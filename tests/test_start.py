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
        self.assertIn("---- DataPiler 0.1.0 ----", log)
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


if __name__ == "__main__":
    unittest.main()
