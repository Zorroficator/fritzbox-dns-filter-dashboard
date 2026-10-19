#!/usr/bin/env python3
"""Generate synthetic demo data for the FTrap dashboard (stdlib only).

Builds a temporary SQLite database with the collector schema (dnsfilter_stats,
dnsfilter_lists, poller_health), fills it with 30 days of plausible fake
counters (snapshot every 180 s, day/night curve, one simulated box restart with
a counter reset), runs export.py on it and marks ftrap.json with ``demo: true``.
All timestamps are relative to "now"; ftrap.json also carries exported_at so the
page can shift them client-side and the static demo never looks stale.

Usage: python3 demo/make_sample.py [--out DIR]   (default: ./data)
"""

import argparse
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
        "source_path TEXT, top_keys TEXT, n_domains_allow INT, n_domains_deny INT)")
    conn.execute(
        "CREATE TABLE dnsfilter_lists(uid TEXT PRIMARY KEY, name TEXT, url TEXT, enabled INT, action TEXT,"
        "is_ready INT, entry_count INT, last_success_ts INT, latest_status TEXT, latest_ts INT,"
        "latest_error TEXT, latest_cause TEXT, first_seen_ts INT, observed_ts INT)")
    conn.execute("CREATE TABLE poller_health(tier TEXT, ts INT, success INT, note TEXT)")


def fill(conn, now, seed=42):
    rng = random.Random(seed)
    start = (now - DAYS * 86400) // STEP * STEP
    restart_ts = int(now - RESTART_DAYS_AGO * 86400)
    top_keys = json.dumps(sorted(export.EXPECTED_TOP_KEYS))
    blocked = total = 0
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
        stats.append((ts, 1, blocked, total, 1, 28800, now - 3 * 3600, now - 5 * 86400,
                      7, 4, 3, "demo", top_keys, 3, 1))
        health.append(("DNSF", ts, 1, "ok"))
        ts += STEP
    conn.executemany("INSERT INTO dnsfilter_stats VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", stats)
    conn.executemany("INSERT INTO poller_health VALUES(?,?,?,?)", health)
    lists = [
        ("demo-1", "Example Blocklist", "https://lists.example.org/blocklists/example-blocklist.txt",
         1, "deny", 1, 312_480, now - 3 * 3600, "success", now - 3 * 3600, None, None, start, now),
        ("demo-2", "Example Tracker List", "https://lists.example.org/trackers/hosts.txt",
         1, "deny", 1, 48_215, now - 3 * 3600, "success", now - 3 * 3600, None, None, start, now),
    ]
    conn.executemany("INSERT INTO dnsfilter_lists VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lists)
    conn.commit()


def shift_ts(o, delta):
    """Shift every ``ts`` / ``*_ts`` value in a JSON structure by delta seconds."""
    if isinstance(o, list):
        for x in o:
            shift_ts(x, delta)
    elif isinstance(o, dict):
        for k, v in o.items():
            if (k == "ts" or k.endswith("_ts")) and isinstance(v, (int, float)):
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
    print(f"demo data written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
