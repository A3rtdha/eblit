from __future__ import annotations

import ctypes
import sys

from .log import write
from .paths import web_index
from .place import pick_screen, xy_for_screen

WIDTH = 400
HEIGHT = 620


def _cursor() -> tuple[int, int]:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--stack"]:
        from .stack.cli import run

        return run(args[1] if len(args) > 1 else "")

    page = web_index()
    if not page.is_file():
        print(f"нет UI: {page}", file=sys.stderr)
        return 1

    import webview

    from .bridge import Bridge
    from .tray import start_tray

    ctypes.windll.user32.SetProcessDPIAware()
    screens = webview.screens
    target = pick_screen(list(screens), _cursor()) if screens else None
    x = y = None
    if target is not None:
        x, y = xy_for_screen(target, WIDTH, HEIGHT)

    bridge = Bridge()
    window = webview.create_window(
        "Eblit",
        url=str(page),
        width=WIDTH,
        height=HEIGHT,
        x=x,
        y=y,
        frameless=True,
        easy_drag=True,
        resizable=False,
        shadow=True,
        background_color="#09090b",
        js_api=bridge,
    )
    bridge.set_window(window)
    tray = start_tray()
    if tray is not None:
        # pystray.notify(message, title) — полноценный балун Windows из трея.
        bridge.set_notify(lambda title, msg: tray.notify(msg, title))
    try:
        webview.start(gui="edgechromium")
    finally:
        if tray is not None:
            try:
                tray.stop()
            except Exception as exc:  # выходим: иконку всё равно снимет завершение процесса
                write(f"tray stop: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
