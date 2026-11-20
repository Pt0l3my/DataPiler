"""EldenNet's derivation report, `derive.json`, as the guard checks it (DP36; EldenNet O89; settled S98).

The derivation's offline round R0 runs EldenNet's devkit tool on the game's executable (`devkit.py`) and shares its
report as it is: the same bytes the tool wrote and the tool's own lint passed, so that EldenNet's lint can check it
again where it arrives. Before it becomes a share file, DataPiler's guard checks it with its own copy of the report's
vocabulary (schema 1, as EldenNet's `derive_report.cpp` writes it): every key known and given once, `report` first and
`schema` second; each value of its key's type: a whole number of 0 or more, a flag, one of its key's fixed words, one
of the leads' labels, or a byte pattern of at most 64 bytes in canonical form; no other string, no fraction, no null.
So no path, name, text, param or code dump has a place to go. A pattern whose fixed bytes read as text (eight
printable ASCII characters in a row, or eight UTF-16 ones) is refused too: code does not read so, and text must not
travel inside a pattern.

`walk` gives check 1 (the shape) and check 2 (the values) and every string with its kind for checks 3 and 4; the guard
(`guard.py`) runs those and checks 5 and 6. Keys, words, labels and patterns are DataPiler's or the devkit's own
words, never read from the game: check 3 skips them, as it skips DataPiler's fixed words (S20), and checks any other
string, which checks 1 and 2 refuse already. A new schema of the report needs a new DataPiler."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

REPORT = "derive"
SCHEMA = 1
MAX_BYTES = 256 * 1024          # EldenNet's lint: a report of at most 256 KiB
MAX_PATTERNS = 64
MAX_PATTERN_BYTES = 64
MIN_FIXED = 4
MAX_ITEMS = 4096
MAX_DEPTH = 16
UINT_MAX = 2 ** 64 - 1
TEXT_RUN = 8                    # printable characters in a row that make a pattern's fixed bytes read as text

LABEL_RX = re.compile(r"[a-z][a-z0-9_]{0,47}")
PATTERN_RX = re.compile(r"(?:[0-9A-F]{2}|\?\?)(?: (?:[0-9A-F]{2}|\?\?)){0,63}")

# The value types of the report's keys.
U, B, O, AO, AU, LABEL, PATTERN = "uint", "bool", "object", "objects", "uints", "label", "pattern"

STATUS = ("derived", "ambiguous", "refused", "missing", "not_unique", "needs_slot", "depends")
REFUSAL = ("unreadable", "static_section", "static_alignment", "class_section", "getter_section",
           "getter_not_function", "no_path", "path_section", "path_text")
REGION = ("ww", "jp", "other", "none")
PRODUCT = ("matches", "differs", "absent", "not_given")
SECTION = (".text", ".rdata", ".data", ".pdata", ".xdata", ".rsrc", ".reloc", ".tls", ".idata", ".edata", ".bss",
           ".CRT", "_RDATA", ".00cfg", ".gfids", ".retplne", ".voltbl", ".didat", ".buildid", "other")
CAPTURE = ("static", "class", "getter", "path")
ENCODING = ("ascii", "utf16")
REGISTER = ("rcx", "rdx", "r8", "r9", "ecx", "edx", "r8d", "r9d")
SOURCE = ("pointer_table", "code_reference")
KIND = ("class", "module")
ITEM = ("name_layout", "singleton_instance", "vtable_set", "register_task", "register_abi", "task_group_index",
        "task_run_slot", "task_object_size", "static_slot_instance", "static_slot_module_base",
        "static_pattern_in_memory", "layout_fields")

# Every key of schema 1 and its type: a type name, or a tuple of the key's fixed words.
KEYS: dict[str, object] = {
    # the top
    "complete": B, "image": O, "fd4": O, "rtti": O, "register": O, "group": O, "statics": AO, "confirm": AO,
    "stats": O,
    # the image
    "file_size": U, "image_base": U, "entry_point": U, "size_of_image": U, "size_of_headers": U,
    "section_alignment": U, "file_alignment": U, "time_date_stamp": U, "characteristics": U,
    "dll_characteristics": U, "subsystem": U, "functions": U, "fixups": U, "file_version": AU,
    "product_version": AU, "region": REGION, "product_name": PRODUCT, "translation": AU, "resource_language": U,
    "sections": AO, "section": SECTION, "rva": U, "virtual_size": U, "raw_size": U,
    # the FD4 finder
    "status": STATUS, "path_strings": U, "path_references": U, "sites": U, "shapes": U, "sites_used": U,
    "idiom": O, "bytes": PATTERN, "length": U, "fixed": U, "hits": U, "sites_matched": U, "captures": AO,
    "capture": CAPTURE, "at": U, "insn_end": U, "align": U, "function": B, "scan_resolved": B, "scan_hits": U,
    "scan_rejected": U, "names": O, "offset": U, "encoding": ENCODING, "agree": U, "of": U, "accepted": U,
    "refused": O, "unreadable": U, "static_section": U, "static_alignment": U, "class_section": U,
    "getter_section": U, "getter_not_function": U, "no_path": U, "path_section": U, "path_text": U, "unnamed": U,
    "unlisted": U, "unlisted_ambiguous": U, "singletons": AO, "label": LABEL, "static": U, "class": U, "getter": U,
    "refusal": REFUSAL,
    # RTTI
    "locators": U, "vtables_found": U, "sets": AO, "type_descriptor": U, "classes": U, "primary": AU,
    "subobject": AU, "task": O, "base_vtable": U, "base_slots": U, "vtables": AU, "slots_min": U, "slots_max": U,
    "slot_targets": AU, "run_slot": U,
    # the registration
    "instance_static": U, "loads": U, "calls": U, "candidates": AO, "callee": U, "instance_register": REGISTER,
    "task_register": REGISTER, "group_register": REGISTER, "shaped": B, "agrees": B, "callers": AU, "pattern": O,
    "hit": U, "entry": U, "anchor": U, "fn_length": U, "matches": U, "capture_at": U, "capture_insn_end": U,
    "target": U,
    # the group
    "strings": U, "index": U, "source": SOURCE, "entries": U,
    # the statics and the list for R1
    "kind": KIND, "vtable": U, "slots": U, "rtti_status": STATUS, "slot": U, "references": U, "item": ITEM,
    "value": U,
    # the counts
    "instructions": U, "undecodable": U,
}

WORDS: frozenset[str] = frozenset({REPORT} | set(KEYS) | {w for t in KEYS.values() if isinstance(t, tuple) for w in t})


def is_report(doc: object) -> bool:
    """A parsed share file that is a report of EldenNet's devkit: an object whose first key is `report`. DataPiler's
    own share files start with `format`."""
    return isinstance(doc, dict) and bool(doc) and next(iter(doc)) == "report"


@dataclass
class Walk:
    shape: str | None = None            # check 1's first failing place
    values: str | None = None           # check 2's
    strings: list[tuple[str, str, str]] = field(default_factory=list)   # (place, kind, string): key, word, label,
    #                                                                     pattern or other
    patterns: int = 0
    values_seen: int = 0


def pattern_ok(s: str) -> bool:
    """A byte pattern in canonical form: 1 to 64 bytes, each two upper-case hex digits or `??`, one space between
    them, at least four fixed; and its fixed bytes do not read as text."""
    if not PATTERN_RX.fullmatch(s):
        return False
    parts = s.split(" ")
    if sum(1 for x in parts if x != "??") < MIN_FIXED:
        return False
    return not reads_as_text([None if x == "??" else int(x, 16) for x in parts])


def reads_as_text(data: list[int | None]) -> bool:
    """TEXT_RUN printable ASCII characters in a row among the fixed bytes, or TEXT_RUN printable UTF-16LE ones."""
    run = 0
    for b in data:
        run = run + 1 if b is not None and 0x20 <= b < 0x7F else 0
        if run >= TEXT_RUN:
            return True
    for start in (0, 1):
        run = 0
        for k in range(start, len(data) - 1, 2):
            lo, hi = data[k], data[k + 1]
            run = run + 1 if lo is not None and hi == 0 and 0x20 <= lo < 0x7F else 0
            if run >= TEXT_RUN:
                return True
    return False


def _uint(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= UINT_MAX


def walk(doc: object, labels: frozenset[str] | None) -> Walk:
    """Checks 1 and 2 of a parsed report (objects as guard._Obj, which marks a key given twice), and its strings.
    labels: the leads' labels the report may name; None when DataPiler kept none for it, so that no label passes."""
    w = Walk()

    def shape(place: str) -> None:
        if w.shape is None:
            w.shape = place

    def value(place: str) -> None:
        if w.values is None:
            w.values = place

    if not isinstance(doc, dict):
        shape("(file)")
        return w
    keys = list(doc)
    if getattr(doc, "dups", False) or keys[:2] != ["report", "schema"]:
        shape("(top level)")
    if doc.get("report") != REPORT:
        shape("report")
    if not (_uint(doc.get("schema")) and doc.get("schema") == SCHEMA):
        shape("schema")
    w.strings.extend(("(top level)", "key", k) for k in keys if isinstance(k, str))
    if isinstance(doc.get("report"), str):
        w.strings.append(("report", "word" if doc["report"] == REPORT else "other", doc["report"]))
    body = {k: v for k, v in doc.items() if k not in ("report", "schema")}
    queue: deque[tuple[str, dict, int]] = deque([("", body, 1)])     # objects in the file's order, level by level
    while queue:
        place, obj, depth = queue.popleft()
        if depth > MAX_DEPTH:
            shape(place or "(top level)")
            continue
        for key, v in obj.items():
            at = "%s.%s" % (place, key) if place else key
            kind = KEYS.get(key)
            if place:
                w.strings.append((at, "key", key))
            if kind is None:
                shape(at)
                w.strings.extend(_loose_strings(at, v))
                continue
            if kind == O:
                if not isinstance(v, dict) or getattr(v, "dups", False):
                    shape(at)
                    w.strings.extend(_loose_strings(at, v))
                    continue
                queue.append((at, v, depth + 1))
            elif kind in (AO, AU):
                if not isinstance(v, list) or len(v) > MAX_ITEMS:
                    shape(at)
                    w.strings.extend(_loose_strings(at, v))
                    continue
                for j, x in enumerate(v):
                    xat = "%s[%d]" % (at, j)
                    if kind == AO:
                        if not isinstance(x, dict) or getattr(x, "dups", False):
                            shape(xat)
                            w.strings.extend(_loose_strings(xat, x))
                        else:
                            queue.append((xat, x, depth + 2))
                    else:
                        w.values_seen += 1
                        if not _uint(x):
                            value(xat)
                            w.strings.extend(_loose_strings(xat, x))
            else:
                w.values_seen += 1
                if isinstance(v, (dict, list)):
                    shape(at)
                    w.strings.extend(_loose_strings(at, v))
                elif kind == U:
                    if not _uint(v):
                        value(at)
                        w.strings.extend(_loose_strings(at, v))
                elif kind == B:
                    if not isinstance(v, bool):
                        value(at)
                        w.strings.extend(_loose_strings(at, v))
                elif kind == LABEL:
                    if isinstance(v, str) and LABEL_RX.fullmatch(v) and labels is not None and v in labels:
                        w.strings.append((at, "label", v))
                    else:
                        value(at)
                        w.strings.extend(_loose_strings(at, v))
                elif kind == PATTERN:
                    w.patterns += 1
                    if isinstance(v, str) and pattern_ok(v):
                        w.strings.append((at, "pattern", v))
                    else:
                        value(at)
                        w.strings.extend(_loose_strings(at, v))
                else:                                           # a key of fixed words
                    if isinstance(v, str) and v in kind:        # type: ignore[operator]
                        w.strings.append((at, "word", v))
                    else:
                        value(at)
                        w.strings.extend(_loose_strings(at, v))
    return w


def _loose_strings(place: str, v: object) -> list[tuple[str, str, str]]:
    """Every string in a value that has no place in the report, keys included: checks 3 and 4 read each."""
    out: list[tuple[str, str, str]] = []
    stack: list[tuple[str, object]] = [(place, v)]
    while stack:
        at, x = stack.pop()
        if isinstance(x, str):
            out.append((at, "other", x))
        elif isinstance(x, dict):
            for k, y in x.items():
                out.append((at, "other", k))
                stack.append(("%s.%s" % (at, k) if isinstance(k, str) else at, y))
        elif isinstance(x, list):
            stack.extend(("%s[%d]" % (at, j), y) for j, y in enumerate(x))
    return out


# ------------------------------------------------------------------------------------------------ the leads' labels

_HEADER_RX = re.compile(r"\[\s*([A-Za-z0-9_.\"\s]+?)\s*\]\s*(?:#.*)?")
_KEY_RX = re.compile(r"(?:([a-z][a-z0-9_]*)|\"([a-z][a-z0-9_]*)\")\s*=")
LABEL_TABLES = ("singletons", "vtable_sets", "statics")


def leads_labels(text: str) -> frozenset[str]:
    """The labels a leads file gives (EldenNet's `gal/leads.toml`): the keys of its [singletons], [vtable_sets] and
    [statics] tables, and the names of [statics.<label>] tables. A line DataPiler does not read as one of those adds
    no label: a label it missed fails check 2, so this reader fails closed."""
    labels: set[str] = set()
    table: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            m = _HEADER_RX.fullmatch(line)
            if m is None or line.startswith("[["):
                table = None
                continue
            parts = [p.strip().strip('"') for p in m.group(1).split(".")]
            table = parts[0] if len(parts) == 1 else None
            if len(parts) == 2 and parts[0] == "statics" and LABEL_RX.fullmatch(parts[1]):
                labels.add(parts[1])
            continue
        if table in LABEL_TABLES:
            m = _KEY_RX.match(line)
            if m is not None:
                label = m.group(1) or m.group(2)
                if LABEL_RX.fullmatch(label):
                    labels.add(label)
    return frozenset(labels)
