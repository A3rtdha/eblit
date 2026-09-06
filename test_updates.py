"""Semver and GitHub release payload — без сети."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.stack import updates
from app.version import VERSION


class Tag(unittest.TestCase):
    def test_parse_strips_v(self):
        self.assertEqual(updates.parse_tag("v1.2.3"), (1, 2, 3))
        self.assertEqual(updates.parse_tag("1.0.0"), (1, 0, 0))

    def test_newer(self):
        self.assertTrue(updates.is_newer("1.0.1", "1.0.0"))
        self.assertFalse(updates.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updates.is_newer("1.0.0", "1.0.1"))


class Check(unittest.TestCase):
    def test_404_is_no_release_not_error(self):
        err = HTTPError("https://x", 404, "no", hdrs=None, fp=None)
        with patch.object(updates, "_request", side_effect=err):
            result = updates.check()
        self.assertTrue(result["ok"])
        self.assertFalse(result["newer"])
        self.assertEqual(result["current"], VERSION)

    def test_picks_setup_asset(self):
        payload = {
            "tag_name": "v1.0.1",
            "html_url": "https://github.com/A3rtdha/eblit/releases/tag/v1.0.1",
            "assets": [
                {"name": "notes.txt", "browser_download_url": "https://example/notes"},
                {
                    "name": "EblitSetup.exe",
                    "browser_download_url": "https://github.com/A3rtdha/eblit/releases/download/v1.0.1/EblitSetup.exe",
                },
            ],
        }
        with patch.object(updates, "_request", return_value=json.dumps(payload).encode()):
            with patch.object(updates, "VERSION", "1.0.0"):
                result = updates.check()
        self.assertTrue(result["newer"])
        self.assertEqual(result["latest"], "1.0.1")
        self.assertTrue(result["asset"].endswith("EblitSetup.exe"))

    def test_same_version_is_not_newer(self):
        payload = {"tag_name": "v1.0.0", "assets": []}
        with patch.object(updates, "_request", return_value=json.dumps(payload).encode()):
            with patch.object(updates, "VERSION", "1.0.0"):
                result = updates.check()
        self.assertFalse(result["newer"])

    def test_network_error_is_honest(self):
        with patch.object(updates, "_request", side_effect=OSError("нет сети")):
            result = updates.check()
        self.assertFalse(result["ok"])
        self.assertIn("сети", result["why"])

    def test_download_rejects_tiny_blob(self):
        with patch.object(updates, "_request", return_value=b"not-an-exe"):
            with self.assertRaises(ValueError):
                updates.download("https://github.com/A3rtdha/eblit/releases/download/v1/EblitSetup.exe")

    def test_download_rejects_non_https(self):
        with self.assertRaises(ValueError):
            updates.download("http://evil.example/EblitSetup.exe")


if __name__ == "__main__":
    unittest.main()
