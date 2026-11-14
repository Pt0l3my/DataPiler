"""Packs the rendered PNGs of DataPiler's icon into launcher-src/app.ico (S65). Standard library only.

Usage, from the repository's root, after `python3 tools/icon/make_svg.py` and `node tools/icon/render.js` (or any SVG
renderer) have written png/<size>.png for each size below, in the current folder:

    python3 -I tools/icon/make_ico.py png launcher-src/app.ico

Each image goes in as PNG, 32-bit with alpha, which Windows reads at every size since Vista."""

import struct
import sys
from pathlib import Path

SIZES = (256, 128, 64, 48, 32, 24, 20, 16)
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        raise ValueError("not a PNG")
    return struct.unpack(">II", data[16:24])


def pack(images: list[bytes]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, body = b"", b""
    for data in images:
        w, h = png_size(data)
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(data), offset)
        body += data
        offset += len(data)
    return head + entries + body


def main(src: str, out: str) -> None:
    images = []
    for n in SIZES:
        data = (Path(src) / ("%d.png" % n)).read_bytes()
        if png_size(data) != (n, n):
            raise SystemExit("%d.png is not %d by %d" % (n, n, n))
        images.append(data)
    Path(out).write_bytes(pack(images))
    print("wrote %s: %d sizes" % (out, len(images)))


if __name__ == "__main__":
    main(*sys.argv[1:3])
