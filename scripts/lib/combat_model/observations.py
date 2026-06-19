from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .battle_enums import battle_type_name, fleet_data_type_name
from .formula_effects import formula_effect_for_modifier
from .mitigation_targets import isolytic_damage_model_from_observed, normal_mitigation_from_observed
from .ship_bonuses import apply_static_ship_bonuses_to_rows
from .simulator_state import attach_resolved_player_states, load_resolved_player_state_index
from .static_catalog import build_static_ship, load_static_catalog


START_ROUND = -96
END_ROUND = -97
START_ATTACK = -98
END_ATTACK = -99
ATTACK_CHARGE = -95
START_SUB_ROUND = -90
END_SUB_ROUND = -89
OFFICER_ABILITIES_FIRING = -93
START_OFFICER_ABILITY = -91
END_OFFICER_ABILITY = -92
END_OFFICER_ABILITIES = -94
START_FORBIDDEN_TECH_ABILITIES = -84
END_FORBIDDEN_TECH_ABILITIES = -83
START_FORBIDDEN_TECH_ABILITY = -82
END_FORBIDDEN_TECH_ABILITY = -81
OFFICER_ABILITY_FIELDS = ("captainManeuverId", "officerAbilityId", "belowDecksAbilityId")
FLEET_RATING_FIELDS = (
    "fleet_grade",
    "offense_rating",
    "defense_rating",
    "health_rating",
    "deflector_rating",
    "sensor_rating",
    "officer_rating",
    "forbidden_tech_rating",
)
FLEET_RATING_MODIFIER_CODES = {
    "fleet_grade": "-7",
    "offense_rating": "-8",
    "defense_rating": "-9",
    "health_rating": "-10",
    "deflector_rating": "-11",
    "sensor_rating": "-12",
    "officer_rating": "-13",
    "forbidden_tech_rating": "-18",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _to_int(value: Any) -> int:
    return int(round(float(value)))


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return bool(int(value))


def _find_marker(log: list[Any], marker: int, start_index: int) -> int:
    try:
        return log.index(marker, start_index)
    except ValueError as exc:
        raise ValueError(f"battle_log marker {marker} has no matching terminator") from exc


def _is_charge_attack(values: list[Any]) -> bool:
    return len(values) >= 2 and values[1] == ATTACK_CHARGE


def _triggered_effects(values: list[Any], forbidden_tech_activations: list[dict[str, Any]] | None = None) -> list[str]:
    effects = []
    if len(values) > 5 and _to_bool(values[5]):
        effects.append("critical")
    if OFFICER_ABILITIES_FIRING in values[16:]:
        effects.append("officer")
    if len(values) > 11 and _to_int(values[11]) > 0:
        effects.append("isolytic")
    if forbidden_tech_activations:
        effects.append("forbidden_tech")
    return effects


def _parse_officer_activations(values: list[Any]) -> list[dict[str, Any]]:
    activations = []
    firing_ship_id: str | None = None
    tail = values[16:]
    i = 0
    while i < len(tail):
        value = tail[i]
        if value == OFFICER_ABILITIES_FIRING:
            firing_ship_id = _id_key(tail[i + 1]) if i + 1 < len(tail) else None
            i += 2
            continue
        if value == START_OFFICER_ABILITY:
            end_index = i + 1
            while end_index < len(tail) and tail[end_index] != END_OFFICER_ABILITY:
                end_index += 1
            payload = tail[i + 1 : end_index]
            if len(payload) >= 3:
                activation = {
                    "firing_ship_id": firing_ship_id,
                    "officer_id": _id_key(payload[0]),
                    "ability_buff_id": _id_key(payload[1]),
                    "value": _number(payload[2]),
                }
                if len(payload) > 3:
                    activation["extra_values"] = payload[3:]
                activations.append(activation)
            i = end_index + 1
            continue
        if value == END_OFFICER_ABILITIES:
            firing_ship_id = None
        i += 1
    return activations


def _parse_forbidden_tech_activations(values: list[Any]) -> list[dict[str, Any]]:
    activations = []
    firing_ship_id: str | None = None
    i = 0
    while i < len(values):
        value = values[i]
        if value == START_FORBIDDEN_TECH_ABILITY:
            end_index = i + 1
            while end_index < len(values) and values[end_index] != END_FORBIDDEN_TECH_ABILITY:
                end_index += 1
            payload = values[i + 1 : end_index]
            if len(payload) >= 3:
                activation = {
                    "firing_ship_id": firing_ship_id,
                    "forbidden_tech_id": _id_key(payload[0]),
                    "ability_buff_id": _id_key(payload[1]),
                    "value": _number(payload[2]),
                }
                if len(payload) > 3:
                    activation["extra_values"] = payload[3:]
                activations.append(activation)
            i = end_index + 1
            continue
        if value not in {END_FORBIDDEN_TECH_ABILITY, END_FORBIDDEN_TECH_ABILITIES}:
            firing_ship_id = _id_key(value)
        i += 1
    return activations


def _iter_attacks(log: list[Any]) -> list[dict[str, Any]]:
    attacks = []
    battle_round = 0
    sub_round = 0
    active_forbidden_tech_activations: dict[tuple[str | None, str, str], dict[str, Any]] = {}
    i = 0

    while i < len(log):
        value = log[i]
        if value == START_ROUND:
            battle_round += 1
            sub_round = 0
            i += 1
            continue
        if value == END_ROUND:
            i += 1
            continue
        if value == START_SUB_ROUND:
            sub_round += 1
            i += 1
            continue
        if value == END_SUB_ROUND:
            i += 1
            continue
        if value == START_FORBIDDEN_TECH_ABILITIES:
            end_index = _find_marker(log, END_FORBIDDEN_TECH_ABILITIES, i + 1)
            for activation in _parse_forbidden_tech_activations(log[i + 1 : end_index]):
                key = (
                    activation.get("firing_ship_id"),
                    activation["forbidden_tech_id"],
                    activation["ability_buff_id"],
                )
                active_forbidden_tech_activations[key] = activation
            i = end_index + 1
            continue
        if value != START_ATTACK:
            i += 1
            continue

        if i == 0:
            raise ValueError("battle_log attack marker is missing attacker ship id")

        end_index = _find_marker(log, END_ATTACK, i + 1)
        values = log[i + 1 : end_index]
        if _is_charge_attack(values):
            i = end_index + 1
            continue
        if len(values) < 16:
            raise ValueError(f"battle_log attack entry has {len(values)} fields, expected at least 16")

        shield_damage = _to_int(values[8])
        hull_damage = _to_int(values[6])
        mitigated_damage = max(0, _to_int(values[10]))
        observed_damage = shield_damage + hull_damage
        raw_damage = observed_damage + mitigated_damage

        forbidden_tech_activations = list(active_forbidden_tech_activations.values())

        attacks.append(
            {
                "battle_round": battle_round,
                "sub_round": sub_round,
                "attacker_ship_id": _id_key(log[i - 1]),
                "target_ship_id": _id_key(values[1]),
                "weapon_id": _id_key(values[0]),
                "accuracy_roll": _number(values[2]),
                "dodge_roll": _number(values[3]),
                "hit": _to_bool(values[4]),
                "critical": _to_bool(values[5]),
                "hull_damage": hull_damage,
                "remaining_hull": _to_int(values[7]),
                "shield_damage": shield_damage,
                "remaining_shield": _to_int(values[9]),
                "mitigated_damage": mitigated_damage,
                "isolytic_damage": _to_int(values[11]),
                "mitigated_isolytic_damage": _to_int(values[12]),
                "mitigated_apex_barrier": _to_int(values[13]),
                "mitigated_critical_damage": _to_int(values[14]),
                "mitigated_isolytic_critical_damage": _to_int(values[15]),
                "observed_damage": observed_damage,
                "raw_damage": raw_damage,
                "effective_mitigation": mitigated_damage / raw_damage if raw_damage else 0.0,
                "triggered_effects": _triggered_effects(values, forbidden_tech_activations),
                "officer_activations": _parse_officer_activations(values),
                "forbidden_tech_activations": forbidden_tech_activations,
            }
        )
        i = end_index + 1

    return attacks


def _optional_static_collection(decoded_static_dir: Path, file_stem: str, collection_key: str) -> dict[str, Any]:
    path = decoded_static_dir / f"{file_stem}.json"
    if not path.exists():
        return {}
    data = _read_json(path)
    collection = data.get(collection_key, {})
    return collection if isinstance(collection, dict) else {}


def _officer_summary(officer_id: str, officer: dict[str, Any], ability_buff_id: str) -> dict[str, Any]:
    ability_field = next(
        (field for field in OFFICER_ABILITY_FIELDS if _id_key(officer.get(field)) == ability_buff_id),
        None,
    )
    return {
        "id": officer_id,
        "id_str": officer.get("idStr"),
        "name": officer.get("name"),
        "idRefs": officer.get("idRefs", {}),
        "ability_field": ability_field,
        "captainManeuverId": _id_key(officer.get("captainManeuverId")),
        "officerAbilityId": _id_key(officer.get("officerAbilityId")),
        "belowDecksAbilityId": _id_key(officer.get("belowDecksAbilityId")),
        "rarity": officer.get("rarity"),
        "officerClassType": officer.get("officerClassType"),
        "officerType": officer.get("officerType"),
        "factionId": officer.get("factionId"),
    }


def _ability_summary(ability_buff_id: str, ability: dict[str, Any], *, source_type: str) -> dict[str, Any]:
    summary = {
        "buff_id": ability_buff_id,
        "source_type": source_type,
        "targetCode": ability.get("targetCode"),
        "triggerCode": ability.get("triggerCode"),
        "op": ability.get("op"),
        "modifierCode": _id_key(ability.get("modifierCode")),
        "showPercentage": ability.get("showPercentage"),
        "rankedValueType": ability.get("rankedValueType"),
        "conditionCodes": [_id_key(code) for code in ability.get("conditionCodes", []) or []],
        "attributes": ability.get("attributes", {}),
    }
    for key in ("rankedChances", "rankedValues", "rankedBuffValues"):
        if key in ability:
            summary[key] = ability.get(key)
    if "idRefs" in ability:
        summary["idRefs"] = ability.get("idRefs", {})
    return summary


def _officer_static_index(decoded_static_dir: Path) -> dict[str, Any]:
    officers = _optional_static_collection(decoded_static_dir, "OfficerSpecs", "officerSpecs")
    abilities = _optional_static_collection(decoded_static_dir, "OfficerAbilityBuffSpecs", "officerAbilitySpecs")
    ship_bonus_buffs = _optional_static_collection(decoded_static_dir, "ShipBonusBuffSpecs", "shipBonusSpecs")
    officers_by_ability: dict[str, list[dict[str, Any]]] = {}
    for officer_id, officer in officers.items():
        if not isinstance(officer, dict):
            continue
        for field in OFFICER_ABILITY_FIELDS:
            ability_buff_id = officer.get(field)
            if ability_buff_id is None or _id_key(ability_buff_id) == "-1":
                continue
            officers_by_ability.setdefault(_id_key(ability_buff_id), []).append(
                _officer_summary(_id_key(officer_id), officer, _id_key(ability_buff_id))
            )
    for candidates in officers_by_ability.values():
        candidates.sort(key=lambda candidate: (candidate["id"], candidate.get("ability_field") or ""))
    return {
        "officers": officers,
        "abilities": abilities,
        "ship_bonus_buffs": ship_bonus_buffs,
        "officers_by_ability": officers_by_ability,
    }


def _forbidden_tech_static_index(decoded_static_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    specs_path = decoded_static_dir / "ForbiddenTechSpecs.json"
    buffs_path = decoded_static_dir / "ForbiddenTechBuffs.json"
    specs = _read_json(specs_path) if specs_path.exists() else {}
    buffs = _read_json(buffs_path) if buffs_path.exists() else {}

    spec_index = {}
    spec_entries = specs.get("forbiddenTechSpecs", [])
    if isinstance(spec_entries, list):
        for spec in spec_entries:
            if isinstance(spec, dict) and spec.get("id") is not None:
                spec_index[_id_key(spec["id"])] = spec

    buff_index = buffs.get("forbiddenTechBuffsSpecs", {})
    return {
        "specs": spec_index,
        "buffs": buff_index if isinstance(buff_index, dict) else {},
    }


def _mapped_officer_activations(
    activations: list[dict[str, Any]],
    officer_index: dict[str, Any],
) -> list[dict[str, Any]]:
    mapped = []
    officers = officer_index.get("officers") or {}
    abilities = officer_index.get("abilities") or {}
    ship_bonus_buffs = officer_index.get("ship_bonus_buffs") or {}
    officers_by_ability = officer_index.get("officers_by_ability") or {}
    for activation in activations:
        officer_id = _id_key(activation.get("officer_id"))
        ability_buff_id = _id_key(activation.get("ability_buff_id"))
        row = dict(activation)
        officer = officers.get(officer_id)
        ability = abilities.get(ability_buff_id)
        ability_source_type = "officer_ability"
        if not isinstance(ability, dict):
            ability = ship_bonus_buffs.get(ability_buff_id)
            ability_source_type = "ship_bonus"
        if isinstance(officer, dict):
            row["officer"] = _officer_summary(officer_id, officer, ability_buff_id)
        else:
            row["officer"] = {"id": officer_id, "status": "not_found"}
            candidates = officers_by_ability.get(ability_buff_id, [])
            if candidates:
                row["candidate_officers"] = candidates
        if isinstance(ability, dict):
            ability_summary = _ability_summary(ability_buff_id, ability, source_type=ability_source_type)
            row["ability"] = ability_summary
            row["ability_source_type"] = ability_source_type
            row["modifierCode"] = ability_summary.get("modifierCode")
            row["targetCode"] = ability_summary.get("targetCode")
            row["triggerCode"] = ability_summary.get("triggerCode")
            row["op"] = ability_summary.get("op")
            row["conditionCodes"] = ability_summary.get("conditionCodes", [])
            row["formula_effect"] = formula_effect_for_modifier(ability_summary.get("modifierCode"))
        else:
            row["ability"] = {"buff_id": ability_buff_id, "status": "not_found"}
            row["formula_effect"] = formula_effect_for_modifier(None)
        mapped.append(row)
    return mapped


def _forbidden_tech_summary(forbidden_tech_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": forbidden_tech_id,
        "type": spec.get("type"),
        "subtype": spec.get("subtype"),
        "rarity": spec.get("rarity"),
        "requiredSlotSpecId": _id_key(spec.get("requiredSlotSpecId")),
        "idRefs": spec.get("idRefs", {}),
    }


def _mapped_forbidden_tech_activations(
    activations: list[dict[str, Any]],
    forbidden_tech_index: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    mapped = []
    specs = forbidden_tech_index.get("specs", {})
    buffs = forbidden_tech_index.get("buffs", {})
    for activation in activations:
        forbidden_tech_id = _id_key(activation.get("forbidden_tech_id"))
        ability_buff_id = _id_key(activation.get("ability_buff_id"))
        row = dict(activation)
        forbidden_tech = specs.get(forbidden_tech_id)
        ability = buffs.get(ability_buff_id)
        if isinstance(forbidden_tech, dict):
            row["forbidden_tech"] = _forbidden_tech_summary(forbidden_tech_id, forbidden_tech)
        else:
            row["forbidden_tech"] = {"id": forbidden_tech_id, "status": "not_found"}
        if isinstance(ability, dict):
            ability_summary = _ability_summary(ability_buff_id, ability, source_type="forbidden_tech")
            row["ability"] = ability_summary
            row["ability_source_type"] = "forbidden_tech"
            row["modifierCode"] = ability_summary.get("modifierCode")
            row["targetCode"] = ability_summary.get("targetCode")
            row["triggerCode"] = ability_summary.get("triggerCode")
            row["op"] = ability_summary.get("op")
            row["conditionCodes"] = ability_summary.get("conditionCodes", [])
            row["formula_effect"] = formula_effect_for_modifier(ability_summary.get("modifierCode"))
        else:
            row["ability"] = {"buff_id": ability_buff_id, "status": "not_found"}
            row["formula_effect"] = formula_effect_for_modifier(None)
        mapped.append(row)
    return mapped


def _operation_delta(operation: Any, value: Any) -> float | None:
    numeric = _number(value)
    if numeric is None:
        return None
    if operation in {"BUFFOPERATION_ADD", "BUFFOPERATION_MULTIPLYADD"}:
        return float(numeric)
    if operation in {"BUFFOPERATION_SUB", "BUFFOPERATION_MULTIPLYSUB"}:
        return -float(numeric)
    return None


def _ship_matches_log_id(ship: dict[str, Any], ship_id: str | None) -> bool:
    if ship_id is None:
        return False
    return ship_id in {_id_key(ship.get("ship_id")), _id_key(ship.get("battle_log_ship_id"))}


def _report_number(value: int | float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def _apply_forbidden_tech_activations(row: dict[str, Any]) -> None:
    observed = row.get("observed")
    if not isinstance(observed, dict):
        return
    for activation in observed.get("forbidden_tech_activations", []) or []:
        if _id_key(activation.get("targetCode")) != "1":
            activation["application_status"] = "unsupported_target"
            continue
        modifier_code = activation.get("modifierCode")
        delta = _operation_delta(activation.get("op"), activation.get("value"))
        if modifier_code is None or delta is None:
            activation["application_status"] = "missing_modifier_delta"
            continue
        ship = next(
            (
                candidate
                for candidate in (row.get("attacker"), row.get("defender"))
                if isinstance(candidate, dict) and _ship_matches_log_id(candidate, activation.get("firing_ship_id"))
            ),
            None,
        )
        if ship is None:
            activation["application_status"] = "ship_not_found"
            continue
        resolved = ship.setdefault("resolved_modifiers", {})
        resolved[_id_key(modifier_code)] = _report_number(delta)
        activation["application_status"] = "applied"



def _iter_deployed_fleets(fleet_data: dict[str, Any]) -> list[dict[str, Any]]:
    deployed_fleets = []
    seen = set()
    for deployed in [fleet_data.get("deployed_fleet"), *(fleet_data.get("deployed_fleets") or {}).values()]:
        if not isinstance(deployed, dict) or id(deployed) in seen:
            continue
        deployed_fleets.append(deployed)
        seen.add(id(deployed))
    return deployed_fleets


def _ship_ids(deployed: dict[str, Any]) -> set[str]:
    return {_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])}


def _ordered_ship_ids_for_fleet_data(fleet_data: dict[str, Any]) -> list[str]:
    ordered_ids = []
    seen = set()
    for ship_id in fleet_data.get("ship_ids", []):
        key = _id_key(ship_id)
        if key not in seen:
            ordered_ids.append(key)
            seen.add(key)
    for deployed in _iter_deployed_fleets(fleet_data):
        for ship_id in deployed.get("ship_ids", []):
            key = _id_key(ship_id)
            if key not in seen:
                ordered_ids.append(key)
                seen.add(key)
    return ordered_ids


def _top_level_hull_id_for_ship(fleet_data: dict[str, Any], ship_id: str) -> str | None:
    ship_ids = [_id_key(value) for value in fleet_data.get("ship_ids", [])]
    hull_ids = [_id_key(value) for value in fleet_data.get("hull_ids", [])]
    if ship_id in ship_ids and len(ship_ids) == len(hull_ids):
        return hull_ids[ship_ids.index(ship_id)]
    return None


def _ship_ids_for_fleet_data(fleet_data: dict[str, Any]) -> set[str]:
    return set(_ordered_ship_ids_for_fleet_data(fleet_data))


def _looks_like_player_fleet_data(fleet_data: dict[str, Any]) -> bool:
    if any(ship_id != "0" for ship_id in _ordered_ship_ids_for_fleet_data(fleet_data)):
        return True
    for deployed in _iter_deployed_fleets(fleet_data):
        if deployed.get("active_buffs"):
            return True
    return False


def _active_buff_count(fleet_data: dict[str, Any]) -> int:
    return sum(
        len(deployed.get("active_buffs") or [])
        for deployed in _iter_deployed_fleets(fleet_data)
    )


def _id_prefix(value: Any) -> str:
    text = _id_key(value)
    if "_" not in text:
        return text if text else "unknown"
    return text.split("_", 1)[0]


def _combat_fleet_data(journal: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    initiator = journal["initiator_fleet_data"]
    target = journal["target_fleet_data"]
    initiator_active_buffs = _active_buff_count(initiator)
    target_active_buffs = _active_buff_count(target)
    if target_active_buffs and not initiator_active_buffs:
        return target, initiator, "target", "initiator"
    if initiator_active_buffs and not target_active_buffs:
        return initiator, target, "initiator", "target"

    initiator_is_player = _looks_like_player_fleet_data(initiator)
    target_is_player = _looks_like_player_fleet_data(target)
    if target_is_player and not initiator_is_player:
        return target, initiator, "target", "initiator"
    return initiator, target, "initiator", "target"


def _known_side_for_ship(ship_id: str, player_ids: set[str], hostile_ids: set[str]) -> str | None:
    if ship_id in player_ids:
        return "player"
    if ship_id in hostile_ids:
        return "hostile"
    return None


def _opposite_side(side: str) -> str:
    return "hostile" if side == "player" else "player"


def _is_synthetic_ship_id(ship_id: str) -> bool:
    return ship_id.startswith("-")


def _canonical_ship_id_for_side(ship_id: str, fleet_data: dict[str, Any]) -> str:
    side_ids = _ordered_ship_ids_for_fleet_data(fleet_data)
    if ship_id in side_ids:
        deployed_fleets = _iter_deployed_fleets(fleet_data)
        top_level_hull_id = _top_level_hull_id_for_ship(fleet_data, ship_id)
        if top_level_hull_id is not None:
            matching_deployed_ids = []
            for deployed in deployed_fleets:
                deployed_hull_ids = [_id_key(value) for value in deployed.get("hull_ids", [])]
                deployed_ship_ids = [_id_key(value) for value in deployed.get("ship_ids", [])]
                if top_level_hull_id in deployed_hull_ids and deployed_ship_ids:
                    matching_deployed_ids.append(deployed_ship_ids[deployed_hull_ids.index(top_level_hull_id)])
            if len(set(matching_deployed_ids)) == 1:
                return matching_deployed_ids[0]

        deployed_ship_sets = [tuple(sorted(_ship_ids(deployed))) for deployed in deployed_fleets]
        distinct_deployed_ship_sets = set(deployed_ship_sets)
        if all(ship_id not in ship_ids for ship_ids in distinct_deployed_ship_sets) and len(distinct_deployed_ship_sets) == 1:
            deployed_ship_ids = list(next(iter(distinct_deployed_ship_sets)))
            if len(deployed_ship_ids) == 1:
                return deployed_ship_ids[0]
        return ship_id
    if _is_synthetic_ship_id(ship_id) and len(side_ids) == 1:
        return side_ids[0]
    return ship_id


def _resolve_attack_participants(
    attack: dict[str, Any],
    player_fleet_data: dict[str, Any],
    hostile_fleet_data: dict[str, Any],
) -> dict[str, str]:
    player_ids = _ship_ids_for_fleet_data(player_fleet_data)
    hostile_ids = _ship_ids_for_fleet_data(hostile_fleet_data)
    attacker_log_id = attack["attacker_ship_id"]
    defender_log_id = attack["target_ship_id"]
    attacker_side = _known_side_for_ship(attacker_log_id, player_ids, hostile_ids)
    defender_side = _known_side_for_ship(defender_log_id, player_ids, hostile_ids)

    if attacker_side is None and defender_side is not None and _is_synthetic_ship_id(attacker_log_id):
        attacker_side = _opposite_side(defender_side)
    if defender_side is None and attacker_side is not None and _is_synthetic_ship_id(defender_log_id):
        defender_side = _opposite_side(attacker_side)
    if attacker_side is None:
        raise ValueError(f"battle_log attack references unknown attacker ship id {attacker_log_id}")
    if defender_side is None:
        raise ValueError(f"battle_log attack references unknown target ship id {defender_log_id}")

    attacker_fleet_data = player_fleet_data if attacker_side == "player" else hostile_fleet_data
    defender_fleet_data = player_fleet_data if defender_side == "player" else hostile_fleet_data
    return {
        "attacker_side": attacker_side,
        "defender_side": defender_side,
        "attacker_ship_id": _canonical_ship_id_for_side(attacker_log_id, attacker_fleet_data),
        "defender_ship_id": _canonical_ship_id_for_side(defender_log_id, defender_fleet_data),
        "attacker_log_ship_id": attacker_log_id,
        "defender_log_ship_id": defender_log_id,
    }


def _first_hull_id(deployed: dict[str, Any]) -> str:
    hull_ids = deployed.get("hull_ids", [])
    if not hull_ids:
        raise ValueError("deployed_fleet is missing hull_ids")
    return _id_key(hull_ids[0])


def _hull_id_for_ship(deployed: dict[str, Any], ship_id: str) -> str:
    ship_ids = [_id_key(value) for value in deployed.get("ship_ids", [])]
    hull_ids = [_id_key(value) for value in deployed.get("hull_ids", [])]
    if ship_id in ship_ids and len(ship_ids) == len(hull_ids):
        return hull_ids[ship_ids.index(ship_id)]
    return _first_hull_id(deployed)


def _deployed_fleet_for_ship(fleet_data: dict[str, Any], ship_id: str) -> dict[str, Any]:
    deployed_fleets = _iter_deployed_fleets(fleet_data)
    for deployed in deployed_fleets:
        if ship_id in _ship_ids(deployed):
            return deployed
    distinct_deployed_ship_sets = {tuple(sorted(_ship_ids(deployed))) for deployed in deployed_fleets}
    if ship_id in _ship_ids_for_fleet_data(fleet_data) and len(distinct_deployed_ship_sets) == 1 and deployed_fleets:
        return deployed_fleets[0]
    raise ValueError(f"no deployed_fleet found for ship id {ship_id}")


def _component_ids_for_ship(deployed: dict[str, Any], ship_id: str) -> list[Any] | None:
    return (deployed.get("ship_components") or {}).get(ship_id)


def _captured_stats(deployed: dict[str, Any], ship_id: str) -> dict[str, Any]:
    ship_stats = (deployed.get("ship_stats") or {}).get(ship_id, {})
    return {key: _number(value) for key, value in ship_stats.items()}


def _captured_fleet_stats(deployed: dict[str, Any]) -> dict[str, Any]:
    stats = deployed.get("stats") or {}
    return {key: _number(value) for key, value in stats.items()}


def _captured_fleet_attributes(deployed: dict[str, Any]) -> dict[str, Any]:
    attributes = deployed.get("attributes") or {}
    return {key: _number(value) for key, value in attributes.items()}


def _captured_fleet_ratings(deployed: dict[str, Any]) -> dict[str, Any]:
    ratings = {}
    modifier_codes = {}
    for field in FLEET_RATING_FIELDS:
        value = deployed.get(field)
        if value is None:
            continue
        number = _number(value)
        ratings[field] = number
        modifier_code = FLEET_RATING_MODIFIER_CODES.get(field)
        if modifier_code is not None:
            modifier_codes[modifier_code] = number
    if modifier_codes:
        ratings["modifier_codes"] = modifier_codes
    return ratings


def _status_effects(deployed: dict[str, Any]) -> dict[str, Any]:
    status_effects = deployed.get("status_effects") or {}
    if not isinstance(status_effects, dict):
        return {}
    return {_id_key(key): _number(value) for key, value in status_effects.items()}


def _active_ship_bonus_ids(deployed: dict[str, Any], static_ship: dict[str, Any]) -> list[str]:
    static_hull = (static_ship.get("hull") or {})
    ship_bonus_ids = set(static_hull.get("all_ship_bonus_ids") or static_hull.get("ship_bonus_ids") or [])
    if not ship_bonus_ids:
        return []
    active_ids = []
    for active_buff in deployed.get("active_buffs", []) or []:
        if not isinstance(active_buff, dict):
            continue
        buff_id = _id_key(active_buff.get("buff_id") if "buff_id" in active_buff else active_buff.get("buffId"))
        if buff_id in ship_bonus_ids:
            active_ids.append(buff_id)
    return sorted(set(active_ids))


def _ship_ref(
    *,
    catalog: dict[str, Any],
    fleet_data: dict[str, Any],
    ship_id: str,
    battle_log_ship_id: str | None = None,
) -> dict[str, Any]:
    deployed = _deployed_fleet_for_ship(fleet_data, ship_id)
    hull_id = _hull_id_for_ship(deployed, ship_id)
    component_ids = _component_ids_for_ship(deployed, ship_id)
    static_ship = build_static_ship(
        catalog,
        hull_id,
        component_ids=component_ids,
        ship_tier=(deployed.get("ship_tiers") or {}).get(ship_id),
        ship_level=(deployed.get("ship_levels") or {}).get(ship_id),
    )
    ship_ref = {
        "ship_id": int(ship_id) if ship_id.lstrip("-").isdigit() else ship_id,
        "hull_id": hull_id,
        "fleet_faction_id": fleet_data.get("faction_id"),
        "ship_level": (deployed.get("ship_levels") or {}).get(ship_id),
        "ship_tier": (deployed.get("ship_tiers") or {}).get(ship_id),
        "component_ids": [_id_key(component_id) for component_id in component_ids or []],
        "captured_stats": _captured_stats(deployed, ship_id),
        "captured_fleet_stats": _captured_fleet_stats(deployed),
        "captured_fleet_attributes": _captured_fleet_attributes(deployed),
        "captured_fleet_ratings": _captured_fleet_ratings(deployed),
        "status_effects": _status_effects(deployed),
        "active_ship_bonus_ids": _active_ship_bonus_ids(deployed, static_ship),
        "static_ship": static_ship,
    }
    if battle_log_ship_id is not None and battle_log_ship_id != ship_id:
        ship_ref["battle_log_ship_id"] = (
            int(battle_log_ship_id) if battle_log_ship_id.lstrip("-").isdigit() else battle_log_ship_id
        )
    return ship_ref


def _weapon_ref(static_ship: dict[str, Any], weapon_id: str) -> dict[str, Any]:
    for weapon in static_ship["weapons"]:
        if _id_key(weapon["id"]) == weapon_id:
            return weapon
    return {"id": int(weapon_id) if weapon_id.lstrip("-").isdigit() else weapon_id}


def _observation_rows_for_battle(
    *,
    catalog: dict[str, Any],
    officer_index: dict[str, Any],
    forbidden_tech_index: dict[str, dict[str, dict[str, Any]]],
    battle_path: Path,
    battle: dict[str, Any],
) -> list[dict[str, Any]]:
    journal = battle["journal"]
    player_fleet_data, hostile_fleet_data, player_battle_side, hostile_battle_side = _combat_fleet_data(journal)
    battle_id = str(journal.get("id") or battle_path.stem)
    rows = []

    for index, attack in enumerate(_iter_attacks(journal["battle_log"]), start=1):
        participants = _resolve_attack_participants(attack, player_fleet_data, hostile_fleet_data)
        attacker_side = participants["attacker_side"]
        defender_side = participants["defender_side"]
        attacker_fleet_data = player_fleet_data if attacker_side == "player" else hostile_fleet_data
        defender_fleet_data = player_fleet_data if defender_side == "player" else hostile_fleet_data
        attacker = _ship_ref(
            catalog=catalog,
            fleet_data=attacker_fleet_data,
            ship_id=participants["attacker_ship_id"],
            battle_log_ship_id=participants["attacker_log_ship_id"],
        )
        defender = _ship_ref(
            catalog=catalog,
            fleet_data=defender_fleet_data,
            ship_id=participants["defender_ship_id"],
            battle_log_ship_id=participants["defender_log_ship_id"],
        )

        observed = {
            "hit": attack["hit"],
            "critical": attack["critical"],
            "damage": {"shield": attack["shield_damage"], "hull": attack["hull_damage"]},
            "remaining": {"shield": attack["remaining_shield"], "hull": attack["remaining_hull"]},
            "observed_damage": attack["observed_damage"],
            "mitigated_damage": attack["mitigated_damage"],
            "raw_damage": attack["raw_damage"],
            "effective_mitigation": attack["effective_mitigation"],
            "accuracy_roll": attack["accuracy_roll"],
            "dodge_roll": attack["dodge_roll"],
            "isolytic_damage": attack["isolytic_damage"],
            "mitigated_isolytic_damage": attack["mitigated_isolytic_damage"],
            "mitigated_apex_barrier": attack["mitigated_apex_barrier"],
            "mitigated_critical_damage": attack["mitigated_critical_damage"],
            "mitigated_isolytic_critical_damage": attack["mitigated_isolytic_critical_damage"],
            "triggered_effects": attack["triggered_effects"],
        }
        officer_activations = _mapped_officer_activations(attack.get("officer_activations", []), officer_index)
        if officer_activations:
            observed["officer_activations"] = officer_activations
        forbidden_tech_activations = _mapped_forbidden_tech_activations(
            attack.get("forbidden_tech_activations", []),
            forbidden_tech_index,
        )
        if forbidden_tech_activations:
            observed["forbidden_tech_activations"] = forbidden_tech_activations
        observed["normal_mitigation"] = normal_mitigation_from_observed(observed)
        observed["isolytic_damage_model"] = isolytic_damage_model_from_observed(
            observed,
            attacker_stats=attacker.get("captured_fleet_stats", {}),
            attacker_stat_source="captured_fleet_stats",
        )

        battle_type = journal.get("battle_type")
        player_battle_data_type = player_fleet_data.get("battle_data_type")
        hostile_battle_data_type = hostile_fleet_data.get("battle_data_type")
        initiator_id = _id_key(journal.get("initiator_id"))
        target_id = _id_key(journal.get("target_id"))
        hostile_id = initiator_id if hostile_battle_side == "initiator" else target_id

        row = {
            "schema_version": 1,
            "battle_id": battle_id,
            "battle_path": str(battle_path),
            "server_version": battle.get("server_version"),
            "initiator_id": initiator_id,
            "target_id": target_id,
            "hostile_id": hostile_id,
            "hostile_id_prefix": _id_prefix(hostile_id),
            "battle_type": battle_type,
            "battle_type_name": battle_type_name(battle_type),
            "player_battle_side": player_battle_side,
            "hostile_battle_side": hostile_battle_side,
            "player_battle_data_type": player_battle_data_type,
            "player_battle_data_type_name": fleet_data_type_name(player_battle_data_type),
            "hostile_battle_data_type": hostile_battle_data_type,
            "hostile_battle_data_type_name": fleet_data_type_name(hostile_battle_data_type),
            "attack_index": index,
            "battle_round": attack["battle_round"],
            "sub_round": attack["sub_round"],
            "attacker_side": attacker_side,
            "defender_side": defender_side,
            "weapon": _weapon_ref(attacker["static_ship"], attack["weapon_id"]),
            "attacker": attacker,
            "defender": defender,
            "observed": observed,
        }
        _apply_forbidden_tech_activations(row)
        rows.append(row)

    return rows


def export_observations(
    *,
    decoded_static_dir: Path,
    capture_root: Path,
    buff_audit_path: Path | None = None,
) -> list[dict[str, Any]]:
    catalog = load_static_catalog(decoded_static_dir)
    officer_index = _officer_static_index(decoded_static_dir)
    forbidden_tech_index = _forbidden_tech_static_index(decoded_static_dir)
    rows = []
    for battle_path in sorted((capture_root / "battles").glob("*.json")):
        battle = _read_json(battle_path)
        rows.extend(
            _observation_rows_for_battle(
                catalog=catalog,
                officer_index=officer_index,
                forbidden_tech_index=forbidden_tech_index,
                battle_path=battle_path,
                battle=battle,
            )
        )
    if buff_audit_path is not None:
        rows = attach_resolved_player_states(rows, load_resolved_player_state_index(buff_audit_path))
    rows = apply_static_ship_bonuses_to_rows(rows, catalog)
    return rows


def write_observations_jsonl(*, observations: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in observations),
        encoding="utf-8",
    )
