from __future__ import annotations

import unittest

from scripts.lib.combat_model.mitigation_targets import (
    isolytic_damage_model_from_observed,
    normal_effective_mitigation,
    normal_mitigation_from_observed,
)


class MitigationTargetTests(unittest.TestCase):
    def test_restores_apex_before_subtracting_isolytic_damage(self) -> None:
        observed = {
            "damage": {"shield": 100, "hull": 0},
            "mitigated_damage": 25,
            "isolytic_damage": 150,
            "mitigated_isolytic_damage": 0,
            "mitigated_apex_barrier": 100,
        }

        normal = normal_mitigation_from_observed(observed)

        self.assertEqual(50, normal["observed_damage"])
        self.assertEqual(75, normal["raw_damage"])
        self.assertAlmostEqual(1 / 3, normal["effective_mitigation"])
        self.assertEqual("normal_then_isolytic_then_apex", normal["stage_order"])

    def test_normal_effective_mitigation_recomputes_stage_order_for_old_rows(self) -> None:
        row = {
            "observed": {
                "damage": {"shield": 100, "hull": 0},
                "mitigated_damage": 25,
                "isolytic_damage": 150,
                "mitigated_isolytic_damage": 0,
                "mitigated_apex_barrier": 100,
                "normal_mitigation": {"effective_mitigation": 1.0},
            }
        }

        self.assertAlmostEqual(1 / 3, normal_effective_mitigation(row))

    def test_isolytic_model_uses_captured_final_707_as_one_plus_bonus_with_cascade(self) -> None:
        observed = {
            "damage": {"shield": 2305, "hull": 0},
            "mitigated_damage": 0,
            "isolytic_damage": 1305,
            "mitigated_isolytic_damage": 0,
            "forbidden_tech_activations": [
                {"modifierCode": "707", "op": "BUFFOPERATION_ADD", "value": 0.02},
            ],
        }

        model = isolytic_damage_model_from_observed(
            observed,
            attacker_stats={"707": 2.26},
            attacker_stat_source="captured_fleet_stats",
        )

        self.assertAlmostEqual(1.3052, model["damage_multiplier"])
        self.assertAlmostEqual(1.26, model["isolytic_bonus"])
        self.assertAlmostEqual(0.02, model["cascade_bonus"])
        self.assertEqual("captured_final_fleet_707", model["multiplier_source"])

    def test_isolytic_model_preserves_static_707_as_base_bonus(self) -> None:
        observed = {
            "damage": {"shield": 21250, "hull": 0},
            "mitigated_damage": 0,
            "isolytic_damage": 20250,
            "mitigated_isolytic_damage": 0,
        }

        model = isolytic_damage_model_from_observed(
            observed,
            attacker_stats={"707": 20.25},
            attacker_stat_source="resolved_buff_audit_static_ship_bonus",
        )

        self.assertAlmostEqual(20.25, model["damage_multiplier"])
        self.assertAlmostEqual(20.25, model["isolytic_bonus"])
        self.assertEqual("resolved_static_707_bonus", model["multiplier_source"])


if __name__ == "__main__":
    unittest.main()
