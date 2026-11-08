"""S27 by the code's own shape (build plan 0.2 §7.1): datapiler/update.py is the only module that opens a connection
to anywhere but 127.0.0.1, and its presses are reached only from POST /api/update. Read by ast over every module of
the app: datapiler/*.py, datapiler.py, update-helper.py and tools/*.py. The tests themselves are not the app."""

import _repo  # noqa: F401

import ast
import dataclasses
import unittest
from pathlib import Path

from datapiler import link, settings

ROOT = Path(_repo.ROOT)
NET_MODULES = ("urllib.request", "urllib.error", "http.client", "http.cookiejar", "ssl", "ftplib", "smtplib",
               "xmlrpc.client", "xmlrpc", "asyncio", "socket", "telnetlib", "poplib", "imaplib", "nntplib", "urllib3",
               "requests", "httpx", "aiohttp", "websocket", "websockets")
PRESSES = ("_check", "_download", "_install", "_cancel")
WORKERS = {"_run_check": "_check", "_run_download": "_download"}


def app_files() -> dict[str, ast.AST]:
    files = sorted((ROOT / "datapiler").glob("*.py")) + [ROOT / "datapiler.py", ROOT / "update-helper.py"] + \
        sorted((ROOT / "tools").glob("*.py"))
    return {f.relative_to(ROOT).as_posix(): ast.parse(f.read_text(encoding="utf-8"), filename=str(f)) for f in files}


def dotted(node) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def imports(tree) -> list[tuple[str, int]]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * node.level) + (node.module or "")
            out.append((mod, node.lineno))
            out += [("%s.%s" % (mod, a.name), node.lineno) for a in node.names]
    return out


def is_net(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in NET_MODULES)


def enclosing(tree) -> dict[ast.AST, list[str]]:
    """For each node, the names of the classes and functions it lies in, outermost first."""
    where: dict[ast.AST, list[str]] = {}

    def visit(node, stack):
        for child in ast.iter_child_nodes(node):
            here = stack + [child.name] if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                               ast.ClassDef)) else stack
            where[child] = here
            visit(child, here)

    visit(tree, [])
    return where


class OneNetworkModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = app_files()

    def test_the_files_are_found(self):
        for name in ("datapiler/update.py", "datapiler/api.py", "datapiler.py", "update-helper.py",
                     "tools/manifest.py", "datapiler/install.py"):
            self.assertIn(name, self.trees)

    def test_network_modules_are_imported_by_update_py_alone(self):
        allowed = {("datapiler.py", "http.client"), ("datapiler/link.py", "socket"),
                   ("datapiler/server.py", "socket"), ("datapiler/winapi.py", "socket")}
        problems = []
        for name, tree in self.trees.items():
            if name == "datapiler/update.py":
                continue
            for mod, line in imports(tree):
                if is_net(mod) and (name, mod) not in allowed:
                    problems.append("%s:%d imports %s" % (name, line, mod))
        self.assertEqual(problems, [])

    def test_the_helper_imports_none_of_them(self):
        for mod, line in imports(self.trees["update-helper.py"]):
            self.assertFalse(is_net(mod) or mod.startswith("urllib") or mod.startswith("http"), (mod, line))

    def test_connections_elsewhere_go_to_127_0_0_1_only(self):
        self.assertEqual(link.HOST, "127.0.0.1")
        problems = []
        for name, tree in self.trees.items():
            if name == "datapiler/update.py":
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    d = dotted(node) or ""
                    if d.startswith(("urllib.request", "ssl.", "ftplib", "smtplib", "xmlrpc", "asyncio")):
                        problems.append("%s:%d uses %s" % (name, node.lineno, d))
                if not isinstance(node, ast.Call):
                    continue
                d = dotted(node.func) or ""
                first = node.args[0] if node.args else None
                if d == "socket.create_connection":
                    ok = name == "datapiler/link.py" and isinstance(first, ast.Tuple) and \
                        isinstance(first.elts[0], ast.Name) and first.elts[0].id == "HOST"
                    if not ok:
                        problems.append("%s:%d socket.create_connection" % (name, node.lineno))
                elif d == "http.client.HTTPConnection":
                    ok = name == "datapiler.py" and isinstance(first, ast.Constant) and first.value == "127.0.0.1"
                    if not ok:
                        problems.append("%s:%d http.client.HTTPConnection" % (name, node.lineno))
                elif d.startswith("http.client.") and d != "http.client.HTTPException":
                    problems.append("%s:%d %s" % (name, node.lineno, d))
                elif d in ("socket.socket", "asyncio.open_connection") or d.endswith(".connect_ex"):
                    problems.append("%s:%d %s" % (name, node.lineno, d))
                elif d.endswith(".connect") and d != "sqlite3.connect":
                    problems.append("%s:%d %s" % (name, node.lineno, d))
        self.assertEqual(problems, [])

    def test_update_py_asks_only_its_hosts(self):
        from datapiler import update
        self.assertEqual(update.HOSTS, ("api.github.com", "github.com", "objects.githubusercontent.com",
                                        "release-assets.githubusercontent.com"))
        tree = self.trees["datapiler/update.py"]
        urls = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and (n.value.startswith(("http://", "https://")) or "(+http" in n.value)]
        self.assertGreaterEqual(len(urls), 4)
        for u in urls:
            self.assertTrue(u.startswith(("https://api.github.com/repos/Pt0l3my/DataPiler/",
                                          "https://github.com/Pt0l3my/DataPiler", "(+https://github.com/")) or
                            u.startswith("DataPiler/%s (+https://github.com/Pt0l3my/DataPiler)"), u)
            self.assertNotIn("http://", u)

    def test_the_presses_are_reached_only_from_post(self):
        problems = []
        for name, tree in self.trees.items():
            where = enclosing(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in PRESSES:
                    if name != "datapiler/update.py" or where.get(node) != ["Updater", "post"]:
                        problems.append("%s:%d %s from %s" % (name, node.lineno, node.attr, where.get(node)))
                if isinstance(node, ast.Attribute) and node.attr in WORKERS:
                    if name != "datapiler/update.py" or where.get(node) != ["Updater", WORKERS[node.attr]]:
                        problems.append("%s:%d %s from %s" % (name, node.lineno, node.attr, where.get(node)))
                if isinstance(node, ast.Name) and node.id == "real_fetch" and name == "datapiler/update.py":
                    if where.get(node) != ["Updater", "post"]:
                        problems.append("%s:%d real_fetch from %s" % (name, node.lineno, where.get(node)))
        self.assertEqual(problems, [])

    def test_the_presses_are_defined_on_the_updater(self):
        tree = self.trees["datapiler/update.py"]
        updater = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Updater")
        names = {n.name for n in updater.body if isinstance(n, ast.FunctionDef)}
        self.assertLessEqual(set(PRESSES) | set(WORKERS), names)

    def test_the_update_module_and_its_post_have_one_caller_each(self):
        problems = []
        posts = []
        for name, tree in self.trees.items():
            if name == "datapiler/update.py":
                continue
            where = enclosing(tree)
            for mod, line in imports(tree):
                if mod in ("datapiler.update", ".update") or mod.endswith(("datapiler.update", "..update")) or \
                        mod in (".update", "datapiler.update.Updater"):
                    if name != "datapiler.py":
                        problems.append("%s:%d imports the update module" % (name, line))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "Updater":
                    if name != "datapiler.py" or where.get(node) != ["RealParts", "updater"]:
                        problems.append("%s:%d Updater from %s" % (name, node.lineno, where.get(node)))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "post" \
                        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "updates":
                    posts.append((name, where.get(node)))
        self.assertEqual(problems, [])
        self.assertEqual(posts, [("datapiler/api.py", ["Api", "post"])])
        # and in api.py that call sits under the /api/update route
        api = (ROOT / "datapiler" / "api.py").read_text(encoding="utf-8")
        at = api.index("self.updates.post(body)")
        route = api.rfind('if path == "/api/update":', 0, at)
        self.assertGreater(route, 0)
        self.assertNotIn('if path ==', api[route + 10:at])

    def test_no_timer_or_thread_runs_a_press(self):
        banned = set(PRESSES) | {"post", "get"}
        problems = []
        for name, tree in self.trees.items():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                d = dotted(node.func) or ""
                if not d.endswith(("Thread", "Timer")):
                    continue
                targets = [k.value for k in node.keywords if k.arg in ("target", "function")] + list(node.args[:2])
                for t in targets:
                    if isinstance(t, ast.Attribute) and t.attr in banned and name == "datapiler/update.py":
                        problems.append("%s:%d %s" % (name, node.lineno, t.attr))
                    if isinstance(t, ast.Attribute) and t.attr in PRESSES:
                        problems.append("%s:%d %s" % (name, node.lineno, t.attr))
        self.assertEqual(problems, [])

    def test_no_setting_checks_or_updates(self):
        for f in dataclasses.fields(settings.Settings):
            self.assertNotIn("update", f.name)
            self.assertNotIn("check", f.name)


if __name__ == "__main__":
    unittest.main()
