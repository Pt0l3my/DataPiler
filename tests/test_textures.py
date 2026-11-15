"""S73 (DP25): exported map tiles found anywhere in DataPiler's folder, as numbers. Invented files only."""
import os
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datapiler import textures  # noqa: E402


def png(w: int, h: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"


def dds(w: int, h: int) -> bytes:
    return b"DDS " + struct.pack("<I", 124) + struct.pack("<I", 0) + struct.pack("<II", h, w) + b"\x00" * 8


class FindTilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel: str, data: bytes) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def test_tiles_anywhere_with_sizes_and_copies(self):
        self.put("workspace/inbox/71_maptile/MENU_MapTile_M00_L0_00_01_00000000.png", png(256, 256))
        self.put("exports/deep/er/MENU_MapTile_M00_L0_00_01_00000000.png", png(256, 256))      # a copy
        self.put("exports/MENU_MapTile_M01_L2_03_04_0000a00F.dds", dds(512, 256))
        self.put("exports/menu_maptile_m00_l1_02_02_00000001.PNG", png(128, 128))                # case
        self.put("exports/MENU_MapTile_M00_L0_09_09_00000000.tga", b"not a header we read")
        self.put("exports/notes.png", png(1, 1))                                                   # not a tile
        self.put(".venv/MENU_MapTile_M00_L0_05_05_00000000.png", png(256, 256))                  # left out
        self.put("workspace/bin/x/MENU_MapTile_M00_L0_06_06_00000000.png", png(256, 256))        # left out
        rows, n = textures.find_tiles(self.root, skip=(self.root / "workspace" / "bin",))
        self.assertEqual(rows, [(0, 0, 0, 1, 0, 256, 256, 2), (0, 0, 9, 9, 0, -1, -1, 1),
                                (0, 1, 2, 2, 1, 128, 128, 1), (1, 2, 3, 4, 0xA00F, 512, 256, 1)])
        self.assertEqual((n["found"], n["unread"], n["stopped"]), (5, 1, 0))

    def test_cancel(self):
        self.put("a/MENU_MapTile_M00_L0_00_00_00000000.png", png(2, 2))
        ev = threading.Event()
        ev.set()
        with self.assertRaises(textures.Cancelled):
            textures.find_tiles(self.root, cancel=ev)

    def test_image_size_of_other_headers(self):
        self.put("b.bmp", b"BM" + b"\x00" * 16 + struct.pack("<ii", 64, -32) + b"\x00" * 6)
        self.put("c.png", b"\x89PNG\r\n")
        self.assertEqual(textures.image_size(self.root / "b.bmp"), (64, 32))
        self.assertEqual(textures.image_size(self.root / "c.png"), (-1, -1))
        self.assertEqual(textures.image_size(self.root / "missing.png"), (-1, -1))


if __name__ == "__main__":
    unittest.main()
