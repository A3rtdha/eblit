from __future__ import annotations

RIOT_PROCESS_NAMES = (
    "VALORANT-Win64-Shipping.exe",
    "VALORANT.exe",
    "RiotClientServices.exe",
    "RiotClientUx.exe",
    "RiotClientUxRender.exe",
    "vgc.exe",
    "vgm.exe",
)
RIOT_DOMAIN_SUFFIXES = (
    "riotgames.com",
    "riotgames.net",
    "riotcdn.net",
    "playvalorant.com",
    "pvp.net",
)


def _real_dns_server(dns: dict) -> str | None:
    servers = [
        server["tag"]
        for server in dns.get("servers", [])
        if isinstance(server, dict)
        and isinstance(server.get("tag"), str)
        and server["tag"] != "fakeip"
        and server.get("type") != "fakeip"
        and server.get("address") != "fakeip"
    ]
    preferred = dns.get("final")
    if preferred in servers:
        return preferred
    return servers[0] if servers else None


def _is_game_dns_rule(rule: dict) -> bool:
    return (
        set(rule) == {"domain_suffix", "server"}
        and rule.get("domain_suffix") == list(RIOT_DOMAIN_SUFFIXES)
    )


def apply_game_bypass(cfg: dict) -> bool:
    """Keep Riot traffic direct and its DNS answers outside the FakeIP pool."""
    changed = False
    route_rules = cfg.setdefault("route", {}).setdefault("rules", [])
    process_rule = {"process_name": list(RIOT_PROCESS_NAMES), "outbound": "direct"}
    domain_rule = {"domain_suffix": list(RIOT_DOMAIN_SUFFIXES), "outbound": "direct"}
    rules = [rule for rule in route_rules if rule not in (process_rule, domain_rule)]

    insert_at = 0
    while insert_at < len(rules) and rules[insert_at].get("action") in {
        "sniff", "hijack-dns", "resolve",
    }:
        insert_at += 1
    rules[insert_at:insert_at] = [process_rule, domain_rule]
    if rules != route_rules:
        route_rules[:] = rules
        changed = True

    dns = cfg.setdefault("dns", {})
    server = _real_dns_server(dns)
    dns_rules = dns.setdefault("rules", [])
    rules = [rule for rule in dns_rules if not _is_game_dns_rule(rule)]
    if server is not None:
        rules.insert(0, {"domain_suffix": list(RIOT_DOMAIN_SUFFIXES), "server": server})
    if rules != dns_rules:
        dns_rules[:] = rules
        changed = True
    return changed
