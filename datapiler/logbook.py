"""The log: its format, levels, rotation, masking, the ring for the Terminal tab and the job logs (build plan §3.3).

One format everywhere (the window, the files, the Terminal tab):

    2026-11-08 08:42:01.123  INFO   extract  NpcParam: 2,105 rows read in 0.4 s

A message is built from a literal template with %-placeholders and safe arguments, nothing else: int, float, bool,
None and Own arguments appear as they are, any other str becomes "<text>" and any other object "<?>". The mask sits
in one logging.Filter on every handler and is applied to each line's message (design §5: mask at the formatter, not
at each call)."""

from __future__ import annotations

import collections
import logging
import logging.handlers
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

from . import NAME, VERSION, paths, winapi

SOURCES = ("app", "page", "smithbox", "link", "extract", "job", "guard", "textdb", "env")
LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
RING = 5000

_LEVELNO = {"DEBUG": logging.DEBUG, "INFO": logging.INFO, "WARN": logging.WARNING, "ERROR": logging.ERROR}
_LEVELNAME = {v: k for k, v in _LEVELNO.items()}
_SEPARATOR = "---- %s %s ----" % (NAME, VERSION)
_ANSI = {logging.WARNING: "\x1b[33m", logging.ERROR: "\x1b[31m"}
_RESET = "\x1b[0m"
_CONTROL_RX = re.compile(r"[\x00-\x1f\x7f]+")


class Own(str):
    """A string DataPiler wrote or checked: its own words, a name it made, an id that passed its pattern, a param
    name from fields.PARAMS, a method name from link.ALLOWED. Only Own strings reach a log line as they are."""

    __slots__ = ()


def own(s: str) -> Own:
    return Own(s)


def n(x: int | float) -> Own:
    """2105 -> "2,105"; 0.42 -> "0.4"."""
    if isinstance(x, bool):
        return Own("%d" % int(x))
    if isinstance(x, int):
        return Own("{:,}".format(int(x)))
    try:
        return Own("{:,.1f}".format(float(x)))
    except (TypeError, ValueError):
        return Own("<?>")


def why(e: BaseException) -> Own:
    """The exception's type name, with errno for an OSError ("PermissionError (errno 13)"). Never str(e)."""
    name = type(e).__name__
    if isinstance(e, OSError) and isinstance(e.errno, int):
        return Own("%s (errno %d)" % (name, e.errno))
    return Own(name)


# ---------------------------------------------------------------------------------------------------------- mask

_ABS_RX = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")
_SEP_RX = re.compile(r"[\\/]+")
_V4_RX = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)(?!\w)")
_V6_RX = re.compile(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}(?:(?:\d{1,3}\.){3}\d{1,3}|[0-9A-Fa-f]{1,4})?(?![\w:])")
_KEEP_IP = "127.0.0.1"


def _folder_rx(folder: str) -> str | None:
    """A folder as a pattern matching either slash; None for something that is not an absolute folder."""
    f = folder.strip()
    if not f or not _ABS_RX.match(f):
        return None
    pieces = _SEP_RX.split(f)
    while pieces and pieces[-1] == "":
        pieces.pop()
    if not any(pieces):
        return None
    return r"[\\/]+".join(re.escape(p) for p in pieces) if pieces[0] else r"[\\/]+" + r"[\\/]+".join(
        re.escape(p) for p in pieces[1:])


def _folder_variants(folder: str) -> list[str]:
    out = [folder]
    try:
        short = winapi.backend().short_path(folder)
    except Exception:
        short = None
    if short and short != folder:
        out.append(short)
    return out


def _ip_v6(m: re.Match) -> str:
    s = m.group(0)
    if "::" not in s and s.count(":") != 7:
        return s
    import ipaddress
    try:
        ipaddress.ip_address(s)
    except ValueError:
        return s
    return "<IP>"


def _ip_v4(m: re.Match) -> str:
    s = m.group(0)
    return s if s == _KEEP_IP else "<IP>"


class _Mask:
    def __init__(self, folders: re.Pattern | None, folder_map: dict[str, str], home: re.Pattern | None,
                 words: list[tuple[re.Pattern, str]]):
        self.folders = folders
        self.folder_map = folder_map
        self.home = home
        self.words = words

    def apply(self, text: str) -> str:
        if self.folders is not None:
            text = self.folders.sub(lambda m: self.folder_map[m.lastgroup or ""], text)
        if self.home is not None:
            text = self.home.sub("<HOME>", text)
        for rx, repl in self.words:
            text = rx.sub(repl, text)
        text = _V6_RX.sub(_ip_v6, text)
        return _V4_RX.sub(_ip_v4, text)


_mask = _Mask(None, {}, None, [])
_mask_inputs: dict = {"folders": {}, "home": None, "user": None, "pc": None}


def set_masks(*, folders: Mapping[str, str | None], home: str | None, user: str | None, pc: str | None) -> None:
    """folders maps "<GAME>", "<SMITHBOX>", "<PROJECT>", "<WORKSPACE>", "<SHARE>", "<DATAPILER>" to a folder (or None).
    Rebuilds the mask: each folder in either slash, any case, and its 8.3 short form (winapi short_path), longest
    first; then the home folder as <HOME>; then user and PC names as whole words (<USER>, <PC>); then any IPv4 or
    IPv6 address other than 127.0.0.1 as <IP>. Called at start and on every settings.saved."""
    global _mask
    entries: list[tuple[int, str, str]] = []
    for placeholder, folder in folders.items():
        if not folder:
            continue
        for variant in _folder_variants(str(folder)):
            rx = _folder_rx(variant)
            if rx is not None:
                entries.append((len(variant.rstrip("\\/")), rx, placeholder))
    entries.sort(key=lambda e: -e[0])
    folder_map: dict[str, str] = {}
    alts: list[str] = []
    for i, (_, rx, placeholder) in enumerate(entries):
        group = "f%d" % i
        folder_map[group] = placeholder
        alts.append("(?P<%s>%s)" % (group, rx))
    folders_rx = re.compile("|".join(alts), re.IGNORECASE) if alts else None

    home_rx = None
    if home:
        home_alts = sorted({rx for v in _folder_variants(str(home)) if (rx := _folder_rx(v))}, key=len, reverse=True)
        if home_alts:
            home_rx = re.compile("|".join("(?:%s)" % a for a in home_alts), re.IGNORECASE)

    words: list[tuple[re.Pattern, str]] = []
    for word, repl in sorted(((user, "<USER>"), (pc, "<PC>")), key=lambda w: -len(w[0] or "")):
        if word and word.strip():
            words.append((re.compile(r"(?<!\w)%s(?!\w)" % re.escape(word.strip()), re.IGNORECASE), repl))

    _mask_inputs.update(folders=dict(folders), home=home, user=user, pc=pc)
    _mask = _Mask(folders_rx, folder_map, home_rx, words)


def mask(text: str) -> str:
    """The mask the formatter applies, for the start log and error texts sent to the page."""
    try:
        return _mask.apply(str(text))
    except Exception:
        return "<text>"


# ---------------------------------------------------------------------------------------------------------- format


def _safe(a: object) -> object:
    if a is None:
        return None
    if isinstance(a, bool):
        return bool(a)
    if isinstance(a, int):
        return int(a)
    if isinstance(a, float):
        return float(a)
    if isinstance(a, Own):
        return str.__str__(a)
    if isinstance(a, str):
        return "<text>"
    return "<?>"


def format_message(template: object, args: tuple) -> str:
    """The message of one log call: the template with its safe arguments. Never raises."""
    if not isinstance(template, str):
        return "<?>"
    if not args:
        return str.__str__(template)
    safe = tuple(_safe(a) for a in args)
    try:
        return str.__str__(template) % safe
    except Exception:
        return str.__str__(template) + " <args did not format>"


class _MaskFilter(logging.Filter):
    """The one mask, on every handler: the record's message is replaced by its masked, one-line form."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "dp_masked", False):
            try:
                msg = record.getMessage()
            except Exception:
                msg = "<args did not format>"
            record.msg = mask(_CONTROL_RX.sub(" ", msg))
            record.args = None
            record.dp_masked = True
        return True


class _Formatter(logging.Formatter):
    def __init__(self, colour: bool = False):
        super().__init__()
        self.colour = colour

    def stamp(self, record: logging.LogRecord) -> str:
        return "%s.%03d" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)), int(record.msecs))

    def format(self, record: logging.LogRecord) -> str:
        level = _LEVELNAME.get(record.levelno, "INFO")
        src = getattr(record, "dp_src", "app")
        line = "%s  %-5s  %-8s %s" % (self.stamp(record), level, src, record.msg)
        if self.colour and record.levelno in _ANSI:
            return _ANSI[record.levelno] + line + _RESET
        return line


class _Quiet:
    def handleError(self, record: logging.LogRecord) -> None:   # noqa: N802 - logging's name
        pass                    # a log line that cannot be written never stops DataPiler


class _StreamHandler(_Quiet, logging.StreamHandler):
    pass


class _StderrHandler(_Quiet, logging.Handler):
    """Before setup: lines go to whatever sys.stderr is at the time, masked."""

    def emit(self, record: logging.LogRecord) -> None:
        stream = sys.stderr
        if stream is None:
            return
        try:
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            pass


class _RotatingHandler(_Quiet, logging.handlers.RotatingFileHandler):
    pass


class _FileHandler(_Quiet, logging.FileHandler):
    pass


class _RingHandler(_Quiet, logging.Handler):
    """The Terminal tab's lines: the newest RING, each with a sequence number."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.ring: collections.deque = collections.deque(maxlen=RING)
        self.seq = 0
        self.fmt = _Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        with _ring_lock:
            self.seq += 1
            self.ring.append({
                "seq": self.seq,
                "t": self.fmt.stamp(record),
                "level": _LEVELNAME.get(record.levelno, "INFO"),
                "src": getattr(record, "dp_src", "app"),
                "msg": str(record.msg),
            })


_ring_lock = threading.Lock()
_state_lock = threading.RLock()
_LOGGER = logging.getLogger("datapiler")
_LOGGER.setLevel(logging.DEBUG)
_LOGGER.propagate = False
_MASK_FILTER = _MaskFilter()
_ring = _RingHandler()
_ring.addFilter(_MASK_FILTER)
_early = _StderrHandler(logging.INFO)
_early.setFormatter(_Formatter())
_early.addFilter(_MASK_FILTER)
_file: _RotatingHandler | None = None
_console: _StreamHandler | None = None
_logs_dir: Path | None = None
_debug = False
_job_handlers: "set[_FileHandler]" = set()
_LOGGER.handlers = [_early, _ring]


class Log:
    """The log of one source. Never raises."""

    def __init__(self, source: str):
        self.source = source

    def _record(self, level: int, template: str, args: tuple) -> logging.LogRecord | None:
        try:
            msg = format_message(template, args)
            record = _LOGGER.makeRecord(_LOGGER.name, level, "datapiler", 0, msg, None, None)
            record.dp_src = self.source
            return record
        except Exception:
            return None

    def _log(self, level: int, template: str, args: tuple) -> None:
        if level < logging.INFO and not _debug:
            return
        record = self._record(level, template, args)
        if record is None:
            return
        try:
            _LOGGER.handle(record)
        except Exception:
            pass
        self._also(record)

    def _also(self, record: logging.LogRecord) -> None:
        pass

    def debug(self, template: str, *args: object) -> None:
        self._log(logging.DEBUG, template, args)

    def info(self, template: str, *args: object) -> None:
        self._log(logging.INFO, template, args)

    def warn(self, template: str, *args: object) -> None:
        self._log(logging.WARNING, template, args)

    def error(self, template: str, *args: object) -> None:
        self._log(logging.ERROR, template, args)


class JobLog(Log):
    """Source "job": the main handlers and logs/jobs/<job id>.log, same format, same mask."""

    def __init__(self, job_id: str):
        super().__init__("job")
        self.job_id = job_id
        self._handler: _FileHandler | None = None
        with _state_lock:
            if _logs_dir is not None:
                folder = _logs_dir / "jobs"
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                    h = _FileHandler(folder / (job_id + ".log"), mode="a", encoding="utf-8")
                    h.setFormatter(_Formatter())
                    h.addFilter(_MASK_FILTER)
                    h.setLevel(logging.DEBUG if _debug else logging.INFO)
                    self._handler = h
                    _job_handlers.add(h)
                except OSError:
                    self._handler = None

    def _also(self, record: logging.LogRecord) -> None:
        h = self._handler
        if h is not None and record.levelno >= h.level:
            try:
                h.handle(record)
            except Exception:
                pass

    def close(self) -> None:
        with _state_lock:
            h, self._handler = self._handler, None
            if h is not None:
                _job_handlers.discard(h)
        if h is not None:
            try:
                h.close()
            except Exception:
                pass


_logs: dict[str, Log] = {}


def get(source: str) -> Log:
    """Raises ValueError for a source not in SOURCES."""
    if source not in SOURCES:
        raise ValueError("not a log source")
    with _state_lock:
        log = _logs.get(source)
        if log is None:
            log = _logs[source] = Log(source)
        return log


def setup(logs: Path, *, max_bytes: int, keep: int, console: bool) -> None:
    """The rotating file, the console handler when console is true, the ring. Before setup, lines go to stderr,
    masked."""
    global _file, _console, _logs_dir
    logs = Path(logs)
    with _state_lock:
        _close_main()
        logs.mkdir(parents=True, exist_ok=True)
        # keep counts every file, datapiler.log among them: keep - 1 backups (at least one, as a handler with no
        # backup never limits its file)
        fh = _RotatingHandler(logs / "datapiler.log", maxBytes=max(0, int(max_bytes)),
                              backupCount=max(1, int(keep) - 1), encoding="utf-8")
        fh.setFormatter(_Formatter())
        fh.addFilter(_MASK_FILTER)
        fh.setLevel(logging.DEBUG if _debug else logging.INFO)
        fh.acquire()
        try:
            if fh.stream is None:
                fh.stream = fh._open()
            fh.stream.write(_SEPARATOR + "\n")
            fh.flush()
        finally:
            fh.release()
        handlers: list[logging.Handler] = [fh, _ring]
        _file = fh
        _console = None
        if console and sys.stdout is not None:
            try:
                winapi.backend().enable_vt()
            except Exception:
                pass
            ch = _StreamHandler(sys.stdout)
            ch.setFormatter(_Formatter(colour=True))
            ch.addFilter(_MASK_FILTER)
            ch.setLevel(logging.INFO)
            handlers.insert(1, ch)
            _console = ch
        _logs_dir = logs
        _LOGGER.handlers = handlers


def _close_main() -> None:
    global _file, _console
    for h in (_file, _console):
        if h is None:
            continue
        try:
            h.flush()
            if h is _file:
                h.close()
        except Exception:
            pass
    _file = None
    _console = None


def set_debug(on: bool) -> None:
    global _debug
    with _state_lock:
        _debug = bool(on)
        level = logging.DEBUG if _debug else logging.INFO
        if _file is not None:
            _file.setLevel(level)
        for h in list(_job_handlers):
            h.setLevel(level)


def debug_on() -> bool:
    return _debug


def for_job(job_id: Own) -> JobLog:
    """Source "job"; writes to the main handlers and to logs/jobs/<job_id>.log, same format, same mask."""
    if not paths.name_ok(job_id):
        raise ValueError("not a job id")
    return JobLog(str.__str__(job_id))


def lines_after(seq: int, limit: int = 1000) -> tuple[list[dict], int]:
    """Ring lines with a seq above seq, oldest first, at most limit, as
    {"seq": int, "t": str, "level": str, "src": str, "msg": str}, and the newest seq. Already masked."""
    with _ring_lock:
        newest = _ring.seq
        if seq >= newest:
            return [], newest
        lines = [dict(x) for x in _ring.ring if x["seq"] > seq]
    if limit >= 0:
        lines = lines[:limit]
    return lines, newest


def first_seq() -> int:
    """The oldest seq the ring still keeps (the newest seq plus one while it is empty)."""
    with _ring_lock:
        return _ring.ring[0]["seq"] if _ring.ring else _ring.seq + 1


def _thread_hook(args: "threading.ExceptHookArgs") -> None:
    if args.exc_type is SystemExit:
        return
    e = args.exc_value
    get("app").error("a thread failed: %s", why(e) if e is not None else own(getattr(args.exc_type, "__name__", "?")))


def _main_hook(exc_type: type, exc: BaseException, tb: object) -> None:
    get("app").error("crashed: %s", why(exc) if exc is not None else own(getattr(exc_type, "__name__", "?")))


def install_excepthooks() -> Callable[[], None]:
    """An exception no one catches, in a thread or at the top, is logged by its type alone (the mask's rule: never
    str(e), never a traceback, whose frames name DataPiler's folders and the user's home). The default hooks print
    the traceback to stderr, the window the owner reads. Returns the function that puts the old hooks back."""
    old_thread, old_main = threading.excepthook, sys.excepthook
    threading.excepthook = _thread_hook
    sys.excepthook = _main_hook

    def restore() -> None:
        threading.excepthook, sys.excepthook = old_thread, old_main

    return restore


def shutdown() -> None:
    """Flush and close every handler."""
    global _logs_dir
    with _state_lock:
        for h in list(_job_handlers):
            try:
                h.close()
            except Exception:
                pass
        _job_handlers.clear()
        _close_main()
        _logs_dir = None
        _LOGGER.handlers = [_early, _ring]
