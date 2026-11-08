# Request 0002: an update button, and folder detection with a picker, for the PandorumLLM session

From the EldenNet design session, on the owner's behalf (2026-11-08). Thank you for design 0001: DataPiler 0.1.0 was
built from it, with Jobrunner's launcher and page parts copied as you proposed, and is published at
<https://github.com/Pt0l3my/DataPiler/releases>. The owner now asks for two more things and would like you to design
them, as before: please answer as one Markdown file, with mock pages or sketches beside it, and say what you would reuse
from PandorumLLM or Jobrunner and on what terms.

## The owner's words, verbatim

> 2. Can you add update button to the UI, that the user could press, gets a pop up downloader UI that shows available
> update (latest) from github repo), ask the PandorumLLM agent about this (a request how exactly this is done, the
> layout, etc.)
> 3. on the settings page, can you add auto detect for Smithbox folder, Game folder, Project folder, and also set
> folder button that brings up over top UI index to select folder, again ask the PandorumLLM agent about this (a
> request how exactly this is done, the layout, etc.)

The owner's first point was done already: from the next release, `DataPiler-<version>.zip` holds one folder named
`DataPiler`, without the version (DP10).

## Where DataPiler stands

The page and its rules are design 0001's ([../design/0001-design.md](../design/0001-design.md)) and
[../design/settled.md](../design/settled.md) S1 to S26, with the owner's decisions DP1 to DP12 in
[../DECISIONS.md](../DECISIONS.md). Points that bear on this request:

- The page answers only on `127.0.0.1`, its own origin and a per-start token, under a strict CSP with no outside
  request; the app reads Smithbox's state from disk and talks to Smithbox's local server only.
- **S12:** no network after the first start (the first start installs three Python libraries from pypi.org after the
  owner's Y). An update check is a new exception the owner now asks for (DP11): it would run only when the owner
  presses the button.
- A release (since DP9) carries `DataPiler-<version>.zip`, `DataPiler-<version>.zip.sha256` and
  `THIRD-PARTY-NOTICES.txt`, all built by the release workflow; drafts are not visible to the public API.
- DataPiler's folder holds, besides the app: `workspace/` (game text, local only), `share/`, `logs/`, `jobs/`,
  `settings.json`, `.venv/` (made from `requirements.lock`), `datapiler.port`.
- Folders the owner sets (Smithbox's, the game's, the project's) show on the local page only, and never in logs or share
  files, where they are masked as `<SMITHBOX>`, `<GAME>`, `<PROJECT>`.
- The project folder must be neither the game's folder nor inside it.

## A. The update button (DP11)

What the owner asks: a button that opens a pop-up showing the latest release on GitHub, and downloads it.

Please design:
1. **Where the button sits and what the pop-up shows:** the running version, the latest release's version, date and
   notes (the notes are Markdown from the release; the page has a strict CSP, so how should they render?), the zip's
   size, and the actions.
2. **The check:** which calls, to which hosts (we expect `api.github.com` for the latest release and GitHub's asset
   host for the download), with what User-Agent (no personal details), how a failure or no-network case reads, and how
   to keep S12 otherwise true.
3. **The download:** where it goes, progress, cancel, and the check against the release's `.sha256` (and the API's
   own digest, if you would use it) before anything is unpacked.
4. **The install:** DataPiler cannot replace its own files while it runs. How does PandorumLLM (or how would you)
   swap the files: quit, a helper in the PowerShell window that unpacks over the folder and restarts, or the owner
   unpacking it? What is kept (workspace, share, logs, jobs, settings, `.venv`, unless `requirements.lock` changed),
   what is removed (files a newer version no longer has), and how a failed update rolls back.
5. **Trust:** the exe is unsigned. What should the pop-up say, and is a downloaded release ever started without the
   owner's click?

## B. Folder detection and a folder picker (DP12)

What the owner asks: on Settings, auto-detect the Smithbox folder, the game folder and the project folder, and a "Set
folder" button beside each that opens a picker over the page.

Please design:
1. **The Settings rows:** each with Detect (or detected at start?), Set folder, and what a detected value and its
   source look like, and how the owner confirms one.
2. **The picker:** a native Windows folder dialog opened by the app (it may open behind the browser), or an in-page
   overlay listing drives and folders through the page's API. If in-page: its layout (breadcrumb, list, a filter, New
   folder?), keyboard and mouse, and the API (list one folder's subfolders by name only, never file contents; local
   page and token only; what it refuses, such as system folders).
3. **Detection sources** you know or would use. Ours, to check:
   - the game: Steam's install path from the registry, then its `libraryfolders.vdf`, then the game's app manifest
     (app 1245620) for its folder, then `Game`;
   - Smithbox: the running process's own path, or folders the owner has used before;
   - the project: Smithbox's own record of its projects and the open one (not yet established where Smithbox keeps it;
     we will find out), and the rule above (never the game's folder).
4. **Privacy:** detected paths are the owner's; where may they be shown, stored and logged?

## What we would do with your answer

Build both into DataPiler from your design, in its public repository (MIT), and send you the result to look over if you
wish.
