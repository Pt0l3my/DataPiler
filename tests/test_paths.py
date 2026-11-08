import _repo  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path

from datapiler import paths


class PathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_is_inside(self):
        game = self.root / "Game"
        (game / "sub").mkdir(parents=True)
        (self.root / "Game2").mkdir()
        self.assertTrue(paths.is_inside(game, game))
        self.assertTrue(paths.is_inside(game / "sub", game))
        self.assertTrue(paths.is_inside(str(game / "sub" / "x.bin"), str(game)))
        self.assertFalse(paths.is_inside(self.root / "Game2", game))
        self.assertFalse(paths.is_inside(self.root, game))
        self.assertTrue(paths.is_inside(game / "sub" / ".." / "sub", game))
        self.assertFalse(paths.is_inside(game / ".." / "Game2", game))
        self.assertFalse(paths.is_inside("", game))

    @unittest.skipUnless(os.name == "nt", "case folding is Windows' rule")
    def test_is_inside_folds_case_on_windows(self):
        game = self.root / "Game"
        game.mkdir()
        self.assertTrue(paths.is_inside(str(game).upper() + "\\x", str(game).lower()))

    def test_name_rx(self):
        for ok in ("a", "roster-counts", "npc_named", "0abc", "a" * 64):
            self.assertTrue(paths.NAME_RX.fullmatch(ok), ok)
        for bad in ("", "-a", "_a", "A", "a.b", "a/b", "a\\b", "..", "a b", "a" * 65, "é"):
            self.assertIsNone(paths.NAME_RX.fullmatch(bad), bad)

    def test_names_windows_keeps_for_devices(self):
        """NAME_RX accepts them, and on Windows "nul.json" or jobs\\con is a device, not a file."""
        p = paths.resolve(Path("/r"), "workspace", "share")
        for name in ("con", "prn", "aux", "nul", "com0", "com1", "com9", "lpt1", "lpt9", "CON", "Nul"):
            self.assertTrue(paths.reserved(name), name)
            self.assertFalse(paths.name_ok(name), name)
            with self.assertRaises(ValueError):
                paths.share_file(p, name.lower())
            with self.assertRaises(ValueError):
                paths.local_file(p, "job-1", name.lower())
            with self.assertRaises(ValueError):
                paths.local_file(p, name.lower(), "x")
        for name in ("console", "con-1", "nul_", "com10", "lpt", "a"):
            self.assertTrue(paths.name_ok(name), name)
        for name in (None, 5, "a.b"):
            self.assertFalse(paths.name_ok(name), name)

    def test_resolve_and_files(self):
        p = paths.resolve(self.root, "workspace", "share")
        self.assertEqual(p.workspace, self.root / "workspace")
        self.assertEqual(p.inbox, self.root / "workspace" / "inbox")
        self.assertEqual(p.textdb, self.root / "workspace" / "textdb.sqlite")
        self.assertEqual(p.venv_marker, self.root / ".venv" / "datapiler-lock.sha256")
        other = self.root / "elsewhere"
        q = paths.resolve(self.root, str(other), "share")
        self.assertEqual(q.workspace, other)
        self.assertEqual(paths.share_file(p, "roster-counts"), p.share / "roster-counts.json")
        self.assertEqual(paths.local_file(p, "en-0007", "npc-named"),
                         p.workspace / "local" / "en-0007" / "npc-named.json")
        for bad in ("../x", "A", "a.json", ""):
            with self.assertRaises(ValueError):
                paths.share_file(p, bad)
            with self.assertRaises(ValueError):
                paths.local_file(p, bad, "x")
            with self.assertRaises(ValueError):
                paths.local_file(p, "job", bad)

    def test_ensure(self):
        p = paths.resolve(self.root, "workspace", "share")
        paths.ensure(p)
        for d in (p.workspace, p.inbox, p.imported, p.local, p.share, p.logs, p.job_logs, p.jobs):
            self.assertTrue(d.is_dir(), d)


if __name__ == "__main__":
    unittest.main()
