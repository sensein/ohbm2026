# Feature Specification: Rewire The Pipeline Into Re-Runnable Stages — Stage 1 (Fetch Abstracts + GraphQL Schema)

**Feature Branch**: `002-rewire-pipeline`
**Created**: 2026-05-12
**Status**: Draft
**Input**: User description: "review and clean up sourcecode for this project. we are going to create scripts that can re-execute different stages of the flow. read the docs/readme to understand what was done. and we will cleanup one step at a time, starting with fetching the abstracts. but this time also save the graphql schema so we know the structures that exist in the database. we will also clean up and test the source code for both python library and the ui frontend (rewire using astro)"

## Clarifications

### Session 2026-05-12

- Q: Is backward compatibility with the existing `ohbmcli ingest`
  invocation required? → A: No. Clean break is preferred over a
  deprecation alias. The new Stage 1 entry point replaces `ingest`
  outright.
- Q: Is fetch-stage wall-clock speed a primary success criterion?
  → A: No. Quality of representation and reproducibility of every
  step dominate; time-to-fetch is explicitly NOT a target metric for
  this spec.
- Q: How strict is the recovery-from-interruption requirement?
  → A: Strict. A long-running fetch interrupted by network failure,
  rate limiting, or operator cancellation MUST be resumable from
  checkpoint on the next run. Re-fetching from scratch after an
  outage is unacceptable.
- Q: What overarching goal does this rewire serve?
  → A: A clean, reproducible representation of the OHBM 2026 abstract
  information space that supports semantically meaningful search and
  serves as the foundation for downstream experimentation. Stage 1's
  job is to make that representation's upstream input trustworthy and
  re-fetchable without rework.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Operator re-runs the abstract-fetch stage independently and gets a Schema-Verified snapshot (Priority: P1) — MVP

A project maintainer or contributor wants to refresh the Oxford Abstracts
corpus snapshot. They invoke a single, focused entry point for the
fetch-abstracts stage (no other stages run as side effects). The stage
fetches the accepted-abstracts corpus AND a full Oxford Abstracts GraphQL
schema introspection result, persists both to local artifacts under the
existing gitignored `data/inputs/` root, writes a machine-readable
provenance record alongside, and reports a short human-readable summary
(counts, timing, code revision, schema hash, change-vs-previous summary
if a prior snapshot exists). The script is idempotent: running it twice
against an unchanged upstream produces identical primary outputs (modulo
the timestamp in provenance).

**Why this priority**: this is the foundational stage. Every other stage
in the pipeline depends on the corpus snapshot it produces. Establishing
this stage as a focused, schema-verified, provenance-carrying script is
the unit pattern that every later stage will follow. Without P1 done,
later stages have no model to follow and the existing schema-drift risk
(NOCD-checkpoint-style silent breakage) remains.

**Independent Test**: Run the fetch-abstracts stage against the live
Oxford Abstracts endpoint with a valid token; verify it produces (a) the
normalized corpus snapshot, (b) a GraphQL schema introspection artifact,
(c) a provenance record. Re-run immediately and verify the primary
outputs are byte-identical (or content-identical with permitted
timestamp drift). Mutate the local schema artifact and re-run; verify
the script detects the drift and emits a precise error rather than
silently overwriting.

**Acceptance Scenarios**:

1. **Given** a clean local working tree with `OHBM2026_API` set,
   **When** the operator invokes the fetch-abstracts stage,
   **Then** the stage writes the normalized corpus to its canonical
   path, writes the GraphQL schema introspection result to a sibling
   path, writes a provenance record to a sibling path, and exits 0.
2. **Given** an existing corpus snapshot and schema artifact from a
   previous run, **When** the operator re-runs the fetch-abstracts
   stage against an unchanged upstream, **Then** the stage produces
   primary outputs that match the previous run on every user-visible
   field (timestamps and other provenance-only fields may differ).
3. **Given** an existing schema artifact, **When** the upstream Oxford
   Abstracts schema has changed in a way that affects fields the corpus
   pipeline actually uses, **Then** the stage emits a precise error
   naming the changed field(s) and exits non-zero, without overwriting
   the existing corpus snapshot.
4. **Given** the same starting state, **When** the upstream schema has
   changed only in fields the pipeline does NOT use, **Then** the stage
   completes successfully, writes the new schema artifact, and the
   provenance record explicitly lists the new/removed/changed fields so
   the maintainer can decide whether to start using them later.
5. **Given** any transient error during fetch (network, rate limit, 5xx)
   that the existing retry policy can recover from, **When** the
   recovery succeeds within budget, **Then** the script logs the retry
   with cause and continues; if the budget is exhausted, the script
   exits non-zero with the upstream error preserved (no silent
   fallback).
6. **Given** a successful run, **When** the operator inspects the
   on-disk artifacts, **Then** none of them lives under a tracked path;
   all three live under the gitignored `data/inputs/` root and no other
   directory.

---

### User Story 2 — The per-stage script pattern is documented and reusable (Priority: P1)

A maintainer or future contributor wants to understand how to add or
clean up a later pipeline stage. They open one short reference page
(README section or doc) that names the contract every stage script
satisfies: (1) input contract — exactly which prior-stage artifacts and
env vars the stage reads, by path and by name; (2) output contract —
exactly which artifacts the stage writes, by path; (3) provenance
contract — what fields the stage's provenance record contains; (4)
error-handling contract — what failures are surfaced loudly, and how
upstream/transient errors are distinguished from contract violations;
(5) resumability contract — whether the stage is fully resumable from
checkpoint, idempotent on full re-run, or both; (6) discovery contract
— which external state the stage discovers at runtime versus what it
treats as configuration.

**Why this priority**: P1 because Story 1's script is the first concrete
instance. Defining the pattern is part of "Story 1 done" — without it,
Story 1 is just a one-off script and the user's stated ambition ("we
will cleanup one step at a time") has nothing to clone.

**Independent Test**: Hand the doc + Story 1's stage script to someone
who has never seen the project. They MUST be able to: (a) explain in
plain English what the stage reads, writes, and promises; (b) point at
each of the six contract items in the script; (c) describe how they
would write a Stage-2 script that follows the same pattern.

**Acceptance Scenarios**:

1. **Given** the documented pattern, **When** a contributor reads it,
   **Then** they can locate each of the six contract elements in the
   Stage 1 script without ambiguity.
2. **Given** the pattern, **When** a contributor sketches a Stage 2
   script for a different pipeline step, **Then** their sketch
   satisfies all six contract elements without prompting.
3. **Given** the existing README's "End-To-End Workflow" section,
   **When** the rewire lands, **Then** the Stage 1 entry references the
   new script form (not just the legacy `ohbmcli ingest` invocation) and
   the new pattern doc is cross-linked.

---

### User Story 3 — The Python library modules involved in Stage 1 have first-class test coverage (Priority: P1)

A contributor changing Stage 1 code (or adjacent modules that read its
outputs) wants confidence that their change does not silently break
behavior. The modules touched by Stage 1 — currently
`src/ohbm2026/graphql_api.py`, `src/ohbm2026/assets.py`, and
`src/ohbm2026/artifacts.py` — have explicit unit tests that exercise:
the happy path against a mocked GraphQL endpoint; transient-error retry
behavior under a budget; schema-introspection persistence and
comparison; provenance shape; failure paths (auth, exhausted retries,
schema mismatch on used fields); and the no-data-committed invariant
(no test creates an artifact outside the gitignored roots).

**Why this priority**: P1 because the constitution's Principle IV
(plan-first, test-first) requires verification land with behavior change;
Story 1 IS a behavior change. P1 also because Stage 1's output is
upstream of every later stage — regressions here propagate everywhere.

**Independent Test**: Run the test suite via `.venv/bin/python -m
unittest discover -s tests -v`; the new Stage 1 tests pass and
collectively cover the six contract items from Story 2. Temporarily
introduce a deliberate bug into the schema-comparison logic; the test
suite catches it.

**Acceptance Scenarios**:

1. **Given** the Stage 1 implementation, **When** the test suite runs,
   **Then** all Stage 1 tests pass and exercise each acceptance
   scenario from Story 1 at least once.
2. **Given** a deliberate bug introduced in any of the six contract
   areas (input, output, provenance, error, resume, discovery),
   **When** the test suite runs, **Then** at least one test fails with
   a message that points at the violated contract.
3. **Given** the existing project test suite (≈250 tests, currently 1
   pre-existing unrelated failure), **When** Stage 1 tests are added,
   **Then** the rest of the suite remains green; the pre-existing
   unrelated failure is unaffected.

---

### Edge Cases

- The `OHBM2026_API` env var is missing → fail immediately with a
  named error, do not attempt the request, do not overwrite local
  artifacts.
- The upstream returns a response that is structurally valid but
  semantically empty (zero accepted abstracts) → fail with a precise
  error rather than silently writing an empty corpus snapshot that
  would later wipe downstream caches.
- The schema introspection response is too large to fit a single
  paginated response → the stage fetches and stitches paginated parts;
  resume on partial completion if interrupted.
- A previous run's provenance record is corrupt or unreadable → the
  stage treats the previous run as missing, not as a hard failure;
  proceeds with a fresh run and logs the recovery clearly.
- The upstream schema gains a brand-new top-level type unrelated to
  abstracts → recorded in provenance as informational; does not block
  the run, does not break downstream stages.
- A field the pipeline depends on is renamed upstream → fail loudly with
  the old name, new name, and a one-line "this is a Principle VII
  breakage, update the code" message. Never silently substitute.
- The operator runs the stage on a branch that has a different `data/`
  gitignore boundary → the stage refuses to write anywhere the index
  could pick up; honors the boundary, not assumes it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The fetch-abstracts stage MUST be invocable as a
  standalone, focused entry point — running it MUST NOT trigger any
  other pipeline stage as a side effect.
- **FR-002**: The fetch-abstracts stage MUST persist a full GraphQL
  schema introspection result for the Oxford Abstracts endpoint
  alongside the corpus snapshot on every successful run.
- **FR-003**: On every run, the fetch-abstracts stage MUST compare the
  freshly fetched schema against the most recent locally persisted
  schema (if any). Differences in fields the pipeline actually uses
  MUST surface as a precise blocking error; differences in fields the
  pipeline does not use MUST be recorded in provenance and MUST NOT
  block the run.
- **FR-004**: The fetch-abstracts stage MUST be idempotent on full
  re-run against unchanged upstream state: the primary corpus snapshot
  and the schema artifact MUST be content-identical between runs;
  only the provenance record's run-specific fields (timestamp, run id)
  may differ.
- **FR-005**: The fetch-abstracts stage MUST write a machine-readable
  provenance record alongside its primary outputs. The record MUST
  include: run timestamp (UTC, ISO-8601), code revision (git sha plus
  dirty/clean flag), command line that was invoked, env-var names
  consulted (NOT values), GraphQL endpoint URL, total query count,
  total response size, abstract count, retry count and reasons,
  schema hash, and a `schema_diff_vs_previous` summary if a previous
  schema is present.
- **FR-006**: The fetch-abstracts stage MUST preserve the on-disk
  shape of the existing normalized corpus snapshot
  (`data/primary/abstracts.json`) so that all downstream stages
  continue to work unchanged. Any change to that shape is OUT of
  scope for this spec.
- **FR-007**: The fetch-abstracts stage MUST surface every failure
  loudly with a typed cause: missing env var, auth failure, transient
  network error (retried), exhausted retries, schema-drift on used
  field, semantically empty corpus, partial fetch. Silent fallbacks,
  bare excepts, and "log and continue" handlers are PROHIBITED.
- **FR-008**: The fetch-abstracts stage MUST write all artifacts (the
  corpus snapshot, the schema introspection, the provenance record,
  any retry-state checkpoint) under the existing gitignored
  `data/inputs/` root. The stage MUST refuse to write outside the
  gitignored boundary even if explicitly directed to.
- **FR-009**: The per-stage pattern documented for future stages MUST
  define and name each of the six contract elements: input contract,
  output contract, provenance contract, error-handling contract,
  resumability contract, discovery contract.
- **FR-010**: The Stage 1 implementation MUST be the canonical
  reference instance of the pattern; the pattern doc MUST cite it by
  file and function name so contributors can read the spec and the
  code together.
- **FR-011**: Stage 1 entry points MUST run only through the
  repository-local `.venv/bin/python` (or `uv` targeting it). Any
  invocation example in docs MUST show that form, never bare
  `python`/`python3`.
- **FR-012**: Unit tests added in this spec MUST cover every
  acceptance scenario from User Story 1 at least once, and MUST
  collectively exercise each of the six contract elements at least
  once.
- **FR-013**: README "End-To-End Workflow" section's Stage 1 entry,
  CLAUDE.md's pipeline overview, and `docs/reproducibility-vision.md`
  Stage 1 mention MUST be updated in the same change to reflect the
  new entry point and the schema artifact's existence.
- **FR-014**: This feature replaces the existing `ohbmcli ingest`
  invocation with the new Stage 1 entry point. Backward compatibility
  with the old `ingest` form is NOT required — the old form is
  removed in the same change. (Decision recorded in Clarifications
  session 2026-05-12.)
- **FR-015**: This feature MUST NOT alter behavior in any stage
  downstream of fetch-abstracts. Figure analysis, enrichment,
  references, embeddings, clustering, and UI build all continue to
  read their existing inputs from existing paths.
- **FR-016**: Stage 1 MUST be resumable from checkpoint on
  interruption. When a fetch is interrupted (network failure, rate
  limit exhaustion, operator cancellation, schema-introspection
  partial completion), the next invocation MUST detect the
  checkpoint, validate it against the current upstream state, and
  continue from where the previous run stopped. Re-fetching already-
  retrieved records is permitted only when validation determines the
  partial checkpoint is no longer trustworthy.
- **FR-017**: The checkpoint Stage 1 writes MUST be readable by a
  human and by tests: it MUST be a single JSON file under the
  gitignored `data/inputs/` (or `data/cache/`) root, MUST be updated
  atomically (write-then-rename) as each unit of progress lands, and
  MUST contain enough information to (a) decide whether to resume,
  (b) know how far the previous run got, and (c) explain to a
  human what was completed and what is still pending.

### Key Entities

- **Corpus Snapshot**: The normalized accepted-abstract corpus produced
  by the fetch stage. Shape and path identical to today's
  `data/primary/abstracts.json` (plus a sibling GraphQL source under
  `data/inputs/abstracts_graphql__<state-key>.json`).
- **GraphQL Schema Artifact**: A JSON file capturing the upstream
  Oxford Abstracts GraphQL schema introspection result at fetch time.
  Lives alongside the GraphQL source under `data/inputs/` with a
  name that pairs it to the same `<state-key>`.
- **Provenance Record**: A JSON sidecar with the fields enumerated in
  FR-005; lives alongside the corpus snapshot.
- **Schema Diff Summary**: A structured diff between the current and
  previous schema artifacts (added/removed/changed types and fields),
  partitioned by "used by pipeline" vs "not used by pipeline".
  Embedded in the Provenance Record under `schema_diff_vs_previous`.
- **Per-Stage Pattern Doc**: A short reference page (README section or
  separate doc) that names the six contracts every stage script
  satisfies. Cites Stage 1 by file and function.

### Constitution Alignment *(mandatory)*

- **CA-001**: Every Python invocation introduced by this feature
  (stage entry point, tests, helper scripts) MUST run through
  `.venv/bin/python` or `uv` targeting that interpreter; no system
  Python.
- **CA-002**: Tests for each of the three user stories MUST be
  written and identified before implementation lands. User Story 1
  → unit + integration tests for the stage; User Story 2 → doc
  validation (can someone read the pattern and find the contract
  elements?); User Story 3 → the new test files exist, are listed
  in the spec, and initially fail.
- **CA-003**: README's Stage 1 / "End-To-End Workflow" section,
  CLAUDE.md's "Default pipeline state" + "Module Layout" + new
  pattern reference, and `docs/reproducibility-vision.md` Stage 1
  paragraph MUST be updated in the same change as the code.
- **CA-004**: Credentials are named only as env vars in spec and
  code: `OHBM2026_API` (required), no value embedded. The
  provenance record records `env_vars_consulted` as a list of names
  only.
- **CA-005**: The corpus snapshot, schema artifact, and provenance
  record all live under `data/inputs/` (already gitignored). No new
  artifact root is introduced; the spec confirms the gitignored
  boundary holds (Principle II).
- **CA-006**: All failure modes enumerated in FR-007 surface
  loudly with typed causes. The Stage 1 module MUST contain zero
  bare `except:`, zero `except Exception: pass`, and zero "log and
  continue" handlers around schema-drift-on-used-field, exhausted
  retries, or write-outside-gitignored-boundary. Verification: the
  repo's `constitution-check.sh --full` lint stays green; new
  module-specific tests assert that each failure path raises.
- **CA-007**: This feature IS Principle VII applied to the fetch
  stage. The persisted GraphQL schema, the field-level diff, and the
  "fail loudly on used-field drift" requirement are the explicit
  implementation of "discover external state, don't hardcode it".
  The implementation MUST NOT introduce any hardcoded "supported
  fields" allow-list except the list of fields the pipeline actually
  reads — and that list MUST be discoverable from the code (e.g. by
  introspecting the GraphQL query body), not from a separate file
  that can drift.
- **CA-008**: The provenance record IS the machine-readable
  provenance that Principle VIII requires for any artifact reaching
  organizers/downstream consumers. The corpus snapshot is upstream
  of every organizer-facing artifact in the project (UI exports,
  poster proposals, sequencing experiments), so its provenance
  record MUST satisfy the no-absolute-paths and no-user-home-paths
  rules and MUST survive moving the snapshot to another machine.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new contributor with the repo cloned and `.env`
  configured can run the fetch-abstracts stage end-to-end (produce
  corpus + schema + provenance) by following only the updated
  README's Stage 1 section, with no other documentation lookups
  required. Wall-clock time is NOT a target — quality of representation
  and reproducibility dominate. (Decision recorded in Clarifications
  session 2026-05-12.)
- **SC-008**: A Stage 1 fetch interrupted at any point during a run
  is resumable on the next invocation 100% of the time — measured
  by an automated test that interrupts the fetch at three distinct
  progress points (early, mid, late) and verifies that resume
  completes the corpus without re-fetching the already-retrieved
  records.
- **SC-002**: Two consecutive fetch-abstracts runs against unchanged
  upstream produce primary outputs (corpus snapshot, schema
  artifact) that match on 100% of user-visible fields; only
  provenance run-id and timestamp differ.
- **SC-003**: When a deliberate "used-field renamed upstream"
  scenario is simulated in tests, the stage detects and surfaces it
  with a precise error 100% of the time and writes 0 corrupted
  corpus snapshots.
- **SC-004**: 100% of acceptance scenarios listed under User Story
  1 are covered by at least one automated test.
- **SC-005**: The per-stage pattern doc lets an unfamiliar
  contributor identify all six contract elements in the Stage 1
  script in under 10 minutes, measured by a one-time walkthrough
  with someone who has not seen this work before.
- **SC-006**: The existing test suite (excluding the one
  pre-existing unrelated failure in
  `test_plot_poster_layout_floorplan`) remains 100% green after this
  feature lands; no test was skipped, xfail-ed, or deleted to make
  it so.
- **SC-007**: The `constitution-check.sh --full` lint stays green
  after this feature lands.

## Assumptions

These are informed defaults applied when the brief did not specify; any
of them can be overridden in `/speckit-clarify` or `/speckit-plan`.

- **Scope is Stage 1 only**: the cleanup of stages 2–14 (figure
  analysis, enrichment, references, embeddings, clustering, UI build,
  poster layout, sequencing) is OUT of this spec. Each subsequent
  stage will get its own `/speckit-specify` round and follow the
  pattern Stage 1 establishes.
- **Astro UI rewrite is OUT of scope for v1 of this spec**: the user
  named it as part of the broader ambition, but per "one step at a
  time, starting with fetching the abstracts" it is queued behind
  the Stage-1 cleanup. The Astro rewrite will be a separate
  `/speckit-specify` round at the UI-build stage.
- **GraphQL schema persistence form**: full introspection result
  (everything returned by `__schema` / `__type` queries), not just
  the subset the pipeline reads. This is what lets the project
  notice and reason about upstream changes the pipeline does not
  yet consume.
- **Schema-diff field-classification rule**: a field is "used by
  pipeline" if it is referenced by the live fetch query body in
  `graphql_api.py` (or any helper the fetch stage calls). The
  classification is derived from the code at run time, not a
  separate config file.
- **Entry-point form**: `ohbmcli ingest` is removed in this change
  (no backward-compatibility shim — see Clarifications session
  2026-05-12). The plan phase decides between (a) a new `ohbmcli`
  subcommand name and (b) a top-level `scripts/` wrapper as the
  canonical entry; the spec only constrains that whichever form is
  chosen, it is a single focused entry that runs Stage 1 and only
  Stage 1.
- **Test framework**: continue with the existing `unittest`-based
  suite under `tests/`; do not switch to pytest as part of this
  spec.
- **Schema artifact filename pattern**:
  `data/inputs/abstracts_graphql_schema__<state-key>.json`,
  matching the existing GraphQL source filename pattern.
- **State-key derivation**: same scheme already used by the project
  (the existing `state_key` helper in `artifacts.py`).
- **Figure-asset download remains in Stage 1 for v1**: the existing
  `ingest` command also downloads methods/results figures and links
  them into each abstract. Splitting figure download into a
  separate stage is a candidate cleanup but is deferred to a later
  `/speckit-specify` round.
- **Failure mode for "semantically empty corpus"**: defaults to
  refuse-and-exit-non-zero. If a future operator legitimately needs
  to record an empty-corpus state (e.g. for early-cycle testing),
  they can pass an explicit `--allow-empty` flag added during
  planning; the default remains refuse.

## Future Work (explicitly OUT of scope for this spec)

Listed here so they are not lost; each will be its own
`/speckit-specify` round.

- **Stage 2..N cleanups**: figure analysis (`analyze-figures`),
  enrichment (`enrich`, `title-audit`), claim extraction
  (`extract-claims`), reference matching (`reference-metadata`),
  embeddings (`embed-*`), stage-2 application
  (`apply-published-stage2`, `embed-stage2`), clustering
  (`semantic-analysis`, `cluster-benchmark`), projections
  (`umap-plot`, `compare-projections`, `optimize-projections`), UI
  build (`export-ui`, `build-ui`), poster layout
  (`scripts/optimize_poster_layout.py` and friends), poster
  sequencing (`scripts/benchmark_poster_sequencing.py` and
  friends).
- **Astro UI rewrite**: rewrite the static `ui/` frontend (vanilla
  JS + HTML + CSS) on Astro, preserving the existing UX and the
  current data contract.
- **Module-level cleanup of oversized files**: `enrichment.py`
  (~62 KB), `openalex.py` (~96 KB), `neuroscape.py` (~118 KB),
  `poster_layout.py` (~103 KB), `poster_sequencing.py` (~103 KB).
  These are clear cleanup candidates but their refactors land in
  the per-stage rounds that touch them, not in this Stage-1 spec.
- **Pytest migration**: candidate later improvement; not in v1.
- **Renaming `ohbmcli ingest` to `ohbmcli fetch-abstracts`**:
  candidate later improvement; backward-compatible alias decisions
  belong in a deprecation-cycle spec, not here.
