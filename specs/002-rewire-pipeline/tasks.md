---

description: "Task list for Rewire Pipeline Stage 1 — Fetch Abstracts + GraphQL Schema"
---

# Tasks: Rewire Pipeline Stage 1 — Fetch Abstracts + GraphQL Schema

**Input**: Design documents from `/specs/002-rewire-pipeline/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED for every behavior task (Principle IV + User Story 3 in spec). Tests are written first and must fail, then implementation makes them pass (red → green). No xfail / skip / weakened assertions to make CI green (Principle VI).

**Organization**: Tasks are grouped by user story. All three user stories (US1, US2, US3) are P1 and must all land for Stage 1 to be complete.

**User stories**:
- **US1** — Operator re-runs the abstract-fetch stage independently and gets a schema-verified, resumable, provenance-bearing snapshot (the orchestrator BEHAVIOR).
- **US2** — The per-stage script pattern is documented and reusable (the PATTERN doc + companion doc-sync).
- **US3** — The Python library modules involved in Stage 1 have first-class test coverage (the TEST FILES). Per Principle IV, US3's tests are written before US1's implementation makes them pass.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3); omitted in Setup, Foundational, and Polish phases
- Every task includes an exact file path

## Path Conventions

- Library code: `src/ohbm2026/`
- Tests: `tests/` (existing `unittest`-based suite)
- Operator-facing wrappers: `scripts/`
- Docs: `docs/`, plus `README.md` and `CLAUDE.md` at repo root
- Spec artifacts: `specs/002-rewire-pipeline/`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm a clean pre-change baseline so we can detect regressions caused by this work.

- [ ] T001 Refresh `.venv` and run baseline tests: `UV_CACHE_DIR=.uv-cache uv venv --python 3.11 .venv && PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` — confirm only the known pre-existing `test_plot_poster_layout_floorplan` failure
- [ ] T002 [P] Run baseline lint: `.specify/scripts/bash/constitution-check.sh --full` — confirm exit 0 before any changes land

**Checkpoint**: Baseline is clean. Any new failure introduced from here on is owned by Stage 1 work.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared symbols and spec updates that every user story depends on.

**⚠️ CRITICAL**: No user story implementation may start until this phase is complete.

- [ ] T003 [P] Add the new path helpers to `src/ohbm2026/artifacts.py`: `build_schema_artifact_path(state_key)`, `build_provenance_path(state_key)`, `build_fetch_checkpoint_path(state_key)`. Each returns a `pathlib.Path` under the project-relative gitignored roots per data-model.md State-Key Convention.
- [ ] T004 [P] Create `src/ohbm2026/exceptions.py` defining typed exception hierarchy used across Stage 1: `Stage1Error(RuntimeError)` (base), `SchemaContractError(Stage1Error)` (HARD-tier drift), `CheckpointError(Stage1Error)` (resume validation failure), `ProvenanceError(Stage1Error)` (absolute/user-home path violation). Re-export `GraphQLAPIError` from `graphql_api.py` through this module for a single import surface.
- [ ] T005 Verify the poster-id wiring landed during planning: `specs/002-rewire-pipeline/spec.md` contains `FR-020` and the Clarifications session entry, the Corpus Snapshot Key Entity mentions `poster_id`, and the Edge Case for "upstream does not expose a poster-identifier field" is present; `specs/002-rewire-pipeline/data-model.md` opens with the Corpus Snapshot section that mentions `poster_id`. This task is a consistency check, not an authoring task — the content was authored during planning. If anything is missing, restore it before proceeding.
- [ ] T006 [P] Augment `tests/test_artifacts.py` with three new test cases: `test_build_schema_artifact_path_lives_under_inputs`, `test_build_provenance_path_lives_under_inputs`, `test_build_fetch_checkpoint_path_lives_under_cache`. Each asserts the returned path is project-relative, under the expected gitignored root, and contains the state-key segment. Tests MUST fail initially.

**Checkpoint**: Foundation ready. The new symbols exist, the spec records the poster-id requirement, and the path-helper tests are red.

---

## Phase 3: User Story 3 — Test Coverage (Priority: P1) — Tests-First

**Goal**: Author every test that Stage 1's User Story 1 implementation will need to pass. Per Principle IV, the tests land before the code and MUST initially fail.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` shows the new tests collected and failing (with messages that name the contract elements they verify, not generic `AttributeError`s).

### Tests for User Story 3 (REQUIRED, BEFORE IMPLEMENTATION) ⚠️

- [ ] T007 [P] [US3] Create `tests/test_schema_diff.py` with the following test classes: `TestFieldIndexEntry` (shape, JSON round-trip), `TestFlattenIntrospection` (synthetic introspection → expected field_index), `TestHashFieldIndex` (deterministic; JSON-whitespace-invariant; serialization-order-invariant), `TestParseHardSetFromQueries` (the minimal query-body AST walker; covers the two existing queries `ABSTRACT_IDS_QUERY` and `ABSTRACT_CONTENTS_QUERY` extended to include the poster-id field), `TestCollectSoftContractFields` (consumer-module registration model), `TestCompare` (HARD / SOFT / INFORMATIONAL classification; HARD+SOFT overlap case populates `downstream_consumers`).
- [ ] T008 [P] [US3] Augment `tests/test_graphql_api.py`: add `TestIntrospectionQuery` (canonical introspection request body + happy path); `TestIntrospectionRetry` (transient failures retried within budget; exhaustion raises `GraphQLAPIError`); `TestPosterIdRequested` (the live content query body includes the field representing the upstream poster identifier — name discovered from introspection in implementation, asserted by referencing a query-text fixture); `TestSchemaContractError` (HARD-tier mismatch raises typed error, message names old/new shape).
- [ ] T009 [P] [US3] Augment `tests/test_assets.py`: add `TestBatchedFetchHooks` (per-batch callback fires once per batch with correct submission_id list; per-record callback fires once per record with the (id, state) transition); `TestPerRecordStateTransitions` (pending → corpus_fetched → figures_in_progress → done; failed-retryable for figure errors; never transitions backwards); `TestPosterIdPropagation` (normalized abstract record carries the poster_id field populated from the upstream content response).
- [ ] T010 [P] [US3] Create `tests/test_fetch_stage.py` covering ALL six contract elements from US2: **input contract** (`OHBM2026_API` env var consumed by name only; missing → typed error); **output contract** (corpus + schema artifact + provenance written at expected paths; checkpoint deleted on success); **provenance contract** (record validates against `contracts/abstracts_fetch_provenance.schema.json`; no absolute or ~-prefixed paths); **error contract** (HARD-tier drift exits 2 and does NOT overwrite corpus; figure-failure-rate > threshold exits 5; semantically empty corpus exits 6); **resumability contract** (six interrupt points per SC-008: before-any-page, between-batches, mid-batch — each at early/mid/late phases; resume completes corpus; SC-009 request-count equals pending records only); **discovery contract** (schema introspection happens before content fetch; schema-diff classification runs on every run; checkpoint refuses to resume on bound_schema_hash mismatch without `--allow-schema-change`).
- [ ] T011 [P] [US3] Augment `tests/test_cli.py`: assert `ohbmcli ingest` subcommand is REMOVED (importing it or invoking it raises a clear "renamed to fetch-abstracts" error); assert `ohbmcli fetch-abstracts` parses every option enumerated in `contracts/cli.md`; assert all CLI exit codes from `contracts/cli.md` are reachable via tests for the corresponding error conditions.
- [ ] T012 [US3] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_schema_diff tests.test_graphql_api tests.test_assets tests.test_fetch_stage tests.test_cli tests.test_artifacts -v` and confirm ALL new tests fail (red phase). Verify failure messages name the missing contract element, not just `ImportError`.

**Checkpoint**: All US3 test files exist; the project's RED phase is established.

---

## Phase 4: User Story 1 — Stage 1 Orchestrator (Priority: P1)

**Goal**: Implement the modules and CLI rewire so every US3 test goes from red to green. This is the bulk of the engineering work.

**Independent Test**: `PYTHONPATH=src .venv/bin/python scripts/run_fetch_abstracts.py` against the live Oxford Abstracts endpoint (with a valid token) produces corpus + schema artifact + provenance record; running it twice in a row produces byte-identical primary outputs; interrupting it mid-fetch and re-running it completes the corpus without re-fetching done records.

### Implementation for User Story 1

- [ ] T013 [P] [US1] Implement `src/ohbm2026/schema_diff.py` with: `FieldIndexEntry` dataclass; `flatten_introspection(introspection_raw: dict) -> list[FieldIndexEntry]`; `hash_field_index(entries) -> str`; `parse_hard_set_from_queries(*query_texts: str) -> set[tuple[str, str]]` using a minimal recursive AST walker (no third-party GraphQL parser); `collect_soft_contract_fields() -> dict[tuple[str, str], list[str]]` that imports each `src/ohbm2026/` consuming module and unions its `CONSUMED_ABSTRACT_FIELDS` declarations; `compare(prev_index, curr_index, hard_set, soft_set) -> list[SchemaDiffEntry]`. Pure functions; no I/O. Make every Test in T007 pass.
- [ ] T014 [US1] Add introspection support to `src/ohbm2026/graphql_api.py`: define `INTROSPECTION_QUERY` constant (the canonical graphql-spec introspection query body); add `fetch_schema_introspection(api_key, ...) -> dict` that uses the existing `graphql_request()`. Extend `ABSTRACT_CONTENTS_QUERY` to also request the poster-identifier field whose name is discovered from the introspection at implementation time (the introspection tells us the actual upstream field name — if upstream does not expose one, raise `SchemaContractError` per T005's Edge Case). Make every Test in T008 pass.
- [ ] T015 [US1] Refactor `src/ohbm2026/assets.py`: split `build_database` into focused functions — `resolve_submission_ids()`, `fetch_content_batches(ids, batch_size, on_batch_complete, on_record_state_change)`, `download_figures_for_abstract(abstract, ...)`. Expose the two callback hooks for the orchestrator's checkpoint lifecycle. Extend `normalize_abstract` to include the new `poster_id` field on the normalized record (FR-020 / T005). Add `CONSUMED_ABSTRACT_FIELDS: frozenset[str]` declaration if `assets.py` itself reads from a future `abstracts.json` (likely empty here, but the convention is established). Preserve every existing user-visible field of `data/primary/abstracts.json` (FR-006). Make every Test in T009 pass.
- [ ] T016 [US1] Implement `src/ohbm2026/fetch_stage.py` — depends on T013, T014, T015. Module exposes `main(argv: list[str] | None = None) -> int` as the testable orchestration entry. Internal flow: parse args → load API key (named env var only) → introspect schema → diff vs previous → on HARD drift, raise `SchemaContractError` → load-or-create checkpoint, validate `bound_schema_hash` → resolve_submission_ids → for each batch, fetch content, write per-record checkpoint updates, atomic-rename → on full completion, write corpus snapshot atomically, write provenance record atomically, delete checkpoint, print summary JSON. Atomic write via `tempfile.NamedTemporaryFile(dir=...)` + `os.replace`. All path writes validated against absolute / `~`-prefix (raises `ProvenanceError`). Add `CONSUMED_ABSTRACT_FIELDS = frozenset()` (orchestrator does not consume `abstracts.json`). Make every Test in T010 pass.
- [ ] T017 [US1] Rewire `src/ohbm2026/cli.py`: REMOVE the `ingest` subcommand entirely (no alias, no deprecation shim — per Clarifications session). ADD `fetch-abstracts` subcommand that delegates to `ohbm2026.fetch_stage.main`. Argparse choices and options match `contracts/cli.md` exactly. Make every Test in T011 pass.
- [ ] T018 [P] [US1] Create `scripts/run_fetch_abstracts.py` — a 10-line wrapper that imports `ohbm2026.fetch_stage.main` and forwards `sys.argv[1:]`. Shebang `#!/usr/bin/env -S .venv/bin/python` (or document the `PYTHONPATH=src .venv/bin/python …` invocation in the file header). Make `chmod +x` part of the same change.
- [ ] T019 [US1] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_schema_diff tests.test_graphql_api tests.test_assets tests.test_fetch_stage tests.test_cli tests.test_artifacts -v` and confirm ALL US3 tests now PASS (green phase). If any test fails, fix the implementation — do NOT weaken the test.

**Checkpoint**: Stage 1 is functional. The new orchestrator works end-to-end; resume works; schema-diff classification works; poster_id is captured.

---

## Phase 5: User Story 2 — Pattern Doc + Doc Sync (Priority: P1)

**Goal**: Document the per-stage pattern so subsequent stages have a model to follow, and sync every doc that points at Stage 1.

**Independent Test**: Hand `docs/per-stage-pattern.md` + `src/ohbm2026/fetch_stage.py` to someone who has not seen this work; in under 10 minutes they identify each of the six contract elements in the code (SC-005).

- [ ] T020 [P] [US2] Create `docs/per-stage-pattern.md` documenting the six contracts (input, output, provenance, error-handling, resumability, discovery). Each contract section: a one-sentence definition + a code reference into `src/ohbm2026/fetch_stage.py` by function name (e.g. "**Input contract**: see `fetch_stage._load_api_key` and `fetch_stage._parse_args`"). The doc names Stage 1 as the canonical reference instance and notes which functions to adapt for a future Stage N.
- [ ] T021 [US2] Update `README.md` "End-To-End Workflow" section: remove the `ohbmcli ingest` invocation in Step 1; replace with the `scripts/run_fetch_abstracts.py` and `ohbmcli fetch-abstracts` invocations from `contracts/cli.md` + `quickstart.md`; add a sentence pointing at `docs/per-stage-pattern.md`; update the "Module Layout" section to list `fetch_stage.py`, `schema_diff.py`, and `exceptions.py`; update the "Main Outputs By Stage" entry for raw ingest to also list the schema artifact, provenance record, and (gitignored) checkpoint.
- [ ] T022 [P] [US2] Update `CLAUDE.md`: refresh the "Module Layout" mentions; refresh the "Default pipeline state" section if any default changed; update the "Reading order" entry that points at the plan; ensure `CLAUDE.md`'s `## Non-negotiables` list is unchanged (no new principle introduced).
- [ ] T023 [P] [US2] Update `docs/reproducibility-vision.md` Stage 1 paragraph (in the "Reproduction Ladder" section, Level 3): replace the `ohbmcli ingest` reference with the new entry; mention the persisted GraphQL schema and the per-stage pattern doc as new artifacts.

**Checkpoint**: All Stage 1 docs are consistent with the code. Future readers find the canonical entry point and the pattern doc without rediscovering them.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verify the cross-cutting invariants from the constitution and from the spec's Success Criteria.

- [ ] T024 Run the full test suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`. Confirm green except the pre-existing unrelated `test_plot_poster_layout_floorplan` failure. No new failures, no skipped tests, no xfail markers (Principle VI, SC-006).
- [ ] T025 Run `.specify/scripts/bash/constitution-check.sh --full` and confirm exit 0 (SC-007).
- [ ] T026 Run `git status --porcelain` and `git diff --cached --name-only` after staging — verify NO file under `data/`, `export/`, `tmp/`, `archive/`, `memory/archive/`, or `.claude/` was tracked or staged (Principle II, CA-005, FR-008).
- [ ] T027 Provenance fixture audit: grep test fixtures for absolute path patterns (`^/`) and home-prefix patterns (`~/` and `os.path.expanduser`) — assert none appear in any committed test or fixture under `tests/`. Use `git grep -nE "(\"|')(/Users/|/home/|~/)" -- tests/` and confirm any hit is a fixture asserting that such paths are REJECTED, not used as valid input (CA-008).
- [ ] T028 Performance smoke (non-blocking): record wall-clock time of a fresh `scripts/run_fetch_abstracts.py` run against the live endpoint, compare to the most recent successful `ohbmcli ingest` time in `memory/summary.md` or recent runs. Allow up to 25% regression (loose envelope, not a primary SC). Record the result in the run's provenance record.
- [ ] T029 SC-005 walkthrough (manual): hand `docs/per-stage-pattern.md` + `src/ohbm2026/fetch_stage.py` to someone unfamiliar with the work; have them locate the six contract elements; record the time. Acceptance: under 10 minutes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** — no dependencies; starts immediately.
- **Foundational (Phase 2)** — depends on Setup completion. BLOCKS all user-story phases. T003, T004, T006 can run in parallel; T005 should land first so subsequent tasks can reference FR-020 + the updated data-model; the augmented `test_artifacts.py` (T006) can be written in parallel with T003 because they touch different files.
- **User Story 3 (Phase 3, tests-first)** — depends on Foundational. All five new/augmented test files are parallel ([P]) because they live in different files. T012 (red-phase verification) is sequential after T007–T011.
- **User Story 1 (Phase 4, implementation)** — depends on US3 tests existing (red). T013 (`schema_diff.py`) is independent and can land first. T014 (`graphql_api.py`) is independent of T013/T015 but the introspection-discovered poster-id field name from T014 informs T015. T015 (`assets.py`) needs T014 done. T016 (`fetch_stage.py`) depends on T013, T014, T015. T017 (`cli.py`) and T018 (`scripts/run_fetch_abstracts.py`) depend on T016. T019 is the green-phase verification, sequential at the end.
- **User Story 2 (Phase 5, docs)** — depends on US1 implementation existing so `docs/per-stage-pattern.md` can cite real function names. T020, T022, T023 can run in parallel; T021 (README) is the bigger edit and is sequential within its lane.
- **Polish (Phase 6)** — depends on US1, US2, US3 all complete.

### User Story Dependencies

- **US3 BEFORE US1**: tests are written and failing before implementation makes them pass (Principle IV).
- **US1 BEFORE US2**: pattern doc cites real function names in `fetch_stage.py`.
- **US3 and US1 ARE COUPLED**: cannot release US1 without US3 tests passing. Cannot release US3 alone (tests would fail).
- **All three (US1, US2, US3) BEFORE handoff**: spec says all are P1 for Stage 1 done.

### Parallel Opportunities

- All Phase 2 tasks (T003, T004, T006 — different files) run in parallel; T005 (spec update) is independent.
- All Phase 3 test files (T007–T011) — different files, no inter-task dependencies — run in parallel.
- T013 (`schema_diff.py`) and T014 (`graphql_api.py`) — different files, no shared dependencies — run in parallel.
- T018 (`scripts/run_fetch_abstracts.py`) — runs in parallel with T017 (`cli.py`) and T019.
- T020 (pattern doc), T022 (CLAUDE.md), T023 (vision doc) — different files — run in parallel.
- Polish tasks T024, T025, T026, T027 — verification only, can run in parallel after Phase 5.

---

## Implementation Strategy

### MVP First

The MVP is the union of US1 (functional Stage 1) + US3 (test coverage) + US2 (pattern doc). All three are P1; none can be deferred without violating spec or constitution.

1. Complete Phase 1 (Setup) and Phase 2 (Foundational). Commit.
2. Complete Phase 3 (US3 tests, red phase). Commit.
3. Complete Phase 4 (US1 implementation, green phase). Commit after each major file (schema_diff.py, graphql_api.py extension, assets.py refactor, fetch_stage.py, cli.py rewire, scripts wrapper).
4. Complete Phase 5 (US2 pattern doc + doc sync). Commit.
5. Complete Phase 6 (Polish/verification). Commit if any small fixes needed.
6. End-to-end verification: full unittest pass, constitution lint pass, manual quickstart walkthrough.

### Commit cadence (Principle V)

- Every verified slice gets its own commit with a descriptive message.
- Do NOT batch unrelated phases into one commit.
- Each commit MUST contain only source / docs / tests / specs — never data, caches, exports, or downloaded assets.
- The `.githooks/pre-commit` constitution lint runs automatically on every commit.

### Parallel team strategy

If multiple contributors are available:
- Contributor A: Phase 2 + Phase 3 test files (T003–T012)
- Contributor B: Once Phase 3 lands, T013 + T014 in parallel; then T015, T016, T017, T018 sequentially
- Contributor C: Phase 5 docs (after Phase 4 is complete enough to cite real function names)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps task to user story for traceability.
- Tests are written first and MUST fail before implementation begins (Principle IV).
- Commit early and often: each validated slice gets its own descriptive commit; do not batch hours of work into one commit, and push once the requested change is complete unless the requester explicitly says not to (Principle V).
- Commits MUST NOT include data, caches, exports, downloaded assets, or secrets (Principle II). The `.githooks/pre-commit` constitution lint catches the automatable subset.
- Never silence failures or bypass verification gates to make a task look done; surface the error and address the root cause (Principle VI). No `--no-verify`, no skipped tests, no xfail-as-shortcut.
- All Python invocations run through `.venv/bin/python` or `uv` targeting that interpreter (Principle I, FR-011).
- External-state discovery is the defining feature: the poster-id field name is discovered from introspection at implementation time, not hardcoded (Principle VII).
- Provenance record paths are project-relative; no absolute or `~`-prefixed paths reach disk (Principle VIII, CA-008).
