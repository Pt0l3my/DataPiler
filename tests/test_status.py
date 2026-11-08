import _repo  # noqa: F401

import builtins
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from datapiler import events, fileio, game, logbook, smithbox, status, winapi
from dataclasses import replace

from datapiler.settings import Settings
from datapiler.winapi import Proc


class FakeBackend(winapi.PortableBackend):
    def __init__(self):
        self.procs = []
        self.fail = False
        self.versions = {}
        self.version_calls = 0

    def processes(self):
        if self.fail:
            raise OSError(5, "refused")
        return list(self.procs)

    def file_version(self, path):
        self.version_calls += 1
        return self.versions.get(os.path.basename(path).lower())


class FakeLink:
    def __init__(self, state="off"):
        self.state = state

    def stats(self):
        return {"calls": 3, "last_call": "08:41:58", "last_methods": ["ListParamRows", "GetParamRows"]}

    def would_call(self):
        return [{"method": "ListParams", "for": "the names of the params"}]


class StatusBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.game = root / "Game"
        self.game.mkdir()
        (self.game / "eldenring.exe").write_bytes(b"")
        (self.game / "regulation.bin").write_bytes(b"invented regulation bytes " * 40)
        self.sb = root / "Smithbox"
        self.sb.mkdir()
        (self.sb / "Smithbox.exe").write_bytes(b"")
        self.project = root / "Project"
        self.project.mkdir()
        self.appdata = root / "AppData"
        (self.appdata / "Smithbox" / "Configuration").mkdir(parents=True)
        self.startup = self.appdata / "Smithbox" / "Configuration" / "Startup.json"
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.appdata)})
        self.env.start()
        self.b = FakeBackend()
        self.b.versions = {"eldenring.exe": "1.16.0.0", "smithbox.exe": "2.2.6.0"}
        self.use = winapi.use(self.b)
        self.use.__enter__()
        self.cfg = Settings(game_dir=str(self.game), smithbox_dir=str(self.sb), project_dir=str(self.project))
        self.link = FakeLink()
        self.port = True
        self.st = status.Status(lambda: self.cfg, lambda: self.link, lambda: self.port)
        game._version_cache.clear()
        game._sha_cache.clear()
        smithbox._build_cache.clear()

    def tearDown(self):
        self.st.close()
        self.use.__exit__(None, None, None)
        self.env.stop()
        self.tmp.cleanup()

    def switch(self, value):
        if value == "missing-file":
            if self.startup.exists():
                self.startup.unlink()
        elif value == "broken":
            self.startup.write_text("{broken", encoding="utf-8")
        elif value == "missing-key":
            self.startup.write_text(json.dumps({"Other": True}), encoding="utf-8")
        else:
            self.startup.write_text(json.dumps({"System_Enable_Soapstone_Server": value}), encoding="utf-8")

    def card(self, kind, cid):
        return next(c for c in self.st.cards()[kind] if c["id"] == cid)


class StatusTest(StatusBase):
    def test_switch_states(self):
        for value, ok in ((True, True), (False, False), ("missing-file", None), ("broken", None), ("missing-key", None)):
            self.switch(value)
            self.assertEqual(smithbox.read_switch(smithbox.startup_json()), ok if ok is not None else None, value)
            self.assertEqual(self.card("smithbox", "switch")["ok"], ok, value)

    def test_read_switch_never_opens_for_writing(self):
        self.switch(True)
        before = (self.startup.read_bytes(), self.startup.stat().st_mtime_ns)
        modes = []
        real_open = builtins.open
        real_os_open = os.open

        def spy_open(file, mode="r", *a, **kw):
            modes.append(mode)
            return real_open(file, mode, *a, **kw)

        def spy_os_open(path, flags, *a, **kw):
            modes.append(flags)
            return real_os_open(path, flags, *a, **kw)

        with mock.patch("builtins.open", spy_open), mock.patch("os.open", spy_os_open):
            self.assertTrue(smithbox.read_switch(self.startup))
        self.assertTrue(modes)
        for m in modes:
            if isinstance(m, str):
                self.assertNotRegex(m, "[wax+]")
            else:
                self.assertEqual(m & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND), 0)
        self.assertEqual((self.startup.read_bytes(), self.startup.stat().st_mtime_ns), before)

    def test_s7_by_name(self):
        self.assertFalse(self.st.game_running().running)
        for name in ("eldenring.exe", "START_PROTECTED_GAME.EXE"):
            self.b.procs = [Proc("explorer.exe", None), Proc(name.lower(), None)]
            g = self.st.game_running()
            self.assertTrue(g.running)
            self.assertIn("is running", g.why)
        self.assertEqual(self.st.pills()["game"], "running")

    def test_s7_by_path_inside_the_game_folder(self):
        self.b.procs = [Proc("helper.exe", str(self.game / "sub" / "helper.exe"))]
        g = self.st.game_running()
        self.assertTrue(g.running)
        self.assertEqual(g.why, "a program from the game's folder is running")
        self.b.procs = [Proc("helper.exe", str(self.game) + "2" + os.sep + "helper.exe")]
        self.assertFalse(self.st.game_running().running)

    def test_s7_unreadable_list_counts_as_running(self):
        self.b.fail = True
        g = self.st.game_running()
        self.assertTrue(g.running)
        self.assertEqual(g.why, game.UNREADABLE)
        self.assertEqual(self.st.pills()["game"], "unknown")
        self.assertIsNotNone(self.st.block_line())
        self.assertIsNone(smithbox.running(str(self.sb)))

    def test_hash_once_until_the_file_changes(self):
        reg = self.game / "regulation.bin"
        with mock.patch.object(fileio, "sha256_file", wraps=fileio.sha256_file) as spy:
            a = game.regulation_sha256(str(self.game))
            b = game.regulation_sha256(str(self.game))
            self.assertEqual(a, b)
            self.assertEqual(spy.call_count, 1)
            reg.write_bytes(b"other invented bytes, a different length")
            os.utime(reg, ns=(time.time_ns(), time.time_ns() + 10 ** 9))
            c = game.regulation_sha256(str(self.game))
            self.assertNotEqual(a, c)
            self.assertEqual(spy.call_count, 2)
        self.assertEqual(c, fileio.sha256_file(reg))

    def test_version_cached(self):
        self.assertEqual(game.version(str(self.game)), "1.16.0.0")
        self.assertEqual(game.version(str(self.game)), "1.16.0.0")
        self.assertEqual(self.b.version_calls, 1)

    def test_provenance(self):
        # P2 (settled S21): the owner's statement in Settings, unset at first; the marker files never decide
        (self.game / "invented-marker.bin").write_bytes(b"")
        with mock.patch.object(game, "EXPANSION_MARKERS", ("invented-marker.bin",)):
            with self.assertRaises(status.ProvenanceMissing) as cm:
                self.st.provenance()
        self.assertEqual(str(cm.exception), status.EXPANSION_UNSET)
        self.assertIn("Settings", str(cm.exception))
        self.cfg = replace(self.cfg, expansion="no")
        with mock.patch.object(game, "EXPANSION_MARKERS", ("invented-marker.bin",)):
            p = self.st.provenance()
            self.assertIs(p["expansion"], False)        # what the owner said, though the marker file is there
        self.cfg = replace(self.cfg, expansion="yes")
        p = self.st.provenance()
        self.assertEqual(list(p), ["game_version", "regulation_sha256", "expansion", "expansion_source", "language",
                                   "smithbox_build", "datapiler", "date"])
        self.assertEqual(p["game_version"], "1.16.0.0")
        self.assertIs(p["expansion"], True)
        self.assertEqual(p["expansion_source"], "owner")
        self.assertEqual(p["date"], time.strftime("%Y-%m-%d"))
        self.b.versions = {}
        game._version_cache.clear()
        with self.assertRaises(status.ProvenanceMissing) as cm:
            self.st.provenance()
        # found by the end-to-end run on Linux: the folder was set, only the version resource was unreadable
        self.assertEqual(str(cm.exception), "the game's version is not known - eldenring.exe's version resource "
                                            "could not be read (it is read on Windows only)")
        self.cfg = Settings(smithbox_dir=self.cfg.smithbox_dir, project_dir=self.cfg.project_dir, expansion="yes")
        with self.assertRaises(status.ProvenanceMissing) as cm:
            self.st.provenance()
        self.assertEqual(str(cm.exception), "the game's version is not known - set the game folder")

    def test_the_expansion_check_on_the_card(self):
        c = self.card("game", "expansion")
        self.assertIs(c["ok"], False)
        self.assertIn("not stated yet", c["text"])
        self.assertIn("Settings", c["fix"])
        self.assertNotIn("hint", c["fix"].lower())          # no marker file is confirmed: no hint
        self.cfg = replace(self.cfg, expansion="yes")
        c = self.card("game", "expansion")
        self.assertEqual((c["ok"], c["text"], c["fix"]), (True, "Installed, as stated in Settings", None))
        # a file check, once its markers are set, adds a hint and never decides
        (self.game / "invented-marker.bin").write_bytes(b"")
        with mock.patch.object(game, "EXPANSION_MARKERS", ("invented-marker.bin", "invented-other.bin")):
            c = self.card("game", "expansion")
            self.assertEqual((c["ok"], c["text"]), (True, "Installed, as stated in Settings"))
            self.assertIn("A hint only: the expansion's files are not present in <GAME>", c["fix"])
            self.assertNotIn(str(self.game), c["fix"])
            self.assertIn("Check what Settings says", c["fix"])
            self.cfg = replace(self.cfg, expansion="no")
            c = self.card("game", "expansion")
            self.assertEqual((c["ok"], c["text"], c["fix"]), (True, "Not installed, as stated in Settings",
                                                               "A hint only: the expansion's files are not present in "
                                                               "<GAME>."))

    def test_project_ok(self):
        self.assertEqual(self.st.project_ok()[0], True)
        inner = self.game / "proj"
        inner.mkdir()
        self.cfg = Settings(game_dir=str(self.game), project_dir=str(inner))
        ok, why = self.st.project_ok()
        self.assertFalse(ok)
        self.assertIn("inside the game's folder", why)
        self.cfg = Settings(game_dir=str(self.game), project_dir=str(self.game))
        self.assertIn("is the game's folder", self.st.project_ok()[1])
        self.cfg = Settings(game_dir=str(self.game))
        self.assertFalse(self.st.project_ok()[0])
        self.assertFalse(self.card("project", "outside_game")["ok"])

    def test_cards_shape_and_placeholders(self):
        self.switch(True)
        cards = self.st.cards()
        self.assertEqual([c["id"] for c in cards["smithbox"]], ["installed", "build", "running", "switch", "port",
                                                                "project"])
        self.assertEqual([c["id"] for c in cards["game"]], ["folder", "version", "expansion", "running", "regulation"])
        self.assertEqual([c["id"] for c in cards["project"]], ["outside_game", "open_project"])
        # DP4's check reads the folder typed in Settings; which project Smithbox has open is not known (P1).
        self.assertIn("set in Settings", self.card("project", "outside_game")["text"])
        self.assertIsNone(self.card("project", "open_project")["ok"])
        self.assertIn("cannot yet see which project Smithbox has open", self.card("smithbox", "project")["fix"])
        self.assertIn("set in Settings", self.card("smithbox", "project")["text"])
        for kind in ("smithbox", "game", "project"):
            for c in cards[kind]:
                self.assertEqual(set(c), {"id", "ok", "text", "fix", "detail"})
                for k in ("text", "fix"):
                    self.assertNotIn(self.tmp.name, c[k] or "")
        self.assertEqual(self.card("smithbox", "installed")["detail"], str(self.sb))
        self.assertIn("<SMITHBOX>", self.card("smithbox", "installed")["text"])
        self.assertEqual(set(cards["link"]), {"state", "calls", "last_call", "last_methods", "would_call", "after"})
        self.assertEqual(cards["link"]["calls"], 3)

    def test_port_check_cached(self):
        calls = []
        st = status.Status(lambda: self.cfg, lambda: None, lambda: calls.append(1) or False)
        try:
            st.cards()
            st.cards()
            self.assertEqual(len(calls), 1)
        finally:
            st.close()

    def test_s9_line_after_the_link_went_off(self):
        self.switch(True)
        self.assertIsNone(self.st.cards()["link"]["after"])
        events.emit("link.state", state=logbook.own("on"), why=None)
        self.link.state = "off"
        self.assertIn("System_Enable_Soapstone_Server", self.st.cards()["link"]["after"])
        self.switch(False)
        self.assertIsNone(self.st.cards()["link"]["after"])

    def test_pills(self):
        self.assertEqual(self.st.pills(), {"smithbox": "not_running", "game": "closed", "link": "off"})
        self.b.procs = [Proc("smithbox.exe", None)]
        self.assertEqual(self.st.pills()["smithbox"], "running")
        self.cfg = Settings()
        self.b.procs = []
        self.assertEqual(self.st.pills()["smithbox"], "not_found")


class FakeFound:
    def __init__(self, cands=None):
        self.cands = cands or {}

    def found(self, want):
        return list(self.cands.get(want, []))


class Status02Test(StatusBase):
    """Build plan 0.2 §5.8 and DP15: Found n places, the project rules of S32, the open project's lead, the running
    Smithbox by its exe, and Smithbox*.exe."""

    def cand(self, path):
        from datapiler import detect
        return detect.Candidate(str(path), ("recent",), None, False, None)

    def test_found_places_when_a_folder_is_blank_or_missing(self):
        from datapiler.settings import with_values
        self.st.attach(folders=FakeFound({"smithbox": [self.cand(self.sb)], "game": [self.cand(self.game),
                                                                                       self.cand(self.sb)]}))
        self.assertTrue(self.card("smithbox", "installed")["ok"])     # set and present: never second-guessed
        self.cfg = with_values(self.cfg, smithbox_dir="", game_dir=str(Path(self.tmp.name) / "gone"))
        c = self.card("smithbox", "installed")
        self.assertEqual((c["ok"], c["text"], c["fix"]), ("warn", "Found 1 place - confirm it in Settings",
                                                          "Open Settings and press Use."))
        self.assertEqual(c["use"], {"key": "smithbox_dir", "path": str(self.sb), "shown": str(self.sb)})
        g = self.card("game", "folder")
        self.assertEqual((g["ok"], g["text"]), ("warn", "Found 2 places - confirm them in Settings"))
        self.assertNotIn("use", g)                               # two: the owner chooses in Settings
        self.assertEqual(self.cfg.smithbox_dir, "")

    def test_the_project_rules_of_0_2(self):
        root = Path(self.tmp.name) / "DataPiler"
        (root / "projects").mkdir(parents=True)
        self.st.attach(root=root)
        for project, words in ((root, "DataPiler's own folder"), (root / "projects", "inside DataPiler's folder"),
                               (Path(self.tmp.name), "holds the game's folder")):
            with self.subTest(project=project.name):
                self.cfg = Settings(game_dir=str(self.game), project_dir=str(project))
                ok, why = self.st.project_ok()
                self.assertFalse(ok)
                self.assertIn(words, why)
                self.assertFalse(self.card("project", "outside_game")["ok"])

    def test_the_open_project_from_smithboxs_record(self):
        """A lead (O48): the record's one marked Elden Ring project."""
        from datapiler import sbproject
        local = Path(self.tmp.name) / "Local"
        folder = local / "Smithbox" / "Projects"
        folder.mkdir(parents=True)

        class WithLocal(FakeBackend):
            def local_appdata(self):
                return str(local)

        def mark(project):
            (folder / "p.json").write_text(json.dumps({"ProjectName": "Invented", "ProjectPath": str(project),
                                                       "DataPath": str(self.game), "ProjectType": 8,
                                                       "AutoSelect": True}), encoding="utf-8")
            sbproject.forget()

        b = WithLocal()
        b.procs, b.versions = self.b.procs, self.b.versions
        with winapi.use(b):
            c = self.card("project", "open_project")
            self.assertEqual((c["ok"], c["text"]), (None, "Which project Smithbox has open is not known yet"))
            mark(self.project)
            c = self.card("project", "open_project")
            self.assertEqual((c["ok"], c["text"]), (True, "Smithbox's record marks <PROJECT> as the project it opens"))
            self.assertIn("lead", c["fix"])
            other = Path(self.tmp.name) / "Other"
            other.mkdir()
            mark(other)
            c = self.card("project", "open_project")
            self.assertEqual((c["ok"], c["text"], c["detail"]), ("warn", "Smithbox's record marks another project to "
                                                                         "open", str(other)))
        sbproject.forget()

    def test_the_running_smithbox_by_its_exe(self):
        """Smithbox.Vulkan.exe and Smithbox.OpenGL.exe in one folder is the normal case; Status names the one
        running, with its build, and a second Smithbox elsewhere is listed too."""
        (self.sb / "Smithbox.exe").unlink()
        (self.sb / "Smithbox.Vulkan.exe").write_bytes(b"")
        (self.sb / "Smithbox.OpenGL.exe").write_bytes(b"")
        self.b.versions = {"eldenring.exe": "1.16.0.0", "smithbox.vulkan.exe": "2.2.6.0",
                           "smithbox.opengl.exe": "2.2.6.0"}
        self.assertTrue(self.card("smithbox", "installed")["ok"])
        self.assertEqual(self.card("smithbox", "build")["text"], "Build 2.2.6.0")
        self.assertEqual(self.card("smithbox", "running")["text"], "Not running")
        self.b.procs = [Proc("smithbox.vulkan.exe", str(self.sb / "Smithbox.Vulkan.exe"))]
        c = self.card("smithbox", "running")
        self.assertEqual((c["ok"], c["text"], c["detail"]), (True, "Running: Smithbox.Vulkan.exe · build 2.2.6.0",
                                                             str(self.sb)))
        self.assertEqual(self.st.pills()["smithbox"], "running")
        other = Path(self.tmp.name) / "Smithbox-old"
        other.mkdir()
        (other / "Smithbox.exe").write_bytes(b"")
        self.b.procs.append(Proc("smithbox.exe", str(other / "Smithbox.exe")))
        c = self.card("smithbox", "running")
        self.assertEqual(c["text"], "Running: 2 Smithbox processes")
        self.assertEqual(c["fix"], "Smithbox.Vulkan.exe · build 2.2.6.0; Smithbox.exe")
        e = self.card("smithbox", "elsewhere")
        self.assertEqual((e["ok"], e["detail"]), ("warn", str(other)))
        self.assertEqual(e["use"]["path"], str(other))
        # the Settings folder blank: the pill still says running (whatever the Settings say)
        self.cfg = Settings(game_dir=str(self.game))
        self.assertEqual(self.st.pills()["smithbox"], "running")

    def test_builds_that_differ_and_the_provenance(self):
        (self.sb / "Smithbox.exe").unlink()
        (self.sb / "Smithbox.Vulkan.exe").write_bytes(b"")
        (self.sb / "Smithbox.OpenGL.exe").write_bytes(b"")
        self.b.versions = {"eldenring.exe": "1.16.0.0", "smithbox.vulkan.exe": "2.2.6.0",
                           "smithbox.opengl.exe": "2.2.5.0"}
        self.cfg = Settings(game_dir=str(self.game), smithbox_dir=str(self.sb), project_dir=str(self.project),
                            expansion="no")
        self.assertEqual(self.card("smithbox", "build")["ok"], "warn")
        with self.assertRaises(status.ProvenanceMissing) as cm:
            self.st.provenance()
        self.assertIn("builds differ", str(cm.exception))
        self.b.procs = [Proc("smithbox.opengl.exe", str(self.sb / "Smithbox.OpenGL.exe"))]
        self.assertEqual(self.st.provenance()["smithbox_build"], "2.2.5.0")      # the running one's
        self.b.procs = []
        for f in self.sb.iterdir():
            f.unlink()
        with self.assertRaises(status.ProvenanceMissing) as cm:
            self.st.provenance()
        self.assertIn("Smithbox*.exe", str(cm.exception))
        self.assertIn("Smithbox's exe is not in <SMITHBOX>", self.card("smithbox", "installed")["text"])

    def test_the_provenance_has_the_running_smithboxs_build(self):
        """Found by the correctness review (C1): the build of the folder in Settings was recorded while another
        Smithbox, from another folder, served the link."""
        self.b.versions = {"eldenring.exe": "1.16.0.0", "smithbox.exe": "2.2.5.0", "smithbox.vulkan.exe": "2.2.6.0"}
        new = Path(self.tmp.name) / "Smithbox 2.2.6"
        new.mkdir()
        (new / "Smithbox.Vulkan.exe").write_bytes(b"")
        self.cfg = Settings(game_dir=str(self.game), smithbox_dir=str(self.sb), project_dir=str(self.project),
                            expansion="no")
        self.assertEqual(self.st.provenance()["smithbox_build"], "2.2.5.0")      # none runs: the folder's
        self.b.procs = [Proc("smithbox.vulkan.exe", str(new / "Smithbox.Vulkan.exe"))]
        self.assertEqual(self.st.provenance()["smithbox_build"], "2.2.6.0")      # the running one's, elsewhere
        self.b.procs.append(Proc("smithbox.exe", str(self.sb / "Smithbox.exe")))
        with self.assertRaises(status.ProvenanceMissing) as cm:
            self.st.provenance()
        self.assertIn("different builds are running", str(cm.exception))
        self.b.procs = [Proc("smithbox.exe", None)]                              # its path could not be read
        with self.assertRaises(status.ProvenanceMissing) as cm:
            self.st.provenance()
        self.assertIn("the running Smithbox exe's version resource could not be read", str(cm.exception))

    def test_a_running_smithbox_elsewhere_is_masked_without_detect(self):
        """Found by the reviews (SEC-3, C4): with Mask paths on, Status drew the folder of a Smithbox running from
        another folder in full until Settings or Detect had taught it to the mask."""
        from datapiler import api, logbook
        other = Path(self.tmp.name) / "OtherTools"
        other.mkdir()
        (other / "Smithbox.Vulkan.exe").write_bytes(b"")
        self.b.procs = [Proc("smithbox.vulkan.exe", str(other / "Smithbox.Vulkan.exe"))]
        self.cfg = Settings(game_dir=str(self.game), smithbox_dir=str(self.sb), project_dir=str(self.project),
                            mask_paths=True)
        logbook.set_masks(folders={"<SMITHBOX>": str(self.sb), "<GAME>": str(self.game)}, home=None, user=None,
                          pc=None)
        try:
            cards = self.st.cards()
            api._mask_cards(cards)
            seen = {c["id"]: c for c in cards["smithbox"]}
            self.assertEqual(seen["running"]["detail"], "<FOUND>")
            self.assertEqual(seen["elsewhere"]["detail"], "<FOUND>")
            self.assertEqual(seen["elsewhere"]["use"]["shown"], "<FOUND>")
            for c in cards["smithbox"]:                         # drawn: every text but Use's value to save
                drawn = {k: v for k, v in c.items() if k != "use"}
                drawn["shown"] = (c.get("use") or {}).get("shown")
                self.assertNotIn("OtherTools", json.dumps(drawn), c["id"])
        finally:
            logbook.set_masks(folders={}, home=None, user=None, pc=None)

    def test_the_watcher_teaches_the_mask(self):
        from datapiler import logbook
        other = Path(self.tmp.name) / "Watched"
        w = smithbox.Watch(read=lambda: [smithbox.Running("Smithbox.Vulkan.exe", str(other / "Smithbox.Vulkan.exe"),
                                                            str(other), "2.2.6.0")])
        self.assertEqual(logbook.mask(str(other) + "/x"), str(other) + "/x")
        w.check_once()
        self.assertEqual(logbook.mask(str(other) + "/x"), "<FOUND>/x")


if __name__ == "__main__":
    unittest.main()
