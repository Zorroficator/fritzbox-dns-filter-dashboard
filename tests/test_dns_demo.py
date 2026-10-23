"""The synthetic DNS demo files must match the documented output contract (docs/dns_contract.md)."""
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo"))
import make_sample  # noqa: E402

DOC = (ROOT / "docs" / "dns_contract.md").read_text(encoding="utf-8")
FREE_MAPS = {"statuses"}                    # dictionaries with data-dependent keys
DEMO_ONLY_KEYS = {"demo", "exported_at"}    # added by make_sample.py, not part of the collector output


def doc_json(heading):
    """First ```json block after the '## <heading>' line."""
    start = DOC.index(f"## `{heading}`")
    m = re.search(r"```json\n(.*?)```", DOC[start:], re.S)
    return json.loads(m.group(1))


def shape(value, key=""):
    if isinstance(value, dict):
        if key in FREE_MAPS:
            return "map"
        return {k: shape(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(value[0], key)] if value else []
    return "scalar"


def diff(a, b, path=""):
    """List differences; an empty list on either side matches anything."""
    if isinstance(a, list) and isinstance(b, list):
        if not a or not b:
            return []
        return diff(a[0], b[0], path + "[]")
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: missing in docs")
            elif k not in b:
                out.append(f"{path}.{k}: missing in output")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


class DnsDemoContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        out = Path(cls.tmp.name)
        cls.now = int(time.time())
        make_sample.make_dns(out, cls.now, seed=7)
        cls.live = json.loads((out / "dns_live.json").read_text(encoding="utf-8"))
        cls.top = json.loads((out / "dns_top.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def without_demo_keys(d):
        return {k: v for k, v in d.items() if k not in DEMO_ONLY_KEYS}

    def test_demo_markers(self):
        for d in (self.live, self.top):
            self.assertIs(d["demo"], True)
            self.assertEqual(d["exported_at"], self.now)

    def test_live_shape_matches_docs(self):
        self.assertEqual(diff(shape(doc_json("dns_live.json")), shape(self.without_demo_keys(self.live))), [])

    def test_top_shape_matches_docs(self):
        doc = doc_json("dns_top.json")
        doc["periods"]["7d"] = doc["periods"]["30d"] = doc["periods"]["today"]
        self.assertEqual(diff(shape(doc), shape(self.without_demo_keys(self.top))), [])

    def test_vocabulary_matches_docs(self):
        for e in self.live["events"]:
            self.assertIn(f"`{e['status']}`", DOC)
            self.assertIn(f"`{e['reply']}`", DOC)
        self.assertEqual(self.live["health"]["last_error"], "")

    def test_series_consistency(self):
        sr = self.top["series_24h"]
        self.assertEqual(len(sr["buckets"]), 144)
        self.assertEqual(sr["step"], 600)
        self.assertEqual(sr["start"] % 600, 0)
        self.assertIsNone(sr["buckets"][0]["allowed"])
        for c in self.top["clients_24h"]["clients"] + [self.top["clients_24h"]["rest"]]:
            self.assertEqual(len(c["series"]), 144)
            self.assertEqual(len(c["blocked_series"]), 144)
        for p in self.top["periods"].values():
            self.assertEqual(sum(p["statuses"].values()), p["total"])
            self.assertLessEqual(len(p["top_permitted"]), 10)
        self.assertEqual(len(self.live["events"]), 200)
        ts = [e["ts"] for e in self.live["events"]]
        self.assertEqual(ts, sorted(ts, reverse=True))


if __name__ == "__main__":
    unittest.main()
