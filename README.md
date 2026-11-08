# DataPiler

A local companion for [Smithbox](https://github.com/vawser/Smithbox) on your own PC. It extracts Elden Ring's data
from **your own install**, for the research behind [EldenNet](https://github.com/Pt0l3my/EldenNet), an LLM-driven
NPC framework for Elden Ring. You start it from `DataPiler.exe`; a PowerShell window shows its live log, and its page
opens as a tab in your browser with all its tools: Smithbox's status, data extraction by type or by bundle, a drop
zone for jobs, the outputs, and the log.

**Status: 0.1.0.** The first version, built from [design 0001](docs/design/0001-design.md). The owner's decisions are
in [docs/DECISIONS.md](docs/DECISIONS.md), what the build settled in [docs/design/settled.md](docs/design/settled.md),
and what changed in [CHANGELOG.md](CHANGELOG.md).

## What you need

- Windows 10 or 11, with Windows PowerShell 5.1 (part of Windows) or PowerShell 7.
- Python 3.10 or newer from [python.org](https://www.python.org/), found as `py -3` or `python`.
- Smithbox and Elden Ring, both installed by you. DataPiler bundles neither.

## Start and stop

- **Get it:** each release has one zip of the whole app, `DataPiler-<version>.zip` (the source at that version with
  `DataPiler.exe` built into it), and its sha256 beside it. Download the zip, check it against its sha256, and unpack
  it anywhere you like.
  - **Making a release:** on GitHub, open Actions › release › **Run workflow**, choose the branch, and run it. A few
    minutes later a draft release `v<version>` holds the zip; publish it, or download it from the draft. Pushing a
    `v<version>` tag does the same.
- **Start:** double-click `DataPiler.exe` in the unpacked folder.
  - It opens a PowerShell window titled DataPiler, which checks Python and runs the app; the window shows the log.
  - Once the page is up, the exe opens it in your browser: `http://127.0.0.1:<port>/`.
  - Starting it again while DataPiler runs, or while its window is still starting, just opens the running page once
    it is up; no second window opens.
- **Stop:** press **Quit** on the page. Closing the window, or Ctrl+C in it, stops DataPiler the same way. After a
  normal stop the window closes by itself; after a crash it stays open with the exit code, and
  `datapiler-start.log` beside the exe says why when the page never came up.
- **Windows' warning:** the exe is unsigned, so SmartScreen may warn on its first start: choose More info, then Run
  anyway. Its source is in `launcher-src/`, [BUILD.md](BUILD.md) says how to build it yourself, and each release's
  exe is built by a GitHub workflow from that source, with its sha256 beside it.
- **Without the exe:** in DataPiler's folder, run
  `powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\DataPiler.ps1` (the policy applies to that one
  process and changes nothing on your PC). DataPiler then opens the page itself.

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
  and wait until you have given it.
- The names' text ids (which part of Smithbox's text exports holds the character and place names) come from
  EldenNet's research and are checked against your own data each time a job joins names: if fewer than half of the
  names it looks up are found there, the job stops and says so.
- Its page answers only on `127.0.0.1`, to itself, with a token made at each start, and loads nothing from
  elsewhere. Its logs show your folders as placeholders (`<GAME>`, `<SMITHBOX>`, `<PROJECT>`, `<WORKSPACE>`).
- Jobs are data, never code: a closed set of operations, checked when they are dropped, run only on Start.
- It writes only inside its own folder, and into the workspace and share folders if you move them in Settings.
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
  `logs/`, `jobs/`), a game file, a share file, an IP address, a user's folder or an e-mail address in the tree, and
  CI runs it on every push.

## Licence

[MIT](LICENSE). ELDEN RING is a trademark of FromSoftware and Bandai Namco.
