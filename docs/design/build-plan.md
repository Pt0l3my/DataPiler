# DataPiler 0.1: the build plan

*For the four builders of DataPiler 0.1 and the lead who commits their work (2026-11-08). Built from design 0001
([0001-design.md](0001-design.md), its mock [0001-mock.html](0001-mock.html)), what was settled from it
([settled.md](settled.md), S1 to S14, which win over design §7 where they differ, and S15 to S24 from the build and
its fix rounds), the owner's decisions ([../DECISIONS.md](../DECISIONS.md), DP1 to DP8) and the request's "Rules it
must keep"
([../requests/0001-design.md](../requests/0001-design.md)). Smithbox facts are EldenNet's ER08 §3.1 and §4.2.*

The four builders work at the same time in the same working tree, each writing only the files this plan gives them:

- **CORE**: `datapiler.py`, the HTTP server and the API, settings, the logbook and its masking, the Windows adapter,
  the Smithbox and game status reads, the page (HTML, script, style, built from the mock), and the page parts copied
  from Jobrunner.
- **LINK**: `datapiler/link.py`, the game watcher, `soapstone/`, `requirements.lock`, the fake Soapstone server.
- **JOBS**: the job format and its check, the runner, the catalogue, the guard, the text database, the guided-export
  import, `schema/datapiler-job-1.schema.json`.
- **PACK**: `launcher-src/`, `DataPiler.ps1`, `BUILD.md`, `.github/workflows/`, `README.md`, `NOTICE`,
  `CHANGELOG.md`, the repository check, `.gitignore`.

Where this plan names something "to verify", no builder guesses it: §10 lists those points for the lead.

---

## 0. Order of work

1. **Phase 0, CORE first (short).** CORE writes the shared seams with their final signatures (§3) before anything
   else: `datapiler/__init__.py`, `datapiler/fileio.py`, `datapiler/events.py`, `datapiler/logbook.py`,
   `datapiler/paths.py`, `datapiler/winapi.py` (its portable backend at least) and `tests/_repo.py`. Then CORE tells
   the lead they are in place. The other three start at once on their own files and need the seams only to run their
   tests.
2. **Phase 1, all four in parallel**, each against the signatures in §3 and §4. A builder who needs a change in
   someone else's file asks the lead; nobody edits another builder's file, not even to fix an import.
3. **Phase 2, integration.** CORE wires the real `Link`, `Runner`, `Guard`, `TextDB` and `Inbox` into
   `datapiler.py` and writes `tests/test_integration.py`. LINK and JOBS fix mismatches in their own files.
4. **Phase 3, the lead.** The privacy sweep over every file, the full test run on Linux (standard library only, link
   tests skipping) and with grpcio in a venv under the brief's build folder, then the commit.

Each builder's report to the lead: the files written, the test command and its last lines, the sweep's result
(`privsweep.py files FILE...` from EldenNet's `tools/privsweep/`), and any §10 point they ran into.

---

## 1. The repository layout, file by file

Every file of 0.1 and its one owner. Existing files not listed (`LICENSE`, `CLAUDE.md`, `docs/`) are nobody's in
this build: no builder edits them.

| Path | Owner | What it is |
|---|---|---|
| `datapiler.py` | CORE | The entry point: command line, start and stop sequence (§4.11), start log |
| `datapiler/__init__.py` | CORE | `NAME`, `VERSION = "0.1.0"`: the one version every other file reads |
| `datapiler/fileio.py` | CORE | `write_atomic`, hashes, bounded reads (§3.1) |
| `datapiler/events.py` | CORE | The in-process event bus (§3.2) |
| `datapiler/logbook.py` | CORE | The log: format, levels, rotation, masking, the ring for the Terminal, job logs (§3.3) |
| `datapiler/paths.py` | CORE | The run-time folders and file names (§2, §3.4) |
| `datapiler/winapi.py` | CORE | The Windows adapter and its portable fallback (§3.5) |
| `datapiler/settings.py` | CORE | `settings.json`, its keys and checks; the session's switches (§4.1) |
| `datapiler/env.py` | CORE | The Python found and the venv's state, for the `env` log lines and the start log (§4.2) |
| `datapiler/game.py` | CORE | The game's folder, version, running check (S7), expansion, `regulation.bin`'s hash (§4.3) |
| `datapiler/smithbox.py` | CORE | Smithbox's folder, build, running, the server switch read from `Startup.json` (§4.3) |
| `datapiler/status.py` | CORE | The Status cards, the pills, the block line, the provenance block (§4.3) |
| `datapiler/server.py` | CORE | The HTTP server: Host, Origin and token guard, headers and CSP, the page's assembly (§4.4) |
| `datapiler/api.py` | CORE | The endpoints of §5, building their JSON from the modules |
| `datapiler/page/index.html` | CORE | The page's markup, from the mock |
| `datapiler/page/app.css` | CORE | Its one style sheet, from the mock and Jobrunner's tokens |
| `datapiler/page/app.js` | CORE | Its one script |
| `datapiler/link.py` | LINK | The server link: the allowlist, the one gate, the calls (§4.5) |
| `datapiler/gamewatch.py` | LINK | The 2 s game watcher while the link is on (§4.5) |
| `soapstone/__init__.py` | LINK | Empty, but for a docstring naming the source |
| `soapstone/*_pb2.py` | LINK | Message classes generated from SoapstoneLib's `.proto` files; no `*_pb2_grpc.py` |
| `soapstone/LICENSE` | LINK | SoapstoneLib's MIT licence, as fetched |
| `soapstone/SOURCE.md` | LINK | The pinned commit, each proto's path and sha256, the grpcio-tools version, the command, the service's full method list, the allowed seven |
| `requirements.lock` | LINK | grpcio and protobuf, wheels only, every file's sha256, with the header of §4.12 |
| `datapiler/jobs.py` | JOBS | The `datapiler-job/1` format: the check on arrival and the preview (§4.6) |
| `datapiler/fields.py` | JOBS | The params and fields DataPiler reads: the field allowlist (§4.6) |
| `datapiler/catalogue.py` | JOBS | The Extract rows, the bundles and each row's built-in ops (§4.7) |
| `datapiler/runner.py` | JOBS | The queue and the run of jobs and Extract rows (§4.8) |
| `datapiler/textdb.py` | JOBS | The local text database, `workspace/textdb.sqlite` (§4.9) |
| `datapiler/inbox.py` | JOBS | The guided-export import from `workspace/inbox/` (§4.9) |
| `datapiler/guard.py` | JOBS | The share file's format and the guard's six checks, and the kept row counts (§4.10) |
| `schema/datapiler-job-1.schema.json` | JOBS | The job format as JSON Schema, draft 2020-12 |
| `launcher-src/launcher.cpp` | PACK | Jobrunner's launcher, adapted (§7.3) |
| `launcher-src/app.rc` | PACK | Its resource script: DataPiler's name and version; no icon line for 0.1 (§10, P11) |
| `launcher-src/app.manifest` | PACK | Its manifest, `asInvoker` |
| `DataPiler.ps1` | PACK | The window's script (§4.12) |
| `BUILD.md` | PACK | Both routes to the exe, and how to check it |
| `.github/workflows/checks.yml` | PACK | Tests on Linux and Windows; the repository check (S14) |
| `.github/workflows/release.yml` | PACK | The exe built on a tag, attached with its sha256 to a draft release (S4) |
| `tools/repocheck.py` | PACK | The S14 check, standard library only |
| `README.md` | PACK | Rewritten for 0.1: what it is, how to start it, the first start's question, SmartScreen, the Jobrunner line |
| `NOTICE` | PACK | DataPiler (MIT); grpcio, protobuf, SoapstoneLib, Jobrunner (§7.4) |
| `CHANGELOG.md` | PACK | 0.1.0 |
| `.gitignore` | PACK | Adds `/jobs/`, `/settings.json`, `/datapiler.lock` to what it has |
| `tests/_repo.py` | CORE | Puts the repository root on `sys.path` (the test command runs with `-I`); every test module imports it first |
| `tests/test_fileio.py`, `test_logbook.py`, `test_masking.py`, `test_log_templates.py`, `test_settings.py`, `test_paths.py`, `test_winapi.py`, `test_status.py`, `test_server.py`, `test_api.py`, `test_page.py`, `test_start.py`, `test_integration.py` | CORE | §8.1 |
| `tests/fake_soapstone.py`, `test_link.py`, `test_link_static.py`, `test_gamewatch.py`, `test_lock.py` | LINK | §8.2 |
| `tests/test_jobs_check.py`, `test_jobs_preview.py`, `test_schema.py`, `test_runner.py`, `test_guard.py`, `test_textdb.py`, `test_inbox.py`, `test_catalogue.py` | JOBS | §8.3 |
| `tests/fixtures/job-files/*.json`, `tests/fixtures/text-exports/*.json` | JOBS | Invented fixtures (§8.5) |
| `tests/test_repocheck.py`, `test_launcher_src.py`, `test_ps1.py`, `test_workflows.py` | PACK | §8.4 |

Test files carry no `__init__.py`: the command is `python3 -I -m unittest discover -s tests` from the repository
root, which puts only `tests/` on the path, so each test module starts with `import _repo  # noqa: F401`.

---

## 2. The folder at run time

DataPiler writes only inside its own folder, and into the workspace and share folders when Settings moves them.

```
<DATAPILER>/
  DataPiler.exe            the launcher (release only; *.exe is ignored by git)
  DataPiler.ps1
  datapiler.py
  datapiler/  soapstone/  schema/  launcher-src/
  requirements.lock
  .venv/                   made by DataPiler.ps1 after Y; holds datapiler-lock.sha256 (§4.12)
  settings.json            CORE, atomic
  datapiler.port           CORE: the page's port, ASCII digits; removed at start and at stop
  datapiler.lock           CORE's portable stand-in for the mutex (not on Windows)
  datapiler-start.log      CORE: only when the page never came up
  logs/
    datapiler.log, .1 ... .4   CORE: RotatingFileHandler, log_max_mb each, log_keep backups
    jobs/<job id>.log          CORE's logbook, opened by JOBS's runner
  jobs/<job id>/
    job.json               JOBS: the bytes as dropped
    state.json             JOBS: the card's state, its ops' states, its result
  workspace/               local only, may hold game text
    textdb.sqlite          JOBS (textdb)
    share-counts.json      JOBS (runner, guard): each share file's row counts, for check 6 (S19); local only
    inbox/                 the owner saves Smithbox's text exports here; refused files stay, with their reason
    imported/              JOBS (inbox): imported exports, renamed <yyyymmdd-hhmmss>-<container>-<language>.json
    local/<job id>/<name>.json      JOBS: write_local
    local/extract/<row id>.json     JOBS: the Extract rows' full numbers
  share/<name>.json        JOBS (guard): share files, each guarded before it is written
```

A refused job with no usable id is kept under `jobs/refused-<first 12 hex of its sha256>/`. Names DataPiler writes
match `[a-z0-9][a-z0-9_-]{0,63}` plus `.json`; nothing is ever written under a name a job or the page supplies
without that check.

---

## 3. The shared seams (CORE, phase 0)

### 3.1 `datapiler/fileio.py`

```python
def write_atomic(path: Path, data: bytes) -> None:
    """Write data through "<path>.<pid>.tmp" in the same folder, flush, fsync, os.replace.
    Copied from Jobrunner's write_atomic (§7.1). Raises OSError."""

def sha256_bytes(data: bytes) -> str:
    """Lower-case hex."""

def sha256_file(path: Path) -> str:
    """Lower-case hex, read in 1 MiB chunks. Raises OSError."""

class TooLarge(ValueError):
    """A file or a request over its limit."""

def read_limited(path: Path, max_bytes: int) -> bytes:
    """The file's bytes. Raises TooLarge past max_bytes, OSError otherwise."""
```

### 3.2 `datapiler/events.py`

```python
def emit(topic: str, **data: int | float | bool | None | Own) -> None:
    """Call every subscriber whose prefix matches topic, in this thread. A subscriber that raises is logged
    (source app, ERROR, logbook.why(e)) and the others still run. Never raises."""

def subscribe(prefix: str, fn: Callable[[str, dict], None]) -> Callable[[], None]:
    """fn(topic, data) for every topic starting with prefix. Returns the function that unsubscribes."""
```

Event data follows the log rule (§3.3): numbers, booleans, `None` and `Own` strings only.

| Topic | Emitted by | Data | Who listens |
|---|---|---|---|
| `settings.saved` | CORE (api) | — | logbook masks (CORE), runner (JOBS: folders) |
| `app.stopping` | CORE (datapiler.py) | — | runner, inbox (JOBS), link (LINK) |
| `link.state` | LINK | `state` (off, on, blocked, no_libs), `why` (Own or None) | runner (wakes waiting work), api (state) |
| `link.call` | LINK | `method` (Own, one of the seven), `n` (items), `secs`, `ok` | status (calls, last call) |
| `job.added` | JOBS | `id` (Own), `state` | — |
| `job.state` | JOBS | `id`, `state` | — |
| `job.op` | JOBS | `id`, `n` (op index), `state`, `done`, `of` | — |
| `extract.row` | JOBS | `row` (Own), `state`, `done`, `of` | — |
| `inbox.import` | JOBS | `container` (Own), `ok`, `entries` | api (outputs revision) |
| `textdb.changed` | JOBS | `containers`, `entries` | guard (S6 label re-check) |
| `local.written` | JOBS | `job` (Own), `size` | api (outputs revision) |
| `share.written` | JOBS | `name` (Own), `size` | api (outputs revision) |
| `guard.failed` | JOBS | `name` (Own), `check` | — |

The page polls; events never reach it directly. CORE counts `inbox.import`, `local.written` and `share.written`
into `outputs_rev` in `/api/state`, so the Outputs tab reloads only when a file was written.

### 3.3 `datapiler/logbook.py`: the log call

The format, everywhere (window, files, Terminal tab), exactly:

```
f"{time}  {level:<5}  {source:<8} {message}"     time = local "YYYY-MM-DD HH:MM:SS.mmm"
2026-11-08 08:42:01.123  INFO   extract  NpcParam: 2,105 rows read in 0.4 s
```

Levels `DEBUG`, `INFO`, `WARN`, `ERROR`. `DEBUG` goes to the file only, and only while the session's debug switch is
on. The console and the ring (the Terminal tab) take `INFO` and up; the console colours `WARN` amber and `ERROR` red
with ANSI codes (`winapi.enable_vt()` first on Windows). At setup the file gets one separator line,
`---- DataPiler 0.1.0 ----`.

| Source | Owner | Used for |
|---|---|---|
| `app` | CORE | start, port, quit, the window's close, an event handler that failed |
| `page` | CORE | refused requests (the reason only, never a header's value), settings saved, uploads received (sizes) |
| `smithbox` | CORE | what the status reads found ("found in `<SMITHBOX>` - running, server on") |
| `env` | CORE | the Python, the venv's state, grpcio's and protobuf's versions (DataPiler.ps1 prints its own lines in the same format, source `env`) |
| `link` | LINK | switched on or off, blocked, each call at DEBUG (method and counts), failures (gRPC code name) |
| `extract` | JOBS | the Extract rows' progress and results |
| `job` | JOBS | jobs: added (counts of refusals), started, each op's result, done or failed; also the job's own file |
| `guard` | JOBS | a share file written (name, size) or refused (the check and the place) |
| `textdb` | JOBS | imports (container, counts), refused inbox files (their reason, never the file's name) |

```python
SOURCES = ("app", "page", "smithbox", "link", "extract", "job", "guard", "textdb", "env")
LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
RING = 5000

class Own(str):
    """A string DataPiler wrote or checked: its own words, a name it made, an id that passed its pattern, a param
    name from fields.PARAMS, a method name from link.ALLOWED. Only Own strings reach a log line as they are."""

def own(s: str) -> Own: ...
def n(x: int | float) -> Own:
    """2105 -> "2,105"; 0.42 -> "0.4"."""
def why(e: BaseException) -> Own:
    """The exception's type name, with errno for an OSError ("PermissionError (errno 13)"). Never str(e)."""

class Log:
    source: str
    def debug(self, template: str, *args: object) -> None: ...
    def info(self, template: str, *args: object) -> None: ...
    def warn(self, template: str, *args: object) -> None: ...
    def error(self, template: str, *args: object) -> None: ...
    # template: a string literal with %-placeholders. int, float, bool, None and Own args appear as they are; any
    # other str becomes "<text>", any other object "<?>". Never raises: a template whose args do not format is
    # logged as itself followed by " <args did not format>".

class JobLog(Log):
    def close(self) -> None: ...

def get(source: str) -> Log:
    """Raises ValueError for a source not in SOURCES."""
def setup(logs: Path, *, max_bytes: int, keep: int, console: bool) -> None:
    """The rotating file, the console handler when console is true, the ring. Before setup, lines go to stderr,
    masked."""
def set_masks(*, folders: Mapping[str, str | None], home: str | None, user: str | None, pc: str | None) -> None:
    """folders maps "<GAME>", "<SMITHBOX>", "<PROJECT>", "<WORKSPACE>", "<SHARE>", "<DATAPILER>" to a folder (or None).
    Rebuilds the mask: each folder in either slash, any case, and its 8.3 short form (winapi short_path), longest
    first; then the home folder as <HOME>; then user and PC names as whole words (<USER>, <PC>); then any IPv4 or
    IPv6 address other than 127.0.0.1 as <IP>. Called at start and on every settings.saved."""
def mask(text: str) -> str:
    """The mask the formatter applies, for the start log and error texts sent to the page."""
def set_debug(on: bool) -> None: ...
def for_job(job_id: Own) -> JobLog:
    """Source "job"; writes to the main handlers and to logs/jobs/<job_id>.log, same format, same mask."""
def lines_after(seq: int, limit: int = 1000) -> tuple[list[dict], int]:
    """Ring lines with a seq above seq, oldest first, at most limit, as
    {"seq": int, "t": str, "level": str, "src": str, "msg": str}, and the newest seq. Already masked."""
def shutdown() -> None:
    """Flush and close every handler."""
```

The mask sits in one `logging.Filter` on every handler, applied to the formatted line (design §5: mask at the
formatter, not at each call). A message is built from a literal template and safe arguments; nothing else. No
f-string, `.format` or `%` operator inside a log call's arguments (CORE's template test enforces it everywhere).

### 3.4 `datapiler/paths.py`

```python
NAME_RX = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

@dataclass(frozen=True)
class Paths:
    root: Path; workspace: Path; inbox: Path; imported: Path; local: Path; textdb: Path
    share: Path; logs: Path; job_logs: Path; jobs: Path
    port_file: Path; start_log: Path; settings: Path
    lock: Path                                      # requirements.lock
    mutex_file: Path                                # datapiler.lock, the portable stand-in for the mutex
    venv: Path; venv_marker: Path                   # .venv/ and .venv/datapiler-lock.sha256

def resolve(root: Path, workspace_dir: str, share_dir: str) -> Paths:
    """Relative workspace and share folders are taken under root."""
def ensure(p: Paths) -> None:
    """Make every folder DataPiler writes into. Raises OSError."""
def is_inside(child: str | Path, parent: str | Path) -> bool:
    """True when child is parent or lies inside it: resolved, compared by path parts, case-folded on Windows
    ("Game2" is not inside "Game")."""
def share_file(p: Paths, name: str) -> Path:
    """share/<name>.json. ValueError for a name not matching NAME_RX."""
def local_file(p: Paths, job_id: str, name: str) -> Path:
    """workspace/local/<job_id>/<name>.json. ValueError likewise."""
```

### 3.5 `datapiler/winapi.py`: the adapter

Everything Windows-only sits here, through `ctypes` with explicit `argtypes` and `restype` (handles are 64-bit). The
portable backend lets every test run on Linux.

```python
@dataclass(frozen=True)
class Proc:
    name: str            # image name, lower-cased, e.g. "eldenring.exe"
    path: str | None     # full image path when readable

class Holder(Protocol):
    def release(self) -> None: ...

class Backend(Protocol):
    def processes(self) -> list[Proc]:
        """Windows: CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS), Process32FirstW/NextW; the path through
        OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) and QueryFullProcessImageNameW, None when refused.
        Raises OSError when the snapshot fails. Portable: /proc where present, else []."""
    def file_version(self, path: str) -> str | None:
        """The fixed file version "a.b.c.d" (GetFileVersionInfoW, VerQueryValueW). Portable: None."""
    def hold_mutex(self, name: str, fallback_file: Path) -> Holder | None:
        """CreateMutexW(name); None when it already existed. Portable: fcntl.flock on fallback_file."""
    def on_console_close(self, fn: Callable[[], None]) -> None:
        """SetConsoleCtrlHandler for the close, logoff and shutdown events: calls fn and waits up to 4.5 s for it
        (Windows allows about 5). Ctrl+C stays KeyboardInterrupt. Portable: SIGTERM and SIGHUP."""
    def set_clipboard(self, text: str) -> bool:
        """CF_UNICODETEXT. Portable: False."""
    def open_folder(self, path: str) -> bool:
        """os.startfile. Portable: False."""
    def short_path(self, path: str) -> str | None:
        """GetShortPathNameW. Portable: None."""
    def enable_vt(self) -> None:
        """ENABLE_VIRTUAL_TERMINAL_PROCESSING on the console. Portable: nothing."""
    def user_name(self) -> str | None: ...
    def pc_name(self) -> str | None: ...
    def home(self) -> str | None: ...

def backend() -> Backend:
    """The Windows backend on Windows, else the portable one."""
@contextmanager
def use(b: Backend) -> Iterator[None]:
    """For tests: replace the backend inside the block."""
```

The user name, the PC name and the home folder are used for masks and the guard's check 4 only: never logged, never
sent to the page.

---

## 4. The interfaces

### 4.1 Settings (CORE, `datapiler/settings.py`)

`settings.json`, written atomically:

```json
{"format": "datapiler-settings/1", "smithbox_dir": "", "game_dir": "", "project_dir": "",
 "workspace_dir": "workspace", "share_dir": "share", "language": "engus", "expansion": "", "port": 0,
 "log_max_mb": 2, "log_keep": 5}
```

| Key | Type, range | Default | Takes effect |
|---|---|---|---|
| `smithbox_dir` | absolute folder or `""` | `""` | at once |
| `game_dir` | absolute folder or `""` | `""` | at once |
| `project_dir` | absolute folder or `""`; neither `game_dir` nor inside it | `""` | at once |
| `workspace_dir` | folder, relative to `<DATAPILER>` or absolute; not inside the game's, Smithbox's or the project's folder | `workspace` | at once, refused while a job or import runs |
| `share_dir` | as `workspace_dir`, and not inside the workspace | `share` | likewise |
| `language` | `[a-z]{2,8}` (Smithbox's code) | `engus` | at once |
| `expansion` | `"yes"`, `"no"`, or `""` (not stated yet): the owner's statement (P2, S21); share writes wait for it | `""` | at once |
| `port` | `0` (any free one) or 1024 to 65535 | `0` | next start |
| `log_max_mb` | 1 to 50 | `2` | next start |
| `log_keep` | 1 to 20 | `5` | next start |

The server's address is not a setting: `127.0.0.1:22720` is a constant in `link.py`, shown on the page.

```python
@dataclass(frozen=True)
class Settings:
    smithbox_dir: str = ""; game_dir: str = ""; project_dir: str = ""
    workspace_dir: str = "workspace"; share_dir: str = "share"; language: str = "engus"; expansion: str = ""
    port: int = 0; log_max_mb: int = 2; log_keep: int = 5

class SettingsError(ValueError):
    field: str           # the key
    rule: str            # DataPiler's words, e.g. "the project folder must be outside the game's folder"

def check(raw: Mapping[str, object]) -> Settings:
    """Every key known (an unknown key is refused), each of its type and range, the folder rules above.
    Raises SettingsError."""
def load(path: Path) -> tuple[Settings, list[Own]]:
    """settings.json, or the defaults; the list says what was wrong (a missing file: nothing)."""
def save(path: Path, s: Settings) -> None:
    """Atomic. Raises OSError."""

@dataclass
class Session:          # never saved: off at every start
    link: bool = False
    debug: bool = False
```

### 4.2 The environment (CORE, `datapiler/env.py`)

```python
def python_info() -> Own:
    """"Python 3.12.7 (64-bit)"."""
def venv_state(p: Paths) -> Own:
    """One of "running in .venv, matching the lock", ".venv differs from the lock", "no .venv",
    "running outside .venv"; from sys.prefix and .venv/datapiler-lock.sha256 against sha256(requirements.lock)."""
```

### 4.3 Status reads (CORE, `game.py`, `smithbox.py`, `status.py`)

```python
# game.py
GAME_EXES = ("eldenring.exe", "start_protected_game.exe")
EXPANSION_MARKERS: tuple[str, ...] = ()   # relative paths in the game folder; a hint on Status only (§10, P2; S21)

@dataclass(frozen=True)
class GameRunning:
    running: bool
    why: Own | None      # "eldenring.exe is running", "a program from the game's folder is running",
                         # "the process list could not be read"

def running(game_dir: str) -> GameRunning:
    """S7: running when a process named as in GAME_EXES exists (any case), or, with game_dir set, any process
    whose image lies inside game_dir. Fails closed: an unreadable process list counts as running. Never raises."""
def version(game_dir: str) -> str | None:
    """eldenring.exe's version resource, cached by the exe's size and mtime."""
def expansion(game_dir: str) -> bool | None:
    """A hint for Status only, never a decision: None until EXPANSION_MARKERS is set."""
def regulation_sha256(game_dir: str) -> str | None:
    """sha256 of regulation.bin (no decryption), recomputed only when its size or mtime_ns changes."""

# smithbox.py
SWITCH_KEY = "System_Enable_Soapstone_Server"
EXE_NAME = "Smithbox.exe"                  # to verify (§10, P1)

def startup_json() -> Path | None:
    """%LOCALAPPDATA%\\Smithbox\\Configuration\\Startup.json (ER08 §3.1), or None without LOCALAPPDATA."""
def read_switch(path: Path | None) -> bool | None:
    """The key's value, read only. None when the file or the key is missing or unreadable. Never writes."""
def installed(smithbox_dir: str) -> bool: ...
def build(smithbox_dir: str) -> str | None:
    """Smithbox.exe's version resource."""
def running(smithbox_dir: str) -> bool | None: ...
def open_project() -> str | None:
    """None in 0.1: where Smithbox records its open project is not established (§10, P1)."""

# status.py
class ProvenanceMissing(ValueError):
    """str(e) names what is missing in DataPiler's words: "the game's version is not known - set the game folder"."""

class Status:
    def __init__(self, settings: Callable[[], Settings], link: Callable[[], "LinkView | None"],
                 port_answers: Callable[[], bool | None]):
        """link is a callable because the Link is made after the Status (it takes status.game_running)."""
    def game_running(self) -> GameRunning: ...      # handed to Link and Runner
    def project_ok(self) -> tuple[bool, Own]:
        """False with the reason when the project folder is unset, missing, the game's folder or inside it."""
    def pills(self) -> dict: ...                    # /api/state "pills"
    def block_line(self) -> str | None: ...         # /api/state "block"
    def cards(self) -> dict: ...                    # /api/state "status"
    def provenance(self) -> dict:
        """{"game_version", "regulation_sha256", "expansion", "expansion_source", "language", "smithbox_build",
        "datapiler", "date"}; expansion is Settings' statement and expansion_source "owner" (S21); date is today's
        local date. The runner adds "names" (S22). Raises ProvenanceMissing, also while expansion is not stated."""
```

`LinkView` is the read side of LINK's `Link` (`state`, `stats()`, `would_call()`). Status reads are made on each
`/api/state` with the caches above; no poller. The port check is LINK's `port_answers` (§4.5), so every touch of
`127.0.0.1:22720` is in `link.py`.

The Status checks, by id, in the order of the mock (ok is `true` ✓, `false` ✗, `"warn"` amber, `null` not known):

- **smithbox:** `installed`, `build`, `running`, `switch` ("Its server is switched on", with "It has no password:
  switch it off when you are done"), `port` ("The server answers on 127.0.0.1:22720"), `project`.
- **game:** `folder`, `version`, `expansion` (the owner's statement in Settings; a file check adds a hint only, S21),
  `running`, `regulation`.
- **project:** `outside_game` (red ✗ and "Choose a project folder outside the game's" otherwise).
- **link:** the state, the calls made, the last call's time and methods; with the link off, what would be called;
  once the link has gone off with the switch still true, S9's line (worded as in §10, P7).

### 4.4 The HTTP server (CORE, `server.py`)

Copied from Jobrunner (§7.1) with DataPiler's names: `127.0.0.1` only; `Host` must be `127.0.0.1:<port>` or
`localhost:<port>`; every POST's `Origin` must be `http://127.0.0.1:<port>` or `http://localhost:<port>`; every
`/api/` request carries `X-DataPiler-Token` (the per-start token, `secrets.token_urlsafe(24)`, compared with
`hmac.compare_digest`). Headers on every answer: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy: same-origin`, and the CSP

```
default-src 'none'; script-src 'nonce-N'; style-src 'nonce-N'; connect-src 'self'; img-src 'self' data:;
base-uri 'none'; form-action 'none'; frame-ancestors 'none'
```

`server_version` is `DataPiler`. Request bodies: `/api/jobs/drop` at most 400 KB (a 256 KB job in base64), every
other POST at most 64 KB; a body is a JSON object. Errors: 400 `{"error": "..."}` for a refusal in DataPiler's words
(masked), 403 for the guard, 404, 413, 500 `{"error": "..."}` from `logbook.why`. A 403 closes the connection
(`Connection: close`): the refused request's body is never read, so a kept-alive connection must not carry another
request (found in integration). The page is assembled once per start
from `datapiler/page/`: `index.html` with its one `<style nonce>` (app.css) and one `<script nonce>` (app.js), the
nonce and the token put in by `str.replace` of `__NONCE__` and `__TOKEN__`.

### 4.5 The server link (LINK, `link.py`, `gamewatch.py`)

```python
HOST = "127.0.0.1"
PORT = 22720
ALLOWED = ("ListParams", "ListParamRows", "GetParamRows", "SearchObjects", "GetObject",
           "BatchGetObjects", "OpenResource")
MAP_RX = re.compile(r"m\d{2}_\d{2}_\d{2}_\d{2}")
MAP_BATCH = 10                      # S8

class LinkError(Exception):
    """A refusal or a failure; str(e) is DataPiler's words, safe to show and to log."""
class LinkOff(LinkError): ...       # the session's switch is off
class LinkBlocked(LinkError): ...   # the game is running
class LibsMissing(LinkError): ...   # grpcio or protobuf missing, or --no-link
class LinkDataError(LinkError): ... # the server sent something that is not a number where DataPiler reads one
class LinkCallError(LinkError):
    code: str                       # the gRPC status code's name only, never its details

def available() -> tuple[bool, Own]:
    """Whether grpc, protobuf and soapstone import, at the lock's versions. Imports them lazily. Never raises."""
def port_answers(game: Callable[[], GameRunning]) -> bool | None:
    """A TCP connect to 127.0.0.1:22720 within 0.5 s, closed at once, no bytes sent. None, with no connect made,
    while the game runs. Needs no grpc."""
def map_key(map_id: str) -> int:
    """"m12_34_56_78" -> 12345678. ValueError for anything not MAP_RX."""

@dataclass(frozen=True)
class Placement:
    map: int            # map_key
    entity_id: int
    npc_param_id: int
    talk_id: int
    model: int          # "c1234" -> 1234; -1 when the model is not of that shape (counted, never returned as text)

class Link:
    def __init__(self, game: Callable[[], GameRunning], *, libs: bool, _test_port: int | None = None):
        """libs False (from --no-link or available()) makes the state "no_libs" for good. The host is always HOST;
        _test_port exists for the fake server and is used nowhere outside tests/."""
    @property
    def state(self) -> str:
        """"off", "on", "blocked" or "no_libs"."""
    def switch(self, on: bool) -> str:
        """On: refused (state returned unchanged) with no_libs; "blocked" while the game runs; starts the watcher.
        Off: closes the channel and stops the watcher. Emits link.state."""
    def stats(self) -> dict:
        """{"calls": int, "last_call": "HH:MM:SS" or None, "last_methods": [method, ...]}."""
    def would_call(self) -> list[dict]:
        """[{"method": "ListParams", "for": "the names of the params"}, ...] for the Status card."""
    def list_params(self) -> list[str]:
        """Param names matching [A-Za-z0-9_]{1,64}; anything else is dropped and counted."""
    def list_param_rows(self, param: str) -> list[int]:
        """Row ids only; row names never leave this module."""
    def get_param_rows(self, param: str, row_ids: Sequence[int], fields: Sequence[str], *,
                       cancel: threading.Event | None = None,
                       progress: Callable[[int, int], None] | None = None) -> list[dict[str, int | float | bool]]:
        """One dict per row, {"id": row id, field: value}, only the fields asked; vanilla=True forced. Checks cancel
        between calls. Raises LinkDataError (naming the field's index) for a value that is not a number or a
        boolean, LinkError otherwise."""
    def loaded_maps(self) -> list[str]:
        """The map ids loaded in Smithbox's map view."""
    def map_ids(self) -> list[str] | None:
        """Every map id, if an allowed call lists them; None otherwise (§10, P5)."""
    def open_maps(self, map_ids: Sequence[str], *, cancel: threading.Event | None = None,
                  progress: Callable[[int, int], None] | None = None) -> int:
        """OpenResource for map resources only, MAP_BATCH at a time, waiting for each batch to show in
        loaded_maps(); returns how many are loaded. Asking the owner above ten is the runner's (S8)."""
    def placements(self, map_id: str) -> list[Placement]:
        """SearchObjects and BatchGetObjects on a loaded map: the placed characters, numbers only."""
    def close(self, why: Own) -> None:
        """Close the channel and stop the watcher; the switch goes off."""
```

Every call goes through one private function, `_call(method, request)`, which in this order: refuses a method not in
`ALLOWED`; checks the switch (`LinkOff`); checks `game()` afresh, not from the watcher's cache (`LinkBlocked`);
makes the call on the one channel with `channel.unary_unary("/<service>/<Method>", ...)` from a fixed table; counts
it; logs at DEBUG the method and counts, never data; emits `link.call`. The service's name and each method's request
and response classes come from the protos (`soapstone/SOURCE.md` records them, checked against ER08 §4.2).

```python
# gamewatch.py
class GameWatch:
    def __init__(self, game: Callable[[], GameRunning], on_change: Callable[[bool], None], interval: float = 2.0):
        ...
    def start(self) -> None:
        """A daemon thread: checks at once, then every interval; calls on_change(running) when it flips."""
    def stop(self) -> None: ...
```

While the link is on, the watcher runs. When the game starts, `Link` closes the channel at once, the state becomes
`blocked`, it logs WARN "the game started - the server link is closed" and emits `link.state`. When the game has been
closed for two checks in a row, the state returns to `on` (the session's switch is still on) and waiting work goes on.

### 4.6 The job format and its check (JOBS, `jobs.py`, `fields.py`)

Top-level keys: `format` (`"datapiler-job/1"`), `id` (`[a-z0-9][a-z0-9-]{2,63}`, not starting `extract-`, unique
among the jobs here), `title` (1 to 120 characters, no control characters), `ops` (1 to 64), and optionally `needs`
(`\d+\.\d+(\.\d+)?`, S13). Any other key is refused.

Names: tables (`as`, `rows`, `tables`) `[a-z][a-z0-9_]{0,31}`, each `as` used once, each reference to an earlier
op's `as`; fields `[A-Za-z][A-Za-z0-9_]{0,63}`; file names `paths.NAME_RX`. Column types inside the runner:
`int`, `number` (finite, S5), `bool`, `text_local` (only `join_names`'s `name`, never allowed in `write_share`).

| op | Arguments (all required unless marked) | Produces |
|---|---|---|
| `fetch_rows` | `as`; `param` (a key of `fields.PARAMS`); `fields` (1 to 32, each in `fields.PARAMS[param]`); `ids` (optional: 1 to 65,535 ints, or `{"from": int, "to": int}`) | the rows' `id` and fields |
| `load_maps` | `maps`: 1 to 2,000 ids matching `MAP_RX`, or `"all"` | nothing (Smithbox loads them) |
| `read_placements` | `as`; `maps`: ids, or `"all"` (the loaded maps) | `map`, `entityId`, `npcParamId`, `talkId`, `model` |
| `join_names` | `as`; `rows`; `key` (an `int` column); `text` (`"character_names"` or `"place_names"`) | `rows`' columns, `named` (bool), `name` (`text_local`) |
| `filter` | `as`; `rows`; `where` and `ids` (optional, at least one): `ids` 1 to 1,000 row ids (ints), matched against `key` (optional: the table's row id, `id` or `entityId`; `npcParamId` also for placements) | `rows`' columns |
| `count` | `as`; `rows`; `by` (optional, 0 to 8 `int` or `bool` columns); `where` (optional) | `by`'s columns and `count` |
| `distinct` | `as`; `rows`; `by` (1 to 8 `int` or `bool` columns) | `by`'s columns |
| `write_local` | `name`; `tables` (1 to 16); `columns` (optional, `{table: [column, ...]}`) | `workspace/local/<job id>/<name>.json` |
| `write_share` | `name`; `tables` (1 to 32); `columns` (`{table: [column, ...]}` for every table, no `text_local`); `notes` (optional, labels from `guard.LABELS`) | `share/<name>.json` through the guard |

`where`: an object of 1 to 16 conditions, all of which must hold: `{column: value}` for equality, or
`{column: {"eq"|"ne"|"lt"|"le"|"gt"|"ge": number or bool}}` or `{column: {"in": [1 to 1,000 numbers]}}`; columns of
type `int`, `number` or `bool` only. A job has at most one `write_share`; a `write_share` name used by another job is
refused. `"needs"` above `VERSION` is refused: "this job needs DataPiler 0.2 or newer; this is 0.1.0".

**Lineage (DP8, S18).** Every table carries its lineage (`jobs.Lineage`, kept on `Job.lineage`): *raw* as
`fetch_rows` and `read_placements` make it, and after a `filter`, `distinct` or `join_names` of a raw table;
*narrowed* by a filter keeping only the named rows (`named` true, `{"eq": true}` or `{"ne": false}`) of a table
`join_names` made, or by a filter with `ids`; an *aggregate* as `count` makes it, unless it counts a raw table by its
row id or by a column that holds other tables' ids (`fields.REFERENCES`: `nameId`, `msgId`;
`jobs.PLACEMENT_REFERENCES`: `npcParamId`, `talkId`, `model`), which stays raw (§10, P15). A narrowed or aggregate
table stays so through later filters, distincts and joins. `write_share` refuses a raw
table at `ops[i].tables[j]`, naming the operation and the rule (`jobs.DP8_RULE`). The lineage also gives the runner
what check 6 measures: the source op, its row-id column while the table keeps it, whether its rows are one per row
of the source, and the source's columns of ids (`refs`).

```python
# fields.py
PARAMS: dict[str, dict[str, str]] = {
    "NpcParam": {"id": "int", "nameId": "int", "teamType": "int", "npcType": "int"},
    "TalkParam": {"id": "int", "msgId": "int"},
    "WorldMapPlaceNameParam": {"id": "int"},     # more once verified (§10, P4)
    "BonfireWarpParam": {"id": "int"},           # likewise
}
REFERENCES: dict[str, tuple[str, ...]] = {       # the fields that hold other tables' ids (P15, S18)
    "NpcParam": ("nameId",), "TalkParam": ("msgId",), "WorldMapPlaceNameParam": (), "BonfireWarpParam": (),
}

# jobs.py
FORMAT = "datapiler-job/1"
MAX_BYTES = 256 * 1024
MAX_DEPTH = 16
MAX_OPS = 64
OPS = ("fetch_rows", "load_maps", "read_placements", "join_names", "filter", "count", "distinct",
       "write_local", "write_share")

@dataclass(frozen=True)
class Refusal:
    where: str           # "ops[3].fields[1]", "id", "(file)"
    text: str            # "`teamName` is not a field DataPiler reads (ids and numbers only)"
    op: int | None

class JobRefused(ValueError):
    refusals: list[Refusal]

@dataclass(frozen=True)
class Job:
    id: str; title: str; sha256: str; ops: tuple[dict, ...]; needs: str | None
    uses_link: bool               # any fetch_rows, load_maps or read_placements
    maps: int | None              # how many maps load_maps names; None for "all"
    share_name: str | None

def check(raw: bytes, *, known_ids: Collection[str], share_names: Mapping[str, str],
          builtin: bool = False) -> Job:
    """The checks of design §6 at once: a JSON object of at most MAX_BYTES, nesting at most MAX_DEPTH, the
    format, every key known, every op from OPS with its arguments of their types and ranges, names only (never a
    path), the id unique. builtin=True allows the "extract-" prefix (catalogue rows only). Raises JobRefused with
    every refusal found, each naming the field and the rule. A refusal quotes the job's own value only when it
    matches [A-Za-z0-9_.:-]{1,64}; otherwise it names the place alone."""

def preview(job: Job) -> dict[str, list[str]]:
    """{"reads": [...], "computes": [...], "writes": [...]} in DataPiler's words (below)."""
```

Preview wording, one line per op: `fetch_rows` "NpcParam rows: id, nameId, teamType, npcType" (and " - rows A to B"
or " - N rows"); `load_maps` "loads N maps in Smithbox - its view changes, not its data" (Reads); `read_placements`
"placed characters of N maps (or: of the loaded maps): entity, row, dialogue and model ids"; `join_names` "join npc
with the character names - local"; `filter` "keeps the rows of npc where ..." (with `ids`: "keeps the rows of npc whose id is one of 3 ids listed");
`count` "counts the rows of npc_named
per teamType, where named is true"; `distinct` "distinct teamType of npc"; `write_local` "workspace file
`npc-named.json`: 1 table (local)"; `write_share` "share file `roster-counts.json`: 1 table". Conditions read
"named is true", "teamType >= 6", "npcType in 3 values".

### 4.7 The catalogue (JOBS, `catalogue.py`)

```python
@dataclass(frozen=True)
class Row:
    id: str                       # "character_rows"
    name: str                     # "Character rows"
    help: str                     # the "?" text
    sources: tuple[str, ...]      # ("server",) or ("guided",)
    gives: str                    # "row ids, name numbers"
    goes_to: str                  # "workspace", or "workspace+counts": a counts-only summary to share too (S18)
    steps: tuple[str, ...]        # guided rows: the numbered steps, with <WORKSPACE> as a placeholder
    containers: tuple[str, ...]   # guided rows: the text containers it waits for
    needs_maps: bool

ROWS: tuple[Row, ...]             # character_rows, character_names, dialogue_links, map_placements, places, place_names
BUNDLES: dict[str, tuple[str, ...]] = {
    "roster": ("character_rows", "character_names", "dialogue_links"),
    "placements": ("map_placements",),
    "places": ("places", "place_names"),
    "everything": ("character_rows", "character_names", "dialogue_links", "map_placements", "places", "place_names"),
}

def ops_for(row_id: str) -> list[dict]:
    """A server row's built-in ops in datapiler-job/1 form: its full numbers by write_local to
    workspace/local/extract/<row id>.json, and at most a counts-only summary (never an id, DP8) by write_share to
    share/extract-<row id>.json. KeyError for a guided row."""
def public() -> dict:
    """GET /api/catalogue: {"rows": [...], "bundles": {...}}."""
```

The built-in jobs carry the id `extract-<row id>` and, as their `job.sha256`, the sha256 of their ops' canonical JSON.
The guided rows' steps follow design §2 and ER08 §4.2 item 4: open the Text Editor; choose the container; set the
Data Transfer tab's export directory to `<WORKSPACE>\inbox` (once); Export Text, Export Selected Container.

### 4.8 The runner (JOBS, `runner.py`)

One worker thread runs one thing at a time, jobs and Extract rows in the order they were started; server rows of an
Extract run go first. Everything is thread-safe behind one lock.

```python
class LinkLike(Protocol):        # the part of link.Link the runner uses
    state: str
    def list_param_rows(self, param: str) -> list[int]: ...
    def get_param_rows(self, param, row_ids, fields, *, cancel=None, progress=None) -> list[dict]: ...
    def loaded_maps(self) -> list[str]: ...
    def map_ids(self) -> list[str] | None: ...
    def open_maps(self, map_ids, *, cancel=None, progress=None) -> int: ...
    def placements(self, map_id: str) -> list["Placement"]: ...

class Runner:
    def __init__(self, paths: Paths, link: LinkLike, textdb: "TextDB", guard: "Guard",
                 provenance: Callable[[], dict], game: Callable[[], GameRunning], language: Callable[[], str]):
        ...
    def load_folder(self) -> None:
        """jobs/ at start: every card back; a job that was running shows "stopped" and is not resumed."""
    def add(self, filename: str, raw: bytes) -> tuple[dict, bool]:
        """Keep raw as jobs/<id>/job.json, check it, return (card, again). again is True when the same sha256 is
        here already (its card is returned, nothing duplicated). A refused job is a card too. Never raises for a
        bad job; ValueError for an empty upload."""
    def act(self, job_id: str, what: str, *, confirm_maps: int | None = None) -> dict:
        """what: "start", "cancel" or "remove". {"ok": True}, or {"ok": False, "ask": {...}} when Start would load
        more than ten maps and confirm_maps does not equal that number (S8). ValueError for an unknown id or what."""
    def run_extract(self, rows: Sequence[str], *, load_maps: bool = False,
                    confirm_maps: int | None = None) -> dict:
        """Queue the ticked rows (server rows first); guided rows show their steps and wait for the inbox.
        {"ok": True} or {"ok": False, "ask": {...}}. ValueError for an unknown row."""
    def cancel_extract(self) -> None: ...
    def cards(self) -> list[dict]: ...           # /api/state "jobs"
    def extract_state(self) -> dict: ...         # /api/state "extract"
    def made_by(self) -> dict[str, Own]:
        """Output files, relative to the workspace or the share folder, and what made each: a job id, "Extract"
        or "guided import"."""
    def busy(self) -> dict | None:
        """{"kind": "job" or "extract", "id": ..., "title": ...} while something runs."""
    def stop(self, *, cancel: bool, timeout: float = 3.0) -> None:
        """For Quit: cancel between calls, wait up to timeout."""
```

A job that uses the link waits while the link is off, blocked or without its libraries, and says which ("the server
link is off", "the game is running", "the server link needs its libraries - restart DataPiler and answer Y"); it
goes on when `link.state` turns `on`. Cancel stops between calls. A failed job writes no share file and names the op
and the reason; a guard failure names the check and the place, never the value. Each job logs to
`logbook.for_job(id)`. The share file goes through `Guard.write` only, with each table's row counts from the job's
lineage (S19): the game table each came from (the param, or `placements`) and its rows: for a `fetch_rows` source
the param's rows as `list_param_rows` gives them (called for an explicit `ids` list too when the job writes a share
file), each row id once, and whether a row id repeats among the rows read (an id may be held by more than one row);
for `read_placements` the placements of every map the job read, each map once. A table of counts alone is not
measured; a table keeping a param's row id, none repeating, is measured by its ids; every other one by its rows
(placements always). After the write the runner keeps them with `guard.record_counts`. `join_names` verifies the names' wrapper leads first (S22): fewer than
half of the joined rows' non-negative name numbers resolving, or none to try, fails the operation with the share.

### 4.9 The text database and the inbox (JOBS, `textdb.py`, `inbox.py`)

Smithbox's text export (ER08 §4.2): `{Name, SourceContainer, SourceCategory, FmgWrappers: [{Name, ID, Fmg: {Name,
Entries: [{ID, Text}], Version, BigEndian, Unicode}}]}`; `SourceContainer` is missing from older exports, so the
container is `SourceContainer`, else `Name`.

```python
# ER01's leads (§10, P3; S22): character names in wrappers 428, 328 and 18, place names in 429, 329 and 19, of the item
# containers, the live container and the newest layer first. join_names uses a set only once at least half
# (VERIFY_SHARE) of the joined rows' non-negative name numbers resolve in it.
LEAD_CONTAINERS = ("item_dlc02", "item_dlc01", "item")
LEADS = {"character_names": (428, 328, 18), "place_names": (429, 329, 19)}
VERIFY_SHARE = 0.5
TEXT_SETS: dict[str, tuple[tuple[str, int], ...]]   # "character_names" -> ((container, wrapper id), ...), from LEADS

@dataclass(frozen=True)
class ImportResult:
    container: str; language: str; wrappers: int; entries: int

class TextDB:
    def __init__(self, path: Path):
        """sqlite3, one connection behind a lock. Tables imports(container, language, wrappers, entries, sha256, at)
        and entries(container, language, wrapper_id, wrapper_name, entry_id, text), keyed by the first five."""
    def import_export(self, data: dict, *, container: str, language: str, sha256: str) -> ImportResult:
        """Replace that container's entries for that language. Empty texts are skipped. Emits textdb.changed."""
    def containers(self) -> list[dict]: ...      # container, language, wrappers, entries, imported time
    def ids(self, text_set: str, language: str) -> set[int]: ...
    def wrappers(self, text_set: str) -> list[int]: ...   # for provenance.names
    def names(self, text_set: str, language: str) -> dict[int, str]:
        """Local only: for write_local, never for a share file."""
    def text_hit(self, s: str) -> bool:
        """Check 3 for one string: it equals a text, case-folded; or, at 4 or more characters, it is contained in a
        text; or it contains a text of 4 or more characters."""
    def find_in(self, haystack: str) -> bool:
        """Whether any text of 4 or more characters occurs in haystack, case-folded: an index of texts by their
        first four case-folded characters, probed at each position (for log lines and share strings alike)."""
    def entries(self) -> int: ...
    def close(self) -> None: ...

class NotAnExport(ValueError):
    """str(e) is the reason the page shows: "not a Smithbox text export", "not a Smithbox text export of `item`",
    "a text export in another language than Settings' (engus)"."""

def check_export(data: object, *, expected: Collection[str], language: str) -> tuple[str, str]:
    """(container, language) by shape alone (S10), never by file name. Raises NotAnExport."""

class Inbox:
    MAX_BYTES = 64 * 1024 * 1024
    def __init__(self, paths: Paths, textdb: TextDB, language: Callable[[], str],
                 expected: Callable[[], set[str]]):
        ...
    def start(self) -> None: ...                 # a daemon thread, every second
    def stop(self) -> None: ...
    def poll_once(self) -> list[dict]:
        """Take each .json in the inbox whose size has not changed since the last poll; import it and move it to
        imported/ under DataPiler's own name, or leave it with its reason. For tests and the thread."""
    def state(self) -> list[dict]:
        """[{"file": name, "reason": ...}]: the files left in the inbox, for the page only (never logged)."""
```

### 4.10 The guard and the share file (JOBS, `guard.py`)

The share file (design §6, with S5's `number`):

```json
{
  "format": "datapiler-share/1",
  "job": {"id": "en-0007-roster-counts", "sha256": "<64 hex: the job file as dropped>"},
  "provenance": {"game_version": "<a.b.c.d>", "regulation_sha256": "<64 hex>", "expansion": true,
                 "expansion_source": "owner", "language": "engus",
                 "names": {"character_names": {"wrappers": [428, 328, 18], "verified": true, "resolved": 0.95}},
                 "smithbox_build": "<a.b.c>", "datapiler": "0.1.0", "date": "2026-11-08"},
  "tables": [
    {"name": "per_team", "columns": [{"name": "teamType", "type": "int"}, {"name": "count", "type": "int"}],
     "rows": [
      [0, 112],
      [6, 48]
     ]}
  ],
  "notes": ["named_only"]
}
```

Keys in that order; written pretty with each row on one line, so the viewer shows the file's exact bytes. Column
types: `int`, `number` (finite, S5), `bool`, `enum:<name>` (a key of `ENUMS`), `label`. `expansion` is the owner's
statement and `expansion_source` says so (S21); `names` holds, for each text set the job joined, the wrapper leads
verified at `join_names` and the lowest share of name numbers that resolved, rounded down (S22), and is `{}` when the
job joined no names. 0.1 is unreleased, so these keys join `datapiler-share/1` before any file of it exists.

```python
SHARE_FORMAT = "datapiler-share/1"
LABELS: tuple[str, ...] = ("named_only", "vanilla_rows", "loaded_maps_only", "summary")   # ours; snake_case ASCII
ENUMS: dict[str, tuple[str, ...]] = {"source": ("server", "guided")}
MAX_BYTES = 4 * 1024 * 1024
MAX_VALUES = 200_000

@dataclass(frozen=True)
class CheckResult:
    check: int            # 1 to 6
    name: str             # "Shape", "Values", "Text", "The owner", "Size", "Coverage"
    ok: bool
    where: str | None     # the first failing place, e.g. "tables[1].rows[40][2]", "notes[0]", "provenance.language"

class GuardFailed(Exception):
    check: int
    where: str            # str(e) == "check 3 at tables[1].rows[40][2]"

@dataclass(frozen=True)
class ShareWritten:
    name: str; size: int; sha256: str

class Guard:
    def __init__(self, textdb: TextDB, owner_words: Callable[[], list[str]]):
        """owner_words: the user name and the PC name (from winapi), never logged."""
    def build(self, *, job_id: str, job_sha256: str, provenance: dict, tables: list[dict],
              notes: Sequence[str]) -> bytes:
        """The share file's bytes, in the order and layout above."""
    def check(self, data: bytes, *, declared: Mapping[str, Sequence[str]],
              coverage: Mapping[str, tuple[str | None, int, str] | None] | None = None) -> list[CheckResult]:
        """All six checks; never raises. declared: {table: [column, ...]} as the job's write_share names them.
        coverage: check 6's input, {table: None (counts alone) or (row-id column or None for the rows, rows of the
        game table, the game table's name)}; without it check 6 fails."""
    def write(self, share_dir: Path, name: str, data: bytes, *, declared: Mapping[str, Sequence[str]],
              coverage: Mapping[str, tuple[str | None, int, str] | None] | None) -> ShareWritten:
        """Check, then write atomically only if all six pass. Raises GuardFailed naming the first failing check;
        nothing is written. Logs (source guard) and emits share.written or guard.failed."""
    def check_labels(self) -> list[int]:
        """S6: the indices of LABELS found in the text database; also run at start against check 4."""

def fixed_words() -> frozenset[str]: ...    # what check 3 skips where a value is exactly one of them (S20)
def owner_patterns(words: Sequence[str]) -> list[re.Pattern]: ...   # check 4's, and Copy for sharing's (S26)
def record_counts(path: Path, file_name: str, sha256: str, coverage: Mapping) -> None: ...   # workspace, by sha256
def counts_for(path: Path, file_name: str, sha256: str) -> dict | None: ...   # None: not written by DataPiler as is
```

The checks, all of them run over the bytes, the first failure stopping the write:

1. **Shape.** Parses as JSON; exactly the keys above; `format` is `SHARE_FORMAT`; `job.id` matches `jobs.ID_RX` or
   `extract-<row id>`; `job.sha256` and `regulation_sha256` 64 lower-case hex; `game_version` and `smithbox_build`
   `\d{1,5}(\.\d{1,5}){1,3}`; `language` `[a-z]{2,8}`; `date` `\d{4}-\d{2}-\d{2}`; 1 to 32 tables, each with a name,
   1 to 64 columns and rows of exactly that many cells; tables and columns exactly as declared, in order.
2. **Values.** Each cell of its column's type: `int` a JSON integer (not a boolean, magnitude below 2^63); `number`
   a finite number (NaN and infinities refused, S5); `bool`; `enum:<name>` a value of that enum; `label` one of
   `LABELS`. Each note one of `LABELS`. No other string anywhere.
3. **Text.** Every string value in the file: `TextDB.text_hit` false. The format's own keys are not read (check 1
   fixes them), and a value exactly one of DataPiler's fixed words (`fixed_words()`: `LABELS`, S6, the column types
   and enum values, the column names its operations make, the expansion's source and the format constant) is
   skipped (S20). Each value is compared case-folded as it is, then normalised (accents dropped, every run of
   spaces, `_`, `-` and other signs one space) against the texts normalised the same way (S25). An empty text
   database passes, with a WARN once per write.
4. **The owner.** Every string, `LABELS` included: no `\`, no `/` (the format constant aside), no drive letter
   (`(?<![A-Za-z])[A-Za-z]:([\\/]|$)`), no `~`, no user or PC name as a whole word, case-folded, whatever signs
   stand between its parts (`owner_patterns`, S26), and no IP address.
   The IP rule skips `game_version` and `smithbox_build`, whose shape check 1 fixes (a four-part version looks like
   an IPv4 address; §10, P8).
5. **Size.** At most `MAX_BYTES` bytes and `MAX_VALUES` values (cells and notes).
6. **Coverage** (DP8, S19). The tables of one game table, together, cover at most half of its rows (a param's rows
   as Smithbox lists them, or the placements of the maps read, each map once), as the runner hands them over: their
   distinct row ids, counted once across the tables measured by id (a param's `id` where none repeats among the rows
   read), plus the rows of those measured by rows (one per source row, or one per group of a count or a
   distinct). Only a table of counts alone is not measured. A table
   without counts fails, so `/api/share` and Outputs read them back with `counts_for` (by file name and sha256,
   `datapiler-share-counts/2`) and a file DataPiler did not write never passes. The failure names the table at which
   its game table passes half, `tables[i]`, never a value.

### 4.11 Start and stop (CORE, `datapiler.py`)

Command line: `python datapiler.py [--console] [--port N] [--no-browser] [--no-link]`. `--console`: this console is
the app's own (colours, the close event); `--no-browser`: the launcher opens the page; `--no-link`: the owner answered
N, so grpc is never imported.

Start, in this order:

1. Resolve the root (the folder of `datapiler.py`), load settings, resolve the paths.
2. `winapi.backend().hold_mutex("Local\\DataPiler", paths.mutex_file)`. Held by another: read its port with the
   adapted `running_port()` (§7.1), print "DataPiler is running already: http://127.0.0.1:<port>/" and exit 3.
3. Remove any `datapiler.port` (a file left by a killed run; the launcher's second-start wait relies on this).
4. `paths.ensure`; `logbook.setup`; `logbook.set_masks`; `env` lines (Python, venv state, the libraries).
5. `TextDB`, `Guard` (labels against check 4, then against the text database, S6), `Status`,
   `Link(status.game_running, libs=not no_link and link.available()[0])`, `Runner.load_folder()`, `Inbox.start()`.
   `Runner` and `Inbox` are given `lambda: live.paths`, not the Paths of the start, so a workspace or share folder
   moved in Settings is the one written to.
6. Bind `127.0.0.1` on `--port`, else the setting, else any free port. Failure: start log and exit 2.
7. The token, the nonce, the hosts and origins; write `datapiler.port` atomically; log INFO "Page:
   http://127.0.0.1:<port>/ (the browser opens it)".
8. `winapi.on_console_close(stop)`; then `serve_forever(poll_interval=0.5)`; Ctrl+C is a Quit.

Stop (Quit, the window's close, Ctrl+C), once: emit `app.stopping`; `link.close`; `runner.stop(cancel=True)`;
`inbox.stop`; `guard.close`; `textdb.close`; remove `datapiler.port` if it holds our port; log "stopped"; `logbook.shutdown`;
release the mutex; exit 0. The window's close logs "window closed - stopping" first.

Exit codes: 0 stopped; 1 a crash; 2 the page's port did not open; 3 already running. A failure before step 7 writes
`datapiler-start.log`: the time, the exception's type and its masked traceback, `env.python_info()` and
`env.venv_state()`.

### 4.12 The window's script and the launcher's contract (PACK, LINK, CORE)

**`requirements.lock`** (LINK) starts with this header, which `DataPiler.ps1` reads:

```
# datapiler-lock/1
# pythons: 3.10 3.11 3.12 3.13
# download-mb: 12
# grpcio <version> Apache-2.0
# protobuf <version> BSD-3-Clause
```

then one `name==version` line per package, each with a `--hash=sha256:<64 hex>` for every win_amd64 wheel of the
listed Pythons (continued with `\`). Only grpcio and protobuf (and a dependency, if one is needed with `--no-deps`,
listed in the header the same way). The pythons, the size and the versions are LINK's to fill from what PyPI
publishes; protobuf is at least the version the generated code requires.

**The venv marker** (PACK writes, CORE and LINK read): after pip succeeds, `DataPiler.ps1` writes
`.venv/datapiler-lock.sha256`, the lower-case hex sha256 of `requirements.lock`'s bytes and a newline. A `.venv`
without it, or with another hash, "does not match the lock".

**`DataPiler.ps1`** (PACK), ASCII only, runs on Windows PowerShell 5.1 and PowerShell 7:

1. Sets the title **DataPiler** and the colours; prints the banner with the version read from
   `datapiler/__init__.py`.
2. Finds Python: `py -3`, then `python`; 3.10 or newer, else says so plainly and stops. A Python not in the lock's
   `# pythons:` line: names the supported ones and runs with `--no-link`.
3. No `.venv`, or one not matching the lock: prints the two packages, their versions and licences, the size, "from
   pypi.org over https", and waits for **Y** or **N**. Y: removes a mismatched `.venv`, `python -m venv .venv`, then
   `.venv\Scripts\python.exe -m pip install --isolated --disable-pip-version-check --no-input --require-hashes
   --only-binary=:all: --no-deps -r requirements.lock`, then the marker. N or a failed install: runs with
   `--no-link`, saying what N means.
4. Runs `<python> datapiler.py --console` in the same window, adding `--no-browser` when started with
   `-FromLauncher`, and `--no-link` as above.
5. Exit code 0: "DataPiler has stopped - this window closes in 5 s". 3: "DataPiler is running already - its page
   opens", then 5 s. Anything else: the code, and "press Enter to close".

**The launcher** (PACK) and the app share two names: the mutex `Local\DataPiler` and the file `datapiler.port`
(ASCII digits, written atomically by the app once the page is up, removed at its start and its stop).

---

## 5. The API

All under the guard of §4.4; JSON in and out. Words in answers are DataPiler's, masked.

### GET

| Path | Answer |
|---|---|
| `/` | the page |
| `/api/state` | the state below; the page reads it every second, and three failures in a row show "DataPiler has stopped" |
| `/api/catalogue` | `catalogue.public()`: `{"rows": [{"id", "name", "help", "sources", "gives", "goes_to", "steps"}], "bundles": {"roster": [...], ...}}` |
| `/api/outputs` | `{"workspace": [file], "share": [file]}`, file = `{"name": "local/en-0007-roster-counts/npc-named.json", "size": 245760, "time": "2026-11-08 08:43", "made_by": "en-0007-roster-counts"}` |
| `/api/share?name=roster-counts.json` | `{"name", "size", "sha256", "text": "<the file's exact text>", "checks": [{"check": 1, "name": "Shape", "ok": true, "where": null}, ...]}`; the guard's six checks are run again on the bytes, check 6 with the row counts kept for that file at that sha256 |
| `/api/log?after=<seq>` | `{"lines": [{"seq", "t", "level", "src", "msg"}], "last": <seq>, "first": <oldest seq kept>}` |
| `/api/settings` | `{"settings": {...§4.1}, "server": "127.0.0.1:22720", "session": {"link": false, "debug": false}}` |

`/api/state`:

```json
{
  "version": "0.1.0",
  "pills": {"smithbox": "running", "game": "closed", "link": "on"},
  "block": null,
  "status": {
    "smithbox": [{"id": "installed", "ok": true, "text": "Installed in <SMITHBOX>", "fix": null,
                  "detail": "<the real folder: page only>"}],
    "game": [{"id": "running", "ok": true, "text": "Not running", "fix": null, "detail": null}],
    "project": [{"id": "outside_game", "ok": true, "text": "Outside the game's folder", "fix": null, "detail": null}],
    "link": {"state": "on", "calls": 142, "last_call": "08:41:58", "last_methods": ["ListParamRows", "GetParamRows"],
             "would_call": [{"method": "ListParams", "for": "the names of the params"}], "after": null}
  },
  "extract": {
    "running": "dialogue_links",
    "rows": [{"id": "character_rows", "state": "done", "grey": null, "progress": null,
              "result": {"count": 2105, "unit": "rows", "secs": 0.4}, "error": null},
             {"id": "dialogue_links", "state": "running", "grey": null,
              "progress": {"done": 312, "of": 820, "unit": "rows"}, "result": null, "error": null},
             {"id": "character_names", "state": "waiting_export", "grey": null, "progress": null,
              "result": null, "error": null},
             {"id": "map_placements", "state": "idle", "grey": "load the maps in Smithbox first",
              "progress": null, "result": null, "error": null}],
    "ask": null,
    "inbox": [{"file": "export.json", "reason": "not a Smithbox text export of `item`"}]
  },
  "jobs": [{"id": "en-0007-roster-counts", "title": "Roster: named characters per team", "format": "datapiler-job/1",
            "sha256": "<64 hex>", "state": "checked", "refusals": [],
            "preview": {"reads": ["NpcParam rows: id, nameId, teamType, npcType"], "computes": ["..."],
                        "writes": ["share file `roster-counts.json`: 1 table"]},
            "wait": null, "ops": [{"n": 0, "op": "fetch_rows", "state": "waiting", "done": 0, "of": null,
                                   "unit": "rows", "secs": null}],
            "result": null}],
  "outputs_rev": 7,
  "session": {"link": true, "debug": false, "libs": true}
}
```

Pills: `smithbox` running, not_running or not_found; `game` closed, running or unknown; `link` off, on, blocked or
no_libs. Row states: idle, queued, running, done, failed, waiting_export, cancelled. Job states: refused, checked,
queued, waiting, running, done, failed, cancelled, stopped. A refusal is `{"op": 3, "where": "ops[3].fields[1]",
"text": "..."}`; `wait` is the reason a started job waits; a done job's `result` is `{"share": {"name", "size",
"sha256"} or null, "local": ["npc-named.json"], "failed": null}`, a failed one's `"failed": {"op": 2, "why": "...",
"check": 3 or null, "where": "tables[1].rows[40][2]" or null}`.

### POST

| Path | Body | Answer |
|---|---|---|
| `/api/quit` | `{"cancel_running": false}` | `{"ok": true}`, then the stop of §4.11; or `{"ok": false, "ask": {"text": "A job is running (en-0007-roster-counts). Quit cancels it between calls."}}` |
| `/api/link` | `{"on": true}` | `{"ok": true, "state": "on"}`, or `{"ok": false, "state": "...", "why": "..."}`; switching on is refused while `status.project_ok()` is false, the game runs, or the libraries are missing |
| `/api/debug` | `{"on": true}` | `{"ok": true}` |
| `/api/extract/run` | `{"rows": ["character_rows"], "load_maps": false, "confirm_maps": null}` | `{"ok": true}` or `{"ok": false, "ask": {"maps": 98, "text": "..."}}` |
| `/api/extract/cancel` | `{}` | `{"ok": true}` |
| `/api/jobs/drop` | `{"name": "job.json", "data": "<base64>"}` | `{"ok": true, "card": {...}, "again": false}` |
| `/api/jobs/act` | `{"id": "...", "what": "start", "confirm_maps": null}` | `{"ok": true}` or `{"ok": false, "ask": {...}}` |
| `/api/open` | `{"area": "workspace"}` or `"share"` | `{"ok": true}` or `{"ok": false, "error": "Opening a folder works on Windows only."}` |
| `/api/copy-path` | `{"name": "roster-counts.json"}` (share files only) | `{"ok": true}`: the real path is put on the clipboard by `winapi`, never sent to the page |
| `/api/settings` | `{"settings": {...}}` | `{"ok": true, "next_start": ["port"]}` or 400 `{"error": "...", "field": "project_dir"}`; emits `settings.saved` |
| `/api/log/share` | `{"after": 0, "upto": 1234, "levels": ["INFO", "WARN", "ERROR"], "sources": ["link"]}` | `{"ok": true, "text": "..."}`, or `{"ok": false, "refused": {"check": 3, "line": 1187}}` (S11: checks 3 and 4 over each line, `TextDB.find_in` and the owner rules) |

---

## 6. The page (CORE)

Built from the mock, which shows every tab's layout; its made-up states become the data of §5. The mock's
"(mock)", its note and its static states go; the version comes from `/api/state`.

- **Top bar:** "DataPiler 0.1", the three pills, Quit (with the question of `/api/quit`); the block line under it.
- **Status:** the four cards of §4.3; placeholders shown, the real folder only in the "?" title.
- **Extract:** the bundle chips (a chip ticks its rows; a row ticked by hand clears the chip's highlight); the table
  of `/api/catalogue` with each row's state from `/api/state` (it scrolls sideways inside its card on a narrow
  window, never the page); guided steps open in place; greyed rows with the reason behind their "?"; Run and Cancel;
  the map question (S8) as a confirm with the number.
- **Jobs:** the drop zone and Choose file (uploads only, 256 KB at most); a card per job as in the mock: title, id,
  format, sha256 (short), Reads / Computes / Writes, refusals, Start (Start again once done, failed, cancelled or
  stopped) / Cancel / Remove, op lines while it runs, the result with Show (to Outputs).
- **Outputs:** two panes (*Local only - never share* in red, *Passed the guard* in green), Open folder, the viewer
  (the exact text, its sha256, each check ✓), Copy path.
- **Terminal:** `/api/log?after=` every second; level chips (INFO+, WARN+) and source chips; Pause scroll; Copy
  visible (the browser's clipboard, the lines being masked); Copy for sharing (`/api/log/share` first).
- **Settings:** the form of §4.1, Save, the fixed server address (shown from `/api/settings`' `server`, so the port is
  written in `link.py` only), Server link this session, and DEBUG to the file this session.

Rules: one script and one style, both with the nonce; no inline event attribute, no `<link>`, no image or font from
anywhere; all data put into the page through `textContent` or Jobrunner's `esc()`; British spelling.

---

## 7. What is copied from Jobrunner, and by whom

From the owner's LLM Jobrunner 1.2 (outside the repository; its location is in the brief), read with `sed` or `grep`,
never run. Copied under DataPiler's MIT licence (DP7), with the README line naming Jobrunner as the source. Never
copied: its servers and PandorumLLM parts (`panel_*`, `srv_log`, the `Runner`'s server code), the payload feed, the
result zip, the remote-PC and LAN features, and the three LAN example lines (`llm_jobrunner.py` 101, 103 and 1677,
which the privacy sweep flags).

### 7.1 CORE, from `llm_jobrunner.py`

| Jobrunner (lines) | Into | Change |
|---|---|---|
| `write_atomic` (152-158) | `fileio.write_atomic` | none |
| `start_log` (161-166) | `datapiler.py` | adds the Python and the venv's state; masked |
| `__main__` block (2073-2081) | `datapiler.py` | the start log on a crash before the page is up |
| `App` (1231-1238) | `server.App` | none |
| `Handler.send` (1249-1267) | `server.Handler.send` | `server_version` DataPiler; `img-src 'self' data:` |
| `Handler.guard` (1269-1278) | `server.Handler.guard` | the header `X-DataPiler-Token` |
| `do_GET` (1280-1308), `do_POST` (1310-1383) | `server.Handler` | the frame only: guard first, length cap, JSON object, `Bad` as 400, `OSError` as 500, 404; the `/api/quit` branch (1339-1342: answer, then shutdown on a thread); DataPiler's endpoints in `api.py` |
| `Server` (1386-1388) | `server.Server` | none |
| `running_port` (1391-1405) | `datapiler.py` | used only when the mutex is held |
| `main` (1408-1456) | `datapiler.py` | the bind, nonce, hosts, origins, port file and `finally` (remove our own port file); with the mutex, the logbook, the close event, no browser when the launcher opens it |
| `Bad` (61-62) | `server.Bad` | none |
| page CSS: `:root` tokens (1466-1470), tabs and panes (1499-1506), drop zone (1530-1535), terminal (1578-1581), shade and modal (1588-1594) | `page/app.css` | merged with the mock's CSS, which already shares the tokens |
| page HTML: the "has stopped" shade (1661-1662) | `page/index.html` | DataPiler's words |
| page JS: `$`, `esc`, `store` (1711-1716); `api()` (1718-1722); `note()` (1724-1731); `showTab()` (1735-1741) | `page/app.js` | the token header renamed; the zip branch dropped |
| page JS: `lineCls`, `linesHtml`, `paintTerm`, `pollTerm` (1848-1881) | `page/app.js` | one log source, `/api/log?after=`; the level from the line's field, not a pattern; filters added |
| page JS: `addFiles` (1973-1988), drop listeners (2055-2061), `poll` (1991-2004), Quit (2045-2049) | `page/app.js` | 256 KB cap, `/api/jobs/drop`; the heartbeat (three failures show the shade) |

`said` and `CUT_RX` (56, 65-67) are not copied: DataPiler never shows or logs a library's own words (`logbook.why`).

### 7.2 JOBS, from `llm_jobrunner.py`

| Jobrunner (lines) | Into | Change |
|---|---|---|
| `_depth` (224-235) | `jobs.py` | the limit 16, not 32 |
| `_strings` (238-248) | `guard.py` | walks keys and values with their places (`tables[1].rows[40][2]`) |
| `ID_RX` (45) | `jobs.py` | DataPiler's pattern (§4.6) |
| `Runner.add` (900-937): sha256 on arrival, the file kept as dropped, the same file again recognised, a refused item becoming a card | `runner.Runner.add` | `jobs/<id>/job.json`; the same file again shows its card, nothing resumes; no folder titles by date |

### 7.3 PACK, from Jobrunner's `launcher-src/` and `BUILD.md`

- **`launcher.cpp`** (97 lines): `ExeDir` (18-23), `FindOnPath` (25-29), `Ticks` (31-33) and `FreshPort` (35-49)
  unchanged. `wWinMain` (51-97) rewritten for DataPiler: first `OpenMutexW(SYNCHRONIZE, FALSE, L"Local\\DataPiler")`;
  held: wait up to 60 s for `datapiler.port` to exist (no freshness rule: the running app removed any old one at its
  start), open `http://127.0.0.1:<port>/`, exit 0. Not held: `DataPiler.ps1` must exist beside the exe; find
  `pwsh.exe` on PATH, else `powershell.exe`; start
  `"<ps>" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "<folder>\DataPiler.ps1" -FromLauncher` with
  `CREATE_NEW_CONSOLE`, in DataPiler's folder; wait up to 60 s for a fresh port (`FreshPort`, 2 s slack); open the
  page; else "DataPiler did not start - its window says why". No pythonw route, no `CREATE_NO_WINDOW`, no socket.
- **`app.rc`** (27 lines): DataPiler's names, `FILEVERSION 0,1,0,0`, "0.1.0.0", `LegalCopyright` exactly as
  `LICENSE`'s holder line, Comments naming `launcher-src/launcher.cpp` and Jobrunner as its source; the `ICON` line
  dropped (no icon in 0.1; Jobrunner's icon is never reused).
- **`app.manifest`** (24 lines): the name `DataPiler.Launcher`, the description; `asInvoker`, the supported OS
  entries and `dpiAware` unchanged.
- **`BUILD.md`** (18 lines): the MinGW-w64 commands with DataPiler's file names and the same flags, the `file` and
  version checks, then the Actions route (S4) and how to compare the release's sha256 with a local build.
- **The README's SmartScreen note**, in Jobrunner's README's spirit (its lines 27-28), in our words.

### 7.4 NOTICE (PACK)

DataPiler, MIT. grpcio, Apache-2.0, downloaded at the first start from PyPI and never shipped (PACK reads its licence
files in the wheel, including the third-party notices it carries, and lists them). protobuf, BSD-3-Clause, likewise.
SoapstoneLib, MIT, "Copyright (c) 2022 thefifthmatt", its full notice (as `soapstone/LICENSE`), for the generated
`soapstone/*_pb2.py`. The launcher and the page parts of §7.1 to §7.3, from LLM Jobrunner 1.2, the owner's own code,
under DataPiler's licence. Each licence is read before it is listed.

---

## 8. The test plan

One command, standard library only: `python3 -I -m unittest discover -s tests` from the repository root. The link
tests skip cleanly (`unittest.skipUnless`) when grpcio is missing; LINK runs them in a venv under the brief's build
folder with grpcio and protobuf. Windows-only tests skip on Linux and run in CI on Windows. Tests write only into
`tempfile.TemporaryDirectory()` folders, never into the repository.

### 8.1 CORE

- `test_fileio`: no temporary file left; replace over an existing file; `read_limited` past its limit.
- `test_logbook`: the exact line format; DEBUG only to the file and only with `set_debug`; console and ring INFO and
  up; the ring capped at 5,000; rotation with a tiny `max_bytes` keeps `keep` files; the separator line; a job log
  file; formatting never raises.
- `test_masking`: each placeholder, either slash, any case, an 8.3 form from a fake backend, longest first (a
  workspace inside DataPiler's folder masks as `<WORKSPACE>`); `<USER>` and `<PC>` as whole words only; IPv4 and
  IPv6 masked, `127.0.0.1` kept; a plain `str` argument shows as `<text>`.
- `test_log_templates`: an `ast` scan of `datapiler.py` and every `datapiler/**/*.py`: every log call's template is a
  string literal; no f-string, `.format` or `%` operator in its arguments; every `get("...")` source is in `SOURCES`;
  every template formatted with a planted invented name in each argument never shows the name.
- `test_settings`: defaults; an unknown key refused; each range; a project folder inside the game's refused (temp
  folders); a round trip; the session's switches never saved.
- `test_paths`: `is_inside` (sibling prefixes, case on Windows); `NAME_RX` refusals.
- `test_winapi`: the portable backend's documented answers; on Windows, the test's own process is listed, a second
  `hold_mutex` returns None, `python.exe` has a file version.
- `test_status`: folders built in a temp folder (an empty `eldenring.exe`, a `regulation.bin` of invented bytes,
  `Startup.json` with the switch true, false, missing and broken); fake process lists; S7 (by name, by path inside
  the game's folder, an unreadable list counting as running); the hash computed once until the file changes;
  `ProvenanceMissing`; `read_switch` never opens the file for writing.
- `test_server`: a wrong Host, a POST without Origin, a missing or wrong token: 403; the headers and the CSP on every
  answer; 413 past the caps; a body that is not an object: 400; 404; the server bound to `127.0.0.1` only; a 403
  closes a kept-alive connection, so the next request on it is not read from the refused one's body.
- `test_page`: the assembled page has exactly one `<script nonce=` and one `<style nonce=`, no `http://` or
  `https://` address, no `<link`, no `on...=` attribute, no `<img`.
- `test_api`: every endpoint of §5 with fakes (a fake `Runner`, `Link`, `Status`, `TextDB`): the JSON shapes; link
  switching refused when the project check fails, the game runs or the libraries are missing; Quit asks while a job
  runs; copy-path puts the real path on a fake clipboard and answers no path; `/api/log/share` refuses a line holding
  a planted text and a line holding an IP.
- `test_start`: `main()` in a thread with a temp root and `--port 0`: the port file written after the bind and
  removed at stop; an old port file removed at start; a second `main()` exits 3.
- `test_integration` (phase 2, skips without grpc): the real modules, the fake Soapstone server, an invented text
  export dropped in the inbox, the design's example job dropped and started: a share file whose checks all pass, a
  job log, and no planted name in the ring, the files or the share file; then the share folder moved in Settings and
  the job started again, its share file in the new folder. It supplies invented values for P2 and P3 (§10), which
  0.1 leaves unconfirmed.

### 8.2 LINK

- `tests/fake_soapstone.py` (not a test module): an in-process gRPC server on `127.0.0.1` at a free port, built with
  `grpc.method_handlers_generic_handler` for the seven allowed methods only, so any other method answers
  UNIMPLEMENTED. Invented data: `NpcParam` and `TalkParam` with a few dozen rows (ids from 9000000, invented numbers,
  invented row names to prove they never come out), one cell of text to prove `LinkDataError`, maps
  `m99_00_00_00` to `m99_00_00_14`, placements with models `c9990`. It records every call and its request
  (`vanilla`, the resource kind).
- `test_link_static` (always runs): `ALLOWED` is the seven; every method path in `link.py`'s table names one of them;
  no other method name of the service (read from `soapstone/SOURCE.md`'s full list) appears in any `.py` file outside
  `soapstone/*_pb2.py` and `tests/`; no `*_pb2_grpc.py` anywhere; `grpc`, `google.protobuf` and `soapstone` are
  imported only by `datapiler/link.py`, `soapstone/` and LINK's tests, and inside functions only in `link.py`;
  `22720` appears only in `link.py`; `_test_port=` only under `tests/`; `vanilla` only ever `True`.
- `test_link` (skips without grpc): off: `LinkOff`, the fake sees no call; the game running: `LinkBlocked`, no call;
  rows and ids as numbers; `vanilla=True` on every `GetParamRows`; a text cell: `LinkDataError`; row names never
  returned; `open_maps` in batches of ten, map resources only; placements as numbers, `c9990` as 9990; the watcher
  closing the channel within one interval of the game starting (no further call reaches the fake), `blocked`, the
  event, and back to `on`; `stats`; the ring holds methods and counts, never the fake's planted strings.
- `test_gamewatch`: flips reported once each; `stop` ends the thread.
- `test_lock`: the header of §4.12; every requirement `==`-pinned with at least one `--hash=sha256:`; only the
  packages the header names; the header's versions match the pins.

### 8.3 JOBS

- `test_jobs_check`: the design's example job passes; each refusal from a fixture, with its exact text, e.g.
  "ops[3].fields[1]: `teamName` is not a field DataPiler reads (ids and numbers only)"; not JSON, too large, too deep,
  the wrong format, an unknown key, an unknown op, a path-like name, an `as` used twice, a later table referenced, two
  `write_share`, a `text_local` column in `write_share`, `needs` above 0.1.0, an id used twice, the `extract-` prefix;
  a value that is not identifier-shaped is never quoted.
- `test_jobs_preview`: the example job's lines exactly as §4.6 words them.
- `test_schema`: the schema parses, is draft 2020-12, has `additionalProperties: false` on every object; its op list
  equals `jobs.OPS`; each op's properties and required lists equal `jobs`'s argument table; every fixture agrees.
- `test_runner`: a fake link of its own with invented rows: ops in order with progress; waiting while the link is
  off and while the game runs, going on at `link.state`; Cancel between calls; a failure writes no share file; the job
  log; state saved and loaded (running becomes stopped); Extract server rows before guided rows; the map question
  above ten; Remove.
- `test_guard`: share documents built in code (never fixture files, §8.5): a good one passes; each check fails with
  its number and place (an extra key; columns not as declared; a string in an `int` column; NaN; a boolean as an
  `int`; an unknown enum value or label; a text equal, contained or containing; an exact label skipped (S6); `\`,
  `/`, a drive letter, `~`, a planted user name and PC name, an IP; the format constant and the versions passing;
  too many bytes, too many values); a failure leaves the share folder unchanged; no message carries the value;
  `check_labels` finds a label planted in the text database.
- `test_textdb`: an import, a re-import replacing it, `ids` and `names`, `text_hit` and `find_in` cases.
- `test_inbox`: a good export imported and moved under DataPiler's name; a good export under a misleading file name
  accepted, a bad one named `item.json` refused (S10); a wrong container; a wrong language; a file still growing left
  for the next poll; a file over the limit refused.
- `test_catalogue`: every server row's ops pass `jobs.check(builtin=True)`; the bundles as design §6; no built-in
  `write_share` table carries a fetched column.

### 8.4 PACK

- `test_repocheck`: temp trees: a file under the top-level `workspace/`, `share/`, `logs/` or `jobs/` fails (the same names deeper, such as `tests/fixtures/`, do not); a `.json` whose
  `format` is `datapiler-share/1` fails; the same string in a `.md` passes; an IP other than `127.0.0.1` fails; a
  clean tree passes.
- `test_launcher_src`: `launcher.cpp` names `Local\\DataPiler`, `pwsh.exe` before `powershell.exe`,
  `-ExecutionPolicy Bypass`, `-NoProfile`, `-FromLauncher`, `CREATE_NEW_CONSOLE` and a 60 s bound, and has no
  `pythonw`, `CREATE_NO_WINDOW` or socket call; the manifest says `asInvoker`; `app.rc`'s version matches `VERSION`.
- `test_ps1`: the pip flags of §4.12; the Y question before `-m venv`; no `Set-ExecutionPolicy`, `Invoke-WebRequest`,
  `Invoke-RestMethod`, `Start-BitsTransfer` or `curl`; the version read from `datapiler/__init__.py`; the branches for
  0, 3 and other codes; ASCII only.
- `test_workflows`: every action pinned by a 40-hex commit; the release workflow runs only on tags, makes a draft,
  asks for `contents: write` in that job only; the checks run the test command on `ubuntu-latest` and
  `windows-latest`, and the Windows job installs from `requirements.lock` with the flags of §4.12 for the link tests.

### 8.5 Fixtures

Invented only: names like "Quillon Marrowgate" or "the Lamplighter of Corrow", numbers from 9000000, map ids in
`m99`, models `c999x`. Never game data, never a path of any machine, never an IP but `127.0.0.1`. JOBS owns
`tests/fixtures/job-files/` (good and bad jobs, one refusal each, named for it) and `tests/fixtures/text-exports/`
(Smithbox-shaped exports of invented texts). No fixture file is a share file (S14's check would rightly refuse it):
share documents are built in code. No fixture folder is named `workspace`, `share`, `logs`, `jobs` or `exports`
(`.gitignore` and S14 cover those names). Each builder plants its own invented name in its own tests.

---

## 9. What each builder must not do

**Everyone:**
- write a file this plan gives to someone else, or a file it does not name (ask the lead);
- commit, push, publish or post anything;
- run, build or import anything from the Jobrunner copy or any other untrusted copy, or copy its LAN, remote-PC or
  PandorumLLM parts;
- put game data, game text, a path of this machine, a user or machine name, an owner detail, or an IP other than
  `127.0.0.1` in code, tests, fixtures, docs or log lines; or an assistant model identifier in any file;
- use a library beyond the standard library, except grpcio and protobuf in `link.py` and `soapstone/` (and
  grpcio-tools in a venv under the brief's build folder, never in the repository);
- put `str(exception)`, a job's title, a refusal's text, a file name DataPiler did not make, or any text from Smithbox
  or a job into a log line or an event;
- reach any network at run time but `127.0.0.1` (the page) and `127.0.0.1:22720` (the link);
- change a rule of the design, S1 to S14 or DP1 to DP7; a point they leave open goes to the lead (§10).

**CORE:** connect to `127.0.0.1:22720` itself (only `link.port_answers` and `Link` do); write any Smithbox file
(`Startup.json` is read only) or anything in the game's folder; scan the PC for installs (the folders come from
Settings); send a real path to the page except a Status check's `detail`; let the page load anything from elsewhere;
keep the link or debug switch across starts; implement any part of the job check, the guard or the link's gate.

**LINK:** generate or import a gRPC stub; build a method path from input; take an address or port from settings, the
command line or the page; call a method outside the seven; pass `vanilla=False` or anything but a map resource to
`OpenResource`; return or log a row name, a cell that is not a number, or any string from the server but checked
param names; write `Startup.json`; clone Smithbox or fetch anything of it beyond SoapstoneLib's `.proto` files and
`LICENSE`; commit the `.proto` files; install grpcio anywhere but a venv under the brief's build folder.

**JOBS:** evaluate, template or run anything from a job; accept a path, or write outside `jobs/`, `workspace/` and
`share/` (logs go through `logbook.for_job`); let a `text_local` column reach a share table; write a share file other
than through `Guard.write`; accept a text export by its file name, or move a refused one; weaken a guard check beyond
S5 and S6; quote a job's value in a refusal unless it is identifier-shaped; put a share document in a fixture file.

**PACK:** change the PC's execution policy (only the one process's `-ExecutionPolicy Bypass`), ask for elevation,
embed Python or probe a socket in the exe; reach the network in the script except pip after **Y**, and pip only with
`--require-hashes --only-binary=:all: --no-deps`; reuse Jobrunner's icon; publish a release from CI (a draft, on the
owner's tag); use an action not pinned by commit; name the owner anywhere beyond what `LICENSE` already holds.

---

## 10. Open points for the lead

Facts this plan does not have, and small calls it leaves to the lead. None is guessed in code: each sits behind one
named constant or returns "not known". A point settled since is marked **Closed**, with the S entry that settles it;
its first text is kept.

- **P1. Smithbox's open project and its process name.** ER08 establishes only `Startup.json` and its switch. Where
  Smithbox records its open project is not known, so 0.1 checks the project folder set in Settings and
  `smithbox.open_project()` returns None. `EXE_NAME = "Smithbox.exe"` is to be confirmed. **Closed (2026-11-08,
  0.2.0):** the process name is a fact on the owner's PC: Smithbox 2.2.6 runs as `Smithbox.Vulkan.exe`, and the same
  folder holds `Smithbox.OpenGL.exe` (`Smithbox.exe` stays a lead). From 0.2.0 DataPiler recognises Smithbox by any
  exe named `Smithbox*.exe`, in any case, everywhere (`smithbox.EXE_RX`): the folder check, the process watcher
  (DP15), the build read from the running exe's version resource (else the one the folder's exes share), the
  provenance, Detect and the picker's mark. Where Smithbox records its open project is a lead in 0.2.0
  (`sbproject`, smithbox-projects.md; build plan 0.2 §10 P1): `open_project()` reads its record's mark and informs
  Status only, and the link's project question stays.
- **P2. The expansion's files.** `game.EXPANSION_MARKERS` is empty until the files whose presence means the expansion
  is installed are confirmed on the owner's install. Until then `expansion` is null and every share write is refused
  by `ProvenanceMissing`: this blocks the tag, not the build. **Closed (S21, fix round 2):** the owner states it in
  Settings (Expansion installed: yes or no, not stated at first); a share write waits for the statement and the
  provenance records it with `expansion_source` `owner`. The marker files, once confirmed, only add a hint on Status.
- **P3. The text exports.** Whether Smithbox's text JSON names its language (and in which key), the wrapper ids of
  the character and place names in `item`, `item_dlc01` and `item_dlc02` (`TEXT_SETS`), and the container of the
  place names. To read at the pinned commit (`FmgExporter.cs`, `StoredFmgContainer.cs`) and to confirm on the
  owner's first import. Until then the language comes from Settings and the steps say to export in it. **Closed in
  part (S22, fix round 2):** ER01's wrapper ids are built in as leads (428, 328 and 18; 429, 329 and 19, of the item
  containers, which hold the place names too) and verified with the owner's own numbers at each `join_names`; the
  provenance records the share that resolved. Still open: whether the text JSON names its language.
- **P4. The places' fields.** `fields.PARAMS` has `id` only for `WorldMapPlaceNameParam` and `BonfireWarpParam` until
  their numeric fields are confirmed from the server's own answers on the owner's PC (EldenNet O48).
- **P5. Listing maps.** Whether an allowed call lists every map (for `"all"`) and which object properties give the
  placements' numbers: from the protos (LINK). If no allowed call lists maps, `"all"` is refused in 0.1 and maps are
  named by id. **Closed (S17):** no allowed call lists every map, so `load_maps` names its maps by id;
  `read_placements` with `"all"` reads the maps loaded in Smithbox.
- **P6. Access to Smithbox's repository.** In this session `gh api repos/vawser/Smithbox/...` was refused (403:
  GitHub access to that repository is not enabled). LINK needs read access attached before it can fetch the protos;
  the commit to pin is ER08's `e2dbcae`, unless the lead names another. **Closed (the build):** the four files were
  read at `e2dbcae` from GitHub's raw file host, as `soapstone/SOURCE.md` records.
- **P7. S9's wording.** ER08 §3.1 found no switch for the server in Smithbox's app at `e2dbcae`, so the Status line
  says to set `System_Enable_Soapstone_Server` to `false` in Smithbox's `Startup.json` and restart Smithbox, rather
  than design §7.5's "in Smithbox's settings".
- **P8. Check 4 and the versions.** A four-part version such as the game's looks like an IPv4 address. The plan
  exempts `game_version` and `smithbox_build`, by field, from the IP rule only, their shape being fixed by check 1.
  To confirm, or to put to the owner.
- **P9. Whole columns.** The request forbids a whole param column in a share file; the guard has no check for it.
  The built-in rows write summaries only, but a job could still share every row id through `distinct`. A sixth check,
  or a rule in the job check, would need an S entry or a DP question. **Closed (DP8; S18 and S19, fix round 2):**
  both: the job check's lineage rule and the guard's check 6. **Note, fix round 3:** the second review found the
  close premature: a `count` of a raw table by a column of ids listed that column (P15), check 6 left counts and
  distincts unmeasured, measured each table alone, and measured placements by entity ids that can repeat. Now a count
  by a column of ids stays raw, and check 6 measures every table but counts alone, by rows (or by a param's row ids
  where none repeats), with the file's other tables from the same game table (S18, S19).
- **P10. The release as a draft.** S4 attaches the exe to "the release"; the plan makes it a draft, so publishing
  stays the owner's act.
- **P11. No icon in 0.1.** The brief allows a simple icon of ours or none; none keeps a binary out of the
  repository.
- **P12. Check 3 over the share format's own keys (blocks real use).** Check 3 runs over every string, keys included,
  and "contained in a text, at 4 or more characters" then matches the format's own keys and column names inside
  ordinary words: `name` in "named", `rows` in "arrows", `count` in "counted". One ordinary description in the text
  database refuses every share file (at `tables[0].name`, the key). The invented names of the end-to-end run did not
  trip it; `test_guard.test_p12_...` shows it and is marked as an expected failure until this is settled. JOBS's
  suggestion, as an S entry like S6: check 3 skips the strings check 1 has already fixed to DataPiler's own vocabulary
  (the format's keys, the column types, and column names that are `fields.PARAMS` fields or op-made columns), and
  keeps checking table names, job ids and labels. The guard stays as written (fails closed) until the lead decides.
  **Closed (S20, fix round 2):** check 3 reads values only, and skips a value that is exactly one of DataPiler's fixed
  words (the labels, the column types and enum values, the column names its operations make, the expansion's source,
  the format constant); `test_guard`'s P12 test passes, beside one with ordinary words that hold the keys.
- **P13. Three libraries, not two.** grpcio needs `typing-extensions` (PSF-2.0) with `--no-deps`, so the lock, the
  window's question, NOTICE and README name three; DP4's accepted cost and the page's and the API's words ("its two
  libraries") name two. A DP note, and the wording, are the lead's. **Closed (S23, fix round 2)** for the wording:
  README, NOTICE, the page and the window's question say "grpcio and protobuf, and typing-extensions, which grpcio
  needs", and the waits say "its libraries". DP4's own text still names two: a dated note there is the owner's
  record to make, if wanted.
- **P14. "Jobs on what is already in the workspace".** Design §4's answer N says jobs on what the workspace holds still
  work, but no 0.1 operation reads the workspace: every job starts with `fetch_rows` or `read_placements` and waits
  for the link. README now says so; the design's line is the lead's to amend. **Closed (fix round 2):** README,
  CHANGELOG and the window's N line (`DataPiler.ps1`) say that every job reads from Smithbox first and so waits for
  the link; design 0001 stays as received.
- **P15. A count by a reference column (fix round 2).** S18 counts every `count` as an aggregate unless it counts by
  a raw table's own row id. A count of a raw table by another column that holds ids (`nameId`, `msgId`, or a
  placement's `npcParamId`, `talkId` or `model`) lists that column's distinct values, with counts, and check 6 does
  not measure an aggregate. DP8 forbids "a raw table or column straight from Smithbox": whether such a count is one
  (and so whether `fields.PARAMS` should mark the columns that hold ids) is the lead's call, or a DP question.
  **Closed (S18, fix round 3):** it is one. `fields.REFERENCES` marks the params' columns of ids (`nameId`, `msgId`)
  and `jobs.PLACEMENT_REFERENCES` the placements' (`npcParamId`, `talkId`, `model`); a count of a raw table by one of
  them, or by its row id, stays raw and is refused at `write_share`, naming the column. Such a count still goes to the
  workspace, and a count of picked or named rows by them is an aggregate as before.
- **P16. An explicit list in `fetch_rows` (fix round 2).** S18 follows the brief: `fetch_rows` makes a raw table even
  when it names its rows by an explicit list of ids, so a job filters by the same `ids` again to share them. Counting
  `fetch_rows`'s explicit list (never its range) as narrowed would save that step; the lead's call.
- **P17. Check 6 across share files, and placements per map (fix round 3).** Check 6 measures each share file on its
  own (S19): several jobs, each sharing under half of one game table, can between them share more. Measuring with
  the files already in `share/` would make a file's answer change after it is written, and miss files moved out of
  the folder. Likewise the placements' bound is the placements of the maps the job chose to read, so a job that reads
  many maps can share every placement of a few; measuring per map would need each share table to keep `map` or the
  counts file to carry per-map counts. Both are the lead's call.

---

## 11. Done means

- **CORE:** the app starts with `python datapiler.py --console --port 0` on Linux and Windows, serves the page with
  every tab live against fakes or the real modules, stops cleanly by Quit, Ctrl+C and the close event, and passes
  §8.1; the integration test passes with grpcio.
- **LINK:** `soapstone/` generated with its licence and `SOURCE.md`, `requirements.lock` filled and hash-checked,
  `link.py` and `gamewatch.py` passing §8.2 with and without grpcio.
- **JOBS:** the example job and every built-in row check, preview and run against a fake link; the guard and the
  inbox pass §8.3; the schema agrees with the code.
- **PACK:** the launcher source builds with the `BUILD.md` commands (cross-compiled where MinGW-w64 is to hand, or in
  CI), the script and workflows pass §8.4, and `README.md`, `NOTICE` and `CHANGELOG.md` say what 0.1 is.
- **All:** every file swept clean, British spelling in what the owner reads, nothing committed.

---

## 12. The integration run (phase 2, 2026-11-08)

`datapiler.py --no-browser --port 0` was run end to end on Linux (the adapter's portable fallback) from a copy of the
tree, against the fake Soapstone server on the server's own port, and driven through its page in headless Chromium at
1280 and 400 px: every tab rendered with no console or page error and no request outside `127.0.0.1`; a request
without the token, with another Host or without this page's Origin was refused (403); Settings were saved through the
form, the link switched on, three invented text exports imported through the guided inbox (a fourth, not an export
but named `item.json`, left with its reason), an invented job dropped on the drop zone and run, its share file shown
in the viewer with checks 1 to 5 passed, the Terminal copied for sharing, and Quit stopped the app with exit code 0
and the port file removed. Afterwards each share file passed the guard again against the run's own text database, and
no invented name was in the share folder, the logs or the job folders.

Three facts had to be supplied, invented, for a share file to be written at all: the expansion's marker files (P2),
the names' wrapper ids (P3), and the two exes' version resources, which the portable fallback does not read (it
answers "not known", and the share write is then refused, correctly, with the reason). Run as it is on Linux, the
same job fails at `join_names` with P3's reason and Extract's Character rows at `write_share` with the version's.

**Fix round 2 (2026-11-08).** The same run, against this round's tree, with one fact supplied: the version resources.
The expansion was stated through the Settings form (P2, S21), and the invented text exports carried ER01's wrapper ids
(18, 328 and 428), which `join_names` verified (two in three of the invented name numbers resolve; P3, S22). Besides
the job above, a job sharing a raw table was refused on arrival with DP8's rule on its card, and one sharing three
picked ids ran and wrote its share file; every share file showed checks 1 to 6 passed in the viewer, and passed all
six again afterwards with the row counts kept in the workspace. Run with the expansion not stated, every share write
was refused with the line saying where to state it; run as it is on Linux, with the version's reason.

**Fix round 3 (2026-11-08, the second review).** The same three runs, against this round's tree, came out the same:
the three share files passed all six checks again with their kept counts, now each with its source (`NpcParam`; the
per-team count measured by its groups, the picked rows by their rows, as the invented NpcParam holds one row id
twice), and no invented name was found outside the workspace.
