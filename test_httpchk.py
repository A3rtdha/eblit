"""test.bat: any HTTP/ is OK. health probe: only 2xx/3xx."""

from __future__ import annotations

import unittest

from app.stack.httpchk import has_http, live_exit, status_code


class Httpchk(unittest.TestCase):
    def test_empty_is_fail(self):
        self.assertFalse(has_http(""))
        self.assertFalse(live_exit(""))
        self.assertEqual(status_code(""), "")

    def test_bat_accepts_403(self):
        out = "HTTP/1.1 403 Forbidden\r\nserver: x\r\n"
        self.assertTrue(has_http(out))
        self.assertFalse(live_exit(out))
        self.assertEqual(status_code(out), "403")

    def test_200_is_live(self):
        out = "HTTP/2 200\r\n"
        self.assertTrue(has_http(out))
        self.assertTrue(live_exit(out))

    def test_302_is_live(self):
        self.assertTrue(live_exit("HTTP/1.1 302 Found"))


if __name__ == "__main__":
    unittest.main()
