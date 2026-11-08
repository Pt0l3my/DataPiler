# Owner decisions

The project owner's decisions on DataPiler, binding, one entry each, numbered DP1 onwards. A new question takes the
next free id as an entry marked **Open**, with its options and a recommendation; the owner's answer is recorded in the
entry with its date and their words; a later decision amends an earlier one by a dated note, never by rewriting it,
and ids are never renumbered. EldenNet's decisions are cited as "EldenNet O55" and live in EldenNet's
`docs/DECISIONS.md`.

## By date

- **2026-11-08.** DP1 (what DataPiler is), DP2 (its name), DP3 (a public repository of its own), DP4 (the Smithbox
  server link, game closed) and DP5 (the design asked of the PandorumLLM session). DP6 (design 0001 adopted) and DP7
  (Jobrunner's code copied). DP8 (what a share file may hold).
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
