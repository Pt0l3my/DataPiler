"""The game's folder, version, running check (S7), expansion and regulation.bin's hash (build plan §4.3).

Read only: nothing in the game's folder is ever written. The folder comes from Settings; nothing scans the PC."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path, PurePath

from . import fileio, winapi
from .logbook import Own, own

GAME_EXES = ("eldenring.exe", "start_protected_game.exe")
EXE = "eldenring.exe"
REGULATION = "regulation.bin"
# Relative paths in the game folder whose presence hints that the expansion is installed: none confirmed yet (build
# plan §10, P2). The owner's statement in Settings decides; this check only ever shows a hint on Status (S21).
EXPANSION_MARKERS: tuple[str, ...] = ()


@dataclass(frozen=True)
class GameRunning:
    running: bool
    why: Own | None      # "eldenring.exe is running", "a program from the game's folder is running",
                         # "the process list could not be read"


UNREADABLE = own("the process list could not be read")
_lock = threading.Lock()
_version_cache: dict[str, tuple[tuple[int, int], str | None]] = {}
_sha_cache: dict[str, tuple[tuple[int, int], str]] = {}


def _norm_parts(path: str) -> tuple[str, ...]:
    return tuple(os.path.normcase(x) for x in PurePath(os.path.abspath(path)).parts)


def _folder_parts(folder: str) -> list[tuple[str, ...]]:
    out = [_norm_parts(folder)]
    try:
        real = _norm_parts(str(Path(folder).resolve()))
        if real not in out:
            out.append(real)
    except (OSError, RuntimeError):
        pass
    return out


def running(game_dir: str) -> GameRunning:
    """S7: running when a process named as in GAME_EXES exists (any case), or, with game_dir set, any process
    whose image lies inside game_dir. Fails closed: an unreadable process list counts as running. Never raises."""
    try:
        procs = winapi.backend().processes()
    except Exception:
        return GameRunning(True, UNREADABLE)
    try:
        for p in procs:
            name = (p.name or "").lower()
            for exe in GAME_EXES:
                if name == exe:
                    return GameRunning(True, own(exe + " is running"))
        if game_dir:
            folders = _folder_parts(game_dir)
            for p in procs:
                if not p.path:
                    continue
                parts = _norm_parts(p.path)
                for f in folders:
                    if len(parts) > len(f) and parts[: len(f)] == f:
                        return GameRunning(True, own("a program from the game's folder is running"))
    except Exception:
        return GameRunning(True, UNREADABLE)
    return GameRunning(False, None)


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def exe_path(game_dir: str) -> Path | None:
    if not game_dir:
        return None
    p = Path(game_dir) / EXE
    return p if p.is_file() else None


def version(game_dir: str) -> str | None:
    """eldenring.exe's version resource, cached by the exe's size and mtime."""
    exe = exe_path(game_dir)
    if exe is None:
        return None
    key = _stat_key(exe)
    if key is None:
        return None
    with _lock:
        hit = _version_cache.get(str(exe))
        if hit and hit[0] == key:
            return hit[1]
    try:
        v = winapi.backend().file_version(str(exe))
    except Exception:
        v = None
    with _lock:
        _version_cache[str(exe)] = (key, v)
    return v


def expansion(game_dir: str) -> bool | None:
    """A hint for Status only, never a decision (P2): whether the marker files are present; None until
    EXPANSION_MARKERS is set."""
    if not EXPANSION_MARKERS or not game_dir:
        return None
    root = Path(game_dir)
    if not root.is_dir():
        return None
    return all((root / m).exists() for m in EXPANSION_MARKERS)


def regulation_sha256(game_dir: str) -> str | None:
    """sha256 of regulation.bin (no decryption), recomputed only when its size or mtime_ns changes."""
    if not game_dir:
        return None
    reg = Path(game_dir) / REGULATION
    key = _stat_key(reg)
    if key is None:
        return None
    with _lock:
        hit = _sha_cache.get(str(reg))
        if hit and hit[0] == key:
            return hit[1]
    try:
        sha = fileio.sha256_file(reg)
    except OSError:
        return None
    with _lock:
        _sha_cache[str(reg)] = (key, sha)
    return sha
