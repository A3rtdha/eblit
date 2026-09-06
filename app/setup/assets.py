from __future__ import annotations

from pathlib import Path

WARP_MSI_URL = "https://downloads.cloudflareclient.com/v1/download/windows/ga"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
SINGBOX_API = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"


def pick_singbox_zip(assets: list) -> str | None:
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        url = item.get("browser_download_url")
        if "windows-amd64.zip" in name and url:
            return str(url)
    return None


def msiexec_args(msi: Path) -> list[str]:
    return ["msiexec", "/i", str(msi), "/qn", "/norestart"]
