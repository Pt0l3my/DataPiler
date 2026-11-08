"""Phase 2 (build plan §8.1): the real modules, the fake Soapstone server, an invented text export dropped in the
inbox, the design's example job dropped and started: a share file whose checks all pass, a job log, and no planted
name in the ring, the files or the share file. Skips without grpc.

And 0.2.0's update the whole way (build plan 0.2 §3.4, §7.1): the real Updater with a fake GitHub and the real
Folders with a fake backend, through datapiler.main: Update..., Download and Install on the page's API, exit 75, the
window's helper, the new start on the same port, and the result served once. Needs no grpc."""

import _repo  # noqa: F401

import base64
import contextlib
import http.client
import importlib.util
import io
import json
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import grpc  # noqa: F401
    HAVE_GRPC = True
except ImportError:
    HAVE_GRPC = False

from datapiler import install, textdb, winapi
from datapiler.settings import Settings, save

EXAMPLE_JOB = {
    "format": "datapiler-job/1",
    "id": "en-0007-roster-counts",
    "title": "Roster: named characters per team",
    "ops": [
        {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId", "teamType", "npcType"]},
        {"op": "fetch_rows", "as": "talk", "param": "TalkParam", "fields": ["id", "msgId"]},
        {"op": "join_names", "as": "npc_named", "rows": "npc", "key": "nameId", "text": "character_names"},
        {"op": "count", "as": "per_team", "rows": "npc_named", "by": ["teamType"], "where": {"named": True}},
        {"op": "write_share", "name": "roster-counts", "tables": ["per_team"],
         "columns": {"per_team": ["teamType", "count"]}},
    ],
}

# Invented names for the text export: they may sit in the workspace, never in a log line or the share file.
NAMES = ("Halvard Emberwick", "Odessa of the Grey Weir", "Corvin Saltmarrow", "Ysolde Thistlegate",
         "Brother Aumric Fenlow", "Tamsin Rookhollow")


class FakeBackend(winapi.PortableBackend):
    def processes(self):
        return []

    def file_version(self, path):
        name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        return {"eldenring.exe": "1.16.0.0", "smithbox.exe": "2.2.6.0"}.get(name)

    def user_name(self):
        return "zorblax"

    def pc_name(self):
        return "QUENTIN-RIG"

    def home(self):
        return None


def wait_for(fn, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return None


@unittest.skipUnless(HAVE_GRPC, "the integration test needs grpcio and protobuf")
class IntegrationTest(unittest.TestCase):
    def setUp(self):
        import fake_soapstone
        self.fs_mod = fake_soapstone
        # P2: the owner states the expansion in Settings (below). P3: the names' wrappers are ER01's leads, as built
        # in, and join_names verifies them with this run's own (invented) numbers.
        self.patches = [mock.patch.object(fake_soapstone, "TEXT_CELL_ID", -1)]     # every nameId a number here
        for p in self.patches:
            p.start()
        self.fake = fake_soapstone.FakeSoapstone().start()
        self.tmp = tempfile.TemporaryDirectory()
        # DataPiler's folder, with the game, Smithbox and the project beside it: from 0.2.0 a project inside
        # DataPiler's folder is refused (S32)
        base = Path(self.tmp.name)
        root = self.root = base / "DataPiler"
        root.mkdir()
        for d in ("Game", "Smithbox", "Project"):
            (base / d).mkdir()
        (base / "Game" / "eldenring.exe").write_bytes(b"")
        (base / "Game" / "regulation.bin").write_bytes(b"invented regulation bytes " * 64)
        (base / "Smithbox" / "Smithbox.exe").write_bytes(b"")
        save(root / "settings.json", Settings(game_dir=str(base / "Game"), smithbox_dir=str(base / "Smithbox"),
                                              project_dir=str(base / "Project"), expansion="yes"))
        self.use = winapi.use(FakeBackend())
        self.use.__enter__()
        spec = importlib.util.spec_from_file_location("datapiler_main_it", str(Path(_repo.ROOT) / "datapiler.py"))
        self.entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.entry)

    def tearDown(self):
        self.use.__exit__(None, None, None)
        self.fake.stop()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def text_export(self):
        sets = textdb.TEXT_SETS["character_names"]
        container, wrapper = sets[0]
        ids = sorted({9500000 + (rid - 9000000) for rid in self.fs_mod.NPC_IDS})
        entries = [{"ID": i, "Text": NAMES[k % len(NAMES)] if k % 3 else ""} for k, i in enumerate(ids)]
        return {"Name": container, "SourceContainer": container, "SourceCategory": "Common",
                "FmgWrappers": [{"Name": "InventedWrapper", "ID": wrapper,
                                 "Fmg": {"Name": "InventedWrapper", "Entries": entries, "Version": 2,
                                         "BigEndian": False, "Unicode": True}}]}

    def test_the_whole_way(self):
        entry, fake = self.entry, self.fake

        class Parts(entry.RealParts):
            def link(self, status, no_link):
                from datapiler import link as link_mod
                return link_mod.Link(status.game_running, libs=True, _test_port=fake.port), True

            def port_answers(self, game_fn):
                return True

        out = {}

        def run():
            with contextlib.redirect_stdout(io.StringIO()):
                out["code"] = entry.main(["--port", "0", "--no-browser"], root=self.root, parts=Parts())

        t = threading.Thread(target=run, daemon=True)
        t.start()
        port_file = self.root / "datapiler.port"
        port = wait_for(lambda: port_file.is_file() and int(port_file.read_text(encoding="ascii").strip() or 0))
        self.assertTrue(port)
        page = self.http(port, "GET", "/")[1].decode("utf-8")
        self.token = re.search(r'const TOKEN = "([^"]+)"', page).group(1)
        try:
            # the text export arrives in the inbox and is imported
            inbox = self.root / "workspace" / "inbox"
            (inbox / "my export.json").write_text(json.dumps(self.text_export()), encoding="utf-8")
            self.assertTrue(wait_for(lambda: not (inbox / "my export.json").exists()), self.api(port, "/api/state"))
            # the server link on, the example job dropped and started
            # (asked once a session whether Smithbox has the project set in Settings open)
            self.assertIn("ask", self.api(port, "/api/link", {"on": True}))
            self.assertEqual(self.api(port, "/api/link", {"on": True, "confirm_project": True}),
                             {"ok": True, "state": "on"})
            raw = json.dumps(EXAMPLE_JOB, indent=1).encode()
            r = self.api(port, "/api/jobs/drop", {"name": "job.json", "data": base64.b64encode(raw).decode()})
            self.assertEqual(r["card"]["state"], "checked", r["card"])
            r = self.api(port, "/api/jobs/act", {"id": EXAMPLE_JOB["id"], "what": "start", "confirm_maps": None})
            self.assertTrue(r["ok"], r)

            def finished():
                s = self.api(port, "/api/state")
                card = next(j for j in s["jobs"] if j["id"] == EXAMPLE_JOB["id"])
                return card if card["state"] in ("done", "failed", "cancelled") else None

            card = wait_for(finished, 60)
            self.assertIsNotNone(card)
            self.assertEqual(card["state"], "done", card)
            share = card["result"]["share"]
            self.assertEqual(share["name"], "roster-counts.json")
            v = self.api(port, "/api/share?name=roster-counts.json")
            self.assertTrue(all(c["ok"] for c in v["checks"]), v["checks"])
            self.assertEqual([c["check"] for c in v["checks"]], [1, 2, 3, 4, 5, 6])
            doc = json.loads(v["text"])
            self.assertEqual(doc["format"], "datapiler-share/1")
            self.assertEqual(doc["provenance"]["game_version"], "1.16.0.0")
            self.assertEqual((doc["provenance"]["expansion"], doc["provenance"]["expansion_source"]), (True, "owner"))
            # the leads verified: two in three of the invented name numbers have a text
            self.assertEqual(doc["provenance"]["names"], {"character_names": {
                "wrappers": [428, 328, 18], "verified": True, "resolved": 0.666}})
            outputs = self.api(port, "/api/outputs")
            self.assertIn("roster-counts.json", [f["name"] for f in outputs["share"]])
            # Settings moves the share folder: the runner writes to the new one (it reads the Paths at each write)
            cfg = self.api(port, "/api/settings")["settings"]
            cfg["share_dir"] = "share-moved"
            self.assertTrue(self.api(port, "/api/settings", {"settings": cfg})["ok"])
            r = self.api(port, "/api/jobs/act", {"id": EXAMPLE_JOB["id"], "what": "start", "confirm_maps": None})
            self.assertTrue(r["ok"], r)
            card = wait_for(finished, 60)
            self.assertEqual(card["state"], "done", card)
            self.assertTrue((self.root / "share-moved" / "roster-counts.json").is_file())
            outputs = self.api(port, "/api/outputs")
            self.assertIn("roster-counts.json", [f["name"] for f in outputs["share"]])
            ring = json.dumps(self.api(port, "/api/log?after=0"))
        finally:
            self.assertEqual(self.api(port, "/api/quit", {"cancel_running": True}), {"ok": True})
            t.join(15)
        self.assertEqual(out.get("code"), 0)
        job_log = self.root / "logs" / "jobs" / (EXAMPLE_JOB["id"] + ".log")
        self.assertTrue(job_log.is_file())
        texts = [ring, v["text"], (self.root / "share" / "roster-counts.json").read_text(encoding="utf-8")]
        for f in (self.root / "logs").rglob("*.log*"):
            texts.append(f.read_text(encoding="utf-8"))
        planted = NAMES + tuple(self.fs_mod.PLANTED) + ("zorblax", "QUENTIN-RIG", self.tmp.name)
        for text in texts:
            for name in planted:
                self.assertNotIn(name.casefold(), text.casefold())

    # ------------------------------------------------------------------------------------ the page's requests

    def http(self, port, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % port, "Origin": "http://127.0.0.1:%d" % port}
        if getattr(self, "token", None):
            h["X-DataPiler-Token"] = self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, raw

    def api(self, port, path, body=None):
        status, raw = self.http(port, "POST" if body is not None else "GET", path, body)
        self.assertEqual(status, 200, raw[:300])
        return json.loads(raw)


class UpdateTheWholeWay(unittest.TestCase):
    def setUp(self):
        from test_archive import invented_app, manifest_of, release_zip, sha
        from test_update import ASSET_HOST, FakeGitHub
        from datapiler.update import ASSET_PREFIX, LATEST, PAGE_PREFIX
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        root = self.root = base / "DataPiler"
        self.old = invented_app("0.2.0")
        for rel, data in self.old.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        (root / "manifest.sha256").write_bytes(manifest_of(self.old))
        for d in ("Game", "Smithbox"):
            (base / d).mkdir()
        (base / "Game" / "eldenring.exe").write_bytes(b"")
        (base / "Smithbox" / "Smithbox.exe").write_bytes(b"")
        self.game = base / "Game"
        save(root / "settings.json", Settings(game_dir=str(base / "Game"), smithbox_dir=str(base / "Smithbox")))
        self.new = invented_app("0.3.0", **{"datapiler/added.py": b"# new in the invented 0.3.0\n"})
        z = release_zip(Path(self.tmp.name) / "built.zip", self.new).read_bytes()
        name = "DataPiler-0.3.0.zip"
        gh = self.gh = FakeGitHub()
        gh.routes[LATEST] = (200, {}, json.dumps({
            "tag_name": "v0.3.0", "published_at": "2026-11-20T10:00:00Z", "html_url": PAGE_PREFIX + "tag/v0.3.0",
            "body": "## What's new\n- invented", "assets": [
                {"name": name, "size": len(z), "browser_download_url": ASSET_PREFIX + "v0.3.0/" + name,
                 "digest": "sha256:" + sha(z)},
                {"name": name + ".sha256", "size": 90, "browser_download_url": ASSET_PREFIX + "v0.3.0/" + name +
                 ".sha256"}]}).encode())
        gh.routes[ASSET_PREFIX + "v0.3.0/" + name] = (302, {"Location": ASSET_HOST + "z"}, b"")
        gh.routes[ASSET_HOST + "z"] = lambda: (200, {}, z)
        gh.routes[ASSET_PREFIX + "v0.3.0/" + name + ".sha256"] = (200, {}, ("%s  %s\n" % (sha(z), name)).encode())
        self.use = winapi.use(FakeBackend())
        self.use.__enter__()
        spec = importlib.util.spec_from_file_location("datapiler_main_up", str(Path(_repo.ROOT) / "datapiler.py"))
        self.entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.entry)

    def tearDown(self):
        self.use.__exit__(None, None, None)
        self.tmp.cleanup()

    def start(self, *args):
        entry, gh = self.entry, self.gh

        class Parts(entry.RealParts):
            def updater(self, run):
                from datapiler import update
                return update.Updater(root=run.root, version=self.version, port=lambda: run.port,
                                      busy=run.runner.busy, request_exit=run.request_update_exit, fetch=gh)

        Parts.version = self.version
        out = {}

        def run():
            with contextlib.redirect_stdout(io.StringIO()):
                out["code"] = entry.main(["--no-browser", "--no-link", *args], root=self.root, parts=Parts())

        t = threading.Thread(target=run, daemon=True)
        t.start()
        port_file = self.root / "datapiler.port"
        port = wait_for(lambda: port_file.is_file() and int(port_file.read_text(encoding="ascii").strip() or 0))
        self.assertTrue(port)
        page = IntegrationTest.http(self, port, "GET", "/")[1].decode("utf-8")
        self.token = re.search(r'const TOKEN = "([^"]+)"', page).group(1)
        return t, out, port

    http = IntegrationTest.http
    api = IntegrationTest.api

    def view_until(self, port, state):
        return wait_for(lambda: (lambda v: v if v["state"] == state else None)(self.api(port, "/api/update")), 20)

    def test_check_download_install_swap_and_come_back(self):
        self.version = "0.2.0"
        t, out, port = self.start("--port", "0")
        try:
            v = self.api(port, "/api/update", {"action": "check", "fresh": False})
            self.assertIn(v["state"], ("checking", "newer"))
            v = self.view_until(port, "newer")
            self.assertEqual(v["latest"]["version"], "0.3.0")
            self.api(port, "/api/update", {"action": "download"})
            v = self.view_until(port, "ready")
            self.assertTrue(all(c["ok"] is True for c in v["checks"]), v["checks"])
            self.assertEqual(v["plan"]["add"], 1)
            self.assertEqual(self.api(port, "/api/settings")["settings"]["game_dir"], str(self.game))
        except BaseException:
            self.api(port, "/api/quit", {"cancel_running": True})
            raise
        self.assertEqual(self.api(port, "/api/update", {"action": "install"}),
                         {"ok": True, "state": "restarting", "to": "0.3.0"})
        t.join(15)
        self.assertEqual(out.get("code"), 75)
        pending = install.read_pending(self.root)
        self.assertEqual(pending.port, port)
        # the window: the helper from the verified download, as DataPiler.ps1 runs it on exit code 75
        said = []
        h = install.helper(install.APP)
        self.assertEqual(h.install(self.root, self.root / "update" / "pending.json", say=said.append), 0, said)
        for rel, data in self.new.items():
            self.assertEqual((self.root / rel).read_bytes(), data, rel)
        # the new version starts on the page's port, serves the result once, and cleans up
        self.version = "0.3.0"
        t, out, port2 = self.start()
        try:
            self.assertEqual(port2, port)
            r = wait_for(lambda: (lambda x: x if x["state"] else None)(self.api(port2, "/api/update-result")), 10)
            self.assertEqual((r["state"], r["from"], r["to"], r["backup"]), ("updated", "0.2.0", "0.3.0",
                                                                              "update\\backup-0.2.0"))
            self.assertEqual(r["counts"]["added"], 1)
            self.assertEqual(r["check"], {"files": len(self.new), "differ": 0, "manifest": True})
            self.assertEqual(self.api(port2, "/api/update-result"), {"state": None})
            self.assertFalse((self.root / "update" / "pending.json").exists())
            self.assertTrue(wait_for(lambda: not (self.root / "update" / "0.3.0").exists(), 10))
            self.assertTrue((self.root / "update" / "backup-0.2.0" / "backup.json").is_file())
        finally:
            self.assertEqual(self.api(port2, "/api/quit", {"cancel_running": True}), {"ok": True})
            t.join(15)
        self.assertEqual(out.get("code"), 0)
        log = (self.root / "logs" / "datapiler.log").read_text(encoding="utf-8")
        self.assertIn("update   install check: all %d files match the release" % len(self.new), log)
        self.assertIn("update   update requested: 0.3.0 - stopping (exit code 75)", log)
        self.assertIn("(the open page reloads)", log)
        texts = [log, (self.root / "logs" / "update.log").read_text(encoding="utf-8")] + said
        for text in texts:
            self.assertNotIn(self.tmp.name, text)
            for name in ("zorblax", "QUENTIN-RIG"):
                self.assertNotIn(name.casefold(), text.casefold())


if __name__ == "__main__":
    unittest.main()
