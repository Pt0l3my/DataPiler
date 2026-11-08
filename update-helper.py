#!/usr/bin/env python3
"""DataPiler's update helper (design 0002 §2.5; build plan 0.2 §4.6). Standard library only, and no network.

    python update\\<to>\\update-helper.py --pending update\\pending.json     the swap, run by DataPiler.ps1 on exit 75
    python update\\<to>\\update-helper.py --rollback update\\backup-<from>   the owner's R, after a failed start;
                                                                         the window's, after a swap cut off
    python update-helper.py --check-zip <zip> --version <X.Y.Z>             read only: the release workflow's check

It is the one home of the archive, manifest and plan checks: the app loads this same file to prove a download
(datapiler/install.py), so the app and the helper prove a zip the same way. For the swap and the rollback it runs as
the copy taken from the verified download, update\\<to>\\update-helper.py, and DataPiler's folder is the folder two
above it, which update\\pending.json must name.

The swap acts only on a pending file under ten minutes old that names this folder, with DataPiler's mutex free. It
backs up every file it will overwrite or remove, writes each new file beside its target, puts it in place, checks
the file that landed, moves removed files into the backup, and on any failure puts everything back. Ctrl+C is held
off while it swaps; a swap cut off all the same (the window closed, the power cut) leaves backup.json unfinished,
and --rollback puts it back while update\\pending.json still names that update. It never touches NEVER, nor the
workspace and share folders settings.json names inside DataPiler's folder, by name or by an 8.3 short name. Its exit
codes: 0 swapped, 1 failed and put back, 2 refused with nothing touched.

Its words: ASCII console lines (settled S38) and logs/update.log in DataPiler's line format, source "update", with
DataPiler's folder shown as <DATAPILER> and the home folder as <HOME>. A reason names DataPiler's relative paths and
an exception's type and errno, never the exception's own text."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

FORMAT_PENDING = "datapiler-update-pending/1"
FORMAT_RESULT = "datapiler-update-result/1"
FORMAT_BACKUP = "datapiler-update-backup/1"
TOP = "DataPiler"
MAX_MEMBERS = 2000
MAX_UNPACKED = 256 * 1024 * 1024
PENDING_SECS = 600
MUTEX = "Local\\DataPiler"
NEVER = ("workspace", "share", "logs", "jobs", "update", ".venv", ".venv.new", ".venv.prev",
         "settings.json", "datapiler.port", "datapiler-start.log", "datapiler.lock")

MANIFEST = "manifest.sha256"
HELPER = "update-helper.py"
INIT = "datapiler/__init__.py"
LOCK = "requirements.lock"
CHUNK = 64 * 1024
ZIP_MAX = 256 * 1024 * 1024
MANIFEST_MAX = 1024 * 1024
SMALL_MAX = 64 * 1024           # pending.json, settings.json, result.json
BACKUP_MAX = 4 * 1024 * 1024    # backup.json
SKEW = 60                       # seconds a pending file may seem to come from the future (clocks)

VERSION_RX = re.compile(r'^VERSION\s*=\s*"(\d+\.\d+\.\d+)"\s*$', re.M)
SEMVER_RX = re.compile(r"\d{1,4}\.\d{1,4}\.\d{1,4}")
HEX_RX = re.compile(r"[0-9a-f]{64}")
NONCE_RX = re.compile(r"[0-9a-f]{32}")
LINE_RX = re.compile(r"([0-9a-f]{64})  (.+)")
# Windows' device names, whatever follows the dot (paths.RESERVED_RX's list, written out here)
DEVICE_RX = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9]|conin\$|conout\$)", re.I)
BAD_CHAR_RX = re.compile(r'[\x00-\x1f\x7f<>:"\\|?*]')
# Windows' 8.3 short names (WORKSP~1, SETTIN~1.JSO): an alias of another name, so never a name a release ships
SHORT_RX = re.compile(r"~[0-9]")
STAGES = ("checks", "verify", "plan", "backup", "write", "remove", "manifest", "done")


class Refused(Exception):
    """Nothing was touched: exit 2. stage is the step that refused, text DataPiler's words."""

    def __init__(self, stage: str, text: str):
        super().__init__(stage)
        self.stage = stage
        self.text = text


class Failed(Exception):
    """A step of the swap failed: everything is put back, exit 1."""

    def __init__(self, stage: str, text: str):
        super().__init__(stage)
        self.stage = stage
        self.text = text


def why(e: BaseException) -> str:
    """An exception's type, with errno for an OSError. Never str(e), which can name a path."""
    name = type(e).__name__
    if isinstance(e, OSError) and isinstance(e.errno, int):
        return "%s (errno %d)" % (name, e.errno)
    return name


def n(x: int) -> str:
    return "{:,}".format(int(x))


# ---------------------------------------------------------------------------------------------------------- paths


def safe_rel(path: str) -> bool:
    """Relative, '/' only, no '..' or '.' part, no drive, no ':', no backslash, no control character, no part
    ending in a dot or a space, no device name, no 8.3 short name's '~<digit>', none of Windows' refused
    characters."""
    if not isinstance(path, str) or not path or len(path) > 400:
        return False
    if path.startswith("/") or BAD_CHAR_RX.search(path):
        return False
    for part in path.split("/"):
        if part in ("", ".", ".."):
            return False
        if part.endswith(".") or part.endswith(" "):
            return False
        if DEVICE_RX.fullmatch(part.split(".", 1)[0]):
            return False
        if SHORT_RX.search(part):
            return False
    return True


def _fold(s: str) -> str:
    return s.casefold()


def root_id(root: Path) -> str:
    """pending.json's fingerprint of DataPiler's folder: the sha256 of the case-folded, resolved folder."""
    return hashlib.sha256(_fold(str(Path(root).resolve())).encode("utf-8")).hexdigest()


def _norm(p: str) -> str:
    p = os.path.normpath(p)
    return os.path.normcase(p) if sys.platform == "win32" else p


def _inside(root: Path, target: Path) -> bool:
    """target, every link in it resolved, lies inside root (and is not root itself)."""
    r = _norm(os.path.realpath(root))
    t = _norm(os.path.realpath(target))
    if t == r:
        return False
    try:
        return os.path.commonpath([r, t]) == r
    except ValueError:      # another drive
        return False


def _in(rel: str, folders: Iterable[str]) -> bool:
    """rel is one of folders, or lies inside one (case-folded: Windows' folders are)."""
    r = _fold(rel)
    for f in folders:
        f = _fold(f.strip("/"))
        if f and (r == f or r.startswith(f + "/")):
            return True
    return False


# ---------------------------------------------------------------------------------------------------------- hashes


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _read_limited(path: Path, limit: int) -> bytes:
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError("too large")
    return data


# ---------------------------------------------------------------------------------------------------------- the manifest


def parse_manifest(data: bytes) -> dict[str, str]:
    """manifest.sha256: '<64 hex>  <path>' lines, UTF-8, LF, each path safe_rel and listed once (case-folded), the
    manifest itself never listed. Raises ValueError with DataPiler's words."""
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("not bytes")
    if len(data) > MANIFEST_MAX:
        raise ValueError("the manifest is larger than 1 MiB")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("the manifest is not UTF-8") from None
    if text.startswith("﻿"):
        raise ValueError("the manifest starts with a byte-order mark")
    if "\r" in text:
        raise ValueError("the manifest has a CR - its lines end in LF only")
    if text and not text.endswith("\n"):
        raise ValueError("the manifest's last line has no LF")
    out: dict[str, str] = {}
    seen: set[str] = set()
    for i, line in enumerate(text.split("\n")[:-1] if text else [], start=1):
        m = LINE_RX.fullmatch(line)
        if not m:
            raise ValueError("line %d of the manifest is not '<sha256>  <path>'" % i)
        h, rel = m.group(1), m.group(2)
        if not safe_rel(rel):
            raise ValueError("line %d of the manifest names a path DataPiler does not write" % i)
        if rel == MANIFEST:
            raise ValueError("the manifest lists itself (line %d)" % i)
        key = _fold(rel)
        if key in seen:
            raise ValueError("line %d of the manifest lists a file a second time" % i)
        seen.add(key)
        out[rel] = h
    return out


def format_manifest(entries: dict[str, str]) -> bytes:
    """The manifest's bytes: sorted by the UTF-8 bytes of the path, LF."""
    lines = ["%s  %s\n" % (entries[p], p) for p in sorted(entries, key=lambda p: p.encode("utf-8"))]
    return "".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------------------------------------- the archive


@dataclass
class Archive:
    manifest: dict[str, str]        # path inside TOP -> sha256, every file but the manifest
    files: int                      # the files the manifest lists
    unpacked: int                   # bytes, as read
    version: str                    # datapiler/__init__.py's VERSION
    lock_sha256: str | None         # requirements.lock's sha256, if the release has one


def _is_link(zi: zipfile.ZipInfo) -> bool:
    mode = (zi.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        return True
    return bool(zi.external_attr & 0x400)     # FILE_ATTRIBUTE_REPARSE_POINT, from a Windows zip tool


def _members(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """The zip's directory, checked before any member is read: every name under TOP/, safe, once, no link, no
    encryption, stored or deflated, at most MAX_MEMBERS. Returns the file members by their path inside TOP."""
    infos = zf.infolist()
    if len(infos) > MAX_MEMBERS:
        raise Refused("shape", "the zip holds more than %s entries" % n(MAX_MEMBERS))
    prefix = TOP + "/"
    files: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()
    declared = 0
    for zi in infos:
        name = zi.orig_filename      # as stored: zipfile turns a backslash into "/" on Windows in filename
        if not isinstance(name, str) or BAD_CHAR_RX.search(name) or name.startswith("/") or ".." in name.split("/"):
            raise Refused("shape", "the zip names a path DataPiler does not write (an absolute path, a drive, "
                                   "'..', a backslash or a refused character)")
        if not name.startswith(prefix):
            if name.endswith("/") or "/" in name:
                raise Refused("shape", "the zip has a second top folder beside %s" % TOP)
            raise Refused("shape", "the zip has a file at its top, beside the %s folder" % TOP)
        rel = name[len(prefix):]
        is_dir = name.endswith("/")
        if is_dir:
            rel = rel[:-1] if rel.endswith("/") else rel
        if rel and not safe_rel(rel):
            raise Refused("shape", "the zip names a path DataPiler does not write (an absolute path, a drive, "
                                   "'..', a backslash or a refused character)")
        if _is_link(zi):
            raise Refused("shape", "the zip holds a link")
        if zi.flag_bits & 0x1:
            raise Refused("shape", "the zip holds an encrypted entry")
        if not is_dir and zi.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise Refused("shape", "the zip holds an entry packed in a way DataPiler does not read")
        key = _fold(rel) + ("/" if is_dir else "")
        if key in seen:
            raise Refused("shape", "the zip names one path twice")
        seen.add(key)
        if is_dir:
            continue
        if not rel:
            raise Refused("shape", "the zip has a file where its %s folder should be" % TOP)
        declared += max(0, zi.file_size)
        files[rel] = zi
    # a file and a folder of one name (case-folded) cannot both be unpacked
    folders = {k[:-1] for k in seen if k.endswith("/")}
    for rel in files:
        parts = _fold(rel).split("/")
        for i in range(1, len(parts)):
            folders.add("/".join(parts[:i]))
    if any(_fold(rel) in folders for rel in files):
        raise Refused("shape", "the zip has a file and a folder of the same name")
    if declared > MAX_UNPACKED:
        raise Refused("shape", "the zip would unpack to more than %s MiB" % n(MAX_UNPACKED // (1024 * 1024)))
    return files


def _stream(zf: zipfile.ZipFile, zi: zipfile.ZipInfo, budget: list[int], keep: bool = False) -> tuple[str, bytes]:
    """A member read once, its size counted as it is read against what is left of MAX_UNPACKED."""
    h = hashlib.sha256()
    kept = bytearray()
    with zf.open(zi) as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            budget[0] -= len(b)
            if budget[0] < 0:
                raise Refused("manifest", "the zip unpacks to more than %s MiB" % n(MAX_UNPACKED // (1024 * 1024)))
            h.update(b)
            if keep:
                kept += b
                if len(kept) > MANIFEST_MAX:
                    raise Refused("manifest", "a file DataPiler reads from the zip is larger than 1 MiB")
    return h.hexdigest(), bytes(kept)


def check_archive(zip_path: Path, *, version: str) -> Archive:
    """The shape from the zip's directory first, then every file member read once: its size counted as read
    (MAX_UNPACKED), its sha256 against DataPiler/manifest.sha256, which must list every file member but itself;
    update-helper.py listed; datapiler/__init__.py's VERSION line is version. Raises Refused with stage "shape",
    "manifest" or "version"."""
    if not SEMVER_RX.fullmatch(version or ""):
        raise Refused("version", "the release's version is not one DataPiler reads")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            files = _members(zf)
            budget = [MAX_UNPACKED]
            mzi = files.pop(MANIFEST, None)
            if mzi is None:
                raise Refused("manifest", "the zip holds no %s/%s" % (TOP, MANIFEST))
            _, raw = _stream(zf, mzi, budget, keep=True)
            try:
                manifest = parse_manifest(raw)
            except ValueError as e:
                raise Refused("manifest", "its manifest: %s" % e.args[0]) from None
            unlisted = [rel for rel in files if rel not in manifest]
            if unlisted:
                raise Refused("manifest", "the zip holds %s file(s) its manifest does not list" % n(len(unlisted)))
            missing = [rel for rel in manifest if rel not in files]
            if missing:
                raise Refused("manifest", "its manifest lists %s file(s) the zip does not hold" % n(len(missing)))
            if HELPER not in manifest:
                raise Refused("manifest", "its manifest does not list %s" % HELPER)
            if INIT not in manifest:
                raise Refused("manifest", "its manifest does not list %s" % INIT)
            init = b""
            for rel in sorted(files):
                got, body = _stream(zf, files[rel], budget, keep=(rel == INIT))
                if got != manifest[rel]:
                    raise Refused("manifest", "%s does not match its sha256 in the manifest" % rel)
                if rel == INIT:
                    init = body
            m = VERSION_RX.search(init.decode("utf-8", "replace"))
            inside = m.group(1) if m else None
            if inside != version:
                raise Refused("version", "the version inside is %s, not the release's %s" % (inside or "not read",
                                                                                              version))
            lock = manifest.get(LOCK)
            return Archive(manifest=manifest, files=len(manifest), unpacked=MAX_UNPACKED - budget[0],
                           version=inside, lock_sha256=lock)
    except Refused:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, NotImplementedError, RuntimeError):
        raise Refused("shape", "it is not a zip DataPiler can read, or a member does not read back as "
                               "stored") from None
    except OSError as e:
        raise Refused("shape", "the zip could not be read: %s" % why(e)) from None


# ---------------------------------------------------------------------------------------------------------- the plan


@dataclass
class Plan:
    write: list[str] = field(default_factory=list)      # in new, on disk, another hash
    add: list[str] = field(default_factory=list)        # in new, not on disk
    remove: list[str] = field(default_factory=list)     # in old, not in new, on disk
    same: list[str] = field(default_factory=list)       # on disk with new's hash
    edited: list[str] = field(default_factory=list)     # on disk with a hash other than old's


def plan(root: Path, new: dict[str, str], old: dict[str, str] | None) -> Plan:
    """What the swap does to each file the manifests name. A path that is not a regular file on disk (a folder) is
    planned as a write; the swap's plan stage refuses it."""
    root = Path(root)
    old = old or {}
    p = Plan()
    for rel in sorted(new):
        target = root / rel
        if target.is_file():
            h = sha256_file(target)
            if h == new[rel]:
                p.same.append(rel)
            else:
                p.write.append(rel)
            if rel in old and h != old[rel]:
                p.edited.append(rel)
        elif os.path.lexists(target):
            p.write.append(rel)
        else:
            p.add.append(rel)
    folded = {}
    for rel in new:
        folded.setdefault(_fold(rel), rel)
    for rel in sorted(old):
        if rel in new:
            continue
        target = root / rel
        renamed = folded.get(_fold(rel))
        if renamed is not None and _same_file(target, root / renamed):
            # a name whose case alone changed, on a folder that ignores case (Windows): the one file is rewritten
            # or kept under its new name, never removed after it
            continue
        if target.is_file():
            p.remove.append(rel)
            if sha256_file(target) != old[rel]:
                p.edited.append(rel)
    p.edited.sort()
    return p


def _same_file(a: Path, b: Path) -> bool:
    """a and b are one file on disk (a seam the tests plant a case-insensitive folder in)."""
    try:
        return os.path.samefile(a, b)
    except (OSError, ValueError):
        return False


def _real_rel(root: Path, rel: str) -> str | None:
    """rel as the file system resolves it below root, '/' separated: on Windows realpath expands an 8.3 short name
    (WORKSP~1) to its long name, even for a missing file below an existing folder. None when it leads elsewhere."""
    try:
        r = os.path.relpath(os.path.realpath(Path(root) / rel), os.path.realpath(root))
    except (OSError, ValueError):       # another drive
        return None
    r = r.replace(os.sep, "/")
    if r == ".." or r.startswith("../"):
        return None
    return r


def never_touched(root: Path) -> list[str]:
    """NEVER, plus settings.json's workspace_dir and share_dir when they lie inside root (settings.json read, at
    most 64 KiB, those two keys only)."""
    root = Path(root)
    out = list(NEVER)
    try:
        doc = json.loads(_read_limited(root / "settings.json", SMALL_MAX).decode("utf-8-sig"))
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict):
        for key in ("workspace_dir", "share_dir"):
            v = doc.get(key)
            if not isinstance(v, str) or not v.strip() or "\x00" in v:
                continue
            p = Path(os.path.expanduser(v.strip())) if v.strip().startswith("~") else Path(v.strip())
            if not p.is_absolute():
                p = root / p
            try:
                rel = os.path.relpath(os.path.realpath(p), os.path.realpath(root))
            except ValueError:      # another drive
                continue
            rel = rel.replace(os.sep, "/")
            if rel == "." or rel.startswith("../") or rel == "..":
                if rel == ".":
                    out.append("")          # the whole folder: nothing may be touched
                continue
            out.append(rel)
    return out


# ---------------------------------------------------------------------------------------------------------- words


def _folder_rx(folder: str) -> str | None:
    pieces = [p for p in re.split(r"[\\/]+", folder.strip()) if p]
    if not pieces:
        return None
    lead = r"[\\/]+" if folder.strip()[:1] in ("/", "\\") else ""
    return lead + r"[\\/]+".join(re.escape(p) for p in pieces)


class Narrator:
    """The window's lines ('[HH:MM:SS] ok ...', '! ...', 'x ...', ASCII) and logs/update.log in DataPiler's format,
    both with DataPiler's folder as <DATAPILER> and the home folder as <HOME>."""

    def __init__(self, root: Path, say: Callable[[str], None]):
        self.root = Path(root)
        self.say = say
        alts = []
        for f in {str(root), os.path.realpath(root)}:
            rx = _folder_rx(f)
            if rx:
                alts.append(rx)
        self._root_rx = re.compile("|".join(sorted(alts, key=len, reverse=True)), re.I) if alts else None
        homes = []
        for h in (os.environ.get("USERPROFILE"), os.environ.get("HOME")):
            if h and len(h.strip("\\/")) > 2:
                rx = _folder_rx(h)
                if rx:
                    homes.append(rx)
        self._home_rx = re.compile("|".join(sorted(set(homes), key=len, reverse=True)), re.I) if homes else None

    def mask(self, text: str) -> str:
        text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text))
        if self._root_rx is not None:
            text = self._root_rx.sub("<DATAPILER>", text)
        if self._home_rx is not None:
            text = self._home_rx.sub("<HOME>", text)
        return text

    def _write(self, level: str, mark: str, text: str) -> None:
        text = self.mask(text)
        now = time.time()
        clock = time.strftime("%H:%M:%S", time.localtime(now))
        line = ("[%s] %s %s" % (clock, mark, text) if mark else "[%s] %s" % (clock, text)).rstrip()
        try:
            self.say(line.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass
        stamp = "%s.%03d" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), int((now % 1) * 1000))
        try:
            logs = self.root / "logs"
            logs.mkdir(exist_ok=True)
            with open(logs / "update.log", "a", encoding="utf-8") as f:
                f.write("%s  %-5s  %-8s %s\n" % (stamp, level, "update", text))
        except OSError:
            pass

    def info(self, text: str) -> None:
        self._write("INFO", "", text)

    def ok(self, text: str) -> None:
        self._write("INFO", "ok", text)

    def warn(self, text: str) -> None:
        self._write("WARN", "!", text)

    def bad(self, text: str) -> None:
        self._write("ERROR", "x", text)


# ---------------------------------------------------------------------------------------------------------- the mutex


def hold_mutex(root: Path, name: str) -> Callable[[], None] | None:
    """DataPiler's mutex, taken for the swap; None when another holds it. Windows: CreateMutexW by name.
    Elsewhere: flock on datapiler.lock, as the Windows adapter's fallback does."""
    if sys.platform == "win32":     # pragma: no cover - exercised by the Windows run in CI
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k.CreateMutexW(None, False, name)
        err = ctypes.get_last_error()
        if not h:
            raise OSError(err, "mutex")
        if err == 183:      # ERROR_ALREADY_EXISTS
            k.CloseHandle(h)
            return None
        return lambda: k.CloseHandle(h)
    import fcntl
    fd = os.open(str(Path(root) / "datapiler.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None

    def release() -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    return release


# ---------------------------------------------------------------------------------------------------------- files


def _write_json(path: Path, doc: dict) -> None:
    """A small state file of the helper's own (backup.json, result.json): written beside, then put in place."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=True, indent=1, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _copy(src: Path, dst: Path) -> str:
    """A backup copy: src streamed to dst, hashed; the copy hashed again where it landed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            b = fi.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
        fo.flush()
        os.fsync(fo.fileno())
    got = h.hexdigest()
    if sha256_file(dst) != got:
        raise Failed("backup", "the backup copy of a file did not read back as written")
    return got


def _remove(path: Path) -> None:
    os.remove(path)


def _landed(path: Path) -> str:
    """The sha256 of a file where it landed (a seam the tests plant a failure in)."""
    return sha256_file(path)


def _put(source: BinaryIO, root: Path, rel: str, expect: str, replace: Callable, journal: "Journal | None",
         stage: str) -> None:
    """source streamed to <target>.dpnew and hashed, the target's resolution checked again, then put in place; a
    held target (PermissionError) is set aside as <target>.old and the new file put in place again; the landed file
    hashed against expect."""
    target = root / rel
    if not _inside(root, target):
        raise Failed(stage, "%s leads outside DataPiler's folder" % rel)
    tmp = target.with_name(target.name + ".dpnew")
    h = hashlib.sha256()
    with open(tmp, "wb") as fo:
        while True:
            b = source.read(CHUNK)
            if not b:
                break
            h.update(b)
            fo.write(b)
        fo.flush()
        os.fsync(fo.fileno())
    if h.hexdigest() != expect:
        _quiet_remove(tmp)
        raise Failed(stage, "%s did not come out of the zip as its manifest says" % rel)
    if not _inside(root, target):
        _quiet_remove(tmp)
        raise Failed(stage, "%s leads outside DataPiler's folder" % rel)
    try:
        try:
            replace(tmp, target)
        except PermissionError:
            aside = target.with_name(target.name + ".old")
            replace(target, aside)
            if journal is not None:
                journal.aside.append(rel + ".old")
                journal.save()
            replace(tmp, target)
    except BaseException:
        _quiet_remove(tmp)
        raise
    if _landed(target) != expect:
        raise Failed(stage, "%s did not land as the release has it" % rel)


def _quiet_remove(path: Path) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------- the journal


@dataclass
class Journal:
    """backup.json: what the swap backed up and did, so it can be put back, and R can roll it back."""

    folder: Path
    from_version: str
    to_version: str
    nonce: str
    complete: bool = False
    files: list[dict] = field(default_factory=list)     # {"path", "sha256"}: each copy in files/<path>
    added: list[str] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)       # folders the swap made, outermost first
    aside: list[str] = field(default_factory=list)      # <path>.old files set aside
    manifest: bool = False                              # the old manifest.sha256 is in the backup

    def doc(self) -> dict:
        return {"format": FORMAT_BACKUP, "from": self.from_version, "to": self.to_version, "nonce": self.nonce,
                "complete": self.complete, "files": self.files, "added": self.added, "dirs": self.dirs,
                "aside": self.aside, "manifest": self.manifest}

    def save(self) -> None:
        _write_json(self.folder / "backup.json", self.doc())


def read_journal(folder: Path) -> Journal:
    """backup.json read back and checked: its format, its versions, every path safe. Raises ValueError."""
    doc = json.loads(_read_limited(Path(folder) / "backup.json", BACKUP_MAX).decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT_BACKUP:
        raise ValueError("backup.json is not one this helper wrote")
    fv, tv, nonce = doc.get("from"), doc.get("to"), doc.get("nonce")
    if not (isinstance(fv, str) and SEMVER_RX.fullmatch(fv) and isinstance(tv, str) and SEMVER_RX.fullmatch(tv)):
        raise ValueError("backup.json's versions are not versions")
    if not (isinstance(nonce, str) and NONCE_RX.fullmatch(nonce)):
        raise ValueError("backup.json's nonce is not one")
    j = Journal(folder=Path(folder), from_version=fv, to_version=tv, nonce=nonce,
                complete=doc.get("complete") is True, manifest=doc.get("manifest") is True)
    for rec in doc.get("files") or []:
        if not (isinstance(rec, dict) and safe_rel(rec.get("path")) and isinstance(rec.get("sha256"), str)
                and HEX_RX.fullmatch(rec["sha256"])):
            raise ValueError("backup.json lists a file it should not")
        j.files.append({"path": rec["path"], "sha256": rec["sha256"]})
    for key in ("added", "dirs", "aside"):
        for rel in doc.get(key) or []:
            if not safe_rel(rel):
                raise ValueError("backup.json lists a path it should not")
            getattr(j, key).append(rel)
    return j


def _put_back(root: Path, j: Journal, replace: Callable, out: Narrator, *, always: bool,
              counts: dict | None = None) -> bool:
    """Every backed-up file written back and hashed, every added file removed, the old manifest put back, the
    folders the swap made removed when empty. always: write back even a file whose hash is already right (R).
    counts, when given, gets the files written back ("written") and the added files removed ("removed")."""
    ok = True
    done = {"written": 0, "removed": 0}
    for rec in j.files:
        rel, expect = rec["path"], rec["sha256"]
        target = root / rel
        try:
            if not always and target.is_file() and sha256_file(target) == expect:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(j.folder / "files" / rel, "rb") as src:
                _put(src, root, rel, expect, replace, None, "restore")
            done["written"] += 1
        except (Failed, OSError) as e:
            ok = False
            out.bad("%s could not be put back: %s" % (rel, e.text if isinstance(e, Failed) else why(e)))
    for rel in j.added:
        target = root / rel
        try:
            if os.path.lexists(target) and _inside(root, target):
                _remove(target)
                done["removed"] += 1
        except OSError as e:
            ok = False
            out.bad("%s, which the update added, could not be removed: %s" % (rel, why(e)))
    if j.manifest:
        src_path = j.folder / MANIFEST
        try:
            expect = sha256_file(src_path)
            target = root / MANIFEST
            if always or not (target.is_file() and sha256_file(target) == expect):
                with open(src_path, "rb") as src:
                    _put(src, root, MANIFEST, expect, replace, None, "restore")
        except (Failed, OSError) as e:
            ok = False
            out.bad("%s could not be put back: %s" % (MANIFEST, e.text if isinstance(e, Failed) else why(e)))
    for rel in reversed(j.dirs):
        try:
            os.rmdir(root / rel)
        except OSError:
            pass
    if counts is not None:
        counts.update(done)
    return ok


# ---------------------------------------------------------------------------------------------------------- pending


def _read_pending(root: Path, pending: Path, now: float) -> dict:
    expected = root / "update" / "pending.json"
    if _norm(os.path.realpath(pending)) != _norm(os.path.realpath(expected)):
        raise Refused("checks", "the pending file is not update\\pending.json in this DataPiler's folder")
    try:
        doc = json.loads(_read_limited(pending, SMALL_MAX).decode("utf-8"))
    except FileNotFoundError:
        raise Refused("checks", "there is no update\\pending.json - press Install and restart on the page") from None
    except (OSError, ValueError):
        raise Refused("checks", "update\\pending.json could not be read as DataPiler writes it") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT_PENDING:
        raise Refused("checks", "update\\pending.json is not one DataPiler wrote")
    for key, ok in (("from", lambda v: isinstance(v, str) and SEMVER_RX.fullmatch(v)),
                    ("to", lambda v: isinstance(v, str) and SEMVER_RX.fullmatch(v)),
                    ("zip_sha256", lambda v: isinstance(v, str) and HEX_RX.fullmatch(v)),
                    ("zip_size", lambda v: type(v) is int and 1 <= v <= ZIP_MAX),
                    ("port", lambda v: type(v) is int and 0 <= v <= 65535),
                    ("nonce", lambda v: isinstance(v, str) and NONCE_RX.fullmatch(v)),
                    ("at", lambda v: type(v) is int and v > 0),
                    ("root", lambda v: isinstance(v, str) and HEX_RX.fullmatch(v))):
        if not ok(doc.get(key)):
            raise Refused("checks", "update\\pending.json's %s is not as DataPiler writes it" % key)
    if doc.get("zip") != "update/%s/DataPiler-%s.zip" % (doc["to"], doc["to"]):
        raise Refused("checks", "update\\pending.json names a zip outside update\\%s\\" % doc["to"])
    if doc["root"] != root_id(root):
        raise Refused("checks", "update\\pending.json was written for another DataPiler folder")
    age = now - doc["at"]
    if age > PENDING_SECS or age < -SKEW:
        raise Refused("checks", "update\\pending.json is older than ten minutes - press Install and restart again "
                                "on the page")
    return doc


def _result(root: Path, doc: dict) -> None:
    try:
        (root / "update").mkdir(exist_ok=True)
        _write_json(root / "update" / "result.json", doc)
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------------------- install


def hold_off_interrupts() -> Callable[[], None]:
    """Ctrl+C ignored until the returned function is called, so the swap is never cut off between two files: SIGINT
    (the main thread only), and on Windows the console's Ctrl+C for this process as well. Closing the window or a
    power cut can still stop it: rollback() then puts back an unfinished swap."""
    undo: list[Callable[[], object]] = []
    try:
        old = signal.signal(signal.SIGINT, signal.SIG_IGN)
        if old is not None:
            undo.append(lambda: signal.signal(signal.SIGINT, old))
    except (ValueError, OSError, AttributeError):       # not the main thread
        pass
    if sys.platform == "win32":     # pragma: no cover - exercised by the Windows run in CI
        try:
            import ctypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            if k.SetConsoleCtrlHandler(None, True):
                undo.append(lambda: k.SetConsoleCtrlHandler(None, False))
        except (OSError, AttributeError):
            pass

    def restore() -> None:
        for u in reversed(undo):
            try:
                u()
            except (ValueError, OSError, TypeError):
                pass

    return restore


def install(root: Path, pending: Path, *, mutex: str = MUTEX, now: Callable[[], float] = time.time,
            replace: Callable = os.replace, say: Callable[[str], None] = print) -> int:
    """The swap, by stage (build plan 0.2 §4.6): checks, verify, plan (exit 2, nothing touched), then backup,
    write, remove, manifest (any failure: everything put back, exit 1), then done (exit 0)."""
    root = Path(root).resolve()
    out = Narrator(root, say)
    res: dict = {"format": FORMAT_RESULT, "nonce": None, "state": "refused", "from": None, "to": None,
                 "stage": "checks", "text": None, "counts": None, "backup": None, "restored": None,
                 "at": int(now())}
    release = None
    try:
        p = _read_pending(root, Path(pending), now())
        res.update({"nonce": p["nonce"], "from": p["from"], "to": p["to"]})
        out.info("update helper %s (from the verified download), for DataPiler %s" % (p["to"], p["from"]))
        release = hold_mutex(root, mutex)
        if release is None:
            raise Refused("checks", "DataPiler is still running (its mutex is held) - nothing was changed")
        out.ok("pending.json is fresh and names this folder; DataPiler has stopped")
        # verify
        zip_path = root / p["zip"]
        zip_name = "DataPiler-%s.zip" % p["to"]
        try:
            size = os.path.getsize(zip_path)
            got = sha256_file(zip_path) if size == p["zip_size"] else None
        except OSError:
            raise Refused("verify", "%s is not in update\\%s\\" % (zip_name, p["to"])) from None
        if got != p["zip_sha256"]:
            raise Refused("verify", "%s is not the download the page checked" % zip_name)
        try:
            arch = check_archive(zip_path, version=p["to"])
        except Refused as e:
            raise Refused("verify", e.text) from None
        out.ok("%s verified again (%s...%s): %s files, each against its manifest" % (
            zip_name, got[:4], got[-4:], n(arch.files)))
        # plan
        try:
            old = parse_manifest(_read_limited(root / MANIFEST, MANIFEST_MAX))
        except FileNotFoundError:
            raise Refused("plan", "this copy has no manifest.sha256, so it was not unpacked from a release - unpack "
                                  "the release by hand") from None
        except (OSError, ValueError):
            raise Refused("plan", "this copy's manifest.sha256 could not be read as a release writes it") from None
        if (root / MANIFEST).is_symlink() or not _inside(root, root / MANIFEST):
            raise Refused("plan", "manifest.sha256 leads outside DataPiler's folder")
        pl = plan(root, arch.manifest, old)
        guard = never_touched(root)
        if "" in guard:
            raise Refused("plan", "settings.json puts the workspace or the share folder at DataPiler's own folder - "
                                  "the update would touch it")
        for rel in pl.write + pl.add + pl.remove:
            if not safe_rel(rel):
                raise Refused("plan", "the plan names a path DataPiler does not write")
            real = _real_rel(root, rel)
            if _in(rel, guard) or (real is not None and _in(real, guard)):
                raise Refused("plan", "the release would change %s, which an update never touches - nothing was "
                                      "changed" % rel)
            target = root / rel
            if real is None or not _inside(root, target):
                raise Refused("plan", "%s leads outside DataPiler's folder" % rel)
            if os.path.lexists(target) and (target.is_symlink() or not target.is_file()):
                raise Refused("plan", "%s is not a plain file here (a folder or a link) - nothing was changed" % rel)
        out.ok("plan: write %s, add %s, remove %s (into the backup), %s already current" % (
            n(len(pl.write)), n(len(pl.add)), n(len(pl.remove)), n(len(pl.same))))
        for rel in pl.edited:
            out.warn("%s was edited here since the last release - the edited copy goes into the backup" % rel)
    except Refused as e:
        res.update({"state": "refused", "stage": e.stage, "text": e.text})
        out.bad("refused at %s: %s" % (e.stage, e.text))
        out.bad("nothing was changed")
        _result(root, res)
        if release is not None:
            release()
        return 2
    except Exception as e:
        res.update({"state": "refused", "stage": "checks", "text": "the checks failed: %s" % why(e)})
        out.bad("refused: the checks failed: %s - nothing was changed" % why(e))
        _result(root, res)
        if release is not None:
            release()
        return 2

    bdir = root / "update" / ("backup-%s" % p["from"])
    backup_rel = "update/backup-%s" % p["from"]
    res["backup"] = backup_rel
    j = Journal(folder=bdir, from_version=p["from"], to_version=p["to"], nonce=p["nonce"])
    allow_interrupts = hold_off_interrupts()
    try:
        return _swap(root, p, pl, arch, j, bdir, out, res, release, replace)
    finally:
        allow_interrupts()


def _swap(root: Path, p: dict, pl: Plan, arch: Archive, j: Journal, bdir: Path, out: Narrator, res: dict,
          release: Callable[[], None], replace: Callable) -> int:
    """install()'s backup, write, remove and manifest stages, with Ctrl+C held off: any failure, an interrupt
    included, puts everything back (exit 1); then done (exit 0)."""
    stage = "backup"
    try:
        # backup
        prev = bdir.with_name(bdir.name + ".prev")
        if os.path.lexists(bdir):
            if os.path.lexists(prev):
                shutil.rmtree(prev)
            os.replace(bdir, prev)
        (bdir / "files").mkdir(parents=True)
        j.save()        # from here on, an unfinished swap can be put back from this journal (rollback)
        for rel in pl.write + pl.remove:
            j.files.append({"path": rel, "sha256": _copy(root / rel, bdir / "files" / rel)})
        _copy(root / MANIFEST, bdir / MANIFEST)
        j.manifest = True
        j.save()
        out.ok("backed up %s file(s) to update\\backup-%s\\" % (n(len(j.files)), p["from"]))
        # write
        stage = "write"
        with zipfile.ZipFile(root / p["zip"]) as zf:
            for rel in sorted(pl.write + pl.add):
                parts = rel.split("/")[:-1]
                for i in range(1, len(parts) + 1):
                    d = "/".join(parts[:i])
                    if not os.path.lexists(root / d):
                        if not _inside(root, root / d):
                            raise Failed("write", "%s leads outside DataPiler's folder" % d)
                        os.mkdir(root / d)
                        j.dirs.append(d)
                        j.save()
                if rel in pl.add:
                    j.added.append(rel)
                    j.save()
                with zf.open("%s/%s" % (TOP, rel)) as src:
                    _put(src, root, rel, arch.manifest[rel], replace, j, "write")
        out.ok("wrote %s, added %s - each checked after writing" % (n(len(pl.write)), n(len(pl.add))))
        # remove
        stage = "remove"
        for rel in pl.remove:
            _remove(root / rel)
        out.ok("removed %s (in the backup), %s already current" % (n(len(pl.remove)), n(len(pl.same))))
        # manifest
        stage = "manifest"
        with zipfile.ZipFile(root / p["zip"]) as zf:
            raw = zf.read("%s/%s" % (TOP, MANIFEST))
        _put(io.BytesIO(raw), root, MANIFEST, hashlib.sha256(raw).hexdigest(), replace, j, "manifest")
        out.ok("manifest.sha256 written: %s files" % n(arch.files))
    except BaseException as e:      # an interrupt or an exit too: the files are put back first
        text = e.text if isinstance(e, Failed) else "%s failed: %s" % (stage, why(e))
        out.bad("the update stopped at %s: %s" % (stage, text))
        out.info("putting every file back")
        for rel in pl.write + pl.add + [MANIFEST]:
            _quiet_remove((root / rel).with_name(Path(rel).name + ".dpnew"))
        restored = _put_back(root, j, replace, out, always=False)
        try:
            j.save()
        except OSError:
            pass
        if restored:
            out.ok("every file was put back - DataPiler %s stays" % p["from"])
        else:
            out.bad("some files could not be put back - their copies are in update\\backup-%s\\" % p["from"])
        res.update({"state": "failed", "stage": stage, "text": text, "restored": restored,
                    "counts": None})
        _result(root, res)
        release()
        return 1

    # done
    j.complete = True
    try:
        j.save()
    except OSError as e:
        out.warn("backup.json could not be marked complete: %s" % why(e))
    for other in sorted((root / "update").glob("backup-*")):
        if other == bdir or not other.is_dir() or other.is_symlink():
            continue
        try:
            shutil.rmtree(other)
        except OSError as e:
            out.warn("an older backup could not be removed: %s" % why(e))
    kept = [k for k in ("workspace", "share", "logs", "jobs", "settings.json", ".venv") if (root / k).exists()]
    out.ok("kept: %s" % ", ".join(kept or ["(none here yet)"]))
    if LOCK in pl.write or LOCK in pl.add:
        out.warn("requirements.lock changed - the Python environment is made again next")
    res.update({"state": "updated", "stage": "done", "text": None, "restored": None,
                "counts": {"written": len(pl.write), "added": len(pl.add), "removed": len(pl.remove),
                           "same": len(pl.same), "files": arch.files}})
    _result(root, res)
    out.ok("updated to %s" % p["to"])
    release()
    return 0


# ---------------------------------------------------------------------------------------------------------- rollback


def _pending_nonce(root: Path) -> str | None:
    """update/pending.json's nonce, whatever its age, when it is DataPiler's and names this folder; else None."""
    try:
        doc = json.loads(_read_limited(Path(root) / "update" / "pending.json", SMALL_MAX).decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT_PENDING or doc.get("root") != root_id(root):
        return None
    nonce = doc.get("nonce")
    return nonce if isinstance(nonce, str) and NONCE_RX.fullmatch(nonce) else None


def rollback(root: Path, backup: Path, *, mutex: str = MUTEX, replace: Callable = os.replace,
             say: Callable[[str], None] = print) -> int:
    """The owner's R, and the window's putting back of a swap that was cut off (its window closed, the power cut):
    every backed-up file put back, every added file removed, the old manifest put back. A completed update's
    backup is written back whole; an unfinished one only while update/pending.json names the same update, and
    only the files that differ from their backup. result.json rolled_back with the update's nonce; exit 0,
    else 1."""
    root = Path(root).resolve()
    out = Narrator(root, say)
    backup = Path(backup)
    res: dict = {"format": FORMAT_RESULT, "nonce": None, "state": "failed", "from": None, "to": None,
                 "stage": "rollback", "text": None, "counts": None, "backup": None, "restored": False,
                 "at": int(time.time())}
    m = re.fullmatch(r"backup-(\d{1,4}\.\d{1,4}\.\d{1,4})", backup.name)
    expected = root / "update" / backup.name
    if not m or _norm(os.path.realpath(backup)) != _norm(os.path.realpath(expected)) or not _inside(root, backup):
        out.bad("the backup to roll back to is not an update\\backup-<version> folder of this DataPiler")
        return 1
    release = hold_mutex(root, mutex)
    if release is None:
        out.bad("DataPiler is still running (its mutex is held) - nothing was changed")
        return 1
    allow_interrupts = hold_off_interrupts()
    try:
        try:
            j = read_journal(expected)
        except (OSError, ValueError):
            out.bad("update\\%s\\backup.json could not be read - nothing was changed" % backup.name)
            return 1
        res.update({"nonce": j.nonce, "from": j.to_version, "to": j.from_version,
                    "backup": "update/%s" % backup.name})
        if not j.complete and _pending_nonce(root) != j.nonce:
            out.bad("that backup is of an update that did not finish, and update\\pending.json does not name it - "
                    "nothing was changed")
            res["text"] = "the backup is of an unfinished update that update\\pending.json does not name"
            _result(root, res)
            return 1
        if j.complete:
            out.info("going back to %s from update\\%s\\" % (j.from_version, backup.name))
        else:
            out.info("the update to %s did not finish - putting %s's files back from update\\%s\\" % (
                j.to_version, j.from_version, backup.name))
            for rel in [rec["path"] for rec in j.files] + j.added + [MANIFEST]:
                target = root / rel
                left = target.with_name(target.name + ".dpnew")
                if os.path.lexists(left) and _inside(root, left):
                    _quiet_remove(left)
        counts: dict = {}
        ok = _put_back(root, j, replace, out, always=j.complete, counts=counts)
        if not ok:
            res["text"] = "some files could not be put back - their copies are in update\\%s\\" % backup.name
            _result(root, res)
            out.bad(res["text"])
            return 1
        res.update({"state": "rolled_back", "restored": True,
                    "text": None if j.complete else "the update to %s was cut off part way, and its files were put "
                                                    "back" % j.to_version,
                    "counts": {"written": counts["written"], "added": 0, "removed": counts["removed"], "same": 0,
                               "files": len(j.files)}})
        _result(root, res)
        out.ok("back on %s: %s file(s) put back, %s removed" % (j.from_version, n(counts["written"]),
                                                                  n(counts["removed"])))
        return 0
    finally:
        allow_interrupts()
        release()


# ---------------------------------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="update-helper.py", description="DataPiler's update helper.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pending", help="update\\pending.json: swap in the verified download")
    g.add_argument("--rollback", help="update\\backup-<version>: go back to that version")
    g.add_argument("--check-zip", help="a release zip to check, read only")
    ap.add_argument("--version", help="with --check-zip: the release's version, X.Y.Z")
    a = ap.parse_args(argv)
    if a.check_zip:
        if not a.version:
            ap.error("--check-zip needs --version")
        try:
            arch = check_archive(Path(a.check_zip), version=a.version)
        except Refused as e:
            print("x %s: %s" % (e.stage, e.text))
            return 2
        print("ok one folder, %s, %s files, %s bytes unpacked; every sha256 matches its manifest; version %s" % (
            TOP, n(arch.files), n(arch.unpacked), arch.version))
        return 0
    if a.version:
        ap.error("--version goes with --check-zip only")
    root = Path(__file__).resolve().parents[2]
    if a.pending:
        return install(root, Path(a.pending))
    return rollback(root, Path(a.rollback))


if __name__ == "__main__":
    sys.exit(main())
