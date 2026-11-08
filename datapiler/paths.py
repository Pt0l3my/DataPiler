"""The run-time folders and file names (build plan §2, §3.4).

DataPiler writes only inside its own folder, and into the workspace and share folders when Settings moves them.
Every name it writes matches NAME_RX plus ".json" and is not a Windows device's name (RESERVED_RX); nothing is ever
written under a name a job or the page supplies without that check."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

NAME_RX = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# The names Windows keeps for devices, whatever follows the dot: "con.json" opens the console, "nul" nothing.
RESERVED_RX = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9]|conin\$|conout\$)", re.I)
RESERVED_TEXT = "is a name Windows keeps for a device"


def reserved(name: str) -> bool:
    return bool(RESERVED_RX.fullmatch(name))


def name_ok(name: object) -> bool:
    """A name DataPiler writes under: NAME_RX, and not a device's name."""
    return isinstance(name, str) and bool(NAME_RX.fullmatch(name)) and not reserved(name)


@dataclass(frozen=True)
class Paths:
    root: Path
    workspace: Path
    inbox: Path
    imported: Path
    local: Path
    textdb: Path
    share_counts: Path      # the row counts of the share files written (check 6's input, kept local; DP8)
    share: Path
    logs: Path
    job_logs: Path
    jobs: Path
    port_file: Path
    start_log: Path
    settings: Path
    lock: Path              # requirements.lock
    mutex_file: Path        # datapiler.lock, the portable stand-in for the mutex
    venv: Path              # .venv/
    venv_marker: Path       # .venv/datapiler-lock.sha256


def _under(root: Path, folder: str) -> Path:
    p = Path(os.path.expanduser(folder)) if folder.startswith("~") else Path(folder)
    return p if p.is_absolute() else root / p


def resolve(root: Path, workspace_dir: str, share_dir: str) -> Paths:
    """Relative workspace and share folders are taken under root."""
    root = Path(root)
    workspace = _under(root, workspace_dir)
    logs = root / "logs"
    venv = root / ".venv"
    return Paths(
        root=root,
        workspace=workspace,
        inbox=workspace / "inbox",
        imported=workspace / "imported",
        local=workspace / "local",
        textdb=workspace / "textdb.sqlite",
        share_counts=workspace / "share-counts.json",
        share=_under(root, share_dir),
        logs=logs,
        job_logs=logs / "jobs",
        jobs=root / "jobs",
        port_file=root / "datapiler.port",
        start_log=root / "datapiler-start.log",
        settings=root / "settings.json",
        lock=root / "requirements.lock",
        mutex_file=root / "datapiler.lock",
        venv=venv,
        venv_marker=venv / "datapiler-lock.sha256",
    )


def ensure(p: Paths) -> None:
    """Make every folder DataPiler writes into. Raises OSError."""
    for folder in (p.workspace, p.inbox, p.imported, p.local, p.share, p.logs, p.job_logs, p.jobs):
        folder.mkdir(parents=True, exist_ok=True)


def _parts(path: str | Path) -> tuple[str, ...]:
    resolved = Path(os.path.abspath(os.path.expanduser(str(path))))
    try:
        resolved = resolved.resolve(strict=False)
    except (OSError, RuntimeError):
        pass
    parts = resolved.parts
    if os.name == "nt":
        parts = tuple(os.path.normcase(x) for x in parts)
    return parts


def is_inside(child: str | Path, parent: str | Path) -> bool:
    """True when child is parent or lies inside it: resolved, compared by path parts, case-folded on Windows
    ("Game2" is not inside "Game")."""
    if not str(child) or not str(parent):
        return False
    c, p = _parts(child), _parts(parent)
    return len(c) >= len(p) and c[: len(p)] == p


def _name(name: str) -> str:
    if not name_ok(name):
        raise ValueError("not a name DataPiler writes")
    return name


def share_file(p: Paths, name: str) -> Path:
    """share/<name>.json. ValueError for a name not matching NAME_RX."""
    return p.share / (_name(name) + ".json")


def local_file(p: Paths, job_id: str, name: str) -> Path:
    """workspace/local/<job_id>/<name>.json. ValueError likewise."""
    return p.local / _name(job_id) / (_name(name) + ".json")
