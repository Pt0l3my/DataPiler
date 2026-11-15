"""DP22 (settled S70): the Deleted bin. Every removal moves what it removes into the bin and never erases it; Restore
puts it back exactly, an import of the text database included, and refuses while something of the same name is in the
way; Erase and Empty bin, and every removal of collected data, need DELETE typed in, which the API checks, and a job
needs its pop-up's confirmation. Every name, number and text is invented."""

import _repo  # noqa: F401

import errno
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from datapiler import deleted, events, fileio, guard, logbook, paths, runner, textdb, winapi
from datapiler.api import Api, Live
from datapiler.game import GameRunning
from datapiler.server import Bad
from datapiler.settings import Session, Settings
from datapiler.status import Status

import test_api as ta
import test_runner as tr

EXPORT = os.path.join(_repo.ROOT, "tests", "fixtures", "text-exports", "item-invented.json")
SETS = {"character_names": (("item", 9001),), "place_names": (("item", 9002),)}
MAPS = ["m99_00_00_%02d" % i for i in range(5)]


def tree(folder: Path) -> dict:
    """Every file under folder, by its place relative to it, with its bytes."""
    folder = Path(folder)
    return {f.relative_to(folder).as_posix(): f.read_bytes() for f in sorted(folder.rglob("*")) if f.is_file()}


def export() -> dict:
    with open(EXPORT, encoding="utf-8") as f:
        return json.load(f)


def map_doc(jid: str = "en-0902-bin-maps") -> bytes:
    return json.dumps({"format": "datapiler-job/1", "id": jid, "title": "Kept maps", "ops": [
        {"op": "load_maps", "maps": MAPS},
        {"op": "read_placements", "as": "placed", "maps": MAPS},
        {"op": "count", "as": "per_map", "rows": "placed", "by": ["map"]},
        {"op": "write_share", "name": "bin-maps", "tables": ["per_map"], "columns": {"per_map": ["map", "count"]}}]}
    ).encode()


class BinFilesTest(unittest.TestCase):
    """The bin on its own: workspace files and share files in and out, never overwriting, across drives, erased."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = paths.resolve(Path(self.tmp.name), "workspace", "share")
        paths.ensure(self.p)

    def tearDown(self):
        self.tmp.cleanup()

    def local(self, name: str = "per-team.json", data: bytes = b'{"rows": [1, 2, 3]}\n') -> Path:
        f = self.p.local / "en-0901-bin" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        return f

    def test_the_bin_is_a_workspace_folder(self):
        self.assertEqual(self.p.bin, self.p.workspace / "bin")
        self.assertTrue(self.p.bin.is_dir())

    def test_a_workspace_file_is_moved_not_erased_and_restored_exactly(self):
        f = self.local()
        before = f.read_bytes()
        item = deleted.remove_workspace_file(self.p, "local/en-0901-bin/per-team.json")
        self.assertFalse(f.exists())
        self.assertEqual((item["kind"], item["name"], item["from"], item["size"]),
                         ("local", "local/en-0901-bin/per-team.json", "Workspace: local/en-0901-bin/per-team.json",
                          len(before)))
        held = tree(self.p.bin / item["id"])
        self.assertEqual(held["files/per-team.json"], before)
        meta = json.loads(held["item.json"])
        self.assertEqual(set(meta), {"format", "id", "kind", "name", "from", "at", "size", "files", "data", "extra"})
        self.assertEqual(meta["from"], {"area": "workspace", "place": "local/en-0901-bin/per-team.json"})
        self.assertNotIn(self.tmp.name, held["item.json"].decode("ascii"))
        self.assertTrue(paths.name_ok(item["id"]))
        self.assertEqual([x["id"] for x in deleted.items(self.p)], [item["id"]])
        self.assertEqual(deleted.restore(self.p, item["id"])["id"], item["id"])
        self.assertEqual(f.read_bytes(), before)
        self.assertEqual(deleted.items(self.p), [])
        self.assertEqual(os.listdir(self.p.bin), [])

    def test_restore_never_overwrites(self):
        f = self.local()
        item = deleted.remove_workspace_file(self.p, "local/en-0901-bin/per-team.json")
        f.write_bytes(b"a newer file")
        with self.assertRaises(deleted.BinError) as cm:
            deleted.restore(self.p, item["id"])
        text = str(cm.exception)
        self.assertIn("Not restored", text)
        self.assertIn("local/en-0901-bin/per-team.json", text)
        self.assertIn(deleted.KEPT, text)
        self.assertNotIn(self.tmp.name, text)
        self.assertEqual(f.read_bytes(), b"a newer file")
        self.assertEqual(len(deleted.items(self.p)), 1)
        f.unlink()
        deleted.restore(self.p, item["id"])
        self.assertEqual(f.read_bytes(), b'{"rows": [1, 2, 3]}\n')

    def test_a_text_export_file_of_the_guided_import(self):
        f = self.p.imported / "20261114-101500-item-engus.json"
        f.write_bytes(b"{}")
        item = deleted.remove_workspace_file(self.p, "imported/20261114-101500-item-engus.json")
        self.assertEqual(item["kind"], "export")
        self.assertFalse(f.exists())
        deleted.restore(self.p, item["id"])
        self.assertEqual(f.read_bytes(), b"{}")

    def test_only_the_workspace_files_the_page_lists(self):
        (self.p.workspace / "textdb.sqlite").write_bytes(b"x")
        self.local()
        for bad in ("textdb.sqlite", "local/../textdb.sqlite", "local/en-0901-bin/../../textdb.sqlite", "inbox/x.json",
                    "local/x.txt", "/local/x.json", "local//x.json", "local/.x.json", "share-counts.json",
                    "local\\en-0901-bin\\per-team.json", 5, None):
            with self.assertRaises(deleted.BinError, msg=repr(bad)):
                deleted.remove_workspace_file(self.p, bad)
        with self.assertRaises(deleted.BinError):
            deleted.remove_workspace_file(self.p, "local/en-0901-bin/none.json")
        self.assertTrue((self.p.workspace / "textdb.sqlite").exists())
        self.assertEqual(deleted.items(self.p), [])

    def test_a_share_file_goes_with_its_row_counts_and_comes_back_with_them(self):
        data = b'{"format": "datapiler-share/1"}\n'
        (self.p.share / "per-team.json").write_bytes(data)
        sha = fileio.sha256_bytes(data)
        guard.record_counts(self.p.share_counts, "per-team.json", sha, {"per_team": ("teamType", 20, "NpcParam")})
        guard.record_counts(self.p.share_counts, "other.json", "b" * 64, {"other": None})
        kept = guard.counts_for(self.p.share_counts, "per-team.json", sha)
        self.assertIsNotNone(kept)
        item = deleted.remove_share(self.p, "per-team.json")
        self.assertEqual((item["kind"], item["from"]), ("share", "Share folder: per-team.json"))
        self.assertFalse((self.p.share / "per-team.json").exists())
        self.assertIsNone(guard.counts_for(self.p.share_counts, "per-team.json", sha))
        self.assertEqual(guard.counts_for(self.p.share_counts, "other.json", "b" * 64), {"other": None})
        deleted.restore(self.p, item["id"])
        self.assertEqual((self.p.share / "per-team.json").read_bytes(), data)
        self.assertEqual(guard.counts_for(self.p.share_counts, "per-team.json", sha), kept)
        for bad in ("../x.json", "Per.json", "con.json", "x.txt", "none.json", None):
            with self.assertRaises(deleted.BinError, msg=repr(bad)):
                deleted.remove_share(self.p, bad)

    def test_across_drives_a_file_is_copied_compared_and_then_removed(self):
        f = self.local()
        before = f.read_bytes()
        real = os.replace
        refused = []

        def replace(src, dst):
            if Path(src) == f:
                refused.append(1)
                raise OSError(errno.EXDEV, "another drive")
            return real(src, dst)

        with mock.patch.object(os, "replace", replace):
            item = deleted.remove_workspace_file(self.p, "local/en-0901-bin/per-team.json")
        self.assertEqual(refused, [1])
        self.assertFalse(f.exists())
        self.assertEqual(tree(self.p.bin / item["id"] / "files"), {"per-team.json": before})

    def test_a_failed_move_puts_back_what_had_moved(self):
        a = self.local("a.json", b"A")
        b = self.local("b.json", b"B")
        real = deleted._move

        def move(src, dst):
            if Path(src) == b:
                raise PermissionError(errno.EACCES, "held by another program")
            return real(src, dst)

        with mock.patch.object(deleted, "_move", move):
            with self.assertRaises(PermissionError):
                deleted.put(self.p, "job", "en-0901-bin", "jobs", "en-0901-bin", [(a, "a.json"), (b, "b.json")])
        self.assertEqual((a.read_bytes(), b.read_bytes()), (b"A", b"B"))
        self.assertEqual(os.listdir(self.p.bin), [])

    def test_erase_and_empty(self):
        one = deleted.remove_workspace_file(self.p, "local/en-0901-bin/%s" % self.local("a.json").name)
        two = deleted.remove_workspace_file(self.p, "local/en-0901-bin/%s" % self.local("b.json").name)
        self.assertEqual(deleted.erase(self.p, one["id"])["id"], one["id"])
        self.assertEqual([x["id"] for x in deleted.items(self.p)], [two["id"]])
        with self.assertRaises(deleted.BinError):
            deleted.erase(self.p, one["id"])
        with self.assertRaises(deleted.BinError):
            deleted.restore(self.p, one["id"])
        self.assertEqual(deleted.empty(self.p), 1)
        self.assertEqual(deleted.items(self.p), [])
        self.assertEqual(os.listdir(self.p.bin), [])
        self.assertFalse((self.p.local / "en-0901-bin" / "a.json").exists())
        for bad in ("../workspace", "", None, "a/b", "con"):
            with self.assertRaises(deleted.BinError, msg=repr(bad)):
                deleted.erase(self.p, bad)
            with self.assertRaises(deleted.BinError, msg=repr(bad)):
                deleted.restore(self.p, bad)

    def test_an_item_that_names_a_place_outside_is_not_one(self):
        item = deleted.remove_workspace_file(self.p, "local/en-0901-bin/%s" % self.local().name)
        f = self.p.bin / item["id"] / deleted.ITEM_FILE
        meta = json.loads(f.read_text("ascii"))
        meta["from"]["place"] = "../../outside.json"
        f.write_text(json.dumps(meta), "ascii")
        self.assertEqual(deleted.items(self.p), [])
        with self.assertRaises(deleted.BinError):
            deleted.restore(self.p, item["id"])
        self.assertFalse((Path(self.tmp.name) / "outside.json").exists())


class TextBinTest(unittest.TestCase):
    """An import of the text database: its rows and its record into the bin, back exactly, through the write imports
    use."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = paths.resolve(Path(self.tmp.name), "workspace", "share")
        paths.ensure(self.p)
        self.sets = mock.patch.dict(textdb.TEXT_SETS, SETS)
        self.sets.start()
        self.db = textdb.TextDB(self.p.textdb)
        self.db.import_export(export(), container="item", language="engus", sha256="a" * 64)
        self.db.import_export(export(), container="item", language="frafr", sha256="c" * 64)

    def tearDown(self):
        self.db.close()
        self.sets.stop()
        self.tmp.cleanup()

    def snapshot(self, container: str, language: str) -> tuple:
        con = sqlite3.connect(str(self.p.textdb))
        try:
            imp = con.execute("SELECT * FROM imports WHERE container = ? AND language = ?",
                              (container, language)).fetchall()
            rows = con.execute("SELECT * FROM entries WHERE container = ? AND language = ? ORDER BY wrapper_id, "
                               "wrapper_name, entry_id", (container, language)).fetchall()
        finally:
            con.close()
        return imp, rows

    def test_imported_text_is_kept_and_restored_exactly(self):
        before = self.snapshot("item", "engus")
        other = self.snapshot("item", "frafr")
        self.assertTrue(before[0] and before[1])
        seen = []
        unsub = events.subscribe("textdb.changed", lambda t, d: seen.append(d))
        try:
            item = deleted.remove_text(self.p, self.db, "item", "engus")
        finally:
            unsub()
        self.assertEqual((item["kind"], item["name"], item["from"]), ("text", "item (engus)",
                                                                      "Text database: item/engus"))
        self.assertFalse(self.db.has("item", "engus"))
        self.assertEqual(self.snapshot("item", "engus"), ([], []))
        self.assertEqual(self.snapshot("item", "frafr"), other)
        self.assertEqual(len(seen), 1)
        self.assertIn("files/rows.json", tree(self.p.bin / item["id"]))
        deleted.restore(self.p, item["id"], textdb=self.db)
        self.assertEqual(self.snapshot("item", "engus"), before)      # its sha256, its time, its counts, its rows
        self.assertEqual(deleted.items(self.p), [])
        # the check-3 index is built again from the texts restored
        self.db.remove("item", "frafr")
        self.assertTrue(self.db.text_hit("Quillon Marrowgate"))

    def test_restore_is_refused_while_that_import_is_in_the_database_again(self):
        item = deleted.remove_text(self.p, self.db, "item", "engus")
        smaller = export()
        smaller["FmgWrappers"] = smaller["FmgWrappers"][:1]
        self.db.import_export(smaller, container="item", language="engus", sha256="b" * 64)
        newer = self.snapshot("item", "engus")
        with self.assertRaises(deleted.BinError) as cm:
            deleted.restore(self.p, item["id"], textdb=self.db)
        self.assertIn("item (engus)", str(cm.exception))
        self.assertIn(deleted.KEPT, str(cm.exception))
        self.assertEqual(self.snapshot("item", "engus"), newer)
        self.assertEqual(len(deleted.items(self.p)), 1)

    def test_nothing_is_taken_out_when_the_bin_cannot_keep_it(self):
        before = self.snapshot("item", "engus")
        with mock.patch.object(deleted, "put", side_effect=OSError(errno.ENOSPC, "no space")):
            with self.assertRaises(OSError):
                deleted.remove_text(self.p, self.db, "item", "engus")
        self.assertEqual(self.snapshot("item", "engus"), before)

    def test_no_such_import(self):
        self.assertIsNone(deleted.remove_text(self.p, self.db, "item", "deude"))
        self.assertIsNone(deleted.remove_text(self.p, self.db, "Item!", "engus"))
        self.assertIsNone(deleted.remove_text(self.p, self.db, "item", "en-GB"))
        self.assertEqual(deleted.items(self.p), [])

    def test_put_back_refuses_a_dump_not_of_its_shape(self):
        for dump in ({}, {"record": {}, "rows": []}, {"record": {"wrappers": 1, "skipped": 0, "sha256": "a" * 64,
                                                               "at": 1.0}, "rows": [[1, "x", "two", "t"]]}):
            with self.assertRaises(ValueError):
                self.db.put_back("item", "deude", dump)
        self.assertFalse(self.db.has("item", "deude"))


class RunnerBinTest(tr.RunnerBase):
    """Jobs and a map job's saved progress: Remove, Start again and a stale progress file move them to the bin."""

    def items(self, kind: str | None = None) -> list:
        return [x for x in deleted.items(self.p) if kind is None or x["kind"] == kind]

    def failed_map_job(self) -> dict:
        self.link.every_map = list(MAPS)
        self.link.loaded = []
        self.link.crash_on_read = 3                 # two maps read and kept, then Smithbox is gone
        card = self.run_job(map_doc(), state="failed")
        self.link.crash_on_read = None
        self.link.loaded = []
        return card

    def wait_state(self, jid: str, state: str) -> dict:
        self.assertTrue(tr.wait_for(lambda: self.card(jid)["state"] == state), self.card(jid))
        return self.card(jid)

    def test_remove_moves_the_job_to_the_bin_and_restore_brings_it_back(self):
        card = self.run_job(tr.fixture("job-files", "good-example.json"))
        folder = self.p.jobs / card["id"]
        before = tree(folder)
        self.assertEqual(sorted(before), ["job.json", "state.json"])
        self.assertEqual(self.r.removal_word(card["id"]), deleted.MOVE)
        self.assertEqual(self.r.act(card["id"], "remove"), {"ok": True})
        self.assertFalse(folder.exists())
        self.assertEqual(self.r.cards(), [])
        self.assertIn("roster-counts.json", self.share_files())      # what the job wrote stays where it is
        [item] = self.items("job")
        self.assertEqual((item["name"], item["from"]), (card["id"], "Jobs: " + card["id"]))
        self.assertEqual(tree(self.p.bin / item["id"] / "files"), before)
        deleted.restore(self.p, item["id"], runner=self.r)
        self.assertEqual(tree(folder), before)
        back = self.card(card["id"])
        for k in ("state", "result", "ops", "sha256", "added", "title"):
            self.assertEqual(back[k], card[k], k)
        self.assertEqual(self.items(), [])
        self.assertIn(("job.added", {"id": card["id"], "state": "done"}), self.events)

    def test_restore_refused_while_the_job_is_here_again(self):
        raw = tr.fixture("job-files", "good-example.json")
        card, _ = self.r.add("job.json", raw)
        self.r.act(card["id"], "remove")
        [item] = self.items("job")
        self.r.add("job.json", raw)                  # the same job dropped again
        with self.assertRaises(deleted.BinError) as cm:
            deleted.restore(self.p, item["id"], runner=self.r)
        self.assertIn("a job with the id %s is here" % card["id"], str(cm.exception))
        self.assertEqual(len(self.items("job")), 1)
        self.assertEqual(len(self.r.cards()), 1)

    def test_restore_refused_when_its_share_file_is_another_jobs_now(self):
        raw = tr.fixture("job-files", "good-example.json")
        card, _ = self.r.add("job.json", raw)
        self.r.act(card["id"], "remove")
        doc = json.loads(raw)
        doc["id"] = "en-0903-other-roster"
        other, _ = self.r.add("other.json", json.dumps(doc).encode())
        self.assertEqual(other["state"], "checked")
        [item] = self.items("job")
        with self.assertRaises(deleted.BinError) as cm:
            deleted.restore(self.p, item["id"], runner=self.r)
        self.assertIn("en-0903-other-roster", str(cm.exception))
        self.assertEqual([c["id"] for c in self.r.cards()], ["en-0903-other-roster"])
        self.assertEqual(len(self.items("job")), 1)

    def test_remove_while_running_moves_it_when_the_run_ends(self):
        self.link.proceed = threading.Event()
        card, _ = self.r.add("job.json", tr.fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(self.link.started.wait(5))
        self.r.act(card["id"], "remove")
        self.assertEqual(self.items(), [])
        self.link.proceed.set()
        self.assertTrue(tr.wait_for(lambda: self.r.cards() == []))
        [item] = self.items("job")
        self.assertEqual(sorted(tree(self.p.bin / item["id"] / "files")), ["job.json", "state.json"])
        deleted.restore(self.p, item["id"], runner=self.r)
        self.assertEqual(self.card(card["id"])["state"], "cancelled")

    def test_a_refused_file_a_new_one_replaces_goes_to_the_bin(self):
        bad_raw = tr.fixture("job-files", "bad-field-not-read.json")
        bad, _ = self.r.add("y.json", bad_raw)
        self.assertEqual(bad["state"], "refused")
        good, _ = self.r.add("z.json", tr.fixture("job-files", "good-example.json"))
        self.assertEqual((good["id"], good["state"]), (bad["id"], "checked"))
        [item] = self.items("job")
        self.assertEqual(tree(self.p.bin / item["id"] / "files")["job.json"], bad_raw)

    def test_a_failed_move_keeps_the_job(self):
        card, _ = self.r.add("job.json", tr.fixture("job-files", "good-example.json"))
        with mock.patch.object(deleted, "_move", side_effect=PermissionError(errno.EACCES, "held")):
            r = self.r.act(card["id"], "remove")
        self.assertFalse(r["ok"])
        self.assertIn("Deleted bin", r["error"])
        self.assertNotIn(self.tmp.name, r["error"])
        self.assertEqual([c["id"] for c in self.r.cards()], [card["id"]])
        self.assertEqual(sorted(tree(self.p.jobs / card["id"])), ["job.json", "state.json"])
        self.assertEqual(self.items(), [])

    def test_a_job_with_saved_progress_needs_delete_and_takes_it_along(self):
        card = self.failed_map_job()
        self.assertEqual(self.r.removal_word(card["id"]), deleted.WORD)
        kept = (self.p.jobs / card["id"] / runner.MAPS_FILE).read_bytes()
        self.r.act(card["id"], "remove")
        [item] = self.items("job")
        self.assertEqual(tree(self.p.bin / item["id"] / "files")[runner.MAPS_FILE], kept)
        deleted.restore(self.p, item["id"], runner=self.r)
        self.assertEqual(self.card(card["id"])["result"]["kept"]["maps"], 2)
        with self.assertRaises(ValueError):
            self.r.removal_word("en-9999-nobody")

    def test_start_again_moves_the_saved_progress_to_the_bin(self):
        card = self.failed_map_job()
        kept = (self.p.jobs / card["id"] / runner.MAPS_FILE).read_bytes()
        self.link.calls = []
        self.assertEqual(self.r.act(card["id"], "start"), {"ok": True})
        self.wait_state(card["id"], "done")
        [item] = self.items("progress")
        self.assertEqual((item["name"], item["from"]), (card["id"], "Jobs: %s/%s" % (card["id"], runner.MAPS_FILE)))
        self.assertEqual(tree(self.p.bin / item["id"] / "files"), {runner.MAPS_FILE: kept})
        self.assertEqual(len([c for c in self.link.calls if c[0] == "BatchGetObjects"]), 5)   # read again

    def test_saved_progress_restored_for_resume_and_its_refusals(self):
        card = self.failed_map_job()
        f = self.p.jobs / card["id"] / runner.MAPS_FILE
        kept = f.read_bytes()
        self.link.state = "off"                      # Start again waits for the link: nothing is read
        self.r.act(card["id"], "start")
        self.wait_state(card["id"], "waiting")
        [item] = self.items("progress")
        with self.assertRaises(deleted.BinError) as cm:
            deleted.restore(self.p, item["id"], runner=self.r)
        self.assertIn("is running", str(cm.exception))
        self.r.act(card["id"], "cancel")
        self.wait_state(card["id"], "cancelled")
        f.write_bytes(b"newer progress\n")
        with self.assertRaises(deleted.BinError) as cm:
            deleted.restore(self.p, item["id"], runner=self.r)
        self.assertIn("saved progress of its own", str(cm.exception))
        self.assertEqual(f.read_bytes(), b"newer progress\n")
        f.unlink()
        deleted.restore(self.p, item["id"], runner=self.r)
        self.assertEqual(f.read_bytes(), kept)
        self.assertEqual(self.card(card["id"])["result"]["kept"]["maps"], 2)
        self.link_on()
        self.link.calls = []
        self.assertEqual(self.r.act(card["id"], "resume"), {"ok": True})
        self.wait_state(card["id"], "done")
        self.assertEqual(sorted(c[1] for c in self.link.calls if c[0] == "BatchGetObjects"), MAPS[2:])

    def test_saved_progress_of_a_job_not_here_is_not_restored(self):
        card = self.failed_map_job()
        self.link.state = "off"
        self.r.act(card["id"], "start")
        self.wait_state(card["id"], "waiting")
        self.r.act(card["id"], "cancel")
        self.wait_state(card["id"], "cancelled")
        self.r.act(card["id"], "remove")
        [item] = self.items("progress")
        with self.assertRaises(deleted.BinError) as cm:
            deleted.restore(self.p, item["id"], runner=self.r)
        self.assertIn("is not here", str(cm.exception))
        self.assertEqual(len(self.items("progress")), 1)

    def test_a_stale_progress_goes_to_the_bin_not_away(self):
        card = self.failed_map_job()
        f = self.p.jobs / card["id"] / runner.MAPS_FILE
        lines = f.read_text("ascii").splitlines()
        header = json.loads(lines[0])
        header["game_version"] = "0.0.0.1-changed"
        f.write_text("\n".join([json.dumps(header)] + lines[1:]) + "\n", "ascii")
        stale = f.read_bytes()
        self.link.calls = []
        self.assertEqual(self.r.act(card["id"], "resume"), {"ok": True})
        self.wait_state(card["id"], "done")
        self.assertEqual([c for c in self.link.calls if c[0] == "OpenResource"], [("OpenResource", tuple(MAPS))])
        [item] = self.items("progress")
        self.assertEqual(tree(self.p.bin / item["id"] / "files"), {runner.MAPS_FILE: stale})


class ApiBinTest(unittest.TestCase):
    """The endpoints: a job's pop-up, DELETE for collected data and for erasing, refused without them; the bin's
    list, Restore, Erase and Empty bin; no path in an answer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "DataPiler"
        self.root.mkdir()
        (base / "Game").mkdir()
        (base / "Game" / "eldenring.exe").write_bytes(b"")
        (base / "Project").mkdir()
        cfg = Settings(game_dir=str(base / "Game"), project_dir=str(base / "Project"))
        self.p = paths.resolve(self.root, cfg.workspace_dir, cfg.share_dir)
        paths.ensure(self.p)
        self.live = Live(root=self.root, settings=cfg, paths=self.p, session=Session())
        self.use = winapi.use(ta.FakeBackend())
        self.use.__enter__()
        self.sets = mock.patch.dict(textdb.TEXT_SETS, SETS)
        self.sets.start()
        self.db = textdb.TextDB(self.p.textdb)
        self.db.import_export(export(), container="item", language="engus", sha256="a" * 64)
        self.guard = guard.Guard(self.db, lambda: ["velkorquist"])
        self.r = runner.Runner(lambda: self.live.paths, tr.FakeLink(), self.db, self.guard,
                               lambda: dict(tr.PROVENANCE), lambda: GameRunning(False, None), lambda: "engus")
        link = ta.FakeLink()
        self.status = Status(lambda: self.live.settings, lambda: link, lambda: False)
        self.api = Api(live=self.live, status=self.status, link=link, runner=self.r, textdb=self.db,
                       guard=self.guard, inbox=ta.FakeInbox(), catalogue=ta.FakeCatalogue(), stop=lambda: None,
                       libs=True)
        self.answers = []

    def tearDown(self):
        for a in self.answers:
            self.assertNotIn(self.tmp.name, a)
        self.api.close()
        self.status.close()
        self.r.stop(cancel=True, timeout=3)
        self.guard.close()
        self.db.close()
        self.sets.stop()
        self.use.__exit__(None, None, None)
        logbook.set_masks(folders={}, home=None, user=None, pc=None)
        self.tmp.cleanup()

    def post(self, path: str, body: dict) -> dict:
        code, answer, _ = self.api.post(path, body)
        self.assertEqual(code, 200, path)
        text = json.dumps(answer)
        self.answers.append(text)
        return json.loads(text)

    def get(self, path: str) -> dict:
        code, answer = self.api.get(path, {})
        self.assertEqual(code, 200, path)
        text = json.dumps(answer)
        self.answers.append(text)
        return json.loads(text)

    def bin(self) -> list:
        return self.get("/api/bin")["items"]

    def test_a_job_asks_first_and_goes_to_the_bin(self):
        card, _ = self.r.add("job.json", tr.fixture("job-files", "good-example.json"))
        for confirm in (None, "yes", "delete", True):
            body = {"id": card["id"], "what": "remove"}
            if confirm is not None:
                body["confirm"] = confirm
            r = self.post("/api/jobs/act", body)
            self.assertFalse(r["ok"], confirm)
            self.assertEqual(r["ask"]["word"], deleted.MOVE)
            self.assertIn("Deleted bin", r["ask"]["text"])
            self.assertEqual(len(self.r.cards()), 1)
        self.assertEqual(self.bin(), [])
        self.assertEqual(self.post("/api/jobs/act", {"id": card["id"], "what": "remove", "confirm": "move"}),
                         {"ok": True})
        self.assertEqual(self.r.cards(), [])
        [item] = self.bin()
        self.assertEqual((item["kind"], item["what"], item["name"]), ("job", "Job", card["id"]))
        self.assertEqual(set(item), {"id", "kind", "what", "name", "from", "when", "at", "size", "files"})
        r = self.post("/api/bin/restore", {"id": item["id"]})
        self.assertTrue(r["ok"])
        self.assertEqual([c["id"] for c in self.r.cards()], [card["id"]])
        with self.assertRaises(Bad):
            self.api.post("/api/jobs/act", {"id": "en-9999-nobody", "what": "remove"})

    def test_a_job_with_saved_progress_needs_delete(self):
        card, _ = self.r.add("job.json", tr.fixture("job-files", "good-example.json"))
        (self.p.jobs / card["id"] / runner.MAPS_FILE).write_bytes(b'{"format": "datapiler-mapprogress/1"}\n')
        r = self.post("/api/jobs/act", {"id": card["id"], "what": "remove", "confirm": "move"})
        self.assertEqual(r["ask"]["word"], deleted.WORD)
        self.assertIn("saved map progress", r["ask"]["text"])
        self.assertEqual(len(self.r.cards()), 1)
        self.assertTrue(self.post("/api/jobs/act", {"id": card["id"], "what": "remove", "confirm": "DELETE"})["ok"])
        self.assertEqual(self.r.cards(), [])

    def test_collected_data_needs_delete(self):
        (self.p.share / "per-team.json").write_bytes(b'{"format": "datapiler-share/1"}\n')
        local = self.p.local / "en-0904-bin" / "named.json"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"{}")
        rev = self.api.get("/api/state", {})[1]["outputs_rev"]      # Status's details may hold paths (api.py)
        for area, name, f in (("share", "per-team.json", self.p.share / "per-team.json"),
                              ("workspace", "local/en-0904-bin/named.json", local)):
            for confirm in (None, "delete", "move", " DELETE"):
                body = {"area": area, "name": name}
                if confirm is not None:
                    body["confirm"] = confirm
                r = self.post("/api/outputs/remove", body)
                self.assertFalse(r["ok"])
                self.assertEqual(r["ask"]["word"], deleted.WORD)
                self.assertIn("type DELETE", r["ask"]["text"])
                self.assertTrue(f.exists())
            r = self.post("/api/outputs/remove", {"area": area, "name": name, "confirm": "DELETE"})
            self.assertTrue(r["ok"], r)
            self.assertFalse(f.exists())
        o = self.get("/api/outputs")
        self.assertEqual(o["share"], [])
        self.assertNotIn("local/en-0904-bin/named.json", [x["name"] for x in o["workspace"]])
        self.assertEqual(sorted(x["kind"] for x in self.bin()), ["local", "share"])
        self.assertGreater(self.api.get("/api/state", {})[1]["outputs_rev"], rev)
        # what the page cannot remove
        for area, name in (("workspace", "textdb.sqlite"), ("workspace", "local/../textdb.sqlite"),
                           ("workspace", "local/en-0904-bin/none.json"), ("share", "../per-team.json"),
                           ("share", "none.json")):
            r = self.post("/api/outputs/remove", {"area": area, "name": name, "confirm": "DELETE"})
            self.assertFalse(r["ok"], name)
            self.assertNotIn("ask", r)
        self.assertTrue(self.p.textdb.exists())
        with self.assertRaises(Bad):
            self.api.post("/api/outputs/remove", {"area": "game", "name": "x.json", "confirm": "DELETE"})
        with self.assertRaises(Bad):
            self.api.post("/api/outputs/remove", {"area": "share", "name": "x.json", "path": "/x"})

    def test_imported_text_needs_delete_and_comes_back(self):
        r = self.post("/api/imported/remove", {"container": "item", "language": "engus"})
        self.assertEqual(r["ask"]["word"], deleted.WORD)
        self.assertTrue(self.db.has("item", "engus"))
        r = self.post("/api/imported/remove", {"container": "item", "language": "engus", "confirm": "DELETE"})
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.db.has("item", "engus"))
        self.assertEqual(self.get("/api/imported")["containers"], [])
        [item] = self.bin()
        self.assertEqual(item["kind"], "text")
        with mock.patch.object(self.r, "busy", lambda: {"kind": "job", "id": "en-0905-busy", "title": None}):
            r = self.post("/api/bin/restore", {"id": item["id"]})
            self.assertFalse(r["ok"])
            self.assertIn("is going", r["error"])
        self.assertTrue(self.post("/api/bin/restore", {"id": item["id"]})["ok"])
        self.assertTrue(self.db.has("item", "engus"))
        with mock.patch.object(self.r, "busy", lambda: {"kind": "job", "id": "en-0905-busy", "title": None}):
            r = self.post("/api/imported/remove", {"container": "item", "language": "engus", "confirm": "DELETE"})
            self.assertIn("is going", r["error"])
        self.assertTrue(self.db.has("item", "engus"))
        for c, lang in (("item", "deude"), ("../item", "engus"), ("", "")):
            r = self.post("/api/imported/remove", {"container": c, "language": lang, "confirm": "DELETE"})
            self.assertEqual(r, {"ok": False, "error": "no such import"})

    def test_restore_refused_when_the_name_is_taken(self):
        local = self.p.local / "en-0904-bin" / "named.json"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"old")
        self.post("/api/outputs/remove", {"area": "workspace", "name": "local/en-0904-bin/named.json",
                                          "confirm": "DELETE"})
        local.write_bytes(b"new")
        [item] = self.bin()
        r = self.post("/api/bin/restore", {"id": item["id"]})
        self.assertFalse(r["ok"])
        self.assertIn("Not restored", r["error"])
        self.assertIn(deleted.KEPT, r["error"])
        self.assertEqual(local.read_bytes(), b"new")
        self.assertEqual(len(self.bin()), 1)
        self.assertEqual(self.post("/api/bin/restore", {"id": "20261114-000000-job-000000"}),
                         {"ok": False, "error": deleted.NO_ITEM})

    def test_erase_and_empty_need_delete(self):
        for name in ("a.json", "b.json"):
            (self.p.share / name).write_bytes(b"{}")
            self.post("/api/outputs/remove", {"area": "share", "name": name, "confirm": "DELETE"})
        first, second = self.bin()
        for confirm in (None, "delete", "move"):
            body = {"id": first["id"]}
            if confirm is not None:
                body["confirm"] = confirm
            r = self.post("/api/bin/erase", body)
            self.assertEqual((r["ok"], r["ask"]["word"], r["ask"]["button"]), (False, deleted.WORD, "Erase"))
            self.assertIn("cannot be undone", r["ask"]["text"])
        self.assertEqual(len(self.bin()), 2)
        self.assertTrue(self.post("/api/bin/erase", {"id": first["id"], "confirm": "DELETE"})["ok"])
        self.assertEqual([x["id"] for x in self.bin()], [second["id"]])
        self.assertEqual(self.post("/api/bin/erase", {"id": first["id"], "confirm": "DELETE"}),
                         {"ok": False, "error": deleted.NO_ITEM})
        r = self.post("/api/bin/empty", {})
        self.assertEqual((r["ok"], r["ask"]["word"]), (False, deleted.WORD))
        self.assertIn("1 item", r["ask"]["text"])
        self.assertEqual(len(self.bin()), 1)
        self.assertEqual(self.post("/api/bin/empty", {"confirm": "DELETE"}), {"ok": True, "erased": 1})
        self.assertEqual(self.get("/api/bin"), {"items": [], "size": 0})
        self.assertFalse((self.p.share / "b.json").exists())
        with self.assertRaises(Bad):
            self.api.post("/api/bin/empty", {"confirm": "DELETE", "all": True})

    def test_the_bin_routes_are_posts(self):
        for path in ("/api/bin/restore", "/api/bin/erase", "/api/bin/empty", "/api/outputs/remove"):
            self.assertEqual(self.api.get(path, {})[0], 404, path)


if __name__ == "__main__":
    unittest.main()
