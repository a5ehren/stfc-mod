from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


CLIENT_MODIFIER_ENUM_RE = re.compile(
    r'(?:\[OriginalName\("(?P<original>[^"]+)"\)\]\s*)?'
    r"public const ClientModifierType (?P<name>\w+) = (?P<value>-?\d+);"
)

FALLBACK_CLIENT_MODIFIER_TYPES = {
    "-17": {
        "code": "-17",
        "enum_name": "ClientModifierType.FleetOfficerBonusHealth",
        "original_name": "FLEET_OFFICER_BONUS_HEALTH",
        "source": "local_fallback",
    },
    "-16": {
        "code": "-16",
        "enum_name": "ClientModifierType.FleetOfficerBonusDefense",
        "original_name": "FLEET_OFFICER_BONUS_DEFENSE",
        "source": "local_fallback",
    },
    "-15": {
        "code": "-15",
        "enum_name": "ClientModifierType.FleetOfficerBonusAttack",
        "original_name": "FLEET_OFFICER_BONUS_ATTACK",
        "source": "local_fallback",
    },
    "-3": {
        "code": "-3",
        "enum_name": "CapturedShipStat.ArmorPlating",
        "original_name": "CAPTURED_ARMOR_PLATING",
        "source": "local_fallback",
    },
    "-2": {
        "code": "-2",
        "enum_name": "CapturedShipStat.ShieldAbsorption",
        "original_name": "CAPTURED_SHIELD_ABSORPTION",
        "source": "local_fallback",
    },
    "2": {
        "code": "2",
        "enum_name": "ClientModifierType.ModAllDamage",
        "original_name": "MOD_ALL_DAMAGE",
        "source": "local_fallback",
    },
    "6": {
        "code": "6",
        "enum_name": "ClientModifierType.ModAccuracy",
        "original_name": "MOD_ACCURACY",
        "source": "local_fallback",
    },
    "7": {
        "code": "7",
        "enum_name": "ClientModifierType.ModArmorPiercing",
        "original_name": "MOD_ARMOR_PIERCING",
        "source": "local_fallback",
    },
    "8": {
        "code": "8",
        "enum_name": "ClientModifierType.ModShieldPiercing",
        "original_name": "MOD_SHIELD_PIERCING",
        "source": "local_fallback",
    },
    "9": {
        "code": "9",
        "enum_name": "ClientModifierType.ModCritChance",
        "original_name": "MOD_CRIT_CHANCE",
        "source": "local_fallback",
    },
    "10": {
        "code": "10",
        "enum_name": "ClientModifierType.ModCritDamage",
        "original_name": "MOD_CRIT_DAMAGE",
        "source": "local_fallback",
    },
    "11": {
        "code": "11",
        "enum_name": "ClientModifierType.ModShipDodge",
        "original_name": "MOD_SHIP_DODGE",
        "source": "local_fallback",
    },
    "12": {
        "code": "12",
        "enum_name": "ClientModifierType.ModShipArmor",
        "original_name": "MOD_SHIP_ARMOR",
        "source": "local_fallback",
    },
    "13": {
        "code": "13",
        "enum_name": "ClientModifierType.ModShields",
        "original_name": "MOD_SHIELDS",
        "source": "local_fallback",
    },
    "60": {
        "code": "60",
        "enum_name": "ClientModifierType.ModShieldHpMax",
        "original_name": "MOD_SHIELD_HP_MAX",
        "source": "local_fallback",
    },
    "61": {
        "code": "61",
        "enum_name": "ClientModifierType.ModHullHpMax",
        "original_name": "MOD_HULL_HP_MAX",
        "source": "local_fallback",
    },
    "73": {
        "code": "73",
        "enum_name": "ClientModifierType.ModAllDefenses",
        "original_name": "MOD_ALL_DEFENSES",
        "source": "local_fallback",
    },
    "74": {
        "code": "74",
        "enum_name": "ClientModifierType.ModAllPiercing",
        "original_name": "MOD_ALL_PIERCING",
        "source": "local_fallback",
    },
    "707": {
        "code": "707",
        "enum_name": "ClientModifierType.ModIsolyticDamage",
        "original_name": "MOD_ISOLYTIC_DAMAGE",
        "source": "local_fallback",
    },
    "808": {
        "code": "808",
        "enum_name": "ClientModifierType.ModIsolyticDefense",
        "original_name": "MOD_ISOLYTIC_DEFENSE",
        "source": "local_fallback",
    },
    "67001": {
        "code": "67001",
        "enum_name": "ClientModifierType.ModApexBarrier",
        "original_name": "MOD_APEX_BARRIER",
        "source": "local_fallback",
    },
}


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _newest_dump_dir(project_root: Path) -> Path | None:
    dump_root = project_root / "dump"
    if not dump_root.exists():
        return None
    candidates = sorted((path for path in dump_root.iterdir() if (path / "dump.cs").exists()), key=lambda path: path.name)
    return candidates[-1] if candidates else None


def _dump_dir(project_root: Path, game_version: str | None = None) -> Path | None:
    if game_version:
        dump_dir = project_root / "dump" / game_version
        if dump_dir.exists():
            return dump_dir
        return _newest_dump_dir(project_root)
    return _newest_dump_dir(project_root)


def _newest_dump_cs(project_root: Path) -> Path | None:
    dump_dir = _newest_dump_dir(project_root)
    return dump_dir / "dump.cs" if dump_dir else None


def _load_modifier_type_artifact(project_root: Path, game_version: str | None = None) -> dict[str, dict[str, Any]]:
    dump_dir = _dump_dir(project_root, game_version)
    if dump_dir is None:
        return {}
    path = dump_dir / "modifier-type-map.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("codes", {})


def parse_client_modifier_types(dump_cs_path: Path) -> dict[str, dict[str, Any]]:
    text = dump_cs_path.read_text(encoding="utf-8", errors="replace")
    mapping: dict[str, dict[str, Any]] = {}
    for match in CLIENT_MODIFIER_ENUM_RE.finditer(text):
        code = match.group("value")
        enum_name = f"ClientModifierType.{match.group('name')}"
        mapping[code] = {
            "code": code,
            "enum_name": enum_name,
            "original_name": match.group("original"),
            "source": str(dump_cs_path),
        }
    return mapping


def load_client_modifier_types(
    project_root: Path | None = None,
    *,
    game_version: str | None = None,
) -> dict[str, dict[str, Any]]:
    root = project_root or _project_root()
    mapping = {code: dict(summary) for code, summary in FALLBACK_CLIENT_MODIFIER_TYPES.items()}
    artifact_mapping = _load_modifier_type_artifact(root, game_version)
    if artifact_mapping:
        mapping.update(artifact_mapping)
        return mapping

    dump_dir = _dump_dir(root, game_version)
    dump_cs_path = dump_dir / "dump.cs" if dump_dir else _newest_dump_cs(root)
    if dump_cs_path is not None:
        mapping.update(parse_client_modifier_types(dump_cs_path))
    return mapping


def modifier_type_for(code: Any, modifier_types: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = _id_key(code)
    return modifier_types.get(
        key,
        {
            "code": key,
            "enum_name": None,
            "original_name": None,
            "source": "unknown",
        },
    )


def modifier_type_name(code: Any, modifier_types: dict[str, dict[str, Any]]) -> str | None:
    return modifier_type_for(code, modifier_types).get("enum_name")
