"""eblit-first.json: экран первого запуска не всплывает после апдейта."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import first_pref, power_pref, subscribe


class FirstPref(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-first-")
        self.dir = Path(self.tmp.name)
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_missing_is_unread(self):
        got = first_pref.seen()
        self.assertTrue(got["ok"])
        self.assertFalse(got["read"])
        self.assertFalse((self.dir / first_pref.FIRST_FILE).is_file())

    def test_mark_roundtrip(self):
        written = first_pref.mark()
        self.assertTrue(written["ok"])
        self.assertTrue(written["read"])
        self.assertTrue(first_pref.seen()["read"])
        disk = json.loads((self.dir / first_pref.FIRST_FILE).read_text(encoding="utf-8"))
        self.assertEqual(disk, {"read": True})

    def test_power_file_means_old_user(self):
        (self.dir / power_pref.POWER_FILE).write_text('{"on": true}\n', encoding="utf-8")
        got = first_pref.seen()
        self.assertTrue(got["read"])
        self.assertTrue((self.dir / first_pref.FIRST_FILE).is_file())

    def test_sub_file_means_old_user(self):
        (self.dir / subscribe.SUB_FILE).write_text(
            '{"url": "https://panel.example/sub"}', encoding="utf-8"
        )
        got = first_pref.seen()
        self.assertTrue(got["read"])

    def test_broken_json_is_unread(self):
        (self.dir / first_pref.FIRST_FILE).write_text("{ не json", encoding="utf-8")
        got = first_pref.seen()
        self.assertFalse(got["ok"])
        self.assertFalse(got["read"])


class BridgeFirst(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-first-br-")
        self.dir = Path(self.tmp.name)
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_first_seen_and_mark(self):
        from app.bridge import Bridge

        b = Bridge()
        self.assertFalse(b.first_seen()["read"])
        b.first_mark()
        self.assertTrue(b.first_seen()["read"])


if __name__ == "__main__":
    unittest.main()
