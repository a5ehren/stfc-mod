from __future__ import annotations

from typing import Any

from .battle_enums import is_chain_shot_battle_type


CHAIN_SHOT_DAMAGE_MODIFIER_CODE = "77001"
CHAIN_SHOT_SECONDARY_MODIFIER_CODE = "77002"


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def resolved_modifier(row: dict[str, Any], role: str, modifier_code: str) -> float:
    ship = row.get(role, {})
    modifiers = ship.get("resolved_modifiers", {}) if isinstance(ship, dict) else {}
    return _number(modifiers.get(modifier_code)) if isinstance(modifiers, dict) else 0.0


def is_chain_shot_attack(row: dict[str, Any]) -> bool:
    if is_chain_shot_battle_type(row.get("battle_type")):
        return True
    weapon = row.get("weapon", {})
    if not isinstance(weapon, dict) or _id_key(weapon.get("id")) != "0":
        return False
    return resolved_modifier(row, "attacker", CHAIN_SHOT_DAMAGE_MODIFIER_CODE) > 0.0


def observed_normal_raw_damage(row: dict[str, Any]) -> float:
    observed = row.get("observed", {})
    normal = observed.get("normal_mitigation", {}) if isinstance(observed, dict) else {}
    if isinstance(normal, dict):
        return _number(normal.get("raw_damage"))
    return 0.0
