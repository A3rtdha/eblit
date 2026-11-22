from __future__ import annotations

import unittest
from unittest.mock import patch

from app.stack import autostart


class AutostartCommand(unittest.TestCase):
    def test_quotes_spaces(self):
        with patch.object(autostart, "argv0", return_value=[r"C:\Program Files\Eblit\Eblit.exe"]):
            self.assertEqual(autostart.command(), r'"C:\Program Files\Eblit\Eblit.exe"')


if __name__ == "__main__":
    unittest.main()
