"""Pick the first VLESS geo that answers Reality. Do not scan the rest."""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from concurrent.futures import as_completed
from datetime import datetime
from pathlib import Path

import app.paths as paths
from app.log import echo
from app.paths import singbox
from app.stack import nodes
from app.stack.httpchk import live_exit, status_code
from app.stack.run import CREATE_NO_WINDOW

DIR = None  # tests may patch paths.root


def _dir() -> Path:
    return paths.data_root()


def _cfg() -> Path:
    return _dir() / "config.json"


def _ips() -> Path:
    return _dir() / "eblit-ips.json"


def _pick() -> Path:
    return _dir() / "eblit-pick.json"


def _fav() -> Path:
    return _dir() / "eblit-favorite.json"


def _log() -> Path:
    return _dir() / "health.log"

PROBE_URL = "https://grok.com/"
PROBE_PORT = 2099
SCAN_PORT = 2100
SCAN_WORKERS = 4
CURL_TIMEOUT = 8
RESOLVE_TIMEOUT = 2.0
SCAN_BUDGET = 40.0
_PROBE_LOCK = threading.Lock()
_PROCESSES: set[subprocess.Popen] = set()
_CANCELLED = threading.Event()


def resume_probes() -> None:
    _CANCELLED.clear()


def cancel_probes() -> None:
    with _PROBE_LOCK:
        _CANCELLED.set()
        processes = list(_PROCESSES)
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def log(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{stamp} {line}"
    try:
        with _log().open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    echo(text)


def resolve_one(host: str, timeout: float = RESOLVE_TIMEOUT) -> str | None:
    """Системный резолвер. Раньше был DoH к `dns.google` — серия таких запросов
    с домашнего IP при каждом старте выглядела для Google автоматикой и приводила
    к reCAPTCHA в браузере. Не возвращать сюда HTTP-резолверы."""
    box: list[str | None] = []

    def lookup() -> None:
        ips: list[str] = []
        try:
            for info in socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM):
                ip = info[4][0]
                if ip not in ips:
                    ips.append(ip)
            box.append(ips[0] if ips else None)
        except OSError:
            box.append(None)

    # getaddrinfo не умеет timeout; поток-демон доживёт DNS сам.
    worker = threading.Thread(target=lookup, name="eblit-dns", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive() or not box:
        return None
    return box[0]


def probe(
    tag: str,
    outbound: dict,
    ip: str,
    port: int = PROBE_PORT,
    probe_path: Path | None = None,
) -> tuple[bool, int, str]:
    ob = dict(outbound)
    ob["server"] = ip
    path = probe_path if probe_path is not None else _dir() / "_probe.json"
    cfg = {
        "log": {"level": "error"},
        "inbounds": [
            {"type": "mixed", "tag": "m", "listen": "127.0.0.1", "listen_port": port}
        ],
        "outbounds": [ob, {"type": "direct", "tag": "direct"}],
        "route": {"final": tag, "auto_detect_interface": True},
    }
    proc = None
    try:
        with _PROBE_LOCK:
            if _CANCELLED.is_set():
                raise OSError("проверка отменена")
            nodes._atomic_write(path, json.dumps(cfg))
            proc = subprocess.Popen(
                [str(singbox()), "run", "-c", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            _PROCESSES.add(proc)
        time.sleep(0.6)
        t0 = time.perf_counter()
        try:
            r = subprocess.run(
                [
                    "curl.exe",
                    "-4",
                    "--socks5-hostname",
                    f"127.0.0.1:{port}",
                    "-sI",
                    "--connect-timeout",
                    "5",
                    "--max-time",
                    "6",
                    PROBE_URL,
                ],
                capture_output=True,
                text=True,
                timeout=CURL_TIMEOUT,
                creationflags=CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            ms = int((time.perf_counter() - t0) * 1000)
            return False, ms, "timeout"
        ms = int((time.perf_counter() - t0) * 1000)
        if live_exit(r.stdout):
            return True, ms, status_code(r.stdout)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("HTTP/")), "")
        return False, ms, status_code(r.stdout) or line or "timeout"
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            with _PROBE_LOCK:
                _PROCESSES.discard(proc)
        path.unlink(missing_ok=True)


def last_pick() -> str | None:
    if _pick().is_file():
        try:
            data = json.loads(_pick().read_text(encoding="utf-8"))
            tag = data.get("tag") if isinstance(data, dict) else None
            if isinstance(tag, str) and tag in nodes.vless_tags():
                return tag
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return None


def favorite_tag() -> str | None:
    if not _fav().is_file():
        return None
    try:
        data = json.loads(_fav().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("tag")
    known = nodes.vless_tags()
    if isinstance(tag, str) and tag in known:
        return tag
    host = data.get("host")
    mapping = nodes.hosts()
    if isinstance(host, str):
        for t, h in mapping.items():
            if h == host and t in known:
                return t
    return None


def try_order(cfg: dict | None = None) -> list[str]:
    data = cfg if cfg is not None else nodes.read_config()
    tags = nodes.vless_tags(data)
    order: list[str] = []
    fav = favorite_tag()
    if fav in tags:
        order.append(fav)
    prev = last_pick()
    if prev in tags and prev not in order:
        order.append(prev)
    for tag in tags:
        if tag not in order:
            order.append(tag)
    return order


def _ip_for_tag(tag: str, outbound: dict, host_map: dict[str, str], pins: dict[str, str]) -> str | None:
    host = host_map.get(tag, "")
    if host:
        if host in pins:
            return pins[host]
        try:
            ip = resolve_one(host)
        except Exception as e:
            log(f"dns {host} {e}")
            ip = None
        if ip:
            pins[host] = ip
            return ip
    server = outbound.get("server")
    if isinstance(server, str) and server:
        return server
    return None


def last_result_line() -> str:
    if not _log().is_file():
        return ""
    found = ""
    for line in _log().read_text(encoding="utf-8", errors="replace").splitlines():
        if " RESULT " in line:
            found = line
    return found


def scan_all() -> dict:
    """Пинг всех vless. Не first-live и не пишет selector / eblit-pick."""
    cfg = nodes.read_config()
    by_tag = {
        ob.get("tag"): ob
        for ob in cfg.get("outbounds", [])
        if isinstance(ob, dict) and ob.get("type") == "vless" and ob.get("tag")
    }
    host_map = nodes.hosts()
    jobs = [(tag, SCAN_PORT + i) for i, tag in enumerate(by_tag)]
    rows: list[dict] = []

    def one(tag: str, port: int) -> dict:
        ip = _ip_for_tag(tag, by_tag[tag], host_map, {})
        if not ip:
            return {"tag": tag, "live": False, "ms": 0, "why": "нет IP"}
        path = _dir() / f"_probe_{port}.json"
        try:
            live, ms, why = probe(tag, by_tag[tag], ip, port=port, probe_path=path)
        except (OSError, ValueError) as exc:
            return {"tag": tag, "live": False, "ms": 0, "why": str(exc)}
        return {"tag": tag, "live": live, "ms": ms, "why": why}

    if jobs:
        workers = min(SCAN_WORKERS, len(jobs))
        pool = ThreadPoolExecutor(max_workers=workers)
        futs = {pool.submit(one, tag, port): tag for tag, port in jobs}
        pending = dict(futs)
        try:
            for fut in as_completed(futs, timeout=SCAN_BUDGET):
                rows.append(fut.result())
                pending.pop(fut, None)
        except FuturesTimeout:
            for fut, tag in pending.items():
                rows.append({"tag": tag, "live": False, "ms": 0, "why": "timeout"})
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    order = {tag: i for i, tag in enumerate(by_tag)}
    rows.sort(key=lambda n: order.get(n["tag"], 999))
    return {"ok": True, "nodes": rows}


def main() -> int:
    # Только свой файл: glob `_probe*.json` сносил `_probe_2100.json` у ping
    # и на Windows падал PermissionError, если scan держал файл.
    leftover = _dir() / "_probe.json"
    leftover.unlink(missing_ok=True)

    cfg = nodes.read_config()
    by_tag = {
        ob.get("tag"): ob
        for ob in cfg.get("outbounds", [])
        if isinstance(ob, dict) and ob.get("type") == "vless" and ob.get("tag")
    }
    if not by_tag:
        log("ERR no vless outbounds")
        return 1

    host_map = nodes.hosts()
    pins: dict[str, str] = {}
    log("health start (first live geo wins)")
    winner = None
    manual = nodes.manual_tag()
    deadline = time.monotonic() + SCAN_BUDGET
    if manual and manual in by_tag:
        ip = _ip_for_tag(manual, by_tag[manual], host_map, pins)
        if ip:
            ok, ms, detail = probe(manual, by_tag[manual], ip)
            log(f"{manual:12} {ip:15} {'OK' if ok else 'FAIL':4} {ms}ms {detail} (manual)")
            if ok:
                winner = (manual, ip)
            else:
                log(f"выбранный сервер {manual} не отвечает — берём первый живой")

    if not winner:
        for tag in try_order(cfg):
            if _CANCELLED.is_set() or time.monotonic() >= deadline:
                break
            if tag not in by_tag or tag == manual:
                continue
            ip = _ip_for_tag(tag, by_tag[tag], host_map, pins)
            if not ip:
                log(f"{tag:12} {'':15} SKIP no IP")
                continue
            ok, ms, detail = probe(tag, by_tag[tag], ip)
            log(f"{tag:12} {ip:15} {'OK' if ok else 'FAIL':4} {ms}ms {detail}")
            if ok:
                winner = (tag, ip)
                break

    with nodes.configuration.locked():
        current = nodes.read_config()
        if winner:
            original = by_tag[winner[0]]
            candidate = next((ob for ob in current["outbounds"] if ob.get("tag") == winner[0]), None)
            if candidate != original:
                log("RESULT server changed during probe; retry")
                return 1
        for ob in current["outbounds"]:
            original = by_tag.get(ob.get("tag"))
            if original and ob == original:
                host = host_map.get(ob["tag"], "")
                if host in pins:
                    ob["server"] = pins[host]
        nodes._atomic_write(_ips(), json.dumps(pins, indent=2) + "\n")
        if not winner:
            nodes.write_config(current)
            log("RESULT none — no live server")
            return 1
        tag, ip = winner
        if tag not in nodes.vless_tags(current) or nodes.manual_tag() != manual:
            log("RESULT selection changed during probe; retry")
            return 1
        nodes._set_selector(current, [tag])
        pick_payload = {"tag": tag, "ip": ip}
        if manual == tag:
            pick_payload["manual"] = True
        nodes.write_config(current)
        nodes._atomic_write(_pick(), json.dumps(pick_payload) + "\n")
    log(f"RESULT pick={tag}:{ip} (stopped, rest not probed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
