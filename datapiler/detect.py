"""Detect: where Smithbox, the game, the project and the expansion are, from what this PC already records (build plan
0.2 §5.4; design 0002 §3.4; DP13, DP15).

All local and read only: the running processes, Smithbox's record of its projects, Steam's registry values and files,
and the folders used here before. Nothing walks a drive. Candidates and names live in memory for the session only,
each folder goes to the log's mask as <FOUND> as it is found, and a log line names the folder, the counts and the
sources, never a path or a name. Nothing is saved: the owner presses Use, Choose or Save.

The sources, in order (DP13): Smithbox from its running process (QueryFullProcessImageNameW, through the Windows
adapter), then the folders used before; the project and game folders from Smithbox's record of the open project
(sbproject), Steam's library list and its uninstall entry and the running game as further game sources and the
cross-check; the expansion from the game's app manifest (its dlcappid values, never a built-in id). Everything from
Smithbox's record is a lead (O48)."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from . import dirs, game as game_mod, logbook, sbproject, smithbox, steam, winapi
from .logbook import Own, own

WANTS = ("smithbox", "game", "project", "expansion")
KEYS = {"smithbox": "smithbox_dir", "game": "game_dir", "project": "project_dir", "expansion": "expansion"}
TAGS = {"running_smithbox": "the running Smithbox", "smithbox_record": "Smithbox's project record",
        "steam_library": "Steam's library list", "steam_uninstall": "Windows' uninstall entry",
        "running_game": "the running game", "steam_manifest": "Steam's app manifest", "recent": "used here before"}
SOURCE_ORDER = tuple(TAGS)
# Every registry value Detect reads, and nothing else (S33; test_detect holds every call to this table).
REGISTRY = {
    "steam_user":   ("HKCU", r"Software\Valve\Steam", "SteamPath"),
    "steam_system": ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    "uninstall":    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 1245620",
                     "InstallLocation"),
    "uninstall_32": ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 1245620",
                     "InstallLocation"),
}

NOT_RUNNING = ("Smithbox is not running, so its folder cannot be read - start Smithbox, then Detect again")
SET_FOLDER = " - choose the folder with Set folder…"
DIFFER = ("Smithbox's project record and Steam name different game folders - use the one your project is for")
NO_STEAM_LIST = "Steam's library list could not be read"
NO_MANIFEST = "Steam's app manifest for the game was not found, so whether the expansion is installed is not known"
MARKED = "marked to open"
AGREES = "Steam's library list agrees"

_log = logbook.get("folders")


@dataclass(frozen=True)
class Candidate:
    value: str                   # a folder (resolved), or "yes"/"no" for the expansion
    sources: tuple[str, ...]     # ids of TAGS, in the order above
    name: str | None             # the record's ProjectName (page only, never logged, not sent with the mask on)
    marked: bool                 # from the record's one marked Elden Ring project: the tag adds "marked to open"
    detail: Own | None           # the expansion's "DLC app 2778580 installed", or None


def norm(path: str) -> str:
    """For merging: case-folded, either slash, no trailing separator."""
    return path.replace("/", "\\").rstrip("\\").casefold()


def _resolve(path: str) -> str:
    """A candidate's folder as Use saves it (dirs.resolved: links resolved, a mapped drive kept as a drive)."""
    try:
        if os.path.isdir(path):
            return dirs.resolved(str(Path(path).absolute()))
    except (OSError, RuntimeError, ValueError):
        pass
    return os.path.normpath(path) if path else path


def merge(raw: list[Candidate]) -> list[Candidate]:
    """Candidates from several sources merged by folder (or value), keeping every source in SOURCE_ORDER; the first
    name and detail kept, marked if any source marks it."""
    out: dict[str, Candidate] = {}
    for c in raw:
        k = norm(c.value)
        old = out.get(k)
        if old is None:
            out[k] = c
            continue
        sources = tuple(s for s in SOURCE_ORDER if s in old.sources or s in c.sources)
        out[k] = replace(old, sources=sources, name=old.name or c.name, marked=old.marked or c.marked,
                         detail=old.detail or c.detail)
    return [replace(c, sources=tuple(s for s in SOURCE_ORDER if s in c.sources)) for c in out.values()]


def tags(c: Candidate) -> list[str]:
    """The page's words for a candidate's sources."""
    out = []
    for s in c.sources:
        if s == "smithbox_record" and c.marked:
            out.append(TAGS[s] + ", " + MARKED)
        elif s == "steam_library" and "smithbox_record" in c.sources:
            out.append(AGREES)
        else:
            out.append(TAGS[s])
    return out


def _count(k: int, one: str, many: str) -> Own:
    """1 -> "1 place", 2 -> "2 places": the log's words, the count only."""
    return own("%s %s" % (logbook.n(k), one if k == 1 else many))


def _sources_text(cands: list[Candidate]) -> Own:
    used = [s for s in SOURCE_ORDER if any(s in c.sources for c in cands)]
    return own(", ".join(TAGS[s] for s in used) if used else "none")


class Folders:
    """The session's Detect. Nothing runs at construction; at_start() starts the Smithbox watcher (DP15) and, on a
    daemon thread, Detect for each folder whose setting is blank or no longer a folder."""

    def __init__(self, live) -> None:
        self.live = live
        self._lock = threading.Lock()
        self._found: dict[str, list[Candidate]] = {}
        self._notes: dict[str, list[str]] = {}
        self._threads: list[threading.Thread] = []
        self._closed = threading.Event()
        self._watching = False
        self._smithbox_was: bool | None = None

    # ------------------------------------------------------------------------------------------------ start, stop

    def at_start(self) -> None:
        """Detect for each folder whose setting is blank or no longer a folder, and for the expansion while it is not
        stated, on a daemon thread; and the Smithbox watcher. Nothing saved."""
        if self._closed.is_set():
            return
        smithbox.start_watch(self._smithbox_changed)
        self._watching = True
        self._spawn(self._missing())

    def _missing(self) -> list[str]:
        s = self.live.settings
        out = []
        for want in ("smithbox", "game", "project"):
            v = getattr(s, KEYS[want])
            try:
                ok = bool(v) and os.path.isdir(v)
            except (OSError, ValueError):
                ok = False
            if not ok:
                out.append(want)
        if s.expansion not in ("yes", "no"):
            out.append("expansion")
        return out

    def _spawn(self, wants: list[str]) -> None:
        if not wants or self._closed.is_set():
            return

        def run() -> None:
            for w in wants:
                if self._closed.is_set():
                    return
                try:
                    self.detect(w)
                except Exception as e:
                    _log.error("Detect failed for the %s folder: %s", own(w), logbook.why(e))

        t = threading.Thread(target=run, name="datapiler-detect", daemon=True)
        with self._lock:
            self._threads = [x for x in self._threads if x.is_alive()] + [t]
        t.start()

    def _smithbox_changed(self, now: list) -> None:
        """DP15: once Smithbox is seen, Detect goes on to the project and game folders still blank or missing."""
        running = bool(now)
        was, self._smithbox_was = self._smithbox_was, running
        if was is None:
            return                  # the first reading: at_start's own Detect covers what is missing
        if running and not was:
            self._spawn([w for w in self._missing() if w in ("game", "project")])

    def close(self) -> None:
        self._closed.set()
        if self._watching:
            smithbox.stop_watch()
            self._watching = False
        with self._lock:
            threads, self._threads = self._threads, []
        for t in threads:
            if t is not threading.current_thread():
                t.join(5.0)

    def wait(self, timeout: float = 5.0) -> None:
        """For tests: the start's Detect threads ended."""
        with self._lock:
            threads = list(self._threads)
        for t in threads:
            t.join(timeout)

    # ------------------------------------------------------------------------------------------------ reads

    def found(self, want: str) -> list[Candidate]:
        """The candidates the last Detect kept for the session; for Smithbox, its running processes as they are now
        (DP15), whether Detect was pressed or not."""
        if want not in WANTS:
            raise ValueError("not something Detect finds")
        with self._lock:
            kept = list(self._found.get(want, []))
        if want != "smithbox":
            return kept
        stored = [replace(c, sources=tuple(s for s in c.sources if s != "running_smithbox")) for c in kept]
        stored = [c for c in stored if c.sources]
        return merge(self._running_smithbox() + stored)

    def notes(self, want: str) -> list[str]:
        with self._lock:
            return list(self._notes.get(want, []))

    def detect(self, want: str) -> list[Candidate]:
        """Every source of want, in order; the candidates kept in memory for the session and learnt by the mask; the
        log names the folder, the counts and the sources. Returns them merged."""
        if want not in WANTS:
            raise ValueError("not something Detect finds")
        notes: list[str] = []
        if want == "smithbox":
            cands = self._smithbox(notes)
        elif want == "game":
            cands = self._game(notes)
        elif want == "project":
            cands = self._project(notes)
        else:
            cands = self._expansion(notes)
        with self._lock:
            self._found[want] = cands
            self._notes[want] = notes
        return cands

    # ------------------------------------------------------------------------------------------------ sources

    def _learn(self, folders: list[str]) -> None:
        logbook.learn_found([f for f in folders if f])

    def _recent(self, key: str) -> list[Candidate]:
        rec = self.live.settings.recent.get(key, ())
        return [Candidate(_resolve(f), ("recent",), None, False, None) for f in rec if f]

    def _running_smithbox(self) -> list[Candidate]:
        out = []
        for r in smithbox.seen() or []:
            if r.folder:
                out.append(Candidate(_resolve(r.folder), ("running_smithbox",), None, False, None))
        self._learn([c.value for c in out])
        return [c for c in merge(out) if smithbox.installed(c.value)]

    def _smithbox(self, notes: list[str]) -> list[Candidate]:
        running = smithbox.seen()
        raw = []
        for r in running or []:
            if r.folder:
                raw.append(Candidate(_resolve(r.folder), ("running_smithbox",), None, False, None))
        raw += self._recent("smithbox_dir")
        self._learn([c.value for c in raw])
        cands = [c for c in merge(raw) if smithbox.installed(c.value)]
        if not running:
            notes.append(NOT_RUNNING)
        _log.info("Smithbox folder: %s (%s)", _count(len(cands), "place", "places"), _sources_text(cands))
        return cands

    def _record(self) -> sbproject.Record:
        try:
            local = winapi.backend().local_appdata()
        except Exception:
            local = None
        return sbproject.cached(local)

    def _project(self, notes: list[str]) -> list[Candidate]:
        rec = self._record()
        lead = rec.open_lead()
        raw = [Candidate(_resolve(x.project_dir), ("smithbox_record",), x.name, x is lead, None) for x in rec.leads]
        raw += self._recent("project_dir")
        self._learn([c.value for c in raw])
        cands = merge(raw)
        self._record_notes(rec, notes)
        _log.info("project: %s from Smithbox's project record, %s open, %s for another game, %s not recognised",
                  _count(len(rec.leads), "place", "places"), 1 if lead is not None else 0, rec.other_games,
                  rec.unrecognised)
        return cands

    @staticmethod
    def _record_notes(rec: sbproject.Record, notes: list[str]) -> None:
        if rec.why is not None:
            notes.append(str(rec.why) + SET_FOLDER)
        elif rec.leads and rec.unrecognised:
            notes.append("%s more file%s not recognised" % (logbook.n(rec.unrecognised),
                                                             "" if rec.unrecognised == 1 else "s"))

    def _steam_dir(self) -> str | None:
        b = winapi.backend()
        for name in ("steam_user", "steam_system"):
            try:
                v = b.registry_value(*REGISTRY[name])
            except Exception:
                v = None
            if isinstance(v, str) and v.strip() and dirs.full(v.strip()):
                return os.path.normpath(v.strip())
        return None

    def _manifests(self, notes: list[str] | None) -> list[tuple[str, steam.AppManifest]]:
        """(library, manifest) for the game, from the library whose apps hold GAME_APP_ID, else every library."""
        sd = self._steam_dir()
        if not sd:
            return []
        try:
            libs = steam.libraries(sd)
        except steam.VdfError:
            if notes is not None:
                notes.append(NO_STEAM_LIST)
            libs = [steam.Library(sd, None)]
        holding = [x for x in libs if x.apps is not None and steam.GAME_APP_ID in x.apps]
        out = []
        for lib in holding or libs:
            m = steam.app_manifest(lib.path, steam.GAME_APP_ID)
            if m is not None:
                out.append((lib.path, m))
        return out

    def _game(self, notes: list[str]) -> list[Candidate]:
        rec = self._record()
        lead = rec.open_lead()
        raw = [Candidate(_resolve(x.data_dir), ("smithbox_record",), x.name, x is lead, None) for x in rec.leads]
        steam_raw = []
        for lib, m in self._manifests(notes):
            if m.installdir:
                steam_raw.append(Candidate(_resolve(steam.game_folder(lib, m.installdir)), ("steam_library",), None,
                                           False, None))
        b = winapi.backend()
        for name in ("uninstall", "uninstall_32"):
            try:
                v = b.registry_value(*REGISTRY[name])
            except Exception:
                v = None
            if isinstance(v, str) and v.strip() and dirs.full(v.strip()):
                steam_raw.append(Candidate(_resolve(os.path.join(os.path.normpath(v.strip()), "Game")),
                                           ("steam_uninstall",), None, False, None))
        running = []
        try:
            procs = b.processes()
        except Exception:
            procs = []
        for p in procs:
            if (p.name or "").lower() == game_mod.EXE and p.path:
                running.append(Candidate(_resolve(os.path.dirname(p.path)), ("running_game",), None, False, None))
        raw += steam_raw + running + self._recent("game_dir")
        self._learn([c.value for c in raw])
        cands = [c for c in merge(raw) if game_mod.exe_path(c.value) is not None]
        steam_ids = {"steam_library", "steam_uninstall"}
        rec_only = [c for c in cands if "smithbox_record" in c.sources and not steam_ids & set(c.sources)]
        steam_only = [c for c in cands if steam_ids & set(c.sources) and "smithbox_record" not in c.sources]
        if rec_only and steam_only:
            notes.append(DIFFER)        # both listed, neither chosen (DP13's cross-check)
        if not cands:
            self._record_notes(rec, notes)
        _log.info("game folder: %s (%s)", _count(len(cands), "place", "places"), _sources_text(cands))
        return cands

    def _expansion(self, notes: list[str]) -> list[Candidate]:
        raw = []
        manifests = self._manifests(notes)
        for _, m in manifests:
            if m.dlc_app_ids:
                # Any DLC app is not the expansion (the deluxe editions' artbook and soundtrack are DLC apps too), and
                # its id is never assumed (DP13): the ids are shown, and Yes and No are both the owner's to choose
                # (the correctness review's C7).
                ids = ", ".join(str(i) for i in m.dlc_app_ids)
                one = len(m.dlc_app_ids) == 1
                raw.append(Candidate("yes", ("steam_manifest",), None, False, own(
                    ("Steam lists DLC app %s as installed: Yes if it is the expansion" if one else
                     "Steam lists DLC apps %s as installed: Yes if one of them is the expansion") % ids)))
                raw.append(Candidate("no", ("steam_manifest",), None, False, own(
                    "No if it is not" if one else "No if none of them is")))
            else:
                raw.append(Candidate("no", ("steam_manifest",), None, False, own("no DLC app installed")))
        cands = merge(raw)
        if not manifests:
            notes.append(NO_MANIFEST)
        n = max((len(m.dlc_app_ids) for _, m in manifests), default=0)
        _log.info("expansion: Steam's app manifest lists %s installed", _count(n, "DLC app", "DLC apps"))
        return cands


# ---------------------------------------------------------------------------------------------------------- views


def in_use(c: Candidate, current: str) -> bool:
    if not current:
        return False
    if c.value in ("yes", "no"):
        return c.value == current
    return dirs.same_folder(c.value, current)


def view(want: str, c: Candidate, s, root: Path) -> dict:
    """One candidate as the page draws it (build plan 0.2 §6): path and shown (value for the expansion), its source
    ids and tags, whether it is in use, its check line; a record's candidate its marked and, with the mask off, its
    name."""
    mask_on = bool(s.mask_paths)
    current = getattr(s, KEYS[want])
    out: dict = {}
    if want == "expansion":
        out["value"] = c.value
    else:
        out["path"] = c.value
        out["shown"] = dirs.shown(c.value, mask_on)
    out["sources"] = list(c.sources)
    out["tags"] = tags(c)
    out["in_use"] = in_use(c, current)
    if c.detail is not None:
        out["detail"] = str(c.detail)
    if want != "expansion":
        out["check"] = dirs.check(want, c.value, s, root).as_dict()
    if "smithbox_record" in c.sources:
        out["marked"] = bool(c.marked)
        if not mask_on and c.name:
            out["name"] = c.name
    return out
