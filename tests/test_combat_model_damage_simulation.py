from __future__ import annotations

import unittest

from scripts.lib.combat_model.damage_simulation import (
    evaluate_observed_apex_barrier_replay,
    evaluate_observed_mitigation_damage_replay,
    evaluate_observed_isolytic_damage_replay,
    infer_pre_shot_state,
    simulate_isolytic_damage,
    simulate_damage_from_raw,
)


NO_REPLAY_ERRORS = {"shield": 0, "hull": 0, "mitigated_damage": 0, "remaining_shield": 0, "remaining_hull": 0}


def _row(
    *,
    raw_damage: int = 1000,
    effective_mitigation: float = 0.25,
    shield_damage: int = 500,
    hull_damage: int = 250,
    remaining_shield: int = 0,
    remaining_hull: int = 750,
    critical: bool = False,
    triggered_effects: list[str] | None = None,
    shield_mitigation: float = 1.0,
    battle_type: int = 2,
    cutting_beam_unscaled_damage: int | None = None,
    cutting_beam_player_level: int | None = None,
    cutting_beam_hostile_level: int | None = None,
    include_defender: bool = True,
    attacker_side: str = "hostile",
    mitigated_apex_barrier: int = 0,
    defender_resolved_modifiers: dict[str, float] | None = None,
) -> dict[str, object]:
    observed: dict[str, object] = {
        "hit": True,
        "critical": critical,
        "raw_damage": raw_damage,
        "effective_mitigation": effective_mitigation,
        "normal_mitigation": {
            "raw_damage": raw_damage,
        },
        "isolytic_damage": 1070,
        "mitigated_isolytic_damage": 0,
        "isolytic_damage_model": {
            "base_damage": raw_damage,
            "raw_damage": 1070,
            "observed_damage": 1070,
            "mitigated_damage": 0,
            "damage_multiplier": 1.07,
            "damage_multiplier_percent": 107,
            "effective_mitigation": 0,
            "inferred_base_damage": raw_damage,
            "base_damage_gap": 0,
            "damage_modifier_code": "707",
            "defense_modifier_code": "808",
            "source": "derived_from_battle_log",
        },
        "mitigated_apex_barrier": mitigated_apex_barrier,
        "damage": {
            "shield": shield_damage,
            "hull": hull_damage,
        },
        "remaining": {
            "shield": remaining_shield,
            "hull": remaining_hull,
        },
        "triggered_effects": triggered_effects or [],
    }
    if cutting_beam_unscaled_damage is not None:
        observed["cutting_beam_unscaled_damage"] = cutting_beam_unscaled_damage
    if cutting_beam_player_level is not None:
        observed["cutting_beam_player_level"] = cutting_beam_player_level
    if cutting_beam_hostile_level is not None:
        observed["cutting_beam_hostile_level"] = cutting_beam_hostile_level

    row: dict[str, object] = {
        "battle_type": battle_type,
        "attacker_side": attacker_side,
        "observed": observed,
    }
    if include_defender:
        row["defender"] = {
            "static_ship": {
                "base_stats": {
                    "shield_mitigation": shield_mitigation,
                }
            }
        }
        if defender_resolved_modifiers is not None:
            row["defender"]["resolved_modifiers"] = defender_resolved_modifiers
    return row


class DamageSimulationTests(unittest.TestCase):
    def test_inferrs_pre_shot_state_from_damage_and_remaining_state(self) -> None:
        state = infer_pre_shot_state(_row())

        self.assertEqual({"shield": 500, "hull": 1000}, state)

    def test_simulates_shield_first_damage_from_raw_damage_and_mitigation(self) -> None:
        simulated = simulate_damage_from_raw(_row())

        self.assertEqual(
            {
                "mode",
                "raw_damage",
                "effective_mitigation",
                "shield_mitigation",
                "mitigated_damage",
                "pre_shot",
                "damage",
                "remaining",
                "observed_damage",
                "observed_remaining",
                "errors",
            },
            set(simulated),
        )
        self.assertEqual("standard_iso_apex_shield", simulated["mode"])
        self.assertEqual(750, simulated["mitigated_damage"])
        self.assertEqual({"shield": 500, "hull": 250}, simulated["damage"])
        self.assertEqual({"shield": 0, "hull": 750}, simulated["remaining"])
        self.assertEqual(NO_REPLAY_ERRORS, simulated["errors"])

    def test_simulates_shield_mitigation_split_when_shields_are_active(self) -> None:
        simulated = simulate_damage_from_raw(
            _row(
                shield_damage=600,
                hull_damage=150,
                remaining_shield=400,
                remaining_hull=850,
                shield_mitigation=0.8,
            )
        )

        self.assertEqual(750, simulated["mitigated_damage"])
        self.assertEqual({"shield": 600, "hull": 150}, simulated["damage"])
        self.assertEqual({"shield": 400, "hull": 850}, simulated["remaining"])
        self.assertEqual(NO_REPLAY_ERRORS, simulated["errors"])

    def test_defaults_missing_shield_mitigation_to_full_shield_absorption(self) -> None:
        simulated = simulate_damage_from_raw(
            _row(
                shield_damage=750,
                hull_damage=0,
                remaining_shield=250,
                remaining_hull=1000,
                include_defender=False,
            )
        )

        self.assertEqual(1.0, simulated["shield_mitigation"])
        self.assertEqual(750, simulated["mitigated_damage"])
        self.assertEqual({"shield": 750, "hull": 0}, simulated["damage"])
        self.assertEqual({"shield": 250, "hull": 1000}, simulated["remaining"])
        self.assertEqual(NO_REPLAY_ERRORS, simulated["errors"])

    def test_simulates_cutting_beam_as_direct_hull_damage_without_mitigation(self) -> None:
        simulated = simulate_damage_from_raw(
            _row(
                battle_type=13,
                raw_damage=250,
                effective_mitigation=0.95,
                shield_damage=0,
                hull_damage=250,
                remaining_shield=500,
                remaining_hull=750,
                shield_mitigation=0.8,
            )
        )

        self.assertEqual("cutting_beam_direct_hull", simulated["mode"])
        self.assertEqual(0.0, simulated["effective_mitigation"])
        self.assertEqual(0.0, simulated["shield_mitigation"])
        self.assertEqual(250, simulated["mitigated_damage"])
        self.assertEqual({"shield": 0, "hull": 250}, simulated["damage"])
        self.assertEqual({"shield": 500, "hull": 750}, simulated["remaining"])
        self.assertEqual("observed_scaled_raw_damage", simulated["cutting_beam_damage_source"])
        self.assertEqual(NO_REPLAY_ERRORS, simulated["errors"])

    def test_applies_cutting_beam_level_scaling_when_unscaled_damage_is_available(self) -> None:
        simulated = simulate_damage_from_raw(
            _row(
                battle_type=13,
                raw_damage=800,
                shield_damage=0,
                hull_damage=800,
                remaining_shield=500,
                remaining_hull=200,
                cutting_beam_unscaled_damage=1000,
                cutting_beam_player_level=10,
                cutting_beam_hostile_level=12,
            )
        )

        self.assertEqual(0.8, simulated["cutting_beam_level_scaling"]["multiplier"])
        self.assertEqual(2, simulated["cutting_beam_level_scaling"]["level_delta"])
        self.assertEqual("unscaled_damage_with_level_scale", simulated["cutting_beam_damage_source"])
        self.assertEqual(800, simulated["mitigated_damage"])
        self.assertEqual({"shield": 0, "hull": 800}, simulated["damage"])

    def test_evaluates_observed_mitigation_damage_replay_for_simple_rows(self) -> None:
        rows = [
            _row(),
            _row(critical=True),
            _row(triggered_effects=["isolytic"]),
        ]

        report = evaluate_observed_mitigation_damage_replay(rows)

        self.assertEqual(3, report["rows"])
        self.assertEqual(1, report["simple_rows"])
        self.assertEqual({"count": 1, "mae": 0, "max_abs_error": 0, "bias": 0}, report["simple_metrics"]["shield"])
        self.assertEqual({"count": 1, "mae": 0, "max_abs_error": 0, "bias": 0}, report["simple_metrics"]["hull"])
        self.assertEqual(
            {"critical": 1, "triggered_effects": 1},
            report["excluded_reasons"],
        )

    def test_simulates_isolytic_damage_from_normal_base_damage_and_multiplier(self) -> None:
        simulated = simulate_isolytic_damage(_row())

        self.assertEqual(1000, simulated["base_damage"])
        self.assertEqual(1000, simulated["inferred_base_damage"])
        self.assertEqual(0, simulated["base_damage_gap"])
        self.assertEqual(1.07, simulated["damage_multiplier"])
        self.assertEqual(1070, simulated["raw_damage"])
        self.assertEqual(1070, simulated["damage"])
        self.assertEqual(
            {
                "raw_damage": 0,
                "damage": 0,
                "mitigated_damage": 0,
                "damage_multiplier": 0,
                "effective_mitigation": 0,
            },
            simulated["errors"],
        )

    def test_simulates_isolytic_mitigation_from_defender_808_modifier(self) -> None:
        simulated = simulate_isolytic_damage(
            _row(
                shield_damage=267,
                hull_damage=0,
                remaining_shield=733,
                defender_resolved_modifiers={"808": 3},
            ),
            mitigation_source="resolved_808",
        )

        self.assertEqual("resolved_808", simulated["effective_mitigation_source"])
        self.assertAlmostEqual(0.75, simulated["effective_mitigation"])
        self.assertEqual(268, simulated["damage"])
        self.assertEqual(802, simulated["mitigated_damage"])

    def test_evaluates_observed_isolytic_damage_replay(self) -> None:
        report = evaluate_observed_isolytic_damage_replay(
            [
                _row(),
                _row(triggered_effects=[]),
                _row(triggered_effects=["officer"], defender_resolved_modifiers={"808": 3}),
            ]
        )

        self.assertEqual(3, report["rows"])
        self.assertEqual(3, report["isolytic_rows"])
        self.assertEqual({"count": 3, "min": 107, "max": 107, "mean": 107, "stddev": 0}, report["multiplier_percent"])
        self.assertEqual({"count": 3, "mae": 0, "max_abs_error": 0, "bias": 0}, report["metrics"]["damage"])
        self.assertEqual(3, report["by_source"]["derived_from_battle_log"]["isolytic_rows"])
        self.assertEqual(
            {"count": 3, "mae": 0, "max_abs_error": 0, "bias": 0},
            report["by_source"]["derived_from_battle_log"]["metrics"]["damage"],
        )
        self.assertEqual(1, report["resolved_808_formula"]["isolytic_rows"])
        self.assertEqual(
            {"count": 1, "mae": 802, "max_abs_error": 802, "bias": -802},
            report["resolved_808_formula"]["metrics"]["damage"],
        )
        self.assertEqual(
            {"count": 1, "mae": 0.75, "max_abs_error": 0.75, "bias": 0.75},
            report["resolved_808_formula"]["metrics"]["effective_mitigation"],
        )

    def test_evaluates_observed_apex_barrier_replay_from_resolved_modifier(self) -> None:
        report = evaluate_observed_apex_barrier_replay(
            [
                _row(
                    shield_damage=400,
                    hull_damage=400,
                    remaining_hull=600,
                    mitigated_apex_barrier=200,
                    defender_resolved_modifiers={"67001": 2500},
                ),
                _row(mitigated_apex_barrier=0),
            ]
        )

        self.assertEqual(2, report["rows"])
        self.assertEqual(1, report["apex_rows"])
        self.assertEqual(1, report["rows_with_modeled_barrier"])
        self.assertAlmostEqual(0.2, report["observed_mitigation"]["mean"])
        self.assertEqual(2500, report["required_barrier"]["mean"])
        self.assertEqual({"count": 1, "mae": 0, "max_abs_error": 0, "bias": 0}, report["metrics"]["mitigated_damage"])


if __name__ == "__main__":
    unittest.main()
