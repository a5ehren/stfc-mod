from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _id_key(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _read_static_collection(decoded_static_dir: Path, file_name: str, key: str) -> dict[str, Any]:
    path = decoded_static_dir / f"{file_name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    collection = payload.get(key)
    if not isinstance(collection, dict):
        raise ValueError(f"{path} does not contain object key {key!r}")
    return collection


def _ranked_values(spec: dict[str, Any]) -> list[Any]:
    values = spec.get("rankedBuffValues") or spec.get("rankedValues") or []
    return values if isinstance(values, list) else []


def _core_modifier_text(hull: dict[str, Any]) -> str:
    return ";".join(
        f"{modifier.get('type')}:{modifier.get('bonus')}@{modifier.get('threshold')}"
        for modifier in hull.get("coreStatModifiers", []) or []
    )


def _hull_summary(hulls: dict[str, Any], hull_id: str) -> dict[str, Any]:
    hull = hulls.get(_id_key(hull_id), {}) or {}
    return {
        "hull_ids": _id_key(hull_id),
        "hull_name": hull.get("name") or hull.get("idStr") or "",
        "hull_type": hull.get("type") or "",
        "core_stat_modifiers": _core_modifier_text(hull),
    }


def _static_core_rows(hulls: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    pattern_counts: Counter[tuple[str, Any, Any]] = Counter()
    for hull_id, hull in hulls.items():
        core_modifiers = hull.get("coreStatModifiers") or []
        if not core_modifiers:
            continue
        modifiers = []
        for modifier in core_modifiers:
            modifier_type = _id_key(modifier.get("type"))
            bonus = modifier.get("bonus")
            threshold = modifier.get("threshold")
            pattern_counts[(modifier_type, bonus, threshold)] += 1
            modifiers.append(f"{modifier_type}:{bonus}@{threshold}")
        rows.append(
            {
                "hull_id": hull_id,
                "hull_idStr": hull.get("idStr"),
                "hull_name": hull.get("name"),
                "hull_type": hull.get("type"),
                "grade": hull.get("grade"),
                "rarity": hull.get("rarity"),
                "core_stat_modifiers": modifiers,
            }
        )

    patterns = [
        {"type": modifier_type, "bonus": bonus, "threshold": threshold, "hull_count": count}
        for (modifier_type, bonus, threshold), count in pattern_counts.most_common()
    ]
    return rows, patterns


def _ship_bonus_link_row(
    *,
    hull_id: str,
    hull: dict[str, Any],
    ship_bonus_id: str,
    source: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    values = _ranked_values(spec)
    return {
        "hull_id": hull_id,
        "hull_idStr": hull.get("idStr"),
        "hull_name": hull.get("name"),
        "hull_type": hull.get("type"),
        "ship_bonus_id": ship_bonus_id,
        "source": source,
        "modifier_codes": [_id_key(spec["modifierCode"])] if spec.get("modifierCode") is not None else [],
        "buffOperation": spec.get("op"),
        "targetCode": spec.get("targetCode"),
        "triggerCode": spec.get("triggerCode"),
        "conditionCodes": [_id_key(code) for code in spec.get("conditionCodes", []) or [] if _id_key(code) != "0"],
        "showPercentage": spec.get("showPercentage"),
        "ranked_values_min": min(values) if values else None,
        "ranked_values_max": max(values) if values else None,
    }


def _static_ship_bonus_rows(hulls: dict[str, Any], ship_bonus_specs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    explicit_ids = set()
    for hull_id, hull in hulls.items():
        for ship_bonus_id in hull.get("shipBonuses", []) or []:
            ship_bonus_id = _id_key(ship_bonus_id)
            explicit_ids.add(ship_bonus_id)
            rows.append(
                _ship_bonus_link_row(
                    hull_id=hull_id,
                    hull=hull,
                    ship_bonus_id=ship_bonus_id,
                    source="HullSpecs.shipBonuses",
                    spec=ship_bonus_specs.get(ship_bonus_id, {}) or {},
                )
            )

    for ship_bonus_id, spec in ship_bonus_specs.items():
        if ship_bonus_id in explicit_ids or ship_bonus_id not in hulls:
            continue
        rows.append(
            _ship_bonus_link_row(
                hull_id=ship_bonus_id,
                hull=hulls[ship_bonus_id],
                ship_bonus_id=ship_bonus_id,
                source="ShipBonusBuffSpecs.hullId",
                spec=spec,
            )
        )

    return rows


def _group_active_generated_core_rows(active_buffs: list[dict[str, Any]], hulls: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    for row in active_buffs:
        if row.get("source_type") != "generated_hull_core_stat_modifier":
            continue
        hull_ids = ",".join(_id_key(value) for value in row.get("hull_ids", []) or [])
        buff_id = _id_key(row.get("buff_id"))
        modifier_codes = tuple(_id_key(value) for value in row.get("modifierCodes", []) or [])
        key = (hull_ids, buff_id, modifier_codes)
        grouped.setdefault(
            key,
            {
                **_hull_summary(hulls, hull_ids.split(",")[0] if hull_ids else ""),
                "runtime_buff_id": buff_id,
                "modifierCodes": list(modifier_codes),
                "active_row_count": 0,
                "battle_ids": set(),
                "ship_ids": set(),
            },
        )
        grouped[key]["active_row_count"] += 1
        if row.get("battle_id") is not None:
            grouped[key]["battle_ids"].add(_id_key(row.get("battle_id")))
        for ship_id in row.get("ship_ids", []) or []:
            grouped[key]["ship_ids"].add(_id_key(ship_id))

    return [
        {
            **{key: value for key, value in row.items() if key not in {"battle_ids", "ship_ids"}},
            "battle_count": len(row["battle_ids"]),
            "ship_count": len(row["ship_ids"]),
            "sample_battle_ids": sorted(row["battle_ids"])[:5],
            "sample_ship_ids": sorted(row["ship_ids"])[:5],
        }
        for row in sorted(grouped.values(), key=lambda item: (item["hull_name"], item["runtime_buff_id"]))
    ]


def _group_active_ship_bonus_rows(
    active_buffs: list[dict[str, Any]],
    hulls: dict[str, Any],
    ship_bonus_specs: dict[str, Any],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in active_buffs:
        if row.get("source_type") != "ship_bonus":
            continue
        hull_ids = ",".join(_id_key(value) for value in row.get("hull_ids", []) or [])
        buff_id = _id_key(row.get("buff_id"))
        modifier_code = _id_key(row.get("modifierCode"))
        spec = ship_bonus_specs.get(buff_id, {}) or {}
        key = (hull_ids, buff_id, modifier_code)
        grouped.setdefault(
            key,
            {
                **_hull_summary(hulls, hull_ids.split(",")[0] if hull_ids else ""),
                "ship_bonus_id": buff_id,
                "modifierCode": modifier_code,
                "buffOperation": spec.get("op"),
                "targetCode": spec.get("targetCode"),
                "triggerCode": spec.get("triggerCode"),
                "conditionCodes": [_id_key(code) for code in spec.get("conditionCodes", []) or [] if _id_key(code) != "0"],
                "active_row_count": 0,
                "battle_ids": set(),
                "ship_ids": set(),
            },
        )
        grouped[key]["active_row_count"] += 1
        if row.get("battle_id") is not None:
            grouped[key]["battle_ids"].add(_id_key(row.get("battle_id")))
        for ship_id in row.get("ship_ids", []) or []:
            grouped[key]["ship_ids"].add(_id_key(ship_id))

    return [
        {
            **{key: value for key, value in row.items() if key not in {"battle_ids", "ship_ids"}},
            "battle_count": len(row["battle_ids"]),
            "ship_count": len(row["ship_ids"]),
            "sample_battle_ids": sorted(row["battle_ids"])[:5],
        }
        for row in sorted(grouped.values(), key=lambda item: (item["hull_name"], item["ship_bonus_id"]))
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            flattened = {
                key: ";".join(_id_key(item) for item in value) if isinstance(value, list) else value
                for key, value in row.items()
                if key in fieldnames
            }
            writer.writerow(flattened)


def build_hull_buff_map(
    *,
    decoded_static_dir: Path,
    out_dir: Path,
    label: str,
    buff_audit_path: Path | None = None,
) -> dict[str, Any]:
    hulls = _read_static_collection(decoded_static_dir, "HullSpecs", "hullSpecs")
    ship_bonus_specs = _read_static_collection(decoded_static_dir, "ShipBonusBuffSpecs", "shipBonusSpecs")

    core_rows, core_patterns = _static_core_rows(hulls)
    ship_bonus_rows = _static_ship_bonus_rows(hulls, ship_bonus_specs)
    summary = {
        "hull_specs_total": len(hulls),
        "hulls_with_core_stat_modifiers": len(core_rows),
        "core_stat_modifier_patterns": core_patterns,
        "hulls_with_ship_bonus_ids": len({row["hull_id"] for row in ship_bonus_rows}),
        "ship_bonus_links_total": len(ship_bonus_rows),
        "explicit_ship_bonus_links": sum(1 for row in ship_bonus_rows if row["source"] == "HullSpecs.shipBonuses"),
        "implicit_hull_id_ship_bonus_links": sum(
            1 for row in ship_bonus_rows if row["source"] == "ShipBonusBuffSpecs.hullId"
        ),
    }

    report: dict[str, Any] = {
        "schema_version": 1,
        "decoded_static_dir": str(decoded_static_dir),
        "buff_audit_path": str(buff_audit_path) if buff_audit_path else None,
        "summary": summary,
        "core_stat_hulls": core_rows,
        "ship_bonus_links": ship_bonus_rows,
    }

    if buff_audit_path is not None:
        active_buffs = json.loads(buff_audit_path.read_text(encoding="utf-8")).get("active_buffs", [])
        generated_core_rows = _group_active_generated_core_rows(active_buffs, hulls)
        active_ship_bonus_rows = _group_active_ship_bonus_rows(active_buffs, hulls, ship_bonus_specs)
        report["active_generated_hull_core_buffs"] = generated_core_rows
        report["active_ship_bonus_buffs"] = active_ship_bonus_rows
        summary.update(
            {
                "generated_hull_core_active_rows": sum(row["active_row_count"] for row in generated_core_rows),
                "generated_hull_core_unique_runtime_buffs": len(
                    {row["runtime_buff_id"] for row in generated_core_rows}
                ),
                "generated_hull_core_hull_count": len({row["hull_ids"] for row in generated_core_rows}),
                "active_ship_bonus_rows": sum(row["active_row_count"] for row in active_ship_bonus_rows),
                "active_ship_bonus_unique_buffs": len({row["ship_bonus_id"] for row in active_ship_bonus_rows}),
                "active_ship_bonus_hull_count": len({row["hull_ids"] for row in active_ship_bonus_rows}),
            }
        )

        _write_csv(
            out_dir / f"hull-generated-core-active-map-{label}.csv",
            generated_core_rows,
            [
                "hull_ids",
                "hull_name",
                "hull_type",
                "core_stat_modifiers",
                "runtime_buff_id",
                "modifierCodes",
                "active_row_count",
                "battle_count",
                "ship_count",
                "sample_battle_ids",
                "sample_ship_ids",
            ],
        )
        _write_csv(
            out_dir / f"hull-active-ship-bonus-map-{label}.csv",
            active_ship_bonus_rows,
            [
                "hull_ids",
                "hull_name",
                "hull_type",
                "ship_bonus_id",
                "modifierCode",
                "buffOperation",
                "targetCode",
                "triggerCode",
                "conditionCodes",
                "active_row_count",
                "battle_count",
                "ship_count",
                "sample_battle_ids",
            ],
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"hull-static-buff-map-{label}.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        out_dir / f"hull-core-stat-modifiers-{label}.csv",
        core_rows,
        ["hull_id", "hull_idStr", "hull_name", "hull_type", "grade", "rarity", "core_stat_modifiers"],
    )
    _write_csv(
        out_dir / f"hull-ship-bonus-links-{label}.csv",
        ship_bonus_rows,
        [
            "hull_id",
            "hull_idStr",
            "hull_name",
            "hull_type",
            "ship_bonus_id",
            "source",
            "modifier_codes",
            "buffOperation",
            "targetCode",
            "triggerCode",
            "conditionCodes",
            "showPercentage",
            "ranked_values_min",
            "ranked_values_max",
        ],
    )
    return report
