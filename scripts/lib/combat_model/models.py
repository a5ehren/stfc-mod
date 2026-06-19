from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Side = Literal["player", "hostile"]


@dataclass(frozen=True, slots=True)
class ReplayThreshold:
    """Damage tolerance for round replay comparison."""

    max_relative_delta: float

    @classmethod
    def mvp(cls) -> "ReplayThreshold":
        return cls(max_relative_delta=0.20)

    @classmethod
    def release(cls) -> "ReplayThreshold":
        return cls(max_relative_delta=0.10)

    def damage_within_limit(self, *, expected: int, actual: int) -> bool:
        if expected == 0:
            return actual == 0
        delta = abs(actual - expected) / abs(expected)
        return delta <= self.max_relative_delta


@dataclass(frozen=True, slots=True)
class CombatState:
    hull: int
    shield: int

    def to_dict(self) -> dict[str, int]:
        return {"hull": self.hull, "shield": self.shield}


@dataclass(frozen=True, slots=True)
class DamageBreakdown:
    raw: int
    mitigated: int
    shield: int
    hull: int

    def to_dict(self) -> dict[str, int]:
        return {
            "raw": self.raw,
            "mitigated": self.mitigated,
            "shield": self.shield,
            "hull": self.hull,
        }


@dataclass(frozen=True, slots=True)
class RoundTrace:
    round_number: int
    acting_side: Side
    action: str
    attacker: CombatState
    defender_before: CombatState
    defender_after: CombatState
    damage: DamageBreakdown
    triggered_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_number,
            "acting_side": self.acting_side,
            "action": self.action,
            "attacker": self.attacker.to_dict(),
            "defender_before": self.defender_before.to_dict(),
            "defender_after": self.defender_after.to_dict(),
            "damage": self.damage.to_dict(),
            "triggered_effects": list(self.triggered_effects),
        }
