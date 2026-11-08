"""The Update... pop-up's page code (build plan 0.2 §4.7, §7.1): update.js is one IIFE defining nothing global; none
of the calls that write HTML or run text as code; only its three addresses fetched; the release link only behind the
view's `page` field, opening a new tab with rel="noopener noreferrer"; its own classes prefixed up-; nothing from
elsewhere in either file."""

import _repo  # noqa: F401

import re
import unittest
from pathlib import Path

PAGE = Path(_repo.ROOT) / "datapiler" / "page"
JS = (PAGE / "update.js").read_text(encoding="utf-8")
CSS = (PAGE / "update.css").read_text(encoding="utf-8")
SHARED_CLASSES = {"mute", "mono", "pri", "left", "m", "unk"}      # app.css's own, used as they are


def code_only(js: str) -> str:
    """The script without its comments and with each string literal's text kept (for the address checks)."""
    out, i, n = [], 0, len(js)
    while i < n:
        c = js[i]
        if js.startswith("//", i):
            j = js.find("\n", i)
            i = n if j < 0 else j
        elif js.startswith("/*", i):
            i = js.index("*/", i) + 2
        elif c in "\"'`":
            j = i + 1
            while js[j] != c:
                j += 2 if js[j] == "\\" else 1
            out.append(js[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


CODE = code_only(JS)


class UpdateJs(unittest.TestCase):
    def test_one_iife(self):
        body = CODE.strip()
        self.assertTrue(body.startswith("(() => {"), body[:40])
        self.assertTrue(body.endswith("})();"), body[-40:])
        depth = 0
        inner = body[len("(() => {"):-len("})();")]
        for ch in re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`|/(?:\\.|[^/\n\\])+/[a-z]*(?=[;.,)\s])", "",
                         inner):
            depth += {"{": 1, "}": -1}.get(ch, 0)
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)
        self.assertNotRegex(CODE, r"\bwindow\.[A-Za-z_]+\s*=")
        self.assertNotRegex(CODE, r"\bglobalThis\b")
        self.assertNotRegex(CODE, r"(?m)^\s*var\s")

    def test_no_html_and_no_text_run_as_code(self):
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "Function(",
                    "setAttribute(\"style\"", ".style.", "cssText", "srcdoc", "javascript:", "DOMParser",
                    "createContextualFragment", "setTimeout(\"", "setInterval(\""):
            self.assertNotIn(bad, CODE, bad)

    def test_only_its_three_addresses(self):
        strings = re.findall(r"\"(/[^\"]*)\"", CODE)
        self.assertTrue(strings)
        self.assertLessEqual(set(strings), {"/api/update", "/api/update-result", "/"}, strings)
        fetched = re.findall(r"\bfetch\(([^,)]*)", CODE)
        self.assertEqual(fetched, ['"/"'])
        for first in re.findall(r"\bapi\(([^,)]*)", CODE):
            self.assertIn(first, ('"/api/update"', '"/api/update-result"'))
        self.assertNotRegex(CODE, r"https?://")
        self.assertNotIn("XMLHttpRequest", CODE)
        self.assertNotIn("WebSocket", CODE)
        self.assertNotIn("sendBeacon", CODE)
        self.assertNotIn("import(", CODE)

    def test_the_release_link(self):
        link = CODE[CODE.index("function releaseLink"):]
        link = link[:link.index("\n  }\n") + 4]
        self.assertIn("const page = v && v.latest && v.latest.page;", link)
        self.assertIn("RELEASES.test(page)", link)
        self.assertIn("a.href = page;", link)
        self.assertIn('a.target = "_blank";', link)
        self.assertIn('a.rel = "noopener noreferrer";', link)
        self.assertEqual(CODE.count(".href ="), 1)
        self.assertEqual(CODE.count('el("a"'), 1)
        rx = re.search(r"const RELEASES = /(.+)/;", JS).group(1)
        self.assertTrue(re.match(rx.replace("\\/", "/"), "https://github.com/Pt0l3my/DataPiler/releases/tag/v0.3.0"))
        for bad in ("https://github.com/someone/DataPiler/releases/tag/v1", "http://github.com/Pt0l3my/DataPiler/"
                    "releases/x", "https://github.com/Pt0l3my/DataPiler/releases/x\"onclick", "javascript:alert(1)"):
            self.assertIsNone(re.match(rx.replace("\\/", "/"), bad), bad)

    def test_notes_are_built_as_text(self):
        notes = CODE[CODE.index("function parts("):CODE.index("function latestRows(")]
        self.assertIn('el("span", "up-href", String(p.href || ""))', notes)
        self.assertNotIn(".href", notes.replace("p.href", ""))
        self.assertIn('"[image: " + v + "]"', notes)

    def test_the_restart_and_the_result(self):
        self.assertIn("holdHeartbeat(true);", CODE)
        # while held, the page's own polls ask nothing: an old token would only meet the new app's 403
        app = (PAGE / "app.js").read_text(encoding="utf-8")
        self.assertIn("function poll() {\n  if (GONE || HOLD) return Promise.resolve();", app)
        self.assertIn("function pollTerm() {\n  if (GONE || HOLD) return;", app)
        self.assertIn('fetch("/", { cache: "no-store" })', CODE)
        self.assertIn("text.indexOf(TOKEN) < 0", CODE)
        self.assertIn("location.reload()", CODE)
        self.assertIn('const FLAG = "dp.update";', CODE)
        self.assertIn("const BACK_MS = 90 * 1000;", CODE)
        self.assertIn("DataPiler did not come back on this address - it may have opened a new tab, or its window says "
                      "\" +\n          \"why\"", CODE)
        self.assertIn('api("/api/update-result")', CODE)

    def test_each_state_of_the_view_is_painted(self):
        for state in ("idle", "checking", "up_to_date", "older", "none", "not_installable", "newer", "downloading",
                      "ready"):
            self.assertIn('"%s"' % state, CODE, state)
        self.assertIn('{ action: "check", fresh: false }', CODE)
        self.assertIn('{ action: "check", fresh: true }', CODE)
        for action in ("download", "install", "cancel"):
            self.assertIn('{ action: "%s" }' % action, CODE)
        self.assertIn("setInterval(tick, 500)", CODE)
        self.assertIn('el("progress", "up-bar")', CODE)

    def test_its_classes_are_its_own(self):
        used = set()
        for m in re.finditer(r"\bel\(\"[a-z0-9]+\", \"([^\"]+)\"", CODE):
            used.update(m.group(1).split())
        for m in re.finditer(r"\bbtn\(\"[^\"]+\", \"([^\"]+)\"", CODE):
            used.update(m.group(1).split())
        own = {c for c in used if c.startswith("up-")}
        self.assertTrue(own)
        self.assertLessEqual(used - own, SHARED_CLASSES, used - own)
        defined = set(re.findall(r"\.(up-[a-z0-9-]+)", CSS))
        self.assertLessEqual(own - {"up-lt"}, defined, own - defined)


class UpdateCss(unittest.TestCase):
    def test_only_up_classes(self):
        body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
        for sel in re.findall(r"(?m)^([^{}\n]+)\{", body):
            for cls in re.findall(r"\.([A-Za-z][A-Za-z0-9_-]*)", sel):
                self.assertTrue(cls.startswith("up-") or cls in ("ok", "warn", "err"), (sel, cls))

    def test_nothing_from_elsewhere(self):
        self.assertNotRegex(CSS, r"(?i)url\(|@import|https?://")
        self.assertNotIn("</style", CSS.lower())
        self.assertNotIn("</script", JS.lower())


if __name__ == "__main__":
    unittest.main()
