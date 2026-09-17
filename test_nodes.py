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

    def test_xhttp_outbound_is_tls_not_reality(self):
        parsed = {
            "tag": "Netherlands",
            "name": "Netherlands",
            "host": "89.110.108.96",
            "port": 443,
            "uuid": "11111111-2222-3333-4444-555555555555",
            "sni": "ned-06.hello-there.ru",
            "fingerprint": "firefox",
            "public_key": "",
            "flow": "",
            "net": "xhttp",
            "path": "/xh",
            "transport_host": "ned-06.hello-there.ru",
            "mode": "auto",
            "alpn": ["h2", "http/1.1"],
        }
        ob = nodes.parsed_to_outbound(parsed)
        self.assertNotIn("reality", ob["tls"])
        self.assertEqual(ob["tls"]["server_name"], "ned-06.hello-there.ru")
        self.assertEqual(ob["tls"]["alpn"], ["h2", "http/1.1"])
        self.assertEqual(ob["transport"]["type"], "xhttp")
        self.assertEqual(ob["transport"]["path"], "/xh")
        self.assertEqual(ob["transport"]["host"], "ned-06.hello-there.ru")
        self.assertEqual(ob["transport"]["mode"], "auto")
        self.assertEqual(ob["transport"]["x_padding_bytes"], {"from": 100, "to": 1000})
        nodes.add(parsed)
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        got = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "Netherlands")
        self.assertEqual(got["transport"]["type"], "xhttp")
        sweden = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "Sweden")
        self.assertTrue(sweden["tls"]["reality"]["enabled"])

    def test_atomic_write_retries_locked_replace(self):
        target = self.dir / "locked.json"
        target.write_text("old", encoding="utf-8")
        real_replace = type(target).replace
        hits = {"n": 0}

        def flaky(self_path, dest):
            hits["n"] += 1
            if hits["n"] < 3:
                raise PermissionError("занят")
            return real_replace(self_path, dest)

        with patch.object(type(target), "replace", flaky):
            nodes._atomic_write(target, "new\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
        self.assertGreaterEqual(hits["n"], 3)

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

    def test_set_favorite_does_not_touch_selector(self):
        """Избранное — только lagom-favorite.json, без selector и без pick."""
        nodes.set_favorite("Sweden")
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertEqual(selector["outbounds"], ["Sweden"])
        self.assertFalse((self.dir / nodes.PICK_FILE).is_file())
        fav = json.loads((self.dir / nodes.FAV_FILE).read_text(encoding="utf-8"))
        self.assertEqual(fav["tag"], "Sweden")

    def test_set_links_updates_route_and_dns(self):
        nodes.set_links(["grok.com", "x.ai"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        suffixes = nodes.lagom_suffixes(cfg)
        self.assertEqual(suffixes[:2], ["grok.com", "x.ai"])
        self.assertIn("aistudio.google.com", suffixes)
        self.assertIn("alkalimakersuite-pa.clients6.google.com", suffixes)
        self.assertNotIn("google.com", suffixes)
        dns_rule = next(r for r in cfg["dns"]["rules"] if r.get("server") == "fakeip")
        self.assertEqual(dns_rule["domain_suffix"], suffixes)

    def test_duplicate_add_raises(self):
        nodes.add(NODE_PARSED)
        with self.assertRaises(ValueError):
            nodes.add(NODE_PARSED)


if __name__ == "__main__":
    unittest.main()
