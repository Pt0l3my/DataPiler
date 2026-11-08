# Changelog

All notable changes to DataPiler. Versions follow `VERSION` in `datapiler/__init__.py`; a release is tagged
`v<version>`.

## 0.1.0 (unreleased)

The first version, built from [design 0001](docs/design/0001-design.md), what was settled from it
([docs/design/settled.md](docs/design/settled.md), S1 to S14) and the owner's decisions DP1 to DP7.

- **Start and stop.** `DataPiler.exe`, a small launcher adapted from LLM Jobrunner 1.2's (DP7): one PowerShell window
  running `DataPiler.ps1` and the app, the page opened in the browser once it is up, a second start opening the
  running page (the app's mutex `Local\DataPiler`, and the window's `Local\DataPiler-window` while it is still
  starting). Quit on the page, closing the window and Ctrl+C all stop it cleanly.
- **The window's script.** `DataPiler.ps1` finds Python 3.10 or newer, and at the first start asks before making
  `.venv` from `requirements.lock` (wheels only, every file checked by its sha256). Answering N starts DataPiler
  without the server link.
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
- **The guard**: every share file (`datapiler-share/1`) is checked before it is written: numbers and DataPiler's own
  labels only, no text from the game's text database, no path, name or address.
- **Logging**: one log to the window, to rotating files and to the Terminal tab, with folders masked as
  placeholders; Copy for sharing checks the lines first.
- **The repository**: CI runs the tests on Linux and Windows (with the lock's libraries on Windows), builds the
  launcher, and runs `tools/repocheck.py` (S14); a version tag builds the exe on Windows and attaches it with its
  sha256 and the MinGW-w64 runtime's notices to a draft release (S4). `.gitattributes` keeps every checkout LF.
