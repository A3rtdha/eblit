"""Lagom nodes and routing lists in config.json."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import app.paths as paths

SELECTOR = "LagomVPN"
HOSTS_FILE = "lagom-nodes.json"
FAV_FILE = "lagom-favorite.json"
PICK_FILE = "lagom-pick.json"

# Теги, которые 1.0.0 по ошибке увёз как «встроенные». Не хосты и не ключи —
# только чтобы установщик затёр ту утечку, а не принял её за ноды пользователя.
STOCK_LEAK_TAGS = frozenset(
    {"Finland", "Sweden", "USA", "Italy", "Germany", "UK", "Japan"}
)
_TUN_DIRECT_CIDR = "172.19.88.0/30"

FASTLY_CIDRS = [
    "151.101.0.0/16",
    "151.139.0.0/16",
    "199.232.0.0/16",
    "199.27.69.0/24",
    "199.27.74.0/23",
    "199.27.77.0/24",
    "199.27.128.0/21",
    "199.27.212.0/22",
    "199.27.228.0/24",
    "199.27.231.0/24",
    "23.235.32.0/19",
    "23.235.126.0/23",
]

DNS_VIA_TUN = ["8.8.8.8/32", "8.8.4.4/32", "1.1.1.1/32", "1.0.0.1/32"]
FAKEIP_RANGE = "198.18.0.0/15"
DOH_BLOCK = ["dns.google", "cloudflare-dns.com", "one.one.one.one"]

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def cfg_path() -> Path:
    return paths.root() / "config.json"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_config() -> dict:
    return json.loads(cfg_path().read_text(encoding="utf-8"))


def write_config(cfg: dict) -> None:
    _atomic_write(cfg_path(), json.dumps(cfg, indent=2) + "\n")


def _hosts_path() -> Path:
    return paths.root() / HOSTS_FILE


def _sni(ob: dict) -> str:
    tls = ob.get("tls")
    if not isinstance(tls, dict):
        return ""
    name = tls.get("server_name")
    return name if isinstance(name, str) else ""


def _seed_hosts_from_config(cfg: dict) -> dict[str, str]:
    """tag → hostname только из тех vless, что уже есть в config. Без стокового списка."""
    out: dict[str, str] = {}
    for ob in cfg.get("outbounds", []):
        if not isinstance(ob, dict) or ob.get("type") != "vless":
            continue
        tag = ob.get("tag")
        if not isinstance(tag, str) or not tag:
            continue
        server = ob.get("server")
        host = server if isinstance(server, str) and server and not _IP_RE.match(server) else ""
        if not host:
            host = _sni(ob)
        if host:
            out[tag] = host
    return out


def hosts() -> dict[str, str]:
    path = _hosts_path()
    cfg = read_config()
    seeded = _seed_hosts_from_config(cfg)
    if not path.is_file():
        if seeded:
            _atomic_write(path, json.dumps(seeded, indent=2) + "\n")
        return seeded
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return seeded
    if not isinstance(data, dict):
        return seeded
    merged = dict(seeded)
    for tag, host in data.items():
        if isinstance(tag, str) and isinstance(host, str) and tag and host:
            merged[tag] = host
    return merged


def _set_hosts(mapping: dict[str, str]) -> None:
    _atomic_write(_hosts_path(), json.dumps(mapping, indent=2) + "\n")


def vless_tags(cfg: dict | None = None) -> list[str]:
    data = cfg if cfg is not None else read_config()
    tags: list[str] = []
    for ob in data.get("outbounds", []):
        if isinstance(ob, dict) and ob.get("type") == "vless":
            tag = ob.get("tag")
            if isinstance(tag, str) and tag:
                tags.append(tag)
    return tags


def is_builtin_tag(tag: str) -> bool:
    """Продуктовых нод нет. Оставлено, чтобы ростер не падал."""
    return False


def lagom_suffixes(cfg: dict | None = None) -> list[str]:
    data = cfg if cfg is not None else read_config()
    for rule in data.get("route", {}).get("rules", []):
        if not isinstance(rule, dict):
            continue
        if rule.get("outbound") != SELECTOR:
            continue
        suffixes = rule.get("domain_suffix")
        if isinstance(suffixes, list):
            return [str(s) for s in suffixes if s]
    return []


def _find_rule(cfg: dict, *, outbound: str | None = None, action: str | None = None) -> dict | None:
    for rule in cfg.get("route", {}).get("rules", []):
        if not isinstance(rule, dict):
            continue
        if outbound is not None and rule.get("outbound") != outbound:
            continue
        if action is not None and rule.get("action") != action:
            continue
        return rule
    return None


def apply_lagom_suffixes(cfg: dict, suffixes: list[str]) -> None:
    clean = []
    seen: set[str] = set()
    for item in suffixes:
        s = str(item).strip().lstrip(".")
        if not s or s in seen:
            continue
        seen.add(s)
        clean.append(s)

    route_rule = _find_rule(cfg, outbound=SELECTOR)
    if route_rule is not None:
        route_rule["domain_suffix"] = list(clean)

    dns = cfg.setdefault("dns", {})
    rules = dns.setdefault("rules", [])
    fake_rule = None
    for rule in rules:
        if isinstance(rule, dict) and rule.get("server") == "fakeip":
            fake_rule = rule
            break
    if fake_rule is None:
        rules.insert(0, {"domain_suffix": list(clean), "server": "fakeip"})
    else:
        fake_rule["domain_suffix"] = list(clean)


def has_user_vless(cfg: dict) -> bool:
    """Есть нода, которую человек добавил сам — не семёрка из утечки 1.0.0."""
    for ob in cfg.get("outbounds", []):
        if not isinstance(ob, dict) or ob.get("type") != "vless":
            continue
        tag = ob.get("tag")
        if isinstance(tag, str) and tag and tag not in STOCK_LEAK_TAGS:
            return True
    return False


def _strip_builder_routes(cfg: dict) -> None:
    """Из payload не уезжают личные bypass-правила сборщика (хосты/CIDR нод)."""
    route = cfg.get("route")
    if not isinstance(route, dict):
        return
    rules = route.get("rules")
    if not isinstance(rules, list):
        return
    kept = []
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("outbound") != "direct":
            kept.append(rule)
            continue
        suffixes = rule.get("domain_suffix")
        cidrs = rule.get("ip_cidr")
        if (
            isinstance(suffixes, list)
            and suffixes
            and "domain" not in rule
            and all(isinstance(s, str) and s.endswith(".download") for s in suffixes)
        ):
            continue
        if (
            isinstance(cidrs, list)
            and cidrs
            and _TUN_DIRECT_CIDR not in cidrs
            and not rule.get("ip_is_private")
        ):
            continue
        kept.append(rule)
    route["rules"] = kept


def sanitize_for_ship(cfg: dict) -> dict:
    """Конфиг для установщика: без vless и без обходов под ноды сборщика.

    Селектор → `direct`: пустой selector sing-box не примет. Копия: живой файл не трогаем.
    """
    cfg = copy.deepcopy(cfg)
    outbounds = []
    for ob in cfg.get("outbounds", []):
        if isinstance(ob, dict) and ob.get("type") == "vless":
            continue
        outbounds.append(ob)
    if not any(isinstance(o, dict) and o.get("tag") == "direct" for o in outbounds):
        outbounds.append({"type": "direct", "tag": "direct"})
    for ob in outbounds:
        if isinstance(ob, dict) and ob.get("tag") == SELECTOR:
            ob["type"] = "selector"
            ob["outbounds"] = ["direct"]
    cfg["outbounds"] = outbounds

    for ib in cfg.get("inbounds", []):
        if isinstance(ib, dict) and ib.get("tag") == "mixed-local":
            ib["listen"] = "127.0.0.1"
    _strip_builder_routes(cfg)
    return cfg


def apply_narrow_tun(cfg: dict) -> None:
    for inbound in cfg.get("inbounds", []):
        if not isinstance(inbound, dict) or inbound.get("type") != "tun":
            continue
        inbound.pop("route_exclude_address", None)
        inbound.pop("inet4_route_address", None)
        inbound["address"] = ["172.19.88.1/30"]
        inbound.pop("inet4_address", None)
        inbound["route_address"] = [*FASTLY_CIDRS, FAKEIP_RANGE, *DNS_VIA_TUN]

    dns = cfg.setdefault("dns", {})
    servers = dns.setdefault("servers", [])
    if not any(isinstance(s, dict) and s.get("tag") == "fakeip" for s in servers):
        servers.append({"type": "fakeip", "tag": "fakeip", "inet4_range": FAKEIP_RANGE})

    rules = cfg.setdefault("route", {}).setdefault("rules", [])
    if not _find_rule(cfg, action="reject"):
        insert_at = 0
        for i, rule in enumerate(rules):
            if isinstance(rule, dict) and rule.get("action") == "sniff":
                insert_at = i + 1
                break
        rules.insert(
            insert_at,
            {"domain": list(DOH_BLOCK), "port": [443], "action": "reject"},
        )

    suffixes = lagom_suffixes(cfg)
    if suffixes:
        apply_lagom_suffixes(cfg, suffixes)


def links() -> list[str]:
    return lagom_suffixes()


def set_links(suffixes: list[str]) -> None:
    cfg = read_config()
    apply_lagom_suffixes(cfg, suffixes)
    write_config(cfg)


def parsed_to_outbound(parsed: dict) -> dict:
    tag = str(parsed.get("tag") or parsed.get("name") or parsed.get("host") or "Custom").strip()
    host = str(parsed.get("host") or "").strip()
    port = int(parsed.get("port") or 443)
    uuid = str(parsed.get("uuid") or "").strip()
    sni = str(parsed.get("sni") or host).strip()
    fp = str(parsed.get("fingerprint") or "firefox").strip() or "firefox"
    pbk = str(parsed.get("public_key") or "").strip()
    flow = str(parsed.get("flow") or "").strip()
    ob: dict = {
        "type": "vless",
        "tag": tag,
        "server": host,
        "server_port": port,
        "uuid": uuid,
        "packet_encoding": "xudp",
        "tls": {
            "enabled": True,
            "server_name": sni,
            "utls": {"enabled": True, "fingerprint": fp},
            "reality": {"enabled": True, "public_key": pbk},
        },
    }
    if flow:
        ob["flow"] = flow
    return ob


def _host_for(parsed: dict, outbound: dict) -> str:
    host = str(parsed.get("host") or outbound.get("server") or "").strip()
    if host and not _IP_RE.match(host):
        return host
    sni = str(parsed.get("sni") or _sni(outbound)).strip()
    return sni or host


def _selector_outbounds(cfg: dict) -> list[str]:
    for ob in cfg.get("outbounds", []):
        if isinstance(ob, dict) and ob.get("tag") == SELECTOR:
            picked = ob.get("outbounds")
            if isinstance(picked, list):
                return [str(x) for x in picked if isinstance(x, str)]
    return []


def _set_selector(cfg: dict, tags: list[str]) -> None:
    for ob in cfg.get("outbounds", []):
        if isinstance(ob, dict) and ob.get("tag") == SELECTOR:
            ob["outbounds"] = tags
            return
    cfg.setdefault("outbounds", []).insert(
        0,
        {"type": "selector", "tag": SELECTOR, "outbounds": tags},
    )


def ensure_selector(cfg: dict) -> bool:
    """Пустой или мёртвый LagomVPN → первый vless или direct. True если писал.

    Не создаёт селектор, если его нет: установщик чинит только уже лежащий файл.
    """
    has_sel = any(
        isinstance(ob, dict) and ob.get("tag") == SELECTOR
        for ob in cfg.get("outbounds", [])
    )
    if not has_sel:
        return False
    tags = vless_tags(cfg)
    selected = _selector_outbounds(cfg)
    alive = set(tags)
    if selected and all(t in alive or t == "direct" for t in selected):
        return False
    _set_selector(cfg, tags[:1] or ["direct"])
    return True


def add(parsed: dict) -> dict:
    from app.stack import roster

    outbound = parsed_to_outbound(parsed)
    tag = outbound["tag"]
    cfg = read_config()
    tags = vless_tags(cfg)
    if tag in tags:
        raise ValueError(f"сервер {tag} уже есть")
    insert_at = len(cfg.get("outbounds", []))
    for i, ob in enumerate(cfg.get("outbounds", [])):
        if isinstance(ob, dict) and ob.get("tag") in ("warp", "direct"):
            insert_at = i
            break
    cfg.setdefault("outbounds", []).insert(insert_at, outbound)
    mapping = hosts()
    mapping[tag] = _host_for(parsed, outbound)
    _set_hosts(mapping)
    write_config(cfg)
    return roster.stack_nodes()


def remove(tag: str) -> dict:
    from app.stack import roster

    cfg = read_config()
    cfg["outbounds"] = [
        ob
        for ob in cfg.get("outbounds", [])
        if not (isinstance(ob, dict) and ob.get("tag") == tag and ob.get("type") == "vless")
    ]
    if tag in _selector_outbounds(cfg):
        # Пустой селектор sing-box не принимает («missing tags») — переводим на любой живой тег.
        rest = vless_tags(cfg)
        _set_selector(cfg, rest[:1])
    mapping = hosts()
    mapping.pop(tag, None)
    _set_hosts(mapping)
    pick_path = paths.root() / PICK_FILE
    if pick_path.is_file():
        try:
            pick = json.loads(pick_path.read_text(encoding="utf-8"))
            if isinstance(pick, dict) and pick.get("tag") == tag:
                pick_path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    fav_path = paths.root() / FAV_FILE
    if fav_path.is_file():
        try:
            fav = json.loads(fav_path.read_text(encoding="utf-8"))
            if isinstance(fav, dict) and fav.get("tag") == tag:
                fav_path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    write_config(cfg)
    return roster.stack_nodes()


def select(tag: str | None) -> None:
    pick_path = paths.root() / PICK_FILE
    if not tag or tag == "auto":
        if pick_path.is_file():
            try:
                data = json.loads(pick_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.pop("manual", None)
                    if data.get("tag"):
                        _atomic_write(pick_path, json.dumps(data) + "\n")
                    else:
                        pick_path.unlink(missing_ok=True)
            except (OSError, json.JSONDecodeError, TypeError):
                pick_path.unlink(missing_ok=True)
        return

    cfg = read_config()
    if tag not in vless_tags(cfg):
        raise ValueError(f"нет сервера {tag}")
    ip = ""
    for ob in cfg.get("outbounds", []):
        if isinstance(ob, dict) and ob.get("tag") == tag:
            server = ob.get("server")
            ip = server if isinstance(server, str) else ""
            break
    _set_selector(cfg, [tag])
    write_config(cfg)
    _atomic_write(pick_path, json.dumps({"tag": tag, "ip": ip, "manual": True}) + "\n")


def set_favorite(tag: str | None) -> None:
    path = paths.root() / FAV_FILE
    if not tag:
        path.unlink(missing_ok=True)
        return
    cfg = read_config()
    if tag not in vless_tags(cfg):
        raise ValueError(f"нет сервера {tag}")
    host = hosts().get(tag, "")
    payload = {"tag": tag}
    if host:
        payload["host"] = host
    _atomic_write(path, json.dumps(payload) + "\n")


def manual_tag() -> str | None:
    path = paths.root() / PICK_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("manual"):
        return None
    tag = data.get("tag")
    return tag if isinstance(tag, str) and tag else None


def clear_manual() -> None:
    select(None)
