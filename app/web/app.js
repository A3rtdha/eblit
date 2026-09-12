let probeSec = 30;
let powerOn = false;
let tickTimer = 0;
let busy = "";
let serverRefresh = null;
let applyPing = null;
let applySub = null;
let linksLoader = null;

function paintLegs(legs) {
  const ids = { box: "st-box", warp: "st-warp", node: "st-node" };
  Object.entries(ids).forEach(([key, id]) => {
    const el = document.getElementById(id);
    if (!el) return;
    const leg = (legs && legs[key]) || { state: "off", why: "" };
    el.classList.remove("off", "ok", "bad");
    el.classList.add(leg.state || "off");
    if (leg.why) el.title = leg.why;
  });
}

function applyStack(data) {
  if (!data || data.pending) return;
  if (data.kind === "reconnect") {
    // Watchdog сам инициировал перезапуск — покажем спиннер, если окно открыто.
    if (!busy) setBusy("reload");
    armPull();
    return;
  }
  if (data.kind === "update") {
    if (data.started) {
      setVer("go", data);
      paintUpdateAsk("go", data);
      return;
    }
    if (data.newer) {
      setVer("new", data);
      if (data.must) lockUpdate(data);
      return;
    }
    setVer(data.ok === false ? "fail" : "same", data);
    paintUpdateAsk(data.ok === false ? "fail" : "same", data);
    return;
  }
  if (data.kind === "ping") {
    if (applyPing) applyPing(data);
    return;
  }
  if (data.kind === "sub") {
    if (applySub) applySub(data);
    return;
  }
  if (data.kind === "autostart") {
    if (chkAuto) {
      chkAuto.checked = !!data.on;
      chkAuto.title = data.on ? "в автозагрузке" : (data.why || "");
    }
    return;
  }
  if ("power" in data) {
    powerOn = !!data.power;
    clearBusy();
    setOn(powerOn);
    power.title = data.why || "Питание";
  }
  if (data.legs) paintLegs(data.legs);
  armTick();
}

function armTick() {
  window.clearInterval(tickTimer);
  tickTimer = 0;
  const box = document.getElementById("chk-tick");
  if (!powerOn || (box && !box.checked)) return;
  tickTimer = window.setInterval(() => {
    call("tick");
  }, Math.max(10, probeSec) * 1000);
}

let syncTimer = 0;
function armSyncPower() {
  if (syncTimer) return;
  syncTimer = window.setInterval(() => {
    if (!busy) call("sync_power");
  }, 5000);
}

async function call(name, arg) {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api[name]) {
    clearBusy();
    return null;
  }
  const result = arg === undefined ? await api[name]() : await api[name](arg);
  applyStack(result);
  if (result && result.pending) armPull();
  return result;
}

let pullTimer = 0;
function armPull() {
  if (pullTimer) return;
  const api = () => window.pywebview && window.pywebview.api;
  let idle = 0;
  pullTimer = window.setInterval(async () => {
    const bridge = api();
    if (!bridge || !bridge.pull) {
      idle += 1;
      if (idle > 50) {
        window.clearInterval(pullTimer);
        pullTimer = 0;
      }
      return;
    }
    const data = await bridge.pull();
    if (!data || data.pending) {
      idle = data && data.wait ? 0 : idle + 1;
      // Подключение не отвечает — не оставляем кнопку вечно в «Включаю…».
      if (busy && idle > 20) clearBusy();
      if (idle > 50) {
        window.clearInterval(pullTimer);
        pullTimer = 0;
      }
      return;
    }
    idle = 0;
    applyStack(data);
  }, 100);
}

window.applyStack = applyStack;

const ROUTES = {
  "": "home",
  "#": "home",
  "#/": "home",
  "#/settings": "settings",
  "#/guide": "guide",
  "#/first": "first",
};

const TITLES = {
  home: "Eblit",
  settings: "Настройки",
  guide: "Что это и как работает",
  first: "Сначала",
};

const power = document.getElementById("power");
const label = document.getElementById("st-label");
const island = document.querySelector(".island");
const title = document.getElementById("title");
const back = document.getElementById("btn-back");
const views = {
  home: document.getElementById("view-home"),
  settings: document.getElementById("view-settings"),
  guide: document.getElementById("view-guide"),
  first: document.getElementById("view-first"),
};

function routeName() {
  return ROUTES[location.hash] || "home";
}

function applyRoute() {
  const name = routeName();
  Object.entries(views).forEach(([key, el]) => {
    if (el) el.hidden = key !== name;
  });
  title.textContent = TITLES[name] || "Eblit";
  back.hidden = name === "home" || name === "first";
  if (name === "settings") {
    if (linksLoader) linksLoader();
    if (serverRefresh) serverRefresh();
  }
}

function go(path) {
  const hash = path.startsWith("#") ? path : `#/${path}`;
  if (location.hash === hash) applyRoute();
  else location.hash = hash;
}

function goHome() {
  if (routeName() === "home") return;
  location.hash = "#/";
}

if (!location.hash) history.replaceState(null, "", `${location.pathname}${location.search}#/`);
applyRoute();
window.addEventListener("hashchange", applyRoute);

function closeCombos(except) {
  document.querySelectorAll(".combo.open").forEach((root) => {
    if (root === except) return;
    root.classList.remove("open");
    const menu = root.querySelector(".combo-menu");
    const btn = root.querySelector(".combo-btn");
    if (menu) menu.hidden = true;
    if (btn) btn.setAttribute("aria-expanded", "false");
  });
}

function paintCombo(root) {
  const sel = root.querySelector("select");
  const btn = root.querySelector(".combo-btn");
  const menu = root.querySelector(".combo-menu");
  if (!sel) return;
  const opt = sel.selectedOptions[0];
  if (btn) btn.textContent = opt ? opt.textContent : "";
  if (!menu) return;
  menu.querySelectorAll("[role='option']").forEach((el) => {
    const on = el.dataset.value === sel.value;
    el.setAttribute("aria-selected", on ? "true" : "false");
    el.classList.toggle("hi", on);
  });
}

function rebuildComboMenu(root) {
  const sel = root.querySelector("select");
  const menu = root.querySelector(".combo-menu");
  if (!sel || !menu) return;
  menu.replaceChildren(
    ...[...sel.options].map((opt) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.dataset.value = opt.value;
      li.textContent = opt.textContent;
      return li;
    })
  );
  paintCombo(root);
}

function mountCombo(root) {
  const sel = root.querySelector("select");
  const btn = root.querySelector(".combo-btn");
  const menu = root.querySelector(".combo-menu");
  if (!sel || !btn || !menu) return;
  rebuildComboMenu(root);
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (root.classList.contains("open")) closeCombos();
    else {
      closeCombos(root);
      root.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      menu.hidden = false;
      paintCombo(root);
    }
  });
  menu.addEventListener("click", (e) => {
    const opt = e.target.closest("[role='option']");
    if (!opt) return;
    sel.value = opt.dataset.value;
    sel.dispatchEvent(new Event("change"));
    closeCombos();
    btn.focus();
  });
  sel.addEventListener("change", () => paintCombo(root));
}

document.addEventListener("mousedown", (e) => {
  if (!e.target.closest(".combo")) closeCombos();
});

// pywebview easy_drag слушает mousedown на window и тянет окно. В полях ввода это
// съедало выделение мышью — гасим всплытие, поведение самого поля остаётся.
document.addEventListener("mousedown", (e) => {
  if (e.target.closest("input, textarea, .ask")) e.stopPropagation();
});

back.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  goHome();
});

window.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (updateLocked()) {
    e.preventDefault();
    return;
  }
  const openCombo = document.querySelector(".combo.open");
  if (openCombo) {
    e.preventDefault();
    closeCombos();
    openCombo.querySelector(".combo-btn")?.focus();
    return;
  }
  if (routeName() === "first") {
    e.preventDefault();
    return;
  }
  if (routeName() !== "home") {
    e.preventDefault();
    goHome();
  }
});

window.addEventListener("mousedown", (e) => {
  if (e.button === 3 || e.button === 4) e.preventDefault();
});
window.addEventListener("mouseup", (e) => {
  if (e.button === 3 && updateLocked()) {
    e.preventDefault();
    return;
  }
  if (e.button === 3 && routeName() !== "home" && routeName() !== "first") {
    e.preventDefault();
    goHome();
  }
});

function setOn(on) {
  power.setAttribute("aria-pressed", on ? "true" : "false");
  label.classList.toggle("on", on);
  label.textContent = on ? "Включено" : "Выключено";
  if (power.classList.contains("on") === on) return;
  power.classList.remove("on");
  requestAnimationFrame(() => {
    power.classList.toggle("on", on);
  });
}

const BUSY_LABEL = {
  start: "Включаю…",
  stop: "Выключаю…",
  reload: "Перезапуск…",
  test: "Проверяю…",
};

function setBusy(name) {
  busy = name;
  power.classList.add("busy");
  power.setAttribute("aria-busy", "true");
  if (island) island.classList.add("busy");
  label.textContent = BUSY_LABEL[name] || "Работаю…";
}

function clearBusy() {
  if (!busy) return;
  busy = "";
  power.classList.remove("busy");
  power.removeAttribute("aria-busy");
  if (island) island.classList.remove("busy");
  setOn(powerOn);
  if (serverRefresh) serverRefresh();
}

power.addEventListener("click", () => {
  if (busy) return;
  const next = !powerOn;
  setBusy(next ? "start" : "stop");
  call(next ? "start" : "stop");
});

document.querySelectorAll("[data-action]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const name = btn.dataset.action;
    if (name === "settings") {
      go("#/settings");
      return;
    }
    if (name === "guide") {
      go("#/guide");
      return;
    }
    if (busy) return;
    setBusy(name);
    call(name);
  });
});

document.getElementById("btn-close").addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  if (updateLocked()) return;
  call("quit");
});
document.getElementById("btn-min").addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  if (updateLocked()) return;
  const tray = document.getElementById("chk-tray");
  call(tray && !tray.checked ? "minimize" : "hide");
});

const DEFAULT_LINKS = [
  "x.ai",
  "grok.com",
  "openai.com",
  "chatgpt.com",
  "oaistatic.com",
  "oaiusercontent.com",
  "claude.ai",
  "anthropic.com",
  "pornhub.com",
  "pornhub.org",
  "pornhubpremium.com",
  "phncdn.com",
  "rncdn7.com",
  "cursor.sh",
  "cursor.com",
  "cursor-cdn.com",
  "cursorapi.com",
  "cursorvm.com",
  "anysphere.com",
  "anysphere.co",
  "oculus.com",
  "oculuscdn.com",
  "oculusvr.com",
  "meta.com",
  "facebook.com",
  "facebook-hardware.com",
  "fbcdn.net",
  "fbsbx.com",
  "instagram.com",
  "cdninstagram.com",
];

function parseLinks(raw) {
  const seen = new Set();
  const out = [];
  String(raw || "")
    .split(/[,;\r\n]+/)
    .forEach((part) => {
      const item = part.trim();
      if (!item || item.startsWith("#")) return;
      if (seen.has(item)) return;
      seen.add(item);
      out.push(item);
    });
  return out;
}

function formatLinksCsv(list) {
  return list.join(", ");
}

function formatLinksExport(list) {
  return ["# eblit-links v1", "# one suffix per line", ...list].join("\n");
}

function bindLinks() {
  const input = document.getElementById("links-input");
  const btnExport = document.getElementById("btn-links-export");
  const btnImport = document.getElementById("btn-links-import");
  if (!input && !btnExport && !btnImport) return;
  let saved = "";

  async function loadLinks() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.links || !input) return;
    try {
      const data = await api.links();
      if (data && data.ok && Array.isArray(data.links) && data.links.length) {
        input.value = formatLinksCsv(data.links);
        saved = input.value;
        return;
      }
    } catch (err) {
      /* ignore */
    }
    if (!parseLinks(input.value).length) {
      input.value = formatLinksCsv(DEFAULT_LINKS);
    }
  }

  if (input && !parseLinks(input.value).length) {
    input.value = formatLinksCsv(DEFAULT_LINKS);
  }

  // Поле — источник правды для config.json: пишем по уходу из поля, без перезапуска.
  async function saveLinks() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.set_links || !input) return;
    const list = parseLinks(input.value);
    if (!list.length) return;
    const text = formatLinksCsv(list);
    if (text === saved) return;
    try {
      const result = await api.set_links(list);
      if (result && result.ok) saved = text;
    } catch (err) {
      /* ignore */
    }
  }

  if (input) {
    input.addEventListener("change", saveLinks);
    input.addEventListener("blur", saveLinks);
  }

  if (btnExport) {
    btnExport.addEventListener("click", async () => {
      const list = input ? parseLinks(input.value) : [];
      const text = formatLinksExport(list);
      try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) {
          btnExport.title = "Буфер недоступен";
          return;
        }
        await navigator.clipboard.writeText(text);
        btnExport.title = "Скопировано";
      } catch (err) {
        btnExport.title = "Ошибка буфера";
      }
    });
  }

  if (btnImport) {
    btnImport.addEventListener("click", async () => {
      try {
        if (!navigator.clipboard || !navigator.clipboard.readText) {
          btnImport.title = "Буфер недоступен";
          return;
        }
        const text = await navigator.clipboard.readText();
        const list = parseLinks(text);
        if (!list.length) {
          btnImport.title = "Пустой буфер";
          return;
        }
        if (input) input.value = formatLinksCsv(list);
        btnImport.title = "Импортировано";
      } catch (err) {
        btnImport.title = "Ошибка буфера";
      }
    });
  }

  return loadLinks;
}

const PROBE_SECONDS = [10, 30, 60, 300, 900, 3600];
const PROBE_PRESET = [
  { n: 10, u: "s" },
  { n: 30, u: "s" },
  { n: 1, u: "m" },
  { n: 5, u: "m" },
  { n: 15, u: "m" },
  { n: 1, u: "h" },
];
const UNIT_SEC = { s: 1, m: 60, h: 3600 };

function clampProbeIndex(n) {
  const i = Math.round(Number(n));
  if (!Number.isFinite(i)) return 0;
  return Math.min(5, Math.max(0, i));
}

function nearestProbeIndex(sec) {
  let best = 0;
  let dist = Infinity;
  for (let i = 0; i < PROBE_SECONDS.length; i += 1) {
    const d = Math.abs(PROBE_SECONDS[i] - sec);
    if (d < dist) {
      dist = d;
      best = i;
    }
  }
  return best;
}

function bindProbe() {
  const seg = document.getElementById("probe-seg");
  const thumb = document.getElementById("probe-thumb");
  const num = document.getElementById("probe-num");
  const unit = document.getElementById("probe-unit");
  if (!seg && !num) return;

  let index = 1;

  function setThumb(i) {
    index = clampProbeIndex(i);
    probeSec = PROBE_SECONDS[index];
    armTick();
    if (thumb && seg) {
      const w = seg.clientWidth;
      const dpr = window.devicePixelRatio || 1;
      const x = w ? Math.round(((index + 0.5) / 6) * w * dpr) / dpr : 0;
      thumb.style.left = `${x}px`;
      seg.querySelectorAll(".seg-dots i").forEach((dot, n) => {
        dot.hidden = n === index;
      });
    }
    if (seg) seg.setAttribute("aria-valuenow", String(index));
  }

  function writePreset(i) {
    const p = PROBE_PRESET[clampProbeIndex(i)];
    if (num) num.value = String(p.n);
    if (unit) unit.value = p.u;
    const unitCombo = document.getElementById("probe-unit-combo");
    if (unitCombo) paintCombo(unitCombo);
  }

  function fieldsToSec() {
    const n = Number(String(num ? num.value : "").replace(",", ".").trim());
    if (!Number.isFinite(n) || n < 0) return null;
    const u = unit ? unit.value : "s";
    return Math.round(n * (UNIT_SEC[u] || 1));
  }

  function persistProbe() {
    const api = window.pywebview && window.pywebview.api;
    if (api && api.set_probe_sec) api.set_probe_sec(probeSec);
  }

  function commitFields() {
    const sec = fieldsToSec();
    if (sec === null) {
      writePreset(index);
      return;
    }
    setThumb(nearestProbeIndex(sec));
    persistProbe();
  }

  function applyFromSeg(clientX, writeFields) {
    const box = seg.getBoundingClientRect();
    const t = box.width ? Math.min(1, Math.max(0, (clientX - box.left) / box.width)) : 0;
    setThumb(t >= 1 ? 5 : Math.floor(t * 6));
    if (writeFields) {
      writePreset(index);
      persistProbe();
    }
  }

  setThumb(1);
  writePreset(1);
  if (seg && typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => setThumb(index)).observe(seg);
  }

  if (seg) {
    const drag = (e) => applyFromSeg(e.clientX, true);
    seg.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      seg.setPointerCapture(e.pointerId);
      applyFromSeg(e.clientX, true);
    });
    seg.addEventListener("pointermove", (e) => {
      if (!seg.hasPointerCapture(e.pointerId)) return;
      applyFromSeg(e.clientX, true);
    });
    seg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowUp") {
        e.preventDefault();
        setThumb(index + 1);
        writePreset(index);
        persistProbe();
      }
      if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
        e.preventDefault();
        setThumb(index - 1);
        writePreset(index);
        persistProbe();
      }
    });
  }

  if (num) {
    num.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        commitFields();
        num.blur();
      }
    });
    num.addEventListener("blur", commitFields);
  }
  if (unit) unit.addEventListener("change", commitFields);

  function applySaved(sec) {
    const n = Number(sec);
    if (!Number.isFinite(n) || n < 0) return;
    setThumb(nearestProbeIndex(n));
    writePreset(index);
  }

  return applySaved;
}

const FIRST_KEY = "eblit-first";

function seenFirst() {
  try {
    return localStorage.getItem(FIRST_KEY) === "1";
  } catch (err) {
    return true;
  }
}

function markFirst() {
  try {
    localStorage.setItem(FIRST_KEY, "1");
  } catch (err) {
    /* private mode — покажем снова */
  }
}

function firstSay(text) {
  const el = document.getElementById("first-msg");
  if (!el) return;
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = text;
}

async function paintFirst() {
  const api = window.pywebview && window.pywebview.api;
  const need = document.getElementById("first-need-sub");
  const have = document.getElementById("first-have-sub");
  const input = document.getElementById("first-sub");
  let nodes = [];
  try {
    const data = api && api.nodes ? await api.nodes() : null;
    nodes = data && Array.isArray(data.nodes) ? data.nodes : [];
  } catch (err) {
    nodes = [];
  }
  const empty = !nodes.length;
  if (need) need.hidden = !empty;
  if (have) have.hidden = empty;
  if (empty && input && api && api.sub_get) {
    try {
      const sub = await api.sub_get();
      if (sub && sub.url) input.value = sub.url;
    } catch (err) {
      /* ignore */
    }
  }
}

function bindFirst() {
  const btn = document.getElementById("btn-first-go");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    if (busy) return;
    const api = window.pywebview && window.pywebview.api;
    const need = document.getElementById("first-need-sub");
    const input = document.getElementById("first-sub");
    firstSay("");
    if (need && !need.hidden) {
      const url = input ? input.value.trim() : "";
      if (!url) {
        firstSay("нужна ссылка подписки");
        if (input) input.focus();
        return;
      }
      if (!api || !api.sub_set) {
        firstSay("не удалось сохранить ссылку");
        return;
      }
      try {
        const saved = await api.sub_set(url);
        if (!saved || !saved.ok) {
          firstSay((saved && saved.why) || "нужен https://");
          return;
        }
      } catch (err) {
        firstSay("не удалось сохранить ссылку");
        return;
      }
    }
    btn.disabled = true;
    markFirst();
    go("#/");
    if (powerOn) return;
    setBusy("start");
    await call("start");
  });
}

const STAR_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6 14.2 8.7l5.6.8-4 3.94.95 5.56L12 16.5l-4.75 2.5.95-5.56-4-3.94 5.6-.8z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>';
const STAR_SVG_ON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6 14.2 8.7l5.6.8-4 3.94.95 5.56L12 16.5l-4.75 2.5.95-5.56-4-3.94 5.6-.8z" fill="currentColor" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>';

function bindServers() {
  const parseApi = window.EblitNodeParse;
  const list = document.getElementById("server-list");
  const msg = document.getElementById("server-msg");
  const sel = document.getElementById("sel-node");
  const combo = document.getElementById("node-combo");
  const paste = document.getElementById("node-paste");
  const composer = document.getElementById("node-composer");
  const btnCompose = document.getElementById("btn-node-compose");
  const btnPing = document.getElementById("btn-node-ping");
  const subUrl = document.getElementById("sub-url");
  const btnSub = document.getElementById("btn-sub-refresh");
  const btnParse = document.getElementById("btn-node-parse");
  const btnAdd = document.getElementById("btn-node-add");
  const btnCancel = document.getElementById("btn-node-cancel");
  const preview = document.getElementById("node-preview");
  if (!list) return null;

  let pending = [];
  let waits = 0;
  let selWanted = "auto";
  let pingByTag = {};
  let pinging = false;
  let subbing = false;
  let savedSub = "";

  function say(text, ok) {
    if (!msg) return;
    if (!text) {
      msg.hidden = true;
      msg.textContent = "";
      msg.classList.remove("ok");
      return;
    }
    msg.hidden = false;
    msg.textContent = text;
    msg.classList.toggle("ok", !!ok);
  }

  function clearPreview() {
    pending = [];
    if (preview) {
      preview.hidden = true;
      preview.replaceChildren();
    }
    if (btnAdd) btnAdd.hidden = true;
  }

  function setComposerOpen(open) {
    if (composer) composer.hidden = !open;
    if (open && paste) paste.focus();
  }

  function closeComposer() {
    clearPreview();
    if (paste) paste.value = "";
    setComposerOpen(false);
  }

  function mixGreyToLive(hex, t) {
    const n = hex.replace("#", "");
    const live = [parseInt(n.slice(0, 2), 16), parseInt(n.slice(2, 4), 16), parseInt(n.slice(4, 6), 16)];
    const grey = [255, 255, 255];
    const ga = 0.18;
    const m = grey.map((v, i) => Math.round(v + (live[i] - v) * t));
    const a = +(ga + (1 - ga) * t).toFixed(3);
    return `rgba(${m[0]}, ${m[1]}, ${m[2]}, ${a})`;
  }

  function paintDot(dot, ping) {
    if (!dot) return;
    if (!ping) {
      dot.style.background = "";
      dot.style.boxShadow = "";
      dot.removeAttribute("title");
      return;
    }
    if (!ping.live) {
      dot.style.background = "";
      dot.style.boxShadow = "";
      dot.title = ping.why || "нет ответа";
      return;
    }
    const lives = Object.values(pingByTag).filter((n) => n && n.live);
    const root = document.documentElement;
    const live = getComputedStyle(root).getPropertyValue("--live").trim() || "#8aaeb4";
    let t = 1;
    if (lives.length > 1) {
      const times = lives.map((n) => n.ms);
      const minMs = Math.min(...times);
      const maxMs = Math.max(...times);
      if (maxMs > minMs) {
        t = 1 - (ping.ms - minMs) / (maxMs - minMs);
      }
    }
    dot.style.background = mixGreyToLive(live, t);
    dot.style.boxShadow = "none";
    dot.title = `${ping.ms} мс`;
  }

  function applyLamps(payload) {
    const nodes = Array.isArray(payload) ? payload : payload && payload.nodes;
    if (Array.isArray(nodes)) {
      pingByTag = {};
      nodes.forEach((n) => {
        if (n && n.tag) pingByTag[n.tag] = n;
      });
      pinging = false;
      if (btnPing) btnPing.classList.remove("spin");
      if (payload && !Array.isArray(payload) && payload.ok === false && payload.why) {
        say(payload.why, false);
      }
    }
    list.querySelectorAll("li").forEach((li) => {
      paintDot(li.querySelector(".geo-dot"), pingByTag[li.dataset.tag]);
    });
  }

  function row(n) {
    const li = document.createElement("li");
    li.classList.toggle("on", !!n.current);
    li.dataset.tag = n.tag;
    const dot = document.createElement("span");
    dot.className = "geo-dot";
    const body = document.createElement("span");
    body.className = "geo-body";
    const title = document.createElement("span");
    title.className = "geo-title";
    const name = document.createElement("span");
    name.className = "geo-name";
    name.textContent = n.tag;
    const now = document.createElement("span");
    now.className = "geo-now";
    now.setAttribute("aria-hidden", "true");
    now.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9.2 6.4 15.6 12 9.2 17.6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    title.append(name, now);
    body.appendChild(title);
    if (n.host) {
      const host = document.createElement("span");
      host.className = "geo-host";
      host.textContent = n.host;
      body.appendChild(host);
    }
    const ops = document.createElement("div");
    ops.className = "node-ops";
    const fav = document.createElement("button");
    fav.type = "button";
    fav.className = "node-ico node-fav";
    fav.dataset.tag = n.tag;
    const favOn = !!n.favorite;
    fav.setAttribute("aria-pressed", favOn ? "true" : "false");
    fav.setAttribute("aria-label", favOn ? "Снять избранное" : "Избранное для первого живого");
    fav.title = favOn ? "Снять избранное" : "«Первый живой» начинает с этого сервера";
    fav.classList.toggle("on", favOn);
    fav.innerHTML = favOn ? STAR_SVG_ON : STAR_SVG;
    const drop = document.createElement("button");
    drop.type = "button";
    drop.className = "node-ico node-drop";
    drop.dataset.tag = n.tag;
    drop.setAttribute("aria-label", "Удалить");
    drop.title = "Удалить из config.json";
    drop.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.2 6.2 17.8 17.8M17.8 6.2 6.2 17.8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
    ops.append(fav, drop);
    li.append(dot, body, ops);
    if (n.current) li.title = "сейчас через этот сервер";
    paintDot(dot, pingByTag[n.tag]);
    return li;
  }

  function note(data) {
    if (!data.nodes.length) return "в config.json нет vless-серверов";
    if (!data.selected && !data.auto) return "сервер не выбран";
    if (data.pick && data.pick.tag && data.selected && data.pick.tag !== data.selected) {
      return `проверка выбрала ${data.pick.tag}, в конфиге ${data.selected}`;
    }
    return "";
  }

  function paintSelect(data, nodes) {
    if (!sel) return;
    sel.replaceChildren();
    const auto = document.createElement("option");
    auto.value = "auto";
    auto.textContent = "Первый живой";
    sel.appendChild(auto);
    nodes.forEach((n) => {
      const opt = document.createElement("option");
      opt.value = n.tag;
      opt.textContent = n.tag;
      sel.appendChild(opt);
    });
    const tags = new Set(nodes.map((n) => n.tag));
    selWanted = !data.auto && data.selected && tags.has(data.selected) ? data.selected : "auto";
    sel.value = selWanted;
    if (combo) rebuildComboMenu(combo);
  }

  async function refresh() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.nodes) {
      if (waits < 6) {
        waits += 1;
        window.setTimeout(refresh, 500);
      }
      return;
    }
    waits = 0;
    let data = null;
    try {
      data = await api.nodes();
    } catch (err) {
      data = null;
    }
    if (!data || !data.ok) {
      list.replaceChildren();
      say(data && data.why ? `config.json не прочитан: ${data.why}` : "config.json не прочитан");
      return;
    }
    const nodes = Array.isArray(data.nodes) ? data.nodes : [];
    list.replaceChildren(...nodes.map(row));
    paintSelect(data, nodes);
    say(note({ ...data, nodes }));
    if (subUrl && !subUrl.value) await loadSub();
  }

  async function loadSub() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.sub_get || !subUrl) return;
    try {
      const data = await api.sub_get();
      if (data && data.url) {
        subUrl.value = data.url;
        savedSub = data.url;
      }
    } catch (err) {
      /* ignore */
    }
  }

  async function saveSub() {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.sub_set || !subUrl) return false;
    const url = subUrl.value.trim();
    if (url === savedSub) return true;
    try {
      const result = await api.sub_set(url);
      if (result && result.ok) {
        savedSub = url;
        return true;
      }
      say((result && result.why) || "не удалось сохранить ссылку", false);
      return false;
    } catch (err) {
      say("не удалось сохранить ссылку", false);
      return false;
    }
  }

  function paintSub(data, opts) {
    const quiet = !!(opts && opts.quiet);
    subbing = false;
    if (btnSub) btnSub.classList.remove("spin");
    if (!data) return;
    if (!quiet) {
      if (data.ok === false) {
        say(data.why || "не удалось обновить подписку", false);
      } else if (data.skipped) {
        say(data.why || "нет ссылки подписки", false);
      } else {
        const n = Array.isArray(data.nodes) ? data.nodes.length : 0;
        say(n ? `список обновлён: ${n}` : "список обновлён", true);
      }
    }
    if (data.nodes) {
      const nodes = Array.isArray(data.nodes) ? data.nodes : [];
      list.replaceChildren(...nodes.map(row));
      paintSelect(data, nodes);
      applyLamps();
    } else {
      refresh();
    }
  }

  function paintStar(btn, on) {
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.setAttribute("aria-label", on ? "Снять избранное" : "Избранное для первого живого");
    btn.title = on ? "Снять избранное" : "«Первый живой» начинает с этого сервера";
    btn.classList.toggle("on", on);
    btn.innerHTML = on ? STAR_SVG_ON : STAR_SVG;
  }

  list.addEventListener("click", async (e) => {
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;

    // Избранное — только файл рядом с config, без перезапуска: красим строку на месте.
    const star = e.target.closest(".node-fav");
    if (star) {
      const on = star.getAttribute("aria-pressed") === "true";
      paintStar(star, !on);
      if (!on) {
        list.querySelectorAll(".node-fav").forEach((other) => {
          if (other !== star && other.getAttribute("aria-pressed") === "true") paintStar(other, false);
        });
      }
      try {
        const result = await api.set_favorite(on ? null : star.dataset.tag);
        if (result && !result.ok) {
          paintStar(star, on);
          say(result.why || "не удалось сохранить избранное", false);
        }
      } catch (err) {
        paintStar(star, on);
        say("не удалось сохранить избранное", false);
      }
      return;
    }

    const drop = e.target.closest(".node-drop");
    if (!drop) return;
    const li = drop.closest("li");
    const wasCurrent = !!(li && li.classList.contains("on"));
    try {
      const result = await api.remove_node(drop.dataset.tag);
      if (result && !result.ok) {
        say(result.why || "не удалось удалить", false);
        return;
      }
      await refresh();
      if (wasCurrent) say("удалён текущий — сменится после перезапуска", true);
    } catch (err) {
      say("не удалось удалить", false);
    }
  });

  if (sel) {
    sel.addEventListener("change", async () => {
      const want = sel.value;
      if (want === selWanted) return;
      const api = window.pywebview && window.pywebview.api;
      if (!api || !api.select_node) {
        sel.value = selWanted;
        if (combo) paintCombo(combo);
        return;
      }
      const prev = selWanted;
      selWanted = want;
      list.querySelectorAll("li").forEach((li) => {
        li.classList.toggle("on", want !== "auto" && li.dataset.tag === want);
      });
      if (combo) paintCombo(combo);
      try {
        const result = await api.select_node(want);
        if (result && result.ok === false) {
          selWanted = prev;
          sel.value = prev;
          if (combo) paintCombo(combo);
          say(result.why || "не удалось выбрать", false);
          await refresh();
          return;
        }
        if (result && result.nodes) {
          const nodes = Array.isArray(result.nodes) ? result.nodes : [];
          list.replaceChildren(...nodes.map(row));
          paintSelect(result, nodes);
          applyLamps();
          say(note({ ...result, nodes }));
        }
        if (result && result.restart) {
          setBusy("reload");
          armPull();
        }
      } catch (err) {
        selWanted = prev;
        sel.value = prev;
        if (combo) paintCombo(combo);
        say("не удалось выбрать", false);
      }
    });
  }

  if (btnCompose) {
    btnCompose.addEventListener("click", () => {
      say("", false);
      setComposerOpen(true);
    });
  }

  if (btnPing) {
    btnPing.addEventListener("click", async () => {
      if (pinging) return;
      const api = window.pywebview && window.pywebview.api;
      if (!api || !api.ping_nodes) return;
      pinging = true;
      btnPing.classList.add("spin");
      try {
        const res = await api.ping_nodes();
        if (res && res.ignored) {
          pinging = false;
          btnPing.classList.remove("spin");
          return;
        }
        if (res && res.kind === "ping") applyLamps(res);
        if (res && res.pending) armPull();
      } catch (err) {
        pinging = false;
        btnPing.classList.remove("spin");
        say("не удалось проверить серверы", false);
      }
    });
  }

  if (subUrl) {
    subUrl.addEventListener("change", saveSub);
    subUrl.addEventListener("blur", saveSub);
  }

  if (btnSub) {
    btnSub.addEventListener("click", async () => {
      if (subbing) return;
      const api = window.pywebview && window.pywebview.api;
      if (!api || !api.sub_refresh) return;
      const saved = await saveSub();
      if (!saved) return;
      subbing = true;
      btnSub.classList.add("spin");
      try {
        const res = await api.sub_refresh();
        if (res && res.ignored) {
          subbing = false;
          btnSub.classList.remove("spin");
          return;
        }
        if (res && res.kind === "sub") paintSub(res);
        if (res && res.pending) armPull();
      } catch (err) {
        subbing = false;
        btnSub.classList.remove("spin");
        say("не удалось обновить подписку", false);
      }
    });
  }

  if (btnParse && parseApi) {
    btnParse.addEventListener("click", () => {
      const raw = paste ? paste.value.trim() : "";
      if (/^(https?:\/\/|happ:\/\/)/i.test(raw) && !/vless:\/\//i.test(raw)) {
        clearPreview();
        say("это ссылка подписки — вставьте её в поле выше", false);
        return;
      }
      const r = parseApi.parseNodes(paste ? paste.value : "");
      if (!r.ok) {
        clearPreview();
        say(r.error, false);
        return;
      }
      pending = r.nodes;
      say("", false);
      if (preview) {
        preview.hidden = false;
        preview.replaceChildren(
          ...parseApi.previewRows(pending).map((item) => {
            const art = document.createElement("article");
            const title = document.createElement("strong");
            title.textContent = item.name;
            const meta = document.createElement("div");
            meta.textContent = `${item.host} · SNI ${item.sni} · flow ${item.flow}`;
            const secrets = document.createElement("div");
            secrets.textContent = `uuid ${item.uuid} · pbk ${item.pbk}`;
            art.append(title, meta, secrets);
            return art;
          })
        );
      }
      if (btnAdd) btnAdd.hidden = false;
    });
  }

  if (btnAdd) {
    btnAdd.addEventListener("click", async () => {
      if (!pending.length) {
        say("сначала разбери вставку", false);
        return;
      }
      const api = window.pywebview && window.pywebview.api;
      if (!api || !api.add_node) return;
      let added = 0;
      let lastWhy = "";
      for (const n of pending) {
        try {
          const result = await api.add_node(n);
          if (result && result.ok) added += 1;
          else lastWhy = (result && result.why) || "ошибка";
        } catch (err) {
          lastWhy = String(err);
        }
      }
      if (!added) {
        say(lastWhy || "не добавилось", false);
        return;
      }
      closeComposer();
      refresh();
      say(added === 1 ? "сервер добавлен" : `добавлено: ${added}`, true);
    });
  }

  if (btnCancel) {
    btnCancel.addEventListener("click", () => {
      closeComposer();
      say("", false);
    });
  }

  applyPing = applyLamps;
  applySub = paintSub;
  loadSub();
  return refresh;
}

document.querySelectorAll(".combo").forEach(mountCombo);
linksLoader = bindLinks();
const applySavedProbe = bindProbe();
serverRefresh = bindServers();
if (serverRefresh) serverRefresh();
bindFirst();

const chkTick = document.getElementById("chk-tick");
if (chkTick) chkTick.addEventListener("change", armTick);

const chkAuto = document.getElementById("chk-autostart");
if (chkAuto) {
  chkAuto.addEventListener("change", () => {
    call("set_autostart", chkAuto.checked);
  });
}

const chkReconnect = document.getElementById("chk-reconnect");
function sendAutoreconnect() {
  const api = window.pywebview && window.pywebview.api;
  if (api && api.set_autoreconnect) api.set_autoreconnect(chkReconnect.checked);
}
if (chkReconnect) {
  try {
    if (localStorage.getItem("eblit-reconnect") === "0") chkReconnect.checked = false;
  } catch (err) {
    /* ignore */
  }
  chkReconnect.addEventListener("change", () => {
    try {
      localStorage.setItem("eblit-reconnect", chkReconnect.checked ? "1" : "0");
    } catch (err) {
      /* ignore */
    }
    sendAutoreconnect();
  });
}

const chkLan = document.getElementById("chk-lan");
function paintLan(data) {
  if (!chkLan || !data) return;
  const on = !!data.on;
  chkLan.checked = on;
  chkLan.title = data.why || "";
  const field = document.getElementById("lan-field");
  const addr = document.getElementById("lan-addr");
  const hint = document.getElementById("lan-hint");
  if (field) field.hidden = !on;
  if (hint) hint.hidden = !on;
  if (!addr) return;
  // Адрес не нашли (только TUN / нет сети) — порт всё равно называем.
  addr.value = data.address ? `${data.address}:${data.port}` : on ? `порт ${data.port}` : "";
}
if (chkLan) {
  chkLan.addEventListener("change", async () => {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.set_lan) return;
    if (busy) {
      chkLan.checked = !chkLan.checked;
      return;
    }
    const res = await api.set_lan(chkLan.checked);
    paintLan(res);
    // Питание включено — подключение уже перезапускается, кнопка не должна врать.
    if (res && res.restart) {
      setBusy("reload");
      armPull();
    }
  });
}

const chkTray = document.getElementById("chk-tray");
if (chkTray) {
  try {
    const raw = localStorage.getItem("eblit-tray");
    if (raw === "0") chkTray.checked = false;
    if (raw === "1") chkTray.checked = true;
  } catch (err) {
    /* ignore */
  }
  chkTray.addEventListener("change", () => {
    try {
      localStorage.setItem("eblit-tray", chkTray.checked ? "1" : "0");
    } catch (err) {
      /* ignore */
    }
  });
}

const verBtn = document.getElementById("ver");
const askUpdate = document.getElementById("ask-update");
const askUpdateText = document.getElementById("ask-update-text");
const askUpdateGo = document.getElementById("ask-update-go");
let verMode = "idle";

function updateLocked() {
  return !!(askUpdate && !askUpdate.hidden);
}

function lockUpdate(data) {
  if (!askUpdate) return;
  const latest = (data && data.latest) || "";
  if (askUpdateText) {
    askUpdateText.textContent = latest
      ? `Доступна ${latest}. Обновить?`
      : "Доступна новая версия. Обновить?";
  }
  askUpdate.hidden = false;
  paintUpdateAsk("new", data);
}

function paintUpdateAsk(mode, data) {
  if (!updateLocked() || !askUpdateGo) return;
  if (mode === "go") {
    askUpdateGo.disabled = true;
    askUpdateGo.textContent = "Ставлю…";
    return;
  }
  askUpdateGo.disabled = false;
  askUpdateGo.textContent = mode === "fail" ? "Повторить" : "Обновить";
  if (mode === "fail" && askUpdateText) {
    askUpdateText.textContent = (data && data.why) || "не вышло, попробуй ещё";
  }
}

async function startUpdate() {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.install_update) return;
  if (verMode === "wait" || verMode === "go") return;
  setVer("go", { current: verBtn && verBtn.dataset.current });
  paintUpdateAsk("go");
  const res = await api.install_update();
  applyStack(res);
  if (res && res.pending) armPull();
}

function setVer(mode, data) {
  verMode = mode;
  if (!verBtn) return;
  const current = (data && data.current) || verBtn.dataset.current || "1.0.0";
  verBtn.dataset.current = current;
  verBtn.classList.toggle("fresh", mode === "new");
  verBtn.classList.toggle("busy", mode === "wait" || mode === "go");
  if (mode === "wait") {
    verBtn.textContent = "…";
    verBtn.title = "спрашиваю GitHub";
    return;
  }
  if (mode === "go") {
    verBtn.textContent = "ставлю";
    verBtn.title = data && data.why ? data.why : "запускаю установщик";
    return;
  }
  if (mode === "new") {
    verBtn.textContent = data.latest;
    verBtn.title = `поставить ${data.latest}`;
    return;
  }
  verBtn.textContent = current;
  if (mode === "same") verBtn.title = "это последняя";
  else if (mode === "fail") verBtn.title = (data && data.why) || "не достучался";
  else verBtn.title = "проверить обновление";
}
if (askUpdateGo) {
  askUpdateGo.addEventListener("click", () => {
    startUpdate();
  });
}
if (verBtn) {
  verBtn.addEventListener("click", async () => {
    if (updateLocked()) {
      startUpdate();
      return;
    }
    const api = window.pywebview && window.pywebview.api;
    if (!api) return;
    if (verMode === "wait" || verMode === "go") return;
    if (verMode === "new") {
      startUpdate();
      return;
    }
    if (!api.check_update) return;
    setVer("wait", { current: verBtn.dataset.current });
    const res = await api.check_update();
    if (!res) {
      setVer("fail", { why: "нет ответа" });
      return;
    }
    if (res.newer) {
      setVer("new", res);
      lockUpdate(res);
    } else {
      setVer(res.ok === false ? "fail" : "same", res);
    }
  });
}

window.addEventListener("pywebviewready", async () => {
  const api = window.pywebview && window.pywebview.api;
  if (api && api.get_probe_sec && applySavedProbe) {
    const saved = await api.get_probe_sec();
    if (saved && saved.sec != null) applySavedProbe(saved.sec);
  }
  armPull();
  armSyncPower();
  const st = await call("status");
  if (api && api.sub_pull) {
    try {
      const sub = await api.sub_pull();
      if (applySub && sub && !sub.skipped) applySub(sub, { quiet: true });
    } catch (err) {
      /* нет сети — старый список, подключение всё равно */
    }
  }
  if (!seenFirst()) {
    await paintFirst();
    go("#/first");
  } else if (st && st.want_on && !st.power) {
    setBusy("start");
    await call("start");
  }
  if (serverRefresh) serverRefresh();
  if (!api) return;
  if (api.version) {
    const ver = await api.version();
    if (ver && ver.version) setVer("idle", { current: ver.version });
  }
  if (api.check_update_bg) {
    api.check_update_bg();
    armPull();
  }
  if (chkReconnect) sendAutoreconnect();
  if (api.lan_state) paintLan(await api.lan_state());
  if (!api.autostart_state) return;
  const auto = await api.autostart_state();
  if (chkAuto && auto) chkAuto.checked = !!auto.on;
});
