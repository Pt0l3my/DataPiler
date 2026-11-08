"""The app's side of an update (build plan 0.2 §4.5): update/pending.json and update/result.json, the install check
at each start, the clean-up once the page is up, and update-helper.py loaded as a module.

update-helper.py is the one home of the archive, manifest and plan checks: the app loads that same file, so the app
and the helper prove a zip the same way. Paths here are relative to DataPiler's folder; none reaches a log line or
the page but a path the helper's safe_rel passed, and only relative to the folder."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from . import fileio, logbook
from .logbook import Own, own

UPDATE_DIR = "update"
MANIFEST = "manifest.sha256"
HELPER = "update-helper.py"
PENDING = "update/pending.json"
RESULT = "update/result.json"
APP = Path(__file__).resolve().parents[1]       # the folder this code runs from, where its helper is

SMALL_MAX = 64 * 1024
VERSION_RX = re.compile(r"\d{1,4}\.\d{1,4}\.\d{1,4}")
HEX_RX = re.compile(r"[0-9a-f]{64}")
NONCE_RX = re.compile(r"[0-9a-f]{32}")
RESULT_STATES = ("updated", "failed", "refused", "rolled_back")
RESULT_STAGES = ("checks", "verify", "plan", "backup", "write", "remove", "manifest", "done", "rollback")
TEXT_MAX = 300

log = logbook.get("update")

_helpers: dict[str, ModuleType] = {}
_helpers_lock = threading.Lock()


def helper(root: Path) -> ModuleType:
    """<root>/update-helper.py, loaded once by path (importlib.util.spec_from_file_location). Raises OSError or
    ImportError when it is not there."""
    path = Path(root).resolve() / HELPER
    key = str(path)
    with _helpers_lock:
        mod = _helpers.get(key)
        if mod is None:
            if not path.is_file():
                raise FileNotFoundError(2, "update-helper.py")
            spec = importlib.util.spec_from_file_location("datapiler_update_helper_%d" % len(_helpers), str(path))
            if spec is None or spec.loader is None:
                raise ImportError("update-helper.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod        # dataclasses look their module up while the file runs
            try:
                spec.loader.exec_module(mod)
            except BaseException:
                sys.modules.pop(spec.name, None)
                raise
            _helpers[key] = mod
        return mod


# ---------------------------------------------------------------------------------------------------------- pending


@dataclass(frozen=True)
class Pending:
    from_version: str
    to_version: str
    zip: str            # relative to DataPiler's folder, with "/"
    zip_sha256: str
    zip_size: int
    port: int
    nonce: str
    at: int


def write_pending(root: Path, *, from_version: str, to_version: str, zip_rel: str, zip_sha256: str, zip_size: int,
                  port: int) -> Pending:
    """update/pending.json, for the window's helper: relative paths, the folder's fingerprint, the page's port, a
    nonce, the time. Raises ValueError for a field out of its pattern, OSError when it cannot be written."""
    h = helper(APP)
    p = Pending(from_version=from_version, to_version=to_version, zip=zip_rel, zip_sha256=zip_sha256,
                zip_size=int(zip_size), port=int(port), nonce=secrets.token_hex(16), at=int(time.time()))
    bad = _bad_field(p)
    if bad:
        raise ValueError(bad)
    doc = {"format": h.FORMAT_PENDING, "from": p.from_version, "to": p.to_version, "zip": p.zip,
           "zip_sha256": p.zip_sha256, "zip_size": p.zip_size, "port": p.port, "nonce": p.nonce, "at": p.at,
           "root": h.root_id(Path(root))}
    folder = Path(root) / UPDATE_DIR
    folder.mkdir(exist_ok=True)
    fileio.write_atomic(Path(root) / PENDING, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("ascii"))
    return p


def _bad_field(p: Pending) -> str | None:
    if not VERSION_RX.fullmatch(p.from_version or ""):
        return "from"
    if not VERSION_RX.fullmatch(p.to_version or ""):
        return "to"
    if p.zip != "update/%s/DataPiler-%s.zip" % (p.to_version, p.to_version):
        return "zip"
    if not HEX_RX.fullmatch(p.zip_sha256 or ""):
        return "zip_sha256"
    if not 1 <= p.zip_size <= 256 * 1024 * 1024:
        return "zip_size"
    if not 0 <= p.port <= 65535:
        return "port"
    if not NONCE_RX.fullmatch(p.nonce or ""):
        return "nonce"
    if p.at <= 0:
        return "at"
    return None


def read_pending(root: Path) -> Pending | None:
    """update/pending.json, any age: its format, the folder's fingerprint and every field's pattern checked. A file
    that fails is removed, with a WARN naming the field."""
    path = Path(root) / PENDING
    try:
        raw = fileio.read_limited(path, SMALL_MAX)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log.warn("update/pending.json could not be read: %s - removed", logbook.why(e))
        remove_pending(root)
        return None
    field = "format"
    try:
        doc = json.loads(raw.decode("utf-8"))
        h = helper(APP)
        if not isinstance(doc, dict) or doc.get("format") != h.FORMAT_PENDING:
            raise ValueError
        field = "root"
        if doc.get("root") != h.root_id(Path(root)):
            raise ValueError
        ints = {}
        for k in ("zip_size", "port", "at"):
            field = k
            if type(doc.get(k)) is not int:
                raise ValueError
            ints[k] = doc[k]
        for k in ("from", "to", "zip", "zip_sha256", "nonce"):
            field = k
            if not isinstance(doc.get(k), str):
                raise ValueError
        p = Pending(from_version=doc["from"], to_version=doc["to"], zip=doc["zip"], zip_sha256=doc["zip_sha256"],
                    zip_size=ints["zip_size"], port=ints["port"], nonce=doc["nonce"], at=ints["at"])
        field = _bad_field(p) or ""
        if field:
            raise ValueError
        return p
    except (ValueError, OSError, ImportError):
        log.warn("update/pending.json is not as DataPiler writes it (%s) - removed", own(field or "format"))
        remove_pending(root)
        return None


def remove_pending(root: Path) -> None:
    try:
        os.remove(Path(root) / PENDING)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warn("update/pending.json could not be removed: %s", logbook.why(e))


# ---------------------------------------------------------------------------------------------------------- the install check


@dataclass(frozen=True)
class Check:
    manifest: bool                  # this copy has a manifest.sha256 (it was unpacked from a release)
    files: int                      # the files it lists
    differ: tuple[Own, ...]         # listed, here, with another sha256
    missing: tuple[Own, ...]        # listed, not here


def install_check(root: Path) -> Check:
    """Each file manifest.sha256 lists, hashed (its paths checked by the helper's safe_rel). A statement, never a
    repair."""
    root = Path(root)
    try:
        raw = fileio.read_limited(root / MANIFEST, 1024 * 1024)
    except FileNotFoundError:
        return Check(manifest=False, files=0, differ=(), missing=())
    except (OSError, ValueError):
        return Check(manifest=True, files=0, differ=(own("manifest.sha256"),), missing=())
    try:
        listed = helper(APP).parse_manifest(raw)
    except (ValueError, OSError, ImportError):
        return Check(manifest=True, files=0, differ=(own("manifest.sha256"),), missing=())
    differ: list[Own] = []
    missing: list[Own] = []
    for rel in sorted(listed):
        p = root / rel
        try:
            if not p.is_file():
                missing.append(own(rel))
            elif fileio.sha256_file(p) != listed[rel]:
                differ.append(own(rel))
        except OSError:
            differ.append(own(rel))
    return Check(manifest=True, files=len(listed), differ=tuple(differ), missing=tuple(missing))


def check_line(c: Check) -> None:
    """The install check's log line (build plan 0.2 §4.8)."""
    if not c.manifest:
        log.info("install check: no manifest.sha256 - a copy from the repository, not a release")
        return
    off = list(c.differ) + list(c.missing)
    if not off:
        log.info("install check: all %s files match the release", logbook.n(c.files))
        return
    shown = ", ".join(off[:10]) + (" and %s more" % logbook.n(len(off) - 10) if len(off) > 10 else "")
    log.warn("install check: %s files differ from the release: %s", logbook.n(len(off)), own(shown))


# ---------------------------------------------------------------------------------------------------------- the result


def read_result(root: Path, nonce: str) -> dict | None:
    """update/result.json, when its nonce is nonce: its fields checked and rebuilt, the text masked and cut at 300
    characters, paths relative to DataPiler's folder only. None otherwise."""
    if not isinstance(nonce, str) or not NONCE_RX.fullmatch(nonce):
        return None
    try:
        doc = json.loads(fileio.read_limited(Path(root) / RESULT, SMALL_MAX).decode("utf-8"))
    except (OSError, ValueError):
        return None
    try:
        h = helper(APP)
        fmt = h.FORMAT_RESULT
    except (OSError, ImportError):
        fmt = "datapiler-update-result/1"
    if not isinstance(doc, dict) or doc.get("format") != fmt or doc.get("nonce") != nonce:
        return None
    state = doc.get("state")
    if state not in RESULT_STATES:
        return None
    out: dict = {"state": state}
    for k in ("from", "to"):
        v = doc.get(k)
        out[k] = v if isinstance(v, str) and VERSION_RX.fullmatch(v) else None
    stage = doc.get("stage")
    out["stage"] = stage if stage in RESULT_STAGES else None
    text = doc.get("text")
    out["text"] = logbook.mask(text)[:TEXT_MAX] if isinstance(text, str) and text else None
    counts = doc.get("counts")
    if isinstance(counts, dict):
        out["counts"] = {k: counts[k] for k in ("written", "added", "removed", "same", "files")
                         if type(counts.get(k)) is int and counts[k] >= 0}
    else:
        out["counts"] = None
    backup = doc.get("backup")
    m = re.fullmatch(r"update/(backup-\d{1,4}\.\d{1,4}\.\d{1,4})", backup) if isinstance(backup, str) else None
    out["backup"] = "update\\%s" % m.group(1) if m else None
    out["restored"] = doc.get("restored") if isinstance(doc.get("restored"), bool) else None
    out["log"] = "logs\\update.log"
    return out


# ---------------------------------------------------------------------------------------------------------- clean-up


def _inside(root: Path, p: Path) -> bool:
    try:
        r = os.path.realpath(root)
        t = os.path.realpath(p)
        if sys.platform == "win32":
            r, t = os.path.normcase(r), os.path.normcase(t)
        return t != r and os.path.commonpath([r, t]) == r
    except (OSError, ValueError):
        return False


def cleanup(root: Path) -> None:
    """At page-up: every update/<X.Y.Z>/ folder (a download not installed, the helper taken from one), any .part
    left in update/, and the .old files the latest backup.json lists (each still inside root). Never anything
    else."""
    root = Path(root)
    folder = root / UPDATE_DIR
    if not folder.is_dir() or folder.is_symlink():
        return
    removed = 0
    failed = 0
    try:
        entries = list(os.scandir(folder))
    except OSError as e:
        log.warn("the update folder could not be read: %s", logbook.why(e))
        return
    backups = []
    for e in entries:
        p = Path(e.path)
        try:
            if e.is_dir(follow_symlinks=False) and VERSION_RX.fullmatch(e.name):
                if _inside(root, p):
                    shutil.rmtree(p)
                    removed += 1
            elif e.is_file(follow_symlinks=False) and e.name.endswith(".part"):
                os.remove(p)
                removed += 1
            elif e.is_dir(follow_symlinks=False) and re.fullmatch(r"backup-\d{1,4}\.\d{1,4}\.\d{1,4}", e.name):
                backups.append(p)
        except OSError:
            failed += 1
    latest = max(backups, key=lambda b: _mtime(b / "backup.json"), default=None)
    aside = 0
    if latest is not None:
        try:
            j = helper(APP).read_journal(latest)
            for rel in j.aside:
                p = root / rel
                if not rel.endswith(".old") or not _inside(root, p) or not p.is_file() or p.is_symlink():
                    continue
                try:
                    os.remove(p)
                    aside += 1
                except OSError:
                    failed += 1
        except (OSError, ValueError, ImportError):
            pass
    if removed or aside:
        log.info("clean-up: %s download folder(s) or part files removed, %s file(s) set aside by the last update "
                 "removed", logbook.n(removed), logbook.n(aside))
    if failed:
        log.warn("clean-up: %s file(s) or folder(s) in update/ could not be removed", logbook.n(failed))


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def sha256_of(path: Path) -> str | None:
    """A file's sha256, or None when it cannot be read."""
    try:
        return fileio.sha256_file(path)
    except OSError:
        return None


def lock_sha256(root: Path) -> str | None:
    """This copy's requirements.lock, as the release manifest hashes it."""
    return sha256_of(Path(root) / "requirements.lock")


def manifest_here(root: Path) -> dict[str, str] | None:
    """This copy's manifest.sha256, parsed; None when there is none or it does not parse."""
    try:
        return helper(APP).parse_manifest(fileio.read_limited(Path(root) / MANIFEST, 1024 * 1024))
    except (OSError, ValueError, ImportError):
        return None


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
