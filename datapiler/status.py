"""The Status cards, the pills, the block line and the provenance block (build plan §4.3).

Status reads are made on each /api/state with the caches of game.py and smithbox.py; the running Smithbox comes from
smithbox's watcher (DP15). The port check is LINK's port_answers, so every touch of 127.0.0.1:22720 is in link.py.
Real folders go to the page only in a check's "detail" (the "?" title) and a "use" offer, masked by the API while
Mask paths on this page is on (DP14); the text shows placeholders."""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Protocol

from pathlib import Path

from . import VERSION, events, game, link, paths, settings as settings_mod, smithbox
from .game import GameRunning
from .logbook import Own, own
from .settings import Settings

SERVER = "%s:%d" % (link.HOST, link.PORT)
PORT_CACHE_S = 5.0
SWITCH_OFF_LINE = ("Smithbox's server is still switched on, and it has no password: set "
                   "System_Enable_Soapstone_Server to false in Smithbox's Startup.json and restart Smithbox.")


class LinkView(Protocol):
    state: str
    def stats(self) -> dict: ...
    def would_call(self) -> list[dict]: ...


class ProvenanceMissing(ValueError):
    """str(e) names what is missing in DataPiler's words: "the game's version is not known - set the game folder"."""


NOT_SEEN = "DataPiler cannot yet see which project Smithbox has open: check in Smithbox that it is this one."
OPEN_LEAD = ("A lead: the record's mark is normally, not always, the project open (it moves when a project is "
             "started).")
EXPANSION_UNSET = ("whether the expansion is installed is not stated yet - set Expansion installed in Settings (yes "
                   "or no)")


def _check(cid: str, ok: object, text: str, fix: str | None = None, detail: str | None = None) -> dict:
    return {"id": cid, "ok": ok, "text": text, "fix": fix, "detail": detail}


def _offer(check: dict, key: str, folder: str | None) -> dict:
    """A Status line that offers one folder with Use (DP15): the page saves it through /api/settings/one."""
    if folder:
        check["use"] = {"key": key, "path": folder, "shown": folder}
    return check


def _places(n: int) -> str:
    return "Found 1 place - confirm it in Settings" if n == 1 else "Found %d places - confirm them in Settings" % n


def _missing(folder: str) -> bool:
    if not folder:
        return True
    try:
        return not os.path.isdir(folder)
    except (OSError, ValueError):
        return True


class Status:
    def __init__(self, settings: Callable[[], Settings], link: Callable[[], "LinkView | None"],
                 port_answers: Callable[[], bool | None]):
        """link is a callable because the Link is made after the Status (it takes status.game_running)."""
        self._settings = settings
        self._link = link
        self._port_answers = port_answers
        self._root: Path = settings_mod.ROOT
        self._folders = None
        self._lock = threading.Lock()
        self._port: tuple[float, bool | None] | None = None
        self._was_on = False
        self._calls = 0
        self._last_call: str | None = None
        self._last_methods: list[str] = []
        self._unsub = [events.subscribe("link.call", self._on_call), events.subscribe("link.state", self._on_state)]

    # ---------------------------------------------------------------------------------------------- events

    def _on_call(self, topic: str, data: dict) -> None:
        method = data.get("method")
        with self._lock:
            self._calls += 1
            self._last_call = time.strftime("%H:%M:%S")
            if isinstance(method, Own) and self._last_methods[-1:] != [str(method)]:
                self._last_methods = (self._last_methods + [str(method)])[-2:]

    def _on_state(self, topic: str, data: dict) -> None:
        if data.get("state") in ("on", "blocked"):
            with self._lock:
                self._was_on = True

    def close(self) -> None:
        for u in self._unsub:
            u()

    def attach(self, *, root: Path | None = None, folders=None) -> None:
        """The API gives Status DataPiler's folder (the project rules, S32) and the session's Detect (its places in
        memory, "Found n places"). Without them Status runs as in 0.1."""
        if root is not None:
            self._root = Path(root)
        if folders is not None:
            self._folders = folders

    def _found(self, want: str) -> list:
        f = self._folders
        if f is None:
            return []
        try:
            return list(f.found(want))
        except Exception:
            return []

    # ---------------------------------------------------------------------------------------------- reads

    def game_running(self) -> GameRunning:
        return game.running(self._settings().game_dir)

    def project_ok(self) -> tuple[bool, Own]:
        """False with the reason when the project folder is unset, missing, the game's folder or inside it, a folder
        that holds the game's folder, or DataPiler's folder or inside it (S32)."""
        s = self._settings()
        if s.project_dir and paths.is_inside(s.project_dir, str(self._root)):
            if paths.is_inside(str(self._root), s.project_dir):
                return False, own("the project folder is DataPiler's own folder - choose one outside it")
            return False, own("the project folder is inside DataPiler's folder - choose one outside it")
        if not s.project_dir:
            return False, own("the project folder is not set - set it in Settings")
        if not s.game_dir:
            return False, own("the game folder is not set, so the project folder cannot be checked against it")
        try:
            if not os.path.isdir(s.project_dir):
                return False, own("the project folder does not exist")
        except OSError:
            return False, own("the project folder could not be read")
        if paths.is_inside(s.project_dir, s.game_dir):
            if paths.is_inside(s.game_dir, s.project_dir):
                return False, own("the project folder is the game's folder - choose one outside it")
            return False, own("the project folder is inside the game's folder - choose one outside it")
        if paths.is_inside(s.game_dir, s.project_dir):
            return False, own("the project folder holds the game's folder - choose one outside it")
        return True, own("outside the game's folder")

    def _link_state(self) -> str:
        lk = self._link()
        if lk is None:
            return "off"
        try:
            return str(lk.state)
        except Exception:
            return "off"

    def port_answers(self) -> bool | None:
        now = time.monotonic()
        with self._lock:
            if self._port is not None and now - self._port[0] < PORT_CACHE_S:
                return self._port[1]
        try:
            v = self._port_answers()
        except Exception:
            v = None
        with self._lock:
            self._port = (now, v)
        return v

    def pills(self) -> dict:
        s = self._settings()
        run = smithbox.running(s.smithbox_dir)      # DP15: any Smithbox*.exe process, whatever the Settings say
        if run:
            sb = "running"
        elif smithbox.installed(s.smithbox_dir):
            sb = "not_running"
        else:
            sb = "not_found"
        g = self.game_running()
        gp = "unknown" if g.why == game.UNREADABLE else ("running" if g.running else "closed")
        return {"smithbox": sb, "game": gp, "link": self._link_state()}

    def block_line(self) -> str | None:
        g = self.game_running()
        if g.running:
            if g.why == game.UNREADABLE:
                return "The process list could not be read, so the game counts as running - the server link waits."
            return "The game is running - the server link waits until it closes."
        if self._link_state() == "blocked":
            return "The server link is blocked - it goes on once the game has been closed for a moment."
        return None

    def cards(self) -> dict:
        s = self._settings()
        return {"smithbox": self._smithbox_card(s), "game": self._game_card(s),
                "project": self._project_card(), "link": self._link_card()}

    def _smithbox_card(self, s: Settings) -> list[dict]:
        out = []
        found = self._found("smithbox") if _missing(s.smithbox_dir) else []
        if found:
            out.append(_offer(_check("installed", "warn", _places(len(found)), "Open Settings and press Use.",
                                     s.smithbox_dir or None), "smithbox_dir",
                              found[0].value if len(found) == 1 else None))
        elif not s.smithbox_dir:
            out.append(_check("installed", False, "Not set", "Set the Smithbox folder in Settings."))
        elif smithbox.installed(s.smithbox_dir):
            out.append(_check("installed", True, "Installed in <SMITHBOX>", None, s.smithbox_dir))
        else:
            out.append(_check("installed", False, "Smithbox's exe is not in <SMITHBOX>",
                              "Check the Smithbox folder in Settings: it holds Smithbox.Vulkan.exe or another "
                              "Smithbox*.exe.", s.smithbox_dir))
        out.append(self._build_check(s))
        runs = smithbox.seen()
        if runs is None:
            out.append(_check("running", None, "Not known - the process list could not be read"))
        elif runs:
            names = []
            for r in runs:
                n = r.name if smithbox.is_exe_name(r.name) else "a Smithbox exe"
                names.append(n + (" · build " + r.build if r.build else ""))
            folders = [r.folder for r in runs if r.folder]
            detail = "; ".join(dict.fromkeys(folders)) or None
            if len(runs) == 1:
                out.append(_check("running", True, "Running: " + names[0], None, detail))
            else:
                out.append(_check("running", True, "Running: %d Smithbox processes" % len(runs), "; ".join(names),
                                  detail))
            other = [f for f in dict.fromkeys(folders) if s.smithbox_dir and not _same(f, s.smithbox_dir)]
            if other and not _missing(s.smithbox_dir):
                c = _check("elsewhere", "warn", "Smithbox runs from another folder than <SMITHBOX>",
                           "Press Use to switch to it, or leave the folder as it is.", "; ".join(other))
                out.append(_offer(c, "smithbox_dir", other[0] if len(other) == 1 and smithbox.installed(other[0])
                                  else None))
        else:
            out.append(_check("running", False, "Not running", "Start Smithbox and open your project."))
        path = smithbox.startup_json()
        sw = smithbox.read_switch(path)
        detail = str(path) if path is not None and path.is_file() else None
        if sw is True:
            out.append(_check("switch", True, "Its server is switched on",
                              "It has no password: switch it off when you are done.", detail))
        elif sw is False:
            out.append(_check("switch", False, "Its server is switched off",
                              "Set System_Enable_Soapstone_Server to true in Smithbox's Startup.json and restart "
                              "Smithbox.", detail))
        else:
            out.append(_check("switch", None, "The server's switch could not be read",
                              "It is System_Enable_Soapstone_Server in Smithbox's Startup.json, read and never "
                              "written.", detail))
        port = self.port_answers()
        if port is True:
            out.append(_check("port", True, "The server answers on " + SERVER))
        elif port is False:
            out.append(_check("port", False, "The server does not answer on " + SERVER,
                              "Start Smithbox with its server switched on."))
        else:
            out.append(_check("port", None, "Not checked while the game runs"))
        ok, why = self.project_ok()
        if s.project_dir:
            # What DataPiler checks is the folder typed in Settings, not the project Smithbox has open: where
            # Smithbox records that is not established yet (build plan §10, P1; smithbox.open_project).
            out.append(_check("project", ok, "Project folder set in Settings: <PROJECT>",
                              ("Outside the game's folder. " + NOT_SEEN if ok else why[:1].upper() + why[1:] + "."),
                              s.project_dir))
        else:
            out.append(_check("project", False, "No project folder set",
                              "Set the project folder in Settings: Smithbox's project, outside the game's folder."))
        return out

    @staticmethod
    def _build_check(s: Settings) -> dict:
        b = smithbox.build(s.smithbox_dir)
        if b:
            return _check("build", True, "Build " + b)
        if smithbox.builds_differ(s.smithbox_dir):
            rs = smithbox.reports(s.smithbox_dir)
            return _check("build", "warn", "Its exes' builds differ, and none runs",
                          ", ".join("%s %s" % (r.name, r.build) for r in rs if r.build)
                          + ". Start Smithbox: the running one's build is read.")
        return _check("build", None, "Its build is not known",
                      "Read from the Smithbox exe's version resource, on Windows.")

    def _game_card(self, s: Settings) -> list[dict]:
        out = []
        found = self._found("game") if _missing(s.game_dir) else []
        if found:
            out.append(_offer(_check("folder", "warn", _places(len(found)), "Open Settings and press Use.",
                                     s.game_dir or None), "game_dir", found[0].value if len(found) == 1 else None))
        elif not s.game_dir:
            out.append(_check("folder", False, "Not set", "Set the game folder in Settings."))
        elif game.exe_path(s.game_dir) is not None:
            out.append(_check("folder", True, "Folder <GAME>", None, s.game_dir))
        else:
            out.append(_check("folder", False, "eldenring.exe is not in <GAME>", "Check the game folder in Settings.",
                              s.game_dir))
        v = game.version(s.game_dir)
        out.append(_check("version", True, "Version " + v) if v else _check(
            "version", None, "Its version is not known", "Read from eldenring.exe's version resource, on Windows."))
        out.append(self._expansion_check(s))
        g = self.game_running()
        if not g.running:
            out.append(_check("running", True, "Not running"))
        elif g.why == game.UNREADABLE:
            out.append(_check("running", False, "Not known - the process list could not be read",
                              "It counts as running until the list can be read."))
        else:
            out.append(_check("running", False, "Running" + (" (" + str(g.why) + ")" if g.why else ""),
                              "Close the game: the server link waits until it closes."))
        sha = game.regulation_sha256(s.game_dir)
        if sha:
            out.append(_check("regulation", True, "regulation.bin's sha256 read (%s...%s)" % (sha[:4], sha[-4:])))
        else:
            out.append(_check("regulation", False, "regulation.bin's sha256 is not known",
                              "Set the game folder in Settings."))
        return out

    @staticmethod
    def _expansion_check(s: Settings) -> dict:
        """The owner's statement decides (P2, settled S21); a file check, once its marker files are confirmed, only
        adds a hint, and never changes what the provenance records."""
        files = game.expansion(s.game_dir)
        hint = None
        if files is not None:
            hint = ("A hint only: the expansion's files are %s in <GAME>." % ("present" if files else "not present"))
        if s.expansion not in ("yes", "no"):
            return _check("expansion", False, "Whether the expansion is installed is not stated yet",
                          "Set Expansion installed in Settings: share files wait for it." + (" " + hint if hint
                                                                                            else ""))
        stated = s.expansion == "yes"
        text = "Installed, as stated in Settings" if stated else "Not installed, as stated in Settings"
        if files is not None and files != stated:
            return _check("expansion", True, text, hint + " Check what Settings says; it is what share files record.")
        return _check("expansion", True, text, hint)

    def _project_card(self) -> list[dict]:
        ok, why = self.project_ok()
        s = self._settings()
        found = self._found("project") if _missing(s.project_dir) else []
        if found:
            first = _check("outside_game", "warn", _places(len(found)), "Open Settings and press Use.",
                           s.project_dir or None)
        elif ok:
            first = _check("outside_game", True, "The folder set in Settings, <PROJECT>, is outside the game's folder",
                           None, s.project_dir)
        else:
            first = _check("outside_game", False, why[:1].upper() + why[1:],
                           "Choose a project folder outside the game's and DataPiler's.")
        return [first, self._open_project(s)]

    @staticmethod
    def _open_project(s: Settings) -> dict:
        """A lead (O48; smithbox-projects.md §4): the record's AutoSelect mark, normally the project open."""
        try:
            marked = smithbox.open_project()
        except Exception:
            marked = None
        if marked is None:
            return _check("open_project", None, "Which project Smithbox has open is not known yet",
                          NOT_SEEN + " Switching the server link on asks you once.")
        if s.project_dir and _same(marked, s.project_dir):
            return _check("open_project", True, "Smithbox's record marks <PROJECT> as the project it opens",
                          OPEN_LEAD + " Switching the server link on still asks you once.")
        return _check("open_project", "warn", "Smithbox's record marks another project to open",
                      OPEN_LEAD + " Check in Smithbox which project is open.", marked)

    def _link_card(self) -> dict:
        lk = self._link()
        state = self._link_state()
        with self._lock:
            stats = {"calls": self._calls, "last_call": self._last_call, "last_methods": list(self._last_methods)}
            was_on = self._was_on
        would: list[dict] = []
        if lk is not None:
            try:
                got = lk.stats()
                if isinstance(got, dict):
                    stats.update({k: got[k] for k in ("calls", "last_call", "last_methods") if k in got})
            except Exception:
                pass
            try:
                would = list(lk.would_call())
            except Exception:
                would = []
        if state in ("on", "blocked"):
            with self._lock:
                self._was_on = was_on = True
        after = None
        if was_on and state in ("off", "no_libs"):
            try:
                if smithbox.read_switch(smithbox.startup_json()) is True:
                    after = SWITCH_OFF_LINE
            except Exception:
                after = None
        return {"state": state, "calls": stats["calls"], "last_call": stats["last_call"],
                "last_methods": stats["last_methods"], "would_call": would, "after": after}

    # ---------------------------------------------------------------------------------------------- provenance

    @staticmethod
    def _running_build() -> str | None:
        """The build of the Smithbox that runs, whatever its folder: the one that serves the link, which may not be
        the folder in Settings (the correctness review's C1). None when none runs or the list cannot be read (the
        folder's rule then applies). Raises ProvenanceMissing when the running exe's build cannot be read, or when
        Smithbox processes of different builds run."""
        runs = smithbox.seen()
        if not runs:
            return None
        builds = [r.build for r in runs]
        if any(not b for b in builds):
            raise ProvenanceMissing("Smithbox's build is not known - the running Smithbox exe's version resource could "
                                    "not be read (it is read on Windows only)")
        if len(set(builds)) > 1:
            raise ProvenanceMissing("Smithbox's build is not known - Smithbox processes of different builds are "
                                    "running: close one, so the one that serves the link is known")
        return builds[0]

    def provenance(self) -> dict:
        """{"game_version", "regulation_sha256", "expansion", "expansion_source", "language", "smithbox_build",
        "datapiler", "date"}; date is today's local date. expansion is the owner's statement in Settings, and
        expansion_source says so ("owner"); smithbox_build is the running Smithbox's, whatever its folder, else the
        build of the Smithbox folder's exes; the runner adds "names" (P3). Raises ProvenanceMissing."""
        s = self._settings()
        v = game.version(s.game_dir)
        if not v:
            if game.exe_path(s.game_dir) is None:
                raise ProvenanceMissing("the game's version is not known - set the game folder")
            raise ProvenanceMissing("the game's version is not known - eldenring.exe's version resource could not "
                                    "be read (it is read on Windows only)")
        sha = game.regulation_sha256(s.game_dir)
        if not sha:
            raise ProvenanceMissing("regulation.bin's sha256 is not known - set the game folder")
        if s.expansion not in ("yes", "no"):
            raise ProvenanceMissing(EXPANSION_UNSET)
        b = self._running_build()
        if b is None:
            b = smithbox.build(s.smithbox_dir)
        if not b:
            if smithbox.exe_path(s.smithbox_dir) is None:
                raise ProvenanceMissing("Smithbox's build is not known - set the Smithbox folder (the one that holds "
                                        "Smithbox.Vulkan.exe or another Smithbox*.exe)")
            if smithbox.builds_differ(s.smithbox_dir):
                raise ProvenanceMissing("Smithbox's build is not known - its exes' builds differ: start Smithbox, so "
                                        "the running one's build is read")
            raise ProvenanceMissing("Smithbox's build is not known - the Smithbox exe's version resource could not "
                                    "be read (it is read on Windows only)")
        return {"game_version": v, "regulation_sha256": sha, "expansion": s.expansion == "yes",
                "expansion_source": "owner", "language": s.language, "smithbox_build": b, "datapiler": VERSION,
                "date": time.strftime("%Y-%m-%d")}


def _same(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a.replace("/", "\\").rstrip("\\").casefold() == b.replace("/", "\\").rstrip("\\").casefold():
        return True
    return paths.is_inside(a, b) and paths.is_inside(b, a)
