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


class StatusTest(unittest.TestCase):
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
        with self.assertRaises(status.ProvenanceMissing) as cm:
            self.st.provenance()
        self.assertIn("expansion", str(cm.exception))
        (self.game / "invented-marker.bin").write_bytes(b"")
        with mock.patch.object(game, "EXPANSION_MARKERS", ("invented-marker.bin",)):
            p = self.st.provenance()
            self.assertEqual(list(p), ["game_version", "regulation_sha256", "expansion", "language", "smithbox_build",
                                       "datapiler", "date"])
            self.assertEqual(p["game_version"], "1.16.0.0")
            self.assertIs(p["expansion"], True)
            self.assertEqual(p["date"], time.strftime("%Y-%m-%d"))
            self.b.versions = {}
            game._version_cache.clear()
            with self.assertRaises(status.ProvenanceMissing) as cm:
                self.st.provenance()
            # found by the end-to-end run on Linux: the folder was set, only the version resource was unreadable
            self.assertEqual(str(cm.exception), "the game's version is not known - eldenring.exe's version resource "
                                                "could not be read (it is read on Windows only)")
            self.cfg = Settings(smithbox_dir=self.cfg.smithbox_dir, project_dir=self.cfg.project_dir)
            with self.assertRaises(status.ProvenanceMissing) as cm:
                self.st.provenance()
            self.assertEqual(str(cm.exception), "the game's version is not known - set the game folder")

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


if __name__ == "__main__":
    unittest.main()
