"""Интервал UI-проб рядом с config.json. Не health.probe и не tick-математика."""

from __future__ import annotations

import json

import app.paths as paths

DEFAULT_SEC = 30
PROBE_FILE = "lagom-probe.json"


def _path():
    return paths.root() / PROBE_FILE


def _coerce(raw) -> int | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip().replace(",", ".")
        if not raw:
            return None
        try:
            raw = float(raw)
        except ValueError:
            return None
    if isinstance(raw, (int, float)):
        if raw != raw or raw in (float("inf"), float("-inf")):
            return None
        sec = int(raw)
        if sec < 10:
            return None
        return sec
    return None


def read_sec() -> int:
    got = get()
    return int(got["sec"])


def get() -> dict:
    path = _path()
    if not path.is_file():
        return {"ok": True, "sec": DEFAULT_SEC}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"ok": False, "sec": DEFAULT_SEC, "why": "битый lagom-probe.json"}
    parsed = _coerce(data.get("sec") if isinstance(data, dict) else None)
    if parsed is None:
        return {"ok": False, "sec": DEFAULT_SEC, "why": "неверный интервал"}
    return {"ok": True, "sec": parsed}


def set_sec(sec) -> dict:
    parsed = _coerce(sec)
    if parsed is None:
        return {"ok": False, "sec": read_sec(), "why": "неверный интервал"}
    path = _path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"sec": parsed}) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "sec": parsed}
