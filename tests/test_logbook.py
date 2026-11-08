import _repo  # noqa: F401

import io
import sys
import tempfile
import unittest
from pathlib import Path

from datapiler import VERSION, logbook



class LogbookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self.tmp.name) / "logs"
        self.out = io.StringIO()
        self._stdout = sys.stdout
        sys.stdout = self.out
        logbook.set_masks(folders={}, home=None, user=None, pc=None)
        logbook.set_debug(False)
        logbook.setup(self.logs, max_bytes=1 << 20, keep=2, console=True)
        _, self.seq = logbook.lines_after(0, limit=0)

    def tearDown(self):
        logbook.set_debug(False)
        logbook.shutdown()
        sys.stdout = self._stdout
        self.tmp.cleanup()

    def file_lines(self):
        logbook.shutdown()
        return (self.logs / "datapiler.log").read_text(encoding="utf-8").splitlines()

    def ring(self):
        lines, _ = logbook.lines_after(self.seq, limit=logbook.RING)
        return lines

    def test_exact_line_format(self):
        logbook.get("extract").info("NpcParam: %s rows read in %s s", logbook.n(2105), logbook.n(0.42))
        lines = self.file_lines()
        self.assertEqual(lines[0], "---- DataPiler %s ----" % VERSION)
        self.assertRegex(lines[1], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}  INFO   extract  "
                                   r"NpcParam: 2,105 rows read in 0\.4 s$")

    def test_levels_and_sources(self):
        for lv, src in (("info", "app"), ("warn", "link"), ("error", "guard")):
            getattr(logbook.get(src), lv)("a line")
        lines = self.file_lines()[1:]
        self.assertIn("  INFO   app      a line", lines[0])
        self.assertIn("  WARN   link     a line", lines[1])
        self.assertIn("  ERROR  guard    a line", lines[2])
        with self.assertRaises(ValueError):
            logbook.get("nobody")

    def test_debug_only_to_the_file_and_only_with_the_switch(self):
        log = logbook.get("link")
        log.debug("hidden one")
        logbook.set_debug(True)
        log.debug("shown one")
        logbook.set_debug(False)
        log.debug("hidden two")
        ring = [x["msg"] for x in self.ring()]
        console = self.out.getvalue()
        lines = self.file_lines()
        self.assertIn("shown one", "\n".join(lines))
        self.assertNotIn("hidden", "\n".join(lines))
        self.assertNotIn("shown one", ring)
        self.assertNotIn("shown one", console)

    def test_console_and_ring_take_info_and_up(self):
        log = logbook.get("app")
        log.info("an info")
        log.warn("a warning")
        log.error("an error")
        ring = self.ring()
        self.assertEqual([x["level"] for x in ring], ["INFO", "WARN", "ERROR"])
        self.assertEqual(set(ring[0]), {"seq", "t", "level", "src", "msg"})
        console = self.out.getvalue()
        self.assertIn("\x1b[33m", console)
        self.assertIn("\x1b[31m", console)
        self.assertIn("an info", console)

    def test_ring_capped(self):
        log = logbook.get("app")
        for i in range(logbook.RING + 25):
            log.info("line %s", i)
        lines, last = logbook.lines_after(0, limit=logbook.RING + 100)
        self.assertEqual(len(lines), logbook.RING)
        self.assertEqual(lines[-1]["seq"], last)
        self.assertEqual(logbook.first_seq(), lines[0]["seq"])
        some, _ = logbook.lines_after(last - 10, limit=3)
        self.assertEqual([x["seq"] for x in some], [last - 9, last - 8, last - 7])

    def test_rotation_keeps_keep_files(self):
        """log_keep counts every file kept, datapiler.log among them (design §5: "five files kept")."""
        for keep, names in ((2, ["datapiler.log", "datapiler.log.1"]),
                            (5, ["datapiler.log"] + ["datapiler.log.%d" % i for i in range(1, 5)])):
            with self.subTest(keep=keep):
                logbook.shutdown()
                for p in self.logs.iterdir():
                    if p.is_file():
                        p.unlink()
                logbook.setup(self.logs, max_bytes=300, keep=keep, console=False)
                log = logbook.get("app")
                for i in range(120):
                    log.info("a line long enough to fill the tiny file quickly %s", i)
                logbook.shutdown()
                self.assertEqual(sorted(p.name for p in self.logs.iterdir() if p.is_file()), names)

    def test_an_uncaught_exception_is_logged_by_its_type_only(self):
        """No traceback in the window: its frames name DataPiler's folders and the user's home (design §5)."""
        import threading
        err = io.StringIO()
        old_err = sys.stderr
        restore = logbook.install_excepthooks()
        try:
            sys.stderr = err

            def boom():
                raise ValueError("a text with a folder in it")

            t = threading.Thread(target=boom)
            t.start()
            t.join()
            try:
                raise KeyError("another text")
            except KeyError:
                sys.excepthook(*sys.exc_info())
        finally:
            sys.stderr = old_err
            restore()
        self.assertEqual(err.getvalue(), "")
        msgs = [x["msg"] for x in self.ring()]
        self.assertIn("a thread failed: ValueError", msgs)
        self.assertIn("crashed: KeyError", msgs)
        self.assertNotIn("folder", self.out.getvalue())
        self.assertIsNot(threading.excepthook, logbook._thread_hook)
        self.assertIsNot(sys.excepthook, logbook._main_hook)

    def test_job_log(self):
        jl = logbook.for_job(logbook.own("en-0007-roster-counts"))
        jl.info("started: %s ops", 3)
        jl.close()
        f = self.logs / "jobs" / "en-0007-roster-counts.log"
        self.assertIn("  INFO   job      started: 3 ops", f.read_text(encoding="utf-8"))
        self.assertIn("started: 3 ops", "\n".join(self.file_lines()))
        with self.assertRaises(ValueError):
            logbook.for_job(logbook.own("../escape"))

    def test_formatting_never_raises(self):
        log = logbook.get("app")
        log.info("%d rows", "not a number")
        log.info("%s %s", 1)
        log.info("no placeholder", 1, 2)
        log.info(None)                          # not a template at all
        log.info("100% done")
        msgs = [x["msg"] for x in self.ring()]
        self.assertEqual(msgs[0], "%d rows <args did not format>")
        self.assertEqual(msgs[1], "%s %s <args did not format>")
        self.assertEqual(msgs[2], "no placeholder <args did not format>")
        self.assertEqual(msgs[3], "<?>")
        self.assertEqual(msgs[4], "100% done")

    def test_arguments(self):
        log = logbook.get("app")

        class Thing:
            def __str__(self):
                return "Thing-Text"

        log.info("%s|%s|%s|%s|%s|%s", "plain", logbook.own("own"), 7, 0.5, None, Thing())
        log.info("%s", True)
        msgs = [x["msg"] for x in self.ring()]
        self.assertEqual(msgs[0], "<text>|own|7|0.5|None|<?>")
        self.assertEqual(msgs[1], "True")

    def test_helpers(self):
        self.assertEqual(logbook.n(2105), "2,105")
        self.assertEqual(logbook.n(0.42), "0.4")
        self.assertEqual(logbook.why(PermissionError(13, "secret words")), "PermissionError (errno 13)")
        self.assertEqual(logbook.why(ValueError("secret words")), "ValueError")
        self.assertIsInstance(logbook.why(KeyError("x")), logbook.Own)

    def test_a_line_stays_one_line(self):
        logbook.get("app").info("%s", logbook.own("one\ntwo\rthree"))
        self.assertEqual(self.ring()[0]["msg"], "one two three")


if __name__ == "__main__":
    unittest.main()
