import _repo  # noqa: F401

import html.parser
import re
import unittest

from datapiler import server


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
        self.assertEqual(tabs, ["status", "extract", "jobs", "outputs", "terminal", "settings"])
        self.assertIn("DataPiler has stopped.", self.page)
        # the server's address comes from /api/settings ("server", built from link.HOST and link.PORT), so the port
        # is written in link.py only
        self.assertIn('id="sServer"', self.page)
        self.assertIn('$("sServer").textContent = r.server', self.page)
        self.assertNotIn("22720", self.page)


if __name__ == "__main__":
    unittest.main()
