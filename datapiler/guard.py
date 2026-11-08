"""The share file's format and the guard's five checks (design 0001 §6, settled S5 and S6, build plan §4.10).

A share file's bytes are checked before they are written, and nothing is written unless all five checks pass:

1. **Shape**: the format's keys only, tables and columns exactly as the job declared them.
2. **Values**: every cell of its column's type (finite numbers allowed, S5); notes are labels; no other string.
3. **Text**: no string (keys and names included) is or holds a text of the local text database, nor sits inside one;
   values that are exactly one of `LABELS` are skipped (S6), and so is the format constant.
4. **The owner**: no path, drive letter, `~`, user or PC name, or IP address in any string.
5. **Size**: at most `MAX_BYTES` bytes and `MAX_VALUES` values.

A failure names the check and the place (`tables[1].rows[40][2]`), never the value. `_strings` follows LLM Jobrunner
1.2's `_strings`, walking keys and values with their places (build plan §7.2)."""

from __future__ import annotations

import json
import math
import re
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

NAMES = {1: "Shape", 2: "Values", 3: "Text", 4: "The owner", 5: "Size"}
WORDS = {1: "the share file's shape", 2: "a value that is not a number, a flag or a label",
         3: "a string the text database holds", 4: "a path, a name of the PC's or its user's, or an address",
         5: "over the size limits"}

TOP_KEYS = ("format", "job", "provenance", "tables", "notes")
JOB_KEYS = ("id", "sha256")
PROVENANCE_KEYS = ("game_version", "regulation_sha256", "expansion", "language", "smithbox_build", "datapiler", "date")
TABLE_KEYS = ("name", "columns", "rows")
COLUMN_KEYS = ("name", "type")
FORMAT_KEYS = frozenset(TOP_KEYS + JOB_KEYS + PROVENANCE_KEYS + TABLE_KEYS + COLUMN_KEYS)
COLUMN_TYPES = ("int", "number", "bool", "label")

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


def _word_rx(words: Sequence[str]) -> list[re.Pattern]:
    out = []
    for w in words:
        if isinstance(w, str) and w.strip():
            out.append(re.compile(r"(?<![^\W_])%s(?![^\W_])" % re.escape(w.strip().casefold())))
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
            return _word_rx(list(self._owner_words() or []))
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

    def check(self, data: bytes, *, declared: Mapping[str, Sequence[str]]) -> list[CheckResult]:
        """All five checks; never raises. declared: {table: [column, ...]} as the job's write_share names them."""
        results: dict[int, tuple[bool, str | None]] = {}
        try:
            results = self._run(data, declared)
        except Exception as e:
            _log.error("the guard could not finish its checks: %s", logbook.why(e))
            for n in range(1, 6):
                results.setdefault(n, (False, "(file)"))
        return [CheckResult(n, NAMES[n], results[n][0], results[n][1]) for n in range(1, 6)]

    def _run(self, data: bytes, declared: Mapping[str, Sequence[str]]) -> dict[int, tuple[bool, str | None]]:
        out: dict[int, tuple[bool, str | None]] = {}
        raw = bytes(data) if isinstance(data, (bytes, bytearray)) else b""
        try:
            doc = _parse(raw)
            parsed = True
        except (ValueError, RecursionError):
            doc, parsed = None, False
        if not parsed:
            out[1] = (False, "(file)")
            out[2] = out[3] = out[4] = (False, "(file)")
        else:
            where = _check_shape(doc, dict(declared))
            out[1] = (where is None, where)
            where = _check_values(doc)
            out[2] = (where is None, where)
            out[3] = (True, None)
            out[4] = (True, None)
            words = self._words()
            for place, s, is_key in _strings(doc):
                if out[3][0] and not (not is_key and (s in LABELS or s == SHARE_FORMAT)):
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
        return out

    def write(self, share_dir: Path, name: str, data: bytes, *,
              declared: Mapping[str, Sequence[str]]) -> ShareWritten:
        """Check, then write atomically only if all five pass. Raises GuardFailed naming the first failing check;
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
        results = self.check(data, declared=declared)
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
        _log.info("%s written (%s bytes), checks 1-5 passed", file_name, logbook.n(len(data)))
        events.emit("share.written", name=file_name, size=len(data))
        return ShareWritten(str.__str__(file_name), len(data), sha)
