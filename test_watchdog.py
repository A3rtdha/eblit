"""Bridge._watchdog_step: обрыв → уведомка + reload, но без ложных срабатываний."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.bridge import WD_MAX_ATTEMPTS, Bridge

OK = {"ok": True, "power": True, "legs": {"box": {"state": "ok"}, "warp": {"state": "ok"}, "node": {"state": "ok"}}}
BAD = {"ok": False, "power": True, "legs": {"box": {"state": "ok"}, "warp": {"state": "ok"}, "node": {"state": "bad", "why": "timeout"}}}


class WatchdogStep(unittest.TestCase):
    def setUp(self):
        self.b = Bridge()
        self.b._notify_os = MagicMock()
        self.b._job = MagicMock(return_value={"ok": True, "pending": True})

    def _run(self, *, running=True, tick=BAD):
        with (
            patch("app.bridge.singbox.running", return_value=running),
            patch("app.bridge.probe.light_tick", return_value=tick),
        ):
            self.b._watchdog_step()

    def test_healthy_never_reloads(self):
        self._run(tick=OK)
        self.b._job.assert_not_called()
        self.assertEqual(self.b._wd_fail, 0)

    def test_one_blip_is_debounced(self):
        self._run(tick=BAD)
        self.b._job.assert_not_called()
        self.assertEqual(self.b._wd_fail, 1)

    def test_two_fails_reload_and_notify(self):
        self._run(tick=BAD)
        self._run(tick=BAD)
        self.b._job.assert_called_once_with(self.b._reload)
        msg = self.b._notify_os.call_args[0][1]
        self.assertIn("сервер", msg)
        self.assertGreater(self.b._wd_cooldown_until, time.monotonic())
        self.assertEqual(self.b._wd_attempts, 1)

    def test_cooldown_blocks_next(self):
        self.b._wd_cooldown_until = time.monotonic() + 1000
        self._run(tick=BAD)
        self._run(tick=BAD)
        self.b._job.assert_not_called()

    def test_power_off_resets(self):
        self.b._wd_fail = 1
        self.b._wd_attempts = 2
        self._run(running=False)
        self.b._job.assert_not_called()
        self.assertEqual(self.b._wd_fail, 0)
        self.assertEqual(self.b._wd_attempts, 0)

    def test_crash_reloads_without_light_tick(self):
        """Процесс умер, а юзер питание не выключал — это обрыв, не «выключено»."""
        self.b._want_on = True
        with (
            patch("app.bridge.singbox.running", return_value=False),
            patch("app.bridge.probe.light_tick") as tick,
        ):
            self.b._watchdog_step()
            self.b._watchdog_step()
        tick.assert_not_called()
        self.b._job.assert_called_once_with(self.b._reload)
        msg = self.b._notify_os.call_args[0][1]
        self.assertIn("sing-box", msg)

    def test_toggle_off_does_nothing(self):
        self.b._autoreconnect = False
        self._run(tick=BAD)
        self._run(tick=BAD)
        self.b._job.assert_not_called()

    def test_busy_skips(self):
        self.b._busy = True
        self._run(tick=BAD)
        self._run(tick=BAD)
        self.b._job.assert_not_called()

    def test_gives_up_after_max_attempts(self):
        self.b._wd_attempts = WD_MAX_ATTEMPTS
        self._run(tick=BAD)
        self._run(tick=BAD)
        self.b._job.assert_not_called()
        msg = self.b._notify_os.call_args[0][1]
        self.assertIn("вручную", msg)

    def test_recovery_notifies_and_resets(self):
        self.b._wd_attempts = 2
        self._run(tick=OK)
        msg = self.b._notify_os.call_args[0][1]
        self.assertIn("восстановлено", msg)
        self.assertEqual(self.b._wd_attempts, 0)


class ManualPower(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="eblit-watchdog-")
        self.addCleanup(temporary.cleanup)
        root = patch("app.paths.root", return_value=Path(temporary.name))
        root.start()
        self.addCleanup(root.stop)
        self.bridge = Bridge()
        self.bridge._power = True
        self.bridge._want_on = True
        self.bridge._wd_fail = 1
        self.bridge._notify_os = MagicMock()

    def wait_for_job(self):
        deadline = time.monotonic() + 2
        while self.bridge._busy and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.bridge._busy)

    def test_stop_discards_watchdog_failure_from_before_disconnect(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_probe(*, power_on):
            entered.set()
            release.wait(3)
            return BAD

        with (
            patch("app.bridge.singbox.running", return_value=True),
            patch("app.bridge.probe.light_tick", side_effect=slow_probe),
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.stop", return_value={"ok": True, "power": False}),
            patch("app.bridge.lifecycle.reload") as reload,
            patch("app.bridge.lifecycle.start") as start,
        ):
            worker = threading.Thread(target=self.bridge._watchdog_step)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(self.bridge.stop()["pending"])
                self.wait_for_job()
                self.assertFalse(self.bridge._want_on)
            finally:
                release.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        reload.assert_not_called()
        start.assert_not_called()
        self.bridge._notify_os.assert_not_called()
        self.assertEqual(self.bridge._wd_fail, 0)
        self.assertFalse(any(item.get("kind") == "reconnect" for item in self.bridge._outbox))

    def test_stop_discards_process_query_started_before_disconnect(self):
        def stale_process_query():
            self.bridge.stop()
            self.wait_for_job()
            return True

        with (
            patch("app.bridge.singbox.running", side_effect=stale_process_query),
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.stop", return_value={"ok": True, "power": False}),
            patch("app.bridge.probe.light_tick") as probe,
        ):
            self.bridge._watchdog_step()
        self.assertFalse(self.bridge._want_on)
        probe.assert_not_called()

    def test_sync_does_not_restore_intent_from_stale_process_query(self):
        self.bridge._power = False

        def stale_process_query():
            self.bridge.stop()
            self.wait_for_job()
            return True

        with (
            patch("app.bridge.singbox.running", side_effect=stale_process_query),
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.stop", return_value={"ok": True, "power": False}),
            patch.object(self.bridge, "_tick_async") as tick,
        ):
            result = self.bridge.sync_power()
        self.assertNotIn("power", result)
        self.assertFalse(self.bridge._want_on)
        self.assertFalse(self.bridge._power)
        tick.assert_not_called()

    def test_surviving_process_does_not_override_manual_off(self):
        self.bridge._want_on = False
        with (
            patch("app.bridge.singbox.running", return_value=True),
            patch("app.bridge.probe.light_tick") as probe,
            patch.object(self.bridge, "_job") as job,
        ):
            self.bridge._watchdog_step()
            self.bridge._watchdog_step()
        probe.assert_not_called()
        job.assert_not_called()
        self.assertFalse(self.bridge._want_on)

    def test_disabling_reconnect_discards_in_flight_failure(self):
        def probe(*, power_on):
            self.bridge.set_autoreconnect(False)
            return BAD

        with (
            patch("app.bridge.singbox.running", return_value=True),
            patch("app.bridge.probe.light_tick", side_effect=probe),
            patch.object(self.bridge, "_job") as job,
        ):
            self.bridge._watchdog_step()
        job.assert_not_called()
        self.bridge._notify_os.assert_not_called()

    def test_failed_manual_start_does_not_enable_retries(self):
        with (
            patch.object(self.bridge, "_start", return_value={"ok": False, "power": False}),
            patch("app.bridge.singbox.running", return_value=False),
        ):
            self.bridge.start()
            self.wait_for_job()
            self.bridge._watchdog_step()
            self.bridge._watchdog_step()
        self.assertFalse(self.bridge._want_on)
        self.bridge._notify_os.assert_not_called()


if __name__ == "__main__":
    unittest.main()
