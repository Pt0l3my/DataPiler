"""DP29 (S83): the PC's hardware, read on any system, and what the image steps may use."""

import _repo  # noqa: F401

import sys
import unittest

from datapiler import hardware as hw

GB = 2 ** 30


def pc(logical=8, free=16 * GB):
    return hw.Hardware(logical, logical // 2, 32 * GB, free, "an invented processor", ("an invented card",))


class PlanTest(unittest.TestCase):
    def test_automatic(self):
        w = hw.plan(pc())
        self.assertEqual((w.workers, w.memory, w.auto_workers, w.auto_memory), (7, 4 * GB, True, True))
        self.assertEqual(hw.plan(pc(logical=1)).workers, 1)
        self.assertEqual(hw.plan(pc(free=100 * GB)).memory, hw.MEMORY_MAX_AUTO)
        self.assertEqual(hw.plan(pc(free=10 * 2 ** 20)).memory, hw.MEMORY_MIN)
        self.assertEqual(hw.plan(pc(free=None)).memory, hw.MEMORY_MIN)

    def test_the_settings_caps(self):
        w = hw.plan(pc(), 3, 1024)
        self.assertEqual((w.workers, w.memory, w.auto_workers, w.auto_memory), (3, GB, False, False))
        self.assertEqual(hw.plan(pc(logical=4), 64).workers, 4)          # never more than the PC has

    def test_public(self):
        self.assertEqual(set(pc().public()), {"logical", "physical", "memory", "free", "cpu", "graphics"})
        self.assertEqual(set(hw.plan(pc()).public()), {"workers", "memory", "auto_workers", "auto_memory"})


class ScanTest(unittest.TestCase):
    def test_a_scan_on_this_system(self):
        h = hw.scan(fresh=True)
        self.assertGreaterEqual(h.logical, 1)
        self.assertIs(hw.scan(), h)                                       # reused within RESCAN
        if h.memory is not None:
            self.assertGreater(h.memory, 0)
            self.assertLessEqual(h.free or 0, h.memory)
        self.assertIsInstance(h.graphics, tuple)

    @unittest.skipUnless(sys.platform == "win32", "Windows' own answers")
    def test_windows_reads_its_memory(self):
        h = hw.scan(fresh=True)
        self.assertIsNotNone(h.memory)
        self.assertIsNotNone(h.free)


if __name__ == "__main__":
    unittest.main()
