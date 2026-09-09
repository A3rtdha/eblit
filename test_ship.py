"""nodes.sanitize_for_ship: в установщик не уходят личные данные сборщика."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.stack import nodes

ROOT = Path(__file__).resolve().parent


def _cfg() -> dict:
    return {
        "inbounds": [
            {"type": "tun", "tag": "tun-fastly", "route_address": ["151.101.0.0/16"]},
            {"type": "mixed", "tag": "mixed-local", "listen": "0.0.0.0", "listen_port": 2080},
        ],
        "outbounds": [
            {"type": "selector", "tag": "LagomVPN", "outbounds": ["MyPrivate"]},
            {"type": "vless", "tag": "Sweden", "server": "203.0.113.10", "uuid": "u"},
            {"type": "vless", "tag": "MyPrivate", "server": "1.2.3.4", "uuid": "secret"},
            {"type": "socks", "tag": "warp", "server": "127.0.0.1", "server_port": 40000},
            {"type": "direct", "tag": "direct"},
        ],
        "route": {"rules": [{"domain_suffix": ["grok.com"], "outbound": "LagomVPN"}]},
    }


class Sanitize(unittest.TestCase):
    def test_strips_every_vless(self):
        """Sweden ничем не лучше MyPrivate: оба — ключи с машины сборщика."""
        out = nodes.sanitize_for_ship(_cfg())
        tags = [o["tag"] for o in out["outbounds"] if o.get("type") == "vless"]
        self.assertEqual(tags, [])

    def test_selector_points_at_direct(self):
        out = nodes.sanitize_for_ship(_cfg())
        sel = next(o for o in out["outbounds"] if o.get("tag") == "LagomVPN")
        self.assertEqual(sel["outbounds"], ["direct"])

    def test_lan_reset_off(self):
        """Открытый прокси на 0.0.0.0 у чужого человека — нет."""
        out = nodes.sanitize_for_ship(_cfg())
        mixed = next(i for i in out["inbounds"] if i.get("tag") == "mixed-local")
        self.assertEqual(mixed["listen"], "127.0.0.1")

    def test_keeps_warp_direct_and_rules(self):
        out = nodes.sanitize_for_ship(_cfg())
        tags = [o.get("tag") for o in out["outbounds"]]
        self.assertIn("warp", tags)
        self.assertIn("direct", tags)
        self.assertNotIn("Sweden", tags)
        self.assertEqual(out["route"]["rules"][0]["domain_suffix"], ["grok.com"])

    def test_does_not_mutate_source(self):
        """Иначе pack мог бы записать в живой config.json сборщика 127.0.0.1 и выкинуть ноды."""
        src = _cfg()
        nodes.sanitize_for_ship(src)
        self.assertEqual(src["inbounds"][1]["listen"], "0.0.0.0")
        tags = [o["tag"] for o in src["outbounds"] if o.get("type") == "vless"]
        self.assertIn("MyPrivate", tags)
        self.assertIn("Sweden", tags)

    def test_has_user_vless(self):
        self.assertTrue(nodes.has_user_vless(_cfg()))
        only_stock = _cfg()
        only_stock["outbounds"] = [o for o in only_stock["outbounds"] if o.get("tag") != "MyPrivate"]
        self.assertFalse(nodes.has_user_vless(only_stock))
        self.assertFalse(nodes.has_user_vless({"outbounds": []}))
        self.assertFalse(nodes.has_user_vless({"outbounds": [{"type": "vless", "tag": ""}]}))

    def test_shipped_json_has_no_vless_secrets(self):
        blob = json.dumps(nodes.sanitize_for_ship(_cfg()))
        self.assertNotIn("secret", blob)
        self.assertNotIn('"uuid"', blob)
        self.assertNotIn("203.0.113.10", blob)

    def test_strips_node_bypass_rules(self):
        cfg = _cfg()
        cfg["route"]["rules"].extend(
            [
                {"domain_suffix": ["node.example.download"], "outbound": "direct"},
                {"ip_cidr": ["203.0.113.0/24"], "outbound": "direct"},
                {"ip_cidr": ["172.19.88.0/30"], "outbound": "direct"},
            ]
        )
        out = nodes.sanitize_for_ship(cfg)
        rules = out["route"]["rules"]
        self.assertTrue(any(r.get("ip_cidr") == ["172.19.88.0/30"] for r in rules))
        self.assertFalse(any(r.get("ip_cidr") == ["203.0.113.0/24"] for r in rules))
        self.assertFalse(
            any(r.get("domain_suffix") == ["node.example.download"] for r in rules)
        )


class LiveShip(unittest.TestCase):
    def test_example_and_live_lose_every_vless(self):
        """Именно этот файл pack кладёт в установщик — не стендовый _cfg()."""
        for name in ("config.example.json", "config.json"):
            path = ROOT / name
            if not path.is_file():
                continue
            out = nodes.sanitize_for_ship(json.loads(path.read_text(encoding="utf-8")))
            tags = [o["tag"] for o in out["outbounds"] if o.get("type") == "vless"]
            self.assertEqual(tags, [], msg=name)
            sel = next(o for o in out["outbounds"] if o.get("tag") == "LagomVPN")
            self.assertEqual(sel["outbounds"], ["direct"], msg=name)
            for rule in out.get("route", {}).get("rules", []):
                if not isinstance(rule, dict) or rule.get("outbound") != "direct":
                    continue
                cidrs = rule.get("ip_cidr")
                if isinstance(cidrs, list):
                    self.assertEqual(cidrs, ["172.19.88.0/30"], msg=name)


class ShipSkip(unittest.TestCase):
    def test_payload_skips_subscription_and_power(self):
        from app.pack import main as pack_main
        from app.setup import install

        self.assertIn("lagom-sub.json", install._SKIP_PAYLOAD)
        self.assertIn("eblit-power.json", install._SKIP_PAYLOAD)
        src = Path(pack_main.__code__.co_filename).read_text(encoding="utf-8")
        self.assertIn("eblit-power.json", src)


class BadLeg(unittest.TestCase):
    def test_first_bad_wins_box_over_others(self):
        from app.stack import probe

        legs = {
            "box": {"state": "bad", "why": "нет tun"},
            "warp": {"state": "bad", "why": "молчит"},
            "node": {"state": "ok", "why": ""},
        }
        self.assertEqual(probe.bad_leg_name(legs), "sing-box")

    def test_all_ok_is_none(self):
        from app.stack import probe

        legs = {"box": {"state": "ok"}, "warp": {"state": "ok"}, "node": {"state": "ok"}}
        self.assertIsNone(probe.bad_leg_name(legs))

    def test_node_only(self):
        from app.stack import probe

        legs = {"box": {"state": "ok"}, "warp": {"state": "ok"}, "node": {"state": "bad"}}
        self.assertEqual(probe.bad_leg_name(legs), "сервер")


if __name__ == "__main__":
    unittest.main()
