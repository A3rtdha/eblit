"""Первый экран уже прочитан — sidecar рядом с config.json. Не localStorage."""

from __future__ import annotations

import json

import app.paths as paths

FIRST_FILE = "eblit-first.json"
_POWER_FILE = "eblit-power.json"
_SUB_FILE = "lagom-sub.json"


def _path():
    return paths.root() / FIRST_FILE


def _write(read: bool) -> dict:
    path = _path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"read": bool(read)}
    tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, **payload}


def _legacy_user() -> bool:
    """Уже ставили и пользовались: апдейт не должен снова показывать экран."""
    root = paths.root()
    if (root / _POWER_FILE).is_file():
        return True
    if (root / _SUB_FILE).is_file():
        return True
    return False


def seen() -> dict:
    path = _path()
    if not path.is_file():
        if _legacy_user():
            return _write(True)
        return {"ok": True, "read": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"ok": False, "read": False, "why": "битый eblit-first.json"}
    if not isinstance(data, dict) or not isinstance(data.get("read"), bool):
        return {"ok": False, "read": False, "why": "неверный first"}
    return {"ok": True, "read": data["read"]}


def mark() -> dict:
    return _write(True)
