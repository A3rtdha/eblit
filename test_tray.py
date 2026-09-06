"""Трей живёт в потоке основного процесса: окно ищем только своё, падение трея не уносит UI."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from app import tray


class OwnHwnd(unittest.TestCase):
    def test_skips_window_of_another_copy(self):
        with (
            patch.object(tray, "_pid_self", return_value=100),
            patch.object(tray, "_enum_top_windows", return_value=[11, 22, 33]),
            patch.object(tray, "_window_pid", side_effect={11: 999, 22: 100, 33: 100}.get),
            patch.object(tray, "_window_title", side_effect={11: "Eblit", 22: "Eblit", 33: "Eblit"}.get),
        ):
            self.assertEqual(tray.own_hwnd(), 22)

    def test_zero_when_no_window(self):
        with (
            patch.object(tray, "_pid_self", return_value=100),
            patch.object(tray, "_enum_top_windows", return_value=[11]),
            patch.object(tray, "_window_pid", return_value=100),
            patch.object(tray, "_window_title", return_value="Что-то другое"),
        ):
            self.assertEqual(tray.own_hwnd(), 0)


class WindowActions(unittest.TestCase):
    def test_show_without_window_is_noop(self):
        with (
            patch.object(tray, "own_hwnd", return_value=0),
            patch.object(tray, "user32") as u32,
        ):
            tray.show_window()
        u32.ShowWindow.assert_not_called()

    def test_show_restores_and_focuses(self):
        with (
            patch.object(tray, "own_hwnd", return_value=77),
            patch.object(tray, "user32") as u32,
        ):
            tray.show_window()
        u32.ShowWindow.assert_called_once_with(77, tray.SW_RESTORE)
        u32.SetForegroundWindow.assert_called_once_with(77)

    def test_quit_posts_close(self):
        with (
            patch.object(tray, "own_hwnd", return_value=77),
            patch.object(tray, "user32") as u32,
        ):
            tray.close_window()
        u32.PostMessageW.assert_called_once_with(77, tray.WM_CLOSE, 0, 0)


class StartTray(unittest.TestCase):
    def test_broken_tray_does_not_kill_window(self):
        with (
            patch.object(tray.pystray, "Icon", side_effect=OSError("нет шелла")),
            patch.object(tray, "write") as log,
        ):
            self.assertIsNone(tray.start_tray())
        log.assert_called_once()

    def test_runs_icon_off_the_main_thread(self):
        ran = threading.Event()
        main = threading.get_ident()
        seen: dict[str, int] = {}

        class FakeIcon:
            def run(self) -> None:
                seen["thread"] = threading.get_ident()
                ran.set()

        with (
            patch.object(tray.pystray, "Icon", return_value=FakeIcon()),
            patch.object(tray, "make_icon", return_value=object()),
        ):
            icon = tray.start_tray()
        self.assertIsNotNone(icon)
        self.assertTrue(ran.wait(2))
        self.assertNotEqual(seen["thread"], main)


if __name__ == "__main__":
    unittest.main()
