"""Стоп должен реально гасить стек: taskkill без админа молча не работает."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.bridge import Bridge
from app.stack import cli, lifecycle

OFF_LEGS = {"ok": True, "power": False, "legs": {}}
ON_LEGS = {"ok": True, "power": True, "legs": {}}


class LifecycleStop(unittest.TestCase):
    def test_kill_ok_disconnects_warp_and_reports_off(self):
        with (
            patch.object(lifecycle.singbox, "kill") as kill,
            patch.object(lifecycle.singbox, "wait_gone", return_value=True),
            patch.object(lifecycle.warp, "disconnect") as warp_off,
            patch.object(lifecycle.probe, "light_tick", return_value=dict(OFF_LEGS)),
        ):
            result = lifecycle.stop()
        kill.assert_called_once()
        warp_off.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertFalse(result["power"])

    def test_survivor_keeps_power_on_and_does_not_cut_warp(self):
        with (
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.singbox, "wait_gone", return_value=False),
            patch.object(lifecycle.warp, "disconnect") as warp_off,
            patch.object(lifecycle.probe, "light_tick", return_value=dict(ON_LEGS)),
        ):
            result = lifecycle.stop()
        warp_off.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertTrue(result["power"])
        self.assertIn("sing-box", result["why"])


class BridgeStop(unittest.TestCase):
    def test_asks_for_admin(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=False),
            patch("app.bridge.admin.elevated", return_value=(True, 0)) as elev,
            patch("app.bridge.singbox.running", return_value=False),
            patch("app.bridge.probe.light_tick", return_value=dict(OFF_LEGS)),
        ):
            result = Bridge()._stop()
        elev.assert_called_once_with(["stop"])
        self.assertTrue(result["ok"])
        self.assertFalse(result["power"])

    def test_uac_refused_keeps_power_true(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=False),
            patch("app.bridge.admin.elevated", return_value=(False, 1)),
            patch("app.bridge.singbox.running", return_value=True),
            patch("app.bridge.probe.light_tick", return_value=dict(ON_LEGS)),
        ):
            result = Bridge()._stop()
        self.assertFalse(result["ok"])
        self.assertTrue(result["power"])
        self.assertEqual(result["why"], "нужен администратор")

    def test_elevated_but_process_survived(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=False),
            patch("app.bridge.admin.elevated", return_value=(True, 0)),
            patch("app.bridge.singbox.running", return_value=True),
            patch("app.bridge.probe.light_tick", return_value=dict(ON_LEGS)),
        ):
            result = Bridge()._stop()
        self.assertFalse(result["ok"])
        self.assertTrue(result["power"])

    def test_admin_runs_lifecycle_directly(self):
        with (
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.stop", return_value=dict(OFF_LEGS)) as stop,
        ):
            Bridge()._stop()
        stop.assert_called_once()


class CliStop(unittest.TestCase):
    def test_elevates_and_fails_when_still_running(self):
        with (
            patch.object(cli.admin, "ensure_admin", return_value=None) as ensure,
            patch.object(cli.lifecycle, "stop", return_value={"ok": False, "power": True}),
        ):
            code = cli.run("stop")
        ensure.assert_called_once_with("stop")
        self.assertEqual(code, 1)

    def test_zero_when_stopped(self):
        with (
            patch.object(cli.admin, "ensure_admin", return_value=None),
            patch.object(cli.lifecycle, "stop", return_value={"ok": True, "power": False}),
        ):
            self.assertEqual(cli.run("stop"), 0)


if __name__ == "__main__":
    unittest.main()
