# DataPiler 0.2.0: the build plan

*For the two builders of DataPiler 0.2.0 and the lead who commits their work (2026-11-08). Built from design 0002
([0002-design.md](0002-design.md), its mock [0002-mock.html](0002-mock.html)) as the owner adopted it: DP13 (no
record of programs started; Smithbox found from its running process; the project and game folders from Smithbox's
own record of the open project, Steam's library list as a cross-check; the expansion's app id read from the owner's
manifest, never assumed), DP14 (Mask paths on this page, off by default) and DP10 (one `DataPiler` folder in the zip).
It builds on 0.1 as built: [build-plan.md](build-plan.md) and the code it names. Design 0001, `settled.md` S1 to S26
and DP1 to DP14 still bind; what this plan settles is §9, to go into `settled.md` as S27 onwards.*

The two builders work at the same time in the same working tree, each writing only the files §1 gives them:

- **UPDATE**: the update button end to end: `datapiler/update.py` (the one network module), `datapiler/install.py`,
  `update-helper.py`, `/api/update` and `/api/update-result` (behind the routes FOLDERS puts in `api.py`, §3.3), the
  pop-up (`page/update.js`, `page/update.css`), `datapiler.py`'s start and stop (exit 75, the port after an update,
  the install check, the wiring of both builders' parts), `DataPiler.ps1`'s update path, the launcher's "updating"
  message, the release workflow's manifest and helper, the version bump, and the documents.
- **FOLDERS**: Detect and the picker end to end: the Windows adapter's new calls, Steam's files
  (`datapiler/steam.py`), Smithbox's project record (`datapiler/sbproject.py`, built from the research already in
  [smithbox-projects.md](smithbox-projects.md), §6), detection (`datapiler/detect.py`), the check lines and the picker's API
  (`datapiler/dirs.py`), `/api/dirs` and `/api/dirs/new` and the other folder endpoints, the settings' new keys and
  project rules, the mask-paths switch, Status's new lines, and the page: the Settings rows, the picker, and the shared
  page seams (§3.2).

Nobody edits another builder's file, not even to fix an import: a builder who needs a change asks the lead. Where
this plan names something "to verify", no builder guesses it: §10 lists those points.

---

## 0. Order of work

1. **Phase 0, both, short.** Each writes the seams the other runs against (§3), then tells the lead:
   - FOLDERS: the two log sources and `logbook.learn_found`; `server.assemble` over several page files; `#btn-update`
     in the top bar; `overlay()` and `holdHeartbeat()` in `app.js` with the overlay's CSS; the `Api` constructor's
     two new arguments and the three update routes; `test_page.py` and `test_api.py` made to pass with them
     (`test_api.py` reads the version from `datapiler.VERSION`, not a literal).
   - UPDATE: `datapiler/update.py` with `Updater`'s constructor and its public methods answering an idle view;
     `page/update.js` (an empty IIFE) and `page/update.css` (a comment); the version bump (§4.12) with every test it
     breaks outside FOLDERS's files.
2. **Phase 1, both in parallel**, against §3 to §6.
3. **Phase 2, integration.** UPDATE wires `detect.Folders` and `update.Updater` into `datapiler.py` and extends
   `tests/test_integration.py`; FOLDERS fixes mismatches in its own files.
4. **Phase 3, the lead.** The privacy sweep over every file written, `python3 -I tools/repocheck.py`, the full test
   run (`python3 -I -m unittest discover -s tests`, and with the brief's venv), then the commit.

Each builder's report to the lead: the files written, the test commands and their last lines, the sweep's result
(`privsweep.py files FILE...` from EldenNet's `tools/privsweep/`), and any §10 point met.

---

## 1. Files and their owners

Every file 0.2.0 adds or changes, with its one owner. A file not listed is nobody's in this build.

| Path | Owner | New or changed |
|---|---|---|
| `datapiler/__init__.py` | UPDATE | `VERSION = "0.2.0"` |
| `datapiler/update.py` | UPDATE | new: the check, the download, its proofs, the install request (§4.1) |
| `datapiler/install.py` | UPDATE | new: pending and result files, the install check, the start's clean-up, the helper loaded as a module (§4.5) |
| `update-helper.py` | UPDATE | new, at the repository's root: the swap and the restore, standard library only (§4.6) |
| `tools/manifest.py` | UPDATE | new: writes `manifest.sha256` for a folder (the release workflow, tests) |
| `datapiler.py` | UPDATE | the port after an update, exit 75, the install check, the clean-up, both builders' parts wired (§4.8) |
| `DataPiler.ps1` | UPDATE | `-AfterUpdate`, exit 75, the helper, `.venv.new`, the R prompt (§4.9) |
| `launcher-src/launcher.cpp` | UPDATE | "DataPiler is updating - see its window" (§4.10) |
| `launcher-src/app.rc`, `launcher-src/app.manifest` | UPDATE | the version 0.2.0.0 |
| `.github/workflows/release.yml` | UPDATE | the manifest in the zip, the helper's own check of the zip (§4.11) |
| `.github/workflows/checks.yml` | UPDATE | Windows: a venv made as `.venv.new` and renamed works (§4.11) |
| `tools/repocheck.py` | UPDATE | `update/` and `manifest.sha256` as run-time files |
| `.gitignore` | UPDATE | `/update/`, `/manifest.sha256`, `/.venv.new/`, `/.venv.prev/`, `*.dpnew` |
| `datapiler/page/update.js`, `datapiler/page/update.css` | UPDATE | new: the Update… pop-up (§4.7) |
| `README.md`, `CHANGELOG.md`, `BUILD.md` | UPDATE | 0.2.0; the button; the first update by hand; FOLDERS's part from §4.12 |
| `docs/release-notes/0.2.0.md` | UPDATE | new (§4.12) |
| `docs/design/settled.md` | UPDATE | S27 onwards, as §9 words them |
| `tests/test_update.py`, `test_update_static.py`, `test_archive.py`, `test_helper.py`, `test_install.py`, `test_manifest_tool.py`, `test_page_update.py` | UPDATE | new (§7.1) |
| `tests/test_start.py`, `test_ps1.py`, `test_launcher_src.py`, `test_workflows.py`, `test_repocheck.py`, `test_integration.py` | UPDATE | extended (§7.1) |
| `tests/test_jobs_check.py`, `tests/fixtures/job-files/bad-needs-newer.json`, and any other test outside FOLDERS's that names 0.1.0 as this version | UPDATE | the version bump's fallout only: a `needs` above 0.2.0, comparisons read from `VERSION` |
| `datapiler/winapi.py` | FOLDERS | `registry_value`, `drives`, `windows_dir`, `hidden`, `local_appdata` (§5.1) |
| `datapiler/steam.py` | FOLDERS | new: the KeyValues parser, Steam's install path, libraries and app manifest (§5.2) |
| `datapiler/sbproject.py` | FOLDERS | new: Smithbox's record of its projects, read only, as smithbox-projects.md §6 says (§5.3) |
| `docs/design/smithbox-projects.md` | nobody | the research, already written (leads, O48): an input. A build finding that contradicts it goes to the lead |
| `datapiler/detect.py` | FOLDERS | new: `Folders`, every source of §5.4, detection at start |
| `datapiler/dirs.py` | FOLDERS | new: the check lines, the picker's listing, New folder (§5.5) |
| `datapiler/smithbox.py` | FOLDERS | `open_project()` from `sbproject` |
| `datapiler/settings.py` | FOLDERS | `mask_paths`, `recent`, the project rules, unknown keys at load (§5.6) |
| `datapiler/status.py` | FOLDERS | "Found n places", the project rules, the open project (§5.8) |
| `datapiler/logbook.py` | FOLDERS | the sources `update` and `folders`; `learn_found` (§3.1) |
| `datapiler/api.py` | FOLDERS | the folder endpoints, the update routes, the mask (§3.3, §6) |
| `datapiler/server.py` | FOLDERS | `assemble` over `PAGE_JS` and `PAGE_CSS` (§3.2) |
| `datapiler/page/index.html`, `app.js`, `app.css` | FOLDERS | the shared seams (§3.2); the Settings rows and the mask switch (§5.9) |
| `datapiler/page/folders.js` | FOLDERS | new: the rows' behaviour and the picker (§5.9) |
| `tests/test_steam.py`, `test_sbproject.py`, `test_detect.py`, `test_dirs.py` | FOLDERS | new (§7.2) |
| `tests/fixtures/steam/*`, `tests/fixtures/smithbox/*` | FOLDERS | new, invented: VDF and ACF files, Smithbox records in the shape §5.3 establishes |
| `tests/test_api.py`, `test_settings.py`, `test_status.py`, `test_page.py`, `test_server.py`, `test_masking.py`, `test_winapi.py`, `test_logbook.py` | FOLDERS | extended (§7.2) |

`game.py` is unchanged (its `version` serves the check line; `EXPANSION_MARKERS` stays empty, S21). `paths.py` is
unchanged: `install.py` names the update folder's files relative to the root.

---

## 2. The folder at run time: what 0.2.0 adds

```
<DATAPILER>/
  manifest.sha256        release only: every shipped file's sha256 (S28); read at each start (the install check)
  update-helper.py       shipped; only ever run as the copy taken from a verified download
  update/                UPDATE's, and nothing is written outside it by the button but the swap itself
    <version>/DataPiler-<version>.zip      the download (.part while it arrives); removed at the next page-up
    <version>/update-helper.py             extracted at Install, checked against the zip's manifest
    pending.json         written at Install; removed by the returning app once its page is up
    result.json          written by the helper; served once by /api/update-result
    backup-<from>/       backup.json, manifest.sha256 (the old one), files/<path>; only the latest kept
  .venv.new/             DataPiler.ps1, while a changed venv is built
  .venv.prev/            DataPiler.ps1: the old venv after an update, until the new version's page has come up
  logs/update.log        the helper's lines, and R's
  <file>.old             a file held during the swap; listed in backup.json, removed at the next page-up
  settings.json          gains mask_paths and recent (§5.6)
```

---

## 3. The seams

### 3.1 Log sources and the found-folder mask (FOLDERS, `logbook.py`)

```python
SOURCES = ("app", "page", "smithbox", "link", "extract", "job", "guard", "textdb", "env", "update", "folders")

def learn_found(folders: Iterable[str]) -> None:
    """Adds candidates Detect found to this session's mask as <FOUND>, after the named folders (longest first), so a
    candidate that is not yet a setting never reaches a line. Never cleared during a run; never saved."""
```

| Source | Owner | Used for |
|---|---|---|
| `update` | UPDATE | each outbound call (host and path, the status, the seconds), the check's and the download's outcome, Install, the install check at start, the clean-up. The helper writes `logs/update.log` in the same line format with this source |
| `folders` | FOLDERS | each Detect (the folder, the count, the sources; never a path), the picker at DEBUG (counts only), a Steam or Smithbox file that could not be read (its kind and `why`) |

The template rule is 0.1's (§3.3 of build-plan.md; `test_log_templates.py` enforces it over the new modules too).

### 3.2 The page (FOLDERS)

- **Assembly.** `server.PAGE_JS = ("app.js", "folders.js", "update.js")` and `server.PAGE_CSS = ("app.css",
  "update.css")`. `assemble` joins each tuple's files with a newline into the one `<style nonce>` and the one
  `<script nonce>`; a missing file is an error. The page still has one script and one style (test_page).
- **Top-level names.** `app.js` stays top-level: its functions are the page's shared API (`$`, `api`, `note`, `el`,
  `add`, `clear`, `qm`, `mark`, `fmtN`, `fmtSize`, `showTab`, `store`, `TOKEN`). `folders.js` and `update.js` are
  each one IIFE, `(() => { ... })();`, defining nothing global.
- **`#btn-update`.** `index.html`'s top bar gains, just before `#quit`:
  `<button id="btn-update" title="Ask GitHub for the latest DataPiler release - only when pressed">Update…</button>`.
  FOLDERS writes the markup; `update.js` adds its listener.
- **The overlay.** One frame for the picker and the pop-up, in `app.js`, with its CSS in `app.css`:

  ```js
  // Opens the one overlay (a second call closes the first). Esc and its × close it; focus is kept inside while it is
  // open and returns to opts.opener (else the element that had focus) when it closes; onClose runs on every close.
  // Returns the parts to fill: box (.modal), body (.mb), foot (.mf); and close().
  function overlay(title, opts) -> { box, body, foot, close }   // opts: { opener, onClose, wide }
  ```

  Classes: `.ov` (the shade, `.ov.on` shown), `.modal`, `.mh` (title and ×), `.mb`, `.mf` (buttons), `.x`. UPDATE
  styles only what it puts inside, with classes prefixed `up-`; FOLDERS's own are prefixed `pk-` (picker) and `fr-`
  (the rows). The modal's look and focus handling may come from Jobrunner on DP7's terms, or be written afresh.
- **`holdHeartbeat(on)`** in `app.js`: while on, `poll()`'s failures never show "DataPiler has stopped". UPDATE turns
  it on at Install and leaves it on until the page reloads.
- **`SOURCES`** in `app.js` lists the same eleven sources as `logbook.SOURCES` (a test compares them).

### 3.3 The API's constructor and the update routes (FOLDERS, `api.py`)

```python
class Api:
    def __init__(self, *, live, status, link, runner, textdb, guard, inbox, catalogue, stop, libs,
                 updates: "update.Updater | None" = None, folders: "detect.Folders | None" = None): ...
    def close(self) -> None:
        """As now, then updates.close() and folders.close() when given."""
```

The routes, and nothing else of `api.py`, reach UPDATE's code; with `updates` None each answers 404:

| Route | Calls | Answer |
|---|---|---|
| `GET /api/update` | `self.updates.get()` | 200 and the dict |
| `GET /api/update-result` | `self.updates.result()` | 200 and the dict |
| `POST /api/update` | `self.updates.post(body)` | the `(code, answer, after)` triple as it is |

### 3.4 `datapiler.py`'s wiring (UPDATE writes it; FOLDERS's interface)

In step 5 of the start, after `Status`, `Link`, `Runner` and `Inbox`:

```python
self.folders = parts.folders(live)            # RealParts: detect.Folders(live)
self.updates = parts.updater(self)            # RealParts: update.Updater(root=..., version=VERSION, ...), §4.1
self.api = Api(..., updates=self.updates, folders=self.folders)
```

Once the page is up (after `datapiler.port` is written; §4.8): the install check, `updates.came_back(...)`,
`install.remove_pending`, `install.cleanup`, then `self.folders.at_start()`. A fake `parts` without `folders` or
`updater` (the older tests') gives `None` for that part.

---

## 4. UPDATE

### 4.1 `datapiler/update.py`: the only network module (S27)

```python
REPO = "Pt0l3my/DataPiler"
LATEST = "https://api.github.com/repos/Pt0l3my/DataPiler/releases/latest"
PAGE_PREFIX = "https://github.com/Pt0l3my/DataPiler/releases/"
ASSET_PREFIX = "https://github.com/Pt0l3my/DataPiler/releases/download/"
HOSTS = ("api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
TIMEOUT = 15.0; CACHE_SECS = 600; CHUNK = 64 * 1024; REDIRECTS = 5
API_MAX = 1024 * 1024; SHA_MAX = 1024; NOTES_MAX = 20_000; ZIP_MAX = 256 * 1024 * 1024
POLL_GONE = 5.0          # a download stops when the pop-up has not read GET /api/update for 5 s (S27)

@dataclass
class Answer:
    status: int
    headers: dict[str, str]                  # names lower-cased
    body: BinaryIO                           # read(n) -> bytes
    def close(self) -> None: ...

Fetch = Callable[[str, Mapping[str, str], float], Answer]   # (url, headers, timeout); raises OSError on no answer

def allowed(url: str) -> bool:
    """https, a host in HOSTS exactly (no port, no user, no fragment), nothing else."""
def real_fetch() -> Fetch:
    """urllib.request with its default proxy handler (HTTPS_PROXY) and ssl.create_default_context(); redirects are
    not followed by urllib: a 3xx comes back as an Answer, and _request follows it."""
def _request(fetch: Fetch, url: str, *, max_bytes: int) -> Answer:
    """Every URL and every Location checked with allowed() before it is asked; at most REDIRECTS; https throughout.
    A refused one: 'GitHub sent the download to <host>, which DataPiler does not fetch from' (host: an Own only when
    it matches a host pattern, else '<text>')."""

class Updater:
    def __init__(self, *, root: Path, version: str, port: Callable[[], int], busy: Callable[[], dict | None],
                 request_exit: Callable[[], None], fetch: Fetch | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        """Nothing runs here. fetch None: real_fetch(), made at the first press."""
    def get(self) -> dict:                                       # GET /api/update: the view (§4.2); notes the poll
    def post(self, body: dict) -> tuple[int, dict, Callable[[], None] | None]:   # POST /api/update
    def result(self) -> dict:                                    # GET /api/update-result
    def came_back(self, pending: "install.Pending | None", check: "install.Check") -> None:
        """datapiler.py, once the page is up: keeps result.json's content when its nonce is pending's."""
    def close(self) -> None:                                     # stops a check or a download; removes its .part
    # Reached only from post (S27; test_update_static):
    def _check(self, fresh: bool) -> None
    def _download(self) -> None
    def _install(self) -> tuple[dict, Callable[[], None] | None]
    def _cancel(self) -> None
```

- **Headers**, exactly: `User-Agent: DataPiler/<version> (+https://github.com/Pt0l3my/DataPiler)`, `Accept:
  application/vnd.github+json` (the API; `application/octet-stream` for assets), `X-GitHub-Api-Version: 2022-11-28`.
  No token, cookie or Referer.
- **The check** runs on a thread; `checking` until it ends. It reads `tag_name`, `published_at`, `html_url`, `body`
  and `assets[]` (`name`, `size`, `browser_download_url`, `digest`). The tag is `v<X.Y.Z>`; this version is
  `X.Y.Z` with an optional `-suffix`, which sorts below the same `X.Y.Z`. The zip is the asset named exactly
  `DataPiler-<X.Y.Z>.zip`, its checksum `DataPiler-<X.Y.Z>.zip.sha256`; each `browser_download_url` must be
  `ASSET_PREFIX + "v<X.Y.Z>/" + name`; the zip's `size` 1 byte to `ZIP_MAX`; `digest`, when present,
  `sha256:<64 hex>`. `html_url` is shown only if it starts with `PAGE_PREFIX`.
- **Failures** (design §2.3's table, its words): no answer or a timeout; 403 or 429 with `x-ratelimit-remaining: 0`
  ("It resets at HH:MM", local time, from `x-ratelimit-reset`); 404 ("No release is published yet." as state
  `none`); any other status ("GitHub answered <code>."). Each ends "Nothing was downloaded or changed."
- **The cache:** a successful answer is kept for `CACHE_SECS`; `check` with `fresh: false` within that reuses it;
  Check again sends `fresh: true`; a failure is never kept.
- **The download** runs on a thread into `update/<X.Y.Z>/DataPiler-<X.Y.Z>.zip.part`, 64 KiB at a time, hashed as it
  arrives, cut off and refused past the asset's `size`; Cancel, `close()` and the `POLL_GONE` rule stop it between
  chunks and remove the part. The `.sha256` file is fetched first (at most `SHA_MAX`). Then the proofs of §4.3, in
  order; any ✗ removes the download.
- **Install** (`action: install`) is refused, with its words, unless the state is `ready`; while `busy()` names a job
  or an Extract run ("A job or an Extract run is going - let it finish or cancel it, then press Install again.");
  and when this copy has no `manifest.sha256` (state `not_installable` already says so at the check: "This copy was
  not unpacked from a release, so the button does not replace its files - unpack the release by hand."). Then: the
  zip hashed again against the staged sha256; `DataPiler/update-helper.py` extracted to
  `update/<X.Y.Z>/update-helper.py` and checked against the zip's manifest; `install.write_pending(...)` with the
  page's current port; the answer `{"ok": true, "state": "restarting", "to": "0.3.0"}` with `after` =
  `request_exit`.
- **Log lines** (source `update`): `GET %s - %s, %s s` with the host and path only (never a query; a path that is
  not `[A-Za-z0-9/._-]+` shows as `<text>`); `latest release %s (this is %s)`; `download verified: %s, %s MiB`;
  `download refused at %s: %s` (the check's id and DataPiler's words); `update requested: %s - stopping (exit code
  75)`.

### 4.2 The view and the actions

`GET /api/update`:

```json
{"state": "ready", "this": "0.2.0", "checked_at": "18:02",
 "latest": {"version": "0.3.0", "published": "2026-11-20", "page": "https://github.com/Pt0l3my/DataPiler/releases/tag/v0.3.0",
            "zip": {"name": "DataPiler-0.3.0.zip", "size": 2004112}, "sha256_file": "DataPiler-0.3.0.zip.sha256",
            "digest": true, "notes": [{"k": "h", "level": 2, "parts": [{"t": "text", "v": "What's new"}]}],
            "notes_cut": false},
 "why": null,
 "progress": null,
 "checks": [{"id": "size", "ok": true, "text": "2,004,112 bytes - the size the release states"},
            {"id": "sha256", "ok": true, "text": "sha256 matches DataPiler-0.3.0.zip.sha256 (9f2c…41ab)"},
            {"id": "digest", "ok": true, "text": "and matches GitHub's digest for the file"},
            {"id": "shape", "ok": true, "text": "one folder, DataPiler, 61 files - nothing outside it, no links"},
            {"id": "manifest", "ok": true, "text": "its manifest: every file's sha256 checked; version inside: 0.3.0"}],
 "plan": {"write": 41, "add": 6, "remove": 2, "same": 12, "edited": 1, "files": 61, "libs": true},
 "failed": null}
```

- `state`: `idle`, `checking`, `up_to_date`, `newer`, `older` (this build is newer than the latest release),
  `not_installable` (no zip, no `.sha256`, a tag that is not a version, or no `manifest.sha256` here; `why` says
  which), `none` (no release yet), `downloading`, `ready`, `failed`. "Restarting", "updated" and "rolled back" are the
  page's own states (§4.7).
- `progress` while downloading: `{"done": 1258291, "of": 2004112, "rate": 655360}` (bytes, bytes a second).
- `plan` (ready only): `install.plan` of the new manifest against this copy (§4.6); `libs` is whether the zip's
  `requirements.lock` differs from this one's (S37).
- `failed`: `{"stage": "check" | "download" | "verify" | "install", "text": "...", "kept": false}`; `kept` true when the
  verified download is still there (a refused Install).

`POST /api/update` takes `{"action": "check", "fresh": false}`, `{"action": "download"}`, `{"action": "install"}` or
`{"action": "cancel"}`, and answers the view (Install: §4.1). Cancel stops a check (its answer is dropped) or a
download (its part removed), and in the ready state discards the download. An action the state does not allow, or
any other key or value, is 400 `{"error": "..."}`.

`GET /api/update-result`: `{"state": null}`, or, once after an update came back (`came_back` matched the nonce):

```json
{"state": "updated", "from": "0.2.0", "to": "0.3.0", "stage": "done", "text": null,
 "counts": {"written": 41, "added": 6, "removed": 2, "same": 12, "files": 61},
 "backup": "update\\backup-0.2.0", "log": "logs\\update.log", "check": {"files": 61, "differ": 0}}
```

`state` is `updated`, `failed` (restored; `text` and `stage` say where), `refused` (nothing touched) or `rolled_back`
(R). `text` is the helper's words, masked, at most 300 characters. Only paths relative to DataPiler's folder reach the
pop-up.

### 4.3 The proofs before anything is unpacked

In design §2.4's order, each a line of `checks`; the first ✗ ends them and removes the download:

1. `size`: the file's length is the asset's `size`.
2. `sha256`: the `.sha256` file's first token is 64 hex; a second token (after spaces and an optional `*`) must be the
   zip's name; it equals the file's sha256.
3. `digest`: equals GitHub's `digest`; without one, the line says "GitHub states no digest for this file - the
   published .sha256 alone" and is ✓ amber (`"ok": "warn"`).
4. `shape` and 5. `manifest`: `helper.check_archive(zip, version=...)` (§4.6), which raises `Refused` with `stage`
   `shape`, `manifest` or `version`.

### 4.4 The release notes as a tree

The app turns `body` (cut at `NOTES_MAX` characters, then `notes_cut` true) into blocks; nothing is ever HTML:

```
block  = {"k": "h", "level": 1..6, "parts": [part]} | {"k": "p", "parts": [part]}
       | {"k": "li", "n": null | 1.., "parts": [part]}          (consecutive li blocks are one list)
       | {"k": "code", "v": "text"}                              (fenced or indented)
part   = {"t": "text" | "b" | "i" | "code", "v": "text"}
       | {"t": "link", "v": "text", "href": "address as written"}
       | {"t": "image", "v": "alt text"}                         (shown as [image: alt text])
```

Flat parts, no nesting; raw HTML in the Markdown is kept as text. `update.js` builds it with `createElement` and
`textContent` only; a link shows its text, then its address in grey, and is not a link.

### 4.5 `datapiler/install.py`

```python
UPDATE_DIR = "update"; MANIFEST = "manifest.sha256"; HELPER = "update-helper.py"
PENDING = "update/pending.json"; RESULT = "update/result.json"

def helper(root: Path) -> ModuleType:
    """<root>/update-helper.py, loaded once by path (importlib.util.spec_from_file_location): the one home of the
    archive, manifest and plan checks, so the app and the helper prove a zip the same way."""

@dataclass(frozen=True)
class Pending:
    from_version: str; to_version: str; zip: str; zip_sha256: str; zip_size: int; port: int; nonce: str; at: int

def write_pending(root: Path, *, from_version: str, to_version: str, zip_rel: str, zip_sha256: str, zip_size: int,
                  port: int) -> Pending: ...
def read_pending(root: Path) -> Pending | None:
    """Format, root fingerprint and every field's pattern checked; any age. A file that fails is removed, with a
    WARN naming the field."""
def remove_pending(root: Path) -> None: ...

@dataclass(frozen=True)
class Check:
    manifest: bool; files: int; differ: tuple[Own, ...]; missing: tuple[Own, ...]

def install_check(root: Path) -> Check:
    """Each file manifest.sha256 lists, hashed (paths checked by helper.safe_rel; Own after that check). Never
    repairs."""
def read_result(root: Path, nonce: str) -> dict | None: ...
def cleanup(root: Path) -> None:
    """At page-up: every update/<X.Y.Z>/ folder, any .part, and the .old files the latest backup.json lists (each
    still inside root). Never anything else."""
```

### 4.6 `update-helper.py`

Standard library only; run as `python update\<to>\update-helper.py --pending update\pending.json`, `--rollback
update\backup-<from>` or `--check-zip <zip> --version <X.Y.Z>` (read-only, for the release workflow). Its root is
`Path(__file__).resolve().parents[2]` for the first two, and must be the folder `pending.json` names.

```python
FORMAT_PENDING = "datapiler-update-pending/1"; FORMAT_RESULT = "datapiler-update-result/1"
FORMAT_BACKUP = "datapiler-update-backup/1"
TOP = "DataPiler"; MAX_MEMBERS = 2000; MAX_UNPACKED = 256 * 1024 * 1024; PENDING_SECS = 600
MUTEX = "Local\\DataPiler"
NEVER = ("workspace", "share", "logs", "jobs", "update", ".venv", ".venv.new", ".venv.prev",
         "settings.json", "datapiler.port", "datapiler-start.log", "datapiler.lock")

class Refused(Exception): stage: str; text: str     # nothing touched: exit 2
class Failed(Exception): stage: str; text: str      # put back: exit 1

def safe_rel(path: str) -> bool:
    """Relative, '/' only, no '..' or '.' part, no drive, no ':', no backslash, no control character, no part
    ending in a dot or a space, no device name (paths.RESERVED_RX's list, written out here)."""
def root_id(root: Path) -> str:          # sha256 of the case-folded, resolved root: pending.json's fingerprint
def parse_manifest(data: bytes) -> dict[str, str]:  # "<64 hex>  <path>" lines, UTF-8, LF; each path safe_rel, once
def check_archive(zip_path: Path, *, version: str) -> "Archive":
    """From the zip's directory first: every name under TOP + '/'; safe_rel; no symlink (external attributes); at
    most MAX_MEMBERS; directory entries allowed and unlisted. Then every file member read once: sizes counted as
    read (MAX_UNPACKED), each sha256 against DataPiler/manifest.sha256, which must list every file member but
    itself; update-helper.py listed; datapiler/__init__.py's VERSION line is version."""
@dataclass
class Archive: manifest: dict[str, str]; files: int; unpacked: int; version: str; lock_sha256: str | None
def plan(root: Path, new: dict[str, str], old: dict[str, str] | None) -> "Plan":
    """write: in new, on disk, another hash; add: in new, not on disk; same: on disk with new's hash; remove: in old,
    not in new, on disk; edited: on disk with a hash other than old's (named in the log)."""
@dataclass
class Plan: write: list[str]; add: list[str]; remove: list[str]; same: list[str]; edited: list[str]
def never_touched(root: Path) -> list[str]:
    """NEVER, plus settings.json's workspace_dir and share_dir when they lie inside root (settings.json read, at
    most 64 KiB, those two keys only)."""
def install(root: Path, pending: Path, *, mutex: str = MUTEX, now: Callable[[], float] = time.time,
            replace: Callable = os.replace, say: Callable[[str], None] = print) -> int: ...
def rollback(root: Path, backup: Path, *, mutex: str = MUTEX, replace: Callable = os.replace,
             say: Callable[[str], None] = print) -> int: ...
def main(argv: list[str] | None = None) -> int: ...
```

**Install, by stage** (`result.json`'s `stage`):

| Stage | Does | On failure |
|---|---|---|
| `checks` | `pending.json` read (format, `at` within `PENDING_SECS`, `root_id`, a zip path under `update/`); the mutex free, then taken (Windows: `CreateMutexW` by ctypes; elsewhere `fcntl.flock` on `datapiler.lock`, as `winapi`'s fallback) | exit 2 |
| `verify` | the zip's size and sha256 are pending's; `check_archive(version=to)` | exit 2 |
| `plan` | the installed `manifest.sha256` (none: refused); `plan`; any planned path in `never_touched` or failing `safe_rel` refuses the whole update; each target resolved (`realpath`) inside root, compared case-folded on Windows | exit 2 |
| `backup` | `update/backup-<from>/` (one already there is renamed `.prev`): each `write` and `remove` target copied to `files/<path>` and hashed; the old manifest; `backup.json` with `complete: false` | put back, exit 1 |
| `write` | each `write` and `add`: the member streamed to `<target>.dpnew`, hashed, the target's resolution checked again, `os.replace`; a `PermissionError` sets the target aside as `<target>.old` (listed in `backup.json` `aside`) and replaces again; the landed file hashed against the manifest; new folders recorded | put back, exit 1 |
| `remove` | each `remove` target deleted (its copy is in the backup) | put back, exit 1 |
| `manifest` | the zip's `manifest.sha256` written the same way | put back, exit 1 |
| `done` | `backup.json` `complete: true` with `added`; `backup-<from>.prev` and any older `backup-*` removed; `result.json` `updated` | — |

**Putting back:** each backed-up file written back the same way and hashed against the old manifest; each added file
and new folder removed; `result.json` `failed` with the stage and the reason, and `restored: false` with the backup's
folder named if a file could not be put back.

**Rollback (R):** the mutex; `backup.json` complete; every backed-up file put back, every `added` file removed, the
old manifest put back; `result.json` `rolled_back` with pending's nonce; exit 0, else 1.

**Its words.** Console lines `[HH:MM:SS] ok ...`, `[HH:MM:SS] ! ...`, `[HH:MM:SS] x ...` (ASCII, S38), as the mock's
window shows them; `logs/update.log` in DataPiler's line format, source `update`, with the root replaced by
`<DATAPILER>` and the home folder by `<HOME>` before a line is written. A reason names DataPiler's relative paths and
an exception's type and errno, never `str(e)`.

### 4.7 The pop-up (`page/update.js`, `page/update.css`)

UPDATE's page parts: the Update… button's listener; the pop-up in every state of design §2.1 and the mock; the
restarting wait; the result after the reload.

- **Opening** runs `check` with `fresh: false`, then reads `GET /api/update` every 0.5 s while the pop-up is open.
  **Check again** sends `fresh: true`. Closing it while checking or downloading sends `cancel`.
- **Newer:** the version and date (`published`, shown as "20 Nov 2026"), the zip's name and its size in MiB with the
  decimal MB beside it, "Checksum: published beside it (`<sha256_file>`)" and, with `digest`, "GitHub states its
  own digest"; the notes (§4.4), "… the rest is on the release page" when `notes_cut`; **Open the release page ↗**
  only when `page` is set, as `<a href target="_blank" rel="noopener noreferrer">`; **Download n MiB**.
- **Downloading:** a `<progress>` element (no inline style), "1.2 of 1.9 MiB · 640 KiB/s".
- **Ready:** each check line; "Install and restart stops DataPiler. Its window then replaces 41 files, adds 6 and
  removes 2 (kept in the backup), and starts 0.3.0", what is kept, "Python libraries: changed - after the restart the
  window asks Y" when `plan.libs`; the unsigned-exe note in amber (design §2.6); "a download not installed is removed
  when DataPiler next starts"; **Discard the download**, **Later**, **Install and restart**.
- **Restarting** (after Install's answer): `holdHeartbeat(true)`; `sessionStorage["dp.update"] = "1"`; every 2 s
  `fetch("/", {cache: "no-store"})`; once it answers 200 with a page that does not hold this page's `TOKEN`, the
  page reloads. After 90 s: "DataPiler did not come back on this address - it may have opened a new tab, or its
  window says why".
- **After the reload:** with `dp.update` set, `GET /api/update-result`, the updated, failed or rolled-back state
  (the mock's words), and the flag removed.
- Rules: the IIFE (§3.2); no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` or
  `Function`; it fetches only `/api/update`, `/api/update-result` and `/`; British spelling.

### 4.8 `datapiler.py`

- `Run.exit_code = 0`; `request_update_exit()` logs the `update requested` line, sets 75 and calls `request_stop`;
  `start()` returns `self.exit_code` after the stop. Exit codes: 0, 1, 2, 3 as before, and **75** "update
  requested".
- After the log is set up: `pending = install.read_pending(root)`.
- The port: `--port` if given, else `pending.port`, else the setting, else any free one. If pending's port does not
  bind: the setting's or any, with WARN "the page's port before the update was taken - a new tab opens".
- The browser: not opened when the page is on pending's port (the old page reloads itself; the line reads "Page:
  http://127.0.0.1:<port>/ (the open page reloads)"); otherwise as 0.1.
- After `datapiler.port` is written: `check = install.install_check(root)`, logged (`install check: all %s files
  match the release`, or WARN `install check: %s files differ from the release: %s`, or INFO `install check: no
  manifest.sha256 - a copy from the repository, not a release`); `self.updates.came_back(pending, check)`;
  `install.remove_pending(root)`; `install.cleanup(root)`; `self.folders.at_start()`.
- `RealParts.updater(run)`: `update.Updater(root=run.root, version=VERSION, port=lambda: run.port, busy=run.runner.busy,
  request_exit=run.request_update_exit)`. `RealParts.folders(live)`: `detect.Folders(live)`.

### 4.9 `DataPiler.ps1`

- `param([switch]$FromLauncher, [switch]$AfterUpdate)`; ASCII only, PowerShell 5.1 and 7, as before.
- **Every Y** builds `.venv.new` (a leftover one removed first, never a reparse point): `-m venv .venv.new`, pip into
  it with 0.1's flags, the marker into it; then `.venv` renamed `.venv.prev` and `.venv.new` renamed `.venv`. Without
  `-AfterUpdate`, `.venv.prev` is removed at once ("environment made (.venv); the old one removed"). A failure
  removes `.venv.new` and keeps `.venv`. At a start without `-AfterUpdate`, a leftover `.venv.prev` or `.venv.new` is
  removed.
- **The run loop.** The app runs as now; exit **75**: `pending.json` read (`ConvertFrom-Json`; `to` and `from` must
  match `^\d+\.\d+\.\d+$`), "DataPiler stopped to update to <to>.", then `& <python> <pre> update\<to>\update-helper.py
  --pending update\pending.json` with the Python found at the start (never the venv's). Helper 0: `&
  "$PSScriptRoot\DataPiler.ps1" -AfterUpdate`, then `exit $LASTEXITCODE`. 1 or 2: result.json's reason (or "the
  update did not complete - logs\update.log has why") and the app is started again by the loop. The window's own
  mutex stays held throughout (the new script's `WaitOne(0)` succeeds on the same thread: to verify, §10 P4).
- **With `-AfterUpdate`**, after the app exits: a code other than 0 and 3, `update\pending.json` still there, and
  under 90 s since the app was started: the two lines of design §2.5 ("DataPiler <to> stopped before its page came
  up (exit code N) - datapiler-start.log has why." / "Press R to go back to <from>, or Enter to close this window.").
  **R**: the helper's `--rollback update\backup-<from>`; on 0, `.venv` removed and `.venv.prev` renamed `.venv` when
  there is one; then `& "$PSScriptRoot\DataPiler.ps1"` and its exit code. The page came up (pending gone):
  `.venv.prev` removed.

### 4.10 The launcher

In the branch where `Local\DataPiler` or the window's mutex is held: if `update\pending.json` exists beside the exe,
`MessageBoxW` "DataPiler is updating - see its window." and exit 0, opening nothing. Nothing else changes; `app.rc`
and `app.manifest` carry 0.2.0.0.

### 4.11 The release and CI

- **`tools/manifest.py <folder>`** writes `<folder>/manifest.sha256`: every regular file below it except
  `manifest.sha256`, as `<64 hex>  <path>` with `/`, sorted by the UTF-8 bytes of the path, LF; a symlink or a path
  failing the helper's `safe_rel` stops it.
- **`release.yml`**, after the zip holds the exe and the notices: unzip into a fresh stage folder; `python3
  src/tools/manifest.py stage/DataPiler`; `(cd stage && zip -X -q "../$app.zip" DataPiler/manifest.sha256)`; then
  `(cd stage/DataPiler && sha256sum -c --strict --quiet manifest.sha256)`, `unzip -l` holds
  `DataPiler/update-helper.py` and `DataPiler/manifest.sha256`, and `python3 src/update-helper.py --check-zip
  "$app.zip" --version "$version"` passes, before the zip's sha256 is taken. The DP10 check stays.
- **`checks.yml`**, Windows job: a venv made as `.venv.new` from the lock as the script does, renamed `.venv`, and
  `.venv\Scripts\python.exe -c "import grpc, google.protobuf"` succeeds.

### 4.12 The version and the documents

- `VERSION = "0.2.0"`; `app.rc` and `app.manifest` 0.2.0.0; `BUILD.md`'s version line.
- **`docs/release-notes/0.2.0.md`**, short: the Update… button (three presses, the checks, the window's swap with its
  backup, R); Detect and Set folder… (the running Smithbox, Smithbox's record of the open project, Steam as a
  cross-check; nothing saved until Use); Mask paths on this page; plainly: **not tried on a real PC yet** — the
  download from GitHub, the swap and R, Detect on a real Steam install and Smithbox's record, the picker on real
  drives; and that **0.1.0 users unpack 0.2.0 by hand, once** (0.1.0's window cannot hand over to the helper).
- **`README.md`**: the button and what it checks and keeps; the first update by hand; SmartScreen both ways (a zip
  downloaded by hand: More info → Run anyway; the button's update is proved by checksum and carries no download
  mark); the recommendation of two-factor authentication and workflow-only assets for the release account; for
  FOLDERS's part: Detect's sources as S33 words them, Set folder… lists folder names only, Use saves, Mask paths on
  this page.
- **`CHANGELOG.md`** 0.2.0; **`settled.md`** S27 onwards as §9 words them.

---

## 5. FOLDERS

### 5.1 The Windows adapter's new calls (`winapi.py`)

```python
@dataclass(frozen=True)
class Drive:
    name: str      # "C:"
    path: str      # "C:\\"
    kind: str      # "local", "removable", "network", "cdrom", "ram", "unknown"

class Backend(Protocol):                       # added to 0.1's
    def registry_value(self, hive: str, key: str, name: str) -> str | None:
        """winreg: hive "HKCU" or "HKLM", KEY_READ, the 64-bit view; REG_SZ and REG_EXPAND_SZ as stored, else None;
        None when missing or refused. Portable: None."""
    def drives(self) -> list[Drive]:
        """GetLogicalDrives and GetDriveTypeW; never a volume label. Portable: [Drive("/", "/", "local")]."""
    def windows_dir(self) -> str | None:
        """GetWindowsDirectoryW. Portable: None."""
    def hidden(self, path: str) -> bool:
        """GetFileAttributesW: HIDDEN or SYSTEM. Portable: the name starts with a dot."""
    def local_appdata(self) -> str | None:
        """SHGetKnownFolderPath(FOLDERID_LocalAppData), as .NET finds it for Smithbox (smithbox-projects.md §2), not
        the LOCALAPPDATA variable. Portable: None."""
```

No window-title read: smithbox-projects.md §4's second sign is the lead's call (§10 P1), and is not built unless
the lead adds it. `processes()` (with `QueryFullProcessImageNameW`, as 0.1) gives the running Smithbox's and the game's paths;
`file_version()` gives the builds. Every registry read takes its three values from `detect.REGISTRY`, a fixed table
(a test holds every call to it):

```python
REGISTRY = {
    "steam_user":   ("HKCU", r"Software\Valve\Steam", "SteamPath"),
    "steam_system": ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    "uninstall":    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 1245620", "InstallLocation"),
    "uninstall_32": ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 1245620", "InstallLocation"),
}
```

### 5.2 `datapiler/steam.py`

```python
GAME_APP_ID = 1245620            # a lead (§10 P2): every candidate is still proved by eldenring.exe
VDF_MAX = 1024 * 1024; VDF_DEPTH = 16; VDF_KEYS = 10_000

class VdfError(ValueError): ...
def parse_vdf(text: str) -> dict:
    """Valve's KeyValues: quoted strings (escapes \\ \" \n \t), braces, // comments; anything else is a VdfError.
    Keys keep their case; lookups with key() are case-insensitive. No eval."""
def key(d: dict, name: str) -> object | None: ...
def libraries(steam_dir: str) -> list["Library"]:
    """<steam>/steamapps/libraryfolders.vdf and <steam>/config/libraryfolders.vdf, both formats (the old flat "1"
    "<path>" entries; the new blocks with path and apps), and the Steam folder itself; merged, case-folded."""
@dataclass(frozen=True)
class Library: path: str; apps: frozenset[int] | None      # None: an old file without apps
def app_manifest(library: str, app_id: int) -> "AppManifest | None":
    """<library>/steamapps/appmanifest_<id>.acf: installdir (one folder name, nothing else) and InstalledDepots'
    dlcappid values."""
@dataclass(frozen=True)
class AppManifest: installdir: str; dlc_app_ids: tuple[int, ...]
```

### 5.3 Smithbox's record of its projects (`sbproject.py`)

The research is done: [smithbox-projects.md](smithbox-projects.md) (Smithbox at the commit of tag 2.2.6, each file
and line named). FOLDERS builds its §6 as written, reading, showing and refusing; everything in it is a lead (O48)
until its §7 passes on the owner's PC. In short: one file per project, `<Local AppData>\Smithbox\Projects\*.json`,
per Windows user (so not found through the Smithbox folder); the five keys `ProjectName`, `ProjectPath`, `DataPath`,
`ProjectType` (8, or `"ER"`; never a boolean) and `AutoSelect`; nothing on disk says which project is open, and the
`AutoSelect` mark is the sign used.

```python
PROJECT_MARKS = ("project.json", ".smithbox")   # the weaker "a Smithbox project file is here" (its §5)
ER_TYPES = (8, "ER")

@dataclass(frozen=True)
class ProjectLead:
    name: str; project_dir: str; data_dir: str; marked: bool     # the record's five values, kept in memory only

@dataclass(frozen=True)
class Record:
    found: bool                   # the Projects folder was there and could be read
    leads: tuple[ProjectLead, ...]        # recognised Elden Ring records
    other_games: int; unrecognised: int
    why: Own | None               # its §6's words: "No Smithbox project record was found", "Smithbox's project record
                                  # is in a form this DataPiler does not recognise (N files)", a cap exceeded
    def open_lead(self) -> ProjectLead | None:
        """The one marked Elden Ring record; None when none or two or more are marked (no "open" tag then)."""

def read(local_appdata: str | None) -> Record:
    """Its §6, Reading: only *.json directly in the folder, at most 64 files of 1 MiB (past either cap, none read);
    read-only, UTF-8 with or without a BOM, one re-read after 0.5 s of a file that does not parse; the five keys
    checked by type, every other key dropped at once; each path an absolute drive path (no share, device path or NUL).
    Never an exception, a pattern search, a fallback to other keys or to project.json, a write, a lock or a rename,
    and never a read of Configuration.json."""
```

`smithbox.open_project()` returns `read(winapi.backend().local_appdata()).open_lead().project_dir`, or None (cached
by the folder's file names, sizes and mtimes). The link's project question (`api.PROJECT_ASK`) is unchanged in 0.2.0
(§10 P1).

### 5.4 `datapiler/detect.py`

```python
WANTS = ("smithbox", "game", "project", "expansion")
KEYS = {"smithbox": "smithbox_dir", "game": "game_dir", "project": "project_dir", "expansion": "expansion"}
TAGS = {"running_smithbox": "the running Smithbox", "smithbox_record": "Smithbox's project record",
        "steam_library": "Steam's library list", "steam_uninstall": "Windows' uninstall entry",
        "running_game": "the running game", "steam_manifest": "Steam's app manifest", "recent": "used here before"}

@dataclass(frozen=True)
class Candidate:
    value: str                   # a folder (resolved), or "yes"/"no" for the expansion
    sources: tuple[str, ...]     # ids of TAGS, in the order below
    name: str | None             # the record's ProjectName (page only, never logged, not sent with the mask on)
    marked: bool                 # from the record's one marked Elden Ring project: the tag adds "marked to open"
    detail: Own | None           # the expansion's "DLC app 2778580 installed", or None

class Folders:
    def __init__(self, live: Live) -> None: ...
    def at_start(self) -> None:
        """A daemon thread: Detect for each folder whose setting is blank or no longer a folder, and for the expansion
        while it is not stated. Nothing saved."""
    def detect(self, want: str) -> dict:          # the /api/detect answer (§6); its candidates kept for /api/settings
    def found(self, want: str) -> list[Candidate]: ...
    def close(self) -> None: ...
```

**The sources, in order (DP13).** Candidates from several sources merge by folder (case-folded, separators and a
trailing backslash normalised), keeping every source:

| Want | Sources | A candidate counts |
|---|---|---|
| smithbox | `running_smithbox` (each `smithbox.exe` process's folder, from `processes()`), `recent` | if `Smithbox.exe` is in it |
| project | `smithbox_record` (each lead's `project_dir`), `recent` | always listed, with its check line; Use only when the check is not ✗ |
| game | `smithbox_record` (each lead's `data_dir`), `steam_library` (the Steam folder from `REGISTRY["steam_user"]`, else `["steam_system"]`; the library whose `apps` holds `GAME_APP_ID`, else every library; the app manifest's `installdir`; `\Game`), `steam_uninstall` (both uninstall entries, `\Game` added), `running_game` (`eldenring.exe`'s folder), `recent` | if `eldenring.exe` is in it |
| expansion | `steam_manifest`: "yes" when `InstalledDepots` lists any `dlcappid`, with `detail` naming the ids; "no" when it lists none | — |

The record is read whether or not Smithbox runs (smithbox-projects.md §2); the running Smithbox gives its folder only.

**The cross-check (DP13):** a game candidate from `smithbox_record` that a Steam source also gives carries both tags
("Steam's library list agrees"); when they differ, both are listed and neither is chosen, with the note "Smithbox's
project record and Steam name different game folders - use the one your project is for". The expansion's id is never
compared with a built-in one: the owner reads the ids and presses Use.

**Notes**, in the answer: "Smithbox is not running, so its folder cannot be read - start Smithbox, then Detect
again"; `Record.why` followed by "- choose the folder with Set folder…"; "N more files not recognised"; "Steam's
library list could not be read".

**Privacy (design §3.5).** Candidates and names live in memory for the session only, and every candidate goes to
`logbook.learn_found` as it is found. Log lines (source `folders`) name the folder, the counts and the sources only:
`game folder: %s places (%s)`; `project: %s places from Smithbox's project record, %s open, %s for another game, %s not
recognised`; `expansion: Steam's app manifest lists %s DLC apps installed`.

### 5.5 `datapiler/dirs.py`: the check lines, the picker, New folder

```python
MARKS = {"smithbox": ("Smithbox.exe",), "game": ("eldenring.exe",), "project": sbproject.PROJECT_MARKS}
LIST_MAX = 2000; LIST_SECS = 3.0; PATH_MAX = 1024

@dataclass(frozen=True)
class Check:
    ok: bool | str               # True ✓, "warn" !, False ✗
    text: Own                    # DataPiler's words, never a path
    mark: bool
def check(want: str, path: str, s: Settings, root: Path) -> Check: ...
def path_refusal(path: str, windows_dir: str | None) -> Own | None:
    """Pure: 'not a folder path' (relative; '..' after resolving; a device path, \\.\ or \\?\), 'network paths can be typed in the
    field, not browsed' (UNC), "Windows' own folder" (windows_dir or inside it)."""
def listing(want: str, path: str, s: Settings, root: Path) -> dict: ...      # the /api/dirs answer
def name_refusal(name: str) -> Own | None: ...
def new_folder(parent: str, name: str, s: Settings, root: Path) -> dict: ... # the /api/dirs/new answer
```

**Check lines:**

| Want | ✓ | ! (saves) | ✗ |
|---|---|---|---|
| any | — | "not set"; "no such folder" (project: "- New folder… in the picker makes one"); "a network path - not checked" (a UNC path is never touched) | "a full folder path is needed (it starts with a drive letter)" |
| smithbox | "Smithbox.exe is here · build a.b.c.d" (or "· build not read") | — | "no Smithbox.exe here" |
| game | "eldenring.exe is here · version a.b.c.d" | — | "no eldenring.exe here - the game's folder is the Game folder inside ELDEN RING" |
| project | "outside the game's folder", then "· a Smithbox project for this game" when a recognised record's `ProjectPath` is this folder and its `DataPath` the game folder, else "· a Smithbox project file is here" with the mark (smithbox-projects.md §5) | "set the game folder first, so this can be checked against it" | "the game's folder itself", "inside the game's folder", "it holds the game's folder", "DataPiler's own folder", "inside DataPiler's folder", each "- choose a folder outside it" |

**The listing:** folder names only, never a file, from `os.scandir` on a worker thread with `LIST_SECS`; at most one
listing outstanding a drive (a request for a drive whose listing has not ended answers "this drive did not answer in
3 s" at once); hidden or system folders left out (`winapi.hidden`); a folder that cannot be read shows "(no access)";
sorted case-insensitively; at most `LIST_MAX`, then `more`; `mark` is an existence check of `MARKS[want]`'s fixed names in each folder (one for the game and Smithbox, two for a project);
a junction or symlink listed under its name. A blank path lists `winapi.drives()`. DEBUG only: `picker: %s folder
listed, %s entries`.

**New folder** (want `project` only): `name_refusal` (Windows' refused characters `<>:"/\|?*`, control characters, a
trailing dot or space, a device name, over 255 characters); the parent passes `path_refusal`; the new folder must
not be the game's folder or inside it, nor DataPiler's folder or inside it; `os.mkdir`, never `makedirs`; one that
exists is refused.

### 5.6 Settings (`settings.py`)

```json
{"format": "datapiler-settings/1", "...": "0.1's keys", "mask_paths": false,
 "recent": {"smithbox_dir": [], "game_dir": [], "project_dir": []}}
```

| Key | Type | Default | Rule |
|---|---|---|---|
| `mask_paths` | bool | `false` | DP14; at once |
| `recent` | object of three lists, each at most five absolute folders, newest first, no repeats (case-folded) | empty | kept by the app: whenever a folder key's saved value changes, the new value goes to the front of its list; never sent by the page (`POST /api/settings` and `/api/settings/one` refuse it: "not a setting the page sets") |

- **The project rules** in `check` (with its `root`) and `Status.project_ok`: not the game's folder nor inside it (as
  0.1), not a folder that holds the game's folder, not DataPiler's folder nor inside it (S32).
- **`load` from 0.2.0** drops a key it does not know, with a problem line naming it (pattern `[a-z_]{1,32}`, else
  "(key)"), and checks the rest (S36). `check` for the page still refuses an unknown key.

### 5.7 Masking the page (DP14)

With `mask_paths` on, every path an answer gives for drawing is `logbook.mask(path)` (the named folders, `<FOUND>`,
`<HOME>`, `<USER>`, `<PC>`), in a `shown` field beside the real `path`, and Status's `detail` values are masked. In the
picker, the crumbs are those of the masked path: a placeholder is one crumb (`<GAME>`), standing for the folders it
hides, and each crumb keeps its real `path` for navigating. The page draws `shown` everywhere; the five folder fields
show `shown` read-only, with "Paths are masked on this page - switch Mask paths off to edit them"; Save leaves out the
fields it did not let the owner edit. With it off, `shown` equals `path`.

### 5.8 Status (`status.py`)

- `smithbox` card's `installed` and `game` card's `folder`: with the setting blank or missing and Detect's places in
  memory, `"ok": "warn"`, "Found 1 place - confirm it in Settings" (or "n places"), fix "Open Settings and press Use".
- `project` card's `outside_game`: `project_ok`'s reasons with the new rules.
- `open_project`: ✓ "Smithbox's record marks <PROJECT> as the project it opens" when `smithbox.open_project()` is
  the project folder; amber "Smithbox's record marks another project to open" (its masked folder in `detail`) when it
  differs; `null` "Which project Smithbox has open is not known yet" when it is None. A lead (O48): the mark is
  normally, not always, the project open (smithbox-projects.md §4).

### 5.9 The page (FOLDERS's parts)

- **Settings**: a Folders card (the mock's): for each of the three folders, the title with its "?" (DP13's sources,
  in the owner's words), the path field, **Detect** and **Set folder…**, the live check line (`POST /api/dirs/check`,
  300 ms after typing stops), Detect's list (path or `shown`, its tags, **Use** or "in use"), Recent with **Use** and
  "forget recent folders"; under the game row, Expansion installed (0.1's select) with Detect's value, its detail and
  **Use**. **Mask paths on this page**: a switch beside the session switches, saved at once. The rest of Settings
  unchanged.
- **Save**: refused on the page, with the check's words, for a folder field whose value differs from the saved one
  and whose check is ✗; the app refuses the project rules whatever the page does.
- **The picker** (`folders.js`): design §3.2's layout, keys and focus, in `overlay()`; This PC, Detected (n) (opened
  first when there are any) and Recent (n) as chips; the filter box over the folder shown only; the check line under
  the list; ↑ Up, Cancel, **Choose this folder** (greyed on ✗); New folder… in the project picker only. Refusals and
  notes show in place of the list.
- **Status**: the cards' new lines come from `/api/state` as 0.1's do.
- Rules as 0.1's page (build-plan.md §6): `textContent` or `esc()` only, no inline handler or style attribute.

---

## 6. The API: new and changed endpoints

All under 0.1's guard (Host, Origin on a POST, the per-start token), JSON in and out, at most 64 KB a body. Words in
answers are DataPiler's. A malformed body (an unknown key, a `want` or `key` outside its list, a path not a string,
over `PATH_MAX`, or holding a control character) is 400 `{"error": "..."}`.

| Method and path | Owner | Body | Answer |
|---|---|---|---|
| `GET /api/update` | UPDATE (route: FOLDERS) | — | the view, §4.2 |
| `POST /api/update` | UPDATE (route: FOLDERS) | `{"action": "check", "fresh": false}` / `download` / `install` / `cancel` | the view; Install: `{"ok": true, "state": "restarting", "to": "0.3.0"}`, then exit 75 |
| `GET /api/update-result` | UPDATE (route: FOLDERS) | — | §4.2 |
| `GET /api/settings` | FOLDERS | — | below |
| `POST /api/settings` | FOLDERS | `{"settings": {...}}` | as 0.1; the body's keys laid over the current settings before `check`; `recent` refused |
| `POST /api/settings/one` | FOLDERS | `{"key": "game_dir", "value": "C:\\Games\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game"}`; key one of `smithbox_dir`, `game_dir`, `project_dir`, `expansion`, `mask_paths` | `{"ok": true}` or 400 `{"error", "field"}`. A folder value is saved as the folder it resolves to, and refused on a ✗ check with its words. Emits `settings.saved`, renews the masks, resets the project's confirmation as Save does |
| `POST /api/detect` | FOLDERS | `{"want": "game"}` | below |
| `POST /api/dirs` | FOLDERS | `{"path": "C:\\Games\\SteamLibrary\\steamapps\\common", "want": "game"}` | below |
| `POST /api/dirs/new` | FOLDERS | `{"parent": "C:\\Mods", "name": "ER project", "want": "project"}` | `{"path": "C:\\Mods\\ER project", "shown": "..."}` or `{"refused": "..."}` |
| `POST /api/dirs/check` | FOLDERS | `{"want": "project", "path": "C:\\Mods\\ER project"}` | `{"ok": true, "text": "outside the game's folder", "mark": false}` |
| `POST /api/dirs/forget` | FOLDERS | `{"key": "project_dir"}` | `{"ok": true}`: that folder's recent list emptied |
| `GET /api/state` | FOLDERS | — | as 0.1, with §5.8's lines; `detail` masked with `mask_paths` |

`GET /api/settings`:

```json
{"settings": {"smithbox_dir": "C:\\Tools\\Smithbox", "game_dir": "", "...": "...", "mask_paths": false},
 "server": "127.0.0.1:22720", "session": {"link": false, "debug": false},
 "folders": {
   "smithbox_dir": {"shown": "<SMITHBOX>",
                    "check": {"ok": true, "text": "Smithbox.exe is here · build 2.2.6.0", "mark": true},
                    "found": [{"path": "C:\\Tools\\Smithbox", "shown": "<SMITHBOX>", "sources": ["running_smithbox"],
                               "tags": ["the running Smithbox"], "in_use": true,
                               "check": {"ok": true, "text": "Smithbox.exe is here · build 2.2.6.0", "mark": true}}],
                    "recent": [{"path": "C:\\Old\\Smithbox", "shown": "C:\\Old\\Smithbox"}]},
   "game_dir": {"...": "..."}, "project_dir": {"...": "..."}},
 "expansion": {"found": [{"value": "yes", "sources": ["steam_manifest"], "tags": ["Steam's app manifest"],
                          "detail": "DLC app 2778580 installed", "in_use": false}]},
 "shown": {"workspace_dir": "workspace", "share_dir": "share"}}
```

`settings` no longer carries `recent` (it is in `folders`). `POST /api/detect` answers `{"want": "game", "found":
[candidate as above], "notes": ["..."]}`; for the expansion, its candidates carry `value` instead of `path`. A
candidate from Smithbox's record also carries `"marked": true|false` and `"name": "<the record's ProjectName>"`, the
name left out while `mask_paths` is on.

`POST /api/dirs`:

```json
{"path": "C:\\Games\\SteamLibrary\\steamapps\\common", "shown": "C:\\Games\\SteamLibrary\\steamapps\\common",
 "crumbs": [{"name": "C:", "path": "C:\\"}, {"name": "Games", "path": "C:\\Games"}, "..."],
 "dirs": [{"name": "ELDEN RING", "mark": false}, {"name": "Sekiro", "mark": false}], "more": 0,
 "check": {"ok": false, "text": "no eldenring.exe here - the game's folder is the Game folder inside ELDEN RING", "mark": false},
 "note": null}
```

A blank `path`: `{"path": "", "shown": "This PC", "crumbs": [], "drives": [{"name": "C:", "path": "C:\\", "kind":
"local"}], "dirs": [], "more": 0, "check": null, "note": null}`. A refusal: `{"refused": "network paths can be typed in
the field, not browsed"}` and nothing else. A drive that did not answer, or "(no access)": `dirs` empty and `note`
saying so.

---

## 7. Tests

No test touches the network or the owner's PC: Windows-only parts through `winapi.use(fake)`, Steam's and Smithbox's
files as invented fixtures in temporary folders, GitHub through a fake `Fetch`. Invented paths are on `C:\` only;
temporary folders exist at run time, never in a file. Each test module starts with `import _repo  # noqa: F401`.

### 7.1 UPDATE

- **`test_update_static.py`** (S27): over every module of the app (`datapiler/*.py`, `datapiler.py`,
  `update-helper.py`, `tools/*.py`) by AST: `urllib.request`, `http.client`, `ssl`, `ftplib`, `smtplib`,
  `xmlrpc.client`, `asyncio.open_connection`, `socket.create_connection` and `socket.socket(...).connect` appear only
  in `update.py`, except `link.py`'s `socket.create_connection((HOST, PORT), ...)` and `datapiler.py`'s
  `http.client.HTTPConnection("127.0.0.1", ...)`; `update-helper.py` imports none of them; `_check`, `_download`,
  `_install` and `_cancel` are referenced only inside `Updater.post`; `Updater.post` and `update` are referenced only
  by `api.py`'s `/api/update` route and `datapiler.py`'s construction; no timer or thread calls a press; no settings
  key holds "update" or "check".
- **`test_update.py`**: `allowed()` on URLs (each host; http; a port; a user; a look-alike host; a fragment) and on
  redirect chains (allowed to allowed, to a foreign host, to http, more than five); the headers, and no Authorization,
  Cookie or Referer; each state from invented releases (newer, older, same, 404, 403 and 429 with the reset time, 500,
  `OSError`, a timeout, no zip, no `.sha256`, a bad tag, a wrong `browser_download_url`, a foreign `html_url`); the
  cache (kept 10 min, `fresh` asks again, a failure never kept); the download (the part file, cancel removes it, more
  bytes than `size` refused, the 5 s poll rule); each proof's ✗ removes the download; `digest` absent is amber;
  Install refused while busy, without a manifest, after the zip changed; Install writes `pending.json` and calls
  `request_exit` only after the answer; the notes tree (headings, lists, code, bold, italic, links, images, raw HTML
  as text, the 20,000 cut); `real_fetch` patched to fail for the whole module.
- **`test_archive.py`**: `check_archive` on crafted zips: `..`, an absolute path, a drive letter, a backslash, a
  symlink, two top folders, a file at the top, no manifest, a manifest mismatch, an unlisted member, a listed file
  missing, an oversize member (its declared size small), more members than the limit (with the limit patched down),
  no `update-helper.py`, another version; `safe_rel`'s cases; the app (`install.helper`) and the helper agree on each.
- **`test_helper.py`**: on a temporary copy of an invented app with an old and a new manifest: a swap (written, added,
  removed into the backup, same files untouched, the edited file in the backup and named in the log); a failure
  planted at each stage (backup, write, a landed hash, remove, manifest) puts every byte back and removes what was
  added; exit 2 for stale, foreign-root, mutex-held (a test mutex name) and `never_touched` cases, with nothing
  touched; settings' relative `workspace_dir` inside root left alone; a held file set aside as `.old`; rollback; only
  the latest backup kept; `result.json` for each outcome; no line of `update.log` or the console holds the temporary
  root's path.
- **`test_install.py`**: `read_pending` (format, fingerprint, patterns, a bad file removed); `install_check` (all
  match, files differing named, no manifest); `cleanup` removes only what it names; `read_result` by nonce.
- **`test_manifest_tool.py`**: the format, the order, the manifest left out, a symlink refused, and `parse_manifest`
  reads what it writes.
- **`test_page_update.py`**: `update.js` is one IIFE; none of the refused calls of §4.7; only its three addresses
  fetched; the release link only behind the `page` field, with `rel="noopener noreferrer"`.
- **Extended:** `test_start.py` (exit 75 after Install; pending's port bound first, the fallback opens the browser;
  the install check's line; `pending.json` removed after page-up; the result served once), `test_ps1.py`
  (`-AfterUpdate`; the 75 branch and the helper's line with the base Python; `.venv.new` and the swap; the R prompt's
  words and the 90 s rule; still no network but pip after Y), `test_launcher_src.py` (the updating message; 0.2.0.0),
  `test_workflows.py` (the manifest step, `--check-zip`, the venv rename on Windows), `test_repocheck.py`,
  `test_integration.py` (the real `Updater` with a fake `Fetch` and the real `Folders` with a fake backend through
  `datapiler.main`).

### 7.2 FOLDERS

- **`test_steam.py`**: `parse_vdf` on invented `libraryfolders.vdf` in both formats, escapes, comments, an unclosed
  brace, an unquoted token, the depth and size limits; `libraries` merges both files and the Steam folder;
  `app_manifest` (installdir, a separator in installdir refused, `dlcappid` values).
- **`test_sbproject.py`**: smithbox-projects.md §6's list, on invented fixtures in its §3 shape: the 2.2.6 shape;
  the default branch's; two marks; none; a `ProjectType` of `"ER"`, of `true` and of `15`; a missing key; a
  non-object; invalid JSON recovered on the second read, and not; a BOM; an oversize file; too many files; a
  network-share path; a relative path; no folder. Files' bytes and mtimes unchanged; no `Configuration.json` read.
- **`test_detect.py`**: each source with a fake backend (registry values from `REGISTRY` only, processes with paths)
  and temporary folders holding empty, invented `Smithbox.exe` and `eldenring.exe`; candidates without their exe
  dropped; merging and the cross-check note; the expansion's yes and no; at start only for blank or missing settings,
  nothing saved; no log line holds a candidate's path, and a candidate is masked as `<FOUND>`; every
  `registry_value(` call in the code takes a `REGISTRY` entry.
- **`test_dirs.py`**: the picker's refusals (relative, `..`, `\\.\`, `\\?\`, UNC, the Windows folder from a fake
  `windows_dir` and inside it) answered as `refused`; files never listed; hidden folders left out; "(no access)";
  `more` past 2,000; `mark`; the order; links listed by name and saved resolved; the 3 s limit with a slow fake
  listing, and a second request for the same drive; drives with letter and kind only; New folder's refusals; the DEBUG
  line holds counts only; every check line of §5.5.
- **Extended:** `test_settings.py` (the project rules, `mask_paths`, `recent` kept and capped, the page cannot set
  it, `load` dropping an unknown key with its line), `test_api.py` (every endpoint of §6 with its refusals; the update
  routes forward to a fake updater and answer 404 without one; with the mask on, no answer's `shown` or `detail`
  holds an invented real folder; the version read from `VERSION`), `test_status.py` (§5.8), `test_page.py` (the files
  assembled in order, one script and one style, the rules over every page file, `#btn-update` before `#quit`, the
  sources lists agree), `test_server.py`, `test_masking.py` (`learn_found`), `test_winapi.py` (the portable answers;
  on Windows only, a registry value every Windows has, `drives()` holding a local `C:`), `test_logbook.py` (the two
  sources).

---

## 8. What each builder must not do

**Both:** write a file §1 gives the other, or one it does not name (ask the lead); commit, push, publish or post
anything; put a real path, a user or machine name, an owner detail, an IP other than `127.0.0.1`, game data or game
text in code, tests, fixtures, docs or log lines, or an assistant model identifier in any file; use a library beyond
the standard library (grpcio and protobuf stay in `link.py` and `soapstone/`); put `str(exception)`, a path, a release
note, a tag or any text from GitHub, Steam or Smithbox into a log line; copy code from PandorumLLM (design 0002 §5) or
anything from Smithbox; change a rule of design 0001 or 0002, S1 to S26 or DP1 to DP14 (a point they leave open goes
to the lead, §10).

**UPDATE:** open a connection anywhere but in `update.py`, or from `update.py` to anything but `HOSTS`; follow a
redirect without `allowed()`; check, download or install from a timer, a start step, a job or a setting; start
anything downloaded but through Install and the window; let the helper write outside DataPiler's folder, touch
`never_touched`, delete a file it could have moved into the backup, or act without a fresh `pending.json` and the
mutex; send the page an absolute path; make the rollback automatic; change the PC's execution policy or ask for
elevation; reach the network in the script except pip after **Y** with 0.1's flags.

**FOLDERS:** walk a drive or search beyond the folder shown; read a registry value outside `REGISTRY`, or anything of
Windows' record of programs started (DP13); read Smithbox's `Configuration.json`, a project's `project.json` for a
game folder, or a window's title (§10 P1); list a file, open a file in a listed folder (`mark` is an existence check
of fixed names), or read a volume label; write, lock or rename any Smithbox or Steam file, or anything in the game's folder; save a
detected value without Use, Choose or Save; log or keep a candidate beyond the session's memory and the mask; browse a
UNC path; touch the update routes beyond forwarding them.

---

## 9. Settled by this plan (for `settled.md`, S27 onwards)

| # | Point | Settled |
|---|---|---|
| S27 | S12a (DP11) | DataPiler reaches the internet after the first start only when the owner presses Update… (the check), Download and Install: `api.github.com`, `github.com` and GitHub's two asset hosts, https only, every redirect checked again, each call logged by host and path. `datapiler/update.py` is the only module that opens a connection to anywhere but `127.0.0.1`, and its calls are reached only from `POST /api/update`; nothing checks on its own, and a download stops when the pop-up has not polled for 5 s. S12 reads "none after the first start, except S27" |
| S28 | The release (design 0002 §4.2) | From 0.2.0 the zip carries `DataPiler/manifest.sha256` (every file but itself, in `sha256sum`'s format) and `DataPiler/update-helper.py`; the release workflow passes the zip through the helper's own `--check-zip` before the draft |
| S29 | The swap (§2.5) | Install re-proves the zip, extracts the helper, writes `update/pending.json` (relative paths, the folder's fingerprint, the port, a nonce) and exits 75; the old window runs the helper with its Python; the helper acts only on a pending file under ten minutes old that names this folder, with the mutex free; it backs up, writes, checks each landed file, moves removed files into the backup, and puts everything back on any failure; it never touches its fixed list or settings' workspace and share folders inside DataPiler's. Only a copy unpacked from a release (with `manifest.sha256`) installs from the button; a job or Extract run blocks Install; the result is shown once, matched by the nonce |
| S30 | Rollback (§4.6) | The owner's R, offered when the new version exits non-zero within 90 s while `pending.json` is still there (its page never came up); never automatic |
| S31 | The venv (§2.5) | Every Y builds `.venv.new` and swaps it in only after pip and the marker succeed; the old one is removed at once, or after an update kept as `.venv.prev` until the new version's page has come up, and put back by R |
| S32 | The project folder (§4.3) | Not the game's folder or inside it (design 0001), not a folder that holds the game's folder, not DataPiler's folder or inside it; `settings.check`, Status and New folder enforce all three |
| S33 | Detect (DP13, §3.4) | Smithbox from the running Smithbox's own process path, then the folders used before; no record of programs started, and no switch for one. The project and game folders from Smithbox's record of its projects (`<Local AppData>\Smithbox\Projects`, from the known folder, read only, as smithbox-projects.md §6), the one marked Elden Ring record tagged as the one Smithbox opens, a format not recognised said so with the picker offered; Steam (its install path in the registry, `libraryfolders.vdf`, the app manifest, the uninstall entry) and the running game as further game sources and the cross-check. The expansion from the app manifest's `dlcappid` values, shown with their ids, never matched against a built-in id. Registry reads only from a fixed table; candidates in memory only, logged as source and count, masked as `<FOUND>`; detection at start for a folder blank or missing; nothing saved without Use, Choose or Save |
| S34 | Check lines and the picker (§3.1 to §3.3) | ✓, ! and ✗; ✗ refuses Use and Choose in the app and Save on the page for a changed folder, and the app refuses the project rules on every save; ! saves. A typed path is saved as typed; Use and Choose save the folder a link resolves to. The picker lists folder names only, answers its refusals as `refused`, gives a listing 3 s and a drive one listing at a time; New folder for the project only. Recent: five a folder, kept by the app |
| S35 | Mask paths on this page (DP14) | `mask_paths`, saved, off by default; on, every path the page draws is the log's mask of it (Settings, Detect's list, the picker, Status's details), the path fields are read-only and Save leaves them as they are |
| S36 | Settings across versions | From 0.2.0, a key `settings.json` holds that this version does not know is dropped at load with a warning naming it, so a version rolled back to keeps the owner's folders; a save from the page still refuses an unknown key, and lays its keys over the current settings |
| S37 | "The Python libraries change" (§2.1) | Known only once the download is verified (its `requirements.lock` against this one), so shown in the ready state; before the download the pop-up says that a `.sha256` and a GitHub digest are published, and the ready state shows them checked |
| S38 | The window's words during an update | The helper's console lines are ASCII (`ok`, `!`, `x`), as `DataPiler.ps1` is |

---

## 10. Open points for the lead

| # | Point | Until verified |
|---|---|---|
| P1 | Smithbox's record of its projects (smithbox-projects.md) | Leads until its §7 passes on the owner's PC (O48): the record's places are offered for Use, never applied; `open_project` informs Status only; `PROJECT_ASK` stays. Its §4 proposes reading the running Smithbox's window title (`EnumWindows`, `GetWindowThreadProcessId`, `GetWindowTextW`) to tell the open project: not built unless the lead adopts it, which would add an adapter call and an S entry |
| P2 | The game's Steam app id 1245620, and the expansion's | 1245620 is a lead, harmless as every candidate needs `eldenring.exe`; the expansion's id is whatever the owner's manifest lists, which the owner reads on the page |
| P3 | GitHub's `digest` on this repository's assets, and the asset host it redirects to | Confirm from 0.2.0's own release before the next one; a missing digest is the amber line, a new host refuses the download with design §2.3's words |
| P4 | Windows behaviour not testable here | The registry, drives and hidden attributes; the 3 s limit on a sleeping drive; the window's mutex re-entered by the new script; ReadKey for R; `os.replace` on a held file; a renamed venv (the CI step); the launcher's message. The Windows CI run covers what it can; the rest is the owner's first update |
| P5 | The first real update | Only from 0.2.0 to the release after it; 0.2.0's notes say the button's install path has not been tried on a real PC |
| P6 | 0.1.0 | Has neither exit 75 nor S36: 0.1.0 users unpack 0.2.0 by hand once, and nothing rolls back to 0.1.0 |

---

## 11. Done means

- Every file of §1 written by its owner, and nothing else changed.
- `python3 -I -m unittest discover -s tests` passes, and with the brief's venv; no test skipped on Linux but the
  Windows-only ones; `python3 -I tools/repocheck.py` passes.
- The privacy sweep passes over every file written; no real path, name or address anywhere; no model identifier.
- `docs/design/smithbox-projects.md` names its commit, files and lines; `settled.md` carries S27 to S38;
  `docs/release-notes/0.2.0.md`, `CHANGELOG.md` and `README.md` say 0.2.0, what is untried, and the unpack by hand.
- Nothing committed, pushed, published or posted: the lead commits.
