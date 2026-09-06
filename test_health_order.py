"""Health try_order: favorite, last pick, config order, manual."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import health as m
from app.stack import nodes

TAGS = ["Finland", "Sweden", "USA", "Italy", "Germany", "UK", "Japan"]


def cfg_with_tags(tags: list[str]) -> dict:
    outbounds = [{"type": "selector", "tag": "LagomVPN", "outbounds": []}]
    for tag in tags:
        outbounds.append(
            {
                "type": "vless",
                "tag": tag,
                "server": "1.2.3.4",
                "server_port": 443,
                "uuid": "11111111-2222-3333-4444-555555555555",
            }
        )
    return {"outbounds": outbounds}


class TryOrder(unittest.TestCase):
    def test_config_order_without_favorite_or_pick(self):
        cfg = cfg_with_tags(TAGS)
        with (
            patch.object(m, "favorite_tag", return_value=None),
            patch.object(m, "last_pick", return_value=None),
        ):
            self.assertEqual(m.try_order(cfg), TAGS)

    def test_favorite_first(self):
        cfg = cfg_with_tags(TAGS)
        with (
            patch.object(m, "favorite_tag", return_value="Germany"),
            patch.object(m, "last_pick", return_value=None),
        ):
            self.assertEqual(m.try_order(cfg)[0], "Germany")

    def test_last_pick_after_favorite(self):
        cfg = cfg_with_tags(TAGS)
        with (
            patch.object(m, "favorite_tag", return_value="Germany"),
            patch.object(m, "last_pick", return_value="Sweden"),
        ):
            order = m.try_order(cfg)
            self.assertEqual(order[:2], ["Germany", "Sweden"])

    def test_sweden_last_pick_no_special_jump(self):
        cfg = cfg_with_tags(TAGS)
        with (
            patch.object(m, "favorite_tag", return_value=None),
            patch.object(m, "last_pick", return_value="Sweden"),
        ):
            order = m.try_order(cfg)
            self.assertEqual(order[0], "Sweden")
            self.assertEqual(order[1], "Finland")


class ResolveWithoutGoogle(unittest.TestCase):
    """Резолв хостов — системным DNS. DoH к dns.google ловил reCAPTCHA на домашний IP."""

    def test_uses_system_resolver(self):
        with patch.object(
            m.socket,
            "getaddrinfo",
            return_value=[(2, 1, 6, "", ("203.0.113.10", 0)), (2, 1, 6, "", ("8.8.8.8", 0))],
        ) as gai:
            self.assertEqual(m.resolve_one("node.example"), "203.0.113.10")
        gai.assert_called_once()

    def test_no_http_resolver_left(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        self.assertNotIn("https://dns.google", src)
        self.assertNotIn("urllib", src)


class ManualPick(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-health-")
        self.dir = Path(self.tmp.name)
        self.root_patch = patch("app.paths.root", return_value=self.dir)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_manual_tag_read(self):
        (self.dir / nodes.PICK_FILE).write_text(
            json.dumps({"tag": "Sweden", "ip": "1.1.1.1", "manual": True}),
            encoding="utf-8",
        )
        self.assertEqual(nodes.manual_tag(), "Sweden")

    def test_auto_clears_manual_flag(self):
        pick = self.dir / nodes.PICK_FILE
        pick.write_text(json.dumps({"tag": "Sweden", "ip": "1.1.1.1", "manual": True}), encoding="utf-8")
        (self.dir / "config.json").write_text(json.dumps(cfg_with_tags(TAGS)), encoding="utf-8")
        nodes.clear_manual()
        data = json.loads(pick.read_text(encoding="utf-8"))
        self.assertNotIn("manual", data)


if __name__ == "__main__":
    unittest.main()
