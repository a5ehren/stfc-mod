from __future__ import annotations

import unittest

from scripts.lib.combat_model.damage_pipeline import (
    infer_pre_shot_state,
    observed_damage_stages,
    predict_damage_from_stages,
    weapon_damage_diagnostics,
)


class CombatModelDamagePipelineTests(unittest.TestCase):
    def test_reports_static_weapon_damage_diagnostics(self) -> None:
        row = {
            "weapon": {
                "minimum_damage": 100,
                "maximum_damage": 300,
                "shots": 2,
                "accuracy": 50,
                "penetration": 60,
                "modulation": 70,
                "crit_modifier": 1.5,
            },
        }

        diagnostics = weapon_damage_diagnostics(row)

        self.assertEqual(100, diagnostics["base_min"])
        self.assertEqual(300, diagnostics["base_max"])
        self.assertEqual(200, diagnostics["base_midpoint"])
        self.assertEqual(2, diagnostics["shots"])
        self.assertEqual(100, diagnostics["damage_per_shot_midpoint"])
        self.assertEqual(50, diagnostics["accuracy"])
        self.assertEqual(60, diagnostics["armor_piercing"])
        self.assertEqual(70, diagnostics["shield_piercing"])
        self.assertEqual(1.5, diagnostics["crit_modifier"])

    def test_infers_pre_shot_state_from_observed_damage_and_remaining_state(self) -> None:
        row = {
            "observed": {
                "damage": {"shield": 544, "hull": 136},
                "remaining": {"shield": 456, "hull": 864},
            },
        }

        self.assertEqual({"shield": 1000, "hull": 1000}, infer_pre_shot_state(row))

    def test_predicts_standard_iso_apex_shield_stage_order(self) -> None:
        row = {
            "defender": {
                "static_ship": {
                    "base_stats": {
                        "shield_mitigation": 0.8,
                    },
                },
            },
            "observed": {
                "damage": {"shield": 544, "hull": 136},
                "remaining": {"shield": 456, "hull": 864},
            },
        }

        prediction = predict_damage_from_stages(
            row,
            standard_raw_damage=1000,
            standard_mitigation=0.25,
            isolytic_raw_damage=200,
            isolytic_mitigation=0.5,
            apex_mitigation=0.2,
        )

        self.assertEqual("standard_iso_apex_shield", prediction["mode"])
        self.assertEqual({"shield": 1000, "hull": 1000}, prediction["pre_shot"])
        self.assertEqual(750, prediction["standard_unmitigated"])
        self.assertEqual(100, prediction["isolytic_unmitigated"])
        self.assertEqual(680, prediction["after_apex"])
        self.assertEqual({"shield": 544, "hull": 136}, prediction["damage"])
        self.assertEqual({"shield": 456, "hull": 864}, prediction["remaining"])

    def test_predicts_standard_path_with_default_shield_mitigation(self) -> None:
        row = {
            "observed": {
                "damage": {"shield": 800, "hull": 200},
                "remaining": {"shield": 200, "hull": 800},
            },
        }

        prediction = predict_damage_from_stages(
            row,
            standard_raw_damage=1000,
            standard_mitigation=0,
        )

        self.assertEqual("standard_iso_apex_shield", prediction["mode"])
        self.assertEqual(1000, prediction["standard_unmitigated"])
        self.assertEqual(0, prediction["isolytic_unmitigated"])
        self.assertEqual(1000, prediction["after_apex"])
        self.assertEqual({"shield": 800, "hull": 200}, prediction["damage"])
        self.assertEqual({"shield": 200, "hull": 800}, prediction["remaining"])

    def test_predicts_cutting_beam_as_scaled_direct_hull_damage(self) -> None:
        row = {
            "battle_type": 13,
            "defender": {
                "static_ship": {
                    "base_stats": {
                        "shield_mitigation": 0.95,
                    },
                },
            },
            "observed": {
                "cutting_beam_unscaled_damage": 1000,
                "cutting_beam_player_level": 50,
                "cutting_beam_hostile_level": 52,
                "damage": {"shield": 0, "hull": 800},
                "remaining": {"shield": 1000, "hull": 200},
            },
        }

        prediction = predict_damage_from_stages(
            row,
            standard_raw_damage=1000,
            standard_mitigation=0.95,
            isolytic_raw_damage=500,
            isolytic_mitigation=0.95,
            apex_mitigation=0.95,
        )

        self.assertEqual("cutting_beam_direct_hull", prediction["mode"])
        self.assertEqual({"shield": 1000, "hull": 1000}, prediction["pre_shot"])
        self.assertEqual(0, prediction["standard_unmitigated"])
        self.assertEqual(0, prediction["isolytic_unmitigated"])
        self.assertEqual(800, prediction["after_apex"])
        self.assertEqual({"shield": 0, "hull": 800}, prediction["damage"])
        self.assertEqual({"shield": 1000, "hull": 200}, prediction["remaining"])

    def test_predicts_cutting_beam_from_standard_raw_damage_when_observed_unscaled_is_absent(self) -> None:
        row = {
            "battle_type": 14,
            "observed": {
                "damage": {"shield": 0, "hull": 700},
                "remaining": {"shield": 1000, "hull": 300},
            },
        }

        prediction = predict_damage_from_stages(
            row,
            standard_raw_damage=700,
            standard_mitigation=0.95,
            isolytic_raw_damage=500,
            isolytic_mitigation=0.95,
            apex_mitigation=0.95,
        )

        self.assertEqual("cutting_beam_direct_hull", prediction["mode"])
        self.assertEqual({"shield": 1000, "hull": 1000}, prediction["pre_shot"])
        self.assertEqual(0, prediction["standard_unmitigated"])
        self.assertEqual(0, prediction["isolytic_unmitigated"])
        self.assertEqual(700, prediction["after_apex"])
        self.assertEqual({"shield": 0, "hull": 700}, prediction["damage"])
        self.assertEqual({"shield": 1000, "hull": 300}, prediction["remaining"])

    def test_does_not_level_scale_cutting_beam_fallback_raw_damage(self) -> None:
        row = {
            "battle_type": 14,
            "player_level": 10,
            "hostile_level": 12,
            "observed": {
                "damage": {"shield": 0, "hull": 800},
                "remaining": {"shield": 1000, "hull": 200},
            },
        }

        prediction = predict_damage_from_stages(
            row,
            standard_raw_damage=800,
            standard_mitigation=0.95,
            isolytic_raw_damage=500,
            isolytic_mitigation=0.95,
            apex_mitigation=0.95,
        )

        self.assertEqual("cutting_beam_direct_hull", prediction["mode"])
        self.assertEqual(800, prediction["after_apex"])
        self.assertEqual({"shield": 0, "hull": 800}, prediction["damage"])
        self.assertEqual({"shield": 1000, "hull": 200}, prediction["remaining"])

    def test_observed_damage_stages_match_toolbox_attack_totals(self) -> None:
        row = {
            "observed": {
                "damage": {
                    "hull": 70,
                    "shield": 130,
                },
                "mitigated_damage": 300,
                "isolytic_damage": 40,
                "mitigated_isolytic_damage": 10,
                "mitigated_apex_barrier": 50,
            },
        }

        stages = observed_damage_stages(row)

        self.assertEqual(70, stages["taken_hull"])
        self.assertEqual(130, stages["taken_shield"])
        self.assertEqual(300, stages["std_mitigated"])
        self.assertEqual(40, stages["iso_unmitigated"])
        self.assertEqual(10, stages["iso_mitigated"])
        self.assertEqual(50, stages["apex_mitigated"])
        self.assertEqual(50, stages["iso_raw"])
        self.assertEqual(510, stages["std_raw"])
        self.assertEqual(560, stages["damage_total_before_all_mitigation"])
        self.assertEqual(250, stages["damage_before_apex"])
        self.assertEqual(300 / 510, stages["std_mitigation"])
        self.assertEqual(10 / 50, stages["iso_mitigation"])
        self.assertEqual(50 / 250, stages["apex_mitigation"])
        self.assertEqual(1 - 200 / 560, stages["all_mitigation"])


if __name__ == "__main__":
    unittest.main()
