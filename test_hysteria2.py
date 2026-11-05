"""Hysteria2 subscription import and sync, without network requests."""

from __future__ import annotations

import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import hysteria2, nodes, subscribe
from test_subscribe import BASE_CFG, UUID_A, happ_profile, happ_xray_outbound, vless_uri


PIN_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
PIN_BASE64 = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="


def xray_hysteria(*, tag="proxy", host="hy.example", password="Secret-Auth") -> dict:
    return {
        "tag": tag,
        "protocol": "hysteria",
        "settings": {"version": 2, "address": host, "port": 443},
        "streamSettings": {
            "network": "hysteria",
            "security": "tls",
            "tlsSettings": {
                "serverName": host,
                "alpn": ["h3"],
                "minVersion": "1.3",
                "maxVersion": "1.3",
                "pinnedPeerCertSha256": PIN_HEX,
            },
            "hysteriaSettings": {"version": 2, "auth": password},
            "finalmask": {
                "quicParams": {"congestion": "bbr", "keepAlivePeriod": 10, "maxIdleTimeout": 30},
                "udp": [{"type": "salamander", "settings": {"password": "Mask-Password"}}],
            },
        },
        "domainStrategy": "AsIs",
    }


def native_hysteria() -> dict:
    return {
        "type": "hysteria2",
        "tag": "Native",
        "server": "hy.example",
        "server_port": 443,
        "password": "Secret-Auth",
        "network": "tcp",
        "obfs": {"type": "salamander", "password": "Mask-Password"},
        "tls": {
            "enabled": True,
            "server_name": "hy.example",
            "alpn": ["h3"],
            "certificate_sha256": [PIN_BASE64],
            "insecure": False,
        },
    }


def hy2_uri(scheme="hy2") -> str:
    return (
        f"{scheme}://Mixed%3Apassword@hy.example:443/"
        f"?sni=hy.example&pinSHA256={PIN_HEX}"
        "&obfs=salamander&obfs-password=Mask-Password#France"
    )


class ParseHysteria2(unittest.TestCase):
    def test_happ_profile_preserves_auth_mask_tls_and_full_certificate_pin(self):
        body = json.dumps(happ_profile(xray_hysteria(), remarks="France"))
        parsed = subscribe.parse_body(body)
        self.assertTrue(parsed["ok"], parsed.get("why"))
        self.assertEqual(len(parsed["nodes"]), 1)
        node = parsed["nodes"][0]
        self.assertEqual(node["type"], "hysteria2")
        self.assertEqual(node["tag"], "France")
        self.assertEqual(node["password"], "Secret-Auth")
        outbound = nodes.parsed_to_outbound(node)
        self.assertEqual(outbound["server"], "hy.example")
        self.assertEqual(outbound["server_port"], 443)
        self.assertEqual(outbound["obfs"], {"type": "salamander", "password": "Mask-Password"})
        self.assertEqual(outbound["tls"], {
            "enabled": True,
            "server_name": "hy.example",
            "alpn": ["h3"],
            "min_version": "1.3",
            "max_version": "1.3",
            "certificate_sha256": [PIN_BASE64],
        })
        self.assertEqual(outbound["idle_timeout"], "30s")
        self.assertEqual(outbound["keep_alive_period"], "10s")
        self.assertNotIn("up_mbps", outbound)
        self.assertNotIn("down_mbps", outbound)
        self.assertNotIn("certificate_public_key_sha256", outbound["tls"])
        self.assertNotIn("insecure", outbound["tls"])

    def test_explicit_insecure_is_preserved_without_removing_the_pin(self):
        outbound = xray_hysteria()
        outbound["streamSettings"]["tlsSettings"]["allowInsecure"] = True
        node = hysteria2.from_xray(outbound)
        self.assertIsNotNone(node)
        converted = hysteria2.to_outbound(node)
        self.assertTrue(converted["tls"]["insecure"])
        self.assertEqual(converted["tls"]["certificate_sha256"], [PIN_BASE64])

    def test_mixed_profiles_choose_only_the_primary_server(self):
        profiles = [
            happ_profile(
                happ_xray_outbound(tag="spare"),
                xray_hysteria(),
                xray_hysteria(tag="extra", host="spare.example"),
                remarks="Hysteria primary",
            ),
            happ_profile(
                xray_hysteria(tag="spare"),
                happ_xray_outbound(tag="proxy"),
                remarks="VLESS primary",
            ),
        ]
        parsed = subscribe.parse_body(json.dumps(profiles))
        self.assertTrue(parsed["ok"], parsed.get("why"))
        self.assertEqual(len(parsed["nodes"]), 2)
        first, second = parsed["nodes"]
        self.assertEqual((first["tag"], first["type"], first["host"]), ("Hysteria primary", "hysteria2", "hy.example"))
        self.assertEqual((second["tag"], second.get("type", "vless")), ("VLESS primary", "vless"))

    def test_invalid_happ_server_is_skipped_and_vless_survives(self):
        mutations = [
            (("settings", "version"), 1),
            (("settings", "version"), 2.0),
            (("settings", "port"), True),
            (("settings", "port"), 443.5),
            (("settings", "port"), 0),
            (("settings", "port"), 65536),
            (("settings", "port"), "443.0"),
            (("settings", "address"), True),
            (("streamSettings", "hysteriaSettings", "auth"), ""),
            (("streamSettings", "hysteriaSettings", "auth"), 42),
            (("streamSettings", "hysteriaSettings", "version"), 2.0),
            (("streamSettings", "hysteriaSettings", "udpIdleTimeout"), 60),
            (("streamSettings", "tlsSettings", "pinnedPeerCertSha256"), ""),
            (("streamSettings", "tlsSettings", "pinnedPeerCertSha256"), "bad"),
            (("streamSettings", "tlsSettings", "pinnedPeerCertificateChainSha256"), [PIN_BASE64]),
            (("streamSettings", "tlsSettings", "certificateFile"), "/provider/server.pem"),
            (("streamSettings", "tlsSettings", "minVersion"), []),
            (("streamSettings", "tlsSettings", "maxVersion"), {}),
            (("streamSettings", "tlsSettings", "maxVersion"), "1.2"),
            (("streamSettings", "tlsSettings", "allowInsecure"), "true"),
            (("streamSettings", "tlsSettings", "serverName"), True),
            (("streamSettings", "tlsSettings", "serverName"), False),
            (("streamSettings", "tlsSettings", "serverName"), []),
            (("streamSettings", "security"), "none"),
            (("streamSettings", "method"), "tcp"),
            (("streamSettings", "sockopt"), {"dialerProxy": "another-outbound"}),
            (("proxySettings",), {"tag": "another-outbound"}),
            (("sendThrough",), "192.0.2.1"),
            (("streamSettings", "finalmask", "udp"), [{"type": "gecko", "settings": {"password": "mask"}}]),
            (("streamSettings", "finalmask", "udp"), [{"type": "salamander", "settings": {"password": ""}}]),
            (("streamSettings", "finalmask", "udp"), [{"type": "salamander", "settings": {"password": "mask", "extra": True}}]),
            (("streamSettings", "finalmask", "tcp"), [{"type": "fragment"}]),
            (("streamSettings", "finalmask", "quicParams", "congestion"), "brutal"),
            (("streamSettings", "finalmask", "quicParams", "keepAlivePeriod"), float("inf")),
            (("streamSettings", "finalmask", "quicParams", "keepAlivePeriod"), 10 ** 1000),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                outbound = xray_hysteria()
                target = outbound
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertIsNone(hysteria2.from_xray(outbound))
                profiles = [
                    happ_profile(outbound, remarks="Broken Hysteria2"),
                    happ_profile(happ_xray_outbound(tag="proxy"), remarks="VLESS"),
                ]
                parsed = subscribe.parse_body(json.dumps(profiles))
                self.assertTrue(parsed["ok"], parsed.get("why"))
                self.assertEqual([node["tag"] for node in parsed["nodes"]], ["VLESS"])

    def test_native_json_keeps_tcp_only_restriction_and_tls_pin(self):
        original = native_hysteria()
        parsed = subscribe.parse_body(json.dumps({"outbounds": [original]}))
        self.assertTrue(parsed["ok"], parsed.get("why"))
        self.assertEqual(len(parsed["nodes"]), 1)
        self.assertEqual(hysteria2.to_outbound(parsed["nodes"][0]), original)

    def test_native_unsupported_constraints_and_malformed_types_are_skipped(self):
        mutations = [
            (("network",), "invalid"),
            (("network",), []),
            (("server_port",), False),
            (("server_port",), 443.5),
            (("server_ports",), ["1000:2000"]),
            (("detour",), "other-server"),
            (("realm",), {"server_url": "https://realm.example"}),
            (("tls", "certificate_path"), "/provider/server.pem"),
            (("tls", "certificate_sha256"), []),
            (("tls", "certificate_sha256"), ["bad"]),
            (("tls", "min_version"), []),
            (("tls", "max_version"), {}),
            (("tls", "enabled"), False),
            (("obfs", "type"), "gecko"),
            (("obfs", "extra"), True),
        ]
        for path, value in mutations:
            with self.subTest(path=path, value=value):
                outbound = native_hysteria()
                target = outbound
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertIsNone(hysteria2.from_singbox(outbound))

    def test_both_uri_schemes_preserve_password_obfuscation_and_pin(self):
        for scheme in ("hy2", "hysteria2"):
            with self.subTest(scheme=scheme):
                parsed = subscribe.parse_body(hy2_uri(scheme))
                self.assertTrue(parsed["ok"], parsed.get("why"))
                node = parsed["nodes"][0]
                self.assertEqual(node["password"], "Mixed:password")
                self.assertEqual(node["certificate_sha256"], [PIN_BASE64])
                self.assertEqual(node["obfs"], {"type": "salamander", "password": "Mask-Password"})
                self.assertNotIn("insecure", node)

    def test_uri_userpass_and_encoded_password_are_preserved(self):
        node = hysteria2.parse_uri("hy2://User:Pass%3Aword@hy.example:443?sni=hy.example")
        self.assertIsNotNone(node)
        self.assertEqual(node["password"], "User:Pass:word")

    def test_base64_can_contain_only_hysteria_or_a_mixed_list(self):
        for raw, expected in (
            (hy2_uri(), {"hysteria2"}),
            (hy2_uri() + "\n" + vless_uri(), {"hysteria2", "vless"}),
        ):
            with self.subTest(expected=expected):
                parsed = subscribe.parse_body(base64.b64encode(raw.encode()).decode())
                self.assertTrue(parsed["ok"], parsed.get("why"))
                self.assertEqual({node.get("type", "vless") for node in parsed["nodes"]}, expected)

    def test_invalid_uri_constraints_are_not_silently_dropped(self):
        for query in (
            "pinSHA256=", "pinSHA256=bad", "insecure=maybe", "mport=1000-2000",
            "realm=https%3A%2F%2Frealm.example", "obfs=gecko&obfs-password=mask",
            "obfs=salamander", "unknown-tls-pin=some-value",
        ):
            with self.subTest(query=query):
                self.assertIsNone(hysteria2.parse_uri("hy2://password@hy.example:443?" + query))


class SyncHysteria2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-hy2-sync-")
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.config_path = self.directory / "config.json"
        self.config_path.write_text(json.dumps(BASE_CFG), encoding="utf-8")
        root_patch = patch("app.paths.root", return_value=self.directory)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def read_config(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def test_refresh_is_repeatable_and_preserves_manual_vless(self):
        original_manual = copy.deepcopy(BASE_CFG["outbounds"][1])
        body = json.dumps([happ_profile(xray_hysteria(), remarks="France")])
        subscribe.set_url("https://panel.example/sub?format=happ")
        with patch.object(subscribe, "_download", return_value=(body, "")):
            self.assertTrue(subscribe.refresh()["ok"])
            first = self.config_path.read_bytes()
            self.assertTrue(subscribe.refresh()["ok"])
        self.assertEqual(self.config_path.read_bytes(), first)
        self.assertEqual(subscribe.get()["tags"], ["France"])
        servers = [ob for ob in self.read_config()["outbounds"] if nodes.is_server(ob)]
        self.assertEqual(len(servers), 2)
        self.assertIn(original_manual, servers)
        self.assertEqual(next(ob for ob in servers if ob["type"] == "hysteria2")["password"], "Secret-Auth")

    def test_manual_hysteria_with_the_same_identity_is_not_duplicated_or_owned(self):
        manual = hysteria2.from_xray(xray_hysteria(tag="Home"))
        nodes.add(manual)
        incoming = subscribe.parse_body(json.dumps(happ_profile(xray_hysteria(), remarks="France")))
        result = subscribe.sync(incoming["nodes"])
        self.assertTrue(result["ok"], result.get("why"))
        servers = [ob for ob in self.read_config()["outbounds"] if ob.get("type") == "hysteria2"]
        self.assertEqual([ob["tag"] for ob in servers], ["Home"])
        self.assertEqual(subscribe.get()["tags"], [])

    def test_hysteria_only_import_populates_an_empty_selector_and_roster(self):
        config = self.read_config()
        config["outbounds"] = [ob for ob in config["outbounds"] if ob.get("type") != "vless"]
        config["outbounds"][0]["outbounds"] = []
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        incoming = subscribe.parse_body(json.dumps(happ_profile(xray_hysteria(), remarks="France")))
        result = subscribe.sync(incoming["nodes"])
        self.assertTrue(result["ok"], result.get("why"))
        self.assertEqual([row["tag"] for row in result["nodes"]], ["France"])
        selector = next(ob for ob in self.read_config()["outbounds"] if ob.get("tag") == "proxy-select")
        self.assertEqual(selector["outbounds"], ["France"])

    def test_credentials_are_case_sensitive_and_protocols_do_not_collide(self):
        body = json.dumps([
            happ_profile(xray_hysteria(host="node.example", password=UUID_A), remarks="Hysteria lower"),
            happ_profile(xray_hysteria(host="node.example", password=UUID_A.upper()), remarks="Hysteria upper"),
            happ_profile(happ_xray_outbound(tag="proxy", host="node.example", uuid=UUID_A), remarks="VLESS"),
        ])
        incoming = subscribe.parse_body(body)
        self.assertTrue(incoming["ok"], incoming.get("why"))
        self.assertTrue(subscribe.sync(incoming["nodes"])["ok"])
        self.assertTrue(subscribe.sync(incoming["nodes"])["ok"])
        self.assertEqual(set(subscribe.get()["tags"]), {"Hysteria lower", "Hysteria upper", "VLESS"})
        imported = [ob for ob in self.read_config()["outbounds"] if ob.get("tag") in subscribe.get()["tags"]]
        self.assertEqual(len(imported), 3)
        self.assertEqual({ob["password"] for ob in imported if ob["type"] == "hysteria2"}, {UUID_A, UUID_A.upper()})


if __name__ == "__main__":
    unittest.main()
