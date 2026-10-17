from __future__ import annotations

import ctypes
import hashlib
from contextlib import contextmanager
from ctypes import wintypes

from app.paths import data_root


@contextmanager
def application_instance(name: str | None = None):
    if name is None:
        identity = str(data_root().resolve()).casefold().encode("utf-8")
        name = "Local\\Eblit.UI." + hashlib.sha256(identity).hexdigest()[:16]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, True, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    primary = ctypes.get_last_error() != 183
    try:
        yield primary
    finally:
        if primary:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
