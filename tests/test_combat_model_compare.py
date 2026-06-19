from __future__ import annotations

import unittest

from scripts.lib.combat_model.compare import compare_traces
from scripts.lib.combat_model.models import CombatState, DamageBreakdown, ReplayThreshold, RoundTrace
from scripts.lib.combat_model.reporting import render_markdown_report


def _trace(round_number: int, shield: int, hull: int, effects: list[str] | None = None) -> RoundTrace:
    return RoundTrace(
        round_number=round_number,
        acting_side="player",
        action="kinetic",
        attacker=CombatState(hull=10000, shield=5000),
        defender_before=CombatState(hull=8000, shield=3000),
        defender_after=CombatState(hull=8000 - hull, shield=max(0, 3000 - shield)),
        damage=DamageBreakdown(raw=shield + hull, mitigated=shield + hull, shield=shield, hull=hull),
        triggered_effects=effects or [],
    )


class ComparatorTests(unittest.TestCase):
    def test_passes_when_damage_and_triggers_match_threshold(self) -> None:
        result = compare_traces(
            expected=[_trace(1, shield=1000, hull=0, effects=["a"])],
            actual=[_trace(1, shield=1110, hull=0, effects=["a"])],
            threshold=ReplayThreshold.mvp(),
        )

        self.assertTrue(result.passed)
        self.assertEqual([], result.mismatches)

    def test_reports_damage_and_trigger_mismatch(self) -> None:
        result = compare_traces(
            expected=[_trace(1, shield=1000, hull=0, effects=["a"])],
            actual=[_trace(1, shield=1400, hull=0, effects=["b"])],
            threshold=ReplayThreshold.mvp(),
        )

        self.assertFalse(result.passed)
        self.assertEqual(["damage_delta", "trigger_mismatch"], [m.kind for m in result.mismatches])

    def test_renders_markdown_summary(self) -> None:
        result = compare_traces(
            expected=[_trace(1, shield=1000, hull=0)],
            actual=[_trace(1, shield=1400, hull=0)],
            threshold=ReplayThreshold.mvp(),
        )

        markdown = render_markdown_report("sample-fixture", result)

        self.assertIn("# Combat Replay Report: sample-fixture", markdown)
        self.assertIn("damage_delta", markdown)


if __name__ == "__main__":
    unittest.main()
