"""The job check (build plan §4.6, §8.3): the design's example passes; each refusal from a fixture, with its exact
text; a value that is not identifier-shaped is never quoted."""

import _repo  # noqa: F401

import json
import os
import unittest

from datapiler import jobs

FIXTURES = os.path.join(_repo.ROOT, "tests", "fixtures", "job-files")
PLANTED = "Quillon Marrowgate"
OPS_LIST = "fetch_rows, load_maps, read_placements, join_names, filter, count, distinct, write_local, write_share"

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
    "bad-text-local-share.json": ("ops[3].columns.npc_named[1]", "`name` holds local text (the names) and never goes "
                                                                 "into a share file"),
    "bad-needs-newer.json": ("needs", "this job needs DataPiler 0.2 or newer; this is 0.1.0"),
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
        for needs, ok in (("0.1", True), ("0.1.0", True), ("0.0.9", True), ("0.1.1", False), ("1.0", False)):
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
