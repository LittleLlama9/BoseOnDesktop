"use strict";

// ---- device/API bridge with a mock fallback for headless screenshots ----
// pywebview injects window.pywebview.api asynchronously (after the
// 'pywebviewready' event, which fires AFTER DOMContentLoaded), so we must NOT
// latch a boolean at load time -- check dynamically every call and wait for
// the bridge in init(). In a plain browser (headless capture) the bridge never
// arrives and we fall back to mock data.
function hasApi() { return !!(window.pywebview && window.pywebview.api); }

function waitForApi(timeout) {
  timeout = timeout || 2500;
  if (hasApi()) return Promise.resolve(true);
  return new Promise((res) => {
    let done = false;
    const fin = (v) => { if (!done) { done = true; res(v); } };
    window.addEventListener("pywebviewready", () => fin(true), { once: true });
    setTimeout(() => fin(hasApi()), timeout);
  });
}

const MOCK_STATE = {
  connected: true, error: "", battery: 50, mode_idx: 3, mode_name: "Focus",
  editable: true, cnc_app: 5, spatial: 0, anc: false,
  sidetone: "medium", auto_off: 0, auto_pause: false, auto_answer: true, multipoint: true,
  modes: [
    { idx: 0, name: "Quiet", editable: false, configured: true, cnc_app: 10, spatial: 0, anc: true, active: false },
    { idx: 1, name: "Aware", editable: false, configured: true, cnc_app: 0, spatial: 0, anc: false, active: false },
    { idx: 2, name: "Immersion", editable: false, configured: true, cnc_app: 8, spatial: 2, anc: true, active: false },
    { idx: 3, name: "Home", editable: true, configured: true, cnc_app: 5, spatial: 0, anc: false, active: true },
    { idx: 4, name: "Focus", editable: true, configured: true, cnc_app: 6, spatial: 0, anc: false, active: false },
  ],
};
const MOCK_EXTRAS = { name: "Bose QC Ultra Headphones", firmware: "1.6.7",
  paired: [{ mac: "AA:BB", name: "HOOPOE" }, { mac: "CC:DD", name: "Matthew's iPhone" }],
  eq: { bass: -3, mid: 0, treble: 0 }, prompts: { enabled: true, language: "English" }, error: "" };
const MOCK_APP = { speak_mode: true, autostart: false,
  hotkeys: { mode_quiet: "Ctrl+Alt+Q", mode_aware: "Ctrl+Alt+W", mode_immersion: "Ctrl+Alt+E", mode_cycle: "Ctrl+Alt+N" } };
const MOCK_SHORTCUT_OPTS = [
  { action: "BatteryLevel", label: "Hear Battery Level", icon: "battery",
    desc: "A voice prompt announces the battery level of your headphones." },
  { action: "SpatialAudioMode", label: "Change Immersive Audio", icon: "immersion",
    desc: "Cycle through Still, Motion, and Off settings." },
  { action: "VPA", label: "Access Your Voice Assistant", icon: "vpa",
    desc: "Use voice control on your mobile device." },
  { action: "SpotifyGo", label: "Spotify", icon: "spotify",
    desc: "Use your shortcut to resume Spotify. Do it again to discover music you'll love. To set this shortcut, make sure your Spotify app is up to date." },
];
const MOCK_OPTIONS = { auto_off_minutes: [0, 5, 20, 40, 60, 180, 1440],
  sidetone_order: ["high", "medium", "low", "off"],
  sidetone_names: { 0: "off", 1: "high", 2: "medium", 3: "low" },
  spatial_labels: { 0: "Off", 1: "Still", 2: "Motion" } };

function api(method, ...args) {
  if (hasApi()) return window.pywebview.api[method](...args);
  // mock
  return new Promise((res) => {
    setTimeout(() => {
      if (method === "get_extras") res(JSON.parse(JSON.stringify(MOCK_EXTRAS)));
      else if (method === "get_app_settings") res(JSON.parse(JSON.stringify(MOCK_APP)));
      else if (method === "get_options") res(JSON.parse(JSON.stringify(MOCK_OPTIONS)));
      else if (method === "get_shortcut") res({ button: "Shortcut", event: "long_press",
        action: "SpotifyGo", enabled: true, last_action: "SpotifyGo",
        hint: "Touch and hold the volume strip on the right earcup to use your shortcut.",
        options: MOCK_SHORTCUT_OPTS });
      else if (method === "set_shortcut") res({ ok: true, action: args[0],
        enabled: args[0] !== "Disabled", last_action: args[0] !== "Disabled" ? args[0] : "SpotifyGo",
        options: MOCK_SHORTCUT_OPTS });
      else if (method === "get_tech_info") res({ model: "Bose QC Ultra Headphones (1st Gen)",
        firmware: "1.6.7", product_id: "0x4066", codename: "lonestarr", platform: "OTG-QCC-514x" });
      else if (method === "open_url") res({ ok: true });
      else if (method === "set_name") res({ ok: true });
      else if (method === "add_mode") {
        const nm = String(args[0] || "").trim();
        const used = MOCK_STATE.modes.map((m) => m.idx);
        let slot = 3; while (used.includes(slot)) slot++;
        MOCK_STATE.modes.forEach((m) => { m.active = false; });
        MOCK_STATE.modes.push({ idx: slot, name: nm, editable: true,
          configured: true, cnc_app: 10, spatial: 0, anc: true, active: true });
        MOCK_STATE.mode_idx = slot; MOCK_STATE.mode_name = nm;
        MOCK_STATE.editable = true; MOCK_STATE.cnc_app = 10;
        MOCK_STATE.spatial = 0; MOCK_STATE.anc = true;
        res(JSON.parse(JSON.stringify(MOCK_STATE)));
      }
      else res(JSON.parse(JSON.stringify(MOCK_STATE)));
    }, 40);
  });
}

// ---- icon injection ----
function paintIcons(root) {
  (root || document).querySelectorAll("[data-ico]").forEach((el) => {
    if (el.dataset.painted) return;
    const svg = window.ICONS[el.dataset.ico];
    if (svg) { el.innerHTML = svg; el.dataset.painted = "1"; }
  });
}

const MODE_ICON = { Quiet: "quiet", Aware: "aware", Immersion: "immersion",
  Home: "home", Focus: "focus", Commute: "commute", Music: "music",
  Outdoor: "outdoor", Relax: "relax", Run: "run", Walk: "walk",
  Workout: "workout" };
function iconForMode(name) { return MODE_ICON[name] || "modes"; }

function heroSub(s) {
  const parts = [];
  const cnc = s.cnc_app;  // app scale: 10 = full noise cancellation, 0 = fully aware
  if (cnc != null) {
    if (cnc >= 10) parts.push("Full Noise Cancellation");
    else if (cnc <= 0) parts.push("Fully Aware");
    else parts.push("Noise level " + cnc);
  }
  if (s.spatial) parts.push("Immersive");
  return parts.join(" \u00b7 ") || "Connected";
}

// ---- navigation ----
let current = "home";
function show(screen) {
  document.querySelectorAll(".screen").forEach((s) => {
    s.hidden = s.dataset.screen !== screen;
  });
  current = screen;
  if (screen === "bluetooth" || screen === "settings") loadExtras();
  if (screen === "eq") { loadExtras(); drawEq(); }
  if (screen === "shortcut") loadShortcut();
  if (screen === "prompts") loadPrompts();
  if (screen === "techinfo" || screen === "productupdate") loadTechInfo();
  if (screen === "rename") loadRename();
}

// ---- state + rendering ----
let STATE = null;
let OPTIONS = MOCK_OPTIONS;
let EXTRAS = null;

function batteryGlyph(pct) {
  const g = document.getElementById("batt-glyph");
  g.innerHTML = "<i></i>";
  g.querySelector("i").style.width = Math.max(0, Math.min(100, pct || 0)) * 0.24 + "px";
}

function render() {
  const s = STATE; if (!s) return;
  document.body.classList.toggle("disconnected", !s.connected);
  document.getElementById("batt-pct").textContent = (s.battery != null ? s.battery : "--") + "%";
  batteryGlyph(s.battery);

  // active-mode hero
  const activeMode = (s.modes || []).find((m) => m.active) || {};
  const heroName = s.mode_name || activeMode.name || "--";
  document.getElementById("hero-mode").textContent = heroName;
  const hb = document.getElementById("hero-badge");
  hb.dataset.ico = iconForMode(heroName);
  hb.dataset.painted = ""; paintIcons(hb.parentElement);
  document.getElementById("hero-sub").textContent = s.connected ? heroSub(s) : "";

  // modes list
  const list = document.getElementById("mode-list");
  list.innerHTML = "";
  (s.modes || []).filter((m) => m.name && m.name.toLowerCase() !== "none").forEach((m) => {
    const b = document.createElement("button");
    b.className = "mode-item" + (m.active ? " active" : "");
    b.innerHTML = `<span class="m-ico" data-ico="${iconForMode(m.name)}"></span>`
      + `<span class="m-name">${m.name}</span>`
      + (m.editable ? `<span class="m-dots" data-ico="dots"></span>` : "")
      + `<span class="m-star" data-ico="star"></span>`;
    // whole row = switch to this mode
    b.onclick = () => act("set_mode", m.idx);
    // "..." = switch to this mode (await the switch), then open its detail so
    // the detail screen (and its Delete button) always targets THIS mode.
    const dots = b.querySelector(".m-dots");
    if (dots) dots.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!m.active) {
        while (busy) await new Promise((r) => setTimeout(r, 40));
        busy = true;
        try {
          const st = await api("set_mode", m.idx);
          if (st && st.modes) STATE = st;
          if (st && st.error) toast(st.error);
        } finally { busy = false; }
      }
      render();
      show("noise");
    });
    // star = favorite (managed in the mobile app on 1st gen)
    const star = b.querySelector(".m-star");
    if (star) star.addEventListener("click", (e) => {
      e.stopPropagation();
      toast("Favorite modes are managed in the Bose mobile app.");
    });
    list.appendChild(b);
  });
  const add = document.createElement("div");
  add.className = "mode-add";
  add.innerHTML = `<button class="mode-add-btn" data-ico="plus"></button>`;
  add.querySelector(".mode-add-btn").onclick = () => {
    const inp = document.getElementById("newmode-input");
    if (inp) inp.value = "";
    show("newmode");
    if (inp) setTimeout(() => inp.focus(), 30);
  };
  list.appendChild(add);
  paintIcons(list);

  // noise / mode detail
  const active = (s.modes || []).find((m) => m.active) || {};
  document.getElementById("noise-mode-name").textContent = s.mode_name || active.name || "--";
  const badge = document.getElementById("noise-badge");
  badge.dataset.ico = iconForMode(s.mode_name || active.name);
  badge.dataset.painted = ""; paintIcons(badge.parentElement);
  const cnc = s.cnc_app != null ? s.cnc_app : 0;
  document.getElementById("nc-fill").style.width = (cnc / 10 * 100) + "%";
  const sl = document.getElementById("nc-slider");
  if (sl) sl.classList.toggle("locked", active.editable === false);
  const nlk = document.getElementById("nc-locked-note");
  if (nlk) nlk.hidden = active.editable !== false;
  buildTicks();
  const seg = document.getElementById("spatial-seg");
  seg.querySelectorAll("button").forEach((btn) => {
    btn.classList.toggle("active", Number(btn.dataset.val) === (s.spatial || 0));
  });
  document.getElementById("spatial-hint").textContent =
    "Immersive Audio is " + (OPTIONS.spatial_labels[s.spatial] || "Off").toLowerCase() + ".";

  // delete-mode (editable modes only; the detail screen always shows the
  // active mode, so this targets the active slot)
  const delBtn = document.getElementById("delete-mode-btn");
  if (delBtn) {
    wireDeleteBtn();
    if (active.editable && active.idx != null) {
      delBtn.hidden = false;
      delBtn.dataset.idx = active.idx;
      if (delBtn.dataset.arm !== "1") delBtn.textContent = "Delete Mode";
    } else {
      delBtn.hidden = true;
    }
  }

  // bluetooth
  const mp = document.getElementById("mp-toggle"); mp.checked = !!s.multipoint;

  // settings values
  const svName = OPTIONS.sidetone_names && Object.values ? capitalize(s.sidetone) : s.sidetone;
  document.getElementById("sv-val").textContent = capitalize(s.sidetone) || "--";
  document.getElementById("ao-val").textContent = autoOffLabel(s.auto_off);
  document.getElementById("oh-pause").checked = !!s.auto_pause;
  document.getElementById("oh-answer").checked = !!s.auto_answer;

  buildRadioLists();
}

function capitalize(x) { return x ? x[0].toUpperCase() + x.slice(1) : x; }

function wireDeleteBtn() {
  const b = document.getElementById("delete-mode-btn");
  if (!b || b.dataset.wired) return;
  b.dataset.wired = "1";
  b.addEventListener("click", () => {
    const idx = Number(b.dataset.idx);
    if (Number.isNaN(idx)) return;
    if (b.dataset.arm === "1") {
      clearTimeout(b._t);
      b.dataset.arm = ""; b.classList.remove("armed");
      b.textContent = "Delete Mode";
      // Safety: only delete the mode that is actually active/shown right now.
      const active = (STATE && STATE.modes || []).find((m) => m.active);
      if (!active || active.idx !== idx) {
        toast("Open the mode you want to delete first.");
        return;
      }
      act("delete_mode", idx).then(() => show("modes"));
    } else {
      b.dataset.arm = "1"; b.classList.add("armed");
      b.textContent = "Tap again to delete";
      clearTimeout(b._t);
      b._t = setTimeout(() => {
        b.dataset.arm = ""; b.classList.remove("armed");
        b.textContent = "Delete Mode";
      }, 3000);
    }
  });
}

function autoOffLabel(mins) {
  if (mins == null) return "--";
  const map = { 0: "Never", 5: "5 Minutes", 20: "20 Minutes", 40: "40 Minutes",
    60: "1 Hour", 180: "3 Hours", 1440: "24 Hours" };
  return map[mins] || (mins + " min");
}

function buildTicks() {
  const t = document.getElementById("nc-ticks");
  if (t.childElementCount) return;
  for (let i = 0; i < 11; i++) t.appendChild(document.createElement("i"));
}

function buildRadioLists() {
  // Self Voice
  const sv = document.getElementById("sv-list");
  const svOrder = ["high", "medium", "low", "off"];
  sv.innerHTML = "";
  svOrder.forEach((name) => {
    const sel = STATE && STATE.sidetone === name;
    const el = document.createElement("button");
    el.className = "radio-item" + (sel ? " sel" : "");
    el.innerHTML = `<span>${capitalize(name)}</span><span class="radio-dot"></span>`;
    el.onclick = () => act("set_sidetone", name);
    sv.appendChild(el);
  });
  // Auto-Off
  const ao = document.getElementById("ao-list");
  ao.innerHTML = "";
  (OPTIONS.auto_off_minutes || []).forEach((mins) => {
    const sel = STATE && STATE.auto_off === mins;
    const el = document.createElement("button");
    el.className = "radio-item" + (sel ? " sel" : "");
    el.innerHTML = `<span>${autoOffLabel(mins)}</span><span class="radio-dot"></span>`;
    el.onclick = () => act("set_auto_off", mins);
    ao.appendChild(el);
  });
}

// ---- actions ----
let busy = false;
async function act(method, ...args) {
  if (busy) return; busy = true;
  try {
    const st = await api(method, ...args);
    if (st && st.modes) { STATE = st; render(); }
    if (st && st.error) toast(st.error);
  } catch (e) { toast(String(e)); }
  busy = false;
}

let toastTimer = null;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2200);
}

// ---- extras (name, paired, eq, prompts) + app settings ----
async function loadExtras() {
  EXTRAS = await api("get_extras");
  if (EXTRAS) {
    if (EXTRAS.name) document.getElementById("set-name").textContent = EXTRAS.name;
    renderPaired();
    if (EXTRAS.eq) setEqInputs(EXTRAS.eq);
    // Settings-list summaries
    const vpVal = document.getElementById("vp-val");
    if (vpVal) vpVal.textContent = EXTRAS.prompts
      ? (EXTRAS.prompts.enabled ? "On" : "Off") : "";
  }
  const app = await api("get_app_settings");
  if (app) {
    document.getElementById("app-speak").checked = !!app.speak_mode;
    document.getElementById("app-autostart").checked = !!app.autostart;
    const hk = document.getElementById("hotkey-list");
    hk.innerHTML = "";
    Object.entries(app.hotkeys || {}).forEach(([k, label]) => {
      const nice = { mode_quiet: "Quiet", mode_aware: "Aware",
        mode_immersion: "Immersion", mode_cycle: "Cycle modes" }[k] || k;
      const row = document.createElement("div");
      row.className = "li";
      row.innerHTML = `<span>${nice}</span><span class="li-val">${label}</span>`;
      hk.appendChild(row);
    });
  }
  loadShortcutSummary();
}

const SHORTCUT_LABELS = { VPA: "Access Your Voice Assistant", SpotifyGo: "Spotify",
  BatteryLevel: "Hear Battery Level", SpatialAudioMode: "Change Immersive Audio",
  Disabled: "Off" };
function shortcutLabel(action, options) {
  if (action === "Disabled") return "Off";
  const o = (options || []).find((x) => x.action === action);
  return (o && o.label) || SHORTCUT_LABELS[action] || action || "";
}

async function loadShortcutSummary() {
  const el = document.getElementById("set-shortcut");
  if (!el) return;
  const sc = await api("get_shortcut");
  SHORTCUT = sc || SHORTCUT;
  if (sc) el.textContent = (sc.enabled === false) ? "Off" : shortcutLabel(sc.action, sc.options);
}

let SHORTCUT = null;
async function loadShortcut() {
  const list = document.getElementById("shortcut-list");
  const toggle = document.getElementById("shortcut-toggle");
  const hintEl = document.getElementById("shortcut-hint");
  list.innerHTML = "";
  const sc = SHORTCUT || await api("get_shortcut");
  SHORTCUT = sc;
  if (!sc) return;
  if (hintEl && sc.hint) hintEl.textContent = sc.hint;
  const enabled = sc.enabled !== false;
  if (toggle) toggle.checked = enabled;
  list.classList.toggle("off", !enabled);

  (sc.options || []).forEach((opt) => {
    const sel = enabled && sc.action === opt.action;
    const el = document.createElement("button");
    el.className = "radio-item shortcut-item" + (opt.icon === "spotify" ? " spotify" : "") + (sel ? " sel" : "");
    el.innerHTML =
      `<span class="sc-ico" data-ico="${opt.icon || "shortcut"}"></span>` +
      `<span class="sc-text"><span class="sc-title">${opt.label}</span>` +
      `<span class="sc-desc">${opt.desc || ""}</span></span>` +
      `<span class="radio-dot"></span>`;
    el.onclick = () => applyShortcut(opt.action);
    list.appendChild(el);
  });
  paintIcons(list);
}

async function applyShortcut(action) {
  const r = await api("set_shortcut", action);
  if (r && r.ok) {
    SHORTCUT = { ...(SHORTCUT || {}), action: r.action, enabled: r.enabled,
      options: r.options || (SHORTCUT && SHORTCUT.options), last_action: r.last_action };
    loadShortcut();
    const s = document.getElementById("set-shortcut");
    if (s) s.textContent = (r.enabled === false) ? "Off" : shortcutLabel(r.action, r.options);
  } else if (r && r.error) { toast(r.error); }
}

async function loadPrompts() {
  if (!EXTRAS) EXTRAS = await api("get_extras");
  const p = EXTRAS && EXTRAS.prompts;
  document.getElementById("vp-state").textContent = p ? (p.enabled ? "On" : "Off") : "--";
  document.getElementById("vp-lang").textContent = (p && p.language) || "--";
}

async function loadTechInfo() {
  const ti = await api("get_tech_info");
  if (!ti) return;
  const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v || "--"; };
  set("ti-model", ti.model); set("ti-fw", ti.firmware); set("ti-pid", ti.product_id);
  set("ti-code", ti.codename); set("ti-plat", ti.platform);
  set("pu-fw", ti.firmware);
}

function loadRename() {
  const inp = document.getElementById("rename-input");
  if (inp) inp.value = (EXTRAS && EXTRAS.name) || "";
}

function renderPaired() {
  const wrap = document.getElementById("paired-list");
  wrap.innerHTML = "";
  (EXTRAS.paired || []).forEach((p, i) => {
    const el = document.createElement("div");
    el.className = "paired-item";
    const filled = i === 0;
    el.innerHTML = `<span class="paired-ava ${filled ? "filled" : ""}" data-ico="${filled ? "speaker" : "phone"}"></span>`
      + `<div class="paired-main"><div class="paired-name">${p.name || p.mac}</div>`
      + (filled ? `<div class="paired-sub">Active stream</div>` : "") + `</div>`
      + `<label class="switch"><input type="checkbox" checked disabled><span class="track"></span></label>`;
    wrap.appendChild(el);
  });
  const add = document.createElement("div");
  add.className = "paired-item paired-add";
  add.innerHTML = `<span class="paired-ava" data-ico="plus"></span><div class="paired-main"><div class="paired-name" style="font-weight:500">Add New</div></div>`;
  wrap.appendChild(add);
  paintIcons(wrap);
}

// ---- EQ curve ----
let EQ = { bass: 0, mid: 0, treble: 0 };
function setEqInputs(eq) { EQ = { ...eq }; drawEq(); syncEqVals(); }
function syncEqVals() {
  document.getElementById("eq-bass-val").textContent = EQ.bass;
  document.getElementById("eq-mid-val").textContent = EQ.mid;
  document.getElementById("eq-treble-val").textContent = EQ.treble;
}
function drawEq() {
  syncEqVals();
  const c = document.getElementById("eq-canvas");
  if (!c) return;
  const ctx = c.getContext("2d");
  ctx.clearRect(0, 0, c.width, c.height);
  const w = c.width, h = c.height, midY = h / 2;
  const xs = [w * 0.1, w * 0.5, w * 0.9];
  const ys = [midY - EQ.bass / 10 * (h * 0.4), midY - EQ.mid / 10 * (h * 0.4), midY - EQ.treble / 10 * (h * 0.4)];
  // ghost baseline
  ctx.strokeStyle = "#ececec"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(0, midY); ctx.lineTo(w, midY); ctx.stroke();
  // curve
  ctx.strokeStyle = "#181818"; ctx.lineWidth = 4; ctx.lineJoin = "round";
  ctx.beginPath(); ctx.moveTo(0, ys[0]);
  ctx.lineTo(xs[0], ys[0]);
  ctx.bezierCurveTo((xs[0]+xs[1])/2, ys[0], (xs[0]+xs[1])/2, ys[1], xs[1], ys[1]);
  ctx.bezierCurveTo((xs[1]+xs[2])/2, ys[1], (xs[1]+xs[2])/2, ys[2], xs[2], ys[2]);
  ctx.lineTo(w, ys[2]); ctx.stroke();
  // nodes
  ctx.fillStyle = "#fff"; ctx.strokeStyle = "#181818"; ctx.lineWidth = 3.5;
  xs.forEach((x, i) => { ctx.beginPath(); ctx.arc(x, ys[i], 11, 0, 7); ctx.fill(); ctx.stroke(); });
}

// ---- events ----
function wire() {
  paintIcons(document);
  document.querySelectorAll("[data-nav]").forEach((el) => {
    el.addEventListener("click", () => show(el.dataset.nav));
  });
  document.querySelectorAll("[data-sub]").forEach((el) => {
    el.addEventListener("click", () => show(el.dataset.sub));
  });
  document.querySelectorAll("[data-link]").forEach((el) => {
    el.addEventListener("click", async () => {
      const r = await api("open_url", el.dataset.link);
      if (r && r.ok) toast("Opening in your browser.");
      else toast("Could not open link.");
    });
  });
  const rnSave = document.getElementById("rename-save");
  if (rnSave) rnSave.addEventListener("click", async () => {
    const inp = document.getElementById("rename-input");
    const name = (inp.value || "").trim();
    if (!name) { toast("Enter a name."); return; }
    const r = await api("set_name", name);
    if (r && r.ok) {
      if (EXTRAS) EXTRAS.name = name;
      const sn = document.getElementById("set-name");
      if (sn) sn.textContent = name;
      toast("Name updated.");
      show("settings");
    } else { toast((r && r.error) || "Could not rename."); }
  });
  const nmSave = document.getElementById("newmode-save");
  if (nmSave) nmSave.addEventListener("click", async () => {
    const inp = document.getElementById("newmode-input");
    const name = (inp.value || "").trim();
    if (!name) { toast("Enter a mode name."); return; }
    if (busy) return; busy = true;
    try {
      const st = await api("add_mode", name);
      if (st && st.modes) { STATE = st; render(); }
      if (st && st.error) { toast(st.error); return; }
      toast("Mode created.");
      show("modes");
    } catch (e) { toast(String(e)); }
    finally { busy = false; }
  });
  document.getElementById("spatial-seg").querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => act("set_spatial", Number(btn.dataset.val)));
  });
  document.getElementById("wind-btn").addEventListener("click", () => act("set_wind"));
  document.getElementById("mp-toggle").addEventListener("change", (e) => act("set_multipoint", e.target.checked));
  document.getElementById("oh-pause").addEventListener("change", (e) => act("set_auto_pause", e.target.checked));
  document.getElementById("oh-answer").addEventListener("change", (e) => act("set_auto_answer", e.target.checked));
  document.getElementById("app-speak").addEventListener("change", () => api("toggle_speak"));
  document.getElementById("app-autostart").addEventListener("change", () => api("toggle_autostart"));
  document.getElementById("shortcut-toggle").addEventListener("change", (e) => {
    const on = e.target.checked;
    const last = (SHORTCUT && SHORTCUT.last_action) || "SpotifyGo";
    applyShortcut(on ? last : "Disabled");
  });

  // noise slider drag to set level (0..10): preview live, commit on release
  const sl = document.getElementById("nc-slider");
  const lvlFromEvent = (e) => {
    const r = sl.getBoundingClientRect();
    const cx = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
    return Math.max(0, Math.min(10, Math.round(cx / r.width * 10)));
  };
  const ncPreview = (lvl) => {
    document.getElementById("nc-fill").style.width = (lvl / 10 * 100) + "%";
  };
  let ncDrag = false, ncLast = null;
  sl.addEventListener("pointerdown", (e) => {
    if (sl.classList.contains("locked")) {
      toast("Preset modes have a fixed noise level.");
      return;
    }
    ncDrag = true;
    try { sl.setPointerCapture(e.pointerId); } catch (_) {}
    ncLast = lvlFromEvent(e); ncPreview(ncLast);
  });
  sl.addEventListener("pointermove", (e) => {
    if (!ncDrag) return;
    ncLast = lvlFromEvent(e); ncPreview(ncLast);
  });
  const ncEnd = () => {
    if (!ncDrag) return; ncDrag = false;
    if (ncLast != null) act("set_cnc_app", ncLast);
  };
  sl.addEventListener("pointerup", ncEnd);
  sl.addEventListener("pointercancel", ncEnd);

  // EQ presets
  document.querySelectorAll("[data-eq]").forEach((b) => {
    b.addEventListener("click", () => {
      const d = b.dataset.eq;
      if (d === "bass+") EQ.bass = Math.min(10, EQ.bass + 3);
      if (d === "bass-") EQ.bass = Math.max(-10, EQ.bass - 3);
      if (d === "treble+") EQ.treble = Math.min(10, EQ.treble + 3);
      if (d === "treble-") EQ.treble = Math.max(-10, EQ.treble - 3);
      drawEq();
      api("set_eq", EQ.bass, EQ.mid, EQ.treble);
    });
  });
  document.getElementById("eq-reset").addEventListener("click", () => {
    EQ = { bass: 0, mid: 0, treble: 0 }; drawEq();
    api("set_eq", 0, 0, 0);
  });

  // EQ curve drag: grab the nearest band node and move it vertically
  const cvs = document.getElementById("eq-canvas");
  if (cvs) {
    let band = null, commit = null;
    const bandFromX = (e) => {
      const r = cvs.getBoundingClientRect();
      const fx = ((e.touches ? e.touches[0].clientX : e.clientX) - r.left) / r.width;
      if (fx < 0.34) return "bass";
      if (fx > 0.66) return "treble";
      return "mid";
    };
    const valFromY = (e) => {
      const r = cvs.getBoundingClientRect();
      const fy = ((e.touches ? e.touches[0].clientY : e.clientY) - r.top) / r.height;
      return Math.max(-10, Math.min(10, Math.round((0.5 - fy) / 0.4 * 10)));
    };
    const push = () => api("set_eq", EQ.bass, EQ.mid, EQ.treble);
    cvs.addEventListener("pointerdown", (e) => {
      band = bandFromX(e);
      try { cvs.setPointerCapture(e.pointerId); } catch (_) {}
      EQ[band] = valFromY(e); drawEq(); e.preventDefault();
    });
    cvs.addEventListener("pointermove", (e) => {
      if (!band) return;
      EQ[band] = valFromY(e); drawEq();
      clearTimeout(commit); commit = setTimeout(push, 140);
    });
    const eqEnd = () => {
      if (!band) return; band = null;
      clearTimeout(commit); push();
    };
    cvs.addEventListener("pointerup", eqEnd);
    cvs.addEventListener("pointercancel", eqEnd);
  }
}

async function init() {
  wire();
  await waitForApi(2500);
  OPTIONS = await api("get_options") || MOCK_OPTIONS;
  STATE = await api("get_state");
  // headless preview hook: ?state=disc forces the disconnected banner (mock only)
  const q0 = new URLSearchParams(location.search);
  if (q0.get("state") === "disc" && STATE) STATE.connected = false;
  render();
  // deep-link for headless screenshots: ?screen=modes
  const q = new URLSearchParams(location.search);
  if (q.get("screen")) show(q.get("screen"));
  // full refresh in background (real device only)
  if (hasApi()) {
    api("refresh").then((st) => { if (st && st.modes) { STATE = st; render(); } });
    // live poll so connect/disconnect, battery and mode changes show without a
    // user action. get_state is a cached serialize (instant); only re-render on
    // an actual change, and never mid-action.
    setInterval(pollState, 2000);
  }
}

let lastSig = "";
async function pollState() {
  if (!hasApi() || busy) return;
  try {
    const st = await api("get_state");
    if (!st) return;
    const sig = JSON.stringify(st);
    if (sig !== lastSig) { lastSig = sig; STATE = st; render(); }
  } catch (e) { /* transient bridge hiccup; try again next tick */ }
}

document.addEventListener("DOMContentLoaded", init);
