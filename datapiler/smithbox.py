"""Smithbox's folder, build, running, and the server's switch read from Startup.json (build plan §4.3).

Read only: no Smithbox file is ever written. Startup.json is at %LOCALAPPDATA%\\Smithbox\\Configuration\\Startup.json
(EldenNet's ER08 §3.1); the server starts only while System_Enable_Soapstone_Server is true."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from . import fileio, winapi

SWITCH_KEY = "System_Enable_Soapstone_Server"
EXE_NAME = "Smithbox.exe"                  # to verify (build plan §10, P1)
STARTUP_MAX = 1024 * 1024

_lock = threading.Lock()
_build_cache: dict[str, tuple[tuple[int, int], str | None]] = {}


def startup_json() -> Path | None:
    """%LOCALAPPDATA%\\Smithbox\\Configuration\\Startup.json (ER08 §3.1), or None without LOCALAPPDATA."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    return Path(base) / "Smithbox" / "Configuration" / "Startup.json"


def _find(doc: object, depth: int = 0) -> object:
    if isinstance(doc, dict):
        if SWITCH_KEY in doc:
            return doc[SWITCH_KEY]
        if depth < 3:
            for v in doc.values():
                found = _find(v, depth + 1)
                if found is not None:
                    return found
    return None


def read_switch(path: Path | None) -> bool | None:
    """The key's value, read only. None when the file or the key is missing or unreadable. Never writes."""
    if path is None:
        return None
    try:
        data = fileio.read_limited(Path(path), STARTUP_MAX)
        doc = json.loads(data.decode("utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    v = _find(doc)
    return v if isinstance(v, bool) else None


def exe_path(smithbox_dir: str) -> Path | None:
    if not smithbox_dir:
        return None
    p = Path(smithbox_dir) / EXE_NAME
    return p if p.is_file() else None


def installed(smithbox_dir: str) -> bool:
    return exe_path(smithbox_dir) is not None


def build(smithbox_dir: str) -> str | None:
    """Smithbox.exe's version resource."""
    exe = exe_path(smithbox_dir)
    if exe is None:
        return None
    try:
        st = exe.stat()
    except OSError:
        return None
    key = (st.st_size, st.st_mtime_ns)
    with _lock:
        hit = _build_cache.get(str(exe))
        if hit and hit[0] == key:
            return hit[1]
    try:
        v = winapi.backend().file_version(str(exe))
    except Exception:
        v = None
    with _lock:
        _build_cache[str(exe)] = (key, v)
    return v


def running(smithbox_dir: str) -> bool | None:
    """Whether a process named Smithbox.exe runs; None when the process list cannot be read."""
    try:
        procs = winapi.backend().processes()
    except Exception:
        return None
    name = EXE_NAME.lower()
    return any((p.name or "").lower() == name for p in procs)


def open_project() -> str | None:
    """None in 0.1: where Smithbox records its open project is not established (build plan §10, P1)."""
    return None
