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


def tile_files(root: Path, sheet: int, level: int, *, skip: Collection[Path] = (),
               cancel: threading.Event | None = None
               ) -> dict[tuple[int, int], tuple[tuple[tuple[int, Path], ...], Path | None]]:
    """For each tile position of one sheet and level, the exported files of its widest revealed variants (S77: every
    piece revealed is these laid together over the base) and of its base variant (code 0), if exported.
    {(x, y): (((code, path), ...), base path or None)}. Paths never leave this module's callers' logs."""
    root = Path(root)
    skipped = {os.path.normcase(os.path.abspath(str(s))) for s in skip}
    found: dict[tuple[int, int], dict[int, Path]] = {}
    base_depth = len(Path(os.path.abspath(str(root))).parts)
    looked = 0

    def result() -> dict[tuple[int, int], tuple[tuple[tuple[int, Path], ...], Path | None]]:
        return {k: (tuple((c, v[c]) for c in widest(v)), v.get(0)) for k, v in found.items()}

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
                return result()
            m = TILE_RX.fullmatch(name)
            if m is None or m.group(6).lower() != "png":
                continue
            if int(m.group(1)) != sheet or int(m.group(2)) != level:
                continue
            full = Path(here) / name
            if os.path.islink(full):
                continue
            found.setdefault((int(m.group(3)), int(m.group(4))), {}).setdefault(int(m.group(5), 16), full)
    return result()


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


VARIANTS = ("revealed", "base")   # S77: every piece revealed (its widest variants laid over the base), or the base alone


def overview(root: Path, sheet: int, level: int, *, rows_from: str = "bottom", variant: str = "revealed",
             skip: Collection[Path] = (),
             cancel: threading.Event | None = None,
             progress: Callable[[int, int], None] | None = None) -> tuple[bytes, dict[str, int]]:
    """One PNG of a sheet's level, each position with every piece revealed (S77) or in its base variant, laid out on
    the tile grid (column x; row y counted from the bottom, or from the top). Positions without a file stay
    transparent. "joined" counts the positions laid from more than one revealed variant. ValueError when no tile
    is found, the result would pass MAX_SIDE, or a tile is not a PNG DataPiler reads or not square."""
    if rows_from not in ROWS_FROM:
        raise ValueError("rows_from is bottom or top")
    if variant not in VARIANTS:
        raise ValueError("variant is revealed or base")
    files = tile_files(root, sheet, level, skip=skip, cancel=cancel)
    if not files:
        raise ValueError("no exported PNG tile of that sheet and level was found in DataPiler's folder")
    cols = max(x for x, _ in files) + 1
    rows = max(y for _, y in files) + 1
    size = None
    canvas = None
    done = 0
    joined = 0
    for (x, y), (lays, base_path) in sorted(files.items()):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        under = None
        if base_path is not None:
            with open(base_path, "rb") as f:
                tw, th, under = png_decode(f.read())
        if variant == "base" and under is not None:
            lays = ()
        elif variant == "base":
            lays = lays[:1]               # no base exported: its first variant stands in, as before
        # S77: every piece revealed is the base with each widest revealed variant laid over it where it differs
        px = bytearray(under) if under is not None else None
        for _, path in lays:
            with open(path, "rb") as f:
                ow, oh, over = png_decode(f.read())
            if px is None:
                tw, th, px = ow, oh, bytearray(over)
                continue
            if (ow, oh) != (tw, th):
                raise ValueError("a tile's variants are not of one size")
            lay_over(px, over, under)
        if len(lays) > 1:
            joined += 1
        if tw != th or (size is not None and tw != size):
            raise ValueError("the tiles are not all square and of one size")
        if size is None:
            size = tw
            if cols * size > MAX_SIDE or rows * size > MAX_SIDE:
                raise ValueError("that level would make an image over %d pixels a side; choose a smaller level" % MAX_SIDE)
            canvas = bytearray(cols * size * rows * size * 4)
        top = (rows - 1 - y) * size if rows_from == "bottom" else y * size
        left = x * size
        line = cols * size * 4
        for r in range(size):
            at = (top + r) * line + left * 4
            canvas[at:at + size * 4] = px[r * size * 4:(r + 1) * size * 4]
        done += 1
        if progress is not None:
            progress(done, len(files))
    data = png_encode(cols * size, rows * size, canvas)
    return data, {"tiles": len(files), "columns": cols, "rows": rows, "tile": size, "width": cols * size,
                  "height": rows * size, "joined": joined}
