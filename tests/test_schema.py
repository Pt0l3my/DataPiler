"""The job format's JSON Schema (build plan §8.3): it parses, is draft 2020-12, has additionalProperties false on every
object; its op list equals jobs.OPS; each op's properties and required lists equal jobs's argument table; every
fixture agrees. The standard library has no JSON Schema validator, so a small one for the keywords the schema uses is
below; it refuses a keyword it does not know, so the schema cannot quietly grow past it."""

import _repo  # noqa: F401

import json
import os
import re
import unittest

from datapiler import fields, guard, jobs

ROOT = _repo.ROOT
SCHEMA = os.path.join(ROOT, "schema", "datapiler-job-1.schema.json")
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "job-files")

# Bad fixtures the schema refuses too; the others break rules a schema cannot state, which only jobs.check finds.
SCHEMA_CATCHES = {"bad-not-object.json", "bad-too-deep.json", "bad-wrong-format.json", "bad-unknown-key.json",
                  "bad-unknown-op.json", "bad-unknown-argument.json", "bad-field-not-read.json",
                  "bad-unquoted-value.json", "bad-path-name.json", "bad-extract-prefix.json", "bad-load-all.json",
                  "bad-missing-title.json"}
CHECK_ONLY = {"bad-duplicate-key.json", "bad-as-twice.json", "bad-later-table.json", "bad-two-write-share.json",
              "bad-text-local-share.json", "bad-needs-newer.json", "bad-where-type.json", "bad-raw-share.json"}
NOT_JSON = {"bad-not-json.json"}

KNOWN = {"$schema", "$id", "$ref", "$defs", "title", "description", "type", "const", "enum", "pattern", "minLength",
         "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minItems", "maxItems",
         "uniqueItems", "items", "properties", "patternProperties", "additionalProperties", "required",
         "minProperties", "maxProperties", "oneOf", "anyOf", "allOf", "not", "if", "then", "else"}


def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _same(a, b) -> bool:
    if _kind(a) != _kind(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    return a == b


def _is_type(v, t) -> bool:
    if t == "integer":
        return _kind(v) == "number" and float(v).is_integer()
    return _kind(v) == t


def _search(pattern: str, s: str) -> bool:
    # ECMA-262's $ does not match before a final newline; Python's does.
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.search(pattern, s) is not None


class Validator:
    def __init__(self, root: dict):
        self.root = root

    def resolve(self, ref: str) -> dict:
        assert ref.startswith("#/$defs/"), ref
        return self.root["$defs"][ref[len("#/$defs/"):]]

    def valid(self, v, s) -> bool:
        if s is True:
            return True
        if s is False:
            return False
        unknown = set(s) - KNOWN
        if unknown:
            raise AssertionError("a keyword the test's validator does not know: %s" % sorted(unknown))
        if "$ref" in s and not self.valid(v, self.resolve(s["$ref"])):
            return False
        if "type" in s:
            types = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(_is_type(v, t) for t in types):
                return False
        if "const" in s and not _same(v, s["const"]):
            return False
        if "enum" in s and not any(_same(v, e) for e in s["enum"]):
            return False
        if _kind(v) == "string":
            if "pattern" in s and not _search(s["pattern"], v):
                return False
            if len(v) < s.get("minLength", 0) or len(v) > s.get("maxLength", float("inf")):
                return False
        if _kind(v) == "number":
            if "minimum" in s and v < s["minimum"]:
                return False
            if "maximum" in s and v > s["maximum"]:
                return False
            if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
                return False
            if "exclusiveMaximum" in s and v >= s["exclusiveMaximum"]:
                return False
        if _kind(v) == "array":
            if len(v) < s.get("minItems", 0) or len(v) > s.get("maxItems", float("inf")):
                return False
            if s.get("uniqueItems") and any(_same(v[i], v[j]) for i in range(len(v)) for j in range(i)):
                return False
            if "items" in s and not all(self.valid(x, s["items"]) for x in v):
                return False
        if _kind(v) == "object":
            if len(v) < s.get("minProperties", 0) or len(v) > s.get("maxProperties", float("inf")):
                return False
            if any(k not in v for k in s.get("required", [])):
                return False
            props = s.get("properties", {})
            pats = s.get("patternProperties", {})
            for k, x in v.items():
                matched = False
                if k in props:
                    matched = True
                    if not self.valid(x, props[k]):
                        return False
                for p, ps in pats.items():
                    if _search(p, k):
                        matched = True
                        if not self.valid(x, ps):
                            return False
                if not matched and "additionalProperties" in s and not self.valid(x, s["additionalProperties"]):
                    return False
        if "allOf" in s and not all(self.valid(v, x) for x in s["allOf"]):
            return False
        if "anyOf" in s and not any(self.valid(v, x) for x in s["anyOf"]):
            return False
        if "oneOf" in s and sum(1 for x in s["oneOf"] if self.valid(v, x)) != 1:
            return False
        if "not" in s and self.valid(v, s["not"]):
            return False
        if "if" in s:
            if self.valid(v, s["if"]):
                if "then" in s and not self.valid(v, s["then"]):
                    return False
            elif "else" in s and not self.valid(v, s["else"]):
                return False
        return True


def subschemas(s, path="#"):
    if isinstance(s, dict):
        yield path, s
        for k, v in s.items():
            if k in ("properties", "patternProperties", "$defs"):
                for name, sub in v.items():
                    yield from subschemas(sub, "%s/%s/%s" % (path, k, name))
            elif k in ("items", "additionalProperties", "not", "if", "then", "else"):
                yield from subschemas(v, "%s/%s" % (path, k))
            elif k in ("oneOf", "anyOf", "allOf"):
                for i, sub in enumerate(v):
                    yield from subschemas(sub, "%s/%s/%d" % (path, k, i))


class SchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SCHEMA, encoding="utf-8") as f:
            cls.schema = json.load(f)
        cls.v = Validator(cls.schema)

    def test_draft_2020_12(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_additional_properties_false_on_every_object(self):
        objects = 0
        for path, s in subschemas(self.schema):
            if s.get("type") == "object" or ("properties" in s and "type" in s) or "patternProperties" in s:
                objects += 1
                self.assertIs(s.get("additionalProperties"), False, path)
        self.assertGreater(objects, 12)

    def test_the_top_level_keys(self):
        self.assertEqual(set(self.schema["properties"]), set(jobs.TOP_KEYS))
        self.assertEqual(sorted(self.schema["required"]), sorted(k for k, r in jobs.TOP_KEYS.items() if r))
        self.assertEqual(self.schema["properties"]["format"], {"const": jobs.FORMAT})

    def test_the_op_list_is_jobs_ops(self):
        refs = [x["$ref"] for x in self.schema["properties"]["ops"]["items"]["oneOf"]]
        self.assertEqual(refs, ["#/$defs/op_" + o for o in jobs.OPS])
        self.assertEqual(self.schema["properties"]["ops"]["maxItems"], jobs.MAX_OPS)

    def test_each_ops_arguments(self):
        for op in jobs.OPS:
            with self.subTest(op):
                s = self.schema["$defs"]["op_" + op]
                self.assertEqual(s["properties"]["op"], {"const": op})
                self.assertEqual(set(s["properties"]) - {"op"}, set(jobs.ARGS[op]))
                self.assertEqual(sorted(s["required"]), sorted(["op"] + [a for a, r in jobs.ARGS[op].items() if r]))

    def test_the_closed_lists(self):
        fetch = self.schema["$defs"]["op_fetch_rows"]
        self.assertEqual(fetch["properties"]["param"]["enum"], list(fields.PARAMS))
        per_param = {x["if"]["properties"]["param"]["const"]: x["then"]["properties"]["fields"]["items"]["enum"]
                     for x in fetch["allOf"]}
        self.assertEqual(per_param, {p: list(f) for p, f in fields.PARAMS.items()})
        share = self.schema["$defs"]["op_write_share"]
        self.assertEqual(share["properties"]["notes"]["items"]["enum"], list(guard.LABELS))
        self.assertEqual(self.schema["$defs"]["op_join_names"]["properties"]["text"]["enum"], list(jobs.TEXTS))

    def test_every_fixture_agrees(self):
        names = sorted(os.listdir(FIXTURES))
        self.assertEqual({n for n in names if n.startswith("bad-")}, SCHEMA_CATCHES | CHECK_ONLY | NOT_JSON)
        for name in names:
            with open(os.path.join(FIXTURES, name), "rb") as f:
                raw = f.read()
            with self.subTest(name):
                if name in NOT_JSON:
                    with self.assertRaises(ValueError):
                        json.loads(raw)
                    continue
                doc = json.loads(raw)
                check_ok = True
                try:
                    jobs.check(raw, known_ids=(), share_names={})
                except jobs.JobRefused:
                    check_ok = False
                if name.startswith("good-"):
                    self.assertTrue(check_ok)
                    self.assertTrue(self.v.valid(doc, self.schema))
                else:
                    self.assertFalse(check_ok)
                    self.assertEqual(self.v.valid(doc, self.schema), name not in SCHEMA_CATCHES)

    def test_the_built_in_jobs_agree_but_for_their_id(self):
        from datapiler import catalogue
        for r in catalogue.ROWS:
            if "server" not in r.sources:
                continue
            doc = {"format": jobs.FORMAT, "id": "test-builtin-" + r.id.replace("_", "-"), "title": r.name,
                   "ops": catalogue.ops_for(r.id)}
            with self.subTest(r.id):
                self.assertTrue(self.v.valid(doc, self.schema))

    def test_the_validator_refuses_what_it_should(self):
        doc = {"format": jobs.FORMAT, "id": "test-0004-small", "title": "Small", "ops": [
            {"op": "fetch_rows", "as": "t", "param": "TalkParam", "fields": ["msgId"]},
            {"op": "count", "as": "c", "rows": "t", "where": {"msgId": {"ge": 0}}},
            {"op": "write_share", "name": "small", "tables": ["c"], "columns": {"c": ["count"]}}]}
        self.assertTrue(self.v.valid(doc, self.schema))
        for mutate in (lambda d: d["ops"][0].update(fields=["nameId"]),
                       lambda d: d["ops"][1].update(where={"msgId": {"ge": "0"}}),
                       lambda d: d.update(title="two\nlines"),
                       lambda d: d.update(title="x" * 121),
                       lambda d: d["ops"][2].update(columns={"C": ["count"]}),
                       lambda d: d["ops"][0].update(ids={"from": 1, "to": 2, "step": 1})):
            bad = json.loads(json.dumps(doc))
            mutate(bad)
            self.assertFalse(self.v.valid(bad, self.schema))

    def test_filters_explicit_list_of_ids(self):
        doc = {"format": jobs.FORMAT, "id": "test-0006-pick", "title": "Pick", "ops": [
            {"op": "fetch_rows", "as": "t", "param": "TalkParam", "fields": ["msgId"]},
            {"op": "filter", "as": "p", "rows": "t", "ids": [9000001, 9000002]},
            {"op": "write_share", "name": "picked", "tables": ["p"], "columns": {"p": ["id", "msgId"]}}]}
        self.assertTrue(self.v.valid(doc, self.schema))
        jobs.check(json.dumps(doc).encode(), known_ids=(), share_names={})
        for mutate in (lambda d: d["ops"][1].pop("ids"),                         # neither where nor ids
                       lambda d: d["ops"][1].update(ids=[]),
                       lambda d: d["ops"][1].update(ids=[1.5]),
                       lambda d: d["ops"][1].update(ids=list(range(1001))),
                       lambda d: d["ops"][1].update(ids=[2 ** 31]),
                       lambda d: (d["ops"][1].pop("ids"), d["ops"][1].update(key="id", where={"msgId": 1}))):
            bad = json.loads(json.dumps(doc))
            mutate(bad)
            with self.subTest(op=bad["ops"][1]):
                self.assertFalse(self.v.valid(bad, self.schema))
                with self.assertRaises(jobs.JobRefused):
                    jobs.check(json.dumps(bad).encode(), known_ids=(), share_names={})

    def test_names_windows_keeps_for_devices_are_refused(self):
        doc = {"format": jobs.FORMAT, "id": "test-0005-names", "title": "Names", "ops": [
            {"op": "fetch_rows", "as": "t", "param": "TalkParam", "fields": ["msgId"]},
            {"op": "count", "as": "c", "rows": "t"},
            {"op": "write_local", "name": "here", "tables": ["c"]},
            {"op": "write_share", "name": "small", "tables": ["c"], "columns": {"c": ["count"]}}]}
        self.assertTrue(self.v.valid(doc, self.schema))
        for name in ("con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt0"):
            for where in ("id", "local", "share"):
                with self.subTest(name=name, where=where):
                    bad = json.loads(json.dumps(doc))
                    if where == "id":
                        bad["id"] = name
                    else:
                        bad["ops"][2 if where == "local" else 3]["name"] = name
                    self.assertFalse(self.v.valid(bad, self.schema))
        for name in ("console", "con-1", "nul0", "com10", "lpt-1"):
            with self.subTest(name=name):
                good = json.loads(json.dumps(doc))
                good["id"] = name
                good["ops"][3]["name"] = name
                self.assertTrue(self.v.valid(good, self.schema))


if __name__ == "__main__":
    unittest.main()
