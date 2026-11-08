"""tools/repocheck.py, the repository's own check (settled S14, build plan §8.4), on trees built in temporary folders.
The addresses planted here are put together at run time, so this file holds none for a sweep to find."""

import _repo  # noqa: F401

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.join(_repo.ROOT, "tools"))
import repocheck  # noqa: E402


def dotted(*parts: int) -> str:
    return ".".join(str(p) for p in parts)


LAN_V4 = dotted(192, 168, 7, 23)
TEN_V4 = dotted(10, 20, 30, 40)
CGNAT_V4 = dotted(100, 64, 3, 9)
LINK_LOCAL_V4 = dotted(169, 254, 10, 11)
PUBLIC_V4 = dotted(8, 8, 4, 4)
OTHER_LOOPBACK = dotted(127, 0, 0, 2)
PUBLIC_V6 = ":".join(["2a01", "4f8", "c0c", "1234"]) + "::1"
ULA_V6 = ":".join(["fd12", "3456", "789a"]) + "::5"
FULL_LINK_LOCAL_V6 = "fe80::" + ":".join(["a1b2", "c3d4", "e5f6", "0789"])


class TreeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "tree"
        self.root.mkdir()
        self.put("README.md", "# An invented project\n\nServed on 127.0.0.1 only.\n")
        self.put("tests/fixtures/job-files/good.json", json.dumps({"format": "datapiler-job/1", "id": "count-rows"}))

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel: str, text: str | bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, str):
            text = text.encode("utf-8")
        path.write_bytes(text)
        return path

    def findings(self, mode: str = "walk") -> list:
        found, count = repocheck.check_tree(self.root, mode)
        self.assertGreater(count, 0)
        return found

    def rules(self, mode: str = "walk") -> list[str]:
        return [str(f) for f in self.findings(mode)]


class CleanTree(TreeCase):
    def test_a_clean_tree_passes(self):
        self.put("datapiler/x.py", 'HOST = "127.0.0.1"\nVERSION = "0.1.0"\n')
        self.assertEqual(self.findings(), [])

    def test_main_answers_0_and_prints_no_value(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = repocheck.main([str(self.root), "--walk"])
        self.assertEqual(code, 0)
        self.assertIn("clean", out.getvalue())

    def test_the_real_repository_passes(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = repocheck.main([_repo.ROOT])
        self.assertEqual(code, 0, out.getvalue())


class RunTimeFolders(TreeCase):
    def test_top_level_run_time_folders_fail(self):
        for folder in ("workspace", "share", "logs", "jobs", "exports", ".venv", "Workspace", "update", ".venv.new",
                       ".venv.prev"):
            with self.subTest(folder=folder):
                path = self.put(folder + "/some.json", "{}")
                found = self.rules()
                self.assertTrue(any(f.startswith(folder + "/some.json: a file under the top-level") for f in found),
                                found)
                path.unlink()
                path.parent.rmdir()

    def test_the_same_names_deeper_pass(self):
        for folder in ("workspace", "share", "logs", "jobs"):
            self.put("tests/fixtures/%s/item.json" % folder, "{}")
            self.put("docs/%s/notes.md" % folder, "notes\n")
        self.assertEqual(self.findings(), [])

    def test_the_update_helpers_files_fail(self):
        """Build plan 0.2 §4.6: the helper writes <target>.dpnew beside a file while it swaps."""
        self.put("datapiler/api.py.dpnew", "x\n")
        self.assertIn("datapiler/api.py.dpnew: a file the update helper writes while it swaps (build plan 0.2 section "
                      "4.6)", self.rules())

    def test_a_short_name_fails(self):
        """The helper refuses an 8.3 short name's ~<digit> (the security review's SEC-5), so none may ship."""
        self.put("docs/NOTES~1.md", "x\n")
        self.assertIn("docs/NOTES~1.md: a name shaped like an 8.3 short name (~ and a digit), which the update "
                      "helper refuses", self.rules())
        from test_archive import helper
        self.assertEqual(repocheck.SHORT_NAME_RX.pattern, helper().SHORT_RX.pattern)

    def test_the_update_names_deeper_pass(self):
        self.put("tests/fixtures/update/pending.json", "{}")
        self.put("docs/manifest.sha256", "x\n")
        self.put("update-helper.py", "# the helper itself\n")
        self.assertEqual(self.findings(), [])

    def test_the_gitignore_keeps_the_update_files_out(self):
        with open(os.path.join(_repo.ROOT, ".gitignore"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        for want in ("/update/", "/manifest.sha256", "/.venv.new/", "/.venv.prev/", "*.dpnew"):
            self.assertIn(want, lines)

    def test_a_top_level_file_named_like_a_folder_passes(self):
        self.put("jobs", "not a folder\n")
        self.assertEqual(self.findings(), [])

    def test_local_state_at_the_top_fails(self):
        for name in ("settings.json", "datapiler.port", "datapiler.lock", "datapiler-start.log", "manifest.sha256"):
            with self.subTest(name=name):
                path = self.put(name, "{}" if name.endswith(".json") else "1")
                self.assertIn("%s: DataPiler's local state, written at run time" % name, self.rules())
                path.unlink()
        self.put("tests/fixtures/settings.json", "{}")
        self.assertEqual(self.findings(), [])


class GameFiles(TreeCase):
    def test_game_files_by_kind_fail(self):
        for name in ("data/NpcParam.csv", "regulation.bin", "x/Item.fmg", "x/Item.FMG.XML", "a/m99.dcx",
                     "oo2core_6_win64.dll", "saves/ER0000.sl2", "game-export/notes.txt"):
            with self.subTest(name=name):
                path = self.put(name, "invented\n")
                self.assertTrue(any(f.startswith(name + ": a game file") for f in self.rules()), name)
                path.unlink()


class ShareFiles(TreeCase):
    def share(self) -> str:
        return json.dumps({"format": "datapiler-share/1", "provenance": {"datapiler": "0.1.0"}, "tables": []})

    def test_a_share_file_fails_wherever_it_is(self):
        for rel in ("out.json", "tests/fixtures/share-example.json", "docs/example.JSON"):
            with self.subTest(rel=rel):
                path = self.put(rel, self.share())
                self.assertTrue(any(f.startswith(rel + ": a share file") for f in self.rules()), rel)
                path.unlink()

    def test_a_share_document_inside_another_fails(self):
        self.put("bundle.json", json.dumps({"items": [json.loads(self.share())]}))
        self.assertTrue(any(f.startswith("bundle.json: a share file") for f in self.rules()))

    def test_a_broken_json_naming_the_format_fails(self):
        self.put("broken.json", '{"format": "datapiler-share/1", ')
        self.assertTrue(any(f.startswith("broken.json: a .json that does not parse") for f in self.rules()))

    def test_the_same_string_elsewhere_passes(self):
        self.put("docs/format.md", 'A share file starts with `"format": "datapiler-share/1"`.\n')
        self.put("datapiler/guard.py", 'FORMAT = "datapiler-share/1"\n')
        self.put("schema/x.schema.json", json.dumps({"properties": {"format": {"const": "datapiler-job/1"}}}))
        self.put("broken.json", '{"format": "datapiler-job/1", ')
        self.assertEqual(self.findings(), [])


class Addresses(TreeCase):
    def test_addresses_other_than_127_0_0_1_fail(self):
        cases = {
            LAN_V4: "a private or local IPv4 address",
            TEN_V4: "a private or local IPv4 address",
            CGNAT_V4: "a private or local IPv4 address",
            LINK_LOCAL_V4: "a private or local IPv4 address",
            dotted(192, 168, 1, 0): "a private or local IPv4 address",
            PUBLIC_V4: "an IPv4 address other than 127.0.0.1",
            OTHER_LOOPBACK: "an IPv4 address other than 127.0.0.1",
            PUBLIC_V6: "an IPv6 address",
            ULA_V6: "an IPv6 address",
            FULL_LINK_LOCAL_V6: "an IPv6 link-local address with a full interface identifier",
        }
        for value, rule in cases.items():
            with self.subTest(rule=rule):
                path = self.put("notes/where.md", "first line\nthe server is at %s, port 8080\n" % value)
                self.assertEqual(self.rules(), ["notes/where.md:2: " + rule])
                path.unlink()

    def test_a_finding_never_shows_the_value(self):
        self.put("notes/where.md", "at %s and %s\n" % (LAN_V4, PUBLIC_V6))
        out = io.StringIO()
        with redirect_stdout(out):
            code = repocheck.main([str(self.root), "--walk"])
        self.assertEqual(code, 1)
        self.assertNotIn(LAN_V4, out.getvalue())
        self.assertNotIn(PUBLIC_V6, out.getvalue())
        self.assertIn("notes/where.md:1", out.getvalue())

    def test_in_a_binary_file_too(self):
        self.put("bin/blob.dat", b"\x00\x01" + LAN_V4.encode("ascii") + b"\xff\x00")
        self.assertEqual(self.rules(), ["bin/blob.dat:1: a private or local IPv4 address"])

    def test_what_names_no_machine_passes(self):
        text = "\n".join([
            "the page: http://127.0.0.1:8765/ and ::1",
            "documentation: %s %s %s %s" % (dotted(192, 0, 2, 10), dotted(198, 51, 100, 40),
                                            dotted(203, 0, 113, 7), "2001:db8:0:0:0:0:2:1"),
            "versions: game %s, file %s, Smithbox %s, regulation %s" % (dotted(1, 16, 0, 0), dotted(0, 1, 0, 0),
                                                                        dotted(2, 2, 6, 0), dotted(2, 6, 1, 0)),
            "a five-part number %s.9 and a mask %s" % (dotted(1, 2, 3, 4), dotted(255, 255, 255, 0)),
            "times 08:41:58 and 08:42:01, a slice a[1::2], std::wstring::npos, link-local fe80::1 fe80::1c2b:3a",
            "not addresses: 300.1.2.3 1.2.3",
        ])
        self.put("notes/fine.md", text + "\n")
        self.assertEqual(self.findings(), [])


B = "\\"
AT = "@"


class PeopleAndMail(TreeCase):
    """The sweep's rules that need no list of anyone's names (S14 and its note): a user's folder, an e-mail address.
    The planted values are put together at run time, so this file holds none for a sweep or this check to find."""

    USER_DIRS = ("C:" + B + "Users" + B + "zorblax7" + B + "Documents",
                 "C:" + B + B + "Users" + B + B + "zorblax7" + B + B + "x",           # as source code doubles them
                 "D:/Users" + "/zorblax7/x", "c:" + B + "documents and settings" + B + "zorblax7",
                 "/home" + "/zorblax7/project", "/Users" + "/zorblax7/Library")
    MAILS = ("zorblax7" + AT + "mailhost.net", "first.last+tag" + AT + "sub.mailhost.co.uk")

    def test_a_users_folder_fails(self):
        for value in self.USER_DIRS:
            with self.subTest(value=value):
                path = self.put("notes/where.md", "first line\nthe log is in %s now\n" % value)
                self.assertEqual(self.rules(), ["notes/where.md:2: a user's folder, which names a person or a "
                                                "machine's account"])
                path.unlink()

    def test_an_email_address_fails(self):
        for value in self.MAILS:
            with self.subTest(value=value):
                path = self.put("docs/who.md", "write to %s\n" % value)
                self.assertEqual(self.rules(), ["docs/who.md:1: an e-mail address other than a noreply or an "
                                                "example one"])
                path.unlink()

    def test_what_names_no_one_passes(self):
        text = "\n".join([
            "C:" + B + "Users" + B + "<name>" + B + "Downloads" + B + "DataPiler",
            "C:" + B + "Users" + B + "%USERNAME%" + B + "x and C:" + B + "Users" + B + "$env:USERNAME" + B + "x",
            "C:" + B + "Users" + B + "player" + B + "x, C:" + B + "Users" + B + "Public" + B + "x, "
            "C:" + B + "Users" + B + "runneradmin" + B + "x, C:" + B + "Users" + B + "..." + B + "x",
            "/home" + "/user/datapiler, /home" + "/runner/work, /Users" + "/someone/x, /home" + "/<name>/x",
            "noreply" + AT + "anthropic.com, 1234+someone" + AT + "users.noreply.github.com, "
            "noreply" + AT + "github.com, someone" + AT + "example.com, a" + AT + "b.invalid, git" + AT + "github.com",
            "packages: left-pad" + AT + "1.3.0 is not mail, nor icon" + AT + "2x.png",
            "a decorator " + AT + "property and a scope std::wstring",
        ])
        self.put("notes/fine.md", text + "\n")
        self.assertEqual(self.findings(), [])

    def test_a_finding_never_shows_the_value(self):
        self.put("notes/where.md", "%s and %s\n" % (self.USER_DIRS[0], self.MAILS[0]))
        out = io.StringIO()
        with redirect_stdout(out):
            code = repocheck.main([str(self.root), "--walk"])
        self.assertEqual(code, 1)
        self.assertNotIn("zorblax7", out.getvalue())
        self.assertNotIn("mailhost", out.getvalue())
        self.assertEqual(out.getvalue().count("notes/where.md:1"), 2)


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class GitMode(TreeCase):
    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.root)] + list(args), check=True, capture_output=True, timeout=60)

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.put(".gitignore", "/workspace/\n/jobs/\n")

    def test_ignored_run_time_folders_are_not_checked(self):
        self.put("workspace/textdb.json", "{}")
        self.put("jobs/count-rows/job.json", "{}")
        self.assertEqual(self.findings("git"), [])

    def test_a_forced_add_fails(self):
        self.put("workspace/textdb.json", "{}")
        self.git("add", "-f", "workspace/textdb.json")
        self.assertTrue(any(f.startswith("workspace/textdb.json: a file under the top-level")
                            for f in self.rules("git")))

    def test_an_untracked_file_git_would_add_is_checked(self):
        self.put("notes.md", "at %s\n" % LAN_V4)
        self.assertEqual(self.rules("git"), ["notes.md:1: a private or local IPv4 address"])

    def test_git_mode_refuses_a_folder_that_is_not_a_work_tree_top(self):
        sub = self.root / "tests"
        with self.assertRaises(OSError):
            repocheck.check_tree(sub, "git")


if __name__ == "__main__":
    unittest.main()
