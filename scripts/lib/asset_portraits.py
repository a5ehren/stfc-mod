"""Extract portrait and icon assets into ID-addressed folders."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from . import dump_runner


PORTRAIT_CLASSES = frozenset({"hostile", "ship", "crew", "ftech"})
CLASS_ALIASES = {"ctech": "ftech"}
ACCEPTED_CLASSES = PORTRAIT_CLASSES | frozenset(CLASS_ALIASES)
DEFAULT_BUNDLES = (
    "actors/thumbnail_index",
    "characters/thumbnails",
    "ships/ship_thumbnails",
    "ship_thumbnails_v2.hd",
    "ship_thumbnails_v2.md",
    "ship_thumbnails_v2.ld",
    "shared_ui/resource_icons",
    "shared_ui/resource_icons_large",
)
HOSTILE_CHARACTER_ID_MIN = 5000
IDENTIFIER_ID_RE = re.compile(r"/(-?\d+)$")
LOCALIZATION_CACHE_FILENAME = "LocalizationCacheData.json"
LOCALIZATION_STATUS_NAMES = {
    0: "CONTENTIDSTATUS_OK",
    1: "CONTENTIDSTATUS_REQUESTFAILED",
    2: "CONTENTIDSTATUS_MISSINGDATA",
}


@dataclass(frozen=True, slots=True)
class PortraitTarget:
    class_name: str
    internal_id: str
    art_id: str
    source: str
    identifiers: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    name_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AssetImage:
    name: str
    identifiers: frozenset[str]
    save: Callable[[Path], None]
    source: str | None = None


class AssetIndex:
    def __init__(self, images: Iterable[AssetImage] = ()) -> None:
        self._by_identifier: dict[str, AssetImage] = {}
        self._by_name: dict[str, AssetImage] = {}
        self._images: list[AssetImage] = []
        for image in images:
            self.add(image)

    @property
    def images(self) -> tuple[AssetImage, ...]:
        return tuple(self._images)

    def add(self, image: AssetImage) -> None:
        self._images.append(image)
        self._by_name.setdefault(image.name, image)
        for identifier in image.identifiers:
            self._by_identifier.setdefault(identifier, image)

    def find(self, target: PortraitTarget) -> AssetImage | None:
        for identifier in target.identifiers:
            image = self._by_identifier.get(identifier)
            if image is not None:
                return image

        for name in target.names:
            image = self._by_name.get(name)
            if image is not None:
                return image

        for prefix in target.name_prefixes:
            for name in sorted(self._by_name):
                if name.startswith(prefix):
                    return self._by_name[name]

        return None

    def character_art_ids(self) -> list[tuple[str, AssetImage]]:
        rows: list[tuple[str, AssetImage]] = []
        for identifier, image in self._by_identifier.items():
            if not identifier.startswith("Character/"):
                continue
            match = IDENTIFIER_ID_RE.search(identifier)
            if match is None:
                continue
            rows.append((match.group(1), image))
        return sorted(rows, key=lambda item: int(item[0]) if item[0].lstrip("-").isdigit() else item[0])


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _id_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value)
    return text if text else None


def _int_text(value: str) -> str:
    return str(int(value)) if value.lstrip("-").isdigit() else value


def _padded(value: str, width: int) -> str | None:
    if not value.lstrip("-").isdigit():
        return None
    return f"{int(value):0{width}d}"


def _collection(decoded_static_dir: Path, file_name: str, root_key: str) -> list[tuple[str, dict[str, Any]]]:
    data = _read_json(decoded_static_dir / f"{file_name}.json")
    if not isinstance(data, dict):
        return []
    root = data.get(root_key)
    if isinstance(root, dict):
        return [(str(key), value) for key, value in root.items() if isinstance(value, dict)]
    if isinstance(root, list):
        rows = []
        for index, value in enumerate(root):
            if isinstance(value, dict):
                rows.append((str(value.get("id", index)), value))
        return rows
    return []


def _art_id(row: dict[str, Any], field: str = "idRefs") -> str | None:
    refs = row.get(field)
    if not isinstance(refs, dict):
        return None
    return _id_key(refs.get("artId"))


def _target_id(key: str, row: dict[str, Any]) -> str | None:
    return _id_key(row.get("id")) or _id_key(key)


def _ship_target(key: str, hull: dict[str, Any]) -> PortraitTarget | None:
    id_str = hull.get("idStr")
    if not isinstance(id_str, str) or not id_str.startswith("Hull_G"):
        return None
    internal_id = _target_id(key, hull)
    art_id = _art_id(hull)
    if internal_id is None or art_id is None:
        return None
    compact = _int_text(art_id)
    names = [f"prefab_ship_{compact}"]
    padded = _padded(art_id, 3)
    if padded is not None:
        names.extend([f"prefab_ship_{padded}", f"prefab_ship_{padded}_thumb"])
    return PortraitTarget(
        class_name="ship",
        internal_id=internal_id,
        art_id=art_id,
        source="HullSpecs",
        identifiers=(f"Ships/prefab_ship_{compact}",),
        names=tuple(names),
    )


def _crew_target(key: str, officer: dict[str, Any]) -> PortraitTarget | None:
    internal_id = _target_id(key, officer)
    art_id = _art_id(officer)
    if internal_id is None or art_id is None:
        return None
    return PortraitTarget(
        class_name="crew",
        internal_id=internal_id,
        art_id=art_id,
        source="OfficerSpecs",
        identifiers=(f"Character/{_int_text(art_id)}",),
    )


def _ftech_target(_: str, tech: dict[str, Any]) -> PortraitTarget | None:
    internal_id = _id_key(tech.get("id"))
    art_id = _art_id(tech)
    if internal_id is None or art_id is None:
        return None
    compact = _int_text(art_id)
    prefixes = []
    padded = _padded(art_id, 4)
    if padded is not None:
        prefixes.append(f"FtechToken_{padded}_")
    return PortraitTarget(
        class_name="ftech",
        internal_id=internal_id,
        art_id=art_id,
        source="ForbiddenTechSpecs",
        identifiers=(f"forbiddentech/item_{compact}",),
        name_prefixes=tuple(prefixes),
    )


def _generated_hostiles(decoded_static_dir: Path) -> list[PortraitTarget]:
    targets: list[PortraitTarget] = []
    seen: set[tuple[str, str]] = set()
    for file_name, root_key in (("EntitySlotsData", "entitySlots"), ("EntitySlots", "entitySlots_")):
        data = _read_json(decoded_static_dir / f"{file_name}.json")
        if not isinstance(data, dict):
            continue
        for root in data.get(root_key, []) or []:
            slots = root.get("slots") if isinstance(root, dict) else None
            if slots is None and isinstance(data.get(root_key), list):
                slots = data.get(root_key)
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                challenge = slot.get("challengeLadderSlotParams")
                if not isinstance(challenge, dict):
                    continue
                ship = challenge.get("generatedShip")
                if not isinstance(ship, dict):
                    continue
                internal_id = _id_key(ship.get("hullId"))
                art_id = _art_id(ship, "officerIdRefs")
                if internal_id is None or art_id is None:
                    continue
                key = (internal_id, art_id)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(
                    PortraitTarget(
                        class_name="hostile",
                        internal_id=internal_id,
                        art_id=art_id,
                        source=file_name,
                        identifiers=(f"Character/{_int_text(art_id)}",),
                    )
                )
    return targets


def _asset_hostiles(asset_index: AssetIndex) -> list[PortraitTarget]:
    targets: list[PortraitTarget] = []
    for art_id, image in asset_index.character_art_ids():
        if not art_id.lstrip("-").isdigit() or int(art_id) < HOSTILE_CHARACTER_ID_MIN:
            continue
        targets.append(
            PortraitTarget(
                class_name="hostile",
                internal_id=art_id,
                art_id=art_id,
                source="CharacterThumbnailDatabase",
                identifiers=(f"Character/{art_id}",),
                names=(image.name,),
            )
        )
    return targets


def build_portrait_targets(
    decoded_static_dir: Path,
    *,
    asset_index: AssetIndex | None = None,
    classes: set[str] | None = None,
) -> list[PortraitTarget]:
    selected = _normalize_classes(classes)

    targets: list[PortraitTarget] = []
    if "ship" in selected:
        targets.extend(
            target
            for _, hull in _collection(decoded_static_dir, "HullSpecs", "hullSpecs")
            if (target := _ship_target(str(hull.get("id", "")), hull)) is not None
        )
    if "crew" in selected:
        targets.extend(
            target
            for key, officer in _collection(decoded_static_dir, "OfficerSpecs", "officerSpecs")
            if (target := _crew_target(key, officer)) is not None
        )
    if "ftech" in selected:
        targets.extend(
            target
            for key, tech in _collection(decoded_static_dir, "ForbiddenTechSpecs", "forbiddenTechSpecs")
            if (target := _ftech_target(key, tech)) is not None
        )
    if "hostile" in selected:
        targets.extend(_generated_hostiles(decoded_static_dir))
        if asset_index is not None:
            existing = {(target.internal_id, target.art_id) for target in targets if target.class_name == "hostile"}
            for target in _asset_hostiles(asset_index):
                key = (target.internal_id, target.art_id)
                if key not in existing:
                    targets.append(target)
                    existing.add(key)

    deduped: dict[tuple[str, str], PortraitTarget] = {}
    for target in targets:
        deduped.setdefault((target.class_name, target.internal_id), target)
    return sorted(deduped.values(), key=lambda target: (target.class_name, _sort_key(target.internal_id)))


def _sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.lstrip("-").isdigit() else (1, value)


def _normalize_classes(classes: set[str] | None) -> set[str]:
    if classes is None:
        return set(PORTRAIT_CLASSES)
    unknown = classes - ACCEPTED_CLASSES
    if unknown:
        raise ValueError(f"Unsupported portrait class(es): {', '.join(sorted(unknown))}")
    return {CLASS_ALIASES.get(class_name, class_name) for class_name in classes}


def export_portraits(
    targets: Iterable[PortraitTarget],
    asset_index: AssetIndex,
    *,
    out_dir: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"exports": {}, "missing_targets": []}
    exported = 0
    missing = 0
    skipped_existing = 0

    for target in targets:
        image = asset_index.find(target)
        rel_path = Path(target.class_name) / f"{target.internal_id}.png"
        if image is None:
            missing += 1
            manifest["missing_targets"].append(_target_manifest(target))
            continue

        dest = out_dir / rel_path
        if dest.exists() and not overwrite:
            skipped_existing += 1
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            image.save(dest)
            exported += 1

        manifest["exports"][rel_path.as_posix()] = {
            **_target_manifest(target),
            "asset_name": image.name,
            "asset_source": image.source,
        }

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "targets": exported + missing + skipped_existing,
        "exported": exported,
        "missing": missing,
        "skipped_existing": skipped_existing,
        "manifest": str(out_dir / "manifest.json"),
    }


def _target_manifest(target: PortraitTarget) -> dict[str, Any]:
    return {
        "class": target.class_name,
        "internal_id": target.internal_id,
        "art_id": target.art_id,
        "source": target.source,
        "identifiers": list(target.identifiers),
        "names": list(target.names),
        "name_prefixes": list(target.name_prefixes),
    }


class _ProtoReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def done(self) -> bool:
        return self.pos >= len(self.data)

    def varint(self) -> int:
        shift = 0
        value = 0
        while shift < 70:
            if self.pos >= len(self.data):
                raise ValueError("truncated protobuf varint")
            byte = self.data[self.pos]
            self.pos += 1
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value
            shift += 7
        raise ValueError("protobuf varint is too long")

    def length_delimited(self) -> bytes:
        size = self.varint()
        end = self.pos + size
        if end > len(self.data):
            raise ValueError("truncated protobuf length-delimited field")
        value = self.data[self.pos : end]
        self.pos = end
        return value

    def tag(self) -> tuple[int, int]:
        tag = self.varint()
        field_number = tag >> 3
        wire_type = tag & 0x07
        if field_number == 0:
            raise ValueError("invalid protobuf field number 0")
        return field_number, wire_type

    def skip(self, wire_type: int) -> None:
        if wire_type == 0:
            self.varint()
        elif wire_type == 1:
            self._skip_bytes(8)
        elif wire_type == 2:
            self._skip_bytes(self.varint())
        elif wire_type == 5:
            self._skip_bytes(4)
        else:
            raise ValueError(f"unsupported protobuf wire type {wire_type}")

    def _skip_bytes(self, size: int) -> None:
        end = self.pos + size
        if end > len(self.data):
            raise ValueError("truncated protobuf fixed-width field")
        self.pos = end


def _proto_string(reader: _ProtoReader) -> str:
    return reader.length_delimited().decode("utf-8")


def _int64_text(value: int) -> str:
    if value >= (1 << 63):
        value -= 1 << 64
    return str(value)


def _parse_category_info(data: bytes) -> dict[str, Any]:
    reader = _ProtoReader(data)
    info: dict[str, Any] = {}
    while not reader.done():
        field_number, wire_type = reader.tag()
        if field_number == 1 and wire_type == 0:
            info["id"] = _int64_text(reader.varint())
        elif field_number == 2 and wire_type == 2:
            info["name"] = _proto_string(reader)
        elif field_number == 3 and wire_type == 0:
            dynamic = bool(reader.varint())
            if dynamic:
                info["dynamic"] = dynamic
        else:
            reader.skip(wire_type)
    return info


def _parse_cached_translation(data: bytes) -> dict[str, Any]:
    reader = _ProtoReader(data)
    translation: dict[str, Any] = {}
    while not reader.done():
        field_number, wire_type = reader.tag()
        if field_number == 1 and wire_type == 2:
            translation["id"] = _proto_string(reader)
        elif field_number == 2 and wire_type == 0:
            translation["key"] = _int64_text(reader.varint())
        elif field_number == 3 and wire_type == 2:
            translation["text"] = _proto_string(reader)
        elif field_number == 4 and wire_type == 0:
            status = reader.varint()
            translation["status"] = LOCALIZATION_STATUS_NAMES.get(status, str(status))
        else:
            reader.skip(wire_type)
    return translation


def _parse_translation_entry(data: bytes) -> tuple[str, dict[str, Any]] | None:
    reader = _ProtoReader(data)
    key: str | None = None
    value: dict[str, Any] | None = None
    while not reader.done():
        field_number, wire_type = reader.tag()
        if field_number == 1 and wire_type == 0:
            key = _int64_text(reader.varint())
        elif field_number == 2 and wire_type == 2:
            value = _parse_cached_translation(reader.length_delimited())
        else:
            reader.skip(wire_type)
    if value is None:
        return None
    return key or value.get("key") or "0", value


def _parse_cached_category(data: bytes) -> dict[str, Any]:
    reader = _ProtoReader(data)
    category: dict[str, Any] = {}
    translations: dict[str, dict[str, Any]] = {}
    while not reader.done():
        field_number, wire_type = reader.tag()
        if field_number == 1 and wire_type == 2:
            category["info"] = _parse_category_info(reader.length_delimited())
        elif field_number == 2 and wire_type == 2:
            entry = _parse_translation_entry(reader.length_delimited())
            if entry is not None:
                key, value = entry
                translations[key] = value
        else:
            reader.skip(wire_type)
    if translations:
        category["translations"] = translations
    return category


def _parse_category_entry(data: bytes) -> tuple[str, dict[str, Any]] | None:
    reader = _ProtoReader(data)
    key: str | None = None
    value: dict[str, Any] | None = None
    while not reader.done():
        field_number, wire_type = reader.tag()
        if field_number == 1 and wire_type == 0:
            key = _int64_text(reader.varint())
        elif field_number == 2 and wire_type == 2:
            value = _parse_cached_category(reader.length_delimited())
        else:
            reader.skip(wire_type)
    if value is None:
        return None
    return key or value.get("info", {}).get("id") or "0", value


def decode_localization_cache_data(data: bytes) -> dict[str, Any]:
    reader = _ProtoReader(data)
    decoded: dict[str, Any] = {}
    categories: dict[str, dict[str, Any]] = {}
    while not reader.done():
        field_number, wire_type = reader.tag()
        if field_number == 1 and wire_type == 2:
            decoded["language"] = _proto_string(reader)
        elif field_number == 2 and wire_type == 2:
            entry = _parse_category_entry(reader.length_delimited())
            if entry is not None:
                key, value = entry
                categories[key] = value
        else:
            reader.skip(wire_type)
    if categories:
        decoded["categories"] = categories
    return decoded


def default_locale_dir() -> Path | None:
    candidates = [
        Path.home() / "Library" / "Application Support" / "com.scopely.startrek" / "LocaleDB",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def locale_cache_file(*, locale_file: Path | None = None, locale_dir: Path | None = None, language: str = "en") -> Path:
    if locale_file is not None:
        return locale_file
    root = locale_dir or default_locale_dir()
    if root is None:
        raise FileNotFoundError("Could not find LocaleDB; pass --locale-file or --locale-dir")
    return root / f"locale_{language}.bin"


def export_localization_cache(locale_file: Path, *, out_dir: Path) -> dict[str, Any]:
    source = Path(locale_file)
    if not source.exists():
        raise FileNotFoundError(f"Missing localization cache file: {source}")

    decoded = decode_localization_cache_data(source.read_bytes())
    categories = decoded.get("categories", {})
    category_count = len(categories) if isinstance(categories, dict) else 0
    translation_count = 0
    if isinstance(categories, dict):
        for category in categories.values():
            if isinstance(category, dict) and isinstance(category.get("translations"), dict):
                translation_count += len(category["translations"])

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / LOCALIZATION_CACHE_FILENAME
    out_path.write_text(json.dumps(decoded, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "source": str(source),
        "out": str(out_path),
        "language": decoded.get("language"),
        "categories": category_count,
        "translations": translation_count,
    }


def _unitypy_missing() -> RuntimeError:
    return RuntimeError(
        "UnityPy is required to read Unity asset bundles. Install it in the Python environment used for this script "
        "with: python3 -m pip install UnityPy"
    )


def _image_name(data: Any) -> str:
    return str(getattr(data, "m_Name", None) or getattr(data, "name", None) or "")


def _save_unity_image(obj: Any, dest: Path) -> None:
    data = obj.read()
    data.image.save(dest)


def load_unity_asset_index(bundle_paths: Iterable[Path]) -> AssetIndex:
    try:
        import UnityPy  # type: ignore[import-not-found]
    except ImportError as exc:
        raise _unitypy_missing() from exc

    paths = [Path(path) for path in bundle_paths if Path(path).exists()]
    if not paths:
        raise FileNotFoundError("No asset bundles found to load")

    env = UnityPy.load(*(str(path) for path in paths))
    index = AssetIndex()
    images_by_path_id: dict[int, AssetImage] = {}
    identifiers_by_path_id: dict[int, set[str]] = {}
    source_by_path_id: dict[int, str] = {}

    for obj in env.objects:
        if obj.type.name not in {"Sprite", "Texture2D"}:
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        name = _image_name(data)
        if not name:
            continue
        source = str(getattr(getattr(obj, "assets_file", None), "name", "") or "")
        image = AssetImage(
            name=name,
            identifiers=frozenset(),
            source=source or None,
            save=lambda dest, unity_obj=obj: _save_unity_image(unity_obj, dest),
        )
        images_by_path_id[int(obj.path_id)] = image
        source_by_path_id[int(obj.path_id)] = source

    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            typetree = obj.read_typetree()
        except Exception:
            continue
        for entry in _database_entries(typetree):
            identifier = entry.get("m_identifier")
            sprite = entry.get("m_originalSprite")
            if not isinstance(identifier, str) or not isinstance(sprite, dict):
                continue
            path_id = sprite.get("m_PathID")
            if not path_id:
                continue
            identifiers_by_path_id.setdefault(int(path_id), set()).add(identifier)

    for path_id, image in images_by_path_id.items():
        index.add(
            AssetImage(
                name=image.name,
                identifiers=frozenset(identifiers_by_path_id.get(path_id, set())),
                source=source_by_path_id.get(path_id) or image.source,
                save=image.save,
            )
        )
    return index


def _database_entries(typetree: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key in ("Entries", "m_assetTable"):
        value = typetree.get(key)
        if isinstance(value, list):
            entries.extend(entry for entry in value if isinstance(entry, dict))
    return entries


def prebundles_dir_from_game_dir(game_dir: Path) -> Path:
    game_files = dump_runner.locate_game_files(Path(game_dir))
    data_dir = game_files.global_game_managers.parent
    return data_dir / "StreamingAssets" / "Pre-Bundles"


def default_bundle_paths(asset_root: Path) -> list[Path]:
    return [asset_root / rel for rel in DEFAULT_BUNDLES]


def parse_classes(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    raw_values = {item.strip() for item in raw.split(",") if item.strip()}
    unknown = raw_values - ACCEPTED_CLASSES
    if unknown:
        raise argparse.ArgumentTypeError(f"unsupported class(es): {', '.join(sorted(unknown))}")
    return {CLASS_ALIASES.get(item, item) for item in raw_values}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dump selected STFC assets into decoded output folders.")
    sub = parser.add_subparsers(dest="command", required=True)

    portraits = sub.add_parser("portraits", help="export hostile, ship, crew, and forbidden/chaos tech portraits/icons")
    source = portraits.add_mutually_exclusive_group(required=True)
    source.add_argument("--game-dir", type=Path, help="Path to the game directory (.app on macOS, game root on Windows)")
    source.add_argument("--asset-root", type=Path, help="Path to StreamingAssets/Pre-Bundles")
    portraits.add_argument("--decoded-static-dir", type=Path, required=True, help="Directory containing decoded static JSON")
    portraits.add_argument("--out-dir", type=Path, required=True, help="Destination portrait directory")
    portraits.add_argument(
        "--classes",
        type=parse_classes,
        help="Comma-separated classes to export; ctech is accepted as an alias for ftech",
    )
    portraits.add_argument("--bundle", type=Path, action="append", help="Additional or explicit bundle path to load")
    portraits.add_argument("--overwrite", action="store_true", help="Overwrite existing PNGs")
    portraits.add_argument("--dry-run", action="store_true", help="Build indexes and report counts without writing PNGs")
    portraits.add_argument("--strict-missing", action="store_true", help="Exit non-zero if any target cannot be matched")
    portraits.set_defaults(func=cmd_portraits)

    localization = sub.add_parser("localization", help="export cached localization strings")
    localization_source = localization.add_mutually_exclusive_group()
    localization_source.add_argument("--locale-file", type=Path, help="Path to a locale_<language>.bin cache file")
    localization_source.add_argument("--locale-dir", type=Path, help="Directory containing locale_<language>.bin files")
    localization.add_argument("--language", default="en", help="Language code to load from --locale-dir (default: en)")
    localization.add_argument("--out-dir", type=Path, required=True, help="Destination decoded static directory")
    localization.set_defaults(func=cmd_localization)
    return parser


def cmd_portraits(args: argparse.Namespace) -> int:
    try:
        asset_root = Path(args.asset_root) if args.asset_root else prebundles_dir_from_game_dir(Path(args.game_dir))
        bundle_paths = [Path(path) for path in args.bundle] if args.bundle else default_bundle_paths(asset_root)
        asset_index = load_unity_asset_index(bundle_paths)
        targets = build_portrait_targets(
            Path(args.decoded_static_dir),
            asset_index=asset_index,
            classes=args.classes,
        )
        if args.dry_run:
            report = _dry_run_report(targets, asset_index, bundle_count=len(bundle_paths))
            print(json.dumps(report, indent=2, sort_keys=True))
            return 2 if args.strict_missing and report["missing"] else 0
        report = export_portraits(targets, asset_index, out_dir=Path(args.out_dir), overwrite=args.overwrite)
    except (ExceptionGroup, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if args.strict_missing and report["missing"] else 0


def cmd_localization(args: argparse.Namespace) -> int:
    try:
        source = locale_cache_file(
            locale_file=Path(args.locale_file) if args.locale_file else None,
            locale_dir=Path(args.locale_dir) if args.locale_dir else None,
            language=args.language,
        )
        report = export_localization_cache(source, out_dir=Path(args.out_dir))
    except (FileNotFoundError, RuntimeError, UnicodeDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _dry_run_report(targets: list[PortraitTarget], asset_index: AssetIndex, *, bundle_count: int) -> dict[str, Any]:
    by_class = {class_name: {"targets": 0, "missing": 0} for class_name in sorted(PORTRAIT_CLASSES)}
    missing = 0
    for target in targets:
        bucket = by_class.setdefault(target.class_name, {"targets": 0, "missing": 0})
        bucket["targets"] += 1
        if asset_index.find(target) is None:
            bucket["missing"] += 1
            missing += 1
    return {
        "targets": len(targets),
        "missing": missing,
        "bundles": bundle_count,
        "by_class": by_class,
    }
