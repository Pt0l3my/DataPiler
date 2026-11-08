"""The Python found and the venv's state, for the `env` log lines and the start log (build plan §4.2).

Nothing here imports grpc or protobuf: the libraries' versions are read from their installed metadata."""

from __future__ import annotations

import os
import platform
import struct
import sys
from pathlib import Path

from . import fileio
from .logbook import Own, own
from .paths import Paths

LIBRARIES = ("grpcio", "protobuf")


def python_info() -> Own:
    """"Python 3.12.7 (64-bit)"."""
    return own("Python %s (%d-bit)" % (platform.python_version(), struct.calcsize("P") * 8))


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def in_venv(p: Paths) -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) and _same(Path(sys.prefix), p.venv)


def venv_matches(p: Paths) -> bool:
    """The marker holds the sha256 of requirements.lock's bytes."""
    try:
        marker = fileio.read_limited(p.venv_marker, 1024).decode("ascii").strip().lower()
        return bool(marker) and marker == fileio.sha256_file(p.lock)
    except (OSError, ValueError):
        return False


def venv_state(p: Paths) -> Own:
    """One of "running in .venv, matching the lock", ".venv differs from the lock", "no .venv",
    "running outside .venv"; from sys.prefix and .venv/datapiler-lock.sha256 against sha256(requirements.lock)."""
    if in_venv(p):
        return own("running in .venv, matching the lock") if venv_matches(p) else own(".venv differs from the lock")
    if not p.venv.is_dir():
        return own("no .venv")
    return own("running outside .venv")


def library_versions() -> dict[str, Own | None]:
    """{"grpcio": "1.2.3" or None, "protobuf": ...} from the installed metadata; never imports the libraries."""
    out: dict[str, Own | None] = {}
    try:
        from importlib import metadata
    except ImportError:
        return {name: None for name in LIBRARIES}
    for name in LIBRARIES:
        try:
            v = metadata.version(name)
        except Exception:
            v = None
        out[name] = own(v) if v and all(c.isalnum() or c in ".+-" for c in v) and len(v) <= 32 else None
    return out
