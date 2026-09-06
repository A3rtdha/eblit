"""Mixed-инбаунд наружу: прокси для Quest / телефона в домашней сети.

Тумблер трогает только `inbounds[mixed-local].listen`. Узкий TUN, fake-ip DNS
и WARP не при делах — устройство ходит через `:2080` и получает те же правила
разделения, что и сам ПК.
"""

from __future__ import annotations

import socket

from app.log import write
from app.stack.nodes import read_config, write_config
from app.stack.run import hidden

TAG = "mixed-local"
RULE = "Eblit LAN 2080"
LOCAL = "127.0.0.1"
ANY = "0.0.0.0"
TUN_PREFIX = "172.19.88."


def _mixed(cfg: dict) -> dict:
    for inbound in cfg.get("inbounds", []):
        if isinstance(inbound, dict) and inbound.get("tag") == TAG:
            return inbound
    raise ValueError(f"в config.json нет инбаунда {TAG}")


def _private(ip: str) -> bool:
    if ip.startswith("192.168.") or ip.startswith("10."):
        return True
    if not ip.startswith("172."):
        return False
    try:
        second = int(ip.split(".")[1])
    except (IndexError, ValueError):
        return False
    return 16 <= second <= 31


def address() -> str:
    """Адрес ПК в домашней сети. Адрес TUN сюда попасть не должен: вбитый
    в шлем `172.19.88.1` выглядит рабочим и молча никуда не ведёт."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError as exc:
        write(f"lan: адрес не определён ({exc})")
        return ""
    found: list[str] = []
    for info in infos:
        ip = info[4][0]
        if not isinstance(ip, str) or ip in found:
            continue
        if ip.startswith(TUN_PREFIX) or ip.startswith("127."):
            continue
        if _private(ip):
            found.append(ip)
    found.sort(key=lambda ip: (not ip.startswith("192.168."), not ip.startswith("10."), ip))
    return found[0] if found else ""


def state() -> dict:
    inbound = _mixed(read_config())
    port = int(inbound.get("listen_port") or 0)
    on = str(inbound.get("listen") or LOCAL) == ANY
    return {"on": on, "port": port, "address": address() if on else ""}


def set_enabled(on: bool) -> dict:
    """Только config.json — как и правка доменов, тумблер не дёргает UAC.
    Файрвол догоняет на следующем старте / перезапуске подключения."""
    cfg = read_config()
    _mixed(cfg)["listen"] = ANY if on else LOCAL
    write_config(cfg)
    return state()


def _drop_rule() -> None:
    # Без delete повторное включение плодит одинаковые правила.
    hidden(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE}"], timeout=15)


def sync_firewall() -> None:
    """Зовётся из-под админа (start / reload), поэтому netsh здесь и живёт."""
    try:
        inbound = _mixed(read_config())
    except (OSError, ValueError) as exc:
        write(f"lan: файрвол пропущен ({exc})")
        return
    _drop_rule()
    if str(inbound.get("listen") or LOCAL) != ANY:
        return
    port = int(inbound.get("listen_port") or 0)
    r = hidden(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={RULE}",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={port}",
            # profile=any, а не private: Windows часто метит домашнюю сеть
            # «Общественной», и правило на private молча не срабатывает.
            "profile=any",
        ],
        timeout=15,
    )
    if r.returncode != 0:
        write(f"lan: netsh {r.returncode} {(r.stderr or r.stdout or '').strip()}")
