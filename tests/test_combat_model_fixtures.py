from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.fixtures import FixtureError, load_fixture


class CombatModelFixtureTests(unittest.TestCase):
    def test_load_fixture_returns_normalized_fixture(self) -> None:
        fixture_data = {
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
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.json"
            path.write_text(json.dumps(fixture_data), encoding="utf-8")

            fixture = load_fixture(path)

        self.assertEqual(fixture["game_version"], "1.000.48902")
        self.assertEqual(fixture["rounds"][0]["round"], 1)

    def test_load_fixture_reports_missing_required_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture.json"
            path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

            with self.assertRaisesRegex(FixtureError, "missing required fixture key: game_version"):
                load_fixture(path)


if __name__ == "__main__":
    unittest.main()
