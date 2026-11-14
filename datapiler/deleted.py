"""The Deleted bin, `workspace/bin/` (DP22, settled S70).

Nothing DataPiler keeps is erased by a removal. A job, a share file, a workspace file, an import of the text database
and a map job's saved progress each become one bin item: a folder holding the files moved out of their place, under
`files/`, and `item.json`, which names its kind, a display name, where it came from (one of DataPiler's folders and a
place relative to it, never a full path), when, its size and its files. An import of the text database lives in
SQLite, so its item holds its rows and its record as `files/rows.json`, which Restore writes back through the write
imports use (`TextDB.put_back`), keeping its sha256 and its time.

Restore puts every file back where it came from and refuses, saying what is in the way, when something of the same
name is there now: it never overwrites. Only Erase (one item) and Empty bin (every item) erase; the API asks for DELETE
typed in before either. The bin keeps everything until then.

Files move with os.replace. Only where the bin is on another drive than the file's place (Settings can put the
workspace and the share folder elsewhere than DataPiler's own folder, which holds `jobs/`) is a file copied, flushed,
compared and then removed. Nothing outside DataPiler's jobs folder, its workspace and its share folder is ever read or
moved. The bin is in the workspace because what it holds may be game text: it never leaves the PC.

Log lines name the kind, the item's id (DataPiler's own name) and counts, never a file name or a path."""

from __future__ import annotations

import errno
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from . import events, fileio, logbook, paths as paths_mod
from .logbook import own

if TYPE_CHECKING:
    from .paths import Paths
    from .textdb import TextDB

FORMAT = "datapiler-bin/1"
ITEM_FILE = "item.json"
STORE = "files"
WORD = "DELETE"         # typed in to remove collected data, and to erase from the bin
MOVE = "move"           # the confirmation of a pop-up without a text box (a job)
KINDS = {"job": "Job", "progress": "Saved map progress", "share": "Share file", "local": "Workspace file",
         "export": "Text export file", "text": "Imported text"}
AREAS = {"jobs": "Jobs", "share": "Share folder", "workspace": "Workspace", "textdb": "Text database"}
PART_RX = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")         # one part of a place: api.SAFE_NAME_RX
SHARE_RX = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.json")          # a share file's name: api.FILE_RX
CONTAINER_RX = re.compile(r"[a-z0-9][a-z0-9_]{0,31}")             # inbox.CONTAINER_RX
LANGUAGE_RX = re.compile(r"[a-z]{2,8}")                           # inbox.LANGUAGE_RX
ROWS_FILE = "rows.json"
ITEM_MAX = 1024 * 1024
ROWS_MAX = 512 * 1024 * 1024
NO_ITEM = "no such item in the Deleted bin"
KEPT = "The item stays in the bin."
_NOT_SAME_DEVICE = 17           # Windows' ERROR_NOT_SAME_DEVICE

_lock = threading.RLock()       # never held while calling the runner or the text database
_log = logbook.get("app")


class BinError(Exception):
    """A bin operation refused, in DataPiler's own words, which the page shows. Never a path."""


# ------------------------------------------------------------------------------------------------ places and moves

def _place_ok(place: object) -> bool:
    if not isinstance(place, str):
        return False
    parts = place.split("/")
    return 1 <= len(parts) <= 4 and all(PART_RX.fullmatch(x) for x in parts)


def _root(p: "Paths", area: str) -> Path | None:
    return {"jobs": p.jobs, "share": p.share, "workspace": p.workspace}.get(area)


def _dest(p: "Paths", area: str, place: str) -> Path:
    """Where a place of an area is now; BinError for anything that would leave the area."""
    root = _root(p, area)
    if root is None or not _place_ok(place):
        raise BinError(NO_ITEM)
    d = root.joinpath(*place.split("/"))
    if not paths_mod.is_inside(d, root):
        raise BinError(NO_ITEM)
    return d


def _other_drive(e: OSError) -> bool:
    return e.errno == errno.EXDEV or getattr(e, "winerror", None) == _NOT_SAME_DEVICE


def _plain_file(f: Path) -> bool:
    return not f.is_symlink() and f.is_file()


def _move(src: Path, dst: Path) -> None:
    """Move one plain file to a name not taken: os.replace, or across drives a copy, flushed and compared, then the
    original removed. Raises FileExistsError, BinError for a link, OSError."""
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, "taken")
    if not _plain_file(src):
        raise BinError("only plain files go to the Deleted bin and back")
    try:
        os.replace(src, dst)
        return
    except OSError as e:
        if not _other_drive(e):
            raise
    part = dst.with_name(dst.name + ".part")
    try:
        with open(src, "rb") as fi, open(part, "xb") as fo:
            shutil.copyfileobj(fi, fo, fileio.CHUNK)
            fo.flush()
            os.fsync(fo.fileno())
        if fileio.sha256_file(part) != fileio.sha256_file(src):
            raise OSError(errno.EIO, "the copy differs")
        os.replace(part, dst)
    except BaseException:
        try:
            os.unlink(part)
        except OSError:
            pass
        raise
    os.unlink(src)


def _erase_folder(folder: Path) -> None:
    shutil.rmtree(folder)


# ------------------------------------------------------------------------------------------------ items

def _new_id(p: "Paths", kind: str) -> str:
    for _ in range(100):
        iid = "%s-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), kind, secrets.token_hex(3))
        if paths_mod.name_ok(iid) and not os.path.lexists(p.bin / iid):
            return iid
    raise BinError("the Deleted bin has no free name now - try again")


def _whole(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _files_ok(v: object) -> bool:
    return isinstance(v, list) and all(isinstance(f, dict) and PART_RX.fullmatch(str(f.get("name", ""))) and
                                       _whole(f.get("size")) for f in v)


def _meta(p: "Paths", iid: object) -> dict:
    """An item's item.json, checked. BinError for anything else."""
    if not paths_mod.name_ok(iid):
        raise BinError(NO_ITEM)
    folder = p.bin / str(iid)
    if folder.is_symlink() or not folder.is_dir():
        raise BinError(NO_ITEM)
    try:
        meta = json.loads(fileio.read_limited(folder / ITEM_FILE, ITEM_MAX).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        raise BinError(NO_ITEM) from None
    if not isinstance(meta, dict) or meta.get("format") != FORMAT or meta.get("id") != iid or \
            meta.get("kind") not in KINDS or not isinstance(meta.get("name"), str) or len(meta["name"]) > 300 or \
            not isinstance(meta.get("from"), dict) or meta["from"].get("area") not in AREAS or \
            not _place_ok(meta["from"].get("place")) or not isinstance(meta.get("at"), (int, float)) or \
            isinstance(meta.get("at"), bool) or not _whole(meta.get("size")) or not _files_ok(meta.get("files")) or \
            not _files_ok(meta.get("data")) or not isinstance(meta.get("extra"), dict):
        raise BinError(NO_ITEM)
    return meta


def view(meta: dict) -> dict:
    """What the page shows of an item: its kind, name, where it came from (a place in one of DataPiler's folders),
    when and size."""
    return {"id": meta["id"], "kind": meta["kind"], "what": KINDS[meta["kind"]], "name": meta["name"],
            "from": "%s: %s" % (AREAS[meta["from"]["area"]], meta["from"]["place"]),
            "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(meta["at"])), "at": meta["at"],
            "size": meta["size"], "files": len(meta["files"]) + len(meta["data"])}


def put(p: "Paths", kind: str, name: str, area: str, place: str, files: list[tuple[Path, str]], *,
        extra: dict | None = None, data: dict[str, bytes] | None = None) -> dict:
    """One removal into the bin: files [(the file, its name in the item)] moved in, data {name: bytes} written in,
    item.json first. The page's view of the item. When a move fails, what moved goes back, the item goes, and the
    error is raised (OSError or BinError): nothing is ever lost on the way."""
    if kind not in KINDS or area not in AREAS or not _place_ok(place):
        raise ValueError("not a bin item DataPiler makes")
    data = dict(data or {})
    names = [rel for _, rel in files] + list(data)
    if len(set(names)) != len(names) or not all(PART_RX.fullmatch(n) for n in names):
        raise ValueError("not a bin item DataPiler makes")
    with _lock:
        listed = []
        for src, rel in files:
            if not _plain_file(src):
                raise BinError("only plain files go to the Deleted bin")
            listed.append({"name": rel, "size": int(src.stat().st_size)})
        kept = [{"name": rel, "size": len(b)} for rel, b in data.items()]
        p.bin.mkdir(parents=True, exist_ok=True)
        iid = _new_id(p, kind)
        folder = p.bin / iid
        store = folder / STORE
        meta = {"format": FORMAT, "id": iid, "kind": kind, "name": str(name)[:300], "from": {"area": area,
                "place": place}, "at": time.time(), "size": sum(f["size"] for f in listed + kept), "files": listed,
                "data": kept, "extra": dict(extra or {})}
        moved: list[tuple[Path, Path]] = []
        try:
            store.mkdir(parents=True)
            for rel, b in data.items():
                fileio.write_atomic(store / rel, b)
            doc = json.dumps(meta, indent=1, ensure_ascii=True) + "\n"
            fileio.write_atomic(folder / ITEM_FILE, doc.encode("ascii"))
            for src, rel in files:
                _move(src, store / rel)
                moved.append((src, store / rel))
        except BaseException as e:
            back = True
            for src, dst in reversed(moved):
                try:
                    _move(dst, src)
                except (OSError, BinError):
                    back = False
            if back:
                shutil.rmtree(folder, ignore_errors=True)
            if back:
                _log.warn("not moved to the Deleted bin (%s): %s", own(KINDS[kind].lower()), logbook.why(e))
            else:
                _log.warn("not moved to the Deleted bin (%s): %s - the item %s holds what had moved",
                          own(KINDS[kind].lower()), logbook.why(e), own(iid))
            raise
    _log.info("moved to the Deleted bin (%s): item %s, %s files, %s bytes", own(KINDS[kind].lower()), own(iid),
              logbook.n(len(listed) + len(kept)), logbook.n(meta["size"]))
    events.emit("bin.changed")
    return view(meta)


def items(p: "Paths") -> list[dict]:
    """Every item, the newest first."""
    out = []
    with _lock:
        try:
            entries = list(os.scandir(p.bin))
        except FileNotFoundError:
            return []
        for e in entries:
            if not paths_mod.name_ok(e.name) or not e.is_dir(follow_symlinks=False):
                continue
            try:
                out.append(view(_meta(p, e.name)))
            except BinError:
                continue
    out.sort(key=lambda x: -x["at"])
    return out


def item(p: "Paths", iid: object) -> dict:
    """One item's item.json, checked. BinError for no such item."""
    with _lock:
        return _meta(p, iid)


def read_file(p: "Paths", iid: str, rel: str, cap: int) -> bytes:
    """A file of an item, as it lies in the bin. OSError, fileio.TooLarge, BinError."""
    if not paths_mod.name_ok(iid) or not PART_RX.fullmatch(rel):
        raise BinError(NO_ITEM)
    with _lock:
        f = p.bin / iid / STORE / rel
        if not _plain_file(f):
            raise BinError(NO_ITEM)
        return fileio.read_limited(f, cap)


def move_back(p: "Paths", iid: str, meta: dict, dests: dict[str, Path], conflict: str) -> None:
    """Restore's move: each file the item holds to dests[its name], none overwritten; then the item goes. BinError
    with the words conflict (and KEPT) when a file of that name is there, before anything moves; when a move fails,
    what moved goes back into the item and the error is raised."""
    with _lock:
        meta = _meta(p, iid)                 # still there: not erased or restored since it was read
        folder = p.bin / iid
        store = folder / STORE
        plan = []
        for f in meta["files"]:
            src = store / f["name"]
            if not _plain_file(src):
                continue                     # never moved in (an item cut short), or moved back already
            dst = dests.get(f["name"])
            if dst is None:
                raise BinError(NO_ITEM)
            if os.path.lexists(dst):
                raise BinError("%s %s" % (conflict, KEPT))
            plan.append((src, dst))
        moved: list[tuple[Path, Path]] = []
        try:
            for src, dst in plan:
                dst.parent.mkdir(parents=True, exist_ok=True)
                _move(src, dst)
                moved.append((src, dst))
        except FileExistsError:
            _put_back(moved)
            raise BinError("%s %s" % (conflict, KEPT)) from None
        except BaseException:
            _put_back(moved)
            raise
        _gone(folder, iid)
    _log.info("restored from the Deleted bin (%s): item %s, %s files", own(KINDS[meta["kind"]].lower()), own(iid),
              logbook.n(len(plan)))
    events.emit("bin.changed")


def _put_back(moved: list[tuple[Path, Path]]) -> None:
    for src, dst in reversed(moved):
        try:
            _move(dst, src)
        except (OSError, BinError) as e:
            _log.error("a restored file could not go back into the Deleted bin: %s", logbook.why(e))


def _gone(folder: Path, iid: str) -> None:
    """A restored item's folder, which holds nothing of its place now, removed."""
    try:
        _erase_folder(folder)
    except OSError as e:
        _log.warn("the Deleted bin's item %s could not be cleared after its restore: %s", own(iid), logbook.why(e))


def erase(p: "Paths", iid: object) -> dict:
    """Erase one item for good (the API asks for DELETE first). Its view. BinError, OSError."""
    with _lock:
        meta = _meta(p, iid)
        _erase_folder(p.bin / meta["id"])
    _log.info("erased from the Deleted bin (%s): item %s", own(KINDS[meta["kind"]].lower()), own(meta["id"]))
    events.emit("bin.changed")
    return view(meta)


def empty(p: "Paths") -> int:
    """Erase every item for good (the API asks for DELETE first): every folder in the bin. How many. OSError."""
    n = 0
    with _lock:
        try:
            entries = list(os.scandir(p.bin))
        except FileNotFoundError:
            return 0
        for e in entries:
            if paths_mod.name_ok(e.name) and e.is_dir(follow_symlinks=False):
                _erase_folder(p.bin / e.name)
                n += 1
    _log.info("the Deleted bin emptied: %s items erased", logbook.n(n))
    events.emit("bin.changed")
    return n


# ------------------------------------------------------------------------------------------------ what goes in

def remove_share(p: "Paths", name: object) -> dict:
    """A share file, with its kept row counts (check 6's input), into the bin."""
    from . import guard as guard_mod

    if not isinstance(name, str) or not SHARE_RX.fullmatch(name) or not paths_mod.name_ok(name[:-5]):
        raise BinError("no such share file")
    src = p.share / name
    if not _plain_file(src):
        raise BinError("no such share file")
    entry = guard_mod.counts_entry(p.share_counts, name)
    out = put(p, "share", name, "share", name, [(src, name)], extra={"counts": entry})
    try:
        guard_mod.forget_counts(p.share_counts, name)
    except OSError as e:
        _log.warn("a share file's row counts stay recorded after its move to the Deleted bin: %s", logbook.why(e))
    return out


def workspace_parts(rel: object) -> list[str] | None:
    """The parts of a workspace file the page can remove: one under local/ or imported/, as Outputs names it."""
    if not isinstance(rel, str):
        return None
    parts = rel.split("/")
    if not 2 <= len(parts) <= 4 or parts[0] not in ("local", "imported") or \
            not all(PART_RX.fullmatch(x) for x in parts) or not parts[-1].endswith(".json"):
        return None
    return parts


def remove_workspace_file(p: "Paths", rel: object) -> dict:
    """A file of the workspace's local/ (what jobs and Extract wrote) or imported/ (the text exports imported)."""
    parts = workspace_parts(rel)
    if parts is None:
        raise BinError("not a workspace file the page can remove")
    src = p.workspace.joinpath(*parts)
    if not paths_mod.is_inside(src, p.local if parts[0] == "local" else p.imported) or not _plain_file(src):
        raise BinError("no such workspace file")
    place = "/".join(parts)
    return put(p, "local" if parts[0] == "local" else "export", place, "workspace", place, [(src, parts[-1])])


def remove_text(p: "Paths", textdb: "TextDB", container: str, language: str) -> dict | None:
    """An import of the text database into the bin, its rows and record kept exactly. None when there is none."""
    if not isinstance(container, str) or not CONTAINER_RX.fullmatch(container) or \
            not isinstance(language, str) or not LANGUAGE_RX.fullmatch(language):
        return None

    def keep(dump: dict) -> dict:
        rows = json.dumps(dump, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return put(p, "text", "%s (%s)" % (container, language), "textdb", "%s/%s" % (container, language), [],
                   extra={"container": container, "language": language}, data={ROWS_FILE: rows})

    out = textdb.take(container, language, keep)
    return out if isinstance(out, dict) else None


# ------------------------------------------------------------------------------------------------ Restore

def restore(p: "Paths", iid: object, *, runner=None, textdb: "TextDB | None" = None) -> dict:
    """Put an item back where it came from, as it was. Its view. BinError, naming what is in the way, when something
    of the same name is there now (nothing moves then); OSError."""
    meta = item(p, iid)
    kind = meta["kind"]
    place = meta["from"]["place"]
    if kind in ("job", "progress"):
        if runner is None:
            raise BinError("jobs cannot be restored now")
        (runner.restore_job if kind == "job" else runner.restore_progress)(meta["id"], meta)
    elif kind == "share":
        if not SHARE_RX.fullmatch(place):
            raise BinError(NO_ITEM)
        move_back(p, meta["id"], meta, {place: _dest(p, "share", place)},
                  "Not restored: the share folder has a file %s now. Remove or rename it first." % place)
        entry = meta["extra"].get("counts")
        if isinstance(entry, dict):
            from . import guard as guard_mod
            try:
                guard_mod.put_counts(p.share_counts, place, entry)
            except (OSError, ValueError) as e:
                _log.warn("a restored share file's row counts could not be put back: %s", logbook.why(e))
    elif kind in ("local", "export"):
        parts = workspace_parts(place)
        if parts is None or len(meta["files"]) != 1:
            raise BinError(NO_ITEM)
        move_back(p, meta["id"], meta, {meta["files"][0]["name"]: _dest(p, "workspace", place)},
                  "Not restored: the workspace has a file %s now. Remove or rename it first." % place)
    else:
        _restore_text(p, meta, textdb)
    return view(meta)


def _restore_text(p: "Paths", meta: dict, textdb: "TextDB | None") -> None:
    container, language = meta["extra"].get("container"), meta["extra"].get("language")
    if textdb is None or not isinstance(container, str) or not CONTAINER_RX.fullmatch(container) or \
            not isinstance(language, str) or not LANGUAGE_RX.fullmatch(language):
        raise BinError(NO_ITEM)
    try:
        dump = json.loads(read_file(p, meta["id"], ROWS_FILE, ROWS_MAX).decode("utf-8"))
        done = textdb.put_back(container, language, dump)
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        raise BinError("the item's texts could not be read back. %s" % KEPT) from None
    if not done:
        raise BinError("Not restored: the text database holds %s (%s) now. Remove that import first. %s"
                       % (container, language, KEPT))
    with _lock:
        _gone(p.bin / meta["id"], meta["id"])
    _log.info("restored from the Deleted bin (imported text): item %s", own(meta["id"]))
    events.emit("bin.changed")
