# Changelog

All notable changes to DataPiler. Versions follow `VERSION` in `datapiler/__init__.py`; a release is tagged
`v<version>`.











## 0.2.39 - 2026-11-15

- New: an **About** block at the top of every checked job's card, before a run, while it runs and after (DP34, S95).
  It holds the job's own description, when its file has one; a line DataPiler counts from the job's steps, such as
  "Reads 40 game files: m12_07_00_00 (31 models and its placement file), m12_04_00_00 (7 and its placement file).
  Computes nothing. Writes 40 local folders, none shared."; and the codes its title and description cite (such as
  WHY§93, DP28, S81, G27, O48, ER05§8 or en-0036), as small chips of plain text.
- Changed: a card's Reads / Computes / Writes columns are under **Details (N steps)**, folded at first (S95). Unfolded,
  steps whose sentences differ only by the name they quote are one item, with the count and the names in a list that
  wraps ("40 game files … that Smithbox unpacked, …"), and steps whose sentences are the same word for word are one
  item ("2 steps: …"). Each card's Details stays open or closed while the page is open; folding the card, **Fold all**
  and **Unfold all** leave it as it was.
- New: a job file may have an `about`: plain text of 1 to 600 characters, where a newline starts a new line and no
  other control character is taken; anything else is refused, naming the rule. A job that has one says
  `"needs": "0.2.39"`, as older versions refuse the key. The schema has it.

## 0.2.38 - 2026-11-15

- Changed: the top bar's server link chip says whether the link is established, not only whether it is on (DP33,
  S94). With the link on it reads **Server link connected** (green) once Smithbox's server answers, **Server link on:
  waiting for Smithbox** (amber) while Smithbox is not running, and **Server link on: no answer** (red) while Smithbox
  runs but its server does not answer, or did not answer the last call; the chip's tooltip says when the server last
  answered, or why not. While the game runs it reads **Server link on: not used while the game runs** and claims no
  connection. The Server link card on Status has the same line under its state. The answer comes from the check
  Status already makes every few seconds (a connection to the server's port, closed at once, never while the game
  runs) and from the link's own calls: nothing new is sent to Smithbox.

## 0.2.37 - 2026-11-15

- Changed: the Update pop-up's drop zone is a box titled **Drop a DataPiler update here** with an **Add file** button,
  shown in every state from the moment the pop-up opens (S93). A file dropped anywhere on the pop-up counts, and it
  stops a check or a download that is under way.
- Changed: jobs that finished since DataPiler started stay unfolded, their results in view (S92); jobs finished before
  still start folded, and your own fold or unfold of a card still wins.

## 0.2.36 - 2026-11-15

- New: install from a file (DP32, S91). The Update pop-up has a zone to drop a DataPiler release zip on, and
  **Choose file…**. DataPiler checks the zip as it checks a download (its shape, every file against the zip's own
  manifest, the version inside, never an older one), shows its sha256 in full to compare with the one given with the
  file, and **Install and restart** installs it as it installs a download.
- New: **Link to Smithbox's server by itself** in Settings (DP31, S90), off at first. With it on, DataPiler switches the
  server link on once Smithbox's server answers, the game is closed and the project folder passes its check, and again
  if the link closed, unless you switched the link off yourself in that session. It stands for the question whether
  Smithbox has your project open.
- New: jobs can read the map-information images' other two colour keys, weather and mimicry, with the expansion's, and
  share their rows for research under DP21's label (S89).

## 0.2.35 - 2026-11-15

- New: **Pack 7z** on a finished job's title row (DP30, S87). It packs the job's share file (only while it passes all
  six checks now) and every file in the job's workspace folder into a 7z archive in the workspace's `packed` folder,
  ready to upload: `<job id>.7z`, or parts `<job id>.7z.001`, `.002` and on when the archive is larger than 29.9 MB,
  which 7-Zip opens from the first. The files go in under the job's id, with no times and nothing about the PC; each
  archive is read back whole before it is offered, and packing a job again replaces its earlier archive. **Open packed
  folder** opens the folder (Windows).
- Changed: finished jobs start folded to their title row (DP30, S86). Folding or unfolding a card yourself is remembered
  in the browser and wins.
- Fixed: an unpack step counts the files it writes, so en-0032's steps read "2 of 2 files" (S88); the binder it opened
  was counted as a third.

## 0.2.34 - 2026-11-15

- Changed: the levels' sizes, measured on the game's own overviews (en-0029, S85): level 1 is 0.74857 of level 0 and
  level 2 0.19875, on every sheet, both from the top left (they were taken as 3/4 and 2,089 / 10,496). Checks of level
  0 against level 1 no longer drift towards the right and the bottom. Overviews were never affected: each level is drawn
  on its own grid.
- Fixed: Stop during a tile check or an overview now waits for the worker processes' running chunks (a few seconds)
  instead of leaving them reading files in the background.

## 0.2.33 - 2026-11-15

- New: the image steps (tile checks and overviews) use the PC (DP29 (b), S83): worker processes on its cores (every
  core but one by default), Windows' own PNG decoder (used only after it decodes test images exactly as DataPiler's own
  does), and decoded tiles kept in memory. Settings has **Cores for image steps** and **Memory for image steps**; the
  Status page has a **This PC** card with the processor, the memory, the graphics card (shown, never used) and what the
  image steps use. Results are the same as before, only faster.
- Changed: `moved` is measured only at levels 0 and 1, where the older layout's shift is a whole number of tiles.
- Fixed: with the game's masks, each level is measured against its nearest level the game draws (level 0 against
  1, levels 1 and 2 against each other). en-0029 measured level 2 against the older layout's level 3, so none of it
  passed on the base map and the underground.
- New: **Pause** on a running job (S84): the step running finishes (a map step stops at its next map, its maps kept),
  the job's finished steps are saved in the workspace, and **Resume job** goes on from the next step, also after
  DataPiler is closed. Start again and Remove send a pause point to the Deleted bin, which can restore it.
- New: **Stop** (was Cancel) asks before it cuts a running job short, and Extract's Cancel asks too.

## 0.2.32 - 2026-11-15

- New: overviews draw each level as the game does (S82). The game's own mask files, which an `unpack_game_file` job
  of `71_maptile.mtmskbnd.dcx` writes to the workspace, say for every tile which map pieces touch it; with every piece
  revealed, the game draws the variant whose code is that mask. DataPiler finds them in its folder and draws each
  level's frame from them; every other code is another layout's and is left out. `"masks": false` turns this off.
- New: `check_map_tiles` adds `in_mask`: whether each variant is one the game draws (1), another layout's (0), or
  not known (-1).
- Changed: one geometry for every sheet, measured from the masks (S82): level 1 three quarters of level 0 and level
  2 2,089 / 10,496 of it, both at the top left of their frame (31 and 9 tiles a side). Levels 3 and 4 are an older
  layout the game no longer draws; they are no longer the reference level.
- Withdrawn: 0.2.31's moving of the "old tile set" in overviews. The masks show those tiles are today's, and the
  reference level 3 the older layout's; `moved` now measures a tile 1,024 map units to the left, where the ground of
  a tile of the older layout lies today.

## 0.2.31 - 2026-11-15

- New: `unpack_game_file` opens a game file that Smithbox unpacked into DataPiler's folder (DP28, S81): DCX files are
  decompressed (KRAK with the game's own Oodle library, loaded from the game folder and never copied) and BND4 binders
  split, binders inside them too. The inner files go to the job's workspace folder on the PC, never shared; its table
  is numbers only. A job may not name a key or the regulation, and DataPiler never decrypts an archive.
- New: the expansion's map has its own geometry (S81): level 2 is level 0 at 2,089 / 10,496, and levels 1 and 2 sit
  at the top left of their grids.
- New: overviews of levels 0 and 1 move the old tile set's variants to where they match (S81), so pieces whose
  variant today's set lacks or gets wrong are drawn there; labels mark them with a plus.

## 0.2.30 - 2026-11-15

- Fixed: level 1 was measured from the bottom of its grid, but its map sits at the top (S80), so almost none of its
  tiles passed. Levels now carry where their map sits; level 1 is lifted by the gap its grid leaves.
- New: `check_map_tiles` gives each variant a `moved` score as well: how well it matches 1,024 map units (four
  level-0 columns) to the right, where the game's old tile set belongs. Levels 0 and 1 hold such a set beside today's.

## 0.2.29 - 2026-11-15

- Every level of every sheet is checked now, not only levels 2 to 4 (S79): each sheet has a reference level (the
  coarsest with six tiles a side or more), and every other level is measured against it at its own scale (levels 0
  and 1 too, at an eighth and a sixth of level 3), the reference against its nearest level. The expansion's map gets
  the same check.
- New: `"shrink"` (2, 4 or 8) makes an overview's tiles smaller, so that levels 0 and 1 fit; labels shrink with them.

## 0.2.28 - 2026-11-15

- Fixed: level 2 overviews mixed two images (S78). Besides the variants that are the base with pieces drawn in, the
  export holds variants carrying another drawing of the whole map at three quarters of the scale, and the file names
  do not tell them apart. `make_map_overview` now checks each variant against the next zoom level (levels 2, 3 and 4
  nest by two) and leaves out one that does not match (`"check": false` turns this off, `"min_match"` sets the bar,
  700 per mille by default); the widest variants inside it are tried instead.
- New: `"labels": true` draws each tile's border, its column and row, and the codes laid (with their scores) or left
  out (with a minus), so every tile in an overview can be traced to its files.
- New: `"variant": "code"` with `"code"` shows one code's files where they were exported, and the base elsewhere.
- New operation `check_map_tiles`: one row per exported tile of a sheet's level, with the number of the folder it was
  found in, its copies, how much of it differs from its base, and how well it matches the next level. Numbers only; it
  may go to a share file.

## 0.2.27 - 2026-11-15

- Fixed: overview tiles showed only some of their pieces revealed, so blocks of the map looked unexplored beside
  explored ones (S77). Where a tile holds pieces that never meet, the game keeps one variant per piece and lays them
  together; 0.2.26 used only one of them. `make_map_overview` now lays every widest revealed variant over the base,
  where it differs from the base, so every piece shows. The log says how many tiles were joined this way.

## 0.2.26 - 2026-11-15

- Fixed: the overview images were split up and showed their joins (S76). A tile's revealed variants are mostly
  transparent: the game draws them over the tile's base variant (code 0). `make_map_overview` now does the same: it
  lays the most revealed variant over the base, by its alpha. `"variant": "base"` gives the base alone.
- A job card that wrote workspace files or images has an **Open folder** button: it opens that job's folder in the
  workspace (Windows).

## 0.2.25 - 2026-11-15

- A new job operation, `make_map_overview` (DP27, S75): it lays the map tiles you exported from Smithbox out on their
  grid, each tile in its most revealed variant, and writes one PNG of a sheet's level to the workspace
  (`local/<job>/<name>.png`), on your PC only: it never goes into a share file. Up to 4,096 pixels a side (level 2 of
  the base map at most). DataPiler reads the PNG tiles with its own code and needs no new library. Outputs lists the
  image with the workspace files.

## 0.2.24 - 2026-11-15

- Job cards can be put in your own order (DP26, S74): drag a card by its grip (⠿) above, below or between the others;
  a line shows where it will land. Or focus the grip and press the up or down arrow. The order is kept in
  `jobs/order.json` and survives a restart; a job added later shows on top, newest first, until you move it.

## 0.2.23 - 2026-11-15

- A new job operation, `read_map_tiles` (DP25, S73): it finds the map tiles you exported from Smithbox's Texture
  Viewer anywhere inside DataPiler's folder, in any subfolder, and gives one row per tile: the sheet, level, column,
  row and eight-digit code from the file's name, the width and height from the file's header, and how many copies were
  found. It never opens an image beyond its size, and no path reaches a table or the log. DataPiler's environment,
  logs, update downloads and Deleted bin are left out. The table may go into a share file.
- The inbox no longer lists exported images as refused files: it leaves them to `read_map_tiles`.

## 0.2.22 - 2026-11-15

- A job may read a field DataPiler does not list yet, when an earlier `check_fields` in the same job names it for the
  same table (DP24, S72). The field is read only if that check found it, with the type the server named (whole
  numbers, numbers or flags; never text); a missing field stops the job before anything is read. A field read this way
  counts as one that may hold ids, so a count by it never reaches a share file.
- Five more of the game's map tables can be read and shared under `map_coords` (DP21): the two colour keys of the
  areas and of the save names, each with the expansion's twin (`MapNameTexParam`, `MapPieceTexParam` and their
  `_m61`), and `MapGridCreateHeightLimitInfo`.

## 0.2.21 - 2026-11-14

- Nothing collected is lost (DP22, S70). A new **Deleted** tab is the bin, `workspace/bin/`: removing a job, a share
  file, a workspace file, an import of the text database or a map job's saved progress moves it there, never erasing
  it. **Restore** puts an item back exactly (a job with its state, a share file with its row counts, an import with its
  rows, sha256 and time) and refuses, saying what is in the way, rather than overwrite. **Erase…** and **Empty bin…**
  erase for good.
- Removing a job asks first in a pop-up; removing collected data (a share file, a workspace file, an import, a job that
  holds saved map progress) asks for `DELETE` typed in, and the button waits for it. The API refuses each removal
  without its confirmation.
- Outputs has **Delete…** for share files and for the workspace files under `local` and `imported`. Start again moves
  the saved progress to the bin, and so does a run that finds progress saved on another game version.
- New endpoints: `GET /api/bin`, `POST /api/bin/restore`, `/api/bin/erase`, `/api/bin/empty` and
  `/api/outputs/remove`; `/api/jobs/act` (remove) and `/api/imported/remove` take `confirm`.
- Game updates (DP23, S71). Every job run that completes keeps what it read (each `fetch_rows` and `read_placements`
  table, numbers only, with the provenance) for its game version, in the workspace's new `versions` folder, one folder
  per version (game version, regulation hash, Smithbox build), never removed. A job whose last run was on another
  version says so on its card ("Game updated since this ran: v1.16.0.0 (ab12cd34) → ...") and offers **Update data**:
  it reads again (maps resumable as before), compares with the last version's read by row id for params and map by map
  for placements, rebuilds the outputs from the new reads, and shows a line per table on the card ("422 → 425 rows: 3
  added, 2 changed, 0 removed, ..."), with a change report of the ids in the workspace. When only the game's exe
  changed (the same regulation and Smithbox build), the param's kept rows are used and not read again.
- Before a run on a new version writes anything, the job's outputs of the last version (its workspace files and its
  share file) move into that version's folder, so every version's outputs stay. Nothing of the reads or the reports
  reaches a share file.
- **Compare versions…** on a job card compares any two versions it kept, by `GET /api/versions` and
  `GET /api/versions/compare`; `/api/jobs/act` takes `update`.
- By the owner's rule, **Start again** on a job holding saved map progress now asks for `DELETE` typed in, as the
  progress moves to the Deleted bin; so do Resume job and Update data when the saved progress is of another game
  version. The API refuses those runs without it. Start again without saved progress keeps its plain question.
- A map job started while the provenance is incomplete no longer stops with an internal error: it keeps no map
  progress and leaves the saved progress where it is.

## 0.2.20 - 2026-11-14

- The game's five map tables can be read in full (S69): `fetch_rows` reads the 91 fields of `BonfireWarpParam`,
  `WorldMapPointParam`, `WorldMapPlaceNameParam`, `WorldMapPieceParam` and `WorldMapLegacyConvParam` that en-0015
  verified on the owner's PC: areas, grid cells and positions, the pieces' rectangles and scales, the conversion's
  source and destination, and their flags, icons and text ids.
- By the owner's decision DP21, a job may share these tables' rows whole when its `write_share` carries the new label
  `map_coords`: for research only, never committed. Every other table keeps DP8's rule, and the label lets nothing
  else through.

## 0.2.19 - 2026-11-14

- Fixed: a share file with a `check_fields` table was refused by the guard's check 3 when the game's text in the
  workspace holds a word with `field` in it, as the owner's does (S68). `field`, `present` and `type`, the columns
  `check_fields` makes, are now among DataPiler's fixed words, as `count` is.

## 0.2.18 - 2026-11-14

- A new job operation, `check_fields` (S67): whether a param's rows have the fields a job names, and their types, as
  Smithbox's server answers for the param's first row. It reads no value and keeps no name: its table holds each
  field's place in the job's list, whether it is there, and its type as a number, so it may go into a share file. It is
  how a field is verified before `fetch_rows` may read it (build plan §10, P4).
- `fetch_rows` and `check_fields` may name three more of the game's map tables, `WorldMapPointParam`,
  `WorldMapPieceParam` and `WorldMapLegacyConvParam`, by row id only until their fields are verified, as
  `WorldMapPlaceNameParam` and `BonfireWarpParam` already were.
- Placements' positions cannot be read through Smithbox's server (S67): it sends single numbers and text only, and a
  position is a vector it leaves out. No position column is added.

## 0.2.17 - 2026-11-14

- The icon redrawn once more, at the owner's choice (S65): a crimson katana on a plain curve, wrapped and trailed by
  blood-red flame whose tongues break up into a spray of blood towards their ends; a handle in black cord over crimson
  diamonds, with a round guard and fittings of dark iron edged in gold. No separate drops. Still our own drawing,
  readable from 16 to 256 px.

## 0.2.16 - 2026-11-14

- The icon redrawn to a katana's proportions (S65): a slender, evenly curved crimson blade about three times the
  handle, with its point (kissaki), temper line and the line across the point; a gold collar, a round guard, and a
  handle in dark cord over light diamonds. The trail streams off the whole blade in tapered strands, lighter than
  before, and the drops sit in the open corner. Still our own drawing, readable from 16 to 256 px.

## 0.2.15 - 2026-11-14

- The icon redrawn at the owner's request (S65): the slash is now a trail streaming off the whole blade, in tapered
  strands that fade where the swing began, with the blade's edge leading and blood drops flung from the tip's path.
  Still our own drawing, readable from 16 to 256 px.

## 0.2.14 - 2026-11-14

- No more pause at 300 maps (S65): a map job runs in one go. It still keeps each map as soon as it is read, so a
  crash costs only the map in hand, and **Resume job** goes on from there.
- DataPiler.exe has an icon (S65): our own blood-red katana in a rising slash, with blood drops, readable from 16 to
  256 px. It comes with the exe, which a new release (or the patch's own build) carries.
- **Resume job** (S66): a job that failed, was cancelled or stopped with maps kept shows how much is kept and where it
  picks up ("Saved progress: 300 of 829 maps read and kept ... Resume job picks up at map 301 of 829 (m60_...)"), and
  a **Resume job** button that goes on from there. **Start again** now asks first, and starts from the beginning,
  dropping what was kept.

## 0.2.13 - 2026-11-14

- A setting, on by default: **Map jobs on Smithbox's OpenGL build only** (DP20, S64). Smithbox's Vulkan build prepares
  graphics data for every map it loads, even with rendering off; its OpenGL build (`Smithbox.OpenGL.exe`, in
  Smithbox's folder) does not. While the setting is on and Smithbox runs as its Vulkan build, a map job waits and its
  card says how to switch; once the OpenGL build runs, the job waits for Smithbox to open its project, then goes on.
  Switch it off on the Settings tab.

## 0.2.12 - 2026-11-14

- Map jobs keep what they read as they go (S63). Each map's placed characters are read as soon as the map loads and
  saved to disk in the job's folder at once, numbers only. If Smithbox, the graphics driver or DataPiler stops
  partway, **Start again** goes on from there: the maps already read are not loaded or read again. What is kept is
  dropped when the job finishes, is removed, or the game or Smithbox changes.
- A map job pauses once Smithbox holds 300 maps (S63), before Smithbox's Vulkan build runs short of graphics memory;
  the card says how many maps are read and kept. Close Smithbox, start it again, and press **Start again**.

## 0.2.11 - 2026-11-14

- A map that loads with nothing in it now counts as loaded (S62). DataPiler asks Smithbox which maps are loaded by the
  maps' file keys (BatchGetObjects, already on DP4's list), which Smithbox answers for every loaded map, empty or not;
  the entry search it used before saw only maps with something in them. en-0011 stopped twice on three empty tiles of
  the open world in a row, which looked like a stuck Smithbox. Should Smithbox refuse that call, the entry search takes
  over, with a warning. The loaded maps are also asked for together, not one call per map.

## 0.2.10 - 2026-11-14

- A placed character's property that the part does not have is read as -1 (S60): Smithbox leaves it out of its answer,
  as for a character without dialogue (no TalkID), and en-0007's first full read stopped on it as "not a number".
- A map that never shows as loaded is described as such (S61): either Smithbox could not load it, or it loaded with
  nothing to list, as m10_01_00_99 on the owner's PC, which Smithbox's auto-save named among its loaded maps.
## 0.2.9 - 2026-11-14

- A map not loaded in 10 s is skipped for now (S58), not after 5 minutes: the limit stretches to three times the slowest
  load seen in the run, skipped maps are asked for once more at the end, a map that loads late is read all the same, and
  three in a row stop the job only if none of them loaded late. A job may set its own limit (`load_maps`'s `timeout`,
  5 to 900 s). Maps are asked for again every 2 s while they wait.
- Before a map job, DataPiler reads two of Smithbox's saved preferences (DP19, S59): Enable Model Rendering and the
  skipping of Havok loading. With rendering off the first map gets 10 s; with it on, 300 s and a warning to turn it
  off. Nothing else of that file is kept or logged. Smithbox saves its preferences when it closes, so the log says
  they may lag a change made since.
- Smithbox keeps its log in its own windows only (no file, no server call), so the messages point to its Warning Log
  for why a map did not load.
## 0.2.8 - 2026-11-14

- The newest job really is first (S54): each card now carries the time it was added, which the page sorts by; 0.2.7
  sorted on a field the page never received.
- The top bar shows the full version, 0.2.8 rather than 0.2 (S56).
- A map that will not load no longer holds up the rest (S57): the log names each map as it loads, a map not loaded
  after 5 minutes is skipped with a warning and the next one asked for, and read_placements leaves the skipped maps
  out. Three skipped maps in a row stop the job, as Smithbox is then likely stuck.
## 0.2.7 - 2026-11-14

- Maps load one at a time (S53). Smithbox refuses to start a map load while another runs, so 0.2.3 to 0.2.6 lost nine of
  every ten maps they asked for at once and waited for them in vain. A map not loaded yet is asked for again every
  10 s until Smithbox takes it; the fake server now refuses a load while another runs, as Smithbox does.
- Job cards (S54): the newest job first; each card folds to its title row (▸/▾, remembered in the browser), with Fold
  all and Unfold all; the title row shows the step the job is at and its share done, and every op line its percentage.
- Row reads run four calls at once (S55), the answers kept in the row ids' order; a failure or Cancel stops the rest.
## 0.2.6 - 2026-11-14

- Map loading says what it does (S52): the job card shows maps loaded of maps to load, the time so far and a rough
  guess of the time left, at every poll; the log says how many maps are to load, each batch of ten, and every minute
  how far it is.
- A batch may take as long as Smithbox keeps loading: the job gives up only after 15 minutes with no map loaded, and
  then says why. Smithbox hands a queued map load to its Map Editor only while that editor's tab is in front and its
  window is not minimised (`MapEditorStub.cs` at 2.2.6), which is why en-0007's first run loaded nothing.
## 0.2.5 - 2026-11-14

- Map searches carry their search clause (S51). Smithbox's server library refuses a SearchObjects without one
  (`CheckNonNull(request.Search)`), which DataPiler saw as UNKNOWN: listing the maps sent none, from 0.1.0 on, so every
  map job failed whatever the project's editors. Listing and the loaded check now send an empty clause; the fake
  server refuses a search without one, as Smithbox does.
- A project that lists no map now says to enable the Visual Map Editor (its name in Smithbox 2.2.6's Available
  Editors), press Update Project and restart Smithbox; an UNKNOWN on a map search says the server failed.
## 0.2.4 - 2026-11-14

- DP17 (S48): what `unused_names` makes, numbers and layers only, is not held to check 6's half, so job en-0006's 269
  of 483 name numbers can be shared whole.
- DP18 (S49): check 3 compares with the texts of the name sets DataPiler uses (character and place names), not every
  text imported: with the whole item container imported, ordinary words (a table named `unused`, a log line listing
  files) collided with item descriptions. Copy for sharing leaves a failing line out and says how many, instead of
  refusing the whole copy.
- Quit (S50): the window closes at once after a normal stop, and the page asks the browser to close its tab, which it
  does where the tab holds a single page, as the one the launcher opens does.
## 0.2.3 - 2026-11-14

- `unused_names` (S47): the entries of a text set that no row of a table names, with their layers and, locally,
  their texts. Narrowed from the start, as a pick for a purpose (the names the game sets elsewhere, boss bars among
  them); check 6 measures it against the set's entries.
- Maps (S44): Smithbox lists every map of its project for a file search, loaded or not, so 0.2.x read every map as
  loaded. The link now lists the project's maps (`all_maps`, also `map_ids`, so Extract can load every map) and
  tells a loaded map by an entry search. `open_maps` skips map ids the project does not have and waits for real
  loading; `read_placements` skips such ids and still fails on a map the project has but has not loaded. When the
  server fails on maps (UNKNOWN), the error says the Map Editor is most likely not enabled in the project.
- Map families (S45): `load_maps` and `read_placements` take `m10_*` for every map of an area; a job naming one asks
  before it starts.
- Boss slots (S46): `filter` takes `"slots": "boss"`, keeping placements whose entity id ends 800 to 899, a pick for a
  purpose (DP8).
## 0.2.2 - 2026-11-08

- `join_names` also makes `layer`: the earliest layer of the imported text that holds the name, 0 the base game, 1
  DLC 1, 2 DLC 2, -1 when no name is found (S43). A number, so a count by it is a summary, and a named table keeps it
  beside its ids.
## 0.2.1 - 2026-11-08

- The Imported tab (DP16, the owner's request): the text containers in the text database, with their language,
  wrappers, entries, placeholders left out and which names each holds per layer (base game, DLC 1, DLC 2), counts
  only; what jobs can use now; and Remove, which takes an import out of the database (its export file stays).
- The game's `[ERROR]` placeholder texts are no longer imported, never count as names and are no longer texts for the
  guard's check 3; 0.2.0's imports are cleaned when the database opens, without a new export (S40).
- Extract's names rows end their wait once one export arrives (Smithbox 2.2.6 shows one Item container per language,
  `item_dlc02`, holding the base game and both DLC layers), and their steps follow Smithbox 2.2.6 (S42).
## Unreleased (0.2.0)

Built from [design 0002](docs/design/0002-design.md) and its build plan
([build-plan-0.2.md](docs/design/build-plan-0.2.md)), with the owner's decisions DP11 to DP15; what the build settled
is S27 to S38 in [settled.md](docs/design/settled.md). Not yet tried on a real PC: see the release notes.

- **The Update… button (DP11, S27 to S31, S37, S38).** Three presses: the check (`releases/latest` on GitHub's API),
  the download into `update/<version>/`, and Install and restart. `datapiler/update.py` is the only module that opens
  a connection to anywhere but `127.0.0.1`, reached only from `POST /api/update` (`test_update_static.py` holds it to
  that): GitHub's four hosts, https only, every redirect checked, each call logged by host and path, an answer cached
  for ten minutes and a failure never. The download is proved before anything is unpacked: its size, the release's
  `.sha256`, GitHub's digest, the zip's shape and every file's sha256 in its manifest. Install proves it again,
  extracts the helper, writes `update/pending.json` and exits with code 75.
- **`update-helper.py`**, standard library only: the swap, run by `DataPiler.ps1` from the verified download with the
  Python it found. It acts only on a fresh pending file naming its folder with DataPiler's mutex free, backs up every
  file it will overwrite or remove, writes each new file beside its target and checks the landed file, moves removed
  files into the backup, and puts everything back on any failure; its fixed list (workspace, share, logs, jobs,
  update, the venvs, settings.json and the run-time files) and the workspace and share folders Settings names are never
  touched. `--rollback` is the owner's R; `--check-zip` is the release workflow's check. The app loads the same file to
  prove a download, so both prove a zip the same way.
- **`datapiler/install.py`**: the pending and result files, the install check at each start (every file against
  `manifest.sha256`, a statement, never a repair), and the clean-up once the page is up.
- **`DataPiler.ps1`**: exit code 75 runs the helper, then the new script in the same window with `-AfterUpdate`; a
  failed swap starts the old version again with the helper's reason. Every Y now builds `.venv.new` and swaps it in only
  once pip and the marker succeed; after an update the old venv is kept as `.venv.prev` until the new version's page
  is up. If the new version stops before its page comes up within 90 s, the window offers R.
- **`datapiler.py`**: after an update it binds the old page's port first, so that page reloads itself (a new tab opens
  when the port is taken); exit code 75; the install check, the result kept for the page, and the clean-up at page-up;
  FOLDERS's Detect and UPDATE's Updater wired in.
- **The launcher** says "DataPiler is updating - see its window." while an update runs, and opens nothing.
- **The release** carries `DataPiler/manifest.sha256` (`tools/manifest.py`) and passes the helper's `--check-zip`
  before the draft (S28). CI's Windows job builds the venv as `.venv.new` and renames it, as the script does.
- **The pop-up** (`page/update.js`, `page/update.css`): every state of the design's mock; the release notes as a tree
  of text, never HTML; the restarting wait and the result after the reload.
- **Detect and Set folder… on Settings (DP12, DP13, S32 to S34).** Each of the three folder rows has Detect, Set
  folder… and a live check line (✓, ! or ✗). Detect looks only in what the PC already records, never walking a drive:
  the running Smithbox's own exe path (`QueryFullProcessImageNameW`), Smithbox's record of its projects for the project
  and game folders (`datapiler/sbproject.py`, a lead until checked on the owner's PC; a form it does not recognise is
  said so, with the picker offered), Steam's install path, `libraryfolders.vdf`, the game's app manifest and the
  uninstall entry (`datapiler/steam.py`, registry values from a fixed table only) and the running game as further game
  sources and the cross-check, and the folders used here before. The expansion comes from the app manifest's
  `dlcappid` values, shown with their ids, never matched against a built-in one. Windows' record of programs started
  is not read (DP13). Nothing is saved until Use, Choose this folder or Save; candidates live in memory only, and log
  lines name the source and the count, never a path. The picker (`datapiler/dirs.py`, `page/folders.js`) is drawn in
  the page: folder names only, never a file; it refuses relative and device paths, network shares and Windows' own
  folder; a listing gets 3 s; New folder… in the project picker only. The project folder may not be the game's
  folder, inside it, a folder that holds it, or DataPiler's own folder or inside it (S32).
- **Smithbox seen by its process (DP15).** A watcher reads the process list every 2 s from the start, whatever
  Settings say: the top bar's pill and the Status card read "running" as soon as Smithbox runs, name the exe and its
  build, and say when it stops; two processes are both listed. A running Smithbox in another folder than the one set
  is offered with Use. Smithbox is recognised by any `Smithbox*.exe` (`Smithbox.Vulkan.exe` and
  `Smithbox.OpenGL.exe`, side by side in one folder on the owner's PC), in the folder check, the build, the
  provenance, Detect and the picker.
- **Mask paths on this page (DP14, S35)**, off by default: every path the page draws becomes the log's placeholder
  (Settings, Detect's list, the picker's crumbs, Status), and the path fields turn read-only.
- **Settings across versions (S36):** a key `settings.json` holds that this version does not know is dropped at load
  with a warning, so a version rolled back to keeps the owner's folders; `recent` keeps five folders a row.
- **Found by the integration run** (headless Chromium over invented folders and an invented release): off Windows the
  page's server sets `SO_REUSEADDR`, so the page that asked for an update gets its port back past `TIME_WAIT`, as
  Windows allows without it (still off on Windows); the page's own polls pause while an update restarts, so the old
  page sends nothing with its old token; Detect's log lines say "1 place" and "1 DLC app"; the start line names
  `Smithbox*.exe` when the folder holds no Smithbox exe.
- **Found by the 0.2.0 reviews** (security and correctness):
  - The swap holds off Ctrl+C (the helper ignores it, and the window makes it a key while the helper runs), and an
    interrupt is put back like any failure. A swap cut off all the same (the window closed, the power cut) is put
    back by the window from its backup, after the helper's exit or at the next start: `--rollback` now accepts an
    unfinished backup while `update/pending.json` names the same update, and writes back only what differs.
  - The old window offers R also when the new version's script stops before it starts its app, or cannot run (the
    new script exits 76 when it has settled R itself); a failed R waits for Enter.
  - The never-touched list is checked against the path as the file system resolves it, and a release may not name
    an 8.3 short name (`~` and a digit; `tools/repocheck.py` fails one too); a file whose name changes only in case
    is rewritten, never deleted after it.
  - Mask paths: the picker draws each folder's name masked (the account's folder as `<HOME>`) and opens it by its
    real path, and Up goes to the real parent; the folders Smithbox runs from are taught to the mask as soon as they
    are seen; a folder's mask ends where its name ends (`...\Smithbox` no longer masks `...\Smithbox-old`), and a
    known sibling is matched before a shorter named folder.
  - The provenance's `smithbox_build` is the running Smithbox's, whatever its folder; Smithbox processes of
    different builds refuse the write.
  - Detect no longer proposes Yes for the expansion from any DLC app id: with ids listed, Yes and No are both offered
    and neither is the primary button.
  - The picker refuses Windows' own folder also with a trailing dot or space (`C:\Windows.`), waits for a drive's
    listing under way instead of answering that the drive did not answer, and a folder on a mapped drive is saved
    with its drive letter.
  - S27 and S12 name pip's two hosts, used after an update whose libraries changed and the owner's Y.
- **The version is 0.2.0**: `VERSION`, the launcher's resources, BUILD.md. A job's `needs` above 0.2.0 is refused.
- **Releases carry fewer files (DP9):** the zip (with the exe and the notices inside), its sha256, and
  `THIRD-PARTY-NOTICES.txt` on its own too; the exe's sha256 is in the release workflow's log, which the notes link.
  The README's Licence section names the notices.
- **The zip's one folder is `DataPiler` (DP10):** the zip's name keeps the version; the folder inside does not.

## 0.1.0 (2026-11-08)

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
- **A refused upload gets its answer**: a request refused before its body is read (too large, no token, no length)
  now has its answer sent, then the rest of its body read and dropped (up to 8 MB or 3 s) before the connection
  closes; closing with the body unread let Windows reset the connection before the client read the answer.
- **Releases**: a draft release can also be started with the release workflow's Run workflow button (the session
  that builds DataPiler cannot push tags); its notes come from `docs/release-notes/<version>.md`.
