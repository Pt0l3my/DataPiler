"""The job check (build plan §4.6, §8.3): the design's example passes; each refusal from a fixture, with its exact
text; a value that is not identifier-shaped is never quoted; DP8's lineage (settled S18): only narrowed and
aggregate tables reach write_share, and filter's explicit list of ids."""

import _repo  # noqa: F401

import json
import os
import unittest

from datapiler import VERSION, fields, jobs

FIXTURES = os.path.join(_repo.ROOT, "tests", "fixtures", "job-files")
PLANTED = "Quillon Marrowgate"
OPS_LIST = "fetch_rows, load_maps, read_placements, join_names, unused_names, filter, count, distinct, write_local, write_share"

# Each bad fixture gives exactly one refusal: (where, text).
EXPECTED = {
    "bad-not-json.json": ("(file)", "the file is not JSON"),
    "bad-not-object.json": ("(file)", "the file is not a JSON object"),
    "bad-too-deep.json": ("(file)", "the file nests deeper than 16 levels"),
    "bad-wrong-format.json": ("format", "not a format DataPiler reads (it reads datapiler-job/1)"),
    "bad-unknown-key.json": ("(top level)", "`colour` is not a key of a job (format, id, title, ops, needs)"),
    "bad-duplicate-key.json": ("(top level)", "a key is given twice"),
    "bad-unknown-op.json": ("ops[2].op", "`run_command` is not an operation DataPiler has (%s)" % OPS_LIST),
    "bad-unknown-argument.json": ("ops[0]", "`path` is not an argument of fetch_rows"),
    "bad-field-not-read.json": ("ops[3].fields[1]", "`teamName` is not a field DataPiler reads (ids and numbers only)"),
    "bad-unquoted-value.json": ("ops[0].fields[1]", "not a field DataPiler reads (ids and numbers only)"),
    "bad-path-name.json": ("ops[4].name", "not a file name (a-z, 0-9, _ and -, up to 64 characters) - never a path"),
    "bad-as-twice.json": ("ops[1].as", "`npc` is the name of an earlier table - each `as` is used once"),
    "bad-later-table.json": ("ops[1].rows", "`npc_named` is made by a later operation (ops[2]) - an operation reads "
                                            "only the tables made before it"),
    "bad-two-write-share.json": ("ops[5]", "a job writes one share file at most - ops[4] writes one already"),
    "bad-text-local-share.json": ("ops[4].columns.named_rows[1]", "`name` holds local text (the names) and never "
                                                                  "goes into a share file"),
    "bad-raw-share.json": ("ops[1].tables[0]", "`npc` comes straight from fetch_rows (ops[0]) - " + jobs.DP8_RULE),
    "bad-needs-newer.json": ("needs", "this job needs DataPiler 0.3 or newer; this is %s" % VERSION),
    "bad-extract-prefix.json": ("id", "`extract-roster`: ids starting `extract` are kept for Extract's own jobs"),
    "bad-load-all.json": ("ops[0].maps", "\"all\" cannot be loaded in 0.1: none of the allowed calls lists every map - "
                                         "name the maps by id"),
    "bad-where-type.json": ("ops[3].where.named", "`named` is a flag - compare it with true or false"),
    "bad-missing-title.json": ("title", "missing - a job has a title of 1 to 120 characters"),
}


def fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def check(raw: bytes, **kw) -> jobs.Job:
    kw.setdefault("known_ids", ())
    kw.setdefault("share_names", {})
    return jobs.check(raw, **kw)


def refusals(raw: bytes, **kw) -> list:
    with unittest.TestCase().assertRaises(jobs.JobRefused) as cm:
        check(raw, **kw)
    return cm.exception.refusals


def example() -> dict:
    return json.loads(fixture("good-example.json"))


class ExampleTest(unittest.TestCase):
    def test_the_designs_example_passes(self):
        raw = fixture("good-example.json")
        job = check(raw)
        self.assertEqual(job.id, "en-0007-roster-counts")
        self.assertEqual(job.title, "Roster: named characters per team")
        self.assertEqual(len(job.sha256), 64)
        self.assertEqual(len(job.ops), 5)
        self.assertTrue(job.uses_link)
        self.assertEqual(job.maps, 0)
        self.assertEqual(job.share_name, "roster-counts")
        self.assertIsNone(job.needs)

    def test_every_op_passes(self):
        job = check(fixture("good-every-op.json"))
        self.assertEqual(job.maps, 2)
        self.assertEqual(job.needs, "0.1")
        self.assertEqual([o["op"] for o in job.ops].count("count"), 2)
        self.assertEqual(set(o["op"] for o in job.ops), set(jobs.OPS))

    def test_a_built_in_id_passes_only_as_built_in(self):
        doc = example()
        doc["id"] = "extract-character_rows"
        raw = json.dumps(doc).encode()
        self.assertEqual(check(raw, builtin=True).id, "extract-character_rows")
        self.assertEqual([r.where for r in refusals(raw)], ["id"])


def job(ops: list, jid: str = "test-0200-lineage") -> bytes:
    return json.dumps({"format": jobs.FORMAT, "id": jid, "title": "Lineage (invented)", "ops": ops}).encode()


NPC = {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId", "teamType"]}
JOIN = {"op": "join_names", "as": "npc_named", "rows": "npc", "key": "nameId", "text": "character_names"}
PLACED = {"op": "read_placements", "as": "placed", "maps": "all"}


def share(*tables: str, cols=None) -> dict:
    return {"op": "write_share", "name": "lineage", "tables": list(tables),
            "columns": {t: (cols or {}).get(t, ["teamType"] if t != "placed_x" else ["map"]) for t in tables}}


class LineageTest(unittest.TestCase):
    """DP8 (settled S18): raw tables, and filters and distincts of them, never reach write_share; the named rows, an
    explicit list of ids and a count do. The refusal names the operation and the rule."""

    def refused_at(self, ops: list) -> list:
        return [(r.where, r.text) for r in refusals(job(ops))]

    def test_what_is_refused(self):
        rule = jobs.DP8_RULE
        cases = [
            ([NPC, share("npc")], "`npc` comes straight from fetch_rows (ops[0])"),
            ([NPC, JOIN, share("npc_named")],
             "`npc_named` is join_names (ops[1]) of rows straight from fetch_rows (ops[0]): it keeps every row, named "
             "or not"),
            ([NPC, {"op": "filter", "as": "f", "rows": "npc", "where": {"teamType": {"ge": 6}}}, share("f")],
             "`f` is a filter (ops[1]) of rows straight from fetch_rows (ops[0]), never narrowed"),
            ([NPC, JOIN, {"op": "filter", "as": "f", "rows": "npc_named", "where": {"named": False}}, share("f")],
             "`f` is a filter (ops[2]) of rows straight from fetch_rows (ops[0]), never narrowed"),
            ([NPC, {"op": "filter", "as": "f", "rows": "npc", "where": {"id": {"in": [1, 2]}}}, share("f")],
             "`f` is a filter (ops[1]) of rows straight from fetch_rows (ops[0]), never narrowed"),
            ([NPC, {"op": "distinct", "as": "d", "rows": "npc", "by": ["teamType"]}, share("d")],
             "`d` is a distinct (ops[1]) of rows straight from fetch_rows (ops[0])"),
            ([NPC, {"op": "count", "as": "c", "rows": "npc", "by": ["id"]}, share("c", cols={"c": ["id", "count"]})],
             "`c` is a count (ops[1]) by `id`, the row id of rows straight from fetch_rows (ops[0]): one row per row "
             "id"),
            ([PLACED, {"op": "distinct", "as": "placed_x", "rows": "placed", "by": ["map"]}, share("placed_x")],
             "`placed_x` is a distinct (ops[1]) of rows straight from read_placements (ops[0])"),
            ([PLACED, share("placed", cols={"placed": ["map"]})],
             "`placed` comes straight from read_placements (ops[0])"),
            # P15: a count of a raw table by a column of other tables' ids is that column, with counts
            ([NPC, {"op": "count", "as": "c", "rows": "npc", "by": ["nameId"]},
              share("c", cols={"c": ["nameId", "count"]})],
             "`c` is a count (ops[1]) by `nameId`, a column of ids, of rows straight from fetch_rows (ops[0]): one row "
             "per id it holds"),
            ([NPC, {"op": "count", "as": "c", "rows": "npc", "by": ["teamType", "nameId"]},
              share("c", cols={"c": ["teamType", "count"]})],
             "`c` is a count (ops[1]) by `nameId`, a column of ids, of rows straight from fetch_rows (ops[0]): one row "
             "per id it holds"),
            ([NPC, JOIN, {"op": "count", "as": "c", "rows": "npc_named", "by": ["nameId"], "where": {"named": True}},
              share("c", cols={"c": ["nameId", "count"]})],
             "`c` is a count (ops[2]) by `nameId`, a column of ids, of rows straight from fetch_rows (ops[0]): one row "
             "per id it holds"),
            ([{"op": "fetch_rows", "as": "talk", "param": "TalkParam", "fields": ["msgId"]},
              {"op": "count", "as": "c", "rows": "talk", "by": ["msgId"]},
              {"op": "distinct", "as": "d", "rows": "c", "by": ["msgId"]}, share("d", cols={"d": ["msgId"]})],
             "`d` is a distinct (ops[2]) of rows straight from fetch_rows (ops[0])"),
            ([PLACED, {"op": "count", "as": "c", "rows": "placed", "by": ["map", "npcParamId", "talkId", "model"]},
              share("c", cols={"c": ["map", "count"]})],
             "`c` is a count (ops[1]) by `npcParamId`, a column of ids, of rows straight from read_placements "
             "(ops[0]): one row per id it holds"),
            ([PLACED, {"op": "count", "as": "c", "rows": "placed", "by": ["model"]},
              share("c", cols={"c": ["model", "count"]})],
             "`c` is a count (ops[1]) by `model`, a column of ids, of rows straight from read_placements (ops[0]): "
             "one row per id it holds"),
        ]
        for ops, how in cases:
            with self.subTest(how=how):
                got = self.refused_at(ops)
                self.assertEqual(got, [("ops[%d].tables[0]" % (len(ops) - 1), how + " - " + rule)])

    def test_what_passes(self):
        ok = [
            [NPC, {"op": "count", "as": "c", "rows": "npc", "by": ["teamType"]}, share("c")],
            [NPC, {"op": "count", "as": "c", "rows": "npc"}, share("c", cols={"c": ["count"]})],
            [NPC, JOIN, {"op": "filter", "as": "n", "rows": "npc_named", "where": {"named": True}}, share("n")],
            [NPC, JOIN, {"op": "filter", "as": "n", "rows": "npc_named", "where": {"named": {"eq": True}}}, share("n")],
            [NPC, JOIN, {"op": "filter", "as": "n", "rows": "npc_named", "where": {"named": {"ne": False}}},
             {"op": "distinct", "as": "d", "rows": "n", "by": ["teamType"]}, share("d")],
            [NPC, {"op": "filter", "as": "p", "rows": "npc", "ids": [9000001]},
             {"op": "filter", "as": "q", "rows": "p", "where": {"teamType": 1}}, share("q")],
            [NPC, {"op": "filter", "as": "p", "rows": "npc", "ids": [9000001]},
             {"op": "count", "as": "c", "rows": "p", "by": ["id"]}, share("c", cols={"c": ["id", "count"]})],
            [PLACED, {"op": "filter", "as": "p", "rows": "placed", "key": "npcParamId", "ids": [9000001]},
             share("p", cols={"p": ["map", "entityId"]})],
            [PLACED, {"op": "filter", "as": "p", "rows": "placed", "ids": [9001000]},
             share("p", cols={"p": ["map", "npcParamId"]})],
            # a count by columns that hold no ids, or by ids of rows already picked
            [PLACED, {"op": "count", "as": "c", "rows": "placed", "by": ["map"]},
             share("c", cols={"c": ["map", "count"]})],
            [NPC, JOIN, {"op": "filter", "as": "n", "rows": "npc_named", "where": {"named": True}},
             {"op": "count", "as": "c", "rows": "n", "by": ["nameId"]}, share("c", cols={"c": ["nameId", "count"]})],
            [PLACED, {"op": "filter", "as": "p", "rows": "placed", "key": "npcParamId", "ids": [9000001]},
             {"op": "count", "as": "c", "rows": "p", "by": ["talkId"]}, share("c", cols={"c": ["talkId", "count"]})],
        ]
        for ops in ok:
            with self.subTest(ops=[o["op"] for o in ops]):
                check(job(ops))

    def test_the_columns_of_ids_are_listed_for_every_param(self):
        """fields.REFERENCES names, for every param DataPiler reads, which of its fields hold other tables' ids (P15),
        and the placements' are their reference columns."""
        self.assertEqual(set(fields.REFERENCES), set(fields.PARAMS))
        for param, refs in fields.REFERENCES.items():
            for f in refs:
                self.assertEqual(fields.PARAMS[param].get(f), "int", (param, f))
                self.assertNotEqual(f, "id")
        self.assertEqual(set(jobs.PLACEMENT_REFERENCES) | {"map", "entityId"}, {c for c, _ in jobs.PLACEMENT_COLUMNS})
        j = check(job([NPC, PLACED, {"op": "write_local", "name": "x", "tables": ["npc", "placed"]}]))
        self.assertEqual(j.lineage["npc"].refs, ("nameId",))
        self.assertEqual(j.lineage["placed"].refs, ("npcParamId", "talkId", "model"))

    def test_the_lineage_on_the_job(self):
        j = check(fixture("good-picked.json"))
        got = {t: (lin.kind, lin.source, lin.id_col, lin.per_row) for t, lin in j.lineage.items()}
        self.assertEqual(got, {"npc": ("raw", 0, "id", True), "npc_named": ("raw", 0, "id", True),
                               "named_rows": ("narrowed", 0, "id", True), "picked": ("narrowed", 0, "id", True),
                               "placed": ("raw", 4, "entityId", True),
                               "placed_picked": ("narrowed", 4, "entityId", True)})
        # filter's `ids` without `key` picks by the row id, and the checked op says so
        self.assertEqual(j.ops[3]["key"], "id")
        self.assertEqual(j.ops[5]["key"], "npcParamId")

    def test_ids_rules(self):
        self.assertEqual(self.refused_at([NPC, {"op": "filter", "as": "f", "rows": "npc"}, share("f")])[0],
                         ("ops[1]", "a filter needs `where`, `ids`, `slots` or more than one"))
        self.assertEqual(self.refused_at([NPC, {"op": "filter", "as": "f", "rows": "npc", "key": "id",
                                                "where": {"teamType": 1}},
                                          {"op": "count", "as": "c", "rows": "f"}, share("c", cols={"c": ["count"]})]),
                         [("ops[1].key", "`key` names the column `ids` picks by - give `ids` too")])
        self.assertEqual(self.refused_at([NPC, {"op": "filter", "as": "f", "rows": "npc", "key": "nameId",
                                                "ids": [1]}, {"op": "count", "as": "c", "rows": "f"},
                                          share("c", cols={"c": ["count"]})]),
                         [("ops[1].key", "`nameId` is not a column ids can pick npc's rows by (id)")])
        got = self.refused_at([NPC, {"op": "count", "as": "c", "rows": "npc", "by": ["teamType"]},
                               {"op": "filter", "as": "f", "rows": "c", "ids": [1]}, share("f")])
        self.assertEqual(got, [("ops[2].ids", "`c` has no row-id column to pick by (`id` from fetch_rows, `entityId` "
                                              "or `npcParamId` from read_placements) - a count or a distinct keeps "
                                              "none")])
        for bad, text in (([], "must be a list of 1 to 1,000 row ids (whole numbers)"),
                          (list(range(1001)), "must be a list of 1 to 1,000 row ids (whole numbers)"),
                          ("9000001", "must be a list of 1 to 1,000 row ids (whole numbers)")):
            got = self.refused_at([NPC, {"op": "filter", "as": "f", "rows": "npc", "ids": bad},
                                   {"op": "count", "as": "c", "rows": "f"}, share("c", cols={"c": ["count"]})])
            self.assertEqual(got, [("ops[1].ids", text)])
        got = self.refused_at([NPC, {"op": "filter", "as": "f", "rows": "npc", "ids": [1, "Quillon Marrowgate"]},
                               {"op": "count", "as": "c", "rows": "f"}, share("c", cols={"c": ["count"]})])
        self.assertEqual(got, [("ops[1].ids[1]", "not a row id (a whole number)")])

    def test_extracts_own_share_files_hold_counts_only(self):
        """Extract writes the workspace, and at most a counts-only summary share file: no id reaches it."""
        from datapiler import catalogue
        for r in catalogue.ROWS:
            if "server" not in r.sources:
                self.assertEqual(r.goes_to, "workspace")
                continue
            with self.subTest(r.id):
                self.assertEqual(r.goes_to, "workspace+counts")
                ops = catalogue.ops_for(r.id)
                j = check(json.dumps({"format": jobs.FORMAT, "id": catalogue.job_id(r.id), "title": r.name,
                                      "ops": ops}).encode(), builtin=True)
                shares = [o for o in j.ops if o["op"] == "write_share"]
                self.assertLessEqual(len(shares), 1)
                for o in shares:
                    for t in o["tables"]:
                        self.assertEqual(j.lineage[t].kind, "aggregate", t)
                        self.assertEqual(o["columns"][t], ["count"], t)


class RefusalTest(unittest.TestCase):
    def test_every_bad_fixture_is_listed(self):
        bad = sorted(f for f in os.listdir(FIXTURES) if f.startswith("bad-"))
        self.assertEqual(bad, sorted(EXPECTED))

    def test_each_fixture_gives_its_one_refusal(self):
        for name, (where, text) in EXPECTED.items():
            with self.subTest(name):
                got = refusals(fixture(name))
                self.assertEqual([(r.where, r.text) for r in got], [(where, text)])

    def test_the_line_reads_place_then_rule(self):
        r = refusals(fixture("bad-field-not-read.json"))[0]
        self.assertEqual(r.line(),
                         "ops[3].fields[1]: `teamName` is not a field DataPiler reads (ids and numbers only)")
        self.assertEqual(r.op, 3)

    def test_too_large(self):
        raw = b"{" + b" " * jobs.MAX_BYTES + b"}"
        self.assertEqual([(r.where, r.text) for r in refusals(raw)], [("(file)", "the file is over 256 KB")])

    def test_empty(self):
        self.assertEqual([r.text for r in refusals(b"")], ["the file is empty"])

    def test_not_utf8_and_nan(self):
        self.assertEqual([r.text for r in refusals(b"\xff\xfe{}")], ["the file is not UTF-8 text"])
        doc = json.dumps(example()).replace('"named": true', '"named": NaN').encode()
        self.assertEqual([r.text for r in refusals(doc)], ["the file is not JSON"])

    def test_an_id_used_twice(self):
        got = refusals(fixture("good-example.json"), known_ids={"en-0007-roster-counts"})
        self.assertEqual([(r.where, r.text) for r in got],
                         [("id", "`en-0007-roster-counts` is the id of another job here - give this one its own id")])

    def test_reserved_ids(self):
        for jid, text in (("extract", "`extract`: ids starting `extract` are kept for Extract's own jobs"),
                          ("refused-0011aa", "`refused-0011aa`: ids starting `refused-` are kept for refused files")):
            doc = example()
            doc["id"] = jid
            self.assertEqual([r.text for r in refusals(json.dumps(doc).encode())], [text])

    def test_names_windows_keeps_for_devices(self):
        """An id names jobs/<id>/ and logs/jobs/<id>.log, a write's name share/<name>.json: on Windows "con" or
        "nul" there is a device, not a file."""
        for name in ("con", "prn", "aux", "nul", "com1", "lpt9"):
            with self.subTest(name=name):
                doc = example()
                doc["id"] = name
                self.assertEqual([(r.where, r.text) for r in refusals(json.dumps(doc).encode())],
                                 [("id", "`%s` is a name Windows keeps for a device - choose another id" % name)])
                doc = example()
                doc["ops"][4]["name"] = name
                self.assertEqual([(r.where, r.text) for r in refusals(json.dumps(doc).encode())],
                                 [("ops[4].name", "`%s` is a name Windows keeps for a device - choose another name"
                                   % name)])
        doc = example()
        doc["id"], doc["ops"][4]["name"] = "console", "con-counts"
        self.assertEqual(check(json.dumps(doc).encode()).share_name, "con-counts")

    def test_a_share_name_used_by_another_job(self):
        got = refusals(fixture("good-example.json"), share_names={"roster-counts": "test-0099-other"})
        self.assertEqual([(r.where, r.text) for r in got],
                         [("ops[4].name", "`roster-counts` is the share file of the job `test-0099-other` already")])
        self.assertEqual(check(fixture("good-example.json"),
                               share_names={"roster-counts": "en-0007-roster-counts"}).share_name, "roster-counts")

    def test_needs(self):
        for needs, ok in (("0.1", True), ("0.1.0", True), ("0.2", True), (VERSION, True), ("0.0.9", True), ("0.2.7", False),
                          ("0.3", False), ("1.0", False)):
            doc = example()
            doc["needs"] = needs
            raw = json.dumps(doc).encode()
            if ok:
                self.assertEqual(check(raw).needs, needs)
            else:
                self.assertEqual([r.where for r in refusals(raw)], ["needs"])
        doc = example()
        doc["needs"] = "0.2-beta"
        self.assertEqual([r.text for r in refusals(json.dumps(doc).encode())],
                         ["must be a version such as 0.1 or 0.1.0"])

    def test_a_job_refers_to_its_own_table(self):
        doc = example()
        doc["ops"][3]["rows"] = "per_team"
        got = refusals(json.dumps(doc).encode())
        self.assertEqual([r.where for r in got], ["ops[3].rows"])

    def test_columns_of_the_wrong_type(self):
        doc = example()
        doc["ops"][2]["key"] = "named"
        self.assertEqual([r.where for r in refusals(json.dumps(doc).encode())], ["ops[2].key"])
        doc = example()
        doc["ops"][3]["by"] = ["name"]
        self.assertEqual([(r.where, r.text) for r in refusals(json.dumps(doc).encode())],
                         [("ops[3].by[0]", "`name` holds local text - `by` takes columns of whole numbers or flags")])

    def test_where_rules(self):
        cases = [({"teamType": {"ge": True}}, "ops[3].where.teamType.ge"),
                 ({"named": {"lt": 1}}, "ops[3].where.named.lt"),
                 ({"teamType": {"in": []}}, "ops[3].where.teamType.in"),
                 ({"teamType": {"between": 3}}, "ops[3].where.teamType"),
                 ({"name": 1}, "ops[3].where.name"),
                 ({}, "ops[3].where")]
        for where, place in cases:
            with self.subTest(place):
                doc = example()
                doc["ops"][3]["where"] = where
                self.assertEqual([r.where for r in refusals(json.dumps(doc).encode())], [place])

    def test_ids_rules(self):
        for ids, place in (([], "ops[0].ids"), ([1, "2"], "ops[0].ids[1]"), ([True], "ops[0].ids[0]"),
                           ({"from": 5, "to": 1}, "ops[0].ids"), ({"from": 1}, "ops[0].ids"),
                           ([2 ** 40], "ops[0].ids[0]")):
            with self.subTest(ids=ids):
                doc = example()
                doc["ops"][0]["ids"] = ids
                self.assertEqual([r.where for r in refusals(json.dumps(doc).encode())], [place])

    def test_many_refusals_at_once(self):
        doc = example()
        doc["colour"] = 1
        doc["ops"][0]["param"] = "ChrInvented"
        doc["ops"][4]["notes"] = ["not_a_label"]
        got = refusals(json.dumps(doc).encode())
        self.assertEqual([r.where for r in got], ["(top level)", "ops[0].param", "ops[4].notes[0]"])

    def test_the_count_of_refusals_is_capped(self):
        doc = example()
        doc["ops"] = [{"op": "frob%d" % i} for i in range(64)]
        got = refusals(json.dumps(doc).encode())
        self.assertLessEqual(len(got), 61)
        self.assertTrue(got[-1].text.startswith("and "))


class NeverQuotedTest(unittest.TestCase):
    """A value that is not identifier-shaped is never quoted, nor put in a place."""

    def test_planted_values_never_appear(self):
        values = [PLANTED, "../x", "a/b", "C:\\x", "Öskarvale-gate", "x" * 65, "with space", "semi;colon"]
        for v in values:
            doc = example()
            doc["id"] = v
            doc["format"] = jobs.FORMAT
            doc["ops"][0]["as"] = v
            doc["ops"][0]["param"] = v
            doc["ops"][0]["fields"] = ["id", v]
            doc["ops"][1]["op"] = v
            doc["ops"][2]["text"] = v
            doc["ops"][3]["where"] = {v: 1}
            doc["ops"][4]["name"] = v
            doc["ops"][4]["notes"] = [v]
            doc[v] = 1
            with self.subTest(v=v):
                got = refusals(json.dumps(doc).encode())
                self.assertGreater(len(got), 5)
                for r in got:
                    self.assertNotIn(v, r.text)
                    self.assertNotIn(v, r.where)

    def test_a_wrong_format_is_quoted_only_when_shaped(self):
        doc = example()
        doc["format"] = "job_one"
        self.assertEqual([r.text for r in refusals(json.dumps(doc).encode())],
                         ["`job_one` is not a format DataPiler reads (it reads datapiler-job/1)"])


class RefusedCardTest(unittest.TestCase):
    def test_the_refusal_carries_a_usable_id_and_title(self):
        with self.assertRaises(jobs.JobRefused) as cm:
            check(fixture("bad-field-not-read.json"))
        self.assertEqual(cm.exception.id, "en-0007-roster-counts")
        self.assertEqual(cm.exception.title, "Roster: named characters per team")
        self.assertTrue(cm.exception.format_ok)
        with self.assertRaises(jobs.JobRefused) as cm:
            check(fixture("good-example.json"), known_ids={"en-0007-roster-counts"})
        self.assertIsNone(cm.exception.id)


if __name__ == "__main__":
    unittest.main()


class BossOpsTest(unittest.TestCase):
    """0.2.3: unused_names (S47), map families (S45) and boss slots (S46)."""

    def refused_at(self, ops: list) -> list:
        return [(r.where, r.text) for r in refusals(job(ops))]

    def test_unused_names_is_narrowed_and_shareable(self):
        un = {"op": "unused_names", "as": "un", "rows": "npc", "key": "nameId", "text": "character_names"}
        j = check(job([NPC, un, share("un", cols={"un": ["nameId", "layer"]})]))
        self.assertEqual(j.lineage["un"].kind, "narrowed")
        self.assertEqual(jobs.columns_of(j)["un"], list(jobs.UNUSED_COLUMNS))
        self.assertEqual(self.refused_at([NPC, dict(un, text="weapon_names"), share("un", cols={"un": ["nameId"]})])[0][0],
                         "ops[1].text")
        self.assertEqual(self.refused_at([NPC, dict(un, key="nope"), share("un", cols={"un": ["nameId"]})])[0][0],
                         "ops[1].key")

    def test_map_families(self):
        j = check(job([{"op": "load_maps", "maps": ["m10_*", "m11_00_00_00"]},
                       {"op": "read_placements", "as": "placed", "maps": ["m10_*"]},
                       {"op": "count", "as": "c", "rows": "placed"}, share("c", cols={"c": ["count"]})]))
        self.assertEqual((j.maps, j.map_families), (1, ("m10_*",)))
        self.assertEqual(jobs.preview(j)["reads"][0],
                         "loads the maps of m10_* and 1 map in Smithbox - its view changes, not its data")
        for bad in ("m1_*", "m10*", "m10_00_*", "*"):
            self.assertEqual(self.refused_at([{"op": "load_maps", "maps": [bad]}])[0][0], "ops[0].maps[0]")

    def test_boss_slots(self):
        slots = {"op": "filter", "as": "b", "rows": "placed", "slots": "boss"}
        j = check(job([PLACED, slots, share("b", cols={"b": ["map", "entityId", "npcParamId"]})]))
        self.assertEqual(j.lineage["b"].kind, "narrowed")
        self.assertIn("boss slot", jobs.preview(j)["computes"][0])
        self.assertEqual(self.refused_at([PLACED, dict(slots, slots="all"), share("b", cols={"b": ["map"]})])[0][0],
                         "ops[1].slots")
        self.assertEqual(self.refused_at([NPC, dict(slots, rows="npc"), share("b")])[0][0], "ops[1].slots")

