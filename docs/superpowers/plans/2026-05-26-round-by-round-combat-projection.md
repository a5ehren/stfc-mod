# Round-by-Round Combat Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic round-by-round combat projection that uses the synced-linear mitigation model, emits per-attack state transitions, and validates those projections against captured observations.

**Architecture:** Keep projection in Python under `scripts/lib/combat_model/`. Load the fitted mitigation model from `reports/combat-model/mitigation-analysis.json`, reuse `damage_pipeline.predict_damage_from_stages()` for allocation, and add a `project-rounds` CLI that can run both observed-order validation and deterministic scheduler validation.

**Tech Stack:** Python 3 stdlib `argparse`/`dataclasses`/`json`/`pathlib`/`unittest`, existing combat-model observation JSONL, existing mitigation-analysis report JSON, and existing damage pipeline helpers.

**Spec:** `docs/superpowers/specs/2026-05-26-round-by-round-combat-projection-design.md`

---

## Scope Check

This plan implements one subsystem: offline round projection and validation reports. It does not add Monte Carlo sampling, target switching across multi-ship fleets, or production C++/mod integration.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/lib/combat_model/mitigation_model.py` | Create | Load `combat_triangle_synced_linear_formula` and predict mitigation from a row |
| `scripts/lib/combat_model/damage_pipeline.py` | Modify | Allow callers to supply projected pre-shot shield/hull state |
| `scripts/lib/combat_model/round_projection.py` | Create | Group observations, schedule weapons, project attacks, compare observed traces |
| `scripts/lib/combat_model/projection_reporting.py` | Create | Render projection JSON and Markdown reports |
| `scripts/combat-model.py` | Modify | Add `project-rounds` CLI |
| `tests/test_combat_model_round_projection.py` | Create | Unit and CLI coverage for mitigation loading, scheduling, projection, reporting |

---

### Task 1: Mitigation Model Loader

**Files:**
- Create: `scripts/lib/combat_model/mitigation_model.py`
- Test: `tests/test_combat_model_round_projection.py`

- [ ] **Step 1: Write failing tests**

Add tests that write a tiny mitigation-analysis report and assert prediction uses coefficients plus clamping:

```python
report = {
    "broad_formula_goal": {
        "candidate_metrics": {
            "combat_triangle_synced_linear_formula": {
                "model": {
                    "base_formula": "combat_triangle_static_player_max_buffs_formula",
                    "attacker_hull_labels": [],
                    "defender_hull_labels": [],
                    "coefficients": {"intercept": 0.2, "battle_type=2": 0.1},
                }
            }
        }
    }
}
model = load_synced_linear_mitigation_model(path)
self.assertAlmostEqual(0.3, model.predict({"battle_type": 2, "observed": {"remaining": {"shield": 10}}}))
```

- [ ] **Step 2: Implement loader**

Implement `SyncedLinearMitigationModel` with `load_synced_linear_mitigation_model(path)` and feature generation that mirrors `_synced_linear_features()` without fitting:

```python
model = load_synced_linear_mitigation_model(Path("reports/combat-model/mitigation-analysis.json"))
mitigation = model.predict(row)
```

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_round_projection.py
```

Expected: mitigation-model tests pass.

### Task 2: Projected State Damage Pipeline

**Files:**
- Modify: `scripts/lib/combat_model/damage_pipeline.py`
- Test: `tests/test_combat_model_round_projection.py`

- [ ] **Step 1: Write failing test**

Add a test proving projected state overrides observed state:

```python
result = predict_damage_from_stages(
    row,
    standard_raw_damage=100,
    standard_mitigation=0.0,
    pre_shot_state={"shield": 50, "hull": 1000},
)
self.assertEqual({"shield": 40, "hull": 60}, result["damage"])
self.assertEqual({"shield": 10, "hull": 940}, result["remaining"])
```

- [ ] **Step 2: Implement optional state**

Add a keyword-only `pre_shot_state: dict[str, Any] | None = None` parameter to `predict_damage_from_stages()`. Use `infer_pre_shot_state(row)` when it is absent and use the supplied state when present.

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_damage_pipeline.py tests/test_combat_model_round_projection.py
```

Expected: existing pipeline tests and new override test pass.

### Task 3: Deterministic Projector

**Files:**
- Create: `scripts/lib/combat_model/round_projection.py`
- Test: `tests/test_combat_model_round_projection.py`

- [ ] **Step 1: Write failing tests**

Add tests for warmup/cooldown scheduling and one-battle observed-order projection:

```python
schedule = build_projected_schedule(rows, max_rounds=3)
self.assertEqual(["w1", "w2", "w1", "w1", "w2"], [attack["weapon"]["id"] for attack in schedule])

report = project_observations(rows, mitigation_model=model, mode="observed-order")
self.assertEqual("observed-order", report["metadata"]["mode"])
self.assertEqual(2, report["summary"]["attack_count"])
self.assertLess(report["summary"]["damage_mae"], 100)
```

- [ ] **Step 2: Implement projector**

Implement:

```python
def load_observations_jsonl(path: Path) -> list[dict[str, Any]]
def group_observations_by_battle(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]
def build_projected_schedule(rows: list[dict[str, Any]], *, max_rounds: int, max_attacks: int) -> list[dict[str, Any]]
def project_observations(rows: list[dict[str, Any]], *, mitigation_model, mode: str, max_rounds: int, max_attacks: int) -> dict[str, Any]
```

Use `(minimum_damage + maximum_damage) / 2`, apply modifier `3` through `weapon_damage_diagnostics()`, call `mitigation_model.predict(row)`, and advance projected defender state through `predict_damage_from_stages(..., pre_shot_state=state)`.

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_round_projection.py
```

Expected: scheduling and projection tests pass.

### Task 4: Reports And CLI

**Files:**
- Create: `scripts/lib/combat_model/projection_reporting.py`
- Modify: `scripts/combat-model.py`
- Test: `tests/test_combat_model_round_projection.py`

- [ ] **Step 1: Write failing CLI test**

Add a subprocess test that runs:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py project-rounds \
  --observations observations.jsonl \
  --mitigation-analysis mitigation-analysis.json \
  --out projection.json \
  --mode observed-order
```

Assert `projection.json` and `projection.md` are created and contain aggregate metrics plus per-attack traces.

- [ ] **Step 2: Implement reporting and CLI**

Add `render_projection_json(report)` and `render_projection_markdown(report)`, then wire parser args:

```python
project_rounds.add_argument("--observations", type=Path, required=True)
project_rounds.add_argument("--mitigation-analysis", type=Path, required=True)
project_rounds.add_argument("--out", type=Path, required=True)
project_rounds.add_argument("--mode", choices=("observed-order", "deterministic"), default="observed-order")
project_rounds.add_argument("--battle-id", action="append")
project_rounds.add_argument("--battle-class", action="append")
project_rounds.add_argument("--limit", type=int)
project_rounds.add_argument("--max-rounds", type=int, default=30)
project_rounds.add_argument("--max-attacks", type=int, default=500)
```

- [ ] **Step 3: Verify**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests/test_combat_model_round_projection.py
```

Expected: CLI report test passes.

### Task 5: Full Verification

**Files:**
- All changed combat-model Python files

- [ ] **Step 1: Run focused Python tests**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_combat_model_damage_pipeline.py \
  tests/test_combat_model_round_projection.py \
  tests/test_combat_model_mitigation_analysis.py
```

Expected: all tests pass.

- [ ] **Step 2: Run combat-model regression set**

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_combat_model_models.py \
  tests/test_combat_model_fixtures.py \
  tests/test_combat_model_compare.py \
  tests/test_combat_model_replay.py \
  tests/test_combat_model_static_normalizer.py \
  tests/test_combat_model_capture_static.py \
  tests/test_combat_model_mitigation_analysis.py \
  tests/test_combat_model_mitigation_formula.py \
  tests/test_combat_model_observations.py \
  tests/test_combat_model_damage_pipeline.py \
  tests/test_combat_model_round_projection.py
```

Expected: all tests pass.

- [ ] **Step 3: Run repo gates**

```bash
git diff --check -- . ':(exclude)mods/src/patches/parts/embedded_loading_image.h'
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y
xmake -y combat-model-fixture
```

Expected: diff check and build gates pass.
