"""Install dir (exe) vs writable user data (config, sidecars, logs)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_DATA_FILES = (
    "config.json",
    "lagom-nodes.json",
    "lagom-ips.json",
    "lagom-pick.json",
    "lagom-favorite.json",
    "lagom-probe.json",
    "lagom-sub.json",
    "eblit-power.json",
    "eblit-first.json",
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


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _migrate(install: Path, data: Path) -> None:
    if (data / _MIGRATE_STAMP).is_file():
        return
    data.mkdir(parents=True, exist_ok=True)
    for name in _DATA_FILES:
        src = install / name
        dst = data / name
        if src.is_file() and not dst.is_file():
            shutil.copy2(src, dst)
    if install.is_dir():
        for src in install.glob("_probe*.json"):
            dst = data / src.name
            if src.is_file() and not dst.is_file():
                shutil.copy2(src, dst)
    (data / _MIGRATE_STAMP).write_text(str(install), encoding="utf-8")


def data_root() -> Path:
    """Config and sidecars. Repo root in dev; AppData when Program Files is read-only."""
    global _data_root
    if not frozen():
        return root()
    if _data_root is not None:
        return _data_root
    install = root()
    if _writable(install):
        _data_root = install
        return _data_root
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Eblit"
    _migrate(install, local)
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
