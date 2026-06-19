from __future__ import annotations

import unittest

from scripts.lib.combat_model.mechanics import combat_triangle_mitigation as toolbox_combat_triangle_mitigation
from scripts.lib.combat_model.mitigation_formula import (
    deterministic_basic_live_features,
    combat_triangle_features,
    predict_combat_triangle_mitigation,
    predict_basic_live_mitigation,
)


CORE_THRESHOLDS = {
    "1": {"thresholds": [{"statTotal": 20, "statBonus": 0.1}, {"statTotal": 90, "statBonus": 0.4}]},
    "2": {"thresholds": [{"statTotal": 40, "statBonus": 0.2}, {"statTotal": 120, "statBonus": 0.5}]},
    "3": {"thresholds": [{"statTotal": 20, "statBonus": 0.1}, {"statTotal": 120, "statBonus": 0.5}]},
}


def _row(*, attacker_side: str = "player", defender_side: str = "hostile") -> dict[str, object]:
    return {
        "attacker_side": attacker_side,
        "defender_side": defender_side,
        "attacker": {
            "ship_id": "attacker-ship",
            "captured_stats": {"6": 10, "7": 10, "8": 10},
            "resolved_stats": {"6": 100, "7": 100, "8": 100},
        },
        "defender": {
            "ship_id": "defender-ship",
            "captured_fleet_stats": {"58": 200},
            "captured_stats": {"11": 100, "-3": 100, "-2": 100},
            "static_ship": {"hull": {"type": "HULLTYPE_SURVEY"}},
        },
        "observed": {
            "damage": {"shield": 1, "hull": 0},
            "remaining": {"shield": 10, "hull": 1000},
        },
    }


class MitigationFormulaTests(unittest.TestCase):
    def test_basic_live_formula_prefers_resolved_player_stats(self) -> None:
        features = deterministic_basic_live_features(_row())

        self.assertEqual(
            {
                "live_dodge_ratio": 0.5,
                "live_plating_ratio": 0.5,
                "live_absorption_ratio": 0.5,
            },
            features,
        )
        self.assertEqual(0.5, predict_basic_live_mitigation(_row()))

    def test_basic_live_formula_can_use_captured_stats_only(self) -> None:
        features = deterministic_basic_live_features(_row(), prefer_resolved_player_stats=False)

        self.assertAlmostEqual(100 / 110, features["live_dodge_ratio"])
        self.assertAlmostEqual(100 / 110, features["live_plating_ratio"])
        self.assertAlmostEqual(100 / 110, features["live_absorption_ratio"])

    def test_basic_live_formula_ignores_absorption_when_shields_are_inactive_before_shot(self) -> None:
        row = _row()
        row["observed"] = {
            "damage": {"shield": 0, "hull": 100},
            "remaining": {"shield": 0, "hull": 900},
        }

        features = deterministic_basic_live_features(row)

        self.assertEqual(0.0, features["live_absorption_ratio"])
        self.assertAlmostEqual(1 / 3, predict_basic_live_mitigation(row))

    def test_combat_triangle_formula_uses_weighted_defender_hull_type(self) -> None:
        row = {
            "attacker_side": "player",
            "defender_side": "hostile",
            "attacker": {
                "captured_stats": {
                    "7": 2141,
                    "8": 1606,
                    "6": 14000,
                }
            },
            "defender": {
                "captured_stats": {
                    "-3": 363,
                    "-2": 6667,
                    "11": 484,
                },
                "static_ship": {
                    "hull": {
                        "type": "HULLTYPE_EXPLORER",
                    }
                },
            },
        }

        self.assertAlmostEqual(0.578, predict_combat_triangle_mitigation(row), places=3)

    def test_combat_triangle_row_level_formula_matches_toolbox_weighted_product(self) -> None:
        row = {
            "attacker_side": "player",
            "defender_side": "hostile",
            "attacker": {
                "captured_stats": {
                    "7": 1000,
                    "8": 1000,
                    "6": 1000,
                }
            },
            "defender": {
                "captured_stats": {
                    "-3": 1100,
                    "-2": 1100,
                    "11": 1100,
                },
                "static_ship": {
                    "hull": {
                        "type": "HULLTYPE_BATTLESHIP",
                    }
                },
            },
        }

        expected = toolbox_combat_triangle_mitigation(
            armor=1100,
            shield=1100,
            dodge=1100,
            armor_piercing=1000,
            shield_piercing=1000,
            accuracy=1000,
            defender_hull_type="HULLTYPE_BATTLESHIP",
        )

        self.assertAlmostEqual(expected, 1 - (1 - 0.55 * 0.5) * (1 - 0.2 * 0.5) * (1 - 0.2 * 0.5))

        self.assertAlmostEqual(
            expected,
            predict_combat_triangle_mitigation(row, stat_source="captured_live"),
        )

    def test_combat_triangle_curve_base_defaults_to_existing_toolbox_curve(self) -> None:
        row = _row()
        expected = toolbox_combat_triangle_mitigation(
            armor=100,
            shield=100,
            dodge=100,
            armor_piercing=100,
            shield_piercing=100,
            accuracy=100,
            defender_hull_type="HULLTYPE_SURVEY",
        )

        self.assertAlmostEqual(
            expected,
            predict_combat_triangle_mitigation(row),
        )
        self.assertAlmostEqual(
            expected,
            predict_combat_triangle_mitigation(row, curve_base=4.0),
        )

    def test_combat_triangle_curve_base_changes_weighted_product_and_power_product(self) -> None:
        row = _row()

        default_weighted_product = predict_combat_triangle_mitigation(row)
        base_two_weighted_product = predict_combat_triangle_mitigation(row, curve_base=2.0)
        default_power_product = predict_combat_triangle_mitigation(row, composition="weighted_power_product")
        base_two_power_product = predict_combat_triangle_mitigation(
            row,
            composition="weighted_power_product",
            curve_base=2.0,
        )

        self.assertNotAlmostEqual(default_weighted_product, base_two_weighted_product)
        self.assertGreater(base_two_weighted_product, default_weighted_product)
        self.assertNotAlmostEqual(default_power_product, base_two_power_product)
        self.assertGreater(base_two_power_product, default_power_product)

    def test_combat_triangle_curve_base_rejects_invalid_values(self) -> None:
        row = _row()

        for curve_base in (0.0, 1.0, float("nan")):
            with self.subTest(curve_base=curve_base):
                with self.assertRaises(ValueError):
                    predict_combat_triangle_mitigation(row, curve_base=curve_base)

    def test_combat_triangle_formula_maps_destroyer_to_interceptor_weights(self) -> None:
        row = _row()
        row["attacker"]["resolved_stats"] = {"6": 14000, "7": 2141, "8": 1606}
        row["defender"]["captured_stats"] = {"-3": 484, "-2": 363, "11": 6682}
        row["defender"]["static_ship"]["hull"]["type"] = "HULLTYPE_DESTROYER"

        self.assertAlmostEqual(0.235, predict_combat_triangle_mitigation(row), places=2)

    def test_combat_triangle_formula_can_compare_stat_sources(self) -> None:
        row = _row()
        row["attacker"]["static_ship"] = {
            "base_stats": {
                "weapon_accuracy_max": 50,
                "weapon_penetration_max": 50,
                "weapon_modulation_max": 50,
            }
        }
        row["defender"]["static_ship"]["base_stats"] = {
            "armor_plating": 150,
            "shield_absorption": 150,
            "dodge": 150,
        }

        default_prediction = predict_combat_triangle_mitigation(row)
        captured_prediction = predict_combat_triangle_mitigation(row, stat_source="captured_live")
        static_prediction = predict_combat_triangle_mitigation(row, stat_source="static_base")
        static_features = combat_triangle_features(row, stat_source="static_base")

        self.assertLess(default_prediction, captured_prediction)
        self.assertNotEqual(captured_prediction, static_prediction)
        self.assertEqual("static_base", static_features["stat_source"])
        self.assertAlmostEqual(150, static_features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(50, static_features["stat_inputs"]["armor"]["piercing"])

    def test_combat_triangle_static_player_max_buffs_applies_player_defender_modifiers(self) -> None:
        row = _row(attacker_side="hostile", defender_side="player")
        row["attacker"]["static_ship"] = {
            "base_stats": {
                "weapon_accuracy_max": 100,
                "weapon_penetration_max": 100,
                "weapon_modulation_max": 100,
            }
        }
        row["defender"]["static_ship"]["base_stats"] = {
            "armor_plating": 100,
            "shield_absorption": 200,
            "dodge": 300,
        }
        row["defender"]["static_ship"]["hull"]["core_stat_modifiers"] = [
            {"type": "OFFICERCORESTATTYPE_DEFENSE", "bonus": 3.5, "threshold": 25},
        ]
        row["defender"]["static_ship"]["hull"]["officer_core_thresholds"] = CORE_THRESHOLDS
        row["defender"]["captured_fleet_stats"] = {"57": 41, "59": 99}
        row["defender"]["resolved_modifiers"] = {"11": 1.0, "12": 4.0, "13": 5.0, "73": 1.5}

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertEqual("static_player_max_buffs", features["stat_source"])
        self.assertAlmostEqual(700, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(1600, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(1200, features["stat_inputs"]["dodge"]["defense"])

    def test_combat_triangle_static_player_max_buffs_applies_player_defender_officer_stat_all_rating_buff(self) -> None:
        row = _row(attacker_side="hostile", defender_side="player")
        row["defender"]["static_ship"]["base_stats"] = {
            "armor_plating": 100,
            "shield_absorption": 200,
            "dodge": 300,
        }
        row["defender"]["captured_fleet_ratings"] = {"defense_rating": 1000}
        row["defender"]["resolved_modifier_rows"] = [
            {
                "buff_id": "660954013",
                "modifierCode": "59",
                "buffOperation": "BUFFOPERATION_MULTIPLYADD",
                "targetCode": "5",
                "triggerCode": "24",
                "selected_ranked_value": 5,
                "source_type": "starbase",
                "source_key": "starbaseBuffsSpecs/660954013",
            }
        ]

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(5100, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(5200, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(300, features["stat_inputs"]["dodge"]["defense"])

    def test_combat_triangle_static_player_max_buffs_synthesizes_missing_officer_stat_all_rating_buff(self) -> None:
        row = _row(attacker_side="hostile", defender_side="player")
        row["defender"]["static_ship"]["base_stats"] = {
            "armor_plating": 100,
            "shield_absorption": 200,
            "dodge": 300,
        }
        row["defender"]["captured_fleet_stats"] = {"59": 200}
        row["defender"]["captured_fleet_ratings"] = {"defense_rating": 1000}

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(5100, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(5200, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(300, features["stat_inputs"]["dodge"]["defense"])

    def test_combat_triangle_static_player_max_buffs_applies_player_attacker_officer_stat_all_rating_buff(self) -> None:
        row = _row(attacker_side="player", defender_side="hostile")
        row["attacker"]["static_ship"] = {
            "base_stats": {
                "weapon_accuracy_max": 100,
                "weapon_penetration_max": 200,
                "weapon_modulation_max": 300,
            },
        }
        row["attacker"]["captured_fleet_ratings"] = {"offense_rating": 1000}
        row["attacker"]["resolved_modifier_rows"] = [
            {
                "buff_id": "660954013",
                "modifierCode": "59",
                "buffOperation": "BUFFOPERATION_MULTIPLYADD",
                "targetCode": "5",
                "triggerCode": "24",
                "selected_ranked_value": 5,
                "source_type": "starbase",
                "source_key": "starbaseBuffsSpecs/660954013",
            }
        ]

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(100, features["stat_inputs"]["dodge"]["piercing"])
        self.assertAlmostEqual(200, features["stat_inputs"]["armor"]["piercing"])
        self.assertAlmostEqual(5300, features["stat_inputs"]["shield"]["piercing"])

    def test_combat_triangle_static_player_max_buffs_synthesizes_missing_attacker_officer_stat_all_rating_buff(self) -> None:
        row = _row(attacker_side="player", defender_side="hostile")
        row["attacker"]["static_ship"] = {
            "base_stats": {
                "weapon_accuracy_max": 100,
                "weapon_penetration_max": 200,
                "weapon_modulation_max": 300,
            },
        }
        row["attacker"]["captured_fleet_stats"] = {"59": 200}
        row["attacker"]["captured_fleet_ratings"] = {"offense_rating": 1000}

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(100, features["stat_inputs"]["dodge"]["piercing"])
        self.assertAlmostEqual(200, features["stat_inputs"]["armor"]["piercing"])
        self.assertAlmostEqual(5300, features["stat_inputs"]["shield"]["piercing"])

    def test_combat_triangle_static_player_max_buffs_can_use_lookup_stats_for_special_player_defenders(self) -> None:
        row = _row(attacker_side="hostile", defender_side="player")
        row["defender"]["static_ship"]["hull"]["id"] = "2016654425"
        row["defender"]["static_ship"]["base_stats"] = {
            "armor_plating": 100,
            "shield_absorption": 200,
            "dodge": 300,
        }
        row["defender"]["static_ship"]["client_ship_stat_lookup_sources"] = {
            "armor_plating": {"status": "found", "value": 1000},
            "shield_absorption": {"status": "found", "value": 2000},
            "dodge": {"status": "found", "value": 3000},
        }
        row["defender"]["resolved_modifiers"] = {"73": 1.0}

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(2000, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(4000, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(6000, features["stat_inputs"]["dodge"]["defense"])

    def test_combat_triangle_static_player_max_buffs_keeps_component_stats_for_other_player_defenders(self) -> None:
        row = _row(attacker_side="hostile", defender_side="player")
        row["defender"]["static_ship"]["hull"]["id"] = "not-special"
        row["defender"]["static_ship"]["base_stats"] = {
            "armor_plating": 100,
            "shield_absorption": 200,
            "dodge": 300,
        }
        row["defender"]["static_ship"]["client_ship_stat_lookup_sources"] = {
            "armor_plating": {"status": "found", "value": 1000},
            "shield_absorption": {"status": "found", "value": 2000},
            "dodge": {"status": "found", "value": 3000},
        }
        row["defender"]["resolved_modifiers"] = {"73": 1.0}

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(200, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(400, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(600, features["stat_inputs"]["dodge"]["defense"])

    def test_combat_triangle_static_player_max_buffs_applies_player_attacker_modifiers(self) -> None:
        row = _row(attacker_side="player", defender_side="hostile")
        row["attacker"]["static_ship"] = {
            "base_stats": {
                "weapon_accuracy_max": 100,
                "weapon_penetration_max": 200,
                "weapon_modulation_max": 300,
            },
            "hull": {
                "core_stat_modifiers": [
                    {"type": "OFFICERCORESTATTYPE_ATTACK", "bonus": 3.5, "threshold": 25},
                ]
            },
        }
        row["attacker"]["captured_fleet_stats"] = {"56": 37, "59": 60}
        row["attacker"]["static_ship"]["hull"]["officer_core_thresholds"] = CORE_THRESHOLDS
        row["attacker"]["resolved_modifiers"] = {"74": 1.5}

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(290, features["stat_inputs"]["dodge"]["piercing"])
        self.assertAlmostEqual(580, features["stat_inputs"]["armor"]["piercing"])
        self.assertAlmostEqual(870, features["stat_inputs"]["shield"]["piercing"])

    def test_combat_triangle_static_player_max_buffs_uses_weapon_stats_for_hostile_attacker(self) -> None:
        row = _row(attacker_side="hostile", defender_side="player")
        row["attacker"]["static_ship"] = {
            "base_stats": {
                "weapon_accuracy_max": 100,
                "weapon_penetration_max": 100,
                "weapon_modulation_max": 100,
            }
        }
        row["weapon"] = {
            "accuracy": 25,
            "penetration": 50,
            "modulation": 75,
        }

        features = combat_triangle_features(row, stat_source="static_player_max_buffs")

        self.assertAlmostEqual(25, features["stat_inputs"]["dodge"]["piercing"])
        self.assertAlmostEqual(50, features["stat_inputs"]["armor"]["piercing"])
        self.assertAlmostEqual(75, features["stat_inputs"]["shield"]["piercing"])

    def test_combat_triangle_can_include_defender_apex_barrier_stage(self) -> None:
        row = _row()
        row["defender"]["resolved_modifiers"] = {"67001": 10000}

        baseline = predict_combat_triangle_mitigation(row)
        with_apex = predict_combat_triangle_mitigation(row, include_apex_barrier=True)

        self.assertGreater(with_apex, baseline)
        self.assertAlmostEqual(1 - (1 - baseline) * 0.5, with_apex)

    def test_combat_triangle_formula_can_report_swapped_stat_role_diagnostic(self) -> None:
        row = _row()
        row["attacker"]["captured_stats"] = {"6": 10, "7": 20, "8": 30, "11": 40, "-3": 50, "-2": 60}
        row["attacker"]["static_ship"] = {"hull": {"type": "HULLTYPE_BATTLESHIP"}}
        row["defender"]["captured_stats"] = {"6": 100, "7": 200, "8": 300, "11": 400, "-3": 500, "-2": 600}
        row["defender"]["static_ship"]["hull"]["type"] = "HULLTYPE_EXPLORER"

        defender_weight_features = combat_triangle_features(
            row,
            stat_role_orientation="swapped_stats_defender_weights",
        )
        attacker_weight_features = combat_triangle_features(
            row,
            stat_role_orientation="swapped_stats_attacker_weights",
        )

        self.assertEqual("swapped_stats_defender_weights", defender_weight_features["stat_role_orientation"])
        self.assertEqual("HULLTYPE_EXPLORER", defender_weight_features["defender_hull_type"])
        self.assertEqual("HULLTYPE_BATTLESHIP", attacker_weight_features["defender_hull_type"])
        self.assertAlmostEqual(50, defender_weight_features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(200, defender_weight_features["stat_inputs"]["armor"]["piercing"])

    def test_combat_triangle_formula_can_apply_triggered_all_defense_buffs(self) -> None:
        row = _row()
        row["observed"]["officer_activations"] = [
            {
                "firing_ship_id": "defender-ship",
                "ability_buff_id": "ability-defense",
                "officer_id": "officer-defense",
                "modifierCode": "73",
                "op": "BUFFOPERATION_MULTIPLYBASEADD",
                "targetCode": "1",
                "value": 3.0,
                "formula_effect": {"formula_stage": "normal_mitigation_triangle"},
            }
        ]

        baseline = predict_combat_triangle_mitigation(row)
        triggered = predict_combat_triangle_mitigation(row, apply_triggered_effects=True)
        features = combat_triangle_features(row, apply_triggered_effects=True)

        self.assertGreater(triggered, baseline)
        self.assertAlmostEqual(400, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(400, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(400, features["stat_inputs"]["dodge"]["defense"])
        self.assertEqual(3, len(features["stat_adjustments"]))

    def test_combat_triangle_formula_can_apply_triggered_all_defense_debuffs(self) -> None:
        row = _row()
        row["observed"]["officer_activations"] = [
            {
                "firing_ship_id": "attacker-ship",
                "ability_buff_id": "ability-defense-debuff",
                "officer_id": "officer-defense-debuff",
                "modifierCode": "73",
                "op": "BUFFOPERATION_MULTIPLYBASESUB",
                "targetCode": "6",
                "value": 0.25,
                "formula_effect": {"formula_stage": "normal_mitigation_triangle"},
            }
        ]

        baseline = predict_combat_triangle_mitigation(row)
        triggered = predict_combat_triangle_mitigation(row, apply_triggered_effects=True)
        features = combat_triangle_features(row, apply_triggered_effects=True)

        self.assertLess(triggered, baseline)
        self.assertAlmostEqual(75, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(75, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(75, features["stat_inputs"]["dodge"]["defense"])
        self.assertEqual(3, len(features["stat_adjustments"]))

    def test_combat_triangle_triggered_effects_can_scale_by_officer_stat(self) -> None:
        row = _row()
        row["observed"]["officer_activations"] = [
            {
                "firing_ship_id": "defender-ship",
                "ability_buff_id": "ability-defense",
                "officer_id": "officer-defense",
                "modifierCode": "73",
                "op": "BUFFOPERATION_MULTIPLYBASEADD",
                "targetCode": "1",
                "value": 3.0,
                "ability": {
                    "attributes": {
                        "officerStat": "OFFICERCORESTATTYPE_HEALTH",
                    },
                },
                "formula_effect": {"formula_stage": "normal_mitigation_triangle"},
            }
        ]

        features = combat_triangle_features(
            row,
            apply_triggered_effects=True,
            officer_stat_scale="percent",
        )

        self.assertAlmostEqual(700, features["stat_inputs"]["armor"]["defense"])
        self.assertAlmostEqual(700, features["stat_inputs"]["shield"]["defense"])
        self.assertAlmostEqual(700, features["stat_inputs"]["dodge"]["defense"])
        self.assertEqual(6.0, features["stat_adjustments"][0]["effective_value"])
        self.assertEqual(200, features["stat_adjustments"][0]["officer_stat_scale"]["stat_value"])


if __name__ == "__main__":
    unittest.main()
