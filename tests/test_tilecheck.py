"""S78: which exported map tiles belong to one image - the tile set, the check against the next level, labels and the
one-code overview. Invented patterns only: no game image is used."""
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

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

    def put(self, level, x, y, code, px, folder="ex"):
        p = self.root / folder / ("MENU_MapTile_M00_L%d_%02d_%02d_%08X.png" % (level, x, y, code))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(textures.png_encode(S, S, px))

    def two_levels(self):
        """Level 2: 2 x 2 tiles of the world, each with a genuine variant (code 1, a lit patch) and, at (1, 1), a
        variant from another drawing (code 2). Level 3: the world at half size, one tile, base and code 1."""
        for x in (0, 1):
            for y in (0, 1):
                top = (1 - y) * S                    # rows from the bottom: y 1 is the top row of the image
                self.put(2, x, y, 0, tile(world, x * S, top))
                self.put(2, x, y, 1, tile(world, x * S, top, patch=(10, 10, 30)))
        self.put(2, 1, 1, 2, tile(other, 0, 0))
        self.put(3, 0, 0, 0, tile(world, 0, 0, step=2.0))
        self.put(3, 0, 0, 1, tile(world, 0, 0, step=2.0))


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
        rows, n = textures.check_level(textures.tile_set(self.root, 0), 2)
        by = {(r[0], r[1], r[2]): dict(zip([c for c, _ in textures.TILE_CHECK_COLUMNS], r)) for r in rows}
        self.assertEqual(len(rows), 9)
        self.assertEqual((n["near_level"], n["other_image"], n["folders"]), (3, 1, 1))
        base = by[(0, 0, 0)]
        self.assertEqual((base["drawn"], base["like"], base["near_level"], base["near_code"]), (0, 1000, 3, 0))
        self.assertGreater(base["near"], 950)
        genuine = by[(1, 1, 1)]
        self.assertEqual(genuine["near_code"], 1)
        self.assertTrue(textures.passes(genuine["near"], genuine["near_base"]))
        self.assertEqual(genuine["drawn"], round(1000 * 30 * 30 / (S * S)))      # the lit patch only
        foreign = by[(1, 1, 2)]
        self.assertEqual(foreign["near_code"], 0)                               # level 3 has no code 2: its base
        self.assertFalse(textures.passes(foreign["near"], foreign["near_base"]))
        self.assertLess(max(foreign["near"], foreign["near_base"]), 500)

    def test_the_coarsest_level_is_measured_against_the_finer_one(self):
        self.two_levels()
        judge = textures.Judge(textures.tile_set(self.root, 0), 3)
        self.assertEqual((judge.other, judge.up), (2, False))
        rows, n = textures.check_level(judge.ts, 3)
        self.assertEqual(n["near_level"], 2)
        self.assertTrue(all(max(r[9], r[10]) > 950 for r in rows), rows)

    def test_nothing_to_measure(self):
        self.put(0, 0, 0, 0, tile(world, 0, 0))
        self.put(0, 0, 0, 4, tile(other, 0, 0))
        rows, n = textures.check_level(textures.tile_set(self.root, 0), 0)
        self.assertEqual(n["near_level"], -1)
        self.assertEqual([r[7:] for r in rows], [(-1, -1, textures.UNMEASURED, textures.UNMEASURED)] * 2)
        self.assertTrue(textures.passes(textures.UNMEASURED, textures.UNMEASURED))
        flat = [5.0] * 16
        self.assertEqual(textures.ncc(flat, [float(k) for k in range(16)]), textures.UNMEASURED)
        self.assertEqual(textures.ncc([1.0, 2.0, 30.0], [2.0, 4.0, 60.0]), 1000)

    def test_the_table_is_numbers_the_guard_lets_through(self):
        self.assertTrue(all(t == "int" for _, t in textures.TILE_CHECK_COLUMNS))
        words = guard.fixed_words()
        self.assertTrue(all(c in words for c, _ in textures.TILE_CHECK_COLUMNS))


class OverviewTest(Base):
    def pixel(self, data, x, y):
        w, h, px = textures.png_decode(data)
        k = (y * w + x) * 4
        return tuple(px[k:k + 4])

    def test_another_drawing_is_left_out_and_its_inner_codes_tried(self):
        self.two_levels()
        self.put(2, 1, 1, 3, tile(other, 5, 5))      # codes 1 and 2 inside 3: 3 fails, then 2 fails, 1 is laid
        data, n = textures.overview(self.root, 0, 2)
        self.assertEqual((n["left_out"], n["near_level"]), (2, 3))
        want = tile(world, S, 0, patch=(10, 10, 30))      # top right tile: the genuine variant
        w, h, px = textures.png_decode(data)
        got = b"".join(px[(r * w + S) * 4:(r * w + 2 * S) * 4] for r in range(S))
        self.assertEqual(got, want)
        raw, n = textures.overview(self.root, 0, 2, check=False)
        self.assertEqual(n["left_out"], 0)
        self.assertNotEqual(raw, data)

    def test_one_code_where_exported_and_the_base_elsewhere(self):
        self.two_levels()
        data, _ = textures.overview(self.root, 0, 2, variant="code", code=2)
        w, h, px = textures.png_decode(data)
        top_right = b"".join(px[(r * w + S) * 4:(r * w + 2 * S) * 4] for r in range(S))
        bottom_left = b"".join(px[((S + r) * w) * 4:((S + r) * w + S) * 4] for r in range(S))
        self.assertEqual(top_right, tile(other, 0, 0))
        self.assertEqual(bottom_left, tile(world, 0, S))
        with self.assertRaises(ValueError):
            textures.overview(self.root, 0, 2, variant="code")

    def test_labels_draw_borders_and_text(self):
        self.two_levels()
        plain, _ = textures.overview(self.root, 0, 2)
        data, _ = textures.overview(self.root, 0, 2, labels=True)
        self.assertEqual(self.pixel(data, 0, 40), textures.GRID_RGBA)          # the left border
        self.assertEqual(self.pixel(data, 40, S), textures.GRID_RGBA)          # the second row's top border
        w, h, px = textures.png_decode(data)
        white = sum(1 for k in range(0, len(px), 4) if px[k:k + 4] == b"\xff\xff\xff\xff")
        self.assertGreater(white, 100)
        self.assertEqual(self.pixel(plain, S - 1, S - 1), self.pixel(data, S - 1, S - 1))   # far from any label

    def test_label_lines_that_do_not_fit(self):
        canvas = bytearray(S * S * 4)
        textures.label(canvas, S, 0, 0, S, ["%d" % k for k in range(20)])
        self.assertEqual(bytes(canvas[0:4]), bytes(textures.GRID_RGBA))


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
        self.assertEqual(self.where(self.doc(variant="code", code=0x4000)), [])
        self.assertEqual(self.where(self.doc(code=1)), ["ops[0].code"])
        self.assertEqual(self.where(self.doc(variant="code")), ["ops[0].code"])
        self.assertEqual(self.where(self.doc(variant="code", code=-1)), ["ops[0].code"])
        self.assertEqual(self.where(self.doc(labels="yes")), ["ops[0].labels"])
        self.assertEqual(self.where(self.doc(min_match=1001)), ["ops[0].min_match"])

    def test_check_map_tiles(self):
        raw = json.dumps({"format": "datapiler-job/1", "id": "test-0301-tiles", "title": "tiles", "ops": [
            {"op": "check_map_tiles", "as": "t_check", "sheet": 0, "level": 2},
            {"op": "write_share", "name": "tile-check", "tables": ["t_check"],
             "columns": {"t_check": [c for c, _ in textures.TILE_CHECK_COLUMNS]}}]}).encode()
        self.assertEqual(self.where(raw), [])
        bad = json.dumps({"format": "datapiler-job/1", "id": "test-0302-tiles", "title": "tiles", "ops": [
            {"op": "check_map_tiles", "as": "t_check", "sheet": 0, "level": 12}]}).encode()
        self.assertEqual(self.where(bad), ["ops[0].level"])


if __name__ == "__main__":
    unittest.main()
