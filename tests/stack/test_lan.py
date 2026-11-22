"""lan.set_enabled / address on temp config."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import lan

BASE_CFG = {
    "inbounds": [
        {
            "type": "tun",
            "tag": "tun-fastly",
            "route_address": ["151.101.0.0/16", "198.18.0.0/15"],
        },
        {"type": "mixed", "tag": "mixed-local", "listen": "127.0.0.1", "listen_port": 2080},
    ],
    "outbounds": [{"type": "direct", "tag": "direct"}],
    "route": {"rules": [], "final": "direct"},
}


def _addr_infos(*ips: str) -> list:
    return [(2, 1, 6, "", (ip, 0)) for ip in ips]


class LanConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-lan-")
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps(BASE_CFG), encoding="utf-8")
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def read(self) -> dict:
        return json.loads(self.cfg.read_text(encoding="utf-8"))

    def test_toggle_on_off_keeps_narrow_tun(self):
        """Тумблер трогает только mixed: route_address узкого TUN — не его дело."""
        with patch("app.stack.lan.address", return_value="192.168.1.5"):
            state = lan.set_enabled(True)
        self.assertTrue(state["on"])
        self.assertEqual(state["address"], "192.168.1.5")
        cfg = self.read()
        mixed = next(i for i in cfg["inbounds"] if i["tag"] == "mixed-local")
        tun = next(i for i in cfg["inbounds"] if i["tag"] == "tun-fastly")
        self.assertEqual(mixed["listen"], "0.0.0.0")
        self.assertEqual(mixed["listen_port"], 2080)
        self.assertEqual(tun["route_address"], ["151.101.0.0/16", "198.18.0.0/15"])

        state = lan.set_enabled(False)
        self.assertFalse(state["on"])
        self.assertEqual(state["address"], "")
        mixed = next(i for i in self.read()["inbounds"] if i["tag"] == "mixed-local")
        self.assertEqual(mixed["listen"], "127.0.0.1")

    def test_missing_inbound_raises(self):
        cfg = self.read()
        cfg["inbounds"] = [i for i in cfg["inbounds"] if i["tag"] != "mixed-local"]
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ValueError):
            lan.set_enabled(True)


class LanAddress(unittest.TestCase):
    def test_skips_tun_and_loopback(self):
        """172.19.88.1 в шлеме выглядит рабочим и молча никуда не ведёт."""
        infos = _addr_infos("127.0.0.1", "172.19.88.1", "192.168.0.14")
        with patch("socket.getaddrinfo", return_value=infos):
            self.assertEqual(lan.address(), "192.168.0.14")

    def test_prefers_192_168(self):
        infos = _addr_infos("10.8.0.2", "192.168.31.7")
        with patch("socket.getaddrinfo", return_value=infos):
            self.assertEqual(lan.address(), "192.168.31.7")

    def test_public_and_link_local_ignored(self):
        infos = _addr_infos("172.15.0.1", "172.32.0.1", "93.184.216.34")
        with patch("socket.getaddrinfo", return_value=infos):
            self.assertEqual(lan.address(), "")

    def test_resolver_failure_is_not_fatal(self):
        with patch("socket.getaddrinfo", side_effect=OSError("no dns")):
            self.assertEqual(lan.address(), "")


if __name__ == "__main__":
    unittest.main()
