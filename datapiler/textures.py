"""Exported map tiles (S73, DP25): the textures Smithbox's Texture Viewer exported, found anywhere in DataPiler's folder.

The owner exports the game's map tiles from Smithbox (its Texture Viewer, Data Export) into any folder inside
DataPiler's own folder. `find_tiles` walks that folder, keeps the files whose names are the map tiles' names, and reads
each one's width and height from the first bytes of its file header. It never decodes an image, never reads past the
header, and keeps no path or name outside this module: what it gives back is numbers (the sheet, level, column, row and
eight-digit code the name carries, the size, and how many copies were found). Folders that hold DataPiler's own
environment, logs, update downloads or the Deleted bin are left out, as are links."""

from __future__ import annotations

import os
import re
import struct
import threading
import zlib
from array import array
from pathlib import Path
from typing import Callable, Collection

TILE_RX = re.compile(r"MENU_MapTile_M(\d{2})_L(\d)_(\d{2})_(\d{2})_([0-9A-Fa-f]{8})\.(png|dds|bmp|tga|tif|tiff|jpg|jpeg|webp)",
                     re.IGNORECASE)
IMAGE_EXTS = (".png", ".dds", ".bmp", ".tga", ".tif", ".tiff", ".jpg", ".jpeg", ".webp")
SKIP_DIRS = frozenset((".git", ".venv", "__pycache__", "logs", "node_modules"))
MAX_DEPTH = 16                 # folders below DataPiler's own
MAX_FILES = 2_000_000          # files looked at, at most: the walk stops there and says so
COLUMNS: tuple[tuple[str, str], ...] = (("sheet", "int"), ("level", "int"), ("x", "int"), ("y", "int"),
                                        ("code", "int"), ("width", "int"), ("height", "int"), ("copies", "int"))

_PNG = b"\x89PNG\r\n\x1a\n"


class Cancelled(Exception):
    pass


def image_size(path: Path) -> tuple[int, int]:
    """(width, height) from the file's header, for PNG, DDS and BMP; (-1, -1) for another type or a header that does
    not parse. Reads 32 bytes at most."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return -1, -1
    if head.startswith(_PNG) and len(head) >= 24 and head[12:16] == b"IHDR":
        w, h = struct.unpack(">II", head[16:24])
        return int(w), int(h)
    if head.startswith(b"DDS ") and len(head) >= 20:
        h, w = struct.unpack("<II", head[12:20])
        return int(w), int(h)
    if head.startswith(b"BM") and len(head) >= 26:
        w, h = struct.unpack("<ii", head[18:26])
        return int(w), abs(int(h))
    return -1, -1


def find_tiles(root: Path, *, skip: Collection[Path] = (), cancel: threading.Event | None = None,
               progress: Callable[[int], None] | None = None) -> tuple[list[tuple[int, ...]], dict[str, int]]:
    """Every exported map tile under root, as rows of COLUMNS (one per distinct tile and size, with how many copies),
    sorted; and counts: files looked at, tiles found, sizes not read, whether the walk stopped at MAX_FILES."""
    root = Path(root)
    skipped = {os.path.normcase(os.path.abspath(str(s))) for s in skip}
    copies: dict[tuple[int, ...], int] = {}
    looked = found = unread = 0
    stopped = False
    base_depth = len(Path(os.path.abspath(str(root))).parts)
    for here, dirs, files in os.walk(root, followlinks=False):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        depth = len(Path(os.path.abspath(here)).parts) - base_depth
        keep = []
        for d in dirs:
            full = os.path.join(here, d)
            if d.lower() in SKIP_DIRS or os.path.islink(full) or depth >= MAX_DEPTH:
                continue
            if os.path.normcase(os.path.abspath(full)) in skipped:
                continue
            keep.append(d)
        dirs[:] = sorted(keep)
        for name in files:
            looked += 1
            if looked > MAX_FILES:
                stopped = True
                break
            m = TILE_RX.fullmatch(name)
            if m is None:
                continue
            full = os.path.join(here, name)
            if os.path.islink(full):
                continue
            found += 1
            w, h = image_size(Path(full))
            if w < 0:
                unread += 1
            key = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5), 16), w, h)
            copies[key] = copies.get(key, 0) + 1
            if progress is not None and found % 200 == 0:
                progress(found)
        if stopped:
            break
    rows = [k + (n,) for k, n in sorted(copies.items())]
    return rows, {"looked": looked, "found": found, "unread": unread, "stopped": int(stopped)}


# ------------------------------------------------------------------------------------------------ overview (S75)

MAX_SIDE = 4096                # the largest overview, in pixels a side: level 2 at most on the base map
ROWS_FROM = ("bottom", "top")  # where tile row 0 sits: the bottom, by WHY§62's fit, unless a job says otherwise


def widest(codes: Collection[int]) -> list[int]:
    """S77: the codes no other code of the set contains (bits are map pieces, WHY§62), lowest first. A position's
    exported variants are every subset of these and nothing else (WHY§63): pieces whose drawings meet in a tile share
    a variant; pieces apart in it have one each, which the game lays together."""
    nonzero = sorted(set(c for c in codes if c))
    return [c for c in nonzero if not any(d != c and d & c == c for d in nonzero)]


class TileSet:
    """S78: the exported PNG tiles of one sheet, every level: {level: {(x, y): {code: path}}}, the first copy of each
    name in walk order; how many copies of each name were found; which folder each kept file is in, numbered 1, 2, ...
    in walk order (folders themselves never leave this module: numbers only)."""

    def __init__(self) -> None:
        self.levels: dict[int, dict[tuple[int, int], dict[int, Path]]] = {}
        self.copies: dict[tuple[int, int, int, int], int] = {}
        self.folder: dict[Path, int] = {}
        self.folders = 0
        self.stopped = False

    def grid(self, level: int) -> tuple[int, int]:
        at = self.levels.get(level) or {}
        if not at:
            return 0, 0
        return max(x for x, _ in at) + 1, max(y for _, y in at) + 1


def tile_set(root: Path, sheet: int, *, skip: Collection[Path] = (),
             cancel: threading.Event | None = None) -> TileSet:
    """Every exported PNG tile of one sheet found under root (S78), as a TileSet. Paths never leave this module's
    callers' logs."""
    root = Path(root)
    skipped = {os.path.normcase(os.path.abspath(str(s))) for s in skip}
    ts = TileSet()
    numbers: dict[str, int] = {}
    base_depth = len(Path(os.path.abspath(str(root))).parts)
    looked = 0
    for here, dirs, files in os.walk(root, followlinks=False):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        depth = len(Path(os.path.abspath(here)).parts) - base_depth
        dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_DIRS and depth < MAX_DEPTH
                         and not os.path.islink(os.path.join(here, d))
                         and os.path.normcase(os.path.abspath(os.path.join(here, d))) not in skipped)
        for name in sorted(files):
            looked += 1
            if looked > MAX_FILES:
                ts.stopped = True
                return ts
            m = TILE_RX.fullmatch(name)
            if m is None or m.group(6).lower() != "png" or int(m.group(1)) != sheet:
                continue
            full = Path(here) / name
            if os.path.islink(full):
                continue
            level, x, y, code = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5), 16)
            key = (level, x, y, code)
            ts.copies[key] = ts.copies.get(key, 0) + 1
            at = ts.levels.setdefault(level, {}).setdefault((x, y), {})
            if code not in at:
                at[code] = full
                ts.folder[full] = numbers.setdefault(here, len(numbers) + 1)
    ts.folders = len(numbers)
    return ts


def tile_files(root: Path, sheet: int, level: int, *, skip: Collection[Path] = (),
               cancel: threading.Event | None = None
               ) -> dict[tuple[int, int], tuple[tuple[tuple[int, Path], ...], Path | None]]:
    """For each tile position of one sheet and level, the exported files of its widest revealed variants (S77: every
    piece revealed is these laid together over the base) and of its base variant (code 0), if exported.
    {(x, y): (((code, path), ...), base path or None)}. Paths never leave this module's callers' logs."""
    at = tile_set(root, sheet, skip=skip, cancel=cancel).levels.get(level, {})
    return {k: (tuple((c, v[c]) for c in widest(v)), v.get(0)) for k, v in at.items()}


def lay_over(canvas: bytearray, over: bytes | bytearray, base: bytes | bytearray | None = None) -> int:
    """S77: `over` drawn on `canvas` in place (all RGBA, one size), by its alpha, wherever it differs from the tile's
    base variant `base` (everywhere when there is none): a revealed variant is the base with its pieces drawn in, so
    what differs is its pieces, and several laid on one canvas reveal them all. Straight alpha, rounded. The number of
    pixels drawn."""
    n = len(over) // 4
    if base is not None and bytes(over) == bytes(base):
        return 0
    o32 = memoryview(over).cast("B").cast("I")
    b32 = memoryview(base).cast("B").cast("I") if base is not None else None
    drawn = 0
    for k in range(n):
        if b32 is not None and o32[k] == b32[k]:
            continue
        j = k * 4
        a = over[j + 3]
        if a == 0:
            continue
        drawn += 1
        if a == 255:
            canvas[j:j + 4] = over[j:j + 4]
            continue
        ca = canvas[j + 3]
        ia = 255 - a
        for c in range(3):
            canvas[j + c] = (over[j + c] * a + canvas[j + c] * ia + 127) // 255
        canvas[j + 3] = a + (ca * ia + 127) // 255
    return drawn


def png_decode(data: bytes) -> tuple[int, int, bytearray]:
    """(width, height, RGBA bytes) of a non-interlaced 8-bit PNG: grey, grey with alpha, RGB, RGBA or a palette (with
    tRNS). ValueError for anything else."""
    if not data.startswith(_PNG):
        raise ValueError("not a PNG")
    pos = 8
    w = h = depth = ctype = interlace = None
    idat = []
    palette = b""
    trns = b""
    while pos + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h, depth, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if w is None or not idat:
        raise ValueError("a PNG without its header or image data")
    if depth != 8 or interlace != 0 or ctype not in (0, 2, 3, 4, 6):
        raise ValueError("a PNG DataPiler does not read (only 8 bits a channel, not interlaced)")
    if w <= 0 or h <= 0 or w * h > MAX_SIDE * MAX_SIDE:
        raise ValueError("a PNG of an unexpected size")
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    if len(raw) < h * (stride + 1):
        raise ValueError("a PNG cut short")
    pix = bytearray(h * stride)
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif f != 0:
            raise ValueError("a PNG with an unknown row filter")
        pix[y * stride:(y + 1) * stride] = line
        prev = line
    if ctype == 6:
        return w, h, pix
    out = bytearray(w * h * 4)
    if ctype == 2:
        out[0::4], out[1::4], out[2::4] = pix[0::3], pix[1::3], pix[2::3]
        out[3::4] = b"\xff" * (w * h)
    elif ctype == 0:
        out[0::4] = out[1::4] = out[2::4] = pix
        out[3::4] = b"\xff" * (w * h)
    elif ctype == 4:
        out[0::4] = out[1::4] = out[2::4] = pix[0::2]
        out[3::4] = pix[1::2]
    else:
        if not palette:
            raise ValueError("a palette PNG without its palette")
        for k, idx in enumerate(pix):
            j = idx * 3
            out[k * 4:k * 4 + 3] = palette[j:j + 3] if j + 3 <= len(palette) else b"\x00\x00\x00"
            out[k * 4 + 3] = trns[idx] if idx < len(trns) else 255
    return w, h, out


def png_encode(w: int, h: int, rgba: bytes | bytearray) -> bytes:
    """An 8-bit RGBA PNG, each row unfiltered, deflated."""
    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (_PNG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------------------------------------ tile check (S78)
#
# The overviews of 0.2.25 to 0.2.27 mixed two images at level 2: next to variants that are the base with pieces drawn
# in, the export holds variants that carry another drawing of the whole map, at three quarters of the level's scale
# (WHY§64). The file names hold nothing to tell them apart, so DataPiler looks: a level whose grid is twice as fine as
# the next level's must look like it at half size (levels 2, 3 and 4 nest so, from the bottom left). Each variant is
# measured against the next level's variant for the same pieces, and its base, on small grey thumbnails.

THUMB = 64                   # a tile's grey thumbnail, pixels a side
UNMEASURED = -9999           # a score that could not be measured: no next level, a tile too small, or nothing in it
MATCH_MIN = 700              # per mille: a variant that matches the next level less than this is another image's
FLAT = 2.0                   # grey levels: a thumbnail part flatter than this holds nothing to compare
TILE_CHECK_COLUMNS: tuple[tuple[str, str], ...] = (
    ("x", "int"), ("y", "int"), ("code", "int"), ("folder", "int"), ("copies", "int"), ("drawn", "int"),
    ("like", "int"), ("near_level", "int"), ("near_code", "int"), ("near", "int"), ("near_base", "int"))


def thumb(px: bytes | bytearray, size: int) -> array:
    """The THUMB x THUMB grey means of a size x size RGBA tile (size a multiple of THUMB), rows from its top."""
    k = size // THUMB
    out = array("f", bytes(4 * THUMB * THUMB))
    line = size * 4
    for r in range(THUMB * k):
        at = r * line
        R = px[at:at + line:4]
        G = px[at + 1:at + line:4]
        B = px[at + 2:at + line:4]
        o = (r // k) * THUMB
        for c in range(THUMB):
            j = c * k
            out[o + c] += sum(R[j:j + k]) + sum(G[j:j + k]) + sum(B[j:j + k])
    d = 3.0 * k * k
    for i in range(THUMB * THUMB):
        out[i] /= d
    return out


def _half(t: array) -> list[float]:
    """A thumbnail at half size: (THUMB/2)^2 means of 2 x 2."""
    h = THUMB // 2
    return [(t[2 * r * THUMB + 2 * c] + t[2 * r * THUMB + 2 * c + 1] + t[(2 * r + 1) * THUMB + 2 * c]
             + t[(2 * r + 1) * THUMB + 2 * c + 1]) / 4 for r in range(h) for c in range(h)]


def _quarter(t: array, qx: int, qy: int) -> list[float]:
    """One quarter of a thumbnail: qx 0 left, 1 right; qy 0 bottom, 1 top (tile rows count from the bottom)."""
    h = THUMB // 2
    r0 = 0 if qy == 1 else h
    return [t[(r0 + r) * THUMB + qx * h + c] for r in range(h) for c in range(h)]


def ncc(a: list[float], b: list[float]) -> int:
    """The correlation of two equal lists of grey values, per mille, or UNMEASURED when either is flat."""
    n = len(a)
    if n == 0 or n != len(b):
        return UNMEASURED
    ma = sum(a) / n
    mb = sum(b) / n
    sab = saa = sbb = 0.0
    for u, v in zip(a, b):
        du = u - ma
        dv = v - mb
        sab += du * dv
        saa += du * du
        sbb += dv * dv
    if saa / n < FLAT * FLAT or sbb / n < FLAT * FLAT:
        return UNMEASURED
    return int(round(1000 * sab / (saa * sbb) ** 0.5))


def _within(codes: Collection[int], code: int) -> int | None:
    """The exported code with the most bits (then the highest) whose pieces are all among `code`'s."""
    best = None
    for c in codes:
        if c & ~code == 0 and (best is None or (bin(c).count("1"), c) > (bin(best).count("1"), best)):
            best = c
    return best


def differs(over: bytes | bytearray, base: bytes | bytearray) -> int:
    """How many pixels of two equal RGBA images differ."""
    if bytes(over) == bytes(base):
        return 0
    o32 = memoryview(over).cast("B").cast("I")
    b32 = memoryview(base).cast("B").cast("I")
    return sum(1 for u, v in zip(o32, b32) if u != v)


def nests(finer: tuple[int, int], coarser: tuple[int, int]) -> bool:
    """Whether a coarser grid is the finer one at half size (levels 2, 3 and 4; not 0 and 1, whose steps are three
    quarters and a third): a side of half the finer one's, rounded up, or one more where the export leaves an edge."""
    return all((f + 1) // 2 <= c <= (f + 1) // 2 + 1 for f, c in zip(finer, coarser)) and min(finer) > 0


class Judge:
    """S78: measures a level's exported variants against the next level whose grid nests with it by two (the coarser
    one, else the finer one), from the bottom left. Decoded thumbnails of the other level are kept."""

    def __init__(self, ts: TileSet, level: int, cancel: threading.Event | None = None) -> None:
        self.ts = ts
        self.level = level
        self.cancel = cancel
        self.at = ts.levels.get(level, {})
        self.other: int | None = None
        self.up = True
        if level + 1 in ts.levels and nests(ts.grid(level), ts.grid(level + 1)):
            self.other = level + 1
        elif level - 1 in ts.levels and nests(ts.grid(level - 1), ts.grid(level)):
            self.other, self.up = level - 1, False
        self.size: int | None = None
        self._kept: dict[Path, array | None] = {}

    def decode(self, path: Path) -> bytearray:
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()
        with open(path, "rb") as f:
            w, h, px = png_decode(f.read())
        if w != h or (self.size is not None and w != self.size):
            raise ValueError("the tiles are not all square and of one size")
        self.size = w
        return px

    def thumb(self, px: bytes | bytearray) -> array | None:
        if self.size is None or self.size < THUMB or self.size % THUMB:
            return None
        return thumb(px, self.size)

    def _other(self, path: Path) -> array | None:
        if path not in self._kept:
            self._kept[path] = self.thumb(self.decode(path))
        return self._kept[path]

    def near(self, x: int, y: int, code: int, t: array | None) -> tuple[int, int, int]:
        """(the other level's code compared or -1, the match with it, the match with the other level's base), per
        mille; UNMEASURED where it cannot be measured."""
        if self.other is None or t is None:
            return -1, UNMEASURED, UNMEASURED
        there = self.ts.levels[self.other]
        if self.up:
            parts = [(_half(t), (x // 2, y // 2), (x % 2, y % 2))]
        else:
            parts = [(_quarter(t, i, j), (2 * x + i, 2 * y + j), None) for j in (0, 1) for i in (0, 1)]
        chosen = -1
        pairs: dict[str, tuple[list[float], list[float]]] = {"code": ([], []), "base": ([], [])}
        for part, pos, quarter in parts:
            codes = there.get(pos) or {}
            for kind, want in (("code", _within(codes, code)), ("base", 0 if 0 in codes else None)):
                o = self._other(codes[want]) if want is not None else None
                if o is None:
                    continue
                if kind == "code":
                    chosen = max(chosen, 0) | want
                pairs[kind][0].extend(part)
                pairs[kind][1].extend(_quarter(o, *quarter) if quarter is not None else _half(o))
        return chosen, ncc(*pairs["code"]), ncc(*pairs["base"])


def passes(near: int, near_base: int, min_match: int = MATCH_MIN) -> bool:
    """S78: a variant is kept unless it was measured and matched the next level below min_match both ways."""
    best = max(near, near_base)
    return best == UNMEASURED or best >= min_match


def check_level(ts: TileSet, level: int, *, cancel: threading.Event | None = None,
                progress: Callable[[int, int], None] | None = None) -> tuple[list[tuple[int, ...]], dict[str, int]]:
    """S78: one row of TILE_CHECK_COLUMNS per exported variant of a sheet's level: where it is, which folder it was
    found in (numbered) and how many copies, how much of it differs from the base (per mille of pixels), how like the
    base it is, and how well it matches the next level, per mille (UNMEASURED where it cannot be). Numbers only."""
    judge = Judge(ts, level, cancel)
    rows: list[tuple[int, ...]] = []
    total = sum(len(v) for v in judge.at.values())
    done = 0
    for (x, y), codes in sorted(judge.at.items()):
        base_px = judge.decode(codes[0]) if 0 in codes else None
        base_t = judge.thumb(base_px) if base_px is not None else None
        for code in sorted(codes):
            px = base_px if code == 0 and base_px is not None else judge.decode(codes[code])
            t = base_t if code == 0 and base_t is not None else judge.thumb(px)
            drawn = UNMEASURED if base_px is None else (1000 * differs(px, base_px) + len(px) // 8) // (len(px) // 4)
            like = UNMEASURED if base_t is None or t is None else (1000 if code == 0 else ncc(list(t), list(base_t)))
            near_code, near, near_base = judge.near(x, y, code, t)
            rows.append((x, y, code, ts.folder.get(codes[code], 0), ts.copies.get((level, x, y, code), 1), drawn,
                         like, judge.other if judge.other is not None else -1, near_code, near, near_base))
            done += 1
            if progress is not None:
                progress(done, total)
    left = sum(1 for r in rows if r[2] and not passes(r[9], r[10]))
    return rows, {"tiles": len(rows), "positions": len(judge.at), "folders": ts.folders,
                  "near_level": judge.other if judge.other is not None else -1, "other_image": left,
                  "stopped": int(ts.stopped)}


# ------------------------------------------------------------------------------------------------ labels (S78)

_GLYPHS = {   # 3 x 5, rows from the top
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001010010",
    "8": "111101111101111", "9": "111101111001111", "A": "010101111101101", "B": "110101110101110",
    "C": "111100100100111", "D": "110101101101110", "E": "111100111100111", "F": "111100111100100",
    ",": "000000000010100", "-": "000000111000000", "+": "000010111010000", " ": "000000000000000",
    "?": "111001011000010", "f": "011010111010010",
}
LABEL_SCALE = 3
_ADVANCE = 4 * LABEL_SCALE
_LINE = 6 * LABEL_SCALE + 1
GRID_RGBA = (255, 210, 0, 255)


def _box(canvas: bytearray, width: int, left: int, top: int, w: int, h: int) -> None:
    for r in range(top, top + h):
        at = (r * width + left) * 4
        for k in range(at, at + w * 4, 4):
            canvas[k] = canvas[k] * 3 // 10
            canvas[k + 1] = canvas[k + 1] * 3 // 10
            canvas[k + 2] = canvas[k + 2] * 3 // 10
            canvas[k + 3] = 255


def label(canvas: bytearray, width: int, left: int, top: int, size: int, lines: list[str]) -> None:
    """S78: a tile's border, in GRID_RGBA, and its lines of text, white on a dark box, drawn into the canvas (RGBA,
    `width` pixels a row) at the tile whose top left is (left, top)."""
    for k in range(size):
        canvas[((top + k) * width + left) * 4:((top + k) * width + left) * 4 + 4] = bytes(GRID_RGBA)
        canvas[(top * width + left + k) * 4:(top * width + left + k) * 4 + 4] = bytes(GRID_RGBA)
    room = max(0, (size - 4) // _ADVANCE)
    most = max(1, (size - 4) // _LINE)
    if len(lines) > most:
        lines = lines[:most - 1] + ["+%d" % (len(lines) - most + 1)]
    for n, text in enumerate(lines):
        text = text[:room]
        if not text:
            continue
        y0 = top + 2 + n * _LINE
        _box(canvas, width, left + 2, y0, len(text) * _ADVANCE + 2, _LINE)
        for i, ch in enumerate(text):
            g = _GLYPHS.get(ch, _GLYPHS["?"])
            for gy in range(5):
                for gx in range(3):
                    if g[gy * 3 + gx] != "1":
                        continue
                    for sy in range(LABEL_SCALE):
                        row = y0 + 1 + gy * LABEL_SCALE + sy
                        at = (row * width + left + 3 + i * _ADVANCE + gx * LABEL_SCALE) * 4
                        canvas[at:at + 4 * LABEL_SCALE] = b"\xff\xff\xff\xff" * LABEL_SCALE


# ------------------------------------------------------------------------------------------------ overview (S75)

VARIANTS = ("revealed", "base", "code")   # S77/S78: every piece revealed, the base alone, or one code as exported


def _choose(codes: dict[int, Path], judge: Judge | None, x: int, y: int, min_match: int,
            px_of: dict[int, bytearray]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """S78: the widest variants to lay, each with its score, and those left out as another image's. A widest variant
    that fails gives way to the widest of the codes inside it, which are judged in turn."""
    nonzero = [c for c in codes if c]
    todo = widest(nonzero)
    seen: set[int] = set()
    kept: list[tuple[int, int]] = []
    out: list[tuple[int, int]] = []
    while todo:
        c = todo.pop(0)
        if c in seen:
            continue
        seen.add(c)
        if judge is None:
            kept.append((c, UNMEASURED))
            continue
        px = px_of.get(c)
        if px is None:
            px = px_of[c] = judge.decode(codes[c])
        _, near, near_base = judge.near(x, y, c, judge.thumb(px))
        score = max(near, near_base)
        if passes(near, near_base, min_match):
            kept.append((c, score))
        else:
            out.append((c, score))
            todo.extend(d for d in widest([d for d in nonzero if d != c and d & c == d]) if d not in seen)
    best = set(widest([c for c, _ in kept]))
    return sorted((c, sc) for c, sc in kept if c in best), sorted(out)


def overview(root: Path, sheet: int, level: int, *, rows_from: str = "bottom", variant: str = "revealed",
             code: int | None = None, check: bool = True, min_match: int = MATCH_MIN, labels: bool = False,
             skip: Collection[Path] = (),
             cancel: threading.Event | None = None,
             progress: Callable[[int, int], None] | None = None) -> tuple[bytes, dict[str, int]]:
    """One PNG of a sheet's level, laid out on the tile grid (column x; row y counted from the bottom, or from the
    top). Each position with every piece revealed (S77; with `check`, variants that do not match the next level are
    left out, S78), or in its base variant, or (variant "code") the file of one code where it was exported and the
    base elsewhere. `labels` draws each tile's border, its column and row, and the codes laid (a score after each, per
    mille) or left out (a minus before). Positions without a file stay transparent. ValueError when no tile is found,
    the result would pass MAX_SIDE, or a tile is not a PNG DataPiler reads or not square."""
    if rows_from not in ROWS_FROM:
        raise ValueError("rows_from is bottom or top")
    if variant not in VARIANTS:
        raise ValueError("variant is revealed, base or code")
    if variant == "code" and (code is None or not 0 <= code <= 0xFFFFFFFF):
        raise ValueError("variant code needs a code")
    ts = tile_set(root, sheet, skip=skip, cancel=cancel)
    at = ts.levels.get(level, {})
    if not at:
        raise ValueError("no exported PNG tile of that sheet and level was found in DataPiler's folder")
    cols, rows = ts.grid(level)
    judge = Judge(ts, level, cancel)
    use_judge = judge if variant == "revealed" and check else None
    size = None
    canvas = None
    done = joined = left_out = measured = 0
    for (x, y), codes in sorted(at.items()):
        under = judge.decode(codes[0]) if 0 in codes else None
        px_of: dict[int, bytearray] = {}
        text = ["%d,%d" % (x, y)]
        if variant == "base" or (variant == "code" and code not in codes):
            if under is not None:
                px = bytearray(under)
                text.append("0")
            else:
                first = widest(codes)[0]                 # no base exported: its first variant stands in
                px = judge.decode(codes[first])
                text.append("%X" % first)
        elif variant == "code":
            px = judge.decode(codes[code])
            text.append("%X" % code)
        else:
            lays, out = _choose(codes, use_judge, x, y, min_match, px_of)
            px = bytearray(under) if under is not None else None
            for c, _ in lays:
                over = px_of[c] if c in px_of else judge.decode(codes[c])
                if px is None:
                    px = bytearray(over)
                    continue
                lay_over(px, over, under)
            if px is None:                               # every variant left out and no base: the first stands in
                c = widest(codes)[0]
                px = judge.decode(codes[c])
            if len(lays) > 1:
                joined += 1
            left_out += len(out)
            measured += sum(1 for _, sc in lays + out if sc != UNMEASURED)
            text += ["%X" % c if sc == UNMEASURED else "%X %d" % (c, sc) for c, sc in lays] or ["0"]
            text += ["-%X" % c if sc == UNMEASURED else "-%X %d" % (c, sc) for c, sc in out]
        if size is None:
            size = judge.size
            if cols * size > MAX_SIDE or rows * size > MAX_SIDE:
                raise ValueError("that level would make an image over %d pixels a side; choose a smaller level" % MAX_SIDE)
            canvas = bytearray(cols * size * rows * size * 4)
        top = (rows - 1 - y) * size if rows_from == "bottom" else y * size
        left = x * size
        line = cols * size * 4
        for r in range(size):
            at_ = (top + r) * line + left * 4
            canvas[at_:at_ + size * 4] = px[r * size * 4:(r + 1) * size * 4]
        if labels:
            label(canvas, cols * size, left, top, size, text)
        done += 1
        if progress is not None:
            progress(done, len(at))
    data = png_encode(cols * size, rows * size, canvas)
    return data, {"tiles": len(at), "columns": cols, "rows": rows, "tile": size, "width": cols * size,
                  "height": rows * size, "joined": joined, "left_out": left_out, "measured": measured,
                  "near_level": judge.other if use_judge is not None and judge.other is not None else -1}
