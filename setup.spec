# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")

root = Path(SPECPATH)
payload = root / "dist" / "Eblit"

# Без этого setup собирался пустым, и юзер узнавал об этом только при запуске.
missing = [n for n in ("Eblit.exe", "config.json", "_internal") if not (payload / n).exists()]
if missing:
    raise SystemExit(f"payload не готов: нет {missing} в {payload} — сначала python -m app.pack")
if not (payload / "sing-box.exe").is_file():
    print(f"ВНИМАНИЕ: нет {payload / 'sing-box.exe'} — установщик останется без запасного sing-box")

a = Analysis(
    [str(root / "app" / "setup" / "__main__.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(payload), "payload"),
        (str(root / "app" / "assets" / "icon.png"), "."),
        (str(root / "app" / "assets" / "icon.ico"), "."),
    ],
    hiddenimports=[
        "app.paths",
        "app.setup.install",
        "app.setup.fetch",
        "app.setup.assets",
        "app.setup.ui",
        "app.stack.warp",
        "app.stack.teredo",
        "app.stack.admin",
        "app.stack.autostart",
        "app.stack.singbox",
        "app.stack.nodes",
        "tkinter",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["webview", "pystray", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EblitSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    uac_admin=True,
    icon=str(root / "app" / "assets" / "icon.ico"),
)
