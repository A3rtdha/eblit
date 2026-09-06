from __future__ import annotations

import time

from app.paths import root, singbox
from app.stack.httpchk import has_http
from app.stack.run import hidden, kill_image, spawn

TUN_TRIES = 20
SPOTIFY = "https://open.spotify.com"


def kill() -> None:
    kill_image("sing-box.exe")


def wait_gone(tries: int = 10) -> bool:
    """taskkill без админа тихо получает «отказано в доступе» — проверяем, что процесса нет."""
    for _ in range(tries):
        if not running():
            return True
        time.sleep(0.3)
    return False


def running() -> bool:
    r = hidden(["tasklist", "/FI", "IMAGENAME eq sing-box.exe", "/NH"], timeout=8)
    text = (r.stdout or "") + (r.stderr or "")
    return "sing-box.exe" in text.lower()


def adapter() -> bool:
    r = hidden(["ipconfig"], timeout=8)
    return "tun-fastly" in (r.stdout or "").lower()


def check() -> tuple[bool, str]:
    cfg = root() / "config.json"
    r = hidden([str(singbox()), "check", "-c", str(cfg)], timeout=20)
    if r.returncode == 0:
        return True, ""
    err = (r.stderr or r.stdout or "bad config").strip()
    return False, err.splitlines()[0] if err else "bad config"


def start() -> None:
    cfg = root() / "config.json"
    log = (root() / "sing-box.log").open("a", encoding="utf-8")
    spawn([str(singbox()), "run", "-c", str(cfg)], cwd=str(root()), log=log)


def tun_http() -> bool:
    r = hidden(
        [
            "curl.exe",
            "-4",
            "-sI",
            "--connect-timeout",
            "3",
            "--max-time",
            "5",
            SPOTIFY,
        ],
        timeout=8,
    )
    return has_http(r.stdout)


def wait_tun() -> bool:
    for _ in range(TUN_TRIES):
        if tun_http():
            return True
        time.sleep(2)
    return False
