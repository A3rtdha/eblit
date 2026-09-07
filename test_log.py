"""Console log must not crash Windows charmap on Cyrillic / ⚡ in tags."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import log as logmod
from app.stack import health


def charmap_stdout() -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", line_buffering=True)


class CharmapConsole(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-log-")
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_write_cyrillic_tag_does_not_raise(self):
        path = self.dir / "split-ui.log"
        with patch.object(logmod, "LOG", path), patch("sys.stdout", charmap_stdout()):
            logmod.write("de Германия ⚡")
        text = path.read_text(encoding="utf-8")
        self.assertIn("Германия ⚡", text)

    def test_health_log_cyrillic_tag_does_not_raise(self):
        with (
            patch.object(health, "_dir", return_value=self.dir),
            patch("sys.stdout", charmap_stdout()),
        ):
            health.log("de Германия ⚡")
        text = (self.dir / "health.log").read_text(encoding="utf-8")
        self.assertIn("Германия ⚡", text)

    def test_echo_none_stdout_does_not_raise(self):
        with patch("sys.stdout", None):
            logmod.echo("de Германия ⚡")


if __name__ == "__main__":
    unittest.main()
