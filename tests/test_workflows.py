"""The GitHub workflows (build plan §8.4; settled S4, S14): every action pinned by a commit, the release workflow only
on tags, making a draft, with `contents: write` in its release job only, and the checks running the test command on
Linux and Windows, Windows with the lock's libraries installed as DataPiler.ps1 installs them. The workflows are read
with a small parser for the plain subset of YAML they are written in (the tests use the standard library only)."""

import _repo  # noqa: F401

import os
import re
import unittest

WORKFLOWS = os.path.join(_repo.ROOT, ".github", "workflows")
CHECKS = os.path.join(WORKFLOWS, "checks.yml")
RELEASE = os.path.join(WORKFLOWS, "release.yml")
PS1 = os.path.join(_repo.ROOT, "DataPiler.ps1")

TEST_COMMAND = "-I -m unittest discover -s tests"
PIP_FLAGS = ("--isolated", "--disable-pip-version-check", "--no-input", "--require-hashes", "--only-binary=:all:",
             "--no-deps")
USES_RX = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")


# ------------------------------------------------------------------------------------------------ a small YAML reader

class MiniYaml:
    """Block mappings and sequences, `|` and `>` block scalars, quoted and plain scalars, `[a, b]` and `{}`, and
    comments. Scalars stay strings. Anything else raises ValueError, so a workflow outside the subset fails loudly."""

    def __init__(self, text: str):
        self.lines = text.splitlines()
        self.i = 0

    @staticmethod
    def indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def skip(self) -> None:
        while self.i < len(self.lines):
            s = self.lines[self.i].strip()
            if s and not s.startswith("#"):
                return
            self.i += 1

    def parse(self):
        self.skip()
        if self.i >= len(self.lines):
            return None
        out = self.node(self.indent(self.lines[self.i]))
        self.skip()
        if self.i < len(self.lines):
            raise ValueError("line %d: unexpected" % (self.i + 1))
        return out

    def node(self, ind: int):
        line = self.lines[self.i]
        if line.strip() == "-" or line.strip().startswith("- "):
            return self.seq(ind)
        return self.mapping(ind)

    def mapping(self, ind: int) -> dict:
        out = {}
        while True:
            self.skip()
            if self.i >= len(self.lines):
                return out
            line = self.lines[self.i]
            cur = self.indent(line)
            if cur < ind or line.strip().startswith("- "):
                return out
            if cur > ind:
                raise ValueError("line %d: bad indentation" % (self.i + 1))
            m = re.match(r"""^(?:"([^"]*)"|'([^']*)'|([^\s:#'"][^:#]*?))\s*:(?:\s+(.*))?$""", line.strip())
            if not m:
                raise ValueError("line %d: not a mapping entry" % (self.i + 1))
            key = next(g for g in m.groups()[:3] if g is not None)
            if key in out:
                raise ValueError("line %d: key %s twice" % (self.i + 1, key))
            self.i += 1
            out[key] = self.value(m.group(4) or "", ind)

    def value(self, rest: str, ind: int):
        rest = self.uncomment(rest).strip()
        if rest in ("|", "|-", ">", ">-"):
            return self.block(ind, folded=rest.startswith(">"))
        if rest:
            return self.scalar(rest)
        self.skip()
        if self.i >= len(self.lines):
            return None
        line = self.lines[self.i]
        cur = self.indent(line)
        if line.strip().startswith("- ") and cur >= ind:
            return self.seq(cur)
        if cur > ind:
            return self.node(cur)
        return None

    def seq(self, ind: int) -> list:
        out = []
        while True:
            self.skip()
            if self.i >= len(self.lines):
                return out
            line = self.lines[self.i]
            if self.indent(line) != ind or not (line.strip() == "-" or line.strip().startswith("- ")):
                if self.indent(line) > ind:
                    raise ValueError("line %d: bad indentation" % (self.i + 1))
                return out
            content = line.strip()[1:].lstrip()
            col = ind + len(line.strip()) - len(content)
            if not content:
                self.i += 1
                self.skip()
                out.append(self.node(self.indent(self.lines[self.i])))
            elif re.match(r"""^(?:"[^"]*"|'[^']*'|[^\s:#'"\[{][^:#]*?)\s*:(\s|$)""", content):
                self.lines[self.i] = " " * col + content
                out.append(self.mapping(col))
            else:
                self.i += 1
                out.append(self.scalar(self.uncomment(content).strip()))

    def block(self, ind: int, folded: bool) -> str:
        buf, col = [], None
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                buf.append("")
                self.i += 1
                continue
            if self.indent(line) <= ind:
                break
            if col is None:
                col = self.indent(line)
            buf.append(line[col:])
            self.i += 1
        while buf and not buf[-1]:
            buf.pop()
        return (" " if folded else "\n").join(buf) + "\n"

    @staticmethod
    def uncomment(s: str) -> str:
        quote = None
        for k, ch in enumerate(s):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"" and (k == 0 or s[k - 1] in " [,{:"):
                quote = ch
            elif ch == "#" and (k == 0 or s[k - 1] in " \t"):
                return s[:k]
        return s

    def scalar(self, s: str):
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
            return s[1:-1]
        if s == "{}":
            return {}
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            return [self.scalar(x.strip()) for x in inner.split(",")] if inner else []
        if s.startswith(("{", "[", "&", "*", "!", "%", "@", "`")):
            raise ValueError("line %d: outside the subset: %s" % (self.i, s[:1]))
        return s


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return MiniYaml(f.read()).parse()


def steps(job: dict) -> list[dict]:
    return job.get("steps") or []


def runs(job: dict) -> str:
    return "\n".join(s.get("run", "") for s in steps(job))


def write_permissions(perms) -> list[str]:
    if perms in (None, {}):
        return []
    if isinstance(perms, str):
        return [perms] if perms == "write-all" else []
    return [k for k, v in perms.items() if v == "write"]


class Parser(unittest.TestCase):
    def test_the_subset(self):
        doc = MiniYaml("a: 1  # note\nb:\n  - x\n  - k: v\n    m: |\n      one\n      two\nc: [p, q]\nd: {}\n"
                       "'on':\n  push:\n").parse()
        self.assertEqual(doc, {"a": "1", "b": ["x", {"k": "v", "m": "one\ntwo\n"}], "c": ["p", "q"], "d": {},
                               "on": {"push": None}})

    def test_outside_the_subset_raises(self):
        for text in ("a: &anchor x\n", "a: {b: c}\n", "a:\n   b: 1\n  c: 2\n"):
            with self.assertRaises(ValueError, msg=text):
                MiniYaml(text).parse()


class Both(unittest.TestCase):
    def test_only_these_two(self):
        self.assertEqual(sorted(os.listdir(WORKFLOWS)), ["checks.yml", "release.yml"])

    def test_every_action_pinned_by_a_commit(self):
        for path in (CHECKS, RELEASE):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            raw = re.findall(r"(?m)^\s*(?:-\s+)?uses:\s*(\S+)", text)
            self.assertTrue(raw, path)
            parsed = [s["uses"] for job in load(path)["jobs"].values() for s in steps(job) if "uses" in s]
            self.assertEqual(sorted(raw), sorted(parsed), path)
            for uses in parsed:
                self.assertRegex(uses, USES_RX)

    def test_the_same_action_at_the_same_commit(self):
        seen = {}
        for path in (CHECKS, RELEASE):
            for job in load(path)["jobs"].values():
                for s in steps(job):
                    if "uses" in s:
                        name, sha = s["uses"].split("@")
                        self.assertEqual(seen.setdefault(name, sha), sha, name)

    def test_no_risky_triggers_or_secrets(self):
        for path in (CHECKS, RELEASE):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("pull_request_target", text)
            self.assertNotIn("workflow_run", text)
            self.assertNotIn("secrets.", text)
            for s in (s for job in load(path)["jobs"].values() for s in steps(job) if "uses" in s):
                if s["uses"].startswith("actions/checkout@"):
                    self.assertEqual((s.get("with") or {}).get("persist-credentials"), "false", path)


class Release(unittest.TestCase):
    def setUp(self):
        self.wf = load(RELEASE)

    def test_only_on_tags(self):
        self.assertEqual(list(self.wf["on"]), ["push"])
        self.assertEqual(list(self.wf["on"]["push"]), ["tags"])
        self.assertEqual(self.wf["on"]["push"]["tags"], ["v*"])

    def test_a_draft_only(self):
        text = "\n".join(runs(job) for job in self.wf["jobs"].values())
        creates = [l for l in text.splitlines() if "gh release" in l]
        self.assertEqual(len(creates), 1, creates)
        self.assertIn("gh release create", creates[0])
        self.assertIn(" --draft", creates[0])
        self.assertNotIn("--draft=false", creates[0])
        self.assertNotIn("gh release edit", text)
        self.assertNotIn("--latest", text)

    def test_contents_write_in_the_release_job_only(self):
        self.assertEqual(write_permissions(self.wf.get("permissions")), [])
        self.assertIn("permissions", self.wf)
        writers = {name: write_permissions(job.get("permissions")) for name, job in self.wf["jobs"].items()}
        self.assertEqual({n: w for n, w in writers.items() if w}, {"release": ["contents"]})
        for name, job in self.wf["jobs"].items():
            self.assertIn("permissions", job, name)
        self.assertIn("gh release create", runs(self.wf["jobs"]["release"]))
        self.assertNotIn("gh release", runs(self.wf["jobs"]["build"]))

    def test_built_on_windows_with_msys2_and_checked(self):
        build = self.wf["jobs"]["build"]
        self.assertEqual(build["runs-on"], "windows-latest")
        msys = [s for s in steps(build) if s.get("uses", "").startswith("msys2/setup-msys2@")]
        self.assertEqual(len(msys), 1)
        self.assertIn("mingw-w64-x86_64-gcc", msys[0]["with"]["install"])
        text = runs(build)
        self.assertIn('test "v$version" = "$GITHUB_REF_NAME"', text)
        self.assertIn("sha256sum DataPiler.exe", text)
        check = runs(self.wf["jobs"]["release"])
        self.assertIn("sha256sum -c DataPiler.exe.sha256", check)
        # file 5.45's wording and 5.46's ("PE32+ executable for MS Windows 6.00 (GUI), x86-64") both match
        self.assertIn("file -b DataPiler.exe | grep -Eq '^PE32\\+ executable .*\\(GUI\\).*x86-64'", check)
        rx = re.compile(r"^PE32\+ executable .*\(GUI\).*x86-64")
        for said in ("PE32+ executable (GUI) x86-64 (stripped to external PDB), for MS Windows, 10 sections",
                     "PE32+ executable for MS Windows 6.00 (GUI), x86-64, 10 sections"):
            self.assertRegex(said, rx)
        for said in ("PE32+ executable (console) x86-64, for MS Windows", "PE32 executable (GUI) Intel 80386",
                     "PE32+ executable for MS Windows 6.00 (DLL), x86-64"):
            self.assertNotRegex(said, rx)
        self.assertEqual(self.wf["jobs"]["release"]["needs"], "build")

    def test_the_version_is_read_whatever_the_line_ends(self):
        """A CRLF checkout on the Windows runner kept sed's `$` from matching, so the tag check always failed."""
        text = runs(self.wf["jobs"]["build"])
        line = next(l for l in text.splitlines() if "datapiler/__init__.py" in l and "sed" in l)
        self.assertIn("tr -d '\\r' < datapiler/__init__.py", line)
        self.assertIn('if [ -z "$version" ]', text)

    def test_the_toolchains_notices_go_with_the_exe(self):
        """The exe is linked -static with MinGW-w64: its CRT's and winpthreads' notices go with it (NOTICE §4)."""
        build = runs(self.wf["jobs"]["build"])
        self.assertIn("/mingw64/share/licenses", build)
        for part in ("*crt*", "*winpthread*", "build/THIRD-PARTY-NOTICES.txt"):
            self.assertIn(part, build)
        upload = next(s for s in steps(self.wf["jobs"]["build"]) if s.get("uses", "").startswith(
            "actions/upload-artifact@"))
        self.assertIn("build/THIRD-PARTY-NOTICES.txt", upload["with"]["path"])
        create = next(l for l in runs(self.wf["jobs"]["release"]).splitlines() if "gh release create" in l)
        self.assertIn("DataPiler.exe DataPiler.exe.sha256 THIRD-PARTY-NOTICES.txt", create)
        with open(os.path.join(_repo.ROOT, "NOTICE"), encoding="utf-8") as f:
            notice = f.read()
        self.assertIn("THIRD-PARTY-NOTICES.txt", notice)

    def test_one_zip_of_the_whole_app(self):
        """S24: the tagged source as git archive makes it, with the built exe and its notices placed in it, and its
        sha256, attached to the same draft release, so the owner downloads one file."""
        rel = self.wf["jobs"]["release"]
        checkout = [s for s in steps(rel) if s.get("uses", "").startswith("actions/checkout@")]
        self.assertEqual(len(checkout), 1)
        self.assertEqual(checkout[0]["with"].get("persist-credentials"), "false")
        text = runs(rel)
        self.assertIn('git -C src archive --format=zip --prefix="$app/" -o "../$app.zip" HEAD', text)
        self.assertIn('app="DataPiler-${TAG#v}"', text)
        self.assertIn('zip -X -q "../$app.zip" "$app/DataPiler.exe" "$app/THIRD-PARTY-NOTICES.txt"', text)
        self.assertIn('sha256sum "$app.zip" | tee "$app.zip.sha256"', text)
        # the exe inside the zip is the exe that was checked against its own sha256
        self.assertIn('unzip -p "$app.zip" "$app/DataPiler.exe" | sha256sum', text)
        # the zip is made only from the commit the tag names
        self.assertIn('rev-parse "$TAG^{commit}"', text)
        create = next(l for l in text.splitlines() if "gh release create" in l)
        self.assertIn('THIRD-PARTY-NOTICES.txt "$app.zip" "$app.zip.sha256" --draft', create)
        order = [s.get("name", "") for s in steps(rel)]
        self.assertLess(order.index("One zip of the whole app, the tagged source with the exe placed in it"),
                        next(k for k, n in enumerate(order) if n.startswith("A draft release")))

    def test_github_values_reach_the_shell_through_the_environment(self):
        for job in self.wf["jobs"].values():
            for s in steps(job):
                self.assertNotRegex(s.get("run", ""), r"\$\{\{\s*github\.", s.get("name"))


class Checks(unittest.TestCase):
    def setUp(self):
        self.wf = load(CHECKS)
        self.jobs = self.wf["jobs"]

    def test_on_push_and_pull_request_read_only(self):
        self.assertEqual(sorted(self.wf["on"]), ["pull_request", "push"])
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        for name, job in self.jobs.items():
            self.assertEqual(write_permissions(job.get("permissions")), [], name)

    def test_the_test_command_on_linux_and_windows(self):
        oses = {}
        for name, job in self.jobs.items():
            for s in steps(job):
                run = s.get("run", "")
                if TEST_COMMAND in run and "-p " not in run:
                    oses.setdefault(job["runs-on"], []).append(name)
        self.assertIn("ubuntu-latest", oses)
        self.assertIn("windows-latest", oses)

    def test_python_310_is_among_those_tested(self):
        for name in ("tests-linux", "tests-windows"):
            self.assertIn("3.10", self.jobs[name]["strategy"]["matrix"]["python"], name)

    def test_windows_installs_from_the_lock_as_the_script_does(self):
        win = self.jobs["tests-windows"]
        self.assertEqual(win["runs-on"], "windows-latest")
        lines = [l for l in runs(win).splitlines() if "pip install" in l]
        self.assertEqual(len(lines), 1, lines)
        pip = lines[0]
        for flag in PIP_FLAGS:
            self.assertIn(" " + flag, pip, flag)
        self.assertIn("-r requirements.lock", pip)
        with open(PS1, encoding="ascii") as f:
            script = next(l for l in f.read().splitlines() if "-m pip install" in l)
        flags = lambda line: [w for w in line.split() if w.startswith("--")]  # noqa: E731
        self.assertEqual(flags(pip), flags(script))
        # The tests then run with that venv's Python, after the install.
        order = [s.get("run", "") for s in steps(win)]
        install = next(k for k, r in enumerate(order) if "pip install" in r)
        linked = [k for k, r in enumerate(order) if TEST_COMMAND in r and "venv" in r]
        self.assertTrue(linked and linked[0] > install)

    def test_the_repository_check_runs(self):
        self.assertTrue(any("tools/repocheck.py" in runs(job) for job in self.jobs.values()))

    def test_the_launcher_is_built(self):
        job = self.jobs["launcher"]
        self.assertIn("mingw-w64", runs(job))
        test = [s for s in steps(job) if "test_launcher_src.py" in s.get("run", "")]
        self.assertEqual(len(test), 1)
        self.assertEqual((test[0].get("env") or {}).get("DATAPILER_NEED_MINGW"), "1")


if __name__ == "__main__":
    unittest.main()
