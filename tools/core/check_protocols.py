"""Exercise XHTTP and pinned Hysteria2 traffic through isolated loopback cores."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


LOOPBACK = "127.0.0.1"
TEST_UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def free_port(socket_type: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, socket_type) as listener:
        listener.bind((LOOPBACK, 0))
        return listener.getsockname()[1]


def make_certificate(binary: Path) -> tuple[str, str, str]:
    result = subprocess.run(
        [str(binary), "generate", "tls-keypair", "localhost"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    certificate = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", result.stdout, re.S)
    key = re.search(r"-----BEGIN PRIVATE KEY-----.*?-----END PRIVATE KEY-----", result.stdout, re.S)
    if certificate is None or key is None:
        raise RuntimeError("core did not generate the expected TLS key pair")
    certificate_pem = certificate.group(0)
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate_pem)).digest()
    return certificate_pem, key.group(0), base64.b64encode(digest).decode("ascii")


@contextmanager
def http_origin(marker: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(marker)))
            self.end_headers()
            self.wfile.write(marker)

        def log_message(self, *_args):
            pass

    server = HTTPServer((LOOPBACK, 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def wait_listener(process: subprocess.Popen, port: int, log_path: Path) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("core exited during startup: " + log_path.read_text(encoding="utf-8")[-1500:])
        try:
            with socket.create_connection((LOOPBACK, port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("core did not open its loopback listener")


def wait_log_message(process: subprocess.Popen, log_path: Path, message: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        output = log_path.read_text(encoding="utf-8", errors="replace")
        if message in output:
            return
        if process.poll() is not None:
            raise RuntimeError("core exited during startup: " + output[-1500:])
        time.sleep(0.05)
    raise RuntimeError("core did not confirm its UDP loopback listener")


@contextmanager
def running_core(binary: Path, directory: Path, name: str, config: dict, tcp_port: int | None = None, *, ready_log: str | None = None):
    config_path = directory / f"{name}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    log_path = directory / f"{name}.log"
    with log_path.open("wb") as output:
        process = subprocess.Popen(
            [str(binary), "run", "-c", str(config_path)], cwd=directory,
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            if tcp_port is not None:
                wait_listener(process, tcp_port, log_path)
            elif ready_log is not None:
                wait_log_message(process, log_path, ready_log)
            yield log_path
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def receive_exact(stream: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise OSError("proxy closed the connection")
        data.extend(chunk)
    return bytes(data)


def fetch_through_socks(proxy_port: int, origin_port: int) -> bytes:
    with socket.create_connection((LOOPBACK, proxy_port), timeout=8) as stream:
        stream.sendall(b"\x05\x01\x00")
        if receive_exact(stream, 2) != b"\x05\x00":
            raise OSError("SOCKS5 authentication negotiation failed")
        stream.sendall(b"\x05\x01\x00\x01" + socket.inet_aton(LOOPBACK) + struct.pack("!H", origin_port))
        reply = receive_exact(stream, 4)
        if reply[:2] != b"\x05\x00":
            raise OSError("SOCKS5 connect was rejected")
        address_length = {1: 4, 4: 16}.get(reply[3])
        if reply[3] == 3:
            address_length = receive_exact(stream, 1)[0]
        if address_length is None:
            raise OSError("SOCKS5 returned an invalid address type")
        receive_exact(stream, address_length + 2)
        stream.sendall(b"GET /core-check HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        response = bytearray()
        while len(response) <= 65536:
            chunk = stream.recv(4096)
            if not chunk:
                return bytes(response)
            response.extend(chunk)
        raise OSError("unexpectedly large loopback response")


def configurations(protocol: str, certificate: str, key: str, pin: str, server_port: int, proxy_port: int):
    tls_server = {"enabled": True, "certificate": [certificate], "key": [key]}
    tls_client = {"enabled": True, "server_name": "localhost"}
    inbound = {"type": protocol, "tag": "server", "listen": LOOPBACK, "listen_port": server_port, "tls": tls_server}
    outbound = {"type": protocol, "tag": "proxy", "server": LOOPBACK, "server_port": server_port, "tls": tls_client}
    if protocol == "vless":
        transport = {"type": "xhttp", "path": "/core-check", "host": "localhost", "mode": "auto", "x_padding_bytes": {"from": 100, "to": 1000}}
        inbound.update(users=[{"uuid": TEST_UUID}], transport=transport)
        outbound.update(uuid=TEST_UUID, transport=copy.deepcopy(transport))
        tls_server["alpn"] = ["h2", "http/1.1"]
        tls_client.update(certificate=[certificate], alpn=["h2"])
    else:
        obfs = {"type": "salamander", "password": "loopback-mask-password"}
        inbound.update(users=[{"name": "test", "password": "loopback-auth-password"}], obfs=obfs)
        outbound.update(password="loopback-auth-password", obfs=copy.deepcopy(obfs))
        tls_server["alpn"] = ["h3"]
        tls_client.update(certificate_sha256=[pin], alpn=["h3"])
    server = {"log": {"level": "error"}, "inbounds": [inbound], "outbounds": [{"type": "direct", "tag": "direct"}], "route": {"final": "direct"}}
    client = {"log": {"level": "error"}, "inbounds": [{"type": "socks", "listen": LOOPBACK, "listen_port": proxy_port}], "outbounds": [outbound], "route": {"final": "proxy"}}
    if protocol == "hysteria2":
        server["log"]["level"] = "info"
    return server, client


def check_protocol(binary: Path, directory: Path, protocol: str, origin_port: int, marker: bytes, certificate: str, key: str, pin: str) -> None:
    socket_type = socket.SOCK_DGRAM if protocol == "hysteria2" else socket.SOCK_STREAM
    server_port, proxy_port = free_port(socket_type), free_port()
    while proxy_port == server_port:
        proxy_port = free_port()
    server, client = configurations(protocol, certificate, key, pin, server_port, proxy_port)
    ready_log = f"udp server started at {LOOPBACK}:{server_port}" if protocol == "hysteria2" else None
    with running_core(binary, directory, f"{protocol}-server", server, server_port if protocol == "vless" else None, ready_log=ready_log):
        with running_core(binary, directory, f"{protocol}-client", client, proxy_port):
            response = fetch_through_socks(proxy_port, origin_port)
            header, _, body = response.partition(b"\r\n\r\n")
            if not header.startswith(b"HTTP/1.0 200") or body != marker:
                raise RuntimeError(f"{protocol} did not carry the expected loopback response")
        if protocol == "hysteria2":
            client["outbounds"][0]["tls"]["certificate_sha256"] = [base64.b64encode(bytes(32)).decode("ascii")]
            with running_core(binary, directory, "hysteria2-wrong-pin", client, proxy_port) as log_path:
                try:
                    fetch_through_socks(proxy_port, origin_port)
                except OSError:
                    pass
                else:
                    raise RuntimeError("Hysteria2 accepted the wrong certificate pin")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if "unrecognized remote certificate" in log_path.read_text(encoding="utf-8", errors="replace"):
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Hysteria2 failure did not confirm certificate pin rejection")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--protocol", choices=("all", "xhttp", "hysteria2"), default="all")
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    certificate, key, pin = make_certificate(binary)
    marker = secrets.token_hex(24).encode("ascii")
    protocols = ("vless", "hysteria2") if args.protocol == "all" else ("vless" if args.protocol == "xhttp" else "hysteria2",)
    with tempfile.TemporaryDirectory(prefix="eblit-core-protocols-") as temporary, http_origin(marker) as origin_port:
        for protocol in protocols:
            check_protocol(binary, Path(temporary), protocol, origin_port, marker, certificate, key, pin)
            print("XHTTP traffic: OK" if protocol == "vless" else "Hysteria2 + Salamander traffic and wrong-pin rejection: OK", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"protocol check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
