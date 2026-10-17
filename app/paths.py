"""Install dir (exe) vs writable user data (config, sidecars, logs)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.storage import atomic_write

_DATA_FILES = (
    "config.json",
    "eblit-nodes.json",
    "eblit-ips.json",
    "eblit-pick.json",
    "eblit-favorite.json",
    "eblit-probe.json",
    "eblit-sub.json",
    "eblit-power.json",
    "eblit-first.json",
    "eblit-warp.json",
    "split-ui.log",
    "health.log",
    "sing-box.log",
)
_MIGRATE_STAMP = ".data-root-v1"
_data_root: Path | None = None


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def root() -> Path:
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _migrate(install: Path, data: Path) -> None:
    if (data / _MIGRATE_STAMP).is_file():
        return
    data.mkdir(parents=True, exist_ok=True)
    for name in _DATA_FILES:
        src = install / name
        dst = data / name
        if src.is_file() and not dst.is_file():
            atomic_write(dst, src.read_text(encoding="utf-8"))
    atomic_write(data / _MIGRATE_STAMP, str(install))


def _migrate_names(data: Path) -> None:
    stamp = data / ".legacy-names-v2"
    if stamp.is_file():
        return
    for suffix in ("nodes", "ips", "pick", "favorite", "probe", "sub"):
        old = data / f"lagom-{suffix}.json"
        new = data / f"eblit-{suffix}.json"
        if old.is_file() and not new.exists():
            atomic_write(new, old.read_text(encoding="utf-8"))
    atomic_write(stamp, "2\n")


def data_root() -> Path:
    """Use the same user directory before and after elevation."""
    global _data_root
    if not frozen():
        _migrate_names(root())
        return root()
    if _data_root is not None:
        return _data_root
    install = root()
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Eblit"
    if not (local / "config.json").is_file() and not (install / "config.json").is_file():
        local.mkdir(parents=True, exist_ok=True)
        _data_root = local
        return local
    _migrate(install, local)
    for old in install.glob("lagom-*.json"):
        if not (local / old.name).exists():
            atomic_write(local / old.name, old.read_text(encoding="utf-8"))
    _migrate_names(local)
    _data_root = local
    return _data_root


def reset_data_root_cache() -> None:
    """Tests only: clear memoized data_root()."""
    global _data_root
    _data_root = None


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
