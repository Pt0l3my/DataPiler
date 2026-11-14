"""DataPiler.ps1, the window's script (build plan §4.12, §8.4): ASCII only, the pip flags, the question before any
download, no other network and no change to the PC, the version read from datapiler/__init__.py, the lock's header
read as LINK writes it, the venv marker as CORE reads it, and the branches for the exit codes; and from 0.2.0 the
update's path (build plan 0.2 §4.9): exit code 75 and the helper with the base Python, -AfterUpdate, every Y built as
.venv.new and swapped in, and the R prompt. Where PowerShell is installed (Windows in CI), the script is also parsed
by PowerShell itself."""

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
        self.assertIn("$NewPython -m pip install", pip)
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
        self.assertIn("[System.IO.File]::WriteAllText($NewMarker, $LockInfo.Hash + \"`n\", [System.Text.Encoding]::ASCII)",
                      self.code)
        self.assertIn("$NewMarker = Join-Path $VenvNew 'datapiler-lock.sha256'", self.code)
        with open(PATHS, encoding="utf-8") as f:
            paths = f.read()
        self.assertIn('"datapiler-lock.sha256"', paths)
        self.assertIn('".venv"', paths)
        # The marker is written only after pip succeeded.
        self.assertGreater(self.code.find("WriteAllText($NewMarker"), self.code.find("-m pip"))

    def test_python_is_found_as_the_plan_says(self):
        self.assertLess(self.code.find("Exe = 'py'; Pre = @('-3')"), self.code.find("Exe = 'python'; Pre = @()"))
        self.assertIn("$MinPython = [version]'3.10'", self.code)
        self.assertIn("$LockInfo.Pythons -notcontains $PyName", self.code)

    def test_the_apps_arguments(self):
        self.assertIn("$Arguments += '--console'", self.code)
        self.assertIn("if ($FromLauncher) { $Arguments += '--no-browser' }", self.code)
        self.assertIn("if ($NoLink) { $Arguments += '--no-link' }", self.code)
        self.assertIn("param([switch]$FromLauncher, [switch]$AfterUpdate)", self.code)
        self.assertIn("$App = Join-Path $Root 'datapiler.py'", self.code)
        # N and a failed install both run without the link.
        self.assertGreaterEqual(self.code.count("$NoLink = $true"), 3)

    def test_the_exit_code_branches(self):
        for line in ("if ($Code -eq 0) {", "} elseif ($Code -eq 3) {", "} else {"):
            self.assertIn(line, self.code)
        self.assertIn("'DataPiler has stopped' Green", self.code)            # S50: closes at once
        self.assertNotIn("this window closes in 5 s'", self.code)
        self.assertIn("'DataPiler is running already - its page opens'", self.code)
        self.assertIn("('DataPiler stopped with code {0}' -f $Code)", self.code)
        self.assertIn("'Press Enter to close.'", self.code)
        self.assertEqual(self.code.count("[System.Threading.Thread]::Sleep(5000)"), 2)   # S50: no wait after a normal stop
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


class UpdatePath(unittest.TestCase):
    """Build plan 0.2 §4.9 and design 0002 §2.5."""

    def setUp(self):
        self.text = read_bytes(PS1).decode("ascii")
        self.code = "\n".join(code_lines(self.text))

    def test_after_update_is_a_switch(self):
        self.assertIn("param([switch]$FromLauncher, [switch]$AfterUpdate)", self.code)
        # after an update the window keeps the helper's lines in view
        self.assertIn("if (-not $AfterUpdate) { Clear-Host }", self.code)

    def test_exit_75_runs_the_helper_with_the_base_python(self):
        self.assertIn("$EXIT_UPDATE = 75", self.code)
        self.assertIn("if ($Code -ne $EXIT_UPDATE) { break }", self.code)
        self.assertIn("$Pending = Join-Path $UpdateDir 'pending.json'", self.code)
        self.assertIn("$UpdateDir = Join-Path $Root 'update'", self.code)
        self.assertIn("$HelperPath = Join-Path $UpdateDir ('{0}\\update-helper.py' -f $Upd.To)", self.code)
        lines = [l.strip() for l in self.code.splitlines() if "--pending" in l]
        self.assertEqual(lines, ["& $Python.Exe @Pre $HelperPath --pending $Pending"])
        for line in (l for l in self.code.splitlines() if "update-helper.py" in l or "$HelperPath --" in l):
            self.assertNotIn("$VenvPython", line)
            self.assertNotIn("$RunExe", line)
        self.assertIn("'DataPiler stopped to update to {0}.' -f $Upd.To", self.code)

    def test_pending_is_read_by_its_patterns(self):
        self.assertIn("ConvertFrom-Json", self.code)
        self.assertIn("$to -match '^\\d+\\.\\d+\\.\\d+$' -and $from -match '^\\d+\\.\\d+\\.\\d+$'", self.code)

    def test_helper_0_starts_the_new_script_in_this_window(self):
        loop = self.code[self.code.index("if ($Code -ne $EXIT_UPDATE) { break }"):self.code.index("} finally {")]
        start = loop.index("if ($Helped -eq 0) {")
        self.assertIn('& "$PSScriptRoot\\DataPiler.ps1" -AfterUpdate', loop[start:])
        self.assertLess(loop.index('& "$PSScriptRoot\\DataPiler.ps1" -AfterUpdate'), loop.index("$Code = $LASTEXITCODE",
                                                                                                start))
        # 1 or 2: the reason, and the loop starts the old version again
        self.assertIn("$Why = Read-ResultText", loop)
        self.assertIn("'The update did not complete - logs\\update.log has why.'", loop)
        self.assertIn("$Result = Join-Path $UpdateDir 'result.json'", self.code)
        # the window's mutex is not let go before the new script takes it again
        self.assertNotIn("Release-Window", loop)
        self.assertIn("if (-not $Owned -and $AfterUpdate) {", self.code)

    def test_every_y_builds_venv_new_and_swaps_it_in(self):
        self.assertIn("$VenvNew = Join-Path $Root '.venv.new'", self.code)
        self.assertIn("$VenvPrev = Join-Path $Root '.venv.prev'", self.code)
        self.assertEqual(self.code.count("-m venv"), 1)
        self.assertIn("& $Python.Exe @Pre -m venv $VenvNew", self.code)
        marker = self.code.index("WriteAllText($NewMarker")
        first = self.code.index("Rename-Item -LiteralPath $Venv -NewName '.venv.prev'")
        second = self.code.index("Rename-Item -LiteralPath $VenvNew -NewName '.venv'")
        self.assertLess(self.code.index("-m pip"), marker)
        self.assertLess(marker, first)
        self.assertLess(first, second)
        # a leftover .venv.new is removed first, and never through a link
        self.assertLess(self.code.index("if ($ok) { $ok = Remove-Leftover $VenvNew }"), self.code.index("-m venv"))
        leftover = self.code[self.code.index("function Remove-Leftover"):]
        self.assertLess(leftover.index("ReparsePoint"), leftover.index("Remove-Item"))
        # a failure removes .venv.new and keeps .venv
        self.assertIn("} else {\n            [void](Remove-Leftover $VenvNew)\n        }", self.code)
        self.assertNotIn("Remove-Item -LiteralPath $Venv -Recurse", self.code)
        # without -AfterUpdate the old one goes at once
        self.assertIn("'environment made (.venv); the old one removed'", self.code)

    def test_leftovers_removed_at_a_plain_start(self):
        part = self.code[self.code.index("if (-not $AfterUpdate) {\n    [void](Remove-Leftover $VenvNew)"):]
        self.assertIn("[void](Remove-Leftover $VenvPrev)", part[:200])
        self.assertLess(self.code.index("[void](Remove-Leftover $VenvNew)"), self.code.index("$Python = Find-Python"))

    def test_the_r_prompt(self):
        self.assertIn("$BACK_SECS = 90", self.code)
        fin = self.code[self.code.index("} finally {"):]
        self.assertIn("if ($AfterUpdate -and -not $Handed) {", fin)
        self.assertIn("$Code -ne 0 -and $Code -ne 3 -and $Ran -lt $BACK_SECS -and (Test-Path -LiteralPath $Pending "
                      "-PathType Leaf)", fin)
        self.assertIn("('DataPiler {0} stopped before its page came up (exit code {1}) - datapiler-start.log has why.' "
                      "-f $Upd.To, $Code)", fin)
        self.assertIn("('Press R to go back to {0}, or Enter to close this window.' -f $Upd.From)", fin)
        self.assertIn("if ((Read-RorEnter) -eq 'R') {", fin)
        self.assertIn("& $Python.Exe @Pre $HelperPath --rollback (Join-Path $UpdateDir ('backup-{0}' -f $Upd.From))",
                      fin)
        r = fin[fin.index("--rollback"):]
        self.assertLess(r.index("Rename-Item -LiteralPath $VenvPrev -NewName '.venv'"), r.index('& "$PSScriptRoot'))
        self.assertIn('& "$PSScriptRoot\\DataPiler.ps1"\n', r)
        # the page came up (pending gone): the old environment goes
        self.assertIn("} elseif (-not (Test-Path -LiteralPath $Pending)) {\n            [void](Remove-Leftover "
                      "$VenvPrev)", fin)
        # never automatic: R is read from the keyboard
        self.assertIn("[Console]::ReadKey($true)", self.code)

    def test_r_when_the_new_script_stops_before_its_app(self):
        """Found by the correctness review (C3): R was offered only from the new script's app loop, so a new script
        that stopped earlier (its Python too old, datapiler.py missing) or could not run left the owner on a version
        that cannot start. The old script offers R then; the new one says when it has settled R itself (76)."""
        self.assertIn("$EXIT_SETTLED = 76", self.code)
        loop = self.code[self.code.index("if ($Code -ne $EXIT_UPDATE) { break }"):self.code.index("} finally {")]
        call = loop.index('& "$PSScriptRoot\\DataPiler.ps1" -AfterUpdate')
        self.assertLess(loop.rindex("try {", 0, call), call)
        self.assertIn("} catch {", loop[call:])
        self.assertIn("$NewStopped = ($Code -ne 0 -and $Code -ne 3 -and $Code -ne $EXIT_SETTLED)", loop)
        fin = self.code[self.code.index("} finally {"):]
        self.assertIn("} elseif ($NewStopped -and (Test-Path -LiteralPath $Pending -PathType Leaf)) {", fin)
        # one R prompt serves both, and the new script, once it has reached it, tells the old one so
        self.assertEqual(self.code.count("if ((Read-RorEnter) -eq 'R') {"), 1)
        self.assertIn("$Settled = $true", fin)
        tail = self.code[self.code.rindex("} finally {"):]
        self.assertIn("}\nif ($Settled) { $Code = $EXIT_SETTLED }\nexit $Code", tail)
        # an early stop just after an update leaves R to the old script, instead of waiting for Enter
        close = self.code[self.code.index("function Close-Window"):self.code.index("function Get-Version")]
        early = close.index("if ($AfterUpdate -and (Test-Path -LiteralPath $Pending -PathType Leaf)) {")
        self.assertLess(close.index("Release-Window"), early)
        self.assertLess(early, close.index("exit $Code"))
        self.assertLess(close.index("exit $Code"), close.index("'Press Enter to close.'"))
        # a failed R waits for Enter, so its words can be read
        r = fin[fin.index("--rollback"):]
        failed = r.index("'Going back did not complete - logs\\update.log has why.'")
        self.assertIn("[void][Console]::ReadLine()", r[failed:failed + 200])

    def test_a_swap_cut_off_is_put_back(self):
        """Found by the security review (SEC-1): a helper stopped part way left old and new files mixed, and the
        old version started on them. backup-<from>\\backup.json unfinished, with this update's nonce, and no
        result.json for it: the window runs --rollback, after the helper's exit and at the next start."""
        test = self.code[self.code.index("function Test-Unfinished"):self.code.index("function Set-CtrlCHeld")]
        self.assertIn("('backup-{0}\\backup.json' -f $Upd.From)", test)
        self.assertIn("[string]$doc.nonce -ne $Upd.Nonce -or $doc.complete -eq $true", test)
        self.assertIn("[string]$res.nonce -eq $Upd.Nonce", test)
        self.assertIn("$nonce -match '^[0-9a-f]{32}$'", self.code)
        rollbacks = [l.strip() for l in self.code.splitlines() if "--rollback" in l]
        self.assertEqual(len(rollbacks), 3, rollbacks)
        for line in rollbacks:
            self.assertEqual(line, "& $Python.Exe @Pre $HelperPath --rollback (Join-Path $UpdateDir ('backup-{0}' "
                                   "-f $Upd.From))")
        # after the helper, before the old version starts again
        loop = self.code[self.code.index("if ($Code -ne $EXIT_UPDATE) { break }"):self.code.index("} finally {")]
        self.assertLess(loop.index("--pending"), loop.index("if (Test-Unfinished $Upd) {"))
        self.assertLess(loop.index("if (Test-Unfinished $Upd) {"), loop.index("$Why = Read-ResultText"))
        # at a start, once Python is found and before anything runs
        start = self.code.index("if (Test-Unfinished $Upd) {")
        self.assertLess(self.code.index("Write-Line ('Python {0}' -f $PyName)"), start)
        self.assertLess(start, self.code.index("$LockInfo = Read-Lock"))

    def test_ctrl_c_is_held_around_every_helper_run(self):
        lines = [l.strip() for l in self.code.splitlines()]
        runs = [i for i, l in enumerate(lines) if l.startswith("& $Python.Exe @Pre $HelperPath")]
        self.assertEqual(len(runs), 4)
        for i in runs:
            self.assertEqual(lines[i - 1], "Set-CtrlCHeld $true", lines[i])
            self.assertEqual(lines[i + 2], "Set-CtrlCHeld $false", lines[i])
        held = self.code[self.code.index("function Set-CtrlCHeld"):]
        self.assertIn("[Console]::TreatControlCAsInput = $On", held[:400])

    def test_no_control_leaves_the_finally_block(self):
        """PowerShell refuses return, break, continue and exit inside a finally block (ControlLeavingFinally)."""
        fin = self.code[self.code.index("} finally {"):self.code.rindex("exit $Code")]
        for word in ("return", "break", "continue", "exit"):
            self.assertIsNone(re.search(r"(?m)^\s*%s\b" % word, fin), word)
            self.assertNotRegex(fin, r"[;{]\s*%s\b" % word)

    def test_braces_balance(self):
        depth = 0
        for ch in re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "", self.code):
            depth += {"{": 1, "}": -1}.get(ch, 0)
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)


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
