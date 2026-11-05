"""Pinned core downloads and local build state stay verifiable and isolated."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.core import build


class DownloadResponse(io.BytesIO):
    def geturl(self):
        return "https://downloads.example/core.zip"


class CoreBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-core-build-")
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_download_rejects_changed_bytes_before_publishing_file(self):
        path = self.root / "core.zip"
        expected = hashlib.sha256(b"trusted archive").hexdigest()
        with patch.object(build.urllib.request, "urlopen", return_value=DownloadResponse(b"changed")):
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                build.download_verified("https://downloads.example/core.zip", path, expected)
        self.assertFalse(path.exists())
        self.assertFalse(path.with_suffix(".zip.part").exists())

    def test_cached_download_is_verified_again(self):
        path = self.root / "core.zip"
        path.write_bytes(b"changed cache")
        expected = hashlib.sha256(b"trusted archive").hexdigest()
        with patch.object(build.urllib.request, "urlopen") as request:
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                build.download_verified("https://downloads.example/core.zip", path, expected)
        request.assert_not_called()

    def test_verified_download_can_be_reused_without_network(self):
        path = self.root / "core.zip"
        data = b"trusted archive"
        expected = hashlib.sha256(data).hexdigest()
        with patch.object(build.urllib.request, "urlopen", return_value=DownloadResponse(data)):
            build.download_verified("https://downloads.example/core.zip", path, expected)
        with patch.object(build.urllib.request, "urlopen") as request:
            build.download_verified("https://downloads.example/core.zip", path, expected)
        self.assertEqual(path.read_bytes(), data)
        request.assert_not_called()

    def test_zip_rejects_parent_path_before_extracting_any_entry(self):
        path = self.root / "toolchain.zip"
        target = self.root / "toolchain"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("go/bin/go.exe", b"trusted")
            archive.writestr("../outside.txt", b"escape")
        with self.assertRaisesRegex(ValueError, "leaves extraction directory"):
            build.extract_zip(path, target)
        self.assertFalse((self.root / "outside.txt").exists())
        self.assertFalse((target / "go/bin/go.exe").exists())

    def test_environment_ignores_user_go_overrides_and_keeps_caches_in_work_dir(self):
        manifest = json.loads(build.MANIFEST.read_text(encoding="utf-8"))
        with patch.dict(os.environ, {"GOFLAGS": "-mod=mod", "GOTOOLCHAIN": "auto", "GOSUMDB": "off"}):
            environment = build.build_environment(self.root, self.root / "go", manifest)
        self.assertEqual(environment["GOFLAGS"], "-mod=readonly")
        self.assertEqual(environment["GOTOOLCHAIN"], "local")
        self.assertEqual(environment["GOSUMDB"], "sum.golang.org")
        self.assertEqual(environment["GOWORK"], "off")
        self.assertEqual(environment["GOENV"], "off")
        for name in ("GOMODCACHE", "GOCACHE", "GOPATH"):
            self.assertTrue(Path(environment[name]).is_relative_to(self.root))
        self.assertEqual(environment["CGO_ENABLED"], "0")
        self.assertEqual(environment["GOOS"], "windows")
        self.assertEqual(environment["GOARCH"], "amd64")

    def test_manifest_pins_patch_and_handshake_sources(self):
        manifest = json.loads(build.MANIFEST.read_text(encoding="utf-8"))
        for name in ("patch", "handshake_test", "protocol_test"):
            item = manifest[name]
            build.verify_file(build.HERE / item["file"], item["sha256"])


if __name__ == "__main__":
    unittest.main()
