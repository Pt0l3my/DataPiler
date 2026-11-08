"""The share file's format and the guard's six checks (design 0001 §6, settled S5, S6, S19, S20, S25 and S26, DP8,
build plan §4.10).

A share file's bytes are checked before they are written, and nothing is written unless all six checks pass:

1. **Shape**: the format's keys only, tables and columns exactly as the job declared them.
2. **Values**: every cell of its column's type (finite numbers allowed, S5); notes are labels; no other string.
3. **Text**: no string value is or holds a text of the local text database, nor sits inside one. The format's own keys
   are not checked: they come from the format, and check 1 fixes them. A value that is exactly one of DataPiler's
   fixed words (`fixed_words()`: its labels, S6, its column types and enum values, the column names its operations
   make, the expansion's source and the format constant) is skipped (S20, build plan §10 P12). Each value is
   compared as it is and normalised, accents and the signs between words aside (`TextDB.text_hit`, S25).
4. **The owner**: no path, drive letter, `~`, user or PC name (whatever signs stand between its parts:
   `owner_patterns`, S26), or IP address in any string.
5. **Size**: at most `MAX_BYTES` bytes and `MAX_VALUES` values.
6. **Coverage** (DP8, S19): no table, nor the file's tables from one game table together, covers more than half of
   the rows of the game table it came from. The runner hands the guard each table's row counts and source
   (`coverage`); a table with no counts fails, so a file DataPiler did not write never passes. The counts are kept
   beside the workspace (`record_counts`), never in the share file.

A failure names the check and the place (`tables[1].rows[40][2]`, `tables[0]`), never the value. `_strings` follows
LLM Jobrunner 1.2's `_strings`, walking keys and values with their places (build plan §7.2)."""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator, Mapping, Sequence

from . import events, fields, fileio, logbook, paths
from .logbook import own

if TYPE_CHECKING:
    from .textdb import TextDB

SHARE_FORMAT = "datapiler-share/1"
LABELS: tuple[str, ...] = ("named_only", "vanilla_rows", "loaded_maps_only", "summary")   # ours; snake_case ASCII
ENUMS: dict[str, tuple[str, ...]] = {"source": ("server", "guided")}
MAX_BYTES = 4 * 1024 * 1024
MAX_VALUES = 200_000
MAX_TABLES = 32
MAX_COLUMNS = 64

CHECKS = (1, 2, 3, 4, 5, 6)
NAMES = {1: "Shape", 2: "Values", 3: "Text", 4: "The owner", 5: "Size", 6: "Coverage"}
WORDS = {1: "the share file's shape", 2: "a value that is not a number, a flag or a label",
         3: "a string the text database holds", 4: "a path, a name of the PC's or its user's, or an address",
         5: "over the size limits",
         6: "a table covering, alone or with the file's other tables from the same game table, more than half of "
            "that game table's rows, or one without its row counts"}

# The text sets join_names knows (jobs.TEXTS is this tuple), each a key of provenance.names.
NAME_SETS = ("character_names", "place_names")
# Who said whether the expansion is installed: the owner, in Settings (P2). A file check is a hint on Status only.
EXPANSION_SOURCES = ("owner",)

TOP_KEYS = ("format", "job", "provenance", "tables", "notes")
JOB_KEYS = ("id", "sha256")
PROVENANCE_KEYS = ("game_version", "regulation_sha256", "expansion", "expansion_source", "language", "names",
                   "smithbox_build", "datapiler", "date")
NAMES_KEYS = ("wrappers", "verified", "resolved")      # provenance.names.<set>: the leads verified at join time (P3)
TABLE_KEYS = ("name", "columns", "rows")
COLUMN_KEYS = ("name", "type")
FORMAT_KEYS = frozenset(TOP_KEYS + JOB_KEYS + PROVENANCE_KEYS + NAME_SETS + NAMES_KEYS + TABLE_KEYS + COLUMN_KEYS)
COLUMN_TYPES = ("int", "number", "bool", "label")
MAX_WRAPPERS = 16
VERIFY_SHARE = 0.5                                      # textdb.VERIFY_SHARE: at least half must resolve
COUNTS_FORMAT = "datapiler-share-counts/2"     # /2: each table's source (the game table) beside its counts (S19)
COUNTS_MAX_FILES = 4096
NO_COUNTS = "(no row counts)"

HEX64_RX = re.compile(r"[0-9a-f]{64}")
VERSION_RX = re.compile(r"\d{1,5}(\.\d{1,5}){1,3}")
LANGUAGE_RX = re.compile(r"[a-z]{2,8}")
DATE_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
TABLE_RX = re.compile(r"[a-z][a-z0-9_]{0,31}")
DRIVE_RX = re.compile(r"(?<![A-Za-z])[A-Za-z]:([\\/]|$)")
IPV4_RX = re.compile(r"(?<!\d)\d{1,3}(?:\.\d{1,3}){3}(?!\d)")
IPV6_RX = re.compile(r"[0-9A-Fa-f.:]*:[0-9A-Fa-f.:]*:[0-9A-Fa-f.:]*")
NO_IP_RULE = ("provenance.game_version", "provenance.smithbox_build")   # their shape is fixed by check 1 (§10, P8)
INT_LIMIT = 2 ** 63

_log = logbook.get("guard")


@dataclass(frozen=True)
class CheckResult:
    check: int            # 1 to 5
    name: str             # "Shape", "Values", "Text", "The owner", "Size"
    ok: bool
    where: str | None     # the first failing place, e.g. "tables[1].rows[40][2]", "notes[0]", "provenance.language"


class GuardFailed(Exception):
    def __init__(self, check: int, where: str | None):
        self.check = check
        self.where = where or ""
        super().__init__("check %d at %s" % (check, where) if where else "check %d" % check)


@dataclass(frozen=True)
class ShareWritten:
    name: str             # the file's name, "roster-counts.json"
    size: int
    sha256: str


# ------------------------------------------------------------------------------------------------ reading

class _Obj(dict):
    dups: bool = False


def _pairs(pairs: list) -> _Obj:
    o = _Obj()
    for k, v in pairs:
        if k in o:
            o.dups = True
        o[k] = v
    return o


def _parse(data: bytes) -> object:
    """Raises ValueError (not UTF-8, not JSON) or RecursionError."""
    return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)


def _key_place(place: str, key: str, value: bool) -> str:
    if key in FORMAT_KEYS:
        return "%s.%s" % (place, key) if place else key
    base = place or "(top level)"
    return base + (" (a key's value)" if value else " (a key)")


def _strings(o: object) -> Iterator[tuple[str, str, bool]]:
    """(place, string, is_key) for every string, keys included, in the file's order."""
    stack: list[tuple[object, str, bool]] = [(o, "", False)]
    while stack:
        x, place, is_key = stack.pop()
        if isinstance(x, str):
            yield place, x, is_key
        elif isinstance(x, dict):
            items: list[tuple[object, str, bool]] = []
            for k, v in x.items():
                items.append((k, _key_place(place, k, False), True))
                items.append((v, _key_place(place, k, True), False))
            stack.extend(reversed(items))
        elif isinstance(x, list):
            stack.extend(reversed([(v, "%s[%d]" % (place, i), False) for i, v in enumerate(x)]))


def _column_type_ok(t: object) -> bool:
    if not isinstance(t, str):
        return False
    if t in COLUMN_TYPES:
        return True
    return t.startswith("enum:") and t[5:] in ENUMS


def _cell_ok(t: str, v: object) -> bool:
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool) and abs(v) < INT_LIMIT
    if t == "number":
        if isinstance(v, bool):
            return False
        if isinstance(v, int):
            return abs(v) < INT_LIMIT
        return isinstance(v, float) and math.isfinite(v)
    if t == "bool":
        return isinstance(v, bool)
    if t == "label":
        return isinstance(v, str) and v in LABELS
    if t.startswith("enum:"):
        return isinstance(v, str) and v in ENUMS.get(t[5:], ())
    return False


def fixed_words() -> frozenset[str]:
    """DataPiler's fixed words, which check 3 skips where a value is exactly one of them (S6, S20): the labels, the
    column types and enum values, the column names its operations make (fields.PARAMS's fields, the placements'
    columns, `named` and `count`), the expansion's source and the format constant. Each is a word of DataPiler's
    own code, never one read from the game or a job; table names, job ids and every other value stay checked."""
    from . import jobs     # jobs imports this module: its columns are read here, at the check

    words = set(LABELS) | set(COLUMN_TYPES) | set(EXPANSION_SOURCES) | {SHARE_FORMAT}
    for name, values in ENUMS.items():
        words.add("enum:" + name)
        words.update(values)
    for flds in fields.PARAMS.values():
        words.update(flds)
    words.update(c for c, _ in jobs.PLACEMENT_COLUMNS)
    words.update(jobs.MADE_COLUMNS)
    return frozenset(words)


# ------------------------------------------------------------------------------------------------ the checks

def _check_shape(doc: object, declared: Mapping[str, Sequence[str]]) -> str | None:
    from . import jobs     # jobs imports this module: its patterns are read here, at the check

    if not isinstance(doc, dict):
        return "(file)"
    if getattr(doc, "dups", False) or set(doc) != set(TOP_KEYS):
        return "(top level)"
    if doc["format"] != SHARE_FORMAT:
        return "format"
    job = doc["job"]
    if not isinstance(job, dict) or getattr(job, "dups", False) or set(job) != set(JOB_KEYS):
        return "job"
    jid = job["id"]
    if not isinstance(jid, str) or not (jobs.ID_RX.fullmatch(jid) or jobs.BUILTIN_ID_RX.fullmatch(jid)):
        return "job.id"
    if not isinstance(job["sha256"], str) or not HEX64_RX.fullmatch(job["sha256"]):
        return "job.sha256"
    prov = doc["provenance"]
    if not isinstance(prov, dict) or getattr(prov, "dups", False) or set(prov) != set(PROVENANCE_KEYS):
        return "provenance"
    for key, rx in (("game_version", VERSION_RX), ("regulation_sha256", HEX64_RX), ("language", LANGUAGE_RX),
                    ("smithbox_build", VERSION_RX), ("datapiler", VERSION_RX), ("date", DATE_RX)):
        v = prov[key]
        if not isinstance(v, str) or not rx.fullmatch(v):
            return "provenance." + key
    if not isinstance(prov["expansion"], bool):
        return "provenance.expansion"
    if not isinstance(prov["expansion_source"], str) or prov["expansion_source"] not in EXPANSION_SOURCES:
        return "provenance.expansion_source"
    where = _check_names(prov["names"])
    if where is not None:
        return where
    tables = doc["tables"]
    if not isinstance(tables, list) or not 1 <= len(tables) <= MAX_TABLES:
        return "tables"
    want = list(declared.items())
    if len(tables) != len(want):
        return "tables"
    for i, t in enumerate(tables):
        tp = "tables[%d]" % i
        if not isinstance(t, dict) or getattr(t, "dups", False) or set(t) != set(TABLE_KEYS):
            return tp
        if not isinstance(t["name"], str) or not TABLE_RX.fullmatch(t["name"]) or t["name"] != want[i][0]:
            return tp + ".name"
        cols = t["columns"]
        if not isinstance(cols, list) or not 1 <= len(cols) <= MAX_COLUMNS:
            return tp + ".columns"
        names = list(want[i][1])
        if len(cols) != len(names):
            return tp + ".columns"
        for j, c in enumerate(cols):
            cp = "%s.columns[%d]" % (tp, j)
            if not isinstance(c, dict) or getattr(c, "dups", False) or set(c) != set(COLUMN_KEYS):
                return cp
            if not isinstance(c["name"], str) or not fields.FIELD_RX.fullmatch(c["name"]) or c["name"] != names[j]:
                return cp + ".name"
            if not _column_type_ok(c["type"]):
                return cp + ".type"
        rows = t["rows"]
        if not isinstance(rows, list):
            return tp + ".rows"
        for k, r in enumerate(rows):
            if not isinstance(r, list) or len(r) != len(cols):
                return "%s.rows[%d]" % (tp, k)
    if not isinstance(doc["notes"], list):
        return "notes"
    return None


def _check_names(names: object) -> str | None:
    """provenance.names: for each text set a job joined, the wrapper leads verified with the owner's own numbers and
    the share of them that resolved (P3); {} when the job joined no names."""
    if not isinstance(names, dict) or getattr(names, "dups", False) or not set(names) <= set(NAME_SETS):
        return "provenance.names"
    for key, v in names.items():
        place = "provenance.names." + key
        if not isinstance(v, dict) or getattr(v, "dups", False) or set(v) != set(NAMES_KEYS):
            return place
        w = v["wrappers"]
        if not isinstance(w, list) or not 1 <= len(w) <= MAX_WRAPPERS or \
                not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 2 ** 31 for x in w):
            return place + ".wrappers"
        if v["verified"] is not True:
            return place + ".verified"
        r = v["resolved"]
        if isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r) or \
                not VERIFY_SHARE <= r <= 1:
            return place + ".resolved"
    return None


def _check_values(doc: object) -> str | None:
    if not isinstance(doc, dict):
        return "(file)"
    tables = doc.get("tables")
    for i, t in enumerate(tables if isinstance(tables, list) else []):
        if not isinstance(t, dict):
            continue
        cols = t.get("columns")
        types = [c.get("type") if isinstance(c, dict) else None for c in cols] if isinstance(cols, list) else []
        rows = t.get("rows")
        for k, r in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(r, list):
                continue
            for j, v in enumerate(r):
                typ = types[j] if j < len(types) else None
                if not (isinstance(typ, str) and _column_type_ok(typ) and _cell_ok(typ, v)):
                    return "tables[%d].rows[%d][%d]" % (i, k, j)
    notes = doc.get("notes")
    for j, x in enumerate(notes if isinstance(notes, list) else []):
        if not isinstance(x, str) or x not in LABELS:
            return "notes[%d]" % j
    return None


def _check_coverage(doc: object, coverage: Mapping[str, object] | None) -> str | None:
    """Check 6 (DP8, S19). For each table, coverage names what to measure: None for counts alone (a table whose only
    column is `count`), or (column, of, source): source the game table it came from (a param's name, or
    `placements`), of that game table's rows, and column the row-id column to measure by its distinct values, or None
    to measure by the table's rows (one per source row, or one per group of a count or a distinct). The tables of one
    source are measured together, in the file's order: their distinct row ids, each counted once whichever table
    holds it, plus the rows of those measured by rows, must stay at most half of `of` (the lowest given for that
    source). So several tables, each under half, never carry a whole table between them. A table missing from
    coverage, or no coverage at all, fails: the guard never guesses a count. The failure names the table at which
    its source passes half."""
    if not isinstance(doc, dict) or not isinstance(doc.get("tables"), list):
        return "(file)"
    if coverage is None:
        return NO_COUNTS
    ids: dict[str, set] = {}
    rows_of: dict[str, int] = {}
    bound: dict[str, int] = {}
    for i, t in enumerate(doc["tables"]):
        place = "tables[%d]" % i
        if not isinstance(t, dict) or not isinstance(t.get("name"), str) or t["name"] not in coverage:
            return place
        spec = coverage[t["name"]]
        if spec is None:
            continue
        if not _spec_ok(spec):
            return place
        column, of, source = spec        # type: ignore[misc]
        rows = t.get("rows")
        if not isinstance(rows, list):
            return place
        if column is None:
            rows_of[source] = rows_of.get(source, 0) + len(rows)
        else:
            cols = t.get("columns")
            names = [c.get("name") if isinstance(c, dict) else None for c in cols] if isinstance(cols, list) else []
            if column not in names:
                return place
            j = names.index(column)
            seen = ids.setdefault(source, set())
            for r in rows:
                if not isinstance(r, list) or j >= len(r):
                    return place
                v = r[j]
                seen.add((column, type(v).__name__, v) if isinstance(v, (bool, int, float, str)) or v is None
                         else (column, repr(v)))
        bound[source] = min(bound.get(source, of), of)
        if (len(ids.get(source, ())) + rows_of.get(source, 0)) * 2 > bound[source]:
            return place
    return None


def _ip_in(s: str) -> bool:
    import ipaddress
    for m in IPV4_RX.finditer(s):
        try:
            ipaddress.IPv4Address(m.group(0))
            return True
        except ValueError:
            continue
    for m in IPV6_RX.finditer(s):
        cand = m.group(0).strip(".:") if m.group(0).count(":") >= 2 else ""
        for c in (m.group(0), cand):
            if c.count(":") < 2:
                continue
            try:
                ipaddress.IPv6Address(c)
                return True
            except ValueError:
                continue
    return False


def owner_patterns(words: Sequence[str]) -> list[re.Pattern]:
    """Check 4's patterns for the owner's words (the user name and the PC name), to search case-folded text with. Each
    is built from the word's letters and digits, with any signs between them, or none (`[\\W_]*`), and stands as a
    whole word: so `DESKTOP-XXXXXXX` is found as `desktop_xxxxxxx` too, and a user name of two parts with `_`, `-`
    or nothing between them. Copy for sharing uses the same patterns (`api.owner_hit`)."""
    out = []
    for w in words:
        parts = re.findall(r"[^\W_]+", w.casefold()) if isinstance(w, str) else []
        if parts:
            out.append(re.compile(r"(?<![^\W_])%s(?![^\W_])" % r"[\W_]*".join(re.escape(x) for x in parts)))
    return out


def owner_fault(s: str, place: str, words: Sequence[re.Pattern]) -> bool:
    """Check 4 for one string at its place: a path sign, a drive letter, `~`, an owner's word or an IP address."""
    if "\\" in s or "~" in s:
        return True
    if "/" in s and s != SHARE_FORMAT:
        return True
    if DRIVE_RX.search(s):
        return True
    folded = s.casefold()
    if any(rx.search(folded) for rx in words):
        return True
    if place not in NO_IP_RULE and _ip_in(s):
        return True
    return False


def _count_values(doc: object) -> tuple[int, str | None]:
    """The values (cells and notes), and the place where the count first passes MAX_VALUES."""
    count = 0
    if not isinstance(doc, dict):
        return 0, None
    tables = doc.get("tables")
    for i, t in enumerate(tables if isinstance(tables, list) else []):
        rows = t.get("rows") if isinstance(t, dict) else None
        for k, r in enumerate(rows if isinstance(rows, list) else []):
            count += len(r) if isinstance(r, list) else 1
            if count > MAX_VALUES:
                return count, "tables[%d].rows[%d]" % (i, k)
    notes = doc.get("notes")
    for j, _ in enumerate(notes if isinstance(notes, list) else []):
        count += 1
        if count > MAX_VALUES:
            return count, "notes[%d]" % j
    return count, None


# ------------------------------------------------------------------------------------------------ the guard

class Guard:
    def __init__(self, textdb: "TextDB", owner_words: Callable[[], list[str]]):
        """owner_words: the user name and the PC name (from winapi), never logged. The labels are checked against
        check 4 at once, and against the text database here and on every textdb.changed (S6)."""
        self.textdb = textdb
        self._owner_words = owner_words
        self._unsub = events.subscribe("textdb.changed", self._on_textdb)
        self.check_labels()

    def close(self) -> None:
        self._unsub()

    def _words(self) -> list[re.Pattern]:
        try:
            return owner_patterns(list(self._owner_words() or []))
        except Exception:
            return []

    def _on_textdb(self, topic: str, data: dict) -> None:
        if getattr(self.textdb, "closed", False):       # DataPiler is stopping: nothing to re-check
            self.close()
            return
        self.check_labels()

    def check_labels(self) -> list[int]:
        """S6: the indices of LABELS found in the text database, or failing check 4's rules; each is logged (the
        label is DataPiler's own word) so it can be renamed."""
        words = self._words()
        found: list[int] = []
        for i, label in enumerate(LABELS):
            if owner_fault(label, "labels", words):
                _log.warn("the label %s fails check 4 (a path sign, an owner's word or an address) - rename it",
                          own(label))
                found.append(i)
                continue
            try:
                hit = self.textdb.text_hit(label)
            except Exception as e:
                _log.error("the labels could not be checked against the text database: %s", logbook.why(e))
                hit = False
            if hit:
                _log.warn("the label %s is a text in the text database - check 3 skips it (S6), but it should be "
                          "renamed", own(label))
                found.append(i)
        return found

    def build(self, *, job_id: str, job_sha256: str, provenance: dict, tables: list[dict],
              notes: Sequence[str]) -> bytes:
        """The share file's bytes, in the order and layout of build plan §4.10: keys in order, each row on one line.
        tables: [{"name": ..., "columns": [{"name", "type"} or (name, type), ...], "rows": [[...], ...]}]."""
        def j(v: object) -> str:
            return json.dumps(v, ensure_ascii=True, allow_nan=True, separators=(", ", ": "))

        prov = {k: provenance.get(k) for k in PROVENANCE_KEYS}
        lines = ["{",
                 '  "format": %s,' % j(SHARE_FORMAT),
                 '  "job": %s,' % j({"id": job_id, "sha256": job_sha256}),
                 '  "provenance": %s,' % j(prov),
                 '  "tables": [']
        for ti, t in enumerate(tables):
            cols = []
            for c in t["columns"]:
                if isinstance(c, dict):
                    cols.append({"name": c["name"], "type": c["type"]})
                else:
                    cols.append({"name": c[0], "type": c[1]})
            lines.append('    {"name": %s, "columns": %s,' % (j(t["name"]), j(cols)))
            rows = list(t["rows"])
            end = "," if ti < len(tables) - 1 else ""
            if rows:
                lines.append('     "rows": [')
                lines.append(",\n".join("      " + j(list(r)) for r in rows))
                lines.append("     ]}" + end)
            else:
                lines.append('     "rows": []}' + end)
        lines.append("  ],")
        lines.append('  "notes": %s' % j(list(notes)))
        lines.append("}")
        return ("\n".join(lines) + "\n").encode("ascii")

    def check(self, data: bytes, *, declared: Mapping[str, Sequence[str]],
              coverage: Mapping[str, object] | None = None) -> list[CheckResult]:
        """All six checks; never raises. declared: {table: [column, ...]} as the job's write_share names them.
        coverage: {table: None or (row-id column or None, rows of the game table, the game table's name)}, from the
        runner or from `counts_for`; without it check 6 fails (DP8: a table's coverage is never guessed)."""
        results: dict[int, tuple[bool, str | None]] = {}
        try:
            results = self._run(data, declared, coverage)
        except Exception as e:
            _log.error("the guard could not finish its checks: %s", logbook.why(e))
            for n in CHECKS:
                results.setdefault(n, (False, "(file)"))
        return [CheckResult(n, NAMES[n], results[n][0], results[n][1]) for n in CHECKS]

    def _run(self, data: bytes, declared: Mapping[str, Sequence[str]],
             coverage: Mapping[str, object] | None) -> dict[int, tuple[bool, str | None]]:
        out: dict[int, tuple[bool, str | None]] = {}
        raw = bytes(data) if isinstance(data, (bytes, bytearray)) else b""
        try:
            doc = _parse(raw)
            parsed = True
        except (ValueError, RecursionError):
            doc, parsed = None, False
        if not parsed:
            out[1] = (False, "(file)")
            out[2] = out[3] = out[4] = out[6] = (False, "(file)")
        else:
            where = _check_shape(doc, dict(declared))
            out[1] = (where is None, where)
            where = _check_values(doc)
            out[2] = (where is None, where)
            out[3] = (True, None)
            out[4] = (True, None)
            words = self._words()
            fixed = fixed_words()
            for place, s, is_key in _strings(doc):
                # Check 3 reads values only: the format's own keys come from the format (check 1 fixes them); a key
                # of anything else is checked, though check 1 refuses the file already (P12, S20).
                skip = (s in FORMAT_KEYS) if is_key else (s in fixed)
                if out[3][0] and not skip:
                    if self.textdb.text_hit(s):
                        out[3] = (False, place)
                if out[4][0] and owner_fault(s, place, words):
                    out[4] = (False, place)
                if not out[3][0] and not out[4][0]:
                    break
        if len(raw) > MAX_BYTES:
            out[5] = (False, "(file)")
        else:
            _, where = _count_values(doc) if parsed else (0, None)
            out[5] = (where is None, where)
        if parsed:
            where = _check_coverage(doc, coverage)
            out[6] = (where is None, where)
        return out

    def write(self, share_dir: Path, name: str, data: bytes, *, declared: Mapping[str, Sequence[str]],
              coverage: Mapping[str, object] | None) -> ShareWritten:
        """Check, then write atomically only if all six pass. Raises GuardFailed naming the first failing check;
        nothing is written. Logs (source guard) and emits share.written or guard.failed. ValueError for a name
        that is not one DataPiler writes."""
        if not paths.name_ok(name):
            raise ValueError("not a name DataPiler writes")
        file_name = own(name + ".json")
        try:
            empty = self.textdb.entries() == 0
        except Exception:
            empty = True
        if empty:
            _log.warn("the text database is empty - check 3 had no text to compare (import the text exports first)")
        results = self.check(data, declared=declared, coverage=coverage)
        failed = next((r for r in results if not r.ok), None)
        if failed is not None:
            _log.error("%s not written: check %s at %s (%s)", file_name, failed.check, own(failed.where or "-"),
                       own(WORDS[failed.check]))
            events.emit("guard.failed", name=file_name, check=failed.check)
            raise GuardFailed(failed.check, failed.where)
        share_dir = Path(share_dir)
        share_dir.mkdir(parents=True, exist_ok=True)
        fileio.write_atomic(share_dir / file_name, bytes(data))
        sha = fileio.sha256_bytes(bytes(data))
        _log.info("%s written (%s bytes), checks 1-6 passed", file_name, logbook.n(len(data)))
        events.emit("share.written", name=file_name, size=len(data))
        return ShareWritten(str.__str__(file_name), len(data), sha)


# ------------------------------------------------------------------------------------------------ the row counts

_counts_lock = threading.Lock()


def _spec_ok(spec: object) -> bool:
    """One table's row counts as check 6 takes them: None, or (column or None, of, source), source a game table's
    name (a param's, or `placements`)."""
    if spec is None:
        return True
    if not isinstance(spec, (list, tuple)) or len(spec) != 3:
        return False
    column, of, source = spec
    return (column is None or (isinstance(column, str) and fields.FIELD_RX.fullmatch(column) is not None)) and \
        isinstance(of, int) and not isinstance(of, bool) and of >= 0 and \
        isinstance(source, str) and fields.FIELD_RX.fullmatch(source) is not None


def _read_counts(path: Path) -> dict:
    try:
        raw = fileio.read_limited(Path(path), 8 * 1024 * 1024)
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, fileio.TooLarge):
        return {}
    if not isinstance(doc, dict) or doc.get("format") != COUNTS_FORMAT or not isinstance(doc.get("files"), dict):
        return {}
    return doc["files"]


def record_counts(path: Path, file_name: str, sha256: str, coverage: Mapping[str, object]) -> None:
    """Keep a written share file's row counts (check 6's input) in the workspace, by the file's name and sha256, so
    Outputs can run check 6 again later. Local only: the counts are numbers of the owner's game tables, never in a
    share file. Atomic. Raises OSError or ValueError."""
    if not HEX64_RX.fullmatch(sha256) or not isinstance(file_name, str) or \
            not paths.name_ok(file_name[:-5] if file_name.endswith(".json") else ""):
        raise ValueError("not a share file DataPiler wrote")
    tables: dict[str, object] = {}
    for t, spec in coverage.items():
        if not isinstance(t, str) or not TABLE_RX.fullmatch(t) or not _spec_ok(spec):
            raise ValueError("not row counts DataPiler keeps")
        tables[t] = None if spec is None else \
            {"column": spec[0], "of": spec[1], "source": spec[2]}  # type: ignore[index]
    with _counts_lock:
        files = _read_counts(path)
        files.pop(file_name, None)
        files[file_name] = {"sha256": sha256, "tables": tables}
        while len(files) > COUNTS_MAX_FILES:
            files.pop(next(iter(files)))
        doc = {"format": COUNTS_FORMAT, "files": files}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fileio.write_atomic(Path(path), (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("ascii"))


def counts_for(path: Path, file_name: str, sha256: str) -> dict[str, object] | None:
    """The row counts kept for that share file at that sha256, as `check` takes them; None when there are none (a
    file DataPiler did not write, or one changed since), so check 6 fails. Never raises."""
    try:
        with _counts_lock:
            entry = _read_counts(path).get(file_name)
        if not isinstance(entry, dict) or entry.get("sha256") != sha256 or not isinstance(entry.get("tables"), dict):
            return None
        out: dict[str, object] = {}
        for t, v in entry["tables"].items():
            if v is None:
                out[t] = None
            elif isinstance(v, dict) and set(v) == {"column", "of", "source"} and \
                    _spec_ok((v["column"], v["of"], v["source"])):
                out[t] = (v["column"], v["of"], v["source"])
            else:
                return None
        return out
    except Exception:
        return None
