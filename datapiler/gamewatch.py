"""The game watcher (build plan §4.5): while the server link is on, a daemon thread checks every 2 s whether the game
runs, and tells the link when that changes.

A running game is reported at the first check that sees it. A closed game is reported only once it has been closed
for `closed_checks` checks in a row (two by default), so the link comes back only when the game has really gone. A
check that raises counts as the game running: the watcher fails closed."""

from __future__ import annotations

import threading
from typing import Callable

from . import logbook

_log = logbook.get("link")


class GameWatch:
    def __init__(self, game: Callable[[], object], on_change: Callable[[bool], None], interval: float = 2.0, *,
                 closed_checks: int = 2):
        """game() returns a GameRunning (its `running` is read); on_change(running) is called from the watcher's
        thread when the reading flips. The reading starts as closed: the link is switched on only while the game is
        closed."""
        self._game = game
        self._on_change = on_change
        self._interval = max(0.01, float(interval))
        self._closed_checks = max(1, int(closed_checks))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._closed_seen = 0

    @property
    def running(self) -> bool:
        """The last reading reported (or noted through saw_running)."""
        with self._lock:
            return self._running

    def start(self) -> None:
        """A daemon thread: checks at once, then every interval; calls on_change(running) when it flips."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop = threading.Event()
            self._thread = threading.Thread(target=self._loop, args=(self._stop,), name="datapiler-gamewatch",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Ends the thread; waits for it unless called from the watcher's own thread (from on_change)."""
        with self._lock:
            self._stop.set()
            t = self._thread
            self._thread = None
        if t is not None and t is not threading.current_thread():
            t.join(self._interval + 5.0)

    def saw_running(self) -> None:
        """The link saw the game running between two checks (its own check before a call): take that as the
        reading, without a call to on_change, so the closed game is again reported only after closed_checks."""
        with self._lock:
            self._running = True
            self._closed_seen = 0

    def check_once(self) -> bool | None:
        """One check, as the thread makes it. Returns the new reading when it flipped, else None. For tests and the
        thread."""
        try:
            now = bool(self._game().running)
        except Exception as e:
            _log.warn("the game check failed (%s) - counted as running", logbook.why(e))
            now = True
        with self._lock:
            if now:
                self._closed_seen = 0
                if self._running:
                    return None
                self._running = True
                flipped: bool | None = True
            else:
                if not self._running:
                    return None
                self._closed_seen += 1
                if self._closed_seen < self._closed_checks:
                    return None
                self._running = False
                self._closed_seen = 0
                flipped = False
        try:
            self._on_change(flipped)
        except Exception as e:
            _log.error("the game watcher's handler failed: %s", logbook.why(e))
        return flipped

    def _loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.check_once()
            if stop.wait(self._interval):
                break
