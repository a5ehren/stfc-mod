from __future__ import annotations

import unittest

from scripts.lib.combat_model.mechanics import (
    HULL_ARMADA,
    HULL_BATTLESHIP,
    HULL_DESTROYER,
    HULL_EXPLORER,
    HULL_INTERCEPTOR,
    HULL_SURVEY,
    apex_barrier_damage_reduction,
    apply_shield_allocation,
    combat_triangle_mitigation,
    isolytic_damage,
    isolytic_mitigation,
    mitigation_component,
    round_shots,
    weights_for,
)


class CombatModelMechanicsTests(unittest.TestCase):
    def test_mitigation_component_matches_toolbox_curve(self) -> None:
        self.assertAlmostEqual(mitigation_component(1100, 1000), 0.5)
        self.assertAlmostEqual(mitigation_component(0, 1000), 1 / (1 + 4**1.1))
        self.assertEqual(mitigation_component(1000, 0), 0.0)

    def test_combat_triangle_uses_toolbox_weighted_product(self) -> None:
        result = combat_triangle_mitigation(
            armor=1100,
            shield=1100,
            dodge=1100,
            armor_piercing=1000,
            shield_piercing=1000,
            accuracy=1000,
            defender_hull_type=HULL_BATTLESHIP,
        )
        self.assertAlmostEqual(result, 1 - (1 - 0.55 * 0.5) * (1 - 0.2 * 0.5) * (1 - 0.2 * 0.5))

    def test_combat_triangle_weights_by_hull_type(self) -> None:
        self.assertEqual(weights_for(HULL_ARMADA), {"armor": 0.3, "shield": 0.3, "dodge": 0.3})
        self.assertEqual(weights_for(HULL_BATTLESHIP), {"armor": 0.55, "shield": 0.2, "dodge": 0.2})
        self.assertEqual(weights_for(HULL_EXPLORER), {"armor": 0.2, "shield": 0.55, "dodge": 0.2})
        self.assertEqual(weights_for(HULL_INTERCEPTOR), {"armor": 0.2, "shield": 0.2, "dodge": 0.55})
        self.assertEqual(weights_for(HULL_DESTROYER), {"armor": 0.2, "shield": 0.2, "dodge": 0.55})
        self.assertEqual(weights_for(HULL_SURVEY), {"armor": 0.3, "shield": 0.3, "dodge": 0.3})

    def test_isolytic_and_apex_formulas_match_toolbox_docs(self) -> None:
        self.assertEqual(isolytic_damage(regular_after_modifiers=1000, isolytic_bonus=0.25, cascade_bonus=0.1), 375)
        self.assertAlmostEqual(isolytic_mitigation(isolytic_defense=3), 0.25)
        self.assertAlmostEqual(apex_barrier_damage_reduction(apex_barrier=10000, apex_shred=0), 0.5)
        self.assertAlmostEqual(
            apex_barrier_damage_reduction(apex_barrier=10000, apex_shred=1),
            10000 / (10000 + 5000),
        )
        self.assertAlmostEqual(isolytic_mitigation(isolytic_defense=-0.5), 2.0)
        self.assertAlmostEqual(
            apex_barrier_damage_reduction(apex_barrier=-5000, apex_shred=0),
            10000 / (10000 - 5000),
        )

    def test_shield_allocation_uses_post_apex_unmitigated_damage(self) -> None:
        allocation = apply_shield_allocation(total_unmitigated_damage=1000, shield_mitigation=0.8, shield_before=600)
        self.assertEqual(allocation["shield"], 600)
        self.assertEqual(allocation["hull"], 400)
        self.assertEqual(allocation["remaining_shield"], 0)

        allocation = apply_shield_allocation(total_unmitigated_damage=1000, shield_mitigation=0.8, shield_before=2000)
        self.assertEqual(allocation["shield"], 800)
        self.assertEqual(allocation["hull"], 200)
        self.assertEqual(allocation["remaining_shield"], 1200)

    def test_weapon_shots_round_half_even(self) -> None:
        self.assertEqual(round_shots(0.5), 0)
        self.assertEqual(round_shots(1.5), 2)
        self.assertEqual(round_shots(2.5), 2)
        self.assertEqual(round_shots(3.5), 4)


if __name__ == "__main__":
    unittest.main()
