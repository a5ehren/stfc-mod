# Combat Model Viability Tooling

This tooling is for testing whether controlled PvE hostile fights can be replayed offline from captured game data. It is
not a crew optimizer and it does not change combat behavior in game.

The workflow is:

1. Enable capture in the mod config.
2. Run controlled PvE fights in game.
3. Decode captured static protobuf payloads.
4. Build normalized fixture JSON from static data plus one battle journal.
5. Replay the fixture and inspect the report.

## Prerequisites

- Build the mod on the same branch as this tooling.
- Use game captures and static payloads from the same game version.
- Keep the first dataset controlled: same ship, crew, components, forbidden tech, fleet commander, active buffs, hostile
  family, and hostile level.
- Do not commit raw captures, decoded player data, battle journals, or reports unless they are sanitized and intentionally
  added.

## Enable Capture

Capture is disabled by default. Enable it only while gathering controlled fixtures:

```toml
[combat_model]
capture_enabled = true
capture_dir = ""
```

If `capture_dir` is empty, the mod writes captures beside the mod config under `combat_model_captures/`. Set
`capture_dir` to an absolute path if you want the output somewhere else.

Captured data is local only. It is written to disk and is not uploaded through sync targets.

## Collect A Dataset

1. Start the game with capture enabled.
2. Let the game load far enough for static sync payloads to arrive.
3. Fight the controlled PvE hostile.
4. Open or trigger the combat log so the battle journal is fetched.
5. Close the game or disable capture after collecting enough samples.

The capture directory should contain:

```text
manifest.jsonl
static/*.pb
battles/<journal-id>.json
```

`manifest.jsonl` links each captured entity group to its raw protobuf file. `battles/<journal-id>.json` is the raw parsed
journal response from the game server.

## Build The Decoder

Build the C++ decoder target:

```bash
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y
xmake -y combat-model-fixture
```

The decoder loads repo proto descriptors at runtime. Run it from the repo root, or set `STFC_PROTO_ROOT` to the directory
containing `Digit.PrimeServer.Models.proto`.

## Decode Static Payloads

Decode the captured static payloads into JSON:

```bash
./build/macosx/arm64/debug/combat-model-fixture <capture-root> <decoded-static-dir>
```

Example:

```bash
./build/macosx/arm64/debug/combat-model-fixture \
  "$HOME/Library/Preferences/com.stfcmod.startrekpatch/combat_model_captures" \
  /tmp/stfc-combat-decoded
```

The decoded directory should include files such as `BattleConfig.json`, `HullSpecs.json`, `ComponentSpecs.json`,
`BaseShipTierSpecs.json`, `ShipTierSpecs.json`, `OfficerSpecs.json`, and `ActionSpecs.json`.

## Compare Static Catalog To Captures

To check whether decoded static hull/component specs can reconstruct captured hostile base state, run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py static-catalog \
  --decoded-static-dir <decoded-static-dir> \
  --capture-root <capture-root> \
  --out reports/combat-model/static-catalog-comparison.json
```

The command reads `HullSpecs.json` and `ComponentSpecs.json`, builds static ship entries from hull/component ids, then
compares them against captured `deployed_fleet` values. By default it compares the target/hostile side; pass
`--side initiator` or `--side both` when you want player-side checks too.

Use this report to separate catalog coverage from formula work. Exact or near-exact static matches mean base hull,
component, weapon, mitigation, and HP values can likely be sourced without fighting that hostile. Mismatches point to
runtime modifiers, missing static inputs, server overrides, or account-specific state.

## Export Attack Observations

To start formula work, export one JSONL row per battle-log damage attack:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py observations \
  --decoded-static-dir <decoded-static-dir> \
  --capture-root <capture-root> \
  --out reports/combat-model/observations.jsonl
```

After running `buff-audit`, pass the audit report back into observation export to attach resolved player live stats to
player attacker/defender rows:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py observations \
  --decoded-static-dir <decoded-static-dir> \
  --capture-root <capture-root> \
  --buff-audit reports/combat-model/buff-audit.json \
  --out reports/combat-model/observations.jsonl
```

Each row keeps model inputs separate from observed outputs:

- battle id, round, subround, attacker side, and defender side
- attacker and defender captured ship stats
- resolved player ship stats when `--buff-audit` is provided
- attacker and defender static hull/component/weapon data
- weapon spec for the fired weapon
- observed hit/crit flags, shield damage, hull damage, remaining state, mitigated damage, and effective mitigation

Use this file as the training/evaluation table for formula work. The model should consume the static/captured input
fields and predict the observed fields; it should not read observed mitigation or observed damage as inputs.

## Analyze Mitigation

After exporting observations, fit and report a first mitigation baseline:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py analyze-mitigation \
  --observations reports/combat-model/observations.jsonl \
  --out reports/combat-model/mitigation-analysis.json
```

The analyzer compares deterministic formula candidates, a global-mean baseline, and fitted ratio models using:

- defender dodge versus weapon accuracy
- defender armor plating versus weapon penetration
- defender shield absorption versus weapon modulation

The fitted model is an empirical baseline, not the final game formula. Use its grouped error summaries to decide where
the next formula work should focus.

`observed.effective_mitigation` is the raw battle-log mitigation ratio. `observed.normal_mitigation` subtracts observed
isolytic damage before computing mitigation, because isolytic has its own mitigation stat and must not be folded into the
normal mitigation target. Formula-model metrics in `analyze-mitigation` use `observed.normal_mitigation.effective_mitigation`.

`observed.isolytic_damage_model` separately records the isolytic damage track. It uses modifier code `707`
(`MODISOLYTICDAMAGE`) for the attacker multiplier and `808` (`MODISOLYTICDEFENSE`) for target mitigation. Current battle
journals do not include those codes in `deployed_fleet.ship_stats`, so the first pass derives the multiplier from the log:
`isolytic raw damage / observed.normal_mitigation.raw_damage`. A displayed 107% isolytic stat should therefore appear as a
`damage_multiplier` near `1.07`.

When `--buff-audit` is provided, observation export prefers resolved active `707` buff totals over the battle-log-derived
multiplier. This matters on overkill rows: observed normal damage can be capped by remaining target HP, while isolytic
damage is still calculated from the untruncated attack base. In that case `base_damage_gap` reports the missing base
damage implied by the resolved isolytic multiplier.

Rows with a positive `base_damage_gap` are excluded from normal-mitigation fitting because their observed normal base is
HP-capped. They remain in `damage_pipeline.observed_isolytic_damage_replay`, where the gap is reported separately.

`combat_triangle_formula` is the current explicit normal-mitigation candidate. It applies per-defender-hull weights to
the armor/plating versus armor-piercing, shield-deflection/absorption versus shield-piercing, and dodge versus accuracy
pairs, then combines them multiplicatively. The report also emits `combat_triangle_captured_live_formula` and
`combat_triangle_static_base_formula` so you can compare resolved-player live stats, captured-only live stats, and static
base stats.

`combat_triangle_linear_fit` and `attacker_side_combat_triangle_linear_fit` are diagnostic calibration models over the
explicit triangle prediction. They are not promoted formulas; they tell us whether the triangle components have roughly
the right shape but need side-specific scale/offset handling. `combat_triangle_residuals` groups the explicit triangle
error by attacker side, defender hull type, isolytic trigger state, and shield-active state.

Use `data_gaps` before drawing a formula conclusion. It cross-tabs attacker side against isolytic trigger state, defender
hull type, and shield-active state, and emits warnings when the current observations cannot separate two effects.

The report also includes `damage_pipeline.observed_mitigation_replay`, which holds observed effective mitigation fixed and
tests only post-mitigation damage application. This isolates the damage split from the mitigation formula. The current
first-pass rule applies `round(raw_damage * (1 - mitigation))`, sends `floor(damage * shield_mitigation)` to active
shields, and sends the remainder to hull.

`damage_pipeline.observed_isolytic_damage_replay` holds the derived isolytic multiplier and mitigation fixed, then checks
that isolytic damage replays independently from normal mitigation.

## Resolve Player Buffs

A useful combat model needs a live-stat layer before the formula layer. Hostile stats can usually be reconstructed from
static hull/component data, but player stats include account and loadout state that must be resolved separately.

The player buff resolver should map static ship inputs to the captured live `ship_stats` values before mitigation or
damage formulas run. Treat these as first-class inputs to that resolver:

- research and primes, including hull-type-specific research
- fleet commander selections, skills, and active fleet-wide bonuses
- forbidden tech, artifacts, buildings, exocomps, refits, ship abilities, and temporary event buffs
- captain, officer, below-deck, and synergy modifiers
- current ship tier, level, components, and equipped loadout

Until that resolver can reproduce captured player live stats, keep player and hostile mitigation fits separate. Otherwise
the formula regression will absorb account buffs into combat coefficients, which produces misleading global weights.

Use `live_stat_scaling`, `live_stat_scaling_by_hull`, and `live_stat_scaling_by_hull_type` in the mitigation report as
temporary evidence for the unresolved buff layer. Hull-level scaling is the most precise current fallback; hull-type
scaling becomes useful once captures include Battleship, Explorer, Interceptor, and Survey player ships under comparable
loadouts.

Run the player buff audit before trying to fit player-side combat formulas:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py buff-audit \
  --decoded-static-dir <decoded-static-dir> \
  --capture-root <capture-root> \
  --out reports/combat-model/buff-audit.json
```

The report indexes static `BuffSpec` sources, resolves deployed `active_buffs`, explains runtime-generated hull core-stat
buffs when possible, and compares component-derived static ship stats to captured live `ship_stats`. It also records the
component field used for each static stat, whether `BaseShipTierSpecs` and `ShipTierSpecs` were captured, and any selected
tier stat modifier present in those tables. Where `ClientShipStatLookupSpecs` has a matching hull type and ship level, the
live residual row also includes the lookup field/value as static level-scaling context. A missing source table in this
report means the capture run did not deliver that entity group; collect another dataset with the updated capture code
before treating that stat as formula work.

For resolved buffs, `source_context` links research buffs back to their research project/tree and officer ability buffs
back to the owning officer when `OfficerSpecs` has a matching ability id. Buff-only sources such as starbase, consumable,
ship bonus, ship level-up, and forbidden tech still include compact `buff_spec` metadata so `idRefs` and attributes stay
visible in residual summaries.

The live-stat resolver now uses zero-based active-buff rank selection and applies flat `BUFFOPERATION_ADD` values to the
base before percentage multipliers. Use `conditional_effects` to find stats where condition-coded buffs improve or worsen
the residual. Use `static_buff_subset_effects` to find rows where the best diagnostic subset of active static buffs
materially improves the residual; those rows are likely condition-gating or target-scope gaps, not missing buff IDs. Use
`related_modifier_effects` to see broad combat modifiers, such as all-piercing and all-defenses buffs, that are relevant
to a stat but are still kept out of the promoted math until their exact application rules are known. Use
`flat_application_effects`, `rank_selection_effects`, and `zero_based_base_additive_effects` as legacy comparisons against
the previous flat-after-percent and positive-rank-as-one-based interpretation.

## Build A Fixture

Build one normalized fixture from the decoded static data and one battle journal:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py build-fixture \
  --decoded-static-dir <decoded-static-dir> \
  --battle-journal <capture-root>/battles/<journal-id>.json \
  --out fixtures/pve/<journal-id>.json
```

The normalized fixture contains:

- `schema_version`
- `game_version`
- source payload references
- initial player and hostile state
- normalized combat rounds

The normalizer supports the spike fixture shape (`journal.initial_state` plus `journal.rounds`) and captured game
journals with a raw `journal.battle_log` marker stream. For raw journals, the first implementation builds each damage
entry from observed battle-log damage, shield/hull allocation, and effective mitigation. Treat a passing report from raw
fixtures as parser/replay plumbing evidence, not proof that the offline model has independently reproduced every combat
formula.

## Replay And Report

Replay a fixture and write Markdown plus JSON reports:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py report \
  fixtures/pve/<journal-id>.json \
  --out-dir reports/combat-model
```

Use the release threshold when you want the tighter 10% damage tolerance:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/combat-model.py report \
  fixtures/pve/<journal-id>.json \
  --out-dir reports/combat-model \
  --threshold release
```

Exit codes:

- `0`: comparison passed
- `2`: comparison ran and found mismatches
- other nonzero values: command or input failure

## Interpret Results

MVP viability means controlled repeated PvE fixtures preserve mechanics ordering and trigger timing, with per-round damage
inside the selected tolerance.

When a report fails, classify the mismatch before changing formulas:

- damage delta only
- shield versus hull allocation
- trigger timing
- missing or extra triggered effect
- round count or acting-side mismatch
- bad fixture normalization

Keep the failing fixture and report while investigating. The report is the evidence for deciding whether the offline model
needs a formula change, more static inputs, or more runtime instrumentation.

## Useful Checks

Run the Python coverage for this tooling:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests/test_combat_model_models.py \
  tests/test_combat_model_fixtures.py \
  tests/test_combat_model_compare.py \
  tests/test_combat_model_buff_audit.py \
  tests/test_combat_model_mitigation_analysis.py \
  tests/test_combat_model_observations.py \
  tests/test_combat_model_replay.py \
  tests/test_combat_model_static_catalog.py \
  tests/test_combat_model_static_normalizer.py \
  tests/test_combat_model_capture_static.py
```

Run the C++ checks:

```bash
git diff --check
xmake f -p macosx -a arm64 -m debug --target_minver=13.5 -y
xmake -y mods
xmake -y combat-model-fixture
```

## Cleanup

After capture, turn capture back off:

```toml
[combat_model]
capture_enabled = false
```

Leave `combat_model_captures/`, `fixtures/pve/`, and `reports/combat-model/` uncommitted unless you are intentionally
adding sanitized samples.
