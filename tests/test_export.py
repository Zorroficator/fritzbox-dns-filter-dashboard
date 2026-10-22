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
        self.assertEqual(data["exceptions"], {"n_domains": 2, "n_allow": None, "n_deny": None,
                                              "n_disabled": None})

    def test_new_columns_exported(self):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 1)])
        conn.execute("ALTER TABLE dnsfilter_stats ADD COLUMN n_domains_allow INTEGER")
        conn.execute("ALTER TABLE dnsfilter_stats ADD COLUMN n_domains_deny INTEGER")
        conn.execute("UPDATE dnsfilter_stats SET n_domains_allow=1, n_domains_deny=1")
        data, _ = export.build(conn, now, BER)
        self.assertEqual(data["exceptions"], {"n_domains": 2, "n_allow": 1, "n_deny": 1,
                                              "n_disabled": None})
        self.assertEqual(set(data["auto_update"]),
                         {"enabled", "interval_s", "last_ts", "manual_last_ts"})

    def test_new_columns_null_in_last_row(self):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 1)])
        for c in ("n_domains_allow", "n_domains_deny", "n_domains_disabled"):
            conn.execute(f"ALTER TABLE dnsfilter_stats ADD COLUMN {c} INTEGER")   # stay NULL
        data, _ = export.build(conn, now, BER)
        self.assertEqual(data["exceptions"], {"n_domains": 2, "n_allow": None, "n_deny": None,
                                              "n_disabled": None})

    def _with_new(self, disabled, stats_keys):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 1)])
        conn.execute("ALTER TABLE dnsfilter_stats ADD COLUMN n_domains_disabled INTEGER")
        conn.execute("ALTER TABLE dnsfilter_stats ADD COLUMN stats_keys TEXT")
        conn.execute("UPDATE dnsfilter_stats SET n_domains_disabled=?, stats_keys=?", (disabled, stats_keys))
        return export.build(conn, now, BER)[0]

    def test_disabled_exported(self):
        data = self._with_new(3, None)
        self.assertEqual(data["exceptions"]["n_disabled"], 3)
        self.assertIsNone(data["drift"])   # stats_keys NULL -> no hint

    def test_disabled_null(self):
        self.assertIsNone(self._with_new(None, None)["exceptions"]["n_disabled"])


class StatsKeysDrift(unittest.TestCase):
    OK = '["dnsQueryCount","dnsQueryCount.blocked","dnsQueryCount.total"]'
    TOP = '["' + '","'.join(sorted(export.EXPECTED_TOP_KEYS)) + '"]'

    def test_no_drift(self):
        self.assertIsNone(export.drift_info(self.TOP, self.OK))

    def test_null_or_missing_column(self):
        self.assertIsNone(export.drift_info(self.TOP, None))
        self.assertIsNone(export.drift_info(self.TOP))
        self.assertIsNone(export.drift_info(None, None))

    def test_stats_added_and_missing(self):
        d = export.drift_info(self.TOP, '["dnsQueryCount","dnsQueryCount.blocked","dnsQueryCount.cached"]')
        self.assertEqual(d["stats_added"], ["dnsQueryCount.cached"])
        self.assertEqual(d["stats_missing"], ["dnsQueryCount.total"])
        self.assertEqual((d["missing"], d["added"]), ([], []))

    def test_top_keys_still_work(self):
        d = export.drift_info('["enabled","newthing"]', self.OK)
        self.assertIn("newthing", d["added"])
        self.assertIn("clients", d["missing"])
        self.assertEqual(d["stats_added"] + d["stats_missing"], [])

    def test_unparseable_stats_ignored(self):
        self.assertIsNone(export.drift_info(self.TOP, "{broken"))

    def test_build_drift_from_column(self):
        now = ts(2026, 10, 18, 12)
        conn = mkdb(rows=[(now - 300, 1, 1)])
        conn.execute("ALTER TABLE dnsfilter_stats ADD COLUMN stats_keys TEXT")
        conn.execute("UPDATE dnsfilter_stats SET stats_keys='[\"dnsQueryCount\",\"new\"]'")
        d = export.build(conn, now, BER)[0]["drift"]
        self.assertEqual(d["stats_added"], ["new"])
        self.assertEqual(d["stats_missing"], ["dnsQueryCount.blocked", "dnsQueryCount.total"])


class ListUpdates(unittest.TestCase):
    NOW = ts(2026, 10, 19, 12)

    def test_detect_first_value_and_change(self):
        rows = [(1, 0, 0), (2, 1000, 0), (3, 1000, 0), (4, 5000, 0), (5, 5000, 0)]
        runs = export.detect_runs(rows)
        self.assertEqual(runs, [{"ts": 1000, "kind": "auto"}, {"ts": 5000, "kind": "auto"}])

    def test_detect_zero_and_null_skipped(self):
        rows = [(1, None, None), (2, 0, 0), (3, 700, None), (4, None, 0), (5, 0, 0), (6, 700, 0)]
        self.assertEqual(export.detect_runs(rows), [{"ts": 700, "kind": "auto"}])
        self.assertEqual(export.detect_runs([(1, 0, 0), (2, None, None)]), [])
        self.assertEqual(export.detect_runs([]), [])

    def test_detect_manual_and_dedup(self):
        rows = [(1, 100, 100), (2, 200, 100), (3, 100, 100)]   # fall back to 100 -> duplicate dropped
        runs = export.detect_runs(rows)
        self.assertEqual(runs, [{"ts": 100, "kind": "auto"}, {"ts": 100, "kind": "manual"},
                                {"ts": 200, "kind": "auto"}])

    def test_counts_windows_by_run_ts(self):
        n = self.NOW
        runs = [{"ts": n - 3600, "kind": "auto"}, {"ts": n - 2 * 86400, "kind": "auto"},
                {"ts": n - 10 * 86400, "kind": "manual"}, {"ts": n - 40 * 86400, "kind": "auto"}]
        c = export.run_counts(runs, n)
        self.assertEqual(c["24h"], {"auto": 1, "manual": 0})
        self.assertEqual(c["7d"], {"auto": 2, "manual": 0})
        self.assertEqual(c["30d"], {"auto": 2, "manual": 1})

    def test_next_expected(self):
        runs = [{"ts": 100, "kind": "auto"}, {"ts": 500, "kind": "manual"}, {"ts": 300, "kind": "auto"}]
        self.assertEqual(export.next_expected(runs, 1, 86400), 300 + 86400)
        self.assertIsNone(export.next_expected(runs, 0, 86400))
        self.assertIsNone(export.next_expected(runs, None, 86400))
        self.assertIsNone(export.next_expected(runs, 1, 0))
        self.assertIsNone(export.next_expected([{"ts": 5, "kind": "manual"}], 1, 86400))

    def _build(self, snaps, success, interval=86400, enabled=1):
        """snaps: [(snap_ts, auto, manual)]"""
        n = self.NOW
        conn = mkdb(rows=[(t, 1, 1) for t, _a, _m in snaps],
                    lists=[("L", "http://x", 1, "deny", 1, 5, success, "success", success, None, None)])
        for t, a, m in snaps:
            conn.execute("UPDATE dnsfilter_stats SET auto_update_last_ts=?, manual_update_last_ts=?,"
                         "auto_update_enabled=?, auto_update_interval=? WHERE ts=?", (a, m, enabled, interval, t))
        return export.build(conn, n, BER)[0]

    def test_build_block(self):
        n = self.NOW
        r1, r2 = n - 30 * 3600, n - 6 * 3600
        d = self._build([(n - 40 * 3600, r1, 0), (n - 5 * 3600, r2, 0), (n - 300, r2, 0)], r2)
        lu = d["list_updates"]
        self.assertEqual(lu["observed_since"], n - 40 * 3600)
        self.assertEqual([r["ts"] for r in lu["recent"]], [r2, r1])
        self.assertEqual(lu["counts"]["24h"]["auto"], 1)
        self.assertEqual(lu["counts"]["7d"]["auto"], 2)
        self.assertEqual(lu["next_expected_ts"], r2 + 86400)
        self.assertEqual(lu["interval_s"], 86400)

    def test_next_expected_none_when_auto_off(self):
        n = self.NOW
        d = self._build([(n - 300, n - 3600, 0)], n - 3600, enabled=0)
        self.assertIsNone(d["list_updates"]["next_expected_ts"])

    def test_recent_limited_to_10_newest_first(self):
        n = self.NOW
        snaps = [(n - 20000 + i * 100, n - 15000 + i * 600, 0) for i in range(15)]
        lu = self._build(snaps, n)["list_updates"]
        self.assertEqual(len(lu["recent"]), 10)
        self.assertEqual(lu["recent"][0]["ts"], n - 15000 + 14 * 600)

    def test_no_not_refreshed_warning(self):
        """A list whose last success predates the last run raises no 'not_refreshed' warning."""
        n = self.NOW
        run = n - 3600
        d = self._build([(n - 300, run, 0)], run - 86400)
        self.assertNotIn("not_refreshed", d["lists"]["items"][0]["warnings"])
        self.assertNotIn("not_refreshed", export.list_warnings(
            {"latest_status": "success", "is_ready": 1, "last_success_ts": 1000, "enabled": 1},
            86400, 0, 5000))

    def test_old_db_without_columns(self):
        n = self.NOW
        conn = mkdb(rows=[(n - 300, 1, 1)])
        conn.execute("ALTER TABLE dnsfilter_stats DROP COLUMN auto_update_last_ts")
        conn.execute("ALTER TABLE dnsfilter_stats DROP COLUMN manual_update_last_ts")
        d = export.build(conn, n, BER)[0]
        self.assertEqual(d["list_updates"]["recent"], [])
        self.assertEqual(d["list_updates"]["counts"]["30d"], {"auto": 0, "manual": 0})
        self.assertIsNone(d["auto_update"]["last_ts"])

    def test_old_schema_without_new_columns_and_tables(self):
        """Old schema (no n_domains_disabled / stats_keys / dnsfilter_list_updates): still populated."""
        n = self.NOW
        r = n - 7200
        conn = mkdb(rows=[(n - 3600, 1, 1)])
        conn.execute("UPDATE dnsfilter_stats SET auto_update_last_ts=?", (r,))
        d = export.build(conn, n, BER)[0]
        self.assertEqual(d["list_updates"]["recent"], [{"ts": r, "kind": "auto"}])
        self.assertIsNone(d["exceptions"]["n_disabled"])
        self.assertIsNone(d["drift"])


class ManualHistory(unittest.TestCase):
    NOW = ts(2026, 10, 22, 12)

    def _db(self, entries, stats=True):
        conn = mkdb(rows=[(self.NOW - 300, 1, 1)] if stats else [])
        conn.execute("CREATE TABLE dnsfilter_list_updates(uid TEXT, latest_ts INTEGER, latest_cause TEXT,"
                     "latest_status TEXT, last_success_ts INTEGER, first_seen_ts INTEGER,"
                     "PRIMARY KEY(uid, latest_ts))")
        for uid, t, cause in entries:
            conn.execute("INSERT INTO dnsfilter_list_updates VALUES(?,?,?,'success',?,0)", (uid, t, cause, t))
        return conn

    def test_no_table(self):
        self.assertEqual(export.fetch_manual_runs(mkdb()), [])

    def test_grouping(self):
        t = self.NOW - 86400
        c = self._db([("a", t, "manual"), ("b", t + 60, "manual")])
        self.assertEqual(export.fetch_manual_runs(c), [{"ts": t, "kind": "manual"}])
        c = self._db([("a", t, "manual"), ("b", t + 901, "manual")])
        self.assertEqual([r["ts"] for r in export.fetch_manual_runs(c)], [t, t + 901])
        c = self._db([("a", t, "manual"), ("b", t + 900, "manual")])
        self.assertEqual(len(export.fetch_manual_runs(c)), 1)

    def test_cause_and_ts_filter(self):
        t = self.NOW - 3600
        c = self._db([("a", t, "Manual"), ("b", t + 5000, "auto"), ("c", t + 9000, None),
                      ("d", t + 12000, "other"), ("e", 0, "manual"), ("f", None, "manual")])
        self.assertEqual(export.fetch_manual_runs(c), [{"ts": t, "kind": "manual"}])

    def test_merge_duplicate_with_stats_manual(self):
        runs = [{"ts": 1000, "kind": "auto"}, {"ts": 5000, "kind": "manual"}]
        man = [{"ts": 5300, "kind": "manual"}, {"ts": 20000, "kind": "manual"}]
        self.assertEqual(export.merge_runs(runs, man),
                         [{"ts": 1000, "kind": "auto"}, {"ts": 5000, "kind": "manual"},
                          {"ts": 20000, "kind": "manual"}])
        self.assertEqual(export.merge_runs(runs, []), runs)

    def test_build_with_table(self):
        t = self.NOW - 3600
        d = export.build(self._db([("a", t, "manual"), ("b", t + 30, "manual")]), self.NOW, BER)[0]
        lu = d["list_updates"]
        self.assertEqual(lu["counts"]["24h"], {"auto": 0, "manual": 1})
        self.assertEqual(lu["recent"], [{"ts": t, "kind": "manual"}])
        self.assertEqual(d["auto_update"]["manual_last_ts"], t)

    def test_build_manual_last_keeps_larger_stats_value(self):
        t = self.NOW - 3600
        c = self._db([("a", t, "manual")])
        c.execute("UPDATE dnsfilter_stats SET manual_update_last_ts=?", (t + 100,))
        self.assertEqual(export.build(c, self.NOW, BER)[0]["auto_update"]["manual_last_ts"], t + 100)

    def test_build_without_table_unchanged(self):
        d = export.build(mkdb(rows=[(self.NOW - 300, 1, 1)]), self.NOW, BER)[0]
        self.assertEqual(d["list_updates"]["recent"], [])
        self.assertEqual(d["auto_update"]["manual_last_ts"], 0)


if __name__ == "__main__":
    unittest.main()
