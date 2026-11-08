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
}


def field_type(param: str, field: str) -> str | None:
    """The column type of a listed field, or None when DataPiler does not read it."""
    return PARAMS.get(param, {}).get(field)
