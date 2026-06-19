from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .damage_pipeline import observed_damage_stages


APEX_BARRIER_MODIFIER_CODE = "67001"
APEX_STATIC_SOURCES = (
    ("ResearchSpecs", "researchEffects", "research"),
    ("StarbaseBuffs", "starbaseBuffsSpecs", "starbase"),
    ("ConsumableBuffs", "consumableBuffsSpecs", "consumable"),
    ("ForbiddenTechBuffs", "forbiddenTechBuffsSpecs", "forbidden_tech"),
    ("ShipBonusBuffSpecs", "shipBonusSpecs", "ship_bonus"),
)
SAFE_GLOBAL_PROFILE_CONDITION_CODES = {"28", "137"}


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _report_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _collection(decoded_static_dir: Path, source_table: str, collection_key: str) -> dict[str, Any]:
    data = _read_json(decoded_static_dir / f"{source_table}.json")
    collection = data.get(collection_key)
    return collection if isinstance(collection, dict) else {}


def _global_active_rows(decoded_static_dir: Path) -> list[dict[str, Any]]:
    rows = _read_json(decoded_static_dir / "GlobalActiveBuffs.json").get("globalActiveBuffs", [])
    return [row for row in rows if isinstance(row, dict)]


def _ranked_values(spec: dict[str, Any]) -> list[Any]:
    values = spec.get("rankedValues") or spec.get("rankedBuffValues")
    return values if isinstance(values, list) else []


def _selected_ranked_value(spec: dict[str, Any], level: Any) -> tuple[int | None, float | None, str]:
    numeric_level = _number(level)
    if numeric_level <= 0:
        return None, None, "missing_level"
    selected_rank = int(numeric_level) - 1
    values = _ranked_values(spec)
    if not values:
        return selected_rank, None, "missing_ranked_values"
    if selected_rank < 0 or selected_rank >= len(values):
        return selected_rank, None, "level_rank_out_of_range"
    return selected_rank, _number(values[selected_rank]), "selected_from_global_level"


def _operation_delta(spec: dict[str, Any], value: float | None) -> tuple[float | None, str]:
    if value is None:
        return None, "missing_value"
    operation = spec.get("op")
    if operation in {"BUFFOPERATION_ADD", "BUFFOPERATION_MULTIPLYADD"}:
        return value, "applied"
    if operation in {"BUFFOPERATION_SUB", "BUFFOPERATION_MULTIPLYSUB"}:
        return -value, "applied"
    return None, "unsupported_operation"


def _condition_status(spec: dict[str, Any], source_type: str) -> str:
    condition_codes = {_id_key(code) for code in spec.get("conditionCodes", []) if _id_key(code) != "0"}
    attrs = spec.get("attributes") or {}
    faction_id = _id_key(attrs.get("factionId")) if isinstance(attrs, dict) and attrs.get("factionId") is not None else "-1"
    if source_type == "research" and condition_codes <= SAFE_GLOBAL_PROFILE_CONDITION_CODES and faction_id == "-1":
        return "supported_global_profile_research"
    if not condition_codes:
        return "unsupported_missing_conditions"
    return "requires_condition_evaluator"


def _spec_index(decoded_static_dir: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for source_table, collection_key, source_type in APEX_STATIC_SOURCES:
        for buff_id, spec in _collection(decoded_static_dir, source_table, collection_key).items():
            if not isinstance(spec, dict) or _id_key(spec.get("modifierCode")) != APEX_BARRIER_MODIFIER_CODE:
                continue
            index.setdefault(
                _id_key(buff_id),
                {
                    "buff_id": _id_key(buff_id),
                    "source_table": source_table,
                    "source_type": source_type,
                    "source_key": f"{collection_key}/{_id_key(buff_id)}",
                    "spec": spec,
                },
            )
    return index


def build_apex_source_index(decoded_static_dir: Path) -> dict[str, Any]:
    spec_index = _spec_index(decoded_static_dir)
    active_global_candidates = []
    for active in _global_active_rows(decoded_static_dir):
        buff_id = _id_key(active.get("buffId") or (active.get("activeBuff") or {}).get("buffId"))
        entry = spec_index.get(buff_id)
        if entry is None:
            continue
        spec = entry["spec"]
        selected_rank, selected_value, selected_status = _selected_ranked_value(spec, active.get("level"))
        delta, delta_status = _operation_delta(spec, selected_value)
        active_global_candidates.append(
            {
                "buff_id": buff_id,
                "source_table": entry["source_table"],
                "source_type": entry["source_type"],
                "source_key": entry["source_key"],
                "level": _report_number(_number(active.get("level"))),
                "selected_rank": selected_rank,
                "selected_ranked_value": _report_number(selected_value) if selected_value is not None else None,
                "selected_rank_status": selected_status,
                "delta": _report_number(delta) if delta is not None else None,
                "delta_status": delta_status,
                "conditionCodes": [_id_key(code) for code in spec.get("conditionCodes", [])],
                "spec_attributes": spec.get("attributes", {}),
                "condition_status": _condition_status(spec, str(entry["source_type"])),
            }
        )

    return {
        "decoded_static_dir": str(decoded_static_dir),
        "static_apex_spec_count": len(spec_index),
        "active_global_apex_count": len(active_global_candidates),
        "active_global_candidates": active_global_candidates,
    }


def _required_apex_barrier(row: dict[str, Any]) -> float:
    stages = observed_damage_stages(row)
    mitigation = _number(stages.get("apex_mitigation"))
    if mitigation <= 0.0:
        return 0.0
    mitigation = min(0.999999, mitigation)
    return 10000.0 * mitigation / (1.0 - mitigation)


def _activation_apex_value(activation: Any) -> float:
    if not isinstance(activation, dict) or _id_key(activation.get("modifierCode")) != APEX_BARRIER_MODIFIER_CODE:
        return 0.0
    value = _number(activation.get("value"))
    if activation.get("op") in {"BUFFOPERATION_SUB", "BUFFOPERATION_MULTIPLYSUB"}:
        return -value
    return value


def _battle_forbidden_tech_apex(row: dict[str, Any]) -> float:
    observed = row.get("observed", {})
    activations = observed.get("forbidden_tech_activations", []) if isinstance(observed, dict) else []
    if not isinstance(activations, list):
        return 0.0
    return sum(_activation_apex_value(activation) for activation in activations)


def _metrics(errors: list[float]) -> dict[str, int | float]:
    if not errors:
        return {"count": 0, "mae": 0, "max_abs_error": 0, "bias": 0}
    return {
        "count": len(errors),
        "mae": _report_number(sum(abs(error) for error in errors) / len(errors)),
        "max_abs_error": _report_number(max(abs(error) for error in errors)),
        "bias": _report_number(sum(errors) / len(errors)),
    }


def _distribution(values: list[float]) -> dict[str, int | float]:
    if not values:
        return {"count": 0, "min": 0, "max": 0, "mean": 0, "stddev": 0}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {
        "count": len(values),
        "min": _report_number(min(values)),
        "max": _report_number(max(values)),
        "mean": _report_number(mean),
        "stddev": _report_number(variance**0.5),
    }


def _candidate_barriers(index: dict[str, Any]) -> dict[str, float]:
    candidates = index.get("active_global_candidates", [])
    safe_research = sum(
        _number(candidate.get("delta"))
        for candidate in candidates
        if candidate.get("condition_status") == "supported_global_profile_research"
        and candidate.get("delta_status") == "applied"
    )
    all_global = sum(
        _number(candidate.get("delta"))
        for candidate in candidates
        if candidate.get("delta_status") == "applied"
    )
    by_source = {
        source_type: sum(
            _number(candidate.get("delta"))
            for candidate in candidates
            if candidate.get("source_type") == source_type and candidate.get("delta_status") == "applied"
        )
        for source_type in ("research", "starbase", "consumable")
    }
    return {
        "active_global_safe_research": safe_research,
        "active_global_all": all_global,
        **{f"active_global_{source_type}": value for source_type, value in by_source.items()},
    }


def evaluate_apex_source_candidates(rows: list[dict[str, Any]], index: dict[str, Any]) -> dict[str, Any]:
    apex_rows = [
        row
        for row in rows
        if _number((row.get("observed", {}) if isinstance(row.get("observed"), dict) else {}).get("mitigated_apex_barrier"))
        > 0.0
    ]
    base_candidates = _candidate_barriers(index)
    candidates = dict(base_candidates)
    candidates["battle_forbidden_tech"] = None
    candidates["active_global_safe_research_plus_battle_forbidden_tech"] = None
    candidates["active_global_all_plus_battle_forbidden_tech"] = None

    metrics = {}
    for name, barrier in candidates.items():
        errors = []
        for row in apex_rows:
            row_barrier = _battle_forbidden_tech_apex(row) if barrier is None else barrier
            if name == "active_global_safe_research_plus_battle_forbidden_tech":
                row_barrier = base_candidates["active_global_safe_research"] + _battle_forbidden_tech_apex(row)
            elif name == "active_global_all_plus_battle_forbidden_tech":
                row_barrier = base_candidates["active_global_all"] + _battle_forbidden_tech_apex(row)
            errors.append(row_barrier - _required_apex_barrier(row))
        metrics[name] = {
            "barrier": _report_number(base_candidates.get(name, 0.0)) if name in base_candidates else "row_level",
            "metrics": _metrics(errors),
        }

    condition_status_counts: dict[str, int] = {}
    for candidate in index.get("active_global_candidates", []):
        status = str(candidate.get("condition_status") or "unknown")
        condition_status_counts[status] = condition_status_counts.get(status, 0) + 1

    by_defender_status: dict[str, list[float]] = {}
    for row in apex_rows:
        defender = row.get("defender", {})
        status_effects = defender.get("status_effects", {}) if isinstance(defender, dict) else {}
        if not isinstance(status_effects, dict):
            continue
        required_barrier = _required_apex_barrier(row)
        for status_effect in status_effects:
            by_defender_status.setdefault(_id_key(status_effect), []).append(required_barrier)

    return {
        "purpose": "diagnostic only; compare Apex Barrier source candidates before wiring 67001 into simulator state",
        "apex_rows": len(apex_rows),
        "static_apex_spec_count": index.get("static_apex_spec_count", 0),
        "active_global_apex_count": index.get("active_global_apex_count", 0),
        "active_global_condition_status_counts": dict(sorted(condition_status_counts.items())),
        "active_global_candidates": index.get("active_global_candidates", []),
        "required_barrier_by_defender_status": {
            status_effect: _distribution(values)
            for status_effect, values in sorted(
                by_defender_status.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )
        },
        "candidate_metrics": metrics,
    }
