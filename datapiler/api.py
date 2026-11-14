"""The endpoints of build plan §5, building their JSON from the modules.

Words in answers are DataPiler's, masked. No real path reaches the page but a Status check's "detail" and the
Settings form's own values (what the owner typed); Copy path puts a share file's path on the clipboard only."""

from __future__ import annotations

import base64
import binascii
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import (VERSION, detect as detect_mod, dirs as dirs_mod, events, fileio, link as link_mod, logbook,
               paths as paths_mod, settings as settings_mod, winapi)
from .logbook import own
from .paths import Paths
from .server import Bad
from .settings import Session, Settings, SettingsError

SERVER = "%s:%d" % (link_mod.HOST, link_mod.PORT)
SHARE_MAX = 4 * 1024 * 1024          # the guard's MAX_BYTES (guard.py); read from it when it imports
FILE_RX = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.json")
SAFE_NAME_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
WORKSPACE_FILES = ("textdb.sqlite",)
WORKSPACE_MOVES = ("The workspace moves at the next start; until then DataPiler keeps using the one it has. It does "
                   "not move its files: before you start it again, move textdb.sqlite, inbox, imported and local from "
                   "the old workspace into the new one, or the text exports are to be imported again.")
PROJECT_ASK = ("Is the project open in Smithbox the project folder set in Settings? DataPiler cannot yet see which "
               "project Smithbox has open, and the server link must never read a project in the game's own folder. "
               "OK switches the link on; you are asked once a session.")
LEVELS = logbook.LEVELS
ONE_KEYS = ("smithbox_dir", "game_dir", "project_dir", "expansion", "mask_paths")
FOLDER_WANTS = {"smithbox_dir": "smithbox", "game_dir": "game", "project_dir": "project"}
_PATH_CONTROL_RX = re.compile(r"[\x00-\x1f\x7f]")

# The owner rules of S11 for one log line (the guard's check 4 as it reads a line: the lines are masked already, so
# a placeholder such as <WORKSPACE>\inbox and the page's own address pass).
DRIVE_RX = re.compile(r"(?<![A-Za-z])[A-Za-z]:([\\/]|$)")
UNC_RX = re.compile(r"\\\\[^\\\s]")
HOME_RX = re.compile(r"~[\\/]")
V4_RX = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)(?!\w)")
V6_RX = re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9A-Fa-f]{1,4})?(?![\w:])")


@dataclass
class Live:
    """What changes while DataPiler runs: the settings, the folders they give, the session's switches."""
    root: Path
    settings: Settings
    paths: Paths
    session: Session


def _ip_in(text: str) -> bool:
    for m in V4_RX.finditer(text):
        if m.group(0) != "127.0.0.1":
            return True
    for m in V6_RX.finditer(text):
        s = m.group(0)
        if "::" in s or s.count(":") == 7:
            import ipaddress
            try:
                ipaddress.ip_address(s)
                return True
            except ValueError:
                pass
    return False


# What to do about each reason a queued Extract row waits (the runner's LINK_WAITS; design §2: say where to fix it).
EXTRACT_FIX = {
    "the server link is off": "switch it on in Status",
}


def extract_block(rows: list) -> str | None:
    """The line under the top bar for an Extract run whose server rows wait (design §2), or None."""
    for r in rows:
        if not isinstance(r, dict) or r.get("state") != "queued":
            continue
        why = r.get("grey")
        if isinstance(why, str) and why:
            why = why.rstrip(".")
            fix = EXTRACT_FIX.get(why)
            return "Extract waits: %s%s." % (why, " - " + fix if fix else "")
    return None


def owner_hit(text: str, words: list[str]) -> bool:
    """Whether a log line breaks the owner rules: a drive letter, a network path, a home folder, the user's or the
    PC's name as a whole word (case-folded, with `_`, `-` or nothing between its parts: the guard's check 4
    patterns, `guard.owner_patterns`), or an IP address other than 127.0.0.1."""
    from .guard import owner_patterns       # JOBS's module, read at the check as the other guard reads are

    if DRIVE_RX.search(text) or UNC_RX.search(text) or HOME_RX.search(text):
        return True
    folded = text.casefold()
    if any(rx.search(folded) for rx in owner_patterns([w for w in words if w])):
        return True
    return _ip_in(text)


def line_text(line: dict) -> str:
    return "%s  %-5s  %-8s %s" % (line["t"], line["level"], line["src"], line["msg"])


def _bool(body: dict, key: str, default: bool = False) -> bool:
    v = body.get(key, default)
    if not isinstance(v, bool):
        raise Bad("%s must be true or false" % key)
    return v


def _int_or_none(body: dict, key: str) -> int | None:
    v = body.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise Bad("%s must be a whole number or null" % key)
    return v


def _str(body: dict, key: str, limit: int = 256) -> str:
    v = body.get(key, "")
    if not isinstance(v, str) or len(v) > limit:
        raise Bad("%s must be text" % key)
    return v


class Api:
    def __init__(self, *, live: Live, status, link, runner, textdb, guard, inbox, catalogue,
                 stop: Callable[[], None], libs: bool, updates=None, folders=None):
        """updates: UPDATE's update.Updater, reached only through the three update routes (S27); folders: the
        session's detect.Folders. Either may be None: the update routes then answer 404, Detect finds nothing."""
        self.updates = updates
        self.folders = folders
        self.live = live
        if hasattr(status, "attach"):
            status.attach(root=live.root, folders=folders)
        _learn_recent(live.settings)
        self.status = status
        self.link = link
        self.runner = runner
        self.textdb = textdb
        self.guard = guard
        self.inbox = inbox
        self.catalogue = catalogue
        self.stop = stop
        self.libs = libs
        self.outputs_rev = 0
        self._lock = threading.Lock()
        self._log = logbook.get("page")
        # Outputs' guard results, per share file: (mtime_ns, size, text generation) -> (ok, first failed check)
        self._passed: dict[str, tuple[tuple[int, int, int], bool, int | None]] = {}
        self._text_gen = 0
        self._unsub = [events.subscribe(t, self._bump) for t in ("inbox.import", "local.written", "share.written")]
        self._unsub.append(events.subscribe("textdb.changed", self._on_text))

    def close(self) -> None:
        """As 0.1, then updates.close() and folders.close() when given."""
        for u in self._unsub:
            u()
        for part in (self.updates, self.folders):
            if part is not None:
                try:
                    part.close()
                except Exception as e:
                    self._log.warn("a part did not close cleanly: %s", logbook.why(e))

    def _bump(self, topic: str, data: dict) -> None:
        with self._lock:
            self.outputs_rev += 1

    def _on_text(self, topic: str, data: dict) -> None:
        """New text can make a share file fail check 3: every file is checked again."""
        with self._lock:
            self._text_gen += 1
            self._passed.clear()
            self.outputs_rev += 1

    # ------------------------------------------------------------------------------------------------ GET

    def get(self, path: str, query: dict[str, str]) -> tuple[int, object]:
        if path == "/api/state":
            return 200, self.state()
        if path == "/api/catalogue":
            return 200, self.catalogue.public()
        if path == "/api/outputs":
            return 200, self.outputs()
        if path == "/api/share":
            return 200, self.share(query.get("name", ""))
        if path == "/api/log":
            return 200, self.log_lines(query.get("after", "0"))
        if path == "/api/settings":
            return 200, self.settings_view()
        if path == "/api/imported":
            return 200, self.imported()
        # UPDATE's routes (build plan 0.2 §3.3): forwarded as they are, and nothing else of api.py reaches update.py.
        if path == "/api/update":
            if self.updates is None:
                return 404, {"error": "not found"}
            return 200, self.updates.get()
        if path == "/api/update-result":
            if self.updates is None:
                return 404, {"error": "not found"}
            return 200, self.updates.result()
        return 404, {"error": "not found"}

    def state(self) -> dict:
        jobs = self.runner.cards()
        extract = dict(self.runner.extract_state())
        if "inbox" not in extract:
            try:
                extract["inbox"] = self.inbox.state()
            except Exception:
                extract["inbox"] = []
        status = self.status.cards()
        if self.live.settings.mask_paths:
            _mask_cards(status)
        block = self.status.block_line()
        if block is None:
            for j in jobs:
                if j.get("state") == "waiting" and j.get("wait"):
                    block = "A job waits: %s." % str(j["wait"]).rstrip(".")
                    break
        if block is None:
            block = extract_block(extract.get("rows") or [])
        state = getattr(self.link, "state", "off") if self.link is not None else "off"
        self.live.session.link = state in ("on", "blocked")
        return {
            "version": VERSION,
            "pills": self.status.pills(),
            "block": block,
            "status": status,
            "extract": extract,
            "jobs": jobs,
            "outputs_rev": self.outputs_rev,
            "session": {"link": self.live.session.link, "debug": self.live.session.debug, "libs": self.libs},
        }

    def _file(self, base: Path, f: Path, made_by: dict, default: str | None) -> dict | None:
        try:
            st = f.stat()
        except OSError:
            return None
        rel = f.relative_to(base).as_posix()
        if not all(SAFE_NAME_RX.fullmatch(part) for part in rel.split("/")):
            return None
        by = made_by.get(rel)
        return {"name": rel, "size": st.st_size, "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                "made_by": str(by) if by is not None else default, "mtime": st.st_mtime}

    def outputs(self) -> dict:
        p = self.live.paths
        try:
            made_by = dict(self.runner.made_by())
        except Exception:
            made_by = {}
        work: list[dict] = []
        for name in WORKSPACE_FILES:
            f = p.workspace / name
            if f.is_file():
                item = self._file(p.workspace, f, made_by, "guided import")
                if item:
                    work.append(item)
        for folder, default in ((p.local, None), (p.imported, "guided import")):
            if not folder.is_dir():
                continue
            for f in sorted(folder.rglob("*.json")):
                if f.is_file():
                    item = self._file(p.workspace, f, made_by, default)
                    if item:
                        work.append(item)
        share: list[dict] = []
        if p.share.is_dir():
            for f in sorted(p.share.glob("*.json")):
                if f.is_file() and FILE_RX.fullmatch(f.name):
                    item = self._file(p.share, f, made_by, None)
                    if item:
                        # The guard's answer now, not when the file was written: a file DataPiler did not write,
                        # one changed since, or one that fails check 3 after a new text import is never shown as
                        # passing (the page lists it apart).
                        item["ok"], item["failed"] = self._passes(f)
                        share.append(item)
        for lst in (work, share):
            lst.sort(key=lambda x: -x["mtime"])
            for x in lst:
                x.pop("mtime", None)
        return {"workspace": work, "share": share}

    def _share_path(self, name: str) -> Path:
        if not isinstance(name, str) or not FILE_RX.fullmatch(name):
            raise Bad("not a share file's name")
        f = self.live.paths.share / name
        if not f.is_file():
            raise Bad("no such share file")
        return f

    @staticmethod
    def _cap() -> int:
        try:
            from . import guard as guard_mod
            return int(getattr(guard_mod, "MAX_BYTES", SHARE_MAX))
        except ImportError:
            return SHARE_MAX

    @staticmethod
    def _declared(data: bytes) -> dict[str, list[str]]:
        """The tables and columns the file itself names, as the guard's check 1 takes them."""
        declared: dict[str, list[str]] = {}
        try:
            import json
            doc = json.loads(data.decode("utf-8"))
            for t in doc.get("tables", []) if isinstance(doc, dict) else []:
                if isinstance(t, dict) and isinstance(t.get("name"), str):
                    declared[t["name"]] = [c.get("name") for c in t.get("columns", []) if isinstance(c, dict)]
        except (ValueError, UnicodeDecodeError, AttributeError, TypeError, RecursionError):
            declared = {}
        return declared

    def _guard_now(self, f: Path) -> tuple[bytes | None, list[dict]]:
        """The file's bytes (None when over the guard's size) and the six checks run on them now. Check 6 takes the
        row counts the runner kept when it wrote the file (DP8): a file DataPiler did not write, or one changed
        since, has none and fails it."""
        try:
            data = fileio.read_limited(f, self._cap())
        except fileio.TooLarge:
            return None, [{"check": 5, "name": "Size", "ok": False, "where": "(file)"}]
        from . import guard as guard_mod
        coverage = guard_mod.counts_for(self.live.paths.share_counts, f.name, fileio.sha256_bytes(data))
        checks = [{"check": r.check, "name": r.name, "ok": r.ok, "where": r.where}
                  for r in self.guard.check(data, declared=self._declared(data), coverage=coverage)]
        return data, checks

    @staticmethod
    def _first_failed(checks: list[dict]) -> int | None:
        if not checks:
            return 1
        return next((int(c["check"]) for c in checks if not c["ok"]), None)

    def _passes(self, f: Path) -> tuple[bool, int | None]:
        """Outputs' answer for one share file: (all six pass now, the first failing check), kept while the file's
        time and size, the text database and the kept row counts stay as they were."""
        try:
            st = f.stat()
        except OSError:
            return False, 1
        try:
            cs = self.live.paths.share_counts.stat()
            counts = (cs.st_mtime_ns, cs.st_size)
        except OSError:
            counts = None
        with self._lock:
            key = (st.st_mtime_ns, st.st_size, self._text_gen, counts)
            hit = self._passed.get(f.name)
        if hit is not None and hit[0] == key:
            return hit[1], hit[2]
        try:
            _, checks = self._guard_now(f)
            failed = self._first_failed(checks)
        except OSError:
            failed = 1
        with self._lock:
            self._passed[f.name] = (key, failed is None, failed)
        return failed is None, failed

    def share(self, name: str) -> dict:
        f = self._share_path(name)
        data, checks = self._guard_now(f)
        if data is None:
            raise Bad("the share file is over the guard's size")
        return {"name": name, "size": len(data), "sha256": fileio.sha256_bytes(data),
                "text": data.decode("utf-8", errors="replace"), "checks": checks}

    def log_lines(self, after: str) -> dict:
        try:
            seq = int(after)
        except (TypeError, ValueError):
            raise Bad("after must be a number") from None
        lines, last = logbook.lines_after(max(0, seq))
        return {"lines": lines, "last": lines[-1]["seq"] if lines else last, "first": logbook.first_seq()}

    # ------------------------------------------------------------------------------------------------ POST

    def post(self, path: str, body: dict) -> tuple[int, object, Callable[[], None] | None]:
        if path == "/api/update":
            if self.updates is None:
                return 404, {"error": "not found"}, None
            return self.updates.post(body)
        handler = self._posts().get(path)
        if handler is None:
            return 404, {"error": "not found"}, None
        out = handler(body)
        if isinstance(out, tuple):
            return out
        return 200, out, None

    def _posts(self) -> dict:
        return {
            "/api/quit": self.quit,
            "/api/link": self.switch_link,
            "/api/debug": self.debug,
            "/api/extract/run": self.extract_run,
            "/api/extract/cancel": self.extract_cancel,
            "/api/imported/remove": self.imported_remove,
            "/api/jobs/drop": self.drop,
            "/api/jobs/act": self.act,
            "/api/open": self.open_folder,
            "/api/copy-path": self.copy_path,
            "/api/settings": self.save_settings,
            "/api/settings/one": self.save_one,
            "/api/detect": self.detect,
            "/api/dirs": self.dirs,
            "/api/dirs/new": self.dirs_new,
            "/api/dirs/check": self.dirs_check,
            "/api/dirs/forget": self.dirs_forget,
            "/api/log/share": self.log_share,
        }

    def quit(self, body: dict):
        cancel = _bool(body, "cancel_running")
        busy = self.runner.busy()
        if busy and not cancel:
            if busy.get("kind") == "extract":
                text = "An Extract run is going. Quit cancels it between calls."
            else:
                jid = str(busy.get("id") or "")
                text = ("A job is running (%s). Quit cancels it between calls." % jid
                        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", jid) else
                        "A job is running. Quit cancels it between calls.")
            return {"ok": False, "ask": {"text": text}}
        self._log.info("Quit pressed on the page")
        return 200, {"ok": True}, self.stop

    def switch_link(self, body: dict) -> dict:
        on = _bool(body, "on")
        if self.link is None:
            return {"ok": False, "state": "no_libs", "why": "the server link is not available"}
        if not on:
            state = self.link.switch(False)
            self.live.session.link = False
            return {"ok": True, "state": state}
        if self.link.state == "no_libs" or not self.libs:
            return {"ok": False, "state": self.link.state,
                    "why": "the server link needs its libraries - restart DataPiler and answer Y"}
        ok, why = self.status.project_ok()
        if not ok:
            return {"ok": False, "state": self.link.state, "why": str(why)}
        g = self.status.game_running()
        if g.running:
            return {"ok": False, "state": self.link.state, "why": "the game is running - close it first"}
        # DP4 refuses a project in the game's folder, but DataPiler sees only the folder set in Settings, not the
        # project Smithbox has open (build plan §10, P1): the owner confirms it once a session.
        if not self.live.session.project_confirmed:
            if body.get("confirm_project") is not True:
                return {"ok": False, "state": self.link.state, "ask": {"text": PROJECT_ASK}}
            self.live.session.project_confirmed = True
            self._log.info("the owner confirmed that Smithbox has the project folder set in Settings open")
        state = self.link.switch(True)
        self.live.session.link = state in ("on", "blocked")
        if state == "on":
            return {"ok": True, "state": state}
        return {"ok": False, "state": state, "why": "the game is running - the server link waits until it closes"
                if state == "blocked" else "the server link did not switch on"}

    def debug(self, body: dict) -> dict:
        on = _bool(body, "on")
        self.live.session.debug = on
        logbook.set_debug(on)
        self._log.info("DEBUG to the file: %s for this session", own("on" if on else "off"))
        return {"ok": True}

    def extract_run(self, body: dict) -> dict:
        rows = body.get("rows")
        if not isinstance(rows, list) or not rows or len(rows) > 32 or not all(
                isinstance(r, str) and re.fullmatch(r"[a-z0-9_]{1,64}", r) for r in rows):
            raise Bad("rows must be a list of the catalogue's rows")
        load_maps = _bool(body, "load_maps")
        confirm = _int_or_none(body, "confirm_maps")
        try:
            return self.runner.run_extract(rows, load_maps=load_maps, confirm_maps=confirm)
        except ValueError:
            raise Bad("not a row of the catalogue") from None

    def extract_cancel(self, body: dict) -> dict:
        self.runner.cancel_extract()
        return {"ok": True}

    def imported(self) -> dict:
        """The Imported tab (S41): the text containers in the text database, counts only, and what jobs can use in
        Settings' language. Never a text."""
        from . import jobs as jobs_mod
        lang = self.live.settings.language
        out = []
        for c in self.textdb.containers():
            c = dict(c)
            c["in_use"] = c["language"] == lang
            c["serves"] = [dict(x, words=jobs_mod.TEXT_WORDS.get(x["set"], x["set"]))
                           for x in self.textdb.serves(c["container"], c["language"])]
            out.append(c)
        ready = sorted({x["set"] for c in out if c["in_use"] for x in c["serves"]})
        return {"language": lang, "containers": out,
                "ready": [{"set": s, "words": jobs_mod.TEXT_WORDS.get(s, s)} for s in ready]}

    def imported_remove(self, body: dict) -> dict:
        container = _str(body, "container", 32)
        language = _str(body, "language", 8)
        if not container or not language:
            return {"ok": False, "error": "no such import"}
        if getattr(self.runner, "busy", lambda: None)():
            return {"ok": False, "error": "a job or an Extract run is going - remove it when it ends"}
        ok = self.textdb.remove(container, language)
        if ok:
            self._log.info("the import %s (%s) removed from the text database", own(container), own(language))
        return {"ok": ok} if ok else {"ok": False, "error": "no such import"}

    def drop(self, body: dict) -> dict:
        name = _str(body, "name", 260) or "job.json"
        data = body.get("data", "")
        if not isinstance(data, str):
            raise Bad("data must be the file in base64")
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise Bad("the file did not arrive whole (not base64)") from None
        self._log.info("a job file received (%s bytes)", logbook.n(len(raw)))
        try:
            card, again = self.runner.add(name, raw)
        except ValueError:
            raise Bad("the file is empty") from None
        return {"ok": True, "card": card, "again": bool(again)}

    def act(self, body: dict) -> dict:
        jid = _str(body, "id", 128)
        what = _str(body, "what", 16)
        confirm = _int_or_none(body, "confirm_maps")
        try:
            return self.runner.act(jid, what, confirm_maps=confirm)
        except ValueError:
            raise Bad("no such job, or not something a job can do") from None

    def _area(self, body: dict) -> Path:
        area = body.get("area")
        if area == "workspace":
            return self.live.paths.workspace
        if area == "share":
            return self.live.paths.share
        raise Bad("area must be workspace or share")

    def open_folder(self, body: dict) -> dict:
        folder = self._area(body)
        folder.mkdir(parents=True, exist_ok=True)
        if winapi.backend().open_folder(str(folder)):
            return {"ok": True}
        return {"ok": False, "error": "Opening a folder works on Windows only."}

    def copy_path(self, body: dict) -> dict:
        """The path goes on the clipboard for an upload only when the file passes all six checks now."""
        f = self._share_path(_str(body, "name", 128))
        _, checks = self._guard_now(f)
        failed = self._first_failed(checks)
        if failed is not None:
            return {"ok": False, "error": "The file does not pass the guard now: check %d. Never share it." % failed}
        if winapi.backend().set_clipboard(str(f.resolve())):
            return {"ok": True}
        return {"ok": False, "error": "Copying a path works on Windows only."}

    # ------------------------------------------------------------------------------------------------ Settings

    def settings_view(self) -> dict:
        """GET /api/settings (build plan 0.2 §6): the settings without recent, the server, the session's switches, and
        for each folder its shown value, its check line, Detect's places and the recent ones; the expansion's places;
        the workspace's and the share folder's shown values."""
        s = self.live.settings
        mask_on = bool(s.mask_paths)
        root = self.live.root
        cfg = s.as_dict()
        cfg.pop("recent", None)
        folders: dict = {}
        for key, want in FOLDER_WANTS.items():
            value = getattr(s, key)
            found = self._found(want)
            folders[key] = {
                "shown": dirs_mod.shown(value, mask_on),
                "check": dirs_mod.check(want, value, s, root).as_dict(),
                "found": [detect_mod.view(want, c, s, root) for c in found],
                "notes": self._notes(want),
                "recent": [{"path": r, "shown": dirs_mod.shown(r, mask_on)} for r in s.recent.get(key, ())],
            }
        exp = [detect_mod.view("expansion", c, s, root) for c in self._found("expansion")]
        sess = self.live.session
        return {"settings": cfg, "server": SERVER, "session": {"link": sess.link, "debug": sess.debug},
                "folders": folders, "expansion": {"found": exp, "notes": self._notes("expansion")},
                "shown": {k: dirs_mod.shown(getattr(s, k), mask_on) for k in ("workspace_dir", "share_dir")}}

    def _found(self, want: str) -> list:
        if self.folders is None:
            return []
        try:
            return list(self.folders.found(want))
        except Exception as e:
            self._log.warn("Detect's places could not be read: %s", logbook.why(e))
            return []

    def _notes(self, want: str) -> list[str]:
        if self.folders is None:
            return []
        try:
            return [logbook.mask(n) for n in self.folders.notes(want)]
        except Exception:
            return []

    def save_settings(self, body: dict):
        _only(body, ("settings",))
        raw = body.get("settings")
        if not isinstance(raw, dict):
            raise Bad("settings must be an object")
        if "recent" in raw:
            return 400, {"error": settings_mod.NOT_PAGE, "field": "recent"}, None
        # The body's keys laid over the current settings before the check (build plan 0.2 §6): a page that leaves
        # out the fields it did not let the owner edit (Mask paths on) keeps them as they are.
        merged = self.live.settings.as_dict()
        merged.update(raw)
        return self._save(merged)

    def save_one(self, body: dict):
        """POST /api/settings/one: Use, Choose and the mask switch save one setting at once (S34). A folder is saved as
        the folder it resolves to, and refused on a ✗ check with its words."""
        _only(body, ("key", "value"))
        key = body.get("key")
        if key == "recent":
            return 400, {"error": settings_mod.NOT_PAGE, "field": "recent"}, None
        if key not in ONE_KEYS:
            raise Bad("key must be one of " + ", ".join(ONE_KEYS))
        value = body.get("value")
        if key in FOLDER_WANTS:
            value = _path(body, "value")
            value = value.strip()
            if value:
                c = dirs_mod.check(FOLDER_WANTS[key], value, self.live.settings, self.live.root)
                if c.ok is False:
                    return 400, {"error": str(c.text), "field": key}, None
                if not dirs_mod.unc(value) and os.path.isdir(value):
                    value = dirs_mod.resolved(value)
        elif key == "expansion":
            if not isinstance(value, str) or value not in settings_mod.EXPANSION:
                raise Bad("value must be yes, no or blank")
        elif not isinstance(value, bool):
            raise Bad("value must be true or false")
        merged = self.live.settings.as_dict()
        merged[key] = value
        out = self._save(merged)
        if isinstance(out, tuple):
            return out
        return {"ok": True}

    def _save(self, raw: dict):
        try:
            new = settings_mod.check(raw, root=self.live.root)
        except SettingsError as e:
            return 400, {"error": logbook.mask(e.rule), "field": e.field}, None
        old = self.live.settings
        new = settings_mod.with_recent(old, new)
        diff = settings_mod.changed(old, new)
        if "share_dir" in diff and self.runner.busy():
            return 400, {"error": "the share folder cannot change while a job or an import runs",
                         "field": "share_dir"}, None
        # The workspace moves at the next start (NEXT_START): the text database stays open where it is, so this
        # session's inbox, imports, jobs and Outputs stay with it, in the workspace in use.
        workspace = self.live.paths.workspace
        target = paths_mod.resolve(self.live.root, new.workspace_dir, new.share_dir)
        moved = not _same_folder(target.workspace, workspace)
        new_paths = paths_mod.resolve(self.live.root, str(workspace), new.share_dir)
        if moved and (paths_mod.is_inside(str(new_paths.share), str(workspace))
                      or paths_mod.is_inside(str(workspace), str(new_paths.share))):
            return 400, {"error": "the share folder must be outside the workspace, which stays where it is until "
                                  "the next start", "field": "share_dir"}, None
        paths_mod.ensure(new_paths)
        settings_mod.save(self.live.paths.settings, new)
        self.live.settings = new
        self.live.paths = new_paths
        if "project_dir" in diff:
            self.live.session.project_confirmed = False      # asked again for the new folder
        set_masks(self.live)
        _learn_recent(new)
        self._log.info("settings saved (%s changed)", logbook.n(len([k for k in diff if k != "recent"])))
        events.emit("settings.saved")
        later = [k for k in settings_mod.NEXT_START if k in diff and k != "workspace_dir"]
        out: dict = {"ok": True, "next_start": later + (["workspace_dir"] if moved else [])}
        if moved:
            out["note"] = WORKSPACE_MOVES
        return out

    # ------------------------------------------------------------------------------------------------ Detect, picker

    def detect(self, body: dict) -> dict:
        _only(body, ("want",))
        want = body.get("want")
        if want not in detect_mod.WANTS:
            raise Bad("want must be one of " + ", ".join(detect_mod.WANTS))
        s, root = self.live.settings, self.live.root
        if self.folders is None:
            return {"want": want, "found": [], "notes": []}
        found = self.folders.detect(want)
        return {"want": want, "found": [detect_mod.view(want, c, s, root) for c in found],
                "notes": self._notes(want)}

    @staticmethod
    def _want(body: dict, allowed: tuple[str, ...] = dirs_mod.WANTS) -> str:
        want = body.get("want")
        if want not in allowed:
            raise Bad("want must be one of " + ", ".join(allowed))
        return want

    def dirs(self, body: dict) -> dict:
        _only(body, ("path", "want", "filter"))
        want = self._want(body)
        path = _path(body, "path")
        filt = body.get("filter", "")
        if not isinstance(filt, str) or len(filt) > dirs_mod.FILTER_MAX or _PATH_CONTROL_RX.search(filt):
            raise Bad("filter must be text")
        return dirs_mod.listing(want, path, self.live.settings, self.live.root, filt=filt)

    def dirs_new(self, body: dict) -> dict:
        _only(body, ("parent", "name", "want"))
        self._want(body, ("project",))
        parent = _path(body, "parent")
        name = body.get("name")
        if not isinstance(name, str) or len(name) > dirs_mod.PATH_MAX:
            raise Bad("name must be text")
        return dirs_mod.new_folder(parent, name, self.live.settings, self.live.root)

    def dirs_check(self, body: dict) -> dict:
        _only(body, ("want", "path"))
        want = self._want(body)
        path = _path(body, "path")
        return dirs_mod.check(want, path, self.live.settings, self.live.root).as_dict()

    def dirs_forget(self, body: dict):
        _only(body, ("key",))
        key = body.get("key")
        if key not in settings_mod.FOLDER_KEYS:
            raise Bad("key must be one of " + ", ".join(settings_mod.FOLDER_KEYS))
        new = settings_mod.forget_recent(self.live.settings, key)
        settings_mod.save(self.live.paths.settings, new)
        self.live.settings = new
        self._log.info("the recent folders of one folder setting forgotten")
        events.emit("settings.saved")
        return {"ok": True}

    def log_share(self, body: dict) -> dict:
        after = _int_or_none(body, "after") or 0
        upto = _int_or_none(body, "upto")
        levels = body.get("levels", list(LEVELS))
        sources = body.get("sources", list(logbook.SOURCES))
        if not isinstance(levels, list) or not all(isinstance(x, str) for x in levels):
            raise Bad("levels must be a list")
        if not isinstance(sources, list) or not all(isinstance(x, str) for x in sources):
            raise Bad("sources must be a list")
        lines, last = logbook.lines_after(max(0, after), limit=logbook.RING)
        upto = last if upto is None else upto
        picked = [ln for ln in lines if ln["seq"] <= upto and ln["level"] in levels and ln["src"] in sources]
        b = winapi.backend()
        words = [w for w in (b.user_name(), b.pc_name()) if w]
        out = []
        left = {"3": 0, "4": 0}
        for ln in picked:
            text = line_text(ln)
            # DP18 (settled S49): a failing line is left out, never copied, and counted; the rest is copied.
            if self.textdb.find_in(text):
                left["3"] += 1
                continue
            if owner_hit(text, words):
                left["4"] += 1
                continue
            out.append(text)
        return {"ok": True, "text": "\n".join(out) + ("\n" if out else ""), "left_out": left}


def _only(body: dict, allowed: tuple[str, ...]) -> None:
    for k in body:
        if k not in allowed:
            raise Bad("not a key this request takes")


def _path(body: dict, key: str) -> str:
    v = body.get(key, "")
    if not isinstance(v, str):
        raise Bad("%s must be text" % key)
    if len(v) > dirs_mod.PATH_MAX or _PATH_CONTROL_RX.search(v):
        raise Bad("%s is not a folder path DataPiler takes" % key)
    return v


def _learn_recent(s: Settings) -> None:
    """The folders used before are Detect's "recent" source: the mask learns them as <FOUND> (design 0002 §3.5)."""
    logbook.learn_found([f for v in s.recent.values() for f in v])


def _mask_cards(cards: dict) -> None:
    """Mask paths on this page (DP14): every Status check's detail and offered folder drawn as the log's mask."""
    for checks in cards.values():
        if not isinstance(checks, list):
            continue
        for c in checks:
            if not isinstance(c, dict):
                continue
            if isinstance(c.get("detail"), str):
                c["detail"] = logbook.mask(c["detail"])
            use = c.get("use")
            if isinstance(use, dict) and isinstance(use.get("path"), str):
                use["shown"] = logbook.mask(use["path"])


def _same_folder(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (OSError, ValueError):
        return False


def set_masks(live: Live) -> None:
    """The log's masks from the settings, the folders and the PC (build plan §3.3)."""
    s, p = live.settings, live.paths
    b = winapi.backend()

    def full(x: str) -> str | None:
        return x if x and os.path.isabs(x) else None

    logbook.set_masks(
        folders={"<GAME>": full(s.game_dir), "<SMITHBOX>": full(s.smithbox_dir), "<PROJECT>": full(s.project_dir),
                 "<WORKSPACE>": str(p.workspace.resolve()), "<SHARE>": str(p.share.resolve()),
                 "<DATAPILER>": str(Path(live.root).resolve())},
        home=_safe(b.home), user=_safe(b.user_name), pc=_safe(b.pc_name))


def _safe(fn: Callable[[], str | None]) -> str | None:
    try:
        return fn()
    except Exception:
        return None
