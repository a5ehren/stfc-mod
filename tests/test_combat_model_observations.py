from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.observations import export_observations


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_decoded_static(decoded: Path) -> None:
    decoded.mkdir()
    (decoded / "HullSpecs.json").write_text(
        json.dumps(
            {
                "hullSpecs": {
                    "player-hull": {
                        "id": "player-hull",
                        "idStr": "Hull_Player",
                        "type": "HULLTYPE_EXPLORER",
                        "componentDefaults": ["player-armor", "player-shield", "player-weapon"],
                    },
                    "hostile-hull": {
                        "id": "hostile-hull",
                        "idStr": "Hull_Hostile",
                        "type": "HULLTYPE_SURVEY",
                        "componentDefaults": ["hostile-armor", "hostile-shield", "hostile-weapon"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "ComponentSpecs.json").write_text(
        json.dumps(
            {
                "componentSpecs": {
                    "player-armor": {"id": "player-armor", "armorSpec": {"hp": 1000, "plating": 10}},
                    "player-shield": {
                        "id": "player-shield",
                        "type": "COMPONENTTYPE_SHIELD",
                        "shieldSpec": {"hp": 2000, "absorption": 20, "mitigation": 0.8},
                    },
                    "player-weapon": {
                        "id": "player-weapon",
                        "type": "COMPONENTTYPE_WEAPON",
                        "weaponSpec": {
                            "attack": {
                                "minimumDamage": "100",
                                "maximumDamage": "200",
                                "shots": 2,
                                "warmUp": 1,
                                "coolDown": 1,
                                "accuracy": "50",
                                "penetration": "60",
                                "modulation": "70",
                                "critChance": 0.1,
                                "critModifier": 1.5,
                            }
                        },
                    },
                    "hostile-armor": {"id": "hostile-armor", "armorSpec": {"hp": 800, "plating": 30}},
                    "hostile-shield": {
                        "id": "hostile-shield",
                        "type": "COMPONENTTYPE_SHIELD",
                        "shieldSpec": {"hp": 1200, "absorption": 40, "mitigation": 0.8},
                    },
                    "hostile-weapon": {
                        "id": "hostile-weapon",
                        "type": "COMPONENTTYPE_WEAPON",
                        "weaponSpec": {
                            "attack": {
                                "minimumDamage": "300",
                                "maximumDamage": "400",
                                "shots": 3,
                                "warmUp": 1,
                                "coolDown": 2,
                                "accuracy": "90",
                                "penetration": "100",
                                "modulation": "110",
                                "critChance": 0.2,
                                "critModifier": 1.8,
                            }
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "OfficerSpecs.json").write_text(
        json.dumps(
            {
                "officerSpecs": {
                    "officer-1": {
                        "id": "officer-1",
                        "idStr": "Officer_Test_One",
                        "name": "Officer One",
                        "idRefs": {"locaId": "officer-one-loca"},
                        "captainManeuverId": "-1",
                        "officerAbilityId": "ability-1",
                        "belowDecksAbilityId": "-1",
                        "rarity": "RARITY_RARE",
                        "officerClassType": "OFFICERCORESTATTYPE_ATTACK",
                        "officerType": "OFFICERTYPE_REGULAROFFICER",
                        "factionId": "fed",
                    },
                    "officer-2": {
                        "id": "officer-2",
                        "idStr": "Officer_Test_Two",
                        "name": "Officer Two",
                        "captainManeuverId": "-1",
                        "officerAbilityId": "-1",
                        "belowDecksAbilityId": "ability-2",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "OfficerAbilityBuffSpecs.json").write_text(
        json.dumps(
            {
                "officerAbilitySpecs": {
                    "ability-1": {
                        "buffId": "ability-1",
                        "targetCode": 1,
                        "triggerCode": 25,
                        "op": "BUFFOPERATION_MULTIPLYADD",
                        "modifierCode": "707",
                        "showPercentage": True,
                        "rankedValues": [0.1, 0.2, 0.25],
                        "conditionCodes": ["27"],
                        "attributes": {"combat": "test"},
                    },
                    "ability-2": {
                        "buffId": "ability-2",
                        "targetCode": 2,
                        "triggerCode": 25,
                        "op": "BUFFOPERATION_ADD",
                        "modifierCode": "9",
                        "rankedBuffValues": [1, 2, 3],
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def _fleet(
    hull_id: str,
    ship_id: int,
    components: list[str],
    *,
    hull: int,
    shield: int,
    level: int = 1,
    tier: int = 1,
    faction_id: int | str = -1,
    active_buffs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "faction_id": faction_id,
        "deployed_fleet": {
            "hull_ids": [hull_id],
            "ship_ids": [ship_id],
            "ship_components": {str(ship_id): components},
            "ship_levels": {str(ship_id): level},
            "ship_tiers": {str(ship_id): tier},
            "ship_hps": {str(ship_id): hull},
            "ship_shield_hps": {str(ship_id): shield},
            "ship_stats": {
                str(ship_id): {
                    "-3": 40,
                    "-2": 30,
                    "6": 90,
                    "7": 100,
                    "8": 110,
                    "9": 0.2,
                    "10": 1.8,
                    "11": 50,
                    "60": shield,
                    "61": hull,
                }
            },
            "active_buffs": active_buffs or [],
        }
    }


def _write_capture(capture_root: Path) -> None:
    battles = capture_root / "battles"
    battles.mkdir(parents=True)
    (battles / "battle-1.json").write_text(
        json.dumps(
            {
                "server_version": "test-version",
                "journal": {
                    "id": 123,
                    "initiator_fleet_data": _fleet(
                        "player-hull",
                        111,
                        ["player-armor", "player-shield", "player-weapon"],
                        hull=1000,
                        shield=2000,
                    ),
                    "target_fleet_data": _fleet(
                        "hostile-hull",
                        0,
                        ["hostile-armor", "hostile-shield", "hostile-weapon"],
                        hull=800,
                        shield=1200,
                    ),
                    "battle_log": [
                        -96,
                        -90,
                        111,
                        -98,
                        "player-weapon",
                        0,
                        1.0,
                        0.0,
                        1,
                        1,
                        25,
                        775,
                        75,
                        1125,
                        10,
                        5,
                        2,
                        3,
                        4,
                        6,
                        -99,
                        -89,
                        -97,
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_formation_capture(capture_root: Path) -> None:
    battles = capture_root / "battles"
    battles.mkdir(parents=True)
    primary_player = _fleet(
        "player-hull",
        111,
        ["player-armor", "player-shield", "player-weapon"],
        hull=1000,
        shield=2000,
    )["deployed_fleet"]
    secondary_player = _fleet(
        "player-hull",
        222,
        ["player-armor", "player-shield", "player-weapon"],
        hull=1500,
        shield=2500,
        level=7,
        tier=3,
    )["deployed_fleet"]
    hostile = _fleet(
        "hostile-hull",
        0,
        ["hostile-armor", "hostile-shield", "hostile-weapon"],
        hull=800,
        shield=1200,
    )["deployed_fleet"]
    (battles / "formation.json").write_text(
        json.dumps(
            {
                "server_version": "test-version",
                "journal": {
                    "id": 456,
                    "battle_type": 8,
                    "initiator_fleet_data": {
                        "battle_data_type": 2,
                        "deployed_fleet": primary_player,
                        "deployed_fleets": {"fleet-a": primary_player, "fleet-b": secondary_player},
                        "ship_ids": [111, 222],
                        "hull_ids": ["player-hull", "player-hull"],
                    },
                    "target_fleet_data": {
                        "battle_data_type": 0,
                        "deployed_fleet": hostile,
                        "deployed_fleets": {"hostile-fleet": hostile},
                        "ship_ids": [0],
                        "hull_ids": ["hostile-hull"],
                    },
                    "battle_log": [
                        -96,
                        -90,
                        -77,
                        -98,
                        "hostile-weapon",
                        222,
                        1.0,
                        0.0,
                        1,
                        0,
                        25,
                        775,
                        75,
                        1125,
                        10,
                        0,
                        0,
                        0,
                        0,
                        0,
                        -99,
                        -89,
                        -97,
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_target_player_capture(capture_root: Path) -> None:
    battles = capture_root / "battles"
    battles.mkdir(parents=True)
    hostile = _fleet(
        "hostile-hull",
        0,
        ["hostile-armor", "hostile-shield", "hostile-weapon"],
        hull=800,
        shield=1200,
    )
    player = _fleet(
        "player-hull",
        111,
        ["player-armor", "player-shield", "player-weapon"],
        hull=1000,
        shield=2000,
    )
    (battles / "target-player.json").write_text(
        json.dumps(
            {
                "server_version": "test-version",
                "journal": {
                    "id": 789,
                    "battle_type": 5,
                    "initiator_fleet_data": hostile,
                    "target_fleet_data": player,
                    "battle_log": [
                        -96,
                        -90,
                        0,
                        -98,
                        "hostile-weapon",
                        111,
                        1.0,
                        0.0,
                        1,
                        0,
                        25,
                        775,
                        75,
                        1125,
                        10,
                        0,
                        0,
                        0,
                        0,
                        0,
                        -99,
                        -89,
                        -97,
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


class ObservationExportTests(unittest.TestCase):
    def test_exports_one_observation_per_damage_attack(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            observations = export_observations(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(1, len(observations))
        row = observations[0]
        self.assertEqual("123", row["battle_id"])
        self.assertEqual("player", row["attacker_side"])
        self.assertEqual("hostile", row["defender_side"])
        self.assertEqual("player-weapon", row["weapon"]["id"])
        self.assertEqual(111, row["attacker"]["ship_id"])
        self.assertEqual(1, row["attacker"]["ship_level"])
        self.assertEqual(1, row["attacker"]["ship_tier"])
        self.assertEqual("hostile-hull", row["defender"]["hull_id"])
        self.assertEqual(1, row["defender"]["ship_level"])
        self.assertEqual(1, row["defender"]["ship_tier"])
        self.assertEqual({"shield": 75, "hull": 25}, row["observed"]["damage"])
        self.assertEqual(10, row["observed"]["mitigated_damage"])
        self.assertTrue(row["observed"]["critical"])
        self.assertAlmostEqual(10 / 110, row["observed"]["effective_mitigation"])
        self.assertEqual(
            {
                "observed_damage": 98,
                "raw_damage": 108,
                "mitigated_damage": 10,
                "effective_mitigation": 10 / 108,
                "excluded_isolytic_damage": 5,
                "excluded_mitigated_isolytic_damage": 2,
                "raw_damage_without_apex_barrier": 105,
                "included_mitigated_apex_barrier": 3,
                "post_apex_observed_damage": 95,
                "pre_apex_observed_damage": 98,
                "stage_order": "normal_then_isolytic_then_apex",
            },
            row["observed"]["normal_mitigation"],
        )
        self.assertEqual(
            {
                "base_damage": 108,
                "raw_damage": 7,
                "observed_damage": 5,
                "mitigated_damage": 2,
                "damage_multiplier": 7 / 108,
                "damage_multiplier_percent": (7 / 108) * 100,
                "effective_mitigation": 2 / 7,
                "inferred_base_damage": 108,
                "base_damage_gap": 0,
                "damage_modifier_code": "707",
                "defense_modifier_code": "808",
                "source": "derived_from_battle_log",
            },
            row["observed"]["isolytic_damage_model"],
        )

    def test_exports_deployed_fleet_attributes_and_ratings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            battle_path = capture_root / "battles" / "battle-1.json"
            battle = json.loads(battle_path.read_text(encoding="utf-8"))
            deployed = battle["journal"]["initiator_fleet_data"]["deployed_fleet"]
            deployed["attributes"] = {
                "-8": 856797.0,
                "-9": 448290.0,
                "-15": 5.0,
                "-16": 5.0,
                "-17": 5.0,
            }
            deployed["fleet_grade"] = 4
            deployed["offense_rating"] = 856797.0
            deployed["defense_rating"] = 448290.0
            deployed["health_rating"] = 44469486.0
            deployed["officer_rating"] = 198.0
            battle_path.write_text(json.dumps(battle), encoding="utf-8")

            observations = export_observations(decoded_static_dir=decoded, capture_root=capture_root)

        attacker = observations[0]["attacker"]
        self.assertEqual(
            {"-8": 856797.0, "-9": 448290.0, "-15": 5.0, "-16": 5.0, "-17": 5.0},
            attacker["captured_fleet_attributes"],
        )
        self.assertEqual(
            {
                "fleet_grade": 4,
                "offense_rating": 856797.0,
                "defense_rating": 448290.0,
                "health_rating": 44469486.0,
                "officer_rating": 198.0,
                "modifier_codes": {
                    "-7": 4,
                    "-8": 856797.0,
                    "-9": 448290.0,
                    "-10": 44469486.0,
                    "-13": 198.0,
                },
            },
            attacker["captured_fleet_ratings"],
        )

    def test_exports_observations_with_resolved_player_state_from_buff_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            buff_audit = root / "buff-audit.json"
            _write_decoded_static(decoded)
            _write_capture(capture_root)
            buff_audit.write_text(
                json.dumps(
                    {
                        "live_stat_residuals": [
                            {
                                "battle_id": "123",
                                "battle_side": "initiator",
                                "side": "player",
                                "ship_id": "111",
                                "stat_code": "6",
                                "captured": 90,
                                "static": 50,
                                "explained": 95,
                                "residual": -5,
                                "math_status": "operation_model_partial",
                                "explanation_components": {
                                    "selected_live_stat_model": "primary_operation_model",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            observations = export_observations(
                decoded_static_dir=decoded,
                capture_root=capture_root,
                buff_audit_path=buff_audit,
            )

        self.assertEqual({"6": 95}, observations[0]["attacker"]["resolved_stats"])
        self.assertEqual("buff_audit", observations[0]["attacker"]["resolved_stat_source"]["source"])
        self.assertNotIn("resolved_stats", observations[0]["defender"])

    def test_maps_officer_ability_payloads_from_battle_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_capture(capture_root)
            battle_path = capture_root / "battles" / "battle-1.json"
            battle = json.loads(battle_path.read_text(encoding="utf-8"))
            battle_log = battle["journal"]["battle_log"]
            end_attack = battle_log.index(-99)
            battle_log[end_attack:end_attack] = [
                -93,
                111,
                -91,
                "officer-1",
                "ability-1",
                0.25,
                -92,
                -91,
                "officer-2",
                "ability-2",
                3,
                -92,
                -94,
            ]
            battle_path.write_text(json.dumps(battle), encoding="utf-8")

            observations = export_observations(decoded_static_dir=decoded, capture_root=capture_root)

        activations = observations[0]["observed"]["officer_activations"]
        self.assertEqual(2, len(activations))
        self.assertEqual(["officer"], [effect for effect in observations[0]["observed"]["triggered_effects"] if effect == "officer"])
        self.assertEqual(
            {
                "firing_ship_id": "111",
                "officer_id": "officer-1",
                "ability_buff_id": "ability-1",
                "value": 0.25,
                "modifierCode": "707",
                "targetCode": 1,
                "triggerCode": 25,
                "op": "BUFFOPERATION_MULTIPLYADD",
                "conditionCodes": ["27"],
            },
            {
                key: activations[0][key]
                for key in (
                    "firing_ship_id",
                    "officer_id",
                    "ability_buff_id",
                    "value",
                    "modifierCode",
                    "targetCode",
                    "triggerCode",
                    "op",
                    "conditionCodes",
                )
            },
        )
        self.assertEqual("Officer One", activations[0]["officer"]["name"])
        self.assertEqual("officerAbilityId", activations[0]["officer"]["ability_field"])
        self.assertEqual("ability-1", activations[0]["ability"]["buff_id"])
        self.assertEqual([0.1, 0.2, 0.25], activations[0]["ability"]["rankedValues"])
        self.assertEqual("isolytic_damage", activations[0]["formula_effect"]["formula_stage"])
        self.assertEqual(["isolytic_damage_multiplier", "isolytic_raw_damage"], activations[0]["formula_effect"]["formula_inputs"])
        self.assertEqual("belowDecksAbilityId", activations[1]["officer"]["ability_field"])
        self.assertEqual("9", activations[1]["modifierCode"])
        self.assertEqual("critical_resolution", activations[1]["formula_effect"]["formula_stage"])

    def test_maps_forbidden_tech_payloads_from_battle_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            buff_audit = root / "buff-audit.json"
            _write_decoded_static(decoded)
            _write_capture(capture_root)
            (decoded / "ForbiddenTechSpecs.json").write_text(
                json.dumps(
                    {
                        "forbiddenTechSpecs": [
                            {
                                "id": "electromagnetic-lute",
                                "type": "FORBIDDENTECHTYPE_PVE",
                                "subtype": "FORBIDDENTECHSUBTYPE_HOSTILES",
                                "rarity": "RARITY_RARE",
                                "requiredSlotSpecId": "953301906",
                                "idRefs": {"locaId": "72103", "artId": "35"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (decoded / "ForbiddenTechBuffs.json").write_text(
                json.dumps(
                    {
                        "forbiddenTechBuffsSpecs": {
                            "apex-buff": {
                                "buffId": "apex-buff",
                                "modifierCode": "67001",
                                "targetCode": 1,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_ADD",
                                "conditionCodes": ["17", "246"],
                                "attributes": {"factionId": "hostile-faction"},
                                "rankedBuffValues": [900],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            battle_path = capture_root / "battles" / "battle-1.json"
            battle = json.loads(battle_path.read_text(encoding="utf-8"))
            battle["journal"]["initiator_fleet_data"]["deployed_fleet"]["stats"] = {"67001": 1}
            battle["journal"]["battle_log"][3:3] = [
                -84,
                111,
                -82,
                "electromagnetic-lute",
                "apex-buff",
                900,
                -81,
                -83,
                111,
            ]
            end_attack = battle["journal"]["battle_log"].index(-99)
            battle["journal"]["battle_log"][end_attack + 1 : end_attack + 1] = [
                111,
                -98,
                "player-weapon",
                0,
                1.0,
                0.0,
                1,
                0,
                25,
                775,
                75,
                1125,
                10,
                5,
                2,
                3,
                4,
                6,
                -99,
            ]
            battle_path.write_text(json.dumps(battle), encoding="utf-8")
            buff_audit.write_text(
                json.dumps(
                    {
                        "active_buffs": [
                            {
                                "battle_id": "123",
                                "side": "player",
                                "ship_ids": ["111"],
                                "modifierCode": "707",
                                "selected_ranked_value": 1,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            observations = export_observations(
                decoded_static_dir=decoded,
                capture_root=capture_root,
                buff_audit_path=buff_audit,
            )

        self.assertEqual(2, len(observations))
        activation = observations[0]["observed"]["forbidden_tech_activations"][0]
        self.assertEqual("electromagnetic-lute", activation["forbidden_tech_id"])
        self.assertEqual("apex-buff", activation["ability_buff_id"])
        self.assertEqual(900, activation["value"])
        self.assertEqual("67001", activation["modifierCode"])
        self.assertEqual("apex_barrier", activation["formula_effect"]["formula_stage"])
        self.assertEqual(900, observations[0]["attacker"]["resolved_modifiers"]["67001"])
        self.assertEqual(900, observations[1]["attacker"]["resolved_modifiers"]["67001"])
        self.assertEqual(900, observations[1]["observed"]["forbidden_tech_activations"][0]["value"])
        self.assertEqual(
            ["forbidden_tech"],
            [effect for effect in observations[0]["observed"]["triggered_effects"] if effect == "forbidden_tech"],
        )

    def test_applies_matching_static_ship_bonuses_and_tags_loot_bonuses(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            buff_audit = root / "buff-audit.json"
            _write_decoded_static(decoded)

            hull_specs = json.loads((decoded / "HullSpecs.json").read_text(encoding="utf-8"))
            hull_specs["hullSpecs"]["player-hull"]["shipBonuses"] = [
                "iso-bonus",
                "apex-bonus",
                "loot-bonus",
                "opponent-shots-bonus",
                "wrong-faction-bonus",
            ]
            (decoded / "HullSpecs.json").write_text(json.dumps(hull_specs), encoding="utf-8")
            (decoded / "ShipBonusBuffSpecs.json").write_text(
                json.dumps(
                    {
                        "shipBonusSpecs": {
                            "iso-bonus": {
                                "buffId": "iso-bonus",
                                "modifierCode": "707",
                                "targetCode": 1,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_ADD",
                                "rankedValues": [10, 20, 240],
                                "conditionCodes": ["17"],
                                "attributes": {"factionId": "wok"},
                            },
                            "apex-bonus": {
                                "buffId": "apex-bonus",
                                "modifierCode": "67001",
                                "targetCode": 1,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_ADD",
                                "rankedValues": [100, 200, 50000],
                                "conditionCodes": ["17"],
                                "attributes": {"factionId": "wok"},
                            },
                            "loot-bonus": {
                                "buffId": "loot-bonus",
                                "modifierCode": "78010",
                                "targetCode": 1,
                                "triggerCode": 24,
                                "op": "BUFFOPERATION_MULTIPLYADD",
                                "rankedValues": [1, 2, 3],
                            },
                            "opponent-shots-bonus": {
                                "buffId": "opponent-shots-bonus",
                                "modifierCode": "3",
                                "targetCode": 6,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_SUB",
                                "rankedValues": [1, 2, 9],
                                "conditionCodes": ["17"],
                                "attributes": {"factionId": "wok"},
                            },
                            "wrong-faction-bonus": {
                                "buffId": "wrong-faction-bonus",
                                "modifierCode": "707",
                                "targetCode": 1,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_ADD",
                                "rankedValues": [1, 2, 3],
                                "conditionCodes": ["17"],
                                "attributes": {"factionId": "other"},
                            },
                            "player-hull": {
                                "buffId": "player-hull",
                                "modifierCode": "2",
                                "targetCode": 1,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_MULTIPLYADD",
                                "rankedValues": [10, 20, 30],
                                "conditionCodes": ["17"],
                                "attributes": {"factionId": "wok"},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            _write_capture(capture_root)
            battle_path = capture_root / "battles" / "battle-1.json"
            battle = json.loads(battle_path.read_text(encoding="utf-8"))
            battle["journal"]["initiator_fleet_data"]["deployed_fleet"]["ship_levels"]["111"] = 3
            battle["journal"]["initiator_fleet_data"]["deployed_fleet"]["stats"] = {"707": 2.07}
            battle["journal"]["target_fleet_data"]["faction_id"] = "wok"
            battle_path.write_text(json.dumps(battle), encoding="utf-8")
            buff_audit.write_text(
                json.dumps(
                    {
                        "active_buffs": [
                            {
                                "battle_id": "123",
                                "side": "player",
                                "ship_ids": ["111"],
                                "modifierCode": "707",
                                "selected_ranked_value": 1.07,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            observations = export_observations(
                decoded_static_dir=decoded,
                capture_root=capture_root,
                buff_audit_path=buff_audit,
            )

        attacker = observations[0]["attacker"]
        self.assertAlmostEqual(4.47, attacker["resolved_modifiers"]["707"])
        self.assertEqual(30, attacker["resolved_modifiers"]["2"])
        self.assertEqual(50000, attacker["resolved_modifiers"]["67001"])
        self.assertEqual(
            {"apex-bonus", "iso-bonus", "player-hull"},
            {bonus["buff_id"] for bonus in attacker["static_ship_bonus_effects"]["applied_modifiers"]},
        )
        iso_bonus = next(
            bonus
            for bonus in attacker["static_ship_bonus_effects"]["applied_modifiers"]
            if bonus["buff_id"] == "iso-bonus"
        )
        self.assertEqual("isolytic_damage", iso_bonus["formula_effect"]["formula_stage"])
        self.assertEqual(["player-hull"], attacker["static_ship"]["hull"]["implicit_ship_bonus_ids"])
        self.assertEqual("ShipBonusBuffSpecs.hullId", attacker["static_ship"]["hull"]["ship_bonus_sources"]["player-hull"])
        self.assertEqual(
            "ShipBonusBuffSpecs.hullId",
            next(
                bonus
                for bonus in attacker["static_ship_bonus_effects"]["applied_modifiers"]
                if bonus["buff_id"] == "player-hull"
            )["source"],
        )
        self.assertEqual(
            ["loot-bonus"],
            [bonus["buff_id"] for bonus in attacker["static_ship_bonus_effects"]["loot_bonuses"]],
        )
        self.assertEqual(-9, observations[0]["defender"]["resolved_modifiers"]["3"])
        self.assertEqual(
            ["opponent-shots-bonus"],
            [bonus["buff_id"] for bonus in attacker["static_ship_bonus_effects"]["opponent_modifiers"]],
        )
        opponent_bonus = attacker["static_ship_bonus_effects"]["opponent_modifiers"][0]
        self.assertEqual("shot_count", opponent_bonus["formula_effect"]["formula_stage"])
        self.assertEqual(
            ["wrong-faction-bonus"],
            [
                bonus["buff_id"]
                for bonus in attacker["static_ship_bonus_effects"]["skipped_modifiers"]
                if bonus["application_status"] == "faction_mismatch"
            ],
        )
        self.assertEqual("resolved_buff_audit_static_ship_bonus", observations[0]["observed"]["isolytic_damage_model"]["source"])
        self.assertAlmostEqual(4.47, observations[0]["observed"]["isolytic_damage_model"]["damage_multiplier"])

    def test_exports_formation_armada_deployed_fleets_and_synthetic_hostile_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_formation_capture(capture_root)

            observations = export_observations(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(1, len(observations))
        row = observations[0]
        self.assertEqual("hostile", row["attacker_side"])
        self.assertEqual("player", row["defender_side"])
        self.assertEqual(8, row["battle_type"])
        self.assertEqual("ARMADA_MARAUDER", row["battle_type_name"])
        self.assertEqual(2, row["player_battle_data_type"])
        self.assertEqual("ARMADA", row["player_battle_data_type_name"])
        self.assertEqual(0, row["hostile_battle_data_type"])
        self.assertEqual("DEPLOYED_FLEET", row["hostile_battle_data_type_name"])
        self.assertEqual("hostile-weapon", row["weapon"]["id"])
        self.assertEqual(0, row["attacker"]["ship_id"])
        self.assertEqual(-77, row["attacker"]["battle_log_ship_id"])
        self.assertEqual("hostile-hull", row["attacker"]["hull_id"])
        self.assertEqual(222, row["defender"]["ship_id"])
        self.assertEqual(7, row["defender"]["ship_level"])
        self.assertEqual(3, row["defender"]["ship_tier"])

    def test_uses_single_deployed_fleet_for_top_level_fleet_ship_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_formation_capture(capture_root)
            battle_path = capture_root / "battles" / "formation.json"
            battle = json.loads(battle_path.read_text(encoding="utf-8"))
            battle["journal"]["target_fleet_data"]["ship_ids"] = [1]
            battle["journal"]["battle_log"][2] = 1
            battle_path.write_text(json.dumps(battle), encoding="utf-8")

            observations = export_observations(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(1, len(observations))
        row = observations[0]
        self.assertEqual("hostile", row["attacker_side"])
        self.assertEqual(0, row["attacker"]["ship_id"])
        self.assertEqual(1, row["attacker"]["battle_log_ship_id"])
        self.assertEqual("hostile-hull", row["attacker"]["hull_id"])

    def test_detects_player_on_target_side_when_initiator_is_hostile(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_target_player_capture(capture_root)

            observations = export_observations(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(1, len(observations))
        row = observations[0]
        self.assertEqual(5, row["battle_type"])
        self.assertEqual("ACTIVE_MARAUDER_MARAUDER_INITIATOR", row["battle_type_name"])
        self.assertEqual("target", row["player_battle_side"])
        self.assertEqual("initiator", row["hostile_battle_side"])
        self.assertEqual("hostile", row["attacker_side"])
        self.assertEqual("player", row["defender_side"])
        self.assertEqual("hostile-weapon", row["weapon"]["id"])
        self.assertEqual(0, row["attacker"]["ship_id"])
        self.assertEqual("hostile-hull", row["attacker"]["hull_id"])
        self.assertEqual(111, row["defender"]["ship_id"])
        self.assertEqual("player-hull", row["defender"]["hull_id"])

    def test_prefers_active_buff_side_when_hostile_has_nonzero_ship_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_target_player_capture(capture_root)
            battle_path = capture_root / "battles" / "target-player.json"
            battle = json.loads(battle_path.read_text(encoding="utf-8"))
            battle["journal"]["initiator_id"] = "npc_test"
            battle["journal"]["target_id"] = "player-test"
            battle["journal"]["initiator_fleet_data"] = _fleet(
                "hostile-hull",
                222,
                ["hostile-armor", "hostile-shield", "hostile-weapon"],
                hull=800,
                shield=1200,
            )
            battle["journal"]["target_fleet_data"]["deployed_fleet"]["active_buffs"] = [{"buff_id": "player-buff"}]
            battle["journal"]["battle_log"][2] = 222
            battle_path.write_text(json.dumps(battle), encoding="utf-8")

            observations = export_observations(decoded_static_dir=decoded, capture_root=capture_root)

        row = observations[0]
        self.assertEqual("target", row["player_battle_side"])
        self.assertEqual("initiator", row["hostile_battle_side"])
        self.assertEqual("npc_test", row["hostile_id"])
        self.assertEqual("npc", row["hostile_id_prefix"])
        self.assertEqual("hostile", row["attacker_side"])
        self.assertEqual(222, row["attacker"]["ship_id"])
        self.assertEqual("player", row["defender_side"])
        self.assertEqual(111, row["defender"]["ship_id"])

    def test_cli_observations_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            out_path = root / "observations.jsonl"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "observations",
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
            rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(rows))
            self.assertEqual("player-weapon", rows[0]["weapon"]["id"])


if __name__ == "__main__":
    unittest.main()
