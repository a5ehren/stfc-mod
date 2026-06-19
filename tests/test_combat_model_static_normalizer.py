from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.static_normalizer import build_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StaticNormalizerTests(unittest.TestCase):
    def test_builds_minimal_fixture_from_decoded_static_and_battle_journal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            decoded.mkdir()
            (decoded / "BattleConfig.json").write_text(
                json.dumps({"battleConfig": {"static": {"base_mitigation": 0.125}, "equations": {}}}),
                encoding="utf-8",
            )
            battle = root / "battle.json"
            battle.write_text(
                json.dumps(
                    {
                        "journal": {
                            "game_version": "1.000.48902",
                            "initial_state": {
                                "player": {"hull": 10000, "shield": 5000},
                                "hostile": {"hull": 8000, "shield": 3000},
                            },
                            "rounds": [
                                {
                                    "round": 1,
                                    "acting_side": "player",
                                    "action": "kinetic",
                                    "raw_damage": 4000,
                                    "expected": {"shield": 3000, "hull": 500},
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            fixture = build_fixture(decoded_static_dir=decoded, battle_journal_path=battle)

        self.assertEqual("1.000.48902", fixture["game_version"])
        self.assertEqual(0.125, fixture["rounds"][0]["mitigation"])
        self.assertEqual("decoded/BattleConfig.json", fixture["source_payloads"][0]["path"])

    def test_cli_build_fixture_writes_normalized_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            decoded.mkdir()
            (decoded / "BattleConfig.json").write_text(
                json.dumps({"battleConfig": {"static": {"base_mitigation": 0.25}, "equations": {}}}),
                encoding="utf-8",
            )
            battle = root / "battle.json"
            battle.write_text(
                json.dumps(
                    {
                        "journal": {
                            "game_version": "1.000.48902",
                            "initial_state": {
                                "player": {"hull": 10000, "shield": 5000},
                                "hostile": {"hull": 8000, "shield": 3000},
                            },
                            "rounds": [
                                {
                                    "round": 1,
                                    "acting_side": "player",
                                    "action": "kinetic",
                                    "raw_damage": 4000,
                                    "expected": {"shield": 3000, "hull": 0},
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            out_path = root / "fixtures" / "sample.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "build-fixture",
                    "--decoded-static-dir",
                    str(decoded),
                    "--battle-journal",
                    str(battle),
                    "--out",
                    str(out_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            fixture = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(0.25, fixture["rounds"][0]["mitigation"])

    def test_builds_fixture_from_raw_battle_log_marker_stream(self) -> None:
        player_ship_id = 1111
        hostile_ship_id = 0

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            decoded.mkdir()
            (decoded / "BattleConfig.json").write_text(
                json.dumps({"battleConfig": {"combatLengthSeconds": 5}}),
                encoding="utf-8",
            )
            battle = root / "battle.json"
            battle.write_text(
                json.dumps(
                    {
                        "server_version": "v15-29-0",
                        "journal": {
                            "initiator_fleet_data": {
                                "deployed_fleet": {
                                    "ship_ids": [player_ship_id],
                                    "ship_hps": {str(player_ship_id): 100},
                                    "ship_shield_hps": {str(player_ship_id): 200},
                                }
                            },
                            "target_fleet_data": {
                                "deployed_fleet": {
                                    "ship_ids": [hostile_ship_id],
                                    "ship_hps": {str(hostile_ship_id): 80},
                                    "ship_shield_hps": {str(hostile_ship_id): 120},
                                }
                            },
                            "battle_log": [
                                -96,
                                -90,
                                hostile_ship_id,
                                -98,
                                4444,
                                player_ship_id,
                                1.0,
                                0.0,
                                1,
                                0,
                                10,
                                90,
                                20,
                                180,
                                5,
                                0,
                                0,
                                0,
                                0,
                                0,
                                -99,
                                player_ship_id,
                                -98,
                                5555,
                                hostile_ship_id,
                                1.0,
                                0.0,
                                1,
                                1,
                                30,
                                50,
                                40,
                                80,
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

            fixture = build_fixture(decoded_static_dir=decoded, battle_journal_path=battle)

        self.assertEqual("v15-29-0", fixture["game_version"])
        self.assertEqual({"hull": 100, "shield": 200}, fixture["initial_state"]["player"])
        self.assertEqual({"hull": 80, "shield": 120}, fixture["initial_state"]["hostile"])
        self.assertEqual("hostile", fixture["rounds"][0]["acting_side"])
        self.assertEqual("weapon:4444", fixture["rounds"][0]["action"])
        self.assertEqual(35, fixture["rounds"][0]["raw_damage"])
        self.assertAlmostEqual(5 / 35, fixture["rounds"][0]["mitigation"])
        self.assertEqual({"shield": 20, "hull": 10}, fixture["rounds"][0]["expected"])
        self.assertEqual("player", fixture["rounds"][1]["acting_side"])
        self.assertIn("critical", fixture["rounds"][1]["triggered_effects"])


if __name__ == "__main__":
    unittest.main()
