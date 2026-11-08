"""Steam's own files, read only, for Detect (build plan 0.2 §5.2; design 0002 §3.4).

Valve's KeyValues text (`libraryfolders.vdf`, `appmanifest_<id>.acf`) is read by a small, strict parser: quoted
strings, braces and // comments, nothing else, and no eval. Nothing of Steam is ever written, locked or renamed.

GAME_APP_ID is a lead (build plan 0.2 §10, P2): every candidate it gives is still proved by eldenring.exe in it. The
expansion's app id is never built in: an app manifest's `dlcappid` values are read and shown as they are (DP13)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import fileio, logbook
from .logbook import own

GAME_APP_ID = 1245620            # a lead (§10 P2): every candidate is still proved by eldenring.exe
VDF_MAX = 1024 * 1024
VDF_DEPTH = 16
VDF_KEYS = 10_000
INSTALLDIR_MAX = 255

_log = logbook.get("folders")
_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}


class VdfError(ValueError):
    """Not Valve's KeyValues as this parser reads it. `why` is DataPiler's own words, never the file's text."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = own(why)


@dataclass(frozen=True)
class Library:
    path: str
    apps: frozenset[int] | None      # None: an old file without apps


@dataclass(frozen=True)
class AppManifest:
    installdir: str                  # one folder name; "" when missing or refused
    dlc_app_ids: tuple[int, ...]     # InstalledDepots' dlcappid values, sorted


# ---------------------------------------------------------------------------------------------------------- parser


def _tokens(text: str):
    """("s", value) for a quoted string, ("{", None), ("}", None). Raises VdfError."""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n\ufeff":
            i += 1
            continue
        if ch == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch in "{}":
            yield ch, None
            i += 1
            continue
        if ch != '"':
            raise VdfError("an unquoted token")
        i += 1
        out: list[str] = []
        while True:
            if i >= n:
                raise VdfError("an unclosed string")
            ch = text[i]
            if ch == '"':
                i += 1
                break
            if ch == "\\":
                if i + 1 >= n or text[i + 1] not in _ESCAPES:
                    raise VdfError("an escape this parser does not read")
                out.append(_ESCAPES[text[i + 1]])
                i += 2
                continue
            out.append(ch)
            i += 1
        yield "s", "".join(out)


def parse_vdf(text: str) -> dict:
    """Valve's KeyValues: quoted strings (escapes \\\\ \\" \\n \\t), braces, // comments; anything else is a VdfError.
    Keys keep their case; lookups with key() are case-insensitive. A repeated key keeps its last value. No eval."""
    if not isinstance(text, str):
        raise VdfError("not text")
    if len(text) > VDF_MAX:
        raise VdfError("over the size limit")
    root: dict = {}
    stack: list[dict] = [root]
    count = 0
    pending: str | None = None
    for kind, value in _tokens(text):
        if kind == "s":
            if pending is None:
                pending = value
                continue
            stack[-1][pending] = value
            pending = None
            count += 1
        elif kind == "{":
            if pending is None:
                raise VdfError("a block without a key")
            if len(stack) > VDF_DEPTH:
                raise VdfError("nested too deep")
            block: dict = {}
            stack[-1][pending] = block
            stack.append(block)
            pending = None
            count += 1
        else:
            if pending is not None:
                raise VdfError("a key without a value")
            if len(stack) == 1:
                raise VdfError("a closing brace without its block")
            stack.pop()
        if count > VDF_KEYS:
            raise VdfError("too many keys")
    if pending is not None:
        raise VdfError("a key without a value")
    if len(stack) != 1:
        raise VdfError("an unclosed brace")
    return root


def key(d: object, name: str) -> object | None:
    """d[name], or the first key equal to name case-insensitively; None when d is not a block or has neither."""
    if not isinstance(d, dict):
        return None
    if name in d:
        return d[name]
    folded = name.casefold()
    for k, v in d.items():
        if isinstance(k, str) and k.casefold() == folded:
            return v
    return None


def read_vdf(path: Path, kind: str) -> dict | None:
    """One file parsed; None when it is not there. A file that is there but cannot be read is logged by its kind and
    why (source folders), and None."""
    try:
        data = fileio.read_limited(Path(path), VDF_MAX)
    except FileNotFoundError:
        return None
    except (OSError, fileio.TooLarge) as e:
        _log.warn("Steam's %s could not be read: %s", own(kind), logbook.why(e))
        raise VdfError("could not be read") from None
    try:
        return parse_vdf(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        _log.warn("Steam's %s could not be read: %s", own(kind), own("not UTF-8"))
        raise VdfError("not UTF-8") from None
    except VdfError as e:
        _log.warn("Steam's %s could not be read: %s", own(kind), e.why)
        raise


# ---------------------------------------------------------------------------------------------------------- files


def _norm(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").casefold()


def _app_ids(block: object) -> frozenset[int]:
    if not isinstance(block, dict):
        return frozenset()
    return frozenset(int(k) for k in block if isinstance(k, str) and k.isdigit() and len(k) <= 10)


def _entries(doc: dict) -> list[Library]:
    root = key(doc, "libraryfolders")
    if not isinstance(root, dict):
        raise VdfError("no libraryfolders block")
    out: list[Library] = []
    for k, v in root.items():
        if not (isinstance(k, str) and k.isdigit()):
            continue                            # TimeNextStatsReport, ContentStatsID and the like
        if isinstance(v, str):                  # the old flat format: "1" "D:\\SteamLibrary"
            if v.strip():
                out.append(Library(v.strip(), None))
        elif isinstance(v, dict):               # the new blocks: path and apps
            p = key(v, "path")
            if isinstance(p, str) and p.strip():
                apps = key(v, "apps")
                out.append(Library(p.strip(), _app_ids(apps) if isinstance(apps, dict) else None))
    return out


def libraries(steam_dir: str) -> list[Library]:
    """<steam>/steamapps/libraryfolders.vdf and <steam>/config/libraryfolders.vdf, both formats (the old flat "1"
    "<path>" entries; the new blocks with path and apps), and the Steam folder itself; merged, case-folded. Raises
    VdfError when a file is there but cannot be read and no other file could be."""
    if not steam_dir:
        return []
    found: list[Library] = [Library(steam_dir, None)]
    failed = 0
    read = 0
    for rel in (("steamapps", "libraryfolders.vdf"), ("config", "libraryfolders.vdf")):
        try:
            doc = read_vdf(Path(steam_dir).joinpath(*rel), "library list")
        except VdfError:
            failed += 1
            continue
        if doc is None:
            continue
        try:
            found.extend(_entries(doc))
            read += 1
        except VdfError as e:
            _log.warn("Steam's %s could not be read: %s", own("library list"), e.why)
            failed += 1
    if failed and not read:
        raise VdfError("the library list could not be read")
    merged: dict[str, Library] = {}
    for lib in found:
        k = _norm(lib.path)
        if not k:
            continue
        old = merged.get(k)
        if old is None:
            merged[k] = lib
        elif lib.apps is not None:
            merged[k] = Library(old.path, (old.apps or frozenset()) | lib.apps)
    return list(merged.values())


def installdir_ok(name: object) -> bool:
    """One folder name: no separator, drive, '.', '..', control character, or trailing dot or space."""
    if not isinstance(name, str) or not name or len(name) > INSTALLDIR_MAX:
        return False
    if name in (".", "..") or name != name.strip() or name.endswith("."):
        return False
    return not any(ch in '\\/:*?"<>|' or ord(ch) < 32 for ch in name)


def app_manifest(library: str, app_id: int) -> AppManifest | None:
    """<library>/steamapps/appmanifest_<id>.acf: installdir (one folder name, nothing else) and InstalledDepots'
    dlcappid values. None when the file is missing, unreadable or for another app."""
    if not library or not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        return None
    try:
        doc = read_vdf(Path(library) / "steamapps" / ("appmanifest_%d.acf" % app_id), "app manifest")
    except VdfError:
        return None
    if doc is None:
        return None
    state = key(doc, "AppState")
    if not isinstance(state, dict):
        _log.warn("Steam's %s could not be read: %s", own("app manifest"), own("no AppState block"))
        return None
    stated = key(state, "appid")
    if isinstance(stated, str) and stated.strip() and stated.strip() != str(app_id):
        return None
    inst = key(state, "installdir")
    installdir = inst if installdir_ok(inst) else ""
    if isinstance(inst, str) and inst and not installdir:
        _log.warn("Steam's %s names an install folder DataPiler does not use: %s", own("app manifest"),
                  own("not one folder name"))
    dlc: set[int] = set()
    depots = key(state, "InstalledDepots")
    if isinstance(depots, dict):
        for depot in depots.values():
            v = key(depot, "dlcappid")
            if isinstance(v, str) and v.strip().isdigit() and len(v.strip()) <= 10:
                dlc.add(int(v.strip()))
    return AppManifest(installdir, tuple(sorted(dlc)))


def game_folder(library: str, installdir: str) -> str:
    """<library>/steamapps/common/<installdir>/Game, normalised (Windows: backslashes)."""
    return os.path.normpath(os.path.join(library, "steamapps", "common", installdir, "Game"))
