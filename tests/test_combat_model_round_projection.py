from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.damage_pipeline import predict_damage_from_stages
from scripts.lib.combat_model.mitigation_model import load_synced_linear_mitigation_model
from scripts.lib.combat_model.round_projection import (
    _apex_mitigation,
    _initial_states,
    _isolytic_damage_assumption,
    _raw_damage_assumption,
    _standard_mitigation,
    build_projected_schedule,
    load_observations_jsonl,
    project_observations,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConstantMitigationModel:
    model_name = "constant_test_model"
    model_source = "test"

    def __init__(self, mitigation: float) -> None:
        self.mitigation = mitigation

    def predict(self, _row: dict[str, object]) -> float:
        return self.mitigation

    def metadata(self) -> dict[str, object]:
        return {"model_name": self.model_name, "model_source": self.model_source}


def _ship(side: str, *, hull: int = 1000, shield: int = 500) -> dict[str, object]:
    weapons = [
        {
            "id": "w1",
            "name": f"{side} weapon 1",
            "minimum_damage": 100,
            "maximum_damage": 100,
            "shots": 1,
            "warm_up": 1,
            "cooldown": 2,
            "crit_chance": 0,
            "crit_modifier": 1,
        },
        {
            "id": "w2",
            "name": f"{side} weapon 2",
            "minimum_damage": 50,
            "maximum_damage": 50,
            "shots": 1,
            "warm_up": 1,
            "cooldown": 3,
            "crit_chance": 0,
            "crit_modifier": 1,
        },
    ]
    return {
        "ship_id": f"{side}-ship",
        "captured_stats": {
            "60": shield,
            "61": hull,
            "3": 1,
        },
        "static_ship": {
            "base_stats": {
                "hull_hp": hull,
                "shield_hp": shield,
                "shield_mitigation": 0.8,
                "dodge": 0,
                "armor_plating": 0,
                "shield_absorption": 0,
                "weapon_accuracy_max": 100,
                "weapon_penetration_max": 100,
                "weapon_modulation_max": 100,
            },
            "hull": {
                "id": f"{side}-hull",
                "name": f"{side} hull",
                "type": "HULLTYPE_EXPLORER",
                "grade": 1,
            },
            "weapons": weapons,
        },
    }


def _row(
    *,
    attack_index: int,
    battle_round: int,
    sub_round: int,
    attacker_side: str,
    weapon_id: str,
    damage: int,
    remaining_shield: int,
    remaining_hull: int,
) -> dict[str, object]:
    player = _ship("player")
    hostile = _ship("hostile")
    attacker = player if attacker_side == "player" else hostile
    defender = hostile if attacker_side == "player" else player
    defender_side = "hostile" if attacker_side == "player" else "player"
    weapon = next(
        dict(candidate)
        for candidate in attacker["static_ship"]["weapons"]  # type: ignore[index]
        if candidate["id"] == weapon_id
    )
    return {
        "schema_version": 1,
        "battle_id": "battle-1",
        "battle_type": 2,
        "battle_type_name": "PASSIVE_MARAUDER",
        "attack_index": attack_index,
        "battle_round": battle_round,
        "sub_round": sub_round,
        "attacker_side": attacker_side,
        "defender_side": defender_side,
        "attacker": attacker,
        "defender": defender,
        "weapon": weapon,
        "observed": {
            "hit": True,
            "critical": False,
            "raw_damage": damage,
            "mitigated_damage": 0,
            "isolytic_damage": 0,
            "mitigated_isolytic_damage": 0,
            "mitigated_apex_barrier": 0,
            "damage": {
                "shield": damage,
                "hull": 0,
            },
            "remaining": {
                "shield": remaining_shield,
                "hull": remaining_hull,
            },
            "triggered_effects": [],
        },
    }


def _rows() -> list[dict[str, object]]:
    return [
        _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="player",
            weapon_id="w1",
            damage=80,
            remaining_shield=420,
            remaining_hull=1000,
        ),
        _row(
            attack_index=2,
            battle_round=1,
            sub_round=2,
            attacker_side="player",
            weapon_id="w2",
            damage=40,
            remaining_shield=380,
            remaining_hull=1000,
        ),
    ]


def _mitigation_report() -> dict[str, object]:
    return {
        "broad_formula_goal": {
            "candidate_metrics": {
                "combat_triangle_synced_linear_formula": {
                    "model": {
                        "formula": "clamp(sum(feature_value * coefficient), 0, 0.95)",
                        "base_formula": "combat_triangle_static_player_max_buffs_formula",
                        "attacker_hull_labels": [],
                        "defender_hull_labels": [],
                        "features": ["intercept", "battle_type=2"],
                        "coefficients": {
                            "intercept": 0.2,
                            "battle_type=2": 0.1,
                        },
                    }
                }
            }
        }
    }


class CombatModelRoundProjectionTests(unittest.TestCase):
    def test_loads_synced_linear_mitigation_model_from_analysis_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mitigation-analysis.json"
            path.write_text(json.dumps(_mitigation_report()), encoding="utf-8")

            model = load_synced_linear_mitigation_model(path)

        self.assertEqual("combat_triangle_synced_linear_formula", model.model_name)
        self.assertAlmostEqual(0.3, model.predict({"battle_type": 2, "observed": {"remaining": {"shield": 10}}}))
        self.assertEqual("combat_triangle_static_player_max_buffs_formula", model.metadata()["base_formula"])

    def test_damage_pipeline_accepts_projected_pre_shot_state(self) -> None:
        result = predict_damage_from_stages(
            {
                "defender": {"static_ship": {"base_stats": {"shield_mitigation": 0.4}}},
                "observed": {
                    "damage": {"shield": 1, "hull": 1},
                    "remaining": {"shield": 1, "hull": 1},
                },
            },
            standard_raw_damage=100,
            standard_mitigation=0.0,
            pre_shot_state={"shield": 50, "hull": 1000},
        )

        self.assertEqual({"shield": 40, "hull": 60}, result["damage"])
        self.assertEqual({"shield": 10, "hull": 940}, result["remaining"])

    def test_builds_deterministic_weapon_schedule_from_warmup_and_cooldown(self) -> None:
        schedule = build_projected_schedule(_rows(), max_rounds=3, max_attacks=20)

        self.assertEqual(
            [
                ("player", 1, "w1"),
                ("player", 1, "w2"),
                ("hostile", 1, "w1"),
                ("hostile", 1, "w2"),
                ("player", 3, "w1"),
                ("hostile", 3, "w1"),
            ],
            [(attack["attacker_side"], attack["battle_round"], attack["weapon"]["id"]) for attack in schedule],
        )

    def test_raw_damage_assumption_applies_mod_all_damage_multiplier(self) -> None:
        row = _rows()[0]
        row["battle_type"] = 8
        row["attacker"]["resolved_modifiers"] = {"2": 2.0}  # type: ignore[index]

        assumption = _raw_damage_assumption(row)

        self.assertEqual(100, assumption["effective_midpoint"])
        self.assertEqual(2, assumption["standard_damage_modifier"])
        self.assertEqual(3, assumption["standard_damage_multiplier"])
        self.assertEqual(300, assumption["standard_raw_damage"])

    def test_raw_damage_assumption_applies_wave_defense_damage_multiplier(self) -> None:
        row = _rows()[0]
        row["attacker"]["resolved_modifiers"] = {"2": 1.0, "88": 2.2}  # type: ignore[index]
        row["defender"]["static_ship"]["hull"]["name"] = "Hull_L45_Destroyer_Klg_WaveDefense"  # type: ignore[index]

        assumption = _raw_damage_assumption(row)

        self.assertEqual(
            "weapon_midpoint_expected_crit_mod_all_damage_wave_defense_player_damage_scale_wave_defense_modifier_88",
            assumption["source"],
        )
        self.assertEqual(2.2, assumption["wave_defense_damage_modifier"])
        self.assertEqual(1.12, assumption["wave_defense_player_damage_scale"])
        self.assertAlmostEqual(492.8, assumption["standard_raw_damage"])

    def test_raw_damage_assumption_does_not_apply_wave_defense_damage_multiplier_outside_wave(self) -> None:
        row = _rows()[0]
        row["battle_type"] = 8
        row["attacker"]["resolved_modifiers"] = {"2": 1.0, "88": 2.2}  # type: ignore[index]

        assumption = _raw_damage_assumption(row)

        self.assertEqual("weapon_midpoint_expected_crit_mod_all_damage", assumption["source"])
        self.assertNotIn("wave_defense_damage_modifier", assumption)
        self.assertEqual(200, assumption["standard_raw_damage"])

    def test_observed_order_projection_applies_standard_hostile_raw_damage_scale(self) -> None:
        row = _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="hostile",
            weapon_id="w1",
            damage=80,
            remaining_shield=420,
            remaining_hull=1000,
        )

        assumption = _raw_damage_assumption(row, use_observed_critical=True)

        self.assertEqual(
            "weapon_midpoint_observed_noncrit_mod_all_damage_pve_hostile_damage_scale_standard_hostile_damage_scale",
            assumption["source"],
        )
        self.assertEqual(0.692, assumption["pve_hostile_damage_scale"])
        self.assertEqual(1.1, assumption["standard_hostile_damage_scale"])
        self.assertAlmostEqual(76.12, assumption["standard_raw_damage"])

    def test_raw_damage_assumption_applies_standard_hostile_player_damage_scale(self) -> None:
        row = _rows()[0]

        assumption = _raw_damage_assumption(row)

        self.assertEqual(
            "weapon_midpoint_expected_crit_mod_all_damage_standard_hostile_damage_scale",
            assumption["source"],
        )
        self.assertEqual(1.5, assumption["standard_hostile_damage_scale"])
        self.assertEqual(150, assumption["standard_raw_damage"])

    def test_raw_damage_assumption_applies_wave_player_critical_damage_surface(self) -> None:
        row = _rows()[0]
        row["observed"]["critical"] = True  # type: ignore[index]
        row["weapon"]["crit_modifier"] = 1.5  # type: ignore[index]
        row["attacker"]["resolved_modifiers"] = {"88": 2.2}  # type: ignore[index]
        row["defender"]["static_ship"]["hull"]["name"] = "Hull_L45_Destroyer_Klg_WaveDefense"  # type: ignore[index]

        assumption = _raw_damage_assumption(row, use_observed_critical=True)

        self.assertEqual(1.12, assumption["wave_defense_player_damage_scale"])
        self.assertEqual(1.1, assumption["wave_defense_player_critical_damage_scale"])
        self.assertEqual(2.2, assumption["wave_defense_damage_multiplier"])
        self.assertAlmostEqual(406.56, assumption["standard_raw_damage"])

    def test_wave_defense_hostile_shots_use_player_defender_mitigation_surface(self) -> None:
        row = _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="hostile",
            weapon_id="w1",
            damage=80,
            remaining_shield=420,
            remaining_hull=1000,
        )
        row["attacker"]["static_ship"]["hull"]["name"] = "Hull_L45_Destroyer_Klg_WaveDefense"  # type: ignore[index]
        row["defender"]["static_ship"]["hull"]["name"] = "Junker"  # type: ignore[index]

        mitigation = _standard_mitigation(row, ConstantMitigationModel(0.2))

        self.assertEqual(0.701457, mitigation)

    def test_wave_defense_hostile_shots_use_player_defender_apex_surface(self) -> None:
        row = _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="hostile",
            weapon_id="w1",
            damage=80,
            remaining_shield=420,
            remaining_hull=1000,
        )
        row["attacker"]["static_ship"]["hull"]["name"] = "Hull_L45_Destroyer_Klg_WaveDefense"  # type: ignore[index]
        row["defender"]["static_ship"]["hull"]["name"] = "Junker"  # type: ignore[index]

        self.assertEqual(0.10314, _apex_mitigation(row))

    def test_standard_hostile_shots_use_player_defender_apex_surface(self) -> None:
        row = _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="hostile",
            weapon_id="w1",
            damage=80,
            remaining_shield=420,
            remaining_hull=1000,
        )
        row["defender"]["static_ship"]["hull"]["name"] = "USS Titan-A"  # type: ignore[index]

        self.assertEqual(0.014778, _apex_mitigation(row))

    def test_observed_order_projection_caps_pve_hostile_critical_modifier(self) -> None:
        row = _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="hostile",
            weapon_id="w1",
            damage=80,
            remaining_shield=420,
            remaining_hull=1000,
        )
        row["observed"]["critical"] = True  # type: ignore[index]
        row["weapon"]["crit_modifier"] = 1.8  # type: ignore[index]

        assumption = _raw_damage_assumption(row, use_observed_critical=True)

        self.assertEqual(
            "weapon_midpoint_observed_crit_mod_all_damage_pve_hostile_damage_scale_standard_hostile_damage_scale",
            assumption["source"],
        )
        self.assertEqual(1.5, assumption["crit_multiplier"])
        self.assertEqual(0.692, assumption["pve_hostile_damage_scale"])
        self.assertEqual(1.1, assumption["standard_hostile_damage_scale"])
        self.assertAlmostEqual(114.18, assumption["standard_raw_damage"])

    def test_observed_order_projection_uses_observed_critical_damage_multiplier(self) -> None:
        row = _rows()[0]
        row["observed"]["critical"] = True  # type: ignore[index]
        row["weapon"]["crit_chance"] = 0.1  # type: ignore[index]
        row["weapon"]["crit_modifier"] = 1.5  # type: ignore[index]
        row["attacker"]["captured_stats"]["10"] = 2.0  # type: ignore[index]

        report = project_observations(
            [row],
            mitigation_model=ConstantMitigationModel(0.2),
            mode="observed-order",
            max_rounds=5,
            max_attacks=20,
        )

        raw_damage = report["battles"][0]["attacks"][0]["raw_damage"]
        self.assertEqual(
            "weapon_midpoint_observed_crit_mod_all_damage_standard_hostile_damage_scale",
            raw_damage["source"],
        )
        self.assertEqual(3, raw_damage["crit_multiplier"])
        self.assertEqual(1.5, raw_damage["standard_hostile_damage_scale"])
        self.assertEqual(450, raw_damage["standard_raw_damage"])

    def test_observed_critical_multiplier_ignores_hostile_captured_crit_stat(self) -> None:
        row = _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="hostile",
            weapon_id="w1",
            damage=80,
            remaining_shield=420,
            remaining_hull=1000,
        )
        row["observed"]["critical"] = True  # type: ignore[index]
        row["weapon"]["crit_modifier"] = 1.5  # type: ignore[index]
        row["attacker"]["captured_stats"]["10"] = 2.0  # type: ignore[index]

        assumption = _raw_damage_assumption(row, use_observed_critical=True)

        self.assertEqual(
            "weapon_midpoint_observed_crit_mod_all_damage_pve_hostile_damage_scale_standard_hostile_damage_scale",
            assumption["source"],
        )
        self.assertEqual(1.5, assumption["crit_multiplier"])
        self.assertEqual(0.692, assumption["pve_hostile_damage_scale"])
        self.assertEqual(1.1, assumption["standard_hostile_damage_scale"])
        self.assertAlmostEqual(114.18, assumption["standard_raw_damage"])

    def test_isolytic_damage_assumption_uses_mod_707_and_defender_808(self) -> None:
        row = _rows()[0]
        row["attacker"]["resolved_modifiers"] = {"707": 0.5}  # type: ignore[index]
        row["defender"]["resolved_modifiers"] = {"808": 1.0}  # type: ignore[index]

        assumption = _isolytic_damage_assumption(row, 200)

        self.assertEqual("attacker_mod_707_from_standard_raw_damage", assumption["source"])
        self.assertEqual(0.5, assumption["damage_modifier"])
        self.assertEqual(100, assumption["raw_damage"])
        self.assertEqual(0.5, assumption["mitigation"])

    def test_isolytic_damage_assumption_uses_captured_final_707_with_activation_cascade(self) -> None:
        row = _rows()[0]
        row["attacker"]["captured_fleet_stats"] = {"707": 2.26}  # type: ignore[index]
        row["attacker"]["resolved_modifiers"] = {"707": 0.02}  # type: ignore[index]
        row["observed"]["forbidden_tech_activations"] = [  # type: ignore[index]
            {"modifierCode": "707", "op": "BUFFOPERATION_ADD", "value": 0.02},
        ]

        assumption = _isolytic_damage_assumption(row, 1000)

        self.assertEqual("captured_final_fleet_707_from_standard_raw_damage", assumption["source"])
        self.assertAlmostEqual(1.3052, assumption["damage_modifier"])
        self.assertEqual(1305, assumption["raw_damage"])

    def test_isolytic_damage_assumption_ignores_neutral_captured_final_707(self) -> None:
        row = _rows()[0]
        row["attacker"]["captured_fleet_stats"] = {"707": 1.0}  # type: ignore[index]

        assumption = _isolytic_damage_assumption(row, 1000)

        self.assertEqual("attacker_mod_707_from_standard_raw_damage", assumption["source"])
        self.assertEqual(0, assumption["damage_modifier"])
        self.assertEqual(0, assumption["raw_damage"])

    def test_isolytic_damage_assumption_applies_wave_junker_buff_surface(self) -> None:
        row = _rows()[0]
        row["attacker"]["resolved_modifiers"] = {"707": 2.11}  # type: ignore[index]
        row["attacker"]["static_ship"]["hull"]["name"] = "Junker"  # type: ignore[index]
        row["defender"]["static_ship"]["hull"]["name"] = "Hull_L45_Destroyer_Klg_WaveDefense"  # type: ignore[index]

        assumption = _isolytic_damage_assumption(row, 1000)

        self.assertEqual("wave_defense_player_isolytic_buff_surface_Junker", assumption["source"])
        self.assertEqual(2.748, assumption["damage_modifier"])
        self.assertEqual(2748, assumption["raw_damage"])

    def test_isolytic_damage_assumption_applies_wave_newton_buff_surface(self) -> None:
        row = _rows()[0]
        row["attacker"]["resolved_modifiers"] = {"707": 2.11}  # type: ignore[index]
        row["attacker"]["static_ship"]["hull"]["name"] = "Newton_LIVE"  # type: ignore[index]
        row["defender"]["static_ship"]["hull"]["name"] = "Hull_L45_Destroyer_Klg_WaveDefense"  # type: ignore[index]

        assumption = _isolytic_damage_assumption(row, 1000)

        self.assertEqual("wave_defense_player_isolytic_buff_surface_Newton_LIVE", assumption["source"])
        self.assertEqual(1.248, assumption["damage_modifier"])
        self.assertEqual(1248, assumption["raw_damage"])

    def test_chain_shot_raw_damage_uses_observed_normal_raw_for_weapon_zero(self) -> None:
        row = _rows()[0]
        row["weapon"] = {"id": 0}
        row["attacker"]["resolved_modifiers"] = {"77001": 75000000, "77002": 50000}  # type: ignore[index]
        row["observed"]["normal_mitigation"] = {"raw_damage": 81300000}  # type: ignore[index]

        assumption = _raw_damage_assumption(row)

        self.assertEqual("chain_shot_observed_normal_raw_damage", assumption["source"])
        self.assertEqual(75000000, assumption["chain_shot_damage_modifier"])
        self.assertEqual(50000, assumption["chain_shot_secondary_modifier"])
        self.assertEqual(81300000, assumption["standard_raw_damage"])

    def test_damage_pipeline_applies_chain_shot_as_direct_hull_damage(self) -> None:
        row = _rows()[0]
        row["weapon"] = {"id": 0}
        row["attacker"]["resolved_modifiers"] = {"77001": 75000000, "77002": 50000}  # type: ignore[index]

        result = predict_damage_from_stages(
            row,
            standard_raw_damage=81300000,
            standard_mitigation=0.95,
            pre_shot_state={"shield": 1301910274, "hull": 1022929006},
        )

        self.assertEqual("chain_shot_direct_hull", result["mode"])
        self.assertEqual({"shield": 0, "hull": 81300000}, result["damage"])
        self.assertEqual({"shield": 1301910274, "hull": 941629006}, result["remaining"])

    def test_chain_shot_attack_does_not_spawn_isolytic_damage_lane(self) -> None:
        row = _rows()[0]
        row["weapon"] = {"id": 0}
        row["attacker"]["resolved_modifiers"] = {  # type: ignore[index]
            "707": 2.11,
            "77001": 75000000,
            "77002": 50000,
        }

        assumption = _isolytic_damage_assumption(row, 81300000)

        self.assertEqual("chain_shot_no_isolytic_lane", assumption["source"])
        self.assertEqual(2.11, assumption["damage_modifier"])
        self.assertEqual(0, assumption["raw_damage"])

    def test_initial_states_use_first_observed_pre_shot_state(self) -> None:
        first = _row(
            attack_index=1,
            battle_round=1,
            sub_round=1,
            attacker_side="hostile",
            weapon_id="w1",
            damage=20,
            remaining_shield=300,
            remaining_hull=700,
        )
        first["observed"]["damage"]["hull"] = 10  # type: ignore[index]
        second = _row(
            attack_index=2,
            battle_round=1,
            sub_round=2,
            attacker_side="hostile",
            weapon_id="w2",
            damage=30,
            remaining_shield=270,
            remaining_hull=690,
        )

        states = _initial_states([first, second])

        self.assertEqual({"shield": 320, "hull": 710}, states["player"])

    def test_projects_observed_order_attacks_with_projected_state(self) -> None:
        report = project_observations(
            _rows(),
            mitigation_model=ConstantMitigationModel(0.2),
            mode="observed-order",
            max_rounds=5,
            max_attacks=20,
        )

        self.assertEqual("observed-order", report["metadata"]["mode"])
        self.assertEqual(1, report["summary"]["battle_count"])
        self.assertEqual(2, report["summary"]["attack_count"])
        battle = report["battles"][0]
        self.assertEqual({"shield": 380, "hull": 1000}, battle["observed_final_state"]["hostile"])
        self.assertEqual({"shield": 356, "hull": 964}, battle["projected_final_state"]["hostile"])
        self.assertEqual(30, battle["metrics"]["damage_mae"])
        self.assertEqual(2, len(battle["attacks"]))
        self.assertEqual(0.2, battle["attacks"][0]["mitigation"]["standard"])

    def test_cli_project_rounds_writes_json_and_markdown_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            observations_path = temp_path / "observations.jsonl"
            mitigation_path = temp_path / "mitigation-analysis.json"
            out_path = temp_path / "projection.json"
            observations_path.write_text("".join(json.dumps(row) + "\n" for row in _rows()), encoding="utf-8")
            mitigation_path.write_text(json.dumps(_mitigation_report()), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "project-rounds",
                    "--observations",
                    str(observations_path),
                    "--mitigation-analysis",
                    str(mitigation_path),
                    "--out",
                    str(out_path),
                    "--mode",
                    "observed-order",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            markdown_path = temp_path / "projection.md"

            self.assertEqual("", result.stderr)
            self.assertEqual(0, result.returncode)
            self.assertTrue(out_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertEqual(2, json.loads(out_path.read_text(encoding="utf-8"))["summary"]["attack_count"])
            self.assertIn("# Combat Projection Report", markdown_path.read_text(encoding="utf-8"))

    def test_load_observations_jsonl_skips_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "observations.jsonl"
            path.write_text(json.dumps(_rows()[0]) + "\n\n", encoding="utf-8")

            self.assertEqual(1, len(load_observations_jsonl(path)))


if __name__ == "__main__":
    unittest.main()
