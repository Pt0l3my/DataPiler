# DataPiler

A local companion for [Smithbox](https://github.com/vawser/Smithbox) on your own PC. It extracts Elden Ring's data
from **your own install**, for the research behind [EldenNet](https://github.com/Pt0l3my/EldenNet), an LLM-driven
NPC framework for Elden Ring. You start it from `DataPiler.exe`; a PowerShell window shows its live log, and its page
opens as a tab in your browser with all its tools: Smithbox's status, data extraction by type or by bundle, a drop
zone for jobs, the outputs, and the log.

**Status: 0.2.0.** Built from [design 0001](docs/design/0001-design.md) and, for the Update… button and the folder
detection, [design 0002](docs/design/0002-design.md). The owner's decisions are in
[docs/DECISIONS.md](docs/DECISIONS.md), what the builds settled in [docs/design/settled.md](docs/design/settled.md),
and what changed in [CHANGELOG.md](CHANGELOG.md).

## What you need

- Windows 10 or 11, with Windows PowerShell 5.1 (part of Windows) or PowerShell 7.
- Python 3.10 or newer from [python.org](https://www.python.org/), found as `py -3` or `python`.
- Smithbox and Elden Ring, both installed by you. DataPiler bundles neither.

## Start and stop

- **Get it:** each release has one zip of the whole app, `DataPiler-<version>.zip` (the source at that version with
  `DataPiler.exe` built into it), and its sha256 beside it. Download the zip, check it against its sha256, and unpack
  it anywhere you like: it holds one folder, `DataPiler`, without the version in its name, so the folder keeps its name
  from one release to the next.
  - **Making a release:** on GitHub, open Actions › release › **Run workflow**, choose the branch, and run it. A few
    minutes later a draft release `v<version>` holds the zip; publish it, or download it from the draft. Pushing a
    `v<version>` tag does the same.
- **Start:** double-click `DataPiler.exe` in the unpacked folder.
  - It opens a PowerShell window titled DataPiler, which checks Python and runs the app; the window shows the log.
  - Once the page is up, the exe opens it in your browser: `http://127.0.0.1:<port>/`.
  - Starting it again while DataPiler runs, or while its window is still starting, just opens the running page once
    it is up; no second window opens.
- **Stop:** press **Quit** on the page. Closing the window, or Ctrl+C in it, stops DataPiler the same way. After a
  normal stop the window closes at once, and the page closes its tab where the browser allows it (it does for the tab
  the exe opened); after a crash the window stays open with the exit code, and `datapiler-start.log` beside the exe
  says why when the page never came up.
- **Windows' warning:** the exe is unsigned, so SmartScreen may warn on its first start: choose More info, then Run
  anyway. Its source is in `launcher-src/`, [BUILD.md](BUILD.md) says how to build it yourself, and each release's
  exe is built by a GitHub workflow from that source, with its sha256 beside it.
- **Without the exe:** in DataPiler's folder, run
  `powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\DataPiler.ps1` (the policy applies to that one
  process and changes nothing on your PC). DataPiler then opens the page itself.

## Updating

- **The first update is by hand, once.** 0.1.0 cannot hand over to the updater, so reaching 0.2.0 is an unpack by
  hand: quit DataPiler, download `DataPiler-0.2.0.zip`, check it against its sha256, and copy what its `DataPiler`
  folder holds over your DataPiler folder, replacing the files there. Your `settings.json`, workspace, share folder,
  logs, jobs and `.venv` are not in the zip, so they stay. From 0.2.0 on, the button does it.
- **Update…** in the top bar asks GitHub for the latest release, only when you press it: nothing checks on its own,
  and there is no setting that would. The pop-up shows the release's version, date and notes (as text: its links show
  their address and do not open from there), and **Open the release page ↗** opens the release in a new tab.
- **Download** fetches the zip into DataPiler's own `update\` folder, then checks it before anything is unpacked: its
  size; the release's own `.sha256`; GitHub's own digest of the file (both must agree, and without a digest the
  pop-up says it relies on the `.sha256` alone); the zip's shape (one `DataPiler` folder, nothing outside it, no
  links); and every file in it against the release's manifest, `manifest.sha256`, with the version inside. Closing the
  pop-up stops a download. A download not installed is removed at the next start.
- **Install and restart** stops DataPiler. Its window then backs up every file it will replace or remove into
  `update\backup-<version>\`, writes the new files, checks each where it landed, and starts the new version. It never
  touches your workspace, share, logs, jobs, `settings.json` or `.venv`, nor a file you added yourself. A file the new
  version drops goes into the backup, not the bin. Any failure puts every file back and starts the old version again.
  Ctrl+C does not stop the swap part way; if it is cut off all the same (the window closed, the power cut), the
  window puts the old files back from the backup, at once or at the next start. Install waits while a job or an
  Extract run is going.
- **If the new version does not start** (its page never comes up, or its window script stops first), the window says
  so and offers **R** to go back to the version you had, with its Python environment. It never goes back by itself.
- **If the Python libraries changed**, the window asks Y again after the restart, as at the first start; the new
  `.venv` is built beside the old one, which stays until the new version's page is up.
- **At each start** DataPiler checks its own files against the release's manifest and says in the log which differ.
  It repairs nothing. A copy from the repository has no manifest: it can check for a release, but installs one only by
  hand.
- **Where it connects:** `api.github.com`, `github.com` and GitHub's two file hosts, over https only, every redirect
  checked again, and only from those three presses. Each call is a log line, by host and path. After an update whose
  Python libraries changed, and your Y, pip fetches them from `pypi.org` and `files.pythonhosted.org`, as at the first
  start.
- **SmartScreen:** a zip you download by hand carries Windows' download mark, so the unsigned exe may warn on its
  first start (More info, then Run anyway). The files the button writes carry no such mark; they are proved by their
  checksums instead.
- **For the release account:** the checks prove the files are the ones the release published, not that the release
  itself is good, which rests on the GitHub account. Keep two-factor authentication on it, and let only the release
  workflow put files on a release, never a hand upload.

## The first start's question

The server link, which reads data from Smithbox, needs three libraries beyond Python's own: `grpcio` (Apache-2.0) and
`protobuf` (BSD-3-Clause), and `typing-extensions` (PSF-2.0), which grpcio needs. They are not in the download. At
the first start the window names them with their versions and licences, says about how many MB they are and that they
come from pypi.org over https, and asks:

- **Y:** it makes a `.venv` folder inside DataPiler's folder and has pip install them there, each file checked
  against its sha256 in `requirements.lock`; pip refuses anything else. No later start touches the network.
- **N:** DataPiler starts without the server link. The guided exports and Outputs still work, and a job you drop is
  checked at once, but no job runs without the link, as every job reads from Smithbox first; Extract's server rows
  wait for it too. It asks again at the next start.

The Pythons the server link supports are the ones `requirements.lock` names. With another Python, DataPiler says so
and starts without the link.

## Smithbox's server

The link talks to the local server Smithbox runs at `127.0.0.1:22720`, with read calls only, and only while the game
is closed: it is off at every start, you switch it on for the session on the page, and it stops as soon as the game
starts. Smithbox runs that server while `System_Enable_Soapstone_Server` is `true` in
`%LOCALAPPDATA%\Smithbox\Configuration\Startup.json` (its default). The server has no password, so any program on the
PC can call it while it runs: when you are done, set the switch to `false` in that file and restart Smithbox.
DataPiler reads the file and never writes it.

**Map jobs** need Smithbox's Visual Map Editor enabled in the project (Projects tab › Available Editors, then Update
Project and a restart of Smithbox). While a job loads maps, keep Smithbox's window up, not minimised, with its Map
Editor tab in front: Smithbox takes its load commands only then. The job card shows the maps loaded so far and a guess
of the time left.

**Faster map loading.** Smithbox loads one map at a time, and by its code (2.2.6) most of that time goes into what its
3D view needs: each map's models and textures (on the Vulkan build, while viewport rendering is on) and its Havok
collision (unless its setting to skip Havok loading is on). DataPiler reads only the placed characters, so for map
jobs turn viewport rendering off and skip Havok loading in Smithbox's settings, or start `Smithbox.OpenGL.exe`, which
by the same code never loads map models or textures.

A map that has not loaded after 10 seconds is skipped for now and asked for again at the end of the run; the log names
it. DataPiler cannot see why Smithbox did not load it, as Smithbox keeps its log in its own windows: look in its
**Warning Log** (in its top bar). Before a map job DataPiler reads two of Smithbox's saved preferences, Enable Model
Rendering and the skipping of Havok loading, and nothing else of that file; Smithbox saves them when it closes, so a
change you just made may not show yet.

A map job keeps each map's characters as soon as it has read them, so if Smithbox, the graphics driver or DataPiler
stops partway, **Start again** goes on where it stopped. A job pauses once Smithbox holds 300 maps, because
Smithbox's Vulkan build keeps graphics memory for every map it has loaded and has brought a graphics driver down with
about 700: close Smithbox, start it again, and press **Start again**.

A map that loads with nothing in it, as some tiles of the open world do, counts as loaded. For long map jobs, turn
Smithbox's auto-save off first: every five minutes it saves each loaded map into your Smithbox project folder (your
game folder is never touched), and with hundreds of maps loaded that adds up. Restart Smithbox after a big map job to
free what the loaded maps hold.

## What it will and won't do

- It reads data from your own game through Smithbox. It never bundles, downloads or redistributes Smithbox or any
  game file, and uses none of Smithbox's me3 features.
- The game's text and data stay on your PC, in the **workspace** folder, which Settings refuses to put on a network
  share or a mapped network drive. What DataPiler writes for sharing, in the **share** folder, holds numbers, counts
  and its own labels only, and ids only for rows a job picked for a purpose: the named characters, matched with their
  names on your PC, or an explicit list of ids. A job is refused when you drop it if it would share a table straight
  from Smithbox, a filter or distinct of one, or a count of one by a column of ids (a row id, a name number, a message
  id, a placement's character, dialogue or model id); a count by other columns is a summary. The guard, which checks
  every share file before it is written, then refuses a file whose tables from one game table cover, together, more
  than half of that table's rows (DP8). Extract's own share files hold counts only.
- **Settings asks you one thing about your game:** whether its expansion is installed. Share files record your answer,
  and wait until you have given it. Detect reads Steam's app manifest and shows the DLC app ids it lists; as a DLC app
  may be an artbook or a soundtrack, it offers Yes and No and you choose. It is saved only when you press Use.
- **Finding your folders:** each folder on Settings has **Detect** and **Set folder…**, with a check line under it.
  Detect reads only what this PC already records: Smithbox's folder from the running Smithbox (DataPiler sees it start
  and stop, whichever of its exes you run), your project and the game's folder from Smithbox's own record of its
  projects (read as Smithbox's source describes it, not yet checked against a real install), and Steam's install path, its library list, the game's app manifest and Windows' uninstall entry, with the
  running game, for the game's folder and as a cross-check. Each find is listed with where it came from; nothing is
  saved until you press **Use**. Finds are kept in memory for the session only and never logged. **Set folder…** opens
  a folder picker in the page: it lists folder names only, never a file, and does not browse network shares or
  Windows' own folder. The project folder must be outside the game's folder, must not hold it, and must be outside
  DataPiler's own folder.
- **Mask paths on this page** (Settings, off by default) shows your folders on the page as the placeholders the logs
  use, for screenshots, the folder names the picker lists included.
- The names' text ids (which part of Smithbox's text exports holds the character and place names) come from
  EldenNet's research and are checked against your own data each time a job joins names: if fewer than half of the
  names it looks up are found there, the job stops and says so.
- Its page answers only on `127.0.0.1`, to itself, with a token made at each start, and loads nothing from
  elsewhere. Its logs show your folders as placeholders (`<GAME>`, `<SMITHBOX>`, `<PROJECT>`, `<WORKSPACE>`).
- Jobs are data, never code: a closed set of operations, checked when they are dropped, run only on Start.
- It writes only inside its own folder, and into the workspace and share folders if you move them in Settings. Its
  one use of the internet after the first start is the Update… button, when you press it, and pip after your Y when
  an update changes the Python libraries.
- It is not a Smithbox plugin and is not affiliated with Smithbox, FromSoftware or Bandai Namco.

## Where its code comes from

- The launcher (`launcher-src/`, `BUILD.md`) and the page's safety parts (the local-only guard, the per-start token,
  the content-security policy, the port file, the drop zone and the Terminal tab) are copied and adapted from the
  owner's **LLM Jobrunner 1.2**, under DataPiler's licence (DP7).
- `soapstone/` is generated from SoapstoneLib's message definitions (MIT), as Smithbox's repository carries them;
  [soapstone/SOURCE.md](soapstone/SOURCE.md) names the commit.
- [NOTICE](NOTICE) lists everything taken from others and its terms.

## For developers

- Tests: `python3 -I -m unittest discover -s tests` from the repository's root, standard library only; the link tests
  skip without grpcio.
- The repository's own check: `python3 -I tools/repocheck.py`. It fails a run-time file (`workspace/`, `share/`,
  `logs/`, `jobs/`, `update/`, a release's `manifest.sha256`), a game file, a share file, an IP address, a user's
  folder or an e-mail address in the tree, and CI runs it on every push.
- A release's manifest: `python3 tools/manifest.py <folder>` writes `<folder>/manifest.sha256`, and
  `python3 update-helper.py --check-zip <zip> --version <X.Y.Z>` makes the button's checks of a release zip, read only.
  The release workflow runs both.

## Licence

[MIT](LICENSE). The exe is linked with parts of the MinGW-w64 runtime, whose licences ask that their notices go with
it: they are in `THIRD-PARTY-NOTICES.txt`, inside each release's zip and attached to the release beside it
([NOTICE](NOTICE), section 4). ELDEN RING is a trademark of FromSoftware and Bandai Namco.
