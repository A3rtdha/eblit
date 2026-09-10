from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

CREATE_NO_WINDOW = 0x08000000


def hidden(
    args: Sequence[str],
    *,
    timeout: float | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=cwd,
        **({"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}),
    )


def spawn(args: Sequence[str], *, cwd: str | None = None, log) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        list(args),
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        creationflags=CREATE_NO_WINDOW,
    )


def kill_image(name: str) -> None:
    hidden(["taskkill", "/IM", name, "/F"])


def image_running(name: str) -> bool:
    r = hidden(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"], timeout=8)
    return name.lower() in ((r.stdout or "") + (r.stderr or "")).lower()
