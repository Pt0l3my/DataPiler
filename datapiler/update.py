"""The Update... button (design 0002 §2; build plan 0.2 §4.1 to §4.4; settled S27): the check, the download, its
proofs and the install request.

This is the only module of DataPiler that opens a connection to anywhere but 127.0.0.1, and its calls are reached
only from POST /api/update (Updater.post): nothing checks on its own, and nothing here runs at a start, from a timer,
a job or a setting. It asks only HOSTS, over https, with every redirect checked again, and logs each call by its host
and path. The page never talks to GitHub; nothing from GitHub reaches a log line but a status and a version that
passed its pattern, and nothing from GitHub reaches the page as HTML (the notes are a tree of text, §4.4).

A download goes into update/<X.Y.Z>/ as a .part, hashed as it arrives, cut off past the size the release states,
and is proved (§4.3) before anything is unpacked: its size, the release's own .sha256, GitHub's digest, then the
zip's shape and manifest through update-helper.py, the one home of those checks. Install proves it again, extracts
the helper, writes update/pending.json and asks the app to stop with exit code 75; DataPiler.ps1 does the swap."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Mapping

from . import fileio, install, logbook
from .logbook import own

REPO = "Pt0l3my/DataPiler"
LATEST = "https://api.github.com/repos/Pt0l3my/DataPiler/releases/latest"
PAGE_PREFIX = "https://github.com/Pt0l3my/DataPiler/releases/"
ASSET_PREFIX = "https://github.com/Pt0l3my/DataPiler/releases/download/"
HOSTS = ("api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
TIMEOUT = 15.0
CACHE_SECS = 600
CHUNK = 64 * 1024
REDIRECTS = 5
API_MAX = 1024 * 1024
SHA_MAX = 1024
NOTES_MAX = 20_000
ZIP_MAX = 256 * 1024 * 1024
POLL_GONE = 5.0          # a download stops when the pop-up has not read GET /api/update for 5 s (S27)
HELPER_MAX = 1024 * 1024

API_ACCEPT = "application/vnd.github+json"
ASSET_ACCEPT = "application/octet-stream"
ACTIONS = ("check", "download", "install", "cancel")
STATES = ("idle", "checking", "up_to_date", "newer", "older", "not_installable", "none", "downloading", "ready",
          "failed")

NOTHING = " Nothing was downloaded or changed."
NO_ANSWER = "GitHub could not be reached - no internet, a firewall, or a proxy that refused it."
BUSY = "A job or an Extract run is going - let it finish or cancel it, then press Install again."
NOT_UNPACKED = ("This copy was not unpacked from a release, so the button does not replace its files - unpack the "
                "release by hand.")

_URL_RX = re.compile(r"[A-Za-z0-9\-._~:/?\[\]@!$&'()*+,;=%]+")
_HOST_RX = re.compile(r"[a-z0-9.-]{1,253}")
_PATH_RX = re.compile(r"[A-Za-z0-9/._-]+")
_TAG_RX = re.compile(r"v(\d{1,4})\.(\d{1,4})\.(\d{1,4})")
_THIS_RX = re.compile(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})(-[0-9A-Za-z.-]+)?")
_DATE_RX = re.compile(r"(\d{4}-\d{2}-\d{2})T[0-9:.]+Z?")
_DIGEST_RX = re.compile(r"sha256:([0-9a-f]{64})")
_PAGE_RX = re.compile(r"[A-Za-z0-9/._:-]{1,300}")

log = logbook.get("update")


# ---------------------------------------------------------------------------------------------------------- the calls


@dataclass
class Answer:
    status: int
    headers: dict[str, str]                  # names lower-cased
    body: BinaryIO                           # read(n) -> bytes

    def close(self) -> None:
        try:
            self.body.close()
        except Exception:
            pass


Fetch = Callable[[str, Mapping[str, str], float], Answer]   # (url, headers, timeout); raises OSError on no answer


class Stop(Exception):
    """A call or a proof that ends the press, with DataPiler's words."""

    def __init__(self, text: str):
        super().__init__("stop")
        self.text = text


class _Cancelled(Exception):
    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


def allowed(url: str) -> bool:
    """https, a host in HOSTS exactly (no port, no user, no fragment), nothing else."""
    if not isinstance(url, str) or not url or len(url) > 4096 or not _URL_RX.fullmatch(url):
        return False
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return u.scheme == "https" and u.netloc in HOSTS and not u.fragment


def real_fetch() -> Fetch:
    """urllib.request with its default proxy handler (HTTPS_PROXY) and ssl.create_default_context(); redirects are
    not followed by urllib: a 3xx comes back as an Answer, and _request follows it. Only https is handled."""
    import ssl
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):    # noqa: ARG002 - urllib's signature
            return None

    opener = urllib.request.OpenerDirector()
    for h in (urllib.request.ProxyHandler(), urllib.request.HTTPSHandler(context=ssl.create_default_context()),
              _NoRedirect(), urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        opener.add_handler(h)

    def fetch(url: str, headers: Mapping[str, str], timeout: float) -> Answer:
        if not allowed(url):
            raise OSError("not an address DataPiler fetches from")
        req = urllib.request.Request(url, headers=dict(headers), method="GET")
        try:
            resp = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            return Answer(int(e.code), {k.lower(): v for k, v in (e.headers or {}).items()}, e)
        return Answer(int(resp.status), {k.lower(): v for k, v in resp.headers.items()}, resp)

    return fetch


def headers_for(version: str, accept: str) -> dict[str, str]:
    """Exactly these: no token, cookie or Referer, nothing about the PC or the owner."""
    return {"User-Agent": "DataPiler/%s (+https://github.com/Pt0l3my/DataPiler)" % version, "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28"}


def _shown(url: str) -> logbook.Own:
    """A URL for a log line: its host and path, never a query; a path outside [A-Za-z0-9/._-] as <text>."""
    u = urllib.parse.urlsplit(url)
    host = u.netloc if u.netloc in HOSTS else "<text>"
    path = u.path if _PATH_RX.fullmatch(u.path or "/") else "/<text>"
    return own(host + path)


def _refused(url: str, what: str) -> str:
    try:
        u = urllib.parse.urlsplit(url)
        scheme, host = u.scheme, (u.hostname or "")
    except ValueError:
        scheme, host = "", ""
    if scheme != "https":
        return "GitHub sent the %s to an address that is not https, which DataPiler does not fetch from." % what
    if host in HOSTS:
        return ("GitHub sent the %s to an address on %s that DataPiler does not fetch from (a port, a user or a "
                "fragment)." % (what, host))
    shown = host if _HOST_RX.fullmatch(host) else "<text>"
    return "GitHub sent the %s to %s, which DataPiler does not fetch from." % (what, shown)


def _request(fetch: Fetch, url: str, *, max_bytes: int, headers: Mapping[str, str], what: str = "download",
             clock: Callable[[], float] = time.monotonic) -> Answer:
    """Every URL and every Location checked with allowed() before it is asked; at most REDIRECTS; https throughout.
    A 2xx whose Content-Length is past max_bytes is refused. Raises Stop, or OSError when there is no answer."""
    for _ in range(REDIRECTS + 1):
        if not allowed(url):
            raise Stop(_refused(url, what))
        t0 = clock()
        a = fetch(url, headers, TIMEOUT)
        log.info("GET %s - %s, %s s", _shown(url), int(a.status), logbook.n(max(0.0, clock() - t0)))
        if a.status in (301, 302, 303, 307, 308):
            loc = a.headers.get("location")
            a.close()
            if not isinstance(loc, str) or not loc.strip():
                raise Stop("GitHub answered %d without saying where to." % int(a.status))
            url = urllib.parse.urljoin(url, loc.strip())
            continue
        if 200 <= a.status < 300:
            cl = a.headers.get("content-length", "")
            if isinstance(cl, str) and cl.isdigit() and int(cl) > max_bytes:
                a.close()
                raise Stop("GitHub's answer is larger than DataPiler reads for it.")
        return a
    raise Stop("GitHub redirected the %s more than %d times - DataPiler stopped there." % (what, REDIRECTS))


def _read(a: Answer, max_bytes: int) -> bytes:
    data = bytearray()
    while True:
        b = a.body.read(min(CHUNK, max_bytes + 1 - len(data)))
        if not b:
            break
        data += b
        if len(data) > max_bytes:
            raise Stop("GitHub's answer is larger than DataPiler reads for it.")
    return bytes(data)


def _when(epoch: object) -> str | None:
    try:
        return time.strftime("%H:%M", time.localtime(int(str(epoch).strip())))
    except (ValueError, OverflowError, OSError):
        return None


# ---------------------------------------------------------------------------------------------------------- versions


def version_key(v: str) -> tuple[int, int, int, int] | None:
    """X.Y.Z, with an optional -suffix that sorts below the same X.Y.Z."""
    m = _THIS_RX.fullmatch(v or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1


def core(v: str) -> str | None:
    m = _THIS_RX.fullmatch(v or "")
    return "%s.%s.%s" % (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def parse_sha_file(data: bytes, zip_name: str, sha_name: str) -> tuple[str | None, str]:
    """The .sha256 file's first token, 64 hex; a second (after spaces and an optional *) must be the zip's name.
    (sha256, "") or (None, DataPiler's words)."""
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        return None, "%s is not a sha256 file (not text)" % sha_name
    toks = text.strip().split(None, 1)
    if not toks or not re.fullmatch(r"[0-9A-Fa-f]{64}", toks[0]):
        return None, "%s does not start with a sha256" % sha_name
    if len(toks) == 2:
        second = toks[1].strip()
        if second.startswith("*"):
            second = second[1:]
        if second != zip_name:
            return None, "%s names another file" % sha_name
    return toks[0].lower(), ""


# ---------------------------------------------------------------------------------------------------------- the notes


_INLINE_RX = re.compile(
    r"(?P<tick>`+)(?P<code>.+?)(?P=tick)"
    r"|!\[(?P<alt>[^\]\n]*)\]\((?P<src>[^)\s]*)(?:\s+\"[^\"\n]*\")?\)"
    r"|\[(?P<text>[^\]\n]+)\]\((?P<href>[^)\s]+)(?:\s+\"[^\"\n]*\")?\)"
    r"|<(?P<auto>https?://[^>\s]+)>"
    r"|\*\*(?P<b1>[^*\n]+?)\*\*|__(?P<b2>[^_\n]+?)__"
    r"|\*(?P<i1>[^*\s](?:[^*\n]*?[^*\s])?)\*"
    r"|(?<![A-Za-z0-9])_(?P<i2>[^_\s](?:[^_\n]*?[^_\s])?)_(?![A-Za-z0-9])")
_LI_RX = re.compile(r"^ {0,3}(?:([-*+])|(\d{1,9})[.)])(?:\s+(.*))?$")
_H_RX = re.compile(r"^ {0,3}(#{1,6})(?:\s+(.*?))?\s*$")
_RULE_RX = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_FENCE_RX = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_QUOTE_RX = re.compile(r"^ {0,3}>\s?(.*)$")


def _inline(text: str) -> list[dict]:
    """Flat parts: text, b, i, code, link (its text and its address as written) and image (its alt text)."""
    parts: list[dict] = []

    def add(t: str, v: str, **kw: str) -> None:
        if not v and t == "text":
            return
        if t == "text" and parts and parts[-1]["t"] == "text":
            parts[-1]["v"] += v
            return
        parts.append(dict({"t": t, "v": v}, **kw))

    pos = 0
    for m in _INLINE_RX.finditer(text):
        if m.start() > pos:
            add("text", text[pos:m.start()])
        if m.group("tick"):
            v = m.group("code")
            add("code", v[1:-1] if len(v) > 2 and v.startswith(" ") and v.endswith(" ") else v)
        elif m.group("src") is not None:
            add("image", m.group("alt"))
        elif m.group("text") is not None:
            add("link", m.group("text"), href=m.group("href"))
        elif m.group("auto"):
            add("link", m.group("auto"), href=m.group("auto"))
        elif m.group("b1") or m.group("b2"):
            add("b", m.group("b1") or m.group("b2"))
        else:
            add("i", m.group("i1") or m.group("i2"))
        pos = m.end()
    if pos < len(text):
        add("text", text[pos:])
    return parts


def notes_tree(body: object) -> tuple[list[dict], bool]:
    """The release's Markdown as blocks (§4.4): headings, paragraphs, list items, code; never HTML (raw HTML stays
    text). Cut at NOTES_MAX characters; the second value says whether it was."""
    if not isinstance(body, str) or not body.strip():
        return [], False
    cut = len(body) > NOTES_MAX
    lines = body[:NOTES_MAX].replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append({"k": "p", "parts": _inline(" ".join(s.strip() for s in para))})
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i].replace("\t", "    ")
        s = line.strip()
        fence = _FENCE_RX.match(line)
        if fence:
            flush()
            mark = fence.group(1)
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(mark[0] * len(mark)):
                code.append(lines[i])
                i += 1
            i += 1
            blocks.append({"k": "code", "v": "\n".join(code)})
            continue
        if not s:
            flush()
            i += 1
            continue
        if para and re.fullmatch(r" {0,3}(=+|-+)\s*", line):         # a setext heading
            level = 1 if s.startswith("=") else 2
            text = " ".join(x.strip() for x in para)
            para.clear()
            blocks.append({"k": "h", "level": level, "parts": _inline(text)})
            i += 1
            continue
        h = _H_RX.match(line)
        if h:
            flush()
            text = re.sub(r"\s+#+\s*$", "", h.group(2) or "")
            blocks.append({"k": "h", "level": len(h.group(1)), "parts": _inline(text)})
            i += 1
            continue
        if _RULE_RX.match(line):
            flush()
            i += 1
            continue
        li = _LI_RX.match(line)
        if li:
            flush()
            item = [li.group(3) or ""]
            i += 1
            while i < len(lines):
                nxt = lines[i].replace("\t", "    ")
                if not nxt.strip() or _LI_RX.match(nxt) or _H_RX.match(nxt) or _FENCE_RX.match(nxt) \
                        or _RULE_RX.match(nxt):
                    break
                item.append(nxt.strip())
                i += 1
            blocks.append({"k": "li", "n": int(li.group(2)) if li.group(2) else None,
                           "parts": _inline(" ".join(x for x in item if x))})
            continue
        if line.startswith("    ") and not para:
            code = []
            while i < len(lines):
                nxt = lines[i].replace("\t", "    ")
                if nxt.strip() and not nxt.startswith("    "):
                    break
                code.append(nxt[4:])
                i += 1
            while code and not code[-1].strip():
                code.pop()
            blocks.append({"k": "code", "v": "\n".join(code)})
            continue
        q = _QUOTE_RX.match(line)
        para.append(q.group(1) if q else line)
        i += 1
    flush()
    return blocks, cut


# ---------------------------------------------------------------------------------------------------------- the release


@dataclass
class Release:
    """What the check read from releases/latest, already checked."""

    version: str | None                 # X.Y.Z from the tag, or None when the tag is not a version
    published: str | None
    page: str | None
    notes: list[dict]
    notes_cut: bool
    zip_name: str | None = None
    zip_size: int | None = None
    zip_url: str | None = None
    sha_name: str | None = None
    sha_url: str | None = None
    digest: str | None = None
    why: str | None = None              # why it cannot be installed from the button

    def view(self) -> dict:
        return {"version": self.version, "published": self.published, "page": self.page,
                "zip": {"name": self.zip_name, "size": self.zip_size} if self.zip_name else None,
                "sha256_file": self.sha_name, "digest": self.digest is not None, "notes": self.notes,
                "notes_cut": self.notes_cut}


def parse_release(doc: object) -> Release:
    """releases/latest's answer: tag_name, published_at, html_url, body and assets[] (name, size,
    browser_download_url, digest). Raises Stop for an answer that is not a release."""
    if not isinstance(doc, dict):
        raise Stop("GitHub's answer was not the release DataPiler asked for.")
    pub = doc.get("published_at")
    m = _DATE_RX.fullmatch(pub) if isinstance(pub, str) else None
    published = m.group(1) if m else None
    page = doc.get("html_url")
    page = page if isinstance(page, str) and page.startswith(PAGE_PREFIX) and _PAGE_RX.fullmatch(page) else None
    notes, cut = notes_tree(doc.get("body"))
    tag = doc.get("tag_name")
    t = _TAG_RX.fullmatch(tag) if isinstance(tag, str) else None
    if not t:
        return Release(version=None, published=published, page=page, notes=notes, notes_cut=cut,
                       why="The latest release's tag is not a version DataPiler reads, so DataPiler will not install "
                           "it - the release page has it.")
    v = "%d.%d.%d" % (int(t.group(1)), int(t.group(2)), int(t.group(3)))
    if tag != "v" + v:
        return Release(version=None, published=published, page=page, notes=notes, notes_cut=cut,
                       why="The latest release's tag is not a version DataPiler reads, so DataPiler will not install "
                           "it - the release page has it.")
    rel = Release(version=v, published=published, page=page, notes=notes, notes_cut=cut)
    assets = doc.get("assets") if isinstance(doc.get("assets"), list) else []
    zip_name, sha_name = "DataPiler-%s.zip" % v, "DataPiler-%s.zip.sha256" % v
    by_name = {}
    for a in assets:
        if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"] in (zip_name, sha_name):
            by_name.setdefault(a["name"], a)
    z, s = by_name.get(zip_name), by_name.get(sha_name)
    if z is None:
        rel.why = "%s does not carry %s, so DataPiler will not install it - the release page has it." % (v, zip_name)
        return rel
    rel.zip_name = zip_name
    size = z.get("size")
    rel.zip_size = size if type(size) is int else None
    if s is None:
        rel.why = ("%s does not carry a checksum file, so DataPiler will not install it - the release page has it."
                   % v)
        return rel
    rel.sha_name = sha_name
    for a, name in ((z, zip_name), (s, sha_name)):
        if a.get("browser_download_url") != ASSET_PREFIX + "v%s/%s" % (v, name):
            rel.why = ("%s's download address is not this repository's release file, so DataPiler will not fetch it."
                       % name)
            return rel
    rel.zip_url = z["browser_download_url"]
    rel.sha_url = s["browser_download_url"]
    if type(size) is not int or not 1 <= size <= ZIP_MAX:
        rel.why = "%s's size, as the release states it, is not one DataPiler downloads." % zip_name
        return rel
    digest = z.get("digest")
    if digest is not None:
        d = _DIGEST_RX.fullmatch(digest) if isinstance(digest, str) else None
        if not d:
            rel.why = "GitHub's digest for %s is not a sha256, so DataPiler will not install it." % zip_name
            return rel
        rel.digest = d.group(1)
    return rel


# ---------------------------------------------------------------------------------------------------------- the updater


@dataclass
class _Staged:
    zip: Path
    sha256: str
    size: int
    version: str
    manifest: dict[str, str] = field(default_factory=dict)


class Updater:
    """The pop-up's back end. Nothing runs at construction: every call follows a press (post)."""

    def __init__(self, *, root: Path, version: str, port: Callable[[], int], busy: Callable[[], dict | None],
                 request_exit: Callable[[], None], fetch: Fetch | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        """fetch None: real_fetch(), made at the first press."""
        self.root = Path(root)
        self.version = version
        self._port = port
        self._busy = busy
        self._exit = request_exit
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.RLock()
        self._state = "idle"
        self._rel: Release | None = None
        self._why: str | None = None
        self._failed: dict | None = None
        self._progress: dict | None = None
        self._checks: list[dict] = []
        self._plan: dict | None = None
        self._checked_at: str | None = None
        self._cache: tuple[float, Release] | None = None
        self._gen = 0
        self._thread: threading.Thread | None = None
        self._poll = clock()
        self._staged: _Staged | None = None
        self._result: dict | None = None
        self._closed = False
        self._leaving = False

    # -------------------------------------------------------------------------------------------- the routes

    def view(self) -> dict:
        with self._lock:
            return {"state": self._state, "this": self.version, "checked_at": self._checked_at,
                    "latest": self._rel.view() if self._rel is not None else None, "why": self._why,
                    "progress": dict(self._progress) if self._progress else None,
                    "checks": [dict(c) for c in self._checks], "plan": dict(self._plan) if self._plan else None,
                    "failed": dict(self._failed) if self._failed else None}

    def get(self) -> dict:
        """GET /api/update: the view; notes the poll (a download stops when the pop-up has not read this for
        POLL_GONE seconds)."""
        with self._lock:
            self._poll = self._clock()
        return self.view()

    def post(self, body: dict) -> tuple[int, dict, Callable[[], None] | None]:
        """POST /api/update: {"action": "check", "fresh": false} / download / install / cancel."""
        if not isinstance(body, dict):
            return 400, {"error": "the body must be an object"}, None
        extra = sorted(k for k in body if k not in ("action", "fresh"))
        if extra:
            return 400, {"error": "unknown key - the body holds action, and fresh with check"}, None
        action = body.get("action")
        if action not in ACTIONS:
            return 400, {"error": "action must be check, download, install or cancel"}, None
        if "fresh" in body and (action != "check" or not isinstance(body["fresh"], bool)):
            return 400, {"error": "fresh goes with check only, as true or false"}, None
        wait: threading.Thread | None = None
        with self._lock:
            if self._closed or self._leaving:
                return 400, {"error": "DataPiler is stopping"}, None
            self._poll = self._clock()
            if self._fetch is None and action in ("check", "download"):
                self._fetch = real_fetch()
            if action == "check":
                self._check(bool(body.get("fresh", False)))
            elif action == "download":
                if self._state != "newer":
                    return 400, {"error": "Download needs a newer release that this copy can install - press "
                                          "Check again"}, None
                self._download()
            elif action == "install":
                if self._state != "ready":
                    return 400, {"error": "Install and restart needs a verified download - press Download "
                                          "first"}, None
                answer, after = self._install()
                return 200, answer, after
            else:
                wait = self._cancel()
        if wait is not None:
            wait.join(2.0)
        return 200, self.view(), None

    def result(self) -> dict:
        """GET /api/update-result: once after an update came back (came_back matched the nonce), else
        {"state": null}."""
        with self._lock:
            r, self._result = self._result, None
        return r if r is not None else {"state": None}

    def came_back(self, pending: "install.Pending | None", check: "install.Check") -> None:
        """datapiler.py, once the page is up: keeps result.json's content when its nonce is pending's."""
        if pending is None:
            return
        r = install.read_result(self.root, pending.nonce)
        if r is None:
            r = {"state": "failed", "from": pending.from_version, "to": pending.to_version, "stage": None,
                 "text": "The update did not complete - logs\\update.log has why.", "counts": None,
                 "backup": None, "restored": None, "log": "logs\\update.log"}
        r["check"] = {"files": check.files, "differ": len(check.differ) + len(check.missing),
                      "manifest": check.manifest}
        with self._lock:
            self._result = r

    def close(self) -> None:
        """Stops a check or a download, and removes its .part. A verified download stays."""
        with self._lock:
            self._closed = True
            self._gen += 1
            t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(3.0)
        self._remove_parts()

    def wait(self, timeout: float = 10.0) -> bool:
        """For tests and the stop: waits for a check or a download thread to end."""
        with self._lock:
            t = self._thread
        if t is None or t is threading.current_thread():
            return True
        t.join(timeout)
        return not t.is_alive()

    # -------------------------------------------------------------------------------------------- the presses
    # Reached only from post (S27; test_update_static).

    def _check(self, fresh: bool) -> None:
        if self._state in ("checking", "downloading", "ready"):
            return
        now = self._clock()
        if not fresh and self._cache is not None and 0 <= now - self._cache[0] < CACHE_SECS:
            self._apply(self._cache[1])
            return
        self._gen += 1
        gen = self._gen
        self._reset("checking")
        self._start(threading.Thread(target=self._run_check, args=(gen, self._fetch), name="update-check",
                                     daemon=True))

    def _download(self) -> None:
        rel = self._rel
        self._gen += 1
        gen = self._gen
        prev = self._thread
        self._reset("downloading")
        self._progress = {"done": 0, "of": rel.zip_size, "rate": 0}
        self._start(threading.Thread(target=self._run_download, args=(gen, self._fetch, rel, prev),
                                     name="update-download", daemon=True))

    def _install(self) -> tuple[dict, Callable[[], None] | None]:
        st = self._staged
        if self._busy():
            self._failed = {"stage": "install", "text": BUSY, "kept": True}
            return self.view(), None
        if not (self.root / install.MANIFEST).is_file():
            self._failed = {"stage": "install", "text": NOT_UNPACKED, "kept": True}
            return self.view(), None
        try:
            size = os.path.getsize(st.zip)
            sha = fileio.sha256_file(st.zip) if size == st.size else None
        except OSError:
            sha = None
        if sha != st.sha256:
            log.warn("download refused at %s: %s", own("install"), own("the zip changed since it was checked"))
            self._discard()
            self._reset("failed")
            self._failed = {"stage": "install", "text": "The download changed since it was checked - it was removed. "
                                                        "Nothing was changed; press Check again to fetch it anew.",
                            "kept": False}
            return self.view(), None
        dest = st.zip.parent / install.HELPER
        try:
            with zipfile.ZipFile(st.zip) as zf:
                zi = zf.getinfo("DataPiler/" + install.HELPER)
                if zi.file_size > HELPER_MAX:
                    raise ValueError("too large")
                data = zf.read(zi)
            if hashlib.sha256(data).hexdigest() != st.manifest.get(install.HELPER):
                raise ValueError("not the manifest's")
            fileio.write_atomic(dest, data)
            if fileio.sha256_file(dest) != st.manifest.get(install.HELPER):
                raise ValueError("did not land")
            port = int(self._port() or 0)
            install.write_pending(self.root, from_version=core(self.version) or "0.0.0", to_version=st.version,
                                  zip_rel="update/%s/%s" % (st.version, st.zip.name), zip_sha256=st.sha256,
                                  zip_size=st.size, port=port)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
            log.warn("download refused at %s: %s", own("install"), logbook.why(e))
            self._discard()
            self._reset("failed")
            self._failed = {"stage": "install", "text": "The update helper could not be taken from the download - it "
                                                        "was removed. Nothing was changed.", "kept": False}
            return self.view(), None
        self._leaving = True
        log.info("update requested: %s - stopping (exit code 75)", own(st.version))
        return {"ok": True, "state": "restarting", "to": st.version}, self._exit

    def _cancel(self) -> threading.Thread | None:
        """Stops a check (its answer dropped) or a download (its part removed); in the ready state, discards the
        download. Elsewhere it does nothing."""
        t = self._thread
        if self._state == "checking":
            self._gen += 1
            self._reset("idle")
            self._rel = None
            return t
        if self._state == "downloading":
            self._gen += 1
            self._reset("newer")
            return t
        if self._state == "ready":
            self._discard()
            self._reset("newer")
            return None
        return None

    # -------------------------------------------------------------------------------------------- the work

    def _start(self, t: threading.Thread) -> None:
        self._thread = t
        t.start()

    def _reset(self, state: str) -> None:
        self._state = state
        self._failed = None
        self._why = None
        self._progress = None
        self._checks = []
        self._plan = None

    def _apply(self, rel: Release) -> None:
        """A release read (from GitHub or the cache): its state against this version."""
        self._reset("idle")
        self._rel = rel
        this = version_key(self.version)
        if rel.version is None:
            self._state, self._why = "not_installable", rel.why
            return
        latest = version_key(rel.version)
        if this is not None and latest == this:
            self._state = "up_to_date"
        elif this is not None and latest < this:
            self._state = "older"
        elif rel.why:
            self._state, self._why = "not_installable", rel.why
        elif not (self.root / install.MANIFEST).is_file():
            self._state, self._why = "not_installable", NOT_UNPACKED
        else:
            self._state = "newer"

    def _run_check(self, gen: int, fetch: Fetch) -> None:
        rel = None
        state, text = "failed", None
        try:
            a = _request(fetch, LATEST, max_bytes=API_MAX, headers=headers_for(self.version, API_ACCEPT),
                         what="check")
            try:
                remaining = a.headers.get("x-ratelimit-remaining")
                if a.status == 404:
                    state = "none"
                elif a.status in (403, 429) and isinstance(remaining, str) and remaining.strip() == "0":
                    at = _when(a.headers.get("x-ratelimit-reset"))
                    text = ("GitHub's limit for checks from this address is reached (60 an hour without an "
                            "account)." + (" It resets at %s." % at if at else ""))
                elif a.status != 200:
                    text = "GitHub answered %d." % int(a.status)
                else:
                    try:
                        doc = json.loads(_read(a, API_MAX).decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        raise Stop("GitHub's answer was not the release DataPiler asked for.") from None
                    rel = parse_release(doc)
            finally:
                a.close()
        except Stop as e:
            text = e.text
        except OSError:
            text = NO_ANSWER
        except Exception as e:
            text = "The check failed (%s)." % logbook.why(e)
        with self._lock:
            if gen != self._gen:
                return
            if rel is not None:
                self._cache = (self._clock(), rel)
                self._checked_at = time.strftime("%H:%M", time.localtime(self._clock()))
                self._apply(rel)
                log.info("latest release %s (this is %s)", own(rel.version or "not a version"),
                         own(self.version) if version_key(self.version) else own("not a version"))
                return
            self._rel = None
            if state == "none":
                self._reset("none")
                self._checked_at = time.strftime("%H:%M", time.localtime(self._clock()))
                log.info("latest release: none published yet")
                return
            self._reset("failed")
            self._failed = {"stage": "check", "text": (text or NO_ANSWER) + NOTHING, "kept": False}
            log.warn("the check did not finish: %s", own(text or NO_ANSWER))

    def _gone(self, gen: int) -> None:
        """Between chunks: a cancel, a stop, or the pop-up gone for POLL_GONE seconds ends the download."""
        with self._lock:
            if gen != self._gen:
                raise _Cancelled("cancel")
            if self._clock() - self._poll > POLL_GONE:
                raise _Cancelled("gone")

    def _run_download(self, gen: int, fetch: Fetch, rel: Release, prev: threading.Thread | None) -> None:
        if prev is not None and prev.is_alive():
            prev.join(TIMEOUT + 5)          # a cancelled download first removes its own part
        folder = self.root / install.UPDATE_DIR / rel.version
        part = folder / (rel.zip_name + ".part")
        final = folder / rel.zip_name
        checks: list[dict] = []
        try:
            self._gone(gen)
            folder.mkdir(parents=True, exist_ok=True)
            for old in (part, final):
                if os.path.lexists(old):
                    os.remove(old)
            a = _request(fetch, rel.sha_url, max_bytes=SHA_MAX, headers=headers_for(self.version, ASSET_ACCEPT))
            try:
                if a.status != 200:
                    raise Stop("GitHub answered %d for %s." % (int(a.status), rel.sha_name))
                sha_text = _read(a, SHA_MAX)
            finally:
                a.close()
            got, size = self._stream(gen, fetch, rel, part)
            checks, arch = self._prove(rel, part, sha_text, got, size)
            if arch is None:
                bad = checks[-1]
                with self._lock:
                    if gen != self._gen:
                        raise _Cancelled("cancel")
                    self._reset("failed")
                    self._checks = [{k: v for k, v in c.items() if k != "own"} for c in checks]
                    self._failed = {"stage": "verify", "text": "The download did not pass its checks (%s) - it was "
                                                               "removed. Nothing was changed." % bad["text"],
                                    "kept": False}
                log.warn("download refused at %s: %s", own(bad["id"]),
                         own(bad["text"]) if bad.get("own") else bad["text"])
                self._remove(part)
                return
            os.replace(part, final)
            old = install.manifest_here(self.root)
            pl = install.helper(install.APP).plan(self.root, arch.manifest, old)
            plan = {"write": len(pl.write), "add": len(pl.add), "remove": len(pl.remove), "same": len(pl.same),
                    "edited": len(pl.edited), "files": arch.files,
                    "libs": arch.lock_sha256 != install.lock_sha256(self.root)}
            with self._lock:
                if gen != self._gen:
                    self._remove(final)
                    return
                self._reset("ready")
                self._checks = [{k: v for k, v in c.items() if k != "own"} for c in checks]
                self._plan = plan
                self._staged = _Staged(zip=final, sha256=got, size=size, version=rel.version,
                                       manifest=dict(arch.manifest))
            log.info("download verified: %s, %s MiB", own(rel.zip_name), logbook.n(size / (1024 * 1024)))
        except _Cancelled as c:
            self._remove(part)
            if c.why == "gone":
                with self._lock:
                    if gen == self._gen:
                        self._reset("failed")
                        self._failed = {"stage": "download", "text": "The download stopped because the Update "
                                                                     "pop-up was closed. Nothing was kept or changed.",
                                        "kept": False}
                log.info("download stopped: the pop-up was closed")
            else:
                log.info("download cancelled")
        except Exception as e:
            self._remove(part)
            if isinstance(e, Stop):
                text = e.text
            elif isinstance(e, OSError) and not isinstance(e, FileNotFoundError):
                text = NO_ANSWER
            else:
                text = "The download failed (%s)." % logbook.why(e)
            with self._lock:
                if gen != self._gen:
                    return
                self._reset("failed")
                self._failed = {"stage": "download", "text": text + " The part file was removed; nothing was changed.",
                                "kept": False}
            log.warn("the download did not finish: %s", own(text))

    def _stream(self, gen: int, fetch: Fetch, rel: Release, part: Path) -> tuple[str, int]:
        a = _request(fetch, rel.zip_url, max_bytes=rel.zip_size, headers=headers_for(self.version, ASSET_ACCEPT))
        h = hashlib.sha256()
        done = 0
        t0 = self._clock()
        try:
            if a.status != 200:
                raise Stop("GitHub answered %d for %s." % (int(a.status), rel.zip_name))
            with open(part, "wb") as f:
                while True:
                    self._gone(gen)
                    b = a.body.read(CHUNK)
                    if not b:
                        break
                    done += len(b)
                    if done > rel.zip_size:
                        raise Stop("GitHub sent more bytes than the release states for %s - the download was "
                                   "refused." % rel.zip_name)
                    h.update(b)
                    f.write(b)
                    secs = self._clock() - t0
                    with self._lock:
                        if gen == self._gen:
                            self._progress = {"done": done, "of": rel.zip_size,
                                              "rate": int(done / secs) if secs > 0 else 0}
        finally:
            a.close()
        return h.hexdigest(), done

    def _prove(self, rel: Release, part: Path, sha_text: bytes, got: str, size: int) -> tuple[list[dict], object]:
        """§4.3, in order: each a line of checks; the first ✗ ends them (the Archive is then None)."""
        checks: list[dict] = []

        def line(cid: str, ok: object, text: str, mine: bool = True) -> None:
            checks.append({"id": cid, "ok": ok, "text": text, "own": mine})

        if size != rel.zip_size:
            line("size", False, "%s bytes, but the release states %s" % (logbook.n(size), logbook.n(rel.zip_size)))
            return checks, None
        line("size", True, "%s bytes - the size the release states" % logbook.n(size))
        sha, problem = parse_sha_file(sha_text, rel.zip_name, rel.sha_name)
        if sha is None:
            line("sha256", False, problem)
            return checks, None
        if sha != got:
            line("sha256", False, "the sha256 does not match %s" % rel.sha_name)
            return checks, None
        line("sha256", True, "sha256 matches %s (%s…%s)" % (rel.sha_name, got[:4], got[-4:]))
        if rel.digest is None:
            line("digest", "warn", "GitHub states no digest for this file - the published .sha256 alone")
        elif rel.digest != got:
            line("digest", False, "but GitHub's digest for the file differs")
            return checks, None
        else:
            line("digest", True, "and matches GitHub's digest for the file")
        h = install.helper(install.APP)
        try:
            arch = h.check_archive(part, version=rel.version)
        except h.Refused as e:
            if e.stage == "shape":
                line("shape", False, e.text, mine=False)
            else:
                line("shape", True, "one folder, DataPiler - nothing outside it, no links")
                line("manifest", False, e.text, mine=False)
            return checks, None
        line("shape", True, "one folder, DataPiler, %s files - nothing outside it, no links" % logbook.n(arch.files))
        line("manifest", True, "its manifest: every file's sha256 checked; version inside: %s" % arch.version)
        return checks, arch

    def _discard(self) -> None:
        st, self._staged = self._staged, None
        if st is not None:
            self._remove(st.zip)
            self._remove(st.zip.parent / install.HELPER)
            try:
                st.zip.parent.rmdir()
            except OSError:
                pass

    def _remove(self, p: Path) -> None:
        try:
            if os.path.lexists(p):
                os.remove(p)
        except OSError as e:
            log.warn("a file in update/ could not be removed: %s", logbook.why(e))

    def _remove_parts(self) -> None:
        folder = self.root / install.UPDATE_DIR
        try:
            for p in folder.glob("*/*.part"):
                self._remove(p)
        except OSError:
            pass
