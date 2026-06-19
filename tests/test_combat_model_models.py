from __future__ import annotations

import unittest

from scripts.lib.combat_model.models import (
    CombatState,
    DamageBreakdown,
    ReplayThreshold,
    RoundTrace,
)


class CombatModelTests(unittest.TestCase):
    def test_threshold_accepts_mvp_damage_delta(self) -> None:
        threshold = ReplayThreshold.mvp()

        self.assertTrue(threshold.damage_within_limit(expected=1000, actual=1125))
        self.assertTrue(threshold.damage_within_limit(expected=1000, actual=800))
        self.assertFalse(threshold.damage_within_limit(expected=1000, actual=799))
        self.assertFalse(threshold.damage_within_limit(expected=1000, actual=1201))

    def test_round_trace_serializes_to_plain_dict(self) -> None:
        trace = RoundTrace(
            round_number=1,
            acting_side="player",
            action="kinetic",
            attacker=CombatState(hull=10000, shield=5000),
            defender_before=CombatState(hull=8000, shield=3000),
            defender_after=CombatState(hull=7500, shield=0),
            damage=DamageBreakdown(raw=4000, mitigated=3500, shield=3000, hull=500),
            triggered_effects=["captain_maneuver"],
        )

        self.assertEqual(
            trace.to_dict(),
            {
                "round": 1,
                "acting_side": "player",
                "action": "kinetic",
                "attacker": {"hull": 10000, "shield": 5000},
                "defender_before": {"hull": 8000, "shield": 3000},
                "defender_after": {"hull": 7500, "shield": 0},
                "damage": {"raw": 4000, "mitigated": 3500, "shield": 3000, "hull": 500},
                "triggered_effects": ["captain_maneuver"],
            },
        )


if __name__ == "__main__":
    unittest.main()
