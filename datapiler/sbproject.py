"""Smithbox's record of its projects, read only (build plan 0.2 §5.3; smithbox-projects.md §6).

Everything here is a lead (EldenNet O48) until smithbox-projects.md §7 passes on the owner's PC: the record's places
are offered for Use, never applied. One file per project, `<Local AppData>\\Smithbox\\Projects\\*.json`, per Windows
user; the five keys ProjectName, ProjectPath, DataPath, ProjectType and AutoSelect, every other key dropped at once.

Never: an exception out of read(), a pattern search over the text, a fallback to other keys or to a project's own
project.json, a write, a lock or a rename, or a read of Smithbox's Configuration.json. The names and paths stay in
memory for the session; the log names counts only."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import fileio, logbook
from .logbook import Own, own

PROJECT_MARKS = ("project.json", ".smithbox")   # the weaker "a Smithbox project file is here" (its §5)
ER_TYPES = (8, "ER")
FILES_MAX = 64
FILE_MAX = 1024 * 1024
RETRY_SECS = 0.5
PATH_MAX = 1024
NAME_MAX = 128

NOT_FOUND = own("No Smithbox project record was found")
_DRIVE_RX = re.compile(r"[A-Za-z]:[\\/]")
_CONTROL_RX = re.compile(r"[\x00-\x1f\x7f]")

_log = logbook.get("folders")


@dataclass(frozen=True)
class ProjectLead:
    name: str
    project_dir: str
    data_dir: str
    marked: bool         # the record's AutoSelect: the project Smithbox opens at start


@dataclass(frozen=True)
class Record:
    found: bool                           # the Projects folder was there and could be read
    leads: tuple[ProjectLead, ...]        # recognised Elden Ring records
    other_games: int
    unrecognised: int
    why: Own | None                       # its §6's words, or None

    def open_lead(self) -> ProjectLead | None:
        """The one marked Elden Ring record; None when none or two or more are marked (no "open" tag then)."""
        marked = [x for x in self.leads if x.marked]
        return marked[0] if len(marked) == 1 else None


def projects_folder(local_appdata: str | None) -> Path | None:
    if not local_appdata or not isinstance(local_appdata, str):
        return None
    return Path(local_appdata) / "Smithbox" / "Projects"


def drive_path(p: object, *, posix_ok: bool | None = None) -> bool:
    """An absolute drive path (X:\\...), no network share, device path or NUL. Off Windows (posix_ok, for the
    portable backend and the tests) an absolute POSIX path also counts."""
    if posix_ok is None:
        posix_ok = os.name != "nt"
    if not isinstance(p, str) or not p or len(p) > PATH_MAX or "\x00" in p or _CONTROL_RX.search(p):
        return False
    if p.startswith(("\\\\", "//", "\\/", "/\\")):
        return False
    if _DRIVE_RX.match(p):
        return True
    return bool(posix_ok and p.startswith("/"))


def _not_recognised(n: int, reason: str | None = None) -> Own:
    text = "Smithbox's project record is in a form this DataPiler does not recognise (%s file%s)" % (
        logbook.n(n), "" if n == 1 else "s")
    return own(text + (" - " + reason if reason else ""))


def _parse(data: bytes) -> object:
    return json.loads(data.decode("utf-8-sig"))


def _lead(doc: object, posix_ok: bool | None) -> tuple[str, ProjectLead | None]:
    """("lead", lead) for an Elden Ring record, ("other", None) for another game's, ("bad", None) otherwise."""
    if not isinstance(doc, dict):
        return "bad", None
    name, project, data, kind = (doc.get(k) for k in ("ProjectName", "ProjectPath", "DataPath", "ProjectType"))
    auto = doc.get("AutoSelect", False)
    if not (isinstance(name, str) and isinstance(project, str) and isinstance(data, str)):
        return "bad", None
    if isinstance(kind, bool) or not (isinstance(kind, int) or isinstance(kind, str)):
        return "bad", None
    if not isinstance(auto, bool):
        return "bad", None
    if kind not in ER_TYPES:
        return ("other", None) if isinstance(kind, int) or re.fullmatch(r"[A-Za-z0-9]{1,16}", kind) else ("bad", None)
    if not (drive_path(project, posix_ok=posix_ok) and drive_path(data, posix_ok=posix_ok)):
        return "bad", None
    shown = _CONTROL_RX.sub(" ", name).strip()[:NAME_MAX]
    return "lead", ProjectLead(shown, project, data, auto)


def read(local_appdata: str | None, *, pause: Callable[[float], None] = time.sleep,
         posix_ok: bool | None = None) -> Record:
    """Its §6, Reading: only *.json directly in the folder, at most 64 files of 1 MiB (past either cap, none read);
    read-only, UTF-8 with or without a BOM, one re-read after 0.5 s of a file that does not parse; the five keys
    checked by type, every other key dropped at once; each path an absolute drive path (no share, device path or NUL).
    Never an exception, a pattern search, a fallback to other keys or to project.json, a write, a lock or a rename,
    and never a read of Configuration.json."""
    try:
        return _read(local_appdata, pause, posix_ok)
    except Exception as e:          # never an exception out of here: the format is then not recognised
        _log.warn("Smithbox's %s could not be read: %s", own("project record"), logbook.why(e))
        return Record(False, (), 0, 0, NOT_FOUND)


def _json_files(folder: Path) -> list[Path]:
    out = []
    with os.scandir(folder) as it:
        for entry in it:
            if entry.name.lower().endswith(".json"):
                try:
                    if entry.is_file():
                        out.append(Path(entry.path))
                except OSError:
                    continue
    return sorted(out, key=lambda p: p.name.casefold())


def _read(local_appdata: str | None, pause: Callable[[float], None], posix_ok: bool | None) -> Record:
    folder = projects_folder(local_appdata)
    if folder is None:
        return Record(False, (), 0, 0, NOT_FOUND)
    try:
        if not folder.is_dir():
            return Record(False, (), 0, 0, NOT_FOUND)
        files = _json_files(folder)
    except OSError as e:
        _log.warn("Smithbox's %s could not be read: %s", own("project record"), logbook.why(e))
        return Record(False, (), 0, 0, NOT_FOUND)
    if not files:
        return Record(True, (), 0, 0, NOT_FOUND)
    if len(files) > FILES_MAX:
        return Record(True, (), 0, len(files), _not_recognised(len(files), "more than %d files" % FILES_MAX))
    datas: dict[Path, bytes | None] = {}
    for f in files:
        try:
            datas[f] = fileio.read_limited(f, FILE_MAX)
        except fileio.TooLarge:
            return Record(True, (), 0, len(files), _not_recognised(len(files), "a file is over 1 MiB"))
        except OSError:
            datas[f] = None
    docs: dict[Path, object] = {}
    retry: list[Path] = []
    for f, data in datas.items():
        try:
            if data is None:
                raise ValueError("unread")
            docs[f] = _parse(data)
        except (ValueError, UnicodeDecodeError, RecursionError):
            retry.append(f)
    if retry:
        pause(RETRY_SECS)               # a write may be under way: Smithbox's writes are not atomic (its §3)
        for f in retry:
            try:
                docs[f] = _parse(fileio.read_limited(f, FILE_MAX))
            except (OSError, fileio.TooLarge, ValueError, UnicodeDecodeError, RecursionError):
                docs[f] = None
    leads: list[ProjectLead] = []
    other = bad = 0
    for f in files:
        kind, lead = _lead(docs.get(f), posix_ok)
        docs[f] = None                  # the rest of the object dropped at once
        if kind == "lead" and lead is not None:
            leads.append(lead)
        elif kind == "other":
            other += 1
        else:
            bad += 1
    why = None
    if not leads and not other:
        why = _not_recognised(bad)
    return Record(True, tuple(leads), other, bad, why)


# ---------------------------------------------------------------------------------------------------------- cache

_cache_lock = threading.Lock()
_cache: dict[str, tuple[tuple, Record]] = {}


def _fingerprint(folder: Path) -> tuple | None:
    try:
        if not folder.is_dir():
            return None
        out = []
        with os.scandir(folder) as it:
            for entry in it:
                if entry.name.lower().endswith(".json"):
                    try:
                        st = entry.stat()
                    except OSError:
                        continue
                    out.append((entry.name, st.st_size, st.st_mtime_ns))
        return tuple(sorted(out))
    except OSError:
        return None


def cached(local_appdata: str | None) -> Record:
    """read(), kept while the folder's file names, sizes and mtimes stay as they were."""
    folder = projects_folder(local_appdata)
    if folder is None:
        return Record(False, (), 0, 0, NOT_FOUND)
    fp = _fingerprint(folder)
    k = str(folder)
    with _cache_lock:
        hit = _cache.get(k)
        if hit is not None and fp is not None and hit[0] == fp:
            return hit[1]
    rec = read(local_appdata)
    if fp is not None:
        with _cache_lock:
            _cache[k] = (fp, rec)
    return rec


def forget() -> None:
    """For tests: the cache emptied."""
    with _cache_lock:
        _cache.clear()
