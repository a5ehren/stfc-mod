from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.hull_buff_map import build_hull_buff_map


def _write_decoded_static(decoded: Path) -> None:
    decoded.mkdir()
    (decoded / "HullSpecs.json").write_text(
        json.dumps(
            {
                "hullSpecs": {
                    "hull-1": {
                        "id": "hull-1",
                        "idStr": "Hull_Test",
                        "name": "Test Hull",
                        "type": "HULLTYPE_EXPLORER",
                        "grade": 4,
                        "rarity": "RARITY_RARE",
                        "coreStatModifiers": [
                            {"type": "OFFICERCORESTATTYPE_ATTACK", "bonus": 3.5, "threshold": 25},
                            {"type": "OFFICERCORESTATTYPE_DEFENSE", "bonus": 3.5, "threshold": 25},
                        ],
                        "shipBonuses": ["bonus-1"],
                    },
                    "bonus-2": {
                        "id": "bonus-2",
                        "idStr": "Hull_Implicit",
                        "name": "Implicit Hull",
                        "coreStatModifiers": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "ShipBonusBuffSpecs.json").write_text(
        json.dumps(
            {
                "shipBonusSpecs": {
                    "bonus-1": {
                        "buffId": "bonus-1",
                        "modifierCode": "78010",
                        "targetCode": 1,
                        "triggerCode": 24,
                        "op": "BUFFOPERATION_MULTIPLYADD",
                        "conditionCodes": ["0"],
                        "rankedValues": [1, 2],
                    },
                    "bonus-2": {
                        "buffId": "bonus-2",
                        "modifierCode": "105",
                        "targetCode": 1,
                        "triggerCode": 24,
                        "op": "BUFFOPERATION_ADD",
                        "rankedBuffValues": [5],
                    },
                }
            }
        ),
        encoding="utf-8",
    )


class HullBuffMapTest(unittest.TestCase):
    def test_builds_static_and_active_hull_buff_maps(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            out_dir = root / "reports"
            audit = root / "buff-audit.json"
            _write_decoded_static(decoded)
            audit.write_text(
                json.dumps(
                    {
                        "active_buffs": [
                            {
                                "source_type": "generated_hull_core_stat_modifier",
                                "hull_ids": ["hull-1"],
                                "buff_id": "runtime-1",
                                "modifierCodes": ["-15", "-16"],
                                "battle_id": "battle-1",
                                "ship_ids": ["ship-1"],
                            },
                            {
                                "source_type": "ship_bonus",
                                "hull_ids": ["hull-1"],
                                "buff_id": "bonus-1",
                                "modifierCode": "78010",
                                "battle_id": "battle-1",
                                "ship_ids": ["ship-1"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_hull_buff_map(
                decoded_static_dir=decoded,
                buff_audit_path=audit,
                out_dir=out_dir,
                label="test",
            )

        self.assertEqual(2, report["summary"]["hull_specs_total"])
        self.assertEqual(1, report["summary"]["hulls_with_core_stat_modifiers"])
        self.assertEqual(2, report["summary"]["ship_bonus_links_total"])
        self.assertEqual(1, report["summary"]["explicit_ship_bonus_links"])
        self.assertEqual(1, report["summary"]["implicit_hull_id_ship_bonus_links"])
        self.assertEqual(1, report["summary"]["generated_hull_core_active_rows"])
        self.assertEqual("Test Hull", report["active_generated_hull_core_buffs"][0]["hull_name"])
        self.assertEqual(["-15", "-16"], report["active_generated_hull_core_buffs"][0]["modifierCodes"])
        self.assertEqual("78010", report["active_ship_bonus_buffs"][0]["modifierCode"])


if __name__ == "__main__":
    unittest.main()
