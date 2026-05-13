# Per-Stage Pattern

Every pipeline stage in this repo (Stage 1 fetch, Stage 2 enrich,
Stage 3+ analyses, …) satisfies the same six contracts. This doc
defines them and points at two canonical reference implementations
— **Stage 1 (`src/ohbm2026/fetch_stage.py`)** for a single-fetch
stage, and **Stage 2 (`src/ohbm2026/enrich_stage.py`)** for a
multi-component stage — for each.

A new stage author should be able to read this page plus
`fetch_stage.py` and write the next stage script in the same style.
Adding a new stage means writing a new orchestrator module that
satisfies these six contracts, not inventing new ones.

## The Six Contracts

### 1. Input contract

What env vars + prior-stage artifacts the stage reads, by name and
by path.

- **Env vars** are named only (never logged with values). The
  orchestrator collects the list and records it in the provenance
  record's `env_vars_consulted`.
- **Prior-stage artifacts** are read from their canonical paths
  under the gitignored data roots.

Stage 1 reference:
- `fetch_stage._load_api_key` reads `OHBM2026_API` (name only) from
  `.env` (default) or environment.
- `fetch_stage._build_parser` declares the CLI surface (env-file,
  env-var, batch-size, timeouts, allow flags, output overrides).

Stage 2 reference (multi-component):
- `enrich_stage._classify_backend_availability` discovers which of
  `OPENAI_API_KEY` / `OPENALEX_API` are present (names only) and
  returns a `BackendAvailability` dataclass that the orchestrator
  uses to refuse running components whose backend is unavailable.
- `enrich_stage._build_parser` declares the Stage 2 CLI surface
  (env-file, source corpus, per-component model identifiers,
  per-component failure thresholds, `--invalidate`, optional Parquet
  export).

### 2. Output contract

What artifacts the stage writes, at what paths, with what shape.

- Every output path is under the existing gitignored data roots
  (`data/primary/`, `data/inputs/`, `data/cache/`). The stage refuses
  to write outside the gitignored boundary even if explicitly
  directed to.
- The on-disk shape of canonical downstream-consumed artifacts is
  preserved across stage iterations; additive fields are OK,
  breaking changes need a separate spec.

Stage 1 reference:
- Corpus snapshot: `fetch_stage._write_corpus` →
  `data/primary/abstracts.json`.
- Schema artifact: `fetch_stage._write_schema_artifact` →
  `data/inputs/abstracts_graphql_schema__<state-key>.json`.
- Provenance: `fetch_stage._write_provenance` →
  `data/inputs/abstracts_fetch_provenance__<state-key>.json`.
- All three use `fetch_stage._atomic_write_json` (temp-file →
  `os.replace`) for crash safety.

Stage 2 reference:
- Enriched corpus: `enrich_storage.EnrichedCorpusWriter` →
  `data/primary/abstracts_enriched.sqlite` (SQLite + zlib(json) per
  row; atomic temp→rename via `os.replace`).
- Provenance: `enrich_stage._atomic_write_json` →
  `data/inputs/abstracts_enrich_provenance__<state-key>.json`.
- Per-component caches: `enrich_stage._write_cache_entry` →
  `data/cache/{figure_analysis,claim_analysis,reference_metadata}/<cache-key>.json`.
- Optional Parquet export: `--export-parquet PATH` lazy-imports
  `pyarrow` so the module's top-level imports stay stdlib-only.

### 3. Provenance contract

What the stage's provenance record contains, and how it is kept
portable.

- Required fields: `provenance_version`, `run_id`, `state_key`,
  `run_timestamp`, `code_revision`, `command_line`,
  `env_vars_consulted`, `endpoint_url` (where applicable),
  `query_count` / equivalent, `*_count` metrics, `*_path` pointers,
  `schema_hash`, `schema_diff_vs_previous` (where applicable),
  `checkpoint_path`, `resumed_from_previous_run`.
- All path fields are project-relative — no absolute paths, no
  `~`-prefix. Verified at write time; violations raise
  `ProvenanceError` (Principle VIII / CA-008).

Stage 1 reference:
- `fetch_stage._build_provenance_record` assembles the full record.
- `fetch_stage._assert_provenance_paths_safe` enforces the
  no-absolute / no-`~` rule.
- The exact field set is contract-tested against
  `specs/002-rewire-pipeline/contracts/abstracts_fetch_provenance.schema.json`.

Stage 2 reference:
- The record is assembled inline in `enrich_stage.main` (no separate
  builder helper) — required fields include `components` (one entry
  per `{figures, claims, references}`), `delta_vs_previous`, and
  `parquet_export_path` (null when the export flag was absent).
- `enrich_stage._assert_paths_safe` is invoked on every path candidate
  (output, parquet export, provenance) before any write.
- The exact field set is contract-tested against
  `specs/003-enrich-abstracts/contracts/enrich_provenance.schema.json`.

### 4. Error-handling contract

What failures the stage surfaces loudly, with what typed cause,
and at what exit code.

- Typed exception hierarchy in `ohbm2026.exceptions` rooted at a
  cross-stage `OhbmStageError(RuntimeError)`. Stage 1 subclass tree:
  `Stage1Error` → `SchemaContractError`, `CheckpointError`,
  `FigureFailureError`. Stage 2 subclass tree: `Stage2Error` →
  `EnrichmentError`, `CacheVersionError`,
  `ComponentFailureThresholdError`. `ProvenanceError` lives directly
  under `OhbmStageError` since both stages reuse it.
- No bare `except`. No silent fallbacks. No "log and continue"
  around operations whose failure would corrupt downstream
  artifacts.
- Exit codes are documented in the stage's CLI contract doc.

Stage 1 reference:
- `fetch_stage.main` catches each typed exception and maps it to
  a documented exit code (1 GraphQL, 2 HARD drift, 3 checkpoint,
  4 provenance, 5 figure failure rate, 6 empty corpus).
- Exit codes documented in
  `specs/002-rewire-pipeline/contracts/cli.md`.

Stage 2 reference:
- `enrich_stage.main` catches each typed exception and maps it to
  exit codes (1 generic EnrichmentError, 2 schema, 4 ProvenanceError
  path-boundary, 5 ComponentFailureThresholdError, 6 empty corpus,
  7 CacheVersionError). The enriched corpus is NOT written when a
  threshold breach is detected (Principle VI: never clobber the
  previous good corpus with a known-bad new one).
- Exit codes documented in
  `specs/003-enrich-abstracts/contracts/cli.md`.

### 5. Resumability contract

Whether the stage is fully resumable from checkpoint, idempotent on
full re-run, or both. If checkpointed: what the checkpoint shape is,
how it validates, and what guarantees the worst-case redo bound.

- Idempotency on full re-run: identical input state produces
  identical primary outputs (only provenance run-id / timestamp
  differ).
- Checkpointing (where applicable): a single JSON file under a
  gitignored cache root, written atomically; carries enough
  state to (a) decide whether to resume, (b) know how far the
  previous run got, and (c) explain that to a human.

Stage 1 reference:
- `fetch_stage._load_or_init_checkpoint`,
  `fetch_stage._new_checkpoint`, `fetch_stage._atomic_write_json`.
- Dual granularity: page-level cursor (`completed_submission_ids`)
  + per-record markers within the in-flight page. Worst-case redo
  on interruption is bounded to records still in flight.
- Checkpoint self-validates against the schema artifact's hash
  (`bound_schema_hash`); mismatch raises `CheckpointError` unless
  `--allow-schema-change` is set.
- Schema in `specs/002-rewire-pipeline/contracts/abstracts_fetch_checkpoint.schema.json`.

Stage 2 reference:
- Caches-as-checkpoint: there is no separate checkpoint file. Each
  per-component cache entry written by `_write_cache_entry` is
  atomic (temp + rename) and immediately visible to subsequent
  abstracts in the same run. An interrupted run leaves the populated
  cache entries on disk; the next invocation iterates the corpus
  again, but every populated entry short-circuits to a cache hit
  (research.md §8).
- The enriched SQLite is written only at the very end, as one
  atomic commit. An interruption before that final write leaves
  the previous good corpus (if any) intact.

### 6. Discovery contract

Which external state the stage discovers at runtime versus what it
treats as configuration.

- Upstream data shape (schema, available fields, available
  checkpoints, vendor enumerations) is discovered at runtime, never
  hardcoded as a separate file that can drift.
- Discovered state is persisted alongside the data so subsequent
  runs (or downstream stages) can diff against it (Principle VII).
- Mismatches surface as precise errors naming what was searched
  and what was found — never silent skips.

Stage 1 reference:
- `fetch_stage._run_introspection` fetches the live GraphQL
  schema; result persisted as the schema artifact.
- `schema_diff.flatten_introspection` + `compare` classify drift
  into HARD / SOFT / INFORMATIONAL.
- HARD set is derived from the live query body via
  `schema_diff.parse_hard_set_from_queries`. SOFT set is derived
  by importing consuming modules and unioning their
  `CONSUMED_ABSTRACT_FIELDS`. Neither set is a separately
  maintained allow-list.

Stage 2 reference:
- `enrich_stage._classify_backend_availability` discovers which
  enrichment backends are invocable (which API keys are present,
  which optional dependencies are installed). It returns a typed
  `BackendAvailability` dataclass rather than a free-form dict
  (CA-007).
- LLM-response schema discovery: each component runner (figures,
  claims, references) validates the model's response shape at parse
  time. Mismatches raise `EnrichmentError` with the offending
  response captured for post-hoc diagnosis (CA-007 / Principle VII).

## Adding a New Stage

When you write Stage N:

1. **Sketch the six contracts first.** Open a spec under
   `specs/<NNN>-<short-name>/spec.md` and name what each contract
   element will be: input env vars + prior-stage artifacts;
   output paths; provenance fields; error types; resume strategy;
   discovery surface.
2. **Author the test file first** (Principle IV). One test per
   contract element, organized into a class per contract.
3. **Implement the orchestrator** in
   `src/ohbm2026/<stage_name>.py`. Use Stage 1's `fetch_stage.py`
   as the layout reference. Share helpers via `artifacts.py`,
   `exceptions.py`, and `schema_diff.py` where possible.
4. **Add a CLI subcommand** in `cli.py` that delegates to your
   new `main(argv)`.
5. **Add a `scripts/run_<stage_name>.py` wrapper** for the README.
6. **Update the per-stage README section + this doc** so a future
   contributor can find your stage.

## Common Helpers

- `ohbm2026.artifacts.build_*_path(state_key)` — path derivation
  under gitignored roots.
- `ohbm2026.artifacts.build_dependency_basis` + `build_state_key` —
  deterministic state key from input fingerprint.
- `ohbm2026.exceptions.*` — typed exception hierarchy.
- `ohbm2026.schema_diff.*` — schema-diff / discovery primitives
  (reusable across stages that talk to GraphQL).
- The constitution lint at
  `.specify/scripts/bash/constitution-check.sh` catches the
  automatable subset of contract violations.
