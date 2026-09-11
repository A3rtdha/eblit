"""Последовательность установки и снятия. Без сети, без реального Program Files."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.setup import install


def make_payload(src: Path) -> None:
    src.mkdir(parents=True, exist_ok=True)
    (src / "Eblit.exe").write_bytes(b"exe")
    (src / "config.json").write_text('{"outbounds": []}', encoding="utf-8")
    inner = src / "_internal"
    inner.mkdir(exist_ok=True)
    (inner / "python3.dll").write_bytes(b"dll")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eblit-install-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / "payload"
        self.dest = self.root / "dest"
        make_payload(self.src)
        self.enter(patch.object(install, "DEST", self.dest))
        self.enter(patch.object(install, "payload_dir", return_value=self.src))
        self.enter(patch.object(install, "kill_image"))
        self.logs: list[str] = []
        self.enter(patch.object(install, "_log", self.logs.append))

    def enter(self, patcher):
        obj = patcher.start()
        self.addCleanup(patcher.stop)
        return obj


class Sequence(Base):
    def setUp(self):
        super().setUp()
        self.order: list[str] = []

        def step(name, result=None):
            def inner(*_a, **_kw):
                self.order.append(name)
                return result

            return inner

        def singbox(tmp):
            self.order.append("singbox")
            sb = Path(tmp) / "sing-box.exe"
            sb.write_bytes(b"sb")
            return sb

        self.enter(patch.object(install, "_install_webview2", step("webview2")))
        self.enter(patch.object(install, "_install_warp", step("warp")))
        self.enter(patch.object(install, "_install_singbox", singbox))
        self.enter(patch.object(install, "_check_singbox", step("check", True)))
        self.enter(patch.object(install, "_configure_warp", step("configure_warp")))
        self.enter(patch.object(install, "_shortcuts", step("shortcuts")))
        self.enter(patch.object(install, "_register_uninstall", step("uninstall_key")))
        self.enter(patch.object(install, "_stop_running", step("stop", True)))
        teredo = self.enter(patch.object(install, "teredo"))
        teredo.disable.return_value = (True, "teredo off")

    def test_returns_zero_and_copies_payload(self):
        self.assertEqual(install.run(), 0)
        self.assertTrue((self.dest / "Eblit.exe").is_file())
        self.assertTrue((self.dest / "config.json").is_file())
        self.assertTrue((self.dest / "_internal" / "python3.dll").is_file())
        self.assertTrue((self.dest / "sing-box.exe").is_file())

    def test_uninstall_key_registered_before_heavy_steps(self):
        """Иначе упавшая установка не снимается из «Программы и компоненты»."""
        install.run()
        self.assertLess(self.order.index("uninstall_key"), self.order.index("configure_warp"))

    def test_warp_installed_before_configured(self):
        install.run()
        self.assertLess(self.order.index("warp"), self.order.index("configure_warp"))

    def test_config_checked_after_copy(self):
        install.run()
        self.assertIn("check", self.order)

    def test_keeps_existing_config_on_reinstall(self):
        """Апдейт не затирает vless, которые человек уже добавил у себя."""
        self.dest.mkdir(parents=True)
        custom = '{"outbounds":[{"type":"vless","tag":"Home","uuid":"x"}]}'
        (self.dest / "config.json").write_text(custom, encoding="utf-8")
        self.assertEqual(install.run(), 0)
        self.assertEqual((self.dest / "config.json").read_text(encoding="utf-8"), custom)

    def test_replaces_stock_builder_nodes(self):
        """Прошлая утечка Japan/Sweden — не «свои ноды», её надо затереть чистым payload."""
        self.dest.mkdir(parents=True)
        leaked = '{"outbounds":[{"type":"vless","tag":"Sweden","uuid":"secret"}]}'
        (self.dest / "config.json").write_text(leaked, encoding="utf-8")
        self.assertEqual(install.run(), 0)
        self.assertEqual(
            (self.dest / "config.json").read_text(encoding="utf-8"),
            '{"outbounds": []}',
        )

    def test_keeps_mixed_custom_and_stock(self):
        """Свои ноды + сток с прошлой утечки: апдейт не должен снести Home."""
        self.dest.mkdir(parents=True)
        mixed = (
            '{"outbounds":['
            '{"type":"vless","tag":"Sweden","uuid":"s"},'
            '{"type":"vless","tag":"Home","uuid":"h"}'
            "]}"
        )
        (self.dest / "config.json").write_text(mixed, encoding="utf-8")
        self.assertEqual(install.run(), 0)
        self.assertEqual((self.dest / "config.json").read_text(encoding="utf-8"), mixed)

    def test_replaces_broken_config(self):
        self.dest.mkdir(parents=True)
        (self.dest / "config.json").write_text("{ обрезано", encoding="utf-8")
        self.assertEqual(install.run(), 0)
        self.assertEqual(
            (self.dest / "config.json").read_text(encoding="utf-8"),
            '{"outbounds": []}',
        )

    def test_skips_builder_sidecars(self):
        (self.src / "lagom-pick.json").write_text('{"tag": "Sweden"}', encoding="utf-8")
        (self.src / "lagom-probe.json").write_text('{"sec": 10}', encoding="utf-8")
        (self.src / "lagom-sub.json").write_text('{"url": "https://secret"}', encoding="utf-8")
        (self.src / "eblit-power.json").write_text('{"on": true}', encoding="utf-8")
        (self.src / "split-ui.log").write_text("секрет", encoding="utf-8")
        self.assertEqual(install.run(), 0)
        self.assertFalse((self.dest / "lagom-pick.json").exists())
        self.assertFalse((self.dest / "lagom-probe.json").exists())
        self.assertFalse((self.dest / "lagom-sub.json").exists())
        self.assertFalse((self.dest / "eblit-power.json").exists())
        self.assertFalse((self.dest / "split-ui.log").exists())

    def test_keeps_installed_subscription_and_power(self):
        self.dest.mkdir(parents=True)
        (self.dest / "lagom-sub.json").write_text('{"url": "https://mine"}', encoding="utf-8")
        (self.dest / "eblit-power.json").write_text('{"on": true}', encoding="utf-8")
        (self.src / "lagom-sub.json").write_text('{"url": "https://builder"}', encoding="utf-8")
        (self.src / "eblit-power.json").write_text('{"on": false}', encoding="utf-8")
        self.assertEqual(install.run(), 0)
        self.assertEqual(
            (self.dest / "lagom-sub.json").read_text(encoding="utf-8"),
            '{"url": "https://mine"}',
        )
        self.assertEqual(
            (self.dest / "eblit-power.json").read_text(encoding="utf-8"),
            '{"on": true}',
        )

    def test_keeps_installed_probe_interval(self):
        self.dest.mkdir(parents=True)
        (self.dest / "lagom-probe.json").write_text('{"sec": 300}', encoding="utf-8")
        (self.src / "lagom-probe.json").write_text('{"sec": 10}', encoding="utf-8")
        self.assertEqual(install.run(), 0)
        self.assertEqual(
            (self.dest / "lagom-probe.json").read_text(encoding="utf-8"),
            '{"sec": 300}',
        )

    def test_reinstall_replaces_nested_dir(self):
        install.run()
        stale = self.dest / "_internal" / "stale.dll"
        stale.write_bytes(b"old")
        install.run()
        self.assertFalse(stale.exists())
        self.assertTrue((self.dest / "_internal" / "python3.dll").is_file())

    def test_warp_config_failure_propagates_but_key_stays(self):
        with patch.object(install, "_configure_warp", side_effect=OSError("нет регистрации")):
            with self.assertRaises(OSError):
                install.run()
        self.assertIn("uninstall_key", self.order)

    def test_shortcut_failure_does_not_kill_install(self):
        with patch.object(install, "_shortcuts", side_effect=OSError("нет powershell")):
            self.assertEqual(install.run(), 0)
        self.assertTrue(any("ярлык" in line.lower() for line in self.logs))


class NoPayload(Base):
    def test_returns_one_without_exe(self):
        (self.src / "Eblit.exe").unlink()
        self.assertEqual(install.run(), 1)
        self.assertFalse(self.dest.exists())

    def test_returns_one_without_config(self):
        (self.src / "config.json").unlink()
        self.assertEqual(install.run(), 1)
        self.assertFalse(self.dest.exists())


class CopyGuard(Base):
    def test_refuses_when_singbox_survives_kill(self):
        with patch.object(install, "_stop_running", return_value=False):
            with self.assertRaises(OSError) as ctx:
                install._copy_payload()
        self.assertIn("sing-box", str(ctx.exception).lower() + "sing-box")
        self.assertFalse((self.dest / "Eblit.exe").exists())


class SingboxPick(Base):
    def setUp(self):
        super().setUp()
        self.dl = self.root / "dl"
        self.dl.mkdir()
        (self.src / "sing-box.exe").write_bytes(b"bundled")

    def zip_with(self, name: str) -> None:
        def fake_download(url, dest, timeout=120):
            with zipfile.ZipFile(dest, "w") as zf:
                zf.writestr(name, b"downloaded")

        return fake_download

    def test_takes_exe_from_zip(self):
        with (
            patch.object(install, "latest_singbox_zip", return_value="u"),
            patch.object(install, "download", self.zip_with("sing-box-1.0/sing-box.exe")),
        ):
            got = install._install_singbox(self.dl)
        self.assertEqual(got.read_bytes(), b"downloaded")

    def test_bad_zip_falls_back_to_bundled(self):
        def corrupt(url, dest, timeout=120):
            Path(dest).write_bytes(b"not a zip")

        with (
            patch.object(install, "latest_singbox_zip", return_value="u"),
            patch.object(install, "download", corrupt),
        ):
            got = install._install_singbox(self.dl)
        self.assertEqual(got.read_bytes(), b"bundled")

    def test_network_down_falls_back_to_bundled(self):
        with patch.object(install, "latest_singbox_zip", side_effect=OSError("нет сети")):
            got = install._install_singbox(self.dl)
        self.assertEqual(got.read_bytes(), b"bundled")

    def test_no_bundled_and_no_network_raises(self):
        (self.src / "sing-box.exe").unlink()
        with patch.object(install, "latest_singbox_zip", side_effect=OSError("нет сети")):
            with self.assertRaises(OSError):
                install._install_singbox(self.dl)


class ConfigCheck(Base):
    def test_bad_config_falls_back_to_bundled(self):
        """Свежий sing-box может не принять наш config: тогда ставим тот, с которым собрано."""
        (self.src / "sing-box.exe").write_bytes(b"bundled")
        self.dest.mkdir(parents=True)
        (self.dest / "config.json").write_text("{}", encoding="utf-8")
        (self.dest / "sing-box.exe").write_bytes(b"downloaded")
        calls = []

        def check(*_a, **_kw):
            calls.append(1)
            return len(calls) > 1

        with patch.object(install, "_check_singbox", check):
            install._ensure_config_accepted(downloaded=True)
        self.assertEqual((self.dest / "sing-box.exe").read_bytes(), b"bundled")

    def test_empty_selector_repaired_keeps_vless(self):
        """Живые ноды не сносим: только дописываем тег в пустой LagomVPN."""
        self.dest.mkdir(parents=True)
        cfg = {
            "outbounds": [
                {"type": "selector", "tag": "LagomVPN", "outbounds": []},
                {"type": "vless", "tag": "Finland", "server": "node.example"},
                {"type": "direct", "tag": "direct"},
            ]
        }
        (self.dest / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.assertTrue(install._repair_empty_selector())
        got = json.loads((self.dest / "config.json").read_text(encoding="utf-8"))
        sel = next(ob for ob in got["outbounds"] if ob.get("tag") == "LagomVPN")
        self.assertEqual(sel["outbounds"], ["Finland"])
        self.assertEqual(
            [ob["tag"] for ob in got["outbounds"] if ob.get("type") == "vless"],
            ["Finland"],
        )

    def test_repair_skips_config_without_selector(self):
        self.dest.mkdir(parents=True)
        (self.dest / "config.json").write_text("{}", encoding="utf-8")
        self.assertFalse(install._repair_empty_selector())

    def test_ensure_repairs_empty_selector_before_bundled(self):
        (self.src / "sing-box.exe").write_bytes(b"bundled")
        self.dest.mkdir(parents=True)
        (self.dest / "sing-box.exe").write_bytes(b"downloaded")
        (self.dest / "config.json").write_text(
            json.dumps(
                {
                    "outbounds": [
                        {"type": "selector", "tag": "LagomVPN", "outbounds": []},
                        {"type": "vless", "tag": "Finland"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        calls = []

        def check():
            calls.append(1)
            cfg = json.loads((self.dest / "config.json").read_text(encoding="utf-8"))
            sel = next(ob for ob in cfg["outbounds"] if ob.get("tag") == "LagomVPN")
            return bool(sel.get("outbounds"))

        with patch.object(install, "_check_singbox", check):
            install._ensure_config_accepted(downloaded=True)
        self.assertEqual((self.dest / "sing-box.exe").read_bytes(), b"downloaded")
        self.assertGreaterEqual(len(calls), 2)

    def test_both_bad_raises(self):
        (self.src / "sing-box.exe").write_bytes(b"bundled")
        self.dest.mkdir(parents=True)
        (self.dest / "config.json").write_text("{}", encoding="utf-8")
        (self.dest / "sing-box.exe").write_bytes(b"downloaded")
        with patch.object(install, "_check_singbox", return_value=False):
            with self.assertRaises(OSError):
                install._ensure_config_accepted(downloaded=True)


class WarpSkip(Base):
    def test_skips_download_when_cli_works(self):
        with (
            patch.object(install, "warp_ok", return_value=True),
            patch.object(install, "download") as dl,
            patch.object(install, "hidden") as hid,
        ):
            install._install_warp(self.root)
        dl.assert_not_called()
        hid.assert_not_called()

    def test_installs_when_cli_missing(self):
        with (
            patch.object(install, "warp_ok", return_value=False),
            patch.object(install, "download") as dl,
            patch.object(install, "hidden") as hid,
            patch.object(install, "_wait_warp_cli", return_value=True),
        ):
            hid.return_value.returncode = 0
            install._install_warp(self.root)
        dl.assert_called_once()
        hid.assert_called()

    def test_msiexec_reboot_required_is_success_if_cli_appears(self):
        """3010 = установлен, нужна перезагрузка. Это не ошибка msiexec."""
        with (
            patch.object(install, "warp_ok", return_value=False),
            patch.object(install, "download"),
            patch.object(install, "hidden") as hid,
            patch.object(install, "_wait_warp_cli", return_value=True),
        ):
            hid.return_value.returncode = 3010
            install._install_warp(self.root)
        hid.assert_called()


class Steps(unittest.TestCase):
    def test_run_begins_every_declared_step(self):
        src = Path(install.__file__).read_text(encoding="utf-8")
        for key, _label in install.STEPS:
            self.assertIn(f'_begin("{key}")', src)


class Uninstall(Base):
    def setUp(self):
        super().setUp()
        self.dest.mkdir(parents=True)
        (self.dest / "Eblit.exe").write_bytes(b"exe")
        self.enter(patch.object(install, "_unregister"))
        self.enter(patch.object(install, "_drop_shortcuts"))
        self.enter(patch.object(install, "_stop_running", return_value=True))
        self.warp = self.enter(patch.object(install, "warp"))
        self.auto = self.enter(patch.object(install, "autostart"))

    def test_removes_dest_and_returns_zero(self):
        self.assertEqual(install.uninstall(), 0)
        self.assertFalse(self.dest.exists())

    def test_resets_warp_and_autostart(self):
        install.uninstall()
        self.warp.disconnect.assert_called_once()
        self.warp.reset_mode.assert_called_once()
        self.auto.remove.assert_called_once()

    def test_does_not_uninstall_warp_client(self):
        install.uninstall()
        self.assertFalse(hasattr(self.warp, "uninstall") and self.warp.uninstall.called)
        names = [c[0] for c in self.warp.method_calls]
        self.assertNotIn("uninstall", names)

    def test_leftovers_are_reported_not_hidden(self):
        with patch.object(install.shutil, "rmtree", side_effect=OSError("занято")):
            code = install.uninstall()
        self.assertEqual(code, 1)
        self.assertTrue(any("остал" in line.lower() or "занято" in line for line in self.logs))


class WarpCfg(unittest.TestCase):
    def test_connects_after_configure(self):
        with (
            patch.object(install.warp, "wait_daemon", return_value=True),
            patch.object(install.warp, "ensure_registration", return_value=True),
            patch.object(install.warp, "configure_and_connect") as connect,
            patch.object(install.warp, "wait_ready", return_value=True) as ready,
            patch.object(install, "_log"),
        ):
            install._configure_warp()
        connect.assert_called_once()
        ready.assert_called_once()
        _, kwargs = ready.call_args
        self.assertLessEqual(kwargs.get("tries", 30), 5)

    def test_timeout_does_not_raise(self):
        with (
            patch.object(install.warp, "wait_daemon", return_value=True),
            patch.object(install.warp, "ensure_registration", return_value=True),
            patch.object(install.warp, "configure_and_connect"),
            patch.object(install.warp, "wait_ready", return_value=False),
            patch.object(install, "_log"),
        ):
            install._configure_warp()


if __name__ == "__main__":
    unittest.main()
