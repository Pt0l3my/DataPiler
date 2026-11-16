"""The guard's form for a derivation report (DP36, settled S98; derive.py): EldenNet's derive.json, shared as the devkit
tool wrote it. Reports are built in code from an invented one, never kept as fixture files: a good one passes all six
checks with the leads' labels kept for it; each check fails with its place, never the value; a file without its
record fails checks 2 and 6; record_counts, labels_for and put_counts keep the labels; the leads' labels are read
from an invented leads file. Every name, label and number is invented."""

import _repo  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datapiler import derive, guard, textdb

PLANTED_USER = "velkorquist"
TEXTS = ["Quillon Marrowgate", "Vellmoor"]
LABELS = frozenset({"loom_keeper", "ember_desk", "vault_warden", "kin_set", "module_base", "ledger_slot"})
PATTERN = "48 8B 1D ?? ?? ?? ?? 48 85 DB 75 21 48 8D 0D ?? ?? ?? ?? E8 ?? ?? ?? ??"

LEADS = """# invented leads, in the shape of EldenNet's gal/leads.toml
schema = 1
product_name = "Invented Game"

[fd4]
path_suffix = "Invented.h"

[singletons]                      # label = name
loom_keeper = "LoomKeeper"
"ember_desk" = "EmberDesk"   # a quoted key
vault_warden = "VaultWarden"

[register]
instance = "loom_keeper"

[task]
group = "Invented_Group"
base = "IV::TaskBase"

[vtable_sets]
kin_set = "IV::Kin"

[statics]
module_base = { module = true }

[statics.ledger_slot]
rtti = "IV::LedgerImp"
"""


def report() -> dict:
    """An invented report in schema 1's vocabulary, every kind of value in it."""
    return {
        "report": "derive", "schema": 1, "complete": False,
        "image": {"file_size": 4096000, "image_base": 5368709120, "time_date_stamp": 1700000000,
                  "file_version": [9, 8, 7, 0], "region": "ww", "product_name": "matches",
                  "sections": [{"section": ".text", "rva": 4096, "virtual_size": 8192, "raw_size": 8192},
                               {"section": "other", "rva": 12288, "virtual_size": 512, "raw_size": 512}]},
        "fd4": {"status": "derived", "path_strings": 3,
                "idiom": {"bytes": PATTERN, "length": 24, "fixed": 12, "hits": 9,
                          "captures": [{"capture": "static", "at": 3, "insn_end": 7}]},
                "names": {"offset": 24, "encoding": "ascii"},
                "refused": {"unreadable": 0, "path_text": 1},
                "singletons": [{"label": "loom_keeper", "status": "derived", "static": 70000, "class": 70100},
                               {"label": "ember_desk", "status": "missing"}]},
        "rtti": {"locators": 120, "sets": [{"label": "kin_set", "status": "derived", "primary": [9000, 9100]}],
                 "task": {"status": "missing", "vtables": []}},
        "register": {"status": "depends", "candidates": [
            {"callee": 4200, "instance_register": "rcx", "shaped": True,
             "pattern": {"bytes": "44 89 C7 48 8B 05 ?? ?? ?? ?? 48 39 F0 75 ??", "hit": 4300, "anchor": 9}}]},
        "group": {"status": "missing", "strings": 0},
        "statics": [{"label": "module_base", "kind": "module", "status": "needs_slot"},
                    {"label": "ledger_slot", "kind": "class", "rtti_status": "derived", "vtable": 9300}],
        "confirm": [{"item": "name_layout", "value": 24}, {"item": "task_run_slot"},
                    {"item": "singleton_instance", "label": "loom_keeper", "value": 70000}],
        "stats": {"instructions": 1234567, "undecodable": 0},
    }


def raw(doc: dict) -> bytes:
    return json.dumps(doc, indent=1).encode("ascii")


class DeriveGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.share = root / "share"
        self.share.mkdir()
        self.counts = root / "work" / "share-counts.json"
        self.sets = mock.patch.dict(textdb.TEXT_SETS, {"character_names": (("item", 9001),),
                                                       "place_names": (("item", 9002),)})
        self.sets.start()
        self.db = textdb.TextDB(root / "work" / "textdb.sqlite")
        self.db.import_export({"Name": "item", "FmgWrappers": [{"Name": "Invented", "ID": 9001, "Fmg": {
            "Entries": [{"ID": 9000000 + i, "Text": t} for i, t in enumerate(TEXTS)]}}]},
            container="item", language="engus", sha256="0" * 64)
        self.guard = guard.Guard(self.db, lambda: [PLANTED_USER])

    def tearDown(self):
        self.guard.close()
        self.db.close()
        self.sets.stop()
        self.tmp.cleanup()

    def results(self, data: bytes, labels=LABELS) -> dict:
        return {r.check: (r.ok, r.where) for r in self.guard.check(data, declared={}, coverage={}, labels=labels)}

    def failed(self, data: bytes, labels=LABELS) -> dict:
        return {n: w for n, (ok, w) in self.results(data, labels).items() if not ok}

    def test_s98_a_good_report_passes_all_six(self):
        self.assertEqual(self.failed(raw(report())), {})

    def test_s98_without_its_record_checks_2_and_6_fail(self):
        got = self.failed(raw(report()), labels=None)
        self.assertEqual(sorted(got), [2, 6])
        self.assertTrue(got[2].endswith(".label"))
        self.assertEqual(got[6], guard.NO_COUNTS)

    def test_s98_a_label_not_of_the_leads_fails_check_2(self):
        doc = report()
        doc["fd4"]["singletons"][1]["label"] = "stray_label"
        self.assertEqual(self.failed(raw(doc)), {2: "fd4.singletons[1].label"})
        # not one of the leads' labels, so read as any string: a name of the text database fails check 3 too
        doc["fd4"]["singletons"][1]["label"] = "quillon_marrowgate"
        self.assertEqual(self.failed(raw(doc)), {2: "fd4.singletons[1].label", 3: "fd4.singletons[1].label"})

    def test_s98_report_and_schema_come_first(self):
        doc = report()
        moved = {"schema": 1, "report": "derive"}
        moved.update({k: v for k, v in doc.items() if k not in moved})
        self.assertEqual(self.failed(raw(moved))[1], "(top level)")      # read as a share file of DataPiler's
        doc = report()
        doc["schema"] = 2
        self.assertEqual(self.failed(raw(doc)), {1: "schema"})

    def test_s98_a_key_given_twice_fails_check_1(self):
        text = raw(report()).decode("ascii").replace('"complete": false', '"complete": false, "complete": true', 1)
        self.assertEqual(self.failed(text.encode("ascii")), {1: "(top level)"})

    def test_s98_an_unknown_key_with_a_path_and_a_name(self):
        doc = report()
        doc["image"]["file_path"] = "C:\\Users\\%s\\Game\\invented.exe" % PLANTED_USER
        doc["fd4"]["note"] = "Quillon Marrowgate"
        got = self.failed(raw(doc))
        self.assertEqual(got[1], "image.file_path")
        self.assertEqual(got[3], "fd4.note")
        self.assertEqual(got[4], "image.file_path")
        for where in got.values():
            self.assertNotIn("Users", where)
            self.assertNotIn("Quillon", where)

    def test_s98_values_of_the_wrong_type_fail_check_2(self):
        for path, value in ((("image", "region"), "atlantis"), (("image", "file_size"), 1.5),
                            (("image", "file_size"), -1), (("image", "file_size"), None), (("image", "file_size"), True),
                            (("complete",), 1), (("image", "file_size"), 2 ** 64), (("fd4", "status"), "Derived")):
            with self.subTest(path=path, value=value):
                doc = report()
                target = doc
                for k in path[:-1]:
                    target = target[k]
                target[path[-1]] = value
                self.assertEqual(self.failed(raw(doc)), {2: ".".join(path)})

    def test_s98_a_number_list_holds_numbers_only(self):
        doc = report()
        doc["image"]["file_version"] = [9, "8", 7]
        self.assertEqual(self.failed(raw(doc)), {2: "image.file_version[1]"})

    def test_s98_patterns_in_canonical_form_of_at_most_64_bytes(self):
        long = " ".join(["48"] * 65)
        text = " ".join("%02X" % b for b in b"Quillon Marrowgate")
        utf16 = " ".join("%02X" % b for b in "Vellmoor".encode("utf-16-le"))
        for bad in (long, PATTERN.lower(), "48 8B ?? ??", "48  8B 1D 05 06", "48 8B 1D 05 0", "4? 8B 1D 05 06",
                    text, utf16, "", 4096):
            with self.subTest(bad=bad if not isinstance(bad, str) or len(bad) < 40 else bad[:40]):
                doc = report()
                doc["fd4"]["idiom"]["bytes"] = bad
                self.assertEqual(self.failed(raw(doc)), {2: "fd4.idiom.bytes"})
        doc = report()
        doc["fd4"]["idiom"]["bytes"] = " ".join(["48", "8B"] * 32)
        self.assertEqual(self.failed(raw(doc)), {})
        self.assertFalse(derive.reads_as_text([0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41]))   # seven in a row: code

    def test_s98_an_owner_word_in_a_label_fails_check_4(self):
        doc = report()
        doc["confirm"][2]["label"] = PLANTED_USER + "_slot"
        self.assertEqual(self.failed(raw(doc), labels=LABELS | {PLANTED_USER + "_slot"}),
                         {4: "confirm[2].label"})

    def test_s98_a_pattern_is_not_read_for_the_owner_s_words(self):
        doc = report()
        doc["fd4"]["idiom"]["bytes"] = "48 8B ED ?? ?? ?? ?? 48 85 DB"
        self.assertEqual(self.failed(raw(doc)), {})
        with mock.patch.object(self.guard, "_owner_words", lambda: ["ed"]):
            self.assertEqual(self.failed(raw(doc)), {})

    def test_s98_size_limits(self):
        doc = report()
        doc["statics"] = [{"pattern": {"bytes": PATTERN}} for _ in range(derive.MAX_PATTERNS + 1)]
        self.assertEqual(self.failed(raw(doc)), {5: "(file)"})
        doc = report()
        doc["stats"]["instructions"] = 7
        big = raw(doc).replace(b'"instructions": 7', b'"instructions": 7' + b" " * derive.MAX_BYTES)
        self.assertEqual(self.failed(big), {5: "(file)"})

    def test_s98_too_deep(self):
        doc = report()
        inner: dict = {"value": 1}
        for _ in range(derive.MAX_DEPTH + 2):
            inner = {"pattern": inner}
        doc["fd4"]["idiom"] = inner
        self.assertIn(1, self.failed(raw(doc)))

    def test_s98_write_and_the_record(self):
        data = raw(report())
        written = self.guard.write(self.share, "derive-r0", data, declared={}, coverage={}, labels=LABELS)
        self.assertEqual((self.share / "derive-r0.json").read_bytes(), data)
        guard.record_counts(self.counts, written.name, written.sha256, {}, LABELS)
        self.assertEqual(guard.labels_for(self.counts, written.name, written.sha256), LABELS)
        self.assertEqual(guard.counts_for(self.counts, written.name, written.sha256), {})
        self.assertIsNone(guard.labels_for(self.counts, written.name, "ef" * 32))
        entry = guard.counts_entry(self.counts, written.name)
        guard.forget_counts(self.counts, written.name)
        self.assertIsNone(guard.labels_for(self.counts, written.name, written.sha256))
        guard.put_counts(self.counts, written.name, entry)
        self.assertEqual(guard.labels_for(self.counts, written.name, written.sha256), LABELS)
        with self.assertRaises(ValueError):
            guard.record_counts(self.counts, written.name, written.sha256, {}, ["Not A Label"])

    def test_s98_write_refuses_and_writes_nothing(self):
        doc = report()
        doc["fd4"]["note"] = "anything"
        with self.assertRaises(guard.GuardFailed) as cm:
            self.guard.write(self.share, "derive-r0", raw(doc), declared={}, coverage={}, labels=LABELS)
        self.assertEqual(cm.exception.check, 1)
        self.assertEqual(list(self.share.iterdir()), [])

    def test_s98_a_share_file_of_datapiler_s_own_is_not_a_report(self):
        self.assertFalse(derive.is_report({"format": guard.SHARE_FORMAT, "report": "derive"}))
        self.assertTrue(derive.is_report(report()))

    def test_s98_the_leads_labels(self):
        self.assertEqual(derive.leads_labels(LEADS), LABELS)
        self.assertEqual(derive.leads_labels("[singletons]\n# none\n"), frozenset())
        self.assertEqual(derive.leads_labels("[task]\nbase = \"IV::X\"\n[fd4]\npath_suffix = \"x\"\n"), frozenset())
        # a table this reader does not know adds no label: what it misses fails check 2 (it fails closed)
        self.assertEqual(derive.leads_labels("[[statics]]\nodd = 1\n"), frozenset())


if __name__ == "__main__":
    unittest.main()
