import _repo  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path

from datapiler import fileio


class FileioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_atomic_leaves_no_temporary_file(self):
        f = self.dir / "a.json"
        fileio.write_atomic(f, b"one")
        self.assertEqual(f.read_bytes(), b"one")
        self.assertEqual(sorted(os.listdir(self.dir)), ["a.json"])

    def test_write_atomic_replaces_an_existing_file(self):
        f = self.dir / "a.json"
        f.write_bytes(b"old and longer")
        fileio.write_atomic(f, b"new")
        self.assertEqual(f.read_bytes(), b"new")
        self.assertEqual(sorted(os.listdir(self.dir)), ["a.json"])

    def test_write_atomic_into_a_missing_folder_raises_and_leaves_nothing(self):
        with self.assertRaises(OSError):
            fileio.write_atomic(self.dir / "missing" / "a.json", b"x")
        self.assertEqual(os.listdir(self.dir), [])

    def test_hashes(self):
        f = self.dir / "b.bin"
        data = bytes(range(256)) * 9000
        f.write_bytes(data)
        self.assertEqual(fileio.sha256_file(f), fileio.sha256_bytes(data))
        self.assertEqual(fileio.sha256_bytes(b""),
                         "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_read_limited(self):
        f = self.dir / "c.bin"
        f.write_bytes(b"x" * 10)
        self.assertEqual(fileio.read_limited(f, 10), b"x" * 10)
        with self.assertRaises(fileio.TooLarge):
            fileio.read_limited(f, 9)
        self.assertTrue(issubclass(fileio.TooLarge, ValueError))
        with self.assertRaises(OSError):
            fileio.read_limited(self.dir / "none", 10)


if __name__ == "__main__":
    unittest.main()
