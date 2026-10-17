"""JS API: power and probes call the same Python stack."""

from __future__ import annotations

import threading
import time
import traceback

from .log import write
from .stack import (
    admin,
    autostart,
    first_pref,
    health,
    lan,
    lifecycle,
    nodes,
    probe,
    probe_pref,
    power_pref,
    roster,
    singbox,
    subscribe,
    updates,
    warp,
)
from .version import VERSION

# Watchdog: пока питание включено, сам ловит обрыв и переподключается.
WD_INTERVAL = 15.0  # как часто щупать, сек
WD_DEBOUNCE = 2  # столько фейлов подряд, чтобы не дёргаться на моргании
WD_MAX_ATTEMPTS = 3  # попыток переподключения, потом «включи вручную»
WD_COOLDOWN = 90.0  # пауза между попытками, сек
WD_GIVEUP_COOLDOWN = 600.0  # после сдачи — долго не трогаем
UPD_INTERVAL = 3600.0  # раз в час, пока процесс жив (окно и трей)


class Bridge:
    """Публичные атрибуты — только методы: pywebview рекурсивно обходит js_api."""

    def __init__(self) -> None:
        self._window = None
        self._busy = False
        self._power = False
        self._tick_busy = False
        self._ping_busy = False
        self._sub_busy = False
        self._update_busy = False
        self._outbox: list[dict] = []
        self._out_lock = threading.Lock()
        self._notify = None
        self._autoreconnect = True
        self._want_on: bool | None = None
        self._wd_started = False
        self._wd_fail = 0
        self._wd_attempts = 0
        self._wd_cooldown_until = 0.0
        self._upd_started = False
        self._update_told = ""
        self._closing = threading.Event()
        self._operation_lock = threading.Lock()
        self._job_lock = threading.RLock()
        self._power_revision = 0
        self._watchdog_revision = 0
        self._stop_requested = False
        self._shutdown_complete = False
        health.resume_probes()

    def set_window(self, window) -> None:
        self._window = window
        self._start_watchdog()
        self._start_update_watch()

    def set_notify(self, fn) -> None:
        """Колбэк OS-уведомки (трей). Без него watchdog просто пишет в лог."""
        self._notify = fn

    def start(self) -> dict:
        return self._job(self._start, requested_power=True)

    def stop(self) -> dict:
        return self._job(self._stop, requested_power=False)

    def reload(self) -> dict:
        return self._job(self._reload)

    def test(self) -> dict:
        return self._job(lambda: probe.full_test(power_on=self._power or singbox.running()))

    def tick(self) -> dict:
        return self._tick_async()

    def status(self) -> dict:
        with self._job_lock:
            revision = self._power_revision
        on = singbox.running()
        want = power_pref.is_on()
        with self._job_lock:
            if revision != self._power_revision or self._busy or self._closing.is_set():
                return {"ok": True, "revision": self._power_revision}
            self._power = on
            if on and self._want_on is None:
                self._want_on = True
            if on:
                self._tick_async()
                return {"ok": True, "power": True, "want_on": want, "revision": revision}
            return {**probe.light_tick(power_on=False), "want_on": want, "revision": revision}

    def restore_power(self, revision: int) -> dict:
        if not power_pref.is_on():
            return {"ok": True}
        with self._job_lock:
            if self._want_on is False or self._power:
                return {"ok": True, "revision": self._power_revision}
            return self._job(self._start, requested_power=True, expected_revision=revision)

    def sync_power(self) -> dict:
        """Пока не busy, подпись = жив ли sing-box. Tick по-прежнему без power."""
        with self._job_lock:
            if self._busy or self._closing.is_set():
                return {"ok": True}
            revision = self._power_revision
        on = singbox.running()
        with self._job_lock:
            if revision != self._power_revision or self._busy or self._closing.is_set():
                return {"ok": True}
            if on == self._power:
                return {"ok": True}
            self._power = on
            if on and self._want_on is None:
                self._want_on = True
        if on:
            self._tick_async()
            return {"ok": True, "power": True, "revision": revision}
        return {**probe.light_tick(power_on=False), "revision": revision}

    def _tick_async(self) -> dict:
        with self._job_lock:
            if self._tick_busy or self._busy or self._closing.is_set():
                return {"ok": True, "pending": True}
            revision = self._power_revision
            self._tick_busy = True

        def run() -> None:
            try:
                on = self._power or singbox.running()
                result = probe.light_tick(power_on=on)
                result.pop("power", None)
                with self._job_lock:
                    if revision == self._power_revision and not self._closing.is_set():
                        self._push({**result, "revision": revision})
            except (OSError, ValueError) as exc:
                write(f"tick fail: {exc}")
            finally:
                with self._job_lock:
                    self._tick_busy = False

        threading.Thread(target=run, name="eblit-tick", daemon=True).start()
        return {"ok": True, "pending": True, "revision": revision}

    def nodes(self) -> dict:
        try:
            return roster.stack_nodes()
        except (OSError, ValueError) as exc:
            write(f"nodes fail: {exc}")
            return {
                "ok": False,
                "nodes": [],
                "selected": None,
                "pick": None,
                "favorite": None,
                "manual": False,
                "auto": True,
                "why": str(exc),
            }

    def add_node(self, parsed: dict) -> dict:
        try:
            return {**nodes.add(parsed), "ok": True}
        except (OSError, ValueError) as exc:
            write(f"add_node fail: {exc}")
            return {**roster.stack_nodes(), "ok": False, "why": str(exc)}

    def remove_node(self, tag: str) -> dict:
        try:
            return {**nodes.remove(tag), "ok": True}
        except (OSError, ValueError) as exc:
            write(f"remove_node fail: {exc}")
            return {**roster.stack_nodes(), "ok": False, "why": str(exc)}

    def select_node(self, tag: str) -> dict:
        try:
            if tag == "auto":
                nodes.clear_manual()
            else:
                nodes.select(tag)
            roster_data = roster.stack_nodes()
        except (OSError, ValueError) as exc:
            write(f"select_node fail: {exc}")
            return {**roster.stack_nodes(), "ok": False, "why": str(exc)}
        restart_info = {"restart": False}
        if singbox.running():
            job = self._job(self._reload)
            restart_info = {"restart": bool(job.get("pending")), "revision": job.get("revision")}
        return {**roster_data, "ok": True, **restart_info}

    def set_favorite(self, tag: str | None) -> dict:
        try:
            nodes.set_favorite(tag or None)
            return {**roster.stack_nodes(), "ok": True}
        except (OSError, ValueError) as exc:
            write(f"set_favorite fail: {exc}")
            return {**roster.stack_nodes(), "ok": False, "why": str(exc)}

    def links(self) -> dict:
        try:
            return {"ok": True, "links": nodes.links()}
        except (OSError, ValueError) as exc:
            return {"ok": False, "links": [], "why": str(exc)}

    def set_links(self, suffixes: list[str]) -> dict:
        """Пишет только config.json: правка домена не должна дёргать UAC и рвать связь."""
        try:
            nodes.set_links(suffixes)
            return {"ok": True, "links": nodes.links()}
        except (OSError, ValueError) as exc:
            write(f"set_links fail: {exc}")
            return {"ok": False, "why": str(exc)}

    def autoreconnect_state(self) -> dict:
        return {"ok": True, "on": self._autoreconnect}

    def set_autoreconnect(self, on: bool) -> dict:
        with self._job_lock:
            self._autoreconnect = bool(on)
            self._watchdog_revision += 1
            self._wd_fail = 0
        write(f"autoreconnect {'on' if self._autoreconnect else 'off'}")
        return {"ok": True, "on": self._autoreconnect}

    def lan_state(self) -> dict:
        try:
            return {"ok": True, **lan.state()}
        except (OSError, ValueError) as exc:
            return {"ok": False, "on": False, "port": 0, "address": "", "why": str(exc)}

    def set_lan(self, on: bool) -> dict:
        """Пишет config.json и, если подключение живо, перезапускает его (UAC) — как выбор
        сервера. Тумблер ждут «сейчас»: шлем уже стоит с открытым полем прокси, а без
        перезапуска sing-box так и слушает 127.0.0.1."""
        try:
            result = lan.set_enabled(bool(on))
        except (OSError, ValueError) as exc:
            write(f"set_lan fail: {exc}")
            return {"ok": False, "on": False, "port": 0, "address": "", "why": str(exc)}
        write(f"lan {'on' if on else 'off'} {result.get('address') or '-'}")
        restart_info = {"restart": False}
        if singbox.running():
            job = self._job(self._reload)
            restart_info = {"restart": bool(job.get("pending")), "revision": job.get("revision")}
        return {"ok": True, **result, **restart_info}

    def get_probe_sec(self) -> dict:
        """Интервал UI-тика. Только файл, без _reload / _job."""
        try:
            return probe_pref.get()
        except OSError as exc:
            write(f"get_probe_sec fail: {exc}")
            return {"ok": False, "sec": probe_pref.DEFAULT_SEC, "why": str(exc)}

    def set_probe_sec(self, sec) -> dict:
        try:
            return probe_pref.set_sec(sec)
        except OSError as exc:
            write(f"set_probe_sec fail: {exc}")
            return {"ok": False, "sec": probe_pref.read_sec(), "why": str(exc)}

    def version(self) -> dict:
        return {"ok": True, "version": VERSION}

    def first_seen(self) -> dict:
        try:
            return first_pref.seen()
        except OSError as exc:
            write(f"first_seen fail: {exc}")
            return {"ok": False, "read": False, "why": str(exc)}

    def first_mark(self) -> dict:
        try:
            return first_pref.mark()
        except OSError as exc:
            write(f"first_mark fail: {exc}")
            return {"ok": False, "read": False, "why": str(exc)}

    def sub_get(self) -> dict:
        try:
            return subscribe.get()
        except OSError as exc:
            write(f"sub_get fail: {exc}")
            return {"ok": False, "url": "", "tags": [], "why": str(exc)}

    def sub_set(self, url: str) -> dict:
        try:
            return subscribe.set_url(url)
        except OSError as exc:
            write(f"sub_set fail: {exc}")
            return {"ok": False, "url": "", "tags": [], "why": str(exc)}

    def sub_pull(self) -> dict:
        """Синхронно стянуть подписку. Для старта окна — до автоподключения."""
        try:
            return subscribe.refresh()
        except (OSError, ValueError) as exc:
            write(f"sub pull fail: {exc}")
            return {**roster.stack_nodes(), "ok": False, "why": subscribe.fetch_error(exc)}

    def sub_refresh(self) -> dict:
        if self._sub_busy:
            return {"ok": True, "pending": True, "ignored": True}

        def run() -> None:
            try:
                result = subscribe.refresh()
                self._push({**result, "kind": "sub"})
            except Exception as exc:  # поток: иначе спиннер в UI навсегда
                write(f"sub fail: {exc}")
                self._push({**roster.stack_nodes(), "ok": False, "kind": "sub", "why": subscribe.fetch_error(exc)})
            finally:
                self._sub_busy = False

        self._sub_busy = True
        threading.Thread(target=run, name="eblit-sub", daemon=True).start()
        return {"ok": True, "pending": True}

    def ping_nodes(self) -> dict:
        if self._ping_busy:
            return {"ok": True, "pending": True, "ignored": True}

        def run() -> None:
            try:
                result = health.scan_all()
                self._push({**result, "kind": "ping"})
            except Exception as exc:  # поток: иначе спиннер в UI навсегда
                write(f"ping fail: {exc}")
                self._push({"ok": False, "kind": "ping", "nodes": [], "why": str(exc)})
            finally:
                self._ping_busy = False

        self._ping_busy = True
        threading.Thread(target=run, name="eblit-ping", daemon=True).start()
        return {"ok": True, "pending": True}

    def check_update(self) -> dict:
        return updates.check()

    def check_update_bg(self) -> dict:
        if self._update_busy:
            return {"ok": True, "pending": True}

        def run() -> None:
            try:
                info = updates.check()
                if info.get("newer") and info.get("asset"):
                    latest = str(info.get("latest") or "")
                    if latest and latest == self._update_told:
                        return
                    self._update_told = latest
                    self._notify_os("Eblit", f"Доступна {latest} — обновите в окне")
                    self._push({**info, "kind": "update", "must": True})
            except (OSError, ValueError) as exc:
                write(f"update check fail: {exc}")
            finally:
                self._update_busy = False

        self._update_busy = True
        threading.Thread(target=run, name="eblit-update", daemon=True).start()
        return {"ok": True, "pending": True}

    def install_update(self) -> dict:
        return self._job(self._install_update)

    def _install_update(self) -> dict:
        info = updates.check()
        if not info.get("ok"):
            return {**info, "kind": "update"}
        if not info.get("newer"):
            return {**info, "kind": "update", "why": info.get("why") or "уже последняя"}
        if not info.get("asset"):
            return {**info, "ok": False, "kind": "update", "why": info.get("why") or "нет установщика"}
        try:
            path = updates.download(str(info["asset"]), expected_digest=str(info.get("digest") or ""))
            updates.launch(path)
        except (OSError, ValueError) as exc:
            write(f"update fail: {exc}")
            return {**info, "ok": False, "kind": "update", "why": str(exc)}
        write(f"update launch {info.get('latest')}")
        return {**info, "ok": True, "kind": "update", "started": True}

    def autostart_state(self) -> dict:
        return {"ok": True, "on": autostart.enabled()}

    def set_autostart(self, on: bool) -> dict:
        if on:
            ok, why = autostart.install()
            write(f"autostart on={ok} {why}")
            return {"ok": ok, "on": ok and autostart.enabled(), "kind": "autostart", "why": why}
        autostart.remove()
        write("autostart off")
        return {"ok": True, "on": False, "kind": "autostart"}

    def hide(self) -> dict:
        if self._window is not None:
            self._window.hide()
        return {"ok": True, "line": ""}

    def minimize(self) -> dict:
        if self._window is not None:
            self._window.minimize()
        return {"ok": True, "line": ""}

    def quit(self) -> dict:
        with self._job_lock:
            if self._closing.is_set():
                return {"ok": True, "pending": True, "revision": self._power_revision}
            self._closing.set()
            self._want_on = False
            self._autoreconnect = False
            self._power_revision += 1
            self._remember_power(False)

        def run() -> None:
            result = self.shutdown()
            if result.get("ok"):
                if self._window is not None:
                    self._window.destroy()
            else:
                with self._job_lock:
                    self._closing.clear()
                    self._stop_requested = False
                health.resume_probes()
                self._push({**result, "kind": "shutdown"})
                self._notify_os("Eblit", result.get("why") or "Не удалось остановить подключение")
                if self._window is not None:
                    self._window.show()

        threading.Thread(target=run, name="eblit-quit", daemon=False).start()
        return {"ok": True, "pending": True}

    def on_closing(self) -> bool:
        if self._shutdown_complete:
            return True
        self.quit()
        return False

    def shutdown(self) -> dict:
        with self._job_lock:
            self._closing.set()
            self._want_on = False
            self._remember_power(False)
        try:
            health.cancel_probes()
            with self._operation_lock:
                if self._shutdown_complete:
                    return {"ok": True}
                if self._power or singbox.running() or warp.owned():
                    result = self._stop()
                    with self._job_lock:
                        self._power = bool(result.get("power"))
                        self._stop_requested = False
                    if not result.get("ok") or result.get("power"):
                        return {**result, "ok": False}
                self._shutdown_complete = True
                return {"ok": True}
        except Exception as exc:
            write(f"shutdown fail: {type(exc).__name__}")
            return {"ok": False, "why": "Не удалось остановить подключение. Повторите выход."}

    def ensure_warp_gui(self) -> dict:
        """Окно Cloudflare сразу, без зонда :40000 — иначе на первом запуске его нет."""
        try:
            opened = bool(warp.open_gui())
            return {"ok": True, "opened": opened}
        except (OSError, ValueError) as exc:
            write(f"warp gui: {exc}")
            return {"ok": False, "opened": False, "why": str(exc)}

    def _start(self) -> dict:
        if not admin.is_admin():
            launched, code = admin.elevated(["start"])
            if not launched:
                return {
                    **probe.light_tick(power_on=singbox.running()),
                    "ok": False,
                    "why": "нужен администратор",
                }
            if code == 0:
                for _ in range(20):
                    if singbox.running():
                        break
                    time.sleep(0.25)
            on = singbox.running()
            result = probe.light_tick(power_on=on)
            result["power"] = on
            if code != 0 and not on:
                result["ok"] = False
                result["power"] = False
                result["why"] = "старт не прошёл"
            if result.get("power"):
                self._remember_started()
            return result
        result = lifecycle.start()
        if result.get("power"):
            self._remember_started()
        return result

    def _stop(self) -> dict:
        if admin.is_admin():
            result = lifecycle.stop()
        else:
            launched, code = admin.elevated(["stop"])
            on = singbox.running()
            result = probe.light_tick(power_on=on)
            result["power"] = on
            if not launched:
                result["ok"] = False
                result["why"] = "нужен администратор"
            elif on:
                result["ok"] = False
                result["why"] = "sing-box не остановился"
            elif code != 0:
                result["ok"] = False
                result["why"] = "Не удалось отключить WARP"
        if not result.get("power"):
            self._want_on = False
            self._remember_power(False)
        return result

    def _reload(self) -> dict:
        with self._job_lock:
            if self._closing.is_set() or self._want_on is False:
                return {**probe.light_tick(power_on=False), "ok": False, "why": "Питание выключено"}
        if not admin.is_admin():
            launched, code = admin.elevated(["reload"])
            if not launched:
                return {**probe.light_tick(power_on=singbox.running()), "ok": False, "why": "нужен администратор"}
            result = probe.light_tick(power_on=singbox.running())
            if code != 0:
                result.update({"ok": False, "why": "перезапуск не прошёл"})
            return result
        return lifecycle.reload()

    def _job(self, fn, *, requested_power: bool | None = None, expected_revision: int | None = None) -> dict:
        with self._job_lock:
            if self._closing.is_set():
                return {"ok": False, "why": "Приложение завершает работу", "revision": self._power_revision}
            if expected_revision is not None and expected_revision != self._power_revision:
                return {"ok": True, "ignored": True, "revision": self._power_revision}
            if fn == self._reload and self._want_on is False:
                return {**probe.light_tick(power_on=False), "ok": False, "why": "Питание выключено", "revision": self._power_revision}
            if self._busy and requested_power is not False:
                return {"ok": False, "pending": False, "why": "уже крутится", "revision": self._power_revision}
            self._power_revision += 1
            revision = self._power_revision
            if requested_power is not None:
                self._want_on = requested_power
                self._wd_fail = 0
                self._wd_attempts = 0
                self._wd_cooldown_until = 0.0
            if requested_power is False:
                self._stop_requested = True
                self._remember_power(False)
            if self._busy:
                return {"ok": True, "pending": True, "revision": revision}
            self._busy = True

        threading.Thread(
            target=self._run_job,
            args=(fn, revision, requested_power),
            name="eblit-stack",
            daemon=True,
        ).start()
        return {"ok": True, "pending": True, "revision": revision}

    def _run_job(self, fn, revision: int, requested_power: bool | None) -> None:
        with self._operation_lock:
            with self._job_lock:
                if self._closing.is_set():
                    self._busy = False
                    return
                stopping = self._stop_requested
            if stopping:
                fn = self._stop
            while True:
                result = self._execute_stack_operation(fn)
                with self._job_lock:
                    if self._closing.is_set():
                        if "power" in result:
                            self._power = bool(result["power"])
                        self._busy = False
                        return
                    if self._stop_requested and not stopping:
                        stopping = True
                        fn = self._stop
                        continue
                    if stopping:
                        self._stop_requested = False
                        revision = self._power_revision
                    if revision == self._power_revision:
                        if "power" in result:
                            self._power = bool(result["power"])
                            if not self._power and (stopping or requested_power is True):
                                self._want_on = False
                        self._push({**result, "revision": revision})
                    self._busy = False
                    return

    def _execute_stack_operation(self, fn) -> dict:
        try:
            return fn()
        except (OSError, ValueError) as exc:
            write(f"stack fail: {exc}")
            return self._stack_failure(str(exc))
        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            location = f"{frames[-1].name}:{frames[-1].lineno}" if frames else "stack"
            write(f"stack fail: {type(exc).__name__} in {location}")
            return self._stack_failure("Ошибка подключения. Проверьте журнал.")

    def _remember_started(self) -> None:
        with self._job_lock:
            if self._closing.is_set() or self._stop_requested or self._want_on is False:
                return
            self._want_on = True
            self._remember_power(True)

    def _stack_failure(self, why: str) -> dict:
        on = self._power
        try:
            on = singbox.running()
        except OSError as exc:
            write(f"stack status fail: {type(exc).__name__}")
        return {"ok": False, "power": on, "why": why}

    def pull(self) -> dict:
        with self._job_lock:
            with self._out_lock:
                while self._outbox:
                    payload = self._outbox.pop(0)
                    revision = payload.get("revision")
                    if revision is None or revision == self._power_revision:
                        return payload
            if self._busy or self._tick_busy or self._ping_busy or self._sub_busy or self._update_busy:
                return {"ok": True, "pending": True, "wait": True}
            return {"ok": True, "pending": True}

    def _push(self, payload: dict) -> None:
        with self._out_lock:
            self._outbox.append(payload)
            if len(self._outbox) > 8:
                del self._outbox[:-8]

    def _remember_power(self, on: bool) -> None:
        try:
            power_pref.set_on(on)
        except OSError as exc:
            write(f"power pref: {exc}")

    def _notify_os(self, title: str, message: str) -> None:
        write(f"notify: {message}")
        if self._notify is None:
            return
        try:
            self._notify(title, message)
        except Exception as exc:  # уведомка не критична — приложение живёт дальше
            write(f"notify fail: {exc}")

    def _start_watchdog(self) -> None:
        if self._wd_started:
            return
        self._wd_started = True
        threading.Thread(target=self._watchdog, name="eblit-watchdog", daemon=True).start()

    def _start_update_watch(self) -> None:
        if self._upd_started:
            return
        self._upd_started = True
        threading.Thread(target=self._update_watch, name="eblit-upd", daemon=True).start()

    def _update_watch(self) -> None:
        while not self._closing.wait(UPD_INTERVAL):
            try:
                self.check_update_bg()
            except (OSError, ValueError) as exc:
                write(f"update watch: {exc}")

    def _watchdog(self) -> None:
        while not self._closing.wait(WD_INTERVAL):
            try:
                self._watchdog_step()
            except (OSError, ValueError) as exc:
                write(f"watchdog: {exc}")

    def _watchdog_step(self) -> None:
        with self._job_lock:
            if self._closing.is_set() or self._busy or not self._autoreconnect:
                return
            revision = self._power_revision
            watchdog_revision = self._watchdog_revision
        running = singbox.running()
        with self._job_lock:
            if revision != self._power_revision or self._closing.is_set() or self._busy or not self._autoreconnect:
                return
            if running and self._want_on is None:
                self._want_on = True
            if not self._want_on:
                self._wd_fail = 0
                self._wd_attempts = 0
                return
            if time.monotonic() < self._wd_cooldown_until:
                return

        if running:
            result = probe.light_tick(power_on=True)
        else:
            # Процесс умер — light_tick тут бесполезен и ещё 10с висит на grok.
            result = {
                "ok": False,
                "legs": {
                    "box": {"state": "bad", "why": "sing-box не запущен"},
                    "warp": {"state": "off", "why": ""},
                    "node": {"state": "off", "why": ""},
                },
            }
        self._finish_watchdog_probe(result, revision=revision, watchdog_revision=watchdog_revision)

    def _finish_watchdog_probe(self, result: dict, *, revision: int, watchdog_revision: int) -> None:
        with self._job_lock:
            if (
                revision != self._power_revision
                or watchdog_revision != self._watchdog_revision
                or self._closing.is_set()
                or self._busy
                or not self._autoreconnect
                or not self._want_on
            ):
                return
            self._apply_watchdog_result(result)

    def _apply_watchdog_result(self, result: dict) -> None:
        if result.get("ok"):
            if self._wd_attempts:
                self._notify_os("Eblit", "Соединение восстановлено")
            self._wd_fail = 0
            self._wd_attempts = 0
            return

        self._wd_fail += 1
        if self._wd_fail < WD_DEBOUNCE:  # одно моргание — не повод рвать TUN
            return
        self._wd_fail = 0

        if self._wd_attempts >= WD_MAX_ATTEMPTS:
            self._notify_os("Eblit", "Не удалось переподключиться. Включите вручную.")
            self._wd_cooldown_until = time.monotonic() + WD_GIVEUP_COOLDOWN
            return

        self._wd_attempts += 1
        leg = probe.bad_leg_name(result.get("legs", {})) or "Соединение"
        self._notify_os("Eblit", f"{leg} отвалилось — переподключаюсь…")
        self._wd_cooldown_until = time.monotonic() + WD_COOLDOWN
        self._push({"ok": True, "kind": "reconnect", "revision": self._power_revision + 1})
        if result.get("legs", {}).get("warp", {}).get("state") == "bad":
            self._job(self._start)
        else:
            self._job(self._reload)
