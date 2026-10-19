#!/usr/bin/env python3
"""FTrap export - SQLite DB -> JSON files for the FRITZ!Box DNS filter dashboard.

Reads the collector database read-only (``file:...?mode=ro``, no copying) and
writes to ``data/`` next to index.html:

  ftrap.json        tiles, filter lists, warnings, collector health
  series_day.json   24 h,    15-minute buckets
  series_week.json  7 days,  hourly buckets
  series_month.json 30 days, daily buckets (local days, see FTRAP_TZ)

Increment logic: ``dnsfilter_stats.blocked/total`` are counters since the last
box restart. Delta = value - previous value; if a counter drops (restart), the
delta is the value itself (the counter started at 0). Both counters are treated
as reset together so the blocked delta never exceeds the total delta. Gaps are
not interpolated: the delta belongs to the interval of the newer snapshot. Rows
containing NULL are skipped (the previous value is kept). The first snapshot
has no delta.

Stdlib only. Robust: missing table / empty data -> JSON with a ``notes`` entry,
no crash. CLI: python3 export.py [--db PATH] [--out DIR]
Environment: FTRAP_DB (default DB path; else $XDG_DATA_HOME/ftrap/ftrap.db or
~/.local/share/ftrap/ftrap.db), FTRAP_TZ (IANA zone for daily buckets,
default: local time of the host).
"""

import argparse
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(os.environ["FTRAP_TZ"]) if os.environ.get("FTRAP_TZ") else None
except Exception:  # unknown zone / tzdata missing -> host local time
    TZ = None

BASE_DIR = Path(__file__).resolve().parent


def default_db_path():
    """FTRAP_DB, else $XDG_DATA_HOME/ftrap/ftrap.db, else ~/.local/share/ftrap/ftrap.db."""
    if os.environ.get("FTRAP_DB"):
        return Path(os.environ["FTRAP_DB"]).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg and Path(xdg).expanduser().is_absolute() \
        else Path.home() / ".local" / "share"
    return base / "ftrap" / "ftrap.db"


DB_SRC = default_db_path()
OUT_DIR = BASE_DIR / "data"

STALE_COLLECTOR_S = 900            # collector data older than this -> warning
DEFAULT_LIST_MAX_AGE_S = 48 * 3600  # used when the interval is missing
EXPECTED_TOP_KEYS = frozenset([
    "automaticUpdate", "clients", "domains", "enabled",
    "filterlists", "manualUpdate", "profiles", "statistics",
])

# name -> (file name, bucket kind, bucket count)
SERIES = {
    "day": ("series_day.json", "15min", 96),
    "week": ("series_week.json", "hour", 168),
    "month": ("series_month.json", "day", 30),
}
STEP_S = {"15min": 900, "hour": 3600}


def _stamp() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg):
    print(f"[{_stamp()}] {msg}", flush=True)


def warn(msg):
    print(f"[{_stamp()}] WARN {msg}", file=sys.stderr, flush=True)


# --- Time ---------------------------------------------------------------------

def local_dt(ts, tz=None):
    tz = tz or TZ
    return datetime.datetime.fromtimestamp(ts, tz) if tz else datetime.datetime.fromtimestamp(ts)


def local_midnight(d, tz=None):
    """Epoch of local midnight for a date (DST-safe)."""
    tz = tz or TZ
    dt = datetime.datetime(d.year, d.month, d.day, tzinfo=tz) if tz \
        else datetime.datetime(d.year, d.month, d.day)
    return int(dt.timestamp())


def today_start(now, tz=None):
    return local_midnight(local_dt(now, tz).date(), tz)


def bucket_key(ts, kind, tz=None):
    if kind == "day":
        return local_midnight(local_dt(ts, tz).date(), tz)
    step = STEP_S[kind]
    return ts - ts % step


def bucket_starts(kind, count, now, tz=None):
    """Ascending bucket start times; the last bucket contains ``now``."""
    if kind == "day":
        today = local_dt(now, tz).date()
        return [local_midnight(today - datetime.timedelta(days=i), tz)
                for i in range(count - 1, -1, -1)]
    step = STEP_S[kind]
    end = now - now % step
    return [end - i * step for i in range(count - 1, -1, -1)]


# --- Increments ------------------------------------------------------------------

def compute_deltas(rows):
    """rows: [(ts, blocked, total)] ascending. Returns [(ts, d_blocked, d_total)].

    See module docstring (reset, gaps, NULL).
    """
    out = []
    prev = None
    for ts, blocked, total in rows:
        if not isinstance(blocked, (int, float)) or not isinstance(total, (int, float)):
            continue
        if prev is not None:
            pb, pt = prev
            if blocked < pb or total < pt:      # box restart
                db, dt = blocked, total
            else:
                db, dt = blocked - pb, total - pt
            out.append((ts, db, dt))
        prev = (blocked, total)
    return out


def aggregate(deltas, kind, count, now, tz=None):
    starts = bucket_starts(kind, count, now, tz)
    acc = {s: [0, 0, False] for s in starts}
    for ts, db, dt in deltas:
        k = bucket_key(ts, kind, tz)
        if k in acc:
            a = acc[k]
            a[0] += db
            a[1] += dt
            a[2] = True
    points = []
    for s in starts:
        b, t, has = acc[s]
        if not has:
            points.append({"ts": s, "blocked": None, "allowed": None,
                           "total": None, "pct": None})
        else:
            points.append({"ts": s, "blocked": b, "allowed": max(0, t - b),
                           "total": t, "pct": round(b / t * 100, 2) if t > 0 else None})
    return points


def sum_since(deltas, since_ts):
    b = t = 0
    n = 0
    for ts, db, dt in deltas:
        if ts >= since_ts:
            b += db
            t += dt
            n += 1
    return {"blocked": b, "total": t, "intervals": n,
            "pct": round(b / t * 100, 3) if t > 0 else None}


# --- List warning logic -----------------------------------------------------------

def list_warnings(lst, interval_s, auto_enabled, now):
    """lst: dict (columns of dnsfilter_lists). Returns a list of codes:
    'status' (latest_status != success), 'stale' (too old / never), 'not_ready'."""
    reasons = []
    if lst.get("latest_status") != "success":
        reasons.append("status")
    if lst.get("is_ready") == 0:
        reasons.append("not_ready")
    if auto_enabled != 0:   # no age alarm when auto-update is disabled
        limit = 2 * interval_s if isinstance(interval_s, (int, float)) and interval_s > 0 \
            else DEFAULT_LIST_MAX_AGE_S
        last = lst.get("last_success_ts")
        if not last or now - last > limit:
            reasons.append("stale")
    return reasons


def drift_info(top_keys_json):
    if not top_keys_json:
        return None
    try:
        keys = set(json.loads(top_keys_json))
    except (ValueError, TypeError):
        return {"missing": [], "added": [], "unparseable": True}
    missing = sorted(EXPECTED_TOP_KEYS - keys)
    added = sorted(keys - EXPECTED_TOP_KEYS)
    return {"missing": missing, "added": added} if (missing or added) else None


# --- DB -------------------------------------------------------------------------

def has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table','view')",
                        (name,)).fetchone() is not None


def fetch_rows(conn, since_ts):
    """Snapshots from since_ts on plus the immediate predecessor (for the first delta)."""
    prev = conn.execute(
        "SELECT ts, blocked, total FROM dnsfilter_stats WHERE ts < ? ORDER BY ts DESC LIMIT 1",
        (since_ts,)).fetchone()
    rows = conn.execute(
        "SELECT ts, blocked, total FROM dnsfilter_stats WHERE ts >= ? ORDER BY ts",
        (since_ts,)).fetchall()
    return ([prev] if prev else []) + rows


def build(conn, now, tz=None):
    """Returns (ftrap_dict, {name: series_dict}). Does not crash on missing data."""
    notes = []
    base = {"generated_at": _stamp(), "now_ts": now, "db_available": True,
            "available": False, "notes": notes}
    empty_series = {}
    for name, (_f, kind, count) in SERIES.items():
        empty_series[name] = {"generated_at": base["generated_at"], "kind": kind,
                              "first_ts": None, "partial": True, "points": []}

    if not has_table(conn, "dnsfilter_stats"):
        notes.append("table_missing:dnsfilter_stats")
        base["lists"] = {"available": False, "items": []}
        return base, empty_series
    first_ts, n_rows = conn.execute("SELECT MIN(ts), COUNT(*) FROM dnsfilter_stats").fetchone()
    if not n_rows:
        notes.append("no_snapshots")
        base["lists"] = {"available": False, "items": []}
        return base, empty_series

    # allow/deny counters exist only in databases written by newer collectors
    have = {r[1] for r in conn.execute("PRAGMA table_info(dnsfilter_stats)")}
    ex_cols = ", ".join(c if c in have else "NULL" for c in ("n_domains_allow", "n_domains_deny"))
    last = conn.execute(
        "SELECT ts, enabled, blocked, total, auto_update_enabled, auto_update_interval, "
        "auto_update_last_ts, manual_update_last_ts, n_clients, n_domains, n_profiles, top_keys, "
        + ex_cols + " FROM dnsfilter_stats ORDER BY ts DESC LIMIT 1").fetchone()
    (l_ts, enabled, l_blocked, l_total, au_en, au_int, au_last, man_last,
     n_clients, n_domains, n_profiles, top_keys, n_allow, n_deny) = last

    # compute increments once over the largest window (30 local days)
    month_start = bucket_starts("day", SERIES["month"][2], now, tz)[0]
    deltas = compute_deltas(fetch_rows(conn, month_start))

    series = {}
    for name, (_f, kind, count) in SERIES.items():
        pts = aggregate(deltas, kind, count, now, tz)
        series[name] = {"generated_at": base["generated_at"], "kind": kind,
                        "first_ts": first_ts, "partial": first_ts > pts[0]["ts"],
                        "points": pts}

    t0 = today_start(now, tz)
    today = sum_since(deltas, t0)
    today["since_ts"] = t0
    today["effective_since_ts"] = max(t0, first_ts)

    # Lists
    lists = {"available": False, "items": [], "entries_active": None}
    if has_table(conn, "dnsfilter_lists"):
        cur = conn.execute("SELECT * FROM dnsfilter_lists ORDER BY name")
        cols = [c[0] for c in cur.description]
        items, entries = [], 0
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            reasons = list_warnings(d, au_int, au_en, now)
            if d.get("enabled"):
                entries += d.get("entry_count") or 0
            items.append({
                "name": d.get("name"), "url": d.get("url"),
                "enabled": bool(d.get("enabled")), "action": d.get("action"),
                "is_ready": d.get("is_ready"), "entry_count": d.get("entry_count"),
                "last_success_ts": d.get("last_success_ts"),
                "latest_status": d.get("latest_status"), "latest_ts": d.get("latest_ts"),
                "latest_error": d.get("latest_error"), "latest_cause": d.get("latest_cause"),
                "warnings": reasons,
            })
        lists = {"available": True, "items": items, "entries_active": entries}
    else:
        notes.append("table_missing:dnsfilter_lists")

    # Collector health
    age = now - l_ts if l_ts else None
    collector = {"last_ts": l_ts, "age_s": age,
                 "stale": age is None or age > STALE_COLLECTOR_S,
                 "last_note": None, "last_error": None}
    if has_table(conn, "poller_health"):
        r = conn.execute("SELECT ts, success, note FROM poller_health WHERE tier='DNSF' "
                         "ORDER BY ts DESC LIMIT 1").fetchone()
        if r:
            collector["last_note"] = {"ts": r[0], "success": r[1], "note": r[2]}
        r = conn.execute("SELECT ts, note FROM poller_health WHERE tier='DNSF' AND success=0 "
                         "ORDER BY ts DESC LIMIT 1").fetchone()
        if r:
            collector["last_error"] = {"ts": r[0], "note": r[1]}

    pct = lambda b, t: round(b / t * 100, 3) if t else None
    base.update({
        "available": True,
        "first_ts": first_ts,
        "filter_enabled": bool(enabled) if enabled is not None else None,
        "today": today,
        "since_restart": {"blocked": l_blocked, "total": l_total, "pct": pct(l_blocked, l_total)
                          if isinstance(l_blocked, (int, float)) and isinstance(l_total, (int, float)) else None},
        "lists": lists,
        "auto_update": {"enabled": None if au_en is None else bool(au_en),
                        "interval_s": au_int, "last_ts": au_last, "manual_last_ts": man_last},
        "exceptions": {"n_domains": n_domains, "n_allow": n_allow, "n_deny": n_deny},
        "counts": {"clients": n_clients, "profiles": n_profiles},
        "collector": collector,
        "drift": drift_info(top_keys),
    })
    return base, series


def atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run(db_src, out_dir):
    now = int(time.time())
    out_dir = Path(out_dir)
    db_src = Path(db_src)
    if not db_src.exists():
        warn(f"DB missing: {db_src}")
        atomic_write_json(out_dir / "ftrap.json", {
            "generated_at": _stamp(), "now_ts": now, "db_available": False, "notes": ["db_missing"]})
        return 1
    try:
        conn = sqlite3.connect(db_src.resolve().as_uri() + "?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error as e:
        warn(f"DB not readable: {e}")
        atomic_write_json(out_dir / "ftrap.json", {
            "generated_at": _stamp(), "now_ts": now, "db_available": False, "notes": ["db_unreadable"]})
        return 1
    try:
        data, series = build(conn, now)
    except sqlite3.Error as e:
        warn(f"Query failed: {e}")
        atomic_write_json(out_dir / "ftrap.json", {
            "generated_at": _stamp(), "now_ts": now, "db_available": False,
            "notes": [f"query_error:{e}"]})
        return 1
    finally:
        conn.close()
    atomic_write_json(out_dir / "ftrap.json", data)
    for name, (fname, _k, _c) in SERIES.items():
        atomic_write_json(out_dir / fname, series[name])
        log(f"{fname}: {len(series[name]['points'])} buckets")
    log(f"ftrap.json written (available={data['available']}, notes={data['notes']})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="FTrap DB->JSON export")
    ap.add_argument("--db", type=Path, default=DB_SRC, help=f"default: $FTRAP_DB or {DB_SRC}")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help=f"default: {OUT_DIR}")
    args = ap.parse_args(argv)
    t0 = time.time()
    rc = run(args.db, args.out)
    log(f"done in {time.time() - t0:.1f}s (rc={rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
