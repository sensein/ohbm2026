---
description: "Task list for spec 019 — NeuroScape Semantic Search"
---

# Tasks: NeuroScape Semantic Search

**Input**: Design documents under `/Users/satra/software/sensein/ohbm2026/specs/019-neuroscape-semantic-search/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Included for every behavior-changing task (FR-021..FR-026, US1-US4) per spec CA-002. Pure rename / doc tasks are unannotated.

**Organization**: Tasks grouped by user story to enable independent implementation + testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4) — REQUIRED for user story phase tasks only
- Setup, Foundational, and Polish phase tasks omit the [Story] label
- Include exact file paths

## Path Conventions

Single-project layout per plan.md §Structure Decision. Python under `src/ohbm2026/`; SvelteKit under `site/src/`; Python tests under `tests/`; browser tests under `site/src/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify dev env + new cache root before any code lands.

- [X] T001 Verify `.venv/bin/python` exists + the `embeddings` extra is installed: `uv pip install --python .venv/bin/python ".[embeddings]"` (sentence-transformers comes with this extra; no new top-level dep) — DONE: sentence-transformers 5.2.3 + joblib 1.5.3 present
- [X] T002 [P] Add the new cache root `data/cache/atlas-vectors/` to the existing `data/` gitignore rule — confirm `data/` already covers it via `git check-ignore data/cache/atlas-vectors/` (no .gitignore edit expected; CA-005 enforcement) — DONE: top-level `data/` rule covers it
- [X] T003 [P] Confirm `site/` has no new browser deps: `pnpm --dir site install` succeeds without lock-file changes (the Xenova transformers + hyparquet libs already used by /ohbm2026/ are sufficient) — DONE: pnpm install clean

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Typed exception subtree + SearchBar parameterisation that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 [P] Add `Stage19SemanticError` base + `EmbeddingComputeError` + `VectorsParquetWriteError` + `VectorsManifestDriftError` subclasses to `src/ohbm2026/exceptions.py` (mirror the Stage15Error subtree pattern; extend Stage15Error so existing Stage-15 catchers see Stage-19 errors too)
- [X] T005 [P] Add typed-exception unit test in `tests/test_atlas_exceptions.py`: every new Stage19SemanticError subclass surfaces (path, reason) kwargs identically to UmapCacheError. Test MUST run + pass after T004. — DONE: 13 tests pass (was 10)
- [X] T006 Parameterise `site/src/lib/components/SearchBar.svelte` so the `id:` autocomplete data source + the placeholder text are corpus-driven props (default values preserve existing `/ohbm2026/` behaviour byte-identically — FR-016 / SC-007 gate) — DONE: corpus + placeholderOverride props added with defaults that preserve OHBM behaviour
- [X] T007 [P] Vitest unit test in `site/src/tests/unit/searchbar_corpus_prop.test.ts`: SearchBar mounted with `corpus="ohbm2026"` produces identical DOM + behaviour to the un-parameterised version (regression gate) — DONE: 6 tests pass (source-string default check + corpus-agnostic filterSuggestions exercise)
- [X] T008 [P] Add `ParsedQuery` type export in `site/src/lib/filter.ts` (alias for the existing parser's return shape) so the ranker contracts at `contracts/search-ranking-pipeline.md` can import it without a fresh type — DONE: `ParsedQuery` already exported at filter.ts:179; contract typo `FilterResult` → `LexicalResult` corrected

**Checkpoint**: Foundation ready — user-story phases can now proceed.

---

## Phase 3: User Story 1 — NeuroScape semantic search (Priority: P1) 🎯 MVP

**Goal**: A user on `/neuroscape/` can enable `✨ Semantic` and find articles by concept-meaning even when their query has no lexical match in any title.

**Independent Test**: Open `/neuroscape/`, type a 3–5 word concept phrase that doesn't appear verbatim in any title, enable `✨ Semantic`, observe at least one `✨`-badged article in the result list within 10 s on broadband.

### Tests for User Story 1 ⚠️

> Write these tests FIRST; ensure they FAIL before implementation tasks T016+.

- [ ] T009 [P] [US1] Build-side byte-identity test in `tests/test_atlas_semantic_index.py`: two `ohbmcli build-atlas-package --semantic-index` runs with pinned timestamps produce sha256-identical `neuroscape_vectors.parquet` (SC-004 mirror of the spec-015 byte-identity contract)
- [ ] T010 [P] [US1] Per-cluster cache hit/miss test in `tests/test_atlas_vectors_compute.py`: first invocation populates `data/cache/atlas-vectors/<state-key>/cluster_<id>.npy`; second invocation with identical inputs reads from cache (R-009)
- [ ] T011 [P] [US1] INT8 round-trip recovery test in `tests/test_atlas_vectors_compute.py`: cosine_recovery_mae of the quantise-then-dequantise vectors against the float32 originals MUST be < 0.005 (parquet-schemas.md §5)
- [ ] T012 [P] [US1] Cluster-centroid table assertion in `tests/test_atlas_orchestrator.py` extension: after `build-atlas-package --semantic-index`, `neuroscape.parquet` carries a `cluster_centroids` table with one row per `cluster_id` on the articles table (INV-001) and `sum(member_count) == n_articles` (INV-002)
- [ ] T013 [P] [US1] Vitest happy-path test in `site/src/tests/unit/neuroscape_ranker.test.ts`: `searchNeuroscape(parsed, topK=5)` returns 5 ranked hits in expected cosine order, given a mocked worker that returns canned scores
- [ ] T014 [P] [US1] Vitest cap test in `site/src/tests/unit/neuroscape_ranker.test.ts`: routing the 5th distinct cluster in one session fires `onCapExceeded` hook + does NOT call `loadClusterVectors` (FR-024)
- [ ] T015 [P] [US1] Vitest drift test in `site/src/tests/unit/neuroscape_ranker.test.ts`: mismatched `model_sha256` between manifest + worker-init payload raises `VectorsManifestDriftError`, surfaces via `onError` hook (R-010 / INV-006)
- [ ] T016 [P] [US1] Playwright e2e in `site/src/tests/e2e/semantic.spec.ts` (NeuroScape section): clear storage → navigate `/neuroscape/` → enable `✨ Semantic` → type "sleep memory consolidation hippocampus" → at least one `✨`-badged result row appears within 10 s. **Additionally** (FR-008): click the `✨`-badged row and assert the detail panel opens with the SAME `data-testid` markers (`detail-panel`, `detail-title`, `detail-abstract`) as a non-semantic row produced by a lexical search.

### Implementation for User Story 1

- [ ] T017 [P] [US1] Implement `src/ohbm2026/atlas_package/vectors_compute.py` — loads `Xenova/all-MiniLM-L6-v2` via sentence-transformers; runs inference in batches over article titles; quantises with `scale = 127.0 / max_abs_original` (single global scale, same as `src/ohbm2026/ui_data/vectors.py:107-110`); per-cluster `.npy` cache under `<semantic_cache_root>/<state-key>/cluster_<id>.npy`; cache state key = `sha256(articles_csv_sha256 || hdf5_shard_manifest_sha256 || model_id || quantization_scheme)[:12]`
- [ ] T018 [P] [US1] Implement `src/ohbm2026/atlas_package/semantic_index.py::write_neuroscape_vectors_parquet(out_path, vectors_by_cluster, scale, model_sha256, manifest_json)` — writes parquet with columns `(cluster_id INT16, pubmed_id INT64, minilm_vector FIXED_LEN_BYTE_ARRAY(384))`; sorts rows by `(cluster_id, pubmed_id)`; uses `row_group_size=8192`; asserts INV-003 before write; raises `VectorsParquetWriteError` on mismatch
- [ ] T019 [US1] Extend `src/ohbm2026/atlas_package/parquet_writer.py::write_neuroscape_parquet` to also emit the `cluster_centroids` table in the same atomic write (columns: `cluster_id INT16, centroid_vector LIST<FLOAT32, 384>, member_count INT32`); centroid is the L2-renormalised mean of the cluster's dequantised INT8 vectors (NOT the float32 mean — see data-model.md §1 build-side invariant)
- [ ] T020 [US1] Wire the semantic-index step into `src/ohbm2026/atlas_package/orchestrator.py` — runs AFTER UMAP, BEFORE the parquet writes; calls `vectors_compute` → `semantic_index.write_neuroscape_vectors_parquet`; populates the centroid input passed to `parquet_writer`; respects `cfg.semantic_index_enabled` (False short-circuits the step + omits the cluster_centroids table)
- [ ] T021 [US1] Extend `src/ohbm2026/atlas_package/cli.py` argparser with `--semantic-index` / `--no-semantic-index` (default `--semantic-index`); `--semantic-cache-root` (default `data/cache/atlas-vectors`); `--semantic-model-id` (default `Xenova/all-MiniLM-L6-v2`); thread the values through to `AtlasBuildConfig`
- [ ] T022 [US1] Add `semantic_index` block to provenance JSON via `src/ohbm2026/atlas_package/provenance.py` — fields per `contracts/cli-build-atlas-package.md §3`; new exit-code map entries 8 / 9 / 10 added to `cli.py`'s `_EXIT_CODES`
- [ ] T023 [P] [US1] Extend `site/src/lib/workers/semantic.worker.ts` to accept the additional message shapes from `contracts/search-ranking-pipeline.md §2`: `init` with `corpus: 'neuroscape'`, `load-cluster`, `evict-cluster`, `route`, `brute-force`, `rerank`; preserves the existing `corpus: 'ohbm2026'` init path byte-identically
- [ ] T024 [US1] Add `loadClusterVectors(clusterId: number, vectorsParquetUrl: string)` to `site/src/lib/data_package/loader.ts` using `asyncBufferFromUrl` from hyparquet + `cluster_id` predicate pushdown (mirror the existing pattern at `loader.ts:683-719` for sibling-drift manifest peek; generalise from "1 KB manifest peek" to "1 cluster row group fetch")
- [ ] T025 [P] [US1] Add `loadClusterCentroids()` helper in `site/src/lib/shards.ts` reading the new `cluster_centroids` table from `data/neuroscape/clusters.json` (the loader's reconstructed envelope)
- [ ] T026 [US1] Implement `site/src/lib/search/neuroscape_ranker.ts` — single new file delivering four orthogonal pieces (the implementing agent MAY land them as separate commits within this task):
  1. **State machine + hooks** (data-model.md §6): `RankerState` enum, `RankerHooks` interface (`onState`, `onCapExceeded`, `onError`), AbortController plumbing so each new keystroke aborts in-flight transitions.
  2. **LRU + cap** (FR-024): `Map<int16, Int8Array>` cluster cache; eviction order = least-recently-used; never evicts the routing cluster of the active query; cap default = 4.
  3. **5-step pipeline orchestrator** (contracts/search-ranking-pipeline.md §3): the `searchNeuroscape` + `searchAtlasRoot` + `expandSearchDepth` public API; the 5-step pipeline from embed → route → range-fetch → top-3 → KNN-expand → re-rank.
  4. **Worker dispatch**: wraps `postMessage`/`onmessage` to/from `site/src/lib/workers/semantic.worker.ts` with transferable `ArrayBuffer` payloads (no main-thread copies).
- [ ] T027 [US1] Extend `site/src/lib/data_package/loader.ts::verifyAtlasSiblingDrift` (currently at line 683) to also cross-check the new INV-006 invariant: `neuroscape.parquet.manifest.expected_model_sha256` matches `neuroscape_vectors.parquet.manifest.model_sha256` matches the worker's loaded-model sha256; raise `VectorsManifestDriftError` on mismatch
- [ ] T028 [US1] Modify `site/src/lib/components/NeuroscapeBrowsePanel.svelte` to mount the shared parameterised `SearchBar.svelte` (replaces the existing slim cluster-and-year-scoped input); wire the `✨ Semantic` toggle to `neuroscape_ranker.searchNeuroscape`; results flow into the existing result list via the same set-difference / ✨-badge logic as `/ohbm2026/`

**Checkpoint**: US1 fully functional — `/neuroscape/` users can enable semantic search + get cluster-routed + KNN-expanded results.

---

## Phase 4: User Story 2 — Loading UX (Priority: P2)

**Goal**: First-time `✨ Semantic` activation surfaces clear loading state; failure modes return the toggle to OFF with a Retry affordance; repeat queries on the same cluster return in < 2 s.

**Independent Test**: Clear browser storage, navigate `/neuroscape/`, enable `✨ Semantic`, type a query → observe loading indicator on toggle + result list until ranking ready (SC-002); kill network mid-fetch → toggle returns to OFF + visible Retry message (FR-006); reload + re-enable → cluster vectors served from Cache API in < 2 s (SC-003).

### Tests for User Story 2 ⚠️

- [ ] T029 [P] [US2] Vitest in `site/src/tests/unit/neuroscape_ranker.test.ts`: the ranker emits states `idle → embedding → routing → fetching-vectors → brute-force → knn-expand → re-rank → ready` in expected order, captured via `hooks.onState`
- [ ] T030 [P] [US2] Vitest in `site/src/tests/unit/neuroscape_ranker.test.ts`: a failed range-fetch (mocked `loadClusterVectors` rejects) transitions ranker to state `error` + `hooks.onError(RangeFetchError)` fires
- [ ] T031 [P] [US2] Playwright e2e in `site/src/tests/e2e/semantic.spec.ts`: clear `localStorage` + `Cache API` → navigate `/neuroscape/` → enable `✨ Semantic` → observe loading affordance on toggle for the duration of the first range-fetch; simulate network failure (Playwright route handler) → toggle returns OFF + Retry button visible
- [ ] T032 [P] [US2] Playwright e2e in `site/src/tests/e2e/semantic.spec.ts`: cold load (`/neuroscape/` first visit) records the time to first ✨-badged hit; repeat query against same cluster after page reload returns within 2 s (SC-003)

### Implementation for User Story 2

- [ ] T033 [US2] Add loading-state indicator to `site/src/lib/components/NeuroscapeBrowsePanel.svelte` — visual spinner on `✨ Semantic` toggle while ranker state is in `loading-model | embedding | routing | fetching-vectors | brute-force | knn-expand | re-rank`; ARIA live-polite on the result list container
- [ ] T034 [US2] Add error-recovery affordance in `site/src/lib/components/NeuroscapeBrowsePanel.svelte` — toggle returns to OFF + a `<div role="alert">` with the error message + a Retry button when ranker state is `error`; Retry re-fires the last query
- [ ] T035 [US2] Add "expand search depth?" affordance triggered by the `onCapExceeded` hook (FR-024) — modal/banner with allow/deny buttons; allow calls `expandSearchDepth()` + re-runs the deferred query

**Checkpoint**: US2 loading UX hardened — first-time + failure + repeat-cache paths all surface visible state.

---

## Phase 5: User Story 4 — Atlas-root cross-conference search (Priority: P2)

**Goal**: Atlas-root gains a search bar that ranks across BOTH corpora in a single merged list, identified by the existing OHBM-vs-NeuroScape source pill. `id:N` matches both corpora in parallel.

**Independent Test**: Navigate atlas-root, type a query with lexical matches in BOTH corpora → both surface in a single ranked list, each row identified by the existing source pill. Enable `✨ Semantic` + type a concept query → semantic results from EITHER corpus appear. Type `id:1234` → if both OHBM `poster_id=1234` and NeuroScape `pubmed_id=1234` exist, both rows surface.

### Tests for User Story 4 ⚠️

- [ ] T036 [P] [US4] OHBM vectors-table assertion test in `tests/test_atlas_parquet_writer.py` (NEW or extension): after `build-atlas-package --semantic-index`, `atlas.parquet` carries an `ohbm_vectors` table with one row per OHBM 2026 accepted abstract (INV-005); same `scale` as `neuroscape_vectors.parquet` (INV-007)
- [ ] T037 [P] [US4] Cross-corpus byte-identity test extension in `tests/test_atlas_orchestrator.py`: two runs with pinned timestamps produce sha256-identical `atlas.parquet` (SC-004 extension)
- [ ] T038 [P] [US4] Vitest in `site/src/tests/unit/neuroscape_ranker.test.ts`: `searchAtlasRoot` kicks both lanes in parallel (verified via `vi.spyOn` on the worker brute-force call + the OHBM brute-force helper); merges results by cosine descending; no source-bias weighting (FR-023)
- [ ] T039 [P] [US4] Vitest in `site/src/tests/unit/neuroscape_ranker.test.ts`: a `ParsedQuery` containing an `id:1234` term short-circuits the semantic pipeline + queries both corpora's id columns in parallel; both matching rows surface in the result (FR-026)
- [ ] T040 [P] [US4] Playwright e2e in `site/src/tests/e2e/semantic.spec.ts`: atlas-root + cross-corpus lexical query → result list shows rows from both corpora, each carrying the existing source pill
- [ ] T041 [P] [US4] Playwright e2e in `site/src/tests/e2e/semantic.spec.ts`: atlas-root + `id:1234` → if both OHBM poster + NeuroScape PMID match, both rows visible; clicking the OHBM row → `/ohbm2026/abstract/1234/`; clicking the NeuroScape row → `/neuroscape/abstract/1234/`

### Implementation for User Story 4

- [ ] T042 [US4] Extend `src/ohbm2026/atlas_package/parquet_writer.py::write_atlas_parquet` to emit the `ohbm_vectors` table (columns: `poster_id INT16, minilm_vector FIXED_LEN_BYTE_ARRAY(384)`); same scale as the NeuroScape vectors parquet (cross-checked via INV-007)
- [ ] T043 [US4] Extend `src/ohbm2026/atlas_package/orchestrator.py` to compute OHBM 2026 vectors via the same `vectors_compute` pathway as NeuroScape — small corpus (~3 240 abstracts); cache key derives from `(ohbm2026_state_key, model_id, quantization_scheme)`
- [ ] T044 [P] [US4] Write `site/src/lib/components/AtlasRootSearchBar.svelte` — thin wrapper around the shared `SearchBar.svelte` with cross-conference `id:` autocomplete (union of poster_id + pubmed_id indexes) + placeholder copy "Search across OHBM 2026 + NeuroScape…"; visual styling per `contracts/atlas-root-search-ui.md §1`
- [ ] T045 [P] [US4] Write `site/src/lib/components/AtlasRootResultList.svelte` — renders the merged `RankedHit[]` from `searchAtlasRoot`; each row uses the existing OHBM-vs-NeuroScape source pill from atlas-root's existing cross-pointers + scatter colour palette (no new badge UX); click navigation per FR-020
- [ ] T046 [US4] Modify `site/src/routes/+page.svelte` (atlas-root mode block guarded by `SITE_MODE === 'atlas-root'`) to mount `<AtlasRootSearchBar />` + `<AtlasRootResultList>` above the existing scatter; the existing overlay toggle stays untouched (FR-019)
- [ ] T047 [US4] Add `bruteForceOhbm(queryVector, topK)` helper in `site/src/lib/search/neuroscape_ranker.ts` (or a sibling `ohbm_ranker.ts`) — in-memory cosine over the eagerly-loaded `ohbm_vectors` table; `searchAtlasRoot` orchestrates this lane in parallel with the NeuroScape lane

**Checkpoint**: US4 atlas-root cross-conference search functional — users can search across both corpora from the root subsite.

---

## Phase 6: User Story 3 — Search-bar parity (Priority: P3)

**Goal**: All three surfaces share the same SearchBar component bytes; operator syntax + UI behaviour is identical across `/ohbm2026/`, `/neuroscape/`, atlas-root.

**Independent Test**: Cross-navigate `/ohbm2026/` → `/neuroscape/` → atlas-root; type the same operator-laden query (`"phrase"`, `-foo`, `word OR word`, `id:N`) on each; observe identical operator parsing + result-list semantics + identical SearchBar position / help-dropdown copy.

### Tests for User Story 3 ⚠️

- [ ] T048 [P] [US3] Vitest in `site/src/tests/unit/searchbar_corpus_prop.test.ts` extension: parameterised SearchBar mounted with `corpus="neuroscape"` + `corpus="atlas-root"` produces identical operator parsing + identical operator help dropdown copy + only the placeholder text + `id:` autocomplete data differ
- [ ] T049 [P] [US3] Playwright e2e in `site/src/tests/e2e/searchbar_parity.spec.ts` (NEW): on each of the three surfaces, type `-fmri` → result list excludes any row whose title contains "fmri"; identical row-exclusion semantics
- [ ] T050 [P] [US3] Playwright e2e in `site/src/tests/e2e/searchbar_parity.spec.ts`: side-by-side screenshot diff of the SearchBar component on all three surfaces — same DOM bytes for the operator help dropdown, same visual padding / position (SC-008 multi-surface variant)
- [ ] T051 [P] [US3] Playwright e2e in `site/src/tests/e2e/searchbar_parity.spec.ts`: `id:1234` typed on `/ohbm2026/` → only OHBM `poster_id=1234` row; same query on `/neuroscape/` → only NeuroScape `pubmed_id=1234` row; same query on atlas-root → both rows (FR-026)

### Implementation for User Story 3

- [ ] T052 [US3] Audit `site/src/lib/components/SearchBar.svelte` help-dropdown copy — confirm all four operator entries (`"phrase"`, `-foo`, `word OR word`, `id:N`) render identically across all three corpus values; remove any OHBM-specific glossary references that don't apply to NeuroScape (e.g. "poster id" → corpus-conditional "poster id" / "PubMed id" / "id"); does NOT change the operator semantics
- [ ] T053 [US3] Verify the `data-testid` selectors on the SearchBar are stable across corpus values (`search-input`, `search-semantic-toggle`); existing OHBM e2e specs MUST NOT need selector changes (regression gate)

**Checkpoint**: US3 parity verified — the three surfaces share one SearchBar component + the user moves between them without surprise.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: README + memory + constitution + final end-to-end gates.

- [ ] T054 [P] Doc: update `README.md` operational runbook with the new `ohbmcli build-atlas-package --semantic-index` block under the existing Stage-15 section
- [ ] T055 [P] Doc: verify the `<!-- SPECKIT START -->` block in `CLAUDE.md` references `specs/019-neuroscape-semantic-search/plan.md` (landed during `/speckit-plan`, NOT via a numbered task; this Polish item is a regression check)
- [ ] T056 [P] Capture the pre-spec-019 baseline for the FR-016 / SC-007 byte-identity gate (consumed by T060): on the merge-base of this branch against `main`, run `PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py --output-format parquet-single --output-dir /tmp/ohbm2026-baseline` and record `sha256sum /tmp/ohbm2026-baseline/ohbm2026.parquet` into `tests/_baseline/ohbm2026_parquet.sha256` (a NEW gitignored path under `tests/_baseline/`). T060 then reads + asserts this value
- [ ] T057 Run `.specify/scripts/bash/constitution-check.sh --full` and address any reported violations (CA-006); confirm pre-commit hook still installs from `.githooks/pre-commit`
- [ ] T058 Run the full Python test suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` — confirm no regressions on existing Stage 15 / 15.4 tests + all new Stage-19 tests pass
- [ ] T059 Run the full browser test suite: `pnpm --dir site test:unit -- --run` (vitest, expect 147 + new = ~165 tests pass); `pnpm --dir site exec playwright test` (e2e, expect existing OHBM suite + new neuroscape + atlas-root + parity cases all pass)
- [ ] T060 Verify `ohbm2026.parquet` bytes are IDENTICAL to the pre-spec-019 baseline (FR-016 / SC-007). Read the sha256 captured by T056 from `tests/_baseline/ohbm2026_parquet.sha256`; rebuild on the current branch via `PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py --output-format parquet-single --output-dir /tmp/ohbm2026-post-spec019`; assert `sha256sum /tmp/ohbm2026-post-spec019/ohbm2026.parquet` equals the baseline value. Mismatch blocks the merge regardless of every other test passing
- [ ] T061 Run `specs/019-neuroscape-semantic-search/quickstart.md` end-to-end against a real local build of the NeuroScape v1.0.1 fixture and confirm every step in §2 through §5 produces the expected outputs (CA-002 / quickstart validation)
- [ ] T062 [P] Verify no new files committed under `data/`, `export/`, `tmp/`, or any other gitignored root — accidental tracking MUST be reverted (CA-005); `git check-ignore` every new path produced by the build step
- [ ] T063 [P] **SC-006 quality gate** — curate the 20-query evaluation set at `data/inputs/semantic-eval/queries.json` (gitignored; format: `[{query: str, relevant_pubmed_ids: int[]}, ...]`). Implement `tests/test_semantic_eval.py` that loads the eval set, runs the cluster-routed ranker against the production `neuroscape_vectors.parquet`, and asserts ≥ 80% of queries have at least one curated relevant article in the top-10 semantic hits. The eval set itself is project-owned (not generated); the test is run manually before each pre-deploy verification, NOT in the per-PR CI (it requires the full 461k-article parquet which CI doesn't have)
- [ ] T064 [P] **SC-005 build-wall-clock gate** — extend `tests/test_atlas_semantic_index.py` (or add `tests/test_semantic_build_perf.py`) to measure the semantic-index step wall-clock under `ohbmcli build-atlas-package --semantic-index` against the synthetic fixture in `tests/_atlas_fixtures.py`. Assert the step's `build_seconds` (recorded in provenance per T022) is below a fixture-scaled threshold (~5 s for the synthetic 6-article fixture; the production gate of <900 s lives in T061's quickstart validation against the real corpus, not in CI)
- [ ] T065 [P] **FR-009 facet-respect gate** — Playwright e2e in `site/src/tests/e2e/semantic.spec.ts`: activate a cluster facet on `/neuroscape/` → enable `✨ Semantic` → confirm the result list contains ONLY rows whose `cluster_id` matches the active facet; semantic-only candidates from clusters OUTSIDE the active facet MUST be filtered from the result list (NOT shown greyed out). Repeat with a year facet active
- [ ] T066 [P] **FR-010 min-char threshold gate** — vitest in `site/src/tests/unit/neuroscape_ranker.test.ts`: assert `searchNeuroscape` with a query shorter than the minimum-character threshold (same value as `/ohbm2026/`'s existing minimum) does NOT call `worker.encode-query` (verified via `vi.spyOn` on the worker postMessage). Same threshold MUST be enforced by `searchAtlasRoot`

---

> **Post-merge follow-up** (NOT a numbered task — out of implementation scope per U3 of the /speckit-analyze remediation): once this branch is merged to `main` and deployed, update the user-level memory inventory at `/Users/satra/.claude/projects/-Users-satra-software-sensein-ohbm2026/memory/MEMORY.md` to flip the "NeuroScape semantic search" entry from Still Relevant → Addressed.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — starts immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories — T006 (SearchBar param) is the gating prereq for US1's mount, US4's wrapper, and US3's verification.
- **US1 (Phase 3, P1)**: Depends on Foundational. Internal order: tests T009-T016 → Python impl T017-T022 → browser impl T023-T028.
- **US2 (Phase 4, P2)**: Depends on US1 (the loading-UX hooks rely on the ranker state machine landing in T026).
- **US4 (Phase 5, P2)**: Depends on US1 (reuses `vectors_compute`, `neuroscape_ranker`'s public API surface) + Foundational T006. Can proceed in PARALLEL with US2 — the two stories touch disjoint files.
- **US3 (Phase 6, P3)**: Depends on US1 + US4 — the parity verification needs BOTH the `/neuroscape/` SearchBar mount AND the atlas-root wrapper to compare against.
- **Polish (Phase 7)**: Depends on all user stories complete.

### User Story Dependencies (visual)

```text
Setup (Phase 1)
  └── Foundational (Phase 2)
        └── US1 [P1]  ─────────────────┐
              │                        │
              ├── US2 [P2] (loading UX)│
              │                        │
              └── US4 [P2] (atlas-root)┤
                                       │
                                       └── US3 [P3] (parity verification)
                                                 │
                                                 └── Polish (Phase 7)
```

### Within Each User Story

- Test tasks ([T009–T016] / [T029–T032] / [T036–T041] / [T048–T051]) MUST be written FIRST and FAIL or be missing before the matching implementation tasks land (Constitution Principle IV, CA-002).
- Within Python: Models / exception subtree → writers → orchestrator wiring → CLI flags → provenance.
- Within browser: Worker contract → loader helpers → ranker orchestrator → component mount.

### Parallel Execution Examples

**Phase 2 (Foundational) — all parallel except T006 → T007**:
- T004 + T005 (Python exceptions + test) and T006 (SearchBar param) and T008 (ParsedQuery export) can ALL run in parallel; T007 runs after T006.

**Phase 3 US1 tests (T009–T016)**:
- All `[P]` — different files, no dependencies. Eight tests in parallel.

**Phase 3 US1 Python implementation (T017–T022)**:
- T017 (vectors_compute.py NEW) and T018 (semantic_index.py NEW) parallel.
- T019 (parquet_writer.py MOD) waits for T017 (needs the per-cluster vectors to compute centroids).
- T020 (orchestrator.py MOD) waits for T017 + T018 + T019.
- T021 (cli.py MOD) waits for T020 (config passes through).
- T022 (provenance.py MOD) parallel with T020 / T021.

**Phase 3 US1 Browser implementation (T023–T028)**:
- T023 (worker.ts MOD) and T024 (loader.ts MOD) parallel.
- T025 (shards.ts MOD) parallel with both.
- T026 (neuroscape_ranker.ts NEW) waits for T023 + T024 + T025.
- T027 (loader drift extension) parallel with T026.
- T028 (NeuroscapeBrowsePanel.svelte MOD) waits for T026.

**Phase 5 US4 — runs in parallel with Phase 4 US2** (disjoint files).

**Phase 6 US3 — all four tests parallel after US1 + US4 land**.

---

## Implementation Strategy

### MVP Scope (Phase 1 → Phase 3 only)

The Minimum Viable Increment is **US1 alone** (Phases 1–3). Shipping just US1 delivers:
- `/neuroscape/` semantic search functional end-to-end.
- Build step + new parquet artefacts in place.
- Browser-side ranker + worker + loader extensions wired.
- The existing `/ohbm2026/` search behaviour byte-identical (FR-016 honoured).

US2 (loading UX) is a hardening pass; US4 (atlas-root) is a NEW surface; US3 (parity) is multi-surface verification. All three are valuable but US1 alone is releasable.

### Incremental Delivery

A reasonable PR cadence on this branch:

1. **PR 1**: Phase 1 + Phase 2 (Setup + Foundational). Small, low-risk; parameterises SearchBar without behaviour change.
2. **PR 2**: Phase 3 US1 (`/neuroscape/` semantic search). Mid-sized; ships the full MVP slice.
3. **PR 3**: Phase 4 US2 (loading UX). Small; tightens the UX around the US1 ranker.
4. **PR 4**: Phase 5 US4 (atlas-root cross-conference). Mid-sized; introduces the new search surface.
5. **PR 5**: Phase 6 US3 + Phase 7 Polish. Small; verification + cleanup.

Each PR ends with `deploy-production` label + the production smoke probe pattern established in PRs #40/41/42/43/44/45/46.

### Risk Notes

- **R-001 (matched-pair invariant)**: model_sha256 drift is the single highest-risk failure mode. T015 + T027 both gate on it.
- **R-006 (range-fetch wiring)**: hyparquet `asyncBufferFromUrl` precedent exists at one site (`loader.ts:683`); T024 generalises it. Mid-risk.
- **R-007 (in-memory candidate set)**: FR-024 cluster-cap + KNN-distance fallback is novel UX; the T031 + T035 test pair specifies the contract.
- **SC-007 (`ohbm2026.parquet` byte-identity)**: T060 is the gate. A regression here blocks the merge regardless of every other test passing.

---

## Format Validation

All 66 tasks above follow the strict checklist format: `- [ ] T<NNN> [P?] [Story?] <description with file path>`.
- Checkbox: ✓ every task starts with `- [ ]`
- Sequential ID: T001 → T066, monotonically increasing in execution order
- [P] marker: present where the task is parallelizable (~70%)
- [Story] label: present on every user-story-phase task (US1 / US2 / US3 / US4), absent on Setup / Foundational / Polish per format rules
- File paths: every implementation task names the absolute file; every test task names the test file; doc / verification tasks name the command or paths to inspect

**Phase distribution** (post-analyze remediation): Setup 3 · Foundational 5 · US1 P1 (MVP) 20 · US2 P2 7 · US4 P2 12 · US3 P3 6 · Polish 13 (was 9; +4 new gates T063–T066). Total 66.
