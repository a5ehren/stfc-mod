from __future__ import annotations

from dataclasses import dataclass, field

from .models import ReplayThreshold, RoundTrace


@dataclass(frozen=True, slots=True)
class ReplayMismatch:
    round_number: int
    kind: str
    message: str

    def to_dict(self) -> dict[str, int | str]:
        return {"round": self.round_number, "kind": self.kind, "message": self.message}


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    passed: bool
    mismatches: list[ReplayMismatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "mismatches": [m.to_dict() for m in self.mismatches]}


def compare_traces(
    *,
    expected: list[RoundTrace],
    actual: list[RoundTrace],
    threshold: ReplayThreshold,
) -> ReplayComparison:
    mismatches: list[ReplayMismatch] = []

    if len(expected) != len(actual):
        mismatches.append(
            ReplayMismatch(
                round_number=0,
                kind="round_count_mismatch",
                message=f"expected {len(expected)} rounds, got {len(actual)} rounds",
            )
        )

    for expected_round, actual_round in zip(expected, actual, strict=False):
        if expected_round.round_number != actual_round.round_number:
            mismatches.append(
                ReplayMismatch(
                    round_number=expected_round.round_number,
                    kind="ordering_mismatch",
                    message=f"expected round {expected_round.round_number}, got {actual_round.round_number}",
                )
            )
            continue

        expected_damage = expected_round.damage.shield + expected_round.damage.hull
        actual_damage = actual_round.damage.shield + actual_round.damage.hull
        if not threshold.damage_within_limit(expected=expected_damage, actual=actual_damage):
            mismatches.append(
                ReplayMismatch(
                    round_number=expected_round.round_number,
                    kind="damage_delta",
                    message=f"expected damage {expected_damage}, got {actual_damage}",
                )
            )

        if expected_round.triggered_effects != actual_round.triggered_effects:
            mismatches.append(
                ReplayMismatch(
                    round_number=expected_round.round_number,
                    kind="trigger_mismatch",
                    message=(
                        "expected triggers "
                        f"{expected_round.triggered_effects}, got {actual_round.triggered_effects}"
                    ),
                )
            )

    return ReplayComparison(passed=not mismatches, mismatches=mismatches)
