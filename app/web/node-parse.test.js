const assert = require("assert");
const { parseNodes, parseVlessUri, maskSecret, previewRows } = require("./node-parse.js");

const GOOD =
  "vless://aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee@node.example:443" +
  "?security=reality&sni=node.example&pbk=TESTKEY_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" +
  "&fp=firefox&flow=xtls-rprx-vision&type=tcp#Finland";

function throwsFail(raw, needle) {
  const r = parseNodes(raw);
  assert.strictEqual(r.ok, false, `expected fail for ${JSON.stringify(raw).slice(0, 40)}`);
  assert.ok(r.error && r.error.includes(needle), `error «${r.error}» should include «${needle}»`);
}

{
  const r = parseVlessUri(GOOD);
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.node.tag, "Finland");
  assert.strictEqual(r.node.host, "node.example");
  assert.strictEqual(r.node.port, 443);
  assert.strictEqual(r.node.sni, "node.example");
  assert.strictEqual(r.node.flow, "xtls-rprx-vision");
  assert.strictEqual(r.node.packet_encoding, "xudp");
  assert.ok(r.node.uuid.includes("aaaaaaaa"));
  assert.ok(r.node.public_key.startsWith("TESTKEY"));
}

{
  const r = parseNodes(GOOD);
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.nodes.length, 1);
}

throwsFail("", "пусто");
throwsFail("hello world", "непонятный формат");
throwsFail("vmess://aaaa", "не vmess");
throwsFail("vless://not-a-uuid@host:443?security=reality&sni=x&pbk=yyyyyyyyyy", "не хватает");
throwsFail(
  "vless://aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee@host:443?security=tls&sni=x&pbk=yyyyyyyyyy",
  "Reality"
);
throwsFail("{not json", "битый JSON");
throwsFail('{"foo":1}', "неизвестный JSON");
throwsFail(
  JSON.stringify({
    type: "vless",
    tag: "X",
    server: "h.example",
    uuid: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  }),
  "uuid/host/sni/pbk"
);

{
  const r = parseNodes(
    JSON.stringify({
      outbounds: [
        { type: "direct", tag: "direct" },
        {
          type: "vless",
          tag: "Sweden",
          server: "edge.example",
          server_port: 443,
          uuid: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
          flow: "xtls-rprx-vision",
          tls: {
            server_name: "edge.example",
            utls: { fingerprint: "firefox" },
            reality: { public_key: "TESTKEY_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" },
          },
        },
      ],
    })
  );
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.nodes.length, 1);
  assert.strictEqual(r.nodes[0].tag, "Sweden");
  assert.strictEqual(r.nodes[0].host, "edge.example");
}

{
  const r = parseNodes(
    JSON.stringify({
      proxies: [
        {
          name: "USA",
          type: "vless",
          server: "west.example",
          port: 443,
          uuid: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
          servername: "west.example",
          flow: "xtls-rprx-vision",
          "client-fingerprint": "firefox",
          "reality-opts": { "public-key": "TESTKEY_cccccccccccccccccccccccccccccccccc" },
        },
      ],
    })
  );
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.nodes[0].tag, "USA");
}

{
  const rows = previewRows(parseNodes(GOOD).nodes);
  assert.ok(rows[0].uuid.includes("…"));
  assert.ok(!rows[0].uuid.includes("bbbb"));
  assert.ok(maskSecret("abcdefghijklmnop").includes("…"));
}

{
  const packed = Buffer.from(`${GOOD}\n${GOOD.replace("#Finland", "#Copy")}`, "utf8").toString("base64");
  const r = parseNodes(packed);
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.nodes.length, 2);
}

console.log("node-parse ok");
