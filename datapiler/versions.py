"""Game updates: every version's data kept side by side, and any two compared (DP23, settled S71).

A version is the key DataPiler already records in every provenance block and in a map job's saved progress
(runner.MAPS_KEY): the game's version, regulation.bin's sha256 and Smithbox's build. Its label, for the page and the
log, is the game's version and the first eight characters of the regulation hash, `v1.16.0.0 (ab12cd34)`; its folder
is named after it (`v1.16.0.0-ab12cd34`), with Smithbox's build added when two share a label. Everything lives in the
workspace,
under `versions/`, and never leaves the PC:

    versions/<version>/version.json                  the version's key, its label and when DataPiler first met it
    versions/<version>/<job>/reads/<table>.json      what the job's last completed run on that version read: each
                                                     fetch_rows and read_placements table as it was read (numbers
                                                     only), with the run's provenance
    versions/<version>/<job>/outputs/local|share/    the job's outputs of that version, moved here when a run on a
                                                     later version is about to write its own
    versions/<version>/<job>/changes/<earlier>.json  the change report of an update from an earlier version

A version's folder is never removed. A run again on the same version replaces that version's reads only when they
hold the same rows; reads that differ (or were read by another job file of the same id) are moved aside first, to
`reads-<date>-<time>/`, so nothing read is lost.

A param's read is compared with another by row id (rows sharing an id: as a multiset); a placements read map by map
(each map's placements as a multiset). The reports are local files: they hold row ids and map ids, and reach no share
file. Log lines name labels, job ids, table names and counts, never a path."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from . import events, fileio, logbook, paths as paths_mod
from .logbook import own

if TYPE_CHECKING:
    from .paths import Paths

KEY = ("game_version", "regulation_sha256", "smithbox_build")      # runner.MAPS_KEY
VERSION_FORMAT = "datapiler-version/1"
READ_FORMAT = "datapiler-read/1"
CHANGES_FORMAT = "datapiler-changes/1"
VERSION_FILE = "version.json"
READS = "reads"
OUTPUTS = "outputs"
CHANGES = "changes"
COUNTS_FILE = "share-counts.json"     # the moved share files' row counts (check 6's input), as the guard kept them
FOLDER_RX = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")
READ_KINDS = ("fetch_rows", "read_placements")
READ_MAX = 512 * 1024 * 1024
META_MAX = 64 * 1024
REPORT_MAX = 256 * 1024 * 1024

_lock = threading.RLock()
_log = logbook.get("job")


# ------------------------------------------------------------------------------------------------ keys and labels

def key_of(prov: object) -> dict | None:
    """The version key of a provenance block, or None when any of its three parts is missing."""
    if not isinstance(prov, dict):
        return None
    key = {k: prov.get(k) for k in KEY}
    if not all(isinstance(v, str) and v and len(v) <= 128 for v in key.values()):
        return None
    return key


def label(key: dict) -> str:
    """The page's and the log's short name of a version: the game's version and the first characters of the regulation
    hash, "v1.16.0.0 (ab12cd34)". (The "v" also keeps the log's mask from taking a four-part version for an address.)"""
    return "v%s (%s)" % (key["game_version"], str(key["regulation_sha256"])[:8])


def change_text(old: dict, new: dict) -> str:
    """The card's line for a job whose last run was on another version."""
    if old["game_version"] == new["game_version"] and old["regulation_sha256"] == new["regulation_sha256"]:
        return "Smithbox updated since this ran: build %s → %s" % (old["smithbox_build"], new["smithbox_build"])
    return "Game updated since this ran: %s → %s" % (label(old), label(new))


def params_same(old: dict, new: dict) -> bool:
    """Whether a param read on old holds what one on new would: the same regulation.bin, read by the same Smithbox
    build (a new build may read the same bytes into its fields differently, so its rows are read again)."""
    return old["regulation_sha256"] == new["regulation_sha256"] and old["smithbox_build"] == new["smithbox_build"]


def _part(s: str) -> str:
    out = re.sub(r"[^a-z0-9.]+", "-", str(s).lower())
    out = re.sub(r"\.{2,}", ".", out).strip("-.")
    return out or "x"


def _folder_ok(name: object) -> bool:
    return isinstance(name, str) and bool(FOLDER_RX.fullmatch(name)) and ".." not in name and \
        not name.endswith(".") and not paths_mod.reserved(name.split(".")[0])


def _root(p: "Paths") -> Path:
    return p.versions


# ------------------------------------------------------------------------------------------------ version folders

def _meta(p: "Paths", folder: str) -> dict | None:
    """A version folder's version.json, checked; None for anything else."""
    if not _folder_ok(folder):
        return None
    d = _root(p) / folder
    if d.is_symlink() or not d.is_dir():
        return None
    try:
        doc = json.loads(fileio.read_limited(d / VERSION_FILE, META_MAX).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return None
    if not isinstance(doc, dict) or doc.get("format") != VERSION_FORMAT or key_of(doc.get("key")) != doc.get("key") \
            or not isinstance(doc.get("at"), (int, float)) or isinstance(doc.get("at"), bool):
        return None
    return {"id": folder, "key": dict(doc["key"]), "label": label(doc["key"]), "at": float(doc["at"])}


def all_versions(p: "Paths") -> list[dict]:
    """Every version folder's record, the first met first."""
    try:
        names = [e.name for e in os.scandir(_root(p)) if e.is_dir(follow_symlinks=False)]
    except FileNotFoundError:
        return []
    out = [m for m in (_meta(p, n) for n in names) if m is not None]
    out.sort(key=lambda m: (m["at"], m["id"]))
    return out


def find(p: "Paths", key: dict | None) -> str | None:
    """The folder of a version, or None when DataPiler has not met it."""
    if key is None:
        return None
    with _lock:
        for m in all_versions(p):
            if m["key"] == key:
                return m["id"]
    return None


def ensure(p: "Paths", key: dict) -> str:
    """The folder of a version, made with its version.json when it is new: named by its label, with Smithbox's build
    or a number added when that name is another version's. Raises OSError."""
    if key_of(key) != key:
        raise ValueError("not a version key")
    with _lock:
        have = find(p, key)
        if have is not None:
            return have
        base = "v%s-%s" % (_part(key["game_version"])[:48], _part(key["regulation_sha256"])[:8])
        tries = [base, "%s-sb%s" % (base, _part(key["smithbox_build"])[:20])]
        tries += ["%s-%d" % (tries[1], k) for k in range(2, 100)]
        for name in tries:
            if not _folder_ok(name) or os.path.lexists(_root(p) / name):
                continue
            d = _root(p) / name
            d.mkdir(parents=True)
            doc = {"format": VERSION_FORMAT, "key": dict(key), "label": label(key), "at": time.time()}
            fileio.write_atomic(d / VERSION_FILE, (json.dumps(doc, indent=1, ensure_ascii=True) + "\n").encode("ascii"))
            _log.info("a new game version is kept apart in the workspace: %s", own(label(key)))
            return name
    raise OSError("the versions folder has no free name for this version")


def _job_dir(p: "Paths", folder: str, job_id: str) -> Path:
    if not _folder_ok(folder) or not paths_mod.name_ok(job_id):
        raise ValueError("not a version or a job DataPiler keeps")
    return _root(p) / folder / job_id


def rel(p: "Paths", f: Path) -> str:
    """A kept file's place relative to the workspace, as the page names it."""
    return Path(f).relative_to(p.workspace).as_posix()


# ------------------------------------------------------------------------------------------------ the reads

def _file_name(table: str) -> str:
    return (table + "-table" if paths_mod.reserved(table) else table) + ".json"


def _digest(body: object) -> str:
    return fileio.sha256_bytes(json.dumps(body, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
                                          allow_nan=False).encode("ascii"))


def _read_bytes(doc: dict, body_key: str, body: object) -> bytes:
    """A read as JSON, one row (or one map) a line, so a person can look at it."""
    def j(v: object) -> str:
        return json.dumps(v, ensure_ascii=True, allow_nan=False, separators=(", ", ": "))

    head = j(doc)[:-1]
    if body_key == "rows":
        lines = [" " + j(list(r)) for r in body]          # type: ignore[union-attr]
        text = head + ', "rows": [' + ("\n" + ",\n".join(lines) + "\n]" if lines else "]") + "}\n"
    else:
        lines = [" %s: %s" % (j(m), j([list(r) for r in rows])) for m, rows in body.items()]   # type: ignore[union-attr]
        text = head + ', "maps": {' + ("\n" + ",\n".join(lines) + "\n}" if lines else "}") + "}\n"
    return text.encode("ascii")


def _body(read: dict) -> tuple[str, object]:
    if read["kind"] == "fetch_rows":
        return "rows", [list(r) for r in read["rows"]]
    return "maps", {m: [list(r) for r in rows] for m, rows in read["maps"].items()}


def write_reads(p: "Paths", folder: str, job_id: str, job_sha256: str, provenance: dict | None,
                reads: Iterable[dict]) -> int:
    """Keep a completed run's reads for its version: one file per table. Reads already kept there that hold other rows
    (or another job file's) are moved aside first, never overwritten. How many files. Raises OSError."""
    jd = _job_dir(p, folder, job_id)
    docs = []
    for r in reads:
        if r.get("kind") not in READ_KINDS:
            continue
        body_key, body = _body(r)
        doc = {"format": READ_FORMAT, "job": job_id, "job_sha256": job_sha256, "op": int(r["op"]), "kind": r["kind"],
               "table": r["table"], "columns": [{"name": c, "type": t} for c, t in r["columns"]]}
        if r["kind"] == "fetch_rows":
            doc["param"] = r["param"]
            doc["listed"] = r.get("listed")
        else:
            doc["not_loaded"] = sorted(r.get("not_loaded") or [])
        doc["kept_from"] = r.get("kept_from")
        doc["provenance"] = dict(provenance or {})
        doc["sha256"] = _digest(body)
        docs.append((_file_name(r["table"]), doc, body_key, body))
    if not docs:
        return 0                                          # a job that reads no game table keeps nothing
    with _lock:
        rd = jd / READS
        if rd.is_dir():
            old = load_reads(p, folder, job_id)
            same = {t: d["sha256"] for t, d in old.items() if d["job_sha256"] == job_sha256}
            new = {d["table"]: d["sha256"] for _, d, _, _ in docs}
            others = [f for f in rd.iterdir() if f.name.endswith(".json")]
            if others and same != new:
                aside = jd / ("%s-%s" % (READS, time.strftime("%Y%m%d-%H%M%S")))
                k = 2
                while os.path.lexists(aside):
                    aside = jd / ("%s-%s-%d" % (READS, time.strftime("%Y%m%d-%H%M%S"), k))
                    k += 1
                os.replace(rd, aside)
                _log.info("job %s: the reads kept for %s held other rows; they are kept apart beside the new ones",
                          own(job_id), own(_label_of(p, folder)))
        rd.mkdir(parents=True, exist_ok=True)
        for name, doc, body_key, body in docs:
            fileio.write_atomic(rd / name, _read_bytes(doc, body_key, body))
    events.emit("versions.changed")
    return len(docs)


def _label_of(p: "Paths", folder: str) -> str:
    m = _meta(p, folder)
    return m["label"] if m else folder


def _cols_ok(cols: object) -> bool:
    return isinstance(cols, list) and bool(cols) and all(
        isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("type") in ("int", "number", "bool")
        for c in cols)


def _cell_ok(t: str, v: object) -> bool:
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, bool)


def _rows_ok(rows: object, types: list[str]) -> bool:
    return isinstance(rows, list) and all(
        isinstance(r, list) and len(r) == len(types) and all(_cell_ok(t, v) for t, v in zip(types, r)) for r in rows)


def _check_read(doc: object, job_id: str) -> dict | None:
    if not isinstance(doc, dict) or doc.get("format") != READ_FORMAT or doc.get("job") != job_id or \
            doc.get("kind") not in READ_KINDS or not isinstance(doc.get("table"), str) or \
            not isinstance(doc.get("job_sha256"), str) or not _cols_ok(doc.get("columns")):
        return None
    types = [c["type"] for c in doc["columns"]]
    if doc["kind"] == "fetch_rows":
        if not isinstance(doc.get("param"), str) or not _rows_ok(doc.get("rows"), types):
            return None
        listed = doc.get("listed")
        if listed is not None and (not isinstance(listed, int) or isinstance(listed, bool)):
            return None
    else:
        maps = doc.get("maps")
        if not isinstance(maps, dict) or not all(isinstance(m, str) and _rows_ok(r, types) for m, r in maps.items()):
            return None
        if not isinstance(doc.get("not_loaded", []), list):
            return None
    return doc


def load_read(p: "Paths", folder: str | None, job_id: str, table: str) -> dict | None:
    """One kept read, checked; None when there is none."""
    if folder is None:
        return None
    try:
        f = _job_dir(p, folder, job_id) / READS / _file_name(table)
        doc = json.loads(fileio.read_limited(f, READ_MAX).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return None
    doc = _check_read(doc, job_id)
    return doc if doc is not None and doc["table"] == table else None


def load_reads(p: "Paths", folder: str | None, job_id: str) -> dict[str, dict]:
    """Every read kept for a job on a version, by table."""
    out: dict[str, dict] = {}
    if folder is None:
        return out
    try:
        rd = _job_dir(p, folder, job_id) / READS
        files = sorted(f for f in rd.iterdir() if f.name.endswith(".json") and f.is_file())
    except (OSError, ValueError):
        return out
    for f in files:
        try:
            doc = _check_read(json.loads(fileio.read_limited(f, READ_MAX).decode("utf-8")), job_id)
        except (OSError, ValueError, UnicodeDecodeError, RecursionError):
            continue
        if doc is not None and f.name == _file_name(doc["table"]):
            out[doc["table"]] = doc
    return out


def of_job(p: "Paths", job_id: str) -> list[dict]:
    """The versions a job has kept reads for, the first met first: id, label, when met, its tables."""
    out = []
    for m in all_versions(p):
        try:
            rd = _job_dir(p, m["id"], job_id) / READS
        except ValueError:
            continue
        try:
            names = [f.name[:-5] for f in rd.iterdir() if f.name.endswith(".json") and f.is_file()]
        except OSError:
            continue
        tables = sorted(n[:-6] if n.endswith("-table") else n for n in names)
        if tables:
            out.append({"id": m["id"], "label": m["label"], "key": m["key"],
                        "since": time.strftime("%Y-%m-%d", time.localtime(m["at"])), "tables": tables})
    return out


def counts(p: "Paths") -> dict[str, int]:
    """How many versions each job has kept reads for (a cheap listing: folders only)."""
    out: dict[str, int] = {}
    for m in all_versions(p):
        try:
            jobs = [e for e in os.scandir(_root(p) / m["id"]) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for e in jobs:
            if paths_mod.name_ok(e.name) and (Path(e.path) / READS).is_dir():
                out[e.name] = out.get(e.name, 0) + 1
    return out


# ------------------------------------------------------------------------------------------------ comparing

def _n(x: int) -> str:
    return "{:,}".format(x)


def _plain(t: str, doc: dict) -> str:
    return "%s (%s)" % (t, doc["param"]) if doc.get("kind") == "fetch_rows" else t


def _by_id(rows: list) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r[0], []).append(tuple(r))
    return out


def compare_rows(old: list, new: list) -> dict:
    """Two reads of a param, by row id (the first column): the ids added, changed (any field differs; rows sharing an
    id compared as a multiset) and removed, and how many are unchanged."""
    a, b = _by_id(old), _by_id(new)
    both = set(a) & set(b)
    changed = sorted(i for i in both if Counter(a[i]) != Counter(b[i]))
    return {"unit": "rows", "before": len(old), "after": len(new), "added": sorted(set(b) - set(a)),
            "changed": changed, "removed": sorted(set(a) - set(b)), "unchanged": len(both) - len(changed)}


def compare_maps(old: dict, new: dict, not_loaded: Iterable[str] = ()) -> dict:
    """Two reads of placements, map by map (each map's placements as a multiset): the maps added, changed and removed,
    how many are unchanged, and the maps the newer read named but could not load (not counted as removed)."""
    skip = set(not_loaded)
    both = set(old) & set(new)
    changed = sorted(m for m in both if Counter(map(tuple, old[m])) != Counter(map(tuple, new[m])))
    gone = set(old) - set(new)
    return {"unit": "maps", "before": len(old), "after": len(new), "added": sorted(set(new) - set(old)),
            "changed": changed, "removed": sorted(gone - skip), "not_read": sorted(gone & skip),
            "unchanged": len(both) - len(changed),
            "rows": {"before": sum(len(r) for r in old.values()), "after": sum(len(r) for r in new.values())}}


def _same_read(a: dict, b: dict) -> str | None:
    """Why two reads of a table cannot be compared, or None."""
    if a["job_sha256"] != b["job_sha256"]:
        return "read by another job file of this id"
    if a["kind"] != b["kind"] or a.get("param") != b.get("param") or a["columns"] != b["columns"]:
        return "the two reads are not of the same fields"
    return None


def _line(entry: dict) -> str:
    t = entry["name"]
    if entry.get("skipped"):
        return "%s: %s rows, unchanged (the regulation and Smithbox's build are those of %s, so the param was not " \
               "read again)" % (t, _n(entry["after"]), entry["skipped"])
    if not entry["compared"]:
        return "%s: not compared (%s)" % (t, entry["why"])
    unit = entry["unit"]
    out = "%s: %s → %s %s: %s added, %s changed, %s removed, %s unchanged" % (
        t, _n(entry["before"]), _n(entry["after"]), unit, _n(len(entry["added"])), _n(len(entry["changed"])),
        _n(len(entry["removed"])), _n(entry["unchanged"]))
    if entry.get("not_read"):
        out += ", %s not read (they did not load)" % _n(len(entry["not_read"]))
    return out


def compare_reads(old: dict[str, dict], new: dict[str, dict], *, old_label: str) -> list[dict]:
    """The tables of two versions' reads of one job, in the newer read's order, then those only the older one has."""
    out = []
    order = sorted(new, key=lambda t: (new[t]["op"], t)) + sorted(set(old) - set(new), key=lambda t: (old[t]["op"], t))
    for t in order:
        a, b = old.get(t), new.get(t)
        doc = b if b is not None else a
        entry: dict = {"table": t, "name": _plain(t, doc), "kind": doc["kind"], "param": doc.get("param"),
                       "compared": False, "why": None, "skipped": None}
        if a is None:
            entry["why"] = "no read of %s was kept" % old_label
        elif b is None:
            entry["why"] = "the newer version has no read of it"
        else:
            entry["why"] = _same_read(a, b)
        if entry["why"] is None:
            entry["compared"] = True
            if doc["kind"] == "fetch_rows":
                entry.update(compare_rows(a["rows"], b["rows"]))
                if b.get("kept_from") is not None and b.get("kept_from") == a.get("_folder"):
                    entry["skipped"] = old_label
            else:
                entry.update(compare_maps(a["maps"], b["maps"], b.get("not_loaded") or ()))
        entry["line"] = _line(entry)
        out.append(entry)
    return out


def compare(p: "Paths", job_id: str, a: str | None, b: str, *, a_key: dict | None = None) -> dict:
    """The change report of a job between two versions' kept reads (a, the older, may be a version DataPiler holds no
    reads of: a_key names it then). ValueError for a version it does not have."""
    if not paths_mod.name_ok(job_id):
        raise ValueError("not a job DataPiler keeps")
    mb = _meta(p, b) if isinstance(b, str) else None
    ma = _meta(p, a) if isinstance(a, str) else None
    if mb is None or (a is not None and ma is None) or (ma is None and a_key is None):
        raise ValueError("not a version DataPiler keeps")
    old_label = ma["label"] if ma else label(a_key)          # type: ignore[arg-type]
    old = load_reads(p, a, job_id)
    for d in old.values():
        d["_folder"] = a
    new = load_reads(p, b, job_id)
    tables = compare_reads(old, new, old_label=old_label)
    for e in tables:
        e.pop("name", None)
    return {"format": CHANGES_FORMAT, "job": job_id,
            "from": {"version": a, "label": old_label, "key": ma["key"] if ma else a_key},
            "to": {"version": b, "label": mb["label"], "key": mb["key"]},
            "made": time.strftime("%Y-%m-%d %H:%M"), "tables": tables, "lines": [e["line"] for e in tables]}


def write_report(p: "Paths", folder: str, job_id: str, report: dict) -> str:
    """Keep a change report beside the newer version's reads; its place relative to the workspace. Raises OSError."""
    src = report["from"]["version"] or ("v%s-%s" % (_part(report["from"]["key"]["game_version"])[:48],
                                                    _part(report["from"]["key"]["regulation_sha256"])[:8]))
    if not _folder_ok(src):
        src = "earlier"
    f = _job_dir(p, folder, job_id) / CHANGES / (src + ".json")
    f.parent.mkdir(parents=True, exist_ok=True)
    fileio.write_atomic(f, (json.dumps(report, indent=1, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
    events.emit("versions.changed")
    return rel(p, f)


# ------------------------------------------------------------------------------------------------ the outputs

def keep_outputs(p: "Paths", folder: str, job_id: str, local: list[tuple[Path, str]],
                 share: tuple[Path, str] | None, counts_entry: dict | None) -> int:
    """Move a job's outputs of a version into that version's folder, before a run on another version writes its own:
    each workspace file to outputs/local/, the share file to outputs/share/ with its row counts in share-counts.json.
    Never over a file: when outputs/ holds one of the names, they go to outputs-<date>-<time>/. How many files moved.
    Raises OSError (what moved stays moved; what did not stays in its place)."""
    from .deleted import move_file

    jd = _job_dir(p, folder, job_id)
    files = [(src, "local", name) for src, name in local if src.is_file()]
    if share is not None and share[0].is_file():
        files.append((share[0], "share", share[1]))
    if not files:
        return 0
    with _lock:
        out = jd / OUTPUTS
        if any(os.path.lexists(out / area / name) for _, area, name in files):
            out = jd / ("%s-%s" % (OUTPUTS, time.strftime("%Y%m%d-%H%M%S")))
            k = 2
            while os.path.lexists(out):
                out = jd / ("%s-%s-%d" % (OUTPUTS, time.strftime("%Y%m%d-%H%M%S"), k))
                k += 1
        moved = 0
        for src, area, name in files:
            (out / area).mkdir(parents=True, exist_ok=True)
            if area == "share" and counts_entry is not None:
                fileio.write_atomic(out / COUNTS_FILE, (json.dumps({name: counts_entry}, indent=1, ensure_ascii=True)
                                                        + "\n").encode("ascii"))
            move_file(src, out / area / name)
            moved += 1
    events.emit("versions.changed")
    return moved
