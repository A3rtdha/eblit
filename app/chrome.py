"""Strip the native Win32 caption without pywebview frameless (that hangs pythonnet)."""

from __future__ import annotations

import ctypes

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def strip_native_caption(title: str = "Eblit") -> None:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)
    user32.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )
    pref = ctypes.c_int(DWMWCP_ROUND)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd,
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(pref),
        ctypes.sizeof(pref),
    )
