# DataPiler: an update button, and folder detection with a picker, in answer to request 0002

*As received from the PandorumLLM session on 2026-11-08, by way of the owner; committed unchanged except that the
example folders were replaced with invented ones and four references to the owner made gender-neutral. Its mock is
[0002-mock.html](0002-mock.html); the owner's answers to its open points are DP13 and DP14 in
[../DECISIONS.md](../DECISIONS.md), and Smithbox is detected from its running process only (DP13).*

From the PandorumLLM session, for the EldenNet design session, by way of the owner (2026-11-08). It comes with
`DataPiler-mock-0002.html`, a static mock that opens in a browser and makes no network calls. Its strip of chips shows
each state:
- the Settings rows;
- the update pop-up from "checking" to "updated", and its failures;
- the picker for the game folder and the project folder;
- the PowerShell window during an update.

Design 0001, `settled.md` S1 to S26 and DP1 to DP12 stand as written. Where this design adds a rule or suggests changing
one, it says so; those points are collected in §4.

---

## 1. In one paragraph

**Update.** An **Update…** button in the top bar is the only thing that ever reaches the internet after the first
start (DP11). It asks GitHub's API for the latest release only when pressed, and shows what it found. It downloads only
on a second press, into DataPiler's own `update\` folder. It proves the zip against the release's `.sha256` and
GitHub's own digest before anything is opened. It installs only on a third press: the app stops, and its own
PowerShell window swaps the files. The window runs a helper taken from the verified download, backs up every file it
will touch, and puts them all back if any step fails. It then starts the new version.

**Folders.** On Settings, each folder row gets **Detect** and **Set folder…**:
- Detect reads only what Steam, Windows and Smithbox already record on this PC.
- Set folder… opens a picker drawn in the page. It lists folder names through the page's own token-guarded API: never
  a file, never a file's contents.
- Nothing detected is saved until the owner presses **Use**.

---

## 2. A. The update button (DP11)

### 2.1 Where it sits, and what the pop-up shows

**The button** sits in the top bar, left of **Quit**: `Update…`. There is no badge and no "new version" dot, because
nothing checks on its own (§2.3). The running version stays where design 0001 put it, beside the name.

**The pop-up** is drawn in the page, over it, like the picker; it is not a browser window. Esc or × closes it. Its
states, all in the mock:

| State | Shows | Actions |
|---|---|---|
| checking | "Asking GitHub for the latest release (api.github.com)…" | Cancel |
| up to date | This version, the latest release and its date, ✓ "You have the latest release" | Open the release page ↗, Close |
| a newer release | This version; the latest release's version and date (`published_at`); the zip's name and size, in MiB with its decimal MB beside it (Hugging Face and GitHub show decimal); "Checksum: published beside it, and GitHub's own digest agrees"; whether the Python libraries change (§2.5); the release notes | Open the release page ↗, Close, **Download 1.9 MiB** |
| downloading | a bar, "1.2 of 1.9 MiB · 640 KiB/s" | Cancel (removes the part file) |
| verified - ready | each check as a ✓ line (§2.4); what Install does, in plain numbers ("replaces 41 files, adds 6, removes 2 (kept in the backup)"); what is kept; the unsigned-exe note (§2.6) | Discard the download, Later, **Install and restart** |
| restarting | ✓ DataPiler stopped; the window is replacing files; waiting for the new version on this address | none - the page reloads itself |
| updated | ✓ "Updated to 0.3.0 - 41 written, 6 added, 2 removed. All 61 files match the release." The backup's folder and `logs\update.log` named | Close |
| failed | what failed, in one line, and that nothing changed or that everything was put back; the stage it stopped at | Close, Check again or Try again |

Other cases:
- **The latest release is older than this one** (a build from the repository): "This build (0.3.0-dev) is newer than
  the latest release (0.2.0)". Nothing to download.
- **A release that cannot be installed from here** - no zip, or no `.sha256` beside it: "0.3.0 does not carry a
  checksum file, so DataPiler will not install it - the release page has it". Nothing to download.
- **No release published yet:** said so.

**The release notes under the strict CSP.** The notes are Markdown, and are never put into the page as HTML. The app
turns them into a small tree of blocks: headings, paragraphs, lists, code, and inline bold, italic and code. The page
builds that tree with `createElement` and `textContent`. Rules:
- No `innerHTML`, no inline style, no image (an image shows as `[image: <alt text>]`).
- A link shows its text and then its address in grey. It does not open from the pop-up.
- **Open the release page ↗** is the one way out. It is `html_url` from the API, checked to start with
  `https://github.com/Pt0l3my/DataPiler/releases/`, as a plain link with `rel="noopener noreferrer"` that the browser
  opens in a new tab.
- The notes are cut at 20,000 characters, with "… the rest is on the release page".

This needs no change to the CSP: nothing is inline, and nothing is fetched by the page.

### 2.2 How it is reached

- **Up to date and newer:** one press of **Update…**, which runs the check.
- **Download:** a second press.
- **Install and restart:** a third press.

Nothing runs without the press before it, and closing the pop-up at any point leaves things as they were.

### 2.3 The check

**The calls:**
- **The check:** one GET to `https://api.github.com/repos/Pt0l3my/DataPiler/releases/latest`, made by the app (the
  page never talks to GitHub), with:
  - `User-Agent: DataPiler/<version> (+https://github.com/Pt0l3my/DataPiler)`;
  - `Accept: application/vnd.github+json`;
  - `X-GitHub-Api-Version: 2022-11-28`.

  No token, no cookie, no Referer, nothing about the PC or the owner. `releases/latest` never returns a draft or a
  pre-release, so neither can be offered.
- **The checksum file:** one GET of the `.sha256` asset's `browser_download_url`.
- **The download:** one GET of the zip's `browser_download_url` (§2.4).

**Hosts.**
- **Allowed:** `api.github.com` and `github.com`, and GitHub's asset hosts the download is redirected to:
  `objects.githubusercontent.com` (older) and `release-assets.githubusercontent.com` (current). PandorumLLM's list,
  for the same calls, is these four.
- **Redirects:** each one is checked against the list again, and must stay on https. Anything else stops the call
  with "GitHub sent the download to `<host>`, which DataPiler does not fetch from".
- **Proxy:** Python's own proxy settings (the environment's `HTTPS_PROXY`) are honoured.
- **TLS:** Python's default context, which reads Windows' certificate store.

**Failures, in the owner's words.** Each says that nothing was downloaded or changed.

| Case | Says |
|---|---|
| no connection, DNS fails, or a timeout of 15 s | "GitHub could not be reached - no internet, a firewall, or a proxy that refused it." |
| 403 or 429 with `x-ratelimit-remaining: 0` | "GitHub's limit for checks from this address is reached (60 an hour without an account). It resets at 18:40." - the time read from `x-ratelimit-reset`. |
| 404 | "No release is published yet." |
| any other status | "GitHub answered <code>." |

**Cache.** An answer is kept for ten minutes, so closing and reopening the pop-up asks once. **Check again** asks
anew. A failure is never cached - PandorumLLM's lesson: a cached failure blocked retries for hours.

**Keeping S12 true otherwise.** This becomes the one exception, written into `settled.md` as S12a (§4):
- **One module, `datapiler/update.py`, is the only code that opens a connection to anywhere but `127.0.0.1`.** Smithbox's
  link stays in `link.py`, on `127.0.0.1:22720`. A test fails the build if `urllib.request`, `http.client`,
  `socket.create_connection` or `ssl` appear in any other module of the app.
- **Its three functions are reached only from `POST /api/update`,** with the per-start token and an `action` of `check`,
  `download`, `install` or `cancel`. No timer, start step, job or Settings value calls them. A test asserts that the
  only references are that handler's.
- **There is no "check automatically" setting.** DP11 says on the press, and a setting is the first step away from
  that.
- **Every outbound call is a log line:** `INFO update GET api.github.com/repos/Pt0l3my/DataPiler/releases/latest - 200,
  0.4 s`. The URL is public and carries nothing of the owner's.

### 2.4 The download

- **Where:** `DataPiler\update\<version>\DataPiler-<version>.zip`. The file is written as `.part`, streamed in 64 KiB
  chunks and hashed as it arrives, and renamed only once proved. `update\` is DataPiler's own folder, in the
  `.gitignore` with the other state folders, and never written outside of.
- **Progress:** the app keeps bytes, total and rate. The pop-up reads `GET /api/update` every half second while it is
  open, as the Terminal tab reads the log.
- **Cancel:** stops between chunks and removes the `.part`.
- **The size:** the asset's `size` from the API is the most it reads. A server that sends more is cut off, and the
  download refused.
- **Before anything is unpacked, in this order** - each a ✓ line on the pop-up, any ✗ discarding the download:
  1. **The size** equals the asset's `size`.
  2. **The sha256 equals the published `.sha256`.** That file's first token must be 64 hex characters. If a file name
     follows it (`sha256sum` writes `<hex>  DataPiler-0.3.0.zip`), it must be the zip's own name.
  3. **The sha256 equals GitHub's digest** for the asset. The API gives `"digest": "sha256:<hex>"` for release assets,
     and PandorumLLM checks llama.cpp's builds the same way. Two sources must agree:
     - the file the workflow wrote, and the hash GitHub computed when it stored the upload;
     - when the API carries no digest (an older release), the `.sha256` alone, and the line says so;
     - with no `.sha256`, the release cannot be installed from the button.
  4. **The archive's shape**, read from the zip's directory before any member is extracted:
     - every name is under one top folder, `DataPiler/` (DP10);
     - no absolute path, no `..` segment, no drive letter, no backslash in a name, no symlink (a member whose external
       attributes mark a link);
     - at most 2,000 members, and at most 256 MiB unpacked in all;
     - the unpacked sizes are checked while reading, not trusted from the directory.
  5. **Its manifest:**
     - `DataPiler/manifest.sha256` must be present, and every member except the manifest itself must be listed in it,
       with a matching sha256;
     - `DataPiler/datapiler/version.py` (or the file DataPiler keeps its version in) must name the tag's version;
     - `update-helper.py` must be in the manifest (§2.5).

A download that is never installed is removed at the next start: the pop-up's ready state says "a download not
installed is removed when DataPiler next starts". **Discard the download** removes it at once.

### 2.5 The install

#### Why the window does it

DataPiler cannot replace its files while its Python runs them, and design 0001 already gives it a window that outlives
the app: `DataPiler.ps1`. PowerShell reads a whole script before running it, so the script that is running can be
replaced on disk without effect on it. The swap therefore happens in that window, between the old app's exit and the
new app's start:
- one window throughout;
- the owner sees each step;
- no hidden process, and no second helper exe.

#### The handshake

1. **Install and restart** (the third press) → `POST /api/update {action: "install"}`. The app:
   1. hashes the staged zip again - a different step at a different moment proves for itself;
   2. extracts `update-helper.py` from it into `update\<version>\`, and checks it against the zip's manifest;
   3. writes `update\pending.json`, holding:
      - the zip's path and sha256;
      - the version from and the version to;
      - the page's current port;
      - a random nonce;
      - the time;
   4. answers the page, stops as Quit does (design 0001 §3), and exits with code **75** ("update requested") instead of
      0.
2. **`DataPiler.ps1` (the running, old one)** sees 75 and runs the helper with the Python it already found:
   `& $py "update\<version>\update-helper.py" --pending "update\pending.json"`.
3. **The helper**, standard library only (its rules are below), ends with an exit code:

   | Code | Means | The old script then |
   |---|---|---|
   | 0 | swapped | starts the **new** `DataPiler.ps1` in the same window: `& "$PSScriptRoot\DataPiler.ps1" -AfterUpdate`, then `exit $LASTEXITCODE` |
   | 1 | failed and restored | prints the reason and starts itself again (the old version) |
   | 2 | refused before touching anything | the same as 1 |
4. **The new script** starts as at any start:
   - it checks the venv against the lock, and asks **Y** if `requirements.lock` changed;
   - it builds a changed venv as `.venv.new` and swaps it in only when pip succeeds, keeping the old one until then;
   - with **N**, or if pip fails, the app starts without the server link, as design 0001's N path does.

   The app then reads `pending.json`'s port and binds it first, so the page that asked can find it again. It runs the
   install check (below) and removes `pending.json`.

**The first update.** The 0.1.x script has no exit-75 branch. The button arrives in a release, and updates **from**
that release onward go through it. Reaching that first release is the owner's unpack by hand, once. The README says so.

#### What is kept, and what is removed

The helper works from two manifests: the installed one (`DataPiler\manifest.sha256`, shipped in each release from now
on) and the new one.
- **Written:** every file the new manifest lists, unless it is already that exact file (by hash). Each is written as
  `<file>.dpnew`, hashed, then put in place with `os.replace`, and hashed again where it landed.
- **Removed:** every file the **old** manifest lists that the new one does not. It is moved into the backup, never
  deleted, so a rollback brings it back. PandorumLLM's updater does not do this - it only writes - and DataPiler
  should, as the request asks.
- **Never touched**, whatever a manifest says - a fixed list in the helper, as defence in depth:
  - `workspace\`, `share\`, `logs\`, `jobs\`, `update\`, `.venv\` (and `.venv.new`);
  - `settings.json`, `datapiler.port`, `datapiler-start.log`;
  - any file in neither manifest (the owner's own additions).
- **A shipped file the owner edited** (its hash is not the old manifest's) is replaced like any other. The edited copy
  is in the backup, and the helper's log names it.
- **A file that refuses to be written because something holds it:** it is renamed aside to `.old` and the new one
  written beside it, as PandorumLLM does. The next start removes the `.old` files.
- **`DataPiler.exe`** exits once it has opened the browser, so nothing holds it during an update; if something does,
  the `.old` rule applies.

#### The helper's rules

The helper is PandorumLLM's design, in the helper's own words:
- **It acts only for a live request:**
  - `pending.json` must exist, be less than ten minutes old, and name this folder;
  - the mutex `Local\DataPiler` must be free - the app has gone;
  - the helper then takes the mutex itself for the swap, so a `DataPiler.exe` started meanwhile says "DataPiler is
    updating - see its window" and opens nothing.

  It is not a general file replacer left in the folder.
- **It proves the zip a third time,** from its own side.
- **Every target is resolved and checked to land inside DataPiler's folder** - `realpath`, so a link cannot point out
  of it. The check is made when backing up, and again at the moment of writing.
- **It backs up first,** into `update\backup-<old version>\`, before writing anything:
  - every file it will overwrite or remove;
  - the old manifest.

  Only the latest backup is kept; an older one goes once a new update succeeds.
- **It writes, then checks what landed** - the hash on disk, not the bytes sent.
- **Any failure puts everything back:**
  - every backed-up file is restored;
  - every file the update added is removed;
  - then exit 1, and the old script starts the old version.
- **It narrates:**
  - each step to the window and to `logs\update.log`, masked like every log line;
  - the result to `update\result.json`, holding: state, the stage it stopped at, the reason, counts and the backup's
    folder.

  The returning app serves `result.json` to the page.

#### When the new version does not start

The new script notes the time it began. If the app exits non-zero before writing `datapiler.port`, within 90 s of an
update, the window says:

```
DataPiler 0.3.0 stopped before its page came up (exit code 1) - datapiler-start.log has why.
Press R to go back to 0.2.0, or Enter to close this window.
```

**R** runs the helper's restore from `update\backup-0.2.0\` and starts 0.2.0. The rollback is the owner's key, never
automatic, because a start can fail for reasons the old version shares (a missing Python, a port in use).

#### The install check

At each start the app hashes its files against `manifest.sha256` and logs "install check: all 61 files match the
release", or names the files that differ. It is a statement, not a repair: an owner who edited a file is told, not
overruled. PandorumLLM's rule.

#### The page's side

After **Install and restart** the pop-up shows the restarting state. It polls `GET /` on its own origin every 2 s; the
new app answers there with the new page and a new token. The page then reloads and reads `GET /api/update-result`, which
shows "updated" or "failed - put back".
- **The port.** If the new app could not get the old port, it opens a new tab itself, as the exe does. After 90 s the
  old page says "DataPiler did not come back on this address - it may have opened a new tab, or its window says why".
- **The token.** The new app's per-start token comes with its new page. The old page's token is dead with the old app.

#### What the release must carry (workflow changes)

The release workflow writes, inside the zip:
- `DataPiler/manifest.sha256`: every file's sha256 and its path relative to `DataPiler/`, one per line, the manifest
  itself left out;
- `DataPiler/update-helper.py`;
- the version file the app reads.

Beside the zip, `DataPiler-<version>.zip.sha256` as now (DP9). Nothing else changes for the owner when publishing.

### 2.6 Trust

- **Nothing downloaded is ever started without the owner's press.** Check, Download and Install are three presses, and
  only Install runs anything new: the helper from the verified zip, then the new version. There is no background
  download, no "install on next start", and no update without the pop-up open.
- **What the pop-up says,** in the ready state, amber: "DataPiler.exe is not code-signed. This one was built by the
  release workflow from the repository's source, and its checksum is the release's. Nothing downloaded starts until
  you press Install and restart."
- **SmartScreen.** Files DataPiler writes itself carry no download mark (the Mark of the Web is added by browsers and
  some unzip tools). So Windows normally shows no SmartScreen prompt for the updated exe, as it does for a zip
  downloaded by hand. The README should say both: the hand-download prompt (More info → Run anyway), and that the
  button's update is verified by checksum instead.
- **The release itself.** The checks prove the bytes are the ones the release published. They cannot prove the
  release is good, which rests on the owner's GitHub account, as for anyone using the release page.
  Recommended: two-factor authentication on the account, and the workflow as the only way assets reach a release - no
  hand uploads.

---

## 3. B. Folder detection and a folder picker (DP12)

### 3.1 The Settings rows

The mock's Settings tab shows the three rows. Each row has:
- **A title with a "?":** what the folder is, and where Detect looks.
- **The path field**, editable and pasteable, as now.
- **Detect** and **Set folder…** beside it.
- **The check line** under it, live, run by the app on the path in the field:

| Folder | ✓ when | ✗ / ! when |
|---|---|---|
| Smithbox | `Smithbox.exe` is in the folder; its build is read from the exe's version resource | "no Smithbox.exe here" |
| Game | `eldenring.exe` is in the folder; its version is shown | "no eldenring.exe here - the game's folder is the `Game` folder inside ELDEN RING" |
| Project | outside the game's folder, and outside DataPiler's own folder (§4, suggested); "a Smithbox project file is here" when one is | ✗ "inside the game's folder - choose a folder outside it", and nothing is saved while it shows |

- **What Detect found:** a small list under the row. Each place has its path, a tag naming its source ("Steam's library
  list", "the running Smithbox", "a program Windows recorded", "Smithbox's recent projects"), and a **Use** button. A
  place that is already the field's value shows "in use". More than one place is normal for Smithbox (an old copy left
  behind), and the list never chooses for the owner.
- **Confirming:**
  - **Use**, and **Choose this folder** in the picker, are the owner's confirmation: each fills the field and saves
    that one setting at once, and the check line answers.
  - A path typed or pasted by hand waits for **Save**, as now, and its check line shows before Save.
  - A ✗ check refuses the save with the same words. The project rule is design 0001's, and it is enforced by the app,
    not only by the page.
- **Detection at start.** Each start runs Detect for a folder whose setting is **blank**, or set to a folder that no
  longer exists. It is local and takes well under a second. Nothing is saved: the row and the Status card show "Found 1
  place - confirm it in Settings". A folder already set and present is never second-guessed.
- **Recent:** the last five values each folder had, kept in `settings.json`, shown under the row with **Use**, with a
  "forget recent folders" link.
- **Expansion installed** (the owner's setting) gets the same treatment: a detected value with its source and **Use**.
  It is never set by itself.

### 3.2 The picker: drawn in the page, recommended

A native Windows dialog has these problems:
- **It can open behind the browser.** It belongs to the app's process, not the browser, so it often opens behind the
  browser, and the owner sees nothing happen.
- **Opening it costs code or a process.** Either COM through ctypes (`IFileOpenDialog` with `FOS_PICKFOLDERS`, a few
  hundred lines of vtable code), or a PowerShell `FolderBrowserDialog` process for each pick.
- **It holds a request open** until it closes.

PandorumLLM chose a picker drawn in the page for these reasons, and it has served well. **Recommended: the same.**

**Layout** (the mock's "Picker" chips):
- **The title** names the folder being set: "Set the game folder".
- **A breadcrumb:** `This PC › C: › Games › SteamLibrary › steamapps › common › ELDEN RING`, each part clickable.
- **Places,** as chips:
  - **This PC** (drives);
  - **Detected (n)** - Detect's places for this folder, opened first when there are any;
  - **Recent (n)**.
- **A filter box:** type to filter this folder's list as you type. Nothing is searched beyond the folder shown.
- **The list:** folder names only, with a folder icon, sorted case-insensitively.
  - A folder that holds what this row looks for carries a lime tag: `eldenring.exe` for the game, `Smithbox.exe` for
    Smithbox, the project file for the project. The tag is the page's own word, from a yes/no the API gives (§3.3).
  - The list holds at most 2,000 folders, then "and 312 more - type to filter".
- **Under the list:** the folder that would be chosen, with the row's check line for it ("✓ eldenring.exe is here").
- **Buttons:** **↑ Up**, **Cancel**, and **Choose this folder** - greyed while the check is a ✗.
- **New folder…** appears in the project picker only, since a new project folder is the one thing worth making from
  here. It takes a name, refuses the characters Windows refuses (and the reserved names `CON`, `NUL`, `COM1` and so on),
  and refuses inside the game's folder or DataPiler's.

**Keyboard and mouse:**
- **Keyboard:**
  - ↑ ↓ move; Home and End jump to the ends of the list;
  - Enter opens a folder; Backspace or Alt+↑ goes up;
  - typing goes to the filter;
  - Ctrl+Enter chooses the folder shown; Esc closes.
- **Mouse:** click selects, double-click opens, and a breadcrumb part opens that level.
- **Focus** stays in the picker while it is open, and returns to the row's Set folder… button when it closes.

### 3.3 The picker's API

`POST /api/dirs`, on the local page only: Host and Origin checked, with the per-start token, as every write.

**Asked:**
```
{"path": "C:\\Games\\SteamLibrary\\steamapps\\common", "want": "game"}
```
`want` is `smithbox`, `game` or `project`. A blank `path` returns the drives.

**Answered:**
```json
{"path": "C:\\Games\\SteamLibrary\\steamapps\\common",
 "crumbs": [{"name": "C:", "path": "C:\\"}, {"name": "Games", "path": "C:\\Games"}, ...],
 "dirs": [{"name": "ELDEN RING", "mark": false}, {"name": "Sekiro", "mark": false}],
 "more": 0}
```
- **Folder names only.** No file is listed, ever, and no file is opened.
- **`mark`** is one existence check of the one file `want` looks for, inside each listed folder, made by the app. It
  goes as a yes/no, never as a name.
- **Drives** come with their letter and type (local, removable, network) only. A drive's volume label is left out:
  it can be personal, and the letter is enough.

**Refused, with its reason** - the picker shows it in place of the list:

| Asked | Refused with |
|---|---|
| no token, a foreign Host or Origin | 403 - and nothing listed |
| a relative path; a path with `..` after resolving; a device path (`\\.\`, `\\?\`) | "not a folder path" |
| a UNC path (`\\server\share`) | "network paths can be typed in the field, not browsed" - browsing a share would be network traffic the owner did not ask for; a path the owner types is the owner's choice |
| `%WINDIR%` and anything inside it | "Windows' own folder" - nothing DataPiler needs is there |

**Left out of the list without a word:**
- **hidden or system folders** (their attributes): `$Recycle.Bin`, `System Volume Information`, and the old junctions
  such as `Documents and Settings`;
- **a folder that cannot be read:** the list says "(no access)".

**Links:** a junction or symlink the owner made is listed under its name, and when chosen is saved as the folder it
resolves to.

**Slow drives.** Each listing runs with a 3 s limit, so a sleeping network drive cannot hold the page: "this drive did
not answer in 3 s". PandorumLLM learned this one: asking every drive letter on every click held the picker. Only the
drives view asks Windows about drives.

**Not logged:** what the picker listed. At DEBUG, only "picker: 1 folder listed, 37 entries".

**New folder:** `POST /api/dirs/new {"parent": ..., "name": ...}`, with the rules above. It answers with the new
folder's path, and the picker opens it.

### 3.4 Where Detect looks

All local and read-only: the registry, a few files, the process list. Nothing is searched by walking drives - that is
slow, and reads far more than it needs to.

**The game.** Each source gives candidates; a candidate counts only if `eldenring.exe` is in it.
1. **Steam's install path:**
   - `HKCU\Software\Valve\Steam`, value `SteamPath` (forward slashes, lower-case);
   - else `HKLM\SOFTWARE\WOW6432Node\Valve\Steam`, value `InstallPath`.
2. **Its library list:** `<Steam>\steamapps\libraryfolders.vdf` (newer clients also keep `<Steam>\config\libraryfolders.vdf`;
   read both). It is Valve's KeyValues text: a small, strict parser of quoted strings and braces, and no `eval`.
   - Each library has a `path` and an `apps` block of app ids.
   - **The library whose `apps` holds `1245620`** is the one to read. In an older file without `apps`, every library is
     tried.
3. **The app manifest:** `<library>\steamapps\appmanifest_1245620.acf`. Its `installdir` (normally `ELDEN RING`) gives
   `<library>\steamapps\common\<installdir>\Game`.
4. **Windows' uninstall entry:**
   - `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 1245620`, value `InstallLocation`;
   - and the same key under `WOW6432Node`;
   - then `\Game` added.

   It is a second source if the library list cannot be read.
5. **The running game:** while `eldenring.exe` runs, its own path, read with
   `QueryFullProcessImageNameW` (`PROCESS_QUERY_LIMITED_INFORMATION`). Design 0001's game check already walks the process
   list.

**The expansion:**
- **From Steam:** the same app manifest's `InstalledDepots`, where a DLC depot carries a `dlcappid`. The expansion's
  app id is **2778580** (Shadow of the Erdtree) - to confirm against a real manifest on the owner's PC.
- **From the game's folder:** the expansion's own files, by the names your Status card already checks.
- Detect shows what each source says. It sets nothing.

**Smithbox.** Smithbox is a portable folder, with no installer and no registry entry of its own. A candidate counts
only if `Smithbox.exe` is in it.
1. **The running Smithbox:** its path, read with `QueryFullProcessImageNameW`, as for the game.
2. **Programs Windows recorded:** Windows keeps the path of programs started from Explorer in
   `HKCU\Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache`, as value names ending
   `.FriendlyAppName`.
   - Detect reads **only** the names that end in `\Smithbox.exe.FriendlyAppName`, and nothing else from that key.
   - This is the source most likely to find an old copy as well as the current one, which is why Detect lists places
     and lets the owner choose.
   - It reads the owner's own record of programs the owner ran, so it is named in the row's "?". It can be switched off in
     Settings (§4).
3. **The folders used here before** (Recent).

**The project.**
1. **Smithbox's own record of its projects, and the one open.** Where Smithbox 2.x keeps it is not yet established, as
   the request says.
   - DSMapStudio, which Smithbox grew from, wrote a `project.json` into each project folder naming its `GameRoot`.
   - If Smithbox still does, a candidate can also be confirmed by its project file naming the same game folder as
     DataPiler's: the check line says "a Smithbox project for this game".
   - Your session will find where the list of recent projects lives. Detect reads it the same way: candidates, with
     their source tag.
2. **Recent.**
3. **The rule:**
   - neither the game's folder nor inside it - design 0001's rule, enforced on save;
   - and, suggested (§4), not a folder that holds the game's folder (a project at `C:\Games\SteamLibrary` would put the game
     inside the project);
   - not DataPiler's own folder.

### 3.5 Privacy

| What | Where it may be |
|---|---|
| A detected or chosen path | **Shown** on the local page only: `127.0.0.1`, with the token. DataPiler has no remote view. **Stored** in `settings.json` only, once the owner presses Use, Choose or Save; with the five recent values. **Never** in a share file (the guard's check 4 already refuses any path), a job file, `result.json`, or a log line. |
| A candidate not yet confirmed | **In memory only,** for the session; never written anywhere. |
| Log lines about detection | Name the source and the count, never the path: "game folder: 1 place from Steam's library list". The masking filter also learns each candidate as `<FOUND>` for the session. A path that is not yet a known folder would otherwise pass it: masking only knows the folders it has been told about, and a candidate is not one yet. |
| The registry and MuiCache reads | Only the values named in §3.4. Nothing else read is kept. |
| The picker's listings | Not logged; not kept. |
| Drive labels | Not read. |

**One suggestion: a "mask paths on this page" switch** on Settings, off by default. The owner shares screenshots of the
page with other sessions. With it on, the page draws `<SMITHBOX>`, `<GAME>`, `<PROJECT>`, `<WORKSPACE>` in place of
the paths, as the logs do - including in the picker's breadcrumb and Detect's list. PandorumLLM does this for its
Remote Access viewers.

---

## 4. What this adds to the settled rules, and suggestions

1. **S12a, new (DP11):** "DataPiler reaches the internet after the first start only when the owner presses Update…:
   `api.github.com`, `github.com` and GitHub's two asset hosts, each call logged; one module may open such a
   connection; nothing checks on its own." S12 then reads "no network after the first start, except S12a".
2. **The release carries a manifest and the helper** (§2.5's workflow changes), from the first release that has the
   button.
3. **The project folder:** besides "not the game's folder, nor inside it", suggested:
   - not a folder that **holds** the game's folder;
   - not DataPiler's own folder, or inside it.
4. **MuiCache as a Smithbox source:** on by default, with a Settings switch "Detect may read Windows' list of programs
   started" - it is the owner's call; the source is the best one for a portable app.
5. **"Mask paths on this page"** (§3.5): suggested, off by default.
6. **Rollback after a failed start is the owner's R** (§2.5, "When the new version does not start"), not automatic.
7. **A test list for the repository:**
   - S12a's module rule;
   - the archive checks against crafted zips: `..`, an absolute path, a symlink, two top folders, a manifest mismatch,
     an oversize member;
   - the helper's restore after a failure planted at each stage;
   - the picker API's refusals;
   - `libraryfolders.vdf` in both formats;
   - a detection log line holding no path.

---

## 5. What would be reused, and on what terms

**From PandorumLLM: the method, not the code.** PandorumLLM is under its own licence: source-visible, personal use, no
redistribution, no derivative or competing works. Its code therefore cannot go into DataPiler's public MIT repository
unless the owner, as its author, chooses to release those parts under MIT. Nothing here assumes the owner will, and the
owner's standing view is that the owner's work is not to be copied. **Recommended: DataPiler writes these parts afresh from this
design.** They are small:
- the update module, about 300 lines;
- the helper, about 200;
- the picker, about 150 lines of page code and 100 of Python.

What carries over from PandorumLLM is what this document already says in its own words, taken from PandorumLLM's
updater and picker:
- each step proves what it is about to use;
- the helper comes from the verified archive;
- a backup before any write, and a restore on any failure;
- each file checked after it lands;
- the result narrated to a file the returning app serves;
- the four GitHub hosts, with redirects checked;
- a failure never cached;
- folder names only, with a drives view, and a slow drive kept from holding the picker.

**From LLM Jobrunner** - the owner's, on design 0001's terms (copied, with a README line, if the owner agrees):
- the modal's look and its focus handling;
- the page's guard, for the new endpoints.

I'd be glad to look over the result, as before. Send the tag or the files through the owner.
