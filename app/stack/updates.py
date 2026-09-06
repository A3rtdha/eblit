"""Проверка и скачивание релиза с GitHub. Без токена — лимит API терпим: жмём руками."""

from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from app.version import REPO, VERSION

UA = "Eblit"
SETUP_NAME = "EblitSetup.exe"
# Меньше этого — скорее HTML-ошибка GitHub, не установщик.
MIN_SETUP = 1_000_000


def parse_tag(tag: str) -> tuple[int, int, int]:
    raw = str(tag or "").strip()
    if raw.lower().startswith("v"):
        raw = raw[1:]
    bits = re.split(r"[.\-+]", raw)
    nums = []
    for bit in bits[:3]:
        nums.append(int(bit) if bit.isdigit() else 0)
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def is_newer(remote: str, local: str) -> bool:
    return parse_tag(remote) > parse_tag(local)


def _request(url: str, *, accept: str, timeout: int) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def check() -> dict:
    url = f"https://api.github.com/repos/{REPO}/releases/latest"
    try:
        raw = _request(url, accept="application/vnd.github+json", timeout=12)
        data = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "ok": True,
                "current": VERSION,
                "latest": VERSION,
                "newer": False,
                "asset": "",
                "why": "релизов ещё нет",
            }
        return {
            "ok": False,
            "current": VERSION,
            "latest": "",
            "newer": False,
            "asset": "",
            "why": f"github {exc.code}",
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "current": VERSION,
            "latest": "",
            "newer": False,
            "asset": "",
            "why": str(exc),
        }

    if not isinstance(data, dict):
        return {
            "ok": False,
            "current": VERSION,
            "latest": "",
            "newer": False,
            "asset": "",
            "why": "непонятный ответ github",
        }

    tag = str(data.get("tag_name") or "")
    latest = tag[1:] if tag.lower().startswith("v") else tag
    asset = ""
    for item in data.get("assets") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").lower() == SETUP_NAME.lower():
            asset = str(item.get("browser_download_url") or "")
            break

    newer = bool(latest) and is_newer(latest, VERSION)
    why = ""
    if newer and not asset:
        why = f"{latest} есть, но установщика в релизе нет"
    return {
        "ok": True,
        "current": VERSION,
        "latest": latest or VERSION,
        "newer": newer,
        "asset": asset,
        "html": str(data.get("html_url") or ""),
        "why": why,
    }


def download(asset_url: str) -> Path:
    if not asset_url or not asset_url.startswith("https://"):
        raise ValueError("нет ссылки на установщик")
    dest = Path(tempfile.gettempdir()) / SETUP_NAME
    blob = _request(asset_url, accept="application/octet-stream", timeout=180)
    if len(blob) < MIN_SETUP:
        raise ValueError("скачался не установщик")
    dest.write_bytes(blob)
    return dest


def launch(path: Path) -> None:
    os.startfile(str(path))  # type: ignore[attr-defined]
