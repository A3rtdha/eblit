from __future__ import annotations

from datetime import datetime

from .paths import root

LOG = root() / "split-ui.log"


def write(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} {line}\n")
