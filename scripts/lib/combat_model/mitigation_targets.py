from __future__ import annotations

from typing import Any


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _report_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _modifier_value(stats: dict[str, Any] | None, modifier_code: str) -> float:
    return _number((stats or {}).get(modifier_code)) if isinstance(stats, dict) else 0.0


def _isolytic_bonus_from_final_fleet_value(value: float) -> float:
    if value <= 0.0:
        return 0.0
    return value - 1.0 if value > 1.0 else value


def _activation_707_value(activation: Any) -> float:
    if not isinstance(activation, dict) or str(activation.get("modifierCode")) != "707":
        return 0.0
    value = _number(activation.get("value"))
    if activation.get("op") in {"BUFFOPERATION_SUB", "BUFFOPERATION_MULTIPLYSUB"}:
        return -value
    return value


def _isolytic_cascade_bonus_from_observed(observed: dict[str, Any]) -> float:
    total = 0.0
    for key in ("forbidden_tech_activations", "officer_activations"):
        activations = observed.get(key, [])
        if not isinstance(activations, list):
            continue
        total += sum(_activation_707_value(activation) for activation in activations)
    return total


def _isolytic_multiplier_inputs(
    observed: dict[str, Any],
    *,
    attacker_stats: dict[str, Any] | None,
    attacker_stat_source: str,
    captured_attacker_stats: dict[str, Any] | None,
) -> dict[str, float | str]:
    primary_707 = _modifier_value(attacker_stats, "707")
    captured_707 = _modifier_value(captured_attacker_stats, "707")
    cascade_bonus = _isolytic_cascade_bonus_from_observed(observed)

    if attacker_stat_source in {"captured_fleet_stats", "captured_ship_stats"} and primary_707 > 0.0:
        isolytic_bonus = _isolytic_bonus_from_final_fleet_value(primary_707)
        source = "captured_final_fleet_707"
    elif captured_707 > 0.0 and attacker_stat_source == "resolved_buff_audit":
        isolytic_bonus = _isolytic_bonus_from_final_fleet_value(captured_707)
        if cascade_bonus == 0.0 and 0.0 < primary_707 < 1.0:
            cascade_bonus = primary_707
        source = "captured_final_fleet_707_plus_resolved_cascade"
    elif primary_707 > 0.0 and attacker_stat_source == "resolved_buff_audit_static_ship_bonus":
        isolytic_bonus = primary_707
        source = "resolved_static_707_bonus"
    elif primary_707 > 0.0:
        isolytic_bonus = _isolytic_bonus_from_final_fleet_value(primary_707)
        source = "resolved_or_captured_707"
    else:
        return {
            "isolytic_bonus": 0.0,
            "cascade_bonus": 0.0,
            "damage_multiplier": 0.0,
            "source": "missing_707",
        }

    damage_multiplier = isolytic_bonus + (1.0 + isolytic_bonus) * cascade_bonus
    return {
        "isolytic_bonus": isolytic_bonus,
        "cascade_bonus": cascade_bonus,
        "damage_multiplier": damage_multiplier,
        "source": source,
    }


def normal_mitigation_from_observed(
    observed: dict[str, Any],
    *,
    include_apex_barrier: bool = True,
) -> dict[str, int | float]:
    damage = observed.get("damage", {})
    shield_damage = _number(damage.get("shield") if isinstance(damage, dict) else 0.0)
    hull_damage = _number(damage.get("hull") if isinstance(damage, dict) else 0.0)
    mitigated_damage = _number(observed.get("mitigated_damage"))
    isolytic_damage = _number(observed.get("isolytic_damage"))
    mitigated_isolytic_damage = _number(observed.get("mitigated_isolytic_damage"))
    mitigated_apex_barrier = _number(observed.get("mitigated_apex_barrier"))

    post_apex_damage = shield_damage + hull_damage
    pre_apex_damage = post_apex_damage + (mitigated_apex_barrier if include_apex_barrier else 0.0)
    post_apex_observed_damage = max(0.0, post_apex_damage - isolytic_damage)
    observed_damage = max(0.0, pre_apex_damage - isolytic_damage)
    raw_damage_without_apex = post_apex_observed_damage + mitigated_damage
    raw_damage = observed_damage + mitigated_damage
    result = {
        "observed_damage": _report_number(observed_damage),
        "raw_damage": _report_number(raw_damage),
        "mitigated_damage": _report_number(mitigated_damage),
        "effective_mitigation": mitigated_damage / raw_damage if raw_damage else 0.0,
        "excluded_isolytic_damage": _report_number(isolytic_damage),
        "excluded_mitigated_isolytic_damage": _report_number(mitigated_isolytic_damage),
        "raw_damage_without_apex_barrier": _report_number(raw_damage_without_apex),
        "included_mitigated_apex_barrier": _report_number(mitigated_apex_barrier),
        "post_apex_observed_damage": _report_number(post_apex_observed_damage),
        "pre_apex_observed_damage": _report_number(observed_damage),
        "stage_order": "normal_then_isolytic_then_apex",
    }
    if not include_apex_barrier:
        result["included_mitigated_apex_barrier"] = 0
    return result


def isolytic_damage_model_from_observed(
    observed: dict[str, Any],
    *,
    attacker_stats: dict[str, Any] | None = None,
    attacker_stat_source: str = "captured_ship_stats",
    captured_attacker_stats: dict[str, Any] | None = None,
) -> dict[str, int | float | str]:
    normal_mitigation = normal_mitigation_from_observed(observed)
    base_damage = _number(normal_mitigation.get("raw_damage"))
    observed_damage = _number(observed.get("isolytic_damage"))
    mitigated_damage = _number(observed.get("mitigated_isolytic_damage"))
    raw_damage = observed_damage + mitigated_damage
    multiplier_inputs = _isolytic_multiplier_inputs(
        observed,
        attacker_stats=attacker_stats,
        attacker_stat_source=attacker_stat_source,
        captured_attacker_stats=captured_attacker_stats,
    )
    if _number(multiplier_inputs["damage_multiplier"]) > 0:
        damage_multiplier = _number(multiplier_inputs["damage_multiplier"])
        source = attacker_stat_source
    else:
        damage_multiplier = raw_damage / base_damage if base_damage else 0.0
        source = "derived_from_battle_log"
    inferred_base_damage = raw_damage / damage_multiplier if damage_multiplier else 0.0
    result = {
        "base_damage": _report_number(base_damage),
        "raw_damage": _report_number(raw_damage),
        "observed_damage": _report_number(observed_damage),
        "mitigated_damage": _report_number(mitigated_damage),
        "damage_multiplier": damage_multiplier,
        "damage_multiplier_percent": damage_multiplier * 100.0,
        "effective_mitigation": mitigated_damage / raw_damage if raw_damage else 0.0,
        "inferred_base_damage": _report_number(inferred_base_damage),
        "base_damage_gap": _report_number(inferred_base_damage - base_damage),
        "damage_modifier_code": "707",
        "defense_modifier_code": "808",
        "source": source,
    }
    if source != "derived_from_battle_log":
        result["isolytic_bonus"] = _report_number(_number(multiplier_inputs["isolytic_bonus"]))
        result["cascade_bonus"] = _report_number(_number(multiplier_inputs["cascade_bonus"]))
        result["multiplier_source"] = str(multiplier_inputs["source"])
    return result


def normal_effective_mitigation(row: dict[str, Any]) -> float:
    observed = row.get("observed", {})
    if not isinstance(observed, dict):
        return 0.0
    return _number(normal_mitigation_from_observed(observed).get("effective_mitigation"))
