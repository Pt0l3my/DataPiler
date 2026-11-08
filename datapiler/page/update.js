// The Update... pop-up (design 0002 §2.1, its mock; build plan 0.2 §4.7). It talks to DataPiler only: GET
// /api/update every 0.5 s while it is open, POST /api/update for each press, GET /api/update-result once after the
// page reloads, and, while DataPiler restarts, GET / on this page's own address. The page never talks to GitHub, and
// nothing from GitHub is HTML here: the release notes come as a tree of text (§4.4), built with createElement and
// textContent; a link in them shows its address and does not open. The one way out is Open the release page, a plain
// link to the address the app checked. One IIFE, defining nothing global; it uses app.js's shared functions.
(() => {
  const RELEASES = /^https:\/\/github\.com\/Pt0l3my\/DataPiler\/releases\/[A-Za-z0-9\/._:-]*$/;   // as the app checks it
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const STAGES = { checks: "checking its request", verify: "checking the download again", plan: "planning the swap",
                   backup: "backing up", write: "writing files", remove: "removing files",
                   manifest: "writing the manifest", done: "finishing", rollback: "going back" };
  const FLAG = "dp.update";
  const BACK_MS = 90 * 1000;

  let H = null;           // the open overlay's parts
  let TIMER = null;       // the 0.5 s poll while it is open
  let SHOWN = null;       // the view painted last
  let KEY = "";           // its key: a poll that changes nothing repaints nothing
  let BUSY = false;       // a press on its way
  let LEAVING = false;    // Install answered: DataPiler is restarting

  // ---- small helpers
  function date(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? Number(m[3]) + " " + MONTHS[Number(m[2]) - 1] + " " + m[1] : "";
  }
  function mib(b) { return (Number(b) / 1048576).toFixed(1) + " MiB"; }
  function mb(b) { return (Number(b) / 1000000).toFixed(1) + " MB"; }
  function rate(b) { return Math.max(0, Math.round(Number(b) / 1024)).toLocaleString("en-GB") + " KiB/s"; }
  function flag(on) {
    try { if (on) sessionStorage.setItem(FLAG, "1"); else sessionStorage.removeItem(FLAG); } catch (e) { /* off */ }
  }
  function flagged() { try { return sessionStorage.getItem(FLAG) === "1"; } catch (e) { return false; } }
  function btn(text, cls, fn) {
    const b = el("button", cls || null, text);
    b.addEventListener("click", fn);
    return b;
  }
  function box(kind, text) { return el("div", "up-box" + (kind ? " " + kind : ""), text); }
  function kv(rows) {
    const g = el("div", "up-kv");
    rows.forEach((r) => { if (r) add(g, el("div", "up-k", r[0]), typeof r[1] === "string" ? el("div", null, r[1]) : r[1]); });
    return g;
  }
  function releaseLink(v) {
    const page = v && v.latest && v.latest.page;
    if (typeof page !== "string" || !RELEASES.test(page)) return null;
    const a = el("a", "up-link left", "Open the release page ↗");
    a.href = page;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  }

  // ---- the release notes: a tree of blocks, never HTML (build plan 0.2 §4.4)
  function parts(parent, ps) {
    (ps || []).forEach((p) => {
      const v = String(p && p.v != null ? p.v : "");
      if (p.t === "b") add(parent, el("b", null, v));
      else if (p.t === "i") add(parent, el("i", null, v));
      else if (p.t === "code") add(parent, el("code", null, v));
      else if (p.t === "link") add(parent, el("span", "up-lt", v), " ", el("span", "up-href", String(p.href || "")));
      else if (p.t === "image") add(parent, el("span", "mute", "[image: " + v + "]"));
      else add(parent, v);
    });
    return parent;
  }
  function notes(blocks, cut) {
    const out = el("div", "up-notes");
    let list = null, ordered = null;
    (blocks || []).forEach((b) => {
      if (b.k === "li") {
        const want = b.n != null;
        if (!list || ordered !== want) {
          list = el(want ? "ol" : "ul");
          if (want && Number(b.n) > 1) list.start = Number(b.n);
          ordered = want;
          add(out, list);
        }
        add(list, parts(el("li"), b.parts));
        return;
      }
      list = null;
      if (b.k === "h") add(out, parts(el(Number(b.level) <= 2 ? "h4" : "h5", "up-h"), b.parts));
      else if (b.k === "code") add(out, el("pre", "up-code", String(b.v || "")));
      else add(out, parts(el("p"), b.parts));
    });
    if (cut) add(out, el("p", "mute", "… the rest is on the release page"));
    return out;
  }

  // ---- the pop-up's states
  function latestRows(v) {
    const l = v.latest || {};
    const rows = [["This version", v.this]];
    if (l.version) {
      const when = date(l.published);
      const val = el("div");
      add(val, v.state === "newer" ? el("b", null, l.version) : l.version, when ? " · published " + when : "");
      rows.push(["Latest release", val]);
    }
    return rows;
  }
  function checkLines(checks) {
    const ul = el("ul", "up-steps");
    (checks || []).forEach((c) => add(ul, add(el("li"), mark(c.ok), el("span", null, c.text))));
    return ul;
  }
  function failedBox(f) {
    return f ? box(f.kept ? "warn" : "err", f.text) : null;
  }

  function paint(v) {
    if (!H) return;
    const body = clear(H.body), foot = clear(H.foot);
    const close = btn("Close", null, () => H && H.close());
    const again = btn("Check again", null, () => press({ action: "check", fresh: true }));
    const s = v.state;
    if (s === "idle" || s === "checking") {
      add(body, el("div", null, "Asking GitHub for the latest release "), el("span", "mute", "(api.github.com)…"));
      add(foot, btn("Cancel", null, () => H && H.close()));
    } else if (s === "up_to_date") {
      add(body, kv(latestRows(v)), box("ok", "✓ You have the latest release."));
      add(foot, releaseLink(v), close);
    } else if (s === "older") {
      add(body, kv(latestRows(v)), box(null, "This build (" + v.this + ") is newer than the latest release (" +
        ((v.latest && v.latest.version) || "?") + "). Nothing to download."));
      add(foot, releaseLink(v), close);
    } else if (s === "none") {
      add(body, kv([["This version", v.this]]), box(null, "No release is published yet."));
      add(foot, close, again);
    } else if (s === "not_installable") {
      add(body, kv(latestRows(v)), box("warn", v.why || "This release cannot be installed from here."));
      add(foot, releaseLink(v), close, again);
    } else if (s === "newer") {
      paintNewer(v, body, foot, close);
    } else if (s === "downloading") {
      paintDownloading(v, body, foot);
    } else if (s === "ready") {
      paintReady(v, body, foot);
    } else {
      // failed
      add(body, failedBox(v.failed) || box("err", "The update stopped."));
      if (v.checks && v.checks.length) add(body, checkLines(v.checks));
      if (v.failed && v.failed.stage === "check") {
        add(body, el("div", "mute up-gap", "Only api.github.com was asked. DataPiler makes no other call."));
      }
      add(foot, close, again);
    }
    add(body, el("div", "up-err"));
    const pri = foot.querySelector("button.pri") || foot.querySelector("button:last-child");
    if (pri) setTimeout(() => { if (H && H.box.contains(pri)) pri.focus(); }, 0);
  }

  function paintNewer(v, body, foot, close) {
    const l = v.latest || {};
    const rows = latestRows(v);
    if (l.zip) {
      const d = el("div");
      add(d, el("span", "mono", l.zip.name), " · " + mib(l.zip.size) + " (" + mb(l.zip.size) + ")");
      rows.push(["Download", d]);
    }
    const sum = el("div");
    add(sum, mark(true), " published beside it (", el("span", "mono", l.sha256_file || ""), ")",
        l.digest ? ", and GitHub states its own digest" : "");
    rows.push(["Checksum", sum]);
    rows.push(["Python libraries", el("div", "mute", "known once the download is checked")]);
    add(body, kv(rows));
    if (l.notes && l.notes.length) add(body, notes(l.notes, l.notes_cut));
    add(body, el("div", "mute up-small", "The notes are the release's own text, shown as text: headings, lists, " +
      "bold, code. Links show their address and do not open from here."));
    add(foot, releaseLink(v), close,
        btn("Download " + (l.zip ? mib(l.zip.size) : ""), "pri", () => press({ action: "download" })));
  }

  function progressText(p) {
    return mib(p.done).replace(" MiB", "") + " of " + mib(p.of) + " · " + rate(p.rate);
  }
  function paintDownloading(v, body, foot) {
    const l = v.latest || {}, p = v.progress || { done: 0, of: (l.zip && l.zip.size) || 0, rate: 0 };
    const head = el("div", "up-gap-b");
    add(head, "Downloading ", el("span", "mono", (l.zip && l.zip.name) || ""), " into ",
        el("span", "mono", "update\\" + (l.version || "") + "\\"));
    const bar = el("progress", "up-bar");
    bar.max = Math.max(1, Number(p.of) || 1);
    bar.value = Math.min(bar.max, Number(p.done) || 0);
    bar.id = "upBar";
    const said = el("div", "mute", progressText(p) + " · from GitHub's release files");
    said.id = "upSaid";
    add(body, head, bar, said);
    add(foot, btn("Cancel", null, () => press({ action: "cancel" })));
  }
  function moveProgress(v) {
    const bar = $("upBar"), said = $("upSaid"), p = v.progress;
    if (!bar || !said || !p) return false;
    bar.max = Math.max(1, Number(p.of) || 1);
    bar.value = Math.min(bar.max, Number(p.done) || 0);
    said.textContent = progressText(p) + " · from GitHub's release files";
    return true;
  }

  function paintReady(v, body, foot) {
    const l = v.latest || {}, p = v.plan || {};
    add(body, checkLines(v.checks));
    const what = el("div", "up-box");
    add(what, el("b", null, "Install and restart"), " stops DataPiler. Its window then replaces " + fmtN(p.write) +
        " files, adds " + fmtN(p.add) + " and removes " + fmtN(p.remove) + " (kept in the backup), and starts " +
        (l.version || "the new version") + ". Your workspace, share, logs, jobs, settings and Python environment " +
        "stay as they are. If any step fails, the window puts " + v.this + " back and starts it.");
    add(body, what);
    if (p.edited) {
      add(body, box("warn", fmtN(p.edited) + " of DataPiler's own files were edited here since the last release: " +
        "the edited copies go into the backup, and logs\\update.log names them."));
    }
    const libs = el("div", "up-line");
    if (p.libs) add(libs, mark("warn"), " Python libraries: changed - after the restart the window asks Y to fetch " +
                    "them from pypi.org, as at the first start");
    else add(libs, mark(true), " Python libraries: unchanged");
    add(body, libs);
    add(body, box("warn", "DataPiler.exe is not code-signed. This one was built by the release workflow from the " +
      "repository's source, and its checksum is the release's. Nothing downloaded starts until you press Install " +
      "and restart."));
    add(body, failedBox(v.failed));
    add(body, el("div", "mute up-small", "A download not installed is removed when DataPiler next starts."));
    const discard = btn("Discard the download", "left", () => press({ action: "cancel" }));
    add(foot, discard, btn("Later", null, () => H && H.close()),
        btn("Install and restart", "pri", () => press({ action: "install" })));
  }

  function show(v) {
    if (!H || LEAVING || !v || typeof v.state !== "string") return;
    if (SHOWN && SHOWN.state === "downloading" && v.state === "downloading" && moveProgress(v)) { SHOWN = v; return; }
    const key = JSON.stringify(v);
    SHOWN = v;
    if (key === KEY) return;
    KEY = key;
    paint(v);
  }
  function problem(text) {
    const line = H && H.body.querySelector(".up-err");
    if (line) line.textContent = String(text || "DataPiler did not answer.");
  }

  // ---- presses and the poll
  function press(body) {
    if (BUSY || LEAVING) return;
    BUSY = true;
    api("/api/update", body).then((v) => {
      BUSY = false;
      if (body.action === "install" && v && v.ok === true && v.state === "restarting") restarting(v);
      else show(v);
    }).catch((e) => { BUSY = false; problem(e && e.message); });
  }
  function tick() { if (!LEAVING) api("/api/update").then(show).catch(() => {}); }
  function open() {
    if (H) return;
    SHOWN = { state: "checking" };
    KEY = "";
    H = overlay("Update DataPiler", { opener: $("btn-update"), onClose: closed });
    paint({ state: "checking" });
    press({ action: "check", fresh: false });
    TIMER = setInterval(tick, 500);
  }
  function closed() {
    if (TIMER) clearInterval(TIMER);
    TIMER = null;
    H = null;
    const s = SHOWN && SHOWN.state;
    if (!LEAVING && (s === "checking" || s === "downloading")) api("/api/update", { action: "cancel" }).catch(() => {});
  }

  // ---- restarting: DataPiler stops, its window swaps the files, the new version answers on this address
  function restarting(v) {
    LEAVING = true;
    if (TIMER) clearInterval(TIMER);
    TIMER = null;
    holdHeartbeat(true);
    flag(true);
    if (H) {
      const body = clear(H.body);
      clear(H.foot);
      const steps = el("ul", "up-steps");
      add(steps, add(el("li"), mark(true), el("span", null, "DataPiler " + (SHOWN ? SHOWN.this : "") + " stopped")));
      add(steps, add(el("li"), el("span", "m unk", "…"), el("span", null, "The DataPiler window is replacing files - " +
        "it shows each step")));
      add(steps, add(el("li"), el("span", "m unk", "○"), el("span", "mute", "Waiting for DataPiler " + (v.to || "") +
        " to answer on this address")));
      add(body, steps, el("div", "mute up-gap", "This page reloads by itself when DataPiler is back."));
    }
    const t0 = Date.now();
    let said = false;
    const wait = setInterval(() => {
      if (!said && Date.now() - t0 > BACK_MS) {
        said = true;
        const msg = "DataPiler did not come back on this address - it may have opened a new tab, or its window says " +
          "why";
        if (H) add(H.body, box("warn", msg)); else note(msg);
      }
      fetch("/", { cache: "no-store" }).then((r) => (r.ok ? r.text() : "")).then((text) => {
        if (text && text.indexOf(TOKEN) < 0) { clearInterval(wait); location.reload(); }
      }).catch(() => { /* still away */ });
    }, 2000);
  }

  // ---- after the reload: the result, once
  function showResult(r) {
    H = overlay("Update DataPiler", { opener: $("btn-update"), onClose: () => { H = null; } });
    const body = H.body, foot = H.foot;
    const c = r.counts || {}, chk = r.check || {};
    if (r.state === "updated") {
      add(body, box("ok", "✓ Updated to " + r.to + " - " + fmtN(c.written || 0) + " files written, " +
        fmtN(c.added || 0) + " added, " + fmtN(c.removed || 0) + " removed." +
        (chk.manifest && !chk.differ ? " All " + fmtN(chk.files) + " files match the release." : "")));
      if (chk.differ) add(body, box("warn", fmtN(chk.differ) + " files differ from the release - the Terminal tab's " +
        "install check names them."));
      const after = el("div", "mute up-gap");
      add(after, r.from + "'s files are kept in ", el("span", "mono", (r.backup || "update") + "\\"),
          " until the next update. ", el("span", "mono", r.log || "logs\\update.log"), " has each step.");
      add(body, after);
    } else if (r.state === "rolled_back") {
      // r.text: a swap cut off part way, which the window put back without R
      add(body, box("ok", "✓ Back on " + r.to + ": " + (r.text ? r.text + "." : "the update to " + r.from +
        " was undone (R), and its files were put back.")));
      add(body, el("div", "mute up-gap", "logs\\update.log has each step."));
    } else if (r.state === "refused") {
      add(body, box("err", "The update was refused before anything was touched" + (r.text ? ": " + r.text : ".") +
        " You are on " + (r.from || "the version before") + "."));
      add(body, el("div", "mute up-gap", "logs\\update.log has each step. Press Update… to try again."));
    } else {
      const where = STAGES[r.stage] ? " while " + STAGES[r.stage] : "";
      const back = r.restored === false ? " Some files could not be put back - their copies are in " +
        (r.backup || "update") + "\\." : " Every file was put back - you are on " + (r.from || "the version before") + ".";
      add(body, box("err", "The update stopped" + where + (r.text ? ": " + r.text : ".") + back));
      add(body, el("div", "mute up-gap", "logs\\update.log has each step. The download was removed when DataPiler " +
        "started again: press Update… to fetch it anew."));
    }
    add(foot, btn("Close", "pri", () => H && H.close()));
  }

  function afterReload() {
    // Asked once at every load, not only with the flag: when DataPiler came back on another port it opened a new
    // tab, which has no flag. The result is served once, so it shows once.
    const had = flagged();
    flag(false);
    api("/api/update-result").then((r) => {
      if (r && typeof r.state === "string" && ["updated", "failed", "refused", "rolled_back"].indexOf(r.state) >= 0) {
        showResult(r);
      }
    }).catch(() => { if (had) note("The update's result could not be read - logs\\update.log has each step."); });
  }

  const b = $("btn-update");
  if (b) b.addEventListener("click", open);
  afterReload();
})();
