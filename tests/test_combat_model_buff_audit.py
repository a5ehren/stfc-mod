from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model import buff_audit
from scripts.lib.combat_model.buff_audit import build_static_buff_index, generate_buff_audit
from scripts.lib.combat_model.modifier_types import load_client_modifier_types
from scripts.lib.combat_model.simulator_state import build_resolved_player_state_index


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _buff_spec(
    buff_id: int,
    *,
    modifier_code: int = 6,
    ranked_values: list[float] | None = None,
    operation: str = "BUFFOPERATION_ADD",
) -> dict[str, object]:
    return {
        "buffId": str(buff_id),
        "modifierCode": str(modifier_code),
        "targetCode": 1,
        "triggerCode": 2,
        "op": operation,
        "rankedValues": ranked_values or [1.0, 2.0, 3.0],
        "conditionCodes": ["28"],
        "attributes": {"grade": 3},
    }


def _write_decoded_static(decoded: Path) -> None:
    decoded.mkdir()
    (decoded / "OfficerAbilityBuffSpecs.json").write_text(
        json.dumps({"officerAbilitySpecs": {"100": _buff_spec(100), "200": _buff_spec(200, modifier_code=7)}}),
        encoding="utf-8",
    )
    (decoded / "ForbiddenTechBuffs.json").write_text(
        json.dumps({"forbiddenTechBuffsSpecs": {"100": _buff_spec(100, modifier_code=8)}}),
        encoding="utf-8",
    )
    (decoded / "BuffTargetSpecs.json").write_text(
        json.dumps({"buffTargetSpecs": {"target-1": {"id": "target-1", "code": 1, "idStr": "targ_self_ship"}}}),
        encoding="utf-8",
    )
    (decoded / "BuffTriggerSpecs.json").write_text(
        json.dumps(
            {
                "buffTriggerSpecs": {
                    "trigger-2": {
                        "id": "trigger-2",
                        "code": 2,
                        "idStr": "trig_self_launch",
                        "schema": "BUFFSCHEMATYPE_FLEETDEPLOYMENTSCHEMA",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "OfficerCoreStatSpecs.json").write_text(
        json.dumps({"officerCoreStatSpecs": {"1": {"level": 1, "stats": {"1": 10, "3": 20}}}}),
        encoding="utf-8",
    )
    (decoded / "OfficerCoreStatThresholdsSpecs.json").write_text(
        json.dumps({"officerCoreStatThresholds": {"1": {"thresholds": [{"statTotal": 10, "statBonus": 1.0}]}}}),
        encoding="utf-8",
    )
    (decoded / "HullSpecs.json").write_text(
        json.dumps(
            {
                "hullSpecs": {
                    "hull-1": {
                        "id": "hull-1",
                        "idStr": "Hull_Test",
                        "name": "Test Hull",
                        "type": "HULLTYPE_EXPLORER",
                        "componentDefaults": ["armor-1", "shield-1", "impulse-1", "weapon-1"],
                        "coreStatModifiers": [
                            {"type": "OFFICERCORESTATTYPE_ATTACK", "threshold": 10, "bonus": 5},
                            {"type": "OFFICERCORESTATTYPE_DEFENSE", "threshold": 10, "bonus": 5},
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "OfficerSpecs.json").write_text(
        json.dumps(
            {
                "officerSpecs": {
                    "777": {
                        "id": "777",
                        "attack": 1,
                        "defense": 1,
                        "health": 1,
                        "rarity": "RARITY_RARE",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (decoded / "ComponentSpecs.json").write_text(
        json.dumps(
            {
                "componentSpecs": {
                    "armor-1": {"id": "armor-1", "armorSpec": {"hp": 1000, "plating": 30}},
                    "shield-1": {
                        "id": "shield-1",
                        "shieldSpec": {"hp": 2000, "absorption": 40, "mitigation": 0.8},
                    },
                    "impulse-1": {"id": "impulse-1", "impulseSpec": {"dodge": 50}},
                    "weapon-1": {
                        "id": "weapon-1",
                        "weaponSpec": {
                            "attack": {
                                "accuracy": 60,
                                "penetration": 70,
                                "modulation": 80,
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


def _fleet() -> dict[str, object]:
    return {
        "bridge_officers": [{"id": 777, "level": 1, "rank": 1}],
        "deployed_fleet": {
            "fleet_id": 10,
            "hull_ids": ["hull-1"],
            "ship_ids": [111],
            "attributes": {"-15": 5, "-16": 5},
            "ship_components": {"111": ["armor-1", "shield-1", "impulse-1", "weapon-1"]},
            "ship_levels": {"111": 51},
            "ship_tiers": {"111": 4},
            "ship_stats": {
                "111": {
                    "-3": 45,
                    "-2": 40,
                    "6": 90,
                    "7": 75,
                    "8": 80,
                    "9": 0.1,
                    "10": 1.5,
                    "11": 55,
                    "60": 2100,
                    "61": 1100,
                }
            },
            "stats": {"6": 1.5, "7": 2.0},
            "active_buffs": [
                {"buff_id": 100, "activator_id": 501, "ranks": [2], "expiry_time": None},
                {"buff_id": 200, "activator_id": 502, "ranks": [], "expiry_time": "2026-01-01T00:00:00"},
                {"buff_id": 999, "activator_id": 503, "ranks": [1], "expiry_time": None},
                {"buff_id": 888, "activator_id": 111, "ranks": [1, 2, 3], "expiry_time": None},
            ],
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
                    "initiator_fleet_data": _fleet(),
                    "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                },
            }
        ),
        encoding="utf-8",
    )


class BuffAuditTests(unittest.TestCase):
    def test_modifier_code_summary_resolves_symbol_candidates_once_per_code(self) -> None:
        calls: list[str] = []
        original = buff_audit.symbol_candidates_for

        def fake_symbol_candidates_for(code, numeric_symbols):
            calls.append(str(code))
            return [{"symbolName": f"Code{code}"}]

        try:
            buff_audit.symbol_candidates_for = fake_symbol_candidates_for
            rows = buff_audit._summarize_modifier_codes(
                active_buffs=[
                    {
                        "modifierCode": "6",
                        "modifierCodes": ["6"],
                        "source_table": "ResearchSpecs",
                        "source_type": "research",
                        "buffOperation": "BUFFOPERATION_ADD",
                        "targetSpec": {"idStr": "targ_self_ship"},
                        "triggerSpec": {"idStr": "trig_self_launch"},
                        "buff_id": "100",
                        "battle_id": "battle-1",
                    }
                    for _ in range(10)
                ],
                aggregate_modifier_rows=[
                    {
                        "modifierCode": "6",
                        "captured_source": "stats",
                        "captured_aggregate": 1.5,
                        "battle_id": "battle-1",
                    }
                    for _ in range(5)
                ],
                live_stat_residuals=[
                    {
                        "stat_code": "6",
                        "static_field": "weapon_accuracy_max",
                        "math_status": "operation_model_partial",
                        "battle_id": "battle-1",
                    }
                    for _ in range(5)
                ],
                modifier_types={},
                numeric_symbols={"values": {}},
            )
        finally:
            buff_audit.symbol_candidates_for = original

        self.assertEqual(["6"], calls)
        self.assertEqual([{"symbolName": "Code6"}], rows[0]["candidateSymbols"])
        self.assertEqual(10, rows[0]["active_buff_count"])
        self.assertEqual(5, rows[0]["aggregate_row_count"])
        self.assertEqual(5, rows[0]["live_stat_row_count"])

    def test_modifier_type_loader_falls_back_to_newest_artifact_for_server_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dump_dir = root / "dump" / "1.000.50000"
            dump_dir.mkdir(parents=True)
            (dump_dir / "dump.cs").write_text("// intentionally lacks ClientModifierType constants\n", encoding="utf-8")
            (dump_dir / "modifier-type-map.json").write_text(
                json.dumps(
                    {
                        "codes": {
                            "78010": {
                                "code": "78010",
                                "enum_name": "ClientModifierType.ModWokAugmentAllLootRewards",
                                "original_name": "MOD_WOK_AUGMENT_ALL_LOOT_REWARDS",
                                "source": "artifact",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            modifier_types = load_client_modifier_types(
                project_root=root,
                game_version="server-package-version-that-is-not-a-dump-dir",
            )

        self.assertEqual("ClientModifierType.ModWokAugmentAllLootRewards", modifier_types["78010"]["enum_name"])

    def test_active_row_match_index_groups_static_generated_and_unresolved_rows(self) -> None:
        static_row = {
            "buff_id": "100",
            "resolution_kind": "static",
            "source_table": "ResearchSpecs",
            "source_type": "research",
            "source_context": {"id": "research-1"},
            "modifierCode": "6",
            "modifierName": "ClientModifierType.ModAccuracy",
            "modifierOriginalName": "MOD_ACCURACY",
            "modifierType": {"code": "6"},
            "buffOperation": "BUFFOPERATION_ADD",
            "targetCode": 1,
            "targetSpec": {"idStr": "targ_self_ship"},
            "triggerCode": 2,
            "triggerSpec": {"idStr": "trig_self_launch"},
            "conditionCodes": [],
            "selected_rank": 1,
            "selected_ranked_value": 5,
            "selected_rank_status": "selected",
            "zero_based_ranked_value": 5,
            "zero_based_rank_status": "selected",
            "legacy_one_based_ranked_value": 4,
            "legacy_one_based_rank_status": "selected",
        }
        generated_row = {
            "buff_id": "888",
            "resolution_kind": "generated",
            "source_table": "Generated",
            "source_type": "generated_core_stat_modifier",
            "selected_rank": None,
            "selected_rank_status": "generated",
            "generated_explanation": {
                "confidence": "test",
                "core_stat_modifiers": [
                    {"fleet_modifierCode": "-15", "core_stat": "ATTACK"},
                    {"fleet_modifierCode": "11"},
                ],
            },
        }
        unresolved_row = {"buff_id": "999", "resolution_kind": "unresolved"}

        index = buff_audit._active_row_match_index([static_row, generated_row, unresolved_row])

        self.assertEqual(["100"], [row["buff_id"] for row in index["static_by_code"]["6"]])
        self.assertEqual(["888"], [row["buff_id"] for row in index["generated_by_code"]["-15"]])
        self.assertEqual(["888"], [row["buff_id"] for row in index["generated_by_code"]["6"]])
        self.assertEqual(["888"], [row["buff_id"] for row in index["generated_by_code"]["11"]])
        self.assertEqual([{"fleet_modifierCode": "-15", "core_stat": "ATTACK"}],
                         index["generated_by_code"]["6"][0]["core_stat_modifiers"])
        self.assertEqual([unresolved_row], index["unresolved"])

    def test_static_buff_index_uses_explicit_source_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            _write_decoded_static(decoded)

            index, sources = build_static_buff_index(decoded)

        self.assertEqual("OfficerAbilityBuffSpecs", index["100"]["source_table"])
        self.assertEqual("officer_ability", index["100"]["source_type"])
        duplicate_tables = [source["source_table"] for source in index["100"]["duplicate_sources"]]
        self.assertEqual(["ForbiddenTechBuffs"], duplicate_tables)
        self.assertEqual("found", sources["OfficerAbilityBuffSpecs"]["status"])
        self.assertEqual("missing_source_table", sources["ResearchSpecs"]["status"])
        self.assertEqual("found", sources["BuffTargetSpecs"]["status"])
        self.assertEqual("found", sources["BuffTriggerSpecs"]["status"])
        self.assertEqual("found", sources["OfficerCoreStatSpecs"]["status"])
        self.assertEqual("supporting_static", sources["OfficerCoreStatSpecs"]["source_type"])
        self.assertEqual("missing_source_table", sources["BaseShipTierSpecs"]["status"])
        self.assertEqual("missing_source_table", sources["ShipTierSpecs"]["status"])
        self.assertEqual("missing_source_table", sources["LocalizationCacheData"]["status"])

    def test_resolves_deployed_player_active_buffs_and_reports_residuals(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(1, report["summary"]["battle_count"])
        self.assertEqual(1, report["summary"]["player_fleet_count"])
        self.assertEqual(4, report["summary"]["active_buff_count"])
        self.assertEqual(3, report["summary"]["resolved_active_buff_count"])
        self.assertEqual(2, report["summary"]["static_resolved_active_buff_count"])
        self.assertEqual(1, report["summary"]["generated_explained_active_buff_count"])
        self.assertEqual(1, report["summary"]["unresolved_active_buff_count"])
        self.assertEqual(10, report["live_stat_error_summary"]["live_stat_row_count"])
        self.assertEqual(10, report["live_stat_error_summary"]["residual_row_count"])
        self.assertEqual({"primary_operation_model": 10}, report["live_stat_error_summary"]["selected_live_stat_models"])

        resolved = {row["buff_id"]: row for row in report["active_buffs"] if row["resolved"]}
        self.assertEqual(3.0, resolved["100"]["selected_ranked_value"])
        self.assertEqual(2.0, resolved["100"]["legacy_one_based_ranked_value"])
        self.assertEqual("selected", resolved["100"]["selected_rank_status"])
        self.assertEqual("ClientModifierType.ModAccuracy", resolved["100"]["modifierName"])
        self.assertEqual("MOD_ACCURACY", resolved["100"]["modifierOriginalName"])
        self.assertEqual("targ_self_ship", resolved["100"]["targetSpec"]["idStr"])
        self.assertEqual("trig_self_launch", resolved["100"]["triggerSpec"]["idStr"])
        self.assertEqual("missing_rank", resolved["200"]["selected_rank_status"])
        generated = resolved["888"]
        self.assertEqual("generated", generated["resolution_kind"])
        self.assertEqual("HullSpecs", generated["source_table"])
        self.assertEqual("generated_hull_core_stat_modifier", generated["source_type"])
        self.assertEqual(
            ["OFFICERCORESTATTYPE_ATTACK", "OFFICERCORESTATTYPE_DEFENSE"],
            [modifier["core_stat_type"] for modifier in generated["generated_explanation"]["core_stat_modifiers"]],
        )
        self.assertEqual(
            ["-15", "-16"],
            [modifier["fleet_modifierCode"] for modifier in generated["generated_explanation"]["core_stat_modifiers"]],
        )
        self.assertEqual(
            ["ClientModifierType.FleetOfficerBonusAttack", "ClientModifierType.FleetOfficerBonusDefense"],
            [modifier["enum_name"] for modifier in generated["modifierTypes"]],
        )
        self.assertEqual(20, generated["generated_explanation"]["estimated_officer_core_totals"]["ATTACK"])
        unresolved_by_id = {row["buff_id"]: row for row in report["unresolved_buffs"]}
        self.assertEqual("unknown_static_source", unresolved_by_id["999"]["probable_source_type"])
        self.assertNotIn("888", unresolved_by_id)
        self.assertEqual("888", report["generated_buffs"][0]["buff_id"])

        accuracy = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "6")
        self.assertEqual("player", accuracy["side"])
        self.assertEqual("hull-1", accuracy["hull_id"])
        self.assertEqual("HULLTYPE_EXPLORER", accuracy["hull_type"])
        self.assertEqual("ClientModifierType.ModAccuracy", accuracy["stat_modifierName"])
        self.assertEqual("MOD_ACCURACY", accuracy["stat_modifierOriginalName"])
        self.assertEqual(60, accuracy["static"])
        self.assertEqual(90, accuracy["captured"])
        self.assertEqual(30, accuracy["static_residual"])
        self.assertEqual(63, accuracy["explained"])
        self.assertEqual(27, accuracy["residual"])
        self.assertEqual("operation_model_partial", accuracy["math_status"])
        self.assertEqual(87, accuracy["explanation_components"]["implied_static_base"])
        self.assertEqual(27, accuracy["explanation_components"]["implied_static_base_delta"])
        self.assertEqual(["100"], [buff["buff_id"] for buff in accuracy["matching_resolved_buffs"]])
        self.assertEqual(["100"], accuracy["explanation_components"]["conditional_static_buff_ids"])
        self.assertEqual([], accuracy["explanation_components"]["unconditional_static_buff_ids"])
        self.assertEqual(3, accuracy["explanation_components"]["conditional_static_flat_delta"])
        self.assertEqual(0, accuracy["explanation_components"]["conditional_static_multiply_percent_total"])
        self.assertEqual(60, accuracy["explanation_components"]["without_conditional_static_buffs_explained"])
        self.assertEqual(30, accuracy["explanation_components"]["without_conditional_static_buffs_residual"])
        self.assertEqual("applied_conditional_buffs_improve", accuracy["explanation_components"]["conditional_effect"])
        self.assertEqual([1], [buff["targetCode"] for buff in accuracy["matching_resolved_buffs"]])
        self.assertEqual(["6"], [buff["modifierCode"] for buff in accuracy["matching_resolved_buffs"]])
        modifier_code_6 = next(row for row in report["modifier_codes"] if row["modifierCode"] == "6")
        self.assertEqual("ClientModifierType.ModAccuracy", modifier_code_6["modifierName"])
        self.assertIn("weapon_accuracy_max", modifier_code_6["live_static_fields"])
        self.assertIn("OfficerAbilityBuffSpecs", modifier_code_6["source_tables"])
        self.assertEqual([2], [buff["triggerCode"] for buff in accuracy["matching_resolved_buffs"]])
        self.assertEqual(["targ_self_ship"], [buff["targetSpec"]["idStr"] for buff in accuracy["matching_resolved_buffs"]])
        self.assertEqual(
            ["trig_self_launch"], [buff["triggerSpec"]["idStr"] for buff in accuracy["matching_resolved_buffs"]]
        )
        self.assertEqual([["28"]], [buff["conditionCodes"] for buff in accuracy["matching_resolved_buffs"]])
        self.assertEqual(["888"], [buff["buff_id"] for buff in accuracy["matching_generated_buffs"]])
        self.assertEqual("found", accuracy["static_source"]["status"])
        self.assertEqual("weapon-1", accuracy["static_source"]["component_id"])
        self.assertEqual("weaponSpec.attack.accuracy", accuracy["static_source"]["field_path"])
        self.assertEqual("missing_source_table", accuracy["tier_static_sources"]["ShipTierSpecs"]["status"])
        self.assertIsNone(accuracy["tier_stat_modifier"])
        self.assertEqual(
            {
                "conditionCode": "28",
                "conditionName": None,
                "count": 2,
                "sample_buff_ids": ["100", "200"],
                "source_types": ["officer_ability"],
                "modifierCodes": ["6", "7"],
                "target_idStrs": ["targ_self_ship"],
                "trigger_idStrs": ["trig_self_launch"],
            },
            report["condition_codes"][0],
        )
        self.assertEqual(
            {
                "conditional_effect": "applied_conditional_buffs_improve",
                "count": 1,
                "hull_type": "HULLTYPE_EXPLORER",
                "stat_code": "6",
                "static_field": "weapon_accuracy_max",
                "math_statuses": ["operation_model_partial"],
                "battle_sides": ["initiator"],
                "sample_battle_ids": ["123"],
                "sample_ship_ids": ["111"],
                "mean_abs_residual": 27,
                "mean_abs_without_conditional_residual": 30,
                "conditional_buff_ids": ["100"],
                "unconditional_buff_ids": [],
                "conditional_buffs": [
                    {
                        "buff_id": "100",
                        "modifierCode": "6",
                        "modifierName": "ClientModifierType.ModAccuracy",
                        "modifierOriginalName": "MOD_ACCURACY",
                        "source_table": "OfficerAbilityBuffSpecs",
                        "source_type": "officer_ability",
                        "buffOperation": "BUFFOPERATION_ADD",
                        "conditionCodes": ["28"],
                        "selected_rank": 2,
                        "selected_ranked_value": 3,
                        "target_idStr": "targ_self_ship",
                        "trigger_idStr": "trig_self_launch",
                        "source_context": None,
                    }
                ],
                "matching_static_buffs": [
                    {
                        "buff_id": "100",
                        "modifierCode": "6",
                        "modifierName": "ClientModifierType.ModAccuracy",
                        "modifierOriginalName": "MOD_ACCURACY",
                        "source_table": "OfficerAbilityBuffSpecs",
                        "source_type": "officer_ability",
                        "buffOperation": "BUFFOPERATION_ADD",
                        "conditionCodes": ["28"],
                        "selected_rank": 2,
                        "selected_ranked_value": 3,
                        "target_idStr": "targ_self_ship",
                        "trigger_idStr": "trig_self_launch",
                        "source_context": None,
                    }
                ],
            },
            report["conditional_effects"][0],
        )

        aggregate = next(row for row in report["aggregate_modifier_rows"] if row["modifierCode"] == "6")
        self.assertEqual(1.5, aggregate["captured_aggregate"])
        self.assertEqual("aggregate_not_reconstructed", aggregate["math_status"])
        self.assertEqual(["100"], [buff["buff_id"] for buff in aggregate["matching_resolved_buffs"]])

    def test_audits_each_player_deployed_fleet_in_formation_armadas(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            first_fleet = _fleet()
            first_deployed = first_fleet["deployed_fleet"]
            second_deployed = json.loads(json.dumps(first_deployed))
            second_deployed["fleet_id"] = 20
            second_deployed["ship_ids"] = [222]
            for key in ("ship_components", "ship_levels", "ship_tiers", "ship_stats"):
                second_deployed[key]["222"] = second_deployed[key].pop("111")
            second_deployed["active_buffs"] = [{"buff_id": 200, "activator_id": 602, "ranks": [1], "expiry_time": None}]

            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "formation.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 456,
                            "battle_type": 8,
                            "initiator_fleet_data": {
                                **first_fleet,
                                "battle_data_type": 2,
                                "deployed_fleets": {"10": first_deployed, "20": second_deployed},
                                "ship_ids": [111, 222],
                                "hull_ids": ["hull-1", "hull-1"],
                            },
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(2, report["summary"]["player_fleet_count"])
        self.assertEqual(5, report["summary"]["active_buff_count"])
        active_ship_ids = {tuple(row["ship_ids"]) for row in report["active_buffs"]}
        self.assertEqual({("111",), ("222",)}, active_ship_ids)
        residual_ship_ids = {row["ship_id"] for row in report["live_stat_residuals"]}
        self.assertEqual({"111", "222"}, residual_ship_ids)

    def test_live_stat_explanation_applies_percentage_operations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            officer_buffs_path = decoded / "OfficerAbilityBuffSpecs.json"
            officer_buffs = json.loads(officer_buffs_path.read_text(encoding="utf-8"))
            officer_buffs["officerAbilitySpecs"]["300"] = _buff_spec(
                300,
                modifier_code=8,
                ranked_values=[0.5],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs["officerAbilitySpecs"]["400"] = _buff_spec(
                400,
                modifier_code=8,
                ranked_values=[0.25],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs_path.write_text(json.dumps(officer_buffs), encoding="utf-8")

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [
                {"buff_id": 300, "activator_id": 501, "ranks": [0], "expiry_time": None},
                {"buff_id": 400, "activator_id": 502, "ranks": [0], "expiry_time": None},
            ]
            deployed["ship_stats"]["111"]["8"] = 140
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        modulation = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "8")
        self.assertEqual(80, modulation["static"])
        self.assertEqual(140, modulation["captured"])
        self.assertEqual(60, modulation["static_residual"])
        self.assertEqual(140, modulation["explained"])
        self.assertEqual(0, modulation["residual"])
        self.assertEqual("operation_model_closed", modulation["math_status"])
        self.assertEqual(0.75, modulation["explanation_components"]["multiply_percent_total"])
        self.assertEqual(80, modulation["explanation_components"]["implied_static_base"])
        self.assertEqual(0, modulation["explanation_components"]["implied_static_base_delta"])
        self.assertEqual(["300", "400"], modulation["explanation_components"]["applied_static_buff_ids"])
        self.assertEqual(
            "static_buff_subset_no_residual_change",
            modulation["explanation_components"]["best_static_buff_subset_effect"],
        )
        self.assertEqual([], report["static_buff_subset_effects"])

    def test_live_stat_explanation_reports_best_static_buff_subset_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            officer_buffs_path = decoded / "OfficerAbilityBuffSpecs.json"
            officer_buffs = json.loads(officer_buffs_path.read_text(encoding="utf-8"))
            officer_buffs["officerAbilitySpecs"]["300"] = _buff_spec(
                300,
                modifier_code=8,
                ranked_values=[1.0],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs["officerAbilitySpecs"]["400"] = _buff_spec(
                400,
                modifier_code=8,
                ranked_values=[0.5],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs_path.write_text(json.dumps(officer_buffs), encoding="utf-8")

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [
                {"buff_id": 300, "activator_id": 501, "ranks": [0], "expiry_time": None},
                {"buff_id": 400, "activator_id": 502, "ranks": [0], "expiry_time": None},
            ]
            deployed["ship_stats"]["111"]["8"] = 160
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        modulation = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "8")
        self.assertEqual(160, modulation["explained"])
        self.assertEqual(0, modulation["residual"])
        self.assertEqual("static_subset_model_closed", modulation["math_status"])
        self.assertEqual(200, modulation["explanation_components"]["primary_operation_model_explained"])
        self.assertEqual(-40, modulation["explanation_components"]["primary_operation_model_residual"])
        self.assertEqual("static_subset_model", modulation["explanation_components"]["selected_live_stat_model"])
        self.assertEqual(
            "best_static_buff_subset_closes",
            modulation["explanation_components"]["selected_live_stat_effect"],
        )
        self.assertEqual(
            "best_static_buff_subset_closes",
            modulation["explanation_components"]["best_static_buff_subset_effect"],
        )
        self.assertEqual(160, modulation["explanation_components"]["best_static_buff_subset_explained"])
        self.assertEqual(0, modulation["explanation_components"]["best_static_buff_subset_residual"])
        self.assertEqual(["300"], modulation["explanation_components"]["best_static_buff_subset_buff_ids"])
        self.assertEqual(["400"], modulation["explanation_components"]["best_static_buff_subset_excluded_buff_ids"])
        self.assertEqual(
            {
                "best_static_buff_subset_effect": "best_static_buff_subset_closes",
                "count": 1,
                "hull_type": "HULLTYPE_EXPLORER",
                "stat_code": "8",
                "static_field": "weapon_modulation_max",
                "math_statuses": ["static_subset_model_closed"],
                "battle_sides": ["initiator"],
                "sample_battle_ids": ["123"],
                "sample_ship_ids": ["111"],
                "mean_abs_residual": 0,
                "mean_abs_primary_operation_model_residual": 40,
                "mean_abs_best_static_buff_subset_residual": 0,
                "best_static_buff_subset_buff_ids": ["300"],
                "best_static_buff_subset_excluded_buff_ids": ["400"],
            },
            report["static_buff_subset_effects"][0],
        )

    def test_live_stat_explanation_promotes_related_modifier_buffs_when_they_close(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            officer_buffs_path = decoded / "OfficerAbilityBuffSpecs.json"
            officer_buffs = json.loads(officer_buffs_path.read_text(encoding="utf-8"))
            officer_buffs["officerAbilitySpecs"]["300"] = _buff_spec(
                300,
                modifier_code=11,
                ranked_values=[1.0],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs["officerAbilitySpecs"]["400"] = _buff_spec(
                400,
                modifier_code=73,
                ranked_values=[2.0],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs_path.write_text(json.dumps(officer_buffs), encoding="utf-8")

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [
                {"buff_id": 300, "activator_id": 501, "ranks": [0], "expiry_time": None},
                {"buff_id": 400, "activator_id": 502, "ranks": [0], "expiry_time": None},
            ]
            deployed["ship_stats"]["111"]["11"] = 200
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        dodge = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "11")
        self.assertEqual(200, dodge["explained"])
        self.assertEqual(0, dodge["residual"])
        self.assertEqual("related_modifier_model_closed", dodge["math_status"])
        self.assertEqual(["300"], dodge["explanation_components"]["applied_static_buff_ids"])
        self.assertEqual(["400"], [buff["buff_id"] for buff in dodge["matching_related_buffs"]])
        self.assertEqual(100, dodge["explanation_components"]["primary_operation_model_explained"])
        self.assertEqual(100, dodge["explanation_components"]["primary_operation_model_residual"])
        self.assertEqual("related_modifier_model", dodge["explanation_components"]["selected_live_stat_model"])
        self.assertEqual(
            "related_modifier_buffs_close",
            dodge["explanation_components"]["selected_live_stat_effect"],
        )
        self.assertEqual(["73"], dodge["explanation_components"]["related_modifier_codes"])
        self.assertEqual(["400"], dodge["explanation_components"]["related_modifier_static_buff_ids"])
        self.assertEqual(2.0, dodge["explanation_components"]["related_modifier_multiply_percent_total"])
        self.assertEqual(200, dodge["explanation_components"]["with_related_modifier_buffs_explained"])
        self.assertEqual(0, dodge["explanation_components"]["with_related_modifier_buffs_residual"])
        self.assertEqual(
            "related_modifier_buffs_close",
            dodge["explanation_components"]["related_modifier_effect"],
        )
        self.assertEqual(
            {
                "related_modifier_effect": "related_modifier_buffs_close",
                "count": 1,
                "hull_type": "HULLTYPE_EXPLORER",
                "stat_code": "11",
                "static_field": "dodge",
                "math_statuses": ["related_modifier_model_closed"],
                "battle_sides": ["initiator"],
                "sample_battle_ids": ["123"],
                "sample_ship_ids": ["111"],
                "mean_abs_residual": 0,
                "mean_abs_primary_operation_model_residual": 100,
                "mean_abs_with_related_modifier_residual": 0,
                "related_modifier_codes": ["73"],
                "related_modifier_static_buff_ids": ["400"],
            },
            report["related_modifier_effects"][0],
        )

    def test_live_stat_explanation_treats_ship_armor_as_related_to_destroyer_dodge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            officer_buffs_path = decoded / "OfficerAbilityBuffSpecs.json"
            officer_buffs = json.loads(officer_buffs_path.read_text(encoding="utf-8"))
            officer_buffs["officerAbilitySpecs"]["300"] = _buff_spec(
                300,
                modifier_code=11,
                ranked_values=[1.0],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs["officerAbilitySpecs"]["400"] = _buff_spec(
                400,
                modifier_code=12,
                ranked_values=[2.0],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs_path.write_text(json.dumps(officer_buffs), encoding="utf-8")

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["hull_ids"] = ["destroyer-hull"]
            deployed["ship_components"] = {"111": ["armor-1", "shield-1", "impulse-1", "weapon-1"]}
            hull_specs_path = decoded / "HullSpecs.json"
            hull_specs = json.loads(hull_specs_path.read_text(encoding="utf-8"))
            hull_specs["hullSpecs"]["destroyer-hull"] = {
                **hull_specs["hullSpecs"]["hull-1"],
                "id": "destroyer-hull",
                "type": "HULLTYPE_DESTROYER",
            }
            hull_specs_path.write_text(json.dumps(hull_specs), encoding="utf-8")
            deployed["active_buffs"] = [
                {"buff_id": 300, "activator_id": 501, "ranks": [0], "expiry_time": None},
                {"buff_id": 400, "activator_id": 502, "ranks": [0], "expiry_time": None},
            ]
            deployed["ship_stats"]["111"]["11"] = 200
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        dodge = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "11")
        self.assertEqual("HULLTYPE_DESTROYER", dodge["hull_type"])
        self.assertEqual(200, dodge["explained"])
        self.assertEqual(0, dodge["residual"])
        self.assertEqual("related_modifier_model_closed", dodge["math_status"])
        self.assertEqual(["12"], dodge["explanation_components"]["related_modifier_codes"])
        self.assertEqual(["400"], dodge["explanation_components"]["related_modifier_static_buff_ids"])

    def test_live_stat_explanation_reports_base_additive_counterfactual(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            officer_buffs_path = decoded / "OfficerAbilityBuffSpecs.json"
            officer_buffs = json.loads(officer_buffs_path.read_text(encoding="utf-8"))
            officer_buffs["officerAbilitySpecs"]["300"] = _buff_spec(
                300,
                modifier_code=8,
                ranked_values=[20],
                operation="BUFFOPERATION_ADD",
            )
            officer_buffs["officerAbilitySpecs"]["300"]["conditionCodes"] = []
            officer_buffs["officerAbilitySpecs"]["400"] = _buff_spec(
                400,
                modifier_code=8,
                ranked_values=[1.0],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs["officerAbilitySpecs"]["400"]["conditionCodes"] = []
            officer_buffs_path.write_text(json.dumps(officer_buffs), encoding="utf-8")

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [
                {"buff_id": 300, "activator_id": 501, "ranks": [0], "expiry_time": None},
                {"buff_id": 400, "activator_id": 502, "ranks": [0], "expiry_time": None},
            ]
            deployed["ship_stats"]["111"]["8"] = 200
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        modulation = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "8")
        self.assertEqual(200, modulation["explained"])
        self.assertEqual(0, modulation["residual"])
        self.assertEqual("operation_model_closed", modulation["math_status"])
        self.assertEqual(180, modulation["explanation_components"]["legacy_flat_after_percent_explained"])
        self.assertEqual(20, modulation["explanation_components"]["legacy_flat_after_percent_residual"])
        self.assertEqual(200, modulation["explanation_components"]["base_additive_static_buffs_explained"])
        self.assertEqual(0, modulation["explanation_components"]["base_additive_static_buffs_residual"])
        self.assertEqual(
            "promoted_base_additive_static_buffs_close",
            modulation["explanation_components"]["flat_application_effect"],
        )
        self.assertEqual(["300"], modulation["explanation_components"]["flat_static_buff_ids"])
        self.assertEqual(["400"], modulation["explanation_components"]["multiply_static_buff_ids"])
        self.assertEqual(
            {
                "flat_application_effect": "promoted_base_additive_static_buffs_close",
                "count": 1,
                "hull_type": "HULLTYPE_EXPLORER",
                "stat_code": "8",
                "static_field": "weapon_modulation_max",
                "math_statuses": ["operation_model_closed"],
                "battle_sides": ["initiator"],
                "sample_battle_ids": ["123"],
                "sample_ship_ids": ["111"],
                "mean_abs_residual": 0,
                "mean_abs_legacy_flat_after_percent_residual": 20,
                "flat_static_buff_ids": ["300"],
                "multiply_static_buff_ids": ["400"],
            },
            report["flat_application_effects"][0],
        )

    def test_live_stat_explanation_reports_zero_based_rank_counterfactual(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            officer_buffs_path = decoded / "OfficerAbilityBuffSpecs.json"
            officer_buffs = json.loads(officer_buffs_path.read_text(encoding="utf-8"))
            officer_buffs["officerAbilitySpecs"]["300"] = _buff_spec(
                300,
                modifier_code=8,
                ranked_values=[10, 20],
                operation="BUFFOPERATION_ADD",
            )
            officer_buffs["officerAbilitySpecs"]["300"]["conditionCodes"] = []
            officer_buffs_path.write_text(json.dumps(officer_buffs), encoding="utf-8")

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [{"buff_id": 300, "activator_id": 501, "ranks": [1], "expiry_time": None}]
            deployed["ship_stats"]["111"]["8"] = 100
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        resolved = next(row for row in report["active_buffs"] if row["buff_id"] == "300")
        self.assertEqual(20, resolved["selected_ranked_value"])
        self.assertEqual(10, resolved["legacy_one_based_ranked_value"])
        modulation = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "8")
        self.assertEqual(100, modulation["explained"])
        self.assertEqual(0, modulation["residual"])
        self.assertEqual("operation_model_closed", modulation["math_status"])
        self.assertEqual(90, modulation["explanation_components"]["legacy_one_based_rank_explained"])
        self.assertEqual(10, modulation["explanation_components"]["legacy_one_based_rank_residual"])
        self.assertEqual(100, modulation["explanation_components"]["zero_based_rank_explained"])
        self.assertEqual(0, modulation["explanation_components"]["zero_based_rank_residual"])
        self.assertEqual(
            "promoted_zero_based_rank_selection_closes",
            modulation["explanation_components"]["rank_selection_effect"],
        )
        self.assertEqual(["300"], modulation["explanation_components"]["rank_sensitive_static_buff_ids"])
        self.assertEqual(
            {
                "rank_selection_effect": "promoted_zero_based_rank_selection_closes",
                "count": 1,
                "hull_type": "HULLTYPE_EXPLORER",
                "stat_code": "8",
                "static_field": "weapon_modulation_max",
                "math_statuses": ["operation_model_closed"],
                "battle_sides": ["initiator"],
                "sample_battle_ids": ["123"],
                "sample_ship_ids": ["111"],
                "mean_abs_residual": 0,
                "mean_abs_legacy_one_based_rank_residual": 10,
                "rank_sensitive_static_buff_ids": ["300"],
            },
            report["rank_selection_effects"][0],
        )

    def test_live_stat_explanation_reports_combined_zero_based_base_additive_counterfactual(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            officer_buffs_path = decoded / "OfficerAbilityBuffSpecs.json"
            officer_buffs = json.loads(officer_buffs_path.read_text(encoding="utf-8"))
            officer_buffs["officerAbilitySpecs"]["300"] = _buff_spec(
                300,
                modifier_code=8,
                ranked_values=[10, 20],
                operation="BUFFOPERATION_ADD",
            )
            officer_buffs["officerAbilitySpecs"]["300"]["conditionCodes"] = []
            officer_buffs["officerAbilitySpecs"]["400"] = _buff_spec(
                400,
                modifier_code=8,
                ranked_values=[1.0, 2.0],
                operation="BUFFOPERATION_MULTIPLYADD",
            )
            officer_buffs["officerAbilitySpecs"]["400"]["conditionCodes"] = []
            officer_buffs_path.write_text(json.dumps(officer_buffs), encoding="utf-8")

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [
                {"buff_id": 300, "activator_id": 501, "ranks": [1], "expiry_time": None},
                {"buff_id": 400, "activator_id": 502, "ranks": [1], "expiry_time": None},
            ]
            deployed["ship_stats"]["111"]["8"] = 300
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        modulation = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "8")
        self.assertEqual(300, modulation["explained"])
        self.assertEqual(0, modulation["residual"])
        self.assertEqual("operation_model_closed", modulation["math_status"])
        self.assertEqual(170, modulation["explanation_components"]["legacy_one_based_flat_after_percent_explained"])
        self.assertEqual(130, modulation["explanation_components"]["legacy_one_based_flat_after_percent_residual"])
        self.assertEqual(300, modulation["explanation_components"]["zero_based_base_additive_explained"])
        self.assertEqual(0, modulation["explanation_components"]["zero_based_base_additive_residual"])
        self.assertEqual(
            "promoted_zero_based_base_additive_closes",
            modulation["explanation_components"]["zero_based_base_additive_effect"],
        )
        self.assertEqual(
            {
                "zero_based_base_additive_effect": "promoted_zero_based_base_additive_closes",
                "count": 1,
                "hull_type": "HULLTYPE_EXPLORER",
                "stat_code": "8",
                "static_field": "weapon_modulation_max",
                "math_statuses": ["operation_model_closed"],
                "battle_sides": ["initiator"],
                "sample_battle_ids": ["123"],
                "sample_ship_ids": ["111"],
                "mean_abs_residual": 0,
                "mean_abs_legacy_one_based_flat_after_percent_residual": 130,
                "flat_static_buff_ids": ["300"],
                "rank_sensitive_static_buff_ids": ["300", "400"],
            },
            report["zero_based_base_additive_effects"][0],
        )

    def test_live_stat_explanation_treats_large_relative_near_zero_residual_as_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = []
            deployed["ship_stats"]["111"]["60"] = 2_000_000.4
            component_specs_path = decoded / "ComponentSpecs.json"
            component_specs = json.loads(component_specs_path.read_text(encoding="utf-8"))
            component_specs["componentSpecs"]["shield-1"]["shieldSpec"]["hp"] = 2_000_000
            component_specs_path.write_text(json.dumps(component_specs), encoding="utf-8")
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        shield_hp = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "60")
        self.assertAlmostEqual(0.4, shield_hp["residual"])
        self.assertEqual("static_only_closed", shield_hp["math_status"])

    def test_resolved_research_buffs_include_project_and_tree_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            (decoded / "ResearchSpecs.json").write_text(
                json.dumps(
                    {
                        "researchEffects": {"300": _buff_spec(300, modifier_code=6)},
                        "researchProjects": {
                            "project-1": {
                                "id": "project-1",
                                "researchTreeId": "tree-1",
                                "idRefs": {"locaId": "249", "artId": "238"},
                                "buffEffectsIds": ["300"],
                                "viewLevel": "42",
                                "levels": [{"militaryMight": "10"}, {"militaryMight": "20"}],
                            }
                        },
                        "researchTrees": [
                            {
                                "id": "tree-1",
                                "idRefs": {"locaId": "2", "artId": "2"},
                                "viewLevel": "1",
                                "factionId": "-1",
                                "entityType": "ENTITYTYPE_PLAYER",
                                "entityId": "-1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [{"buff_id": 300, "activator_id": 501, "ranks": [1], "expiry_time": None}]
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        research = next(row for row in report["active_buffs"] if row["buff_id"] == "300")
        self.assertEqual("research", research["source_type"])
        self.assertEqual("found", research["source_context"]["status"])
        self.assertEqual("project-1", research["source_context"]["research_projects"][0]["id"])
        self.assertEqual("researchProjects/project-1", research["source_context"]["research_projects"][0]["source_key"])
        self.assertEqual(2, research["source_context"]["research_projects"][0]["levels_count"])
        self.assertEqual(
            {"locaId": "249", "artId": "238"}, research["source_context"]["research_projects"][0]["idRefs"]
        )
        self.assertEqual("tree-1", research["source_context"]["research_projects"][0]["tree"]["id"])
        self.assertEqual(
            "researchTrees/0", research["source_context"]["research_projects"][0]["tree"]["source_key"]
        )

        accuracy = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "6")
        self.assertEqual("project-1", accuracy["matching_resolved_buffs"][0]["source_context"]["research_projects"][0]["id"])

    def test_resolved_research_buffs_include_localized_idref_text_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            (decoded / "LocalizationCacheData.json").write_text(
                json.dumps(
                    {
                        "language": "en",
                        "categories": {
                            "1": {
                                "info": {"id": "1", "name": "research"},
                                "translations": {
                                    "249": {"id": "research_project_name", "key": "249", "text": "Impulse Optimization"},
                                    "238": {"id": "research_project_art", "key": "238", "text": "Impulse Artwork"},
                                },
                            },
                            "2": {
                                "info": {"id": "2", "name": "trees"},
                                "translations": {
                                    "2": {"id": "station_tree", "key": "2", "text": "Station Research"},
                                    "300": {"id": "buff_name", "key": "300", "text": "Dodge Boost"},
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (decoded / "ResearchSpecs.json").write_text(
                json.dumps(
                    {
                        "researchEffects": {"300": {**_buff_spec(300, modifier_code=6), "idRefs": {"locaId": "300"}}},
                        "researchProjects": {
                            "project-1": {
                                "id": "project-1",
                                "researchTreeId": "tree-1",
                                "idRefs": {"locaId": "249", "artId": "238"},
                                "buffEffectsIds": ["300"],
                                "viewLevel": "42",
                                "levels": [{"militaryMight": "10"}],
                            }
                        },
                        "researchTrees": [
                            {
                                "id": "tree-1",
                                "idRefs": {"locaId": "2", "artId": "missing-art"},
                                "viewLevel": "1",
                                "factionId": "-1",
                                "entityType": "ENTITYTYPE_PLAYER",
                                "entityId": "-1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [{"buff_id": 300, "activator_id": 501, "ranks": [1], "expiry_time": None}]
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        research = next(row for row in report["active_buffs"] if row["buff_id"] == "300")
        self.assertEqual(
            {
                "locaId": "300",
                "locaText": "Dodge Boost",
                "locaTextSource": "LocalizationCacheData:en/trees",
            },
            research["source_context"]["buff_spec"]["idRefs"],
        )
        project_refs = research["source_context"]["research_projects"][0]["idRefs"]
        self.assertEqual("Impulse Optimization", project_refs["locaText"])
        self.assertEqual("Impulse Artwork", project_refs["artText"])
        tree_refs = research["source_context"]["research_projects"][0]["tree"]["idRefs"]
        self.assertEqual("Station Research", tree_refs["locaText"])
        self.assertNotIn("artText", tree_refs)
        self.assertEqual("found", report["static_sources"]["LocalizationCacheData"]["status"])
        self.assertEqual(4, report["static_sources"]["LocalizationCacheData"]["entries"])
        self.assertEqual(2, report["static_sources"]["LocalizationCacheData"]["categories"])

    def test_buff_only_sources_include_buff_spec_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            consumable_buff = _buff_spec(500, modifier_code=60)
            consumable_buff["idRefs"] = {"locaId": "loca-500", "artId": "art-500"}
            consumable_buff["attributes"] = {"grade": 7, "factionId": "-1"}
            consumable_buff["showPercentage"] = True
            (decoded / "ConsumableBuffs.json").write_text(
                json.dumps({"consumableBuffsSpecs": {"500": consumable_buff}}),
                encoding="utf-8",
            )

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [{"buff_id": 500, "activator_id": 501, "ranks": [1], "expiry_time": None}]
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        consumable = next(row for row in report["active_buffs"] if row["buff_id"] == "500")
        self.assertEqual("consumable", consumable["source_type"])
        self.assertEqual("buff_spec_only", consumable["source_context"]["status"])
        self.assertEqual(
            {
                "buff_id": "500",
                "idRefs": {"locaId": "loca-500", "artId": "art-500"},
                "attributes": {"grade": 7, "factionId": "-1"},
                "showPercentage": True,
            },
            consumable["source_context"]["buff_spec"],
        )

    def test_officer_ability_buffs_include_officer_context_when_linked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            officers_path = decoded / "OfficerSpecs.json"
            officers = json.loads(officers_path.read_text(encoding="utf-8"))
            officers["officerSpecs"]["officer-1"] = {
                "id": "officer-1",
                "idRefs": {"locaId": "officer-loca", "artId": "officer-art"},
                "rarity": "RARITY_EPIC",
                "officerClassType": "OFFICERCORESTATTYPE_ATTACK",
                "officerType": "OFFICERTYPE_REGULAROFFICER",
                "factionId": "faction-1",
                "captainManeuverId": "-1",
                "officerAbilityId": "-1",
                "belowDecksAbilityId": "100",
            }
            officers_path.write_text(json.dumps(officers), encoding="utf-8")
            _write_capture(capture_root)

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        officer_buff = next(row for row in report["active_buffs"] if row["buff_id"] == "100")
        self.assertEqual("officer_ability", officer_buff["source_type"])
        self.assertEqual("found", officer_buff["source_context"]["status"])
        self.assertEqual(
            {
                "id": "officer-1",
                "source_key": "officerSpecs/officer-1",
                "ability_field": "belowDecksAbilityId",
                "idRefs": {"locaId": "officer-loca", "artId": "officer-art"},
                "rarity": "RARITY_EPIC",
                "officerClassType": "OFFICERCORESTATTYPE_ATTACK",
                "officerType": "OFFICERTYPE_REGULAROFFICER",
                "factionId": "faction-1",
            },
            officer_buff["source_context"]["officers"][0],
        )
        self.assertEqual("100", officer_buff["source_context"]["buff_spec"]["buff_id"])

        accuracy = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "6")
        self.assertEqual("officer-1", accuracy["matching_resolved_buffs"][0]["source_context"]["officers"][0]["id"])

    def test_live_stat_explanation_deduplicates_generated_core_stat_modifiers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [
                {"buff_id": 888, "activator_id": 111, "ranks": [2], "expiry_time": None},
                {"buff_id": 889, "activator_id": 111, "ranks": [2], "expiry_time": None},
            ]
            deployed["ship_stats"]["111"]["-2"] = 240
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        shield_absorption = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "-2")
        self.assertEqual(40, shield_absorption["static"])
        self.assertEqual(240, shield_absorption["captured"])
        self.assertEqual(240, shield_absorption["explained"])
        self.assertEqual(0, shield_absorption["residual"])
        self.assertEqual("generated_core_stat_model_closed", shield_absorption["math_status"])
        self.assertEqual(["888", "889"], [buff["buff_id"] for buff in shield_absorption["matching_generated_buffs"]])
        self.assertEqual(5, shield_absorption["explanation_components"]["generated_percent_total"])
        self.assertEqual(["-16"], shield_absorption["explanation_components"]["applied_generated_modifierCodes"])
        self.assertEqual(["DEFENSE"], shield_absorption["explanation_components"]["applied_generated_core_stats"])
        self.assertEqual(["888", "889"], shield_absorption["explanation_components"]["applied_generated_buff_ids"])

    def test_serene_squall_warshield_applies_provisional_dodge_modifier(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            hull_specs_path = decoded / "HullSpecs.json"
            hull_specs = json.loads(hull_specs_path.read_text(encoding="utf-8"))
            hull_specs["hullSpecs"]["697653604"] = {
                "id": "697653604",
                "idStr": "Hull_G3_Survey_None_SereneSquall",
                "name": "Serene Squall",
                "type": "HULLTYPE_SURVEY",
                "componentDefaults": ["armor-1", "shield-1", "impulse-1", "weapon-1"],
                "activatedAbilitiesIds": ["3488429048"],
            }
            hull_specs_path.write_text(json.dumps(hull_specs), encoding="utf-8")
            (decoded / "ActivatedAbilitySpecs.json").write_text(
                json.dumps(
                    {
                        "spec": [
                            {
                                "id": "3488429048",
                                "idStr": "WARSHIELDS_SERENESQUALL",
                                "abilityType": "ACTIVATEDABILITYTYPE_WARSHIELD",
                                "statusEffect": "4",
                                "buffIds": [
                                    "3221322680",
                                    "3913316913",
                                    "2307361409",
                                    "804797682",
                                    "1744906888",
                                    "775790404",
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["hull_ids"] = ["697653604"]
            deployed["active_buffs"] = []
            deployed["status_effects"] = {"4": 1777599982.0}
            deployed["ship_stats"]["111"]["-3"] = 75
            deployed["ship_stats"]["111"]["-2"] = 100
            deployed["ship_stats"]["111"]["11"] = 87.5
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        dodge = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "11")
        self.assertEqual(50, dodge["static"])
        self.assertEqual(87.5, dodge["captured"])
        self.assertEqual(87.5, dodge["explained"])
        self.assertEqual(0, dodge["residual"])
        self.assertEqual("generated_core_stat_model_closed", dodge["math_status"])
        self.assertEqual(["804797682"], dodge["explanation_components"]["applied_generated_buff_ids"])
        self.assertEqual(["11"], dodge["explanation_components"]["applied_generated_modifierCodes"])
        self.assertEqual(0.75, dodge["explanation_components"]["generated_percent_total"])
        armor_plating = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "-3")
        self.assertEqual(30, armor_plating["static"])
        self.assertEqual(75, armor_plating["captured"])
        self.assertEqual(75, armor_plating["explained"])
        self.assertEqual(0, armor_plating["residual"])
        self.assertEqual(["3913316913"], armor_plating["explanation_components"]["applied_generated_buff_ids"])
        self.assertEqual(["-3"], armor_plating["explanation_components"]["applied_generated_modifierCodes"])
        self.assertEqual(1.5, armor_plating["explanation_components"]["generated_percent_total"])
        shield_absorption = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "-2")
        self.assertEqual(40, shield_absorption["static"])
        self.assertEqual(100, shield_absorption["captured"])
        self.assertEqual(100, shield_absorption["explained"])
        self.assertEqual(0, shield_absorption["residual"])
        self.assertEqual(["2307361409"], shield_absorption["explanation_components"]["applied_generated_buff_ids"])
        self.assertEqual(["-2"], shield_absorption["explanation_components"]["applied_generated_modifierCodes"])

    def test_live_stat_explanation_keeps_static_closed_rows_closed_with_generated_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)

            fleet = _fleet()
            deployed = fleet["deployed_fleet"]
            deployed["active_buffs"] = [{"buff_id": 888, "activator_id": 111, "ranks": [2], "expiry_time": None}]
            deployed["ship_stats"]["111"]["-3"] = 30
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": fleet,
                            "target_fleet_data": {"deployed_fleet": {"ship_ids": [0], "hull_ids": ["hull-1"]}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        armor_plating = next(row for row in report["live_stat_residuals"] if row["stat_code"] == "-3")
        self.assertEqual(30, armor_plating["static"])
        self.assertEqual(30, armor_plating["captured"])
        self.assertEqual(30, armor_plating["explained"])
        self.assertEqual(0, armor_plating["residual"])
        self.assertEqual("static_only_closed", armor_plating["math_status"])
        self.assertEqual(["888"], [buff["buff_id"] for buff in armor_plating["matching_generated_buffs"]])
        self.assertEqual([], armor_plating["explanation_components"]["applied_generated_modifierCodes"])

    def test_resolves_player_fleet_when_player_is_battle_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            battles = capture_root / "battles"
            battles.mkdir(parents=True)
            (battles / "battle-1.json").write_text(
                json.dumps(
                    {
                        "server_version": "test-version",
                        "journal": {
                            "id": 123,
                            "initiator_fleet_data": {
                                "deployed_fleet": {
                                    "fleet_id": 1,
                                    "hull_ids": ["hostile-hull"],
                                    "ship_ids": [0],
                                    "ship_stats": {"0": {"6": 999}},
                                    "active_buffs": [],
                                }
                            },
                            "target_fleet_data": _fleet(),
                        },
                    }
                ),
                encoding="utf-8",
            )

            report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)

        self.assertEqual(1, report["summary"]["player_fleet_count"])
        self.assertEqual(4, report["summary"]["active_buff_count"])
        self.assertEqual({"target"}, {row["battle_side"] for row in report["active_buffs"]})
        self.assertEqual({"target"}, {row["battle_side"] for row in report["live_stat_residuals"]})
        self.assertEqual({"111"}, {row["ship_id"] for row in report["live_stat_residuals"]})

    def test_cli_buff_audit_writes_report_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            out_path = root / "buff-audit.json"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "buff-audit",
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
            self.assertEqual(4, report["summary"]["active_buff_count"])

    def test_simulator_detail_keeps_resolved_state_and_prunes_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            full_report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root)
            slim_report = generate_buff_audit(decoded_static_dir=decoded, capture_root=capture_root, detail="simulator")

        self.assertEqual("simulator", slim_report["detail"])
        self.assertEqual([], slim_report["aggregate_modifier_rows"])
        self.assertNotIn("modifier_codes", slim_report)
        self.assertNotIn("matching_resolved_buffs", slim_report["live_stat_residuals"][0])
        self.assertEqual(
            build_resolved_player_state_index(full_report),
            build_resolved_player_state_index(slim_report),
        )

    def test_cli_buff_audit_writes_simulator_detail_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            capture_root = root / "captures"
            out_path = root / "buff-audit.json"
            _write_decoded_static(decoded)
            _write_capture(capture_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "buff-audit",
                    "--decoded-static-dir",
                    str(decoded),
                    "--capture-root",
                    str(capture_root),
                    "--detail",
                    "simulator",
                    "--out",
                    str(out_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            report = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual("simulator", report["detail"])
            self.assertEqual(4, report["summary"]["active_buff_count"])
            self.assertNotIn("modifier_codes", report)


if __name__ == "__main__":
    unittest.main()
