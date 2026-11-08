# Owner decisions

The project owner's decisions on DataPiler, binding, one entry each, numbered DP1 onwards. A new question takes the
next free id as an entry marked **Open**, with its options and a recommendation; the owner's answer is recorded in the
entry with its date and their words; a later decision amends an earlier one by a dated note, never by rewriting it,
and ids are never renumbered. EldenNet's decisions are cited as "EldenNet O55" and live in EldenNet's
`docs/DECISIONS.md`.

## By date

- **2026-11-08.** DP1 (what DataPiler is), DP2 (its name), DP3 (a public repository of its own), DP4 (the Smithbox
  server link, game closed) and DP5 (the design asked of the PandorumLLM session). DP6 (design 0001 adopted) and DP7
  (Jobrunner's code copied). DP8 (what a share file may hold). DP9 (what a release carries). DP10 (the zip's folder), DP11 (an update
  button) and DP12 (folder detection and a picker), the last two asked of the PandorumLLM session.
- **Open.** None.

## DP1

**What DataPiler is** · *2026-11-08 · The owner's request*

**Question.** None was put: the owner's request of 2026-11-08, after the Smithbox dry run was proposed (EldenNet O56).

**Decision.** A local tool on the owner's PC for extracting the game's data from their own install through Smithbox,
for EldenNet's research (EldenNet O54, O55, O57): started from an executable, it opens in the browser as a tab and
holds all the tools; it shows Smithbox's runtime state; it extracts types of data, chosen one by one or in bundles; it
has a drop zone that takes job files written by the assistant, runs the job and writes an output file the owner can
share back in the conversation; it ships with a PowerShell terminal window and a logging system.

**Owner's words.** "can you make this Smithbox plugin to come with established repo, executable to run, http UI, and
interactive button that run tools. Basically I would like to be able to simply start the tool with executable, then
it open on the browser as a tab, and it features all the tools, to see smithbox runtime, extract types of data (user
can select types individually or in bundles to extract), it also has drop in file zone that accepts jobs from you
(drop in the job file, do the job and write output file that I can share here). Also ship it with powershell terminal
window and logging system. for the design you could ask PandorumLLM agent (write request)."

**Follows from.** EldenNet O54 (research now, no EldenNet build before the blueprint), O55 (Smithbox as the source),
O56 (how far our tools go: this request answers it), O57 (research extraction kept apart from the framework's data and
live tracing).

## DP2

**The name** · *2026-11-08 · Decided by the owner*

**Question.** What is the tool called? Smithbox's name was kept out of it, so that it does not look like an official
Smithbox plugin.

**Decision.** DataPiler, written as the owner named the repository they created for it (`Pt0l3my/DataPiler`, 2026-11-08).

**Owner's words.** "let's call it Datapiler".

## DP3

**A public repository of its own** · *2026-11-08 · Decided by the owner*

**Question.** Should the tool live in a repository of its own, and public or private? Private was put forward only as
a cautious default.

**Decision.** A repository of its own, public, MIT, like EldenNet and GraceUI. It holds only our own code, never game
data, and every push passes the privacy sweep.

**Owner's words.** "these tools are made for AI framwork, so if somebody doesn't like AI they will not bother to use
the AI framework itself to begin with, so that's not a concern. just make extra sure that you use the sweep tool and
never expose any delicate information about my privacy or security."

## DP4

**The Smithbox server link, with the game closed** · *2026-11-08 · Decided by the owner, as recommended*

**Question.** Smithbox cannot be driven by a script or a command line. Should DataPiler's buttons fetch data straight
from a running Smithbox through its built-in local server, or should the owner click Smithbox's exports and DataPiler
process the files? **As put to the owner:** the only danger to the game is one server call that writes into a running
game; with the game closed there is nothing for it to write into. While the server is on it has no password, so
another program on the PC could make Smithbox edit the open project's params, a throwaway folder, never the install.

**Decision.** The server link, with the game closed. DataPiler uses the server's read calls only; it connects only
while the game is not running and stops if the game starts; it refuses a project folder that is the game's folder or
inside it. Guided exports (the owner clicks, DataPiler processes the files as they land) remain for what the server
does not serve, such as the game's text. The cost accepted: two Python libraries beyond the standard library (grpcio
and protobuf, licences to be read before adoption), and map loading that may take an hour or more.

**Owner's words.** "Server link, game closed (Recommended)"; earlier, on the question as first put: "why is a running
game a concern? as far as I know, we only intend to use smithbox for non in-game data extractions."

**Later changes.** 2026-11-08, a fact found in the build, not a new decision: grpcio needs a third library,
typing-extensions (PSF-2.0), which the first start installs with the other two from the same lock; README, NOTICE, the
page and the window's question name all three ([design/settled.md](design/settled.md), S23).

## DP5

**The design asked of the PandorumLLM session** · *2026-11-08 · The owner's request*

**Decision.** The design of DataPiler (its page, its launcher and terminal window, logging, the drop zone and jobs) is
asked of the PandorumLLM session, whose LLM Jobrunner already has the same shape, by a written request the owner
passes on: [requests/0001-design.md](requests/0001-design.md). DataPiler is built from its answer.

**Owner's words.** "for the design you could ask PandorumLLM agent (write request)."

## DP6

**Design 0001 adopted** · *2026-11-08 · The owner's act*

**Decision.** The PandorumLLM session's answer to request 0001, [design/0001-design.md](design/0001-design.md) with
its mock [design/0001-mock.html](design/0001-mock.html), is DataPiler's design, which the owner brought back to be
built from. What the designers settled from its open points is in [design/settled.md](design/settled.md) (S1 onwards).

**Owner's words.** The owner passed on the design and its mock without comment, to be built from (DP5: "for the design
you could ask PandorumLLM agent").

## DP7

**LLM Jobrunner's code copied** · *2026-11-08 · Decided by the owner, as recommended*

**Question.** Design 0001 reuses the owner's LLM Jobrunner: the launcher (its C++ source, manifest, resource script and
`BUILD.md`) and the page's safety parts (the local-only guard, the per-start token, the content-security policy, the
port file, the drop zone and the Terminal tab). May they be copied into this public repository under its MIT licence,
with a README line naming Jobrunner as the source, Jobrunner itself untouched and neither depending on the other? Or
written afresh from the design?

**Decision.** Copied, adapted for DataPiler (a visible PowerShell window, the single-instance check, a 60 s wait, its
name and version), under DataPiler's MIT licence, with the README line.

**Owner's words.** "Copy it (Recommended)".

## DP8

**What a share file may hold** · *2026-11-08 · Decided by the owner, as recommended*

**Question.** The build's review found that a job could put a whole column of the game's character table (every row's
id and name number) into a share file, against the rule that no whole table or column of the game's data leaves the
PC. What may share files hold? **Options:** (a) **only what a feature needs**: ids and numbers only for rows a job has
picked for a purpose (the named characters, matched with their names on the owner's PC, or an explicit list of ids),
never a raw table or column straight from Smithbox, and the guard refuses a table that covers more than half of a game
table's rows; (b) **counts only**: counts and summaries, never ids; (c) **whole columns allowed**, since ids and
numbers are not text.

**Decision.** (a). A share file holds ids and numbers only for rows a job picked for a purpose; a table made straight
from `fetch_rows` or `read_placements`, or by a filter of one, never reaches `write_share` unless it was narrowed by
`join_names` to the named rows or by an explicit list of ids; and the guard gains a sixth check, refusing any table
that covers more than half of a game table's rows. The leads it allows go to a numbers-only research file in EldenNet
(EldenNet O59).

**Owner's words.** "Only what a feature needs (Recommended)".

**Follows from.** Request 0001's rules; CLAUDE.md, Game data; EldenNet ER08 §7 item 3.

## DP9

**What a release carries** · *2026-11-08 · Decided by the owner*

**Question.** DataPiler 0.1.0's draft release carried the zip of the whole app (with the exe and the toolchain's
notices inside), its sha256, and also the exe, the exe's sha256 and the notices on their own. Asked why the exe was
attached separately, the assistant explained it was left over from S4, before the zip (S24), and proposed releases
with only the zip and its sha256; asked what `THIRD-PARTY-NOTICES.txt` is, and whether it could live in the
repository and the README instead, the assistant explained that the MinGW-w64 runtime's licences ask that the notices
go with every copy of the exe, so they must stay in the zip, and recommended the zip only, with a README line.

**Decision.** From the next release on, a release carries the zip (with the exe and the notices inside), the zip's
sha256, and the notices as their own file too; the exe and its sha256 are no longer attached on their own, and the
exe's sha256 is in the release workflow's log, which the release's notes link. The README's Licence section names
the notices. 0.1.0's draft stays as it was built.

**Owner's words.** "alright" (to the exe's explanation), then: "let's do both then (in future releases), as separate
doc in github release and inside zip."

## DP10

**The zip's folder has no version** · *2026-11-08 · Decided by the owner*

**Decision.** From the next release, `DataPiler-<version>.zip` keeps the version in its name, and holds one folder
named `DataPiler`, without the version (0.1.0's zip held `DataPiler-0.1.0/`).

**Owner's words.** "For datapiler releases, can you make it so that the zip carries the version in title but not the
folder inside, so e.g. currently we have DataPiler-0.1.0.zip and DataPiler-0.1.0 inside it. what I would like is
DataPiler-<version>.zip and DataPiler folder inside it."

## DP11

**An update button** · *2026-11-08 · The owner's request; its design asked of the PandorumLLM session*

**Decision.** DataPiler gains an update button: pressed, it opens a pop-up showing the latest release on GitHub and
downloads it. The design is asked of the PandorumLLM session in [requests/0002-update-and-folders.md](requests/0002-update-and-folders.md).
It amends S12 (no network after the first start): the update check and download run only when the owner presses
the button, and only to GitHub.

**Owner's words.** "Can you add update button to the UI, that the user could press, gets a pop up downloader UI that
shows available update (latest) from github repo), ask the PandorumLLM agent about this (a request how exactly this is
done, the layout, etc.)"

## DP12

**Folder detection and a folder picker** · *2026-11-08 · The owner's request; its design asked of the PandorumLLM session*

**Decision.** Settings gains detection of the Smithbox folder, the game folder and the project folder, and a "Set
folder" button beside each that opens a folder picker over the page. The design is asked of the PandorumLLM session in
the same request.

**Owner's words.** "on the settings page, can you add auto detect for Smithbox folder, Game folder, Project folder,
and also set folder button that brings up over top UI index to select folder, again ask the PandorumLLM agent about
this (a request how exactly this is done, the layout, etc.)"
