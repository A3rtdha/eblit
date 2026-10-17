from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import psutil

from app.paths import data_root, root, singbox
from app.stack.httpchk import has_http
from app.stack.run import hidden, spawn

TUN_TRIES = 20
SPOTIFY = "https://open.spotify.com"


def _processes(executable: Path | None = None) -> list[psutil.Process]:
    executable = executable if executable is not None else singbox()
    if not executable.is_absolute():
        found = shutil.which(str(executable))
        if found is None:
            return []
        executable = Path(found)
    expected = os.path.normcase(str(executable.resolve()))
    configs = {(data_root() / "config.json").resolve(), (executable.parent / "config.json").resolve()}
    owned = []
    for process in psutil.process_iter(["name"]):
        if str(process.info["name"]).lower() not in {"sing-box.exe", "sing-box"}:
            continue
        try:
            if os.path.normcase(process.exe()) != expected:
                continue
            try:
                args = process.cmdline()
            except psutil.AccessDenied:
                owned.append(process)
                continue
            if "run" not in args or "-c" not in args:
                continue
            index = args.index("-c") + 1
            if index >= len(args):
                continue
            config = Path(args[index])
            if not config.is_absolute():
                config = Path(process.cwd()) / config
            if config.resolve() in configs:
                owned.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise PermissionError("не удалось проверить процесс sing-box") from exc
    return owned


def kill(*, executable: Path | None = None) -> None:
    for process in _processes(executable):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise PermissionError("нужны права администратора для остановки sing-box") from exc


def wait_gone(tries: int = 10, *, executable: Path | None = None) -> bool:
    """taskkill без админа тихо получает «отказано в доступе» — проверяем, что процесса нет."""
    for _ in range(tries):
        if not running(executable=executable):
            return True
        time.sleep(0.3)
    return False


def running(*, executable: Path | None = None) -> bool:
    return bool(_processes(executable))


def adapter() -> bool:
    r = hidden(["ipconfig"], timeout=8)
    return "tun-fastly" in (r.stdout or "").lower()


def check() -> tuple[bool, str]:
    cfg = data_root() / "config.json"
    r = hidden([str(singbox()), "check", "-c", str(cfg)], timeout=20)
    if r.returncode == 0:
        return True, ""
    err = (r.stderr or r.stdout or "bad config").strip()
    return False, err.splitlines()[0] if err else "bad config"


def start() -> None:
    cfg = data_root() / "config.json"
    with (data_root() / "sing-box.log").open("a", encoding="utf-8") as log:
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
    deadline = time.monotonic() + 30
    for _ in range(TUN_TRIES):
        if not running():
            return False
        if adapter() and tun_http():
            return True
        if time.monotonic() >= deadline:
            break
        time.sleep(0.3)
    return False
