# Request 0001: the design of DataPiler, for the PandorumLLM session

From the EldenNet design session, on the owner's behalf (2026-11-08). The owner will pass this to you and bring your
answer back; please answer as one Markdown file (and any mock pages or sketches beside it), and say what you would
reuse from LLM Jobrunner and on what terms.

## What DataPiler is

A small local tool on the owner's gaming PC. It extracts Elden Ring's data from the owner's own install, through the
modding tool Smithbox, for EldenNet's research: EldenNet is an LLM-driven NPC framework for Elden Ring, and it must
match every named character to the game's numbers (character data rows, name numbers, map placements) before its
character profiles can be written. DataPiler's decisions are in [../DECISIONS.md](../DECISIONS.md) (DP1 to DP5).

The owner's request, verbatim:

> can you make this Smithbox plugin to come with established repo, executable to run, http UI, and interactive button
> that run tools. Basically I would like to be able to simply start the tool with executable, then it open on the
> browser as a tab, and it features all the tools, to see smithbox runtime, extract types of data (user can select
> types individually or in bundles to extract), it also has drop in file zone that accepts jobs from you (drop in the
> job file, do the job and write output file that I can share here). Also ship it with powershell terminal window and
> logging system. for the design you could ask PandorumLLM agent (write request).

LLM Jobrunner 1.2, which you built, has the same shape: a small unsigned launcher exe that starts a standard-library
Python app with no console, waits for its port file and opens the page; a page on 127.0.0.1 only, answering its own
origin and a token made at each start, under a strict content-security policy; a drop zone whose files are checked on
arrival and run only on Start; a queue; a Terminal tab with live logs. We would like DataPiler to feel like a sibling
of it.

## What it must do

1. **Start.** Double-click `DataPiler.exe`: a PowerShell window opens showing DataPiler's live log, the app starts,
   and the page opens in the browser as a tab. A second start opens the running page. Quit from the page closes both.
2. **Smithbox status** (read-only): whether Smithbox is installed and where, its build, whether it is running, whether
   its local server is on (the `System_Enable_Soapstone_Server` setting in Smithbox's `Startup.json`, and whether its
   port answers), which project is open, and the checks below (game closed; the project folder neither the game's
   folder nor inside it).
3. **Extract.** A catalogue of data types the owner ticks one by one or by bundle, then Run. Each type says where it
   comes from (the server link, or a guided export the owner clicks in Smithbox, which DataPiler picks up from a
   watched folder), what it gives, and where its output goes. A first catalogue, to refine with us:

   | Type | From | Gives |
   |---|---|---|
   | Character rows | server: NpcParam rows | row id, name number (`nameId`, signed; negative means none) and a few numeric fields per row |
   | Character names | guided text export (Smithbox's Text Editor, containers `item`, `item_dlc01`, `item_dlc02`) | the name behind each name number, **local only** |
   | Dialogue links | server: TalkParam rows | row id and message number (`msgId`, signed) |
   | Map placements | server: map objects, map by map (maps must be loaded in Smithbox) | entity id, character row id, dialogue id and model per placed character, with its map |
   | Places | server: WorldMapPlaceNameParam and BonfireWarpParam; guided text export for place names | place and warp numbers; names local only |

   Bundles: "Roster" (character rows, names, dialogue links), "Placements", "Places", "Everything". Boss health bars
   and quest flags live in the game's event and talk scripts, which Smithbox neither exports readably nor serves;
   EldenNet reads those live in game later, so they are not in the catalogue.
4. **Jobs from the assistant.** A drop zone for job files the assistant writes in the conversation. Each is checked
   when it lands and shown (what it reads, what it computes, what it will write); nothing runs until Start. It runs,
   and writes one output file the owner can share back in the conversation.
5. **Outputs, in two kinds.** A **local workspace** that may hold names and other game text, and never leaves the PC;
   and a **share folder** whose files hold numbers, counts and our own words only, each passed through a guard before
   it is written (below). The page shows both, and a share file's contents before the owner shares it.
6. **Logging.** Log files with rotation in DataPiler's folder, shown live in the PowerShell window and in a Terminal
   tab on the page.
7. **Settings.** The Smithbox and game folders, the project folder, the workspace and share folders, the text language,
   and the server link's switch for this session (off at start).

## Rules it must keep

- **The game's data never leaves the PC.** No game file, no game text (names, dialogue, descriptions), no whole param
  table or column, and no Smithbox file is ever put in a share file, a log the owner might share, or the repository.
  Share files hold ids, numbers, counts, our own labels and a provenance block (the game's version, a hash of its
  `regulation.bin`, whether the expansion is installed, the language, Smithbox's build, DataPiler's version, the date).
- **Nothing about the owner either** (the owner's own emphasis): no paths, user names, machine names, IP addresses or
  account names in a share file or the repository; logs show folders as placeholders (`<GAME>`, `<SMITHBOX>`,
  `<PROJECT>`, `<WORKSPACE>`).
- **The guard.** Before a share file is written: every value must be an integer, an enum, or one of our own labels from
  a fixed list; no string that occurs in the local text database may appear; no path, user name or machine name may
  appear. A file that fails is not written, and the page says which check failed without showing the offending text.
- **The server link.** Read calls only, from a fixed allowlist: `ListParams`, `ListParamRows`, `GetParamRows` (with
  `vanilla = true`), `SearchObjects`, `GetObject`, `BatchGetObjects`, and `OpenResource` only to load a map. Never
  `ExecuteMassEdit`, `SetParamCell`, `ReloadParams` or any call not on the list. Connect only while `eldenring.exe` is
  not running, and stop at once if it starts. The server is Smithbox's, at `127.0.0.1:22720` (gRPC; its definitions are
  SoapstoneLib's, MIT); it has no authentication, so DataPiler suggests switching it off again in `Startup.json` when
  done.
- **Smithbox itself** is never bundled, downloaded or redistributed by DataPiler; the owner installs it. None of its
  me3 features is used. Its own labels (row names and annotations) are never taken as facts: only numbers from the
  owner's data.
- **Jobs are data, never code.** A job names operations from a closed set (fetch these param rows; load these maps and
  read their placements; join rows with names; count; write these numbers to a share file), with a schema version.
  No scripts, no shell commands, no file paths outside DataPiler's folders, no network beyond Smithbox's local server.
- **The page** answers only on 127.0.0.1, its own origin and a token, under a strict content-security policy, with no
  CDN, remote font or script, as Jobrunner's does.
- **Dependencies.** The server link needs `grpcio` (Apache-2.0) and `protobuf` (BSD-3-Clause), beyond the standard
  library; every licence is read and noted before adoption.

## What we ask you to design

1. **The page:** its layout and tabs (Status, Extract, Jobs, Outputs, Terminal, Settings, or better), the look (a
   sibling of Jobrunner and PandorumLLM), and how the catalogue, bundles, progress and results read. Mock pages or
   sketches are welcome.
2. **The launcher and the PowerShell window:** how `DataPiler.exe` starts the PowerShell window with the live log and
   the app, how Quit closes both, and how a second start finds the running page. Would you reuse Jobrunner's launcher
   (and on what terms), and how is the exe built (your `BUILD.md` route, or a GitHub Actions build on Windows)?
3. **Python and its two libraries:** Jobrunner is standard library only. How should DataPiler bring `grpcio` and
   `protobuf`: a local virtual environment made at first start, wheels in the release, or another way? Which Python
   versions?
4. **Logging:** format, levels, rotation, the Terminal tab, and the placeholders for folders.
5. **Jobs:** the drop-zone flow (check on arrival, preview, Start, progress, result), the job file's format (we will
   write the jobs, so a schema we can validate against helps), and the share file's format.
6. **Anything we have missed,** and anything in these rules that makes the tool harder to use than it needs to be.

We would then build DataPiler from your design in its own public repository, MIT, and send you the result to look
over if you wish.
