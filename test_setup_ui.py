"""Окно установки и маршруты входа. Окно создаётся скрытым, показов не будет."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.setup import ui

STEPS = (("a", "Шаг A"), ("b", "Шаг B"))


class WindowStates(unittest.TestCase):
    """Одно окно на класс: в бою Tk-root тоже ровно один, и пересоздание его не любит."""

    win = None

    @classmethod
    def setUpClass(cls):
        try:
            cls.win = ui.Window(STEPS)
        except Exception as exc:  # нет рабочего Tk — окна не будет и в бою
            raise unittest.SkipTest(f"Tk не поднялся: {exc}") from exc
        cls.win.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        if cls.win is not None:
            cls.win.root.destroy()
            cls.win = None

    def setUp(self):
        win = self.win
        while not win.queue.empty():
            win.queue.get_nowait()
        win.code = 1
        win.finished = False
        win.current = None
        win.done = 0
        win.detail.configure(text="", fg=ui.MUTE)
        win.status.configure(text="Идёт установка", fg=ui.LIVE)
        for key, label in win.steps:
            win._mark(key, ui.DIM, ui.DIM, filled=False)
            win.labels[key].configure(text=label, fg=ui.DIM)

    def pump(self):
        """Один проход обработчика: очередь наполняет рабочий поток, рисует главный."""
        self.win.finished = True  # без перепланирования after
        self.win._drain()

    def test_opens_with_installing_status(self):
        self.assertEqual(self.win.status.cget("text"), "Идёт установка")
        self.assertEqual(self.win.root.title(), "Eblit — установка")

    def test_step_marks_running_then_done(self):
        self.win.report("step", "a")
        self.win.report("step", "b")
        self.pump()
        self.assertEqual(self.win.labels["a"].cget("fg"), ui.MUTE)
        self.assertEqual(self.win.labels["b"].cget("fg"), ui.TEXT)
        self.assertEqual(self.win.current, "b")

    def test_log_goes_to_detail(self):
        self.win.report("log", "", "качаю WARP…")
        self.pump()
        self.assertEqual(self.win.detail.cget("text"), "качаю WARP…")

    def test_fail_marks_current_step_and_shows_why(self):
        self.win.report("step", "a")
        self.win.report("fail", "", "WARP не встал")
        self.pump()
        self.assertEqual(self.win.labels["a"].cget("fg"), ui.FAULT)
        self.assertEqual(self.win.detail.cget("text"), "WARP не встал")
        self.assertEqual(self.win.status.cget("text"), "Не получилось")
        self.assertEqual(self.win.code, 1)
        self.assertTrue(self.win.finished)

    def test_done_marks_everything_and_closes_itself(self):
        self.win.report("step", "a")
        self.win.report("done")
        with patch.object(self.win.root, "after") as after:
            self.pump()
        self.assertEqual(self.win.code, 0)
        self.assertEqual(self.win.status.cget("text"), "Готово")
        self.assertEqual(self.win.labels["b"].cget("fg"), ui.MUTE)
        after.assert_called_once()  # окно само уходит, кликать «Закрыть» не нужно

    def test_close_ignored_while_running(self):
        self.win.finished = False
        self.win._try_close()
        self.assertTrue(self.win.root.winfo_exists())

    def test_job_exception_becomes_fail_not_crash(self):
        def job(_report):
            raise OSError("нет сети")

        with patch.object(self.win.root, "mainloop"), patch.object(self.win.root, "after"):
            code = self.win.run(job)
        self.assertEqual(code, 1)  # mainloop замокан: код по умолчанию
        deadline = 0
        while self.win.queue.empty() and deadline < 200:
            deadline += 1
        kind, _key, text = self.win.queue.get(timeout=2)
        self.assertEqual(kind, "fail")
        self.assertIn("нет сети", text)


class Routes(unittest.TestCase):
    def route(self, args, admin_ok=True, gui=True):
        from app.setup import __main__ as entry

        with (
            patch.object(entry.admin, "is_admin", return_value=admin_ok),
            patch.object(entry.admin, "elevate_and_wait", return_value=(True, 7)) as elev,
            patch.object(entry, "_headless", return_value=11) as headless,
            patch.object(entry, "_windowed", return_value=12) as windowed,
            patch.object(entry, "_uninstall", return_value=13) as unin,
            patch.object(entry.ui, "available", return_value=gui),
        ):
            code = entry.main(args)
        return code, {"elev": elev, "headless": headless, "windowed": windowed, "unin": unin}

    def test_default_goes_to_window(self):
        code, calls = self.route([])
        self.assertEqual(code, 12)
        calls["windowed"].assert_called_once()

    def test_nogui_flag_goes_headless(self):
        code, calls = self.route(["--nogui"])
        self.assertEqual(code, 11)
        calls["headless"].assert_called_once()

    def test_no_tkinter_goes_headless(self):
        code, _calls = self.route([], gui=False)
        self.assertEqual(code, 11)

    def test_uninstall_route(self):
        code, calls = self.route(["--uninstall"])
        self.assertEqual(code, 13)
        calls["unin"].assert_called_once()

    def test_without_admin_elevates_and_returns_child_code(self):
        code, calls = self.route([], admin_ok=False)
        self.assertEqual(code, 7)
        calls["elev"].assert_called_once()
        calls["windowed"].assert_not_called()


class Headless(unittest.TestCase):
    def test_launches_app_after_success(self):
        from app.setup import __main__ as entry

        with (
            patch.object(entry, "run", return_value=0),
            patch.object(entry, "_launch") as launch,
            patch.object(entry, "_box"),
        ):
            self.assertEqual(entry._headless([]), 0)
        launch.assert_called_once()

    def test_failure_shows_reason_and_does_not_launch(self):
        from app.setup import __main__ as entry

        with (
            patch.object(entry, "run", side_effect=OSError("WARP не встал")),
            patch.object(entry, "_launch") as launch,
            patch.object(entry, "_box") as box,
            patch.object(entry.install, "log"),
        ):
            self.assertEqual(entry._headless([]), 1)
        launch.assert_not_called()
        self.assertIn("WARP не встал", box.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
