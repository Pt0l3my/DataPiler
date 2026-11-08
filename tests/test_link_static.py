"""The server link's allowlist by construction (S3; build plan §8.2). Runs without grpcio: it reads the source.

- ALLOWED is the seven, and every path in link.py's one table names one of them, as a literal.
- No method of the service outside the seven (soapstone/SOURCE.md's full list) is named in any .py file outside
  soapstone/*_pb2.py and tests/.
- No *_pb2_grpc.py anywhere.
- grpc, google.protobuf and soapstone are imported only by datapiler/link.py (inside functions only), soapstone/ and
  LINK's tests.
- The server's port appears only in link.py; _test_port= only under tests/; vanilla only ever True."""

import _repo  # noqa: F401

import ast
import os
import re
import unittest

from datapiler import link

ROOT = _repo.ROOT
SEVEN = ("ListParams", "ListParamRows", "GetParamRows", "SearchObjects", "GetObject", "BatchGetObjects",
         "OpenResource")
SERVICE = "SoapstoneLib.Proto.Internal.Soapstone"
LINK_PY = os.path.join(ROOT, "datapiler", "link.py")
# The test modules that may import grpc, protobuf or soapstone: LINK's, and the integration test of phase 2,
# which runs the fake server.
TESTS_WITH_GRPC = {"fake_soapstone.py", "test_link.py", "test_link_static.py", "test_integration.py"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


def py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def is_generated(path: str) -> bool:
    r = rel(path)
    return r.startswith("soapstone/") and r.endswith("_pb2.py")


def in_tests(path: str) -> bool:
    return rel(path).startswith("tests/")


def source_methods() -> tuple[list[str], list[str]]:
    """(every method of the service, the allowed ones) from soapstone/SOURCE.md's table."""
    every, allowed = [], []
    for line in read(os.path.join(ROOT, "soapstone", "SOURCE.md")).splitlines():
        m = re.match(r"^\| `([A-Za-z]+)` \| (allowed|not allowed) \|", line)
        if m:
            every.append(m.group(1))
            if m.group(2) == "allowed":
                allowed.append(m.group(1))
    return every, allowed


def imported_roots(tree: ast.AST):
    """(module root, the node) for every import in the tree."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name, node
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node


def forbidden_import(name: str) -> bool:
    return name == "grpc" or name.startswith(("grpc.", "grpc_tools")) or name == "google" or \
        name.startswith("google.protobuf") or name == "soapstone" or name.startswith("soapstone.")


class LinkStaticTests(unittest.TestCase):
    def test_allowed_is_the_seven(self):
        self.assertEqual(link.ALLOWED, SEVEN)

    def test_the_table_names_only_the_seven(self):
        self.assertTrue(set(link._CALLS) <= set(link.ALLOWED))
        for method, (path, req, resp) in link._CALLS.items():
            self.assertEqual(path, "/%s/%s" % (SERVICE, method))
            self.assertEqual(req, method + "Request")
            self.assertEqual(resp, method + "Response")

    def test_paths_are_literals_and_one_unary_unary(self):
        src = read(LINK_PY)
        tree = ast.parse(src)
        self.assertEqual(len(re.findall(r"\bunary_unary\(", src)), 1)
        paths = {p for p, _, _ in link._CALLS.values()}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and SERVICE + "/" in node.value:
                self.assertIn(node.value, paths)
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if isinstance(part, ast.Constant):
                        self.assertNotIn("Soapstone", part.value)
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
                for side in (node.left, node.right):
                    if isinstance(side, ast.Constant) and isinstance(side.value, str):
                        self.assertNotIn("Soapstone", side.value)

    def test_source_md_agrees(self):
        every, allowed = source_methods()
        self.assertEqual(sorted(allowed), sorted(SEVEN))
        self.assertTrue(set(SEVEN) < set(every))
        self.assertEqual(len(every), len(set(every)))

    def test_no_other_method_named_in_the_code(self):
        every, _ = source_methods()
        others = [m for m in every if m not in SEVEN]
        self.assertTrue(others)
        rx = re.compile(r"\b(%s)\b" % "|".join(others))
        hits = []
        for path in py_files():
            if is_generated(path) or in_tests(path):
                continue
            for i, line in enumerate(read(path).splitlines(), 1):
                m = rx.search(line)
                if m:
                    hits.append("%s:%d %s" % (rel(path), i, m.group(1)))
        self.assertEqual(hits, [])

    def test_no_service_stub(self):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                self.assertFalse(f.endswith("_pb2_grpc.py"), f)
                self.assertFalse(f.endswith(".proto"), f)

    def test_imports_of_the_libraries(self):
        hits = []
        for path in py_files():
            r = rel(path)
            if r.startswith("soapstone/"):
                continue
            if in_tests(path) and os.path.basename(path) in TESTS_WITH_GRPC:
                continue
            tree = ast.parse(read(path))
            for name, node in imported_roots(tree):
                if forbidden_import(name) and r != "datapiler/link.py":
                    hits.append("%s:%d %s" % (r, node.lineno, name))
            if r == "datapiler/link.py":
                for node in tree.body:
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                            [node.module or ""]
                        for name in names:
                            if forbidden_import(name):
                                hits.append("link.py imports %s at module level" % name)
        self.assertEqual(hits, [])

    def test_the_port_only_in_link_py(self):
        """In code, outside docstrings: anything else that needs the address reads link.HOST and link.PORT."""
        port = link.PORT
        rx = re.compile(r"(?<!\d)%d(?!\d)" % port)
        hits = []
        for path in py_files():
            if in_tests(path) or rel(path) == "datapiler/link.py":
                continue
            tree = ast.parse(read(path))
            docs = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and \
                        node.body and isinstance(node.body[0], ast.Expr) and \
                        isinstance(node.body[0].value, ast.Constant):
                    docs.add(id(node.body[0].value))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or id(node) in docs:
                    continue
                if (type(node.value) is int and node.value == port) or \
                        (isinstance(node.value, str) and rx.search(node.value)):
                    hits.append("%s:%d" % (rel(path), node.lineno))
        self.assertEqual(hits, [])
        self.assertEqual(link.HOST, "127.0.0.1")

    def test_test_port_only_under_tests(self):
        hits = [rel(p) for p in py_files() if not in_tests(p) and re.search(r"_test_port\s*=", read(p))]
        self.assertEqual(hits, [])

    def test_vanilla_only_ever_true(self):
        bad = []
        found = 0
        for path in py_files():
            if is_generated(path) or in_tests(path):
                continue
            tree = ast.parse(read(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "vanilla":
                    found += 1
                    if not (isinstance(node.value, ast.Constant) and node.value.value is True):
                        bad.append("%s:%d" % (rel(path), node.value.lineno))
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Attribute) and t.attr == "vanilla":
                            if not (isinstance(node.value, ast.Constant) and node.value.value is True):
                                bad.append("%s:%d" % (rel(path), node.lineno))
            for i, line in enumerate(read(path).splitlines(), 1):
                if re.search(r"\bvanilla\s*=\s*(?!True\b)", line) and "vanilla=True" not in line:
                    bad.append("%s:%d (text)" % (rel(path), i))
        self.assertEqual(bad, [])
        self.assertGreaterEqual(found, 2)

    def test_open_resource_takes_a_map_resource_only(self):
        src = read(LINK_PY)
        calls = re.findall(r'_call\("OpenResource", (.*?)\)', src)
        self.assertEqual(len(calls), 1)
        self.assertIn("self._map_resource(", calls[0])
        tree = ast.parse(src)
        types = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                 and node.attr.startswith("EDITOR_RESOURCE_TYPE_")]
        self.assertEqual(types, ["EDITOR_RESOURCE_TYPE_MAP"])


if __name__ == "__main__":
    unittest.main()
