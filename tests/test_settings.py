import _repo  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path

from datapiler import settings, winapi
from datapiler.settings import Settings, SettingsError


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "DataPiler"           # DataPiler's own folder: the project may not be in it (S32)
        self.root.mkdir()
        self.game = self.base / "Game"
        self.game.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, **kw):
        return settings.check(kw, root=self.root)

    def refused(self, field, **kw):
        with self.assertRaises(SettingsError) as cm:
            self.check(**kw)
        self.assertEqual(cm.exception.field, field)
        self.assertTrue(cm.exception.rule)
        return cm.exception

    def test_defaults(self):
        s = self.check()
        self.assertEqual(s, Settings())
        self.assertEqual(s.as_dict(), {"smithbox_dir": "", "game_dir": "", "project_dir": "", "workspace_dir": "workspace",
                                       "share_dir": "share", "language": "engus", "expansion": "", "port": 0,
                                       "log_max_mb": 2, "log_keep": 5, "mask_paths": False, "map_opengl": True,
                                       "work_cores": 0, "work_memory_mb": 0, "link_auto": False, "devkit_dir": "",
                                       "recent": {"smithbox_dir": [], "game_dir": [], "project_dir": []}})

    def test_dp29_the_caps_for_image_steps(self):
        """S83: blank (0) is automatic; otherwise 1 to 256 cores and 256 MB to 1 TB."""
        self.assertEqual((self.check(work_cores=6).work_cores, self.check(work_memory_mb=2048).work_memory_mb), (6, 2048))
        for key, bad in (("work_cores", 257), ("work_cores", -1), ("work_cores", "4"), ("work_cores", True),
                         ("work_memory_mb", 100), ("work_memory_mb", 2 ** 21)):
            with self.subTest(key=key, bad=bad), self.assertRaises(SettingsError) as cm:
                self.check(**{key: bad})
            self.assertEqual(cm.exception.field, key)
        with self.assertRaises(SettingsError) as cm:
            self.check(work_cores=300)
        self.assertIn("blank (automatic)", cm.exception.rule)

    def test_the_expansion_is_the_owners_statement(self):
        """P2 (settled S21): yes, no, or not stated yet (blank, at first); nothing else."""
        self.assertEqual(self.check().expansion, "")
        self.assertEqual(self.check(expansion="yes").expansion, "yes")
        self.assertEqual(self.check(expansion="no").expansion, "no")
        for bad in ("Yes", "true", True, None, 1, "maybe"):
            with self.subTest(bad=bad):
                self.refused("expansion", expansion=bad)

    def test_unknown_key_refused(self):
        self.refused("colour", colour="red")
        self.refused("format", format="something-else/1")
        self.assertEqual(self.check(format=settings.FORMAT), Settings())

    def test_ranges(self):
        self.refused("port", port=80)
        self.refused("port", port=70000)
        self.refused("port", port=True)
        self.refused("port", port="8080")
        self.assertEqual(self.check(port=0).port, 0)
        self.assertEqual(self.check(port=8831).port, 8831)
        self.refused("log_max_mb", log_max_mb=0)
        self.refused("log_max_mb", log_max_mb=51)
        self.assertEqual(self.check(log_max_mb=50).log_max_mb, 50)
        self.refused("log_keep", log_keep=0)
        self.refused("log_keep", log_keep=1)        # every file counts, datapiler.log among them: one backup at least
        self.refused("log_keep", log_keep=21)
        self.assertEqual(self.check(log_keep=2).log_keep, 2)
        self.refused("language", language="EN")
        self.refused("language", language="e")
        self.refused("language", language="engusxxxx")
        self.assertEqual(self.check(language="jpnjp").language, "jpnjp")
        self.refused("game_dir", game_dir="relative/folder")
        self.refused("game_dir", game_dir=str(self.game) + "\x07x")
        self.refused("workspace_dir", workspace_dir="")
        self.refused("smithbox_dir", smithbox_dir=5)

    def test_project_inside_the_game_refused(self):
        inner = self.game / "mod"
        inner.mkdir()
        e = self.refused("project_dir", game_dir=str(self.game), project_dir=str(inner))
        self.assertIn("outside the game's folder", e.rule)
        self.refused("project_dir", game_dir=str(self.game), project_dir=str(self.game))
        sibling = self.base / "Game2"
        sibling.mkdir()
        self.assertEqual(self.check(game_dir=str(self.game), project_dir=str(sibling)).project_dir, str(sibling))

    def test_the_project_rules_of_0_2(self):
        """S32: not a folder that holds the game's folder, not DataPiler's folder nor inside it."""
        e = self.refused("project_dir", game_dir=str(self.game), project_dir=str(self.base))
        self.assertIn("hold the game's folder", e.rule)
        for inner in (self.root, self.root / "projects"):
            with self.subTest(inner=inner.name):
                e = self.refused("project_dir", project_dir=str(inner))
                self.assertIn("outside DataPiler's folder", e.rule)
        self.assertIsNone(settings.project_refusal("", str(self.game), self.root))
        self.assertIsNone(settings.project_refusal(str(self.base / "Mod"), "", self.root))

    def test_mask_paths(self):
        """DP14: off by default, on or off only."""
        self.assertFalse(self.check().mask_paths)
        self.assertTrue(self.check(mask_paths=True).mask_paths)
        for bad in ("yes", 1, None):
            with self.subTest(bad=bad):
                self.refused("mask_paths", mask_paths=bad)

    def test_recent_kept_by_the_app_and_capped(self):
        """S34: five a folder, newest first, no repeats (case-folded); the old value kept behind the new one."""
        folders = [str(self.base / ("F%d" % i)) for i in range(7)]
        s = Settings(game_dir=folders[0])
        for f in folders[1:]:
            s = settings.with_recent(s, settings.with_values(s, game_dir=f))
        self.assertEqual(list(s.recent["game_dir"]), folders[6:1:-1])
        self.assertEqual(s.recent["project_dir"], ())
        again = settings.with_recent(s, settings.with_values(s, game_dir=folders[3].upper()
                                                             if folders[3].upper() != folders[3] else folders[3]))
        self.assertEqual(len(again.recent["game_dir"]), 5)
        self.assertEqual(len({x.casefold() for x in again.recent["game_dir"]}), 5)
        # unchanged values add nothing; blank values are never kept
        self.assertEqual(settings.with_recent(s, s).recent, s.recent)
        blank = settings.with_recent(s, settings.with_values(s, game_dir=""))
        self.assertNotIn("", blank.recent["game_dir"])
        self.assertEqual(settings.forget_recent(s, "game_dir").recent["game_dir"], ())
        # as the file holds it: lists, checked, bad entries dropped, never an error
        got = self.check(recent={"game_dir": [folders[1], "relative", 5, folders[1], folders[2]], "other": [1]})
        self.assertEqual(got.recent["game_dir"], (folders[1], folders[2]))
        self.refused("recent", recent=["not", "an", "object"])
        f = self.root / "settings.json"
        settings.save(f, s)
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["recent"]["game_dir"], folders[6:1:-1])
        self.assertEqual(settings.load(f, root=self.root)[0], s)

    def test_load_drops_a_key_it_does_not_know_with_its_name(self):
        """S36: a version rolled back to keeps the owner's folders; the line names the key (or "(key)")."""
        f = self.root / "settings.json"
        f.write_text(json.dumps({"format": settings.FORMAT, "game_dir": str(self.game), "update_channel": "x",
                                 "Bad Key!": 1}), encoding="utf-8")
        s, problems = settings.load(f, root=self.root)
        self.assertEqual(s.game_dir, str(self.game))
        text = " | ".join(problems)
        self.assertIn("update_channel is not a setting this DataPiler knows", text)
        self.assertIn("(key) is not a setting this DataPiler knows", text)
        self.assertNotIn("Bad Key", text)
        # a save from the page still refuses an unknown key
        self.refused("update_channel", update_channel="x")

    def test_workspace_and_share_rules(self):
        self.refused("workspace_dir", game_dir=str(self.game), workspace_dir=str(self.game / "ws"))
        sb = self.base / "Smithbox"
        self.refused("share_dir", smithbox_dir=str(sb), share_dir=str(sb / "share"))
        self.refused("share_dir", workspace_dir="workspace", share_dir="workspace/share")
        self.refused("workspace_dir", workspace_dir="share/ws", share_dir="share")
        self.assertEqual(self.check(workspace_dir="ws", share_dir="out").share_dir, "out")

    def test_s98_the_devkit_folder(self):
        """DP36: blank, or a full path on this PC, from which a job's probe_exe runs EldenNet's devkit tool."""
        self.assertEqual(self.check().devkit_dir, "")
        kit = str(self.base / "Devkit")
        self.assertEqual(self.check(devkit_dir=kit).devkit_dir, kit)
        e = self.refused("devkit_dir", devkit_dir="devkit")
        self.assertIn("full folder path", e.rule)
        for folder in ("\\\\nas.invalid\\share\\kit", "//nas.invalid/share/kit"):
            with self.subTest(folder=folder):
                self.refused("devkit_dir", devkit_dir=folder)
        e = self.refused("devkit_dir", devkit_dir="//nas.invalid/share/kit")
        self.assertIn("on this PC", e.rule)

    def test_the_workspace_stays_on_this_pc(self):
        """It holds the game's text (design §1): never a UNC path or a mapped network drive."""
        for folder in ("\\\\nas.invalid\\share\\ws", "//nas.invalid/share/ws", "\\\\?\\UNC\\nas.invalid\\ws",
                       "  \\\\nas.invalid\\ws"):
            with self.subTest(folder=folder):
                e = self.refused("workspace_dir", workspace_dir=folder)
                self.assertIn("on this PC", e.rule)

        class Remote(winapi.PortableBackend):
            def drive_is_remote(self, path):
                return True

        with winapi.use(Remote()):
            self.refused("workspace_dir", workspace_dir=str(self.root / "ws"))
            # A relative one sits in DataPiler's own folder: refusing it would refuse the default (the start warns).
            self.assertEqual(self.check(workspace_dir="ws").workspace_dir, "ws")
            self.assertEqual(self.check(), Settings())
        self.assertEqual(self.check(workspace_dir=str(self.root / "ws")).workspace_dir, str(self.root / "ws"))

    def test_round_trip(self):
        f = self.root / "settings.json"
        s = self.check(game_dir=str(self.game), language="frafr", port=8831, log_keep=3)
        settings.save(f, s)
        doc = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(doc["format"], settings.FORMAT)
        back, problems = settings.load(f, root=self.root)
        self.assertEqual(back, s)
        self.assertEqual(problems, [])

    def test_load_missing_and_broken(self):
        f = self.root / "settings.json"
        self.assertEqual(settings.load(f, root=self.root), (Settings(), []))
        f.write_text("{not json", encoding="utf-8")
        s, problems = settings.load(f, root=self.root)
        self.assertEqual(s, Settings())
        self.assertEqual(len(problems), 1)
        f.write_text(json.dumps({"port": 5, "log_keep": 3, "extra": 1}), encoding="utf-8")
        s, problems = settings.load(f, root=self.root)
        self.assertEqual((s.port, s.log_keep), (0, 3))
        self.assertEqual(len(problems), 2)

    def test_session_never_saved(self):
        f = self.root / "settings.json"
        session = settings.Session()
        self.assertEqual((session.link, session.debug, session.link_off_by_owner), (False, False, False))
        session.link = session.debug = session.link_off_by_owner = True
        settings.save(f, Settings())
        saved = set(json.loads(f.read_text(encoding="utf-8")))
        for key in ("link", "debug", "project_confirmed", "link_off_by_owner"):     # link_auto is a setting (S90)
            self.assertNotIn(key, saved)
        self.refused("link", link=True)
        self.refused("debug", debug=True)

    def test_dp31_link_to_smithboxs_server_by_itself(self):
        """S90: saved, off at first, on or off only."""
        self.assertIs(Settings().link_auto, False)
        self.assertIs(self.check(link_auto=True).link_auto, True)
        for bad in ("yes", 1, None):
            self.refused("link_auto", link_auto=bad)


if __name__ == "__main__":
    unittest.main()
