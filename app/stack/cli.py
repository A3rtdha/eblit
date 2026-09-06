from __future__ import annotations

from app.stack import admin, autostart, lifecycle, probe, teredo


def run(cmd: str) -> int:
    if cmd in {"start", "stop", "reload", "teredo"}:
        bounced = admin.ensure_admin(cmd)
        if bounced is not None:
            return bounced

    if cmd == "start":
        result = lifecycle.start()
        return 0 if result.get("ok") or result.get("power") else 1
    if cmd == "stop":
        result = lifecycle.stop()
        return 1 if result.get("power") else 0
    if cmd == "reload":
        result = lifecycle.reload()
        return 0 if result.get("power") else 1
    if cmd == "test":
        result = probe.full_test(power_on=True)
        print(result.get("detail") or "")
        return 0 if result.get("ok") else 1
    if cmd == "teredo":
        ok, why = teredo.disable()
        print(why)
        return 0 if ok else 1
    if cmd == "autostart-on":
        ok, why = autostart.install()
        print(why)
        return 0 if ok else 1
    if cmd == "autostart-off":
        autostart.remove()
        return 0
    print(f"unknown stack command: {cmd}")
    return 2
