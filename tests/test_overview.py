"""S75: the overview image of exported map tiles, made on the PC. Invented tiles only."""
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datapiler import textures  # noqa: E402


def png_with_filters(w, h, rgba, ctype=6):
    """A PNG whose rows cycle through filters 0 to 4, written by a reference encoder of the test's own."""
    bpp = {6: 4, 2: 3}[ctype]
    px = rgba if ctype == 6 else bytes(b for k, b in enumerate(rgba) if k % 4 != 3)
    stride = w * bpp
    out = bytearray()
    prev = bytes(stride)
    for y in range(h):
        line = px[y * stride:(y + 1) * stride]
        f = y % 5
        enc = bytearray(stride)
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 0:
                pred = 0
            elif f == 1:
                pred = a
            elif f == 2:
                pred = b
            elif f == 3:
                pred = (a + b) >> 1
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
            enc[i] = (line[i] - pred) & 255
        out.append(f)
        out += enc
        prev = line

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(out))) + chunk(b"IEND", b""))


def solid(size, rgb):
    return bytes(list(rgb) + [255]) * (size * size)


class PngTest(unittest.TestCase):
    def test_every_filter_and_rgb(self):
        w, h = 7, 10
        rgba = bytes((x * 37 + y * 11 + c * 53) % 256 if c < 3 else 255 for y in range(h) for x in range(w)
                     for c in range(4))
        for ctype in (6, 2):
            got = textures.png_decode(png_with_filters(w, h, rgba, ctype))
            self.assertEqual((got[0], got[1], bytes(got[2])), (w, h, rgba))

    def test_round_trip_and_refusals(self):
        data = textures.png_encode(3, 2, solid(1, (1, 2, 3)) * 6)
        self.assertEqual(textures.png_decode(data)[:2], (3, 2))
        with self.assertRaises(ValueError):
            textures.png_decode(b"not a png")
        bad = bytearray(data)
        bad[24] = 16                                         # 16 bits a channel
        with self.assertRaises(ValueError):
            textures.png_decode(bytes(bad))


class OverviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def tile(self, rel, size, rgb):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(textures.png_encode(size, size, solid(size, rgb)))

    def pixel(self, data, x, y):
        w, h, px = textures.png_decode(data)
        k = (y * w + x) * 4
        return tuple(px[k:k + 3])

    def test_layout_rows_from_the_bottom_and_widest_variant(self):
        s = 4
        self.tile("ex/MENU_MapTile_M00_L4_00_00_00000000.png", s, (10, 0, 0))     # bottom left
        self.tile("ex/MENU_MapTile_M00_L4_01_00_00000000.png", s, (20, 0, 0))     # bottom right, plain
        self.tile("ex/MENU_MapTile_M00_L4_01_00_00000003.png", s, (25, 0, 0))     # bottom right, two pieces
        self.tile("ex/MENU_MapTile_M00_L4_01_00_00000001.png", s, (21, 0, 0))     # one of them only: inside 3, unused
        self.tile("ex/MENU_MapTile_M00_L4_00_01_00000000.png", s, (30, 0, 0))     # top left
        self.tile("ex/MENU_MapTile_M00_L3_00_00_00000000.png", s, (99, 0, 0))     # another level
        self.tile("ex/MENU_MapTile_M01_L4_00_00_00000000.png", s, (98, 0, 0))     # another sheet
        data, n = textures.overview(self.root, 0, 4)
        self.assertEqual((n["columns"], n["rows"], n["width"], n["height"], n["tiles"]), (2, 2, 8, 8, 3))
        self.assertEqual(self.pixel(data, 0, 7), (10, 0, 0))
        self.assertEqual(self.pixel(data, 7, 7), (25, 0, 0))
        self.assertEqual(self.pixel(data, 0, 0), (30, 0, 0))
        w, h, px = textures.png_decode(data)
        self.assertEqual(px[(0 * w + 7) * 4 + 3], 0)          # top right: no tile, transparent
        top, _ = textures.overview(self.root, 0, 4, rows_from="top")
        self.assertEqual(self.pixel(top, 0, 0), (10, 0, 0))

    def test_s76_a_revealed_variant_is_laid_over_the_base(self):
        s = 2
        base = bytes([100, 100, 100, 255]) * (s * s)
        over = bytes([200, 0, 0, 255, 0, 0, 0, 0, 0, 200, 0, 128, 0, 0, 0, 0])   # opaque, clear, half, clear
        for rel, data in (("ex/MENU_MapTile_M00_L4_00_00_00000000.png", textures.png_encode(s, s, base)),
                          ("ex/MENU_MapTile_M00_L4_00_00_00000005.png", textures.png_encode(s, s, over))):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        data, n = textures.overview(self.root, 0, 4)
        w, h, px = textures.png_decode(data)
        self.assertEqual(bytes(px[0:4]), bytes([200, 0, 0, 255]))      # the overlay where it is opaque
        self.assertEqual(bytes(px[4:8]), bytes([100, 100, 100, 255]))   # the base where it is clear
        self.assertEqual(bytes(px[8:12]), bytes([50, 150, 50, 255]))    # half and half
        only, _ = textures.overview(self.root, 0, 4, variant="base")
        self.assertEqual(bytes(textures.png_decode(only)[2][0:4]), bytes([100, 100, 100, 255]))
        with self.assertRaises(ValueError):
            textures.overview(self.root, 0, 4, variant="most")

    def put(self, code, px, s=2):
        p = self.root / ("ex/MENU_MapTile_M00_L4_00_00_%08X.png" % code)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(textures.png_encode(s, s, bytes(px)))

    def test_s77_pieces_apart_in_a_tile_are_laid_together(self):
        g, r, b = [100, 100, 100, 255], [200, 0, 0, 255], [0, 0, 200, 255]
        self.put(0, g * 4)
        self.put(1, r + g * 3)                 # piece 1 drawn in the first pixel
        self.put(2, g + b + g * 2)             # piece 2 drawn in the second: no variant 3, the two never meet here
        data, n = textures.overview(self.root, 0, 4)
        px = textures.png_decode(data)[2]
        self.assertEqual([list(px[k * 4:k * 4 + 4]) for k in range(4)], [r, b, g, g])
        self.assertEqual(n["joined"], 1)
        only, n = textures.overview(self.root, 0, 4, variant="base")
        self.assertEqual(bytes(textures.png_decode(only)[2]), bytes(g * 4))
        self.assertEqual(n["joined"], 0)

    def test_s77_overlapping_widest_variants_and_subsets_left_out(self):
        g, r, b, y = [100, 100, 100, 255], [200, 0, 0, 255], [0, 0, 200, 255], [9, 9, 9, 255]
        self.put(0, g * 4)
        self.put(1, y * 4)                     # a subset of 3: never laid
        self.put(2, y * 4)
        self.put(4, y * 4)
        self.put(3, r + r + g + g)             # pieces 1 and 2 meet: their joint variant
        self.put(6, g + b + b + g)             # pieces 2 and 4 meet; 1 and 4 do not (no 5, no 7)
        data, n = textures.overview(self.root, 0, 4)
        px = textures.png_decode(data)[2]
        self.assertEqual([list(px[k * 4:k * 4 + 4]) for k in range(4)], [r, b, b, g])
        self.assertEqual(textures.widest({0, 1, 2, 4, 3, 6}), [3, 6])
        self.assertEqual(textures.widest({0}), [])

    def test_s77_without_a_base_variants_are_laid_by_alpha(self):
        r, b, clear = [200, 0, 0, 255], [0, 0, 200, 255], [0, 0, 0, 0]
        self.put(1, r + clear * 3)
        self.put(2, clear + b + clear * 2)
        data, _ = textures.overview(self.root, 0, 4)
        px = textures.png_decode(data)[2]
        self.assertEqual([list(px[k * 4:k * 4 + 4]) for k in range(4)], [r, b, clear, clear])

    def test_lay_over_counts_what_it_drew(self):
        g, r = bytes([1, 2, 3, 255]), bytes([4, 5, 6, 255])
        canvas = bytearray(g * 3)
        self.assertEqual(textures.lay_over(canvas, g * 3, g * 3), 0)
        self.assertEqual(textures.lay_over(canvas, r + g * 2, g * 3), 1)
        self.assertEqual(bytes(canvas), r + g * 2)

    def test_refusals(self):
        with self.assertRaises(ValueError):
            textures.overview(self.root, 0, 4)                 # nothing exported
        self.tile("ex/MENU_MapTile_M00_L0_17_00_00000000.png", 256, (1, 1, 1))
        with self.assertRaises(ValueError):
            textures.overview(self.root, 0, 0)                 # 18 x 256 pixels: over the limit
        with self.assertRaises(ValueError):
            textures.overview(self.root, 0, 0, rows_from="left")


if __name__ == "__main__":
    unittest.main()
