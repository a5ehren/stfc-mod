# PvE Combat Model Viability Spike Design

Date: 2026-05-01
Project: STFC Community Mod

## Purpose

Prove whether the repository can support a viable Star Trek Fleet Command PvE combat model before building a battle simulator, crew optimizer, or UI.

The spike answers one question: can controlled hostile fights be replayed round by round from captured game data closely enough to trust later optimization work?

## Feasibility Basis

The IL2CPP dump and protobuf schemas expose enough surface area to attempt the spike, but they are not sufficient by themselves.

- `dump/<version>/dump.cs` and `script.json` identify managed classes, methods, and protobuf-backed game types.
- `mods/src/prime/proto/*.proto` defines message shapes for static sync, battle config, ship stats, mitigation caps, hulls, components, officers, buffs, traits, research, forbidden tech, and related data.
- `mods/src/patches/parts/sync.cc` already captures player state, ship state, officers, buffs, slots, battle headers, and battle journal JSON through the existing sync path.
- Live static sync payloads are required because local dump/proto files describe schemas and APIs, not current game values.

## Scope

MVP scope:

- PvE hostiles only.
- Same player ship and setup for the first fixture batch.
- Repeated controlled fights against the same hostile family/level.
- Capture both raw live static sync payloads and raw PvE battle journal logs.
- Derive hostile stats from static data and compare them against battle-log-observed values.
- Simulate combat round order, damage, mitigation, shield/hull changes, and visible trigger effects.
- Pass when per-round damage is within 10-20% for controlled repeated fights and mechanics ordering/trigger timing match.

Final release target:

- Per-round damage within 5-10% for most rounds.
- Winner and final hull/shield state correct.

Out of scope for this spike:

- PvP.
- Crew optimization/search.
- Polished UI.
- Modeling every mechanic exactly when the available evidence shows missing data or unresolved random variance.

## Architecture

The spike uses an offline replay pipeline with a small capture extension in the existing mod.

### Capture Layer

Extend the existing sync/network capture path to persist raw payloads needed for combat modeling:

- Live static sync payloads for combat-relevant entity groups.
- Raw PvE battle journal JSON for controlled fights.
- Game version, capture timestamp, and source metadata for every payload.

Payloads must be versioned so data from one game update is not mixed with another.

### Fixture Builder

Convert raw captures into normalized fixtures:

- Player ship state.
- Equipped components.
- Officer state.
- Active buffs and research state.
- Hostile identity and derived hostile stats.
- Battle journal ground truth.

### Static Data Resolver

Decode captured protobuf payloads using generated protobuf types and resolve IDs into model-ready inputs:

- `BattleConfig` equations and static values.
- Ship stat lookup data.
- Mitigation caps.
- Global damage reduction config.
- Hull specs.
- Component specs.
- Officer specs and officer abilities.
- Officer synergy factors.
- Buff targets, triggers, and modifiers.
- Action specs.
- Forbidden tech, traits, and relevant research state.

### Round Replay Engine

Run deterministic combat rounds from normalized inputs.

The replay engine must not read dump, proto, or raw game files directly. It consumes normalized model inputs only. This keeps formulas testable and allows capture details to change later.

For each simulated step, emit a trace containing:

- Round number.
- Acting side.
- Selected action or weapon.
- Attacker and defender stat snapshot.
- Mitigation and damage reduction calculation.
- Shield damage.
- Hull damage.
- Triggered officer/buff/ability effects.
- Resulting shield/hull state.

### Comparator

Compare replay traces with battle journals round by round.

Reports must include:

- Damage deltas by round and phase.
- Ordering mismatches.
- Trigger mismatches.
- Unresolved IDs or missing inputs.
- Likely random variance buckets.
- Static derivation failures.

### Report Output

Produce both machine-readable and human-readable reports:

- JSON per fixture for automated checks.
- Markdown per fixture for manual review.
- Aggregate pass/fail summary against the MVP threshold.

## Data Flow

1. Discover schemas and surfaces from `dump/<version>/dump.cs`, `script.json`, and `mods/src/prime/proto/*.proto`.
2. Capture live static sync payloads and controlled PvE battle journals from the game.
3. Persist raw captures with game version and timestamp metadata.
4. Decode raw protobuf payloads into versioned normalized fixture JSON.
5. Resolve IDs and formulas into model inputs.
6. Replay combat rounds from the normalized initial state.
7. Compare simulated trace entries to battle journal entries.
8. Classify every mismatch as formula error, ordering/trigger error, missing captured data, static derivation error, likely random variance, or unknown.

## Error Handling And Validation

The spike should fail loudly when the evidence chain is incomplete.

Validation requirements:

- Every fixture declares all raw payloads it used.
- Required payloads missing for the game version are hard failures.
- Unresolved hull, component, officer, buff, action, hostile, or formula IDs are hard failures unless explicitly marked optional.
- Unknown protobuf fields are allowed, but missing expected fields are reported as schema drift.
- Replaying the same fixture must produce the same trace unless a random seed or variance bucket is explicitly modeled.
- Comparator output must identify the phase that diverged: stat derivation, action selection, mitigation, shield/hull application, officer/buff trigger, or unknown.

A failed replay can still be a successful spike result if it proves that required data is not available from dump/proto/static sync/battle logs. Reports must distinguish model bugs from missing evidence.

## Testing And Fixture Strategy

Initial fixture batch:

- One player ship setup, unchanged.
- One hostile family and level.
- Repeated fights to isolate randomness and base formulas.
- Raw static sync payloads captured from the same game version/session family as the battle logs.
- At least one fight with enough rounds to expose shield/hull transitions and weapon cadence.

Verification:

- Unit tests for normalized stat derivation from static payloads.
- Golden fixture tests for replay traces.
- Comparator tests for threshold logic and mismatch classification.
- CLI report command that runs all fixtures and writes Markdown/JSON summaries.
- Manual inspection of at least one generated report against the original battle journal before treating the spike as useful.

## Acceptance Criteria

The MVP spike is viable when:

- Controlled repeated PvE fixture batch replays with correct mechanics ordering and trigger timing.
- Per-round damage lands within 10-20% for the controlled fixture batch.
- Hostile stats can be derived from static data and checked against battle-log-observed values.
- Reports clearly classify all remaining mismatches.

The spike is not viable yet when:

- Required static values or battle journal fields cannot be captured.
- Hostile stat derivation cannot be grounded in available data.
- Mechanics ordering or trigger timing cannot be inferred from controlled logs.
- Per-round damage is outside the MVP threshold and mismatches cannot be reduced to known variance or missing evidence.

## Recommended Implementation Path

Use the replay harness first.

Hook-assisted instrumentation should be a fallback only when the replay harness exposes a hard blind spot, such as a hidden derived stat or trigger ordering value that cannot be inferred from static payloads and battle journals.

Do not begin crew optimization or UI work until this spike passes or produces a concrete missing-data blocker.
