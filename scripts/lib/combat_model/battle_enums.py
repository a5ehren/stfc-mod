from __future__ import annotations

from typing import Any


# Digit.PrimeServer.Models.BattleType in dump/1.000.49021/dump.cs.
BATTLE_TYPE_NAMES = {
    0: "FLEET",
    1: "BASE",
    2: "PASSIVE_MARAUDER",
    3: "NPC_INSTANTIATED",
    4: "DOCKING_POINT",
    5: "ACTIVE_MARAUDER_MARAUDER_INITIATOR",
    6: "ACTIVE_MARAUDER_PLAYER_INITIATOR",
    7: "ARMADA_BASE",
    8: "ARMADA_MARAUDER",
    9: "PVE_DOCKING_POINT",
    10: "ARMADA_ASB",
    11: "ARMADA_MTA",
    12: "HAZARD",
    13: "PVE_CUTTING_BEAM",
    14: "PVP_CUTTING_BEAM",
    15: "PVE_CHAIN_SHOT",
    16: "PVP_CHAIN_SHOT",
}
CUTTING_BEAM_BATTLE_TYPES = {13, 14}
CHAIN_SHOT_BATTLE_TYPES = {15, 16}

# Digit.PrimeServer.Models.FleetDataType in dump/1.000.49021/dump.cs.
FLEET_DATA_TYPE_NAMES = {
    0: "DEPLOYED_FLEET",
    1: "STARBASE",
    2: "ARMADA",
}


def enum_name(mapping: dict[int, str], value: Any) -> str:
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    return mapping.get(numeric_value, "UNKNOWN")


def battle_type_name(value: Any) -> str:
    return enum_name(BATTLE_TYPE_NAMES, value)


def battle_type_label(value: Any) -> str:
    return f"{value}:{battle_type_name(value)}"


def is_cutting_beam_battle_type(value: Any) -> bool:
    try:
        return int(value) in CUTTING_BEAM_BATTLE_TYPES
    except (TypeError, ValueError):
        return False


def is_chain_shot_battle_type(value: Any) -> bool:
    try:
        return int(value) in CHAIN_SHOT_BATTLE_TYPES
    except (TypeError, ValueError):
        return False


def fleet_data_type_name(value: Any) -> str:
    return enum_name(FLEET_DATA_TYPE_NAMES, value)
