from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from functools import wraps

from app import paths
from app.storage import atomic_write

_LOCK = threading.RLock()
_LOCAL = threading.local()
LEGACY_SELECTOR = "LagomVPN"
SELECTOR = "proxy-select"


@contextmanager
def locked():
    with _LOCK:
        if getattr(_LOCAL, "active", False):
            yield
            return
        path = paths.data_root() / "config.json.lock"
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + 10
            while True:
                stream.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("config.json занят другой операцией")
                    time.sleep(0.05)
            _LOCAL.active = True
            try:
                yield
            finally:
                _LOCAL.active = False
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def changing(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        with locked():
            return fn(*args, **kwargs)

    return run


def migrate_selector(cfg: dict) -> bool:
    tags = {ob.get("tag") for ob in cfg.get("outbounds", []) if isinstance(ob, dict)}
    if LEGACY_SELECTOR in tags and SELECTOR in tags:
        raise ValueError("config.json: имя proxy-select уже занято сервером")
    changed = False

    def visit(value):
        nonlocal changed
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"tag", "outbound", "detour", "final", "default"} and item == LEGACY_SELECTOR:
                    value[key] = SELECTOR
                    changed = True
                elif key == "outbounds" and isinstance(item, list):
                    value[key] = [SELECTOR if tag == LEGACY_SELECTOR else tag for tag in item]
                    changed |= value[key] != item
                    for child in value[key]:
                        visit(child)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(cfg)
    return changed


def read() -> dict:
    path = paths.data_root() / "config.json"
    for attempt in range(3):
        try:
            text = path.read_text(encoding="utf-8-sig")
            break
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.05)
    try:
        cfg = json.loads(text)
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"{path}: повреждён или пуст. Восстановите конфигурацию из резервной копии") from exc
    if not isinstance(cfg, dict) or not isinstance(cfg.get("outbounds"), list):
        raise ValueError(f"{path}: ожидается объект с массивом outbounds")
    for key in ("outbounds", "inbounds"):
        entries = cfg.get(key, [])
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            raise ValueError(f"{path}: {key} должен содержать объекты")
    for key in ("dns", "route"):
        section = cfg.get(key, {})
        if not isinstance(section, dict):
            raise ValueError(f"{path}: {key} должен быть объектом")
        rules = section.get("rules", [])
        if not isinstance(rules, list) or any(not isinstance(item, dict) for item in rules):
            raise ValueError(f"{path}: {key}.rules должен содержать объекты")
    if any(ob.get("tag") == LEGACY_SELECTOR for ob in cfg["outbounds"]):
        with locked():
            current = json.loads(path.read_text(encoding="utf-8-sig"))
            if migrate_selector(current):
                atomic_write(path, json.dumps(current, indent=2) + "\n")
            cfg = current
    return cfg
