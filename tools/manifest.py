#!/usr/bin/env python3
"""Writes <folder>/manifest.sha256 for a release (build plan 0.2 §4.11; settled S28).

    python3 tools/manifest.py <folder>

Every regular file below the folder but manifest.sha256 itself, as '<64 hex>  <path>' with '/', sorted by the UTF-8
bytes of the path, LF: the format `sha256sum -c` reads, and the one update-helper.py's parse_manifest reads. A link,
or a path the helper's safe_rel refuses, stops it with exit code 2 and nothing written. Standard library only."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "update-helper.py"
MANIFEST = "manifest.sha256"


def _helper():
    spec = importlib.util.spec_from_file_location("datapiler_update_helper_tool", str(HELPER))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class Refused(Exception):
    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


def entries(folder: Path, helper=None) -> dict[str, str]:
    """path -> sha256 for every regular file below folder but the manifest. Raises Refused for a link, a special
    file or a path safe_rel refuses."""
    h = helper or _helper()
    folder = Path(folder)
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        here = Path(dirpath)
        for d in list(dirnames):
            if (here / d).is_symlink():
                raise Refused("a link: %s" % (here / d).relative_to(folder).as_posix())
        dirnames.sort()
        for name in sorted(filenames):
            p = here / name
            rel = p.relative_to(folder).as_posix()
            if p.is_symlink():
                raise Refused("a link: %s" % rel)
            if not p.is_file():
                raise Refused("not a regular file: %s" % rel)
            if rel == MANIFEST:
                continue
            if not h.safe_rel(rel):
                raise Refused("a path DataPiler does not write: %s" % rel)
            out[rel] = h.sha256_file(p)
    return out


def write(folder: Path) -> int:
    """Writes the manifest; returns the number of files it lists."""
    h = _helper()
    found = entries(folder, h)
    data = h.format_manifest(found)
    h.parse_manifest(data)      # what it writes, it reads
    tmp = Path(folder) / (MANIFEST + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, Path(folder) / MANIFEST)
    return len(found)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: manifest.py <folder>", file=sys.stderr)
        return 2
    folder = Path(args[0])
    if not folder.is_dir() or folder.is_symlink():
        print("not a folder", file=sys.stderr)
        return 2
    try:
        count = write(folder)
    except Refused as e:
        print("refused - %s" % e.text, file=sys.stderr)
        return 2
    print("manifest.sha256: %d files" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
