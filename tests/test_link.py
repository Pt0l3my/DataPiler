"""The server link against the fake Soapstone server (build plan §8.2). The server tests skip without grpcio and
protobuf; the parts that need neither always run."""

import _repo  # noqa: F401

import socket
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from datapiler import events, link, logbook
from datapiler.logbook import own

try:
    import grpc

    import fake_soapstone
    from soapstone import common_pb2, internal_pb2
    HAVE_GRPC = True
except Exception:          # grpcio or protobuf missing: the server tests skip
    HAVE_GRPC = False


class FakeGame:
    """game() for the link: a switch the test flips, and a count of the checks."""

    def __init__(self, running: bool = False):
        self.running = running
        self.checks = 0

    def __call__(self):
        self.checks += 1
        return types.SimpleNamespace(running=self.running, why=None)


def wait_for(cond, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class WithoutGrpc(unittest.TestCase):
    """What needs neither grpcio nor protobuf."""

    def test_map_key(self):
        self.assertEqual(link.map_key("m12_34_56_78"), 12345678)
        self.assertEqual(link.map_key("m99_00_00_14"), 99000014)
        for bad in ("m12_34_56", "M12_34_56_78", "m12_34_56_78 ", "m1a_34_56_78", "", 12345678):
            with self.assertRaises(ValueError):
                link.map_key(bad)

    def test_no_libs_for_good(self):
        game = FakeGame()
        lk = link.Link(game, libs=False)
        self.assertEqual(lk.state, "no_libs")
        self.assertEqual(lk.switch(True), "no_libs")
        self.assertEqual(lk.state, "no_libs")
        with self.assertRaises(link.LibsMissing):
            lk.list_params()
        with self.assertRaises(link.LibsMissing):
            lk.list_param_rows("NpcParam")
        self.assertEqual(lk.switch(False), "no_libs")
        self.assertEqual(lk.stats(), {"calls": 0, "last_call": None, "last_methods": []})
        with self.assertRaises(link.LibsMissing):
            lk.map_ids()

    def test_would_call_names_allowed_methods_only(self):
        rows = link.Link(FakeGame(), libs=False).would_call()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(set(r), {"method", "for"})
            self.assertIn(r["method"], link.ALLOWED)

    def test_port_answers_makes_no_connect_while_the_game_runs(self):
        with mock.patch.object(link.socket, "create_connection") as connect:
            self.assertIsNone(link.port_answers(FakeGame(running=True)))
            connect.assert_not_called()

    def test_port_answers_connects_and_closes_without_sending(self):
        sock = mock.Mock(spec=socket.socket)
        with mock.patch.object(link.socket, "create_connection", return_value=sock) as connect:
            self.assertTrue(link.port_answers(FakeGame()))
        connect.assert_called_once_with(("127.0.0.1", link.PORT), timeout=0.5)
        sock.close.assert_called_once_with()
        sock.send.assert_not_called()
        sock.sendall.assert_not_called()

    def test_port_answers_false_when_refused(self):
        with mock.patch.object(link.socket, "create_connection", side_effect=ConnectionRefusedError(111, "x")):
            self.assertFalse(link.port_answers(FakeGame()))

    def test_lock_pins(self):
        pins = link.lock_pins()
        self.assertIn("grpcio", pins)
        self.assertIn("protobuf", pins)

    def test_available_never_raises(self):
        ok, why = link.available()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(why, logbook.Own)
        with mock.patch.object(link, "lock_pins", side_effect=OSError(2, "gone")):
            self.assertEqual(link.available(), (False, "requirements.lock could not be read"))


@unittest.skipUnless(HAVE_GRPC, "grpcio and protobuf are not installed")
class AgainstTheFake(unittest.TestCase):
    def setUp(self):
        self.fake = fake_soapstone.FakeSoapstone().start()
        self.addCleanup(self.fake.stop)
        self.game = FakeGame()
        self.link = self.make_link()
        self.events = []
        self.addCleanup(events.subscribe("link.", lambda t, d: self.events.append((t, d))))

    def make_link(self, interval: float = 30.0):
        lk = link.Link(self.game, libs=True, _test_port=self.fake.port)
        lk.watch_interval = interval
        lk.map_poll = 0.01
        lk.map_wait = 5.0
        self.addCleanup(lk.close, own("the test ended"))
        return lk

    def states(self):
        return [d["state"] for t, d in self.events if t == "link.state"]

    def assert_no_planted(self, value):
        text = repr(value)
        for s in fake_soapstone.PLANTED:
            self.assertNotIn(s, text)

    # ---- the gate

    def test_off_refuses_and_calls_nothing(self):
        self.assertEqual(self.link.state, "off")
        for call in (self.link.list_params, lambda: self.link.list_param_rows("NpcParam"),
                     self.link.loaded_maps, lambda: self.link.placements("m99_00_00_00")):
            with self.assertRaises(link.LinkOff):
                call()
        self.assertEqual(self.fake.methods(), [])

    def test_switch_on_while_the_game_runs_waits(self):
        lk = self.make_link(interval=0.05)
        self.game.running = True
        self.assertEqual(lk.switch(True), "blocked")
        self.assertEqual(lk.state, "blocked")
        self.assertEqual(self.states(), ["blocked"])
        with self.assertRaises(link.LinkBlocked):
            lk.list_params()
        self.assertEqual(self.fake.methods(), [])
        self.game.running = False
        self.assertTrue(wait_for(lambda: lk.state == "on"))
        # the event follows the state on the watcher's thread: wait for it rather than race it (a flake under load)
        self.assertTrue(wait_for(lambda: self.states() == ["blocked", "on"]), self.states())
        self.assertEqual(lk.list_params(), ["NpcParam", "TalkParam"])

    def test_game_checked_afresh_before_each_call(self):
        self.assertEqual(self.link.switch(True), "on")
        self.assertEqual(self.link.list_params(), ["NpcParam", "TalkParam"])
        self.game.running = True                 # the watcher (30 s) has not looked yet
        with self.assertRaises(link.LinkBlocked):
            self.link.list_param_rows("NpcParam")
        self.assertEqual(self.fake.methods(), ["ListParams"])
        self.assertEqual(self.link.state, "blocked")
        self.assertIn("blocked", self.states())
        self.game.running = False
        with self.assertRaises(link.LinkBlocked):  # back only once the watcher has seen the game closed twice
            self.link.list_params()
        self.assertEqual(self.fake.methods(), ["ListParams"])

    def test_switch_off(self):
        self.link.switch(True)
        self.link.list_params()
        self.assertEqual(self.link.switch(False), "off")
        self.assertIsNone(self.link._channel)
        with self.assertRaises(link.LinkOff):
            self.link.list_params()
        self.assertEqual(self.fake.methods(), ["ListParams"])
        self.assertEqual(self.states(), ["on", "off"])

    def test_close_and_app_stopping(self):
        self.link.switch(True)
        self.link.close(own("the test closed it"))
        self.assertEqual(self.link.state, "off")
        self.link.switch(True)
        events.emit("app.stopping")
        self.assertEqual(self.link.state, "off")
        self.assertEqual(self.states(), ["on", "off", "on", "off"])

    def test_only_the_table_is_called(self):
        self.link.switch(True)
        with self.assertRaises(link.LinkError):
            self.link._call("SetParamCell", internal_pb2.SetParamCellRequest(), lambda r: 0)
        with self.assertRaises(link.LinkError):        # a request of another call's type
            self.link._call("ListParams", internal_pb2.GetParamRowsRequest(), lambda r: 0)
        self.assertEqual(self.fake.methods(), [])

    def test_the_fake_serves_the_seven_only(self):
        ch = grpc.insecure_channel("127.0.0.1:%d" % self.fake.port, options=[("grpc.enable_http_proxy", 0)])
        self.addCleanup(ch.close)
        call = ch.unary_unary("/SoapstoneLib.Proto.Internal.Soapstone/SetParamCell",
                              request_serializer=internal_pb2.SetParamCellRequest.SerializeToString,
                              response_deserializer=internal_pb2.SetParamCellResponse.FromString)
        with self.assertRaises(grpc.RpcError) as cm:
            call(internal_pb2.SetParamCellRequest(), timeout=5)
        self.assertEqual(cm.exception.code(), grpc.StatusCode.UNIMPLEMENTED)

    # ---- params

    def test_param_names_checked(self):
        self.link.switch(True)
        self.assertEqual(self.link.list_params(), ["NpcParam", "TalkParam"])

    def test_row_ids_as_numbers_vanilla(self):
        self.link.switch(True)
        ids = self.link.list_param_rows("NpcParam")
        self.assertEqual(ids, list(fake_soapstone.NPC_IDS))
        self.assertTrue(all(type(i) is int for i in ids))
        self.assertEqual(self.link.list_param_rows("TalkParam"), list(fake_soapstone.TALK_IDS))
        reqs = self.fake.requests("ListParamRows")
        self.assertEqual(len(reqs), 2)
        self.assertTrue(all(r.vanilla is True for r in reqs))
        with self.assertRaises(ValueError):
            self.link.list_param_rows("../NpcParam")

    def test_rows_as_numbers_only_the_fields_asked(self):
        self.link.switch(True)
        ids = [i for i in fake_soapstone.NPC_IDS if i != fake_soapstone.TEXT_CELL_ID]
        seen = []
        rows = self.link.get_param_rows("NpcParam", ids, ["nameId", "teamType", "npcType", "hitHeight",
                                                          "isGhost", "padFlags"],
                                        progress=lambda d, o: seen.append((d, o)))
        self.assertEqual(len(rows), len(ids) + 1)            # the duplicate id has two rows
        dup = [r for r in rows if r["id"] == fake_soapstone.DUPLICATE_ID]
        self.assertEqual(len(dup), 2)
        for r in rows:
            self.assertEqual(set(r), {"id", "nameId", "teamType", "npcType", "hitHeight", "isGhost", "padFlags"})
            for k in ("id", "nameId", "teamType", "npcType", "padFlags"):
                self.assertIs(type(r[k]), int)
            self.assertIs(type(r["hitHeight"]), float)
            self.assertIs(type(r["isGhost"]), bool)
        first = rows[0]
        self.assertEqual(first, {"id": 9000000, "nameId": 9500000, "teamType": 0, "npcType": 0,
                                 "hitHeight": 1.5, "isGhost": False, "padFlags": 0})
        self.assertEqual(seen[-1], (len(ids), len(ids)))
        self.assert_no_planted(rows)
        reqs = self.fake.requests("GetParamRows")
        self.assertEqual(len(reqs), len(ids))
        self.assertTrue(all(r.vanilla is True for r in reqs))
        only_id = self.link.get_param_rows("TalkParam", [9100003], ["id"])
        self.assertEqual(only_id, [{"id": 9100003}])

    def test_a_text_cell_is_refused(self):
        self.link.switch(True)
        with self.assertRaises(link.LinkDataError) as cm:
            self.link.get_param_rows("NpcParam", [9000000, fake_soapstone.TEXT_CELL_ID], ["teamType", "nameId"])
        self.assertIn("field 1", str(cm.exception))
        self.assert_no_planted(str(cm.exception))
        with self.assertRaises(link.LinkDataError) as cm:     # a text field, whatever it holds
            self.link.get_param_rows("NpcParam", [9000000], ["epithet"])
        self.assertIn("field 0", str(cm.exception))
        self.assert_no_planted(str(cm.exception))
        with self.assertRaises(link.LinkDataError):
            self.link.get_param_rows("NpcParam", [9000000], ["noSuchField"])
        with self.assertRaises(ValueError):
            self.link.get_param_rows("NpcParam", [True], ["nameId"])

    def test_cancel_between_calls(self):
        self.link.switch(True)
        cancel = threading.Event()

        def progress(done, of):
            if done == 3:
                cancel.set()
        with self.assertRaises(link.LinkCancelled):
            self.link.get_param_rows("TalkParam", list(fake_soapstone.TALK_IDS), ["msgId"], cancel=cancel,
                                     progress=progress)
        # S55: up to ROW_WORKERS calls run at once, so a few more may have gone out; the rest never do.
        sent = len(self.fake.requests("GetParamRows"))
        self.assertGreaterEqual(sent, 3)
        self.assertLessEqual(sent, 3 + link.ROW_WORKERS)
        self.assertLess(sent, len(fake_soapstone.TALK_IDS))

    def test_a_failed_call_names_the_code_only(self):
        self.link.switch(True)
        with self.assertRaises(link.LinkCallError) as cm:
            self.link.list_param_rows("NoSuchParam")
        self.assertEqual(cm.exception.code, "NOT_FOUND")
        self.assert_no_planted(str(cm.exception))
        self.assertIsNone(cm.exception.__cause__)
        calls = [d for t, d in self.events if t == "link.call"]
        self.assertEqual(calls[-1]["ok"], False)

    # ---- maps

    def test_loaded_maps(self):
        self.link.switch(True)
        self.assertEqual(self.link.loaded_maps(), list(fake_soapstone.LOADED_AT_START))

    def test_open_maps_in_batches_of_ten_maps_only(self):
        self.link.switch(True)
        seen = []
        n = self.link.open_maps(list(fake_soapstone.MAPS), progress=lambda d, o: seen.append((d, o)))
        self.assertEqual(n, len(fake_soapstone.MAPS))
        opened = self.fake.requests("OpenResource")
        self.assertEqual(len(opened), len(fake_soapstone.MAPS) - len(fake_soapstone.LOADED_AT_START))
        self.assertEqual(self.fake.max_pending, 1)             # S53: one map at a time
        self.assertEqual(self.fake.refused, 0)
        for r in opened:
            self.assertEqual(r.resource.type, common_pb2.EDITOR_RESOURCE_TYPE_MAP)
            self.assertRegex(r.resource.name, r"^m\d{2}_\d{2}_\d{2}_\d{2}$")
        # S52: progress from (0, 13), map by map, never back, up to (13, 13); every report names the same total
        self.assertEqual((seen[0], seen[-1]), ((0, 13), (13, 13)))
        self.assertEqual(sorted(seen), seen)
        self.assertTrue(all(t == 13 for _, t in seen))
        self.assertEqual(sorted({d for d, _ in seen}), list(range(14)))
        self.assertEqual(self.link.loaded_maps(), list(fake_soapstone.MAPS))
        for bad in ("m99_00_00", "chr/c0000", ""):
            with self.assertRaises(ValueError):
                self.link.open_maps([bad])

    def test_all_maps_lists_every_map_loaded_or_not(self):
        # S44: Smithbox answers a file search with every map of its bank; loaded is told by an entry search.
        self.link.switch(True)
        self.assertEqual(self.link.all_maps(), sorted(fake_soapstone.MAPS))
        self.assertEqual(self.link.map_ids(), sorted(fake_soapstone.MAPS))
        self.assertTrue(self.link.is_loaded("m99_00_00_00"))
        self.assertFalse(self.link.is_loaded("m99_00_00_05"))
        asked = [r for r in self.fake.requests("SearchObjects")
                 if r.result_type.category == internal_pb2.PRIMARY_KEY_CATEGORY_ENTRY]
        self.assertTrue(asked and all(r.options.max_results == 1 for r in asked))
        with self.assertRaises(link.LinkError):
            self.link.placements("m99_00_00_05")             # known, not loaded

    def test_open_maps_skips_maps_the_project_does_not_have(self):
        self.link.switch(True)
        n = self.link.open_maps(["m99_00_00_03", "m98_00_00_00"])
        self.assertEqual(n, 1)
        self.assertEqual([r.resource.name for r in self.fake.requests("OpenResource")], ["m99_00_00_03"])

    def test_no_map_editor_says_so(self):
        self.link.switch(True)
        self.fake.no_map_editor = True
        for call in (self.link.all_maps, self.link.loaded_maps, lambda: self.link.open_maps(["m99_00_00_03"])):
            with self.assertRaises(link.LinkError) as cm:
                call()
            self.assertIn("Visual Map Editor", str(cm.exception))

    def test_a_server_failure_on_maps_says_so(self):
        self.link.switch(True)
        self.fake.fail_maps = True
        for call in (self.link.all_maps, lambda: self.link.is_loaded("m99_00_00_00")):
            with self.assertRaises(link.LinkError) as cm:
                call()
            self.assertIn("could not answer a map search", str(cm.exception))

    def test_every_search_carries_its_search_clause(self):
        # S51: SoapstoneLib refuses a SearchObjects without `search` (UNKNOWN); the fake refuses it too.
        self.link.switch(True)
        self.link.all_maps()
        self.link.is_loaded("m99_00_00_00")
        self.link.placements("m99_00_00_00")
        reqs = self.fake.requests("SearchObjects")
        self.assertTrue(reqs and all(r.HasField("search") for r in reqs))

    def test_a_refused_load_is_asked_again(self):
        # S53: Smithbox refuses a load while it still finishes the last map; DataPiler asks again until it takes it.
        self.link.switch(True)
        self.fake.busy_after_load = 3
        self.link.map_poll = 0.01
        self.link.map_reask = 0.02
        n = self.link.open_maps(["m99_00_00_03", "m99_00_00_04", "m99_00_00_05"])
        self.assertEqual(n, 3)
        self.assertGreater(self.fake.refused, 0)
        self.assertEqual(sorted(self.link.loaded_maps()), sorted(set(fake_soapstone.LOADED_AT_START) |
                                                                {"m99_00_00_03", "m99_00_00_04", "m99_00_00_05"}))

    def test_a_map_that_will_not_load_is_skipped(self):
        # S57: named in the log, skipped after map_skip, and the next map asked for.
        self.link.switch(True)
        self.fake.broken = {"m99_00_00_04"}
        self.link.map_poll = 0.01
        self.link.map_reask = 0.02
        self.link.map_skip = 0.2
        n = self.link.open_maps(["m99_00_00_03", "m99_00_00_04", "m99_00_00_05"])
        self.assertEqual(n, 2)
        self.assertEqual(self.link.skipped_maps, ["m99_00_00_04"])

    def test_three_maps_in_a_row_that_will_not_load_stop_it(self):
        self.link.switch(True)
        self.fake.broken = {"m99_00_00_03", "m99_00_00_04", "m99_00_00_05"}
        self.link.map_poll = 0.01
        self.link.map_reask = 0.02
        self.link.map_skip = 0.1
        with self.assertRaises(link.LinkError) as cm:
            self.link.open_maps(["m99_00_00_03", "m99_00_00_04", "m99_00_00_05", "m99_00_00_06"])
        self.assertIn("3 maps in a row did not load", str(cm.exception))

    def test_the_first_limit_holds_until_a_map_loads(self):
        # S58: a short first limit skips a first map that will not load, quickly; later maps use the base.
        self.link.switch(True)
        self.fake.broken = {"m99_00_00_03"}
        self.link.map_poll = 0.01
        self.link.map_reask = 0.02
        t0 = time.monotonic()
        n = self.link.open_maps(["m99_00_00_03", "m99_00_00_04"], timeout=0.3, first_timeout=0.1)
        self.assertEqual(n, 1)
        # the first map's 0.1 s, then the end-of-run retry at the base (0.3 s, or three times the slowest load)
        self.assertLess(time.monotonic() - t0, 3.0)
        self.assertEqual(self.link.skipped_maps, ["m99_00_00_03"])

    def test_open_maps_gives_up_on_a_batch_that_never_loads(self):
        # S57: nothing loading at all ends in three skips in a row and an error that says what to look at.
        self.link.switch(True)
        self.fake.load_after = 10 ** 6
        self.link.map_poll = 0.01
        self.link.map_skip = 0.1
        with self.assertRaises(link.LinkError) as cm:
            self.link.open_maps(["m99_00_00_05", "m99_00_00_06", "m99_00_00_07"])
        self.assertIn("Map Editor tab in front", str(cm.exception))

    def test_placements_as_numbers(self):
        self.link.switch(True)
        got = self.link.placements("m99_00_00_01")
        self.assertEqual(len(got), 3)                       # the map piece is not a placed character
        self.assertEqual([p.model for p in got], [9990, 9991, -1])
        for p in got:
            self.assertIsInstance(p, link.Placement)
            self.assertEqual(p.map, 99000001)
            for v in (p.map, p.entity_id, p.npc_param_id, p.talk_id, p.model):
                self.assertIs(type(v), int)
        self.assertEqual([p.entity_id for p in got], [9990010, 9990011, 9990012])
        self.assertEqual([p.npc_param_id for p in got], [9000000, 9000001, 9000002])
        self.assertEqual([p.talk_id for p in got], [9100000, 9100001, 9100002])
        self.assert_no_planted(got)
        self.assertIn("BatchGetObjects", self.fake.methods())
        with self.assertRaises(link.LinkError):             # not loaded
            self.link.placements("m99_00_00_09")

    # ---- the watcher

    def test_the_watcher_closes_the_channel_and_comes_back(self):
        interval = 0.1
        lk = self.make_link(interval=interval)
        self.assertEqual(lk.switch(True), "on")
        lk.list_params()
        before = len(self.fake.methods())
        t0 = time.monotonic()
        self.game.running = True
        self.assertTrue(wait_for(lambda: lk.state == "blocked", timeout=2.0))
        self.assertLess(time.monotonic() - t0, interval + 0.5)     # one interval, and slack for a busy machine
        self.assertIsNone(lk._channel)
        # the event follows the state on the watcher's thread: wait for it rather than race it (a flake under load)
        self.assertTrue(wait_for(lambda: "blocked" in self.states(), timeout=2.0), self.states())
        with self.assertRaises(link.LinkBlocked):
            lk.list_params()
        self.assertEqual(len(self.fake.methods()), before)
        self.game.running = False
        self.assertTrue(wait_for(lambda: lk.state == "on", timeout=2.0))
        self.assertTrue(wait_for(lambda: self.states()[-1:] == ["on"], timeout=2.0), self.states())
        self.assertEqual(lk.list_params(), ["NpcParam", "TalkParam"])
        self.assertEqual(len(self.fake.methods()), before + 1)
        lk.switch(False)
        self.assertIsNone(lk._watch)

    def test_stats(self):
        self.link.switch(True)
        self.link.list_params()
        self.link.list_param_rows("NpcParam")
        self.link.get_param_rows("NpcParam", [9000000, 9000001], ["nameId"])
        st = self.link.stats()
        self.assertEqual(st["calls"], len(self.fake.methods()))
        self.assertEqual(st["calls"], 4)
        self.assertRegex(st["last_call"], r"^\d{2}:\d{2}:\d{2}$")
        self.assertEqual(st["last_methods"], ["ListParams", "ListParamRows", "GetParamRows"])
        calls = [d for t, d in self.events if t == "link.call"]
        self.assertEqual([d["method"] for d in calls], ["ListParams", "ListParamRows", "GetParamRows",
                                                        "GetParamRows"])
        self.assertTrue(all(d["ok"] is True and isinstance(d["n"], int) for d in calls))

    def test_the_log_holds_methods_and_counts_never_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp) / "logs"
            logbook.setup(logs, max_bytes=1024 * 1024, keep=1, console=False)
            logbook.set_debug(True)
            try:
                _, seq = logbook.lines_after(2 ** 62)
                lk = self.make_link(interval=0.05)
                lk.switch(True)
                lk.list_params()
                lk.get_param_rows("NpcParam", [9000000, fake_soapstone.DUPLICATE_ID], ["nameId", "isGhost"])
                for call in (lambda: lk.get_param_rows("NpcParam", [fake_soapstone.TEXT_CELL_ID], ["nameId"]),
                             lambda: lk.list_param_rows("NoSuchParam")):
                    with self.assertRaises(link.LinkError):
                        call()
                lk.open_maps(["m99_00_00_03"])
                lk.placements("m99_00_00_03")
                self.game.running = True
                self.assertTrue(wait_for(lambda: lk.state == "blocked"))
                self.game.running = False
                self.assertTrue(wait_for(lambda: lk.state == "on"))
                lk.close(own("the test ended"))
                lines, _ = logbook.lines_after(seq)
                logbook.shutdown()
                text = (logs / "datapiler.log").read_text(encoding="utf-8")
            finally:
                logbook.set_debug(False)
                logbook.shutdown()
        msgs = [x["msg"] for x in lines if x["src"] == "link"]
        self.assertTrue(any("the game started - the server link is closed" in m for m in msgs))
        self.assertTrue(any("NOT_FOUND" in m for m in msgs))
        self.assertIn("GetParamRows: 1 items in", text)
        self.assertIn("ListParams: 2 names of another shape were dropped", text)
        for s in fake_soapstone.PLANTED:
            self.assertNotIn(s, text)
            for m in (x["msg"] for x in lines):
                self.assertNotIn(s, m)


if __name__ == "__main__":
    unittest.main()
