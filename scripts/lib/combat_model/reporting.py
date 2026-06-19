from __future__ import annotations

import json

from .compare import ReplayComparison


def render_markdown_report(fixture_name: str, comparison: ReplayComparison) -> str:
    lines = [
        f"# Combat Replay Report: {fixture_name}",
        "",
        f"Passed: {'yes' if comparison.passed else 'no'}",
        "",
        "## Mismatches",
        "",
    ]
    if not comparison.mismatches:
        lines.append("No mismatches.")
    else:
        for mismatch in comparison.mismatches:
            lines.append(f"- Round {mismatch.round_number}: `{mismatch.kind}` - {mismatch.message}")
    lines.append("")
    return "\n".join(lines)


def render_json_report(comparison: ReplayComparison) -> str:
    return json.dumps(comparison.to_dict(), indent=2, sort_keys=True) + "\n"
