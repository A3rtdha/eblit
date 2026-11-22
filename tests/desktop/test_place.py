from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.place import center_in_rect, pick_screen, xy_for_screen


class CenterInRect(unittest.TestCase):
    def test_primary_fhd(self):
        self.assertEqual(center_in_rect(400, 620, 0, 0, 1920, 1040), (760, 210))

    def test_clamps_when_work_smaller(self):
        self.assertEqual(center_in_rect(400, 620, 0, 0, 300, 400), (0, 0))


class PickScreen(unittest.TestCase):
    def test_cursor_hits_second(self):
        a = SimpleNamespace(physical_x=0, physical_y=0, physical_width=1920, physical_height=1080)
        b = SimpleNamespace(physical_x=1920, physical_y=0, physical_width=1920, physical_height=1080)
        self.assertIs(pick_screen([a, b], (2000, 10)), b)

    def test_miss_falls_to_first(self):
        a = SimpleNamespace(physical_x=0, physical_y=0, physical_width=1920, physical_height=1080)
        self.assertIs(pick_screen([a], (-10, -10)), a)


class XyForScreen(unittest.TestCase):
    def test_prefers_working_area(self):
        frame = SimpleNamespace(X=0, Y=0, Width=1920, Height=1040)
        scr = SimpleNamespace(x=0, y=0, width=1920, height=1080, frame=frame)
        self.assertEqual(xy_for_screen(scr, 400, 620), (760, 210))


if __name__ == "__main__":
    unittest.main()
