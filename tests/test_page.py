import _repo  # noqa: F401

import html.parser
import re
import unittest

from datapiler import logbook, server


class Tags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nonce, cls.token = "N0nceForTheTest", "T0kenForTheTest"
        cls.page = server.assemble(cls.nonce, cls.token).decode("utf-8")
        cls.parser = Tags()
        cls.parser.feed(cls.page)

    def test_one_script_and_one_style_with_the_nonce(self):
        self.assertEqual(self.page.count("<script nonce="), 1)
        self.assertEqual(self.page.count("<style nonce="), 1)
        self.assertEqual(len(re.findall(r"<script\b", self.page)), 1)
        self.assertEqual(len(re.findall(r"<style\b", self.page)), 1)
        self.assertIn('<script nonce="%s">' % self.nonce, self.page)
        self.assertIn('<style nonce="%s">' % self.nonce, self.page)
        self.assertIn('const TOKEN = "%s";' % self.token, self.page)

    def test_nothing_from_elsewhere(self):
        self.assertNotRegex(self.page, r"(?i)https?://")
        self.assertNotRegex(self.page, r"(?i)<link\b")
        self.assertNotRegex(self.page, r"(?i)<img\b")
        self.assertNotRegex(self.page, r"(?i)@import|url\(")

    def test_no_inline_event_attribute_or_style_attribute(self):
        for tag, attrs in self.parser.tags:
            for name in attrs:
                self.assertFalse(name.lower().startswith("on"), (tag, name))
                self.assertNotEqual(name.lower(), "style", tag)

    def test_placeholders_filled_and_no_closing_tag_inside(self):
        for ph in ("__NONCE__", "__TOKEN__", "/*__CSS__*/", "/*__JS__*/"):
            self.assertNotIn(ph, self.page)
        css = (server.PAGE_DIR / "app.css").read_text(encoding="utf-8")
        js = (server.PAGE_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("</style", css.lower())
        self.assertNotIn("</script", js.lower())
        self.assertNotIn("__NONCE__", js + css)

    def test_tabs_of_the_design(self):
        tabs = [a.get("data-t") for t, a in self.parser.tags if t == "button" and "data-t" in a]
        self.assertEqual(tabs, ["status", "extract", "imported", "jobs", "outputs", "deleted", "terminal", "settings"])
        self.assertIn("DataPiler has stopped.", self.page)
        # the server's address comes from /api/settings ("server", built from link.HOST and link.PORT), so the port
        # is written in link.py only
        self.assertIn('id="sServer"', self.page)
        self.assertIn('$("sServer").textContent = r.server', self.page)
        self.assertNotIn("22720", self.page)


class Page02Test(unittest.TestCase):
    """Build plan 0.2 §3.2 and §5.9: the files assembled in order, the rules over every page file, #btn-update
    before #quit, the sources lists agree, the Settings rows and the mask switch."""

    @classmethod
    def setUpClass(cls):
        cls.page = server.assemble("N0nce", "T0ken").decode("utf-8")
        cls.files = {n: (server.PAGE_DIR / n).read_text(encoding="utf-8") for n in server.PAGE_JS + server.PAGE_CSS}
        cls.parser = Tags()
        cls.parser.feed(cls.page)

    def test_assembled_in_order(self):
        for names in (server.PAGE_JS, server.PAGE_CSS):
            at = [self.page.index(self.files[n].replace("__TOKEN__", "T0ken")[:60]) for n in names]
            self.assertEqual(at, sorted(at), names)

    def test_the_rules_over_every_page_file(self):
        for name, text in self.files.items():
            with self.subTest(name=name):
                self.assertNotIn("</script", text.lower())
                self.assertNotIn("</style", text.lower())
                self.assertNotRegex(text, r"(?i)https?://")
                self.assertNotRegex(text, r"\beval\s*\(|new Function|document\.write|setAttribute\(\s*[\"'](on|style)")
                self.assertNotRegex(text, r"(?i)url\(|@import")
        js = self.files["folders.js"]
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("insertAdjacentHTML", js)
        self.assertNotRegex(js, r"\.style\b")

    def test_folders_js_is_one_iife(self):
        body = "\n".join(ln for ln in self.files["folders.js"].splitlines() if not ln.startswith("//")).strip()
        self.assertTrue(body.startswith("(() => {"), body[:40])
        self.assertTrue(body.endswith("})();"))
        self.assertEqual(body.count("\n})();"), 1)

    def test_the_update_button_before_quit(self):
        ids = [a.get("id") for t, a in self.parser.tags if t == "button" and a.get("id")]
        self.assertIn("btn-update", ids)
        self.assertEqual(ids.index("btn-update") + 1, ids.index("quit"))
        self.assertIn('title="Ask GitHub for the latest DataPiler release - only when pressed">Update…</button>',
                      self.page)

    def test_the_sources_lists_agree(self):
        import json as _json
        m = re.search(r"const SOURCES = (\[[^\]]*\]);", self.files["app.js"])
        self.assertEqual(tuple(_json.loads(m.group(1))), logbook.SOURCES)

    def test_the_settings_rows_and_the_mask_switch(self):
        ids = {a.get("id") for t, a in self.parser.tags if a.get("id")}
        for i in ("s_smithbox_dir", "s_game_dir", "s_project_dir", "s_expansion", "sMask", "frMasked", "ov"):
            self.assertIn(i, ids)
        rows = [a.get("data-key") for t, a in self.parser.tags if "fr-row" in (a.get("class") or "")]
        self.assertEqual(rows, ["smithbox_dir", "game_dir", "project_dir"])
        acts = [a.get("data-act") for t, a in self.parser.tags if t == "button" and a.get("data-act")]
        self.assertEqual(acts, ["detect", "pick", "detect", "pick", "detect", "detect", "pick"])
        self.assertEqual(self.page.count('id="s_expansion"'), 1)
        self.assertIn("Mask paths on this page", self.page)
        self.assertNotIn("MuiCache", self.page)
        self.assertNotIn("Windows recorded", self.page)          # DP13: no record of programs started

    def test_the_picker_draws_shown_names_and_goes_up_by_the_parent(self):
        """The reviews' SEC-2, C5 and C9: a listed folder is drawn by its shown name (masked with Mask paths on) and
        opened by its real path; Up opens the parent the API sends, never the crumb before the last."""
        js = self.files["folders.js"]
        self.assertIn("label: x.shown != null ? x.shown : x.name", js)
        self.assertIn("path: x.path ||", js)
        up = js[js.index("function goUp()"):js.index("function openSel()")]
        self.assertLess(up.index('typeof d.parent === "string"'), up.index("cs.length"))
        # the expansion's Yes and No from Detect are never the primary button when both are offered (C7)
        self.assertIn('"sm" + (list.length === 1 ? " pri" : "")', js)

    def test_s94_the_link_chip_says_whether_the_link_is_established(self):
        """DP33: a chip for every state Status gives, its reason in the chip's title, and the link card's line."""
        js = self.files["app.js"]
        pills = js[js.index("const PILLS = {"):js.index("function pill(")]
        link = pills[pills.index("  link: {"):]
        for state, words in (("off", '["mute", "Server link off"]'), ("no_libs", '["mute", "Server link: no libraries"]'),
                             ("waiting", '["warn", "Server link on: waiting for Smithbox"]'),
                             ("connected", '["ok", "Server link connected"]'),
                             ("no_answer", '["err", "Server link on: no answer"]'),
                             ("blocked", '["err", "Server link on: not used while the game runs"]')):
            self.assertIn("%s: %s" % (state, words), link)
        self.assertNotIn("(this session)", link)
        self.assertIn('pill("pLink", "link", s.pills.link, s.pills.link_why);', js)
        self.assertIn('e.title = why ? String(why) : "";', js)
        card = js[js.index("function linkCard("):js.index("function paintStatus(")]
        self.assertIn('const sv = l.state === "on" && l.server ? SERVER_WORDS[l.server.state] : null;', card)
        words = js[js.index("const SERVER_WORDS = {"):js.index("function linkCard(")]
        for state in ("connected", "waiting", "no_answer"):
            self.assertIn(state + ": [", words)

    def test_s95_the_about_block_and_the_folded_details(self):
        """DP34: a checked card shows its About block first, then Reads / Computes / Writes under one Details toggle,
        folded by default and kept open or closed while the page is open only; DP30's fold of whole cards leaves it."""
        js, css = self.files["app.js"], self.files["app.css"]
        card = js[js.index("function jobCard("):js.index("function jobOrder(")]
        about, details = card.index("aboutBlock(j.about)"), card.index("detailsBlock(j,")
        self.assertLess(card.index("add(c, head);"), about)
        self.assertLess(about, details)
        self.assertLess(details, card.index("if (j.refusals && j.refusals.length)"))
        self.assertIn('if (j.about && j.state !== "refused") add(c, aboutBlock(j.about));', card)
        self.assertIn('const inDetails = !!j.details && j.state !== "refused";', card)
        self.assertIn("if (inDetails) add(c, detailsBlock(j, stepsInView ? null : steps, local));", card)
        self.assertNotIn("cols3", card)                        # the columns are drawn under Details only
        self.assertNotIn("j.preview", card)
        block = js[js.index("function aboutBlock("):js.index("function opLine(")]
        for part in ('el("b", null, "About")', 'el("div", "jabout-text", a.text)', 'el("div", "jabout-sum", a.summary)',
                     'el("span", "jref", x)', '"References"'):
            self.assertIn(part, block)
        self.assertNotRegex(block, r"innerHTML|insertAdjacentHTML|href|<a\b|window\.open")   # plain chips, no link
        self.assertIn("const DETAILS_OPEN = {};", block)
        det = block[block.index("function detailsBlock("):]
        self.assertIn('"Details (" + n + (n === 1 ? " step)" : " steps)")', det)
        self.assertIn("show(!!DETAILS_OPEN[key]);", det)          # folded unless opened while this page is open
        self.assertIn('b.setAttribute("aria-expanded", on ? "true" : "false");', det)
        self.assertIn("const key = foldKey(j)", det)
        self.assertNotIn("store.", det)                           # never saved in the browser
        self.assertIn('it.names.forEach((n) => add(ns, el("code", null, n)));', block)
        for name in ("foldAll", "unfoldAll"):
            line = next(ln for ln in js.splitlines() if '$("%s")' % name in ln)
            self.assertNotIn("DETAILS_OPEN", line)
        fold = js[js.index("function setFolded("):js.index("function setFolded(") + 400]
        self.assertNotIn("DETAILS_OPEN", fold[:fold.index("\n}\n")])
        self.assertEqual(js.count("DETAILS_OPEN"), 4)            # declared, read once, set once, read once
        self.assertIn(".jobcard.folded > :not(.jhead) { display: none; }", css)   # About and Details fold with it
        for rule in (".jnames { display: flex; flex-wrap: wrap;", "button.dtoggle {", ".jref {",
                     ".jabout-text { white-space: pre-line;"):
            self.assertIn(rule, css)

    def test_s96_the_steps_and_the_workspace_list_under_details(self):
        """DP34's later note: once no step runs and none failed, the steps' lines are under Details; while the job is
        queued, waits or runs, or a step runs or failed, they stay in view. The Workspace line counts; its list is
        under Details."""
        js, css = self.files["app.js"], self.files["app.css"]
        card = js[js.index("function jobCard("):js.index("function jobOrder(")]
        live = js[js.index("function liveSteps("):js.index("function localCount(")]
        self.assertIn('return ["queued", "waiting", "running"].indexOf(j.state) >= 0 ||', live)
        self.assertIn('(j.ops || []).some((o) => o.state === "running" || o.state === "failed");', live)
        self.assertIn("const stepsInView = steps && (!inDetails || liveSteps(j));", card)
        self.assertEqual(card.count("add(c, steps)"), 1)
        self.assertLess(card.index('if (j.wait) add(c, el("div", "wait"'), card.index("if (stepsInView) add(c, steps);"))
        self.assertLess(card.index("if (stepsInView) add(c, steps);"), card.index("if (j.result) {"))
        self.assertIn('"Workspace: " + (inDetails ? localCount(local) + ", local, never shared" : local.join(", "))',
                      card)
        self.assertNotIn('"Workspace: " + j.result.local.join', card)
        det = js[js.index("function detailsBlock("):js.index("function liveSteps(")]
        self.assertIn('if (steps) add(body, add(el("div", "jdsec"), el("b", null, "Steps"), steps));', det)
        self.assertIn('add(body, add(el("div", "jdsec"), el("b", null, "Workspace"), ns));', det)
        self.assertIn("body.hidden = !on;", det)                  # columns, steps and list fold together
        self.assertNotIn("cols.hidden", det)
        count = js[js.index("function localCount("):js.index("function opLine(")]
        self.assertIn('local.filter((x) => String(x).indexOf("/") >= 0).length', count)   # unpacked/<file>/ (N files)
        self.assertIn('(folders === 1 ? " folder" : " folders")', count)
        self.assertIn('(files === 1 ? " file" : " files")', count)
        self.assertIn(".jdsec > b {", css)

    def test_only_the_pages_own_addresses(self):
        js = self.files["folders.js"]
        used = set(re.findall(r'api\("(/api/[a-z/-]+)"', js))
        self.assertEqual(used, {"/api/settings/one", "/api/dirs/forget", "/api/dirs/check", "/api/detect",
                                "/api/dirs", "/api/dirs/new"})
        self.assertNotIn("fetch(", js)


if __name__ == "__main__":
    unittest.main()
