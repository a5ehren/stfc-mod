from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.static_catalog import build_static_ship, compare_static_catalog, load_static_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_decoded_static(decoded: Path) -> None:
    decoded.mkdir()
    (decoded / "HullSpecs.json").write_text(
        json.dumps(
            {
                "hullSpecs": {
                    "hull-1": {
                        "id": "hull-1",
                        "idStr": "Hull_Test_Survey",
                        "name": "Test Survey",
                        "type": "HULLTYPE_SURVEY",
                        "grade": 5,
                        "rarity": "RARITY_COMMON",
                        "activatedAbilitiesIds": ["ability-1"],
                        "componentDefaults": [
                            "armor-1",
                            "shield-1",
                            "impulse-1",
                            "sensor-1",
                            "deflector-1",
                            "weapon-1",
                            "-1",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "ActivatedAbilitySpecs.json").write_text(
        json.dumps(
            {
                "spec": [
                    {
                        "id": "ability-1",
                        "idStr": "TEST_ABILITY",
                        "abilityType": "ACTIVATEDABILITYTYPE_TEST",
                        "targetCode": 1,
                        "statusEffect": "effect-1",
                        "researchId": "-1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (decoded / "ComponentSpecs.json").write_text(
        json.dumps(
            {
                "componentSpecs": {
                    "armor-1": {"id": "armor-1", "name": "Armor", "armorSpec": {"hp": 1000, "plating": 25}},
                    "shield-1": {
                        "id": "shield-1",
                        "type": "COMPONENTTYPE_SHIELD",
                        "name": "Shield",
                        "shieldSpec": {"hp": 2000, "absorption": 30, "mitigation": 0.8},
                    },
                    "impulse-1": {
                        "id": "impulse-1",
                        "type": "COMPONENTTYPE_IMPULSE",
                        "name": "Impulse",
                        "impulseSpec": {"dodge": 40, "impulse": 10},
                    },
                    "sensor-1": {
                        "id": "sensor-1",
                        "type": "COMPONENTTYPE_SENSOR",
                        "name": "Sensor",
                        "sensorSpec": {"sensorRating": 120},
                    },
                    "deflector-1": {
                        "id": "deflector-1",
                        "type": "COMPONENTTYPE_DEFLECTOR",
                        "name": "Deflector",
                        "deflectorSpec": {"deflection": 130},
                    },
                    "weapon-1": {
                        "id": "weapon-1",
                        "type": "COMPONENTTYPE_WEAPON",
                        "name": "Weapon",
                        "weaponSpec": {
                            "attack": {
                                "minimumDamage": "100",
                                "maximumDamage": "200",
                                "shots": 3,
                                "warmUp": 1,
                                "coolDown": 2,
                                "accuracy": "50",
                                "penetration": "60",
                                "modulation": 70,
                                "critChance": 0.1,
                                "critModifier": 1.5,
                            }
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def _write_capture(capture_root: Path) -> None:
    battles = capture_root / "battles"
    battles.mkdir(parents=True)
    (battles / "battle-1.json").write_text(
        json.dumps(
            {
                "server_version": "test-version",
                "journal": {
                    "id": 123,
                    "target_fleet_data": {
                        "deployed_fleet": {
                            "hull_ids": ["hull-1"],
                            "ship_ids": [0],
                            "ship_components": {
                                "0": ["armor-1", "shield-1", "impulse-1", "sensor-1", "deflector-1", "weapon-1"]
                            },
                            "ship_hps": {"0": 1000},
                            "ship_shield_hps": {"0": 2000},
                            "ship_levels": {"0": 51},
                            "ship_tiers": {"0": 1},
                            "ship_stats": {
                                "0": {
                                    "-3": 25,
                                    "-2": 30,
                                    "6": 50,
                                    "7": 60,
                                    "8": 70,
                                    "9": 0.1,
                                    "10": 1.5,
                                    "11": 40,
                                    "60": 2000,
                                    "61": 1000,
                                }
                            },
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )


class StaticCatalogTests(unittest.TestCase):
    def test_builds_static_ship_from_hull_and_components(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(catalog, "hull-1")

        self.assertEqual("Hull_Test_Survey", ship["hull"]["id_str"])
        self.assertEqual(["ability-1"], ship["hull"]["activatedAbilitiesIds"])
        self.assertEqual(["ability-1"], ship["hull"]["activated_ability_ids"])
        self.assertEqual("TEST_ABILITY", ship["hull"]["activated_abilities"][0]["id_str"])
        self.assertEqual("ACTIVATEDABILITYTYPE_TEST", ship["hull"]["activated_abilities"][0]["ability_type"])
        self.assertEqual(1000, ship["base_stats"]["hull_hp"])
        self.assertEqual(2000, ship["base_stats"]["shield_hp"])
        self.assertEqual(25, ship["base_stats"]["armor_plating"])
        self.assertEqual(30, ship["base_stats"]["shield_absorption"])
        self.assertEqual(40, ship["base_stats"]["dodge"])
        self.assertEqual(50, ship["base_stats"]["weapon_accuracy_max"])
        self.assertEqual(1, len(ship["weapons"]))
        self.assertEqual(3, ship["weapons"][0]["shots"])
        self.assertEqual("found", ship["stat_sources"]["shield_hp"]["status"])
        self.assertEqual("shield-1", ship["stat_sources"]["shield_hp"]["component_id"])
        self.assertEqual("shieldSpec.hp", ship["stat_sources"]["shield_hp"]["field_path"])

    def test_preserves_implicit_hull_keyed_ship_bonus(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)
            (decoded / "ShipBonusBuffSpecs.json").write_text(
                json.dumps({"shipBonusSpecs": {"hull-1": {"buffId": "hull-1", "modifierCode": "2"}}}),
                encoding="utf-8",
            )

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(catalog, "hull-1")

        self.assertEqual([], ship["hull"]["ship_bonus_ids"])
        self.assertEqual(["hull-1"], ship["hull"]["implicit_ship_bonus_ids"])
        self.assertEqual(["hull-1"], ship["hull"]["all_ship_bonus_ids"])
        self.assertEqual("ShipBonusBuffSpecs.hullId", ship["hull"]["ship_bonus_sources"]["hull-1"])

    def test_static_ship_averages_equipped_weapon_combat_stats(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)
            component_specs_path = decoded / "ComponentSpecs.json"
            component_specs = json.loads(component_specs_path.read_text(encoding="utf-8"))
            component_specs["componentSpecs"]["weapon-2"] = {
                **component_specs["componentSpecs"]["weapon-1"],
                "id": "weapon-2",
                "name": "Weapon 2",
                "weaponSpec": {
                    "attack": {
                        **component_specs["componentSpecs"]["weapon-1"]["weaponSpec"]["attack"],
                        "accuracy": 70,
                        "penetration": 90,
                        "modulation": 110,
                    }
                },
            }
            component_specs_path.write_text(json.dumps(component_specs), encoding="utf-8")

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(
                catalog,
                "hull-1",
                component_ids=["armor-1", "shield-1", "impulse-1", "weapon-1", "weapon-2"],
            )

        self.assertEqual(60, ship["base_stats"]["weapon_accuracy_max"])
        self.assertEqual(75, ship["base_stats"]["weapon_penetration_max"])
        self.assertEqual(90, ship["base_stats"]["weapon_modulation_max"])
        source = ship["stat_sources"]["weapon_accuracy_max"]
        self.assertEqual("found_average", source["status"])
        self.assertEqual(["weapon-1", "weapon-2"], source["component_ids"])
        self.assertEqual([50, 70], source["values"])

    def test_static_ship_floors_fractional_weapon_stat_averages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)
            component_specs_path = decoded / "ComponentSpecs.json"
            component_specs = json.loads(component_specs_path.read_text(encoding="utf-8"))
            component_specs["componentSpecs"]["weapon-2"] = {
                **component_specs["componentSpecs"]["weapon-1"],
                "id": "weapon-2",
                "name": "Weapon 2",
                "weaponSpec": {
                    "attack": {
                        **component_specs["componentSpecs"]["weapon-1"]["weaponSpec"]["attack"],
                        "accuracy": 51,
                        "penetration": 61,
                        "modulation": 71,
                    }
                },
            }
            component_specs_path.write_text(json.dumps(component_specs), encoding="utf-8")

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(
                catalog,
                "hull-1",
                component_ids=["armor-1", "shield-1", "impulse-1", "weapon-1", "weapon-2"],
            )

        self.assertEqual(50, ship["base_stats"]["weapon_accuracy_max"])
        self.assertEqual(60, ship["base_stats"]["weapon_penetration_max"])
        self.assertEqual(70, ship["base_stats"]["weapon_modulation_max"])
        source = ship["stat_sources"]["weapon_accuracy_max"]
        self.assertEqual(50.5, source["raw_average"])
        self.assertEqual("floor_average", source["rounding"])

    def test_static_ship_reports_missing_component_fields_and_tier_tables(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)
            component_specs_path = decoded / "ComponentSpecs.json"
            component_specs = json.loads(component_specs_path.read_text(encoding="utf-8"))
            del component_specs["componentSpecs"]["shield-1"]["shieldSpec"]["hp"]
            component_specs_path.write_text(json.dumps(component_specs), encoding="utf-8")

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(catalog, "hull-1")

        self.assertNotIn("shield_hp", ship["base_stats"])
        shield_source = ship["stat_sources"]["shield_hp"]
        self.assertEqual("missing_static_field", shield_source["status"])
        self.assertEqual("ComponentSpecs", shield_source["source_table"])
        self.assertEqual("shield-1", shield_source["component_id"])
        self.assertEqual("shieldSpec.hp", shield_source["field_path"])
        self.assertEqual("missing_source_table", ship["tier_static_sources"]["BaseShipTierSpecs"]["status"])
        self.assertEqual("missing_source_table", ship["tier_static_sources"]["ShipTierSpecs"]["status"])

    def test_static_ship_reports_selected_tier_stat_modifiers_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)
            (decoded / "BaseShipTierSpecs.json").write_text(
                json.dumps({"baseShipTierSpecs": {"2": {"tier": 2, "maxShipLevel": 20, "rarity": "RARITY_COMMON"}}}),
                encoding="utf-8",
            )
            (decoded / "ShipTierSpecs.json").write_text(
                json.dumps(
                    {
                        "shipTierSpecs": {
                            "hull-1": {
                                "hullId": "hull-1",
                                "tierStatModifiers": {
                                    "2": {"tier": 2, "statModifiers": {"60": 500, "61": 1000}}
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(catalog, "hull-1", ship_tier=2)

        self.assertEqual("found", ship["tier_static_sources"]["BaseShipTierSpecs"]["status"])
        self.assertEqual("found", ship["tier_static_sources"]["ShipTierSpecs"]["status"])
        self.assertEqual(
            {
                "source_table": "ShipTierSpecs",
                "hull_id": "hull-1",
                "ship_tier": 2,
                "modifierCode": "60",
                "value": 500,
            },
            ship["tier_stat_modifiers_by_code"]["60"],
        )
        self.assertEqual(1000, ship["tier_stat_modifiers_by_code"]["61"]["value"])

    def test_static_ship_reports_client_ship_stat_lookup_for_hull_type_and_level(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)
            (decoded / "ClientShipStatLookupSpecs.json").write_text(
                json.dumps(
                    {
                        "clientShipStatLookupSpecs": {
                            "shipStats": [
                                {
                                    "level": 51,
                                    "surveyAccuracy": 500,
                                    "surveyPenetration": 600,
                                    "surveyModulation": 700,
                                    "surveyDodge": 400,
                                    "surveyPlating": 250,
                                    "surveyAbsorption": 300,
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(catalog, "hull-1", ship_level=51)

        self.assertEqual(
            {
                "status": "found",
                "source_table": "ClientShipStatLookupSpecs",
                "ship_level": 51,
                "hull_type": "HULLTYPE_SURVEY",
                "lookup_field": "surveyDodge",
                "value": 400,
            },
            ship["client_ship_stat_lookup_sources"]["dodge"],
        )
        self.assertEqual(500, ship["client_ship_stat_lookup_sources"]["weapon_accuracy_max"]["value"])
        self.assertEqual(250, ship["client_ship_stat_lookup_sources"]["armor_plating"]["value"])

    def test_builds_hull_type_from_id_string_when_enum_type_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)
            hull_specs_path = decoded / "HullSpecs.json"
            hull_specs = json.loads(hull_specs_path.read_text(encoding="utf-8"))
            hull_specs["hullSpecs"]["hull-1"]["type"] = None
            hull_specs["hullSpecs"]["hull-1"]["idStr"] = "Hull_G4_Destroyer_None_Junker"
            hull_specs_path.write_text(json.dumps(hull_specs), encoding="utf-8")

            catalog = load_static_catalog(decoded)
            ship = build_static_ship(catalog, "hull-1")

        self.assertEqual("HULLTYPE_DESTROYER", ship["hull"]["type"])
        self.assertEqual("idStr", ship["hull"]["type_source"])

    def test_compares_static_ship_to_captured_hostile_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            report = compare_static_catalog(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(1, report["summary"]["ship_samples"])
        self.assertEqual(10, report["summary"]["compared_fields"])
        self.assertEqual(10, report["summary"]["exact_matches"])
        self.assertEqual([], report["samples"][0]["static_ship"]["missing_component_ids"])

    def test_cli_static_catalog_writes_report_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            out_path = root / "report.json"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "static-catalog",
                    "--decoded-static-dir",
                    str(decoded),
                    "--capture-root",
                    str(capture_root),
                    "--out",
                    str(out_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(1, report["summary"]["ship_samples"])
            self.assertEqual("hull-1", report["samples"][0]["hull_id"])


if __name__ == "__main__":
    unittest.main()
