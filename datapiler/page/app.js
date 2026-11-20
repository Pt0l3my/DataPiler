"use strict";
// DataPiler's page. `$`, `esc`, `store`, `api`, `note`, `showTab`, the terminal's painting and polling, the file
// drop and the heartbeat are adapted from LLM Jobrunner 1.2's page (build plan §7.1). Every value from DataPiler
// reaches the page through textContent, or through esc() where markup is built.
const TOKEN = "__TOKEN__";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
const JOB_MAX = 256 * 1024;
const TABS = ["status", "extract", "imported", "jobs", "outputs", "deleted", "terminal", "settings"];
const SOURCES = ["app", "page", "smithbox", "link", "extract", "job", "guard", "textdb", "env", "update", "folders"];
const ROW_UNIT = { rows: "rows", maps: "maps", entries: "entries" };

let ST = null, CAT = null, GONE = false, FAILS = 0, TAB = "status", HOLD = false, OV = null;
let OUT_REV = -1, VIEW = null, SETTINGS = null;
let PICK = new Set(), BUNDLE = null, LAST_ROWS = [];
let JOBS_KEY = "", ROWS_KEY = "", CARDS_KEY = "";
let DRAG = null, DROPLINE = null, REFOCUS = null;   // S74: the job card being dragged, the drop marker, the grip to refocus
const TERM = { last: 0, lines: [], paused: false, level: "INFO", srcs: new Set() };

function api(path, body) {
  const o = { headers: { "X-DataPiler-Token": TOKEN } };
  if (body !== undefined) { o.method = "POST"; o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  return fetch(path, o).then((r) => r.json().then((j) => {
    if (!r.ok) { const e = new Error(j.error || r.statusText); e.field = j.field || null; throw e; }
    return j;
  }));
}
function note(text, ok) {
  const d = document.createElement("div");
  d.className = "msg" + (ok ? " ok" : "");
  d.innerHTML = "<div>" + esc(text) + "</div><button class='sm'>Dismiss</button>";
  d.querySelector("button").addEventListener("click", () => d.remove());
  $("msgs").prepend(d);
  if (ok) setTimeout(() => d.remove(), 6000);
}

// ---- small DOM builders: text always through textContent
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = String(text);
  return e;
}
function add(parent, ...kids) { kids.forEach((k) => { if (k != null) parent.appendChild(typeof k === "string" ? document.createTextNode(k) : k); }); return parent; }
function phText(text) {
  // "Installed in <SMITHBOX>": the placeholders in DataPiler's own colour
  const s = el("span");
  String(text == null ? "" : text).split(/(<[A-Z]+>)/).forEach((part) => {
    if (!part) return;
    add(s, /^<[A-Z]+>$/.test(part) ? el("span", "mono ph", part) : part);
  });
  return s;
}
function qm(title) { const q = el("span", "qm", "?"); q.title = String(title); return q; }
function fmtN(v) { return v == null ? "" : Number(v).toLocaleString("en-GB"); }
function fmtSize(b) {
  if (b == null) return "";
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}
function short(h) { return h ? String(h).slice(0, 4) + "…" + String(h).slice(-4) : ""; }
function mark(ok) {
  if (ok === true) return el("span", "m ok", "✓");
  if (ok === false) return el("span", "m bad", "✗");
  if (ok === "warn") return el("span", "m warn", "●");
  return el("span", "m unk", "?");
}
function clear(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; }

// ---- the one overlay, for the folder picker and the Update... pop-up (build plan 0.2 section 3.2)
// Opens the one overlay (a second call closes the first). Esc and its × close it; focus is kept inside while it is
// open and returns to opts.opener (else the element that had focus) when it closes; onClose runs on every close.
// Returns the parts to fill: box (.modal), body (.mb), foot (.mf); and close().
function overlay(title, opts) {
  opts = opts || {};
  if (OV) OV.close();
  const shade = $("ov");
  const opener = opts.opener || document.activeElement;
  clear(shade);
  const box = el("div", "modal" + (opts.wide ? " wide" : ""));
  const head = el("div", "mh"), t = el("span", "mt", title), x = el("button", "x", "×");
  t.id = "ovTitle";
  x.title = "Close (Esc)";
  x.setAttribute("aria-label", "Close");
  const body = el("div", "mb"), foot = el("div", "mf");
  add(box, add(head, t, x), body, foot);
  add(shade, box);
  shade.classList.add("on");
  let open = true;
  const focusables = () => Array.prototype.filter.call(
    box.querySelectorAll("button, input, select, textarea, a[href], [tabindex]"),
    (e) => !e.disabled && e.tabIndex >= 0 && e.getClientRects().length > 0);
  const first = () => { const f = focusables(); return f.find((e) => e !== x) || x; };
  function onKey(e) {
    if (!open) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key !== "Tab") return;
    const f = focusables();
    if (!f.length) { e.preventDefault(); return; }
    const a = document.activeElement, lo = f[0], hi = f[f.length - 1];
    if (!box.contains(a)) { e.preventDefault(); lo.focus(); }
    else if (e.shiftKey && a === lo) { e.preventDefault(); hi.focus(); }
    else if (!e.shiftKey && a === hi) { e.preventDefault(); lo.focus(); }
  }
  function onFocus(e) { if (open && !box.contains(e.target)) first().focus(); }
  function close() {
    if (!open) return;
    open = false;
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("focusin", onFocus, true);
    shade.classList.remove("on");
    clear(shade);
    if (OV === handle) OV = null;
    try { if (opener && opener.focus && document.body.contains(opener)) opener.focus(); } catch (e) { /* gone */ }
    if (opts.onClose) { try { opts.onClose(); } catch (e) { /* the close goes on */ } }
  }
  x.addEventListener("click", close);
  document.addEventListener("keydown", onKey, true);
  document.addEventListener("focusin", onFocus, true);
  const handle = { box: box, body: body, foot: foot, close: close };
  OV = handle;
  setTimeout(() => { if (open && !box.contains(document.activeElement)) first().focus(); }, 0);
  return handle;
}
// DP22: the pop-up of a removal and of the Deleted bin, in the one overlay. ask is the API's {title, text, word,
// button}: with word DELETE it holds a text box, and its button stays disabled until DELETE is typed in. Resolves with
// the confirmation to send, or null when it is closed without one.
function askRemove(ask) {
  return new Promise((resolve) => {
    let answer = null;
    const h = overlay(ask.title || "Are you sure?", { onClose: () => resolve(answer) });
    add(h.body, el("div", null, ask.text));
    const typed = ask.word === "DELETE";
    const go = el("button", "pri", ask.button || "Move to the Deleted bin");
    let box = null;
    if (typed) {
      box = el("input", "typed");
      box.type = "text"; box.spellcheck = false; box.autocomplete = "off"; box.placeholder = "DELETE";
      box.setAttribute("aria-label", "Type DELETE to go on");
      add(h.body, add(el("div", "typedrow"), el("span", "mute", "Type DELETE to go on:"), box));
      go.disabled = true;
      box.addEventListener("input", () => { go.disabled = box.value !== "DELETE"; });
      // Enter goes on; its default is stopped, or it would press the button that gets the focus back as it closes
      box.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); if (!go.disabled) go.click(); } });
    }
    const no = el("button", null, "Cancel");
    no.addEventListener("click", () => h.close());
    go.addEventListener("click", () => { if (go.disabled) return; answer = typed ? box.value : ask.word; h.close(); });
    add(h.foot, no, go);
  });
}
// Posts the request; while the API asks for a confirmation (DP22), shows the pop-up and posts it again with the answer.
// Resolves with the API's last answer, or {ok: false, cancelled: true} when the pop-up was closed; an answer to a
// confirmed request carries what was typed in as `confirmed`, for a request that has to be sent again.
function confirmed(path, body) {
  return api(path, body).then((r) => {
    if (!r || r.ok || !r.ask || !r.ask.word) return r;
    return askRemove(r.ask).then((c) => c == null ? { ok: false, cancelled: true }
      : confirmed(path, Object.assign({}, body, { confirm: c })).then((x) => {
        if (x && typeof x === "object" && x.confirmed == null) x.confirmed = c;
        return x;
      }));
  });
}
// While on, poll()'s failures never show "DataPiler has stopped" (an update's restart; until the page reloads), and
// poll() and pollTerm() ask nothing: the app is down or about to be, and only the Update... pop-up's probe asks.
function holdHeartbeat(on) { HOLD = !!on; if (HOLD) FAILS = 0; }

// ---- tabs
function showTab(t) {
  if (TABS.indexOf(t) < 0) t = "status";
  TAB = t; store.set("dp.tab", t);
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.getAttribute("data-t") === t));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("on", s.id === "t-" + t));
  if (t === "outputs") loadOutputs();
  if (t === "imported") loadImported();
  if (t === "deleted") loadBin();
  if (t === "settings") loadSettings();
  if (t === "terminal") { paintTerm(); scrollEnd(); }
}

// ---- the top bar
const PILLS = {
  smithbox: { running: ["ok", "Smithbox running"], not_running: ["warn", "Smithbox not running"], not_found: ["err", "Smithbox not found"] },
  game: { closed: ["ok", "Game closed"], running: ["err", "Game running"], unknown: ["warn", "Game: not known"] },
  // S94 (DP33): with its switch on, the link's chip says whether the link is established; never while the game runs
  link: { off: ["mute", "Server link off"], no_libs: ["mute", "Server link: no libraries"],
          waiting: ["warn", "Server link on: waiting for Smithbox"], connected: ["ok", "Server link connected"],
          no_answer: ["err", "Server link on: no answer"], blocked: ["err", "Server link on: not used while the game runs"] },
};
function pill(id, kind, value, why) {
  const p = (PILLS[kind] || {})[value] || ["mute", kind];
  const e = $(id);
  e.className = "pill " + p[0];
  e.textContent = "● " + p[1];
  e.title = why ? String(why) : "";
}
function paintTop(s) {
  $("ver").textContent = String(s.version || "");          // the full version, 0.2.8 not 0.2 (S56)
  pill("pSmithbox", "smithbox", s.pills.smithbox);
  pill("pGame", "game", s.pills.game);
  pill("pLink", "link", s.pills.link, s.pills.link_why);
  $("block").hidden = !s.block;
  $("block").textContent = s.block || "";
}

// ---- Status
const CARD_TITLES = {
  smithbox: ["Smithbox", "Read from Smithbox's own files and its process - nothing in Smithbox is changed"],
  game: ["The game", "Read from its folder and its exe's version resource - nothing in it is changed"],
  project: ["The project", "Smithbox's project folder: never the game's folder, never inside it"],
  link: ["Server link", "Read calls only, from a fixed list; off at every start; closed at once if the game starts"],
  pc: ["This PC", "What the image steps (tile checks and overviews) may use: worker processes on the processor's cores and memory for decoded tiles, set in Settings. Read on this PC, shown here only; the graphics card is shown, never used"],
};
function fmtBytes(n) {
  if (n == null) return "not read";
  return n >= 1073741824 ? (n / 1073741824).toFixed(1) + " GB" : Math.round(n / 1048576) + " MB";
}
function pcCard(h) {
  const out = [], pc = (h && h.pc) || {}, w = (h && h.work) || {};
  const line = (ok, text, sub) => { const r = el("div", "check"); add(r, mark(ok), el("span", null, text)); if (sub) add(r, el("span", "sub", sub)); out.push(r); };
  line(true, "Processor: " + fmtN(pc.logical || 0) + " logical cores" + (pc.physical ? ", " + fmtN(pc.physical) + " physical" : ""), pc.cpu || null);
  line(true, "Memory: " + fmtBytes(pc.memory) + " in all, " + fmtBytes(pc.free) + " free");
  line(null, "Graphics: " + ((pc.graphics && pc.graphics.length) ? pc.graphics.join(", ") : "not read on this system"), "shown only: copying small tiles to it costs about what it saves");
  line(true, "Image steps use " + fmtN(w.workers || 1) + (w.workers === 1 ? " worker process" : " worker processes") + " and up to " + fmtBytes(w.memory) + " for decoded tiles",
       (w.auto_workers ? "cores: automatic (every core but one)" : "cores: set in Settings") + " · " + (w.auto_memory ? "memory: automatic (a quarter of the free memory)" : "memory: set in Settings"));
  return out;
}
function checkRow(c) {
  const row = el("div", "check");
  const textSpan = phText(c.text);
  if (c.detail) add(textSpan, qm(c.detail));
  add(row, mark(c.ok), textSpan);
  if (c.fix) add(row, el("span", "sub", c.fix));
  if (c.use && c.use.key && c.use.path) {
    // DP15: a folder Status offers (one place found, or the folder Smithbox runs from) - saved only on this press
    const b = el("button", "sm", "Use");
    b.title = "Save " + (c.use.shown || "") + " in Settings";
    b.addEventListener("click", () => api("/api/settings/one", { key: c.use.key, value: c.use.path }).then(() => {
      note("Saved in Settings.", true); CARDS_KEY = ""; poll(); if (TAB === "settings") loadSettings();
    }).catch((e) => note(e.message)));
    add(row, add(el("span", "sub"), b));
  }
  return row;
}
function cardFor(kind, body) {
  const card = el("div", "card");
  const h = el("h3", null, CARD_TITLES[kind][0]);
  add(h, qm(CARD_TITLES[kind][1]));
  add(card, h);
  body.forEach((x) => add(card, x));
  return card;
}
const LINK_WORDS = { off: "Off", on: "On for this session", blocked: "Blocked - the game is running",
                     no_libs: "Off - the server link needs its libraries (grpcio and protobuf, and typing-extensions, which grpcio needs): restart DataPiler and answer Y" };
// S94 (DP33): the line under it while the link is on, as the top bar's chip has it
const SERVER_WORDS = { connected: [true, "Connected: Smithbox's server answers"], waiting: ["warn", "Waiting for Smithbox"],
                       no_answer: [false, "No answer from Smithbox's server"] };
function linkCard(l, session) {
  const out = [];
  const row = el("div", "check");
  add(row, mark(l.state === "on" ? "warn" : l.state === "blocked" ? false : null), el("span", null, LINK_WORDS[l.state] || l.state));
  if (l.state === "on" || l.state === "blocked" || l.calls) {
    const parts = [fmtN(l.calls) + " calls"];
    if (l.last_call) parts.push("the last at " + l.last_call);
    if (l.last_methods && l.last_methods.length) parts.push(l.last_methods.join(", "));
    add(row, el("span", "sub", parts.join(" · ")));
  }
  out.push(row);
  const sv = l.state === "on" && l.server ? SERVER_WORDS[l.server.state] : null;
  if (sv) {
    const r = el("div", "check");
    add(r, mark(sv[0]), el("span", null, sv[1]));
    if (l.server.why) add(r, el("span", "sub", l.server.why));
    out.push(r);
  }
  if ((l.state === "off" || l.state === "no_libs") && l.would_call && l.would_call.length) {
    const w = el("div", "check");
    add(w, mark(null), el("span", null, "Switched on, it would call:"));
    const sub = el("div", "sub"), ul = el("ul");
    l.would_call.forEach((c) => add(ul, add(el("li"), el("code", null, c.method), " - " + c["for"])));
    add(w, add(sub, ul));
    out.push(w);
  }
  if (l.after) out.push(el("div", "after", l.after));
  const act = el("div", "actions");
  const b = el("button", null, l.state === "on" || l.state === "blocked" ? "Switch off" : "Switch on");
  b.disabled = l.state === "no_libs";
  b.addEventListener("click", () => switchLink(!(l.state === "on" || l.state === "blocked")));
  out.push(add(act, b));
  return out;
}
function paintStatus(s) {
  const key = JSON.stringify([s.status, s.hardware]);
  if (key === CARDS_KEY) return;
  CARDS_KEY = key;
  const g = clear($("cards"));
  ["smithbox", "game", "project"].forEach((k) => add(g, cardFor(k, (s.status[k] || []).map(checkRow))));
  add(g, cardFor("link", linkCard(s.status.link || {}, s.session)));
  if (s.hardware) add(g, cardFor("pc", pcCard(s.hardware)));
}
// The link asks once a session whether Smithbox has the project set in Settings open (it cannot see that yet).
function linkSwitch(on, confirmProject) {
  const body = { on: on };
  if (confirmProject) body.confirm_project = true;
  return api("/api/link", body).then((r) => {
    if (r.ask) return window.confirm(r.ask.text) ? linkSwitch(on, true) : r;
    if (!r.ok) note("The server link did not switch on: " + (r.why || r.state));
    return r;
  });
}
function switchLink(on) {
  linkSwitch(on).then(() => poll()).catch((e) => note(e.message));
}

// ---- Extract
function loadCatalogue() {
  return api("/api/catalogue").then((c) => { CAT = c; ROWS_KEY = ""; paintBundles(); if (ST) paintExtract(ST); }).catch(() => {});
}
function paintBundles() {
  const b = clear($("bundles"));
  if (!CAT) return;
  Object.keys(CAT.bundles).forEach((name) => {
    const chip = el("span", "chip" + (BUNDLE === name ? " on" : ""), name.charAt(0).toUpperCase() + name.slice(1));
    chip.addEventListener("click", () => { BUNDLE = name; PICK = new Set(CAT.bundles[name]); paintBundles(); ROWS_KEY = ""; if (ST) paintExtract(ST); });
    add(b, chip);
  });
}
function progressCell(r, row, rs) {
  const td = el("td");
  const st = rs ? rs.state : "idle";
  if (rs && rs.grey && st === "idle") { add(td, el("span", "mute", rs.grey)); return td; }
  if (st === "queued") add(td, "queued");
  else if (st === "running") {
    const p = rs.progress;
    if (p && p.of) {
      const bar = el("span", "bar"), fill = el("i");
      fill.style.width = Math.max(0, Math.min(100, Math.round(100 * p.done / p.of))) + "%";
      add(td, add(bar, fill));
      add(td, p.unit === "maps" ? "map " + fmtN(p.done) + " of " + fmtN(p.of) : fmtN(p.done) + " of " + fmtN(p.of) + " " + (ROW_UNIT[p.unit] || p.unit || ""));
    } else add(td, "running");
  } else if (st === "done") {
    add(td, el("span", "m ok", "✓"));
    const res = rs.result || {};
    add(td, " " + (res.count != null ? fmtN(res.count) + " " + (res.unit || "") : "done") + (res.secs != null ? ", " + Number(res.secs).toFixed(1) + " s" : ""));
  } else if (st === "failed") {
    add(td, el("span", "m bad", "✗"));
    add(td, " " + (rs.error || "failed"));
  } else if (st === "waiting_export") add(td, "waiting for the export");
  else if (st === "cancelled") add(td, "cancelled");
  else add(td, "-");
  if (row.sources.indexOf("guided") >= 0 && row.steps && row.steps.length && (st === "waiting_export" || PICK.has(row.id) && st !== "done")) {
    const ol = el("ol", "guided");
    row.steps.forEach((s) => add(ol, add(el("li"), phText(s))));
    add(td, ol);
  }
  return td;
}
function paintExtract(s) {
  if (!CAT) return;
  const x = s.extract || {};
  const byId = {};
  (x.rows || []).forEach((r) => { byId[r.id] = r; });
  const key = JSON.stringify([x.rows, [...PICK]]);
  if (key !== ROWS_KEY) {
    ROWS_KEY = key;
    const tb = clear($("rows"));
    CAT.rows.forEach((row) => {
      const rs = byId[row.id];
      const grey = rs && rs.grey;
      const tr = el("tr", grey ? "off" : null);
      const box = el("input"); box.type = "checkbox"; box.checked = PICK.has(row.id); box.disabled = !!grey;
      box.addEventListener("change", () => { if (box.checked) PICK.add(row.id); else PICK.delete(row.id); BUNDLE = null; paintBundles(); ROWS_KEY = ""; paintExtract(ST); });
      const name = add(el("td"), row.name, qm(grey ? row.help + " - " + grey : row.help));
      const from = el("td");
      row.sources.forEach((src) => add(from, el("span", "from " + (src === "server" ? "srv" : "gd"), src === "server" ? "Server" : "Guided export")));
      add(tr, add(el("td"), box), name, from, el("td", null, row.gives), el("td", null, row.goes_to === "workspace" ? "Workspace" : "Workspace + share (counts only)"),
          progressCell(s, row, rs));
      add(tb, tr);
    });
  }
  const ask = $("xAsk");
  if (x.ask) {
    clear(ask);
    const go = el("button", "pri", "Go on");
    go.addEventListener("click", () => runRows(LAST_ROWS.length ? LAST_ROWS : [...PICK], true, x.ask.maps));
    add(ask, el("span", null, x.ask.text), go);
    ask.hidden = false;
  } else ask.hidden = true;
  const ib = $("inbox");
  if (x.inbox && x.inbox.length) {
    clear(ib);
    add(ib, el("div", null, "Left in the inbox:"));
    x.inbox.forEach((f) => add(ib, add(el("div"), el("code", null, f.file), " - " + f.reason)));
    ib.hidden = false;
  } else ib.hidden = true;
  // Cancel also ends a guided row's wait for its exports (one may never come, as on an install without that DLC).
  const busy = !!x.running || (x.rows || []).some((r) => ["queued", "running", "waiting_export"].includes(r.state));
  $("cancel").disabled = !busy;
}
function runRows(rows, loadMaps, confirm) {
  if (!rows.length) { note("Tick the rows to run first."); return; }
  LAST_ROWS = rows.slice();
  api("/api/extract/run", { rows: rows, load_maps: !!loadMaps, confirm_maps: confirm == null ? null : confirm }).then((r) => {
    if (r.ok) { poll(); return; }
    if (r.ask && window.confirm(r.ask.text)) runRows(rows, true, r.ask.maps);
  }).catch((e) => note(e.message));
}

// ---- Jobs
function jobPill(j) {
  if (j.state === "refused") return el("span", "pill err", "✗ refused");
  if (j.state === "checked") return el("span", "pill ok", "✓ checked");
  if (j.state === "done") return el("span", "pill ok", "✓ done");
  if (j.state === "failed") return el("span", "pill err", "✗ failed");
  if (j.pausing && (j.state === "running" || j.state === "waiting")) return el("span", "pill warn", "pausing");
  if (j.state === "running" || j.state === "queued" || j.state === "waiting") return el("span", "pill warn", j.state);
  if (j.state === "paused") return el("span", "pill warn", "paused");
  return el("span", "pill mute", j.state);
}
// S95 (DP34): the About block at the top of a checked job's card, before a run, during it and after: the job's own
// words (its `about`), DataPiler's line of what it reads, computes and writes, and the codes its title and words cite,
// as plain chips (no link: the page asks nothing of elsewhere).
function aboutBlock(a) {
  const d = el("div", "jabout");
  add(d, el("b", null, "About"));
  if (a.text) add(d, el("div", "jabout-text", a.text));
  add(d, el("div", "jabout-sum", a.summary));
  if (a.refs && a.refs.length) {
    const r = el("div", "jrefs");
    add(r, el("span", "mute", "References"));
    a.refs.forEach((x) => { const s = el("span", "jref", x); s.title = "Cited in the job's title or description"; add(r, s); });
    add(d, r);
  }
  return d;
}
// S95: one item of Details' columns: a step's sentence, or steps that say the same of different names merged, their
// names in a compact list that wraps
function detailItem(it) {
  const li = add(el("li"), phText(it.text));
  if (it.names) {
    const ns = el("div", "jnames");
    it.names.forEach((n) => add(ns, el("code", null, n)));
    add(li, ns, phText(it.tail));
  }
  return li;
}
function detailCol(title, items) {
  const d = el("div"); add(d, el("b", null, title));
  const ul = el("ul");
  (items || []).forEach((it) => add(ul, detailItem(it)));
  if (!items || !items.length) add(ul, el("li", "mute", "nothing"));
  return add(d, ul);
}
// S95: Reads / Computes / Writes under one Details toggle inside the card, folded by default. Whether a card's Details
// is open is kept while this page is open (not saved), by the same key as the card's fold. It is not DP30's fold of
// whole cards (S54, S86, S92): folding a card, Fold all and Unfold all leave it as it was. S96: under the columns,
// the steps' lines once they have nothing live to show (liveSteps), and the list of the job's workspace folders and
// files, which its Workspace line counts.
const DETAILS_OPEN = {};
function detailsBlock(j, steps, local) {
  const key = foldKey(j), n = (j.ops || []).length;
  const words = "Details (" + n + (n === 1 ? " step)" : " steps)");
  const box = el("div", "jdetails");
  const b = el("button", "dtoggle");
  b.title = "Show or hide what each step reads, computes and writes" + (steps ? ", how each step went" : "") +
    (local ? " and the job's workspace folders and files" : "");
  const body = el("div", "jdbody");
  const cols = el("div", "cols3");
  add(cols, detailCol("Reads", j.details.reads), detailCol("Computes", j.details.computes), detailCol("Writes", j.details.writes));
  add(body, cols);
  if (steps) add(body, add(el("div", "jdsec"), el("b", null, "Steps"), steps));
  if (local) {
    const ns = el("div", "jnames");
    local.forEach((x) => add(ns, el("code", null, x)));
    add(body, add(el("div", "jdsec"), el("b", null, "Workspace"), ns));
  }
  const show = (on) => {
    body.hidden = !on;
    b.textContent = (on ? "▾ " : "▸ ") + words;
    b.setAttribute("aria-expanded", on ? "true" : "false");
  };
  show(!!DETAILS_OPEN[key]);
  b.addEventListener("click", () => { DETAILS_OPEN[key] = body.hidden; show(DETAILS_OPEN[key]); });
  return add(box, b, body);
}
// S96: the steps' lines stay in view while the job is queued, waits or runs, and while a step is running or has
// failed; otherwise they are under Details.
function liveSteps(j) {
  return ["queued", "waiting", "running"].indexOf(j.state) >= 0 ||
    (j.ops || []).some((o) => o.state === "running" || o.state === "failed");
}
// S96: "40 folders", "2 folders and 3 files": the job's workspace outputs (result.local: a folder is
// "unpacked/<file>/ (N files)", a file "<name>.json" or "<name>.png")
function localCount(local) {
  const folders = local.filter((x) => String(x).indexOf("/") >= 0).length, files = local.length - folders;
  const parts = [];
  if (folders) parts.push(fmtN(folders) + (folders === 1 ? " folder" : " folders"));
  if (files) parts.push(fmtN(files) + (files === 1 ? " file" : " files"));
  return parts.join(" and ");
}
function opLine(o) {
  const parts = ["op " + o.n + " " + o.op + ": " + o.state];
  if (o.of) parts.push(fmtN(o.done) + " of " + fmtN(o.of) + (o.unit ? " " + o.unit : "") + " (" + Math.floor(100 * o.done / o.of) + "%)");
  else if (o.done) parts.push(fmtN(o.done) + (o.unit ? " " + o.unit : ""));
  if (o.secs != null) parts.push(o.secs >= 120 ? Math.floor(o.secs / 60) + " min " + Math.round(o.secs % 60) + " s" : Number(o.secs).toFixed(1) + " s");
  if (o.state === "running" && o.of && o.done < o.of && o.done > 0 && o.secs > 0) {
    const left = (o.of - o.done) * (o.secs / o.done);   // S52: a rough guess from the pace so far
    parts.push("about " + (left >= 120 ? Math.round(left / 60) + " min" : Math.round(left) + " s") + " left");
  }
  return el("div", null, parts.join(" · "));
}
// S66: what a stopped run kept, which Resume job goes on from; none for a job that is running, queued or done.
function keptOf(j) {
  if (!j.result || !j.result.kept || ["failed", "cancelled", "stopped"].indexOf(j.state) < 0) return null;
  return j.result.kept.maps > 0 ? j.result.kept : null;
}
function keptNote(k) {
  let t = "Saved progress: " + fmtN(k.maps) + (k.of ? " of " + fmtN(k.of) : "") + " maps read and kept from the last run. ";
  if (k.next) t += "Resume job picks up at map " + fmtN(k.next_n) + (k.of ? " of " + fmtN(k.of) : "") + " (" + k.next + ").";
  else if (k.of && k.maps >= k.of) t += "Every map is read: Resume job goes on with the steps after them.";
  else t += "Resume job goes on from there.";
  return t;
}
function jobAct(j, what, confirm, word) {
  const body = { id: j.id, what: what, confirm_maps: confirm == null ? null : confirm };
  if (word) body.confirm = word;
  // DP22: Remove asks in the page's pop-up (DELETE typed in when the job holds saved progress); the job goes to the bin.
  // A run that would move saved map progress to the bin (Start again; Resume job or Update data with progress of
  // another version) asks for DELETE in the same pop-up: the API says when.
  (what === "cancel" || what === "pause" ? api("/api/jobs/act", body) : confirmed("/api/jobs/act", body)).then((r) => {
    if (r.ok) { if (what === "remove") note("Moved to the Deleted bin: " + j.id + ".", true); poll(); return; }
    if (r.cancelled) return;
    if (r.ask && !r.ask.word) { if (window.confirm(r.ask.text)) jobAct(j, what, r.ask.maps, r.confirmed || word); return; }
    if (r.error) note(r.error);
  }).catch((e) => note(e.message));
}
// DP23: a job's kept versions, any two compared (local only: nothing of it reaches a share file)
const IDS_SHOWN = 60;
function idList(ids) {
  if (!ids || !ids.length) return null;
  const t = ids.slice(0, IDS_SHOWN).map((x) => typeof x === "number" ? String(x) : x).join(", ");
  return t + (ids.length > IDS_SHOWN ? " and " + fmtN(ids.length - IDS_SHOWN) + " more" : "");
}
function paintReport(box, rep) {
  clear(box);
  add(box, el("div", "mute", "From " + rep.from.label + " to " + rep.to.label + ". Ids are row ids for params and map ids for maps; the report is local only."));
  (rep.tables || []).forEach((t) => {
    const d = el("div", "vtable");
    add(d, el("div", null, t.line));
    [["Added", t.added], ["Changed", t.changed], ["Removed", t.removed], ["Not read", t.not_read]].forEach((x) => {
      const ids = idList(x[1]);
      if (ids) add(d, el("div", "mono mute", x[0] + ": " + ids));
    });
    add(box, d);
  });
  if (!(rep.tables || []).length) add(box, el("div", "mute", "Neither version kept a read of this job."));
}
function openCompare(j) {
  api("/api/versions?job=" + encodeURIComponent(j.id)).then((r) => {
    const vs = r.versions || [];
    const h = overlay("Compare versions: " + j.id, { wide: true });
    if (vs.length < 2) { add(h.body, el("div", "mute", "This job has kept reads of one version so far: run it on another to compare.")); return; }
    const pick = (at) => {
      const s = el("select");
      vs.forEach((v, k) => { const o = el("option", null, v.label + " - since " + v.since); o.value = v.id; if (k === at) o.selected = true; add(s, o); });
      return s;
    };
    const a = pick(vs.length - 2), b = pick(vs.length - 1), out = el("div", "vreport");
    const go = el("button", "pri", "Compare");
    go.addEventListener("click", () => {
      if (a.value === b.value) { clear(out); add(out, el("div", "mute", "Pick two different versions.")); return; }
      api("/api/versions/compare?job=" + encodeURIComponent(j.id) + "&a=" + encodeURIComponent(a.value) + "&b=" + encodeURIComponent(b.value))
        .then((rep) => paintReport(out, rep)).catch((e) => { clear(out); add(out, el("div", "bad", e.message)); });
    });
    add(h.body, add(el("div", "vpick"), el("span", "mute", "From"), a, el("span", "mute", "to"), b, go), out);
    const close = el("button", null, "Close");
    close.addEventListener("click", () => h.close());
    add(h.foot, close);
    go.click();
  }).catch((e) => note(e.message));
}
// S54: each card can fold to its title row; folded cards are remembered in this browser by the job's sha256 or id.
// S86 (the owner's request of 2026-11-15): a finished job starts folded; the owner's own fold or unfold of a card is
// remembered and wins. S92 (the owner's, the same day): a job that finished since DataPiler started stays unfolded,
// its results in view.
function foldKey(j) { return String(j.sha256 || j.id || ""); }
function keySet(name) { try { return new Set(JSON.parse(store.get(name) || "[]")); } catch (e) { return new Set(); } }
function folded() { return keySet("dp.jobs.folded"); }
function unfolded() { return keySet("dp.jobs.unfolded"); }
function isFolded(j) {
  const key = foldKey(j);
  if (unfolded().has(key)) return false;
  return folded().has(key) || (j.state === "done" && !j.done_now);
}
function setFolded(key, on) {
  const f = folded(), u = unfolded();
  if (on) { f.add(key); u.delete(key); } else { f.delete(key); u.add(key); }
  store.set("dp.jobs.folded", JSON.stringify([...f].slice(-200)));
  store.set("dp.jobs.unfolded", JSON.stringify([...u].slice(-200)));
}
// S87 (DP30): a finished job's files, packed into 7z to upload: its share file and its workspace folder, in parts of
// at most 29.9 MB when larger. The button sits on the title row, so a folded card has it too.
const PACKED_SEEN = {};
function packBits(j, head) {
  const has = j.result && (j.result.share || (j.result.local && j.result.local.length));
  if (j.state !== "done" || !has) return;
  const pk = j.packing;
  const b = el("button", "sm", pk ? "Packing… " + (pk.of ? Math.floor(100 * pk.done / pk.of) : 0) + "%" : "Pack 7z");
  b.title = "Pack this job's share file and its workspace folder into a 7z archive in the workspace's packed folder, " +
    "in parts of up to 29.9 MB when it is larger, ready to upload. The workspace files are research material: share them only for this project's research.";
  if (pk) b.disabled = true;
  b.addEventListener("click", () => {
    api("/api/jobs/act", { id: j.id, what: "pack", confirm_maps: null }).then((r) => {
      if (!r.ok) note(r.error || "Not packed.");
      poll();
    }).catch((e) => note(e.message));
  });
  add(head, b);
  const done = j.packed;
  if (!done || pk) return;
  if (done.error) {
    const bad = el("span", "pill err", "not packed");
    bad.title = done.error;
    add(head, bad);
  } else {
    const n = done.parts.length;
    const pill = el("span", "pill ok", "packed: " + (n === 1 ? "1 part" : n + " parts") + ", " + fmtSize(done.size));
    pill.title = done.parts.map((x) => x.name + " - " + fmtSize(x.size)).join("\n");
    add(head, pill);
    const ob = el("button", "sm", "Open packed folder");
    ob.title = "Open the workspace's packed folder (Windows)";
    ob.addEventListener("click", () => api("/api/open", { area: "packed" }).then((r) => { if (!r.ok) note(r.error || "Not opened."); }).catch((e) => note(e.message)));
    add(head, ob);
  }
  if (PACKED_SEEN[j.id] !== done.at) {
    if (PACKED_SEEN[j.id] !== undefined || Date.now() / 1000 - done.at < 30) {
      note(done.error ? done.error : "Packed " + j.id + ": " + (done.parts.length === 1 ? done.parts[0].name : done.parts.length + " parts, " + done.parts[0].name + " first") + ", " + fmtSize(done.size) + ", in the workspace's packed folder.", !done.error);
    }
    PACKED_SEEN[j.id] = done.at;
  }
}
// S54: where the job is, as a step of its ops and a share of the whole, for every state that has ops.
function jobProgress(j) {
  const ops = j.ops || [];
  if (!ops.length || ["queued", "waiting", "running", "done", "failed", "cancelled", "stopped", "paused"].indexOf(j.state) < 0) return null;
  const n = ops.length;
  const done = ops.filter((o) => o.state === "done").length;
  const cur = ops.find((o) => o.state === "running" || o.state === "failed") || null;
  let frac = done;
  if (cur && cur.state === "running" && cur.of) frac += Math.min(1, cur.done / cur.of);
  const pct = Math.floor(100 * frac / n);
  if (j.state === "done") return "all " + n + " steps done (100%)";
  if (cur) return "step " + (cur.n + 1) + " of " + n + " (" + cur.op + ") · " + pct + "%";
  return done + " of " + n + " steps done · " + pct + "%";
}
function jobCard(j) {
  const key = foldKey(j);
  const c = el("div", "jobcard" + (isFolded(j) ? " folded" : ""));
  c.dataset.jid = j.id;
  const head = el("div", "jhead");
  // S74: drag the grip to move the card above, below or between others; or focus it and use the arrow keys
  const grip = el("button", "jgrip", "⠿");
  grip.title = "Drag to move this job up or down; or focus it and press the up or down arrow";
  grip.setAttribute("aria-label", "Move the job " + (j.title || j.id) + ": drag, or use the up and down arrows");
  grip.addEventListener("mousedown", () => { c.draggable = true; });
  grip.addEventListener("mouseup", () => { if (!DRAG) c.draggable = false; });
  grip.addEventListener("keydown", (e) => {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); moveJob(j.id, e.key === "ArrowUp" ? -1 : 1); }
  });
  c.addEventListener("dragstart", (e) => {
    DRAG = j.id;
    c.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", j.id);
  });
  c.addEventListener("dragend", () => {
    c.draggable = false;
    c.classList.remove("dragging");
    showDrop(null);
    if (DRAG) { DRAG = null; JOBS_KEY = ""; if (ST) paintJobs(ST); }
  });
  add(head, grip);
  const fold = el("button", "fold", isFolded(j) ? "▸" : "▾");
  fold.title = "Fold or unfold this job";
  fold.addEventListener("click", () => {
    const on = !c.classList.contains("folded");
    c.classList.toggle("folded", on);
    fold.textContent = on ? "▸" : "▾";
    setFolded(key, on);
  });
  add(head, fold);
  add(head, el("b", null, j.title || j.id || "a job file"));
  if (j.id) add(head, el("span", "pill mute", j.id));
  if (j.format) add(head, el("span", "pill mute", j.format));
  add(head, jobPill(j));
  const prog = jobProgress(j);
  if (prog) add(head, el("span", "jprog", prog));
  if (j.sha256) add(head, el("span", "mono mute", "sha256 " + short(j.sha256)));
  packBits(j, head);
  add(c, head);
  if (j.about && j.state !== "refused") add(c, aboutBlock(j.about));
  // S96: the steps' lines in view while they are live, else under Details with the workspace's list
  let steps = null;
  if (j.ops && j.ops.length && ["queued", "waiting", "running", "done", "failed", "cancelled", "stopped", "paused"].indexOf(j.state) >= 0) {
    steps = el("div", "oplines");
    j.ops.forEach((o) => add(steps, opLine(o)));
  }
  const local = j.result && j.result.local && j.result.local.length ? j.result.local : null;
  const inDetails = !!j.details && j.state !== "refused";
  const stepsInView = steps && (!inDetails || liveSteps(j));
  if (inDetails) add(c, detailsBlock(j, stepsInView ? null : steps, local));
  if (j.refusals && j.refusals.length) {
    const r = el("div", "refusals");
    j.refusals.forEach((x) => add(r, el("div", null, (x.op != null ? "op " + x.op + " - " : "") + x.where + ": " + x.text)));
    add(c, r);
  }
  if (j.wait) add(c, el("div", "wait", "Waits: " + j.wait));
  if (stepsInView) add(c, steps);
  if (j.result) {
    const res = el("div", "result");
    if (j.result.share) {
      const sh = j.result.share;
      const line = add(el("div"), "Share file ", el("code", null, sh.name), " - " + fmtSize(sh.size) + " - sha256 " + short(sh.sha256) + " ");
      const show = el("button", "sm", "Show");
      show.addEventListener("click", () => { showTab("outputs"); openShare(sh.name); });
      add(res, add(line, show));
    }
    if (local) {
      // S76: the job's own workspace folder, where its files and images are. S96: counted; listed under Details
      const row = el("div", "jlocal");
      add(row, el("span", null, "Workspace: " + (inDetails ? localCount(local) + ", local, never shared" : local.join(", "))));
      const ob = el("button", "sm", "Open folder");
      ob.title = "Open this job's folder in the workspace (Windows)";
      ob.addEventListener("click", () => api("/api/open", { area: "job", job: j.id }).then((r) => { if (!r.ok) note(r.error || "Not opened."); }).catch((e) => note(e.message)));
      add(row, ob);
      add(res, row);
    }
    if (j.result.failed) {
      const f = j.result.failed;
      let t = "Failed at op " + f.op + ": " + f.why;
      if (f.check != null) t += " (check " + f.check + (f.where ? " at " + f.where : "") + ")";
      add(res, el("div", "bad", t));
    }
    if (keptOf(j)) add(res, el("div", "kept", keptNote(keptOf(j))));
    // S84: where a paused job goes on from
    if (j.state === "paused" && j.result.paused) {
      const pz = j.result.paused;
      add(res, el("div", "kept", "Paused after step " + pz.at + " of " + pz.of + " finished. Resume job goes on with step " + (pz.at + 1) + "; what the steps before it made is kept, also if DataPiler is closed meanwhile."));
    }
    // DP23: what changed since the last version, and where the change report is kept
    const ch = j.result.changes;
    if (ch) {
      const d = el("div", "changes");
      add(d, el("div", null, "Changes since " + ch.from + ":"));
      (ch.lines || []).forEach((t) => add(d, el("div", null, t)));
      if (ch.report) add(d, el("div", "mute", "Change report (workspace, local only): " + ch.report));
      add(res, d);
    }
    add(c, res);
  }
  if (j.update) add(c, el("div", "update", j.update.text + ". Update data reads the data again and compares it with the last run's."));
  const act = el("div", "actions");
  const canStart = ["checked", "cancelled", "stopped", "failed", "done", "paused"].indexOf(j.state) >= 0;
  const canCancel = ["queued", "waiting", "running"].indexOf(j.state) >= 0;
  const kept = keptOf(j);
  const paused = j.state === "paused";
  if (canStart && j.update) { const b = el("button", kept ? null : "pri", "Update data"); b.addEventListener("click", () => jobAct(j, "update")); add(act, b); }
  if (canStart && (kept || paused)) { const b = el("button", "pri", "Resume job"); b.addEventListener("click", () => jobAct(j, "resume")); add(act, b); }
  if (canStart) {
    const b = el("button", kept || paused || j.update ? null : "pri", j.state === "checked" ? "Start" : "Start again");
    b.addEventListener("click", () => {
      // S66: starting again from the beginning is asked first. With saved progress, which it moves to the Deleted
      // bin, the API asks instead, in the page's pop-up with DELETE typed in (the owner's rule of 2026-11-14).
      if (j.state !== "checked" && !kept && !paused && !window.confirm("Start this job again from the beginning?")) return;
      jobAct(j, "start");
    });
    add(act, b);
  }
  if (j.versions >= 2) { const b = el("button", null, "Compare versions…"); b.addEventListener("click", () => openCompare(j)); add(act, b); }
  // S84: Pause lets the step running now finish, then stops; Resume job goes on from the next step
  if (canCancel && j.state !== "queued") {
    const b = el("button", null, j.pausing ? "Pausing…" : "Pause");
    b.title = "Let the step running now finish, then stop, keeping everything done so far; Resume job goes on later";
    if (j.pausing) b.disabled = true;
    b.addEventListener("click", () => jobAct(j, "pause"));
    add(act, b);
  }
  if (canCancel) {
    const b = el("button", null, j.state === "queued" ? "Take off the queue" : "Stop");
    b.addEventListener("click", () => {
      // the owner's request of 2026-11-15: Stop asks first, in case it was pressed by mistake
      const q = j.state === "queued" ? "Take this job off the queue? It has not started." :
        "Stop this job now? The step running now is cut short, and what it has read in that step is lost (maps already read are kept). Pause instead lets the step finish and keeps everything, to go on later.";
      if (window.confirm(q)) jobAct(j, "cancel");
    });
    add(act, b);
  }
  if (!canCancel) { const b = el("button", null, "Remove"); b.addEventListener("click", () => jobAct(j, "remove")); add(act, b); }
  add(c, act);
  return c;
}
function jobOrder(list) {
  // S74: the owner's order (pos, first on top); cards added since it was set come first, newest first (S54)
  return list.slice().sort((a, b) => {
    const pa = a.pos == null ? -1 : a.pos, pb = b.pos == null ? -1 : b.pos;
    if (pa === -1 && pb === -1) return (Number(b.added) || 0) - (Number(a.added) || 0);
    if (pa === -1) return -1;
    if (pb === -1) return 1;
    return pa - pb;
  });
}
function paintJobs(s) {
  if (DRAG) return;                                          // never redrawn under a drag
  const key = JSON.stringify(s.jobs);
  if (key === JOBS_KEY) return;
  JOBS_KEY = key;
  const box = clear($("jobs"));
  if (!s.jobs.length) { add(box, el("div", "mute", "No job files yet.")); return; }
  jobOrder(s.jobs).forEach((j) => add(box, jobCard(j)));
  if (REFOCUS) {
    const g = box.querySelector('.jobcard[data-jid="' + CSS.escape(REFOCUS) + '"] .jgrip');
    REFOCUS = null;
    if (g) g.focus();
  }
}
function cardIds() { return Array.prototype.map.call($("jobs").querySelectorAll(".jobcard"), (c) => c.dataset.jid); }
function saveOrder(ids) {
  // shown at once; the server keeps it in jobs/order.json
  if (ST) { ST.jobs.forEach((j) => { j.pos = ids.indexOf(j.id); }); JOBS_KEY = ""; paintJobs(ST); }
  api("/api/jobs/order", { ids: ids }).then((r) => {
    if (!r.ok) note(r.error || "The order was not saved.");
  }).catch((e) => { note(e.message); JOBS_KEY = ""; poll(); });
}
function moveJob(id, by) {
  const ids = cardIds(), k = ids.indexOf(id), to = k + by;
  if (k < 0 || to < 0 || to >= ids.length) return;
  ids.splice(k, 1); ids.splice(to, 0, id);
  REFOCUS = id;
  saveOrder(ids);
}
function dropAt(y) {
  // before the first card whose middle is below the pointer, or after the last
  const cards = Array.prototype.slice.call($("jobs").querySelectorAll(".jobcard"));
  for (let k = 0; k < cards.length; k++) {
    const r = cards[k].getBoundingClientRect();
    if (y < r.top + r.height / 2) return { index: k, card: cards[k], before: true };
  }
  return { index: cards.length, card: cards[cards.length - 1], before: false };
}
function showDrop(t) {
  if (!DROPLINE) DROPLINE = el("div", "dropline");
  if (!t || !t.card) { DROPLINE.remove(); return; }
  if (t.before) t.card.parentNode.insertBefore(DROPLINE, t.card);
  else t.card.parentNode.insertBefore(DROPLINE, t.card.nextSibling);
}
function addFiles(files) {
  Array.prototype.forEach.call(files, (f) => {
    if (f.size > JOB_MAX) { note(f.name + ": too large - a job file is at most 256 KB."); return; }
    const rd = new FileReader();
    rd.onload = () => {
      const bytes = new Uint8Array(rd.result);
      let bin = "";
      for (let i = 0; i < bytes.length; i += 32768) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
      api("/api/jobs/drop", { name: f.name, data: btoa(bin) }).then((r) => {
        const st = r.card && r.card.state;
        note(f.name + ": " + (r.again ? "seen before - its card is shown." : st === "refused" ? "refused - its card says why." : "checked. Press Start to run it."), st !== "refused");
        JOBS_KEY = ""; poll();
      }).catch((e) => note(f.name + ": " + e.message));
    };
    rd.readAsArrayBuffer(f);
  });
}

// ---- Outputs
function fileItem(f, area) {
  const li = el("li");
  add(li, el("span", "n mono", f.name), el("span", null, fmtSize(f.size)), el("span", "mute", f.time));
  if (f.made_by) add(li, el("span", "pill mute", f.made_by));
  if (area === "share" && f.ok === false) add(li, el("span", "pill err", "fails check " + f.failed));
  if (area === "share") { const b = el("button", "sm", "Show"); b.addEventListener("click", () => openShare(f.name)); add(li, b); }
  // DP22: a share file, and what jobs, Extract and the guided import wrote in the workspace, go to the Deleted bin
  if (area === "share" || /^(local|imported)\//.test(f.name)) {
    const d = el("button", "sm", "Delete…");
    d.title = "Move it to the Deleted bin, once you type DELETE; Restore there puts it back";
    d.addEventListener("click", () => removeOutput(area, f.name));
    add(li, d);
  }
  return li;
}
function removeOutput(area, name) {
  confirmed("/api/outputs/remove", { area: area, name: name }).then((r) => {
    if (r.cancelled) return;
    if (!r.ok) { note(r.error || "Not moved to the Deleted bin."); return; }
    note("Moved to the Deleted bin: " + name + ".", true);
    if (VIEW === name) { VIEW = null; $("viewer").hidden = true; $("copyPath").disabled = true; }
    loadOutputs();
  }).catch((e) => note(e.message));
}
function loadImported() {
  return api("/api/imported").then((r) => {
    const ready = r.ready || [];
    $("impReady").textContent = ready.length ? "Jobs can use now (" + r.language + "): " + ready.map((x) => x.words).join(", ") + "."
      : "Nothing jobs can use yet in " + r.language + ": Extract's Character names row shows how to export it from Smithbox.";
    const tb = clear($("impRows"));
    (r.containers || []).forEach((c) => {
      const tr = el("tr");
      const holds = (c.serves || []).map((x) => x.words + " (" + x.layers.map((l) => l.layer + " " + fmtN(l.entries)).join(", ") + ")").join("; ");
      const lang = c.in_use ? c.language : c.language + " (not Settings' language, not used)";
      [c.container, lang, fmtN(c.wrappers), fmtN(c.entries), fmtN(c.skipped), holds || "-", c.imported].forEach((v) => add(tr, el("td", null, String(v))));
      const b = el("button", null, "Remove");
      b.addEventListener("click", () => {
        // DP22: the import goes to the Deleted bin, once DELETE is typed in the pop-up the API asks for
        confirmed("/api/imported/remove", { container: c.container, language: c.language }).then((x) => {
          if (x.cancelled) return;
          if (!x.ok) note(x.error || "Not removed"); else { note("Moved to the Deleted bin: " + c.container + " (" + c.language + ").", true); loadImported(); }
        }).catch((e) => note(e.message));
      });
      add(tr, add(el("td"), b));
      add(tb, tr);
    });
    if (!(r.containers || []).length) add(tb, add(el("tr"), el("td", null, "No text imported yet.")));
  }).catch(() => {});
}
function loadOutputs() {
  return api("/api/outputs").then((o) => {
    const w = clear($("work")), s = clear($("share"));
    if (!o.workspace.length) add(w, el("li", "empty", "Nothing yet."));
    o.workspace.forEach((f) => add(w, fileItem(f, "workspace")));
    // Only what passes the guard now sits under its green pill; the rest is listed apart, never to be shared.
    const good = o.share.filter((f) => f.ok), bad = o.share.filter((f) => !f.ok), sb = clear($("shareBadList"));
    if (!good.length) add(s, el("li", "empty", o.share.length ? "None passes the guard now." : "Nothing yet."));
    good.forEach((f) => add(s, fileItem(f, "share")));
    bad.forEach((f) => add(sb, fileItem(f, "share")));
    $("shareBad").hidden = !bad.length;
    if (VIEW && !o.share.some((f) => f.name === VIEW)) { VIEW = null; $("viewer").hidden = true; $("copyPath").disabled = true; }
  }).catch(() => {});
}
// ---- the Deleted bin (DP22): what a removal moved out, until it is erased
function loadBin() {
  return api("/api/bin").then((r) => {
    const items = r.items || [];
    $("binSum").textContent = items.length ? items.length + (items.length === 1 ? " item, " : " items, ") + fmtSize(r.size) + "." : "The bin is empty.";
    const tb = clear($("binRows"));
    items.forEach((it) => {
      const tr = el("tr");
      [it.what, it.name, it.from, it.when, fmtSize(it.size)].forEach((v, k) => add(tr, el("td", k === 1 || k === 2 ? "mono" : null, String(v))));
      const rs = el("button", "sm", "Restore");
      rs.title = "Put it back where it came from";
      rs.addEventListener("click", () => binRestore(it));
      const er = el("button", "sm", "Erase…");
      er.title = "Erase it for good, once you type DELETE";
      er.addEventListener("click", () => binErase(it));
      add(tr, add(el("td", "acts"), rs, " ", er));
      add(tb, tr);
    });
    if (!items.length) add(tb, add(el("tr"), el("td", "mute", "Nothing here.")));
    $("binEmpty").disabled = !items.length;
  }).catch(() => {});
}
function binRestore(it) {
  api("/api/bin/restore", { id: it.id }).then((r) => {
    if (!r.ok) { note(r.error || "Not restored."); return; }
    note("Restored: " + it.name + ".", true);
    loadBin(); poll();
  }).catch((e) => note(e.message));
}
function binErase(it) {
  confirmed("/api/bin/erase", { id: it.id }).then((r) => {
    if (r.cancelled) return;
    if (!r.ok) { note(r.error || "Not erased."); return; }
    note("Erased for good: " + it.name + ".", true);
    loadBin();
  }).catch((e) => note(e.message));
}
function binEmpty() {
  confirmed("/api/bin/empty", {}).then((r) => {
    if (r.cancelled) return;
    if (!r.ok) { note(r.error || "The bin was not emptied."); return; }
    note("The Deleted bin is empty: " + r.erased + (r.erased === 1 ? " item" : " items") + " erased for good.", true);
    loadBin();
  }).catch((e) => note(e.message));
}
function openShare(name) {
  api("/api/share?name=" + encodeURIComponent(name)).then((v) => {
    VIEW = v.name;
    const allOk = v.checks.length && v.checks.every((c) => c.ok);
    $("vhead").textContent = v.name + " · " + fmtSize(v.size) + " · sha256 " + v.sha256 + " · checks 1-6 " + (allOk ? "✓" : "✗");
    const ch = clear($("vchecks"));
    v.checks.forEach((c) => add(ch, add(el("span"), mark(c.ok), " " + c.check + " " + c.name + (c.ok || !c.where ? "" : " at " + c.where))));
    $("vtext").textContent = v.text;
    $("viewer").hidden = false;
    $("copyPath").disabled = !allOk;
  }).catch((e) => note(e.message));
}

// ---- Terminal: one log source, /api/log?after=; the level from the line's own field
const LV = { DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3 };
function lineCls(l) { return l.level === "ERROR" ? "ln err" : l.level === "WARN" ? "ln warn" : "ln"; }
function visible(l) { return LV[l.level] >= LV[TERM.level] && (!TERM.srcs.size || TERM.srcs.has(l.src)); }
function lineText(l) { return l.t + "  " + (l.level + "     ").slice(0, 5) + "  " + (l.src + "        ").slice(0, 8) + " " + l.msg; }
function lineEl(l) {
  const d = el("div", lineCls(l));
  add(d, el("span", "t", l.t), "  " + (l.level + "     ").slice(0, 5) + "  ", el("span", "src", (l.src + "        ").slice(0, 8)), " " + l.msg);
  return d;
}
function scrollEnd() { const t = $("term"); if (!TERM.paused) t.scrollTop = t.scrollHeight; }
function paintTerm() {
  const t = clear($("term"));
  TERM.lines.filter(visible).forEach((l) => add(t, lineEl(l)));
}
function pollTerm() {
  if (GONE || HOLD) return;
  api("/api/log?after=" + TERM.last).then((r) => {
    if (!r.lines.length) return;
    TERM.last = r.lines[r.lines.length - 1].seq;
    TERM.lines = TERM.lines.concat(r.lines);
    if (TERM.lines.length > 5000) { TERM.lines = TERM.lines.slice(-5000); if (TAB === "terminal") { paintTerm(); scrollEnd(); } return; }
    if (TAB === "terminal") {
      const t = $("term");
      r.lines.filter(visible).forEach((l) => add(t, lineEl(l)));
      scrollEnd();
    }
  }).catch(() => {});
}
function paintSrcChips() {
  const box = clear($("srcChips"));
  SOURCES.forEach((src) => {
    const c = el("span", "chip" + (TERM.srcs.has(src) ? " on" : ""), src);
    c.addEventListener("click", () => { if (TERM.srcs.has(src)) TERM.srcs.delete(src); else TERM.srcs.add(src); paintSrcChips(); paintTerm(); scrollEnd(); });
    add(box, c);
  });
}
function copyText(text, what) {
  const done = () => note(what + " copied.", true);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => note(what + ": the browser did not allow the copy."));
    return;
  }
  const ta = el("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { note(what + ": the browser did not allow the copy."); }
  ta.remove();
}
function copyVisible() { copyText(TERM.lines.filter(visible).map(lineText).join("\n") + "\n", "The visible lines"); }
function copyForSharing() {
  const vis = TERM.lines.filter(visible);
  if (!vis.length) { note("No lines to copy."); return; }
  const levels = Object.keys(LV).filter((k) => LV[k] >= LV[TERM.level]);
  const sources = TERM.srcs.size ? [...TERM.srcs] : SOURCES.slice();
  api("/api/log/share", { after: vis[0].seq - 1, upto: vis[vis.length - 1].seq, levels: levels, sources: sources }).then((r) => {
    if (!r.ok) { note("Not copied."); return; }
    const lo = r.left_out || {}, n3 = lo["3"] || 0, n4 = lo["4"] || 0;
    if (!r.text) { note("Not copied: every line fails a check (" + (n3 ? n3 + " a name the text database holds" : "") + (n3 && n4 ? ", " : "") + (n4 ? n4 + " a path, a name or an address" : "") + ")."); return; }
    copyText(r.text, "The lines, checked for sharing,");
    if (n3 || n4) note("Left out: " + (n3 ? n3 + (n3 === 1 ? " line" : " lines") + " holding a name the text database holds" : "") + (n3 && n4 ? "; " : "") + (n4 ? n4 + (n4 === 1 ? " line" : " lines") + " holding a path, a name or an address" : "") + ".");
  }).catch((e) => note(e.message));
}

// ---- Settings
const FIELDS = ["smithbox_dir", "game_dir", "project_dir", "workspace_dir", "share_dir", "devkit_dir", "language", "expansion", "port", "log_max_mb", "log_keep", "work_cores", "work_memory_mb"];
const NUMS = { port: true, log_max_mb: true, log_keep: true, work_cores: true, work_memory_mb: true };
const BLANK_ZERO = { port: true, work_cores: true, work_memory_mb: true };   // blank: any free port, or automatic
// The six folder fields: drawn read-only as their masks while Mask paths on this page is on, and left out of Save.
const PATH_FIELDS = { smithbox_dir: true, game_dir: true, project_dir: true, workspace_dir: true, share_dir: true, devkit_dir: true };
function masked() { return !!(SETTINGS && SETTINGS.settings && SETTINGS.settings.mask_paths); }
function loadSettings() {
  return api("/api/settings").then((r) => {
    SETTINGS = r;
    FIELDS.forEach((k) => { const v = r.settings[k]; $("s_" + k).value = BLANK_ZERO[k] && !v ? "" : String(v == null ? "" : v); $("s_" + k).classList.remove("bad"); });
    $("sServer").textContent = r.server || "";
    paintSession(r.session);
    $("sErr").textContent = "";
    // folders.js draws the folder rows, the mask and the picker's places from the same answer
    document.dispatchEvent(new CustomEvent("dp:settings", { detail: r }));
  }).catch(() => {});
}
function paintSession(s) {
  if (!s) return;
  $("sLink").textContent = s.link ? "Switch off" : "Switch on";
  $("sDebug").textContent = s.debug ? "Switch off" : "Switch on";
}
function saveSettings() {
  const out = {};
  let bad = null;
  FIELDS.forEach((k) => {
    if (masked() && PATH_FIELDS[k]) return;      // not editable while masked: the app keeps them as they are
    const raw = $("s_" + k).value.trim();
    $("s_" + k).classList.remove("bad");
    if (NUMS[k]) {
      if (BLANK_ZERO[k] && raw === "") { out[k] = 0; return; }
      if (!/^\d{1,6}$/.test(raw)) { bad = bad || k; return; }
      out[k] = Number(raw);
    } else out[k] = raw;
  });
  if (bad) { $("s_" + bad).classList.add("bad"); $("sErr").textContent = "A whole number is needed here."; return; }
  // folders.js refuses a changed folder whose check line is a ✗, with its words (and calls saveSettings again once a
  // pending check has answered)
  if (!document.dispatchEvent(new CustomEvent("dp:beforesave", { cancelable: true, detail: out }))) return;
  api("/api/settings", { settings: out }).then((r) => {
    $("sErr").textContent = "";
    note("Settings saved." + (r.next_start && r.next_start.length ? " At the next start: " + r.next_start.join(", ") + "." : ""), true);
    if (r.note) note(r.note);       // stays until dismissed: the owner has files to move
    loadSettings(); CARDS_KEY = ""; poll();
  }).catch((e) => {
    $("sErr").textContent = e.message;
    if (e.field && $("s_" + e.field)) $("s_" + e.field).classList.add("bad");
  });
}

// ---- polling and the heartbeat: three failures in a row show "DataPiler has stopped"
function gone() { GONE = true; $("gone").classList.add("on"); }
// Quit closes the tab too (S50). A browser closes a tab its script did not open only while the tab has a single page
// in its history, as the one the launcher opens does; where it refuses, the tab says DataPiler has stopped.
function closeTab() { setTimeout(() => { try { window.close(); } catch (e) { /* the browser refused */ } }, 400); }
function poll() {
  if (GONE || HOLD) return Promise.resolve();
  return api("/api/state").then((s) => {
    FAILS = 0;
    ST = s;
    paintTop(s);
    paintStatus(s);
    paintExtract(s);
    paintJobs(s);
    if (s.outputs_rev !== OUT_REV) {
      OUT_REV = s.outputs_rev;
      if (TAB === "outputs") loadOutputs();
      if (TAB === "imported") loadImported();
      if (TAB === "deleted") loadBin();
    }
    if (TAB === "settings") paintSession(s.session);
    if (!CAT) loadCatalogue();
  }).catch(() => { FAILS += 1; if (FAILS >= 3 && !HOLD) gone(); });
}

// ---- wiring
$("tabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-t]"); if (b) showTab(b.getAttribute("data-t")); });
$("quit").addEventListener("click", () => {
  if (!window.confirm("Quit DataPiler? Its page and its window close.")) return;
  const quit = (cancel) => api("/api/quit", { cancel_running: cancel }).then((r) => {
    if (r.ok) { gone(); closeTab(); return; }
    if (r.ask && window.confirm(r.ask.text)) quit(true);
  }).catch((e) => note(e.message));
  quit(false);
});
$("run").addEventListener("click", () => runRows([...PICK], $("loadMaps").checked, null));
$("cancel").addEventListener("click", () => {
  if (!window.confirm("Stop the Extract run now? It stops between calls; what the row running now has read is lost.")) return;
  api("/api/extract/cancel", {}).then(poll).catch((e) => note(e.message));
});
$("pick").addEventListener("click", (e) => { e.stopPropagation(); $("file").click(); });
$("jobs").addEventListener("dragover", (e) => {
  if (!DRAG) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "move";
  showDrop(dropAt(e.clientY));
});
$("jobs").addEventListener("drop", (e) => {
  if (!DRAG) return;
  e.preventDefault();
  const t = dropAt(e.clientY), ids = cardIds(), id = DRAG, from = ids.indexOf(id);
  showDrop(null);
  DRAG = null;
  if (from < 0) return;
  let at = t.index;
  if (from < at) at -= 1;
  if (at === from) { JOBS_KEY = ""; if (ST) paintJobs(ST); return; }
  ids.splice(from, 1); ids.splice(at, 0, id);
  saveOrder(ids);
});
$("jobs").addEventListener("dragleave", (e) => { if (!$("jobs").contains(e.relatedTarget)) showDrop(null); });
$("foldAll").addEventListener("click", () => { if (ST) { ST.jobs.forEach((j) => setFolded(foldKey(j), true)); JOBS_KEY = ""; paintJobs(ST); } });
$("unfoldAll").addEventListener("click", () => { if (ST) { ST.jobs.forEach((j) => setFolded(foldKey(j), false)); JOBS_KEY = ""; paintJobs(ST); } });
$("drop").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
["dragenter", "dragover"].forEach((t) => $("drop").addEventListener(t, (e) => { e.preventDefault(); $("drop").classList.add("over"); }));
["dragleave", "drop"].forEach((t) => $("drop").addEventListener(t, (e) => { e.preventDefault(); $("drop").classList.remove("over"); }));
$("drop").addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
$("openWork").addEventListener("click", () => api("/api/open", { area: "workspace" }).then((r) => { if (!r.ok) note(r.error); }).catch((e) => note(e.message)));
$("openShare").addEventListener("click", () => api("/api/open", { area: "share" }).then((r) => { if (!r.ok) note(r.error); }).catch((e) => note(e.message)));
$("binEmpty").addEventListener("click", binEmpty);
$("copyPath").addEventListener("click", () => {
  if (!VIEW) return;
  api("/api/copy-path", { name: VIEW }).then((r) => { if (r.ok) note("The file's path is on the clipboard.", true); else note(r.error); }).catch((e) => note(e.message));
});
document.querySelectorAll("#tbar [data-lv]").forEach((c) => c.addEventListener("click", () => {
  TERM.level = c.getAttribute("data-lv");
  document.querySelectorAll("#tbar [data-lv]").forEach((x) => x.classList.toggle("on", x === c));
  paintTerm(); scrollEnd();
}));
$("pause").addEventListener("click", () => { TERM.paused = !TERM.paused; $("pause").textContent = TERM.paused ? "Resume scroll" : "Pause scroll"; scrollEnd(); });
$("copyVis").addEventListener("click", copyVisible);
$("copyShare").addEventListener("click", copyForSharing);
$("sSave").addEventListener("click", saveSettings);
$("sLink").addEventListener("click", () => {
  const on = !(ST && ST.session.link);
  linkSwitch(on).then(() => poll().then(() => paintSession(ST && ST.session))).catch((e) => note(e.message));
});
$("sDebug").addEventListener("click", () => {
  const on = !(ST && ST.session.debug);
  api("/api/debug", { on: on }).then(() => poll().then(() => paintSession(ST && ST.session))).catch((e) => note(e.message));
});
paintSrcChips();
showTab(store.get("dp.tab") || "status");
loadCatalogue();
poll();
pollTerm();
setInterval(poll, 1000);
setInterval(pollTerm, 1000);
