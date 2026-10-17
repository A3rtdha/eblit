from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from app.log import write
from app.paths import data_root
from app.stack.httpchk import has_http
from app.stack.run import hidden
from app.storage import atomic_write

SOCKS = "127.0.0.1:40000"
SPOTIFY = "https://open.spotify.com"
CONTROL_URL = "https://cp.cloudflare.com/generate_204"
WAIT_TRIES = 30
_SERVICES = ("CloudflareWARP", "warp-svc")
GUI_NAME = "Cloudflare WARP.exe"
_PROBE_LOCK = threading.Lock()


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
    if not _ok("disconnect"):
        raise OSError("WARP: не удалось отключить прежнее соединение")
    _first(("tunnel", "protocol", "set", "MASQUE"), ("set-tunnel-protocol", "MASQUE"))
    if not _first(("mode", "proxy"), ("set-mode", "proxy")):
        raise OSError("WARP: не удалось включить режим прокси")
    if not _first(("proxy", "port", "40000"), ("set-proxy-port", "40000")):
        raise OSError("WARP: не удалось настроить порт прокси")


def configure_and_connect() -> None:
    atomic_write(data_root() / "eblit-warp.json", "{}\n")
    if not ensure_registration():
        raise OSError("WARP: регистрация не прошла")
    configure()
    if not _ok("connect"):
        raise OSError("WARP: подключение не прошло")


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


def owned() -> bool:
    return (data_root() / "eblit-warp.json").is_file()


def disconnect() -> bool:
    if not _ok("disconnect"):
        return False
    (data_root() / "eblit-warp.json").unlink(missing_ok=True)
    return True


def reset_mode() -> None:
    """Снятие Eblit не должно оставлять чужой WARP в режиме proxy :40000."""
    _ok("disconnect")
    _first(("mode", "warp"), ("set-mode", "warp"))


def _socks_error() -> str | None:
    try:
        connection = socket.create_connection(("127.0.0.1", 40000), timeout=2)
    except OSError:
        return "Нет TCP-соединения с WARP :40000"
    with connection:
        try:
            connection.sendall(b"\x05\x01\x00")
            greeting = b""
            while len(greeting) < 2:
                chunk = connection.recv(2 - len(greeting))
                if not chunk:
                    break
                greeting += chunk
        except OSError:
            return "TCP :40000 открыт, но SOCKS5 не отвечает"
    if greeting != b"\x05\x00":
        return "Порт :40000 не подтвердил SOCKS5 без авторизации"
    return None


def _https_probe(url: str) -> tuple[bool, str]:
    try:
        result = hidden(
            [
                "curl.exe", "-q", "-4", "--socks5-hostname", SOCKS,
                "--noproxy", "", "-sSI", "--connect-timeout", "3", "--max-time", "7", url,
            ],
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        return False, "таймаут HTTPS"
    if result.returncode == 0 and has_http(result.stdout):
        return True, ""
    if result.returncode == 28:
        return False, "таймаут HTTPS"
    if result.returncode in (35, 60):
        return False, "ошибка TLS"
    if result.returncode == 97:
        return False, "SOCKS5 не подключился к сайту"
    return False, f"HTTPS не ответил (curl {result.returncode})"


def proxy_probe() -> dict:
    with _PROBE_LOCK:
        error = _socks_error()
        if error:
            return {"ok": False, "ready": False, "why": error}
        spotify_ok, spotify_error = _https_probe(SPOTIFY)
        if spotify_ok:
            return {"ok": True, "ready": True, "why": "WARP :40000: SOCKS5 и HTTPS отвечают"}
        control_ok, control_error = _https_probe(CONTROL_URL)
        if control_ok:
            return {"ok": True, "ready": True, "why": f"WARP работает; Spotify: {spotify_error}; контрольный сайт доступен"}
        return {
            "ok": False,
            "ready": True,
            "why": f"SOCKS5 :40000 отвечает; Spotify: {spotify_error}; Cloudflare: {control_error}",
        }


def socks_ok() -> bool:
    return bool(proxy_probe()["ok"])


def wait_ready(tries: int = WAIT_TRIES) -> bool:
    deadline = time.monotonic() + 45
    for _ in range(max(1, int(tries))):
        if socks_ok():
            return True
        if time.monotonic() >= deadline:
            break
        time.sleep(2)
    return False
