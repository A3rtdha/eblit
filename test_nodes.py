"""nodes.add/remove/select on temp config."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import nodes, roster

NODE_PARSED = {
    "tag": "Mars",
    "name": "Mars",
    "host": "redplanet.example",
    "port": 443,
    "uuid": "11111111-2222-3333-4444-555555555555",
    "sni": "redplanet.example",
    "fingerprint": "firefox",
    "public_key": "PUBKEYTEST",
    "flow": "",
}

BASE_CFG = {
    "outbounds": [
        {"type": "selector", "tag": "LagomVPN", "outbounds": ["Sweden"]},
        {
            "type": "vless",
            "tag": "Sweden",
            "server": "203.0.113.11",
            "server_port": 443,
            "uuid": "11111111-2222-3333-4444-555555555555",
            "tls": {
                "enabled": True,
                "server_name": "node.example",
                "reality": {"enabled": True, "public_key": "x"},
            },
        },
        {"type": "socks", "tag": "warp", "server": "127.0.0.1", "server_port": 40000},
        {"type": "direct", "tag": "direct"},
    ],
    "route": {
        "rules": [{"domain_suffix": ["grok.com"], "outbound": "LagomVPN"}],
        "final": "direct",
    },
    "dns": {"servers": [], "rules": [], "final": "google"},
}


class NodesIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-nodes-")
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps(BASE_CFG), encoding="utf-8")
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_add_writes_outbound_and_host(self):
        result = nodes.add(NODE_PARSED)
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        tags = [ob["tag"] for ob in cfg["outbounds"] if ob.get("type") == "vless"]
        self.assertIn("Mars", tags)
        hosts = json.loads((self.dir / nodes.HOSTS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(hosts["Mars"], "redplanet.example")
        self.assertEqual(len([n for n in result["nodes"] if n["tag"] == "Mars"]), 1)

    def test_remove_current_repoints_selector(self):
        """Пустой selector sing-box не запускает: остаться должен живой тег."""
        nodes.add(NODE_PARSED)
        nodes.select("Mars")
        nodes.remove("Mars")
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertEqual(selector["outbounds"], ["Sweden"])

    def test_remove_last_leaves_empty_selector(self):
        nodes.remove("Sweden")
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertEqual(selector["outbounds"], [])

    def test_select_manual_writes_pick(self):
        nodes.select("Sweden")
        pick = json.loads((self.dir / nodes.PICK_FILE).read_text(encoding="utf-8"))
        self.assertTrue(pick["manual"])
        self.assertEqual(pick["tag"], "Sweden")
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertEqual(selector["outbounds"], ["Sweden"])

    def test_set_links_updates_route_and_dns(self):
        nodes.set_links(["grok.com", "x.ai"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(nodes.lagom_suffixes(cfg), ["grok.com", "x.ai"])
        dns_rule = next(r for r in cfg["dns"]["rules"] if r.get("server") == "fakeip")
        self.assertEqual(dns_rule["domain_suffix"], ["grok.com", "x.ai"])

    def test_duplicate_add_raises(self):
        nodes.add(NODE_PARSED)
        with self.assertRaises(ValueError):
            nodes.add(NODE_PARSED)


if __name__ == "__main__":
    unittest.main()
