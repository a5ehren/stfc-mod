from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.apex_sources import build_apex_source_index, evaluate_apex_source_candidates


class ApexSourceTests(unittest.TestCase):
    def test_builds_active_global_apex_source_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td)
            (decoded / "GlobalActiveBuffs.json").write_text(
                json.dumps(
                    {
                        "globalActiveBuffs": [
                            {"buffId": "safe-research", "level": 1},
                            {"buffId": "conditional-starbase", "level": 2},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (decoded / "ResearchSpecs.json").write_text(
                json.dumps(
                    {
                        "researchEffects": {
                            "safe-research": {
                                "modifierCode": "67001",
                                "targetCode": 1,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_ADD",
                                "rankedValues": [100],
                                "conditionCodes": ["28", "137"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (decoded / "StarbaseBuffs.json").write_text(
                json.dumps(
                    {
                        "starbaseBuffsSpecs": {
                            "conditional-starbase": {
                                "modifierCode": "67001",
                                "targetCode": 1,
                                "triggerCode": 25,
                                "op": "BUFFOPERATION_ADD",
                                "rankedValues": [2000, 5000],
                                "conditionCodes": ["28", "137", "246"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            index = build_apex_source_index(decoded)

        self.assertEqual(2, index["active_global_apex_count"])
        by_id = {row["buff_id"]: row for row in index["active_global_candidates"]}
        self.assertEqual("supported_global_profile_research", by_id["safe-research"]["condition_status"])
        self.assertEqual("requires_condition_evaluator", by_id["conditional-starbase"]["condition_status"])
        self.assertEqual(100, by_id["safe-research"]["delta"])
        self.assertEqual(5000, by_id["conditional-starbase"]["delta"])

    def test_evaluates_candidate_barriers_against_observed_apex(self) -> None:
        index = {
            "static_apex_spec_count": 2,
            "active_global_apex_count": 2,
            "active_global_candidates": [
                {
                    "buff_id": "safe-research",
                    "source_type": "research",
                    "delta": 100,
                    "delta_status": "applied",
                    "condition_status": "supported_global_profile_research",
                },
                {
                    "buff_id": "conditional-starbase",
                    "source_type": "starbase",
                    "delta": 5000,
                    "delta_status": "applied",
                    "condition_status": "requires_condition_evaluator",
                },
            ],
        }
        row = {
            "defender": {"status_effects": {"22": 1234}},
            "observed": {
                "damage": {"shield": 10000, "hull": 0},
                "mitigated_apex_barrier": 200,
                "forbidden_tech_activations": [
                    {"modifierCode": "67001", "op": "BUFFOPERATION_ADD", "value": 200},
                ],
            }
        }

        report = evaluate_apex_source_candidates([row], index)

        self.assertEqual(
            {"requires_condition_evaluator": 1, "supported_global_profile_research": 1},
            report["active_global_condition_status_counts"],
        )
        self.assertEqual(
            {"count": 1, "mae": 100, "max_abs_error": 100, "bias": -100},
            report["candidate_metrics"]["active_global_safe_research"]["metrics"],
        )
        self.assertEqual(
            {"count": 1, "mae": 0, "max_abs_error": 0, "bias": 0},
            report["candidate_metrics"]["battle_forbidden_tech"]["metrics"],
        )
        self.assertEqual(
            {"count": 1, "min": 200, "max": 200, "mean": 200, "stddev": 0},
            report["required_barrier_by_defender_status"]["22"],
        )


if __name__ == "__main__":
    unittest.main()
