"""The check lines, the picker's listing and New folder (build plan 0.2 §5.5, §7.2), on temporary folders with
empty, invented exes, and the Windows adapter's portable fakes."""

import _repo  # noqa: F401

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from datapiler import dirs, game, logbook, sbproject, smithbox, winapi
from datapiler.settings import Settings
from datapiler.winapi import Drive, Proc


class FakeBackend(winapi.PortableBackend):
    def __init__(self):
        self.windows = None
        self.versions = {}
        self.local = None
        self.procs = []
        self.slow = None            # a folder name whose hidden() call waits on this event
        self.gate = threading.Event()

    def windows_dir(self):
        return self.windows

    def drives(self):
        return [Drive("C:", "C:\\", "local"), Drive("D:", "D:\\", "network"), Drive("E:", "E:\\", "odd-kind")]

    def file_version(self, path):
        return self.versions.get(os.path.basename(path).lower())

    def local_appdata(self):
        return self.local

    def processes(self):
        return list(self.procs)

    def hidden(self, path):
        if self.slow and os.path.basename(path) == self.slow:
            self.gate.wait(10)
        return super().hidden(path)


class DirsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "DataPiler"
        self.root.mkdir()
        self.game = self.base / "Games" / "ELDEN RING" / "Game"
        self.game.mkdir(parents=True)
        (self.game / "eldenring.exe").write_bytes(b"")
        self.sb = self.base / "Smithbox"
        self.sb.mkdir()
        self.b = FakeBackend()
        self.use = winapi.use(self.b)
        self.use.__enter__()
        self.s = Settings(game_dir=str(self.game))
        game._version_cache.clear()
        smithbox._build_cache.clear()
        sbproject.forget()

    def tearDown(self):
        self.use.__exit__(None, None, None)
        self.b.gate.set()
        logbook.set_debug(False)
        sbproject.forget()
        self.tmp.cleanup()

    def check(self, want, path, s=None):
        return dirs.check(want, str(path), s or self.s, self.root)

    # ------------------------------------------------------------------------------------ refusals

    def test_path_refusals(self):
        win = "C:\\Windows"
        cases = {
            "relative\\folder": dirs.NOT_PATH, "folder": dirs.NOT_PATH, "C:": dirs.NOT_PATH, "C:Games": dirs.NOT_PATH,
            "C:\\Games\\..\\Windows": dirs.NOT_PATH, "C:\\Games\\..": dirs.NOT_PATH,
            "\\\\.\\PhysicalDrive0": dirs.NOT_PATH, "\\\\?\\C:\\Games": dirs.NOT_PATH, "//?/C:/Games": dirs.NOT_PATH,
            "\\\\server\\share": dirs.NETWORK, "//server/share/x": dirs.NETWORK,
            "C:\\Windows": dirs.WINDOWS, "c:\\windows\\System32": dirs.WINDOWS, "C:/Windows/Temp": dirs.WINDOWS,
            "": dirs.NOT_PATH, "C:\\Games\x00": dirs.NOT_PATH,
        }
        for path, want in cases.items():
            with self.subTest(path=path):
                self.assertEqual(dirs.path_refusal(path, win, posix=False), want)
        # Windows drops a part's trailing dots and spaces when it opens a path (the security review's SEC-4)
        for path in ("C:\\Windows.\\System32", "C:\\Windows.", "C:\\Windows ", "C:\\WINDOWS.\\Temp",
                     "C:\\Windows. .\\x", "C:\\Windows\\System32.\\drivers"):
            with self.subTest(path=path):
                self.assertEqual(dirs.path_refusal(path, win, posix=False), dirs.WINDOWS)
        for ok in ("C:\\Games", "C:\\Windows2", "D:\\", "C:\\Games\\.\\x", "C:\\Windows.old", "C:\\Win dows"):
            with self.subTest(ok=ok):
                self.assertIsNone(dirs.path_refusal(ok, win, posix=False))
        self.assertEqual(dirs.path_refusal("/tmp/x", win, posix=False), dirs.NOT_PATH)
        self.assertIsNone(dirs.path_refusal("/tmp/x", None, posix=True))

    def test_the_listing_answers_refusals_as_refused_and_nothing_else(self):
        self.b.windows = str(self.base / "Win")
        (self.base / "Win" / "System32").mkdir(parents=True)
        for path in ("relative", "\\\\server\\share", "\\\\?\\C:\\x", str(self.base / "Win"),
                     str(self.base / "Win" / "System32"), str(self.base) + "/a/../b"):
            with self.subTest(path=path):
                got = dirs.listing("game", path, self.s, self.root)
                self.assertEqual(list(got), ["refused"])

    # ------------------------------------------------------------------------------------ the listing

    def test_folder_names_only_hidden_left_out_sorted_and_marked(self):
        common = self.base / "Games"
        for name in ("beta", "Alpha", ".hidden", "gamma"):
            (common / name).mkdir()
        (common / "a-file.txt").write_text("never listed", encoding="utf-8")
        (common / "Alpha" / "eldenring.exe").write_bytes(b"")
        got = dirs.listing("game", str(common), self.s, self.root)
        self.assertEqual([d["name"] for d in got["dirs"]], ["Alpha", "beta", "ELDEN RING", "gamma"])
        self.assertEqual({d["name"]: d["mark"] for d in got["dirs"]}["Alpha"], True)
        self.assertFalse(any(d["mark"] for d in got["dirs"] if d["name"] != "Alpha"))
        self.assertEqual(set(got), {"path", "shown", "crumbs", "parent", "dirs", "more", "check", "note"})
        for d in got["dirs"]:
            self.assertEqual(set(d), {"name", "path", "shown", "mark"})
            self.assertEqual(d["path"], str(common / d["name"]))
            self.assertEqual(d["shown"], d["name"])                   # the mask is off
        self.assertEqual(got["parent"], str(self.base))
        self.assertEqual(got["more"], 0)
        self.assertIsNone(got["note"])
        self.assertEqual(got["check"]["ok"], False)
        self.assertEqual(got["shown"], got["path"])
        self.assertEqual(got["crumbs"][-1], {"name": "Games", "path": str(common)})
        self.assertNotIn("a-file.txt", json.dumps(got))

    def test_marks_for_each_want(self):
        f = self.base / "Picks"
        for name in ("Vulkan", "Plain", "GL", "Proj", "Proj2", "None"):
            (f / name).mkdir(parents=True)
        (f / "Vulkan" / "Smithbox.Vulkan.exe").write_bytes(b"")
        (f / "GL" / "Smithbox.OpenGL.exe").write_bytes(b"")
        (f / "Plain" / "Smithbox.exe").write_bytes(b"")
        (f / "Proj" / "project.json").write_text("{}", encoding="utf-8")
        (f / "Proj2" / ".smithbox").mkdir()
        marks = lambda want: {d["name"] for d in dirs.listing(want, str(f), self.s, self.root)["dirs"] if d["mark"]}
        self.assertEqual(marks("smithbox"), {"Vulkan", "GL", "Plain"})
        self.assertEqual(marks("project"), {"Proj", "Proj2"})
        self.assertEqual(marks("game"), set())

    def test_more_past_the_limit_and_the_filter(self):
        f = self.base / "Many"
        f.mkdir()
        with mock.patch.object(dirs, "LIST_MAX", 5):
            for i in range(8):
                (f / ("d%02d" % i)).mkdir()
            got = dirs.listing("game", str(f), self.s, self.root)
            self.assertEqual((len(got["dirs"]), got["more"]), (5, 3))
            got = dirs.listing("game", str(f), self.s, self.root, filt="D07")
            self.assertEqual(([d["name"] for d in got["dirs"]], got["more"]), (["d07"], 0))

    def test_no_access_and_no_such_folder(self):
        with mock.patch.object(dirs.os, "scandir", side_effect=PermissionError(13, "denied")):
            got = dirs.listing("game", str(self.base), self.s, self.root)
        self.assertEqual((got["dirs"], got["note"]), ([], "(no access)"))
        got = dirs.listing("game", str(self.base / "nowhere"), self.s, self.root)
        self.assertEqual((got["dirs"], got["note"]), ([], "no such folder"))

    def test_a_link_is_listed_by_its_name(self):
        target = self.base / "Target"
        target.mkdir()
        link = self.base / "Games" / "Link"
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this system makes no symlinks here")
        got = dirs.listing("game", str(self.base / "Games"), self.s, self.root)
        self.assertIn("Link", [d["name"] for d in got["dirs"]])
        self.assertEqual(dirs.resolved(str(link)), str(target.resolve()))

    def test_the_3_s_limit_and_one_listing_a_drive(self):
        f = self.base / "Slow"
        (f / "sleepy").mkdir(parents=True)
        self.b.slow = "sleepy"
        with mock.patch.object(dirs, "LIST_SECS", 0.2):
            t0 = time.monotonic()
            got = dirs.listing("game", str(f), self.s, self.root)
            self.assertLess(time.monotonic() - t0, 2.0)
            self.assertEqual((got["dirs"], got["note"]), ([], "this drive did not answer in 3 s"))
            # the drive's listing has still not ended: a second request waits for it, at most the limit, then
            # says so; it never starts a second listing of the drive
            t0 = time.monotonic()
            got = dirs.listing("game", str(self.base), self.s, self.root)
            self.assertLess(time.monotonic() - t0, 0.2 + 0.15)
            self.assertEqual(got["note"], "this drive did not answer in 3 s")
            self.b.gate.set()
            time.sleep(0.1)
            got = dirs.listing("game", str(self.base), self.s, self.root)
            self.assertIsNone(got["note"])

    def test_a_second_listing_waits_for_the_first(self):
        """Found by the correctness review (C8): a request while the drive's listing was still under way was told
        at once that the drive had not answered, and the page drew that empty answer."""
        f = self.base / "Busy"
        (f / "sleepy").mkdir(parents=True)
        (f / "awake").mkdir()
        self.b.slow = "sleepy"
        answers = {}
        first = threading.Thread(target=lambda: answers.update(first=dirs.listing("game", str(f), self.s, self.root)))
        first.start()
        time.sleep(0.1)
        threading.Timer(0.3, self.b.gate.set).start()           # the first listing ends after 0.4 s
        second = dirs.listing("game", str(f), self.s, self.root, filt="awa")
        first.join(5)
        self.assertIsNone(second["note"])
        self.assertEqual([d["name"] for d in second["dirs"]], ["awake"])
        self.assertEqual([d["name"] for d in answers["first"]["dirs"]], ["awake", "sleepy"])

    def test_masked_names_and_the_real_paths_beside_them(self):
        """Found by the reviews (SEC-2, C5): with Mask paths on, the picker drew its crumbs masked but the folders it
        listed as they are, so the folder named after the account showed in C:\\Users."""
        users = self.base / "Users"
        home = users / "Inventedname"
        for d in (home / "AppData", users / "Public", users / "Inventedname-old", self.base / "Tools" / "Smithbox",
                  self.base / "Tools" / "Smithbox 2.2.6 2026-11-01"):
            d.mkdir(parents=True)
        logbook.set_masks(folders={"<SMITHBOX>": str(self.base / "Tools" / "Smithbox")}, home=str(home),
                          user="Inventedname", pc="INVENTED-PC")
        try:
            s = Settings(game_dir=str(self.game), mask_paths=True)
            got = dirs.listing("game", str(users), s, self.root)
            self.assertEqual([(d["name"], d["shown"]) for d in got["dirs"]],
                             [("Inventedname", "<HOME>"), ("Inventedname-old", "<USER>-old"), ("Public", "Public")])
            self.assertEqual([d["path"] for d in got["dirs"]], [str(users / d["name"]) for d in got["dirs"]])
            drawn = json.dumps({k: v for k, v in got.items() if k not in ("dirs", "parent")}) + json.dumps(
                [d["shown"] for d in got["dirs"]])
            self.assertNotIn("Inventedname", drawn)
            inside = dirs.listing("game", str(home), s, self.root)
            self.assertEqual((inside["shown"], [d["shown"] for d in inside["dirs"]]), ("<HOME>", ["AppData"]))
            # a sibling that only adds to a masked folder's name is not drawn as that folder (C6)
            tools = dirs.listing("smithbox", str(self.base / "Tools"), s, self.root)
            self.assertEqual([d["shown"] for d in tools["dirs"]], ["<SMITHBOX>", "Smithbox 2.2.6 2026-11-01"])
        finally:
            logbook.set_masks(folders={}, home=None, user=None, pc=None)

    def test_up_goes_to_the_parent_whatever_the_crumbs(self):
        """Found by the correctness review (C9): Up opened the crumb before the last, and with the mask on a masked
        folder is one crumb, so Up went to This PC."""
        self.assertEqual(dirs.parent_of("C:\\Games\\ELDEN RING\\Game"), "C:\\Games\\ELDEN RING")
        self.assertEqual(dirs.parent_of("C:\\Games"), "C:\\")
        self.assertEqual(dirs.parent_of("C:\\"), "")
        self.assertEqual(dirs.parent_of("/a/b"), "/a")
        self.assertEqual(dirs.parent_of("/a"), "/")
        self.assertEqual(dirs.parent_of("/"), "")
        logbook.set_masks(folders={"<GAME>": str(self.game)}, home=None, user=None, pc=None)
        try:
            got = dirs.listing("game", str(self.game), Settings(game_dir=str(self.game), mask_paths=True), self.root)
            self.assertEqual(len(got["crumbs"]), 1)
            self.assertEqual(got["parent"], str(self.game.parent))
        finally:
            logbook.set_masks(folders={}, home=None, user=None, pc=None)

    def test_a_mapped_drive_keeps_its_letter(self):
        """Found by the correctness review (C10): Windows' realpath turns a mapped drive into its network path, whose
        check line is 'not checked'. A drive-letter path that resolves to a network path is kept as chosen."""
        unc_path = Path("\\\\server\\share\\Projects")
        with mock.patch.object(dirs.Path, "resolve", lambda self, strict=False: unc_path):
            self.assertEqual(dirs.resolved("Z:\\Projects"), "Z:\\Projects")
            self.assertEqual(dirs.resolved("/tmp/projects"), str(unc_path))

    def test_drives_with_letter_and_kind_only(self):
        got = dirs.listing("game", "", self.s, self.root)
        self.assertEqual(got, {"path": "", "shown": "This PC", "crumbs": [], "dirs": [], "more": 0, "check": None,
                               "note": None, "drives": [{"name": "C:", "path": "C:\\", "kind": "local"},
                                                        {"name": "D:", "path": "D:\\", "kind": "network"},
                                                        {"name": "E:", "path": "E:\\", "kind": "unknown"}]})

    def test_the_debug_line_holds_counts_only(self):
        # DEBUG lines go to the file only (the ring takes INFO and up), so the call itself is read
        with mock.patch.object(dirs._log, "debug") as debug:
            dirs.listing("game", str(self.base / "Games"), self.s, self.root)
            dirs.listing("game", "", self.s, self.root)
        msgs = [logbook.format_message(c.args[0], c.args[1:]) for c in debug.call_args_list]
        self.assertEqual(msgs, ["picker: 1 folder listed, 1 entries", "picker: 0 folder listed, 3 entries"])
        self.assertTrue(all(isinstance(a, int) for c in debug.call_args_list for a in c.args[1:]))

    def test_masked_crumbs(self):
        logbook.set_masks(folders={"<GAME>": str(self.game)}, home=None, user=None, pc=None)
        try:
            (self.game / "sub").mkdir()
            s = Settings(game_dir=str(self.game), mask_paths=True)
            got = dirs.listing("project", str(self.game / "sub"), s, self.root)
            self.assertEqual(got["shown"], "<GAME>" + os.sep + "sub" if os.sep == "\\" else "<GAME>/sub")
            self.assertEqual([c["name"] for c in got["crumbs"]], ["<GAME>", "sub"])
            self.assertEqual(got["crumbs"][0]["path"], str(self.game))
            self.assertNotIn(str(self.base), json.dumps([c["name"] for c in got["crumbs"]]))
            # Windows-shaped paths, as the owner's PC gives them
            logbook.set_masks(folders={"<GAME>": "C:\\Games\\ELDEN RING\\Game"}, home=None, user=None, pc=None)
            crumbs = dirs._crumbs("C:\\Games\\ELDEN RING\\Game\\sub\\deeper", True)
            self.assertEqual(crumbs, [{"name": "<GAME>", "path": "C:\\Games\\ELDEN RING\\Game"},
                                      {"name": "sub", "path": "C:\\Games\\ELDEN RING\\Game\\sub"},
                                      {"name": "deeper", "path": "C:\\Games\\ELDEN RING\\Game\\sub\\deeper"}])
            self.assertEqual([c["name"] for c in dirs._crumbs("C:\\Mods\\X", False)], ["C:", "Mods", "X"])
        finally:
            logbook.set_masks(folders={}, home=None, user=None, pc=None)

    # ------------------------------------------------------------------------------------ check lines

    def test_every_check_line(self):
        ok = lambda c: (c.ok, str(c.text), c.mark)
        self.assertEqual(ok(self.check("game", "")), ("warn", "not set", False))
        self.assertEqual(ok(self.check("game", "\\\\nas.invalid\\share")), ("warn", "a network path - not checked",
                                                                            False))
        self.assertEqual(ok(self.check("game", "relative")),
                         (False, "a full folder path is needed (it starts with a drive letter)", False))
        self.assertEqual(ok(self.check("game", "\\\\?\\C:\\x"))[0], False)
        self.assertEqual(ok(self.check("smithbox", self.base / "nowhere")), ("warn", "no such folder", False))
        self.assertEqual(ok(self.check("project", self.base / "nowhere")),
                         ("warn", "no such folder - New folder… in the picker makes one", False))
        # the game
        self.assertEqual(ok(self.check("game", self.game)), (True, "eldenring.exe is here · version not read", True))
        self.b.versions["eldenring.exe"] = "1.99.0.0"
        game._version_cache.clear()
        self.assertEqual(ok(self.check("game", self.game)), (True, "eldenring.exe is here · version 1.99.0.0", True))
        self.assertEqual(ok(self.check("game", self.game.parent)),
                         (False, "no eldenring.exe here - the game's folder is the Game folder inside ELDEN RING",
                          False))

    def test_smithbox_check_lines(self):
        """Smithbox*.exe in any case: Smithbox.Vulkan.exe (a fact on the owner's PC), Smithbox.exe (a lead), both,
        neither; the build of the running one, else the one they share, both named when they differ."""
        txt = lambda: str(self.check("smithbox", self.sb).text)
        self.assertEqual(self.check("smithbox", self.sb).ok, False)
        self.assertEqual(txt(), "no Smithbox exe here (Smithbox*.exe)")
        (self.sb / "Smithbox.Vulkan.exe").write_bytes(b"")
        self.assertEqual(txt(), "Smithbox.Vulkan.exe is here · build not read")
        self.b.versions = {"smithbox.vulkan.exe": "2.2.6.0", "smithbox.opengl.exe": "2.2.6.0", "smithbox.exe": "2.0.0.0"}
        smithbox._build_cache.clear()
        self.assertEqual(txt(), "Smithbox.Vulkan.exe is here · build 2.2.6.0")
        (self.sb / "Smithbox.OpenGL.exe").write_bytes(b"x")
        self.assertEqual(txt(), "Smithbox.Vulkan.exe and Smithbox.OpenGL.exe are here · build 2.2.6.0")
        self.b.versions["smithbox.opengl.exe"] = "2.2.5.0"
        smithbox._build_cache.clear()
        self.assertEqual(txt(), "Smithbox.Vulkan.exe and Smithbox.OpenGL.exe are here · builds differ: "
                                "Smithbox.Vulkan.exe 2.2.6.0, Smithbox.OpenGL.exe 2.2.5.0")
        self.b.procs = [Proc("smithbox.opengl.exe", str(self.sb / "Smithbox.OpenGL.exe"))]
        self.assertEqual(txt(), "Smithbox.Vulkan.exe and Smithbox.OpenGL.exe are here · build 2.2.5.0 "
                                "(the running one)")
        self.b.procs = []
        for f in self.sb.iterdir():
            f.unlink()
        (self.sb / "smithbox.exe").write_bytes(b"")
        self.assertEqual(txt(), "smithbox.exe is here · build 2.0.0.0")
        self.assertTrue(self.check("smithbox", self.sb).mark)
        (self.sb / "smithbox.exe").unlink()
        (self.sb / "NotSmithbox.exe").write_bytes(b"")
        (self.sb / "Smithbox.Vulkan.dll").write_bytes(b"")
        self.assertEqual(self.check("smithbox", self.sb).ok, False)

    def test_project_check_lines(self):
        txt = lambda path, s=None: (self.check("project", path, s).ok, str(self.check("project", path, s).text))
        mods = self.base / "Mods" / "ER project"
        mods.mkdir(parents=True)
        self.assertEqual(txt(mods), (True, "outside the game's folder"))
        self.assertEqual(txt(mods, Settings()), ("warn", "set the game folder first, so this can be checked "
                                                         "against it"))
        for path, words in ((self.game, "the game's folder itself"), (self.game / "mod", "inside the game's folder"),
                            (self.base / "Games", "it holds the game's folder"),
                            (self.root, "DataPiler's own folder"), (self.root / "p", "inside DataPiler's folder")):
            Path(path).mkdir(exist_ok=True)
            with self.subTest(path=path.name):
                self.assertEqual(txt(path), (False, words + " - choose a folder outside it"))
        (mods / "project.json").write_text("{}", encoding="utf-8")
        self.assertEqual(txt(mods), (True, "outside the game's folder · a Smithbox project file is here"))
        self.assertTrue(self.check("project", mods).mark)
        # a recognised record names this folder and the game folder: the stronger line (smithbox-projects.md §5)
        local = self.base / "Local"
        (local / "Smithbox" / "Projects").mkdir(parents=True)
        (local / "Smithbox" / "Projects" / "p.json").write_text(json.dumps({
            "ProjectName": "Invented", "ProjectPath": str(mods), "DataPath": str(self.game), "ProjectType": 8,
            "AutoSelect": True}), encoding="utf-8")
        self.b.local = str(local)
        self.assertEqual(txt(mods), (True, "outside the game's folder · a Smithbox project for this game"))

    # ------------------------------------------------------------------------------------ New folder

    def test_name_refusals(self):
        for bad in ("", "  ", "a<b", "a>b", 'a"b', "a/b", "a\\b", "a|b", "a?b", "a*b", "a:b", "tab\there", "dot.",
                    "space ", "CON", "con.txt", "NUL", "com1", "LPT9.log", "x" * 256, ".", ".."):
            with self.subTest(bad=bad):
                self.assertIsNotNone(dirs.name_refusal(bad))
        for good in ("ER project", "mod.v2", "Project (2)", "x" * 255, "CONSOLE"):
            with self.subTest(good=good):
                self.assertIsNone(dirs.name_refusal(good))

    def test_new_folder(self):
        mods = self.base / "Mods"
        mods.mkdir()
        got = dirs.new_folder(str(mods), "ER project", self.s, self.root)
        self.assertEqual(got, {"path": str(mods / "ER project"), "shown": str(mods / "ER project")})
        self.assertTrue((mods / "ER project").is_dir())
        self.assertEqual(dirs.new_folder(str(mods), "ER project", self.s, self.root),
                         {"refused": "a folder of that name is here already"})
        self.assertIn("refused", dirs.new_folder(str(self.game), "mod", self.s, self.root))
        self.assertIn("refused", dirs.new_folder(str(self.root), "proj", self.s, self.root))
        self.assertIn("refused", dirs.new_folder(str(mods), "CON", self.s, self.root))
        self.assertIn("refused", dirs.new_folder("relative", "x", self.s, self.root))
        self.assertIn("refused", dirs.new_folder("\\\\server\\share", "x", self.s, self.root))
        self.assertEqual(dirs.new_folder(str(mods / "nowhere"), "x", self.s, self.root), {"refused": "no such folder"})
        self.assertFalse((mods / "nowhere").exists())          # os.mkdir, never makedirs
        self.assertFalse((self.game / "mod").exists())
        self.assertFalse((self.root / "proj").exists())


if __name__ == "__main__":
    unittest.main()
