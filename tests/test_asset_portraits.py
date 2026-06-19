from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.asset_portraits import (
    AssetImage,
    AssetIndex,
    build_portrait_targets,
    decode_localization_cache_data,
    export_localization_cache,
    export_portraits,
    parse_classes,
)


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field_varint(field_number: int, value: int) -> bytes:
    return _varint(field_number << 3) + _varint(value)


def _field_bytes(field_number: int, value: bytes) -> bytes:
    return _varint((field_number << 3) | 2) + _varint(len(value)) + value


def _field_string(field_number: int, value: str) -> bytes:
    return _field_bytes(field_number, value.encode("utf-8"))


class AssetPortraitTests(unittest.TestCase):
    def test_decode_localization_cache_data_reads_cached_translations(self) -> None:
        translation = (
            _field_string(1, "research_project_name")
            + _field_varint(2, 249)
            + _field_string(3, "Impulse Optimization")
            + _field_varint(4, 0)
        )
        translation_entry = _field_varint(1, 249) + _field_bytes(2, translation)
        category_info = _field_varint(1, 7) + _field_string(2, "research") + _field_varint(3, 1)
        category = _field_bytes(1, category_info) + _field_bytes(2, translation_entry)
        category_entry = _field_varint(1, 7) + _field_bytes(2, category)
        payload = _field_string(1, "en") + _field_bytes(2, category_entry)

        decoded = decode_localization_cache_data(payload)

        self.assertEqual("en", decoded["language"])
        category = decoded["categories"]["7"]
        self.assertEqual({"id": "7", "name": "research", "dynamic": True}, category["info"])
        self.assertEqual(
            {
                "id": "research_project_name",
                "key": "249",
                "text": "Impulse Optimization",
                "status": "CONTENTIDSTATUS_OK",
            },
            category["translations"]["249"],
        )

    def test_export_localization_cache_writes_decoded_static_json(self) -> None:
        translation = _field_varint(2, 300) + _field_string(3, "Dodge Boost")
        translation_entry = _field_varint(1, 300) + _field_bytes(2, translation)
        category_info = _field_varint(1, 2) + _field_string(2, "trees")
        category = _field_bytes(1, category_info) + _field_bytes(2, translation_entry)
        category_entry = _field_varint(1, 2) + _field_bytes(2, category)
        payload = _field_string(1, "en") + _field_bytes(2, category_entry)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            locale_file = root / "locale_en.bin"
            out_dir = root / "decoded"
            locale_file.write_bytes(payload)

            report = export_localization_cache(locale_file, out_dir=out_dir)

            decoded = json.loads((out_dir / "LocalizationCacheData.json").read_text(encoding="utf-8"))

        self.assertEqual("en", decoded["language"])
        self.assertEqual("Dodge Boost", decoded["categories"]["2"]["translations"]["300"]["text"])
        self.assertEqual(1, report["categories"])
        self.assertEqual(1, report["translations"])

    def test_builds_portrait_targets_from_decoded_static(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td)
            (decoded / "HullSpecs.json").write_text(
                json.dumps(
                    {
                        "hullSpecs": {
                            "111": {"id": "111", "idStr": "Hull_G4_Explorer_Test", "idRefs": {"artId": "9"}},
                            "222": {"id": "222", "idStr": "Hull_L30_Destroyer_Test", "idRefs": {"artId": "10"}},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (decoded / "OfficerSpecs.json").write_text(
                json.dumps({"officerSpecs": {"333": {"id": "333", "idRefs": {"artId": "42"}}}}),
                encoding="utf-8",
            )
            (decoded / "ForbiddenTechSpecs.json").write_text(
                json.dumps(
                    {
                        "forbiddenTechSpecs": [
                            {"id": "444", "idRefs": {"artId": "1"}},
                            {"id": "445", "requiredSlotSpecId": "953301906", "idRefs": {"artId": "58"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (decoded / "ConsumableSpecs.json").write_text(
                json.dumps({"spec": [{"id": "555", "name": "Consumable_Test_Tech", "idRefs": {"artId": "777"}}]}),
                encoding="utf-8",
            )
            (decoded / "EntitySlotsData.json").write_text(
                json.dumps(
                    {
                        "entitySlots": [
                            {
                                "slots": [
                                    {
                                        "challengeLadderSlotParams": {
                                            "generatedShip": {
                                                "hullId": "666",
                                                "officerIdRefs": {"artId": "5016"},
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            targets = {(target.class_name, target.internal_id): target for target in build_portrait_targets(decoded)}

        self.assertEqual("Ships/prefab_ship_9", targets[("ship", "111")].identifiers[0])
        self.assertIn("prefab_ship_009_thumb", targets[("ship", "111")].names)
        self.assertEqual("Character/42", targets[("crew", "333")].identifiers[0])
        self.assertEqual("forbiddentech/item_1", targets[("ftech", "444")].identifiers[0])
        self.assertIn("FtechToken_0001_", targets[("ftech", "444")].name_prefixes)
        self.assertEqual("forbiddentech/item_58", targets[("ftech", "445")].identifiers[0])
        self.assertIn("FtechToken_0058_", targets[("ftech", "445")].name_prefixes)
        self.assertNotIn(("ctech", "555"), targets)
        self.assertEqual("Character/5016", targets[("hostile", "666")].identifiers[0])

    def test_export_portraits_uses_identifier_then_name_prefix(self) -> None:
        saved: list[tuple[str, Path]] = []

        def image(name: str, *identifiers: str) -> AssetImage:
            return AssetImage(name=name, identifiers=frozenset(identifiers), save=lambda path: saved.append((name, path)))

        index = AssetIndex(
            [
                image("crew-image", "Character/42"),
                image("ship-image", "Ships/prefab_ship_9"),
                image("ftech-image", "forbiddentech/item_1"),
            ]
        )

        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded"
            out_dir = Path(td) / "portraits"
            decoded.mkdir()
            (decoded / "HullSpecs.json").write_text(
                json.dumps({"hullSpecs": {"111": {"id": "111", "idStr": "Hull_G4_Test", "idRefs": {"artId": "9"}}}}),
                encoding="utf-8",
            )
            (decoded / "OfficerSpecs.json").write_text(
                json.dumps({"officerSpecs": {"333": {"id": "333", "idRefs": {"artId": "42"}}}}),
                encoding="utf-8",
            )
            (decoded / "ForbiddenTechSpecs.json").write_text(
                json.dumps({"forbiddenTechSpecs": [{"id": "444", "idRefs": {"artId": "1"}}]}),
                encoding="utf-8",
            )
            (decoded / "ConsumableSpecs.json").write_text(
                json.dumps({"spec": [{"id": "555", "name": "Consumable_Test_Tech", "idRefs": {"artId": "777"}}]}),
                encoding="utf-8",
            )

            report = export_portraits(build_portrait_targets(decoded), index, out_dir=out_dir)

            saved_paths = {path.relative_to(out_dir).as_posix() for _, path in saved}
            self.assertEqual(
                {"crew/333.png", "ship/111.png", "ftech/444.png"},
                saved_paths,
            )
            self.assertEqual(3, report["exported"])
            self.assertEqual(0, report["missing"])
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("ftech-image", manifest["exports"]["ftech/444.png"]["asset_name"])

    def test_ctech_selector_exports_forbidden_tech_without_a_split_folder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td)
            (decoded / "ForbiddenTechSpecs.json").write_text(
                json.dumps(
                    {
                        "forbiddenTechSpecs": [
                            {"id": "444", "idRefs": {"artId": "1"}},
                            {"id": "445", "requiredSlotSpecId": "953301906", "idRefs": {"artId": "58"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (decoded / "ConsumableSpecs.json").write_text(
                json.dumps({"spec": [{"id": "555", "idRefs": {"artId": "777"}}]}),
                encoding="utf-8",
            )

            targets = build_portrait_targets(decoded, classes=parse_classes("ctech"))

        self.assertEqual(
            [("ftech", "444", "1"), ("ftech", "445", "58")],
            [(target.class_name, target.internal_id, target.art_id) for target in targets],
        )

    def test_asset_index_can_add_hostile_targets_from_character_art_ids(self) -> None:
        index = AssetIndex(
            [
                AssetImage(name="tex_thumbnail_actor_kirk", identifiers=frozenset({"Character/1"}), save=lambda path: None),
                AssetImage(name="Gavolar_5003", identifiers=frozenset({"Character/5003"}), save=lambda path: None),
                AssetImage(name="5115_G7_ROM_male_hostile_portrait", identifiers=frozenset({"Character/5115"}), save=lambda path: None),
            ]
        )

        targets = build_portrait_targets(Path("/does/not/exist"), asset_index=index, classes={"hostile"})

        self.assertEqual(
            [("5003", "Character/5003"), ("5115", "Character/5115")],
            [(target.internal_id, target.identifiers[0]) for target in targets],
        )


if __name__ == "__main__":
    unittest.main()
