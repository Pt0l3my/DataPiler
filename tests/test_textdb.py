"""The local text database (build plan §4.9, §8.3): an import, a re-import replacing it, ids and names, text_hit and
find_in. Every text is invented."""

import _repo  # noqa: F401

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datapiler import events, textdb

EXPORTS = os.path.join(_repo.ROOT, "tests", "fixtures", "text-exports")
SETS = {"character_names": (("item", 9001), ("item_dlc01", 9001)), "place_names": (("item", 9002),)}


def export(name: str) -> dict:
    with open(os.path.join(EXPORTS, name), encoding="utf-8") as f:
        return json.load(f)


class TextDBTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = textdb.TextDB(Path(self.tmp.name) / "work" / "textdb.sqlite")
        self.events = []
        self.unsub = events.subscribe("textdb.", lambda t, d: self.events.append((t, d)))
        self.sets = mock.patch.dict(textdb.TEXT_SETS, SETS)
        self.sets.start()

    def tearDown(self):
        self.sets.stop()
        self.unsub()
        self.db.close()
        self.tmp.cleanup()

    def test_an_import(self):
        r = self.db.import_export(export("item-invented.json"), container="item", language="engus", sha256="a" * 64)
        self.assertEqual((r.container, r.language, r.wrappers, r.entries), ("item", "engus", 2, 5))
        self.assertEqual(self.db.entries(), 5)
        self.assertEqual([(c["container"], c["language"], c["wrappers"], c["entries"]) for c in self.db.containers()],
                         [("item", "engus", 2, 5)])
        self.assertTrue(self.db.has("item", "engus"))
        self.assertFalse(self.db.has("item", "frafr"))
        self.assertEqual(self.events[-1], ("textdb.changed", {"containers": 1, "entries": 5}))

    def test_a_reimport_replaces_it(self):
        self.db.import_export(export("item-invented.json"), container="item", language="engus", sha256="a" * 64)
        smaller = export("item-invented.json")
        smaller["FmgWrappers"] = smaller["FmgWrappers"][:1]
        smaller["FmgWrappers"][0]["Fmg"]["Entries"] = smaller["FmgWrappers"][0]["Fmg"]["Entries"][:1]
        r = self.db.import_export(smaller, container="item", language="engus", sha256="b" * 64)
        self.assertEqual(r.entries, 1)
        self.assertEqual(self.db.entries(), 1)
        self.assertFalse(self.db.text_hit("Lamplighter"))
        self.assertTrue(self.db.text_hit("Quillon Marrowgate"))
        self.db.import_export(export("item-invented.json"), container="item", language="frafr", sha256="c" * 64)
        self.assertEqual(self.db.entries(), 6)

    def test_ids_and_names(self):
        self.db.import_export(export("item-invented.json"), container="item", language="engus", sha256="a" * 64)
        self.db.import_export(export("item-dlc01-older.json"), container="item_dlc01", language="engus",
                              sha256="d" * 64)
        self.assertEqual(self.db.ids("character_names", "engus"), {9000000, 9000001, 9000004, 9000010})
        names = self.db.names("character_names", "engus")
        self.assertEqual(names[9000000], "Quillon Marrowgate")          # the base container first
        self.assertEqual(names[9000010], "Odrin Vellmoor")
        self.assertNotIn(9000002, names)                                 # an empty text is skipped
        self.assertNotIn(9000003, names)                                 # and a missing one
        self.assertEqual(self.db.ids("place_names", "engus"), {9100000, 9100001})
        self.assertEqual(self.db.ids("character_names", "frafr"), set())
        with self.assertRaises(KeyError):
            self.db.ids("item_names", "engus")

    def test_no_wrappers_known_gives_nothing(self):
        self.db.import_export(export("item-invented.json"), container="item", language="engus", sha256="a" * 64)
        with mock.patch.dict(textdb.TEXT_SETS, {"character_names": ()}):
            self.assertEqual(self.db.ids("character_names", "engus"), set())

    def test_text_hit(self):
        self.db.import_export(export("item-invented.json"), container="item", language="engus", sha256="a" * 64)
        hits = ["Quillon Marrowgate", "quillon marrowgate", "QUILLON MARROWGATE",   # equal, case-folded
                "marrow", "lamplighter", "ashgrove",                                # contained in a text
                "at the hollow of ashgrove!", "xCorrow Landingx"]                   # contains a text
        for s in hits:
            self.assertTrue(self.db.text_hit(s), s)
        self.assertTrue(self.db.text_hit("per_team corrow landing"))               # contains a text
        misses = ["per_team", "count", "teamType", "the", "of", "", "Unl", "named_only", "hollowash"]
        for s in misses:
            self.assertFalse(self.db.text_hit(s), s)

    def test_text_hit_whatever_stands_between_the_words(self):
        """A table name ([a-z0-9_]) or a job id ([a-z0-9-]) cannot hold a space nor an accent, so a text written with
        `_` or `-` between its words, or without its accents, is the text still (invented texts)."""
        self.db.import_export(export("item-invented.json"), container="item", language="engus", sha256="a" * 64)
        self.db.import_export({"Name": "item_dlc01", "FmgWrappers": [{"Name": "W", "ID": 1, "Fmg": {"Entries": [
            {"ID": 1, "Text": "White Mask Varr\u00e9"}, {"ID": 2, "Text": "Ser Ostrel-Vane"}]}}]},
            container="item_dlc01", language="engus", sha256="f" * 64)
        for s in ("the_hollow_of_ashgrove", "quillon_marrowgate", "quillon-marrowgate", "white_mask_varre",
                  "white-mask-varre", "ser_ostrel_vane", "ser-ostrel-vane", "varre", "en-0012-white-mask-varre-x",
                  "quillon_marrowgate_counts", "WHITE MASK VARR\u00c9"):
            with self.subTest(s=s):
                self.assertTrue(self.db.text_hit(s), s)
        for s in ("per_team", "rows_total", "named_only", "en-0007-roster-counts", "white_masks", "ostrelvane"):
            with self.subTest(s=s):
                self.assertFalse(self.db.text_hit(s), s)
        # the same for a line Copy for sharing checks
        self.assertTrue(self.db.find_in("workspace file white_mask_varre.json written: 1 tables"))
        self.assertFalse(self.db.find_in("workspace file roster_rows.json written: 1 tables"))
        self.assertEqual(textdb.normalise("  White Mask  Varr\u00e9!  "), "white mask varre")
        self.assertEqual(textdb.normalise("ser_ostrel--vane"), "ser ostrel vane")

    def test_short_texts_match_only_when_equal(self):
        data = {"Name": "item", "FmgWrappers": [{"Name": "W", "ID": 1, "Fmg": {"Entries": [
            {"ID": 1, "Text": "Orb"}, {"ID": 2, "Text": "Vellmoor"}]}}]}
        self.db.import_export(data, container="item", language="engus", sha256="e" * 64)
        self.assertTrue(self.db.text_hit("orb"))
        self.assertFalse(self.db.text_hit("orbit"))          # a text under 4 characters is not looked for inside
        self.assertFalse(self.db.text_hit("or"))             # nor is a string under 4 inside a text
        self.assertTrue(self.db.text_hit("vell"))            # 4 characters inside a text
        self.assertTrue(self.db.text_hit("odrin_vellmoor_count"))

    def test_find_in(self):
        self.db.import_export(export("item-invented.json"), container="item", language="engus", sha256="a" * 64)
        self.assertTrue(self.db.find_in("2026-11-08 08:42:01.123  INFO   job      saw the HOLLOW of ashgrove here"))
        self.assertTrue(self.db.find_in("xxcorrow landingxx"))
        self.assertFalse(self.db.find_in("2026-11-08 08:42:01.123  INFO   extract  NpcParam: 2,105 rows read"))
        self.assertFalse(self.db.find_in("abc"))

    def test_an_empty_database(self):
        self.assertEqual(self.db.entries(), 0)
        self.assertFalse(self.db.text_hit("anything at all"))
        self.assertFalse(self.db.find_in("anything at all"))
        self.assertEqual(self.db.containers(), [])

    def test_close(self):
        self.db.close()
        self.db.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            self.db.entries()


if __name__ == "__main__":
    unittest.main()
