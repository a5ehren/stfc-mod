from __future__ import annotations

from typing import Any

from .battle_enums import is_cutting_beam_battle_type
from .mechanics import apply_shield_allocation, round_shots
from .special_attacks import is_chain_shot_attack


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _report_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _observed(row: dict[str, Any]) -> dict[str, Any]:
    observed = row.get("observed", {})
    return observed if isinstance(observed, dict) else {}


def _damage(observed: dict[str, Any]) -> dict[str, Any]:
    damage = observed.get("damage", {})
    return damage if isinstance(damage, dict) else {}


def _remaining(observed: dict[str, Any]) -> dict[str, Any]:
    remaining = observed.get("remaining", {})
    return remaining if isinstance(remaining, dict) else {}


def infer_pre_shot_state(row: dict[str, Any]) -> dict[str, int | float]:
    observed = _observed(row)
    damage = _damage(observed)
    remaining = _remaining(observed)
    shield = _number(damage.get("shield")) + _number(remaining.get("shield"))
    hull = _number(damage.get("hull")) + _number(remaining.get("hull"))
    return {
        "shield": _report_number(shield),
        "hull": _report_number(hull),
    }


def _pre_shot_state(value: dict[str, Any]) -> dict[str, int | float]:
    return {
        "shield": _report_number(_number(value.get("shield"))),
        "hull": _report_number(_number(value.get("hull"))),
    }


def weapon_damage_diagnostics(row: dict[str, Any]) -> dict[str, int | float]:
    weapon = row.get("weapon", {})
    weapon = weapon if isinstance(weapon, dict) else {}
    attacker = row.get("attacker", {})
    attacker_modifiers = attacker.get("resolved_modifiers", {}) if isinstance(attacker, dict) else {}
    shot_count_modifier = _number(attacker_modifiers.get("3")) if isinstance(attacker_modifiers, dict) else 0.0
    base_min = _number(weapon.get("minimum_damage"))
    base_max = _number(weapon.get("maximum_damage"))
    base_midpoint = (base_min + base_max) / 2
    shots = round_shots(weapon.get("shots", 1))
    effective_shots = max(0, shots + int(round(shot_count_modifier)))
    damage_per_shot_midpoint = base_midpoint / shots if shots else 0.0

    return {
        "base_min": _report_number(base_min),
        "base_max": _report_number(base_max),
        "base_midpoint": _report_number(base_midpoint),
        "shots": shots,
        "shot_count_modifier": _report_number(shot_count_modifier),
        "effective_shots": effective_shots,
        "effective_damage_midpoint": _report_number(damage_per_shot_midpoint * effective_shots),
        "damage_per_shot_midpoint": _report_number(damage_per_shot_midpoint),
        "accuracy": _report_number(_number(weapon.get("accuracy"))),
        "armor_piercing": _report_number(_number(weapon.get("penetration"))),
        "shield_piercing": _report_number(_number(weapon.get("modulation"))),
        "crit_modifier": _report_number(_number(weapon.get("crit_modifier"))),
    }


def _shield_mitigation(row: dict[str, Any]) -> float:
    defender = row.get("defender", {})
    static_ship = defender.get("static_ship", {}) if isinstance(defender, dict) else {}
    base_stats = static_ship.get("base_stats", {}) if isinstance(static_ship, dict) else {}
    value = base_stats.get("shield_mitigation") if isinstance(base_stats, dict) else None
    if value is None:
        return 0.8
    return max(0.0, min(1.0, _number(value)))


def _cutting_beam_level(observed: dict[str, Any], row: dict[str, Any], key: str) -> float:
    cutting_beam_key = f"cutting_beam_{key}"
    if observed.get(cutting_beam_key) is not None:
        return _number(observed.get(cutting_beam_key))
    return _number(row.get(key))


def predict_damage_from_stages(
    row: dict[str, Any],
    *,
    standard_raw_damage: Any,
    standard_mitigation: Any,
    isolytic_raw_damage: Any = 0,
    isolytic_mitigation: Any = 0,
    apex_mitigation: Any = 0,
    pre_shot_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed = _observed(row)
    pre_shot = _pre_shot_state(pre_shot_state) if pre_shot_state is not None else infer_pre_shot_state(row)
    shield_before = _number(pre_shot["shield"])
    hull_before = _number(pre_shot["hull"])

    if is_cutting_beam_battle_type(row.get("battle_type")):
        unscaled_damage = observed.get("cutting_beam_unscaled_damage")
        if unscaled_damage is None:
            scaled_damage = int(round(_number(standard_raw_damage)))
        else:
            player_level = _cutting_beam_level(observed, row, "player_level")
            hostile_level = _cutting_beam_level(observed, row, "hostile_level")
            level_delta = max(0.0, hostile_level - player_level)
            scaled_damage = int(round(_number(unscaled_damage) * max(0.0, 1.0 - 0.1 * level_delta)))
        return {
            "mode": "cutting_beam_direct_hull",
            "pre_shot": pre_shot,
            "standard_unmitigated": 0,
            "isolytic_unmitigated": 0,
            "after_apex": scaled_damage,
            "damage": {
                "shield": 0,
                "hull": scaled_damage,
            },
            "remaining": {
                "shield": _report_number(shield_before),
                "hull": _report_number(max(0.0, hull_before - scaled_damage)),
            },
        }

    if is_chain_shot_attack(row):
        direct_damage = int(round(max(0.0, _number(standard_raw_damage))))
        return {
            "mode": "chain_shot_direct_hull",
            "pre_shot": pre_shot,
            "standard_unmitigated": direct_damage,
            "isolytic_unmitigated": 0,
            "after_apex": direct_damage,
            "damage": {
                "shield": 0,
                "hull": direct_damage,
            },
            "remaining": {
                "shield": _report_number(shield_before),
                "hull": _report_number(max(0.0, hull_before - direct_damage)),
            },
        }

    standard_unmitigated = int(round(_number(standard_raw_damage) * (1.0 - _number(standard_mitigation))))
    isolytic_unmitigated = int(round(_number(isolytic_raw_damage) * (1.0 - _number(isolytic_mitigation))))
    after_apex = int(round((standard_unmitigated + isolytic_unmitigated) * (1.0 - _number(apex_mitigation))))
    shield_mitigation = _shield_mitigation(row) if shield_before > 0 else 0.0
    allocation = apply_shield_allocation(
        total_unmitigated_damage=after_apex,
        shield_mitigation=shield_mitigation,
        shield_before=shield_before,
    )
    remaining_hull = max(0.0, hull_before - allocation["hull"])

    return {
        "mode": "standard_iso_apex_shield",
        "pre_shot": pre_shot,
        "standard_unmitigated": standard_unmitigated,
        "isolytic_unmitigated": isolytic_unmitigated,
        "after_apex": after_apex,
        "damage": {
            "shield": allocation["shield"],
            "hull": allocation["hull"],
        },
        "remaining": {
            "shield": allocation["remaining_shield"],
            "hull": _report_number(remaining_hull),
        },
    }


def observed_damage_stages(row: dict[str, Any]) -> dict[str, int | float]:
    observed = _observed(row)
    damage = _damage(observed)
    taken_hull = _number(damage.get("hull"))
    taken_shield = _number(damage.get("shield"))
    std_mitigated = _number(observed.get("mitigated_damage"))
    iso_unmitigated = _number(observed.get("isolytic_damage"))
    iso_mitigated = _number(observed.get("mitigated_isolytic_damage"))
    apex_mitigated = _number(observed.get("mitigated_apex_barrier"))

    damage_total = taken_hull + taken_shield + std_mitigated + iso_mitigated + apex_mitigated
    iso_raw = iso_unmitigated + iso_mitigated
    std_raw = damage_total - iso_raw
    damage_before_apex = taken_hull + taken_shield + apex_mitigated

    return {
        "taken_hull": _report_number(taken_hull),
        "taken_shield": _report_number(taken_shield),
        "std_mitigated": _report_number(std_mitigated),
        "iso_unmitigated": _report_number(iso_unmitigated),
        "iso_mitigated": _report_number(iso_mitigated),
        "apex_mitigated": _report_number(apex_mitigated),
        "std_raw": _report_number(std_raw),
        "iso_raw": _report_number(iso_raw),
        "damage_total_before_all_mitigation": _report_number(damage_total),
        "damage_before_apex": _report_number(damage_before_apex),
        "std_mitigation": std_mitigated / std_raw if std_raw else 0,
        "iso_mitigation": iso_mitigated / iso_raw if iso_raw else 0,
        "apex_mitigation": apex_mitigated / damage_before_apex if damage_before_apex else 0,
        "all_mitigation": 1 - (taken_hull + taken_shield) / damage_total if damage_total else 0,
    }
