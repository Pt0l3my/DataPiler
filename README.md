# DataPiler

A local companion for [Smithbox](https://github.com/vawser/Smithbox) on your own PC. It extracts Elden Ring's data
from **your own install**, for the research behind [EldenNet](https://github.com/Pt0l3my/EldenNet), an LLM-driven
NPC framework for Elden Ring. You start it from an executable, it opens as a tab in your browser, and it holds all its
tools there: Smithbox's status, data extraction by type or by bundle, a drop zone for jobs, and its logs.

**Status: design.** Nothing is built yet. The owner's decisions are in [docs/DECISIONS.md](docs/DECISIONS.md), and
the design is being asked of the PandorumLLM session ([docs/requests/0001-design.md](docs/requests/0001-design.md)).

## What it will and won't do

- It reads data from your own game through Smithbox, which you install yourself. It never bundles, downloads or
  redistributes Smithbox or any game file.
- The game's text and data stay on your PC. What DataPiler writes for sharing holds numbers and counts only, and is
  checked before it is written.
- It talks to Smithbox's local server with read calls only, and only while the game is closed.
- It is not a Smithbox plugin and is not affiliated with Smithbox, FromSoftware or Bandai Namco.

## Licence

[MIT](LICENSE). ELDEN RING is a trademark of FromSoftware and Bandai Namco.
