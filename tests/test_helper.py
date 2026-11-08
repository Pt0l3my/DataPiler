"""update-helper.py's swap and its putting back (build plan 0.2 §4.6, §7.1), on a temporary copy of an invented app
with an old and a new manifest: a swap, a failure planted at each stage, the refusals that touch nothing, a held file
set aside, the rollback, the one backup kept, result.json for each outcome, and no line naming the folder."""

import _repo  # noqa: F401

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from datapiler import install, winapi
from test_archive import helper, invented_app, manifest_of, release_zip, sha

OLD = "0.2.0"
NEW = "0.3.0"


def tree(root: Path, skip=("update", "logs", "datapiler.lock")) -> dict:
    """Every file below root but the helper's own folders, path -> bytes."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d not in skip]
        for f in filenames:
            rel = (Path(dirpath) / f).relative_to(root).as_posix()
            if rel in skip:
                continue
            out[rel] = (Path(dirpath) / f).read_bytes()
    return out


def folders(root: Path) -> set:
    out = set()
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            out.add((Path(dirpath) / d).relative_to(root).as_posix())
    return {d for d in out if not d.startswith(("update", "logs"))}


class Swap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "DataPiler"
        self.root.mkdir()
        self.h = helper()
        self.old_files = invented_app(OLD, **{"datapiler/old_only.py": b"# only in 0.2.0\n",
                                              "datapiler/kept.py": b"# the same in both\n"})
        self.new_files = invented_app(NEW, **{"datapiler/newdir/new.py": b"# new in 0.3.0\n",
                                              "datapiler/kept.py": b"# the same in both\n",
                                              "requirements.lock": b"# datapiler-lock/1\n# changed\n"})
        for rel, data in self.old_files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.root / "manifest.sha256").write_bytes(manifest_of(self.old_files))
        # the owner's own state, which no update touches
        for rel, data in (("workspace/textdb.sqlite", b"invented"), ("share/x.json", b"{}"),
                          ("jobs/a.json", b"{}"), ("settings.json", b'{"format": "datapiler-settings/1"}'),
                          (".venv/datapiler-lock.sha256", b"ab\n"), ("notes-of-my-own.txt", b"mine")):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        # an edited shipped file
        (self.root / "datapiler.py").write_bytes(b"# edited by the owner\n")
        self.before = tree(self.root)
        self.before_dirs = folders(self.root)
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, files=None, version=NEW, **pending_changes):
        files = self.new_files if files is None else files
        z = self.root / "update" / version / ("DataPiler-%s.zip" % version)
        z.parent.mkdir(parents=True, exist_ok=True)
        release_zip(z, files)
        data = z.read_bytes()
        p = install.write_pending(self.root, from_version=OLD, to_version=version,
                                  zip_rel="update/%s/DataPiler-%s.zip" % (version, version), zip_sha256=sha(data),
                                  zip_size=len(data), port=22777)
        if pending_changes:
            path = self.root / "update" / "pending.json"
            doc = json.loads(path.read_text())
            doc.update(pending_changes)
            path.write_text(json.dumps(doc))
        return p

    def run_install(self, **kw):
        kw.setdefault("say", self.said.append)
        return self.h.install(self.root, self.root / "update" / "pending.json", **kw)

    def result(self):
        return json.loads((self.root / "update" / "result.json").read_text())

    def assert_untouched(self):
        self.assertEqual(tree(self.root), self.before)
        self.assertEqual(folders(self.root), self.before_dirs)

    def assert_no_path_said(self):
        log = (self.root / "logs" / "update.log").read_text(encoding="utf-8")
        for text in [log] + self.said:
            self.assertNotIn(self.tmp.name, text)
            self.assertNotIn(str(self.root), text)
        for line in self.said:
            line.encode("ascii")
            self.assertRegex(line, r"^\[\d\d:\d\d:\d\d\] (ok |! |x )?\S")
        for line in log.splitlines():
            self.assertRegex(line, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}  (INFO |WARN |ERROR)  update   \S")
        return log

    # ------------------------------------------------------------------------------------------------ the swap

    def test_a_swap(self):
        p = self.stage()
        self.assertEqual(self.run_install(), 0)
        now = tree(self.root)
        for rel, data in self.new_files.items():
            self.assertEqual(now[rel], data, rel)
        self.assertNotIn("datapiler/old_only.py", now)
        self.assertEqual(now["manifest.sha256"], manifest_of(self.new_files))
        for rel in ("workspace/textdb.sqlite", "share/x.json", "jobs/a.json", "settings.json",
                    ".venv/datapiler-lock.sha256", "notes-of-my-own.txt"):
            self.assertEqual(now[rel], self.before[rel], rel)
        # the backup: what was overwritten or removed, and the old manifest
        b = self.root / "update" / "backup-0.2.0"
        self.assertEqual((b / "files" / "datapiler" / "old_only.py").read_bytes(), b"# only in 0.2.0\n")
        self.assertEqual((b / "files" / "datapiler.py").read_bytes(), b"# edited by the owner\n")
        self.assertEqual((b / "manifest.sha256").read_bytes(), self.before["manifest.sha256"])
        self.assertFalse((b / "files" / "README.md").exists())          # the same: untouched, not backed up
        self.assertFalse((b / "files" / "datapiler" / "kept.py").exists())
        j = json.loads((b / "backup.json").read_text())
        self.assertTrue(j["complete"])
        self.assertEqual(j["added"], ["datapiler/newdir/new.py"])
        self.assertEqual(j["dirs"], ["datapiler/newdir"])
        self.assertEqual(j["nonce"], p.nonce)
        r = self.result()
        self.assertEqual((r["state"], r["stage"], r["nonce"], r["from"], r["to"]), ("updated", "done", p.nonce, OLD,
                                                                                     NEW))
        self.assertEqual(r["counts"], {"written": 3, "added": 1, "removed": 1, "same": 5, "files": 9})
        log = self.assert_no_path_said()
        self.assertIn("datapiler.py was edited here since the last release", log)
        self.assertIn("requirements.lock changed", log)
        self.assertIn("kept: workspace, share, logs, jobs, settings.json, .venv", "\n".join(self.said))
        self.assertFalse(list(self.root.rglob("*.dpnew")))

    def test_the_same_files_are_not_rewritten(self):
        self.stage()
        readme = self.root / "README.md"
        os.utime(readme, (1_000_000_000, 1_000_000_000))
        self.assertEqual(self.run_install(), 0)
        self.assertEqual(readme.stat().st_mtime, 1_000_000_000)

    # ------------------------------------------------------------------------------------------------ failures

    def failed_and_put_back(self, stage):
        self.assertEqual(self.run_install(), 1)
        self.assert_untouched()
        r = self.result()
        self.assertEqual((r["state"], r["stage"]), ("failed", stage))
        self.assertTrue(r["restored"])
        self.assertTrue(r["text"])
        self.assertFalse(list(self.root.rglob("*.dpnew")))
        self.assert_no_path_said()
        return r

    def test_a_failure_while_backing_up(self):
        self.stage()
        real = self.h._copy
        calls = []

        def copy(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError(28, "planted")
            return real(src, dst)

        with mock.patch.object(self.h, "_copy", copy):
            r = self.failed_and_put_back("backup")
        self.assertIn("OSError (errno 28)", r["text"])

    def test_a_failure_while_writing(self):
        self.stage()
        calls = []

        def replace(src, dst):
            calls.append(dst)
            if len(calls) == 3:
                raise OSError(5, "planted")
            return os.replace(src, dst)

        self.failed_and_put_back_with(replace, "write")

    def failed_and_put_back_with(self, replace, stage):
        self.assertEqual(self.run_install(replace=replace), 1)
        self.assert_untouched()
        r = self.result()
        self.assertEqual((r["state"], r["stage"], r["restored"]), ("failed", stage, True))
        self.assert_no_path_said()

    def test_a_landed_file_with_the_wrong_hash(self):
        self.stage()
        real = self.h._landed

        def landed(path):
            if Path(path).name == "new.py":
                return "0" * 64
            return real(path)

        with mock.patch.object(self.h, "_landed", landed):
            r = self.failed_and_put_back("write")
        self.assertIn("datapiler/newdir/new.py did not land as the release has it", r["text"])

    def test_a_failure_while_removing(self):
        self.stage()
        real = self.h._remove
        calls = []

        def remove(path):
            calls.append(path)
            if len(calls) == 1:
                raise PermissionError(13, "planted")
            return real(path)

        with mock.patch.object(self.h, "_remove", remove):
            r = self.failed_and_put_back("remove")
        self.assertIn("PermissionError (errno 13)", r["text"])

    def test_a_failure_writing_the_manifest(self):
        self.stage()

        def replace(src, dst):
            if Path(dst).name == "manifest.sha256" and not getattr(replace, "done", False):
                replace.done = True
                raise OSError(5, "planted")
            return os.replace(src, dst)

        self.failed_and_put_back_with(replace, "manifest")

    def test_ctrl_c_while_writing_is_put_back(self):
        """Found by the reviews (SEC-1, C2): a KeyboardInterrupt from the write stage skipped the putting back."""
        self.stage()
        calls = []

        def replace(src, dst):
            calls.append(dst)
            if len(calls) == 3:
                raise KeyboardInterrupt
            return os.replace(src, dst)

        self.failed_and_put_back_with(replace, "write")
        self.assertIn("KeyboardInterrupt", self.result()["text"])
        self.assertFalse(list(self.root.rglob("*.dpnew")))

    def test_ctrl_c_is_held_off_while_it_swaps(self):
        import signal
        import threading
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("signals are set in the main thread only")
        before = signal.getsignal(signal.SIGINT)
        seen = []

        def replace(src, dst):
            seen.append(signal.getsignal(signal.SIGINT))
            return os.replace(src, dst)

        self.stage()
        self.assertEqual(self.run_install(replace=replace), 0)
        self.assertTrue(seen)
        self.assertTrue(all(s == signal.SIG_IGN for s in seen))
        self.assertEqual(signal.getsignal(signal.SIGINT), before)

    def cut_off(self, after: int):
        """The swap run in a process of its own that dies at once (os._exit) at the after-th os.replace: as if its
        window were closed, or the power cut. Returns the exit code."""
        driver = Path(self.tmp.name) / "driver.py"
        driver.write_text(
            "import importlib.util, os, sys\n"
            "spec = importlib.util.spec_from_file_location('h', sys.argv[1])\n"
            "h = importlib.util.module_from_spec(spec); sys.modules['h'] = h; spec.loader.exec_module(h)\n"
            "n = [0]\n"
            "def replace(src, dst):\n"
            "    n[0] += 1\n"
            "    if n[0] == int(sys.argv[3]):\n"
            "        os._exit(9)\n"
            "    return os.replace(src, dst)\n"
            "sys.exit(h.install(sys.argv[2], os.path.join(sys.argv[2], 'update', 'pending.json'), replace=replace,"
            " say=lambda s: None))\n", encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", str(driver), str(Path(_repo.ROOT, "update-helper.py")),
                               str(self.root), str(after)], capture_output=True, timeout=60)
        self.assertEqual(done.stderr, b"")
        return done.returncode

    def test_a_swap_cut_off_is_put_back_by_rollback(self):
        """Found by the reviews (SEC-1, C2): R refused the backup of a swap that never finished. While pending.json
        names the same update, rollback puts every file back from it."""
        p = self.stage()
        self.assertEqual(self.cut_off(3), 9)
        self.assertNotEqual(tree(self.root), self.before)           # old and new mixed
        self.assertFalse((self.root / "update" / "result.json").exists())
        j = json.loads((self.root / "update" / "backup-0.2.0" / "backup.json").read_text())
        self.assertFalse(j["complete"])
        self.assertEqual(self.h.rollback(self.root, self.root / "update" / "backup-0.2.0", say=self.said.append), 0)
        self.assert_untouched()
        r = self.result()
        self.assertEqual((r["state"], r["nonce"], r["from"], r["to"]), ("rolled_back", p.nonce, NEW, OLD))
        self.assertEqual(r["text"], "the update to 0.3.0 was cut off part way, and its files were put back")
        self.assertIn("did not finish", "\n".join(self.said))
        self.assertFalse(list(self.root.rglob("*.dpnew")))
        self.assert_no_path_said()

    def test_a_swap_cut_off_in_each_stage(self):
        """Cut off before each file the swap puts in place (the files, then the manifest): every time put back."""
        self.stage()
        total = {"n": 0}

        def count(src, dst):
            total["n"] += 1
            return os.replace(src, dst)

        with tempfile.TemporaryDirectory() as spare:
            # how many there are: one swap on a copy
            copy = Path(spare) / "DataPiler"
            shutil.copytree(self.root, copy, symlinks=True)
            pend = json.loads((copy / "update" / "pending.json").read_text())
            pend["root"] = self.h.root_id(copy)
            (copy / "update" / "pending.json").write_text(json.dumps(pend))
            self.assertEqual(self.h.install(copy, copy / "update" / "pending.json", replace=count,
                                            say=lambda s: None), 0)
        self.assertGreater(total["n"], 3)
        for after in range(1, total["n"] + 1):
            with self.subTest(after=after):
                self.stage()
                (self.root / "update" / "result.json").unlink(missing_ok=True)
                self.assertEqual(self.cut_off(after), 9)
                b = self.root / "update" / "backup-0.2.0"
                if (b / "backup.json").exists():
                    self.assertEqual(self.h.rollback(self.root, b, say=self.said.append), 0)
                self.assert_untouched()

    def test_a_file_that_cannot_be_put_back_is_named(self):
        self.stage()
        state = {"n": 0}

        def replace(src, dst):
            if Path(dst).name == "datapiler.py":
                state["n"] += 1
                if state["n"] >= 2:          # the write succeeds, then putting it back fails
                    raise OSError(5, "planted")
            if Path(dst).name == "manifest.sha256" and state["n"] == 1:
                raise OSError(5, "planted")
            return os.replace(src, dst)

        self.assertEqual(self.run_install(replace=replace), 1)
        r = self.result()
        self.assertEqual((r["state"], r["restored"], r["backup"]), ("failed", False, "update/backup-0.2.0"))
        self.assertIn("datapiler.py could not be put back", "\n".join(self.said))
        self.assertTrue((self.root / "update" / "backup-0.2.0" / "files" / "datapiler.py").is_file())

    # ------------------------------------------------------------------------------------------------ refusals

    def refused(self, stage, **kw):
        self.assertEqual(self.run_install(**kw), 2)
        self.assert_untouched()
        r = self.result()
        self.assertEqual((r["state"], r["stage"]), ("refused", stage))
        self.assertFalse((self.root / "update" / "backup-0.2.0").exists())
        self.assert_no_path_said()
        return r

    def test_a_stale_pending_file(self):
        self.stage()
        r = self.refused("checks", now=lambda: time.time() + 601)
        self.assertIn("older than ten minutes", r["text"])

    def test_a_pending_file_from_the_future(self):
        self.stage()
        self.refused("checks", now=lambda: time.time() - 3600)

    def test_a_pending_file_for_another_folder(self):
        self.stage(root="f" * 64)
        r = self.refused("checks")
        self.assertIn("another DataPiler folder", r["text"])

    def test_a_pending_file_naming_a_zip_elsewhere(self):
        self.stage(zip="update/../../elsewhere.zip")
        self.refused("checks")

    def test_no_pending_file(self):
        self.assertEqual(self.run_install(), 2)
        self.assert_untouched()

    def test_the_mutex_held(self):
        self.stage()
        name = "Local\\DataPiler-test-%d" % os.getpid()
        held = winapi.backend().hold_mutex(name, self.root / "datapiler.lock")
        self.assertIsNotNone(held)
        try:
            r = self.refused("checks", mutex=name)
        finally:
            held.release()
        self.assertIn("still running", r["text"])

    def test_a_zip_changed_since_the_page_checked_it(self):
        self.stage()
        z = self.root / "update" / NEW / "DataPiler-0.3.0.zip"
        data = bytearray(z.read_bytes())
        data[-30] ^= 1
        z.write_bytes(bytes(data))
        self.refused("verify")

    def test_a_release_that_would_touch_a_folder_it_never_touches(self):
        for rel in ("workspace/evil.txt", "settings.json", ".venv/x.py", "update/x", "logs/x.log"):
            with self.subTest(rel=rel):
                self.stage(files=dict(self.new_files, **{rel: b"x"}))
                r = self.refused("plan")
                self.assertIn("never touches", r["text"])

    def test_the_workspace_inside_root_from_settings_is_left_alone(self):
        (self.root / "settings.json").write_text(json.dumps({"workspace_dir": "data", "share_dir": "out/share"}))
        (self.root / "data").mkdir()
        (self.root / "data" / "mine.txt").write_bytes(b"mine")
        self.before = tree(self.root)
        self.before_dirs = folders(self.root)
        self.assertIn("data", self.h.never_touched(self.root))
        self.assertIn("out/share", self.h.never_touched(self.root))
        self.stage(files=dict(self.new_files, **{"data/mine.txt": b"from the release"}))
        self.refused("plan")
        self.stage(files=dict(self.new_files, **{"out/share/x.json": b"{}"}))
        self.refused("plan")

    def test_a_workspace_outside_root_does_not_widen_the_list(self):
        outside = Path(self.tmp.name) / "elsewhere"
        (self.root / "settings.json").write_text(json.dumps({"workspace_dir": str(outside)}))
        self.assertEqual(self.h.never_touched(self.root), list(self.h.NEVER))

    def test_no_manifest_here(self):
        (self.root / "manifest.sha256").unlink()
        self.before = tree(self.root)
        self.stage()
        r = self.refused("plan")
        self.assertIn("unpack the release by hand", r["text"])

    def test_a_folder_where_the_release_has_a_file(self):
        (self.root / "datapiler" / "newdir" / "new.py").mkdir(parents=True)
        self.before_dirs = folders(self.root)
        self.stage()
        self.refused("plan")

    @unittest.skipIf(sys.platform == "win32", "symlinks need a privilege on Windows")
    def test_a_link_out_of_the_folder(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "datapiler" / "newdir").symlink_to(outside, target_is_directory=True)
        self.before_dirs = folders(self.root)
        self.stage()
        r = self.refused("plan")
        self.assertIn("leads outside", r["text"])
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(sys.platform == "win32", "symlinks need a privilege on Windows")
    def test_an_alias_of_a_folder_it_never_touches(self):
        """Found by the security review (SEC-5): the never-touched list was compared as text, so another name for
        workspace (an 8.3 short name on Windows, a link here) passed. The plan checks the resolved path too."""
        (self.root / "data2").symlink_to(self.root / "workspace", target_is_directory=True)
        self.before_dirs = folders(self.root)
        self.stage(files=dict(self.new_files, **{"data2/x.txt": b"from the release"}))
        r = self.refused("plan")
        self.assertIn("never touches", r["text"])
        self.assertFalse((self.root / "workspace" / "x.txt").exists())

    def test_a_short_name_is_never_planned(self):
        for rel in ("WORKSP~1/x.txt", "SETTIN~1.JSO", "DATAPI~1.POR", "VENV~1/pyvenv.cfg"):
            self.assertFalse(self.h.safe_rel(rel), rel)
            with self.assertRaises(ValueError):
                self.h.parse_manifest(("%s  %s\n" % ("0" * 64, rel)).encode())

    def test_a_name_whose_case_alone_changed(self):
        """Found by the security review (SEC-6): old NOTICE, new Notice. On a folder that ignores case they are one
        file, which the remove stage deleted after writing it. On one that does not, the old name goes."""
        root = self.root
        (root / "NOTICE").write_bytes(b"notice\n")
        old = {"NOTICE": sha(b"notice\n")}
        new = {"Notice": sha(b"notice, reworded\n")}
        pl = self.h.plan(root, new, old)
        if (root / "notice").exists():              # this folder ignores case (Windows)
            self.assertEqual((pl.write, pl.add, pl.remove), (["Notice"], [], []))
        else:
            self.assertEqual((pl.write, pl.add, pl.remove), ([], ["Notice"], ["NOTICE"]))
        with mock.patch.object(self.h, "_same_file", lambda a, b: a.name.casefold() == b.name.casefold()):
            pl = self.h.plan(root, new, old)
        self.assertEqual(pl.remove, [])

    # ------------------------------------------------------------------------------------------------ the rest

    def test_a_held_file_is_set_aside(self):
        self.stage()
        state = {"held": True}

        def replace(src, dst):
            if Path(dst).name == "requirements.lock" and str(src).endswith(".dpnew") and state["held"]:
                state["held"] = False
                raise PermissionError(13, "planted")
            return os.replace(src, dst)

        self.assertEqual(self.run_install(replace=replace), 0)
        self.assertEqual((self.root / "requirements.lock").read_bytes(), self.new_files["requirements.lock"])
        self.assertEqual((self.root / "requirements.lock.old").read_bytes(), self.old_files["requirements.lock"])
        j = json.loads((self.root / "update" / "backup-0.2.0" / "backup.json").read_text())
        self.assertEqual(j["aside"], ["requirements.lock.old"])
        # the next page-up removes it, and nothing else
        install.cleanup(self.root)
        self.assertFalse((self.root / "requirements.lock.old").exists())
        self.assertTrue((self.root / "update" / "backup-0.2.0" / "backup.json").exists())
        self.assertFalse((self.root / "update" / NEW).exists())

    def test_rollback(self):
        p = self.stage()
        self.assertEqual(self.run_install(), 0)
        self.assertEqual(self.h.rollback(self.root, self.root / "update" / "backup-0.2.0", say=self.said.append), 0)
        self.assert_untouched()
        r = self.result()
        self.assertEqual((r["state"], r["nonce"], r["from"], r["to"]), ("rolled_back", p.nonce, NEW, OLD))
        self.assert_no_path_said()

    def test_rollback_refuses_an_incomplete_backup_and_a_foreign_folder(self):
        """An unfinished backup is put back only while pending.json names the same update."""
        self.stage()
        self.assertEqual(self.run_install(), 0)
        b = self.root / "update" / "backup-0.2.0"
        j = json.loads((b / "backup.json").read_text())
        j["complete"] = False
        (b / "backup.json").write_text(json.dumps(j))
        pending = self.root / "update" / "pending.json"
        doc = json.loads(pending.read_text())
        doc["nonce"] = "e" * 32                     # another update's
        pending.write_text(json.dumps(doc))
        after = tree(self.root)
        self.assertEqual(self.h.rollback(self.root, b, say=self.said.append), 1)
        self.assertEqual(tree(self.root), after)
        pending.unlink()                            # the page came up and removed it
        self.assertEqual(self.h.rollback(self.root, b, say=self.said.append), 1)
        self.assertEqual(tree(self.root), after)
        other = Path(self.tmp.name) / "backup-0.2.0"
        other.mkdir()
        self.assertEqual(self.h.rollback(self.root, other, say=self.said.append), 1)
        self.assertEqual(self.h.rollback(self.root, self.root / "update" / "not-a-backup", say=self.said.append), 1)
        self.assertEqual(tree(self.root), after)

    def test_only_the_latest_backup_is_kept(self):
        for name in ("backup-0.1.0", "backup-0.2.0"):
            d = self.root / "update" / name
            (d / "files").mkdir(parents=True)
            (d / "backup.json").write_text("{}")
        self.stage()
        self.assertEqual(self.run_install(), 0)
        left = sorted(p.name for p in (self.root / "update").glob("backup-*"))
        self.assertEqual(left, ["backup-0.2.0"])
        self.assertTrue(json.loads((self.root / "update" / "backup-0.2.0" / "backup.json").read_text())["complete"])

    def test_a_failed_update_keeps_the_previous_backup(self):
        d = self.root / "update" / "backup-0.1.0"
        d.mkdir(parents=True)
        (d / "backup.json").write_text("{}")
        self.stage()

        def replace(src, dst):
            raise OSError(5, "planted")

        self.assertEqual(self.run_install(replace=replace), 1)
        self.assertTrue(d.exists())

    def test_the_window_runs_it_from_the_download(self):
        """As DataPiler.ps1 runs it: update/<to>/update-helper.py, whose folder two above is DataPiler's."""
        self.stage()
        copy = self.root / "update" / NEW / "update-helper.py"
        copy.write_bytes(self.new_files["update-helper.py"])
        done = subprocess.run([sys.executable, "-I", str(copy), "--pending", str(Path("update") / "pending.json")],
                              cwd=str(self.root), capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout.decode("ascii", "replace"))
        self.assertEqual((self.root / "datapiler" / "__init__.py").read_bytes(),
                         self.new_files["datapiler/__init__.py"])
        out = done.stdout.decode("ascii")
        self.assertNotIn(self.tmp.name, out)
        self.assertIn("ok updated to 0.3.0", out)
        # and R, from the same copy
        done = subprocess.run([sys.executable, "-I", str(copy), "--rollback",
                               str(Path("update") / "backup-0.2.0")], cwd=str(self.root), capture_output=True,
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout.decode("ascii", "replace"))
        self.assert_untouched()

    def test_it_imports_no_network_module(self):
        import ast
        tree_ = ast.parse(Path(_repo.ROOT, "update-helper.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree_):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        for bad in ("urllib", "http", "ssl", "socket", "ftplib", "smtplib", "xmlrpc", "asyncio", "datapiler"):
            self.assertNotIn(bad, names)


if __name__ == "__main__":
    unittest.main()
