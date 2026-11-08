"""Smithbox's folder, exes, builds, its running process, the server's switch read from Startup.json, and the project
its record marks to open (build plan §4.3; build plan 0.2 §5.3; DP13, DP15).

Read only: no Smithbox file is ever written. Startup.json is at <Local AppData>\\Smithbox\\Configuration\\Startup.json
(EldenNet's ER08 §3.1); the server starts only while System_Enable_Soapstone_Server is true.

Smithbox is recognised by any exe named Smithbox*.exe, in any case (fact on the owner's PC, 2026-11-08: Smithbox 2.2.6
runs as Smithbox.Vulkan.exe, and the same folder holds Smithbox.OpenGL.exe; Smithbox.exe is a lead only). A folder
with two such exes is the normal case: the folder check passes with either, the build is read from the running one,
or from either when none runs (both reported when they differ).

DP15: a watcher sees a running Smithbox from DataPiler's start, every 2 s, whatever the Settings say. The folder it
runs from goes to the local page only, never to a log line."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import fileio, logbook, winapi
from .logbook import Own, own

SWITCH_KEY = "System_Enable_Soapstone_Server"
EXE_RX = re.compile(r"smithbox[A-Za-z0-9._ ()-]{0,48}\.exe", re.IGNORECASE)   # Smithbox*.exe, any case
# The fixed names the picker's mark checks for (an existence check, never a listing of a folder's files: build plan
# 0.2 §5.5 and §8). Smithbox.Vulkan.exe and Smithbox.OpenGL.exe are facts on the owner's PC; Smithbox.exe is a lead.
KNOWN_EXES = ("Smithbox.Vulkan.exe", "Smithbox.OpenGL.exe", "Smithbox.exe")
EXE_NAME = "Smithbox.exe"                  # 0.1's name: kept for what imports it; recognition is EXE_RX
EXE_TEXT = "Smithbox*.exe"
STARTUP_MAX = 1024 * 1024
EXES_MAX = 16                              # the folder's Smithbox exes looked at, at most
WATCH_SECS = 2.0

_lock = threading.Lock()
_build_cache: dict[str, tuple[tuple[int, int], str | None]] = {}
_log = logbook.get("smithbox")


def is_exe_name(name: object) -> bool:
    """An exe Smithbox runs as: Smithbox*.exe in any case, of plain characters."""
    return isinstance(name, str) and bool(EXE_RX.fullmatch(name))


def startup_json() -> Path | None:
    """<Local AppData>\\Smithbox\\Configuration\\Startup.json (ER08 §3.1): the known folder from the Windows adapter,
    else the LOCALAPPDATA variable; None without either."""
    try:
        base = winapi.backend().local_appdata()
    except Exception:
        base = None
    base = base or os.environ.get("LOCALAPPDATA")
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


# ---------------------------------------------------------------------------------------------------------- exes


def _order(name: str) -> tuple[int, str]:
    low = name.lower()
    known = [k.lower() for k in KNOWN_EXES]
    return (known.index(low) if low in known else len(known), low)


def exes(smithbox_dir: str) -> list[Path]:
    """The Smithbox exes in the folder (Smithbox*.exe, any case), the known names first. Empty when none or unset."""
    if not smithbox_dir:
        return []
    out: list[Path] = []
    try:
        with os.scandir(smithbox_dir) as it:
            for entry in it:
                if not is_exe_name(entry.name):
                    continue
                try:
                    if entry.is_file():
                        out.append(Path(entry.path))
                except OSError:
                    continue
                if len(out) >= EXES_MAX:
                    break
    except OSError:
        return []
    return sorted(out, key=lambda p: _order(p.name))


def exe_path(smithbox_dir: str) -> Path | None:
    """The first of exes(): the running one's folder decides which build is read (build())."""
    found = exes(smithbox_dir)
    return found[0] if found else None


def installed(smithbox_dir: str) -> bool:
    return bool(exes(smithbox_dir))


def file_build(exe: Path | str) -> str | None:
    """An exe's version resource, cached by its size and mtime."""
    exe = Path(exe)
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


@dataclass(frozen=True)
class ExeReport:
    name: str               # the exe's own name, e.g. "Smithbox.Vulkan.exe"
    build: str | None
    running: bool


def _same(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (OSError, ValueError):
        return False


def reports(smithbox_dir: str) -> list[ExeReport]:
    """Each Smithbox exe in the folder with its build, and whether a process runs from it."""
    found = exes(smithbox_dir)
    if not found:
        return []
    runs = seen() or ()
    out = []
    for exe in found:
        running = any(_same(r.path, str(exe)) for r in runs)
        out.append(ExeReport(exe.name, file_build(exe), running))
    return out


def build(smithbox_dir: str) -> str | None:
    """The build of the exe running from the folder; with none running, the build the folder's exes share. None when
    no exe is there, no version resource could be read, or the exes' builds differ and none runs (which one is in
    use is then not known)."""
    rs = reports(smithbox_dir)
    for r in rs:
        if r.running and r.build:
            return r.build
    builds = {r.build for r in rs if r.build}
    return builds.pop() if len(builds) == 1 else None


def builds_differ(smithbox_dir: str) -> bool:
    rs = reports(smithbox_dir)
    return len({r.build for r in rs if r.build}) > 1 and not any(r.running for r in rs)


# ---------------------------------------------------------------------------------------------------------- running


@dataclass(frozen=True)
class Running:
    name: str               # the exe's name (from its path when readable), e.g. "Smithbox.Vulkan.exe"
    path: str | None        # its full image path (QueryFullProcessImageNameW): the local page only, never a log line
    folder: str | None
    build: str | None


def running_now() -> list[Running] | None:
    """The Smithbox processes running now, by their exe's name; None when the process list cannot be read."""
    try:
        procs = winapi.backend().processes()
    except Exception:
        return None
    out: list[Running] = []
    for p in procs:
        base = os.path.basename(p.path) if p.path else ""
        name = base if is_exe_name(base) else (p.name or "")
        if not is_exe_name(name):
            continue
        folder = os.path.dirname(p.path) if p.path else None
        out.append(Running(name, p.path, folder or None, file_build(p.path) if p.path else None))
    out.sort(key=lambda r: (_order(r.name), r.path or ""))
    return out


def running(smithbox_dir: str = "") -> bool | None:
    """Whether a Smithbox process runs (any Smithbox*.exe, whatever the folder); None when the process list cannot be
    read."""
    r = seen()
    if r is None:
        return None
    return bool(r)


def _safe_names(rs: list[Running]) -> Own:
    names = []
    for r in rs:
        n = r.name if is_exe_name(r.name) else "a Smithbox exe"
        if n not in names:
            names.append(n)
    return own(", ".join(names))


class Watch:
    """DP15: a daemon thread reads the process list every interval and keeps what it saw; on_change(list) is called
    from its thread when the set of Smithbox processes changes. A log line names the event, never the path."""

    def __init__(self, interval: float = WATCH_SECS, on_change: Callable[[list[Running]], None] | None = None,
                 read: Callable[[], list[Running] | None] = running_now):
        self._interval = max(0.01, float(interval))
        self._on_change = on_change
        self._read = read
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: list[Running] | None = None
        self._checked = False

    def seen(self) -> list[Running] | None:
        """The last reading: the processes, or None when the list could not be read (or before the first check)."""
        with self._lock:
            return list(self._seen) if self._seen is not None else None

    @property
    def checked(self) -> bool:
        with self._lock:
            return self._checked

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._loop, args=(self._stop,), name="datapiler-smithboxwatch",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            t = self._thread
            self._thread = None
        if t is not None and t is not threading.current_thread():
            t.join(self._interval + 5.0)

    def check_once(self) -> bool:
        """One reading; True when the set of processes changed (and on_change was called). The folders Smithbox runs
        from are taught to the mask before any page can draw them."""
        try:
            now = self._read()
        except Exception:
            now = None
        learn(now)
        with self._lock:
            before = self._seen
            first = not self._checked
            self._seen = now
            self._checked = True
        key = (lambda rs: None if rs is None else sorted((r.name.lower(), (r.path or "").lower()) for r in rs))
        if key(before) == key(now) and not first:
            return False
        if now is None:
            if before is not None or first:
                _log.warn("the process list could not be read, so whether Smithbox runs is not known")
        elif now:
            if len(now) == 1:
                _log.info("Smithbox is running (%s)", _safe_names(now))
            else:
                _log.info("Smithbox is running: %s processes (%s)", len(now), _safe_names(now))
        elif before:
            _log.info("Smithbox stopped")
        if self._on_change is not None and now is not None:
            try:
                self._on_change(list(now))
            except Exception as e:
                _log.error("the Smithbox watcher's handler failed: %s", logbook.why(e))
        return True

    def _loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.check_once()
            if stop.wait(self._interval):
                break


_watch_lock = threading.Lock()
_watch: Watch | None = None


def start_watch(on_change: Callable[[list[Running]], None] | None = None, interval: float = WATCH_SECS) -> Watch:
    """Starts the one watcher (a second call returns it, with its handler replaced when one is given)."""
    global _watch
    with _watch_lock:
        if _watch is None:
            _watch = Watch(interval, on_change)
        elif on_change is not None:
            _watch._on_change = on_change
        w = _watch
    w.start()
    return w


def stop_watch() -> None:
    global _watch
    with _watch_lock:
        w, _watch = _watch, None
    if w is not None:
        w.stop()


def seen() -> list[Running] | None:
    """The watcher's last reading while it runs and has read once; else the process list read now (its folders taught
    to the mask)."""
    with _watch_lock:
        w = _watch
    if w is not None and w.checked:
        return w.seen()
    now = running_now()
    learn(now)
    return now


def learn(rs: list[Running] | None) -> None:
    """The folders Smithbox runs from, added to this session's mask as <FOUND> (logbook.learn_found), so with Mask
    paths on, Status and Settings draw them masked even when Detect has not run (the reviews' SEC-3 and C4)."""
    if rs:
        logbook.learn_found([r.folder for r in rs if r.folder])


# ---------------------------------------------------------------------------------------------------------- project


def open_project() -> str | None:
    """The project folder of the one Elden Ring record Smithbox's record marks to open (AutoSelect), or None: none
    or two marked, no record, or a form not recognised (build plan 0.2 §5.3). A lead (O48): it informs Status only."""
    from . import sbproject
    try:
        local = winapi.backend().local_appdata()
    except Exception:
        return None
    lead = sbproject.cached(local).open_lead()
    return lead.project_dir if lead is not None else None
