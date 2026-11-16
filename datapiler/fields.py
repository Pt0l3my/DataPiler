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
    # S97 (0.2.40): weapons and armour by their row ids alone, which the weapon and armour names are numbered by.
    "EquipParamWeapon": {"id": "int"},
    "EquipParamProtector": {"id": "int"},
    "WorldMapPlaceNameParam": {
        "id": "int", "disableParam_NT": "int", "worldMapPieceId": "int", "textId": "int", "areaNo": "int",
        "gridXNo": "int", "gridZNo": "int", "posX": "number", "posY": "number", "posZ": "number"
    },
    "BonfireWarpParam": {
        "id": "int", "disableParam_NT": "int", "eventflagId": "int", "bonfireEntityId": "int",
        "bonfireSubCategorySortId": "int", "bonfireSubCategoryId": "int", "clearedEventFlagId": "int",
        "iconId": "int", "forbiddenIconId": "int", "dispMinZoomStep": "int", "selectMinZoomStep": "int",
        "dispMask00": "int", "dispMask01": "int", "dispMask02": "int", "areaNo": "int", "gridXNo": "int",
        "gridZNo": "int", "posX": "number", "posY": "number", "posZ": "number", "textId1": "int",
        "textEnableFlagId1": "int", "textDisableFlagId1": "int", "altIconId": "int"
    },
    "WorldMapPointParam": {
        "id": "int", "disableParam_NT": "int", "eventFlagId": "int", "distViewEventFlagId": "int",
        "clearedEventFlagId": "int", "iconId": "int", "altIconId": "int", "distViewIconId": "int",
        "isAreaIcon": "int", "bgmPlaceType": "int", "angle": "number", "areaNo": "int", "gridXNo": "int",
        "gridZNo": "int", "posX": "number", "posY": "number", "posZ": "number", "isOverrideDistViewMarkPos": "int",
        "areaNo_forDistViewMark": "int", "gridXNo_forDistViewMark": "int", "gridZNo_forDistViewMark": "int",
        "posX_forDistViewMark": "number", "posY_forDistViewMark": "number", "posZ_forDistViewMark": "number",
        "distViewId": "int", "dispMinZoomStep": "int", "selectMinZoomStep": "int", "entryFEType": "int",
        "dispMask00": "int", "dispMask01": "int", "dispMask02": "int", "textId1": "int", "textType1": "int"
    },
    "WorldMapPieceParam": {
        "id": "int", "disableParam_NT": "int", "openEventFlagId": "int", "openTravelAreaLeft": "number",
        "openTravelAreaRight": "number", "openTravelAreaTop": "number", "openTravelAreaBottom": "number",
        "acquisitionEventFlagId": "int", "acquisitionEventScale": "number", "acquisitionEventCenterX": "number",
        "acquisitionEventCenterY": "number", "acquisitionEventResScale": "number",
        "acquisitionEventResOffsetX": "number", "acquisitionEventResOffsetY": "number"
    },
    "WorldMapLegacyConvParam": {
        "id": "int", "disableParam_NT": "int", "srcAreaNo": "int", "srcGridXNo": "int", "srcGridZNo": "int",
        "srcPosX": "number", "srcPosY": "number", "srcPosZ": "number", "dstAreaNo": "int", "dstGridXNo": "int",
        "dstGridZNo": "int", "dstPosX": "number", "dstPosY": "number", "dstPosZ": "number", "isBasePoint": "int"
    },
    "MapNameTexParam": {"id": "int"},                   # fields read after a same-job check (S72, DP24)
    "MapNameTexParam_m61": {"id": "int"},               # fields read after a same-job check (S72, DP24)
    "MapPieceTexParam": {"id": "int"},                  # fields read after a same-job check (S72, DP24)
    "MapPieceTexParam_m61": {"id": "int"},              # fields read after a same-job check (S72, DP24)
    "MapGridCreateHeightLimitInfo": {"id": "int"},      # fields read after a same-job check (S72, DP24)
    "WeatherLotTexParam": {"id": "int"},          # S89: fields read after a same-job check (S72, DP24)
    "WeatherLotTexParam_m61": {"id": "int"},      # S89: fields read after a same-job check (S72, DP24)
    "MimicryEstablishmentTexParam": {"id": "int"}, # S89: fields read after a same-job check (S72, DP24)
    "MimicryEstablishmentTexParam_m61": {"id": "int"}, # S89: fields read after a same-job check (S72, DP24)
}

# The fields that hold ids of other tables' rows (a name number, a message id), each param's apart from its own row id.
# A count of a raw table by one of them lists that column's ids, one row per id it holds, so it stays raw and never
# reaches a share file (DP8; settled S18; build plan §10, P15). A field added to PARAMS is added here too if it holds
# ids; tests/test_jobs_check.py keeps the two in step.
REFERENCES: dict[str, tuple[str, ...]] = {
    "NpcParam": ("nameId",),
    "TalkParam": ("msgId",),
    "EquipParamWeapon": (),
    "EquipParamProtector": (),
    "WorldMapPlaceNameParam": ("worldMapPieceId", "textId"),
    "BonfireWarpParam": ("eventflagId", "bonfireEntityId", "bonfireSubCategoryId", "clearedEventFlagId", "iconId", "forbiddenIconId", "textId1", "textEnableFlagId1", "textDisableFlagId1", "altIconId"),
    "WorldMapPointParam": ("eventFlagId", "distViewEventFlagId", "clearedEventFlagId", "iconId", "altIconId", "distViewIconId", "distViewId", "textId1"),
    "WorldMapPieceParam": ("openEventFlagId", "acquisitionEventFlagId"),
    "WorldMapLegacyConvParam": (),
    "MapNameTexParam": (),
    "MapNameTexParam_m61": (),
    "MapPieceTexParam": (),
    "MapPieceTexParam_m61": (),
    "MapGridCreateHeightLimitInfo": (),
    "WeatherLotTexParam": (),
    "WeatherLotTexParam_m61": (),
    "MimicryEstablishmentTexParam": (),
    "MimicryEstablishmentTexParam_m61": (),
}

# The game's map tables (S69, DP21): their fields above were verified on the owner's PC by check_fields (en-0015,
# 2026-11-14: 91 of 91, each of the type Smithbox's definition gives). By DP21 a job may share their rows whole, for
# research only, when its write_share carries the label `map_coords`; a share file holding them is never committed.
# S89 (0.2.36): the map-information images' other two colour keys, weather and mimicry, with the expansion's.
MAP_PARAMS = ("BonfireWarpParam", "WorldMapPointParam", "WorldMapPlaceNameParam", "WorldMapPieceParam",
              "WorldMapLegacyConvParam", "MapNameTexParam", "MapNameTexParam_m61", "MapPieceTexParam",
              "MapPieceTexParam_m61", "MapGridCreateHeightLimitInfo", "WeatherLotTexParam", "WeatherLotTexParam_m61",
              "MimicryEstablishmentTexParam", "MimicryEstablishmentTexParam_m61")

# S72 (DP24): the column type a field read after a check_fields of the same job gets, from the type the server named.
# A text type is never read.
_INT_DEF = frozenset(("s8", "u8", "s16", "u16", "s32", "u32"))
_NUM_DEF = frozenset(("f32", "angle32", "f64"))


def checked_type(def_type: str | None) -> str | None:
    """"int", "number" or "bool" for a field check_fields found, by the server's type; None for absent or text."""
    if def_type in _INT_DEF:
        return "int"
    if def_type in _NUM_DEF:
        return "number"
    if def_type == "b32":
        return "bool"
    return None

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
