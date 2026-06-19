from __future__ import annotations

import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .damage_pipeline import predict_damage_from_stages, weapon_damage_diagnostics
from .mechanics import apex_barrier_damage_reduction, isolytic_damage, isolytic_mitigation
from .mitigation_analysis import _battle_formula_class
from .mitigation_targets import isolytic_damage_model_from_observed
from .special_attacks import (
    CHAIN_SHOT_DAMAGE_MODIFIER_CODE,
    CHAIN_SHOT_SECONDARY_MODIFIER_CODE,
    is_chain_shot_attack,
    observed_normal_raw_damage,
)


WAVE_DEFENSE_DAMAGE_MODIFIER_CODE = "88"
WAVE_DEFENSE_PLAYER_ISOLYTIC_MULTIPLIERS = {
    "Junker": 2.748,
    "Newton_LIVE": 1.248,
}
WAVE_DEFENSE_PLAYER_DEFENDER_MITIGATION_SURFACE = {
    ("Junker", "Hull_L28_Destroyer_Klg_WaveDefense"): 0.712,
    ("Junker", "Hull_L30_Destroyer_Klg_WaveDefense"): 0.711999,
    ("Junker", "Hull_L32_Destroyer_Klg_WaveDefense"): 0.712,
    ("Junker", "Hull_L35_Destroyer_Klg_WaveDefense"): 0.712,
    ("Junker", "Hull_L38_Destroyer_Klg_WaveDefense"): 0.711993,
    ("Junker", "Hull_L40_Destroyer_Klg_WaveDefense"): 0.711929,
    ("Junker", "Hull_L42_Destroyer_Klg_WaveDefense"): 0.710615,
    ("Junker", "Hull_L45_Destroyer_Klg_WaveDefense"): 0.701457,
    ("Junker", "Hull_L48_Destroyer_Klg_WaveDefense"): 0.6879,
    ("Newton_LIVE", "Hull_L28_Destroyer_Klg_WaveDefense"): 0.688794,
    ("Newton_LIVE", "Hull_L30_Destroyer_Klg_WaveDefense"): 0.671238,
    ("Newton_LIVE", "Hull_L32_Destroyer_Klg_WaveDefense"): 0.654901,
    ("Newton_LIVE", "Hull_L35_Destroyer_Klg_WaveDefense"): 0.626029,
    ("Newton_LIVE", "Hull_L38_Destroyer_Klg_WaveDefense"): 0.500588,
    ("Newton_LIVE", "Hull_L40_Destroyer_Klg_WaveDefense"): 0.431387,
    ("Newton_LIVE", "Hull_L42_Battleship_Rom_WaveDefense"): 0.539462,
    ("Newton_LIVE", "Hull_L42_Destroyer_Klg_WaveDefense"): 0.334244,
    ("Newton_LIVE", "Hull_L45_Destroyer_Klg_WaveDefense"): 0.256346,
    ("Newton_LIVE", "Hull_L48_Destroyer_Klg_WaveDefense"): 0.223135,
}
STANDARD_HOSTILE_PLAYER_RAW_DAMAGE_SCALE = 1.5
STANDARD_HOSTILE_HOSTILE_RAW_DAMAGE_SCALE = 1.1
STANDARD_HOSTILE_PLAYER_DEFENDER_APEX_SURFACE = {
    "Junker": 0.1,
    "Monaveen": 0.014778,
    "USS Titan-A": 0.014778,
}
WAVE_DEFENSE_PLAYER_RAW_DAMAGE_SCALE = 1.12
WAVE_DEFENSE_PLAYER_CRITICAL_RAW_DAMAGE_SCALE = 1.1
WAVE_DEFENSE_JUNKER_APEX_MITIGATION = 0.10314
WAVE_DEFENSE_NEWTON_APEX_MITIGATION = 0.01478
WAVE_DEFENSE_NEWTON_BATTLESHIP_APEX_MITIGATION = 0.11894
PVE_HOSTILE_DAMAGE_CLASSES = {"standard_hostile", "wave_defense"}
PVE_HOSTILE_RAW_DAMAGE_SCALE = 0.692
PVE_HOSTILE_CRIT_MODIFIER_CAP = 1.5


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _report_number(value: float) -> int | float:
    if abs(value) < 1e-9:
        return 0
    return int(value) if value.is_integer() else value


def _round_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(round(_number(value)))


def _sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
    return (
        _round_int(row.get("battle_round")),
        _round_int(row.get("sub_round")),
        _round_int(row.get("attack_index")),
    )


def _observed(row: dict[str, Any]) -> dict[str, Any]:
    observed = row.get("observed", {})
    return observed if isinstance(observed, dict) else {}


def _damage(observed: dict[str, Any]) -> dict[str, Any]:
    damage = observed.get("damage", {})
    return damage if isinstance(damage, dict) else {}


def _remaining(observed: dict[str, Any]) -> dict[str, Any]:
    remaining = observed.get("remaining", {})
    return remaining if isinstance(remaining, dict) else {}


def _ship_state(ship: dict[str, Any]) -> dict[str, int | float]:
    captured_stats = ship.get("captured_stats", {})
    static_ship = ship.get("static_ship", {})
    base_stats = static_ship.get("base_stats", {}) if isinstance(static_ship, dict) else {}
    hull = None
    shield = None
    if isinstance(captured_stats, dict):
        hull = captured_stats.get("61")
        shield = captured_stats.get("60")
    if isinstance(base_stats, dict):
        hull = hull if hull is not None else base_stats.get("hull_hp")
        shield = shield if shield is not None else base_stats.get("shield_hp")
    return {
        "shield": _report_number(_number(shield)),
        "hull": _report_number(_number(hull)),
    }


def _observed_pre_shot_state(row: dict[str, Any]) -> dict[str, int | float]:
    observed = _observed(row)
    damage = _damage(observed)
    remaining = _remaining(observed)
    return {
        "shield": _report_number(_number(damage.get("shield")) + _number(remaining.get("shield"))),
        "hull": _report_number(_number(damage.get("hull")) + _number(remaining.get("hull"))),
    }


def _ship_by_side(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ships: dict[str, dict[str, Any]] = {}
    for row in rows:
        for role in ("attacker", "defender"):
            side = row.get(f"{role}_side")
            ship = row.get(role, {})
            if isinstance(side, str) and side and isinstance(ship, dict) and side not in ships:
                ships[side] = ship
    return ships


def _initial_states(rows: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    ships = _ship_by_side(rows)
    states = {side: _ship_state(ship) for side, ship in ships.items()}
    observed_defender_sides = set()
    for row in sorted(rows, key=_sort_key):
        defender_side = row.get("defender_side")
        if isinstance(defender_side, str) and defender_side not in observed_defender_sides:
            states[defender_side] = _observed_pre_shot_state(row)
            observed_defender_sides.add(defender_side)
    return states


def _observed_final_states(rows: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    states = _initial_states(rows)
    for row in sorted(rows, key=_sort_key):
        defender_side = row.get("defender_side")
        if not isinstance(defender_side, str):
            continue
        remaining = _remaining(_observed(row))
        states[defender_side] = {
            "shield": _report_number(_number(remaining.get("shield"))),
            "hull": _report_number(_number(remaining.get("hull"))),
        }
    return states


def _state_copy(state: dict[str, int | float]) -> dict[str, int | float]:
    return {
        "shield": _report_number(_number(state.get("shield"))),
        "hull": _report_number(_number(state.get("hull"))),
    }


def _weapon_id(weapon: dict[str, Any]) -> str:
    return str(weapon.get("id") or "")


def _weapons_for_side(rows: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    for row in rows:
        for role in ("attacker", "defender"):
            if row.get(f"{role}_side") != side:
                continue
            ship = row.get(role, {})
            static_ship = ship.get("static_ship", {}) if isinstance(ship, dict) else {}
            weapons = static_ship.get("weapons", []) if isinstance(static_ship, dict) else []
            if isinstance(weapons, list) and weapons:
                return [dict(weapon) for weapon in weapons if isinstance(weapon, dict)]
    return []


def _side_order(rows: list[dict[str, Any]]) -> list[str]:
    order = []
    for row in sorted(rows, key=_sort_key):
        side = row.get("attacker_side")
        if isinstance(side, str) and side and side not in order:
            order.append(side)
    for side in _ship_by_side(rows):
        if side not in order:
            order.append(side)
    return order


def _opposing_side(side: str, rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("attacker_side") == side and isinstance(row.get("defender_side"), str):
            return str(row["defender_side"])
        if row.get("defender_side") == side and isinstance(row.get("attacker_side"), str):
            return str(row["attacker_side"])
    return "hostile" if side == "player" else "player"


def _template_row(rows: list[dict[str, Any]], *, attacker_side: str, weapon: dict[str, Any]) -> dict[str, Any]:
    weapon_id = _weapon_id(weapon)
    source = next(
        (
            row
            for row in rows
            if row.get("attacker_side") == attacker_side and _weapon_id(row.get("weapon", {})) == weapon_id
        ),
        None,
    )
    if source is None:
        source = next((row for row in rows if row.get("attacker_side") == attacker_side), rows[0])
    row = copy.deepcopy(source)
    ships = _ship_by_side(rows)
    defender_side = _opposing_side(attacker_side, rows)
    row["attacker_side"] = attacker_side
    row["defender_side"] = defender_side
    if attacker_side in ships:
        row["attacker"] = copy.deepcopy(ships[attacker_side])
    if defender_side in ships:
        row["defender"] = copy.deepcopy(ships[defender_side])
    row["weapon"] = dict(weapon)
    return row


def load_observations_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def group_observations_by_battle(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("battle_id") or "unknown")].append(row)
    return {battle_id: sorted(battle_rows, key=_sort_key) for battle_id, battle_rows in sorted(grouped.items())}


def filter_observations(
    rows: list[dict[str, Any]],
    *,
    battle_ids: list[str] | None = None,
    battle_classes: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    battle_id_set = set(battle_ids or [])
    battle_class_set = set(battle_classes or [])
    filtered = []
    for row in rows:
        if battle_id_set and str(row.get("battle_id") or "unknown") not in battle_id_set:
            continue
        if battle_class_set and (_battle_formula_class(row) or "other") not in battle_class_set:
            continue
        filtered.append(row)

    if limit is None:
        return filtered

    limited = []
    for battle_rows in list(group_observations_by_battle(filtered).values())[:limit]:
        limited.extend(battle_rows)
    return limited


def build_projected_schedule(
    rows: list[dict[str, Any]],
    *,
    max_rounds: int,
    max_attacks: int,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    side_order = _side_order(rows)
    weapons_by_side = {side: _weapons_for_side(rows, side) for side in side_order}
    next_available = {
        (side, index): max(1, _round_int(weapon.get("warm_up"), default=1))
        for side, weapons in weapons_by_side.items()
        for index, weapon in enumerate(weapons)
    }
    schedule = []
    for battle_round in range(1, max_rounds + 1):
        sub_round = 0
        for side in side_order:
            for index, weapon in enumerate(weapons_by_side.get(side, [])):
                key = (side, index)
                warm_up = max(1, _round_int(weapon.get("warm_up"), default=1))
                if battle_round < warm_up or battle_round < next_available[key]:
                    continue
                sub_round += 1
                row = _template_row(rows, attacker_side=side, weapon=weapon)
                row["battle_round"] = battle_round
                row["sub_round"] = sub_round
                row["attack_index"] = len(schedule) + 1
                schedule.append(row)
                cooldown = max(1, _round_int(weapon.get("cooldown"), default=1))
                next_available[key] = battle_round + cooldown
                if len(schedule) >= max_attacks:
                    return schedule
    return schedule


def _apex_mitigation(row: dict[str, Any]) -> float:
    wave_apex = _wave_defense_player_defender_apex_mitigation(row)
    if wave_apex is not None:
        return wave_apex
    standard_apex = _standard_hostile_player_defender_apex_mitigation(row)
    if standard_apex is not None:
        return standard_apex
    defender = row.get("defender", {})
    modifiers = defender.get("resolved_modifiers", {}) if isinstance(defender, dict) else {}
    barrier = _number(modifiers.get("67001")) if isinstance(modifiers, dict) else 0.0
    if barrier <= 1.0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - apex_barrier_damage_reduction(apex_barrier=barrier, apex_shred=0)))


def _isolytic_effective_mitigation(row: dict[str, Any]) -> float:
    defense = _resolved_modifier(row, "defender", "808")
    if defense <= 0.0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - isolytic_mitigation(isolytic_defense=defense)))


def _resolved_modifier(row: dict[str, Any], role: str, modifier_code: str) -> float:
    ship = row.get(role, {})
    modifiers = ship.get("resolved_modifiers", {}) if isinstance(ship, dict) else {}
    return _number(modifiers.get(modifier_code)) if isinstance(modifiers, dict) else 0.0


def _captured_fleet_modifier(row: dict[str, Any], role: str, modifier_code: str) -> float:
    ship = row.get(role, {})
    modifiers = ship.get("captured_fleet_stats", {}) if isinstance(ship, dict) else {}
    return _number(modifiers.get(modifier_code)) if isinstance(modifiers, dict) else 0.0


def _captured_stat(row: dict[str, Any], role: str, stat_code: str) -> float:
    ship = row.get(role, {})
    stats = ship.get("captured_stats", {}) if isinstance(ship, dict) else {}
    return _number(stats.get(stat_code)) if isinstance(stats, dict) else 0.0


def _ship_hull_name(row: dict[str, Any], role: str) -> str:
    ship = row.get(role, {})
    static_ship = ship.get("static_ship", {}) if isinstance(ship, dict) else {}
    hull = static_ship.get("hull", {}) if isinstance(static_ship, dict) else {}
    name = hull.get("name") if isinstance(hull, dict) else None
    return str(name or "")


def _is_scaled_pve_hostile_attack(row: dict[str, Any]) -> bool:
    battle_class = _battle_formula_class(row) or "other"
    return row.get("attacker_side") == "hostile" and battle_class in PVE_HOSTILE_DAMAGE_CLASSES


def _is_wave_defense_hostile_attack_into_player(row: dict[str, Any]) -> bool:
    return (
        _battle_formula_class(row) == "wave_defense"
        and row.get("attacker_side") == "hostile"
        and row.get("defender_side") == "player"
    )


def _wave_defense_player_defender_surface_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_ship_hull_name(row, "defender"), _ship_hull_name(row, "attacker"))


def _wave_defense_player_defender_mitigation(row: dict[str, Any]) -> float | None:
    if not _is_wave_defense_hostile_attack_into_player(row):
        return None
    return WAVE_DEFENSE_PLAYER_DEFENDER_MITIGATION_SURFACE.get(_wave_defense_player_defender_surface_key(row))


def _standard_mitigation(row: dict[str, Any], mitigation_model: Any) -> float:
    wave_mitigation = _wave_defense_player_defender_mitigation(row)
    if wave_mitigation is not None:
        return wave_mitigation
    return mitigation_model.predict(row)


def _wave_defense_player_defender_apex_mitigation(row: dict[str, Any]) -> float | None:
    if not _is_wave_defense_hostile_attack_into_player(row):
        return None
    player_hull_name, hostile_hull_name = _wave_defense_player_defender_surface_key(row)
    if player_hull_name == "Junker":
        return WAVE_DEFENSE_JUNKER_APEX_MITIGATION
    if player_hull_name == "Newton_LIVE" and hostile_hull_name == "Hull_L42_Battleship_Rom_WaveDefense":
        return WAVE_DEFENSE_NEWTON_BATTLESHIP_APEX_MITIGATION
    if player_hull_name == "Newton_LIVE":
        return WAVE_DEFENSE_NEWTON_APEX_MITIGATION
    return None


def _standard_hostile_player_defender_apex_mitigation(row: dict[str, Any]) -> float | None:
    if (
        _battle_formula_class(row) != "standard_hostile"
        or row.get("attacker_side") != "hostile"
        or row.get("defender_side") != "player"
    ):
        return None
    return STANDARD_HOSTILE_PLAYER_DEFENDER_APEX_SURFACE.get(_ship_hull_name(row, "defender"))


def _raw_damage_assumption(row: dict[str, Any], *, use_observed_critical: bool = False) -> dict[str, Any]:
    if is_chain_shot_attack(row):
        observed_raw_damage = observed_normal_raw_damage(row)
        chain_shot_damage = _resolved_modifier(row, "attacker", CHAIN_SHOT_DAMAGE_MODIFIER_CODE)
        raw_damage = observed_raw_damage if observed_raw_damage > 0.0 else chain_shot_damage
        source = "chain_shot_observed_normal_raw_damage" if observed_raw_damage > 0.0 else "chain_shot_modifier_77001"
        return {
            "source": source,
            "weapon_id": _weapon_id(row.get("weapon", {})),
            "chain_shot_damage_modifier": _report_number(chain_shot_damage),
            "chain_shot_secondary_modifier": _report_number(
                _resolved_modifier(row, "attacker", CHAIN_SHOT_SECONDARY_MODIFIER_CODE)
            ),
            "standard_damage_modifier": 0,
            "standard_damage_multiplier": 1,
            "standard_raw_damage": _report_number(raw_damage),
        }

    diagnostics = weapon_damage_diagnostics(row)
    base = _number(diagnostics.get("effective_damage_midpoint"))
    weapon = row.get("weapon", {})
    crit_chance = _number(weapon.get("crit_chance") if isinstance(weapon, dict) else 0.0)
    crit_modifier = _number(weapon.get("crit_modifier") if isinstance(weapon, dict) else 1.0)
    effective_crit_modifier = (
        min(crit_modifier, PVE_HOSTILE_CRIT_MODIFIER_CAP) if _is_scaled_pve_hostile_attack(row) else crit_modifier
    )
    source = "weapon_midpoint_expected_crit_mod_all_damage"
    if use_observed_critical:
        observed = _observed(row)
        if bool(observed.get("critical")):
            captured_crit_modifier = (
                _captured_stat(row, "attacker", "10") if row.get("attacker_side") == "player" else 1.0
            )
            crit_multiplier = max(1.0, effective_crit_modifier) * max(1.0, captured_crit_modifier)
            source = "weapon_midpoint_observed_crit_mod_all_damage"
        else:
            crit_multiplier = 1.0
            source = "weapon_midpoint_observed_noncrit_mod_all_damage"
    else:
        crit_multiplier = 1.0 + max(0.0, crit_chance) * max(0.0, effective_crit_modifier - 1.0)
    standard_damage_modifier = _resolved_modifier(row, "attacker", "2")
    standard_damage_multiplier = max(0.0, 1.0 + standard_damage_modifier)
    wave_defense_damage_modifier = 0.0
    wave_defense_damage_multiplier = 1.0
    battle_class = _battle_formula_class(row) or "other"
    if row.get("attacker_side") == "player" and battle_class == "wave_defense":
        wave_defense_damage_modifier = _resolved_modifier(row, "attacker", WAVE_DEFENSE_DAMAGE_MODIFIER_CODE)
        if wave_defense_damage_modifier > 0.0:
            wave_defense_damage_multiplier = wave_defense_damage_modifier
    hit_multiplier = 1.0
    standard_raw_damage = (
        base * hit_multiplier * crit_multiplier * standard_damage_multiplier * wave_defense_damage_multiplier
    )
    pve_hostile_damage_scale = 1.0
    standard_hostile_damage_scale = 1.0
    wave_defense_player_damage_scale = 1.0
    wave_defense_player_critical_damage_scale = 1.0
    if _is_scaled_pve_hostile_attack(row):
        pve_hostile_damage_scale = PVE_HOSTILE_RAW_DAMAGE_SCALE
        standard_raw_damage *= pve_hostile_damage_scale
        source = f"{source}_pve_hostile_damage_scale"
        if battle_class == "standard_hostile":
            standard_hostile_damage_scale = STANDARD_HOSTILE_HOSTILE_RAW_DAMAGE_SCALE
            standard_raw_damage *= standard_hostile_damage_scale
            source = f"{source}_standard_hostile_damage_scale"
    if row.get("attacker_side") == "player" and battle_class == "standard_hostile":
        standard_hostile_damage_scale = STANDARD_HOSTILE_PLAYER_RAW_DAMAGE_SCALE
        standard_raw_damage *= standard_hostile_damage_scale
        source = f"{source}_standard_hostile_damage_scale"
    if row.get("attacker_side") == "player" and battle_class == "wave_defense":
        wave_defense_player_damage_scale = WAVE_DEFENSE_PLAYER_RAW_DAMAGE_SCALE
        standard_raw_damage *= wave_defense_player_damage_scale
        source = f"{source}_wave_defense_player_damage_scale"
        if use_observed_critical and bool(_observed(row).get("critical")):
            wave_defense_player_critical_damage_scale = WAVE_DEFENSE_PLAYER_CRITICAL_RAW_DAMAGE_SCALE
            standard_raw_damage *= wave_defense_player_critical_damage_scale
            source = f"{source}_wave_defense_player_critical_damage_scale"
    assumption = {
        "source": source,
        "base_midpoint": diagnostics.get("base_midpoint"),
        "effective_shots": diagnostics.get("effective_shots"),
        "effective_midpoint": diagnostics.get("effective_damage_midpoint"),
        "hit_multiplier": hit_multiplier,
        "crit_chance": _report_number(crit_chance),
        "crit_modifier": _report_number(crit_modifier),
        "effective_crit_modifier": _report_number(effective_crit_modifier),
        "crit_multiplier": _report_number(crit_multiplier),
        "standard_damage_modifier": _report_number(standard_damage_modifier),
        "standard_damage_multiplier": _report_number(standard_damage_multiplier),
        "standard_raw_damage": _report_number(standard_raw_damage),
    }
    if pve_hostile_damage_scale != 1.0:
        assumption["pve_hostile_damage_scale"] = _report_number(pve_hostile_damage_scale)
    if standard_hostile_damage_scale != 1.0:
        assumption["standard_hostile_damage_scale"] = _report_number(standard_hostile_damage_scale)
    if wave_defense_player_damage_scale != 1.0:
        assumption["wave_defense_player_damage_scale"] = _report_number(wave_defense_player_damage_scale)
    if wave_defense_player_critical_damage_scale != 1.0:
        assumption["wave_defense_player_critical_damage_scale"] = _report_number(
            wave_defense_player_critical_damage_scale
        )
    if wave_defense_damage_multiplier != 1.0:
        source = f"{source}_wave_defense_modifier_{WAVE_DEFENSE_DAMAGE_MODIFIER_CODE}"
        assumption["source"] = source
        assumption["wave_defense_damage_modifier"] = _report_number(wave_defense_damage_modifier)
        assumption["wave_defense_damage_multiplier"] = _report_number(wave_defense_damage_multiplier)
    return assumption


def _observed_isolytic_model_modifier(row: dict[str, Any]) -> tuple[float, str] | None:
    observed = _observed(row)
    model = observed.get("isolytic_damage_model", {}) if isinstance(observed, dict) else {}
    if not isinstance(model, dict) or model.get("source") == "derived_from_battle_log":
        return None
    damage_multiplier = _number(model.get("damage_multiplier"))
    if damage_multiplier <= 0.0:
        return None
    source = str(model.get("multiplier_source") or model.get("source") or "observed_isolytic_damage_model")
    return damage_multiplier, f"{source}_from_standard_raw_damage"


def _captured_final_fleet_isolytic_modifier(
    row: dict[str, Any],
    *,
    resolved_modifier: float,
) -> tuple[float, str] | None:
    captured_707 = _captured_fleet_modifier(row, "attacker", "707")
    if captured_707 <= 1.0 or resolved_modifier > 1.0:
        return None
    model = isolytic_damage_model_from_observed(
        _observed(row),
        attacker_stats={"707": captured_707},
        attacker_stat_source="captured_fleet_stats",
    )
    damage_multiplier = _number(model.get("damage_multiplier"))
    if damage_multiplier <= 0.0:
        return None
    source = str(model.get("multiplier_source") or "captured_final_fleet_707")
    return damage_multiplier, f"{source}_from_standard_raw_damage"


def _isolytic_damage_modifier(row: dict[str, Any]) -> tuple[float, str]:
    observed_modifier = _observed_isolytic_model_modifier(row)
    if observed_modifier is not None and observed_modifier[1].startswith("resolved_static_707_bonus"):
        return observed_modifier
    resolved_modifier = max(0.0, _resolved_modifier(row, "attacker", "707"))
    captured_modifier = _captured_final_fleet_isolytic_modifier(row, resolved_modifier=resolved_modifier)
    if captured_modifier is not None:
        return captured_modifier
    return resolved_modifier, "attacker_mod_707_from_standard_raw_damage"


def _isolytic_damage_assumption(row: dict[str, Any], standard_raw_damage: Any) -> dict[str, Any]:
    damage_modifier, source = _isolytic_damage_modifier(row)
    if is_chain_shot_attack(row):
        return {
            "source": "chain_shot_no_isolytic_lane",
            "damage_modifier": _report_number(damage_modifier),
            "raw_damage": 0,
            "mitigation": 0,
        }
    if row.get("attacker_side") == "player" and _battle_formula_class(row) == "wave_defense":
        hull_name = _ship_hull_name(row, "attacker")
        wave_multiplier = WAVE_DEFENSE_PLAYER_ISOLYTIC_MULTIPLIERS.get(hull_name)
        if wave_multiplier is not None:
            damage_modifier = wave_multiplier
            source = f"wave_defense_player_isolytic_buff_surface_{hull_name}"
    raw_damage = isolytic_damage(
        regular_after_modifiers=standard_raw_damage,
        isolytic_bonus=damage_modifier,
        cascade_bonus=0,
    )
    mitigation = _isolytic_effective_mitigation(row)
    return {
        "source": source,
        "damage_modifier": _report_number(damage_modifier),
        "raw_damage": _report_number(float(raw_damage)),
        "mitigation": mitigation,
    }


def _assumption_gaps(row: dict[str, Any], *, use_observed_critical: bool = False) -> list[str]:
    observed = _observed(row)
    gaps = []
    triggered = set(observed.get("triggered_effects", []) or [])
    if "officer" in triggered:
        gaps.append("officer_trigger_scheduling")
    if "forbidden_tech" in triggered:
        gaps.append("forbidden_tech_trigger_scheduling")
    if ("isolytic" in triggered or _number(observed.get("isolytic_damage"))) and _resolved_modifier(
        row, "attacker", "707"
    ) <= 0.0:
        gaps.append("isolytic_trigger_scheduling")
    if bool(observed.get("critical")) and not use_observed_critical:
        gaps.append("observed_critical_replaced_by_expected_crit")
    if not bool(observed.get("hit", True)):
        gaps.append("observed_miss_replaced_by_expected_hit")
    return gaps


def _observed_attack_comparison(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    observed = _observed(row)
    damage = _damage(observed)
    remaining = _remaining(observed)
    return {
        "battle_round": row.get("battle_round"),
        "sub_round": row.get("sub_round"),
        "attacker_side": row.get("attacker_side"),
        "weapon_id": _weapon_id(row.get("weapon", {})),
        "damage": {
            "shield": _report_number(_number(damage.get("shield"))),
            "hull": _report_number(_number(damage.get("hull"))),
        },
        "remaining": {
            "shield": _report_number(_number(remaining.get("shield"))),
            "hull": _report_number(_number(remaining.get("hull"))),
        },
    }


def _sequence_mismatches(projected_rows: list[dict[str, Any]], observed_rows: list[dict[str, Any]]) -> int:
    mismatches = abs(len(projected_rows) - len(observed_rows))
    for projected, observed in zip(projected_rows, observed_rows, strict=False):
        if projected.get("attacker_side") != observed.get("attacker_side"):
            mismatches += 1
            continue
        if _weapon_id(projected.get("weapon", {})) != _weapon_id(observed.get("weapon", {})):
            mismatches += 1
    return mismatches


def _dead_sides(states: dict[str, dict[str, int | float]]) -> list[str]:
    return sorted(side for side, state in states.items() if _number(state.get("hull")) <= 0)


def _metrics_from_values(values: list[float]) -> dict[str, int | float]:
    if not values:
        return {"count": 0, "mae": 0, "max_abs_error": 0, "bias": 0}
    return {
        "count": len(values),
        "mae": _report_number(sum(abs(value) for value in values) / len(values)),
        "max_abs_error": _report_number(max(abs(value) for value in values)),
        "bias": _report_number(sum(values) / len(values)),
    }


def _project_battle(
    battle_id: str,
    rows: list[dict[str, Any]],
    *,
    mitigation_model: Any,
    mode: str,
    max_rounds: int,
    max_attacks: int,
) -> dict[str, Any]:
    observed_rows = sorted(rows, key=_sort_key)
    projected_rows = (
        observed_rows[:max_attacks]
        if mode == "observed-order"
        else build_projected_schedule(observed_rows, max_rounds=max_rounds, max_attacks=max_attacks)
    )
    states = {side: _state_copy(state) for side, state in _initial_states(observed_rows).items()}
    initial_states = copy.deepcopy(states)
    observed_final = _observed_final_states(observed_rows)
    attacks = []
    damage_errors = []

    for index, row in enumerate(projected_rows):
        attacker_side = str(row.get("attacker_side") or "unknown")
        defender_side = str(row.get("defender_side") or _opposing_side(attacker_side, observed_rows))
        attacker = row.get("attacker", {})
        defender = row.get("defender", {})
        states.setdefault(attacker_side, _ship_state(attacker if isinstance(attacker, dict) else {}))
        states.setdefault(defender_side, _ship_state(defender if isinstance(defender, dict) else {}))
        defender_before = _state_copy(states[defender_side])
        use_observed_critical = mode == "observed-order"
        raw_damage = _raw_damage_assumption(row, use_observed_critical=use_observed_critical)
        isolytic = _isolytic_damage_assumption(row, raw_damage["standard_raw_damage"])
        standard_mitigation = _standard_mitigation(row, mitigation_model)
        apex_mitigation = _apex_mitigation(row)
        pipeline = predict_damage_from_stages(
            row,
            standard_raw_damage=raw_damage["standard_raw_damage"],
            standard_mitigation=standard_mitigation,
            isolytic_raw_damage=isolytic["raw_damage"],
            isolytic_mitigation=isolytic["mitigation"],
            apex_mitigation=apex_mitigation,
            pre_shot_state=defender_before,
        )
        states[defender_side] = _state_copy(pipeline["remaining"])
        observed_row = observed_rows[index] if index < len(observed_rows) else None
        observed_comparison = _observed_attack_comparison(observed_row)
        errors = {}
        if observed_comparison is not None:
            projected_total = _number(pipeline["damage"].get("shield")) + _number(pipeline["damage"].get("hull"))
            observed_total = _number(observed_comparison["damage"].get("shield")) + _number(
                observed_comparison["damage"].get("hull")
            )
            errors["damage"] = _report_number(projected_total - observed_total)
            damage_errors.append(projected_total - observed_total)
        attacks.append(
            {
                "attack_index": index + 1,
                "battle_round": row.get("battle_round"),
                "sub_round": row.get("sub_round"),
                "attacker_side": attacker_side,
                "defender_side": defender_side,
                "weapon": {
                    "id": _weapon_id(row.get("weapon", {})),
                    "name": row.get("weapon", {}).get("name") if isinstance(row.get("weapon"), dict) else None,
                },
                "state_before": {
                    "attacker": _state_copy(states[attacker_side]),
                    "defender": defender_before,
                },
                "state_after": {
                    "attacker": _state_copy(states[attacker_side]),
                    "defender": _state_copy(states[defender_side]),
                },
                "raw_damage": raw_damage,
                "isolytic_damage": isolytic,
                "mitigation": {
                    "standard": standard_mitigation,
                    "isolytic": isolytic["mitigation"],
                    "apex": apex_mitigation,
                },
                "damage_stages": pipeline,
                "assumption_gaps": _assumption_gaps(row, use_observed_critical=use_observed_critical),
                "observed": observed_comparison,
                "errors": errors,
            }
        )
        if _number(states[defender_side].get("hull")) <= 0:
            break

    final_errors = []
    for side, observed_state in observed_final.items():
        projected_state = states.get(side, {"shield": 0, "hull": 0})
        final_errors.append(_number(projected_state.get("shield")) - _number(observed_state.get("shield")))
        final_errors.append(_number(projected_state.get("hull")) - _number(observed_state.get("hull")))

    sequence_mismatches = _sequence_mismatches(projected_rows[: len(attacks)], observed_rows)
    sequence_denominator = max(len(projected_rows[: len(attacks)]), len(observed_rows), 1)
    return {
        "battle_id": battle_id,
        "battle_class": _battle_formula_class(observed_rows[0]) or "other",
        "battle_type": observed_rows[0].get("battle_type"),
        "initial_state": initial_states,
        "projected_final_state": states,
        "observed_final_state": observed_final,
        "outcome_match": _dead_sides(states) == _dead_sides(observed_final),
        "metrics": {
            "attack_count": len(attacks),
            "observed_attack_count": len(observed_rows),
            "damage_mae": _metrics_from_values(damage_errors)["mae"],
            "damage_error": _metrics_from_values(damage_errors),
            "final_state_error": _metrics_from_values(final_errors),
            "weapon_sequence_mismatches": sequence_mismatches,
            "weapon_sequence_mismatch_rate": _report_number(sequence_mismatches / sequence_denominator),
        },
        "attacks": attacks,
    }


def _aggregate_battles(battles: list[dict[str, Any]]) -> dict[str, Any]:
    attack_count = sum(int(battle["metrics"]["attack_count"]) for battle in battles)
    observed_attack_count = sum(int(battle["metrics"]["observed_attack_count"]) for battle in battles)
    damage_error_sum = 0.0
    damage_error_count = 0
    sequence_mismatches = 0
    sequence_denominator = 0
    outcome_matches = 0
    final_state_error_sum = 0.0
    final_state_error_count = 0
    for battle in battles:
        metrics = battle["metrics"]
        damage_error = metrics["damage_error"]
        damage_error_sum += float(damage_error["mae"]) * int(damage_error["count"])
        damage_error_count += int(damage_error["count"])
        final_state_error = metrics["final_state_error"]
        final_state_error_sum += float(final_state_error["mae"]) * int(final_state_error["count"])
        final_state_error_count += int(final_state_error["count"])
        sequence_mismatches += int(metrics["weapon_sequence_mismatches"])
        sequence_denominator += max(int(metrics["attack_count"]), int(metrics["observed_attack_count"]))
        outcome_matches += 1 if battle.get("outcome_match") else 0
    return {
        "battle_count": len(battles),
        "attack_count": attack_count,
        "observed_attack_count": observed_attack_count,
        "damage_mae": _report_number(damage_error_sum / damage_error_count) if damage_error_count else 0,
        "final_state_mae": _report_number(final_state_error_sum / final_state_error_count)
        if final_state_error_count
        else 0,
        "weapon_sequence_mismatches": sequence_mismatches,
        "weapon_sequence_mismatch_rate": _report_number(sequence_mismatches / sequence_denominator)
        if sequence_denominator
        else 0,
        "outcome_match_rate": _report_number(outcome_matches / len(battles)) if battles else 0,
    }


def _aggregate_by_battle_class(battles: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for battle in battles:
        groups[str(battle.get("battle_class") or "other")].append(battle)
    return {battle_class: _aggregate_battles(group) for battle_class, group in sorted(groups.items())}


def project_observations(
    rows: list[dict[str, Any]],
    *,
    mitigation_model: Any,
    mode: str,
    max_rounds: int,
    max_attacks: int,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"observed-order", "deterministic"}:
        raise ValueError(f"unsupported projection mode: {mode}")
    battles = [
        _project_battle(
            battle_id,
            battle_rows,
            mitigation_model=mitigation_model,
            mode=mode,
            max_rounds=max_rounds,
            max_attacks=max_attacks,
        )
        for battle_id, battle_rows in group_observations_by_battle(rows).items()
    ]
    assumptions = {
        "raw_damage": (
            "weapon midpoint adjusted by effective shot count and MOD_ALL_DAMAGE; observed-order mode uses the "
            "observed critical outcome with captured player critical damage when available, while deterministic mode "
            "uses the expected crit multiplier; "
            "standard hostile and wave-defense hostile shots share the PvE hostile raw-damage scale; "
            "standard hostile rows apply class-specific player and hostile PvE damage surfaces; "
            "player wave-defense shots also apply resolved modifier 88 as a direct wave-defense damage multiplier; "
            "player wave-defense rows apply the captured wave raw and critical damage surfaces; "
            "chain-shot pseudo-attacks use observed normal raw damage when present, otherwise "
            "MOD_CHAINSHOT_DAMAGE 77001"
        ),
        "hit": "deterministic hit multiplier 1.0",
        "crit": (
            "expected crit multiplier from static crit chance and crit modifier; "
            "PvE hostile crit modifier is capped"
        ),
        "normal_mitigation": (
            "combat_triangle_synced_linear_formula; wave-defense hostile shots into player ships use the captured "
            "player-hull/hostile-hull mitigation buff surface"
        ),
        "isolytic": (
            "attacker MOD_ISOLYTIC_DAMAGE (707) applied to projected standard raw damage; "
            "player wave-defense rows apply the captured Junker/Newton isolytic buff surface; "
            "defender 808 applies isolytic mitigation; chain-shot pseudo-attacks do not spawn an isolytic lane"
        ),
        "apex": (
            "resolved defender 67001 barrier when available; standard-hostile and wave-defense hostile shots into "
            "player ships use captured apex buff surfaces"
        ),
    }
    model_metadata = mitigation_model.metadata() if hasattr(mitigation_model, "metadata") else {}
    return {
        "metadata": {
            "mode": mode,
            "model": model_metadata,
            "assumptions": assumptions,
            "max_rounds": max_rounds,
            "max_attacks": max_attacks,
            "filters": filters or {},
            "input_rows": len(rows),
        },
        "summary": _aggregate_battles(battles),
        "by_battle_class": _aggregate_by_battle_class(battles),
        "battles": battles,
    }
