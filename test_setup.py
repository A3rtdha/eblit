"""Setup asset picking and WARP CLI path — no network."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.setup.assets import msiexec_args, pick_singbox_zip
from app.setup import ui
from app.stack import warp


class SingboxAsset(unittest.TestCase):
    def test_picks_windows_amd64_zip(self):
        url = pick_singbox_zip(
            [
                {"name": "sing-box-1.0-linux-amd64.tar.gz", "browser_download_url": "bad-linux"},
                {"name": "sing-box-1.0-windows-amd64.zip", "browser_download_url": "good"},
                {"name": "sing-box-1.0-windows-arm64.zip", "browser_download_url": "bad-arm"},
            ]
        )
        self.assertEqual(url, "good")

    def test_empty_assets(self):
        self.assertIsNone(pick_singbox_zip([]))
        self.assertIsNone(pick_singbox_zip([{"name": "source.tar.gz"}]))


class Msiexec(unittest.TestCase):
    def test_quiet_no_org(self):
        args = msiexec_args(Path(r"C:\tmp\warp.msi"))
        self.assertEqual(args[0], "msiexec")
        self.assertIn("/qn", args)
        self.assertTrue(any("warp.msi" in a for a in args))
        self.assertFalse(any("ORGANIZATION" in a for a in args))


class SetupUi(unittest.TestCase):
    def test_available_is_bool(self):
        self.assertIsInstance(ui.available(), bool)

    def test_tokens_match_eblit(self):
        self.assertEqual(ui.INK, "#09090b")
        self.assertEqual(ui.LIVE, "#8aaeb4")
        self.assertEqual(ui.FAULT, "#c47a7a")


class WarpCliPath(unittest.TestCase):
    def test_program_files_wins(self):
        fake = Path(r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe")
        with patch.object(warp, "_program_files_cli", return_value=fake), patch.object(
            Path, "is_file", return_value=True
        ):
            self.assertEqual(warp.cli_path(), str(fake))

    def test_falls_back_to_path(self):
        missing = Path(r"C:\missing\warp-cli.exe")
        with patch.object(warp, "_program_files_cli", return_value=missing), patch.object(
            Path, "is_file", return_value=False
        ):
            self.assertEqual(warp.cli_path(), "warp-cli")


if __name__ == "__main__":
    unittest.main()
