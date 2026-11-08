"""The game watcher (build plan §8.2): flips reported once each, a closed game only after two checks in a row, a
failed check counted as running, and stop ending the thread."""

import _repo  # noqa: F401

import threading
import time
import types
import unittest

from datapiler.gamewatch import GameWatch


class Script:
    """game() answering from a list of readings, then repeating the last one; True means running."""

    def __init__(self, readings):
        self.readings = list(readings)
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            i = min(self.calls, len(self.readings) - 1)
            self.calls += 1
            value = self.readings[i]
        if isinstance(value, Exception):
            raise value
        return types.SimpleNamespace(running=value, why=None)


class GameWatchTests(unittest.TestCase):
    def test_each_flip_reported_once(self):
        flips = []
        w = GameWatch(Script([False, True, True, True, False, False, False, True, False, False]), flips.append)
        got = [w.check_once() for _ in range(12)]
        self.assertEqual(flips, [True, False, True, False])
        self.assertEqual([g for g in got if g is not None], [True, False, True, False])

    def test_closed_only_after_two_checks_in_a_row(self):
        flips = []
        w = GameWatch(Script([True, False, True, False, False]), flips.append)
        for _ in range(4):
            w.check_once()
        self.assertEqual(flips, [True])             # one closed reading between two running ones is not enough
        w.check_once()
        self.assertEqual(flips, [True, False])

    def test_a_failed_check_counts_as_running(self):
        flips = []
        w = GameWatch(Script([OSError(5, "unreadable"), False, False]), flips.append)
        for _ in range(3):
            w.check_once()
        self.assertEqual(flips, [True, False])

    def test_saw_running(self):
        flips = []
        w = GameWatch(Script([False]), flips.append)
        w.saw_running()
        self.assertTrue(w.running)
        w.check_once()
        self.assertEqual(flips, [])
        w.check_once()
        self.assertEqual(flips, [False])

    def test_a_handler_that_raises_does_not_stop_the_watch(self):
        def boom(running):
            raise RuntimeError("handler")
        w = GameWatch(Script([True, False, False]), boom)
        self.assertTrue(w.check_once())
        w.check_once()
        self.assertFalse(w.check_once())

    def test_thread_checks_at_once_and_stop_ends_it(self):
        flips = []
        script = Script([True])
        w = GameWatch(script, flips.append, interval=0.02)
        w.start()
        end = time.monotonic() + 2
        while not flips and time.monotonic() < end:
            time.sleep(0.005)
        self.assertEqual(flips, [True])
        thread = w._thread
        self.assertTrue(thread.daemon)
        w.stop()
        self.assertFalse(thread.is_alive())
        calls = script.calls
        time.sleep(0.1)
        self.assertEqual(script.calls, calls)       # no check after stop
        self.assertEqual(flips, [True])

    def test_stop_from_the_handler(self):
        holder = {}

        def on_change(running):
            holder["w"].stop()
        w = GameWatch(Script([True]), on_change, interval=0.02)
        holder["w"] = w
        w.start()
        thread = w._thread
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_restart(self):
        flips = []
        script = Script([False])
        w = GameWatch(script, flips.append, interval=0.02)
        w.start()
        w.stop()
        w.start()
        time.sleep(0.06)
        self.assertTrue(w._thread.is_alive())
        w.stop()
        self.assertEqual(flips, [])


if __name__ == "__main__":
    unittest.main()
