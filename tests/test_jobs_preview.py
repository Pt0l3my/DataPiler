"""The preview (build plan §4.6, §8.3): the example job's lines exactly as the plan words them."""

import _repo  # noqa: F401

import json
import os
import re
import unittest

from datapiler import jobs

FIXTURES = os.path.join(_repo.ROOT, "tests", "fixtures", "job-files")


def load(name: str) -> jobs.Job:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return jobs.check(f.read(), known_ids=(), share_names={})


class PreviewTest(unittest.TestCase):
    def test_the_example(self):
        self.assertEqual(jobs.preview(load("good-example.json")), {
            "reads": ["NpcParam rows: id, nameId, teamType, npcType", "TalkParam rows: id, msgId"],
            "computes": ["join npc with the character names - local",
                         "counts the rows of npc_named per teamType, where named is true"],
            "writes": ["share file `roster-counts.json`: 1 table"],
        })

    def test_every_op(self):
        self.assertEqual(jobs.preview(load("good-every-op.json")), {
            "reads": ["NpcParam rows: id, nameId, teamType, npcType - rows 9000000 to 9000099",
                      "NpcParam: whether its rows have 2 fields named, and their types - no values",
                      "TalkParam rows: id, msgId - 3 rows",
                      "loads 2 maps in Smithbox - its view changes, not its data",
                      "placed characters of 2 maps: entity, row, dialogue and model ids",
                      "the map tiles exported from Smithbox, anywhere in DataPiler's folder: sheet, level, column, "
                      "row, code and size - no image is opened beyond its size",
                      "the exported map tiles of sheet 0, level 4, measured on the PC: for each, its folder's number, "
                      "how much differs from its base and how well it matches the sheet's reference level - numbers only",
                      "the game file `99_invented.testbnd.dcx` that Smithbox unpacked, anywhere in DataPiler's folder, "
                      "opened on the PC: DCX decompressed (KRAK with the game's own Oodle library, loaded from the game "
                      "folder, never copied) and BND4 binders split - never an archive decrypted"],
            "computes": ["join npc with the character names - local",
                         "the entries of the character names that no row of npc names by nameId - local",
                         "keeps the rows of npc_named where teamType >= 6 and teamType <= 30 and npcType in 3 values "
                         "and named is not false",
                         "counts the rows of npc_kept per teamType and named, where nameId > -1",
                         "counts the rows of placed",
                         "distinct model of placed"],
            "writes": ["workspace folder `unpacked/99_invented.testbnd.dcx`: the file's inner files (local, never "
                       "shared)",
                       "workspace file `npc-named.json`: 3 tables (local)",
                       "share file `every-op-counts.json`: 2 tables",
                       "workspace image `every-op-overview.png`: the exported map tiles of sheet 0, level 4, each with "
                       "every piece revealed as the game's own masks give it, where DataPiler finds them, else from "
                       "variants that match the sheet's reference level, labelled (local, never shared)"],
        })

    def test_the_other_wordings(self):
        doc = {"format": jobs.FORMAT, "id": "test-0003-wording", "title": "Wordings", "ops": [
            {"op": "read_placements", "as": "placed", "maps": "all"},
            {"op": "load_maps", "maps": ["m99_00_00_07"]},
            {"op": "fetch_rows", "as": "one", "param": "TalkParam", "fields": ["id"], "ids": [9000001]},
            {"op": "filter", "as": "kept", "rows": "placed", "where": {"model": 9990, "talkId": {"lt": 0.5}}},
            {"op": "distinct", "as": "pairs", "rows": "placed", "by": ["map", "model", "talkId"]},
            {"op": "count", "as": "c", "rows": "placed", "where": {"model": {"in": [9990]}}},
            {"op": "write_local", "name": "placed", "tables": ["placed"]}]}
        p = jobs.preview(jobs.check(json.dumps(doc).encode(), known_ids=(), share_names={}))
        self.assertEqual(p["reads"], ["placed characters of the loaded maps: entity, row, dialogue and model ids",
                                      "loads 1 map in Smithbox - its view changes, not its data",
                                      "TalkParam rows: id - 1 row"])
        self.assertEqual(p["computes"], ["keeps the rows of placed where model is 9990 and talkId < 0.5",
                                         "distinct map, model and talkId of placed",
                                         "counts the rows of placed, where model in 1 value"])
        self.assertEqual(p["writes"], ["workspace file `placed.json`: 1 table (local)"])

    def test_the_explicit_list_of_ids(self):
        p = jobs.preview(load("good-picked.json"))
        self.assertEqual(p["computes"], [
            "join npc with the character names - local",
            "keeps the rows of npc_named where named is true and teamType >= 6",
            "keeps the rows of npc whose id is one of 3 ids listed",
            "keeps the rows of placed whose npcParamId is one of 1 id listed"])

    def test_the_columns_of_every_table(self):
        cols = jobs.columns_of(load("good-example.json"))
        self.assertEqual(cols["npc_named"], [("id", "int"), ("nameId", "int"), ("teamType", "int"),
                                             ("npcType", "int"), ("named", "bool"), ("layer", "int"),
                                          ("name", "text_local")])
        self.assertEqual(cols["per_team"], [("teamType", "int"), ("count", "int")])



def make(ops: list, title: str = "Invented", about: str | None = None) -> jobs.Job:
    doc = {"format": jobs.FORMAT, "id": "test-0300-about", "title": title, "ops": ops}
    if about is not None:
        doc["about"] = about
    return jobs.check(json.dumps(doc).encode(), known_ids=(), share_names={})


def unpack(*files: str) -> list:
    return [{"op": "unpack_game_file", "file": f} for f in files]


def models(map_id: str, n: int, start: int = 100000) -> list:
    return ["%s_%06d.mapbnd.dcx" % (map_id, start + k) for k in range(n)]


AGREED = ("Reads 40 game files: m99_07_00_00 (31 models and its placement file), m99_04_00_00 (7 and its placement "
          "file). Computes nothing. Writes 40 local folders, none shared.")


class SummaryTest(unittest.TestCase):
    """S95 (DP34): the About block's line, counted from the steps in three sentences."""

    def test_the_agreed_example(self):
        self.assertEqual(jobs.summary(load("good-about.json")), AGREED)

    def test_the_designs_example(self):
        self.assertEqual(jobs.summary(load("good-example.json")),
                         "Reads rows of NpcParam and TalkParam. Computes 1 join with the character names and 1 count. "
                         "Writes the share file roster-counts.json.")

    def test_every_op(self):
        self.assertEqual(jobs.summary(load("good-every-op.json")),
                         "Loads 2 maps in Smithbox and reads their placed characters, rows of NpcParam and TalkParam, "
                         "the field types of NpcParam, the names and sizes of the exported map tiles, measurements of "
                         "the map tiles of sheet 0, level 4 and 1 game file: 99_invented.testbnd.dcx. Computes 1 join "
                         "with the character names, 1 list of unused names, 1 filter, 2 counts and 1 distinct list. "
                         "Writes the share file every-op-counts.json, 1 local folder, 1 local file and 1 local image.")

    def test_maps_loaded_and_read(self):
        fams = ["m90_*", "m91_*", "m92_*", "m93_*", "m94_*"]
        j = make([{"op": "load_maps", "maps": fams},
                  {"op": "read_placements", "as": "placed", "maps": list(reversed(fams))},
                  {"op": "count", "as": "c", "rows": "placed", "by": ["map"]},
                  {"op": "write_share", "name": "per-map", "tables": ["c"], "columns": {"c": ["map", "count"]}}])
        self.assertEqual(jobs.summary(j), "Loads the maps of m90_*, m91_*, m92_* and 2 more families in Smithbox and "
                                          "reads their placed characters. Computes 1 count. Writes the share file "
                                          "per-map.json.")
        j = make([{"op": "load_maps", "maps": ["m99_00_00_00", "m99_00_00_01"]},
                  {"op": "read_placements", "as": "a", "maps": ["m99_00_00_00"]},
                  {"op": "read_placements", "as": "b", "maps": "all"}])
        self.assertEqual(jobs.summary(j), "Loads 2 maps in Smithbox and reads the placed characters of the loaded "
                                          "maps. Computes nothing. Writes nothing.")
        j = make([{"op": "read_placements", "as": "a", "maps": ["m99_00_00_00", "m98_*"]}])
        self.assertEqual(jobs.summary(j), "Reads the placed characters of the maps of m98_* and 1 map. Computes "
                                          "nothing. Writes nothing.")

    def test_nothing_read_or_written(self):
        self.assertEqual(jobs.summary(make([{"op": "load_maps", "maps": ["m99_00_00_00"]}])),
                         "Loads 1 map in Smithbox. Computes nothing. Writes nothing.")
        self.assertEqual(jobs.summary(make([{"op": "make_map_overview", "name": "a", "sheet": 1, "level": 2},
                                            {"op": "make_map_overview", "name": "b", "sheet": 1, "level": 3}])),
                         "Reads nothing. Computes nothing. Writes 2 local images, none shared.")

    def test_the_computes_counted(self):
        j = make([{"op": "fetch_rows", "as": "w", "param": "WorldMapPlaceNameParam", "fields": ["id", "textId"]},
                  {"op": "fetch_rows", "as": "n", "param": "NpcParam", "fields": ["id", "nameId"]},
                  {"op": "join_names", "as": "wn", "rows": "w", "key": "textId", "text": "place_names"},
                  {"op": "join_names", "as": "nn", "rows": "n", "key": "nameId", "text": "character_names"},
                  {"op": "unused_names", "as": "u1", "rows": "n", "key": "nameId", "text": "character_names"},
                  {"op": "unused_names", "as": "u2", "rows": "w", "key": "textId", "text": "place_names"},
                  {"op": "distinct", "as": "d", "rows": "n", "by": ["nameId"]},
                  {"op": "check_map_tiles", "as": "t1", "sheet": 0, "level": 2},
                  {"op": "check_map_tiles", "as": "t2", "sheet": 0, "level": 3},
                  {"op": "check_map_tiles", "as": "t3", "sheet": 10, "level": 1},
                  {"op": "write_local", "name": "all", "tables": ["wn", "nn", "u1", "u2", "d", "t1", "t2", "t3"]}])
        self.assertEqual(jobs.summary(j), "Reads rows of WorldMapPlaceNameParam and NpcParam and measurements of the "
                                          "map tiles of sheet 0, levels 2 and 3 and sheet 10, level 1. Computes 2 "
                                          "joins with the place names and the character names, 2 lists of unused "
                                          "names and 1 distinct list. Writes 1 local file, none shared.")

    def test_names_only_what_the_columns_name(self):
        """Every name in the line (a map, a file, a param, a family, the share file) is in the preview's columns."""
        jobs_ = [load(n) for n in ("good-example.json", "good-every-op.json", "good-picked.json", "good-about.json")]
        jobs_.append(make([{"op": "load_maps", "maps": ["m90_*", "m91_*", "m92_*", "m93_*", "m94_*"]}]))
        for j in jobs_:
            with self.subTest(j.id):
                text = " ".join(" ".join(v) for v in jobs.preview(j).values())
                names = [w for w in (x.rstrip(".") for x in re.findall(r"[\w*.-]+", jobs.summary(j)))
                         if re.search(r"[_*.]|[a-z][A-Z]", w)]          # m99_07_00_00, m10_*, x.json, NpcParam
                self.assertTrue(names)
                for word in names:
                    self.assertIn(word, text)


class GroupingTest(unittest.TestCase):
    """S95: unpack_game_file's files grouped by map in the About line."""

    def line(self, files: list) -> str:
        return jobs.summary(make(unpack(*files))).split(". Computes")[0]

    def test_the_map_of_a_file(self):
        for name, m in (("m99_07_00_00_100001.mapbnd.dcx", "m99_07_00_00"), ("m99_07_00_00.msb.dcx", "m99_07_00_00"),
                        ("m99_07_00_00_9.invented.dcx", "m99_07_00_00"), ("m99_07_00.msb.dcx", None),
                        ("m99_07_00_00x.msb.dcx", None), ("a_b_c_d_e.dcx", None), ("99_invented.testbnd.dcx", None),
                        ("M99_07_00_00.msb.dcx", None)):
            with self.subTest(name):
                self.assertEqual(jobs.map_of(name), m)

    def test_models_other_files_and_placement_files(self):
        a = models("m99_01_00_00", 2) + ["m99_01_00_00_5.invented.dcx", "m99_01_00_00.msb.dcx"]
        b = models("m99_02_00_00", 3) + ["m99_02_00_00.msb.dcx"]
        c = ["m99_03_00_00.msb.dcx"]
        d = ["m99_04_00_00_1.invented.dcx", "m99_04_00_00_2.invented.dcx"]
        self.assertEqual(self.line(a + b + c + d), "Reads 11 game files: m99_01_00_00 (2 models, 1 other file and its "
                                                   "placement file), m99_02_00_00 (3 and its placement file), "
                                                   "m99_03_00_00 (its placement file), m99_04_00_00 (2 files)")
        # "models" is said again for a map that has other files too, and for the first map that has models
        self.assertEqual(self.line(c + b + a), "Reads 9 game files: m99_03_00_00 (its placement file), "
                                               "m99_02_00_00 (3 models and its placement file), m99_01_00_00 (2 "
                                               "models, 1 other file and its placement file)")
        self.assertEqual(self.line(models("m99_05_00_00", 1)), "Reads 1 game file: m99_05_00_00 (1 model)")

    def test_more_maps_than_listed(self):
        files = [f for k in range(8) for f in models("m99_%02d_00_00" % k, 2)]
        self.assertEqual(self.line(files), "Reads 16 game files: m99_00_00_00 (2 models), m99_01_00_00 (2), "
                                           "m99_02_00_00 (2), m99_03_00_00 (2), m99_04_00_00 (2) and 3 more maps")
        files = [f for k in range(6) for f in models("m99_%02d_00_00" % k, 1)]
        self.assertTrue(self.line(files).endswith("m99_05_00_00 (1)"))

    def test_files_of_no_map(self):
        self.assertEqual(self.line(["99_invented_a.testbnd.dcx"]), "Reads 1 game file: 99_invented_a.testbnd.dcx")
        loose = ["99_invented_%s.testbnd.dcx" % x for x in "abcde"]
        self.assertEqual(self.line(loose[:3]), "Reads 3 game files: 99_invented_a.testbnd.dcx, "
                                               "99_invented_b.testbnd.dcx, 99_invented_c.testbnd.dcx")
        self.assertEqual(self.line(models("m99_01_00_00", 2) + loose), "Reads 7 game files: m99_01_00_00 (2 models), "
                                                                      "99_invented_a.testbnd.dcx, "
                                                                      "99_invented_b.testbnd.dcx and 3 more files")

    def test_a_file_named_twice_counts_once(self):
        self.assertEqual(jobs.summary(make(unpack("m99_00_00_00.msb.dcx", "m99_00_00_00.msb.dcx"))),
                         "Reads 1 game file: m99_00_00_00 (its placement file). Computes nothing. Writes 1 local "
                         "folder, none shared.")


class RefsTest(unittest.TestCase):
    """S95: the codes a title and an about cite, as the About block's chips."""

    def test_the_codes(self):
        self.assertEqual(jobs.refs("WHY§93, DP28, S81, G27, O48, ER05§8, en-0036"),
                         ["WHY§93", "DP28", "S81", "G27", "O48", "ER05§8", "en-0036"])
        self.assertEqual(jobs.refs("(DESIGN§5; SN04§5.2) P15 D35 R12 T3 ER05 SP3 PV2 DP28-DP30 en-0039-floors."),
                         ["DESIGN§5", "SN04§5.2", "P15", "D35", "R12", "T3", "ER05", "SP3", "PV2", "DP28", "DP30",
                          "en-0039"])

    def test_not_codes(self):
        self.assertEqual(jobs.refs("BND4 DX12 F11 MD5 S7.8.c m12_07_00_00 en-00361 WHY§93a 9DP28 DP28x §4.6 dp28 "
                                   "1.16.0.0 A1 ÄS81 S81Ü"), [])

    def test_once_each_and_capped(self):
        self.assertEqual(jobs.refs("G27 and G27, then WHY§93 and G27"), ["G27", "WHY§93"])
        self.assertEqual(len(jobs.refs(" ".join("S%d" % k for k in range(100)))), jobs.MAX_REFS)
        self.assertEqual(jobs.refs(""), [])

    def test_the_block(self):
        j = make(unpack("m99_00_00_00.msb.dcx"), title="Terrain (G27), the floor rule (WHY§93)",
                 about="Follows en-0039.\nSee DP28 and G27.")
        self.assertEqual(jobs.about_block(j), {
            "text": "Follows en-0039.\nSee DP28 and G27.",
            "summary": "Reads 1 game file: m99_00_00_00 (its placement file). Computes nothing. Writes 1 local folder, "
                       "none shared.",
            "refs": ["G27", "WHY§93", "en-0039", "DP28"]})
        self.assertEqual(jobs.about_block(load("good-example.json"))["text"], None)
        self.assertEqual(jobs.about_block(load("good-example.json"))["refs"], [])


class DetailsTest(unittest.TestCase):
    """S95: the Details columns, the same sentences merged."""

    def test_forty_unpacks_merge_into_one_item_a_column(self):
        j = load("good-about.json")
        files = [o["file"] for o in j.ops]
        tail = jobs.preview(j)["reads"][0].split("` ", 1)[1]
        self.assertEqual(jobs.details(j), {
            "reads": [{"text": "40 game files", "names": files, "tail": tail}],
            "computes": [],
            "writes": [{"text": "40 workspace folders in `unpacked/`", "names": files,
                        "tail": "each with its file's inner files (local, never shared)"}]})
        self.assertTrue(tail.startswith("that Smithbox unpacked") and tail.endswith("never an archive decrypted"))

    def test_nothing_merged_when_no_two_sentences_are_alike(self):
        for name in ("good-example.json", "good-every-op.json", "good-picked.json"):
            with self.subTest(name):
                j = load(name)
                self.assertEqual(jobs.details(j), {k: [{"text": t} for t in v] for k, v in jobs.preview(j).items()})

    def test_the_same_sentence_word_for_word(self):
        ops = [{"op": "fetch_rows", "as": "n", "param": "NpcParam", "fields": ["id", "teamType"]},
               {"op": "count", "as": "c1", "rows": "n", "by": ["teamType"]},
               {"op": "filter", "as": "f", "rows": "n", "where": {"teamType": 1}},
               {"op": "count", "as": "c2", "rows": "n", "by": ["teamType"]},
               {"op": "count", "as": "c3", "rows": "n", "by": ["teamType"]}]
        self.assertEqual(jobs.details(make(ops))["computes"], [
            {"text": "3 steps: counts the rows of n per teamType"},
            {"text": "keeps the rows of n where teamType is 1"}])
        d = jobs.details(make(unpack("m99_00_00_00.msb.dcx", "m99_00_00_00.msb.dcx")))
        self.assertEqual(d["reads"], [{"text": "2 steps: " + jobs.UNPACK_READ % "m99_00_00_00.msb.dcx"}])
        self.assertEqual(d["writes"], [{"text": "2 steps: " + jobs.UNPACK_WRITE % "m99_00_00_00.msb.dcx"}])

    def test_local_files_and_images(self):
        ops = [{"op": "read_map_tiles", "as": "t"},
               {"op": "count", "as": "c", "rows": "t", "by": ["sheet"]},
               {"op": "write_local", "name": "one", "tables": ["t"]},
               {"op": "write_local", "name": "two", "tables": ["t", "c"]},
               {"op": "make_map_overview", "name": "level-2", "sheet": 0, "level": 2},
               {"op": "write_local", "name": "three", "tables": ["c"]},
               {"op": "make_map_overview", "name": "level-2-base", "sheet": 0, "level": 2, "variant": "base"},
               {"op": "make_map_overview", "name": "level-2-again", "sheet": 0, "level": 2}]
        writes = jobs.details(make(ops))["writes"]
        look = jobs.preview(make(ops))["writes"][2].split(": ", 1)[1]
        self.assertEqual(writes, [
            {"text": "2 workspace files", "names": ["one.json", "three.json"], "tail": "each with 1 table (local)"},
            {"text": "workspace file `two.json`: 2 tables (local)"},
            {"text": "2 workspace images", "names": ["level-2.png", "level-2-again.png"], "tail": "of " + look},
            {"text": jobs.preview(make(ops))["writes"][4]}])

    def test_unpacks_among_other_steps_keep_their_place(self):
        ops = [{"op": "read_map_tiles", "as": "t"}] + unpack("99_invented_a.testbnd.dcx") + \
              [{"op": "write_local", "name": "tiles", "tables": ["t"]}] + unpack("99_invented_b.testbnd.dcx")
        d = jobs.details(make(ops))
        self.assertEqual([x["text"] for x in d["reads"]], [jobs.preview(make(ops))["reads"][0], "2 game files"])
        self.assertEqual(d["reads"][1]["names"], ["99_invented_a.testbnd.dcx", "99_invented_b.testbnd.dcx"])
        self.assertEqual([x["text"] for x in d["writes"]], ["2 workspace folders in `unpacked/`",
                                                            "workspace file `tiles.json`: 1 table (local)"])


if __name__ == "__main__":
    unittest.main()
