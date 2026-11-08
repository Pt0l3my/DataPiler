"""The launcher's source (build plan §7.3, §8.4): launcher.cpp's contract with the app and DataPiler.ps1, its
manifest, its resource script's version, and, where MinGW-w64 is on PATH, a build with BUILD.md's own commands."""

import _repo  # noqa: F401

import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from datapiler import VERSION

SRC = os.path.join(_repo.ROOT, "launcher-src")
CPP = os.path.join(SRC, "launcher.cpp")
RC = os.path.join(SRC, "app.rc")
MANIFEST = os.path.join(SRC, "app.manifest")
BUILD_MD = os.path.join(_repo.ROOT, "BUILD.md")
APP = os.path.join(_repo.ROOT, "datapiler.py")
PATHS = os.path.join(_repo.ROOT, "datapiler", "paths.py")
LICENSE = os.path.join(_repo.ROOT, "LICENSE")

GPP = "x86_64-w64-mingw32-g++"
WINDRES = "x86_64-w64-mingw32-windres"
OBJDUMP = "x86_64-w64-mingw32-objdump"


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def code_only(cpp: str) -> str:
    """The source without its comments, so a rule about calls is not met or broken by a comment."""
    cpp = re.sub(r"/\*.*?\*/", " ", cpp, flags=re.S)
    return re.sub(r"//[^\n]*", " ", cpp)


def version4() -> tuple[int, int, int, int]:
    major, minor, patch = (int(x) for x in VERSION.split("."))
    return major, minor, patch, 0


class LauncherCpp(unittest.TestCase):
    def setUp(self):
        self.src = read(CPP)
        self.code = code_only(self.src)

    def test_the_mutex_is_the_apps(self):
        self.assertIn('L"Local\\\\DataPiler"', self.code)
        self.assertIn("OpenMutexW(SYNCHRONIZE, FALSE, name)", self.code)
        self.assertIn("static bool Running() { return Held(MUTEX); }", self.code)
        m = re.search(r'^MUTEX\s*=\s*"([^"]+)"', read(APP), re.M)
        self.assertIsNotNone(m, "datapiler.py names no MUTEX")
        self.assertEqual(m.group(1), "Local\\\\DataPiler")

    def test_the_port_file_is_the_apps(self):
        self.assertIn('L"\\\\datapiler.port"', self.code)
        self.assertIn('"datapiler.port"', read(PATHS))

    def test_powershell_7_before_windows_powershell(self):
        a, b = self.code.find('L"pwsh.exe"'), self.code.find('L"powershell.exe"')
        self.assertGreater(a, 0)
        self.assertGreater(b, a)

    def test_the_command_line(self):
        for part in ("-NoLogo", "-NoProfile", "-ExecutionPolicy Bypass", "-File", "-FromLauncher",
                     'L"\\\\DataPiler.ps1"'):
            self.assertIn(part, self.code, part)
        self.assertIn("CREATE_NEW_CONSOLE", self.code)

    def test_a_60_second_bound(self):
        self.assertRegex(self.code, r"WAIT_MS\s*=\s*60\s*\*\s*1000\s*;")
        self.assertIn("GetTickCount64() - t0 >= WAIT_MS", self.code)

    def test_no_bound_while_its_own_window_works(self):
        """Found by the correctness review: the 60 s ran through the first start's question, .venv and pip, then
        said "did not start" while DataPiler was still starting. The bound is for a page another start brings up."""
        self.assertIn("if (!window && GetTickCount64() - t0 >= WAIT_MS) return 0;", self.code)
        self.assertNotIn("did not start - its window says why", self.code)

    def test_powershell_never_from_its_own_or_the_current_folder(self):
        """SearchPathW(NULL, ...) tries the exe's folder and the current folder before PATH, so a pwsh.exe lying
        beside an unpacked DataPiler.exe would run instead (the security review)."""
        self.assertNotRegex(self.code, r"SearchPathW\s*\(\s*NULL")
        self.assertIn('GetEnvironmentVariableW(L"PATH"', self.code)
        self.assertIn("GetSystemDirectoryW(", self.code)
        self.assertIn('L"\\\\WindowsPowerShell\\\\v1.0\\\\"', self.code)
        self.assertIn("!IsAbsolute(dir)", self.code)
        self.assertIn("key == exeKey", self.code)
        self.assertIn("key == cwdKey", self.code)

    def test_a_starting_window_counts_as_running(self):
        """A second start while the first window is still before the app (its question, .venv, pip) starts no
        second window: DataPiler.ps1 holds its own mutex from its first line, and the launcher waits for the page."""
        m = re.search(r'WINDOW_MUTEX = L"([^"]+)"', self.code)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "Local\\\\DataPiler-window")
        with open(os.path.join(_repo.ROOT, "DataPiler.ps1"), encoding="ascii") as f:
            ps1 = f.read()
        self.assertIn("New-Object System.Threading.Mutex($false, 'Local\\DataPiler-window')", ps1)
        start = self.code.index("int WINAPI wWinMain(")
        body = self.code[start:]
        self.assertLess(body.index("if (Running())"), body.index("if (Starting())"))
        self.assertLess(body.index("if (Starting())"), body.index("CreateProcessW("))

    def test_what_it_never_does(self):
        low = self.code.lower()
        for word in ("pythonw", "create_no_window", "socket", "connect(", "wsastartup", "winsock", "ws2_32",
                     "winhttp", "wininet", "internetopen", "urldownload", "runas", "setexecutionpolicy",
                     "regsetvalue", "regcreatekey"):
            self.assertNotIn(word, low, word)

    def test_jobrunners_helpers_are_kept(self):
        for name in ("static std::wstring ExeDir()", "static bool FindOnPath(", "static ULONGLONG Ticks(",
                     "static int FreshPort("):
            self.assertIn(name, self.code, name)


class Manifest(unittest.TestCase):
    NS = {"v1": "urn:schemas-microsoft-com:asm.v1", "v3": "urn:schemas-microsoft-com:asm.v3"}

    def setUp(self):
        self.root = ET.parse(MANIFEST).getroot()

    def test_as_invoker(self):
        levels = self.root.findall(".//v3:requestedExecutionLevel", self.NS)
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0].get("level"), "asInvoker")
        self.assertEqual(levels[0].get("uiAccess"), "false")

    def test_its_name_and_version(self):
        ident = self.root.find("v1:assemblyIdentity", self.NS)
        self.assertEqual(ident.get("name"), "DataPiler.Launcher")
        self.assertEqual(ident.get("version"), "%d.%d.%d.%d" % version4())


class ResourceScript(unittest.TestCase):
    def setUp(self):
        self.rc = read(RC)

    def value(self, key: str) -> str:
        m = re.search(r'VALUE\s+"%s",\s*"([^"]*)"' % key, self.rc)
        self.assertIsNotNone(m, key)
        return m.group(1)

    def test_the_version_matches(self):
        dotted = "%d.%d.%d.%d" % version4()
        commas = "%d,%d,%d,%d" % version4()
        self.assertRegex(self.rc, r"(?m)^FILEVERSION %s$" % re.escape(commas))
        self.assertRegex(self.rc, r"(?m)^PRODUCTVERSION %s$" % re.escape(commas))
        self.assertEqual(self.value("FileVersion"), dotted)
        self.assertEqual(self.value("ProductVersion"), dotted)

    def test_its_names(self):
        self.assertEqual(self.value("ProductName"), "DataPiler")
        self.assertEqual(self.value("OriginalFilename"), "DataPiler.exe")
        comments = self.value("Comments")
        self.assertIn("launcher-src/launcher.cpp", comments)
        self.assertIn("Jobrunner", comments)

    def test_the_copyright_is_licenses_line(self):
        line = next(l.strip() for l in read(LICENSE).splitlines() if l.startswith("Copyright"))
        self.assertEqual(self.value("LegalCopyright"), line)

    def test_no_icon_and_the_manifest(self):
        self.assertNotRegex(self.rc, r"\bICON\b")
        self.assertNotRegex(self.rc, r"\.ico\b")
        self.assertRegex(self.rc, r'(?m)^1 24 "app\.manifest"$')

    def test_no_icon_file_in_the_folder(self):
        self.assertEqual(sorted(os.listdir(SRC)), ["app.manifest", "app.rc", "launcher.cpp"])


def build_md_commands() -> list[list[str]]:
    """The windres and g++ lines of BUILD.md's first code block, split as a shell would."""
    text = read(BUILD_MD)
    block = re.search(r"```\n(.*?)```", text, re.S)
    assert block, "BUILD.md has no code block"
    return [shlex.split(line) for line in block.group(1).splitlines() if line.startswith("x86_64-w64-mingw32-")]


class BuildMd(unittest.TestCase):
    def test_the_commands_and_the_checks(self):
        cmds = build_md_commands()
        self.assertEqual([c[0] for c in cmds], [WINDRES, GPP])
        gpp = cmds[1]
        for flag in ("-std=c++17", "-O2", "-municode", "-mwindows", "-static", "-s", "-Wl,--no-insert-timestamp",
                     "-lshell32", "-lole32"):
            self.assertIn(flag, gpp, flag)
        self.assertEqual(gpp[gpp.index("-o") + 1], "DataPiler.exe")
        text = read(BUILD_MD)
        self.assertIn("PE32+ executable (GUI) x86-64", text)
        self.assertIn("strings -a -el DataPiler.exe | grep %d.%d.%d.%d" % version4(), text)

    def test_the_release_workflow_builds_the_same_way(self):
        gpp = build_md_commands()[1]
        wf = read(os.path.join(_repo.ROOT, ".github", "workflows", "release.yml"))
        line = next(l.strip() for l in wf.splitlines() if l.strip().startswith("g++ -std"))
        self.assertEqual(shlex.split(line)[1:], gpp[1:])


def pe_header(data: bytes) -> dict:
    """The fields of a PE file's headers this test checks."""
    assert data[:2] == b"MZ", "not an MZ file"
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0", "no PE signature"
    machine, _sections, stamp = struct.unpack_from("<HHI", data, pe + 4)
    magic = struct.unpack_from("<H", data, pe + 24)[0]
    subsystem = struct.unpack_from("<H", data, pe + 24 + 68)[0]
    return {"machine": machine, "stamp": stamp, "magic": magic, "subsystem": subsystem}


@unittest.skipUnless((shutil.which(GPP) and shutil.which(WINDRES)) or os.environ.get("DATAPILER_NEED_MINGW"),
                     "MinGW-w64 is not on PATH")
class Build(unittest.TestCase):
    """BUILD.md's commands, run as written (without a shell) in a temporary folder."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = cls._tmp.name
        for name in ("launcher.cpp", "app.rc", "app.manifest"):
            shutil.copy(os.path.join(SRC, name), cls.dir)
        cls.exe = os.path.join(cls.dir, "DataPiler.exe")
        for cmd in build_md_commands():
            subprocess.run(cmd, cwd=cls.dir, check=True, capture_output=True, timeout=300)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_a_gui_pe32_plus_for_x86_64(self):
        with open(self.exe, "rb") as f:
            h = pe_header(f.read())
        self.assertEqual(h["machine"], 0x8664)      # x86-64
        self.assertEqual(h["magic"], 0x20B)         # PE32+
        self.assertEqual(h["subsystem"], 2)         # Windows GUI
        self.assertEqual(h["stamp"], 0)             # --no-insert-timestamp

    def test_its_version_and_manifest_are_inside(self):
        with open(self.exe, "rb") as f:
            data = f.read()
        self.assertIn(("%d.%d.%d.%d" % version4()).encode("utf-16-le"), data)
        self.assertIn(b'level="asInvoker"', data)

    def test_the_same_bytes_twice(self):
        again = os.path.join(self.dir, "again.exe")
        cmd = build_md_commands()[1]
        cmd = cmd[:cmd.index("-o") + 1] + ["again.exe"] + cmd[cmd.index("-o") + 2:]
        subprocess.run(cmd, cwd=self.dir, check=True, capture_output=True, timeout=300)
        with open(self.exe, "rb") as a, open(again, "rb") as b:
            self.assertEqual(a.read(), b.read())

    @unittest.skipUnless(shutil.which(OBJDUMP), "objdump is not on PATH")
    def test_no_socket_library_imported(self):
        out = subprocess.run([OBJDUMP, "-p", self.exe], check=True, capture_output=True, timeout=120).stdout
        dlls = sorted({d.decode().upper() for d in re.findall(rb"DLL Name: (\S+)", out)})
        self.assertTrue({"KERNEL32.DLL", "SHELL32.DLL", "USER32.DLL"} <= set(dlls), dlls)
        for dll in dlls:
            self.assertTrue(dll in {"KERNEL32.DLL", "SHELL32.DLL", "USER32.DLL", "MSVCRT.DLL", "UCRTBASE.DLL"}
                            or dll.startswith("API-MS-WIN-CRT-"), dll)


if __name__ == "__main__":
    unittest.main()
