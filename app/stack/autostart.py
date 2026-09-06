"""HKCU Run — start the app with the user session. No admin, no schtasks."""

from __future__ import annotations

import winreg

from app.paths import argv0
from app.stack.run import hidden

NAME = "Eblit"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
OLD_TASK = "ZapretFastlySplit"
OLD_TASK_NEW = "Eblit"


def command() -> str:
    return " ".join(f'"{p}"' if " " in p else p for p in argv0())


def enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            val, _ = winreg.QueryValueEx(key, NAME)
        return bool(str(val).strip())
    except OSError:
        return False


def install() -> tuple[bool, str]:
    hidden(["schtasks", "/Delete", "/TN", OLD_TASK, "/F"])
    hidden(["schtasks", "/Delete", "/TN", OLD_TASK_NEW, "/F"])
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
    except OSError as exc:
        return False, str(exc)
    return True, NAME


def remove() -> None:
    hidden(["schtasks", "/Delete", "/TN", OLD_TASK, "/F"])
    hidden(["schtasks", "/Delete", "/TN", OLD_TASK_NEW, "/F"])
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, NAME)
    except OSError:
        pass
