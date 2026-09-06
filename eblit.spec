# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "eblit_boot.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "app" / "web"), "web"),
        (str(root / "app" / "assets" / "icon.png"), "."),
        (str(root / "app" / "assets" / "icon.ico"), "."),
    ],
    hiddenimports=[
        "app",
        "app.__main__",
        "app.place",
        "app.tray",
        "app.stack.cli",
        "app.stack.health",
        "app.stack.lifecycle",
        "app.stack.probe",
        "app.stack.roster",
        "app.stack.updates",
        "app.version",
        "webview.platforms.edgechromium",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Eblit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(root / "app" / "assets" / "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Eblit",
)
