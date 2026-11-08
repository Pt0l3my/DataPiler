"""requirements.lock (build plan §4.12, §8.2): its header, every requirement pinned with its hashes, only the packages
the header names, and the header's versions matching the pins."""

import _repo  # noqa: F401

import os
import re
import unittest

LOCK = os.path.join(_repo.ROOT, "requirements.lock")

HEADER_RX = (
    re.compile(r"# datapiler-lock/1"),
    re.compile(r"# pythons:( 3\.\d{1,2})+"),
    re.compile(r"# download-mb: [1-9]\d{0,2}"),
)
PACKAGE_RX = re.compile(r"# ([a-z0-9][a-z0-9._-]*) (\d+(?:\.\d+){1,3}) ([A-Za-z0-9.+-]+)")
REQ_RX = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\d+(?:\.\d+){1,3})((?: --hash=sha256:[0-9a-f]{64})+)")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class LockTests(unittest.TestCase):
    def setUp(self):
        with open(LOCK, "rb") as f:
            self.raw = f.read()
        self.text = self.raw.decode("ascii")
        self.lines = self.text.splitlines()

    def header(self):
        out = []
        for line in self.lines:
            if not line.startswith("#"):
                break
            out.append(line)
        return out

    def packages(self):
        return {norm(m.group(1)): (m.group(2), m.group(3))
                for m in (PACKAGE_RX.fullmatch(x) for x in self.header()[3:])}

    def requirements(self):
        body = [x for x in self.lines[len(self.header()):] if x.strip()]
        joined = re.sub(r"\s*\\\n\s*", " ", "\n".join(body))
        reqs = {}
        for line in joined.splitlines():
            m = REQ_RX.fullmatch(line.strip())
            self.assertIsNotNone(m, "a requirement line of another shape")
            hashes = re.findall(r"[0-9a-f]{64}", m.group(3))
            self.assertEqual(len(hashes), len(set(hashes)))
            reqs[norm(m.group(1))] = (m.group(2), hashes)
        return reqs

    def test_ascii_and_unix_lines(self):
        self.assertNotIn(b"\r", self.raw)
        self.assertTrue(self.raw.endswith(b"\n"))

    def test_every_checkout_keeps_lf(self):
        """Git for Windows checks text out with CRLF unless told otherwise (core.autocrlf=true), which would break
        the line above and the release workflow's sed on the Windows runners."""
        with open(os.path.join(_repo.ROOT, ".gitattributes"), encoding="ascii") as f:
            rules = [line.split() for line in f.read().splitlines() if line.strip() and not line.startswith("#")]
        self.assertIn(["*", "text=auto", "eol=lf"], rules)
        self.assertIn(["*.exe", "binary"], rules)

    def test_header(self):
        head = self.header()
        self.assertGreaterEqual(len(head), 5)
        for rx, line in zip(HEADER_RX, head):
            self.assertRegex(line, "^" + rx.pattern + "$")
        pythons = head[1].split(":", 1)[1].split()
        self.assertIn("3.10", pythons)
        self.assertEqual(pythons, sorted(pythons, key=lambda v: tuple(int(x) for x in v.split("."))))
        for line in head[3:]:
            self.assertIsNotNone(PACKAGE_RX.fullmatch(line), "a header line of another shape")
        pk = self.packages()
        self.assertEqual(pk["grpcio"][1], "Apache-2.0")
        self.assertEqual(pk["protobuf"][1], "BSD-3-Clause")

    def test_every_requirement_pinned_with_hashes(self):
        reqs = self.requirements()
        self.assertTrue(reqs)
        for name, (version, hashes) in reqs.items():
            self.assertGreaterEqual(len(hashes), 1, name)

    def test_grpcio_has_a_wheel_for_every_python(self):
        pythons = self.header()[1].split(":", 1)[1].split()
        self.assertEqual(len(self.requirements()["grpcio"][1]), len(pythons))

    def test_only_the_packages_the_header_names(self):
        self.assertEqual(set(self.requirements()), set(self.packages()))
        self.assertIn("grpcio", self.packages())
        self.assertIn("protobuf", self.packages())

    def test_header_versions_match_the_pins(self):
        reqs = self.requirements()
        for name, (version, _licence) in self.packages().items():
            self.assertEqual(reqs[name][0], version, name)

    def test_no_other_source_or_option(self):
        for bad in ("--index-url", "--extra-index-url", "--find-links", "-f ", "--trusted-host", "http:", "https:",
                    "file:", "-e ", "--editable", "@ "):
            self.assertNotIn(bad, self.text)


if __name__ == "__main__":
    unittest.main()
