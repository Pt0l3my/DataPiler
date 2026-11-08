# Smithbox's record of its projects: leads for Detect

*Research for design 0002 §3.4 ("The project") and DP13, 2026-11-08. Every statement about Smithbox here is a **lead**:
read in Smithbox's source, not yet seen on the owner's PC. Under EldenNet O48 DataPiler relies on none of it until
§7's checks pass on that PC; until then Detect treats the record as a source to show, never as a fact.*

## 1. What was read, and how

- **Commit.** vawser/Smithbox at **`d144cc7f85b755665f3291edf1bae847094c1963`**, the commit of tag `2.2.6` (the
  version the owner runs), from `git ls-remote --tags` on 2026-11-08. The same files were compared at
  `e2dbcae7141f4ae2738f1c39c1feb955b0f33079`, the default branch EldenNet's ER08 read (§8).
- **Method.** Single files from `https://raw.githubusercontent.com/vawser/Smithbox/<commit>/<path>`. No clone, no tree
  listing, no GitHub API: paths were found by `HEAD` requests on guessed paths, and `ls-remote` listed refs only.
  Nothing else of Smithbox was read, and no code is copied here: the key names below are the format's own, the rest
  is in our words. The copies stay in the session's untrusted folder, outside the repository.
- **Files** (under `src/Smithbox.Program/`; folder names contain spaces):

| File | Lines used | What it shows |
|---|---|---|
| `Editors/Project Editor/Utilities/ProjectUtils.cs` | 65–100 | the base, configuration and projects folders; the project-local folder |
| `Editors/Project Editor/ProjectOrchestrator.cs` | 22–60, 101–448 | the project list, how it is loaded and saved, the auto-load mark, the legacy `project.json` |
| `Editors/Project Editor/JSON/ProjectDescriptor.cs` | 10–39, 70–123, 189–277 | the fields of a project record and of the legacy `project.json` |
| `Editors/Project Editor/JSON/ProjectJsonSerializerContext.cs` | 8–27, 54 | how the records are serialised |
| `Editors/Project Editor/Enums/ProjectType.cs` | 10–47 | the project type's numbers |
| `Editors/Project Editor/ProjectEntry.cs` | 21–40, 119–141, 356–362 | what a project needs to load; what it takes from the data folder |
| `Application/CFG.cs` | 85–101, 1418–1463 | the two auto-load settings; `Configuration.json` |
| `Application/Startup.cs` | 33–74 | `Startup.json` in the same folder |
| `Smithbox.cs` | 28, 161, 224–231 | the orchestrator's creation; the window title |
| `Smithbox.Program.csproj` | item lines only | that folder names carry spaces (to find the paths) |

## 2. Where the record is

- **Base folder:** `%LOCALAPPDATA%\Smithbox` (`ProjectUtils.cs:65-70`), made at start with the two below
  (`ProjectOrchestrator.cs:109-127`).
- **Configuration:** `%LOCALAPPDATA%\Smithbox\Configuration` (`ProjectUtils.cs:72-77`), holding `Configuration.json`
  (`CFG.cs:1418-1463`) and `Startup.json` (`Startup.cs:35-37, 62-64`).
- **Projects:** `%LOCALAPPDATA%\Smithbox\Projects` (`ProjectUtils.cs:90-95`): **one file per project**, named
  `<ProjectGUID>.json` (`ProjectOrchestrator.cs:130-144`). The list of projects is every `*.json` directly in that
  folder (`146-158`); Smithbox reads each as a project record and logs and skips one that fails (`160-195`). There is
  no separate list of recent projects and no ordering: the folder is the list.
- **Per Windows user, not per copy of Smithbox.** The folder comes from .NET's `LocalApplicationData` special folder,
  which on Windows is the Local AppData known folder. Every copy of Smithbox the owner runs shares one record, so the
  Smithbox folder that DP13 reads from the running process does not locate it. Detect should ask Windows for that
  known folder through the Windows adapter (`SHGetKnownFolderPath`, `FOLDERID_LocalAppData`), as .NET does, rather
  than from the `LOCALAPPDATA` variable.
- **Project-local data:** Smithbox keeps its own files for a project under `<ProjectPath>\.smithbox\Project`
  (`ProjectUtils.cs:97-100`); ER08 found its text exports under `<ProjectPath>\.smithbox\Workflow`. Whether the folder
  always exists was not read.

## 3. The format of a project record

- **Serialiser.** .NET's System.Text.Json with a source-generated context (`ProjectJsonSerializerContext.cs:8-11, 25`):
  indented, public fields included, and no naming policy or enum converter among its options. So the keys are the
  C# names as written (PascalCase) and the project type is written **as a number** (inferred from the options it
  lacks: to confirm, §7). A GUID is written as a string.
- **Writing.** `File.WriteAllText` (`ProjectOrchestrator.cs:142`): UTF-8 without a BOM by .NET's default, and **not
  atomic** (the file is truncated, then written). A read that meets a half-written file sees invalid JSON.
- **When it is written:** on creating a project, on editing its configuration, whenever any project is marked for
  auto-load (every project's file is saved then), and for every project when Smithbox exits (`101-107, 225-247,
  305-319`). The files' modified times therefore say nothing about which project was used last.
- **Fields** (`ProjectDescriptor.cs:10-39`), and what Detect would read:

| Key | JSON type | Meaning | Detect |
|---|---|---|---|
| `ProjectGUID` | string (GUID) | the record's id and file name | not needed |
| `ProjectName` | string | the name the owner gave | read: shown in Detect's list, matched to the window title (§4) |
| `ProjectPath` | string | **the project (mod) folder** | read: candidate for the Project field |
| `DataPath` | string | **the game's data folder**, the `Game` folder for Elden Ring | read: candidate for the Game field |
| `ProjectType` | number | **the project type**: `8` is Elden Ring (`ProjectType.cs:36-37`) | read: only `8` is kept |
| `AutoSelect` | bool | the project Smithbox opens at start (§4) | read |
| `ImportedParamRowNames`, `FolderTag`, `EnableExternalMaterialData`, the `Enable…Editor` flags, `PinnedParams`, `PinnedRows`, `PinnedFields` | various | editor state | never read; dropped at once |

- **Why `DataPath` is the `Game` folder.** A project does not load unless `ProjectPath` and `DataPath` both exist and
  the type is set (`ProjectEntry.cs:119-141`); for Elden Ring Smithbox copies `oo2core_6_win64.dll` from `DataPath`
  (`356-362`), a file of the game's `Game` folder; and an imported DSMapStudio-style `project.json` puts its `GameRoot`
  into `DataPath` (`ProjectDescriptor.cs:70-76`).
- **Project types.** The numbers are assigned explicitly: Undefined 0, DES 1, DS1 2, DS1R 3, DS2S 4, DS3 5, BB 6,
  SDT 7, **ER 8**, AC6 9, DS2 10, NR 15 (Nightreign, a different game and folder). The default branch adds 16 and 17
  (§8). A record of any type but 8 is another game's, and Detect only counts it.
- **Shape, with invented values** (the fixtures' model; key order is not significant; editor flags shortened):

```json
{
  "ProjectGUID": "00000000-0000-4000-8000-000000000001",
  "ProjectName": "Example project",
  "ProjectPath": "C:\\Mods\\ExampleProject",
  "DataPath": "C:\\Games\\SteamLibrary\\steamapps\\common\\ELDEN RING\\Game",
  "ProjectType": 8,
  "ImportedParamRowNames": false,
  "AutoSelect": true,
  "FolderTag": "",
  "EnableExternalMaterialData": true,
  "EnableParamEditor": true,
  "PinnedParams": [],
  "PinnedRows": {},
  "PinnedFields": {}
}
```

## 4. How the open project is known

Nothing on disk says which project is open: Smithbox holds it in memory (`SelectedProject`,
`ProjectOrchestrator.cs:26`). Two signs reach outside it.

**1. The auto-load mark, `AutoSelect`.** When Smithbox starts and `Project_Enable_Auto_Load` is on (`CFG.cs:90`,
default on), it starts the marked project (`ProjectOrchestrator.cs:197-220`). When a project is started and
`Project_Enable_Automatic_Auto_Load_Assignment` is on (`CFG.cs:91`, default on), Smithbox marks that project, clears
the mark on every other and saves them all (`287-290, 305-319`). With the defaults, the marked record is the project
started last, which is normally the one open. Where it is not:

- the mark moves only after the load has run (`273, 287`): during a load, the previous project still carries it;
- the load's result is not looked at (`273`), so a project whose folders are missing is marked all the same;
- reloading a project does not mark it (`348-396`), and unloading one does not clear its mark (`338-346`): a project
  closed in the project list still carries it;
- with automatic assignment switched off, the mark is the owner's own choice, not the last project started;
- at 2.2.6 a project imported from a legacy `project.json` is created marked (`ProjectDescriptor.cs:78, 105`), and the
  others keep their marks until a project is started, so **two marks** can exist; the start loop then starts each
  marked project in turn (`ProjectOrchestrator.cs:197-220`), and the last in the folder's order stays open.

**2. The window title.** Smithbox sets its window's title to `<ProjectName> - <version>` when it starts or reloads a
project (`Smithbox.cs:224-227`; `ProjectOrchestrator.cs:253, 352`), and back to `Smithbox - <version>` when one is
unloaded (`Smithbox.cs:228-231`; `ProjectOrchestrator.cs:345`). It is set before the load, so it also names a
project still loading. The Windows adapter could read the title of the running Smithbox's top-level window (the
process DP13 already finds) with `EnumWindows`, `GetWindowThreadProcessId` and `GetWindowTextW`: read-only, held in
memory and never logged. **This is a new read for the adapter, not in design 0002: the lead's call** (an S entry). The
version's own text was not read, so the match strips the part after the last ` - ` and compares the rest with
`ProjectName`; names need not be unique.

**Not used: Soapstone.** `GetServerInfo` returns open resources with a `project_json_path` field (SoapstoneLib's
`common.proto:46-49`, read for 0.1), but it is not one of DataPiler's allowed calls (DP4; `link.ALLOWED`), and what
Smithbox puts there was not read. Adding it would be a DP question; not recommended for 0.2.

**Recommended rule.** Among the Elden Ring records:
- if the title names exactly one of them, that one is tagged **"open in Smithbox"**;
- otherwise, if exactly one is marked, it is tagged **"Smithbox opens this one at start"** (the page says plainly that
  it is probably, not certainly, the open one);
- otherwise no record is tagged.

Either way Detect only lists: nothing is set until the owner presses Use (design 0002 §3.3).

## 5. The legacy `project.json` in the project folder

- Smithbox 2.2.6 writes `<ProjectPath>\project.json` "for other tools" only when a project is first created, and only
  if none is there (`ProjectOrchestrator.cs:402-418`, reached with its first-time flag only from `CreateProject`,
  `225-238`, through `SaveProject`, `138`); starting and reloading pass no flag, so they write nothing (`255, 354`).
- It holds `ProjectName`, `GameRoot` (the `DataPath` at creation), `GameType` (the type's number), the pinned lists,
  `UseLooseParams`, `PartialParams` and `LastFmgLanguageUsed` (`ProjectDescriptor.cs:189-232`).
- So **its `GameRoot` can be stale**: changing a project's data folder in Smithbox does not update it.
- **Consequence for design 0002 §3.4.** The check line "a Smithbox project for this game" should rest on the AppData
  record (a record whose `ProjectPath` is this folder and whose `DataPath` is the Game field's folder). `project.json`
  (or a `.smithbox` folder) gives only the weaker "a Smithbox project file is here". Detect never takes a game folder
  from `project.json`.

## 6. What Detect should do

**Reading** (only when the owner presses Detect; Smithbox need not be running for the record, only for the title):
1. The folder is `<Local AppData>\Smithbox\Projects`, as §2. Read only `*.json` directly inside it, at most 64 files
   of at most 1 MiB each (generous for records of a few hundred bytes; past either cap, read none and say so).
2. Open each read-only; decode as UTF-8, accepting a BOM. If one fails to parse, wait half a second and read it once
   more (a write may be under way, §3).
3. A record is **recognised** only if it is a JSON object with `ProjectPath`, `DataPath` and `ProjectName` as strings,
   `ProjectType` as an integer (and not a boolean: Python's `bool` is an `int`), or the string `"ER"` in case a later
   version writes names, and `AutoSelect` as a boolean or absent. Any other key is ignored, whatever it holds (the
   default branch already differs there, §8).
4. Keep the five values and drop the rest of the object at once. Keep only type `8` (or `"ER"`); count the others as
   "for another game".
5. Each path must be an absolute drive path (`X:\…`): no network share, no `\\?\` or device path, no NUL. Compare
   paths case-insensitively after normalising separators and a trailing backslash.

**Showing** (design 0002 §3.3's list, with the source tag "Smithbox's project record"):
- `ProjectPath` as a Project candidate and `DataPath` as a Game candidate, each with its record's name and §4's tag.
  Each runs its row's own live check (for the game, `eldenring.exe` is there; for the project, design 0002 §3.4's
  rules): one that fails shows its ✗, and Use is refused as on any save.
- **Steam's cross-check** (DP13): if Steam's library list gives a game folder, the Game candidate says "Steam's
  library list agrees" when they are the same folder, and lists both, choosing neither, when they differ.

**When the format is not the expected one,** Detect says so and offers the picker (Set folder…); it never guesses:
- **no Projects folder, or it cannot be read:** "No Smithbox project record was found" (normal for a Smithbox older
  than 2.x, or one run by another Windows user);
- **files, but none recognised:** "Smithbox's project record is in a form this DataPiler does not recognise
  (N files)";
- **some recognised:** they are listed, with "N more files not recognised";
- **a cap exceeded:** treated as not recognised, with the reason;
- **two or more Elden Ring records marked, or none:** listed with no "open" tag (§4).

Never: a pattern search over the text, a fallback to other keys or to `project.json` for the game folder, a write,
lock or rename in Smithbox's folders, or a read of `Configuration.json` (it holds other folders of the owner's, and the
two auto-load settings are not needed for the rule above).

**Privacy** (design 0002 §3.5, DP3): the names and paths stay in memory for the session; the masking filter learns
each path as `<FOUND>`; the log names only sources and counts, for example "project: 2 places from Smithbox's
project record, 1 open, 3 for another game, 1 not recognised"; and the "Mask paths on this page" switch (DP14)
covers the list.

**Tests** (invented fixtures only): the 2.2.6 shape; the default branch's shape; two marks; none; a title match; a
`ProjectType` of `"ER"`, of `true` and of `15`; a missing key; a non-object; invalid JSON, recovered on the second
read and not; a BOM; an oversize file; too many files; a network-share path; a relative path; no folder.

## 7. To check on the owner's PC (O48)

Detect's own first run is the check, reported by counts so that no path or name leaves the PC:
1. `%LOCALAPPDATA%\Smithbox\Projects` exists and holds one `.json` per project in Smithbox's project list.
2. The owner's Elden Ring project is recognised, with `ProjectType` the number `8`.
3. Its `DataPath` is the game's `Game` folder (the row's check finds `eldenring.exe`), and Steam's list agrees.
4. Its `ProjectPath` is the project folder the owner chose in Smithbox.
5. After the owner opens a project in Smithbox and Detect is pressed again, exactly one record is marked and it is the
   one open; with the title read adopted, the tag says "open in Smithbox".
6. Whether the project folder holds `project.json` and `.smithbox`.

If any check fails, the format is treated as not recognised (§6) until this note is corrected.

## 8. At the default branch (`e2dbcae`)

The same files at the default branch keep the folder, the file naming, the five keys and their meaning, so Detect's
reading survives the next release as far as can be seen. What differs: the editor flags (`EnableMapDataEditor`
removed, `EnableTimeActEditor` added); types 16 and 17 added (both other games); an imported legacy project is no
longer marked (`ProjectDescriptor.cs:78-79` there); auto-load starts only the first marked record
(`ProjectOrchestrator.cs:266-276` there); a crash-recovery path watches a project while it loads (its reader was not
read); and `Startup.json`'s loading is hardened. None of it changes §6.
