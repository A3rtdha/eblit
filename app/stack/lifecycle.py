from __future__ import annotations

from functools import wraps

from app.log import write
from app.stack import health, lan, probe, singbox, subscribe, warp


def _rollback_on_error(fn):
    @wraps(fn)
    def run():
        try:
            return fn()
        except Exception:
            try:
                stop()
            except Exception as exc:
                write(f"cleanup fail: {type(exc).__name__}")
            raise

    return run


@_rollback_on_error
def start() -> dict:
    write("подключение: старт")
    try:
        from app.stack import nodes

        if nodes.ensure_seed_suffixes_file():
            write("домены: Gemini/AI Studio дописаны в список")
        if nodes.ensure_telegram_cidrs_file():
            write("telegram: DC-сети в TUN")
    except (OSError, ValueError, TypeError) as exc:
        write(f"домены: {exc}")
    singbox.kill()
    if not singbox.wait_gone():
        raise OSError("sing-box не остановился")
    try:
        sub = subscribe.refresh()
        if not sub.get("ok") and not sub.get("skipped"):
            write(f"подписка: {sub.get('why') or 'не обновилась'}")
    except (OSError, ValueError) as exc:
        write(f"подписка: {exc}")
    if health.main() != 0:
        write("health: нет живого сервера — стартуем как есть")
    ok, err = singbox.check()
    if not ok:
        write(f"config: {err}")
        result = probe.light_tick(power_on=False)
        result.update({"ok": False, "power": False, "why": err})
        return result
    warp.configure_and_connect()
    if not warp.wait_ready():
        write("WARP: не подтверждён доступ в интернет через :40000")
        warp.disconnect()
        result = probe.light_tick(power_on=False)
        result.update({"ok": False, "power": False, "why": "WARP: не подтверждён доступ в интернет через :40000"})
        return result
    lan.sync_firewall()
    singbox.start()
    if not singbox.wait_tun():
        result = stop()
        result.update({"ok": False, "why": "TUN не готов — подключение остановлено"})
        return result
    result = probe.light_tick(power_on=True)
    result["ok"] = bool(result.get("ok"))
    result["power"] = True
    write("подключение: старт готов")
    return result


def stop() -> dict:
    write("подключение: стоп")
    singbox.kill()
    if not singbox.wait_gone():
        write("stop: sing-box жив — WARP не рвём")
        result = probe.light_tick(power_on=True)
        result.update({"ok": False, "power": True, "why": "sing-box не остановился"})
        return result
    disconnected = warp.disconnect()
    result = probe.light_tick(power_on=False)
    result.update({"ok": bool(disconnected), "power": False})
    if not disconnected:
        result["why"] = "WARP не отключился"
    return result


@_rollback_on_error
def reload() -> dict:
    write("подключение: перезапуск")
    try:
        from app.stack import nodes

        if nodes.ensure_telegram_cidrs_file():
            write("telegram: DC-сети в TUN")
    except (OSError, ValueError, TypeError) as exc:
        write(f"telegram: {exc}")
    if health.main() != 0:
        write("health: нет живого сервера — перезапуск как есть")
    ok, err = singbox.check()
    if not ok:
        write(f"config: {err}")
        on = singbox.running()
        result = probe.light_tick(power_on=on)
        result.update({"ok": False, "power": on, "why": err})
        return result
    singbox.kill()
    if not singbox.wait_gone():
        raise OSError("sing-box не остановился")
    lan.sync_firewall()
    singbox.start()
    if not singbox.wait_tun():
        result = stop()
        result.update({"ok": False, "why": "TUN не готов — подключение остановлено"})
        return result
    result = probe.light_tick(power_on=True)
    result["power"] = True
    write("подключение: перезапуск готов")
    return result
