# DataPiler: notes for Claude

DataPiler is a local tool on the owner's PC that extracts Elden Ring's data from the owner's own install through
Smithbox, for EldenNet's research (EldenNet O54 to O57). Its decisions are in [docs/DECISIONS.md](docs/DECISIONS.md)
(DP1 onwards). EldenNet's own rules bind it too; where they overlap, follow the stricter.

## Privacy and safety: the sweep comes first

- Nothing is pushed or uploaded before the privacy and safety sweep passes. The sweep is the owner's `privsweep`, kept
  in EldenNet under `tools/privsweep/` and installed as git's global pre-push gate. If `~/.config/privsweep` is
  missing, run `python3 -I tools/privsweep/privsweep.py install` in the EldenNet checkout first. Sweep by hand anything
  the gate doesn't cover, such as a file sent to the owner or a published page.
- Never bypass it: no `--no-verify`, no change to `core.hooksPath`, no HOME or GIT_CONFIG override.
- Never commit or upload anything personal about the owner (DP3, in the owner's words: "never expose any delicate
  information about my privacy or security"): real name, account names, machine names, contact details, API keys,
  local paths, local endpoint addresses or IPs. Examples and tests use placeholders and invented data.
- Commit identities are noreply addresses only; use the environment's default git identity. No model identifiers of
  the assistant in files, apart from the commit trailer.

## Game data

- Never commit game files, game text (names, dialogue, descriptions, FMG), params (as dumps or whole columns),
  developer labels, the game's keys, Oodle, or any part of Smithbox. Fixtures are invented.
- Share files hold ids, numbers, counts, our own labels and a provenance block only, and pass the guard (request 0001,
  "The guard") before they are written. Names and other game text stay in the local workspace on the owner's PC.
- Smithbox's own labels and annotations are never facts: only numbers from the owner's data (EldenNet O48).
- The Smithbox server link (DP4): read calls only, from a fixed allowlist; only while the game is not running; never a
  project folder that is the game's folder or inside it.
- No me3 and no fromsoftware-rs, in any form (EldenNet O47, O48); none of Smithbox's me3 features.
- Jobs are data, never code: a closed set of operations, a schema version, no scripts, shell commands, outside paths
  or network beyond Smithbox's local server.

## Licences

- DataPiler is MIT. Write our own code. Read a dependency's licence before adopting it and list it in `NOTICE`.
- Smithbox is MIT and is never bundled. SoapstoneLib's definitions (MIT) may be used to generate the gRPC client, with
  its notice in `NOTICE`.
- Untrusted copies (clones, downloads) go in their own folder outside the repository and are never built or run.

## Working rules

- Work on a topic branch (`design/`, `feat/`, `fix/`, `docs/`, `test/`, `chore/`), never directly on `main` unless the
  owner asks. Open a pull request only when asked.
- Ask the owner, with a recommendation, about anything the design leaves open, as a DP entry marked Open.
- Text the owner reads uses British spelling.
