import _repo  # noqa: F401

import tempfile
import unittest
from pathlib import Path

from datapiler import logbook, winapi


class FakeBackend(winapi.PortableBackend):
    def __init__(self, shorts=None):
        self.shorts = shorts or {}

    def short_path(self, path):
        return self.shorts.get(path)


GAME = "C:\\Games\\Steam\\steamapps\\common\\ELDEN RING\\Game"
DATAPILER = "C:\\Tools\\DataPiler"
WORKSPACE = "C:\\Tools\\DataPiler\\workspace"
HOME = "C:\\Users\\player"


class MaskingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        logbook.setup(Path(self.tmp.name) / "logs", max_bytes=1 << 20, keep=1, console=False)
        _, self.seq = logbook.lines_after(0, limit=0)
        with winapi.use(FakeBackend({GAME: "C:\\Games\\Steam\\STEAMA~1\\common\\ELDENR~1\\Game"})):
            logbook.set_masks(folders={"<GAME>": GAME, "<SMITHBOX>": "C:\\Tools\\Smithbox", "<PROJECT>": None,
                                       "<WORKSPACE>": WORKSPACE, "<SHARE>": "C:\\Tools\\DataPiler\\share",
                                       "<DATAPILER>": DATAPILER},
                              home=HOME, user="zorblax", pc="QUENTIN-RIG")

    def tearDown(self):
        logbook.set_masks(folders={}, home=None, user=None, pc=None)
        logbook.shutdown()
        self.tmp.cleanup()

    def m(self, s):
        return logbook.mask(s)

    def test_each_placeholder(self):
        self.assertEqual(self.m(GAME + "\\regulation.bin"), "<GAME>\\regulation.bin")
        self.assertEqual(self.m("C:\\Tools\\Smithbox\\Smithbox.exe"), "<SMITHBOX>\\Smithbox.exe")
        self.assertEqual(self.m("C:\\Tools\\DataPiler\\share\\x.json"), "<SHARE>\\x.json")
        self.assertEqual(self.m("C:\\Tools\\DataPiler\\datapiler.py"), "<DATAPILER>\\datapiler.py")
        self.assertEqual(self.m(HOME + "\\AppData\\Local"), "<HOME>\\AppData\\Local")

    def test_either_slash_and_any_case(self):
        self.assertEqual(self.m("c:/games/steam/STEAMAPPS/common/elden ring/game/x"), "<GAME>/x")
        self.assertEqual(self.m("C:\\Games/Steam\\steamapps/common\\ELDEN RING/Game"), "<GAME>")

    def test_learn_found(self):
        """Detect's candidates as <FOUND>, after the named folders, for the session; a drive alone never."""
        found = "C:\\Old\\Smithbox-1.0"
        self.assertEqual(self.m(found + "\\x.exe"), found + "\\x.exe")
        logbook.learn_found([found, "C:\\", "relative\\folder", 5, GAME + "\\mod", GAME])
        self.assertEqual(self.m(found + "\\x.exe"), "<FOUND>\\x.exe")
        self.assertEqual(self.m("c:/old/smithbox-1.0"), "<FOUND>")
        self.assertEqual(self.m(GAME + "\\regulation.bin"), "<GAME>\\regulation.bin")    # the named one first
        self.assertEqual(self.m(GAME + "\\mod\\a"), "<GAME>\\mod\\a")
        self.assertEqual(self.m("C:\\Other"), "C:\\Other")                              # not the drive
        self.assertEqual(self.m("relative\\folder"), "relative\\folder")
        # kept when the named folders change (settings.saved), never saved anywhere
        logbook.set_masks(folders={"<GAME>": GAME}, home=None, user=None, pc=None)
        self.assertEqual(self.m(found), "<FOUND>")
        logbook.get("app").info("a line about %s", logbook.own(found + "\\x"))
        lines, _ = logbook.lines_after(self.seq)
        self.assertEqual(lines[-1]["msg"], "a line about <FOUND>\\x")

    def test_a_folder_ends_where_its_name_ends(self):
        """Found by the correctness review (C6): a folder's mask also matched any longer name that began with it."""
        self.assertEqual(self.m("C:\\Tools\\Smithbox-old\\x"), "C:\\Tools\\Smithbox-old\\x")
        self.assertEqual(self.m("C:\\Tools\\Smithbox2\\x"), "C:\\Tools\\Smithbox2\\x")
        self.assertEqual(self.m("C:\\Tools\\Smithbox.old"), "C:\\Tools\\Smithbox.old")
        self.assertEqual(self.m(HOME + "Two\\Mods"), HOME + "Two\\Mods")
        self.assertEqual(self.m(HOME + " Smith\\Mods"), HOME + " Smith\\Mods")
        # where a sentence, a quotation or a list goes on, the folder still ends
        for tail in ("", " - x", ".", ". Next", "'", '"', ")", ";", ",", ": x", "\\", "/"):
            with self.subTest(tail=tail):
                self.assertEqual(self.m("C:\\Tools\\Smithbox" + tail), "<SMITHBOX>" + tail)
                if not tail.startswith(" "):                # the home folder never ends before a space
                    self.assertEqual(self.m(HOME + tail), "<HOME>" + tail)
        self.assertEqual(self.m("'C:\\\\Tools\\\\Smithbox'"), "'<SMITHBOX>'")      # an exception's repr
        # a sibling that only adds words is its own once known, before the named folder it starts with
        sibling = "C:\\Tools\\Smithbox 2.2.6 2026-11-01"
        logbook.learn_found([sibling])
        self.assertEqual(self.m(sibling + "\\Smithbox.Vulkan.exe"), "<FOUND>\\Smithbox.Vulkan.exe")
        self.assertEqual(self.m("C:\\Tools\\Smithbox\\Smithbox.exe"), "<SMITHBOX>\\Smithbox.exe")

    def test_short_form(self):
        self.assertEqual(self.m("C:\\Games\\Steam\\STEAMA~1\\common\\ELDENR~1\\Game\\eldenring.exe"),
                         "<GAME>\\eldenring.exe")

    def test_longest_first(self):
        self.assertEqual(self.m(WORKSPACE + "\\inbox\\a.json"), "<WORKSPACE>\\inbox\\a.json")
        self.assertEqual(self.m(DATAPILER + "\\logs"), "<DATAPILER>\\logs")

    def test_words(self):
        self.assertEqual(self.m("by zorblax on QUENTIN-RIG"), "by <USER> on <PC>")
        self.assertEqual(self.m("ZORBLAX's files"), "<USER>'s files")
        self.assertEqual(self.m("zorblaxian quentin-rigs"), "zorblaxian quentin-rigs")

    def test_addresses(self):
        self.assertEqual(self.m("from 203.0.113.7 and 127.0.0.1"), "from <IP> and 127.0.0.1")
        self.assertEqual(self.m("at http://127.0.0.1:8831/"), "at http://127.0.0.1:8831/")
        self.assertEqual(self.m("v6 fe80::1c2b:3a and 2001:db8:0:0:0:0:2:1 end"), "v6 <IP> and <IP> end")
        self.assertEqual(self.m("at 08:42:01.123"), "at 08:42:01.123")

    def test_a_log_line_is_masked_and_plain_text_hidden(self):
        log = logbook.get("smithbox")
        log.info("found in %s - %s", logbook.own("C:\\Tools\\Smithbox"), "C:\\Tools\\Smithbox")
        lines, _ = logbook.lines_after(self.seq, limit=10)
        self.assertEqual(lines[-1]["msg"], "found in <SMITHBOX> - <text>")


if __name__ == "__main__":
    unittest.main()
