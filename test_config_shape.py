"""Config shape for narrow TUN and VLESS lists."""

from __future__ import annotations

import json
import unittest
from ipaddress import ip_address, ip_network
from pathlib import Path

from app.stack import nodes

ROOT = Path(__file__).resolve().parent


def load_cfg() -> dict:
    live = ROOT / "config.json"
    example = ROOT / "config.example.json"
    path = live if live.is_file() else example
    return json.loads(path.read_text(encoding="utf-8"))


class ConfigShape(unittest.TestCase):
    def test_current_spotify_fastly_addresses_use_warp(self):
        cfg = load_cfg()
        tun = next(inbound for inbound in cfg["inbounds"] if inbound.get("type") == "tun")
        warp = next(rule for rule in cfg["route"]["rules"] if rule.get("outbound") == "warp" and rule.get("ip_cidr"))
        for address in ("146.75.119.42", "146.75.118.250"):
            self.assertTrue(any(ip_address(address) in ip_network(cidr) for cidr in tun["route_address"]))
            self.assertTrue(any(ip_address(address) in ip_network(cidr) for cidr in warp["ip_cidr"]))
        obsolete = set(nodes.LEGACY_FASTLY_CIDRS) - set(nodes.FASTLY_CIDRS)
        self.assertFalse(obsolete.intersection(tun["route_address"]))
        self.assertFalse(obsolete.intersection(warp["ip_cidr"]))

    def test_narrow_tun_and_fakeip(self):
        cfg = load_cfg()
        tun = next(ob for ob in cfg["inbounds"] if ob.get("type") == "tun")
        routes = tun.get("route_address", [])
        self.assertNotIn("route_exclude_address", tun)
        self.assertNotIn("inet4_route_address", tun)
        for cidr in nodes.FASTLY_CIDRS:
            self.assertIn(cidr, routes)
        self.assertIn(nodes.FAKEIP_RANGE, routes)
        for cidr in nodes.DNS_VIA_TUN:
            self.assertIn(cidr, routes)
        self.assertFalse(set(nodes.TELEGRAM_CIDRS).intersection(routes))
        for rule in cfg["route"]["rules"]:
            if rule.get("outbound") == "proxy-select":
                self.assertFalse(set(nodes.TELEGRAM_CIDRS).intersection(rule.get("ip_cidr", [])))
        self.assertEqual(tun.get("address"), ["172.19.88.1/30"])

        dns_servers = {s.get("tag"): s for s in cfg["dns"]["servers"] if isinstance(s, dict)}
        self.assertEqual(dns_servers["fakeip"]["type"], "fakeip")
        self.assertEqual(dns_servers["fakeip"]["inet4_range"], nodes.FAKEIP_RANGE)

        reject = next(
            r
            for r in cfg["route"]["rules"]
            if isinstance(r, dict) and r.get("action") == "reject" and r.get("domain")
        )
        self.assertEqual(set(reject["domain"]), set(nodes.DOH_BLOCK))

    def test_proxy_suffixes_match_dns_and_route(self):
        cfg = load_cfg()
        route_suffixes = nodes.proxy_suffixes(cfg)
        dns_rule = next(
            r for r in cfg["dns"]["rules"] if isinstance(r, dict) and r.get("server") == "fakeip"
        )
        self.assertEqual(route_suffixes, dns_rule["domain_suffix"])
        self.assertEqual(dns_rule["query_type"], ["A", "AAAA"])
        self.assertIn("grok.com", route_suffixes)
        self.assertIn("cursor.com", route_suffixes)
        self.assertIn("gemini.google.com", route_suffixes)
        self.assertIn("aistudio.google.com", route_suffixes)
        self.assertIn("generativelanguage.googleapis.com", route_suffixes)
        self.assertIn("alkalimakersuite-pa.clients6.google.com", route_suffixes)
        self.assertNotIn("google.com", route_suffixes)
        self.assertNotIn("googleapis.com", route_suffixes)
        self.assertNotIn("clients6.google.com", route_suffixes)


class ExampleIsSafe(unittest.TestCase):
    def test_example_has_no_vless_and_no_node_bypasses(self):
        """Пример = то, что уедет в установщик. Личных нод и их обходов быть не должно."""
        cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual([o for o in cfg["outbounds"] if o.get("type") == "vless"], [])
        sel = next(o for o in cfg["outbounds"] if o.get("tag") == "proxy-select")
        self.assertEqual(sel["outbounds"], ["direct"])
        for rule in cfg.get("route", {}).get("rules", []):
            if not isinstance(rule, dict) or rule.get("outbound") != "direct":
                continue
            cidrs = rule.get("ip_cidr")
            if isinstance(cidrs, list):
                self.assertEqual(cidrs, ["172.19.88.0/30"])
            suffixes = rule.get("domain_suffix")
            if isinstance(suffixes, list) and "domain" not in rule:
                self.assertFalse(all(str(s).endswith(".download") for s in suffixes))


if __name__ == "__main__":
    unittest.main()
