from __future__ import annotations

from app.stack.run import hidden


def disable() -> tuple[bool, str]:
    r = hidden(["netsh", "interface", "teredo", "set", "state", "disabled"], timeout=15)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "netsh failed").strip()
        return False, err.splitlines()[0] if err else "netsh failed"
    return True, "teredo off"
