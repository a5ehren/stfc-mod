import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPOSITORY_ROOT / "docs" / "schemas" / "remote-sync.schema.json"
VALID_FIXTURES_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "remote_sync" / "valid"
INVALID_FIXTURES_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "remote_sync" / "invalid"

EXPECTED_VALID_FIXTURES = {
    "battle.json",
    "buff.json",
    "emerald_chain.json",
    "forbidden_tech.json",
    "inventory.json",
    "job.json",
    "mission.json",
    "module.json",
    "officer.json",
    "research.json",
    "resource.json",
    "ship.json",
    "slot.json",
    "trait.json",
}
EXPECTED_INVALID_FIXTURES = {
    "empty_batch.json",
    "extra_mod_owned_field.json",
    "missing_required_field.json",
    "mixed_batch_families.json",
    "wrong_type_tag.json",
}


class RemoteSyncSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
            cls.schema = json.load(schema_file)

        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def test_schema_metadata_and_definitions(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(
            self.schema["$id"],
            "https://raw.githubusercontent.com/a5ehren/stfc-mod/dev/docs/schemas/remote-sync.schema.json",
        )
        self.assertIn("title", self.schema)
        self.assertIn("description", self.schema)
        self.assertIn("oneOf", self.schema)
        self.assertIn("$defs", self.schema)

    def test_exactly_fourteen_valid_fixtures_validate(self):
        fixture_paths = sorted(VALID_FIXTURES_DIR.glob("*.json"))
        self.assertEqual({path.name for path in fixture_paths}, EXPECTED_VALID_FIXTURES)
        self.assertEqual(len(fixture_paths), 14)

        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                with fixture_path.open(encoding="utf-8") as fixture_file:
                    document = json.load(fixture_file)
                errors = list(self.validator.iter_errors(document))
                self.assertEqual(errors, [], "\n".join(error.message for error in errors))

    def test_exactly_five_invalid_fixtures_are_rejected(self):
        fixture_paths = sorted(INVALID_FIXTURES_DIR.glob("*.json"))
        self.assertEqual({path.name for path in fixture_paths}, EXPECTED_INVALID_FIXTURES)
        self.assertEqual(len(fixture_paths), 5)

        for fixture_path in fixture_paths:
            with self.subTest(fixture=fixture_path.name):
                with fixture_path.open(encoding="utf-8") as fixture_file:
                    document = json.load(fixture_file)
                errors = list(self.validator.iter_errors(document))
                self.assertTrue(errors, f"{fixture_path.name} unexpectedly validated")


if __name__ == "__main__":
    unittest.main()
