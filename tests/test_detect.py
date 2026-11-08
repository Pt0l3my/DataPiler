"""Detect (build plan 0.2 §5.4, §7.2; DP13, DP15): each source through a fake backend (registry values from REGISTRY
only, processes with their paths), temporary folders holding empty, invented exes, and nothing saved."""

import _repo  # noqa: F401

import ast
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from datapiler import detect, logbook, sbproject, smithbox, steam, winapi
from datapiler.api import Live
from datapiler.paths import resolve
from datapiler.settings import Session, Settings, with_values
from datapiler.winapi import Proc

ROOT = Path(_repo.ROOT)


def vdf(path: str) -> str:
    return path.replace("\\", "\\\\")


class FakeBackend(winapi.PortableBackend):
    def __init__(self):
        self.reg = {}               # (hive, key, name) -> value
        self.reads = []
        self.procs = []
        self.local = None
        self.versions = {}
        self.fail = False

    def registry_value(self, hive, key, name):
        self.reads.append((hive, key, name))
        return self.reg.get((hive, key, name))

    def processes(self):
        if self.fail:
            raise OSError(5, "refused")
        return list(self.procs)

    def local_appdata(self):
        return self.local

    def file_version(self, path):
        return self.versions.get(os.path.basename(path).lower())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "DataPiler"
        self.root.mkdir()
        self.b = FakeBackend()
        self.use = winapi.use(self.b)
        self.use.__enter__()
        self.live = Live(root=self.root, settings=Settings(), paths=resolve(self.root, "workspace", "share"),
                         session=Session())
        self.folders = detect.Folders(self.live)
        sbproject.forget()
        smithbox._build_cache.clear()

    def tearDown(self):
        self.folders.close()
        smithbox.stop_watch()
        self.use.__exit__(None, None, None)
        logbook.set_masks(folders={}, home=None, user=None, pc=None)
        sbproject.forget()
        self.tmp.cleanup()

    def mk(self, *parts, exe=None):
        p = self.base.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        for e in ([exe] if isinstance(exe, str) else exe or []):
            (p / e).write_bytes(b"")
        return p

    def steam_install(self, *, with_apps=True, dlc=(9000020,)):
        steam_dir = self.mk("Steam")
        lib = self.mk("Library")
        game = self.mk("Library", "steamapps", "common", "ELDEN RING", "Game", exe="eldenring.exe")
        (steam_dir / "steamapps").mkdir(exist_ok=True)
        apps = '"apps" { "%d" "1" }' % steam.GAME_APP_ID if with_apps else ""
        (steam_dir / "steamapps" / "libraryfolders.vdf").write_text(
            '"libraryfolders" { "0" { "path" "%s" } "1" { "path" "%s" %s } }' % (vdf(str(steam_dir)), vdf(str(lib)),
                                                                                 apps), encoding="utf-8")
        depots = "".join('"%d" { "size" "1" "dlcappid" "%d" }' % (i + 1, d) for i, d in enumerate(dlc))
        (lib / "steamapps" / ("appmanifest_%d.acf" % steam.GAME_APP_ID)).write_text(
            '"AppState" { "appid" "%d" "installdir" "ELDEN RING" "InstalledDepots" { "9" { "size" "1" } %s } }'
            % (steam.GAME_APP_ID, depots), encoding="utf-8")
        self.b.reg[detect.REGISTRY["steam_user"]] = str(steam_dir)
        return steam_dir, lib, game

    def record(self, **leads):
        local = self.base / "Local"
        folder = local / "Smithbox" / "Projects"
        folder.mkdir(parents=True, exist_ok=True)
        for i, (name, (project, data, marked)) in enumerate(leads.items()):
            (folder / ("p%d.json" % i)).write_text(json.dumps({
                "ProjectGUID": "00000000-0000-4000-8000-00000000000%d" % i, "ProjectName": name,
                "ProjectPath": str(project), "DataPath": str(data), "ProjectType": 8, "AutoSelect": marked}),
                encoding="utf-8")
        self.b.local = str(local)
        sbproject.forget()


class SourcesTest(Base):
    def test_the_running_smithbox_and_recent(self):
        """DP13: Smithbox's folder from its running process; any Smithbox*.exe; a candidate without one dropped."""
        vulkan = self.mk("Tools", "Smithbox-build", exe=["Smithbox.Vulkan.exe", "Smithbox.OpenGL.exe"])
        old = self.mk("Old", "Smithbox", exe="Smithbox.exe")
        gone = self.mk("Old", "Empty")
        self.live.settings = with_values(Settings(), recent={"smithbox_dir": (str(old), str(gone)), "game_dir": (),
                                                             "project_dir": ()})
        self.assertEqual(self.folders.detect("smithbox"), [detect.Candidate(str(old.resolve()), ("recent",), None,
                                                                            False, None)])
        self.assertIn(detect.NOT_RUNNING, self.folders.notes("smithbox"))
        self.b.procs = [Proc("smithbox.vulkan.exe", str(vulkan / "Smithbox.Vulkan.exe")), Proc("explorer.exe", None)]
        got = self.folders.detect("smithbox")
        self.assertEqual([(Path(c.value).name, c.sources) for c in got],
                         [("Smithbox-build", ("running_smithbox",)), ("Smithbox", ("recent",))])
        self.assertEqual(self.folders.notes("smithbox"), [])

    def test_smithbox_exe_names(self):
        """Smithbox.Vulkan.exe is a fact on the owner's PC; Smithbox.exe a lead; both; neither."""
        for exes, counts in ((["Smithbox.Vulkan.exe"], True), (["Smithbox.exe"], True),
                             (["Smithbox.Vulkan.exe", "Smithbox.OpenGL.exe"], True), (["SmithboxHelper.dll"], False),
                             ([], False)):
            with self.subTest(exes=exes):
                f = self.mk("Case%d" % len(list(self.base.iterdir())), exe=exes)
                name = exes[0] if exes and exes[0].endswith(".exe") else "Smithbox.exe"
                self.b.procs = [Proc(name.lower(), str(f / name))]
                self.assertEqual(len(self.folders.detect("smithbox")), 1 if counts else 0)

    def test_the_game_from_steam_the_uninstall_entry_and_the_running_game(self):
        _, lib, game = self.steam_install()
        got = self.folders.detect("game")
        self.assertEqual([(c.value, c.sources) for c in got], [(str(game.resolve()), ("steam_library",))])
        # the uninstall entries add \Game; the running game its own folder; all merge into one place
        self.b.reg[detect.REGISTRY["uninstall"]] = str(game.parent)
        self.b.reg[detect.REGISTRY["uninstall_32"]] = str(game.parent) + os.sep
        self.b.procs = [Proc("eldenring.exe", str(game / "eldenring.exe"))]
        got = self.folders.detect("game")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].sources, ("steam_library", "steam_uninstall", "running_game"))
        # without apps (an older file) every library is tried
        self.steam_install(with_apps=False)
        self.b.procs = []
        self.assertEqual(len(self.folders.detect("game")), 1)

    def test_steam_system_and_a_broken_library_list(self):
        steam_dir, lib, game = self.steam_install()
        del self.b.reg[detect.REGISTRY["steam_user"]]
        self.b.reg[detect.REGISTRY["steam_system"]] = str(steam_dir)
        self.assertEqual(len(self.folders.detect("game")), 1)
        (steam_dir / "steamapps" / "libraryfolders.vdf").write_text("broken {", encoding="utf-8")
        self.assertEqual(self.folders.detect("game"), [])
        self.assertIn(detect.NO_STEAM_LIST, self.folders.notes("game"))

    def test_candidates_without_their_exe_are_dropped(self):
        empty = self.mk("NoGame", "Game")
        self.b.reg[detect.REGISTRY["uninstall"]] = str(empty.parent)
        self.b.procs = [Proc("eldenring.exe", None)]               # no path: nothing to offer
        self.assertEqual(self.folders.detect("game"), [])

    def test_smithbox_record_and_the_cross_check(self):
        """DP13: the project and game folders from Smithbox's record; Steam's library list agrees, or both are listed
        and neither is chosen."""
        _, lib, game = self.steam_install()
        project = self.mk("Mods", "ER project")
        self.record(Mine=(project, game, True))
        got = self.folders.detect("game")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].sources, ("smithbox_record", "steam_library"))
        self.assertTrue(got[0].marked)
        self.assertEqual(detect.tags(got[0]), ["Smithbox's project record, marked to open", detect.AGREES])
        self.assertNotIn(detect.DIFFER, self.folders.notes("game"))
        other = self.mk("Elsewhere", "Game", exe="eldenring.exe")
        self.record(Mine=(project, other, True))
        got = self.folders.detect("game")
        self.assertEqual({c.sources for c in got}, {("smithbox_record",), ("steam_library",)})
        self.assertIn(detect.DIFFER, self.folders.notes("game"))
        p = self.folders.detect("project")
        self.assertEqual([(c.value, c.sources, c.name, c.marked) for c in p],
                         [(str(project.resolve()), ("smithbox_record",), "Mine", True)])

    def test_the_record_notes(self):
        self.assertEqual(self.folders.detect("project"), [])
        self.assertEqual(self.folders.notes("project"), [str(sbproject.NOT_FOUND) + detect.SET_FOLDER])
        local = self.base / "Local"
        (local / "Smithbox" / "Projects").mkdir(parents=True)
        (local / "Smithbox" / "Projects" / "x.json").write_text("[1]", encoding="utf-8")
        self.b.local = str(local)
        sbproject.forget()
        self.folders.detect("project")
        self.assertIn("does not recognise (1 file)", self.folders.notes("project")[0])
        self.record(A=(self.mk("Mods", "A"), self.mk("G"), False))
        (local / "Smithbox" / "Projects" / "x.json").write_text("[1]", encoding="utf-8")
        sbproject.forget()
        self.folders.detect("project")
        self.assertEqual(self.folders.notes("project"), ["1 more file not recognised"])

    def test_the_expansion_yes_and_no(self):
        """The ids are the owner's manifest's, shown as they are; never compared with a built-in id. A DLC app may
        not be the expansion (an artbook, a soundtrack), so with any listed, Yes and No are both offered and neither
        is proposed (the correctness review's C7)."""
        self.steam_install(dlc=(9000020,))
        got = self.folders.detect("expansion")
        self.assertEqual([(c.value, c.detail) for c in got],
                         [("yes", "Steam lists DLC app 9000020 as installed: Yes if it is the expansion"),
                          ("no", "No if it is not")])
        self.steam_install(dlc=(9000020, 9000030))
        self.assertEqual([c.detail for c in self.folders.detect("expansion")],
                         ["Steam lists DLC apps 9000020, 9000030 as installed: Yes if one of them is the expansion",
                          "No if none of them is"])
        self.steam_install(dlc=())
        self.assertEqual([c.value for c in self.folders.detect("expansion")], ["no"])
        self.b.reg.clear()
        self.assertEqual(self.folders.detect("expansion"), [])
        self.assertIn(detect.NO_MANIFEST, self.folders.notes("expansion"))

    def test_recent_and_merging(self):
        _, lib, game = self.steam_install()
        upper = str(game).upper() if os.name == "nt" else str(game)
        self.live.settings = with_values(Settings(), recent={"game_dir": (upper + os.sep,), "smithbox_dir": (),
                                                             "project_dir": ()})
        got = self.folders.detect("game")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].sources, ("steam_library", "recent"))

    def test_every_registry_read_comes_from_the_table(self):
        self.steam_install()
        for want in detect.WANTS:
            self.folders.detect(want)
        self.assertTrue(self.b.reads)
        self.assertTrue(set(self.b.reads) <= set(detect.REGISTRY.values()))

    def test_every_registry_value_call_in_the_code_takes_a_registry_entry(self):
        calls = 0
        for f in sorted((ROOT / "datapiler").glob("*.py")) + [ROOT / "datapiler.py"]:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                        and node.func.attr == "registry_value":
                    calls += 1
                    self.assertEqual(f.name, "detect.py", f.name)
                    self.assertEqual(len(node.args), 1, f.name)
                    a = node.args[0]
                    self.assertIsInstance(a, ast.Starred)
                    self.assertIsInstance(a.value, ast.Subscript)
                    self.assertEqual(ast.unparse(a.value.value), "REGISTRY")
        self.assertGreaterEqual(calls, 2)
        text = (ROOT / "datapiler" / "detect.py").read_text(encoding="utf-8")
        self.assertNotIn("MuiCache", text)                      # DP13: no record of programs started


class PrivacyTest(Base):
    def test_no_log_line_holds_a_path_and_candidates_are_masked(self):
        _, lib, game = self.steam_install()
        project = self.mk("Mods", "Secret project")
        self.record(**{"Invented Name": (project, game, True)})
        sb = self.mk("Tools", "SB", exe="Smithbox.Vulkan.exe")
        self.b.procs = [Proc("smithbox.vulkan.exe", str(sb / "Smithbox.Vulkan.exe"))]
        _, seq = logbook.lines_after(0, limit=0)
        for want in detect.WANTS:
            self.folders.detect(want)
        lines, _ = logbook.lines_after(seq)
        text = "\n".join(ln["msg"] for ln in lines)
        self.assertIn("game folder: 1 place (Smithbox's project record, Steam's library list)", text)
        self.assertIn("project: 1 place from Smithbox's project record, 1 open, 0 for another game, 0 not "
                      "recognised", text)
        self.assertIn("expansion: Steam's app manifest lists 1 DLC app installed", text)
        self.assertIn("Smithbox folder: 1 place (the running Smithbox)", text)
        for secret in (str(self.base), "Secret project", "Invented Name", "Library"):
            self.assertNotIn(secret, text)
        # a candidate that is not a setting reaches no line: the mask knows it as <FOUND>
        # (resolved: a temporary folder may come as an 8.3 short form, which the portable fake does not give)
        self.assertEqual(logbook.mask("in " + str(project.resolve()) + os.sep + "x"), "in <FOUND>" + os.sep + "x")
        self.assertEqual(logbook.mask(str(game.resolve())), "<FOUND>")

    def test_nothing_is_saved(self):
        self.steam_install()
        for want in detect.WANTS:
            self.folders.detect(want)
        self.assertEqual(self.live.settings, Settings())
        self.assertFalse((self.root / "settings.json").exists())


class StartTest(Base):
    def test_at_start_only_for_blank_or_missing_settings(self):
        _, lib, game = self.steam_install()
        asked = []
        real = self.folders.detect
        self.folders.detect = lambda want: asked.append(want) or real(want)
        self.folders.at_start()
        self.folders.wait()
        self.assertEqual(asked, ["smithbox", "game", "project", "expansion"])
        self.assertEqual(len(self.folders.found("game")), 1)
        asked.clear()
        self.folders.close()
        self.folders = detect.Folders(self.live)
        self.folders.detect = lambda want: asked.append(want) or real(want)
        sb = self.mk("SB", exe="Smithbox.Vulkan.exe")
        self.live.settings = Settings(game_dir=str(game), smithbox_dir=str(sb), project_dir=str(self.base / "gone"),
                                      expansion="no")
        self.folders.at_start()
        self.folders.wait()
        self.assertEqual(asked, ["project"])                    # a folder set and present is never second-guessed
        self.assertEqual(self.live.settings.project_dir, str(self.base / "gone"))


class WatchTest(Base):
    """DP15: Smithbox seen by its process at all times, whatever the Settings say."""

    def lines(self, seq):
        lines, _ = logbook.lines_after(seq)
        return [ln["msg"] for ln in lines if ln["src"] == "smithbox"]

    def test_seen_at_start_later_gone_and_two_at_once(self):
        sb = self.mk("Tools", "Smithbox 2.2.6", exe=["Smithbox.Vulkan.exe", "Smithbox.OpenGL.exe"])
        other = self.mk("Old", "SB", exe="Smithbox.exe")
        self.b.versions = {"smithbox.vulkan.exe": "2.2.6.0", "smithbox.exe": "2.0.0.0"}
        _, seq = logbook.lines_after(0, limit=0)
        self.b.procs = [Proc("smithbox.vulkan.exe", str(sb / "Smithbox.Vulkan.exe"))]
        w = smithbox.Watch(interval=60)
        self.assertTrue(w.check_once())                         # seen at start
        self.assertEqual([(r.name, r.build) for r in w.seen()], [("Smithbox.Vulkan.exe", "2.2.6.0")])
        self.assertFalse(w.check_once())
        self.b.procs = []
        self.assertTrue(w.check_once())                         # gone when it stops
        self.assertEqual(w.seen(), [])
        self.b.procs = [Proc("smithbox.exe", str(other / "Smithbox.exe")),
                        Proc("smithbox.vulkan.exe", str(sb / "Smithbox.Vulkan.exe"))]
        self.assertTrue(w.check_once())                         # two at once, both listed, none chosen
        self.assertEqual([r.name for r in w.seen()], ["Smithbox.Vulkan.exe", "Smithbox.exe"])
        self.b.fail = True
        self.assertTrue(w.check_once())
        self.assertIsNone(w.seen())
        msgs = self.lines(seq)
        self.assertEqual(msgs, ["Smithbox is running (Smithbox.Vulkan.exe)", "Smithbox stopped",
                                "Smithbox is running: 2 processes (Smithbox.Vulkan.exe, Smithbox.exe)",
                                "the process list could not be read, so whether Smithbox runs is not known"])
        self.assertFalse(any(str(self.base) in m or "2.2.6" in m for m in msgs))     # a log line names the event

    def test_the_watcher_thread_and_seen(self):
        sb = self.mk("SB", exe="Smithbox.Vulkan.exe")
        changes = []
        w = smithbox.start_watch(changes.append, interval=0.05)
        try:
            deadline = time.monotonic() + 5
            while not w.checked and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(smithbox.seen(), [])
            self.assertFalse(smithbox.running())
            self.b.procs = [Proc("smithbox.vulkan.exe", str(sb / "Smithbox.Vulkan.exe"))]   # starts later
            while not (changes and changes[-1]) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(smithbox.running())
            self.assertEqual(Path(smithbox.seen()[0].folder), sb)
        finally:
            smithbox.stop_watch()

    def test_the_running_smithbox_is_offered_whatever_the_settings_say(self):
        """Settings and Status offer the running Smithbox's folder as Detect's find, Detect pressed or not; nothing
        saved; and once Smithbox is seen, Detect goes on to the game and project folders still blank."""
        sb = self.mk("Tools", "SB", exe="Smithbox.Vulkan.exe")
        self.assertEqual(self.folders.found("smithbox"), [])
        self.b.procs = [Proc("smithbox.vulkan.exe", str(sb / "Smithbox.Vulkan.exe"))]
        got = self.folders.found("smithbox")
        self.assertEqual([(c.value, c.sources) for c in got], [(str(sb.resolve()), ("running_smithbox",))])
        self.live.settings = Settings(smithbox_dir=str(self.mk("Other", exe="Smithbox.exe")))
        self.assertEqual(len(self.folders.found("smithbox")), 1)
        self.assertEqual(logbook.mask(str(sb.resolve())), "<FOUND>")
        asked = []
        self.folders._spawn = lambda wants: asked.extend(wants)
        self.folders._smithbox_changed([object()])
        self.assertEqual(asked, [])                             # the first reading: at_start's Detect covers it
        self.folders._smithbox_changed([])
        self.folders._smithbox_changed([object()])
        self.assertEqual(asked, ["game", "project"])
        self.folders._smithbox_changed([object()])
        self.assertEqual(asked, ["game", "project"])            # once, when it starts


class ViewTest(Base):
    def test_a_candidates_view(self):
        _, lib, game = self.steam_install()
        project = self.mk("Mods", "P")
        self.record(Mine=(project, game, True))
        c = self.folders.detect("project")[0]
        v = detect.view("project", c, self.live.settings, self.root)
        self.assertEqual(set(v), {"path", "shown", "sources", "tags", "in_use", "check", "marked", "name"})
        self.assertEqual((v["name"], v["marked"], v["in_use"]), ("Mine", True, False))
        self.assertEqual(v["check"]["ok"], "warn")              # the game folder is not set yet
        s = Settings(project_dir=str(project), game_dir=str(game), mask_paths=True)
        v = detect.view("project", c, s, self.root)
        self.assertNotIn("name", v)                             # never sent with the mask on
        self.assertEqual((v["shown"], v["in_use"]), ("<FOUND>", True))
        e = self.folders.detect("expansion")[0]
        v = detect.view("expansion", e, Settings(expansion="yes"), self.root)
        self.assertEqual(v, {"value": "yes", "sources": ["steam_manifest"], "tags": ["Steam's app manifest"],
                             "in_use": True, "detail": "Steam lists DLC app 9000020 as installed: Yes if it is the "
                                                       "expansion"})


if __name__ == "__main__":
    unittest.main()
