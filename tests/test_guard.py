"""The guard (build plan §4.10, §8.3). Share documents are built in code, never kept as fixture files (§8.5): a good
one passes; each check fails with its number and place; a failure leaves the share folder unchanged; no message
carries the value; check_labels finds a label planted in the text database; check 3 reads values only and skips
DataPiler's fixed words (P12, S20); check 6 refuses a table covering more than half of its game table's rows, alone or
with the file's other tables from the same game table, or one without its counts (DP8, S19); check 4 finds the
owner's words written with `_`, `-` or nothing between their parts; the provenance's expansion source and names (P2,
P3). Every text and name is invented."""

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
PROVENANCE = {"game_version": "1.99.0.0", "regulation_sha256": "ab" * 32, "expansion": True,
              "expansion_source": "owner", "language": "engus", "names": {}, "smithbox_build": "9.9.9",
              "datapiler": "0.1.0", "date": "2026-11-08"}
NAMES_RECORD = {"character_names": {"wrappers": [428, 328, 18], "verified": True, "resolved": 0.95}}
JOB_SHA = "cd" * 32
EXPECTED_BYTES = (
    '{\n'
    '  "format": "datapiler-share/1",\n'
    '  "job": {"id": "en-0007-roster-counts", "sha256": "%s"},\n'
    '  "provenance": {"game_version": "1.99.0.0", "regulation_sha256": "%s", "expansion": true, '
    '"expansion_source": "owner", "language": "engus", "names": {}, "smithbox_build": "9.9.9", "datapiler": "0.1.0", '
    '"date": "2026-11-08"},\n'
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

    @staticmethod
    def counts(data: bytes) -> dict:
        """Every table an aggregate (nothing for check 6 to measure), as the runner says of a count."""
        try:
            return {t["name"]: None for t in json.loads(data)["tables"]}
        except (ValueError, KeyError, TypeError):
            return {}

    def results(self, data: bytes, declared=None, coverage="aggregates"):
        return self.guard.check(data, declared=declared if declared is not None else self.declared_of(data),
                                coverage=self.counts(data) if coverage == "aggregates" else coverage)

    def failing(self, data: bytes, declared=None, coverage="aggregates") -> dict:
        return {r.check: r.where for r in self.results(data, declared, coverage) if not r.ok}

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
                          (4, "The owner", True, None), (5, "Size", True, None), (6, "Coverage", True, None)])
        w = self.guard.write(self.share, "roster-counts", data, declared=self.declared_of(data),
                             coverage=self.counts(data))
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
                g.write(Path(d) / "share", "corrow-counts", data, declared={"corrow": ["count"]},
                        coverage={"corrow": None})
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

    def test_the_owner_words_whatever_stands_between_their_parts(self):
        """A table name cannot hold `-` nor a space, so the PC's or the user's name written with `_`, `-` or nothing
        between its parts is the name still (invented words)."""
        g = guard.Guard(self.db, lambda: ["QRIG-Z7KX2PM", "Velkor Quist", "", None])
        try:
            for name in ("qrig_z7kx2pm", "qrigz7kx2pm", "velkor_quist", "velkorquist", "x_velkor_quist_counts"):
                with self.subTest(table=name):
                    data = self.doc(tables=[{"name": name, "columns": [("count", "int")], "rows": [[1]]}])
                    res = {r.check: r.where for r in g.check(data, declared=self.declared_of(data),
                                                              coverage=self.counts(data)) if not r.ok}
                    self.assertEqual(res, {4: "tables[0].name"})
            for jid in ("qrig-z7kx2pm-x", "velkor-quist"):
                with self.subTest(job=jid):
                    data = self.doc(job_id=jid)
                    res = {r.check: r.where for r in g.check(data, declared=self.declared_of(data),
                                                              coverage=self.counts(data)) if not r.ok}
                    self.assertEqual(res, {4: "job.id"})
            for name in ("velkorquistian", "xvelkor_quist", "qrig_z7kx", "quist_velkor"):
                with self.subTest(other=name):
                    data = self.doc(tables=[{"name": name, "columns": [("count", "int")], "rows": [[1]]}])
                    self.assertNotIn(4, {r.check for r in g.check(data, declared=self.declared_of(data),
                                                                    coverage=self.counts(data)) if not r.ok})
        finally:
            g.close()

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
            self.guard.write(self.share, "roster-counts", data, declared={"lamplighter": ["count"]},
                             coverage={"lamplighter": None})
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
                self.guard.write(self.share, "x", data, declared=self.declared_of(data), coverage=self.counts(data))
            self.assertNotIn(user_data, str(cm.exception))
        lines, _ = logbook.lines_after(seq)
        text = "\n".join(x["msg"] for x in lines).lower()
        self.assertNotIn(PLANTED_USER, text)
        self.assertNotIn(PLANTED_PC, text)
        self.assertEqual(sorted(p.name for p in self.share.iterdir()), before)

    def test_a_bad_name(self):
        with self.assertRaises(ValueError):
            self.guard.write(self.share, "../x", self.doc(), declared=self.declared_of(self.doc()),
                             coverage=self.counts(self.doc()))

    def test_check_never_raises(self):
        for junk in (b"", b"\xff\xfe", b"[" * 5000, b'{"format": 1}'):
            res = self.guard.check(junk, declared={}, coverage={})
            self.assertEqual([r.check for r in res], [1, 2, 3, 4, 5, 6])
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

    def test_p12_the_formats_own_keys_against_an_ordinary_description(self):
        """Found while integrating (build plan §10, P12; settled S20): check 3 ran over the share format's own keys
        too, and "name", "rows", "type", "count" sit inside ordinary words, so one ordinary description in the text
        database refused every share file. Now the keys are check 1's, and `count`, a column name DataPiler's
        operations make, is one of its fixed words."""
        self.db.import_export({"Name": "item", "FmgWrappers": [{"Name": "Invented", "ID": 9001, "Fmg": {
            "Entries": [{"ID": 9100000, "Text": "An invented blade, named for the arrows its maker counted in rows."}]}}]},
            container="item", language="engus", sha256="1" * 64)
        self.assertEqual(self.failing(self.doc(notes=())), {})

    def test_ordinary_words_that_hold_a_key_or_a_fixed_word(self):
        """One-word texts that hold the format's keys (rows, name, tables, type, provenance's names, wrappers) or
        DataPiler's fixed words (count, number, bool, summary, owner): none refuses a share file, and a table name
        or job id holding a text still fails."""
        words = ["Sparrows", "Unnamed", "Notables", "Archetype", "Viscount", "Numbered", "Boolean", "Summarise",
                 "Landowner", "Formatted", "Wrappers", "Resolved", "Unverified", "Shipwrecked"]
        self.db.import_export({"Name": "item_dlc01", "FmgWrappers": [{"Name": "Invented", "ID": 9001, "Fmg": {
            "Entries": [{"ID": 9200000 + i, "Text": w} for i, w in enumerate(words)]}}]},
            container="item_dlc01", language="engus", sha256="3" * 64)
        data = self.doc(tables=[{"name": "per_team", "columns": [("teamType", "int"), ("count", "int"),
                                                                 ("nameId", "number"), ("named", "bool")],
                                 "rows": [[0, 1, 2.5, True]]}],
                        notes=["summary"], provenance=dict(PROVENANCE, names=NAMES_RECORD))
        self.assertEqual(self.failing(data), {})
        bad = self.doc(tables=[{"name": "viscount_rows", "columns": [("count", "int")], "rows": [[1]]}])
        self.assertEqual(self.failing(bad).get(3), "tables[0].name")
        self.assertEqual(self.failing(self.doc(job_id="en-0003-sparrows")).get(3), "job.id")
        # a column name that is not one DataPiler's operations make is still checked
        odd = self.doc(tables=[{"name": "t", "columns": [("unnamed", "int")], "rows": [[1]]}])
        self.assertEqual(self.failing(odd).get(3), "tables[0].columns[0].name")

    def test_the_fixed_words(self):
        fixed = guard.fixed_words()
        for w in ("named_only", "summary", "int", "number", "bool", "label", "enum:source", "server", "guided",
                  "id", "nameId", "teamType", "npcType", "msgId", "map", "entityId", "npcParamId", "talkId", "model",
                  "named", "count", "owner", guard.SHARE_FORMAT):
            self.assertIn(w, fixed, w)
        self.assertNotIn("name", fixed)          # join_names's local text never reaches a share file
        self.assertNotIn("per_team", fixed)

    # ---- the provenance's own records (P2, P3)

    def test_the_expansion_source_and_the_names(self):
        good = self.doc(provenance=dict(PROVENANCE, names=NAMES_RECORD))
        self.assertEqual(self.failing(good), {})
        decl = self.declared_of(good)

        def names(fn):
            return self.edit(good, lambda d: fn(d["provenance"]["names"]))

        cases = [
            (self.edit(good, lambda d: d["provenance"].update(expansion_source="files")),
             "provenance.expansion_source"),
            (self.edit(good, lambda d: d["provenance"].pop("expansion_source")), "provenance"),
            (self.edit(good, lambda d: d["provenance"].update(names=[])), "provenance.names"),
            (names(lambda n: n.update(other_names={})), "provenance.names"),
            (names(lambda n: n["character_names"].pop("verified")), "provenance.names.character_names"),
            (names(lambda n: n["character_names"].update(verified=False)),
             "provenance.names.character_names.verified"),
            (names(lambda n: n["character_names"].update(resolved=0.49)),
             "provenance.names.character_names.resolved"),
            (names(lambda n: n["character_names"].update(resolved=True)),
             "provenance.names.character_names.resolved"),
            (names(lambda n: n["character_names"].update(wrappers=[])),
             "provenance.names.character_names.wrappers"),
            (names(lambda n: n["character_names"].update(wrappers=["18"])),
             "provenance.names.character_names.wrappers"),
        ]
        for data, where in cases:
            with self.subTest(where=where):
                self.assertEqual(self.failing(data, decl).get(1), where)

    # ---- check 6 (DP8)

    def per_row(self, ids):
        return self.doc(tables=[{"name": "npc_named", "columns": [("id", "int"), ("nameId", "int")],
                                 "rows": [[i, 9500000 + i] for i in ids]}])

    def test_coverage(self):
        data = self.per_row(range(10))
        # the row id against the game table's rows: half passes, more than half fails, at the table
        self.assertEqual(self.failing(data, coverage={"npc_named": ("id", 20, "NpcParam")}), {})
        self.assertEqual(self.failing(data, coverage={"npc_named": ("id", 19, "NpcParam")}), {6: "tables[0]"})
        # rows that repeat an id count once
        twice = self.per_row([1, 1, 2, 2, 3, 3])
        self.assertEqual(self.failing(twice, coverage={"npc_named": ("id", 6, "NpcParam")}), {})
        self.assertEqual(self.failing(twice, coverage={"npc_named": (None, 6, "NpcParam")}), {6: "tables[0]"})
        # without the id column: the table's rows
        self.assertEqual(self.failing(data, coverage={"npc_named": (None, 20, "NpcParam")}), {})
        self.assertEqual(self.failing(data, coverage={"npc_named": (None, 10, "NpcParam")}), {6: "tables[0]"})
        # counts alone are not measured
        self.assertEqual(self.failing(data, coverage={"npc_named": None}), {})
        # no counts, a table left out, a column that is not there, a bad count or source: refused
        self.assertEqual(self.failing(data, coverage=None), {6: guard.NO_COUNTS})
        self.assertEqual(self.failing(data, coverage={}), {6: "tables[0]"})
        for bad in (("entityId", 1000, "NpcParam"), ("id", -1, "NpcParam"), ("id", True, "NpcParam"),
                    ("id", 1000), ("id", 1000, None), ("id", 1000, "a b"), ("id", 1000, "NpcParam", 1)):
            with self.subTest(spec=bad):
                self.assertEqual(self.failing(data, coverage={"npc_named": bad}), {6: "tables[0]"})
        two = self.doc(tables=[{"name": "a", "columns": [("count", "int")], "rows": [[1]]},
                               {"name": "b", "columns": [("id", "int")], "rows": [[1], [2]]}])
        self.assertEqual(self.failing(two, coverage={"a": None, "b": ("id", 3, "NpcParam")}), {6: "tables[1]"})
        empty = self.doc(tables=[{"name": "b", "columns": [("id", "int")], "rows": []}])
        self.assertEqual(self.failing(empty, coverage={"b": ("id", 0, "NpcParam")}), {})

    def test_coverage_of_tables_from_one_game_table_together(self):
        """Several tables, each under half of one game table, never carry it whole between them: the tables of one
        source are measured together, their distinct row ids once, their rows added up."""
        quarters = self.doc(tables=[{"name": "q%d" % k, "columns": [("id", "int"), ("msgId", "int")],
                                     "rows": [[9000000 + i, 9500000 + i] for i in range(10 * k, 10 * k + 10)]}
                                    for k in range(4)])
        by_id = {"q%d" % k: ("id", 40, "TalkParam") for k in range(4)}
        self.assertEqual(self.failing(quarters, coverage=by_id), {6: "tables[2]"})       # 30 of 40 at the third
        by_rows = {"q%d" % k: (None, 40, "TalkParam") for k in range(4)}
        self.assertEqual(self.failing(quarters, coverage=by_rows), {6: "tables[2]"})
        # the same ids in two tables count once
        same = self.doc(tables=[{"name": n, "columns": [("id", "int"), ("msgId", "int")],
                                 "rows": [[9000000 + i, 9500000 + i] for i in range(10)]} for n in ("a", "b")])
        self.assertEqual(self.failing(same, coverage={"a": ("id", 20, "TalkParam"), "b": ("id", 20, "TalkParam")}),
                         {})
        # rows measured by rows add to the ids of the same source
        self.assertEqual(self.failing(same, coverage={"a": ("id", 20, "TalkParam"), "b": (None, 20, "TalkParam")}),
                         {6: "tables[1]"})
        # other sources are measured apart; the lowest bound given for a source holds
        self.assertEqual(self.failing(same, coverage={"a": ("id", 20, "TalkParam"), "b": ("id", 20, "NpcParam")}),
                         {})
        self.assertEqual(self.failing(same, coverage={"a": ("id", 20, "TalkParam"), "b": ("id", 19, "TalkParam")}),
                         {6: "tables[1]"})

    def test_a_coverage_failure_writes_nothing_and_names_no_value(self):
        data = self.per_row([9001234, 9005678, 9009999])
        _, seq = logbook.lines_after(0, limit=0)
        with self.assertRaises(guard.GuardFailed) as cm:
            self.guard.write(self.share, "named-rows", data, declared=self.declared_of(data),
                             coverage={"npc_named": ("id", 4, "NpcParam")})
        self.assertEqual((cm.exception.check, cm.exception.where), (6, "tables[0]"))
        self.assertEqual(list(self.share.iterdir()), [])
        lines, _ = logbook.lines_after(seq)
        text = "\n".join(x["msg"] for x in lines)
        self.assertIn("named-rows.json not written: check 6 at tables[0]", text)
        for v in ("9001234", "9005678", "9009999", "9,001,234"):
            self.assertNotIn(v, text)
        with self.assertRaises(TypeError):
            self.guard.write(self.share, "named-rows", data, declared=self.declared_of(data))   # counts required

    def test_the_kept_row_counts(self):
        path = Path(self.tmp.name) / "work" / "share-counts.json"
        sha = "ef" * 32
        self.assertIsNone(guard.counts_for(path, "named-rows.json", sha))
        guard.record_counts(path, "named-rows.json", sha, {"npc_named": ("id", 20, "NpcParam"), "per_team": None,
                                                           "rows": (None, 7, "placements")})
        self.assertEqual(guard.counts_for(path, "named-rows.json", sha),
                         {"npc_named": ("id", 20, "NpcParam"), "per_team": None, "rows": (None, 7, "placements")})
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["format"], "datapiler-share-counts/2")
        self.assertEqual(doc["files"]["named-rows.json"]["tables"]["npc_named"],
                         {"column": "id", "of": 20, "source": "NpcParam"})
        self.assertIsNone(guard.counts_for(path, "named-rows.json", "00" * 32))      # changed since: none
        self.assertIsNone(guard.counts_for(path, "other.json", sha))
        guard.record_counts(path, "named-rows.json", "00" * 32, {"npc_named": None})   # the next write replaces it
        self.assertIsNone(guard.counts_for(path, "named-rows.json", sha))
        self.assertEqual(guard.counts_for(path, "named-rows.json", "00" * 32), {"npc_named": None})
        for bad in (("../x.json", sha, {}), ("x.json", "nothex", {}), ("x.json", sha, {"T": None}),
                    ("x.json", sha, {"t": ("id", -1, "NpcParam")}), ("x.json", sha, {"t": ("a b", 1, "NpcParam")}),
                    ("x.json", sha, {"t": ("id", 1)}), ("x.json", sha, {"t": ("id", 1, "../x")})):
            with self.subTest(bad=bad[0]):
                with self.assertRaises(ValueError):
                    guard.record_counts(path, *bad)
        path.write_text("not json", encoding="utf-8")
        self.assertIsNone(guard.counts_for(path, "named-rows.json", "00" * 32))
        # the first format's counts, without their sources, are none: the file lists apart until its job runs again
        path.write_text(json.dumps({"format": "datapiler-share-counts/1", "files": {"named-rows.json": {
            "sha256": sha, "tables": {"npc_named": {"column": "id", "of": 20}}}}}), encoding="utf-8")
        self.assertIsNone(guard.counts_for(path, "named-rows.json", sha))


if __name__ == "__main__":
    unittest.main()
