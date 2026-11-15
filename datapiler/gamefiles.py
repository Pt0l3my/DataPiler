"""Game files that Smithbox unpacked (DP28, settled S81): DataPiler's own reader of the DCX and BND4 formats.

The owner unpacks parts of the game with Smithbox into a folder inside DataPiler's folder. A job names one of those
files by its file name; `find_file` walks DataPiler's folder for it by the rules of textures.find_tiles (the Deleted
bin, the environment, logs, update downloads and DataPiler's own outputs left out, as are links), and `unpack` opens it
on the PC. A DCX is decompressed: DFLT with zlib, KRAK with the game's own Oodle library, which `load_oodle` loads from
the game folder at run time and never copies, ships or commits; any other kind is refused. A BND4 binder is split into
its inner files, and an inner file that is a DCX or a BND4 is opened in turn, MAX_NEST binders deep. DataPiler never
decrypts an archive and holds no key: it opens only what Smithbox has already unpacked, and reads nothing in the game
folder but that one library.

`unpack` hands each inner file to the caller with a safe relative path (the job's workspace folder on the PC, never
shared) and gives back one row of numbers per file (UNPACK_COLUMNS): its place, its binder's, its depth, its ID, its
kind and packing as numbers, and its sizes. No name, path or byte of the data reaches a table or a log line.

The layouts were learnt from SoulsFormats (MIT, read in Smithbox's sources, never copied): a DCX header is big-endian,
`DCX\\0`, its version, then the DCS block (sizes), the DCP block (the packing) and the DCA block, with the data at 0x4C;
a BND4 header is 0x40 bytes, its format byte bit-reversed unless the file says otherwise, then one file header per
inner file, whose size the format byte fixes."""

from __future__ import annotations

import hashlib
import os
import re
import struct
import threading
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Collection

from . import textures

Cancelled = textures.Cancelled

FILE_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")   # a file name a job names: no folder, no drive
KEY_RX = re.compile(r"(?i).*(key|secret|regulation).*")    # the game's keys and its encrypted regulation: never opened
MAX_INPUT = 512 * 2 ** 20       # bytes of the file a job names, at most
MAX_OUTPUT = 2 * 2 ** 30        # bytes one unpack writes, at most
MAX_ENTRIES = 50_000            # inner files, every binder together
MAX_NEST = 4                    # binders inside binders
MAX_NAME = 1024                 # characters of an inner file's name
MAX_PARTS = 12                  # folders and name of an inner file's path
OODLE_RX = re.compile(r"oo2core_(\d+)_win64\.dll", re.IGNORECASE)
OODLE_VERSIONS = (9, 8, 6)      # those whose OodleLZ_Decompress takes the fourteen arguments below; newest first
OODLE_PAD = 64 * 1024           # room past the output's end, as the library's own decode-buffer size allows for

# What unpack makes (S81): one row per file, the named file first. file: its place in the table; parent: its binder's
# row (-1 for the named file); depth: binders above it; id: its BND4 ID (-1 if none); kind (KINDS) and packing
# (PACKINGS) as numbers; stored: its bytes as stored; size: its bytes once decompressed.
UNPACK_COLUMNS: tuple[tuple[str, str], ...] = (("file", "int"), ("parent", "int"), ("depth", "int"), ("id", "int"),
                                               ("kind", "int"), ("packing", "int"), ("stored", "int"), ("size", "int"))
KINDS = {"other": 0, "bnd4": 1, "bnd3": 2, "bhf": 3, "tpf": 4, "gfx": 5, "dds": 6, "png": 7, "dcx": 8}
PACKINGS = {"none": 0, "dflt": 1, "krak": 2}
UNPACKED_SUFFIX = "_unpacked"   # the folder a binder inside a binder is written into, after its own name

_PNG = b"\x89PNG\r\n\x1a\n"
_SEG_BAD = re.compile(r"[^A-Za-z0-9 ._()+\-]")
_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[0-9]|LPT[0-9])(\..*)?", re.IGNORECASE)


class FormatError(ValueError):
    """The file is not what DataPiler opens: its message says why, in the owner's words, with no path."""


class Unavailable(RuntimeError):
    """A KRAK file, and the game's Oodle library cannot be used: its message says why, with no path."""


# ------------------------------------------------------------------------------------------------ DCX

def kind_of(b: bytes | memoryview) -> int:
    h = bytes(b[:8])
    if h[:4] == b"BND4":
        return KINDS["bnd4"]
    if h[:4] == b"BND3":
        return KINDS["bnd3"]
    if h[:4] in (b"BHF4", b"BHF3"):
        return KINDS["bhf"]
    if h[:4] == b"TPF\0":
        return KINDS["tpf"]
    if h[:3] in (b"GFX", b"CFX", b"FWS", b"CWS"):
        return KINDS["gfx"]
    if h[:4] == b"DDS ":
        return KINDS["dds"]
    if h == _PNG:
        return KINDS["png"]
    if h[:4] == b"DCX\0":
        return KINDS["dcx"]
    return KINDS["other"]


def _inflate(payload: bytes | memoryview, raw_len: int) -> bytes:
    """A DFLT payload: a zlib header, then deflate. Its checksum is not needed, as SoulsFormats reads it."""
    p = bytes(payload)
    if len(p) < 2 or p[0] & 0x0F != 8 or (p[0] * 256 + p[1]) % 31 != 0:
        raise FormatError("a DFLT DCX whose data is not zlib")
    d = zlib.decompressobj(-15)
    try:
        out = d.decompress(p[2:], raw_len + 1)
    except zlib.error:
        raise FormatError("a DFLT DCX whose data does not inflate") from None
    if len(out) != raw_len:
        raise FormatError("a DFLT DCX whose data is not the size its header says")
    return out


def dcx(data: bytes | memoryview, oodle: Callable[[], "Oodle"] | None) -> tuple[bytes, int]:
    """The payload of a DCX and its packing (PACKINGS). FormatError for what is not a DCX this reader knows;
    Unavailable from `oodle` for a KRAK one when the game's library cannot be used."""
    if len(data) < 0x4C or bytes(data[:4]) != b"DCX\0":
        raise FormatError("not a DCX file")
    version, dcs, dcp = struct.unpack_from(">III", data, 4)
    if version not in (0x10000, 0x11000) or dcs != 0x18 or dcp != 0x24 or bytes(data[0x18:0x1C]) != b"DCS\0" \
            or bytes(data[0x24:0x28]) != b"DCP\0":
        raise FormatError("a DCX header DataPiler does not know")
    raw_len, comp_len = struct.unpack_from(">II", data, 0x1C)
    kind = bytes(data[0x28:0x2C])
    (dcp_size,) = struct.unpack_from(">I", data, 0x2C)
    dca = 0x24 + dcp_size
    if dcp_size != 0x20 or bytes(data[dca:dca + 4]) != b"DCA\0" or struct.unpack_from(">I", data, dca + 4)[0] != 8:
        raise FormatError("a DCX header DataPiler does not know")
    start = dca + 8
    if start + comp_len > len(data):
        raise FormatError("a DCX shorter than its header says")
    if raw_len > MAX_OUTPUT:
        raise FormatError("a DCX larger than DataPiler opens")
    payload = data[start:start + comp_len]
    if kind == b"DFLT":
        return _inflate(payload, raw_len), PACKINGS["dflt"]
    if kind == b"KRAK":
        if oodle is None:
            raise Unavailable("a KRAK DCX, and the game's Oodle library is not at hand")
        return oodle().decompress(payload, raw_len), PACKINGS["krak"]
    if kind == b"ZSTD":
        raise FormatError("a ZSTD DCX, which DataPiler does not open")
    raise FormatError("a DCX packed in a way DataPiler does not open")


# ------------------------------------------------------------------------------------------------ the game's Oodle

class Oodle:
    """The game's own Oodle library (DP28), loaded from the game folder at run time. Never copied, shipped or committed;
    its one call is OodleLZ_Decompress, with the arguments SoulsFormats passes it (fuzz-safe, no CRC check, quiet, no
    callback, unthreaded)."""

    def __init__(self, path: Path):
        import ctypes

        self._ct = ctypes
        lib = ctypes.CDLL(str(path))
        f = lib.OodleLZ_Decompress
        f.restype = ctypes.c_ssize_t
        f.argtypes = (ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_int,
                      ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_int)
        self._f = f
        self._lock = threading.Lock()

    def decompress(self, comp: bytes | memoryview, raw_len: int) -> bytes:
        src = bytes(comp)
        out = self._ct.create_string_buffer(raw_len + OODLE_PAD)
        with self._lock:
            n = self._f(src, len(src), out, raw_len, 1, 0, 0, None, 0, None, None, None, 0, 3)
        if n != raw_len:
            raise FormatError("a KRAK DCX that the game's Oodle library could not decompress")
        return out.raw[:raw_len]


_loaded: dict[str, Oodle] = {}
_load_lock = threading.Lock()


def oodle_file(game_dir: str) -> Path | None:
    """The game's Oodle library in its Game folder (the folder that holds eldenring.exe): the newest of
    OODLE_VERSIONS there, a plain file, not a link. None when there is none or the folder is not the game's."""
    from . import game

    if not game_dir or game.exe_path(game_dir) is None:
        return None
    found: dict[int, Path] = {}
    try:
        with os.scandir(game_dir) as it:
            for entry in it:
                m = OODLE_RX.fullmatch(entry.name)
                if m and int(m.group(1)) in OODLE_VERSIONS and entry.is_file(follow_symlinks=False):
                    found[int(m.group(1))] = Path(entry.path)
    except OSError:
        return None
    return next((found[v] for v in OODLE_VERSIONS if v in found), None)


def _pe_x64(path: Path) -> bool:
    """A 64-bit Windows library by its headers (read only, 4 KiB at most)."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    if len(head) < 0x40 or head[:2] != b"MZ":
        return False
    (pe,) = struct.unpack_from("<I", head, 0x3C)
    return pe + 6 <= len(head) and head[pe:pe + 4] == b"PE\0\0" and struct.unpack_from("<H", head, pe + 4)[0] == 0x8664


def load_oodle(game_dir: str) -> Oodle:
    """The game's Oodle library, loaded once per process. Unavailable, saying why, off Windows, without the game
    folder's library, or when it does not load."""
    if os.name != "nt":
        raise Unavailable("a KRAK DCX, which needs the game's Oodle library: DataPiler loads it on Windows only")
    path = oodle_file(game_dir)
    if path is None:
        raise Unavailable("a KRAK DCX, which needs the game's Oodle library (oo2core_6, 8 or 9), and the game folder "
                          "in Settings holds none")
    if not _pe_x64(path):
        raise Unavailable("a KRAK DCX, and the game folder's Oodle library is not a 64-bit Windows library")
    key = os.path.normcase(os.path.abspath(str(path)))
    with _load_lock:
        o = _loaded.get(key)
        if o is None:
            try:
                o = Oodle(path)
            except (OSError, AttributeError):
                raise Unavailable("a KRAK DCX, and the game folder's Oodle library could not be loaded") from None
            _loaded[key] = o
    return o


# ------------------------------------------------------------------------------------------------ BND4

@dataclass(frozen=True)
class Entry:
    index: int
    id: int
    name: str | None
    compressed: bool
    offset: int
    stored: int
    size: int           # -1 where the binder's format holds none


def _reverse_bits(b: int) -> int:
    return int("{:08b}".format(b)[::-1], 2)


def _name_at(blob: bytes | memoryview, at: int, unicode: bool, big: bool) -> str:
    if not 0 <= at < len(blob):
        raise FormatError("a BND4 file name outside the binder")
    if unicode:
        end, limit = at, min(len(blob) - 1, at + 2 * MAX_NAME)
        while end < limit and (blob[end] or blob[end + 1]):
            end += 2
        return bytes(blob[at:end]).decode("utf-16-be" if big else "utf-16-le", errors="replace")
    raw = bytes(blob[at:at + MAX_NAME])
    end = raw.find(b"\0")
    return (raw if end < 0 else raw[:end]).decode("cp932", errors="replace")


def bnd4(blob: bytes | memoryview) -> list[Entry]:
    """The inner files of a BND4 binder, in its order. FormatError for what is not a BND4 this reader knows."""
    if len(blob) < 0x40 or bytes(blob[:4]) != b"BND4":
        raise FormatError("not a BND4 binder")
    big = blob[9] == 1
    bit_big = blob[0x0A] == 0
    e = ">" if big else "<"
    (count,) = struct.unpack_from(e + "i", blob, 0x0C)
    (header_size,) = struct.unpack_from(e + "q", blob, 0x10)
    (fh_size,) = struct.unpack_from(e + "q", blob, 0x20)
    unicode = blob[0x30] == 1
    raw = blob[0x31]
    fmt = raw if (bit_big or (raw & 1 and not raw & 0x80)) else _reverse_bits(raw)
    long_off, comp, ids, names = fmt & 0x10, fmt & 0x20, fmt & 0x02, fmt & 0x0C
    want = 0x10 + (8 if long_off else 4) + (8 if comp else 0) + (4 if ids else 0) + (4 if names else 0) \
        + (8 if fmt == 0x04 else 0)
    if header_size != 0x40 or not 0 <= count <= MAX_ENTRIES or fh_size != want:
        raise FormatError("a BND4 header DataPiler does not know")
    if 0x40 + count * want > len(blob):
        raise FormatError("a BND4 binder shorter than its header says")
    out = []
    for i in range(count):
        at = 0x40 + i * want
        flags = blob[at] if bit_big else _reverse_bits(blob[at])
        if struct.unpack_from(e + "i", blob, at + 4)[0] != -1:
            raise FormatError("a BND4 file header DataPiler does not know")
        pos = at + 8
        (stored,) = struct.unpack_from(e + "q", blob, pos)
        pos += 8
        size = -1
        if comp:
            (size,) = struct.unpack_from(e + "q", blob, pos)
            pos += 8
        if long_off:
            (offset,) = struct.unpack_from(e + "q", blob, pos)
            pos += 8
        else:
            (offset,) = struct.unpack_from(e + "I", blob, pos)
            pos += 4
        fid = -1
        if ids:
            (fid,) = struct.unpack_from(e + "i", blob, pos)
            pos += 4
        name = None
        if names:
            (name_off,) = struct.unpack_from(e + "I", blob, pos)
            name = _name_at(blob, name_off, unicode, big)
            pos += 4
        if fmt == 0x04:
            (fid,) = struct.unpack_from(e + "i", blob, pos)
        if stored < 0 or offset < 0 or offset + stored > len(blob):
            raise FormatError("a BND4 file outside the binder")
        out.append(Entry(i, fid, name, bool(flags & 1), offset, stored, size))
    return out


# ------------------------------------------------------------------------------------------------ paths

def safe_parts(name: str | None, index: int) -> tuple[str, ...]:
    """The relative path an inner file is written to, as parts: its name's folders after any drive and the game's
    INTERROOT folder, each part made safe for Windows. Never `..`, a drive, an absolute path or a device's name."""
    raw: list[str] = []
    if name:
        s = re.sub(r"^[A-Za-z]:", "", name.replace("\\", "/"))
        raw = [x for x in s.split("/") if x not in ("", ".")]
        roots = [k for k, x in enumerate(raw) if x.lower().startswith("interroot")]
        if roots:
            raw = raw[roots[-1] + 1:]
    parts = []
    for x in raw[-MAX_PARTS:]:
        x = _SEG_BAD.sub("_", "_" if x == ".." else x)[:100].rstrip(" .")
        if not x:
            x = "_"
        if _RESERVED.fullmatch(x):
            x = "_" + x
        parts.append(x)
    return tuple(parts) or ("file-%05d.bin" % index,)


def _suffixed(name: str, n: int) -> str:
    stem, dot, ext = name.rpartition(".")
    return "%s-%d.%s" % (stem, n, ext) if dot and stem else "%s-%d" % (name, n)


def _undcx(parts: tuple[str, ...], packing: int) -> tuple[str, ...]:
    """A decompressed file's name without its `.dcx`."""
    if packing and parts[-1].lower().endswith(".dcx") and len(parts[-1]) > 4:
        return parts[:-1] + (parts[-1][:-4],)
    return parts


class _Namer:
    """Keeps every path unique (in any case) and never a file where a folder is, or a folder where a file is."""

    def __init__(self):
        self.files: set[str] = set()
        self.dirs: set[str] = set()

    @staticmethod
    def _key(parts: tuple[str, ...]) -> str:
        return "/".join(parts).lower()

    def _free(self, parts: tuple[str, ...]) -> bool:
        k = self._key(parts)
        return k not in self.files and k not in self.dirs and \
            not any(self._key(parts[:j]) in self.files for j in range(1, len(parts)))

    def place(self, parts: tuple[str, ...], *, folder: bool = False) -> tuple[str, ...]:
        if any(self._key(parts[:j]) in self.files for j in range(1, len(parts))):
            top, k = "_clash", 2                       # a file stands where one of its folders would be
            while self._key((top,)) in self.files:
                top, k = "_clash-%d" % k, k + 1
            parts = (top, parts[-1])
        p, n = parts, 2
        while not self._free(p):
            p, n = parts[:-1] + (_suffixed(parts[-1], n),), n + 1
        (self.dirs if folder else self.files).add(self._key(p))
        for j in range(1, len(p)):
            self.dirs.add(self._key(p[:j]))
        return p


# ------------------------------------------------------------------------------------------------ unpack

def unpack(data: bytes | memoryview, file_name: str, emit: Callable[[tuple[str, ...], bytes], None], *,
           oodle: Callable[[], Oodle] | None = None, cancel: threading.Event | None = None) -> list[tuple[int, ...]]:
    """Opens a game file and hands each inner file to emit(relative parts, bytes); gives back one row of
    UNPACK_COLUMNS per file, the named file first. A DCX that holds no binder is written as its payload, named as the
    file without `.dcx`. FormatError for a file that is neither a DCX nor a BND4, or that breaks a limit."""
    rows: list[tuple[int, ...]] = []
    namer = _Namer()
    total = [0]

    def opened(b: bytes | memoryview) -> tuple[bytes | memoryview, int]:
        if bytes(b[:4]) == b"DCX\0":
            return dcx(b, oodle)
        return b, PACKINGS["none"]

    def put(parts: tuple[str, ...], body: bytes | memoryview, packing: int) -> None:
        parts = _undcx(parts, packing)
        total[0] += len(body)
        if total[0] > MAX_OUTPUT:
            raise FormatError("more than DataPiler writes from one file (%d MiB)" % (MAX_OUTPUT // 2 ** 20))
        emit(namer.place(parts), bytes(body))

    def binder(blob: bytes | memoryview, parent: int, depth: int, prefix: tuple[str, ...]) -> None:
        for en in bnd4(blob):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if len(rows) > MAX_ENTRIES:
                raise FormatError("more than %d inner files" % MAX_ENTRIES)
            stored = memoryview(blob)[en.offset:en.offset + en.stored]
            if en.compressed and bytes(stored[:4]) != b"DCX\0":
                raise FormatError("a BND4 file marked compressed that is not a DCX")
            body, packing = opened(stored)
            kind = kind_of(body)
            here = len(rows)
            rows.append((here, parent, depth, en.id, kind, packing, en.stored, len(body)))
            parts = prefix + safe_parts(en.name, en.index)
            if kind == KINDS["bnd4"] and depth < MAX_NEST:
                named = _undcx(parts, packing)
                folder = namer.place(named[:-1] + (named[-1] + UNPACKED_SUFFIX,), folder=True)
                binder(body, here, depth + 1, folder)
            else:
                put(parts, body, packing)

    if len(data) > MAX_INPUT:
        raise FormatError("larger than DataPiler opens (%d MiB)" % (MAX_INPUT // 2 ** 20))
    top, packing = opened(data)
    kind = kind_of(top)
    rows.append((0, -1, 0, -1, kind, packing, len(data), len(top)))
    if kind == KINDS["bnd4"]:
        binder(top, 0, 1, ())
    elif packing:
        put(safe_parts(file_name, 0), top, packing)
    else:
        raise FormatError("neither a DCX nor a BND4 file, so there is nothing to unpack")
    return rows


# ------------------------------------------------------------------------------------------------ finding the file

def find_file(root: Path, name: str, *, skip: Collection[Path] = (), cancel: threading.Event | None = None
              ) -> tuple[list[Path], dict[str, int]]:
    """Every plain file under root named `name` (in any case), by textures.find_tiles's rules; and counts: files
    looked at, whether the walk stopped at textures.MAX_FILES. The paths stay with the caller: never logged."""
    root = Path(root)
    want = name.lower()
    skipped = {os.path.normcase(os.path.abspath(str(s))) for s in skip}
    base_depth = len(Path(os.path.abspath(str(root))).parts)
    found: list[Path] = []
    looked = 0
    stopped = False
    for here, dirs, files in os.walk(root, followlinks=False):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        depth = len(Path(os.path.abspath(here)).parts) - base_depth
        dirs[:] = sorted(d for d in dirs if d.lower() not in textures.SKIP_DIRS and depth < textures.MAX_DEPTH
                         and not os.path.islink(os.path.join(here, d))
                         and os.path.normcase(os.path.abspath(os.path.join(here, d))) not in skipped)
        for f in sorted(files):
            looked += 1
            if looked > textures.MAX_FILES:
                stopped = True
                break
            full = os.path.join(here, f)
            if f.lower() == want and not os.path.islink(full) and os.path.isfile(full):
                found.append(Path(full))
        if stopped:
            break
    return found, {"looked": looked, "stopped": int(stopped)}


def digest(path: Path) -> tuple[int, str]:
    """(size, sha256) of a file, read in blocks."""
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            n += len(b)
            h.update(b)
    return n, h.hexdigest()
