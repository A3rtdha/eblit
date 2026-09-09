"""Питание было включено — sidecar рядом с config.json. Не _want_on и не watchdog."""

from __future__ import annotations

import json

import app.paths as paths

POWER_FILE = "eblit-power.json"


def _path():
    return paths.root() / POWER_FILE


def get() -> dict:
    path = _path()
    if not path.is_file():
        return {"ok": True, "on": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"ok": False, "on": False, "why": "битый eblit-power.json"}
    if not isinstance(data, dict) or not isinstance(data.get("on"), bool):
        return {"ok": False, "on": False, "why": "неверное питание"}
    return {"ok": True, "on": data["on"]}


def is_on() -> bool:
    return bool(get()["on"])


def set_on(on: bool) -> dict:
    path = _path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"on": bool(on)}
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, **payload}
