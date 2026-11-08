"""Files: the atomic write, hashes and bounded reads (build plan §3.1).

`write_atomic` is copied from LLM Jobrunner 1.2's `write_atomic`, unchanged in what it does (build plan §7.1)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

CHUNK = 1 << 20


class TooLarge(ValueError):
    """A file or a request over its limit."""


def write_atomic(path: Path, data: bytes) -> None:
    """Write data through "<path>.<pid>.tmp" in the same folder, flush, fsync, os.replace. Raises OSError."""
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sha256_bytes(data: bytes) -> str:
    """Lower-case hex."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Lower-case hex, read in 1 MiB chunks. Raises OSError."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def read_limited(path: Path, max_bytes: int) -> bytes:
    """The file's bytes. Raises TooLarge past max_bytes, OSError otherwise."""
    with open(path, "rb") as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise TooLarge("over %d bytes" % max_bytes)
    return data
