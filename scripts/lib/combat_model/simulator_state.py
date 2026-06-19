from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from .mitigation_targets import isolytic_damage_model_from_observed


PlayerStateIndex = dict[tuple[str, str], dict[str, Any]]
CAPTURED_FLEET_MODIFIER_BASELINE_CODES = {"707", "808", "67001"}
OFFICER_STAT_ALL_MODIFIER_CODE = "59"


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


def _new_state(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "battle_id": _id_key(row.get("battle_id")),
        "battle_side": row.get("battle_side"),
        "side": "player",
        "ship_id": _id_key(row.get("ship_id")),
        "hull_id": row.get("hull_id"),
        "hull_type": row.get("hull_type"),
        "resolved_stats": {},
        "resolved_modifiers": {},
        "resolved_modifier_rows": [],
        "captured_stats": {},
        "static_stats": {},
        "stat_rows": {},
        "max_abs_residual": 0,
        "math_statuses": Counter(),
    }


def _modifier_value(row: dict[str, Any]) -> float | None:
    value = _number(row.get("selected_ranked_value"))
    if value is None:
        value = _number(row.get("zero_based_ranked_value"))
    return float(value) if value is not None else None


def _slim_active_modifier_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "buff_id": _id_key(row.get("buff_id")),
        "modifierCode": _id_key(row.get("modifierCode")),
        "buffOperation": row.get("buffOperation"),
        "targetCode": _id_key(row.get("targetCode")),
        "triggerCode": _id_key(row.get("triggerCode")),
        "selected_ranked_value": _report_number(_number(row.get("selected_ranked_value"))),
        "selected_rank": _report_number(_number(row.get("selected_rank"))),
        "source_type": row.get("source_type"),
        "source_key": row.get("source_key"),
    }


def _add_active_modifier_rows(buff_audit_report: dict[str, Any], index: PlayerStateIndex) -> None:
    for row in buff_audit_report.get("active_buffs", []):
        if not isinstance(row, dict) or row.get("side") != "player":
            continue
        if row.get("battle_id") is None or row.get("modifierCode") is None:
            continue
        value = _modifier_value(row)
        if value is None:
            continue
        ship_ids = row.get("ship_ids") or []
        if not isinstance(ship_ids, list):
            continue
        for ship_id in ship_ids:
            key = (_id_key(row["battle_id"]), _id_key(ship_id))
            state = index.setdefault(
                key,
                {
                    "battle_id": _id_key(row.get("battle_id")),
                    "battle_side": row.get("battle_side"),
                    "side": "player",
                    "ship_id": _id_key(ship_id),
                    "hull_id": (row.get("hull_ids") or [None])[0],
                    "hull_type": None,
                    "resolved_stats": {},
                    "resolved_modifiers": {},
                    "resolved_modifier_rows": [],
                    "captured_stats": {},
                    "static_stats": {},
                    "stat_rows": {},
                    "max_abs_residual": 0,
                    "math_statuses": Counter(),
                },
            )
            modifier_code = _id_key(row["modifierCode"])
            state["resolved_modifiers"][modifier_code] = _report_number(
                float(state["resolved_modifiers"].get(modifier_code, 0.0)) + value
            )
            if modifier_code == OFFICER_STAT_ALL_MODIFIER_CODE:
                state["resolved_modifier_rows"].append(_slim_active_modifier_row(row))


def _selected_live_stat_model(row: dict[str, Any]) -> str | None:
    components = row.get("explanation_components")
    if not isinstance(components, dict):
        return None
    model = components.get("selected_live_stat_model")
    return str(model) if model is not None else None


def build_resolved_player_state_index(buff_audit_report: dict[str, Any]) -> PlayerStateIndex:
    """Build simulator-facing player ship stats from a buff audit report.

    Keys are `(battle_id, ship_id)` because observations know player/hostile role but not
    the original initiator/target battle side. Captures currently have one player side per
    battle, and `battle_side` is retained in the indexed state for diagnostics.
    """

    index: PlayerStateIndex = {}
    _add_active_modifier_rows(buff_audit_report, index)
    for row in buff_audit_report.get("live_stat_residuals", []):
        if not isinstance(row, dict) or row.get("side") != "player":
            continue
        if row.get("battle_id") is None or row.get("ship_id") is None or row.get("stat_code") is None:
            continue

        explained = _number(row.get("explained"))
        if explained is None:
            continue

        key = (_id_key(row["battle_id"]), _id_key(row["ship_id"]))
        state = index.setdefault(key, _new_state(row))
        state["battle_side"] = row.get("battle_side") or state.get("battle_side")
        state["hull_id"] = row.get("hull_id") or state.get("hull_id")
        state["hull_type"] = row.get("hull_type") or state.get("hull_type")
        stat_code = _id_key(row["stat_code"])
        captured = _number(row.get("captured"))
        static = _number(row.get("static"))
        residual = _number(row.get("residual"))
        math_status = row.get("math_status")

        state["resolved_stats"][stat_code] = _report_number(explained)
        if captured is not None:
            state["captured_stats"][stat_code] = _report_number(captured)
        if static is not None:
            state["static_stats"][stat_code] = _report_number(static)
        if residual is not None:
            state["max_abs_residual"] = _report_number(
                max(float(state["max_abs_residual"]), abs(float(residual)))
            )
        if math_status is not None:
            state["math_statuses"].update([str(math_status)])

        state["stat_rows"][stat_code] = {
            "stat_code": stat_code,
            "static_field": row.get("static_field"),
            "captured": _report_number(captured),
            "static": _report_number(static),
            "explained": _report_number(explained),
            "residual": _report_number(residual),
            "math_status": math_status,
            "selected_live_stat_model": _selected_live_stat_model(row),
        }

    for state in index.values():
        state["math_statuses"] = dict(sorted(state["math_statuses"].items()))
    return index


def load_resolved_player_state_index(buff_audit_path: Path) -> PlayerStateIndex:
    return build_resolved_player_state_index(json.loads(buff_audit_path.read_text(encoding="utf-8")))


def attach_resolved_player_state(row: dict[str, Any], index: PlayerStateIndex) -> dict[str, Any]:
    attached = deepcopy(row)
    battle_id = _id_key(attached.get("battle_id"))

    for role in ("attacker", "defender"):
        if attached.get(f"{role}_side") != "player":
            continue
        ship = attached.get(role)
        if not isinstance(ship, dict) or ship.get("ship_id") is None:
            continue
        state = index.get((battle_id, _id_key(ship["ship_id"])))
        if state is None:
            continue

        existing_modifiers = dict(ship.get("resolved_modifiers", {}))
        ship["resolved_stats"] = dict(state["resolved_stats"])
        if state.get("resolved_modifiers") or existing_modifiers:
            ship["resolved_modifiers"] = {**state["resolved_modifiers"], **existing_modifiers}
        if state.get("resolved_modifier_rows"):
            ship["resolved_modifier_rows"] = list(state["resolved_modifier_rows"])
        captured_fleet_stats = ship.get("captured_fleet_stats", {})
        if isinstance(captured_fleet_stats, dict):
            resolved = ship.setdefault("resolved_modifiers", {})
            for modifier_code in CAPTURED_FLEET_MODIFIER_BASELINE_CODES:
                captured_value = _number(captured_fleet_stats.get(modifier_code))
                if captured_value is not None and modifier_code not in existing_modifiers:
                    resolved[modifier_code] = _report_number(captured_value)
        ship["resolved_stat_source"] = {
            "source": "buff_audit",
            "battle_id": state["battle_id"],
            "ship_id": state["ship_id"],
            "max_abs_residual": state["max_abs_residual"],
            "math_statuses": state["math_statuses"],
        }
        if role == "attacker":
            observed = attached.get("observed")
            if isinstance(observed, dict) and ship.get("resolved_modifiers"):
                observed["isolytic_damage_model"] = isolytic_damage_model_from_observed(
                    observed,
                    attacker_stats=ship["resolved_modifiers"],
                    attacker_stat_source="resolved_buff_audit",
                    captured_attacker_stats=ship.get("captured_fleet_stats", {}),
                )

    return attached


def attach_resolved_player_states(rows: list[dict[str, Any]], index: PlayerStateIndex) -> list[dict[str, Any]]:
    return [attach_resolved_player_state(row, index) for row in rows]
