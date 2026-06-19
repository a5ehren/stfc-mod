from __future__ import annotations

from typing import Any

from .models import CombatState, DamageBreakdown, RoundTrace, Side


def _state(data: dict[str, Any]) -> CombatState:
    return CombatState(hull=int(data["hull"]), shield=int(data["shield"]))


def _apply_damage(defender: CombatState, mitigated_damage: int) -> tuple[CombatState, int, int]:
    shield_damage = min(defender.shield, mitigated_damage)
    hull_damage = max(0, mitigated_damage - shield_damage)
    return (
        CombatState(hull=max(0, defender.hull - hull_damage), shield=defender.shield - shield_damage),
        shield_damage,
        hull_damage,
    )


def replay_fixture(fixture: dict[str, Any]) -> list[RoundTrace]:
    player = _state(fixture["initial_state"]["player"])
    hostile = _state(fixture["initial_state"]["hostile"])
    traces: list[RoundTrace] = []

    for round_data in fixture["rounds"]:
        acting_side: Side = round_data["acting_side"]
        attacker = player if acting_side == "player" else hostile
        defender_before = hostile if acting_side == "player" else player
        raw = int(round_data["raw_damage"])
        mitigated = int(round(raw * (1 - float(round_data["mitigation"]))))
        defender_after, shield_damage, hull_damage = _apply_damage(defender_before, mitigated)

        if acting_side == "player":
            hostile = defender_after
        else:
            player = defender_after

        traces.append(
            RoundTrace(
                round_number=int(round_data["round"]),
                acting_side=acting_side,
                action=round_data["action"],
                attacker=attacker,
                defender_before=defender_before,
                defender_after=defender_after,
                damage=DamageBreakdown(
                    raw=raw,
                    mitigated=mitigated,
                    shield=shield_damage,
                    hull=hull_damage,
                ),
                triggered_effects=list(round_data.get("triggered_effects", [])),
            )
        )

    return traces


def expected_trace_from_fixture(fixture: dict[str, Any]) -> list[RoundTrace]:
    player = _state(fixture["initial_state"]["player"])
    hostile = _state(fixture["initial_state"]["hostile"])
    traces: list[RoundTrace] = []

    for round_data in fixture["rounds"]:
        acting_side: Side = round_data["acting_side"]
        attacker = player if acting_side == "player" else hostile
        defender_before = hostile if acting_side == "player" else player
        expected = round_data["expected"]
        shield_damage = int(expected["shield"])
        hull_damage = int(expected["hull"])
        mitigated = shield_damage + hull_damage
        defender_after = CombatState(
            hull=max(0, defender_before.hull - hull_damage),
            shield=max(0, defender_before.shield - shield_damage),
        )

        if acting_side == "player":
            hostile = defender_after
        else:
            player = defender_after

        traces.append(
            RoundTrace(
                round_number=int(round_data["round"]),
                acting_side=acting_side,
                action=round_data["action"],
                attacker=attacker,
                defender_before=defender_before,
                defender_after=defender_after,
                damage=DamageBreakdown(
                    raw=int(round_data["raw_damage"]),
                    mitigated=mitigated,
                    shield=shield_damage,
                    hull=hull_damage,
                ),
                triggered_effects=list(round_data.get("expected_triggered_effects", ["journal"])),
            )
        )

    return traces
