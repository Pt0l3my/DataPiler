"""Phase 2 (build plan §8.1): the real modules, the fake Soapstone server, an invented text export dropped in the
inbox, the design's example job dropped and started: a share file whose checks all pass, a job log, and no planted
name in the ring, the files or the share file. Skips without grpc."""

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

from datapiler import game, textdb, winapi
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
        # P2 and P3 (build plan §10) leave the expansion's files and the names' wrapper ids unconfirmed in 0.1, so
        # every share write and every join_names would be refused: the test supplies invented ones.
        self.patches = [mock.patch.object(fake_soapstone, "TEXT_CELL_ID", -1),     # every nameId a number here
                        mock.patch.object(game, "EXPANSION_MARKERS", ("invented-expansion-marker.bin",)),
                        mock.patch.dict(textdb.TEXT_SETS, {"character_names": (("item", 9001),),
                                                           "place_names": (("item", 9002),)})]
        for p in self.patches:
            p.start()
        self.fake = fake_soapstone.FakeSoapstone().start()
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name)
        for d in ("Game", "Smithbox", "Project"):
            (root / d).mkdir()
        (root / "Game" / "eldenring.exe").write_bytes(b"")
        (root / "Game" / "regulation.bin").write_bytes(b"invented regulation bytes " * 64)
        (root / "Game" / "invented-expansion-marker.bin").write_bytes(b"")
        (root / "Smithbox" / "Smithbox.exe").write_bytes(b"")
        save(root / "settings.json", Settings(game_dir=str(root / "Game"), smithbox_dir=str(root / "Smithbox"),
                                              project_dir=str(root / "Project")))
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
            doc = json.loads(v["text"])
            self.assertEqual(doc["format"], "datapiler-share/1")
            self.assertEqual(doc["provenance"]["game_version"], "1.16.0.0")
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


if __name__ == "__main__":
    unittest.main()
