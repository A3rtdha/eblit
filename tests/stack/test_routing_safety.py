from __future__ import annotations

import copy
import unittest

from app.stack import routing_safety


def base_config() -> dict:
    return {
        "dns": {
            "servers": [
                {"type": "udp", "tag": "google", "server": "8.8.8.8"},
                {"type": "fakeip", "tag": "fakeip", "inet4_range": "198.18.0.0/15"},
            ],
            "rules": [{"domain_suffix": ["com"], "server": "fakeip"}],
            "final": "google",
        },
        "route": {
            "rules": [
                {"action": "sniff"},
                {"protocol": "dns", "action": "hijack-dns"},
                {"port": [53], "action": "hijack-dns"},
                {"domain_suffix": ["com"], "outbound": "proxy-select"},
                {"ip_cidr": ["151.101.0.0/16"], "outbound": "warp"},
            ],
            "final": "direct",
        },
    }


def first_domain_match(rules: list[dict], domain: str, result_key: str) -> str | None:
    for rule in rules:
        suffixes = rule.get("domain_suffix", [])
        if any(domain == suffix or domain.endswith("." + suffix) for suffix in suffixes):
            return rule.get(result_key)
    return None


class GameBypass(unittest.TestCase):
    def test_riot_uses_real_dns_and_direct_route_before_broad_proxy_rule(self):
        cfg = base_config()
        routing_safety.apply_game_bypass(cfg)
        for domain in (
            "auth.riotgames.com",
            "clientconfig.rpg.riotgames.com",
            "valorant.secure.dyn.riotcdn.net",
            "playvalorant.com",
            "chat.euw1.lol.riotgames.com",
        ):
            with self.subTest(domain=domain):
                self.assertEqual(first_domain_match(cfg["dns"]["rules"], domain, "server"), "google")
                self.assertEqual(first_domain_match(cfg["route"]["rules"], domain, "outbound"), "direct")
        self.assertEqual(first_domain_match(cfg["dns"]["rules"], "notriotgames.com", "server"), "fakeip")
        self.assertEqual(first_domain_match(cfg["route"]["rules"], "notriotgames.com", "outbound"), "proxy-select")

    def test_game_processes_go_direct_without_intercepting_dns_preprocessing(self):
        cfg = base_config()
        original_preprocessing = copy.deepcopy(cfg["route"]["rules"][:3])
        routing_safety.apply_game_bypass(cfg)
        rules = cfg["route"]["rules"]
        proxy_rule = next(rule for rule in rules if rule.get("outbound") == "proxy-select")
        self.assertEqual(rules[:3], original_preprocessing)
        for process_name in (
            "VALORANT-Win64-Shipping.exe", "VALORANT.exe", "RiotClientServices.exe",
            "RiotClientUx.exe", "RiotClientUxRender.exe", "vgc.exe", "vgm.exe",
        ):
            matching_rule = next(rule for rule in rules if process_name in rule.get("process_name", []))
            self.assertEqual(matching_rule["outbound"], "direct")
            self.assertLess(rules.index(matching_rule), rules.index(proxy_rule))
            self.assertNotIn("domain_suffix", matching_rule)

    def test_other_routes_and_dns_settings_are_preserved(self):
        cfg = base_config()
        original = copy.deepcopy(cfg)
        routing_safety.apply_game_bypass(cfg)
        self.assertEqual(first_domain_match(cfg["route"]["rules"], "spotify.com", "outbound"), "proxy-select")
        self.assertEqual(cfg["dns"]["servers"], original["dns"]["servers"])
        self.assertEqual(cfg["dns"]["rules"][1:], original["dns"]["rules"])
        self.assertEqual(cfg["route"]["rules"][5:], original["route"]["rules"][3:])
        self.assertEqual(cfg["route"]["final"], "direct")

    def test_reapplying_is_idempotent_and_keeps_dns_guard_first(self):
        cfg = base_config()
        self.assertTrue(routing_safety.apply_game_bypass(cfg))
        expected = copy.deepcopy(cfg)
        self.assertFalse(routing_safety.apply_game_bypass(cfg))
        self.assertEqual(cfg, expected)
        cfg["dns"]["rules"].reverse()
        self.assertTrue(routing_safety.apply_game_bypass(cfg))
        self.assertEqual(cfg, expected)

    def test_changed_default_dns_updates_guard_instead_of_duplicating_it(self):
        cfg = base_config()
        routing_safety.apply_game_bypass(cfg)
        cfg["dns"]["servers"].append({"type": "udp", "tag": "alternate", "server": "77.88.8.8"})
        cfg["dns"]["final"] = "alternate"
        routing_safety.apply_game_bypass(cfg)
        self.assertEqual(cfg["dns"]["rules"][0]["server"], "alternate")
        self.assertEqual(len(cfg["dns"]["rules"]), 2)

    def test_fakeip_default_falls_back_to_first_real_dns_server(self):
        cfg = base_config()
        cfg["dns"]["final"] = "fakeip"
        routing_safety.apply_game_bypass(cfg)
        self.assertEqual(cfg["dns"]["rules"][0]["server"], "google")

    def test_no_real_dns_server_does_not_create_invalid_reference(self):
        cfg = base_config()
        cfg["dns"]["servers"] = [{"type": "fakeip", "tag": "pool"}]
        original_dns = copy.deepcopy(cfg["dns"])
        routing_safety.apply_game_bypass(cfg)
        self.assertEqual(cfg["dns"], original_dns)

    def test_removed_real_dns_drops_stale_game_guard(self):
        cfg = base_config()
        routing_safety.apply_game_bypass(cfg)
        cfg["dns"]["servers"] = [{"type": "fakeip", "tag": "fakeip"}]
        cfg["dns"]["final"] = "fakeip"
        self.assertTrue(routing_safety.apply_game_bypass(cfg))
        self.assertEqual(cfg["dns"]["rules"], [{"domain_suffix": ["com"], "server": "fakeip"}])


if __name__ == "__main__":
    unittest.main()
