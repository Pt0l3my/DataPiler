# What the designers settled from design 0001

The owner's decisions are in [../DECISIONS.md](../DECISIONS.md); this is the designers' own log, one entry each (S1
onwards), for points design 0001 left to us or suggested. Each can be reopened; one that would change an owner's rule
becomes a DP question instead.

| # | Point | Settled | Why |
|---|---|---|---|
| S1 | The shape (§1) | As design 0001 §1: `DataPiler.exe`, `DataPiler.ps1`, `datapiler.py` with its modules, `soapstone/`, `requirements.lock`, `launcher-src/`, and the workspace, share, logs and jobs folders kept out of the repository | It is the request's shape and Jobrunner's, with the PowerShell window |
| S2 | Python's two libraries (§4) | A local `.venv` made at the first start from `requirements.lock` (wheels only, a sha256 for every file), after the owner answers Y; N starts DataPiler without the server link | One download, checked by hash, with the owner's consent; no binaries redistributed |
| S3 | The gRPC client (§4) | Message classes only, generated once from SoapstoneLib's `.proto` files at a pinned commit, committed with its MIT notice; each allowed call built by hand from a fixed table, so no stub for any other call exists; a test fails if any other method name appears in the code | The allowlist is enforced by construction, not by care |
| S4 | The exe's build (§3) | A GitHub Actions workflow on Windows builds the launcher on a tag the owner pushes and attaches it with its sha256 to the release; the `BUILD.md` route stays for a local build | For a public repository, anyone can see the exe comes from the source |
| S5 | Floats in share files (§7.1) | Allowed: any finite JSON number; NaN and infinities refused | A finite number cannot carry text; some character fields are floats |
| S6 | Labels against the text database (§7.2) | The guard's text check skips values that are exactly one of DataPiler's fixed labels; the label list is checked against the text database once it is built, and a label found there is renamed | Otherwise a label that happens to be a game word fails forever |
| S7 | "The game is closed" (§7.3) | Neither `eldenring.exe` nor `start_protected_game.exe` is running, by name and, with the game's folder known, by path | Easy Anti-Cheat's launcher starts the game |
| S8 | Map loading (§7.4) | Loads maps in batches, and asks before loading more than ten | `OpenResource` changes Smithbox's state and memory, not its data |
| S9 | Smithbox's server switch (§7.5) | Read and shown, never written; at the end of a session the Status card says how to switch it off | Smithbox's files are read only |
| S10 | Guided exports (§7.6) | Accepted by shape (Smithbox's text export format, the container, the language), never by file name; anything else stays in the inbox with the reason | A file name proves nothing |
| S11 | Sharing logs (§7.7) | **Copy for sharing** on the Terminal tab runs the guard's text and owner checks over the lines first | Logs are masked by construction, but a check costs nothing |
| S12 | The network (§7.8) | None after the first start, and none at the first without the owner's Y; the page loads nothing from elsewhere | DP3, the owner's emphasis on privacy and security |
| S13 | Versions (§7.9) | A job may say `"needs": "<version>"`; an older DataPiler refuses it, saying so | Jobs are written ahead of releases |
| S14 | The repository's own check (§7.10) | A CI check fails any change that adds a file under `workspace/`, `share/`, `logs/` or `jobs/`, a share file, or a file the privacy sweep flags | It catches a forced add |
