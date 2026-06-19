from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.replay import expected_trace_from_fixture, replay_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fixture() -> dict[str, object]:
    return {
        "schema_version": 1,
        "game_version": "1.000.48902",
        "source_payloads": [{"kind": "battle_journal", "path": "battle.json"}],
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
                "mitigation": 0.125,
                "expected": {"shield": 3000, "hull": 500},
            }
        ],
    }


class CombatModelReplayTests(unittest.TestCase):
    def test_replays_damage_into_shield_then_hull(self) -> None:
        trace = replay_fixture(_fixture())

        self.assertEqual(trace[0].damage.shield, 3000)
        self.assertEqual(trace[0].damage.hull, 500)
        self.assertEqual(trace[0].defender_after.hull, 7500)
        self.assertEqual(trace[0].defender_after.shield, 0)

    def test_replay_reports_overkill_hull_damage(self) -> None:
        fixture = _fixture()
        fixture["initial_state"] = {
            "player": {"hull": 10000, "shield": 5000},
            "hostile": {"hull": 1000, "shield": 500},
        }
        fixture["rounds"] = [
            {
                "round": 1,
                "acting_side": "player",
                "action": "kinetic",
                "raw_damage": 4000,
                "mitigation": 0.0,
                "expected": {"shield": 500, "hull": 3500},
            }
        ]

        trace = replay_fixture(fixture)

        self.assertEqual(trace[0].damage.shield, 500)
        self.assertEqual(trace[0].damage.hull, 3500)
        self.assertEqual(trace[0].defender_after.hull, 0)
        self.assertEqual(trace[0].defender_after.shield, 0)

    def test_expected_trace_uses_battle_journal_values(self) -> None:
        trace = expected_trace_from_fixture(_fixture())

        self.assertEqual(trace[0].damage.mitigated, 3500)
        self.assertEqual(trace[0].triggered_effects, ["journal"])

    def test_cli_report_writes_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture_path = Path(temp_dir) / "fixture.json"
            out_dir = Path(temp_dir) / "reports"
            fixture_path.write_text(json.dumps(_fixture()), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "combat-model.py"),
                    "report",
                    str(fixture_path),
                    "--out-dir",
                    str(out_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            markdown_path = out_dir / "fixture.md"
            json_path = out_dir / "fixture.json"

            self.assertEqual(result.returncode, 2)
            self.assertTrue(markdown_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("# Combat Replay Report:", markdown_path.read_text(encoding="utf-8"))
            self.assertFalse(json.loads(json_path.read_text(encoding="utf-8"))["passed"])


if __name__ == "__main__":
    unittest.main()
