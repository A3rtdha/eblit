"""Tray icon in the same process as the window.

Window handles from the tray thread must use Win32 only (ShowWindow, PostMessage).
pywebview/js_api must not be touched from the tray thread.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

import pystray

from .icon import make_icon
from .log import write

TITLE = "Eblit"
SW_RESTORE = 9
WM_CLOSE = 0x0010
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _pid_self() -> int:
    return int(kernel32.GetCurrentProcessId())


def _enum_top_windows() -> list[int]:
    found: list[int] = []

    @ENUM_PROC
    def collect(hwnd, _param):
        found.append(int(hwnd))
        return True

    user32.EnumWindows(collect, 0)
    return found


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _window_title(hwnd: int) -> str:
    size = int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd))) + 1
    buf = ctypes.create_unicode_buffer(size)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, size)
    return buf.value


def own_hwnd() -> int:
    """Только окно нашего процесса: по заголовку нашлась бы и вторая копия Eblit."""
    me = _pid_self()
    for hwnd in _enum_top_windows():
        if _window_pid(hwnd) == me and _window_title(hwnd) == TITLE:
            return hwnd
    return 0


def show_window() -> None:
    hwnd = own_hwnd()
    if not hwnd:
        return
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def close_window() -> None:
    hwnd = own_hwnd()
    if hwnd:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def start_tray():
    """Иконка в трее отдельным потоком. Вернёт None, если трей не поднялся — окно живёт дальше."""
    icon = {"ref": None}

    def quit_all(*_args) -> None:
        close_window()
        if icon["ref"] is not None:
            icon["ref"].stop()

    def run(tray) -> None:
        try:
            tray.run()
        except Exception as exc:  # трей не критичен: окно должно жить без него
            write(f"tray run: {exc}")

    try:
        menu = pystray.Menu(
            pystray.MenuItem("Открыть", lambda *_: show_window(), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", quit_all),
        )
        tray = pystray.Icon("eblit", make_icon(64), TITLE, menu)
    except Exception as exc:  # то же: без иконки приложение остаётся рабочим
        write(f"tray: {exc}")
        return None

    icon["ref"] = tray
    threading.Thread(target=run, args=(tray,), name="eblit-tray", daemon=True).start()
    return tray
