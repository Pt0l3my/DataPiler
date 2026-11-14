# Changelog

All notable changes to DataPiler. Versions follow `VERSION` in `datapiler/__init__.py`; a release is tagged
`v<version>`.








## 0.2.7 - 2026-11-14

- Maps load one at a time (S53). Smithbox refuses to start a map load while another runs, so 0.2.3 to 0.2.6 lost nine of
  every ten maps they asked for at once and waited for them in vain. A map not loaded yet is asked for again every
  10 s until Smithbox takes it; the fake server now refuses a load while another runs, as Smithbox does.
- Job cards (S54): the newest job first; each card folds to its title row (▸/▾, remembered in the browser), with Fold
  all and Unfold all; the title row shows the step the job is at and its share done, and every op line its percentage.
- Row reads run four calls at once (S55), the answers kept in the row ids' order; a failure or Cancel stops the rest.
## 0.2.6 - 2026-11-14

- Map loading says what it does (S52): the job card shows maps loaded of maps to load, the time so far and a rough
  guess of the time left, at every poll; the log says how many maps are to load, each batch of ten, and every minute
  how far it is.
- A batch may take as long as Smithbox keeps loading: the job gives up only after 15 minutes with no map loaded, and
  then says why. Smithbox hands a queued map load to its Map Editor only while that editor's tab is in front and its
  window is not minimised (`MapEditorStub.cs` at 2.2.6), which is why en-0007's first run loaded nothing.
## 0.2.5 - 2026-11-14

- Map searches carry their search clause (S51). Smithbox's server library refuses a SearchObjects without one
  (`CheckNonNull(request.Search)`), which DataPiler saw as UNKNOWN: listing the maps sent none, from 0.1.0 on, so every
  map job failed whatever the project's editors. Listing and the loaded check now send an empty clause; the fake
  server refuses a search without one, as Smithbox does.
- A project that lists no map now says to enable the Visual Map Editor (its name in Smithbox 2.2.6's Available
  Editors), press Update Project and restart Smithbox; an UNKNOWN on a map search says the server failed.
## 0.2.4 - 2026-11-14

- DP17 (S48): what `unused_names` makes, numbers and layers only, is not held to check 6's half, so job en-0006's 269
  of 483 name numbers can be shared whole.
- DP18 (S49): check 3 compares with the texts of the name sets DataPiler uses (character and place names), not every
  text imported: with the whole item container imported, ordinary words (a table named `unused`, a log line listing
  files) collided with item descriptions. Copy for sharing leaves a failing line out and says how many, instead of
  refusing the whole copy.
- Quit (S50): the window closes at once after a normal stop, and the page asks the browser to close its tab, which it
  does where the tab holds a single page, as the one the launcher opens does.
## 0.2.3 - 2026-11-14

- `unused_names` (S47): the entries of a text set that no row of a table names, with their layers and, locally,
  their texts. Narrowed from the start, as a pick for a purpose (the names the game sets elsewhere, boss bars among
  them); check 6 measures it against the set's entries.
- Maps (S44): Smithbox lists every map of its project for a file search, loaded or not, so 0.2.x read every map as
  loaded. The link now lists the project's maps (`all_maps`, also `map_ids`, so Extract can load every map) and
  tells a loaded map by an entry search. `open_maps` skips map ids the project does not have and waits for real
  loading; `read_placements` skips such ids and still fails on a map the project has but has not loaded. When the
  server fails on maps (UNKNOWN), the error says the Map Editor is most likely not enabled in the project.
- Map families (S45): `load_maps` and `read_placements` take `m10_*` for every map of an area; a job naming one asks
  before it starts.
- Boss slots (S46): `filter` takes `"slots": "boss"`, keeping placements whose entity id ends 800 to 899, a pick for a
  purpose (DP8).
## 0.2.2 - 2026-11-08

- `join_names` also makes `layer`: the earliest layer of the imported text that holds the name, 0 the base game, 1
  DLC 1, 2 DLC 2, -1 when no name is found (S43). A number, so a count by it is a summary, and a named table keeps it
  beside its ids.
## 0.2.1 - 2026-11-08

- The Imported tab (DP16, the owner's request): the text containers in the text database, with their language,
  wrappers, entries, placeholders left out and which names each holds per layer (base game, DLC 1, DLC 2), counts
  only; what jobs can use now; and Remove, which takes an import out of the database (its export file stays).
- The game's `[ERROR]` placeholder texts are no longer imported, never count as names and are no longer texts for the
  guard's check 3; 0.2.0's imports are cleaned when the database opens, without a new export (S40).
- Extract's names rows end their wait once one export arrives (Smithbox 2.2.6 shows one Item container per language,
  `item_dlc02`, holding the base game and both DLC layers), and their steps follow Smithbox 2.2.6 (S42).
## Unreleased (0.2.0)

Built from [design 0002](docs/design/0002-design.md) and its build plan
([build-plan-0.2.md](docs/design/build-plan-0.2.md)), with the owner's decisions DP11 to DP15; what the build settled
is S27 to S38 in [settled.md](docs/design/settled.md). Not yet tried on a real PC: see the release notes.

- **The Update… button (DP11, S27 to S31, S37, S38).** Three presses: the check (`releases/latest` on GitHub's API),
  the download into `update/<version>/`, and Install and restart. `datapiler/update.py` is the only module that opens
  a connection to anywhere but `127.0.0.1`, reached only from `POST /api/update` (`test_update_static.py` holds it to
  that): GitHub's four hosts, https only, every redirect checked, each call logged by host and path, an answer cached
  for ten minutes and a failure never. The download is proved before anything is unpacked: its size, the release's
  `.sha256`, GitHub's digest, the zip's shape and every file's sha256 in its manifest. Install proves it again,
  extracts the helper, writes `update/pending.json` and exits with code 75.
- **`update-helper.py`**, standard library only: the swap, run by `DataPiler.ps1` from the verified download with the
  Python it found. It acts only on a fresh pending file naming its folder with DataPiler's mutex free, backs up every
  file it will overwrite or remove, writes each new file beside its target and checks the landed file, moves removed
  files into the backup, and puts everything back on any failure; its fixed list (workspace, share, logs, jobs,
  update, the venvs, settings.json and the run-time files) and the workspace and share folders Settings names are never
  touched. `--rollback` is the owner's R; `--check-zip` is the release workflow's check. The app loads the same file to
  prove a download, so both prove a zip the same way.
- **`datapiler/install.py`**: the pending and result files, the install check at each start (every file against
  `manifest.sha256`, a statement, never a repair), and the clean-up once the page is up.
- **`DataPiler.ps1`**: exit code 75 runs the helper, then the new script in the same window with `-AfterUpdate`; a
  failed swap starts the old version again with the helper's reason. Every Y now builds `.venv.new` and swaps it in only
  once pip and the marker succeed; after an update the old venv is kept as `.venv.prev` until the new version's page
  is up. If the new version stops before its page comes up within 90 s, the window offers R.
- **`datapiler.py`**: after an update it binds the old page's port first, so that page reloads itself (a new tab opens
  when the port is taken); exit code 75; the install check, the result kept for the page, and the clean-up at page-up;
  FOLDERS's Detect and UPDATE's Updater wired in.
- **The launcher** says "DataPiler is updating - see its window." while an update runs, and opens nothing.
- **The release** carries `DataPiler/manifest.sha256` (`tools/manifest.py`) and passes the helper's `--check-zip`
  before the draft (S28). CI's Windows job builds the venv as `.venv.new` and renames it, as the script does.
- **The pop-up** (`page/update.js`, `page/update.css`): every state of the design's mock; the release notes as a tree
  of text, never HTML; the restarting wait and the result after the reload.
- **Detect and Set folder… on Settings (DP12, DP13, S32 to S34).** Each of the three folder rows has Detect, Set
  folder… and a live check line (✓, ! or ✗). Detect looks only in what the PC already records, never walking a drive:
  the running Smithbox's own exe path (`QueryFullProcessImageNameW`), Smithbox's record of its projects for the project
  and game folders (`datapiler/sbproject.py`, a lead until checked on the owner's PC; a form it does not recognise is
  said so, with the picker offered), Steam's install path, `libraryfolders.vdf`, the game's app manifest and the
  uninstall entry (`datapiler/steam.py`, registry values from a fixed table only) and the running game as further game
  sources and the cross-check, and the folders used here before. The expansion comes from the app manifest's
  `dlcappid` values, shown with their ids, never matched against a built-in one. Windows' record of programs started
  is not read (DP13). Nothing is saved until Use, Choose this folder or Save; candidates live in memory only, and log
  lines name the source and the count, never a path. The picker (`datapiler/dirs.py`, `page/folders.js`) is drawn in
  the page: folder names only, never a file; it refuses relative and device paths, network shares and Windows' own
  folder; a listing gets 3 s; New folder… in the project picker only. The project folder may not be the game's
  folder, inside it, a folder that holds it, or DataPiler's own folder or inside it (S32).
- **Smithbox seen by its process (DP15).** A watcher reads the process list every 2 s from the start, whatever
  Settings say: the top bar's pill and the Status card read "running" as soon as Smithbox runs, name the exe and its
  build, and say when it stops; two processes are both listed. A running Smithbox in another folder than the one set
  is offered with Use. Smithbox is recognised by any `Smithbox*.exe` (`Smithbox.Vulkan.exe` and
  `Smithbox.OpenGL.exe`, side by side in one folder on the owner's PC), in the folder check, the build, the
  provenance, Detect and the picker.
- **Mask paths on this page (DP14, S35)**, off by default: every path the page draws becomes the log's placeholder
  (Settings, Detect's list, the picker's crumbs, Status), and the path fields turn read-only.
- **Settings across versions (S36):** a key `settings.json` holds that this version does not know is dropped at load
  with a warning, so a version rolled back to keeps the owner's folders; `recent` keeps five folders a row.
- **Found by the integration run** (headless Chromium over invented folders and an invented release): off Windows the
  page's server sets `SO_REUSEADDR`, so the page that asked for an update gets its port back past `TIME_WAIT`, as
  Windows allows without it (still off on Windows); the page's own polls pause while an update restarts, so the old
  page sends nothing with its old token; Detect's log lines say "1 place" and "1 DLC app"; the start line names
  `Smithbox*.exe` when the folder holds no Smithbox exe.
- **Found by the 0.2.0 reviews** (security and correctness):
  - The swap holds off Ctrl+C (the helper ignores it, and the window makes it a key while the helper runs), and an
    interrupt is put back like any failure. A swap cut off all the same (the window closed, the power cut) is put
    back by the window from its backup, after the helper's exit or at the next start: `--rollback` now accepts an
    unfinished backup while `update/pending.json` names the same update, and writes back only what differs.
  - The old window offers R also when the new version's script stops before it starts its app, or cannot run (the
    new script exits 76 when it has settled R itself); a failed R waits for Enter.
  - The never-touched list is checked against the path as the file system resolves it, and a release may not name
    an 8.3 short name (`~` and a digit; `tools/repocheck.py` fails one too); a file whose name changes only in case
    is rewritten, never deleted after it.
  - Mask paths: the picker draws each folder's name masked (the account's folder as `<HOME>`) and opens it by its
    real path, and Up goes to the real parent; the folders Smithbox runs from are taught to the mask as soon as they
    are seen; a folder's mask ends where its name ends (`...\Smithbox` no longer masks `...\Smithbox-old`), and a
    known sibling is matched before a shorter named folder.
  - The provenance's `smithbox_build` is the running Smithbox's, whatever its folder; Smithbox processes of
    different builds refuse the write.
  - Detect no longer proposes Yes for the expansion from any DLC app id: with ids listed, Yes and No are both offered
    and neither is the primary button.
  - The picker refuses Windows' own folder also with a trailing dot or space (`C:\Windows.`), waits for a drive's
    listing under way instead of answering that the drive did not answer, and a folder on a mapped drive is saved
    with its drive letter.
  - S27 and S12 name pip's two hosts, used after an update whose libraries changed and the owner's Y.
- **The version is 0.2.0**: `VERSION`, the launcher's resources, BUILD.md. A job's `needs` above 0.2.0 is refused.
- **Releases carry fewer files (DP9):** the zip (with the exe and the notices inside), its sha256, and
  `THIRD-PARTY-NOTICES.txt` on its own too; the exe's sha256 is in the release workflow's log, which the notes link.
  The README's Licence section names the notices.
- **The zip's one folder is `DataPiler` (DP10):** the zip's name keeps the version; the folder inside does not.

## 0.1.0 (2026-11-08)

The first version, built from [design 0001](docs/design/0001-design.md), what was settled from it and by the build
([docs/design/settled.md](docs/design/settled.md), S1 to S26) and the owner's decisions DP1 to DP8.

- **Start and stop.** `DataPiler.exe`, a small launcher adapted from LLM Jobrunner 1.2's (DP7): one PowerShell window
  running `DataPiler.ps1` and the app, the page opened in the browser once it is up, a second start opening the
  running page (the app's mutex `Local\DataPiler`, and the window's `Local\DataPiler-window` while it is still
  starting). Quit on the page, closing the window and Ctrl+C all stop it cleanly.
- **The window's script.** `DataPiler.ps1` finds Python 3.10 or newer, and at the first start asks before making
  `.venv` from `requirements.lock` (wheels only, every file checked by its sha256): grpcio and protobuf, and
  typing-extensions, which grpcio needs. Answering N starts DataPiler without the server link, so jobs, which all read
  from Smithbox first, wait for it.
- **The page**, on `127.0.0.1` only, with a per-start token and a strict content-security policy: Status, Extract,
  Jobs, Outputs, Terminal and Settings, as the mock shows them.
- **Smithbox's status**, read from disk: its folder, build, whether it runs, its server's switch in `Startup.json`
  (read, never written), and the checks that the game is closed and the project folder is not the game's.
- **The server link**: Smithbox's local server, read calls only from a fixed list of seven, off at every start, and
  only while the game is closed; a watcher closes it within seconds if the game starts.
- **Extract**: the catalogue's rows and bundles (Roster, Placements, Places, Everything), from the server link or
  from Smithbox's text exports dropped in the workspace's inbox.
- **Jobs**: `datapiler-job/1` files dropped on the page, checked on arrival against a closed set of operations,
  previewed, and run only on Start; `schema/datapiler-job-1.schema.json` describes the format.
- **The guard**: every share file (`datapiler-share/1`) is checked before it is written, by six checks: numbers and
  DataPiler's own labels only, no text from the game's text database (string values only, DataPiler's own fixed words
  skipped: S20; compared as they are and with accents and the signs between words set aside, so `white_mask_varre`
  is a text's name still: S25), no path, the PC's or the user's name (whatever signs stand between its parts: S26) or
  an address, the size, and (check 6, DP8) no table, nor the file's tables from one game table together, covering
  more than half of that game table's rows: every table but counts alone is measured, by its rows or groups, or by a
  param's row ids where none repeats, and placements by their rows against the maps read, each once (S19). The row counts check
  6 needs are kept in the workspace, so Outputs runs all six again on every share file, and one DataPiler did not
  write never passes. Copy for sharing checks the log lines by the same rules.
- **What a share file may hold (DP8)**: ids and numbers only for rows a job picked for a purpose. Each table carries
  its lineage; a job that would share a table straight from `fetch_rows` or `read_placements`, a filter or distinct
  of one, or a count of one by its row id or by a column of other tables' ids (`nameId`, `msgId`; a placement's
  `npcParamId`, `talkId`, `model`), is refused on arrival, naming the operation and the rule. A filter's new `ids` (an explicit list of 1 to
  1,000 row ids) narrows a table, as does keeping the named rows after `join_names`. Extract's own share files hold
  counts only.
- **The expansion (S21)**: the owner says in Settings whether it is installed (yes or no, not stated at first); share
  writes wait for the statement, and the provenance records it as the owner's.
- **The names (S22)**: the character and place names' text ids are EldenNet's research leads (428, 328 and 18; 429,
  329 and 19), checked against the owner's own data at each `join_names` (at least half must resolve); the share
  file's provenance records the share that did. The Place names row waits for the same exports as the Character names.
- **Logging**: one log to the window, to rotating files and to the Terminal tab, with folders masked as
  placeholders; Copy for sharing checks the lines first.
- **The repository**: CI runs the tests on Linux and Windows (with the lock's libraries on Windows), builds the
  launcher, and runs `tools/repocheck.py` (S14); a version tag builds the exe on Windows and attaches it with its
  sha256 and the MinGW-w64 runtime's notices to a draft release (S4), beside one zip of the whole app (the tagged
  source with the exe and its notices placed in it) and its sha256 (S24). The exe's check reads `file`'s wording of
  5.45 and of 5.46 and later alike. `.gitattributes` keeps every checkout LF.
- **A refused upload gets its answer**: a request refused before its body is read (too large, no token, no length)
  now has its answer sent, then the rest of its body read and dropped (up to 8 MB or 3 s) before the connection
  closes; closing with the body unread let Windows reset the connection before the client read the answer.
- **Releases**: a draft release can also be started with the release workflow's Run workflow button (the session
  that builds DataPiler cannot push tags); its notes come from `docs/release-notes/<version>.md`.
