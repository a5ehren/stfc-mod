from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from .apex_sources import build_apex_source_index, evaluate_apex_source_candidates
from .battle_enums import battle_type_label, is_chain_shot_battle_type, is_cutting_beam_battle_type
from .damage_pipeline import observed_damage_stages, weapon_damage_diagnostics
from .damage_simulation import (
    evaluate_observed_apex_barrier_replay,
    evaluate_observed_isolytic_damage_replay,
    evaluate_observed_mitigation_damage_replay,
)
from .formula_effects import FORMULA_STAGE_REGISTRY
from .mitigation_formula import (
    BASIC_LIVE_MITIGATION_FEATURES,
    BASIC_LIVE_MITIGATION_WEIGHTS,
    COMBAT_TRIANGLE_COMPOSITIONS,
    COMBAT_TRIANGLE_STAT_SOURCES,
    COMBAT_TRIANGLE_STAT_ROLE_ORIENTATIONS,
    COMBAT_TRIANGLE_WEIGHTS,
    _apex_barrier_stage_mitigation,
    _combat_triangle_component,
    _combine_mitigation_stages,
    _clamp_mitigation,
    combat_triangle_features,
    deterministic_basic_live_features,
    predict_combat_triangle_mitigation,
    predict_basic_live_mitigation,
)
from .mitigation_targets import normal_effective_mitigation, normal_mitigation_from_observed


RATIO_FEATURES = ("dodge_ratio", "plating_ratio", "absorption_ratio")
BASIC_LIVE_FEATURES = ("live_dodge_ratio", "live_plating_ratio", "live_absorption_ratio")
COMBAT_TRIANGLE_CALIBRATION_FEATURES = ("combat_triangle_prediction",)
SIMULATOR_TARGET_MAE = 0.05
SIMULATOR_ELIGIBLE_INPUT_CLASSES = ("static_composable", "synced_profile")
BROAD_FORMULA_TARGET_CLASSES = ("standard_hostile", "armada", "wave_defense")
BROAD_CONTEXT_CORRECTION_MIN_GROUP_ROWS = 100
BROAD_SYNCED_LINEAR_MIN_HULL_ROWS = 100
BROAD_SYNCED_LINEAR_REGULARIZATION = 1e-4
BROAD_SYNCED_LINEAR_CV_FOLDS = 5
EXPANDED_FEATURES = (
    *RATIO_FEATURES,
    "attacker_is_player",
    "critical",
    "weapon_shots",
    "weapon_crit_modifier",
    "weapon_accuracy_log",
    "weapon_penetration_log",
    "weapon_modulation_log",
    "weapon_damage_midpoint_log",
    "weapon_damage_per_shot_log",
    "weapon_damage_spread_ratio",
    "isolytic_triggered",
    "officer_triggered",
    "attacker_cloaking_ability",
    "defender_cloaking_ability",
    "hostile_id_mar_prefix",
    "hostile_id_npc_prefix",
    "apex_barrier_ratio",
    "defender_shield_mitigation",
    "attacker_hull_grade",
    "defender_hull_grade",
    "same_hull_type",
    "attacker_hull_explorer",
    "attacker_hull_battleship",
    "attacker_hull_interceptor",
    "attacker_hull_survey",
    "defender_hull_explorer",
    "defender_hull_battleship",
    "defender_hull_interceptor",
    "defender_hull_survey",
)
OVERKILL_BASE_DAMAGE_GAP_TOLERANCE = 1.0
# These fits are diagnostic guardrails, not model training. The full capture set
# has hundreds of battles, and refitting every diagnostic model for too many
# holdouts dominates report runtime.
LEAVE_ONE_GROUP_OUT_MAX_GROUPS = 8
ANALYSIS_SCOPE = {
    "name": "1v1_pve",
    "description": (
        "Fit the current mitigation models on simple 1v1 PvE rows. Armada rows stay in observations "
        "but are excluded from this equation until armadas get a separate model. Cutting-beam and chain-shot "
        "rows are special ability damage, so they are excluded from the normal weapon-mitigation equation."
    ),
    "excluded_reasons": [
        "armada_battle_scope",
        "cutting_beam_bypasses_mitigation",
        "chain_shot_special_damage",
        "normal_damage_capped_by_isolytic_overkill",
    ],
}
BROAD_FORMULA_SCOPE = {
    "name": "synced_standard_armada_wave",
    "description": (
        "Evaluate formula candidates on standard hostile, armada, and wave-defense rows using data that is present in "
        "synced battle journals plus synced/static profile state. Cutting-beam, chain-shot, missing-normal-damage, and "
        "shot-count-stage rows are reported as exclusions until those stages have separate formulas."
    ),
    "target_battle_classes": list(BROAD_FORMULA_TARGET_CLASSES),
    "excluded_reasons": [
        "outside_target_battle_class",
        "cutting_beam_bypasses_mitigation",
        "missing_normal_raw_damage",
        "normal_damage_capped_by_isolytic_overkill",
    ],
}

IDEAL_HOSTILE_MATCHUPS = (
    ("voyager_vs_hirogen", ("voyager",), ("hirogen",)),
    ("franklin_vs_swarm", ("franklin",), ("swarm", "swm_")),
    ("stella_vs_eclipse", ("stella", "mudd"), ("eclipse", "ecp")),
    ("monaveen_vs_rogue_ai", ("monaveen",), ("rogueai", "rogue_ai", "rai_")),
    ("reliant_vs_wok", ("reliant",), ("wok",)),
)
FLEET_ATTRIBUTE_FACTOR_CODES = ("-7", "-8", "-9", "-10", "-11", "-12", "-13", "-15", "-16", "-17", "-18")
FLEET_RATING_FACTOR_FIELDS = (
    "fleet_grade",
    "offense_rating",
    "defense_rating",
    "health_rating",
    "deflector_rating",
    "sensor_rating",
    "officer_rating",
    "forbidden_tech_rating",
)

FEATURE_DESCRIPTIONS = {
    "dodge_ratio": "defender dodge / (weapon accuracy + defender dodge)",
    "plating_ratio": "defender armor plating / (weapon penetration + defender armor plating)",
    "absorption_ratio": "defender shield absorption / (weapon modulation + defender shield absorption)",
    "live_dodge_ratio": "defender dodge / (attacker captured ModAccuracy + defender dodge)",
    "live_plating_ratio": "defender plating / (attacker captured ModArmorPiercing + defender plating)",
    "live_absorption_ratio": (
        "defender absorption / (attacker captured ModShieldPiercing + defender absorption), "
        "or 0 when defender pre-shot shield HP is 0"
    ),
    "combat_triangle_prediction": "deterministic combat-triangle mitigation prediction before calibration",
    "attacker_is_player": "1 when the attacking ship is the player ship, else 0",
    "critical": "1 when the observed attack crits, else 0",
    "weapon_shots": "static weapon shot count",
    "weapon_crit_modifier": "static weapon critical damage modifier",
    "weapon_accuracy_log": "natural log of one plus static weapon accuracy",
    "weapon_penetration_log": "natural log of one plus static weapon penetration",
    "weapon_modulation_log": "natural log of one plus static weapon modulation",
    "weapon_damage_midpoint_log": "natural log of one plus the midpoint between static minimum and maximum weapon damage",
    "weapon_damage_per_shot_log": (
        "natural log of one plus static weapon damage midpoint divided by static weapon shot count"
    ),
    "weapon_damage_spread_ratio": "(maximum static weapon damage - minimum static weapon damage) / maximum static weapon damage",
    "isolytic_triggered": "1 when the captured attack lists an isolytic triggered effect, else 0",
    "officer_triggered": "1 when the captured attack lists an officer triggered effect, else 0",
    "attacker_cloaking_ability": "1 when the static attacker hull exposes an activated cloaking ability",
    "defender_cloaking_ability": "1 when the static defender hull exposes an activated cloaking ability",
    "hostile_id_mar_prefix": "1 when the hostile encounter id starts with mar_",
    "hostile_id_npc_prefix": "1 when the hostile encounter id starts with npc_",
    "apex_barrier_ratio": "captured mitigated apex barrier damage divided by captured raw damage",
    "defender_shield_mitigation": "static defender base shield mitigation value",
    "attacker_hull_grade": "static attacker hull grade",
    "defender_hull_grade": "static defender hull grade",
    "same_hull_type": "1 when static attacker and defender hull types match, else 0",
    "attacker_hull_explorer": "1 when the static attacker hull type is Explorer, else 0",
    "attacker_hull_battleship": "1 when the static attacker hull type is Battleship, else 0",
    "attacker_hull_interceptor": "1 when the static attacker hull type is Interceptor, else 0",
    "attacker_hull_survey": "1 when the static attacker hull type is Survey, else 0",
    "defender_hull_explorer": "1 when the static defender hull type is Explorer, else 0",
    "defender_hull_battleship": "1 when the static defender hull type is Battleship, else 0",
    "defender_hull_interceptor": "1 when the static defender hull type is Interceptor, else 0",
    "defender_hull_survey": "1 when the static defender hull type is Survey, else 0",
}


def _read_observations(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _report_number(value: float) -> int | float:
    if abs(value) < 1e-9:
        return 0
    return int(value) if value.is_integer() else value


def _ratio(defender_value: Any, attacker_value: Any) -> float:
    defender = _number(defender_value)
    attacker = _number(attacker_value)
    denominator = defender + attacker
    if denominator == 0:
        return 0.0
    return defender / denominator


def _flag(value: bool) -> float:
    return 1.0 if value else 0.0


def _nested_dict(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return {}
        value = value.get(key, {})
    return value if isinstance(value, dict) else {}


def _hull_type(row: dict[str, Any], side: str) -> str:
    return str(_nested_dict(row, side, "static_ship", "hull").get("type") or "")


def _hull_label(row: dict[str, Any], side: str) -> str:
    ship = row.get(side, {})
    hull = _nested_dict(row, side, "static_ship", "hull")
    hull_id = str(hull.get("id") or (ship.get("hull_id") if isinstance(ship, dict) else "") or "unknown")
    hull_name = str(hull.get("name") or hull.get("id_str") or hull_id)
    return f"{hull_id}:{hull_name}"


def _hull_search_text(row: dict[str, Any], side: str) -> str:
    hull = _nested_dict(row, side, "static_ship", "hull")
    return " ".join(
        str(value or "").lower()
        for value in (
            hull.get("id"),
            hull.get("name"),
            hull.get("id_str"),
        )
    )


def _has_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _ideal_hostile_matchup_keys(row: dict[str, Any]) -> list[str]:
    attacker_text = _hull_search_text(row, "attacker")
    defender_text = _hull_search_text(row, "defender")
    keys = []
    for label, ship_tokens, hostile_tokens in IDEAL_HOSTILE_MATCHUPS:
        attacker_is_ship = _has_any_token(attacker_text, ship_tokens)
        attacker_is_hostile = _has_any_token(attacker_text, hostile_tokens)
        defender_is_ship = _has_any_token(defender_text, ship_tokens)
        defender_is_hostile = _has_any_token(defender_text, hostile_tokens)
        if attacker_is_ship and defender_is_hostile:
            keys.append(f"{label}:ship_attacking_ideal_hostile")
        if attacker_is_hostile and defender_is_ship:
            keys.append(f"{label}:ideal_hostile_attacking_ship")
    return keys or ["none"]


def _battle_formula_class(row: dict[str, Any]) -> str | None:
    if _is_armada_scope(row):
        return "armada"
    if row.get("battle_type") in {5, 6}:
        return "wave_defense"
    if "wavedefense" in _hull_search_text(row, "attacker") or "wavedefense" in _hull_search_text(row, "defender"):
        return "wave_defense"
    if row.get("battle_type") == 2:
        return "standard_hostile"
    return None


def _broad_formula_excluded_reason(row: dict[str, Any]) -> str | None:
    if _battle_formula_class(row) not in BROAD_FORMULA_TARGET_CLASSES:
        return "outside_target_battle_class"
    if is_cutting_beam_battle_type(row.get("battle_type")):
        return "cutting_beam_bypasses_mitigation"
    if not row.get("observed", {}).get("hit", True):
        return "miss"
    normal_mitigation = _row_normal_mitigation(row)
    if _number(normal_mitigation.get("raw_damage")) <= 0:
        return "missing_normal_raw_damage"
    if (
        "isolytic" in row.get("observed", {}).get("triggered_effects", [])
        and _number(normal_mitigation.get("observed_damage")) <= 0
        and _number(normal_mitigation.get("mitigated_damage")) > 0
    ):
        return "normal_damage_capped_by_isolytic_overkill"
    return None


def _broad_formula_rows(raw_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, dict[str, int]]]:
    rows = []
    raw_counts = Counter()
    excluded: dict[str, Counter[str]] = {battle_class: Counter() for battle_class in BROAD_FORMULA_TARGET_CLASSES}
    for row in raw_rows:
        battle_class = _battle_formula_class(row)
        if battle_class in BROAD_FORMULA_TARGET_CLASSES:
            raw_counts[battle_class] += 1
        reason = _broad_formula_excluded_reason(row)
        if reason is None:
            rows.append(row)
        elif battle_class in BROAD_FORMULA_TARGET_CLASSES:
            excluded[battle_class][reason] += 1
    return (
        rows,
        {battle_class: raw_counts[battle_class] for battle_class in BROAD_FORMULA_TARGET_CLASSES},
        {
            battle_class: dict(sorted(reason_counts.items()))
            for battle_class, reason_counts in excluded.items()
            if reason_counts
        },
    )


def _synced_context_residual_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _battle_formula_class(row) or "other",
        str(row.get("attacker_side") or "unknown"),
        _hull_label(row, "attacker"),
        _hull_label(row, "defender"),
    )


def _synced_context_residual_key_string(row: dict[str, Any]) -> str:
    return " | ".join(_synced_context_residual_key(row))


def _fit_synced_context_residual_model(
    rows: list[dict[str, Any]],
    base_predict: Callable[[dict[str, Any]], float],
    *,
    min_group_rows: int = BROAD_CONTEXT_CORRECTION_MIN_GROUP_ROWS,
) -> dict[str, Any]:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[_synced_context_residual_key_string(row)].append(base_predict(row) - _target(row))

    corrections = {}
    for key, residuals in sorted(groups.items()):
        if len(residuals) < min_group_rows:
            continue
        parts = key.split(" | ", 3)
        corrections[key] = {
            "battle_class": parts[0],
            "attacker_side": parts[1],
            "attacker_hull": parts[2],
            "defender_hull": parts[3],
            "rows": len(residuals),
            "residual_bias": _mean(residuals),
        }
    return {
        "base_formula": "combat_triangle_static_player_max_buffs_formula",
        "formula": (
            "clamp(base_formula - mean_residual[battle_class, attacker_side, attacker_hull, defender_hull], "
            "0, 0.95)"
        ),
        "correction_key": ["battle_class", "attacker_side", "attacker_hull", "defender_hull"],
        "min_group_rows": min_group_rows,
        "fallback_residual_bias": 0.0,
        "groups_seen": len(groups),
        "corrected_groups": len(corrections),
        "corrections": corrections,
    }


def _predict_synced_context_residual_model(
    row: dict[str, Any],
    *,
    model: dict[str, Any],
    base_predict: Callable[[dict[str, Any]], float],
) -> float:
    correction = model["corrections"].get(_synced_context_residual_key_string(row), {})
    residual_bias = _number(correction.get("residual_bias", model["fallback_residual_bias"]))
    return _clamp_prediction(base_predict(row) - residual_bias)


def _metrics_by_battle_class(
    rows: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], float],
) -> dict[str, dict[str, float | int]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        battle_class = _battle_formula_class(row)
        if battle_class in BROAD_FORMULA_TARGET_CLASSES:
            groups[battle_class].append(row)
    return {battle_class: _metrics(groups[battle_class], predict) for battle_class in BROAD_FORMULA_TARGET_CLASSES}


def _broad_candidate_metrics(
    rows: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], float],
) -> dict[str, Any]:
    return {
        "overall": _metrics(rows, predict),
        "by_battle_class": _metrics_by_battle_class(rows, predict),
    }


def _synced_context_residual_leave_one_battle_out_metrics(
    rows: list[dict[str, Any]],
    base_predict: Callable[[dict[str, Any]], float],
    *,
    min_group_rows: int,
) -> dict[str, Any]:
    group_totals: dict[str, dict[str, float | int]] = defaultdict(lambda: {"rows": 0, "residual_sum": 0.0})
    battle_group_totals: dict[str, dict[str, dict[str, float | int]]] = defaultdict(
        lambda: defaultdict(lambda: {"rows": 0, "residual_sum": 0.0})
    )
    for row in rows:
        key = _synced_context_residual_key_string(row)
        battle_id = str(row.get("battle_id") or "unknown")
        residual = base_predict(row) - _target(row)
        group_totals[key]["rows"] = int(group_totals[key]["rows"]) + 1
        group_totals[key]["residual_sum"] = float(group_totals[key]["residual_sum"]) + residual
        battle_group_totals[battle_id][key]["rows"] = int(battle_group_totals[battle_id][key]["rows"]) + 1
        battle_group_totals[battle_id][key]["residual_sum"] = (
            float(battle_group_totals[battle_id][key]["residual_sum"]) + residual
        )

    errors_by_class: dict[str, list[float]] = defaultdict(list)
    all_errors = []
    for row in rows:
        key = _synced_context_residual_key_string(row)
        battle_id = str(row.get("battle_id") or "unknown")
        total = group_totals[key]
        held_out = battle_group_totals[battle_id][key]
        train_rows = int(total["rows"]) - int(held_out["rows"])
        train_residual_sum = float(total["residual_sum"]) - float(held_out["residual_sum"])
        correction = train_residual_sum / train_rows if train_rows >= min_group_rows else 0.0
        error = _clamp_prediction(base_predict(row) - correction) - _target(row)
        all_errors.append(error)
        battle_class = _battle_formula_class(row)
        if battle_class in BROAD_FORMULA_TARGET_CLASSES:
            errors_by_class[battle_class].append(error)

    return {
        "group": "battle_id",
        "groups": len({str(row.get("battle_id") or "unknown") for row in rows}),
        "sampling": "all_groups",
        "overall": _metrics_from_errors(all_errors),
        "by_battle_class": {
            battle_class: _metrics_from_errors(errors_by_class[battle_class])
            for battle_class in BROAD_FORMULA_TARGET_CLASSES
        },
    }


def _feature_key(prefix: str, value: Any) -> str:
    return f"{prefix}={value}"


def _add_indicator(features: dict[str, float], prefix: str, value: Any) -> None:
    features[_feature_key(prefix, value)] = 1.0


def _common_hull_labels(rows: list[dict[str, Any]], role: str, *, min_rows: int) -> tuple[str, ...]:
    counts = Counter(_hull_label(row, role) for row in rows)
    return tuple(sorted(label for label, count in counts.items() if count >= min_rows))


def _supported_hull_label(row: dict[str, Any], role: str, labels: tuple[str, ...]) -> str:
    label = _hull_label(row, role)
    return label if label in labels else "rare"


def _synced_linear_features(
    row: dict[str, Any],
    *,
    base_predict: Callable[[dict[str, Any]], float],
    attacker_hulls: tuple[str, ...],
    defender_hulls: tuple[str, ...],
) -> dict[str, float]:
    base_prediction = base_predict(row)
    features = {
        "intercept": 1.0,
        "base_prediction": base_prediction,
        "base_prediction_squared": base_prediction * base_prediction,
        "shield_active_before_shot": _flag(_shield_active_before_shot(row)),
    }
    _add_indicator(features, "battle_class", _battle_formula_class(row) or "other")
    _add_indicator(features, "battle_type", row.get("battle_type") or "unknown")
    _add_indicator(features, "attacker_side", row.get("attacker_side") or "unknown")
    _add_indicator(features, "defender_side", row.get("defender_side") or "unknown")
    _add_indicator(features, "attacker_hull_type", _hull_type(row, "attacker") or "unknown")
    _add_indicator(features, "defender_hull_type", _hull_type(row, "defender") or "unknown")
    _add_indicator(features, "attacker_hull", _supported_hull_label(row, "attacker", attacker_hulls))
    _add_indicator(features, "defender_hull", _supported_hull_label(row, "defender", defender_hulls))

    weapon = row.get("weapon", {})
    weapon_shots = _number(weapon.get("shots") if isinstance(weapon, dict) else 0.0)
    attacker_shot_count_modifier = _resolved_modifier_value(row, "attacker", "3")
    defender_shot_count_modifier = _resolved_modifier_value(row, "defender", "3")
    features["weapon_shots"] = weapon_shots
    features["weapon_shots_log"] = math.log1p(max(0.0, weapon_shots))
    features["chain_shot_battle_type"] = _flag(is_chain_shot_battle_type(row.get("battle_type")))
    features["attacker_shot_count_modifier"] = attacker_shot_count_modifier
    features["defender_shot_count_modifier"] = defender_shot_count_modifier
    features["shot_count_modifier_present"] = _flag(
        attacker_shot_count_modifier != 0.0 or defender_shot_count_modifier != 0.0
    )
    if attacker_shot_count_modifier:
        _add_indicator(features, "attacker_shot_count_modifier_value", _report_number(attacker_shot_count_modifier))
    if defender_shot_count_modifier:
        _add_indicator(features, "defender_shot_count_modifier_value", _report_number(defender_shot_count_modifier))

    combat_features = combat_triangle_features(row, stat_source="static_player_max_buffs")
    for lane in ("armor", "shield", "dodge"):
        components = combat_features["components"]
        stat_inputs = combat_features["stat_inputs"]
        lane_inputs = stat_inputs.get(lane, {}) if isinstance(stat_inputs, dict) else {}
        defense = _number(lane_inputs.get("defense") if isinstance(lane_inputs, dict) else 0.0)
        piercing = _number(lane_inputs.get("piercing") if isinstance(lane_inputs, dict) else 0.0)
        denominator = defense + piercing
        features[f"{lane}_component"] = _number(components.get(lane) if isinstance(components, dict) else 0.0)
        features[f"{lane}_stat_ratio"] = defense / denominator if denominator else 0.0
    return features


def _fit_sparse_linear_model(
    rows: list[dict[str, Any]],
    *,
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
    regularization: float = BROAD_SYNCED_LINEAR_REGULARIZATION,
) -> dict[str, Any]:
    row_features = [feature_fn(row) for row in rows]
    feature_names = tuple(sorted({name for features in row_features for name in features}))
    feature_indexes = {name: index for index, name in enumerate(feature_names)}
    size = len(feature_names)
    matrix = [[0.0 for _ in range(size)] for _ in range(size)]
    vector = [0.0 for _ in range(size)]

    for row, features in zip(rows, row_features, strict=True):
        active = [(feature_indexes[name], value) for name, value in features.items() if value]
        target = _target(row)
        for i, left_value in active:
            vector[i] += left_value * target
            matrix_row = matrix[i]
            for j, right_value in active:
                matrix_row[j] += left_value * right_value

    for i in range(size):
        matrix[i][i] += regularization

    coefficients = _solve_linear_system(matrix, vector) if rows else []
    return {
        "formula": "clamp(sum(feature_value * coefficient), 0, 0.95)",
        "regularization": regularization,
        "features": list(feature_names),
        "coefficients": {
            name: _report_number(coefficient)
            for name, coefficient in zip(feature_names, coefficients, strict=True)
            if abs(coefficient) >= 1e-12
        },
    }


def _predict_sparse_linear_model(
    row: dict[str, Any],
    *,
    model: dict[str, Any],
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
) -> float:
    coefficients = model.get("coefficients", {})
    value = 0.0
    for name, feature_value in feature_fn(row).items():
        value += _number(coefficients.get(name)) * feature_value
    return _clamp_prediction(value)


def _stable_fold(key: Any, folds: int) -> int:
    digest = hashlib.sha256(str(key).encode("utf-8")).digest()
    return digest[0] % folds


def _synced_linear_cross_validation_metrics(
    rows: list[dict[str, Any]],
    base_predict: Callable[[dict[str, Any]], float],
    *,
    folds: int = BROAD_SYNCED_LINEAR_CV_FOLDS,
) -> dict[str, Any]:
    all_errors = []
    errors_by_class: dict[str, list[float]] = defaultdict(list)
    fold_summaries = []

    for fold in range(folds):
        train_rows = [row for row in rows if _stable_fold(row.get("battle_id"), folds) != fold]
        test_rows = [row for row in rows if _stable_fold(row.get("battle_id"), folds) == fold]
        if not train_rows or not test_rows:
            continue

        attacker_hulls = _common_hull_labels(
            train_rows,
            "attacker",
            min_rows=BROAD_SYNCED_LINEAR_MIN_HULL_ROWS,
        )
        defender_hulls = _common_hull_labels(
            train_rows,
            "defender",
            min_rows=BROAD_SYNCED_LINEAR_MIN_HULL_ROWS,
        )
        feature_fn = _cached_feature_fn(
            lambda row, ah=attacker_hulls, dh=defender_hulls: _synced_linear_features(
                row,
                base_predict=base_predict,
                attacker_hulls=ah,
                defender_hulls=dh,
            )
        )
        model = _fit_sparse_linear_model(train_rows, feature_fn=feature_fn)

        fold_errors = []
        fold_errors_by_class: dict[str, list[float]] = defaultdict(list)
        for row in test_rows:
            error = _predict_sparse_linear_model(row, model=model, feature_fn=feature_fn) - _target(row)
            fold_errors.append(error)
            all_errors.append(error)
            battle_class = _battle_formula_class(row)
            if battle_class in BROAD_FORMULA_TARGET_CLASSES:
                fold_errors_by_class[battle_class].append(error)
                errors_by_class[battle_class].append(error)

        fold_summaries.append(
            {
                "fold": fold,
                "train_rows": len(train_rows),
                "test_rows": len(test_rows),
                "feature_count": len(model["features"]),
                "overall": _metrics_from_errors(fold_errors),
                "by_battle_class": {
                    battle_class: _metrics_from_errors(fold_errors_by_class[battle_class])
                    for battle_class in BROAD_FORMULA_TARGET_CLASSES
                },
            }
        )

    return {
        "group": "battle_id",
        "folds": folds,
        "evaluated_folds": len(fold_summaries),
        "overall": _metrics_from_errors(all_errors),
        "by_battle_class": {
            battle_class: _metrics_from_errors(errors_by_class[battle_class])
            for battle_class in BROAD_FORMULA_TARGET_CLASSES
        },
        "fold_summaries": fold_summaries,
    }


def _broad_formula_goal(
    raw_rows: list[dict[str, Any]],
    base_predict: Callable[[dict[str, Any]], float],
) -> dict[str, Any]:
    rows, raw_counts, excluded_by_class = _broad_formula_rows(raw_rows)
    cached_base_predict = _cached_prediction_fn(base_predict)
    context_model = _fit_synced_context_residual_model(rows, cached_base_predict)
    attacker_hulls = _common_hull_labels(rows, "attacker", min_rows=BROAD_SYNCED_LINEAR_MIN_HULL_ROWS)
    defender_hulls = _common_hull_labels(rows, "defender", min_rows=BROAD_SYNCED_LINEAR_MIN_HULL_ROWS)
    synced_linear_features = _cached_feature_fn(
        lambda row: _synced_linear_features(
            row,
            base_predict=cached_base_predict,
            attacker_hulls=attacker_hulls,
            defender_hulls=defender_hulls,
        )
    )
    synced_linear_model = _fit_sparse_linear_model(rows, feature_fn=synced_linear_features)

    def predict_context(row: dict[str, Any]) -> float:
        return _predict_synced_context_residual_model(row, model=context_model, base_predict=cached_base_predict)

    def predict_synced_linear(row: dict[str, Any]) -> float:
        return _predict_sparse_linear_model(row, model=synced_linear_model, feature_fn=synced_linear_features)

    candidates = {
        "combat_triangle_static_player_max_buffs_formula": _broad_candidate_metrics(rows, cached_base_predict),
        "combat_triangle_synced_linear_formula": {
            **_broad_candidate_metrics(rows, predict_synced_linear),
            "cross_validation_metrics": _synced_linear_cross_validation_metrics(
                rows,
                cached_base_predict,
            ),
            "model": {
                **synced_linear_model,
                "base_formula": "combat_triangle_static_player_max_buffs_formula",
                "common_hull_min_rows": BROAD_SYNCED_LINEAR_MIN_HULL_ROWS,
                "attacker_hull_labels": list(attacker_hulls),
                "defender_hull_labels": list(defender_hulls),
            },
        },
        "combat_triangle_synced_context_residual_formula": {
            **_broad_candidate_metrics(rows, predict_context),
            "leave_one_battle_out_metrics": _synced_context_residual_leave_one_battle_out_metrics(
                rows,
                cached_base_predict,
                min_group_rows=int(context_model["min_group_rows"]),
            ),
            "model": context_model,
        },
    }

    passing = sorted(
        name
        for name, metrics in candidates.items()
        if all(
            int(metrics["by_battle_class"][battle_class].get("count", 0)) > 0
            and float(metrics["by_battle_class"][battle_class].get("mae", 0.0)) <= SIMULATOR_TARGET_MAE
            for battle_class in BROAD_FORMULA_TARGET_CLASSES
        )
    )
    best_candidate = None
    if candidates:
        best_candidate = min(
            candidates,
            key=lambda name: (
                max(
                    float(candidates[name]["by_battle_class"][battle_class].get("mae", 0.0))
                    for battle_class in BROAD_FORMULA_TARGET_CLASSES
                ),
                float(candidates[name]["overall"].get("mae", 0.0)),
                name,
            ),
        )
    return {
        "target_mae": SIMULATOR_TARGET_MAE,
        "scope": BROAD_FORMULA_SCOPE,
        "usable_rows": len(rows),
        "raw_rows_by_battle_class": raw_counts,
        "usable_rows_by_battle_class": {
            battle_class: candidates["combat_triangle_static_player_max_buffs_formula"]["by_battle_class"][battle_class][
                "count"
            ]
            for battle_class in BROAD_FORMULA_TARGET_CLASSES
        },
        "excluded_reasons_by_battle_class": excluded_by_class,
        "candidate_metrics": candidates,
        "passing": passing,
        "best_candidate": best_candidate,
    }


def _hull_grade(row: dict[str, Any], side: str) -> float:
    return _number(_nested_dict(row, side, "static_ship", "hull").get("grade"))


def _hull_type_flags(prefix: str, hull_type: str) -> dict[str, float]:
    normalized = hull_type.removeprefix("HULLTYPE_").lower()
    return {
        f"{prefix}_hull_explorer": _flag(normalized == "explorer"),
        f"{prefix}_hull_battleship": _flag(normalized == "battleship"),
        f"{prefix}_hull_interceptor": _flag(normalized == "interceptor"),
        f"{prefix}_hull_survey": _flag(normalized == "survey"),
    }


def _ratio_features(row: dict[str, Any]) -> dict[str, float]:
    weapon = row.get("weapon", {})
    defender_stats = row.get("defender", {}).get("captured_stats", {})
    return {
        "dodge_ratio": _ratio(defender_stats.get("11"), weapon.get("accuracy")),
        "plating_ratio": _ratio(defender_stats.get("-3"), weapon.get("penetration")),
        "absorption_ratio": _ratio(defender_stats.get("-2"), weapon.get("modulation")),
    }


def _shield_active_before_shot(row: dict[str, Any]) -> bool:
    observed = row.get("observed", {})
    damage = observed.get("damage", {})
    remaining = observed.get("remaining", {})
    shield_damage = _number(damage.get("shield") if isinstance(damage, dict) else 0.0)
    remaining_shield = _number(remaining.get("shield") if isinstance(remaining, dict) else 0.0)
    return shield_damage + remaining_shield > 0


def _basic_live_features(row: dict[str, Any]) -> dict[str, float]:
    return deterministic_basic_live_features(row)


def _combat_triangle_calibration_features(row: dict[str, Any]) -> dict[str, float]:
    return {"combat_triangle_prediction": predict_combat_triangle_mitigation(row, include_apex_barrier=False)}


def _expanded_features(row: dict[str, Any]) -> dict[str, float]:
    features = _ratio_features(row)
    weapon = row.get("weapon", {})
    observed = row.get("observed", {})
    triggered_effects = set(observed.get("triggered_effects", []))
    minimum_damage = _number(weapon.get("minimum_damage"))
    maximum_damage = _number(weapon.get("maximum_damage"))
    damage_midpoint = (minimum_damage + maximum_damage) / 2.0
    weapon_shots = _number(weapon.get("shots"))
    raw_damage = _number(observed.get("raw_damage"))
    attacker_hull_type = _hull_type(row, "attacker")
    defender_hull_type = _hull_type(row, "defender")

    features.update(
        {
            "attacker_is_player": _flag(row.get("attacker_side") == "player"),
            "critical": _flag(bool(observed.get("critical"))),
            "weapon_shots": weapon_shots,
            "weapon_crit_modifier": _number(weapon.get("crit_modifier")),
            "weapon_accuracy_log": math.log1p(max(0.0, _number(weapon.get("accuracy")))),
            "weapon_penetration_log": math.log1p(max(0.0, _number(weapon.get("penetration")))),
            "weapon_modulation_log": math.log1p(max(0.0, _number(weapon.get("modulation")))),
            "weapon_damage_midpoint_log": math.log1p(max(0.0, damage_midpoint)),
            "weapon_damage_per_shot_log": math.log1p(
                max(0.0, damage_midpoint / weapon_shots) if weapon_shots else 0.0
            ),
            "weapon_damage_spread_ratio": ((maximum_damage - minimum_damage) / maximum_damage if maximum_damage else 0.0),
            "isolytic_triggered": _flag("isolytic" in triggered_effects),
            "officer_triggered": _flag("officer" in triggered_effects),
            "attacker_cloaking_ability": _flag(
                _has_activated_ability_type(row, "attacker", "ACTIVATEDABILITYTYPE_CLOAKING")
            ),
            "defender_cloaking_ability": _flag(
                _has_activated_ability_type(row, "defender", "ACTIVATEDABILITYTYPE_CLOAKING")
            ),
            "hostile_id_mar_prefix": _flag(_hostile_id_prefix(row) == "mar"),
            "hostile_id_npc_prefix": _flag(_hostile_id_prefix(row) == "npc"),
            "apex_barrier_ratio": _number(observed.get("mitigated_apex_barrier")) / raw_damage if raw_damage else 0.0,
            "defender_shield_mitigation": _number(
                _nested_dict(row, "defender", "static_ship", "base_stats").get("shield_mitigation")
            ),
            "attacker_hull_grade": _hull_grade(row, "attacker"),
            "defender_hull_grade": _hull_grade(row, "defender"),
            "same_hull_type": _flag(bool(attacker_hull_type) and attacker_hull_type == defender_hull_type),
        }
    )
    features.update(_hull_type_flags("attacker", attacker_hull_type))
    features.update(_hull_type_flags("defender", defender_hull_type))
    return features


def _target(row: dict[str, Any]) -> float:
    return normal_effective_mitigation(row)


def _observed_effective_mitigation(row: dict[str, Any]) -> float:
    return _number(row.get("observed", {}).get("effective_mitigation"))


def _overkill_base_damage_gap(row: dict[str, Any]) -> float:
    observed = row.get("observed", {})
    model = observed.get("isolytic_damage_model", {}) if isinstance(observed, dict) else {}
    if not isinstance(model, dict):
        return 0.0
    normal_without_apex = normal_mitigation_from_observed(observed, include_apex_barrier=False)
    inferred_base_damage = _number(model.get("inferred_base_damage", normal_without_apex.get("raw_damage")))
    return inferred_base_damage - _number(normal_without_apex.get("raw_damage"))


def _row_normal_mitigation(row: dict[str, Any]) -> dict[str, Any]:
    observed = row.get("observed", {})
    return normal_mitigation_from_observed(observed if isinstance(observed, dict) else {})


def _is_armada_scope(row: dict[str, Any]) -> bool:
    return row.get("battle_type") == 8 or row.get("player_battle_data_type") == 2 or row.get("hostile_battle_data_type") == 2


def _resolved_modifier_value(row: dict[str, Any], role: str, modifier_code: str) -> float:
    ship = row.get(role, {})
    modifiers = ship.get("resolved_modifiers", {}) if isinstance(ship, dict) else {}
    if not isinstance(modifiers, dict):
        return 0.0
    return _number(modifiers.get(modifier_code))


def _has_nonzero_resolved_modifier(row: dict[str, Any], modifier_code: str) -> bool:
    for role in ("attacker", "defender"):
        if _resolved_modifier_value(row, role, modifier_code):
            return True
    return False


def _mitigation_fit_excluded_reason(row: dict[str, Any]) -> str | None:
    if _is_armada_scope(row):
        return "armada_battle_scope"
    if is_cutting_beam_battle_type(row.get("battle_type")):
        return "cutting_beam_bypasses_mitigation"
    if is_chain_shot_battle_type(row.get("battle_type")):
        return "chain_shot_special_damage"
    if not row.get("observed", {}).get("hit", True):
        return "miss"
    normal_mitigation = _row_normal_mitigation(row)
    if _number(normal_mitigation.get("raw_damage")) <= 0:
        return "missing_normal_raw_damage"
    if _has_nonzero_resolved_modifier(row, "3"):
        return "shot_count_damage_stage"
    if (
        "isolytic" in row.get("observed", {}).get("triggered_effects", [])
        and _number(normal_mitigation.get("observed_damage")) <= 0
        and _number(normal_mitigation.get("mitigated_damage")) > 0
    ):
        return "normal_damage_capped_by_isolytic_overkill"
    return None


def _usable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _mitigation_fit_excluded_reason(row) is None]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "stddev": 0.0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": _mean(values),
        "stddev": _stddev(values),
    }


def _scaling_distribution(values: list[float]) -> dict[str, float | int]:
    return _distribution(values)


def _clamp_prediction(value: float) -> float:
    return max(0.0, min(0.95, value))


def _metrics(rows: list[dict[str, Any]], predict: Callable[[dict[str, Any]], float]) -> dict[str, float | int]:
    if not rows:
        return {"count": 0, "mae": 0.0, "rmse": 0.0, "max_abs_error": 0.0, "bias": 0.0}
    errors = []
    for row in rows:
        errors.append(predict(row) - _target(row))
    return _metrics_from_errors(errors)


def _metrics_from_errors(errors: list[float]) -> dict[str, float | int]:
    if not errors:
        return {"count": 0, "mae": 0.0, "rmse": 0.0, "max_abs_error": 0.0, "bias": 0.0}
    abs_errors = [abs(error) for error in errors]
    squared_errors = [error * error for error in errors]
    return {
        "count": len(errors),
        "mae": _mean(abs_errors),
        "rmse": math.sqrt(_mean(squared_errors)),
        "max_abs_error": max(abs_errors),
        "bias": _mean(errors),
    }


def _tag_input_class(model: dict[str, Any], input_class: str, dependencies: list[str]) -> dict[str, Any]:
    model["input_class"] = input_class
    model["input_dependencies"] = dependencies
    return model


def _candidate_metrics(models: dict[str, Any]) -> dict[str, dict[str, float | int]]:
    candidates = {}
    for name, model in models.items():
        if not isinstance(model, dict):
            continue
        if model.get("input_class") not in SIMULATOR_ELIGIBLE_INPUT_CLASSES:
            continue
        metrics = model.get("metrics")
        if isinstance(metrics, dict):
            candidates[name] = metrics
    return candidates


def _simulator_goal(models: dict[str, Any]) -> dict[str, Any]:
    candidates = _candidate_metrics(models)
    passing = sorted(
        name
        for name, metrics in candidates.items()
        if float(metrics.get("mae", 0.0)) <= SIMULATOR_TARGET_MAE
    )
    best_candidate = None
    if candidates:
        best_candidate = min(
            candidates,
            key=lambda name: (
                float(candidates[name].get("mae", 0.0)),
                float(candidates[name].get("rmse", 0.0)),
                name,
            ),
        )
    return {
        "target_mae": SIMULATOR_TARGET_MAE,
        "eligible_input_classes": list(SIMULATOR_ELIGIBLE_INPUT_CLASSES),
        "candidate_metrics": candidates,
        "passing": passing,
        "best_candidate": best_candidate,
    }


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]

    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            augmented[col][col] += 1e-9
            pivot = col
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]

        pivot_value = augmented[col][col]
        if abs(pivot_value) < 1e-12:
            continue
        for idx in range(col, size + 1):
            augmented[col][idx] /= pivot_value

        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0:
                continue
            for idx in range(col, size + 1):
                augmented[row][idx] -= factor * augmented[col][idx]

    return [augmented[row][size] for row in range(size)]


def _feature_descriptions(feature_names: tuple[str, ...]) -> dict[str, str]:
    return {name: FEATURE_DESCRIPTIONS[name] for name in feature_names}


def _combat_triangle_composition_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants = []
    for composition in COMBAT_TRIANGLE_COMPOSITIONS:
        predictor = lambda row, composition=composition: predict_combat_triangle_mitigation(
            row,
            composition=composition,
            include_apex_barrier=False,
        )
        variants.append(
            {
                "composition": composition,
                "metrics": _metrics(rows, predictor),
            }
        )
    return sorted(
        variants,
        key=lambda variant: (
            float(variant["metrics"]["mae"]),
            float(variant["metrics"]["rmse"]),
            str(variant["composition"]),
        ),
    )


def _combat_triangle_static_player_max_buffs_curve_base_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants = []
    for composition in ("weighted_product", "weighted_power_product"):
        predictor = lambda row, composition=composition: predict_combat_triangle_mitigation(
            row,
            stat_source="static_player_max_buffs",
            composition=composition,
            curve_base=2.0,
            include_apex_barrier=False,
        )
        variants.append(
            {
                "name": f"combat_triangle_static_player_max_buffs_curve_base_2_{composition}",
                "purpose": "diagnostic only; compare the Monaveen curve-base hypothesis without promoting it",
                "input_class": "diagnostic_only",
                "stat_source": "static_player_max_buffs",
                "composition": composition,
                "curve_base": 2.0,
                "metrics": _metrics(rows, predictor),
            }
        )
    return sorted(
        variants,
        key=lambda variant: (
            float(variant["metrics"]["mae"]),
            float(variant["metrics"]["rmse"]),
            str(variant["composition"]),
        ),
    )


def _combat_triangle_stat_role_orientation_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    variants = []
    for orientation in COMBAT_TRIANGLE_STAT_ROLE_ORIENTATIONS:
        predictor = lambda row, orientation=orientation: predict_combat_triangle_mitigation(
            row,
            stat_role_orientation=orientation,
            include_apex_barrier=False,
        )
        variants.append(
            {
                "stat_role_orientation": orientation,
                "metrics": _metrics(rows, predictor),
            }
        )
    return sorted(
        variants,
        key=lambda variant: (
            float(variant["metrics"]["mae"]),
            float(variant["metrics"]["rmse"]),
            str(variant["stat_role_orientation"]),
        ),
    )


def _fit_linear_model(
    rows: list[dict[str, Any]],
    *,
    feature_names: tuple[str, ...],
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
    regularization: float = 1e-6,
) -> dict[str, Any]:
    terms = ("intercept", *feature_names)
    size = len(terms)
    matrix = [[0.0 for _ in range(size)] for _ in range(size)]
    vector = [0.0 for _ in range(size)]

    for row in rows:
        features = feature_fn(row)
        x = [1.0, *(features.get(name, 0.0) for name in feature_names)]
        y = _target(row)
        for i in range(size):
            vector[i] += x[i] * y
            for j in range(size):
                matrix[i][j] += x[i] * x[j]

    for i in range(size):
        matrix[i][i] += regularization

    coefficients = _solve_linear_system(matrix, vector) if rows else [0.0 for _ in range(size)]
    return {
        "intercept": coefficients[0],
        "coefficients": dict(zip(feature_names, coefficients[1:], strict=True)),
        "regularization": regularization,
    }


def _fit_nonnegative_feature_linear_model(
    rows: list[dict[str, Any]],
    *,
    feature_names: tuple[str, ...],
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
) -> dict[str, Any]:
    best_model: dict[str, Any] | None = None
    best_metrics: dict[str, float | int] | None = None
    feature_count = len(feature_names)

    for mask in range(1 << feature_count):
        active_features = tuple(feature_names[index] for index in range(feature_count) if mask & (1 << index))
        candidate = _fit_linear_model(rows, feature_names=active_features, feature_fn=feature_fn)
        if any(coefficient < -1e-9 for coefficient in candidate["coefficients"].values()):
            continue

        coefficients = {name: 0.0 for name in feature_names}
        coefficients.update(candidate["coefficients"])
        model = {
            "intercept": candidate["intercept"],
            "coefficients": coefficients,
            "regularization": candidate["regularization"],
            "constraint": "feature coefficients are constrained to be nonnegative; intercept is unconstrained",
            "active_features": list(active_features),
        }

        def predict(row: dict[str, Any], fitted_model: dict[str, Any] = model) -> float:
            return _predict_linear_model(fitted_model, row, feature_fn=feature_fn)

        candidate_metrics = _metrics(rows, predict)
        if best_metrics is None or float(candidate_metrics["mae"]) < float(best_metrics["mae"]):
            best_model = model
            best_metrics = candidate_metrics

    if best_model is None:
        best_model = {
            "intercept": 0.0,
            "coefficients": {name: 0.0 for name in feature_names},
            "regularization": 0.0,
            "constraint": "feature coefficients are constrained to be nonnegative; intercept is unconstrained",
            "active_features": [],
        }
    return best_model


def _predict_linear_model(
    model: dict[str, Any],
    row: dict[str, Any],
    *,
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
) -> float:
    features = feature_fn(row)
    value = model["intercept"]
    for name, coefficient in model["coefficients"].items():
        value += coefficient * features.get(name, 0.0)
    return _clamp_prediction(value)


def _cached_feature_fn(
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
) -> Callable[[dict[str, Any]], dict[str, float]]:
    cache: dict[int, dict[str, float]] = {}

    def cached(row: dict[str, Any]) -> dict[str, float]:
        key = id(row)
        features = cache.get(key)
        if features is None:
            features = feature_fn(row)
            cache[key] = features
        return features

    return cached


def _cached_prediction_fn(
    predict: Callable[[dict[str, Any]], float],
) -> Callable[[dict[str, Any]], float]:
    cache: dict[int, float] = {}

    def cached(row: dict[str, Any]) -> float:
        key = id(row)
        if key not in cache:
            cache[key] = predict(row)
        return cache[key]

    return cached


def _fit_partitioned_linear_model(
    rows: list[dict[str, Any]],
    *,
    partition_name: str,
    key_fn: Callable[[dict[str, Any]], str],
    feature_names: tuple[str, ...],
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    partitions: dict[str, dict[str, Any]] = {}
    for key, group_rows in sorted(groups.items()):
        model = _fit_linear_model(group_rows, feature_names=feature_names, feature_fn=feature_fn)

        def predict_partition(row: dict[str, Any], fitted_model: dict[str, Any] = model) -> float:
            return _predict_linear_model(fitted_model, row, feature_fn=feature_fn)

        model["rows"] = len(group_rows)
        model["metrics"] = _metrics(group_rows, predict_partition)
        partitions[key] = model

    fallback_model = _fit_linear_model(rows, feature_names=feature_names, feature_fn=feature_fn)

    def predict(row: dict[str, Any]) -> float:
        model = partitions.get(key_fn(row), fallback_model)
        return _predict_linear_model(model, row, feature_fn=feature_fn)

    return {
        "formula": "fit the expanded linear formula independently for each partition, then clamp to [0, 0.95]",
        "partition": partition_name,
        "features": _feature_descriptions(feature_names),
        "partitions": partitions,
        "fallback": fallback_model,
        "metrics": _metrics(rows, predict),
    }


def _fit_partitioned_nonnegative_feature_linear_model(
    rows: list[dict[str, Any]],
    *,
    partition_name: str,
    key_fn: Callable[[dict[str, Any]], str],
    feature_names: tuple[str, ...],
    feature_fn: Callable[[dict[str, Any]], dict[str, float]],
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    partitions: dict[str, dict[str, Any]] = {}
    for key, group_rows in sorted(groups.items()):
        model = _fit_nonnegative_feature_linear_model(group_rows, feature_names=feature_names, feature_fn=feature_fn)

        def predict_partition(row: dict[str, Any], fitted_model: dict[str, Any] = model) -> float:
            return _predict_linear_model(fitted_model, row, feature_fn=feature_fn)

        model["rows"] = len(group_rows)
        model["metrics"] = _metrics(group_rows, predict_partition)
        partitions[key] = model

    fallback_model = _fit_nonnegative_feature_linear_model(rows, feature_names=feature_names, feature_fn=feature_fn)

    def predict(row: dict[str, Any]) -> float:
        model = partitions.get(key_fn(row), fallback_model)
        return _predict_linear_model(model, row, feature_fn=feature_fn)

    return {
        "formula": "fit basic live-stat ratios independently for each partition with nonnegative feature coefficients",
        "partition": partition_name,
        "features": _feature_descriptions(feature_names),
        "partitions": partitions,
        "fallback": fallback_model,
        "metrics": _metrics(rows, predict),
    }


def _leave_one_group_out_metrics(
    rows: list[dict[str, Any]],
    *,
    group_name: str,
    key_fn: Callable[[dict[str, Any]], str],
    build_predictor: Callable[[list[dict[str, Any]]], Callable[[dict[str, Any]], float]],
    max_groups: int | None = LEAVE_ONE_GROUP_OUT_MAX_GROUPS,
) -> dict[str, float | int | str]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    group_items = sorted(groups.items())
    sampling = "all_groups"
    if max_groups is not None and max_groups > 0 and len(group_items) > max_groups:
        if max_groups == 1:
            selected_indexes = [0]
        else:
            selected_indexes = [
                round(index * (len(group_items) - 1) / (max_groups - 1))
                for index in range(max_groups)
            ]
        group_items = [group_items[index] for index in selected_indexes]
        sampling = "deterministic_evenly_spaced_groups"

    errors: list[float] = []
    evaluated_groups = 0
    for key, test_rows in group_items:
        train_rows = [row for group_key, group_rows in groups.items() if group_key != key for row in group_rows]
        if not train_rows:
            continue
        predict = build_predictor(train_rows)
        evaluated_groups += 1
        for row in test_rows:
            errors.append(predict(row) - _target(row))

    metrics = _metrics_from_errors(errors)
    metrics.update(
        {
            "group": group_name,
            "groups": len(groups),
            "evaluated_groups": evaluated_groups,
            "evaluation_limit": max_groups or len(groups),
            "skipped_groups": max(0, len(groups) - evaluated_groups),
            "sampling": sampling,
        }
    )
    return metrics


def _group_summary(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
    predictions: dict[str, Callable[[dict[str, Any]], float]],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    summaries = []
    for key, group_rows in sorted(groups.items()):
        summaries.append(
            {
                "key": key,
                "count": len(group_rows),
                "observed": _distribution([_target(row) for row in group_rows]),
                **{model_name: _metrics(group_rows, predict) for model_name, predict in predictions.items()},
            }
        )
    return summaries


def _multi_group_summary(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], list[str]],
    predictions: dict[str, Callable[[dict[str, Any]], float]],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for key in sorted(set(key_fn(row))):
            groups[key].append(row)

    summaries = []
    for key, group_rows in sorted(groups.items()):
        summaries.append(
            {
                "key": key,
                "count": len(group_rows),
                "observed": _distribution([_target(row) for row in group_rows]),
                **{model_name: _metrics(group_rows, predict) for model_name, predict in predictions.items()},
            }
        )
    return summaries


def _weapon_actuals_group_summary(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    summaries = []
    for key, group_rows in sorted(groups.items()):
        diagnostics = [weapon_damage_diagnostics(row) for row in group_rows]
        summaries.append(
            {
                "key": key,
                "count": len(group_rows),
                "diagnostics": {
                    field: _distribution([_number(row[field]) for row in diagnostics])
                    for field in diagnostics[0]
                }
                if diagnostics
                else {},
                "sample_weapon_ids": sorted({str(row.get("weapon", {}).get("id")) for row in group_rows})[:5],
            }
        )
    return summaries


def _residual_group_summary(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
    predict: Callable[[dict[str, Any]], float],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    summaries = []
    for key, group_rows in sorted(groups.items()):
        predictions = [predict(row) for row in group_rows]
        errors = [prediction - _target(row) for prediction, row in zip(predictions, group_rows, strict=True)]
        summaries.append(
            {
                "key": key,
                "count": len(group_rows),
                "observed": _distribution([_target(row) for row in group_rows]),
                "prediction": _distribution(predictions),
                "error": _metrics_from_errors(errors),
                "sample_battle_ids": sorted({str(row.get("battle_id")) for row in group_rows})[:5],
            }
        )
    return sorted(summaries, key=lambda row: (-float(row["error"]["mae"]), row["key"]))


def _multi_residual_group_summary(
    rows: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], list[str]],
    predict: Callable[[dict[str, Any]], float],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for key in sorted(set(key_fn(row))):
            groups[key].append(row)

    summaries = []
    for key, group_rows in sorted(groups.items()):
        predictions = [predict(row) for row in group_rows]
        errors = [prediction - _target(row) for prediction, row in zip(predictions, group_rows, strict=True)]
        summaries.append(
            {
                "key": key,
                "count": len(group_rows),
                "observed": _distribution([_target(row) for row in group_rows]),
                "prediction": _distribution(predictions),
                "error": _metrics_from_errors(errors),
                "sample_battle_ids": sorted({str(row.get("battle_id")) for row in group_rows})[:5],
            }
        )
    return sorted(summaries, key=lambda row: (-float(row["error"]["mae"]), row["key"]))


def _is_isolytic_triggered(row: dict[str, Any]) -> bool:
    return "isolytic" in row.get("observed", {}).get("triggered_effects", [])


def _officer_activations(row: dict[str, Any]) -> list[dict[str, Any]]:
    activations = row.get("observed", {}).get("officer_activations", [])
    return [activation for activation in activations if isinstance(activation, dict)]


def _officer_ability_keys(row: dict[str, Any]) -> list[str]:
    activations = _officer_activations(row)
    if not activations:
        return ["none"]
    keys = []
    for activation in activations:
        ability_id = str(activation.get("ability_buff_id") or "unknown")
        modifier_code = str(activation.get("modifierCode") or "unknown")
        op = str(activation.get("op") or "unknown")
        keys.append(f"{ability_id}:modifier={modifier_code}:op={op}")
    return keys


def _activation_formula_stage(activation: dict[str, Any]) -> str:
    effect = activation.get("formula_effect")
    if isinstance(effect, dict):
        return str(effect.get("formula_stage") or "unknown")
    return "unknown"


def _officer_formula_stage_keys(row: dict[str, Any]) -> list[str]:
    activations = _officer_activations(row)
    if not activations:
        return ["none"]
    return [_activation_formula_stage(activation) for activation in activations]


def _officer_stage_modifier_keys(row: dict[str, Any]) -> list[str]:
    activations = _officer_activations(row)
    if not activations:
        return ["none"]
    return [
        f"{_activation_formula_stage(activation)}:{activation.get('modifierCode') or 'unknown'}:"
        f"op={activation.get('op') or 'unknown'}"
        for activation in activations
    ]


def _officer_modifier_keys(row: dict[str, Any]) -> list[str]:
    activations = _officer_activations(row)
    if not activations:
        return ["none"]
    return [
        f"{activation.get('modifierCode') or 'unknown'}:op={activation.get('op') or 'unknown'}"
        for activation in activations
    ]


def _officer_id_keys(row: dict[str, Any]) -> list[str]:
    activations = _officer_activations(row)
    if not activations:
        return ["none"]
    return [str(activation.get("officer_id") or "unknown") for activation in activations]


def _ship_list_keys(row: dict[str, Any], side: str, key: str) -> list[str]:
    ship = row.get(side, {})
    values = ship.get(key, []) if isinstance(ship, dict) else []
    if not isinstance(values, list) or not values:
        return ["none"]
    return [str(value) for value in values]


def _hull_list_keys(row: dict[str, Any], side: str, key: str) -> list[str]:
    hull = _nested_dict(row, side, "static_ship", "hull")
    values = hull.get(key, [])
    if not isinstance(values, list) or not values:
        return ["none"]
    return [str(value) for value in values]


def _hull_activated_ability_keys(row: dict[str, Any], side: str) -> list[str]:
    hull = _nested_dict(row, side, "static_ship", "hull")
    abilities = hull.get("activated_abilities", [])
    if isinstance(abilities, list) and abilities:
        keys = []
        for ability in abilities:
            if not isinstance(ability, dict):
                continue
            ability_id = str(ability.get("id") or "unknown")
            label = str(ability.get("id_str") or ability.get("ability_type") or ability_id)
            keys.append(f"{ability_id}:{label}")
        if keys:
            return keys
    return _hull_list_keys(row, side, "activated_ability_ids")


def _has_activated_ability_type(row: dict[str, Any], side: str, ability_type: str) -> bool:
    hull = _nested_dict(row, side, "static_ship", "hull")
    for ability in hull.get("activated_abilities", []) or []:
        if isinstance(ability, dict) and str(ability.get("ability_type")) == ability_type:
            return True
    return False


def _hostile_id_prefix(row: dict[str, Any]) -> str:
    prefix = str(row.get("hostile_id_prefix") or "")
    if prefix:
        return prefix
    hostile_id = str(row.get("hostile_id") or "")
    if "_" not in hostile_id:
        return hostile_id or "unknown"
    return hostile_id.split("_", 1)[0]


def _activation_label(activation: dict[str, Any]) -> str:
    return (
        f"{activation.get('ability_buff_id') or 'unknown'}:"
        f"modifier={activation.get('modifierCode') or 'unknown'}:"
        f"op={activation.get('op') or 'unknown'}"
    )


def _activation_formula_effect_summary(activation: dict[str, Any]) -> dict[str, Any]:
    effect = activation.get("formula_effect")
    if not isinstance(effect, dict):
        return {
            "modifierCode": str(activation.get("modifierCode") or "unknown"),
            "formula_stage": "unknown",
            "formula_inputs": [],
            "confidence": "unknown",
        }
    return {
        "modifierCode": effect.get("modifierCode"),
        "formula_stage": effect.get("formula_stage"),
        "formula_inputs": effect.get("formula_inputs", []),
        "confidence": effect.get("confidence"),
        "notes": effect.get("notes"),
    }


def _officer_activation_ablation_summary(
    rows: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], float],
) -> list[dict[str, Any]]:
    all_rows = list(rows)
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        for activation in _officer_activations(row):
            key = _activation_label(activation)
            group = groups.setdefault(
                key,
                {
                    "key": key,
                    "ability_buff_id": str(activation.get("ability_buff_id") or "unknown"),
                    "officer_ids": set(),
                    "values": [],
                    "formula_effect": _activation_formula_effect_summary(activation),
                    "rows": [],
                    "activation_count": 0,
                    "source_types": set(),
                    "sample_battle_ids": set(),
                },
            )
            group["rows"].append(row)
            group["activation_count"] += 1
            group["values"].append(_number(activation.get("value")))
            group["officer_ids"].add(str(activation.get("officer_id") or "unknown"))
            group["source_types"].add(str(activation.get("ability_source_type") or "unknown"))
            group["sample_battle_ids"].add(str(row.get("battle_id")))

    summaries = []
    for key, group in groups.items():
        group_rows = group["rows"]
        group_row_ids = {id(row) for row in group_rows}
        complement_rows = [row for row in all_rows if id(row) not in group_row_ids]
        group_metrics = _metrics(group_rows, predict)
        complement_metrics = _metrics(complement_rows, predict)
        summaries.append(
            {
                "key": key,
                "ability_buff_id": group["ability_buff_id"],
                "officer_ids": sorted(group["officer_ids"]),
                "source_types": sorted(group["source_types"]),
                "row_count": len(group_rows),
                "activation_count": group["activation_count"],
                "value": _distribution(group["values"]),
                "formula_effect": group["formula_effect"],
                "metrics": group_metrics,
                "without_this_activation_metrics": complement_metrics,
                "mae_delta_vs_without": _report_number(
                    float(group_metrics["mae"]) - float(complement_metrics["mae"])
                ),
                "bias_delta_vs_without": _report_number(
                    float(group_metrics["bias"]) - float(complement_metrics["bias"])
                ),
                "sample_battle_ids": sorted(group["sample_battle_ids"])[:5],
            }
        )
    return sorted(
        summaries,
        key=lambda row: (
            -float(row["mae_delta_vs_without"]),
            -float(row["metrics"]["mae"]),
            str(row["key"]),
        ),
    )


def _cross_tab(
    rows: list[dict[str, Any]],
    row_key_fn: Callable[[dict[str, Any]], str],
    column_key_fn: Callable[[dict[str, Any]], str],
) -> dict[str, dict[str, int]]:
    table: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        table[row_key_fn(row)][column_key_fn(row)] += 1
    return {
        row_key: {column_key: count for column_key, count in sorted(columns.items())}
        for row_key, columns in sorted(table.items())
    }


def _formula_data_gaps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    warnings = []
    rows_by_attacker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_attacker[str(row.get("attacker_side"))].append(row)

    for attacker_side, side_rows in sorted(rows_by_attacker.items()):
        if side_rows and all(_is_isolytic_triggered(row) for row in side_rows):
            warnings.append(f"{attacker_side} attacker rows are fully confounded with isolytic-triggered rows")
        if side_rows and not any(_is_isolytic_triggered(row) for row in side_rows):
            warnings.append(f"{attacker_side} attacker rows contain no isolytic-triggered rows")

    return {
        "warnings": warnings,
        "attacker_side_by_isolytic_triggered": _cross_tab(
            rows,
            lambda row: str(row.get("attacker_side")),
            lambda row: str(_is_isolytic_triggered(row)),
        ),
        "attacker_side_by_defender_hull_type": _cross_tab(
            rows,
            lambda row: str(row.get("attacker_side")),
            lambda row: _hull_type(row, "defender") or "unknown",
        ),
        "attacker_side_by_shield_active_before_shot": _cross_tab(
            rows,
            lambda row: str(row.get("attacker_side")),
            lambda row: str(_shield_active_before_shot(row)),
        ),
    }


def _stat_scaling_rows(
    rows: list[dict[str, Any]],
    *,
    by_hull: bool = False,
    by_hull_type: bool = False,
) -> list[dict[str, Any]]:
    stat_specs = {
        "attacker": (
            ("weapon_accuracy", "6", "weapon_accuracy_max"),
            ("weapon_armor_piercing", "7", "weapon_penetration_max"),
            ("weapon_shield_piercing", "8", "weapon_modulation_max"),
        ),
        "defender": (
            ("ship_dodge", "11", "dodge"),
            ("ship_plating", "-3", "armor_plating"),
            ("ship_absorption", "-2", "shield_absorption"),
        ),
    }
    groups: dict[tuple[str, ...], dict[str, list[float] | set[tuple[str, str, str, str]]]] = defaultdict(
        lambda: {"captured": [], "static": [], "delta": [], "multiplier": [], "seen": set()}
    )

    for row in rows:
        battle_id = str(row.get("battle_id"))
        for role, specs in stat_specs.items():
            ship = row.get(role, {})
            side = str(row.get(f"{role}_side"))
            ship_id = str(ship.get("ship_id"))
            hull = _nested_dict(row, role, "static_ship", "hull")
            hull_id = str(hull.get("id") or ship.get("hull_id") or "")
            hull_name = str(hull.get("name") or hull.get("id_str") or hull_id)
            hull_type = str(hull.get("type") or "")
            captured_stats = ship.get("captured_stats", {})
            base_stats = _nested_dict(row, role, "static_ship", "base_stats")
            for stat_name, captured_key, static_key in specs:
                seen_key = (battle_id, role, side, ship_id, stat_name)
                if by_hull:
                    group_key = (role, side, hull_id, hull_name, hull_type, stat_name)
                elif by_hull_type:
                    group_key = (role, side, hull_type, stat_name)
                else:
                    group_key = (role, side, stat_name)
                group = groups[group_key]
                seen = group["seen"]
                if seen_key in seen:
                    continue
                seen.add(seen_key)

                captured = _number(captured_stats.get(captured_key))
                static = _number(base_stats.get(static_key))
                group["captured"].append(captured)
                group["static"].append(static)
                group["delta"].append(captured - static)
                if static != 0:
                    group["multiplier"].append(captured / static)

    summaries = []
    for group_key, values in sorted(groups.items()):
        if by_hull:
            role, side, hull_id, hull_name, hull_type, stat_name = group_key
        elif by_hull_type:
            role, side, hull_type, stat_name = group_key
            hull_id = ""
            hull_name = ""
        else:
            role, side, stat_name = group_key
            hull_id = ""
            hull_name = ""
            hull_type = ""
        summary = {
            "role": role,
            "side": side,
            "stat": stat_name,
            "samples": len(values["captured"]),
            "captured": _scaling_distribution(values["captured"]),
            "static": _scaling_distribution(values["static"]),
            "delta": _scaling_distribution(values["delta"]),
            "multiplier": _scaling_distribution(values["multiplier"]),
        }
        if by_hull:
            summary["hull_id"] = hull_id
            summary["hull_name"] = hull_name
            summary["hull_type"] = hull_type
        if by_hull_type:
            summary["hull_type"] = hull_type
        summaries.append(summary)
    return summaries


def _combat_triangle_residual_groups(
    rows: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], float],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "attacker_side": _residual_group_summary(rows, lambda row: str(row.get("attacker_side")), predict),
        "attacker_hull_name": _residual_group_summary(
            rows,
            lambda row: _hull_label(row, "attacker"),
            predict,
        ),
        "defender_hull_name": _residual_group_summary(
            rows,
            lambda row: _hull_label(row, "defender"),
            predict,
        ),
        "defender_hull_type": _residual_group_summary(
            rows,
            lambda row: _hull_type(row, "defender") or "unknown",
            predict,
        ),
        "ideal_hostile_matchup": _multi_residual_group_summary(rows, _ideal_hostile_matchup_keys, predict),
        "attacker_active_ship_bonus": _multi_residual_group_summary(
            rows,
            lambda row: _ship_list_keys(row, "attacker", "active_ship_bonus_ids"),
            predict,
        ),
        "defender_active_ship_bonus": _multi_residual_group_summary(
            rows,
            lambda row: _ship_list_keys(row, "defender", "active_ship_bonus_ids"),
            predict,
        ),
        "attacker_hull_ship_bonus": _multi_residual_group_summary(
            rows,
            lambda row: _hull_list_keys(row, "attacker", "ship_bonus_ids"),
            predict,
        ),
        "defender_hull_ship_bonus": _multi_residual_group_summary(
            rows,
            lambda row: _hull_list_keys(row, "defender", "ship_bonus_ids"),
            predict,
        ),
        "attacker_hull_all_ship_bonus": _multi_residual_group_summary(
            rows,
            lambda row: _hull_list_keys(row, "attacker", "all_ship_bonus_ids"),
            predict,
        ),
        "defender_hull_all_ship_bonus": _multi_residual_group_summary(
            rows,
            lambda row: _hull_list_keys(row, "defender", "all_ship_bonus_ids"),
            predict,
        ),
        "attacker_hull_activated_ability": _multi_residual_group_summary(
            rows,
            lambda row: _hull_activated_ability_keys(row, "attacker"),
            predict,
        ),
        "defender_hull_activated_ability": _multi_residual_group_summary(
            rows,
            lambda row: _hull_activated_ability_keys(row, "defender"),
            predict,
        ),
        "attacker_cloaking_ability": _residual_group_summary(
            rows,
            lambda row: str(_has_activated_ability_type(row, "attacker", "ACTIVATEDABILITYTYPE_CLOAKING")),
            predict,
        ),
        "defender_cloaking_ability": _residual_group_summary(
            rows,
            lambda row: str(_has_activated_ability_type(row, "defender", "ACTIVATEDABILITYTYPE_CLOAKING")),
            predict,
        ),
        "hostile_id_prefix": _residual_group_summary(rows, _hostile_id_prefix, predict),
        "isolytic_triggered": _residual_group_summary(
            rows,
            lambda row: str("isolytic" in row.get("observed", {}).get("triggered_effects", [])),
            predict,
        ),
        "shield_active_before_shot": _residual_group_summary(
            rows,
            lambda row: str(_shield_active_before_shot(row)),
            predict,
        ),
        "officer_ability": _multi_residual_group_summary(rows, _officer_ability_keys, predict),
        "officer_modifier": _multi_residual_group_summary(rows, _officer_modifier_keys, predict),
        "officer_formula_stage": _multi_residual_group_summary(
            rows,
            _officer_formula_stage_keys,
            predict,
        ),
        "officer_stage_modifier": _multi_residual_group_summary(
            rows,
            _officer_stage_modifier_keys,
            predict,
        ),
        "officer_id": _multi_residual_group_summary(rows, _officer_id_keys, predict),
    }


def _pearson_correlation(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < 2:
        return None
    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    x_stddev = _stddev(xs)
    y_stddev = _stddev(ys)
    if x_stddev == 0.0 or y_stddev == 0.0:
        return None
    x_mean = _mean(xs)
    y_mean = _mean(ys)
    covariance = _mean([(x - x_mean) * (y - y_mean) for x, y in pairs])
    return covariance / (x_stddev * y_stddev)


def _numeric_factor(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _fleet_factor_entry(
    rows: list[dict[str, Any]],
    residuals: list[float],
    *,
    role: str,
    source: str,
    key: str,
) -> dict[str, Any]:
    values: list[float] = []
    residual_pairs: list[tuple[float, float]] = []
    for row, residual in zip(rows, residuals, strict=True):
        ship = row.get(role, {})
        if not isinstance(ship, dict):
            continue
        factors = ship.get(source, {})
        if not isinstance(factors, dict):
            continue
        value = _numeric_factor(factors.get(key))
        if value is None:
            continue
        values.append(value)
        residual_pairs.append((value, residual))
    return {
        "present_count": len(values),
        "distribution": _distribution(values),
        "residual_correlation": _pearson_correlation(residual_pairs),
    }


def _formula_input_ratio_summary(
    rows: list[dict[str, Any]],
    *,
    role: str,
    source: str,
    key: str,
    formula_stat_source: str,
) -> dict[str, Any]:
    ratios: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        ship = row.get(role, {})
        if not isinstance(ship, dict):
            continue
        factors = ship.get(source, {})
        if not isinstance(factors, dict):
            continue
        value = _numeric_factor(factors.get(key))
        if value is None:
            continue
        stat_inputs = combat_triangle_features(row, stat_source=formula_stat_source)["stat_inputs"]
        for lane in ("armor", "shield", "dodge"):
            defense = _numeric_factor((stat_inputs.get(lane) or {}).get("defense"))
            if defense is None or defense == 0.0:
                continue
            ratios[f"{key}_to_formula_{lane}_defense"].append(value / defense)
    return {name: _distribution(values) for name, values in ratios.items()}


def _combat_triangle_prediction_from_inputs(
    *,
    row: dict[str, Any],
    stat_inputs: dict[str, dict[str, Any]],
    weights: dict[str, Any],
    include_apex_barrier: bool,
) -> float:
    components = {
        lane: _combat_triangle_component(values.get("defense"), values.get("piercing"))
        for lane, values in stat_inputs.items()
    }
    prediction = _clamp_mitigation(
        1.0
        - math.prod(
            1.0 - float(weights[lane]) * float(components[lane])
            for lane in ("armor", "shield", "dodge")
        )
    )
    if include_apex_barrier:
        return _combine_mitigation_stages(prediction, _apex_barrier_stage_mitigation(row))
    return prediction


def _scaled_defender_rating_prediction(
    row: dict[str, Any],
    *,
    rating_scale: float,
    lanes: tuple[str, ...],
    formula_stat_source: str,
) -> float:
    features = combat_triangle_features(row, stat_source=formula_stat_source)
    stat_inputs = {
        lane: dict(values)
        for lane, values in features["stat_inputs"].items()
        if isinstance(values, dict)
    }
    defender = row.get("defender", {})
    ratings = defender.get("captured_fleet_ratings", {}) if isinstance(defender, dict) else {}
    defense_rating = _numeric_factor(ratings.get("defense_rating")) if isinstance(ratings, dict) else None
    if defense_rating is None:
        return _combat_triangle_prediction_from_inputs(
            row=row,
            stat_inputs=stat_inputs,
            weights=features["weights"],
            include_apex_barrier=False,
        )
    for lane in lanes:
        lane_inputs = stat_inputs.get(lane)
        if not isinstance(lane_inputs, dict):
            continue
        lane_inputs["defense"] = _number(lane_inputs.get("defense")) + defense_rating * rating_scale
    return _combat_triangle_prediction_from_inputs(
        row=row,
        stat_inputs=stat_inputs,
        weights=features["weights"],
        include_apex_barrier=False,
    )


def _required_defender_rating_scale(
    row: dict[str, Any],
    *,
    lanes: tuple[str, ...],
    formula_stat_source: str,
) -> float | None:
    target = _target(row)
    current = _scaled_defender_rating_prediction(
        row,
        rating_scale=0.0,
        lanes=lanes,
        formula_stat_source=formula_stat_source,
    )
    if current >= target:
        return 0.0
    high = 1.0
    while high <= 10.0:
        prediction = _scaled_defender_rating_prediction(
            row,
            rating_scale=high,
            lanes=lanes,
            formula_stat_source=formula_stat_source,
        )
        if prediction >= target:
            break
        high *= 2.0
    if high > 10.0:
        return None
    low = 0.0
    for _ in range(48):
        mid = (low + high) / 2.0
        prediction = _scaled_defender_rating_prediction(
            row,
            rating_scale=mid,
            lanes=lanes,
            formula_stat_source=formula_stat_source,
        )
        if prediction < target:
            low = mid
        else:
            high = mid
    return high


def _required_defender_rating_scale_summary(
    rows: list[dict[str, Any]],
    *,
    formula_stat_source: str,
) -> dict[str, Any]:
    modes = {
        "all_defense_lanes": ("armor", "shield", "dodge"),
        "armor_only": ("armor",),
        "shield_only": ("shield",),
        "dodge_only": ("dodge",),
    }
    summaries = {}
    for name, lanes in modes.items():
        values = [
            scale
            for row in rows
            if (
                scale := _required_defender_rating_scale(
                    row,
                    lanes=lanes,
                    formula_stat_source=formula_stat_source,
                )
            )
            is not None
        ]
        summaries[name] = {
            "lanes": list(lanes),
            "scale_distribution": _distribution(values),
            "percent_distribution": _distribution([value * 100.0 for value in values]),
        }
    return summaries


def _fleet_input_factor_diagnostics(
    rows: list[dict[str, Any]],
    predict: Callable[[dict[str, Any]], float],
    *,
    formula_stat_source: str,
) -> dict[str, Any]:
    residuals = [predict(row) - _target(row) for row in rows]
    roles = {}
    for role in ("attacker", "defender"):
        attribute_entries = {
            code: _fleet_factor_entry(
                rows,
                residuals,
                role=role,
                source="captured_fleet_attributes",
                key=code,
            )
            for code in FLEET_ATTRIBUTE_FACTOR_CODES
        }
        rating_entries = {
            field: _fleet_factor_entry(
                rows,
                residuals,
                role=role,
                source="captured_fleet_ratings",
                key=field,
            )
            for field in FLEET_RATING_FACTOR_FIELDS
        }
        roles[role] = {
            "captured_fleet_attributes": {
                code: entry for code, entry in attribute_entries.items() if entry["present_count"] > 0
            },
            "captured_fleet_ratings": {
                field: entry for field, entry in rating_entries.items() if entry["present_count"] > 0
            },
        }
        if role == "defender":
            roles[role]["rating_to_formula_defense_ratios"] = _formula_input_ratio_summary(
                rows,
                role=role,
                source="captured_fleet_ratings",
                key="defense_rating",
                formula_stat_source=formula_stat_source,
            )
            roles[role]["attribute_to_formula_defense_ratios"] = _formula_input_ratio_summary(
                rows,
                role=role,
                source="captured_fleet_attributes",
                key="-9",
                formula_stat_source=formula_stat_source,
            )
            roles[role]["required_defender_defense_rating_scale_to_match_target"] = (
                _required_defender_rating_scale_summary(rows, formula_stat_source=formula_stat_source)
            )
    return {
        "purpose": (
            "Report-only inventory of captured fleet aggregate inputs that are available in battle journals but are "
            "not part of the static/player-max mitigation stat reconstruction yet."
        ),
        "model": "combat_triangle_static_player_max_buffs_formula",
        "stat_source": formula_stat_source,
        "target": "observed.normal_mitigation.effective_mitigation",
        "residual_convention": "prediction - target",
        "metrics": _metrics(rows, predict),
        "roles": roles,
    }


def analyze_mitigation(*, observations_path: Path, decoded_static_dir: Path | None = None) -> dict[str, Any]:
    raw_rows = _read_observations(observations_path)
    rows = _usable_rows(raw_rows)
    cached_ratio_features = _cached_feature_fn(_ratio_features)
    cached_basic_live_features = _cached_feature_fn(_basic_live_features)
    cached_combat_triangle_calibration_features = _cached_feature_fn(_combat_triangle_calibration_features)
    cached_expanded_features = _cached_feature_fn(_expanded_features)
    mitigation_excluded_reasons = Counter(
        reason for row in raw_rows if (reason := _mitigation_fit_excluded_reason(row)) is not None
    )
    targets = [_target(row) for row in rows]
    observed_targets = [_observed_effective_mitigation(row) for row in rows]
    global_prediction = _mean(targets)
    ratio_model = _fit_linear_model(rows, feature_names=RATIO_FEATURES, feature_fn=cached_ratio_features)
    basic_live_model = _fit_linear_model(rows, feature_names=BASIC_LIVE_FEATURES, feature_fn=cached_basic_live_features)
    basic_live_nonnegative_model = _fit_nonnegative_feature_linear_model(
        rows,
        feature_names=BASIC_LIVE_FEATURES,
        feature_fn=cached_basic_live_features,
    )
    combat_triangle_model = _fit_linear_model(
        rows,
        feature_names=COMBAT_TRIANGLE_CALIBRATION_FEATURES,
        feature_fn=cached_combat_triangle_calibration_features,
    )
    side_combat_triangle_model = _fit_partitioned_linear_model(
        rows,
        partition_name="attacker_side",
        key_fn=lambda row: str(row.get("attacker_side")),
        feature_names=COMBAT_TRIANGLE_CALIBRATION_FEATURES,
        feature_fn=cached_combat_triangle_calibration_features,
    )
    side_basic_live_nonnegative_model = _fit_partitioned_nonnegative_feature_linear_model(
        rows,
        partition_name="attacker_side",
        key_fn=lambda row: str(row.get("attacker_side")),
        feature_names=BASIC_LIVE_FEATURES,
        feature_fn=cached_basic_live_features,
    )
    expanded_model = _fit_linear_model(rows, feature_names=EXPANDED_FEATURES, feature_fn=cached_expanded_features)
    side_expanded_model = _fit_partitioned_linear_model(
        rows,
        partition_name="attacker_side",
        key_fn=lambda row: str(row.get("attacker_side")),
        feature_names=EXPANDED_FEATURES,
        feature_fn=cached_expanded_features,
    )

    def predict_global(_row: dict[str, Any]) -> float:
        return global_prediction

    def predict_ratio(row: dict[str, Any]) -> float:
        return _predict_linear_model(ratio_model, row, feature_fn=cached_ratio_features)

    def predict_basic_live(row: dict[str, Any]) -> float:
        return _predict_linear_model(basic_live_model, row, feature_fn=cached_basic_live_features)

    def predict_deterministic_basic_live(row: dict[str, Any]) -> float:
        return predict_basic_live_mitigation(row)

    def predict_combat_triangle(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(row, include_apex_barrier=False)

    def predict_combat_triangle_triggered(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(row, apply_triggered_effects=True, include_apex_barrier=False)

    def predict_combat_triangle_triggered_officer_stat_percent(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(
            row,
            apply_triggered_effects=True,
            officer_stat_scale="percent",
            include_apex_barrier=False,
        )

    def predict_combat_triangle_triggered_officer_stat_raw(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(
            row,
            apply_triggered_effects=True,
            officer_stat_scale="raw",
            include_apex_barrier=False,
        )

    def predict_combat_triangle_captured(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(row, stat_source="captured_live", include_apex_barrier=False)

    def predict_combat_triangle_static(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(row, stat_source="static_base", include_apex_barrier=False)

    def predict_combat_triangle_static_player_max_buffs(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(
            row,
            stat_source="static_player_max_buffs",
            include_apex_barrier=False,
        )

    def predict_combat_triangle_swapped_stats_defender_weights(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(
            row,
            stat_role_orientation="swapped_stats_defender_weights",
            include_apex_barrier=False,
        )

    def predict_combat_triangle_swapped_stats_attacker_weights(row: dict[str, Any]) -> float:
        return predict_combat_triangle_mitigation(
            row,
            stat_role_orientation="swapped_stats_attacker_weights",
            include_apex_barrier=False,
        )

    def predict_combat_triangle_linear(row: dict[str, Any]) -> float:
        return _predict_linear_model(
            combat_triangle_model,
            row,
            feature_fn=cached_combat_triangle_calibration_features,
        )

    def predict_side_combat_triangle_linear(row: dict[str, Any]) -> float:
        partition_model = side_combat_triangle_model["partitions"].get(
            str(row.get("attacker_side")),
            side_combat_triangle_model["fallback"],
        )
        return _predict_linear_model(
            partition_model,
            row,
            feature_fn=cached_combat_triangle_calibration_features,
        )

    def predict_basic_live_nonnegative(row: dict[str, Any]) -> float:
        return _predict_linear_model(basic_live_nonnegative_model, row, feature_fn=cached_basic_live_features)

    def predict_side_basic_live_nonnegative(row: dict[str, Any]) -> float:
        partition_model = side_basic_live_nonnegative_model["partitions"].get(
            str(row.get("attacker_side")),
            side_basic_live_nonnegative_model["fallback"],
        )
        return _predict_linear_model(partition_model, row, feature_fn=cached_basic_live_features)

    def predict_expanded(row: dict[str, Any]) -> float:
        return _predict_linear_model(expanded_model, row, feature_fn=cached_expanded_features)

    def predict_side_expanded(row: dict[str, Any]) -> float:
        partition_model = side_expanded_model["partitions"].get(str(row.get("attacker_side")), side_expanded_model["fallback"])
        return _predict_linear_model(partition_model, row, feature_fn=cached_expanded_features)

    def build_ratio_predictor(training_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], float]:
        model = _fit_linear_model(training_rows, feature_names=RATIO_FEATURES, feature_fn=cached_ratio_features)
        return lambda row: _predict_linear_model(model, row, feature_fn=cached_ratio_features)

    def build_basic_live_predictor(training_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], float]:
        model = _fit_linear_model(training_rows, feature_names=BASIC_LIVE_FEATURES, feature_fn=cached_basic_live_features)
        return lambda row: _predict_linear_model(model, row, feature_fn=cached_basic_live_features)

    def build_basic_live_nonnegative_predictor(training_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], float]:
        model = _fit_nonnegative_feature_linear_model(
            training_rows,
            feature_names=BASIC_LIVE_FEATURES,
            feature_fn=cached_basic_live_features,
        )
        return lambda row: _predict_linear_model(model, row, feature_fn=cached_basic_live_features)

    def build_combat_triangle_predictor(training_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], float]:
        model = _fit_linear_model(
            training_rows,
            feature_names=COMBAT_TRIANGLE_CALIBRATION_FEATURES,
            feature_fn=cached_combat_triangle_calibration_features,
        )
        return lambda row: _predict_linear_model(
            model,
            row,
            feature_fn=cached_combat_triangle_calibration_features,
        )

    def build_side_combat_triangle_predictor(training_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], float]:
        model = _fit_partitioned_linear_model(
            training_rows,
            partition_name="attacker_side",
            key_fn=lambda row: str(row.get("attacker_side")),
            feature_names=COMBAT_TRIANGLE_CALIBRATION_FEATURES,
            feature_fn=cached_combat_triangle_calibration_features,
        )

        def predict(row: dict[str, Any]) -> float:
            partition_model = model["partitions"].get(str(row.get("attacker_side")), model["fallback"])
            return _predict_linear_model(
                partition_model,
                row,
                feature_fn=cached_combat_triangle_calibration_features,
            )

        return predict

    def build_side_basic_live_nonnegative_predictor(
        training_rows: list[dict[str, Any]],
    ) -> Callable[[dict[str, Any]], float]:
        model = _fit_partitioned_nonnegative_feature_linear_model(
            training_rows,
            partition_name="attacker_side",
            key_fn=lambda row: str(row.get("attacker_side")),
            feature_names=BASIC_LIVE_FEATURES,
            feature_fn=cached_basic_live_features,
        )

        def predict(row: dict[str, Any]) -> float:
            partition_model = model["partitions"].get(str(row.get("attacker_side")), model["fallback"])
            return _predict_linear_model(partition_model, row, feature_fn=cached_basic_live_features)

        return predict

    def build_expanded_predictor(training_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], float]:
        model = _fit_linear_model(training_rows, feature_names=EXPANDED_FEATURES, feature_fn=cached_expanded_features)
        return lambda row: _predict_linear_model(model, row, feature_fn=cached_expanded_features)

    def build_side_expanded_predictor(training_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], float]:
        model = _fit_partitioned_linear_model(
            training_rows,
            partition_name="attacker_side",
            key_fn=lambda row: str(row.get("attacker_side")),
            feature_names=EXPANDED_FEATURES,
            feature_fn=cached_expanded_features,
        )

        def predict(row: dict[str, Any]) -> float:
            partition_model = model["partitions"].get(str(row.get("attacker_side")), model["fallback"])
            return _predict_linear_model(partition_model, row, feature_fn=cached_expanded_features)

        return predict

    ratio_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_ratio_predictor,
    )
    expanded_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_expanded_predictor,
    )
    basic_live_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_basic_live_predictor,
    )
    basic_live_nonnegative_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_basic_live_nonnegative_predictor,
    )
    combat_triangle_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_combat_triangle_predictor,
    )
    side_combat_triangle_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_side_combat_triangle_predictor,
    )
    side_combat_triangle_model["leave_one_battle_out_metrics"] = side_combat_triangle_holdout_metrics
    side_basic_live_nonnegative_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_side_basic_live_nonnegative_predictor,
    )
    side_basic_live_nonnegative_model["leave_one_battle_out_metrics"] = side_basic_live_nonnegative_holdout_metrics
    side_expanded_holdout_metrics = _leave_one_group_out_metrics(
        rows,
        group_name="battle_id",
        key_fn=lambda row: str(row.get("battle_id")),
        build_predictor=build_side_expanded_predictor,
    )
    side_expanded_model["leave_one_battle_out_metrics"] = side_expanded_holdout_metrics

    group_predictions = {
        "ratio_linear_fit": _cached_prediction_fn(predict_ratio),
        "deterministic_basic_live_formula": _cached_prediction_fn(predict_deterministic_basic_live),
        "combat_triangle_formula": _cached_prediction_fn(predict_combat_triangle),
        "combat_triangle_triggered_effects_formula": _cached_prediction_fn(predict_combat_triangle_triggered),
        "combat_triangle_triggered_officer_stat_percent_formula": _cached_prediction_fn(
            predict_combat_triangle_triggered_officer_stat_percent,
        ),
        "combat_triangle_triggered_officer_stat_raw_formula": _cached_prediction_fn(
            predict_combat_triangle_triggered_officer_stat_raw,
        ),
        "combat_triangle_captured_live_formula": _cached_prediction_fn(predict_combat_triangle_captured),
        "combat_triangle_static_base_formula": _cached_prediction_fn(predict_combat_triangle_static),
        "combat_triangle_swapped_stats_defender_weights_formula": _cached_prediction_fn(
            predict_combat_triangle_swapped_stats_defender_weights
        ),
        "combat_triangle_swapped_stats_attacker_weights_formula": _cached_prediction_fn(
            predict_combat_triangle_swapped_stats_attacker_weights
        ),
        "combat_triangle_linear_fit": _cached_prediction_fn(predict_combat_triangle_linear),
        "attacker_side_combat_triangle_linear_fit": _cached_prediction_fn(predict_side_combat_triangle_linear),
        "basic_live_linear_fit": _cached_prediction_fn(predict_basic_live),
        "basic_live_nonnegative_fit": _cached_prediction_fn(predict_basic_live_nonnegative),
        "attacker_side_basic_live_nonnegative_fit": _cached_prediction_fn(predict_side_basic_live_nonnegative),
        "expanded_linear_fit": _cached_prediction_fn(predict_expanded),
        "attacker_side_expanded_linear_fit": _cached_prediction_fn(predict_side_expanded),
    }

    analysis = {
        "schema_version": 1,
        "observations_path": str(observations_path),
        "decoded_static_dir": str(decoded_static_dir) if decoded_static_dir is not None else None,
        "scope": ANALYSIS_SCOPE,
        "summary": {
            "rows": len(rows),
            "raw_rows": len(raw_rows),
            "mitigation_fit_excluded_reasons": dict(sorted(mitigation_excluded_reasons.items())),
            "overkill_excluded_rows": mitigation_excluded_reasons.get("overkill_base_damage_gap", 0),
            "overkill_base_damage_gap_rows": sum(
                1 for row in raw_rows if _overkill_base_damage_gap(row) > OVERKILL_BASE_DAMAGE_GAP_TOLERANCE
            ),
            "critical_rows": sum(1 for row in rows if row.get("observed", {}).get("critical")),
            "officer_trigger_rows": sum(1 for row in rows if "officer" in row.get("observed", {}).get("triggered_effects", [])),
            "officer_activation_rows": sum(1 for row in rows if _officer_activations(row)),
            "officer_activation_count": sum(len(_officer_activations(row)) for row in rows),
            "shield_active_before_shot_rows": sum(1 for row in rows if _shield_active_before_shot(row)),
            "shield_inactive_before_shot_rows": sum(1 for row in rows if not _shield_active_before_shot(row)),
            "observed_effective_mitigation": _distribution(observed_targets),
            "normal_effective_mitigation": _distribution(targets),
            "isolytic_rows": sum(1 for row in rows if "isolytic" in row.get("observed", {}).get("triggered_effects", [])),
        },
        "models": {
            "global_mean": {
                "formula": "predict the global mean normal effective mitigation",
                "prediction": global_prediction,
                "metrics": _metrics(rows, predict_global),
            },
            "ratio_linear_fit": {
                "formula": (
                    "clamp(intercept + dodge_ratio*dodge_coef + plating_ratio*plating_coef + "
                    "absorption_ratio*absorption_coef, 0, 0.95)"
                ),
                "features": _feature_descriptions(RATIO_FEATURES),
                "intercept": ratio_model["intercept"],
                "coefficients": ratio_model["coefficients"],
                "regularization": ratio_model["regularization"],
                "metrics": _metrics(rows, predict_ratio),
                "leave_one_battle_out_metrics": ratio_holdout_metrics,
            },
            "deterministic_basic_live_formula": {
                "formula": (
                    "clamp((live_dodge_ratio + live_plating_ratio + live_absorption_ratio) / 3, 0, 0.95); "
                    "use resolved player stats when observations include buff-audit state, otherwise captured stats"
                ),
                "features": _feature_descriptions(BASIC_LIVE_MITIGATION_FEATURES),
                "weights": BASIC_LIVE_MITIGATION_WEIGHTS,
                "metrics": _metrics(rows, predict_deterministic_basic_live),
                "feature_summary": {
                    feature: _distribution([deterministic_basic_live_features(row)[feature] for row in rows])
                    for feature in BASIC_LIVE_MITIGATION_FEATURES
                },
            },
            "combat_triangle_formula": {
                "formula": (
                    "1 - product(1 - hull_weight * 1 / (1 + 4 ** (1.1 - defense_stat / piercing_stat)))) "
                    "for armor/plating, shield-deflection/absorption, and dodge"
                ),
                "composition": "weighted_product",
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "resolved_player_live",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["resolved_player_live"],
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle),
                "feature_summary": {
                    "armor": _distribution(
                        [float(combat_triangle_features(row)["components"]["armor"]) for row in rows]
                    ),
                    "shield": _distribution(
                        [float(combat_triangle_features(row)["components"]["shield"]) for row in rows]
                    ),
                    "dodge": _distribution(
                        [float(combat_triangle_features(row)["components"]["dodge"]) for row in rows]
                    ),
                },
            },
            "combat_triangle_triggered_effects_formula": {
                "formula": (
                    "same combat-triangle formula as combat_triangle_formula, after applying mapped triggered "
                    "normal_mitigation_triangle officer/ship-bonus stat operations to attacker piercing and defender defense stats"
                ),
                "composition": "weighted_product",
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "resolved_player_live",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["resolved_player_live"],
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_triggered),
                "adjusted_rows": sum(
                    1 for row in rows if combat_triangle_features(row, apply_triggered_effects=True)["stat_adjustments"]
                ),
                "adjustment_count": sum(
                    len(combat_triangle_features(row, apply_triggered_effects=True)["stat_adjustments"])
                    for row in rows
                ),
                "feature_summary": {
                    "armor": _distribution(
                        [
                            float(
                                combat_triangle_features(row, apply_triggered_effects=True)["components"]["armor"]
                            )
                            for row in rows
                        ]
                    ),
                    "shield": _distribution(
                        [
                            float(
                                combat_triangle_features(row, apply_triggered_effects=True)["components"]["shield"]
                            )
                            for row in rows
                        ]
                    ),
                    "dodge": _distribution(
                        [
                            float(
                                combat_triangle_features(row, apply_triggered_effects=True)["components"]["dodge"]
                            )
                            for row in rows
                        ]
                    ),
                },
            },
            "combat_triangle_triggered_officer_stat_percent_formula": {
                "formula": (
                    "same combat-triangle triggered-effects formula, but triggered ability values with "
                    "attributes.officerStat are multiplied by the firing ship's captured officer stat / 100"
                ),
                "composition": "weighted_product",
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "resolved_player_live",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["resolved_player_live"],
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_triggered_officer_stat_percent),
                "adjusted_rows": sum(
                    1
                    for row in rows
                    if combat_triangle_features(
                        row,
                        apply_triggered_effects=True,
                        officer_stat_scale="percent",
                    )["stat_adjustments"]
                ),
                "adjustment_count": sum(
                    len(
                        combat_triangle_features(
                            row,
                            apply_triggered_effects=True,
                            officer_stat_scale="percent",
                        )["stat_adjustments"]
                    )
                    for row in rows
                ),
            },
            "combat_triangle_triggered_officer_stat_raw_formula": {
                "formula": (
                    "same combat-triangle triggered-effects formula, but triggered ability values with "
                    "attributes.officerStat are multiplied by the firing ship's captured officer stat without /100 scaling"
                ),
                "composition": "weighted_product",
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "resolved_player_live",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["resolved_player_live"],
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_triggered_officer_stat_raw),
                "adjusted_rows": sum(
                    1
                    for row in rows
                    if combat_triangle_features(
                        row,
                        apply_triggered_effects=True,
                        officer_stat_scale="raw",
                    )["stat_adjustments"]
                ),
                "adjustment_count": sum(
                    len(
                        combat_triangle_features(
                            row,
                            apply_triggered_effects=True,
                            officer_stat_scale="raw",
                        )["stat_adjustments"]
                    )
                    for row in rows
                ),
            },
            "combat_triangle_captured_live_formula": {
                "formula": (
                    "same combat-triangle formula as combat_triangle_formula, using captured live ship_stats only"
                ),
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "captured_live",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["captured_live"],
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_captured),
                "feature_summary": {
                    "armor": _distribution(
                        [
                            float(combat_triangle_features(row, stat_source="captured_live")["components"]["armor"])
                            for row in rows
                        ]
                    ),
                    "shield": _distribution(
                        [
                            float(combat_triangle_features(row, stat_source="captured_live")["components"]["shield"])
                            for row in rows
                        ]
                    ),
                    "dodge": _distribution(
                        [
                            float(combat_triangle_features(row, stat_source="captured_live")["components"]["dodge"])
                            for row in rows
                        ]
                    ),
                },
            },
            "combat_triangle_static_base_formula": {
                "formula": (
                    "same combat-triangle formula as combat_triangle_formula, using static hull/component base stats only"
                ),
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "static_base",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["static_base"],
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_static),
                "feature_summary": {
                    "armor": _distribution(
                        [
                            float(combat_triangle_features(row, stat_source="static_base")["components"]["armor"])
                            for row in rows
                        ]
                    ),
                    "shield": _distribution(
                        [
                            float(combat_triangle_features(row, stat_source="static_base")["components"]["shield"])
                            for row in rows
                        ]
                    ),
                    "dodge": _distribution(
                        [
                            float(combat_triangle_features(row, stat_source="static_base")["components"]["dodge"])
                            for row in rows
                        ]
                    ),
                },
            },
            "combat_triangle_static_player_max_buffs_formula": {
                "formula": (
                    "same combat-triangle formula as combat_triangle_formula, using static hull/component stats and "
                    "assuming player hull core-stat bonuses are active near max, plus resolved player triangle modifiers "
                    "for the normal mitigation stage; Apex Barrier is evaluated separately in damage_stage_pipeline"
                ),
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "static_player_max_buffs",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["static_player_max_buffs"],
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_static_player_max_buffs),
                "feature_summary": {
                    "armor": _distribution(
                        [
                            float(
                                combat_triangle_features(row, stat_source="static_player_max_buffs")["components"][
                                    "armor"
                                ]
                            )
                            for row in rows
                        ]
                    ),
                    "shield": _distribution(
                        [
                            float(
                                combat_triangle_features(row, stat_source="static_player_max_buffs")["components"][
                                    "shield"
                                ]
                            )
                            for row in rows
                        ]
                    ),
                    "dodge": _distribution(
                        [
                            float(
                                combat_triangle_features(row, stat_source="static_player_max_buffs")["components"][
                                    "dodge"
                                ]
                            )
                            for row in rows
                        ]
                    ),
                },
            },
            "combat_triangle_swapped_stats_defender_weights_formula": {
                "formula": (
                    "diagnostic only: same combat-triangle formula as combat_triangle_formula, but use the current "
                    "defender's piercing stats against the current attacker's defense stats while keeping current "
                    "defender hull weights"
                ),
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "resolved_player_live",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["resolved_player_live"],
                "stat_role_orientation": "swapped_stats_defender_weights",
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_swapped_stats_defender_weights),
            },
            "combat_triangle_swapped_stats_attacker_weights_formula": {
                "formula": (
                    "diagnostic only: same combat-triangle formula as combat_triangle_formula, but use the current "
                    "defender's piercing stats against the current attacker's defense stats and use current attacker "
                    "hull weights"
                ),
                "target": "observed.normal_mitigation.effective_mitigation",
                "stat_source": "resolved_player_live",
                "stat_source_description": COMBAT_TRIANGLE_STAT_SOURCES["resolved_player_live"],
                "stat_role_orientation": "swapped_stats_attacker_weights",
                "defender_hull_weights": COMBAT_TRIANGLE_WEIGHTS,
                "metrics": _metrics(rows, predict_combat_triangle_swapped_stats_attacker_weights),
            },
            "combat_triangle_linear_fit": {
                "formula": "clamp(intercept + combat_triangle_prediction*combat_triangle_coef, 0, 0.95)",
                "features": _feature_descriptions(COMBAT_TRIANGLE_CALIBRATION_FEATURES),
                "intercept": combat_triangle_model["intercept"],
                "coefficients": combat_triangle_model["coefficients"],
                "regularization": combat_triangle_model["regularization"],
                "metrics": _metrics(rows, predict_combat_triangle_linear),
                "leave_one_battle_out_metrics": combat_triangle_holdout_metrics,
            },
            "attacker_side_combat_triangle_linear_fit": side_combat_triangle_model,
            "basic_live_linear_fit": {
                "formula": (
                    "clamp(intercept + live_dodge_ratio*dodge_coef + live_plating_ratio*plating_coef + "
                    "live_absorption_ratio*absorption_coef, 0, 0.95)"
                ),
                "features": _feature_descriptions(BASIC_LIVE_FEATURES),
                "intercept": basic_live_model["intercept"],
                "coefficients": basic_live_model["coefficients"],
                "regularization": basic_live_model["regularization"],
                "metrics": _metrics(rows, predict_basic_live),
                "leave_one_battle_out_metrics": basic_live_holdout_metrics,
            },
            "basic_live_nonnegative_fit": {
                "formula": (
                    "clamp(intercept + live_dodge_ratio*dodge_coef + live_plating_ratio*plating_coef + "
                    "live_absorption_ratio*absorption_coef, 0, 0.95)"
                ),
                "features": _feature_descriptions(BASIC_LIVE_FEATURES),
                "intercept": basic_live_nonnegative_model["intercept"],
                "coefficients": basic_live_nonnegative_model["coefficients"],
                "regularization": basic_live_nonnegative_model["regularization"],
                "constraint": basic_live_nonnegative_model["constraint"],
                "active_features": basic_live_nonnegative_model["active_features"],
                "metrics": _metrics(rows, predict_basic_live_nonnegative),
                "leave_one_battle_out_metrics": basic_live_nonnegative_holdout_metrics,
            },
            "attacker_side_basic_live_nonnegative_fit": side_basic_live_nonnegative_model,
            "expanded_linear_fit": {
                "formula": "clamp(intercept + sum(feature_value * coefficient), 0, 0.95)",
                "features": _feature_descriptions(EXPANDED_FEATURES),
                "intercept": expanded_model["intercept"],
                "coefficients": expanded_model["coefficients"],
                "regularization": expanded_model["regularization"],
                "metrics": _metrics(rows, predict_expanded),
                "leave_one_battle_out_metrics": expanded_holdout_metrics,
            },
            "attacker_side_expanded_linear_fit": side_expanded_model,
        },
        "groups": {
            "battle_type": _group_summary(
                rows,
                lambda row: battle_type_label(row.get("battle_type")),
                group_predictions,
            ),
            "attacker_side": _group_summary(rows, lambda row: str(row.get("attacker_side")), group_predictions),
            "weapon": _group_summary(rows, lambda row: str(row.get("weapon", {}).get("id")), group_predictions),
            "defender_hull": _group_summary(rows, lambda row: str(row.get("defender", {}).get("hull_id")), group_predictions),
            "attacker_hull_name": _group_summary(rows, lambda row: _hull_label(row, "attacker"), group_predictions),
            "defender_hull_name": _group_summary(rows, lambda row: _hull_label(row, "defender"), group_predictions),
            "defender_hull_type": _group_summary(rows, lambda row: _hull_type(row, "defender") or "unknown", group_predictions),
            "ideal_hostile_matchup": _multi_group_summary(rows, _ideal_hostile_matchup_keys, group_predictions),
            "attacker_active_ship_bonus": _multi_group_summary(
                rows,
                lambda row: _ship_list_keys(row, "attacker", "active_ship_bonus_ids"),
                group_predictions,
            ),
            "defender_active_ship_bonus": _multi_group_summary(
                rows,
                lambda row: _ship_list_keys(row, "defender", "active_ship_bonus_ids"),
                group_predictions,
            ),
            "attacker_hull_ship_bonus": _multi_group_summary(
                rows,
                lambda row: _hull_list_keys(row, "attacker", "ship_bonus_ids"),
                group_predictions,
            ),
            "defender_hull_ship_bonus": _multi_group_summary(
                rows,
                lambda row: _hull_list_keys(row, "defender", "ship_bonus_ids"),
                group_predictions,
            ),
            "attacker_hull_all_ship_bonus": _multi_group_summary(
                rows,
                lambda row: _hull_list_keys(row, "attacker", "all_ship_bonus_ids"),
                group_predictions,
            ),
            "defender_hull_all_ship_bonus": _multi_group_summary(
                rows,
                lambda row: _hull_list_keys(row, "defender", "all_ship_bonus_ids"),
                group_predictions,
            ),
            "attacker_hull_activated_ability": _multi_group_summary(
                rows,
                lambda row: _hull_activated_ability_keys(row, "attacker"),
                group_predictions,
            ),
            "defender_hull_activated_ability": _multi_group_summary(
                rows,
                lambda row: _hull_activated_ability_keys(row, "defender"),
                group_predictions,
            ),
            "attacker_cloaking_ability": _group_summary(
                rows,
                lambda row: str(_has_activated_ability_type(row, "attacker", "ACTIVATEDABILITYTYPE_CLOAKING")),
                group_predictions,
            ),
            "defender_cloaking_ability": _group_summary(
                rows,
                lambda row: str(_has_activated_ability_type(row, "defender", "ACTIVATEDABILITYTYPE_CLOAKING")),
                group_predictions,
            ),
            "hostile_id_prefix": _group_summary(rows, _hostile_id_prefix, group_predictions),
            "critical": _group_summary(rows, lambda row: str(bool(row.get("observed", {}).get("critical"))), group_predictions),
            "isolytic_triggered": _group_summary(
                rows,
                lambda row: str("isolytic" in row.get("observed", {}).get("triggered_effects", [])),
                group_predictions,
            ),
            "shield_active_before_shot": _group_summary(
                rows,
                lambda row: str(_shield_active_before_shot(row)),
                group_predictions,
            ),
            "officer_ability": _multi_group_summary(rows, _officer_ability_keys, group_predictions),
            "officer_modifier": _multi_group_summary(rows, _officer_modifier_keys, group_predictions),
            "officer_formula_stage": _multi_group_summary(rows, _officer_formula_stage_keys, group_predictions),
            "officer_stage_modifier": _multi_group_summary(rows, _officer_stage_modifier_keys, group_predictions),
            "officer_id": _multi_group_summary(rows, _officer_id_keys, group_predictions),
        },
        "weapon_actuals": {
            "purpose": "explain residuals by static weapon stats; these values are not separate mitigation tables",
            "by_weapon": _weapon_actuals_group_summary(rows, lambda row: str(row.get("weapon", {}).get("id"))),
            "by_damage_type": _weapon_actuals_group_summary(
                rows,
                lambda row: str(row.get("weapon", {}).get("damage_type") or "unknown"),
            ),
        },
        "combat_triangle_residuals": _combat_triangle_residual_groups(rows, predict_combat_triangle),
        "combat_triangle_triggered_officer_stat_percent_residuals": {
            "model": "combat_triangle_triggered_officer_stat_percent_formula",
            "purpose": "post-triggered-effect residual localization for the normal stat-role formula",
            "groups": _combat_triangle_residual_groups(rows, predict_combat_triangle_triggered_officer_stat_percent),
        },
        "combat_triangle_swapped_stats_defender_weights_residuals": {
            "model": "combat_triangle_swapped_stats_defender_weights_formula",
            "purpose": "diagnostic residual localization for swapped stat roles with current defender hull weights",
            "groups": _combat_triangle_residual_groups(rows, predict_combat_triangle_swapped_stats_defender_weights),
        },
        "officer_effect_ablation": {
            "purpose": (
                "Compare combat-triangle residuals for rows where each triggered officer/ship-bonus effect fires "
                "against all usable rows where that specific effect does not fire. This localizes formula-stage "
                "candidates; it does not apply the effect yet."
            ),
            "model": "combat_triangle_formula",
            "formula_stage_registry": FORMULA_STAGE_REGISTRY,
            "by_ability": _officer_activation_ablation_summary(rows, predict_combat_triangle),
            "by_ability_with_triggered_effects_applied": _officer_activation_ablation_summary(
                rows,
                predict_combat_triangle_triggered,
            ),
            "by_ability_with_officer_stat_percent_triggered_effects_applied": _officer_activation_ablation_summary(
                rows,
                predict_combat_triangle_triggered_officer_stat_percent,
            ),
            "by_ability_with_officer_stat_raw_triggered_effects_applied": _officer_activation_ablation_summary(
                rows,
                predict_combat_triangle_triggered_officer_stat_raw,
            ),
        },
        "combat_triangle_composition_variants": _combat_triangle_composition_variants(rows),
        "combat_triangle_static_player_max_buffs_curve_base_variants": (
            _combat_triangle_static_player_max_buffs_curve_base_variants(rows)
        ),
        "combat_triangle_stat_role_orientation_variants": _combat_triangle_stat_role_orientation_variants(rows),
        "input_factor_diagnostics": _fleet_input_factor_diagnostics(
            rows,
            predict_combat_triangle_static_player_max_buffs,
            formula_stat_source="static_player_max_buffs",
        ),
        "data_gaps": _formula_data_gaps(rows),
        "damage_pipeline": {
            "observed_mitigation_replay": evaluate_observed_mitigation_damage_replay(raw_rows),
            "observed_isolytic_damage_replay": evaluate_observed_isolytic_damage_replay(raw_rows),
            "observed_apex_barrier_replay": evaluate_observed_apex_barrier_replay(raw_rows),
        },
        "live_stat_scaling": _stat_scaling_rows(rows),
        "live_stat_scaling_by_hull": _stat_scaling_rows(rows, by_hull=True),
        "live_stat_scaling_by_hull_type": _stat_scaling_rows(rows, by_hull_type=True),
        "notes": [
            "Deterministic toolbox mechanics are reported separately from empirical diagnostic fits.",
            "Metrics are in-sample. Use more captures before trusting generalization.",
            "Leave-one-battle-out metrics are a rough guardrail against memorizing repeated attacks in the same battle.",
            "Expanded coefficients are useful for hypothesis generation but can overfit repeated battle structures.",
            "Basic live-stat models use captured attacker attack ratings instead of static per-weapon ratings.",
            "Normal mitigation metrics subtract observed isolytic damage before computing the mitigation target.",
            "Shield absorption is fully active for a shot when pre-shot shield HP is above 0; it is not scaled down by remaining shield HP.",
            "Observed hit and crit outcomes are treated as known; RNG is out of scope for this pass.",
        ],
    }
    models = analysis["models"]
    for name in (
        "global_mean",
        "ratio_linear_fit",
        "combat_triangle_linear_fit",
        "attacker_side_combat_triangle_linear_fit",
        "basic_live_linear_fit",
        "basic_live_nonnegative_fit",
        "attacker_side_basic_live_nonnegative_fit",
        "expanded_linear_fit",
        "attacker_side_expanded_linear_fit",
    ):
        _tag_input_class(models[name], "validation_only", ["observed mitigation targets"])
    for name in (
        "deterministic_basic_live_formula",
        "combat_triangle_formula",
        "combat_triangle_triggered_effects_formula",
        "combat_triangle_triggered_officer_stat_percent_formula",
        "combat_triangle_triggered_officer_stat_raw_formula",
        "combat_triangle_captured_live_formula",
        "combat_triangle_swapped_stats_defender_weights_formula",
        "combat_triangle_swapped_stats_attacker_weights_formula",
    ):
        _tag_input_class(models[name], "validation_only", ["captured live ship stats or battle-log triggered effects"])
    _tag_input_class(
        models["combat_triangle_static_base_formula"],
        "static_composable",
        ["static hulls", "static components", "static weapons"],
    )
    _tag_input_class(
        models["combat_triangle_static_player_max_buffs_formula"],
        "synced_profile",
        ["static hulls", "static components", "static weapons", "synced profile buffs", "user-selected active buffs"],
    )
    analysis["simulator_goal"] = _simulator_goal(models)
    analysis["broad_formula_goal"] = _broad_formula_goal(raw_rows, predict_combat_triangle_static_player_max_buffs)
    analysis["models"] = {
        "toolbox_mechanics": {
            "deterministic_basic_live_formula": models["deterministic_basic_live_formula"],
            "combat_triangle_formula": models["combat_triangle_formula"],
            "combat_triangle_triggered_effects_formula": models["combat_triangle_triggered_effects_formula"],
            "combat_triangle_triggered_officer_stat_percent_formula": models[
                "combat_triangle_triggered_officer_stat_percent_formula"
            ],
            "combat_triangle_triggered_officer_stat_raw_formula": models[
                "combat_triangle_triggered_officer_stat_raw_formula"
            ],
            "combat_triangle_captured_live_formula": models["combat_triangle_captured_live_formula"],
            "combat_triangle_static_base_formula": models["combat_triangle_static_base_formula"],
            "combat_triangle_static_player_max_buffs_formula": models[
                "combat_triangle_static_player_max_buffs_formula"
            ],
            "combat_triangle_swapped_stats_defender_weights_formula": models[
                "combat_triangle_swapped_stats_defender_weights_formula"
            ],
            "combat_triangle_swapped_stats_attacker_weights_formula": models[
                "combat_triangle_swapped_stats_attacker_weights_formula"
            ],
        },
    }
    analysis["diagnostic_fits"] = {
        "purpose": "residual/error localization only; not an authoritative combat formula",
        "global_mean": models["global_mean"],
        "ratio_linear_fit": models["ratio_linear_fit"],
        "combat_triangle_linear_fit": models["combat_triangle_linear_fit"],
        "attacker_side_combat_triangle_linear_fit": models["attacker_side_combat_triangle_linear_fit"],
        "basic_live_linear_fit": models["basic_live_linear_fit"],
        "basic_live_nonnegative_fit": models["basic_live_nonnegative_fit"],
        "attacker_side_basic_live_nonnegative_fit": models["attacker_side_basic_live_nonnegative_fit"],
        "expanded_linear_fit": models["expanded_linear_fit"],
        "attacker_side_expanded_linear_fit": models["attacker_side_expanded_linear_fit"],
    }
    if decoded_static_dir is not None:
        apex_source_index = build_apex_source_index(decoded_static_dir)
        analysis["damage_pipeline"]["observed_apex_barrier_replay"]["source_candidates"] = (
            evaluate_apex_source_candidates(raw_rows, apex_source_index)
        )
    analysis["damage_stage_pipeline"] = analysis["damage_pipeline"]
    return analysis


def write_mitigation_analysis(*, analysis: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
