from __future__ import annotations

from typing import Any

from .formula_effects import formula_effect_for_modifier
from .mitigation_targets import isolytic_damage_model_from_observed


COMBAT_START_TRIGGER_CODES = {"25"}
SELF_SHIP_TARGET_CODES = {"1"}
OPPONENT_SHIP_TARGET_CODES = {"6"}
FACTION_CONDITION_CODES = {"17"}

LOOT_MODIFIER_CODES = {
    "23",
    "24",
    "25",
    "26",
    "27",
    "28",
    "29",
    "37",
    "38",
    "39",
    "40",
    "101",
    "103",
    "145",
    "146",
    "148",
    "149",
    "156",
    "161",
    "170",
    "171",
    "172",
    "173",
    "174",
    "175",
    "176",
    "177",
    "178",
    "179",
    "205",
    "206",
    "207",
    "209",
    "211",
    "212",
    "213",
    "215",
    "217",
    "242",
    "244",
    "67003",
    "71001",
    "75004",
    "78010",
    "78016",
    "80002",
    "80003",
}
PERCENT_AS_MULTIPLIER_MODIFIER_CODES = {"707"}


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _report_number(value: int | float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def _ranked_values(spec: dict[str, Any]) -> list[Any]:
    value = spec.get("rankedBuffValues")
    if not value:
        value = spec.get("rankedValues")
    return value if isinstance(value, list) else []


def _selected_ranked_value(spec: dict[str, Any], ship_level: Any) -> tuple[int | None, Any, str]:
    level = _number(ship_level)
    if level is None:
        return None, None, "missing_ship_level"
    selected_rank = int(level) - 1
    values = _ranked_values(spec)
    if not values:
        return selected_rank, None, "missing_ranked_values"
    if selected_rank < 0 or selected_rank >= len(values):
        return selected_rank, None, "ship_level_rank_out_of_range"
    return selected_rank, _number(values[selected_rank]), "selected_from_ship_level"


def _modifier_value_for_formula(modifier_code: Any, value: Any) -> float | None:
    numeric = _number(value)
    if numeric is None:
        return None
    if _id_key(modifier_code) in PERCENT_AS_MULTIPLIER_MODIFIER_CODES and abs(float(numeric)) >= 100.0:
        return float(numeric) / 100.0
    return float(numeric)


def _operation_delta(operation: Any, value: Any, *, modifier_code: Any = None) -> tuple[float | None, str]:
    numeric = _modifier_value_for_formula(modifier_code, value)
    if numeric is None:
        return None, "missing_value"
    if operation in {"BUFFOPERATION_ADD", "BUFFOPERATION_MULTIPLYADD"}:
        return float(numeric), "applied"
    if operation in {"BUFFOPERATION_SUB", "BUFFOPERATION_MULTIPLYSUB"}:
        return -float(numeric), "applied"
    return None, "unsupported_operation"


def _nonzero_condition_codes(spec: dict[str, Any]) -> set[str]:
    return {_id_key(code) for code in spec.get("conditionCodes", []) if _id_key(code) != "0"}


def _faction_status(spec: dict[str, Any], opponent: dict[str, Any]) -> str:
    attrs = spec.get("attributes") or {}
    faction_id = attrs.get("factionId")
    if faction_id is None or _id_key(faction_id) == "-1":
        return "any_faction"
    opponent_faction = opponent.get("fleet_faction_id")
    if opponent_faction is not None and _id_key(faction_id) == _id_key(opponent_faction):
        return "matched_faction"
    return "faction_mismatch"


def _first_pass_condition_status(spec: dict[str, Any], opponent: dict[str, Any]) -> str:
    condition_codes = _nonzero_condition_codes(spec)
    attrs = set((spec.get("attributes") or {}).keys())
    unsupported_attrs = attrs - {"factionId"}
    if unsupported_attrs:
        return "unsupported_attributes"

    faction_status = _faction_status(spec, opponent)
    if faction_status == "faction_mismatch":
        return faction_status

    if not condition_codes:
        return faction_status
    if condition_codes <= FACTION_CONDITION_CODES and "factionId" in attrs:
        return faction_status
    return "unsupported_condition_codes"


def _base_summary(
    *,
    buff_id: str,
    spec: dict[str, Any],
    ship: dict[str, Any],
    opponent: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    selected_rank, selected_value, selected_status = _selected_ranked_value(spec, ship.get("ship_level"))
    delta, delta_status = _operation_delta(
        spec.get("op"),
        selected_value,
        modifier_code=spec.get("modifierCode"),
    )
    return {
        "buff_id": buff_id,
        "modifierCode": _id_key(spec.get("modifierCode")),
        "formula_effect": formula_effect_for_modifier(spec.get("modifierCode")),
        "buffOperation": spec.get("op"),
        "targetCode": _id_key(spec.get("targetCode")),
        "triggerCode": _id_key(spec.get("triggerCode")),
        "conditionCodes": sorted(_nonzero_condition_codes(spec)),
        "spec_attributes": spec.get("attributes", {}),
        "opponent_faction_id": opponent.get("fleet_faction_id"),
        "selected_rank": selected_rank,
        "selected_ranked_value": _report_number(selected_value),
        "selected_rank_status": selected_status,
        "delta": _report_number(delta),
        "delta_status": delta_status,
        "source": source,
    }


def _candidate_ship_bonus_ids(static_hull: dict[str, Any]) -> list[str]:
    ids = static_hull.get("all_ship_bonus_ids")
    if not isinstance(ids, list) or not ids:
        ids = static_hull.get("ship_bonus_ids", [])
    return [_id_key(buff_id) for buff_id in ids]


def resolve_static_ship_bonuses(
    ship: dict[str, Any], opponent: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    static_hull = ((ship.get("static_ship") or {}).get("hull") or {})
    ship_bonus_ids = _candidate_ship_bonus_ids(static_hull)
    ship_bonus_sources = static_hull.get("ship_bonus_sources") or {}
    ship_bonus_specs = catalog.get("ship_bonus_specs") or {}
    active_ship_bonus_ids = {_id_key(buff_id) for buff_id in ship.get("active_ship_bonus_ids", [])}

    applied_modifiers = []
    opponent_modifiers = []
    loot_bonuses = []
    skipped_modifiers = []
    for buff_id in ship_bonus_ids:
        spec = ship_bonus_specs.get(buff_id)
        if not isinstance(spec, dict):
            continue

        summary = _base_summary(
            buff_id=buff_id,
            spec=spec,
            ship=ship,
            opponent=opponent,
            source=str(ship_bonus_sources.get(buff_id) or "HullSpecs.shipBonuses"),
        )
        modifier_code = summary["modifierCode"]
        if modifier_code in LOOT_MODIFIER_CODES:
            loot_bonuses.append({**summary, "tag": "loot_bonus"})

        if summary["targetCode"] not in SELF_SHIP_TARGET_CODES | OPPONENT_SHIP_TARGET_CODES:
            skipped_modifiers.append({**summary, "application_status": "unsupported_target"})
            continue
        if summary["triggerCode"] not in COMBAT_START_TRIGGER_CODES:
            skipped_modifiers.append({**summary, "application_status": "unsupported_trigger"})
            continue

        condition_status = _first_pass_condition_status(spec, opponent)
        if condition_status in {"faction_mismatch", "unsupported_attributes", "unsupported_condition_codes"}:
            skipped_modifiers.append({**summary, "application_status": condition_status})
            continue
        if buff_id in active_ship_bonus_ids:
            skipped_modifiers.append({**summary, "application_status": "already_active"})
            continue
        if summary["delta"] is None or summary["delta_status"] != "applied":
            skipped_modifiers.append({**summary, "application_status": summary["delta_status"]})
            continue

        applied = {**summary, "application_status": condition_status}
        if summary["targetCode"] in OPPONENT_SHIP_TARGET_CODES:
            opponent_modifiers.append(applied)
        else:
            applied_modifiers.append(applied)

    return {
        "applied_modifiers": applied_modifiers,
        "opponent_modifiers": opponent_modifiers,
        "loot_bonuses": loot_bonuses,
        "skipped_modifiers": skipped_modifiers,
    }


def apply_static_ship_bonuses_to_row(row: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    for role, opponent_role in (("attacker", "defender"), ("defender", "attacker")):
        ship = row.get(role)
        opponent = row.get(opponent_role)
        if not isinstance(ship, dict) or not isinstance(opponent, dict):
            continue

        effects = resolve_static_ship_bonuses(ship, opponent, catalog)
        if any(effects.values()):
            ship["static_ship_bonus_effects"] = effects

        for bonus in effects["applied_modifiers"]:
            modifier_code = bonus["modifierCode"]
            delta = float(bonus["delta"])
            resolved = ship.setdefault("resolved_modifiers", {})
            resolved[modifier_code] = _report_number(float(resolved.get(modifier_code, 0.0)) + delta)

        for bonus in effects["opponent_modifiers"]:
            modifier_code = bonus["modifierCode"]
            delta = float(bonus["delta"])
            resolved = opponent.setdefault("resolved_modifiers", {})
            resolved[modifier_code] = _report_number(float(resolved.get(modifier_code, 0.0)) + delta)

        if role == "attacker" and effects["applied_modifiers"]:
            observed = row.get("observed")
            if isinstance(observed, dict):
                observed["isolytic_damage_model"] = isolytic_damage_model_from_observed(
                    observed,
                    attacker_stats=ship.get("resolved_modifiers", {}),
                    attacker_stat_source="resolved_buff_audit_static_ship_bonus",
                    captured_attacker_stats=ship.get("captured_fleet_stats", {}),
                )

    return row


def apply_static_ship_bonuses_to_rows(rows: list[dict[str, Any]], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    return [apply_static_ship_bonuses_to_row(row, catalog) for row in rows]
