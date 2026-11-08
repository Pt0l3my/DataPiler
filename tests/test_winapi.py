import _repo  # noqa: F401

import os
import sys
import tempfile
import unittest
from pathlib import Path

from datapiler import winapi


class PortableTest(unittest.TestCase):
    def setUp(self):
        self.b = winapi.PortableBackend()

    def test_documented_answers(self):
        self.assertIsNone(self.b.file_version(sys.executable))
        self.assertFalse(self.b.set_clipboard("x"))
        self.assertFalse(self.b.open_folder("."))
        self.assertIsNone(self.b.short_path("."))
        self.assertFalse(self.b.drive_is_remote("."))
        self.assertIsNone(self.b.enable_vt())
        procs = self.b.processes()
        self.assertIsInstance(procs, list)
        for p in procs:
            self.assertEqual(p.name, p.name.lower())
        if Path("/proc").is_dir():
            self.assertTrue(any(p.path and os.path.samefile(p.path, sys.executable) for p in procs
                                if p.path and os.path.exists(p.path)) or procs)

    def test_hold_mutex_twice(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "datapiler.lock"
            h = self.b.hold_mutex("Local\\DataPiler-test", f)
            self.assertIsNotNone(h)
            self.assertIsNone(self.b.hold_mutex("Local\\DataPiler-test", f))
            h.release()
            h.release()                          # twice is harmless
            again = self.b.hold_mutex("Local\\DataPiler-test", f)
            self.assertIsNotNone(again)
            again.release()

    def test_on_console_close_off_the_main_thread_is_harmless(self):
        import threading
        t = threading.Thread(target=self.b.on_console_close, args=(lambda: None,))
        t.start()
        t.join()

    def test_use_swaps_the_backend(self):
        fake = winapi.PortableBackend()
        before = winapi.backend()
        with winapi.use(fake):
            self.assertIs(winapi.backend(), fake)
        self.assertIs(winapi.backend(), before)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class WindowsTest(unittest.TestCase):
    def setUp(self):
        self.b = winapi.WindowsBackend()

    def test_own_process_listed(self):
        name = os.path.basename(sys.executable).lower()
        self.assertTrue(any(p.name == name for p in self.b.processes()))

    def test_second_mutex(self):
        with tempfile.TemporaryDirectory() as d:
            h = self.b.hold_mutex("Local\\DataPiler-test-%d" % os.getpid(), Path(d) / "x.lock")
            self.assertIsNotNone(h)
            self.assertIsNone(self.b.hold_mutex("Local\\DataPiler-test-%d" % os.getpid(), Path(d) / "x.lock"))
            h.release()

    def test_a_local_folder_is_not_remote(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(self.b.drive_is_remote(d))
        self.assertTrue(self.b.drive_is_remote("\\\\server.invalid\\share\\ws"))

    def test_python_has_a_file_version(self):
        v = self.b.file_version(sys.executable)
        self.assertRegex(v or "", r"^\d+\.\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
