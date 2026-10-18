const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
const links = source.slice(source.indexOf("const DEFAULT_LINKS ="), source.indexOf("const PROBE_SECONDS ="));

function settings(api) {
  const events = {};
  const attributes = {};
  const input = {
    value: "",
    validationMessage: "",
    reported: 0,
    addEventListener: (name, handler) => { events[name] = handler; },
    setCustomValidity(message) { this.validationMessage = message; },
    reportValidity() { this.reported += 1; },
    setAttribute: (name, value) => { attributes[name] = value; },
  };
  const context = vm.createContext({
    document: { getElementById: (id) => id === "links-input" ? input : null },
    window: { pywebview: { api } },
  });
  vm.runInContext(links + "\nconst load = bindLinks();", context);
  return {
    input,
    events,
    attributes,
    load: () => vm.runInContext("load()", context),
  };
}

test("invalid suffix shows the backend error and allows correction", async () => {
  const ui = settings({ set_links: async () => ({ ok: false, why: "Укажите полный домен: example.com" }) });
  ui.input.value = "com";

  await ui.events.change();

  assert.strictEqual(ui.input.value, "com");
  assert.strictEqual(ui.input.validationMessage, "Укажите полный домен: example.com");
  assert.strictEqual(ui.attributes["aria-invalid"], "true");
  assert.strictEqual(ui.input.reported, 1);
  ui.input.value = "example.com";
  ui.events.input();
  assert.strictEqual(ui.input.validationMessage, "");
  assert.strictEqual(ui.attributes["aria-invalid"], "false");
});

test("successful save displays canonical domains returned by the backend", async () => {
  let saves = 0;
  const ui = settings({ set_links: async () => {
    saves += 1;
    return { ok: true, links: ["example.com", "gemini.google.com"] };
  } });
  ui.input.value = "https://EXAMPLE.COM/path";

  await ui.events.blur();

  assert.strictEqual(ui.input.value, "example.com, gemini.google.com");
  await ui.events.blur();
  assert.strictEqual(saves, 1);
});

test("a save response does not overwrite a newer edit", async () => {
  let resolve;
  const ui = settings({ set_links: () => new Promise((done) => { resolve = done; }) });
  ui.input.value = "https://example.com/path";
  const pending = ui.events.change();
  ui.input.value = "another.example";
  resolve({ ok: true, links: ["example.com"] });
  await pending;
  assert.strictEqual(ui.input.value, "another.example");
});

test("a transport failure reports that the domains were not saved", async () => {
  const ui = settings({ set_links: async () => { throw new Error("disconnected"); } });
  ui.input.value = "example.com";
  await ui.events.blur();
  assert.strictEqual(ui.input.validationMessage, "Не удалось сохранить домены");
});

test("a failed load reports its error without replacing the existing list", async () => {
  const ui = settings({ links: async () => ({ ok: false, why: "config.json повреждён" }) });
  ui.input.value = "custom.example";
  await ui.load();
  assert.strictEqual(ui.input.value, "custom.example");
  assert.strictEqual(ui.input.validationMessage, "config.json повреждён");
});
