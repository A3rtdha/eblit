from __future__ import annotations

import sys
from datetime import datetime

from .paths import root

LOG = root() / "split-ui.log"


def echo(text: str) -> None:
    """Консоль на Windows cp1251/cp1252 не должна ронять стек из‑за кириллицы или ⚡."""
    out = getattr(sys, "stdout", None)
    if out is None:
        return
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(out, "encoding", None) or "ascii"
        safe = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        try:
            print(safe, flush=True)
        except (UnicodeEncodeError, OSError):
            return
    except OSError:
        return


def write(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{stamp} {line}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{text}\n")
    echo(text)
