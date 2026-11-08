"""Smithbox's record of its projects (build plan 0.2 §5.3, §7.2; smithbox-projects.md §6), on invented records in
its §3 shape, in a temporary Local AppData. Everything read is a lead (O48)."""

import _repo  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datapiler import fileio, sbproject

FIX = Path(_repo.ROOT) / "tests" / "fixtures" / "smithbox"


def record(**kw):
    doc = json.loads((FIX / "record-2.2.6.json").read_text(encoding="utf-8"))
    doc.update(kw)
    for k in [k for k, v in kw.items() if v is KeyError]:
        doc.pop(k)
    return doc


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name) / "LocalAppData"
        self.projects = self.local / "Smithbox" / "Projects"
        self.projects.mkdir(parents=True)
        self.config = self.local / "Smithbox" / "Configuration"
        self.config.mkdir()
        (self.config / "Configuration.json").write_text('{"Invented": "never read"}', encoding="utf-8")
        self.pauses = []

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, doc, raw=None):
        data = raw if raw is not None else json.dumps(doc, indent=2).encode("utf-8")
        (self.projects / name).write_bytes(data)

    def read(self, **kw):
        return sbproject.read(str(self.local), pause=self.pauses.append, **kw)

    def test_the_2_2_6_shape(self):
        self.put("00000000-0000-4000-8000-000000000001.json", None,
                 (FIX / "record-2.2.6.json").read_bytes())
        r = self.read()
        self.assertTrue(r.found)
        self.assertEqual(r.leads, (sbproject.ProjectLead(
            "Example project", "C:\\Mods\\ExampleProject",
            "C:\\Games\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game", True),))
        self.assertEqual((r.other_games, r.unrecognised, r.why), (0, 0, None))
        self.assertEqual(r.open_lead(), r.leads[0])

    def test_the_default_branchs_shape_and_another_game(self):
        self.put("a.json", None, (FIX / "record-default-branch.json").read_bytes())
        self.put("b.json", None, (FIX / "record-other-game.json").read_bytes())
        r = self.read()
        self.assertEqual([x.name for x in r.leads], ["Another example"])
        self.assertEqual((r.other_games, r.unrecognised), (1, 0))
        self.assertIsNone(r.open_lead())                       # none marked

    def test_two_marks_and_none(self):
        self.put("a.json", record(ProjectName="One"))
        self.put("b.json", record(ProjectName="Two", ProjectPath="C:\\Mods\\Two"))
        r = self.read()
        self.assertEqual(len(r.leads), 2)
        self.assertIsNone(r.open_lead())                       # two marked: no "open" tag
        self.put("b.json", record(ProjectName="Two", AutoSelect=False))
        self.assertEqual(self.read().open_lead().name, "One")
        self.put("a.json", record(AutoSelect=KeyError))        # absent counts as not marked
        r = self.read()
        self.assertEqual(len(r.leads), 2)
        self.assertIsNone(r.open_lead())

    def test_project_types(self):
        cases = ((8, "lead"), ("ER", "lead"), (15, "other"), (True, "bad"), (8.0, "bad"), (None, "bad"))
        for value, want in cases:
            with self.subTest(value=value):
                self.put("a.json", record(ProjectType=value))
                r = self.read()
                got = "lead" if r.leads else "other" if r.other_games else "bad"
                self.assertEqual(got, want)

    def test_missing_keys_and_wrong_types(self):
        for change in ({"ProjectPath": KeyError}, {"DataPath": KeyError}, {"ProjectName": KeyError},
                       {"ProjectType": KeyError}, {"ProjectPath": 5}, {"AutoSelect": "yes"}):
            with self.subTest(change=change):
                self.put("a.json", record(**change))
                r = self.read()
                self.assertEqual((r.leads, r.unrecognised), ((), 1))
                self.assertIn("does not recognise (1 file)", r.why)

    def test_a_non_object(self):
        self.put("a.json", ["not", "an", "object"])
        self.put("b.json", "text")
        r = self.read()
        self.assertEqual((r.leads, r.unrecognised), ((), 2))
        self.assertEqual(r.why, "Smithbox's project record is in a form this DataPiler does not recognise (2 files)")

    def test_invalid_json_recovered_on_the_second_read(self):
        self.put("a.json", None, b'{"ProjectName": "half-writ')
        good = json.dumps(record()).encode("utf-8")

        def pause(secs):
            self.pauses.append(secs)
            self.put("a.json", None, good)                     # the write that was under way ends

        r = sbproject.read(str(self.local), pause=pause)
        self.assertEqual(self.pauses, [sbproject.RETRY_SECS])
        self.assertEqual(len(r.leads), 1)

    def test_invalid_json_not_recovered(self):
        self.put("a.json", None, b"{broken")
        self.put("b.json", None, b"{broken too")
        r = self.read()
        self.assertEqual(self.pauses, [0.5])                   # one wait for all of them
        self.assertEqual((r.leads, r.unrecognised), ((), 2))
        self.put("c.json", record())
        r = self.read()
        self.assertEqual((len(r.leads), r.unrecognised, r.why), (1, 2, None))

    def test_a_bom(self):
        self.put("a.json", None, b"\xef\xbb\xbf" + json.dumps(record()).encode("utf-8"))
        self.assertEqual(len(self.read().leads), 1)

    def test_an_oversize_file_and_too_many_files_read_none(self):
        self.put("a.json", record())
        self.put("big.json", None, b" " * (sbproject.FILE_MAX + 1))
        r = self.read()
        self.assertEqual((r.leads, r.unrecognised), ((), 2))
        self.assertIn("over 1 MiB", r.why)
        (self.projects / "big.json").unlink()
        for i in range(sbproject.FILES_MAX):
            self.put("p%02d.json" % i, record())
        r = self.read()
        self.assertEqual((r.leads, r.unrecognised), ((), sbproject.FILES_MAX + 1))
        self.assertIn("more than 64 files", r.why)

    def test_paths_must_be_drive_paths(self):
        for bad in ("\\\\server\\share\\Mods", "//server/share/Mods", "\\\\?\\C:\\Mods", "Mods\\Relative",
                    "C:Mods", "C:\\Mods\x00x", ""):
            with self.subTest(bad=bad):
                self.put("a.json", record(ProjectPath=bad))
                r = self.read(posix_ok=False)
                self.assertEqual((r.leads, r.unrecognised), ((), 1))
                self.put("a.json", record(DataPath=bad))
                self.assertEqual(self.read(posix_ok=False).leads, ())
        self.put("a.json", record(ProjectPath="/mods/example", DataPath="/games/Game"))
        self.assertEqual(self.read(posix_ok=False).leads, ())
        self.assertEqual(len(self.read(posix_ok=True).leads), 1)    # off Windows only

    def test_no_folder(self):
        for local in (None, "", str(Path(self.tmp.name) / "nowhere")):
            with self.subTest(local=local):
                r = sbproject.read(local, pause=self.pauses.append)
                self.assertEqual((r.found, r.leads, r.why), (False, (), sbproject.NOT_FOUND))
        r = self.read()                                        # the folder, empty
        self.assertEqual((r.found, r.leads, r.why), (True, (), sbproject.NOT_FOUND))

    def test_only_json_directly_in_the_folder(self):
        self.put("a.json", record())
        (self.projects / "notes.txt").write_text("not read", encoding="utf-8")
        (self.projects / "sub").mkdir()
        (self.projects / "sub" / "deeper.json").write_text(json.dumps(record()), encoding="utf-8")
        self.assertEqual(len(self.read().leads), 1)

    def test_read_only_and_never_configuration_json(self):
        self.put("a.json", record())
        self.put("b.json", None, b"{broken")
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.local.rglob("*") if p.is_file()}
        opened = []
        real_open = open

        def spy(file, mode="r", *a, **kw):
            opened.append((str(file), mode))
            return real_open(file, mode, *a, **kw)

        with mock.patch("builtins.open", spy):
            self.read()
        self.assertTrue(opened)
        self.assertTrue(all(m == "rb" for _, m in opened), opened)
        self.assertFalse(any("Configuration" in f for f, _ in opened))
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.local.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(sorted(p.name for p in self.projects.iterdir()), ["a.json", "b.json"])

    def test_never_an_exception(self):
        with mock.patch.object(fileio, "read_limited", side_effect=RuntimeError("unexpected")):
            self.put("a.json", record())
            r = self.read()
        self.assertEqual((r.found, r.leads), (False, ()))

    def test_the_name_is_kept_short_and_plain(self):
        self.put("a.json", record(ProjectName="Line\nbreak " + "x" * 300))
        name = self.read().leads[0].name
        self.assertNotIn("\n", name)
        self.assertLessEqual(len(name), sbproject.NAME_MAX)

    def test_cached_reads_again_when_a_file_changes(self):
        self.put("a.json", record())
        sbproject.forget()
        first = sbproject.cached(str(self.local))
        with mock.patch.object(sbproject, "read", side_effect=AssertionError("read again")):
            self.assertIs(sbproject.cached(str(self.local)), first)
        self.put("b.json", record(ProjectName="Two", AutoSelect=False))
        self.assertEqual(len(sbproject.cached(str(self.local)).leads), 2)
        sbproject.forget()


if __name__ == "__main__":
    unittest.main()
