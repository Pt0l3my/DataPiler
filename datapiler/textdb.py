"""The local text database, `workspace/textdb.sqlite` (design 0001 §2 and §6, build plan §4.9).

It holds the texts of Smithbox's text exports, which may be game text: it stays in the workspace and never leaves the
PC. Its texts serve two ends only: `join_names` (the names, for workspace files) and the guard's check 3, which keeps
every one of them out of share files and shared log lines. Nothing here logs or returns a text but `names()`.

Check 3 compares a string with the texts twice: case-folded as it is, and in a normalised form (`normalise`: accents
dropped, case-folded, and every run of spaces, `_`, `-` and other signs one space), against the texts normalised the
same way. So a name written as a table name or a job id (`white_mask_varre`, `ser-ostrel-vane`) is a text still.

Smithbox's text export (ER08 §4.2): `{Name, SourceContainer, SourceCategory, FmgWrappers: [{Name, ID, Fmg: {Name,
Entries: [{ID, Text}], Version, BigEndian, Unicode}}]}`; `SourceContainer` is missing from older exports."""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import events, logbook

# Which wrappers of which containers hold each text set: "character_names" -> ((container, wrapper id), ...).
# ER01's leads (EldenNet's research, §8.2; build plan §10, P3; settled S22): the item containers hold the character
# names in the wrappers 18, 328 and 428 (the base game and the expansion's two layers) and the place names in 19, 329
# and 429. They are leads, not facts: join_names uses a set only once at least half (VERIFY_SHARE) of the
# non-negative name numbers of the rows it joins resolve in it, with the owner's own data, and fails with the reason
# otherwise; the share file's provenance records the share that resolved. The live container and the newest layer
# come first, as the game reads them, so the first text for an id is the one the game shows.
LEAD_CONTAINERS = ("item_dlc02", "item_dlc01", "item")
LEADS: dict[str, tuple[int, ...]] = {
    "character_names": (428, 328, 18),
    "place_names": (429, 329, 19),
}
VERIFY_SHARE = 0.5
TEXT_SETS: dict[str, tuple[tuple[str, int], ...]] = {
    name: tuple((c, w) for c in LEAD_CONTAINERS for w in wrappers) for name, wrappers in LEADS.items()
}

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS imports (container TEXT NOT NULL, language TEXT NOT NULL, wrappers INTEGER NOT NULL,"
    " entries INTEGER NOT NULL, sha256 TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (container, language))",
    "CREATE TABLE IF NOT EXISTS entries (container TEXT NOT NULL, language TEXT NOT NULL, wrapper_id INTEGER NOT NULL,"
    " wrapper_name TEXT NOT NULL, entry_id INTEGER NOT NULL, text TEXT NOT NULL,"
    " PRIMARY KEY (container, language, wrapper_id, wrapper_name, entry_id))",
)
_SEP = "\x00"
_APART_RX = re.compile(r"[\W_]+")


def normalise(s: str) -> str:
    """A string as check 3 also compares it: decomposed (NFKD) with its combining marks dropped, case-folded, and each
    run of characters other than letters and digits (spaces, `_`, `-`, punctuation) turned into one space, without
    spaces at either end. "White Mask Varré" and `white_mask_varre` both become "white mask varre"."""
    t = "".join(c for c in unicodedata.normalize("NFKD", s.casefold()) if not unicodedata.combining(c))
    return _APART_RX.sub(" ", t.casefold()).strip()


@dataclass(frozen=True)
class ImportResult:
    container: str
    language: str
    wrappers: int
    entries: int


class _Index:
    """The case-folded texts: a set for equality, one joined string for "contained in a text", and the texts of 4 or
    more characters by their first four characters for "contains a text"."""

    def __init__(self, texts: list[str]):
        folded = [t.casefold() for t in texts]
        self.exact = set(folded)
        self.joined = _SEP + _SEP.join(folded) + _SEP
        self.by_four: dict[str, list[str]] = {}
        for t in set(folded):
            if len(t) >= 4:
                self.by_four.setdefault(t[:4], []).append(t)
        for lst in self.by_four.values():
            lst.sort(key=len)

    def contains_text(self, hay: str) -> bool:
        get = self.by_four.get
        for i in range(len(hay) - 3):
            cands = get(hay[i:i + 4])
            if cands:
                for t in cands:
                    if hay.startswith(t, i):
                        return True
        return False


def _hit(idx: _Index, t: str) -> bool:
    """Check 3's three comparisons of one prepared string with one index."""
    if t in idx.exact:
        return True
    if len(t) >= 4 and t in idx.joined:
        return True
    return idx.contains_text(t)


class TextDB:
    def __init__(self, path: Path):
        """sqlite3, one connection behind a lock. Tables imports(container, language, wrappers, entries, sha256, at)
        and entries(container, language, wrapper_id, wrapper_name, entry_id, text), keyed by the first five."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            for stmt in _SCHEMA:
                self._db.execute(stmt)
            self._db.commit()
        self._index: _Index | None = None
        self._nindex: _Index | None = None          # the texts normalised (`normalise`), for check 3

    # ---- writing

    def import_export(self, data: dict, *, container: str, language: str, sha256: str) -> ImportResult:
        """Replace that container's entries for that language. Empty texts are skipped. Emits textdb.changed.
        data has passed inbox.check_export."""
        rows: list[tuple] = []
        wrappers = 0
        for w in data.get("FmgWrappers") or []:
            wrappers += 1
            wid = int(w["ID"])
            wname = w.get("Name") if isinstance(w.get("Name"), str) else ""
            for e in (w.get("Fmg") or {}).get("Entries") or []:
                text = e.get("Text")
                if not isinstance(text, str) or not text.strip():
                    continue
                rows.append((container, language, wid, wname, int(e["ID"]), text))
        with self._lock:
            db = self._conn()
            with db:
                db.execute("DELETE FROM entries WHERE container = ? AND language = ?", (container, language))
                db.executemany("INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?, ?, ?)", rows)
                kept = db.execute("SELECT COUNT(*) FROM entries WHERE container = ? AND language = ?",
                                  (container, language)).fetchone()[0]
                db.execute("INSERT OR REPLACE INTO imports VALUES (?, ?, ?, ?, ?, ?)",
                           (container, language, wrappers, kept, sha256, time.time()))
            self._index = None
            self._nindex = None
            total_containers, total_entries = self._totals()
        events.emit("textdb.changed", containers=total_containers, entries=total_entries)
        return ImportResult(container, language, wrappers, int(kept))

    # ---- reading

    def _conn(self) -> sqlite3.Connection:
        if self._db is None:
            raise sqlite3.ProgrammingError("the text database is closed")
        return self._db

    def _totals(self) -> tuple[int, int]:
        db = self._conn()
        c = db.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
        e = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        return int(c), int(e)

    def containers(self) -> list[dict]:
        """[{"container", "language", "wrappers", "entries", "imported": "YYYY-MM-DD HH:MM"}], by container."""
        with self._lock:
            rows = self._conn().execute(
                "SELECT container, language, wrappers, entries, at FROM imports ORDER BY container, language"
            ).fetchall()
        return [{"container": c, "language": lang, "wrappers": int(w), "entries": int(e),
                 "imported": time.strftime("%Y-%m-%d %H:%M", time.localtime(at))} for c, lang, w, e, at in rows]

    def has(self, container: str, language: str) -> bool:
        with self._lock:
            row = self._conn().execute("SELECT 1 FROM imports WHERE container = ? AND language = ?",
                                       (container, language)).fetchone()
        return row is not None

    def _set_rows(self, text_set: str, language: str) -> list[tuple[int, str]]:
        pairs = TEXT_SETS.get(text_set)
        if pairs is None:
            raise KeyError(text_set)
        out: list[tuple[int, str]] = []
        with self._lock:
            db = self._conn()
            for container, wrapper_id in pairs:
                out.extend(db.execute(
                    "SELECT entry_id, text FROM entries WHERE container = ? AND language = ? AND wrapper_id = ? "
                    "ORDER BY entry_id", (container, language, int(wrapper_id))).fetchall())
        return [(int(i), t) for i, t in out]

    def ids(self, text_set: str, language: str) -> set[int]:
        """The entry ids of a text set that hold a text. KeyError for an unknown set."""
        return {i for i, _ in self._set_rows(text_set, language)}

    def wrappers(self, text_set: str) -> list[int]:
        """The wrapper ids of a text set, in TEXT_SETS's order, each once. KeyError for an unknown set."""
        pairs = TEXT_SETS.get(text_set)
        if pairs is None:
            raise KeyError(text_set)
        return list(dict.fromkeys(int(w) for _, w in pairs))

    def names(self, text_set: str, language: str) -> dict[int, str]:
        """Local only: for write_local, never for a share file. The first text for an id wins, in TEXT_SETS's
        order (the live container and the newest layer first)."""
        out: dict[int, str] = {}
        for i, t in self._set_rows(text_set, language):
            out.setdefault(i, t)
        return out

    def _idx(self) -> _Index:
        with self._lock:
            if self._index is None:
                texts = [t for (t,) in self._conn().execute("SELECT DISTINCT text FROM entries").fetchall()]
                self._index = _Index(texts)
            return self._index

    def _nidx(self) -> _Index:
        """The texts normalised (`normalise`), built when first needed after each import."""
        with self._lock:
            if self._nindex is None:
                texts = [t for (t,) in self._conn().execute("SELECT DISTINCT text FROM entries").fetchall()]
                self._nindex = _Index([n for n in (normalise(t) for t in texts) if n])
            return self._nindex

    def text_hit(self, s: str) -> bool:
        """Check 3 for one string: it equals a text, case-folded; or, at 4 or more characters, it is contained in a
        text; or it contains a text of 4 or more characters. Then the same three in the normalised form, against the
        texts normalised (accents, case and the signs between words aside)."""
        if not isinstance(s, str) or not s:
            return False
        t = s.casefold()
        if _SEP in t:
            if t in self._idx().exact:
                return True
            return any(self.text_hit(part) for part in t.split(_SEP) if part)
        if _hit(self._idx(), t):
            return True
        n = normalise(s)
        return bool(n) and _hit(self._nidx(), n)

    def find_in(self, haystack: str) -> bool:
        """Whether any text of 4 or more characters occurs in haystack, case-folded, or normalised in the haystack
        normalised: an index of texts by their first four characters, probed at each position (for log lines and
        share strings alike)."""
        if not isinstance(haystack, str) or len(haystack) < 4:
            return False
        if self._idx().contains_text(haystack.casefold()):
            return True
        n = normalise(haystack)
        return len(n) >= 4 and self._nidx().contains_text(n)

    def entries(self) -> int:
        with self._lock:
            return self._totals()[1]

    @property
    def closed(self) -> bool:
        return self._db is None

    def close(self) -> None:
        with self._lock:
            db, self._db = self._db, None
            self._index = None
            self._nindex = None
        if db is not None:
            try:
                db.close()
            except sqlite3.Error as e:
                logbook.get("textdb").warn("the text database did not close cleanly: %s", logbook.why(e))
