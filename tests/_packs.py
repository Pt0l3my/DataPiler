"""Invented DCX and BND4 files for the tests (S81): DataPiler's own writer of the layouts gamefiles reads. Every name and
byte in them is made up; no game file is ever used."""

from __future__ import annotations

import struct
import zlib


def reverse_bits(b: int) -> int:
    return int("{:08b}".format(b)[::-1], 2)


def dcx_bytes(payload: bytes, kind: bytes = b"DFLT", *, raw_len: int | None = None, comp: bytes | None = None) -> bytes:
    """A DCX of payload: DFLT packs it with zlib; any other kind keeps it as it is (a fake Oodle gives it back)."""
    if comp is None:
        comp = zlib.compress(payload, 9) if kind == b"DFLT" else payload
    h = b"DCX\0" + struct.pack(">IIIII", 0x11000, 0x18, 0x24, 0x44, 0x4C)
    h += b"DCS\0" + struct.pack(">II", len(payload) if raw_len is None else raw_len, len(comp))
    h += b"DCP\0" + kind + struct.pack(">I", 0x20) + bytes([9 if kind == b"DFLT" else 6, 0, 0, 0]) \
        + struct.pack(">I", 0) + bytes(4) + struct.pack(">I", 0) + struct.pack(">I", 0x10100)
    h += b"DCA\0" + struct.pack(">I", 8)
    assert len(h) == 0x4C
    return h + comp


def bnd4_bytes(files: list[tuple[int, str | None, bytes, bool]], *, fmt: int = 0x2E, unicode: bool = True,
               big: bool = False, bit_big: bool = False) -> bytes:
    """A BND4 binder of (id, name, data, compressed) files; a compressed file's data is given as a DCX already."""
    e = ">" if big else "<"
    long_off, comp, ids, names = fmt & 0x10, fmt & 0x20, fmt & 0x02, fmt & 0x0C
    fh = 0x10 + (8 if long_off else 4) + (8 if comp else 0) + (4 if ids else 0) + (4 if names else 0) \
        + (8 if fmt == 0x04 else 0)
    pos = 0x40 + len(files) * fh
    name_offs, blobs = [], []
    for _, name, _, _ in files:
        if not names or name is None:
            name_offs.append(0)
            continue
        nb = (name.encode("utf-16-be" if big else "utf-16-le") + b"\0\0") if unicode else name.encode("cp932") + b"\0"
        name_offs.append(pos)
        blobs.append(nb)
        pos += len(nb)
    data_at = (pos + 15) // 16 * 16
    head = b"BND4" + bytes([0, 0, 0, 0]) + bytes([0, 1 if big else 0, 0 if bit_big else 1, 0])
    head += struct.pack(e + "i", len(files)) + struct.pack(e + "q", 0x40) + b"07D7R6\0\0"
    head += struct.pack(e + "q", fh) + struct.pack(e + "q", data_at)
    head += bytes([1 if unicode else 0, fmt if bit_big else reverse_bits(fmt), 0, 0]) + struct.pack(e + "i", 0) \
        + struct.pack(e + "q", 0)
    assert len(head) == 0x40
    headers, datas = b"", b""
    at = data_at
    for (fid, _, data, compressed), noff in zip(files, name_offs):
        flags = 0x02 | (0x01 if compressed else 0)
        h = bytes([flags if bit_big else reverse_bits(flags), 0, 0, 0]) + struct.pack(e + "i", -1)
        h += struct.pack(e + "q", len(data))
        if comp:
            h += struct.pack(e + "q", len(data))
        h += struct.pack(e + "q", at) if long_off else struct.pack(e + "I", at)
        if ids:
            h += struct.pack(e + "i", fid)
        if names:
            h += struct.pack(e + "I", noff)
        if fmt == 0x04:
            h += struct.pack(e + "i", fid) + struct.pack(e + "i", 0)
        assert len(h) == fh
        headers += h
        datas += data + bytes((-len(data)) % 16)
        at += len(data) + (-len(data)) % 16
    body = head + headers + b"".join(blobs)
    return body + bytes(data_at - len(body)) + datas


class FakeOodle:
    """Stands in for the game's library: gives back what a test's KRAK DCX holds as it is."""

    def __init__(self):
        self.calls = 0

    def decompress(self, comp, raw_len: int) -> bytes:
        self.calls += 1
        b = bytes(comp)
        if len(b) != raw_len:
            from datapiler.gamefiles import FormatError
            raise FormatError("a KRAK DCX that the game's Oodle library could not decompress")
        return b


def menu_like(names: tuple[str, ...] = ("a_m00.testmsk", "a_m01.testmsk")) -> bytes:
    """A KRAK DCX holding a BND4 of small invented files, named under an invented INTERROOT path."""
    files = [(k, "\\XX\\data\\INTERROOT_win64\\menu\\Invented\\mask\\" + n, bytes([k]) * (40 + k), False)
             for k, n in enumerate(names)]
    return dcx_bytes(bnd4_bytes(files), b"KRAK")
