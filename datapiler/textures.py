"""Exported map tiles (S73, DP25): the textures Smithbox's Texture Viewer exported, found anywhere in DataPiler's folder.

The owner exports the game's map tiles from Smithbox (its Texture Viewer, Data Export) into any folder inside
DataPiler's own folder. `find_tiles` walks that folder, keeps the files whose names are the map tiles' names, and reads
each one's width and height from the first bytes of its file header. It never decodes an image, never reads past the
header, and keeps no path or name outside this module: what it gives back is numbers (the sheet, level, column, row and
eight-digit code the name carries, the size, and how many copies were found). Folders that hold DataPiler's own
environment, logs, update downloads or the Deleted bin are left out, as are links."""

from __future__ import annotations

import math
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
    in walk order (folders themselves never leave this module: numbers only). S82: the game's own masks of the sheet,
    {level: {(x, y): mask}}, when its mask file is found (unpacked by unpack_game_file), else empty."""

    def __init__(self) -> None:
        self.levels: dict[int, dict[tuple[int, int], dict[int, Path]]] = {}
        self.copies: dict[tuple[int, int, int, int], int] = {}
        self.folder: dict[Path, int] = {}
        self.folders = 0
        self.stopped = False
        self.sheet = 0
        self.masks: dict[int, dict[tuple[int, int], int]] = {}
        self.mask_copies = 0

    def masked(self) -> bool:
        """S82: whether the game draws the sheet with pieces: its mask file was found and names one."""
        return any(m for at in self.masks.values() for m in at.values())

    def mask_at(self, level: int) -> dict[tuple[int, int], int] | None:
        """S82: a level's masks, or None when the game keeps none for it (or none were found)."""
        return self.masks.get(level) if self.masked() else None

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
    ts.sheet = sheet
    numbers: dict[str, int] = {}
    mask_files: list[Path] = []
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
            mk = MASK_RX.fullmatch(name)
            if mk is not None and int(mk.group(1)) == sheet and not os.path.islink(os.path.join(here, name)):
                mask_files.append(Path(here) / name)
                continue
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
    if mask_files:
        datas = set()
        for f in mask_files:
            if f.stat().st_size > MAX_MASK_BYTES:
                raise ValueError("the game's mask file of sheet %d is larger than DataPiler reads" % sheet)
            datas.add(f.read_bytes())
        if len(datas) > 1:
            raise ValueError("%d copies of the game's mask file of sheet %d differ - keep one" % (len(mask_files), sheet))
        ts.masks = parse_masks(datas.pop())
        ts.mask_copies = len(mask_files)
    return ts


# ------------------------------------------------------------------------------------------------ the game's masks (S82)

MASK_RX = re.compile(r"MENU_MapTile_M(\d{2})\.mtmsk", re.IGNORECASE)
MAX_MASK_BYTES = 4 * 2 ** 20
_MASK_LINE = re.compile(r'<MapTileMask exists="([01])" id="(\d{1,6})" mask="(\d{1,10})"\s*/>')
_MASK_OTHER = re.compile(r'<\?xml version="1\.0"( encoding="[A-Za-z0-9_-]{1,16}")? \?>|<MapTileMaskList id="\d{1,6}">'
                         r'|</MapTileMaskList>|')


def parse_masks(data: bytes) -> dict[int, dict[tuple[int, int], int]]:
    """S82 (WHY§73): the game's own mask file of one sheet, `MENU_MapTile_Mxx.mtmsk` in 71_maptile.mtmskbnd: an XML list
    read line by line against fixed patterns, never by an XML parser. {level: {(x, y): mask}}: an entry's id is
    level * 10,000 + x * 100 + y (x and y as the tiles' names give them) and its mask the pieces that touch the tile;
    an entry the game marks as not existing counts as no pieces. The game draws, at each place, the variant whose code
    is the mask without the pieces not yet revealed: every subset of the mask is exported, and any other code there is
    another layout's. ValueError for anything else."""
    if len(data) > MAX_MASK_BYTES:
        raise ValueError("the game's mask file is larger than DataPiler reads")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("not a mask file DataPiler reads") from None
    out: dict[int, dict[tuple[int, int], int]] = {}
    for line in text.splitlines():
        t = line.strip()
        m = _MASK_LINE.fullmatch(t)
        if m is None:
            if _MASK_OTHER.fullmatch(t) is None:
                raise ValueError("not a mask file DataPiler reads")
            continue
        exists, i, mask = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if mask > 0xFFFFFFFF:
            raise ValueError("not a mask file DataPiler reads")
        out.setdefault(i // 10000, {})[((i % 10000) // 100, i % 100)] = mask if exists else 0
    return out


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


# ------------------------------------------------------------------------------------------------ tile check (S78, S79)
#
# The overviews of 0.2.25 to 0.2.27 mixed two images at level 2: next to variants that are the base with pieces drawn
# in, the game's container holds variants of another drawing, named by code like the rest (WHY§64, WHY§67). The file
# names hold nothing to tell them apart, so DataPiler looks. S79: every level of a sheet is measured against one
# reference level (the coarsest with six tiles a side or more, else the coarsest), the reference against its
# neighbour, each scaled by LEVEL_SCALES from the bottom left: each variant's grey thumbnail against the reference's
# variant for the same pieces, and its base, sampled over the same ground.

THUMB = 64                   # a tile's grey thumbnail, pixels a side
UNMEASURED = -9999           # a score that could not be measured: no next level, a tile too small, or nothing in it
MATCH_MIN = 700              # per mille: a variant that matches the next level less than this is another image's
FLAT = 2.0                   # grey levels: a thumbnail part flatter than this holds nothing to compare
# S82 (WHY§73): the levels the game draws today, on every sheet: level 1 three quarters of level 0 and level 2 2,089 /
# 10,496 of it, each at the top left of the frame of whole tiles that holds it (31 and 9 tiles a side of level 0's 41).
# Levels 3 and 4 are an older layout the game no longer draws (no masks; their ground sits 1,024 map units right of
# today's): they keep their own scales and are never the reference.
LEVEL_SCALES = (1.0, 0.75, 2089 / 10496)
LEGACY_SCALES = {3: 0.125, 4: 0.0625}
CELLS = 32                   # cells a side, at most, that a variant and the reference are compared on
REF_MIN_SIDE = 6             # the reference level: the coarsest with at least this many tiles a side
TILE_CHECK_COLUMNS: tuple[tuple[str, str], ...] = (
    ("x", "int"), ("y", "int"), ("code", "int"), ("folder", "int"), ("copies", "int"), ("drawn", "int"),
    ("like", "int"), ("near_level", "int"), ("near_code", "int"), ("near", "int"), ("near_base", "int"),
    ("moved", "int"), ("in_mask", "int"))
LEVEL_TOP = frozenset({1, 2})   # S80, S82: the levels whose map sits at the top left of their frame
OLD_SHIFT = -1024    # S82: map units from where a tile of the older layout is named to where its ground lies today


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


def legacy(level: int) -> bool:
    """S82: a level of the older layout, which the game no longer draws (3 and 4, and past them)."""
    return level >= len(LEVEL_SCALES)


def level_scale(level: int, sheet: int = 0) -> float:
    """S79, S82: a level's size against level 0's, the same on every sheet (WHY§73): LEVEL_SCALES for the levels the
    game draws, LEGACY_SCALES for the older layout's, halving past those."""
    if not legacy(level):
        return LEVEL_SCALES[level]
    if level in LEGACY_SCALES:
        return LEGACY_SCALES[level]
    top = max(LEGACY_SCALES)
    return LEGACY_SCALES[top] / 2 ** (level - top)


def level_top(sheet: int = 0) -> frozenset[int]:
    """S80, S82: the levels whose map sits at the top left of their frame, on every sheet."""
    return LEVEL_TOP


def frame(ts: TileSet, level: int) -> tuple[int, int]:
    """S82: the tiles a side of the frame that holds a level the game draws: level 0's grid at the level's scale, in
    whole tiles (41, 31 and 9 a side on the base map); level 0's own grid, or a legacy level's, as exported."""
    g0 = ts.grid(0)
    if level == 0 or legacy(level) or not g0[0]:
        return ts.grid(level)
    s = level_scale(level)
    return math.ceil(g0[0] * s - 1e-9), math.ceil(g0[1] * s - 1e-9)


def reference_level(ts: TileSet) -> int | None:
    """S79, S82: the level a sheet's other levels are measured against: of the levels the game draws, the coarsest
    whose frame has REF_MIN_SIDE tiles a side or more, else the coarsest; legacy levels only when it draws none. None
    when the sheet has no tile."""
    levels = sorted(lv for lv, at in ts.levels.items() if at)
    if not levels:
        return None
    drawn = [lv for lv in levels if not legacy(lv)] or levels
    big = [lv for lv in drawn if min(frame(ts, lv)) >= REF_MIN_SIDE]
    return max(big) if big else max(drawn)


def _shrink_thumb(t: array, n: int) -> list[float]:
    """A THUMB-side thumbnail as n x n means (n divides THUMB), rows from the top."""
    k = THUMB // n
    out = []
    for r in range(n):
        for c in range(n):
            s = 0.0
            for i in range(k):
                row = (r * k + i) * THUMB + c * k
                for j in range(k):
                    s += t[row + j]
            out.append(s / (k * k))
    return out


class _Sums:
    """A tile's grey summed-area table: the sum of any rectangle of its pixels in four reads."""

    def __init__(self, px: bytes | bytearray, size: int) -> None:
        self.size = size
        w = size + 1
        sums = array("d", bytes(8 * w * w))
        for r in range(size):
            at = r * size * 4
            R = px[at:at + size * 4:4]
            G = px[at + 1:at + size * 4:4]
            B = px[at + 2:at + size * 4:4]
            run = 0.0
            o = (r + 1) * w
            above = r * w
            for c in range(size):
                run += (R[c] + G[c] + B[c]) / 3.0
                sums[o + c + 1] = sums[above + c + 1] + run
        self.sums = sums

    def total(self, x0: int, y0: int, x1: int, y1: int) -> float:
        """The sum over columns x0..x1-1 and rows y0..y1-1, rows from the top."""
        w = self.size + 1
        s = self.sums
        return s[y1 * w + x1] - s[y0 * w + x1] - s[y1 * w + x0] + s[y0 * w + x0]


class Judge:
    """S78/S79: measures a level's exported variants against the sheet's reference level (the reference against its
    nearest level), scaled by LEVEL_SCALES from the bottom left. The other level's tiles are read once each and kept as
    summed-area tables, a bounded number at a time."""

    KEEP = 160

    def __init__(self, ts: TileSet, level: int, cancel: threading.Event | None = None) -> None:
        self.ts = ts
        self.sheet = ts.sheet
        self.level = level
        self.cancel = cancel
        self.at = ts.levels.get(level, {})
        self.other: int | None = None
        ref = reference_level(ts)
        if ref is not None and self.at:
            if level != ref:
                self.other = ref
            else:
                near = sorted((lv for lv, at in ts.levels.items() if at and lv != level),
                              key=lambda lv: (abs(lv - level), -lv))
                self.other = near[0] if near else None
        self.ratio = level_scale(self.other, self.sheet) / level_scale(level, self.sheet) \
            if self.other is not None else 0.0
        self.size: int | None = None
        self._kept: dict[Path, _Sums] = {}
        # S82: at the other level, only the variants its masks allow (another layout's never stand in)
        there = ts.levels.get(self.other, {}) if self.other is not None else {}
        masks = ts.mask_at(self.other) if self.other is not None else None
        self.there = there if masks is None else {
            k: {c: p for c, p in v.items() if c & ~masks.get(k, 0) == 0} for k, v in there.items()}

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

    def _sums(self, path: Path) -> _Sums:
        got = self._kept.pop(path, None)
        if got is None:
            got = _Sums(self.decode(path), self.size or 0)
            if len(self._kept) >= self.KEEP:
                self._kept.pop(next(iter(self._kept)))
        self._kept[path] = got
        return got

    def lift(self, level: int) -> float:
        """S80: how far above its grid's bottom a level's map starts, in that level's pixels: the gap left at the
        bottom by a level whose map sits at the top of its grid (level_top), else 0. The map is level 0's grid at
        the level's scale."""
        if level not in level_top(self.sheet) or self.size is None:
            return 0.0
        full = (self.ts.grid(0)[1] or 41) * self.size * level_scale(level, self.sheet)
        return max(0.0, frame(self.ts, level)[1] * self.size - full)

    def near(self, x: int, y: int, code: int, t: array | None, shift: float = 0.0) -> tuple[int, int, int]:
        """(the other level's codes compared, OR-ed, or -1; the match with them; the match with the other level's
        base), per mille; UNMEASURED where it cannot be measured. shift (S80): map units to the right that the tile
        is measured at, for the old tile set (OLD_SHIFT)."""
        if self.other is None or t is None or self.size is None:
            return -1, UNMEASURED, UNMEASURED
        size = self.size
        there = self.there
        span = size * self.ratio                       # this tile's side, in the other level's pixels
        n = CELLS
        while n > 4 and span / n < 1.0:
            n //= 2
        mine_all = _shrink_thumb(t, n)
        mine, theirs = level_scale(self.level, self.sheet), level_scale(self.other, self.sheet)
        x0 = (x * size + shift * mine) * self.ratio   # its bottom left, in the other level's pixels from the bottom
        y0 = (y * size - self.lift(self.level)) / mine * theirs + self.lift(self.other)
        cell = span / n
        chosen = -1
        pairs: dict[str, tuple[list[float], list[float]]] = {"code": ([], []), "base": ([], [])}
        for j in range(n):                             # rows from the top of this tile
            gy1 = y0 + span - j * cell                 # top and bottom of the cell, from the bottom of the level
            gy0 = gy1 - cell
            b0 = math.floor(gy0 + 1e-6)
            b1 = max(b0 + 1, math.ceil(gy1 - 1e-6))
            for i in range(n):
                gx0 = x0 + i * cell
                a0 = math.floor(gx0 + 1e-6)
                a1 = max(a0 + 1, math.ceil(gx0 + cell - 1e-6))
                for kind in ("code", "base"):
                    total = area = 0.0
                    for ty in range(b0 // size, (b1 - 1) // size + 1):
                        for tx in range(a0 // size, (a1 - 1) // size + 1):
                            codes = there.get((tx, ty))
                            if not codes:
                                continue
                            want = _within(codes, code) if kind == "code" else (0 if 0 in codes else None)
                            if want is None:
                                continue
                            if kind == "code":
                                chosen = max(chosen, 0) | want
                            sums = self._sums(codes[want])
                            cx0, cx1 = max(a0, tx * size) - tx * size, min(a1, (tx + 1) * size) - tx * size
                            by0, by1 = max(b0, ty * size) - ty * size, min(b1, (ty + 1) * size) - ty * size
                            if cx1 <= cx0 or by1 <= by0:
                                continue
                            total += sums.total(cx0, size - by1, cx1, size - by0)
                            area += (cx1 - cx0) * (by1 - by0)
                    if area:
                        pairs[kind][0].append(mine_all[j * n + i])
                        pairs[kind][1].append(total / area)
        least = n * n // 4
        code_score = ncc(*pairs["code"]) if len(pairs["code"][0]) >= least else UNMEASURED
        base_score = ncc(*pairs["base"]) if len(pairs["base"][0]) >= least else UNMEASURED
        return chosen, code_score, base_score


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
    masks = ts.mask_at(level)
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
            moved = max(judge.near(x, y, code, t, OLD_SHIFT)[1:]) if code else UNMEASURED
            in_mask = -1 if masks is None else int(code & ~masks.get((x, y), 0) == 0)
            rows.append((x, y, code, ts.folder.get(codes[code], 0), ts.copies.get((level, x, y, code), 1), drawn,
                         like, judge.other if judge.other is not None else -1, near_code, near, near_base, moved,
                         in_mask))
            done += 1
            if progress is not None:
                progress(done, total)
    left = sum(1 for r in rows if r[2] and not passes(r[9], r[10]))
    return rows, {"tiles": len(rows), "positions": len(judge.at), "folders": ts.folders,
                  "near_level": judge.other if judge.other is not None else -1, "other_image": left,
                  "stopped": int(ts.stopped), "masks": int(masks is not None),
                  "outside_masks": sum(1 for r in rows if r[12] == 0)}


# ------------------------------------------------------------------------------------------------ labels (S78)

_GLYPHS = {   # 3 x 5, rows from the top
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001010010",
    "8": "111101111101111", "9": "111101111001111", "A": "010101111101101", "B": "110101110101110",
    "C": "111100100100111", "D": "110101101101110", "E": "111100111100111", "F": "111100111100100",
    ",": "000000000010100", "-": "000000111000000", "+": "000010111010000", " ": "000000000000000",
    "?": "111001011000010", "f": "011010111010010",
}
LABEL_SCALE = 3              # the font's size on a tile of LABEL_FULL pixels or more; smaller tiles get smaller text
LABEL_FULL = 192
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
    `width` pixels a row) at the tile whose top left is (left, top). S79: the text is three times the font on a tile of
    LABEL_FULL pixels or more, twice on half of that, else once."""
    scale = LABEL_SCALE if size >= LABEL_FULL else (2 if size >= LABEL_FULL // 2 else 1)
    _ADVANCE = 4 * scale
    _LINE = 6 * scale + 1
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
                    for sy in range(scale):
                        row = y0 + 1 + gy * scale + sy
                        at = (row * width + left + 3 + i * _ADVANCE + gx * scale) * 4
                        canvas[at:at + 4 * scale] = b"\xff\xff\xff\xff" * scale


# ------------------------------------------------------------------------------------------------ overview (S75)

VARIANTS = ("revealed", "base", "code")   # S77/S78: every piece revealed, the base alone, or one code as exported
SHRINKS = (1, 2, 4, 8)                    # S79: an overview's tiles may be shrunk so that levels 0 and 1 fit


def shrink_rgba(px: bytes | bytearray, size: int, f: int) -> bytearray:
    """S79: a size x size RGBA tile as (size / f) x (size / f), each pixel the mean of an f x f block, rounded."""
    if f == 1:
        return bytearray(px)
    side = size // f
    out = bytearray(side * side * 4)
    line = size * 4
    half = f * f // 2
    for r in range(side):
        for ch in range(4):
            rows = [px[(r * f + k) * line + ch:(r * f + k + 1) * line:4] for k in range(f)]
            o = r * side * 4 + ch
            for c in range(side):
                a = c * f
                out[o + c * 4] = (sum(sum(row[a:a + f]) for row in rows) + half) // (f * f)
    return out


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
             shrink: int = 1, masks: bool = True, skip: Collection[Path] = (),
             cancel: threading.Event | None = None,
             progress: Callable[[int, int], None] | None = None) -> tuple[bytes, dict[str, int]]:
    """One PNG of a sheet's level, laid out on the tile grid (column x; row y counted from the bottom, or from the
    top). Each position with every piece revealed, or in its base variant, or (variant "code") the file of one code
    where it was exported and the base elsewhere. Every piece revealed is, where the game's mask file of the sheet is
    found and `masks` is on (S82), what the game draws: at each place of the level's frame the variant whose code is
    the place's mask, the base where it has none; any other code is another layout's and is left out. Else (S77, S78)
    the widest variants are laid together, and with `check` those that do not match the reference level are left out.
    `labels` draws each tile's border, its column and row, and the codes laid (a score after each, per mille) or left
    out (a minus before). `shrink` (S79) makes each tile 2, 4 or 8 times smaller, so that levels 0 and 1 fit.
    Positions without a file stay transparent. ValueError when no tile is found, the result would pass MAX_SIDE, or a
    tile is not a PNG DataPiler reads or not square."""
    if rows_from not in ROWS_FROM:
        raise ValueError("rows_from is bottom or top")
    if variant not in VARIANTS:
        raise ValueError("variant is revealed, base or code")
    if variant == "code" and (code is None or not 0 <= code <= 0xFFFFFFFF):
        raise ValueError("variant code needs a code")
    if shrink not in SHRINKS:
        raise ValueError("shrink is 1, 2, 4 or 8")
    ts = tile_set(root, sheet, skip=skip, cancel=cancel)
    at = ts.levels.get(level, {})
    if not at:
        raise ValueError("no exported PNG tile of that sheet and level was found in DataPiler's folder")
    game = ts.mask_at(level) if masks else None
    cols, rows = frame(ts, level) if game is not None else ts.grid(level)
    places = sorted(k for k in at if k[0] < cols and k[1] < rows)
    judge = Judge(ts, level, cancel)
    use_judge = judge if variant == "revealed" and check and game is None else None
    first = at[places[0]] if places else at[min(at)]
    judge.decode(first[min(first)])                    # the tiles' size, before anything else is read
    full = judge.size
    if full % shrink:
        raise ValueError("the tiles cannot be shrunk %d times" % shrink)
    size = full // shrink
    if cols * size > MAX_SIDE or rows * size > MAX_SIDE:
        raise ValueError("that level would make an image over %d pixels a side; choose a smaller level or shrink it"
                         % MAX_SIDE)
    canvas = bytearray(cols * size * rows * size * 4)
    done = joined = left_out = measured = masked = 0
    for (x, y) in places:
        codes = at[(x, y)]
        under = judge.decode(codes[0]) if 0 in codes else None
        px_of: dict[int, bytearray] = {}
        text = ["%d,%d" % (x, y)]
        px = None
        if variant == "base" or (variant == "code" and code not in codes):
            if under is not None:
                px = bytearray(under)
                text.append("0")
            else:
                first_code = widest(codes)[0]            # no base exported: its first variant stands in
                px = judge.decode(codes[first_code])
                text.append("%X" % first_code)
        elif variant == "code":
            px = judge.decode(codes[code])
            text.append("%X" % code)
        elif game is not None:
            m = game.get((x, y), 0)
            want = _within(codes, m)                     # the mask itself, exported at every place the game names
            left_out += sum(1 for c in codes if c & ~m)
            if want is not None:
                px = judge.decode(codes[want]) if want else bytearray(under)
                masked += int(want != 0)
                text.append("%X" % want)
                if m and want != m:
                    text.append("-%X" % (m & ~want))
            else:
                px = judge.decode(codes[widest(codes)[0]])
                text.append("?")
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
        px = shrink_rgba(px, full, shrink)
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
            progress(done, len(places))
    data = png_encode(cols * size, rows * size, canvas)
    return data, {"tiles": len(places), "columns": cols, "rows": rows, "tile": size, "width": cols * size,
                  "height": rows * size, "joined": joined, "left_out": left_out, "measured": measured,
                  "masked": masked, "outside": len(at) - len(places), "masks": int(game is not None),
                  "near_level": judge.other if use_judge is not None and judge.other is not None else -1}
