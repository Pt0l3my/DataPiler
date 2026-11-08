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
        self.root = Path(self.tmp.name)
        self.game = self.root / "Game"
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
                                       "share_dir": "share", "language": "engus", "port": 0, "log_max_mb": 2,
                                       "log_keep": 5})

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
        sibling = self.root / "Game2"
        sibling.mkdir()
        self.assertEqual(self.check(game_dir=str(self.game), project_dir=str(sibling)).project_dir, str(sibling))

    def test_workspace_and_share_rules(self):
        self.refused("workspace_dir", game_dir=str(self.game), workspace_dir=str(self.game / "ws"))
        sb = self.root / "Smithbox"
        self.refused("share_dir", smithbox_dir=str(sb), share_dir=str(sb / "share"))
        self.refused("share_dir", workspace_dir="workspace", share_dir="workspace/share")
        self.refused("workspace_dir", workspace_dir="share/ws", share_dir="share")
        self.assertEqual(self.check(workspace_dir="ws", share_dir="out").share_dir, "out")

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
        self.assertEqual((session.link, session.debug), (False, False))
        session.link = session.debug = True
        settings.save(f, Settings())
        text = f.read_text(encoding="utf-8")
        self.assertNotIn("link", text)
        self.assertNotIn("debug", text)
        self.refused("link", link=True)
        self.refused("debug", debug=True)


if __name__ == "__main__":
    unittest.main()
