"""The in-process event bus (build plan §3.2).

Event data follows the log rule: numbers, booleans, None and Own strings only. The page polls; events never reach
it directly."""

from __future__ import annotations

import threading
from typing import Callable

from . import logbook

Subscriber = Callable[[str, dict], None]

_lock = threading.Lock()
_subs: list[tuple[str, Subscriber]] = []
_warned: set[str] = set()


def _allowed(v: object) -> bool:
    return v is None or isinstance(v, (bool, int, float, logbook.Own))


def emit(topic: str, **data: object) -> None:
    """Call every subscriber whose prefix matches topic, in this thread. A subscriber that raises is logged
    (source app, ERROR, logbook.why(e)) and the others still run. Never raises."""
    try:
        bad = [k for k, v in data.items() if not _allowed(v)]
        if bad and topic not in _warned:
            _warned.add(topic)
            logbook.get("app").warn("event %s carried a value that is not a number, a flag or DataPiler's own "
                                    "word (key %s)", logbook.own(topic), logbook.own(bad[0]))
        with _lock:
            targets = [fn for prefix, fn in _subs if topic.startswith(prefix)]
    except Exception:
        return
    for fn in targets:
        try:
            fn(topic, dict(data))
        except Exception as e:
            try:
                logbook.get("app").error("an event handler for %s failed: %s", logbook.own(topic), logbook.why(e))
            except Exception:
                pass


def subscribe(prefix: str, fn: Subscriber) -> Callable[[], None]:
    """fn(topic, data) for every topic starting with prefix. Returns the function that unsubscribes."""
    entry = (prefix, fn)
    with _lock:
        _subs.append(entry)

    def unsubscribe() -> None:
        with _lock:
            try:
                _subs.remove(entry)
            except ValueError:
                pass

    return unsubscribe
