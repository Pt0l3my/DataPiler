"""EldenNet's devkit tool, run for the derivation's offline round R0 (DP36; EldenNet O89, O73 to O75; settled S98).

DataPiler never bundles the tool. The owner unpacks EldenNet's devkit package into a folder of their own and names it
in Settings (`devkit_dir`). The folder holds `eldennet-engine.exe`, `gal/leads.toml` (what the derivation looks for:
names and shapes, never bytes) and `SHA256SUMS`, and both files must match their lines in SHA256SUMS before anything
runs (`locate`). A job's `probe_exe` step then runs, with the game closed:

    eldennet-engine.exe probe-exe <game folder>\\eldenring.exe --derive --leads <devkit>\\gal\\leads.toml --out derive.json
    eldennet-engine.exe lint --report derive.json

each with its arguments as a list (no shell), no window, nothing on its standard input, an empty folder of the
workspace as its working folder (where derive.json is written), and a time limit (`run`). It stops at once when the
job is cancelled or the game starts. The tool reads the game's executable file and the leads file only, never the
game's memory, and writes derive.json only; DataPiler reads what it wrote, its exit code and its messages, and passes
derive.json to its own guard (`derive.py`) before it becomes the job's share file.

The tool's messages are one line each and show no path and nothing read from the executable (EldenNet's
`src/en-tools/README.md`); DataPiler still shows only lines of the tool's own shape (`shown`), each in the log's mask,
and says what each exit code means in its own words."""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import derive, fileio
from .logbook import Own, own

TOOL = "eldennet-engine.exe"
LEADS = ("gal", "leads.toml")
SUMS = "SHA256SUMS"
WORK_DIR = "devkit-run"            # workspace/devkit-run/: the tool's working folder, emptied before and after a run
OUT = "derive.json"
LEADS_MAX = 64 * 1024              # the tool's own limit for a leads file
SUMS_MAX = 64 * 1024
TOOL_MAX = 256 * 1024 * 1024
STREAM_MAX = 64 * 1024             # what DataPiler keeps of the tool's standard output and error
SHOWN_MAX = 24                     # the tool's lines shown in the job's log, at most
PROBE_TIMEOUT = 900.0              # seconds; the tool takes about a minute on the game's executable
LINT_TIMEOUT = 120.0
POLL = 0.25
GAME_POLL = 2.0
CREATE_NO_WINDOW = 0x08000000

HEX64_RX = re.compile(r"[0-9a-fA-F]{64}")
_SUM_RX = re.compile(r"([0-9a-fA-F]{64}) [ *]([^\r\n]+)")
_SHOWN_RX = re.compile(r"(?:probe-exe|lint): [ -~]{1,240}")

# probe-exe's exit codes (EldenNet's src/en-tools/README.md), in DataPiler's words: 0 and 1 write derive.json.
PROBE_WORDS = {
    2: "the devkit tool refused DataPiler's command line (exit code 2): this DataPiler and that devkit do not fit "
       "together - take the devkit package that goes with this version",
    3: "the devkit tool could not read the game's executable, or it is not a 64-bit Windows program (exit code 3): "
       "check the game folder in Settings, and that eldenring.exe is whole (Steam's Verify integrity of game files)",
    4: "the devkit tool refused its leads file, gal\\leads.toml (exit code 4): unpack the devkit package again; the "
       "tool's own words are in the job's log",
    5: "the devkit tool's own check refused the report it made (exit code 5): a fault of EldenNet's, nothing of yours "
       "- send the job's log with your report",
    6: "the devkit tool could not write its report into the workspace (exit code 6): check that the workspace has "
       "room and can be written",
}
LINT_WORDS = {
    1: "the devkit's lint refused the report (exit code 1), so nothing is shared: a fault of EldenNet's - send the "
       "job's log, which names each problem's place",
    2: "the devkit's lint could not read the report (exit code 2)",
}


class DevkitError(Exception):
    """Why the devkit cannot be used, in DataPiler's words (an Own string: no path)."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = own(why)


class Stopped(Exception):
    """A run stopped before the tool ended: "cancelled", "game" (the game started) or "timeout"."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Kit:
    """The devkit, located and checked: the tool and the leads file, their sha256s, and the leads' labels."""
    folder: Path
    tool: Path
    leads: Path
    tool_sha256: str
    leads_sha256: str
    labels: frozenset[str]


@dataclass(frozen=True)
class Result:
    code: int
    out: list[str]          # standard output's lines
    err: list[str]          # standard error's lines


def sums(data: bytes) -> dict[str, str]:
    """SHA256SUMS as sha256sum writes it: `<sha256>  <name>` (or ` *<name>`) a line; names with / and case kept,
    sha256s lower-case. Lines of another shape are left out."""
    out: dict[str, str] = {}
    for line in data.decode("utf-8", "replace").splitlines():
        m = _SUM_RX.fullmatch(line.strip("﻿"))
        if m is not None:
            out[m.group(2).strip().replace("\\", "/")] = m.group(1).lower()
    return out


def locate(devkit_dir: str) -> Kit:
    """The devkit in the folder Settings names, checked: the folder set and on this PC, the tool and the leads file
    there and whole by SHA256SUMS, the leads file at most 64 KiB, with at least one label. Raises DevkitError."""
    d = (devkit_dir or "").strip()
    if not d:
        raise DevkitError("the EldenNet devkit folder is not set: in Settings, set it to the folder where you unpacked "
                          "EldenNet's devkit package")
    folder = Path(d)
    if not folder.is_absolute():
        raise DevkitError("the EldenNet devkit folder in Settings must be a full folder path")
    if not folder.is_dir():
        raise DevkitError("the EldenNet devkit folder in Settings is not a folder on this PC")
    tool = folder / TOOL
    leads = folder.joinpath(*LEADS)
    listed = folder / SUMS
    for f, name in ((tool, TOOL), (leads, "gal\\leads.toml"), (listed, SUMS)):
        if not f.is_file() or f.is_symlink():
            raise DevkitError("%s is not in the EldenNet devkit folder: unpack the whole devkit package there" % name)
    try:
        table = sums(fileio.read_limited(listed, SUMS_MAX))
        if tool.stat().st_size > TOOL_MAX:
            raise DevkitError("%s is larger than a devkit tool can be" % TOOL)
        tool_sha = fileio.sha256_file(tool)
        leads_bytes = fileio.read_limited(leads, LEADS_MAX)
    except fileio.TooLarge:
        raise DevkitError("a file of the EldenNet devkit is larger than DataPiler reads (the leads file holds at "
                          "most 64 KiB)") from None
    except OSError:
        raise DevkitError("the EldenNet devkit's files could not be read") from None
    leads_sha = fileio.sha256_bytes(leads_bytes)
    for name, sha, key in ((TOOL, tool_sha, TOOL), ("gal\\leads.toml", leads_sha, "/".join(LEADS))):
        want = table.get(key)
        if want is None:
            raise DevkitError("%s lists no %s: unpack the whole devkit package again" % (SUMS, name))
        if want != sha:
            raise DevkitError("%s does not match its line in %s: unpack the devkit package again" % (name, SUMS))
    try:
        labels = derive.leads_labels(leads_bytes.decode("utf-8"))
    except UnicodeDecodeError:
        raise DevkitError("gal\\leads.toml is not UTF-8 text") from None
    if not labels:
        raise DevkitError("gal\\leads.toml names no label")
    return Kit(folder, tool, leads, tool_sha, leads_sha, labels)


def run(argv: Sequence[str], *, cwd: Path, cancel: threading.Event, game_running: Callable[[], bool],
        timeout: float, poll: float | None = None, game_poll: float | None = None) -> Result:
    """Runs the tool: argv as a list (never a shell), cwd its working folder, nothing on its standard input, no
    window on Windows. Stops it (and raises Stopped) when cancel is set, when game_running() turns true (checked
    every game_poll seconds; a check that raises counts as running) or after timeout seconds. Raises OSError when it
    cannot start."""
    poll = POLL if poll is None else poll
    game_poll = GAME_POLL if game_poll is None else game_poll
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    proc = subprocess.Popen([str(a) for a in argv], cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=False, close_fds=True, **kw)
    out = bytearray()
    err = bytearray()

    def pump(stream, buf: bytearray) -> None:
        try:
            for chunk in iter(lambda: stream.read(4096), b""):
                if len(buf) < STREAM_MAX:
                    buf.extend(chunk[: STREAM_MAX - len(buf)])
        except (OSError, ValueError):
            pass

    readers = [threading.Thread(target=pump, args=(proc.stdout, out), daemon=True, name="datapiler-devkit-out"),
               threading.Thread(target=pump, args=(proc.stderr, err), daemon=True, name="datapiler-devkit-err")]
    for t in readers:
        t.start()
    t0 = time.monotonic()
    last_game = t0
    reason: str | None = None
    while True:
        try:
            code = proc.wait(poll)
            break
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        if cancel.is_set():
            reason = "cancelled"
        elif now - t0 > timeout:
            reason = "timeout"
        elif now - last_game >= game_poll:
            last_game = now
            try:
                running = bool(game_running())
            except Exception:
                running = True
            if running:
                reason = "game"
        if reason is not None:
            proc.kill()
            proc.wait()
            break
    for t in readers:
        t.join(5)
    for s in (proc.stdout, proc.stderr):
        try:
            s.close()
        except (OSError, ValueError, AttributeError):
            pass
    if reason is not None:
        raise Stopped(reason)
    return Result(code, _lines(out), _lines(err))


def _lines(buf: bytes) -> list[str]:
    return [x.rstrip("\r") for x in bytes(buf).decode("ascii", "replace").split("\n") if x.strip()]


def shown(lines: Sequence[str]) -> tuple[list[Own], int]:
    """The tool's lines DataPiler shows in the job's log: those of its own shape (`probe-exe: ...` or `lint: ...`,
    printable ASCII), with no path sign; at most SHOWN_MAX. (the lines, how many were left out)."""
    keep: list[Own] = []
    left = 0
    for x in lines:
        if _SHOWN_RX.fullmatch(x) and "\\" not in x and "/" not in x and len(keep) < SHOWN_MAX:
            keep.append(own(x))
        else:
            left += 1
    return keep, left


def probe_words(code: int) -> Own:
    """What probe-exe's exit code means, for a run that wrote no report."""
    if code in PROBE_WORDS:
        return own(PROBE_WORDS[code])
    return own("the devkit tool stopped unexpectedly (exit code %d) and wrote no report: send the job's log with "
               "your report" % code)


def lint_words(code: int) -> Own:
    if code in LINT_WORDS:
        return own(LINT_WORDS[code])
    return own("the devkit's lint stopped unexpectedly (exit code %d)" % code)
