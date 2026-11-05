from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from app.setup.assets import SINGBOX_SHA256, SINGBOX_VERSION

UA = "eblit-setup"


def verify_singbox(path: Path) -> None:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != SINGBOX_SHA256:
        raise OSError(f"sing-box: контрольная сумма не совпадает с версией {SINGBOX_VERSION}")


def download(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
    if dest.stat().st_size <= 0:
        dest.unlink(missing_ok=True)
        raise OSError(f"пустая загрузка: {url}")
