"""The `datapiler-job/1` format: the check on arrival and the preview (design 0001 §6, build plan §4.6).

A job is data, never code. Nothing in it is evaluated, used as a template or run: each operation comes from a closed
set, each argument is of its declared type and range, and every name it writes is a name, never a path. The check
finds every refusal at once, each naming the place and the rule in DataPiler's words. A refusal quotes the job's own
value only when it looks like an identifier (`QUOTE_RX`); otherwise it names the place alone.

`_depth` follows LLM Jobrunner 1.2's `_depth`, with the limit 16 (build plan §7.2). `schema/datapiler-job-1.schema.json`
states the same format for job authors; `tests/test_schema.py` keeps the two in step."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Collection, Mapping

from . import VERSION, fields, fileio, guard, paths
from .link import MAP_RX

FORMAT = "datapiler-job/1"
MAX_BYTES = 256 * 1024
MAX_DEPTH = 16
MAX_OPS = 64
OPS = ("fetch_rows", "load_maps", "read_placements", "join_names", "filter", "count", "distinct",
       "write_local", "write_share")

ID_RX = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
BUILTIN_ID_RX = re.compile(r"extract-[a-z][a-z0-9_]{0,55}")     # Extract's own jobs: extract-<row id>
TABLE_RX = re.compile(r"[a-z][a-z0-9_]{0,31}")
FIELD_RX = fields.FIELD_RX
NAME_RX = paths.NAME_RX
NEEDS_RX = re.compile(r"\d+\.\d+(\.\d+)?")
QUOTE_RX = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
TEXTS = ("character_names", "place_names")
COMPARE = ("eq", "ne", "lt", "le", "gt", "ge")

# P5 (build plan §10): none of the seven allowed calls lists every map, so `load_maps` with "all" is refused in 0.1
# and maps are named by id. `read_placements` with "all" reads the maps loaded in Smithbox.
LOAD_ALL_MAPS = False

MAX_FIELDS = 32
MAX_IDS = 65_535
MAX_MAPS = 2_000
MAX_BY = 8
MAX_WHERE = 16
MAX_IN = 1_000
MAX_LOCAL_TABLES = 16
MAX_SHARE_TABLES = 32
MAX_COLUMNS = 64
INT32 = (-2 ** 31, 2 ** 31 - 1)
INT_LIMIT = 2 ** 63

# The keys of a job and of each operation: True when required. tests/test_schema.py checks the schema against these.
TOP_KEYS: dict[str, bool] = {"format": True, "id": True, "title": True, "ops": True, "needs": False}
ARGS: dict[str, dict[str, bool]] = {
    "fetch_rows": {"as": True, "param": True, "fields": True, "ids": False},
    "load_maps": {"maps": True},
    "read_placements": {"as": True, "maps": True},
    "join_names": {"as": True, "rows": True, "key": True, "text": True},
    "filter": {"as": True, "rows": True, "where": True},
    "count": {"as": True, "rows": True, "by": False, "where": False},
    "distinct": {"as": True, "rows": True, "by": True},
    "write_local": {"name": True, "tables": True, "columns": False},
    "write_share": {"name": True, "tables": True, "columns": True, "notes": False},
}
LINK_OPS = ("fetch_rows", "load_maps", "read_placements")
READS = ("fetch_rows", "load_maps", "read_placements")
COMPUTES = ("join_names", "filter", "count", "distinct")
WRITES = ("write_local", "write_share")

# What read_placements and join_names make (build plan §4.6).
PLACEMENT_COLUMNS: tuple[tuple[str, str], ...] = (("map", "int"), ("entityId", "int"), ("npcParamId", "int"),
                                                   ("talkId", "int"), ("model", "int"))
TYPE_WORDS = {"int": "whole numbers", "number": "numbers", "bool": "flags (true or false)",
              "text_local": "local text"}
TEXT_WORDS = {"character_names": "the character names", "place_names": "the place names"}

_PARAM_LIST = ", ".join(fields.PARAMS)
_OP_LIST = ", ".join(OPS)
_LABEL_LIST = ", ".join(guard.LABELS)
_CONTROL_RX = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MAX_REFUSALS = 60


@dataclass(frozen=True)
class Refusal:
    where: str           # "ops[3].fields[1]", "id", "(file)"
    text: str            # "`teamName` is not a field DataPiler reads (ids and numbers only)"
    op: int | None

    def line(self) -> str:
        return "%s: %s" % (self.where, self.text)


class JobRefused(ValueError):
    """Every refusal found. `id` is the job's id when it is usable (of the pattern, not reserved, not taken), `title`
    its title when it keeps the rule; both for the card, never for a log line."""

    def __init__(self, refusals: list[Refusal], *, id: str | None = None, title: str | None = None,
                 format_ok: bool = False, sha256: str = ""):
        super().__init__("%d refusals" % len(refusals))
        self.refusals = refusals
        self.id = id
        self.title = title
        self.format_ok = format_ok
        self.sha256 = sha256


@dataclass(frozen=True)
class Job:
    id: str
    title: str
    sha256: str
    ops: tuple[dict, ...]
    needs: str | None
    uses_link: bool               # any fetch_rows, load_maps or read_placements
    maps: int | None              # how many maps load_maps names; None for "all"
    share_name: str | None


# ------------------------------------------------------------------------------------------------ helpers

def _q(v: object) -> str | None:
    return v if isinstance(v, str) and QUOTE_RX.fullmatch(v) else None


def _named(v: object, quoted: str, plain: str) -> str:
    """"`value` <quoted>" when the value may be quoted, else <plain>, which names no value."""
    q = _q(v)
    return "`%s` %s" % (q, quoted) if q is not None else plain


def _is_int(v: object, lo: int = -INT_LIMIT + 1, hi: int = INT_LIMIT - 1) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _is_number(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return abs(v) < INT_LIMIT
    return isinstance(v, float) and math.isfinite(v) and abs(v) < INT_LIMIT


def _plural(k: int, one: str, many: str) -> str:
    return "%s %s" % ("{:,}".format(k), one if k == 1 else many)


def _and(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def version_tuple(v: str) -> tuple[int, ...]:
    t = tuple(int(x) for x in v.split("."))
    return t + (0,) * (3 - len(t))


class _Obj(dict):
    """A JSON object that remembers keys given twice (the later value wins in json; here it is refused)."""

    dups: list


def _pairs(pairs: list) -> _Obj:
    o = _Obj()
    o.dups = []
    for k, v in pairs:
        if k in o:
            o.dups.append(k)
        o[k] = v
    return o


def _no_constant(name: str) -> object:
    raise ValueError("not JSON")


def parse(raw: bytes) -> object:
    """JSON with no NaN or infinity literals; objects as _Obj. Raises ValueError, RecursionError."""
    text = raw.decode("utf-8-sig")
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=_no_constant)


def _depth(o: object) -> int:
    stack, deepest = [(o, 1)], 0
    while stack:
        x, d = stack.pop()
        deepest = max(deepest, d)
        if deepest > MAX_DEPTH:
            return deepest
        if isinstance(x, dict):
            stack.extend((v, d + 1) for v in x.values())
        elif isinstance(x, list):
            stack.extend((v, d + 1) for v in x)
    return deepest


def _plain(o: object) -> object:
    """A plain copy: dicts and lists, no _Obj."""
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_plain(v) for v in o]
    return o


def _dups(o: object) -> list:
    return list(getattr(o, "dups", None) or [])


# ------------------------------------------------------------------------------------------------ the check

class _Checker:
    def __init__(self, *, known_ids: Collection[str], share_names: Mapping[str, str], builtin: bool):
        self.known_ids = known_ids
        self.share_names = share_names
        self.builtin = builtin
        self.refusals: list[Refusal] = []
        self.more = 0
        self.tables: dict[str, list[tuple[str, str]] | None] = {}
        self.later: dict[str, int] = {}
        self.local_names: set[str] = set()
        self.share_at: int | None = None
        self.share_name: str | None = None
        self.job_id: str | None = None
        self.maps: set[str] = set()

    def add(self, where: str, text: str, op: int | None = None) -> None:
        if len(self.refusals) >= _MAX_REFUSALS:
            self.more += 1
            return
        self.refusals.append(Refusal(where, text, op))

    def finish(self) -> list[Refusal]:
        out = list(self.refusals)
        if self.more:
            out.append(Refusal("(file)", "and %s more refusals" % "{:,}".format(self.more), None))
        return out

    # ---- tables and columns

    def new_table(self, place: str, v: object, i: int) -> str | None:
        if not isinstance(v, str) or not TABLE_RX.fullmatch(v):
            self.add(place, _named(v, "is not a table name (a-z, 0-9 and _, up to 32 characters, starting with a "
                                      "letter)", "not a table name (a-z, 0-9 and _, up to 32 characters, starting "
                                                 "with a letter)"), i)
            return None
        if v in self.tables:
            self.add(place, "`%s` is the name of an earlier table - each `as` is used once" % v, i)
            return None
        return v

    def ref(self, place: str, v: object, i: int) -> tuple[str, list[tuple[str, str]] | None] | None:
        if not isinstance(v, str) or not TABLE_RX.fullmatch(v):
            self.add(place, _named(v, "is not a table name", "not a table name"), i)
            return None
        if v not in self.tables:
            later = self.later.get(v)
            if later == i:
                self.add(place, "`%s` is this operation's own table - an operation reads only the tables made "
                                "before it" % v, i)
            elif later is not None and later > i:
                self.add(place, "`%s` is made by a later operation (ops[%d]) - an operation reads only the tables "
                                "made before it" % (v, later), i)
            else:
                self.add(place, "`%s` is not a table an earlier operation made" % v, i)
            return None
        return v, self.tables[v]

    def column(self, place: str, v: object, table: str, cols: list[tuple[str, str]] | None, i: int,
               kinds: tuple[str, ...] | None = None, need: str = "") -> str | None:
        if not isinstance(v, str) or not FIELD_RX.fullmatch(v):
            self.add(place, _named(v, "is not a column of %s" % table, "not a column of %s" % table), i)
            return None
        if cols is None:
            return v
        types = dict(cols)
        if v not in types:
            self.add(place, "`%s` is not a column of %s" % (v, table), i)
            return None
        if kinds is not None and types[v] not in kinds:
            self.add(place, "`%s` holds %s - %s" % (v, TYPE_WORDS[types[v]], need), i)
            return None
        return v

    def column_list(self, place: str, v: object, table: str, cols, i: int, lo: int, hi: int,
                    kinds: tuple[str, ...] | None = None, need: str = "", what: str = "column names"
                    ) -> list[str] | None:
        if not isinstance(v, list) or not lo <= len(v) <= hi:
            self.add(place, "must be a list of %d to %d %s" % (lo, hi, what), i)
            return None
        out: list[str] = []
        ok = True
        for j, c in enumerate(v):
            p = "%s[%d]" % (place, j)
            name = self.column(p, c, table, cols, i, kinds, need)
            if name is None:
                ok = False
            elif name in out:
                self.add(p, "`%s` is named twice" % name, i)
                ok = False
            else:
                out.append(name)
        return out if ok else None

    def table_list(self, place: str, v: object, i: int, hi: int) -> list[tuple[str, list | None]] | None:
        if not isinstance(v, list) or not 1 <= len(v) <= hi:
            self.add(place, "must be a list of 1 to %d table names" % hi, i)
            return None
        out: list[tuple[str, list | None]] = []
        ok = True
        for j, t in enumerate(v):
            p = "%s[%d]" % (place, j)
            r = self.ref(p, t, i)
            if r is None:
                ok = False
            elif any(r[0] == x[0] for x in out):
                self.add(p, "`%s` is named twice" % r[0], i)
                ok = False
            else:
                out.append(r)
        return out if ok else None

    # ---- where

    def where(self, place: str, w: object, table: str, cols, i: int) -> None:
        if not isinstance(w, dict) or not 1 <= len(w) <= MAX_WHERE:
            self.add(place, "must be an object of 1 to %d conditions" % MAX_WHERE, i)
            return
        if _dups(w):
            self.add(place, "a key is given twice", i)
        types = dict(cols) if cols is not None else None
        for col, cond in w.items():
            if not isinstance(col, str) or not FIELD_RX.fullmatch(col) or (types is not None and col not in types):
                self.add(place, _named(col, "is not a column of %s" % table,
                                       "a key that is not a column of %s" % table), i)
                continue
            typ = types[col] if types is not None else None
            cp = "%s.%s" % (place, col)
            if typ == "text_local":
                self.add(cp, "`%s` holds local text - a condition takes whole numbers, numbers or flags" % col, i)
                continue
            if isinstance(cond, dict):
                if not cond:
                    self.add(cp, "an empty condition", i)
                    continue
                if _dups(cond):
                    self.add(cp, "a key is given twice", i)
                for k, v in cond.items():
                    if k in COMPARE:
                        self.value("%s.%s" % (cp, k), col, typ, v, k, i)
                    elif k == "in":
                        if typ == "bool":
                            self.add("%s.in" % cp, "`%s` is a flag - compare it with eq or ne" % col, i)
                        elif not isinstance(v, list) or not 1 <= len(v) <= MAX_IN or \
                                not all(_is_number(x) for x in v):
                            self.add("%s.in" % cp, "must be a list of 1 to 1,000 numbers", i)
                    else:
                        self.add(cp, _named(k, "is not a comparison (eq, ne, lt, le, gt, ge, in)",
                                            "a key that is not a comparison (eq, ne, lt, le, gt, ge, in)"), i)
            else:
                self.value(cp, col, typ, cond, "eq", i)

    def value(self, place: str, col: str, typ: str | None, v: object, cmp: str, i: int) -> None:
        if typ == "bool" or (typ is None and isinstance(v, bool)):
            if cmp not in ("eq", "ne"):
                self.add(place, "`%s` is a flag - compare it with eq or ne" % col, i)
            elif not isinstance(v, bool):
                self.add(place, "`%s` is a flag - compare it with true or false" % col, i)
            return
        if not _is_number(v):
            self.add(place, "`%s` holds numbers - compare it with a number" % col, i)

    # ---- maps

    def map_list(self, place: str, v: object, i: int, *, all_ok: bool) -> list[str] | None | bool:
        """The maps named; True for "all"; None when refused."""
        if v == "all":
            if all_ok:
                return True
            self.add(place, "\"all\" cannot be loaded in 0.1: none of the allowed calls lists every map - name the "
                            "maps by id", i)
            return None
        if not isinstance(v, list) or not 1 <= len(v) <= MAX_MAPS:
            self.add(place, "must be a list of 1 to 2,000 map ids%s" % (", or \"all\"" if all_ok else ""), i)
            return None
        out: list[str] = []
        for j, m in enumerate(v):
            p = "%s[%d]" % (place, j)
            if not isinstance(m, str) or not MAP_RX.fullmatch(m):
                self.add(p, _named(m, "is not a map id of the form m00_00_00_00",
                                   "not a map id of the form m00_00_00_00"), i)
                return None
            if m in out:
                self.add(p, "`%s` is named twice" % m, i)
                return None
            out.append(m)
        return out

    # ---- one operation

    def op(self, i: int, o: object) -> None:
        place = "ops[%d]" % i
        if not isinstance(o, dict):
            self.add(place, "an operation is an object with an `op`", i)
            return
        if _dups(o):
            self.add(place, "a key is given twice", i)
        if "op" not in o:
            self.add(place, "has no `op`", i)
            return
        name = o["op"]
        if not isinstance(name, str) or name not in OPS:
            self.add(place + ".op", _named(name, "is not an operation DataPiler has (%s)" % _OP_LIST,
                                           "not an operation DataPiler has (%s)" % _OP_LIST), i)
            return
        args = ARGS[name]
        for k in o:
            if k != "op" and k not in args:
                self.add(place, _named(k, "is not an argument of %s" % name,
                                       "a key that is not an argument of %s" % name), i)
        missing = [a for a, req in args.items() if req and a not in o]
        for a in missing:
            self.add("%s.%s" % (place, a), "missing - %s needs it" % name, i)
        _CHECKS[name](self, place, i, o)

    def op_fetch_rows(self, place: str, i: int, o: dict) -> None:
        as_ = self.new_table(place + ".as", o.get("as"), i) if "as" in o else None
        param = o.get("param")
        known = param if isinstance(param, str) and param in fields.PARAMS else None
        if "param" in o and known is None:
            self.add(place + ".param", _named(param, "is not a param DataPiler reads (%s)" % _PARAM_LIST,
                                              "not a param DataPiler reads (%s)" % _PARAM_LIST), i)
        cols: list[tuple[str, str]] | None = None
        fl = o.get("fields")
        if "fields" in o:
            if not isinstance(fl, list) or not 1 <= len(fl) <= MAX_FIELDS:
                self.add(place + ".fields", "must be a list of 1 to %d field names" % MAX_FIELDS, i)
            else:
                ok = True
                seen: list[str] = []
                for j, f in enumerate(fl):
                    p = "%s.fields[%d]" % (place, j)
                    if not isinstance(f, str) or not FIELD_RX.fullmatch(f) or \
                            (known is not None and f not in fields.PARAMS[known]):
                        self.add(p, _named(f, "is not a field DataPiler reads (ids and numbers only)",
                                           "not a field DataPiler reads (ids and numbers only)"), i)
                        ok = False
                    elif f in seen:
                        self.add(p, "`%s` is named twice" % f, i)
                        ok = False
                    else:
                        seen.append(f)
                if ok and known is not None:
                    cols = [("id", "int")] + [(f, fields.PARAMS[known][f]) for f in seen if f != "id"]
        if "ids" in o:
            self.ids(place + ".ids", o["ids"], i)
        if as_ is not None:
            self.tables[as_] = cols

    def ids(self, place: str, v: object, i: int) -> None:
        if isinstance(v, list):
            if not 1 <= len(v) <= MAX_IDS:
                self.add(place, "must be a list of 1 to 65,535 row ids, or {\"from\": first, \"to\": last}", i)
                return
            for j, x in enumerate(v):
                if not _is_int(x, *INT32):
                    self.add("%s[%d]" % (place, j), "not a row id (a whole number)", i)
                    return
            return
        if isinstance(v, dict):
            if _dups(v):
                self.add(place, "a key is given twice", i)
            if set(v) != {"from", "to"}:
                self.add(place, "a range is {\"from\": first, \"to\": last}, with no other key", i)
                return
            ok = True
            for k in ("from", "to"):
                if not _is_int(v[k], *INT32):
                    self.add("%s.%s" % (place, k), "not a row id (a whole number)", i)
                    ok = False
            if ok and v["from"] > v["to"]:
                self.add(place, "`from` is above `to`", i)
            return
        self.add(place, "must be a list of 1 to 65,535 row ids, or {\"from\": first, \"to\": last}", i)

    def op_load_maps(self, place: str, i: int, o: dict) -> None:
        if "maps" in o:
            maps = self.map_list(place + ".maps", o["maps"], i, all_ok=LOAD_ALL_MAPS)
            if isinstance(maps, list):
                self.maps.update(maps)

    def op_read_placements(self, place: str, i: int, o: dict) -> None:
        as_ = self.new_table(place + ".as", o.get("as"), i) if "as" in o else None
        if "maps" in o:
            self.map_list(place + ".maps", o["maps"], i, all_ok=True)
        if as_ is not None:
            self.tables[as_] = list(PLACEMENT_COLUMNS)

    def op_join_names(self, place: str, i: int, o: dict) -> None:
        as_ = self.new_table(place + ".as", o.get("as"), i) if "as" in o else None
        r = self.ref(place + ".rows", o["rows"], i) if "rows" in o else None
        cols = r[1] if r is not None else None
        ok = r is not None and cols is not None
        if r is not None and cols is not None and any(c in ("named", "name") for c, _ in cols):
            self.add(place + ".rows", "`%s` has a `named` or `name` column already - a table is joined once" % r[0],
                     i)
            ok = False
        if "key" in o:
            table = r[0] if r is not None else "its table"
            if self.column(place + ".key", o["key"], table, cols, i, ("int",),
                           "the key is a column of whole numbers") is None:
                ok = False
        t = o.get("text")
        if "text" in o and t not in TEXTS:
            self.add(place + ".text", _named(t, "is not a text set DataPiler has (%s)" % ", ".join(TEXTS),
                                             "not a text set DataPiler has (%s)" % ", ".join(TEXTS)), i)
        if as_ is not None:
            self.tables[as_] = (list(cols) + [("named", "bool"), ("name", "text_local")]) if ok and cols else None

    def op_filter(self, place: str, i: int, o: dict) -> None:
        as_ = self.new_table(place + ".as", o.get("as"), i) if "as" in o else None
        r = self.ref(place + ".rows", o["rows"], i) if "rows" in o else None
        if "where" in o:
            self.where(place + ".where", o["where"], r[0] if r else "its table", r[1] if r else None, i)
        if as_ is not None:
            self.tables[as_] = list(r[1]) if r is not None and r[1] is not None else None

    def _by(self, place: str, o: dict, r, i: int, lo: int) -> list[str] | None:
        if "by" not in o:
            return [] if lo == 0 else None
        table, cols = (r[0], r[1]) if r is not None else ("its table", None)
        return self.column_list(place + ".by", o["by"], table, cols, i, lo, MAX_BY, ("int", "bool"),
                                "`by` takes columns of whole numbers or flags")

    def op_count(self, place: str, i: int, o: dict) -> None:
        as_ = self.new_table(place + ".as", o.get("as"), i) if "as" in o else None
        r = self.ref(place + ".rows", o["rows"], i) if "rows" in o else None
        by = self._by(place, o, r, i, 0)
        if by is not None and "count" in by:
            self.add("%s.by[%d]" % (place, by.index("count")), "`count` is the column count makes - it cannot "
                                                               "be a `by` column too", i)
            by = None
        if "where" in o:
            self.where(place + ".where", o["where"], r[0] if r else "its table", r[1] if r else None, i)
        cols = None
        if r is not None and r[1] is not None and by is not None:
            types = dict(r[1])
            cols = [(b, types[b]) for b in by] + [("count", "int")]
        if as_ is not None:
            self.tables[as_] = cols

    def op_distinct(self, place: str, i: int, o: dict) -> None:
        as_ = self.new_table(place + ".as", o.get("as"), i) if "as" in o else None
        r = self.ref(place + ".rows", o["rows"], i) if "rows" in o else None
        by = self._by(place, o, r, i, 1)
        cols = None
        if r is not None and r[1] is not None and by is not None:
            types = dict(r[1])
            cols = [(b, types[b]) for b in by]
        if as_ is not None:
            self.tables[as_] = cols

    def file_name(self, place: str, v: object, i: int) -> str | None:
        if not isinstance(v, str) or not NAME_RX.fullmatch(v):
            self.add(place, _named(v, "is not a file name (a-z, 0-9, _ and -, up to 64 characters) - never a path",
                                   "not a file name (a-z, 0-9, _ and -, up to 64 characters) - never a path"), i)
            return None
        if paths.reserved(v):
            self.add(place, "`%s` %s - choose another name" % (v, paths.RESERVED_TEXT), i)
            return None
        return v

    def columns_map(self, place: str, v: object, tables: list[tuple[str, list | None]] | None, i: int, *,
                    every: bool, share: bool) -> None:
        if not isinstance(v, dict):
            self.add(place, "must be an object: {table: [column, ...]}", i)
            return
        if _dups(v):
            self.add(place, "a key is given twice", i)
        if tables is None:
            return
        named = dict(tables)
        for t in v:
            if t not in named:
                self.add(place, _named(t, "is not one of this operation's tables",
                                       "a key that is not one of this operation's tables"), i)
        if every:
            for t, _ in tables:
                if t not in v:
                    self.add(place, "`%s` has no list of columns - write_share names the columns of every table" % t,
                             i)
        for t, cols in tables:
            if t not in v:
                continue
            p = "%s.%s" % (place, t)
            chosen = self.column_list(p, v[t], t, cols, i, 1, MAX_COLUMNS)
            if share and chosen is not None and cols is not None:
                types = dict(cols)
                for j, c in enumerate(chosen):
                    if types.get(c) == "text_local":
                        self.add("%s[%d]" % (p, j), "`%s` holds local text (the names) and never goes into a share "
                                                    "file" % c, i)

    def op_write_local(self, place: str, i: int, o: dict) -> None:
        name = self.file_name(place + ".name", o["name"], i) if "name" in o else None
        if name is not None:
            if name in self.local_names:
                self.add(place + ".name", "`%s` is written twice by this job" % name, i)
            self.local_names.add(name)
        tables = self.table_list(place + ".tables", o["tables"], i, MAX_LOCAL_TABLES) if "tables" in o else None
        if "columns" in o:
            self.columns_map(place + ".columns", o["columns"], tables, i, every=False, share=False)

    def op_write_share(self, place: str, i: int, o: dict) -> None:
        if self.share_at is not None:
            self.add(place, "a job writes one share file at most - ops[%d] writes one already" % self.share_at, i)
        else:
            self.share_at = i
        name = self.file_name(place + ".name", o["name"], i) if "name" in o else None
        if name is not None:
            owner = self.share_names.get(name)
            if owner is not None and owner != self.job_id:
                self.add(place + ".name", "`%s` is the share file of the job `%s` already" % (name, owner)
                         if ID_RX.fullmatch(str(owner)) or BUILTIN_ID_RX.fullmatch(str(owner))
                         else "`%s` is the share file of another job already" % name, i)
            elif self.share_at == i:
                self.share_name = name
        tables = self.table_list(place + ".tables", o["tables"], i, MAX_SHARE_TABLES) if "tables" in o else None
        if "columns" in o:
            self.columns_map(place + ".columns", o["columns"], tables, i, every=True, share=True)
        if "notes" in o:
            notes = o["notes"]
            if not isinstance(notes, list) or len(notes) > len(guard.LABELS):
                self.add(place + ".notes", "must be a list of DataPiler's labels (%s)" % _LABEL_LIST, i)
            else:
                seen: set[str] = set()
                for j, x in enumerate(notes):
                    p = "%s.notes[%d]" % (place, j)
                    if not isinstance(x, str) or x not in guard.LABELS:
                        self.add(p, _named(x, "is not a label DataPiler has (%s)" % _LABEL_LIST,
                                           "not a label DataPiler has (%s)" % _LABEL_LIST), i)
                    elif x in seen:
                        self.add(p, "`%s` is named twice" % x, i)
                    else:
                        seen.add(x)


# The closed set: each operation's own check (a fixed table, never a name looked up from the job).
_CHECKS = {
    "fetch_rows": _Checker.op_fetch_rows,
    "load_maps": _Checker.op_load_maps,
    "read_placements": _Checker.op_read_placements,
    "join_names": _Checker.op_join_names,
    "filter": _Checker.op_filter,
    "count": _Checker.op_count,
    "distinct": _Checker.op_distinct,
    "write_local": _Checker.op_write_local,
    "write_share": _Checker.op_write_share,
}


def _check_id(c: _Checker, v: object, builtin: bool) -> str | None:
    """The id when it is usable; None after a refusal."""
    if builtin:
        if not isinstance(v, str) or not BUILTIN_ID_RX.fullmatch(v):
            c.add("id", "not an id of Extract's own: extract-<row id>")
            return None
    else:
        if not isinstance(v, str) or not ID_RX.fullmatch(v):
            c.add("id", _named(v, "is not an id: a-z, 0-9 and -, 3 to 64 characters, starting with a letter or a "
                                  "digit", "not an id: a-z, 0-9 and -, 3 to 64 characters, starting with a letter "
                                           "or a digit"))
            return None
        if v.startswith("extract-") or v == "extract":
            c.add("id", "`%s`: ids starting `extract` are kept for Extract's own jobs" % v)
            return None
        if v.startswith("refused-"):
            c.add("id", "`%s`: ids starting `refused-` are kept for refused files" % v)
            return None
        if paths.reserved(v):                   # it names jobs/<id>/ and logs/jobs/<id>.log
            c.add("id", "`%s` %s - choose another id" % (v, paths.RESERVED_TEXT))
            return None
    if v in c.known_ids:
        c.add("id", "`%s` is the id of another job here - give this one its own id" % v)
        return None
    return v


def _title_ok(v: object) -> bool:
    return isinstance(v, str) and 1 <= len(v) <= 120 and not _CONTROL_RX.search(v)


def check(raw: bytes, *, known_ids: Collection[str], share_names: Mapping[str, str],
          builtin: bool = False) -> Job:
    """The checks of design §6 at once: a JSON object of at most MAX_BYTES, nesting at most MAX_DEPTH, the
    format, every key known, every op from OPS with its arguments of their types and ranges, names only (never a
    path), the id unique. builtin=True allows the "extract-" prefix (catalogue rows only). Raises JobRefused with
    every refusal found, each naming the field and the rule. A refusal quotes the job's own value only when it
    matches [A-Za-z0-9_.:-]{1,64}; otherwise it names the place alone."""
    c = _Checker(known_ids=known_ids, share_names=share_names, builtin=builtin)
    sha = fileio.sha256_bytes(raw) if isinstance(raw, (bytes, bytearray)) else ""

    def refuse(**kw) -> JobRefused:
        return JobRefused(c.finish(), sha256=sha, **kw)

    if not isinstance(raw, (bytes, bytearray)) or not raw:
        c.add("(file)", "the file is empty")
        raise refuse()
    if len(raw) > MAX_BYTES:
        c.add("(file)", "the file is over 256 KB")
        raise refuse()
    try:
        doc = parse(bytes(raw))
    except UnicodeDecodeError:
        c.add("(file)", "the file is not UTF-8 text")
        raise refuse() from None
    except RecursionError:
        c.add("(file)", "the file nests deeper than %d levels" % MAX_DEPTH)
        raise refuse() from None
    except ValueError:
        c.add("(file)", "the file is not JSON")
        raise refuse() from None
    if not isinstance(doc, dict):
        c.add("(file)", "the file is not a JSON object")
        raise refuse()
    if _depth(doc) > MAX_DEPTH:
        c.add("(file)", "the file nests deeper than %d levels" % MAX_DEPTH)
        raise refuse()

    title = doc.get("title") if _title_ok(doc.get("title")) else None
    if _dups(doc):
        c.add("(top level)", "a key is given twice")
    for k in doc:
        if k not in TOP_KEYS:
            c.add("(top level)", _named(k, "is not a key of a job (format, id, title, ops, needs)",
                                        "a key that is not a key of a job (format, id, title, ops, needs)"))
    if "format" not in doc:
        c.add("format", "missing - a job says \"format\": \"datapiler-job/1\"")
    elif doc["format"] != FORMAT:
        c.add("format", _named(doc["format"], "is not a format DataPiler reads (it reads datapiler-job/1)",
                               "not a format DataPiler reads (it reads datapiler-job/1)"))
    format_ok = doc.get("format") == FORMAT

    job_id = None
    if "id" not in doc:
        c.add("id", "missing - a job has an id: a-z, 0-9 and -, 3 to 64 characters")
    else:
        job_id = _check_id(c, doc["id"], builtin)
    c.job_id = job_id

    if "title" not in doc:
        c.add("title", "missing - a job has a title of 1 to 120 characters")
    elif title is None:
        c.add("title", "must be 1 to 120 characters, with no control characters")

    needs = doc.get("needs")
    if "needs" in doc:
        if not isinstance(needs, str) or not NEEDS_RX.fullmatch(needs):
            c.add("needs", "must be a version such as 0.1 or 0.1.0")
            needs = None
        elif version_tuple(needs) > version_tuple(VERSION):
            c.add("needs", "this job needs DataPiler %s or newer; this is %s" % (needs, VERSION))

    if not format_ok:
        raise refuse(id=job_id, title=title, format_ok=False)

    ops = doc.get("ops")
    if "ops" not in doc:
        c.add("ops", "missing - a job has a list of 1 to 64 operations")
        ops = None
    elif not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPS:
        c.add("ops", "must be a list of 1 to 64 operations")
        ops = None
    if ops is not None:
        for i, o in enumerate(ops):
            if isinstance(o, dict) and isinstance(o.get("as"), str) and o.get("as") not in c.later:
                c.later[o["as"]] = i
        for i, o in enumerate(ops):
            c.op(i, o)

    if c.refusals:
        raise refuse(id=job_id, title=title, format_ok=True)

    assert job_id is not None and title is not None and ops is not None
    plain_ops = tuple(_plain(o) for o in ops)
    return Job(id=job_id, title=title, sha256=sha, ops=plain_ops, needs=needs if "needs" in doc else None,
               uses_link=any(o["op"] in LINK_OPS for o in plain_ops), maps=len(c.maps), share_name=c.share_name)


def canonical_sha256(ops: object) -> str:
    """The sha256 of the ops' canonical JSON (sorted keys, no spaces): the built-in jobs' job.sha256."""
    text = json.dumps(ops, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return fileio.sha256_bytes(text.encode("ascii"))


# ------------------------------------------------------------------------------------------------ the preview

def _num(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return repr(v) if isinstance(v, float) else str(v)


_SIGNS = {"lt": "<", "le": "<=", "gt": ">", "ge": ">="}


def conditions(where: Mapping[str, object]) -> str:
    """"named is true", "teamType >= 6", "npcType in 3 values", joined with " and "."""
    parts: list[str] = []
    for col, cond in where.items():
        items = cond.items() if isinstance(cond, dict) else [("eq", cond)]
        for k, v in items:
            if k == "eq":
                parts.append("%s is %s" % (col, _num(v)))
            elif k == "ne":
                parts.append("%s is not %s" % (col, _num(v)))
            elif k == "in":
                parts.append("%s in %s" % (col, _plural(len(v) if isinstance(v, list) else 0, "value", "values")))
            else:
                parts.append("%s %s %s" % (col, _SIGNS.get(k, k), _num(v)))
    return " and ".join(parts)


def _line(o: dict) -> str:
    op = o["op"]
    if op == "fetch_rows":
        flds = ["id"] + [f for f in o["fields"] if f != "id"]
        s = "%s rows: %s" % (o["param"], ", ".join(flds))
        ids = o.get("ids")
        if isinstance(ids, dict):
            s += " - rows %d to %d" % (ids["from"], ids["to"])
        elif isinstance(ids, list):
            s += " - " + _plural(len(set(ids)), "row", "rows")
        return s
    if op == "load_maps":
        return "loads %s in Smithbox - its view changes, not its data" % _plural(len(o["maps"]), "map", "maps")
    if op == "read_placements":
        of = "the loaded maps" if o["maps"] == "all" else _plural(len(o["maps"]), "map", "maps")
        return "placed characters of %s: entity, row, dialogue and model ids" % of
    if op == "join_names":
        return "join %s with %s - local" % (o["rows"], TEXT_WORDS[o["text"]])
    if op == "filter":
        return "keeps the rows of %s where %s" % (o["rows"], conditions(o["where"]))
    if op == "count":
        s = "counts the rows of %s" % o["rows"]
        if o.get("by"):
            s += " per %s" % _and(list(o["by"]))
        if o.get("where"):
            s += ", where %s" % conditions(o["where"])
        return s
    if op == "distinct":
        return "distinct %s of %s" % (_and(list(o["by"])), o["rows"])
    if op == "write_local":
        return "workspace file `%s.json`: %s (local)" % (o["name"], _plural(len(o["tables"]), "table", "tables"))
    if op == "write_share":
        return "share file `%s.json`: %s" % (o["name"], _plural(len(o["tables"]), "table", "tables"))
    return op


def preview(job: Job) -> dict[str, list[str]]:
    """{"reads": [...], "computes": [...], "writes": [...]} in DataPiler's words (build plan §4.6)."""
    out: dict[str, list[str]] = {"reads": [], "computes": [], "writes": []}
    for o in job.ops:
        op = o["op"]
        key = "reads" if op in READS else "computes" if op in COMPUTES else "writes"
        out[key].append(_line(o))
    return out


def columns_of(job: Job) -> dict[str, list[tuple[str, str]]]:
    """Every table the job makes, with its columns and their types, in the order the ops make them."""
    tables: dict[str, list[tuple[str, str]]] = {}
    for o in job.ops:
        op = o["op"]
        if op == "fetch_rows":
            tables[o["as"]] = [("id", "int")] + [(f, fields.PARAMS[o["param"]][f]) for f in o["fields"] if f != "id"]
        elif op == "read_placements":
            tables[o["as"]] = list(PLACEMENT_COLUMNS)
        elif op == "join_names":
            tables[o["as"]] = tables[o["rows"]] + [("named", "bool"), ("name", "text_local")]
        elif op == "filter":
            tables[o["as"]] = list(tables[o["rows"]])
        elif op == "count":
            types = dict(tables[o["rows"]])
            tables[o["as"]] = [(b, types[b]) for b in o.get("by", [])] + [("count", "int")]
        elif op == "distinct":
            types = dict(tables[o["rows"]])
            tables[o["as"]] = [(b, types[b]) for b in o["by"]]
    return tables
