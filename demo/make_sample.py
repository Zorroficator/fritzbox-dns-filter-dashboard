#!/usr/bin/env python3
"""Generate synthetic demo data for the FTrap dashboard (stdlib only).

Builds a temporary SQLite database with the collector schema (dnsfilter_stats,
dnsfilter_lists, dnsfilter_list_updates, poller_health), fills it with 30 days of plausible fake
counters (snapshot every 180 s, day/night curve, one simulated box restart with
a counter reset), runs export.py on it and marks ftrap.json with ``demo: true``.
All timestamps are relative to "now"; ftrap.json also carries exported_at so the
page can shift them client-side and the static demo never looks stale.

It also writes dns_top.json and dns_live.json (fictional devices and domains, format of
docs/dns_contract.md, marked ``demo: true`` with ``exported_at``) for the optional DNS section.

Usage: python3 demo/make_sample.py [--out DIR]   (default: ./data)
"""

import argparse
import datetime
import json
import math
import random
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import export  # noqa: E402

STEP = 180                  # seconds between snapshots
DAYS = 30
RESTART_DAYS_AGO = 11.3     # simulated box restart (counters fall back to ~0)
REQUESTS_PER_DAY = 120_000
UPDATE_INTERVAL = 8 * 3600  # automatic list update every 8 h
LAST_AUTO_AGO = 3 * 3600    # most recent automatic run
MANUAL_RUNS_AGO = (19.4 * 86400, 1.3 * 86400)  # two manual runs ("update now" clicks)
STATS_KEYS = json.dumps(sorted(export.EXPECTED_STATS_KEYS))


def rate_factor(ts):
    """Relative request rate for a timestamp: low at night, peaks in the evening."""
    hour = (ts % 86400) / 3600.0
    base = 0.35 + 0.65 * (0.5 - 0.5 * math.cos((hour - 4.0) / 24.0 * 2 * math.pi))
    evening = 0.35 * math.exp(-((hour - 20.0) ** 2) / 8.0)
    return base + evening


def create_schema(conn):
    conn.execute(
        "CREATE TABLE dnsfilter_stats(ts INTEGER PRIMARY KEY, enabled INT, blocked INT, total INT,"
        "auto_update_enabled INT, auto_update_interval INT, auto_update_last_ts INT,"
        "manual_update_last_ts INT, n_clients INT, n_domains INT, n_profiles INT,"
        "source_path TEXT, top_keys TEXT, n_domains_allow INT, n_domains_deny INT,"
        "n_domains_disabled INT, stats_keys TEXT)")
    conn.execute(
        "CREATE TABLE dnsfilter_lists(uid TEXT PRIMARY KEY, name TEXT, url TEXT, enabled INT, action TEXT,"
        "is_ready INT, entry_count INT, last_success_ts INT, latest_status TEXT, latest_ts INT,"
        "latest_error TEXT, latest_cause TEXT, first_seen_ts INT, observed_ts INT)")
    conn.execute(
        "CREATE TABLE dnsfilter_list_updates(uid TEXT NOT NULL, latest_ts INTEGER NOT NULL,"
        "latest_cause TEXT, latest_status TEXT, last_success_ts INT, first_seen_ts INT,"
        "PRIMARY KEY (uid, latest_ts))")
    conn.execute("CREATE TABLE poller_health(tier TEXT, ts INT, success INT, note TEXT)")


def fill(conn, now, seed=42):
    rng = random.Random(seed)
    start = (now - DAYS * 86400) // STEP * STEP
    restart_ts = int(now - RESTART_DAYS_AGO * 86400)
    top_keys = json.dumps(sorted(export.EXPECTED_TOP_KEYS))
    blocked = total = 0
    last_auto = now - LAST_AUTO_AGO
    auto_runs = []                                  # every 8 h back to the start of the sample
    t = last_auto
    while t >= start:
        auto_runs.append(t)
        t -= UPDATE_INTERVAL
    auto_runs.sort()
    run_idx = 0
    ts = start
    last_snapshot = now - 60
    stats, health = [], []
    while ts <= last_snapshot:
        if ts >= restart_ts > ts - STEP:          # simulated restart: counters start from 0
            blocked = total = 0
        mean = REQUESTS_PER_DAY / (86400 / STEP) * rate_factor(ts) / 0.74
        n = max(0, int(rng.gauss(mean, mean * 0.18)))
        share = min(0.12, max(0.03, rng.gauss(0.065, 0.012)))
        b = int(n * share)
        total += n
        blocked += b
        while run_idx + 1 < len(auto_runs) and auto_runs[run_idx + 1] <= ts:
            run_idx += 1
        auto_last = auto_runs[run_idx] if auto_runs and auto_runs[run_idx] <= ts else 0
        # manualUpdate.lastTimestamp stays 0 on the real box; manual runs only show up
        # in dnsfilter_list_updates
        stats.append((ts, 1, blocked, total, 1, UPDATE_INTERVAL, auto_last, 0,
                      7, 4, 3, "demo", top_keys, 3, 1, 0, STATS_KEYS))
        health.append(("DNSF", ts, 1, "ok"))
        ts += STEP
    conn.executemany("INSERT INTO dnsfilter_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", stats)
    conn.executemany("INSERT INTO poller_health VALUES(?,?,?,?)", health)
    lists = [
        ("demo-1", "Example Blocklist", "https://lists.example.org/blocklists/example-blocklist.txt",
         1, "deny", 1, 312_480, last_auto, "success", last_auto, None, "automatic", start, now),
        ("demo-2", "Example Tracker List", "https://lists.example.org/trackers/hosts.txt",
         1, "deny", 1, 48_215, last_auto, "success", last_auto, None, "automatic", start, now),
    ]
    conn.executemany("INSERT INTO dnsfilter_lists VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lists)
    # run history as the collector writes it: one row per list and run
    updates = []
    for i, (uid, *_rest) in enumerate(lists):
        for t in auto_runs:
            updates.append((uid, t + i * 4, "automatic", "success", t + i * 4, t + i * 4 + 60))
        for ago in MANUAL_RUNS_AGO:
            t = int(now - ago)
            updates.append((uid, t + i * 4, "manual", "success", t + i * 4, t + i * 4 + 60))
    conn.executemany("INSERT INTO dnsfilter_list_updates VALUES(?,?,?,?,?,?)", updates)
    conn.commit()


# --- optional DNS section (dns_top.json / dns_live.json) ------------------------------------------
DNS_STEP = 600              # bucket width in seconds (contract)
DNS_BUCKETS = 144           # 24 h
DNS_NULL_BUCKETS = 4        # "no data yet" buckets at the start of the capture
# name, relative activity, blocked share
DNS_DEVICES = [
    ("living-room-tv", 0.22, 0.16), ("laptop-1", 0.20, 0.08), ("phone-a", 0.16, 0.10),
    ("phone-b", 0.12, 0.09), ("tablet", 0.08, 0.11), ("printer", 0.02, 0.02),
    ("smart-speaker", 0.09, 0.14), ("game-console", 0.11, 0.10),
]
# fictional domains only: example.com / .net / .org and *.invalid
DNS_PERMITTED = [
    "www.example.com", "cdn.example.net", "api.example.org", "video.example.net", "mail.example.org",
    "updates.example.com", "img.example.com", "static.example.org", "music.example.net",
    "docs.example.org", "games.example.com", "time.example.net", "push.example.net", "shop.example.com",
]
DNS_BLOCKED = [
    "ads.tracker-1.invalid", "metrics.example.com", "telemetry.example.net", "pixel.ads-2.invalid",
    "beacon.example.org", "sdk.tracker-3.invalid", "stats.example.net", "adserver.example.com",
    "events.tracker-4.invalid", "analytics.example.org", "banner.ads-5.invalid", "collect.example.net",
]
DNS_QTYPES = [("A", 58.0), ("AAAA", 30.0), ("HTTPS", 8.0), ("PTR", 2.0), ("SRV", 1.0), ("TXT", 1.0)]


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(timespec="seconds")


def _weighted_counts(names, total, rng, share):
    """Zipf-like counts for a top list; the 10 entries together carry ``share`` of ``total``."""
    weights = [1.0 / (i + 1) ** 0.9 * rng.uniform(0.85, 1.15) for i in range(len(names))]
    scale = total * share / sum(weights[:10])
    rows = [{"qname": n, "n": max(1, int(w * scale))} for n, w in zip(names, weights)]
    rows.sort(key=lambda r: -r["n"])
    return rows[:10]


def make_dns(out, now, seed=42):
    """Write synthetic dns_top.json and dns_live.json (fictional data, see docs/dns_contract.md)."""
    rng = random.Random(seed + 1)
    end = now // DNS_STEP * DNS_STEP
    start = end - (DNS_BUCKETS - 1) * DNS_STEP
    cap_start = start + DNS_NULL_BUCKETS * DNS_STEP
    buckets = []
    series = {name: [0] * DNS_BUCKETS for name, _w, _b in DNS_DEVICES}
    bseries = {name: [0] * DNS_BUCKETS for name, _w, _b in DNS_DEVICES}
    for i in range(DNS_BUCKETS):
        ts = start + i * DNS_STEP
        if i < DNS_NULL_BUCKETS:
            buckets.append({"ts": ts, "allowed": None, "blocked": None, "nxdomain": None, "no_answer": None})
            continue
        total = blocked = 0
        rf = rate_factor(ts)
        for name, weight, share in DNS_DEVICES:
            mean = 130 * weight * rf / 0.74
            if name == "printer" and rng.random() < 0.6:
                mean = 0
            n = max(0, int(rng.gauss(mean, mean * 0.25))) if mean else 0
            b = min(n, int(n * share * 1.25 * rng.uniform(0.7, 1.3)))
            series[name][i], bseries[name][i] = n, b
            total += n
            blocked += b
        nx = min(total - blocked, int(total * rng.uniform(0.005, 0.02)))
        na = rng.randint(1, 3) if rng.random() < 0.15 else 0
        buckets.append({"ts": ts, "allowed": total - blocked, "blocked": blocked, "nxdomain": nx, "no_answer": na})

    valid = [b for b in buckets if b["allowed"] is not None]
    day_allowed = sum(b["allowed"] for b in valid)
    day_blocked = sum(b["blocked"] for b in valid)
    day_nx = sum(b["nxdomain"] for b in valid)
    day_na = sum(b["no_answer"] for b in valid)
    day_total = day_allowed + day_blocked
    day_err = max(1, day_total // 4000)
    dev_total = {n: sum(series[n]) for n, _w, _b in DNS_DEVICES}
    dev_blocked = {n: sum(bseries[n]) for n, _w, _b in DNS_DEVICES}

    order = sorted(dev_total, key=lambda n: -dev_total[n])
    rest_names = order[6:]
    clients = [{"name": n, "total": dev_total[n], "blocked": dev_blocked[n],
                "series": series[n], "blocked_series": bseries[n]} for n in order[:6]]
    rest = {"total": sum(dev_total[n] for n in rest_names), "blocked": sum(dev_blocked[n] for n in rest_names),
            "series": [sum(series[n][i] for n in rest_names) for i in range(DNS_BUCKETS)],
            "blocked_series": [sum(bseries[n][i] for n in rest_names) for i in range(DNS_BUCKETS)]}

    def period(factor):
        total = int(day_total * factor)
        blocked = int(day_blocked * factor)
        nx, na, err = int(day_nx * factor), int(day_na * factor), int(day_err * factor)
        permitted = _weighted_counts(DNS_PERMITTED, total - blocked, rng, 0.6)
        if factor > 1:      # longer periods also show the catch-all domain of the collector
            permitted.append({"qname": "(other)", "n": int((total - blocked) * 0.03)})
            permitted = sorted(permitted, key=lambda r: -r["n"])[:10]
        return {
            "total": total, "blocked": blocked, "active_clients": len(DNS_DEVICES),
            "top_permitted": permitted,
            "top_blocked": _weighted_counts(DNS_BLOCKED, blocked, rng, 0.85),
            "top_clients": [{"name": n, "n": int(dev_total[n] * factor), "blocked": int(dev_blocked[n] * factor)}
                            for n in order],
            "top_clients_blocked": [{"name": n, "n": int(dev_blocked[n] * factor), "total": int(dev_total[n] * factor)}
                                    for n in sorted(order, key=lambda n: -dev_blocked[n])],
            "qtypes": [{"qtype": q, "n": int(total * w / 100), "pct": w} for q, w in DNS_QTYPES],
            "statuses": {"allowed": total - blocked - nx - na - err, "blocked": blocked,
                         "nxdomain": nx, "no_answer": na, "error": err},
        }

    # "today" is simplified to the last 24 h in the demo
    periods = {"today": period(1.0), "7d": period(6.6), "30d": period(27.0)}

    events = []
    ts = now - 1.2
    names = [n for n, _w, _b in DNS_DEVICES]
    weights = [w for _n, w, _b in DNS_DEVICES]
    for _ in range(200):
        r = rng.random()
        status = ("blocked" if r < 0.11 else "nxdomain" if r < 0.125 else "no_answer" if r < 0.13
                  else "error" if r < 0.133 else "allowed")
        qtype = rng.choices([q for q, _w in DNS_QTYPES], [w for _q, w in DNS_QTYPES])[0]
        if status == "blocked":
            qname, reply = rng.choice(DNS_BLOCKED), "blocked"
        elif status == "nxdomain":
            qname, reply = f"unknown-{rng.randint(100, 999)}.example.org", "nxdomain"
        elif status == "no_answer":
            qname, reply = rng.choice(DNS_PERMITTED), "none"
        elif status == "error":
            qname, reply = rng.choice(DNS_PERMITTED), "error"
        else:
            qname = rng.choice(DNS_PERMITTED)
            reply = "nodata" if qtype == "AAAA" and rng.random() < 0.2 else rng.choice(["ip", "ip", "ip", "cname"])
        events.append({
            "ts": round(ts, 3), "name": rng.choices(names, weights)[0], "qname": qname, "qtype": qtype,
            "status": status, "latency_ms": None if status == "no_answer" else round(rng.uniform(2, 40), 1),
            "reply": reply})
        ts -= rng.expovariate(1 / 1.5)

    health = {"connected": True, "last_error": "", "reconnects": 0, "host_errors": 0, "rate_limited": 0,
              "capture_since": float(cap_start), "connected_since": float(cap_start),
              "last_packet_ts": events[0]["ts"]}
    top = {
        "generated": _iso(end), "capture_since": _iso(cap_start), "health": health,
        "series_24h": {"start": start, "step": DNS_STEP, "buckets": buckets},
        "clients_24h": {"start": start, "step": DNS_STEP, "clients": clients, "rest": rest},
        "periods": periods, "demo": True, "exported_at": now,
    }
    live = {"generated": _iso(now), "health": health, "events": events, "demo": True, "exported_at": now}
    export.atomic_write_json(out / "dns_top.json", top)
    export.atomic_write_json(out / "dns_live.json", live)


def shift_ts(o, delta):
    """Shift every ``ts`` / ``*_ts`` value (also ``observed_since``) in a JSON structure."""
    if isinstance(o, list):
        for x in o:
            shift_ts(x, delta)
    elif isinstance(o, dict):
        for k, v in o.items():
            if (k == "ts" or k.endswith("_ts") or k == "observed_since") and isinstance(v, (int, float)):
                o[k] = v + delta
            else:
                shift_ts(v, delta)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate synthetic FTrap demo data")
    ap.add_argument("--out", type=Path, default=ROOT / "data", help="output directory for the JSON files")
    ap.add_argument("--age-seconds", type=int, default=0,
                    help="back-date all timestamps (testing the page's demo time shift)")
    args = ap.parse_args(argv)
    now = int(time.time())
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "demo.db"
        conn = sqlite3.connect(db)
        create_schema(conn)
        fill(conn, now)
        conn.close()
        rc = export.run(db, args.out)
    if rc != 0:
        return rc
    path = args.out / "ftrap.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["demo"] = True
    data["exported_at"] = now   # lets the page shift all timestamps to "now"
    if args.age_seconds:
        data["exported_at"] = now - args.age_seconds
        shift_ts(data, -args.age_seconds)
        for f in ("series_day.json", "series_week.json", "series_month.json"):
            p = args.out / f
            s = json.loads(p.read_text(encoding="utf-8"))
            shift_ts(s, -args.age_seconds)
            export.atomic_write_json(p, s)
    export.atomic_write_json(path, data)
    make_dns(args.out, now - args.age_seconds)
    print(f"demo data written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
