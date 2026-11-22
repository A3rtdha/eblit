"""Setup downloads, core verification and WARP CLI path — no network."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.setup import fetch, ui
from app.setup.assets import msiexec_args
from app.stack import warp


class PinnedSingbox(unittest.TestCase):
    def test_changed_binary_is_rejected_even_with_the_expected_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sing-box.exe"
            path.write_bytes(b"abc")
            expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
            with patch.object(fetch, "SINGBOX_SHA256", expected):
                fetch.verify_singbox(path)
                path.write_bytes(b"abcd")
                with self.assertRaisesRegex(OSError, "контрольная сумма"):
                    fetch.verify_singbox(path)


class Download(unittest.TestCase):
    def test_download_saves_the_response(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "downloads" / "setup.exe"
            with patch.object(fetch.urllib.request, "urlopen", return_value=io.BytesIO(b"setup")) as request:
                fetch.download("https://example.test/setup.exe", destination, timeout=180)
            self.assertEqual(destination.read_bytes(), b"setup")
            self.assertEqual(request.call_args.args[0].full_url, "https://example.test/setup.exe")
            self.assertEqual(request.call_args.kwargs["timeout"], 180)

    def test_empty_download_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "setup.exe"
            with patch.object(fetch.urllib.request, "urlopen", return_value=io.BytesIO(b"")):
                with self.assertRaisesRegex(OSError, "пустая загрузка"):
                    fetch.download("https://example.test/setup.exe", destination)
            self.assertFalse(destination.exists())


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
