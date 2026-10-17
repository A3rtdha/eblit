const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(path.join(__dirname, "app.js"), "utf8");
const controller = source.slice(0, source.indexOf("const ROUTES ="));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function session(api) {
  const timers = [];
  const context = vm.createContext({
    document: { getElementById: () => null },
    window: {
      pywebview: { api },
      setInterval: (fn) => { timers.push(fn); return timers.length; },
      clearInterval: () => {},
    },
  });
  vm.runInContext(controller + `
    const power = { title: "Питание" };
    const label = { textContent: "" };
    function clearBusy() { busy = ""; }
    function setBusy(name) { busy = name; }
    function setOn() {}
  `, context);
  return {
    run: (code) => vm.runInContext(code, context),
    timers,
  };
}

async function main() {
  {
    const starting = deferred();
    const order = [];
    const ui = session({
      start: () => { order.push("start"); return starting.promise; },
      stop: () => { order.push("stop"); return { ok: true, pending: true, revision: 2 }; },
    });
    const start = ui.run('call("start")');
    const stop = ui.run('setBusy("stop"); call("stop")');
    await Promise.resolve();
    assert.deepStrictEqual(order, ["start"]);
    starting.resolve({ ok: false, power: true, why: "old failure", revision: 1 });
    await Promise.all([start, stop]);
    assert.deepStrictEqual(order, ["start", "stop"]);
    assert.strictEqual(ui.run("busy"), "stop");
    assert.strictEqual(ui.run("power.title"), "Питание");
    ui.run('applyStack({ ok: true, power: false, revision: 2 })');
    ui.run('applyStack({ ok: true, power: true, revision: 1 })');
    assert.strictEqual(ui.run("powerOn"), false);
  }
  {
    const syncing = deferred();
    const ui = session({
      sync_power: () => syncing.promise,
      stop: () => ({ ok: true, power: false, revision: 2 }),
    });
    const old = ui.run('call("sync_power")');
    await ui.run('call("stop")');
    syncing.resolve({ ok: true, power: true, revision: 1 });
    assert.strictEqual(await old, null);
    assert.strictEqual(ui.run("powerOn"), false);
  }
  {
    const starting = deferred();
    const ui = session({
      start: () => starting.promise,
      stop: () => ({ ok: true, pending: true, revision: 2 }),
    });
    const start = ui.run('call("start")');
    await Promise.resolve();
    const stop = ui.run('setBusy("stop"); call("stop")');
    starting.reject(new Error("late transport error"));
    await Promise.all([start, stop]);
    assert.strictEqual(ui.run("busy"), "stop");
    assert.strictEqual(ui.run("label.textContent"), "");
  }
  {
    const pulling = deferred();
    const ui = session({
      pull: () => pulling.promise,
      stop: () => ({ ok: true, power: false, revision: 2 }),
    });
    ui.run("armPull()");
    const old = ui.timers[0]();
    await ui.run('call("stop")');
    pulling.resolve({ ok: true, power: true, revision: 1 });
    await old;
    assert.strictEqual(ui.run("powerOn"), false);
  }
  {
    const ui = session({ status: () => ({ ok: false, why: "old error", revision: 1 }) });
    ui.run('applyStack({ ok: true, power: false, revision: 2 }); setBusy("stop")');
    assert.strictEqual(await ui.run('call("status")'), null);
    assert.strictEqual(ui.run("busy"), "stop");
  }
  {
    const pulling = deferred();
    const stopping = deferred();
    const ui = session({ pull: () => pulling.promise, stop: () => stopping.promise });
    ui.run("powerOn = true; powerRevision = 1; armPull()");
    const polled = ui.timers[0]();
    const stopped = ui.run('setBusy("stop"); call("stop")');
    pulling.resolve({ ok: true, power: false, revision: 2 });
    await Promise.resolve();
    assert.strictEqual(ui.run("busy"), "stop");
    stopping.resolve({ ok: true, pending: true, revision: 2 });
    await Promise.all([polled, stopped]);
    assert.strictEqual(ui.run("powerOn"), false);
    assert.strictEqual(ui.run("busy"), "");
  }
  {
    const ui = session({ stop: () => ({ ok: true, power: false, revision: 2 }) });
    await ui.run('call("stop")');
    ui.run('watchRestart({ restart: true, revision: 1 }, 0)');
    assert.strictEqual(ui.run("busy"), "");
  }
  {
    const ui = session({});
    ui.run('applyStack({ ok: true, power: true, revision: 3 })');
    ui.run('watchRestart({ restart: true, revision: 3 }, 0)');
    assert.strictEqual(ui.run("busy"), "");
    ui.run('watchRestart({ restart: true, revision: 4 }, 0)');
    assert.strictEqual(ui.run("busy"), "reload");
  }
  console.log("power-state: 8 transition scenarios passed");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
