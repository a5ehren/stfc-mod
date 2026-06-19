from __future__ import annotations

from typing import Any


FORMULA_STAGE_REGISTRY: dict[str, dict[str, Any]] = {
    "2": {
        "formula_stage": "standard_base_damage",
        "formula_inputs": ["standard_raw_damage"],
        "confidence": "high",
        "notes": "MOD_ALL_DAMAGE changes normal weapon damage before normal mitigation.",
    },
    "3": {
        "formula_stage": "shot_count",
        "formula_inputs": ["shots_per_attack", "standard_raw_damage"],
        "confidence": "high",
        "notes": "MOD_SHOTS_PER_ATTACK changes the number of normal weapon shots before damage allocation.",
    },
    "6": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["attacker_accuracy", "dodge_component"],
        "confidence": "high",
        "notes": "MOD_ACCURACY changes the attacker's dodge counter in the triangle.",
    },
    "7": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["attacker_armor_piercing", "armor_component"],
        "confidence": "high",
        "notes": "MOD_ARMOR_PIERCING changes the attacker's armor counter in the triangle.",
    },
    "8": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["attacker_shield_piercing", "shield_component"],
        "confidence": "high",
        "notes": "MOD_SHIELD_PIERCING changes the attacker's shield-absorption counter in the triangle.",
    },
    "9": {
        "formula_stage": "critical_resolution",
        "formula_inputs": ["critical_roll", "critical_chance"],
        "confidence": "high",
        "notes": "MOD_CRIT_CHANCE affects whether the shot crits, not the triangle value directly.",
    },
    "10": {
        "formula_stage": "critical_damage",
        "formula_inputs": ["critical_damage_multiplier", "standard_raw_damage"],
        "confidence": "high",
        "notes": "MOD_CRIT_DAMAGE changes critical damage before normal mitigation.",
    },
    "11": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["defender_dodge", "dodge_component"],
        "confidence": "high",
        "notes": "MOD_SHIP_DODGE changes the defender dodge side of the triangle.",
    },
    "12": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["defender_armor_plating", "armor_component"],
        "confidence": "high",
        "notes": "MOD_SHIP_ARMOR changes the defender armor side of the triangle.",
    },
    "13": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["defender_shield_absorption", "shield_component"],
        "confidence": "high",
        "notes": "MOD_SHIELDS appears to affect shield defense and needs component validation.",
    },
    "16": {
        "formula_stage": "post_damage_state",
        "formula_inputs": ["shield_repair", "remaining_shield"],
        "confidence": "medium",
        "notes": "MOD_SHIELD_HP_REPAIR changes state after damage rather than normal mitigation.",
    },
    "18": {
        "formula_stage": "triggered_state",
        "formula_inputs": ["status_effect"],
        "confidence": "medium",
        "notes": "MOD_ADD_STATE applies a state that may gate other buffs.",
    },
    "56": {
        "formula_stage": "officer_stat_damage",
        "formula_inputs": ["officer_attack_stat", "standard_raw_damage"],
        "confidence": "medium",
        "notes": "MOD_OFFICER_STAT_ATTACK likely feeds officer-stat-derived damage before mitigation.",
    },
    "73": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["defender_dodge", "defender_armor_plating", "defender_shield_absorption"],
        "confidence": "high",
        "notes": "MOD_ALL_DEFENSES changes all three defender triangle inputs.",
    },
    "74": {
        "formula_stage": "normal_mitigation_triangle",
        "formula_inputs": ["attacker_accuracy", "attacker_armor_piercing", "attacker_shield_piercing"],
        "confidence": "high",
        "notes": "MOD_ALL_PIERCING changes all three attacker triangle counters.",
    },
    "76": {
        "formula_stage": "shield_allocation",
        "formula_inputs": ["shield_mitigation", "shield_damage", "hull_damage"],
        "confidence": "high",
        "notes": "MOD_SHIELD_MITIGATION changes shield-vs-hull allocation after normal mitigation.",
    },
    "223": {
        "formula_stage": "shield_allocation",
        "formula_inputs": ["shield_bypass", "shield_damage", "hull_damage"],
        "confidence": "medium",
        "notes": "MOD_BYPASS_SHIELDS changes shield-vs-hull allocation after normal mitigation.",
    },
    "707": {
        "formula_stage": "isolytic_damage",
        "formula_inputs": ["isolytic_damage_multiplier", "isolytic_raw_damage"],
        "confidence": "high",
        "notes": "MOD_ISOLYTIC_DAMAGE changes the isolytic damage lane.",
    },
    "808": {
        "formula_stage": "isolytic_mitigation",
        "formula_inputs": ["isolytic_defense", "isolytic_effective_mitigation"],
        "confidence": "high",
        "notes": "MOD_ISOLYTIC_DEFENSE changes mitigation against the isolytic damage lane.",
    },
    "67001": {
        "formula_stage": "apex_barrier",
        "formula_inputs": ["apex_barrier", "apex_mitigation"],
        "confidence": "medium",
        "notes": "Apex barrier is modeled as a separate damage reduction stage after normal and isolytic damage.",
    },
}


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def formula_effect_for_modifier(modifier_code: Any) -> dict[str, Any]:
    code = _id_key(modifier_code)
    effect = FORMULA_STAGE_REGISTRY.get(code)
    if effect is None:
        return {
            "modifierCode": code,
            "formula_stage": "unknown",
            "formula_inputs": [],
            "confidence": "unknown",
            "notes": "No formula-stage mapping has been assigned for this modifier code.",
        }
    return {"modifierCode": code, **effect}
