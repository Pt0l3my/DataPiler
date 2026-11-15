"""DP19 (settled S59): two of Smithbox's preferences, read only, before a map job; nothing else of the file leaves
`smithbox.map_prefs`. Invented values and folders only."""

import _repo  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path

from datapiler import smithbox


class MapPrefsTest(unittest.TestCase):
    def test_the_two_values_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "Smithbox" / "Configuration"
            conf.mkdir(parents=True)
            startup = conf / "Startup.json"
            startup.write_text("{}", encoding="utf-8")
            self.assertIsNone(smithbox.map_prefs(startup))                        # no Configuration.json
            (conf / "Configuration.json").write_text(json.dumps({
                "Viewport_Enable_Rendering": False, "MapEditor_SkipHavokLoad": True,
                "Some_Folder": "C:\\Invented\\Folder"}), encoding="utf-8")
            prefs = smithbox.map_prefs(startup)
            self.assertEqual(prefs, {"rendering": False, "skip_havok": True})
            self.assertNotIn("Invented", json.dumps(prefs))
            (conf / "Configuration.json").write_text(json.dumps({"Viewport_Enable_Rendering": "yes"}),
                                                     encoding="utf-8")
            self.assertEqual(smithbox.map_prefs(startup), {"rendering": None, "skip_havok": None})
            (conf / "Configuration.json").write_text("not json", encoding="utf-8")
            self.assertIsNone(smithbox.map_prefs(startup))

    def test_no_folder_known(self):
        self.assertIsNone(smithbox.map_prefs(None) if smithbox.startup_json() is None else None)


if __name__ == "__main__":
    unittest.main()
