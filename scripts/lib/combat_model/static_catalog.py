from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


COMPARISON_FIELDS = (
    ("ship_hps", "hull_hp"),
    ("ship_shield_hps", "shield_hp"),
    ("stat_-3", "armor_plating"),
    ("stat_-2", "shield_absorption"),
    ("stat_6", "weapon_accuracy_max"),
    ("stat_7", "weapon_penetration_max"),
    ("stat_8", "weapon_modulation_max"),
    ("stat_9", "weapon_crit_chance_max"),
    ("stat_10", "weapon_crit_modifier_max"),
    ("stat_11", "dodge"),
)

HULL_TYPE_TOKENS = {
    "Battleship": "HULLTYPE_BATTLESHIP",
    "Destroyer": "HULLTYPE_DESTROYER",
    "Explorer": "HULLTYPE_EXPLORER",
    "Survey": "HULLTYPE_SURVEY",
}

SHIP_STAT_LOOKUP_PREFIXES = {
    "HULLTYPE_BATTLESHIP": "battleship",
    "HULLTYPE_DESTROYER": "destroyer",
    "HULLTYPE_EXPLORER": "explorer",
    "HULLTYPE_SURVEY": "survey",
    "HULLTYPE_DEFENSE": "defense",
}

SHIP_STAT_LOOKUP_SUFFIXES = {
    "weapon_accuracy_max": "Accuracy",
    "weapon_penetration_max": "Penetration",
    "weapon_modulation_max": "Modulation",
    "dodge": "Dodge",
    "armor_plating": "Plating",
    "shield_absorption": "Absorption",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_collection(decoded_static_dir: Path, source_table: str, collection_key: str) -> dict[str, Any] | None:
    path = decoded_static_dir / f"{source_table}.json"
    if not path.exists():
        return None
    collection = _read_json(path).get(collection_key, {})
    return collection if isinstance(collection, dict) else {}


def _read_optional_list(decoded_static_dir: Path, source_table: str, root_key: str, collection_key: str) -> list[Any] | None:
    path = decoded_static_dir / f"{source_table}.json"
    if not path.exists():
        return None
    root = _read_json(path).get(root_key, {})
    if not isinstance(root, dict):
        return []
    collection = root.get(collection_key, [])
    return collection if isinstance(collection, list) else []


def _read_optional_top_level_list(decoded_static_dir: Path, source_table: str, root_key: str) -> list[Any] | None:
    path = decoded_static_dir / f"{source_table}.json"
    if not path.exists():
        return None
    collection = _read_json(path).get(root_key, [])
    return collection if isinstance(collection, list) else []


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _dedupe_ids(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _component_type(component: dict[str, Any]) -> str:
    if "type" in component:
        return str(component["type"])
    if "armorSpec" in component:
        return "COMPONENTTYPE_ARMOR"
    return "COMPONENTTYPE_UNKNOWN"


def _component_summary(component_id: str, component: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": component_id,
        "name": component.get("name"),
        "type": _component_type(component),
        "grade": component.get("grade"),
        "rarity": component.get("rarity"),
        "tier": component.get("tier"),
    }


def _weapon_summary(component_id: str, component: dict[str, Any]) -> dict[str, Any]:
    attack = component.get("weaponSpec", {}).get("attack", {})
    return {
        "id": component_id,
        "name": component.get("name"),
        "minimum_damage": _number(attack.get("minimumDamage")),
        "maximum_damage": _number(attack.get("maximumDamage")),
        "shots": _number(attack.get("shots")),
        "warm_up": _number(attack.get("warmUp")),
        "cooldown": _number(attack.get("coolDown")),
        "accuracy": _number(attack.get("accuracy")),
        "penetration": _number(attack.get("penetration")),
        "modulation": _number(attack.get("modulation")),
        "crit_chance": _number(attack.get("critChance")),
        "crit_modifier": _number(attack.get("critModifier")),
    }


def _activated_ability_summary(ability_id: str, ability: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ability, dict):
        return {"id": ability_id, "status": "missing_static_spec"}
    return {
        "id": ability_id,
        "id_str": ability.get("idStr"),
        "ability_type": ability.get("abilityType"),
        "target_code": _id_key(ability.get("targetCode")),
        "status_effect": _id_key(ability.get("statusEffect")),
        "research_id": _id_key(ability.get("researchId")),
    }


def load_static_catalog(decoded_static_dir: Path) -> dict[str, Any]:
    activated_abilities = _read_optional_top_level_list(decoded_static_dir, "ActivatedAbilitySpecs", "spec") or []
    return {
        "hulls": _read_json(decoded_static_dir / "HullSpecs.json")["hullSpecs"],
        "components": _read_json(decoded_static_dir / "ComponentSpecs.json")["componentSpecs"],
        "activated_abilities": {
            _id_key(ability.get("id")): ability
            for ability in activated_abilities
            if isinstance(ability, dict) and ability.get("id") is not None
        },
        "ship_bonus_specs": _read_optional_collection(decoded_static_dir, "ShipBonusBuffSpecs", "shipBonusSpecs"),
        "base_ship_tiers": _read_optional_collection(decoded_static_dir, "BaseShipTierSpecs", "baseShipTierSpecs"),
        "ship_tiers": _read_optional_collection(decoded_static_dir, "ShipTierSpecs", "shipTierSpecs"),
        "officer_core_thresholds": _read_optional_collection(
            decoded_static_dir,
            "OfficerCoreStatThresholdsSpecs",
            "officerCoreStatThresholds",
        ),
        "client_ship_stat_lookup": _read_optional_list(
            decoded_static_dir,
            "ClientShipStatLookupSpecs",
            "clientShipStatLookupSpecs",
            "shipStats",
        ),
    }


def _component_source(
    *,
    status: str,
    component_id: str,
    component: dict[str, Any],
    field_path: str,
    value: Any = None,
) -> dict[str, Any]:
    source = {
        "status": status,
        "source_table": "ComponentSpecs",
        "component_id": component_id,
        "component_name": component.get("name"),
        "component_type": _component_type(component),
        "field_path": field_path,
    }
    if value is not None:
        source["value"] = value
    return source


def _set_component_stat(
    base_stats: dict[str, Any],
    stat_sources: dict[str, Any],
    *,
    key: str,
    value: Any,
    component_id: str,
    component: dict[str, Any],
    field_path: str,
) -> None:
    numeric = _number(value)
    if numeric is None:
        stat_sources.setdefault(
            key,
            _component_source(
                status="missing_static_field",
                component_id=component_id,
                component=component,
                field_path=field_path,
            ),
        )
        return

    base_stats[key] = numeric
    stat_sources[key] = _component_source(
        status="found",
        component_id=component_id,
        component=component,
        field_path=field_path,
        value=numeric,
    )


def _set_max_component_stat(
    base_stats: dict[str, Any],
    stat_sources: dict[str, Any],
    *,
    key: str,
    value: Any,
    component_id: str,
    component: dict[str, Any],
    field_path: str,
) -> None:
    numeric = _number(value)
    if numeric is None:
        stat_sources.setdefault(
            key,
            _component_source(
                status="missing_static_field",
                component_id=component_id,
                component=component,
                field_path=field_path,
            ),
        )
        return

    current = base_stats.get(key)
    if current is None or numeric > current:
        base_stats[key] = numeric
        stat_sources[key] = _component_source(
            status="found",
            component_id=component_id,
            component=component,
            field_path=field_path,
            value=numeric,
        )


def _weapon_stat_average(values: list[int | float], *, floor_fractional: bool) -> tuple[int | float, float, str]:
    raw_average = sum(float(value) for value in values) / len(values)
    if floor_fractional:
        return math.floor(raw_average), raw_average, "floor_average"
    average = int(raw_average) if raw_average.is_integer() else raw_average
    return average, raw_average, "exact_average"


def _set_average_weapon_stat(
    base_stats: dict[str, Any],
    stat_sources: dict[str, Any],
    *,
    key: str,
    weapon_key: str,
    weapons: list[dict[str, Any]],
    field_path: str,
    floor_fractional: bool = False,
) -> None:
    numeric_weapons = [
        {
            "id": weapon["id"],
            "name": weapon.get("name"),
            "value": _number(weapon.get(weapon_key)),
        }
        for weapon in weapons
        if _number(weapon.get(weapon_key)) is not None
    ]
    if not numeric_weapons:
        if weapons:
            stat_sources.setdefault(
                key,
                {
                    "status": "missing_static_field",
                    "source_table": "ComponentSpecs",
                    "component_ids": [weapon["id"] for weapon in weapons],
                    "component_names": [weapon.get("name") for weapon in weapons],
                    "component_type": "COMPONENTTYPE_WEAPON",
                    "field_path": field_path,
                },
            )
        return

    values = [weapon["value"] for weapon in numeric_weapons]
    average, raw_average, rounding = _weapon_stat_average(values, floor_fractional=floor_fractional)
    base_stats[key] = average
    if len(numeric_weapons) == 1:
        weapon = numeric_weapons[0]
        stat_sources[key] = {
            "status": "found",
            "source_table": "ComponentSpecs",
            "component_id": weapon["id"],
            "component_name": weapon.get("name"),
            "component_type": "COMPONENTTYPE_WEAPON",
            "field_path": field_path,
            "value": average,
            "raw_average": raw_average,
            "rounding": rounding,
        }
        return

    stat_sources[key] = {
        "status": "found_average",
        "source_table": "ComponentSpecs",
        "component_ids": [weapon["id"] for weapon in numeric_weapons],
        "component_names": [weapon.get("name") for weapon in numeric_weapons],
        "component_type": "COMPONENTTYPE_WEAPON",
        "field_path": field_path,
        "values": values,
        "value": average,
        "raw_average": raw_average,
        "rounding": rounding,
    }


def _tier_static_sources(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = {}
    for source_table, collection_key in (
        ("BaseShipTierSpecs", "base_ship_tiers"),
        ("ShipTierSpecs", "ship_tiers"),
    ):
        collection = catalog.get(collection_key)
        sources[source_table] = {
            "status": "missing_source_table" if collection is None else "found",
            "entries": 0 if collection is None else len(collection),
        }
    return sources


def _hull_type(hull: dict[str, Any]) -> tuple[str | None, str | None]:
    if hull.get("type"):
        return str(hull["type"]), "type"

    id_str = hull.get("idStr")
    if not isinstance(id_str, str):
        return None, None

    for token in id_str.split("_"):
        if token in HULL_TYPE_TOKENS:
            return HULL_TYPE_TOKENS[token], "idStr"
    return None, None


def _ship_tier_spec_for_hull(catalog: dict[str, Any], hull_id: str) -> dict[str, Any] | None:
    ship_tiers = catalog.get("ship_tiers")
    if not isinstance(ship_tiers, dict):
        return None

    direct = ship_tiers.get(hull_id)
    if isinstance(direct, dict):
        return direct

    for spec in ship_tiers.values():
        if isinstance(spec, dict) and spec.get("hullId") is not None and _id_key(spec.get("hullId")) == hull_id:
            return spec
    return None


def _selected_tier_stat_modifiers(
    *,
    catalog: dict[str, Any],
    hull_id: str,
    ship_tier: Any,
) -> dict[str, dict[str, Any]]:
    numeric_tier = _number(ship_tier)
    if numeric_tier is None:
        return {}

    tier_spec = _ship_tier_spec_for_hull(catalog, hull_id)
    if tier_spec is None:
        return {}

    tier_modifiers = tier_spec.get("tierStatModifiers") or {}
    if not isinstance(tier_modifiers, dict):
        return {}

    tier_entry = tier_modifiers.get(_id_key(numeric_tier))
    if not isinstance(tier_entry, dict):
        return {}

    stat_modifiers = tier_entry.get("statModifiers") or {}
    if not isinstance(stat_modifiers, dict):
        return {}

    modifiers = {}
    for modifier_code, value in stat_modifiers.items():
        numeric_value = _number(value)
        if numeric_value is None:
            continue
        code = _id_key(modifier_code)
        modifiers[code] = {
            "source_table": "ShipTierSpecs",
            "hull_id": hull_id,
            "ship_tier": numeric_tier,
            "modifierCode": code,
            "value": numeric_value,
        }
    return modifiers


def _client_ship_stat_lookup_entry(catalog: dict[str, Any], ship_level: Any) -> dict[str, Any] | None:
    numeric_level = _number(ship_level)
    if numeric_level is None:
        return None

    entries = catalog.get("client_ship_stat_lookup")
    if not isinstance(entries, list):
        return None

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_level = _number(entry.get("level"))
        if entry_level is not None and int(entry_level) == int(numeric_level):
            return entry
    return None


def _client_ship_stat_lookup_sources(
    *,
    catalog: dict[str, Any],
    hull_type: str | None,
    ship_level: Any,
) -> dict[str, dict[str, Any]]:
    if hull_type is None:
        return {}

    prefix = SHIP_STAT_LOOKUP_PREFIXES.get(hull_type)
    if prefix is None:
        return {}

    entry = _client_ship_stat_lookup_entry(catalog, ship_level)
    if entry is None:
        return {}

    numeric_level = _number(ship_level)
    sources = {}
    for static_field, suffix in SHIP_STAT_LOOKUP_SUFFIXES.items():
        lookup_field = f"{prefix}{suffix}"
        value = _number(entry.get(lookup_field))
        if value is None:
            continue
        sources[static_field] = {
            "status": "found",
            "source_table": "ClientShipStatLookupSpecs",
            "ship_level": numeric_level,
            "hull_type": hull_type,
            "lookup_field": lookup_field,
            "value": value,
        }
    return sources


def build_static_ship(
    catalog: dict[str, Any],
    hull_id: str,
    *,
    component_ids: list[Any] | None = None,
    ship_tier: Any = None,
    ship_level: Any = None,
) -> dict[str, Any]:
    hull_id = _id_key(hull_id)
    hull = catalog["hulls"][hull_id]
    raw_component_ids = component_ids if component_ids is not None else hull.get("componentDefaults", [])
    normalized_component_ids = [_id_key(component_id) for component_id in raw_component_ids if _id_key(component_id) != "-1"]

    components = []
    weapons = []
    base_stats: dict[str, Any] = {}
    stat_sources: dict[str, Any] = {}
    missing_component_ids = []

    for component_id in normalized_component_ids:
        component = catalog["components"].get(component_id)
        if component is None:
            missing_component_ids.append(component_id)
            continue

        components.append(_component_summary(component_id, component))

        if armor := component.get("armorSpec"):
            _set_component_stat(
                base_stats,
                stat_sources,
                key="hull_hp",
                value=armor.get("hp"),
                component_id=component_id,
                component=component,
                field_path="armorSpec.hp",
            )
            _set_component_stat(
                base_stats,
                stat_sources,
                key="armor_plating",
                value=armor.get("plating"),
                component_id=component_id,
                component=component,
                field_path="armorSpec.plating",
            )

        if shield := component.get("shieldSpec"):
            _set_component_stat(
                base_stats,
                stat_sources,
                key="shield_hp",
                value=shield.get("hp"),
                component_id=component_id,
                component=component,
                field_path="shieldSpec.hp",
            )
            _set_component_stat(
                base_stats,
                stat_sources,
                key="shield_absorption",
                value=shield.get("absorption"),
                component_id=component_id,
                component=component,
                field_path="shieldSpec.absorption",
            )
            _set_component_stat(
                base_stats,
                stat_sources,
                key="shield_mitigation",
                value=shield.get("mitigation"),
                component_id=component_id,
                component=component,
                field_path="shieldSpec.mitigation",
            )

        if impulse := component.get("impulseSpec"):
            _set_component_stat(
                base_stats,
                stat_sources,
                key="dodge",
                value=impulse.get("dodge"),
                component_id=component_id,
                component=component,
                field_path="impulseSpec.dodge",
            )
            _set_component_stat(
                base_stats,
                stat_sources,
                key="impulse",
                value=impulse.get("impulse"),
                component_id=component_id,
                component=component,
                field_path="impulseSpec.impulse",
            )

        if sensor := component.get("sensorSpec"):
            _set_component_stat(
                base_stats,
                stat_sources,
                key="sensor_rating",
                value=sensor.get("sensorRating"),
                component_id=component_id,
                component=component,
                field_path="sensorSpec.sensorRating",
            )

        if deflector := component.get("deflectorSpec"):
            _set_component_stat(
                base_stats,
                stat_sources,
                key="deflection",
                value=deflector.get("deflection"),
                component_id=component_id,
                component=component,
                field_path="deflectorSpec.deflection",
            )

        if component.get("weaponSpec"):
            weapon = _weapon_summary(component_id, component)
            weapons.append(weapon)

    for key, weapon_key, field_path, floor_fractional in (
        ("weapon_accuracy_max", "accuracy", "weaponSpec.attack.accuracy", True),
        ("weapon_penetration_max", "penetration", "weaponSpec.attack.penetration", True),
        ("weapon_modulation_max", "modulation", "weaponSpec.attack.modulation", True),
        ("weapon_crit_chance_max", "crit_chance", "weaponSpec.attack.critChance", False),
        ("weapon_crit_modifier_max", "crit_modifier", "weaponSpec.attack.critModifier", False),
    ):
        _set_average_weapon_stat(
            base_stats,
            stat_sources,
            key=key,
            weapon_key=weapon_key,
            weapons=weapons,
            field_path=field_path,
            floor_fractional=floor_fractional,
        )

    hull_type, hull_type_source = _hull_type(hull)
    activated_ability_ids = [_id_key(ability_id) for ability_id in hull.get("activatedAbilitiesIds", [])]
    activated_abilities = catalog.get("activated_abilities") or {}
    explicit_ship_bonus_ids = [_id_key(buff_id) for buff_id in hull.get("shipBonuses", [])]
    ship_bonus_specs = catalog.get("ship_bonus_specs") or {}
    implicit_ship_bonus_ids = []
    if hull_id not in explicit_ship_bonus_ids and hull_id in ship_bonus_specs:
        implicit_ship_bonus_ids.append(hull_id)
    all_ship_bonus_ids = _dedupe_ids([*explicit_ship_bonus_ids, *implicit_ship_bonus_ids])
    ship_bonus_sources = {
        buff_id: (
            "HullSpecs.shipBonuses"
            if buff_id in explicit_ship_bonus_ids
            else "ShipBonusBuffSpecs.hullId"
        )
        for buff_id in all_ship_bonus_ids
    }
    client_ship_stat_lookup_sources = _client_ship_stat_lookup_sources(
        catalog=catalog,
        hull_type=hull_type,
        ship_level=ship_level,
    )
    return {
        "hull": {
            "id": hull_id,
            "id_str": hull.get("idStr"),
            "name": hull.get("name"),
            "type": hull_type,
            "type_source": hull_type_source,
            "grade": hull.get("grade"),
            "rarity": hull.get("rarity"),
            "tier_max": hull.get("tierMax"),
            "core_stat_modifiers": hull.get("coreStatModifiers", []),
            "officer_core_thresholds": catalog.get("officer_core_thresholds") or {},
            "ship_bonus_ids": explicit_ship_bonus_ids,
            "implicit_ship_bonus_ids": implicit_ship_bonus_ids,
            "all_ship_bonus_ids": all_ship_bonus_ids,
            "ship_bonus_sources": ship_bonus_sources,
            "activatedAbilitiesIds": activated_ability_ids,
            "activated_ability_ids": activated_ability_ids,
            "activated_abilities": [
                _activated_ability_summary(ability_id, activated_abilities.get(ability_id))
                for ability_id in activated_ability_ids
            ],
        },
        "component_ids": normalized_component_ids,
        "missing_component_ids": missing_component_ids,
        "components": components,
        "weapons": weapons,
        "base_stats": base_stats,
        "stat_sources": stat_sources,
        "tier_static_sources": _tier_static_sources(catalog),
        "tier_stat_modifiers_by_code": _selected_tier_stat_modifiers(
            catalog=catalog, hull_id=hull_id, ship_tier=ship_tier
        ),
        "client_ship_stat_lookup_sources": client_ship_stat_lookup_sources,
    }


def _deployed_fleet(journal: dict[str, Any], side: str) -> dict[str, Any]:
    key = "target_fleet_data" if side == "target" else "initiator_fleet_data"
    return journal[key]["deployed_fleet"]


def _ship_stat(stats: dict[str, Any], key: str) -> Any:
    return stats.get(key.removeprefix("stat_"))


def _captured_values(deployed: dict[str, Any], ship_id: str) -> dict[str, Any]:
    ship_stats = (deployed.get("ship_stats") or {}).get(ship_id, {})
    values = {
        "ship_hps": (deployed.get("ship_hps") or {}).get(ship_id),
        "ship_shield_hps": (deployed.get("ship_shield_hps") or {}).get(ship_id),
    }
    for key, _static_key in COMPARISON_FIELDS:
        if key.startswith("stat_"):
            values[key] = _ship_stat(ship_stats, key)
    return {key: _number(value) for key, value in values.items() if value is not None}


def _compare_values(captured: Any, static: Any) -> dict[str, Any]:
    captured_number = _number(captured)
    static_number = _number(static)
    if captured_number is None or static_number is None:
        return {"status": "missing", "captured": captured_number, "static": static_number}

    delta = captured_number - static_number
    relative_delta = 0 if static_number == 0 and captured_number == 0 else None
    if static_number:
        relative_delta = delta / static_number

    return {
        "status": "exact" if abs(delta) < 1e-9 else "mismatch",
        "captured": captured_number,
        "static": static_number,
        "delta": delta,
        "relative_delta": relative_delta,
    }


def _sample_from_deployed(
    *,
    catalog: dict[str, Any],
    battle: dict[str, Any],
    side: str,
    deployed: dict[str, Any],
) -> dict[str, Any]:
    ship_ids = [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])]
    hull_ids = [_id_key(hull_id) for hull_id in deployed.get("hull_ids", [])]
    if not ship_ids or not hull_ids:
        raise ValueError(f"{side} deployed_fleet is missing ship_ids or hull_ids")

    ship_id = ship_ids[0]
    hull_id = hull_ids[0]
    component_ids = (deployed.get("ship_components") or {}).get(ship_id)
    static_ship = build_static_ship(
        catalog,
        hull_id,
        component_ids=component_ids,
        ship_tier=(deployed.get("ship_tiers") or {}).get(ship_id),
        ship_level=(deployed.get("ship_levels") or {}).get(ship_id),
    )
    captured = _captured_values(deployed, ship_id)
    comparisons = []

    for captured_key, static_key in COMPARISON_FIELDS:
        result = _compare_values(captured.get(captured_key), static_ship["base_stats"].get(static_key))
        comparisons.append(
            {
                "captured_field": captured_key,
                "static_field": static_key,
                **result,
            }
        )

    return {
        "battle_id": str(battle.get("journal", {}).get("id") or Path(str(battle.get("_path", ""))).stem),
        "server_version": battle.get("server_version"),
        "side": side,
        "ship_id": ship_id,
        "hull_id": hull_id,
        "level": (deployed.get("ship_levels") or {}).get(ship_id),
        "tier": (deployed.get("ship_tiers") or {}).get(ship_id),
        "captured": {
            "component_ids": component_ids or [],
            "values": captured,
        },
        "static_ship": static_ship,
        "comparisons": comparisons,
    }


def _summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    compared_fields = 0
    exact_matches = 0
    mismatches = 0
    missing = 0
    missing_components = 0

    for sample in samples:
        missing_components += len(sample["static_ship"]["missing_component_ids"])
        for comparison in sample["comparisons"]:
            if comparison["status"] == "exact":
                exact_matches += 1
                compared_fields += 1
            elif comparison["status"] == "mismatch":
                mismatches += 1
                compared_fields += 1
            else:
                missing += 1

    return {
        "ship_samples": len(samples),
        "unique_hulls": len({sample["hull_id"] for sample in samples}),
        "compared_fields": compared_fields,
        "exact_matches": exact_matches,
        "mismatches": mismatches,
        "missing_fields": missing,
        "missing_static_components": missing_components,
    }


def compare_static_catalog(
    *,
    decoded_static_dir: Path,
    capture_root: Path,
    side: str = "target",
) -> dict[str, Any]:
    catalog = load_static_catalog(decoded_static_dir)
    samples = []
    sides = ("initiator", "target") if side == "both" else (side,)

    for path in sorted((capture_root / "battles").glob("*.json")):
        battle = _read_json(path)
        battle["_path"] = str(path)
        journal = battle["journal"]
        for selected_side in sides:
            samples.append(
                _sample_from_deployed(
                    catalog=catalog,
                    battle=battle,
                    side=selected_side,
                    deployed=_deployed_fleet(journal, selected_side),
                )
            )

    return {
        "schema_version": 1,
        "decoded_static_dir": str(decoded_static_dir),
        "capture_root": str(capture_root),
        "side": side,
        "summary": _summarize(samples),
        "samples": samples,
    }
