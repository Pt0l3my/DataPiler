# DataPiler: the design, in answer to request 0001

*As received from the PandorumLLM session on 2026-11-08, by way of the owner; committed unchanged except that three
references to the owner were made gender-neutral. Its mock is [0001-mock.html](0001-mock.html), the request
[../requests/0001-design.md](../requests/0001-design.md); what was settled from it is [settled.md](settled.md).*

From the PandorumLLM session, for the EldenNet design session, by way of the owner (2026-11-08). With it:
`DataPiler-mock.html` (here [0001-mock.html](0001-mock.html)), a static mock of the page that opens in a browser. It has the six tabs and their states, and
makes no network calls.

DataPiler follows the request's rules (DP1 to DP5, and "Rules it must keep") as written. Where this design adds a rule
or suggests changing one, it says so. Those points are collected in §7.

---

## 1. Shape, in one paragraph

`DataPiler.exe` is a small native launcher. It opens one PowerShell window, and runs `datapiler.py` inside it. The
Python app serves the page on `127.0.0.1` and writes the log, to that window, to rotating files and to the page's
Terminal tab. It reads Smithbox's state from disk, and calls Smithbox's local server only when the owner switches the
link on and the game is closed. The app keeps two folders:
- the **workspace**, local only, which may hold game text;
- the **share folder**, whose files pass the guard before they are written.

Jobs are JSON data with a closed set of operations, dropped on the page and run on Start. It is Jobrunner's shape, with
three differences: the PowerShell window, two libraries beyond the standard library, and the guard.

```
DataPiler/                       the folder the owner unpacks; DataPiler writes only inside it
  DataPiler.exe                  the launcher (§3)
  DataPiler.ps1                  the window's script: checks Python, prepares the environment, runs the app
  datapiler.py                   the app: page, Smithbox reads, the server link, jobs, guard, log
  datapiler/                     the app's modules (link.py, guard.py, jobs.py, smithbox.py, textdb.py, logbook.py)
  soapstone/                     the generated gRPC messages for the allowed calls only (§4), with SoapstoneLib's MIT notice
  requirements.lock              grpcio and protobuf, wheels only, a sha256 for every file (§4)
  launcher-src/                  the launcher's source, its icon, its manifest; BUILD.md
  .venv/                         made at first start, on the owner's confirmation (§4) - not in the repository
  workspace/                     local only: text database, raw reads, guided exports - not in the repository
    inbox/                       the folder DataPiler watches for Smithbox's guided exports
  share/                         share files, each one guarded - not in the repository
  logs/                          datapiler.log and its rotations; jobs/<job>.log - not in the repository
  jobs/                          dropped job files, as dropped, and their state - not in the repository
  datapiler.port                 the page's port, written once the page is up
  datapiler-start.log            what went wrong, if the page never came up
  settings.json                  the owner's settings
```

The workspace and share folders default to these two, and Settings can move them. A share file never carries a path,
so moving them changes nothing in the files.

---

## 2. The page

The page has a single origin on `127.0.0.1` and a token made at each start. It sends Jobrunner's headers: CSP
`default-src 'none'` with a nonce for its one script and one style, `X-Frame-Options: DENY`, `no-store`, and no CDN,
font or image from anywhere else. It is a sibling of Jobrunner and PandorumLLM:
- the same dark ground and lime accent (`#b5f320`), cards and pills;
- a ✓ in green, a warning in amber, a refusal in red;
- each description behind a "?" beside its title, as PandorumLLM does since v3.98 patch15.

**The top bar**, always visible:
- **DataPiler 0.1** and three pills:
  - **Smithbox** (running / not running);
  - **Game** (closed / running - red while running);
  - **Server link** (off / on / blocked - off at every start).
- **Quit** on the right.
- One line under the bar when something blocks a run, saying what and where to fix it. For example: "The game is
  running - the server link waits until it closes."

### Tabs
1. **Status.** One card for Smithbox and one for the game, each a list of checks with ✓ or ✗ and what to do:
   - **Smithbox:**
     - installed, and where (shown as `<SMITHBOX>` and, behind its "?", the real path - the page is local);
     - its build;
     - running;
     - the server's switch, `System_Enable_Soapstone_Server` in `Startup.json` (read, never written);
     - the server's port answering;
     - the project that is open.
   - **The game:**
     - its folder;
     - its version, read from `eldenring.exe`'s own version resource;
     - whether `eldenring.exe` (or its launcher `start_protected_game.exe`) is running;
     - whether the expansion's files are present;
     - the hash of `regulation.bin`. It goes into the provenance block, and is computed once per change of the file.
   - **The project:** its folder, which must be neither the game's folder nor inside it - a red ✗ and "Choose a project
     folder outside the game's" otherwise.
   - **The server link:** the switch for this session. With it off, the page says what would be called. With it on:
     the calls made, and the last call's time.
2. **Extract.** The catalogue is a table, one row per data type, each row a tick box with:
   - its name and a "?" with what it gives;
   - **From:** a pill, *Server* or *Guided export*;
   - **Gives:** a short phrase;
   - **Goes to:** *Workspace* (local), or *Workspace + share* when a numbers-only file is made from it.
   - The bundles sit above the table as chips (*Roster*, *Placements*, *Places*, *Everything*). A chip ticks its rows;
     a row ticked by hand clears the chip's highlight. The rows each bundle holds are in §6.
   - **Run** starts the ticked rows, server rows first.
   - Each row shows its own progress in its last cell: "waiting", a bar with "312 of 2,105 rows", "map 14 of 98", or
     "✓ 2,105 rows, 0.4 s".
   - **A guided row** opens its steps in place, numbered as Smithbox names them. For example:
     1. Open the Text Editor;
     2. choose the container `item`;
     3. Export;
     4. save into `<WORKSPACE>\inbox`.

     Its cell then shows "waiting for the export". DataPiler sees the file arrive and checks that it is Smithbox's
     export, of that container and language. It imports the file into the text database and moves it to
     `workspace/imported/`, and the cell turns ✓.
   - Rows that need what is missing are greyed, with the reason behind their "?": "the server link is off", "the game
     is running", "load the maps in Smithbox first".
3. **Jobs.** A drop zone, and **Choose file**. Each dropped file becomes a card, checked on arrival (§6):
   - its title, the job's id and schema version, its sha256;
   - **Reads**, **Computes** and **Writes** - three short lists in DataPiler's own words, from the job's operations
     ("NpcParam rows: id, nameId, teamType"; "join with the character names - local"; "share file
     `roster-counts.json`: 4 tables");
   - the check's result: ✓, or each refusal with its operation's number;
   - **Start**, **Cancel**, **Remove**. Nothing runs until Start.
   - Running: each operation a line with its state, as a run of Extract rows reads.
   - Done:
     - the share file's name, size and sha256, and **Show** (it opens on Outputs);
     - the local files it wrote (Workspace);
     - or the step that failed and why. A guard failure names the check that failed, never the text.
4. **Outputs.** Two panes side by side, each a list of files with size, time, the job or extract that made it, and
   **Open folder**:
   - **Workspace**, under a red pill *Local only - never share*;
   - **Share**, under a green pill *Passed the guard*.

   A share file opens in a viewer: its exact bytes, pretty-printed, its sha256, and the guard's report (each check
   ✓). The owner reads that before sharing it. **Copy path** puts the file's own path on the clipboard for the upload
   dialog; nothing else leaves the page.
5. **Terminal.** The log, live: the same lines the PowerShell window shows. Each line has a time, a level and a source,
   warnings amber and errors red. Filters by level and source; **Pause scroll**; **Copy visible**. The lines are already
   masked (§5), so copying them is safe.
6. **Settings.**
   - the Smithbox folder, the game folder, the project folder, the workspace and share folders;
   - the text language (Smithbox's code, e.g. `engus`);
   - the page's port (blank for any free one);
   - the log's size and how many files it keeps;
   - **Server link this session** (off at each start).

   The server's address is fixed at `127.0.0.1:22720` and shown, not editable. An address field invites the one
   thing the rules forbid.

The mock (`DataPiler-mock.html`) shows every tab in a typical state: Smithbox running with its server on, the game
closed, a Roster run in progress, a job checked and waiting for Start, a share file open in the viewer, and a log.

---

## 3. The launcher and the PowerShell window

### What happens
1. **`DataPiler.exe` starts.** It checks for the named mutex `Local\DataPiler` (held by a running app):
   - **Held:** DataPiler is running. The exe reads `datapiler.port`, opens the page in the browser and exits. No second
     window opens.
   - **Not held:** it starts `pwsh.exe` (PowerShell 7) if it is on PATH, else Windows PowerShell 5.1:
     ```
     -NoLogo -NoProfile -ExecutionPolicy Bypass -File "<folder>\DataPiler.ps1"
     ```
     The window is visible, titled **DataPiler**, in DataPiler's folder. `-ExecutionPolicy Bypass` applies to that one
     process; nothing is changed on the PC.
2. **`DataPiler.ps1`:**
   1. sets the title and the console's colours, and prints a one-line banner with DataPiler's version;
   2. finds Python 3.10 or newer (`py -3`, then `python`) and says plainly if there is none;
   3. makes `.venv` on the first start if it is missing or does not match the lock - see §4, which asks first;
   4. runs `.venv\Scripts\python.exe datapiler.py --console` **in the same window**.

   The app writes its log to that console (colour codes, which Windows 10 and 11 consoles render). The window is the
   app's own console, not a tail of a file. One process tree; nothing to keep in step.
3. **The exe waits for the port file.** `datapiler.port` must be written since this start began, as Jobrunner's
   launcher reads it. The exe then opens `http://127.0.0.1:<port>/` and exits. After 60 s it says "DataPiler did not
   start - its window says why". 60 s, not 24: a first start may be making the environment.
4. **The app** takes the mutex and binds `127.0.0.1` on the set port, or any free one. It writes `datapiler.port`
   atomically, and logs "Page: http://127.0.0.1:<port>/ (the browser opens it)".

### How it ends
- **Quit on the page:** `POST /api/quit` with the token. The app answers, stops the server link, finishes or cancels
  the running job (it asks first if one runs), flushes the log and releases the mutex. It removes `datapiler.port` and
  exits with code 0.
  - The script then prints "DataPiler has stopped - this window closes in 5 s" and exits.
  - With any other exit code it prints the code and "press Enter to close", so a crash stays readable.
- **Closing the window:** Windows ends the app with it (the console's close event). The app catches it, logs "window
  closed - stopping", and stops as Quit does. Windows allows about five seconds for that. The page sees no heartbeat
  answer and says "DataPiler has stopped".
- **Ctrl+C in the window** is the same as Quit.

### Reusing Jobrunner's launcher
Jobrunner's launcher is the owner's code: a C++ file of about 120 lines, its icon, manifest and resource script, built
as `BUILD.md` says. Reusing it in DataPiler is the owner's to decide. If the owner agrees:
- **Copy it,** don't link it: its source goes into DataPiler's `launcher-src/` under DataPiler's MIT licence, with one
  line in the README saying where it came from. Nothing changes in Jobrunner, and neither repository depends on the
  other.
- **Changes needed:**
  - start PowerShell with the script, visibly, instead of `pythonw` with no window;
  - the mutex check before anything starts, so a second start opens no second window;
  - the 60 s wait;
  - DataPiler's name, icon and version.

  It keeps Jobrunner's rules: `asInvoker` (no elevation), no Python inside the exe, no socket probing, and a stale port
  file never trusted.
- **The app's half** comes too, with the same terms: the guard (Host, Origin, token), the CSP and headers, the atomic
  port file, the drop zone with its check on arrival and its cards, the Terminal tab's renderer and the start log.

**The exe's build.** Two routes give the same exe:
- **The `BUILD.md` route:** MinGW-w64 cross-compile, about 200 KB, reproducible apart from the PE timestamp. Six bytes
  differ.
- **A GitHub Actions build on Windows (recommended for a public repository):** a workflow on a tag builds the exe from
  `launcher-src/` on `windows-latest` with MSYS2's MinGW-w64 and the same flags. It attaches the exe and its sha256 to
  the release, so anyone can see the exe was made from the source in the repository. Publishing stays the owner's
  act, as the workflow runs only on a tag the owner pushes.

  The exe is unsigned either way, so Windows' SmartScreen warns on the first start (More info, Run anyway). The README
  says so, as Jobrunner's does.

---

## 4. Python, grpcio and protobuf

**Recommended: a local virtual environment made at the first start, from a lock, on the owner's confirmation.** This
is the route PandorumLLM's Converter already takes for its own Python.

- **`requirements.lock`** names `grpcio` and `protobuf` (and their dependencies, if any), each pinned, **wheels only**,
  with the sha256 of every wheel file for each Python version DataPiler supports on Windows x64.
- **The first start.** The script sees no `.venv`, or one that does not match the lock's hash. It prints what it will
  do: the two packages, their versions and licences (Apache-2.0, BSD-3-Clause), about how many MB, and from
  `pypi.org` over https. It waits for **Y**. Then:
  1. `python -m venv .venv`;
  2. `pip install --require-hashes --only-binary=:all: --no-deps -r requirements.lock`.

  pip refuses any file whose sha256 differs. No later start touches the network. **N** starts DataPiler without the
  server link: the guided exports, jobs on what is already in the workspace, and Outputs all work, and Extract's server
  rows say "the server link needs its two libraries - restart DataPiler and answer Y".
- **The supported Pythons** are the ones whose win_amd64 wheels the lock carries. This is decided when the lock is
  made, from what grpcio and protobuf publish then - expect 3.10 and newer. The script names them when the Python it
  finds is not one of them.
- **The gRPC messages.** SoapstoneLib's `.proto` files (MIT) are compiled once, at a pinned commit, into
  `soapstone/*_pb2.py`. That is done when the repository is made, with `grpcio-tools` on the maintainer's machine, not
  at the owner's. The generated files are committed with SoapstoneLib's licence and the commit they came from. The
  generated code pins the protobuf runtime it needs, so the lock's protobuf matches it.
- **The allowlist is a module.** `datapiler/link.py` is the one place that calls Smithbox:
  - one channel, to `127.0.0.1:22720` only;
  - one method per allowed call (`ListParams`, `ListParamRows`, `GetParamRows` with `vanilla=True` forced,
    `SearchObjects`, `GetObject`, `BatchGetObjects`, `OpenResource` with a map resource only);
  - each built with `channel.unary_unary("/<service>/<Method>", ...)` from a fixed table, so no stub with the other
    calls is generated or imported.

  A test fails the build if any other method name appears anywhere in the code. Every call passes through one
  function:
  - it checks the game is closed (a process check, `CreateToolhelp32Snapshot` through ctypes);
  - it checks the session's switch is on;
  - it logs the call's name and counts, never its data.

  A watcher checks the game every 2 s while the link is on. If the game starts, the channel closes at once and the
  link shows *blocked*.

**Wheels in the release**, the other route, means a 10 to 20 MB release per Python version. It also redistributes
binaries, which their licences allow with their notices, but which then have to be kept current. I would not ship
them.

**A third route, not chosen: no libraries at all.** The calls DataPiler makes are unary. A minimal HTTP/2 (h2c) client
with hand-encoded protobuf messages could be written with the standard library alone, as Jobrunner is. It would be a
few hundred lines of protocol code to get right and keep right against Smithbox's server, so I would take the two
libraries. If the owner prefers stdlib-only above all, this is the way, and the allowlist becomes the only messages the
client can encode at all.

---

## 5. Logging

- **One format, everywhere** - the window, the files, the Terminal tab:
  ```
  2026-11-08 08:42:01.123  INFO   extract  NpcParam: 2,105 rows read in 0.4 s
  2026-11-08 08:42:03.877  WARN   link     the game started - the server link is closed
  2026-11-08 08:43:10.002  ERROR  guard    roster-counts.json not written: check 3 (a string the text database holds)
  ```
  The time is local, to the millisecond, followed by the level (`DEBUG`, `INFO`, `WARN`, `ERROR`). The source is one
  of `app`, `page`, `smithbox`, `link`, `extract`, `job`, `guard`, `textdb`, `env`, and the message comes last.
- **Levels.**
  - `DEBUG` goes to the file only, and only when Settings turns it on for the session.
  - The window and the Terminal tab show `INFO` and up: `WARN` in amber, `ERROR` in red.
- **Rotation.** `logs/datapiler.log`, 2 MB a file, five files kept (the standard library's `RotatingFileHandler`), and
  each job's own `logs/jobs/<job id>.log`. A start writes a separator line with DataPiler's version.
- **What a log line may hold.** Ids, counts, times, file names DataPiler made, operation names, and DataPiler's own
  words.
  - **Never game text.** No name, dialogue or description is ever put into a log message. The code builds messages
    from numbers, and a test runs every message template with a planted name to prove it.
  - **A guard failure** names the check and the field's place (`tables[1].rows[40][2]`), never the value.
- **The placeholders.** A filter on every handler replaces known folders, longest first:
  - the game's folder → `<GAME>`, Smithbox's → `<SMITHBOX>`, the project's → `<PROJECT>`, the workspace → `<WORKSPACE>`,
    the share folder → `<SHARE>`, DataPiler's → `<DATAPILER>`;
  - the home folder → `<HOME>`;
  - the user name → `<USER>`, the PC's name → `<PC>`, any IP other than `127.0.0.1` → `<IP>`.

  Folders match in either slash, any case, and Windows' short 8.3 names too. A word matches only where it stands as
  a word. This is the rule PandorumLLM's log uses since v3.98 patch13. Its lesson: mask at the formatter, not at each
  call - one call site that forgets is enough.
- **The Terminal tab** reads `GET /api/log?after=<seq>` every second. The app keeps the last 5,000 lines in memory,
  already masked. The tab never reads the files, so what it shows is what the window shows.
- **The start log.** `datapiler-start.log` is written only if the page never came up: the exception, the Python found,
  the venv's state. The launcher's message points at it.

---

## 6. Jobs, and the files they write

### The flow
1. **Drop or choose** a file on Jobs. The page uploads it, and nothing is read from a path the page names. It is kept
   as dropped in `jobs/<job id>/job.json`.
2. **The check, at once:**
   - a JSON object of at most 256 KB, nesting at most 16 deep;
   - `format` is `datapiler-job/1`;
   - every field known, every operation from the closed set, every argument of its declared type and range;
   - names only, never paths, for everything it writes;
   - `id` unique among the jobs here.

   A refusal names the field and the rule: "ops[3].fields[1]: `teamName` is not a field DataPiler reads (ids and
   numbers only)". An unknown field is refused, not ignored, since the job's author is you and a typo should say so.
3. **The preview:** Reads / Computes / Writes, in DataPiler's words, built from the operations, so the owner sees
   what it will do in plain terms.
4. **Start** (the owner's click). The job waits while the link is off or the game runs, and says which.
5. **Progress:** each operation a line, with its count as it goes. **Cancel** stops between calls.
6. **The result:**
   - the share file, guarded and then written, with its sha256;
   - the local files;
   - `job.log`, masked.

   A job that fails writes no share file and says which operation failed and why.

### The job file: `datapiler-job/1`
```json
{
  "format": "datapiler-job/1",
  "id": "en-0007-roster-counts",
  "title": "Roster: named characters per team",
  "ops": [
    {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId", "teamType", "npcType"]},
    {"op": "fetch_rows", "as": "talk", "param": "TalkParam", "fields": ["id", "msgId"]},
    {"op": "join_names", "as": "npc_named", "rows": "npc", "key": "nameId", "text": "character_names"},
    {"op": "count", "as": "per_team", "rows": "npc_named", "by": ["teamType"], "where": {"named": true}},
    {"op": "write_share", "name": "roster-counts", "tables": ["per_team"],
     "columns": {"per_team": ["teamType", "count"]}}
  ]
}
```
The closed set, each operation's arguments fixed:

| op | does | writes |
|---|---|---|
| `fetch_rows` | a param's rows through the server (`vanilla = true`), only the named fields, numbers only | a working table |
| `load_maps` | loads maps in Smithbox (`OpenResource`, map resources only) - `maps`: a list of map ids, or `"all"` | nothing |
| `read_placements` | the placed characters of loaded maps (`SearchObjects`, `BatchGetObjects`): entity id, character row id, dialogue id, model number | a working table |
| `join_names` | joins a table with the local text database by a name number; the names stay in the workspace, and the table gains `named` (true/false) | a working table, local |
| `filter`, `count`, `distinct` | on working tables: `where` on numbers and booleans, `by` on fields | a working table |
| `write_local` | a working table to the workspace, names allowed | a workspace file |
| `write_share` | the tables and columns named, through the guard | one share file |

A job writes at most one share file. It reads only through the operations above, and writes only into DataPiler's
folders, by name. It cannot run a command, name a path, reach a network other than Smithbox's local server, or carry
code - nothing in it is evaluated or used as a template. A JSON Schema of the format (draft 2020-12),
`schema/datapiler-job-1.schema.json`, is in the repository for you to validate against before you send a job.
DataPiler checks the same rules again itself.

### The share file: `datapiler-share/1`
```json
{
  "format": "datapiler-share/1",
  "job": {"id": "en-0007-roster-counts", "sha256": "<64 hex - the job file as dropped>"},
  "provenance": {"game_version": "2.6.1.0", "regulation_sha256": "<64 hex>", "expansion": true,
                 "language": "engus", "smithbox_build": "2.1.3", "datapiler": "0.1.0", "date": "2026-11-08"},
  "tables": [
    {"name": "per_team", "columns": [{"name": "teamType", "type": "int"}, {"name": "count", "type": "int"}],
     "rows": [[0, 112], [6, 48], [24, 9]]}
  ],
  "notes": ["named_only"]
}
```
The values above are placeholders that show the format, not read from a game.
- `columns[].type` is one of `int`, `bool`, `enum:<name>` (an enum DataPiler defines, e.g. `enum:source` with
  `server`, `guided`) and `label`.
- `notes` holds labels only.
- Keys come from the format, never from data.

### The guard
A share file's bytes are checked before they are written. All checks run, and the first failure stops the write:
1. **Shape:** the format above; only its keys; tables and columns as the job declared.
2. **Values:** every value an integer, a boolean, a value of a declared enum, or a label from DataPiler's fixed list.
   No other string, and no float (§7 suggests allowing finite numbers).
3. **Text:**
   - no string in the file equals, case-folded, any text in the local database;
   - no string of 4 or more characters is contained in one, or contains one.
4. **The owner:** no path (no `\`, `/`, drive letter or `~`), no user name, no PC name, no IP address. This also
   applies to the labels list itself, checked once at start.
5. **Size:** at most 4 MB and 200,000 values, so a mistake cannot write a table dump.

A failure writes nothing. It names the check and the place - "check 3 at `notes[0]`" - and the page shows exactly that.

### The catalogue's bundles, as rows
- **Roster:** Character rows, Character names (guided), Dialogue links.
- **Placements:** Map placements (needs the maps loaded; the row offers to load them through `OpenResource` first).
- **Places:** Places (server), Place names (guided).
- **Everything:** all of them.

---

## 7. What the request leaves open, and where the rules could be easier

1. **Floats.** Some character fields are floats. "Integer, enum or label" refuses them. A finite number cannot carry
   text, so the guard could allow any finite JSON number and still keep every word out. Suggested: allow finite
   numbers; keep NaN and infinities out.
2. **Labels against the text database.** A label of ours that happens to be a game word ("Roster", "Places") would
   fail check 3 forever. Suggested:
   - check 3 skips values that are exactly a label from the fixed list;
   - the list is checked once against the text database when it is built, and a label found there is renamed.
3. **The game check.** "The game closed" should mean neither `eldenring.exe` nor `start_protected_game.exe` (Easy
   Anti-Cheat's launcher) is running. With the game's folder known, an exe of that name started from elsewhere is
   also caught.
4. **`OpenResource` changes Smithbox's state.** It loads maps into the editor - nothing written to data, but memory
   used and the editor's view changed. The Extract row should say so and load maps in batches. Suggested: ask before
   loading more than ten maps.
5. **The server has no authentication.** DataPiler only reads, but any program on the PC can call it while it is on.
   - The Status card shows the switch's state in `Startup.json`. When the link goes off at the end of a session, it
     says "Smithbox's server is still on: switch it off in Smithbox's settings (`System_Enable_Soapstone_Server`) or
     restart Smithbox with it off".
   - DataPiler never edits `Startup.json` itself: Smithbox's files are read only.
6. **Guided exports need a contract.** DataPiler should accept a guided export only by its shape: Smithbox's text
   export format, the container named in it, the language. Not by file name. A file that is not one stays in the
   inbox with "not a Smithbox text export of `item`".
7. **Sharing logs.** Logs are masked and hold no game text by construction, but the owner may still share one. Suggested:
   **Copy for sharing** on the Terminal tab runs checks 3 and 4 over the lines first.
8. **No outbound network at all after the first start**, and none at the first without the owner's Y. The page loads
   nothing from elsewhere.
9. **Versions.** The share file names DataPiler's version. A job may say `"needs": "0.2"`, refused clearly by an older
   DataPiler.
10. **The repository.** Beyond the `.gitignore`, a CI check could fail a pull request that adds any file under
    `workspace/`, `share/`, `logs/` or `jobs/`, or any `.json` carrying `datapiler-share` with a path in it. That is
    cheap, and it catches a forced add.
11. **What this design does not do:** it does not edit game data, bundle or download Smithbox, use me3, take
    Smithbox's own row names or annotations as facts, or run anything a job names.

---

## 8. What would be reused from LLM Jobrunner, and on what terms

All of it is the owner's own code. The reuse is the owner's to decide; nothing here assumes it.

| From Jobrunner | Reused as | Changed for DataPiler |
|---|---|---|
| `launcher.cpp`, its manifest, resource script, icon slot, `BUILD.md` | copied into `launcher-src/` | PowerShell window, mutex check, 60 s wait, name and version (§3) |
| the page's guard: Host, Origin, the per-start token, the CSP with a nonce, the headers | copied into `datapiler.py` | none |
| the atomic port file and the stale-file rule | copied | none |
| the drop zone, its check on arrival and its cards | copied, re-worded | Reads / Computes / Writes preview, the guard's report |
| the Terminal tab's renderer (levels in colour, filters) | copied | one log source instead of one per server |
| the start log | copied | names the venv's state too |
| the look (colours, cards, pills, "?" tooltips) | the same CSS tokens | none |

**Terms:**
- copied into DataPiler's repository under its MIT licence, with a line in its README naming Jobrunner as the source;
- no shared library, no dependency between the two repositories, and no change to Jobrunner;
- if the owner prefers DataPiler's launcher written afresh, §3 is enough to write it from.

I'd be glad to look over the result. Send the repository's tag, or the files, through the owner.
