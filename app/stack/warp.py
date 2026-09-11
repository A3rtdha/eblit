from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from app.log import write
from app.stack.httpchk import has_http
from app.stack.run import hidden

SOCKS = "127.0.0.1:40000"
SPOTIFY = "https://open.spotify.com"
WAIT_TRIES = 30
_SERVICES = ("CloudflareWARP", "warp-svc")
GUI_NAME = "Cloudflare WARP.exe"


def _program_files_cli() -> Path:
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    return base / "Cloudflare" / "Cloudflare WARP" / "warp-cli.exe"


def cli_path() -> str:
    pf = _program_files_cli()
    if pf.is_file():
        return str(pf)
    return "warp-cli"


def gui_path() -> Path:
    return _program_files_cli().parent / GUI_NAME


def open_gui() -> bool:
    """Окно в сессии пользователя. Не hidden: иначе GUI не видно."""
    exe = gui_path()
    if not exe.is_file():
        return False
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
    except OSError:
        return False
    return True


def _run(*args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    cmd = [cli_path(), *args]
    try:
        return hidden(cmd, timeout=timeout)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", "warp-cli не найден")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def _out(r: subprocess.CompletedProcess[str]) -> str:
    return f"{r.stdout or ''}{r.stderr or ''}"


def _ok(*args: str, timeout: float = 30) -> bool:
    r = _run(*args, timeout=timeout)
    if r.returncode == 0:
        return True
    text = _out(r).strip()
    if text:
        write(f"warp-cli {' '.join(args)}: {text[:200]}")
    return False


def _first(*variants: tuple[str, ...], timeout: float = 30) -> bool:
    for args in variants:
        if _ok(*args, timeout=timeout):
            return True
    return False


def daemon_ready() -> bool:
    r = _run("status", timeout=15)
    text = _out(r).lower()
    if "unable to connect to cloudflarewarp daemon" in text:
        return False
    if r.returncode == 127:
        return False
    if r.returncode == 0:
        return True
    return "status" in text


def wait_daemon(tries: int = 30) -> bool:
    for _ in range(tries):
        for name in _SERVICES:
            try:
                hidden(["sc", "start", name], timeout=15)
            except (OSError, subprocess.SubprocessError):
                pass
        if daemon_ready():
            return True
        time.sleep(2)
    return daemon_ready()


def configure() -> None:
    # Смена mode, пока туннель жив, у WARP часто no-op / error — SOCKS так и не слушает :40000.
    _ok("disconnect")
    _first(("tunnel", "protocol", "set", "MASQUE"), ("set-tunnel-protocol", "MASQUE"))
    _first(("mode", "proxy"), ("set-mode", "proxy"))
    _first(("proxy", "port", "40000"), ("set-proxy-port", "40000"))


def configure_and_connect() -> None:
    ensure_registration()
    configure()
    _ok("connect")


def registered() -> bool:
    r = _run("registration", "show", timeout=15)
    text = _out(r).lower()
    if "missing" in text or "not registered" in text:
        return False
    return r.returncode == 0


def ensure_registration() -> bool:
    if registered():
        return True
    _ok("registration", "accept-tos")
    if _ok("--accept-tos", "registration", "new", timeout=60) or registered():
        return True
    if _ok("registration", "new", timeout=60) or registered():
        return True
    if _ok("--accept-tos", "register", timeout=60) or registered():
        return True
    return _ok("register", timeout=60) or registered()


def disconnect() -> None:
    _ok("disconnect")


def reset_mode() -> None:
    """Снятие Eblit не должно оставлять чужой WARP в режиме proxy :40000."""
    _ok("disconnect")
    _first(("mode", "warp"), ("set-mode", "warp"))


def socks_ok() -> bool:
    r = hidden(
        [
            "curl.exe",
            "-4",
            "--socks5-hostname",
            SOCKS,
            "-sI",
            "--connect-timeout",
            "3",
            SPOTIFY,
        ],
        timeout=8,
    )
    return has_http(r.stdout)


def wait_ready(tries: int = WAIT_TRIES) -> bool:
    for _ in range(max(1, int(tries))):
        if socks_ok():
            return True
        time.sleep(2)
    return False
