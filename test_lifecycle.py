"""start.bat order: kill → subscribe → health (warn) → check (abort) → warp → sing-box → test."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import lifecycle, nodes, routing_safety

OFF = {"ok": False, "power": False, "legs": {}}
ON = {"ok": True, "power": True, "legs": {}}

_SKIP_SUB = {"ok": True, "skipped": True}


class StartOrder(unittest.TestCase):
    def setUp(self):
        prepare = patch.object(lifecycle, "_prepare_routing")
        self.prepare = prepare.start()
        self.addCleanup(prepare.stop)

    def test_bad_config_does_not_touch_warp(self):
        with (
            patch.object(lifecycle.subscribe, "refresh", return_value=dict(_SKIP_SUB)),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.health, "main", return_value=0),
            patch.object(lifecycle.singbox, "check", return_value=(False, "bad config")),
            patch.object(lifecycle.warp, "configure_and_connect") as warp,
            patch.object(lifecycle.probe, "light_tick", return_value=OFF),
        ):
            result = lifecycle.start()
        warp.assert_not_called()
        self.assertFalse(result["power"])
        self.assertEqual(result["why"], "bad config")

    def test_routing_repair_failure_aborts_before_network_start(self):
        self.prepare.side_effect = OSError("config.json is locked")
        with (
            patch.object(lifecycle, "stop") as stop,
            patch.object(lifecycle.subscribe, "refresh") as refresh,
            patch.object(lifecycle.singbox, "start") as start,
        ):
            with self.assertRaisesRegex(OSError, "locked"):
                lifecycle.start()
        refresh.assert_not_called()
        start.assert_not_called()
        stop.assert_called_once()

    def test_health_fail_still_starts(self):
        with (
            patch.object(lifecycle.subscribe, "refresh", return_value=dict(_SKIP_SUB)),
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.health, "main", return_value=1),
            patch.object(lifecycle.singbox, "check", return_value=(True, "")),
            patch.object(lifecycle.warp, "configure_and_connect") as warp,
            patch.object(lifecycle.warp, "wait_ready", return_value=True),
            patch.object(lifecycle.warp, "disconnect") as warp_off,
            patch.object(lifecycle.singbox, "start") as run,
            patch.object(lifecycle.singbox, "wait_tun", return_value=True),
            patch.object(lifecycle.lan, "sync_firewall"),
            patch.object(lifecycle.probe, "light_tick", return_value=dict(ON)),
        ):
            result = lifecycle.start()
        self.prepare.assert_called_once()
        warp.assert_called_once()
        warp_off.assert_not_called()
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
            patch.object(lifecycle.warp, "disconnect") as warp_off,
            patch.object(lifecycle.singbox, "start") as run,
            patch.object(lifecycle.probe, "light_tick", return_value=OFF),
        ):
            result = lifecycle.start()
        run.assert_not_called()
        warp_off.assert_called_once()
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
            patch.object(lifecycle.lan, "sync_firewall"),
            patch.object(lifecycle.probe, "light_tick", return_value=dict(ON)),
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
            patch.object(lifecycle.lan, "sync_firewall"),
            patch.object(lifecycle.probe, "light_tick", return_value=dict(ON)),
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
            patch.object(lifecycle.lan, "sync_firewall"),
            patch.object(lifecycle.probe, "light_tick", return_value=dict(ON)),
        ):
            lifecycle.reload()
        self.prepare.assert_called_once()
        refresh.assert_not_called()
        warp.assert_not_called()
        run.assert_called_once()


class PrepareRouting(unittest.TestCase):
    def test_repairs_existing_config_without_changing_servers(self):
        with tempfile.TemporaryDirectory(prefix="eblit-routing-") as directory:
            data = Path(directory)
            cfg = {
                "inbounds": [{"type": "tun", "route_address": ["198.18.0.0/15", "91.108.4.0/22"]}],
                "outbounds": [{"type": "direct", "tag": "direct"}],
                "dns": {
                    "servers": [{"tag": "google", "type": "udp", "server": "8.8.8.8"}],
                    "final": "google",
                    "rules": [{"domain_suffix": ["com", "grok.com"], "server": "fakeip"}],
                },
                "route": {"rules": [
                    {"domain_suffix": ["com", "grok.com"], "outbound": "proxy-select"},
                    {"ip_cidr": ["91.108.4.0/22"], "outbound": "proxy-select"},
                ]},
            }
            path = data / "config.json"
            path.write_text(json.dumps(cfg), encoding="utf-8")
            with patch("app.paths.root", return_value=data):
                lifecycle._prepare_routing()
                repaired = nodes.read_config()
                self.assertEqual(repaired["outbounds"], cfg["outbounds"])
                self.assertNotIn("com", nodes.proxy_suffixes(repaired))
                self.assertNotIn("91.108.4.0/22", repaired["inbounds"][0]["route_address"])
                self.assertIn(
                    {"domain_suffix": list(routing_safety.RIOT_DOMAIN_SUFFIXES), "server": "google"},
                    repaired["dns"]["rules"],
                )
                before = path.read_bytes()
                lifecycle._prepare_routing()
                self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
