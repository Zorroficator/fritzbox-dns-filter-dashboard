#!/usr/bin/env python3
"""FRITZ!Box DNS filter collector.

Polls the DNS filter status of a FRITZ!Box (``GET /api/v0/<path>``) and stores
counters and filter list metadata in a local SQLite database.

Requirements and caveats
  * FRITZ!OS has no read-only permission. The user needs the right "FRITZ!Box
    Settings", which includes write access. Use a dedicated user for this
    only, disable "Access from the Internet" for it and treat the credentials
    like an admin password.
  * The endpoint exists from FRITZ!OS 8.50 and in 8.4x lab firmware (beta API, undocumented). The path may
    change with the firmware; the box answers HTTP 400 "permission denied"
    even for unknown paths (error code 3002 "bad path" on 8.50; an expired
    session ID is reported as HTTP 400 with code 3001). Therefore several
    paths can be configured and are tried in order (first success wins).
  * Python >= 3.11, standard library only.

Privacy rules (deliberate)
  * The raw response is never stored, logged or printed.
  * Of ``clients`` / ``domains`` / ``profiles`` only the number of entries is
    kept, never their content. For ``domains`` the entries are additionally
    counted by ``action`` (allow / deny) and ``enabled``; the domain names are never
    read. Of ``statistics`` only the field names are kept, never the values.
  * JSON errors are logged with the response length only.
  * Responses larger than 2 MB are rejected.
  * The password is never logged.

Environment
  FTRAP_USER / FTRAP_PASSWORD  credentials (take precedence over credentials_file)
  FTRAP_DB                     database path (overrides db_path; default
                               $XDG_DATA_HOME/ftrap/ftrap.db or ~/.local/share/ftrap/ftrap.db)
  A config file is optional: with these variables set, --config can be omitted.

Usage
  python3 ftrap_collector.py --config config.toml          # run forever
  python3 ftrap_collector.py --config config.toml --once   # single run

A credentials file readable by group/others is rejected (exit 2) unless
--allow-insecure-credentials is given. Redirects from the box are never followed.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import sqlite3
import stat
import sys
import threading
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fritz_auth import AuthError, FritzAuth, build_box_opener  # noqa: E402

log = logging.getLogger("ftrap")

MAX_BYTES = 2_000_000
SECS_PER_DAY = 86400
DEFAULTS: dict[str, Any] = {
    "box_url": "http://fritz.box",
    "credentials_file": "~/.config/ftrap/credentials",
    "db_path": None,  # None -> default_db_path(); relative values: repository root
    "ca_file": None,  # optional PEM file to trust for https to the box
    "interval_seconds": 180,
    "timeout_seconds": 10,
    "paths": ["beta/dnsfilter", "generic/dnsfilter"],
    "retention_days": 730,
}

# ── Parsing ───────────────────────────────────────────────────────────────────

_missing_logged: set[str] = set()


def _note_missing(what: str) -> None:
    """Report a missing/renamed field only once per process (no log spam)."""
    if what not in _missing_logged:
        _missing_logged.add(what)
        log.info("DNS filter: field '%s' missing or unexpected type -> NULL", what)


def _in_int64(val: int, label: str) -> int | None:
    """SQLite stores signed 64-bit integers; anything else becomes NULL."""
    if -(2 ** 63) <= val < 2 ** 63:
        return val
    _note_missing(label + " (out of int64 range)")
    return None


def _get_int(obj: Any, key: str, label: str) -> int | None:
    val = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return _in_int64(val, label)
    if isinstance(val, float):
        if math.isfinite(val):
            return _in_int64(int(val), label)
        _note_missing(label + " (non-finite number)")
        return None
    if isinstance(val, str):
        try:
            return _in_int64(int(val.strip()), label)
        except ValueError:
            pass
    _note_missing(label)
    return None


def _get_str(obj: Any, key: str, label: str, maxlen: int = 500) -> str | None:
    val = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(val, str):
        return val[:maxlen]
    if val is None:
        _note_missing(label)
        return None
    if isinstance(val, float) and not math.isfinite(val):
        _note_missing(label + " (non-finite number)")
        return None
    if isinstance(val, (int, float, bool)):
        return str(val)[:maxlen]
    _note_missing(label)
    return None


def _get_len(obj: Any, key: str) -> int | None:
    """Number of entries of a list/dict field - never its content."""
    val = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(val, (list, dict)):
        return len(val)
    _note_missing(key)
    return None


def _count_actions(obj: Any, key: str) -> tuple[int | None, int | None, int | None]:
    """Count list entries by ``action`` and ``enabled`` - only counters.

    Only the fields ``action`` and ``enabled`` are read. Returns
    (allow, deny, disabled). ``action`` is case-insensitive; unknown or missing
    actions are counted in neither allow nor deny. Disabled entries are still
    counted in allow/deny. disabled = entries with ``enabled`` False/0/"0"/"false";
    a missing or null ``enabled`` does NOT count as disabled.
    Not a list -> (None, None, None).
    """
    val = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(val, list):
        return None, None, None
    allow = deny = disabled = 0
    for entry in val:
        if not isinstance(entry, dict):
            continue
        action = entry.get("action")
        if isinstance(action, str):
            action = action.strip().lower()
            if action == "allow":
                allow += 1
            elif action == "deny":
                deny += 1
        en = entry.get("enabled")
        if en is not None:  # null behaves like a missing field: not disabled
            if isinstance(en, str):
                en = en.strip().lower() not in ("", "0", "false")
            if not en:
                disabled += 1
    return allow, deny, disabled


def _stats_keys(data: dict) -> list[str] | None:
    """Field names of ``statistics`` (one level deep, dict children prefixed) - never values.

    Sorted, names truncated to 100 characters, at most 50 entries. Not a dict -> None.
    """
    stats = data.get("statistics")
    if not isinstance(stats, dict):
        return None
    names: set[str] = set()
    for k, v in stats.items():
        names.add(str(k)[:100])
        if isinstance(v, dict):
            names.update(f"{k}.{c}"[:100] for c in v.keys())
    return sorted(names)[:50]


def _parse_list(item: Any) -> dict | None:
    """Reduce one filter list to the allowed fields (None if unusable)."""
    if not isinstance(item, dict):
        _note_missing("filterlists[]")
        return None
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    latest = item.get("latestUpdate") if isinstance(item.get("latestUpdate"), dict) else {}
    err = latest.get("error")
    err_txt = None
    if isinstance(err, dict):
        msg, code = err.get("message"), err.get("code")
        if code in (0, "0"):  # code 0 means "no error"
            code = None
        parts = [str(p) for p in (code, msg) if p not in (None, "")]
        err_txt = ": ".join(parts)[:200] or None
    elif isinstance(err, str) and err:
        err_txt = err[:200]
    cause = latest.get("cause")
    uid = _get_str(item, "UID", "filterlists.UID", 200)
    if not uid:
        return None  # no primary key
    return {
        "uid": uid,
        "name": _get_str(item, "name", "filterlists.name", 200),
        "url": _get_str(item, "url", "filterlists.url", 500),
        "enabled": _get_int(item, "enabled", "filterlists.enabled"),
        "action": _get_str(item, "action", "filterlists.action", 100),
        "is_ready": _get_int(status, "isReady", "filterlists.status.isReady"),
        "entry_count": _get_int(status, "entryCount", "filterlists.status.entryCount"),
        "last_success_ts": _get_int(status, "lastSuccessfulUpdateTimestamp",
                                    "filterlists.status.lastSuccessfulUpdateTimestamp"),
        "latest_status": _get_str(latest, "status", "filterlists.latestUpdate.status", 100),
        "latest_ts": _get_int(latest, "timestamp", "filterlists.latestUpdate.timestamp"),
        "latest_error": err_txt,
        "latest_cause": str(cause)[:200] if cause not in (None, "") else None,
    }


def parse_dnsfilter(data: Any, path: str) -> dict:
    """Turn the raw response into the filtered result dict (field-wise tolerant)."""
    if not isinstance(data, dict):
        raise ValueError("DNS filter response is not a JSON object")
    stats = data.get("statistics") if isinstance(data.get("statistics"), dict) else {}
    qc = stats.get("dnsQueryCount") if isinstance(stats.get("dnsQueryCount"), dict) else {}
    if not qc:
        _note_missing("statistics.dnsQueryCount")
    auto = data.get("automaticUpdate") if isinstance(data.get("automaticUpdate"), dict) else {}
    manual = data.get("manualUpdate") if isinstance(data.get("manualUpdate"), dict) else {}
    raw_lists = data.get("filterlists")
    if not isinstance(raw_lists, list):
        _note_missing("filterlists")
        raw_lists = []
    lists = [p for p in (_parse_list(i) for i in raw_lists) if p is not None]
    n_allow, n_deny, n_disabled = _count_actions(data, "domains")
    return {
        "path": path,
        "enabled": _get_int(data, "enabled", "enabled"),
        "blocked": _get_int(qc, "blocked", "dnsQueryCount.blocked"),
        "total": _get_int(qc, "total", "dnsQueryCount.total"),
        "auto_update_enabled": _get_int(auto, "enabled", "automaticUpdate.enabled"),
        "auto_update_interval": _get_int(auto, "interval", "automaticUpdate.interval"),
        "auto_update_last_ts": _get_int(auto, "lastTimestamp", "automaticUpdate.lastTimestamp"),
        "manual_update_last_ts": _get_int(manual, "lastTimestamp", "manualUpdate.lastTimestamp"),
        # counts only - content of clients/domains/profiles is never touched
        "n_clients": _get_len(data, "clients"),
        "n_domains": _get_len(data, "domains"),
        "n_domains_allow": n_allow,
        "n_domains_deny": n_deny,
        "n_domains_disabled": n_disabled,
        "n_profiles": _get_len(data, "profiles"),
        "top_keys": sorted(str(k) for k in data.keys()),
        "stats_keys": _stats_keys(data),
        "lists": lists,
    }


# ── Fetching ──────────────────────────────────────────────────────────────────

def _is_expired_sid(exc: urllib.error.HTTPError) -> bool:
    """True for an error response with code 3001 or "permission denied" (reads <= 4000 bytes).

    The box reports an expired session ID as HTTP 400 with code 3001 (code 3002 means
    "bad path" and is no reason to log in again). The error body is never logged.
    """
    try:
        body = json.loads(exc.read(4000).decode("utf-8", "replace"))
    except (ValueError, OSError, AttributeError):
        return False
    items: list = []
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        errs = body.get("errors")
        items = [body] + (errs if isinstance(errs, list) else [])
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("code")) == "3001":
            return True
        msg = it.get("message")
        if isinstance(msg, str) and "permission denied" in msg.lower():
            return True
    return False


def _fetch(box_url: str, auth: FritzAuth, path: str, timeout: float,
           opener: urllib.request.OpenerDirector | None = None) -> Any:
    """One GET on /api/v0/<path>. 401/403 -> new SID + one retry.

    HTTP 400 with code 3001 / "permission denied" (how the box reports an expired SID)
    also gets exactly one new SID + retry; every other 400 is a hard error.
    """
    url = f"{box_url.rstrip('/')}/api/v0/{path.lstrip('/')}"
    opener = opener or auth.opener

    def _get(sid: str) -> bytes:
        req = urllib.request.Request(url, headers={
            "Authorization": f"AVM-SID {sid}",
            "Accept": "application/json",
        })
        with opener.open(req, timeout=timeout) as resp:
            return resp.read(MAX_BYTES + 1)

    try:
        raw = _get(auth.ensure_sid())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            log.debug("DNS filter %s: HTTP %d - renewing SID and retrying", path, exc.code)
            raw = _get(auth.get_sid())
        elif exc.code == 400 and _is_expired_sid(exc):
            log.debug("DNS filter %s: HTTP 400 (code 3001) - renewing SID and retrying", path)
            raw = _get(auth.get_sid())
        else:
            raise
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Response larger than {MAX_BYTES} bytes")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        # never log the content (privacy), only the length
        raise ValueError(
            f"JSON error (response length {len(raw)} bytes): {type(exc).__name__}") from None


def _scrub(text: str, box_url: str) -> str:
    """Keep the box URL out of messages that end up in the database."""
    base = box_url.rstrip("/")
    if base:
        text = text.replace(base, "<box>")
    try:
        parsed = urlparse(box_url)
        host, netloc = parsed.hostname, parsed.netloc
    except ValueError:
        host = netloc = None
    for needle in (netloc, host):  # netloc first: it contains the host
        if needle:
            text = text.replace(needle, "<box>")
    return text


def collect_dnsfilter(box_url: str, auth: FritzAuth, paths: list[str],
                      timeout: float = 10) -> dict:
    """Try ``paths`` in order; return the filtered dict, never the raw response."""
    errors: list[str] = []
    for path in paths:
        try:
            return parse_dnsfilter(_fetch(box_url, auth, path, timeout), path)
        except urllib.error.HTTPError as exc:
            errors.append(f"{path}: HTTP {exc.code}")
        except Exception as exc:
            errors.append(f"{path}: {_scrub(str(exc), box_url)[:120]}")
    raise RuntimeError("DNS filter not available - " + "; ".join(errors) if errors
                       else "DNS filter: no paths configured")


# ── Database ──────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS poller_health (
    ts               INTEGER PRIMARY KEY,
    tier             TEXT,
    response_time_ms INTEGER,
    success          INTEGER,
    backoff_active   INTEGER,
    note             TEXT
);

CREATE TABLE IF NOT EXISTS dnsfilter_stats (
    ts                   INTEGER PRIMARY KEY,
    enabled              INTEGER,
    blocked              INTEGER,   -- counter since box restart
    total                INTEGER,   -- counter since box restart
    auto_update_enabled  INTEGER,
    auto_update_interval INTEGER,
    auto_update_last_ts  INTEGER,
    manual_update_last_ts INTEGER,
    n_clients            INTEGER,
    n_domains            INTEGER,
    n_profiles           INTEGER,
    source_path          TEXT,
    top_keys             TEXT       -- sorted top-level keys (structure drift)
);  -- n_domains_allow/_deny/_disabled and stats_keys: see STATS_MIGRATIONS

CREATE TABLE IF NOT EXISTS dnsfilter_lists (
    uid             TEXT PRIMARY KEY,
    name            TEXT,
    url             TEXT,
    enabled         INTEGER,
    action          TEXT,
    is_ready        INTEGER,
    entry_count     INTEGER,
    last_success_ts INTEGER,
    latest_status   TEXT,
    latest_ts       INTEGER,
    latest_error    TEXT,
    latest_cause    TEXT,
    first_seen_ts   INTEGER,
    observed_ts     INTEGER
);

-- Run history per filter list: the box does not fill manualUpdate.lastTimestamp,
-- only latestUpdate per list is reliable (dnsfilter_lists is an upsert without history).
CREATE TABLE IF NOT EXISTS dnsfilter_list_updates (
    uid             TEXT    NOT NULL,
    latest_ts       INTEGER NOT NULL,   -- latestUpdate.timestamp of the box
    latest_cause    TEXT,
    latest_status   TEXT,
    last_success_ts INTEGER,
    first_seen_ts   INTEGER,            -- snapshot ts in which the run was first seen
    PRIMARY KEY (uid, latest_ts)
);
"""


# Columns added after the first release; appended by _migrate() (idempotent).
STATS_MIGRATIONS = (
    ("n_domains_allow", "INTEGER"),
    ("n_domains_deny", "INTEGER"),
    ("n_domains_disabled", "INTEGER"),
    ("stats_keys", "TEXT"),  # JSON list of statistics field names (drift check, no values)
)

LIST_UPDATES_RETENTION_DAYS = 90  # fixed, independent of retention_days


class Database:
    def __init__(self, path: str | Path) -> None:
        if str(path) != ":memory:":
            parent = Path(path).parent
            parent_new = not parent.exists()
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if parent_new:
                os.chmod(parent, 0o700)  # mkdir mode is masked by umask
            # Pre-create the file as 0600 so the WAL/SHM files inherit it.
            # Existing files and directories are left untouched.
            if not Path(path).exists():
                os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
        self._conn = sqlite3.connect(str(path))
        cur = self._conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=5000;")
        cur.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add missing columns to dnsfilter_stats; existing data stays untouched."""
        have = {r[1] for r in self._conn.execute("PRAGMA table_info(dnsfilter_stats)")}
        for name, decl in STATS_MIGRATIONS:  # static names, no injection
            if name not in have:
                self._conn.execute(f"ALTER TABLE dnsfilter_stats ADD COLUMN {name} {decl}")

    def close(self) -> None:
        self._conn.close()

    def rollback(self) -> None:
        self._conn.rollback()

    def log_health(self, tier: str, response_time_ms: int, success: bool,
                   backoff_active: bool = False, note: str = "") -> None:
        """ts is the primary key: on collision retry with ts+1 (never overwrite)."""
        ts = int(time.time())
        cur = self._conn.cursor()
        for attempt in range(10):
            cur.execute(
                "INSERT OR IGNORE INTO poller_health VALUES (?,?,?,?,?,?)",
                (ts + attempt, tier, response_time_ms, int(success),
                 int(backoff_active), note),
            )
            if cur.rowcount == 1:
                break
        else:
            log.warning("poller_health: 10 collisions in a row, entry %s dropped", tier)
        self._conn.commit()

    def insert_dnsfilter(self, ts: int, d: dict) -> None:
        """Write one snapshot (dnsfilter_stats) and upsert all filter lists."""
        cur = self._conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO dnsfilter_stats "
            "(ts, enabled, blocked, total, auto_update_enabled, auto_update_interval, "
            "auto_update_last_ts, manual_update_last_ts, n_clients, n_domains, n_profiles, "
            "source_path, top_keys, n_domains_allow, n_domains_deny, n_domains_disabled, "
            "stats_keys) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, d.get("enabled"), d.get("blocked"), d.get("total"),
             d.get("auto_update_enabled"), d.get("auto_update_interval"),
             d.get("auto_update_last_ts"), d.get("manual_update_last_ts"),
             d.get("n_clients"), d.get("n_domains"), d.get("n_profiles"),
             d.get("path"), json.dumps(d.get("top_keys") or []),
             d.get("n_domains_allow"), d.get("n_domains_deny"), d.get("n_domains_disabled"),
             None if d.get("stats_keys") is None else json.dumps(d["stats_keys"])),
        )
        for lst in d.get("lists") or []:
            self._upsert_list(cur, lst, ts)
            self._record_update(cur, lst, ts)
        self._conn.commit()

    @staticmethod
    def _upsert_list(cur, lst: dict, now: int) -> None:
        """One row per ``uid`` (no history); first_seen_ts is preserved."""
        cur.execute(
            "INSERT INTO dnsfilter_lists "
            "(uid, name, url, enabled, action, is_ready, entry_count, last_success_ts, "
            "latest_status, latest_ts, latest_error, latest_cause, first_seen_ts, observed_ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(uid) DO UPDATE SET "
            "name=excluded.name, url=excluded.url, enabled=excluded.enabled, "
            "action=excluded.action, is_ready=excluded.is_ready, "
            "entry_count=excluded.entry_count, last_success_ts=excluded.last_success_ts, "
            "latest_status=excluded.latest_status, latest_ts=excluded.latest_ts, "
            "latest_error=excluded.latest_error, latest_cause=excluded.latest_cause, "
            "observed_ts=excluded.observed_ts",
            (lst["uid"], lst.get("name"), lst.get("url"), lst.get("enabled"),
             lst.get("action"), lst.get("is_ready"), lst.get("entry_count"),
             lst.get("last_success_ts"), lst.get("latest_status"), lst.get("latest_ts"),
             lst.get("latest_error"), lst.get("latest_cause"), now, now),
        )

    @staticmethod
    def _record_update(cur, lst: dict, now: int) -> None:
        """Keep every observed list run (uid, latest_ts).

        INSERT OR IGNORE: the first observation stays (its status may still be preliminary).
        Only a real integer latest_ts other than 0 is recorded.
        """
        lts = lst.get("latest_ts")
        if not isinstance(lts, int) or isinstance(lts, bool) or lts == 0:
            return
        cur.execute(
            "INSERT OR IGNORE INTO dnsfilter_list_updates "
            "(uid, latest_ts, latest_cause, latest_status, last_success_ts, first_seen_ts) "
            "VALUES (?,?,?,?,?,?)",
            (lst["uid"], lts, lst.get("latest_cause"), lst.get("latest_status"),
             lst.get("last_success_ts"), now),
        )

    def run_retention(self, retention_days: int, now: int | None = None) -> dict:
        """Delete old rows of dnsfilter_stats, poller_health and dnsfilter_list_updates.

        dnsfilter_lists is kept on purpose: one row per list, no history.
        dnsfilter_list_updates is pruned after a fixed 90 days (not retention_days); the
        newest row per uid always stays, otherwise the next snapshot (the box still
        reports the same latestUpdate) would re-insert it and the history would flicker.
        """
        now = now if now is not None else int(time.time())
        cutoff = now - retention_days * SECS_PER_DAY
        cur = self._conn.cursor()
        result = {}
        for table in ("poller_health", "dnsfilter_stats"):  # static names, no injection
            cur.execute(f"DELETE FROM {table} WHERE ts < ?", (cutoff,))
            result[table] = cur.rowcount
        cur.execute(
            "DELETE FROM dnsfilter_list_updates WHERE latest_ts < ? AND latest_ts < "
            "(SELECT MAX(u2.latest_ts) FROM dnsfilter_list_updates u2 "
            "WHERE u2.uid = dnsfilter_list_updates.uid)",
            (now - LIST_UPDATES_RETENTION_DAYS * SECS_PER_DAY,))
        result["dnsfilter_list_updates"] = cur.rowcount
        self._conn.commit()
        return result


# ── Configuration ─────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent


def default_db_path() -> Path:
    """$XDG_DATA_HOME/ftrap/ftrap.db, else ~/.local/share/ftrap/ftrap.db."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg and Path(xdg).expanduser().is_absolute() \
        else Path.home() / ".local" / "share"
    return base / "ftrap" / "ftrap.db"


def resolve_db_path(value: str | Path) -> Path:
    """Expand ~; relative paths are relative to the repository root."""
    p = Path(str(value)).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


def load_config(path: str | Path | None) -> dict:
    cfg = dict(DEFAULTS)
    if path:
        with open(path, "rb") as fh:
            cfg.update(tomllib.load(fh))
    paths = cfg["paths"]
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("'paths' must be a list of strings")
    if os.environ.get("FTRAP_DB"):  # environment overrides the config file
        cfg["db_path"] = os.environ["FTRAP_DB"]
    cfg["db_path"] = str(resolve_db_path(cfg["db_path"] or default_db_path()))
    if cfg.get("ca_file"):
        cfg["ca_file"] = str(Path(str(cfg["ca_file"])).expanduser())
    cfg["interval_seconds"] = max(10, int(cfg["interval_seconds"]))
    cfg["timeout_seconds"] = float(cfg["timeout_seconds"])
    cfg["retention_days"] = int(cfg["retention_days"])
    return cfg


def load_credentials(cfg: dict, allow_insecure: bool = False) -> tuple[str, str]:
    """Environment (FTRAP_USER/FTRAP_PASSWORD) first, then the credentials file."""
    user, password = os.environ.get("FTRAP_USER"), os.environ.get("FTRAP_PASSWORD")
    if user and password:
        return user, password
    cred = Path(str(cfg["credentials_file"])).expanduser()
    try:
        mode = stat.S_IMODE(cred.stat().st_mode)
        if mode & 0o077:
            msg = f"Credentials file {cred} has mode {mode:o}; restrict it with chmod 600"
            if not allow_insecure:
                raise AuthError(msg + " (or pass --allow-insecure-credentials)")
            log.warning(msg)
        text = cred.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthError(f"Cannot read credentials file {cred}: {exc.strerror}") from exc
    return parse_credentials(text)


def parse_credentials(text: str) -> tuple[str, str]:
    """Accept 'user line + password line' or 'username:/login:/user: ...' + 'password: ...'."""
    lines = text.splitlines()
    keyed: dict[str, str] = {}
    for line in lines:
        k, sep, v = line.partition(":")
        if sep and k.strip().lower() in ("username", "login", "user", "password"):
            keyed[k.strip().lower()] = v.strip()
    user = next((keyed[k] for k in ("username", "login", "user") if keyed.get(k)), "")
    if user and keyed.get("password"):
        return user, keyed["password"]
    if len(lines) < 2 or not lines[0].strip() or not lines[1]:
        raise AuthError("Credentials file needs user name on line 1 and password on line 2 "
                        "(or 'username: ...' / 'password: ...')")
    return lines[0].strip(), lines[1].rstrip("\r\n")


# ── Run loop ──────────────────────────────────────────────────────────────────

def run_once(cfg: dict, auth: FritzAuth, db: Database) -> bool:
    """One collection run. Failures are recorded in poller_health (tier DNSF)."""
    t0 = time.monotonic()
    try:
        res = collect_dnsfilter(cfg["box_url"], auth, list(cfg["paths"]),
                                cfg["timeout_seconds"])
        ms = int((time.monotonic() - t0) * 1000)
        db.insert_dnsfilter(int(time.time()), res)
        db.log_health("DNSF", ms, True, False, "")
        log.info("ok - %s/%s blocked, %d lists in %.1fs",
                 res["blocked"], res["total"], len(res["lists"]), ms / 1000)
        return True
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        log.warning("failed (%.1fs): %s", ms / 1000, _scrub(str(exc), cfg["box_url"]))
        try:
            db.rollback()  # never commit a half-written snapshot with the health row
            db.log_health("DNSF", ms, False, False,
                          _scrub(str(exc), cfg["box_url"])[:200])
        except Exception as dexc:
            log.warning("health row not writable: %s", dexc)
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Collect FRITZ!Box DNS filter statistics into SQLite.")
    ap.add_argument("--config", help="path to the TOML configuration file")
    ap.add_argument("--once", action="store_true", help="run a single collection and exit")
    ap.add_argument("--allow-insecure-credentials", action="store_true",
                    help="accept a credentials file readable by group/others")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        cfg = load_config(args.config)
        user, password = load_credentials(cfg, args.allow_insecure_credentials)
        auth = FritzAuth(cfg["box_url"], user, password, cfg["timeout_seconds"],
                         cfg.get("ca_file"))
    except (OSError, ValueError, AuthError, tomllib.TOMLDecodeError) as exc:
        log.error("configuration error: %s", exc)
        return 2

    db = Database(cfg["db_path"])

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    try:
        if args.once:
            return 0 if run_once(cfg, auth, db) else 1
        next_retention = 0.0
        while not stop.is_set():
            if time.time() >= next_retention:
                try:
                    log.info("retention: %s", db.run_retention(cfg["retention_days"]))
                except sqlite3.Error as exc:
                    log.warning("retention failed: %s", exc)
                next_retention = time.time() + SECS_PER_DAY
            run_once(cfg, auth, db)
            stop.wait(cfg["interval_seconds"])
        log.info("stopped")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
