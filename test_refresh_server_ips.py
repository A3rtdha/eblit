"""favorite_tag by host still resolves a tag from hosts() mapping."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import health as m


class FavoriteByHost(unittest.TestCase):
    def test_favorite_by_host(self):
        path = Path(__file__).resolve().parent / "_fav_order_test.json"
        path.write_text('{"host": "node.example"}\n', encoding="utf-8")
        try:
            with (
                patch.object(m, "_fav", return_value=path),
                patch("app.stack.nodes.vless_tags", return_value=["Alpha", "Beta"]),
                patch(
                    "app.stack.nodes.hosts",
                    return_value={"Alpha": "other.example", "Beta": "node.example"},
                ),
            ):
                self.assertEqual(m.favorite_tag(), "Beta")
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
