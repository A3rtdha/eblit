"""Ростер читает config.json / pick / ips. Только чтение, без секретов, без сети."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import roster

NODE = {
    "type": "vless",
    "tag": "Finland",
    "server": "203.0.113.10",
    "server_port": 443,
    "uuid": "11111111-2222-3333-4444-555555555555",
    "tls": {
        "enabled": True,
        "server_name": "grok.com",
        "reality": {"enabled": True, "public_key": "SECRETPBK"},
    },
}


def cfg_with(*nodes: dict, selector: list | None = None) -> dict:
    outbounds: list[dict] = []
    if selector is not None:
        outbounds.append({"type": "selector", "tag": "LagomVPN", "outbounds": selector})
    outbounds.extend(nodes)
    outbounds.append({"type": "direct", "tag": "direct"})
    return {"outbounds": outbounds}


class Roster(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-roster-")
        self.dir = Path(self.tmp.name)
        patcher = patch("app.paths.root", return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write_cfg(self, data: dict) -> None:
        (self.dir / "config.json").write_text(json.dumps(data), encoding="utf-8")

    def test_reads_vless_outbounds_with_host_and_ip(self):
        self.write_cfg(cfg_with(NODE, selector=["Finland"]))
        r = roster.stack_nodes()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["nodes"]), 1)
        node = r["nodes"][0]
        self.assertEqual(node["tag"], "Finland")
        self.assertEqual(node["ip"], "203.0.113.10")
        self.assertEqual(node["port"], 443)
        self.assertEqual(node["sni"], "grok.com")
        self.assertEqual(node["host"], "grok.com")
        self.assertTrue(node["current"])
        self.assertEqual(r["selected"], "Finland")

    def test_no_secrets_leak(self):
        self.write_cfg(cfg_with(NODE, selector=["Finland"]))
        blob = json.dumps(roster.stack_nodes())
        self.assertNotIn("SECRETPBK", blob)
        self.assertNotIn(NODE["uuid"], blob)
        self.assertNotIn("public_key", blob)
        self.assertNotIn("uuid", blob)

    def test_selector_marks_only_its_tag(self):
        other = dict(NODE, tag="Sweden", server="203.0.113.11")
        self.write_cfg(cfg_with(NODE, other, selector=["Sweden"]))
        r = roster.stack_nodes()
        current = [n["tag"] for n in r["nodes"] if n["current"]]
        self.assertEqual(current, ["Sweden"])

    def test_pick_read_when_present(self):
        self.write_cfg(cfg_with(NODE, selector=["Finland"]))
        (self.dir / "lagom-pick.json").write_text(
            json.dumps({"tag": "Finland", "ip": "203.0.113.10"}), encoding="utf-8"
        )
        r = roster.stack_nodes()
        self.assertEqual(r["pick"], {"tag": "Finland", "ip": "203.0.113.10"})

    def test_pick_absent_is_none_not_error(self):
        self.write_cfg(cfg_with(NODE, selector=["Finland"]))
        r = roster.stack_nodes()
        self.assertTrue(r["ok"])
        self.assertIsNone(r["pick"])

    def test_pick_broken_is_none_not_error(self):
        self.write_cfg(cfg_with(NODE, selector=["Finland"]))
        (self.dir / "lagom-pick.json").write_text("{ не json", encoding="utf-8")
        r = roster.stack_nodes()
        self.assertTrue(r["ok"])
        self.assertIsNone(r["pick"])

    def test_ips_file_gives_host_for_unknown_tag(self):
        custom = {"type": "vless", "tag": "Mars", "server": "9.9.9.9"}
        self.write_cfg(cfg_with(custom, selector=["Mars"]))
        (self.dir / "lagom-ips.json").write_text(
            json.dumps({"redplanet.example": "9.9.9.9"}), encoding="utf-8"
        )
        r = roster.stack_nodes()
        self.assertEqual(r["nodes"][0]["host"], "redplanet.example")

    def test_unknown_tag_without_ips_has_empty_host(self):
        custom = {"type": "vless", "tag": "Mars", "server": "9.9.9.9"}
        self.write_cfg(cfg_with(custom, selector=["Mars"]))
        r = roster.stack_nodes()
        self.assertEqual(r["nodes"][0]["host"], "")

    def test_missing_config_is_honest_failure(self):
        r = roster.stack_nodes()
        self.assertFalse(r["ok"])
        self.assertEqual(r["nodes"], [])
        self.assertIn("config.json", r["why"])

    def test_broken_config_is_honest_failure(self):
        (self.dir / "config.json").write_text("{ обрезано", encoding="utf-8")
        r = roster.stack_nodes()
        self.assertFalse(r["ok"])
        self.assertEqual(r["nodes"], [])
        self.assertTrue(r["why"])

    def test_locked_config_retries_then_reports(self):
        """config.json replace while health runs: busy file is a reason, not empty roster."""
        calls = {"n": 0}
        real = Path.read_text

        def flaky(self_path, *a, **kw):
            if self_path.name == "config.json":
                calls["n"] += 1
                raise PermissionError("занят")
            return real(self_path, *a, **kw)

        self.write_cfg(cfg_with(NODE, selector=["Finland"]))
        with patch.object(Path, "read_text", flaky):
            r = roster.stack_nodes()
        self.assertFalse(r["ok"])
        self.assertGreater(calls["n"], 1)

    def test_locked_config_second_try_wins(self):
        real = Path.read_text
        state = {"first": True}

        def flaky(self_path, *a, **kw):
            if self_path.name == "config.json" and state["first"]:
                state["first"] = False
                raise PermissionError("занят")
            return real(self_path, *a, **kw)

        self.write_cfg(cfg_with(NODE, selector=["Finland"]))
        with patch.object(Path, "read_text", flaky):
            r = roster.stack_nodes()
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["nodes"]), 1)

    def test_no_selector_means_nothing_current(self):
        self.write_cfg(cfg_with(NODE))
        r = roster.stack_nodes()
        self.assertTrue(r["ok"])
        self.assertIsNone(r["selected"])
        self.assertFalse(r["nodes"][0]["current"])

    def test_non_vless_outbounds_skipped(self):
        self.write_cfg(cfg_with(NODE, {"type": "wireguard", "tag": "warp"}, selector=["Finland"]))
        self.assertEqual([n["tag"] for n in roster.stack_nodes()["nodes"]], ["Finland"])

    def test_outbound_without_tag_skipped(self):
        self.write_cfg(cfg_with(NODE, {"type": "vless", "server": "1.2.3.4"}, selector=["Finland"]))
        self.assertEqual(len(roster.stack_nodes()["nodes"]), 1)


if __name__ == "__main__":
    unittest.main()
