"""start.bat order: kill → subscribe → health (warn) → check (abort) → warp → sing-box → test."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.stack import lifecycle

OFF = {"ok": False, "power": False, "legs": {}}
ON = {"ok": True, "power": True, "legs": {}}

_SKIP_SUB = {"ok": True, "skipped": True}


class StartOrder(unittest.TestCase):
    def test_bad_config_does_not_touch_warp(self):
        with (
            patch.object(lifecycle.subscribe, "refresh", return_value=dict(_SKIP_SUB)),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.health, "main", return_value=0),
            patch.object(lifecycle.singbox, "check", return_value=(False, "bad config")),
            patch.object(lifecycle.warp, "configure_and_connect") as warp,
            patch.object(lifecycle.probe, "full_test", return_value=OFF),
            patch.object(lifecycle.time, "sleep"),
        ):
            result = lifecycle.start()
        warp.assert_not_called()
        self.assertFalse(result["power"])
        self.assertEqual(result["why"], "bad config")

    def test_health_fail_still_starts(self):
        with (
            patch.object(lifecycle.subscribe, "refresh", return_value=dict(_SKIP_SUB)),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.health, "main", return_value=1),
            patch.object(lifecycle.singbox, "check", return_value=(True, "")),
            patch.object(lifecycle.warp, "configure_and_connect") as warp,
            patch.object(lifecycle.warp, "wait_ready", return_value=True),
            patch.object(lifecycle.singbox, "start") as run,
            patch.object(lifecycle.singbox, "wait_tun", return_value=True),
            patch.object(lifecycle.probe, "full_test", return_value=dict(ON)),
            patch.object(lifecycle.time, "sleep"),
        ):
            result = lifecycle.start()
        warp.assert_called_once()
        run.assert_called_once()
        self.assertTrue(result["power"])

    def test_warp_timeout_does_not_start_singbox(self):
        with (
            patch.object(lifecycle.subscribe, "refresh", return_value=dict(_SKIP_SUB)),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.health, "main", return_value=0),
            patch.object(lifecycle.singbox, "check", return_value=(True, "")),
            patch.object(lifecycle.warp, "configure_and_connect"),
            patch.object(lifecycle.warp, "wait_ready", return_value=False),
            patch.object(lifecycle.singbox, "start") as run,
            patch.object(lifecycle.probe, "full_test", return_value=OFF),
            patch.object(lifecycle.time, "sleep"),
        ):
            result = lifecycle.start()
        run.assert_not_called()
        self.assertFalse(result["power"])

    def test_subscribe_runs_before_health(self):
        order: list[str] = []

        def refresh():
            order.append("sub")
            return {"ok": True}

        def health():
            order.append("health")
            return 0

        with (
            patch.object(lifecycle.subscribe, "refresh", side_effect=refresh),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.health, "main", side_effect=health),
            patch.object(lifecycle.singbox, "check", return_value=(True, "")),
            patch.object(lifecycle.warp, "configure_and_connect"),
            patch.object(lifecycle.warp, "wait_ready", return_value=True),
            patch.object(lifecycle.singbox, "start"),
            patch.object(lifecycle.singbox, "wait_tun", return_value=True),
            patch.object(lifecycle.probe, "full_test", return_value=dict(ON)),
            patch.object(lifecycle.time, "sleep"),
        ):
            result = lifecycle.start()
        self.assertEqual(order, ["sub", "health"])
        self.assertTrue(result["power"])

    def test_subscribe_fail_still_starts(self):
        with (
            patch.object(lifecycle.subscribe, "refresh", return_value={"ok": False, "why": "нет сети"}),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.health, "main", return_value=0),
            patch.object(lifecycle.singbox, "check", return_value=(True, "")),
            patch.object(lifecycle.warp, "configure_and_connect"),
            patch.object(lifecycle.warp, "wait_ready", return_value=True),
            patch.object(lifecycle.singbox, "start") as run,
            patch.object(lifecycle.singbox, "wait_tun", return_value=True),
            patch.object(lifecycle.probe, "full_test", return_value=dict(ON)),
            patch.object(lifecycle.time, "sleep"),
        ):
            result = lifecycle.start()
        run.assert_called_once()
        self.assertTrue(result["power"])

    def test_reload_does_not_reconfigure_warp(self):
        with (
            patch.object(lifecycle.subscribe, "refresh") as refresh,
            patch.object(lifecycle.health, "main", return_value=0),
            patch.object(lifecycle.singbox, "check", return_value=(True, "")),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.singbox, "start") as run,
            patch.object(lifecycle.singbox, "wait_tun", return_value=True),
            patch.object(lifecycle.warp, "configure_and_connect") as warp,
            patch.object(lifecycle.probe, "full_test", return_value=dict(ON)),
            patch.object(lifecycle.time, "sleep"),
        ):
            lifecycle.reload()
        refresh.assert_not_called()
        warp.assert_not_called()
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
