"""Puts the repository root on sys.path: the test command runs with -I, which leaves only tests/ on it. Every test
module imports this first (`import _repo  # noqa: F401`)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
