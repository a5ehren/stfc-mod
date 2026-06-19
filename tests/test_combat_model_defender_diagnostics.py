from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.defender_diagnostics import build_defender_diagnostics


def _row(
    *,
    battle_id: str,
    attacker_side: str = "hostile",
    hull_name: str = "Player Hull",
    hull_id: str = "player-hull",
) -> dict[str, object]:
    defender_side = "player" if attacker_side == "hostile" else "hostile"
    return {
        "battle_id": battle_id,
        "battle_type": 2,
        "battle_type_name": "PASSIVE_MARAUDER",
        "player_battle_data_type": 0,
        "hostile_battle_data_type": 0,
        "attacker_side": attacker_side,
        "defender_side": defender_side,
        "weapon": {
            "accuracy": 100,
            "penetration": 100,
            "modulation": 100,
        },
        "attacker": {
            "captured_stats": {"6": 100, "7": 100, "8": 100},
            "static_ship": {
                "base_stats": {
                    "weapon_accuracy_max": 100,
                    "weapon_penetration_max": 100,
                    "weapon_modulation_max": 100,
                },
                "hull": {"name": "Hostile Hull", "id": "hostile-hull", "type": "HULLTYPE_EXPLORER"},
            },
        },
        "defender": {
            "captured_stats": {"11": 100, "-3": 100, "-2": 100},
            "resolved_modifiers": {"11": 1.0, "12": 1.0, "13": 1.0, "73": 1.0},
            "static_ship": {
                "base_stats": {
                    "dodge": 100,
                    "armor_plating": 100,
                    "shield_absorption": 100,
                },
                "hull": {
                    "name": hull_name,
                    "id": hull_id,
                    "type": "HULLTYPE_EXPLORER",
                    "core_stat_modifiers": [],
                },
            },
        },
        "observed": {
            "hit": True,
            "critical": False,
            "damage": {"shield": 500, "hull": 0},
            "remaining": {"shield": 500, "hull": 1000},
            "normal_mitigation": {
                "raw_damage": 1000,
                "observed_damage": 500,
                "mitigated_damage": 500,
                "effective_mitigation": 0.5,
            },
            "triggered_effects": [],
        },
    }


class DefenderDiagnosticsTests(unittest.TestCase):
    def test_builds_hostile_shot_player_defender_report(self) -> None:
        rows = [
            _row(battle_id="1", hull_name="Player Hull"),
            _row(battle_id="2", hull_name="Player Hull"),
            _row(battle_id="3", attacker_side="player", hull_name="Player Hull"),
        ]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            report = build_defender_diagnostics(observations_path=path, min_group_count=1)

        self.assertEqual("usable hostile-shot rows where player is defender", report["scope"])
        self.assertEqual(2, report["hostile_shot_rows"])
        self.assertEqual(1, report["player_shot_rows"])
        self.assertIn("weighted_product", report["composition_metrics"])
        self.assertEqual("Player Hull:player-hull", report["by_player_hull"][0]["key"])
        self.assertEqual(2, report["by_player_hull"][0]["count"])
        self.assertEqual("unknown", report["by_hostile_id"][0]["key"])
        self.assertIn("armor", report["by_player_hull"][0]["component_means"])
        self.assertIn(
            "HULLTYPE_EXPLORER",
            [row["hull_type"] for row in report["by_player_hull"][0]["hull_type_sensitivity"]],
        )
        self.assertEqual(2, report["clean_specialty_calibration"]["hostile_shot_rows"])
        self.assertEqual("Player Hull:player-hull", report["clean_specialty_calibration"]["by_player_hull"][0]["key"])

    def test_clean_specialty_scope_excludes_newton_crew_data(self) -> None:
        rows = [
            _row(battle_id="1", hull_name="Newton_LIVE", hull_id="2057434885"),
            _row(battle_id="2", hull_name="Monaveen", hull_id="49906243"),
        ]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observations.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            report = build_defender_diagnostics(observations_path=path, min_group_count=1)

        self.assertEqual(2, report["hostile_shot_rows"])
        clean = report["clean_specialty_calibration"]
        self.assertEqual(1, clean["hostile_shot_rows"])
        self.assertEqual([{"player_hull_id": "2057434885", "player_hull_name": "Newton_LIVE"}], clean["excluded_player_hulls"])
        self.assertEqual("Monaveen:49906243", clean["by_player_hull"][0]["key"])


if __name__ == "__main__":
    unittest.main()
