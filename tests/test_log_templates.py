"""An ast scan of datapiler.py and every datapiler/**/*.py: every log call's template is a string literal, no
f-string, .format or % operator in its arguments, every logbook.get source is in SOURCES, and every template
formatted with a planted invented name in each argument never shows the name."""

import _repo  # noqa: F401

import ast
import os
import unittest
from pathlib import Path

from datapiler import logbook

ROOT = Path(_repo.ROOT)
LOG_METHODS = {"debug", "info", "warn", "error"}
PLANTED = "Velkor Dunmarrow of Ashgate"


def sources():
    files = [ROOT / "datapiler.py"]
    for dirpath, dirnames, filenames in os.walk(ROOT / "datapiler"):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        files += [Path(dirpath) / f for f in filenames if f.endswith(".py")]
    return sorted(f for f in files if f.is_file())


def log_calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS \
                and node.args:
            yield node


def get_calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logbook":
            yield node


def bad_parts(node):
    for sub in ast.walk(node):
        if isinstance(sub, ast.JoinedStr):
            yield "an f-string"
        elif isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Mod):
            yield "a % operator"
        elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "format":
            yield "a .format call"


class TemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {}
        for f in sources():
            cls.trees[f.relative_to(ROOT).as_posix()] = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))

    def test_files_found(self):
        self.assertIn("datapiler.py", self.trees)
        self.assertIn("datapiler/logbook.py", self.trees)

    def test_templates_are_literals_and_arguments_plain(self):
        problems = []
        for name, tree in self.trees.items():
            for call in log_calls(tree):
                first = call.args[0]
                if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                    problems.append("%s:%d: the template is not a string literal" % (name, call.lineno))
                for arg in list(call.args) + [k.value for k in call.keywords]:
                    for why in bad_parts(arg):
                        problems.append("%s:%d: %s in a log call" % (name, call.lineno, why))
        self.assertEqual(problems, [])

    def test_sources_known(self):
        problems = []
        for name, tree in self.trees.items():
            for call in get_calls(tree):
                a = call.args[0] if call.args else None
                if not (isinstance(a, ast.Constant) and a.value in logbook.SOURCES):
                    problems.append("%s:%d: logbook.get with a source not in SOURCES" % (name, call.lineno))
        self.assertEqual(problems, [])

    def test_planted_name_never_shows(self):
        count = 0
        for name, tree in self.trees.items():
            for call in log_calls(tree):
                first = call.args[0]
                if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                    continue
                args = tuple(PLANTED for _ in call.args[1:])
                for planted in (args, tuple(PLANTED.lower() for _ in args)):
                    msg = logbook.format_message(first.value, planted)
                    self.assertNotIn(PLANTED.lower(), msg.lower(), "%s:%d" % (name, call.lineno))
                count += 1
        self.assertGreater(count, 10)

    def test_the_real_log_hides_a_planted_name(self):
        _, seq = logbook.lines_after(0, limit=0)
        logbook.get("app").info("%s and %s", PLANTED, logbook.own("own words"))
        lines, _ = logbook.lines_after(seq, limit=10)
        self.assertTrue(lines)
        self.assertNotIn(PLANTED, lines[-1]["msg"])


if __name__ == "__main__":
    unittest.main()
