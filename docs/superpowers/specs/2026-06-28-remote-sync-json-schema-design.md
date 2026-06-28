# Remote sync JSON Schema design

## Goal

Publish a machine-readable contract for JSON documents emitted by the mod to configured remote sync targets. The contract must support strict server-side validation and be easy for coding agents to discover and use.

## Scope

The schema covers outbound HTTP request bodies only. Each request body is a non-empty JSON array of records. It does not cover inbound game payloads, protobuf messages, HTTP headers, authentication, or response bodies.

## Contract shape

The schema will use JSON Schema Draft 2020-12. Its root will be a `oneOf` of homogeneous batch branches. Each branch will constrain every array item to one sync family and will identify records through a `type` constant. The supported record tags are:

- `battlelog`
- `buff`, `expired_buff`
- `module`
- `emerald_chain`
- `inventory`
- `job`, `completed_job`
- `mission`, `active_mission`
- `officer`
- `research`
- `resource`
- `ship`
- `slot`
- `ft`
- `trait`

Reusable definitions will describe each record shape and nested slot parameter variant. Mod-owned records will use `additionalProperties: false` so typoed or unsupported fields fail validation. Numeric identifiers, levels, counts, timestamps, and percentages will have appropriate integer/number constraints and descriptions.

The `battlelog` record will require `names` and `journal`, but `journal` will remain an open object because it is game-server data outside the mod's ownership and may evolve independently. Player-name entries will be described sufficiently for consumers while tolerating additional profile fields.

## Agent usability

The published schema will include a canonical `$id`, a human-readable `title` and `description`, `$comment` guidance for batch selection and lifecycle records, descriptions on definitions/properties, and representative examples. The file will be self-contained so an agent or validation library can load it without repository-specific code.

## Compatibility and testing

The schema will be checked against representative instances for every record family, including lifecycle/deletion records and every slot parameter variant. Invalid fixtures will verify that wrong type tags, missing required fields, extra mod-owned fields, mixed batch families, and empty batches are rejected. The schema itself will be validated with a standards-compliant Draft 2020-12 validator available in the repository environment.

