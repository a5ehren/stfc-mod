import copy
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

    def load_valid_fixture(self, name):
        with (VALID_FIXTURES_DIR / name).open(encoding="utf-8") as fixture_file:
            return json.load(fixture_file)

    def assert_rejected(self, document):
        errors = list(self.validator.iter_errors(document))
        self.assertTrue(errors, "mutated document unexpectedly validated")

    def find_record(self, document, record_type, **attributes):
        matches = [
            record
            for record in document
            if record.get("type") == record_type
            and all(record.get(name) == value for name, value in attributes.items())
        ]
        self.assertEqual(len(matches), 1, f"expected one {record_type} record matching {attributes}")
        return matches[0]

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

    def test_emerald_chain_empty_claims_use_unknown_sentinel(self):
        document = self.load_valid_fixture("emerald_chain.json")
        emerald_chain = self.find_record(document, "emerald_chain")
        emerald_chain["level"] = -1

        errors = list(self.validator.iter_errors(document))
        self.assertEqual(errors, [], "\n".join(error.message for error in errors))

    def test_emerald_chain_non_sentinel_negative_level_is_rejected(self):
        document = self.load_valid_fixture("emerald_chain.json")
        emerald_chain = self.find_record(document, "emerald_chain")
        emerald_chain["level"] = -2

        self.assert_rejected(document)

    def test_extra_nested_slot_params_field_is_rejected(self):
        document = self.load_valid_fixture("slot.json")
        crew_slot = self.find_record(document, "slot", slot_type=2)
        crew_slot["params"]["unexpected"] = True

        self.assert_rejected(document)

    def test_wrong_job_variant_field_for_job_type_is_rejected(self):
        document = self.load_valid_fixture("job.json")
        research_job = self.find_record(document, "job", job_type=3)
        research_job["bid"] = research_job.pop("rid")

        self.assert_rejected(document)

    def test_slot_discriminator_and_params_pairing_is_rejected(self):
        document = self.load_valid_fixture("slot.json")
        empty_slot = self.find_record(document, "slot", slot_type=0)
        crew_slot = self.find_record(document, "slot", slot_type=2)
        empty_slot["params"] = copy.deepcopy(crew_slot["params"])

        self.assert_rejected(document)

    def test_negative_non_sentinel_state_or_percentage_is_rejected(self):
        negative_state = self.load_valid_fixture("research.json")
        research = self.find_record(negative_state, "research")
        research["level"] = -1
        self.assert_rejected(negative_state)

        negative_percentage = self.load_valid_fixture("ship.json")
        ship = self.find_record(negative_percentage, "ship")
        ship["level_percentage"] = -0.1
        self.assert_rejected(negative_percentage)

    def test_all_schema_refs_are_local_existing_defs(self):
        refs = []

        def collect_refs(node):
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str):
                    refs.append(ref)
                for value in node.values():
                    collect_refs(value)
            elif isinstance(node, list):
                for value in node:
                    collect_refs(value)

        collect_refs(self.schema)

        self.assertTrue(refs)
        for ref in refs:
            with self.subTest(ref=ref):
                self.assertRegex(ref, r"^#/\$defs/[^/]+$")
                self.assertIn(ref.removeprefix("#/$defs/"), self.schema["$defs"])


if __name__ == "__main__":
    unittest.main()
