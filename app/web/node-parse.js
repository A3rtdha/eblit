(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.EblitNodeParse = api;
})(typeof self !== "undefined" ? self : this, function () {
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  function fail(error) {
    return { ok: false, error: error };
  }

  function maskSecret(value) {
    const s = String(value || "");
    if (!s) return "—";
    if (s.length <= 8) return "••••";
    return `${s.slice(0, 4)}…${s.slice(-4)}`;
  }

  function cleanHost(host) {
    return String(host || "").trim().replace(/^\[|\]$/g, "");
  }

  function validPort(n) {
    return Number.isInteger(n) && n >= 1 && n <= 65535;
  }

  function validHost(host) {
    if (!host || /\s/.test(host)) return false;
    if (host.length > 253) return false;
    return true;
  }

  function nodeFromParts(p) {
    const uuid = String(p.uuid || "").trim();
    const host = cleanHost(p.host);
    const port = Number(p.port);
    const sni = String(p.sni || "").trim();
    const publicKey = String(p.publicKey || "").trim();
    const net = String(p.net || "tcp").toLowerCase();
    if (!UUID_RE.test(uuid)) return null;
    if (!validHost(host)) return null;
    if (!validPort(port)) return null;
    if (!sni) return null;
    if (!publicKey) return null;
    if (net && net !== "tcp") return null;
    const tag = String(p.tag || p.name || host).trim() || host;
    const flow = String(p.flow || "").trim();
    const fingerprint = String(p.fingerprint || "firefox").trim() || "firefox";
    const shortId = String(p.shortId || "").trim();
    return {
      tag: tag,
      name: tag,
      host: host,
      port: port,
      uuid: uuid,
      packet_encoding: "xudp",
      sni: sni,
      fingerprint: fingerprint,
      public_key: publicKey,
      flow: flow,
      short_id: shortId,
    };
  }

  function parseVlessUri(uri) {
    const raw = String(uri || "").trim();
    if (!/^vless:\/\//i.test(raw)) return fail("это не vless://");
    let url;
    try {
      url = new URL(raw);
    } catch (err) {
      return fail("битая ссылка vless://");
    }
    if (url.protocol.toLowerCase() !== "vless:") return fail("это не vless://");
    const q = url.searchParams;
    const security = (q.get("security") || "").toLowerCase();
    const pbk = q.get("pbk") || q.get("publicKey") || "";
    if (security && security !== "reality") {
      return fail(`нужен Reality, не ${security}`);
    }
    if (!security && !pbk) return fail("нет security=reality и pbk");
    const node = nodeFromParts({
      uuid: decodeURIComponent(url.username || ""),
      host: url.hostname,
      port: url.port || 443,
      sni: q.get("sni") || q.get("peer") || "",
      publicKey: pbk,
      fingerprint: q.get("fp") || q.get("fingerprint") || "firefox",
      flow: q.get("flow") || "",
      net: q.get("type") || q.get("net") || "tcp",
      shortId: q.get("sid") || q.get("shortId") || "",
      name: url.hash ? decodeURIComponent(url.hash.slice(1)) : "",
    });
    if (!node) return fail("в vless:// не хватает uuid, host, sni или pbk");
    return { ok: true, node: node };
  }

  function fromSingbox(ob) {
    if (!ob || typeof ob !== "object") return null;
    if (String(ob.type || "").toLowerCase() !== "vless") return null;
    const tls = ob.tls && typeof ob.tls === "object" ? ob.tls : {};
    const reality = tls.reality && typeof tls.reality === "object" ? tls.reality : {};
    const utls = tls.utls && typeof tls.utls === "object" ? tls.utls : {};
    return nodeFromParts({
      uuid: ob.uuid,
      host: ob.server,
      port: ob.server_port || ob.serverPort || 443,
      sni: tls.server_name || tls.serverName || "",
      publicKey: reality.public_key || reality.publicKey || "",
      fingerprint: utls.fingerprint || "firefox",
      flow: ob.flow || "",
      net: "tcp",
      shortId: reality.short_id || reality.shortId || "",
      tag: ob.tag,
      name: ob.tag,
    });
  }

  function fromClash(p) {
    if (!p || typeof p !== "object") return null;
    if (String(p.type || "").toLowerCase() !== "vless") return null;
    const ro = p["reality-opts"] || p.reality_opts || p.realityOpts || {};
    return nodeFromParts({
      uuid: p.uuid,
      host: p.server,
      port: p.port || 443,
      sni: p.servername || p.server_name || p.sni || "",
      publicKey: ro["public-key"] || ro.public_key || ro.publicKey || "",
      fingerprint: p["client-fingerprint"] || p.client_fingerprint || p.fp || "firefox",
      flow: p.flow || "",
      net: p.network || p.net || "tcp",
      shortId: ro["short-id"] || ro.short_id || "",
      tag: p.name,
      name: p.name,
    });
  }

  function collectFromJson(data) {
    const nodes = [];
    const seenBrokenVless = [];

    function pushCandidate(obj, kind) {
      if (!obj || typeof obj !== "object") return;
      const t = String(obj.type || "").toLowerCase();
      if (t && t !== "vless") return;
      const node = kind === "clash" ? fromClash(obj) : fromSingbox(obj) || fromClash(obj);
      if (node) nodes.push(node);
      else if (t === "vless") seenBrokenVless.push(obj.tag || obj.name || "?");
    }

    if (Array.isArray(data)) {
      data.forEach((item) => pushCandidate(item, "any"));
      return { nodes: nodes, broken: seenBrokenVless };
    }
    if (data && typeof data === "object") {
      if (Array.isArray(data.outbounds)) {
        data.outbounds.forEach((item) => pushCandidate(item, "sb"));
        return { nodes: nodes, broken: seenBrokenVless };
      }
      if (Array.isArray(data.proxies)) {
        data.proxies.forEach((item) => pushCandidate(item, "clash"));
        return { nodes: nodes, broken: seenBrokenVless };
      }
      if (data.type) {
        pushCandidate(data, "any");
        return { nodes: nodes, broken: seenBrokenVless };
      }
    }
    return { nodes: nodes, broken: seenBrokenVless, unknown: true };
  }

  function extractVlessUris(text) {
    const found = [];
    const re = /vless:\/\/[^\s<>"']+/gi;
    let m;
    while ((m = re.exec(text))) found.push(m[0].replace(/[),.;]+$/, ""));
    return found;
  }

  function tryBase64(text) {
    const compact = String(text || "").replace(/\s+/g, "");
    if (!compact || compact.length < 16) return "";
    if (!/^[A-Za-z0-9+/]+=*$/.test(compact)) return "";
    if (compact.includes("{") || compact.toLowerCase().includes("vless://")) return "";
    try {
      const decoded = atob(compact);
      if (/vless:\/\//i.test(decoded)) return decoded;
      return "";
    } catch (err) {
      return "";
    }
  }

  function parseNodes(raw) {
    const text = String(raw || "").trim();
    if (!text) return fail("пусто");

    const uris = extractVlessUris(text);
    if (uris.length) {
      const nodes = [];
      for (let i = 0; i < uris.length; i += 1) {
        const one = parseVlessUri(uris[i]);
        if (!one.ok) return fail(one.error);
        nodes.push(one.node);
      }
      return { ok: true, nodes: nodes };
    }

    const b64 = tryBase64(text);
    if (b64) return parseNodes(b64);

    if (text[0] === "{" || text[0] === "[") {
      let data;
      try {
        data = JSON.parse(text);
      } catch (err) {
        return fail("битый JSON");
      }
      const got = collectFromJson(data);
      if (got.unknown && !got.nodes.length) {
        return fail("неизвестный JSON: нет outbounds / proxies / vless");
      }
      if (!got.nodes.length) {
        if (got.broken.length) return fail("vless без uuid/host/sni/pbk — отказ");
        return fail("в JSON нет пригодного vless");
      }
      if (got.broken.length) return fail("часть vless дырявая — отказ, чини экспорт");
      return { ok: true, nodes: got.nodes };
    }

    if (/vmess:\/\/|trojan:\/\/|ss:\/\//i.test(text)) {
      return fail("нужен vless:// или JSON, не vmess/trojan/ss");
    }
    return fail("непонятный формат: жду vless:// или JSON экспорта");
  }

  function previewRows(nodes) {
    return (nodes || []).map((n) => ({
      name: n.name,
      host: n.host,
      sni: n.sni,
      flow: n.flow || "—",
      uuid: maskSecret(n.uuid),
      pbk: maskSecret(n.public_key),
    }));
  }

  function sameNode(a, b) {
    return a.uuid === b.uuid && a.host === b.host && Number(a.port) === Number(b.port);
  }

  return {
    parseVlessUri: parseVlessUri,
    parseNodes: parseNodes,
    maskSecret: maskSecret,
    previewRows: previewRows,
    sameNode: sameNode,
  };
});
