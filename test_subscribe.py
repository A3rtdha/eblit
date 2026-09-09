"""Подписка: мягкий разбор, синк не трогает ручной vless, фейл не стирает ноды."""

from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app.bridge import Bridge
from app.stack import nodes, subscribe


UUID_A = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
UUID_B = "11111111-2222-3333-4444-555555555555"
UUID_C = "cccccccc-dddd-4eee-8fff-000000000000"
PBK = "TESTKEY_" + "a" * 36


def vless_uri(tag="Finland", host="node.example", port=443, uuid=UUID_A) -> str:
    return (
        f"vless://{uuid}@{host}:{port}"
        f"?security=reality&sni={host}&pbk={PBK}"
        f"&fp=firefox&type=tcp#{tag}"
    )


def happ_xray_outbound(
    *,
    tag="Finland",
    host="node.example",
    port=443,
    uuid=UUID_A,
    security="reality",
    network="tcp",
    flow="xtls-rprx-vision",
    pbk=PBK,
) -> dict:
    stream = {"network": network, "security": security}
    if security == "reality" or pbk:
        stream["realitySettings"] = {
            "serverName": host,
            "publicKey": pbk,
            "fingerprint": "firefox",
        }
    if security == "tls":
        stream["tlsSettings"] = {"serverName": host}
    return {
        "tag": tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": host,
                    "port": port,
                    "users": [{"id": uuid, "encryption": "none", "flow": flow}],
                }
            ]
        },
        "streamSettings": stream,
    }


def happ_profile(*outbounds, remarks="Finland") -> dict:
    extras = [
        {"tag": "direct", "protocol": "freedom", "settings": {}},
        {"tag": "block", "protocol": "blackhole", "settings": {}},
    ]
    return {
        "dns": {"servers": ["1.1.1.1"]},
        "remarks": remarks,
        "outbounds": list(outbounds) + extras,
    }


BASE_CFG = {
    "outbounds": [
        {"type": "selector", "tag": "LagomVPN", "outbounds": ["Sweden"]},
        {
            "type": "vless",
            "tag": "Sweden",
            "server": "203.0.113.11",
            "server_port": 443,
            "uuid": UUID_B,
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


class ParseBody(unittest.TestCase):
    def test_plain_uri(self):
        got = subscribe.parse_body(vless_uri())
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["nodes"]), 1)
        self.assertEqual(got["nodes"][0]["tag"], "Finland")
        self.assertEqual(got["nodes"][0]["host"], "node.example")
        self.assertEqual(got["nodes"][0]["uuid"], UUID_A)

    def test_base64_list(self):
        raw = vless_uri() + "\n" + vless_uri("Sweden", "edge.example", uuid=UUID_B)
        blob = base64.b64encode(raw.encode()).decode()
        got = subscribe.parse_body(blob)
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["nodes"]), 2)
        tags = {n["tag"] for n in got["nodes"]}
        self.assertEqual(tags, {"Finland", "Sweden"})

    def test_vmess_and_vless_mix_keeps_vless(self):
        raw = "vmess://aaaa\n" + vless_uri() + "\ntrojan://x@h:443\n"
        got = subscribe.parse_body(raw)
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["nodes"]), 1)
        self.assertEqual(got["nodes"][0]["tag"], "Finland")
        self.assertGreaterEqual(got.get("skipped", 0), 1)

    def test_empty_is_zero_nodes(self):
        got = subscribe.parse_body("")
        self.assertFalse(got["ok"])
        self.assertEqual(got["nodes"], [])
        self.assertIn("why", got)

    def test_garbage_is_zero_nodes(self):
        got = subscribe.parse_body("hello world #clash yaml\nproxies:\n  - {type: ss}")
        self.assertFalse(got["ok"])
        self.assertEqual(got["nodes"], [])

    def test_clash_proxies_still_walk(self):
        payload = {
            "proxies": [
                {
                    "name": "Finland",
                    "type": "vless",
                    "server": "node.example",
                    "port": 443,
                    "uuid": UUID_A,
                    "servername": "node.example",
                    "reality-opts": {"public-key": PBK},
                    "network": "tcp",
                },
                {
                    "name": "Sweden",
                    "type": "vless",
                    "server": "edge.example",
                    "port": 443,
                    "uuid": UUID_B,
                    "sni": "edge.example",
                    "reality-opts": {"public-key": PBK},
                    "network": "tcp",
                },
            ]
        }
        got = subscribe.parse_body(json.dumps(payload))
        self.assertTrue(got["ok"])
        self.assertEqual({n["tag"] for n in got["nodes"]}, {"Finland", "Sweden"})

    def test_json_skips_vmess_keeps_vless(self):
        payload = {
            "outbounds": [
                {"type": "direct", "tag": "direct"},
                {"type": "vmess", "tag": "Skip", "server": "x.example", "uuid": UUID_A},
                {
                    "type": "vless",
                    "tag": "Sweden",
                    "server": "edge.example",
                    "server_port": 443,
                    "uuid": UUID_A,
                    "tls": {
                        "server_name": "edge.example",
                        "utls": {"fingerprint": "firefox"},
                        "reality": {"public_key": PBK},
                    },
                },
            ]
        }
        got = subscribe.parse_body(json.dumps(payload))
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["nodes"]), 1)
        self.assertEqual(got["nodes"][0]["tag"], "Sweden")

    def test_singbox_multi_vless_still_walks(self):
        payload = {
            "outbounds": [
                {
                    "type": "vless",
                    "tag": "Finland",
                    "server": "node.example",
                    "server_port": 443,
                    "uuid": UUID_A,
                    "tls": {
                        "server_name": "node.example",
                        "reality": {"public_key": PBK},
                    },
                },
                {
                    "type": "vless",
                    "tag": "Sweden",
                    "server": "edge.example",
                    "server_port": 443,
                    "uuid": UUID_B,
                    "tls": {
                        "server_name": "edge.example",
                        "reality": {"public_key": PBK},
                    },
                },
            ]
        }
        got = subscribe.parse_body(json.dumps(payload))
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["nodes"]), 2)
        self.assertEqual({n["tag"] for n in got["nodes"]}, {"Finland", "Sweden"})

    def test_happ_xray_profile_array(self):
        """Панель Happ: JSON-массив Xray-конфигов, не URI и не sing-box type=vless."""
        raw = json.dumps(
            [
                happ_profile(
                    happ_xray_outbound(tag="proxy"),
                    happ_xray_outbound(
                        tag="SkipTLS",
                        host="tls.example",
                        security="tls",
                        pbk="",
                    ),
                    happ_xray_outbound(
                        tag="SkipWS",
                        host="ws.example",
                        network="ws",
                    ),
                    remarks="Finland",
                ),
                happ_profile(
                    happ_xray_outbound(tag="proxy", host="edge.example", uuid=UUID_B),
                    happ_xray_outbound(
                        tag="extra-sweden",
                        host="spare.example",
                        uuid=UUID_C,
                    ),
                    remarks="Sweden",
                ),
            ]
        )
        got = subscribe.parse_body(raw)
        self.assertTrue(got["ok"], got.get("why"))
        self.assertEqual(len(got["nodes"]), 2)
        tags = {n["tag"] for n in got["nodes"]}
        self.assertEqual(tags, {"Finland", "Sweden"})
        self.assertNotIn("SkipTLS", tags)
        self.assertNotIn("SkipWS", tags)
        self.assertNotIn("proxy", tags)
        self.assertNotIn("extra-sweden", tags)
        finland = next(n for n in got["nodes"] if n["tag"] == "Finland")
        self.assertEqual(finland["host"], "node.example")
        self.assertEqual(finland["uuid"], UUID_A)
        self.assertEqual(finland["public_key"], PBK)
        self.assertEqual(finland["sni"], "node.example")
        self.assertEqual(finland["flow"], "xtls-rprx-vision")
        sweden = next(n for n in got["nodes"] if n["tag"] == "Sweden")
        self.assertEqual(sweden["host"], "edge.example")
        self.assertEqual(sweden["uuid"], UUID_B)
        self.assertGreaterEqual(got.get("skipped", 0), 4)

    def test_happ_xray_single_config(self):
        raw = json.dumps(
            happ_profile(happ_xray_outbound(tag="Italy", host="it.example"), remarks="Italy")
        )
        got = subscribe.parse_body(raw)
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["nodes"]), 1)
        self.assertEqual(got["nodes"][0]["tag"], "Italy")
        self.assertEqual(got["nodes"][0]["host"], "it.example")

    def test_happ_xray_pbk_without_security_field(self):
        ob = happ_xray_outbound(tag="Bare")
        ob["streamSettings"].pop("security", None)
        got = subscribe.parse_body(json.dumps(happ_profile(ob, remarks="Bare")))
        self.assertTrue(got["ok"])
        self.assertEqual(got["nodes"][0]["tag"], "Bare")

    def test_happ_profile_array_uses_remarks_not_extra_outbounds(self):
        """Один пользовательский сервер на профиль: remarks, не proxy-N / WL-*."""
        raw = json.dumps(
            [
                happ_profile(
                    happ_xray_outbound(
                        tag="WL-01-CON-01",
                        host="wl.example",
                        uuid=UUID_C,
                    ),
                    happ_xray_outbound(tag="proxy"),
                    happ_xray_outbound(
                        tag="proxy-2",
                        host="spare.example",
                        uuid=UUID_B,
                    ),
                    remarks="Germany",
                ),
                happ_profile(
                    happ_xray_outbound(tag="proxy", host="edge.example", uuid=UUID_B),
                    happ_xray_outbound(
                        tag="WL-01-CON-01",
                        host="wl.example",
                        uuid=UUID_C,
                    ),
                    happ_xray_outbound(
                        tag="proxy-2",
                        host="spare.example",
                        uuid=UUID_A,
                    ),
                    remarks="Netherlands",
                ),
            ]
        )
        got = subscribe.parse_body(raw)
        self.assertTrue(got["ok"], got.get("why"))
        self.assertEqual(len(got["nodes"]), 2)
        tags = [n["tag"] for n in got["nodes"]]
        self.assertEqual(tags, ["Germany", "Netherlands"])
        self.assertEqual(got["nodes"][0]["name"], "Germany")
        self.assertEqual(got["nodes"][0]["host"], "node.example")
        self.assertEqual(got["nodes"][0]["uuid"], UUID_A)
        self.assertEqual(got["nodes"][1]["host"], "edge.example")
        self.assertEqual(got["nodes"][1]["uuid"], UUID_B)
        extras = {"proxy", "proxy-2", "WL-01-CON-01"}
        self.assertFalse(extras & set(tags))

    def test_happ_profile_title_ps_name_meta(self):
        ps_only = dict(happ_profile(happ_xray_outbound(tag="proxy")))
        ps_only.pop("remarks")
        ps_only["ps"] = "Spain"
        named = dict(happ_profile(happ_xray_outbound(tag="proxy", host="edge.example", uuid=UUID_B)))
        named.pop("remarks")
        named["name"] = "Poland"
        meta = dict(
            happ_profile(happ_xray_outbound(tag="proxy", host="meta.example", uuid=UUID_C))
        )
        meta.pop("remarks")
        meta["meta"] = {"title": "Portugal"}
        got = subscribe.parse_body(json.dumps([ps_only, named, meta]))
        self.assertTrue(got["ok"], got.get("why"))
        self.assertEqual([n["tag"] for n in got["nodes"]], ["Spain", "Poland", "Portugal"])

    def test_flat_xray_outbound_list_still_walks(self):
        raw = json.dumps(
            [
                happ_xray_outbound(tag="proxy"),
                happ_xray_outbound(tag="proxy-2", host="edge.example", uuid=UUID_B),
            ]
        )
        got = subscribe.parse_body(raw)
        self.assertTrue(got["ok"])
        self.assertEqual(len(got["nodes"]), 2)
        self.assertEqual({n["tag"] for n in got["nodes"]}, {"proxy", "proxy-2"})


class SyncAndFetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-sub-")
        self.dir = Path(self.tmp.name)
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps(BASE_CFG), encoding="utf-8")
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def _tags(self) -> list[str]:
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        return [ob["tag"] for ob in cfg["outbounds"] if ob.get("type") == "vless"]

    def test_sync_keeps_manual_node(self):
        nodes.add(
            {
                "tag": "Mars",
                "name": "Mars",
                "host": "redplanet.example",
                "port": 443,
                "uuid": "99999999-aaaa-4bbb-8ccc-dddddddddddd",
                "sni": "redplanet.example",
                "fingerprint": "firefox",
                "public_key": PBK,
                "flow": "",
            }
        )
        parsed = subscribe.parse_body(vless_uri())
        result = subscribe.sync(parsed["nodes"])
        self.assertTrue(result["ok"])
        tags = self._tags()
        self.assertIn("Mars", tags)
        self.assertIn("Finland", tags)
        self.assertIn("Sweden", tags)

    def test_fetch_fail_does_not_delete_owned(self):
        parsed = subscribe.parse_body(vless_uri())
        subscribe.sync(parsed["nodes"])
        subscribe.set_url("https://panel.example/sub")
        self.assertIn("Finland", self._tags())
        with patch.object(subscribe, "_download", return_value=(None, "нет сети")):
            result = subscribe.refresh()
        self.assertFalse(result["ok"])
        self.assertIn("Finland", self._tags())
        self.assertIn("Sweden", self._tags())

    def test_zero_usable_does_not_wipe(self):
        parsed = subscribe.parse_body(vless_uri())
        subscribe.sync(parsed["nodes"])
        subscribe.set_url("https://panel.example/sub")
        with patch.object(subscribe, "_download", return_value=("vmess://aaaa", "")):
            result = subscribe.refresh()
        self.assertFalse(result["ok"])
        self.assertIn("Finland", self._tags())

    def test_duplicate_tags_get_suffix(self):
        raw = vless_uri("Finland", "a.example", uuid=UUID_A) + "\n" + vless_uri(
            "Finland", "b.example", uuid=UUID_B
        )
        result = subscribe.sync(subscribe.parse_body(raw)["nodes"])
        self.assertTrue(result["ok"])
        tags = self._tags()
        self.assertIn("Finland", tags)
        self.assertIn("Finland-2", tags)

    def test_manual_same_identity_not_duplicated(self):
        nodes.add(
            {
                "tag": "Home",
                "name": "Home",
                "host": "node.example",
                "port": 443,
                "uuid": UUID_A,
                "sni": "node.example",
                "fingerprint": "firefox",
                "public_key": PBK,
                "flow": "",
            }
        )
        result = subscribe.sync(subscribe.parse_body(vless_uri())["nodes"])
        self.assertTrue(result["ok"])
        tags = self._tags()
        self.assertEqual(tags.count("Home"), 1)
        self.assertNotIn("Finland", tags)
        owned = subscribe.get()["tags"]
        self.assertNotIn("Home", owned)

    def test_sync_fills_empty_selector(self):
        """Пустой LagomVPN → missing tags. Синк обязан выбрать живой тег."""
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        for ob in cfg["outbounds"]:
            if ob.get("tag") == "LagomVPN":
                ob["outbounds"] = []
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")
        result = subscribe.sync(subscribe.parse_body(vless_uri())["nodes"])
        self.assertTrue(result["ok"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        sel = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertTrue(sel["outbounds"])
        self.assertTrue(set(sel["outbounds"]) <= set(self._tags()) | {"direct"})

    def test_owned_gone_clears_favorite_and_selector(self):
        parsed = subscribe.parse_body(vless_uri("Finland"))
        subscribe.sync(parsed["nodes"])
        nodes.select("Finland")
        nodes.set_favorite("Finland")
        other = subscribe.parse_body(vless_uri("Japan", "jp.example", uuid=UUID_A))
        subscribe.sync(other["nodes"])
        tags = self._tags()
        self.assertNotIn("Finland", tags)
        self.assertIn("Japan", tags)
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        sel = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertTrue(sel["outbounds"])
        self.assertNotIn("Finland", sel["outbounds"])
        self.assertFalse((self.dir / nodes.FAV_FILE).is_file())
        self.assertFalse((self.dir / nodes.PICK_FILE).is_file())

    def test_sync_renames_stale_owned_tag_to_remarks(self):
        """Первый импорт писал proxy-2; refresh с remarks не должен оставлять старый тег."""
        stale = subscribe.parse_body(
            vless_uri("proxy-2") + "\n" + vless_uri("WL-01-CON-01", "wl.example", uuid=UUID_C)
        )
        subscribe.sync(stale["nodes"])
        nodes.add(
            {
                "tag": "Mars",
                "name": "Mars",
                "host": "redplanet.example",
                "port": 443,
                "uuid": "99999999-aaaa-4bbb-8ccc-dddddddddddd",
                "sni": "redplanet.example",
                "fingerprint": "firefox",
                "public_key": PBK,
                "flow": "",
            }
        )
        nodes.select("proxy-2")
        nodes.set_favorite("proxy-2")
        incoming = subscribe.parse_body(
            json.dumps([happ_profile(happ_xray_outbound(tag="proxy"), remarks="Germany")])
        )
        self.assertEqual(incoming["nodes"][0]["tag"], "Germany")
        result = subscribe.sync(incoming["nodes"])
        self.assertTrue(result["ok"])
        tags = self._tags()
        self.assertIn("Germany", tags)
        self.assertNotIn("proxy-2", tags)
        self.assertNotIn("WL-01-CON-01", tags)
        self.assertIn("Mars", tags)
        self.assertIn("Sweden", tags)
        self.assertEqual(subscribe.get()["tags"], ["Germany"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        sel = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertTrue(sel["outbounds"])
        self.assertIn("Germany", sel["outbounds"])
        self.assertNotIn("proxy-2", sel["outbounds"])
        alive = set(tags) | {"direct"}
        self.assertTrue(set(sel["outbounds"]) <= alive)
        fav = json.loads((self.dir / nodes.FAV_FILE).read_text(encoding="utf-8"))
        self.assertEqual(fav["tag"], "Germany")
        pick = json.loads((self.dir / nodes.PICK_FILE).read_text(encoding="utf-8"))
        self.assertEqual(pick["tag"], "Germany")
        hosts_map = nodes.hosts()
        self.assertIn("Germany", hosts_map)
        self.assertNotIn("proxy-2", hosts_map)
        self.assertNotIn("WL-01-CON-01", hosts_map)

    def test_sync_collapses_duplicate_owned_identity(self):
        """Два owned-тега на один uuid+host+port → одно remarks-имя."""
        subscribe.sync(subscribe.parse_body(vless_uri("proxy"))["nodes"])
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        proto = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "proxy")
        extra = json.loads(json.dumps(proto))
        extra["tag"] = "proxy-10"
        insert = next(i for i, ob in enumerate(cfg["outbounds"]) if ob.get("tag") == "warp")
        cfg["outbounds"].insert(insert, extra)
        self.cfg.write_text(json.dumps(cfg), encoding="utf-8")
        (self.dir / subscribe.SUB_FILE).write_text(
            json.dumps({"url": "", "tags": ["proxy", "proxy-10"]}) + "\n",
            encoding="utf-8",
        )
        incoming = subscribe.parse_body(
            json.dumps([happ_profile(happ_xray_outbound(tag="proxy"), remarks="Germany")])
        )
        result = subscribe.sync(incoming["nodes"])
        self.assertTrue(result["ok"])
        tags = self._tags()
        self.assertEqual(tags.count("Germany"), 1)
        self.assertNotIn("proxy", tags)
        self.assertNotIn("proxy-10", tags)
        self.assertEqual(subscribe.get()["tags"], ["Germany"])

    def test_rejects_http_and_happ(self):
        bad = subscribe.set_url("http://panel.example/sub")
        self.assertFalse(bad["ok"])
        happ = subscribe.set_url("happ://crypto")
        self.assertFalse(happ["ok"])
        self.assertFalse((self.dir / subscribe.SUB_FILE).is_file())

    def test_https_url_roundtrip(self):
        got = subscribe.set_url("https://panel.example/sub?token=1")
        self.assertTrue(got["ok"])
        self.assertEqual(subscribe.get()["url"], "https://panel.example/sub?token=1")

    def test_refresh_happ_xray_adds_nodes(self):
        subscribe.set_url("https://panel.example/sub")
        body = json.dumps(
            [
                happ_profile(happ_xray_outbound(tag="proxy"), remarks="Finland"),
                happ_profile(
                    happ_xray_outbound(tag="proxy", host="edge.example", uuid=UUID_B),
                    happ_xray_outbound(tag="Norway", host="spare.example", uuid=UUID_C),
                    remarks="Norway",
                ),
            ]
        )
        with patch.object(subscribe, "_download", return_value=(body, "")):
            result = subscribe.refresh()
        self.assertTrue(result["ok"], result.get("why"))
        tags = self._tags()
        self.assertIn("Finland", tags)
        self.assertIn("Norway", tags)
        self.assertIn("Sweden", tags)
        self.assertNotIn("proxy", tags)
        self.assertNotIn("proxy-2", tags)

    def test_ua_fallback_when_first_body_unusable(self):
        subscribe.set_url("https://panel.example/sub")
        bodies = ["garbage", vless_uri()]

        def download(_url, ua):
            if ua.startswith("Happ"):
                return bodies[0], ""
            return bodies[1], ""

        with patch.object(subscribe, "_download", side_effect=download) as dl:
            result = subscribe.refresh()
        self.assertTrue(result["ok"])
        self.assertIn("Finland", self._tags())
        uas = [call.args[1] for call in dl.call_args_list]
        self.assertTrue(any(u.startswith("Happ") for u in uas))
        self.assertTrue(any("v2rayN" in u for u in uas))

    def test_refresh_without_url_skips(self):
        result = subscribe.refresh()
        self.assertTrue(result.get("skipped") or result["ok"])
        self.assertEqual(self._tags(), ["Sweden"])

    def test_redirect_handler_rejects_http(self):
        handler = subscribe._HttpsOnlyRedirect()
        req = urllib.request.Request("https://panel.example/sub")
        with self.assertRaises(urllib.error.URLError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "http://evil.example/steal")
        self.assertIn("https", str(ctx.exception))

    def test_download_rejects_http_final_url(self):
        class Fake:
            def geturl(self):
                return "http://evil.example/steal"

            def read(self, _n):
                return b"vless://x"

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        with patch.object(subscribe, "_OPENER") as opener:
            opener.open.return_value = Fake()
            body, err = subscribe._download("https://panel.example/sub", subscribe.UA_HAPP)
        self.assertIsNone(body)
        self.assertIn("редирект", err)


class BridgeSub(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-sub-br-")
        self.dir = Path(self.tmp.name)
        (self.dir / "config.json").write_text(json.dumps(BASE_CFG), encoding="utf-8")
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_sub_refresh_does_not_use_job(self):
        api = Bridge()
        api._job = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("_job"))
        with patch.object(subscribe, "refresh", return_value={"ok": True, "nodes": []}):
            first = api.sub_refresh()
        self.assertTrue(first.get("pending"))
        self.assertFalse(api._busy)
        deadline = time.time() + 2
        while time.time() < deadline:
            if not api._sub_busy:
                break
            time.sleep(0.02)
        self.assertFalse(api._sub_busy)

    def test_sub_set_rejects_http(self):
        api = Bridge()
        api._job = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("_job"))
        result = api.sub_set("http://x")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
