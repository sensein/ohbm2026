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
- Q: At what granularity does Stage 1 checkpoint progress so an
  interrupted fetch can resume? → A: Combined — a page-level cursor
  for the GraphQL query AND per-record completion markers within the
  in-flight page. Worst-case redo on interruption is bounded to the
  records still in flight when the interruption happened (not a full
  page, not the whole fetch).
- Q: How is "used by pipeline" defined for schema-drift classification
  — what blocks the fetch versus what is informational? → A: Tiered.
  Fields the GraphQL fetch query body requests are the **hard
  contract** — drift on these blocks Stage 1. Fields any downstream
  pipeline module reads from `data/primary/abstracts.json` are the
  **soft contract** — drift on these is recorded in the schema-diff
  summary with a "DOWNSTREAM IMPACT" tag, but Stage 1 still completes.
  Operators see both classes in one place; only the hard class halts
  the fetch.
- Q: Should Stage 1 also retrieve the upstream-assigned poster
  identifier for each accepted submission?
  → A: Yes. Stage 1 MUST include the poster id on every normalized
  corpus record. The exact upstream GraphQL field name is discovered
  from the introspection result at implementation time (Principle
  VII); if the upstream does not expose any field that represents a
  poster identifier, the stage fails loudly rather than fabricating
  one. (FR-020.)
- Q: A live count probe on 2026-05-13 returned 3244 accepted
  submissions; historical artifacts (`abstracts_enriched.json`
  Mar 13) reference 3333. The 89 missing IDs are all
  `decision_status: Withdrawn`. Should withdrawn submissions be
  captured? → A: Yes — but in a SEPARATE corpus. Stage 1 gains a
  dedicated withdrawn-corpus mode (`--corpus-kind=withdrawn`) using
  its own `WITHDRAWN_IDS_QUERY` and writing to
  `data/primary/abstracts_withdrawn.json`. Accepted and withdrawn
  corpora MUST NEVER mix in a single file or share a state-key
  namespace. (FR-022.)
- Q: Empirical schema probe (2026-05-13) — which upstream field IS
  the poster identifier, and where does poster standby time live?
  → A: Verified live against `https://app.oxfordabstracts.com/v1/graphql`.
  Findings:
  - The flat `poster_id` field name does NOT exist upstream. The
    upstream field that carries the conference-assigned poster
    number is **`submissions.program_code`** (String). FR-020 is
    pinned to `program_code` → normalized as `poster_id`.
  - Poster standby time + location live on the relationship table
    **`submissions.program_sessions_submissions[]`** with
    per-poster `start_time`/`end_time`/`display_order` plus a linked
    `program_session` that carries date, location, type, and track.
  - In the current upstream state (2026-05-13),
    `program_sessions_submissions` is EMPTY for sampled accepted
    abstracts — OHBM 2026 organizer scheduling has not yet been
    entered. Stage 1 still REQUESTS these fields so they land
    automatically once scheduling is populated; null values are
    expected and not an error today. (FR-021.)

### Session 2026-05-13

- Q: Stage 1 should also ingest author details. Which fields from
  the existing `AUTHOR_QUERY` go on disk in the canonical author
  record (email, orcid_id, etc. are returned upstream)? → A: Drop
  email entirely at fetch time. Keep `orcid_id` (public researcher
  identifier by design) and all non-PII fields (name parts, title,
  degree, presenting flag, affiliations). Email is a privacy
  liability and is not required by any planned downstream stage in
  v1; organizer workflows that need contact info can round-trip
  via Oxford Abstracts. (FR-023.)
- Q: Where does the canonical author file live? → A:
  `data/primary/authors.json` for accepted-corpus authors and
  `data/primary/authors_withdrawn.json` for withdrawn-corpus
  authors. Matches the pattern set by `abstracts.json` /
  `abstracts_withdrawn.json` (FR-022) — normalized datasets in
  `data/primary/`, separate files per corpus, never mixed. The
  legacy `data/inputs/authors.json` location used by the standalone
  `ohbmcli authors` subcommand is deprecated.
- Q: What happens to the existing `ohbmcli authors` subcommand
  once Stage 1 ingests authors inline? → A: Removed in this
  change. Clean break, no backward-compat alias — parallel to
  FR-014's removal of `ohbmcli ingest`. Any operator who needs to
  refresh authors invokes `ohbmcli fetch-abstracts` (or
  `fetch-withdrawn`); Stage 1's resumability handles the common
  case where abstracts are already fetched. (FR-024.)
- Q: Should figure assets move from `data/inputs/assets/` to
  `data/primary/assets/`? → A: Yes. Figure assets are normalized
  downstream artifacts (locally-resolved binaries derived from
  upstream URLs), not raw input snapshots. Moving them to
  `data/primary/` matches the pattern set by `abstracts.json`,
  `authors.json`, etc. The existing on-disk files migrate via
  `mv data/inputs/assets data/primary/assets` (gitignored on both
  sides — no commit impact). FR-008 enumerates the new path.

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

- A field that is BOTH in the GraphQL query body AND consumed
  downstream changes upstream → classified as HARD (drift blocks
  Stage 1); the downstream-impact tag is still recorded alongside
  the block so the operator knows which downstream module also
  needs updating once they fix the fetch query.
- A field is in the soft-contract set but the upstream schema
  has dropped it → SOFT-tier entry with `DOWNSTREAM IMPACT`, Stage
  1 completes but the abstracts.json column will be null for that
  field going forward. The consuming module's next run is the
  operator's problem to plan, not Stage 1's problem to block.
- A new field is added upstream that no part of the pipeline reads
  → INFORMATIONAL entry in the schema-diff summary; no action
  required by Stage 1.
- Upstream Oxford Abstracts does NOT expose a poster-identifier field
  → Stage 1 fails loudly with a `SchemaContractError` naming the
  type(s) and pattern of field names searched; does NOT fabricate a
  placeholder; does NOT silently omit the field. The operator's
  options are to (a) wait for upstream to expose the field, or
  (b) downgrade FR-020 in a follow-up spec. (Empirically resolved
  as of 2026-05-13: the field IS `submissions.program_code` —
  this edge case applies only if upstream removes or renames
  `program_code` in the future.)
- An accepted submission has zero rows in `program_sessions_submissions`
  (typical state before OHBM organizer scheduling is entered upstream)
  → Stage 1 normalizes the record with `program_sessions: []`. No
  error, no warning — this is the legitimate pre-scheduling state.
  FR-021 only treats RENAMING or removing requested fields as
  drift; null values on populated rows are tolerated.
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
  schema (if any). The comparison MUST partition every field-level
  difference into one of three tiers:
  - **HARD CONTRACT** — fields the GraphQL fetch query body
    requests. Any drift here (removed type, removed field, renamed
    field, type change on a used field, required-vs-optional flip
    on a used field) MUST surface as a precise blocking error
    naming the affected field, the old shape, and the new shape;
    Stage 1 MUST exit non-zero without overwriting the existing
    corpus snapshot.
  - **SOFT CONTRACT** — fields any `src/ohbm2026/` module reads
    from `data/primary/abstracts.json` (and that the fetch query
    populates into the normalized corpus). Drift here MUST be
    recorded in the schema-diff summary with a `DOWNSTREAM IMPACT`
    tag naming the consuming module(s) and field; Stage 1 MUST
    complete (no block), and the operator's next step is to update
    the consuming module in a separate spec.
  - **INFORMATIONAL** — all other schema changes. Recorded in the
    diff summary for visibility; no impact on Stage 1.
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
- **FR-008**: The fetch-abstracts stage MUST write all artifacts
  under the existing gitignored data roots: the corpus snapshot,
  the author roster (FR-023), and figure assets under
  `data/primary/` (`abstracts.json` / `abstracts_withdrawn.json`,
  `authors.json` / `authors_withdrawn.json`, `assets/`); the
  GraphQL source snapshot, the GraphQL schema artifact, and the
  provenance record under `data/inputs/`; the resume checkpoint
  under `data/cache/fetch_abstracts/`. The stage MUST refuse to
  write outside the gitignored boundary even if explicitly
  directed to.
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
- **FR-018**: The checkpoint MUST track progress at TWO granularities
  simultaneously: (1) **page-level** — the last successfully
  completed GraphQL page cursor, so resume can skip every fully
  retrieved page with no GraphQL traffic; (2) **per-record within
  the in-flight page** — completion markers for each abstract
  inside the page that was being processed when the interruption
  happened, so resume re-fetches only the records that were not yet
  fully resolved (corpus row plus any linked figure assets). The
  worst-case redo on interruption is bounded to the records in
  flight, NOT a full page and NOT the whole fetch.
- **FR-019**: The checkpoint MUST be self-validating against the
  persisted GraphQL schema artifact. If the schema artifact's hash
  in the checkpoint does not match the most recent locally persisted
  schema, the checkpoint MUST be treated as untrustworthy and the
  next run MUST refuse to resume silently — it surfaces the
  mismatch and requires explicit operator intent (e.g. an explicit
  flag) before proceeding. This prevents resuming a fetch across a
  schema change that may have altered the fields being collected.
- **FR-020**: Stage 1 MUST retrieve the upstream-assigned poster
  identifier for each accepted submission and persist it on the
  normalized corpus record as a `poster_id` field. Empirically
  verified upstream field (introspection probe 2026-05-13):
  `submissions.program_code` (String). The fetch query body MUST
  request `program_code` directly; the normalize step MUST rename
  it to `poster_id` on the output record. If upstream removes or
  renames `program_code` in a future schema change, the tiered
  drift detection (FR-003 HARD tier) catches it.
- **FR-021**: Stage 1 MUST retrieve each accepted submission's
  program-session memberships (poster standby + symposium + other
  programmed sessions the abstract appears in) and persist them on
  the normalized corpus record as a `program_sessions` list. Each
  list entry MUST contain, when upstream populates them: per-poster
  `start_time`, `end_time`, `display_order`; the linked session's
  `id`, `name`, `start_time`, `end_time`, `program_date.program_date`
  (date), `program_location.name`, `program_type.name`,
  `program_track.name`. Empty list is the legitimate value today
  (scheduling not yet entered upstream — see Clarifications
  2026-05-13). The fetch query body MUST ask for the full chain so
  values land automatically once OHBM organizer scheduling
  populates them. Null leaves on individual entries are tolerated;
  what is NOT tolerated is upstream RENAMING any of these fields
  while we still ask for them — that is HARD-tier drift (FR-003).
- **FR-022**: Stage 1 MUST support a separate withdrawn-corpus
  mode. Selection: `--corpus-kind=withdrawn` (default `accepted`).
  In withdrawn mode the stage uses a dedicated `WITHDRAWN_IDS_QUERY`
  filtering on `complete=true AND decision_status="Withdrawn" AND
  archived=false`, writes to `data/primary/abstracts_withdrawn.json`,
  and derives a state-key whose dependency basis explicitly includes
  `corpus_kind`. The accepted and withdrawn corpora MUST NEVER mix
  in a single file. The schema artifact, provenance record, and
  checkpoint for the withdrawn run also live under distinct
  state-key-derived filenames so the two namespaces are isolated.
  The CLI exposes both modes as discrete subcommands:
  `ohbmcli fetch-abstracts` (accepted, default) and
  `ohbmcli fetch-withdrawn` (forces corpus-kind=withdrawn).
- **FR-023**: Stage 1 MUST also fetch author details for every
  unique `author_id` referenced by the corpus it just produced.
  The fetch uses the existing `AUTHOR_QUERY` against
  `https://app.oxfordabstracts.com/v1/graphql`. The persisted
  record MUST include: `id`, `first_name`, `middle_initial`,
  `last_name`, `title`, `degree`, `orcid_id`, `presenting`,
  `submission_id`, `affiliations` (with `id`, `affiliation_order`,
  `institution`, `city`, `state`, `country`). The persisted record
  MUST NOT include `email` — the field is fetched from upstream
  but dropped before the on-disk record is written. Authors are
  written to:
  - `data/primary/authors.json` for the accepted-corpus run.
  - `data/primary/authors_withdrawn.json` for the
    withdrawn-corpus run.
  The two files MUST NEVER mix, parallel to FR-022. Update FR-008
  for these new artifact paths. Stage 1's schema-diff machinery
  (FR-003) MUST treat the fetched author fields as HARD-contract:
  upstream removing or renaming any of them blocks the run.
- **FR-024**: This feature removes the legacy `ohbmcli authors`
  subcommand outright (no backward-compatibility alias, parallel
  to FR-014's removal of `ohbmcli ingest`). The standalone
  `enrichment.authors_main` entry point and its associated
  argparse helper are deleted in the same change; downstream
  scripts that still invoke `ohbmcli authors` MUST be updated to
  call `ohbmcli fetch-abstracts` (or `fetch-withdrawn`). Operators
  who only want to refresh authors rely on Stage 1's resumability:
  the abstract content fetch short-circuits via the checkpoint
  when the corpus is already complete, and the author fetch runs
  to refresh `data/primary/authors.json`.

### Key Entities

- **Corpus Snapshot**: The normalized accepted-abstract corpus produced
  by the fetch stage. Path identical to today's
  `data/primary/abstracts.json` (plus a sibling GraphQL source under
  `data/inputs/abstracts_graphql__<state-key>.json`). Shape matches
  today's shape plus two new fields on each record:
  - `poster_id` (String) — sourced from upstream
    `submissions.program_code` (FR-020).
  - `program_sessions` (list) — sourced from upstream
    `submissions.program_sessions_submissions[]` with each linked
    `program_session` flattened (FR-021). Empty list when upstream
    has not yet scheduled the abstract.
  Every other user-visible field is preserved verbatim (FR-006).
- **GraphQL Schema Artifact**: A JSON file capturing the upstream
  Oxford Abstracts GraphQL schema introspection result at fetch time.
  Lives alongside the GraphQL source under `data/inputs/` with a
  name that pairs it to the same `<state-key>`.
- **Provenance Record**: A JSON sidecar with the fields enumerated in
  FR-005; lives alongside the corpus snapshot.
- **Schema Diff Summary**: A structured diff between the current and
  previous schema artifacts (added/removed/changed types and fields),
  partitioned into the three tiers defined in FR-003: HARD CONTRACT
  (fetch-query fields), SOFT CONTRACT (downstream-consumed fields,
  each tagged with the consuming module), and INFORMATIONAL. Embedded
  in the Provenance Record under `schema_diff_vs_previous`. Each
  entry names the field path, the change kind, the previous shape,
  the current shape, and the tier.
- **Resume Checkpoint**: A single JSON file persisted atomically as
  Stage 1 progresses (FR-017, FR-018, FR-019). Contains: the bound
  schema artifact hash; the last fully completed GraphQL page cursor;
  for the in-flight page, a per-abstract completion map (`done` /
  `in_progress` / `failed-retryable` / `failed-blocking`); a count of
  records completed and pending; the run id of the run that wrote it.
  Lives under the gitignored `data/inputs/` (or `data/cache/`) root.
- **Author Roster**: Normalized author records keyed by upstream
  `author_id`. Path: `data/primary/authors.json` for accepted-
  corpus authors; `data/primary/authors_withdrawn.json` for
  withdrawn-corpus authors (FR-023 / FR-022 parallel split). Each
  record carries the fields listed in FR-023 with `email`
  deliberately omitted. The roster is sorted by author `id` for
  byte-identical re-runs.
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
  stage. The persisted GraphQL schema, the tiered field-level diff
  (HARD / SOFT / INFORMATIONAL — see FR-003), and the "fail loudly
  on hard-contract drift" requirement are the explicit implementation
  of "discover external state, don't hardcode it". Neither the hard-
  contract field set nor the soft-contract field set MAY be expressed
  as a manually maintained allow-list that can silently drift from
  the code:
  - The hard-contract set MUST be derived at runtime from the GraphQL
    query body the fetch stage actually sends.
  - The soft-contract set MUST be derived at runtime from the
    downstream consumers (e.g. by static inspection of the
    `src/ohbm2026/` modules that read `abstracts.json`, or by an
    explicit consumer-side declaration each module owns and Stage 1
    discovers — the plan phase chooses the mechanism). The spec only
    constrains that the set is NOT a separate file Stage 1 reads.
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
  is resumable on the next invocation 100% of the time — measured by
  an automated test that interrupts the fetch at six distinct
  progress points: (1) before any page completes, (2) between two
  fully completed pages, (3) inside an in-flight page after some but
  not all records have resolved, repeated for each of the early /
  mid / late phases of the fetch. Resume MUST complete the corpus
  without re-fetching any record whose checkpoint marker is "done".
- **SC-009**: Across a sequence of interrupt-then-resume cycles on
  the same fetch, the count of GraphQL requests issued on resume MUST
  equal the count required for the records still pending (not the
  total record count) — verified by a request-counter mock in the
  test suite.
- **SC-002**: Two consecutive fetch-abstracts runs against unchanged
  upstream produce primary outputs (corpus snapshot, schema
  artifact) that match on 100% of user-visible fields; only
  provenance run-id and timestamp differ.
- **SC-003**: When a deliberate "hard-contract used-field renamed
  upstream" scenario is simulated in tests, Stage 1 detects and
  surfaces it with a precise error 100% of the time and writes 0
  corrupted corpus snapshots. Symmetrically, when a deliberate
  "soft-contract downstream-consumed-field dropped upstream"
  scenario is simulated, Stage 1 completes successfully AND the
  schema-diff summary contains a `DOWNSTREAM IMPACT` entry naming
  the consuming module — verified by an automated test.
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
- **SOFT-tier registry starts empty in production**: existing
  downstream consumers (`enrichment.py`, `openalex.py`,
  `neuroscape.py`, `ui.py`, `poster_layout.py`, etc.) do NOT yet
  declare `CONSUMED_ABSTRACT_FIELDS`, so the SOFT set is effectively
  empty when Stage 1 runs in production at v1. SOFT-tier
  classification is exercised in tests via synthetic registries (per
  SC-003's second half). The `CONSUMED_ABSTRACT_FIELDS` declarations
  land in the per-stage cleanup rounds that touch each consuming
  module (Stage 2..N). This is a deliberate phasing decision: Stage
  1 ships the mechanism; later stages populate it.

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
