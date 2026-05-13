# Data Model — Stage 1 Artifacts

Phase 1 of `/speckit-plan`. Field-level schemas for each new or
extended entity Stage 1 produces or maintains. The Corpus Snapshot
entity is referenced but its shape is unchanged from today's
`data/primary/abstracts.json` (FR-006); only the new and extended
artifacts are detailed below.

## Corpus Files

Stage 1 produces TWO distinct corpus files, each populated by a
distinct upstream filter and a distinct state-key namespace
(FR-022). They MUST NEVER mix:

| File | Filter | Driven by |
|---|---|---|
| `data/primary/abstracts.json` | `complete=true AND accepted_for.value IS NOT NULL` | `ohbmcli fetch-abstracts` |
| `data/primary/abstracts_withdrawn.json` | `complete=true AND decision_status="Withdrawn" AND archived=false` | `ohbmcli fetch-withdrawn` |

Both files share the same per-record schema (described below).

## Corpus Snapshot

`data/primary/abstracts.json` shape is preserved from the previous
ingest, with two new fields on every accepted-submission record
(empirically pinned 2026-05-13 via live introspection probe):

- **`poster_id`** (String) — populated from upstream
  `submissions.program_code` (FR-020). Confirmed live values:
  e.g. `"0581"`, `"0580"`, `"0743"`.
- **`program_sessions`** (list) — populated from upstream
  `submissions.program_sessions_submissions[]` flattened with each
  row's linked `program_session` data (FR-021). Each entry shape:

  ```json
  {
    "session_id":            <int>,             // program_session.id
    "session_name":          <string|null>,
    "session_type":          <string|null>,     // e.g., "Poster Standby"
    "session_track":         <string|null>,
    "session_date":          <date|null>,       // program_date.program_date
    "session_location":      <string|null>,     // program_location.name
    "session_start_time":    <time|null>,       // session-wide
    "session_end_time":      <time|null>,
    "standby_start_time":    <time|null>,       // per-poster window
    "standby_end_time":      <time|null>,
    "display_order":         <int|null>
  }
  ```

  Empty list `[]` is the legitimate value when upstream has not yet
  scheduled the abstract (the typical state pre-OHBM-scheduling).
  Stage 1 does NOT block on emptiness; the schema-diff machinery
  catches RENAMES and REMOVALS of requested fields per FR-021.

These two fields are HARD-contract: their absence from the upstream
schema is a SchemaContractError. Their VALUES being null/empty is
NOT a SchemaContractError — that's expected state today.

## State-Key Convention

Every Stage 1 artifact name embeds a 12-character hex `state_key`
derived from the run's input dependencies (see
`research.md` §6). The same input state always yields the same key;
any input-shape change yields a different key (forcing a fresh
artifact namespace).

| Artifact | Path |
|---|---|
| Corpus Snapshot | `data/primary/abstracts.json` (single canonical name; unchanged) |
| GraphQL Source Snapshot | `data/inputs/abstracts_graphql__<state-key>.json` (existing pattern) |
| GraphQL Schema Artifact | `data/inputs/abstracts_graphql_schema__<state-key>.json` (NEW) |
| Provenance Record | `data/inputs/abstracts_fetch_provenance__<state-key>.json` (NEW) |
| Resume Checkpoint | `data/cache/fetch_abstracts/checkpoint__<state-key>.json` (NEW) |

## 1. GraphQL Schema Artifact

The raw introspection response wrapped with minimal metadata for
downstream comparison.

**Fields**:

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `string` | yes | Internal version of THIS artifact's shape; starts at `"fetch.schema.v1"`. Bumped when this entity's contract changes. |
| `fetched_at` | `string` (ISO-8601 UTC) | yes | When the introspection request returned. |
| `endpoint_url` | `string` | yes | The GraphQL endpoint introspected. |
| `state_key` | `string` (12 hex chars) | yes | Matches the path's `<state-key>` segment. |
| `schema_hash` | `string` (64 hex chars) | yes | SHA-256 of the normalized flattened schema view (see `research.md` §5). Two runs against the same upstream schema produce the same `schema_hash`. |
| `introspection_raw` | `object` | yes | The unmodified `data.__schema` block returned by the introspection query. |
| `field_index` | `array<FieldIndexEntry>` | yes | Flattened normalized view used for diffing. See below. |

**FieldIndexEntry** (one per type+field):

| Field | Type | Description |
|---|---|---|
| `type_name` | `string` | The owning GraphQL type. |
| `field_name` | `string` | The field's name on that type. |
| `wrapping_kinds` | `array<string>` | Stack of `"NON_NULL"` / `"LIST"` from outer to inner. |
| `named_type` | `string` | The innermost named type (scalar, enum, object, etc.). |
| `args_signature` | `string` | Canonical, deterministic stringification of the field's args. |

**Validation rules**:

- `schema_hash` MUST be deterministic over `field_index` content (the
  flattened view, not the raw introspection response — JSON
  whitespace and ordering differences MUST NOT change the hash).
- `state_key` MUST match the path segment.
- `field_index` MUST be sorted by `(type_name, field_name)`.

## 2. Provenance Record

Sidecar to the Corpus Snapshot. Captures the answer to "how was this
corpus produced and is it still trustworthy?".

**Fields**:

| Field | Type | Required | Description |
|---|---|---|---|
| `provenance_version` | `string` | yes | Starts at `"fetch.provenance.v1"`. |
| `run_id` | `string` (UUID4) | yes | Unique per invocation, even across resumes of the same conceptual fetch. |
| `state_key` | `string` (12 hex) | yes | Matches the artifact namespace. |
| `run_timestamp` | `string` (ISO-8601 UTC) | yes | When this run started. |
| `code_revision` | `object` | yes | `{ "git_sha": <hex>, "dirty": <bool> }` — uses `git rev-parse HEAD` + `git status --porcelain` length. |
| `command_line` | `array<string>` | yes | `sys.argv` of this run, with secrets redacted (env vars never appear). |
| `env_vars_consulted` | `array<string>` | yes | Names of env vars Stage 1 read (currently `["OHBM2026_API"]`). Values NEVER recorded. |
| `endpoint_url` | `string` | yes | GraphQL endpoint URL. |
| `query_count` | `integer` | yes | Total GraphQL requests issued in this run (including retries). |
| `request_retry_count` | `integer` | yes | Subset of `query_count` that were retries. |
| `retry_reasons` | `object` | yes | `{ "<reason>": <count> }` — e.g. `{ "HTTP 503": 2 }`. |
| `total_response_bytes` | `integer` | yes | Sum of response body sizes. |
| `abstract_count` | `integer` | yes | Count of abstracts in the resulting corpus. |
| `figure_asset_count` | `integer` | yes | Count of figure assets downloaded or already cached locally. |
| `figure_failure_count` | `integer` | yes | Count of figure URLs that did NOT resolve to a local file. |
| `schema_artifact_path` | `string` (project-relative) | yes | Pointer to the paired GraphQL Schema Artifact. MUST NOT be absolute or `~`-prefixed. |
| `schema_hash` | `string` (64 hex) | yes | Copy of the schema artifact's hash for cross-validation. |
| `schema_diff_vs_previous` | `object \| null` | yes | `null` if no previous schema exists; otherwise see Schema Diff Summary below. |
| `checkpoint_path` | `string` (project-relative) \| `null` | yes | The checkpoint this run consumed/produced. `null` if the run completed end-to-end with no resume. |
| `resumed_from_previous_run` | `boolean` | yes | True if this run started from an existing checkpoint. |

**Validation rules**:

- Every path field MUST be project-relative — no `/`-prefix; no
  `~`-prefix; no `os.path.expanduser("~")` substring (CA-008).
- `run_id` MUST be unique across runs in the same artifact namespace
  (different runs of the same conceptual fetch each get their own).
- If `resumed_from_previous_run` is `True`, `checkpoint_path` MUST
  NOT be `null`.

## 3. Schema Diff Summary

Embedded in the Provenance Record under `schema_diff_vs_previous`.
Produced by `schema_diff.compare()`.

**Shape**:

```json
{
  "previous_schema_hash": "<64 hex>",
  "current_schema_hash": "<64 hex>",
  "entries": [SchemaDiffEntry, …]
}
```

**SchemaDiffEntry**:

| Field | Type | Description |
|---|---|---|
| `tier` | `enum("HARD","SOFT","INFORMATIONAL")` | Classification per FR-003. |
| `change_kind` | `enum("added","removed","type_changed","args_changed")` | What kind of delta. |
| `type_name` | `string` | The GraphQL type. |
| `field_name` | `string` | The field on that type. |
| `previous` | `object \| null` | The prior `FieldIndexEntry` (null if `added`). |
| `current` | `object \| null` | The new `FieldIndexEntry` (null if `removed`). |
| `downstream_consumers` | `array<string>` | For SOFT entries: list of module names that declared the field in `CONSUMED_ABSTRACT_FIELDS`. Empty for HARD/INFORMATIONAL. |

**Validation rules**:

- Every entry MUST appear in exactly one tier.
- HARD entries take precedence: if a field is BOTH in the fetch
  query body AND in the soft-contract set, it is HARD; the
  `downstream_consumers` list is still populated so the operator
  sees both signals (Edge Case in spec).

## 4. Resume Checkpoint

Single JSON file used to recover from interruption. Written
atomically (temp-file → `os.replace`).

**Fields**:

| Field | Type | Required | Description |
|---|---|---|---|
| `checkpoint_version` | `string` | yes | Starts at `"fetch.checkpoint.v1"`. |
| `state_key` | `string` (12 hex) | yes | Pairs the checkpoint to its corpus snapshot namespace. |
| `bound_schema_hash` | `string` (64 hex) | yes | The schema hash at the start of this fetch. FR-019: mismatched-on-resume MUST refuse to silently continue. |
| `started_at` | `string` (ISO-8601 UTC) | yes | When this checkpoint sequence began (first run, before any resume). |
| `last_updated_at` | `string` (ISO-8601 UTC) | yes | When this file was most recently rewritten. |
| `run_id` | `string` (UUID4) | yes | The run that wrote this snapshot of the checkpoint. Different from `started_at`'s originator. |
| `all_submission_ids` | `array<integer>` | yes | The full ordered ID list resolved at fetch start. The "cursor universe". |
| `batch_size` | `integer` | yes | Configured chunk size for content fetches. |
| `completed_submission_ids` | `array<integer>` | yes | IDs whose corpus row + figure-assets are fully resolved. |
| `in_flight_batch` | `object \| null` | yes | The batch currently being processed, or `null` between batches. |

**`in_flight_batch` shape** (when non-null):

| Field | Type | Description |
|---|---|---|
| `batch_index` | `integer` | 0-based index into the page sequence. |
| `submission_ids` | `array<integer>` | The IDs in this batch. |
| `per_record_state` | `object` | Map `{ "<submission_id>": <RecordState> }`. |

**RecordState** enum:

| Value | Meaning |
|---|---|
| `pending` | Not yet attempted in this batch. |
| `corpus_fetched` | Corpus row resolved; figures not yet attempted. |
| `figures_in_progress` | One or more figure downloads underway. |
| `done` | Corpus row + ALL figure attempts terminal. |
| `failed-retryable` | At least one figure download failed in a way that should be retried next run. |
| `failed-blocking` | Reached on hard-contract schema drift or unrecoverable upstream; surfaces an error and halts the run. |

**Validation rules** (enforced by `fetch_stage.load_checkpoint`):

- `bound_schema_hash` MUST match the most recently persisted Schema
  Artifact's `schema_hash`. Mismatch → refuse to resume silently
  (FR-019); requires explicit `--allow-schema-change` flag.
- `completed_submission_ids` ∩ `in_flight_batch.submission_ids` MUST
  be empty.
- The union of `completed_submission_ids`, `in_flight_batch.
  submission_ids`, and "pending future batches" MUST equal
  `all_submission_ids`.

## State Transitions

### RecordState

```
pending  ─┬─> corpus_fetched ─┬─> figures_in_progress ─┬─> done
          │                   │                         │
          │                   └─> done (no figures)     └─> failed-retryable
          │                                                  │
          └─> failed-blocking <──────────────────────────────┘ (only for hard-contract drift mid-batch)
```

A batch is "complete" when every record in
`per_record_state` is `done` (or all transitions to `failed-retryable`
have been resolved). On batch completion, the in-flight batch is
absorbed into `completed_submission_ids` and `in_flight_batch` is
reset to `null` before advancing to the next batch.

### Run lifecycle

```
[no checkpoint exists]
        │
        ▼
─ fetch ID list ─> bind schema_hash ─> create checkpoint
        │
        ▼
─ for each batch: fetch content ─> per-record figure resolution ─> mark done
        │
        ▼
─ all batches complete ─> write corpus + provenance ─> delete checkpoint
```

Interruption at any point preserves the latest checkpoint write
(atomic rename guarantees readers see either the pre- or post-update
state, never a torn write). The next run reads the checkpoint,
validates `bound_schema_hash`, and resumes from the first not-`done`
record in the in-flight batch (or from the next batch if no batch is
in flight).
