from __future__ import annotations

import inspect
import time
import unittest
from unittest.mock import patch

from app.bridge import Bridge
from app.stack import probe


def walkable(obj) -> list[str]:
    """Публичные атрибуты, в которые pywebview полезет рекурсией (webview/util.py get_functions)."""
    out = []
    for name in dir(obj):
        if name.startswith("_"):
            continue
        attr = getattr(obj, name)
        if inspect.ismethod(attr) or inspect.isfunction(attr):
            continue
        if inspect.isclass(attr) or (
            isinstance(attr, object) and not callable(attr) and hasattr(attr, "__module__")
        ):
            out.append(name)
    return out


class Recursion(unittest.TestCase):
    def test_window_is_not_exposed_to_js_api_walker(self):
        class Native:
            def __init__(self) -> None:
                self.parent = self

        b = Bridge()
        b.set_window(Native())
        self.assertEqual(walkable(b), [])

    def test_methods_still_exposed(self):
        names = {n for n in dir(Bridge()) if not n.startswith("_")}
        self.assertLessEqual({"start", "stop", "reload", "test", "tick", "status", "pull"}, names)


class StatusOff(unittest.TestCase):
    def test_matches_light_tick(self):
        with patch.object(probe, "light_tick", wraps=probe.light_tick) as tick:
            with patch("app.bridge.singbox.running", return_value=False):
                result = Bridge().status()
        tick.assert_called_once_with(power_on=False)
        self.assertFalse(result["power"])
        self.assertEqual(result["legs"]["box"]["state"], "off")
        self.assertEqual(result["legs"]["warp"]["state"], "off")
        self.assertEqual(result["legs"]["node"]["state"], "off")


class StatusOnDoesNotBlock(unittest.TestCase):
    def test_returns_before_curl(self):
        hold = True

        def stuck(*, power_on):
            while hold:
                time.sleep(0.05)
            return {"ok": True, "power": True, "legs": {}}

        with (
            patch("app.bridge.singbox.running", return_value=True),
            patch("app.bridge.probe.light_tick", side_effect=stuck),
        ):
            t0 = time.perf_counter()
            result = Bridge().status()
            elapsed = time.perf_counter() - t0
        hold = False
        self.assertTrue(result["power"])
        self.assertNotIn("legs", result)
        self.assertLess(elapsed, 0.4)


class TickAsync(unittest.TestCase):
    def test_returns_pending_and_pull_omits_power(self):
        b = Bridge()
        b._power = True
        with (
            patch("app.bridge.singbox.running", return_value=True),
            patch(
                "app.bridge.probe.light_tick",
                return_value={"ok": True, "power": True, "legs": {"box": {"state": "ok", "why": "x"}}},
            ),
        ):
            first = b.tick()
            self.assertTrue(first.get("pending"))
            got = None
            deadline = time.time() + 2
            while time.time() < deadline:
                got = b.pull()
                if not got.get("pending"):
                    break
                time.sleep(0.02)
        self.assertIsNotNone(got)
        self.assertIn("legs", got)
        self.assertNotIn("power", got)

    def test_pull_empty_is_pending(self):
        self.assertEqual(Bridge().pull(), {"ok": True, "pending": True})

    def test_pull_waits_while_tick_busy(self):
        b = Bridge()
        b._tick_busy = True
        self.assertTrue(b.pull().get("wait"))


class Nodes(unittest.TestCase):
    def test_passes_roster_through(self):
        payload = {"ok": True, "nodes": [{"tag": "Finland"}], "selected": "Finland", "pick": None}
        with patch("app.bridge.roster.stack_nodes", return_value=payload):
            self.assertEqual(Bridge().nodes(), payload)

    def test_read_error_is_honest_not_raise(self):
        with patch("app.bridge.roster.stack_nodes", side_effect=OSError("занят")):
            result = Bridge().nodes()
        self.assertFalse(result["ok"])
        self.assertEqual(result["nodes"], [])
        self.assertIn("занят", result["why"])


class Lan(unittest.TestCase):
    STATE = {"on": True, "port": 2080, "address": "192.168.0.13"}

    def test_off_power_writes_without_restart(self):
        b = Bridge()
        with (
            patch("app.bridge.lan.set_enabled", return_value=dict(self.STATE)) as set_enabled,
            patch("app.bridge.singbox.running", return_value=False),
            patch.object(b, "_job") as job,
        ):
            result = b.set_lan(True)
        set_enabled.assert_called_once_with(True)
        job.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertFalse(result["restart"])
        self.assertEqual(result["address"], "192.168.0.13")

    def test_on_power_restarts_like_select_node(self):
        """Живой sing-box слушает старый адрес, пока его не перезапустить —
        тумблер без reload оставлял шлем «без интернета»."""
        b = Bridge()
        with (
            patch("app.bridge.lan.set_enabled", return_value=dict(self.STATE)),
            patch("app.bridge.singbox.running", return_value=True),
            patch.object(b, "_job", return_value={"ok": True, "pending": True}) as job,
        ):
            result = b.set_lan(True)
        job.assert_called_once_with(b._reload)
        self.assertTrue(result["restart"])

    def test_busy_stack_is_honest(self):
        b = Bridge()
        with (
            patch("app.bridge.lan.set_enabled", return_value=dict(self.STATE)),
            patch("app.bridge.singbox.running", return_value=True),
            patch.object(b, "_job", return_value={"ok": False, "pending": False, "why": "уже крутится"}),
        ):
            result = b.set_lan(True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["restart"])

    def test_config_error_does_not_raise(self):
        with patch("app.bridge.lan.set_enabled", side_effect=ValueError("нет инбаунда")):
            result = Bridge().set_lan(True)
        self.assertFalse(result["ok"])
        self.assertIn("инбаунда", result["why"])


ROSTER = {
    "ok": True,
    "nodes": [{"tag": "Sweden"}],
    "selected": "Sweden",
    "pick": {"tag": "Sweden", "manual": True},
    "favorite": None,
    "manual": True,
    "auto": False,
}


class SelectNode(unittest.TestCase):
    def test_power_off_writes_without_reload(self):
        b = Bridge()
        with (
            patch("app.bridge.nodes.select") as select,
            patch("app.bridge.roster.stack_nodes", return_value=dict(ROSTER)),
            patch("app.bridge.singbox.running", return_value=False),
            patch.object(b, "_job") as job,
        ):
            result = b.select_node("Sweden")
        select.assert_called_once_with("Sweden")
        job.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertFalse(result["restart"])
        self.assertEqual(result["selected"], "Sweden")

    def test_running_reloads_after_write(self):
        b = Bridge()
        order = []

        def select(_tag):
            order.append("select")

        def job(fn):
            order.append("job")
            return {"ok": True, "pending": True}

        with (
            patch("app.bridge.nodes.select", side_effect=select),
            patch("app.bridge.roster.stack_nodes", return_value=dict(ROSTER)),
            patch("app.bridge.singbox.running", return_value=True),
            patch.object(b, "_job", side_effect=job) as job_mock,
        ):
            result = b.select_node("Sweden")
        self.assertEqual(order, ["select", "job"])
        job_mock.assert_called_once_with(b._reload)
        self.assertTrue(result["restart"])

    def test_busy_still_writes_restart_false(self):
        b = Bridge()
        with (
            patch("app.bridge.nodes.select") as select,
            patch("app.bridge.roster.stack_nodes", return_value=dict(ROSTER)),
            patch("app.bridge.singbox.running", return_value=True),
            patch.object(b, "_job", return_value={"ok": False, "pending": False, "why": "уже крутится"}),
        ):
            result = b.select_node("Sweden")
        select.assert_called_once_with("Sweden")
        self.assertTrue(result["ok"])
        self.assertFalse(result["restart"])

    def test_auto_clears_manual_not_select(self):
        b = Bridge()
        auto_roster = {**ROSTER, "manual": False, "auto": True, "pick": {"tag": "Sweden"}}
        with (
            patch("app.bridge.nodes.clear_manual") as clear,
            patch("app.bridge.nodes.select") as select,
            patch("app.bridge.roster.stack_nodes", return_value=auto_roster),
            patch("app.bridge.singbox.running", return_value=False),
            patch.object(b, "_job") as job,
        ):
            result = b.select_node("auto")
        clear.assert_called_once()
        select.assert_not_called()
        job.assert_not_called()
        self.assertTrue(result["auto"])


class Favorite(unittest.TestCase):
    def test_never_starts_job(self):
        b = Bridge()
        with (
            patch("app.bridge.nodes.set_favorite") as fav,
            patch("app.bridge.roster.stack_nodes", return_value=dict(ROSTER)),
            patch.object(b, "_job") as job,
        ):
            result = b.set_favorite("Sweden")
        fav.assert_called_once_with("Sweden")
        job.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertFalse(b._busy)


class UpdateBg(unittest.TestCase):
    def _wait_push(self, b: Bridge, timeout: float = 2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not b._update_busy:
                break
            time.sleep(0.02)

    def test_does_not_set_busy(self):
        b = Bridge()
        payload = {
            "ok": True,
            "newer": True,
            "latest": "1.0.1",
            "asset": "https://example/EblitSetup.exe",
        }
        with patch("app.bridge.updates.check", return_value=payload):
            first = b.check_update_bg()
            self.assertFalse(b._busy)
            self.assertTrue(first.get("pending"))
            self._wait_push(b)
        self.assertFalse(b._busy)
        got = b.pull()
        self.assertTrue(got.get("newer"))
        self.assertEqual(got.get("kind"), "update")

    def test_404_is_silent_not_newer(self):
        b = Bridge()
        b._notify_os = lambda *_a, **_k: None
        with patch(
            "app.bridge.updates.check",
            return_value={"ok": True, "newer": False, "latest": "1.0.0", "asset": "", "why": "релизов ещё нет"},
        ):
            b.check_update_bg()
            self._wait_push(b)
        self.assertFalse(b._busy)
        got = b.pull()
        self.assertTrue(got.get("pending"))
        self.assertNotEqual(got.get("kind"), "update")
        self.assertFalse(got.get("newer"))


class PingNodes(unittest.TestCase):
    def _wait(self, b: Bridge, timeout: float = 2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not b._ping_busy:
                break
            time.sleep(0.02)

    def test_second_call_ignored_while_busy(self):
        b = Bridge()
        hold = True

        def stuck():
            while hold:
                time.sleep(0.02)
            return {"ok": True, "nodes": []}

        with patch("app.bridge.health.scan_all", side_effect=stuck):
            first = b.ping_nodes()
            second = b.ping_nodes()
        hold = False
        self.assertTrue(first.get("pending"))
        self.assertTrue(second.get("ignored") or second.get("pending"))
        self.assertFalse(b._busy)
        self._wait(b)

    def test_unexpected_error_still_pushes(self):
        b = Bridge()
        with patch("app.bridge.health.scan_all", side_effect=RuntimeError("boom")):
            b.ping_nodes()
            self._wait(b)
        self.assertFalse(b._busy)
        self.assertFalse(b._ping_busy)
        got = b.pull()
        self.assertEqual(got.get("kind"), "ping")
        self.assertFalse(got.get("ok"))
        self.assertIn("boom", got.get("why", ""))


if __name__ == "__main__":
    unittest.main()
