"""Bridge._watchdog_step: обрыв → уведомка + reload, но без ложных срабатываний."""

from __future__ import annotations

import time
import unittest
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


if __name__ == "__main__":
    unittest.main()
