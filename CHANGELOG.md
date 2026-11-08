# Changelog

All notable changes to DataPiler. Versions follow `VERSION` in `datapiler/__init__.py`; a release is tagged
`v<version>`.

## 0.1.0 (unreleased)

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
