"""The folder rows' check lines, the picker's listing and New folder (build plan 0.2 §5.5; design 0002 §3.1 to §3.3).

The picker lists folder names only, never a file, from the folder shown and nothing beyond it; a folder's `mark` is
an existence check of fixed names inside it, never a read. Hidden and system folders are left out, a drive's volume
label is never read, a UNC path is never browsed and Windows' own folder is refused. Each listing has LIST_SECS on a
worker thread, and a drive has one listing at a time (the next waits for it, at most LIST_SECS), so a sleeping drive
cannot hold the page. With Mask paths on, each folder's name is drawn as the log's mask of it, and the real path is
sent beside it for opening. What the picker listed is never logged: at DEBUG, counts only."""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from . import game as game_mod, logbook, paths, sbproject, smithbox, winapi
from .logbook import Own, own
from .settings import Settings

WANTS = ("smithbox", "game", "project")
MARKS = {"smithbox": smithbox.KNOWN_EXES, "game": ("eldenring.exe",), "project": sbproject.PROJECT_MARKS}
LIST_MAX = 2000
LIST_SECS = 3.0
PATH_MAX = 1024
NAME_MAX = 255
FILTER_MAX = 128

NOT_PATH = own("not a folder path")
NETWORK = own("network paths can be typed in the field, not browsed")
WINDOWS = own("Windows' own folder")
SLOW = own("this drive did not answer in 3 s")
NO_ACCESS = own("(no access)")
NO_SUCH = own("no such folder")

_DRIVE_RX = re.compile(r"[A-Za-z]:[\\/]")
_CONTROL_RX = re.compile(r"[\x00-\x1f\x7f]")
_BAD_NAME_RX = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_log = logbook.get("folders")


@dataclass(frozen=True)
class Check:
    ok: bool | str               # True ✓, "warn" !, False ✗
    text: Own                    # DataPiler's words, never a path
    mark: bool

    def as_dict(self) -> dict:
        return {"ok": self.ok, "text": str(self.text), "mark": self.mark}


# ---------------------------------------------------------------------------------------------------------- paths


def _posix() -> bool:
    return os.name != "nt"


def unc(path: str) -> bool:
    t = path.strip()
    return t.startswith(("\\\\", "//")) or t[:2] in ("\\/", "/\\")


def device(path: str) -> bool:
    t = path.strip().replace("/", "\\")
    return t.startswith(("\\\\.\\", "\\\\?\\", "\\??\\"))


def full(path: str, *, posix: bool | None = None) -> bool:
    """A full folder path: a drive letter, a colon and a separator; off Windows also an absolute POSIX path."""
    if posix is None:
        posix = _posix()
    if _DRIVE_RX.match(path):
        return True
    return bool(posix and path.startswith("/") and not unc(path))


def _parts(path: str) -> list[str]:
    return [x for x in re.split(r"[\\/]+", path) if x]


def _fold(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").casefold()


def _win_part(part: str) -> str:
    """A part as Windows opens it: its trailing dots and spaces dropped ('.' and '..' as they are)."""
    return part if part in (".", "..") else part.rstrip(". ")


def inside_text(child: str, parent: str) -> bool:
    """Pure: child is parent or inside it, compared by its parts as Windows opens them (trailing dots and spaces
    dropped), case-folded, either slash."""
    c = [_win_part(x) for x in _parts(_fold(child))]
    p = [_win_part(x) for x in _parts(_fold(parent))]
    return bool(p) and len(c) >= len(p) and c[: len(p)] == p


def path_refusal(path: str, windows_dir: str | None, *, posix: bool | None = None) -> Own | None:
    """'not a folder path' (relative; '..' after resolving; a device path, \\\\.\\ or \\\\?\\), 'network paths can be
    typed in the field, not browsed' (UNC), "Windows' own folder" (windows_dir or inside it, also when a part ends in
    a dot or a space, which Windows drops: C:\\Windows.\\System32 is C:\\Windows\\System32). Pure, but on Windows,
    where the path is also compared as the file system resolves it."""
    if not isinstance(path, str) or not path.strip() or "\x00" in path or _CONTROL_RX.search(path):
        return NOT_PATH
    if device(path):
        return NOT_PATH
    if unc(path):
        return NETWORK
    if not full(path, posix=posix):
        return NOT_PATH
    if any(x == ".." for x in _parts(path)):
        return NOT_PATH
    if windows_dir and full(windows_dir, posix=True) and inside_text(path, windows_dir):
        return WINDOWS
    if windows_dir and os.name == "nt" and _same_drive(path, windows_dir) and _real_inside(path, windows_dir):
        return WINDOWS          # pragma: no cover - Windows CI; another drive is checked by the listing's worker
    return None


def _same_drive(a: str, b: str) -> bool:
    da = PureWindowsPath(a).drive if _DRIVE_RX.match(a) else ""
    db = PureWindowsPath(b).drive if _DRIVE_RX.match(b) else ""
    return bool(da) and da.casefold() == db.casefold()


def _real_inside(path: str, folder: str) -> bool:
    """path, as the file system resolves it (links, 8.3 names), is folder or inside it. It opens the path, so off
    Windows' own drive it runs only in a listing's worker, within LIST_SECS."""
    try:
        return inside_text(os.path.realpath(path), os.path.realpath(folder))
    except (OSError, ValueError):
        return False


def _windows_dir() -> str | None:
    try:
        return winapi.backend().windows_dir()
    except Exception:
        return None


def resolved(path: str) -> str:
    """The folder a link (a junction or symlink) resolves to; the path as it is when it cannot be resolved. A drive
    letter path that resolves to a network path (a mapped drive, which Windows' realpath turns into \\\\server\\share)
    is kept as it was chosen, so its check stays the one the picker showed (the correctness review's C10)."""
    try:
        r = str(Path(path).resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return path
    if _DRIVE_RX.match(path.strip()) and unc(r):
        return path
    return r


def shown(path: str, mask_on: bool) -> str:
    """What the page draws for a path: the log's mask of it with Mask paths on, else the path."""
    return logbook.mask(path) if mask_on and path else path


# ---------------------------------------------------------------------------------------------------------- checks


def _marked(folder: str, want: str) -> bool:
    for name in MARKS.get(want, ()):
        try:
            if os.path.exists(os.path.join(folder, name)):
                return True
        except (OSError, ValueError):
            continue
    return False


def _smithbox_text(folder: str) -> Check:
    rs = smithbox.reports(folder)
    if not rs:
        return Check(False, own("no Smithbox exe here (%s)" % smithbox.EXE_TEXT), False)
    names = [r.name if smithbox.is_exe_name(r.name) else "a Smithbox exe" for r in rs]
    here = (names[0] + " is here") if len(names) == 1 else (" and ".join(names[:2]) + (
        " and %d more" % (len(names) - 2) if len(names) > 2 else "") + " are here")
    running = [r for r in rs if r.running]
    builds = [r.build for r in rs if r.build]
    if running and running[0].build:
        tail = "build %s (the running one)" % running[0].build if len(rs) > 1 else "build %s" % running[0].build
    elif builds and len(set(builds)) == 1:
        tail = "build %s" % builds[0]
    elif builds:
        tail = "builds differ: " + ", ".join("%s %s" % (r.name, r.build) for r in rs if r.build)
    else:
        tail = "build not read"
    return Check(True, own(here + " · " + tail), True)


def _project_text(path: str, s: Settings, root: Path) -> Check:
    rootp = str(root)
    if paths.is_inside(path, rootp):
        if paths.is_inside(rootp, path):
            return Check(False, own("DataPiler's own folder - choose a folder outside it"), False)
        return Check(False, own("inside DataPiler's folder - choose a folder outside it"), False)
    g = s.game_dir
    if not g:
        return Check("warn", own("set the game folder first, so this can be checked against it"),
                     _marked(path, "project"))
    if paths.is_inside(path, g):
        if paths.is_inside(g, path):
            return Check(False, own("the game's folder itself - choose a folder outside it"), False)
        return Check(False, own("inside the game's folder - choose a folder outside it"), False)
    if paths.is_inside(g, path):
        return Check(False, own("it holds the game's folder - choose a folder outside it"), False)
    text = "outside the game's folder"
    mark = False
    if record_matches(path, g):
        text += " · a Smithbox project for this game"
        mark = True
    elif _marked(path, "project"):
        text += " · a Smithbox project file is here"
        mark = True
    return Check(True, own(text), mark)


def record_matches(project: str, game_dir: str) -> bool:
    """A recognised record of Smithbox's names this folder as its ProjectPath and the game folder as its DataPath
    (smithbox-projects.md §5: the AppData record, never project.json)."""
    try:
        local = winapi.backend().local_appdata()
    except Exception:
        local = None
    if not local:
        return False
    rec = sbproject.cached(local)
    return any(same_folder(x.project_dir, project) and same_folder(x.data_dir, game_dir) for x in rec.leads)


def same_folder(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if _fold(a) == _fold(b):
        return True
    try:
        return paths.is_inside(a, b) and paths.is_inside(b, a)
    except (OSError, ValueError):
        return False


def check(want: str, path: str, s: Settings, root: Path) -> Check:
    """The row's check line for a path (design 0002 §3.1): ✓, ! (saves) or ✗ (refuses), in DataPiler's words."""
    p = (path or "").strip()
    if not p:
        return Check("warn", own("not set"), False)
    if unc(p) and not device(p):
        return Check("warn", own("a network path - not checked"), False)
    if device(p) or not full(p) or "\x00" in p:
        return Check(False, own("a full folder path is needed (it starts with a drive letter)"), False)
    try:
        isdir = os.path.isdir(p)
    except (OSError, ValueError):
        isdir = False
    if not isdir:
        if want == "project":
            return Check("warn", own("no such folder - New folder… in the picker makes one"), False)
        return Check("warn", NO_SUCH, False)
    if want == "smithbox":
        return _smithbox_text(p)
    if want == "game":
        if game_mod.exe_path(p) is None:
            return Check(False, own("no eldenring.exe here - the game's folder is the Game folder inside ELDEN RING"),
                         False)
        v = game_mod.version(p)
        return Check(True, own("eldenring.exe is here · " + ("version " + v if v else "version not read")), True)
    if want == "project":
        return _project_text(p, s, root)
    raise ValueError("not a folder DataPiler checks")


# ---------------------------------------------------------------------------------------------------------- listing

_busy_lock = threading.Lock()
_busy: dict[str, threading.Thread] = {}


def _drive_key(path: str) -> str:
    d = PureWindowsPath(path).drive if _DRIVE_RX.match(path) else ""
    return (d or "/").casefold()


def _scan(folder: str, want: str, filt: str, out: dict) -> None:
    """The worker: folder names only; hidden and system folders left out; marks for the first LIST_MAX."""
    try:
        b = winapi.backend()
        if os.name == "nt":     # pragma: no cover - Windows CI: a link on another drive into Windows' own folder
            win = _windows_dir()
            if win and not _same_drive(folder, win) and _real_inside(folder, win):
                out.update(dirs=[], more=0, note=WINDOWS)
                return
        names: list[str] = []
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if not entry.is_dir():          # follows a junction or a symlink: listed under its own name
                        continue
                except OSError:
                    continue
                try:
                    if b.hidden(entry.path):
                        continue
                except Exception:
                    continue
                if filt and filt not in entry.name.casefold():
                    continue
                names.append(entry.name)
        names.sort(key=lambda n: (n.casefold(), n))
        more = max(0, len(names) - LIST_MAX)
        dirs = [{"name": n, "mark": _marked(os.path.join(folder, n), want)} for n in names[:LIST_MAX]]
        out.update(dirs=dirs, more=more, note=None)
    except PermissionError:
        out.update(dirs=[], more=0, note=NO_ACCESS)
    except (FileNotFoundError, NotADirectoryError):
        out.update(dirs=[], more=0, note=NO_SUCH)
    except OSError:
        out.update(dirs=[], more=0, note=NO_ACCESS)


def _list(folder: str, want: str, filt: str) -> dict:
    """One listing per drive at a time: a listing still under way is waited for, up to LIST_SECS, and this one then
    has LIST_SECS of its own. A drive answers SLOW only when a listing of it has run that long (the correctness
    review's C8: a second request at once was told the drive had not answered)."""
    key = _drive_key(folder)
    waited_until = time.monotonic() + LIST_SECS
    while True:
        with _busy_lock:
            t = _busy.get(key)
            if t is None or not t.is_alive():
                out: dict = {}
                t = threading.Thread(target=_scan, args=(folder, want, filt, out), name="datapiler-picker",
                                     daemon=True)
                _busy[key] = t
                t.start()
                break
        left = waited_until - time.monotonic()
        if left <= 0:
            return {"dirs": [], "more": 0, "note": SLOW}
        t.join(left)
    t.join(LIST_SECS)
    if t.is_alive():
        return {"dirs": [], "more": 0, "note": SLOW}
    with _busy_lock:
        if _busy.get(key) is t:
            del _busy[key]
    return out or {"dirs": [], "more": 0, "note": NO_ACCESS}


def _crumbs(path: str, mask_on: bool) -> list[dict]:
    """Each level of the path with its real path for navigating; with the mask on, the masked path's levels, a
    placeholder one crumb standing for the folders it hides."""
    real: list[dict] = []
    if _DRIVE_RX.match(path):
        parts = _parts(path)
        acc = parts[0] + "\\"
        real.append({"name": parts[0], "path": acc})
        for x in parts[1:]:
            acc = (acc.rstrip("\\") + "\\" + x)
            real.append({"name": x, "path": acc})
    else:
        parts = _parts(path)
        real.append({"name": "/", "path": "/"})
        acc = ""
        for x in parts:
            acc = acc + "/" + x
            real.append({"name": x, "path": acc})
    if not mask_on:
        return real
    drive = bool(_DRIVE_RX.match(path))
    lead, body = ([], real) if drive else (real[:1], real[1:])     # the POSIX root "/" has no masked part
    masked = logbook.mask(path)
    m = _parts(masked)
    if len(m) == len(body):
        return lead + [{"name": mm, "path": r["path"]} for mm, r in zip(m, body)]
    if m and len(m) < len(body) and re.fullmatch(r"<[A-Z]+>", m[0]):
        hidden = len(body) - len(m)                       # the levels the first placeholder stands for
        out = [{"name": m[0], "path": body[hidden]["path"]}]
        return out + [{"name": mm, "path": r["path"]} for mm, r in zip(m[1:], body[hidden + 1:])]
    return [{"name": masked, "path": path}]


def _child(folder: str, name: str) -> str:
    sep = "\\" if _DRIVE_RX.match(folder) else "/"
    return folder.rstrip("\\/") + sep + name


def parent_of(path: str) -> str:
    """The folder above path, as a path ("" for a drive's root or "/": This PC), for Up, Backspace and Alt+Up, which
    must not depend on the crumbs a mask draws (the correctness review's C9)."""
    parts = _parts(path)
    if _DRIVE_RX.match(path):
        if len(parts) <= 1:
            return ""
        return parts[0] + "\\" + "\\".join(parts[1:-1])
    if not parts:
        return ""
    return "/" + "/".join(parts[:-1])


def shown_name(folder: str, name: str, mask_on: bool) -> str:
    """A listed folder's name as the page draws it: as it is, or with Mask paths on, the placeholder the log's mask
    makes of its full path when the mask hides it whole (<HOME>, <GAME>, <FOUND>), else the mask of the name itself
    (a user's or PC's name as <USER> or <PC>). The security review's SEC-2 and the correctness review's C5: the
    folder named after the account was listed as it is."""
    if not mask_on:
        return name
    whole = _parts(logbook.mask(_child(folder, name)))
    if whole and re.fullmatch(r"<[A-Z]+>", whole[-1]):
        return whole[-1]
    return logbook.mask(name)


def listing(want: str, path: str, s: Settings, root: Path, *, filt: str = "") -> dict:
    """The /api/dirs answer: the drives for a blank path; a refusal as {"refused": ...} and nothing else; else the
    folder's subfolders (each its name, its real path to open and the name as drawn), its crumbs, its parent and its
    check line."""
    mask_on = bool(s.mask_paths)
    p = (path or "").strip()
    if not p:
        try:
            drives = winapi.backend().drives()
        except Exception:
            drives = []
        out = [{"name": d.name, "path": d.path, "kind": d.kind if d.kind in winapi.DRIVE_KINDS else "unknown"}
               for d in drives]
        _log.debug("picker: %s folder listed, %s entries", 0, len(out))
        return {"path": "", "shown": "This PC", "crumbs": [], "drives": out, "dirs": [], "more": 0, "check": None,
                "note": None}
    why = path_refusal(p, _windows_dir())
    if why is not None:
        return {"refused": str(why)}
    if _DRIVE_RX.match(p) and len(_parts(p)) == 1:
        p = _parts(p)[0] + "\\"                               # "C:" and "C:/" are the drive's root, C:\
    elif p != "/":
        p = p.rstrip("\\/") or p
    got = _list(p, want, (filt or "").casefold()[:FILTER_MAX])
    _log.debug("picker: %s folder listed, %s entries", 1, len(got.get("dirs", [])))
    note = got.get("note")
    listed = [{"name": d["name"], "path": _child(p, d["name"]), "shown": shown_name(p, d["name"], mask_on),
               "mark": d["mark"]} for d in got.get("dirs", [])]
    return {"path": p, "shown": shown(p, mask_on), "crumbs": _crumbs(p, mask_on), "parent": parent_of(p),
            "dirs": listed, "more": int(got.get("more", 0)), "check": check(want, p, s, root).as_dict(),
            "note": str(note) if note else None}


# ---------------------------------------------------------------------------------------------------------- new


def name_refusal(name: str) -> Own | None:
    """Windows' refused characters, control characters, a trailing dot or space, a device name, over 255."""
    if not isinstance(name, str) or not name or not name.strip():
        return own("a folder needs a name")
    if len(name) > NAME_MAX:
        return own("a folder name is at most 255 characters")
    if _BAD_NAME_RX.search(name):
        return own('a folder name cannot hold < > : " / \\ | ? * or a control character')
    if name.endswith((".", " ")) or name in (".", ".."):
        return own("a folder name cannot end with a dot or a space")
    if paths.reserved(name.split(".")[0].rstrip(" ")):
        return own("that name is one Windows keeps for a device")
    return None


def new_folder(parent: str, name: str, s: Settings, root: Path) -> dict:
    """The /api/dirs/new answer (the project's picker only): {"path", "shown"} or {"refused"}. os.mkdir, never
    makedirs; a folder that exists is refused."""
    why = name_refusal(name)
    if why is None:
        why = path_refusal((parent or "").strip(), _windows_dir())
    if why is not None:
        return {"refused": str(why)}
    parent = parent.strip()
    try:
        if not os.path.isdir(parent):
            return {"refused": str(NO_SUCH)}
    except (OSError, ValueError):
        return {"refused": str(NO_SUCH)}
    target = os.path.join(parent, name)
    if s.game_dir and (paths.is_inside(target, s.game_dir) or paths.is_inside(s.game_dir, target)):
        return {"refused": "not inside the game's folder - choose a folder outside it"}
    if paths.is_inside(target, str(root)):
        return {"refused": "not inside DataPiler's folder - choose a folder outside it"}
    try:
        os.mkdir(target)
    except FileExistsError:
        return {"refused": "a folder of that name is here already"}
    except PermissionError:
        return {"refused": "Windows did not allow a folder here"}
    except OSError:
        return {"refused": "the folder could not be made here"}
    _log.info("New folder made in the project's picker")
    return {"path": target, "shown": shown(target, bool(s.mask_paths))}
