from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from app.paths import argv0, root

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE = 0
INFINITE = 0xFFFFFFFF


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def elevate_and_wait(file: str, params: str, *, cwd: str | None = None) -> tuple[bool, int]:
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = file
    info.lpParameters = params
    info.lpDirectory = cwd or str(root())
    info.nShow = SW_HIDE
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False, 1
    if not info.hProcess:
        return False, 1
    ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, INFINITE)
    code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True, int(code.value)


def elevated(stack_args: list[str]) -> tuple[bool, int]:
    """Run `--stack …` as admin and wait. Returns (launched, exit_code)."""
    cmd = argv0()
    params = " ".join(_quote(x) for x in [*cmd[1:], "--stack", *stack_args])
    return elevate_and_wait(cmd[0], params)


def _quote(part: str) -> str:
    if not part:
        return '""'
    if any(ch in part for ch in ' \t"'):
        return '"' + part.replace('"', '\\"') + '"'
    return part


def ensure_admin(stack_cmd: str) -> int | None:
    """If not admin, relaunch this command elevated. None = already admin."""
    if is_admin():
        return None
    launched, code = elevated([stack_cmd])
    if not launched:
        return 2
    return code
