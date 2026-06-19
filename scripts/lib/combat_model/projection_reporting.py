from __future__ import annotations

import json
from typing import Any


def render_projection_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_projection_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    metadata = report.get("metadata", {})
    lines = [
        "# Combat Projection Report",
        "",
        f"Mode: `{metadata.get('mode')}`",
        f"Battles: {summary.get('battle_count', 0)}",
        f"Projected attacks: {summary.get('attack_count', 0)}",
        f"Observed attacks: {summary.get('observed_attack_count', 0)}",
        f"Damage MAE: {summary.get('damage_mae', 0)}",
        f"Final state MAE: {summary.get('final_state_mae', 0)}",
        f"Weapon sequence mismatch rate: {summary.get('weapon_sequence_mismatch_rate', 0)}",
        f"Outcome match rate: {summary.get('outcome_match_rate', 0)}",
        "",
        "## By Battle Class",
        "",
    ]
    by_class = report.get("by_battle_class", {})
    if not by_class:
        lines.append("No battles projected.")
    else:
        for battle_class, metrics in sorted(by_class.items()):
            lines.append(
                "- "
                f"`{battle_class}`: battles={metrics.get('battle_count', 0)}, "
                f"attacks={metrics.get('attack_count', 0)}, "
                f"damage_mae={metrics.get('damage_mae', 0)}, "
                f"sequence_mismatch_rate={metrics.get('weapon_sequence_mismatch_rate', 0)}"
            )
    lines.extend(["", "## Worst Battle Damage Error", ""])
    battles = sorted(
        report.get("battles", []),
        key=lambda battle: float(battle.get("metrics", {}).get("damage_mae", 0)),
        reverse=True,
    )
    if not battles:
        lines.append("No battle details.")
    else:
        for battle in battles[:10]:
            metrics = battle.get("metrics", {})
            lines.append(
                "- "
                f"`{battle.get('battle_id')}` ({battle.get('battle_class')}): "
                f"damage_mae={metrics.get('damage_mae', 0)}, "
                f"sequence_mismatches={metrics.get('weapon_sequence_mismatches', 0)}, "
                f"outcome_match={'yes' if battle.get('outcome_match') else 'no'}"
            )
    lines.append("")
    return "\n".join(lines)
