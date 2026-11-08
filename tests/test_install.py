"""datapiler/install.py (build plan 0.2 §4.5, §7.1): update/pending.json read back with every field checked and a
bad file removed, the install check, the clean-up that removes only what it names, and update/result.json read by
its nonce. Every folder is a temporary one; every version and file is invented."""

import _repo  # noqa: F401

import json
import os
import tempfile
import unittest
from pathlib import Path

from datapiler import install, logbook
from test_archive import helper, manifest_of


def lines_since(seq):
    got, _ = logbook.lines_after(seq, limit=100)
    return [l["level"] + " " + l["src"] + " " + l["msg"] for l in got]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def seq(self):
        return logbook.lines_after(0, limit=0)[1]


class PendingFile(Base):
    def write(self, **kw):
        args = dict(from_version="0.2.0", to_version="0.3.0", zip_rel="update/0.3.0/DataPiler-0.3.0.zip",
                    zip_sha256="ab" * 32, zip_size=1234, port=22777)
        args.update(kw)
        return install.write_pending(self.root, **args)

    def doc(self):
        return json.loads((self.root / install.PENDING).read_text())

    def put(self, doc):
        (self.root / install.PENDING).write_text(json.dumps(doc))

    def test_written_and_read_back(self):
        p = self.write()
        self.assertRegex(p.nonce, r"^[0-9a-f]{32}$")
        doc = self.doc()
        self.assertEqual(doc["format"], "datapiler-update-pending/1")
        self.assertEqual((doc["from"], doc["to"], doc["zip"], doc["port"]), ("0.2.0", "0.3.0",
                                                                            "update/0.3.0/DataPiler-0.3.0.zip", 22777))
        self.assertEqual(doc["root"], helper().root_id(self.root))
        self.assertNotIn(self.tmp.name, (self.root / install.PENDING).read_text())
        self.assertEqual(install.read_pending(self.root), p)

    def test_any_age(self):
        self.write()
        doc = self.doc()
        doc["at"] = 1_000_000
        self.put(doc)
        self.assertEqual(install.read_pending(self.root).at, 1_000_000)

    def test_none_without_a_file(self):
        self.assertIsNone(install.read_pending(self.root))

    def test_write_refuses_a_field_out_of_its_pattern(self):
        for kw in ({"to_version": "0.3"}, {"zip_rel": "../x.zip"}, {"zip_sha256": "x"}, {"port": 70000},
                   {"zip_size": 0}):
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    self.write(**kw)

    def test_a_bad_file_is_removed_with_a_warning_naming_the_field(self):
        cases = {"format": {"format": "other/1"}, "root": {"root": "0" * 64}, "port": {"port": "22777"},
                 "to": {"to": "0.3"}, "zip": {"zip": "update/0.3.0/../../x.zip"}, "nonce": {"nonce": "x"},
                 "zip_sha256": {"zip_sha256": "AB" * 32}, "from": {"from": 2}}
        for field, change in cases.items():
            with self.subTest(field=field):
                self.write()
                doc = dict(self.doc(), **change)
                self.put(doc)
                seq = self.seq()
                self.assertIsNone(install.read_pending(self.root))
                self.assertFalse((self.root / install.PENDING).exists())
                said = lines_since(seq)
                self.assertTrue(any(l.startswith("WARN update update/pending.json is not as DataPiler writes it (%s)"
                                                 % field) for l in said), said)

    def test_not_json(self):
        (self.root / "update").mkdir()
        (self.root / install.PENDING).write_bytes(b"\xff not json")
        self.assertIsNone(install.read_pending(self.root))
        self.assertFalse((self.root / install.PENDING).exists())


class InstallCheck(Base):
    def setUp(self):
        super().setUp()
        self.files = {"a.py": b"a\n", "d/b.py": b"b\n", "c.txt": b"c\n"}
        for rel, data in self.files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.root / "manifest.sha256").write_bytes(manifest_of(self.files))

    def test_all_match(self):
        c = install.install_check(self.root)
        self.assertEqual((c.manifest, c.files, c.differ, c.missing), (True, 3, (), ()))
        seq = self.seq()
        install.check_line(c)
        self.assertEqual(lines_since(seq), ["INFO update install check: all 3 files match the release"])

    def test_files_differing_are_named(self):
        (self.root / "d" / "b.py").write_bytes(b"edited\n")
        os.remove(self.root / "c.txt")
        c = install.install_check(self.root)
        self.assertEqual((c.differ, c.missing), (("d/b.py",), ("c.txt",)))
        self.assertIsInstance(c.differ[0], logbook.Own)
        seq = self.seq()
        install.check_line(c)
        self.assertEqual(lines_since(seq), ["WARN update install check: 2 files differ from the release: d/b.py, "
                                            "c.txt"])
        # never a repair
        self.assertEqual((self.root / "d" / "b.py").read_bytes(), b"edited\n")

    def test_no_manifest(self):
        os.remove(self.root / "manifest.sha256")
        c = install.install_check(self.root)
        self.assertFalse(c.manifest)
        seq = self.seq()
        install.check_line(c)
        self.assertEqual(lines_since(seq), ["INFO update install check: no manifest.sha256 - a copy from the "
                                            "repository, not a release"])

    def test_a_manifest_naming_a_path_outside(self):
        (self.root / "manifest.sha256").write_bytes(("%s  ../outside.txt\n" % ("0" * 64)).encode())
        c = install.install_check(self.root)
        self.assertEqual(c.differ, ("manifest.sha256",))


class Cleanup(Base):
    def test_removes_only_what_it_names(self):
        u = self.root / "update"
        (u / "0.3.0").mkdir(parents=True)
        (u / "0.3.0" / "DataPiler-0.3.0.zip").write_bytes(b"zip")
        (u / "0.3.0" / "update-helper.py").write_bytes(b"helper")
        (u / "0.4.0").mkdir()
        (u / "0.4.0" / "DataPiler-0.4.0.zip.part").write_bytes(b"part")
        (u / "stray.part").write_bytes(b"part")
        for keep in ("pending.json", "result.json", "notes.txt"):
            (u / keep).write_text("{}")
        (u / "not-a-version").mkdir()
        b = u / "backup-0.2.0"
        (b / "files").mkdir(parents=True)
        (b / "backup.json").write_text(json.dumps({
            "format": "datapiler-update-backup/1", "from": "0.2.0", "to": "0.3.0", "nonce": "1" * 32,
            "complete": True, "files": [], "added": [], "dirs": [], "aside": ["DataPiler.exe.old", "README.md"],
            "manifest": True}))
        (self.root / "DataPiler.exe.old").write_bytes(b"old exe")
        (self.root / "README.md").write_bytes(b"read me")
        (self.root / "other.old").write_bytes(b"not listed")
        outside = self.root.parent / "x.old"
        install.cleanup(self.root)
        self.assertFalse((u / "0.3.0").exists())
        self.assertFalse((u / "0.4.0").exists())
        self.assertFalse((u / "stray.part").exists())
        self.assertFalse((self.root / "DataPiler.exe.old").exists())
        for kept in (u / "pending.json", u / "result.json", u / "notes.txt", u / "not-a-version", b / "backup.json",
                     self.root / "README.md", self.root / "other.old"):
            self.assertTrue(kept.exists(), kept.name)
        self.assertFalse(outside.exists())

    def test_a_backup_json_naming_a_path_outside_is_not_followed(self):
        b = self.root / "update" / "backup-0.2.0"
        b.mkdir(parents=True)
        (b / "backup.json").write_text(json.dumps({
            "format": "datapiler-update-backup/1", "from": "0.2.0", "to": "0.3.0", "nonce": "1" * 32,
            "complete": True, "files": [], "added": [], "dirs": [], "aside": ["../x.old", "a.old"]}))
        (self.root / "a.old").write_bytes(b"x")
        install.cleanup(self.root)
        self.assertTrue((self.root / "a.old").exists())

    def test_nothing_to_do(self):
        install.cleanup(self.root)
        self.assertEqual(list(self.root.iterdir()), [])


class Result(Base):
    def put(self, **kw):
        doc = {"format": "datapiler-update-result/1", "nonce": "a" * 32, "state": "updated", "from": "0.2.0",
               "to": "0.3.0", "stage": "done", "text": None, "backup": "update/backup-0.2.0", "restored": None,
               "counts": {"written": 41, "added": 6, "removed": 2, "same": 12, "files": 61}}
        doc.update(kw)
        (self.root / "update").mkdir(exist_ok=True)
        (self.root / install.RESULT).write_text(json.dumps(doc))

    def test_read_by_its_nonce(self):
        self.put()
        r = install.read_result(self.root, "a" * 32)
        self.assertEqual(r, {"state": "updated", "from": "0.2.0", "to": "0.3.0", "stage": "done", "text": None,
                             "counts": {"written": 41, "added": 6, "removed": 2, "same": 12, "files": 61},
                             "backup": "update\\backup-0.2.0", "restored": None, "log": "logs\\update.log"})
        self.assertIsNone(install.read_result(self.root, "b" * 32))
        self.assertIsNone(install.read_result(self.root, "not a nonce"))

    def test_fields_checked_and_the_text_masked_and_cut(self):
        home = str(self.root / "Users" / "someone")
        logbook.set_masks(folders={}, home=home, user=None, pc=None)
        try:
            self.put(state="failed", stage="write", text="in " + home + "\\x " + "y" * 400,
                     backup="C:\\elsewhere", counts={"written": "41", "added": -1}, **{"from": "../x"})
            r = install.read_result(self.root, "a" * 32)
        finally:
            logbook.set_masks(folders={}, home=None, user=None, pc=None)
        self.assertEqual(r["state"], "failed")
        self.assertNotIn(home, r["text"])
        self.assertIn("<HOME>", r["text"])
        self.assertEqual(len(r["text"]), 300)
        self.assertIsNone(r["backup"])
        self.assertIsNone(r["from"])
        self.assertEqual(r["counts"], {})

    def test_an_unknown_state(self):
        self.put(state="installed")
        self.assertIsNone(install.read_result(self.root, "a" * 32))


if __name__ == "__main__":
    unittest.main()
