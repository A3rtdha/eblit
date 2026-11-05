"""Hysteria2 subscription nodes and sing-box outbounds."""

from __future__ import annotations

import base64
import binascii
import math
import re
from urllib.parse import parse_qs, unquote, urlparse


_DURATION_RE = re.compile(r"(?:\d+(?:\.\d+)?(?:ns|us|ms|s|m|h))+")
_TLS_FIELDS = (
    "alpn", "min_version", "max_version", "certificate_sha256",
    "certificate_public_key_sha256", "insecure",
)


def _pins(raw) -> list[str]:
    values = [raw] if isinstance(raw, str) else raw
    if not isinstance(values, list) or not values:
        raise ValueError("нужен SHA-256 сертификата")
    for value in values:
        if not isinstance(value, str):
            raise ValueError("неверный SHA-256 сертификата")
        try:
            digest = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("неверный SHA-256 сертификата") from exc
        if len(digest) != 32:
            raise ValueError("неверный SHA-256 сертификата")
    return list(values)


def _tls_options(parsed: dict, host: str) -> dict:
    sni = parsed.get("sni")
    if sni is None or sni == "":
        sni = host
    if not isinstance(sni, str) or not sni.strip() or re.search(r"\s", sni.strip()) or len(sni.strip()) > 253:
        raise ValueError("неверное имя TLS-сервера Hysteria2")
    tls = {"enabled": True, "server_name": sni.strip()}
    for field in ("certificate_sha256", "certificate_public_key_sha256"):
        if field in parsed:
            tls[field] = _pins(parsed[field])
    if "insecure" in parsed:
        if not isinstance(parsed["insecure"], bool):
            raise ValueError("неверный параметр проверки TLS")
        tls["insecure"] = parsed["insecure"]
    if "alpn" in parsed:
        alpn = parsed["alpn"]
        if not isinstance(alpn, list) or any(not isinstance(item, str) or not item for item in alpn):
            raise ValueError("неверный ALPN Hysteria2")
        tls["alpn"] = list(alpn)
    for field in ("min_version", "max_version"):
        if field in parsed:
            if not isinstance(parsed[field], str) or parsed[field] not in {"1.2", "1.3"}:
                raise ValueError("неверная версия TLS")
            tls[field] = parsed[field]
    if tls.get("min_version", "1.2") > tls.get("max_version", "1.3"):
        raise ValueError("минимальная версия TLS выше максимальной")
    return tls


def to_outbound(parsed: dict) -> dict:
    host = parsed.get("host")
    if not isinstance(host, str):
        raise ValueError("нужен адрес Hysteria2")
    host = host.strip().strip("[]")
    port = parsed.get("port", 443)
    if isinstance(port, str) and re.fullmatch(r"[0-9]+", port):
        port = int(port)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("неверный порт Hysteria2")
    if not host or len(host) > 253 or re.search(r"\s", host):
        raise ValueError("нужен адрес Hysteria2")
    password = parsed.get("password")
    if not isinstance(password, str) or not password:
        raise ValueError("нужен пароль Hysteria2")
    tag = str(parsed.get("tag") or parsed.get("name") or host).strip() or host
    outbound = {
        "type": "hysteria2", "tag": tag, "server": host,
        "server_port": port, "password": password, "tls": _tls_options(parsed, host),
    }
    if "network" in parsed:
        if not isinstance(parsed["network"], str) or parsed["network"] not in {"tcp", "udp"}:
            raise ValueError("неверный тип трафика Hysteria2")
        outbound["network"] = parsed["network"]
    if "obfs" in parsed:
        obfs = parsed["obfs"]
        if (
            not isinstance(obfs, dict) or set(obfs) - {"type", "password"}
            or obfs.get("type") != "salamander"
            or not isinstance(obfs.get("password"), str) or not obfs["password"]
        ):
            raise ValueError("нужны тип salamander и пароль маскировки")
        outbound["obfs"] = {"type": "salamander", "password": obfs["password"]}
    for field in ("idle_timeout", "keep_alive_period"):
        if field in parsed:
            value = parsed[field]
            if not isinstance(value, str) or not _DURATION_RE.fullmatch(value):
                raise ValueError("неверный интервал Hysteria2")
            outbound[field] = value
    for field in ("up_mbps", "down_mbps"):
        if field in parsed:
            value = parsed[field]
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("неверная скорость Hysteria2")
            outbound[field] = value
    return outbound


def _validated_node(candidate: dict) -> dict | None:
    try:
        outbound = to_outbound(candidate)
    except ValueError:
        return None
    node = {
        "type": "hysteria2", "tag": outbound["tag"], "name": outbound["tag"],
        "host": outbound["server"], "port": outbound["server_port"],
        "password": outbound["password"], "sni": outbound["tls"]["server_name"],
    }
    for field in _TLS_FIELDS:
        if field in outbound["tls"]:
            node[field] = outbound["tls"][field]
    for field in ("network", "obfs", "idle_timeout", "keep_alive_period", "up_mbps", "down_mbps"):
        if field in outbound:
            node[field] = outbound[field]
    return node


def _hex_pin(raw) -> list[str]:
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        raise ValueError("неверный отпечаток сертификата Hysteria2")
    return [base64.b64encode(bytes.fromhex(raw)).decode("ascii")]


def _seconds(raw) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
        raise ValueError("неверный интервал Hysteria2")
    try:
        if not math.isfinite(raw):
            raise ValueError("неверный интервал Hysteria2")
        return f"{raw:g}s"
    except OverflowError as exc:
        raise ValueError("неверный интервал Hysteria2") from exc


def from_xray(ob: dict) -> dict | None:
    if str(ob.get("protocol") or "").lower() != "hysteria":
        return None
    settings = ob.get("settings")
    stream = ob.get("streamSettings") or ob.get("stream_settings")
    if not isinstance(settings, dict) or not isinstance(stream, dict):
        return None
    transport = stream.get("hysteriaSettings")
    tls = stream.get("tlsSettings")
    if (
        type(settings.get("version")) is not int or settings["version"] != 2
        or not isinstance(transport, dict) or type(transport.get("version")) is not int
        or transport["version"] != 2 or not isinstance(tls, dict)
        or not (stream.get("network") or stream.get("method"))
        or any(stream[field] != "hysteria" for field in ("network", "method") if field in stream)
        or stream.get("security") != "tls"
    ):
        return None
    if ob.get("proxySettings") or ob.get("sendThrough") or stream.get("sockopt"):
        return None
    if set(settings) - {"version", "address", "port"} or set(transport) - {"version", "auth"}:
        return None
    if set(tls) - {"serverName", "alpn", "minVersion", "maxVersion", "allowInsecure", "pinnedPeerCertSha256"}:
        return None
    if set(stream) - {"network", "method", "security", "tlsSettings", "hysteriaSettings", "finalmask", "sockopt"}:
        return None
    candidate = {
        "tag": ob.get("tag"), "host": settings.get("address"),
        "port": settings.get("port"), "password": transport.get("auth"),
        "sni": tls.get("serverName"),
    }
    for source, target in (
        ("alpn", "alpn"), ("minVersion", "min_version"),
        ("maxVersion", "max_version"), ("allowInsecure", "insecure"),
    ):
        if source in tls:
            candidate[target] = tls[source]
    try:
        if "pinnedPeerCertSha256" in tls:
            candidate["certificate_sha256"] = _hex_pin(tls["pinnedPeerCertSha256"])
        finalmask = stream.get("finalmask", {})
        if not isinstance(finalmask, dict) or finalmask.get("tcp"):
            return None
        if set(finalmask) - {"tcp", "udp", "quicParams"}:
            return None
        masks = finalmask.get("udp", [])
        if not isinstance(masks, list) or len(masks) > 1:
            return None
        if masks:
            mask = masks[0]
            if (
                not isinstance(mask, dict) or set(mask) - {"type", "settings"}
                or not isinstance(mask.get("settings"), dict) or set(mask["settings"]) - {"password"}
            ):
                return None
            candidate["obfs"] = {"type": mask.get("type"), "password": mask["settings"].get("password")}
        quic = finalmask.get("quicParams", {})
        if not isinstance(quic, dict) or quic.get("congestion", "bbr") != "bbr":
            return None
        if set(quic) - {"congestion", "keepAlivePeriod", "maxIdleTimeout"}:
            return None
        for source, target in (("keepAlivePeriod", "keep_alive_period"), ("maxIdleTimeout", "idle_timeout")):
            if source in quic:
                candidate[target] = _seconds(quic[source])
    except ValueError:
        return None
    return _validated_node(candidate)


def from_singbox(ob: dict) -> dict | None:
    if str(ob.get("type") or "").lower() != "hysteria2":
        return None
    tls = ob.get("tls")
    if not isinstance(tls, dict) or tls.get("enabled") is not True:
        return None
    # Paths and detours in a provider export cannot be reproduced as independent nodes.
    if ob.get("detour") or ob.get("server_ports") or ob.get("realm"):
        return None
    if set(ob) - {
        "type", "tag", "server", "server_port", "password", "tls", "network",
        "obfs", "idle_timeout", "keep_alive_period", "up_mbps", "down_mbps",
        "detour", "server_ports", "realm",
    }:
        return None
    if set(tls) - {"enabled", "server_name", *_TLS_FIELDS}:
        return None
    candidate = {
        "tag": ob.get("tag"), "host": ob.get("server"),
        "port": ob.get("server_port", 443), "password": ob.get("password"),
        "sni": tls.get("server_name"),
    }
    for field in _TLS_FIELDS:
        if field in tls:
            candidate[field] = tls[field]
    for field in ("network", "obfs", "idle_timeout", "keep_alive_period", "up_mbps", "down_mbps"):
        if field in ob:
            candidate[field] = ob[field]
    return _validated_node(candidate)


def parse_uri(uri: str) -> dict | None:
    try:
        parsed = urlparse(uri)
        if parsed.scheme.lower() not in {"hy2", "hysteria2"}:
            return None
        query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        if set(query) - {"sni", "insecure", "pinSHA256", "obfs", "obfs-password"}:
            return None
        password = unquote(parsed.username or "")
        if parsed.password is not None:
            password += ":" + unquote(parsed.password)
        candidate = {
            "tag": unquote(parsed.fragment), "host": parsed.hostname,
            "port": parsed.port if parsed.port is not None else 443,
            "password": password, "sni": query.get("sni"),
        }
        if "insecure" in query:
            value = query["insecure"].lower()
            if value not in {"0", "1", "false", "true"}:
                return None
            candidate["insecure"] = value in {"1", "true"}
        if "pinSHA256" in query:
            candidate["certificate_sha256"] = _hex_pin(query["pinSHA256"])
        if query.get("obfs") or query.get("obfs-password"):
            candidate["obfs"] = {"type": query.get("obfs"), "password": query.get("obfs-password")}
    except ValueError:
        return None
    return _validated_node(candidate)
