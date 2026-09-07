"""lagom-probe.json: set/get живёт, мусор честно падает на 30."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.bridge import Bridge
from app.stack import probe_pref


class ProbeInterval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-probe-")
        self.dir = Path(self.tmp.name)
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_set_then_read_survives(self):
        written = probe_pref.set_sec(300)
        self.assertTrue(written["ok"])
        self.assertEqual(written["sec"], 300)
        again = probe_pref.get()
        self.assertTrue(again["ok"])
        self.assertEqual(again["sec"], 300)
        disk = json.loads((self.dir / probe_pref.PROBE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(disk["sec"], 300)

    def test_missing_file_is_default(self):
        got = probe_pref.get()
        self.assertTrue(got["ok"])
        self.assertEqual(got["sec"], 30)
        self.assertFalse((self.dir / probe_pref.PROBE_FILE).is_file())

    def test_invalid_set_is_honest_keeps_default(self):
        bad = probe_pref.set_sec("нет")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["sec"], 30)
        self.assertIn("why", bad)
        self.assertFalse((self.dir / probe_pref.PROBE_FILE).is_file())
        self.assertEqual(probe_pref.get()["sec"], 30)

    def test_invalid_file_falls_back_to_default(self):
        (self.dir / probe_pref.PROBE_FILE).write_text("{ не json", encoding="utf-8")
        got = probe_pref.get()
        self.assertFalse(got["ok"])
        self.assertEqual(got["sec"], 30)

    def test_invalid_set_does_not_clobber_saved(self):
        probe_pref.set_sec(60)
        bad = probe_pref.set_sec(-1)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["sec"], 60)
        self.assertEqual(probe_pref.get()["sec"], 60)

    def test_bridge_set_get_without_reload(self):
        api = Bridge()
        api._job = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("_job"))
        api._reload = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("_reload"))
        self.assertTrue(api.set_probe_sec(900)["ok"])
        self.assertEqual(api.get_probe_sec()["sec"], 900)


if __name__ == "__main__":
    unittest.main()
