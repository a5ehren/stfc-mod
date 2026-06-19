from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from .mechanics import (
    HULL_ARMADA,
    HULL_BATTLESHIP,
    HULL_DESTROYER,
    HULL_EXPLORER,
    HULL_INTERCEPTOR,
    HULL_SURVEY,
    combat_triangle_mitigation,
)
from .mitigation_analysis import _mitigation_fit_excluded_reason, _number, _row_normal_mitigation
from .mitigation_formula import combat_triangle_features, predict_combat_triangle_mitigation


COMPOSITIONS = (
    "weighted_product",
    "weighted_sum",
    "weighted_power_product",
    "active_layer_weighted_sum",
    "active_layer_weighted_product",
    "active_layer_weighted_product_unscaled",
)
HULL_TYPES = (
    HULL_BATTLESHIP,
    HULL_EXPLORER,
    HULL_DESTROYER,
    HULL_INTERCEPTOR,
    HULL_SURVEY,
    HULL_ARMADA,
)
DEFENDER_STATS = {
    "armor": "-3",
    "shield": "-2",
    "dodge": "11",
}
LOOKUP_DEFENDER_BASE_STATS = ("armor_plating", "shield_absorption", "dodge")
CREW_CONTAMINATED_PLAYER_HULL_IDS = {
    "2057434885": "Newton_LIVE",
}


def _predict_combat_triangle(row: dict[str, Any], **kwargs: Any) -> float:
    return predict_combat_triangle_mitigation(row, include_apex_barrier=True, **kwargs)


def _read_observations(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _report_number(value: float) -> int | float:
    if abs(value) < 1e-12:
        return 0
    return int(value) if value.is_integer() else value


def _target(row: dict[str, Any]) -> float:
    return _number(_row_normal_mitigation(row).get("effective_mitigation"))


def _apex_barrier(row: dict[str, Any]) -> float:
    normal = _row_normal_mitigation(row)
    return _number(normal.get("included_mitigated_apex_barrier"))


def _with_client_lookup_defender_base(row: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(row)
    defender = candidate.get("defender", {})
    static_ship = defender.get("static_ship", {}) if isinstance(defender, dict) else {}
    base_stats = static_ship.get("base_stats", {}) if isinstance(static_ship, dict) else {}
    lookup_sources = static_ship.get("client_ship_stat_lookup_sources", {}) if isinstance(static_ship, dict) else {}
    if not isinstance(base_stats, dict) or not isinstance(lookup_sources, dict):
        return candidate

    for stat_name in LOOKUP_DEFENDER_BASE_STATS:
        source = lookup_sources.get(stat_name)
        if not isinstance(source, dict):
            continue
        if source.get("status") == "found" and source.get("value") is not None:
            base_stats[stat_name] = source["value"]
    return candidate


def _metrics(rows: list[dict[str, Any]], predict: Callable[[dict[str, Any]], float]) -> dict[str, int | float]:
    errors = [predict(row) - _target(row) for row in rows]
    if not errors:
        return {"count": 0, "mae": 0, "bias": 0, "max_abs_error": 0}
    return {
        "count": len(errors),
        "mae": _report_number(sum(abs(error) for error in errors) / len(errors)),
        "bias": _report_number(sum(errors) / len(errors)),
        "max_abs_error": _report_number(max(abs(error) for error in errors)),
    }


def _distribution(values: list[float]) -> dict[str, int | float]:
    if not values:
        return {"count": 0, "min": 0, "max": 0, "mean": 0}
    return {
        "count": len(values),
        "min": _report_number(min(values)),
        "max": _report_number(max(values)),
        "mean": _report_number(sum(values) / len(values)),
    }


def _player_ship(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("attacker_side") == "player":
        return row.get("attacker", {}) if isinstance(row.get("attacker"), dict) else {}
    return row.get("defender", {}) if isinstance(row.get("defender"), dict) else {}


def _player_hull(row: dict[str, Any]) -> dict[str, Any]:
    ship = _player_ship(row)
    static_ship = ship.get("static_ship", {}) if isinstance(ship, dict) else {}
    hull = static_ship.get("hull", {}) if isinstance(static_ship, dict) else {}
    return hull if isinstance(hull, dict) else {}


def _player_hull_id(row: dict[str, Any]) -> str:
    return str(_player_hull(row).get("id") or "")


def _player_hull_key(row: dict[str, Any]) -> str:
    hull = _player_hull(row)
    return f"{hull.get('name') or 'unknown'}:{hull.get('id') or 'unknown'}"


def _battle_type_key(row: dict[str, Any]) -> str:
    return str(row.get("battle_type_name") or row.get("battle_type") or "unknown")


def _hostile_id_key(row: dict[str, Any]) -> str:
    return str(row.get("hostile_id") or "unknown")


def _modeled_captured_ratios(rows: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    ratios: dict[str, list[float]] = {name: [] for name in DEFENDER_STATS}
    for row in rows:
        features = combat_triangle_features(row, stat_source="static_player_max_buffs")
        stat_inputs = features.get("stat_inputs", {})
        defender = row.get("defender", {}) if isinstance(row.get("defender"), dict) else {}
        captured = defender.get("captured_stats", {}) if isinstance(defender, dict) else {}
        for name, stat_code in DEFENDER_STATS.items():
            captured_value = _number(captured.get(stat_code) if isinstance(captured, dict) else 0)
            modeled_value = _number(stat_inputs.get(name, {}).get("defense") if isinstance(stat_inputs, dict) else 0)
            if captured_value:
                ratios[name].append(modeled_value / captured_value)
    return {name: _distribution(values) for name, values in ratios.items()}


def _component_means(rows: list[dict[str, Any]]) -> dict[str, int | float]:
    components: dict[str, list[float]] = {name: [] for name in DEFENDER_STATS}
    for row in rows:
        features = combat_triangle_features(row, stat_source="static_player_max_buffs")
        row_components = features.get("components", {})
        for name in components:
            components[name].append(_number(row_components.get(name) if isinstance(row_components, dict) else 0))
    return {name: _report_number(sum(values) / len(values)) if values else 0 for name, values in components.items()}


def _mean_prediction(rows: list[dict[str, Any]], predict: Callable[[dict[str, Any]], float]) -> int | float:
    if not rows:
        return 0
    return _report_number(sum(predict(row) for row in rows) / len(rows))


def _hull_type_prediction(row: dict[str, Any], hull_type: str) -> float:
    features = combat_triangle_features(row, stat_source="static_player_max_buffs")
    stat_inputs = features["stat_inputs"]
    return combat_triangle_mitigation(
        armor=stat_inputs["armor"]["defense"],
        shield=stat_inputs["shield"]["defense"],
        dodge=stat_inputs["dodge"]["defense"],
        armor_piercing=stat_inputs["armor"]["piercing"],
        shield_piercing=stat_inputs["shield"]["piercing"],
        accuracy=stat_inputs["dodge"]["piercing"],
        defender_hull_type=hull_type,
    )


def _hull_type_sensitivity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for hull_type in HULL_TYPES:
        candidates.append(
            {
                "hull_type": hull_type,
                "metrics": _metrics(rows, lambda row, hull_type=hull_type: _hull_type_prediction(row, hull_type)),
            }
        )
    return sorted(
        candidates,
        key=lambda row: (
            float(row["metrics"]["mae"]),
            float(row["metrics"]["max_abs_error"]),
            row["hull_type"],
        ),
    )


def _effect_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    formula_effect = row.get("formula_effect", {}) if isinstance(row.get("formula_effect"), dict) else {}
    return (
        str(row.get("modifierCode") or "unknown"),
        str(row.get("targetCode") or "unknown"),
        str(row.get("triggerCode") or "unknown"),
        str(row.get("buffOperation") or row.get("op") or "unknown"),
        str(row.get("application_status") or "unknown"),
        str(formula_effect.get("formula_stage") or "unknown"),
    )


def _counter_rows(counter: dict[tuple[str, str, str, str, str, str], int]) -> list[dict[str, Any]]:
    return [
        {
            "modifierCode": key[0],
            "targetCode": key[1],
            "triggerCode": key[2],
            "operation": key[3],
            "status": key[4],
            "formula_stage": key[5],
            "count": count,
        }
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _ship_bonus_summary(rows: list[dict[str, Any]], side: str) -> dict[str, Any]:
    applied: dict[tuple[str, str, str, str, str, str], int] = defaultdict(int)
    opponent: dict[tuple[str, str, str, str, str, str], int] = defaultdict(int)
    skipped: dict[tuple[str, str, str, str, str, str], int] = defaultdict(int)
    loot: dict[tuple[str, str, str, str, str, str], int] = defaultdict(int)
    for row in rows:
        ship = row.get(side, {}) if isinstance(row.get(side), dict) else {}
        effects = ship.get("static_ship_bonus_effects", {}) if isinstance(ship, dict) else {}
        if not isinstance(effects, dict):
            continue
        for effect in effects.get("applied_modifiers", []) or []:
            if isinstance(effect, dict):
                applied[_effect_key(effect)] += 1
        for effect in effects.get("opponent_modifiers", []) or []:
            if isinstance(effect, dict):
                opponent[_effect_key(effect)] += 1
        for effect in effects.get("skipped_modifiers", []) or []:
            if isinstance(effect, dict):
                skipped[_effect_key(effect)] += 1
        for effect in effects.get("loot_bonuses", []) or []:
            if isinstance(effect, dict):
                loot[_effect_key(effect)] += 1
    return {
        "applied_modifiers": _counter_rows(applied),
        "opponent_modifiers": _counter_rows(opponent),
        "skipped_modifiers": _counter_rows(skipped),
        "loot_bonuses": _counter_rows(loot),
    }


def _officer_activation_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    activations: dict[tuple[str, str, str, str, str, str], int] = defaultdict(int)
    for row in rows:
        observed = row.get("observed", {}) if isinstance(row.get("observed"), dict) else {}
        for activation in observed.get("officer_activations", []) or []:
            if isinstance(activation, dict):
                activations[_effect_key(activation)] += 1
    return _counter_rows(activations)


def _group_summary(name: str, rows: list[dict[str, Any]], *, total_abs_error: float) -> dict[str, Any]:
    static_metrics = _metrics(
        rows,
        lambda row: _predict_combat_triangle(row, stat_source="static_player_max_buffs"),
    )
    captured_metrics = _metrics(
        rows,
        lambda row: _predict_combat_triangle(row, stat_source="captured_live"),
    )
    lookup_metrics = _metrics(
        rows,
        lambda row: _predict_combat_triangle(
            _with_client_lookup_defender_base(row),
            stat_source="static_player_max_buffs",
        ),
    )
    target_values = [_target(row) for row in rows]
    abs_error = float(static_metrics["mae"]) * len(rows)
    hull = _player_hull(rows[0]) if rows else {}
    return {
        "key": name,
        "count": len(rows),
        "player_hull_name": hull.get("name"),
        "player_hull_id": str(hull.get("id") or ""),
        "player_hull_type": hull.get("type"),
        "target_mean": _report_number(sum(target_values) / len(target_values)) if target_values else 0,
        "static_player_max_buffs_prediction_mean": _mean_prediction(
            rows,
            lambda row: _predict_combat_triangle(row, stat_source="static_player_max_buffs"),
        ),
        "client_lookup_defender_base_prediction_mean": _mean_prediction(
            rows,
            lambda row: _predict_combat_triangle(
                _with_client_lookup_defender_base(row),
                stat_source="static_player_max_buffs",
            ),
        ),
        "captured_live_prediction_mean": _mean_prediction(
            rows,
            lambda row: _predict_combat_triangle(row, stat_source="captured_live"),
        ),
        "static_player_max_buffs_metrics": static_metrics,
        "client_lookup_defender_base_metrics": lookup_metrics,
        "captured_live_metrics": captured_metrics,
        "apex_barrier_rows": sum(1 for row in rows if _apex_barrier(row) > 0),
        "apex_barrier": _distribution([_apex_barrier(row) for row in rows if _apex_barrier(row) > 0]),
        "absolute_error_share": _report_number(abs_error / total_abs_error) if total_abs_error else 0,
        "component_means": _component_means(rows),
        "modeled_to_captured_defender_stat_ratios": _modeled_captured_ratios(rows),
        "static_ship_bonus_effects": {
            "attacker": _ship_bonus_summary(rows, "attacker"),
            "defender": _ship_bonus_summary(rows, "defender"),
        },
        "observed_officer_activations": _officer_activation_summary(rows),
        "hull_type_sensitivity": _hull_type_sensitivity(rows),
    }


def _groups(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)
    return dict(groups)


def _hostile_scope_summary(
    rows: list[dict[str, Any]],
    *,
    min_group_count: int,
) -> dict[str, Any]:
    static_predict = lambda row: _predict_combat_triangle(row, stat_source="static_player_max_buffs")
    total_abs_error = sum(abs(static_predict(row) - _target(row)) for row in rows)
    by_player_hull = [
        _group_summary(key, group_rows, total_abs_error=total_abs_error)
        for key, group_rows in _groups(rows, _player_hull_key).items()
        if len(group_rows) >= min_group_count
    ]
    by_battle_type = [
        {
            "key": key,
            "count": len(group_rows),
            "metrics": _metrics(group_rows, static_predict),
            "absolute_error_share": _report_number(
                sum(abs(static_predict(row) - _target(row)) for row in group_rows) / total_abs_error
            )
            if total_abs_error
            else 0,
        }
        for key, group_rows in _groups(rows, _battle_type_key).items()
        if len(group_rows) >= min_group_count
    ]
    by_hostile_id = [
        {
            "key": key,
            "count": len(group_rows),
            "metrics": _metrics(group_rows, static_predict),
            "target_mean": _report_number(sum(_target(row) for row in group_rows) / len(group_rows)),
            "static_player_max_buffs_prediction_mean": _mean_prediction(group_rows, static_predict),
            "absolute_error_share": _report_number(
                sum(abs(static_predict(row) - _target(row)) for row in group_rows) / total_abs_error
            )
            if total_abs_error
            else 0,
        }
        for key, group_rows in _groups(rows, _hostile_id_key).items()
        if len(group_rows) >= min_group_count
    ]
    return {
        "hostile_shot_rows": len(rows),
        "overall": {
            "static_player_max_buffs": _metrics(rows, static_predict),
            "client_lookup_defender_base": _metrics(
                rows,
                lambda row: _predict_combat_triangle(
                    _with_client_lookup_defender_base(row),
                    stat_source="static_player_max_buffs",
                ),
            ),
            "captured_live": _metrics(
                rows,
                lambda row: _predict_combat_triangle(row, stat_source="captured_live"),
            ),
            "static_base": _metrics(
                rows,
                lambda row: _predict_combat_triangle(row, stat_source="static_base"),
            ),
        },
        "by_player_hull": sorted(
            by_player_hull,
            key=lambda row: (-float(row["absolute_error_share"]), row["key"]),
        ),
        "by_battle_type": sorted(
            by_battle_type,
            key=lambda row: (-float(row["absolute_error_share"]), row["key"]),
        ),
        "by_hostile_id": sorted(
            by_hostile_id,
            key=lambda row: (-float(row["absolute_error_share"]), row["key"]),
        ),
    }


def build_defender_diagnostics(
    *,
    observations_path: Path,
    min_group_count: int = 20,
) -> dict[str, Any]:
    raw_rows = _read_observations(observations_path)
    usable_rows = [row for row in raw_rows if _mitigation_fit_excluded_reason(row) is None]
    hostile_rows = [row for row in usable_rows if row.get("attacker_side") == "hostile"]
    player_rows = [row for row in usable_rows if row.get("attacker_side") == "player"]
    clean_specialty_rows = [
        row for row in hostile_rows if _player_hull_id(row) not in CREW_CONTAMINATED_PLAYER_HULL_IDS
    ]
    static_predict = lambda row: _predict_combat_triangle(row, stat_source="static_player_max_buffs")

    composition_metrics = {
        composition: _metrics(
            hostile_rows,
            lambda row, composition=composition: _predict_combat_triangle(
                row,
                stat_source="static_player_max_buffs",
                composition=composition,
            ),
        )
        for composition in COMPOSITIONS
    }
    all_hostile_summary = _hostile_scope_summary(hostile_rows, min_group_count=min_group_count)

    return {
        "observations_path": str(observations_path),
        "scope": "usable hostile-shot rows where player is defender",
        "raw_rows": len(raw_rows),
        "usable_rows": len(usable_rows),
        "hostile_shot_rows": len(hostile_rows),
        "player_shot_rows": len(player_rows),
        "overall": all_hostile_summary["overall"],
        "composition_metrics": composition_metrics,
        "by_player_hull": all_hostile_summary["by_player_hull"],
        "by_battle_type": all_hostile_summary["by_battle_type"],
        "by_hostile_id": all_hostile_summary["by_hostile_id"],
        "clean_specialty_calibration": {
            "scope": "hostile-shot player-defender rows excluding player hulls known to include crew effects",
            "excluded_player_hulls": [
                {"player_hull_id": hull_id, "player_hull_name": name}
                for hull_id, name in sorted(CREW_CONTAMINATED_PLAYER_HULL_IDS.items())
            ],
            **_hostile_scope_summary(clean_specialty_rows, min_group_count=min_group_count),
        },
    }


def write_defender_diagnostics(*, report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
