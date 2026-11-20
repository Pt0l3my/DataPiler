"""probe_exe, the derivation's offline round R0 (DP36, settled S98), against a stand-in for EldenNet's devkit tool
(devkit_standin.py) with invented outputs and exit codes, an invented executable and an invented leads file: the tool
and its lint run with the game closed and their arguments as a list; the report becomes the share file as the tool
wrote it, with a local record of the run and its labels kept for the guard; each exit code stops the job in
DataPiler's words and writes no share file; the devkit's folder and its SHA256SUMS are checked first; the step waits
while the game runs and stops if it starts; Cancel stops the tool; no path reaches a log line; Pack takes the share
file and the record. Every name, label and number is invented."""

import _repo  # noqa: F401

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import test_guard_derive as tgd
import test_runner as tr
from datapiler import derive, devkit, events, fileio, guard, jobs, logbook, paths, runner
from datapiler.game import GameRunning

STAND_IN = os.path.join(_repo.ROOT, "tests", "devkit_standin.py")
JOB = "en-0044-derive-r0"
# a planted user folder, built here so that the repository's own check finds no user's folder in this file
PLANTED_PATH = "C:\\%s\\%s\\Game\\eldenring.exe" % ("Users", "velkorquist")
SUMMARY = ("probe-exe: derive.json written (incomplete): fd4 derived, 1 of 2 singletons; registration depends; "
           "task missing; group missing")


def r0_job(name: str = "derive-r0", jid: str = JOB) -> bytes:
    return json.dumps({"format": jobs.FORMAT, "id": jid, "title": "R0 (invented)",
                       "ops": [{"op": "probe_exe", "name": name}]}).encode()


def wait_for(cond, timeout: float = 15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class ProbeExeTest(tr.RunnerBase):
    def setUp(self):
        super().setUp()
        root = self.p.root
        self.game = root / "Invented Game" / "Game"
        self.game.mkdir(parents=True)
        (self.game / "eldenring.exe").write_bytes(b"MZ invented, never read by the stand-in")
        self.kit = root / "Invented Devkit"
        (self.kit / "gal").mkdir(parents=True)
        (self.kit / devkit.TOOL).write_bytes(b"MZ an invented tool; the stand-in plays it")
        (self.kit / "gal" / "leads.toml").write_text(tgd.LEADS, encoding="utf-8")
        self.write_sums()
        self.plan({"probe-exe": {"code": 1, "report": tgd.raw(tgd.report()).decode("ascii"), "stdout": [SUMMARY]},
                   "lint": {"code": 0, "stdout": ["lint: the report is clean"]}})
        self.r = self.probe_runner()

    def probe_runner(self) -> runner.Runner:
        r = runner.Runner(lambda: self.p, self.link, self.db, self.guard, lambda: self.provenance(),
                          lambda: GameRunning(self.game_running, None), lambda: "engus",
                          game_dir=lambda: str(self.game), devkit_dir=lambda: str(self.kit),
                          devkit_launch=lambda tool: [sys.executable, "-I", STAND_IN, str(tool)])
        self.runners.append(r)
        return r

    def write_sums(self) -> None:
        lines = ["%s  %s" % (fileio.sha256_file(self.kit / devkit.TOOL), devkit.TOOL),
                 "%s  gal/leads.toml" % fileio.sha256_file(self.kit / "gal" / "leads.toml"),
                 "%s  README-R0.txt" % ("ab" * 32)]
        (self.kit / devkit.SUMS).write_text("\n".join(lines) + "\n", encoding="ascii")

    def plan(self, plan: dict) -> None:
        (self.kit / "stand-in-plan.json").write_text(json.dumps(plan), encoding="utf-8")

    def calls(self) -> list[dict]:
        f = self.kit / "stand-in-calls.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []

    def failed_why(self, card: dict) -> str:
        return card["result"]["failed"]["why"]

    # ---- a run that passes

    def test_s98_the_report_becomes_the_share_file_as_the_tool_wrote_it(self):
        _, seq = logbook.lines_after(0, limit=0)
        card = self.run_job(r0_job())
        report = tgd.raw(tgd.report())
        share = self.p.share / "derive-r0.json"
        self.assertEqual(share.read_bytes(), report)
        self.assertEqual(card["result"]["share"]["name"], "derive-r0.json")
        self.assertEqual(card["result"]["local"], ["probe-exe-run.json"])
        self.assertEqual((card["ops"][0]["done"], card["ops"][0]["of"]), (3, 3))
        # the tool, then its lint, each with its arguments as a list, in the emptied working folder
        work = self.p.workspace / devkit.WORK_DIR
        calls = self.calls()
        self.assertEqual([c["args"][0] for c in calls], ["probe-exe", "lint"])
        self.assertEqual(calls[0]["args"], ["probe-exe", str(self.game / "eldenring.exe"), "--derive", "--leads",
                                            str(self.kit / "gal" / "leads.toml"), "--out",
                                            str(work / devkit.OUT)])
        self.assertEqual(calls[1]["args"], ["lint", "--report", str(work / devkit.OUT)])
        self.assertTrue(all(Path(c["cwd"]).resolve() == work.resolve() for c in calls))
        self.assertTrue(all(c["stdin"] for c in calls))
        self.assertEqual(list(work.iterdir()), [])
        # the record of the run, local; and the labels kept for the guard
        record = json.loads(paths.local_file(self.p, JOB, jobs.PROBE_RUN).read_text(encoding="ascii"))
        self.assertEqual(record["probe_exit"], 1)
        self.assertEqual(record["lint_exit"], 0)
        self.assertFalse(record["complete"])
        self.assertEqual(record["tool"]["sha256"], fileio.sha256_file(self.kit / devkit.TOOL))
        self.assertEqual(record["leads"], {"sha256": fileio.sha256_file(self.kit / "gal" / "leads.toml"),
                                           "labels": len(tgd.LABELS)})
        self.assertEqual(record["report"], {"name": "derive-r0.json", "size": len(report),
                                            "sha256": fileio.sha256_bytes(report)})
        sha = fileio.sha256_bytes(report)
        self.assertEqual(guard.labels_for(self.p.share_counts, "derive-r0.json", sha), tgd.LABELS)
        checks = self.guard.check(report, declared={}, coverage={},
                                  labels=guard.labels_for(self.p.share_counts, "derive-r0.json", sha))
        self.assertTrue(all(c.ok for c in checks))
        # the tool's own lines reach the job's log; no folder does
        lines = [x["msg"] for x in logbook.lines_after(seq)[0]]
        self.assertTrue(any(SUMMARY in x for x in lines))
        self.assertTrue(any("lint: the report is clean" in x for x in lines))
        for x in lines:
            for word in ("Invented Game", "Invented Devkit", str(self.p.root), "eldenring.exe "):
                self.assertNotIn(word, x)

    def test_s98_a_complete_report_and_lines_of_another_shape(self):
        self.plan({"probe-exe": {"code": 0, "report": tgd.raw(tgd.report()).decode("ascii"),
                                 "stdout": ["probe-exe: derive.json written (complete): fd4 derived"],
                                 "stderr": ["probe-exe: read " + PLANTED_PATH, "something else"]},
                   "lint": {"code": 0}})
        _, seq = logbook.lines_after(0, limit=0)
        self.run_job(r0_job())
        record = json.loads(paths.local_file(self.p, JOB, jobs.PROBE_RUN).read_text(encoding="ascii"))
        self.assertTrue(record["complete"])
        lines = [x["msg"] for x in logbook.lines_after(seq)[0]]
        self.assertTrue(any("2 more lines of the devkit's are not shown" in x for x in lines))
        for x in lines:
            self.assertNotIn("velkorquist", x)
            self.assertNotIn("something else", x)

    def test_s98_pack_takes_the_share_file_and_the_record(self):
        card = self.run_job(r0_job())

        def share_ok(f: Path) -> bool:
            data = f.read_bytes()
            sha = fileio.sha256_bytes(data)
            return all(c.ok for c in self.guard.check(
                data, declared={}, coverage=guard.counts_for(self.p.share_counts, f.name, sha),
                labels=guard.labels_for(self.p.share_counts, f.name, sha)))

        self.assertEqual(self.r.pack(card["id"], share_ok=share_ok), {"ok": True})
        self.assertTrue(wait_for(lambda: (self.card(JOB).get("packed") or {}).get("parts")), self.card(JOB))
        parts = [self.p.packed / x["name"] for x in self.card(JOB)["packed"]["parts"]]
        names = [n for n, _ in tr.sevenzip.check(parts)]
        self.assertEqual(sorted(names), ["%s/derive-r0.json" % JOB, "%s/probe-exe-run.json" % JOB])

    # ---- exit codes and refusals: no share file

    def test_s98_each_exit_code_of_the_tool_stops_the_job_in_plain_words(self):
        for code, words in ((2, "do not fit together"), (3, "could not read the game's executable"),
                            (4, "refused its leads file"), (5, "a fault of EldenNet's"), (6, "could not write its report"),
                            (9, "stopped unexpectedly (exit code 9)")):
            with self.subTest(code=code):
                self.plan({"probe-exe": {"code": code, "stderr": ["probe-exe: leads: singletons.x: is not a label"]},
                           "lint": {"code": 0}})
                jid = "test-%04d-r0" % (9000 + code)
                card = self.run_job(r0_job(jid=jid, name="derive-%d" % code), state="failed")
                self.assertIn(words, self.failed_why(card))
                self.assertEqual(self.share_files(), [])
                self.assertFalse(paths.local_file(self.p, jid, jobs.PROBE_RUN).exists())

    def test_s98_the_lint_refusing_stops_the_job(self):
        self.plan({"probe-exe": {"code": 1, "report": tgd.raw(tgd.report()).decode("ascii")},
                   "lint": {"code": 1, "stdout": ["lint: fd4.idiom.bytes: is not a pattern in canonical form"]}})
        _, seq = logbook.lines_after(0, limit=0)
        card = self.run_job(r0_job(), state="failed")
        self.assertIn("the devkit's lint refused the report", self.failed_why(card))
        self.assertEqual(self.share_files(), [])
        self.assertEqual(list((self.p.workspace / devkit.WORK_DIR).iterdir()), [])
        lines = [x["msg"] for x in logbook.lines_after(seq)[0]]
        self.assertTrue(any("fd4.idiom.bytes: is not a pattern" in x for x in lines))

    def test_s98_the_guard_refuses_what_the_lint_let_through(self):
        doc = tgd.report()
        doc["image"]["file_path"] = PLANTED_PATH
        self.plan({"probe-exe": {"code": 1, "report": tgd.raw(doc).decode("ascii")}, "lint": {"code": 0}})
        card = self.run_job(r0_job(), state="failed")
        self.assertEqual(card["result"]["failed"]["check"], 1)
        self.assertIn("the guard refused the share file", self.failed_why(card))
        self.assertNotIn("velkorquist", json.dumps(card))
        self.assertEqual(self.share_files(), [])

    def test_s98_a_report_that_was_not_written(self):
        self.plan({"probe-exe": {"code": 1}, "lint": {"code": 0}})
        card = self.run_job(r0_job(), state="failed")
        self.assertIn("its report could not be read", self.failed_why(card))

    # ---- the devkit's folder

    def test_s98_the_devkit_folder_is_checked_first(self):
        cases = []
        cases.append(("", "the EldenNet devkit folder is not set"))
        cases.append(("relative\\folder", "must be a full folder path"))
        cases.append((str(self.p.root / "nowhere"), "is not a folder on this PC"))
        for value, words in cases:
            with self.subTest(value=value):
                r = runner.Runner(lambda: self.p, self.link, self.db, self.guard, lambda: self.provenance(),
                                  lambda: GameRunning(False, None), lambda: "engus", game_dir=lambda: str(self.game),
                                  devkit_dir=lambda v=value: v,
                                  devkit_launch=lambda tool: [sys.executable, "-I", STAND_IN, str(tool)])
                self.runners.append(r)
                self.r = r
                jid = "test-%04d-kit" % (9100 + len(self.runners))
                card = self.run_job(r0_job(jid=jid, name=jid), state="failed")
                self.assertIn(words, self.failed_why(card))
        self.assertEqual(self.calls(), [])

    def test_s98_sha256sums_must_match(self):
        (self.kit / devkit.TOOL).write_bytes(b"MZ another invented tool")
        card = self.run_job(r0_job(jid="test-9201-sums", name="sums-a"), state="failed")
        self.assertIn("eldennet-engine.exe does not match its line in SHA256SUMS", self.failed_why(card))
        self.write_sums()
        (self.kit / "gal" / "leads.toml").write_text(tgd.LEADS + "\n[singletons]\nstray = \"Stray\"\n", encoding="utf-8")
        card = self.run_job(r0_job(jid="test-9202-sums", name="sums-b"), state="failed")
        self.assertIn("gal\\leads.toml does not match its line in SHA256SUMS", self.failed_why(card))
        (self.kit / devkit.SUMS).unlink()
        card = self.run_job(r0_job(jid="test-9203-sums", name="sums-c"), state="failed")
        self.assertIn("SHA256SUMS is not in the EldenNet devkit folder", self.failed_why(card))
        self.assertEqual(self.calls(), [])

    def test_s98_no_game_executable(self):
        (self.game / "eldenring.exe").unlink()
        card = self.run_job(r0_job(), state="failed")
        self.assertIn("eldenring.exe is not in the game folder", self.failed_why(card))
        self.assertEqual(self.calls(), [])

    # ---- the game, Cancel and the time limit

    def test_s98_it_waits_while_the_game_runs(self):
        self.game_running = True
        card, _ = self.r.add("job.json", r0_job())
        self.assertEqual(self.r.act(card["id"], "start"), {"ok": True})
        self.assertTrue(wait_for(lambda: self.card(JOB)["state"] == "waiting"), self.card(JOB))
        self.assertIn("the game is running", self.card(JOB)["wait"])
        self.assertEqual(self.calls(), [])
        self.game_running = False
        self.assertTrue(wait_for(lambda: self.card(JOB)["state"] == "done"), self.card(JOB))
        self.assertEqual(len(self.calls()), 2)

    def test_s98_the_game_starting_stops_the_tool(self):
        self.plan({"probe-exe": {"code": 1, "report": tgd.raw(tgd.report()).decode("ascii"), "sleep": 20},
                   "lint": {"code": 0}})
        card, _ = self.r.add("job.json", r0_job())
        with mock.patch.object(devkit, "GAME_POLL", 0.1):
            self.assertEqual(self.r.act(card["id"], "start"), {"ok": True})
            self.assertTrue(wait_for(lambda: len(self.calls()) == 1))
            self.game_running = True
            self.assertTrue(wait_for(lambda: self.card(JOB)["state"] == "failed"), self.card(JOB))
        self.assertIn("the game started while EldenNet's devkit read its executable", self.failed_why(self.card(JOB)))
        self.assertEqual(self.share_files(), [])

    def test_s98_cancel_stops_the_tool(self):
        self.plan({"probe-exe": {"code": 1, "report": tgd.raw(tgd.report()).decode("ascii"), "sleep": 20},
                   "lint": {"code": 0}})
        card, _ = self.r.add("job.json", r0_job())
        self.assertEqual(self.r.act(card["id"], "start"), {"ok": True})
        self.assertTrue(wait_for(lambda: len(self.calls()) == 1))
        t0 = time.monotonic()
        self.r.act(card["id"], "cancel")
        self.assertTrue(wait_for(lambda: self.card(JOB)["state"] == "cancelled"), self.card(JOB))
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual(self.share_files(), [])

    def test_s98_the_time_limit(self):
        self.plan({"probe-exe": {"code": 1, "sleep": 20}, "lint": {"code": 0}})
        with mock.patch.object(devkit, "PROBE_TIMEOUT", 0.5):
            card = self.run_job(r0_job(), state="failed")
        self.assertIn("did not finish within", self.failed_why(card))


class DevkitPartsTest(unittest.TestCase):
    def test_s98_sums_as_sha256sum_writes_them(self):
        got = devkit.sums(("%s  eldennet-engine.exe\r\n%s *gal/leads.toml\nnot a line\n%s  gal\\x.toml\n"
                           % ("AB" * 32, "cd" * 32, "ef" * 32)).encode())
        self.assertEqual(got, {"eldennet-engine.exe": "ab" * 32, "gal/leads.toml": "cd" * 32, "gal/x.toml": "ef" * 32})

    def test_s98_shown_lines(self):
        lines, left = devkit.shown(["probe-exe: written", "lint: fine", "probe-exe: C:/x", "leads: a", "x" * 300,
                                    "probe-exe: " + "y" * 300])
        self.assertEqual(lines, ["probe-exe: written", "lint: fine"])
        self.assertEqual(left, 4)

    def test_s98_words_for_every_code(self):
        for code in range(2, 7):
            self.assertIn("exit code %d" % code, devkit.probe_words(code))
        self.assertIn("exit code 1", devkit.lint_words(1))
        self.assertIn("exit code 2", devkit.lint_words(2))
        self.assertIn("exit code 7", devkit.lint_words(7))

    def test_s98_the_r0_job_s_words(self):
        job = jobs.check(tr.fixture("job-files", "good-probe-exe.json"), known_ids=(), share_names={})
        self.assertEqual(jobs.summary(job), "Reads the game's executable through EldenNet's devkit, with the game "
                                            "closed. Computes nothing. Writes the share file derive-r0.json and 1 local "
                                            "file.")
        prev = jobs.preview(job)
        self.assertEqual(prev["reads"], [jobs.PROBE_READ])
        self.assertEqual(prev["writes"], [jobs.PROBE_WRITE % "derive-r0", jobs.PROBE_LOCAL])

    def test_s98_one_share_file_a_job(self):
        raw = json.dumps({"format": jobs.FORMAT, "id": "test-9300-two", "title": "Two (invented)",
                          "ops": [{"op": "probe_exe", "name": "a"}, {"op": "probe_exe", "name": "b"}]}).encode()
        with self.assertRaises(jobs.JobRefused) as cm:
            jobs.check(raw, known_ids=(), share_names={})
        self.assertEqual([r.where for r in cm.exception.refusals], ["ops[1]"])
        raw = json.dumps({"format": jobs.FORMAT, "id": "test-9301-path", "title": "Path (invented)",
                          "ops": [{"op": "probe_exe", "name": "a", "exe": "C:\\x.exe"}]}).encode()
        with self.assertRaises(jobs.JobRefused):
            jobs.check(raw, known_ids=(), share_names={})


if __name__ == "__main__":
    unittest.main()
