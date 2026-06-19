# PvE Combat Model Viability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PvE combat-model viability spike that captures controlled battle evidence, normalizes it into fixtures, replays rounds offline, and reports whether the model meets the MVP threshold.

**Architecture:** Keep runtime capture narrow inside the existing sync flow, and keep replay/compare/report logic offline in Python. Use a small C++ decoder target only for protobuf payloads because the repo already builds C++ protobuf types and does not currently carry Python protobuf dependencies.

**Tech Stack:** C++23, XMake, protobuf C++/`google::protobuf::util::MessageToJsonString`, `nlohmann_json`, Python 3 stdlib `unittest`/`argparse`/`dataclasses`/`json`/`pathlib`.

**Spec:** `docs/superpowers/specs/2026-05-01-combat-model-viability-design.md`

---

## Scope Check

This plan implements one project: PvE combat-model viability. It does not build a crew optimizer, PvP model, or UI. Hook-assisted instrumentation is not part of the first implementation path; it remains a fallback after replay reports identify a concrete blind spot.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/combat-model.py` | Create | Python CLI entrypoint for fixture validation, replay, and reports |
| `scripts/lib/combat_model/__init__.py` | Create | Package exports for combat model tooling |
| `scripts/lib/combat_model/models.py` | Create | Dataclasses for fixtures, traces, comparisons, and thresholds |
| `scripts/lib/combat_model/fixtures.py` | Create | Load and validate normalized fixture JSON |
| `scripts/lib/combat_model/replay.py` | Create | Deterministic round replay engine over normalized inputs |
| `scripts/lib/combat_model/compare.py` | Create | Round-by-round comparator and mismatch classification |
| `scripts/lib/combat_model/reporting.py` | Create | Markdown/JSON report rendering |
| `scripts/lib/combat_model/static_normalizer.py` | Create | Convert decoded static payload JSON plus battle journal JSON into normalized fixture JSON |
| `tests/test_combat_model_models.py` | Create | Model and threshold tests |
| `tests/test_combat_model_fixtures.py` | Create | Fixture loading and validation tests |
| `tests/test_combat_model_compare.py` | Create | Comparator and report tests |
| `tests/test_combat_model_replay.py` | Create | Replay-engine tests |
| `tests/test_combat_model_static_normalizer.py` | Create | Static normalizer tests using tiny decoded payload samples |
| `tests/test_combat_model_capture_static.py` | Create | Static source tests for capture config and sync integration |
| `mods/src/patches/parts/combat_model_capture.h` | Create | Runtime capture helper interface |
| `mods/src/patches/parts/combat_model_capture.cc` | Create | Runtime capture helper implementation |
| `mods/src/patches/parts/sync.cc` | Modify | Call capture helper for entity groups and PvE battle journals |
| `mods/src/config.h` | Modify | Add combat-model capture config fields |
| `mods/src/config.cc` | Modify | Load combat-model capture config |
| `mods/src/defaultconfig.h` | Modify | Add capture defaults, disabled by default |
| `example_community_patch_settings.toml` | Modify | Document capture settings, disabled by default |
| `tools/combat-model/xmake.lua` | Create | XMake target for protobuf capture decoder |
| `tools/combat-model/src/main.cc` | Create | Decode raw captured protobuf payloads to JSON |
| `xmake.lua` | Modify | Include `tools/combat-model` target |
| `docs/combat-model-viability.md` | Create | Operator notes for capture, fixture building, replay, and reporting |

---

### Task 1: Python Combat Model CLI And Core Models

**Files:**
- Create: `scripts/combat-model.py`
- Create: `scripts/lib/combat_model/__init__.py`
- Create: `scripts/lib/combat_model/models.py`
- Test: `tests/test_combat_model_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/test_combat_model_models.py`:

```python
from __future__ import annotations

import unittest

from scripts.lib.combat_model.models import (
    CombatState,
    DamageBreakdown,
    ReplayThreshold,
    RoundTrace,
)


class CombatModelTests(unittest.TestCase):
    def test_threshold_accepts_mvp_damage_delta(self) -> None:
        threshold = ReplayThreshold.mvp()

        self.assertTrue(threshold.damage_within_limit(expected=1000, actual=1125))
        self.assertTrue(threshold.damage_within_limit(expected=1000, actual=800))
        self.assertFalse(threshold.damage_within_limit(expected=1000, actual=799))
        self.assertFalse(threshold.damage_within_limit(expected=1000, actual=1201))

    def test_round_trace_serializes_to_plain_dict(self) -> None:
        trace = RoundTrace(
            round_number=1,
            acting_side="player",
            action="kinetic",
            attacker=CombatState(hull=10000, shield=5000),
            defender_before=CombatState(hull=8000, shield=3000),
            defender_after=CombatState(hull=7500, shield=0),
            damage=DamageBreakdown(raw=4000, mitigated=3500, shield=3000, hull=500),
            triggered_effects=["captain_maneuver"],
        )

        self.assertEqual(
            trace.to_dict(),
            {
                "round": 1,
                "acting_side": "player",
                "action": "kinetic",
                "attacker": {"hull": 10000, "shield": 5000},
                "defender_before": {"hull": 8000, "shield": 3000},
                "defender_after": {"hull": 7500, "shield": 0},
                "damage": {"raw": 4000, "mitigated": 3500, "shield": 3000, "hull": 500},
                "triggered_effects": ["captain_maneuver"],
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_models.py
```

Expected: import failure for `scripts.lib.combat_model`.

- [ ] **Step 3: Add package and model implementation**

Create `scripts/lib/combat_model/__init__.py`:

```python
"""Offline PvE combat model viability tooling."""
```

Create `scripts/lib/combat_model/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Side = Literal["player", "hostile"]


@dataclass(frozen=True, slots=True)
class ReplayThreshold:
    """Damage tolerance for round replay comparison."""

    max_relative_delta: float

    @classmethod
    def mvp(cls) -> "ReplayThreshold":
        return cls(max_relative_delta=0.20)

    @classmethod
    def release(cls) -> "ReplayThreshold":
        return cls(max_relative_delta=0.10)

    def damage_within_limit(self, *, expected: int, actual: int) -> bool:
        if expected == 0:
            return actual == 0
        delta = abs(actual - expected) / abs(expected)
        return delta <= self.max_relative_delta


@dataclass(frozen=True, slots=True)
class CombatState:
    hull: int
    shield: int

    def to_dict(self) -> dict[str, int]:
        return {"hull": self.hull, "shield": self.shield}


@dataclass(frozen=True, slots=True)
class DamageBreakdown:
    raw: int
    mitigated: int
    shield: int
    hull: int

    def to_dict(self) -> dict[str, int]:
        return {
            "raw": self.raw,
            "mitigated": self.mitigated,
            "shield": self.shield,
            "hull": self.hull,
        }


@dataclass(frozen=True, slots=True)
class RoundTrace:
    round_number: int
    acting_side: Side
    action: str
    attacker: CombatState
    defender_before: CombatState
    defender_after: CombatState
    damage: DamageBreakdown
    triggered_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_number,
            "acting_side": self.acting_side,
            "action": self.action,
            "attacker": self.attacker.to_dict(),
            "defender_before": self.defender_before.to_dict(),
            "defender_after": self.defender_after.to_dict(),
            "damage": self.damage.to_dict(),
            "triggered_effects": list(self.triggered_effects),
        }
```

Create `scripts/combat-model.py`:

```python
#!/usr/bin/env python3
"""PvE combat model viability tooling."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true", help="print tool name and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print("combat-model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_models.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py --version
```

Expected:

```text
OK
combat-model
```

- [ ] **Step 5: Commit**

```bash
git add scripts/combat-model.py scripts/lib/combat_model/__init__.py scripts/lib/combat_model/models.py tests/test_combat_model_models.py
git commit -m "feat: add combat model CLI skeleton"
```

---

### Task 2: Normalized Fixture Loader

**Files:**
- Create: `scripts/lib/combat_model/fixtures.py`
- Test: `tests/test_combat_model_fixtures.py`

- [ ] **Step 1: Write failing fixture-loader tests**

Create `tests/test_combat_model_fixtures.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.fixtures import FixtureError, load_fixture


class FixtureLoaderTests(unittest.TestCase):
    def test_loads_valid_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixture.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "game_version": "1.000.48902",
                        "source_payloads": [{"kind": "battle_config", "path": "static/BattleConfig.pb"}],
                        "initial_state": {
                            "player": {"hull": 10000, "shield": 5000},
                            "hostile": {"hull": 8000, "shield": 3000},
                        },
                        "rounds": [
                            {
                                "round": 1,
                                "acting_side": "player",
                                "action": "kinetic",
                                "raw_damage": 4000,
                                "mitigation": 0.125,
                                "expected": {"shield": 3000, "hull": 500},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fixture = load_fixture(path)

        self.assertEqual("1.000.48902", fixture["game_version"])
        self.assertEqual(1, fixture["rounds"][0]["round"])

    def test_rejects_missing_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

            with self.assertRaisesRegex(FixtureError, "missing required fixture key: game_version"):
                load_fixture(path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_fixtures.py
```

Expected: import failure for `scripts.lib.combat_model.fixtures`.

- [ ] **Step 3: Add fixture loader**

Create `scripts/lib/combat_model/fixtures.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FixtureError(ValueError):
    """Raised when a normalized combat fixture is incomplete or malformed."""


REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "game_version",
    "source_payloads",
    "initial_state",
    "rounds",
)


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"invalid fixture JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise FixtureError(f"fixture root must be an object: {path}")

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in data:
            raise FixtureError(f"missing required fixture key: {key}")

    if data["schema_version"] != 1:
        raise FixtureError(f"unsupported fixture schema_version: {data['schema_version']}")

    if not isinstance(data["source_payloads"], list) or not data["source_payloads"]:
        raise FixtureError("source_payloads must be a non-empty list")

    if not isinstance(data["rounds"], list) or not data["rounds"]:
        raise FixtureError("rounds must be a non-empty list")

    return data
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_fixtures.py
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/combat_model/fixtures.py tests/test_combat_model_fixtures.py
git commit -m "feat: add combat fixture loader"
```

---

### Task 3: Comparator And Report Rendering

**Files:**
- Create: `scripts/lib/combat_model/compare.py`
- Create: `scripts/lib/combat_model/reporting.py`
- Test: `tests/test_combat_model_compare.py`

- [ ] **Step 1: Write failing comparator/report tests**

Create `tests/test_combat_model_compare.py`:

```python
from __future__ import annotations

import unittest

from scripts.lib.combat_model.compare import compare_traces
from scripts.lib.combat_model.models import CombatState, DamageBreakdown, ReplayThreshold, RoundTrace
from scripts.lib.combat_model.reporting import render_markdown_report


def _trace(round_number: int, shield: int, hull: int, effects: list[str] | None = None) -> RoundTrace:
    return RoundTrace(
        round_number=round_number,
        acting_side="player",
        action="kinetic",
        attacker=CombatState(hull=10000, shield=5000),
        defender_before=CombatState(hull=8000, shield=3000),
        defender_after=CombatState(hull=8000 - hull, shield=max(0, 3000 - shield)),
        damage=DamageBreakdown(raw=shield + hull, mitigated=shield + hull, shield=shield, hull=hull),
        triggered_effects=effects or [],
    )


class ComparatorTests(unittest.TestCase):
    def test_passes_when_damage_and_triggers_match_threshold(self) -> None:
        result = compare_traces(
            expected=[_trace(1, shield=1000, hull=0, effects=["a"])],
            actual=[_trace(1, shield=1110, hull=0, effects=["a"])],
            threshold=ReplayThreshold.mvp(),
        )

        self.assertTrue(result.passed)
        self.assertEqual([], result.mismatches)

    def test_reports_damage_and_trigger_mismatch(self) -> None:
        result = compare_traces(
            expected=[_trace(1, shield=1000, hull=0, effects=["a"])],
            actual=[_trace(1, shield=1400, hull=0, effects=["b"])],
            threshold=ReplayThreshold.mvp(),
        )

        self.assertFalse(result.passed)
        self.assertEqual(["damage_delta", "trigger_mismatch"], [m.kind for m in result.mismatches])

    def test_renders_markdown_summary(self) -> None:
        result = compare_traces(
            expected=[_trace(1, shield=1000, hull=0)],
            actual=[_trace(1, shield=1400, hull=0)],
            threshold=ReplayThreshold.mvp(),
        )

        markdown = render_markdown_report("sample-fixture", result)

        self.assertIn("# Combat Replay Report: sample-fixture", markdown)
        self.assertIn("damage_delta", markdown)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_compare.py
```

Expected: import failure for `scripts.lib.combat_model.compare`.

- [ ] **Step 3: Add comparator and reporting modules**

Create `scripts/lib/combat_model/compare.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from .models import ReplayThreshold, RoundTrace


@dataclass(frozen=True, slots=True)
class ReplayMismatch:
    round_number: int
    kind: str
    message: str

    def to_dict(self) -> dict[str, int | str]:
        return {"round": self.round_number, "kind": self.kind, "message": self.message}


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    passed: bool
    mismatches: list[ReplayMismatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "mismatches": [m.to_dict() for m in self.mismatches]}


def compare_traces(
    *,
    expected: list[RoundTrace],
    actual: list[RoundTrace],
    threshold: ReplayThreshold,
) -> ReplayComparison:
    mismatches: list[ReplayMismatch] = []

    if len(expected) != len(actual):
        mismatches.append(
            ReplayMismatch(
                round_number=0,
                kind="round_count_mismatch",
                message=f"expected {len(expected)} rounds, got {len(actual)} rounds",
            )
        )

    for expected_round, actual_round in zip(expected, actual, strict=False):
        if expected_round.round_number != actual_round.round_number:
            mismatches.append(
                ReplayMismatch(
                    round_number=expected_round.round_number,
                    kind="ordering_mismatch",
                    message=f"expected round {expected_round.round_number}, got {actual_round.round_number}",
                )
            )
            continue

        expected_damage = expected_round.damage.shield + expected_round.damage.hull
        actual_damage = actual_round.damage.shield + actual_round.damage.hull
        if not threshold.damage_within_limit(expected=expected_damage, actual=actual_damage):
            mismatches.append(
                ReplayMismatch(
                    round_number=expected_round.round_number,
                    kind="damage_delta",
                    message=f"expected damage {expected_damage}, got {actual_damage}",
                )
            )

        if expected_round.triggered_effects != actual_round.triggered_effects:
            mismatches.append(
                ReplayMismatch(
                    round_number=expected_round.round_number,
                    kind="trigger_mismatch",
                    message=(
                        "expected triggers "
                        f"{expected_round.triggered_effects}, got {actual_round.triggered_effects}"
                    ),
                )
            )

    return ReplayComparison(passed=not mismatches, mismatches=mismatches)
```

Create `scripts/lib/combat_model/reporting.py`:

```python
from __future__ import annotations

import json

from .compare import ReplayComparison


def render_markdown_report(fixture_name: str, comparison: ReplayComparison) -> str:
    lines = [
        f"# Combat Replay Report: {fixture_name}",
        "",
        f"Passed: {'yes' if comparison.passed else 'no'}",
        "",
        "## Mismatches",
        "",
    ]
    if not comparison.mismatches:
        lines.append("No mismatches.")
    else:
        for mismatch in comparison.mismatches:
            lines.append(f"- Round {mismatch.round_number}: `{mismatch.kind}` - {mismatch.message}")
    lines.append("")
    return "\n".join(lines)


def render_json_report(comparison: ReplayComparison) -> str:
    return json.dumps(comparison.to_dict(), indent=2, sort_keys=True) + "\n"
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_compare.py
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/combat_model/compare.py scripts/lib/combat_model/reporting.py tests/test_combat_model_compare.py
git commit -m "feat: add combat replay comparator"
```

---

### Task 4: Deterministic Replay Engine And CLI Report Command

**Files:**
- Create: `scripts/lib/combat_model/replay.py`
- Modify: `scripts/combat-model.py`
- Test: `tests/test_combat_model_replay.py`

- [ ] **Step 1: Write failing replay tests**

Create `tests/test_combat_model_replay.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.fixtures import load_fixture
from scripts.lib.combat_model.replay import expected_trace_from_fixture, replay_fixture


class ReplayEngineTests(unittest.TestCase):
    def test_replays_damage_into_shield_then_hull(self) -> None:
        fixture = {
            "schema_version": 1,
            "game_version": "1.000.48902",
            "source_payloads": [{"kind": "battle_config", "path": "static/BattleConfig.pb"}],
            "initial_state": {
                "player": {"hull": 10000, "shield": 5000},
                "hostile": {"hull": 8000, "shield": 3000},
            },
            "rounds": [
                {
                    "round": 1,
                    "acting_side": "player",
                    "action": "kinetic",
                    "raw_damage": 4000,
                    "mitigation": 0.125,
                    "expected": {"shield": 3000, "hull": 500},
                }
            ],
        }

        traces = replay_fixture(fixture)

        self.assertEqual(3000, traces[0].damage.shield)
        self.assertEqual(500, traces[0].damage.hull)
        self.assertEqual(7500, traces[0].defender_after.hull)
        self.assertEqual(0, traces[0].defender_after.shield)

    def test_expected_trace_uses_battle_journal_values(self) -> None:
        fixture = {
            "schema_version": 1,
            "game_version": "1.000.48902",
            "source_payloads": [{"kind": "battle_journal", "path": "battles/123.json"}],
            "initial_state": {
                "player": {"hull": 10000, "shield": 5000},
                "hostile": {"hull": 8000, "shield": 3000},
            },
            "rounds": [
                {
                    "round": 1,
                    "acting_side": "player",
                    "action": "kinetic",
                    "raw_damage": 4000,
                    "mitigation": 0.125,
                    "expected": {"shield": 3000, "hull": 500},
                }
            ],
        }

        traces = expected_trace_from_fixture(fixture)

        self.assertEqual(3500, traces[0].damage.mitigated)
        self.assertEqual(["journal"], traces[0].triggered_effects)

    def test_cli_report_writes_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture_path = root / "fixture.json"
            fixture_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "game_version": "1.000.48902",
                        "source_payloads": [{"kind": "battle_journal", "path": "battles/123.json"}],
                        "initial_state": {
                            "player": {"hull": 10000, "shield": 5000},
                            "hostile": {"hull": 8000, "shield": 3000},
                        },
                        "rounds": [
                            {
                                "round": 1,
                                "acting_side": "player",
                                "action": "kinetic",
                                "raw_damage": 4000,
                                "mitigation": 0.125,
                                "expected": {"shield": 3000, "hull": 500},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            fixture = load_fixture(fixture_path)

        self.assertEqual("1.000.48902", fixture["game_version"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_replay.py
```

Expected: import failure for `scripts.lib.combat_model.replay`.

- [ ] **Step 3: Add replay engine**

Create `scripts/lib/combat_model/replay.py`:

```python
from __future__ import annotations

from typing import Any

from .models import CombatState, DamageBreakdown, RoundTrace


def _state(data: dict[str, Any]) -> CombatState:
    return CombatState(hull=int(data["hull"]), shield=int(data["shield"]))


def _apply_damage(defender: CombatState, mitigated_damage: int) -> tuple[CombatState, int, int]:
    shield_damage = min(defender.shield, mitigated_damage)
    hull_damage = max(0, mitigated_damage - shield_damage)
    return (
        CombatState(hull=max(0, defender.hull - hull_damage), shield=max(0, defender.shield - shield_damage)),
        shield_damage,
        hull_damage,
    )


def replay_fixture(fixture: dict[str, Any]) -> list[RoundTrace]:
    player = _state(fixture["initial_state"]["player"])
    hostile = _state(fixture["initial_state"]["hostile"])
    traces: list[RoundTrace] = []

    for round_data in fixture["rounds"]:
        acting_side = round_data["acting_side"]
        attacker = player if acting_side == "player" else hostile
        defender = hostile if acting_side == "player" else player
        mitigated = round(int(round_data["raw_damage"]) * (1.0 - float(round_data["mitigation"])))
        defender_after, shield_damage, hull_damage = _apply_damage(defender, mitigated)

        trace = RoundTrace(
            round_number=int(round_data["round"]),
            acting_side=acting_side,
            action=round_data["action"],
            attacker=attacker,
            defender_before=defender,
            defender_after=defender_after,
            damage=DamageBreakdown(
                raw=int(round_data["raw_damage"]),
                mitigated=mitigated,
                shield=shield_damage,
                hull=hull_damage,
            ),
            triggered_effects=list(round_data.get("triggered_effects", [])),
        )
        traces.append(trace)

        if acting_side == "player":
            hostile = defender_after
        else:
            player = defender_after

    return traces


def expected_trace_from_fixture(fixture: dict[str, Any]) -> list[RoundTrace]:
    player = _state(fixture["initial_state"]["player"])
    hostile = _state(fixture["initial_state"]["hostile"])
    traces: list[RoundTrace] = []

    for round_data in fixture["rounds"]:
        acting_side = round_data["acting_side"]
        attacker = player if acting_side == "player" else hostile
        defender = hostile if acting_side == "player" else player
        expected = round_data["expected"]
        mitigated = int(expected["shield"]) + int(expected["hull"])
        defender_after = CombatState(
            hull=max(0, defender.hull - int(expected["hull"])),
            shield=max(0, defender.shield - int(expected["shield"])),
        )
        traces.append(
            RoundTrace(
                round_number=int(round_data["round"]),
                acting_side=acting_side,
                action=round_data["action"],
                attacker=attacker,
                defender_before=defender,
                defender_after=defender_after,
                damage=DamageBreakdown(
                    raw=int(round_data["raw_damage"]),
                    mitigated=mitigated,
                    shield=int(expected["shield"]),
                    hull=int(expected["hull"]),
                ),
                triggered_effects=list(round_data.get("expected_triggered_effects", ["journal"])),
            )
        )
        if acting_side == "player":
            hostile = defender_after
        else:
            player = defender_after

    return traces
```

- [ ] **Step 4: Add CLI report command**

Replace `scripts/combat-model.py` with:

```python
#!/usr/bin/env python3
"""PvE combat model viability tooling."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.combat_model.compare import compare_traces
from lib.combat_model.fixtures import load_fixture
from lib.combat_model.models import ReplayThreshold
from lib.combat_model.replay import expected_trace_from_fixture, replay_fixture
from lib.combat_model.reporting import render_json_report, render_markdown_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser("report", help="replay one fixture and write reports")
    report.add_argument("fixture", type=Path)
    report.add_argument("--out-dir", type=Path, required=True)
    report.add_argument("--threshold", choices=("mvp", "release"), default="mvp")
    return parser


def _threshold(name: str) -> ReplayThreshold:
    return ReplayThreshold.release() if name == "release" else ReplayThreshold.mvp()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "report":
        fixture = load_fixture(args.fixture)
        expected = expected_trace_from_fixture(fixture)
        actual = replay_fixture(fixture)
        comparison = compare_traces(expected=expected, actual=actual, threshold=_threshold(args.threshold))
        args.out_dir.mkdir(parents=True, exist_ok=True)
        stem = args.fixture.stem
        (args.out_dir / f"{stem}.md").write_text(render_markdown_report(stem, comparison), encoding="utf-8")
        (args.out_dir / f"{stem}.json").write_text(render_json_report(comparison), encoding="utf-8")
        return 0 if comparison.passed else 2
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_replay.py tests/test_combat_model_models.py tests/test_combat_model_fixtures.py tests/test_combat_model_compare.py
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add scripts/combat-model.py scripts/lib/combat_model/replay.py tests/test_combat_model_replay.py
git commit -m "feat: add deterministic combat replay harness"
```

---

### Task 5: Capture Config Defaults

**Files:**
- Modify: `mods/src/config.h`
- Modify: `mods/src/config.cc`
- Modify: `mods/src/defaultconfig.h`
- Modify: `example_community_patch_settings.toml`
- Test: `tests/test_combat_model_capture_static.py`

- [ ] **Step 1: Write failing static tests for capture config**

Create `tests/test_combat_model_capture_static.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_H = PROJECT_ROOT / "mods" / "src" / "config.h"
CONFIG_CC = PROJECT_ROOT / "mods" / "src" / "config.cc"
DEFAULTCONFIG_H = PROJECT_ROOT / "mods" / "src" / "defaultconfig.h"
EXAMPLE_TOML = PROJECT_ROOT / "example_community_patch_settings.toml"
SYNC_CC = PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "sync.cc"


class CombatModelCaptureStaticTests(unittest.TestCase):
    def test_capture_config_defaults_disabled(self) -> None:
        config_h = CONFIG_H.read_text(encoding="utf-8-sig")
        config_cc = CONFIG_CC.read_text(encoding="utf-8-sig")
        defaults = DEFAULTCONFIG_H.read_text(encoding="utf-8-sig")
        example = EXAMPLE_TOML.read_text(encoding="utf-8-sig")

        self.assertIn("bool combat_model_capture_enabled;", config_h)
        self.assertIn("std::string combat_model_capture_dir;", config_h)
        self.assertIn("combat_model_capture_enabled", config_cc)
        self.assertIn('get_config_or_default(config, parsed, "combat_model", "capture_enabled"', config_cc)
        self.assertIn("constexpr bool        capture_enabled", defaults)
        self.assertIn("capture_enabled = false", example)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify config assertions fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_capture_static.py
```

Expected: failures for missing `combat_model_capture_enabled` and missing capture helper include.

- [ ] **Step 3: Add config fields**

In `mods/src/config.h`, add these fields after `sync_resolver_cache_ttl`:

```cpp
  bool        combat_model_capture_enabled;
  std::string combat_model_capture_dir;
```

In `mods/src/defaultconfig.h`, add this namespace after `namespace Sync`:

```cpp
namespace CombatModel
{
  constexpr bool        capture_enabled = false;
  constexpr const char* capture_dir     = "";
}
```

In `mods/src/config.cc`, add this alias near the existing default config aliases:

```cpp
namespace DCCM = DefaultConfig::CombatModel;
```

In `Config::Load()`, after sync settings are loaded, add:

```cpp
  this->combat_model_capture_enabled =
      get_config_or_default(config, parsed, "combat_model", "capture_enabled", DCCM::capture_enabled, write_config);
  this->combat_model_capture_dir =
      get_config_or_default<std::string>(config, parsed, "combat_model", "capture_dir", DCCM::capture_dir, write_log);
```

In `example_community_patch_settings.toml`, add this section after `[sync]` settings:

```toml
[combat_model]
# Disabled by default. Enable only while collecting controlled PvE combat model fixtures.
capture_enabled = false

# Optional absolute output directory. If empty, captures are written beside the mod config.
capture_dir = ""
```

- [ ] **Step 4: Run config test and verify it passes**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_capture_static.py
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add mods/src/config.h mods/src/config.cc mods/src/defaultconfig.h example_community_patch_settings.toml tests/test_combat_model_capture_static.py
git commit -m "feat: add combat model capture config"
```

---

### Task 6: Runtime Capture Helper

**Files:**
- Create: `mods/src/patches/parts/combat_model_capture.h`
- Create: `mods/src/patches/parts/combat_model_capture.cc`
- Modify: `tests/test_combat_model_capture_static.py`

- [ ] **Step 1: Extend static tests for capture helper behavior**

Add this test method to `tests/test_combat_model_capture_static.py`:

```python
    def test_capture_helper_names_required_static_groups(self) -> None:
        header = (PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "combat_model_capture.h").read_text(
            encoding="utf-8-sig"
        )
        source = (PROJECT_ROOT / "mods" / "src" / "patches" / "parts" / "combat_model_capture.cc").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn("CaptureEntityGroup", header)
        self.assertIn("CaptureBattleJournal", header)
        for group in (
            "BattleConfig",
            "ClientShipStatLookupSpecs",
            "MitigationCapsSpecs",
            "GlobalDamageReductionConfig",
            "HullSpecs",
            "ComponentSpecs",
            "OfficerSpecs",
            "OfficerAbilityBuffSpecs",
            "OfficerSynergyFactorSpecs",
            "BuffTargetSpecs",
            "BuffTriggerSpecs",
            "ActionSpecs",
            "ForbiddenTechSpecs",
        ):
            with self.subTest(group=group):
                self.assertIn(group, source)
```

- [ ] **Step 2: Run static tests and verify helper-file failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_capture_static.py
```

Expected: failure because `combat_model_capture.h` and `.cc` do not exist.

- [ ] **Step 3: Add capture helper header**

Create `mods/src/patches/parts/combat_model_capture.h`:

```cpp
#pragma once

#include <prime/EntityGroup.h>

#include <cstdint>
#include <string_view>

namespace nlohmann
{
class json;
}

namespace combat_model_capture
{
bool ShouldCaptureEntityGroup(EntityGroup::Type type);
void CaptureEntityGroup(EntityGroup::Type type, std::string_view bytes);
void CaptureBattleJournal(uint64_t journal_id, const nlohmann::json& battle_json);
} // namespace combat_model_capture
```

- [ ] **Step 4: Add capture helper implementation**

Create `mods/src/patches/parts/combat_model_capture.cc`:

```cpp
#include "combat_model_capture.h"

#include "config.h"
#include "file.h"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <unordered_set>

namespace combat_model_capture
{
namespace
{
std::mutex capture_mtx;
std::atomic_uint64_t capture_counter{0};
std::unordered_set<int> captured_static_groups;

std::string EntityGroupName(EntityGroup::Type type)
{
  switch (type) {
    case EntityGroup::Type::BattleConfig:
      return "BattleConfig";
    case EntityGroup::Type::ClientShipStatLookupSpecs:
      return "ClientShipStatLookupSpecs";
    case EntityGroup::Type::MitigationCapsSpecs:
      return "MitigationCapsSpecs";
    case EntityGroup::Type::GlobalDamageReductionConfig:
      return "GlobalDamageReductionConfig";
    case EntityGroup::Type::HullSpecs:
      return "HullSpecs";
    case EntityGroup::Type::ComponentSpecs:
      return "ComponentSpecs";
    case EntityGroup::Type::OfficerSpecs:
      return "OfficerSpecs";
    case EntityGroup::Type::OfficerAbilityBuffSpecs:
      return "OfficerAbilityBuffSpecs";
    case EntityGroup::Type::OfficerSynergyFactorSpecs:
      return "OfficerSynergyFactorSpecs";
    case EntityGroup::Type::BuffTargetSpecs:
      return "BuffTargetSpecs";
    case EntityGroup::Type::BuffTriggerSpecs:
      return "BuffTriggerSpecs";
    case EntityGroup::Type::ActionSpecs:
      return "ActionSpecs";
    case EntityGroup::Type::ForbiddenTechSpecs:
      return "ForbiddenTechSpecs";
    case EntityGroup::Type::ForbiddenTechBuffs:
      return "ForbiddenTechBuffs";
    case EntityGroup::Type::ActivatedAbilitySpecs:
      return "ActivatedAbilitySpecs";
    case EntityGroup::Type::ActivatedShipAbilitiesConfigs:
      return "ActivatedShipAbilitiesConfigs";
    default:
      return {};
  }
}

std::filesystem::path CaptureRoot()
{
  if (!Config::Get().combat_model_capture_dir.empty()) {
    return Config::Get().combat_model_capture_dir;
  }
  return std::filesystem::path(File::MakePath("combat_model_captures", true));
}

std::string NextStem(const std::string& prefix)
{
  const auto now = std::chrono::duration_cast<std::chrono::milliseconds>(
                       std::chrono::system_clock::now().time_since_epoch())
                       .count();
  return prefix + "-" + std::to_string(now) + "-" + std::to_string(capture_counter.fetch_add(1));
}

void AppendManifest(const nlohmann::json& entry)
{
  const auto manifest_path = CaptureRoot() / "manifest.jsonl";
  std::ofstream manifest(manifest_path, std::ios::app);
  manifest << entry.dump() << '\n';
}
} // namespace

bool ShouldCaptureEntityGroup(EntityGroup::Type type)
{
  return !EntityGroupName(type).empty();
}

void CaptureEntityGroup(EntityGroup::Type type, std::string_view bytes)
{
  if (!Config::Get().combat_model_capture_enabled || !ShouldCaptureEntityGroup(type)) {
    return;
  }

  std::scoped_lock lk(capture_mtx);
  const int group_code = static_cast<int>(type);
  if (captured_static_groups.contains(group_code)) {
    return;
  }
  captured_static_groups.insert(group_code);

  const auto group_name = EntityGroupName(type);
  const auto root       = CaptureRoot();
  const auto rel_path   = std::filesystem::path("static") / (NextStem(group_name) + ".pb");
  const auto abs_path   = root / rel_path;

  std::error_code ec;
  std::filesystem::create_directories(abs_path.parent_path(), ec);
  if (ec) {
    spdlog::error("combat model capture: failed to create {}: {}", abs_path.parent_path().string(), ec.message());
    return;
  }

  std::ofstream out(abs_path, std::ios::binary);
  out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  if (!out.good()) {
    spdlog::error("combat model capture: failed to write {}", abs_path.string());
    return;
  }

  AppendManifest({{"kind", "entity_group"},
                  {"entity_group", group_name},
                  {"entity_group_code", group_code},
                  {"path", rel_path.generic_string()},
                  {"bytes", bytes.size()}});
}

void CaptureBattleJournal(uint64_t journal_id, const nlohmann::json& battle_json)
{
  if (!Config::Get().combat_model_capture_enabled) {
    return;
  }

  std::scoped_lock lk(capture_mtx);
  const auto root     = CaptureRoot();
  const auto rel_path = std::filesystem::path("battles") / (std::to_string(journal_id) + ".json");
  const auto abs_path = root / rel_path;

  std::error_code ec;
  std::filesystem::create_directories(abs_path.parent_path(), ec);
  if (ec) {
    spdlog::error("combat model capture: failed to create {}: {}", abs_path.parent_path().string(), ec.message());
    return;
  }

  std::ofstream out(abs_path);
  out << battle_json.dump(2) << '\n';
  if (!out.good()) {
    spdlog::error("combat model capture: failed to write {}", abs_path.string());
    return;
  }

  AppendManifest({{"kind", "battle_journal"}, {"journal_id", journal_id}, {"path", rel_path.generic_string()}});
}
} // namespace combat_model_capture
```

- [ ] **Step 5: Run static tests and xmake build for helper**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_capture_static.py
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y && xmake -y mods
```

Expected: static tests pass and `mods` builds.

- [ ] **Step 6: Commit**

```bash
git add mods/src/patches/parts/combat_model_capture.h mods/src/patches/parts/combat_model_capture.cc tests/test_combat_model_capture_static.py
git commit -m "feat: add combat model capture helper"
```

---

### Task 7: Sync Capture Integration

**Files:**
- Modify: `mods/src/patches/parts/sync.cc`
- Test: `tests/test_combat_model_capture_static.py`

- [ ] **Step 1: Add failing sync integration test**

Add this test method to `tests/test_combat_model_capture_static.py`:

```python
    def test_sync_calls_capture_helper(self) -> None:
        sync_cc = SYNC_CC.read_text(encoding="utf-8-sig")

        self.assertIn('#include "combat_model_capture.h"', sync_cc)
        self.assertIn("combat_model_capture::CaptureEntityGroup", sync_cc)
        self.assertIn("combat_model_capture::CaptureBattleJournal", sync_cc)
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_capture_static.py
```

Expected: `test_sync_calls_capture_helper` fails because `sync.cc` does not include or call the helper yet.

- [ ] **Step 2: Include capture helper**

Add this include near the top of `mods/src/patches/parts/sync.cc`:

```cpp
#include "combat_model_capture.h"
```

- [ ] **Step 3: Capture relevant entity groups**

In `HandleEntityGroup`, after `bytesPtr` is computed and before `submit_async` is declared, add:

```cpp
  if (combat_model_capture::ShouldCaptureEntityGroup(entity_group->Type_)) {
    combat_model_capture::CaptureEntityGroup(entity_group->Type_, std::string_view(bytesPtr, byteCount));
  }
```

- [ ] **Step 4: Capture raw battle journals**

In `ship_combat_log_data`, after `battle_json = std::move(json::parse(battle_log));`, add:

```cpp
        combat_model_capture::CaptureBattleJournal(journal_id, battle_json);
```

- [ ] **Step 5: Run tests and build**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_capture_static.py
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y && xmake -y mods
```

Expected: static tests pass and `mods` builds.

- [ ] **Step 6: Commit**

```bash
git add mods/src/patches/parts/sync.cc tests/test_combat_model_capture_static.py
git commit -m "feat: capture combat model sync payloads"
```

---

### Task 8: Protobuf Capture Decoder Target

**Files:**
- Create: `tools/combat-model/xmake.lua`
- Create: `tools/combat-model/src/main.cc`
- Modify: `xmake.lua`

- [ ] **Step 1: Add XMake include**

In root `xmake.lua`, add this near the existing `includes("mods")` line:

```lua
includes("tools/combat-model")
```

- [ ] **Step 2: Add tool target**

Create `tools/combat-model/xmake.lua`:

```lua
target("combat-model-fixture")
do
    set_kind("binary")
    add_files("src/*.cc")
    add_packages("protobuf", "nlohmann_json")
    add_rules("protobuf.cpp")
    add_files("../../mods/src/prime/proto/*.proto")
    add_includedirs("../../mods/src", { public = true })
end
```

- [ ] **Step 3: Add decoder implementation**

Create `tools/combat-model/src/main.cc`:

```cpp
#include <Digit.PrimeServer.Models.pb.h>

#include <google/protobuf/message.h>
#include <google/protobuf/util/json_util.h>
#include <nlohmann/json.hpp>

#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <unordered_map>

namespace
{
using Factory = std::unique_ptr<google::protobuf::Message> (*)();

template <typename T> std::unique_ptr<google::protobuf::Message> MakeMessage()
{
  return std::make_unique<T>();
}

const std::unordered_map<std::string, Factory> kFactories{
    {"BattleConfig", MakeMessage<Digit::PrimeServer::Models::StaticSyncBattleConfResponse>},
    {"ClientShipStatLookupSpecs", MakeMessage<Digit::PrimeServer::Models::ClientShipStatLookupSpecsResponse>},
    {"MitigationCapsSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncMitigationCapsSpecResponse>},
    {"GlobalDamageReductionConfig", MakeMessage<Digit::PrimeServer::Models::StaticSyncGlobalDamageReductionConfigResponse>},
    {"HullSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncHullSpecsResponse>},
    {"ComponentSpecs", MakeMessage<Digit::PrimeServer::Models::ComponentSpecResponse>},
    {"OfficerSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncOfficerSpecsResponse>},
    {"OfficerAbilityBuffSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncOfficerAbilitySpecsResponse>},
    {"OfficerSynergyFactorSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncOfficerSynergyFactorSpecsResponse>},
    {"BuffTargetSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncBuffTargetSpecsResponse>},
    {"BuffTriggerSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncBuffTriggerSpecsResponse>},
    {"ActionSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncActionSpecResponse>},
    {"ForbiddenTechSpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncForbiddenTechSpecsResponse>},
    {"ForbiddenTechBuffs", MakeMessage<Digit::PrimeServer::Models::StaticSyncForbiddenTechBuffsSpecsResponse>},
    {"ActivatedAbilitySpecs", MakeMessage<Digit::PrimeServer::Models::StaticSyncActivatedAbilitySpecsResponse>},
    {"ActivatedShipAbilitiesConfigs", MakeMessage<Digit::PrimeServer::Models::StaticSyncActivatedShipAbilityConfigsResponse>},
};

std::string ReadFile(const std::filesystem::path& path)
{
  std::ifstream in(path, std::ios::binary);
  return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

void DecodeOne(const std::filesystem::path& capture_root, const nlohmann::json& manifest_entry,
               const std::filesystem::path& out_dir)
{
  const auto group = manifest_entry.at("entity_group").get<std::string>();
  const auto it    = kFactories.find(group);
  if (it == kFactories.end()) {
    throw std::runtime_error("unsupported entity group: " + group);
  }

  auto message = it->second();
  const auto bytes = ReadFile(capture_root / manifest_entry.at("path").get<std::string>());
  if (!message->ParseFromString(bytes)) {
    throw std::runtime_error("failed to parse entity group: " + group);
  }

  std::string json;
  google::protobuf::util::JsonPrintOptions options;
  options.add_whitespace = true;
  options.preserve_proto_field_names = true;
  const auto status = google::protobuf::util::MessageToJsonString(*message, &json, options);
  if (!status.ok()) {
    throw std::runtime_error("failed to convert entity group to JSON: " + group);
  }

  std::filesystem::create_directories(out_dir);
  std::ofstream out(out_dir / (group + ".json"));
  out << json << '\n';
}
} // namespace

int main(int argc, char** argv)
{
  if (argc != 3) {
    std::cerr << "usage: combat-model-fixture <capture-root> <out-dir>\n";
    return 2;
  }

  const std::filesystem::path capture_root = argv[1];
  const std::filesystem::path out_dir      = argv[2];
  std::ifstream               manifest(capture_root / "manifest.jsonl");
  if (!manifest.is_open()) {
    std::cerr << "missing manifest.jsonl under " << capture_root << "\n";
    return 2;
  }

  std::string line;
  while (std::getline(manifest, line)) {
    if (line.empty()) {
      continue;
    }
    const auto entry = nlohmann::json::parse(line);
    if (entry.value("kind", "") == "entity_group") {
      DecodeOne(capture_root, entry, out_dir);
    }
  }

  return 0;
}
```

- [ ] **Step 4: Build decoder target**

Run:

```bash
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y && xmake -y combat-model-fixture
```

Expected: `combat-model-fixture` builds. If a protobuf message name differs from the checked-in `.proto`, fix the factory mapping to the exact generated type name.

- [ ] **Step 5: Commit**

```bash
git add xmake.lua tools/combat-model/xmake.lua tools/combat-model/src/main.cc
git commit -m "feat: add combat model protobuf decoder"
```

---

### Task 9: Static Normalizer

**Files:**
- Create: `scripts/lib/combat_model/static_normalizer.py`
- Test: `tests/test_combat_model_static_normalizer.py`

- [ ] **Step 1: Write failing normalizer test**

Create `tests/test_combat_model_static_normalizer.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.lib.combat_model.static_normalizer import build_fixture


class StaticNormalizerTests(unittest.TestCase):
    def test_builds_minimal_fixture_from_decoded_static_and_battle_journal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoded = root / "decoded"
            decoded.mkdir()
            (decoded / "BattleConfig.json").write_text(
                json.dumps({"battleConfig": {"static": {"base_mitigation": 0.125}, "equations": {}}}),
                encoding="utf-8",
            )
            battle = root / "battle.json"
            battle.write_text(
                json.dumps(
                    {
                        "journal": {
                            "game_version": "1.000.48902",
                            "initial_state": {
                                "player": {"hull": 10000, "shield": 5000},
                                "hostile": {"hull": 8000, "shield": 3000},
                            },
                            "rounds": [
                                {
                                    "round": 1,
                                    "acting_side": "player",
                                    "action": "kinetic",
                                    "raw_damage": 4000,
                                    "expected": {"shield": 3000, "hull": 500},
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            fixture = build_fixture(decoded_static_dir=decoded, battle_journal_path=battle)

        self.assertEqual("1.000.48902", fixture["game_version"])
        self.assertEqual(0.125, fixture["rounds"][0]["mitigation"])
        self.assertEqual("decoded/BattleConfig.json", fixture["source_payloads"][0]["path"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_static_normalizer.py
```

Expected: import failure for `scripts.lib.combat_model.static_normalizer`.

- [ ] **Step 3: Add normalizer implementation**

Create `scripts/lib/combat_model/static_normalizer.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_fixture(*, decoded_static_dir: Path, battle_journal_path: Path) -> dict[str, Any]:
    battle_config_path = decoded_static_dir / "BattleConfig.json"
    battle_config = _read_json(battle_config_path)
    battle = _read_json(battle_journal_path)
    journal = battle["journal"]
    mitigation = float(battle_config["battleConfig"]["static"].get("base_mitigation", 0.0))

    rounds = []
    for round_data in journal["rounds"]:
        normalized = dict(round_data)
        normalized["mitigation"] = float(round_data.get("mitigation", mitigation))
        rounds.append(normalized)

    return {
        "schema_version": 1,
        "game_version": journal["game_version"],
        "source_payloads": [
            {"kind": "battle_config", "path": "decoded/BattleConfig.json"},
            {"kind": "battle_journal", "path": str(battle_journal_path)},
        ],
        "initial_state": journal["initial_state"],
        "rounds": rounds,
    }
```

- [ ] **Step 4: Run normalizer tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_static_normalizer.py
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/combat_model/static_normalizer.py tests/test_combat_model_static_normalizer.py
git commit -m "feat: add combat fixture normalizer"
```

---

### Task 10: Fixture Build CLI And Operator Notes

**Files:**
- Modify: `scripts/combat-model.py`
- Create: `docs/combat-model-viability.md`

- [ ] **Step 1: Add `build-fixture` CLI command**

Update `scripts/combat-model.py` by adding this import:

```python
from lib.combat_model.static_normalizer import build_fixture
```

Add this subcommand in `build_parser()` before `return parser`:

```python
    build_fixture_cmd = subparsers.add_parser("build-fixture", help="build normalized fixture JSON")
    build_fixture_cmd.add_argument("--decoded-static-dir", type=Path, required=True)
    build_fixture_cmd.add_argument("--battle-journal", type=Path, required=True)
    build_fixture_cmd.add_argument("--out", type=Path, required=True)
```

Add this branch before the final assertion in `main()`:

```python
    if args.command == "build-fixture":
        fixture = build_fixture(
            decoded_static_dir=args.decoded_static_dir,
            battle_journal_path=args.battle_journal,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
```

Add `import json` at the top of the file.

- [ ] **Step 2: Add operator notes**

Create `docs/combat-model-viability.md`:

```markdown
# Combat Model Viability Spike

This spike proves whether controlled PvE hostile fights can be replayed round by round from captured game data.

## Capture

Enable capture only while collecting controlled fixtures:

```toml
[combat_model]
capture_enabled = true
capture_dir = ""
```

When `capture_dir` is empty, captures are written beside the mod config under `combat_model_captures/`.

## Controlled First Dataset

- Use one player ship setup.
- Do not change crew, components, forbidden tech, or active buffs between runs.
- Fight the same hostile family and level repeatedly.
- Keep battle logs from the same game version as the static sync payloads.

## Decode Static Payloads

```bash
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y
xmake -y combat-model-fixture
./build/macosx/arm64/debug/combat-model-fixture <capture-root> <decoded-static-dir>
```

## Build A Fixture

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py build-fixture \
  --decoded-static-dir <decoded-static-dir> \
  --battle-journal <capture-root>/battles/<journal-id>.json \
  --out fixtures/pve/<journal-id>.json
```

## Replay And Report

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py report fixtures/pve/<journal-id>.json --out-dir reports/combat-model
```

MVP passes when controlled repeated PvE fixtures preserve mechanics ordering and trigger timing, and per-round damage lands within 10-20%.
```

- [ ] **Step 3: Run full Python suite and CLI smoke test**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_combat_model_models.py \
  tests/test_combat_model_fixtures.py \
  tests/test_combat_model_compare.py \
  tests/test_combat_model_replay.py \
  tests/test_combat_model_static_normalizer.py \
  tests/test_combat_model_capture_static.py
```

Expected: `OK`.

- [ ] **Step 4: Run C++ build checks**

Run:

```bash
git diff --check
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y && xmake -y mods && xmake -y combat-model-fixture
```

Expected: `git diff --check` has no output; xmake builds `mods` and `combat-model-fixture`.

- [ ] **Step 5: Commit**

```bash
git add scripts/combat-model.py docs/combat-model-viability.md
git commit -m "docs: document combat model viability workflow"
```

---

## Final Verification

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_combat_model_models.py \
  tests/test_combat_model_fixtures.py \
  tests/test_combat_model_compare.py \
  tests/test_combat_model_replay.py \
  tests/test_combat_model_static_normalizer.py \
  tests/test_combat_model_capture_static.py
git diff --check
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y && xmake -y mods && xmake -y combat-model-fixture
```

Expected:

- Python tests report `OK`.
- `git diff --check` prints nothing.
- XMake builds `mods` and `combat-model-fixture`.

## Implementation Notes

- Keep `combat_model.capture_enabled` disabled by default.
- Do not upload capture files through existing sync targets.
- Do not commit captured payloads, normalized player fixtures, or battle journals unless the user explicitly asks for sanitized samples.
- If protobuf message names differ from the planned decoder mapping, use the generated names from `mods/src/prime/proto/Digit.PrimeServer.Models.proto` and keep the manifest entity group names stable.
- If the first controlled fixtures fail the MVP threshold, preserve the report and classify the mismatch before changing formulas.
