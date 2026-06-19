from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mitigation_analysis import _predict_sparse_linear_model, _synced_linear_features
from .mitigation_formula import predict_combat_triangle_mitigation


MODEL_NAME = "combat_triangle_synced_linear_formula"
BASE_FORMULA = "combat_triangle_static_player_max_buffs_formula"


def _base_prediction(row: dict[str, Any]) -> float:
    return predict_combat_triangle_mitigation(
        row,
        stat_source="static_player_max_buffs",
        include_apex_barrier=False,
    )


def _model_from_report(report: dict[str, Any]) -> dict[str, Any]:
    candidates = (
        report.get("broad_formula_goal", {})
        .get("candidate_metrics", {})
    )
    model = candidates.get(MODEL_NAME, {}).get("model")
    if not isinstance(model, dict):
        raise ValueError(f"mitigation analysis report does not contain {MODEL_NAME} model")
    return model


@dataclass(frozen=True, slots=True)
class SyncedLinearMitigationModel:
    model: dict[str, Any]
    model_source: str
    model_name: str = MODEL_NAME

    def predict(self, row: dict[str, Any]) -> float:
        attacker_hulls = tuple(str(value) for value in self.model.get("attacker_hull_labels", []))
        defender_hulls = tuple(str(value) for value in self.model.get("defender_hull_labels", []))

        def feature_fn(feature_row: dict[str, Any]) -> dict[str, float]:
            return _synced_linear_features(
                feature_row,
                base_predict=_base_prediction,
                attacker_hulls=attacker_hulls,
                defender_hulls=defender_hulls,
            )

        return _predict_sparse_linear_model(row, model=self.model, feature_fn=feature_fn)

    def metadata(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_source": self.model_source,
            "formula": self.model.get("formula"),
            "base_formula": self.model.get("base_formula", BASE_FORMULA),
            "feature_count": len(self.model.get("features", [])),
            "coefficient_count": len(self.model.get("coefficients", {})),
        }


def load_synced_linear_mitigation_model(path: Path) -> SyncedLinearMitigationModel:
    report = json.loads(path.read_text(encoding="utf-8"))
    return SyncedLinearMitigationModel(
        model=_model_from_report(report),
        model_source=str(path),
    )
