from __future__ import annotations

from pathlib import Path

WARP_MSI_URL = "https://downloads.cloudflareclient.com/v1/download/windows/ga"
WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
# Extended сохраняет XHTTP; сборка Eblit добавляет проверку полного сертификата.
SINGBOX_VERSION = "1.14.1-extended-2.7.2-eblit.1"
SINGBOX_SHA256 = "99755ba377ff7a4274762933b5327d8d674dfd63d9a3a91ce9bb59d83898ac04"


def msiexec_args(msi: Path) -> list[str]:
    return ["msiexec", "/i", str(msi), "/qn", "/norestart"]
