"""The endpoints of build plan §5 against fakes of JOBS's and LINK's parts. The fakes are also used by test_start."""

import _repo  # noqa: F401

import base64
import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import datapiler
from datapiler import api, events, logbook, paths, settings, winapi
from datapiler.api import Api, Live
from datapiler.logbook import own
from datapiler.server import Bad
from datapiler.settings import Session, Settings
from datapiler.status import Status
from datapiler.winapi import Proc

PLANTED = "Velkor Dunmarrow"
JOB_ID = "en-0007-roster-counts"
CARD = {"id": JOB_ID, "title": "Roster: named characters per team", "format": "datapiler-job/1", "sha256": "0" * 64,
        "state": "checked", "refusals": [], "preview": {"reads": ["NpcParam rows: id"], "computes": [], "writes": []},
        "wait": None, "ops": [], "result": None}


class FakeLink:
    def __init__(self, state="off"):
        self.state = state
        self.switched = []
        self.closed = None

    def switch(self, on):
        self.switched.append(on)
        if self.state != "no_libs":
            self.state = "on" if on else "off"
        return self.state

    def stats(self):
        return {"calls": 0, "last_call": None, "last_methods": []}

    def would_call(self):
        return [{"method": "ListParams", "for": "the names of the params"}]

    def close(self, why):
        self.closed = why
        if self.state != "no_libs":
            self.state = "off"


class FakeRunner:
    def __init__(self):
        self.busy_with = None
        self.added = []
        self.stopped = None
        self.cancelled = False
        self.runs = []
        self.loaded = False
        self.rows = []

    def load_folder(self):
        self.loaded = True

    def add(self, filename, raw):
        if not raw:
            raise ValueError("empty")
        self.added.append((filename, raw))
        return dict(CARD), False

    def act(self, job_id, what, *, confirm_maps=None):
        if job_id != JOB_ID or what not in ("start", "cancel", "remove"):
            raise ValueError("unknown")
        if what == "start" and confirm_maps != 98:
            return {"ok": False, "ask": {"maps": 98, "text": "Start loads 98 maps in Smithbox. Go on?"}}
        return {"ok": True}

    def run_extract(self, rows, *, load_maps=False, confirm_maps=None):
        if any(r not in ("character_rows", "map_placements") for r in rows):
            raise ValueError("unknown row")
        self.runs.append((list(rows), load_maps, confirm_maps))
        return {"ok": True}

    def cancel_extract(self):
        self.cancelled = True

    def cards(self):
        return [dict(CARD)]

    def extract_state(self):
        return {"running": None, "rows": list(self.rows), "ask": None}

    def made_by(self):
        return {"roster-counts.json": own(JOB_ID), "local/%s/npc-named.json" % JOB_ID: own(JOB_ID)}

    def busy(self):
        return self.busy_with

    def stop(self, *, cancel, timeout=3.0):
        self.stopped = cancel


class FakeTextDB:
    def __init__(self, texts=(PLANTED,)):
        self.texts = [t.casefold() for t in texts]
        self.closed = False

    def find_in(self, haystack):
        h = haystack.casefold()
        return any(len(t) >= 4 and t in h for t in self.texts)

    def close(self):
        self.closed = True


@dataclass(frozen=True)
class CheckResult:
    check: int
    name: str
    ok: bool
    where: str | None


class FakeGuard:
    def __init__(self):
        self.fail = {}          # file bytes -> the check that fails on them
        self.calls = 0

    def check(self, data, *, declared, coverage=None):
        self.calls += 1
        self.coverage = coverage
        bad = self.fail.get(bytes(data))
        return [CheckResult(i, n, i != bad, "(file)" if i == bad else None)
                for i, n in enumerate(("Shape", "Values", "Text", "The owner", "Size", "Coverage"), 1)]

    def check_labels(self):
        return []


class FakeInbox:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def state(self):
        return [{"file": "export.json", "reason": "not a Smithbox text export"}]


class FakeCatalogue:
    ROWS = ()

    @staticmethod
    def public():
        return {"rows": [{"id": "character_rows", "name": "Character rows", "help": "?", "sources": ["server"],
                          "gives": "row ids, name numbers", "goes_to": "workspace+share", "steps": []}],
                "bundles": {"roster": ["character_rows"]}}


class FakeParts:
    """datapiler.main's parts for tests: fakes of the TextDB, Guard, Link, Runner and Inbox."""

    def __init__(self):
        self.made = {}

    def store(self, live):
        self.made["textdb"], self.made["guard"] = FakeTextDB(), FakeGuard()
        return self.made["textdb"], self.made["guard"]

    def port_answers(self, game):
        return False

    def link(self, status, no_link):
        self.made["link"] = FakeLink("no_libs" if no_link else "off")
        return self.made["link"], not no_link

    def runner(self, live, link, textdb, guard, status):
        self.made["runner"] = FakeRunner()
        return self.made["runner"]

    def inbox(self, live, textdb):
        self.made["inbox"] = FakeInbox()
        return self.made["inbox"]

    def catalogue(self):
        return FakeCatalogue()


class FakeBackend(winapi.PortableBackend):
    def __init__(self):
        self.procs = []
        self.clipboard = None
        self.opened = None

    def processes(self):
        return list(self.procs)

    def set_clipboard(self, text):
        self.clipboard = text
        return True

    def open_folder(self, path):
        self.opened = path
        return False

    def user_name(self):
        return "zorblax"

    def pc_name(self):
        return "QUENTIN-RIG"

    def home(self):
        return None


class ApiBase(unittest.TestCase):
    """The fixture: DataPiler's folder, the game's and the project's folders outside it, the fakes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "DataPiler"         # DataPiler's own folder: the project is outside it (S32)
        self.root.mkdir()
        self.game = self.base / "Game"
        self.game.mkdir()
        (self.game / "eldenring.exe").write_bytes(b"")
        self.project = self.base / "Project"
        self.project.mkdir()
        cfg = Settings(game_dir=str(self.game), project_dir=str(self.project))
        p = paths.resolve(self.root, cfg.workspace_dir, cfg.share_dir)
        paths.ensure(p)
        self.live = Live(root=self.root, settings=cfg, paths=p, session=Session())
        self.b = FakeBackend()
        self.use = winapi.use(self.b)
        self.use.__enter__()
        self.link = FakeLink()
        self.runner = FakeRunner()
        self.textdb = FakeTextDB()
        self.status = Status(lambda: self.live.settings, lambda: self.link, lambda: False)
        self.stops = []
        self.guard = FakeGuard()
        self.api = Api(live=self.live, status=self.status, link=self.link, runner=self.runner, textdb=self.textdb,
                       guard=self.guard, inbox=FakeInbox(), catalogue=FakeCatalogue(),
                       stop=lambda: self.stops.append(1), libs=True)

    def tearDown(self):
        self.api.close()
        self.status.close()
        self.use.__exit__(None, None, None)
        logbook.set_debug(False)
        logbook.set_masks(folders={}, home=None, user=None, pc=None)
        self.tmp.cleanup()

    def get(self, path, **query):
        code, body = self.api.get(path, {k: str(v) for k, v in query.items()})
        self.assertEqual(code, 200, path)
        return json.loads(json.dumps(body))

    def post(self, path, body):
        code, answer, after = self.api.post(path, body)
        return code, json.loads(json.dumps(answer)), after


class ApiTest(ApiBase):
    # ------------------------------------------------------------------------------------ GET

    def test_state_shape(self):
        s = self.get("/api/state")
        self.assertEqual(set(s), {"version", "pills", "block", "status", "extract", "jobs", "outputs_rev", "session"})
        self.assertEqual(s["version"], datapiler.VERSION)
        self.assertEqual(set(s["pills"]), {"smithbox", "game", "link"})
        self.assertEqual(set(s["status"]), {"smithbox", "game", "project", "link"})
        self.assertEqual(s["extract"]["inbox"], [{"file": "export.json", "reason": "not a Smithbox text export"}])
        self.assertEqual(s["jobs"][0]["id"], JOB_ID)
        self.assertEqual(s["session"], {"link": False, "debug": False, "libs": True})

    def test_a_waiting_extract_run_is_named_under_the_bar(self):
        """Design §2: one line under the bar whenever something blocks a run, saying what and where to fix it."""
        self.assertIsNone(self.get("/api/state")["block"])
        self.runner.rows = [{"id": "character_names", "state": "waiting_export", "grey": None},
                            {"id": "character_rows", "state": "queued", "grey": "the server link is off"}]
        self.assertEqual(self.get("/api/state")["block"],
                         "Extract waits: the server link is off - switch it on in Status.")
        self.runner.rows[1]["grey"] = "the server link needs its libraries - restart DataPiler and answer Y"
        self.assertEqual(self.get("/api/state")["block"], "Extract waits: the server link needs its libraries - "
                                                          "restart DataPiler and answer Y.")
        self.runner.rows[1].update(state="idle")
        self.assertIsNone(self.get("/api/state")["block"])

    def test_outputs_rev_counts_written_files(self):
        before = self.get("/api/state")["outputs_rev"]
        events.emit("share.written", name=own("x"), size=1)
        events.emit("local.written", job=own("x"), size=1)
        events.emit("inbox.import", container=own("item"), ok=True, entries=3)
        events.emit("job.state", id=own("x"), state=own("done"))
        self.assertEqual(self.get("/api/state")["outputs_rev"], before + 3)

    def test_catalogue(self):
        c = self.get("/api/catalogue")
        self.assertEqual(set(c), {"rows", "bundles"})

    def test_outputs_and_share(self):
        p = self.live.paths
        (p.workspace / "textdb.sqlite").write_bytes(b"x" * 10)
        (p.local / JOB_ID).mkdir(parents=True)
        (p.local / JOB_ID / "npc-named.json").write_bytes(b"{}")
        doc = {"format": "datapiler-share/1", "tables": [{"name": "per_team", "columns": [{"name": "count",
                                                                                         "type": "int"}]}]}
        data = json.dumps(doc).encode()
        (p.share / "roster-counts.json").write_bytes(data)
        (p.share / "Not Ours.json").write_bytes(b"{}")
        o = self.get("/api/outputs")
        names = {f["name"]: f for f in o["workspace"]}
        self.assertIn("textdb.sqlite", names)
        self.assertEqual(names["local/%s/npc-named.json" % JOB_ID]["made_by"], JOB_ID)
        self.assertEqual([f["name"] for f in o["share"]], ["roster-counts.json"])
        f = o["share"][0]
        self.assertEqual(set(f), {"name", "size", "time", "made_by", "ok", "failed"})
        self.assertEqual((f["ok"], f["failed"]), (True, None))
        self.assertNotIn(self.tmp.name, json.dumps(o))
        v = self.get("/api/share", name="roster-counts.json")
        self.assertEqual(set(v), {"name", "size", "sha256", "text", "checks"})
        self.assertEqual(v["text"], data.decode())
        self.assertEqual([c["check"] for c in v["checks"]], [1, 2, 3, 4, 5, 6])
        self.assertIsNone(self.guard.coverage)          # no row counts kept for it: the real guard fails check 6
        with self.assertRaises(Bad):
            self.api.get("/api/share", {"name": "../settings.json"})
        with self.assertRaises(Bad):
            self.api.get("/api/share", {"name": "missing.json"})

    def test_log(self):
        logbook.get("app").info("a line for the log test")
        r = self.get("/api/log", after=0)
        self.assertEqual(set(r), {"lines", "last", "first"})
        self.assertEqual(set(r["lines"][-1]), {"seq", "t", "level", "src", "msg"})
        r2 = self.get("/api/log", after=r["last"])
        self.assertEqual(r2["lines"], [])
        with self.assertRaises(Bad):
            self.api.get("/api/log", {"after": "x"})

    def test_settings_get(self):
        r = self.get("/api/settings")
        self.assertEqual(set(r), {"settings", "server", "session", "folders", "expansion", "shown"})
        self.assertEqual(r["server"], "127.0.0.1:22720")
        self.assertEqual(r["session"], {"link": False, "debug": False})
        self.assertEqual(set(r["settings"]), set(settings.KEYS) - {"recent"})     # recent is in folders (§6)

    def test_unknown(self):
        self.assertEqual(self.api.get("/api/none", {})[0], 404)
        self.assertEqual(self.api.post("/api/none", {})[0], 404)

    # ------------------------------------------------------------------------------------ POST

    def test_link_switching(self):
        # Once a session, the owner confirms the project Smithbox has open (DataPiler cannot see it yet, P1).
        code, r, _ = self.post("/api/link", {"on": True})
        self.assertEqual(r, {"ok": False, "state": "off", "ask": {"text": api.PROJECT_ASK}})
        self.assertEqual(self.link.switched, [])
        code, r, _ = self.post("/api/link", {"on": True, "confirm_project": True})
        self.assertEqual(r, {"ok": True, "state": "on"})
        self.assertTrue(self.live.session.link)
        self.assertTrue(self.live.session.project_confirmed)
        code, r, _ = self.post("/api/link", {"on": False})
        self.assertEqual(r, {"ok": True, "state": "off"})
        self.assertFalse(self.live.session.link)
        code, r, _ = self.post("/api/link", {"on": True})                      # asked once only
        self.assertEqual(r, {"ok": True, "state": "on"})

    def test_a_new_project_folder_is_confirmed_again(self):
        self.post("/api/link", {"on": True, "confirm_project": True})
        self.assertTrue(self.live.session.project_confirmed)
        other = self.base / "Project2"
        other.mkdir()
        new = self.get("/api/settings")["settings"]
        new["project_dir"] = str(other)
        code, r, _ = self.post("/api/settings", {"settings": new})
        self.assertEqual(code, 200, r)
        self.assertFalse(self.live.session.project_confirmed)
        _, r, _ = self.post("/api/link", {"on": True})
        self.assertIn("ask", r)

    def test_link_refused_when_the_project_check_fails(self):
        inner = self.game / "proj"
        inner.mkdir()
        self.live.settings = Settings(game_dir=str(self.game), project_dir=str(inner))
        _, r, _ = self.post("/api/link", {"on": True})
        self.assertFalse(r["ok"])
        self.assertIn("inside the game's folder", r["why"])
        self.assertEqual(self.link.switched, [])

    def test_link_refused_while_the_game_runs(self):
        self.b.procs = [Proc("eldenring.exe", None)]
        _, r, _ = self.post("/api/link", {"on": True})
        self.assertFalse(r["ok"])
        self.assertIn("game is running", r["why"])
        self.assertEqual(self.link.switched, [])

    def test_link_refused_without_the_libraries(self):
        self.link.state = "no_libs"
        _, r, _ = self.post("/api/link", {"on": True})
        self.assertEqual(r["state"], "no_libs")
        self.assertIn("needs its libraries", r["why"])
        self.assertEqual(self.link.switched, [])
        with self.assertRaises(Bad):
            self.api.post("/api/link", {"on": "yes"})

    def test_quit_asks_while_a_job_runs(self):
        self.runner.busy_with = {"kind": "job", "id": JOB_ID, "title": "a title"}
        _, r, after = self.post("/api/quit", {"cancel_running": False})
        self.assertEqual(r, {"ok": False, "ask": {"text": "A job is running (%s). Quit cancels it between calls."
                                                          % JOB_ID}})
        self.assertIsNone(after)
        _, r, after = self.post("/api/quit", {"cancel_running": True})
        self.assertEqual(r, {"ok": True})
        after()
        self.assertEqual(self.stops, [1])
        self.runner.busy_with = None
        _, r, after = self.post("/api/quit", {})
        self.assertEqual(r, {"ok": True})

    def test_debug(self):
        _, r, _ = self.post("/api/debug", {"on": True})
        self.assertEqual(r, {"ok": True})
        self.assertTrue(self.live.session.debug)
        self.assertTrue(logbook.debug_on())
        self.post("/api/debug", {"on": False})
        self.assertFalse(logbook.debug_on())

    def test_extract(self):
        _, r, _ = self.post("/api/extract/run", {"rows": ["character_rows"], "load_maps": False, "confirm_maps": None})
        self.assertEqual(r, {"ok": True})
        self.assertEqual(self.runner.runs, [(["character_rows"], False, None)])
        with self.assertRaises(Bad):
            self.api.post("/api/extract/run", {"rows": ["no_such_row"]})
        with self.assertRaises(Bad):
            self.api.post("/api/extract/run", {"rows": "character_rows"})
        _, r, _ = self.post("/api/extract/cancel", {})
        self.assertEqual(r, {"ok": True})
        self.assertTrue(self.runner.cancelled)

    def test_drop_and_act(self):
        raw = b'{"format": "datapiler-job/1"}'
        _, r, _ = self.post("/api/jobs/drop", {"name": "job.json", "data": base64.b64encode(raw).decode()})
        self.assertEqual(r["ok"], True)
        self.assertEqual(r["again"], False)
        self.assertEqual(r["card"]["id"], JOB_ID)
        self.assertEqual(self.runner.added, [("job.json", raw)])
        with self.assertRaises(Bad):
            self.api.post("/api/jobs/drop", {"name": "job.json", "data": "%%% not base64"})
        with self.assertRaises(Bad):
            self.api.post("/api/jobs/drop", {"name": "job.json", "data": ""})
        _, r, _ = self.post("/api/jobs/act", {"id": JOB_ID, "what": "start", "confirm_maps": None})
        self.assertEqual(r["ok"], False)
        self.assertEqual(r["ask"]["maps"], 98)
        _, r, _ = self.post("/api/jobs/act", {"id": JOB_ID, "what": "start", "confirm_maps": 98})
        self.assertEqual(r, {"ok": True})
        with self.assertRaises(Bad):
            self.api.post("/api/jobs/act", {"id": "nobody", "what": "start"})

    def test_open_folder_off_windows(self):
        _, r, _ = self.post("/api/open", {"area": "share"})
        self.assertEqual(r, {"ok": False, "error": "Opening a folder works on Windows only."})
        self.assertEqual(self.b.opened, str(self.live.paths.share))
        with self.assertRaises(Bad):
            self.api.post("/api/open", {"area": "elsewhere"})

    def test_copy_path(self):
        f = self.live.paths.share / "roster-counts.json"
        f.write_bytes(b"{}")
        _, r, _ = self.post("/api/copy-path", {"name": "roster-counts.json"})
        self.assertEqual(r, {"ok": True})
        self.assertEqual(self.b.clipboard, str(f.resolve()))
        self.assertNotIn(self.tmp.name, json.dumps(r))
        with self.assertRaises(Bad):
            self.api.post("/api/copy-path", {"name": "../datapiler.port"})

    def test_check_6_runs_again_with_the_kept_row_counts(self):
        """DP8 (settled S19): Outputs runs check 6 with the counts the runner kept for that file at that sha256; a
        file DataPiler did not write, or one changed since, has none, so the real guard refuses it."""
        from datapiler import guard as guard_mod, textdb as textdb_mod
        share = self.live.paths.share
        db = textdb_mod.TextDB(self.live.paths.textdb)
        real = guard_mod.Guard(db, lambda: [])
        try:
            self.api.guard = real
            data = real.build(job_id="test-0001-rows", job_sha256="cd" * 32, provenance={
                "game_version": "1.99.0.0", "regulation_sha256": "ab" * 32, "expansion": False,
                "expansion_source": "owner", "language": "engus", "names": {}, "smithbox_build": "9.9.9",
                "datapiler": "0.1.0", "date": "2026-11-08"},
                tables=[{"name": "picked", "columns": [("id", "int")], "rows": [[9000001], [9000002]]}], notes=[])
            counts = {"picked": ("id", 20, "NpcParam")}
            w = real.write(share, "picked-rows", data, declared={"picked": ["id"]}, coverage=counts)
            guard_mod.record_counts(self.live.paths.share_counts, w.name, w.sha256, counts)
            (share / "copied-rows.json").write_bytes(data)         # the same bytes under a name DataPiler never wrote
            got = {f["name"]: (f["ok"], f["failed"]) for f in self.get("/api/outputs")["share"]}
            self.assertEqual(got, {"picked-rows.json": (True, None), "copied-rows.json": (False, 6)})
            v = self.get("/api/share", name="copied-rows.json")
            self.assertEqual(v["checks"][5], {"check": 6, "name": "Coverage", "ok": False,
                                              "where": guard_mod.NO_COUNTS})
            # the counts the runner keeps for a later write of the file are read again (the cache's key holds them)
            guard_mod.record_counts(self.live.paths.share_counts, w.name, w.sha256, {"picked": ("id", 3, "NpcParam")})
            got = {f["name"]: (f["ok"], f["failed"]) for f in self.get("/api/outputs")["share"]}
            self.assertEqual(got["picked-rows.json"], (False, 6))
        finally:
            real.close()
            db.close()

    def test_a_file_that_fails_the_guard_now_is_never_vouched_for(self):
        """Found by the security review: Outputs listed every share-named file under "Passed the guard" and Copy
        path put its path on the clipboard unchecked - a file DataPiler did not write, or one changed since."""
        share = self.live.paths.share
        (share / "roster-counts.json").write_bytes(b'{"good": 1}')
        foreign = b'{"foreign": 1}'
        (share / "foreign.json").write_bytes(foreign)
        self.guard.fail[foreign] = 4
        o = self.get("/api/outputs")
        got = {f["name"]: (f["ok"], f["failed"]) for f in o["share"]}
        self.assertEqual(got, {"roster-counts.json": (True, None), "foreign.json": (False, 4)})
        self.b.clipboard = None
        _, r, _ = self.post("/api/copy-path", {"name": "foreign.json"})
        self.assertEqual(r, {"ok": False, "error": "The file does not pass the guard now: check 4. Never share it."})
        self.assertIsNone(self.b.clipboard)
        # Changed since: the next listing checks it again.
        (share / "roster-counts.json").write_bytes(foreign)
        os.utime(share / "roster-counts.json", ns=(1, 1))
        o = self.get("/api/outputs")
        self.assertEqual({f["name"]: f["ok"] for f in o["share"]}, {"roster-counts.json": False, "foreign.json": False})
        # Unchanged files are not checked again until the text database changes.
        calls = self.guard.calls
        self.get("/api/outputs")
        self.assertEqual(self.guard.calls, calls)
        self.guard.fail.clear()
        events.emit("textdb.changed", containers=1, entries=1)
        o = self.get("/api/outputs")
        self.assertEqual(self.guard.calls, calls + 2)
        self.assertTrue(all(f["ok"] for f in o["share"]))
        # Over the guard's size: check 5, and no path on the clipboard.
        big = share / "huge.json"
        big.write_bytes(b" " * (self.api._cap() + 1))
        _, r, _ = self.post("/api/copy-path", {"name": "huge.json"})
        self.assertIn("check 5", r["error"])
        self.assertIsNone(self.b.clipboard)

    def test_settings_post(self):
        new = self.get("/api/settings")["settings"]
        new["port"] = 8831
        seen = []
        unsub = events.subscribe("settings.saved", lambda t, d: seen.append(t))
        try:
            code, r, _ = self.post("/api/settings", {"settings": new})
        finally:
            unsub()
        self.assertEqual((code, r), (200, {"ok": True, "next_start": ["port"]}))
        self.assertEqual(seen, ["settings.saved"])
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["port"], 8831)
        self.assertEqual(self.live.settings.port, 8831)
        bad = dict(new, project_dir=str(self.game / "inner"))
        code, r, _ = self.post("/api/settings", {"settings": bad})
        self.assertEqual(code, 400)
        self.assertEqual(r["field"], "project_dir")
        self.runner.busy_with = {"kind": "job", "id": JOB_ID, "title": "t"}
        code, r, _ = self.post("/api/settings", {"settings": dict(new, share_dir="share2")})
        self.assertEqual((code, r["field"]), (400, "share_dir"))

    def test_the_workspace_moves_at_the_next_start(self):
        """Found by the correctness review: the text database stayed open in the old workspace while the inbox, the
        runner and Outputs moved to the new one at once."""
        p = self.live.paths
        old_ws = p.workspace
        new = dict(self.get("/api/settings")["settings"], workspace_dir="ws2")
        self.runner.busy_with = {"kind": "job", "id": JOB_ID, "title": "t"}         # no longer refused while busy
        code, r, _ = self.post("/api/settings", {"settings": new})
        self.assertEqual(code, 200, r)
        self.assertEqual(r["next_start"], ["workspace_dir"])
        self.assertEqual(r["note"], api.WORKSPACE_MOVES)
        self.assertEqual(self.live.settings.workspace_dir, "ws2")                    # saved for the next start
        self.assertEqual(self.live.paths.workspace, old_ws)                           # in use until then
        self.assertEqual(self.live.paths.textdb, p.textdb)
        self.assertFalse((self.root / "ws2").exists())
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["workspace_dir"], "ws2")
        # Saved again unchanged: still waiting for the next start, said again.
        code, r, _ = self.post("/api/settings", {"settings": new})
        self.assertEqual(r["next_start"], ["workspace_dir"])
        # Back to the folder in use: nothing waits.
        code, r, _ = self.post("/api/settings", {"settings": dict(new, workspace_dir="workspace")})
        self.assertEqual(r, {"ok": True, "next_start": []})
        # A share folder inside the workspace in use is refused, though it is outside the new one.
        code, r, _ = self.post("/api/settings", {"settings": dict(new, share_dir="workspace/share")})
        self.assertEqual((code, r["field"]), (400, "share_dir"))

    def test_log_share(self):
        log = logbook.get("job")
        _, start = logbook.lines_after(0, limit=0)
        log.info("an ordinary line: %s rows", 12)
        _, mid = logbook.lines_after(0, limit=0)
        _, r, _ = self.post("/api/log/share", {"after": start, "upto": mid, "levels": ["INFO", "WARN", "ERROR"],
                                               "sources": ["job"]})
        self.assertTrue(r["ok"])
        self.assertIn("an ordinary line: 12 rows", r["text"])
        log.info("a line with a planted text: %s", own(PLANTED))
        _, last = logbook.lines_after(0, limit=0)
        _, r, _ = self.post("/api/log/share", {"after": start, "upto": last, "levels": ["INFO"], "sources": ["job"]})
        self.assertEqual(r, {"ok": False, "refused": {"check": 3, "line": last}})
        _, r, _ = self.post("/api/log/share", {"after": start, "upto": last, "levels": ["INFO"], "sources": ["app"]})
        self.assertTrue(r["ok"])
        crafted = [{"seq": 41, "t": "2026-11-08 08:00:00.000", "level": "INFO", "src": "link",
                    "msg": "from 198.51.100.40"},
                   {"seq": 42, "t": "2026-11-08 08:00:00.000", "level": "INFO", "src": "link",
                    "msg": "by zorblax"}]
        with mock.patch.object(logbook, "lines_after", lambda seq, limit=1000: ([x for x in crafted if x["seq"] > seq], 42)):
            _, r, _ = self.post("/api/log/share", {"after": 0, "upto": 42, "levels": ["INFO"], "sources": ["link"]})
            self.assertEqual(r, {"ok": False, "refused": {"check": 4, "line": 41}})
            _, r, _ = self.post("/api/log/share", {"after": 41, "upto": 42, "levels": ["INFO"], "sources": ["link"]})
        self.assertEqual(r, {"ok": False, "refused": {"check": 4, "line": 42}})

    def test_owner_rules_for_a_line(self):
        words = ["zorblax", "QUENTIN-RIG"]
        for bad in ("C:\\Games", "at d:/x", "\\\\server\\share", "~/x", "zorblax", "ZORBLAX's", "quentin-rig",
                    "203.0.113.1", "fe80::1",
                    # the guard's check 4 patterns: whatever stands between the name's parts, `_` as a separator
                    "quentin_rig.json", "quentinrig", "x_zorblax_y"):
            self.assertTrue(api.owner_hit("a line " + bad, words), bad)
        for ok in ("<WORKSPACE>\\inbox", "Page: http://127.0.0.1:8831/", "zorblaxian", "08:42:01.123",
                   "NpcParam: 2,105 rows read in 0.4 s", "quentin_rigs", "xquentin-rig"):
            self.assertFalse(api.owner_hit(ok, words), ok)


class FakeUpdater:
    """UPDATE's Updater as the three routes see it (build plan 0.2 §3.3)."""

    def __init__(self):
        self.posts = []
        self.closed = False

    def get(self):
        return {"state": "idle", "this": datapiler.VERSION}

    def result(self):
        return {"state": None}

    def post(self, body):
        self.posts.append(body)
        if body.get("action") == "install":
            return 200, {"ok": True, "state": "restarting", "to": "9.9.9"}, self.close
        return 400, {"error": "not now"}, None

    def close(self):
        self.closed = True


class FakeFolders:
    def __init__(self):
        from datapiler import detect
        self.detect_mod = detect
        self.cands = {}
        self.asked = []
        self.closed = False

    def found(self, want):
        return list(self.cands.get(want, []))

    def notes(self, want):
        return ["Smithbox is not running, so its folder cannot be read - start Smithbox, then Detect again"] \
            if want == "smithbox" else []

    def detect(self, want):
        self.asked.append(want)
        return self.found(want)

    def close(self):
        self.closed = True


class FoldersApiTest(ApiBase):
    """Build plan 0.2 §6: the folder endpoints, the update routes and the mask."""

    def setUp(self):
        super().setUp()
        from datapiler import detect
        self.detect = detect
        self.folders = FakeFolders()
        self.updates = FakeUpdater()
        self.api.close()
        self.api = Api(live=self.live, status=self.status, link=self.link, runner=self.runner, textdb=self.textdb,
                       guard=self.guard, inbox=FakeInbox(), catalogue=FakeCatalogue(),
                       stop=lambda: self.stops.append(1), libs=True, updates=self.updates, folders=self.folders)
        self.sb = self.base / "Tools" / "Smithbox"
        self.sb.mkdir(parents=True)
        (self.sb / "Smithbox.Vulkan.exe").write_bytes(b"")

    def cand(self, value, *sources, name=None, marked=False, detail=None):
        return self.detect.Candidate(str(value), tuple(sources), name, marked, detail)

    def bad(self, path, body):
        """A 400: an answer the API gives, or a Bad the server answers as 400 {"error"}."""
        try:
            code, r, _ = self.post(path, body)
        except Bad as e:
            return {"error": str(e)}
        self.assertEqual(code, 400, (path, body, r))
        return r

    def test_the_update_routes_forward_and_answer_404_without_an_updater(self):
        self.assertEqual(self.get("/api/update"), {"state": "idle", "this": datapiler.VERSION})
        self.assertEqual(self.get("/api/update-result"), {"state": None})
        code, r, after = self.post("/api/update", {"action": "install"})
        self.assertEqual((code, r), (200, {"ok": True, "state": "restarting", "to": "9.9.9"}))
        self.assertIsNotNone(after)
        self.assertEqual(self.post("/api/update", {"action": "check", "fresh": False})[:2],
                         (400, {"error": "not now"}))
        self.assertEqual(self.updates.posts, [{"action": "install"}, {"action": "check", "fresh": False}])
        bare = Api(live=self.live, status=self.status, link=self.link, runner=self.runner, textdb=self.textdb,
                   guard=self.guard, inbox=FakeInbox(), catalogue=FakeCatalogue(), stop=lambda: None, libs=True)
        self.assertEqual(bare.get("/api/update", {})[0], 404)
        self.assertEqual(bare.get("/api/update-result", {})[0], 404)
        self.assertEqual(bare.post("/api/update", {"action": "check"})[0], 404)
        bare.close()
        self.api.close()
        self.assertTrue(self.updates.closed and self.folders.closed)

    def test_settings_view(self):
        old = self.base / "Old" / "Smithbox"
        self.live.settings = settings.with_values(self.live.settings, smithbox_dir=str(self.sb),
                                                  recent={"smithbox_dir": (str(old),), "game_dir": (),
                                                          "project_dir": ()})
        self.folders.cands = {"smithbox": [self.cand(self.sb, "running_smithbox")],
                              "expansion": [self.cand("yes", "steam_manifest", detail=own("DLC app 9000020 installed"))]}
        r = self.get("/api/settings")
        f = r["folders"]["smithbox_dir"]
        self.assertEqual(f["shown"], str(self.sb))
        self.assertEqual(f["check"], {"ok": True, "text": "Smithbox.Vulkan.exe is here · build not read", "mark": True})
        self.assertEqual(f["found"], [{"path": str(self.sb), "shown": str(self.sb), "sources": ["running_smithbox"],
                                       "tags": ["the running Smithbox"], "in_use": True, "check": f["check"]}])
        self.assertEqual(f["recent"], [{"path": str(old), "shown": str(old)}])
        self.assertTrue(f["notes"])
        self.assertEqual(r["folders"]["game_dir"]["check"]["text"], "eldenring.exe is here · version not read")
        self.assertEqual(r["expansion"]["found"], [{"value": "yes", "sources": ["steam_manifest"],
                                                     "tags": ["Steam's app manifest"], "in_use": False,
                                                     "detail": "DLC app 9000020 installed"}])
        self.assertEqual(r["shown"], {"workspace_dir": "workspace", "share_dir": "share"})
        self.assertNotIn("recent", r["settings"])
        self.assertFalse(r["settings"]["mask_paths"])

    def test_settings_post_lays_its_keys_over_and_refuses_recent(self):
        code, r, _ = self.post("/api/settings", {"settings": {"port": 8832}})
        self.assertEqual(code, 200, r)
        self.assertEqual((self.live.settings.port, self.live.settings.game_dir), (8832, str(self.game)))
        r = self.bad("/api/settings", {"settings": {"recent": {"game_dir": []}}})
        self.assertEqual(r, {"error": "not a setting the page sets", "field": "recent"})
        self.assertEqual(self.bad("/api/settings", {"settings": {}, "extra": 1})["error"], "not a key this request takes")
        # the project rules, whatever the page does (S32)
        r = self.bad("/api/settings", {"settings": {"project_dir": str(self.base)}})
        self.assertEqual(r["field"], "project_dir")
        r = self.bad("/api/settings", {"settings": {"project_dir": str(self.root / "p")}})
        self.assertIn("DataPiler's folder", r["error"])

    def test_settings_one(self):
        seen = []
        unsub = events.subscribe("settings.saved", lambda t, d: seen.append(t))
        try:
            self.live.session.project_confirmed = True
            other = self.base / "Other project"
            other.mkdir()
            code, r, _ = self.post("/api/settings/one", {"key": "project_dir", "value": str(other)})
            self.assertEqual((code, r), (200, {"ok": True}))
            self.assertEqual(self.live.settings.project_dir, str(other.resolve()))
            self.assertFalse(self.live.session.project_confirmed)   # asked again, as Save does
            self.assertEqual(self.live.settings.recent["project_dir"], (str(other.resolve()), str(self.project)))
            saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["project_dir"], str(other.resolve()))
            self.assertEqual(seen, ["settings.saved"])
        finally:
            unsub()
        # a ✗ check refuses with its words; a ! saves
        r = self.bad("/api/settings/one", {"key": "game_dir", "value": str(self.project)})
        self.assertEqual(r, {"error": "no eldenring.exe here - the game's folder is the Game folder inside ELDEN RING",
                             "field": "game_dir"})
        r = self.bad("/api/settings/one", {"key": "project_dir", "value": str(self.game / "mod")})
        self.assertEqual(r["field"], "project_dir")
        self.assertEqual(self.post("/api/settings/one", {"key": "smithbox_dir", "value": str(self.base / "x")})[0], 200)
        self.assertEqual(self.post("/api/settings/one", {"key": "smithbox_dir", "value": ""})[0], 200)
        self.assertEqual(self.post("/api/settings/one", {"key": "expansion", "value": "yes"})[0], 200)
        self.assertEqual(self.live.settings.expansion, "yes")
        self.assertEqual(self.post("/api/settings/one", {"key": "mask_paths", "value": True})[0], 200)
        self.assertTrue(self.live.settings.mask_paths)
        for body in ({"key": "recent", "value": []}, {"key": "port", "value": 1}, {"key": "expansion", "value": "x"},
                     {"key": "mask_paths", "value": "yes"}, {"key": "game_dir", "value": 5},
                     {"key": "game_dir", "value": "C:\\x\x07"}, {"key": "game_dir", "value": "C:\\" + "x" * 1100},
                     {"key": "game_dir", "value": "", "more": 1}):
            with self.subTest(body=body):
                self.bad("/api/settings/one", body)

    def test_a_link_is_saved_as_the_folder_it_resolves_to(self):
        target = self.base / "Real project"
        target.mkdir()
        link = self.base / "Project link"
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this system makes no symlinks here")
        self.assertEqual(self.post("/api/settings/one", {"key": "project_dir", "value": str(link)})[0], 200)
        self.assertEqual(self.live.settings.project_dir, str(target.resolve()))
        # a typed path is saved as typed (S34)
        new = dict(self.get("/api/settings")["settings"], project_dir=str(link))
        self.assertEqual(self.post("/api/settings", {"settings": new})[0], 200)
        self.assertEqual(self.live.settings.project_dir, str(link))

    def test_detect(self):
        self.folders.cands = {"game": [self.cand(self.game, "smithbox_record", "steam_library", name="Mine",
                                                 marked=True)]}
        code, r, _ = self.post("/api/detect", {"want": "game"})
        self.assertEqual(code, 200)
        self.assertEqual(self.folders.asked, ["game"])
        self.assertEqual(r["want"], "game")
        self.assertEqual(r["found"][0]["tags"], ["Smithbox's project record, marked to open",
                                                 "Steam's library list agrees"])
        self.assertEqual((r["found"][0]["name"], r["found"][0]["marked"], r["found"][0]["in_use"]), ("Mine", True, True))
        self.assertEqual(r["notes"], [])
        for body in ({"want": "everything"}, {}, {"want": "game", "x": 1}):
            self.bad("/api/detect", body)

    def test_dirs_endpoints(self):
        got = self.post("/api/dirs", {"path": str(self.base), "want": "game"})[1]
        self.assertIn("Game", [d["name"] for d in got["dirs"]])
        self.assertEqual(self.post("/api/dirs", {"path": "", "want": "game"})[1]["shown"], "This PC")
        self.assertEqual(self.post("/api/dirs", {"path": "\\\\server\\share", "want": "game"})[1],
                         {"refused": "network paths can be typed in the field, not browsed"})
        r = self.post("/api/dirs/check", {"want": "project", "path": str(self.project)})[1]
        self.assertEqual(r, {"ok": True, "text": "outside the game's folder", "mark": False})
        r = self.post("/api/dirs/new", {"parent": str(self.base), "name": "ER project", "want": "project"})[1]
        self.assertEqual(r, {"path": str(self.base / "ER project"), "shown": str(self.base / "ER project")})
        self.assertIn("refused", self.post("/api/dirs/new", {"parent": str(self.game), "name": "m", "want": "project"})[1])
        for path, body in (("/api/dirs", {"path": 5, "want": "game"}), ("/api/dirs", {"path": "", "want": "x"}),
                           ("/api/dirs", {"path": "", "want": "game", "extra": 1}),
                           ("/api/dirs", {"path": "C:\\" + "x" * 1100, "want": "game"}),
                           ("/api/dirs", {"path": "C:\\a\nb", "want": "game"}),
                           ("/api/dirs/new", {"parent": str(self.base), "name": "x", "want": "game"}),
                           ("/api/dirs/check", {"want": "expansion", "path": ""}),
                           ("/api/dirs/forget", {"key": "workspace_dir"})):
            with self.subTest(path=path, body=body):
                self.bad(path, body)

    def test_forget(self):
        self.live.settings = settings.with_values(self.live.settings, recent={"smithbox_dir": (str(self.sb),),
                                                                              "game_dir": (str(self.game),),
                                                                              "project_dir": ()})
        self.assertEqual(self.post("/api/dirs/forget", {"key": "smithbox_dir"})[1], {"ok": True})
        self.assertEqual(self.live.settings.recent["smithbox_dir"], ())
        self.assertEqual(self.live.settings.recent["game_dir"], (str(self.game),))
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["recent"]["smithbox_dir"], [])

    def test_with_the_mask_on_no_answer_shows_an_invented_real_folder(self):
        """DP14 (S35): every path the page draws is the log's mask of it; Status's details too."""
        api.set_masks(self.live)
        found_only = self.base / "Found" / "Smithbox"
        found_only.mkdir(parents=True)
        (found_only / "Smithbox.exe").write_bytes(b"")
        self.live.settings = settings.with_values(self.live.settings, smithbox_dir=str(self.sb), mask_paths=True,
                                                  recent={"smithbox_dir": (str(self.base / "Old"),), "game_dir": (),
                                                          "project_dir": ()})
        api._learn_recent(self.live.settings)
        api.set_masks(self.live)
        logbook.learn_found([str(found_only)])
        self.folders.cands = {"smithbox": [self.cand(found_only, "running_smithbox")],
                              "project": [self.cand(self.project, "smithbox_record", name="Secret name")]}
        real = str(self.base)

        def shown_values(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("shown", "detail", "name") and isinstance(v, str):
                        yield v
                    else:
                        yield from shown_values(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from shown_values(v)

        answers = [self.get("/api/settings"), self.get("/api/state"),
                   self.post("/api/detect", {"want": "project"})[1],
                   self.post("/api/dirs", {"path": str(self.game), "want": "game"})[1]]
        for a in answers:
            for v in shown_values(a):
                self.assertNotIn(real, v)
        r = answers[0]
        self.assertEqual(r["folders"]["smithbox_dir"]["shown"], "<SMITHBOX>")
        self.assertEqual(r["folders"]["smithbox_dir"]["found"][0]["shown"], "<FOUND>")
        self.assertEqual(r["folders"]["game_dir"]["shown"], "<GAME>")
        self.assertEqual(r["folders"]["smithbox_dir"]["recent"][0]["shown"], "<FOUND>")
        self.assertNotIn("name", answers[2]["found"][0])
        self.assertEqual(answers[3]["crumbs"][0]["name"], "<GAME>")
        self.assertEqual(r["shown"]["workspace_dir"], "workspace")
        # the Status details masked; the real path stays beside it for Use only
        details = [c["detail"] for card in answers[1]["status"].values() if isinstance(card, list) for c in card
                   if c.get("detail")]
        self.assertTrue(details)
        self.assertTrue(all(real not in d for d in details))

    def test_status_offers_one_found_folder_with_use(self):
        """DP15: the Smithbox folder blank and one place found: Status says so and offers it."""
        self.live.settings = settings.with_values(self.live.settings, smithbox_dir="")
        self.folders.cands = {"smithbox": [self.cand(self.sb, "running_smithbox")]}
        card = {c["id"]: c for c in self.get("/api/state")["status"]["smithbox"]}
        self.assertEqual(card["installed"]["ok"], "warn")
        self.assertEqual(card["installed"]["text"], "Found 1 place - confirm it in Settings")
        self.assertEqual(card["installed"]["use"], {"key": "smithbox_dir", "path": str(self.sb), "shown": str(self.sb)})
        self.assertEqual(self.live.settings.smithbox_dir, "")       # nothing saved by itself


if __name__ == "__main__":
    unittest.main()
