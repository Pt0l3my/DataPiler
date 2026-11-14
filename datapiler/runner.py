"""The queue and the run of jobs and Extract rows (design 0001 §2 and §6, build plan §4.8).

One worker thread runs one thing at a time, jobs and Extract rows in the order they were started; the server rows of
an Extract run go first. Everything is thread-safe behind one lock, which is never held during a server call.

- A job that uses the link waits while the link is off, blocked or without its libraries, says which, and goes on
  when `link.state` turns `on`; an operation cut off by the link going off is run again from its start.
- Cancel stops between calls. A failed job writes no share file and names the operation and the reason; a guard
  failure names the check and the place, never the value.
- The share file goes through `Guard.write` only, after every other operation has passed. The runner hands the guard
  each share table's row counts for check 6 (DP8, settled S19): the game table it came from (a param, or the
  placements), that table's rows (a param's rows as Smithbox lists them; the placements of every map the job read,
  each map once) and what to measure, from the job's lineage; and it keeps them in the workspace
  (`guard.record_counts`) so Outputs can run check 6 again.
- `join_names` uses the names' wrapper leads only once at least half of the rows' non-negative name numbers resolve
  in them (P3, settled S22); the share file's provenance records the share that resolved.
- Each job logs to `logbook.for_job(id)`; Extract rows log to the `extract` source. Log lines hold ids, counts,
  times, operation names and DataPiler's own words: never a title, a refusal's text or a value from a table.

`Runner.add` follows LLM Jobrunner 1.2's `Runner.add` (build plan §7.2): the sha256 on arrival, the file kept as
dropped, the same file again recognised, a refused file becoming a card."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol, Sequence

from . import catalogue, events, fields, fileio, jobs, logbook, paths as paths_mod
from . import link as link_mod
from . import smithbox as smithbox_mod
from .guard import WORDS as GUARD_WORDS, GuardFailed
from .logbook import Own, own

if TYPE_CHECKING:
    from .game import GameRunning
    from .guard import Guard
    from .link import Placement
    from .textdb import TextDB

MAP_QUESTION = 10                   # S8: ask before loading more than ten maps
STATE_FORMAT = "datapiler-jobstate/1"
LOCAL_FORMAT = "datapiler-local/1"
MAPS_FILE = "maps.jsonl"            # S63: a job's placements read so far, map by map, in its own folder
MAPS_FORMAT = "datapiler-mapprogress/1"
MAPS_PER_SESSION = 300              # S63: the most maps a job asks Smithbox to hold at once; then it pauses
MAPS_KEY = ("game_version", "regulation_sha256", "smithbox_build")
MAPS_READY_WAIT = 600.0             # S64: after a switch to the OpenGL build, how long to wait for Smithbox's maps
MAPS_READY_POLL = 2.0
WAIT_POLL = 0.5

LINK_WAITS = {
    "off": "the server link is off",
    "blocked": "the game is running",
    "no_libs": "the server link needs its libraries - restart DataPiler and answer Y",
}
UNITS = {"fetch_rows": "rows", "load_maps": "maps", "read_placements": "maps", "join_names": "rows", "unused_names": "names",
         "filter": "rows", "count": "rows", "distinct": "rows", "write_local": "files", "write_share": "files"}
ACTIVE = ("queued", "waiting", "running")

_extract_log = logbook.get("extract")
_job_log = logbook.get("job")


class LinkLike(Protocol):        # the part of link.Link the runner uses
    state: str
    def list_param_rows(self, param: str) -> list[int]: ...
    def get_param_rows(self, param, row_ids, fields, *, cancel=None, progress=None) -> list[dict]: ...
    def loaded_maps(self) -> list[str]: ...
    def map_ids(self) -> list[str] | None: ...
    def open_maps(self, map_ids, *, cancel=None, progress=None) -> int: ...
    def placements(self, map_id: str) -> list["Placement"]: ...


class _Fail(Exception):
    """An operation failed: why is DataPiler's own words, safe to show and to log."""

    def __init__(self, why: str, *, check: int | None = None, where: str | None = None):
        super().__init__(why)
        self.why = own(why)
        self.check = check
        self.where = where


class _Cancelled(Exception):
    pass


@dataclass
class _Card:
    id: str
    sha256: str
    title: str | None
    format_ok: bool
    job: jobs.Job | None
    refusals: list[jobs.Refusal]
    preview: dict | None
    state: str
    ops: list[dict]
    added: float
    wait: str | None = None
    result: dict | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    remove_after: bool = False

    def public(self) -> dict:
        return {"id": self.id, "title": self.title, "format": jobs.FORMAT if self.format_ok else None,
                "sha256": self.sha256, "state": self.state,
                "refusals": [{"op": r.op, "where": r.where, "text": r.text} for r in self.refusals],
                "preview": self.preview, "wait": self.wait, "ops": [dict(o) for o in self.ops],
                "result": json.loads(json.dumps(self.result)) if self.result is not None else None,
                "added": self.added}          # S54: the page sorts the newest first by it


@dataclass
class _RowState:
    id: str
    state: str = "idle"
    wait: str | None = None
    progress: dict | None = None
    result: dict | None = None
    error: str | None = None
    started: float = 0.0
    waiting_for: set = field(default_factory=set)
    entries: int = 0

    def public(self, grey: str | None) -> dict:
        return {"id": self.id, "state": self.state, "grey": grey,
                "progress": dict(self.progress) if self.progress else None,
                "result": dict(self.result) if self.result else None, "error": self.error}


@dataclass
class _Ctx:
    """One run: of a job or of an Extract row."""
    job: jobs.Job
    builtin: bool
    row: str | None
    cancel: threading.Event
    log: logbook.Log
    on_op: Callable[[int, str, int, int | None, float | None], None]
    on_wait: Callable[[str | None], bool]
    tables: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)      # op index -> _Source: the game table it read (check 6)
    placed: dict = field(default_factory=dict)       # map -> the placements read on it, each map once (check 6)
    names: dict = field(default_factory=dict)        # text set -> provenance.names's record (P3)
    progress: "_MapProgress | None" = None           # S63: where the maps read so far are kept
    kept: dict = field(default_factory=dict)         # S63: map -> its placement rows, read in this run or before
    local: list = field(default_factory=list)
    share: tuple | None = None
    fetched: int = 0
    unit: str = "rows"


@dataclass(frozen=True)
class _Source:
    """The game table a fetch_rows or read_placements read, for check 6: its name (the param, or PLACEMENTS), its rows
    (a param's as Smithbox lists them, each row id once; None for the placements, which add up per map in
    _Ctx.placed), and whether no row id repeats among the rows the operation read, so that a share table's distinct
    row ids are its rows."""
    table: str
    of: int | None
    unique: bool


PLACEMENTS = "placements"           # check 6's name for the placements' game table


class _MapProgress:
    """S63: the placements a job has read, kept map by map in its folder as they are read, so that a job stopped by a
    crash of Smithbox, of the GPU's driver or of DataPiler goes on where it stopped. One JSON line per map, appended
    and flushed to disk at once: a header naming the job's sha256 and the game, Smithbox and regulation it was read
    from, then {"map": id, "rows": [[map, entityId, npcParamId, talkId, model], ...]}. Numbers only, never shared;
    a header that does not match drops the file, and a line cut short by a crash ends what is read. Removed when the
    job is done or removed."""

    def __init__(self, path: Path, key: dict):
        self.path = path
        self.header = dict({"format": MAPS_FORMAT}, **key)

    def load(self) -> dict[str, list[tuple]]:
        out: dict[str, list[tuple]] = {}
        try:
            with open(self.path, "rb") as f:
                lines = f.read().split(b"\n")
        except FileNotFoundError:
            return out
        except OSError:
            return out
        try:
            if json.loads(lines[0].decode("utf-8")) != self.header:
                self.clear()
                return out
        except (ValueError, UnicodeDecodeError):
            self.clear()
            return out
        for line in lines[1:]:
            if not line.strip():
                continue
            try:
                doc = json.loads(line.decode("utf-8"))
                m = doc["map"]
                if not isinstance(m, str) or not link_mod.MAP_RX.fullmatch(m):
                    break
                rows = [tuple(r) for r in doc["rows"]]
                if not all(len(r) == len(jobs.PLACEMENT_COLUMNS) and all(_type_ok("int", v) for v in r)
                           and r[0] == link_mod.map_key(m) for r in rows):
                    break
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                break                                  # a line cut short by a crash: what came before stands
            out[m] = rows
        return out

    def add(self, map_id: str, rows: list[tuple]) -> None:
        new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab") as f:
            if new:
                f.write(json.dumps(self.header, ensure_ascii=True).encode("ascii") + b"\n")
            f.write(json.dumps({"map": map_id, "rows": [list(r) for r in rows]}, ensure_ascii=True).encode("ascii")
                    + b"\n")
            f.flush()
            os.fsync(f.fileno())

    def clear(self) -> None:
        try:
            os.unlink(self.path)
        except OSError:
            pass
UNKNOWN_SOURCE = "unknown"          # a table whose source's rows were not counted: measured against 0


def _ops_public(job: jobs.Job) -> list[dict]:
    return [{"n": i, "op": o["op"], "state": "waiting", "done": 0, "of": None, "unit": UNITS[o["op"]], "secs": None}
            for i, o in enumerate(job.ops)]


def _type_ok(t: str, v: object) -> bool:
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
    if t == "bool":
        return isinstance(v, bool)
    return False


def _predicate(where: dict | None, cols: list[tuple[str, str]]) -> Callable[[tuple], bool]:
    if not where:
        return lambda row: True
    idx = {c: j for j, (c, _) in enumerate(cols)}
    tests: list[tuple[int, str, object]] = []
    for col, cond in where.items():
        items = cond.items() if isinstance(cond, dict) else [("eq", cond)]
        for k, v in items:
            tests.append((idx[col], k, frozenset(v) if k == "in" else v))

    def ok(row: tuple) -> bool:
        for j, k, v in tests:
            x = row[j]
            if x is None:
                return False
            if k == "eq":
                good = x == v
            elif k == "ne":
                good = x != v
            elif k == "lt":
                good = x < v
            elif k == "le":
                good = x <= v
            elif k == "gt":
                good = x > v
            elif k == "ge":
                good = x >= v
            else:
                good = x in v
            if not good:
                return False
        return True

    return ok


def _local_bytes(job_id: str, tables: list[tuple[str, list[tuple[str, str]], list]]) -> bytes:
    def j(v: object) -> str:
        return json.dumps(v, ensure_ascii=False, allow_nan=False, separators=(", ", ": "))

    lines = ["{", '  "format": %s,' % j(LOCAL_FORMAT), '  "job": %s,' % j(job_id), '  "tables": [']
    for ti, (name, cols, rows) in enumerate(tables):
        lines.append('    {"name": %s, "columns": %s,' % (j(name), j([{"name": c, "type": t} for c, t in cols])))
        end = "," if ti < len(tables) - 1 else ""
        if rows:
            lines.append('     "rows": [')
            lines.append(",\n".join("      " + j(list(r)) for r in rows))
            lines.append("     ]}" + end)
        else:
            lines.append('     "rows": []}' + end)
    lines.append("  ]")
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("utf-8")


class Runner:
    def __init__(self, paths: "paths_mod.Paths | Callable[[], paths_mod.Paths]", link: LinkLike, textdb: "TextDB",
                 guard: "Guard", provenance: Callable[[], dict], game: Callable[[], "GameRunning"],
                 language: Callable[[], str], *, map_opengl: Callable[[], bool] = lambda: False):
        """paths: the Paths, or a callable giving the current ones (Settings can move the workspace and the share
        folder; the folders are read afresh at each write)."""
        self._paths = paths
        self.link = link
        self.textdb = textdb
        self.guard = guard
        self.provenance = provenance
        self.game = game
        self.language = language
        self.map_opengl = map_opengl
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._cards: dict[str, _Card] = {}
        self._queue: deque[tuple[str, str]] = deque()
        self._current: tuple[str, str] | None = None
        self._stopping = False
        self._worker: threading.Thread | None = None
        self._rows: dict[str, _RowState] = {r.id: _RowState(r.id) for r in catalogue.ROWS}
        self._row_maps: dict[str, list[str]] = {}
        self._extract_cancel = threading.Event()
        self._ask: dict | None = None
        self._map_hint: str | None = None
        self._unsubs = [events.subscribe("link.state", self._wake),
                        events.subscribe("settings.saved", self._wake),
                        events.subscribe("inbox.import", self._on_import),
                        events.subscribe("app.stopping", self._on_stopping)]

    # ------------------------------------------------------------------------------------------------ folders

    @property
    def paths(self) -> "paths_mod.Paths":
        p = self._paths
        return p() if callable(p) else p

    def _folder(self, card_id: str) -> Path:
        return self.paths.jobs / card_id

    def _save(self, card: _Card) -> None:
        doc = {"format": STATE_FORMAT, "id": card.id, "state": card.state, "wait": card.wait, "ops": card.ops,
               "result": card.result, "added": card.added}
        try:
            folder = self._folder(card.id)
            folder.mkdir(parents=True, exist_ok=True)
            fileio.write_atomic(folder / "state.json", json.dumps(doc, indent=1, ensure_ascii=True).encode("ascii"))
        except (OSError, ValueError) as e:
            _job_log.error("the state of the job %s could not be saved: %s", own(card.id), logbook.why(e))

    def _drop_folder(self, card_id: str) -> None:
        folder = self._folder(card_id)
        for name in ("job.json", "state.json", MAPS_FILE):
            try:
                os.unlink(folder / name)
            except FileNotFoundError:
                pass
            except OSError as e:
                _job_log.warn("a file of the job %s could not be removed: %s", own(card_id), logbook.why(e))
        try:
            folder.rmdir()
        except OSError:
            pass

    # ------------------------------------------------------------------------------------------------ checking

    def _share_names(self, *, skip: str | None = None) -> dict[str, str]:
        out = dict(catalogue.share_names())
        for c in self._cards.values():
            if c.job is not None and c.job.share_name and c.id != skip:
                out.setdefault(c.job.share_name, c.id)
        return out

    def _known_ids(self, *, skip: str | None = None) -> set[str]:
        return {c.id for c in self._cards.values() if c.job is not None and c.id != skip}

    def _make_card(self, raw: bytes, *, known: set[str], share_names: dict[str, str], added: float,
                   folder: str | None = None) -> _Card:
        sha = fileio.sha256_bytes(raw)
        try:
            job = jobs.check(raw, known_ids=known, share_names=share_names)
        except jobs.JobRefused as r:
            card_id = r.id if r.id is not None else "refused-" + sha[:12]
            if folder is not None:
                card_id = folder
            return _Card(id=card_id, sha256=sha, title=r.title, format_ok=r.format_ok, job=None,
                         refusals=list(r.refusals), preview=None, state="refused", ops=[], added=added)
        if folder is not None and folder != job.id:
            return _Card(id=folder, sha256=sha, title=job.title, format_ok=True, job=None,
                         refusals=[jobs.Refusal("id", "the job's folder does not match its id", None)],
                         preview=None, state="refused", ops=[], added=added)
        return _Card(id=job.id, sha256=sha, title=job.title, format_ok=True, job=job, refusals=[],
                     preview=jobs.preview(job), state="checked", ops=_ops_public(job), added=added)

    # ------------------------------------------------------------------------------------------------ jobs

    def load_folder(self) -> None:
        """jobs/ at start: every card back; a job that was running shows "stopped" and is not resumed."""
        root = self.paths.jobs
        try:
            names = [d.name for d in os.scandir(root) if d.is_dir(follow_symlinks=False)]
        except FileNotFoundError:
            return
        found: list[tuple[float, str, dict]] = []
        for name in names:
            if not paths_mod.name_ok(name):
                continue
            state: dict = {}
            try:
                state = json.loads(fileio.read_limited(root / name / "state.json", 4 * 1024 * 1024).decode("utf-8"))
                if not isinstance(state, dict) or state.get("format") != STATE_FORMAT:
                    state = {}
            except (OSError, ValueError):
                state = {}
            added = state.get("added")
            if not isinstance(added, (int, float)) or isinstance(added, bool):
                try:
                    added = (root / name).stat().st_mtime
                except OSError:
                    added = 0.0
            found.append((float(added), name, state))
        found.sort()
        stopped = 0
        with self._lock:
            for added, name, state in found:
                try:
                    raw = fileio.read_limited(root / name / "job.json", jobs.MAX_BYTES * 2)
                except fileio.TooLarge:
                    raw = None
                except OSError:
                    continue
                if raw is None:
                    try:
                        sha = fileio.sha256_file(root / name / "job.json")
                    except OSError:
                        continue
                    card = _Card(id=name, sha256=sha, title=None, format_ok=False, job=None,
                                 refusals=[jobs.Refusal("(file)", "the file is over 256 KB", None)], preview=None,
                                 state="refused", ops=[], added=added)
                elif not raw:
                    continue
                else:
                    card = self._make_card(raw, known=self._known_ids(), share_names=self._share_names(),
                                           added=added, folder=name)
                if card.job is not None:
                    st = state.get("state")
                    if st in ACTIVE:
                        card.state = "stopped"
                        stopped += 1
                    elif st in ("done", "failed", "cancelled", "stopped"):
                        card.state = st
                    ops = state.get("ops")
                    if isinstance(ops, list) and len(ops) == len(card.ops) and \
                            all(isinstance(o, dict) and o.get("op") == c["op"] for o, c in zip(ops, card.ops)):
                        card.ops = [dict(c, **{k: o.get(k) for k in ("state", "done", "of", "secs")})
                                    for o, c in zip(ops, card.ops)]
                        if card.state == "stopped":
                            for o in card.ops:
                                if o["state"] in ("running", "waiting"):
                                    o["state"] = "stopped"
                    result = state.get("result")
                    card.result = result if isinstance(result, dict) and card.state in (
                        "done", "failed", "cancelled", "stopped") else None
                self._cards[card.id] = card
                if card.state == "stopped" and state.get("state") in ACTIVE:
                    self._save(card)
        _job_log.info("jobs folder read: %s jobs, %s stopped by the last quit", logbook.n(len(found)),
                      logbook.n(stopped))

    def add(self, filename: str, raw: bytes) -> tuple[dict, bool]:
        """Keep raw as jobs/<id>/job.json, check it, return (card, again). again is True when the same sha256 is
        here already (its card is returned, nothing duplicated). A refused job is a card too. Never raises for a
        bad job; ValueError for an empty upload. The file's own name is never kept or logged."""
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise ValueError("the upload is empty")
        raw = bytes(raw)
        sha = fileio.sha256_bytes(raw)
        with self._lock:
            for c in self._cards.values():
                if c.sha256 == sha:
                    return c.public(), True
            card = self._make_card(raw, known=self._known_ids(), share_names=self._share_names(), added=time.time())
            old = self._cards.get(card.id)
            if old is not None:
                if old.job is not None:            # cannot happen: an accepted id is never usable again
                    card = replace(card, id="refused-" + sha[:12])
                else:
                    self._drop_folder(old.id)      # a refused card with this id: the new file takes its place
                    del self._cards[old.id]
            try:
                folder = self._folder(card.id)
                folder.mkdir(parents=True, exist_ok=True)
                fileio.write_atomic(folder / "job.json", raw)
            except OSError as e:
                _job_log.error("a dropped job file could not be kept: %s", logbook.why(e))
                raise
            self._cards[card.id] = card
            self._save(card)
            jl = logbook.for_job(own(card.id))
            try:
                if card.job is not None:
                    jl.info("added (%s bytes): checked; operations: %s", logbook.n(len(raw)),
                            logbook.n(len(card.job.ops)))
                else:
                    jl.info("added (%s bytes): refused; refusals: %s", logbook.n(len(raw)),
                            logbook.n(len(card.refusals)))
            finally:
                jl.close()
            events.emit("job.added", id=own(card.id), state=own(card.state))
            return card.public(), False

    def act(self, job_id: str, what: str, *, confirm_maps: int | None = None) -> dict:
        """what: "start", "cancel" or "remove". {"ok": True}, or {"ok": False, "ask": {...}} when Start would load
        more than ten maps and confirm_maps does not equal that number (S8). ValueError for an unknown id or what."""
        if what not in ("start", "cancel", "remove"):
            raise ValueError("not something a job can do")
        with self._cv:
            card = self._cards.get(job_id) if isinstance(job_id, str) else None
            if card is None:
                raise ValueError("no such job")
            if what == "start":
                if card.job is None:
                    return {"ok": False, "error": "a refused job cannot start - drop a corrected file"}
                if card.state in ACTIVE:
                    return {"ok": True}
                maps = card.job.maps or 0
                fams = tuple(getattr(card.job, "map_families", ()) or ())
                if fams and confirm_maps != maps:
                    return {"ok": False, "ask": {"maps": maps, "text": (
                        "This job loads every map of %s in Smithbox%s, ten at a time; how many is known once Smithbox "
                        "lists them. Smithbox's view changes, not its data, and loading may take a long while. Start "
                        "it?" % (jobs._and(list(fams)), " and %s more" % "{:,}".format(maps) if maps else ""))}}
                if maps > MAP_QUESTION and confirm_maps != maps:
                    return {"ok": False, "ask": {"maps": maps, "text": (
                        "This job loads %s maps in Smithbox, ten at a time. Smithbox's view changes, not its data, "
                        "and loading may take a long while. Start it?" % "{:,}".format(maps))}}
                card.cancel = threading.Event()
                card.state, card.wait, card.result = "queued", None, None
                card.ops = _ops_public(card.job)
                self._queue.append(("job", card.id))
                self._save(card)
                events.emit("job.state", id=own(card.id), state=own("queued"))
                self._ensure_worker()
                self._cv.notify_all()
                return {"ok": True}
            if what == "cancel":
                if card.state == "queued" and ("job", card.id) in self._queue:
                    self._queue.remove(("job", card.id))
                    card.state = "cancelled"
                    self._save(card)
                    events.emit("job.state", id=own(card.id), state=own("cancelled"))
                elif card.state in ACTIVE:
                    card.cancel.set()
                    self._cv.notify_all()
                return {"ok": True}
            # remove
            if self._current == ("job", card.id):
                card.cancel.set()
                card.remove_after = True
                self._cv.notify_all()
                return {"ok": True}
            if ("job", card.id) in self._queue:
                self._queue.remove(("job", card.id))
            self._drop_folder(card.id)
            del self._cards[card.id]
            _job_log.info("job %s removed", own(card.id))
            events.emit("job.state", id=own(card.id), state=own("removed"))
            return {"ok": True}

    def cards(self) -> list[dict]:
        """/api/state "jobs", in the order they were added."""
        with self._lock:
            return [c.public() for c in self._cards.values()]

    # ------------------------------------------------------------------------------------------------ Extract

    def run_extract(self, rows: Sequence[str], *, load_maps: bool = False,
                    confirm_maps: int | None = None) -> dict:
        """Queue the ticked rows (server rows first); guided rows show their steps and wait for the inbox.
        {"ok": True} or {"ok": False, "ask": {...}}. ValueError for an unknown row."""
        wanted = list(rows)
        known = {x.id for x in catalogue.ROWS}
        for r in wanted:
            if not isinstance(r, str) or r not in known:
                raise ValueError("not a row of the catalogue")
        chosen = [r for r in catalogue.ROWS if r.id in wanted]
        server = [r for r in chosen if "server" in r.sources]
        guided = [r for r in chosen if "guided" in r.sources]
        maps: list[str] | None = None
        if load_maps and any(r.needs_maps for r in server):
            try:
                maps = self.link.map_ids()
            except link_mod.LinkError:
                maps = None
            if maps is not None:
                maps = [m for m in maps if isinstance(m, str) and link_mod.MAP_RX.fullmatch(m)]
                if len(maps) > MAP_QUESTION and confirm_maps != len(maps):
                    ask = {"maps": len(maps), "text": (
                        "Map placements loads %s maps in Smithbox first, ten at a time. Smithbox's view changes, "
                        "not its data, and loading may take an hour or more. Run?" % "{:,}".format(len(maps)))}
                    with self._lock:
                        self._ask = ask
                    return {"ok": False, "ask": ask}
        with self._cv:
            self._ask = None
            if not any(kind == "extract" for kind, _ in self._queue) and \
                    not (self._current and self._current[0] == "extract"):
                self._extract_cancel = threading.Event()
            queued = 0
            for r in server:
                st = self._rows[r.id]
                if st.state in ("queued", "running"):
                    continue
                self._rows[r.id] = _RowState(r.id, state="queued")
                if maps:
                    self._row_maps[r.id] = list(maps)
                else:
                    self._row_maps.pop(r.id, None)
                self._queue.append(("extract", r.id))
                queued += 1
                events.emit("extract.row", row=own(r.id), state=own("queued"), done=0, of=None)
            for r in guided:
                if not r.containers:
                    continue
                st = self._rows[r.id]
                if st.state == "waiting_export":
                    continue
                self._rows[r.id] = _RowState(r.id, state="waiting_export", started=time.time(),
                                             waiting_for=set(r.containers),
                                             progress={"done": 0, "of": len(r.containers), "unit": "containers"})
                events.emit("extract.row", row=own(r.id), state=own("waiting_export"), done=0,
                            of=len(r.containers))
            if queued:
                self._ensure_worker()
                self._cv.notify_all()
        _extract_log.info("Extract run: %s server rows queued, %s guided rows wait for their exports",
                          logbook.n(len(server)), logbook.n(sum(1 for r in guided if r.containers)))
        return {"ok": True}

    def cancel_extract(self) -> None:
        with self._cv:
            self._extract_cancel.set()
            for kind, rid in list(self._queue):
                if kind == "extract":
                    self._queue.remove((kind, rid))
                    self._rows[rid].state = "cancelled"
                    events.emit("extract.row", row=own(rid), state=own("cancelled"), done=0, of=None)
            for st in self._rows.values():
                if st.state == "waiting_export":
                    st.state = "cancelled"
                    events.emit("extract.row", row=own(st.id), state=own("cancelled"), done=0, of=None)
            self._ask = None
            self._cv.notify_all()
        _extract_log.info("Extract run cancelled")

    def _grey(self, row: catalogue.Row, st: _RowState) -> str | None:
        if "guided" in row.sources:
            return None if row.containers else "the text container of these names is not confirmed yet"
        if st.wait:
            return st.wait
        reason = LINK_WAITS.get(getattr(self.link, "state", "off"))
        if reason:
            return reason
        if row.needs_maps and self._map_hint:
            return self._map_hint
        return None

    def extract_state(self) -> dict:
        """/api/state "extract": the running row, each row's state, the pending map question."""
        with self._lock:
            running = self._current[1] if self._current and self._current[0] == "extract" else None
            return {"running": running,
                    "rows": [self._rows[r.id].public(self._grey(r, self._rows[r.id])) for r in catalogue.ROWS],
                    "ask": dict(self._ask) if self._ask else None}

    def _on_import(self, topic: str, data: dict) -> None:
        container = data.get("container")
        if not data.get("ok") or not isinstance(container, str):
            return
        with self._lock:
            for r in catalogue.ROWS:
                st = self._rows[r.id]
                if st.state != "waiting_export" or container not in st.waiting_for:
                    continue
                st.waiting_for.discard(container)
                entries = data.get("entries")
                st.entries += entries if isinstance(entries, int) and not isinstance(entries, bool) else 0
                done = len(r.containers) - len(st.waiting_for)
                st.progress = {"done": done, "of": len(r.containers), "unit": "containers"}
                if not st.waiting_for or done >= 1:      # one export suffices (S42): any of its containers
                    st.waiting_for.clear()
                    st.state = "done"
                    st.progress = None
                    st.result = {"count": st.entries, "unit": "entries", "secs": round(time.time() - st.started, 1)}
                _extract_log.info("%s: the export of %s arrived (%s of %s)", own(r.name), own(container),
                                  logbook.n(done), logbook.n(len(r.containers)))
                events.emit("extract.row", row=own(r.id), state=own(st.state), done=done, of=len(r.containers))

    # ------------------------------------------------------------------------------------------------ outputs

    def made_by(self) -> dict[str, Own]:
        """Output files, relative to the workspace or the share folder, and what made each: a job id, "Extract"
        or "guided import"."""
        out: dict[str, Own] = {}
        for rid in (r.id for r in catalogue.ROWS if "server" in r.sources):
            out["local/extract/%s.json" % rid] = own("Extract")
        for name in catalogue.share_names():
            out["%s.json" % name] = own("Extract")
        with self._lock:
            for c in self._cards.values():
                if c.job is None:
                    continue
                for o in c.job.ops:
                    if o["op"] == "write_local":
                        out["local/%s/%s.json" % (c.id, o["name"])] = own(c.id)
                if c.job.share_name:
                    out["%s.json" % c.job.share_name] = own(c.id)
        return out

    def busy(self) -> dict | None:
        """{"kind": "job" or "extract", "id": ..., "title": ...} while something runs."""
        with self._lock:
            if self._current is None:
                return None
            kind, ident = self._current
            if kind == "job":
                card = self._cards.get(ident)
                return {"kind": "job", "id": ident, "title": card.title if card else None}
            return {"kind": "extract", "id": ident, "title": catalogue.row(ident).name}

    # ------------------------------------------------------------------------------------------------ stopping

    def _wake(self, topic: str, data: dict) -> None:
        with self._cv:
            self._cv.notify_all()

    def _on_stopping(self, topic: str, data: dict) -> None:
        with self._cv:
            self._stopping = True
            self._cancel_current()
            self._cv.notify_all()

    def _cancel_current(self) -> None:
        if self._current is None:
            return
        kind, ident = self._current
        if kind == "job":
            card = self._cards.get(ident)
            if card is not None:
                card.cancel.set()
        else:
            self._extract_cancel.set()

    def stop(self, *, cancel: bool, timeout: float = 3.0) -> None:
        """For Quit: cancel between calls, wait up to timeout. Jobs still queued show "stopped"."""
        with self._cv:
            self._stopping = True
            if cancel:
                self._cancel_current()
            self._cv.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=max(0.0, timeout))
        with self._cv:
            for kind, ident in list(self._queue):
                if kind == "job" and ident in self._cards:
                    card = self._cards[ident]
                    card.state = "stopped"
                    self._save(card)
                elif kind == "extract":
                    self._rows[ident].state = "cancelled"
            self._queue.clear()
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []

    # ------------------------------------------------------------------------------------------------ the worker

    def _ensure_worker(self) -> None:
        if self._stopping or (self._worker is not None and self._worker.is_alive()):
            return
        self._worker = threading.Thread(target=self._loop, name="datapiler-runner", daemon=True)
        self._worker.start()

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._stopping:
                    self._cv.wait()
                if self._stopping:
                    return
                item = self._queue.popleft()
                self._current = item
            try:
                if item[0] == "job":
                    self._run_job(item[1])
                else:
                    self._run_row(item[1])
            except Exception as e:
                _job_log.error("the runner met an internal error: %s", logbook.why(e))
            finally:
                with self._cv:
                    self._current = None
                    if item[0] == "job":
                        card = self._cards.get(item[1])
                        if card is not None and card.remove_after:
                            self._drop_folder(card.id)
                            del self._cards[card.id]
                            events.emit("job.state", id=own(card.id), state=own("removed"))
                    self._cv.notify_all()

    def _link_reason(self) -> str | None:
        state = getattr(self.link, "state", "off")
        if state != "on":
            return LINK_WAITS.get(state, LINK_WAITS["off"])
        try:
            g = self.game()
            if g.running:
                return LINK_WAITS["blocked"]
        except Exception:
            return LINK_WAITS["blocked"]
        return None

    def _wait_for_link(self, cancel: threading.Event, say: Callable[[str | None], None]) -> bool:
        """Wait until the link is on and the game closed. False when cancelled or stopping."""
        said: str | None = None
        while True:
            if cancel.is_set() or self._stopping:
                return False
            reason = self._link_reason()
            if reason is None:
                if said is not None:
                    say(None)
                return True
            if reason != said:
                say(reason)
                said = reason
            with self._cv:
                if cancel.is_set() or self._stopping:
                    return False
                self._cv.wait(WAIT_POLL)

    def _build_reason(self) -> str | None:
        """DP20 (S64): with the setting on, why a map job may not load maps now: Smithbox runs as its Vulkan build and
        not as its OpenGL build. None when it may, or when the process list cannot be read."""
        try:
            if not self.map_opengl():
                return None
        except Exception:
            return None
        rs = smithbox_mod.seen()
        if not rs:
            return None
        names = [r.name.lower() for r in rs if isinstance(r.name, str)]
        if any("opengl" in n for n in names) or not any("vulkan" in n for n in names):
            return None
        return ("Smithbox runs as its Vulkan build, and map jobs run on its OpenGL build only (Settings): close "
                "Smithbox, start Smithbox.OpenGL.exe from Smithbox's folder with the same project, keep its Map Editor "
                "tab in front, and the job goes on")

    def _wait_for_build(self, ctx: _Ctx) -> bool:
        """Wait until _build_reason clears (S64). False when cancelled or stopping."""
        said: str | None = None
        while True:
            if ctx.cancel.is_set() or self._stopping:
                return False
            reason = self._build_reason()
            if reason is None:
                if said is not None:
                    # Smithbox was just started again: give it time to open its project before asking for maps, as
                    # a map job started at once met UNAVAILABLE (2026-11-14).
                    if not self._wait_for_maps(ctx):
                        return False
                    ctx.on_wait(None)
                return True
            if reason != said:
                ctx.on_wait(reason)
                said = reason
            with self._cv:
                if ctx.cancel.is_set() or self._stopping:
                    return False
                self._cv.wait(WAIT_POLL)

    def _wait_for_maps(self, ctx: _Ctx) -> bool:
        """After a switch of Smithbox's build: wait, up to MAPS_READY_WAIT seconds, until its server lists the
        project's maps; then the job goes on either way, and load_maps says what is wrong if anything is."""
        ctx.on_wait("waiting for Smithbox to open its project and its server to answer")
        end = time.monotonic() + MAPS_READY_WAIT
        while time.monotonic() < end:
            if ctx.cancel.is_set() or self._stopping:
                return False
            try:
                if self.link.all_maps():
                    return True
            except link_mod.LinkError:
                pass
            with self._cv:
                if ctx.cancel.is_set() or self._stopping:
                    return False
                self._cv.wait(MAPS_READY_POLL)
        return True

    # ---- a job

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            card = self._cards.get(job_id)
            if card is None or card.job is None:
                return
            job, cancel = card.job, card.cancel
            card.state = "running"
            self._save(card)
        events.emit("job.state", id=own(job_id), state=own("running"))
        jl = logbook.for_job(own(job_id))
        started = time.monotonic()

        def on_op(i: int, state: str, done: int, of: int | None, secs: float | None) -> None:
            with self._lock:
                o = card.ops[i]
                changed = o["state"] != state
                o.update(state=state, done=done, of=of, secs=secs)
                if changed:
                    self._save(card)
            events.emit("job.op", id=own(job_id), n=i, state=own(state), done=done, of=of)

        def on_wait(reason: str | None) -> bool:
            with self._lock:
                card.wait = reason
                card.state = "waiting" if reason else "running"
                self._save(card)
            if reason:
                jl.info("waits: %s", own(reason))
            events.emit("job.state", id=own(job_id), state=own(card.state))
            return True

        ctx = _Ctx(job=job, builtin=False, row=None, cancel=cancel, log=jl, on_op=on_op, on_wait=on_wait)
        try:
            jl.info("started: %s operations", logbook.n(len(job.ops)))
            self._open_progress(ctx, job_id)
            outcome, fail = self._execute(ctx)
            if outcome == "done" and ctx.progress is not None:
                ctx.progress.clear()
            secs = time.monotonic() - started
            with self._lock:
                card.wait = None
                if outcome == "done":
                    share = ctx.share
                    card.result = {"share": share, "local": list(ctx.local), "failed": None}
                    card.state = "done"
                    jl.info("done in %s s: %s local files, %s", logbook.n(secs), logbook.n(len(ctx.local)),
                            own("a share file" if share else "no share file"))
                elif outcome == "failed":
                    assert fail is not None
                    card.result = {"share": None, "local": list(ctx.local), "failed": fail}
                    card.state = "failed"
                    jl.error("failed at op %s (%s): %s", fail["op"], own(job.ops[fail["op"]]["op"]),
                             own(fail["why"]))
                else:
                    card.result = {"share": None, "local": list(ctx.local), "failed": None}
                    card.state = "stopped" if self._stopping and not card.remove_after else "cancelled"
                    jl.info("%s between calls", own(card.state))
                    for o in card.ops:
                        if o["state"] in ("running", "waiting"):
                            o["state"] = "cancelled"
                self._save(card)
            events.emit("job.state", id=own(job_id), state=own(card.state))
        finally:
            jl.close()

    # ---- an Extract row

    def _builtin_job(self, row_id: str) -> jobs.Job:
        ops = catalogue.ops_for(row_id)
        maps = self._row_maps.get(row_id)
        if maps:
            ops = [{"op": "load_maps", "maps": list(maps)}] + ops
        doc = {"format": jobs.FORMAT, "id": catalogue.job_id(row_id), "title": catalogue.row(row_id).name,
               "ops": ops}
        raw = json.dumps(doc, ensure_ascii=True).encode("ascii")
        job = jobs.check(raw, known_ids=(), share_names={}, builtin=True)
        return replace(job, sha256=jobs.canonical_sha256(ops))

    def _run_row(self, row_id: str) -> None:
        row = catalogue.row(row_id)
        with self._lock:
            st = self._rows[row_id]
            if st.state != "queued":
                return
            cancel = self._extract_cancel
            st.started = time.time()                       # "running" once its first operation starts
        started = time.monotonic()
        try:
            job = self._builtin_job(row_id)
        except jobs.JobRefused:
            with self._lock:
                st.state, st.error = "failed", "an internal error (the row's built-in job did not pass its check)"
            _extract_log.error("%s: its built-in job did not pass the check", own(row.name))
            return

        def on_op(i: int, state: str, done: int, of: int | None, secs: float | None) -> None:
            unit = UNITS[job.ops[i]["op"]]
            with self._lock:
                if st.state == "queued":
                    st.state, st.wait = "running", None
                if state == "running" and unit in ("rows", "maps") and job.ops[i]["op"] in jobs.READS:
                    st.progress = {"done": done, "of": of, "unit": unit}
            events.emit("extract.row", row=own(row_id), state=own("running"), done=done, of=of)

        def on_wait(reason: str | None) -> bool:
            with self._lock:
                st.wait = reason
                st.state = "queued" if reason else "running"
            if reason:
                _extract_log.info("%s waits: %s", own(row.name), own(reason))
            events.emit("extract.row", row=own(row_id), state=own(st.state), done=0, of=None)
            return True

        ctx = _Ctx(job=job, builtin=True, row=row_id, cancel=cancel, log=_extract_log, on_op=on_op, on_wait=on_wait)
        outcome, fail = self._execute(ctx)
        secs = round(time.monotonic() - started, 1)
        with self._lock:
            st.wait = None
            st.progress = None
            if outcome == "done":
                st.state = "done"
                st.result = {"count": ctx.fetched, "unit": ctx.unit, "secs": secs}
                if row.needs_maps:
                    self._map_hint = None
                _extract_log.info("%s done: %s %s in %s s", own(row.name), logbook.n(ctx.fetched), own(ctx.unit),
                                  logbook.n(secs))
            elif outcome == "failed":
                assert fail is not None
                st.state = "failed"
                st.error = fail["why"]
                _extract_log.error("%s failed at op %s (%s): %s", own(row.name), fail["op"],
                                   own(job.ops[fail["op"]]["op"]), own(fail["why"]))
            else:
                st.state = "cancelled"
                _extract_log.info("%s cancelled between calls", own(row.name))
        events.emit("extract.row", row=own(row_id), state=own(st.state), done=ctx.fetched, of=None)

    # ------------------------------------------------------------------------------------------------ the ops

    def _execute(self, ctx: _Ctx) -> tuple[str, dict | None]:
        """("done" | "failed" | "cancelled", the failure)."""
        job = ctx.job
        for i, o in enumerate(job.ops):
            op = o["op"]
            while True:
                if ctx.cancel.is_set() or self._stopping:
                    return "cancelled", None
                if op in jobs.LINK_OPS and not self._wait_for_link(ctx.cancel, ctx.on_wait):
                    return "cancelled", None
                if op == "load_maps" and not ctx.builtin and not self._wait_for_build(ctx):
                    return "cancelled", None
                ctx.on_op(i, "running", 0, None, None)
                t0 = time.monotonic()
                try:
                    done, of = self._op(ctx, i, o)
                except (link_mod.LinkOff, link_mod.LinkBlocked, link_mod.LibsMissing):
                    ctx.on_op(i, "waiting", 0, None, None)
                    with self._cv:
                        self._cv.wait(WAIT_POLL)
                    continue                               # the link went off: wait, then run this op again
                except (link_mod.LinkCancelled, _Cancelled):
                    ctx.on_op(i, "cancelled", 0, None, None)
                    return "cancelled", None
                except GuardFailed as e:
                    ctx.on_op(i, "failed", 0, None, round(time.monotonic() - t0, 1))
                    return "failed", {"op": i, "why": _guard_why(e), "check": e.check, "where": e.where or None}
                except _Fail as e:
                    ctx.on_op(i, "failed", 0, None, round(time.monotonic() - t0, 1))
                    return "failed", {"op": i, "why": str(e.why), "check": e.check, "where": e.where}
                except link_mod.LinkError as e:
                    ctx.on_op(i, "failed", 0, None, round(time.monotonic() - t0, 1))
                    return "failed", {"op": i, "why": str(e), "check": None, "where": None}
                except Exception as e:
                    ctx.on_op(i, "failed", 0, None, round(time.monotonic() - t0, 1))
                    return "failed", {"op": i, "why": "an internal error (%s)" % logbook.why(e), "check": None,
                                      "where": None}
                secs = round(time.monotonic() - t0, 1)
                ctx.on_op(i, "done", done, of, secs)
                if ctx.builtin:
                    ctx.log.debug("op %s %s: %s %s in %s s", i, own(op), logbook.n(done), own(UNITS[op]),
                                  logbook.n(secs))
                else:
                    ctx.log.info("op %s %s: %s %s in %s s", i, own(op), logbook.n(done), own(UNITS[op]),
                                 logbook.n(secs))
                break
        if ctx.share is not None:
            i, name, data, declared, coverage = ctx.share
            try:
                written = self.guard.write(self.paths.share, name, data, declared=declared, coverage=coverage)
            except GuardFailed as e:
                ctx.share = None
                ctx.on_op(i, "failed", 0, None, None)
                return "failed", {"op": i, "why": _guard_why(e), "check": e.check, "where": e.where or None}
            except OSError as e:
                ctx.share = None
                ctx.on_op(i, "failed", 0, None, None)
                return "failed", {"op": i, "why": "the share file could not be written: %s" % logbook.why(e),
                                  "check": None, "where": None}
            try:
                from .guard import record_counts
                record_counts(self.paths.share_counts, written.name, written.sha256, coverage)
            except (OSError, ValueError) as e:
                ctx.log.warn("the share file's row counts could not be kept, so Outputs lists it apart until the job "
                             "runs again: %s", logbook.why(e))
            ctx.share = {"name": written.name, "size": written.size, "sha256": written.sha256}
        return "done", None

    def _op(self, ctx: _Ctx, i: int, o: dict) -> tuple[int, int | None]:
        op = o["op"]
        if op == "fetch_rows":
            return self._fetch_rows(ctx, i, o)
        if op == "load_maps":
            maps = self._resolve_maps(o["maps"])
            t0 = time.monotonic()
            # S63: a map whose placements this run or an earlier one read and kept is not loaded again.
            kept = [m for m in maps if m in ctx.kept]
            todo = [m for m in maps if m not in ctx.kept]
            if kept:
                ctx.log.info("op %s load_maps: %s of %s maps were read before and are kept; they are not loaded again",
                             i, logbook.n(len(kept)), logbook.n(len(maps)))
            # S52: the card shows maps loaded of maps to load, and the time so far, at every poll.
            kw = {"timeout": float(o["timeout"])} if o.get("timeout") is not None else {}
            kw.update(self._map_limits(ctx, i))
            if ctx.progress is not None:
                reads = self._maps_read_later(ctx, i)
                kw["on_loaded"] = lambda m: self._read_now(ctx, m) if m in reads else None
                kw["session_cap"] = MAPS_PER_SESSION
            n = self.link.open_maps(todo, cancel=ctx.cancel, progress=lambda d, t: ctx.on_op(
                i, "running", d, t, round(time.monotonic() - t0, 1)), **kw)
            capped = getattr(self.link, "capped", None) if ctx.progress is not None else None
            if capped:
                done = sum(1 for m in maps if m in ctx.kept)
                raise _Fail("paused, to spare Smithbox and the graphics driver: Smithbox holds %d maps, the most a job "
                            "asks it to hold at once. %d of %d maps are read and kept. Close Smithbox, start it again, "
                            "then press Start again here: the job goes on from there" % (capped[0], done, len(maps)))
            return n + len(kept), len(maps)
        if op == "unused_names":
            return self._unused_names(ctx, i, o)
        if op == "read_placements":
            return self._read_placements(ctx, i, o)
        if op == "join_names":
            return self._join_names(ctx, i, o)
        if op == "filter":
            cols, rows = ctx.tables[o["rows"]]
            keep = _predicate(o.get("where"), cols)
            if o.get("slots") == "boss":
                e = [c for c, _ in cols].index("entityId")
                lo, hi = jobs.BOSS_SLOTS
                where_keep = keep
                keep = lambda r, w=where_keep: isinstance(r[e], int) and r[e] > 0 and lo <= r[e] % 1000 <= hi and w(r)  # noqa: E731
            if o.get("ids") is not None:
                j = [c for c, _ in cols].index(o["key"])
                picked = frozenset(o["ids"])
                out = [r for r in rows if r[j] in picked and keep(r)]
            else:
                out = [r for r in rows if keep(r)]
            ctx.tables[o["as"]] = (list(cols), out)
            return len(out), len(rows)
        if op == "count":
            return self._count(ctx, o)
        if op == "distinct":
            cols, rows = ctx.tables[o["rows"]]
            idx = [j for b in o["by"] for j, (c, _) in enumerate(cols) if c == b]
            seen = sorted({tuple(r[j] for j in idx) for r in rows}, key=_sort_key)
            ctx.tables[o["as"]] = ([cols[j] for j in idx], seen)
            return len(seen), len(rows)
        if op == "write_local":
            return self._write_local(ctx, o)
        if op == "write_share":
            return self._write_share(ctx, i, o)
        raise _Fail("an operation DataPiler does not have")

    def _fetch_rows(self, ctx: _Ctx, i: int, o: dict) -> tuple[int, int | None]:
        param = o["param"]
        cols = [("id", "int")] + [(f, fields.PARAMS[param][f]) for f in o["fields"] if f != "id"]
        ids = o.get("ids")
        listed: int | None = None
        if isinstance(ids, list):
            row_ids = list(dict.fromkeys(ids))
            # Check 6 measures a share table against the whole param's rows, as Smithbox lists them.
            if ctx.job.share_name is not None:
                listed = len(self.link.list_param_rows(param))
        else:
            every = self.link.list_param_rows(param)
            listed = len(every)
            row_ids = [x for x in every if ids["from"] <= x <= ids["to"]] if isinstance(ids, dict) else list(every)
        ctx.on_op(i, "running", 0, len(row_ids), None)
        t0 = time.monotonic()
        recs = self.link.get_param_rows(param, row_ids, [c for c, _ in cols], cancel=ctx.cancel,
                                        progress=lambda d, t: ctx.on_op(i, "running", d, t, None))
        rows: list[tuple] = []
        for rec in recs:
            row = []
            for j, (c, t) in enumerate(cols):
                v = rec.get(c) if isinstance(rec, dict) else None
                if not _type_ok(t, v):
                    raise _Fail("the server sent a value of another type than DataPiler reads (field %d)" % j)
                row.append(v)
            rows.append(tuple(row))
        ctx.tables[o["as"]] = (cols, rows)
        if listed is not None:
            # Smithbox lists each row id once, but a row id may be held by more than one row: the share tables of this
            # read are measured by their ids only when no id repeats among the rows it read (S19).
            ctx.sources[i] = _Source(param, listed, len({r[0] for r in rows}) == len(rows))
        if ctx.builtin:
            ctx.fetched += len(rows)
            ctx.unit = "rows"
            _extract_log.info("%s: %s rows read in %s s", own(param), logbook.n(len(rows)),
                              logbook.n(time.monotonic() - t0))
        return len(rows), len(rows)

    def _map_limits(self, ctx: _Ctx, i: int) -> dict:
        """S59 (DP19): Smithbox's saved preferences, said in the log, set how long the first map may take: 10 s with
        model rendering off, 300 s with it on (and a warning), none passed when they cannot be read."""
        try:
            prefs = smithbox_mod.map_prefs()
        except Exception:
            prefs = None
        if not prefs or prefs.get("rendering") is None:
            ctx.log.info("op %s load_maps: Smithbox's saved preferences could not be read - the first map may take "
                         "as long as the job allows", i)
            return {}
        havok = "skipped" if prefs.get("skip_havok") else "loaded" if prefs.get("skip_havok") is False else "unknown"
        if prefs["rendering"]:
            ctx.log.warn("op %s load_maps: Smithbox's saved preferences have Enable Model Rendering on (Havok %s), so "
                         "each map loads its models and textures, a minute or more for a big one: turn it off in "
                         "Smithbox's Preferences, Viewport. The first map may take 300 s. (Smithbox saves its "
                         "preferences when it closes, so a change made since may not show here.)", i, own(havok))
            return {"first_timeout": 300.0}
        ctx.log.info("op %s load_maps: Smithbox's saved preferences have model rendering off (Havok %s): 10 s a map "
                     "before it is skipped for now", i, own(havok))
        return {"first_timeout": 10.0}

    def _resolve_maps(self, maps: Sequence[str]) -> list[str]:
        """A job's map list with each family (`m10_*`, S45) replaced by the project's maps of that area, in order,
        each once. Ids the project does not have stay; open_maps and read_placements skip them."""
        fams = [m for m in maps if jobs.MAP_FAMILY_RX.fullmatch(m)]
        known = list(self.link.all_maps()) if fams else []
        out: list[str] = []
        for m in maps:
            for x in ([k for k in known if k.startswith(m[:-1])] if m in fams else [m]):
                if x not in out:
                    out.append(x)
        return out

    def _unused_names(self, ctx: _Ctx, i: int, o: dict) -> tuple[int, int | None]:
        """The entries of a text set that no row of a table names (S47), with their layers and, locally, their
        texts. Check 6 measures the table against the set's entries (a source of its own)."""
        text = o["text"]
        words = jobs.TEXT_WORDS[text]
        lang = self.language()
        from . import textdb as textdb_mod
        pairs = textdb_mod.TEXT_SETS.get(text) or ()
        if not any(self.textdb.has(c, lang) for c in dict.fromkeys(c for c, _ in pairs)):
            raise _Fail("%s are not imported yet - run Extract's guided row for them first" % words.capitalize())
        layers = self.textdb.layers(text, lang)
        names = self.textdb.names(text, lang)
        cols, rows = ctx.tables[o["rows"]]
        k = [c for c, _ in cols].index(o["key"])
        used = {r[k] for r in rows if isinstance(r[k], int) and not isinstance(r[k], bool)}
        out = [(n, layers[n], names.get(n)) for n in sorted(layers) if n not in used]
        ctx.tables[o["as"]] = (list(jobs.UNUSED_COLUMNS), out)
        ctx.sources[i] = _Source(text, len(layers), True)
        ctx.log.info("op %s unused_names: %s of %s entries of %s are named by no row of %s", i,
                     logbook.n(len(out)), logbook.n(len(layers)), own(text), own(o["rows"]))
        return len(out), len(layers)

    def _read_placements(self, ctx: _Ctx, i: int, o: dict) -> tuple[int, int | None]:
        if o["maps"] == "all":
            maps = list(self.link.loaded_maps())
            if not maps:
                with self._lock:
                    self._map_hint = "load the maps in Smithbox first"
                raise _Fail("no map is loaded in Smithbox - load the maps in Smithbox first")
        else:
            maps = self._resolve_maps(o["maps"])
            known = set(self.link.all_maps())
            # S57: a map load_maps skipped (it would not load) is left out here too, with a log line.
            skip = set(getattr(self.link, "skipped_maps", None) or ())
            skip = {m for m in skip if not self.link.is_loaded(m)} if skip and hasattr(self.link, "is_loaded") else skip
            if skip & set(maps):
                ctx.log.info("op %s read_placements: %s maps that did not load are left out", i,
                             logbook.n(len(skip & set(maps))))
            maps = [m for m in maps if m not in skip]
            have = [m for m in maps if m in known]
            if len(have) < len(maps):
                # A map id the project does not have is skipped; a map it has but has not loaded fails, clearly.
                ctx.log.info("op %s read_placements: %s of %s map ids are not maps of this Smithbox project and were "
                             "skipped", i, logbook.n(len(maps) - len(have)), logbook.n(len(maps)))
            maps = have
        rows: list[tuple] = []
        per_map: dict[str, int] = {}
        t0 = time.monotonic()
        ctx.on_op(i, "running", 0, len(maps), None)
        kept = sum(1 for m in maps if m in ctx.kept)
        if kept and o["maps"] != "all":
            ctx.log.info("op %s read_placements: %s of %s maps come from what was read and kept", i, logbook.n(kept),
                         logbook.n(len(maps)))
        for k, m in enumerate(maps):
            if ctx.cancel.is_set():
                raise _Cancelled()
            got = ctx.kept.get(m) if o["maps"] != "all" else None
            if got is None:
                got = self._placements_of(m)
                if ctx.progress is not None and o["maps"] != "all":
                    ctx.kept[m] = got
                    ctx.progress.add(m, got)
            rows.extend(got)
            n = len(got)
            per_map[m] = min(n, per_map.get(m, n))
            ctx.on_op(i, "running", k + 1, len(maps), round(time.monotonic() - t0, 1))
        ctx.tables[o["as"]] = (list(jobs.PLACEMENT_COLUMNS), rows)
        # Check 6: the placements of every map the job read, a map read twice counted once (the lower count).
        for m, n in per_map.items():
            ctx.placed[m] = min(n, ctx.placed.get(m, n))
        ctx.sources[i] = _Source(PLACEMENTS, None, False)
        if ctx.builtin:
            ctx.fetched += len(rows)
            ctx.unit = "placements"
        return len(maps), len(maps)

    def _placements_of(self, map_id: str) -> list[tuple]:
        """The placed characters of one loaded map, as rows of numbers (PLACEMENT_COLUMNS)."""
        out: list[tuple] = []
        for p in self.link.placements(map_id):
            row = (p.map, p.entity_id, p.npc_param_id, p.talk_id, p.model)
            if not all(_type_ok("int", v) for v in row):
                raise _Fail("the server sent a placement that is not numbers only")
            out.append(row)
        return out

    def _open_progress(self, ctx: _Ctx, card_id: str) -> None:
        """S63: a job that reads placements of named maps keeps them as it reads them; what an earlier run of the
        same job, on the same game and Smithbox, kept is taken up."""
        if not any(o["op"] == "read_placements" and o["maps"] != "all" for o in ctx.job.ops):
            return
        prov = self.provenance() or {}
        key = {"job_sha256": ctx.job.sha256, **{k: prov.get(k) for k in MAPS_KEY}}
        ctx.progress = _MapProgress(self._folder(card_id) / MAPS_FILE, key)
        ctx.kept = ctx.progress.load()
        if ctx.kept:
            ctx.log.info("%s maps read by an earlier run of this job are kept and not read again",
                         logbook.n(len(ctx.kept)))

    def _maps_read_later(self, ctx: _Ctx, i: int) -> set[str]:
        """The maps a read_placements after op i names, so load_maps can read each as soon as it loads (S63)."""
        out: set[str] = set()
        for o in ctx.job.ops[i + 1:]:
            if o["op"] == "read_placements" and o["maps"] != "all":
                out.update(self._resolve_maps(o["maps"]))
        return out

    def _read_now(self, ctx: _Ctx, map_id: str) -> None:
        """S63: read a map's placements as soon as it loads, and keep them on disk at once."""
        if map_id in ctx.kept or ctx.progress is None:
            return
        rows = self._placements_of(map_id)
        ctx.kept[map_id] = rows
        ctx.progress.add(map_id, rows)

    def _join_names(self, ctx: _Ctx, i: int, o: dict) -> tuple[int, int | None]:
        from . import textdb as textdb_mod
        text = o["text"]
        words = jobs.TEXT_WORDS[text]
        pairs = textdb_mod.TEXT_SETS.get(text) or ()
        if not pairs:
            raise _Fail("which text entries hold %s is not known, so join_names cannot run" % words)
        lang = self.language()
        if not any(self.textdb.has(c, lang) for c in dict.fromkeys(c for c, _ in pairs)):
            raise _Fail("%s are not imported yet - run Extract's guided row for them first" % words.capitalize())
        ids = self.textdb.ids(text, lang)
        cols, rows = ctx.tables[o["rows"]]
        k = [c for c, _ in cols].index(o["key"])
        # P3: the wrappers are ER01's leads, used only once the owner's own numbers resolve in them.
        wrappers = self.textdb.wrappers(text)
        numbers = {r[k] for r in rows if isinstance(r[k], int) and not isinstance(r[k], bool) and r[k] >= 0}
        if not numbers:
            raise _Fail("none of the rows joined has a name number (0 or above), so the wrapper leads of %s "
                        "cannot be verified - join_names stops" % words)
        resolved = len(numbers & ids)
        if resolved * 2 < len(numbers):
            raise _Fail("only %s%% of the rows' name numbers (%s of %s) resolve in the wrappers %s of %s: at least "
                        "half must, so the leads do not hold for this data and join_names stops"
                        % (resolved * 100 // len(numbers), "{:,}".format(resolved), "{:,}".format(len(numbers)),
                           jobs._and([str(w) for w in wrappers]), words))
        share = math.floor(resolved * 1000 / len(numbers)) / 1000      # never above what resolved
        record = ctx.names.get(text)
        if record is None or share < record["resolved"]:
            ctx.names[text] = {"wrappers": wrappers, "verified": True, "resolved": share}
        ctx.log.info("op %s join_names: the wrapper leads %s verified, %s of %s name numbers resolve (%s%%)", i,
                     own(jobs._and([str(w) for w in wrappers])), logbook.n(resolved), logbook.n(len(numbers)),
                     logbook.n(resolved * 100 // len(numbers)))
        names = self.textdb.names(text, lang)
        layers = self.textdb.layers(text, lang)
        out = [tuple(r) + (r[k] in ids, layers.get(r[k], -1) if r[k] in ids else -1,
                           names.get(r[k]) if r[k] in ids else None) for r in rows]
        ctx.tables[o["as"]] = (list(cols) + list(jobs.JOIN_COLUMNS), out)
        return len(out), len(rows)

    def _count(self, ctx: _Ctx, o: dict) -> tuple[int, int | None]:
        cols, rows = ctx.tables[o["rows"]]
        keep = _predicate(o.get("where"), cols)
        by = list(o.get("by") or [])
        idx = [[c for c, _ in cols].index(b) for b in by]
        counts: dict[tuple, int] = {}
        for r in rows:
            if keep(r):
                key = tuple(r[j] for j in idx)
                counts[key] = counts.get(key, 0) + 1
        if not by:
            out = [(counts.get((), 0),)]
        else:
            out = [k + (v,) for k, v in sorted(counts.items(), key=lambda kv: _sort_key(kv[0]))]
        ctx.tables[o["as"]] = ([cols[j] for j in idx] + [("count", "int")], out)
        return len(out), len(rows)

    def _select(self, ctx: _Ctx, tables: list[str], columns: dict | None) -> list[tuple[str, list, list]]:
        out = []
        for t in tables:
            cols, rows = ctx.tables[t]
            want = (columns or {}).get(t)
            if want:
                idx = [[c for c, _ in cols].index(c) for c in want]
                out.append((t, [cols[j] for j in idx], [tuple(r[j] for j in idx) for r in rows]))
            else:
                out.append((t, list(cols), list(rows)))
        return out

    def _write_local(self, ctx: _Ctx, o: dict) -> tuple[int, int | None]:
        chosen = self._select(ctx, o["tables"], o.get("columns"))
        data = _local_bytes(ctx.job.id, chosen)
        folder_id = "extract" if ctx.builtin else ctx.job.id
        try:
            path = paths_mod.local_file(self.paths, folder_id, o["name"])
            path.parent.mkdir(parents=True, exist_ok=True)
            fileio.write_atomic(path, data)
        except ValueError:
            raise _Fail("not a file name DataPiler writes") from None
        except OSError as e:
            raise _Fail("the workspace file could not be written: %s" % logbook.why(e)) from None
        name = o["name"] + ".json"
        ctx.local.append(name)
        ctx.log.info("workspace file %s written: %s tables, %s bytes", own(name), logbook.n(len(chosen)),
                     logbook.n(len(data)))
        events.emit("local.written", job=own(ctx.job.id), size=len(data))
        return 1, 1

    def _write_share(self, ctx: _Ctx, i: int, o: dict) -> tuple[int, int | None]:
        try:
            from .status import ProvenanceMissing
        except ImportError:                                  # pragma: no cover - CORE's module is always there
            ProvenanceMissing = ValueError                   # noqa: N806
        try:
            prov = dict(self.provenance())
        except ProvenanceMissing as e:
            raise _Fail("the provenance block is not complete: %s" % e) from None
        prov["names"] = {k: dict(v) for k, v in sorted(ctx.names.items())}
        chosen = self._select(ctx, o["tables"], o["columns"])
        tables = []
        declared: dict[str, list[str]] = {}
        coverage: dict[str, tuple[str | None, int, str] | None] = {}
        for t, cols, rows in chosen:
            if any(typ not in ("int", "number", "bool") for _, typ in cols):
                raise _Fail("a column of local text cannot go into a share file")
            tables.append({"name": t, "columns": [{"name": c, "type": typ} for c, typ in cols],
                           "rows": [list(r) for r in rows]})
            declared[t] = [c for c, _ in cols]
            coverage[t] = self._coverage(ctx, t, declared[t])
        data = self.guard.build(job_id=ctx.job.id, job_sha256=ctx.job.sha256, provenance=prov, tables=tables,
                                notes=list(o.get("notes") or []))
        results = self.guard.check(data, declared=declared, coverage=coverage)
        if not all(r.ok for r in results):
            # The guard logs the refusal and writes nothing.
            self.guard.write(self.paths.share, o["name"], data, declared=declared, coverage=coverage)
        ctx.share = (i, o["name"], data, declared, coverage)
        return 1, 1

    @staticmethod
    def _coverage(ctx: _Ctx, table: str, columns: list[str]) -> tuple[str | None, int, str] | None:
        """What check 6 measures for one share table (DP8, settled S19), as (column, of, source): source the game
        table it came from (a param, or PLACEMENTS), which the guard measures with the file's other tables from it;
        of that game table's rows. A table of counts alone (a count's `count`, without its groups) is not measured:
        None. Every other table is measured by its rows, one per row of its source or one per group of a count or a
        distinct (column None), but for a table that keeps a param's row id when no row id repeats among the rows
        its fetch_rows read: then by its distinct ids (column `id`), so that rows shared in two tables count once.
        Placements are always measured by their rows, as their entity ids can repeat. A table whose source's rows
        were not counted is measured against 0, so it fails unless it is empty."""
        lin = ctx.job.lineage.get(table)
        if lin is not None and not lin.per_row and list(columns) == ["count"]:
            return None
        src = ctx.sources.get(lin.source) if lin is not None and lin.source is not None else None
        if lin is None or src is None:
            return (None, 0, UNKNOWN_SOURCE)
        if src.table == PLACEMENTS:
            return (None, sum(ctx.placed.values()), PLACEMENTS)
        if src.table in jobs.TEXTS:
            # DP17 (settled S48): what unused_names makes holds name numbers and layers only, never a text, and is not
            # held to check 6's half.
            return None
        of = src.of if src.of is not None else 0
        if src.unique and lin.id_col is not None and lin.id_col in columns:
            return (lin.id_col, of, src.table)
        return (None, of, src.table)


def _guard_why(e: GuardFailed) -> str:
    """The card's and the log's words for a guard failure: the check, the place and what the check is about, never
    the value."""
    return "the guard refused the share file: %s (%s)" % (e, GUARD_WORDS.get(e.check, "a check"))


def _sort_key(key: tuple) -> tuple:
    """Numbers and flags in order; a missing value last."""
    return tuple((0, v) if v is not None else (1, 0) for v in key)
