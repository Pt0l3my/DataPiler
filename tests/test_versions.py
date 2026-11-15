"""DP23 (settled S71): game updates. A version is (game version, regulation sha256, Smithbox build); a completed run
keeps what it read for its version in the workspace; a job whose last run was on another version says so on its card
and offers Update data, which reads again, compares by row id (params) and map by map (placements), keeps the old
version's outputs in that version's folder and writes a local change report; any two versions compare through the API.
An unchanged regulation and Smithbox build reuse the param's kept read. A run that would move saved map progress to
the Deleted bin asks for DELETE (the owner's rule of 2026-11-14). Every name, number and text is invented."""

import _repo  # noqa: F401

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datapiler import deleted, guard, logbook, paths, runner, server, textdb, versions, winapi
from datapiler.api import Api, Live
from datapiler.game import GameRunning
from datapiler.server import Bad
from datapiler.settings import Session, Settings
from datapiler.status import Status

import test_api as ta
import test_runner as tr

V1 = dict(tr.PROVENANCE)                                                  # 1.99.0.0, regulation abab..., 9.9.9
V2 = dict(tr.PROVENANCE, game_version="1.99.1.0", regulation_sha256="cd" * 32)
V1_EXE = dict(tr.PROVENANCE, game_version="1.99.2.0")                    # the exe only: the same regulation
V1_SB = dict(tr.PROVENANCE, smithbox_build="9.9.10")                     # Smithbox only
L1, L2 = "v1.99.0.0 (abababab)", "v1.99.1.0 (cdcdcdcd)"
F1, F2 = "v1.99.0.0-abababab", "v1.99.1.0-cdcdcdcd"
JID = "en-0923-versions"
MAPS = ["m99_00_00_%02d" % i for i in range(1, 5)]                      # A, B, C, D


def param_doc(jid: str = JID) -> bytes:
    return json.dumps({"format": "datapiler-job/1", "id": jid, "title": "Versions (invented)", "ops": [
        {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId", "teamType", "npcType"]},
        {"op": "count", "as": "per_team", "rows": "npc", "by": ["teamType"]},
        {"op": "write_local", "name": "npc-rows", "tables": ["npc"]},
        {"op": "write_share", "name": "team-counts", "tables": ["per_team"],
         "columns": {"per_team": ["teamType", "count"]}}]}).encode()


def map_doc(jid: str = "en-0924-version-maps") -> bytes:
    return json.dumps({"format": "datapiler-job/1", "id": jid, "title": "Map versions (invented)", "ops": [
        {"op": "load_maps", "maps": MAPS},
        {"op": "read_placements", "as": "placed", "maps": MAPS},
        {"op": "count", "as": "per_map", "rows": "placed", "by": ["map"]},
        {"op": "write_share", "name": "version-maps", "tables": ["per_map"],
         "columns": {"per_map": ["map", "count"]}}]}).encode()


def npc_rows(n: int) -> dict:
    return {i: {"nameId": -1, "teamType": i % 2, "npcType": i % 3} for i in range(1, n + 1)}


class KeyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = paths.resolve(Path(self.tmp.name), "workspace", "share")
        paths.ensure(self.p)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_key_and_its_label(self):
        key = versions.key_of(V1)
        self.assertEqual(key, {"game_version": "1.99.0.0", "regulation_sha256": "ab" * 32, "smithbox_build": "9.9.9"})
        self.assertEqual(tuple(key), runner.MAPS_KEY)
        self.assertEqual(versions.label(key), L1)
        for broken in (None, {}, dict(V1, regulation_sha256=None), dict(V1, game_version="")):
            self.assertIsNone(versions.key_of(broken))
        self.assertEqual(versions.change_text(key, versions.key_of(V2)),
                         "Game updated since this ran: %s → %s" % (L1, L2))
        self.assertEqual(versions.change_text(key, versions.key_of(V1_SB)),
                         "Smithbox updated since this ran: build 9.9.9 → 9.9.10")
        self.assertTrue(versions.params_same(key, versions.key_of(V1_EXE)))
        self.assertFalse(versions.params_same(key, versions.key_of(V1_SB)))
        self.assertFalse(versions.params_same(key, versions.key_of(V2)))

    def test_one_folder_per_version_never_shared_by_two(self):
        k1, ksb = versions.key_of(V1), versions.key_of(V1_SB)
        self.assertIsNone(versions.find(self.p, k1))
        self.assertEqual(versions.ensure(self.p, k1), F1)
        self.assertEqual(versions.ensure(self.p, k1), F1)
        self.assertEqual(versions.ensure(self.p, ksb), F1 + "-sb9.9.10")       # the same label, another build
        self.assertEqual(versions.find(self.p, ksb), F1 + "-sb9.9.10")
        meta = json.loads((self.p.versions / F1 / versions.VERSION_FILE).read_text("ascii"))
        self.assertEqual((meta["format"], meta["key"], meta["label"]), (versions.VERSION_FORMAT, k1, L1))
        self.assertEqual([v["id"] for v in versions.all_versions(self.p)], [F1, F1 + "-sb9.9.10"])
        odd = dict(k1, game_version="CON..x/1 ")                             # nothing of it can leave the folder
        name = versions.ensure(self.p, odd)
        self.assertTrue(versions.FOLDER_RX.fullmatch(name), name)
        self.assertEqual((self.p.versions / name).parent, self.p.versions)
        self.assertEqual(self.p.versions, self.p.workspace / "versions")


class UpdateBase(tr.RunnerBase):
    def setUp(self):
        super().setUp()
        self.prov = dict(V1)
        self.provenance = lambda: dict(self.prov)

    def wait_state(self, jid: str, state: str) -> dict:
        self.assertTrue(tr.wait_for(lambda: self.card(jid)["state"] == state, 30), self.card(jid))
        return self.card(jid)

    def act(self, jid: str, what: str, state: str = "done") -> dict:
        self.assertEqual(self.r.act(jid, what), {"ok": True})
        return self.wait_state(jid, state)

    def report(self, card: dict) -> dict:
        return json.loads((self.p.workspace / card["result"]["changes"]["report"]).read_text("utf-8"))

    def read(self, folder: str, jid: str, table: str) -> dict:
        return json.loads((self.p.versions / folder / jid / "reads" / (table + ".json")).read_text("ascii"))


class UpdateTest(UpdateBase):
    def test_reads_kept_per_version_and_the_update_line(self):
        card = self.run_job(param_doc())
        other, _ = self.r.add("job.json", tr.fixture("job-files", "good-example.json"))     # never run
        doc = self.read(F1, JID, "npc")
        self.assertEqual((doc["format"], doc["job"], doc["kind"], doc["param"], doc["listed"]),
                         (versions.READ_FORMAT, JID, "fetch_rows", "NpcParam", 20))
        self.assertEqual([c["name"] for c in doc["columns"]], ["id", "nameId", "teamType", "npcType"])
        self.assertEqual(len(doc["rows"]), 20)
        self.assertEqual(doc["provenance"]["game_version"], "1.99.0.0")
        self.assertEqual(sorted(os.listdir(self.p.versions / F1 / JID / "reads")), ["npc.json"])   # reads only
        self.assertEqual((card["version"], card["update"], card["versions"]), (L1, None, 1))
        self.assertIsNone(card["result"]["changes"])
        # the game is updated: the card says so; a job never run is unaffected
        self.prov = dict(V2)
        card = self.card(JID)
        self.assertEqual(card["update"], {"from": L1, "to": L2,
                                          "text": "Game updated since this ran: %s → %s" % (L1, L2)})
        self.assertIsNone(self.card(other["id"])["update"])
        before = (self.p.versions / F1 / JID / "reads" / "npc.json").read_bytes()
        card = self.act(JID, "update")
        self.assertEqual((card["version"], card["update"], card["versions"]), (L2, None, 2))
        self.assertEqual((self.p.versions / F1 / JID / "reads" / "npc.json").read_bytes(), before)   # never touched
        self.assertEqual(len(self.read(F2, JID, "npc")["rows"]), 20)
        self.assertEqual(card["result"]["changes"]["lines"],
                         ["npc (NpcParam): 20 → 20 rows: 0 added, 0 changed, 0 removed, 20 unchanged"])
        self.assertEqual(self.r.act(JID, "update")["ok"], False)               # nothing left to update
        # the record survives a restart, and so does the update line
        self.prov = dict(V1)
        fresh = self.new_runner()
        fresh.load_folder()
        self.assertEqual(self.card(JID, fresh)["update"]["text"],
                         "Game updated since this ran: %s → %s" % (L2, L1))

    def test_the_owners_example_ten_thousand_rows_become_ten_thousand_and_fifty(self):
        self.link.npc = npc_rows(10_000)
        self.run_job(param_doc())
        self.link.npc = npc_rows(10_050)
        self.link.npc[8000]["npcType"] = 7                                    # rows 8,000 and 8,001 change
        self.link.npc[8001]["teamType"] = 9
        self.prov = dict(V2)
        card = self.act(JID, "update")
        self.assertEqual(card["result"]["changes"]["lines"],
                         ["npc (NpcParam): 10,000 → 10,050 rows: 50 added, 2 changed, 0 removed, 9,998 unchanged"])
        [t] = self.report(card)["tables"]
        self.assertEqual(t["added"], list(range(10_001, 10_051)))
        self.assertEqual(t["changed"], [8000, 8001])
        self.assertEqual((t["removed"], t["unchanged"], t["before"], t["after"]), ([], 9_998, 10_000, 10_050))
        self.assertEqual(card["result"]["changes"]["report"], "versions/%s/%s/changes/%s.json" % (F2, JID, F1))
        # the merged table is exactly the new read
        local = json.loads((self.p.local / JID / "npc-rows.json").read_text("utf-8"))
        self.assertEqual(len(local["tables"][0]["rows"]), 10_050)

    def test_rows_sharing_an_id_are_compared_as_a_multiset(self):
        old = [[1, 5], [1, 6], [2, 7]]
        self.assertEqual(versions.compare_rows(old, [[1, 6], [1, 5], [2, 7]])["changed"], [])
        self.assertEqual(versions.compare_rows(old, [[1, 6], [1, 6], [2, 7]])["changed"], [1])

    def test_a_map_job_compared_map_by_map(self):
        a, b, c, d = MAPS
        self.link.every_map = [a, b, c]                                       # D is not in this version
        self.link.loaded = []
        jid = json.loads(map_doc())["id"]
        self.run_job(map_doc())
        self.link.every_map = [b, c, d]                                       # A is gone, D is new
        self.link.map_extra = {b: [(9001900, 9000001)]}                       # one more placement on B
        self.link.loaded = []
        self.prov = dict(V2)
        card = self.act(jid, "update")
        self.assertEqual(card["result"]["changes"]["lines"],
                         ["placed: 3 → 3 maps: 1 added, 1 changed, 1 removed, 1 unchanged"])
        [t] = self.report(card)["tables"]
        self.assertEqual((t["added"], t["changed"], t["removed"], t["unchanged"]), ([d], [b], [a], 1))
        self.assertEqual(t["rows"], {"before": 9, "after": 10})
        kept = self.read(F2, jid, "placed")
        self.assertEqual(sorted(kept["maps"]), [b, c, d])
        self.assertEqual(len(kept["maps"][b]), 4)

    def test_a_map_that_did_not_load_is_not_counted_as_removed(self):
        self.assertEqual(versions.compare_maps({"m1": [[1]], "m2": [[2]]}, {"m1": [[1]]}, ["m2"]),
                         {"unit": "maps", "before": 2, "after": 1, "added": [], "changed": [], "removed": [],
                          "not_read": ["m2"], "unchanged": 1, "rows": {"before": 2, "after": 1}})

    def test_an_unchanged_regulation_reuses_the_params_read(self):
        self.run_job(param_doc())
        self.prov = dict(V1_EXE)                                              # an exe-only patch
        self.link.calls = []
        card = self.act(JID, "update")
        self.assertFalse([x for x in self.link.calls if x[0] in ("GetParamRows", "ListParamRows")], self.link.calls)
        [line] = card["result"]["changes"]["lines"]
        self.assertEqual(line, "npc (NpcParam): 20 rows, unchanged (the regulation and Smithbox's build are those of "
                               "%s, so the param was not read again)" % L1)
        f3 = versions.find(self.p, versions.key_of(V1_EXE))
        new = self.read(f3, JID, "npc")
        self.assertEqual((new["kept_from"], new["rows"], new["listed"]), (F1, self.read(F1, JID, "npc")["rows"], 20))
        self.assertEqual(new["provenance"]["game_version"], "1.99.2.0")
        self.assertTrue((self.p.share / "team-counts.json").exists())         # check 6 had the param's rows
        # a new Smithbox build with the same regulation reads again: it may read the same bytes differently
        self.prov = dict(V1_EXE, smithbox_build="9.9.10")
        self.link.calls = []
        card = self.act(JID, "update")
        self.assertIn(("ListParamRows", "NpcParam"), self.link.calls)
        self.assertEqual(card["result"]["changes"]["lines"],
                         ["npc (NpcParam): 20 → 20 rows: 0 added, 0 changed, 0 removed, 20 unchanged"])

    def test_the_old_outputs_are_kept_and_nothing_new_reaches_a_share_file(self):
        self.run_job(param_doc())
        old_local = (self.p.local / JID / "npc-rows.json").read_bytes()
        old_share = (self.p.share / "team-counts.json").read_bytes()
        entry = guard.counts_entry(self.p.share_counts, "team-counts.json")
        self.link.npc[9000003]["npcType"] = 2
        self.prov = dict(V2)
        # a run that fails before it writes moves nothing
        self.link.fail = runner.link_mod.LinkError("invented failure")
        self.act(JID, "update", state="failed")
        self.assertEqual((self.p.share / "team-counts.json").read_bytes(), old_share)
        self.assertFalse((self.p.versions / F1 / JID / "outputs").exists())
        self.link.fail = None
        card = self.act(JID, "update")
        out = self.p.versions / F1 / JID / "outputs"
        self.assertEqual((out / "local" / "npc-rows.json").read_bytes(), old_local)
        self.assertEqual((out / "share" / "team-counts.json").read_bytes(), old_share)
        self.assertEqual(json.loads((out / versions.COUNTS_FILE).read_text("ascii")), {"team-counts.json": entry})
        self.assertNotEqual((self.p.local / JID / "npc-rows.json").read_bytes(), old_local)
        self.assertNotEqual((self.p.share / "team-counts.json").read_bytes(), old_share)
        self.assertEqual(card["result"]["changes"]["lines"],
                         ["npc (NpcParam): 20 → 20 rows: 0 added, 1 changed, 0 removed, 19 unchanged"])
        # nothing new reaches the share folder: the job's own file, as the guard passes it, and no report
        self.assertEqual(self.share_files(), ["team-counts.json"])
        data = (self.p.share / "team-counts.json").read_bytes()
        doc = json.loads(data)
        self.assertEqual(sorted(doc), sorted(json.loads(old_share)))
        self.assertEqual([t["name"] for t in doc["tables"]], ["per_team"])
        self.assertTrue(all(r.ok for r in self.guard.check(data, declared={"per_team": ["teamType", "count"]},
                            coverage=guard.counts_for(self.p.share_counts, "team-counts.json",
                                                      card["result"]["share"]["sha256"]))))
        for f in self.p.share.rglob("*"):
            self.assertNotIn(b"9000003", f.read_bytes())                       # no row id of the report
        self.assertIn(b"9000003", (self.p.workspace / card["result"]["changes"]["report"]).read_bytes())
        # a second update to a third version keeps each version's outputs apart
        self.prov = dict(V1_SB)
        self.act(JID, "update")
        f3 = versions.find(self.p, versions.key_of(V1_SB))
        self.assertTrue((self.p.versions / F2 / JID / "outputs" / "share" / "team-counts.json").is_file())
        self.assertEqual((out / "share" / "team-counts.json").read_bytes(), old_share)
        self.assertTrue((self.p.versions / f3 / JID / "reads" / "npc.json").is_file())

    def test_a_run_again_on_the_same_version_keeps_reads_that_differ_apart(self):
        self.run_job(param_doc())
        self.link.npc[9000004]["npcType"] = 2
        self.act(JID, "start")
        names = sorted(os.listdir(self.p.versions / F1 / JID))
        self.assertEqual(names[0], "reads")
        self.assertTrue(names[1].startswith("reads-"), names)
        self.assertEqual(len(names), 2)

    def test_a_job_done_before_this_version_takes_its_version_from_its_share_file(self):
        self.run_job(param_doc())
        state = json.loads((self.p.jobs / JID / "state.json").read_text("ascii"))
        del state["ran"]                                                      # as 0.2.20 saved it
        (self.p.jobs / JID / "state.json").write_text(json.dumps(state), "ascii")
        for d in self.p.versions.iterdir():
            for f in sorted(d.rglob("*"), reverse=True):
                f.unlink() if f.is_file() else f.rmdir()
            d.rmdir()
        self.prov = dict(V2)
        fresh = self.new_runner()
        fresh.load_folder()
        self.assertEqual(self.card(JID, fresh)["update"]["from"], L1)
        self.assertEqual(fresh.act(JID, "update"), {"ok": True})
        self.assertTrue(tr.wait_for(lambda: self.card(JID, fresh)["state"] == "done", 30))
        card = self.card(JID, fresh)
        self.assertEqual(card["result"]["changes"]["lines"], ["npc (NpcParam): not compared (no read of %s was kept)"
                                                              % L1])
        self.assertTrue((self.p.versions / F1 / JID / "outputs" / "share" / "team-counts.json").is_file())

    def test_the_log_names_no_path(self):
        logs = Path(self.tmp.name) / "logs"
        logbook.setup(logs, max_bytes=1 << 20, keep=1, console=False)
        try:
            self.run_job(param_doc())
            self.prov = dict(V2)
            self.act(JID, "update")
            text = (logs / "jobs" / (JID + ".log")).read_text(encoding="utf-8")
            self.assertIn("the last run was on %s and this one is on %s" % (L1, L2), text)
            self.assertIn("changes since %s: npc (NpcParam): 20 → 20 rows" % L1, text)
            self.assertNotIn(self.tmp.name, text)
            self.assertNotIn("<text>", text)
        finally:
            logbook.shutdown()


class StartWordTest(UpdateBase):
    """The owner's rule of 2026-11-14: a run that would move saved map progress to the Deleted bin needs DELETE."""

    def failed_map_job(self) -> dict:
        self.link.every_map = list(MAPS)
        self.link.loaded = []
        self.link.crash_on_read = 3
        card = self.run_job(map_doc(), state="failed")
        self.link.crash_on_read = None
        self.link.loaded = []
        return card

    def test_which_runs_need_delete(self):
        card = self.failed_map_job()
        self.assertEqual(self.r.start_word(card["id"], "start"), deleted.WORD)
        self.assertIsNone(self.r.start_word(card["id"], "resume"))            # it goes on from it
        self.prov = dict(V2)
        self.assertEqual(self.r.start_word(card["id"], "resume"), deleted.WORD)   # of another version: dropped
        self.assertEqual(self.r.start_word(card["id"], "update"), deleted.WORD)
        (self.p.jobs / card["id"] / runner.MAPS_FILE).unlink()
        self.assertIsNone(self.r.start_word(card["id"], "start"))
        with self.assertRaises(ValueError):
            self.r.start_word("en-9999-nobody", "start")

    def test_without_a_provenance_saved_progress_stays_where_it_is(self):
        card = self.failed_map_job()
        kept = (self.p.jobs / card["id"] / runner.MAPS_FILE).read_bytes()

        def missing():
            from datapiler.status import ProvenanceMissing
            raise ProvenanceMissing("the game's version is not known - set the game folder")

        self.provenance = missing
        self.assertIsNone(self.r.start_word(card["id"], "resume"))
        self.act(card["id"], "resume", state="failed")                        # write_share needs the provenance
        self.assertEqual((self.p.jobs / card["id"] / runner.MAPS_FILE).read_bytes(), kept)
        self.assertEqual(deleted.items(self.p), [])


class ApiVersionsTest(unittest.TestCase):
    """The endpoints: the versions a job kept, any two compared, refused for anything else; Start again and Update data
    asking for DELETE when they would move saved progress to the bin; no path in an answer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "DataPiler"
        self.root.mkdir()
        (base / "Game").mkdir()
        (base / "Game" / "eldenring.exe").write_bytes(b"")
        (base / "Project").mkdir()
        cfg = Settings(game_dir=str(base / "Game"), project_dir=str(base / "Project"))
        self.p = paths.resolve(self.root, cfg.workspace_dir, cfg.share_dir)
        paths.ensure(self.p)
        self.live = Live(root=self.root, settings=cfg, paths=self.p, session=Session())
        self.use = winapi.use(ta.FakeBackend())
        self.use.__enter__()
        self.sets = mock.patch.dict(textdb.TEXT_SETS, tr.SETS)
        self.sets.start()
        self.db = textdb.TextDB(self.p.textdb)
        with open(os.path.join(tr.FIXTURES, "text-exports", "item-invented.json"), encoding="utf-8") as f:
            self.db.import_export(json.load(f), container="item", language="engus", sha256="a" * 64)
        self.guard = guard.Guard(self.db, lambda: ["velkorquist"])
        self.link = tr.FakeLink()
        self.prov = dict(V1)
        self.r = runner.Runner(lambda: self.live.paths, self.link, self.db, self.guard, lambda: dict(self.prov),
                               lambda: GameRunning(False, None), lambda: "engus")
        link = ta.FakeLink()
        self.status = Status(lambda: self.live.settings, lambda: link, lambda: False)
        self.api = Api(live=self.live, status=self.status, link=link, runner=self.r, textdb=self.db,
                       guard=self.guard, inbox=ta.FakeInbox(), catalogue=ta.FakeCatalogue(), stop=lambda: None,
                       libs=True)
        self.answers = []

    def tearDown(self):
        for a in self.answers:
            self.assertNotIn(self.tmp.name, a)
        self.api.close()
        self.status.close()
        self.r.stop(cancel=True, timeout=3)
        self.guard.close()
        self.db.close()
        self.sets.stop()
        self.use.__exit__(None, None, None)
        logbook.set_masks(folders={}, home=None, user=None, pc=None)
        self.tmp.cleanup()

    def post(self, path: str, body: dict) -> dict:
        code, answer, _ = self.api.post(path, body)
        self.assertEqual(code, 200, path)
        text = json.dumps(answer)
        self.answers.append(text)
        return json.loads(text)

    def get(self, path: str, query: dict) -> dict:
        code, answer = self.api.get(path, query)
        self.assertEqual(code, 200, path)
        text = json.dumps(answer)
        self.answers.append(text)
        return json.loads(text)

    def card(self, jid: str) -> dict:
        # what /api/state carries as "jobs" (its Status cards hold the folders Settings names, as the owner typed them)
        return json.loads(json.dumps(next(c for c in self.r.cards() if c["id"] == jid)))

    def go(self, jid: str, what: str, state: str = "done", **extra) -> dict:
        r = self.post("/api/jobs/act", dict({"id": jid, "what": what}, **extra))
        self.assertEqual(r, {"ok": True})
        self.assertTrue(tr.wait_for(lambda: self.r.cards() and next(
            c for c in self.r.cards() if c["id"] == jid)["state"] == state, 30))
        return self.card(jid)

    def test_the_compare_endpoint(self):
        self.r.add("job.json", param_doc())
        self.go(JID, "start")
        self.link.npc[9000005]["nameId"] = 9000004
        self.prov = dict(V2)
        card = self.card(JID)
        self.assertEqual(card["update"]["text"], "Game updated since this ran: %s → %s" % (L1, L2))
        card = self.go(JID, "update")
        self.assertEqual(card["versions"], 2)
        vs = self.get("/api/versions", {"job": JID})
        self.assertEqual((vs["job"], vs["current"]), (JID, L2))
        self.assertEqual([(v["id"], v["label"], v["tables"]) for v in vs["versions"]],
                         [(F1, L1, ["npc"]), (F2, L2, ["npc"])])
        rep = self.get("/api/versions/compare", {"job": JID, "a": F1, "b": F2})
        self.assertEqual(rep["lines"], ["npc (NpcParam): 20 → 20 rows: 0 added, 1 changed, 0 removed, 19 unchanged"])
        self.assertEqual(rep["tables"][0]["changed"], [9000005])
        back = self.get("/api/versions/compare", {"job": JID, "a": F2, "b": F1})     # either way round
        self.assertEqual(back["tables"][0]["changed"], [9000005])
        self.assertEqual((back["from"]["label"], back["to"]["label"]), (L2, L1))
        for q in ({"job": JID, "a": F1, "b": F1}, {"job": JID, "a": F1, "b": "1.0.0.0-00000000"},
                  {"job": JID, "a": "../x", "b": F2}, {"job": "../x", "a": F1, "b": F2}, {"job": JID}):
            with self.assertRaises(Bad):
                self.api.get("/api/versions/compare", q)
        with self.assertRaises(Bad):
            self.api.get("/api/versions", {"job": "../x"})
        self.assertEqual(self.get("/api/versions", {"job": "en-9999-nobody"})["versions"], [])
        # the compare view is local only: it writes nothing, and no share file holds it
        self.assertEqual(sorted(os.listdir(self.p.share)), ["team-counts.json"])

    def test_start_again_with_saved_progress_needs_delete(self):
        self.r.add("job.json", map_doc())
        jid = json.loads(map_doc())["id"]
        self.link.every_map = list(MAPS)
        self.link.loaded = []
        self.link.crash_on_read = 3
        self.go(jid, "start", state="failed")
        self.link.crash_on_read = None
        self.link.loaded = []
        progress = self.p.jobs / jid / runner.MAPS_FILE
        self.assertTrue(progress.exists())
        for confirm in (None, "move", "delete", True):
            body = {"id": jid, "what": "start"}
            if confirm is not None:
                body["confirm"] = confirm
            r = self.post("/api/jobs/act", body)
            self.assertFalse(r["ok"], confirm)
            self.assertEqual((r["ask"]["word"], r["ask"]["button"]), (deleted.WORD, "Start again"))
            self.assertIn("type DELETE", r["ask"]["text"].replace("Type", "type"))
            self.assertTrue(progress.exists())
        self.go(jid, "start", confirm=deleted.WORD)
        self.assertEqual([x["kind"] for x in deleted.items(self.p)], ["progress"])
        # without saved progress, Start again asks nothing of the API (the page keeps its plain question)
        self.assertEqual(self.post("/api/jobs/act", {"id": jid, "what": "start"}), {"ok": True})

    def test_update_with_progress_of_the_old_version_needs_delete(self):
        self.r.add("job.json", map_doc())
        jid = json.loads(map_doc())["id"]
        self.link.every_map = list(MAPS)
        self.link.loaded = []
        self.go(jid, "start")                                                # done on V1
        self.link.loaded = []
        self.link.reads = 0
        self.link.crash_on_read = 3
        self.go(jid, "start", state="failed")                               # its progress is of V1
        self.link.crash_on_read = None
        self.link.loaded = []
        self.assertIsNone(self.r.start_word(jid, "resume"))                  # Resume job would go on from it
        self.prov = dict(V2)
        r = self.post("/api/jobs/act", {"id": jid, "what": "update"})
        self.assertEqual((r["ok"], r["ask"]["word"], r["ask"]["button"]), (False, deleted.WORD, "Update data"))
        card = self.go(jid, "update", confirm=deleted.WORD)
        self.assertEqual(card["result"]["changes"]["lines"],
                         ["placed: 4 → 4 maps: 0 added, 0 changed, 0 removed, 4 unchanged"])
        self.assertIn("progress", [x["kind"] for x in deleted.items(self.p)])
        # moving the old outputs into their version's folder is not a deletion: nothing asks for it
        self.assertTrue((self.p.versions / F1 / jid / "outputs" / "share" / "version-maps.json").is_file())


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (server.PAGE_DIR / "app.js").read_text(encoding="utf-8")

    def test_runs_go_through_the_pop_up_and_update_data_is_offered(self):
        act = self.js[self.js.index("function jobAct("):self.js.index("// DP23: a job's kept versions")]
        self.assertIn('what === "cancel" ? api("/api/jobs/act", body) : confirmed("/api/jobs/act", body)', act)
        self.assertIn("r.confirmed || word", act)
        card = self.js[self.js.index("function jobCard("):self.js.index("function paintJobs(")]
        self.assertIn('"Update data"', card)
        self.assertIn('jobAct(j, "update")', card)
        self.assertIn('!kept && !window.confirm("Start this job again from the beginning?")', card)
        self.assertNotIn("go to the Deleted bin and are read again", card)    # no window.confirm for a deletion
        self.assertIn("/api/versions/compare?job=", self.js)


if __name__ == "__main__":
    unittest.main()
