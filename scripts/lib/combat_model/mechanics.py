from __future__ import annotations

from typing import Any

HULL_ARMADA = "HULLTYPE_ARMADATARGET"
HULL_BATTLESHIP = "HULLTYPE_BATTLESHIP"
HULL_EXPLORER = "HULLTYPE_EXPLORER"
HULL_INTERCEPTOR = "HULLTYPE_INTERCEPTOR"
HULL_DESTROYER = "HULLTYPE_DESTROYER"
HULL_SURVEY = "HULLTYPE_SURVEY"

_WEIGHTS = {
    HULL_ARMADA: {"armor": 0.3, "shield": 0.3, "dodge": 0.3},
    HULL_BATTLESHIP: {"armor": 0.55, "shield": 0.2, "dodge": 0.2},
    HULL_EXPLORER: {"armor": 0.2, "shield": 0.55, "dodge": 0.2},
    HULL_INTERCEPTOR: {"armor": 0.2, "shield": 0.2, "dodge": 0.55},
    HULL_DESTROYER: {"armor": 0.2, "shield": 0.2, "dodge": 0.55},
    HULL_SURVEY: {"armor": 0.3, "shield": 0.3, "dodge": 0.3},
}


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def mitigation_component(defense_value: Any, piercing_value: Any) -> float:
    piercing = max(0.0, _number(piercing_value))
    if piercing == 0:
        return 0.0
    return 1.0 / (1.0 + 4.0 ** (1.1 - _number(defense_value) / piercing))


def weights_for(defender_hull_type: str) -> dict[str, float]:
    return dict(_WEIGHTS.get(defender_hull_type, _WEIGHTS[HULL_SURVEY]))


def combat_triangle_mitigation(
    *,
    armor: Any,
    shield: Any,
    dodge: Any,
    armor_piercing: Any,
    shield_piercing: Any,
    accuracy: Any,
    defender_hull_type: str,
) -> float:
    weights = weights_for(defender_hull_type)
    components = {
        "armor": mitigation_component(armor, armor_piercing),
        "shield": mitigation_component(shield, shield_piercing),
        "dodge": mitigation_component(dodge, accuracy),
    }
    unmitigated = 1.0
    for key in ("armor", "shield", "dodge"):
        unmitigated *= 1.0 - weights[key] * components[key]
    return max(0.0, min(1.0, 1.0 - unmitigated))


def isolytic_damage(*, regular_after_modifiers: Any, isolytic_bonus: Any, cascade_bonus: Any) -> int:
    base = _number(regular_after_modifiers)
    bonus = _number(isolytic_bonus)
    cascade = _number(cascade_bonus)
    return int(round(base * (bonus + (1.0 + bonus) * cascade)))


def isolytic_mitigation(*, isolytic_defense: Any) -> float:
    return 1.0 / (1.0 + _number(isolytic_defense))


def apex_barrier_damage_reduction(*, apex_barrier: Any, apex_shred: Any) -> float:
    return 10000.0 / (10000.0 + _number(apex_barrier) / (1.0 + _number(apex_shred)))


def apply_shield_allocation(
    *,
    total_unmitigated_damage: Any,
    shield_mitigation: Any,
    shield_before: Any,
) -> dict[str, int]:
    total = max(0.0, _number(total_unmitigated_damage))
    shield_available = max(0.0, _number(shield_before))
    shield_damage = min(shield_available, int(total * max(0.0, min(1.0, _number(shield_mitigation)))))
    hull_damage = max(0, int(round(total - shield_damage)))
    return {
        "shield": int(shield_damage),
        "hull": hull_damage,
        "remaining_shield": int(max(0.0, shield_available - shield_damage)),
    }


def round_shots(value: Any) -> int:
    return int(round(_number(value)))
