"""eblit-power.json: запоминает питание; фейл старта не пишет on."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.bridge import Bridge
from app.stack import power_pref


OFF = {"ok": False, "power": False, "legs": {}}
ON = {"ok": True, "power": True, "legs": {}}


class PowerPref(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-power-")
        self.dir = Path(self.tmp.name)
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_missing_file_is_off(self):
        got = power_pref.get()
        self.assertTrue(got["ok"])
        self.assertFalse(got["on"])
        self.assertFalse((self.dir / power_pref.POWER_FILE).is_file())

    def test_on_roundtrip(self):
        written = power_pref.set_on(True)
        self.assertTrue(written["ok"])
        self.assertTrue(written["on"])
        again = power_pref.get()
        self.assertTrue(again["ok"])
        self.assertTrue(again["on"])
        disk = json.loads((self.dir / power_pref.POWER_FILE).read_text(encoding="utf-8"))
        self.assertEqual(disk, {"on": True})

    def test_off_roundtrip(self):
        power_pref.set_on(True)
        written = power_pref.set_on(False)
        self.assertTrue(written["ok"])
        self.assertFalse(written["on"])
        self.assertFalse(power_pref.get()["on"])

    def test_broken_json_is_off(self):
        (self.dir / power_pref.POWER_FILE).write_text("{ не json", encoding="utf-8")
        got = power_pref.get()
        self.assertFalse(got["ok"])
        self.assertFalse(got["on"])
        self.assertIn("why", got)

    def test_non_bool_on_is_off(self):
        (self.dir / power_pref.POWER_FILE).write_text('{"on": "yes"}', encoding="utf-8")
        got = power_pref.get()
        self.assertFalse(got["ok"])
        self.assertFalse(got["on"])


class BridgePowerPersist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-power-br-")
        self.dir = Path(self.tmp.name)
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_start_fail_does_not_persist_on(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.start", return_value=dict(OFF)),
        ):
            result = Bridge()._start()
        self.assertFalse(result["power"])
        self.assertFalse(power_pref.get()["on"])
        self.assertFalse((self.dir / power_pref.POWER_FILE).is_file())

    def test_start_ok_persists_on(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.start", return_value=dict(ON)),
        ):
            result = Bridge()._start()
        self.assertTrue(result["power"])
        self.assertTrue(power_pref.get()["on"])

    def test_elevated_fail_does_not_persist_on(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=False),
            patch("app.bridge.admin.elevated", return_value=(False, 1)),
            patch("app.bridge.probe.full_test", return_value=dict(OFF)),
            patch("app.bridge.singbox.running", return_value=False),
        ):
            result = Bridge()._start()
        self.assertFalse(result["power"])
        self.assertFalse((self.dir / power_pref.POWER_FILE).is_file())

    def test_stop_ok_persists_off(self):
        power_pref.set_on(True)
        with (
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.stop", return_value={"ok": True, "power": False, "legs": {}}),
        ):
            result = Bridge()._stop()
        self.assertFalse(result["power"])
        self.assertFalse(power_pref.get()["on"])

    def test_stop_survivor_does_not_write_off(self):
        power_pref.set_on(True)
        with (
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.stop", return_value={"ok": False, "power": True, "why": "жив"}),
        ):
            result = Bridge()._stop()
        self.assertTrue(result["power"])
        self.assertTrue(power_pref.get()["on"])

    def test_quit_does_not_touch_file(self):
        power_pref.set_on(True)
        Bridge().quit()
        self.assertTrue(power_pref.get()["on"])

    def test_sidecar_write_fail_does_not_fail_start(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.start", return_value=dict(ON)),
            patch.object(power_pref, "set_on", side_effect=OSError("диск")),
        ):
            result = Bridge()._start()
        self.assertTrue(result["power"])

    def test_status_exposes_want_on_from_file(self):
        power_pref.set_on(True)
        with (
            patch("app.bridge.singbox.running", return_value=False),
            patch("app.bridge.probe.light_tick", return_value={"ok": True, "power": False, "legs": {}}),
        ):
            result = Bridge().status()
        self.assertFalse(result["power"])
        self.assertTrue(result["want_on"])

    def test_status_want_on_false_when_missing(self):
        with (
            patch("app.bridge.singbox.running", return_value=False),
            patch("app.bridge.probe.light_tick", return_value={"ok": True, "power": False, "legs": {}}),
        ):
            result = Bridge().status()
        self.assertFalse(result["want_on"])


if __name__ == "__main__":
    unittest.main()
