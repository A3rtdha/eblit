"""nodes.add/remove/select on temp config."""

from __future__ import annotations

import json
import tempfile
import unittest
from ipaddress import ip_address, ip_network
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
        {"type": "selector", "tag": "proxy-select", "outbounds": ["Sweden"]},
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
        "rules": [{"domain_suffix": ["grok.com"], "outbound": "proxy-select"}],
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
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "proxy-select")
        self.assertEqual(selector["outbounds"], ["Sweden"])

    def test_remove_last_falls_back_to_direct(self):
        nodes.remove("Sweden")
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "proxy-select")
        self.assertEqual(selector["outbounds"], ["direct"])

    def test_select_manual_writes_pick(self):
        nodes.select("Sweden")
        pick = json.loads((self.dir / nodes.PICK_FILE).read_text(encoding="utf-8"))
        self.assertTrue(pick["manual"])
        self.assertEqual(pick["tag"], "Sweden")
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "proxy-select")
        self.assertEqual(selector["outbounds"], ["Sweden"])

    def test_set_favorite_does_not_touch_selector(self):
        """Избранное — только eblit-favorite.json, без selector и без pick."""
        nodes.set_favorite("Sweden")
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        selector = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "proxy-select")
        self.assertEqual(selector["outbounds"], ["Sweden"])
        self.assertFalse((self.dir / nodes.PICK_FILE).is_file())
        fav = json.loads((self.dir / nodes.FAV_FILE).read_text(encoding="utf-8"))
        self.assertEqual(fav["tag"], "Sweden")

    def test_set_links_updates_route_and_dns(self):
        nodes.set_links(["grok.com", "x.ai"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        suffixes = nodes.proxy_suffixes(cfg)
        self.assertEqual(suffixes[:2], ["grok.com", "x.ai"])
        self.assertIn("aistudio.google.com", suffixes)
        self.assertIn("alkalimakersuite-pa.clients6.google.com", suffixes)
        self.assertNotIn("google.com", suffixes)
        dns_rule = next(r for r in cfg["dns"]["rules"] if r.get("server") == "fakeip")
        self.assertEqual(dns_rule["domain_suffix"], suffixes)
        self.assertEqual(dns_rule["query_type"], ["A", "AAAA"])

    def test_set_links_normalizes_domains_and_urls(self):
        nodes.set_links([" .GROK.COM. ", "https://grok.com/chat?source=settings", "https://ПРИМЕР.РФ/page"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        suffixes = nodes.proxy_suffixes(cfg)
        self.assertEqual(suffixes[:2], ["grok.com", "xn--e1afmkfd.xn--p1ai"])
        self.assertEqual(suffixes.count("grok.com"), 1)

    def test_invalid_domains_do_not_change_config(self):
        before = self.cfg.read_bytes()
        invalid = [
            "com", ".com.", "https://com/path", "127.0.0.1", "*.com", "bad..com", "-bad.com", "bad_.com",
            "example.com/path", "https://user:secret@example.com", "https://example.com:bad", "https://example.com:0",
            "bad name.com", "https://example.com\\@com", "", None, 123,
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    nodes.set_links(["grok.com", value])
                self.assertEqual(self.cfg.read_bytes(), before)
        with self.assertRaises(ValueError):
            nodes.set_links("example.com")
        self.assertEqual(self.cfg.read_bytes(), before)

    def test_migration_removes_broad_suffixes_without_losing_valid_domains_or_nodes(self):
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        cfg["route"]["rules"][0]["domain_suffix"] = [
            "com", "GROK.COM", "https://custom.example/path", "net", "https://org", "example.com/path",
        ]
        cfg["dns"]["rules"] = [{"domain_suffix": ["com", "grok.com"], "server": "fakeip"}]
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")

        self.assertTrue(nodes.ensure_seed_suffixes_file())

        saved = json.loads(self.cfg.read_text(encoding="utf-8"))
        suffixes = nodes.proxy_suffixes(saved)
        self.assertEqual(suffixes[:2], ["grok.com", "custom.example"])
        self.assertNotIn("com", suffixes)
        self.assertNotIn("net", suffixes)
        self.assertNotIn("org", suffixes)
        self.assertEqual(saved["outbounds"], cfg["outbounds"])
        self.assertEqual(saved["route"]["final"], "direct")
        self.assertEqual(saved["dns"]["rules"][0]["domain_suffix"], suffixes)
        self.assertEqual(saved["dns"]["rules"][0]["query_type"], ["A", "AAAA"])
        self.assertFalse(nodes.ensure_seed_suffixes_file())

    def test_migration_replaces_an_entirely_invalid_list_with_seed_domains(self):
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        cfg["route"]["rules"][0]["domain_suffix"] = ["com", "net"]
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")
        self.assertTrue(nodes.ensure_seed_suffixes_file())
        saved = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(nodes.proxy_suffixes(saved), nodes.GOOGLE_AI_SUFFIXES)

    def test_telegram_routes_are_removed_without_changing_custom_networks(self):
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        cfg["inbounds"] = [
            {
                "type": "tun",
                "route_address": ["151.101.0.0/16", *nodes.TELEGRAM_CIDRS, "198.18.0.0/15"],
                "inet4_route_address": ["149.154.160.0/20", "203.0.113.0/24"],
            }
        ]
        cfg["route"]["rules"].extend([
            {"ip_cidr": list(nodes.TELEGRAM_CIDRS), "outbound": "proxy-select"},
            {"ip_cidr": ["91.108.56.0/22", "203.0.113.0/24"], "outbound": "proxy-select"},
            {"ip_cidr": ["91.108.56.0/22"], "outbound": "direct"},
        ])

        self.assertTrue(nodes.remove_telegram_routes(cfg))

        self.assertEqual(cfg["inbounds"][0]["route_address"], ["151.101.0.0/16", "198.18.0.0/15"])
        self.assertEqual(cfg["inbounds"][0]["inet4_route_address"], ["203.0.113.0/24"])
        self.assertEqual(cfg["route"]["rules"], [
            {"domain_suffix": ["grok.com"], "outbound": "proxy-select"},
            {"ip_cidr": ["203.0.113.0/24"], "outbound": "proxy-select"},
            {"ip_cidr": ["91.108.56.0/22"], "outbound": "direct"},
        ])
        self.assertFalse(nodes.remove_telegram_routes(cfg))

    def test_proxy_domains_take_priority_over_warp_ip_ranges(self):
        cfg = {
            "route": {"rules": [
                {"action": "sniff"},
                {"ip_cidr": ["151.101.0.0/16"], "outbound": "warp"},
                {"domain_suffix": ["chatgpt.com"], "network": "udp", "action": "reject"},
                {"domain_suffix": ["chatgpt.com", "openai.com"], "outbound": "proxy-select"},
            ]},
        }
        nodes.apply_proxy_suffixes(cfg, ["chatgpt.com", "openai.com"])
        rules = cfg["route"]["rules"]
        self.assertEqual(rules[0]["action"], "sniff")
        self.assertEqual(rules[1]["action"], "reject")
        self.assertEqual(rules[2]["outbound"], "proxy-select")
        self.assertEqual(rules[3]["outbound"], "warp")
        self.assertIn("openai.com", rules[2]["domain_suffix"])
        self.assertFalse(any(rule.get("outbound") == "direct" for rule in rules))
        before = json.dumps(cfg)
        nodes.apply_proxy_suffixes(cfg, nodes.proxy_suffixes(cfg))
        self.assertEqual(json.dumps(cfg), before)

    def test_domain_update_does_not_add_domain_condition_to_telegram_rule(self):
        telegram = {"ip_cidr": list(nodes.TELEGRAM_CIDRS), "outbound": "proxy-select"}
        cfg = {"route": {"rules": [
            telegram,
            {"domain_suffix": ["chatgpt.com"], "outbound": "proxy-select"},
        ]}}
        nodes.apply_proxy_suffixes(cfg, ["chatgpt.com", "openai.com"])
        self.assertNotIn("domain_suffix", telegram)
        self.assertIn("openai.com", nodes.proxy_suffixes(cfg))

    def test_telegram_rule_is_removed_even_without_tun(self):
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        cfg["route"]["rules"].append(
            {"ip_cidr": ["149.154.160.0/20"], "outbound": "proxy-select"}
        )
        self.assertTrue(nodes.remove_telegram_routes(cfg))
        self.assertEqual(cfg["route"]["rules"], BASE_CFG["route"]["rules"])
        self.assertNotIn("inbounds", cfg)

    def test_telegram_removal_preserves_other_destination_matches_in_the_same_rule(self):
        cfg = {"route": {"rules": [
            {"ip_cidr": ["91.108.56.0/22"], "domain_suffix": ["custom.example"], "outbound": "proxy-select"},
            {"ip_cidr": ["91.108.56.0/22"], "process_name": ["custom.exe"], "outbound": "proxy-select"},
        ]}}
        self.assertTrue(nodes.remove_telegram_routes(cfg))
        self.assertEqual(cfg["route"]["rules"], [
            {"domain_suffix": ["custom.example"], "outbound": "proxy-select"},
        ])

    def test_narrow_tun_and_shipped_config_do_not_restore_telegram(self):
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        cfg["inbounds"] = [{"type": "tun", "auto_route": True, "route_address": list(nodes.TELEGRAM_CIDRS)}]
        cfg["route"]["rules"].append({"ip_cidr": list(nodes.TELEGRAM_CIDRS), "outbound": "proxy-select"})
        shipped = nodes.sanitize_for_ship(cfg)
        self.assertEqual(shipped["inbounds"][0]["route_address"], [])
        self.assertFalse(shipped["inbounds"][0]["auto_route"])
        self.assertFalse(any(rule.get("ip_cidr") for rule in shipped["route"]["rules"]))
        nodes.apply_narrow_tun(cfg)
        self.assertFalse(set(nodes.TELEGRAM_CIDRS).intersection(cfg["inbounds"][0]["route_address"]))
        self.assertFalse(any(rule.get("ip_cidr") for rule in cfg["route"]["rules"]))

    def test_duplicate_add_raises(self):
        nodes.add(NODE_PARSED)
        with self.assertRaises(ValueError):
            nodes.add(NODE_PARSED)

    def test_fastly_migration_captures_current_spotify_addresses_and_keeps_custom_routes(self):
        guard = {"process_name": ["VALORANT.exe"], "outbound": "direct"}
        custom = "203.0.113.0/24"
        cfg = {
            "inbounds": [{"type": "tun", "auto_route": True, "route_address": [*nodes.LEGACY_FASTLY_CIDRS, custom]}],
            "outbounds": [{"type": "socks", "tag": "warp", "server": "127.0.0.1", "server_port": 40000}],
            "route": {"rules": [guard, {"ip_cidr": [*nodes.LEGACY_FASTLY_CIDRS, custom], "outbound": "warp"}]},
        }

        self.assertTrue(nodes.migrate_fastly_routes(cfg))

        routes = cfg["inbounds"][0]["route_address"]
        warp_cidrs = cfg["route"]["rules"][1]["ip_cidr"]
        self.assertEqual(routes, [*nodes.FASTLY_CIDRS, custom])
        self.assertEqual(warp_cidrs, [*nodes.FASTLY_CIDRS, custom])
        self.assertEqual(cfg["route"]["rules"][0], guard)
        self.assertTrue(cfg["inbounds"][0]["auto_route"])
        for address in ("146.75.119.42", "146.75.118.250"):
            self.assertTrue(any(ip_address(address) in ip_network(cidr) for cidr in routes))
            self.assertTrue(any(ip_address(address) in ip_network(cidr) for cidr in warp_cidrs))
        for obsolete in ("151.139.0.0/16", "199.27.128.0/21", "23.235.32.0/19", "23.235.126.0/23"):
            self.assertNotIn(obsolete, routes)
            self.assertNotIn(obsolete, warp_cidrs)
        self.assertFalse(nodes.migrate_fastly_routes(cfg))

    def test_fastly_migration_adds_missing_warp_rule_after_existing_guards(self):
        cfg = {
            "inbounds": [{"type": "tun", "tag": "tun-fastly", "route_address": ["151.101.0.0/16"]}],
            "outbounds": [{"type": "socks", "tag": "warp"}],
            "route": {"rules": [{"process_name": ["VALORANT.exe"], "outbound": "direct"}]},
        }
        self.assertTrue(nodes.migrate_fastly_routes(cfg))
        self.assertEqual(cfg["route"]["rules"], [
            {"process_name": ["VALORANT.exe"], "outbound": "direct"},
            {"ip_cidr": nodes.FASTLY_CIDRS, "outbound": "warp"},
        ])
        self.assertFalse(nodes.migrate_fastly_routes(cfg))

    def test_fastly_migration_preserves_an_unrelated_tun_and_direct_only_config(self):
        configs = [
            {
                "inbounds": [{"type": "tun", "route_address": ["203.0.113.0/24"]}],
                "outbounds": [{"tag": "warp", "type": "socks"}],
                "route": {"rules": [{"ip_cidr": ["203.0.113.0/24"], "outbound": "warp"}]},
            },
            {
                "inbounds": [{"type": "tun", "tag": "custom", "route_address": ["151.101.0.0/16", "203.0.113.0/24"]}],
                "outbounds": [{"tag": "warp", "type": "socks"}],
                "route": {"rules": [{"ip_cidr": ["151.101.0.0/16", "203.0.113.0/24"], "outbound": "warp"}]},
            },
            {
                "inbounds": [{"type": "tun", "tag": "tun-fastly", "route_address": ["151.101.0.0/16"]}],
                "outbounds": [{"tag": "direct", "type": "direct"}],
                "route": {"final": "direct"},
            },
        ]
        for cfg in configs:
            before = json.dumps(cfg)
            self.assertFalse(nodes.migrate_fastly_routes(cfg))
            self.assertEqual(json.dumps(cfg), before)


if __name__ == "__main__":
    unittest.main()
