// The Settings rows' behaviour and the folder picker (build plan 0.2 section 5.9). One IIFE: nothing global.
// Written afresh from design 0002 section 3. Every value from DataPiler reaches the page through textContent.
(() => {
  const ROWS = { smithbox_dir: "smithbox", game_dir: "game", project_dir: "project" };
  const TITLES = { smithbox: "Set the Smithbox folder", game: "Set the game folder", project: "Set the project folder" };
  const MARK_WORD = { smithbox: "Smithbox exe", game: "eldenring.exe", project: "project file" };
  const KIND_WORD = { local: "local", removable: "removable", network: "network", cdrom: "CD/DVD", ram: "RAM disk", unknown: "drive" };
  let VIEW = null;                         // the last /api/settings answer
  const CHECKS = {};                       // key -> { value, check } of the field's last check line
  const TIMERS = {};

  const row = (key) => document.querySelector('.fr-row[data-key="' + key + '"]');
  const part = (scope, name) => scope && scope.querySelector('[data-part="' + name + '"]');
  const isMasked = () => !!(VIEW && VIEW.settings && VIEW.settings.mask_paths);
  const mapGl = () => !(VIEW && VIEW.settings && VIEW.settings.map_opengl === false);
  const shownOf = (x) => (x && x.shown != null ? x.shown : (x && x.path) || "");

  function checkLine(box, c) {
    clear(box);
    if (!c) return;
    add(box, mark(c.ok === "warn" ? "warn" : c.ok), " ", el("span", null, c.text));
  }
  function saved(text) { note(text || "Saved in Settings.", true); CARDS_KEY = ""; poll(); loadSettings(); }
  function failed(e) { note(e.message || String(e)); }
  function saveOne(key, value) { return api("/api/settings/one", { key: key, value: value }).then(() => saved()); }

  // ---- the rows
  function paintFound(key, want, box, found, notes) {
    clear(box);
    const list = found || [];
    if (!list.length && !(notes && notes.length)) { box.hidden = true; return; }
    box.hidden = false;
    const head = want === "expansion"
      ? (list.length > 1 ? "Steam's app manifest does not say which DLC app is the expansion - choose one, or leave it as it is" : list.length ? "Detect found 1 answer" : "Detect found nothing")
      : list.length === 1 ? "Detect found 1 place" : list.length ? "Detect found " + list.length + " places - choose one, or leave the folder as it is" : "Detect found nothing";
    add(box, el("div", "fr-hd", head));
    list.forEach((c) => {
      const it = el("div", "fr-it");
      if (want === "expansion") {
        const v = el("span", null, c.value === "yes" ? "Yes" : "No");
        if (c.detail) add(v, el("span", "mute", " · " + c.detail));
        add(it, v);
      } else {
        const p = el("span", "mono fr-path", shownOf(c));
        if (c.name) add(p, el("span", "mute", " · " + c.name));
        add(it, p);
      }
      const tags = el("span", "fr-tags");
      (c.tags || []).forEach((t, i) => add(tags, el("span", "fr-tag" + (i === 0 ? " acc" : ""), t)));
      add(it, tags);
      if (c.in_use) add(it, el("span", "mute", "in use"));
      else {
        const b = el("button", "sm" + (list.length === 1 ? " pri" : ""), "Use");
        const bad = c.check && c.check.ok === false;
        b.disabled = !!bad;
        if (bad) b.title = c.check.text;
        b.addEventListener("click", () => saveOne(key, want === "expansion" ? c.value : c.path).catch(failed));
        add(it, b);
      }
      if (c.check && want !== "expansion") {
        const cl = el("div", "fr-sub");
        checkLine(cl, c.check);
        add(it, cl);
      }
      add(box, it);
    });
    (notes || []).forEach((n) => add(box, el("div", "fr-note", n)));
  }
  function paintRecent(key, box, recent) {
    clear(box);
    const list = (recent || []).filter((r) => !VIEW || r.path !== VIEW.settings[key]);
    if (!list.length) { box.hidden = true; return; }
    box.hidden = false;
    add(box, el("span", "mute", "Recent: "));
    list.forEach((r) => {
      add(box, el("span", "mono", shownOf(r)), " ");
      const b = el("button", "sm", "Use");
      b.addEventListener("click", () => saveOne(key, r.path).catch(failed));
      add(box, b, " · ");
    });
    const forget = el("button", "sm linklike", "forget recent folders");
    forget.addEventListener("click", () => api("/api/dirs/forget", { key: key }).then(() => saved("The recent folders are forgotten.")).catch(failed));
    add(box, forget);
  }
  function paint(r) {
    VIEW = r;
    const m = isMasked();
    $("frMasked").hidden = !m;
    Object.keys(PATH_FIELDS).forEach((k) => {
      const f = $("s_" + k);
      f.readOnly = m;
      f.classList.toggle("ro", m);
      if (m) {
        const sh = (r.folders && r.folders[k]) ? r.folders[k].shown : (r.shown || {})[k];
        f.value = sh != null ? sh : "";
      }
    });
    Object.keys(ROWS).forEach((key) => {
      const info = (r.folders || {})[key] || {};
      const box = row(key);
      CHECKS[key] = { value: r.settings[key] || "", check: info.check || null };
      checkLine(part(box, "check"), info.check);
      paintFound(key, ROWS[key], part(box, "found"), info.found, info.notes);
      paintRecent(key, part(box, "recent"), info.recent);
      box.querySelectorAll("button[data-act]").forEach((b) => { b.disabled = false; });
    });
    const exp = document.querySelector(".fr-exp");
    paintFound("expansion", "expansion", part(exp, "found"), (r.expansion || {}).found, (r.expansion || {}).notes);
    $("sMask").textContent = m ? "Switch off" : "Switch on";
    $("sGl").textContent = mapGl() ? "Switch off" : "Switch on";
  }

  function runCheck(key) {
    const f = $("s_" + key);
    const value = f.value.trim();
    return api("/api/dirs/check", { want: ROWS[key], path: value }).then((c) => {
      if (f.value.trim() !== value) return null;          // typed on since: the next check answers
      CHECKS[key] = { value: value, check: c };
      checkLine(part(row(key), "check"), c);
      f.classList.toggle("bad", c.ok === false);
      return c;
    });
  }
  Object.keys(ROWS).forEach((key) => {
    const f = $("s_" + key);
    f.addEventListener("input", () => {
      if (isMasked()) return;
      clearTimeout(TIMERS[key]);
      TIMERS[key] = setTimeout(() => runCheck(key).catch(() => {}), 300);
    });
    const r = row(key);
    r.querySelector('[data-act="detect"]').addEventListener("click", (e) => detect(key, ROWS[key], e.currentTarget));
    r.querySelector('[data-act="pick"]').addEventListener("click", (e) => openPicker(key, ROWS[key], e.currentTarget));
  });
  document.querySelector('.fr-exp [data-act="detect"]').addEventListener("click", (e) => detect("expansion", "expansion", e.currentTarget));

  function detect(key, want, button) {
    button.disabled = true;
    const was = button.textContent;
    button.textContent = "Detecting…";
    api("/api/detect", { want: want }).then((d) => {
      button.disabled = false; button.textContent = was;
      const scope = key === "expansion" ? document.querySelector(".fr-exp") : row(key);
      paintFound(key, want, part(scope, "found"), d.found, d.notes);
      if (VIEW) {
        if (key === "expansion") VIEW.expansion = { found: d.found, notes: d.notes };
        else if (VIEW.folders && VIEW.folders[key]) { VIEW.folders[key].found = d.found; VIEW.folders[key].notes = d.notes; }
      }
      CARDS_KEY = ""; poll();
    }).catch((e) => { button.disabled = false; button.textContent = was; failed(e); });
  }

  // Save on the page: a changed folder whose check line is a ✗ is refused with its words; a check still pending is
  // asked first, and Save runs again when every changed folder has answered.
  let resaving = false;
  document.addEventListener("dp:beforesave", (e) => {
    if (!VIEW || isMasked()) return;
    const changed = Object.keys(ROWS).filter((k) => (e.detail[k] || "") !== (VIEW.settings[k] || ""));
    const pending = changed.filter((k) => !CHECKS[k] || CHECKS[k].value !== (e.detail[k] || ""));
    if (pending.length && !resaving) {
      e.preventDefault();
      Promise.all(pending.map((k) => runCheck(k))).then(() => { resaving = true; try { saveSettings(); } finally { resaving = false; } }).catch(failed);
      return;
    }
    const bad = changed.find((k) => CHECKS[k] && CHECKS[k].check && CHECKS[k].check.ok === false);
    if (bad) {
      e.preventDefault();
      $("s_" + bad).classList.add("bad");
      $("sErr").textContent = CHECKS[bad].check.text + " - nothing is saved while this shows.";
    }
  });
  document.addEventListener("dp:settings", (e) => paint(e.detail));
  $("sMask").addEventListener("click", () => saveOne("mask_paths", !isMasked()).catch(failed));
  $("sGl").addEventListener("click", () => saveOne("map_opengl", !mapGl()).catch(failed));

  // ---- the picker (design 0002 section 3.2), drawn in the page in the one overlay
  function openPicker(key, want, opener) {
    const info = (VIEW && VIEW.folders && VIEW.folders[key]) || {};
    const detected = (info.found || []).map((c) => ({ path: c.path, shown: shownOf(c), tags: c.tags || [] }));
    const recent = (info.recent || []).map((r) => ({ path: r.path, shown: shownOf(r), tags: ["used here before"] }));
    const P = { key: key, want: want, view: "list", data: null, sel: 0, filter: "", rows: [], seq: 0, timer: null };
    const ov = overlay(TITLES[want], { opener: opener, wide: true });
    ov.box.classList.add("pk");
    const crumbs = el("div", "pk-crumbs");
    const places = el("div", "pk-places");
    const chipPC = el("button", "chip", "This PC");
    const chipDet = el("button", "chip", "Detected (" + detected.length + ")");
    const chipRec = el("button", "chip", "Recent (" + recent.length + ")");
    chipDet.disabled = !detected.length; chipRec.disabled = !recent.length;
    const newBtn = el("button", "sm", "New folder…");
    newBtn.hidden = want !== "project";
    add(places, chipPC, chipDet, chipRec, el("span", "spacer"), newBtn);
    const filter = el("input", "pk-filter");
    filter.type = "text"; filter.placeholder = "Type to filter this folder"; filter.spellcheck = false;
    filter.setAttribute("aria-label", "Filter this folder");
    const list = el("div", "pk-list");
    list.tabIndex = 0;
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Folders");
    const chosen = el("div", "pk-chosen");
    const newBox = el("div", "pk-new");
    newBox.hidden = true;
    const keys = el("div", "pk-keys", "↑ ↓ move · Home and End · Enter opens · Backspace or Alt+↑ goes up · Ctrl+Enter chooses the folder shown · Esc closes. Folders only - no file is listed.");
    add(ov.body, crumbs, places, filter, list, newBox, chosen, keys);
    const up = el("button", "left", "↑ Up");
    const cancel = el("button", null, "Cancel");
    const choose = el("button", "pri", "Choose this folder");
    add(ov.foot, up, cancel, choose);
    cancel.addEventListener("click", () => ov.close());

    function setChips() {
      chipPC.classList.toggle("on", P.view === "drives");
      chipDet.classList.toggle("on", P.view === "detected");
      chipRec.classList.toggle("on", P.view === "recent");
    }
    function paintCrumbs() {
      clear(crumbs);
      const pc = el("button", "pk-crumb", "This PC");
      pc.addEventListener("click", () => go(""));
      add(crumbs, pc);
      const cs = (P.view === "list" && P.data && P.data.crumbs) || [];
      cs.forEach((c) => {
        add(crumbs, el("span", "pk-sep", "›"));
        const b = el("button", "pk-crumb", c.name);
        b.addEventListener("click", () => go(c.path));
        add(crumbs, b);
      });
    }
    function paintChosen() {
      clear(chosen);
      const d = P.data;
      if (P.view !== "list" || !d || !d.path) {
        add(chosen, el("span", "mute", "Open a folder to choose it."));
        choose.disabled = true;
        return;
      }
      add(chosen, el("span", "mute", "Choose: "), el("span", "mono", d.shown != null ? d.shown : d.path));
      if (d.check) { const l = el("div"); checkLine(l, d.check); add(chosen, l); }
      choose.disabled = !d.check || d.check.ok === false;
    }
    function rowsNow() {
      const f = P.filter.toLowerCase();
      if (P.view === "detected" || P.view === "recent") {
        const src = P.view === "detected" ? detected : recent;
        return src.filter((x) => !f || String(x.shown).toLowerCase().indexOf(f) >= 0)
          .map((x) => ({ label: x.shown, path: x.path, tags: x.tags, mark: false }));
      }
      const d = P.data;
      if (!d) return [];
      if (P.view === "drives" || (d.path === "" && d.drives)) {
        return (d.drives || []).filter((x) => !f || x.name.toLowerCase().indexOf(f) >= 0)
          .map((x) => ({ label: x.name, path: x.path, tags: [KIND_WORD[x.kind] || "drive"], mark: false }));
      }
      // Each folder is drawn by its shown name (masked with Mask paths on) and opened by its real path.
      const base = d.path;
      const sep = /^[A-Za-z]:/.test(base) ? "\\" : "/";
      return (d.dirs || []).map((x) => ({ label: x.shown != null ? x.shown : x.name, name: x.name,
        path: x.path || base.replace(/[\\/]+$/, "") + sep + x.name, tags: [], mark: !!x.mark }))
        .filter((r) => !f || r.label.toLowerCase().indexOf(f) >= 0 || r.name.toLowerCase().indexOf(f) >= 0);
    }
    function paintList() {
      clear(list);
      const d = P.data;
      if (P.view === "list" && d && d.refused) { add(list, el("div", "pk-msg", d.refused)); P.rows = []; return; }
      P.rows = rowsNow();
      if (P.sel >= P.rows.length) P.sel = Math.max(0, P.rows.length - 1);
      if (P.view === "list" && d && d.note) add(list, el("div", "pk-msg", d.note));
      if (!P.rows.length && !(P.view === "list" && d && d.note)) add(list, el("div", "pk-msg mute", P.filter ? "No folder here matches the filter." : "No folders here."));
      P.rows.forEach((r, i) => {
        const it = el("div", "pk-row" + (i === P.sel ? " sel" : ""));
        it.setAttribute("role", "option");
        it.setAttribute("aria-selected", i === P.sel ? "true" : "false");
        add(it, el("span", "pk-ico"), el("span", "pk-nm" + (P.view === "list" ? "" : " mono"), r.label));
        if (r.mark) add(it, el("span", "fr-tag acc", MARK_WORD[want]));
        (r.tags || []).forEach((t) => add(it, el("span", "fr-tag", t)));
        it.addEventListener("click", () => { P.sel = i; paintSel(); });
        it.addEventListener("dblclick", () => go(r.path));
        add(list, it);
      });
      if (P.view === "list" && d && d.more) add(list, el("div", "pk-msg mute", "and " + fmtN(d.more) + " more - type to filter"));
    }
    function paintSel() {
      Array.prototype.forEach.call(list.querySelectorAll(".pk-row"), (it, i) => {
        it.classList.toggle("sel", i === P.sel);
        it.setAttribute("aria-selected", i === P.sel ? "true" : "false");
        if (i === P.sel && it.scrollIntoView) it.scrollIntoView({ block: "nearest" });
      });
    }
    function paintAll() { setChips(); paintCrumbs(); paintList(); paintChosen(); up.disabled = P.view !== "list" || !P.data || P.data.path === ""; }
    function go(path, keepFilter) {
      P.view = "list";
      if (!keepFilter) { P.filter = ""; filter.value = ""; }
      newBox.hidden = true;
      const seq = ++P.seq;
      const body = { path: path, want: want };
      if (keepFilter && P.filter) body.filter = P.filter;
      return api("/api/dirs", body).then((d) => {
        if (seq !== P.seq) return;
        P.data = d; P.sel = 0;
        if (d.path === "" && d.drives) P.view = "drives";
        paintAll();
        if (!ov.box.contains(document.activeElement) || document.activeElement.closest(".pk-new")) list.focus();
      }).catch((e) => { if (seq === P.seq) { P.data = { refused: e.message }; paintAll(); } });
    }
    function show(view) {
      P.view = view; P.sel = 0; P.filter = ""; filter.value = "";
      if (view === "drives") go("").then(() => list.focus()); else { paintAll(); list.focus(); }
    }
    function goUp() {
      // The parent's real path, never the crumbs, which a mask draws as one placeholder for several folders.
      const d = P.data;
      if (P.view !== "list" || !d || d.path === "") return;
      if (typeof d.parent === "string") { go(d.parent); return; }
      const cs = d.crumbs || [];
      go(cs.length >= 2 ? cs[cs.length - 2].path : "");
    }
    function openSel() { const r = P.rows[P.sel]; if (r) go(r.path); }
    function chooseShown() {
      const d = P.data;
      if (P.view !== "list" || !d || !d.path || choose.disabled) return;
      choose.disabled = true;
      api("/api/settings/one", { key: key, value: d.path }).then(() => { ov.close(); saved(); }).catch((e) => {
        clear(chosen); add(chosen, mark(false), " ", el("span", null, e.message)); choose.disabled = false;
      });
    }
    chipPC.addEventListener("click", () => show("drives"));
    chipDet.addEventListener("click", () => show("detected"));
    chipRec.addEventListener("click", () => show("recent"));
    up.addEventListener("click", goUp);
    choose.addEventListener("click", chooseShown);
    function filtered() {
      P.filter = filter.value; P.sel = 0; paintList();
      if (P.view === "list" && P.data && (P.data.more || P.data.filtered)) {
        clearTimeout(P.timer);
        P.timer = setTimeout(() => { const keep = P.data.path; go(keep, true).then(() => { if (P.data) P.data.filtered = !!P.filter; }); }, 300);
      }
    }
    filter.addEventListener("input", filtered);
    newBtn.addEventListener("click", () => {
      if (P.view !== "list" || !P.data || !P.data.path) { note("Open the folder to make the new one in first."); return; }
      clear(newBox);
      newBox.hidden = false;
      const name = el("input", "pk-filter");
      name.type = "text"; name.placeholder = "The new folder's name"; name.spellcheck = false;
      name.setAttribute("aria-label", "The new folder's name");
      const make = el("button", "sm pri", "Make it");
      const why = el("div", "pk-why");
      make.addEventListener("click", () => api("/api/dirs/new", { parent: P.data.path, name: name.value, want: "project" }).then((r) => {
        if (r.refused) { why.textContent = r.refused; return; }
        newBox.hidden = true; go(r.path);
      }).catch((e) => { why.textContent = e.message; }));
      name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); make.click(); } });
      add(newBox, el("span", "mute", "New folder in the folder shown: "), name, make, why);
      name.focus();
    });
    ov.box.addEventListener("keydown", (e) => {
      const t = e.target;
      const inName = t && t.closest && t.closest(".pk-new");
      if (inName) return;
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); chooseShown(); return; }
      if (t === filter && !["ArrowUp", "ArrowDown", "Enter", "Home", "End"].includes(e.key) && !(e.altKey && e.key === "ArrowUp")) return;
      if (e.altKey && e.key === "ArrowUp") { e.preventDefault(); goUp(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); P.sel = Math.min(P.rows.length - 1, P.sel + 1); paintSel(); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); P.sel = Math.max(0, P.sel - 1); paintSel(); return; }
      if (e.key === "Home") { e.preventDefault(); P.sel = 0; paintSel(); return; }
      if (e.key === "End") { e.preventDefault(); P.sel = Math.max(0, P.rows.length - 1); paintSel(); return; }
      if (e.key === "Enter" && (t === list || t === filter)) { e.preventDefault(); openSel(); return; }
      if (e.key === "Backspace" && t !== filter && !(t && t.tagName === "INPUT")) { e.preventDefault(); goUp(); return; }
      if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey && t !== filter && !(t && (t.tagName === "INPUT" || t.tagName === "BUTTON" && e.key === " "))) {
        // typing goes to the filter, its first letter with it
        e.preventDefault();
        filter.focus();
        filter.value += e.key;
        filtered();
      }
    });
    // Opened on Detected when it has places, else at the field's folder, else on This PC.
    if (detected.length) { P.view = "detected"; paintAll(); setTimeout(() => list.focus(), 0); }
    else {
      const start = (VIEW && VIEW.settings && VIEW.settings[key]) || "";
      go(start).then(() => { if (P.data && P.data.refused) go(""); setTimeout(() => list.focus(), 0); });
    }
  }
})();
