from __future__ import annotations

import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from app.bridge import Bridge
from app.instance import application_instance
from app.stack import power_pref

ON = {"ok": True, "power": True}
OFF = {"ok": True, "power": False}


class Transitions(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="eblit-transitions-")
        self.addCleanup(temporary.cleanup)
        root = patch("app.paths.root", return_value=Path(temporary.name))
        root.start()
        self.addCleanup(root.stop)
        self.bridge = Bridge()

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(condition())

    def test_stop_waiting_for_start_is_coalesced_and_final(self):
        entered = threading.Event()
        release = threading.Event()

        def starting():
            entered.set()
            release.wait(3)
            self.bridge._remember_started()
            return dict(ON)

        with (
            patch.object(self.bridge, "_start", side_effect=starting),
            patch.object(self.bridge, "_stop", return_value=dict(OFF)) as stop,
        ):
            self.bridge.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(self.bridge.stop()["pending"])
                self.assertTrue(self.bridge.stop()["pending"])
                self.assertFalse(power_pref.is_on())
                self.assertFalse(self.bridge.start()["ok"])
            finally:
                release.set()
            self.wait_until(lambda: not self.bridge._busy)
        stop.assert_called_once()
        self.assertFalse(self.bridge._want_on)
        self.assertFalse(self.bridge._power)
        self.assertFalse(power_pref.is_on())
        self.assertEqual([item["power"] for item in self.bridge._outbox], [False])

    def test_stop_before_worker_starts_skips_start_completely(self):
        with (
            patch.object(self.bridge, "_start", return_value=dict(ON)) as start,
            patch.object(self.bridge, "_stop", return_value=dict(OFF)) as stop,
        ):
            with self.bridge._operation_lock:
                self.bridge.start()
                self.bridge.stop()
            self.wait_until(lambda: not self.bridge._busy)
        start.assert_not_called()
        stop.assert_called_once()
        self.assertFalse(self.bridge._power)

    def test_stop_still_runs_after_active_operation_raises(self):
        entered = threading.Event()
        release = threading.Event()

        def checking():
            entered.set()
            release.wait(3)
            raise RuntimeError("diagnostic failed")

        with (
            patch("app.bridge.singbox.running", return_value=True),
            patch.object(self.bridge, "_stop", return_value=dict(OFF)) as stop,
        ):
            self.bridge._job(checking)
            self.assertTrue(entered.wait(1))
            self.bridge.stop()
            release.set()
            self.wait_until(lambda: not self.bridge._busy)
        stop.assert_called_once()
        self.assertEqual(self.bridge.pull()["power"], False)

    def test_quit_during_start_does_not_persist_or_publish_on(self):
        entered = threading.Event()
        release = threading.Event()
        destroyed = threading.Event()
        window = Mock()
        window.destroy.side_effect = destroyed.set
        self.bridge._window = window

        def starting():
            entered.set()
            release.wait(3)
            self.bridge._remember_started()
            return dict(ON)

        with (
            patch.object(self.bridge, "_start", side_effect=starting),
            patch.object(self.bridge, "_stop", return_value=dict(OFF)) as stop,
            patch("app.bridge.singbox.running", return_value=True),
        ):
            self.bridge.start()
            self.assertTrue(entered.wait(1))
            self.bridge.quit()
            self.assertFalse(power_pref.is_on())
            release.set()
            self.assertTrue(destroyed.wait(3))
            self.assertTrue(self.bridge.shutdown()["ok"])
        stop.assert_called_once()
        self.assertFalse(power_pref.is_on())
        self.assertFalse(self.bridge._want_on)
        self.assertFalse(any(item.get("power") for item in self.bridge._outbox))

    def test_simultaneous_quit_requests_destroy_window_once(self):
        destroyed = threading.Event()
        self.bridge._window = Mock()
        self.bridge._window.destroy.side_effect = destroyed.set
        with (
            patch("app.bridge.singbox.running", return_value=False),
            patch("app.bridge.warp.owned", return_value=False),
        ):
            callers = [threading.Thread(target=self.bridge.quit) for _ in range(6)]
            for caller in callers:
                caller.start()
            for caller in callers:
                caller.join(2)
            self.assertTrue(destroyed.wait(2))
        self.bridge._window.destroy.assert_called_once()
        self.assertTrue(self.bridge._shutdown_complete)

    def test_quit_during_successful_stop_does_not_request_elevation_twice(self):
        self.bridge._power = True
        entered = threading.Event()
        release = threading.Event()
        destroyed = threading.Event()
        self.bridge._window = Mock()
        self.bridge._window.destroy.side_effect = destroyed.set

        def stopping():
            entered.set()
            release.wait(3)
            return dict(OFF)

        with (
            patch.object(self.bridge, "_stop", side_effect=stopping) as stop,
            patch("app.bridge.singbox.running", return_value=False),
            patch("app.bridge.warp.owned", return_value=False),
        ):
            self.bridge.stop()
            self.assertTrue(entered.wait(1))
            self.bridge.quit()
            release.set()
            self.assertTrue(destroyed.wait(3))
        stop.assert_called_once()
        self.assertFalse(self.bridge._power)
        self.assertFalse(self.bridge._want_on)

    def test_tick_result_from_before_stop_is_discarded(self):
        self.bridge._power = True
        entered = threading.Event()
        release = threading.Event()

        def checking(*, power_on):
            entered.set()
            release.wait(3)
            return {"ok": False, "legs": {"warp": {"state": "bad"}}}

        with (
            patch("app.bridge.probe.light_tick", side_effect=checking),
            patch.object(self.bridge, "_stop", return_value=dict(OFF)),
        ):
            self.bridge.tick()
            self.assertTrue(entered.wait(1))
            self.bridge.stop()
            self.wait_until(lambda: not self.bridge._busy)
            release.set()
            self.wait_until(lambda: not self.bridge._tick_busy)
        self.assertEqual(len(self.bridge._outbox), 1)
        self.assertFalse(self.bridge.pull()["power"])

    def test_initial_status_cannot_overwrite_completed_stop(self):
        def stale_query():
            self.bridge.stop()
            self.wait_until(lambda: not self.bridge._busy)
            return True

        with (
            patch("app.bridge.singbox.running", side_effect=stale_query),
            patch.object(self.bridge, "_stop", return_value=dict(OFF)),
            patch("app.bridge.power_pref.is_on", return_value=True),
        ):
            result = self.bridge.status()
        self.assertNotIn("power", result)
        self.assertNotIn("want_on", result)
        self.assertFalse(self.bridge._power)

    def test_old_startup_restore_cannot_undo_manual_stop(self):
        revision = self.bridge._power_revision
        with (
            patch.object(self.bridge, "_stop", return_value=dict(OFF)),
            patch.object(self.bridge, "_start", return_value=dict(ON)) as start,
            patch("app.bridge.power_pref.is_on", return_value=True),
        ):
            self.bridge.stop()
            self.wait_until(lambda: not self.bridge._busy)
            self.bridge.restore_power(revision)
        start.assert_not_called()
        self.assertFalse(self.bridge._want_on)

    def test_changing_reconnect_preference_does_not_lose_start_result(self):
        entered = threading.Event()
        release = threading.Event()

        def starting():
            entered.set()
            release.wait(3)
            return dict(ON)

        with patch.object(self.bridge, "_start", side_effect=starting):
            self.bridge.start()
            self.assertTrue(entered.wait(1))
            self.bridge.set_autoreconnect(False)
            release.set()
            self.wait_until(lambda: not self.bridge._busy)
        self.assertTrue(self.bridge.pull()["power"])
        self.assertTrue(self.bridge._power)

    def test_delayed_reload_does_not_restart_after_manual_off(self):
        self.bridge._want_on = False
        with patch("app.bridge.lifecycle.reload") as reload:
            self.assertFalse(self.bridge.reload()["ok"])
            self.assertFalse(self.bridge._reload()["ok"])
        reload.assert_not_called()

    def test_failed_stop_does_not_reenable_reconnect_or_saved_power(self):
        self.bridge._power = True
        self.bridge._want_on = True
        power_pref.set_on(True)
        with (
            patch("app.bridge.admin.is_admin", return_value=True),
            patch("app.bridge.lifecycle.stop", return_value={"ok": False, "power": True}),
        ):
            self.bridge.stop()
            self.wait_until(lambda: not self.bridge._busy)
        self.assertTrue(self.bridge._power)
        self.assertFalse(self.bridge._want_on)
        self.assertFalse(power_pref.is_on())

    def test_pull_drops_obsolete_state_but_keeps_other_events(self):
        self.bridge._push({"power": True, "revision": 0})
        self.bridge._push({"kind": "sub", "ok": True})
        self.bridge._push({"power": False, "revision": 1})
        self.bridge._power_revision = 1
        self.assertEqual(self.bridge.pull()["kind"], "sub")
        self.assertFalse(self.bridge.pull()["power"])
        self.assertTrue(self.bridge.pull()["pending"])

    def test_failed_reconnect_keeps_intent_for_next_bounded_attempt(self):
        self.bridge._want_on = True
        with patch.object(self.bridge, "_start", return_value={"ok": False, "power": False}):
            self.bridge._job(self.bridge._start)
            self.wait_until(lambda: not self.bridge._busy)
        self.assertTrue(self.bridge._want_on)
        self.assertFalse(self.bridge._power)

    def test_failed_manual_start_does_not_enable_watchdog(self):
        with patch.object(self.bridge, "_start", return_value={"ok": False, "power": False}):
            self.bridge.start()
            self.wait_until(lambda: not self.bridge._busy)
        self.assertFalse(self.bridge._want_on)

    def test_failed_shutdown_clears_queued_stop_for_explicit_retry(self):
        self.bridge._power = True
        self.bridge._stop_requested = True
        self.bridge._window = Mock()
        shown = threading.Event()
        self.bridge._window.show.side_effect = shown.set
        with patch.object(self.bridge, "_stop", return_value={"ok": False, "power": True}):
            self.bridge.quit()
            self.assertTrue(shown.wait(2))
        self.assertFalse(self.bridge._closing.is_set())
        self.assertFalse(self.bridge._stop_requested)
        self.assertFalse(self.bridge._want_on)
        with patch.object(self.bridge, "_start", return_value=dict(ON)) as start:
            self.bridge.start()
            self.wait_until(lambda: not self.bridge._busy)
        start.assert_called_once()


class SingleWindow(unittest.TestCase):
    def test_only_one_window_can_own_the_same_instance(self):
        name = "Local\\Eblit.test." + uuid.uuid4().hex
        with application_instance(name) as primary:
            self.assertTrue(primary)
            with application_instance(name) as secondary:
                self.assertFalse(secondary)
        with application_instance(name) as reopened:
            self.assertTrue(reopened)


if __name__ == "__main__":
    unittest.main()
