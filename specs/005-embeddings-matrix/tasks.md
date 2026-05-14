---

description: "Task list for Stage 3 — Multi-Model Embeddings Matrix"
---

# Tasks: Stage 3 — Multi-Model Embeddings Matrix

**Input**: Design documents from `specs/005-embeddings-matrix/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Required for every behavior-changing task per CA-002. Each behavior task lists a paired test task that MUST land first and MUST fail before the behavior task starts.

**Organization**: Tasks are grouped by user story (US1–US5 from spec.md). Setup + Foundational phases land first; per-story phases can then run in priority order or in parallel.

## Format: `[ID] [P?] [Story] Description with file path`

- `[P]` = parallelizable (different files, no incomplete dependencies)
- `[USn]` = belongs to user story n; omitted for Setup / Foundational / Polish

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project hygiene and one-time operator steps before any embed run.

- [x] T001 Confirm `.venv/bin/python` is Python 3.14 by running `.venv/bin/python --version` and recording the output in `tmp/stage3_env.txt`; if missing, run `UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv`.
- [x] T002 [P] Add an `[embeddings]` optional extra to `pyproject.toml` covering `voyageai>=0.2`, `sentence-transformers>=2.7`, and `torch>=2.2`; preserve the existing `[enrich]` extra and document the new install in `README.md`'s Stage 3 section.
- [x] T003 [P] Install the new extra into the venv: `uv pip install --python .venv/bin/python ".[embeddings]"`.
- [x] T004 Verify the enriched SQLite exists at `data/primary/abstracts_enriched.sqlite` and its `corpus_metadata` table reports `state_key = f0c51e80dc0e`; record the probe command + output in `specs/005-embeddings-matrix/quickstart.md` if not already captured.
- [x] T005 [P] Create the gitignored archive landing zone `archive/stage3-pre-2026-05-14-legacy-bundles/` and confirm `archive/` is already in the repo's top-level `.gitignore`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Typed exceptions, storage primitives, and component-text assembler that every per-model runner depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T006 Add `Stage3Error`, `EmbeddingError`, `EmbeddingProviderError`, `EmbeddingBudgetError`, `EmbeddingContractError`, `ComponentAssemblyError`, and `EmbeddingThresholdError` to `src/ohbm2026/exceptions.py`; update `__all__`; mirror the tree shape documented in `specs/005-embeddings-matrix/data-model.md` §6.
- [x] T007 [P] Test the exception hierarchy in `tests/test_stage3_exceptions.py`: every Stage 3 typed error MUST subclass `OhbmStageError` and `EmbeddingError`; importing `from ohbm2026.exceptions import EmbeddingError` MUST succeed.
- [x] T008 [P] Create `src/ohbm2026/embed_components.py` exporting `assemble_component(record: dict, component: str) -> str`. Component recipes per `data-model.md` §1: `title` (normalized), `introduction`/`methods`/`results`/`conclusion` (HTML→markdown via existing `enrichment.build_sections_markdown`), `claims` (`\n\n`-joined claim strings), `inference_claims` (claims filtered to `claim_type=="IMPLICIT"`). Pure function; no I/O.
- [x] T009 [P] Test `embed_components.assemble_component` in `tests/test_embed_components.py` with a golden enriched record fixture for each of the 6 components plus `inference_claims`; assert empty result for empty inputs and HTML normalization for the prose components.
- [x] T010 Create `src/ohbm2026/embed_storage.py` with: `_atomic_write_bytes`, `write_cache_entry(cache_path, payload)`, `load_cache_entry(cache_path)`, `write_bundle(bundle_dir, ids, vectors, metadata, provenance)`, `load_bundle(bundle_dir)`. Bundle write MUST write `vectors.npy`, `ids.npy`, `metadata.json`, `provenance.json` in a temp dir then atomically rename; cache write MUST use temp+rename per file. Schemas in `specs/005-embeddings-matrix/contracts/{bundle,cache-entry}.schema.json`.
- [x] T011 [P] Test `embed_storage` round-trips in `tests/test_embed_storage.py`: write a 3-row bundle and a single cache entry, load each back, assert vectors / ids / metadata equal originals. Assert atomic-write contract by simulating mid-write SIGTERM (verify no partial files visible).
- [x] T012 [P] Create `src/ohbm2026/embed_provenance.py` exporting `write_run_provenance(path, payload)` that validates against `contracts/provenance.schema.json` and re-uses Stage 2.1's `_assert_paths_safe` to refuse absolute or `~` paths in any `bundle_path` / `corpus_source_path` / `cache_root` field.
- [x] T013 [P] Test `embed_provenance.write_run_provenance` in `tests/test_embed_provenance.py`: a valid payload writes; payloads with absolute paths or `~` paths raise `ProvenanceError`; payloads missing required fields raise.

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 — Generate canonical per-component embedding matrix (Priority: P1) 🎯 MVP

**Goal**: Operator can run `ohbmcli embed-matrix --models <X> --components <Y>` for one or more `(model, component)` pairs and get a self-contained bundle directory consumable by existing downstream tools.

**Independent Test**: Run the canonical command targeting a single `(model, component)` pair. Verify the bundle directory contains `vectors.npy`, `ids.npy`, `metadata.json`, `provenance.json`; verify `cluster-benchmark` reads it without modification.

### Tests for User Story 1 (write first; MUST fail before implementation)

- [x] T014 [P] [US1] In `tests/test_embed_stage.py`, add a fixture for a 3-abstract synthetic enriched SQLite + a `FakeEmbedClient` that returns deterministic unit vectors. Write `test_single_bundle_clean_run` asserting that a clean run produces a bundle with 3 rows, the correct `metadata.json` shape (matches `bundle.schema.json`), and a sibling `provenance.json`.
- [x] T015 [P] [US1] In `tests/test_embed_stage.py`, add `test_cache_hit_skips_provider`: pre-populate the cache for all 3 abstracts; run the orchestrator and assert `cache_hit_count==3`, `cache_miss_count==0`, `_fake_client.calls == 0`.
- [x] T016 [P] [US1] In `tests/test_embed_stage.py`, add `test_corpus_state_key_mismatch_refuses_overwrite`: write a bundle with `corpus_state_key="OLD"`, then attempt to write the same bundle name with `corpus_state_key="NEW"`; assert exit 7 + typed error + the prior bundle is preserved.

### Implementation for User Story 1

- [x] T017 [P] [US1] Implement `embed_voyage_component(records, component_texts, model_id, ...) -> dict[abstract_id, vector]` in `src/ohbm2026/embed_voyage.py`. Use the existing `neuroscape.voyage_embed` SDK call wrapped with the cache check + write per abstract. Batch size 64.
- [x] T018 [P] [US1] Implement `embed_openai_component(...)` in `src/ohbm2026/embed_openai.py` analogously. Reuse the existing OpenAI client; pass `api_key` in-memory (NEVER via `os.environ`) per CA-004 / Stage 2.1 precedent.
- [x] T019 [P] [US1] Implement `embed_minilm_component(...)` in `src/ohbm2026/embed_minilm.py` via `sentence-transformers`. No HTTP; chunk_mean_pool default for over-length text.
- [x] T020 [P] [US1] Implement `embed_pubmedbert_component(...)` in `src/ohbm2026/embed_pubmedbert.py` (same shape as MiniLM but with `neuml/pubmedbert-base-embeddings`). Reuse a single tokenizer/encoder per pass.
- [x] T021 [US1] Implement `embed_stage.run_single_bundle(model_key, component, args)` in `src/ohbm2026/embed_stage.py`: load enriched SQLite, assemble component text for every abstract, check the cache, dispatch to the correct per-model runner for cache-misses, persist results to the cache, assemble vectors + ids, build metadata, call `embed_storage.write_bundle`. Capture the SDK-reported `model_id` on the first successful response and assert it equals the requested `model_id`; on mismatch raise `EmbeddingContractError` per Principle VII. Depends on T010, T012, T017–T020.
- [x] T022 [US1] Add `_assert_corpus_state_key_compatible(bundle_dir, current_state_key)` to `embed_stage.py` that refuses to overwrite an existing bundle whose `metadata.json["corpus_state_key"]` differs from the active corpus's state_key (FR-013); on refusal raise a typed error and exit 7.
- [x] T023 [US1] Add a per-model `--long-input-strategy` resolver in `embed_stage.py` that defaults `truncate_end` for `voyage` and `openai`, `chunk_mean_pool` for `minilm` and `pubmedbert`, with operator override per `contracts/cli.md`. Record the resolved strategy in `metadata.json`.
- [x] T024 [US1] Create `scripts/run_embed_matrix.py` wrapper that injects `PYTHONPATH=src` and dispatches to `ohbm2026.embed_stage.main`. Mirror `scripts/run_enrich_abstracts.py` for the venv-only execution pattern (Principle I).
- [x] T025 [US1] Wire `ohbmcli embed-matrix` in `src/ohbm2026/cli.py`: register the subparser, copy the existing `embed-voyage` / `embed-openai` / `embed-minilm` flags pattern, dispatch to `embed_stage.main`. Verify `ohbmcli --help` lists the new subcommand.

**Checkpoint**: A single `(model, component)` pair runs end-to-end. The matrix orchestrator (US3) is not yet wired, but US1's bundle output is ready for downstream consumers.

---

## Phase 4: User Story 2 — Resume safely after a partial run (Priority: P1)

**Goal**: An interrupted run resumes from the per-abstract cache without re-calling the provider for completed abstracts; budget-exhausted runs exit cleanly with the cache preserved.

**Independent Test**: Start a 3-abstract synthetic run, kill mid-pass after batch 1 of 2, restart with the same args, verify the second pass makes zero new provider calls for cache-hit abstracts and produces a bundle byte-equivalent (modulo timestamps) to an uninterrupted baseline.

### Tests for User Story 2

- [x] T026 [P] [US2] In `tests/test_embed_stage.py`, add `test_resume_byte_equivalent`: run end-to-end against a `FakeEmbedClient` that raises a SIGTERM-like exception after batch 1; rerun; assert the second run hits cache for the first batch's abstracts and the final `vectors.npy + ids.npy` is byte-equal to a baseline uninterrupted run.
- [x] T027 [P] [US2] In `tests/test_embed_stage.py`, add `test_budget_exhausted_preserves_cache`: have the fake client return HTTP 402 / typed budget-exhausted on batch 2; assert (1) the run exits with code 3, (2) `EmbeddingBudgetError` was raised, (3) batch-1 cache entries persist on disk.

### Implementation for User Story 2

- [x] T028 [US2] Implement `embed_stage._batched_dispatch(provider_key, inputs, model_id, cache_root, ...)` in `embed_stage.py`. Pure helper that: chunks `inputs` into batches of 64, sends each batch via the provider runner (T017–T020), writes per-input cache entries on success, retries on 429/5xx up to 3 attempts, raises `EmbeddingBudgetError` on 402/insufficient-budget responses. Per FR-009a.
- [x] T029 [US2] Implement dynamic concurrency in `embed_stage._concurrent_dispatch(...)` using a `concurrent.futures.ThreadPoolExecutor` for paid providers. Start `max_workers=8`; on observed 429 multiply by 0.5 with floor 1; on 100 consecutive successes ramp toward ceiling 24. Record the curve in the bundle's `metadata.json["concurrency"]` block. Per FR-009b.
- [x] T030 [US2] Implement exit codes per `contracts/cli.md`: 0 / 1 / 2 / 3 / 4 / 5 / 6 / 7 in `embed_stage.main`. Exit 2 if any requested paid provider's API key is missing at startup; exit 3 on `EmbeddingBudgetError`; exit 4 on partial-coverage refusal (FR-007); exit 5 on `EmbeddingThresholdError`; exit 7 on corpus-state-key mismatch.
- [x] T031 [US2] Verify partial cache survival contract in `embed_storage`: a SIGTERM during batch processing MUST never leave a half-written cache file. Use atomic temp+rename per file (already in T010); add a stress test in `tests/test_embed_storage.py:test_signal_during_write_no_partial`.

**Checkpoint**: A real interrupted run resumes correctly. The runner exits cleanly on budget exhaustion and the operator can replay without losing work.

---

## Phase 5: User Story 3 — Matrix orchestration (Priority: P2)

**Goal**: A single command produces (or filters to) the full 30-bundle matrix; identical component texts are assembled once and reused across all models.

**Independent Test**: Run the matrix command with `--models voyage,minilm --components title,claims`; verify 4 bundles are produced, the component-text assembly cost is amortized (assert `embed_components.assemble_component` is invoked once per `(abstract, component)` pair, not 4× per model).

### Tests for User Story 3

- [x] T032 [P] [US3] In `tests/test_embed_matrix.py`, add `test_filtered_matrix_produces_expected_bundles`: request `--models minilm --components title,methods`, run against a synthetic corpus, assert exactly two bundles produced (`minilm_title`, `minilm_methods`) and a single matrix-level provenance record covers both.
- [x] T033 [P] [US3] In `tests/test_embed_matrix.py`, add `test_text_assembly_amortized`: spy on `embed_components.assemble_component`; request 3 models × 2 components against a 5-abstract corpus; assert it's called exactly 10 times (5 abstracts × 2 components), not 30.

### Implementation for User Story 3

- [x] T034 [US3] Implement `embed_stage.run_matrix(args)` in `embed_stage.py`: parse `--models` and `--components` CSVs; pre-assemble component texts for every `(abstract, component)` requested into an in-memory dict (one SQLite pass); loop over `(model, component)` pairs invoking `run_single_bundle`; collect outcomes into a matrix-level provenance record via `embed_provenance.write_run_provenance`.
- [x] T035 [US3] Implement per-bundle JSON-on-stdout in `run_single_bundle` per `contracts/cli.md` (one JSON object per bundle, single line); implement the final matrix rollup JSON in `run_matrix`.
- [x] T036 [US3] Implement state-key composition in `embed_stage._compute_state_key(corpus_state_key, models, components, batch_size, concurrency_policy, long_input_strategies)` matching `research.md` §7; use `artifacts.build_state_key`.
- [x] T037 [US3] Update `ohbmcli embed-matrix` CLI flags in `cli.py` to match every option documented in `contracts/cli.md` (`--models`, `--components`, all the per-model overrides, `--batch-size`, `--concurrency-start`, `--concurrency-max`, `--long-input-strategy`, `--failure-threshold`, `--allow-partial`, `--invalidate`, `--dry-run`, `--env-file`).

**Checkpoint**: The full matrix is producible from one operator invocation; per-bundle and matrix-level summaries land on stdout.

---

## Phase 6: User Story 4 — NeuroScape-over-Voyage derived bundles (Priority: P2)

**Goal**: Apply the published NeuroScape Stage 2 transform to each Voyage component bundle, producing a `neuroscape_<component>` bundle. Deterministic given fixed input + model checkpoint.

**Independent Test**: Given a Voyage bundle for one component, apply the NeuroScape transform; rerun; assert the two output bundles are byte-identical.

### Tests for User Story 4

- [x] T038 [P] [US4] In `tests/test_neuroscape_application.py`, add `test_neuroscape_application_is_deterministic`: invoke the per-component NeuroScape derivation twice on the same synthetic Voyage bundle; assert byte-equality of `vectors.npy`, `ids.npy`, `metadata.json` (modulo `embedded_at`).
- [x] T039 [P] [US4] Add `test_missing_neuroscape_checkpoint_fails_loudly`: run the derivation with the checkpoint path pointing at a missing file; assert a typed `EmbeddingError` is raised naming the missing artifact (Principle VI).

### Implementation for User Story 4

- [x] T040 [US4] Add `embed_stage.run_neuroscape_derivation(voyage_bundle_dir, output_dir)` that wraps the existing `neuroscape.apply_published_stage2` with: a strict checkpoint-existence check (raise typed error if missing), a metadata pass-through that records `upstream_voyage_state_key` + NeuroScape `model_version`, and the bundle-writer call from `embed_storage`.
- [x] T041 [US4] Wire NeuroScape into the matrix orchestrator: when `neuroscape` is in `--models`, run `voyage` first (or use cached Voyage bundle), then derive `neuroscape_<component>` from each Voyage component bundle. Refuse the derivation if the required Voyage component bundle is not present and `voyage` was not also requested.

**Checkpoint**: `neuroscape_*` bundles are produced deterministically from their Voyage upstreams; the UI's `voyage_stage2_published` consumer can be re-pointed at `neuroscape_<recipe-composition>` in Polish.

---

## Phase 7: User Story 5 — Partial-coverage components (Priority: P3)

**Goal**: Components like `inference_claims` (12.3% coverage) cannot produce a full-coverage bundle; the runner refuses by default and produces a `_partial` bundle only with explicit `--allow-partial`.

**Independent Test**: Run `embed-matrix --components inference_claims` without `--allow-partial`; assert exit 1 + a coverage-statistics error message. Then rerun with `--allow-partial inference_claims`; assert a `_partial` bundle is produced with the expected 399-row subset.

### Tests for User Story 5

- [ ] T042 [P] [US5] In `tests/test_embed_matrix.py`, add `test_partial_coverage_refused_by_default`: against a synthetic corpus where only 30% of abstracts have any `inference_claims`, request the bundle without `--allow-partial`; assert exit 1, error message contains "coverage 30%", and no bundle directory is created.
- [ ] T043 [P] [US5] Add `test_allow_partial_produces_suffix_bundle`: rerun with `--allow-partial inference_claims`; assert a `<model>_inference_claims_partial/` directory is created, `metadata.json["present_count"] == 30% of corpus`, `metadata.json["missing_count"] == 70%`.

### Implementation for User Story 5

- [x] T044 [US5] Add coverage-gate check at the start of `run_single_bundle` in `embed_stage.py`: count abstracts where the assembled component text is non-empty; if `present_count < count` AND the component is not in the operator's `--allow-partial` list, raise an `EmbeddingError` with the coverage statistics and exit 1.
- [x] T045 [US5] Implement the `_partial` bundle suffix in `embed_storage.write_bundle`: when the coverage-gate passes via `--allow-partial`, append `_partial` to the bundle directory name; record `partial_coverage_acknowledged: true` in `metadata.json`; emit a warning on stdout naming the missing IDs.

**Checkpoint**: All five user stories are independently functional. Default-matrix run produces 30 bundles; `inference_claims` is opt-in only.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Downstream integration, documentation, validation, and the live Stage 3 run.

- [x] T046 [P] Add `compose_recipe(components, model_key, bundles_root) -> dict` to `src/ohbm2026/neuroscape.py` per `data-model.md` §5. Mean over present components per abstract; abstracts with zero present components excluded.
- [x] T047 [P] Test `neuroscape.compose_recipe` in `tests/test_compose_recipe.py`: against 3 synthetic per-component bundles with overlapping but non-identical id sets, assert the union-id ordering, the per-id mean over present components, and the `present_count_per_id` array.
- [x] T048 Validate SC-004: in `tests/test_compose_recipe.py`, add `test_recipe_matches_direct_embedding_baseline`: for a 50-abstract sample, compare the composed `title+introduction+methods+results+conclusion` MiniLM recipe to a direct full-text MiniLM embedding; assert mean cosine similarity ≥ 0.90.
- [x] T049 Re-point UI export (`src/ohbm2026/ui.py`) at the per-component bundles + `compose_recipe` helper instead of the legacy `voyage_stage2_published` / `minilm_claims` bundle directories. Composition runs in-process at read time — no alias bundle directories are written. The frontend payload format (and the names `voyage_stage2_published` / `minilm_claims` as it appears in the published manifest) stays unchanged from the consumer's perspective.
- [x] T050 [P] Update `README.md`'s Stage 3 section to document the new `ohbmcli embed-matrix` subcommand, the per-component bundle layout, and the composition helper. Update the "Default pipeline state" block to point at the new bundle names + the current `corpus_state_key`.
- [ ] T051 [P] Update `docs/reproducibility-vision.md` with the per-component canonical artifact list. Cross-link to `specs/005-embeddings-matrix/plan.md`.
- [x] T052 Run `.specify/scripts/bash/constitution-check.sh --full` and resolve any reported violations.
- [ ] T053 Audit `src/ohbm2026/embed_*.py` for bare `except:`, silent fallbacks, or `--no-verify`-style bypasses; remediate by surfacing typed errors per the exception tree in T006.
- [x] T054 Verify all new directories under `data/cache/embeddings/`, `data/outputs/experiments/embeddings/`, `data/inputs/` are under existing gitignored roots; confirm no committed data via `git status --short` after a smoke run.
- [x] T055 One-time: move legacy `data/outputs/experiments/embeddings/*` bundles to `archive/stage3-pre-2026-05-14-legacy-bundles/`; record the manifest in `archive/stage3-pre-2026-05-14-legacy-bundles/README.md`.
- [ ] T056 Run the live Stage 3 matrix against the production corpus (`PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py`); verify SC-001 (< 120 min wall-clock), SC-002 (cached re-run < 2 min), SC-003 (resume zero re-calls), SC-004 (composition tolerance), SC-005 (partial gate), SC-006 (truncation telemetry). Capture the run summary + provenance state_key in the commit message.

### Remediation tasks (added from /speckit-analyze)

- [x] T057 [P] [US3] Implement `embed_stage._handle_invalidate(invalidate_keys, cache_root, embeddings_root)` in `src/ohbm2026/embed_stage.py`: for each `<model_key>_<component>` key, delete that subdirectory's cache contents (`data/cache/embeddings/<model_key>/` filtered to entries whose payload's `component` matches), and move any existing bundle directory aside with a `__invalidated_<timestamp>` suffix rather than deleting. Wire into `run_matrix` before the per-bundle loop. (C2)
- [x] T058 [P] [US3] Add `test_invalidate_clears_cache_and_archives_bundle` in `tests/test_embed_matrix.py`: pre-seed a cache entry + a bundle directory for `minilm_title`; invoke the matrix with `--invalidate minilm_title`; assert the cache entry is gone, the bundle is renamed to `minilm_title__invalidated_*`, and the next pass produces a fresh bundle. (C2)
- [x] T059 [P] [US3] Implement `--dry-run` behavior in `embed_stage.run_matrix`: short-circuit before any provider call, emit a single JSON plan summary on stdout (planned bundles, cache-hit / cache-miss counts per bundle, partial-coverage warnings, missing-API-key warnings), exit 0. (C5)
- [x] T060 [P] [US3] Add `test_dry_run_emits_plan_no_provider_calls` in `tests/test_embed_matrix.py`: configure a fake client that raises on any call; run with `--dry-run`; assert the client was never invoked and the plan JSON includes all planned bundle paths. (C5)
- [x] T061 [P] [US2] Add `test_truncation_telemetry_recorded` in `tests/test_embed_stage.py`: with a fake client that flags inputs > N chars as truncated, run `run_single_bundle` against a synthetic corpus that contains over-length text for at least 3 abstracts; assert `metadata.truncated_count == 3`, `len(metadata.truncated_ids) == 3`, and `long_input_params` records the chunk window / truncation point. Covers SC-006 at unit-test granularity. (C3)
- [x] T062 [P] [US1] Add `test_missing_api_key_exits_2_before_provider_call` in `tests/test_embed_stage.py`: invoke `embed_stage.main(['--models', 'voyage', '--components', 'title'])` with `VOYAGE_API_KEY` absent from both `os.environ` and the resolved `.env` payload; assert exit 2, an `EmbeddingError` is raised, and no provider client is constructed. Mirrors Stage 2.1's startup-loud-fail pattern. (C4)
- [x] T063 [P] [US1] Add `test_sdk_reported_model_id_mismatch_raises` in `tests/test_embed_stage.py`: have the fake client return responses tagged with a different `model` than the requested `model_id`; assert `EmbeddingContractError` is raised before bundle write. Verifies Principle VII at unit-test granularity. (CA1)
- [ ] T064 Migrate `src/ohbm2026/neuroscape.py` clustering / UMAP / projection entrypoints (`cluster_benchmark_main`, `umap_main`, `compare_projections_main`) to accept either a per-component bundle directory OR a recipe spec (`title+introduction+methods+results+conclusion` etc.); when a recipe spec is passed, the entrypoint calls `compose_recipe` and treats the in-memory matrix as the input. Update each entrypoint's CLI to document the recipe syntax. (C1)
- [ ] T065 [P] Migrate `scripts/` consumers — `scripts/compare_projections.py`, `scripts/optimize_projections.py`, and the cluster/umap script wrappers — to pass recipe specs where they previously hardcoded multi-component bundle names (`voyage_stage1`, `minilm_claims`, etc.). Each rewritten call MUST go through `compose_recipe` rather than reading a multi-component bundle directly. (C1)
- [ ] T066 [P] Add `tests/test_recipe_consumer_migration.py`: for each migrated consumer (cluster, UMAP, projection), run it end-to-end against a recipe spec produced by `compose_recipe` over per-component bundles and assert it produces the same shape of output it produced from the legacy multi-component bundle (cluster_assignments.json, umap_*.json, projection_comparison_*.json — modulo embedding identifiers and run timestamps). (C1)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories.
- **User Stories (Phases 3–7)**: All depend on Foundational. Once Foundational is done, US1 + US2 are MVP and MUST land before US3/US4/US5.
- **Polish (Phase 8)**: Depends on US1 + US2 + US3 minimum (US4 + US5 land before live run T056).

### User Story Dependencies

- **US1 (P1)** → start after Phase 2. Delivers the per-`(model, component)` bundle.
- **US2 (P1)** → start after Phase 2. Layers resume + dynamic concurrency on US1; T028/T029 need US1's `run_single_bundle` shape, so US2 starts when T021 is in flight.
- **US3 (P2)** → start after US1 + US2; orchestrates them.
- **US4 (P2)** → start after US1 (Voyage runner exists); independent of US2/US3 implementation but consumed by the live-run in T056.
- **US5 (P3)** → start after US1; the gate hooks into `run_single_bundle`.

### Within Each User Story

- Test tasks ([USn]-prefixed ones with `tests/test_*.py` paths) MUST land first and MUST FAIL before the implementation tasks in that story.
- Model layer (T008, T010, T012) → Service layer (T017–T020) → Orchestrator (T021, T034) → CLI wiring (T025, T037).
- Cross-story integration (e.g., NeuroScape derivation reading Voyage bundles) lives in the later story's phase.

### Parallel Opportunities

- **Phase 1**: T002, T003, T005 are independent.
- **Phase 2**: T007, T008, T010, T012 touch different files (`tests/test_stage3_exceptions.py`, `src/ohbm2026/embed_components.py`, `src/ohbm2026/embed_storage.py`, `src/ohbm2026/embed_provenance.py`).
- **US1 tests (T014–T016)**: same test file → sequential.
- **US1 model runners (T017–T020)**: independent files → fully parallel.
- **Polish docs (T050, T051)**: independent files → parallel.

---

## Parallel Example: Foundational phase

```bash
# Four parallel file creations (no shared lines):
Task: "Create src/ohbm2026/embed_components.py and tests/test_embed_components.py"
Task: "Create src/ohbm2026/embed_storage.py and tests/test_embed_storage.py"
Task: "Create src/ohbm2026/embed_provenance.py and tests/test_embed_provenance.py"
Task: "Add Stage 3 exception tree to src/ohbm2026/exceptions.py and tests/test_stage3_exceptions.py"
```

## Parallel Example: US1 model runners

```bash
# Four per-model runners — independent files, no shared state:
Task: "Implement embed_voyage_component in src/ohbm2026/embed_voyage.py"
Task: "Implement embed_openai_component in src/ohbm2026/embed_openai.py"
Task: "Implement embed_minilm_component in src/ohbm2026/embed_minilm.py"
Task: "Implement embed_pubmedbert_component in src/ohbm2026/embed_pubmedbert.py"
```

---

## Implementation Strategy

### MVP first (US1 + US2)

1. Phase 1 (Setup) + Phase 2 (Foundational) — single developer, ~half day.
2. US1 (T014–T025) — single (model, component) bundles working end-to-end.
3. US2 (T026–T031) — resume + budget-exhaustion handling. At this point we can run a one-bundle live test against the production corpus to validate the cache + provider paths.
4. **STOP and VALIDATE** with a one-bundle live run.

### Incremental delivery

1. Setup + Foundational → ready to develop in parallel.
2. US1 → MVP bundle generation.
3. US2 → resume MVP. Commit + push.
4. US3 → matrix orchestrator. Commit + push.
5. US4 → NeuroScape derivation. Commit + push.
6. US5 → partial-coverage gate. Commit + push.
7. Polish (T046–T055) → composition helper + UI re-pointing + docs + audits. Commit + push.
8. T056 → live run.

### Test-first cadence (CA-002)

Within each user story:
- Write the test tasks first; run them; they MUST fail (assert behavior the implementation doesn't yet exist).
- Land each test+implementation pair as a single commit so the test+behavior arrive together with a clean diff.
- Stage 2.1 set the precedent: ~64 targeted tests pass at green; Stage 3 adds ~30 more (~94 total).

---

## Notes

- `[P]` tasks = different files, no incomplete dependencies.
- `[USn]` label maps task to its story for traceability; Setup / Foundational / Polish have no story label.
- Constitution lint (`.specify/scripts/bash/constitution-check.sh --full`) MUST be green before every commit; the pre-commit hook (`.githooks/pre-commit`) enforces this on staged changes.
- No bundles, caches, or provenance files are committed; every new artifact root lands under an existing gitignored path.
- Commit cadence: each verified slice gets a descriptive commit; push at the end of each user story phase.
- Avoid silencing failures or bypassing verification gates to make tasks look done.

---

## Task count summary

| Phase                          | Tasks | of which tests |
|--------------------------------|------:|---------------:|
| Phase 1 (Setup)                | 5     | 0              |
| Phase 2 (Foundational)         | 8     | 3              |
| Phase 3 (US1 — bundle MVP)     | 12    | 3              |
| Phase 4 (US2 — resume)         | 6     | 2              |
| Phase 5 (US3 — matrix)         | 6     | 2              |
| Phase 6 (US4 — NeuroScape)     | 4     | 2              |
| Phase 7 (US5 — partial)        | 4     | 2              |
| Phase 8 (Polish + live run)    | 11    | 2              |
| Remediation (post-analyze)     | 10    | 5              |
| **Total**                      | **66**| **21**         |
