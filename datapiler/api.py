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

from . import VERSION, events, fileio, link as link_mod, logbook, paths as paths_mod, settings as settings_mod, winapi
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
                 stop: Callable[[], None], libs: bool):
        self.live = live
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
        for u in self._unsub:
            u()

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
            s = self.live.session
            return 200, {"settings": self.live.settings.as_dict(), "server": SERVER,
                         "session": {"link": s.link, "debug": s.debug}}
        return 404, {"error": "not found"}

    def state(self) -> dict:
        jobs = self.runner.cards()
        extract = dict(self.runner.extract_state())
        if "inbox" not in extract:
            try:
                extract["inbox"] = self.inbox.state()
            except Exception:
                extract["inbox"] = []
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
            "status": self.status.cards(),
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
            "/api/jobs/drop": self.drop,
            "/api/jobs/act": self.act,
            "/api/open": self.open_folder,
            "/api/copy-path": self.copy_path,
            "/api/settings": self.save_settings,
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

    def save_settings(self, body: dict):
        raw = body.get("settings")
        if not isinstance(raw, dict):
            raise Bad("settings must be an object")
        try:
            new = settings_mod.check(raw, root=self.live.root)
        except SettingsError as e:
            return 400, {"error": logbook.mask(e.rule), "field": e.field}, None
        old = self.live.settings
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
        self._log.info("settings saved (%s changed)", logbook.n(len(diff)))
        events.emit("settings.saved")
        later = [k for k in settings_mod.NEXT_START if k in diff and k != "workspace_dir"]
        out: dict = {"ok": True, "next_start": later + (["workspace_dir"] if moved else [])}
        if moved:
            out["note"] = WORKSPACE_MOVES
        return out

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
        for ln in picked:
            text = line_text(ln)
            if self.textdb.find_in(text):
                return {"ok": False, "refused": {"check": 3, "line": ln["seq"]}}
            if owner_hit(text, words):
                return {"ok": False, "refused": {"check": 4, "line": ln["seq"]}}
            out.append(text)
        return {"ok": True, "text": "\n".join(out) + ("\n" if out else "")}


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
