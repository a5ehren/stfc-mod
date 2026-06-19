"""Post-process Il2CppDumper output into small lookup artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DUMP_DIR = PROJECT_ROOT / "dump"

IMAGE_RE = re.compile(r"^// Image \d+: (?P<assembly>.+?) - ")
NAMESPACE_RE = re.compile(r"^// Namespace: (?P<namespace>.*)$")
TYPE_RE = re.compile(
    r"^(?P<prefix>(?:public|private|protected|internal|sealed|abstract|static|partial|readonly|unsafe|\s)+)"
    r"(?P<kind>class|struct|interface|enum)\s+"
    r"(?P<name>[^:\s/{]+)"
)
ORIGINAL_NAME_RE = re.compile(r'\[OriginalName\("(?P<original>[^"]+)"\)\]')
NUMERIC_CONST_RE = re.compile(
    r"^\s*(?:public|private|protected|internal)\s+const\s+"
    r"(?P<value_type>[\w.<>,\[\]\s]+?)\s+"
    r"(?P<name>\w+)\s*=\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)"
    r"(?P<suffix>[uUlLfFdDmM]*)\s*;"
)
COMBAT_HINT_RE = re.compile(
    r"buff|modifier|combat|battle|ship|hull|fleet|officer|research|hostile|armada|target|trigger|"
    r"condition|reward|loot|damage|defense|pierc|accuracy|dodge|armor|shield|isolytic|apex|wok|borg|titan|"
    r"suliban|hijacked|reliant|squall",
    re.IGNORECASE,
)


def _project_root() -> Path:
    return PROJECT_ROOT


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _normal_value(raw: str) -> str:
    if "." not in raw:
        return raw
    value = raw.rstrip("0").rstrip(".")
    return value or "0"


def _type_name(raw: str) -> str:
    return raw.split("<", 1)[0].strip()


def build_numeric_symbol_index(
    dump_cs_path: Path,
    *,
    game_version: str | None = None,
    unity_version: str | None = None,
) -> dict[str, Any]:
    """Extract numeric constants from a dump.cs file and group them by value."""
    assembly: str | None = None
    namespace = ""
    declaring_type: str | None = None
    declaring_kind: str | None = None
    pending_original_name: str | None = None
    symbols: list[dict[str, Any]] = []

    with dump_cs_path.open(encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            if image_match := IMAGE_RE.match(line):
                assembly = image_match.group("assembly")
                continue

            if namespace_match := NAMESPACE_RE.match(line):
                namespace = namespace_match.group("namespace").strip()
                continue

            if type_match := TYPE_RE.match(line):
                declaring_type = _type_name(type_match.group("name"))
                declaring_kind = type_match.group("kind")
                pending_original_name = None
                continue

            if original_match := ORIGINAL_NAME_RE.search(line):
                pending_original_name = original_match.group("original")

            const_match = NUMERIC_CONST_RE.match(line)
            if const_match is None:
                continue

            value = _normal_value(const_match.group("value"))
            value_type = " ".join(const_match.group("value_type").split())
            symbol = {
                "value": value,
                "valueType": value_type,
                "symbolName": const_match.group("name"),
                "originalName": pending_original_name,
                "declaringType": declaring_type,
                "declaringKind": declaring_kind,
                "namespace": namespace,
                "assembly": assembly,
                "line": line_no,
            }
            symbols.append(symbol)
            pending_original_name = None

    values: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        values.setdefault(symbol["value"], []).append(symbol)

    for candidates in values.values():
        candidates.sort(
            key=lambda item: (
                item.get("assembly") or "",
                item.get("namespace") or "",
                item.get("declaringType") or "",
                item.get("symbolName") or "",
                item.get("line") or 0,
            )
        )

    return {
        "schema_version": 1,
        "dump_cs": str(dump_cs_path),
        "game_version": game_version,
        "unity_version": unity_version,
        "symbol_count": len(symbols),
        "value_count": len(values),
        "symbols": sorted(
            symbols,
            key=lambda item: (
                item["value"],
                item.get("assembly") or "",
                item.get("namespace") or "",
                item.get("declaringType") or "",
                item.get("symbolName") or "",
            ),
        ),
        "values": dict(sorted(values.items(), key=lambda item: item[0])),
    }


def build_modifier_type_map(numeric_symbols: dict[str, Any]) -> dict[str, Any]:
    codes: dict[str, dict[str, Any]] = {}
    for value, candidates in numeric_symbols.get("values", {}).items():
        for candidate in candidates:
            if candidate.get("valueType") != "ClientModifierType":
                continue
            codes[value] = {
                "code": value,
                "enum_name": f"ClientModifierType.{candidate['symbolName']}",
                "original_name": candidate.get("originalName"),
                "source": numeric_symbols.get("dump_cs"),
                "symbol": candidate,
            }
    return {
        "schema_version": 1,
        "game_version": numeric_symbols.get("game_version"),
        "unity_version": numeric_symbols.get("unity_version"),
        "source": numeric_symbols.get("dump_cs"),
        "code_count": len(codes),
        "codes": dict(sorted(codes.items(), key=lambda item: int(item[0]) if item[0].lstrip("-").isdigit() else 0)),
    }


def build_condition_code_map(numeric_symbols: dict[str, Any]) -> dict[str, Any]:
    codes: dict[str, dict[str, Any]] = {}
    for value, candidates in numeric_symbols.get("values", {}).items():
        for candidate in candidates:
            if candidate.get("declaringType") != "BuffCondition.Values":
                continue
            codes[value] = {
                "code": value,
                "name": candidate["symbolName"],
                "source": numeric_symbols.get("dump_cs"),
                "symbol": candidate,
            }
    return {
        "schema_version": 1,
        "game_version": numeric_symbols.get("game_version"),
        "unity_version": numeric_symbols.get("unity_version"),
        "source": numeric_symbols.get("dump_cs"),
        "code_count": len(codes),
        "codes": dict(sorted(codes.items(), key=lambda item: int(item[0]) if item[0].lstrip("-").isdigit() else 0)),
    }


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("valueType", "symbolName", "originalName", "declaringType", "namespace", "assembly")
    )


def is_combat_symbol_candidate(candidate: dict[str, Any]) -> bool:
    return COMBAT_HINT_RE.search(_candidate_text(candidate)) is not None


def symbol_candidates_for(
    value: Any,
    numeric_symbols: dict[str, Any] | None,
    *,
    combat_only: bool = True,
    fallback_to_any: bool = False,
    limit: int = 24,
) -> list[dict[str, Any]]:
    if not numeric_symbols:
        return []
    candidates = list((numeric_symbols.get("values") or {}).get(_id_key(value), []))
    if combat_only:
        filtered = [candidate for candidate in candidates if is_combat_symbol_candidate(candidate)]
        if filtered:
            candidates = filtered
        elif not fallback_to_any:
            return []
    return candidates[:limit]


def build_combat_code_hints(numeric_symbols: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, list[dict[str, Any]]] = {}
    for value, candidates in (numeric_symbols.get("values") or {}).items():
        filtered = [candidate for candidate in candidates if is_combat_symbol_candidate(candidate)]
        if filtered:
            values[value] = filtered
    return {
        "schema_version": 1,
        "game_version": numeric_symbols.get("game_version"),
        "unity_version": numeric_symbols.get("unity_version"),
        "source": numeric_symbols.get("dump_cs"),
        "value_count": len(values),
        "values": dict(sorted(values.items(), key=lambda item: item[0])),
    }


def write_dump_enrichment(
    dump_dir: Path,
    *,
    game_version: str | None = None,
    unity_version: str | None = None,
) -> dict[str, Path]:
    dump_cs_path = dump_dir / "dump.cs"
    numeric_symbols = build_numeric_symbol_index(
        dump_cs_path,
        game_version=game_version,
        unity_version=unity_version,
    )
    modifier_types = build_modifier_type_map(numeric_symbols)
    condition_codes = build_condition_code_map(numeric_symbols)
    combat_hints = build_combat_code_hints(numeric_symbols)

    outputs = {
        "numeric_symbols": dump_dir / "numeric-symbols.json",
        "modifier_types": dump_dir / "modifier-type-map.json",
        "condition_codes": dump_dir / "condition-code-map.json",
        "combat_hints": dump_dir / "combat-code-hints.json",
    }
    outputs["numeric_symbols"].write_text(json.dumps(numeric_symbols, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    outputs["modifier_types"].write_text(json.dumps(modifier_types, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    outputs["condition_codes"].write_text(json.dumps(condition_codes, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    outputs["combat_hints"].write_text(json.dumps(combat_hints, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return outputs


def _newest_dump_dir(dump_root: Path) -> Path | None:
    candidates = sorted(path for path in dump_root.iterdir() if (path / "dump.cs").exists()) if dump_root.exists() else []
    return candidates[-1] if candidates else None


def load_numeric_symbol_index(
    *,
    project_root: Path | None = None,
    game_version: str | None = None,
) -> dict[str, Any] | None:
    root = project_root or _project_root()
    dump_root = root / "dump"
    dump_dir = dump_root / game_version if game_version else _newest_dump_dir(dump_root)
    if dump_dir is not None and not dump_dir.exists():
        dump_dir = _newest_dump_dir(dump_root)
    if dump_dir is None:
        return None

    artifact = dump_dir / "numeric-symbols.json"
    if artifact.exists():
        return json.loads(artifact.read_text(encoding="utf-8"))

    dump_cs_path = dump_dir / "dump.cs"
    if not dump_cs_path.exists():
        return None
    return build_numeric_symbol_index(dump_cs_path, game_version=dump_dir.name)


def load_condition_code_map(
    *,
    project_root: Path | None = None,
    game_version: str | None = None,
) -> dict[str, Any] | None:
    root = project_root or _project_root()
    dump_root = root / "dump"
    dump_dir = dump_root / game_version if game_version else _newest_dump_dir(dump_root)
    if dump_dir is not None and not dump_dir.exists():
        dump_dir = _newest_dump_dir(dump_root)
    if dump_dir is None:
        return None

    artifact = dump_dir / "condition-code-map.json"
    if artifact.exists():
        return json.loads(artifact.read_text(encoding="utf-8"))

    dump_cs_path = dump_dir / "dump.cs"
    if not dump_cs_path.exists():
        return None
    return build_condition_code_map(build_numeric_symbol_index(dump_cs_path))
