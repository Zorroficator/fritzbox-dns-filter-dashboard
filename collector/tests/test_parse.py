import io
import json
import sqlite3
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ftrap_collector as fc  # noqa: E402

FULL = {
    "enabled": True,
    "statistics": {"dnsQueryCount": {"blocked": 12, "total": 345}},
    "automaticUpdate": {"enabled": True, "interval": 24, "lastTimestamp": 1700000000},
    "manualUpdate": {"lastTimestamp": 1700000500},
    "clients": [{"name": "device-a"}, {"name": "device-b"}],
    "domains": ["example.invalid"],
    "profiles": [],
    "filterlists": [
        {"UID": "list-1", "name": "Example list", "url": "https://example.invalid/l.txt",
         "enabled": True, "action": "block",
         "status": {"isReady": True, "entryCount": 100,
                    "lastSuccessfulUpdateTimestamp": 1700000100},
         "latestUpdate": {"status": "ok", "timestamp": 1700000100,
                          "error": {"code": 0, "message": ""}}},
        {"UID": "list-2", "name": "Broken", "enabled": 0,
         "latestUpdate": {"status": "failed", "cause": "timeout",
                          "error": {"code": 7, "message": "download failed"}}},
        {"name": "no uid"},
        "garbage",
    ],
}


class ParseTests(unittest.TestCase):
    def test_full(self):
        r = fc.parse_dnsfilter(FULL, "beta/dnsfilter")
        self.assertEqual((r["enabled"], r["blocked"], r["total"]), (1, 12, 345))
        self.assertEqual((r["n_clients"], r["n_domains"], r["n_profiles"]), (2, 1, 0))
        self.assertEqual(r["auto_update_interval"], 24)
        self.assertEqual(r["manual_update_last_ts"], 1700000500)
        self.assertEqual(len(r["lists"]), 2)
        self.assertEqual(r["lists"][0]["entry_count"], 100)
        self.assertIn("clients", r["top_keys"])
        # no client/domain content may leak into the result
        self.assertNotIn("device-a", repr(r))

    def test_error_code_zero_is_no_error(self):
        r = fc.parse_dnsfilter(FULL, "p")
        self.assertIsNone(r["lists"][0]["latest_error"])
        self.assertEqual(r["lists"][1]["latest_error"], "7: download failed")
        self.assertEqual(r["lists"][1]["latest_cause"], "timeout")

    def test_missing_fields_are_none(self):
        r = fc.parse_dnsfilter({}, "p")
        for k in ("enabled", "blocked", "total", "n_clients", "n_domains", "n_profiles",
                  "auto_update_enabled", "manual_update_last_ts"):
            self.assertIsNone(r[k], k)
        self.assertEqual(r["lists"], [])
        self.assertEqual(r["top_keys"], [])

    def test_empty_lists(self):
        r = fc.parse_dnsfilter({"clients": [], "domains": [], "profiles": [],
                                "filterlists": []}, "p")
        self.assertEqual((r["n_clients"], r["n_domains"], r["n_profiles"]), (0, 0, 0))
        self.assertEqual(r["lists"], [])

    def test_not_an_object(self):
        with self.assertRaises(ValueError):
            fc.parse_dnsfilter([1, 2], "p")


class SecurityTests(unittest.TestCase):
    def test_non_finite_numbers_become_none(self):
        data = json.loads('{"statistics": {"dnsQueryCount": {"blocked": Infinity, "total": NaN}}}')
        r = fc.parse_dnsfilter(data, "p")
        self.assertIsNone(r["blocked"])
        self.assertIsNone(r["total"])

    def test_redirects_are_refused(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import urllib.error
        from fritz_auth import build_box_opener
        seen = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/target")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                build_box_opener().open(f"http://127.0.0.1:{srv.server_port}/start", timeout=5)
            self.assertEqual(cm.exception.code, 302)
            self.assertEqual(seen, ["/start"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_scrub_removes_box_url(self):
        self.assertNotIn("fritz.example", fc._scrub("x http://fritz.example/api y", "http://fritz.example/"))


class DbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = fc.Database(Path(self.tmp.name) / "t.db")
        self.q = self.db._conn.execute

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_schema_columns(self):
        cols = [r[1] for r in self.q("PRAGMA table_info(dnsfilter_stats)")]
        self.assertEqual(cols[:3], ["ts", "enabled", "blocked"])
        self.assertEqual(cols[-4:], ["n_domains_allow", "n_domains_deny",
                                    "n_domains_disabled", "stats_keys"])
        self.assertEqual(len(self.q("PRAGMA table_info(dnsfilter_lists)").fetchall()), 14)
        self.assertEqual(len(self.q("PRAGMA table_info(poller_health)").fetchall()), 6)

    def test_insert_and_upsert(self):
        res = fc.parse_dnsfilter(FULL, "beta/dnsfilter")
        self.db.insert_dnsfilter(1000, res)
        row = self.q("SELECT ts, blocked, total, n_clients, source_path, top_keys "
                     "FROM dnsfilter_stats").fetchone()
        self.assertEqual(row[:5], (1000, 12, 345, 2, "beta/dnsfilter"))
        self.assertTrue(row[5].startswith("["))
        res["lists"][0]["entry_count"] = 200
        self.db.insert_dnsfilter(2000, res)
        rows = self.q("SELECT uid, entry_count, first_seen_ts, observed_ts "
                      "FROM dnsfilter_lists ORDER BY uid").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ("list-1", 200, 1000, 2000))

    def test_log_health_collision(self):
        for _ in range(3):
            self.db.log_health("T1", 5, True)
            self.db.log_health("DNSF", 5, False, note="x")
        n = self.q("SELECT COUNT(*) FROM poller_health").fetchone()[0]
        self.assertEqual(n, 6)
        self.assertEqual(self.q("SELECT COUNT(*) FROM poller_health "
                                "WHERE tier='DNSF'").fetchone()[0], 3)

    def test_retention(self):
        now = int(time.time())
        old = now - 800 * 86400
        self.db.insert_dnsfilter(old, fc.parse_dnsfilter(FULL, "p"))
        self.db.insert_dnsfilter(now, fc.parse_dnsfilter(FULL, "p"))
        self.q("INSERT INTO poller_health VALUES (?,?,?,?,?,?)", (old, "DNSF", 1, 1, 0, ""))
        self.q("INSERT INTO poller_health VALUES (?,?,?,?,?,?)", (now, "DNSF", 1, 1, 0, ""))
        res = self.db.run_retention(730, now)
        self.assertEqual(res, {"poller_health": 1, "dnsfilter_stats": 1,
                               "dnsfilter_list_updates": 0})
        self.assertEqual(self.q("SELECT COUNT(*) FROM dnsfilter_stats").fetchone()[0], 1)
        # lists are never pruned
        self.assertEqual(self.q("SELECT COUNT(*) FROM dnsfilter_lists").fetchone()[0], 2)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = fc.load_config(None)
        self.assertEqual(cfg["interval_seconds"], 180)
        self.assertEqual(cfg["paths"], ["beta/dnsfilter", "generic/dnsfilter"])
        self.assertEqual(cfg["retention_days"], 730)
        self.assertEqual(Path(cfg["db_path"]), fc.default_db_path())
        self.assertNotIn(fc.REPO_ROOT, Path(cfg["db_path"]).parents)

    def test_default_db_path_xdg(self):
        import os
        old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = "/xdg/data"
        try:
            self.assertEqual(fc.default_db_path(), Path("/xdg/data/ftrap/ftrap.db"))
        finally:
            if old is None:
                del os.environ["XDG_DATA_HOME"]
            else:
                os.environ["XDG_DATA_HOME"] = old

    def test_relative_config_db_path_is_repo_relative(self):
        with tempfile.TemporaryDirectory() as d:
            cfgf = Path(d) / "c.toml"
            cfgf.write_text('db_path = "data/x.db"\n')
            self.assertEqual(Path(fc.load_config(cfgf)["db_path"]), fc.REPO_ROOT / "data" / "x.db")

    def test_insecure_credentials_rejected(self):
        import os
        from fritz_auth import AuthError
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "cred"
            f.write_text("alice\nsecret\n")
            os.chmod(f, 0o644)
            cfg = {"credentials_file": str(f)}
            env = {k: os.environ.pop(k) for k in ("FTRAP_USER", "FTRAP_PASSWORD") if k in os.environ}
            try:
                with self.assertRaises(AuthError):
                    fc.load_credentials(cfg)
                self.assertEqual(fc.load_credentials(cfg, allow_insecure=True), ("alice", "secret"))
                os.chmod(f, 0o600)
                self.assertEqual(fc.load_credentials(cfg), ("alice", "secret"))
                os.chmod(f, 0o644)
                self.assertEqual(fc.main(["--config", str(Path(d) / "none.toml")]), 2)
            finally:
                os.environ.update(env)

    def test_credentials_formats(self):
        self.assertEqual(fc.parse_credentials("alice\nsecret\n"), ("alice", "secret"))
        self.assertEqual(fc.parse_credentials("username: alice\npassword: s3: x\n"),
                         ("alice", "s3: x"))
        self.assertEqual(fc.parse_credentials("login: bob\npassword: pw"), ("bob", "pw"))
        self.assertEqual(fc.parse_credentials("user: carl\npassword: pw"), ("carl", "pw"))
        with self.assertRaises(Exception):
            fc.parse_credentials("only-one-line")

    def test_db_path_resolution(self):
        self.assertEqual(fc.resolve_db_path("/abs/x.db"), Path("/abs/x.db"))
        self.assertEqual(fc.resolve_db_path("a/b.db"), fc.REPO_ROOT / "a" / "b.db")
        self.assertTrue(fc.resolve_db_path("~/x.db").is_absolute())

    def test_db_env_override(self):
        import os
        os.environ["FTRAP_DB"] = "/tmp/x.db"
        try:
            self.assertEqual(fc.load_config(None)["db_path"], "/tmp/x.db")
        finally:
            del os.environ["FTRAP_DB"]


class HardeningTests(unittest.TestCase):
    def test_int64_range(self):
        self.assertIsNone(fc._get_int({"a": 2 ** 70}, "a", "a"))
        self.assertIsNone(fc._get_int({"a": str(2 ** 63)}, "a", "a"))
        self.assertEqual(fc._get_int({"a": 2 ** 63 - 1}, "a", "a"), 2 ** 63 - 1)

    def test_scrub_host_and_netloc(self):
        out = fc._scrub("getaddrinfo failed for fritz.example:49000 / fritz.example",
                        "https://fritz.example:49000/")
        self.assertNotIn("fritz.example", out)
        self.assertNotIn("49000", out)

    def test_run_once_rolls_back_partial_snapshot(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            db = fc.Database(Path(d) / "t.db")
            res = fc.parse_dnsfilter(FULL, "beta/dnsfilter")
            cfg = {"box_url": "http://fritz.example", "paths": ["p"], "timeout_seconds": 1}
            with mock.patch.object(fc, "collect_dnsfilter", return_value=res), \
                 mock.patch.object(fc.Database, "_upsert_list",
                                   side_effect=sqlite3.OperationalError("boom")):
                self.assertFalse(fc.run_once(cfg, None, db))
            c = db._conn
            self.assertEqual(c.execute("SELECT COUNT(*) FROM dnsfilter_stats").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM poller_health").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT success FROM poller_health").fetchone()[0], 0)
            db.close()

    def test_db_permissions(self):
        import stat as st
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "t.db"
            db = fc.Database(p)
            db._conn.execute("PRAGMA user_version=1")
            db._conn.commit()
            self.assertEqual(st.S_IMODE(p.parent.stat().st_mode), 0o700)
            self.assertEqual(st.S_IMODE(p.stat().st_mode), 0o600)
            for suffix in ("-wal", "-shm"):
                q = Path(str(p) + suffix)
                if q.exists():
                    self.assertEqual(st.S_IMODE(q.stat().st_mode), 0o600)
            db.close()


class ActionCountTests(unittest.TestCase):
    def _count(self, domains):
        r = fc.parse_dnsfilter({"domains": domains}, "p")
        return r["n_domains"], r["n_domains_allow"], r["n_domains_deny"]

    def _disabled(self, domains):
        return fc.parse_dnsfilter({"domains": domains}, "p")["n_domains_disabled"]

    def test_allow_deny(self):
        doms = [{"domain": "a.invalid", "action": "allow", "enabled": True},
                {"domain": "b.invalid", "action": "deny", "enabled": True},
                {"domain": "c.invalid", "action": "deny", "enabled": True}]
        self.assertEqual(self._count(doms), (3, 1, 2))

    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(self._count([{"action": "ALLOW"}, {"action": " Deny "}]), (2, 1, 1))

    def test_disabled_entries_are_counted(self):
        self.assertEqual(self._count([{"action": "allow", "enabled": False}]), (1, 1, 0))

    def test_unknown_or_missing_action(self):
        doms = [{"action": "block"}, {"action": None}, {"action": 5}, {}, {"action": "allow"}]
        self.assertEqual(self._count(doms), (5, 1, 0))

    def test_broken_entries_no_crash(self):
        self.assertEqual(self._count(["x", 1, None, ["allow"], {"action": "deny"}]), (5, 0, 1))

    def test_not_a_list(self):
        for bad in ({"a": {"action": "allow"}}, "allow", 3, None):
            self.assertEqual(self._count(bad)[1:], (None, None))
            self.assertIsNone(self._disabled(bad))
        r = fc.parse_dnsfilter({}, "p")
        self.assertEqual((r["n_domains"], r["n_domains_allow"], r["n_domains_deny"],
                          r["n_domains_disabled"]), (None,) * 4)

    def test_disabled_values(self):
        doms = [{"action": "allow", "enabled": False}, {"action": "deny", "enabled": 0},
                {"enabled": "0"}, {"enabled": "false"}, {"enabled": " FALSE "},
                {"action": "allow", "enabled": True}, {"enabled": 1}, {"enabled": "1"},
                {"enabled": "true"}]
        # disabled entries are still counted in allow/deny
        self.assertEqual(self._count(doms), (9, 2, 1))
        self.assertEqual(self._disabled(doms), 5)

    def test_missing_or_null_enabled_is_not_disabled(self):
        self.assertEqual(self._disabled([{"action": "allow"}, {"enabled": None}, "x", None]), 0)

    def test_no_domain_content_in_result(self):
        r = fc.parse_dnsfilter({"domains": [{"domain": "secret.invalid", "action": "allow"}]}, "p")
        self.assertNotIn("secret.invalid", repr(r))


class StatsKeysTests(unittest.TestCase):
    def keys(self, stats):
        return fc.parse_dnsfilter({"statistics": stats}, "p")["stats_keys"]

    def test_normal_no_values(self):
        d = fc.parse_dnsfilter(FULL, "p")
        self.assertEqual(d["stats_keys"],
                         ["dnsQueryCount", "dnsQueryCount.blocked", "dnsQueryCount.total"])
        self.assertNotIn("345", json.dumps(d["stats_keys"]))

    def test_extra_keys(self):
        k = self.keys({"dnsQueryCount": {"total": 1, "cached": 3}, "newScalar": 5,
                       "deep": {"x": {"y": 1}}})
        self.assertEqual(k, ["deep", "deep.x", "dnsQueryCount", "dnsQueryCount.cached",
                             "dnsQueryCount.total", "newScalar"])

    def test_missing_statistics(self):
        self.assertIsNone(fc.parse_dnsfilter({}, "p")["stats_keys"])
        for val in ([1], "x", None):
            self.assertIsNone(self.keys(val))

    def test_limits(self):
        self.assertEqual(len(self.keys({f"k{i:03d}": 1 for i in range(80)})), 50)
        self.assertTrue(all(len(x) <= 100 for x in self.keys({"a" * 300: {"b" * 300: 1}})))

    def test_stored_as_json(self):
        with tempfile.TemporaryDirectory() as d:
            db = fc.Database(Path(d) / "s.db")
            db.insert_dnsfilter(1, fc.parse_dnsfilter(FULL, "p"))
            db.insert_dnsfilter(2, fc.parse_dnsfilter({}, "p"))
            rows = dict(db._conn.execute("SELECT ts, stats_keys FROM dnsfilter_stats"))
            self.assertEqual(json.loads(rows[1]),
                             ["dnsQueryCount", "dnsQueryCount.blocked", "dnsQueryCount.total"])
            self.assertIsNone(rows[2])
            db.close()


class FakeAuth:
    def __init__(self):
        self.opener = None
        self.get_sid_calls = 0

    def ensure_sid(self):
        return "sid0"

    def get_sid(self):
        self.get_sid_calls += 1
        return f"sid{self.get_sid_calls}"


class FakeResp:
    def __init__(self, obj):
        self._raw = json.dumps(obj).encode()

    def read(self, n=-1):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(raw))


class Retry3001Tests(unittest.TestCase):
    def run_fetch(self, errors):
        """errors: exceptions for the first calls, then a valid response."""
        calls = []

        class Opener:
            def open(self, req, timeout=None):
                calls.append(req.get_header("Authorization"))
                if len(calls) <= len(errors):
                    raise errors[len(calls) - 1]
                return FakeResp({"enabled": True})

        auth = FakeAuth()
        try:
            r = fc._fetch("http://fritz.example", auth, "beta/dnsfilter", 5, opener=Opener())
        except urllib.error.HTTPError as exc:
            r = exc
        return r, calls, auth

    def test_retry_code_3001_list(self):
        r, calls, auth = self.run_fetch([http_error(400, [{"code": 3001, "message": "x"}])])
        self.assertEqual(calls, ["AVM-SID sid0", "AVM-SID sid1"])
        self.assertEqual(auth.get_sid_calls, 1)
        self.assertEqual(r, {"enabled": True})

    def test_retry_object_string_code_and_errors_list(self):
        for body in ({"code": "3001"}, {"errors": [{"code": 3001}]}):
            _, calls, _ = self.run_fetch([http_error(400, body)])
            self.assertEqual(len(calls), 2)

    def test_retry_permission_denied_message(self):
        _, calls, _ = self.run_fetch([http_error(400, [{"code": 1, "message": "Permission Denied"}])])
        self.assertEqual(len(calls), 2)

    def test_no_retry_other_code_incl_3002(self):
        for code in (3000, 3002):
            r, calls, auth = self.run_fetch([http_error(400, [{"code": code, "message": "bad path"}])])
            self.assertIsInstance(r, urllib.error.HTTPError)
            self.assertEqual((len(calls), auth.get_sid_calls), (1, 0))

    def test_no_retry_unparseable_or_empty_body(self):
        for body in (b"<html>", b"", b"[]", b"42"):
            r, calls, auth = self.run_fetch([http_error(400, body)])
            self.assertIsInstance(r, urllib.error.HTTPError)
            self.assertEqual(auth.get_sid_calls, 0)

    def test_retry_only_once(self):
        r, calls, auth = self.run_fetch([http_error(400, [{"code": 3001}]),
                                         http_error(400, [{"code": 3001}])])
        self.assertIsInstance(r, urllib.error.HTTPError)
        self.assertEqual((len(calls), auth.get_sid_calls), (2, 1))

    def test_401_still_retried(self):
        _, calls, _ = self.run_fetch([http_error(401, b"")])
        self.assertEqual(len(calls), 2)

    def test_body_read_limited(self):
        from unittest import mock
        exc = http_error(400, b"x" * 100000)
        with mock.patch.object(exc, "read", wraps=exc.read) as rd:
            fc._is_expired_sid(exc)
        rd.assert_called_once_with(4000)


class ListUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = fc.Database(Path(self.tmp.name) / "t.db")
        self.q = self.db._conn.execute

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    @staticmethod
    def lst(uid, lts, **kw):
        d = {"uid": uid, "latest_ts": lts, "latest_cause": "manual", "latest_status": "ok",
             "last_success_ts": lts}
        d.update(kw)
        return d

    def snap(self, ts, *lists):
        self.db.insert_dnsfilter(ts, {"lists": list(lists)})

    def test_columns(self):
        cols = [r[1] for r in self.q("PRAGMA table_info(dnsfilter_list_updates)")]
        self.assertEqual(cols, ["uid", "latest_ts", "latest_cause", "latest_status",
                                "last_success_ts", "first_seen_ts"])

    def test_same_ts_once_first_observation_stays(self):
        self.snap(1000, self.lst("a", 900, latest_status="running"))
        self.snap(2000, self.lst("a", 900))
        rows = self.q("SELECT uid, latest_ts, latest_status, first_seen_ts "
                      "FROM dnsfilter_list_updates").fetchall()
        self.assertEqual(rows, [("a", 900, "running", 1000)])

    def test_new_ts_second_row(self):
        self.snap(1000, self.lst("a", 900))
        self.snap(2000, self.lst("a", 1900))
        rows = self.q("SELECT latest_ts, first_seen_ts FROM dnsfilter_list_updates "
                      "ORDER BY latest_ts").fetchall()
        self.assertEqual(rows, [(900, 1000), (1900, 2000)])

    def test_invalid_ts_skipped(self):
        self.snap(1000, self.lst("a", 0), self.lst("b", None), self.lst("c", True),
                  self.lst("d", "5"), self.lst("e", 1.5))
        self.assertEqual(self.q("SELECT COUNT(*) FROM dnsfilter_list_updates").fetchone()[0], 0)

    def test_parsed_response_feeds_table(self):
        self.db.insert_dnsfilter(1000, fc.parse_dnsfilter(FULL, "p"))
        rows = self.q("SELECT uid, latest_ts, latest_status FROM dnsfilter_list_updates").fetchall()
        self.assertEqual(rows, [("list-1", 1700000100, "ok")])  # list-2 has no timestamp

    def test_retention_90_days_keeps_newest_per_uid(self):
        now = int(time.time())
        d = 86400
        ins = "INSERT INTO dnsfilter_list_updates (uid, latest_ts) VALUES (?, ?)"
        for uid, ts in [("a", now - 200 * d), ("a", now - 150 * d), ("a", now - 10 * d),
                        ("b", now - 200 * d), ("b", now - 95 * d), ("c", now - 89 * d),
                        ("c", now - 91 * d)]:
            self.q(ins, (uid, ts))
        self.db._conn.commit()
        res = self.db.run_retention(730, now)  # retention_days must not matter
        rows = self.q("SELECT uid, latest_ts FROM dnsfilter_list_updates "
                      "ORDER BY uid, latest_ts").fetchall()
        self.assertEqual(rows, [("a", now - 10 * d), ("b", now - 95 * d), ("c", now - 89 * d)])
        self.assertEqual(res["dnsfilter_list_updates"], 4)

    def test_stats_retention_stays_configurable(self):
        now = int(time.time())
        self.db.insert_dnsfilter(now - 100 * 86400, fc.parse_dnsfilter(FULL, "p"))
        self.assertEqual(self.db.run_retention(730, now)["dnsfilter_stats"], 0)
        self.assertEqual(self.db.run_retention(30, now)["dnsfilter_stats"], 1)


class MigrationTests(unittest.TestCase):
    OLD_SCHEMA = ("CREATE TABLE dnsfilter_stats(ts INTEGER PRIMARY KEY, enabled INTEGER, blocked INTEGER,"
                  " total INTEGER, auto_update_enabled INTEGER, auto_update_interval INTEGER,"
                  " auto_update_last_ts INTEGER, manual_update_last_ts INTEGER, n_clients INTEGER,"
                  " n_domains INTEGER, n_profiles INTEGER, source_path TEXT, top_keys TEXT)")

    def _cols(self, path):
        conn = sqlite3.connect(path)
        try:
            return [r[1] for r in conn.execute("PRAGMA table_info(dnsfilter_stats)")]
        finally:
            conn.close()

    def test_old_db_is_migrated_idempotently(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "old.db"
            conn = sqlite3.connect(p)
            conn.execute(self.OLD_SCHEMA)
            conn.execute("INSERT INTO dnsfilter_stats VALUES (100,1,5,50,1,86400,0,0,2,4,1,'x','[]')")
            conn.commit()
            conn.close()
            self.assertNotIn("n_domains_allow", self._cols(p))
            fc.Database(p).close()
            cols = self._cols(p)
            self.assertIn("n_domains_allow", cols)
            self.assertIn("n_domains_deny", cols)
            self.assertEqual(cols[-2:], ["n_domains_disabled", "stats_keys"])
            fc.Database(p).close()  # second init: no error, no duplicate columns
            self.assertEqual(self._cols(p), cols)
            conn = sqlite3.connect(p)
            row = conn.execute("SELECT ts, blocked, total, n_domains, n_domains_allow, n_domains_deny "
                               "FROM dnsfilter_stats").fetchall()
            conn.close()
            self.assertEqual(row, [(100, 5, 50, 4, None, None)])

    def test_insert_stores_counts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.db"
            db = fc.Database(p)
            res = fc.parse_dnsfilter({"domains": [{"action": "allow"}, {"action": "deny"},
                                                  {"action": "deny"}]}, "p")
            db.insert_dnsfilter(200, res)
            db.close()
            conn = sqlite3.connect(p)
            row = conn.execute("SELECT n_domains, n_domains_allow, n_domains_deny "
                               "FROM dnsfilter_stats WHERE ts=200").fetchone()
            conn.close()
            self.assertEqual(row, (3, 1, 2))


if __name__ == "__main__":
    unittest.main()
