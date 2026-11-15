"""Game files Smithbox unpacked (S81, DP28): DataPiler's own DCX and BND4 reader, on invented files only."""

import _repo  # noqa: F401

import os
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from _packs import FakeOodle, bnd4_bytes, dcx_bytes, menu_like

from datapiler import gamefiles as gf

K = gf.KINDS
P = gf.PACKINGS


def collect(data: bytes, name: str = "99_invented.testbnd.dcx", **kw):
    out: dict[tuple[str, ...], bytes] = {}

    def emit(parts, body):
        assert parts not in out
        out[parts] = body

    rows = gf.unpack(data, name, emit, **kw)
    return rows, out


class DcxTest(unittest.TestCase):
    def test_dflt(self):
        payload = b"an invented payload " * 50
        body, packing = gf.dcx(dcx_bytes(payload), None)
        self.assertEqual((body, packing), (payload, P["dflt"]))

    def test_krak_goes_to_the_game_library(self):
        fake = FakeOodle()
        body, packing = gf.dcx(dcx_bytes(b"krak payload", b"KRAK"), lambda: fake)
        self.assertEqual((body, packing, fake.calls), (b"krak payload", P["krak"], 1))

    def test_krak_without_the_library(self):
        with self.assertRaises(gf.Unavailable):
            gf.dcx(dcx_bytes(b"x" * 9, b"KRAK"), None)

    def test_refusals(self):
        good = dcx_bytes(b"y" * 100)
        cases = {
            "zstd": dcx_bytes(b"z", b"ZSTD"),
            "edge": dcx_bytes(b"z", b"EDGE"),
            "short": good[:0x40],
            "cut": good[:-3],
            "magic": b"DCY\0" + good[4:],
            "version": good[:4] + struct.pack(">I", 0x12000) + good[8:],
            "size": dcx_bytes(b"y" * 100, raw_len=99),
            "not zlib": dcx_bytes(b"y" * 4, comp=b"\x00\x01\x02\x03"),
            "bad deflate": dcx_bytes(b"y" * 4, comp=b"\x78\xda\xff\xff\xff\xff"),
        }
        for what, data in cases.items():
            with self.subTest(what), self.assertRaises(gf.FormatError):
                gf.dcx(data, None)

    def test_a_dcx_larger_than_datapiler_opens(self):
        with mock.patch.object(gf, "MAX_OUTPUT", 10), self.assertRaises(gf.FormatError):
            gf.dcx(dcx_bytes(b"y" * 11), None)


class Bnd4Test(unittest.TestCase):
    FILES = [(7, "\\XX\\data\\INTERROOT_win64\\menu\\one.test", b"first", False),
             (8, "\\XX\\data\\INTERROOT_win64\\menu\\two.test", dcx_bytes(b"second" * 9), True)]

    def test_the_usual_format(self):
        blob = bnd4_bytes(self.FILES)
        es = gf.bnd4(blob)
        self.assertEqual([(e.index, e.id, e.name, e.compressed) for e in es],
                         [(0, 7, self.FILES[0][1], False), (1, 8, self.FILES[1][1], True)])
        self.assertEqual(blob[es[0].offset:es[0].offset + es[0].stored], b"first")

    def test_other_formats(self):
        for fmt, unicode, big, bit_big in ((0x3E, True, False, False), (0x2E, False, False, False),
                                          (0x2E, True, True, False), (0x2E, True, False, True), (0x04, True, False, False),
                                          (0x06, True, False, False)):
            with self.subTest(fmt=fmt, unicode=unicode, big=big, bit_big=bit_big):
                files = [(5, "folder\\plain.test", b"plain", False)]
                es = gf.bnd4(bnd4_bytes(files, fmt=fmt, unicode=unicode, big=big, bit_big=bit_big))
                self.assertEqual((es[0].name, es[0].compressed), ("folder\\plain.test", False))
                self.assertEqual(es[0].id, 5)
                self.assertEqual(es[0].size, 5 if fmt & 0x20 else -1)

    def test_a_format_without_names_or_ids(self):
        es = gf.bnd4(bnd4_bytes([(1, None, b"abc", False)], fmt=0x20))
        self.assertEqual((es[0].id, es[0].name), (-1, None))

    def test_refusals(self):
        good = bnd4_bytes(self.FILES)
        cut = bytearray(good)
        struct.pack_into("<I", cut, 0x40 + 0x18, len(good) + 100)     # the first file's offset, past the end
        minus = bytearray(good)
        struct.pack_into("<i", minus, 0x44, 0)
        cases = {"magic": b"BND5" + good[4:], "short": good[:0x30], "header size": good[:0x10] + b"\x41" + good[0x11:],
                 "file header size": good[:0x20] + b"\x30" + good[0x21:], "outside": bytes(cut), "not -1": bytes(minus),
                 "count": good[:0x0C] + struct.pack("<i", 9) + good[0x10:]}
        for what, data in cases.items():
            with self.subTest(what), self.assertRaises(gf.FormatError):
                gf.bnd4(data)


class SafePartsTest(unittest.TestCase):
    def test_parts(self):
        self.assertEqual(gf.safe_parts("\\XX\\data\\INTERROOT_win64\\menu\\a\\b.test", 0), ("menu", "a", "b.test"))
        self.assertEqual(gf.safe_parts("..\\..\\evil.test", 0), ("_", "_", "evil.test"))
        self.assertEqual(gf.safe_parts("C:/x/CON.txt", 0), ("x", "_CON.txt"))
        self.assertEqual(gf.safe_parts("a<b>:c|d?.test", 0), ("a_b__c_d_.test",))
        self.assertEqual(gf.safe_parts("name. ", 0), ("name",))
        self.assertEqual(gf.safe_parts("x/./y//z", 0), ("x", "y", "z"))
        self.assertEqual(gf.safe_parts(None, 3), ("file-00003.bin",))
        self.assertEqual(gf.safe_parts("\\\\", 4), ("file-00004.bin",))
        self.assertEqual(len(gf.safe_parts("/".join("d%d" % k for k in range(30)), 0)), gf.MAX_PARTS)
        self.assertEqual(len(gf.safe_parts("x" * 300, 0)[0]), 100)

    def test_the_namer(self):
        n = gf._Namer()
        self.assertEqual(n.place(("a", "b.test")), ("a", "b.test"))
        self.assertEqual(n.place(("A", "B.test")), ("A", "B-2.test"))
        self.assertEqual(n.place(("a", "b.test")), ("a", "b-3.test"))
        self.assertEqual(n.place(("a",)), ("a-2",))                   # a folder is there
        self.assertEqual(n.place(("a", "b.test", "c")), ("_clash", "c"))
        self.assertEqual(n.place(("_clash",)), ("_clash-2",))     # a folder is there
        n.files.add("_clash-3")
        self.assertEqual(n.place(("a", "b.test", "c")), ("_clash", "c-2"))
        self.assertEqual(n.place(("noext",)), ("noext",))
        self.assertEqual(n.place(("noext",)), ("noext-2",))


class UnpackTest(unittest.TestCase):
    def test_a_krak_binder_of_masks(self):
        fake = FakeOodle()
        rows, out = collect(menu_like(), oodle=lambda: fake)
        self.assertEqual(sorted(out), [("menu", "Invented", "mask", "a_m00.testmsk"),
                                       ("menu", "Invented", "mask", "a_m01.testmsk")])
        self.assertEqual(out[("menu", "Invented", "mask", "a_m01.testmsk")], bytes([1]) * 41)
        self.assertEqual(rows[0][:6], (0, -1, 0, -1, K["bnd4"], P["krak"]))
        self.assertEqual(rows[1:], [(1, 0, 1, 0, K["other"], P["none"], 40, 40),
                                    (2, 0, 1, 1, K["other"], P["none"], 41, 41)])
        self.assertEqual(len(rows[0]), len(gf.UNPACK_COLUMNS))

    def test_nested_binders_and_compressed_files(self):
        inner = bnd4_bytes([(1, "deep\\x.test", b"deep file", False)])
        deepest = bnd4_bytes([(1, "y.test", b"y", False)])
        nest3 = bnd4_bytes([(1, "n4.bnd", deepest, False)])
        nest2 = bnd4_bytes([(1, "n3.bnd", nest3, False)])
        nest1 = bnd4_bytes([(1, "n2.bnd", nest2, False)])
        outer = bnd4_bytes([(10, "pack\\inner.bnd.dcx", dcx_bytes(inner), True),
                            (11, "pack\\movie.test.dcx", dcx_bytes(b"GFX\x0a invented"), True),
                            (12, "n1.bnd", nest1, False)])
        rows, out = collect(dcx_bytes(outer))
        self.assertIn(("pack", "inner.bnd" + gf.UNPACKED_SUFFIX, "deep", "x.test"), out)
        self.assertEqual(out[("pack", "movie.test")], b"GFX\x0a invented")       # .dcx left off once decompressed
        self.assertEqual(rows[1][:6], (1, 0, 1, 10, K["bnd4"], P["dflt"]))
        self.assertEqual(rows[2][:6], (2, 1, 2, 1, K["other"], P["none"]))
        self.assertEqual(rows[3][4:6], (K["gfx"], P["dflt"]))
        deep_rows = [r for r in rows if r[4] == K["bnd4"]]
        self.assertEqual(max(r[2] for r in rows), gf.MAX_NEST)
        written_binders = [p for p, b in out.items() if b[:4] == b"BND4"]
        self.assertEqual(len(written_binders), 1)                     # the binder MAX_NEST deep stays a file
        self.assertTrue(deep_rows)

    def test_a_dcx_of_one_file(self):
        rows, out = collect(dcx_bytes(b"TPF\0invented"), "99_invented.tpf.dcx")
        self.assertEqual(out, {("99_invented.tpf",): b"TPF\0invented"})
        self.assertEqual(rows, [(0, -1, 0, -1, K["tpf"], P["dflt"], len(dcx_bytes(b"TPF\0invented")), 12)])

    def test_a_plain_binder(self):
        rows, out = collect(bnd4_bytes([(1, "a.test", b"a", False)]), "99_invented.testbnd")
        self.assertEqual(out, {("a.test",): b"a"})
        self.assertEqual(rows[0][5], P["none"])

    def test_nothing_to_unpack(self):
        with self.assertRaises(gf.FormatError):
            collect(b"just some invented bytes", "99_invented.txt")

    def test_a_compressed_file_that_is_not_a_dcx(self):
        with self.assertRaises(gf.FormatError):
            collect(bnd4_bytes([(1, "a.test", b"plain", True)]))

    def test_limits(self):
        many = bnd4_bytes([(k, "f%d.test" % k, b"x", False) for k in range(5)])
        with mock.patch.object(gf, "MAX_ENTRIES", 3), self.assertRaises(gf.FormatError):
            collect(many)
        with mock.patch.object(gf, "MAX_OUTPUT", 3), self.assertRaises(gf.FormatError):
            collect(many)
        with mock.patch.object(gf, "MAX_INPUT", 10), self.assertRaises(gf.FormatError):
            collect(many)

    def test_cancel(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(gf.Cancelled):
            collect(bnd4_bytes([(1, "a.test", b"a", False)]), cancel=stop)


class FindAndOodleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_find_file(self):
        (self.root / "unpacks" / "menu").mkdir(parents=True)
        (self.root / "unpacks" / "menu" / "99_Invented.testbnd.dcx").write_bytes(b"one")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "99_invented.testbnd.dcx").write_bytes(b"left out")
        (self.root / "bin").mkdir()
        (self.root / "bin" / "99_invented.testbnd.dcx").write_bytes(b"left out")
        (self.root / "other.dcx").write_bytes(b"another")
        found, n = gf.find_file(self.root, "99_invented.testbnd.dcx", skip=(self.root / "bin",))
        self.assertEqual([f.read_bytes() for f in found], [b"one"])
        self.assertEqual(n["stopped"], 0)
        self.assertEqual(gf.digest(found[0]), (3, "7692c3ad3540bb803c020b3aee66cd8887123234ea0c6e7143c0add73ff431ed"))

    def test_the_library_in_the_game_folder(self):
        game = self.root / "Game"
        game.mkdir()
        self.assertIsNone(gf.oodle_file(str(game)))                   # not the game's folder: no eldenring.exe
        (game / "eldenring.exe").write_bytes(b"MZ invented")
        self.assertIsNone(gf.oodle_file(str(game)))
        (game / "oo2core_6_win64.dll").write_bytes(b"MZ invented")
        (game / "oo2core_7_win64.dll").write_bytes(b"MZ invented")    # a version DataPiler does not call
        (game / "oo2core_9_win64.dll").mkdir()                        # a folder, not a library
        self.assertEqual(gf.oodle_file(str(game)).name, "oo2core_6_win64.dll")
        (game / "OO2CORE_8_WIN64.DLL").write_bytes(b"MZ invented")
        self.assertEqual(gf.oodle_file(str(game)).name.lower(), "oo2core_8_win64.dll")
        self.assertIsNone(gf.oodle_file(""))
        with self.assertRaises(gf.Unavailable):                       # off Windows, or not a 64-bit library
            gf.load_oodle(str(game))
        self.assertFalse(gf._pe_x64(game / "oo2core_6_win64.dll"))

    def test_a_64_bit_library_by_its_headers(self):
        f = self.root / "x.dll"
        head = bytearray(0x200)
        head[:2] = b"MZ"
        struct.pack_into("<I", head, 0x3C, 0x80)
        head[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", head, 0x84, 0x8664)
        f.write_bytes(bytes(head))
        self.assertTrue(gf._pe_x64(f))
        struct.pack_into("<H", head, 0x84, 0x14C)
        f.write_bytes(bytes(head))
        self.assertFalse(gf._pe_x64(f))

    @unittest.skipIf(os.name == "nt", "off Windows only")
    def test_off_windows_the_library_is_never_loaded(self):
        with mock.patch.object(gf, "Oodle") as made, self.assertRaises(gf.Unavailable):
            gf.load_oodle(str(self.root))
        made.assert_not_called()


if __name__ == "__main__":
    unittest.main()
