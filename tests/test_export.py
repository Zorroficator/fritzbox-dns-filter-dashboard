import time
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import export  # noqa: E402

BER = ZoneInfo("Europe/Berlin")


def ts(y, mo, d, h=0, mi=0):
    import datetime
    return int(datetime.datetime(y, mo, d, h, mi, tzinfo=BER).timestamp())


def mkdb(rows=None, lists=None, health=None, with_stats=True, with_lists=True):
    conn = sqlite3.connect(":memory:")
    if with_stats:
        conn.execute("CREATE TABLE dnsfilter_stats(ts INTEGER PRIMARY KEY, enabled INT, blocked INT, total INT,"
                     "auto_update_enabled INT, auto_update_interval INT, auto_update_last_ts INT,"
                     "manual_update_last_ts INT, n_clients INT, n_domains INT, n_profiles INT,"
                     "source_path TEXT, top_keys TEXT)")
        for r in rows or []:
            t, b, tot = r[:3]
            enabled = r[3] if len(r) > 3 else 1
            conn.execute("INSERT INTO dnsfilter_stats VALUES(?,?,?,?,1,86400,0,0,0,2,0,'x',?)",
                         (t, enabled, b, tot, '["' + '","'.join(sorted(export.EXPECTED_TOP_KEYS)) + '"]'))
    if with_lists:
        conn.execute("CREATE TABLE dnsfilter_lists(uid TEXT PRIMARY KEY, name TEXT, url TEXT, enabled INT, action TEXT,"
                     "is_ready INT, entry_count INT, last_success_ts INT, latest_status TEXT, latest_ts INT,"
                     "latest_error TEXT, latest_cause TEXT, first_seen_ts INT, observed_ts INT)")
        for i, l in enumerate(lists or []):
            conn.execute("INSERT INTO dnsfilter_lists VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,0)", (f"l{i}",) + l)
    conn.execute("CREATE TABLE poller_health(tier TEXT, ts INT, success INT, note TEXT)")
    for hrow in health or []:
        conn.execute("INSERT INTO poller_health VALUES(?,?,?,?)", hrow)
    return conn


class Deltas(unittest.TestCase):
    def test_simple(self):
        d = export.compute_deltas([(1, 10, 100), (2, 15, 130), (3, 15, 140)])
        self.assertEqual(d, [(2, 5, 30), (3, 0, 10)])

    def test_restart_counter_reset(self):
        d = export.compute_deltas([(1, 100, 1000), (2, 4, 50)])
        self.assertEqual(d, [(2, 4, 50)])

    def test_reset_if_only_total_drops(self):
        d = export.compute_deltas([(1, 10, 100), (2, 12, 90)])
        self.assertEqual(d, [(2, 12, 90)])

    def test_gap_not_interpolated(self):
        d = export.compute_deltas([(0, 0, 0), (10000, 50, 500)])
        self.assertEqual(d, [(10000, 50, 500)])

    def test_null_skipped(self):
        d = export.compute_deltas([(1, 10, 100), (2, None, None), (3, 20, 150), (4, 20, None)])
        self.assertEqual(d, [(3, 10, 50)])

    def test_first_has_no_delta(self):
        self.assertEqual(export.compute_deltas([(1, 5, 5)]), [])
        self.assertEqual(export.compute_deltas([]), [])


class Buckets(unittest.TestCase):
    def test_day_boundary_local(self):
        now = ts(2026, 10, 18, 12, 0)
        # 23:59 previous day and 00:01 today -> different day buckets
        deltas = [(ts(2026, 10, 17, 23, 59), 1, 10), (ts(2026, 10, 18, 0, 1), 2, 20)]
        pts = export.aggregate(deltas, "day", 30, now, BER)
        self.assertEqual(len(pts), 30)
        self.assertEqual(pts[-1]["total"], 20)
        self.assertEqual(pts[-2]["total"], 10)
        self.assertEqual(pts[-1]["ts"], ts(2026, 10, 18))
        self.assertIsNone(pts[0]["total"])

    def test_dst_day_buckets(self):
        now = ts(2026, 10, 27, 12, 0)   # after the DST change on Oct 25
        starts = export.bucket_starts("day", 5, now, BER)
        self.assertEqual(starts, [ts(2026, 10, d) for d in (23, 24, 25, 26, 27)])
        self.assertEqual(starts[3] - starts[2], 25 * 3600)

    def test_15min_and_pct(self):
        now = ts(2026, 10, 18, 12, 7)
        d = [(ts(2026, 10, 18, 12, 1), 5, 50), (ts(2026, 10, 18, 12, 14), 5, 50)]
        pts = export.aggregate(d, "15min", 96, now, BER)
        self.assertEqual(pts[-1]["blocked"], 10)
        self.assertEqual(pts[-1]["allowed"], 90)
        self.assertEqual(pts[-1]["pct"], 10.0)

    def test_today_start(self):
        now = ts(2026, 10, 18, 12, 0)
        self.assertEqual(export.today_start(now, BER), ts(2026, 10, 18))
        s = export.sum_since([(ts(2026, 10, 17, 23, 59), 1, 10), (ts(2026, 10, 18, 0, 3), 2, 20)],
                             export.today_start(now, BER))
        self.assertEqual((s["blocked"], s["total"], s["pct"]), (2, 20, 10.0))


class ListWarn(unittest.TestCase):
    NOW = 1_000_000

    def lst(self, **kw):
        d = {"latest_status": "success", "is_ready": 1, "last_success_ts": self.NOW - 3600}
        d.update(kw)
        return d

    def test_ok(self):
        self.assertEqual(export.list_warnings(self.lst(), 86400, 1, self.NOW), [])

    def test_status(self):
        self.assertIn("status", export.list_warnings(self.lst(latest_status="failed"), 86400, 1, self.NOW))

    def test_stale_2x_interval(self):
        self.assertIn("stale", export.list_warnings(self.lst(last_success_ts=self.NOW - 2 * 86400 - 1), 86400, 1, self.NOW))
        self.assertEqual(export.list_warnings(self.lst(last_success_ts=self.NOW - 2 * 86400 + 60), 86400, 1, self.NOW), [])

    def test_no_interval_48h(self):
        self.assertIn("stale", export.list_warnings(self.lst(last_success_ts=self.NOW - 49 * 3600), None, 1, self.NOW))
        self.assertEqual(export.list_warnings(self.lst(last_success_ts=self.NOW - 47 * 3600), None, 1, self.NOW), [])

    def test_never_succeeded(self):
        self.assertIn("stale", export.list_warnings(self.lst(last_success_ts=None), 86400, 1, self.NOW))

    def test_not_ready(self):
        self.assertIn("not_ready", export.list_warnings(self.lst(is_ready=0), 86400, 1, self.NOW))


class Build(unittest.TestCase):
    def test_missing_stats_table(self):
        conn = mkdb(with_stats=False)
        data, series = export.build(conn, ts(2026, 10, 18, 12), BER)
        self.assertFalse(data["available"])
        self.assertIn("table_missing:dnsfilter_stats", data["notes"])
        self.assertEqual(series["day"]["points"], [])

    def test_empty_tables(self):
        conn = mkdb(rows=[])
        data, series = export.build(conn, ts(2026, 10, 18, 12), BER)
        self.assertIn("no_snapshots", data["notes"])
        self.assertFalse(data["available"])

    def test_missing_lists_table(self):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 10), (now - 120, 2, 20)], with_lists=False)
        data, _ = export.build(conn, now, BER)
        self.assertTrue(data["available"])
        self.assertIn("table_missing:dnsfilter_lists", data["notes"])

    def test_full_with_restart_and_stale_collector(self):
        now = ts(2026, 10, 18, 12)
        rows = [(now - 4000, 100, 1000), (now - 3800, 110, 1100), (now - 3600, 3, 40)]
        conn = mkdb(rows=rows, lists=[("L", "http://x/y", 1, "deny", 1, 500, now - 100, "success", now - 100, None, None)],
                    health=[("DNSF", now - 3500, 0, "boom"), ("DNSF", now - 3600, 1, "")])
        data, series = export.build(conn, now, BER)
        self.assertEqual(data["today"]["total"], 100 + 40)
        self.assertEqual(data["today"]["blocked"], 10 + 3)
        self.assertTrue(data["collector"]["stale"])
        self.assertEqual(data["collector"]["last_error"]["note"], "boom")
        self.assertEqual(data["lists"]["entries_active"], 500)
        self.assertTrue(series["day"]["partial"])
        self.assertEqual(sum(p["total"] or 0 for p in series["day"]["points"]), 140)

    def test_predecessor_before_window_used(self):
        now = ts(2026, 10, 18, 12)
        old = now - 40 * 86400
        conn = mkdb(rows=[(old, 5, 50), (now - 600, 8, 80), (now - 300, 9, 90)])
        data, _ = export.build(conn, now, BER)
        # the (old) predecessor provides the reference for the first delta in the window
        self.assertEqual(data["today"]["total"], 40)

    def test_effective_since(self):
        now = ts(2026, 10, 18, 18, 0)
        conn = mkdb(rows=[(ts(2026, 10, 18, 17, 55), 1, 10), (now - 60, 2, 20)])
        data, _ = export.build(conn, now, BER)
        self.assertEqual(data["today"]["since_ts"], ts(2026, 10, 18))
        self.assertEqual(data["today"]["effective_since_ts"], ts(2026, 10, 18, 17, 55))
        conn = mkdb(rows=[(ts(2026, 10, 17, 9), 1, 10), (now - 60, 2, 20)])
        data, _ = export.build(conn, now, BER)
        self.assertEqual(data["today"]["effective_since_ts"], ts(2026, 10, 18))

    def test_filter_off_and_drift(self):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 1, 0)])
        conn.execute("UPDATE dnsfilter_stats SET top_keys='[\"enabled\",\"newthing\"]'")
        data, _ = export.build(conn, now, BER)
        self.assertFalse(data["filter_enabled"])
        self.assertIn("newthing", data["drift"]["added"])
        self.assertIn("clients", data["drift"]["missing"])

    def test_default_db_path_outside_repo(self):
        self.assertNotIn(Path(export.__file__).resolve().parent, export.default_db_path().parents)

    def test_run_with_real_file_special_chars(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "dir with space#and?q" / "t.db"
            p.parent.mkdir()
            now = int(time.time())
            src = mkdb(rows=[(now - 600, 1, 1), (now - 300, 2, 3)])
            src.commit()
            dst = sqlite3.connect(str(p))
            src.backup(dst)
            dst.close()
            self.assertEqual(export.run(p, Path(d) / "out"), 0)
            self.assertTrue((Path(d) / "out" / "ftrap.json").exists())

    def test_run_missing_db(self):
        with tempfile.TemporaryDirectory() as d:
            rc = export.run(Path(d) / "nope.db", Path(d) / "out")
            self.assertEqual(rc, 1)
            self.assertTrue((Path(d) / "out" / "ftrap.json").exists())


class ExceptionsExport(unittest.TestCase):
    def test_old_db_without_columns_gives_null(self):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 1)])   # old schema: no n_domains_allow/deny
        data, _ = export.build(conn, now, BER)
        self.assertEqual(data["exceptions"], {"n_domains": 2, "n_allow": None, "n_deny": None})

    def test_new_columns_exported(self):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 1)])
        conn.execute("ALTER TABLE dnsfilter_stats ADD COLUMN n_domains_allow INTEGER")
        conn.execute("ALTER TABLE dnsfilter_stats ADD COLUMN n_domains_deny INTEGER")
        conn.execute("UPDATE dnsfilter_stats SET n_domains_allow=1, n_domains_deny=1")
        data, _ = export.build(conn, now, BER)
        self.assertEqual(data["exceptions"], {"n_domains": 2, "n_allow": 1, "n_deny": 1})
        self.assertEqual(set(data["auto_update"]),
                         {"enabled", "interval_s", "last_ts", "manual_last_ts"})


if __name__ == "__main__":
    unittest.main()
