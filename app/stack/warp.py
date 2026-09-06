from __future__ import annotations

import os
import time
from pathlib import Path

from app.stack.httpchk import has_http
from app.stack.run import hidden

SOCKS = "127.0.0.1:40000"
SPOTIFY = "https://open.spotify.com"
WAIT_TRIES = 30


def _program_files_cli() -> Path:
    base = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    return base / "Cloudflare" / "Cloudflare WARP" / "warp-cli.exe"


def cli_path() -> str:
    pf = _program_files_cli()
    if pf.is_file():
        return str(pf)
    return "warp-cli"


def _cli(*args: str) -> None:
    hidden([cli_path(), *args])


def configure() -> None:
    _cli("tunnel", "protocol", "set", "MASQUE")
    _cli("mode", "proxy")
    _cli("proxy", "port", "40000")


def configure_and_connect() -> None:
    configure()
    _cli("connect")


def registered() -> bool:
    r = hidden([cli_path(), "registration", "show"], timeout=15)
    return r.returncode == 0


def ensure_registration() -> bool:
    if registered():
        return True
    r = hidden([cli_path(), "--accept-tos", "registration", "new"], timeout=60)
    return r.returncode == 0 or registered()


def disconnect() -> None:
    _cli("disconnect")


def reset_mode() -> None:
    """Снятие Eblit не должно оставлять чужой WARP в режиме proxy :40000."""
    _cli("mode", "warp")


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


def wait_ready() -> bool:
    for _ in range(WAIT_TRIES):
        if socks_ok():
            return True
        time.sleep(2)
    return False
