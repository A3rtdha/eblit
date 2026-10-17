from __future__ import annotations

import hashlib
import json
import multiprocessing
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil

from app import paths
from app.bridge import Bridge
from app.stack import cli, configuration, health, lifecycle, nodes, probe, singbox, updates, warp
from app.storage import atomic_write


def increment_config(directory: str) -> None:
    with patch("app.paths.root", return_value=Path(directory)):
        for _ in range(8):
            with configuration.locked():
                cfg = nodes.read_config()
                time.sleep(0.001)
                cfg["count"] += 1
                nodes.write_config(cfg)


class Files(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eblit-regression-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        root_patch = patch("app.paths.root", return_value=self.directory)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.config = self.directory / "config.json"

    def test_failed_replace_preserves_original_config(self):
        self.config.write_text('{"outbounds": []}', encoding="utf-8")
        with patch.object(Path, "replace", side_effect=PermissionError("locked")), patch("app.storage.time.sleep"):
            with self.assertRaises(PermissionError):
                atomic_write(self.config, "replacement")
        self.assertEqual(json.loads(self.config.read_text())["outbounds"], [])
        self.assertFalse(list(self.directory.glob("*.tmp")))

    def test_empty_and_wrong_shape_are_actionable_errors(self):
        for value in ("", "[]", "null", '{"outbounds": [null]}', '{"outbounds": [], "route": []}'):
            with self.subTest(value=value):
                self.config.write_text(value, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "config.json"):
                    nodes.read_config()
                self.assertEqual(self.config.read_text(encoding="utf-8"), value)

    def test_bom_config_is_accepted(self):
        self.config.write_text('{"outbounds": []}', encoding="utf-8-sig")
        self.assertEqual(nodes.read_config(), {"outbounds": []})

    def test_selector_migration_preserves_routes_and_credentials(self):
        cfg = {
            "outbounds": [
                {"type": "selector", "tag": configuration.LEGACY_SELECTOR, "outbounds": ["Node"]},
                {"type": "vless", "tag": "Node", "uuid": "keep-this", "server": "node.test"},
            ],
            "route": {"rules": [{"outbound": configuration.LEGACY_SELECTOR}]},
            "dns": {"servers": [{"detour": configuration.LEGACY_SELECTOR}]},
        }
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        actual = nodes.read_config()
        self.assertEqual(actual["outbounds"][0]["tag"], "proxy-select")
        self.assertEqual(actual["outbounds"][1], cfg["outbounds"][1])
        self.assertEqual(actual["route"]["rules"][0]["outbound"], "proxy-select")
        self.assertEqual(actual["dns"]["servers"][0]["detour"], "proxy-select")

    def test_deleted_migrated_favorite_does_not_return(self):
        old = self.directory / "lagom-favorite.json"
        old.write_text('{"tag":"Node"}', encoding="utf-8")
        paths.data_root()
        migrated = self.directory / "eblit-favorite.json"
        self.assertTrue(migrated.exists())
        migrated.unlink()
        paths.data_root()
        self.assertFalse(migrated.exists())

    def test_config_changes_from_multiple_processes_are_not_lost(self):
        self.config.write_text('{"outbounds": [], "count": 0}', encoding="utf-8")
        context = multiprocessing.get_context("spawn")
        workers = [context.Process(target=increment_config, args=(str(self.directory),)) for _ in range(3)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
            if worker.is_alive():
                worker.terminate()
                worker.join()
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(nodes.read_config()["count"], 24)

    def test_ip_server_is_not_replaced_with_tls_camouflage_host(self):
        cfg = {"outbounds": [{"type": "vless", "tag": "Node", "server": "203.0.113.5", "tls": {"server_name": "example.org"}}]}
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        self.assertNotIn("example.org", nodes.hosts().values())
        self.assertEqual(nodes._host_for({"host": "203.0.113.5", "sni": "example.org"}, cfg["outbounds"][0]), "203.0.113.5")

    def test_health_does_not_resolve_servers_after_first_success(self):
        cfg = {"outbounds": [
            {"type": "selector", "tag": nodes.SELECTOR, "outbounds": ["A"]},
            {"type": "vless", "tag": "A", "server": "a.test"},
            {"type": "vless", "tag": "B", "server": "b.test"},
        ]}
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        with (
            patch.object(health, "resolve_one", return_value="203.0.113.1") as resolve,
            patch.object(health, "probe", return_value=(True, 10, "200")),
        ):
            self.assertEqual(health.main(), 0)
        resolve.assert_called_once_with("a.test")

    def test_health_preserves_edits_made_during_network_probe(self):
        cfg = {"outbounds": [
            {"type": "selector", "tag": nodes.SELECTOR, "outbounds": ["A"]},
            {"type": "vless", "tag": "A", "server": "203.0.113.1"},
        ]}
        self.config.write_text(json.dumps(cfg), encoding="utf-8")

        def answer(*args):
            current = nodes.read_config()
            current["route"] = {"rules": [{"domain_suffix": ["new.test"], "outbound": "direct"}]}
            nodes.write_config(current)
            return True, 10, "200"

        with patch.object(health, "probe", side_effect=answer):
            self.assertEqual(health.main(), 0)
        self.assertEqual(nodes.read_config()["route"]["rules"][0]["domain_suffix"], ["new.test"])

    def test_node_cannot_reuse_a_routing_tag(self):
        self.config.write_text('{"outbounds": [{"type":"direct", "tag":"direct"}]}', encoding="utf-8")
        parsed = {"tag": "direct", "host": "node.test", "uuid": "11111111-2222-3333-4444-555555555555"}
        with self.assertRaises(ValueError):
            nodes.add(parsed)
        self.assertEqual(len(nodes.read_config()["outbounds"]), 1)

    def test_probe_spawn_failure_removes_file_with_credentials(self):
        with patch.object(health.subprocess, "Popen", side_effect=OSError("missing")):
            with self.assertRaises(OSError):
                health.probe("A", {"tag": "A", "uuid": "secret"}, "203.0.113.1")
        self.assertFalse((self.directory / "_probe.json").exists())


class Shutdown(unittest.TestCase):
    def test_exit_after_cancelled_start_does_not_ask_for_uac_again(self):
        bridge = Bridge()
        with (
            patch("app.bridge.admin.is_admin", return_value=False),
            patch("app.bridge.admin.elevated", return_value=(False, 1)) as elevate,
            patch("app.bridge.singbox.running", return_value=False),
            patch("app.bridge.warp.owned", return_value=False),
        ):
            bridge._start()
            self.assertTrue(bridge.shutdown()["ok"])
        elevate.assert_called_once_with(["start"])

    def test_denied_uac_does_not_become_successful_off_status(self):
        bridge = Bridge()
        with (
            patch("app.bridge.admin.is_admin", return_value=False),
            patch("app.bridge.admin.elevated", return_value=(False, 1)),
            patch("app.bridge.singbox.running", return_value=False),
        ):
            result = bridge._start()
        self.assertFalse(result["ok"])
        self.assertFalse(result["power"])

    def test_warp_outage_reconnects_warp_instead_of_only_restarting_tun(self):
        bridge = Bridge()
        failed = {"ok": False, "legs": {"warp": {"state": "bad"}}}
        with (
            patch("app.bridge.singbox.running", return_value=True),
            patch("app.bridge.probe.light_tick", return_value=failed),
            patch.object(bridge, "_job") as job,
        ):
            bridge._watchdog_step()
            bridge._watchdog_step()
        job.assert_called_once_with(bridge._start)

    def test_close_waits_for_in_progress_start_then_stops(self):
        bridge = Bridge()
        entered = threading.Event()
        release = threading.Event()
        stopped = threading.Event()

        def start():
            entered.set()
            release.wait(3)
            return {"ok": True, "power": True}

        with (
            patch.object(bridge, "_stop", side_effect=lambda: stopped.set() or {"ok": True, "power": False}),
            patch("app.bridge.singbox.running", return_value=True),
        ):
            bridge._job(start)
            self.assertTrue(entered.wait(1))
            shutdown = threading.Thread(target=bridge.shutdown)
            shutdown.start()
            self.assertFalse(stopped.wait(0.05))
            release.set()
            shutdown.join(3)
        self.assertFalse(shutdown.is_alive())
        self.assertTrue(stopped.is_set())
        self.assertTrue(bridge._shutdown_complete)

    def test_no_new_jobs_or_watchdog_after_exit_requested(self):
        bridge = Bridge()
        bridge._closing.set()
        bridge._want_on = True
        operation = Mock()
        with patch("app.bridge.singbox.running") as running:
            result = bridge._job(operation)
            bridge._watchdog_step()
        self.assertFalse(result["ok"])
        operation.assert_not_called()
        running.assert_not_called()

    def test_failed_stop_keeps_window_open(self):
        bridge = Bridge()
        bridge._window = Mock()
        with patch.object(bridge, "shutdown", return_value={"ok": False, "power": True, "why": "denied"}):
            bridge.quit()
            deadline = time.monotonic() + 2
            while bridge._closing.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
        bridge._window.destroy.assert_not_called()
        self.assertFalse(bridge._shutdown_complete)
        self.assertFalse(bridge._closing.is_set())

    def test_warp_disconnect_failure_is_not_reported_as_success(self):
        with (
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.singbox, "wait_gone", return_value=True),
            patch.object(warp, "disconnect", return_value=False),
        ):
            result = lifecycle.stop()
        self.assertFalse(result["ok"])
        self.assertIn("WARP", result["why"])

    def test_unexpected_start_error_rolls_back(self):
        with (
            patch.object(lifecycle.singbox, "kill"),
            patch.object(lifecycle.singbox, "wait_gone", return_value=True),
            patch.object(lifecycle.health, "main", side_effect=RuntimeError("error")),
            patch.object(lifecycle.subscribe, "refresh", return_value={"ok": True}),
            patch.object(lifecycle, "stop") as stop,
        ):
            with self.assertRaises(RuntimeError):
                lifecycle.start()
        stop.assert_called_once()

    def test_cli_handles_invalid_config_without_traceback(self):
        with (
            patch.object(cli.admin, "ensure_admin", return_value=None),
            patch.object(lifecycle, "start", side_effect=ValueError("config.json повреждён")),
            patch.object(cli, "write") as log,
        ):
            self.assertEqual(cli.run("start"), 1)
        self.assertIn("config.json", log.call_args.args[0])

    def test_off_diagnostics_do_not_make_network_requests(self):
        with patch.object(probe, "_curl") as curl, patch.object(health, "last_result_line", return_value=""):
            result = probe.full_test(power_on=False)
        self.assertFalse(result["power"])
        curl.assert_not_called()


class OwnedProcesses(unittest.TestCase):
    def test_stop_ignores_other_vpn_and_probe_processes(self):
        executable = Path("C:/Eblit/sing-box.exe")
        config = Path("C:/Eblit/config.json")
        main = Mock(info={"name": "sing-box.exe"})
        main.exe.return_value = str(executable)
        main.cmdline.return_value = [str(executable), "run", "-c", str(config)]
        other = Mock(info={"name": "sing-box.exe"})
        other.exe.return_value = "C:/OtherVPN/sing-box.exe"
        checking = Mock(info={"name": "sing-box.exe"})
        checking.exe.return_value = str(executable)
        checking.cmdline.return_value = [str(executable), "run", "-c", "C:/Eblit/_probe.json"]
        with (
            patch.object(singbox, "singbox", return_value=executable),
            patch.object(singbox, "data_root", return_value=config.parent),
            patch.object(psutil, "process_iter", return_value=[main, other, checking]),
        ):
            singbox.kill()
        main.terminate.assert_called_once()
        other.terminate.assert_not_called()
        checking.terminate.assert_not_called()


class UpdateSecurity(unittest.TestCase):
    def test_rejects_installer_from_another_repository_or_host(self):
        for url in (
            "https://evil.test/EblitSetup.exe",
            "https://github.com/other/repo/releases/download/v1/EblitSetup.exe",
            "https://github.com@evil.test/A3rtdha/eblit/releases/download/v1/EblitSetup.exe",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                updates.download(url)

    def test_checksum_mismatch_does_not_write_executable(self):
        data = b"MZ" + b"x" * updates.MIN_SETUP
        with patch.object(updates, "_request", return_value=data), patch.object(updates.tempfile, "mkdtemp") as make_dir:
            with self.assertRaisesRegex(ValueError, "сумма"):
                updates.download(f"https://github.com/{updates.REPO}/releases/download/v1/EblitSetup.exe", expected_digest="sha256:" + "0" * 64)
        make_dir.assert_not_called()

    def test_verified_updates_use_distinct_directories(self):
        data = b"MZ" + b"x" * updates.MIN_SETUP
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as temp, patch.object(updates, "_request", return_value=data):
            real_mkdtemp = tempfile.mkdtemp
            with patch.object(updates.tempfile, "mkdtemp", side_effect=lambda **kwargs: real_mkdtemp(dir=temp, **kwargs)):
                first = updates.download(f"https://github.com/{updates.REPO}/releases/download/v1/EblitSetup.exe", expected_digest=digest)
                second = updates.download(f"https://github.com/{updates.REPO}/releases/download/v1/EblitSetup.exe", expected_digest=digest)
            self.assertNotEqual(first.parent, second.parent)
            self.assertEqual(first.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
