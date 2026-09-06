"""JS API: power and probes call the same Python stack."""

from __future__ import annotations

import threading
import time

from .log import write
from .stack import admin, autostart, lan, lifecycle, nodes, probe, roster, singbox, updates
from .version import VERSION

# Watchdog: пока питание включено, сам ловит обрыв и переподключается.
WD_INTERVAL = 15.0  # как часто щупать, сек
WD_DEBOUNCE = 2  # столько фейлов подряд, чтобы не дёргаться на моргании
WD_MAX_ATTEMPTS = 3  # попыток переподключения, потом «включи вручную»
WD_COOLDOWN = 90.0  # пауза между попытками, сек
WD_GIVEUP_COOLDOWN = 600.0  # после сдачи — долго не трогаем


class Bridge:
    """Публичные атрибуты — только методы: pywebview рекурсивно обходит js_api."""

    def __init__(self) -> None:
        self._window = None
        self._busy = False
        self._power = False
        self._tick_busy = False
        self._outbox: list[dict] = []
        self._out_lock = threading.Lock()
        self._notify = None
        self._autoreconnect = True
        self._want_on = False
        self._wd_started = False
        self._wd_fail = 0
        self._wd_attempts = 0
        self._wd_cooldown_until = 0.0

    def set_window(self, window) -> None:
        self._window = window
        self._start_watchdog()

    def set_notify(self, fn) -> None:
        """Колбэк OS-уведомки (трей). Без него watchdog просто пишет в лог."""
        self._notify = fn

    def start(self) -> dict:
        return self._job(self._start)

    def stop(self) -> dict:
        return self._job(self._stop)

    def reload(self) -> dict:
        return self._job(self._reload)

    def test(self) -> dict:
        return self._job(lambda: probe.full_test(power_on=self._power or singbox.running()))

    def tick(self) -> dict:
        return self._tick_async()

    def status(self) -> dict:
        on = singbox.running()
        self._power = on
        if not on:
            return probe.light_tick(power_on=False)
        self._tick_async()
        return {"ok": True, "power": True}

    def _tick_async(self) -> dict:
        if self._tick_busy:
            return {"ok": True, "pending": True}

        def run() -> None:
            try:
                on = self._power or singbox.running()
                result = probe.light_tick(power_on=on)
                result.pop("power", None)
                self._push(result)
            except (OSError, ValueError) as exc:
                write(f"tick fail: {exc}")
            finally:
                self._tick_busy = False

        self._tick_busy = True
        threading.Thread(target=run, name="eblit-tick", daemon=True).start()
        return {"ok": True, "pending": True}

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
            return {"ok": False, "why": str(exc), **roster.stack_nodes()}

    def remove_node(self, tag: str) -> dict:
        try:
            return {**nodes.remove(tag), "ok": True}
        except (OSError, ValueError) as exc:
            write(f"remove_node fail: {exc}")
            return {"ok": False, "why": str(exc), **roster.stack_nodes()}

    def select_node(self, tag: str) -> dict:
        try:
            if tag == "auto":
                nodes.clear_manual()
            else:
                nodes.select(tag)
            return self._job(self._reload)
        except (OSError, ValueError) as exc:
            write(f"select_node fail: {exc}")
            return {"ok": False, "why": str(exc), **roster.stack_nodes()}

    def set_favorite(self, tag: str | None) -> dict:
        try:
            nodes.set_favorite(tag or None)
            return {**roster.stack_nodes(), "ok": True}
        except (OSError, ValueError) as exc:
            write(f"set_favorite fail: {exc}")
            return {"ok": False, "why": str(exc), **roster.stack_nodes()}

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
        self._autoreconnect = bool(on)
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
        restart = False
        if singbox.running():
            restart = bool(self._job(self._reload).get("pending"))
        return {"ok": True, **result, "restart": restart}

    def version(self) -> dict:
        return {"ok": True, "version": VERSION}

    def check_update(self) -> dict:
        return updates.check()

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
            path = updates.download(str(info["asset"]))
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
        if self._window is not None:
            self._window.destroy()
        return {"ok": True, "line": ""}

    def _start(self) -> dict:
        if not admin.is_admin():
            launched, code = admin.elevated(["start"])
            if not launched:
                return {
                    "ok": False,
                    "power": False,
                    "why": "нужен администратор",
                    **probe.full_test(power_on=False),
                }
            result = probe.full_test(power_on=code == 0 or singbox.running())
            result["power"] = bool(result.get("power")) and singbox.running()
            if code != 0 and not singbox.running():
                result["ok"] = False
                result["power"] = False
                result["why"] = "старт не прошёл"
            if result.get("power"):
                self._want_on = True
            return result
        result = lifecycle.start()
        if result.get("power"):
            self._want_on = True
        return result

    def _stop(self) -> dict:
        if admin.is_admin():
            result = lifecycle.stop()
        else:
            launched, _code = admin.elevated(["stop"])
            on = singbox.running()
            result = probe.light_tick(power_on=on)
            result["power"] = on
            if not launched:
                result["ok"] = False
                result["why"] = "нужен администратор"
            elif on:
                result["ok"] = False
                result["why"] = "sing-box не остановился"
        if not result.get("power"):
            self._want_on = False
        return result

    def _reload(self) -> dict:
        if not admin.is_admin():
            launched, code = admin.elevated(["reload"])
            if not launched:
                return {"ok": False, "why": "нужен администратор", **probe.light_tick(power_on=singbox.running())}
            return probe.full_test(power_on=singbox.running())
        return lifecycle.reload()

    def _job(self, fn) -> dict:
        if self._busy:
            return {"ok": False, "pending": False, "why": "уже крутится"}
        self._busy = True

        def run() -> None:
            try:
                result = fn()
                if "power" in result:
                    self._power = bool(result.get("power"))
                self._push(result)
            except (OSError, ValueError) as exc:
                write(f"stack fail: {exc}")
                self._power = False
                self._push({"ok": False, "power": False, "why": str(exc), **probe.full_test(power_on=False)})
            finally:
                self._busy = False

        threading.Thread(target=run, name="eblit-stack", daemon=True).start()
        return {"ok": True, "pending": True}

    def pull(self) -> dict:
        with self._out_lock:
            if self._outbox:
                return self._outbox.pop(0)
        if self._busy or self._tick_busy:
            return {"ok": True, "pending": True, "wait": True}
        return {"ok": True, "pending": True}

    def _push(self, payload: dict) -> None:
        with self._out_lock:
            self._outbox.append(payload)
            if len(self._outbox) > 8:
                del self._outbox[:-8]

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

    def _watchdog(self) -> None:
        while True:
            time.sleep(WD_INTERVAL)
            try:
                self._watchdog_step()
            except (OSError, ValueError) as exc:
                write(f"watchdog: {exc}")

    def _watchdog_step(self) -> None:
        # Ручная операция сама разберётся; выключенное питание и снятый тумблер — не наше дело.
        if self._busy or not self._autoreconnect:
            return
        running = singbox.running()
        # Окно открыли, а стек уже жил (прошлый сеанс) — держим его, пока юзер сам не выключит.
        if running:
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
        self._push({"ok": True, "kind": "reconnect"})
        self._job(self._reload)  # сам поставит _busy и запушит результат
