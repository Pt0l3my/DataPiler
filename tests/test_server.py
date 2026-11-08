import _repo  # noqa: F401

import contextlib
import http.client
import io
import json
import os
import socket
import struct
import sys
import threading
import unittest

from datapiler import logbook, server


class EchoApi:
    def __init__(self):
        self.after = threading.Event()

    def get(self, path, query):
        if path == "/api/state":
            return 200, {"ok": True, "query": query}
        if path == "/api/boom":
            raise OSError(13, "a secret path")
        if path == "/api/bad":
            raise server.Bad("refused in DataPiler's words", field="port")
        return 404, {"error": "not found"}

    def post(self, path, body):
        if path == "/api/echo":
            return 200, {"ok": True, "body": body}, None
        if path == "/api/quit":
            return 200, {"ok": True}, self.after.set
        return 404, {"error": "not found"}, None


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = EchoApi()
        cls.app = server.App(cls.api)
        cls.httpd = server.Server(0, cls.app)
        cls.port = cls.httpd.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, body=None, *, host=None, origin="default", token="default", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or "127.0.0.1:%d" % self.port}
        if origin == "default":
            origin = "http://127.0.0.1:%d" % self.port
        if origin:
            h["Origin"] = origin
        if token == "default":
            token = self.app.token
        if token:
            h["X-DataPiler-Token"] = token
        h.update(headers or {})
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        if data is not None:
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r, raw

    def test_bound_to_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")
        self.assertEqual(server.HOST, "127.0.0.1")

    def test_wrong_host(self):
        r, _ = self.req("GET", "/api/state", host="example.invalid:%d" % self.port)
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/", host="127.0.0.1:1")
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/api/state", host="localhost:%d" % self.port)
        self.assertEqual(r.status, 200)

    def test_post_without_origin(self):
        r, _ = self.req("POST", "/api/echo", {"a": 1}, origin=None)
        self.assertEqual(r.status, 403)
        r, _ = self.req("POST", "/api/echo", {"a": 1}, origin="http://evil.invalid")
        self.assertEqual(r.status, 403)
        r, raw = self.req("POST", "/api/echo", {"a": 1})
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(raw)["body"], {"a": 1})

    def test_a_refusal_closes_a_kept_alive_connection(self):
        """Found by the end-to-end run: a refused POST's body was left unread on a kept-alive connection, and the
        next request on it was read from that body (a 400 for a good request, after a 403)."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            body = json.dumps({"a": 1}).encode()
            h = {"Host": "127.0.0.1:%d" % self.port, "Content-Type": "application/json",
                 "X-DataPiler-Token": self.app.token}
            c.request("POST", "/api/echo", body=body, headers=h)              # no Origin: refused
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 403)
            self.assertEqual((r.getheader("Connection") or "").lower(), "close")
            h["Origin"] = "http://127.0.0.1:%d" % self.port
            c.request("POST", "/api/echo", body=body, headers=h)              # http.client opens a new connection
            r = c.getresponse()
            raw = r.read()
            self.assertEqual(r.status, 200, raw)
            self.assertEqual(json.loads(raw)["body"], {"a": 1})
        finally:
            c.close()

    def test_token(self):
        r, _ = self.req("GET", "/api/state", token=None)
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/api/state", token="wrong")
        self.assertEqual(r.status, 403)
        r, _ = self.req("GET", "/api/state", token="wéird")
        self.assertEqual(r.status, 403)
        r, raw = self.req("GET", "/api/state?after=12")
        self.assertEqual(r.status, 200)
        self.assertEqual(json.loads(raw)["query"], {"after": "12"})

    def test_headers_and_csp_on_every_answer(self):
        answers = [self.req("GET", "/")[0], self.req("GET", "/api/state")[0], self.req("GET", "/nowhere")[0],
                   self.req("GET", "/api/state", token=None)[0], self.req("POST", "/api/echo", b"[1]")[0],
                   self.req("PUT", "/api/echo", {})[0], self.req("GET", "/api/boom")[0]]
        for r in answers:
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(r.getheader("Referrer-Policy"), "no-referrer")
            self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
            self.assertEqual(r.getheader("Cross-Origin-Resource-Policy"), "same-origin")
            csp = r.getheader("Content-Security-Policy")
            n = self.app.nonce
            self.assertEqual(csp, "default-src 'none'; script-src 'nonce-%s'; style-src 'nonce-%s'; connect-src 'self'; "
                                  "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                             % (n, n))
            self.assertEqual(r.getheader("Server"), "DataPiler")
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))

    def test_caps(self):
        r, _ = self.req("POST", "/api/echo", {"x": "a" * (server.POST_MAX + 10)})
        self.assertEqual(r.status, 413)
        r, _ = self.req("POST", server.DROP_PATH, {"data": "a" * (server.POST_MAX + 10)})
        self.assertNotEqual(r.status, 413)
        r, _ = self.req("POST", server.DROP_PATH, {"data": "a" * (server.DROP_MAX + 10)})
        self.assertEqual(r.status, 413)

    def test_a_refused_upload_still_gets_its_answer(self):
        """A body the server refuses unread used to be cut off by a reset on Windows (WinError 10053) before the
        client read the answer; the server now reads and discards what is still arriving before it closes."""
        for i in range(40):
            r, raw = self.req("POST", "/api/echo", {"x": "a" * (server.POST_MAX * 8)})
            self.assertEqual(r.status, 413, i)
            self.assertEqual(json.loads(raw), {"error": "too large"})
        for i in range(10):
            r, raw = self.req("POST", "/api/echo", {"x": "a" * (server.POST_MAX * 8)}, token="wrong")
            self.assertEqual(r.status, 403, i)

    def test_a_bad_request_line_is_answered(self):
        import socket as _socket
        with _socket.create_connection(("127.0.0.1", self.port), timeout=5) as c:
            c.sendall(b"NONSENSE\r\n\r\n")
            self.assertIn(b" 400 ", c.recv(4096).split(b"\r\n")[0] + b" ")

    def test_body_must_be_an_object(self):
        for body in (b"[1, 2]", b"\"text\"", b"{broken", b"\xff\xfe"):
            r, raw = self.req("POST", "/api/echo", body)
            self.assertEqual(r.status, 400, body)
            self.assertIn("error", json.loads(raw))

    def test_errors(self):
        r, raw = self.req("GET", "/api/nothing")
        self.assertEqual(r.status, 404)
        r, raw = self.req("POST", "/api/nothing", {})
        self.assertEqual(r.status, 404)
        r, raw = self.req("GET", "/api/boom")
        self.assertEqual(r.status, 500)
        self.assertEqual(json.loads(raw), {"error": "PermissionError (errno 13)"})
        r, raw = self.req("GET", "/api/bad")
        self.assertEqual(r.status, 400)
        self.assertEqual(json.loads(raw), {"error": "refused in DataPiler's words", "field": "port"})

    def test_page(self):
        r, raw = self.req("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))
        page = raw.decode("utf-8")
        self.assertIn(self.app.token, page)
        self.assertIn('nonce="%s"' % self.app.nonce, page)
        self.assertNotIn("__TOKEN__", page)
        self.assertNotIn("__NONCE__", page)

    def test_after_runs_once_the_answer_is_sent(self):
        r, raw = self.req("POST", "/api/quit", {})
        self.assertEqual(json.loads(raw), {"ok": True})
        self.assertTrue(self.api.after.wait(5))


BIG = 48 << 20      # more than the two sockets' buffers hold, so the answer is still being sent at the reset


class BigApi:
    def get(self, path, query):
        if path == "/api/big":
            return 200, b"a" * BIG
        return 404, {"error": "not found"}

    def post(self, path, body):
        return 404, {"error": "not found"}, None


class ErrorsStayOffTheWindow(unittest.TestCase):
    """The standard library prints a failed request's traceback, with DataPiler's folders in its frames, to stderr:
    the window the owner reads and copies from (design §5). Server.handle_error replaces it."""

    def setUp(self):
        self.done = threading.Event()
        self.errors = []
        test = self

        class Watched(server.Server):
            def handle_error(self, request, client_address):
                test.errors.append(sys.exc_info()[0])
                super().handle_error(request, client_address)

            def shutdown_request(self, request):
                super().shutdown_request(request)
                test.done.set()

        self.app = server.App(BigApi())
        self.httpd = Watched(0, self.app)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_a_connection_reset_mid_answer_prints_nothing(self):
        port = self.httpd.port
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            s = socket.create_connection(("127.0.0.1", port), timeout=10)
            try:
                s.sendall(b"GET /api/big HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-DataPiler-Token: %s\r\n\r\n"
                          % (port, self.app.token.encode("ascii")))
                self.assertTrue(s.recv(64).startswith(b"HTTP/1.1 200"))     # the answer has begun
                linger = struct.pack("hh" if sys.platform == "win32" else "ii", 1, 0)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)    # close with a reset
            finally:
                s.close()
            self.assertTrue(self.done.wait(20))
        self.assertTrue(self.errors, "the reset never reached handle_error")
        self.assertTrue(all(issubclass(e, OSError) for e in self.errors), self.errors)
        self.assertEqual(buf.getvalue(), "")

    def test_any_other_error_is_logged_by_its_type_only(self):
        buf = io.StringIO()
        before = logbook.lines_after(0, limit=-1)[1]
        with contextlib.redirect_stderr(buf):
            try:
                raise ValueError(os.path.join(os.path.abspath(os.sep), "Users", "player", "secret"))
            except ValueError:
                self.httpd.handle_error(None, ("127.0.0.1", 1))
        # Before logbook.setup the log's own lines go to stderr, masked: the line, never the traceback or the text.
        for word in ("Traceback", "Users", "player", "secret", "Exception occurred"):
            self.assertNotIn(word, buf.getvalue())
        lines, _ = logbook.lines_after(before)
        self.assertEqual([(ln["src"], ln["level"], ln["msg"]) for ln in lines],
                         [("page", "ERROR", "a request failed: ValueError")])


if __name__ == "__main__":
    unittest.main()
