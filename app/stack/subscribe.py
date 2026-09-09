"""Одна HTTPS-подписка: fetch + мягкий разбор + синк только своих тегов."""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urlparse

import app.paths as paths
from app.stack import nodes

SUB_FILE = "lagom-sub.json"
UA_HAPP = "Happ/1.0"
UA_V2RAYN = "v2rayN/1.8.23"
MAX_BODY = 2_000_000
_LOCK = threading.Lock()


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """Токен в URL. Редирект на http — утечка."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not str(newurl).lower().startswith("https://"):
            raise urllib.error.URLError("редирект не на https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirect)

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
VLESS_RE = re.compile(r"vless://[^\s<>\"']+", re.I)
OTHER_RE = re.compile(r"(?:vmess|trojan|ss|hy2|hysteria2)://", re.I)
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _path():
    return paths.root() / SUB_FILE


def _write_pref(url: str, tags: list[str]) -> None:
    path = _path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"url": url, "tags": list(tags)}) + "\n", encoding="utf-8")
    tmp.replace(path)


def get() -> dict:
    path = _path()
    if not path.is_file():
        return {"ok": True, "url": "", "tags": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"ok": False, "url": "", "tags": [], "why": "битый lagom-sub.json"}
    if not isinstance(data, dict):
        return {"ok": False, "url": "", "tags": [], "why": "битый lagom-sub.json"}
    url = data.get("url")
    url = url.strip() if isinstance(url, str) else ""
    tags: list[str] = []
    raw = data.get("tags")
    if isinstance(raw, list):
        tags = [t for t in raw if isinstance(t, str) and t]
    return {"ok": True, "url": url, "tags": tags}


def set_url(url) -> dict:
    raw = str(url or "").strip()
    current = get()
    tags = list(current.get("tags") or [])
    if raw and not raw.lower().startswith("https://"):
        return {
            "ok": False,
            "url": current.get("url") or "",
            "tags": tags,
            "why": "нужен https://",
        }
    _write_pref(raw, tags)
    return {"ok": True, "url": raw, "tags": tags}


def _clean_host(host) -> str:
    return str(host or "").strip().strip("[]")


def _node_from_parts(
    *,
    uuid,
    host,
    port,
    sni,
    public_key,
    fingerprint="firefox",
    flow="",
    net="tcp",
    tag="",
    short_id="",
) -> dict | None:
    uuid = str(uuid or "").strip()
    host = _clean_host(host)
    try:
        port = int(port or 443)
    except (TypeError, ValueError):
        return None
    sni = str(sni or "").strip()
    public_key = str(public_key or "").strip()
    net = str(net or "tcp").lower()
    if not UUID_RE.fullmatch(uuid):
        return None
    if not host or re.search(r"\s", host) or len(host) > 253:
        return None
    if port < 1 or port > 65535:
        return None
    if not sni or not public_key:
        return None
    if net and net != "tcp":
        return None
    name = str(tag or host).strip() or host
    fp = str(fingerprint or "firefox").strip() or "firefox"
    return {
        "tag": name,
        "name": name,
        "host": host,
        "port": port,
        "uuid": uuid,
        "packet_encoding": "xudp",
        "sni": sni,
        "fingerprint": fp,
        "public_key": public_key,
        "flow": str(flow or "").strip(),
        "short_id": str(short_id or "").strip(),
    }


def _parse_vless_uri(uri: str) -> dict | None:
    raw = str(uri or "").strip().rstrip("),.;")
    if not raw.lower().startswith("vless://"):
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() != "vless":
        return None
    q = {k: (v[-1] if v else "") for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    security = (q.get("security") or "").lower()
    pbk = q.get("pbk") or q.get("publicKey") or ""
    if security and security != "reality":
        return None
    if not security and not pbk:
        return None
    port = parsed.port or 443
    name = unquote(parsed.fragment) if parsed.fragment else ""
    user = unquote(parsed.username or "")
    return _node_from_parts(
        uuid=user,
        host=parsed.hostname or "",
        port=port,
        sni=q.get("sni") or q.get("peer") or "",
        public_key=pbk,
        fingerprint=q.get("fp") or q.get("fingerprint") or "firefox",
        flow=q.get("flow") or "",
        net=q.get("type") or q.get("net") or "tcp",
        tag=name,
        short_id=q.get("sid") or q.get("shortId") or "",
    )


def _from_singbox(ob: dict) -> dict | None:
    if str(ob.get("type") or "").lower() != "vless":
        return None
    tls = ob.get("tls") if isinstance(ob.get("tls"), dict) else {}
    reality = tls.get("reality") if isinstance(tls.get("reality"), dict) else {}
    utls = tls.get("utls") if isinstance(tls.get("utls"), dict) else {}
    return _node_from_parts(
        uuid=ob.get("uuid"),
        host=ob.get("server"),
        port=ob.get("server_port") or ob.get("serverPort") or 443,
        sni=tls.get("server_name") or tls.get("serverName") or "",
        public_key=reality.get("public_key") or reality.get("publicKey") or "",
        fingerprint=utls.get("fingerprint") or "firefox",
        flow=ob.get("flow") or "",
        net="tcp",
        tag=ob.get("tag") or "",
        short_id=reality.get("short_id") or reality.get("shortId") or "",
    )


def _from_clash(proxy: dict) -> dict | None:
    if str(proxy.get("type") or "").lower() != "vless":
        return None
    ro = proxy.get("reality-opts") or proxy.get("reality_opts") or proxy.get("realityOpts") or {}
    if not isinstance(ro, dict):
        ro = {}
    return _node_from_parts(
        uuid=proxy.get("uuid"),
        host=proxy.get("server"),
        port=proxy.get("port") or 443,
        sni=proxy.get("servername") or proxy.get("server_name") or proxy.get("sni") or "",
        public_key=ro.get("public-key") or ro.get("public_key") or ro.get("publicKey") or "",
        fingerprint=proxy.get("client-fingerprint")
        or proxy.get("client_fingerprint")
        or proxy.get("fp")
        or "firefox",
        flow=proxy.get("flow") or "",
        net=proxy.get("network") or proxy.get("net") or "tcp",
        tag=proxy.get("name") or "",
        short_id=ro.get("short-id") or ro.get("short_id") or "",
    )


def _profile_title(obj: dict) -> str:
    for key in ("remarks", "ps", "name"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    meta = obj.get("meta")
    if isinstance(meta, dict):
        for key in ("title", "name", "remarks"):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _is_xray_profile(obj) -> bool:
    """Полный Happ/Xray-конфиг, не sing-box и не плоский outbound."""
    if not isinstance(obj, dict):
        return False
    obs = obj.get("outbounds")
    if not isinstance(obs, list):
        return False
    return any(isinstance(item, dict) and item.get("protocol") for item in obs)


def _from_xray_profile(profile: dict) -> tuple[dict | None, int]:
    """Один vless+Reality+tcp на профиль. Имя — remarks/ps/name/meta, не outbound.tag."""
    skipped = 0
    obs = profile.get("outbounds")
    if not isinstance(obs, list):
        return None, 0
    title = _profile_title(profile)
    suitable: list[tuple[str, dict]] = []
    for ob in obs:
        if not isinstance(ob, dict):
            continue
        kind = str(ob.get("type") or ob.get("protocol") or "").lower()
        if kind and kind != "vless":
            skipped += 1
            continue
        node = _from_xray(ob)
        if node:
            if title:
                node = {**node, "tag": title, "name": title}
            suitable.append((str(ob.get("tag") or ""), node))
        elif kind == "vless":
            skipped += 1
    if not suitable:
        return None, skipped
    chosen = None
    for tag, node in suitable:
        if tag == "proxy":
            chosen = node
            break
    if chosen is None:
        chosen = suitable[0][1]
    skipped += len(suitable) - 1
    return chosen, skipped


def _from_xray(ob: dict) -> dict | None:
    """Happ-профиль: Xray outbound (protocol/vnext/streamSettings), не sing-box type=."""
    if str(ob.get("protocol") or "").lower() != "vless":
        return None
    settings = ob.get("settings") if isinstance(ob.get("settings"), dict) else {}
    vnext = settings.get("vnext")
    if not isinstance(vnext, list) or not vnext or not isinstance(vnext[0], dict):
        return None
    server = vnext[0]
    users = server.get("users")
    user = users[0] if isinstance(users, list) and users and isinstance(users[0], dict) else {}
    stream = ob.get("streamSettings") if isinstance(ob.get("streamSettings"), dict) else {}
    if not stream:
        stream = ob.get("stream_settings") if isinstance(ob.get("stream_settings"), dict) else {}
    security = str(stream.get("security") or "").lower()
    reality = stream.get("realitySettings") or stream.get("reality_settings") or {}
    if not isinstance(reality, dict):
        reality = {}
    pbk = reality.get("publicKey") or reality.get("public_key") or ""
    if security and security != "reality":
        return None
    if not security and not pbk:
        return None
    return _node_from_parts(
        uuid=user.get("id") or user.get("uuid") or "",
        host=server.get("address") or server.get("addr") or "",
        port=server.get("port") or 443,
        sni=reality.get("serverName") or reality.get("server_name") or stream.get("sni") or "",
        public_key=pbk,
        fingerprint=reality.get("fingerprint") or reality.get("fp") or "firefox",
        flow=user.get("flow") or "",
        net=stream.get("network") or stream.get("net") or "tcp",
        tag=ob.get("tag") or "",
        short_id=reality.get("shortId") or reality.get("short_id") or "",
    )


def _collect_json(data, skipped: int) -> tuple[list[dict], int]:
    found: list[dict] = []

    def push(obj) -> None:
        nonlocal skipped
        if not isinstance(obj, dict):
            return
        kind = str(obj.get("type") or obj.get("protocol") or "").lower()
        if kind and kind != "vless":
            skipped += 1
            return
        node = _from_singbox(obj) or _from_clash(obj) or _from_xray(obj)
        if node:
            found.append(node)
        elif kind == "vless":
            skipped += 1

    def take_profile(profile: dict) -> None:
        nonlocal skipped
        node, extra = _from_xray_profile(profile)
        skipped += extra
        if node:
            found.append(node)

    def walk(obj) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item)
            return
        if not isinstance(obj, dict):
            return
        nested = False
        if isinstance(obj.get("outbounds"), list):
            for item in obj["outbounds"]:
                walk(item)
            nested = True
        if isinstance(obj.get("proxies"), list):
            for item in obj["proxies"]:
                walk(item)
            nested = True
        if not nested:
            push(obj)

    if isinstance(data, list) and any(_is_xray_profile(x) for x in data):
        for item in data:
            if _is_xray_profile(item):
                take_profile(item)
            else:
                walk(item)
        return found, skipped
    if _is_xray_profile(data):
        take_profile(data)
        return found, skipped
    walk(data)
    return found, skipped


def _try_base64(text: str) -> str:
    compact = "".join(text.split())
    if not compact or len(compact) < 16:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9+/]+=*", compact):
        return ""
    if "{" in compact or "vless://" in compact.lower():
        return ""
    pad = (-len(compact)) % 4
    try:
        decoded = base64.b64decode(compact + ("=" * pad), validate=False)
    except (ValueError, binascii.Error):
        return ""
    try:
        out = decoded.decode("utf-8")
    except UnicodeDecodeError:
        out = decoded.decode("latin-1")
    if re.search(r"vless://", out, re.I):
        return out
    return ""


def parse_body(raw) -> dict:
    text = str(raw or "").strip()
    if not text:
        return {"ok": False, "nodes": [], "skipped": 0, "why": "пусто"}

    skipped = len(OTHER_RE.findall(text))
    uris = [m.group(0).rstrip("),.;") for m in VLESS_RE.finditer(text)]
    if uris:
        nodes_out: list[dict] = []
        for uri in uris:
            node = _parse_vless_uri(uri)
            if node:
                nodes_out.append(node)
            else:
                skipped += 1
        if nodes_out:
            return {"ok": True, "nodes": nodes_out, "skipped": skipped}
        return {"ok": False, "nodes": [], "skipped": skipped, "why": "в подписке нет пригодного vless"}

    decoded = _try_base64(text)
    if decoded:
        return parse_body(decoded)

    if text[:1] in "{[":
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return {"ok": False, "nodes": [], "skipped": skipped, "why": "битый JSON"}
        found, skipped = _collect_json(data, skipped)
        if found:
            return {"ok": True, "nodes": found, "skipped": skipped}
        return {"ok": False, "nodes": [], "skipped": skipped, "why": "в подписке нет пригодного vless"}

    return {"ok": False, "nodes": [], "skipped": skipped, "why": "в подписке нет пригодного vless"}


def _download(url: str, ua: str) -> tuple[str | None, str]:
    if not str(url).lower().startswith("https://"):
        return None, "нужен https://"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": ua, "Accept": "*/*"},
    )
    try:
        with _OPENER.open(req, timeout=15) as resp:
            final = resp.geturl()
            if not str(final).lower().startswith("https://"):
                return None, "редирект не на https"
            data = resp.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        return None, f"подписка {exc.code}"
    except (OSError, ValueError) as exc:
        why = str(exc) or "нет сети"
        if "редирект не на https" in why:
            return None, "редирект не на https"
        return None, why
    if len(data) > MAX_BODY:
        return None, "ответ слишком большой"
    return data.decode("utf-8", errors="replace"), ""


def _unique_tag(want: str, taken: set[str]) -> str:
    base = want or "Server"
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def _identity_parsed(node: dict) -> tuple[str, str, int]:
    try:
        port = int(node.get("port") or 443)
    except (TypeError, ValueError):
        port = 443
    return (
        str(node.get("uuid") or "").strip().lower(),
        str(node.get("host") or "").strip().lower(),
        port,
    )


def _identity_ob(ob: dict, hosts_map: dict[str, str]) -> tuple[str, str, int]:
    uuid = str(ob.get("uuid") or "").strip().lower()
    port = ob.get("server_port")
    port = port if isinstance(port, int) else 443
    tag = ob.get("tag")
    host = ""
    if isinstance(tag, str) and tag:
        host = hosts_map.get(tag) or ""
    if not host or _IP_RE.match(host):
        server = ob.get("server")
        if isinstance(server, str) and server and not _IP_RE.match(server):
            host = server
        elif not host:
            host = server if isinstance(server, str) else ""
    return (uuid, str(host).strip().lower(), port)


def _drop_sidecar_if_gone(filename: str, alive: set[str]) -> None:
    path = paths.root() / filename
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return
    if isinstance(data, dict) and data.get("tag") not in alive:
        path.unlink(missing_ok=True)


def _remap_sidecar_tags(renames: dict[str, str]) -> None:
    if not renames:
        return
    for filename in (nodes.PICK_FILE, nodes.FAV_FILE):
        path = paths.root() / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        tag = data.get("tag")
        if not isinstance(tag, str) or tag not in renames:
            continue
        data["tag"] = renames[tag]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
        tmp.replace(path)


def _roster_fail(why: str) -> dict:
    from app.stack import roster

    return {**roster.stack_nodes(), "ok": False, "why": why}


def sync(parsed_nodes: list[dict]) -> dict:
    from app.stack import roster

    if not parsed_nodes:
        return _roster_fail("в подписке нет пригодного vless")

    pref = get()
    owned = [t for t in (pref.get("tags") or []) if isinstance(t, str) and t]
    owned_set = set(owned)
    cfg = nodes.read_config()
    hosts_map = nodes.hosts()

    existing_vless: list[dict] = []
    others: list = []
    for ob in cfg.get("outbounds", []):
        if isinstance(ob, dict) and ob.get("type") == "vless" and isinstance(ob.get("tag"), str) and ob["tag"]:
            existing_vless.append(ob)
        else:
            others.append(ob)

    by_id: dict[tuple[str, str, int], dict] = {}
    for ob in existing_vless:
        by_id.setdefault(_identity_ob(ob, hosts_map), ob)

    manuals = [ob for ob in existing_vless if ob["tag"] not in owned_set]
    manual_ids = {_identity_ob(ob, hosts_map) for ob in manuals}
    taken = {ob["tag"] for ob in manuals}
    new_owned: list[dict] = []
    new_owned_tags: list[str] = []
    seen_ids: set[tuple[str, str, int]] = set()
    renames: dict[str, str] = {}

    for node in parsed_nodes:
        ident = _identity_parsed(node)
        if ident in seen_ids:
            continue
        seen_ids.add(ident)
        if ident in manual_ids:
            continue
        want = str(node.get("tag") or node.get("name") or node.get("host") or "Server").strip()
        tag = _unique_tag(want, taken)
        existing = by_id.get(ident)
        if existing is not None and existing["tag"] in owned_set and existing["tag"] != tag:
            renames[existing["tag"]] = tag
        taken.add(tag)
        outbound = nodes.parsed_to_outbound({**node, "tag": tag})
        new_owned.append(outbound)
        new_owned_tags.append(tag)
        hosts_map[tag] = nodes._host_for({**node, "tag": tag}, outbound)

    vless_new = new_owned + manuals
    alive = {ob["tag"] for ob in vless_new}
    insert_at = len(others)
    for i, ob in enumerate(others):
        if isinstance(ob, dict) and ob.get("tag") in ("warp", "direct"):
            insert_at = i
            break
    cfg["outbounds"] = others[:insert_at] + vless_new + others[insert_at:]

    if renames:
        selected = nodes._selector_outbounds(cfg)
        if selected:
            nodes._set_selector(cfg, [renames.get(t, t) for t in selected])

    nodes.ensure_selector(cfg)

    _remap_sidecar_tags(renames)
    _drop_sidecar_if_gone(nodes.PICK_FILE, alive)
    _drop_sidecar_if_gone(nodes.FAV_FILE, alive)
    nodes._set_hosts({tag: host for tag, host in hosts_map.items() if tag in alive})
    nodes.write_config(cfg)
    _write_pref(str(pref.get("url") or ""), new_owned_tags)
    return {"ok": True, **roster.stack_nodes()}


def refresh() -> dict:
    from app.stack import roster

    with _LOCK:
        pref = get()
        url = str(pref.get("url") or "").strip()
        if not url:
            return {"ok": True, "skipped": True, "why": "нет ссылки", **roster.stack_nodes()}
        if not url.lower().startswith("https://"):
            return _roster_fail("нужен https://")

        body, err = _download(url, UA_HAPP)
        if err:
            return _roster_fail(err)
        parsed = parse_body(body)
        if not parsed.get("nodes"):
            body2, err2 = _download(url, UA_V2RAYN)
            if not err2:
                again = parse_body(body2)
                if again.get("nodes"):
                    parsed = again
        if not parsed.get("nodes"):
            return _roster_fail(parsed.get("why") or "в подписке нет пригодного vless")
        return sync(parsed["nodes"])
