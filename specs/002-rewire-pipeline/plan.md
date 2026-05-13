# Implementation Plan: Rewire Pipeline Stage 1 — Fetch Abstracts + GraphQL Schema

**Branch**: `002-rewire-pipeline` | **Date**: 2026-05-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-rewire-pipeline/spec.md`

## Summary

Replace the existing `ohbmcli ingest` invocation with a focused Stage 1
entry point that fetches the Oxford Abstracts corpus, persists the
upstream GraphQL schema introspection alongside it, classifies any
schema drift as HARD/SOFT/INFORMATIONAL (Principle VII applied to the
fetch boundary), supports dual-granularity checkpointing for resume
after interruption, and carries a machine-readable provenance record
(Principle VIII applied to the upstream of every organizer-facing
artifact). Tests precede implementation; the pattern this stage
establishes is documented so stages 2–14 can follow.

No new third-party dependencies. The existing `ohbm2026.graphql_api`
and `ohbm2026.assets` modules are extended (introspection helpers,
checkpointed batched fetch, atomic write), and two new modules are
added: `ohbm2026.fetch_stage` (the orchestrator + entry point) and
`ohbm2026.schema_diff` (the tiered diff classifier). A thin
`scripts/run_fetch_abstracts.py` wrapper documents the canonical
re-run command.

## Technical Context

**Language/Version**: Python 3.11
**Primary Dependencies**: stdlib only for the new behavior — `urllib`,
  `json`, `hashlib`, `dataclasses`, `argparse`, `pathlib`, `tempfile`,
  `os` (atomic rename). Existing module: `ohbm2026.artifacts` for the
  state-key derivation. No new third-party packages.
**Storage**: JSON files under the existing gitignored roots —
  corpus and schema artifacts under `data/inputs/`, resume checkpoint
  under `data/cache/fetch_abstracts/`.
**Testing**: existing `unittest` suite under `tests/`. The Stage 1
  test modules use the existing patching/mock patterns already in
  `tests/test_graphql_api.py` and `tests/test_assets.py`; no test
  framework migration is in scope.
**Target Platform**: macOS / Linux developer workstations and CI.
**Project Type**: single-project Python CLI + library. The new entry
  point is both an `ohbmcli` subcommand and a `scripts/` wrapper.
**Performance Goals**: NOT a target per Clarifications session
  2026-05-12 — quality of representation and reproducibility
  dominate. The new orchestrator MUST NOT regress total wall-clock
  time vs. the current `ohbmcli ingest` baseline by more than 25% on
  a clean run against the live endpoint (loose envelope, not a
  primary SC).
**Constraints**: dual-granularity resumability (FR-018); checkpoint
  self-validates against schema hash (FR-019); zero-byte-drift
  idempotency on unchanged upstream (FR-004); no downstream stage
  contract changes (FR-015); no committed data (Principle II);
  failures loud (Principle VI); fail-fast on hard-contract schema
  drift (FR-003 HARD tier).
**Scale/Scope**: 1.5k–3.5k accepted abstract submissions per OHBM
  cycle; ≤ several hundred MB of figure assets; one-time-per-cycle
  fetch with re-runs during corpus refresh. Schema introspection
  result is a single JSON document, typically tens of KB.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Python execution uses `.venv/bin/python` or `uv` targeting it; no
  system Python.** PASS — FR-011, CA-001. Both the `ohbmcli`
  subcommand and the `scripts/run_fetch_abstracts.py` wrapper run via
  the venv; docs show that form.
- **Verification named first; expected to fail or be missing before
  implementation.** PASS — Phase 1 lists `tests/test_fetch_stage.py`
  and `tests/test_schema_diff.py` (NEW) plus the augmented
  `test_graphql_api.py` / `test_assets.py`. Tests land before the new
  modules' implementation.
- **Output paths preserve auditability; canonical raw data not
  silently rewritten; recorded outputs go to fresh directories.**
  PASS — corpus snapshot path unchanged; new artifacts (schema,
  provenance) are sidecars; checkpoint is a separate file under
  `data/cache/fetch_abstracts/` keyed by state-key.
- **All generated artifacts (datasets, caches, exports, downloaded
  assets) land in gitignored roots; no new tracked artifact root.**
  PASS — `data/inputs/`, `data/cache/` already gitignored. FR-008
  enforces refusal to write outside.
- **Error handling is explicit and loud; no bare excepts, silent
  fallbacks, or verification-gate bypasses.** PASS — FR-007, CA-006.
  The constitution-check lint catches the patterns; new code is
  scoped to typed exceptions (`GraphQLAPIError`,
  `SchemaContractError`, `CheckpointError`).
- **External-state dependencies discovered at runtime; mismatches
  surface as precise errors, not silent skips.** PASS — this is the
  defining feature. Schema introspection IS the discovery mechanism;
  HARD-tier drift is the precise error.
- **Organizer-facing outputs ship machine-readable provenance with no
  absolute or user-home paths.** PASS — FR-005 names every required
  field; CA-008 forbids absolute/user-home paths in the provenance
  record. The corpus snapshot is upstream of every organizer-facing
  artifact in the project.
- **Secrets in `.env` or env vars only; named, not embedded.** PASS —
  `OHBM2026_API` only; provenance lists `env_vars_consulted` as
  names (Principle V, FR-005).
- **README/docs/plan updates included when defaults/commands/inputs/
  outputs change.** PASS — FR-013 and CA-003 require updating README
  Stage 1 / End-To-End Workflow section, CLAUDE.md, and
  `docs/reproducibility-vision.md`. New `docs/per-stage-pattern.md`
  added for the pattern doc.
- **Delivery commits each verified slice with descriptive message;
  pushed once requested change is complete.** PASS — the plan
  enumerates the slice boundaries (research → contracts → tests →
  schema diff → fetch orchestrator → docs); commits happen at slice
  completion.

**Result: no violations. No Complexity Tracking rows required.**

## Project Structure

### Documentation (this feature)

```text
specs/002-rewire-pipeline/
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0 output — design decisions resolved
├── data-model.md        # Phase 1 output — entity field-level schemas
├── quickstart.md        # Phase 1 output — operator how-to-run Stage 1
├── contracts/           # Phase 1 output
│   ├── cli.md
│   ├── abstracts_graphql_schema.schema.json
│   ├── abstracts_fetch_provenance.schema.json
│   └── abstracts_fetch_checkpoint.schema.json
├── spec.md              # /speckit.specify + /speckit.clarify output (already on disk)
├── checklists/
│   └── requirements.md  # spec quality checklist (already on disk)
└── tasks.md             # /speckit.tasks output — NOT created here
```

### Source Code (repository root)

```text
src/ohbm2026/
├── graphql_api.py          # extended: introspection helpers, exception types
├── assets.py               # extended: batched fetch yields per-batch checkpoint hook
├── artifacts.py            # extended: schema artifact + checkpoint path helpers
├── fetch_stage.py          # NEW — Stage 1 orchestrator: entry point,
│                           #   checkpoint lifecycle, provenance writer,
│                           #   schema-diff invocation, atomic writes
├── schema_diff.py          # NEW — tiered classification: HARD / SOFT /
│                           #   INFORMATIONAL. Pure functions; no I/O.
└── cli.py                  # `ohbmcli ingest` REMOVED; `ohbmcli fetch-abstracts` ADDED

scripts/
└── run_fetch_abstracts.py  # NEW — thin wrapper documenting the canonical
                            #   re-run command shown in the README

tests/
├── test_fetch_stage.py     # NEW — orchestrator: resume from each granularity,
│                           #   idempotency, provenance shape, atomic writes,
│                           #   gitignored-boundary refusal, six-contract coverage
├── test_schema_diff.py     # NEW — HARD/SOFT/INFORMATIONAL classifier, pure
├── test_graphql_api.py     # augmented: introspection request happy path,
│                           #   introspection retry under budget, schema-shape
│                           #   parser, typed-error surface for HARD drift
├── test_assets.py          # augmented: per-batch checkpoint hook contract,
│                           #   per-record completion marker transitions
└── test_cli.py             # augmented: `fetch-abstracts` subcommand wiring,
                            #   `ingest` removed assertion

docs/
└── per-stage-pattern.md    # NEW — the six contracts every stage script
                            #   satisfies, cited against fetch_stage.py
```

**Structure Decision**: single Python project under `src/ohbm2026/`,
tests under `tests/`, operator-facing wrappers under `scripts/`, and
spec/plan/research/etc. under `specs/002-rewire-pipeline/`. The
new modules (`fetch_stage.py`, `schema_diff.py`) are siblings of the
existing pipeline modules, matching the project's flat layout. No
new top-level directories are introduced.

## Complexity Tracking

> Constitution Check passes with no violations. No rows required.
