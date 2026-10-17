from __future__ import annotations

import subprocess

from app.stack import health, singbox, warp
from app.stack.httpchk import has_http, http_line
from app.stack.run import hidden

FIREFOX = "https://eglc860.m1.fastly-masque.net:2499/"
GROK = "https://grok.com/"
CURSOR = "https://api2.cursor.sh/"
MIXED = "127.0.0.1:2080"


def _curl(url: str, *, socks: str | None = None, connect: int = 8, max_time: int = 15) -> tuple[bool, str]:
    args = ["curl.exe", "-4", "-sI", "--connect-timeout", str(connect), "--max-time", str(max_time)]
    if socks:
        args[2:2] = ["--socks5-hostname", socks]
    try:
        r = hidden(args + [url], timeout=max_time + 4)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    line = http_line(r.stdout)
    return has_http(r.stdout), line or "нет HTTP"


def _leg(state: str, why: str) -> dict:
    return {"state": state, "why": why}


def bad_leg_name(legs: dict) -> str | None:
    """Первая упавшая нога человеческим словом — для уведомки watchdog."""
    for key, name in (("box", "sing-box"), ("warp", "WARP"), ("node", "сервер")):
        leg = legs.get(key) if isinstance(legs, dict) else None
        if isinstance(leg, dict) and leg.get("state") == "bad":
            return name
    return None


def full_test(*, power_on: bool) -> dict:
    if not power_on:
        off = _leg("off", "питание выключено")
        return {
            "ok": True,
            "power": False,
            "legs": {"box": off, "warp": off, "node": off},
            "detail": health.last_result_line(),
        }

    warp_status = warp.proxy_probe()
    warp_ok = warp_status["ok"]
    warp_why = warp_status["why"]
    tun_ok, tun_why = _curl("https://open.spotify.com", connect=10, max_time=15)
    ff_ok, _ff = _curl(FIREFOX, connect=8, max_time=10)
    tun_if = singbox.adapter()
    grok_ok, grok_why = _curl(GROK, socks=MIXED, connect=20, max_time=25)
    cur_ok, _cur = _curl(CURSOR, socks=MIXED, connect=15, max_time=20)
    last = health.last_result_line()
    proc = singbox.running()
    box_ok = proc and tun_if
    box_why = (
        "sing-box и tun-fastly"
        if box_ok
        else ("нет tun-fastly" if not tun_if else "sing-box не запущен")
    )
    return {
        "ok": box_ok and warp_ok and grok_ok,
        "power": True,
        "legs": {
            "box": _leg("ok" if box_ok else "bad", box_why),
            "warp": _leg("ok" if warp_ok else "bad", warp_why),
            "node": _leg("ok" if grok_ok else "bad", "сервер отвечает" if grok_ok else f"сервер {grok_why}"),
        },
        "smoke": {
            "warp": warp_ok,
            "tun_http": tun_ok,
            "firefox": ff_ok,
            "tun_if": tun_if,
            "grok": grok_ok,
            "cursor": cur_ok,
            "tun_http_why": tun_why,
        },
        "detail": last or "нет health.log",
    }


def light_tick(*, power_on: bool) -> dict:
    if not power_on:
        off = _leg("off", "питание выключено")
        return {"ok": True, "power": False, "legs": {"box": off, "warp": off, "node": off}}

    proc = singbox.running()
    tun_if = singbox.adapter()
    warp_status = warp.proxy_probe()
    warp_ok = warp_status["ok"]
    grok_ok, grok_why = _curl(GROK, socks=MIXED, connect=8, max_time=10)
    box_ok = proc and tun_if
    return {
        "ok": box_ok and warp_ok and grok_ok,
        "power": True,
        "legs": {
            "box": _leg(
                "ok" if box_ok else "bad",
                "sing-box и tun-fastly" if box_ok else ("нет tun-fastly" if not tun_if else "sing-box не запущен"),
            ),
            "warp": _leg("ok" if warp_ok else "bad", warp_status["why"]),
            "node": _leg("ok" if grok_ok else "bad", "сервер отвечает" if grok_ok else f"сервер {grok_why}"),
        },
    }
