"""Mixed VLESS/Hysteria2 server selection, probing and packaging."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import health, hysteria2, nodes, roster


VLESS = {
    "type": "vless",
    "tag": "Vless",
    "server": "203.0.113.10",
    "server_port": 443,
    "uuid": "11111111-2222-3333-4444-555555555555",
    "tls": {"enabled": True, "server_name": "vless.example"},
}
HYSTERIA2 = {
    "type": "hysteria2",
    "tag": "Hysteria",
    "server": "hy.example",
    "server_port": 8443,
    "password": "PRIVATE-HY-PASSWORD",
    "obfs": {"type": "salamander", "password": "PRIVATE-OBFS-PASSWORD"},
    "tls": {"enabled": True, "server_name": "hy-sni.example", "alpn": ["h3"]},
}


def config_with(*servers: dict, selected: str | None = "Vless") -> dict:
    return {
        "outbounds": [
            {"type": "selector", "tag": "proxy-select", "outbounds": [selected] if selected else []},
            *copy.deepcopy(servers),
            {"type": "socks", "tag": "warp", "server": "127.0.0.1", "server_port": 40000},
            {"type": "direct", "tag": "direct"},
        ]
    }


class ServerProtocols(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-server-protocols-")
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps(config_with(VLESS, HYSTERIA2)), encoding="utf-8")
        patcher = patch("app.paths.root", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def read_config(self) -> dict:
        return json.loads(self.cfg.read_text(encoding="utf-8"))

    def test_server_tags_include_both_protocols_and_vless_tags_stay_strict(self):
        cfg = self.read_config()
        cfg["outbounds"].extend([None, {"type": ["vless"]}, {"type": "hysteria2"}])
        self.assertEqual(nodes.server_tags(cfg), ["Vless", "Hysteria"])
        self.assertEqual(nodes.vless_tags(cfg), ["Vless"])
        self.assertFalse(nodes.is_server({"type": "wireguard", "tag": "Other"}))

    def test_hysteria2_host_is_seeded_from_config(self):
        self.assertEqual(nodes.hosts(), {"Hysteria": "hy.example"})

    def test_add_dispatches_hysteria2_and_roundtrips_its_outbound(self):
        self.cfg.write_text(json.dumps(config_with(VLESS)), encoding="utf-8")
        parsed = {
            "type": "hysteria2", "tag": "Hysteria", "name": "Hysteria",
            "host": "hy.example", "port": 8443, "password": "PRIVATE-HY-PASSWORD",
            "sni": "hy-sni.example", "alpn": ["h3"],
            "obfs": {"type": "salamander", "password": "PRIVATE-OBFS-PASSWORD"},
        }
        result = nodes.add(parsed)
        cfg = self.read_config()
        outbound = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "Hysteria")
        self.assertEqual(outbound, HYSTERIA2)
        self.assertEqual(nodes.hosts()["Hysteria"], "hy.example")
        self.assertEqual([row["tag"] for row in result["nodes"]], ["Vless", "Hysteria"])
        self.assertEqual(nodes.parsed_to_outbound(hysteria2.from_singbox(outbound)), HYSTERIA2)

    def test_hysteria2_can_be_selected_and_favorited(self):
        nodes.select("Hysteria")
        nodes.set_favorite("Hysteria")
        self.assertEqual(nodes._selector_outbounds(self.read_config()), ["Hysteria"])
        pick = json.loads((self.dir / nodes.PICK_FILE).read_text(encoding="utf-8"))
        self.assertEqual(pick, {"tag": "Hysteria", "ip": "hy.example", "manual": True})
        favorite = json.loads((self.dir / nodes.FAV_FILE).read_text(encoding="utf-8"))
        self.assertEqual(favorite, {"tag": "Hysteria", "host": "hy.example"})

    def test_hysteria2_removal_repoints_selector_and_clears_preferences(self):
        nodes.select("Hysteria")
        nodes.set_favorite("Hysteria")
        result = nodes.remove("Hysteria")
        self.assertEqual(nodes.server_tags(self.read_config()), ["Vless"])
        self.assertEqual(nodes._selector_outbounds(self.read_config()), ["Vless"])
        self.assertEqual([row["tag"] for row in result["nodes"]], ["Vless"])
        self.assertFalse((self.dir / nodes.PICK_FILE).exists())
        self.assertFalse((self.dir / nodes.FAV_FILE).exists())
        self.assertNotIn("Hysteria", nodes.hosts())

    def test_hysteria2_only_selector_is_repaired_then_last_removal_uses_direct(self):
        cfg = config_with(HYSTERIA2, selected=None)
        self.assertTrue(nodes.ensure_selector(cfg))
        self.assertEqual(nodes._selector_outbounds(cfg), ["Hysteria"])
        self.assertFalse(nodes.ensure_selector(cfg))
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")
        nodes.remove("Hysteria")
        self.assertEqual(nodes._selector_outbounds(self.read_config()), ["direct"])

    def test_roster_lists_both_protocols_without_authentication_secrets(self):
        nodes.select("Hysteria")
        result = roster.stack_nodes()
        self.assertEqual([row["tag"] for row in result["nodes"]], ["Vless", "Hysteria"])
        row = result["nodes"][1]
        self.assertEqual(row["host"], "hy.example")
        self.assertEqual(row["port"], 8443)
        self.assertEqual(row["sni"], "hy-sni.example")
        self.assertTrue(row["current"])
        blob = json.dumps(result)
        self.assertNotIn(HYSTERIA2["password"], blob)
        self.assertNotIn(HYSTERIA2["obfs"]["password"], blob)
        self.assertNotIn(VLESS["uuid"], blob)

    def test_hysteria2_favorite_is_tried_before_previous_vless_pick(self):
        nodes.select("Vless")
        nodes.set_favorite("Hysteria")
        self.assertEqual(health.try_order(), ["Hysteria", "Vless"])

    def test_hysteria2_only_health_uses_existing_probe_and_pins_server_ip(self):
        self.cfg.write_text(json.dumps(config_with(HYSTERIA2, selected=None)), encoding="utf-8")
        with (
            patch.object(health, "resolve_one", return_value="203.0.113.20"),
            patch.object(health, "probe", return_value=(True, 10, "200")) as probe,
            patch.object(health, "log"),
        ):
            self.assertEqual(health.main(), 0)
        probe.assert_called_once_with("Hysteria", HYSTERIA2, "203.0.113.20")
        cfg = self.read_config()
        self.assertEqual(nodes._selector_outbounds(cfg), ["Hysteria"])
        server = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "Hysteria")
        self.assertEqual(server["server"], "203.0.113.20")
        self.assertEqual(server["tls"], HYSTERIA2["tls"])
        self.assertEqual(health.last_pick(), "Hysteria")
        pick = json.loads((self.dir / nodes.PICK_FILE).read_text(encoding="utf-8"))
        self.assertEqual(pick, {"tag": "Hysteria", "ip": "203.0.113.20"})

    def test_manual_hysteria2_is_probed_before_automatic_vless(self):
        nodes.select("Hysteria")
        with (
            patch.object(health, "resolve_one", return_value="203.0.113.20"),
            patch.object(health, "probe", return_value=(True, 10, "200")) as probe,
            patch.object(health, "log"),
        ):
            self.assertEqual(health.main(), 0)
        self.assertEqual(probe.call_args.args[0], "Hysteria")
        probe.assert_called_once()
        self.assertEqual(nodes.manual_tag(), "Hysteria")

    def test_scan_includes_both_protocols_without_changing_selection(self):
        nodes.select("Hysteria")
        before_config = self.cfg.read_bytes()
        before_pick = (self.dir / nodes.PICK_FILE).read_bytes()
        with (
            patch.object(health, "resolve_one", return_value="203.0.113.20"),
            patch.object(health, "probe", return_value=(True, 10, "200")) as probe,
        ):
            result = health.scan_all()
        self.assertEqual([row["tag"] for row in result["nodes"]], ["Vless", "Hysteria"])
        self.assertEqual({call.args[1]["type"] for call in probe.call_args_list}, {"vless", "hysteria2"})
        self.assertEqual(self.cfg.read_bytes(), before_config)
        self.assertEqual((self.dir / nodes.PICK_FILE).read_bytes(), before_pick)

    def test_health_rejects_hysteria2_changed_during_probe(self):
        self.cfg.write_text(json.dumps(config_with(HYSTERIA2, selected=None)), encoding="utf-8")

        def change_password(*_args):
            cfg = self.read_config()
            server = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "Hysteria")
            server["password"] = "CHANGED-PASSWORD"
            nodes.write_config(cfg)
            return True, 10, "200"

        with (
            patch.object(health, "resolve_one", return_value="203.0.113.20"),
            patch.object(health, "probe", side_effect=change_password),
            patch.object(health, "log"),
        ):
            self.assertEqual(health.main(), 1)
        self.assertEqual(nodes._selector_outbounds(self.read_config()), [])
        self.assertFalse((self.dir / nodes.PICK_FILE).exists())

    def test_shipping_removes_both_protocols_and_preserves_source(self):
        source = self.read_config()
        before = copy.deepcopy(source)
        shipped = nodes.sanitize_for_ship(source)
        self.assertEqual([ob["tag"] for ob in shipped["outbounds"]], ["proxy-select", "warp", "direct"])
        self.assertEqual(nodes._selector_outbounds(shipped), ["direct"])
        blob = json.dumps(shipped)
        self.assertNotIn(HYSTERIA2["password"], blob)
        self.assertNotIn(HYSTERIA2["obfs"]["password"], blob)
        self.assertNotIn(VLESS["uuid"], blob)
        self.assertEqual(source, before)


if __name__ == "__main__":
    unittest.main()
