from __future__ import annotations

from functools import wraps

from app.log import write
from app.stack import configuration, health, lan, nodes, probe, routing_safety, singbox, subscribe, warp


@configuration.changing
def _prepare_routing() -> None:
    cfg = nodes.read_config()
    changed = nodes.repair_proxy_suffixes(cfg)
    changed = nodes.migrate_fastly_routes(cfg) or changed
    changed = nodes.remove_telegram_routes(cfg) or changed
    changed = routing_safety.apply_game_bypass(cfg) or changed
    if changed:
        nodes.write_config(cfg)
        write("маршруты: домены проверены, Riot напрямую, Telegram исключён")


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
    _prepare_routing()
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
    _prepare_routing()
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
