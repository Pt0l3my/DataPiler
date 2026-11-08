"""The Extract rows, the bundles and each server row's built-in ops (design 0001 §2 and §6, build plan §4.7).

A server row is run as a built-in job in `datapiler-job/1` form, with the id `extract-<row id>`: its full numbers go
by `write_local` to `workspace/local/extract/<row id>.json`, and at most a counts-only summary (counts, never an id:
DP8, settled S18) by `write_share` to `share/extract-<row id>.json`, through the guard like any share file. A guided
row shows its steps and waits for its text containers to arrive in the inbox."""

from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    id: str                       # "character_rows"
    name: str                     # "Character rows"
    help: str                     # the "?" text
    sources: tuple[str, ...]      # ("server",) or ("guided",)
    gives: str                    # "row ids, name numbers"
    goes_to: str                  # "workspace", or "workspace+counts": a counts-only summary goes to share too (DP8)
    steps: tuple[str, ...]        # guided rows: the numbered steps, with <WORKSPACE> as a placeholder
    containers: tuple[str, ...]   # guided rows: the text containers it waits for
    needs_maps: bool


# The containers of the character names (request 0001, "What it must do", 3). The place names sit in the same
# containers, by ER01's lead (§8.2; build plan §10, P3; settled S22), which join_names verifies with the owner's own
# numbers before it uses them (textdb.TEXT_SETS).
CHARACTER_NAME_CONTAINERS = ("item", "item_dlc01", "item_dlc02")
PLACE_NAME_CONTAINERS: tuple[str, ...] = CHARACTER_NAME_CONTAINERS
COUNTS = "workspace+counts"

_EXPORT_STEPS = (
    "In Smithbox, open the Text Editor, showing the language set in DataPiler's Settings",
    "Choose the container `%s`",
    "On the Data Transfer tab, set the export directory to <WORKSPACE>\\inbox (once)",
    "Export Text, then Export Selected Container",
)


def _steps(containers: tuple[str, ...]) -> tuple[str, ...]:
    if not containers:
        return ("The text container that holds these names is not confirmed yet, so this row cannot run in 0.1",)
    steps = [_EXPORT_STEPS[0], _EXPORT_STEPS[1] % containers[0], _EXPORT_STEPS[2], _EXPORT_STEPS[3]]
    if len(containers) > 1:
        rest = ["`%s`" % c for c in containers[1:]]
        steps.append("Repeat steps 2 and 4 for %s" % (" and ".join(rest) if len(rest) <= 2 else
                                                       ", ".join(rest[:-1]) + " and " + rest[-1]))
    return tuple(steps)


ROWS: tuple[Row, ...] = (
    Row("character_rows", "Character rows",
        "NpcParam rows: row id, name number (signed - negative means none) and a few numeric fields",
        ("server",), "row ids, name numbers", COUNTS, (), (), False),
    Row("character_names", "Character names",
        "The name behind each name number - stays in the workspace, never in a share file",
        ("guided",), "names, local only", "workspace", _steps(CHARACTER_NAME_CONTAINERS), CHARACTER_NAME_CONTAINERS,
        False),
    Row("dialogue_links", "Dialogue links", "TalkParam rows: row id and message number (signed)",
        ("server",), "row ids, message numbers", COUNTS, (), (), False),
    Row("map_placements", "Map placements",
        "Needs the maps loaded in Smithbox - DataPiler can load them through OpenResource, asking first above ten "
        "maps", ("server",), "entity, row, dialogue and model ids per map", COUNTS, (), (), True),
    Row("places", "Places", "WorldMapPlaceNameParam and BonfireWarpParam numbers",
        ("server",), "place and warp numbers", COUNTS, (), (), False),
    Row("place_names", "Place names", "The name behind each place number - stays in the workspace, never in a share "
                                      "file. The same exports as the character names", ("guided",),
        "place names, local only", "workspace",
        _steps(PLACE_NAME_CONTAINERS), PLACE_NAME_CONTAINERS, False),
)

BUNDLES: dict[str, tuple[str, ...]] = {
    "roster": ("character_rows", "character_names", "dialogue_links"),
    "placements": ("map_placements",),
    "places": ("places", "place_names"),
    "everything": ("character_rows", "character_names", "dialogue_links", "map_placements", "places", "place_names"),
}

_BY_ID = {r.id: r for r in ROWS}

# The share file's notes for the summaries: our own labels (guard.LABELS).
_SUMMARY = ["summary", "vanilla_rows"]

_OPS: dict[str, list[dict]] = {
    "character_rows": [
        {"op": "fetch_rows", "as": "npc", "param": "NpcParam", "fields": ["id", "nameId", "teamType", "npcType"]},
        {"op": "write_local", "name": "character_rows", "tables": ["npc"]},
        {"op": "count", "as": "rows_total", "rows": "npc"},
        {"op": "count", "as": "rows_with_name_number", "rows": "npc", "where": {"nameId": {"ge": 0}}},
        {"op": "write_share", "name": "extract-character_rows", "tables": ["rows_total", "rows_with_name_number"],
         "columns": {"rows_total": ["count"], "rows_with_name_number": ["count"]}, "notes": _SUMMARY},
    ],
    "dialogue_links": [
        {"op": "fetch_rows", "as": "talk", "param": "TalkParam", "fields": ["id", "msgId"]},
        {"op": "write_local", "name": "dialogue_links", "tables": ["talk"]},
        {"op": "count", "as": "rows_total", "rows": "talk"},
        {"op": "count", "as": "rows_with_message", "rows": "talk", "where": {"msgId": {"ge": 0}}},
        {"op": "write_share", "name": "extract-dialogue_links", "tables": ["rows_total", "rows_with_message"],
         "columns": {"rows_total": ["count"], "rows_with_message": ["count"]}, "notes": _SUMMARY},
    ],
    "map_placements": [
        {"op": "read_placements", "as": "placed", "maps": "all"},
        {"op": "write_local", "name": "map_placements", "tables": ["placed"]},
        {"op": "count", "as": "placements_total", "rows": "placed"},
        {"op": "distinct", "as": "maps_seen", "rows": "placed", "by": ["map"]},
        {"op": "count", "as": "maps_total", "rows": "maps_seen"},
        {"op": "write_share", "name": "extract-map_placements", "tables": ["placements_total", "maps_total"],
         "columns": {"placements_total": ["count"], "maps_total": ["count"]}, "notes": ["summary", "loaded_maps_only"]},
    ],
    "places": [
        {"op": "fetch_rows", "as": "place_rows", "param": "WorldMapPlaceNameParam", "fields": ["id"]},
        {"op": "fetch_rows", "as": "warp_rows", "param": "BonfireWarpParam", "fields": ["id"]},
        {"op": "write_local", "name": "places", "tables": ["place_rows", "warp_rows"]},
        {"op": "count", "as": "places_total", "rows": "place_rows"},
        {"op": "count", "as": "warps_total", "rows": "warp_rows"},
        {"op": "write_share", "name": "extract-places", "tables": ["places_total", "warps_total"],
         "columns": {"places_total": ["count"], "warps_total": ["count"]}, "notes": _SUMMARY},
    ],
}


def row(row_id: str) -> Row:
    """KeyError for a row that is not in the catalogue."""
    return _BY_ID[row_id]


def job_id(row_id: str) -> str:
    return "extract-" + row_id


def ops_for(row_id: str) -> list[dict]:
    """A server row's built-in ops in datapiler-job/1 form: its full numbers by write_local to
    workspace/local/extract/<row id>.json, and a counts-only summary (no id, DP8) by write_share to
    share/extract-<row id>.json. KeyError for a guided row."""
    return copy.deepcopy(_OPS[row_id])


def share_names() -> dict[str, str]:
    """{share name: built-in job id} for every server row: these names are Extract's."""
    out: dict[str, str] = {}
    for rid, ops in _OPS.items():
        for o in ops:
            if o["op"] == "write_share":
                out[o["name"]] = job_id(rid)
    return out


def public() -> dict:
    """GET /api/catalogue: {"rows": [...], "bundles": {...}}."""
    return {"rows": [{"id": r.id, "name": r.name, "help": r.help, "sources": list(r.sources), "gives": r.gives,
                      "goes_to": r.goes_to, "steps": list(r.steps)} for r in ROWS],
            "bundles": {k: list(v) for k, v in BUNDLES.items()}}
