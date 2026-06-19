from __future__ import annotations

from collections import Counter
from typing import Any

from .battle_enums import is_cutting_beam_battle_type
from .damage_pipeline import infer_pre_shot_state, observed_damage_stages, predict_damage_from_stages
from .mechanics import apex_barrier_damage_reduction, isolytic_mitigation


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _report_number(value: float) -> int | float:
    if abs(value) < 1e-9:
        return 0
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


def _shield_mitigation(row: dict[str, Any]) -> float:
    defender = row.get("defender", {})
    static_ship = defender.get("static_ship", {}) if isinstance(defender, dict) else {}
    base_stats = static_ship.get("base_stats", {}) if isinstance(static_ship, dict) else {}
    value = base_stats.get("shield_mitigation") if isinstance(base_stats, dict) else None
    if value is None:
        return 1.0
    return max(0.0, min(1.0, _number(value)))


def _simulation_pipeline_row(row: dict[str, Any]) -> dict[str, Any]:
    defender = row.get("defender", {})
    static_ship = defender.get("static_ship", {}) if isinstance(defender, dict) else {}
    base_stats = static_ship.get("base_stats", {}) if isinstance(static_ship, dict) else {}
    if isinstance(base_stats, dict) and base_stats.get("shield_mitigation") is not None:
        return row

    pipeline_row = dict(row)
    pipeline_defender = dict(defender) if isinstance(defender, dict) else {}
    pipeline_static_ship = dict(static_ship) if isinstance(static_ship, dict) else {}
    pipeline_base_stats = dict(base_stats) if isinstance(base_stats, dict) else {}
    pipeline_base_stats["shield_mitigation"] = 1.0
    pipeline_static_ship["base_stats"] = pipeline_base_stats
    pipeline_defender["static_ship"] = pipeline_static_ship
    pipeline_row["defender"] = pipeline_defender
    return pipeline_row


def _cutting_beam_level(observed: dict[str, Any], row: dict[str, Any], key: str) -> float:
    cutting_beam_key = f"cutting_beam_{key}"
    if observed.get(cutting_beam_key) is not None:
        return _number(observed.get(cutting_beam_key))
    return _number(row.get(key))


def _cutting_beam_level_scaling(observed: dict[str, Any], row: dict[str, Any]) -> dict[str, int | float]:
    player_level = _cutting_beam_level(observed, row, "player_level")
    hostile_level = _cutting_beam_level(observed, row, "hostile_level")
    level_delta = max(0, int(hostile_level - player_level))
    multiplier = max(0.0, 1.0 - 0.10 * level_delta)
    return {
        "player_level": _report_number(player_level),
        "hostile_level": _report_number(hostile_level),
        "level_delta": level_delta,
        "reduction_per_level": 0.10,
        "multiplier": _report_number(multiplier),
    }


def _cutting_beam_metadata(observed: dict[str, Any], row: dict[str, Any]) -> tuple[str, dict[str, int | float]]:
    source = "unscaled_damage_with_level_scale"
    if observed.get("cutting_beam_unscaled_damage") is None:
        source = "observed_scaled_raw_damage"
    return source, _cutting_beam_level_scaling(observed, row)


def simulate_damage_from_raw(
    row: dict[str, Any],
    *,
    effective_mitigation: float | None = None,
) -> dict[str, Any]:
    observed = _observed(row)
    damage = _damage(observed)
    remaining = _remaining(observed)
    mitigation = _number(effective_mitigation if effective_mitigation is not None else observed.get("effective_mitigation"))
    raw_damage = _number(observed.get("raw_damage"))

    pipeline = predict_damage_from_stages(
        _simulation_pipeline_row(row),
        standard_raw_damage=raw_damage,
        standard_mitigation=mitigation,
        isolytic_raw_damage=0,
        isolytic_mitigation=0,
        apex_mitigation=0,
    )

    is_cutting_beam = is_cutting_beam_battle_type(row.get("battle_type"))
    if is_cutting_beam:
        mitigation = 0.0
        shield_mitigation = 0.0
        cutting_beam_damage_source, cutting_beam_level_scaling = _cutting_beam_metadata(
            observed,
            row,
        )
    else:
        shield_mitigation = _shield_mitigation(row) if _number(pipeline["pre_shot"]["shield"]) > 0 else 0.0
        cutting_beam_damage_source = None
        cutting_beam_level_scaling = None

    predicted_damage = pipeline["damage"]
    predicted_remaining = pipeline["remaining"]
    mitigated_damage = _number(pipeline["after_apex"])

    errors = {
        "shield": _number(predicted_damage.get("shield")) - _number(damage.get("shield")),
        "hull": _number(predicted_damage.get("hull")) - _number(damage.get("hull")),
        "mitigated_damage": mitigated_damage - (_number(damage.get("shield")) + _number(damage.get("hull"))),
        "remaining_shield": _number(predicted_remaining.get("shield")) - _number(remaining.get("shield")),
        "remaining_hull": _number(predicted_remaining.get("hull")) - _number(remaining.get("hull")),
    }
    result = {
        "mode": pipeline["mode"],
        "raw_damage": _report_number(raw_damage),
        "effective_mitigation": mitigation,
        "shield_mitigation": shield_mitigation,
        "mitigated_damage": _report_number(mitigated_damage),
        "pre_shot": pipeline["pre_shot"],
        "damage": {
            "shield": _report_number(_number(predicted_damage.get("shield"))),
            "hull": _report_number(_number(predicted_damage.get("hull"))),
        },
        "remaining": {
            "shield": _report_number(_number(predicted_remaining.get("shield"))),
            "hull": _report_number(_number(predicted_remaining.get("hull"))),
        },
        "observed_damage": {
            "shield": _report_number(_number(damage.get("shield"))),
            "hull": _report_number(_number(damage.get("hull"))),
        },
        "observed_remaining": {
            "shield": _report_number(_number(remaining.get("shield"))),
            "hull": _report_number(_number(remaining.get("hull"))),
        },
        "errors": {key: _report_number(float(value)) for key, value in errors.items()},
    }
    if cutting_beam_damage_source is not None:
        result["cutting_beam_damage_source"] = cutting_beam_damage_source
        result["cutting_beam_level_scaling"] = cutting_beam_level_scaling
    return result


def _isolytic_model(observed: dict[str, Any]) -> dict[str, Any]:
    model = observed.get("isolytic_damage_model", {})
    return model if isinstance(model, dict) else {}


def _resolved_modifier(row: dict[str, Any], role: str, modifier_code: str) -> float:
    ship = row.get(role, {})
    modifiers = ship.get("resolved_modifiers", {}) if isinstance(ship, dict) else {}
    return _number(modifiers.get(modifier_code)) if isinstance(modifiers, dict) else 0.0


def _captured_fleet_modifier(row: dict[str, Any], role: str, modifier_code: str) -> float:
    ship = row.get(role, {})
    modifiers = ship.get("captured_fleet_stats", {}) if isinstance(ship, dict) else {}
    return _number(modifiers.get(modifier_code)) if isinstance(modifiers, dict) else 0.0


def simulate_isolytic_damage(
    row: dict[str, Any],
    *,
    damage_multiplier: float | None = None,
    effective_mitigation: float | None = None,
    mitigation_source: str = "observed",
) -> dict[str, Any]:
    observed = _observed(row)
    model = _isolytic_model(observed)
    normal = observed.get("normal_mitigation", {})
    normal_mitigation = normal if isinstance(normal, dict) else {}
    base_damage = _number(model.get("base_damage", normal_mitigation.get("raw_damage")))
    multiplier = _number(damage_multiplier if damage_multiplier is not None else model.get("damage_multiplier"))
    effective_mitigation_source = "override" if effective_mitigation is not None else mitigation_source
    if effective_mitigation is not None:
        mitigation = _number(effective_mitigation)
    elif mitigation_source == "resolved_808":
        defense = _resolved_modifier(row, "defender", "808")
        mitigation = max(0.0, min(1.0, 1.0 - isolytic_mitigation(isolytic_defense=defense)))
    else:
        mitigation = _number(model.get("effective_mitigation"))
    raw_damage = int(round(base_damage * multiplier))
    damage = int(round(raw_damage * (1.0 - mitigation)))
    mitigated_damage = raw_damage - damage
    observed_damage = _number(observed.get("isolytic_damage", model.get("observed_damage")))
    observed_mitigated = _number(observed.get("mitigated_isolytic_damage", model.get("mitigated_damage")))
    observed_raw = observed_damage + observed_mitigated
    observed_damage_multiplier = observed_raw / base_damage if base_damage else 0.0
    observed_effective_mitigation = observed_mitigated / observed_raw if observed_raw else 0.0
    return {
        "base_damage": _report_number(base_damage),
        "inferred_base_damage": _report_number(_number(model.get("inferred_base_damage", base_damage))),
        "base_damage_gap": _report_number(_number(model.get("base_damage_gap"))),
        "damage_multiplier": multiplier,
        "damage_multiplier_percent": multiplier * 100.0,
        "observed_damage_multiplier": observed_damage_multiplier,
        "effective_mitigation": mitigation,
        "effective_mitigation_source": effective_mitigation_source,
        "observed_effective_mitigation": observed_effective_mitigation,
        "raw_damage": _report_number(float(raw_damage)),
        "damage": _report_number(float(damage)),
        "mitigated_damage": _report_number(float(mitigated_damage)),
        "observed_raw_damage": _report_number(observed_raw),
        "observed_damage": _report_number(observed_damage),
        "observed_mitigated_damage": _report_number(observed_mitigated),
        "errors": {
            "raw_damage": _report_number(float(raw_damage - observed_raw)),
            "damage": _report_number(float(damage - observed_damage)),
            "mitigated_damage": _report_number(float(mitigated_damage - observed_mitigated)),
            "damage_multiplier": multiplier - observed_damage_multiplier,
            "effective_mitigation": mitigation - observed_effective_mitigation,
        },
    }


def _apex_mitigation_from_barrier(apex_barrier: Any) -> float:
    barrier = _number(apex_barrier)
    if barrier <= 1.0:
        return 0.0
    damage_remaining = apex_barrier_damage_reduction(apex_barrier=barrier, apex_shred=0)
    return max(0.0, min(1.0, 1.0 - damage_remaining))


def _required_apex_barrier(apex_mitigation: Any) -> float:
    mitigation = max(0.0, min(0.999999, _number(apex_mitigation)))
    if mitigation <= 0.0:
        return 0.0
    return 10000.0 * mitigation / (1.0 - mitigation)


def simulate_apex_barrier(row: dict[str, Any]) -> dict[str, Any]:
    stages = observed_damage_stages(row)
    damage_before_apex = _number(stages.get("damage_before_apex"))
    observed_mitigated = _number(stages.get("apex_mitigated"))
    observed_mitigation = _number(stages.get("apex_mitigation"))
    barrier = _resolved_modifier(row, "defender", "67001")
    captured_barrier = _captured_fleet_modifier(row, "defender", "67001")
    modeled_mitigation = _apex_mitigation_from_barrier(barrier)
    mitigated_damage = int(round(damage_before_apex * modeled_mitigation))
    required_barrier = _required_apex_barrier(observed_mitigation)
    return {
        "damage_before_apex": _report_number(damage_before_apex),
        "observed_mitigated_damage": _report_number(observed_mitigated),
        "observed_mitigation": observed_mitigation,
        "modeled_barrier": _report_number(barrier),
        "captured_fleet_67001": _report_number(captured_barrier),
        "modeled_mitigation": modeled_mitigation,
        "required_barrier": _report_number(required_barrier),
        "mitigated_damage": _report_number(float(mitigated_damage)),
        "errors": {
            "mitigated_damage": _report_number(float(mitigated_damage - observed_mitigated)),
            "mitigation": modeled_mitigation - observed_mitigation,
            "barrier": barrier - required_barrier,
        },
    }


def _excluded_reason(row: dict[str, Any]) -> str | None:
    observed = _observed(row)
    if not observed.get("hit", True):
        return "miss"
    if _number(observed.get("raw_damage")) <= 0:
        return "missing_raw_damage"
    if observed.get("critical"):
        return "critical"
    if observed.get("triggered_effects"):
        return "triggered_effects"
    return None


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


def evaluate_observed_mitigation_damage_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    excluded_reasons: Counter[str] = Counter()
    simple_simulations = []
    for row in rows:
        reason = _excluded_reason(row)
        if reason is not None:
            excluded_reasons.update([reason])
            continue
        simple_simulations.append(simulate_damage_from_raw(row))

    return {
        "formula": (
            "normal rows: round(raw_damage * (1 - observed_effective_mitigation)), then send "
            "floor(mitigated_damage * shield_mitigation) to active shields and the remainder to hull; "
            "cutting-beam rows: apply 10% level reduction per hostile level above player level when unscaled "
            "damage is available, then bypass shields and mitigation and apply the scaled damage directly to hull"
        ),
        "rows": len(rows),
        "simple_rows": len(simple_simulations),
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
        "simple_metrics": {
            "shield": _metrics([float(row["errors"]["shield"]) for row in simple_simulations]),
            "hull": _metrics([float(row["errors"]["hull"]) for row in simple_simulations]),
            "mitigated_damage": _metrics([float(row["errors"]["mitigated_damage"]) for row in simple_simulations]),
        },
    }


def _isolytic_replay_summary(simulations: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "isolytic_rows": len(simulations),
        "multiplier_percent": _distribution([float(row["damage_multiplier_percent"]) for row in simulations]),
        "base_damage_gap": _distribution([float(row["base_damage_gap"]) for row in simulations]),
        "metrics": {
            "raw_damage": _metrics([float(row["errors"]["raw_damage"]) for row in simulations]),
            "damage": _metrics([float(row["errors"]["damage"]) for row in simulations]),
            "mitigated_damage": _metrics([float(row["errors"]["mitigated_damage"]) for row in simulations]),
            "damage_multiplier": _metrics([float(row["errors"]["damage_multiplier"]) for row in simulations]),
            "effective_mitigation": _metrics([float(row["errors"]["effective_mitigation"]) for row in simulations]),
        },
    }


def evaluate_observed_isolytic_damage_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    simulations = []
    resolved_808_simulations = []
    by_source: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        observed = _observed(row)
        if _number(observed.get("isolytic_damage")) + _number(observed.get("mitigated_isolytic_damage")) <= 0:
            continue
        simulation = simulate_isolytic_damage(row)
        simulations.append(simulation)
        if _resolved_modifier(row, "defender", "808") > 0.0:
            resolved_808_simulations.append(simulate_isolytic_damage(row, mitigation_source="resolved_808"))
        source = str(_isolytic_model(observed).get("source") or "unknown")
        by_source.setdefault(source, []).append(simulation)

    return {
        "formula": (
            "round(observed.normal_mitigation.raw_damage * observed.isolytic_damage_model.damage_multiplier), "
            "then apply observed.isolytic_damage_model.effective_mitigation"
        ),
        "damage_modifier_code": "707",
        "defense_modifier_code": "808",
        "rows": len(rows),
        **_isolytic_replay_summary(simulations),
        "by_source": {
            source: _isolytic_replay_summary(source_simulations)
            for source, source_simulations in sorted(by_source.items())
        },
        "resolved_808_formula": {
            "formula": "isolytic_effective_mitigation = 1 - 1 / (1 + defender.resolved_modifiers[808])",
            **_isolytic_replay_summary(resolved_808_simulations),
        },
    }


def evaluate_observed_apex_barrier_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    simulations = []
    for row in rows:
        stages = observed_damage_stages(row)
        if _number(stages.get("apex_mitigated")) <= 0:
            continue
        simulations.append(simulate_apex_barrier(row))

    return {
        "formula": (
            "apex_mitigation = 1 - 10000 / (10000 + defender.resolved_modifiers[67001]); "
            "predicted mitigated apex damage = round(observed damage_before_apex * apex_mitigation)"
        ),
        "barrier_modifier_code": "67001",
        "rows": len(rows),
        "apex_rows": len(simulations),
        "rows_with_modeled_barrier": sum(1 for row in simulations if _number(row["modeled_barrier"]) > 1.0),
        "rows_with_captured_67001_presence_flag": sum(
            1 for row in simulations if _number(row["captured_fleet_67001"]) == 1.0
        ),
        "rows_with_unresolved_captured_67001_presence_flag": sum(
            1
            for row in simulations
            if _number(row["captured_fleet_67001"]) == 1.0 and _number(row["modeled_barrier"]) <= 1.0
        ),
        "observed_mitigation": _distribution([float(row["observed_mitigation"]) for row in simulations]),
        "modeled_mitigation": _distribution([float(row["modeled_mitigation"]) for row in simulations]),
        "required_barrier": _distribution([float(row["required_barrier"]) for row in simulations]),
        "modeled_barrier": _distribution([float(row["modeled_barrier"]) for row in simulations]),
        "metrics": {
            "mitigated_damage": _metrics([float(row["errors"]["mitigated_damage"]) for row in simulations]),
            "mitigation": _metrics([float(row["errors"]["mitigation"]) for row in simulations]),
            "barrier": _metrics([float(row["errors"]["barrier"]) for row in simulations]),
        },
    }
