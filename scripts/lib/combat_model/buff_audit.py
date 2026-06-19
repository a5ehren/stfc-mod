from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..dump_enrichment import load_condition_code_map, load_numeric_symbol_index, symbol_candidates_for
from .modifier_types import load_client_modifier_types, modifier_type_for
from .static_catalog import build_static_ship, load_static_catalog


BUFF_SOURCE_DEFINITIONS = (
    {
        "source_table": "OfficerAbilityBuffSpecs",
        "source_type": "officer_ability",
        "collection_keys": ("officerAbilitySpecs",),
    },
    {
        "source_table": "ForbiddenTechBuffs",
        "source_type": "forbidden_tech",
        "collection_keys": ("forbiddenTechBuffsSpecs",),
    },
    {
        "source_table": "ResearchSpecs",
        "source_type": "research",
        "collection_keys": ("researchEffects",),
    },
    {
        "source_table": "ShipBonusBuffSpecs",
        "source_type": "ship_bonus",
        "collection_keys": ("shipBonusSpecs",),
    },
    {
        "source_table": "ShipLevelUpBonusBuffsSpecs",
        "source_type": "ship_level_up_bonus",
        "collection_keys": ("shipLevelUpBonusBuffSpecs",),
    },
    {
        "source_table": "StarbaseBuffs",
        "source_type": "starbase",
        "collection_keys": ("starbaseBuffsSpecs",),
    },
    {
        "source_table": "ConsumableBuffs",
        "source_type": "consumable",
        "collection_keys": ("consumableBuffsSpecs",),
    },
)

SUPPORTING_SOURCE_DEFINITIONS = (
    {
        "source_table": "HullSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("hullSpecs",),
    },
    {
        "source_table": "BaseShipTierSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("baseShipTierSpecs",),
    },
    {
        "source_table": "ShipTierSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("shipTierSpecs",),
    },
    {
        "source_table": "BuffTargetSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("buffTargetSpecs",),
    },
    {
        "source_table": "BuffTriggerSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("buffTriggerSpecs",),
    },
    {
        "source_table": "OfficerSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("officerSpecs",),
    },
    {
        "source_table": "OfficerCoreStatSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("officerCoreStatSpecs",),
    },
    {
        "source_table": "OfficerCoreStatThresholdsSpecs",
        "source_type": "supporting_static",
        "collection_keys": ("officerCoreStatThresholds",),
    },
    {
        "source_table": "ActivatedAbilitySpecs",
        "source_type": "supporting_static",
        "collection_keys": ("spec",),
    },
)

LIVE_STAT_FIELDS = (
    ("-3", "armor_plating"),
    ("-2", "shield_absorption"),
    ("6", "weapon_accuracy_max"),
    ("7", "weapon_penetration_max"),
    ("8", "weapon_modulation_max"),
    ("9", "weapon_crit_chance_max"),
    ("10", "weapon_crit_modifier_max"),
    ("11", "dodge"),
    ("60", "shield_hp"),
    ("61", "hull_hp"),
)

RELATED_LIVE_STAT_MODIFIER_CODES = {
    "7": {"74"},  # CLIENTMODIFIERTYPE_MODALLPIERCING
    "8": {"74"},  # CLIENTMODIFIERTYPE_MODALLPIERCING
    "11": {"12", "73"},  # CLIENTMODIFIERTYPE_MODSHIPARMOR, CLIENTMODIFIERTYPE_MODALLDEFENSES
    "12": {"73"},  # CLIENTMODIFIERTYPE_MODALLDEFENSES
    "13": {"73"},  # CLIENTMODIFIERTYPE_MODALLDEFENSES
}

LIVE_STAT_CLOSE_ABS_TOLERANCE = 1e-9
LIVE_STAT_CLOSE_REL_TOLERANCE = 1e-6
STATIC_BUFF_SUBSET_DIAGNOSTIC_MAX_BUFFS = 12
BUFF_AUDIT_DETAILS = ("full", "simulator")

CORE_STAT_TYPES = {
    1: "ATTACK",
    2: "DEFENSE",
    3: "HEALTH",
    "OFFICERCORESTATTYPE_ATTACK": "ATTACK",
    "OFFICERCORESTATTYPE_DEFENSE": "DEFENSE",
    "OFFICERCORESTATTYPE_HEALTH": "HEALTH",
}

CORE_STAT_ENUM_NAMES = {
    "ATTACK": "OFFICERCORESTATTYPE_ATTACK",
    "DEFENSE": "OFFICERCORESTATTYPE_DEFENSE",
    "HEALTH": "OFFICERCORESTATTYPE_HEALTH",
}

CORE_STAT_STATIC_KEYS = {
    "ATTACK": "1",
    "DEFENSE": "2",
    "HEALTH": "3",
}

CORE_STAT_FLEET_MODIFIERS = {
    "ATTACK": ("-15", "CLIENTMODIFIERTYPE_FLEETOFFICERBONUSATTACK"),
    "DEFENSE": ("-16", "CLIENTMODIFIERTYPE_FLEETOFFICERBONUSDEFENSE"),
    "HEALTH": ("-17", "CLIENTMODIFIERTYPE_FLEETOFFICERBONUSHEALTH"),
}

CORE_STAT_RELEVANT_LIVE_STATS = {
    "ATTACK": {"-1", "2", "6", "7", "8", "9", "10"},
    "DEFENSE": {"-2", "-3", "11", "12", "13", "73"},
    "HEALTH": {"60", "61"},
}

SERENE_SQUALL_HULL_ID = "697653604"
SERENE_SQUALL_WARSHIELD_ABILITY_ID = "3488429048"
SERENE_SQUALL_WARSHIELD_STATUS_EFFECT = "4"
SERENE_SQUALL_WARSHIELD_DODGE_BUFF_ID = "804797682"
SERENE_SQUALL_WARSHIELD_DODGE_MULTIPLIER = 1.75
SERENE_SQUALL_WARSHIELD_DODGE_STAT_CODE = "11"
SERENE_SQUALL_WARSHIELD_DEFENSE_MULTIPLIER = 2.5
SERENE_SQUALL_WARSHIELD_DEFENSE_STAT_CODES = {"-2", "-3"}
SERENE_SQUALL_WARSHIELD_DEFENSE_BUFF_IDS = {
    "-2": "2307361409",
    "-3": "3913316913",
}

RARITY_CORE_STAT_KEYS = {
    "RARITY_COMMON": "1",
    "RARITY_UNCOMMON": "2",
    "RARITY_RARE": "3",
    "RARITY_EPIC": "4",
    "RARITY_LEGENDARY": "5",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _capture_game_version(battle_paths: list[Path]) -> str | None:
    for battle_path in battle_paths:
        battle = _read_json(battle_path)
        version = battle.get("server_version") or (battle.get("journal") or {}).get("game_version")
        if version:
            return _id_key(version)
    return None


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


def _numbers_close(left: int | float | None, right: int | float | None, *, tolerance: float = 1e-9) -> bool:
    return left is not None and right is not None and abs(float(left) - float(right)) <= tolerance


def _residual_closed(residual: int | float | None, captured: int | float | None) -> bool:
    if residual is None:
        return False
    tolerance = LIVE_STAT_CLOSE_ABS_TOLERANCE
    if captured is not None:
        tolerance = max(tolerance, abs(float(captured)) * LIVE_STAT_CLOSE_REL_TOLERANCE)
    return abs(float(residual)) <= tolerance


def _core_stat_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value.isdigit():
            return CORE_STAT_TYPES.get(int(value))
        return CORE_STAT_TYPES.get(value)
    if isinstance(value, int | float):
        return CORE_STAT_TYPES.get(int(value))
    return None


def _core_stat_rank_types(ranks: list[int]) -> list[str]:
    seen = set()
    values = []
    for rank in ranks:
        core_type = _core_stat_type(rank)
        if core_type is None or core_type in seen:
            continue
        seen.add(core_type)
        values.append(core_type)
    return values


def _optional_static_collection(decoded_static_dir: Path, source_table: str, collection_key: str) -> dict[str, Any]:
    path = decoded_static_dir / f"{source_table}.json"
    if not path.exists():
        return {}
    data = _read_json(path)
    collection = data.get(collection_key, {})
    return collection if isinstance(collection, dict) else {}


def _optional_static_list(decoded_static_dir: Path, source_table: str, collection_key: str) -> list[Any]:
    path = decoded_static_dir / f"{source_table}.json"
    if not path.exists():
        return []
    data = _read_json(path)
    collection = data.get(collection_key, [])
    return collection if isinstance(collection, list) else []


def _load_generated_buff_context(decoded_static_dir: Path) -> dict[str, Any]:
    return {
        "hulls": _optional_static_collection(decoded_static_dir, "HullSpecs", "hullSpecs"),
        "officers": _optional_static_collection(decoded_static_dir, "OfficerSpecs", "officerSpecs"),
        "officer_core_stats": _optional_static_collection(
            decoded_static_dir, "OfficerCoreStatSpecs", "officerCoreStatSpecs"
        ),
        "officer_core_thresholds": _optional_static_collection(
            decoded_static_dir, "OfficerCoreStatThresholdsSpecs", "officerCoreStatThresholds"
        ),
        "activated_abilities": _optional_static_list(decoded_static_dir, "ActivatedAbilitySpecs", "spec"),
    }


def _code_spec_summary(
    *,
    source_table: str,
    collection_key: str,
    source_key: str,
    spec: dict[str, Any],
) -> dict[str, Any] | None:
    code = spec.get("code")
    if code is None:
        return None
    summary = {
        "status": "found",
        "source_table": source_table,
        "source_key": f"{collection_key}/{source_key}",
        "code": _number(code),
        "id": _id_key(spec.get("id")) if spec.get("id") is not None else _id_key(source_key),
        "idStr": spec.get("idStr"),
    }
    if spec.get("schema") is not None:
        summary["schema"] = spec.get("schema")
    return summary


def _code_specs_by_code(decoded_static_dir: Path, source_table: str, collection_key: str) -> dict[str, dict[str, Any]]:
    specs = _optional_static_collection(decoded_static_dir, source_table, collection_key)
    by_code = {}
    for source_key, spec in specs.items():
        if not isinstance(spec, dict):
            continue
        summary = _code_spec_summary(
            source_table=source_table,
            collection_key=collection_key,
            source_key=str(source_key),
            spec=spec,
        )
        if summary is None:
            continue
        by_code[_id_key(summary["code"])] = summary
    return by_code


def _load_static_code_context(decoded_static_dir: Path) -> dict[str, Any]:
    return {
        "targets_by_code": _code_specs_by_code(decoded_static_dir, "BuffTargetSpecs", "buffTargetSpecs"),
        "triggers_by_code": _code_specs_by_code(decoded_static_dir, "BuffTriggerSpecs", "buffTriggerSpecs"),
    }


def _code_spec_for(context: dict[str, Any], collection: str, code: Any) -> dict[str, Any] | None:
    if code is None:
        return None
    return context.get(collection, {}).get(_id_key(code), {"status": "missing_code_spec", "code": _number(code)})


def _modifier_type_summary(code: Any, modifier_types: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return modifier_type_for(code, modifier_types)


def _modifier_name(code: Any, modifier_types: dict[str, dict[str, Any]]) -> str | None:
    return _modifier_type_summary(code, modifier_types).get("enum_name")


def _modifier_original_name(code: Any, modifier_types: dict[str, dict[str, Any]]) -> str | None:
    return _modifier_type_summary(code, modifier_types).get("original_name")


def _modifier_summaries(codes: list[Any], modifier_types: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [_modifier_type_summary(code, modifier_types) for code in codes]


def _source_roots(data: dict[str, Any], collection_keys: tuple[str, ...]) -> list[tuple[str, Any]]:
    roots = []
    for key in collection_keys:
        if key in data:
            roots.append((key, data[key]))
    return roots


def _collection_entries(value: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        return [(str(key), entry) for key, entry in value.items() if isinstance(entry, dict)]
    if isinstance(value, list):
        return [(str(index), entry) for index, entry in enumerate(value) if isinstance(entry, dict)]
    return []


def _collection_entry_count(data: dict[str, Any], collection_keys: tuple[str, ...]) -> int:
    count = 0
    for _root_key, root_value in _source_roots(data, collection_keys):
        if isinstance(root_value, dict | list):
            count += len(root_value)
        else:
            count += 1
    return count


def _looks_like_buff_spec(value: dict[str, Any]) -> bool:
    return "buffId" in value or {"targetCode", "triggerCode", "op", "modifierCode"}.issubset(value.keys())


def _iter_buff_specs(value: Any, path: tuple[str, ...] = ()) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, dict):
        if _looks_like_buff_spec(value):
            specs.append(("/".join(path), value))
            return specs
        for key, nested in value.items():
            specs.extend(_iter_buff_specs(nested, (*path, str(key))))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            specs.extend(_iter_buff_specs(nested, (*path, str(index))))
    return specs


def _buff_id_from_spec(source_key: str, spec: dict[str, Any]) -> str | None:
    buff_id = spec.get("buffId")
    if buff_id is None:
        parts = [part for part in source_key.split("/") if part]
        buff_id = parts[-1] if parts else None
    if buff_id is None:
        return None
    return _id_key(buff_id)


def _duplicate_source(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_table": entry["source_table"],
        "source_type": entry["source_type"],
        "source_key": entry["source_key"],
        "source_precedence": entry["source_precedence"],
    }


def _translation_key(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _load_localization_index(decoded_static_dir: Path) -> dict[str, dict[str, str]]:
    path = decoded_static_dir / "LocalizationCacheData.json"
    if not path.exists():
        return {}

    data = _read_json(path)
    language = str(data.get("language") or "")
    translations: dict[str, dict[str, str]] = {}
    categories = data.get("categories", {})
    if not isinstance(categories, dict):
        return translations

    for category_id, category in categories.items():
        if not isinstance(category, dict):
            continue
        category_name = ""
        info = category.get("info")
        if isinstance(info, dict):
            category_name = str(info.get("name") or "")
        source_parts = ["LocalizationCacheData"]
        if language:
            source_parts.append(language)
        source = ":".join(source_parts)
        source = f"{source}/{category_name or category_id}"
        category_translations = category.get("translations", {})
        if not isinstance(category_translations, dict):
            continue
        for translation_key, translation in category_translations.items():
            if not isinstance(translation, dict):
                continue
            text = translation.get("text")
            if text is None:
                continue
            key = _translation_key(translation.get("key") if translation.get("key") is not None else translation_key)
            translations[key] = {"text": str(text), "source": source}

    return translations


def _localization_source_summary(decoded_static_dir: Path) -> dict[str, Any]:
    path = decoded_static_dir / "LocalizationCacheData.json"
    if not path.exists():
        return {
            "status": "missing_source_table",
            "source_type": "supporting_static",
            "entries": 0,
            "categories": 0,
            "indexed": 0,
            "source_precedence": None,
        }

    data = _read_json(path)
    categories = data.get("categories", {})
    category_count = len(categories) if isinstance(categories, dict) else 0
    translation_count = 0
    if isinstance(categories, dict):
        for category in categories.values():
            if not isinstance(category, dict):
                continue
            translations = category.get("translations", {})
            if isinstance(translations, dict):
                translation_count += len(translations)

    return {
        "status": "found",
        "source_type": "supporting_static",
        "entries": translation_count,
        "categories": category_count,
        "indexed": 0,
        "source_precedence": None,
    }


def _localized_id_refs(id_refs: Any, localization: dict[str, dict[str, str]]) -> Any:
    if not isinstance(id_refs, dict) or not localization:
        return id_refs

    enriched = dict(id_refs)
    for ref_key, text_key, source_key in (
        ("locaId", "locaText", "locaTextSource"),
        ("artId", "artText", "artTextSource"),
    ):
        ref_value = enriched.get(ref_key)
        translation = localization.get(_translation_key(ref_value))
        if translation is None:
            continue
        enriched[text_key] = translation["text"]
        enriched[source_key] = translation["source"]
    return enriched


def _research_tree_summary(source_key: str, tree: dict[str, Any], localization: dict[str, dict[str, str]]) -> dict[str, Any]:
    tree_id = tree.get("id")
    return {
        "status": "found",
        "id": _id_key(tree_id) if tree_id is not None else _id_key(source_key),
        "source_key": f"researchTrees/{source_key}",
        "idRefs": _localized_id_refs(tree.get("idRefs", {}), localization),
        "viewLevel": tree.get("viewLevel"),
        "factionId": tree.get("factionId"),
        "entityType": tree.get("entityType"),
        "entityId": tree.get("entityId"),
    }


def _research_project_summary(
    *,
    source_key: str,
    project: dict[str, Any],
    trees_by_id: dict[str, dict[str, Any]],
    localization: dict[str, dict[str, str]],
) -> dict[str, Any]:
    project_id = project.get("id")
    tree_id = project.get("researchTreeId")
    levels = project.get("levels", [])
    levels_count = len(levels) if isinstance(levels, list) else 0
    return {
        "status": "found",
        "id": _id_key(project_id) if project_id is not None else _id_key(source_key),
        "source_key": f"researchProjects/{source_key}",
        "researchTreeId": _id_key(tree_id) if tree_id is not None else None,
        "idRefs": _localized_id_refs(project.get("idRefs", {}), localization),
        "viewLevel": project.get("viewLevel"),
        "levels_count": levels_count,
        "buffEffectsIds": [_id_key(buff_id) for buff_id in project.get("buffEffectsIds", [])],
        "tree": trees_by_id.get(
            _id_key(tree_id) if tree_id is not None else "",
            {
                "status": "missing_research_tree",
                "id": _id_key(tree_id) if tree_id is not None else None,
            },
        ),
    }


def _research_source_contexts(decoded_static_dir: Path, localization: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    path = decoded_static_dir / "ResearchSpecs.json"
    if not path.exists():
        return {}

    data = _read_json(path)
    trees_by_id = {}
    for source_key, tree in _collection_entries(data.get("researchTrees")):
        summary = _research_tree_summary(source_key, tree, localization)
        trees_by_id[summary["id"]] = summary

    projects_by_buff_id: dict[str, list[dict[str, Any]]] = {}
    for source_key, project in _collection_entries(data.get("researchProjects")):
        summary = _research_project_summary(
            source_key=source_key,
            project=project,
            trees_by_id=trees_by_id,
            localization=localization,
        )
        for buff_id in summary["buffEffectsIds"]:
            projects_by_buff_id.setdefault(buff_id, []).append(summary)

    contexts = {}
    for buff_id, projects in projects_by_buff_id.items():
        contexts[buff_id] = {
            "status": "found",
            "research_projects": sorted(projects, key=lambda project: project["id"]),
        }
    return contexts


OFFICER_ABILITY_FIELDS = ("captainManeuverId", "officerAbilityId", "belowDecksAbilityId")


def _officer_ability_summary(
    source_key: str,
    officer: dict[str, Any],
    ability_field: str,
    localization: dict[str, dict[str, str]],
) -> dict[str, Any]:
    officer_id = officer.get("id")
    return {
        "id": _id_key(officer_id) if officer_id is not None else _id_key(source_key),
        "source_key": f"officerSpecs/{source_key}",
        "ability_field": ability_field,
        "idRefs": _localized_id_refs(officer.get("idRefs", {}), localization),
        "rarity": officer.get("rarity"),
        "officerClassType": officer.get("officerClassType"),
        "officerType": officer.get("officerType"),
        "factionId": officer.get("factionId"),
    }


def _officer_ability_source_contexts(
    decoded_static_dir: Path, localization: dict[str, dict[str, str]]
) -> dict[str, dict[str, Any]]:
    officers = _optional_static_collection(decoded_static_dir, "OfficerSpecs", "officerSpecs")
    contexts: dict[str, dict[str, Any]] = {}
    for source_key, officer in officers.items():
        if not isinstance(officer, dict):
            continue
        for ability_field in OFFICER_ABILITY_FIELDS:
            ability_id = officer.get(ability_field)
            if ability_id is None or _id_key(ability_id) == "-1":
                continue
            buff_id = _id_key(ability_id)
            context = contexts.setdefault(buff_id, {"status": "found", "officers": []})
            context["officers"].append(_officer_ability_summary(str(source_key), officer, ability_field, localization))

    for context in contexts.values():
        context["officers"] = sorted(context["officers"], key=lambda officer: (officer["id"], officer["ability_field"]))
    return contexts


def _load_source_contexts(decoded_static_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    localization = _load_localization_index(decoded_static_dir)
    return {
        "localization": {"_index": localization},
        "officer_ability": _officer_ability_source_contexts(decoded_static_dir, localization),
        "research": _research_source_contexts(decoded_static_dir, localization),
    }


def _buff_spec_source_context(buff_id: str, spec: dict[str, Any], localization: dict[str, dict[str, str]]) -> dict[str, Any]:
    context = {"buff_id": buff_id}
    if spec.get("idRefs") is not None:
        context["idRefs"] = _localized_id_refs(spec.get("idRefs"), localization)
    if spec.get("attributes") is not None:
        context["attributes"] = spec.get("attributes")
    if spec.get("showPercentage") is not None:
        context["showPercentage"] = spec.get("showPercentage")
    return context


def _source_context_for_buff(
    source_contexts: dict[str, dict[str, dict[str, Any]]],
    source_type: str,
    buff_id: str,
    spec: dict[str, Any],
) -> dict[str, Any] | None:
    localization = source_contexts.get("localization", {}).get("_index", {})
    buff_spec_context = _buff_spec_source_context(buff_id, spec, localization)
    if source_type == "officer_ability":
        context = source_contexts.get("officer_ability", {}).get(buff_id)
        if context is None:
            return None
        return {**context, "buff_spec": buff_spec_context}
    if source_type == "research":
        context = source_contexts.get("research", {}).get(
            buff_id,
            {
                "status": "missing_research_project_backref",
                "research_projects": [],
            },
        )
        return {**context, "buff_spec": buff_spec_context}
    if source_type in {
        "forbidden_tech",
        "ship_bonus",
        "ship_level_up_bonus",
        "starbase",
        "consumable",
    }:
        return {"status": "buff_spec_only", "buff_spec": buff_spec_context}
    return None


def build_static_buff_index(decoded_static_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    index: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    source_contexts = _load_source_contexts(decoded_static_dir)

    for precedence, definition in enumerate(BUFF_SOURCE_DEFINITIONS):
        source_table = str(definition["source_table"])
        source_type = str(definition["source_type"])
        path = decoded_static_dir / f"{source_table}.json"
        if not path.exists():
            sources[source_table] = {
                "status": "missing_source_table",
                "source_type": source_type,
                "entries": 0,
                "indexed": 0,
                "source_precedence": precedence,
            }
            continue

        data = _read_json(path)
        entries = []
        for root_key, root_value in _source_roots(data, definition["collection_keys"]):
            entries.extend(_iter_buff_specs(root_value, (root_key,)))

        indexed = 0
        for source_key, spec in entries:
            buff_id = _buff_id_from_spec(source_key, spec)
            if buff_id is None:
                continue
            indexed += 1
            entry = {
                "buff_id": buff_id,
                "source_table": source_table,
                "source_type": source_type,
                "source_key": source_key,
                "source_precedence": precedence,
                "spec": spec,
                "source_context": _source_context_for_buff(source_contexts, source_type, buff_id, spec),
                "duplicate_sources": [],
            }
            if buff_id in index:
                index[buff_id]["duplicate_sources"].append(_duplicate_source(entry))
            else:
                index[buff_id] = entry

        sources[source_table] = {
            "status": "found",
            "source_type": source_type,
            "entries": len(entries),
            "indexed": indexed,
            "source_precedence": precedence,
        }

    for definition in SUPPORTING_SOURCE_DEFINITIONS:
        source_table = str(definition["source_table"])
        source_type = str(definition["source_type"])
        path = decoded_static_dir / f"{source_table}.json"
        if not path.exists():
            sources[source_table] = {
                "status": "missing_source_table",
                "source_type": source_type,
                "entries": 0,
                "indexed": 0,
                "source_precedence": None,
            }
            continue

        data = _read_json(path)
        sources[source_table] = {
            "status": "found",
            "source_type": source_type,
            "entries": _collection_entry_count(data, definition["collection_keys"]),
            "indexed": 0,
            "source_precedence": None,
        }

    sources["LocalizationCacheData"] = _localization_source_summary(decoded_static_dir)

    return index, sources


def _active_buff_value(active_buff: dict[str, Any], snake: str, camel: str) -> Any:
    if snake in active_buff:
        return active_buff[snake]
    return active_buff.get(camel)


def _ranks(active_buff: dict[str, Any]) -> list[int]:
    value = active_buff.get("ranks")
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    ranks = []
    for rank in value:
        if rank is None:
            continue
        ranks.append(int(round(float(rank))))
    return ranks


def _ranked_values(spec: dict[str, Any]) -> list[Any]:
    value = spec.get("rankedBuffValues")
    if not value:
        value = spec.get("rankedValues")
    return value if isinstance(value, list) else []


def _ranked_value_at_index(spec: dict[str, Any], value_index: int) -> tuple[Any, str]:
    values = _ranked_values(spec)
    if not values:
        return None, "missing_ranked_values"
    if value_index < 0 or value_index >= len(values):
        return None, "rank_out_of_range"
    return _number(values[value_index]), "selected"


def _selected_ranked_value(spec: dict[str, Any], ranks: list[int]) -> tuple[int | None, Any, str]:
    if not ranks:
        return None, None, "missing_rank"

    selected_rank = ranks[0]
    value, status = _ranked_value_at_index(spec, selected_rank)
    return selected_rank, value, status


def _legacy_one_based_ranked_value(spec: dict[str, Any], ranks: list[int]) -> tuple[Any, str]:
    if not ranks:
        return None, "missing_rank"
    selected_rank = ranks[0]
    value_index = selected_rank - 1 if selected_rank > 0 else selected_rank
    return _ranked_value_at_index(spec, value_index)


def _expiry_state(active_buff: dict[str, Any]) -> str:
    expiry = _active_buff_value(active_buff, "expiry_time", "expiryTime")
    return "expires" if expiry else "no_expiry"


def _base_active_buff_row(
    *,
    battle_id: str,
    battle_path: Path,
    side: str,
    battle_side: str,
    deployed: dict[str, Any],
    active_buff: dict[str, Any],
    ship_ids: list[str] | None = None,
    hull_ids: list[str] | None = None,
) -> dict[str, Any]:
    buff_id = _id_key(_active_buff_value(active_buff, "buff_id", "buffId"))
    return {
        "battle_id": battle_id,
        "battle_path": str(battle_path),
        "side": side,
        "battle_side": battle_side,
        "fleet_id": deployed.get("fleet_id"),
        "ship_ids": (
            ship_ids if ship_ids is not None else [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])]
        ),
        "hull_ids": (
            hull_ids if hull_ids is not None else [_id_key(hull_id) for hull_id in deployed.get("hull_ids", [])]
        ),
        "buff_id": buff_id,
        "ranks": _ranks(active_buff),
        "activator_id": _active_buff_value(active_buff, "activator_id", "activatorId"),
        "activation_time": _active_buff_value(active_buff, "activation_time", "activationTime"),
        "expiry_time": _active_buff_value(active_buff, "expiry_time", "expiryTime"),
        "expiry_state": _expiry_state(active_buff),
        "attributes": active_buff.get("attributes", {}),
    }


def _resolved_active_buff_row(
    *,
    row: dict[str, Any],
    index_entry: dict[str, Any],
    code_context: dict[str, Any],
    modifier_types: dict[str, dict[str, Any]],
    include_diagnostics: bool = True,
) -> dict[str, Any]:
    spec = index_entry["spec"]
    selected_rank, selected_value, selected_status = _selected_ranked_value(spec, row["ranks"])
    legacy_one_based_value, legacy_one_based_status = _legacy_one_based_ranked_value(spec, row["ranks"])
    target_code = spec.get("targetCode")
    trigger_code = spec.get("triggerCode")
    modifier_code = _id_key(spec.get("modifierCode")) if spec.get("modifierCode") is not None else None
    modifier_codes = [modifier_code] if modifier_code is not None else []
    row.update(
        {
            "resolved": True,
            "resolution_kind": "static",
            "source_table": index_entry["source_table"],
            "source_type": index_entry["source_type"],
            "source_key": index_entry["source_key"],
            "modifierCode": modifier_code,
            "modifierCodes": modifier_codes,
            "buffOperation": spec.get("op"),
            "targetCode": target_code,
            "triggerCode": trigger_code,
            "selected_rank": selected_rank,
            "selected_ranked_value": selected_value,
            "selected_rank_status": selected_status,
            "zero_based_ranked_value": selected_value,
            "zero_based_rank_status": selected_status,
            "legacy_one_based_ranked_value": legacy_one_based_value,
            "legacy_one_based_rank_status": legacy_one_based_status,
            "conditionCodes": [_id_key(code) for code in spec.get("conditionCodes", [])],
            "spec_attributes": spec.get("attributes", {}),
            "unresolved_reason": None,
            "probable_source_type": None,
            "remediation_hint": None,
            "generated_explanation": None,
        }
    )
    if include_diagnostics:
        row.update(
            {
                "source_context": index_entry.get("source_context"),
                "duplicate_sources": index_entry["duplicate_sources"],
                "modifierName": _modifier_name(modifier_code, modifier_types) if modifier_code is not None else None,
                "modifierOriginalName": (
                    _modifier_original_name(modifier_code, modifier_types) if modifier_code is not None else None
                ),
                "modifierType": (
                    _modifier_type_summary(modifier_code, modifier_types) if modifier_code is not None else None
                ),
                "modifierTypes": _modifier_summaries(modifier_codes, modifier_types),
                "targetSpec": _code_spec_for(code_context, "targets_by_code", target_code),
                "triggerSpec": _code_spec_for(code_context, "triggers_by_code", trigger_code),
                "spec_attributes": spec.get("attributes", {}),
            }
        )
    return row


def _fleet_bridge_officers(fleet_data: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(fleet_data, dict):
        return []
    bridge_officers = fleet_data.get("bridge_officers")
    if isinstance(bridge_officers, list):
        return [officer for officer in bridge_officers if isinstance(officer, dict)]

    fleets_officers = fleet_data.get("fleets_officers")
    if isinstance(fleets_officers, dict):
        for officers in fleets_officers.values():
            if isinstance(officers, list):
                return [officer for officer in officers if isinstance(officer, dict)]

    return []


def _rarity_core_stat_key(officer_spec: dict[str, Any]) -> str | None:
    rarity = officer_spec.get("rarity")
    if isinstance(rarity, str):
        return RARITY_CORE_STAT_KEYS.get(rarity)
    if isinstance(rarity, int | float):
        return str(int(rarity))
    return None


def _estimate_officer_core_totals(
    *,
    fleet_data: dict[str, Any] | None,
    generated_context: dict[str, Any],
) -> dict[str, int | float]:
    officers = generated_context.get("officers", {})
    core_specs = generated_context.get("officer_core_stats", {})
    totals: dict[str, float] = {"ATTACK": 0.0, "DEFENSE": 0.0, "HEALTH": 0.0}

    for officer in _fleet_bridge_officers(fleet_data):
        officer_id = officer.get("id")
        if officer_id is None:
            continue
        officer_spec = officers.get(_id_key(officer_id))
        if not isinstance(officer_spec, dict):
            continue

        level = officer.get("level")
        if level is None:
            continue
        core_spec = core_specs.get(_id_key(level))
        if not isinstance(core_spec, dict):
            continue

        rarity_key = _rarity_core_stat_key(officer_spec)
        if rarity_key is None:
            continue
        level_multiplier = _number((core_spec.get("stats") or {}).get(rarity_key))
        if level_multiplier is None:
            continue

        totals["ATTACK"] += float(_number(officer_spec.get("attack")) or 0) * float(level_multiplier)
        totals["DEFENSE"] += float(_number(officer_spec.get("defense")) or 0) * float(level_multiplier)
        totals["HEALTH"] += float(_number(officer_spec.get("health")) or 0) * float(level_multiplier)

    return {key: int(value) if value.is_integer() else value for key, value in totals.items() if value}


def _threshold_window(
    *,
    generated_context: dict[str, Any],
    core_stat_type: str,
    estimated_total: int | float | None,
) -> dict[str, Any]:
    thresholds = generated_context.get("officer_core_thresholds", {})
    threshold_spec = thresholds.get(CORE_STAT_STATIC_KEYS[core_stat_type])
    if not isinstance(threshold_spec, dict):
        return {"last_threshold": None, "next_threshold": None}

    entries = threshold_spec.get("thresholds", [])
    if not isinstance(entries, list):
        return {"last_threshold": None, "next_threshold": None}

    if estimated_total is None:
        return {"last_threshold": None, "next_threshold": entries[0] if entries else None}

    last_threshold = None
    next_threshold = None
    for threshold in entries:
        if not isinstance(threshold, dict):
            continue
        total = _number(threshold.get("statTotal"))
        if total is None:
            continue
        if total <= estimated_total:
            last_threshold = threshold
        elif next_threshold is None:
            next_threshold = threshold
            break

    return {"last_threshold": last_threshold, "next_threshold": next_threshold}


def _activated_ability_summaries(hull: dict[str, Any], generated_context: dict[str, Any]) -> list[dict[str, Any]]:
    abilities_by_id = {
        _id_key(ability.get("id")): ability
        for ability in generated_context.get("activated_abilities", [])
        if isinstance(ability, dict) and ability.get("id") is not None
    }
    summaries = []
    for ability_id in hull.get("activatedAbilitiesIds", []) or []:
        ability = abilities_by_id.get(_id_key(ability_id))
        if not isinstance(ability, dict):
            summaries.append({"id": _id_key(ability_id), "status": "missing_ability_spec"})
            continue
        summaries.append(
            {
                "id": _id_key(ability_id),
                "idStr": ability.get("idStr"),
                "abilityType": ability.get("abilityType"),
                "statusEffect": ability.get("statusEffect"),
                "buffIds": [_id_key(buff_id) for buff_id in ability.get("buffIds", [])],
            }
        )
    return summaries


def _ship_generated_core_stat_explanation(
    *,
    row: dict[str, Any],
    deployed: dict[str, Any],
    fleet_data: dict[str, Any] | None,
    generated_context: dict[str, Any],
) -> dict[str, Any] | None:
    activator_id = row.get("activator_id")
    if activator_id is None:
        return None

    ship_ids = [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])]
    ship_id = _id_key(activator_id)
    if ship_id not in ship_ids:
        return None

    has_lifecycle = bool(row.get("activation_time") or row.get("expiry_time"))
    if has_lifecycle:
        return None

    ship_index = ship_ids.index(ship_id)
    hull_id = _hull_id_for_ship(deployed, ship_index)
    if hull_id is None:
        return None

    hull = generated_context.get("hulls", {}).get(hull_id)
    if not isinstance(hull, dict):
        return None

    core_modifiers = hull.get("coreStatModifiers", [])
    if not isinstance(core_modifiers, list) or not core_modifiers:
        return None

    rank_core_stat_types = _core_stat_rank_types(row["ranks"])
    eligible_core_stat_types = set(rank_core_stat_types) if rank_core_stat_types else set(CORE_STAT_STATIC_KEYS)
    fleet_attributes = deployed.get("attributes") or {}
    estimated_totals = _estimate_officer_core_totals(fleet_data=fleet_data, generated_context=generated_context)

    explained_modifiers = []
    for modifier in core_modifiers:
        if not isinstance(modifier, dict):
            continue
        core_stat_type = _core_stat_type(modifier.get("type"))
        if core_stat_type is None or core_stat_type not in eligible_core_stat_types:
            continue

        modifier_code, modifier_name = CORE_STAT_FLEET_MODIFIERS[core_stat_type]
        captured_bonus = _number(fleet_attributes.get(modifier_code))
        hull_bonus = _number(modifier.get("bonus"))
        hull_threshold = _number(modifier.get("threshold"))
        estimated_total = estimated_totals.get(core_stat_type)
        threshold_met = (
            estimated_total is not None and hull_threshold is not None and float(estimated_total) >= float(hull_threshold)
        )

        explained_modifiers.append(
            {
                "core_stat_type": CORE_STAT_ENUM_NAMES[core_stat_type],
                "core_stat": core_stat_type,
                "fleet_modifierCode": modifier_code,
                "fleet_modifierName": modifier_name,
                "hull_bonus": hull_bonus,
                "hull_threshold": hull_threshold,
                "captured_bonus": captured_bonus,
                "captured_bonus_matches_hull_bonus": _numbers_close(captured_bonus, hull_bonus),
                "estimated_officer_core_total": estimated_total,
                "estimated_total_meets_hull_threshold": threshold_met,
                **_threshold_window(
                    generated_context=generated_context,
                    core_stat_type=core_stat_type,
                    estimated_total=estimated_total,
                ),
            }
        )

    if not explained_modifiers:
        return None

    matched = [
        modifier
        for modifier in explained_modifiers
        if modifier["captured_bonus_matches_hull_bonus"] or modifier["estimated_total_meets_hull_threshold"]
    ]
    if not matched:
        return None

    return {
        "resolver": "hull_core_stat_modifier",
        "source_table": "HullSpecs",
        "source_key": f"hullSpecs/{hull_id}/coreStatModifiers",
        "ship_id": ship_id,
        "hull_id": hull_id,
        "hull_type": hull.get("type"),
        "hull_name": hull.get("name"),
        "ship_level": (deployed.get("ship_levels") or {}).get(ship_id),
        "ship_tier": (deployed.get("ship_tiers") or {}).get(ship_id),
        "rank_core_stat_types": rank_core_stat_types,
        "estimated_officer_core_totals": estimated_totals,
        "core_stat_modifiers": explained_modifiers,
        "hull_activated_abilities": _activated_ability_summaries(hull, generated_context),
        "confidence": "matched_captured_fleet_attribute",
        "note": "Active buff ranks decode to officer core stat types; the captured buff id is runtime-generated, not a static BuffSpec id.",
    }


def _generated_active_buff_row(
    *,
    row: dict[str, Any],
    deployed: dict[str, Any],
    fleet_data: dict[str, Any] | None,
    generated_context: dict[str, Any],
    modifier_types: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    explanation = _ship_generated_core_stat_explanation(
        row=row,
        deployed=deployed,
        fleet_data=fleet_data,
        generated_context=generated_context,
    )
    if explanation is None:
        return None

    modifier_codes = [modifier["fleet_modifierCode"] for modifier in explanation["core_stat_modifiers"]]
    row.update(
        {
            "resolved": True,
            "resolution_kind": "generated",
            "source_table": explanation["source_table"],
            "source_type": "generated_hull_core_stat_modifier",
            "source_key": explanation["source_key"],
            "source_context": None,
            "duplicate_sources": [],
            "modifierCode": None,
            "modifierName": None,
            "modifierOriginalName": None,
            "modifierType": None,
            "modifierCodes": modifier_codes,
            "modifierTypes": _modifier_summaries(modifier_codes, modifier_types),
            "buffOperation": None,
            "targetCode": None,
            "triggerCode": None,
            "selected_rank": row["ranks"][0] if row["ranks"] else None,
            "selected_ranked_value": None,
            "selected_rank_status": "generated_runtime_state",
            "zero_based_ranked_value": None,
            "zero_based_rank_status": "generated_runtime_state",
            "legacy_one_based_ranked_value": None,
            "legacy_one_based_rank_status": "generated_runtime_state",
            "conditionCodes": [],
            "spec_attributes": {},
            "unresolved_reason": None,
            "probable_source_type": "ship_generated_core_stat_or_ability",
            "remediation_hint": None,
            "generated_explanation": explanation,
        }
    )
    return row


def _unresolved_classification(row: dict[str, Any]) -> tuple[str, str, str]:
    activator_id = row.get("activator_id")
    ship_activated = activator_id is not None and _id_key(activator_id) in set(row.get("ship_ids", []))
    has_lifecycle = bool(row.get("activation_time") or row.get("expiry_time"))
    if ship_activated and not has_lifecycle:
        return (
            "ship_activated_without_static_spec",
            "ship_generated_core_stat_or_ability",
            "Capture OfficerCoreStatSpecs/OfficerCoreStatThresholdsSpecs and add generated ship-buff attribution.",
        )

    return (
        "missing_static_buff_spec",
        "unknown_static_source",
        "Add the missing static BuffSpec source or a source-specific generated buff resolver.",
    )


def _unresolved_active_buff_row(row: dict[str, Any]) -> dict[str, Any]:
    unresolved_reason, probable_source_type, remediation_hint = _unresolved_classification(row)
    row.update(
        {
            "resolved": False,
            "resolution_kind": "unresolved",
            "source_table": None,
            "source_type": None,
            "source_key": None,
            "source_context": None,
            "duplicate_sources": [],
            "modifierCode": None,
            "modifierName": None,
            "modifierOriginalName": None,
            "modifierType": None,
            "modifierCodes": [],
            "modifierTypes": [],
            "buffOperation": None,
            "targetCode": None,
            "triggerCode": None,
            "selected_rank": row["ranks"][0] if row["ranks"] else None,
            "selected_ranked_value": None,
            "selected_rank_status": "unresolved_buff",
            "zero_based_ranked_value": None,
            "zero_based_rank_status": "unresolved_buff",
            "legacy_one_based_ranked_value": None,
            "legacy_one_based_rank_status": "unresolved_buff",
            "conditionCodes": [],
            "spec_attributes": {},
            "unresolved_reason": unresolved_reason,
            "probable_source_type": probable_source_type,
            "remediation_hint": remediation_hint,
            "generated_explanation": None,
        }
    )
    return row


def _deployed_fleet(journal: dict[str, Any], key: str) -> dict[str, Any] | None:
    fleet_data = journal.get(key)
    if not isinstance(fleet_data, dict):
        return None
    deployed = fleet_data.get("deployed_fleet")
    return deployed if isinstance(deployed, dict) else None


def _deployed_fleets(fleet_data: dict[str, Any]) -> list[dict[str, Any]]:
    deployed_fleets = fleet_data.get("deployed_fleets")
    if isinstance(deployed_fleets, dict) and deployed_fleets:
        return [
            deployed
            for _, deployed in sorted(deployed_fleets.items(), key=lambda item: str(item[0]))
            if isinstance(deployed, dict)
        ]

    deployed = fleet_data.get("deployed_fleet")
    return [deployed] if isinstance(deployed, dict) else []


def _fleet_data_for_deployed(fleet_data: dict[str, Any], deployed: dict[str, Any]) -> dict[str, Any]:
    context = dict(fleet_data)
    fleets_officers = fleet_data.get("fleets_officers")
    fleet_id = deployed.get("fleet_id")
    if isinstance(fleets_officers, dict) and fleet_id is not None:
        officers = fleets_officers.get(_id_key(fleet_id)) or fleets_officers.get(fleet_id)
        if isinstance(officers, list):
            context["bridge_officers"] = officers
    return context


def _looks_like_player_deployed_fleet(deployed: dict[str, Any]) -> bool:
    ship_ids = [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])]
    if any(ship_id != "0" for ship_id in ship_ids):
        return True
    return bool(deployed.get("active_buffs"))


def _player_fleets(journal: dict[str, Any]) -> list[tuple[str, dict[str, Any] | None, dict[str, Any]]]:
    fleets = []
    for battle_side, key in (("initiator", "initiator_fleet_data"), ("target", "target_fleet_data")):
        fleet_data = journal.get(key)
        if not isinstance(fleet_data, dict):
            continue
        for deployed in _deployed_fleets(fleet_data):
            if not _looks_like_player_deployed_fleet(deployed):
                continue
            fleets.append((battle_side, _fleet_data_for_deployed(fleet_data, deployed), deployed))
    return fleets


def _battle_id(path: Path, battle: dict[str, Any]) -> str:
    return str(battle.get("journal", {}).get("id") or path.stem)


def _active_buff_rows_for_fleet(
    *,
    battle_id: str,
    battle_path: Path,
    side: str,
    battle_side: str,
    fleet_data: dict[str, Any] | None,
    deployed: dict[str, Any],
    buff_index: dict[str, dict[str, Any]],
    generated_context: dict[str, Any],
    code_context: dict[str, Any],
    modifier_types: dict[str, dict[str, Any]],
    include_diagnostics: bool = True,
) -> list[dict[str, Any]]:
    rows = []
    ship_ids = [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])]
    hull_ids = [_id_key(hull_id) for hull_id in deployed.get("hull_ids", [])]
    for active_buff in deployed.get("active_buffs", []) or []:
        if not isinstance(active_buff, dict):
            continue
        row = _base_active_buff_row(
            battle_id=battle_id,
            battle_path=battle_path,
            side=side,
            battle_side=battle_side,
            deployed=deployed,
            active_buff=active_buff,
            ship_ids=ship_ids,
            hull_ids=hull_ids,
        )
        index_entry = buff_index.get(row["buff_id"])
        if index_entry is None:
            generated_row = _generated_active_buff_row(
                row=row,
                deployed=deployed,
                fleet_data=fleet_data,
                generated_context=generated_context,
                modifier_types=modifier_types,
            )
            rows.append(generated_row if generated_row is not None else _unresolved_active_buff_row(row))
        else:
            rows.append(
                _resolved_active_buff_row(
                    row=row,
                    index_entry=index_entry,
                    code_context=code_context,
                    modifier_types=modifier_types,
                    include_diagnostics=include_diagnostics,
                )
            )
    return rows


def _slim_active_buff_row(row: dict[str, Any]) -> dict[str, Any]:
    slim = {
        "battle_id": row.get("battle_id"),
        "side": row.get("side"),
        "battle_side": row.get("battle_side"),
        "ship_ids": row.get("ship_ids", []),
        "hull_ids": row.get("hull_ids", []),
        "buff_id": row.get("buff_id"),
        "resolved": row.get("resolved"),
        "resolution_kind": row.get("resolution_kind"),
        "modifierCode": row.get("modifierCode"),
        "modifierCodes": row.get("modifierCodes", []),
        "selected_ranked_value": row.get("selected_ranked_value"),
        "zero_based_ranked_value": row.get("zero_based_ranked_value"),
    }
    if row.get("source_type") is not None:
        slim["source_type"] = row.get("source_type")
    if row.get("unresolved_reason") is not None:
        slim["unresolved_reason"] = row.get("unresolved_reason")
    return slim


def _sample_values(values: set[str], limit: int = 5) -> list[str]:
    return sorted(values)[:limit]


def _nonzero_condition_codes(buff: dict[str, Any]) -> list[str]:
    return [code for code in buff.get("conditionCodes", []) if _id_key(code) != "0"]


def _single_or_list(values: set[str]) -> str | list[str] | None:
    cleaned = {value for value in values if value is not None}
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return next(iter(cleaned))
    return sorted(cleaned)


def _summarize_unresolved(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["resolved"]:
            continue
        buff_id = row["buff_id"]
        if buff_id not in grouped:
            grouped[buff_id] = {
                "buff_id": buff_id,
                "count": 0,
                "sample_battle_ids": set(),
                "sample_ranks": set(),
                "sample_activator_ids": set(),
                "unresolved_reasons": set(),
                "probable_source_types": set(),
                "remediation_hints": set(),
            }
        group = grouped[buff_id]
        group["count"] += 1
        group["sample_battle_ids"].add(row["battle_id"])
        group["unresolved_reasons"].add(row["unresolved_reason"])
        group["probable_source_types"].add(row["probable_source_type"])
        group["remediation_hints"].add(row["remediation_hint"])
        for rank in row["ranks"]:
            group["sample_ranks"].add(str(rank))
        if row["activator_id"] is not None:
            group["sample_activator_ids"].add(_id_key(row["activator_id"]))

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "buff_id": group["buff_id"],
                "count": group["count"],
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ranks": _sample_values(group["sample_ranks"]),
                "sample_activator_ids": _sample_values(group["sample_activator_ids"]),
                "unresolved_reason": _single_or_list(group["unresolved_reasons"]),
                "probable_source_type": _single_or_list(group["probable_source_types"]),
                "remediation_hint": _single_or_list(group["remediation_hints"]),
            }
        )
    return sorted(summaries, key=lambda row: (-int(row["count"]), row["buff_id"]))


def _summarize_generated(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("resolution_kind") != "generated":
            continue
        buff_id = row["buff_id"]
        if buff_id not in grouped:
            grouped[buff_id] = {
                "buff_id": buff_id,
                "count": 0,
                "sample_battle_ids": set(),
                "sample_ranks": set(),
                "sample_activator_ids": set(),
                "source_tables": set(),
                "source_types": set(),
                "core_stat_types": set(),
                "modifier_codes": set(),
                "confidence": set(),
            }
        group = grouped[buff_id]
        explanation = row.get("generated_explanation") or {}
        group["count"] += 1
        group["sample_battle_ids"].add(row["battle_id"])
        group["source_tables"].add(row["source_table"])
        group["source_types"].add(row["source_type"])
        group["confidence"].add(explanation.get("confidence"))
        if row["activator_id"] is not None:
            group["sample_activator_ids"].add(_id_key(row["activator_id"]))
        for rank in row["ranks"]:
            group["sample_ranks"].add(str(rank))
        for modifier in explanation.get("core_stat_modifiers", []):
            if modifier.get("core_stat_type") is not None:
                group["core_stat_types"].add(modifier.get("core_stat_type"))
            if modifier.get("fleet_modifierCode") is not None:
                group["modifier_codes"].add(modifier.get("fleet_modifierCode"))

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "buff_id": group["buff_id"],
                "count": group["count"],
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ranks": _sample_values(group["sample_ranks"]),
                "sample_activator_ids": _sample_values(group["sample_activator_ids"]),
                "source_table": _single_or_list(group["source_tables"]),
                "source_type": _single_or_list(group["source_types"]),
                "core_stat_types": _sample_values(group["core_stat_types"]),
                "modifierCodes": _sample_values(group["modifier_codes"]),
                "confidence": _single_or_list(group["confidence"]),
            }
        )
    return sorted(summaries, key=lambda row: (-int(row["count"]), row["buff_id"]))


def _condition_summary(code: str, condition_codes: dict[str, Any] | None) -> dict[str, Any] | None:
    if not condition_codes:
        return None
    summary = (condition_codes.get("codes") or {}).get(code)
    return summary if isinstance(summary, dict) else None


def _summarize_condition_codes(
    rows: list[dict[str, Any]],
    *,
    condition_codes: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("resolution_kind") != "static":
            continue
        for code in _nonzero_condition_codes(row):
            group = grouped.setdefault(
                code,
                {
                    "conditionCode": code,
                    "conditionName": (_condition_summary(code, condition_codes) or {}).get("name"),
                    "count": 0,
                    "sample_buff_ids": set(),
                    "source_types": set(),
                    "modifierCodes": set(),
                    "target_idStrs": set(),
                    "trigger_idStrs": set(),
                },
            )
            group["count"] += 1
            group["sample_buff_ids"].add(row["buff_id"])
            if row.get("source_type") is not None:
                group["source_types"].add(row["source_type"])
            if row.get("modifierCode") is not None:
                group["modifierCodes"].add(row["modifierCode"])
            target_id = (row.get("targetSpec") or {}).get("idStr")
            trigger_id = (row.get("triggerSpec") or {}).get("idStr")
            if target_id is not None:
                group["target_idStrs"].add(target_id)
            if trigger_id is not None:
                group["trigger_idStrs"].add(trigger_id)

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "conditionCode": group["conditionCode"],
                "conditionName": group["conditionName"],
                "count": group["count"],
                "sample_buff_ids": _sample_values(group["sample_buff_ids"]),
                "source_types": _sample_values(group["source_types"]),
                "modifierCodes": _sample_values(group["modifierCodes"]),
                "target_idStrs": _sample_values(group["target_idStrs"]),
                "trigger_idStrs": _sample_values(group["trigger_idStrs"]),
            }
        )
    return sorted(summaries, key=lambda row: (-int(row["count"]), row["conditionCode"]))


def _hull_id_for_ship(deployed: dict[str, Any], index: int) -> str | None:
    hull_ids = [_id_key(hull_id) for hull_id in deployed.get("hull_ids", [])]
    if not hull_ids:
        return None
    if index < len(hull_ids):
        return hull_ids[index]
    return hull_ids[0]


def _component_ids_for_ship(deployed: dict[str, Any], ship_id: str) -> list[Any] | None:
    components = deployed.get("ship_components") or {}
    if not isinstance(components, dict):
        return None
    return components.get(ship_id)


def _captured_ship_stats(deployed: dict[str, Any], ship_id: str) -> dict[str, Any]:
    ship_stats = deployed.get("ship_stats") or {}
    if not isinstance(ship_stats, dict):
        return {}
    stats = ship_stats.get(ship_id, {})
    return stats if isinstance(stats, dict) else {}


def _matching_static_buff_summary(row: dict[str, Any], include_diagnostics: bool = True) -> dict[str, Any]:
    summary = {
        "buff_id": row["buff_id"],
        "resolution_kind": row["resolution_kind"],
        "source_table": row["source_table"],
        "source_type": row["source_type"],
        "modifierCode": row["modifierCode"],
        "buffOperation": row["buffOperation"],
        "targetCode": row["targetCode"],
        "triggerCode": row["triggerCode"],
        "conditionCodes": row["conditionCodes"],
        "selected_rank": row["selected_rank"],
        "selected_ranked_value": row["selected_ranked_value"],
        "selected_rank_status": row["selected_rank_status"],
        "zero_based_ranked_value": row.get("zero_based_ranked_value"),
        "zero_based_rank_status": row.get("zero_based_rank_status"),
        "legacy_one_based_ranked_value": row.get("legacy_one_based_ranked_value"),
        "legacy_one_based_rank_status": row.get("legacy_one_based_rank_status"),
    }
    if include_diagnostics:
        summary.update(
            {
                "source_context": row.get("source_context"),
                "modifierName": row.get("modifierName"),
                "modifierOriginalName": row.get("modifierOriginalName"),
                "modifierType": row.get("modifierType"),
                "targetSpec": row.get("targetSpec"),
                "triggerSpec": row.get("triggerSpec"),
            }
        )
    return summary


def _generated_buff_summary(row: dict[str, Any], relevant_modifiers: list[dict[str, Any]]) -> dict[str, Any]:
    explanation = row.get("generated_explanation") or {}
    return {
        "buff_id": row["buff_id"],
        "resolution_kind": row["resolution_kind"],
        "source_table": row["source_table"],
        "source_type": row["source_type"],
        "selected_rank": row["selected_rank"],
        "selected_rank_status": row["selected_rank_status"],
        "confidence": explanation.get("confidence"),
        "core_stat_modifiers": relevant_modifiers,
    }


def _generated_modifier_match_codes(modifier: dict[str, Any]) -> set[str]:
    codes = set()
    modifier_code = modifier.get("fleet_modifierCode")
    if modifier_code is not None:
        codes.add(_id_key(modifier_code))
    core_stat = modifier.get("core_stat")
    codes.update(CORE_STAT_RELEVANT_LIVE_STATS.get(str(core_stat), set()))
    return codes


def _active_row_match_index(active_rows: list[dict[str, Any]], include_diagnostics: bool = True) -> dict[str, Any]:
    static_by_code: dict[str, list[dict[str, Any]]] = {}
    generated_by_code: dict[str, list[dict[str, Any]]] = {}
    unresolved = []

    for row in active_rows:
        resolution_kind = row.get("resolution_kind")
        if resolution_kind == "static":
            modifier_code = row.get("modifierCode")
            if modifier_code is not None:
                static_by_code.setdefault(_id_key(modifier_code), []).append(
                    _matching_static_buff_summary(row, include_diagnostics=include_diagnostics)
                )
        elif resolution_kind == "generated":
            explanation = row.get("generated_explanation") or {}
            modifiers_by_code: dict[str, list[dict[str, Any]]] = {}
            for modifier in explanation.get("core_stat_modifiers", []):
                for code in _generated_modifier_match_codes(modifier):
                    modifiers_by_code.setdefault(code, []).append(modifier)
            for code, relevant_modifiers in modifiers_by_code.items():
                generated_by_code.setdefault(code, []).append(_generated_buff_summary(row, relevant_modifiers))
        elif resolution_kind == "unresolved":
            unresolved.append(row)

    return {
        "static_by_code": static_by_code,
        "generated_by_code": generated_by_code,
        "unresolved": unresolved,
    }


def _matching_resolved_buffs(
    active_rows: list[dict[str, Any]],
    stat_code: str,
    match_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if match_index is not None:
        return list((match_index.get("static_by_code") or {}).get(stat_code, []))
    matches = []
    for row in active_rows:
        if row.get("resolution_kind") != "static" or row.get("modifierCode") != stat_code:
            continue
        matches.append(_matching_static_buff_summary(row))
    return matches


def _matching_related_resolved_buffs(
    active_rows: list[dict[str, Any]],
    stat_code: str,
    match_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    related_codes = RELATED_LIVE_STAT_MODIFIER_CODES.get(stat_code, set())
    if not related_codes:
        return []
    if match_index is not None:
        static_by_code = match_index.get("static_by_code") or {}
        return [buff for code in related_codes for buff in static_by_code.get(code, [])]

    matches = []
    for row in active_rows:
        if row.get("resolution_kind") != "static" or row.get("modifierCode") not in related_codes:
            continue
        matches.append(_matching_static_buff_summary(row))
    return matches


def _generated_modifier_relevant_to_stat(modifier: dict[str, Any], stat_code: str) -> bool:
    modifier_code = modifier.get("fleet_modifierCode")
    if modifier_code == stat_code:
        return True
    core_stat = modifier.get("core_stat")
    return stat_code in CORE_STAT_RELEVANT_LIVE_STATS.get(str(core_stat), set())


def _matching_generated_buffs(
    active_rows: list[dict[str, Any]],
    stat_code: str,
    match_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if match_index is not None:
        return list((match_index.get("generated_by_code") or {}).get(stat_code, []))
    matches = []
    for row in active_rows:
        if row.get("resolution_kind") != "generated":
            continue
        explanation = row.get("generated_explanation") or {}
        relevant_modifiers = [
            modifier
            for modifier in explanation.get("core_stat_modifiers", [])
            if _generated_modifier_relevant_to_stat(modifier, stat_code)
        ]
        if not relevant_modifiers:
            continue
        matches.append(_generated_buff_summary(row, relevant_modifiers))
    return matches


def _has_status_effect(deployed: dict[str, Any], status_effect: str) -> bool:
    status_effects = deployed.get("status_effects") or {}
    if not isinstance(status_effects, dict):
        return False
    return status_effect in {_id_key(key) for key in status_effects}


def _hull_has_activated_ability(static_ship: dict[str, Any], ability_id: str) -> bool:
    hull = static_ship.get("hull") or {}
    if not isinstance(hull, dict):
        return False
    if _id_key(hull.get("id")) == SERENE_SQUALL_HULL_ID:
        return True
    return ability_id in {_id_key(value) for value in hull.get("activatedAbilitiesIds", []) or []}


def _generated_activated_ability_buffs(
    *,
    deployed: dict[str, Any],
    static_ship: dict[str, Any],
    stat_code: str,
) -> list[dict[str, Any]]:
    if not _has_status_effect(deployed, SERENE_SQUALL_WARSHIELD_STATUS_EFFECT):
        return []
    if not _hull_has_activated_ability(static_ship, SERENE_SQUALL_WARSHIELD_ABILITY_ID):
        return []

    if stat_code in SERENE_SQUALL_WARSHIELD_DEFENSE_STAT_CODES:
        return [
            {
                "buff_id": SERENE_SQUALL_WARSHIELD_DEFENSE_BUFF_IDS[stat_code],
                "resolution_kind": "generated",
                "source_table": "ActivatedAbilitySpecs",
                "source_type": "generated_activated_ability_modifier",
                "selected_rank": None,
                "selected_rank_status": "generated_runtime_state",
                "confidence": "serene_squall_warshield_status_effect",
                "core_stat_modifiers": [
                    {
                        "fleet_modifierCode": stat_code,
                        "fleet_modifierName": _modifier_name(stat_code, {}),
                        "captured_bonus": SERENE_SQUALL_WARSHIELD_DEFENSE_MULTIPLIER - 1.0,
                        "ability_multiplier": SERENE_SQUALL_WARSHIELD_DEFENSE_MULTIPLIER,
                        "ability_id": SERENE_SQUALL_WARSHIELD_ABILITY_ID,
                        "statusEffect": SERENE_SQUALL_WARSHIELD_STATUS_EFFECT,
                    }
                ],
            }
        ]

    if stat_code != SERENE_SQUALL_WARSHIELD_DODGE_STAT_CODE:
        return []

    return [
        {
            "buff_id": SERENE_SQUALL_WARSHIELD_DODGE_BUFF_ID,
            "resolution_kind": "generated",
            "source_table": "ActivatedAbilitySpecs",
            "source_type": "generated_activated_ability_modifier",
            "selected_rank": None,
            "selected_rank_status": "generated_runtime_state",
            "confidence": "serene_squall_warshield_status_effect",
            "core_stat_modifiers": [
                {
                    "fleet_modifierCode": SERENE_SQUALL_WARSHIELD_DODGE_STAT_CODE,
                    "fleet_modifierName": "CLIENTMODIFIERTYPE_MODSHIPDODGE",
                    "captured_bonus": SERENE_SQUALL_WARSHIELD_DODGE_MULTIPLIER - 1.0,
                    "ability_multiplier": SERENE_SQUALL_WARSHIELD_DODGE_MULTIPLIER,
                    "ability_id": SERENE_SQUALL_WARSHIELD_ABILITY_ID,
                    "statusEffect": SERENE_SQUALL_WARSHIELD_STATUS_EFFECT,
                }
            ],
        }
    ]


def _matching_unresolved_buffs(
    active_rows: list[dict[str, Any]],
    match_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if match_index is not None:
        return list(match_index.get("unresolved") or [])
    matches = []
    for row in active_rows:
        if row["resolved"]:
            continue
        matches.append(
            {
                "buff_id": row["buff_id"],
                "ranks": row["ranks"],
                "activator_id": row["activator_id"],
                "unresolved_reason": row["unresolved_reason"],
                "probable_source_type": row["probable_source_type"],
            }
        )
    return matches


def _report_number(value: int | float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def _ordered_unique(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _aggregate_modifier_rows_for_fleet(
    *,
    battle_id: str,
    battle_path: Path,
    side: str,
    battle_side: str,
    deployed: dict[str, Any],
    active_rows: list[dict[str, Any]],
    match_index: dict[str, Any],
    modifier_types: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    stats = deployed.get("stats") or {}
    if not isinstance(stats, dict):
        return []
    attributes = deployed.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {}

    modifier_codes = set(stats.keys())
    modifier_codes.update(attributes.keys())
    modifier_codes.update(row["modifierCode"] for row in active_rows if row.get("modifierCode") is not None)
    for active_row in active_rows:
        modifier_codes.update(active_row.get("modifierCodes", []))
    rows = []
    for modifier_code in sorted(modifier_codes, key=lambda value: (not str(value).lstrip("-").isdigit(), str(value))):
        code = _id_key(modifier_code)
        matching_resolved = _matching_resolved_buffs(active_rows, code, match_index)
        matching_generated = _matching_generated_buffs(active_rows, code, match_index)
        if code not in stats and code not in attributes and not matching_resolved and not matching_generated:
            continue
        captured_source = "stats" if code in stats else "attributes" if code in attributes else None
        captured_value = stats.get(code) if code in stats else attributes.get(code)
        rows.append(
            {
                "battle_id": battle_id,
                "battle_path": str(battle_path),
                "side": side,
                "battle_side": battle_side,
                "fleet_id": deployed.get("fleet_id"),
                "ship_ids": [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])],
                "modifierCode": code,
                "modifierName": _modifier_name(code, modifier_types),
                "modifierOriginalName": _modifier_original_name(code, modifier_types),
                "modifierType": _modifier_type_summary(code, modifier_types),
                "captured_source": captured_source,
                "captured_aggregate": _number(captured_value),
                "explained": None,
                "residual": None,
                "math_status": "aggregate_not_reconstructed",
                "matching_resolved_buffs": matching_resolved,
                "matching_generated_buffs": matching_generated,
                "matching_unresolved_buffs": [],
            }
        )
    matching_unresolved = _matching_unresolved_buffs(active_rows, match_index)
    if matching_unresolved:
        rows.append(
            {
                "battle_id": battle_id,
                "battle_path": str(battle_path),
                "side": side,
                "battle_side": battle_side,
                "fleet_id": deployed.get("fleet_id"),
                "ship_ids": [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])],
                "modifierCode": "unknown",
                "modifierName": None,
                "modifierOriginalName": None,
                "modifierType": None,
                "captured_aggregate": None,
                "explained": None,
                "residual": None,
                "math_status": "unresolved_modifier_unknown",
                "matching_resolved_buffs": [],
                "matching_generated_buffs": [],
                "matching_unresolved_buffs": matching_unresolved,
            }
        )
    return rows


def _deduped_generated_modifier_candidates(matching_generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates_by_code: dict[str, dict[str, Any]] = {}
    for buff in matching_generated:
        buff_id = buff.get("buff_id")
        for modifier in buff.get("core_stat_modifiers", []):
            modifier_code = modifier.get("fleet_modifierCode")
            if modifier_code is None:
                continue
            percent_value = _number(modifier.get("captured_bonus"))
            if percent_value is None:
                continue

            code = _id_key(modifier_code)
            candidate = candidates_by_code.setdefault(
                code,
                {
                    "modifierCode": code,
                    "core_stats": [],
                    "percent": float(percent_value),
                    "percent_values": [],
                    "buff_ids": [],
                },
            )
            core_stat = modifier.get("core_stat")
            if core_stat is not None:
                candidate["core_stats"].append(str(core_stat))
            if not any(_numbers_close(value, percent_value) for value in candidate["percent_values"]):
                candidate["percent_values"].append(_report_number(float(percent_value)))
            if buff_id is not None:
                candidate["buff_ids"].append(_id_key(buff_id))

    candidates = []
    for candidate in candidates_by_code.values():
        candidates.append(
            {
                "modifierCode": candidate["modifierCode"],
                "core_stats": _ordered_unique(candidate["core_stats"]),
                "percent": candidate["percent"],
                "percent_values": candidate["percent_values"],
                "buff_ids": _ordered_unique(candidate["buff_ids"]),
            }
        )
    return sorted(candidates, key=lambda candidate: candidate["modifierCode"])


def _flat_after_percent_explained(
    *,
    static: int | float,
    flat_delta: float,
    multiply_percent_total: float,
    generated_percent_total: float = 0.0,
) -> float:
    return (static * (1 + multiply_percent_total + generated_percent_total)) + flat_delta


def _base_additive_explained(
    *,
    static: int | float,
    flat_delta: float,
    multiply_percent_total: float,
    generated_percent_total: float = 0.0,
) -> float:
    return (static + flat_delta) * (1 + multiply_percent_total + generated_percent_total)


def _static_buff_totals(buffs: list[dict[str, Any]]) -> tuple[float, float] | None:
    flat_delta = 0.0
    multiply_percent_total = 0.0
    for buff in buffs:
        selected_value = buff.get("selected_ranked_value")
        if selected_value is None:
            return None

        numeric_value = float(selected_value)
        operation = buff.get("buffOperation")
        if operation == "BUFFOPERATION_ADD":
            flat_delta += numeric_value
        elif operation == "BUFFOPERATION_SUB":
            flat_delta -= numeric_value
        elif operation in {"BUFFOPERATION_MULTIPLYADD", "BUFFOPERATION_MULTIPLYBASEADD"}:
            multiply_percent_total += numeric_value
        elif operation in {"BUFFOPERATION_MULTIPLYSUB", "BUFFOPERATION_MULTIPLYBASESUB"}:
            multiply_percent_total -= numeric_value
        else:
            return None
    return flat_delta, multiply_percent_total


def _best_static_buff_subset(
    *,
    static: int | float | None,
    captured: int | float | None,
    current_residual: int | float | None,
    buffs: list[dict[str, Any]],
    generated_percent_total: float,
) -> dict[str, Any]:
    if static is None or captured is None or current_residual is None:
        return {
            "status": "not_evaluated",
            "effect": "static_buff_subset_not_evaluated",
            "explained": None,
            "residual": None,
            "buff_ids": [],
            "excluded_buff_ids": [buff["buff_id"] for buff in buffs],
            "candidate_count": 0,
        }
    if not buffs:
        return {
            "status": "no_static_buffs",
            "effect": "no_static_buffs",
            "explained": None,
            "residual": None,
            "buff_ids": [],
            "excluded_buff_ids": [],
            "candidate_count": 0,
        }
    if len(buffs) > STATIC_BUFF_SUBSET_DIAGNOSTIC_MAX_BUFFS:
        return {
            "status": "skipped_too_many_static_buffs",
            "effect": "static_buff_subset_skipped_too_many_buffs",
            "explained": None,
            "residual": None,
            "buff_ids": [],
            "excluded_buff_ids": [],
            "candidate_count": 0,
            "buff_count": len(buffs),
            "max_buff_count": STATIC_BUFF_SUBSET_DIAGNOSTIC_MAX_BUFFS,
        }

    best: dict[str, Any] | None = None
    all_buff_ids = [buff["buff_id"] for buff in buffs]
    candidate_count = 0
    for mask in range(0, 1 << len(buffs)):
        subset_indexes = {index for index in range(len(buffs)) if mask & (1 << index)}
        subset = [buff for index, buff in enumerate(buffs) if index in subset_indexes]
        totals = _static_buff_totals(subset)
        if totals is None:
            continue
        flat_delta, multiply_percent_total = totals
        explained = _base_additive_explained(
            static=static,
            flat_delta=flat_delta,
            multiply_percent_total=multiply_percent_total,
            generated_percent_total=generated_percent_total,
        )
        residual = captured - explained
        buff_ids = [buff["buff_id"] for buff in subset]
        excluded_buff_ids = [buff_id for index, buff_id in enumerate(all_buff_ids) if index not in subset_indexes]
        candidate_count += 1
        candidate = {
            "status": "evaluated",
            "explained": explained,
            "residual": residual,
            "buff_ids": buff_ids,
            "excluded_buff_ids": excluded_buff_ids,
            "candidate_count": 0,
        }
        candidate_key = (abs(float(residual)), len(excluded_buff_ids), buff_ids)
        if best is None or candidate_key < best["_candidate_key"]:
            best = {**candidate, "_candidate_key": candidate_key}

    if best is None:
        return {
            "status": "not_evaluated",
            "effect": "static_buff_subset_not_evaluated",
            "explained": None,
            "residual": None,
            "buff_ids": [],
            "excluded_buff_ids": all_buff_ids,
            "candidate_count": candidate_count,
        }

    best.pop("_candidate_key", None)
    best["candidate_count"] = candidate_count
    best_residual = best["residual"]
    if _residual_closed(current_residual, captured):
        effect = "static_buff_subset_no_residual_change"
    elif _residual_closed(best_residual, captured):
        effect = "best_static_buff_subset_closes"
    elif abs(float(best_residual)) + 1e-9 < abs(float(current_residual)):
        effect = "best_static_buff_subset_improves"
    else:
        effect = "static_buff_subset_no_residual_change"
    best["effect"] = effect
    return best


def _related_modifier_explanation(
    *,
    static: int | float | None,
    captured: int | float | None,
    current_residual: int | float | None,
    flat_delta: float,
    multiply_percent_total: float,
    generated_percent_total: float,
    related_buffs: list[dict[str, Any]],
) -> dict[str, Any]:
    if not related_buffs:
        return {
            "status": "no_related_modifier_buffs",
            "effect": "no_related_modifier_buffs",
            "flat_delta": 0,
            "multiply_percent_total": 0,
            "explained": None,
            "residual": None,
            "buff_ids": [],
            "modifier_codes": [],
        }
    if static is None or captured is None or current_residual is None:
        return {
            "status": "not_evaluated",
            "effect": "related_modifier_buffs_not_evaluated",
            "flat_delta": 0,
            "multiply_percent_total": 0,
            "explained": None,
            "residual": None,
            "buff_ids": [buff["buff_id"] for buff in related_buffs],
            "modifier_codes": _ordered_unique([buff["modifierCode"] for buff in related_buffs]),
        }

    totals = _static_buff_totals(related_buffs)
    if totals is None:
        return {
            "status": "unsupported_related_modifier_buffs",
            "effect": "related_modifier_buffs_not_evaluated",
            "flat_delta": 0,
            "multiply_percent_total": 0,
            "explained": None,
            "residual": None,
            "buff_ids": [buff["buff_id"] for buff in related_buffs],
            "modifier_codes": _ordered_unique([buff["modifierCode"] for buff in related_buffs]),
        }

    related_flat_delta, related_multiply_percent_total = totals
    explained = _base_additive_explained(
        static=static,
        flat_delta=flat_delta + related_flat_delta,
        multiply_percent_total=multiply_percent_total + related_multiply_percent_total,
        generated_percent_total=generated_percent_total,
    )
    residual = captured - explained
    if _residual_closed(current_residual, captured):
        effect = "related_modifier_buffs_no_residual_change"
    elif _residual_closed(residual, captured):
        effect = "related_modifier_buffs_close"
    elif abs(float(residual)) + 1e-9 < abs(float(current_residual)):
        effect = "related_modifier_buffs_improve"
    elif abs(float(current_residual)) + 1e-9 < abs(float(residual)):
        effect = "related_modifier_buffs_worsen"
    else:
        effect = "related_modifier_buffs_no_residual_change"

    return {
        "status": "evaluated",
        "effect": effect,
        "flat_delta": related_flat_delta,
        "multiply_percent_total": related_multiply_percent_total,
        "explained": explained,
        "residual": residual,
        "buff_ids": [buff["buff_id"] for buff in related_buffs],
        "modifier_codes": _ordered_unique([buff["modifierCode"] for buff in related_buffs]),
    }


def _choose_generated_application(
    *,
    static: int | float,
    captured: int | float | None,
    flat_delta: float,
    multiply_percent_total: float,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    base_explained = _base_additive_explained(
        static=static,
        flat_delta=flat_delta,
        multiply_percent_total=multiply_percent_total,
    )
    base_residual = captured - base_explained if captured is not None else None
    if captured is None or base_residual is None:
        return {
            "applied_candidates": [],
            "generated_percent_total": 0.0,
            "explained": base_explained,
            "residual": base_residual,
        }

    best_candidates: list[dict[str, Any]] = []
    best_percent_total = 0.0
    best_explained = base_explained
    best_residual = base_residual
    best_abs_residual = abs(float(base_residual))

    candidate_count = len(candidates)
    for mask in range(1, 1 << candidate_count):
        subset = [candidate for index, candidate in enumerate(candidates) if mask & (1 << index)]
        generated_percent_total = sum(float(candidate["percent"]) for candidate in subset)
        explained = _base_additive_explained(
            static=static,
            flat_delta=flat_delta,
            multiply_percent_total=multiply_percent_total,
            generated_percent_total=generated_percent_total,
        )
        residual = captured - explained
        abs_residual = abs(float(residual))
        if abs_residual + 1e-9 >= best_abs_residual:
            continue
        best_candidates = subset
        best_percent_total = generated_percent_total
        best_explained = explained
        best_residual = residual
        best_abs_residual = abs_residual

    return {
        "applied_candidates": best_candidates,
        "generated_percent_total": best_percent_total,
        "explained": best_explained,
        "residual": best_residual,
    }


def _choose_live_stat_application(
    *,
    primary_explained: int | float | None,
    primary_residual: int | float | None,
    best_static_buff_subset: dict[str, Any],
    related_modifier_explanation: dict[str, Any],
) -> dict[str, Any]:
    candidates = [
        {
            "model": "primary_operation_model",
            "effect": "primary_operation_model",
            "explained": primary_explained,
            "residual": primary_residual,
            "precedence": 0,
        }
    ]
    if best_static_buff_subset.get("effect") in {
        "best_static_buff_subset_closes",
        "best_static_buff_subset_improves",
    }:
        candidates.append(
            {
                "model": "static_subset_model",
                "effect": best_static_buff_subset["effect"],
                "explained": best_static_buff_subset.get("explained"),
                "residual": best_static_buff_subset.get("residual"),
                "precedence": 1,
            }
        )
    if related_modifier_explanation.get("effect") in {
        "related_modifier_buffs_close",
        "related_modifier_buffs_improve",
    }:
        candidates.append(
            {
                "model": "related_modifier_model",
                "effect": related_modifier_explanation["effect"],
                "explained": related_modifier_explanation.get("explained"),
                "residual": related_modifier_explanation.get("residual"),
                "precedence": 2,
            }
        )

    def candidate_key(candidate: dict[str, Any]) -> tuple[float, int]:
        residual = candidate.get("residual")
        if residual is None:
            return (float("inf"), int(candidate["precedence"]))
        return (abs(float(residual)), int(candidate["precedence"]))

    selected = min(candidates, key=candidate_key)
    return {key: value for key, value in selected.items() if key != "precedence"}


def _live_stat_explanation(
    *,
    static: int | float | None,
    captured: int | float | None,
    matching_resolved: list[dict[str, Any]],
    matching_related_resolved: list[dict[str, Any]],
    matching_generated: list[dict[str, Any]],
) -> dict[str, Any]:
    flat_delta = 0.0
    multiply_percent_total = 0.0
    conditional_flat_delta = 0.0
    conditional_multiply_percent_total = 0.0
    applied_buffs = []
    unapplied_buffs = []
    flat_buffs = []
    multiply_buffs = []
    legacy_one_based_flat_delta = 0.0
    legacy_one_based_multiply_percent_total = 0.0
    legacy_one_based_applied_buffs = []
    rank_sensitive_buffs = []

    for buff in matching_resolved:
        selected_value = buff.get("selected_ranked_value")
        operation = buff.get("buffOperation")
        legacy_one_based_value = buff.get("legacy_one_based_ranked_value")
        if legacy_one_based_value is not None:
            legacy_numeric_value = float(legacy_one_based_value)
            if operation == "BUFFOPERATION_ADD":
                legacy_one_based_flat_delta += legacy_numeric_value
                legacy_one_based_applied_buffs.append(buff)
            elif operation == "BUFFOPERATION_SUB":
                legacy_one_based_flat_delta -= legacy_numeric_value
                legacy_one_based_applied_buffs.append(buff)
            elif operation in {"BUFFOPERATION_MULTIPLYADD", "BUFFOPERATION_MULTIPLYBASEADD"}:
                legacy_one_based_multiply_percent_total += legacy_numeric_value
                legacy_one_based_applied_buffs.append(buff)
            elif operation in {"BUFFOPERATION_MULTIPLYSUB", "BUFFOPERATION_MULTIPLYBASESUB"}:
                legacy_one_based_multiply_percent_total -= legacy_numeric_value
                legacy_one_based_applied_buffs.append(buff)

            if selected_value is not None and not _numbers_close(_number(selected_value), _number(legacy_one_based_value)):
                rank_sensitive_buffs.append(buff)

        if selected_value is None:
            unapplied_buffs.append(buff)
            continue

        numeric_value = float(selected_value)
        if operation == "BUFFOPERATION_ADD":
            flat_delta += numeric_value
            if _nonzero_condition_codes(buff):
                conditional_flat_delta += numeric_value
            flat_buffs.append(buff)
        elif operation == "BUFFOPERATION_SUB":
            flat_delta -= numeric_value
            if _nonzero_condition_codes(buff):
                conditional_flat_delta -= numeric_value
            flat_buffs.append(buff)
        elif operation in {"BUFFOPERATION_MULTIPLYADD", "BUFFOPERATION_MULTIPLYBASEADD"}:
            multiply_percent_total += numeric_value
            if _nonzero_condition_codes(buff):
                conditional_multiply_percent_total += numeric_value
            multiply_buffs.append(buff)
        elif operation in {"BUFFOPERATION_MULTIPLYSUB", "BUFFOPERATION_MULTIPLYBASESUB"}:
            multiply_percent_total -= numeric_value
            if _nonzero_condition_codes(buff):
                conditional_multiply_percent_total -= numeric_value
            multiply_buffs.append(buff)
        else:
            unapplied_buffs.append(buff)
            continue
        applied_buffs.append(buff)

    multiplier = 1 + multiply_percent_total
    generated_candidates = _deduped_generated_modifier_candidates(matching_generated)
    generated_application = {
        "applied_candidates": [],
        "generated_percent_total": 0.0,
        "explained": None,
        "residual": None,
    }
    if static is not None:
        generated_application = _choose_generated_application(
            static=static,
            captured=captured,
            flat_delta=flat_delta,
            multiply_percent_total=multiply_percent_total,
            candidates=generated_candidates,
        )
    generated_percent_total = float(generated_application["generated_percent_total"])
    applied_generated_candidates = generated_application["applied_candidates"]
    best_static_buff_subset = _best_static_buff_subset(
        static=static,
        captured=captured,
        current_residual=generated_application["residual"],
        buffs=applied_buffs,
        generated_percent_total=generated_percent_total,
    )
    related_modifier_explanation = _related_modifier_explanation(
        static=static,
        captured=captured,
        current_residual=generated_application["residual"],
        flat_delta=flat_delta,
        multiply_percent_total=multiply_percent_total,
        generated_percent_total=generated_percent_total,
        related_buffs=matching_related_resolved,
    )
    selected_application = _choose_live_stat_application(
        primary_explained=generated_application["explained"],
        primary_residual=generated_application["residual"],
        best_static_buff_subset=best_static_buff_subset,
        related_modifier_explanation=related_modifier_explanation,
    )

    implied_multiplier = multiplier + generated_percent_total
    implied_static_base = None
    if captured is not None and implied_multiplier:
        implied_static_base = _report_number((captured / implied_multiplier) - flat_delta)

    implied_static_base_delta = (
        implied_static_base - static if implied_static_base is not None and static is not None else None
    )
    applied_generated_modifier_codes = [candidate["modifierCode"] for candidate in applied_generated_candidates]
    applied_generated_buff_ids = _ordered_unique(
        [buff_id for candidate in applied_generated_candidates for buff_id in candidate["buff_ids"]]
    )
    applied_generated_core_stats = _ordered_unique(
        [core_stat for candidate in applied_generated_candidates for core_stat in candidate["core_stats"]]
    )
    without_conditional_explained = None
    without_conditional_residual = None
    conditional_effect = "no_conditional_static_buffs"
    if static is not None:
        without_conditional_explained = _base_additive_explained(
            static=static,
            flat_delta=flat_delta - conditional_flat_delta,
            multiply_percent_total=multiply_percent_total - conditional_multiply_percent_total,
            generated_percent_total=generated_percent_total,
        )
        without_conditional_residual = (
            captured - without_conditional_explained if captured is not None else None
        )
        full_residual = generated_application["residual"]
        if conditional_flat_delta or conditional_multiply_percent_total:
            if full_residual is None or without_conditional_residual is None:
                conditional_effect = "conditional_buffs_not_evaluated"
            elif abs(float(full_residual)) < abs(float(without_conditional_residual)):
                conditional_effect = "applied_conditional_buffs_improve"
            elif abs(float(without_conditional_residual)) < abs(float(full_residual)):
                conditional_effect = "excluding_conditional_buffs_improves"
            else:
                conditional_effect = "conditional_buffs_no_residual_change"

    base_additive_explained = None
    base_additive_residual = None
    legacy_flat_after_percent_explained = None
    legacy_flat_after_percent_residual = None
    flat_application_effect = "no_flat_static_buffs"
    if static is not None:
        base_additive_explained = _base_additive_explained(
            static=static,
            flat_delta=flat_delta,
            multiply_percent_total=multiply_percent_total,
            generated_percent_total=generated_percent_total,
        )
        base_additive_residual = captured - base_additive_explained if captured is not None else None
        legacy_flat_after_percent_explained = _flat_after_percent_explained(
            static=static,
            flat_delta=flat_delta,
            multiply_percent_total=multiply_percent_total,
            generated_percent_total=generated_percent_total,
        )
        legacy_flat_after_percent_residual = (
            captured - legacy_flat_after_percent_explained if captured is not None else None
        )
        current_residual = legacy_flat_after_percent_residual
        if flat_delta:
            if current_residual is None or base_additive_residual is None:
                flat_application_effect = "flat_application_not_evaluated"
            elif _residual_closed(base_additive_residual, captured):
                flat_application_effect = "promoted_base_additive_static_buffs_close"
            elif abs(float(base_additive_residual)) < abs(float(current_residual)):
                flat_application_effect = "promoted_base_additive_static_buffs_improve"
            elif abs(float(current_residual)) < abs(float(base_additive_residual)):
                flat_application_effect = "legacy_flat_after_percent_improves"
            else:
                flat_application_effect = "flat_application_no_residual_change"

    zero_based_rank_explained = None
    zero_based_rank_residual = None
    legacy_one_based_rank_explained = None
    legacy_one_based_rank_residual = None
    rank_selection_effect = "no_rank_sensitive_static_buffs"
    if static is not None:
        zero_based_rank_explained = base_additive_explained
        zero_based_rank_residual = captured - zero_based_rank_explained if captured is not None else None
        legacy_one_based_rank_explained = _base_additive_explained(
            static=static,
            flat_delta=legacy_one_based_flat_delta,
            multiply_percent_total=legacy_one_based_multiply_percent_total,
            generated_percent_total=generated_percent_total,
        )
        legacy_one_based_rank_residual = (
            captured - legacy_one_based_rank_explained if captured is not None else None
        )
        current_residual = legacy_one_based_rank_residual
        if rank_sensitive_buffs:
            if current_residual is None or zero_based_rank_residual is None:
                rank_selection_effect = "rank_selection_not_evaluated"
            elif _residual_closed(zero_based_rank_residual, captured):
                rank_selection_effect = "promoted_zero_based_rank_selection_closes"
            elif abs(float(zero_based_rank_residual)) < abs(float(current_residual)):
                rank_selection_effect = "promoted_zero_based_rank_selection_improves"
            elif abs(float(current_residual)) < abs(float(zero_based_rank_residual)):
                rank_selection_effect = "legacy_one_based_rank_selection_improves"
            else:
                rank_selection_effect = "rank_selection_no_residual_change"

    zero_based_base_additive_explained = None
    zero_based_base_additive_residual = None
    legacy_one_based_flat_after_percent_explained = None
    legacy_one_based_flat_after_percent_residual = None
    zero_based_base_additive_effect = "no_rank_or_flat_sensitive_static_buffs"
    if static is not None:
        zero_based_base_additive_explained = base_additive_explained
        zero_based_base_additive_residual = (
            captured - zero_based_base_additive_explained if captured is not None else None
        )
        legacy_one_based_flat_after_percent_explained = _flat_after_percent_explained(
            static=static,
            flat_delta=legacy_one_based_flat_delta,
            multiply_percent_total=legacy_one_based_multiply_percent_total,
            generated_percent_total=generated_percent_total,
        )
        legacy_one_based_flat_after_percent_residual = (
            captured - legacy_one_based_flat_after_percent_explained if captured is not None else None
        )
        current_residual = legacy_one_based_flat_after_percent_residual
        if rank_sensitive_buffs or flat_buffs:
            if current_residual is None or zero_based_base_additive_residual is None:
                zero_based_base_additive_effect = "zero_based_base_additive_not_evaluated"
            elif _residual_closed(zero_based_base_additive_residual, captured):
                zero_based_base_additive_effect = "promoted_zero_based_base_additive_closes"
            elif abs(float(zero_based_base_additive_residual)) < abs(float(current_residual)):
                zero_based_base_additive_effect = "promoted_zero_based_base_additive_improves"
            elif abs(float(current_residual)) < abs(float(zero_based_base_additive_residual)):
                zero_based_base_additive_effect = "legacy_one_based_flat_after_percent_improves"
            else:
                zero_based_base_additive_effect = "zero_based_base_additive_no_residual_change"

    explanation_components = {
        "static": static,
        "flat_delta": _report_number(flat_delta),
        "multiply_percent_total": _report_number(multiply_percent_total),
        "applied_static_buff_ids": [buff["buff_id"] for buff in applied_buffs],
        "flat_static_buff_ids": [buff["buff_id"] for buff in flat_buffs],
        "multiply_static_buff_ids": [buff["buff_id"] for buff in multiply_buffs],
        "conditional_static_buff_ids": [buff["buff_id"] for buff in applied_buffs if _nonzero_condition_codes(buff)],
        "unconditional_static_buff_ids": [
            buff["buff_id"] for buff in applied_buffs if not _nonzero_condition_codes(buff)
        ],
        "conditional_static_flat_delta": _report_number(conditional_flat_delta),
        "conditional_static_multiply_percent_total": _report_number(conditional_multiply_percent_total),
        "without_conditional_static_buffs_explained": _report_number(without_conditional_explained),
        "without_conditional_static_buffs_residual": without_conditional_residual,
        "conditional_effect": conditional_effect,
        "base_additive_static_buffs_explained": _report_number(base_additive_explained),
        "base_additive_static_buffs_residual": _report_number(base_additive_residual),
        "legacy_flat_after_percent_explained": _report_number(legacy_flat_after_percent_explained),
        "legacy_flat_after_percent_residual": _report_number(legacy_flat_after_percent_residual),
        "flat_application_effect": flat_application_effect,
        "zero_based_rank_flat_delta": _report_number(flat_delta),
        "zero_based_rank_multiply_percent_total": _report_number(multiply_percent_total),
        "zero_based_rank_static_buff_ids": [buff["buff_id"] for buff in applied_buffs],
        "legacy_one_based_rank_flat_delta": _report_number(legacy_one_based_flat_delta),
        "legacy_one_based_rank_multiply_percent_total": _report_number(legacy_one_based_multiply_percent_total),
        "legacy_one_based_rank_static_buff_ids": [buff["buff_id"] for buff in legacy_one_based_applied_buffs],
        "rank_sensitive_static_buff_ids": [buff["buff_id"] for buff in rank_sensitive_buffs],
        "zero_based_rank_explained": _report_number(zero_based_rank_explained),
        "zero_based_rank_residual": _report_number(zero_based_rank_residual),
        "legacy_one_based_rank_explained": _report_number(legacy_one_based_rank_explained),
        "legacy_one_based_rank_residual": _report_number(legacy_one_based_rank_residual),
        "rank_selection_effect": rank_selection_effect,
        "zero_based_base_additive_explained": _report_number(zero_based_base_additive_explained),
        "zero_based_base_additive_residual": _report_number(zero_based_base_additive_residual),
        "legacy_one_based_flat_after_percent_explained": _report_number(
            legacy_one_based_flat_after_percent_explained
        ),
        "legacy_one_based_flat_after_percent_residual": _report_number(
            legacy_one_based_flat_after_percent_residual
        ),
        "zero_based_base_additive_effect": zero_based_base_additive_effect,
        "unapplied_static_buff_ids": [buff["buff_id"] for buff in unapplied_buffs],
        "generated_buff_ids": [buff["buff_id"] for buff in matching_generated],
        "candidate_generated_modifierCodes": [candidate["modifierCode"] for candidate in generated_candidates],
        "generated_percent_total": _report_number(generated_percent_total),
        "applied_generated_modifierCodes": applied_generated_modifier_codes,
        "applied_generated_core_stats": applied_generated_core_stats,
        "applied_generated_buff_ids": applied_generated_buff_ids,
        "unapplied_generated_modifierCodes": [
            candidate["modifierCode"]
            for candidate in generated_candidates
            if candidate["modifierCode"] not in applied_generated_modifier_codes
        ],
        "best_static_buff_subset_status": best_static_buff_subset["status"],
        "best_static_buff_subset_effect": best_static_buff_subset["effect"],
        "best_static_buff_subset_candidate_count": best_static_buff_subset["candidate_count"],
        "best_static_buff_subset_buff_ids": best_static_buff_subset["buff_ids"],
        "best_static_buff_subset_excluded_buff_ids": best_static_buff_subset["excluded_buff_ids"],
        "best_static_buff_subset_explained": _report_number(best_static_buff_subset["explained"]),
        "best_static_buff_subset_residual": _report_number(best_static_buff_subset["residual"]),
        "related_modifier_status": related_modifier_explanation["status"],
        "related_modifier_effect": related_modifier_explanation["effect"],
        "related_modifier_codes": related_modifier_explanation["modifier_codes"],
        "related_modifier_static_buff_ids": related_modifier_explanation["buff_ids"],
        "related_modifier_flat_delta": _report_number(related_modifier_explanation["flat_delta"]),
        "related_modifier_multiply_percent_total": _report_number(
            related_modifier_explanation["multiply_percent_total"]
        ),
        "with_related_modifier_buffs_explained": _report_number(related_modifier_explanation["explained"]),
        "with_related_modifier_buffs_residual": _report_number(related_modifier_explanation["residual"]),
        "primary_operation_model_explained": _report_number(generated_application["explained"]),
        "primary_operation_model_residual": _report_number(generated_application["residual"]),
        "selected_live_stat_model": selected_application["model"],
        "selected_live_stat_effect": selected_application["effect"],
        "selected_live_stat_explained": _report_number(selected_application["explained"]),
        "selected_live_stat_residual": _report_number(selected_application["residual"]),
        "implied_static_base": implied_static_base,
        "implied_static_base_delta": implied_static_base_delta,
    }

    if static is None:
        return {
            "explained": None,
            "residual": None,
            "math_status": "missing_static",
            "explanation_components": explanation_components,
        }

    explained = selected_application["explained"]
    residual = selected_application["residual"]
    residual_closed = _residual_closed(residual, captured)

    if selected_application["model"] == "static_subset_model":
        math_status = (
            "static_subset_model_closed"
            if residual_closed and not unapplied_buffs
            else "static_subset_model_partial"
        )
    elif selected_application["model"] == "related_modifier_model":
        math_status = (
            "related_modifier_model_closed"
            if residual_closed and not unapplied_buffs
            else "related_modifier_model_partial"
        )
    elif applied_generated_candidates and residual_closed and not unapplied_buffs:
        math_status = "generated_core_stat_model_closed"
    elif applied_generated_candidates and residual is not None:
        math_status = "generated_core_stat_model_partial"
    elif applied_buffs and residual_closed and not unapplied_buffs:
        math_status = "operation_model_closed"
    elif applied_buffs and residual is not None:
        math_status = "operation_model_partial"
    elif residual_closed and not unapplied_buffs:
        math_status = "static_only_closed"
    elif matching_generated:
        math_status = "static_plus_generated_core_stat_not_reconstructed"
    elif unapplied_buffs:
        math_status = "static_plus_unapplied_non_additive_buffs"
    else:
        math_status = "static_only"

    return {
        "explained": _report_number(explained),
        "residual": residual,
        "math_status": math_status,
        "explanation_components": explanation_components,
    }


def _live_stat_residuals_for_fleet(
    *,
    catalog: dict[str, Any],
    battle_id: str,
    battle_path: Path,
    side: str,
    battle_side: str,
    deployed: dict[str, Any],
    active_rows: list[dict[str, Any]],
    match_index: dict[str, Any],
    modifier_types: dict[str, dict[str, Any]],
    include_diagnostics: bool = True,
) -> list[dict[str, Any]]:
    rows = []
    ship_ids = [_id_key(ship_id) for ship_id in deployed.get("ship_ids", [])]
    for ship_index, ship_id in enumerate(ship_ids):
        hull_id = _hull_id_for_ship(deployed, ship_index)
        if hull_id is None:
            continue
        component_ids = _component_ids_for_ship(deployed, ship_id)
        static_ship = build_static_ship(
            catalog,
            hull_id,
            component_ids=component_ids,
            ship_tier=(deployed.get("ship_tiers") or {}).get(ship_id),
            ship_level=(deployed.get("ship_levels") or {}).get(ship_id),
        )
        captured_stats = _captured_ship_stats(deployed, ship_id)
        hull = static_ship["hull"]
        hull_type = hull.get("type")

        for stat_code, static_field in LIVE_STAT_FIELDS:
            captured = _number(captured_stats.get(stat_code))
            static = _number(static_ship["base_stats"].get(static_field))
            static_residual = captured - static if captured is not None and static is not None else None
            matching_resolved = _matching_resolved_buffs(active_rows, stat_code, match_index)
            matching_related_resolved = _matching_related_resolved_buffs(active_rows, stat_code, match_index)
            matching_generated = _matching_generated_buffs(active_rows, stat_code, match_index)
            matching_generated.extend(
                _generated_activated_ability_buffs(
                    deployed=deployed,
                    static_ship=static_ship,
                    stat_code=stat_code,
                )
            )
            explanation = _live_stat_explanation(
                static=static,
                captured=captured,
                matching_resolved=matching_resolved,
                matching_related_resolved=matching_related_resolved,
                matching_generated=matching_generated,
            )
            row = {
                "battle_id": battle_id,
                "battle_path": str(battle_path),
                "side": side,
                "battle_side": battle_side,
                "ship_id": ship_id,
                "hull_id": hull_id,
                "hull_id_str": hull.get("id_str"),
                "hull_name": hull.get("name"),
                "hull_type": hull_type,
                "stat_code": stat_code,
                "static_field": static_field,
                "captured": captured,
                "static": static,
                "static_residual": static_residual,
                "explained": explanation["explained"],
                "residual": explanation["residual"],
                "math_status": explanation["math_status"],
                "explanation_components": explanation.get("explanation_components", {}),
            }
            if include_diagnostics:
                row.update(
                    {
                        "stat_modifierName": _modifier_name(stat_code, modifier_types),
                        "stat_modifierOriginalName": _modifier_original_name(stat_code, modifier_types),
                        "stat_modifierType": _modifier_type_summary(stat_code, modifier_types),
                        "static_source": (static_ship.get("stat_sources") or {}).get(
                            static_field, {"status": "missing_static_source"}
                        ),
                        "tier_static_sources": static_ship.get("tier_static_sources", {}),
                        "tier_stat_modifier": (static_ship.get("tier_stat_modifiers_by_code") or {}).get(stat_code),
                        "client_ship_stat_lookup": (
                            static_ship.get("client_ship_stat_lookup_sources") or {}
                        ).get(static_field, {"status": "missing_lookup_source"}),
                        "matching_resolved_buffs": matching_resolved,
                        "matching_related_buffs": matching_related_resolved,
                        "matching_generated_buffs": matching_generated,
                    }
                )
            else:
                row["explanation_components"] = {
                    "selected_live_stat_model": (explanation.get("explanation_components") or {}).get(
                        "selected_live_stat_model"
                    )
                }
            rows.append(row)
    return rows


def _mean_abs(values: list[Any]) -> int | float | None:
    numbers = [_number(value) for value in values]
    numbers = [float(value) for value in numbers if value is not None]
    if not numbers:
        return None
    return _report_number(sum(abs(value) for value in numbers) / len(numbers))


def _mean_abs_percent_error(rows: list[dict[str, Any]], residual_key: str | None = None) -> int | float | None:
    percentages = []
    for row in rows:
        captured = _number(row.get("captured"))
        if captured in (None, 0):
            continue
        if residual_key is None:
            residual = _number(row.get("residual"))
        else:
            residual = _number((row.get("explanation_components") or {}).get(residual_key))
        if residual is None:
            continue
        percentages.append(abs(float(residual)) / abs(float(captured)))
    if not percentages:
        return None
    return _report_number(sum(percentages) / len(percentages))


def _summarize_live_stat_error(live_stat_residuals: list[dict[str, Any]]) -> dict[str, Any]:
    residual_rows = [row for row in live_stat_residuals if row.get("residual") is not None]
    primary_residuals = [
        (row.get("explanation_components") or {}).get("primary_operation_model_residual")
        for row in live_stat_residuals
    ]
    selected_models = Counter(
        (row.get("explanation_components") or {}).get("selected_live_stat_model", "unknown")
        for row in live_stat_residuals
    )
    math_statuses = Counter(row.get("math_status", "unknown") for row in live_stat_residuals)
    return {
        "live_stat_row_count": len(live_stat_residuals),
        "residual_row_count": len(residual_rows),
        "mean_abs_residual": _mean_abs([row.get("residual") for row in live_stat_residuals]),
        "mean_abs_percent_error": _mean_abs_percent_error(live_stat_residuals),
        "primary_operation_mean_abs_residual": _mean_abs(primary_residuals),
        "primary_operation_mean_abs_percent_error": _mean_abs_percent_error(
            live_stat_residuals, "primary_operation_model_residual"
        ),
        "selected_live_stat_models": dict(sorted(selected_models.items())),
        "math_statuses": dict(sorted(math_statuses.items())),
    }


def _compact_resolved_buff_summary(buff: dict[str, Any]) -> dict[str, Any]:
    return {
        "buff_id": buff["buff_id"],
        "modifierCode": buff.get("modifierCode"),
        "modifierName": buff.get("modifierName"),
        "modifierOriginalName": buff.get("modifierOriginalName"),
        "source_table": buff["source_table"],
        "source_type": buff["source_type"],
        "buffOperation": buff["buffOperation"],
        "conditionCodes": buff["conditionCodes"],
        "selected_rank": buff["selected_rank"],
        "selected_ranked_value": buff["selected_ranked_value"],
        "target_idStr": (buff.get("targetSpec") or {}).get("idStr"),
        "trigger_idStr": (buff.get("triggerSpec") or {}).get("idStr"),
        "source_context": buff.get("source_context"),
    }


def _summarize_conditional_effects(live_stat_residuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, Any, str, str], dict[str, Any]] = {}
    for row in live_stat_residuals:
        components = row.get("explanation_components") or {}
        effect = components.get("conditional_effect")
        if not effect or effect == "no_conditional_static_buffs":
            continue

        key = (effect, row.get("hull_type"), row["stat_code"], row["static_field"])
        group = grouped.setdefault(
            key,
            {
                "conditional_effect": effect,
                "count": 0,
                "hull_type": row.get("hull_type"),
                "stat_code": row["stat_code"],
                "static_field": row["static_field"],
                "math_statuses": set(),
                "battle_sides": set(),
                "sample_battle_ids": set(),
                "sample_ship_ids": set(),
                "residuals": [],
                "without_conditional_residuals": [],
                "conditional_buff_ids": set(),
                "unconditional_buff_ids": set(),
                "conditional_buffs": {},
                "matching_static_buffs": {},
            },
        )
        group["count"] += 1
        group["math_statuses"].add(row["math_status"])
        group["battle_sides"].add(row["battle_side"])
        group["sample_battle_ids"].add(row["battle_id"])
        group["sample_ship_ids"].add(row["ship_id"])
        group["residuals"].append(row.get("residual"))
        group["without_conditional_residuals"].append(components.get("without_conditional_static_buffs_residual"))

        conditional_buff_ids = {_id_key(buff_id) for buff_id in components.get("conditional_static_buff_ids", [])}
        unconditional_buff_ids = {_id_key(buff_id) for buff_id in components.get("unconditional_static_buff_ids", [])}
        group["conditional_buff_ids"].update(conditional_buff_ids)
        group["unconditional_buff_ids"].update(unconditional_buff_ids)

        for buff in row.get("matching_resolved_buffs", []):
            summary = _compact_resolved_buff_summary(buff)
            group["matching_static_buffs"].setdefault(summary["buff_id"], summary)
            if summary["buff_id"] in conditional_buff_ids:
                group["conditional_buffs"].setdefault(summary["buff_id"], summary)

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "conditional_effect": group["conditional_effect"],
                "count": group["count"],
                "hull_type": group["hull_type"],
                "stat_code": group["stat_code"],
                "static_field": group["static_field"],
                "math_statuses": _sample_values(group["math_statuses"]),
                "battle_sides": _sample_values(group["battle_sides"]),
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ship_ids": _sample_values(group["sample_ship_ids"]),
                "mean_abs_residual": _mean_abs(group["residuals"]),
                "mean_abs_without_conditional_residual": _mean_abs(group["without_conditional_residuals"]),
                "conditional_buff_ids": _sample_values(group["conditional_buff_ids"]),
                "unconditional_buff_ids": _sample_values(group["unconditional_buff_ids"]),
                "conditional_buffs": [
                    group["conditional_buffs"][buff_id] for buff_id in _sample_values(set(group["conditional_buffs"]))
                ],
                "matching_static_buffs": [
                    group["matching_static_buffs"][buff_id]
                    for buff_id in _sample_values(set(group["matching_static_buffs"]))
                ],
            }
        )
    return sorted(
        summaries,
        key=lambda row: (-int(row["count"]), row["conditional_effect"], row["hull_type"] or "", row["stat_code"]),
    )


def _summarize_static_buff_subset_effects(live_stat_residuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, Any, str, str], dict[str, Any]] = {}
    ignored_effects = {
        "no_static_buffs",
        "static_buff_subset_no_residual_change",
        "static_buff_subset_not_evaluated",
        "static_buff_subset_skipped_too_many_buffs",
    }
    for row in live_stat_residuals:
        components = row.get("explanation_components") or {}
        effect = components.get("best_static_buff_subset_effect")
        if not effect or effect in ignored_effects:
            continue

        key = (effect, row.get("hull_type"), row["stat_code"], row["static_field"])
        group = grouped.setdefault(
            key,
            {
                "best_static_buff_subset_effect": effect,
                "count": 0,
                "hull_type": row.get("hull_type"),
                "stat_code": row["stat_code"],
                "static_field": row["static_field"],
                "math_statuses": set(),
                "battle_sides": set(),
                "sample_battle_ids": set(),
                "sample_ship_ids": set(),
                "residuals": [],
                "primary_residuals": [],
                "best_subset_residuals": [],
                "best_subset_buff_ids": set(),
                "best_subset_excluded_buff_ids": set(),
            },
        )
        group["count"] += 1
        group["math_statuses"].add(row["math_status"])
        group["battle_sides"].add(row["battle_side"])
        group["sample_battle_ids"].add(row["battle_id"])
        group["sample_ship_ids"].add(row["ship_id"])
        group["residuals"].append(row.get("residual"))
        group["primary_residuals"].append(components.get("primary_operation_model_residual"))
        group["best_subset_residuals"].append(components.get("best_static_buff_subset_residual"))
        group["best_subset_buff_ids"].update(
            _id_key(buff_id) for buff_id in components.get("best_static_buff_subset_buff_ids", [])
        )
        group["best_subset_excluded_buff_ids"].update(
            _id_key(buff_id) for buff_id in components.get("best_static_buff_subset_excluded_buff_ids", [])
        )

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "best_static_buff_subset_effect": group["best_static_buff_subset_effect"],
                "count": group["count"],
                "hull_type": group["hull_type"],
                "stat_code": group["stat_code"],
                "static_field": group["static_field"],
                "math_statuses": _sample_values(group["math_statuses"]),
                "battle_sides": _sample_values(group["battle_sides"]),
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ship_ids": _sample_values(group["sample_ship_ids"]),
                "mean_abs_residual": _mean_abs(group["residuals"]),
                "mean_abs_primary_operation_model_residual": _mean_abs(group["primary_residuals"]),
                "mean_abs_best_static_buff_subset_residual": _mean_abs(group["best_subset_residuals"]),
                "best_static_buff_subset_buff_ids": _sample_values(group["best_subset_buff_ids"]),
                "best_static_buff_subset_excluded_buff_ids": _sample_values(
                    group["best_subset_excluded_buff_ids"]
                ),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (
            -int(row["count"]),
            row["best_static_buff_subset_effect"],
            row["hull_type"] or "",
            row["stat_code"],
        ),
    )


def _summarize_related_modifier_effects(live_stat_residuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, Any, str, str], dict[str, Any]] = {}
    ignored_effects = {
        "no_related_modifier_buffs",
        "related_modifier_buffs_no_residual_change",
        "related_modifier_buffs_not_evaluated",
    }
    for row in live_stat_residuals:
        components = row.get("explanation_components") or {}
        effect = components.get("related_modifier_effect")
        if not effect or effect in ignored_effects:
            continue

        key = (effect, row.get("hull_type"), row["stat_code"], row["static_field"])
        group = grouped.setdefault(
            key,
            {
                "related_modifier_effect": effect,
                "count": 0,
                "hull_type": row.get("hull_type"),
                "stat_code": row["stat_code"],
                "static_field": row["static_field"],
                "math_statuses": set(),
                "battle_sides": set(),
                "sample_battle_ids": set(),
                "sample_ship_ids": set(),
                "residuals": [],
                "primary_residuals": [],
                "related_residuals": [],
                "related_modifier_codes": set(),
                "related_modifier_static_buff_ids": set(),
            },
        )
        group["count"] += 1
        group["math_statuses"].add(row["math_status"])
        group["battle_sides"].add(row["battle_side"])
        group["sample_battle_ids"].add(row["battle_id"])
        group["sample_ship_ids"].add(row["ship_id"])
        group["residuals"].append(row.get("residual"))
        group["primary_residuals"].append(components.get("primary_operation_model_residual"))
        group["related_residuals"].append(components.get("with_related_modifier_buffs_residual"))
        group["related_modifier_codes"].update(
            _id_key(code) for code in components.get("related_modifier_codes", [])
        )
        group["related_modifier_static_buff_ids"].update(
            _id_key(buff_id) for buff_id in components.get("related_modifier_static_buff_ids", [])
        )

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "related_modifier_effect": group["related_modifier_effect"],
                "count": group["count"],
                "hull_type": group["hull_type"],
                "stat_code": group["stat_code"],
                "static_field": group["static_field"],
                "math_statuses": _sample_values(group["math_statuses"]),
                "battle_sides": _sample_values(group["battle_sides"]),
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ship_ids": _sample_values(group["sample_ship_ids"]),
                "mean_abs_residual": _mean_abs(group["residuals"]),
                "mean_abs_primary_operation_model_residual": _mean_abs(group["primary_residuals"]),
                "mean_abs_with_related_modifier_residual": _mean_abs(group["related_residuals"]),
                "related_modifier_codes": _sample_values(group["related_modifier_codes"]),
                "related_modifier_static_buff_ids": _sample_values(group["related_modifier_static_buff_ids"]),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (
            -int(row["count"]),
            row["related_modifier_effect"],
            row["hull_type"] or "",
            row["stat_code"],
        ),
    )


def _summarize_flat_application_effects(live_stat_residuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, Any, str, str], dict[str, Any]] = {}
    ignored_effects = {"no_flat_static_buffs", "flat_application_no_residual_change"}
    for row in live_stat_residuals:
        components = row.get("explanation_components") or {}
        effect = components.get("flat_application_effect")
        if not effect or effect in ignored_effects:
            continue

        key = (effect, row.get("hull_type"), row["stat_code"], row["static_field"])
        group = grouped.setdefault(
            key,
            {
                "flat_application_effect": effect,
                "count": 0,
                "hull_type": row.get("hull_type"),
                "stat_code": row["stat_code"],
                "static_field": row["static_field"],
                "math_statuses": set(),
                "battle_sides": set(),
                "sample_battle_ids": set(),
                "sample_ship_ids": set(),
                "residuals": [],
                "legacy_flat_after_percent_residuals": [],
                "flat_static_buff_ids": set(),
                "multiply_static_buff_ids": set(),
            },
        )
        group["count"] += 1
        group["math_statuses"].add(row["math_status"])
        group["battle_sides"].add(row["battle_side"])
        group["sample_battle_ids"].add(row["battle_id"])
        group["sample_ship_ids"].add(row["ship_id"])
        group["residuals"].append(row.get("residual"))
        group["legacy_flat_after_percent_residuals"].append(
            components.get("legacy_flat_after_percent_residual")
        )
        group["flat_static_buff_ids"].update(_id_key(buff_id) for buff_id in components.get("flat_static_buff_ids", []))
        group["multiply_static_buff_ids"].update(
            _id_key(buff_id) for buff_id in components.get("multiply_static_buff_ids", [])
        )

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "flat_application_effect": group["flat_application_effect"],
                "count": group["count"],
                "hull_type": group["hull_type"],
                "stat_code": group["stat_code"],
                "static_field": group["static_field"],
                "math_statuses": _sample_values(group["math_statuses"]),
                "battle_sides": _sample_values(group["battle_sides"]),
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ship_ids": _sample_values(group["sample_ship_ids"]),
                "mean_abs_residual": _mean_abs(group["residuals"]),
                "mean_abs_legacy_flat_after_percent_residual": _mean_abs(
                    group["legacy_flat_after_percent_residuals"]
                ),
                "flat_static_buff_ids": _sample_values(group["flat_static_buff_ids"]),
                "multiply_static_buff_ids": _sample_values(group["multiply_static_buff_ids"]),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (-int(row["count"]), row["flat_application_effect"], row["hull_type"] or "", row["stat_code"]),
    )


def _summarize_rank_selection_effects(live_stat_residuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, Any, str, str], dict[str, Any]] = {}
    ignored_effects = {"no_rank_sensitive_static_buffs", "rank_selection_no_residual_change"}
    for row in live_stat_residuals:
        components = row.get("explanation_components") or {}
        effect = components.get("rank_selection_effect")
        if not effect or effect in ignored_effects:
            continue

        key = (effect, row.get("hull_type"), row["stat_code"], row["static_field"])
        group = grouped.setdefault(
            key,
            {
                "rank_selection_effect": effect,
                "count": 0,
                "hull_type": row.get("hull_type"),
                "stat_code": row["stat_code"],
                "static_field": row["static_field"],
                "math_statuses": set(),
                "battle_sides": set(),
                "sample_battle_ids": set(),
                "sample_ship_ids": set(),
                "residuals": [],
                "legacy_one_based_rank_residuals": [],
                "rank_sensitive_static_buff_ids": set(),
            },
        )
        group["count"] += 1
        group["math_statuses"].add(row["math_status"])
        group["battle_sides"].add(row["battle_side"])
        group["sample_battle_ids"].add(row["battle_id"])
        group["sample_ship_ids"].add(row["ship_id"])
        group["residuals"].append(row.get("residual"))
        group["legacy_one_based_rank_residuals"].append(components.get("legacy_one_based_rank_residual"))
        group["rank_sensitive_static_buff_ids"].update(
            _id_key(buff_id) for buff_id in components.get("rank_sensitive_static_buff_ids", [])
        )

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "rank_selection_effect": group["rank_selection_effect"],
                "count": group["count"],
                "hull_type": group["hull_type"],
                "stat_code": group["stat_code"],
                "static_field": group["static_field"],
                "math_statuses": _sample_values(group["math_statuses"]),
                "battle_sides": _sample_values(group["battle_sides"]),
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ship_ids": _sample_values(group["sample_ship_ids"]),
                "mean_abs_residual": _mean_abs(group["residuals"]),
                "mean_abs_legacy_one_based_rank_residual": _mean_abs(
                    group["legacy_one_based_rank_residuals"]
                ),
                "rank_sensitive_static_buff_ids": _sample_values(group["rank_sensitive_static_buff_ids"]),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (-int(row["count"]), row["rank_selection_effect"], row["hull_type"] or "", row["stat_code"]),
    )


def _summarize_zero_based_base_additive_effects(live_stat_residuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, Any, str, str], dict[str, Any]] = {}
    ignored_effects = {
        "no_rank_or_flat_sensitive_static_buffs",
        "zero_based_base_additive_no_residual_change",
    }
    for row in live_stat_residuals:
        components = row.get("explanation_components") or {}
        effect = components.get("zero_based_base_additive_effect")
        if not effect or effect in ignored_effects:
            continue

        key = (effect, row.get("hull_type"), row["stat_code"], row["static_field"])
        group = grouped.setdefault(
            key,
            {
                "zero_based_base_additive_effect": effect,
                "count": 0,
                "hull_type": row.get("hull_type"),
                "stat_code": row["stat_code"],
                "static_field": row["static_field"],
                "math_statuses": set(),
                "battle_sides": set(),
                "sample_battle_ids": set(),
                "sample_ship_ids": set(),
                "residuals": [],
                "legacy_one_based_flat_after_percent_residuals": [],
                "flat_static_buff_ids": set(),
                "rank_sensitive_static_buff_ids": set(),
            },
        )
        group["count"] += 1
        group["math_statuses"].add(row["math_status"])
        group["battle_sides"].add(row["battle_side"])
        group["sample_battle_ids"].add(row["battle_id"])
        group["sample_ship_ids"].add(row["ship_id"])
        group["residuals"].append(row.get("residual"))
        group["legacy_one_based_flat_after_percent_residuals"].append(
            components.get("legacy_one_based_flat_after_percent_residual")
        )
        group["flat_static_buff_ids"].update(_id_key(buff_id) for buff_id in components.get("flat_static_buff_ids", []))
        group["rank_sensitive_static_buff_ids"].update(
            _id_key(buff_id) for buff_id in components.get("rank_sensitive_static_buff_ids", [])
        )

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "zero_based_base_additive_effect": group["zero_based_base_additive_effect"],
                "count": group["count"],
                "hull_type": group["hull_type"],
                "stat_code": group["stat_code"],
                "static_field": group["static_field"],
                "math_statuses": _sample_values(group["math_statuses"]),
                "battle_sides": _sample_values(group["battle_sides"]),
                "sample_battle_ids": _sample_values(group["sample_battle_ids"]),
                "sample_ship_ids": _sample_values(group["sample_ship_ids"]),
                "mean_abs_residual": _mean_abs(group["residuals"]),
                "mean_abs_legacy_one_based_flat_after_percent_residual": _mean_abs(
                    group["legacy_one_based_flat_after_percent_residuals"]
                ),
                "flat_static_buff_ids": _sample_values(group["flat_static_buff_ids"]),
                "rank_sensitive_static_buff_ids": _sample_values(group["rank_sensitive_static_buff_ids"]),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (
            -int(row["count"]),
            row["zero_based_base_additive_effect"],
            row["hull_type"] or "",
            row["stat_code"],
        ),
    )


def _add_sample(values: set[str], value: Any) -> None:
    if value is not None:
        values.add(_id_key(value))


def _summarize_modifier_codes(
    *,
    active_buffs: list[dict[str, Any]],
    aggregate_modifier_rows: list[dict[str, Any]],
    live_stat_residuals: list[dict[str, Any]],
    modifier_types: dict[str, dict[str, Any]],
    numeric_symbols: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    def group_for(code: Any) -> dict[str, Any]:
        code_key = _id_key(code)
        group = grouped.get(code_key)
        if group is not None:
            return group
        group = {
            "modifierCode": code_key,
            "modifierName": _modifier_name(code_key, modifier_types),
            "modifierOriginalName": _modifier_original_name(code_key, modifier_types),
            "modifierType": _modifier_type_summary(code_key, modifier_types),
            "candidateSymbols": symbol_candidates_for(code_key, numeric_symbols),
            "active_buff_count": 0,
            "aggregate_row_count": 0,
            "live_stat_row_count": 0,
            "source_tables": set(),
            "source_types": set(),
            "buff_operations": set(),
            "target_idStrs": set(),
            "trigger_idStrs": set(),
            "captured_sources": set(),
            "captured_aggregate_values": set(),
            "live_static_fields": set(),
            "live_math_statuses": set(),
            "sample_buff_ids": set(),
            "sample_battle_ids": set(),
        }
        grouped[code_key] = group
        return group

    for buff in active_buffs:
        codes = []
        if buff.get("modifierCode") is not None:
            codes.append(buff["modifierCode"])
        codes.extend(buff.get("modifierCodes", []))
        for code in _ordered_unique([_id_key(code) for code in codes]):
            group = group_for(code)
            group["active_buff_count"] += 1
            _add_sample(group["source_tables"], buff.get("source_table"))
            _add_sample(group["source_types"], buff.get("source_type"))
            _add_sample(group["buff_operations"], buff.get("buffOperation"))
            _add_sample(group["target_idStrs"], (buff.get("targetSpec") or {}).get("idStr"))
            _add_sample(group["trigger_idStrs"], (buff.get("triggerSpec") or {}).get("idStr"))
            _add_sample(group["sample_buff_ids"], buff.get("buff_id"))
            _add_sample(group["sample_battle_ids"], buff.get("battle_id"))

    for row in aggregate_modifier_rows:
        code = row.get("modifierCode")
        if code is None or code == "unknown":
            continue
        group = group_for(code)
        group["aggregate_row_count"] += 1
        _add_sample(group["captured_sources"], row.get("captured_source"))
        if row.get("captured_aggregate") is not None:
            _add_sample(group["captured_aggregate_values"], row.get("captured_aggregate"))
        _add_sample(group["sample_battle_ids"], row.get("battle_id"))

    for row in live_stat_residuals:
        code = row.get("stat_code")
        if code is None:
            continue
        group = group_for(code)
        group["live_stat_row_count"] += 1
        _add_sample(group["live_static_fields"], row.get("static_field"))
        _add_sample(group["live_math_statuses"], row.get("math_status"))
        _add_sample(group["sample_battle_ids"], row.get("battle_id"))

    summaries = []
    for group in grouped.values():
        summaries.append(
            {
                "modifierCode": group["modifierCode"],
                "modifierName": group["modifierName"],
                "modifierOriginalName": group["modifierOriginalName"],
                "modifierType": group["modifierType"],
                "candidateSymbols": group["candidateSymbols"],
                "active_buff_count": group["active_buff_count"],
                "aggregate_row_count": group["aggregate_row_count"],
                "live_stat_row_count": group["live_stat_row_count"],
                "source_tables": _sample_values(group["source_tables"], limit=12),
                "source_types": _sample_values(group["source_types"], limit=12),
                "buff_operations": _sample_values(group["buff_operations"], limit=12),
                "target_idStrs": _sample_values(group["target_idStrs"], limit=12),
                "trigger_idStrs": _sample_values(group["trigger_idStrs"], limit=12),
                "captured_sources": _sample_values(group["captured_sources"], limit=12),
                "captured_aggregate_values": _sample_values(group["captured_aggregate_values"], limit=8),
                "live_static_fields": _sample_values(group["live_static_fields"], limit=12),
                "live_math_statuses": _sample_values(group["live_math_statuses"], limit=12),
                "sample_buff_ids": _sample_values(group["sample_buff_ids"], limit=8),
                "sample_battle_ids": _sample_values(group["sample_battle_ids"], limit=8),
            }
        )
    return sorted(
        summaries,
        key=lambda row: (
            -int(row["active_buff_count"]) - int(row["aggregate_row_count"]) - int(row["live_stat_row_count"]),
            row["modifierCode"],
        ),
    )


def _load_static_catalog_if_available(decoded_static_dir: Path) -> dict[str, Any] | None:
    try:
        return load_static_catalog(decoded_static_dir)
    except FileNotFoundError:
        return None


def generate_buff_audit(*, decoded_static_dir: Path, capture_root: Path, detail: str = "full") -> dict[str, Any]:
    if detail not in BUFF_AUDIT_DETAILS:
        raise ValueError(f"unknown buff audit detail: {detail}")

    buff_index, static_sources = build_static_buff_index(decoded_static_dir)
    generated_context = _load_generated_buff_context(decoded_static_dir)
    code_context = _load_static_code_context(decoded_static_dir)
    battle_paths = sorted((capture_root / "battles").glob("*.json"))
    game_version = _capture_game_version(battle_paths)
    modifier_types = load_client_modifier_types(game_version=game_version)
    numeric_symbols = load_numeric_symbol_index(game_version=game_version) if detail == "full" else None
    condition_codes = load_condition_code_map(game_version=game_version) if detail == "full" else None
    catalog = _load_static_catalog_if_available(decoded_static_dir)
    active_buffs: list[dict[str, Any]] = []
    live_stat_residuals: list[dict[str, Any]] = []
    aggregate_modifier_rows: list[dict[str, Any]] = []
    player_fleet_count = 0
    include_diagnostics = detail == "full"

    for battle_path in battle_paths:
        battle = _read_json(battle_path)
        journal = battle.get("journal", {})
        battle_id = _battle_id(battle_path, battle)
        for battle_side, fleet_data, deployed in _player_fleets(journal):
            player_fleet_count += 1
            fleet_active_rows = _active_buff_rows_for_fleet(
                battle_id=battle_id,
                battle_path=battle_path,
                side="player",
                battle_side=battle_side,
                fleet_data=fleet_data,
                deployed=deployed,
                buff_index=buff_index,
                generated_context=generated_context,
                code_context=code_context,
                modifier_types=modifier_types,
                include_diagnostics=include_diagnostics,
            )
            fleet_match_index = _active_row_match_index(fleet_active_rows, include_diagnostics=include_diagnostics)
            if include_diagnostics:
                active_buffs.extend(fleet_active_rows)
            else:
                active_buffs.extend(_slim_active_buff_row(row) for row in fleet_active_rows)
            if include_diagnostics:
                aggregate_modifier_rows.extend(
                    _aggregate_modifier_rows_for_fleet(
                        battle_id=battle_id,
                        battle_path=battle_path,
                        side="player",
                        battle_side=battle_side,
                        deployed=deployed,
                        active_rows=fleet_active_rows,
                        match_index=fleet_match_index,
                        modifier_types=modifier_types,
                    )
                )

            if catalog is not None:
                live_stat_residuals.extend(
                    _live_stat_residuals_for_fleet(
                        catalog=catalog,
                        battle_id=battle_id,
                        battle_path=battle_path,
                        side="player",
                        battle_side=battle_side,
                        deployed=deployed,
                        active_rows=fleet_active_rows,
                        match_index=fleet_match_index,
                        modifier_types=modifier_types,
                        include_diagnostics=include_diagnostics,
                    )
                )

    static_resolved_count = sum(1 for row in active_buffs if row.get("resolution_kind") == "static")
    generated_explained_count = sum(1 for row in active_buffs if row.get("resolution_kind") == "generated")
    resolved_count = static_resolved_count + generated_explained_count
    unresolved_count = sum(1 for row in active_buffs if row.get("resolution_kind") == "unresolved")
    report = {
        "schema_version": 1,
        "detail": detail,
        "game_version": game_version,
        "decoded_static_dir": str(decoded_static_dir),
        "capture_root": str(capture_root),
        "summary": {
            "battle_count": len(battle_paths),
            "player_fleet_count": player_fleet_count,
            "active_buff_count": len(active_buffs),
            "resolved_active_buff_count": resolved_count,
            "static_resolved_active_buff_count": static_resolved_count,
            "generated_explained_active_buff_count": generated_explained_count,
            "unresolved_active_buff_count": unresolved_count,
        },
        "static_sources": static_sources,
        "active_buffs": active_buffs,
        "live_stat_error_summary": _summarize_live_stat_error(live_stat_residuals),
        "aggregate_modifier_rows": aggregate_modifier_rows,
        "live_stat_residuals": live_stat_residuals,
    }
    if include_diagnostics:
        report.update(
            {
                "generated_buffs": _summarize_generated(active_buffs),
                "modifier_codes": _summarize_modifier_codes(
                    active_buffs=active_buffs,
                    aggregate_modifier_rows=aggregate_modifier_rows,
                    live_stat_residuals=live_stat_residuals,
                    modifier_types=modifier_types,
                    numeric_symbols=numeric_symbols,
                ),
                "condition_codes": _summarize_condition_codes(active_buffs, condition_codes=condition_codes),
                "conditional_effects": _summarize_conditional_effects(live_stat_residuals),
                "static_buff_subset_effects": _summarize_static_buff_subset_effects(live_stat_residuals),
                "related_modifier_effects": _summarize_related_modifier_effects(live_stat_residuals),
                "flat_application_effects": _summarize_flat_application_effects(live_stat_residuals),
                "rank_selection_effects": _summarize_rank_selection_effects(live_stat_residuals),
                "zero_based_base_additive_effects": _summarize_zero_based_base_additive_effects(live_stat_residuals),
                "unresolved_buffs": _summarize_unresolved(active_buffs),
            }
        )
    return report
