"""The server link (design 0001 §4, build plan §4.5): the one place DataPiler talks to Smithbox's local server.

- One channel, to 127.0.0.1:22720 only. The address is the two constants below, never a setting, an argument or
  anything the page sends.
- Seven read calls (`ALLOWED`), each built by hand with `channel.unary_unary` from the fixed table `_CALLS`. No service
  stub is generated or imported, so no other call can be made through generated code.
- Every call goes through `Link._call`, which in this order refuses a method not on the list, checks the session's
  switch, checks afresh that the game is closed, makes the call, counts it, logs its method and counts at DEBUG
  (never its data) and emits `link.call`.
- Rows are always read from the vanilla bank, and `OpenResource` is sent map resources only.
- Only numbers leave this module: row ids, cells of numeric field types, map ids matching `MAP_RX` and param names of
  a checked shape. Row names, object names, text cells and any other string from the server stay here: they are
  counted, never returned or logged.

`grpc`, `google.protobuf` and `soapstone` are imported inside functions only, so DataPiler runs without them (the
owner's N at the first start)."""

from __future__ import annotations

import math
import re
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

from . import events, logbook
from .gamewatch import GameWatch
from .logbook import Own, own

if TYPE_CHECKING:
    from .game import GameRunning

HOST = "127.0.0.1"
PORT = 22720
ALLOWED = ("ListParams", "ListParamRows", "GetParamRows", "SearchObjects", "GetObject",
           "BatchGetObjects", "OpenResource")
MAP_RX = re.compile(r"m\d{2}_\d{2}_\d{2}_\d{2}")
MAP_BATCH = 10                      # S8

PARAM_RX = re.compile(r"[A-Za-z0-9_]{1,64}")
FIELD_RX = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")

# The one table of calls: method -> (its path, its request class, its response class), the classes in
# soapstone/internal_pb2. The service and the classes are SoapstoneLib's (soapstone/SOURCE.md). Each path is a literal:
# no path is ever built from anything else.
_CALLS: dict[str, tuple[str, str, str]] = {
    "ListParams": ("/SoapstoneLib.Proto.Internal.Soapstone/ListParams",
                   "ListParamsRequest", "ListParamsResponse"),
    "ListParamRows": ("/SoapstoneLib.Proto.Internal.Soapstone/ListParamRows",
                      "ListParamRowsRequest", "ListParamRowsResponse"),
    "GetParamRows": ("/SoapstoneLib.Proto.Internal.Soapstone/GetParamRows",
                     "GetParamRowsRequest", "GetParamRowsResponse"),
    "SearchObjects": ("/SoapstoneLib.Proto.Internal.Soapstone/SearchObjects",
                      "SearchObjectsRequest", "SearchObjectsResponse"),
    "GetObject": ("/SoapstoneLib.Proto.Internal.Soapstone/GetObject",
                  "GetObjectRequest", "GetObjectResponse"),
    "BatchGetObjects": ("/SoapstoneLib.Proto.Internal.Soapstone/BatchGetObjects",
                        "BatchGetObjectsRequest", "BatchGetObjectsResponse"),
    "OpenResource": ("/SoapstoneLib.Proto.Internal.Soapstone/OpenResource",
                     "OpenResourceRequest", "OpenResourceResponse"),
}

# What each call is for, in DataPiler's words, for the Status card while the link is off. GetObject is on the list
# but 0.1 makes no use of it.
_FOR = (
    ("ListParams", "the names of the params"),
    ("ListParamRows", "the row ids of a param, from the game's own (vanilla) rows"),
    ("GetParamRows", "the numbers in a param's rows, from the game's own (vanilla) rows"),
    ("SearchObjects", "the maps loaded in Smithbox's map view, and the characters placed on them"),
    ("BatchGetObjects", "the numbers of the characters placed on a loaded map"),
    ("OpenResource", "loading maps into Smithbox's map view - its view changes, not its data"),
)

# Map objects. The file key's form is the one internal.proto's PrimaryKey and PrimaryKeyType describe, and an empty
# map name means "all open maps" (common.proto's EditorResource). The property names are not in the protos: they are
# to be confirmed against the server's own answers on the owner's PC (build plan §10, P5; EldenNet O48). A name that
# is wrong gives LinkDataError, never a guess.
MAP_FILE_TEMPLATE = "map/mapstudio/{0}.msb"
_MAP_FILE_RX = re.compile(r"map/mapstudio/(m\d{2}_\d{2}_\d{2}_\d{2})\.msb")
PLACEMENT_KEY = "NPCParamID"        # a part with this property above 0 is a placed character
PLACEMENT_PROPS = (("entity_id", "EntityID"), ("npc_param_id", "NPCParamID"), ("talk_id", "TalkID"),
                   ("model", "ModelName"))
MODEL_RX = re.compile(r"c(\d{4})")
OBJECT_BATCH = 200                  # keys per BatchGetObjects

# Field types of a param cell (internal.proto's ParamFieldInfo lists them). Only these become numbers; any other
# type, text among them, is refused.
_INT_TYPES = frozenset(("s8", "u8", "s16", "u16", "s32", "u32"))
_FLOAT_TYPES = frozenset(("f32", "angle32", "f64"))
_BOOL_TYPES = frozenset(("b32",))
_INT_RX = re.compile(r"[+-]?\d{1,19}")
_FLOAT_RX = re.compile(r"[+-]?(?:\d{1,40}(?:\.\d{0,40})?|\.\d{1,40})(?:[eE][+-]?\d{1,3})?")
_INT_VALUES = frozenset(("s8_value", "u8_value", "s16_value", "u16_value", "s32_value", "u32_value", "s64_value",
                         "u64_value"))
_INT32 = (-(2 ** 31), 2 ** 31 - 1)

_CHANNEL_OPTIONS = (
    ("grpc.enable_http_proxy", 0),                      # straight to 127.0.0.1, never through a proxy
    ("grpc.enable_retries", 0),
    ("grpc.max_receive_message_length", 64 * 1024 * 1024),
    ("grpc.max_send_message_length", 1024 * 1024),
)

_LOCK_FILE = Path(__file__).resolve().parent.parent / "requirements.lock"
_LOCK_PIN_RX = re.compile(r"# ([a-z0-9][a-z0-9._-]{0,63}) (\d{1,5}(?:\.\d{1,5}){0,3}) [A-Za-z0-9.+-]{1,32}")
_VERSION_RX = re.compile(r"[0-9][0-9A-Za-z.+-]{0,31}")

_OFF = "the server link is off"
_BLOCKED = "the game is running"
_NO_LIBS = "the server link needs its libraries - restart DataPiler and answer Y"
_CANCELLED = "cancelled"
_MAP_EDITOR = ("Smithbox's server could not list the maps (UNKNOWN): most likely the Map Editor is not enabled "
               "in your Smithbox project. Enable it in the project's settings, open the Map Editor once, then run "
               "again")

_log = logbook.get("link")


class LinkError(Exception):
    """A refusal or a failure; str(e) is DataPiler's words, safe to show and to log."""

    def __init__(self, text: str):
        super().__init__(own(text))

    @property
    def text(self) -> Own:
        return self.args[0]


class LinkOff(LinkError):
    """The session's switch is off."""


class LinkBlocked(LinkError):
    """The game is running."""


class LibsMissing(LinkError):
    """grpcio or protobuf missing, or --no-link."""


class LinkDataError(LinkError):
    """The server sent something that is not a number where DataPiler reads one."""


class LinkCancelled(LinkError):
    """The cancel event was set; checked between calls."""


class LinkCallError(LinkError):
    def __init__(self, method: str, code: str):
        self.code = code                # the gRPC status code's name only, never its details
        super().__init__("the call %s to Smithbox's server failed: %s" % (method, code))


# ------------------------------------------------------------------------------------------------- the libraries

_libs: tuple | None = None
_libs_lock = threading.Lock()


def _load() -> tuple:
    """(grpc, soapstone.common_pb2, soapstone.internal_pb2), imported at first use."""
    global _libs
    with _libs_lock:
        if _libs is None:
            import grpc
            from soapstone import common_pb2, internal_pb2
            _libs = (grpc, common_pb2, internal_pb2)
        return _libs


def lock_pins(path: Path | None = None) -> dict[str, str]:
    """The packages requirements.lock's header names, with their versions. Raises OSError or ValueError."""
    text = (path or _LOCK_FILE).read_text(encoding="ascii")
    lines = text.splitlines()
    if not lines or lines[0] != "# datapiler-lock/1":
        raise ValueError("not a DataPiler lock")
    pins: dict[str, str] = {}
    for line in lines[1:]:
        if not line.startswith("#"):
            break
        if line.startswith(("# pythons:", "# download-mb:")):
            continue
        m = _LOCK_PIN_RX.fullmatch(line)
        if m is None:
            raise ValueError("a header line of another shape")
        pins[m.group(1)] = m.group(2)
    return pins


def available() -> tuple[bool, Own]:
    """Whether grpc, protobuf and soapstone import, at the lock's versions. Imports them lazily. Never raises."""
    try:
        try:
            pins = lock_pins()
        except (OSError, ValueError, UnicodeError):
            return False, own("requirements.lock could not be read")
        if not pins:
            return False, own("requirements.lock names no packages")
        from importlib import metadata
        for name, want in pins.items():
            try:
                have = metadata.version(name)
            except metadata.PackageNotFoundError:
                return False, own("%s is not installed" % name)
            if have != want:
                shown = have if isinstance(have, str) and _VERSION_RX.fullmatch(have) else "another version"
                return False, own("%s %s is installed, the lock pins %s" % (name, shown, want))
        try:
            _load()
        except Exception as e:
            return False, own("the server link's libraries did not load (%s)" % logbook.why(e))
        return True, own(", ".join("%s %s" % kv for kv in pins.items()) + ", as the lock pins them")
    except Exception as e:
        return False, own("the server link's libraries could not be checked (%s)" % logbook.why(e))


def port_answers(game: Callable[[], "GameRunning"]) -> bool | None:
    """A TCP connect to 127.0.0.1:22720 within 0.5 s, closed at once, no bytes sent. None, with no connect made,
    while the game runs. Needs no grpc."""
    try:
        if game().running:
            return None
    except Exception:
        return None
    try:
        s = socket.create_connection((HOST, PORT), timeout=0.5)
    except OSError:
        return False
    try:
        s.close()
    except OSError:
        pass
    return True


def map_key(map_id: str) -> int:
    """"m12_34_56_78" -> 12345678. ValueError for anything not MAP_RX."""
    if not isinstance(map_id, str) or not MAP_RX.fullmatch(map_id):
        raise ValueError("not a map id")
    return int(map_id[1:].replace("_", ""))


@dataclass(frozen=True)
class Placement:
    map: int            # map_key
    entity_id: int
    npc_param_id: int
    talk_id: int
    model: int          # "c1234" -> 1234; -1 when the model is not of that shape (counted, never returned as text)


def _code_name(e: BaseException) -> str:
    try:
        name = e.code().name            # type: ignore[attr-defined]
    except Exception:
        return "UNKNOWN"
    return name if isinstance(name, str) and re.fullmatch(r"[A-Z_]{1,32}", name) else "UNKNOWN"


def _cell(value: object, def_type: object, where: str) -> int | float | bool:
    """One cell's text as a number, by its field type. Raises LinkDataError naming where only."""
    v = value.strip() if isinstance(value, str) else None
    t = def_type if isinstance(def_type, str) else ""
    if v is None:
        raise LinkDataError("the server sent a value that is not a number (%s)" % where)
    if t in _BOOL_TYPES:
        low = v.lower()
        if low in ("true", "1"):
            return True
        if low in ("false", "0"):
            return False
    elif t in _INT_TYPES or (t == "" and _INT_RX.fullmatch(v)):
        if _INT_RX.fullmatch(v):
            x = int(v)
            if abs(x) < 2 ** 63:
                return x
    elif t in _FLOAT_TYPES or t == "":
        if _FLOAT_RX.fullmatch(v):
            f = float(v)
            if math.isfinite(f):
                return f
    raise LinkDataError("the server sent a value that is not a number (%s)" % where)


def _check_param(param: str) -> None:
    if not isinstance(param, str) or not PARAM_RX.fullmatch(param):
        raise ValueError("not a param name")


def _chunks(seq: Sequence, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# ------------------------------------------------------------------------------------------------------ the link

class Link:
    call_timeout = 30.0                 # seconds for one call
    watch_interval = 2.0                # the game watcher's interval
    map_poll = 2.0                      # how often open_maps looks for its batch in the loaded maps
    map_wait = 900.0                    # how long one batch of maps may take to load

    def __init__(self, game: Callable[[], "GameRunning"], *, libs: bool, _test_port: int | None = None):
        """libs False (from --no-link or available()) makes the state "no_libs" for good. The host is always HOST;
        _test_port exists for the fake server and is used nowhere outside tests/."""
        self._game = game
        self._libs = bool(libs)
        self._port = PORT if _test_port is None else int(_test_port)
        self._lock = threading.RLock()
        self._session = False
        self._blocked = False
        self._channel = None
        self._fns: dict[str, object] = {}
        self._watch: GameWatch | None = None
        self._token: object | None = None
        self._calls = 0
        self._last_call: str | None = None
        self._recent: deque[str] = deque(maxlen=16)
        self._unsubscribe = events.subscribe("app.stopping", self._on_stopping)

    # ---- state

    @property
    def state(self) -> str:
        """"off", "on", "blocked" or "no_libs"."""
        with self._lock:
            if not self._libs:
                return "no_libs"
            if not self._session:
                return "off"
            return "blocked" if self._blocked else "on"

    def switch(self, on: bool) -> str:
        """On: refused (state returned unchanged) with no_libs; "blocked" while the game runs (the switch is on,
        no call is made, and the link goes on once the watcher has seen the game closed for two checks in a row);
        starts the watcher. Off: closes the channel and stops the watcher. Emits link.state."""
        if not on:
            if self._stop_link():
                _log.info("the server link is off")
                events.emit("link.state", state=own("off"), why=None)
            return self.state
        with self._lock:
            if not self._libs or self._session:
                return self.state
        running = self._game_running()
        with self._lock:
            if self._session:
                return self.state
            self._session = True
            self._blocked = running
            token = object()
            watch = GameWatch(self._game, lambda now: self._on_game(token, now), self.watch_interval)
            self._token, self._watch = token, watch
        if running:
            watch.saw_running()
            _log.warn("the server link is on but waits: the game is running")
            events.emit("link.state", state=own("blocked"), why=own(_BLOCKED))
        else:
            _log.info("the server link is on")
            events.emit("link.state", state=own("on"), why=None)
        watch.start()
        return self.state

    def close(self, why: Own) -> None:
        """Close the channel and stop the watcher; the switch goes off."""
        if self._stop_link():
            _log.info("the server link is closed: %s", why)
            events.emit("link.state", state=own("off"), why=why if isinstance(why, Own) else None)

    def stats(self) -> dict:
        """{"calls": int, "last_call": "HH:MM:SS" or None, "last_methods": [method, ...]}."""
        with self._lock:
            methods: list[str] = []
            for m in self._recent:
                if m not in methods:
                    methods.append(m)
            return {"calls": self._calls, "last_call": self._last_call, "last_methods": methods}

    def would_call(self) -> list[dict]:
        """[{"method": "ListParams", "for": "the names of the params"}, ...] for the Status card."""
        return [{"method": m, "for": f} for m, f in _FOR]

    # ---- the calls

    def list_params(self) -> list[str]:
        """Param names matching [A-Za-z0-9_]{1,64}; anything else is dropped and counted."""
        pb = self._messages()[2]
        resp = self._call("ListParams", pb.ListParamsRequest(), lambda r: len(r.param_names))
        names: list[str] = []
        dropped = 0
        for s in resp.param_names:
            if isinstance(s, str) and PARAM_RX.fullmatch(s):
                names.append(str(s))
            else:
                dropped += 1
        if dropped:
            _log.info("ListParams: %s names of another shape were dropped", logbook.n(dropped))
        return names

    def list_param_rows(self, param: str) -> list[int]:
        """Row ids only, each once, in the server's order; row names never leave this module."""
        _check_param(param)
        pb = self._messages()[2]
        resp = self._call("ListParamRows", pb.ListParamRowsRequest(param_name=param, vanilla=True),
                          lambda r: len(r.rows))
        ids: list[int] = []
        seen: set[int] = set()
        for row in resp.rows:
            rid = int(row.id)
            if rid not in seen:
                seen.add(rid)
                ids.append(rid)
        return ids

    def get_param_rows(self, param: str, row_ids: Sequence[int], fields: Sequence[str], *,
                       cancel: threading.Event | None = None,
                       progress: Callable[[int, int], None] | None = None) -> list[dict[str, int | float | bool]]:
        """One dict per row, {"id": row id, field: value}, only the fields asked; vanilla=True forced. A row id held
        by more than one row gives one dict per row; an id with no row gives none. Checks cancel between calls
        (LinkCancelled). Raises LinkDataError (naming the field's index) for a value that is not a number or a
        boolean, LinkError otherwise."""
        _check_param(param)
        fields = list(fields)
        for f in fields:
            if not isinstance(f, str) or not FIELD_RX.fullmatch(f):
                raise ValueError("not a field name")
        ids = list(row_ids)
        for rid in ids:
            if isinstance(rid, bool) or not isinstance(rid, int) or not _INT32[0] <= rid <= _INT32[1]:
                raise ValueError("not a row id")
        pb = self._messages()[2]
        out: list[dict[str, int | float | bool]] = []
        missing = 0
        total = len(ids)
        for done, rid in enumerate(ids):
            if cancel is not None and cancel.is_set():
                raise LinkCancelled(_CANCELLED)
            resp = self._call("GetParamRows", pb.GetParamRowsRequest(param_name=param, row_id=rid, vanilla=True),
                              lambda r: len(r.rows))
            if not resp.rows:
                missing += 1
            for row in resp.rows:
                cells: dict[str, tuple[object, object]] = {}
                for fv in row.values:
                    name = fv.internal_name
                    if not isinstance(name, str):
                        continue
                    base = name.split(":", 1)[0] if re.fullmatch(r"[A-Za-z0-9_]+:\d+", name) else name
                    cells.setdefault(base, (fv.value, fv.def_type))
                rec: dict[str, int | float | bool] = {"id": rid}
                for i, f in enumerate(fields):
                    if f == "id":
                        continue
                    cell = cells.get(f)
                    if cell is None:
                        raise LinkDataError("the server's answer has no field %d of those asked" % i)
                    rec[f] = _cell(cell[0], cell[1], "field %d" % i)
                out.append(rec)
            if progress is not None:
                progress(done + 1, total)
        if missing:
            _log.info("GetParamRows: %s of %s row ids had no row", logbook.n(missing), logbook.n(total))
        return out

    def all_maps(self) -> list[str]:
        """Every map id of Smithbox's project, loaded or not, sorted. Smithbox answers a file search over its map bank
        with every map it knows, whether loaded or not (`SoapstoneService.cs` at 2.2.6; settled S44), so this is the
        list of maps, not of loaded ones. A failure of the server here (UNKNOWN) most likely means the project has no
        Map Editor (WHY§6), and the error says so."""
        _, common, pb = self._messages()
        req = pb.SearchObjectsRequest(resource=self._map_resource(""),
                                      result_type=pb.PrimaryKeyType(file=MAP_FILE_TEMPLATE,
                                                                    category=pb.PRIMARY_KEY_CATEGORY_FILE))
        try:
            resp = self._call("SearchObjects", req, lambda r: len(r.results))
        except LinkCallError as e:
            if e.code == "UNKNOWN":
                raise LinkError(_MAP_EDITOR) from None
            raise
        maps: set[str] = set()
        for obj in resp.results:
            m = _MAP_FILE_RX.fullmatch(obj.key.file)
            if m is not None:
                maps.add(m.group(1))
        return sorted(maps)

    def is_loaded(self, map_id: str) -> bool:
        """Whether a map is loaded in Smithbox's map view: Smithbox lists the entries of loaded maps only, so an entry
        search on the map, one result at most, finds one exactly when it is loaded (S44)."""
        if not isinstance(map_id, str) or not MAP_RX.fullmatch(map_id):
            raise ValueError("not a map id")
        _, common, pb = self._messages()
        req = pb.SearchObjectsRequest(resource=self._map_resource(map_id),
                                      result_type=pb.PrimaryKeyType(file=MAP_FILE_TEMPLATE,
                                                                    category=pb.PRIMARY_KEY_CATEGORY_ENTRY),
                                      options=common.SearchOptions(max_results=1))
        try:
            resp = self._call("SearchObjects", req, lambda r: len(r.results))
        except LinkCallError as e:
            if e.code == "UNKNOWN":
                raise LinkError(_MAP_EDITOR) from None
            raise
        return len(resp.results) > 0

    def loaded_maps(self) -> list[str]:
        """The map ids loaded in Smithbox's map view, sorted: every map of the project, each asked whether it is
        loaded (S44)."""
        return [m for m in self.all_maps() if self.is_loaded(m)]

    def map_ids(self) -> list[str] | None:
        """Every map id of the project (all_maps, S44); in 0.1 to 0.2.2 no allowed call was known to list them."""
        return self.all_maps()

    def open_maps(self, map_ids: Sequence[str], *, cancel: threading.Event | None = None,
                  progress: Callable[[int, int], None] | None = None) -> int:
        """OpenResource for map resources only, MAP_BATCH at a time, waiting for each map of a batch to read as
        loaded (is_loaded); returns how many of map_ids are loaded. Map ids the project does not have are skipped,
        with a log line of their count; maps loaded already are not opened again. A batch that does not load within
        map_wait seconds raises LinkError. Asking the owner above ten is the runner's (S8)."""
        wanted: list[str] = []
        for m in map_ids:
            if not isinstance(m, str) or not MAP_RX.fullmatch(m):
                raise ValueError("not a map id")
            if m not in wanted:
                wanted.append(m)
        _, common, pb = self._messages()
        known = set(self.all_maps())
        unknown = [m for m in wanted if m not in known]
        if unknown:
            _log.info("%s of the map ids asked are not maps of this Smithbox project, and were skipped",
                      logbook.n(len(unknown)))
        wanted = [m for m in wanted if m in known]
        loaded = {m for m in wanted if self.is_loaded(m)}
        todo = [m for m in wanted if m not in loaded]
        total = len(todo)
        done = 0
        for batch in _chunks(todo, MAP_BATCH):
            for m in batch:
                if cancel is not None and cancel.is_set():
                    raise LinkCancelled(_CANCELLED)
                self._call("OpenResource", pb.OpenResourceRequest(resource=self._map_resource(m)), lambda r: 1)
            deadline = time.monotonic() + self.map_wait
            while True:
                waiting = [m for m in batch if m not in loaded]
                for m in waiting:
                    if self.is_loaded(m):
                        loaded.add(m)
                if all(m in loaded for m in batch):
                    break
                if time.monotonic() >= deadline:
                    raise LinkError("Smithbox did not load a batch of maps within %d s" % int(self.map_wait))
                if cancel is not None:
                    if cancel.wait(self.map_poll):
                        raise LinkCancelled(_CANCELLED)
                else:
                    time.sleep(self.map_poll)
            done += len(batch)
            if progress is not None:
                progress(done, total)
        return sum(1 for m in wanted if m in loaded)

    def placements(self, map_id: str) -> list[Placement]:
        """SearchObjects and BatchGetObjects on a loaded map: the placed characters, numbers only. LinkError when
        the map is not loaded."""
        if not isinstance(map_id, str) or not MAP_RX.fullmatch(map_id):
            raise ValueError("not a map id")
        _, common, pb = self._messages()
        if not self.is_loaded(map_id):
            raise LinkError("the map %s is not loaded in Smithbox" % map_id)
        number = map_key(map_id)
        file = "map/mapstudio/%s.msb" % map_id
        search = pb.PropertySearch(all_of_any_conditions=[pb.MultiPropertyCondition(conditions=[
            pb.PropertyCondition(type=common.GREATER, key=PLACEMENT_KEY, value=pb.PropertyValue(s32_value=0))])])
        req = pb.SearchObjectsRequest(resource=self._map_resource(map_id),
                                      result_type=pb.PrimaryKeyType(file=MAP_FILE_TEMPLATE,
                                                                    category=pb.PRIMARY_KEY_CATEGORY_ENTRY),
                                      search=search)
        resp = self._call("SearchObjects", req, lambda r: len(r.results))
        keys = [obj.key for obj in resp.results if obj.key.file == file]
        props = [common.RequestedProperty(key=key) for _, key in PLACEMENT_PROPS]
        out: list[Placement] = []
        odd_models = 0
        for chunk in _chunks(keys, OBJECT_BATCH):
            breq = pb.BatchGetObjectsRequest(resource=self._map_resource(map_id), keys=chunk, properties=props)
            bresp = self._call("BatchGetObjects", breq, lambda r: len(r.results))
            for obj in bresp.results:
                p = self._placement(number, obj)
                if p.model < 0:
                    odd_models += 1
                out.append(p)
        if odd_models:
            _log.info("placements of %s: %s models not of the form c0000", own(map_id), logbook.n(odd_models))
        return out

    # ---- inside

    def _messages(self) -> tuple:
        if not self._libs:
            raise LibsMissing(_NO_LIBS)
        try:
            return _load()
        except Exception:
            raise LibsMissing(_NO_LIBS) from None

    def _map_resource(self, name: str):
        """A map resource, the only kind DataPiler names: one map by its id, or "" for all open maps."""
        if name != "" and not MAP_RX.fullmatch(name):
            raise ValueError("not a map id")
        _, common, _pb = _load()
        return common.EditorResource(type=common.EDITOR_RESOURCE_TYPE_MAP, game=common.ELDEN_RING, name=name)

    @staticmethod
    def _placement(number: int, obj) -> Placement:
        props: dict[str, object] = {}
        for p in obj.properties:
            props.setdefault(p.key, p.value)
        vals: dict[str, int] = {}
        for i, (attr, key) in enumerate(PLACEMENT_PROPS):
            v = props.get(key)
            which = v.WhichOneof("value") if v is not None else None
            if attr == "model":
                m = MODEL_RX.fullmatch(v.string_value) if which == "string_value" else None
                vals[attr] = int(m.group(1)) if m is not None else -1
                continue
            if which not in _INT_VALUES:
                raise LinkDataError("the server sent a placed character's property %d that is not a number" % i)
            vals[attr] = int(getattr(v, which))
        return Placement(map=number, **vals)

    def _game_running(self) -> bool:
        try:
            return bool(self._game().running)
        except Exception:
            return True

    def _call(self, method: str, request: object, count: Callable[[object], int]) -> object:
        if method not in ALLOWED or method not in _CALLS:
            raise LinkError("that call is not on DataPiler's list")
        with self._lock:
            if not self._libs:
                raise LibsMissing(_NO_LIBS)
            if not self._session:
                raise LinkOff(_OFF)
            if self._blocked:
                raise LinkBlocked(_BLOCKED)
        if self._game_running():
            self._block(from_watch=False)
            raise LinkBlocked(_BLOCKED)
        grpc, _common, pb = _load()
        path, req_name, resp_name = _CALLS[method]
        if type(request) is not getattr(pb, req_name):
            raise LinkError("that request is not the one its call takes")
        with self._lock:
            if not self._session:
                raise LinkOff(_OFF)
            if self._blocked:
                raise LinkBlocked(_BLOCKED)
            if self._channel is None:
                self._channel = grpc.insecure_channel("%s:%d" % (HOST, self._port), options=_CHANNEL_OPTIONS)
                self._fns = {}
            fn = self._fns.get(method)
            if fn is None:
                fn = self._channel.unary_unary(path, request_serializer=getattr(pb, req_name).SerializeToString,
                                               response_deserializer=getattr(pb, resp_name).FromString)
                self._fns[method] = fn
            self._calls += 1
            self._recent.append(method)
            self._last_call = time.strftime("%H:%M:%S")
        t0 = time.monotonic()
        try:
            resp = fn(request, timeout=self.call_timeout)
        except Exception as e:
            secs = time.monotonic() - t0
            state = self.state
            if state == "blocked":
                err: LinkError = LinkBlocked(_BLOCKED)
            elif state != "on":
                err = LinkOff(_OFF)
            else:
                code = _code_name(e) if isinstance(e, grpc.RpcError) else "UNKNOWN"
                err = LinkCallError(method, code)
                _log.warn("%s failed: %s", own(method), own(code))
            events.emit("link.call", method=own(method), n=0, secs=secs, ok=False)
            raise err from None
        secs = time.monotonic() - t0
        try:
            k = int(count(resp))
        except Exception:
            k = 0
        _log.debug("%s: %s items in %s s", own(method), logbook.n(k), logbook.n(secs))
        events.emit("link.call", method=own(method), n=k, secs=secs, ok=True)
        return resp

    def _close_channel(self) -> None:
        """Under the lock."""
        ch, self._channel, self._fns = self._channel, None, {}
        if ch is not None:
            try:
                ch.close()
            except Exception:
                pass

    def _block(self, *, from_watch: bool) -> None:
        with self._lock:
            if not self._session or self._blocked:
                return
            self._blocked = True
            self._close_channel()
            watch = self._watch
        if watch is not None and not from_watch:
            watch.saw_running()
        _log.warn("the game started - the server link is closed")
        events.emit("link.state", state=own("blocked"), why=own(_BLOCKED))

    def _on_game(self, token: object, running: bool) -> None:
        with self._lock:
            if token is not self._token or not self._session:
                return
        if running:
            self._block(from_watch=True)
            return
        with self._lock:
            if token is not self._token or not self._session or not self._blocked:
                return
            self._blocked = False
        _log.info("the game is closed - the server link is on again")
        events.emit("link.state", state=own("on"), why=None)

    def _stop_link(self) -> bool:
        """The switch off, the channel closed, the watcher stopped. True when the switch was on."""
        with self._lock:
            was = self._session
            self._session = False
            self._blocked = False
            self._close_channel()
            watch, self._watch, self._token = self._watch, None, None
        if watch is not None:
            watch.stop()
        return was

    def _on_stopping(self, topic: str, data: dict) -> None:
        self.close(own("DataPiler is stopping"))
