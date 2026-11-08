"""DataPiler's own check of its repository (settled S14, build plan §8.4). Standard library only.

It fails a tree that holds:

- **run-time files**: a file under the top-level `workspace/`, `share/`, `logs/`, `jobs/` or `exports/` folder, or
  DataPiler's local state at the top (`settings.json`, `datapiler.port`, `datapiler.lock`, `datapiler-start.log`,
  `.venv/`). The same names deeper down, such as a test's fixtures, are not run-time folders and pass;
- **game files**, by the kinds `.gitignore` keeps out (`*.csv`, `*.fmg`, `*.dcx`, `regulation.bin`, Oodle, ...);
- **a share file**: a `.json` holding an object whose `format` is `datapiler-share/<n>`, or a `.json` that does not
  parse but names that format. The same string in any other file passes;
- **an IP address other than 127.0.0.1**. Passed, as they name no one's machine: the documentation ranges
  (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32), `0.x.x.x` and other four-part numbers ending in
  `.0` outside the private and local ranges, which is the shape of a version such as `1.16.0.0` (P8), `::1`, and an
  IPv6 link-local address whose interface identifier is short, as invented examples write it (`fe80::1`). Private,
  shared and link-local IPv4 addresses always fail, whatever their last part;
- **a user's folder**: a Windows user's (`C:\\Users\\<name>`, `Documents and Settings`), a macOS user's
  (`/Users/<name>`) or a home folder (`/home/<name>`), unless the name is a placeholder (`<name>`, `%USERNAME%`,
  `$env:USERNAME`, `...`) or a generic one that names no one (`user`, `player`, `runneradmin`, `Public`, ...);
- **an e-mail address** other than a GitHub noreply address (`@users.noreply.github.com`, `noreply@github.com`), the
  commit trailer's noreply address, or one at a reserved example domain (`example.com`, `.invalid`, `.test`, ...).

These two rules need no list of anyone's names, so they run in CI. The owner's personal words (the privacy sweep's
own list) never leave the owner's PC: that part of the sweep stays with its pre-push gate (settled S14's note).

Each finding names the file, the line and the rule, never the value: CI logs are public.

In a git work tree it checks what git tracks and what `git add .` would add (ignored files are not checked, so a
local `workspace/` is fine until it is forced in). Elsewhere, or with `--walk`, every file under the root but `.git/`
and `__pycache__/`.

    python3 -I tools/repocheck.py [ROOT] [--walk | --git]

Exit codes: 0 clean, 1 findings, 2 the tree could not be listed.
"""

from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RUNTIME_DIRS = {"workspace", "share", "logs", "jobs", "exports", ".venv"}
RUNTIME_FILES = {"settings.json", "datapiler.port", "datapiler.lock", "datapiler-start.log"}
GAME_PATTERNS = ("*.csv", "*.fmg", "*.fmg.xml", "*.dcx", "*.bnd", "*.bdt", "*.bhd", "*.sl2", "regulation.bin",
                 "oo2core*.dll")
GAME_DIRS = {"game-export"}
SHARE_FORMAT = "datapiler-share/"
MAX_BYTES = 20 * 1024 * 1024


def _v4(a: int, b: int, c: int, d: int, bits: int) -> ipaddress.IPv4Network:
    """A network from its parts (written so, this file holds no address for a sweep to find)."""
    return ipaddress.IPv4Network((a << 24 | b << 16 | c << 8 | d, bits))


def _v6(first: int, second: int, bits: int) -> ipaddress.IPv6Network:
    return ipaddress.IPv6Network((first << 112 | second << 96, bits))


LOOPBACK = ipaddress.IPv4Address(127 << 24 | 1)
DOC_V4 = [_v4(192, 0, 2, 0, 24), _v4(198, 51, 100, 0, 24), _v4(203, 0, 113, 0, 24)]   # RFC 5737
THIS_NETWORK = _v4(0, 0, 0, 0, 8)
LOCAL_V4 = [_v4(10, 0, 0, 0, 8), _v4(172, 16, 0, 0, 12), _v4(192, 168, 0, 0, 16),   # RFC 1918
            _v4(100, 64, 0, 0, 10), _v4(169, 254, 0, 0, 16)]                       # shared, link-local
DOC_V6 = _v6(0x2001, 0x0DB8, 32)                                                      # RFC 3849
GLOBAL_V6 = _v6(0x2000, 0, 3)
ULA_V6 = _v6(0xFC00, 0, 7)
LINK_LOCAL_V6 = _v6(0xFE80, 0, 10)

V4_RX = re.compile(rb"(?<![0-9.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9]|\.[0-9])")
V6_RX = re.compile(rb"(?<![0-9A-Za-z:.])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7})(?![0-9A-Za-z:])")

# A user's folder and the name after it (any number of slashes or backslashes, as source code doubles them).
USER_DIR_RX = re.compile(rb"(?i)(?:(?<![A-Za-z0-9])[A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+"
                         rb"|(?<![\w.~-])/+(?:Users|home)/+)([^\\/\s\"'<>|:*?`,;()\[\]{}]+)")
# Names that are no one's: placeholders, CI runners' and containers' accounts, and the invented ones fixtures use.
GENERIC_USERS = {
    "public", "default", "default user", "all users", "user", "users", "username", "yourname", "your name",
    "yourusername", "you", "name", "me", "someone", "somebody", "example", "test", "tester", "player", "owner",
    "runner", "runneradmin", "runner~1", "root", "admin", "administrator", "defaultapppool", "ubuntu", "vagrant",
    "pi", "deck", "steam", "node", "app", "dev", "build", "ci", "foo", "bar", "x", "xxx",
}
EMAIL_RX = re.compile(rb"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
                      rb"(?![A-Za-z0-9-])")
NOREPLY_RX = re.compile(r"(?i)(?:\d+\+)?[a-z0-9-]+(?:\[bot\])?@users\.noreply\.github\.com|noreply@github\.com"
                        r"|noreply@anthropic\.com")
EXAMPLE_MAIL_RX = re.compile(r"(?i).+@(?:[a-z0-9-]+\.)*(?:example\.(?:com|org|net)|example|invalid|test|localhost)"
                             r"|git@github\.com")
# A match that ends in a file's extension is a file, not an address (a package pinned at a version, an asset at a
# size, as npm and image names write them)
FILE_ENDINGS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js", "mjs", "json", "md", "txt", "html",
                "htm", "py", "toml", "yml", "yaml", "xml", "cpp", "hpp", "exe", "dll", "zip", "whl"}


class Finding:
    def __init__(self, path: str, rule: str, line: int | None = None):
        self.path, self.rule, self.line = path, rule, line

    def __str__(self) -> str:
        where = self.path if self.line is None else "%s:%d" % (self.path, self.line)
        return "%s: %s" % (where, self.rule)


# ------------------------------------------------------------------------------------------------ the rules

def path_findings(rel: str) -> list[Finding]:
    """The rules on a file's place and name alone. rel: relative to the root, with '/'."""
    parts = rel.split("/")
    low = [p.lower() for p in parts]
    out = []
    if len(parts) > 1 and low[0] in RUNTIME_DIRS:
        out.append(Finding(rel, "a file under the top-level %s/ folder, which DataPiler writes at run time"
                           % low[0]))
    if len(parts) == 1 and low[0] in RUNTIME_FILES:
        out.append(Finding(rel, "DataPiler's local state, written at run time"))
    if any(p in GAME_DIRS for p in low[:-1]) or any(fnmatch.fnmatchcase(low[-1], g) for g in GAME_PATTERNS):
        out.append(Finding(rel, "a game file, by its kind (.gitignore keeps these out)"))
    return out


def _names_share_format(value, depth: int = 0) -> bool:
    if depth > 64:
        return True                                     # too deep to tell: fail closed
    if isinstance(value, dict):
        fmt = value.get("format")
        if isinstance(fmt, str) and fmt.startswith(SHARE_FORMAT):
            return True
        return any(_names_share_format(v, depth + 1) for v in value.values())
    if isinstance(value, list):
        return any(_names_share_format(v, depth + 1) for v in value)
    return False


def share_findings(rel: str, data: bytes) -> list[Finding]:
    if not rel.lower().endswith(".json"):
        return []
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        if SHARE_FORMAT.encode("ascii") in data:
            return [Finding(rel, "a .json that does not parse and names the share format")]
        return []
    if _names_share_format(doc):
        return [Finding(rel, "a share file (format %s...): share files are never committed" % SHARE_FORMAT)]
    return []


def v4_rule(octets: tuple[int, int, int, int]) -> str | None:
    """Why this dotted quad fails, or None if it passes."""
    if any(o > 255 for o in octets):
        return None                                     # not an address
    ip = ipaddress.IPv4Address(".".join(str(o) for o in octets))
    if ip == LOOPBACK or any(ip in n for n in DOC_V4) or ip in THIS_NETWORK:
        return None
    if any(ip in n for n in LOCAL_V4):
        return "a private or local IPv4 address"
    if octets[3] == 0:
        return None                                     # a four-part version's shape (1.16.0.0), P8
    return "an IPv4 address other than 127.0.0.1"


def v6_rule(text: str) -> str | None:
    if "::" not in text and text.count(":") != 7:
        return None
    try:
        ip = ipaddress.IPv6Address(text)
    except ValueError:
        return None                                     # not an address: a time of day, a C++ scope
    if ip in DOC_V6:
        return None
    if ip in GLOBAL_V6 or ip in ULA_V6:
        return "an IPv6 address"
    if ip in LINK_LOCAL_V6 and (int(ip) >> 32) & 0xFFFFFFFF:
        return "an IPv6 link-local address with a full interface identifier"
    return None


def ip_findings(rel: str, data: bytes) -> list[Finding]:
    out = []
    starts = None

    def line_of(pos: int) -> int:
        nonlocal starts
        if starts is None:
            starts = [m.end() for m in re.finditer(rb"\n", data)]
        lo, hi = 0, len(starts)
        while lo < hi:
            mid = (lo + hi) // 2
            if starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return lo + 1

    for m in V4_RX.finditer(data):
        rule = v4_rule(tuple(int(g) for g in m.groups()))
        if rule:
            out.append(Finding(rel, rule, line_of(m.start())))
    for m in V6_RX.finditer(data):
        rule = v6_rule(m.group(1).decode("ascii"))
        if rule:
            out.append(Finding(rel, rule, line_of(m.start())))
    return out


def _line_finder(data: bytes):
    starts = None

    def line_of(pos: int) -> int:
        nonlocal starts
        if starts is None:
            starts = [m.end() for m in re.finditer(rb"\n", data)]
        lo, hi = 0, len(starts)
        while lo < hi:
            mid = (lo + hi) // 2
            if starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid
        return lo + 1

    return line_of


def user_dir_findings(rel: str, data: bytes) -> list[Finding]:
    """A user's folder whose name is not a placeholder or a generic one."""
    out = []
    line_of = _line_finder(data)
    for m in USER_DIR_RX.finditer(data):
        name = m.group(1).decode("latin-1")
        low = name.lower().strip(".")
        if not low or low in GENERIC_USERS or name[0] in "<%$*{[." or set(low) <= {"x", "*", "."}:
            continue
        out.append(Finding(rel, "a user's folder, which names a person or a machine's account", line_of(m.start())))
    return out


def email_findings(rel: str, data: bytes) -> list[Finding]:
    """An e-mail address other than a noreply or an example one."""
    out = []
    line_of = _line_finder(data)
    for m in EMAIL_RX.finditer(data):
        v = m.group(0).decode("latin-1")
        if v.rsplit(".", 1)[1].lower() in FILE_ENDINGS:
            continue
        if NOREPLY_RX.fullmatch(v) or EXAMPLE_MAIL_RX.fullmatch(v):
            continue
        out.append(Finding(rel, "an e-mail address other than a noreply or an example one", line_of(m.start())))
    return out


def check_file(root: Path, rel: str) -> list[Finding]:
    out = path_findings(rel)
    path = root / rel
    if path.is_symlink():
        return out + [Finding(rel, "a symbolic link, which this check does not follow")]
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            return out + [Finding(rel, "too large to check (over %d MB)" % (MAX_BYTES // (1024 * 1024)))]
        data = path.read_bytes()
    except OSError:
        return out + [Finding(rel, "could not be read")]
    return (out + share_findings(rel, data) + ip_findings(rel, data) + user_dir_findings(rel, data)
            + email_findings(rel, data))


# ------------------------------------------------------------------------------------------------ the tree

def git_files(root: Path) -> list[str] | None:
    """What git tracks and what `git add .` would add, or None if root is not a git work tree's top."""
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True,
                             timeout=60)
        if top.returncode != 0 or Path(top.stdout.decode("utf-8", "surrogateescape").strip()).resolve() \
                != root.resolve():
            return None
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    if listed.returncode != 0:
        return None
    names = listed.stdout.decode("utf-8", "surrogateescape").split("\0")
    return sorted({n for n in names if n and ((root / n).exists() or (root / n).is_symlink())})


def walk_files(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in (".git", "__pycache__"))
        for name in filenames:
            out.append(Path(dirpath, name).relative_to(root).as_posix())
    return sorted(out)


def check_tree(root: Path, mode: str = "auto") -> tuple[list[Finding], int]:
    """(the findings, how many files were checked). mode: "auto", "git" or "walk"."""
    files = None
    if mode in ("auto", "git"):
        files = git_files(root)
        if files is None and mode == "git":
            raise OSError("not the top of a git work tree")
    if files is None:
        files = walk_files(root)
    findings = []
    for rel in files:
        findings.extend(check_file(root, rel))
    return findings, len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="repocheck.py", description="DataPiler's repository check (S14)")
    ap.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parent.parent))
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--walk", action="store_true", help="check every file under the root, whatever git says")
    group.add_argument("--git", action="store_true", help="check what git tracks or would add; fail elsewhere")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print("repocheck: the root is not a folder", file=sys.stderr)
        return 2
    try:
        findings, count = check_tree(root, "walk" if args.walk else "git" if args.git else "auto")
    except OSError:
        print("repocheck: the tree could not be listed", file=sys.stderr)
        return 2
    for f in findings:
        print(f)
    if findings:
        print("repocheck: %d finding(s) in %d file(s) checked" % (len(findings), count))
        return 1
    print("repocheck: clean, %d file(s) checked" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
