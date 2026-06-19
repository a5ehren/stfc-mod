from __future__ import annotations

import json
from pathlib import Path
from typing import Any

START_ROUND = -96
END_ROUND = -97
START_ATTACK = -98
END_ATTACK = -99
ATTACK_CHARGE = -95
START_SUB_ROUND = -90
END_SUB_ROUND = -89
OFFICER_ABILITIES_FIRING = -93


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _to_int(value: Any) -> int:
    return int(round(float(value)))


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return bool(int(value))


def _base_mitigation(battle_config: dict[str, Any]) -> float:
    static_config = battle_config.get("battleConfig", {}).get("static", {})
    return float(static_config.get("base_mitigation", 0.0))


def _deployed_fleet(fleet_data: dict[str, Any]) -> dict[str, Any]:
    deployed = fleet_data.get("deployed_fleet")
    if not isinstance(deployed, dict):
        raise ValueError("battle journal fleet data is missing deployed_fleet")
    return deployed


def _ship_ids(fleet_data: dict[str, Any]) -> set[str]:
    deployed = _deployed_fleet(fleet_data)
    return {_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])}


def _first_ship_state(fleet_data: dict[str, Any]) -> dict[str, int]:
    deployed = _deployed_fleet(fleet_data)
    ship_ids = list(deployed.get("ship_ids", []))
    if ship_ids:
        ship_id = _id_key(ship_ids[0])
    else:
        hp_keys = list(deployed.get("ship_hps", {}).keys())
        if not hp_keys:
            raise ValueError("battle journal fleet data is missing ship_ids and ship_hps")
        ship_id = _id_key(hp_keys[0])

    hps = deployed.get("ship_hps", {})
    shields = deployed.get("ship_shield_hps", {})
    if ship_id not in hps or ship_id not in shields:
        raise ValueError(f"battle journal fleet data is missing hp/shield state for ship {ship_id}")

    return {"hull": _to_int(hps[ship_id]), "shield": _to_int(shields[ship_id])}


def _find_marker(log: list[Any], marker: int, start_index: int) -> int:
    try:
        return log.index(marker, start_index)
    except ValueError as exc:
        raise ValueError(f"battle_log marker {marker} has no matching terminator") from exc


def _is_charge_attack(values: list[Any]) -> bool:
    return len(values) >= 2 and values[1] == ATTACK_CHARGE


def _attack_effects(values: list[Any]) -> list[str]:
    effects = []
    if len(values) > 5 and _to_bool(values[5]):
        effects.append("critical")
    if OFFICER_ABILITIES_FIRING in values[16:]:
        effects.append("officer")
    if len(values) > 11 and _to_int(values[11]) > 0:
        effects.append("isolytic")
    return effects


def _iter_damage_attacks(log: list[Any]) -> list[dict[str, Any]]:
    attacks = []
    current_round = 0
    current_sub_round = 0
    i = 0

    while i < len(log):
        value = log[i]
        if value == START_ROUND:
            current_round += 1
            current_sub_round = 0
            i += 1
            continue
        if value == END_ROUND:
            i += 1
            continue
        if value == START_SUB_ROUND:
            current_sub_round += 1
            i += 1
            continue
        if value == END_SUB_ROUND:
            i += 1
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
        raw_damage = shield_damage + hull_damage + mitigated_damage

        attacks.append(
            {
                "battle_round": current_round,
                "sub_round": current_sub_round,
                "attacker_ship_id": _id_key(log[i - 1]),
                "target_ship_id": _id_key(values[1]),
                "weapon_id": _to_int(values[0]),
                "raw_damage": raw_damage,
                "mitigation": mitigated_damage / raw_damage if raw_damage else 0.0,
                "expected": {"shield": shield_damage, "hull": hull_damage},
                "triggered_effects": _attack_effects(values),
            }
        )
        i = end_index + 1

    return attacks


def _build_synthetic_fixture(
    *,
    decoded_static_dir: Path,
    battle_journal_path: Path,
    journal: dict[str, Any],
    mitigation: float,
) -> dict[str, Any]:

    rounds = []
    for round_data in journal["rounds"]:
        normalized = dict(round_data)
        normalized["mitigation"] = float(round_data.get("mitigation", mitigation))
        rounds.append(normalized)

    return {
        "schema_version": 1,
        "game_version": journal["game_version"],
        "source_payloads": [
            {"kind": "battle_config", "path": f"{decoded_static_dir.name}/BattleConfig.json"},
            {"kind": "battle_journal", "path": str(battle_journal_path)},
        ],
        "initial_state": journal["initial_state"],
        "rounds": rounds,
    }


def _build_raw_battle_log_fixture(
    *,
    decoded_static_dir: Path,
    battle_journal_path: Path,
    battle: dict[str, Any],
    journal: dict[str, Any],
) -> dict[str, Any]:
    initiator_ids = _ship_ids(journal["initiator_fleet_data"])
    target_ids = _ship_ids(journal["target_fleet_data"])
    rounds = []

    for attack_number, attack in enumerate(_iter_damage_attacks(journal["battle_log"]), start=1):
        attacker_ship_id = attack["attacker_ship_id"]
        if attacker_ship_id in initiator_ids:
            acting_side = "player"
        elif attacker_ship_id in target_ids:
            acting_side = "hostile"
        else:
            raise ValueError(f"battle_log attack uses unknown attacker ship id {attacker_ship_id}")

        triggered_effects = list(attack["triggered_effects"])
        rounds.append(
            {
                "round": attack_number,
                "battle_round": attack["battle_round"],
                "sub_round": attack["sub_round"],
                "acting_side": acting_side,
                "action": f"weapon:{attack['weapon_id']}",
                "raw_damage": attack["raw_damage"],
                "mitigation": attack["mitigation"],
                "expected": attack["expected"],
                "triggered_effects": triggered_effects,
                "expected_triggered_effects": triggered_effects,
            }
        )

    if not rounds:
        raise ValueError("battle journal battle_log did not contain any damage attacks")

    return {
        "schema_version": 1,
        "game_version": journal.get("game_version") or battle.get("server_version") or "unknown",
        "source_payloads": [
            {"kind": "battle_config", "path": f"{decoded_static_dir.name}/BattleConfig.json"},
            {"kind": "battle_journal", "path": str(battle_journal_path)},
        ],
        "initial_state": {
            "player": _first_ship_state(journal["initiator_fleet_data"]),
            "hostile": _first_ship_state(journal["target_fleet_data"]),
        },
        "rounds": rounds,
    }


def build_fixture(*, decoded_static_dir: Path, battle_journal_path: Path) -> dict[str, Any]:
    battle_config_path = decoded_static_dir / "BattleConfig.json"
    battle_config = _read_json(battle_config_path)
    battle = _read_json(battle_journal_path)
    journal = battle["journal"]

    if "initial_state" in journal and "rounds" in journal:
        return _build_synthetic_fixture(
            decoded_static_dir=decoded_static_dir,
            battle_journal_path=battle_journal_path,
            journal=journal,
            mitigation=_base_mitigation(battle_config),
        )

    if "battle_log" in journal:
        return _build_raw_battle_log_fixture(
            decoded_static_dir=decoded_static_dir,
            battle_journal_path=battle_journal_path,
            battle=battle,
            journal=journal,
        )

    raise ValueError("battle journal must contain either initial_state/rounds or battle_log")
