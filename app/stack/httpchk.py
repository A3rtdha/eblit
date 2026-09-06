"""Parse curl -sI stdout: any HTTP/ line vs 2xx/3xx for probes."""

from __future__ import annotations


def http_line(stdout: str) -> str:
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.upper().startswith("HTTP/"):
            return line
    return ""


def has_http(stdout: str) -> bool:
    return bool(http_line(stdout))


def status_code(stdout: str) -> str:
    line = http_line(stdout)
    parts = line.split()
    return parts[1] if len(parts) > 1 else ""


def live_exit(stdout: str) -> bool:
    code = status_code(stdout)
    return code.startswith(("2", "3"))
