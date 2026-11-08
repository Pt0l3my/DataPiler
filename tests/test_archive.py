"""update-helper.py's archive checks (build plan 0.2 §4.3, §4.6, §7.1): check_archive on crafted zips, safe_rel's
cases, and the app's copy (install.helper) agreeing with the helper loaded on its own. Every zip is invented and made
in a temporary folder; nothing here touches the network.

The builders at the top (invented_app, release_zip, ...) are shared with test_helper.py and test_update.py."""

import _repo  # noqa: F401

import hashlib
import importlib.util
import io
import stat
import struct
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

from datapiler import install

HELPER_PATH = Path(_repo.ROOT) / "update-helper.py"


def helper():
    """The app's own copy, as the app loads it."""
    return install.helper(install.APP)


def helper_alone():
    """update-helper.py loaded again under another name, as the window runs it."""
    spec = importlib.util.spec_from_file_location("update_helper_alone", str(HELPER_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def invented_app(version: str, **changes) -> dict:
    """An invented DataPiler's files, path -> bytes. changes: path -> bytes, or None to leave a file out."""
    files = {
        "datapiler/__init__.py": ('NAME = "DataPiler"\nVERSION = "%s"\n' % version).encode(),
        "datapiler.py": b"# an invented app, version %s\n" % version.encode(),
        "datapiler/page/app.js": b"// invented page code\n",
        "README.md": b"An invented read-me, the same in every version.\n",
        "requirements.lock": b"# datapiler-lock/1\n# invented\n",
        "update-helper.py": HELPER_PATH.read_bytes(),
        "DataPiler.ps1": b"# invented window script\n",
    }
    for k, v in changes.items():
        k = k.replace("__", "/") if "/" not in k and "__" in k else k
        if v is None:
            files.pop(k, None)
        else:
            files[k] = v
    return files


def manifest_of(files: dict) -> bytes:
    return helper().format_manifest({p: sha(b) for p, b in files.items()})


def release_zip(path: Path, files: dict, *, manifest: bytes | None = None, extra: list | None = None,
                top: str = "DataPiler", with_manifest: bool = True, dirs: bool = True) -> Path:
    """A release zip: top/<file> for each file, top/manifest.sha256 (made from the files unless given), directory
    entries when dirs, and extra raw members (name, data, external_attr or None)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if dirs:
            zf.writestr(zipfile.ZipInfo(top + "/"), b"")
        for rel in sorted(files):
            zf.writestr("%s/%s" % (top, rel), files[rel])
        if with_manifest:
            zf.writestr("%s/manifest.sha256" % top, manifest if manifest is not None else manifest_of(files))
        for name, data, attr in extra or []:
            zi = zipfile.ZipInfo(name)
            zi.filename = name          # as given: ZipInfo turns a backslash into "/" on Windows
            if attr is not None:
                zi.external_attr = attr
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)      # a name twice, on purpose
                zf.writestr(zi, data)
    return path


def shrink_declared(path: Path, name: str, new_size: int) -> None:
    """Rewrites a member's uncompressed size, in its local header and the central directory, to new_size."""
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as zf:
        off = zf.getinfo(name).header_offset
    assert data[off:off + 4] == b"PK\x03\x04"
    struct.pack_into("<I", data, off + 22, new_size)
    nb = name.encode()
    i = data.find(b"PK\x01\x02")
    while i >= 0:
        fnlen = struct.unpack_from("<H", data, i + 28)[0]
        if bytes(data[i + 46:i + 46 + fnlen]) == nb:
            struct.pack_into("<I", data, i + 24, new_size)
            break
        i = data.find(b"PK\x01\x02", i + 4)
    path.write_bytes(bytes(data))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.h = helper()

    def tearDown(self):
        self.tmp.cleanup()

    def refused(self, path, version="0.3.0", h=None):
        h = h or self.h
        with self.assertRaises(h.Refused) as cm:
            h.check_archive(path, version=version)
        return cm.exception


class CheckArchive(Base):
    def test_a_good_release(self):
        files = invented_app("0.3.0")
        z = release_zip(self.dir / "a.zip", files)
        a = self.h.check_archive(z, version="0.3.0")
        self.assertEqual(a.files, len(files))
        self.assertEqual(a.version, "0.3.0")
        self.assertEqual(a.manifest, {p: sha(b) for p, b in files.items()})
        self.assertEqual(a.lock_sha256, sha(files["requirements.lock"]))
        self.assertEqual(a.unpacked, sum(len(b) for b in files.values()) + len(manifest_of(files)))

    def test_without_directory_entries(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), dirs=False)
        self.assertEqual(self.h.check_archive(z, version="0.3.0").version, "0.3.0")

    def test_dot_dot(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/../evil.py", b"x", None)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_dot_dot_inside(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/a/../../evil.py", b"x", None)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_an_absolute_path(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("/DataPiler/evil.py", b"x", None)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_a_drive_letter(self):
        for name in ("C:/DataPiler/evil.py", "DataPiler/C:/evil.py", "DataPiler/C:evil.py"):
            with self.subTest(name=name):
                z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[(name, b"x", None)])
                self.assertEqual(self.refused(z).stage, "shape")

    def test_a_backslash(self):
        for name in ("DataPiler\\evil.py", "DataPiler/datapiler\\evil.py"):
            with self.subTest(name=name):
                z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[(name, b"x", None)])
                self.assertEqual(self.refused(z).stage, "shape")

    def test_a_symlink(self):
        attr = (stat.S_IFLNK | 0o777) << 16
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/link", b"/etc", attr)])
        e = self.refused(z)
        self.assertEqual(e.stage, "shape")
        self.assertIn("link", e.text)

    def test_a_windows_reparse_point(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/junction/", b"", 0x410)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_two_top_folders(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("Other/x.py", b"x", None)])
        e = self.refused(z)
        self.assertEqual(e.stage, "shape")
        self.assertIn("second top folder", e.text)

    def test_a_top_folder_with_another_name(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), top="DataPiler-0.3.0")
        self.assertEqual(self.refused(z).stage, "shape")

    def test_a_file_at_the_top(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("README.md", b"x", None)])
        e = self.refused(z)
        self.assertEqual(e.stage, "shape")
        self.assertIn("file at its top", e.text)

    def test_a_name_twice(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/README.md", b"x", None)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_two_names_one_file_on_windows(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/readme.MD", b"x", None)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_an_8_3_short_name(self):
        """WORKSP~1 is workspace's alias on a volume with 8.3 names (the review's SEC-5)."""
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/WORKSP~1/x.txt", b"x", None)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_a_device_name(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), extra=[("DataPiler/con.txt", b"x", None)])
        self.assertEqual(self.refused(z).stage, "shape")

    def test_no_manifest(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"), with_manifest=False)
        e = self.refused(z)
        self.assertEqual(e.stage, "manifest")
        self.assertIn("no DataPiler/manifest.sha256", e.text)

    def test_a_manifest_mismatch(self):
        files = invented_app("0.3.0")
        listed = dict(files, **{"datapiler.py": b"something else\n"})
        z = release_zip(self.dir / "a.zip", files, manifest=manifest_of(listed))
        e = self.refused(z)
        self.assertEqual(e.stage, "manifest")
        self.assertIn("datapiler.py does not match", e.text)

    def test_an_unlisted_member(self):
        files = invented_app("0.3.0")
        z = release_zip(self.dir / "a.zip", files, extra=[("DataPiler/datapiler/extra.py", b"x", None)])
        e = self.refused(z)
        self.assertEqual(e.stage, "manifest")
        self.assertIn("does not list", e.text)

    def test_a_listed_file_missing(self):
        files = invented_app("0.3.0")
        listed = dict(files, **{"datapiler/gone.py": b"x"})
        z = release_zip(self.dir / "a.zip", files, manifest=manifest_of(listed))
        e = self.refused(z)
        self.assertEqual(e.stage, "manifest")
        self.assertIn("does not hold", e.text)

    def test_a_manifest_that_does_not_parse(self):
        files = invented_app("0.3.0")
        z = release_zip(self.dir / "a.zip", files, manifest=manifest_of(files).replace(b"\n", b"\r\n"))
        self.assertEqual(self.refused(z).stage, "manifest")

    def test_an_oversize_member_whose_declared_size_is_small(self):
        files = invented_app("0.3.0", **{"datapiler/big.bin": b"\0" * 300_000})
        z = release_zip(self.dir / "a.zip", files)
        shrink_declared(z, "DataPiler/datapiler/big.bin", 10)
        e = self.refused(z)
        self.assertIn(e.stage, ("shape", "manifest"))

    def test_more_unpacked_than_the_limit(self):
        files = invented_app("0.3.0", **{"datapiler/big.bin": b"\0" * 300_000})
        z = release_zip(self.dir / "a.zip", files)
        with mock.patch.object(self.h, "MAX_UNPACKED", 100_000):
            e = self.refused(z)
        self.assertIn("more than", e.text)

    def test_counted_as_read_when_the_directory_understates(self):
        """Sizes are counted as read, not trusted from the directory: with the directory's own check lifted, the
        bytes read still refuse."""
        files = invented_app("0.3.0")
        z = release_zip(self.dir / "a.zip", files)
        total = sum(len(b) for b in files.values())
        real = self.h._members

        def lenient(zf):
            with mock.patch.object(self.h, "MAX_UNPACKED", 1 << 40):
                return real(zf)

        with mock.patch.object(self.h, "MAX_UNPACKED", total - 10), mock.patch.object(self.h, "_members", lenient):
            e = self.refused(z)
        self.assertEqual(e.stage, "manifest")
        self.assertIn("unpacks to more than", e.text)

    def test_more_members_than_the_limit(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"))
        with mock.patch.object(self.h, "MAX_MEMBERS", 5):
            e = self.refused(z)
        self.assertEqual(e.stage, "shape")
        self.assertIn("more than 5 entries", e.text)

    def test_no_update_helper(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0", **{"update-helper.py": None}))
        e = self.refused(z)
        self.assertEqual(e.stage, "manifest")
        self.assertIn("update-helper.py", e.text)

    def test_another_version_inside(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.2.9"))
        e = self.refused(z, version="0.3.0")
        self.assertEqual(e.stage, "version")
        self.assertIn("0.2.9", e.text)

    def test_no_version_line(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0", **{"datapiler/__init__.py": b"NAME = 1\n"}))
        self.assertEqual(self.refused(z).stage, "version")

    def test_not_a_zip(self):
        p = self.dir / "a.zip"
        p.write_bytes(b"PK\x03\x04 not really a zip")
        self.assertEqual(self.refused(p).stage, "shape")

    def test_an_encrypted_member(self):
        z = release_zip(self.dir / "a.zip", invented_app("0.3.0"))
        data = bytearray(z.read_bytes())
        with zipfile.ZipFile(z) as zf:
            info = zf.getinfo("DataPiler/README.md")
        nb = info.filename.encode()
        i = data.find(b"PK\x01\x02")
        while i >= 0:
            fnlen = struct.unpack_from("<H", data, i + 28)[0]
            if bytes(data[i + 46:i + 46 + fnlen]) == nb:
                flags = struct.unpack_from("<H", data, i + 8)[0]
                struct.pack_into("<H", data, i + 8, flags | 1)
            i = data.find(b"PK\x01\x02", i + 4)
        z.write_bytes(bytes(data))
        self.assertEqual(self.refused(z).stage, "shape")


class SafeRel(unittest.TestCase):
    GOOD = ("a", "a/b", "datapiler/page/app.js", "update-helper.py", ".github/workflows/checks.yml", "x.tar.gz",
            "a b/c d.txt", "DataPiler.exe", "a~b.txt", "~a")
    BAD = ("", "/a", "a/", "a//b", "./a", "a/./b", "../a", "a/../b", "..", ".", "a\\b", "C:/a", "C:a", "a:b",
           "a\x00b", "a\nb", "a\x7fb", "a./b", "a /b", "b.", "b ", "con", "CON.txt", "a/nul.py", "com1", "lpt9.log",
           "conin$", "a<b", "a>b", 'a"b', "a|b", "a?b", "a*b",
           # 8.3 short names, an alias of another name (the review's SEC-5)
           "WORKSP~1/x.txt", "SETTIN~1.JSO", "DATAPI~1.POR", "VENV~1/pyvenv.cfg", "a/b~12c")

    def test_cases(self):
        h = helper()
        for p in self.GOOD:
            self.assertTrue(h.safe_rel(p), p)
        for p in self.BAD:
            self.assertFalse(h.safe_rel(p), repr(p))
        self.assertFalse(h.safe_rel(None))
        self.assertFalse(h.safe_rel("a/" * 300))

    def test_the_device_names_are_paths_own(self):
        from datapiler import paths
        h = helper()
        for name in ("con", "prn", "aux", "nul", "com0", "com9", "lpt1", "conin$", "conout$"):
            self.assertTrue(paths.reserved(name), name)
            self.assertFalse(h.safe_rel(name), name)
            self.assertFalse(h.safe_rel(name.upper() + ".json"), name)


class Manifest(unittest.TestCase):
    def test_parse_and_format(self):
        h = helper()
        entries = {"b.py": "1" * 64, "a/z.py": "2" * 64, "A.txt": "3" * 64}
        data = h.format_manifest(entries)
        self.assertEqual(data, ("%s  A.txt\n%s  a/z.py\n%s  b.py\n" % ("3" * 64, "2" * 64, "1" * 64)).encode())
        self.assertEqual(h.parse_manifest(data), entries)
        self.assertEqual(h.parse_manifest(b""), {})

    def test_refusals(self):
        h = helper()
        good = ("%s  a.py\n" % ("1" * 64)).encode()
        for bad in (good.replace(b"\n", b"\r\n"), good[:-1], b"\xef\xbb\xbf" + good,
                    good + ("%s  A.py\n" % ("2" * 64)).encode(),          # the same file twice, case-folded
                    ("%s  ../a.py\n" % ("1" * 64)).encode(), ("%s *a.py\n" % ("1" * 64)).encode(),
                    ("%s  manifest.sha256\n" % ("1" * 64)).encode(), ("%s  a.py\n" % ("G" * 64)).encode(),
                    b"\xff\n", ("%s  a\\b.py\n" % ("1" * 64)).encode()):
            with self.subTest(bad=bad[:30]):
                with self.assertRaises(ValueError):
                    h.parse_manifest(bad)


class TheAppAndTheHelperAgree(Base):
    """The app proves a download through install.helper(); the window runs the same file on its own. Each crafted
    zip gets the same answer from both."""

    def test_each_case(self):
        alone = helper_alone()
        self.assertIsNot(alone, self.h)
        cases = {
            "good": release_zip(self.dir / "good.zip", invented_app("0.3.0")),
            "dotdot": release_zip(self.dir / "dd.zip", invented_app("0.3.0"), extra=[("DataPiler/../x", b"x", None)]),
            "link": release_zip(self.dir / "ln.zip", invented_app("0.3.0"),
                                extra=[("DataPiler/l", b"x", (stat.S_IFLNK | 0o777) << 16)]),
            "two tops": release_zip(self.dir / "tt.zip", invented_app("0.3.0"), extra=[("B/x", b"x", None)]),
            "no manifest": release_zip(self.dir / "nm.zip", invented_app("0.3.0"), with_manifest=False),
            "version": release_zip(self.dir / "v.zip", invented_app("0.2.9")),
        }
        for name, z in cases.items():
            with self.subTest(case=name):
                answers = []
                for h in (self.h, alone):
                    try:
                        a = h.check_archive(z, version="0.3.0")
                        answers.append(("ok", a.files, a.version, a.manifest))
                    except h.Refused as e:
                        answers.append(("refused", e.stage, e.text))
                self.assertEqual(answers[0], answers[1])
        for p in SafeRel.GOOD + SafeRel.BAD:
            self.assertEqual(self.h.safe_rel(p), alone.safe_rel(p), repr(p))

    def test_check_zip_from_the_command_line(self):
        alone = helper_alone()
        z = release_zip(self.dir / "good.zip", invented_app("0.3.0"))
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(alone.main(["--check-zip", str(z), "--version", "0.3.0"]), 0)
            self.assertEqual(alone.main(["--check-zip", str(z), "--version", "0.3.1"]), 2)
        said = out.getvalue()
        self.assertIn("ok one folder, DataPiler, 7 files", said)
        self.assertIn("x version: the version inside is 0.3.0, not the release's 0.3.1", said)
        self.assertNotIn(str(self.dir), said)


if __name__ == "__main__":
    unittest.main()
