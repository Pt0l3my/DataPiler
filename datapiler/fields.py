"""The params and fields DataPiler reads: the field allowlist (design 0001 §6, build plan §4.6).

Only numeric fields are listed, each with its column type inside the runner (`int`, `number` or `bool`). A field
that is not listed here cannot be named in a job. The places' params hold `id` only until their numeric fields are
confirmed from the server's own answers on the owner's PC (build plan §10, P4; EldenNet O48): a field is added here
only once it is verified, never from a label or annotation of Smithbox's."""

from __future__ import annotations

import re

TYPES = ("int", "number", "bool")

FIELD_RX = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")

PARAMS: dict[str, dict[str, str]] = {
    "NpcParam": {"id": "int", "nameId": "int", "teamType": "int", "npcType": "int"},
    "TalkParam": {"id": "int", "msgId": "int"},
    "WorldMapPlaceNameParam": {"id": "int"},     # more once verified (§10, P4)
    "BonfireWarpParam": {"id": "int"},           # likewise
    "WorldMapPointParam": {"id": "int"},         # likewise (S67: check_fields verifies before a field is added)
    "WorldMapPieceParam": {"id": "int"},         # likewise
    "WorldMapLegacyConvParam": {"id": "int"},    # likewise
}

# The fields that hold ids of other tables' rows (a name number, a message id), each param's apart from its own row id.
# A count of a raw table by one of them lists that column's ids, one row per id it holds, so it stays raw and never
# reaches a share file (DP8; settled S18; build plan §10, P15). A field added to PARAMS is added here too if it holds
# ids; tests/test_jobs_check.py keeps the two in step.
REFERENCES: dict[str, tuple[str, ...]] = {
    "NpcParam": ("nameId",),
    "TalkParam": ("msgId",),
    "WorldMapPlaceNameParam": (),
    "BonfireWarpParam": (),
    "WorldMapPointParam": (),
    "WorldMapPieceParam": (),
    "WorldMapLegacyConvParam": (),
}

# check_fields (S67): a field's type as the server names it, as a number of ours, so a share file holds numbers only.
# 0: the server's answer has no such field; 99: a type not listed here.
TYPE_CODES: dict[str, int] = {"s8": 1, "u8": 2, "s16": 3, "u16": 4, "s32": 5, "u32": 6, "f32": 7, "angle32": 8,
                              "f64": 9, "b32": 10, "fixstr": 11, "fixstrW": 12, "dummy8": 13}
TYPE_OTHER = 99


def type_code(def_type: str | None) -> int:
    """The number check_fields writes for a field's type: 0 when the field is absent."""
    if def_type is None:
        return 0
    return TYPE_CODES.get(def_type, TYPE_OTHER)


def field_type(param: str, field: str) -> str | None:
    """The column type of a listed field, or None when DataPiler does not read it."""
    return PARAMS.get(param, {}).get(field)
