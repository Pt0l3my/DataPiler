"use strict";
// DataPiler's page. `$`, `esc`, `store`, `api`, `note`, `showTab`, the terminal's painting and polling, the file
// drop and the heartbeat are adapted from LLM Jobrunner 1.2's page (build plan §7.1). Every value from DataPiler
// reaches the page through textContent, or through esc() where markup is built.
const TOKEN = "__TOKEN__";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
const JOB_MAX = 256 * 1024;
const TABS = ["status", "extract", "jobs", "outputs", "terminal", "settings"];
const SOURCES = ["app", "page", "smithbox", "link", "extract", "job", "guard", "textdb", "env", "update", "folders"];
const ROW_UNIT = { rows: "rows", maps: "maps", entries: "entries" };

let ST = null, CAT = null, GONE = false, FAILS = 0, TAB = "status", HOLD = false, OV = null;
let OUT_REV = -1, VIEW = null, SETTINGS = null;
let PICK = new Set(), BUNDLE = null, LAST_ROWS = [];
let JOBS_KEY = "", ROWS_KEY = "", CARDS_KEY = "";
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
  if (t === "settings") loadSettings();
  if (t === "terminal") { paintTerm(); scrollEnd(); }
}

// ---- the top bar
const PILLS = {
  smithbox: { running: ["ok", "Smithbox running"], not_running: ["warn", "Smithbox not running"], not_found: ["err", "Smithbox not found"] },
  game: { closed: ["ok", "Game closed"], running: ["err", "Game running"], unknown: ["warn", "Game: not known"] },
  link: { off: ["mute", "Server link off"], on: ["warn", "Server link on (this session)"], blocked: ["err", "Server link blocked"],
          no_libs: ["mute", "Server link: no libraries"] },
};
function pill(id, kind, value) {
  const p = (PILLS[kind] || {})[value] || ["mute", kind];
  const e = $(id);
  e.className = "pill " + p[0];
  e.textContent = "● " + p[1];
}
function paintTop(s) {
  $("ver").textContent = String(s.version || "").split(".").slice(0, 2).join(".");
  pill("pSmithbox", "smithbox", s.pills.smithbox);
  pill("pGame", "game", s.pills.game);
  pill("pLink", "link", s.pills.link);
  $("block").hidden = !s.block;
  $("block").textContent = s.block || "";
}

// ---- Status
const CARD_TITLES = {
  smithbox: ["Smithbox", "Read from Smithbox's own files and its process - nothing in Smithbox is changed"],
  game: ["The game", "Read from its folder and its exe's version resource - nothing in it is changed"],
  project: ["The project", "Smithbox's project folder: never the game's folder, never inside it"],
  link: ["Server link", "Read calls only, from a fixed list; off at every start; closed at once if the game starts"],
};
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
  const key = JSON.stringify(s.status);
  if (key === CARDS_KEY) return;
  CARDS_KEY = key;
  const g = clear($("cards"));
  ["smithbox", "game", "project"].forEach((k) => add(g, cardFor(k, (s.status[k] || []).map(checkRow))));
  add(g, cardFor("link", linkCard(s.status.link || {}, s.session)));
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
  if (j.state === "running" || j.state === "queued" || j.state === "waiting") return el("span", "pill warn", j.state);
  return el("span", "pill mute", j.state);
}
function listCol(title, items) {
  const d = el("div"); add(d, el("b", null, title));
  const ul = el("ul");
  (items || []).forEach((t) => add(ul, add(el("li"), phText(t))));
  if (!items || !items.length) add(ul, el("li", "mute", "nothing"));
  return add(d, ul);
}
function opLine(o) {
  const parts = ["op " + o.n + " " + o.op + ": " + o.state];
  if (o.of) parts.push(fmtN(o.done) + " of " + fmtN(o.of) + (o.unit ? " " + o.unit : ""));
  else if (o.done) parts.push(fmtN(o.done) + (o.unit ? " " + o.unit : ""));
  if (o.secs != null) parts.push(Number(o.secs).toFixed(1) + " s");
  return el("div", null, parts.join(" · "));
}
function jobAct(j, what, confirm) {
  api("/api/jobs/act", { id: j.id, what: what, confirm_maps: confirm == null ? null : confirm }).then((r) => {
    if (r.ok) { poll(); return; }
    if (r.ask && window.confirm(r.ask.text)) jobAct(j, what, r.ask.maps);
  }).catch((e) => note(e.message));
}
function jobCard(j) {
  const c = el("div", "jobcard");
  const head = el("div", "jhead");
  add(head, el("b", null, j.title || j.id || "a job file"));
  if (j.id) add(head, el("span", "pill mute", j.id));
  if (j.format) add(head, el("span", "pill mute", j.format));
  add(head, jobPill(j));
  if (j.sha256) add(head, el("span", "mono mute", "sha256 " + short(j.sha256)));
  add(c, head);
  if (j.preview && j.state !== "refused") {
    const cols = el("div", "cols3");
    add(cols, listCol("Reads", j.preview.reads), listCol("Computes", j.preview.computes), listCol("Writes", j.preview.writes));
    add(c, cols);
  }
  if (j.refusals && j.refusals.length) {
    const r = el("div", "refusals");
    j.refusals.forEach((x) => add(r, el("div", null, (x.op != null ? "op " + x.op + " - " : "") + x.where + ": " + x.text)));
    add(c, r);
  }
  if (j.wait) add(c, el("div", "wait", "Waits: " + j.wait));
  if (j.ops && j.ops.length && ["queued", "waiting", "running", "done", "failed", "cancelled", "stopped"].indexOf(j.state) >= 0) {
    const ol = el("div", "oplines");
    j.ops.forEach((o) => add(ol, opLine(o)));
    add(c, ol);
  }
  if (j.result) {
    const res = el("div", "result");
    if (j.result.share) {
      const sh = j.result.share;
      const line = add(el("div"), "Share file ", el("code", null, sh.name), " - " + fmtSize(sh.size) + " - sha256 " + short(sh.sha256) + " ");
      const show = el("button", "sm", "Show");
      show.addEventListener("click", () => { showTab("outputs"); openShare(sh.name); });
      add(res, add(line, show));
    }
    if (j.result.local && j.result.local.length) add(res, el("div", null, "Workspace: " + j.result.local.join(", ")));
    if (j.result.failed) {
      const f = j.result.failed;
      let t = "Failed at op " + f.op + ": " + f.why;
      if (f.check != null) t += " (check " + f.check + (f.where ? " at " + f.where : "") + ")";
      add(res, el("div", "bad", t));
    }
    add(c, res);
  }
  const act = el("div", "actions");
  const canStart = ["checked", "cancelled", "stopped", "failed", "done"].indexOf(j.state) >= 0;
  const canCancel = ["queued", "waiting", "running"].indexOf(j.state) >= 0;
  if (canStart) { const b = el("button", "pri", j.state === "checked" ? "Start" : "Start again"); b.addEventListener("click", () => jobAct(j, "start")); add(act, b); }
  if (canCancel) { const b = el("button", null, "Cancel"); b.addEventListener("click", () => jobAct(j, "cancel")); add(act, b); }
  if (!canCancel) { const b = el("button", null, "Remove"); b.addEventListener("click", () => jobAct(j, "remove")); add(act, b); }
  add(c, act);
  return c;
}
function paintJobs(s) {
  const key = JSON.stringify(s.jobs);
  if (key === JOBS_KEY) return;
  JOBS_KEY = key;
  const box = clear($("jobs"));
  if (!s.jobs.length) { add(box, el("div", "mute", "No job files yet.")); return; }
  s.jobs.forEach((j) => add(box, jobCard(j)));
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
  return li;
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
    if (r.ok) copyText(r.text, "The lines, checked for sharing,");
    else note("Not copied: line " + r.refused.line + " fails check " + r.refused.check + (r.refused.check === 3 ? " (a text the text database holds)" : " (a path, a name or an address)") + ".");
  }).catch((e) => note(e.message));
}

// ---- Settings
const FIELDS = ["smithbox_dir", "game_dir", "project_dir", "workspace_dir", "share_dir", "language", "expansion", "port", "log_max_mb", "log_keep"];
const NUMS = { port: true, log_max_mb: true, log_keep: true };
// The five folder fields: drawn read-only as their masks while Mask paths on this page is on, and left out of Save.
const PATH_FIELDS = { smithbox_dir: true, game_dir: true, project_dir: true, workspace_dir: true, share_dir: true };
function masked() { return !!(SETTINGS && SETTINGS.settings && SETTINGS.settings.mask_paths); }
function loadSettings() {
  return api("/api/settings").then((r) => {
    SETTINGS = r;
    FIELDS.forEach((k) => { const v = r.settings[k]; $("s_" + k).value = k === "port" && !v ? "" : String(v == null ? "" : v); $("s_" + k).classList.remove("bad"); });
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
      if (k === "port" && raw === "") { out[k] = 0; return; }
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
function poll() {
  if (GONE || HOLD) return Promise.resolve();
  return api("/api/state").then((s) => {
    FAILS = 0;
    ST = s;
    paintTop(s);
    paintStatus(s);
    paintExtract(s);
    paintJobs(s);
    if (s.outputs_rev !== OUT_REV) { OUT_REV = s.outputs_rev; if (TAB === "outputs") loadOutputs(); }
    if (TAB === "settings") paintSession(s.session);
    if (!CAT) loadCatalogue();
  }).catch(() => { FAILS += 1; if (FAILS >= 3 && !HOLD) gone(); });
}

// ---- wiring
$("tabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-t]"); if (b) showTab(b.getAttribute("data-t")); });
$("quit").addEventListener("click", () => {
  if (!window.confirm("Quit DataPiler? Its page and its window close.")) return;
  const quit = (cancel) => api("/api/quit", { cancel_running: cancel }).then((r) => {
    if (r.ok) { gone(); return; }
    if (r.ask && window.confirm(r.ask.text)) quit(true);
  }).catch((e) => note(e.message));
  quit(false);
});
$("run").addEventListener("click", () => runRows([...PICK], $("loadMaps").checked, null));
$("cancel").addEventListener("click", () => api("/api/extract/cancel", {}).then(poll).catch((e) => note(e.message)));
$("pick").addEventListener("click", (e) => { e.stopPropagation(); $("file").click(); });
$("drop").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
["dragenter", "dragover"].forEach((t) => $("drop").addEventListener(t, (e) => { e.preventDefault(); $("drop").classList.add("over"); }));
["dragleave", "drop"].forEach((t) => $("drop").addEventListener(t, (e) => { e.preventDefault(); $("drop").classList.remove("over"); }));
$("drop").addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());
$("openWork").addEventListener("click", () => api("/api/open", { area: "workspace" }).then((r) => { if (!r.ok) note(r.error); }).catch((e) => note(e.message)));
$("openShare").addEventListener("click", () => api("/api/open", { area: "share" }).then((r) => { if (!r.ok) note(r.error); }).catch((e) => note(e.message)));
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
