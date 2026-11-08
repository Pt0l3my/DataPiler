"""settings.json, its keys and checks, and the session's switches (build plan §4.1).

The server's address is not a setting: 127.0.0.1:22720 is a constant in link.py, shown on the page. The session's
switches (the server link, DEBUG to the file) are never saved: both are off at every start.

`expansion` is the owner's own statement of whether the game's expansion is installed (build plan §10, P2; settled
S21): blank until the owner sets it, and a share write waits for it. No file check decides it; one may only show a
hint on Status."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Mapping

from . import fileio, paths, winapi
from .logbook import Own, own

FORMAT = "datapiler-settings/1"
ROOT = Path(__file__).resolve().parent.parent
NEXT_START = ("port", "log_max_mb", "log_keep", "workspace_dir")   # the text database stays open where it is
FOLDER_MAX = 1024
LANGUAGE_RX = re.compile(r"[a-z]{2,8}")
EXPANSION = ("", "yes", "no")          # not stated yet, installed, not installed
_CONTROL_RX = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Settings:
    smithbox_dir: str = ""
    game_dir: str = ""
    project_dir: str = ""
    workspace_dir: str = "workspace"
    share_dir: str = "share"
    language: str = "engus"
    expansion: str = ""
    port: int = 0
    log_max_mb: int = 2
    log_keep: int = 5

    def as_dict(self) -> dict:
        return asdict(self)


KEYS = tuple(f.name for f in fields(Settings))


class SettingsError(ValueError):
    """A setting refused: field is the key, rule DataPiler's words. str(e) is the rule."""

    def __init__(self, field: str, rule: str):
        super().__init__(rule)
        self.field = field
        self.rule = rule


@dataclass
class Session:          # never saved: off at every start
    link: bool = False
    debug: bool = False
    project_confirmed: bool = False     # the owner said the project open in Smithbox is the one in Settings


def _absolute(s: str) -> bool:
    return os.path.isabs(s)


WORKSPACE_LOCAL = "the workspace must be on this PC, never a network folder: it holds the game's text"


def _network(s: str) -> bool:
    """A UNC path (\\\\server\\share, //server/share, \\\\?\\UNC\\...): a folder on another machine."""
    t = s.strip()
    return t.startswith("\\\\") or t.startswith("//") or t[:2] in ("\\/", "/\\")


def _text(raw: Mapping[str, object], key: str, default: str) -> str:
    v = raw.get(key, default)
    if not isinstance(v, str):
        raise SettingsError(key, "%s must be text" % _LABEL[key])
    v = v.strip()
    if len(v) > FOLDER_MAX or _CONTROL_RX.search(v):
        raise SettingsError(key, "%s is not a folder DataPiler can use" % _LABEL[key])
    return v


def _int(raw: Mapping[str, object], key: str, default: int, lo: int, hi: int, zero: bool = False) -> int:
    v = raw.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int):
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        else:
            raise SettingsError(key, "%s must be a whole number" % _LABEL[key])
    if not (lo <= v <= hi or (zero and v == 0)):
        if zero:
            raise SettingsError(key, "%s must be blank (any free one) or %d to %d" % (_LABEL[key], lo, hi))
        raise SettingsError(key, "%s must be %d to %d" % (_LABEL[key], lo, hi))
    return v


_LABEL = {
    "smithbox_dir": "the Smithbox folder", "game_dir": "the game folder", "project_dir": "the project folder",
    "workspace_dir": "the workspace", "share_dir": "the share folder", "language": "the text language",
    "port": "the page's port", "log_max_mb": "the log's size", "log_keep": "the number of log files kept",
    "expansion": "whether the expansion is installed",
}


def _full(root: Path, folder: str) -> Path:
    p = Path(os.path.expanduser(folder))
    return p if p.is_absolute() else root / p


def check(raw: Mapping[str, object], *, root: Path | None = None) -> Settings:
    """Every key known (an unknown key is refused), each of its type and range, the folder rules of §4.1.
    A missing key takes its default. Raises SettingsError."""
    if not isinstance(raw, Mapping):
        raise SettingsError("(file)", "the settings are not an object")
    root = Path(root) if root is not None else ROOT
    for key in raw:
        if key == "format":
            if raw[key] != FORMAT:
                raise SettingsError("format", "the settings are not of the format " + FORMAT)
            continue
        if key not in KEYS:
            raise SettingsError(str(key) if re.fullmatch(r"[a-z_]{1,32}", str(key)) else "(key)",
                                "not a setting DataPiler knows")
    d = Settings()
    vals: dict[str, object] = {}
    for key in ("smithbox_dir", "game_dir", "project_dir"):
        v = _text(raw, key, getattr(d, key))
        if v and not _absolute(v):
            raise SettingsError(key, "%s must be a full folder path, or blank" % _LABEL[key])
        vals[key] = v
    for key in ("workspace_dir", "share_dir"):
        v = _text(raw, key, getattr(d, key))
        if not v:
            raise SettingsError(key, "%s must be a folder: relative to DataPiler's folder, or a full path"
                                % _LABEL[key])
        vals[key] = v
    # The workspace holds the game's text and stays on this PC (design §1): never a network share.
    if _network(vals["workspace_dir"]):
        raise SettingsError("workspace_dir", WORKSPACE_LOCAL)
    lang = raw.get("language", d.language)
    if not isinstance(lang, str) or not LANGUAGE_RX.fullmatch(lang):
        raise SettingsError("language", "the text language must be Smithbox's code: 2 to 8 small letters, "
                                        "e.g. engus")
    vals["language"] = lang
    exp = raw.get("expansion", d.expansion)
    if not isinstance(exp, str) or exp not in EXPANSION:
        raise SettingsError("expansion", "whether the expansion is installed must be yes, no, or not stated yet")
    vals["expansion"] = exp
    vals["port"] = _int(raw, "port", d.port, 1024, 65535, zero=True)
    vals["log_max_mb"] = _int(raw, "log_max_mb", d.log_max_mb, 1, 50)
    vals["log_keep"] = _int(raw, "log_keep", d.log_keep, 2, 20)     # every file, datapiler.log among them
    s = Settings(**vals)  # type: ignore[arg-type]

    game, smithbox, project = s.game_dir, s.smithbox_dir, s.project_dir
    if project and game:
        if paths.is_inside(project, game):
            raise SettingsError("project_dir", "the project folder must be outside the game's folder")
    workspace = _full(root, s.workspace_dir)
    share = _full(root, s.share_dir)
    # A full path on a mapped network drive. A relative workspace sits in DataPiler's own folder, wherever the owner
    # put that: refusing it here would refuse the default too, so the start warns instead (datapiler.py).
    if Path(os.path.expanduser(s.workspace_dir)).is_absolute():
        try:
            remote = winapi.backend().drive_is_remote(str(workspace))
        except Exception:
            remote = False
        if remote:
            raise SettingsError("workspace_dir", WORKSPACE_LOCAL)
    for key, folder in (("workspace_dir", workspace), ("share_dir", share)):
        for other, label in ((game, "the game's"), (smithbox, "Smithbox's"), (project, "the project's")):
            if other and paths.is_inside(folder, other):
                raise SettingsError(key, "%s must be outside %s folder" % (_LABEL[key], label))
    if paths.is_inside(share, workspace):
        raise SettingsError("share_dir", "the share folder must be outside the workspace")
    if paths.is_inside(workspace, share):
        raise SettingsError("workspace_dir", "the workspace must be outside the share folder")
    return s


def load(path: Path, *, root: Path | None = None) -> tuple[Settings, list[Own]]:
    """settings.json, or the defaults; the list says what was wrong (a missing file: nothing). A key that fails
    its check takes its default and is named in the list."""
    try:
        data = fileio.read_limited(Path(path), 256 * 1024)
    except FileNotFoundError:
        return Settings(), []
    except (OSError, fileio.TooLarge):
        return Settings(), [own("settings.json could not be read - the defaults are used")]
    try:
        raw = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return Settings(), [own("settings.json is not valid JSON - the defaults are used")]
    if not isinstance(raw, dict):
        return Settings(), [own("settings.json is not an object - the defaults are used")]
    problems: list[Own] = []
    raw = dict(raw)
    for _ in range(len(KEYS) + len(raw) + 2):
        try:
            return check(raw, root=root), problems
        except SettingsError as e:
            if e.field in raw:
                raw.pop(e.field)
                problems.append(own("settings.json: %s - its default is used (%s)" % (e.field, e.rule))
                                if e.field in KEYS else own("settings.json: a key DataPiler does not know is "
                                                            "left out"))
            else:
                bad = [k for k in raw if k not in KEYS and k != "format"]
                if not bad:
                    break
                for k in bad:
                    raw.pop(k)
                problems.append(own("settings.json: a key DataPiler does not know is left out"))
    return Settings(), problems + [own("settings.json could not be used - the defaults are used")]


def save(path: Path, s: Settings) -> None:
    """Atomic. Raises OSError."""
    doc = {"format": FORMAT}
    doc.update(s.as_dict())
    fileio.write_atomic(Path(path), (json.dumps(doc, indent=1) + "\n").encode("utf-8"))


def changed(old: Settings, new: Settings) -> list[str]:
    """The keys whose values differ."""
    return [k for k in KEYS if getattr(old, k) != getattr(new, k)]


def with_values(s: Settings, **kw: object) -> Settings:
    return replace(s, **kw)  # type: ignore[arg-type]
