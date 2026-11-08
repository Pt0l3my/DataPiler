"""The preview (build plan §4.6, §8.3): the example job's lines exactly as the plan words them."""

import _repo  # noqa: F401

import json
import os
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
                      "TalkParam rows: id, msgId - 3 rows",
                      "loads 2 maps in Smithbox - its view changes, not its data",
                      "placed characters of 2 maps: entity, row, dialogue and model ids"],
            "computes": ["join npc with the character names - local",
                         "keeps the rows of npc_named where teamType >= 6 and teamType <= 30 and npcType in 3 values "
                         "and named is not false",
                         "counts the rows of npc_kept per teamType and named, where nameId > -1",
                         "counts the rows of placed",
                         "distinct model of placed"],
            "writes": ["workspace file `npc-named.json`: 2 tables (local)",
                       "share file `every-op-counts.json`: 2 tables"],
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
                                             ("npcType", "int"), ("named", "bool"), ("name", "text_local")])
        self.assertEqual(cols["per_team"], [("teamType", "int"), ("count", "int")])


if __name__ == "__main__":
    unittest.main()
