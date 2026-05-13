---

description: "Task list for Stage 2 — Enrich Abstracts (Figures, Claims, References)"
---

# Tasks: Stage 2 — Enrich Abstracts (Figures, Claims, References)

**Input**: Design documents from `/specs/003-enrich-abstracts/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED for every behavior task (Principle IV + CA-002 in spec). Tests are authored first and must fail, then implementation makes them pass (red → green). No xfail / skip / weakened assertions to make CI green (Principle VI).

**Organization**: Tasks are grouped by Setup → Foundational → User Stories → Docs → Polish. All four user stories share the same orchestrator and storage implementation; US1 is the bedrock and US2/US3/US4 verifications mostly pass-for-free once US1 is implemented correctly. Tests for each user story land FIRST as red-phase tasks.

**User stories**:
- **US1 (P1, MVP)** — Operator runs Stage 2 against the current accepted corpus and produces an enriched corpus.
- **US2 (P1)** — Re-run with unchanged models reuses all caches; byte-identical output; zero API calls.
- **US3 (P1)** — Changing one component's model invalidates only that component's cache.
- **US4 (P2)** — Abstracts moving between accepted and withdrawn are handled gracefully across runs.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task primarily belongs to (US1, US2, US3, US4); omitted in Setup, Foundational, Docs, and Polish phases
- Every task includes an exact file path

## Path Conventions

- Library code: `src/ohbm2026/`
- Tests: `tests/` (existing `unittest`-based suite)
- Operator-facing wrappers: `scripts/`
- Docs: `docs/`, plus `README.md` and `CLAUDE.md` at repo root
- Spec artifacts: `specs/003-enrich-abstracts/`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm a clean pre-change baseline so we can detect regressions caused by this work.

- [X] T001 Refresh `.venv` and run baseline tests: `UV_CACHE_DIR=.uv-cache uv venv --python 3.11 .venv && PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` — confirm only the known pre-existing `test_plot_poster_layout_floorplan` failure
- [X] T002 [P] Run baseline lint: `.specify/scripts/bash/constitution-check.sh --full` — confirm exit 0 before any changes land

**Checkpoint**: Baseline is clean. Any new failure introduced from here on is owned by Stage 2 work.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared symbols every user-story phase depends on.

**⚠️ CRITICAL**: No user-story implementation may start until this phase is complete.

- [X] T003 [P] Add the new path helpers to `src/ohbm2026/artifacts.py`: `PRIMARY_ENRICHED_CORPUS_PATH` (= `data/primary/abstracts_enriched.sqlite`), `build_enrich_provenance_path(state_key)` (= `data/inputs/abstracts_enrich_provenance__<state-key>.json`), `build_enrich_cache_path(component, cache_key)` (= `data/cache/<component>/<cache-key>.json`). Each MUST return a project-relative `pathlib.Path` under a gitignored root.
- [X] T004 [P] Extend `src/ohbm2026/exceptions.py` with the Stage 2 hierarchy. Introduce a shared cross-stage base `OhbmStageError(RuntimeError)` and reparent `Stage1Error` to it (in the same edit, retaining backward-compat: `Stage1Error(OhbmStageError)` still has `RuntimeError` as a transitive ancestor). Then `Stage2Error(OhbmStageError)`; `EnrichmentError(Stage2Error)` (LLM-call / component failure); `CacheVersionError(Stage2Error)` (cache schema mismatch); `ComponentFailureThresholdError(Stage2Error)` (per-component failure rate exceeded threshold). Re-export these from the module's `__all__`. Per spec FR-010 + CA-006 these MUST be the only ways Stage 2 surfaces its named failure modes; a unified `OhbmStageError` base lets callers express "any pipeline failure" with a single `except`. Verify Stage 1's existing `Stage1Error` consumers still work via the wider isinstance chain.
- [X] T005 [P] Define module-level version constants in `src/ohbm2026/enrich_storage.py` (NEW, stub): `STORAGE_VERSION = "enrich.storage.v1"`, `CACHE_VERSION = "enrich.cache.v1"`, `PROVENANCE_VERSION = "enrich.provenance.v1"`. The file body is just these constants + module docstring at this stage — implementation lands in T012.
- [X] T006 [P] Augment `tests/test_artifacts.py` with three new tests: `test_primary_enriched_corpus_path_lives_under_primary`, `test_build_enrich_provenance_path_lives_under_inputs`, `test_build_enrich_cache_path_uses_component_namespace`. Each asserts the returned path is project-relative, under the expected gitignored root, and (where applicable) embeds the cache key / state key. Tests MUST fail initially against the current `artifacts.py` before T003 lands.

**Checkpoint**: Foundation ready. New symbols exist, version constants pinned, path-helper tests are red (or green if T003 ran before T006 verification — order within Phase 2 is flexible since T003/T006 touch different files).

---

## Phase 3: User Story Tests (Tests-First, Red Phase)

**Goal**: Author every test for all four user stories. Per Principle IV, the tests land before implementation and MUST initially fail (or, for shared-implementation cases, fail in the same way US1's tests fail).

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_storage tests.test_enrich_stage tests.test_cli tests.test_artifacts -v` shows the new tests collected and failing with messages that name the missing contract elements, not generic `AttributeError`s.

### Tests for User Story 1 — MVP run (P1) ⚠️

- [ ] T007 [P] [US1] Create `tests/test_enrich_storage.py` with the following test classes: `TestRoundTrip` (write then read one abstract; zlib correctness; primary-key uniqueness); `TestRandomByID` (lookup of 100 random IDs returns the correct payloads; latency < 10 ms per lookup); `TestSequentialIteration` (iter_enriched yields all records in id order); `TestAtomicWrite` (temp file is renamed to canonical on success; mid-write interruption leaves the previous file intact); `TestCorpusMetadataTable` (the `corpus_metadata` rows match the version constants and state-key); `TestEnrichedRecordSchema` (one round-tripped record validates against `contracts/enriched_record.schema.json` — load the schema, walk the record's `figure_interpretation`, `claims`, `references` lists against the `$defs` shapes; fail loudly if a required field is missing or has the wrong type). Use a `TemporaryDirectory` for all I/O.
- [ ] T008 [P] [US1] Create `tests/test_enrich_stage.py` with SIX test classes — one per contract in the per-stage pattern (`docs/per-stage-pattern.md`):
  - `InputContractTests` — missing source corpus → typed error; OHBM2026_API not consulted by Stage 2 (only component-specific API keys are); missing API key for the configured backend → typed error.
  - `OutputContractTests` — enriched SQLite written at canonical path; provenance written; provenance path is project-relative; corpus_metadata reflects the run; FR-015 verification (no Stage 1 output is modified — snapshot mtimes of `data/primary/abstracts.json`, `abstracts_withdrawn.json`, `authors.json`, the schema artifact, and the figure assets before the run; assert all unchanged after).
  - `ProvenanceContractTests` — every required field from `enrich_provenance.schema.json` is present; env-var NAMES only; no absolute or `~`-prefixed paths; `parquet_export_path` is null when the flag wasn't passed and is set + project-relative when it was (cross-references T033).
  - `ErrorContractTests` (FR-010 + CA-006) — exceeding `--figure-failure-threshold` raises `ComponentFailureThresholdError` and main() returns exit code 5; same for claims; a synthetic mid-run `EnrichmentError` from one component bubbles up as exit code 1; an absolute-path provenance candidate raises `ProvenanceError` and main() returns exit 4; a `cache_version` mismatch on disk raises `CacheVersionError` and main() returns exit 7.
  - `ResumabilityContractTests` (SC-009) — start a run that writes per-component cache entries for the FIRST half of abstracts, then synthetically `raise EnrichmentError` mid-loop; assert no partial enriched SQLite was written (the previous one — or absence — remains). Re-invoke `main()`; assert the second invocation reuses every already-cached entry (zero LLM mock calls for the first half) and only re-enriches the second half. Verify the final SQLite is complete.
  - `DiscoveryContractTests` (CA-007) — feed a malformed mock LLM response (missing field for figures component) — assert `EnrichmentError` raised; do the same with a malformed claims response — assert raised. Confirm the offending response is captured in either the cache file or provenance for post-hoc diagnosis. Confirm `_classify_backend_availability` returns a typed result (the helper's return shape: a dataclass with `figures_backend: str`, `claims_backend: str`, `references_backend: str` fields).
  Patch all upstream LLM/HTTP calls via a `_patch_upstream` helper modeled on `tests/test_fetch_stage.py::_patch_upstream` — it MUST patch BOTH `ohbm2026.enrichment.fetch_abstract_content` (the local name-imported binding) AND the upstream `ohbm2026.graphql_api.*` references, plus `ohbm2026.enrichment.analyze_figures_batch`, `ohbm2026.enrichment.extract_claims_batch` (or their local equivalents), and `ohbm2026.openalex.*` reference-resolution entries. The test fixture provides synthetic abstracts with deterministic content hashes.
- [ ] T009 [P] [US1] Augment `tests/test_cli.py`: assert `ohbmcli enrich`, `analyze-figures`, `extract-claims`, `reference-metadata` all raise `SystemExit` (subcommands removed per FR-014); assert `ohbmcli enrich-abstracts` parses every option enumerated in `contracts/cli.md` and delegates to `ohbm2026.enrich_stage.main` with stripped argv.

### Tests for User Story 2 — Idempotency (P1) ⚠️

- [ ] T010 [P] [US2] Add class `IdempotencyContractTests` to `tests/test_enrich_stage.py`: run Stage 2 twice with the same source corpus and same model identifiers (mocked LLM responses fixed); assert the second run's provenance shows 100% cache hits for every component; assert the SQLite file's `abstracts.payload` blobs are byte-identical between runs (modulo `corpus_metadata.built_at` and provenance run_id/timestamp); assert zero LLM/API mock calls during the second run.

### Tests for User Story 3 — Component invalidation (P1) ⚠️

- [ ] T011 [P] [US3] Add class `ComponentInvalidationTests` to `tests/test_enrich_stage.py`: baseline run with `figure-model-id=A`, `claims-model-id=X`, `reference-strategy-id=R`; second run with `figure-model-id=B` (only figures changed); assert provenance shows figures component has cache_miss_count == abstract_count, claims + references have 100% cache hits; symmetrically, repeat for `--invalidate claims` and `--invalidate references` forcing miss-on-one-component-only.

### Tests for User Story 4 — Movement handling (P2) ⚠️

- [ ] T012 [P] [US4] Add class `MovementHandlingTests` to `tests/test_enrich_stage.py`: synthesize three abstracts A, B, C in the corpus. Run 1: A and C accepted, B withdrawn → enriched corpus contains A and C only. Mutate the source corpus before Run 2: A is now withdrawn, B is now accepted, C unchanged. Run 2: assert enriched corpus contains B and C only (NOT A); assert B's enrichment came from cache (zero LLM calls for B because content hash matches what was cached during a hypothetical earlier acceptance — seed the cache manually); assert C's record is byte-identical to Run 1.

### Red-phase verification

- [ ] T013 [US1] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_storage tests.test_enrich_stage tests.test_cli tests.test_artifacts -v` and confirm ALL new tests fail (red phase). Verify failure messages name the missing contract element (e.g., `ModuleNotFoundError: ohbm2026.enrich_stage`), not generic noise.

**Checkpoint**: All user-story test files exist; the project's RED phase is established.

---

## Phase 4: User Story 1 — Stage 2 Orchestrator Implementation (Priority: P1)

**Goal**: Implement the orchestrator + storage helper so every US1 test goes from red to green. The same implementation auto-satisfies US2/US3/US4's behavioral assertions once correctly done.

**Independent Test**: `PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py` against the live accepted corpus (`data/primary/abstracts.json`) with the default models produces `data/primary/abstracts_enriched.sqlite` + provenance + per-component cache entries; a second run produces a byte-identical SQLite (modulo provenance metadata).

### Implementation for User Story 1

- [ ] T014 [P] [US1] Implement `src/ohbm2026/enrich_storage.py` (extends the T005 stub): `EnrichedCorpusWriter` context manager that wraps SQLite + atomic temp→rename; `write_record(record_dict)` zlib-compresses the JSON; `read_one_by_id(path, abstract_id) -> dict | None`; `iter_enriched(path) -> Iterator[dict]`; `corpus_metadata(path) -> dict`. Pure I/O; no orchestration; no calls into `enrichment.py`. Make every test in T007 pass.
- [ ] T015 [US1] Implement `src/ohbm2026/enrich_stage.py` orchestrator (depends on T014 + foundational symbols). Module exposes `main(argv: list[str] | None = None) -> int` returning the exit codes documented in `contracts/cli.md`. Internal flow: parse args → discover backend availability → hash source corpus + derive state-key → load Stage 1 corpus → for each accepted abstract, run the three components against their per-component caches → assemble `EnrichedAbstractRecord` per `contracts/enriched_record.schema.json` → atomically write SQLite via `enrich_storage.EnrichedCorpusWriter` → compute delta vs previous enriched corpus (if any) → atomically write provenance per `contracts/enrich_provenance.schema.json` → print stdout summary. Internal helpers: `_compute_state_key`, `_classify_backend_availability` (returns a frozen `BackendAvailability` dataclass with `figures_backend: str`, `claims_backend: str`, `references_backend: str` fields), `_run_figure_component`, `_run_claims_component`, `_run_references_component`, `_atomic_write_provenance`, `_assert_paths_safe`. The three component runners are thin wrappers over the existing `enrichment.py` and `openalex.py` building blocks — no refactor of those modules in this round (per spec Future Work). Each component runner MUST validate the LLM response shape on parse and raise `EnrichmentError` on mismatch (CA-007); the offending response is captured in the cache write or in the run's failure log for post-hoc diagnosis. Make every test in T008 pass.
- [ ] T016 [US1] Rewire `src/ohbm2026/cli.py`: REMOVE the `enrich`, `analyze-figures`, `extract-claims`, `reference-metadata` subcommands and their dispatch entries. ADD `enrich-abstracts` subcommand that delegates to `ohbm2026.enrich_stage.main`. Argparse choices and options match `contracts/cli.md` exactly. Make every test in T009 pass.
- [ ] T017 [P] [US1] Create `scripts/run_enrich_abstracts.py` — a 10-line wrapper that imports `ohbm2026.enrich_stage.main` and forwards `sys.argv[1:]`. Same shebang + sys.path setup pattern as `scripts/run_fetch_abstracts.py`. `chmod +x` part of the same change.
- [ ] T018 [US1] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_storage tests.test_enrich_stage tests.test_cli tests.test_artifacts -v` and confirm ALL US1 tests now PASS (green phase). If any test fails, fix the implementation — do NOT weaken the test.

**Checkpoint**: Stage 2 is functional. The orchestrator runs end-to-end against synthetic fixtures; the SQLite output is correctly structured; provenance is recorded.

---

## Phase 5: User Story 2 — Idempotency Verification (Priority: P1)

**Goal**: Confirm that the US1 implementation also passes the idempotency contract (US2 tests should now go green without additional implementation work).

- [ ] T019 [US2] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.IdempotencyContractTests -v` and confirm green. If failures, the implementation has a non-determinism bug (e.g., dict iteration order, timestamps leaking into the payload) — fix the implementation, not the test.

---

## Phase 6: User Story 3 — Component-Invalidation Verification (Priority: P1)

**Goal**: Confirm US1's per-component cache isolation works end-to-end.

- [ ] T020 [US3] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.ComponentInvalidationTests -v` and confirm green. If failures, the cache-key derivation is conflating components — fix the implementation.

---

## Phase 7: User Story 4 — Movement Handling Verification (Priority: P2)

**Goal**: Confirm US1's stateless-with-cache design handles accepted↔withdrawn movements correctly.

- [ ] T021 [US4] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.MovementHandlingTests -v` and confirm green. If failures, the orchestrator is reading the previous enriched corpus for content (not just for the delta-vs-previous summary) — fix the implementation.

### Resumability verification (SC-009)

- [ ] T021a [US1] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.ResumabilityContractTests -v` and confirm green. If failures, the orchestrator either wrote a partial SQLite (it should write only at the end as one atomic commit) OR ignored existing per-component cache entries on the second run — fix the implementation.

### Discovery + error contract verification (CA-006, CA-007, FR-010)

- [ ] T021b [US1] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.ErrorContractTests tests.test_enrich_stage.DiscoveryContractTests -v` and confirm green. If `ErrorContractTests` fails, a typed exception isn't reaching `main()` and being mapped to the documented exit code — fix `enrich_stage.main`. If `DiscoveryContractTests` fails, a component is "best-effort parsing" a malformed LLM response instead of raising — fix the component runner in `enrich_stage.py` (the existing helper in `enrichment.py` may need a validate-before-return wrapper).

---

## Phase 8: Doc Sync (Cross-Story)

**Goal**: Document Stage 2 across the project's doc surfaces so future readers can find it; remove references to the four legacy subcommands.

- [ ] T022 [P] Update `docs/per-stage-pattern.md`: add Stage 2 as a co-canonical reference instance of the pattern alongside Stage 1. Cite `src/ohbm2026/enrich_stage.py` by function name for each of the six contracts (input via `_load_source_corpus`; output via `enrich_storage.EnrichedCorpusWriter` + `_write_provenance`; provenance via `_build_provenance_record`; error via the typed exception hierarchy in `exceptions.py`; resumability via per-component cache writes; discovery via `_classify_backend_availability`).
- [ ] T023 Update `README.md`: add a "### 2. Enrich The Corpus" section (mirrors quickstart.md); list the new entry points (`scripts/run_enrich_abstracts.py`, `ohbmcli enrich-abstracts`); document the `--invalidate <component>` flag; document `--export-parquet PATH` as an optional secondary export that requires installing the new `parquet` optional extra (`uv pip install --python .venv/bin/python ".[parquet]"`); remove references to the four removed legacy subcommands from "End-To-End Workflow", "Token And Tool Matrix", and "Main Outputs By Stage". Update "Module Layout" to list `enrich_stage.py` + `enrich_storage.py`.
- [ ] T024 [P] Update `CLAUDE.md`: refresh the subcommand catalog (drop the four removed; add `enrich-abstracts`); refresh the code-architecture section to mention `enrich_stage.py`, `enrich_storage.py`, the SQLite+zlib decision, and the per-component cache layout.
- [ ] T025 [P] Update `docs/reproducibility-vision.md` Reproduction Ladder Level 2: replace the four old enrichment commands with `ohbmcli enrich-abstracts` as a single step; note the SQLite enriched output and the per-component cache namespaces.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Verify the cross-cutting invariants from the constitution and from the spec's Success Criteria.

- [ ] T026 Run the full test suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`. Confirm green except the pre-existing unrelated `test_plot_poster_layout_floorplan` failure. No new failures, no skipped tests, no xfail markers (Principle VI, SC-008).
- [ ] T027 Run `.specify/scripts/bash/constitution-check.sh --full` and confirm exit 0 (SC-008).
- [ ] T028 Run `git status --porcelain` after staging — verify NO file under `data/`, `export/`, `tmp/`, `archive/`, `memory/archive/`, or `.claude/` was tracked or staged (Principle II, CA-005, FR-011).
- [ ] T028a Verify FR-015 in the live state: capture `os.stat()` for `data/primary/abstracts.json`, `abstracts_withdrawn.json`, `authors.json`, `authors_withdrawn.json`, each `data/inputs/abstracts_graphql_schema__*.json`, and a representative sample of `data/primary/assets/*` BEFORE the live smoke run (T030). After T030 completes, re-stat them all and assert mtimes unchanged. Confirms Stage 2 read-only access to Stage 1 outputs at runtime, complementing the OutputContractTests in-test assertion.
- [ ] T029 Provenance fixture audit: grep test fixtures for absolute / `~`-prefixed path patterns — `git grep -nE "(\"|')(/Users/|/home/|~/)" -- tests/` returns nothing or only fixtures that ASSERT such paths are REJECTED (CA-008).
- [ ] T030 Live smoke run against the current accepted corpus: `PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py`. Verify the resulting SQLite file is < 30 MB (FR-009 + SC-007: at least 30% smaller than the 70 MB verbose JSON the historical pipeline produced) and that a random-by-id lookup completes in < 10 ms (SC-006). Record the observed values in the run's provenance.
- [ ] T031 SC-001 walkthrough (manual): hand the updated README's Stage 2 section to an unfamiliar contributor and have them run Stage 2 end-to-end. Record any other documentation lookups required. Acceptance: zero docs lookups beyond the README's Stage 2 section. (Tracked in the manual-walkthrough issue.)
- [ ] T032 [P] [US1] Implement optional Parquet export in `src/ohbm2026/enrich_stage.py` (FR-017). When `--export-parquet PATH` is set, after the canonical SQLite atomic commit succeeds, lazy-import `pyarrow` and write a two-column Parquet file (`id: int64`, `payload: string` with JSON serialization) to PATH. PATH MUST be under a gitignored root (Principle II / CA-005). The default (no flag) MUST NOT touch `pyarrow` — the orchestrator's top-level imports stay stdlib-only. Record the project-relative export path in the provenance record's `parquet_export_path` field (see `data-model.md` §3 + `contracts/enrich_provenance.schema.json`); when the flag was NOT passed, write `parquet_export_path: null` so the field is always present.
- [ ] T033 [P] [US1] Add `TestParquetExport` class to `tests/test_enrich_stage.py`: with `--export-parquet PATH` set, assert the Parquet file is created AND the SQLite file is also written; without the flag, assert NO Parquet file exists; assert `pyarrow` is not imported when the flag is absent (use `sys.modules` introspection); when the flag is set on a tmpfs path under `data/`, the run succeeds AND the provenance record's `parquet_export_path` equals the resolved project-relative path; without the flag, assert provenance `parquet_export_path` is `null`; when set on an absolute / `~`-prefixed path, the run fails with `ProvenanceError`-style boundary refusal. `pyarrow` is installed via the `parquet` optional extra (`uv pip install --python .venv/bin/python ".[parquet]"`) and is a hard prerequisite for this test — if not importable, FAIL the test loudly with an actionable message ("install via `pip install ohbm2026[parquet]`"). Do NOT `skip` it (Principle VI: no silent skips making CI look green).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** — no dependencies; starts immediately.
- **Foundational (Phase 2)** — depends on Setup completion. BLOCKS all user-story phases. T003, T004, T005, T006 can run in parallel — they touch different files.
- **User Story Tests (Phase 3)** — depends on Foundational. All test files are parallel ([P]) because they live in different files (test_enrich_storage.py and test_enrich_stage.py); the classes within test_enrich_stage.py for US1/US2/US3/US4 must all be present before T013 (red verification) runs.
- **US1 Implementation (Phase 4)** — depends on Phase 3 tests existing (red). T014 is independent and lands first. T015 depends on T014. T016 depends on T015 (cli must point at enrich_stage.main). T017 (wrapper) is parallel with T015/T016. T018 (green-phase verification) is sequential at the end.
- **US2/US3/US4 Verifications (Phases 5/6/7)** — each depends on US1 implementation being complete. They are READS of the test results; if they fail, the fix is in the implementation, not in the tests.
- **Doc Sync (Phase 8)** — depends on US1 implementation existing so the pattern doc can cite real function names. T022, T024, T025 can run in parallel; T023 (README) is the bigger edit and is sequential within its lane.
- **Polish (Phase 9)** — depends on Phases 1-8 complete.

### Parallel Opportunities

- Phase 2: T003 + T004 + T005 + T006 — all different files.
- Phase 3: every test file is `[P]` (different files); within `test_enrich_stage.py` the four classes touch the same file but can be added incrementally.
- Phase 4: T014 + T017 parallel; T015 sequential after T014; T016 sequential after T015.
- Phase 8: T022 + T024 + T025 parallel.
- Phase 9: T026 + T027 + T028 + T029 parallel; T030 + T031 each sequential.

### User Story Dependencies

- **US1 BEFORE US2, US3, US4**: those stories verify behaviors that the US1 implementation provides for free. If US1 ships correctly, US2/US3/US4 tests pass without additional implementation.
- **US3 (test coverage) BEFORE US1 (implementation)**: per Principle IV, tests precede behavior change.

---

## Implementation Strategy

### MVP First

The MVP is **US1** — produce an enriched corpus from the current accepted corpus, with provenance. US2/US3/US4 are properties of the same implementation, not separate features.

1. Complete Phase 1 (Setup) and Phase 2 (Foundational). Commit.
2. Complete Phase 3 (US1+US2+US3+US4 test files, all red). Commit.
3. Complete Phase 4 (US1 implementation). Commit after each major file (enrich_storage.py, enrich_stage.py, cli.py rewire).
4. Run Phases 5/6/7 verifications (US2 idempotency, US3 invalidation, US4 movement). If anything fails, fix the implementation (Phase 4 had a bug). Commit fixes.
5. Complete Phase 8 (doc sync). Commit.
6. Complete Phase 9 (polish + live smoke run). Commit if any small fixes needed.

### Commit cadence (Principle V)

- Every verified slice gets its own commit with a descriptive message.
- Do NOT batch unrelated phases into one commit.
- Each commit MUST contain only source / docs / tests / specs — never data, caches, exports, or downloaded assets.
- The `.githooks/pre-commit` constitution lint runs automatically on every commit.

### Parallel team strategy

With multiple contributors:
- Contributor A: Phase 2 + Phase 3 test files (T003–T013)
- Contributor B: Once Phase 3 lands, T014 (storage) in parallel with T017 (wrapper); then T015 (orchestrator) → T016 (CLI rewire)
- Contributor C: Phase 8 docs (after Phase 4 is complete enough to cite real function names)

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks.
- `[Story]` label maps task to user story for traceability.
- Tests are written first and MUST fail before implementation begins (Principle IV).
- Commit early and often: each validated slice gets its own descriptive commit; do not batch hours of work into one commit, and push once the requested change is complete unless the requester explicitly says not to (Principle V).
- Commits MUST NOT include data, caches, exports, downloaded assets, or secrets (Principle II). The `.githooks/pre-commit` constitution lint catches the automatable subset.
- Never silence failures or bypass verification gates to make a task look done; surface the error and address the root cause (Principle VI). No `--no-verify`, no skipped tests, no xfail-as-shortcut.
- All Python invocations run through `.venv/bin/python` or `uv` targeting that interpreter (Principle I, FR-013).
- External-state discovery is part of the contract: LLM response schemas validated at parse time; backend availability discovered at runtime (Principle VII, CA-007).
- Provenance record paths are project-relative; no absolute or `~`-prefixed paths reach disk (Principle VIII, CA-008).
