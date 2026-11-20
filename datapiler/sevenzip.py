"""7z archives for packing a finished job's files to upload (DP30, settled S87), from the standard library alone.

`write` makes one 7z archive: every file's data in one solid LZMA2 block (the `lzma` module's raw LZMA2, which is 7z's
coder 0x21), a CRC-32 for every file, the names relative and with `/` between folders, and nothing else about the
files: no times, no attributes. When the archive is larger than `part_size` (29.9 MB, so that each part stays under an
upload limit of 30 MB), it is cut into numbered parts, `<name>.7z.001`, `<name>.7z.002`, ..., which 7-Zip opens from
the first, the rest beside it; a smaller one is `<name>.7z`. The parts are made in a folder of their own and moved
into place once whole, after the archive's earlier parts of that name are taken away, so a half-written or stale part
is never left beside them.

`check` reads what `write` made, part by part, and confirms every file's size and CRC-32 before it is offered; it
reads only the shape `write` makes. The layout follows 7-Zip's own description of the format (7zFormat.txt, in its
public-domain LZMA SDK): a 32-byte signature header, the packed streams, then the header that describes them."""

from __future__ import annotations

import lzma
import os
import shutil
import struct
import zlib
from pathlib import Path
from typing import Callable, Iterable

SIGNATURE = b"7z\xbc\xaf\x27\x1c"
FORMAT_VERSION = b"\x00\x04"
PART_SIZE = 29_900_000          # S87: 29.9 MB (decimal), under a 30 MB upload limit counted either way
MIN_PART = 1 << 16              # no part smaller than this (the first holds the 32-byte signature header)
CHUNK = 1 << 20                 # bytes read from a file at a time
DICT_SIZE = 1 << 23             # 8 MiB: LZMA2 preset 6's dictionary
PRESET = 6
MAX_FILES = 100_000
MAX_INPUT = 4 << 30             # 4 GiB of files at most in one archive
MAX_HEADER = 64 << 20

_END, _HEADER, _MAIN_STREAMS, _FILES_INFO = 0x00, 0x01, 0x04, 0x05
_PACK_INFO, _UNPACK_INFO, _SUBSTREAMS = 0x06, 0x07, 0x08
_SIZE, _CRC, _FOLDER, _CODERS_UNPACK_SIZE, _NUM_UNPACK_STREAM = 0x09, 0x0A, 0x0B, 0x0C, 0x0D
_EMPTY_STREAM, _EMPTY_FILE, _NAME = 0x0E, 0x0F, 0x11
_LZMA2 = b"\x21"


class PackError(Exception):
    """An archive that cannot be made or does not read back whole; its text says why, with no path."""


# ------------------------------------------------------------------------------------------------ encoding

def number(v: int) -> bytes:
    """7z's variable-length number: the first byte's leading 1 bits say how many little-endian bytes follow."""
    if v < 0 or v >= 1 << 64:
        raise ValueError("out of range")
    first, mask, i = 0, 0x80, 0
    while i < 8:
        if v < 1 << (7 * (i + 1)):
            first |= v >> (8 * i)
            break
        first |= mask
        mask >>= 1
        i += 1
    return bytes([first]) + (v & ((1 << (8 * i)) - 1)).to_bytes(i, "little")


def _bits(flags: list[bool]) -> bytes:
    """A bit vector, the first item in the top bit of the first byte."""
    out = bytearray((len(flags) + 7) // 8)
    for k, on in enumerate(flags):
        if on:
            out[k // 8] |= 0x80 >> (k % 8)
    return bytes(out)


def dict_prop(size: int) -> int:
    """LZMA2's one property byte: the smallest dictionary code that holds `size` bytes."""
    for p in range(40):
        if (2 | (p & 1)) << (p // 2 + 11) >= size:
            return p
    return 40


def _name_ok(name: str) -> bool:
    if not isinstance(name, str) or not name or len(name) > 1024 or name.startswith("/") or "\\" in name:
        return False
    parts = name.split("/")
    return all(p and p not in (".", "..") and "\0" not in p and ":" not in p for p in parts)


# ------------------------------------------------------------------------------------------------ the parts

class _PartWriter:
    """Bytes written in order across numbered part files of at most `size` bytes each."""

    def __init__(self, folder: Path, stem: str, size: int):
        self.folder, self.stem, self.size = folder, stem, size
        self.paths: list[Path] = []
        self.total = 0
        self._f = None
        self._left = 0

    def _next(self) -> None:
        if self._f is not None:
            self._f.close()
        p = self.folder / ("%s.7z.%03d" % (self.stem, len(self.paths) + 1))
        self.paths.append(p)
        self._f = open(p, "wb")
        self._left = self.size

    def write(self, b: bytes) -> None:
        view = memoryview(b)
        while view:
            if self._f is None or self._left == 0:
                self._next()
            n = min(self._left, len(view))
            self._f.write(view[:n])
            view = view[n:]
            self._left -= n
            self.total += n

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None


class _PartReader:
    """The parts read back as one stream: seek and read across them."""

    def __init__(self, paths: list[Path]):
        self.paths = paths
        self.sizes = [p.stat().st_size for p in paths]
        self.length = sum(self.sizes)
        self.pos = 0

    def read(self, n: int) -> bytes:
        out = bytearray()
        while n > 0 and self.pos < self.length:
            at, k = self.pos, 0
            while at >= self.sizes[k]:
                at -= self.sizes[k]
                k += 1
            take = min(n, self.sizes[k] - at)
            with open(self.paths[k], "rb") as f:
                f.seek(at)
                got = f.read(take)
            if len(got) != take:
                raise PackError("a part is shorter than it was")
            out += got
            self.pos += take
            n -= take
        return bytes(out)


# ------------------------------------------------------------------------------------------------ writing

def _header(files: list[tuple[str, int, int]], packed: int, prop: int) -> bytes:
    """The plain (not compressed) header for files [(name, size, crc)] whose non-empty data is one LZMA2 block of
    `packed` bytes."""
    full = [(n, s, c) for n, s, c in files if s > 0]
    h = bytearray([_HEADER])
    if full:
        h += bytes([_MAIN_STREAMS])
        h += bytes([_PACK_INFO]) + number(0) + number(1) + bytes([_SIZE]) + number(packed) + bytes([_END])
        h += bytes([_UNPACK_INFO, _FOLDER]) + number(1) + b"\x00"
        h += number(1) + bytes([0x20 | len(_LZMA2)]) + _LZMA2 + number(1) + bytes([prop])
        h += bytes([_CODERS_UNPACK_SIZE]) + number(sum(s for _, s, _ in full)) + bytes([_END])
        h += bytes([_SUBSTREAMS, _NUM_UNPACK_STREAM]) + number(len(full))
        if len(full) > 1:
            h += bytes([_SIZE]) + b"".join(number(s) for _, s, _ in full[:-1])
        h += bytes([_CRC, 1]) + b"".join(struct.pack("<I", c) for _, _, c in full) + bytes([_END])
        h += bytes([_END])
    h += bytes([_FILES_INFO]) + number(len(files))
    empty = [s == 0 for _, s, _ in files]
    if any(empty):
        v = _bits(empty)
        h += bytes([_EMPTY_STREAM]) + number(len(v)) + v
        v = _bits([True] * sum(empty))                    # every empty one is a file, never a folder
        h += bytes([_EMPTY_FILE]) + number(len(v)) + v
    names = b"".join(n.encode("utf-16-le") + b"\0\0" for n, _, _ in files)
    h += bytes([_NAME]) + number(1 + len(names)) + b"\x00" + names
    h += bytes([_END, _END])
    return bytes(h)


def write(entries: Iterable[tuple[str, Path]], out_dir: Path, name: str, *, part_size: int = PART_SIZE,
          progress: Callable[[int, int], None] | None = None) -> list[Path]:
    """Packs [(name in the archive, file on disk)] into out_dir/<name>.7z, or <name>.7z.001 and on when larger than
    part_size; gives back the parts in order. PackError for a bad name, too many files or bytes, or a file that cannot
    be read; OSError for a folder that cannot be written."""
    entries = list(entries)
    if not entries:
        raise PackError("nothing to pack")
    if len(entries) > MAX_FILES:
        raise PackError("more than %d files" % MAX_FILES)
    if not _name_ok(name) or "/" in name:
        raise PackError("not an archive name")
    part_size = max(MIN_PART, int(part_size))
    seen: set[str] = set()
    sizes = []
    for arc, src in entries:
        if not _name_ok(arc):
            raise PackError("a name in the archive is not a plain relative name")
        if arc.casefold() in seen:
            raise PackError("two files with one name in the archive")
        seen.add(arc.casefold())
        try:
            sizes.append(Path(src).stat().st_size)
        except OSError as e:
            raise PackError("a file could not be read (%s)" % (e.strerror or type(e).__name__)) from None
    total = sum(sizes)
    if total > MAX_INPUT:
        raise PackError("more than %d GiB of files" % (MAX_INPUT >> 30))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / (".packing-" + name)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    try:
        parts = _write_parts(entries, work, name, part_size, total, progress)
        check(parts)
        for old in _existing(out_dir, name):              # an earlier pack of this name, whole or in parts
            old.unlink()
        if len(parts) == 1:
            final = [out_dir / (name + ".7z")]
        else:
            final = [out_dir / p.name for p in parts]
        for p, q in zip(parts, final):
            os.replace(p, q)
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _existing(out_dir: Path, name: str) -> list[Path]:
    out = []
    for p in out_dir.iterdir():
        n = p.name
        if p.is_file() and (n == name + ".7z" or (n.startswith(name + ".7z.") and n[len(name) + 4:].isdigit())):
            out.append(p)
    return out


def _write_parts(entries: list[tuple[str, Path]], work: Path, name: str, part_size: int, total: int,
                 progress: Callable[[int, int], None] | None) -> list[Path]:
    w = _PartWriter(work, name, part_size)
    try:
        w.write(bytes(32))                                  # the signature header, filled in at the end
        comp = lzma.LZMACompressor(format=lzma.FORMAT_RAW,
                                   filters=[{"id": lzma.FILTER_LZMA2, "preset": PRESET, "dict_size": DICT_SIZE}])
        files: list[tuple[str, int, int]] = []
        done = 0
        for arc, src in entries:
            size = crc = 0
            try:
                with open(src, "rb") as f:
                    while True:
                        b = f.read(CHUNK)
                        if not b:
                            break
                        size += len(b)
                        crc = zlib.crc32(b, crc)
                        w.write(comp.compress(b))
                        done += len(b)
                        if progress is not None:
                            progress(done, max(total, done))
            except OSError as e:
                raise PackError("a file could not be read (%s)" % (e.strerror or type(e).__name__)) from None
            files.append((arc, size, crc & 0xFFFFFFFF))
        if any(s for _, s, _ in files):
            w.write(comp.flush())
        packed = w.total - 32
        head = _header(files, packed, dict_prop(DICT_SIZE))
        if len(head) > MAX_HEADER:
            raise PackError("too many names for one archive")
        w.write(head)
    finally:
        w.close()
    start = struct.pack("<QQI", packed, len(head), zlib.crc32(head) & 0xFFFFFFFF)
    with open(w.paths[0], "r+b") as f:
        f.write(SIGNATURE + FORMAT_VERSION + struct.pack("<I", zlib.crc32(start) & 0xFFFFFFFF) + start)
    return w.paths


# ------------------------------------------------------------------------------------------------ reading back

class _Cursor:
    def __init__(self, b: bytes):
        self.b, self.i = b, 0

    def byte(self) -> int:
        if self.i >= len(self.b):
            raise PackError("the header ends early")
        self.i += 1
        return self.b[self.i - 1]

    def take(self, n: int) -> bytes:
        if n < 0 or self.i + n > len(self.b):
            raise PackError("the header ends early")
        self.i += n
        return self.b[self.i - n:self.i]

    def number(self) -> int:
        first = self.byte()
        mask, i = 0x80, 0
        while i < 8 and first & mask:
            mask >>= 1
            i += 1
        low = int.from_bytes(self.take(i), "little")
        high = (first & (mask - 1)) if i < 8 else 0
        return low | (high << (8 * i))

    def expect(self, v: int) -> None:
        if self.byte() != v:
            raise PackError("not the header DataPiler writes")


def _vector(c: _Cursor, n: int) -> list[bool]:
    b = c.take((n + 7) // 8)
    return [bool(b[k // 8] & (0x80 >> (k % 8))) for k in range(n)]


def read_header(parts: list[Path]) -> tuple[list[tuple[str, int, int | None]], int, int]:
    """[(name, size, crc or None for an empty file)], the packed block's size and its dictionary property, from the
    header of an archive `write` made. PackError when it is not one."""
    r = _PartReader(parts)
    sig = r.read(32)
    if len(sig) != 32 or sig[:6] != SIGNATURE:
        raise PackError("not a 7z archive")
    start = sig[12:32]
    if zlib.crc32(start) & 0xFFFFFFFF != struct.unpack("<I", sig[8:12])[0]:
        raise PackError("the start header's CRC does not match")
    off, size, crc = struct.unpack("<QQI", start)
    if size > MAX_HEADER or 32 + off + size != r.length:
        raise PackError("the header is not where the start header says")
    r.pos = 32 + off
    head = r.read(size)
    if zlib.crc32(head) & 0xFFFFFFFF != crc:
        raise PackError("the header's CRC does not match")
    c = _Cursor(head)
    c.expect(_HEADER)
    sizes: list[int] = []
    crcs: list[int] = []
    packed, prop = 0, 0
    t = c.byte()
    if t == _MAIN_STREAMS:
        c.expect(_PACK_INFO)
        if c.number() != 0 or c.number() != 1:
            raise PackError("not one packed block")
        c.expect(_SIZE)
        packed = c.number()
        c.expect(_END)
        c.expect(_UNPACK_INFO)
        c.expect(_FOLDER)
        if c.number() != 1 or c.byte() != 0 or c.number() != 1:
            raise PackError("not one folder of one coder")
        flags = c.byte()
        if flags != 0x20 | len(_LZMA2) or c.take(1) != _LZMA2 or c.number() != 1:
            raise PackError("not LZMA2")
        prop = c.byte()
        c.expect(_CODERS_UNPACK_SIZE)
        unpacked = c.number()
        c.expect(_END)
        c.expect(_SUBSTREAMS)
        c.expect(_NUM_UNPACK_STREAM)
        n = c.number()
        t = c.byte()
        if t == _SIZE:
            sizes = [c.number() for _ in range(n - 1)]
            t = c.byte()
        sizes.append(unpacked - sum(sizes))
        if t != _CRC or c.byte() != 1:
            raise PackError("a file's CRC is missing")
        crcs = [struct.unpack("<I", c.take(4))[0] for _ in range(n)]
        c.expect(_END)
        c.expect(_END)
        t = c.byte()
    if t != _FILES_INFO:
        raise PackError("not the header DataPiler writes")
    count = c.number()
    empty = [False] * count
    names: list[str] = []
    while True:
        t = c.byte()
        if t == _END:
            break
        size_t = c.number()
        body = _Cursor(c.take(size_t))
        if t == _EMPTY_STREAM:
            empty = _vector(body, count)
        elif t == _NAME:
            if body.byte() != 0:
                raise PackError("names kept outside the header")
            text = body.take(size_t - 1).decode("utf-16-le")
            names = text.split("\0")[:-1]
    c.expect(_END)
    if len(names) != count or count - sum(empty) != len(sizes):
        raise PackError("the names and the files do not match")
    out: list[tuple[str, int, int | None]] = []
    k = 0
    for name, e in zip(names, empty):
        if e:
            out.append((name, 0, None))
        else:
            out.append((name, sizes[k], crcs[k]))
            k += 1
    return out, packed, prop


def check(parts: list[Path], *, sink: Callable[[str, bytes], None] | None = None) -> list[tuple[str, int]]:
    """Reads an archive `write` made from its parts, decompresses its block and confirms every file's size and CRC-32;
    gives back [(name, size)]. sink(name, data) receives each file's bytes when given (the tests). PackError when it
    does not read back whole."""
    files, packed, prop = read_header(parts)
    r = _PartReader(parts)
    r.pos = 32
    dict_size = (2 | (prop & 1)) << (prop // 2 + 11) if prop < 40 else 0xFFFFFFFF
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dict_size}])
    queue = [(n, s, c) for n, s, c in files if s > 0]
    k, have, crc = 0, 0, 0
    buf = bytearray()
    left = packed
    try:
        while left > 0 or buf:
            if left > 0:
                chunk = r.read(min(CHUNK, left))
                left -= len(chunk)
                data = dec.decompress(chunk)
            else:
                data = b""
            buf += data
            while k < len(queue) and buf:
                name, size, want = queue[k]
                take = min(size - have, len(buf))
                piece = bytes(buf[:take])
                del buf[:take]
                crc = zlib.crc32(piece, crc)
                have += take
                if sink is not None:
                    sink(name, piece)
                if have == size:
                    if crc & 0xFFFFFFFF != want:
                        raise PackError("a file's CRC does not match")
                    k, have, crc = k + 1, 0, 0
            if k == len(queue) and buf:
                raise PackError("more data than the files hold")
            if left == 0 and not data:
                break
    except lzma.LZMAError:
        raise PackError("the packed block does not decompress") from None
    if k != len(queue) or not (dec.eof or not queue):
        raise PackError("the packed block ends early")
    if sink is not None:
        for name, size, _ in files:
            if size == 0:
                sink(name, b"")
    return [(n, s) for n, s, _ in files]
