from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.mitigation_analysis import (
    _basic_live_features,
    _expanded_features,
    _fit_synced_context_residual_model,
    _ideal_hostile_matchup_keys,
    _leave_one_group_out_metrics,
    _predict_synced_context_residual_model,
    _target,
    analyze_mitigation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _observation(
    *,
    battle_id: str,
    attacker_side: str,
    weapon_id: str,
    defender_hull_id: str,
    accuracy: float,
    penetration: float,
    modulation: float,
    dodge: float,
    plating: float,
    absorption: float,
    observed: float,
    attacker_accuracy: float = 100,
    attacker_armor_piercing: float = 200,
    attacker_shield_piercing: float = 300,
    critical: bool = False,
    shots: int = 1,
    crit_modifier: float = 1.5,
    weapon_name: str = "Weap_Energy_Test",
    attacker_hull_type: str = "HULLTYPE_EXPLORER",
    defender_hull_type: str = "HULLTYPE_EXPLORER",
    shield_damage: int = 100,
    remaining_shield: int = 0,
    isolytic_damage: int = 0,
    triggered_effects: list[str] | None = None,
    officer_activations: list[dict[str, object]] | None = None,
    damage_type: str | None = "energy",
    battle_type: int = 2,
    player_battle_data_type: int = 0,
    hostile_battle_data_type: int = 0,
) -> dict[str, object]:
    normal_observed = max(0, 1000 - 1000 * observed - isolytic_damage)
    normal_raw = normal_observed + 1000 * observed
    weapon = {
        "id": weapon_id,
        "accuracy": accuracy,
        "penetration": penetration,
        "modulation": modulation,
        "minimum_damage": 100,
        "maximum_damage": 200,
        "shots": shots,
        "crit_modifier": crit_modifier,
        "name": weapon_name,
    }
    if damage_type is not None:
        weapon["damage_type"] = damage_type
    row = {
        "battle_id": battle_id,
        "battle_type": battle_type,
        "player_battle_data_type": player_battle_data_type,
        "hostile_battle_data_type": hostile_battle_data_type,
        "attacker_side": attacker_side,
        "defender_side": "hostile" if attacker_side == "player" else "player",
        "weapon": weapon,
        "attacker": {
            "hull_id": "attacker-hull",
            "captured_stats": {
                "6": attacker_accuracy,
                "7": attacker_armor_piercing,
                "8": attacker_shield_piercing,
            },
            "static_ship": {
                "base_stats": {
                    "weapon_accuracy_max": 50,
                    "weapon_penetration_max": 100,
                    "weapon_modulation_max": 150,
                },
                "hull": {
                    "id": "attacker-hull",
                    "name": "Attacker Hull",
                    "type": attacker_hull_type,
                    "grade": 3,
                },
            },
        },
        "defender": {
            "hull_id": defender_hull_id,
            "captured_stats": {
                "11": dodge,
                "-3": plating,
                "-2": absorption,
            },
            "static_ship": {
                "base_stats": {
                    "dodge": dodge,
                    "armor_plating": plating,
                    "shield_absorption": absorption,
                    "shield_mitigation": 0.8,
                },
                "hull": {
                    "id": defender_hull_id,
                    "name": "Defender Hull",
                    "type": defender_hull_type,
                    "grade": 3,
                },
            },
        },
        "observed": {
            "hit": True,
            "critical": critical,
            "effective_mitigation": observed,
            "raw_damage": 1000,
            "damage": {
                "hull": 0,
                "shield": shield_damage,
            },
            "remaining": {
                "hull": 1000,
                "shield": remaining_shield,
            },
            "isolytic_damage": isolytic_damage,
            "mitigated_damage": 1000 * observed,
            "normal_mitigation": {
                "observed_damage": normal_observed,
                "raw_damage": normal_raw,
                "mitigated_damage": 1000 * observed,
                "effective_mitigation": (1000 * observed) / normal_raw if normal_raw else 0.0,
                "excluded_isolytic_damage": isolytic_damage,
                "excluded_mitigated_isolytic_damage": 0,
            },
            "mitigated_apex_barrier": 0,
            "triggered_effects": triggered_effects or [],
        },
    }
    if officer_activations is not None:
        row["observed"]["officer_activations"] = officer_activations
    return row


class MitigationAnalysisTests(unittest.TestCase):
    def test_leave_one_group_out_metrics_can_cap_large_group_sets(self) -> None:
        rows = [
            {"battle_id": str(index), "observed": {"normal_mitigation": {"effective_mitigation": 0.25}}}
            for index in range(5)
        ]

        metrics = _leave_one_group_out_metrics(
            rows,
            group_name="battle_id",
            key_fn=lambda row: str(row["battle_id"]),
            build_predictor=lambda _training_rows: (lambda _row: 0.25),
            max_groups=2,
        )

        self.assertEqual(5, metrics["groups"])
        self.assertEqual(2, metrics["evaluated_groups"])
        self.assertEqual(2, metrics["evaluation_limit"])
        self.assertEqual(3, metrics["skipped_groups"])
        self.assertEqual("deterministic_evenly_spaced_groups", metrics["sampling"])

    def test_analyze_mitigation_sets_armada_rows_aside_from_1v1_pve_fit(self) -> None:
        observations = [
            _observation(
                battle_id="1",
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=100,
                penetration=200,
                modulation=300,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.25,
            ),
            _observation(
                battle_id="2",
                attacker_side="player",
                weapon_id="w2",
                defender_hull_id="h2",
                accuracy=100,
                penetration=200,
                modulation=300,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.25,
                battle_type=8,
                player_battle_data_type=2,
            ),
        ]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in observations), encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(1, analysis["summary"]["rows"])
        self.assertEqual(2, analysis["summary"]["raw_rows"])
        self.assertEqual({"armada_battle_scope": 1}, analysis["summary"]["mitigation_fit_excluded_reasons"])
        self.assertEqual("1v1_pve", analysis["scope"]["name"])
        self.assertEqual(
            [
                "armada_battle_scope",
                "cutting_beam_bypasses_mitigation",
                "chain_shot_special_damage",
                "normal_damage_capped_by_isolytic_overkill",
            ],
            analysis["scope"]["excluded_reasons"],
        )
        broad_goal = analysis["broad_formula_goal"]
        self.assertEqual("synced_standard_armada_wave", broad_goal["scope"]["name"])
        self.assertEqual(1, broad_goal["usable_rows_by_battle_class"]["standard_hostile"])
        self.assertEqual(1, broad_goal["usable_rows_by_battle_class"]["armada"])
        self.assertEqual(0, broad_goal["usable_rows_by_battle_class"]["wave_defense"])
        self.assertIn("combat_triangle_static_player_max_buffs_formula", broad_goal["candidate_metrics"])
        self.assertIn("combat_triangle_synced_linear_formula", broad_goal["candidate_metrics"])
        self.assertIn("combat_triangle_synced_context_residual_formula", broad_goal["candidate_metrics"])
        self.assertIn(
            "cross_validation_metrics",
            broad_goal["candidate_metrics"]["combat_triangle_synced_linear_formula"],
        )

    def test_synced_context_residual_model_applies_supported_group_bias(self) -> None:
        rows = [
            _observation(
                battle_id=str(index),
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=100,
                penetration=200,
                modulation=300,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.25,
            )
            for index in range(2)
        ]
        model = _fit_synced_context_residual_model(rows, lambda _row: 0.35, min_group_rows=2)

        self.assertEqual(1, model["corrected_groups"])
        self.assertAlmostEqual(
            _target(rows[0]),
            _predict_synced_context_residual_model(rows[0], model=model, base_predict=lambda _row: 0.35),
        )

    def test_analyze_mitigation_reports_captured_fleet_input_factors(self) -> None:
        row = _observation(
            battle_id="1",
            attacker_side="hostile",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            observed=0.25,
        )
        row["defender"]["captured_fleet_attributes"] = {"-9": 448290.0, "-16": 5.0}
        row["defender"]["captured_fleet_ratings"] = {"defense_rating": 448290.0}

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        diagnostics = analysis["input_factor_diagnostics"]
        self.assertEqual("combat_triangle_static_player_max_buffs_formula", diagnostics["model"])
        defender = diagnostics["roles"]["defender"]
        self.assertEqual(1, defender["captured_fleet_attributes"]["-9"]["present_count"])
        self.assertEqual(1, defender["captured_fleet_attributes"]["-16"]["present_count"])
        self.assertEqual(1, defender["captured_fleet_ratings"]["defense_rating"]["present_count"])
        self.assertEqual(
            448290.0 / 100,
            defender["rating_to_formula_defense_ratios"]["defense_rating_to_formula_armor_defense"]["mean"],
        )

    def test_expanded_features_include_cloak_and_hostile_prefix_context(self) -> None:
        row = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            observed=0.25,
        )
        row["hostile_id_prefix"] = "npc"
        row["attacker"]["static_ship"]["hull"]["activated_abilities"] = [
            {"id": "cloak", "ability_type": "ACTIVATEDABILITYTYPE_CLOAKING"}
        ]

        features = _expanded_features(row)

        self.assertEqual(1.0, features["attacker_cloaking_ability"])
        self.assertEqual(0.0, features["defender_cloaking_ability"])
        self.assertEqual(0.0, features["hostile_id_mar_prefix"])
        self.assertEqual(1.0, features["hostile_id_npc_prefix"])

    def test_analyze_mitigation_sets_cutting_beam_rows_aside_from_normal_weapon_fit(self) -> None:
        observations = [
            _observation(
                battle_id="1",
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=100,
                penetration=200,
                modulation=300,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.25,
            ),
            _observation(
                battle_id="2",
                attacker_side="player",
                weapon_id="cutting-beam",
                defender_hull_id="h2",
                accuracy=0,
                penetration=0,
                modulation=0,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.0,
                battle_type=13,
                shield_damage=0,
                remaining_shield=1000,
            ),
        ]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in observations), encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(1, analysis["summary"]["rows"])
        self.assertEqual(2, analysis["summary"]["raw_rows"])
        self.assertEqual(
            {"cutting_beam_bypasses_mitigation": 1},
            analysis["summary"]["mitigation_fit_excluded_reasons"],
        )

    def test_analyze_mitigation_sets_chain_shot_rows_aside_from_normal_weapon_fit(self) -> None:
        observations = [
            _observation(
                battle_id="1",
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=100,
                penetration=200,
                modulation=300,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.25,
            ),
            _observation(
                battle_id="2",
                attacker_side="player",
                weapon_id="0",
                defender_hull_id="h2",
                accuracy=0,
                penetration=0,
                modulation=0,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.0,
                battle_type=15,
                shield_damage=0,
                remaining_shield=1000,
            ),
        ]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in observations), encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(1, analysis["summary"]["rows"])
        self.assertEqual(2, analysis["summary"]["raw_rows"])
        self.assertEqual(
            {"chain_shot_special_damage": 1},
            analysis["summary"]["mitigation_fit_excluded_reasons"],
        )

    def test_analyzes_observation_jsonl(self) -> None:
        observations = [
            _observation(
                battle_id="1",
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=100,
                penetration=200,
                modulation=300,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.25,
            ),
            _observation(
                battle_id="1",
                attacker_side="hostile",
                weapon_id="w2",
                defender_hull_id="h2",
                accuracy=200,
                penetration=300,
                modulation=400,
                dodge=60,
                plating=120,
                absorption=160,
                observed=0.30,
                critical=True,
                triggered_effects=["officer"],
                officer_activations=[
                    {
                        "officer_id": "officer-1",
                        "ability_buff_id": "ability-1",
                        "modifierCode": "707",
                        "op": "BUFFOPERATION_MULTIPLYADD",
                        "value": 0.25,
                        "formula_effect": {
                            "modifierCode": "707",
                            "formula_stage": "isolytic_damage",
                            "formula_inputs": ["isolytic_damage_multiplier", "isolytic_raw_damage"],
                            "confidence": "high",
                        },
                    }
                ],
                damage_type=None,
            ),
            _observation(
                battle_id="2",
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=120,
                penetration=210,
                modulation=330,
                dodge=55,
                plating=105,
                absorption=170,
                observed=0.28,
                isolytic_damage=100,
                shield_damage=800,
                triggered_effects=["isolytic"],
            ),
        ]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in observations), encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(3, analysis["summary"]["rows"])
        self.assertEqual(0, analysis["summary"]["overkill_excluded_rows"])
        self.assertIn("normal_effective_mitigation", analysis["summary"])
        self.assertNotEqual(
            analysis["summary"]["observed_effective_mitigation"]["mean"],
            analysis["summary"]["normal_effective_mitigation"]["mean"],
        )
        self.assertEqual(1, analysis["summary"]["critical_rows"])
        self.assertIn("damage_stage_pipeline", analysis)
        self.assertEqual(1, analysis["damage_stage_pipeline"]["observed_mitigation_replay"]["simple_rows"])
        self.assertEqual(0, analysis["damage_stage_pipeline"]["observed_apex_barrier_replay"]["apex_rows"])
        self.assertIn("weapon_actuals", analysis)
        self.assertEqual(
            "explain residuals by static weapon stats; these values are not separate mitigation tables",
            analysis["weapon_actuals"]["purpose"],
        )
        self.assertEqual({"w1", "w2"}, {group["key"] for group in analysis["weapon_actuals"]["by_weapon"]})
        self.assertEqual(
            {"energy", "unknown"},
            {group["key"] for group in analysis["weapon_actuals"]["by_damage_type"]},
        )
        weapon_actual = next(group for group in analysis["weapon_actuals"]["by_weapon"] if group["key"] == "w1")
        self.assertEqual(2, weapon_actual["count"])
        self.assertIn("diagnostics", weapon_actual)
        self.assertEqual(["w1"], weapon_actual["sample_weapon_ids"])
        self.assertEqual(150, weapon_actual["diagnostics"]["base_midpoint"]["mean"])
        self.assertEqual(150, weapon_actual["diagnostics"]["damage_per_shot_midpoint"]["mean"])
        self.assertEqual(0, weapon_actual["diagnostics"]["shot_count_modifier"]["mean"])
        self.assertEqual(1, weapon_actual["diagnostics"]["effective_shots"]["mean"])
        self.assertEqual(150, weapon_actual["diagnostics"]["effective_damage_midpoint"]["mean"])
        self.assertEqual(110, weapon_actual["diagnostics"]["accuracy"]["mean"])
        self.assertNotIn("observed", weapon_actual)
        self.assertNotIn("combat_triangle_formula", weapon_actual)

        self.assertIn("diagnostic_fits", analysis)
        self.assertIn("toolbox_mechanics", analysis["models"])
        self.assertEqual({"toolbox_mechanics"}, set(analysis["models"]))
        self.assertNotIn("ratio_linear_fit", analysis["models"])
        self.assertNotIn("combat_triangle_linear_fit", analysis["models"])
        toolbox = analysis["models"]["toolbox_mechanics"]
        self.assertIn("deterministic_basic_live_formula", toolbox)
        self.assertIn("combat_triangle_formula", toolbox)
        self.assertIn("combat_triangle_triggered_effects_formula", toolbox)
        self.assertIn("combat_triangle_triggered_officer_stat_percent_formula", toolbox)
        self.assertIn("combat_triangle_triggered_officer_stat_raw_formula", toolbox)
        self.assertIn("combat_triangle_captured_live_formula", toolbox)
        self.assertIn("combat_triangle_static_base_formula", toolbox)
        self.assertIn("combat_triangle_swapped_stats_defender_weights_formula", toolbox)
        self.assertIn("combat_triangle_swapped_stats_attacker_weights_formula", toolbox)
        self.assertEqual("weighted_product", toolbox["combat_triangle_formula"]["composition"])
        self.assertEqual("static_composable", toolbox["combat_triangle_static_base_formula"]["input_class"])
        self.assertEqual("synced_profile", toolbox["combat_triangle_static_player_max_buffs_formula"]["input_class"])
        self.assertEqual("validation_only", toolbox["combat_triangle_formula"]["input_class"])
        self.assertEqual("validation_only", analysis["diagnostic_fits"]["expanded_linear_fit"]["input_class"])
        self.assertEqual(
            {
                "target_mae": 0.05,
                "eligible_input_classes": ["static_composable", "synced_profile"],
                "passing": [],
                "best_candidate": "combat_triangle_static_base_formula",
            },
            {
                key: analysis["simulator_goal"][key]
                for key in ("target_mae", "eligible_input_classes", "passing", "best_candidate")
            },
        )
        self.assertEqual(
            {
                "combat_triangle_static_base_formula",
                "combat_triangle_static_player_max_buffs_formula",
            },
            set(analysis["simulator_goal"]["candidate_metrics"]),
        )
        self.assertEqual(
            {
                ("weighted_product", 2.0),
                ("weighted_power_product", 2.0),
            },
            {
                (row["composition"], row["curve_base"])
                for row in analysis["combat_triangle_static_player_max_buffs_curve_base_variants"]
            },
        )
        for row in analysis["combat_triangle_static_player_max_buffs_curve_base_variants"]:
            self.assertEqual("static_player_max_buffs", row["stat_source"])
            self.assertEqual("diagnostic_only", row["input_class"])
            self.assertIn("metrics", row)
        self.assertEqual(
            [
                "active_layer_weighted_product",
                "active_layer_weighted_product_unscaled",
                "active_layer_weighted_sum",
                "weighted_power_product",
                "weighted_product",
                "weighted_sum",
            ],
            sorted(row["composition"] for row in analysis["combat_triangle_composition_variants"]),
        )
        variant_metrics = {
            row["composition"]: row["metrics"]
            for row in analysis["combat_triangle_composition_variants"]
        }
        self.assertEqual(
            toolbox["combat_triangle_formula"]["metrics"],
            variant_metrics["weighted_product"],
        )
        self.assertIn("ratio_linear_fit", analysis["diagnostic_fits"])
        self.assertIn("global_mean", analysis["diagnostic_fits"])
        self.assertIn("combat_triangle_linear_fit", analysis["diagnostic_fits"])
        self.assertIn("attacker_side_combat_triangle_linear_fit", analysis["diagnostic_fits"])
        self.assertIn("basic_live_linear_fit", analysis["diagnostic_fits"])
        self.assertIn("basic_live_nonnegative_fit", analysis["diagnostic_fits"])
        self.assertIn("attacker_side_basic_live_nonnegative_fit", analysis["diagnostic_fits"])
        self.assertIn("expanded_linear_fit", analysis["diagnostic_fits"])
        self.assertIn("attacker_side_expanded_linear_fit", analysis["diagnostic_fits"])
        self.assertEqual(
            "residual/error localization only; not an authoritative combat formula",
            analysis["diagnostic_fits"]["purpose"],
        )
        self.assertEqual(
            {
                "attacker_active_ship_bonus",
                "attacker_cloaking_ability",
                "attacker_hull_all_ship_bonus",
                "attacker_hull_activated_ability",
                "attacker_hull_name",
                "attacker_hull_ship_bonus",
                "attacker_side",
                "defender_active_ship_bonus",
                "defender_cloaking_ability",
                "defender_hull_all_ship_bonus",
                "defender_hull_activated_ability",
                "defender_hull_name",
                "defender_hull_ship_bonus",
                "defender_hull_type",
                "hostile_id_prefix",
                "ideal_hostile_matchup",
                "isolytic_triggered",
                "officer_ability",
                "officer_formula_stage",
                "officer_id",
                "officer_modifier",
                "officer_stage_modifier",
                "shield_active_before_shot",
            },
            set(analysis["combat_triangle_residuals"]),
        )
        self.assertIn("prediction", analysis["combat_triangle_residuals"]["attacker_side"][0])
        self.assertIn("error", analysis["combat_triangle_residuals"]["attacker_side"][0])
        self.assertIn("combat_triangle_stat_role_orientation_variants", analysis)
        self.assertEqual(
            {
                "normal",
                "swapped_stats_attacker_weights",
                "swapped_stats_defender_weights",
            },
            {row["stat_role_orientation"] for row in analysis["combat_triangle_stat_role_orientation_variants"]},
        )
        self.assertEqual(
            "combat_triangle_triggered_officer_stat_percent_formula",
            analysis["combat_triangle_triggered_officer_stat_percent_residuals"]["model"],
        )
        self.assertEqual(
            "combat_triangle_swapped_stats_defender_weights_formula",
            analysis["combat_triangle_swapped_stats_defender_weights_residuals"]["model"],
        )
        self.assertEqual(
            set(analysis["combat_triangle_residuals"]),
            set(analysis["combat_triangle_triggered_officer_stat_percent_residuals"]["groups"]),
        )
        self.assertEqual(
            {"h1:Defender Hull", "h2:Defender Hull"},
            {group["key"] for group in analysis["groups"]["defender_hull_name"]},
        )
        self.assertEqual({"none"}, {group["key"] for group in analysis["groups"]["defender_hull_activated_ability"]})
        self.assertEqual({"none"}, {group["key"] for group in analysis["groups"]["ideal_hostile_matchup"]})
        self.assertEqual(
            {"dodge_ratio", "plating_ratio", "absorption_ratio"},
            set(analysis["diagnostic_fits"]["ratio_linear_fit"]["coefficients"]),
        )
        basic_live = analysis["diagnostic_fits"]["basic_live_linear_fit"]
        deterministic = toolbox["deterministic_basic_live_formula"]
        triangle_fit = analysis["diagnostic_fits"]["combat_triangle_linear_fit"]
        side_triangle_fit = analysis["diagnostic_fits"]["attacker_side_combat_triangle_linear_fit"]
        self.assertEqual({"combat_triangle_prediction"}, set(triangle_fit["coefficients"]))
        self.assertIn("leave_one_battle_out_metrics", triangle_fit)
        self.assertEqual({"player", "hostile"}, set(side_triangle_fit["partitions"]))
        self.assertIn("leave_one_battle_out_metrics", side_triangle_fit)
        self.assertEqual(
            {"live_dodge_ratio", "live_plating_ratio", "live_absorption_ratio"},
            set(deterministic["features"]),
        )
        self.assertIn("metrics", deterministic)
        self.assertEqual(
            {"live_dodge_ratio", "live_plating_ratio", "live_absorption_ratio"},
            set(basic_live["coefficients"]),
        )
        constrained = analysis["diagnostic_fits"]["attacker_side_basic_live_nonnegative_fit"]
        self.assertEqual({"player", "hostile"}, set(constrained["partitions"]))
        for partition in constrained["partitions"].values():
            self.assertTrue(all(coefficient >= 0 for coefficient in partition["coefficients"].values()))
        expanded = analysis["diagnostic_fits"]["expanded_linear_fit"]
        self.assertIn("weapon_shots", expanded["coefficients"])
        self.assertIn("weapon_accuracy_log", expanded["coefficients"])
        self.assertIn("weapon_penetration_log", expanded["coefficients"])
        self.assertIn("weapon_modulation_log", expanded["coefficients"])
        self.assertIn("weapon_damage_per_shot_log", expanded["coefficients"])
        self.assertNotIn("weapon_is_energy", expanded["coefficients"])
        self.assertNotIn("weapon_is_kinetic", expanded["coefficients"])
        self.assertIn("attacker_is_player", expanded["coefficients"])
        self.assertIn("critical", expanded["coefficients"])
        self.assertIn("leave_one_battle_out_metrics", expanded)
        side_model = analysis["diagnostic_fits"]["attacker_side_expanded_linear_fit"]
        self.assertEqual({"player", "hostile"}, set(side_model["partitions"]))
        self.assertIn("metrics", side_model)
        self.assertIn("leave_one_battle_out_metrics", side_model)
        self.assertEqual({"2:PASSIVE_MARAUDER"}, {group["key"] for group in analysis["groups"]["battle_type"]})
        self.assertEqual(1, analysis["summary"]["officer_activation_rows"])
        self.assertEqual(1, analysis["summary"]["officer_activation_count"])
        self.assertEqual(
            {
                "ability-1:modifier=707:op=BUFFOPERATION_MULTIPLYADD",
                "none",
            },
            {group["key"] for group in analysis["groups"]["officer_ability"]},
        )
        self.assertEqual(
            {"707:op=BUFFOPERATION_MULTIPLYADD", "none"},
            {group["key"] for group in analysis["groups"]["officer_modifier"]},
        )
        self.assertEqual({"isolytic_damage", "none"}, {group["key"] for group in analysis["groups"]["officer_formula_stage"]})
        self.assertEqual(
            {"isolytic_damage:707:op=BUFFOPERATION_MULTIPLYADD", "none"},
            {group["key"] for group in analysis["groups"]["officer_stage_modifier"]},
        )
        self.assertEqual({"officer-1", "none"}, {group["key"] for group in analysis["groups"]["officer_id"]})
        self.assertIn("officer_effect_ablation", analysis)
        self.assertEqual("combat_triangle_formula", analysis["officer_effect_ablation"]["model"])
        self.assertIn("by_ability_with_triggered_effects_applied", analysis["officer_effect_ablation"])
        self.assertIn(
            "by_ability_with_officer_stat_percent_triggered_effects_applied",
            analysis["officer_effect_ablation"],
        )
        self.assertIn(
            "by_ability_with_officer_stat_raw_triggered_effects_applied",
            analysis["officer_effect_ablation"],
        )
        self.assertEqual(
            "ability-1:modifier=707:op=BUFFOPERATION_MULTIPLYADD",
            analysis["officer_effect_ablation"]["by_ability"][0]["key"],
        )
        self.assertEqual(
            "isolytic_damage",
            analysis["officer_effect_ablation"]["by_ability"][0]["formula_effect"]["formula_stage"],
        )
        self.assertEqual({"player", "hostile"}, {group["key"] for group in analysis["groups"]["attacker_side"]})
        scaling = analysis["live_stat_scaling"]
        self.assertTrue(any(row["role"] == "attacker" and row["side"] == "player" for row in scaling))
        player_accuracy = next(
            row
            for row in scaling
            if row["role"] == "attacker" and row["side"] == "player" and row["stat"] == "weapon_accuracy"
        )
        self.assertAlmostEqual(2.0, player_accuracy["multiplier"]["mean"])
        scaling_by_hull = analysis["live_stat_scaling_by_hull"]
        player_accuracy_by_hull = next(
            row
            for row in scaling_by_hull
            if row["role"] == "attacker"
            and row["side"] == "player"
            and row["stat"] == "weapon_accuracy"
            and row["hull_id"] == "attacker-hull"
        )
        self.assertAlmostEqual(2.0, player_accuracy_by_hull["multiplier"]["mean"])
        scaling_by_hull_type = analysis["live_stat_scaling_by_hull_type"]
        player_accuracy_by_hull_type = next(
            row
            for row in scaling_by_hull_type
            if row["role"] == "attacker"
            and row["side"] == "player"
            and row["stat"] == "weapon_accuracy"
            and row["hull_type"] == "HULLTYPE_EXPLORER"
        )
        self.assertAlmostEqual(2.0, player_accuracy_by_hull_type["multiplier"]["mean"])

    def test_excludes_shot_count_stage_from_mitigation_fit(self) -> None:
        rows = [
            _observation(
                battle_id="1",
                attacker_side="hostile",
                weapon_id="w1",
                defender_hull_id="defender-hull",
                accuracy=100,
                penetration=100,
                modulation=100,
                dodge=100,
                plating=100,
                absorption=100,
                observed=0.5,
            ),
            _observation(
                battle_id="2",
                attacker_side="hostile",
                weapon_id="w1",
                defender_hull_id="defender-hull",
                accuracy=100,
                penetration=100,
                modulation=100,
                dodge=100,
                plating=100,
                absorption=100,
                observed=0.5,
            ),
        ]
        rows[1]["attacker"]["resolved_modifiers"] = {"3": -9}

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(1, analysis["summary"]["rows"])
        self.assertEqual(
            1,
            analysis["summary"]["mitigation_fit_excluded_reasons"]["shot_count_damage_stage"],
        )

    def test_basic_live_features_gate_absorption_on_pre_shot_shields(self) -> None:
        with_shield = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            attacker_accuracy=100,
            attacker_armor_piercing=100,
            attacker_shield_piercing=150,
            observed=0.25,
            shield_damage=1,
            remaining_shield=0,
        )
        without_shield = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            attacker_accuracy=100,
            attacker_armor_piercing=100,
            attacker_shield_piercing=150,
            observed=0.25,
            shield_damage=0,
            remaining_shield=0,
        )

        self.assertGreater(_basic_live_features(with_shield)["live_absorption_ratio"], 0.0)
        self.assertEqual(0.0, _basic_live_features(without_shield)["live_absorption_ratio"])

    def test_identifies_ideal_hostile_matchup_pairs(self) -> None:
        row = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="swarm-hull",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            observed=0.25,
        )
        row["attacker"]["static_ship"]["hull"]["name"] = "Franklin 2.0"
        row["attacker"]["static_ship"]["hull"]["id_str"] = "Hull_G4_Explorer_None_Franklin2"
        row["defender"]["static_ship"]["hull"]["name"] = "Hull_L50_Destroyer_Swm_Swarm2"
        row["defender"]["static_ship"]["hull"]["id_str"] = "Hull_L50_Destroyer_Swm_Swarm2"

        self.assertEqual(["franklin_vs_swarm:ship_attacking_ideal_hostile"], _ideal_hostile_matchup_keys(row))

        row["attacker"], row["defender"] = row["defender"], row["attacker"]

        self.assertEqual(["franklin_vs_swarm:ideal_hostile_attacking_ship"], _ideal_hostile_matchup_keys(row))

    def test_reports_data_gaps_for_isolytic_player_attack_confound(self) -> None:
        observations = [
            _observation(
                battle_id="1",
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=100,
                penetration=200,
                modulation=300,
                dodge=50,
                plating=100,
                absorption=150,
                observed=0.25,
                isolytic_damage=100,
                shield_damage=800,
                triggered_effects=["isolytic"],
            ),
            _observation(
                battle_id="2",
                attacker_side="player",
                weapon_id="w1",
                defender_hull_id="h1",
                accuracy=120,
                penetration=220,
                modulation=320,
                dodge=60,
                plating=110,
                absorption=160,
                observed=0.28,
                isolytic_damage=100,
                shield_damage=800,
                triggered_effects=["isolytic"],
            ),
            _observation(
                battle_id="3",
                attacker_side="hostile",
                weapon_id="w2",
                defender_hull_id="h2",
                accuracy=200,
                penetration=300,
                modulation=400,
                dodge=60,
                plating=120,
                absorption=160,
                observed=0.30,
            ),
        ]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in observations), encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertIn("data_gaps", analysis)
        self.assertEqual(2, analysis["data_gaps"]["attacker_side_by_isolytic_triggered"]["player"]["True"])
        self.assertIn(
            "player attacker rows are fully confounded with isolytic-triggered rows",
            analysis["data_gaps"]["warnings"],
        )

    def test_reports_overkill_base_gap_rows_without_using_it_as_hard_fit_exclusion(self) -> None:
        overkill = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            observed=0.25,
            isolytic_damage=1070,
            triggered_effects=["isolytic"],
        )
        overkill["observed"]["isolytic_damage_model"] = {
            "base_damage": 1000,
            "raw_damage": 1070,
            "observed_damage": 1070,
            "mitigated_damage": 0,
            "damage_multiplier": 1.07,
            "damage_multiplier_percent": 107,
            "effective_mitigation": 0,
            "inferred_base_damage": 1100,
            "base_damage_gap": 100,
            "damage_modifier_code": "707",
            "defense_modifier_code": "808",
            "source": "resolved_buff_audit",
        }
        usable = _observation(
            battle_id="2",
            attacker_side="hostile",
            weapon_id="w2",
            defender_hull_id="h2",
            accuracy=200,
            penetration=300,
            modulation=400,
            dodge=60,
            plating=120,
            absorption=160,
            observed=0.30,
        )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text(json.dumps(overkill) + "\n" + json.dumps(usable) + "\n", encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(1, analysis["summary"]["rows"])
        self.assertEqual(0, analysis["summary"]["overkill_excluded_rows"])
        self.assertEqual(1, analysis["summary"]["overkill_base_damage_gap_rows"])
        self.assertEqual(
            {"normal_damage_capped_by_isolytic_overkill": 1},
            analysis["summary"]["mitigation_fit_excluded_reasons"],
        )
        self.assertEqual(1, analysis["damage_stage_pipeline"]["observed_isolytic_damage_replay"]["isolytic_rows"])

    def test_uses_stage_ordered_normal_target_for_iso_apex_rows(self) -> None:
        stage_decomposable = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            observed=0.25,
            shield_damage=100,
            isolytic_damage=150,
            triggered_effects=["isolytic"],
        )
        stage_decomposable["observed"]["mitigated_apex_barrier"] = 100
        stage_decomposable["observed"]["mitigated_damage"] = 25
        stage_decomposable["observed"]["isolytic_damage_model"] = {
            "base_damage": 25,
            "raw_damage": 150,
            "observed_damage": 150,
            "mitigated_damage": 0,
            "damage_multiplier": 6,
            "damage_multiplier_percent": 600,
            "effective_mitigation": 0,
            "inferred_base_damage": 75,
            "base_damage_gap": 50,
            "damage_modifier_code": "707",
            "defense_modifier_code": "808",
            "source": "resolved_buff_audit",
        }
        usable = _observation(
            battle_id="2",
            attacker_side="hostile",
            weapon_id="w2",
            defender_hull_id="h2",
            accuracy=200,
            penetration=300,
            modulation=400,
            dodge=60,
            plating=120,
            absorption=160,
            observed=0.30,
        )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text(json.dumps(stage_decomposable) + "\n" + json.dumps(usable) + "\n", encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(2, analysis["summary"]["rows"])
        self.assertEqual(1, analysis["summary"]["overkill_base_damage_gap_rows"])
        self.assertEqual({}, analysis["summary"]["mitigation_fit_excluded_reasons"])
        self.assertAlmostEqual(1 / 3, analysis["summary"]["normal_effective_mitigation"]["min"])

    def test_excludes_zero_observed_normal_damage_with_isolytic_from_mitigation_fit(self) -> None:
        capped = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            observed=0.25,
            isolytic_damage=1000,
            triggered_effects=["isolytic"],
        )
        usable = _observation(
            battle_id="2",
            attacker_side="hostile",
            weapon_id="w2",
            defender_hull_id="h2",
            accuracy=200,
            penetration=300,
            modulation=400,
            dodge=60,
            plating=120,
            absorption=160,
            observed=0.30,
        )

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text(json.dumps(capped) + "\n" + json.dumps(usable) + "\n", encoding="utf-8")

            analysis = analyze_mitigation(observations_path=path)

        self.assertEqual(1, analysis["summary"]["rows"])
        self.assertEqual(
            {"normal_damage_capped_by_isolytic_overkill": 1},
            analysis["summary"]["mitigation_fit_excluded_reasons"],
        )

    def test_cli_analyze_mitigation_writes_report(self) -> None:
        observation = _observation(
            battle_id="1",
            attacker_side="player",
            weapon_id="w1",
            defender_hull_id="h1",
            accuracy=100,
            penetration=200,
            modulation=300,
            dodge=50,
            plating=100,
            absorption=150,
            observed=0.25,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            observations = root / "observations.jsonl"
            out = root / "analysis.json"
            observations.write_text(json.dumps(observation) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "analyze-mitigation",
                    "--observations",
                    str(observations),
                    "--out",
                    str(out),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            analysis = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(1, analysis["summary"]["rows"])
            self.assertIn("global_mean", analysis["diagnostic_fits"])
            self.assertNotIn("global_mean", analysis["models"])


if __name__ == "__main__":
    unittest.main()
