from __future__ import annotations

import unittest

from scripts.lib.combat_model.simulator_state import (
    attach_resolved_player_state,
    build_resolved_player_state_index,
)


class SimulatorStateTests(unittest.TestCase):
    def test_builds_resolved_player_state_index_from_buff_audit_rows(self) -> None:
        audit = {
            "active_buffs": [
                {
                    "battle_id": "battle-1",
                    "side": "player",
                    "ship_ids": ["111"],
                    "modifierCode": "707",
                    "selected_ranked_value": 0.38,
                    "source_type": "research",
                },
                {
                    "battle_id": "battle-1",
                    "side": "player",
                    "ship_ids": ["111"],
                    "modifierCode": "707",
                    "selected_ranked_value": 0.69,
                    "source_type": "starbase",
                },
                {
                    "battle_id": "battle-1",
                    "side": "player",
                    "ship_ids": ["111"],
                    "modifierCode": "59",
                    "buffOperation": "BUFFOPERATION_MULTIPLYADD",
                    "targetCode": "5",
                    "triggerCode": "24",
                    "selected_ranked_value": 5,
                    "selected_rank": 34,
                    "buff_id": "660954013",
                    "source_type": "starbase",
                    "source_key": "starbaseBuffsSpecs/660954013",
                },
            ],
            "live_stat_residuals": [
                {
                    "battle_id": "battle-1",
                    "battle_side": "initiator",
                    "side": "player",
                    "ship_id": "111",
                    "hull_id": "hull-1",
                    "hull_type": "HULLTYPE_DESTROYER",
                    "stat_code": "6",
                    "captured": 105,
                    "static": 50,
                    "explained": 100,
                    "residual": 5,
                    "math_status": "operation_model_partial",
                    "explanation_components": {
                        "selected_live_stat_model": "primary_operation_model",
                    },
                },
                {
                    "battle_id": "battle-1",
                    "battle_side": "initiator",
                    "side": "player",
                    "ship_id": "111",
                    "hull_id": "hull-1",
                    "hull_type": "HULLTYPE_DESTROYER",
                    "stat_code": "11",
                    "captured": 50,
                    "static": 25,
                    "explained": 50,
                    "residual": 0,
                    "math_status": "related_modifier_model_closed",
                    "explanation_components": {
                        "selected_live_stat_model": "related_modifier_model",
                    },
                },
                {
                    "battle_id": "battle-1",
                    "battle_side": "target",
                    "side": "hostile",
                    "ship_id": "0",
                    "stat_code": "6",
                    "captured": 10,
                    "explained": 10,
                    "residual": 0,
                },
            ]
        }

        index = build_resolved_player_state_index(audit)

        self.assertEqual([("battle-1", "111")], sorted(index))
        state = index[("battle-1", "111")]
        self.assertEqual("initiator", state["battle_side"])
        self.assertEqual("hull-1", state["hull_id"])
        self.assertEqual("HULLTYPE_DESTROYER", state["hull_type"])
        self.assertEqual({"6": 100, "11": 50}, state["resolved_stats"])
        self.assertAlmostEqual(1.07, state["resolved_modifiers"]["707"])
        self.assertEqual(5, state["resolved_modifiers"]["59"])
        self.assertEqual(
            [
                {
                    "buff_id": "660954013",
                    "modifierCode": "59",
                    "buffOperation": "BUFFOPERATION_MULTIPLYADD",
                    "targetCode": "5",
                    "triggerCode": "24",
                    "selected_ranked_value": 5,
                    "selected_rank": 34,
                    "source_type": "starbase",
                    "source_key": "starbaseBuffsSpecs/660954013",
                }
            ],
            state["resolved_modifier_rows"],
        )
        self.assertEqual({"6": 105, "11": 50}, state["captured_stats"])
        self.assertEqual({"6": 50, "11": 25}, state["static_stats"])
        self.assertEqual(5, state["max_abs_residual"])
        self.assertEqual({"operation_model_partial": 1, "related_modifier_model_closed": 1}, state["math_statuses"])
        self.assertEqual("primary_operation_model", state["stat_rows"]["6"]["selected_live_stat_model"])

    def test_attach_resolved_player_state_does_not_mutate_observation(self) -> None:
        index = {
            ("battle-1", "111"): {
                "battle_id": "battle-1",
                "ship_id": "111",
                "resolved_stats": {"6": 100, "7": 200},
                "captured_stats": {"6": 105, "7": 205},
                "resolved_modifiers": {"707": 1.07},
                "resolved_modifier_rows": [{"modifierCode": "59", "selected_ranked_value": 5}],
                "max_abs_residual": 5,
                "math_statuses": {"operation_model_partial": 2},
            }
        }
        observation = {
            "battle_id": "battle-1",
            "attacker_side": "player",
            "defender_side": "hostile",
            "attacker": {"ship_id": 111, "captured_stats": {"6": 105}, "captured_fleet_stats": {"707": 2.07}},
            "defender": {"ship_id": 0, "captured_stats": {"11": 50}},
            "observed": {
                "normal_mitigation": {"raw_damage": 1000},
                "isolytic_damage": 1070,
                "mitigated_isolytic_damage": 0,
            },
        }

        attached = attach_resolved_player_state(observation, index)

        self.assertNotIn("resolved_stats", observation["attacker"])
        self.assertEqual({"6": 100, "7": 200}, attached["attacker"]["resolved_stats"])
        self.assertEqual({"707": 2.07}, attached["attacker"]["resolved_modifiers"])
        self.assertEqual(
            [{"modifierCode": "59", "selected_ranked_value": 5}],
            attached["attacker"]["resolved_modifier_rows"],
        )
        self.assertEqual("resolved_buff_audit", attached["observed"]["isolytic_damage_model"]["source"])
        self.assertAlmostEqual(1.07, attached["observed"]["isolytic_damage_model"]["damage_multiplier"])
        self.assertEqual("captured_final_fleet_707_plus_resolved_cascade", attached["observed"]["isolytic_damage_model"]["multiplier_source"])
        self.assertEqual(
            {
                "source": "buff_audit",
                "battle_id": "battle-1",
                "ship_id": "111",
                "max_abs_residual": 5,
                "math_statuses": {"operation_model_partial": 2},
            },
            attached["attacker"]["resolved_stat_source"],
        )
        self.assertNotIn("resolved_stats", attached["defender"])


if __name__ == "__main__":
    unittest.main()
