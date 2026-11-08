"""tools/manifest.py (build plan 0.2 §4.11, §7.1): the format sha256sum reads, sorted by the UTF-8 bytes of the path,
LF, the manifest itself left out, a link refused, and update-helper.py's parse_manifest reading what it writes."""

import _repo  # noqa: F401

import hashlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_archive import helper

_spec = importlib.util.spec_from_file_location("manifest_tool", str(Path(_repo.ROOT) / "tools" / "manifest.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class ManifestTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "DataPiler"
        self.dir.mkdir()
        self.files = {"b.py": b"b\n", "a/z.txt": b"z\n", "A.md": b"A\n", "a/é.txt": b"accent\n",
                      ".github/workflows/x.yml": b"x\n"}
        for rel, data in self.files.items():
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, folder):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = tool.main([str(folder)])
        return code, out.getvalue(), err.getvalue()

    def test_the_format_and_the_order(self):
        code, out, _ = self.run_tool(self.dir)
        self.assertEqual(code, 0)
        self.assertIn("manifest.sha256: 5 files", out)
        data = (self.dir / "manifest.sha256").read_bytes()
        self.assertTrue(data.endswith(b"\n"))
        self.assertNotIn(b"\r", data)
        lines = data.decode("utf-8").splitlines()
        paths = [l.split("  ", 1)[1] for l in lines]
        self.assertEqual(paths, sorted(self.files, key=lambda p: p.encode("utf-8")))
        self.assertEqual(paths[0], ".github/workflows/x.yml")
        for line in lines:
            h, rel = line.split("  ", 1)
            self.assertEqual(h, hashlib.sha256(self.files[rel]).hexdigest())
        self.assertEqual(helper().parse_manifest(data), {p: hashlib.sha256(b).hexdigest()
                                                         for p, b in self.files.items()})

    def test_the_manifest_is_left_out_and_rewritten(self):
        (self.dir / "manifest.sha256").write_bytes(b"old")
        self.assertEqual(self.run_tool(self.dir)[0], 0)
        first = (self.dir / "manifest.sha256").read_bytes()
        self.assertNotIn(b"manifest.sha256", first)
        self.assertEqual(self.run_tool(self.dir)[0], 0)
        self.assertEqual((self.dir / "manifest.sha256").read_bytes(), first)

    @unittest.skipIf(sys.platform == "win32", "symlinks need a privilege on Windows")
    def test_a_symlink_is_refused(self):
        os.symlink(self.dir / "b.py", self.dir / "link.py")
        code, _, err = self.run_tool(self.dir)
        self.assertEqual(code, 2)
        self.assertIn("a link: link.py", err)
        self.assertFalse((self.dir / "manifest.sha256").exists())

    @unittest.skipIf(sys.platform == "win32", "symlinks need a privilege on Windows")
    def test_a_linked_folder_is_refused(self):
        os.symlink(self.dir / "a", self.dir / "linked", target_is_directory=True)
        self.assertEqual(self.run_tool(self.dir)[0], 2)

    def test_a_path_the_helper_refuses(self):
        (self.dir / "trailing.").write_bytes(b"x") if sys.platform != "win32" else None
        if sys.platform == "win32":
            self.skipTest("Windows cannot make such a name")
        code, _, err = self.run_tool(self.dir)
        self.assertEqual(code, 2)
        self.assertIn("a path DataPiler does not write", err)

    def test_not_a_folder(self):
        self.assertEqual(self.run_tool(self.dir / "b.py")[0], 2)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            self.assertEqual(tool.main([]), 2)


if __name__ == "__main__":
    unittest.main()
