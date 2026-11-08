"""The guided-export import (build plan §4.9, §8.3, settled S10): a good export imported and moved under DataPiler's
name; a good export under a misleading file name accepted, a bad one named item.json refused; a wrong container; a
wrong language; a file still growing left for the next poll; a file over the limit refused. Every text is invented."""

import _repo  # noqa: F401

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datapiler import events, inbox, logbook, paths, textdb

EXPORTS = os.path.join(_repo.ROOT, "tests", "fixtures", "text-exports")
CONTAINERS = {"item", "item_dlc01", "item_dlc02"}


class InboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = paths.resolve(Path(self.tmp.name), "workspace", "share")
        paths.ensure(self.p)
        self.db = textdb.TextDB(self.p.textdb)
        self.lang = "engus"
        self.box = inbox.Inbox(lambda: self.p, self.db, lambda: self.lang, lambda: set(CONTAINERS))
        self.events = []
        self.unsub = events.subscribe("inbox.import", lambda t, d: self.events.append(d))

    def tearDown(self):
        self.unsub()
        self.box.stop()
        self.db.close()
        self.tmp.cleanup()

    def drop(self, fixture: str, as_name: str) -> Path:
        dest = self.p.inbox / as_name
        shutil.copyfile(os.path.join(EXPORTS, fixture), dest)
        return dest

    def settle(self) -> list:
        """Two polls: the first sees the file, the second takes it."""
        first = self.box.poll_once()
        return first + self.box.poll_once()

    def test_a_good_export_is_imported_and_moved(self):
        self.drop("item-invented.json", "item-invented.json")
        self.assertEqual(self.box.poll_once(), [])                 # seen once: not taken yet
        done = self.box.poll_once()
        self.assertEqual(len(done), 1)
        self.assertTrue(done[0]["ok"])
        self.assertEqual((done[0]["container"], done[0]["entries"]), ("item", 5))
        self.assertEqual(os.listdir(self.p.inbox), [])
        moved = os.listdir(self.p.imported)
        self.assertEqual(len(moved), 1)
        self.assertRegex(moved[0], r"^\d{8}-\d{6}-item-engus\.json$")
        self.assertTrue(paths.NAME_RX.fullmatch(moved[0][:-5]))
        self.assertEqual(self.db.entries(), 5)
        self.assertEqual(self.events, [{"container": "item", "ok": True, "entries": 5}])
        self.assertEqual(self.box.state(), [])

    def test_an_older_export_without_its_source_container(self):
        self.drop("item-dlc01-older.json", "export.json")
        done = self.settle()
        self.assertEqual([(d["ok"], d["container"]) for d in done], [(True, "item_dlc01")])

    def test_the_same_container_twice_gets_two_names(self):
        self.drop("item-invented.json", "a.json")
        self.drop("item-invented.json", "b.json")
        self.settle()
        self.assertEqual(len(os.listdir(self.p.imported)), 2)
        self.assertEqual(self.db.entries(), 5)

    def test_by_shape_never_by_name(self):
        self.drop("item-invented.json", "menu.json")                 # a misleading name: accepted
        self.drop("not-an-export.json", "item.json")                 # the right name, not an export: refused
        done = {d["file"]: d for d in self.settle()}
        self.assertTrue(done["menu.json"]["ok"])
        self.assertFalse(done["item.json"]["ok"])
        self.assertEqual(self.box.state(), [{"file": "item.json", "reason": "not a Smithbox text export"}])
        self.assertTrue((self.p.inbox / "item.json").exists())       # a refused file stays where it is

    def test_a_wrong_container(self):
        self.drop("menu-invented.json", "export.json")
        self.settle()
        self.assertEqual(self.box.state(), [{"file": "export.json", "reason":
                                             "not a Smithbox text export of `item`, `item_dlc01` or `item_dlc02`"}])
        self.assertEqual(self.db.entries(), 0)

    def test_a_wrong_language(self):
        self.drop("item-language-key.json", "export.json")
        with mock.patch.object(inbox, "LANGUAGE_KEYS", ("InventedLanguage",)):
            self.settle()
        self.assertEqual(self.box.state(), [{"file": "export.json", "reason":
                                             "a text export in another language than Settings' (engus)"}])
        self.lang = "frafr"
        os.utime(self.p.inbox / "export.json")                      # touched: looked at again
        with mock.patch.object(inbox, "LANGUAGE_KEYS", ("InventedLanguage",)):
            self.settle()
        self.assertEqual(self.box.state(), [])
        self.assertTrue(self.db.has("item", "frafr"))

    def test_a_file_still_growing_waits(self):
        f = self.drop("item-invented.json", "export.json")
        data = f.read_bytes()
        f.write_bytes(data[:100])
        self.assertEqual(self.box.poll_once(), [])
        f.write_bytes(data)                                           # it grew since the last poll
        self.assertEqual(self.box.poll_once(), [])
        done = self.box.poll_once()
        self.assertEqual([d["ok"] for d in done], [True])

    def test_a_file_over_the_limit(self):
        f = self.p.inbox / "big.json"
        f.write_bytes(b" " * (1024 * 1024 + 10))
        with mock.patch.object(inbox.Inbox, "MAX_BYTES", 1024 * 1024):
            self.settle()
        self.assertEqual(self.box.state(), [{"file": "big.json",
                                             "reason": "over 1 MB - larger than a text export DataPiler takes"}])

    def test_not_a_json_file(self):
        (self.p.inbox / "notes.txt").write_text("invented")
        self.settle()
        self.assertEqual(self.box.state()[0]["file"], "notes.txt")
        self.assertIn("not a .json file", self.box.state()[0]["reason"])

    def test_a_refused_file_is_not_read_again_until_it_changes(self):
        self.drop("not-an-export.json", "x.json")
        self.settle()
        with mock.patch.object(inbox, "check_export", side_effect=AssertionError("read again")):
            self.box.poll_once()
            self.box.poll_once()
        os.remove(self.p.inbox / "x.json")
        self.box.poll_once()
        self.assertEqual(self.box.state(), [])

    def test_a_file_name_never_reaches_the_log(self):
        planted = "Quillon Marrowgate export.json"
        self.drop("menu-invented.json", planted)
        _, seq = logbook.lines_after(0, limit=0)
        self.settle()
        self.assertEqual(self.box.state()[0]["file"], planted)        # the page shows it
        lines, _ = logbook.lines_after(seq)
        self.assertTrue(lines)
        for x in lines:
            self.assertNotIn("Quillon", x["msg"])
            self.assertNotIn("Brightwater", x["msg"])                 # nor a text of the file

    def test_check_export_directly(self):
        good = {"Name": "item", "FmgWrappers": [{"Name": "W", "ID": 1, "Fmg": {"Entries": [{"ID": 1, "Text": None}]}}]}
        self.assertEqual(inbox.check_export(good, expected={"item"}, language="engus"), ("item", "engus"))
        for bad in (None, [], {"Name": 1, "FmgWrappers": []}, {"Name": "item"},
                    {"Name": "item", "FmgWrappers": [{"ID": "1", "Name": "W", "Fmg": {"Entries": []}}]},
                    {"Name": "item", "FmgWrappers": [{"ID": 1, "Name": "W", "Fmg": {"Entries": [{"ID": 1,
                                                                                              "Text": 5}]}}]}):
            with self.assertRaises(inbox.NotAnExport) as cm:
                inbox.check_export(bad, expected={"item"}, language="engus")
            self.assertEqual(str(cm.exception), "not a Smithbox text export")
        with self.assertRaises(inbox.NotAnExport) as cm:
            inbox.check_export(good, expected={"item"}, language="EN GB")
        self.assertFalse(re.search("EN GB", str(cm.exception)))

    def test_the_thread(self):
        self.drop("item-invented.json", "export.json")
        self.box.start()
        for _ in range(60):
            if os.listdir(self.p.imported):
                break
            threading_sleep(0.1)
        self.box.stop()
        self.assertEqual(len(os.listdir(self.p.imported)), 1)


def threading_sleep(s: float) -> None:
    import threading
    threading.Event().wait(s)


if __name__ == "__main__":
    unittest.main()
