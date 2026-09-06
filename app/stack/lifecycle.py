from __future__ import annotations

import time

from app.log import write
from app.stack import health, lan, probe, singbox, warp


def start() -> dict:
    write("подключение: старт")
    singbox.kill()
    time.sleep(2)
    if health.main() != 0:
        write("health: нет живого сервера — стартуем как есть")
    ok, err = singbox.check()
    if not ok:
        write(f"config: {err}")
        result = probe.full_test(power_on=False)
        result.update({"ok": False, "power": False, "why": err})
        return result
    warp.configure_and_connect()
    if not warp.wait_ready():
        write("WARP :40000 timeout")
        result = probe.full_test(power_on=False)
        result.update({"ok": False, "power": False, "why": "WARP :40000 молчит"})
        return result
    lan.sync_firewall()
    singbox.start()
    if not singbox.wait_tun():
        write("TUN Spotify timeout — проверка всё равно")
    result = probe.full_test(power_on=True)
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
    warp.disconnect()
    return {"ok": True, "power": False, **probe.light_tick(power_on=False)}


def reload() -> dict:
    write("подключение: перезапуск")
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
    time.sleep(2)
    lan.sync_firewall()
    singbox.start()
    if not singbox.wait_tun():
        write("TUN Spotify timeout — проверка всё равно")
    result = probe.full_test(power_on=True)
    result["power"] = True
    write("подключение: перезапуск готов")
    return result
