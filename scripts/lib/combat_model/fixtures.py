from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FixtureError(ValueError):
    pass


REQUIRED_TOP_LEVEL_KEYS = ("schema_version", "game_version", "source_payloads", "initial_state", "rounds")


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"invalid fixture JSON in {path}: {exc}") from exc

    if not isinstance(fixture, dict):
        raise FixtureError("fixture root must be an object")

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in fixture:
            raise FixtureError(f"missing required fixture key: {key}")

    if fixture["schema_version"] != 1:
        raise FixtureError(f"unsupported fixture schema_version: {fixture['schema_version']}")

    if not isinstance(fixture["source_payloads"], list) or not fixture["source_payloads"]:
        raise FixtureError("source_payloads must be a non-empty list")

    if not isinstance(fixture["rounds"], list) or not fixture["rounds"]:
        raise FixtureError("rounds must be a non-empty list")

    return fixture
