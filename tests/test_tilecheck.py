"""S78: which exported map tiles belong to one image - the tile set, the check against the next level, labels and the
one-code overview. Invented patterns only: no game image is used."""
import json
import math
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datapiler import guard, jobs, textures  # noqa: E402

S = 64                       # tile side: one thumbnail pixel per tile pixel


def world(x, y):
    """An invented landscape, grey 0-255."""
    return 128 + 60 * math.sin(x / 9.0) * math.cos(y / 7.0) + 30 * math.sin((x + y) / 13.0)


def other(x, y):
    """Another invented drawing, at another scale."""
    return 128 + 70 * math.sin(x / 3.1 + 1) * math.cos(y / 4.3) - 20 * math.cos((x - 2 * y) / 5.0)


def tile(fn, x0, y0, step=1.0, patch=None):
    """S x S RGBA: fn sampled from (x0, y0) at `step` per pixel (rows from the top); `patch` = (left, top, side) lit."""
    out = bytearray()
    for r in range(S):
        for c in range(S):
            g = fn(x0 + c * step, y0 + r * step)
            if patch and patch[0] <= c < patch[0] + patch[2] and patch[1] <= r < patch[1] + patch[2]:
                g += 50
            g = max(0, min(255, int(g)))
            out += bytes((g, g, g, 255))
    return bytes(out)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, level, x, y, code, px, folder="ex", sheet=0):
        p = self.root / folder / ("MENU_MapTile_M%02d_L%d_%02d_%02d_%08X.png" % (sheet, level, x, y, code))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(textures.png_encode(S, S, px))

    def two_levels(self):
        """Level 3: 2 x 2 tiles of the world, each with a genuine variant (code 1, a lit patch) and, at (1, 1), a
        variant from another drawing (code 2). Level 4: the world at half size, one tile, base and code 1. (S82: the
        legacy levels, whose scales still halve.)"""
        for x in (0, 1):
            for y in (0, 1):
                top = (1 - y) * S                    # rows from the bottom: y 1 is the top row of the image
                self.put(3, x, y, 0, tile(world, x * S, top))
                self.put(3, x, y, 1, tile(world, x * S, top, patch=(10, 10, 30)))
        self.put(3, 1, 1, 2, tile(other, 0, 0))
        self.put(4, 0, 0, 0, tile(world, 0, 0, step=2.0))
        self.put(4, 0, 0, 1, tile(world, 0, 0, step=2.0))


class TileSetTest(Base):
    def test_folders_numbered_copies_counted_first_copy_kept(self):
        self.put(0, 0, 0, 0, tile(world, 0, 0), folder="a")
        self.put(0, 0, 0, 0, tile(other, 0, 0), folder="b")      # a second copy: counted, not used
        self.put(0, 1, 0, 0, tile(world, S, 0), folder="b")
        self.put(1, 0, 0, 0, tile(world, 0, 0), folder="b")
        (self.root / "b" / "MENU_MapTile_M01_L0_00_00_00000000.png").write_bytes(b"other sheet")
        ts = textures.tile_set(self.root, 0)
        self.assertEqual(ts.folders, 2)
        self.assertEqual(ts.copies[(0, 0, 0, 0)], 2)
        self.assertEqual(ts.folder[ts.levels[0][(0, 0)][0]], 1)
        self.assertEqual(ts.folder[ts.levels[0][(1, 0)][0]], 2)
        self.assertEqual(ts.grid(0), (2, 1))
        self.assertEqual(ts.grid(5), (0, 0))

    def test_which_grids_nest(self):
        self.assertTrue(textures.nests((11, 11), (6, 6)))
        self.assertTrue(textures.nests((6, 6), (3, 3)))
        self.assertFalse(textures.nests((41, 41), (31, 31)))
        self.assertFalse(textures.nests((31, 31), (11, 11)))


class CheckTest(Base):
    def test_a_variant_of_another_drawing_is_found(self):
        self.two_levels()
        rows, n = textures.check_level(textures.tile_set(self.root, 0), 3)
        by = {(r[0], r[1], r[2]): dict(zip([c for c, _ in textures.TILE_CHECK_COLUMNS], r)) for r in rows}
        self.assertEqual(len(rows), 9)
        self.assertEqual((n["near_level"], n["other_image"], n["folders"]), (4, 1, 1))
        base = by[(0, 0, 0)]
        self.assertEqual((base["drawn"], base["like"], base["near_level"], base["near_code"]), (0, 1000, 4, 0))
        self.assertEqual(base["in_mask"], -1)                                     # no mask file found
        self.assertGreater(base["near"], 950)
        genuine = by[(1, 1, 1)]
        self.assertEqual(genuine["near_code"], 1)
        self.assertTrue(textures.passes(genuine["near"], genuine["near_base"]))
        self.assertEqual(genuine["drawn"], round(1000 * 30 * 30 / (S * S)))      # the lit patch only
        foreign = by[(1, 1, 2)]
        self.assertEqual(foreign["near_code"], 0)                               # level 4 has no code 2: its base
        self.assertFalse(textures.passes(foreign["near"], foreign["near_base"]))
        self.assertLess(max(foreign["near"], foreign["near_base"]), 500)

    def test_the_coarsest_level_is_measured_against_the_finer_one(self):
        self.two_levels()
        judge = textures.Judge(textures.tile_set(self.root, 0), 4)
        self.assertEqual((judge.other, judge.ratio), (3, 2.0))
        rows, n = textures.check_level(judge.ts, 4)
        self.assertEqual(n["near_level"], 3)
        self.assertTrue(all(max(r[9], r[10]) > 950 for r in rows), rows)

    def test_nothing_to_measure(self):
        self.put(0, 0, 0, 0, tile(world, 0, 0))
        self.put(0, 0, 0, 4, tile(other, 0, 0))
        rows, n = textures.check_level(textures.tile_set(self.root, 0), 0)
        self.assertEqual(n["near_level"], -1)
        self.assertEqual([r[7:] for r in rows],
                         [(-1, -1, textures.UNMEASURED, textures.UNMEASURED, textures.UNMEASURED, -1)] * 2)
        self.assertTrue(textures.passes(textures.UNMEASURED, textures.UNMEASURED))
        flat = [5.0] * 16
        self.assertEqual(textures.ncc(flat, [float(k) for k in range(16)]), textures.UNMEASURED)
        self.assertEqual(textures.ncc([1.0, 2.0, 30.0], [2.0, 4.0, 60.0]), 1000)

    def test_the_table_is_numbers_the_guard_lets_through(self):
        self.assertTrue(all(t == "int" for _, t in textures.TILE_CHECK_COLUMNS))
        words = guard.fixed_words()
        self.assertTrue(all(c in words for c, _ in textures.TILE_CHECK_COLUMNS))


class GeneralTest(Base):
    """S79: every level against the sheet's reference level, at any of LEVEL_SCALES' ratios."""

    def fine_level(self, level, side, foreign_at=None):
        """`side` x `side` tiles of the world at `level`, with a level-3 tile of the same ground; each with code 1 (a
        lit patch) and, at foreign_at, code 2 from another drawing."""
        k = textures.level_scale(level) / textures.level_scale(3)          # this level's pixels per level-3 pixel
        step = 1.0 / 4                                                      # world units per pixel at this level
        for x in range(side):
            for y in range(side):
                top = (side - 1 - y) * S
                self.put(level, x, y, 0, tile(world, x * S * step, top * step, step=step))
                self.put(level, x, y, 1, tile(world, x * S * step, top * step, step=step, patch=(5, 5, 8)))
        if foreign_at is not None:
            self.put(level, foreign_at[0], foreign_at[1], 2, tile(other, 0, 0))
        span = side * S / k                                                 # level-3 pixels the level covers
        assert abs(span - S) < 1e-6, span
        self.put(3, 0, 0, 0, tile(world, 0, 0, step=step * k))
        self.put(3, 0, 0, 1, tile(world, 0, 0, step=step * k))

    def scores(self, level):
        ts = textures.tile_set(self.root, 0)
        rows, n = textures.check_level(ts, level)
        return {(r[0], r[1], r[2]): max(r[9], r[10]) for r in rows}, n

    def test_the_reference_level(self):
        ts = textures.TileSet()
        for lv, side in ((0, 41), (1, 31), (2, 11), (3, 6), (4, 3)):
            ts.levels[lv] = {(side - 1, side - 1): {0: Path("a")}}
        self.assertEqual(textures.reference_level(ts), 2)                   # S82: level 2's frame is 9; 3 is legacy
        self.assertEqual([textures.frame(ts, lv) for lv in range(5)], [(41, 41), (31, 31), (9, 9), (6, 6), (3, 3)])
        del ts.levels[2]
        self.assertEqual(textures.reference_level(ts), 1)
        del ts.levels[0], ts.levels[1]
        self.assertEqual(textures.reference_level(ts), 3)                   # legacy levels only when nothing else
        self.assertIsNone(textures.reference_level(textures.TileSet()))
        self.assertEqual(textures.level_scale(5), 0.03125)

    def test_level_0_against_level_3(self):
        self.fine_level(0, 8, foreign_at=(3, 4))
        got, n = self.scores(0)
        self.assertEqual(n["near_level"], 3)
        self.assertTrue(all(v >= textures.MATCH_MIN for (x, y, c), v in got.items() if c != 2), got)
        self.assertTrue(all(v > 950 for (x, y, c), v in got.items() if c == 0), got)
        self.assertLess(got[(3, 4, 2)], 500)

    def test_level_1_against_level_3_at_a_sixth(self):
        self.fine_level(1, 6, foreign_at=(2, 1))
        got, n = self.scores(1)
        self.assertEqual(n["near_level"], 3)
        self.assertTrue(all(v >= textures.MATCH_MIN for (x, y, c), v in got.items() if c != 2), got)
        self.assertTrue(all(v > 950 for (x, y, c), v in got.items() if c == 0), got)
        self.assertLess(got[(2, 1, 2)], 500)

    def test_s80_a_level_whose_map_sits_at_the_top_of_its_frame(self):
        step = 1.0 / 4                                  # world units per level-0 pixel
        for x in range(9):                              # level 0: 9 x 9 tiles, 576 pixels a side
            for y in range(9):
                self.put(0, x, y, 0, tile(world, x * S * step, (8 - y) * S * step, step=step))
        k = 0.75                                        # level 1: the map is 432 pixels, its frame 7 tiles (448)
        for x in range(7):
            for y in range(7):
                top_l0 = (6 - y) * S / k                # the tile's top, in level-0 pixels from the top
                self.put(1, x, y, 0, tile(world, x * S / k * step, top_l0 * step, step=step / k))
                if y:
                    self.put(1, x, y, 1, tile(world, x * S / k * step, top_l0 * step, step=step / k, patch=(5, 5, 8)))
        self.assertIn(1, textures.LEVEL_TOP)
        ts = textures.tile_set(self.root, 0)
        self.assertEqual(textures.frame(ts, 1), (7, 7))
        rows, n = textures.check_level(ts, 1)
        scores = [max(r[9], r[10]) for r in rows if r[1] and r[9] != textures.UNMEASURED]
        self.assertTrue(scores and all(v > 900 for v in scores), scores)
        judge = textures.Judge(ts, 1)
        judge.size = S
        self.assertEqual((judge.lift(1), judge.lift(0)), (16.0, 0.0))

    def test_s82_a_tile_of_the_older_layout_scores_where_its_ground_lies_today(self):
        self.fine_level(0, 8)
        self.put(0, 4, 3, 4, tile(world, 2 * S / 4, (7 - 3) * S / 4, step=1.0 / 4))    # tile (2, 3)'s ground
        old = textures.OLD_SHIFT
        textures.OLD_SHIFT = -2 * S                     # two tiles to the left, in level-0 pixels
        try:
            rows, _ = textures.check_level(textures.tile_set(self.root, 0), 0)
        finally:
            textures.OLD_SHIFT = old
        r = next(r for r in rows if r[:3] == (4, 3, 4))
        self.assertLess(max(r[9], r[10]), 500)
        self.assertGreater(r[11], 950)
        genuine = next(r for r in rows if r[:3] == (1, 1, 1))
        self.assertLess(genuine[11], 900)

    def test_s82_one_geometry_for_every_sheet(self):
        q = 2089 / 10496
        for sheet in (0, 1, 10, 11):
            self.assertEqual([textures.level_scale(lv, sheet) for lv in range(6)], [1.0, 0.75, q, 0.125, 0.0625, 0.03125])
            self.assertEqual(textures.level_top(sheet), frozenset({1, 2}))
        self.assertEqual([textures.legacy(lv) for lv in range(5)], [False, False, False, True, True])
        self.assertEqual(textures.tile_set(self.root, 10).sheet, 10)

    def expansion_level_2(self, sheet):
        """Level 0: 8 x 8 tiles; level 2: the same map at the expansion's scale, at the top left of a 2 x 2 grid."""
        step = 1.0 / 4
        for x in range(8):
            for y in range(8):
                self.put(0, x, y, 0, tile(world, x * S * step, (7 - y) * S * step, step=step), sheet=sheet)
        q = textures.level_scale(2, 10)
        for x in range(2):
            for y in range(2):
                self.put(2, x, y, 0, tile(world, x * S / q * step, (1 - y) * S / q * step, step=step / q), sheet=sheet)
        rows, n = textures.check_level(textures.tile_set(self.root, sheet), 2)
        return [max(r[9], r[10]) for r in rows], n

    def test_s82_level_2_at_the_top_left_on_every_sheet(self):
        for sheet in (0, 10):
            got, n = self.expansion_level_2(sheet)
            self.assertEqual(n["near_level"], 0)
            self.assertEqual(len(got), 4)
            self.assertTrue(all(v > 950 for v in got), got)
            judge = textures.Judge(textures.tile_set(self.root, sheet), 2)
            judge.size = S
            self.assertAlmostEqual(judge.lift(2), 2 * S - 8 * S * textures.level_scale(2))

    def test_sums(self):
        px = bytes(v for k in range(16) for v in (k * 3, k * 3, k * 3, 255))
        sums = textures._Sums(px, 4)
        self.assertEqual(sums.total(0, 0, 4, 4), sum(k * 3 for k in range(16)))
        self.assertEqual(sums.total(1, 2, 3, 4), (9 + 10 + 13 + 14) * 3)


class OverviewTest(Base):
    def pixel(self, data, x, y):
        w, h, px = textures.png_decode(data)
        k = (y * w + x) * 4
        return tuple(px[k:k + 4])

    def test_another_drawing_is_left_out_and_its_inner_codes_tried(self):
        self.two_levels()
        self.put(3, 1, 1, 3, tile(other, 5, 5))      # codes 1 and 2 inside 3: 3 fails, then 2 fails, 1 is laid
        data, n = textures.overview(self.root, 0, 3)
        self.assertEqual((n["left_out"], n["near_level"]), (2, 4))
        want = tile(world, S, 0, patch=(10, 10, 30))      # top right tile: the genuine variant
        w, h, px = textures.png_decode(data)
        got = b"".join(px[(r * w + S) * 4:(r * w + 2 * S) * 4] for r in range(S))
        self.assertEqual(got, want)
        raw, n = textures.overview(self.root, 0, 3, check=False)
        self.assertEqual(n["left_out"], 0)
        self.assertNotEqual(raw, data)

    def test_one_code_where_exported_and_the_base_elsewhere(self):
        self.two_levels()
        data, _ = textures.overview(self.root, 0, 3, variant="code", code=2)
        w, h, px = textures.png_decode(data)
        top_right = b"".join(px[(r * w + S) * 4:(r * w + 2 * S) * 4] for r in range(S))
        bottom_left = b"".join(px[((S + r) * w) * 4:((S + r) * w + S) * 4] for r in range(S))
        self.assertEqual(top_right, tile(other, 0, 0))
        self.assertEqual(bottom_left, tile(world, 0, S))
        with self.assertRaises(ValueError):
            textures.overview(self.root, 0, 3, variant="code")

    def test_shrink(self):
        self.two_levels()
        full, n = textures.overview(self.root, 0, 3, variant="base")
        half, m = textures.overview(self.root, 0, 3, variant="base", shrink=2)
        self.assertEqual((m["width"], m["height"], m["tile"]), (S, S, S // 2))
        fw, fh, fpx = textures.png_decode(full)
        hw, hh, hpx = textures.png_decode(half)
        want = [sum(fpx[((2 * 5 + a) * fw + 2 * 7 + b) * 4] for a in (0, 1) for b in (0, 1)) for _ in (0,)][0]
        self.assertEqual(hpx[(5 * hw + 7) * 4], (want + 2) // 4)
        with self.assertRaises(ValueError):
            textures.overview(self.root, 0, 3, shrink=3)
        self.assertEqual(textures.shrink_rgba(b"\x01\x02\x03\x04" * 4, 2, 1), bytearray(b"\x01\x02\x03\x04" * 4))

    def test_labels_draw_borders_and_text(self):
        self.two_levels()
        plain, _ = textures.overview(self.root, 0, 3)
        data, _ = textures.overview(self.root, 0, 3, labels=True)
        self.assertEqual(self.pixel(data, 0, 40), textures.GRID_RGBA)          # the left border
        self.assertEqual(self.pixel(data, 40, S), textures.GRID_RGBA)          # the second row's top border
        w, h, px = textures.png_decode(data)
        white = sum(1 for k in range(0, len(px), 4) if px[k:k + 4] == b"\xff\xff\xff\xff")
        self.assertGreater(white, 100)
        self.assertEqual(self.pixel(plain, S - 1, S - 1), self.pixel(data, S - 1, S - 1))   # far from any label

    MASK = """<?xml version="1.0" ?>
<MapTileMaskList id="0">
\t<MapTileMask exists="1" id="10000" mask="1"/>
\t<MapTileMask exists="1" id="10100" mask="2"/>
\t<MapTileMask exists="0" id="10200" mask="7"/>
</MapTileMaskList>
"""

    def masked_level_1(self, mask=None):
        """S82: level 0 4 x 4 (so level 1's frame is 3 x 3); level 1 4 x 3 with a column outside the frame; at (0, 0)
        codes 1 (the mask) and 4 (another layout's); at (1, 0) code 2 (the mask); the game's mask file beside them."""
        for x in range(4):
            for y in range(4):
                self.put(0, x, y, 0, tile(world, x * S, y * S))
        for x in range(4):
            for y in range(3):
                self.put(1, x, y, 0, tile(world, x * S, y * S))
        self.put(1, 0, 0, 1, tile(world, 0, 0, patch=(10, 10, 20)))
        self.put(1, 0, 0, 4, tile(other, 0, 0))
        self.put(1, 1, 0, 2, tile(world, S, 0, patch=(30, 30, 20)))
        p = self.root / "unpacked" / "MENU_MapTile_M00.mtmsk"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((self.MASK if mask is None else mask).replace("\n", "\r\n").encode("utf-8"))

    def test_s82_the_masks_are_read_by_fixed_patterns_only(self):
        got = textures.parse_masks(self.MASK.encode())
        self.assertEqual(got, {1: {(0, 0): 1, (1, 0): 2, (2, 0): 0}})
        self.assertEqual(textures.parse_masks(b"\xef\xbb\xbf" + self.MASK.encode()), got)
        for bad in ('<!DOCTYPE x [<!ENTITY a "b">]>', '<MapTileMask id="1" exists="1" mask="1"/>',
                    '<MapTileMask exists="2" id="1" mask="1"/>', '<Other/>', 'text',
                    '<MapTileMask exists="1" id="1" mask="99999999999"/>'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                textures.parse_masks((self.MASK + bad + "\n").encode())
        with self.assertRaises(ValueError):
            textures.parse_masks(b"\xff\xfe")
        with self.assertRaises(ValueError):
            textures.parse_masks(b" " * (textures.MAX_MASK_BYTES + 1))

    def test_s82_the_tile_set_finds_the_masks_and_copies_must_agree(self):
        self.masked_level_1()
        ts = textures.tile_set(self.root, 0)
        self.assertTrue(ts.masked())
        self.assertEqual((ts.mask_at(1), ts.mask_at(0), ts.mask_copies), ({(0, 0): 1, (1, 0): 2, (2, 0): 0}, None, 1))
        self.assertFalse(textures.tile_set(self.root, 1).masked())         # another sheet's
        copy = self.root / "elsewhere" / "menu_maptile_m00.MTMSK"
        copy.parent.mkdir()
        copy.write_bytes((self.root / "unpacked" / "MENU_MapTile_M00.mtmsk").read_bytes())
        self.assertEqual(textures.tile_set(self.root, 0).mask_copies, 2)
        copy.write_bytes(self.MASK.replace('mask="2"', 'mask="3"').encode())
        with self.assertRaises(ValueError):
            textures.tile_set(self.root, 0)

    def test_s82_an_overview_draws_what_the_game_draws(self):
        self.masked_level_1()
        data, n = textures.overview(self.root, 0, 1)
        self.assertEqual((n["masks"], n["columns"], n["rows"], n["outside"], n["masked"], n["left_out"]),
                         (1, 3, 3, 3, 2, 1))
        w, h, px = textures.png_decode(data)
        bottom = (h - S) * w * 4

        def at(tx, c, r):
            k = bottom + (r * w + tx * S + c) * 4
            return bytes(px[k:k + 4])
        lit = tile(world, 0, 0, patch=(10, 10, 20))
        self.assertEqual(at(0, 15, 15), bytes(lit[(15 * S + 15) * 4:(15 * S + 15) * 4 + 4]))     # mask 1 drawn
        two = tile(world, S, 0, patch=(30, 30, 20))
        self.assertEqual(at(1, 35, 35), bytes(two[(35 * S + 35) * 4:(35 * S + 35) * 4 + 4]))     # mask 2 drawn
        base = tile(world, 2 * S, 0)
        self.assertEqual(at(2, 35, 35), bytes(base[(35 * S + 35) * 4:(35 * S + 35) * 4 + 4]))    # no pieces: base
        plain, m = textures.overview(self.root, 0, 1, masks=False, check=False)
        self.assertEqual((m["masks"], m["columns"], m["outside"]), (0, 4, 0))
        labelled, _ = textures.overview(self.root, 0, 1, labels=True)
        self.assertNotEqual(labelled, data)

    def test_s82_the_check_says_which_codes_the_game_draws(self):
        self.masked_level_1()
        ts = textures.tile_set(self.root, 0)
        rows, n = textures.check_level(ts, 1)
        by = {r[:3]: r[12] for r in rows}
        self.assertEqual((by[(0, 0, 0)], by[(0, 0, 1)], by[(0, 0, 4)], by[(1, 0, 2)], by[(3, 2, 0)]), (1, 1, 0, 1, 1))
        self.assertEqual((n["masks"], n["outside_masks"]), (1, 1))
        rows0, n0 = textures.check_level(ts, 0)
        self.assertEqual(({r[12] for r in rows0}, n0["masks"]), ({-1}, 0))        # no masks kept for level 0
        judge = textures.Judge(ts, 0)
        self.assertEqual(judge.other, 1)
        self.assertEqual(sorted(judge.there[(0, 0)]), [0, 1])                     # another layout's never stands in

    def test_label_lines_that_do_not_fit(self):
        canvas = bytearray(S * S * 4)
        textures.label(canvas, S, 0, 0, S, ["%d" % k for k in range(20)])
        self.assertEqual(bytes(canvas[0:4]), bytes(textures.GRID_RGBA))


class WorkersTest(Base):
    """S83: worker processes give the very rows and image one process gives (spawned, as on Windows)."""

    MASK = None                         # OverviewTest's, set below

    def test_s83_the_same_rows_with_worker_processes(self):
        GeneralTest.fine_level(self, 0, 8, foreign_at=(3, 4))
        ts = textures.tile_set(self.root, 0)
        one, n1 = textures.check_level(ts, 0)
        with mock.patch.object(textures, "POOL_MIN", 1):
            two, n2 = textures.check_level(ts, 0, workers=2, memory=32 * 2 ** 20)
        self.assertEqual(one, two)
        self.assertEqual((n1["workers"], n2["workers"]), (1, 2))

    def test_s83_the_same_image_with_worker_processes(self):
        GeneralTest.fine_level(self, 0, 8, foreign_at=(3, 4))
        a, na = textures.overview(self.root, 0, 0, labels=True)
        with mock.patch.object(textures, "POOL_MIN", 1):
            b, nb = textures.overview(self.root, 0, 0, labels=True, workers=2)
        self.assertEqual(a, b)
        self.assertEqual(na, nb)

    def test_s83_the_masks_image_with_worker_processes(self):
        OverviewTest.masked_level_1(self)
        a, na = textures.overview(self.root, 0, 1)
        with mock.patch.object(textures, "POOL_MIN", 1):
            b, nb = textures.overview(self.root, 0, 1, workers=3, memory=8 * 2 ** 20)
        self.assertEqual((a, na), (b, nb))

    def test_s83_cancel_stops_the_workers(self):
        GeneralTest.fine_level(self, 0, 8)
        stop = threading.Event()
        stop.set()
        with mock.patch.object(textures, "POOL_MIN", 1), self.assertRaises(textures.Cancelled):
            textures.check_level(textures.tile_set(self.root, 0), 0, workers=2, cancel=stop)

    def test_s83_chunks_keep_the_order_and_share_the_weight(self):
        places = [(x, y) for x in range(4) for y in range(5)]
        chunks = textures._chunks(places, [3] * 20, 2)
        self.assertEqual([p for c in chunks for p in c], places)
        self.assertEqual([len(c) for c in chunks], [2] * 10)          # 60 // 8 = 7 a chunk: two places of 3 each

    def test_s83_the_cache_follows_the_memory_given(self):
        judge = textures.Judge(textures.TileSet(), 0)
        self.assertEqual(judge.keep(), textures.Judge.KEEP)
        judge.size, judge.keep_bytes = 256, 100 * 257 * 257 * 8
        self.assertEqual(judge.keep(), 100)
        judge.keep_bytes = 1
        self.assertEqual(judge.keep(), 16)


class NativeTest(unittest.TestCase):
    """S83: Windows' own decoder, used only where it decodes as DataPiler does."""

    def test_s83_the_self_test_images_and_colour_chunks(self):
        for d in textures._selftest_pngs():
            w, h, px = textures._python_decode(d)
            self.assertEqual((w, h, len(px)), (7, 5, 140))
            self.assertIn(b"gAMA", d)
            self.assertNotIn(b"gAMA", textures._without_colour(d))
            self.assertEqual(textures._python_decode(textures._without_colour(d)), (w, h, px))

    @unittest.skipIf(sys.platform == "win32", "elsewhere than Windows")
    def test_s83_elsewhere_datapiler_decodes_alone(self):
        self.assertFalse(textures.native_decoding())

    @unittest.skipUnless(sys.platform == "win32", "Windows' own decoder")
    def test_s83_windows_decodes_as_datapiler_does(self):
        self.assertTrue(textures.native_decoding())
        big = bytes((x * 7 + y * 3 + k * 50) % 256 if k < 3 else (x * y) % 256 for y in range(64) for x in range(64)
                    for k in range(4))
        for d in textures._selftest_pngs() + [textures.png_filtered(64, 64, 6, big, [0, 1, 2, 3, 4])]:
            self.assertEqual(textures.png_decode(d), textures._python_decode(d))


class JobTest(unittest.TestCase):
    def doc(self, **over):
        op = {"op": "make_map_overview", "name": "ov", "sheet": 0, "level": 2}
        op.update(over)
        return json.dumps({"format": "datapiler-job/1", "id": "test-0300-tiles", "title": "tiles", "ops": [op]}).encode()

    def where(self, raw):
        try:
            jobs.check(raw, known_ids=(), share_names={})
        except jobs.JobRefused as e:
            return sorted(r.where for r in e.refusals)
        return []

    def test_overview_options(self):
        self.assertEqual(self.where(self.doc(labels=True, check=False, min_match=850)), [])
        self.assertEqual(self.where(self.doc(masks=False)), [])
        self.assertEqual(self.where(self.doc(masks="no")), ["ops[0].masks"])
        self.assertEqual(self.where(self.doc(variant="code", code=0x4000)), [])
        self.assertEqual(self.where(self.doc(code=1)), ["ops[0].code"])
        self.assertEqual(self.where(self.doc(variant="code")), ["ops[0].code"])
        self.assertEqual(self.where(self.doc(variant="code", code=-1)), ["ops[0].code"])
        self.assertEqual(self.where(self.doc(labels="yes")), ["ops[0].labels"])
        self.assertEqual(self.where(self.doc(min_match=1001)), ["ops[0].min_match"])
        self.assertEqual(self.where(self.doc(shrink=4)), [])
        self.assertEqual(self.where(self.doc(shrink=3)), ["ops[0].shrink"])
        self.assertEqual(self.where(self.doc(shrink=True)), ["ops[0].shrink"])

    def test_check_map_tiles(self):
        raw = json.dumps({"format": "datapiler-job/1", "id": "test-0301-tiles", "title": "tiles", "ops": [
            {"op": "check_map_tiles", "as": "t_check", "sheet": 0, "level": 2},
            {"op": "write_share", "name": "tile-check", "tables": ["t_check"],
             "columns": {"t_check": [c for c, _ in textures.TILE_CHECK_COLUMNS]}}]}).encode()
        self.assertEqual(self.where(raw), [])
        bad = json.dumps({"format": "datapiler-job/1", "id": "test-0302-tiles", "title": "tiles", "ops": [
            {"op": "check_map_tiles", "as": "t_check", "sheet": 0, "level": 12}]}).encode()
        self.assertEqual(self.where(bad), ["ops[0].level"])


WorkersTest.MASK = OverviewTest.MASK

if __name__ == "__main__":
    unittest.main()
