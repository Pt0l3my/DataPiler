"""The guided-export import from `workspace/inbox/` (design 0001 §2 and §7.6, settled S10, build plan §4.9).

The owner exports a text container from Smithbox's Text Editor into the inbox; DataPiler takes each `.json` once its
size has held still for one poll, checks by its shape alone that it is Smithbox's text export of a container DataPiler
waits for, in Settings' language (S10: never by its file name), imports it into the text database and moves it to
`workspace/imported/` under DataPiler's own name. Anything else stays in the inbox with its reason, shown on the page
only: file names in the inbox are the owner's and never reach a log line."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Collection

from . import events, fileio, logbook, paths as paths_mod
from .logbook import own
from .textdb import TextDB

# The keys of a text export that name its language, if Smithbox writes one (build plan §10, P3: not established).
# Until one is confirmed, the language is Settings' and the guided steps say to export in it.
LANGUAGE_KEYS: tuple[str, ...] = ()

CONTAINER_RX = re.compile(r"[a-z0-9][a-z0-9_]{0,31}")
LANGUAGE_RX = re.compile(r"[a-z]{2,8}")

_log = logbook.get("textdb")


class NotAnExport(ValueError):
    """str(e) is the reason the page shows: "not a Smithbox text export", "not a Smithbox text export of `item`",
    "a text export in another language than Settings' (engus)"."""


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _shape_ok(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("Name"), str):
        return False
    if "SourceContainer" in data and data["SourceContainer"] is not None and \
            not isinstance(data["SourceContainer"], str):
        return False
    wrappers = data.get("FmgWrappers")
    if not isinstance(wrappers, list):
        return False
    for w in wrappers:
        if not isinstance(w, dict) or not _is_int(w.get("ID")) or not isinstance(w.get("Name"), str):
            return False
        fmg = w.get("Fmg")
        if not isinstance(fmg, dict) or not isinstance(fmg.get("Entries"), list):
            return False
        for e in fmg["Entries"]:
            if not isinstance(e, dict) or not _is_int(e.get("ID")):
                return False
            if e.get("Text") is not None and not isinstance(e.get("Text"), str):
                return False
    return True


def _of(expected: list[str]) -> str:
    quoted = ["`%s`" % c for c in expected]
    if len(quoted) <= 1:
        return "".join(quoted)
    return ", ".join(quoted[:-1]) + " or " + quoted[-1]


def check_export(data: object, *, expected: Collection[str], language: str) -> tuple[str, str]:
    """(container, language) by shape alone (S10), never by file name. Raises NotAnExport."""
    if not _shape_ok(data):
        raise NotAnExport("not a Smithbox text export")
    assert isinstance(data, dict)
    want = sorted(c for c in expected if isinstance(c, str) and CONTAINER_RX.fullmatch(c))
    source = data.get("SourceContainer")
    container = source if isinstance(source, str) and source else data["Name"]
    found = container.lower() if isinstance(container, str) else ""
    if found not in want:
        raise NotAnExport("not a Smithbox text export of %s" % _of(want) if want else
                          "a Smithbox text export, but DataPiler waits for no text container")
    lang = language if isinstance(language, str) and LANGUAGE_RX.fullmatch(language) else ""
    if not lang:
        raise NotAnExport("Settings' language is not a language code DataPiler knows")
    for key in LANGUAGE_KEYS:
        v = data.get(key)
        if v is not None and (not isinstance(v, str) or v.casefold() != lang):
            raise NotAnExport("a text export in another language than Settings' (%s)" % lang)
    return found, lang


class Inbox:
    MAX_BYTES = 64 * 1024 * 1024

    def __init__(self, paths: "paths_mod.Paths | Callable[[], paths_mod.Paths]", textdb: TextDB,
                 language: Callable[[], str], expected: Callable[[], set[str]]):
        """paths: the Paths, or a callable giving the current ones (Settings can move the workspace)."""
        self._paths = paths
        self.textdb = textdb
        self.language = language
        self.expected = expected
        self._lock = threading.Lock()
        self._seen: dict[str, tuple[int, int]] = {}            # name -> (size, mtime_ns) at the last poll
        self._left: dict[str, tuple[tuple[int, int], str]] = {}  # name -> (that stat, the reason)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._unsub = events.subscribe("app.stopping", lambda topic, data: self._stop.set())

    @property
    def paths(self) -> "paths_mod.Paths":
        p = self._paths
        return p() if callable(p) else p

    def start(self) -> None:
        """A daemon thread, every second."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="datapiler-inbox", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=3.0)
        self._unsub()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as e:
                _log.error("the inbox could not be read: %s", logbook.why(e))
            self._stop.wait(1.0)

    def _listing(self, inbox: Path) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        try:
            entries = list(os.scandir(inbox))
        except FileNotFoundError:
            return out
        for e in entries:
            try:
                if not e.is_file(follow_symlinks=False):
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            out[e.name] = (int(st.st_size), int(st.st_mtime_ns))
        return out

    def poll_once(self) -> list[dict]:
        """Take each .json in the inbox whose size has not changed since the last poll; import it and move it to
        imported/ under DataPiler's own name, or leave it with its reason. For tests and the thread. Returns what
        happened to each file this poll: [{"file", "ok", "container", "entries", "reason"}] (page and tests only)."""
        p = self.paths
        listing = self._listing(p.inbox)
        done: list[dict] = []
        with self._lock:
            for name in list(self._seen):
                if name not in listing:
                    self._seen.pop(name, None)
            for name in list(self._left):
                if name not in listing:
                    self._left.pop(name, None)
            ready: list[str] = []
            for name, stat in sorted(listing.items()):
                left = self._left.get(name)
                if left is not None and left[0] == stat:
                    continue                                   # refused already, unchanged since
                if not name.lower().endswith(".json"):
                    self._left[name] = (stat, "not a .json file - DataPiler takes Smithbox's text exports only")
                    continue
                if self._seen.get(name) == stat:
                    ready.append(name)
                else:
                    self._seen[name] = stat                    # still growing, or new: the next poll takes it
        for name in ready:
            done.append(self._take(p, name, listing[name]))
        return done

    def _refuse(self, name: str, stat: tuple[int, int], reason: str) -> dict:
        with self._lock:
            self._left[name] = (stat, reason)
            self._seen.pop(name, None)
        _log.warn("an inbox file was left in the inbox: %s", own(reason))
        events.emit("inbox.import", container=None, ok=False, entries=0)
        return {"file": name, "ok": False, "container": None, "entries": 0, "reason": reason}

    def _take(self, p: "paths_mod.Paths", name: str, stat: tuple[int, int]) -> dict:
        src = p.inbox / name
        if stat[0] > self.MAX_BYTES:
            return self._refuse(name, stat, "over %d MB - larger than a text export DataPiler takes"
                                % (self.MAX_BYTES // (1024 * 1024)))
        try:
            raw = fileio.read_limited(src, self.MAX_BYTES)
        except fileio.TooLarge:
            return self._refuse(name, stat, "over %d MB - larger than a text export DataPiler takes"
                                % (self.MAX_BYTES // (1024 * 1024)))
        except OSError as e:
            _log.warn("an inbox file could not be read: %s", logbook.why(e))
            with self._lock:
                self._seen.pop(name, None)
            return {"file": name, "ok": False, "container": None, "entries": 0, "reason": "could not be read"}
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return self._refuse(name, stat, "not a Smithbox text export")
        try:
            container, language = check_export(data, expected=set(self.expected() or ()), language=self.language())
        except NotAnExport as e:
            return self._refuse(name, stat, str(e))
        sha = fileio.sha256_bytes(raw)
        try:
            result = self.textdb.import_export(data, container=container, language=language, sha256=sha)
        except Exception as e:
            _log.error("an export of %s could not be imported: %s", own(container), logbook.why(e))
            return self._refuse(name, stat, "could not be imported - see the Terminal tab")
        dest = self._dest(p, container, language)
        try:
            p.imported.mkdir(parents=True, exist_ok=True)
            os.replace(src, dest)
        except OSError as e:
            _log.warn("an imported export could not be moved to imported/: %s", logbook.why(e))
        with self._lock:
            self._seen.pop(name, None)
            self._left.pop(name, None)
        _log.info("imported %s (%s): %s wrappers, %s entries", own(container), own(language),
                  logbook.n(result.wrappers), logbook.n(result.entries))
        events.emit("inbox.import", container=own(container), ok=True, entries=result.entries)
        return {"file": name, "ok": True, "container": container, "entries": result.entries, "reason": None,
                "moved_to": dest.name}

    @staticmethod
    def _dest(p: "paths_mod.Paths", container: str, language: str) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = "%s-%s-%s" % (stamp, container, language)
        for k in range(1, 1000):
            stem = base if k == 1 else "%s-%d" % (base, k)
            if paths_mod.NAME_RX.fullmatch(stem) and not (p.imported / (stem + ".json")).exists():
                return p.imported / (stem + ".json")
        return p.imported / (base + "-%d.json" % int(time.time() * 1000))

    def state(self) -> list[dict]:
        """[{"file": name, "reason": ...}]: the files left in the inbox, for the page only (never logged)."""
        with self._lock:
            return [{"file": name, "reason": reason} for name, (_, reason) in sorted(self._left.items())]
