"""WARP CLI: регистрация, смена режима, демон. Без живого warp-cli."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from app.stack import warp


def proc(args, code=0, out="", err=""):
    return subprocess.CompletedProcess(list(args), code, out, err)


class CliPath(unittest.TestCase):
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


class Configure(unittest.TestCase):
    def setUp(self):
        self.calls: list[list[str]] = []

        def fake(args, **_kw):
            cmd = list(args)[1:]
            self.calls.append(cmd)
            return proc(args, 0)

        self.enter = patch.object(warp, "hidden", side_effect=fake)
        self.enter.start()
        self.addCleanup(self.enter.stop)
        self.path = patch.object(warp, "cli_path", return_value="warp-cli")
        self.path.start()
        self.addCleanup(self.path.stop)
        silent = patch.object(warp, "write")
        silent.start()
        self.addCleanup(silent.stop)

    def test_disconnects_before_mode_change(self):
        """Иначе mode proxy падает, пока клиент уже в туннеле — SOCKS :40000 не встаёт."""
        warp.configure()
        self.assertEqual(self.calls[0], ["disconnect"])
        self.assertIn(["mode", "proxy"], self.calls)
        self.assertLess(self.calls.index(["disconnect"]), self.calls.index(["mode", "proxy"]))

    def test_falls_back_to_legacy_set_mode(self):
        def fake(args, **_kw):
            cmd = list(args)[1:]
            self.calls.append(cmd)
            code = 1 if cmd[:1] == ["mode"] else 0
            return proc(args, code, err="unrecognized")

        with patch.object(warp, "hidden", side_effect=fake):
            warp.configure()
        self.assertIn(["set-mode", "proxy"], self.calls)

    def test_falls_back_to_legacy_proxy_port(self):
        def fake(args, **_kw):
            cmd = list(args)[1:]
            self.calls.append(cmd)
            code = 1 if cmd[:2] == ["proxy", "port"] else 0
            return proc(args, code, err="unrecognized")

        with patch.object(warp, "hidden", side_effect=fake):
            warp.configure()
        self.assertIn(["set-proxy-port", "40000"], self.calls)


class Registration(unittest.TestCase):
    def test_skips_new_when_already_registered(self):
        calls: list[list[str]] = []

        def fake(args, **_kw):
            cmd = list(args)[1:]
            calls.append(cmd)
            return proc(args, 0, out="Account: free")

        with patch.object(warp, "hidden", side_effect=fake), patch.object(
            warp, "cli_path", return_value="warp-cli"
        ):
            self.assertTrue(warp.ensure_registration())
        self.assertIn(["registration", "show"], calls)
        self.assertFalse(any(cmd[:2] == ["registration", "new"] or cmd[-1:] == ["register"] for cmd in calls))

    def test_new_syntax_then_legacy_register(self):
        calls: list[list[str]] = []

        def fake(args, **_kw):
            cmd = list(args)[1:]
            calls.append(cmd)
            if cmd == ["registration", "show"]:
                return proc(args, 1, err="Registration missing")
            if "new" in cmd:
                return proc(args, 1, err="unrecognized")
            if cmd == ["register"] or cmd[-1:] == ["register"]:
                return proc(args, 0)
            return proc(args, 1)

        with patch.object(warp, "hidden", side_effect=fake), patch.object(
            warp, "cli_path", return_value="warp-cli"
        ), patch.object(warp, "write"):
            self.assertTrue(warp.ensure_registration())
        self.assertTrue(any("new" in cmd for cmd in calls))
        self.assertTrue(any(cmd[-1] == "register" for cmd in calls))


class Connect(unittest.TestCase):
    def test_registers_before_connect(self):
        with (
            patch.object(warp, "ensure_registration", return_value=True) as reg,
            patch.object(warp, "configure") as cfg,
            patch.object(warp, "_run") as run,
        ):
            run.return_value = proc(["warp-cli", "connect"], 0)
            warp.configure_and_connect()
        reg.assert_called_once()
        cfg.assert_called_once()
        self.assertEqual(run.call_args[0], ("connect",))


class Daemon(unittest.TestCase):
    def test_not_ready_when_daemon_missing(self):
        def fake(args, **_kw):
            return proc(args, 1, err="Unable to connect to CloudflareWARP daemon")

        with patch.object(warp, "hidden", side_effect=fake), patch.object(
            warp, "cli_path", return_value="warp-cli"
        ):
            self.assertFalse(warp.daemon_ready())

    def test_ready_when_status_returns(self):
        def fake(args, **_kw):
            return proc(args, 0, out="Status update: Disconnected")

        with patch.object(warp, "hidden", side_effect=fake), patch.object(
            warp, "cli_path", return_value="warp-cli"
        ):
            self.assertTrue(warp.daemon_ready())


class GuiPath(unittest.TestCase):
    def test_sits_next_to_cli(self):
        fake = Path(r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe")
        with patch.object(warp, "_program_files_cli", return_value=fake):
            self.assertEqual(
                warp.gui_path(),
                Path(r"C:\Program Files\Cloudflare\Cloudflare WARP\Cloudflare WARP.exe"),
            )


class OpenGui(unittest.TestCase):
    def test_missing_exe_is_false(self):
        missing = Path(r"C:\missing\Cloudflare WARP.exe")
        with patch.object(warp, "gui_path", return_value=missing):
            self.assertFalse(warp.open_gui())

    def test_popen_oserror_is_false(self):
        exe = Path(r"C:\Program Files\Cloudflare\Cloudflare WARP\Cloudflare WARP.exe")
        with (
            patch.object(warp, "gui_path", return_value=exe),
            patch.object(Path, "is_file", return_value=True),
            patch("app.stack.warp.subprocess.Popen", side_effect=OSError("нет")),
        ):
            self.assertFalse(warp.open_gui())

    def test_popen_visible_not_hidden(self):
        from app.stack.run import CREATE_NO_WINDOW

        exe = Path(r"C:\Program Files\Cloudflare\Cloudflare WARP\Cloudflare WARP.exe")
        with (
            patch.object(warp, "gui_path", return_value=exe),
            patch.object(Path, "is_file", return_value=True),
            patch("app.stack.warp.subprocess.Popen") as popen,
            patch("app.stack.warp.hidden") as hidden,
        ):
            self.assertTrue(warp.open_gui())
        hidden.assert_not_called()
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], str(exe))
        self.assertNotEqual(kwargs.get("creationflags", 0), CREATE_NO_WINDOW)


class WaitReady(unittest.TestCase):
    def test_short_tries_stops_early(self):
        with (
            patch.object(warp, "socks_ok", return_value=False) as socks,
            patch.object(warp.time, "sleep") as sleep,
        ):
            self.assertFalse(warp.wait_ready(tries=3))
        self.assertEqual(socks.call_count, 3)
        self.assertEqual(sleep.call_count, 3)


if __name__ == "__main__":
    unittest.main()
