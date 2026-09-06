from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from app.setup.assets import SINGBOX_API, pick_singbox_zip

UA = "eblit-setup"


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


def latest_singbox_zip() -> str:
    req = urllib.request.Request(SINGBOX_API, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OSError(f"github sing-box: {exc}") from exc
    url = pick_singbox_zip(data.get("assets") or [])
    if not url:
        raise OSError("в latest нет windows-amd64.zip")
    return url
