"""Writable data dir when install folder is read-only (Program Files)."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import log as logmod
from app import paths


class DataRoot(unittest.TestCase):
    def setUp(self):
        paths.reset_data_root_cache()
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-data-")
        self.install = Path(self.tmp.name) / "install"
        self.install.mkdir()
        self.appdata = Path(self.tmp.name) / "LocalAppData" / "Eblit"
        (self.install / "config.json").write_text('{"outbounds":[]}\n', encoding="utf-8")
        (self.install / "lagom-sub.json").write_text('{"url":"https://x"}\n', encoding="utf-8")

    def tearDown(self):
        paths.reset_data_root_cache()
        self.tmp.cleanup()

    def _readonly(self, path: Path) -> None:
        path.chmod(stat.S_IREAD | stat.S_IEXEC)

    def test_dev_uses_repo_root(self):
        with patch.object(paths, "frozen", return_value=False):
            self.assertEqual(paths.data_root(), paths.root())

    def test_writable_install_keeps_data_there(self):
        with (
            patch.object(paths, "frozen", return_value=True),
            patch.object(paths, "root", return_value=self.install),
        ):
            got = paths.data_root()
        self.assertEqual(got, self.install.resolve())
        self.assertFalse((self.appdata / ".data-root-v1").exists())

    def test_readonly_install_migrates_to_appdata(self):
        env = {**os.environ, "LOCALAPPDATA": str(self.appdata.parent)}
        with (
            patch.object(paths, "frozen", return_value=True),
            patch.object(paths, "root", return_value=self.install),
            patch.object(paths, "_writable", return_value=False),
            patch.dict(os.environ, env, clear=False),
        ):
            paths.reset_data_root_cache()
            got = paths.data_root()
        self.assertEqual(got, self.appdata.resolve())
        self.assertTrue((self.appdata / "config.json").is_file())
        self.assertTrue((self.appdata / "lagom-sub.json").is_file())
        self.assertTrue((self.appdata / ".data-root-v1").is_file())

    def test_log_write_survives_readonly_log_dir(self):
        path = self.install / "split-ui.log"
        self._readonly(self.install)
        with patch.object(logmod, "LOG", path), patch("sys.stdout", None):
            logmod.write("set_favorite fail: test")


if __name__ == "__main__":
    unittest.main()
