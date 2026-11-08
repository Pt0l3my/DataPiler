"""The guard (build plan §4.10, §8.3). Share documents are built in code, never kept as fixture files (§8.5): a good
one passes; each check fails with its number and place; a failure leaves the share folder unchanged; no message
carries the value; check_labels finds a label planted in the text database. Every text and name is invented."""

import _repo  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datapiler import events, guard, logbook, textdb

PLANTED_USER = "velkorquist"
PLANTED_PC = "brightwatertower"
TEXTS = ["Quillon Marrowgate", "the Lamplighter of Corrow", "Vellmoor", "Corrow"]
PROVENANCE = {"game_version": "1.99.0.0", "regulation_sha256": "ab" * 32, "expansion": True, "language": "engus",
              "smithbox_build": "9.9.9", "datapiler": "0.1.0", "date": "2026-11-08"}
JOB_SHA = "cd" * 32
EXPECTED_BYTES = (
    '{\n'
    '  "format": "datapiler-share/1",\n'
    '  "job": {"id": "en-0007-roster-counts", "sha256": "%s"},\n'
    '  "provenance": {"game_version": "1.99.0.0", "regulation_sha256": "%s", "expansion": true, '
    '"language": "engus", "smithbox_build": "9.9.9", "datapiler": "0.1.0", "date": "2026-11-08"},\n'
    '  "tables": [\n'
    '    {"name": "per_team", "columns": [{"name": "teamType", "type": "int"}, {"name": "count", "type": "int"}],\n'
    '     "rows": [\n'
    '      [0, 112],\n'
    '      [6, 48]\n'
    '     ]}\n'
    '  ],\n'
    '  "notes": ["named_only"]\n'
    '}\n') % (JOB_SHA, "ab" * 32)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.share = root / "share"
        self.share.mkdir()
        self.db = textdb.TextDB(root / "work" / "textdb.sqlite")
        self.db.import_export({"Name": "item", "FmgWrappers": [{"Name": "Invented", "ID": 9001, "Fmg": {
            "Entries": [{"ID": 9000000 + i, "Text": t} for i, t in enumerate(TEXTS)]}}]},
            container="item", language="engus", sha256="0" * 64)
        self.guard = guard.Guard(self.db, lambda: [PLANTED_USER, PLANTED_PC])
        self.events = []
        self.unsub = events.subscribe("", self._event)

    def _event(self, topic, data):
        if topic in ("share.written", "guard.failed"):
            self.events.append((topic, data))

    def tearDown(self):
        self.unsub()
        self.guard.close()
        self.db.close()
        self.tmp.cleanup()

    # ---- helpers

    def doc(self, *, tables=None, notes=("named_only",), job_id="en-0007-roster-counts", provenance=None):
        if tables is None:
            tables = [{"name": "per_team", "columns": [("teamType", "int"), ("count", "int")],
                       "rows": [[0, 112], [6, 48]]}]
        return self.guard.build(job_id=job_id, job_sha256=JOB_SHA, provenance=provenance or dict(PROVENANCE),
                                tables=tables, notes=list(notes))

    @staticmethod
    def declared_of(data: bytes) -> dict:
        d = json.loads(data)
        return {t["name"]: [c["name"] for c in t["columns"]] for t in d["tables"]}

    def results(self, data: bytes, declared=None):
        return self.guard.check(data, declared=declared if declared is not None else self.declared_of(data))

    def failing(self, data: bytes, declared=None) -> dict:
        return {r.check: r.where for r in self.results(data, declared) if not r.ok}

    def plant_label(self):
        """Puts DataPiler's label "summary" into the text database, as if a game word were spelt so (S6)."""
        self.db.import_export({"Name": "item_dlc02", "FmgWrappers": [{"Name": "Invented", "ID": 9002, "Fmg": {
            "Entries": [{"ID": 9000100, "Text": "Summary"}]}}]}, container="item_dlc02", language="engus",
            sha256="2" * 64)

    def edit(self, data: bytes, fn) -> bytes:
        d = json.loads(data)
        fn(d)
        return json.dumps(d).encode()

    # ---- a good one

    def test_the_layout(self):
        self.assertEqual(self.doc().decode("ascii"), EXPECTED_BYTES)

    def test_a_good_one_passes_and_is_written(self):
        data = self.doc()
        res = self.results(data)
        self.assertEqual([(r.check, r.name, r.ok, r.where) for r in res],
                         [(1, "Shape", True, None), (2, "Values", True, None), (3, "Text", True, None),
                          (4, "The owner", True, None), (5, "Size", True, None)])
        w = self.guard.write(self.share, "roster-counts", data, declared=self.declared_of(data))
        self.assertEqual((w.name, w.size), ("roster-counts.json", len(data)))
        self.assertEqual((self.share / "roster-counts.json").read_bytes(), data)
        self.assertEqual(len(w.sha256), 64)
        self.assertEqual(self.events, [("share.written", {"name": "roster-counts.json", "size": len(data)})])

    def test_numbers_flags_enums_and_labels(self):
        data = self.doc(tables=[{"name": "mixed", "columns": [("a", "number"), ("b", "bool"), ("c", "enum:source"),
                                                              ("d", "label"), ("e", "int")],
                                 "rows": [[0.5, True, "server", "summary", -2 ** 62], [3, False, "guided",
                                                                                       "vanilla_rows", 0]]}])
        self.assertEqual(self.failing(data), {})

    def test_the_format_constant_and_the_versions_pass(self):
        # "datapiler-share/1" holds a slash and "1.99.0.0" looks like an IPv4 address: both are allowed where they
        # stand, and only there.
        self.assertEqual(self.failing(self.doc()), {})
        data = self.edit(self.doc(), lambda d: d["notes"].append("1.99.0.0"))
        self.assertEqual(self.failing(data)[4], "notes[1]")

    # ---- check 1

    def test_shape(self):
        good = self.doc()
        decl = self.declared_of(good)
        cases = [
            (self.edit(good, lambda d: d.update(extra=1)), decl, "(top level)"),
            (good, {"per_team": ["count", "teamType"]}, "tables[0].columns[0].name"),
            (good, {"per_team": ["teamType"]}, "tables[0].columns"),
            (good, {"other": ["teamType", "count"]}, "tables[0].name"),
            (good, {"per_team": ["teamType", "count"], "more": ["count"]}, "tables"),
            (self.edit(good, lambda d: d.update(format="datapiler-share/2")), decl, "format"),
            (self.edit(good, lambda d: d["job"].update(id="Not An Id")), decl, "job.id"),
            (self.edit(good, lambda d: d["job"].update(sha256="AB" * 32)), decl, "job.sha256"),
            (self.edit(good, lambda d: d["provenance"].update(language="en-GB")), decl, "provenance.language"),
            (self.edit(good, lambda d: d["provenance"].update(expansion="yes")), decl, "provenance.expansion"),
            (self.edit(good, lambda d: d["provenance"].pop("date")), decl, "provenance"),
            (self.edit(good, lambda d: d["tables"][0]["rows"].append([1])), decl, "tables[0].rows[2]"),
            (self.edit(good, lambda d: d["tables"][0]["columns"][1].update(type="text")), decl,
             "tables[0].columns[1].type"),
            (self.edit(good, lambda d: d.update(notes="named_only")), decl, "notes"),
            (b"{not json", decl, "(file)"),
            (b"[1, 2]", decl, "(file)"),
        ]
        for data, declared, where in cases:
            with self.subTest(where=where):
                self.assertEqual(self.failing(data, declared).get(1), where)

    def test_a_key_given_twice(self):
        data = self.doc().replace(b'"notes": ["named_only"]', b'"notes": ["named_only"], "notes": []')
        self.assertEqual(self.failing(data).get(1), "(top level)")

    # ---- check 2

    def test_values(self):
        good = self.doc()

        def cell(v):
            return self.edit(good, lambda d: d["tables"][0]["rows"][1].__setitem__(1, v))

        for v in ("48", True, 1.5, None, [48], 2 ** 63):
            with self.subTest(v=v):
                self.assertEqual(self.failing(cell(v)).get(2), "tables[0].rows[1][1]")
        nan = self.doc(tables=[{"name": "per_team", "columns": [("teamType", "number"), ("count", "int")],
                                "rows": [[float("nan"), 1]]}])
        self.assertIn(b"NaN", nan)
        self.assertEqual(self.failing(nan).get(2), "tables[0].rows[0][0]")
        inf = nan.replace(b"NaN", b"Infinity")
        self.assertEqual(self.failing(inf).get(2), "tables[0].rows[0][0]")

    def test_enums_and_labels(self):
        data = self.doc(tables=[{"name": "kinds", "columns": [("c", "enum:source"), ("d", "label")],
                                 "rows": [["server", "summary"], ["elsewhere", "summary"]]}])
        self.assertEqual(self.failing(data).get(2), "tables[0].rows[1][0]")
        data = self.doc(tables=[{"name": "kinds", "columns": [("c", "enum:source"), ("d", "label")],
                                 "rows": [["server", "not_a_label"]]}])
        self.assertEqual(self.failing(data).get(2), "tables[0].rows[0][1]")
        self.assertEqual(self.failing(self.doc(notes=["named_only", "no_such_note"])).get(2), "notes[1]")

    # ---- check 3

    def test_text(self):
        def table(name):
            return self.doc(tables=[{"name": name, "columns": [("count", "int")], "rows": [[1]]}])

        self.assertEqual(self.failing(table("corrow")).get(3), "tables[0].name")              # equal
        self.assertEqual(self.failing(table("lamplighter")).get(3), "tables[0].name")         # contained in a text
        self.assertEqual(self.failing(table("vellmoor_counts")).get(3), "tables[0].name")     # contains a text
        self.assertNotIn(3, self.failing(table("per_team")))
        self.assertEqual(self.failing(self.doc(job_id="en-0009-corrow")).get(3), "job.id")

    def test_an_exact_label_is_skipped(self):
        # "summary" is a text of the invented database and one of DataPiler's labels (S6).
        self.plant_label()
        self.assertEqual(self.failing(self.doc(notes=["summary"])), {})
        data = self.doc(tables=[{"name": "t", "columns": [("x", "label")], "rows": [["summary"]]}])
        self.assertEqual(self.failing(data), {})

    def test_an_empty_text_database_passes_with_a_warning(self):
        with tempfile.TemporaryDirectory() as d:
            empty = textdb.TextDB(Path(d) / "t.sqlite")
            g = guard.Guard(empty, lambda: [])
            try:
                _, seq = logbook.lines_after(0, limit=0)
                data = self.doc(tables=[{"name": "corrow", "columns": [("count", "int")], "rows": [[1]]}])
                g.write(Path(d) / "share", "corrow-counts", data, declared={"corrow": ["count"]})
                lines, _ = logbook.lines_after(seq)
                self.assertTrue(any(x["src"] == "guard" and x["level"] == "WARN" and "empty" in x["msg"]
                                    for x in lines))
            finally:
                g.close()
                empty.close()

    # ---- check 4

    def test_the_owner(self):
        good = self.doc()
        for note, label in (("a\\b", "backslash"), ("a/b", "slash"), ("x:", "drive letter"), ("c:\\", "drive"),
                            ("~x", "tilde"), (PLANTED_USER, "user"), ("The-" + PLANTED_PC.upper(), "PC, any case"),
                            ("127.0.0.1", "IPv4"), ("::1", "IPv6")):
            with self.subTest(label):
                data = self.edit(good, lambda d, note=note: d["notes"].append(note))
                self.assertEqual(self.failing(data).get(4), "notes[1]")
        user_table = self.doc(tables=[{"name": PLANTED_USER + "_counts", "columns": [("count", "int")],
                                       "rows": [[1]]}])
        self.assertEqual(self.failing(user_table), {4: "tables[0].name"})
        part_of_a_word = self.doc(tables=[{"name": "x" + PLANTED_USER, "columns": [("count", "int")],
                                           "rows": [[1]]}])
        self.assertNotIn(4, self.failing(part_of_a_word))
        enum = self.doc(tables=[{"name": "t", "columns": [("x", "enum:source")], "rows": [["server"]]}])
        self.assertEqual(self.failing(enum), {})

    # ---- check 5

    def test_size(self):
        data = self.doc()
        with mock.patch.object(guard, "MAX_BYTES", len(data) - 1):
            self.assertEqual(self.failing(data).get(5), "(file)")
        with mock.patch.object(guard, "MAX_VALUES", 3):
            self.assertEqual(self.failing(data).get(5), "tables[0].rows[1]")
        with mock.patch.object(guard, "MAX_VALUES", 4):
            self.assertEqual(self.failing(data).get(5), "notes[0]")
        with mock.patch.object(guard, "MAX_VALUES", 5):
            self.assertEqual(self.failing(data), {})

    # ---- writing

    def test_a_failure_writes_nothing_and_names_no_value(self):
        before = sorted(p.name for p in self.share.iterdir())
        _, seq = logbook.lines_after(0, limit=0)
        data = self.doc(tables=[{"name": "lamplighter", "columns": [("count", "int")], "rows": [[1]]}])
        with self.assertRaises(guard.GuardFailed) as cm:
            self.guard.write(self.share, "roster-counts", data, declared={"lamplighter": ["count"]})
        self.assertEqual(cm.exception.check, 3)
        self.assertEqual(cm.exception.where, "tables[0].name")
        self.assertEqual(str(cm.exception), "check 3 at tables[0].name")
        self.assertEqual(sorted(p.name for p in self.share.iterdir()), before)
        self.assertEqual(self.events, [("guard.failed", {"name": "roster-counts.json", "check": 3})])
        lines, _ = logbook.lines_after(seq)
        text = "\n".join(x["msg"] for x in lines).lower()
        self.assertIn("roster-counts.json not written: check 3 at tables[0].name", text)
        self.assertNotIn("lamplighter", text)
        for user_data in (PLANTED_USER, PLANTED_PC):
            data = self.doc(notes=["named_only"], job_id="en-0001-" + user_data)
            with self.assertRaises(guard.GuardFailed) as cm:
                self.guard.write(self.share, "x", data, declared=self.declared_of(data))
            self.assertNotIn(user_data, str(cm.exception))
        lines, _ = logbook.lines_after(seq)
        text = "\n".join(x["msg"] for x in lines).lower()
        self.assertNotIn(PLANTED_USER, text)
        self.assertNotIn(PLANTED_PC, text)
        self.assertEqual(sorted(p.name for p in self.share.iterdir()), before)

    def test_a_bad_name(self):
        with self.assertRaises(ValueError):
            self.guard.write(self.share, "../x", self.doc(), declared=self.declared_of(self.doc()))

    def test_check_never_raises(self):
        for junk in (b"", b"\xff\xfe", b"[" * 5000, b'{"format": 1}'):
            res = self.guard.check(junk, declared={})
            self.assertEqual([r.check for r in res], [1, 2, 3, 4, 5])
            self.assertFalse(res[0].ok)

    # ---- labels

    def test_check_labels_finds_a_planted_label(self):
        self.assertEqual(self.guard.check_labels(), [])
        self.plant_label()
        self.assertEqual(self.guard.check_labels(), [guard.LABELS.index("summary")])
        with mock.patch.object(guard, "LABELS", guard.LABELS + ("loaded/maps",)):
            self.assertEqual(self.guard.check_labels(), [guard.LABELS.index("summary"), 4])

    def test_labels_are_rechecked_when_the_text_database_changes(self):
        with mock.patch.object(self.guard, "check_labels", wraps=self.guard.check_labels) as spy:
            self.db.import_export({"Name": "item", "FmgWrappers": []}, container="item_dlc01", language="engus",
                                  sha256="1" * 64)
            self.assertEqual(spy.call_count, 1)

    @unittest.expectedFailure   # build plan §10, P12: open until the lead settles it; then drop this decorator
    def test_p12_the_formats_own_keys_against_an_ordinary_description(self):
        """Found while integrating: check 3 runs over the share format's own keys too, and "name", "rows", "type",
        "count" sit inside ordinary words, so one ordinary description in the text database refuses every share
        file (here at tables[0].name, the key)."""
        self.db.import_export({"Name": "item", "FmgWrappers": [{"Name": "Invented", "ID": 9001, "Fmg": {
            "Entries": [{"ID": 9100000, "Text": "An invented blade, named for the arrows its maker counted in rows."}]}}]},
            container="item", language="engus", sha256="1" * 64)
        self.assertEqual(self.failing(self.doc(notes=())), {})


if __name__ == "__main__":
    unittest.main()
