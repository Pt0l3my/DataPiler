"""datapiler/update.py (build plan 0.2 §4.1 to §4.4, §7.1): the host allowlist on URLs and redirect chains, the
headers, each state from invented releases, the cache, the download and its proofs, Install, and the notes tree.
GitHub is a fake Fetch serving invented releases from memory; real_fetch is patched to fail for the whole module,
so no test touches the network."""

import _repo  # noqa: F401

import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from datapiler import install, logbook, update
from datapiler.update import ASSET_PREFIX, LATEST, PAGE_PREFIX, Answer
from test_archive import invented_app, manifest_of, release_zip, sha

ASSET_HOST = "https://release-assets.githubusercontent.com/github-production-release-asset/1/"
_patch = None


def setUpModule():
    global _patch

    def refused():
        raise AssertionError("a test reached real_fetch")

    _patch = mock.patch.object(update, "real_fetch", refused)
    _patch.start()


def tearDownModule():
    _patch.stop()


class Body(io.BytesIO):
    """A body that can run a hook before each read (to cancel, or to move the clock)."""

    def __init__(self, data, hook=None):
        super().__init__(data)
        self.hook = hook
        self.reads = 0

    def read(self, n=-1):
        self.reads += 1
        if self.hook is not None:
            self.hook(self.reads)
        return super().read(n)


class FakeGitHub:
    """url -> (status, headers, body), an exception to raise, or a callable giving either."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        r = self.routes.get(url)
        if callable(r) and not isinstance(r, BaseException):
            r = r()
        if r is None:
            return Answer(404, {}, io.BytesIO(b""))
        if isinstance(r, BaseException):
            raise r
        status, hdrs, body = r
        return Answer(status, {k.lower(): v for k, v in hdrs.items()},
                      body if hasattr(body, "read") else io.BytesIO(body))

    def urls(self):
        return [c[0] for c in self.calls]


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def lines_since(seq):
    got, _ = logbook.lines_after(seq, limit=200)
    return [l["level"] + " " + l["src"] + " " + l["msg"] for l in got]


class Base(unittest.TestCase):
    VERSION = "0.2.0"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.old = invented_app("0.2.0")
        for rel, data in self.old.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.root / "manifest.sha256").write_bytes(manifest_of(self.old))
        self.gh = FakeGitHub()
        self.busy = None
        self.exits = []
        self.clock = Clock()
        self.u = self.updater()

    def tearDown(self):
        self.u.close()
        self.tmp.cleanup()

    def updater(self, version=None, clock=None):
        return update.Updater(root=self.root, version=version or self.VERSION, port=lambda: 22777,
                              busy=lambda: self.busy, request_exit=lambda: self.exits.append(1), fetch=self.gh,
                              clock=clock or self.clock)

    def release(self, version="0.3.0", files=None, *, digest=True, sha_text=None, zip_bytes=None, body=None,
                assets=None, **doc_over):
        """Serves an invented release as releases/latest, with its zip behind a redirect to the asset host."""
        files = invented_app(version, **{"requirements.lock": b"# datapiler-lock/1\n# newer\n"}) if files is None \
            else files
        if zip_bytes is None:
            z = release_zip(Path(self.tmp.name) / ("built-%s.zip" % version), files)
            zip_bytes = z.read_bytes()
        name = "DataPiler-%s.zip" % version
        h = sha(zip_bytes)
        zip_url = ASSET_PREFIX + "v%s/%s" % (version, name)
        sha_url = zip_url + ".sha256"
        a_zip = {"name": name, "size": len(zip_bytes), "browser_download_url": zip_url}
        if digest:
            a_zip["digest"] = "sha256:" + h
        a_sha = {"name": name + ".sha256", "size": 90, "browser_download_url": sha_url}
        doc = {"tag_name": "v" + version, "published_at": "2026-11-20T10:00:00Z",
               "html_url": PAGE_PREFIX + "tag/v" + version, "body": "## What's new\n- invented",
               "assets": assets if assets is not None else [a_zip, a_sha]}
        doc.update(doc_over)
        self.gh.routes[LATEST] = (200, {}, json.dumps(doc).encode())
        self.gh.routes[zip_url] = (302, {"Location": ASSET_HOST + "zip?sp=r&sig=PLANTEDSECRET"}, b"")
        self.gh.routes[ASSET_HOST + "zip?sp=r&sig=PLANTEDSECRET"] = lambda: (200, {}, body() if callable(body)
                                                                             else (body or zip_bytes))
        self.gh.routes[sha_url] = (302, {"Location": ASSET_HOST + "sha?sp=r"}, b"")
        self.gh.routes[ASSET_HOST + "sha?sp=r"] = (200, {}, (sha_text if sha_text is not None
                                                              else "%s  %s\n" % (h, name)).encode())
        return zip_bytes

    def post(self, **body):
        code, answer, after = self.u.post(body)
        return code, answer, after

    def check(self, fresh=False):
        code, answer, _ = self.post(action="check", fresh=fresh)
        self.assertEqual(code, 200, answer)
        self.assertTrue(self.u.wait())
        return self.u.get()

    def download(self):
        v = self.check()
        self.assertEqual(v["state"], "newer", v)
        code, answer, _ = self.post(action="download")
        self.assertEqual(code, 200, answer)
        self.assertTrue(self.u.wait())
        return self.u.get()

    def update_files(self):
        return sorted(p.relative_to(self.root).as_posix() for p in (self.root / "update").rglob("*") if p.is_file()) \
            if (self.root / "update").exists() else []


# ---------------------------------------------------------------------------------------------------------- hosts


class Allowed(unittest.TestCase):
    def test_each_host(self):
        for host in update.HOSTS:
            self.assertTrue(update.allowed("https://%s/some/path?q=1" % host), host)

    def test_refused(self):
        at = "@"        # written apart, so the repository's e-mail rule does not read a user and a host as one
        for url in ("http://github.com/x", "https://github.com:443/x", "https://user" + at + "github.com/x",
                    "https://user:pw" + at + "api.github.com/x", "https://api.github.com.example.invalid/x",
                    "https://example.invalid/github.com", "https://xgithub.com/x", "https://github.com/x#frag",
                    "https://github.com/x#", "https://GITHUB.COM/x", "https://github.com\\" + at + "example.invalid/",
                    "https://github.com/a b", "ftp://github.com/x", "file:///etc/passwd", "//github.com/x", "",
                    "https://github.com./x", "https://[::1]/x", "https://127.0.0.1/x"):
            self.assertFalse(update.allowed(url), url)
        self.assertFalse(update.allowed(None))


class Redirects(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()

    def req(self, url):
        return update._request(self.gh, url, max_bytes=100, headers=update.headers_for("0.2.0", "x"))

    def test_allowed_to_allowed(self):
        self.gh.routes["https://github.com/a"] = (302, {"Location": "https://objects.githubusercontent.com/b"}, b"")
        self.gh.routes["https://objects.githubusercontent.com/b"] = (301, {"Location": "/c"}, b"")
        self.gh.routes["https://objects.githubusercontent.com/c"] = (200, {}, b"ok")
        a = self.req("https://github.com/a")
        self.assertEqual((a.status, a.body.read()), (200, b"ok"))
        self.assertEqual(self.gh.urls(), ["https://github.com/a", "https://objects.githubusercontent.com/b",
                                          "https://objects.githubusercontent.com/c"])

    def test_to_a_foreign_host(self):
        self.gh.routes["https://github.com/a"] = (302, {"Location": "https://cdn.example.invalid/b"}, b"")
        with self.assertRaises(update.Stop) as cm:
            self.req("https://github.com/a")
        self.assertEqual(cm.exception.text, "GitHub sent the download to cdn.example.invalid, which DataPiler does "
                                            "not fetch from.")
        self.assertEqual(self.gh.urls(), ["https://github.com/a"])

    def test_to_a_host_that_is_not_a_host_name(self):
        self.gh.routes["https://github.com/a"] = (302, {"Location": "https://EVIL_host%2F/b"}, b"")
        with self.assertRaises(update.Stop) as cm:
            self.req("https://github.com/a")
        self.assertIn("<text>", cm.exception.text)

    def test_to_http(self):
        self.gh.routes["https://github.com/a"] = (307, {"Location": "http://github.com/b"}, b"")
        with self.assertRaises(update.Stop) as cm:
            self.req("https://github.com/a")
        self.assertIn("not https", cm.exception.text)
        self.assertEqual(len(self.gh.calls), 1)

    def test_to_a_port(self):
        self.gh.routes["https://github.com/a"] = (302, {"Location": "https://github.com:8443/b"}, b"")
        with self.assertRaises(update.Stop):
            self.req("https://github.com/a")
        self.assertEqual(len(self.gh.calls), 1)

    def test_more_than_five(self):
        for i in range(10):
            self.gh.routes["https://github.com/%d" % i] = (302, {"Location": "https://github.com/%d" % (i + 1)}, b"")
        with self.assertRaises(update.Stop) as cm:
            self.req("https://github.com/0")
        self.assertIn("more than 5 times", cm.exception.text)
        self.assertEqual(len(self.gh.calls), 6)

    def test_no_location(self):
        self.gh.routes["https://github.com/a"] = (302, {}, b"")
        with self.assertRaises(update.Stop):
            self.req("https://github.com/a")

    def test_a_length_past_the_limit(self):
        self.gh.routes["https://github.com/a"] = (200, {"Content-Length": "101"}, b"x" * 101)
        with self.assertRaises(update.Stop):
            self.req("https://github.com/a")

    def test_the_first_url_is_checked_too(self):
        with self.assertRaises(update.Stop):
            self.req("https://example.invalid/a")
        self.assertEqual(self.gh.calls, [])


class Headers(Base):
    def test_exactly_these(self):
        self.release()
        self.download()
        api = [c for c in self.gh.calls if c[0] == LATEST][0]
        self.assertEqual(api[1], {"User-Agent": "DataPiler/0.2.0 (+https://github.com/Pt0l3my/DataPiler)",
                                  "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        self.assertEqual(api[2], update.TIMEOUT)
        for url, headers, _ in self.gh.calls:
            low = {k.lower() for k in headers}
            for bad in ("authorization", "cookie", "referer"):
                self.assertNotIn(bad, low)
            if url != LATEST:
                self.assertEqual(headers["Accept"], "application/octet-stream")


# ---------------------------------------------------------------------------------------------------------- states


class States(Base):
    def test_nothing_runs_at_construction(self):
        u = update.Updater(root=self.root, version="0.2.0", port=lambda: 1, busy=lambda: None,
                           request_exit=lambda: None)
        v = u.get()
        self.assertEqual(v["state"], "idle")
        self.assertEqual(v["this"], "0.2.0")
        self.assertIsNone(v["latest"])
        self.assertEqual(u.result(), {"state": None})
        u.close()

    def test_newer(self):
        z = self.release()
        seq = logbook.lines_after(0, limit=0)[1]
        v = self.check()
        self.assertEqual(v["state"], "newer")
        self.assertRegex(v["checked_at"], r"^\d\d:\d\d$")
        self.assertEqual(v["latest"], {
            "version": "0.3.0", "published": "2026-11-20", "page": PAGE_PREFIX + "tag/v0.3.0",
            "zip": {"name": "DataPiler-0.3.0.zip", "size": len(z)}, "sha256_file": "DataPiler-0.3.0.zip.sha256",
            "digest": True, "notes": [{"k": "h", "level": 2, "parts": [{"t": "text", "v": "What's new"}]},
                                      {"k": "li", "n": None, "parts": [{"t": "text", "v": "invented"}]}],
            "notes_cut": False})
        said = lines_since(seq)
        self.assertIn("INFO update latest release 0.3.0 (this is 0.2.0)", said)
        self.assertTrue(any(l.startswith("INFO update GET api.github.com/repos/Pt0l3my/DataPiler/releases/latest - "
                                         "200, ") for l in said), said)

    def test_older(self):
        self.release("0.1.9")
        self.assertEqual(self.check()["state"], "older")

    def test_the_same(self):
        self.release("0.2.0")
        self.assertEqual(self.check()["state"], "up_to_date")

    def test_a_suffix_sorts_below_its_release(self):
        self.u = self.updater(version="0.3.0-dev")
        self.release("0.3.0")
        self.assertEqual(self.check()["state"], "newer")
        self.u = self.updater(version="0.3.1-dev")
        self.assertEqual(self.check()["state"], "older")

    def test_none_published(self):
        self.gh.routes[LATEST] = (404, {}, b'{"message": "Not Found"}')
        v = self.check()
        self.assertEqual(v["state"], "none")
        self.assertIsNone(v["failed"])

    def failed(self, route, words):
        self.gh.routes[LATEST] = route
        v = self.check()
        self.assertEqual(v["state"], "failed")
        self.assertEqual(v["failed"]["stage"], "check")
        self.assertEqual(v["failed"]["text"], words + " Nothing was downloaded or changed.")
        self.assertEqual(self.update_files(), [])
        return v

    def test_rate_limited(self):
        reset = int(time.time()) + 1800
        at = time.strftime("%H:%M", time.localtime(reset))
        for status in (403, 429):
            with self.subTest(status=status):
                self.failed((status, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}, b"{}"),
                            "GitHub's limit for checks from this address is reached (60 an hour without an "
                            "account). It resets at %s." % at)

    def test_rate_limited_without_a_reset(self):
        self.failed((403, {"X-RateLimit-Remaining": "0"}, b"{}"), "GitHub's limit for checks from this address is "
                                                                   "reached (60 an hour without an account).")

    def test_a_403_that_is_not_the_limit(self):
        self.failed((403, {"X-RateLimit-Remaining": "12"}, b"{}"), "GitHub answered 403.")

    def test_another_status(self):
        self.failed((500, {}, b""), "GitHub answered 500.")

    def test_no_answer(self):
        self.failed(ConnectionRefusedError(111, "refused"), update.NO_ANSWER)

    def test_a_timeout(self):
        self.failed(TimeoutError("timed out"), update.NO_ANSWER)

    def test_not_json(self):
        self.failed((200, {}, b"<html>"), "GitHub's answer was not the release DataPiler asked for.")

    def not_installable(self, words, **kw):
        self.release(**kw)
        v = self.check()
        self.assertEqual(v["state"], "not_installable", v)
        self.assertEqual(v["why"], words)
        return v

    def test_no_zip(self):
        self.not_installable("0.3.0 does not carry DataPiler-0.3.0.zip, so DataPiler will not install it - the "
                             "release page has it.", assets=[])

    def test_no_sha256(self):
        self.release()
        doc = json.loads(self.gh.routes[LATEST][2])
        doc["assets"] = doc["assets"][:1]
        self.gh.routes[LATEST] = (200, {}, json.dumps(doc).encode())
        v = self.check()
        self.assertEqual(v["state"], "not_installable")
        self.assertEqual(v["why"], "0.3.0 does not carry a checksum file, so DataPiler will not install it - the "
                                   "release page has it.")

    def test_a_bad_tag(self):
        for tag in ("0.3.0", "v0.3", "v0.3.0-beta", "latest", "v00.3.0"):
            with self.subTest(tag=tag):
                v = self.not_installable("The latest release's tag is not a version DataPiler reads, so DataPiler "
                                         "will not install it - the release page has it.", tag_name=tag)
                self.assertIsNone(v["latest"]["version"])

    def test_a_wrong_download_url(self):
        self.release()
        doc = json.loads(self.gh.routes[LATEST][2])
        doc["assets"][0]["browser_download_url"] = "https://github.com/someone-else/DataPiler/releases/download/" \
                                                   "v0.3.0/DataPiler-0.3.0.zip"
        self.gh.routes[LATEST] = (200, {}, json.dumps(doc).encode())
        v = self.check()
        self.assertEqual(v["state"], "not_installable")
        self.assertIn("is not this repository's release file", v["why"])

    def test_a_foreign_page(self):
        for page in ("https://github.com/someone-else/DataPiler/releases/tag/v0.3.0",
                     "https://example.invalid/Pt0l3my/DataPiler/releases/", "javascript:alert(1)", 7):
            with self.subTest(page=page):
                self.release(html_url=page)
                v = self.check(fresh=True)
                self.assertEqual(v["state"], "newer")
                self.assertIsNone(v["latest"]["page"])

    def test_a_size_out_of_bounds(self):
        self.release()
        doc = json.loads(self.gh.routes[LATEST][2])
        doc["assets"][0]["size"] = update.ZIP_MAX + 1
        self.gh.routes[LATEST] = (200, {}, json.dumps(doc).encode())
        self.assertEqual(self.check()["state"], "not_installable")

    def test_a_digest_that_is_not_a_sha256(self):
        self.release()
        doc = json.loads(self.gh.routes[LATEST][2])
        doc["assets"][0]["digest"] = "md5:abc"
        self.gh.routes[LATEST] = (200, {}, json.dumps(doc).encode())
        self.assertEqual(self.check()["state"], "not_installable")

    def test_this_copy_was_not_unpacked_from_a_release(self):
        os.remove(self.root / "manifest.sha256")
        v = self.not_installable(update.NOT_UNPACKED)
        self.assertEqual(v["latest"]["version"], "0.3.0")

    def test_a_bad_body(self):
        for body in ({"action": "download", "x": 1}, {"action": "launch"}, {"action": "check", "fresh": "yes"},
                     {"action": "cancel", "fresh": True}, {}, []):
            with self.subTest(body=body):
                code, answer, after = self.u.post(body)
                self.assertEqual(code, 400)
                self.assertIn("error", answer)
                self.assertIsNone(after)

    def test_actions_the_state_does_not_allow(self):
        self.assertEqual(self.post(action="download")[0], 400)
        self.assertEqual(self.post(action="install")[0], 400)
        self.assertEqual(self.post(action="cancel")[0], 200)
        self.assertEqual(self.gh.calls, [])


class Cache(Base):
    def test_kept_ten_minutes(self):
        self.release()
        self.check()
        self.check()
        self.assertEqual(self.gh.urls().count(LATEST), 1)
        self.clock.t += update.CACHE_SECS - 1
        self.check()
        self.assertEqual(self.gh.urls().count(LATEST), 1)
        self.clock.t += 2
        self.check()
        self.assertEqual(self.gh.urls().count(LATEST), 2)

    def test_fresh_asks_again(self):
        self.release()
        self.check()
        self.check(fresh=True)
        self.assertEqual(self.gh.urls().count(LATEST), 2)

    def test_a_failure_is_never_kept(self):
        self.gh.routes[LATEST] = (500, {}, b"")
        self.assertEqual(self.check()["state"], "failed")
        self.release()
        self.assertEqual(self.check()["state"], "newer")
        self.assertEqual(self.gh.urls().count(LATEST), 2)

    def test_cancel_drops_a_check(self):
        gate = threading.Event()
        reached = threading.Event()

        def slow():
            reached.set()
            gate.wait(5)
            return (200, {}, json.dumps({"tag_name": "v0.3.0", "assets": []}).encode())

        self.gh.routes[LATEST] = slow
        self.post(action="check")
        self.assertTrue(reached.wait(5))
        t = threading.Thread(target=lambda: self.post(action="cancel"))
        t.start()
        for _ in range(100):
            if self.u.view()["state"] == "idle":
                break
            time.sleep(0.01)
        gate.set()
        t.join(5)
        self.assertTrue(self.u.wait())
        v = self.u.get()
        self.assertEqual(v["state"], "idle")
        self.assertIsNone(v["latest"])


# ---------------------------------------------------------------------------------------------------------- the download


class Download(Base):
    def test_downloaded_and_proved(self):
        z = self.release()
        seq = logbook.lines_after(0, limit=0)[1]
        v = self.download()
        self.assertEqual(v["state"], "ready", v)
        h = sha(z)
        self.assertEqual(v["checks"], [
            {"id": "size", "ok": True, "text": "%s bytes - the size the release states" % "{:,}".format(len(z))},
            {"id": "sha256", "ok": True, "text": "sha256 matches DataPiler-0.3.0.zip.sha256 (%s\u2026%s)" % (h[:4],
                                                                                                           h[-4:])},
            {"id": "digest", "ok": True, "text": "and matches GitHub's digest for the file"},
            {"id": "shape", "ok": True, "text": "one folder, DataPiler, 7 files - nothing outside it, no links"},
            {"id": "manifest", "ok": True, "text": "its manifest: every file's sha256 checked; version inside: 0.3.0"}])
        self.assertEqual(v["plan"], {"write": 3, "add": 0, "remove": 0, "same": 4, "edited": 0, "files": 7,
                                     "libs": True})
        self.assertEqual(self.update_files(), ["update/0.3.0/DataPiler-0.3.0.zip"])
        self.assertEqual((self.root / "update" / "0.3.0" / "DataPiler-0.3.0.zip").read_bytes(), z)
        said = lines_since(seq)
        self.assertIn("INFO update download verified: DataPiler-0.3.0.zip, 0.0 MiB", said)
        gets = [l for l in said if " GET " in l or l.startswith("INFO update GET")]
        self.assertEqual(len(gets), 5, gets)       # the API, then each asset and its redirect
        self.assertTrue(any("release-assets.githubusercontent.com/github-production-release-asset/1/zip - 200" in l
                            for l in gets), gets)
        for l in said:
            self.assertNotIn("PLANTEDSECRET", l)
            self.assertNotIn("sp=r", l)
            self.assertNotIn(self.tmp.name, l)

    def test_the_libraries_unchanged(self):
        self.release(files=invented_app("0.3.0"))
        self.assertFalse(self.download()["plan"]["libs"])

    def test_the_digest_absent_is_amber(self):
        self.release(digest=False)
        v = self.download()
        self.assertEqual(v["state"], "ready")
        self.assertEqual(v["checks"][2], {"id": "digest", "ok": "warn", "text": "GitHub states no digest for this "
                                                                                 "file - the published .sha256 alone"})
        self.assertFalse(v["latest"]["digest"])

    def test_a_sha256_file_with_an_asterisk(self):
        z = invented_app("0.3.0")
        built = release_zip(Path(self.tmp.name) / "b.zip", z).read_bytes()
        self.release(zip_bytes=built, sha_text="%s *DataPiler-0.3.0.zip\n" % sha(built))
        self.assertEqual(self.download()["state"], "ready")

    def refused(self, cid, **kw):
        self.release(**kw)
        v = self.download()
        self.assertEqual(v["state"], "failed", v)
        self.assertEqual(v["failed"]["stage"], "verify")
        bad = [c for c in v["checks"] if c["ok"] is False]
        self.assertEqual([c["id"] for c in bad], [cid])
        self.assertEqual(v["checks"][-1]["id"], cid)
        self.assertEqual([p for p in self.update_files() if p.endswith((".zip", ".part"))], [])
        return v

    def test_the_size_differs(self):
        z = invented_app("0.3.0")
        built = release_zip(Path(self.tmp.name) / "b.zip", z).read_bytes()
        self.release(zip_bytes=built, body=built[:-1])
        doc = json.loads(self.gh.routes[LATEST][2])
        self.assertEqual(doc["assets"][0]["size"], len(built))
        v = self.download()
        self.assertEqual(v["checks"][0]["ok"], False)
        self.assertEqual(v["state"], "failed")

    def test_the_sha256_differs(self):
        self.refused("sha256", sha_text="%s  DataPiler-0.3.0.zip\n" % ("0" * 64))

    def test_the_sha256_file_names_another_file(self):
        z = invented_app("0.3.0")
        built = release_zip(Path(self.tmp.name) / "b.zip", z).read_bytes()
        v = self.refused("sha256", zip_bytes=built, sha_text="%s  other.zip\n" % sha(built))
        self.assertIn("names another file", v["checks"][-1]["text"])

    def test_the_sha256_file_is_not_one(self):
        self.refused("sha256", sha_text="not a checksum")

    def test_the_digest_differs(self):
        self.release()
        doc = json.loads(self.gh.routes[LATEST][2])
        doc["assets"][0]["digest"] = "sha256:" + "0" * 64
        self.gh.routes[LATEST] = (200, {}, json.dumps(doc).encode())
        v = self.download()
        self.assertEqual(v["state"], "failed")
        self.assertEqual([c["id"] for c in v["checks"] if c["ok"] is False], ["digest"])

    def test_the_shape(self):
        z = release_zip(Path(self.tmp.name) / "b.zip", invented_app("0.3.0"), extra=[("Other/x", b"x", None)])
        self.refused("shape", zip_bytes=z.read_bytes())

    def test_the_manifest(self):
        files = invented_app("0.3.0")
        z = release_zip(Path(self.tmp.name) / "b.zip", files, manifest=manifest_of(dict(files, **{"x.py": b"x"})))
        v = self.refused("manifest", zip_bytes=z.read_bytes())
        self.assertEqual(v["checks"][-2], {"id": "shape", "ok": True,
                                           "text": "one folder, DataPiler - nothing outside it, no links"})

    def test_another_version_inside(self):
        z = release_zip(Path(self.tmp.name) / "b.zip", invented_app("0.2.9"))
        v = self.refused("manifest", zip_bytes=z.read_bytes())
        self.assertIn("0.2.9", v["checks"][-1]["text"])

    def test_more_bytes_than_the_size(self):
        z = release_zip(Path(self.tmp.name) / "b.zip", invented_app("0.3.0")).read_bytes()
        self.release(zip_bytes=z, body=z + b"\0" * 10)
        v = self.download()
        self.assertEqual(v["state"], "failed")
        self.assertEqual(v["failed"]["stage"], "download")
        self.assertIn("more bytes than the release states", v["failed"]["text"])
        self.assertEqual(self.update_files(), [])

    def test_a_length_past_the_size(self):
        z = release_zip(Path(self.tmp.name) / "b.zip", invented_app("0.3.0")).read_bytes()
        self.release(zip_bytes=z)
        self.gh.routes[ASSET_HOST + "zip?sp=r&sig=PLANTEDSECRET"] = (200, {"Content-Length": str(len(z) + 1)}, z)
        v = self.download()
        self.assertEqual(v["state"], "failed")
        self.assertEqual(self.update_files(), [])

    def test_no_answer_for_the_zip(self):
        self.release()
        self.gh.routes[ASSET_HOST + "zip?sp=r&sig=PLANTEDSECRET"] = ConnectionResetError(104, "reset")
        v = self.download()
        self.assertEqual(v["failed"], {"stage": "download", "text": update.NO_ANSWER + " The part file was removed; "
                                                                                      "nothing was changed.",
                                       "kept": False})

    def big_release(self, hook):
        files = invented_app("0.3.0", **{"datapiler/big.bin": os.urandom(300_000)})
        z = release_zip(Path(self.tmp.name) / "big.zip", files).read_bytes()
        self.assertGreater(len(z), 4 * update.CHUNK)
        self.release(zip_bytes=z, body=lambda: Body(z, hook))
        return z

    def test_cancel_removes_the_part(self):
        reached, go = threading.Event(), threading.Event()
        part = self.root / "update" / "0.3.0" / "DataPiler-0.3.0.zip.part"
        seen = {}

        def hook(n):
            if n == 3:
                seen["part"] = part.exists()
                reached.set()
                go.wait(5)

        self.big_release(hook)
        self.check()
        self.post(action="download")
        self.assertTrue(reached.wait(5))
        self.assertTrue(seen["part"])
        t = threading.Thread(target=lambda: self.post(action="cancel"))
        t.start()
        for _ in range(200):
            if self.u.view()["state"] == "newer":
                break
            time.sleep(0.01)
        go.set()
        t.join(5)
        self.assertTrue(self.u.wait())
        self.assertEqual(self.u.get()["state"], "newer")
        self.assertFalse(part.exists())
        self.assertEqual(self.update_files(), [])

    def test_the_pop_up_gone_for_five_seconds(self):
        def hook(n):
            if n == 3:
                self.clock.t += update.POLL_GONE + 1

        self.big_release(hook)
        self.check()
        self.post(action="download")
        self.assertTrue(self.u.wait())
        v = self.u.view()
        self.assertEqual(v["state"], "failed")
        self.assertEqual(v["failed"]["stage"], "download")
        self.assertIn("pop-up was closed", v["failed"]["text"])
        self.assertEqual(self.update_files(), [])

    def test_polled_it_goes_on(self):
        def hook(n):
            self.clock.t += 3
            self.u.get()

        self.big_release(hook)
        self.assertEqual(self.download()["state"], "ready")

    def test_close_stops_it_and_removes_the_part(self):
        reached, go = threading.Event(), threading.Event()

        def hook(n):
            if n == 3:
                reached.set()
                go.wait(5)

        self.big_release(hook)
        self.check()
        self.post(action="download")
        self.assertTrue(reached.wait(5))
        t = threading.Thread(target=self.u.close)
        t.start()
        time.sleep(0.05)
        go.set()
        t.join(5)
        self.assertEqual(self.update_files(), [])
        self.assertEqual(self.u.post({"action": "check"})[0], 400)

    def test_discard_in_the_ready_state(self):
        self.release()
        self.download()
        code, v, _ = self.post(action="cancel")
        self.assertEqual((code, v["state"]), (200, "newer"))
        self.assertEqual(self.update_files(), [])

    def test_progress_while_downloading(self):
        seen = []

        def hook(n):
            if n == 2:
                self.clock.t += 1
            if n == 4:
                seen.append(self.u.get()["progress"])

        z = self.big_release(hook)
        self.download()
        self.assertEqual(seen[0], {"done": 3 * update.CHUNK, "of": len(z), "rate": 3 * update.CHUNK})


# ---------------------------------------------------------------------------------------------------------- install


class Install(Base):
    def ready(self):
        self.release()
        v = self.download()
        self.assertEqual(v["state"], "ready")
        return v

    def test_refused_while_busy(self):
        self.ready()
        self.busy = {"kind": "job", "id": "en-0001-x", "title": "x"}
        code, v, after = self.post(action="install")
        self.assertEqual((code, v["state"], after), (200, "ready", None))
        self.assertEqual(v["failed"], {"stage": "install", "text": update.BUSY, "kept": True})
        self.assertFalse((self.root / "update" / "pending.json").exists())
        self.busy = None
        code, v, after = self.post(action="install")
        self.assertEqual(v, {"ok": True, "state": "restarting", "to": "0.3.0"})

    def test_refused_without_a_manifest(self):
        self.ready()
        os.remove(self.root / "manifest.sha256")
        code, v, after = self.post(action="install")
        self.assertEqual((v["state"], v["failed"]["text"], v["failed"]["kept"], after),
                         ("ready", update.NOT_UNPACKED, True, None))
        self.assertTrue((self.root / "update" / "0.3.0" / "DataPiler-0.3.0.zip").exists())

    def test_refused_after_the_zip_changed(self):
        self.ready()
        z = self.root / "update" / "0.3.0" / "DataPiler-0.3.0.zip"
        data = bytearray(z.read_bytes())
        data[100] ^= 1
        z.write_bytes(bytes(data))
        code, v, after = self.post(action="install")
        self.assertEqual((v["state"], v["failed"]["stage"], v["failed"]["kept"], after), ("failed", "install", False,
                                                                                         None))
        self.assertEqual(self.update_files(), [])
        self.assertEqual(self.exits, [])

    def test_install_writes_pending_and_asks_to_stop_only_after_the_answer(self):
        self.ready()
        seq = logbook.lines_after(0, limit=0)[1]
        code, v, after = self.post(action="install")
        self.assertEqual((code, v), (200, {"ok": True, "state": "restarting", "to": "0.3.0"}))
        self.assertEqual(self.exits, [])            # the route answers first, then runs after
        self.assertTrue(callable(after))
        after()
        self.assertEqual(self.exits, [1])
        p = install.read_pending(self.root)
        self.assertEqual((p.from_version, p.to_version, p.zip, p.port), ("0.2.0", "0.3.0",
                                                                          "update/0.3.0/DataPiler-0.3.0.zip", 22777))
        z = (self.root / "update" / "0.3.0" / "DataPiler-0.3.0.zip").read_bytes()
        self.assertEqual((p.zip_sha256, p.zip_size), (sha(z), len(z)))
        helper_copy = self.root / "update" / "0.3.0" / "update-helper.py"
        self.assertEqual(helper_copy.read_bytes(), (Path(_repo.ROOT) / "update-helper.py").read_bytes())
        self.assertIn("INFO update update requested: 0.3.0 - stopping (exit code 75)", lines_since(seq))
        # nothing more is taken once it is leaving
        self.assertEqual(self.post(action="check")[0], 400)

    def test_came_back_serves_the_result_once(self):
        self.ready()
        self.post(action="install")
        p = install.read_pending(self.root)
        (self.root / "update" / "result.json").write_text(json.dumps({
            "format": "datapiler-update-result/1", "nonce": p.nonce, "state": "updated", "from": "0.2.0",
            "to": "0.3.0", "stage": "done", "text": None, "backup": "update/backup-0.2.0", "restored": None,
            "counts": {"written": 2, "added": 0, "removed": 0, "same": 5, "files": 7}}))
        u = self.updater(version="0.3.0")
        u.came_back(p, install.Check(manifest=True, files=7, differ=(), missing=()))
        r = u.result()
        self.assertEqual((r["state"], r["to"], r["backup"], r["check"]),
                         ("updated", "0.3.0", "update\\backup-0.2.0", {"files": 7, "differ": 0, "manifest": True}))
        self.assertEqual(u.result(), {"state": None})
        u.close()

    def test_came_back_without_a_result(self):
        self.ready()
        self.post(action="install")
        p = install.read_pending(self.root)
        u = self.updater()
        u.came_back(p, install.Check(manifest=True, files=7, differ=("a",), missing=()))
        r = u.result()
        self.assertEqual(r["state"], "failed")
        self.assertIn("did not complete", r["text"])
        u.came_back(None, install.Check(manifest=False, files=0, differ=(), missing=()))
        self.assertEqual(u.result(), {"state": None})
        u.close()


# ---------------------------------------------------------------------------------------------------------- notes


class Notes(unittest.TestCase):
    def tree(self, text):
        return update.notes_tree(text)[0]

    def test_headings(self):
        self.assertEqual(self.tree("# One\n### Three ###\nTwo\n---\n"), [
            {"k": "h", "level": 1, "parts": [{"t": "text", "v": "One"}]},
            {"k": "h", "level": 3, "parts": [{"t": "text", "v": "Three"}]},
            {"k": "h", "level": 2, "parts": [{"t": "text", "v": "Two"}]}])

    def test_lists(self):
        self.assertEqual(self.tree("- a\n* b\n  more\n+ c\n\n1. one\n2) two"), [
            {"k": "li", "n": None, "parts": [{"t": "text", "v": "a"}]},
            {"k": "li", "n": None, "parts": [{"t": "text", "v": "b more"}]},
            {"k": "li", "n": None, "parts": [{"t": "text", "v": "c"}]},
            {"k": "li", "n": 1, "parts": [{"t": "text", "v": "one"}]},
            {"k": "li", "n": 2, "parts": [{"t": "text", "v": "two"}]}])

    def test_code(self):
        self.assertEqual(self.tree("```python\nx = 1\n  y\n```\n\n    indented\n    two\n"), [
            {"k": "code", "v": "x = 1\n  y"}, {"k": "code", "v": "indented\ntwo"}])

    def test_inline(self):
        self.assertEqual(self.tree("**bold** and *it* and _it2_ and `co de` and snake_case_name"), [
            {"k": "p", "parts": [{"t": "b", "v": "bold"}, {"t": "text", "v": " and "}, {"t": "i", "v": "it"},
                                 {"t": "text", "v": " and "}, {"t": "i", "v": "it2"}, {"t": "text", "v": " and "},
                                 {"t": "code", "v": "co de"}, {"t": "text", "v": " and snake_case_name"}]}])

    def test_links_and_images(self):
        self.assertEqual(self.tree("See [the list](https://github.com/x/compare/a...b \"t\") ![a shot](s.png) "
                                   "<https://example.invalid/z>"), [
            {"k": "p", "parts": [{"t": "text", "v": "See "},
                                 {"t": "link", "v": "the list", "href": "https://github.com/x/compare/a...b"},
                                 {"t": "text", "v": " "}, {"t": "image", "v": "a shot"}, {"t": "text", "v": " "},
                                 {"t": "link", "v": "https://example.invalid/z", "href": "https://example.invalid/z"}]}])

    def test_raw_html_stays_text(self):
        html = '<script>alert(1)</script> <img src=x onerror=alert(1)> <a href="javascript:x">y</a>'
        tree = self.tree(html)
        self.assertEqual(tree, [{"k": "p", "parts": [{"t": "text", "v": html}]}])

    def test_quotes_and_paragraphs(self):
        self.assertEqual(self.tree("> quoted\nline\n\nnext"), [
            {"k": "p", "parts": [{"t": "text", "v": "quoted line"}]},
            {"k": "p", "parts": [{"t": "text", "v": "next"}]}])

    def test_the_cut(self):
        blocks, cut = update.notes_tree("x" * 25_000)
        self.assertTrue(cut)
        self.assertEqual(len(blocks[0]["parts"][0]["v"]), update.NOTES_MAX)
        self.assertEqual(update.notes_tree("x" * 20_000)[1], False)

    def test_nothing(self):
        for body in (None, "", "  \n ", 7):
            self.assertEqual(update.notes_tree(body), ([], False))

    def test_only_known_keys(self):
        blocks, _ = update.notes_tree("# h\n- **b** [l](u)\n```\nc\n```\np ![i](x) `c` *i*")
        for b in blocks:
            self.assertIn(b["k"], ("h", "p", "li", "code"))
            for p in b.get("parts", []):
                self.assertIn(p["t"], ("text", "b", "i", "code", "link", "image"))
                self.assertLessEqual(set(p), {"t", "v", "href"})


if __name__ == "__main__":
    unittest.main()
