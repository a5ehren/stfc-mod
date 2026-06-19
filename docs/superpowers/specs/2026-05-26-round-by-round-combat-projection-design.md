# Round-by-Round Combat Projection Design

## Goal

Build a deterministic combat projection that starts from synced/static battle data and produces a round-by-round trace of
future combat state. The first implementation should use the completed `combat_triangle_synced_linear_formula` mitigation
model and the existing damage-stage pipeline, then compare projected traces against captured journals to quantify error.

Monte Carlo simulation remains a fallback path if deterministic hit, crit, or weapon-damage assumptions do not validate.

## Scope

The first projection engine covers one attacker and one defender at a time for the battle classes already validated by the
mitigation model: standard hostiles, armadas, and wave defense. It should support captured battle journals as validation
fixtures, but it should not require observed attack order or observed mitigation at prediction time.

In scope:

- Weapon scheduling from static weapon `warm_up` and `cooldown`.
- Deterministic weapon damage from static min/max damage, initially midpoint damage.
- Deterministic hit and crit handling, initially expected-value assumptions with explicit fields in the output.
- Normal mitigation from `combat_triangle_synced_linear_formula`.
- Existing standard, isolytic, apex, and shield-allocation stages.
- Round-by-round projected hull/shield state, per-attack damage stages, and final outcome.
- Validation reports against captured journals.

Out of scope for the first implementation:

- Target switching across multi-ship fleets.
- Learning hidden weapon-order rules beyond warmup/cooldown ordering.
- Monte Carlo sampling, except as a follow-up mode behind the same projection interface.
- Production C++/mod integration.

## Architecture

Add a projection module under `scripts/lib/combat_model/`, separate from `replay.py`.

Core units:

- `mitigation_model.py`: load the fitted synced-linear coefficients from `reports/combat-model/mitigation-analysis.json`
  and expose `predict_synced_linear_mitigation(row)`.
- `round_projection.py`: build projected attack schedules, apply deterministic raw damage assumptions, call the mitigation
  model, run damage stages, and advance projected state.
- `projection_reporting.py`: write JSON and Markdown validation reports.
- CLI command: `scripts/combat-model.py project-rounds`.

The existing `damage_pipeline.predict_damage_from_stages()` should remain the canonical state transition for damage
allocation. The projection engine should feed it predicted standard raw damage, predicted normal mitigation, predicted
isolytic stage inputs where available, and predicted apex mitigation where available.

## Inputs

The CLI should accept:

- `--observations`: exported observation JSONL, used both for synced/static ship/weapon fields and validation rows.
- `--mitigation-analysis`: report JSON containing `combat_triangle_synced_linear_formula`.
- `--out`: output report path or directory.
- Optional filters such as `--battle-id`, `--battle-class`, and `--limit`.

Projection rows should be grouped by `battle_id`. For validation runs, observed rows provide the initial ship state,
static ship/weapon specs, and expected observed trace. The projection must not read observed mitigation as a prediction
input.

## Scheduling

The deterministic scheduler should model warmup/cooldown from static weapon specs:

- A weapon is eligible when `battle_round >= warm_up` and its cooldown has elapsed.
- If multiple weapons are eligible, use stable static weapon order as the initial tie-breaker.
- Generate attacks until one side reaches zero projected hull or a configurable max round/attack limit is reached.

Captured journals should be used to compare the scheduled attack count and weapon sequence. If scheduler mismatch is high,
the report should separate scheduling error from damage-model error.

## Damage Assumptions

Start with conservative deterministic assumptions:

- Raw weapon damage uses `(minimum_damage + maximum_damage) / 2`, adjusted for effective shot count when modifier `3`
  is present.
- Hit chance is represented as expected damage unless a deterministic mode is explicitly selected later.
- Critical chance is represented as expected multiplier contribution unless a deterministic mode is explicitly selected
  later.
- Officer/forbidden-tech triggered damage stages are reported when observed validation rows contain them, but unmodeled
  trigger scheduling should be marked as an assumption gap.

The output must label each assumption so validation failures can be assigned to scheduling, RNG, raw-damage, mitigation,
or damage-stage causes.

## Output

JSON output should include:

- Projection metadata: model name, model source, assumptions, filters, and row counts.
- Per-battle summary: battle class, initial state, projected final state, observed final state when available, winner, and
  error metrics.
- Per-attack trace: projected round/sub-round, acting side, weapon id, raw damage, mitigation, stage outputs, shield/hull
  damage, state before/after, and observed comparison when available.
- Aggregate metrics: damage MAE, final shield/hull error, weapon-sequence mismatch, and survival/outcome match rate.

Markdown output should summarize the aggregate metrics and list the worst battle-level mismatches with links or identifiers
for the JSON detail.

## Validation

Validation should run on existing captured observations and report:

- Metrics by battle class: standard hostile, armada, wave defense.
- Metrics by battle id.
- Separate damage-state error from schedule mismatch.
- A strict mode that replays observed attack order but uses projected mitigation/damage stages, for isolating mitigation
  and damage pipeline quality.
- A full deterministic mode that uses projected scheduling, for measuring future-simulation quality.

The strict observed-order mode should be the first correctness gate. Full deterministic scheduling can be less accurate at
first, but its error must be measurable and reported.

## Monte Carlo Fallback

If deterministic assumptions fail validation because of RNG or damage ranges, add a `--mode monte-carlo` extension to the
same projection interface. Monte Carlo should sample weapon damage, hit, and crit outcomes while reusing the deterministic
mitigation and damage-stage code. Reports should expose median, percentile bands, and outcome probabilities.

## Tests

Add unit tests for:

- Mitigation model loading and prediction from report coefficients.
- Weapon warmup/cooldown scheduling.
- One-round deterministic projection state updates.
- Observed-order validation that uses projected mitigation instead of observed mitigation.
- CLI report generation and output schema.

Run the existing combat-model Python tests, `git diff --check`, and the macOS `combat-model-fixture` build gate after
implementation.
