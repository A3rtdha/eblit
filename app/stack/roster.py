"""Vless nodes from config.json: hostnames, live IPs, selector pick. Read-only."""

from __future__ import annotations

import json
import time
from pathlib import Path

import app.paths as paths
from app.stack import nodes

SELECTOR = "LagomVPN"


def _read_json(path: Path, tries: int = 3) -> tuple[object | None, str]:
    last = ""
    for _ in range(tries):
        try:
            return json.loads(path.read_text(encoding="utf-8")), ""
        except FileNotFoundError:
            return None, f"нет {path.name}"
        except PermissionError as exc:
            last = f"{path.name} занят: {exc}"
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            return None, f"{path.name} битый: {exc}"
        time.sleep(0.15)
    return None, last


def _selected(outbounds: list) -> str | None:
    for ob in outbounds:
        if isinstance(ob, dict) and ob.get("tag") == SELECTOR:
            picked = ob.get("outbounds")
            if isinstance(picked, list) and picked and isinstance(picked[0], str):
                return picked[0]
            return None
    return None


def _ip_to_host() -> dict[str, str]:
    data, _why = _read_json(paths.root() / "lagom-ips.json", tries=1)
    if not isinstance(data, dict):
        return {}
    return {str(ip): str(host) for host, ip in data.items() if isinstance(ip, str)}


def _pick() -> dict | None:
    data, _why = _read_json(paths.root() / "lagom-pick.json", tries=1)
    if not isinstance(data, dict):
        return None
    tag, ip = data.get("tag"), data.get("ip")
    if not isinstance(tag, str) or not tag:
        return None
    out = {"tag": tag, "ip": ip if isinstance(ip, str) else ""}
    if data.get("manual"):
        out["manual"] = True
    return out


def _favorite() -> str | None:
    data, _why = _read_json(paths.root() / "lagom-favorite.json", tries=1)
    if not isinstance(data, dict):
        return None
    tag = data.get("tag")
    return tag if isinstance(tag, str) and tag else None


def _sni(ob: dict) -> str:
    tls = ob.get("tls")
    if not isinstance(tls, dict):
        return ""
    name = tls.get("server_name")
    return name if isinstance(name, str) else ""


def stack_nodes() -> dict:
    empty = {
        "ok": False,
        "nodes": [],
        "selected": None,
        "pick": None,
        "favorite": None,
        "manual": False,
        "auto": True,
    }
    cfg, why = _read_json(paths.root() / "config.json")
    if not isinstance(cfg, dict):
        return {**empty, "why": why or "config.json битый"}
    outbounds = cfg.get("outbounds")
    if not isinstance(outbounds, list):
        return {**empty, "why": "в config.json нет outbounds"}

    selected = _selected(outbounds)
    host_map = nodes.hosts()
    ip_hosts = _ip_to_host()
    pick = _pick()
    favorite = _favorite()
    manual = bool(pick and pick.get("manual"))
    node_rows = []
    for ob in outbounds:
        if not isinstance(ob, dict) or ob.get("type") != "vless":
            continue
        tag = ob.get("tag")
        if not isinstance(tag, str) or not tag:
            continue
        ip = ob.get("server")
        ip = ip if isinstance(ip, str) else ""
        node_rows.append(
            {
                "tag": tag,
                "host": host_map.get(tag) or ip_hosts.get(ip, ""),
                "ip": ip,
                "port": ob.get("server_port") if isinstance(ob.get("server_port"), int) else 0,
                "sni": _sni(ob),
                "current": tag == selected,
                "custom": not nodes.is_builtin_tag(tag),
                "favorite": tag == favorite,
            }
        )
    return {
        "ok": True,
        "nodes": node_rows,
        "selected": selected,
        "pick": pick,
        "favorite": favorite,
        "manual": manual,
        "auto": not manual,
        "why": "",
    }
