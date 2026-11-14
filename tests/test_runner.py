"""The runner (build plan §4.8, §8.3), against a fake link of its own with invented rows: ops in order with progress;
waiting while the link is off and while the game runs, going on at link.state; Cancel between calls; a failure
writes no share file; the job log; state saved and loaded (running becomes stopped); Extract server rows before guided
rows; the map question above ten; Remove. Every number and text is invented."""

import _repo  # noqa: F401

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from dataclasses import replace

from datapiler import catalogue, events, guard, jobs, link, logbook, paths, runner, textdb
from datapiler.game import GameRunning
from datapiler.logbook import own

FIXTURES = os.path.join(_repo.ROOT, "tests", "fixtures")
PROVENANCE = {"game_version": "1.99.0.0", "regulation_sha256": "ab" * 32, "expansion": True,
              "expansion_source": "owner", "language": "engus", "smithbox_build": "9.9.9", "datapiler": "0.1.0",
              "date": "2026-11-08"}
SETS = {"character_names": (("item", 9001),), "place_names": (("item", 9002),)}
TITLE = "Roster: named characters per team"
PLANTED = ("Quillon", "Lamplighter", "Serevan", "Ashgrove", TITLE)


def fixture(*parts: str) -> bytes:
    with open(os.path.join(FIXTURES, *parts), "rb") as f:
        return f.read()


def job_bytes(ops: list, jid: str = "test-0100-runner", title: str = "Runner test") -> bytes:
    return json.dumps({"format": "datapiler-job/1", "id": jid, "title": title, "ops": ops}).encode()


class FakeLink:
    """The part of link.Link the runner uses, with invented rows; records every call."""

    def __init__(self):
        self.state = "on"
        self.calls: list[tuple] = []
        self.npc = {9000000 + i: {"nameId": (9000000, 9000001, 9000004, -1)[i % 4], "teamType": (0, 6)[i % 2],
                                  "npcType": i % 3} for i in range(20)}
        self.talk = {9000000 + i: {"msgId": 9500000 + i if i % 2 == 0 else -1} for i in range(10)}
        self.loaded = ["m99_00_00_00", "m99_00_00_01"]
        self.every_map: list[str] | None = None   # every map of the project, when a test sets it
        self.extra_placements: list[tuple[int, int]] = []   # (entity id, row) added to each map's placements
        self.fail: Exception | None = None
        self.drop_at: int | None = None          # the link goes off after this many rows, once
        self.started = threading.Event()
        self.proceed: threading.Event | None = None

    def _check(self):
        if self.state == "off":
            raise link.LinkOff("the server link is off")
        if self.state == "blocked":
            raise link.LinkBlocked("the game is running")

    def _table(self, param):
        return {"NpcParam": self.npc, "TalkParam": self.talk}.get(param, {9000000: {}, 9000001: {}})

    def list_param_rows(self, param):
        self._check()
        self.calls.append(("ListParamRows", param))
        return sorted(self._table(param))

    def get_param_rows(self, param, row_ids, fields, *, cancel=None, progress=None):
        out = []
        for k, rid in enumerate(row_ids):
            if cancel is not None and cancel.is_set():
                raise link.LinkCancelled("cancelled")
            self._check()
            if self.fail is not None:
                raise self.fail
            if self.drop_at is not None and k == self.drop_at:
                self.drop_at = None
                self.state = "off"
                raise link.LinkOff("the server link is off")
            self.calls.append(("GetParamRows", param, rid))
            row = self._table(param).get(rid)
            if row is not None:
                out.append(dict({"id": rid}, **{f: row[f] for f in fields if f != "id"}))
            if progress is not None:
                progress(k + 1, len(row_ids))
            if self.proceed is not None and k == 0:
                self.started.set()
                self.proceed.wait(5)
        return out

    def loaded_maps(self):
        self._check()
        self.calls.append(("SearchObjects",))
        return list(self.loaded)

    def map_ids(self):
        return self.every_map

    def all_maps(self):
        self._check()
        if self.every_map is not None:
            return list(self.every_map)
        return sorted(set(self.loaded) | {"m99_00_00_%02d" % i for i in range(15)})

    def is_loaded(self, map_id):
        self._check()
        return map_id in self.loaded

    def open_maps(self, map_ids, *, cancel=None, progress=None, timeout=None, first_timeout=None):
        self._check()
        self.calls.append(("OpenResource", tuple(map_ids)))
        for k, m in enumerate(map_ids):
            if m not in self.loaded:
                self.loaded.append(m)
            if progress is not None:
                progress(k + 1, len(map_ids))
        return len(map_ids)

    def placements(self, map_id):
        self._check()
        if map_id not in self.loaded:
            raise link.LinkError("the map %s is not loaded in Smithbox" % map_id)
        self.calls.append(("BatchGetObjects", map_id))
        return [link.Placement(map=link.map_key(map_id), entity_id=9001000 + i, npc_param_id=9000000 + i,
                               talk_id=9000000 + i, model=9990 + i % 3) for i in range(3)] + \
            [link.Placement(map=link.map_key(map_id), entity_id=e, npc_param_id=r, talk_id=-1, model=9999)
             for e, r in self.extra_placements]


def wait_for(pred, timeout: float = 6.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


class RunnerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = paths.resolve(Path(self.tmp.name), "workspace", "share")
        paths.ensure(self.p)
        self.sets = mock.patch.dict(textdb.TEXT_SETS, SETS)
        self.sets.start()
        self.db = textdb.TextDB(self.p.textdb)
        with open(os.path.join(FIXTURES, "text-exports", "item-invented.json"), encoding="utf-8") as f:
            self.db.import_export(json.load(f), container="item", language="engus", sha256="0" * 64)
        self.guard = guard.Guard(self.db, lambda: ["velkorquist"])
        self.link = FakeLink()
        self.game_running = False
        self.provenance = lambda: dict(PROVENANCE)
        self.runners = []
        self.r = self.new_runner()
        self.events = []
        self.unsub = events.subscribe("", lambda t, d: self.events.append((t, d)))

    def new_runner(self) -> runner.Runner:
        r = runner.Runner(lambda: self.p, self.link, self.db, self.guard, lambda: self.provenance(),
                          lambda: GameRunning(self.game_running, None), lambda: "engus")
        self.runners.append(r)
        return r

    def tearDown(self):
        self.unsub()
        if self.link.proceed is not None:
            self.link.proceed.set()
        for r in self.runners:
            r.stop(cancel=True, timeout=3)
        self.guard.close()
        self.db.close()
        self.sets.stop()
        self.tmp.cleanup()

    def card(self, jid: str, r: runner.Runner | None = None) -> dict:
        return next(c for c in (r or self.r).cards() if c["id"] == jid)

    def run_job(self, raw: bytes, *, state: str = "done") -> dict:
        card, again = self.r.add("job.json", raw)
        self.assertFalse(again)
        self.assertEqual(self.r.act(card["id"], "start"), {"ok": True})
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == state), self.card(card["id"]))
        return self.card(card["id"])

    def share_files(self) -> list[str]:
        return sorted(os.listdir(self.p.share))

    def link_on(self):
        self.link.state = "on"
        events.emit("link.state", state=own("on"), why=None)


class JobRunTest(RunnerBase):
    def test_ops_in_order_with_progress(self):
        raw = fixture("job-files", "good-example.json")
        card = self.run_job(raw)
        self.assertEqual((self.p.jobs / "en-0007-roster-counts" / "job.json").read_bytes(), raw)
        self.assertEqual([o["state"] for o in card["ops"]], ["done"] * 5)
        self.assertEqual([o["op"] for o in card["ops"]], ["fetch_rows", "fetch_rows", "join_names", "count",
                                                          "write_share"])
        ops = [(d["n"], d["state"]) for t, d in self.events if t == "job.op"]
        self.assertEqual([n for n, s in ops if s == "done"], [0, 1, 2, 3, 4])
        progress = [(d["done"], d["of"]) for t, d in self.events if t == "job.op" and d["n"] == 0
                    and d["state"] == "running" and d["of"]]
        self.assertIn((1, 20), progress)
        self.assertIn((20, 20), progress)
        # the calls in the job's order
        kinds = [c[:2] for c in self.link.calls]
        self.assertEqual(kinds[0], ("ListParamRows", "NpcParam"))
        self.assertEqual(kinds.index(("ListParamRows", "TalkParam")), 21)
        self.assertEqual(len(kinds), 32)
        # the result
        share = card["result"]["share"]
        self.assertEqual(share["name"], "roster-counts.json")
        self.assertEqual(self.share_files(), ["roster-counts.json"])
        data = (self.p.share / "roster-counts.json").read_bytes()
        self.assertEqual(share["size"], len(data))
        doc = json.loads(data)
        self.assertEqual(doc["tables"], [{"name": "per_team", "columns": [{"name": "teamType", "type": "int"},
                                                                         {"name": "count", "type": "int"}],
                                          "rows": [[0, 10], [6, 5]]}])
        self.assertEqual(doc["job"]["sha256"], card["sha256"])
        # the provenance: Status's block, and the names' wrapper leads verified at join_names (3 of 3 numbers)
        self.assertEqual(doc["provenance"], dict(PROVENANCE, names={"character_names": {
            "wrappers": [9001], "verified": True, "resolved": 1.0}}))
        self.assertTrue(all(r.ok for r in self.guard.check(data, declared={"per_team": ["teamType", "count"]},
                                                           coverage={"per_team": None})))
        # the row counts kept for Outputs' check 6: a count by teamType, measured by its groups against NpcParam
        self.assertEqual(guard.counts_for(self.p.share_counts, "roster-counts.json", share["sha256"]),
                         {"per_team": (None, 20, "NpcParam")})
        self.assertEqual(card["result"]["failed"], None)
        self.assertEqual(self.r.made_by()["roster-counts.json"], "en-0007-roster-counts")

    def test_every_op_and_the_local_file(self):
        card = self.run_job(fixture("job-files", "good-every-op.json"))
        self.assertEqual(card["result"]["local"], ["npc-named.json"])
        local = self.p.local / "test-0001-every-op" / "npc-named.json"
        doc = json.loads(local.read_text(encoding="utf-8"))
        self.assertEqual(doc["format"], "datapiler-local/1")
        named = doc["tables"][0]
        self.assertEqual([c["name"] for c in named["columns"]], ["id", "nameId", "name"])
        self.assertIn([9000000, 9000000, "Quillon Marrowgate"], named["rows"])
        self.assertIn([9000003, -1, None], named["rows"])
        self.assertEqual(doc["tables"][1]["rows"], [[9990], [9991], [9992]])
        share = json.loads((self.p.share / "every-op-counts.json").read_bytes())
        self.assertNotIn(b"Quillon", (self.p.share / "every-op-counts.json").read_bytes())
        per_team = share["tables"][0]["rows"]
        # teamType >= 6, named, npcType in 1..3, nameId > -1: odd rows with i % 4 == 1 and npcType i % 3 in (1, 2)
        expect = sum(1 for i in range(20) if i % 2 == 1 and i % 4 == 1 and i % 3 in (1, 2))
        self.assertEqual(per_team, [[6, True, expect]])
        self.assertEqual(share["tables"][1]["rows"], [[6]])
        self.assertIn(("OpenResource", ("m99_00_00_00", "m99_00_00_01")), self.link.calls)
        self.assertEqual(self.r.made_by()["local/test-0001-every-op/npc-named.json"], "test-0001-every-op")
        talk = [c for c in self.link.calls if c[:2] == ("GetParamRows", "TalkParam")]
        self.assertEqual(len(talk), 3)
        # Its rows are named by id, but the job writes a share file: check 6 measures against all of TalkParam's rows
        self.assertIn(("ListParamRows", "TalkParam"), self.link.calls)

    def test_the_job_log(self):
        logs = Path(self.tmp.name) / "logs"
        logbook.setup(logs, max_bytes=1 << 20, keep=1, console=False)
        try:
            self.run_job(fixture("job-files", "good-example.json"))
            text = (logs / "jobs" / "en-0007-roster-counts.log").read_text(encoding="utf-8")
            self.assertIn("started: 5 operations", text)
            self.assertIn("op 0 fetch_rows: 20 rows", text)
            self.assertIn("done in", text)
            main = (logs / "datapiler.log").read_text(encoding="utf-8")
            for s in PLANTED:
                self.assertNotIn(s, text)
                self.assertNotIn(s, main)
        finally:
            logbook.shutdown()

    def test_nothing_planted_reaches_the_ring_or_an_event(self):
        _, seq = logbook.lines_after(0, limit=0)
        self.run_job(fixture("job-files", "good-every-op.json"))
        lines, _ = logbook.lines_after(seq)
        self.assertTrue(lines)
        for x in lines:
            for s in PLANTED:
                self.assertNotIn(s, x["msg"])
        for t, d in self.events:
            for v in d.values():
                self.assertTrue(v is None or isinstance(v, (bool, int, float, logbook.Own)), (t, d))


class WaitTest(RunnerBase):
    def test_waiting_while_the_link_is_off(self):
        self.link.state = "off"
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "waiting"))
        self.assertEqual(self.card(card["id"])["wait"], "the server link is off")
        time.sleep(0.2)
        self.assertEqual(self.link.calls, [])
        self.link_on()
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "done"))
        self.assertIsNone(self.card(card["id"])["wait"])

    def test_waiting_while_the_game_runs(self):
        self.game_running = True
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(wait_for(lambda: self.card(card["id"])["wait"] == "the game is running"))
        self.assertEqual(self.link.calls, [])
        self.game_running = False
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "done"))

    def test_waiting_without_the_libraries(self):
        self.link.state = "no_libs"
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(wait_for(lambda: self.card(card["id"])["wait"] ==
                                 "the server link needs its libraries - restart DataPiler and answer Y"))

    def test_the_link_lost_in_the_middle(self):
        self.link.drop_at = 5
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "waiting"))
        self.link_on()
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "done"))
        npc = [c for c in self.link.calls if c[:2] == ("GetParamRows", "NpcParam")]
        self.assertEqual(len(npc), 5 + 20)                           # the op ran again from its start


class CancelTest(RunnerBase):
    def test_cancel_between_calls(self):
        self.link.proceed = threading.Event()
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(self.link.started.wait(5))
        self.assertEqual(self.r.busy(), {"kind": "job", "id": "en-0007-roster-counts", "title": TITLE})
        self.assertEqual(self.r.act(card["id"], "cancel"), {"ok": True})
        self.link.proceed.set()
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "cancelled"))
        self.assertEqual(len([c for c in self.link.calls if c[0] == "GetParamRows"]), 1)
        self.assertEqual(self.card(card["id"])["ops"][0]["state"], "cancelled")
        self.assertEqual(self.share_files(), [])
        self.assertIsNone(self.r.busy())

    def test_cancel_a_queued_job(self):
        self.link.proceed = threading.Event()
        first, _ = self.r.add("a.json", fixture("job-files", "good-example.json"))
        second, _ = self.r.add("b.json", job_bytes([
            {"op": "fetch_rows", "as": "t", "param": "TalkParam", "fields": ["msgId"]},
            {"op": "write_local", "name": "talk", "tables": ["t"]}]))
        self.r.act(first["id"], "start")
        self.r.act(second["id"], "start")
        self.assertEqual(self.card(second["id"])["state"], "queued")
        self.r.act(second["id"], "cancel")
        self.assertEqual(self.card(second["id"])["state"], "cancelled")
        self.link.proceed.set()
        self.assertTrue(wait_for(lambda: self.card(first["id"])["state"] == "done"))
        self.assertEqual(self.card(second["id"])["state"], "cancelled")

    def test_quit_stops_between_calls(self):
        self.link.proceed = threading.Event()
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(self.link.started.wait(5))
        threading.Timer(0.2, self.link.proceed.set).start()
        self.r.stop(cancel=True, timeout=3)
        self.assertEqual(self.card(card["id"])["state"], "stopped")
        self.assertEqual(self.share_files(), [])


class FailureTest(RunnerBase):
    def test_a_link_failure(self):
        self.link.fail = link.LinkDataError("the server sent a value that is not a number (field 2)")
        card = self.run_job(fixture("job-files", "good-example.json"), state="failed")
        self.assertEqual(card["result"]["failed"], {"op": 0, "why": "the server sent a value that is not a number "
                                                                    "(field 2)", "check": None, "where": None})
        self.assertEqual(card["ops"][0]["state"], "failed")
        self.assertEqual(self.share_files(), [])

    def test_a_guard_failure(self):
        self.sets.stop()             # DP18: check 3 sees the name sets' texts only, so the planted one is in a set
        self.sets = mock.patch.dict(textdb.TEXT_SETS, dict(SETS, place_names=(("item", 9002), ("item_dlc02", 9005))))
        self.sets.start()
        self.db.import_export({"Name": "item_dlc02", "FmgWrappers": [{"Name": "Invented", "ID": 9005, "Fmg": {
            "Entries": [{"ID": 9000200, "Text": "per_team"}]}}]}, container="item_dlc02", language="engus",
            sha256="1" * 64)
        card = self.run_job(fixture("job-files", "good-example.json"), state="failed")
        self.assertEqual(card["result"]["failed"], {"op": 4, "why": "the guard refused the share file: check 3 at "
                                                                    "tables[0].name (a string the text database "
                                                                    "holds)", "check": 3,
                                                    "where": "tables[0].name"})
        self.assertEqual(self.share_files(), [])

    def test_a_later_failure_writes_no_share_file(self):
        card = self.run_job(job_bytes([
            {"op": "fetch_rows", "as": "t", "param": "TalkParam", "fields": ["msgId"]},
            {"op": "count", "as": "c", "rows": "t"},
            {"op": "write_share", "name": "talk-count", "tables": ["c"], "columns": {"c": ["count"]}},
            {"op": "read_placements", "as": "p", "maps": ["m99_00_00_09"]}]), state="failed")
        self.assertEqual(card["result"]["failed"]["op"], 3)
        self.assertEqual(card["result"]["failed"]["why"], "the map m99_00_00_09 is not loaded in Smithbox")
        self.assertEqual(card["ops"][2]["state"], "done")
        self.assertEqual(self.share_files(), [])

    def test_the_provenance_missing(self):
        from datapiler.status import ProvenanceMissing

        def missing():
            raise ProvenanceMissing("the game's version is not known - set the game folder")

        self.provenance = missing
        card = self.run_job(fixture("job-files", "good-example.json"), state="failed")
        self.assertEqual(card["result"]["failed"]["why"], "the provenance block is not complete: the game's version "
                                                          "is not known - set the game folder")
        self.assertEqual(self.share_files(), [])

    def test_names_not_confirmed_or_not_imported(self):
        with mock.patch.dict(textdb.TEXT_SETS, {"character_names": ()}):
            card = self.run_job(fixture("job-files", "good-example.json"), state="failed")
        self.assertEqual(card["result"]["failed"], {"op": 2, "why": "which text entries hold the character names is "
                                                                    "not known, so join_names cannot run",
                                                    "check": None, "where": None})
        empty = textdb.TextDB(Path(self.tmp.name) / "empty.sqlite")
        try:
            self.r.textdb = empty
            self.r.act(card["id"], "start")
            self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "failed" and
                                     self.card(card["id"])["result"] is not None))
            self.assertEqual(self.card(card["id"])["result"]["failed"]["why"],
                             "The character names are not imported yet - run Extract's guided row for them first")
        finally:
            empty.close()


class ShareRulesTest(RunnerBase):
    """DP8 at run time (settled S18, S19): what reaches a share file, and check 6's counts; P3's leads verified at
    join time (S22); P2's statement missing (S21)."""

    NAMED = [{"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId"]},
             {"op": "join_names", "as": "npc_named", "rows": "npc", "key": "nameId", "text": "character_names"},
             {"op": "filter", "as": "named_rows", "rows": "npc_named", "where": {"named": True}}]

    def test_the_named_rows_cover_too_many_of_the_param(self):
        # 15 of NpcParam's 20 invented rows have a name: more than half, so check 6 refuses the table
        card = self.run_job(job_bytes(self.NAMED + [
            {"op": "write_share", "name": "named-rows", "tables": ["named_rows"],
             "columns": {"named_rows": ["id", "nameId"]}}]), state="failed")
        self.assertEqual(card["result"]["failed"]["check"], 6)
        self.assertEqual(card["result"]["failed"]["where"], "tables[0]")
        self.assertIn("check 6 at tables[0] (a table covering, alone or with the file's other tables from the same "
                      "game table, more than half", card["result"]["failed"]["why"])
        self.assertEqual(self.share_files(), [])

    def test_the_named_rows_of_a_few_picked_ids(self):
        card = self.run_job(job_bytes(self.NAMED + [
            {"op": "filter", "as": "few", "rows": "named_rows", "where": {"nameId": {"ge": 0}}},
            {"op": "filter", "as": "picked", "rows": "few", "ids": [9000000, 9000001, 9000002, 9000003]},
            {"op": "write_share", "name": "picked-rows", "tables": ["picked"],
             "columns": {"picked": ["id", "nameId"]}}]))
        doc = json.loads((self.p.share / "picked-rows.json").read_bytes())
        self.assertEqual(doc["tables"][0]["rows"], [[9000000, 9000000], [9000001, 9000001], [9000002, 9000004]])
        sha = card["result"]["share"]["sha256"]
        self.assertEqual(guard.counts_for(self.p.share_counts, "picked-rows.json", sha),
                         {"picked": ("id", 20, "NpcParam")})
        # the same counts give the same answer later, as Outputs asks
        data = (self.p.share / "picked-rows.json").read_bytes()
        res = self.guard.check(data, declared={"picked": ["id", "nameId"]},
                               coverage=guard.counts_for(self.p.share_counts, "picked-rows.json", sha))
        self.assertTrue(all(r.ok for r in res), res)
        # without its id column, the table's rows are measured instead
        card = self.run_job(job_bytes(self.NAMED + [
            {"op": "write_share", "name": "named-numbers", "tables": ["named_rows"],
             "columns": {"named_rows": ["nameId"]}}], jid="test-0101-numbers"), state="failed")
        self.assertEqual(card["result"]["failed"]["check"], 6)

    def test_placements_picked_by_their_character_rows(self):
        card = self.run_job(job_bytes([
            {"op": "read_placements", "as": "placed", "maps": "all"},
            {"op": "filter", "as": "these", "rows": "placed", "key": "npcParamId", "ids": [9000001]},
            {"op": "write_share", "name": "where-placed", "tables": ["these"],
             "columns": {"these": ["map", "entityId", "npcParamId"]}}]))
        doc = json.loads((self.p.share / "where-placed.json").read_bytes())
        self.assertEqual([r[2] for r in doc["tables"][0]["rows"]], [9000001, 9000001])
        # placements are measured by their rows (entity ids can repeat), against the placements of the maps read
        self.assertEqual(guard.counts_for(self.p.share_counts, "where-placed.json", card["result"]["share"]["sha256"]),
                         {"these": (None, 6, "placements")})

    def test_placements_whose_entity_ids_repeat(self):
        """The invented maps repeat their entity ids, so three ids cover every placement read: their rows are
        measured, not their entity ids, and check 6 refuses the table."""
        self.link.loaded = ["m99_00_00_0%d" % k for k in range(4)]
        card = self.run_job(job_bytes([
            {"op": "read_placements", "as": "placed", "maps": "all"},
            {"op": "filter", "as": "these", "rows": "placed", "key": "npcParamId",
             "ids": [9000000, 9000001, 9000002]},
            {"op": "write_share", "name": "every-placement", "tables": ["these"],
             "columns": {"these": ["map", "entityId", "npcParamId"]}}], jid="test-0110-placed"), state="failed")
        self.assertEqual((card["result"]["failed"]["check"], card["result"]["failed"]["where"]), (6, "tables[0]"))
        self.assertEqual(self.share_files(), [])

    def test_a_map_read_twice_counts_once(self):
        """Reading the same maps again never raises the bound: each map's placements count once (6 here, not 12),
        and the tables of both reads are measured together."""
        card = self.run_job(job_bytes([
            {"op": "read_placements", "as": "a", "maps": "all"},
            {"op": "read_placements", "as": "b", "maps": "all"},
            {"op": "filter", "as": "pa", "rows": "a", "key": "npcParamId", "ids": [9000000]},
            {"op": "filter", "as": "pb", "rows": "b", "key": "npcParamId", "ids": [9009999]},
            {"op": "write_share", "name": "read-twice", "tables": ["pa", "pb"],
             "columns": {"pa": ["map", "entityId"], "pb": ["map", "entityId"]}}], jid="test-0111-twice"))
        self.assertEqual(guard.counts_for(self.p.share_counts, "read-twice.json", card["result"]["share"]["sha256"]),
                         {"pa": (None, 6, "placements"), "pb": (None, 6, "placements")})
        card = self.run_job(job_bytes([
            {"op": "read_placements", "as": "a", "maps": "all"},
            {"op": "read_placements", "as": "b", "maps": "all"},
            {"op": "filter", "as": "pa", "rows": "a", "key": "npcParamId", "ids": [9000000]},
            {"op": "filter", "as": "pb", "rows": "b", "key": "npcParamId", "ids": [9000001]},
            {"op": "write_share", "name": "read-twice-more", "tables": ["pa", "pb"],
             "columns": {"pa": ["map", "entityId"], "pb": ["map", "entityId"]}}], jid="test-0112-twice"),
            state="failed")
        self.assertEqual((card["result"]["failed"]["check"], card["result"]["failed"]["where"]), (6, "tables[1]"))

    def test_tables_from_one_param_are_measured_together(self):
        """Four picked lists of a quarter each, from one fetch_rows, are the whole param: check 6 refuses the file
        at the table that passes half (invented TalkParam rows)."""
        self.link.talk = {9000000 + i: {"msgId": 9500000 + i} for i in range(40)}
        ids = sorted(self.link.talk)
        ops = [{"op": "fetch_rows", "as": "talk", "param": "TalkParam", "fields": ["msgId"]}]
        names = ["q%d" % k for k in range(4)]
        for k, n in enumerate(names):
            ops.append({"op": "filter", "as": n, "rows": "talk", "ids": ids[10 * k:10 * k + 10]})
        ops.append({"op": "write_share", "name": "four-quarters", "tables": names,
                    "columns": {n: ["id", "msgId"] for n in names}})
        card = self.run_job(job_bytes(ops, jid="test-0113-quarters"), state="failed")
        self.assertEqual((card["result"]["failed"]["check"], card["result"]["failed"]["where"]), (6, "tables[2]"))
        self.assertEqual(self.share_files(), [])
        # the same picked rows in two tables count once
        card = self.run_job(job_bytes([
            ops[0], {"op": "filter", "as": "a", "rows": "talk", "ids": ids[:20]},
            {"op": "filter", "as": "b", "rows": "a", "where": {"msgId": {"ge": 0}}},
            {"op": "write_share", "name": "twice-the-same", "tables": ["a", "b"],
             "columns": {"a": ["id"], "b": ["id", "msgId"]}}], jid="test-0114-same"))
        self.assertEqual(card["state"], "done")

    def test_a_row_id_held_by_two_rows(self):
        """Smithbox lists each row id once, but an id may be held by more than one row: then the read's share tables
        are measured by their rows, not their ids (S19)."""
        plain = self.link.get_param_rows

        def twice(param, row_ids, fields, **kw):
            out = plain(param, row_ids, fields, **kw)
            return out + [dict(r) for r in out if r["id"] == 9000002]
        self.link.get_param_rows = twice
        card = self.run_job(job_bytes([
            {"op": "fetch_rows", "as": "talk", "param": "TalkParam", "fields": ["msgId"]},
            {"op": "filter", "as": "p", "rows": "talk", "ids": [9000002, 9000004]},
            {"op": "write_share", "name": "held-twice", "tables": ["p"], "columns": {"p": ["id", "msgId"]}}],
            jid="test-0117-twice"))
        doc = json.loads((self.p.share / "held-twice.json").read_bytes())
        self.assertEqual(len(doc["tables"][0]["rows"]), 3)
        self.assertEqual(guard.counts_for(self.p.share_counts, "held-twice.json", card["result"]["share"]["sha256"]),
                         {"p": (None, 10, "TalkParam")})

    def test_a_count_is_measured_by_its_groups(self):
        """A count of a raw table by columns that hold no ids is an aggregate, measured by its groups (P15, S19):
        a count by three columns of a table whose rows are nearly all distinct is refused."""
        for k, row in enumerate(self.link.npc.values()):
            row["teamType"], row["npcType"] = k, k % 2
        card = self.run_job(job_bytes([
            {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["teamType", "npcType"]},
            {"op": "count", "as": "c", "rows": "npc", "by": ["teamType", "npcType"]},
            {"op": "write_share", "name": "near-every-row", "tables": ["c"],
             "columns": {"c": ["teamType", "npcType", "count"]}}], jid="test-0115-groups"), state="failed")
        self.assertEqual((card["result"]["failed"]["check"], card["result"]["failed"]["where"]), (6, "tables[0]"))
        # its counts alone, without their groups, are not measured
        card = self.run_job(job_bytes([
            {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["teamType", "npcType"]},
            {"op": "count", "as": "c", "rows": "npc", "by": ["teamType", "npcType"]},
            {"op": "write_share", "name": "counts-alone", "tables": ["c"], "columns": {"c": ["count"]}}],
            jid="test-0116-counts"))
        self.assertEqual(guard.counts_for(self.p.share_counts, "counts-alone.json", card["result"]["share"]["sha256"]),
                         {"c": None})

    def test_an_explicit_list_reads_the_params_rows_only_for_a_share_file(self):
        self.run_job(job_bytes([
            {"op": "fetch_rows", "as": "talk", "param": "TalkParam", "fields": ["msgId"], "ids": [9000000]},
            {"op": "write_local", "name": "talk", "tables": ["talk"]}]))
        self.assertNotIn(("ListParamRows", "TalkParam"), self.link.calls)

    def test_the_wrapper_leads_must_hold(self):
        # P3: only one of the rows' three name numbers resolves in the wrappers: less than half, so join_names stops
        self.db.import_export({"Name": "item", "SourceContainer": "item", "FmgWrappers": [
            {"Name": "InventedCharacterNames", "ID": 9001, "Fmg": {"Entries": [{"ID": 9000000, "Text": "Ostrel"}]}}]},
            container="item", language="engus", sha256="5" * 64)
        card = self.run_job(fixture("job-files", "good-example.json"), state="failed")
        self.assertEqual(card["result"]["failed"], {"op": 2, "why": (
            "only 33% of the rows' name numbers (1 of 3) resolve in the wrappers 9001 of the character names: at "
            "least half must, so the leads do not hold for this data and join_names stops"), "check": None,
            "where": None})
        self.assertEqual(self.share_files(), [])

    def test_no_name_number_to_verify_the_leads_with(self):
        for row in self.link.npc.values():
            row["nameId"] = -1
        card = self.run_job(fixture("job-files", "good-example.json"), state="failed")
        self.assertEqual(card["result"]["failed"]["op"], 2)
        self.assertIn("cannot be verified", card["result"]["failed"]["why"])

    def test_half_resolving_is_enough_and_the_lowest_share_is_recorded(self):
        self.db.import_export({"Name": "item", "SourceContainer": "item", "FmgWrappers": [
            {"Name": "InventedCharacterNames", "ID": 9001, "Fmg": {"Entries": [
                {"ID": 9000000, "Text": "Ostrel"}, {"ID": 9000001, "Text": "Brannoc"}]}}]},
            container="item", language="engus", sha256="6" * 64)
        card = self.run_job(job_bytes([
            {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId", "teamType"]},
            {"op": "join_names", "as": "a", "rows": "npc", "key": "nameId", "text": "character_names"},
            {"op": "filter", "as": "two", "rows": "npc", "ids": [9000000, 9000001]},
            {"op": "join_names", "as": "b", "rows": "two", "key": "nameId", "text": "character_names"},
            {"op": "count", "as": "per_team", "rows": "a", "by": ["teamType"], "where": {"named": True}},
            {"op": "write_share", "name": "lowest-share", "tables": ["per_team"],
             "columns": {"per_team": ["teamType", "count"]}}]))
        doc = json.loads((self.p.share / "lowest-share.json").read_bytes())
        self.assertEqual(doc["provenance"]["names"], {"character_names": {
            "wrappers": [9001], "verified": True, "resolved": 0.666}})
        self.assertEqual(card["state"], "done")

    def test_the_expansion_not_stated(self):
        from datapiler.status import EXPANSION_UNSET, ProvenanceMissing

        def missing():
            raise ProvenanceMissing(EXPANSION_UNSET)

        self.provenance = missing
        card = self.run_job(fixture("job-files", "good-example.json"), state="failed")
        why = card["result"]["failed"]["why"]
        self.assertEqual(why, "the provenance block is not complete: " + EXPANSION_UNSET)
        self.assertIn("Settings", why)
        self.assertEqual(self.share_files(), [])


class AddAndRemoveTest(RunnerBase):
    def test_the_same_file_again(self):
        raw = fixture("job-files", "good-example.json")
        card, again = self.r.add("job.json", raw)
        self.assertEqual((card["state"], again), ("checked", False))
        self.assertEqual(card["preview"]["writes"], ["share file `roster-counts.json`: 1 table"])
        self.assertEqual(card["format"], "datapiler-job/1")
        card2, again = self.r.add("again.json", raw)
        self.assertTrue(again)
        self.assertEqual(card2["id"], card["id"])
        self.assertEqual(len(self.r.cards()), 1)
        with self.assertRaises(ValueError):
            self.r.add("empty.json", b"")

    def test_refused_cards(self):
        card, _ = self.r.add("x.json", fixture("job-files", "bad-not-json.json"))
        self.assertEqual(card["state"], "refused")
        self.assertRegex(card["id"], r"^refused-[0-9a-f]{12}$")
        self.assertEqual(card["refusals"], [{"op": None, "where": "(file)", "text": "the file is not JSON"}])
        self.assertTrue((self.p.jobs / card["id"] / "job.json").exists())
        bad, _ = self.r.add("y.json", fixture("job-files", "bad-field-not-read.json"))
        self.assertEqual((bad["id"], bad["state"], bad["title"]), ("en-0007-roster-counts", "refused", TITLE))
        self.assertEqual(self.r.act(bad["id"], "start")["ok"], False)
        good, _ = self.r.add("z.json", fixture("job-files", "good-example.json"))
        self.assertEqual((good["id"], good["state"]), ("en-0007-roster-counts", "checked"))   # it took the place
        self.assertEqual([c["id"] for c in self.r.cards()], [card["id"], "en-0007-roster-counts"])
        dup, _ = self.r.add("w.json", fixture("job-files", "bad-as-twice.json"))
        self.assertTrue(dup["id"].startswith("refused-"))
        self.assertIn("id", [r["where"] for r in dup["refusals"]])

    def test_remove(self):
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.assertEqual(self.r.act(card["id"], "remove"), {"ok": True})
        self.assertEqual(self.r.cards(), [])
        self.assertFalse((self.p.jobs / card["id"]).exists())
        with self.assertRaises(ValueError):
            self.r.act(card["id"], "start")
        with self.assertRaises(ValueError):
            self.r.act("refused-000000000000", "remove")
        bad, _ = self.r.add("x.json", fixture("job-files", "bad-not-json.json"))
        self.r.act(bad["id"], "remove")
        self.assertEqual(os.listdir(self.p.jobs), [])

    def test_remove_while_running(self):
        self.link.proceed = threading.Event()
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        self.r.act(card["id"], "start")
        self.assertTrue(self.link.started.wait(5))
        self.r.act(card["id"], "remove")
        self.link.proceed.set()
        self.assertTrue(wait_for(lambda: self.r.cards() == []))
        self.assertFalse((self.p.jobs / card["id"]).exists())

    def test_unknown_what(self):
        card, _ = self.r.add("job.json", fixture("job-files", "good-example.json"))
        with self.assertRaises(ValueError):
            self.r.act(card["id"], "explode")


class SavedStateTest(RunnerBase):
    def test_state_saved_and_loaded(self):
        done = self.run_job(fixture("job-files", "good-example.json"))
        other, _ = self.r.add("b.json", fixture("job-files", "good-every-op.json"))
        refused, _ = self.r.add("c.json", fixture("job-files", "bad-not-object.json"))
        state_file = self.p.jobs / other["id"] / "state.json"
        state = json.loads(state_file.read_text())
        state["state"] = "running"
        state["ops"][0]["state"] = "running"
        state_file.write_text(json.dumps(state))
        calls = len(self.link.calls)
        r2 = self.new_runner()
        r2.load_folder()
        cards = {c["id"]: c for c in r2.cards()}
        self.assertEqual(list(cards), [done["id"], other["id"], refused["id"]])
        self.assertEqual(cards[done["id"]]["state"], "done")
        self.assertEqual(cards[done["id"]]["result"], done["result"])
        self.assertEqual(cards[done["id"]]["ops"], done["ops"])
        self.assertEqual(cards[other["id"]]["state"], "stopped")
        self.assertEqual(cards[other["id"]]["ops"][0]["state"], "stopped")
        self.assertEqual(cards[refused["id"]]["state"], "refused")
        time.sleep(0.3)
        self.assertEqual(len(self.link.calls), calls)                 # nothing resumed
        self.assertIsNone(r2.busy())
        self.assertEqual(json.loads(state_file.read_text())["state"], "stopped")
        self.assertTrue(r2.add("again.json", fixture("job-files", "good-example.json"))[1])


class ExtractTest(RunnerBase):
    def test_server_rows_before_guided_rows(self):
        out = self.r.run_extract(["character_names", "dialogue_links", "character_rows"])
        self.assertEqual(out, {"ok": True})
        rows = {x["id"]: x for x in self.r.extract_state()["rows"]}
        self.assertEqual(rows["character_names"]["state"], "waiting_export")
        self.assertEqual(rows["character_names"]["progress"], {"done": 0, "of": 3, "unit": "containers"})
        self.assertTrue(wait_for(lambda: all(x["state"] == "done" for x in self.r.extract_state()["rows"]
                                             if x["id"] in ("character_rows", "dialogue_links"))))
        firsts = [c[1] for c in self.link.calls if c[0] == "ListParamRows"]
        self.assertEqual(firsts, ["NpcParam", "TalkParam"])                # the catalogue's order
        rows = {x["id"]: x for x in self.r.extract_state()["rows"]}
        self.assertEqual((rows["character_rows"]["result"]["count"], rows["character_rows"]["result"]["unit"]),
                         (20, "rows"))
        self.assertEqual(self.share_files(), ["extract-character_rows.json", "extract-dialogue_links.json"])
        doc = json.loads((self.p.share / "extract-character_rows.json").read_bytes())
        self.assertEqual([(t["name"], t["rows"]) for t in doc["tables"]],
                         [("rows_total", [[20]]), ("rows_with_name_number", [[15]])])
        self.assertEqual(doc["job"]["id"], "extract-character_rows")
        self.assertTrue((self.p.local / "extract" / "character_rows.json").exists())
        self.assertEqual(self.r.made_by()["local/extract/character_rows.json"], "Extract")
        self.assertEqual(self.r.made_by()["extract-character_rows.json"], "Extract")
        for c in ("item", "item_dlc01", "item_dlc02"):
            events.emit("inbox.import", container=own(c), ok=True, entries=5)
        rows = {x["id"]: x for x in self.r.extract_state()["rows"]}
        self.assertEqual(rows["character_names"]["state"], "done")
        self.assertEqual(rows["character_names"]["result"]["count"], 5)   # one export suffices (S42)

    def test_unknown_rows_and_grey_rows(self):
        with self.assertRaises(ValueError):
            self.r.run_extract(["character_rows", "boss_bars"])
        self.link.state = "off"
        rows = {x["id"]: x for x in self.r.extract_state()["rows"]}
        self.assertEqual(rows["character_rows"]["grey"], "the server link is off")
        self.assertIsNone(rows["character_names"]["grey"])
        # P3's lead: the place names sit in the character names' containers, so their row waits for those exports
        self.assertIsNone(rows["place_names"]["grey"])
        with mock.patch.object(catalogue, "ROWS", tuple(
                replace(r, containers=()) if r.id == "place_names" else r for r in catalogue.ROWS)):
            rows = {x["id"]: x for x in self.r.extract_state()["rows"]}
            self.assertEqual(rows["place_names"]["grey"], "the text container of these names is not confirmed yet")

    def test_the_map_question_above_ten(self):
        self.link.every_map = ["m99_00_00_%02d" % i for i in range(12)]
        out = self.r.run_extract(["map_placements"], load_maps=True)
        self.assertEqual(out["ok"], False)
        self.assertEqual(out["ask"]["maps"], 12)
        self.assertEqual(self.r.extract_state()["ask"]["maps"], 12)
        self.assertEqual(self.link.calls, [])
        self.assertEqual(self.r.run_extract(["map_placements"], load_maps=True, confirm_maps=12), {"ok": True})
        self.assertTrue(wait_for(lambda: self.r.extract_state()["rows"][3]["state"] == "done"))
        self.assertIn(("OpenResource", tuple(self.link.every_map)), self.link.calls)
        row = self.r.extract_state()["rows"][3]
        self.assertEqual((row["id"], row["result"]["count"], row["result"]["unit"]), ("map_placements", 36,
                                                                                       "placements"))
        self.assertIsNone(self.r.extract_state()["ask"])

    def test_a_job_asks_above_ten_maps(self):
        maps = ["m99_00_00_%02d" % i for i in range(11)]
        card, _ = self.r.add("job.json", job_bytes([{"op": "load_maps", "maps": maps}]))
        out = self.r.act(card["id"], "start")
        self.assertEqual((out["ok"], out["ask"]["maps"]), (False, 11))
        self.assertEqual(self.r.act(card["id"], "start", confirm_maps=10)["ok"], False)
        self.assertEqual(self.r.act(card["id"], "start", confirm_maps=11), {"ok": True})
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "done"))
        ten, _ = self.r.add("ten.json", job_bytes([{"op": "load_maps", "maps": maps[:10]}], jid="test-0101-ten"))
        self.assertEqual(self.r.act(ten["id"], "start"), {"ok": True})

    def test_no_map_loaded(self):
        self.link.loaded = []
        self.r.run_extract(["map_placements"])
        self.assertTrue(wait_for(lambda: self.r.extract_state()["rows"][3]["state"] == "failed"))
        row = self.r.extract_state()["rows"][3]
        self.assertEqual(row["error"], "no map is loaded in Smithbox - load the maps in Smithbox first")
        self.assertEqual(row["grey"], "load the maps in Smithbox first")

    def test_cancel_extract(self):
        self.link.proceed = threading.Event()
        self.r.run_extract(["character_rows", "dialogue_links", "character_names"])
        self.assertTrue(self.link.started.wait(5))
        self.assertEqual(self.r.busy(), {"kind": "extract", "id": "character_rows", "title": "Character rows"})
        self.assertEqual(self.r.extract_state()["running"], "character_rows")
        self.r.cancel_extract()
        self.link.proceed.set()
        self.assertTrue(wait_for(lambda: self.r.extract_state()["rows"][0]["state"] == "cancelled"))
        states = {x["id"]: x["state"] for x in self.r.extract_state()["rows"]}
        self.assertEqual((states["dialogue_links"], states["character_names"]), ("cancelled", "cancelled"))
        self.assertEqual(self.share_files(), [])

    def test_extract_waits_for_the_link(self):
        self.link.state = "off"
        self.r.run_extract(["dialogue_links"])
        self.assertTrue(wait_for(lambda: self.r.extract_state()["rows"][2]["grey"] == "the server link is off"))
        self.assertEqual(self.r.extract_state()["rows"][2]["state"], "queued")
        self.link_on()
        self.assertTrue(wait_for(lambda: self.r.extract_state()["rows"][2]["state"] == "done"))


if __name__ == "__main__":
    unittest.main()


class BossesTest(RunnerBase):
    """0.2.3: the names no row uses (S47), map families (S45) and boss slots (S46)."""

    def test_unused_names_shares_the_names_no_row_uses(self):
        entries = [{"ID": n, "Text": "Invented %d" % k} for k, n in enumerate((9000000, 9000001, 9000004, 9000777,
                                                                                 9000888))]
        self.db.import_export({"Name": "item", "FmgWrappers": [{"Name": "Invented", "ID": 9001, "Fmg": {
            "Name": "Invented", "Entries": entries}}]}, container="item", language="engus", sha256="1" * 64)
        doc = {"format": jobs.FORMAT, "id": "en-0099-unused", "title": "Unused names", "ops": [
            {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId"]},
            {"op": "unused_names", "as": "unused", "rows": "npc", "key": "nameId", "text": "character_names"},
            {"op": "write_local", "name": "unused-local", "tables": ["unused"]},
            {"op": "write_share", "name": "unused", "tables": ["unused"], "columns": {"unused": ["nameId", "layer"]}}]}
        card = self.run_job(json.dumps(doc).encode())
        with open(os.path.join(self.p.share, "unused.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["tables"][0]["rows"], [[9000777, 0], [9000888, 0]])
        self.assertEqual(card["ops"][1]["done"], 2)
        text = json.dumps(data)
        self.assertNotIn("Invented", text)                    # names stay local

    def test_unused_names_over_half_the_set_is_shared_whole(self):
        doc = {"format": jobs.FORMAT, "id": "en-0098-unused", "title": "Unused names", "ops": [
            {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId"], "ids": [9000003]},
            {"op": "unused_names", "as": "unused", "rows": "npc", "key": "nameId", "text": "character_names"},
            {"op": "write_share", "name": "unused", "tables": ["unused"], "columns": {"unused": ["nameId"]}}]}
        self.run_job(json.dumps(doc).encode())      # DP17: numbers only, not held to check 6's half
        with open(os.path.join(self.p.share, "unused.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["tables"][0]["rows"], [[9000000], [9000001], [9000004]])

    def test_boss_slots_from_map_families(self):
        self.link.every_map = ["m99_00_00_00", "m99_00_00_01", "m99_00_00_02", "m98_00_00_00"]
        self.link.extra_placements = [(9000800, 9000003), (9000950, 9000002)]
        doc = {"format": jobs.FORMAT, "id": "en-0097-bosses", "title": "Boss slots", "ops": [
            {"op": "load_maps", "maps": ["m99_*"]},
            {"op": "read_placements", "as": "placed", "maps": ["m99_*"]},
            {"op": "filter", "as": "bosses", "rows": "placed", "slots": "boss"},
            {"op": "write_share", "name": "bosses", "tables": ["bosses"],
             "columns": {"bosses": ["map", "entityId", "npcParamId"]}}]}
        card, _ = self.r.add("job.json", json.dumps(doc).encode())
        out = self.r.act(card["id"], "start")
        self.assertFalse(out["ok"])
        self.assertIn("m99_*", out["ask"]["text"])
        self.assertEqual(self.r.act(card["id"], "start", confirm_maps=out["ask"]["maps"]), {"ok": True})
        self.assertTrue(wait_for(lambda: self.card(card["id"])["state"] == "done"), self.card(card["id"]))
        self.assertIn(("OpenResource", ("m99_00_00_00", "m99_00_00_01", "m99_00_00_02")), self.link.calls)
        with open(os.path.join(self.p.share, "bosses.json"), encoding="utf-8") as f:
            rows = json.load(f)["tables"][0]["rows"]
        self.assertEqual(sorted(r[1] for r in rows), [9000800] * 3)
        self.assertEqual({r[2] for r in rows}, {9000003})


class CardsTest(RunnerBase):
    def test_each_card_carries_when_it_was_added(self):
        # S54: the page sorts the newest first by `added`, so every card must carry it.
        self.r.add("a.json", fixture("job-files", "good-example.json"))
        cards = self.r.cards()
        self.assertTrue(cards and all(isinstance(c.get("added"), (int, float)) for c in cards))

