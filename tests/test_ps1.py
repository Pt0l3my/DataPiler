"""DataPiler.ps1, the window's script (build plan §4.12, §8.4): ASCII only, the pip flags, the question before any
download, no other network and no change to the PC, the version read from datapiler/__init__.py, the lock's header
read as LINK writes it, the venv marker as CORE reads it, and the branches for the exit codes. Where PowerShell is
installed (Windows in CI), the script is also parsed by PowerShell itself."""

import _repo  # noqa: F401

import os
import re
import shutil
import subprocess
import tempfile
import unittest

from datapiler import VERSION

PS1 = os.path.join(_repo.ROOT, "DataPiler.ps1")
INIT = os.path.join(_repo.ROOT, "datapiler", "__init__.py")
LOCK = os.path.join(_repo.ROOT, "requirements.lock")
PATHS = os.path.join(_repo.ROOT, "datapiler", "paths.py")
ENV = os.path.join(_repo.ROOT, "datapiler", "env.py")

PIP_FLAGS = ("--isolated", "--disable-pip-version-check", "--no-input", "--require-hashes", "--only-binary=:all:",
             "--no-deps")

# The patterns DataPiler.ps1 reads with, which must stay as they are written there (checked below).
VERSION_RX = r'^VERSION\s*=\s*"(\d+\.\d+\.\d+)"'
PYTHONS_RX = r"^# pythons:\s*(.+)$"
MB_RX = r"^# download-mb:\s*(\d+)\s*$"
PACKAGE_RX = r"^# ([A-Za-z0-9][A-Za-z0-9._-]*) (\d[A-Za-z0-9.+!-]*) ([A-Za-z0-9.+-]+)\s*$"


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def code_lines(text: str) -> list[str]:
    """The script's lines without its comments (a whole-line `#` comment, or one after code)."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(re.sub(r"\s#\s.*$", "", line))
    return out


class Script(unittest.TestCase):
    def setUp(self):
        self.raw = read_bytes(PS1)
        self.text = self.raw.decode("ascii")
        self.code = "\n".join(code_lines(self.text))

    def test_ascii_only(self):
        bad = [i for i, b in enumerate(self.raw) if b > 127]
        self.assertEqual(bad, [], "non-ASCII bytes")
        self.assertFalse(self.raw.startswith(b"\xef\xbb\xbf"))

    def test_the_pip_line(self):
        pips = [l for l in self.code.splitlines() if "-m pip" in l]
        self.assertEqual(len(pips), 1, pips)
        pip = pips[0]
        self.assertIn("$VenvPython -m pip install", pip)
        for flag in PIP_FLAGS:
            self.assertIn(" " + flag, pip, flag)
        self.assertTrue(pip.rstrip().endswith("-r $Lock"), pip)
        self.assertIn("$Lock = Join-Path $Root 'requirements.lock'", self.code)

    def test_the_question_comes_before_venv_and_pip(self):
        ask = self.code.find("if (Read-YesNo 'Set them up now? [Y/N]')")
        venv = self.code.find("-m venv")
        pip = self.code.find("-m pip")
        self.assertGreater(ask, 0)
        self.assertEqual(self.code.count("-m venv"), 1)
        self.assertGreater(venv, ask)
        self.assertGreater(pip, venv)
        # Both sit inside the Y branch: no closing brace at the branch's own depth between the question and them.
        branch = self.code[ask:pip]
        depth = 0
        for ch in branch[branch.index("{"):]:
            depth += {"{": 1, "}": -1}.get(ch, 0)
            self.assertGreater(depth, 0, "pip is outside the Y branch")

    def test_what_the_question_says(self):
        for words in ("pypi.org over https", "{0} MB", "$p.Name, $p.Version, $p.Licence", "requirements.lock",
                      "Y: download", "N: start without the server link"):
            self.assertIn(words, self.code, words)

    def test_no_other_network_and_no_change_to_the_pc(self):
        low = self.code.lower()
        for word in ("set-executionpolicy", "invoke-webrequest", "invoke-restmethod", "start-bitstransfer", "curl",
                     "wget", "iwr ", "irm ", "net.webclient", "webclient", "downloadstring", "downloadfile",
                     "httpclient", "bitsadmin", "certutil", "-verb runas", "set-itemproperty", "new-itemproperty",
                     "setx", "[environment]::setenvironmentvariable", "hkcu:", "hklm:", "install-module",
                     "--index-url", "--extra-index-url", "--trusted-host"):
            self.assertNotIn(word, low, word)
        # The only URL is the running page's, on 127.0.0.1.
        urls = re.findall(r"https?://[^\s'\"]+", self.code)
        self.assertEqual(urls, ["http://127.0.0.1:{0}/"])

    def test_the_version_is_read_from_init(self):
        self.assertIn("$Init = Join-Path $Root 'datapiler\\__init__.py'", self.code)
        self.assertIn("'" + VERSION_RX + "'", self.code)
        with open(INIT, encoding="utf-8") as f:
            found = [m.group(1) for m in (re.match(VERSION_RX, l) for l in f.read().splitlines()) if m]
        self.assertEqual(found, [VERSION])
        self.assertIn("(\"DataPiler {0} - ", self.code)

    def test_the_lock_header_is_read_as_it_is_written(self):
        for rx in (PYTHONS_RX, MB_RX, PACKAGE_RX):
            self.assertIn("'" + rx + "'", self.code, rx)
        self.assertIn("'# datapiler-lock/1'", self.code)
        with open(LOCK, encoding="ascii") as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[0], "# datapiler-lock/1")
        header = []
        for line in lines:
            if not line.startswith("#"):
                break
            header.append(line)
        pythons = [m.group(1).split() for m in (re.match(PYTHONS_RX, l) for l in header) if m]
        self.assertEqual(len(pythons), 1)
        self.assertIn("3.10", pythons[0])
        self.assertEqual(len([l for l in header if re.match(MB_RX, l)]), 1)
        named = {m.group(1).lower().replace("_", "-"): m.group(2)
                 for m in (re.match(PACKAGE_RX, l) for l in header) if m}
        pinned = {m.group(1).lower().replace("_", "-"): m.group(2)
                  for m in re.finditer(r"(?m)^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", "\n".join(lines))}
        self.assertEqual(named, pinned)
        self.assertIn("grpcio", named)
        self.assertIn("protobuf", named)

    def test_the_venv_marker_is_the_one_env_reads(self):
        self.assertIn("$Marker = Join-Path $Venv 'datapiler-lock.sha256'", self.code)
        self.assertIn("$Venv = Join-Path $Root '.venv'", self.code)
        self.assertIn("Get-FileHash -Algorithm SHA256 -LiteralPath $Lock", self.code)
        self.assertIn(".Hash.ToLowerInvariant()", self.code)
        self.assertIn("[System.IO.File]::WriteAllText($Marker, $LockInfo.Hash + \"`n\", [System.Text.Encoding]::ASCII)",
                      self.code)
        with open(PATHS, encoding="utf-8") as f:
            paths = f.read()
        self.assertIn('"datapiler-lock.sha256"', paths)
        self.assertIn('".venv"', paths)
        # The marker is written only after pip succeeded.
        self.assertGreater(self.code.find("WriteAllText($Marker"), self.code.find("-m pip"))

    def test_python_is_found_as_the_plan_says(self):
        self.assertLess(self.code.find("Exe = 'py'; Pre = @('-3')"), self.code.find("Exe = 'python'; Pre = @()"))
        self.assertIn("$MinPython = [version]'3.10'", self.code)
        self.assertIn("$LockInfo.Pythons -notcontains $PyName", self.code)

    def test_the_apps_arguments(self):
        self.assertIn("$Arguments += '--console'", self.code)
        self.assertIn("if ($FromLauncher) { $Arguments += '--no-browser' }", self.code)
        self.assertIn("if ($NoLink) { $Arguments += '--no-link' }", self.code)
        self.assertIn("param([switch]$FromLauncher)", self.code)
        self.assertIn("$App = Join-Path $Root 'datapiler.py'", self.code)
        # N and a failed install both run without the link.
        self.assertGreaterEqual(self.code.count("$NoLink = $true"), 3)

    def test_the_exit_code_branches(self):
        for line in ("if ($Code -eq 0) {", "} elseif ($Code -eq 3) {", "} else {"):
            self.assertIn(line, self.code)
        self.assertIn("'DataPiler has stopped - this window closes in 5 s'", self.code)
        self.assertIn("'DataPiler is running already - its page opens'", self.code)
        self.assertIn("('DataPiler stopped with code {0}' -f $Code)", self.code)
        self.assertIn("'Press Enter to close.'", self.code)
        self.assertEqual(self.code.count("[System.Threading.Thread]::Sleep(5000)"), 3)
        self.assertTrue(self.code.rstrip().endswith("exit $Code"))

    def test_one_window_at_a_time(self):
        """Found by the correctness review: the app's mutex is taken only once datapiler.py runs, so a second start
        during the question, .venv or pip opened a second window, and two windows could rebuild .venv at once. The
        script holds a mutex of its own from its top until its app has stopped (the launcher checks it too)."""
        take = self.code.index("New-Object System.Threading.Mutex($false, 'Local\\DataPiler-window')")
        self.assertLess(take, self.code.index("$Python = Find-Python"))
        self.assertIn("$Owned = $WindowMutex.WaitOne(0)", self.code)
        self.assertIn("catch [System.Threading.AbandonedMutexException]", self.code)
        self.assertIn("[System.Threading.Mutex]::TryOpenExisting('Local\\DataPiler', [ref]$AppMutex)", self.code)
        self.assertIn("'DataPiler is starting in another window - answer there. This window closes in 5 s.'",
                      self.code)
        # Let go as soon as the app has stopped, and before any window waits for Enter.
        finally_part = self.code[self.code.index("} finally {"):]
        self.assertLess(finally_part.index("Release-Window"), finally_part.index("if ($Code -eq 0) {"))
        close = self.code[self.code.index("function Close-Window"):]
        self.assertLess(close.index("Release-Window"), close.index("ReadLine()"))

    def test_the_window_is_titled(self):
        self.assertIn("$Host.UI.RawUI.WindowTitle = 'DataPiler'", self.code)


def powershells() -> list[str]:
    """Windows PowerShell 5.1 and PowerShell 7, whichever are installed."""
    return [found for found in (shutil.which(name) for name in ("powershell", "pwsh")) if found]


@unittest.skipUnless(powershells(), "PowerShell is not installed")
class Parse(unittest.TestCase):
    """Each installed PowerShell's own parser finds no error in the script (it is parsed, never run)."""

    def test_it_parses(self):
        checker = (
            "param([string]$Path)\n"
            "$tokens = $null; $errors = $null\n"
            "[void][System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)\n"
            "foreach ($e in $errors) { [Console]::WriteLine($e.Extent.StartLineNumber.ToString() + ': ' + $e.Message) }\n"
            "exit $errors.Count\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "parse.ps1")
            with open(script, "w", encoding="ascii") as f:
                f.write(checker)
            for shell in powershells():
                with self.subTest(shell=os.path.basename(shell)):
                    done = subprocess.run([shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                                           "Bypass", "-File", script, PS1], capture_output=True, timeout=120)
                    self.assertEqual(done.returncode, 0, done.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
