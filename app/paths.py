"""Repo root next to config.json, or the folder of the frozen exe."""

from __future__ import annotations

import sys
from pathlib import Path


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def root() -> Path:
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def app_dir() -> Path:
    if frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def web_index() -> Path:
    return app_dir() / "web" / "index.html"


def icon_png() -> Path:
    for p in (
        app_dir() / "icon.png",
        Path(__file__).resolve().parent / "assets" / "icon.png",
    ):
        if p.is_file():
            return p
    return Path(__file__).resolve().parent / "assets" / "icon.png"


def icon_ico() -> Path:
    png = icon_png()
    ico = png.with_suffix(".ico")
    return ico if ico.is_file() else png


def singbox() -> Path:
    local = root() / "sing-box.exe"
    if local.is_file() and local.stat().st_size > 0:
        return local
    return Path("sing-box")


def argv0() -> list[str]:
    if frozen():
        return [str(Path(sys.executable).resolve())]
    return [sys.executable, "-m", "app"]
