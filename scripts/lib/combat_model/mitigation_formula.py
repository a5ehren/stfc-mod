from __future__ import annotations

import math
from typing import Any

from .mechanics import (
    HULL_ARMADA,
    HULL_BATTLESHIP,
    HULL_DESTROYER,
    HULL_EXPLORER,
    HULL_INTERCEPTOR,
    HULL_SURVEY,
    apex_barrier_damage_reduction,
    mitigation_component as toolbox_mitigation_component,
    weights_for as toolbox_weights_for,
)


BASIC_LIVE_MITIGATION_FEATURES = (
    "live_dodge_ratio",
    "live_plating_ratio",
    "live_absorption_ratio",
)

BASIC_LIVE_MITIGATION_WEIGHTS = {
    "live_dodge_ratio": 1.0 / 3.0,
    "live_plating_ratio": 1.0 / 3.0,
    "live_absorption_ratio": 1.0 / 3.0,
}

COMBAT_TRIANGLE_WEIGHT_HULL_TYPES = (
    HULL_ARMADA,
    HULL_BATTLESHIP,
    HULL_DESTROYER,
    HULL_EXPLORER,
    HULL_INTERCEPTOR,
    HULL_SURVEY,
)

COMBAT_TRIANGLE_WEIGHTS = {hull_type: toolbox_weights_for(hull_type) for hull_type in COMBAT_TRIANGLE_WEIGHT_HULL_TYPES}

COMBAT_TRIANGLE_STAT_SOURCES = {
    "resolved_player_live": "captured live stats, with resolved player stat explanations overlaid when available",
    "captured_live": "captured live ship_stats only",
    "static_base": "static hull/component base stats only",
    "static_player_max_buffs": (
        "static hull/component base stats, hostile weapon stats, player attacker triangle modifiers, and player "
        "defender triangle modifiers plus hull core-stat max bonuses and resolved officer-stat rating buffs applied"
    ),
}

COMBAT_TRIANGLE_COMPOSITIONS = (
    "weighted_product",
    "weighted_sum",
    "weighted_power_product",
    "active_layer_weighted_sum",
    "active_layer_weighted_product",
    "active_layer_weighted_product_unscaled",
)
COMBAT_TRIANGLE_STAT_ROLE_ORIENTATIONS = (
    "normal",
    "swapped_stats_defender_weights",
    "swapped_stats_attacker_weights",
)

TRIANGLE_MODIFIER_STAT_TARGETS = {
    "6": ("attacker", ("6",)),
    "7": ("attacker", ("7",)),
    "8": ("attacker", ("8",)),
    "11": ("defender", ("11",)),
    "12": ("defender", ("-3",)),
    "13": ("defender", ("-2",)),
    "73": ("defender", ("11", "-3", "-2")),
    "74": ("attacker", ("6", "7", "8")),
}
STATIC_PLAYER_MAX_DEFENDER_MODIFIER_CODES = {"11", "12", "13", "73"}
PLAYER_DEFENDER_CLIENT_LOOKUP_HULL_IDS = {
    "2016654425",  # Franklin 2.0
    "3803001941",  # Vidar 2
}
PLAYER_HULL_CORE_TRIANGLE_TARGETS = {
    "OFFICERCORESTATTYPE_ATTACK": ("attacker", ("6", "7", "8")),
    "ATTACK": ("attacker", ("6", "7", "8")),
    "OFFICERCORESTATTYPE_DEFENSE": ("defender", ("11", "-3", "-2")),
    "DEFENSE": ("defender", ("11", "-3", "-2")),
}

SELF_TARGET_CODES = {"1"}
OPPONENT_TARGET_CODES = {"6"}
OFFICER_STAT_MODIFIER_CODES = {
    "OFFICERCORESTATTYPE_ATTACK": "56",
    "OFFICERCORESTATTYPE_DEFENSE": "57",
    "OFFICERCORESTATTYPE_HEALTH": "58",
}
CORE_STAT_THRESHOLD_KEYS = {
    "OFFICERCORESTATTYPE_ATTACK": "1",
    "ATTACK": "1",
    "OFFICERCORESTATTYPE_DEFENSE": "2",
    "DEFENSE": "2",
    "OFFICERCORESTATTYPE_HEALTH": "3",
    "HEALTH": "3",
}
OFFICER_STAT_ALL_MODIFIER_CODE = "59"
OFFICER_STAT_SCALE_MODES = ("none", "percent", "raw")
APEX_BARRIER_MODIFIER_CODE = "67001"
DEFAULT_COMBAT_TRIANGLE_CURVE_BASE = 4.0
STARBASE_OFFICER_STAT_ALL_DEFENSE_TARGET_CODE = "5"
STARBASE_OFFICER_STAT_ALL_DEFENSE_TRIGGER_CODE = "24"
STARBASE_OFFICER_STAT_ALL_DEFENSE_RATING_BUFF_IDS = {"660954013"}
STATIC_PLAYER_MAX_OFFICER_STAT_ALL_RATING_MULTIPLIER = 5.0


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _id_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _ratio(defender_value: Any, attacker_value: Any) -> float:
    defender = _number(defender_value)
    attacker = _number(attacker_value)
    denominator = defender + attacker
    if denominator == 0:
        return 0.0
    return defender / denominator


def _shield_active_before_shot(row: dict[str, Any]) -> bool:
    observed = row.get("observed", {})
    damage = observed.get("damage", {}) if isinstance(observed, dict) else {}
    remaining = observed.get("remaining", {}) if isinstance(observed, dict) else {}
    shield_damage = _number(damage.get("shield") if isinstance(damage, dict) else 0.0)
    remaining_shield = _number(remaining.get("shield") if isinstance(remaining, dict) else 0.0)
    return shield_damage + remaining_shield > 0


def _ship_stats(row: dict[str, Any], role: str, *, prefer_resolved_player_stats: bool) -> dict[str, Any]:
    ship = row.get(role, {})
    if not isinstance(ship, dict):
        return {}
    captured = ship.get("captured_stats")
    stats = dict(captured) if isinstance(captured, dict) else {}
    if prefer_resolved_player_stats and row.get(f"{role}_side") == "player":
        resolved = ship.get("resolved_stats")
        if isinstance(resolved, dict) and resolved:
            stats.update(resolved)
    return stats


def _static_base_stats(row: dict[str, Any], role: str) -> dict[str, Any]:
    ship = row.get(role, {})
    if not isinstance(ship, dict):
        return {}
    static_ship = ship.get("static_ship", {})
    if not isinstance(static_ship, dict):
        return {}
    base_stats = static_ship.get("base_stats", {})
    if not isinstance(base_stats, dict):
        return {}
    if role == "attacker":
        return {
            "6": base_stats.get("weapon_accuracy_max"),
            "7": base_stats.get("weapon_penetration_max"),
            "8": base_stats.get("weapon_modulation_max"),
        }
    return {
        "11": base_stats.get("dodge"),
        "-3": base_stats.get("armor_plating"),
        "-2": base_stats.get("shield_absorption"),
    }


def _player_defender_lookup_base_stats(row: dict[str, Any], role: str, stats: dict[str, Any]) -> dict[str, Any]:
    if role != "defender" or row.get(f"{role}_side") != "player":
        return stats
    ship = row.get(role, {})
    if not isinstance(ship, dict):
        return stats
    static_ship = ship.get("static_ship", {})
    if not isinstance(static_ship, dict):
        return stats
    hull = static_ship.get("hull", {})
    if not isinstance(hull, dict) or _id_key(hull.get("id")) not in PLAYER_DEFENDER_CLIENT_LOOKUP_HULL_IDS:
        return stats
    lookup_sources = static_ship.get("client_ship_stat_lookup_sources", {})
    if not isinstance(lookup_sources, dict):
        return stats

    adjusted = dict(stats)
    for stat_key, lookup_key in (
        ("11", "dodge"),
        ("-3", "armor_plating"),
        ("-2", "shield_absorption"),
    ):
        source = lookup_sources.get(lookup_key)
        if isinstance(source, dict) and source.get("status") == "found" and source.get("value") is not None:
            adjusted[stat_key] = source["value"]
    return adjusted


def _triangle_modifier_percents(row: dict[str, Any], role: str, stats: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    percents = {key: 0.0 for key in stats}
    adjustments: list[dict[str, Any]] = []
    if row.get(f"{role}_side") != "player":
        return percents, adjustments

    ship = row.get(role, {})
    if not isinstance(ship, dict):
        return percents, adjustments

    resolved_modifiers = ship.get("resolved_modifiers", {})
    if isinstance(resolved_modifiers, dict):
        for modifier_code, value in resolved_modifiers.items():
            target = TRIANGLE_MODIFIER_STAT_TARGETS.get(_id_key(modifier_code))
            if target is None:
                continue
            target_role, stat_keys = target
            if target_role != role:
                continue
            if role == "defender" and _id_key(modifier_code) not in STATIC_PLAYER_MAX_DEFENDER_MODIFIER_CODES:
                continue
            percent = _number(value)
            for stat_key in stat_keys:
                if stat_key not in percents:
                    continue
                percents[stat_key] += percent
                adjustments.append(
                    {
                        "source": "resolved_player_modifier",
                        "modifierCode": _id_key(modifier_code),
                        "role": role,
                        "stat": stat_key,
                        "percent": percent,
                    }
                )

    static_ship = ship.get("static_ship", {})
    hull = static_ship.get("hull", {}) if isinstance(static_ship, dict) else {}
    core_modifiers = hull.get("core_stat_modifiers", []) if isinstance(hull, dict) else []
    if isinstance(core_modifiers, list):
        for modifier in core_modifiers:
            if not isinstance(modifier, dict):
                continue
            target = PLAYER_HULL_CORE_TRIANGLE_TARGETS.get(str(modifier.get("type")))
            if target is None:
                continue
            target_role, stat_keys = target
            if target_role != role:
                continue
            percent, core_detail = _player_hull_core_stat_percent(ship, hull, modifier)
            if percent == 0.0:
                continue
            for stat_key in stat_keys:
                if stat_key not in percents:
                    continue
                percents[stat_key] += percent
                adjustments.append(
                    {
                        "source": "player_hull_core_stat_threshold_modifier",
                        "core_stat_type": str(modifier.get("type")),
                        "role": role,
                        "stat": stat_key,
                        "percent": percent,
                        "hull_bonus": modifier.get("bonus"),
                        "hull_threshold": modifier.get("threshold"),
                        **core_detail,
                    }
                )

    return percents, adjustments


def _core_stat_threshold_bonus(thresholds: dict[str, Any], core_stat_type: Any, total: float) -> dict[str, Any] | None:
    threshold_key = CORE_STAT_THRESHOLD_KEYS.get(str(core_stat_type))
    if threshold_key is None:
        return None
    threshold_spec = thresholds.get(threshold_key)
    entries = threshold_spec.get("thresholds", []) if isinstance(threshold_spec, dict) else []
    if not isinstance(entries, list):
        return None

    reached = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stat_total = entry.get("statTotal")
        if stat_total is None:
            continue
        if _number(stat_total) <= total:
            reached = entry
        else:
            break
    if reached is None or reached.get("statBonus") is None:
        return None
    return {
        "statTotal": reached.get("statTotal"),
        "statBonus": _number(reached.get("statBonus")),
    }


def _player_hull_core_stat_percent(ship: dict[str, Any], hull: dict[str, Any], modifier: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    core_stat_type = str(modifier.get("type"))
    stat_code = OFFICER_STAT_MODIFIER_CODES.get(core_stat_type)
    if stat_code is None:
        return 0.0, {"status": "unsupported_core_stat_type"}

    fleet_stats = ship.get("captured_fleet_stats", {})
    if not isinstance(fleet_stats, dict):
        return 0.0, {"status": "missing_captured_fleet_stats"}

    direct_total = _number(fleet_stats.get(stat_code))
    all_total = _number(fleet_stats.get(OFFICER_STAT_ALL_MODIFIER_CODE))
    core_total = direct_total + all_total
    threshold = _core_stat_threshold_bonus(hull.get("officer_core_thresholds", {}), core_stat_type, core_total)
    if threshold is None:
        return 0.0, {
            "status": "missing_reached_core_stat_threshold",
            "core_stat_total": core_total,
            "direct_core_stat": direct_total,
            "all_core_stat": all_total,
        }

    percent = _number(threshold["statBonus"])
    return percent, {
        "status": "applied",
        "core_stat_total": core_total,
        "direct_core_stat": direct_total,
        "all_core_stat": all_total,
        "threshold_stat_total": threshold["statTotal"],
        "threshold_stat_bonus": threshold["statBonus"],
    }


def _starbase_officer_stat_all_rating_buffs(ship: dict[str, Any]) -> list[dict[str, Any]]:
    modifier_rows = ship.get("resolved_modifier_rows", [])
    if not isinstance(modifier_rows, list):
        modifier_rows = []
    matches = []
    for row in modifier_rows:
        if not isinstance(row, dict):
            continue
        if _id_key(row.get("buff_id")) not in STARBASE_OFFICER_STAT_ALL_DEFENSE_RATING_BUFF_IDS:
            continue
        if _id_key(row.get("modifierCode")) != OFFICER_STAT_ALL_MODIFIER_CODE:
            continue
        if row.get("source_type") != "starbase":
            continue
        if _id_key(row.get("buffOperation")) != "BUFFOPERATION_MULTIPLYADD":
            continue
        if _id_key(row.get("targetCode")) != STARBASE_OFFICER_STAT_ALL_DEFENSE_TARGET_CODE:
            continue
        if _id_key(row.get("triggerCode")) != STARBASE_OFFICER_STAT_ALL_DEFENSE_TRIGGER_CODE:
            continue
        value = _number(row.get("selected_ranked_value"))
        if value == 0.0:
            continue
        matches.append({**row, "selected_ranked_value": value})
    if matches:
        return matches

    fleet_stats = ship.get("captured_fleet_stats", {})
    if not isinstance(fleet_stats, dict) or _number(fleet_stats.get(OFFICER_STAT_ALL_MODIFIER_CODE)) == 0.0:
        return []
    return [
        {
            "buff_id": "660954013",
            "modifierCode": OFFICER_STAT_ALL_MODIFIER_CODE,
            "buffOperation": "BUFFOPERATION_MULTIPLYADD",
            "targetCode": STARBASE_OFFICER_STAT_ALL_DEFENSE_TARGET_CODE,
            "triggerCode": STARBASE_OFFICER_STAT_ALL_DEFENSE_TRIGGER_CODE,
            "selected_ranked_value": STATIC_PLAYER_MAX_OFFICER_STAT_ALL_RATING_MULTIPLIER,
            "source_type": "captured_fleet_stats",
            "source_key": "captured_fleet_stats/59",
            "fallback": "missing_explicit_starbase_buff_row",
        }
    ]


def _apply_player_defender_officer_stat_rating_buffs(
    row: dict[str, Any],
    stats: dict[str, Any],
    adjustments: list[dict[str, Any]],
) -> dict[str, Any]:
    if row.get("defender_side") != "player":
        return stats
    ship = row.get("defender", {})
    if not isinstance(ship, dict):
        return stats
    ratings = ship.get("captured_fleet_ratings", {})
    defense_rating = _number(ratings.get("defense_rating") if isinstance(ratings, dict) else 0.0)
    if defense_rating == 0.0:
        return stats
    buffs = _starbase_officer_stat_all_rating_buffs(ship)
    if not buffs:
        return stats

    adjusted = dict(stats)
    for buff in buffs:
        multiplier = _number(buff.get("selected_ranked_value"))
        additive = defense_rating * multiplier
        for stat_key in ("-3", "-2"):
            if stat_key not in adjusted:
                continue
            before = _number(adjusted.get(stat_key))
            adjusted[stat_key] = before + additive
            adjustments.append(
                {
                    "source": "player_starbase_officer_stat_all_defense_rating_modifier",
                    "modifierCode": OFFICER_STAT_ALL_MODIFIER_CODE,
                    "role": "defender",
                    "stat": stat_key,
                    "before": before,
                    "after": adjusted[stat_key],
                    "defense_rating": defense_rating,
                    "multiplier": multiplier,
                    "additive": additive,
                    "buff_id": buff.get("buff_id"),
                    "source_type": buff.get("source_type"),
                    "source_key": buff.get("source_key"),
                    "targetCode": buff.get("targetCode"),
                    "triggerCode": buff.get("triggerCode"),
                }
            )
            if buff.get("fallback"):
                adjustments[-1]["source"] = "captured_fleet_stats_officer_stat_all_fallback"
                adjustments[-1]["fallback"] = buff.get("fallback")
    return adjusted


def _apply_player_attacker_officer_stat_rating_buffs(
    row: dict[str, Any],
    stats: dict[str, Any],
    adjustments: list[dict[str, Any]],
) -> dict[str, Any]:
    if row.get("attacker_side") != "player":
        return stats
    ship = row.get("attacker", {})
    if not isinstance(ship, dict):
        return stats
    ratings = ship.get("captured_fleet_ratings", {})
    offense_rating = _number(ratings.get("offense_rating") if isinstance(ratings, dict) else 0.0)
    if offense_rating == 0.0:
        return stats
    buffs = _starbase_officer_stat_all_rating_buffs(ship)
    if not buffs:
        return stats

    adjusted = dict(stats)
    for buff in buffs:
        multiplier = _number(buff.get("selected_ranked_value"))
        additive = offense_rating * multiplier
        stat_key = "8"
        if stat_key not in adjusted:
            continue
        before = _number(adjusted.get(stat_key))
        adjusted[stat_key] = before + additive
        adjustments.append(
            {
                "source": "player_starbase_officer_stat_all_offense_rating_modifier",
                "modifierCode": OFFICER_STAT_ALL_MODIFIER_CODE,
                "role": "attacker",
                "stat": stat_key,
                "before": before,
                "after": adjusted[stat_key],
                "offense_rating": offense_rating,
                "multiplier": multiplier,
                "additive": additive,
                "buff_id": buff.get("buff_id"),
                "source_type": buff.get("source_type"),
                "source_key": buff.get("source_key"),
                "targetCode": buff.get("targetCode"),
                "triggerCode": buff.get("triggerCode"),
            }
        )
        if buff.get("fallback"):
            adjustments[-1]["source"] = "captured_fleet_stats_officer_stat_all_fallback"
            adjustments[-1]["fallback"] = buff.get("fallback")
    return adjusted


def _static_player_max_buff_stats(row: dict[str, Any], role: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stats = _player_defender_lookup_base_stats(row, role, _static_base_stats(row, role))
    percents, adjustments = _triangle_modifier_percents(row, role, stats)
    adjusted = {}
    for stat_key, value in stats.items():
        adjusted[stat_key] = _number(value) * (1.0 + percents.get(stat_key, 0.0))
    if role == "attacker":
        adjusted = _apply_player_attacker_officer_stat_rating_buffs(row, adjusted, adjustments)
    if role == "defender":
        adjusted = _apply_player_defender_officer_stat_rating_buffs(row, adjusted, adjustments)
    return adjusted, adjustments


def _static_weapon_stats(row: dict[str, Any]) -> dict[str, Any]:
    weapon = row.get("weapon", {})
    if not isinstance(weapon, dict):
        return {}
    return {
        stat_key: weapon.get(weapon_key)
        for stat_key, weapon_key in (
            ("6", "accuracy"),
            ("7", "penetration"),
            ("8", "modulation"),
        )
        if weapon.get(weapon_key) is not None
    }


def _combat_triangle_stats(
    row: dict[str, Any],
    *,
    stat_source: str | None,
    prefer_resolved_player_stats: bool,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    source = stat_source or ("resolved_player_live" if prefer_resolved_player_stats else "captured_live")
    if source == "resolved_player_live":
        return (
            source,
            _ship_stats(row, "attacker", prefer_resolved_player_stats=True),
            _ship_stats(row, "defender", prefer_resolved_player_stats=True),
        )
    if source == "captured_live":
        return (
            source,
            _ship_stats(row, "attacker", prefer_resolved_player_stats=False),
            _ship_stats(row, "defender", prefer_resolved_player_stats=False),
        )
    if source == "static_base":
        return source, _static_base_stats(row, "attacker"), _static_base_stats(row, "defender")
    if source == "static_player_max_buffs":
        attacker_stats, _attacker_adjustments = _static_player_max_buff_stats(row, "attacker")
        defender_stats, _defender_adjustments = _static_player_max_buff_stats(row, "defender")
        if row.get("attacker_side") == "hostile":
            attacker_stats.update(_static_weapon_stats(row))
        return source, attacker_stats, defender_stats
    raise ValueError(f"unknown combat triangle stat source: {source}")


def _ship_id_keys(row: dict[str, Any], role: str) -> set[str]:
    ship = row.get(role, {})
    if not isinstance(ship, dict):
        return set()
    return {
        key
        for key in (
            _id_key(ship.get("ship_id")),
            _id_key(ship.get("battle_log_ship_id")),
        )
        if key
    }


def _opposite_role(role: str | None) -> str | None:
    if role == "attacker":
        return "defender"
    if role == "defender":
        return "attacker"
    return None


def _activation_firing_role(row: dict[str, Any], activation: dict[str, Any]) -> str | None:
    firing_ship_id = _id_key(activation.get("firing_ship_id"))
    if not firing_ship_id:
        return None
    if firing_ship_id in _ship_id_keys(row, "attacker"):
        return "attacker"
    if firing_ship_id in _ship_id_keys(row, "defender"):
        return "defender"
    return None


def _activation_officer_stat_scale(
    row: dict[str, Any],
    activation: dict[str, Any],
    *,
    officer_stat_scale: str,
) -> tuple[float, dict[str, Any] | None]:
    if officer_stat_scale == "none":
        return 1.0, None
    if officer_stat_scale not in OFFICER_STAT_SCALE_MODES:
        raise ValueError(f"unknown officer stat scale mode: {officer_stat_scale}")

    ability = activation.get("ability")
    attributes = ability.get("attributes", {}) if isinstance(ability, dict) else {}
    officer_stat = attributes.get("officerStat") if isinstance(attributes, dict) else None
    stat_code = OFFICER_STAT_MODIFIER_CODES.get(str(officer_stat))
    if stat_code is None:
        return 1.0, None

    firing_role = _activation_firing_role(row, activation)
    ship = row.get(firing_role or "", {})
    fleet_stats = ship.get("captured_fleet_stats", {}) if isinstance(ship, dict) else {}
    stat_value = _number(fleet_stats.get(stat_code) if isinstance(fleet_stats, dict) else 0.0)
    scale = stat_value if officer_stat_scale == "raw" else stat_value / 100.0
    return scale, {
        "officerStat": str(officer_stat),
        "stat_code": stat_code,
        "stat_value": stat_value,
        "scale": scale,
        "scale_mode": officer_stat_scale,
        "firing_role": firing_role or "unknown",
    }


def _activation_target_role(row: dict[str, Any], activation: dict[str, Any]) -> str | None:
    target_code = _id_key(activation.get("targetCode"))
    firing_role = _activation_firing_role(row, activation)
    if target_code in SELF_TARGET_CODES:
        return firing_role
    if target_code in OPPONENT_TARGET_CODES:
        return _opposite_role(firing_role)
    return None


def _apply_buff_operation(*, base_value: float, current_value: float, op: str, value: float) -> float:
    if op == "BUFFOPERATION_ADD":
        result = current_value + value
    elif op == "BUFFOPERATION_SUB":
        result = current_value - value
    elif op == "BUFFOPERATION_MULTIPLYADD":
        result = current_value * (1.0 + value)
    elif op == "BUFFOPERATION_MULTIPLYSUB":
        result = current_value * (1.0 - value)
    elif op == "BUFFOPERATION_MULTIPLYBASEADD":
        result = current_value + base_value * value
    elif op == "BUFFOPERATION_MULTIPLYBASESUB":
        result = current_value - base_value * value
    else:
        result = current_value
    return max(0.0, result)


def _apply_triggered_triangle_effects(
    row: dict[str, Any],
    *,
    attacker_stats: dict[str, Any],
    defender_stats: dict[str, Any],
    officer_stat_scale: str,
) -> tuple[dict[str, float], dict[str, float], list[dict[str, Any]]]:
    adjusted = {
        "attacker": {key: _number(value) for key, value in attacker_stats.items()},
        "defender": {key: _number(value) for key, value in defender_stats.items()},
    }
    base = {
        "attacker": dict(adjusted["attacker"]),
        "defender": dict(adjusted["defender"]),
    }
    applied: list[dict[str, Any]] = []
    observed = row.get("observed", {})
    activations = observed.get("officer_activations", []) if isinstance(observed, dict) else []
    if not isinstance(activations, list):
        return adjusted["attacker"], adjusted["defender"], applied

    for activation in activations:
        if not isinstance(activation, dict):
            continue
        effect = activation.get("formula_effect")
        if isinstance(effect, dict) and effect.get("formula_stage") != "normal_mitigation_triangle":
            continue
        modifier_code = _id_key(activation.get("modifierCode"))
        target = TRIANGLE_MODIFIER_STAT_TARGETS.get(modifier_code)
        if target is None:
            continue
        implied_role, stat_keys = target
        target_role = _activation_target_role(row, activation)
        if target_role is not None and target_role != implied_role:
            continue

        op = str(activation.get("op") or "")
        base_value = _number(activation.get("value"))
        officer_scale, officer_scale_detail = _activation_officer_stat_scale(
            row,
            activation,
            officer_stat_scale=officer_stat_scale,
        )
        value = base_value * officer_scale
        for stat_key in stat_keys:
            before = adjusted[implied_role].get(stat_key, 0.0)
            after = _apply_buff_operation(
                base_value=base[implied_role].get(stat_key, 0.0),
                current_value=before,
                op=op,
                value=value,
            )
            adjusted[implied_role][stat_key] = after
            applied.append(
                {
                    "modifierCode": modifier_code,
                    "op": op,
                    "value": base_value,
                    "effective_value": value,
                    "role": implied_role,
                    "stat": stat_key,
                    "before": before,
                    "after": after,
                    "ability_buff_id": _id_key(activation.get("ability_buff_id")) or "unknown",
                    "officer_id": _id_key(activation.get("officer_id")) or "unknown",
                    "targetCode": _id_key(activation.get("targetCode")) or "unknown",
                    "officer_stat_scale": officer_scale_detail,
                }
            )

    return adjusted["attacker"], adjusted["defender"], applied


def _hull_type(row: dict[str, Any], role: str) -> str:
    ship = row.get(role, {})
    if not isinstance(ship, dict):
        return ""
    static_ship = ship.get("static_ship", {})
    if not isinstance(static_ship, dict):
        return ""
    hull = static_ship.get("hull", {})
    if not isinstance(hull, dict):
        return ""
    return str(hull.get("type") or "")


def deterministic_basic_live_features(
    row: dict[str, Any],
    *,
    prefer_resolved_player_stats: bool = True,
) -> dict[str, float]:
    attacker_stats = _ship_stats(row, "attacker", prefer_resolved_player_stats=prefer_resolved_player_stats)
    defender_stats = _ship_stats(row, "defender", prefer_resolved_player_stats=prefer_resolved_player_stats)
    return {
        "live_dodge_ratio": _ratio(defender_stats.get("11"), attacker_stats.get("6")),
        "live_plating_ratio": _ratio(defender_stats.get("-3"), attacker_stats.get("7")),
        "live_absorption_ratio": (
            _ratio(defender_stats.get("-2"), attacker_stats.get("8")) if _shield_active_before_shot(row) else 0.0
        ),
    }


def _clamp_mitigation(value: float) -> float:
    return max(0.0, min(0.95, value))


def _apex_barrier_stage_mitigation(row: dict[str, Any]) -> float:
    defender = row.get("defender", {})
    if not isinstance(defender, dict):
        return 0.0
    modifiers = defender.get("resolved_modifiers", {})
    if not isinstance(modifiers, dict):
        return 0.0
    barrier = _number(modifiers.get(APEX_BARRIER_MODIFIER_CODE))
    if barrier <= 1.0:
        return 0.0
    damage_remaining = apex_barrier_damage_reduction(apex_barrier=barrier, apex_shred=0)
    return max(0.0, min(1.0, 1.0 - damage_remaining))


def _combine_mitigation_stages(normal_mitigation: float, apex_mitigation: float) -> float:
    return _clamp_mitigation(1.0 - (1.0 - normal_mitigation) * (1.0 - apex_mitigation))


def predict_basic_live_mitigation(
    row: dict[str, Any],
    *,
    prefer_resolved_player_stats: bool = True,
    weights: dict[str, float] | None = None,
) -> float:
    features = deterministic_basic_live_features(
        row,
        prefer_resolved_player_stats=prefer_resolved_player_stats,
    )
    active_weights = weights or BASIC_LIVE_MITIGATION_WEIGHTS
    prediction = sum(features[name] * active_weights.get(name, 0.0) for name in BASIC_LIVE_MITIGATION_FEATURES)
    return _clamp_mitigation(prediction)


def _combat_triangle_component(defense: Any, piercing: Any, *, curve_base: float = DEFAULT_COMBAT_TRIANGLE_CURVE_BASE) -> float:
    if not math.isfinite(curve_base) or curve_base <= 1.0:
        raise ValueError(f"combat triangle curve base must be finite and greater than 1: {curve_base}")
    if curve_base == DEFAULT_COMBAT_TRIANGLE_CURVE_BASE:
        return toolbox_mitigation_component(defense, piercing)
    piercing_value = max(0.0, _number(piercing))
    if piercing_value == 0:
        return 0.0
    return 1.0 / (1.0 + curve_base ** (1.1 - _number(defense) / piercing_value))


def combat_triangle_features(
    row: dict[str, Any],
    *,
    prefer_resolved_player_stats: bool = True,
    stat_source: str | None = None,
    apply_triggered_effects: bool = False,
    officer_stat_scale: str = "none",
    stat_role_orientation: str = "normal",
    curve_base: float = DEFAULT_COMBAT_TRIANGLE_CURVE_BASE,
) -> dict[str, Any]:
    if stat_role_orientation not in COMBAT_TRIANGLE_STAT_ROLE_ORIENTATIONS:
        raise ValueError(f"unknown combat triangle stat role orientation: {stat_role_orientation}")
    source, attacker_stats, defender_stats = _combat_triangle_stats(
        row,
        stat_source=stat_source,
        prefer_resolved_player_stats=prefer_resolved_player_stats,
    )
    stat_adjustments: list[dict[str, Any]] = []
    if apply_triggered_effects:
        attacker_stats, defender_stats, stat_adjustments = _apply_triggered_triangle_effects(
            row,
            attacker_stats=attacker_stats,
            defender_stats=defender_stats,
            officer_stat_scale=officer_stat_scale,
        )
    formula_attacker_stats = attacker_stats
    formula_defender_stats = defender_stats
    formula_defender_role = "defender"
    if stat_role_orientation in {"swapped_stats_defender_weights", "swapped_stats_attacker_weights"}:
        formula_attacker_stats = defender_stats
        formula_defender_stats = attacker_stats
        if stat_role_orientation == "swapped_stats_attacker_weights":
            formula_defender_role = "attacker"

    hull_type = _hull_type(row, formula_defender_role)
    weights = toolbox_weights_for(hull_type)
    stat_inputs = {
        "armor": {
            "defense": _number(formula_defender_stats.get("-3")),
            "piercing": _number(formula_attacker_stats.get("7")),
        },
        "shield": {
            "defense": _number(formula_defender_stats.get("-2")),
            "piercing": _number(formula_attacker_stats.get("8")),
        },
        "dodge": {
            "defense": _number(formula_defender_stats.get("11")),
            "piercing": _number(formula_attacker_stats.get("6")),
        },
    }
    components = {
        key: _combat_triangle_component(values["defense"], values["piercing"], curve_base=curve_base)
        for key, values in stat_inputs.items()
    }
    return {
        "defender_hull_type": hull_type,
        "stat_source": source,
        "stat_role_orientation": stat_role_orientation,
        "curve_base": curve_base,
        "stat_inputs": stat_inputs,
        "weights": weights,
        "components": components,
        "stat_adjustments": stat_adjustments,
    }


def predict_combat_triangle_mitigation(
    row: dict[str, Any],
    *,
    prefer_resolved_player_stats: bool = True,
    stat_source: str | None = None,
    composition: str = "weighted_product",
    apply_triggered_effects: bool = False,
    officer_stat_scale: str = "none",
    stat_role_orientation: str = "normal",
    curve_base: float = DEFAULT_COMBAT_TRIANGLE_CURVE_BASE,
    include_apex_barrier: bool = False,
) -> float:
    features = combat_triangle_features(
        row,
        prefer_resolved_player_stats=prefer_resolved_player_stats,
        stat_source=stat_source,
        apply_triggered_effects=apply_triggered_effects,
        officer_stat_scale=officer_stat_scale,
        stat_role_orientation=stat_role_orientation,
        curve_base=curve_base,
    )
    weights = features["weights"]
    components = features["components"]
    if not isinstance(weights, dict) or not isinstance(components, dict):
        return 0.0
    if composition == "weighted_product":
        prediction = _clamp_mitigation(
            1.0
            - math.prod(
                1.0 - float(weights[key]) * float(components[key])
                for key in ("armor", "shield", "dodge")
            )
        )
        if include_apex_barrier:
            return _combine_mitigation_stages(prediction, _apex_barrier_stage_mitigation(row))
        return prediction
    if composition == "weighted_sum":
        prediction = _clamp_mitigation(
            sum(float(weights[key]) * float(components[key]) for key in ("armor", "shield", "dodge"))
        )
        if include_apex_barrier:
            return _combine_mitigation_stages(prediction, _apex_barrier_stage_mitigation(row))
        return prediction
    if composition == "weighted_power_product":
        unmitigated = 1.0
        for key in ("armor", "shield", "dodge"):
            unmitigated *= (1.0 - float(components[key])) ** float(weights[key])
        prediction = _clamp_mitigation(1.0 - unmitigated)
        if include_apex_barrier:
            return _combine_mitigation_stages(prediction, _apex_barrier_stage_mitigation(row))
        return prediction
    if composition in {
        "active_layer_weighted_sum",
        "active_layer_weighted_product",
        "active_layer_weighted_product_unscaled",
    }:
        active_keys = ("shield", "dodge") if _shield_active_before_shot(row) else ("armor", "dodge")
        active_weight_sum = sum(float(weights[key]) for key in active_keys)
        if composition == "active_layer_weighted_sum":
            prediction = _clamp_mitigation(
                sum(float(weights[key]) * float(components[key]) for key in active_keys) / active_weight_sum
                if active_weight_sum
                else 0.0
            )
            if include_apex_barrier:
                return _combine_mitigation_stages(prediction, _apex_barrier_stage_mitigation(row))
            return prediction
        unmitigated = 1.0
        for key in active_keys:
            weight = float(weights[key])
            if composition == "active_layer_weighted_product":
                weight = weight / active_weight_sum if active_weight_sum else 0.0
            unmitigated *= 1.0 - (weight * float(components[key]))
        prediction = _clamp_mitigation(1.0 - unmitigated)
        if include_apex_barrier:
            return _combine_mitigation_stages(prediction, _apex_barrier_stage_mitigation(row))
        return prediction
    raise ValueError(f"unknown combat triangle composition: {composition}")
