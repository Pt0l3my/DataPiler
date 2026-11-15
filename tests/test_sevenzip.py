"""The 7z writer (DP30, S87): its number encoding, round trips through DataPiler's own reader, parts of the right size,
an earlier pack replaced whole, bad names refused, damage found, and, where 7-Zip itself is installed, 7-Zip's own
test and extraction of what it writes. Invented data only."""

from __future__ import annotations

import _repo  # noqa: F401

import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from datapiler import sevenzip as sz


def _seven_zip() -> str | None:
    for c in ("7z", "7za", r"C:\Program Files\7-Zip\7z.exe"):
        p = shutil.which(c) if not os.path.isabs(c) else (c if os.path.isfile(c) else None)
        if p:
            return p
    return None


class NumberTest(unittest.TestCase):
    def test_known_encodings(self):
        self.assertEqual(sz.number(0), b"\x00")
        self.assertEqual(sz.number(127), b"\x7f")
        self.assertEqual(sz.number(128), b"\x80\x80")
        self.assertEqual(sz.number(0x3FFF), b"\xbf\xff")
        self.assertEqual(sz.number(0x4000), b"\xc0\x00\x40")
        self.assertEqual(sz.number(2 ** 64 - 1), b"\xff" + b"\xff" * 8)

    def test_round_trip(self):
        for v in [0, 1, 127, 128, 255, 256, 2 ** 14 - 1, 2 ** 14, 2 ** 21, 2 ** 28 + 5, 2 ** 35, 2 ** 42 - 1,
                  2 ** 49, 2 ** 56 - 1, 2 ** 56, 2 ** 63, 2 ** 64 - 1]:
            c = sz._Cursor(sz.number(v))
            self.assertEqual(c.number(), v, v)
            self.assertEqual(c.i, len(c.b))

    def test_dictionary_property(self):
        self.assertEqual(sz.dict_prop(1 << 23), 22)
        self.assertEqual(sz.dict_prop(3 << 22), 23)
        self.assertEqual(sz.dict_prop(1 << 24), 24)
        self.assertEqual(sz.dict_prop(1), 0)


class PackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "src"
        self.src.mkdir()
        self.out = self.tmp / "packed"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, rel: str, data: bytes) -> tuple[str, Path]:
        p = self.src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return "job-1/" + rel, p

    def _read(self, parts):
        got: dict[str, bytearray] = {}
        sz.check(parts, sink=lambda n, b: got.setdefault(n, bytearray()).extend(b))
        return {k: bytes(v) for k, v in got.items()}

    def test_one_part_round_trip(self):
        rnd = random.Random(1)
        files = [self._file("a.txt", b"hello " * 1000), self._file("deep/er/b.bin", rnd.randbytes(5000)),
                 self._file("empty.dat", b""), self._file("c.json", b'{"rows": []}')]
        parts = sz.write(files, self.out, "job-1")
        self.assertEqual([p.name for p in parts], ["job-1.7z"])
        got = self._read(parts)
        self.assertEqual(set(got), {n for n, _ in files})
        for n, p in files:
            self.assertEqual(got[n], p.read_bytes())
        self.assertEqual(sorted(os.listdir(self.out)), ["job-1.7z"])     # the work folder is gone

    def test_parts_and_their_sizes(self):
        rnd = random.Random(2)
        files = [self._file("big%d.bin" % k, rnd.randbytes(100_000)) for k in range(3)]
        parts = sz.write(files, self.out, "job-1", part_size=sz.MIN_PART)
        self.assertGreaterEqual(len(parts), 5)
        self.assertEqual([p.name for p in parts], ["job-1.7z.%03d" % (k + 1) for k in range(len(parts))])
        for p in parts[:-1]:
            self.assertEqual(p.stat().st_size, sz.MIN_PART)
        self.assertLessEqual(parts[-1].stat().st_size, sz.MIN_PART)
        got = self._read(parts)
        for n, p in files:
            self.assertEqual(got[n], p.read_bytes())

    def test_an_earlier_pack_is_replaced_whole(self):
        rnd = random.Random(3)
        big = [self._file("big.bin", rnd.randbytes(400_000))]
        first = sz.write(big, self.out, "job-1", part_size=sz.MIN_PART)
        self.assertGreater(len(first), 2)
        (self.out / "other-job.7z").write_bytes(b"kept")
        small = [self._file("small.txt", b"x")]
        again = sz.write(small, self.out, "job-1", part_size=sz.MIN_PART)
        self.assertEqual(sorted(os.listdir(self.out)), ["job-1.7z", "other-job.7z"])
        self.assertEqual(self._read(again), {"job-1/small.txt": b"x"})

    def test_progress_reaches_the_whole(self):
        seen = []
        files = [self._file("a.bin", b"\1" * 3_000_000)]
        sz.write(files, self.out, "job-1", progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen[-1], (3_000_000, 3_000_000))

    def test_bad_names_are_refused(self):
        ok = self._file("a.txt", b"a")[1]
        for bad in ("../a.txt", "/a.txt", "job\\a.txt", "C:a.txt", "job/./a.txt", "job//a.txt", ""):
            with self.assertRaises(sz.PackError, msg=bad):
                sz.write([(bad, ok)], self.out, "job-1")
        with self.assertRaises(sz.PackError):
            sz.write([("job/A.txt", ok), ("job/a.txt", ok)], self.out, "job-1")
        with self.assertRaises(sz.PackError):
            sz.write([], self.out, "job-1")
        with self.assertRaises(sz.PackError):
            sz.write([("job/a.txt", ok)], self.out, "../job")

    def test_damage_is_found(self):
        files = [self._file("a.txt", b"some text that compresses " * 500)]
        parts = sz.write(files, self.out, "job-1")
        data = bytearray(parts[0].read_bytes())
        data[40] ^= 0xFF
        parts[0].write_bytes(bytes(data))
        with self.assertRaises(sz.PackError):
            sz.check(parts)

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(sz.PackError):
            sz.write([("job/a.txt", self.src / "nothing-here")], self.out, "job-1")

    @unittest.skipUnless(_seven_zip(), "7-Zip is not installed here")
    def test_seven_zip_reads_it(self):
        exe = _seven_zip()
        rnd = random.Random(4)
        files = [self._file("a.txt", b"hello " * 1000), self._file("sub/b.bin", rnd.randbytes(150_000)),
                 self._file("empty.dat", b"")]
        for part_size, label in ((sz.PART_SIZE, "one"), (sz.MIN_PART, "many")):
            out = self.tmp / ("out-" + label)
            parts = sz.write(files, out, "job-1", part_size=part_size)
            r = subprocess.run([exe, "t", str(parts[0])], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            dest = self.tmp / ("x-" + label)
            r = subprocess.run([exe, "x", "-y", "-o" + str(dest), str(parts[0])], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for n, p in files:
                self.assertEqual((dest / n).read_bytes(), p.read_bytes(), n)


if __name__ == "__main__":
    unittest.main()
