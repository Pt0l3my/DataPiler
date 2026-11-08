import _repo  # noqa: F401

import contextlib
import http.client
import importlib.util
import io
import json
import re
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from datapiler import VERSION, install
from test_api import FakeParts

_spec = importlib.util.spec_from_file_location("datapiler_main", str(Path(_repo.ROOT) / "datapiler.py"))
entry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(entry)


def wait_for(fn, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return None


class StartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.port_file = self.root / "datapiler.port"

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, *args):
        out = {}
        parts = FakeParts()

        def run():
            with contextlib.redirect_stdout(io.StringIO()):
                out["code"] = entry.main(["--port", "0", "--no-browser", *args], root=self.root, parts=parts)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t, out, parts

    def read_port(self):
        try:
            text = self.port_file.read_text(encoding="ascii").strip()
            return int(text) if text and text != "1" else None
        except (OSError, ValueError):
            return None

    def quit(self, port):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/", headers={"Host": "127.0.0.1:%d" % port})
        page = c.getresponse().read().decode("utf-8")
        token = re.search(r'const TOKEN = "([^"]+)"', page).group(1)
        c.request("POST", "/api/quit", body=json.dumps({"cancel_running": False}).encode(),
                  headers={"Host": "127.0.0.1:%d" % port, "Origin": "http://127.0.0.1:%d" % port,
                           "X-DataPiler-Token": token, "Content-Type": "application/json"})
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        return body

    def test_start_and_stop(self):
        self.port_file.write_text("1", encoding="ascii")        # left by a killed run
        t, out, parts = self.start()
        port = wait_for(self.read_port)
        self.assertTrue(port, "the port file was not written")
        self.assertNotEqual(port, 1)
        self.assertTrue(parts.made["runner"].loaded)
        self.assertTrue(parts.made["inbox"].running)
        # a second start finds the first and exits 3
        with contextlib.redirect_stdout(io.StringIO()) as said:
            code = entry.main(["--port", "0", "--no-browser"], root=self.root, parts=FakeParts())
        self.assertEqual(code, 3)
        self.assertIn("DataPiler is running already: http://127.0.0.1:%d/" % port, said.getvalue())
        self.assertEqual(self.read_port(), port)
        self.assertEqual(self.quit(port), {"ok": True})
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertEqual(out["code"], 0)
        self.assertFalse(self.port_file.exists())
        self.assertEqual(parts.made["runner"].stopped, True)
        self.assertFalse(parts.made["inbox"].running)
        self.assertTrue(parts.made["textdb"].closed)
        self.assertEqual(parts.made["link"].closed, "DataPiler is stopping")
        log = (self.root / "logs" / "datapiler.log").read_text(encoding="utf-8")
        self.assertIn("---- DataPiler %s ----" % VERSION, log)
        self.assertIn("Page: http://127.0.0.1:%d/" % port, log)
        self.assertIn("  INFO   app      stopped", log)
        self.assertNotIn(self.tmp.name, log)
        self.assertFalse((self.root / "datapiler-start.log").exists())
        # the mutex is free again
        t2, out2, _ = self.start()
        port2 = wait_for(self.read_port)
        self.assertTrue(port2)
        self.quit(port2)
        t2.join(10)
        self.assertEqual(out2["code"], 0)

    def test_a_workspace_on_a_network_drive_is_warned_of(self):
        """DataPiler's own folder on a network drive puts the default workspace there too (settings.check refuses
        only a full path on one): the start says so."""
        from datapiler import winapi

        class Remote(winapi.PortableBackend):
            def drive_is_remote(self, path):
                return True

        with winapi.use(Remote()):
            t, out, _ = self.start()
            port = wait_for(self.read_port)
            self.assertTrue(port)
            self.quit(port)
            t.join(10)
        log = (self.root / "logs" / "datapiler.log").read_text(encoding="utf-8")
        self.assertIn("WARN   app      the workspace is on a network drive", log)

    def test_port_that_does_not_open(self):
        self.port_file.write_text("1", encoding="ascii")
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy = s.getsockname()[1]
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = entry.main(["--port", str(busy), "--no-browser"], root=self.root, parts=FakeParts())
        finally:
            s.close()
        self.assertEqual(code, 2)
        self.assertFalse(self.port_file.exists())
        text = (self.root / "datapiler-start.log").read_text(encoding="utf-8")
        self.assertIn("the page's port %d did not open" % busy, text)

    def test_crash_before_the_page_writes_the_start_log(self):
        class Broken(FakeParts):
            def runner(self, *a):
                raise RuntimeError("an invented failure")

        with contextlib.redirect_stdout(io.StringIO()):
            code = entry.main(["--port", "0", "--no-browser"], root=self.root, parts=Broken())
        self.assertEqual(code, 1)
        text = (self.root / "datapiler-start.log").read_text(encoding="utf-8")
        self.assertIn("DataPiler did not start: RuntimeError", text)
        self.assertIn("Python 3.", text)
        self.assertIn("no .venv", text)
        self.assertNotIn(self.tmp.name, text)
        self.assertFalse(self.port_file.exists())
        # and the mutex was released
        t, out, _ = self.start()
        port = wait_for(self.read_port)
        self.quit(port)
        t.join(10)
        self.assertEqual(out["code"], 0)


class FakeUpdater:
    """The update routes' far end, as update.Updater answers them: Install's answer asks for exit code 75."""

    def __init__(self, run):
        self.run = run
        self.came = None
        self.closed = False

    def get(self):
        return {"state": "idle"}

    def post(self, body):
        if body.get("action") == "install":
            return 200, {"ok": True, "state": "restarting", "to": "0.3.0"}, self.run.request_update_exit
        return 200, {"state": "idle"}, None

    def result(self):
        return {"state": None}

    def came_back(self, pending, check):
        self.came = (pending, check)

    def close(self):
        self.closed = True


class UpdateParts(FakeParts):
    def __init__(self, real=False):
        super().__init__()
        self.real = real

    def updater(self, run):
        if self.real:
            from datapiler import update

            def no_network(url, headers, timeout):
                raise AssertionError("no test reaches the network")

            self.made["updater"] = update.Updater(root=run.root, version=VERSION, port=lambda: run.port,
                                                  busy=run.runner.busy, request_exit=run.request_update_exit,
                                                  fetch=no_network)
        else:
            self.made["updater"] = FakeUpdater(run)
        return self.made["updater"]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class UpdateStart(unittest.TestCase):
    """Build plan 0.2 §4.8: exit 75 after Install, the port of the page that asked, the install check's line,
    update/pending.json removed once the page is up, and the result served once."""

    setUp = StartTest.setUp
    tearDown = StartTest.tearDown
    read_port = StartTest.read_port
    quit = StartTest.quit

    def start_with(self, parts, *args):
        out = {}

        def run():
            with contextlib.redirect_stdout(io.StringIO()):
                out["code"] = entry.main(list(args), root=self.root, parts=parts)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t, out

    def api(self, port, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/", headers={"Host": "127.0.0.1:%d" % port})
        page = c.getresponse().read().decode("utf-8")
        token = re.search(r'const TOKEN = "([^"]+)"', page).group(1)
        headers = {"Host": "127.0.0.1:%d" % port, "X-DataPiler-Token": token}
        data = None
        if method == "POST":
            headers.update({"Origin": "http://127.0.0.1:%d" % port, "Content-Type": "application/json"})
            data = json.dumps(body or {}).encode()
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        answer = json.loads(r.read())
        c.close()
        return r.status, answer

    def pending(self, port):
        return install.write_pending(self.root.resolve(), from_version="0.2.0", to_version="0.3.0",
                                     zip_rel="update/0.3.0/DataPiler-0.3.0.zip", zip_sha256="ab" * 32, zip_size=10,
                                     port=port)

    def log(self):
        return (self.root / "logs" / "datapiler.log").read_text(encoding="utf-8")

    def test_exit_75_after_install(self):
        parts = UpdateParts()
        t, out = self.start_with(parts, "--port", "0", "--no-browser")
        port = wait_for(self.read_port)
        self.assertTrue(port)
        self.assertEqual(self.api(port, "POST", "/api/update", {"action": "install"}),
                         (200, {"ok": True, "state": "restarting", "to": "0.3.0"}))
        t.join(10)
        self.assertFalse(t.is_alive())
        self.assertEqual(out["code"], 75)
        self.assertTrue(parts.made["updater"].closed)
        self.assertFalse(self.port_file.exists())
        self.assertIn("  INFO   app      stopped", self.log())

    def test_the_port_of_the_page_that_asked(self):
        want = free_port()
        p = self.pending(want)
        parts = UpdateParts()
        with mock.patch("webbrowser.open") as opened:
            t, out = self.start_with(parts)
            port = wait_for(self.read_port)
            self.assertEqual(port, want)
            for _ in range(100):
                if parts.made["updater"].came is not None:
                    break
                time.sleep(0.02)
            self.assertFalse((self.root / "update" / "pending.json").exists())
            self.quit(port)
            t.join(10)
            time.sleep(0.6)
        opened.assert_not_called()
        self.assertEqual(parts.made["updater"].came[0], p)
        self.assertFalse(parts.made["updater"].came[1].manifest)
        log = self.log()
        self.assertIn("Page: http://127.0.0.1:%d/ (the open page reloads)" % want, log)
        self.assertIn("INFO   update   install check: no manifest.sha256 - a copy from the repository, not a "
                      "release", log)

    def test_the_port_taken_opens_a_new_tab(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        busy = s.getsockname()[1]
        self.pending(busy)
        try:
            with mock.patch("webbrowser.open") as opened:
                t, out = self.start_with(UpdateParts())
                port = wait_for(self.read_port)
                self.assertTrue(port)
                self.assertNotEqual(port, busy)
                for _ in range(100):
                    if opened.called:
                        break
                    time.sleep(0.02)
                self.quit(port)
                t.join(10)
        finally:
            s.close()
        opened.assert_called_once_with("http://127.0.0.1:%d/" % port)
        log = self.log()
        self.assertIn("WARN   app      the page's port before the update was taken - a new tab opens", log)
        self.assertIn("Page: http://127.0.0.1:%d/ (the browser opens it)" % port, log)
        self.assertEqual(out["code"], 0)

    def test_the_install_check_of_a_release(self):
        (self.root / "a.txt").write_bytes(b"a\n")
        # bytes, not write_text: on Windows text mode would end the line in CR LF, which a release's manifest never
        # has and the parser rightly refuses
        (self.root / "manifest.sha256").write_bytes(
            ("%s  a.txt\n" % __import__("hashlib").sha256(b"a\n").hexdigest()).encode("ascii"))
        t, out = self.start_with(UpdateParts(), "--port", "0", "--no-browser")
        port = wait_for(self.read_port)
        for _ in range(100):
            if "install check" in self.log():
                break
            time.sleep(0.02)
        self.quit(port)
        t.join(10)
        self.assertIn("INFO   update   install check: all 1 files match the release", self.log())

    def test_the_result_is_served_once(self):
        p = self.pending(free_port())
        (self.root / "update" / "result.json").write_text(json.dumps({
            "format": "datapiler-update-result/1", "nonce": p.nonce, "state": "failed", "from": "0.2.0",
            "to": "0.3.0", "stage": "write", "text": "datapiler/jobs.py could not be written: PermissionError "
            "(errno 13)", "backup": "update/backup-0.2.0", "restored": True, "counts": None}))
        (self.root / "update" / "0.3.0").mkdir(parents=True)
        (self.root / "update" / "0.3.0" / "DataPiler-0.3.0.zip").write_bytes(b"zip")
        parts = UpdateParts(real=True)
        t, out = self.start_with(parts, "--no-browser")
        port = wait_for(self.read_port)
        for _ in range(100):
            if not (self.root / "update" / "0.3.0").exists():
                break
            time.sleep(0.02)
        code, r = self.api(port, "GET", "/api/update-result")
        self.assertEqual((code, r["state"], r["stage"], r["restored"], r["backup"]),
                         (200, "failed", "write", True, "update\\backup-0.2.0"))
        self.assertEqual(r["check"], {"files": 0, "differ": 0, "manifest": False})
        self.assertEqual(self.api(port, "GET", "/api/update-result"), (200, {"state": None}))
        self.assertEqual(self.api(port, "GET", "/api/update")[1]["state"], "idle")
        self.assertFalse((self.root / "update" / "pending.json").exists())
        self.assertFalse((self.root / "update" / "0.3.0").exists())      # the clean-up at page-up
        self.quit(port)
        t.join(10)
        self.assertEqual(out["code"], 0)

    def test_a_bad_pending_file_is_removed_and_the_start_goes_on(self):
        (self.root / "update").mkdir()
        (self.root / "update" / "pending.json").write_text('{"format": "datapiler-update-pending/1", "port": 1}')
        t, out = self.start_with(UpdateParts(), "--port", "0", "--no-browser")
        port = wait_for(self.read_port)
        self.assertTrue(port)
        self.quit(port)
        t.join(10)
        self.assertFalse((self.root / "update" / "pending.json").exists())
        self.assertIn("WARN   update   update/pending.json is not as DataPiler writes it", self.log())


if __name__ == "__main__":
    unittest.main()
