from __future__ import annotations

import unittest

from scripts.lib.combat_model.ship_bonuses import resolve_static_ship_bonuses


class ShipBonusTests(unittest.TestCase):
    def test_isolytic_ship_bonus_values_below_100_are_not_percent_normalized(self) -> None:
        effects = resolve_static_ship_bonuses(
            {
                "ship_level": 2,
                "static_ship": {"hull": {"ship_bonus_ids": ["iso-bonus"]}},
            },
            {"fleet_faction_id": "any"},
            {
                "ship_bonus_specs": {
                    "iso-bonus": {
                        "buffId": "iso-bonus",
                        "modifierCode": "707",
                        "targetCode": 1,
                        "triggerCode": 25,
                        "op": "BUFFOPERATION_ADD",
                        "rankedValues": [20.25, 23.25],
                    }
                }
            },
        )

        self.assertEqual(23.25, effects["applied_modifiers"][0]["delta"])

    def test_isolytic_ship_bonus_values_at_100_or_above_are_percent_normalized(self) -> None:
        effects = resolve_static_ship_bonuses(
            {
                "ship_level": 1,
                "static_ship": {"hull": {"ship_bonus_ids": ["iso-bonus"]}},
            },
            {"fleet_faction_id": "any"},
            {
                "ship_bonus_specs": {
                    "iso-bonus": {
                        "buffId": "iso-bonus",
                        "modifierCode": "707",
                        "targetCode": 1,
                        "triggerCode": 25,
                        "op": "BUFFOPERATION_ADD",
                        "rankedValues": [275],
                    }
                }
            },
        )

        self.assertEqual(2.75, effects["applied_modifiers"][0]["delta"])


if __name__ == "__main__":
    unittest.main()
