"""Steam's files (build plan 0.2 §5.2, §7.2): the strict KeyValues parser, the library list in both formats and the
app manifest, on invented fixtures and in temporary folders."""

import _repo  # noqa: F401

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from datapiler import logbook, steam

FIX = Path(_repo.ROOT) / "tests" / "fixtures" / "steam"


def vdf_quote(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


class ParseTest(unittest.TestCase):
    def test_the_new_format(self):
        doc = steam.parse_vdf((FIX / "libraryfolders-new.vdf").read_text(encoding="utf-8"))
        root = steam.key(doc, "LIBRARYFOLDERS")                       # lookups are case-insensitive
        self.assertEqual(steam.key(root["1"], "path"), "C:\\Games\\SteamLibrary")
        self.assertIn("1245620", steam.key(root["1"], "apps"))
        self.assertEqual(list(doc), ["libraryfolders"])                # keys keep their case

    def test_the_old_format(self):
        doc = steam.parse_vdf((FIX / "libraryfolders-old.vdf").read_text(encoding="utf-8"))
        root = steam.key(doc, "libraryfolders")
        self.assertEqual(root["1"], "C:\\Games\\SteamLibrary")
        self.assertEqual(root["2"], "C:/Other Library")

    def test_escapes_and_comments(self):
        doc = steam.parse_vdf('// a comment\n"a" { "b" "x\\\\y\\"z\\n\\t" // after\n "c" "" }')
        self.assertEqual(doc, {"a": {"b": 'x\\y"z\n\t', "c": ""}})
        self.assertEqual(steam.parse_vdf('\ufeff"k" "v"'), {"k": "v"})

    def test_refusals(self):
        for text, why in (('"a" {', "an unclosed brace"), ('"a" { "b" "c" } }', "a closing brace"),
                          ("a b", "an unquoted token"), ('"a" "b', "an unclosed string"),
                          ('"a" "\\q"', "an escape"), ('"a"', "a key without a value"), ("{ }", "a block without"),
                          ('"a" [$WIN32]', "an unquoted token"), ('"a" { "b" }', "a key without a value")):
            with self.subTest(text=text):
                with self.assertRaises(steam.VdfError) as cm:
                    steam.parse_vdf(text)
                self.assertIn(why, cm.exception.why)

    def test_limits(self):
        deep = "".join('"k%d" { ' % i for i in range(steam.VDF_DEPTH + 2)) + "}" * (steam.VDF_DEPTH + 2)
        with self.assertRaises(steam.VdfError):
            steam.parse_vdf(deep)
        ok = "".join('"k%d" { ' % i for i in range(steam.VDF_DEPTH)) + "}" * steam.VDF_DEPTH
        steam.parse_vdf(ok)
        with self.assertRaises(steam.VdfError):
            steam.parse_vdf('"a" "' + "x" * steam.VDF_MAX + '"')
        many = "".join('"k%d" "v" ' % i for i in range(steam.VDF_KEYS + 1))
        with self.assertRaises(steam.VdfError):
            steam.parse_vdf(many)


class FilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.steam = self.base / "Steam"
        (self.steam / "steamapps").mkdir(parents=True)
        (self.steam / "config").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_new(self, where: Path, libs: dict):
        blocks = []
        for i, (path, apps) in enumerate(libs.items()):
            app_lines = "".join('"%d" "1"\n' % a for a in apps)
            blocks.append('"%d" { "path" "%s" "apps" { %s } }' % (i, vdf_quote(path), app_lines))
        where.write_text('"libraryfolders" { %s }' % " ".join(blocks), encoding="utf-8")

    def test_libraries_merges_both_files_and_the_steam_folder(self):
        lib = str(self.base / "Library")
        self.write_new(self.steam / "steamapps" / "libraryfolders.vdf", {str(self.steam): [228980], lib: [9000001]})
        self.write_new(self.steam / "config" / "libraryfolders.vdf", {lib.upper() if os.name == "nt" else lib:
                                                                      [steam.GAME_APP_ID]})
        libs = steam.libraries(str(self.steam))
        self.assertEqual(len(libs), 2)
        by = {Path(x.path).name.casefold(): x for x in libs}
        self.assertEqual(by["library"].apps, frozenset({9000001, steam.GAME_APP_ID}))
        self.assertEqual(by["steam"].apps, frozenset({228980}))

    def test_the_old_file_gives_libraries_without_apps(self):
        shutil.copy(FIX / "libraryfolders-old.vdf", self.steam / "steamapps" / "libraryfolders.vdf")
        libs = steam.libraries(str(self.steam))
        self.assertEqual([x.path for x in libs], [str(self.steam), "C:\\Games\\SteamLibrary", "C:/Other Library"])
        self.assertTrue(all(x.apps is None for x in libs))

    def test_no_file_is_the_steam_folder_alone_and_a_broken_one_is_said(self):
        self.assertEqual(steam.libraries(str(self.steam)), [steam.Library(str(self.steam), None)])
        (self.steam / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders" {', encoding="utf-8")
        _, seq = logbook.lines_after(0, limit=0)
        with self.assertRaises(steam.VdfError):
            steam.libraries(str(self.steam))
        lines, _ = logbook.lines_after(seq)
        self.assertTrue(any(ln["src"] == "folders" and "library list could not be read" in ln["msg"] for ln in lines))
        self.assertFalse(any(str(self.base) in ln["msg"] for ln in lines))
        # one good file of the two is enough
        self.write_new(self.steam / "config" / "libraryfolders.vdf", {str(self.base / "Lib"): [1]})
        self.assertEqual(len(steam.libraries(str(self.steam))), 2)

    def test_app_manifest(self):
        apps = self.steam / "steamapps"
        shutil.copy(FIX / "appmanifest_1245620.acf", apps / "appmanifest_1245620.acf")
        m = steam.app_manifest(str(self.steam), steam.GAME_APP_ID)
        self.assertEqual(m, steam.AppManifest("ELDEN RING", (9000020,)))
        self.assertEqual(steam.game_folder(str(self.steam), m.installdir),
                         os.path.normpath(str(self.steam / "steamapps" / "common" / "ELDEN RING" / "Game")))
        self.assertIsNone(steam.app_manifest(str(self.steam), 9000099))           # not there
        # a separator, a drive or '..' in installdir is refused; the DLC ids are still read
        text = (FIX / "appmanifest_1245620.acf").read_text(encoding="utf-8")
        for bad in ("..\\\\Other", "C:\\\\Games", "a/b", "..", "trailing. "):
            with self.subTest(bad=bad):
                (apps / "appmanifest_1245620.acf").write_text(text.replace('"ELDEN RING"', '"%s"' % bad),
                                                              encoding="utf-8")
                self.assertEqual(steam.app_manifest(str(self.steam), steam.GAME_APP_ID),
                                 steam.AppManifest("", (9000020,)))
        # no DLC depot: an empty tuple; a manifest for another app is not this one's
        (apps / "appmanifest_1245620.acf").write_text(
            '"AppState" { "appid" "1245620" "installdir" "ELDEN RING" "InstalledDepots" { "1" { "size" "2" } } }',
            encoding="utf-8")
        self.assertEqual(steam.app_manifest(str(self.steam), steam.GAME_APP_ID).dlc_app_ids, ())
        (apps / "appmanifest_1245620.acf").write_text('"AppState" { "appid" "7" "installdir" "X" }', encoding="utf-8")
        self.assertIsNone(steam.app_manifest(str(self.steam), steam.GAME_APP_ID))

    def test_nothing_is_written(self):
        shutil.copy(FIX / "libraryfolders-new.vdf", self.steam / "steamapps" / "libraryfolders.vdf")
        shutil.copy(FIX / "appmanifest_1245620.acf", self.steam / "steamapps" / "appmanifest_1245620.acf")
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.steam.rglob("*") if p.is_file()}
        steam.libraries(str(self.steam))
        steam.app_manifest(str(self.steam), steam.GAME_APP_ID)
        after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.steam.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
