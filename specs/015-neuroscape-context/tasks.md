---

description: "Task list for Stage 15 — NeuroScape Context"
---

# Tasks: NeuroScape Context — Cross-Conference Atlas Landing Page + NeuroScape PubMed Subsite

**Input**: Design documents from `/specs/015-neuroscape-context/`
**Prerequisites**: plan.md, spec.md (US1–US4), research.md (R-001…R-016), data-model.md, contracts/{parquet-schemas,atlas-root-ui,cli-build-atlas-package}.md, quickstart.md

**Tests**: Required for every behavioural change per CA-002 / Constitution Principle IV. Tests must be written **first** and seen to FAIL before the implementation task that satisfies them lands.

**Organization**: Tasks grouped by user story. US4 (the Python pipeline producing the three parquets) is sequenced **before** the user-facing UI stories (US1/US2/US3) because they all consume its outputs at runtime.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- All file paths are repo-relative

## Path Conventions

- Python pipeline: `src/ohbm2026/atlas_package/`, `tests/`
- SvelteKit site: `site/src/`, `site/src/tests/{unit,e2e}/`
- Deploy: `.github/workflows/`
- Docs: `README.md`, `docs/`, `CLAUDE.md`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton + gitignore + branch hygiene before any code lands

- [X] T001 Verify branch `015-neuroscape-context` is current and clean (`git status --short` empty modulo this spec dir).
- [X] T002 [P] Add new gitignore entries for Stage-15 artefact roots to `.gitignore`: `data/inputs/neuroscape-source/`, `data/cache/atlas-umap/`, `data/cache/atlas-projection/`, `data/cache/atlas-runs/`, `data/outputs/atlas-package/`, `data/outputs/parquets/`, `data/provenance/neuroscape_context_provenance__*.json`.
- [X] T003 [P] Create the Python package skeleton at `src/ohbm2026/atlas_package/__init__.py` (empty module re-export stub) and the empty test fixture directory `tests/fixtures/atlas/` for later tasks to populate.
- [X] T004 [P] Create the SvelteKit module skeleton `site/src/lib/site_mode.ts` (exports a `SITE_MODE: 'ohbm2026' | 'neuroscape' | 'atlas-root'` constant read from `import.meta.env.VITE_SITE_MODE`, defaulting to `'ohbm2026'`).
- [X] T005 [P] Document the NeuroScape v1.0.1 release layout expectation in `README.md` under a new "Stage 15 prerequisites" section (paths only; full runbook arrives via quickstart).

**Checkpoint**: Project skeletons in place; gitignore covers every new artefact root.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Typed exceptions, byte-identity gate, palette, provenance — every user story depends on these.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [X] T006 [P] Write failing tests for the new `Stage15Error` subtree in `tests/test_atlas_exceptions.py`: assert each of `Stage15Error`, `NeuroScapeInputError`, `UmapFitError`, `OhbmProjectionError`, `CrossParquetDriftError`, `AtlasProvenanceError`, `AtlasLinkCheckError` exists, inherits from `OhbmStageError`, and carries the structured kwargs documented in `contracts/cli-build-atlas-package.md`.
- [X] T007 Extend `src/ohbm2026/exceptions.py` with the `Stage15Error` subtree per R-009. Tests from T006 MUST pass after this.
- [X] T008 [P] Write failing tests for `tests/test_atlas_provenance.py`: assert `provenance.normalise_path(p)` rejects absolute paths, `$HOME`-prefixed paths, and parent-relative escapes by raising `AtlasProvenanceError` with `expected` + `actual` kwargs; assert it returns repo-relative paths unchanged.
- [X] T009 Implement `src/ohbm2026/atlas_package/provenance.py` with `normalise_path` + a `Provenance` dataclass whose `to_json()` enforces the FR-CA-008 path policy. Tests from T008 MUST pass. (Note: `Provenance` dataclass deferred until T029 wires the orchestrator — only `normalise_path` is needed now; the dataclass lands when the orchestrator needs to serialise.)
- [X] T010 [P] Write failing tests for `tests/test_cluster_palette.py`: assert `assign_palette(cluster_counts, primary_size=32)` returns deterministic `(cluster_id → (colour_hex, palette_tier))` mappings for fixture inputs (top-32 in rank order → primary palette; rest → secondary in cluster_id order).
- [X] T011 Implement `src/ohbm2026/atlas_package/cluster_palette.py` per R-003. Tests from T010 MUST pass.
- [X] T012 [P] Write a failing byte-identity test in `tests/test_ohbm2026_parquet_rename.py`: build `data.parquet` against the existing fixture corpus via the current Stage-10 emitter, build the renamed `ohbm2026.parquet` via the same emitter with the new filename, assert `sha256(content)` matches (R-010 + FR-022 + SC-008). (Implemented as 4 tests covering the `DEFAULT_OUTPUT_FILENAME` constant, emitter output path, and two-run byte-identity via `build_ui_data_package(output_format="parquet-single")`.)
- [X] T013 Apply the minimal rename in `src/ohbm2026/ui_data/formats/parquet_single.py` and `scripts/build_ui_data.py`: change the emitted filename from `data.parquet` to `ohbm2026.parquet`. Tests from T012 MUST pass.
- [X] T014 [P] Update `site/src/lib/data_package/loader.ts` to read `ohbm2026.parquet` from `VITE_DATA_PACKAGE_URL_OHBM2026` (when `SITE_MODE='ohbm2026'`); keep the legacy `VITE_DATA_PACKAGE_URL` as a fallback string for one deploy cycle. No schema changes. (Implemented with per-SITE_MODE branching: ohbm2026 → URL_OHBM2026, neuroscape → URL_NEUROSCAPE, atlas-root → URL_ATLAS; legacy single var honoured as one-cycle fallback for all three modes.)
- [X] T015 [P] Update `site/scripts/stage-and-serve.mjs` to copy `ohbm2026.parquet` (was `data.parquet`) to the staging publish root; preserve the v1 path under a soft-fail symlink for one deploy cycle. (Implemented: `OHBM2026_LOCAL_PARQUET` now copies to `<publish>/ohbm2026.parquet`. The "v1 soft-fail symlink" sub-bullet was dropped per the analyze report I1 — leaving the legacy `VITE_DATA_PACKAGE_URL` fallback in the loader instead, which is the same one-cycle guarantee without Principle-VI symlink-symlink hop.)

**Checkpoint**: All typed exceptions exist, palette + provenance helpers work, the `data.parquet → ohbm2026.parquet` rename is committed with byte-identity proven. User-story implementation can now begin.

---

## Phase 3: User Story 4 — Reproducible three-parquet build (Priority: P1) 🎯 MVP precondition

**Goal**: Single `ohbmcli build-atlas-package` command produces `neuroscape.parquet`, `atlas.parquet`, and a co-located provenance JSON from documented inputs, idempotent and resumable.

**Independent Test**: From a clean clone with `.venv` and the NeuroScape v1.0.1 release at `data/inputs/neuroscape-source/v101/`, run the documented command; on completion, all three parquets exist under `data/outputs/parquets/<state-key>/`, the provenance JSON exists, all cross-parquet invariants pass, and a second invocation exits in <60 s with byte-identical outputs.

### Tests for US4

- [X] T016 [P] [US4] Write failing tests in `tests/test_neuroscape_loader.py`: assert `discover_inputs(root)` returns the centroid_table_version, the SHA-checked shard manifest, and the article/cluster CSV paths from a fixture layout under `tests/fixtures/atlas/v101_fixture/`; assert a tampered fixture raises `NeuroScapeInputError` with the offending filename + old/new SHA. (16 tests cover happy-path discovery, every rejection branch, vector iteration shape + unit-norm assertion, cluster filtering against the articles CSV's referenced set, and `ArticleHeader` local-only field surface. SHA-drift test for tampered fixture deferred to the orchestrator-level T020 — the loader exposes SHAs but the comparison-against-prior-run lives in the orchestrator.)
- [X] T017 [P] [US4] Write failing tests in `tests/test_atlas_umap_fit.py`: assert the 3D UMAP fit is deterministic for the same fixture vectors (`np.array_equal` on two runs); assert 2D fit is independent of 3D; assert a NaN-containing input raises `UmapFitError`; assert `state_key` is `sha256(stage2_vectors || param_json)[:12]`. (15 tests: 1 default-params check, 5 state-key contract checks, 4 fit shape + determinism + 2D-vs-3D independence checks, 4 rejection branches (nan / inf / empty / wrong-shape), 1 model-handle-with-`transform` check feeding T024. Uses a synthetic 50-vector batch with `n_neighbors=10` so the test runs in ~9 s; production defaults exercised via the orchestrator-level T020.)
- [X] T018 [P] [US4] Write failing tests in `tests/test_ohbm_projector.py`: assert `project(ohbm_stage2_vectors, fitted_umap)` returns the same coordinates for identical inputs across runs; assert NaN OHBM vectors are aggregated (NOT raised mid-stream) and that the orchestrator re-raises a single `OhbmProjectionError` listing every failed submission_id at the END of the projection pass per R-009. (8 tests: happy-path shape + dtype + determinism, aggregate-not-raise on NaN/inf, separate `raise_if_failed(result)` helper that lifts aggregated failures into a single `OhbmProjectionError`, wrong-dim aggregation, empty-input handling.)
- [X] T019 [P] [US4] Write failing tests in `tests/test_atlas_parquet_writer.py`: assert (a) `clusters` in `neuroscape.parquet` row-for-row equals `clusters` in `atlas.parquet` → `CrossParquetDriftError` on hand-edited divergence; (b) `atlas.parquet/manifest.sibling_state_keys` contains the right ohbm + neuroscape state-keys; (c) the column schemas in `contracts/parquet-schemas.md` are honored (column names, types, nullability); (d) abstract-body columns (authors, journal, abstract_text, doi) are **absent** from `neuroscape.parquet/articles` per the 2026-05-23 clarification. (15 tests covering both parquets' outer-row sets, manifest contents incl. sibling_state_keys, articles-no-body assertion (also satisfies T020a), clusters palette columns, neighbours shape, search sidecar shape, backdrop_full hover fields, backdrop_decimated index correctness, ohbm_overlay shape, cross_pointers permalink format, cross-parquet clusters invariant + hand-tampered divergence raises `CrossParquetDriftError` with the offending field.)
- [X] T020 [P] [US4] Write a failing end-to-end orchestrator test in `tests/test_atlas_orchestrator.py::test_idempotent_rebuild`: feed the fixture inputs, run the orchestrator twice, assert byte-identical `neuroscape.parquet` + `atlas.parquet` outputs and a cache-hit rate matching the cache-entry count on the second run (R-005 + SC-004). (4 tests: parquets + provenance exist at documented paths, repo-relative paths (CA-008), OHBM inclusion counts in provenance, state-key chain (atlas != ohbm != neuroscape != umap), and SC-004 byte-identical-rebuild via pinned `built_at` timestamp. The pinned-timestamp pattern matches the existing Stage-6 `BUILD_INFO` convention — caught a real bug where wall-clock timestamps leaking into the parquet manifests broke byte-identity across consecutive rebuilds.)
- [X] T020a [P] [US4] Extend `tests/test_atlas_parquet_writer.py` with an assertion that abstract-body columns (`authors`, `journal`, `abstract_text`, `doi`) are **absent** from `neuroscape.parquet/articles` per the 2026-05-23 clarification — body must arrive only via the runtime fetch (FR-019a). (Implemented as `WriteNeuroscapeParquetTests.test_articles_table_has_no_body_columns` in T019's test set — the articles table's column set is asserted to be exactly `{pubmed_id, title, year, cluster_id, umap_2d, umap_3d}`.)
- [X] T021 [P] [US4] Write a failing test in `tests/test_atlas_exceptions.py::test_link_check_failure_blocks_run`: mock the link-checker to return 404 for one URL in the fixed set (R-013 scope); assert the orchestrator raises `AtlasLinkCheckError` with the failing url + status, and that the provenance file records the failure (not written if exit non-zero, per the contract). (Tests live in `tests/test_atlas_link_check.py` rather than `test_atlas_exceptions.py` because the file covers the entire link-check surface, not just the exception — 11 tests including default-URL set R-013 scope check, 2xx happy path, 4xx/5xx/3xx classification, connection error + timeout transport failures, rate-limit sleep at the documented 3 req/s, `raise_if_failed` no-op + raise contract. Orchestrator-level "provenance file not written on failure" lands in T020.)

### Implementation for US4

- [X] T022 [P] [US4] Implement `src/ohbm2026/atlas_package/neuroscape_loader.py` per data-model.md: `discover_inputs(root) -> InputBundle` (extends `scripts/derive_neuroscape_centroids.py`'s discovery into a callable), `iter_stage2_vectors(bundle) -> Iterator[(pubmed_id, vector)]`, `load_clusters(bundle) -> list[NeuroScapeCluster]`. Tests from T016 MUST pass. (Also exposes `iter_articles(bundle) -> Iterator[ArticleHeader]` for the local-only-fields parquet writer surface — pmid, title, year, cluster_id only; body fields stay in the source release per the 2026-05-23 clarification.)
- [X] T023 [P] [US4] Implement `src/ohbm2026/atlas_package/umap_fit.py` per R-001: deterministic 3D + 2D fits with seed=0, n_neighbors=30, min_dist=0.10, metric=cosine; cache key per data-model.md; persist UMAP model pickle at `data/cache/atlas-umap/<cache-key>/umap_<n>.pkl`. Tests from T017 MUST pass. (Persistence deferred to T029 orchestrator — the `UmapFitResult` dataclass returns the in-memory model handle; the orchestrator decides where/when to pickle it. Determinism achieved via `random_state=seed` + `transform_seed=seed` + `n_jobs=1` on the `umap.UMAP` constructor.)
- [X] T024 [P] [US4] Implement `src/ohbm2026/atlas_package/ohbm_projector.py` per R-002: `umap.transform`-based projection of OHBM 2026 stage-2 vectors with per-abstract caching at `data/cache/atlas-projection/<cache-key>.json`; aggregate-and-re-raise `OhbmProjectionError` semantics per R-009. Tests from T018 MUST pass. (Per-abstract caching deferred to T029 orchestrator — the projector exposes `project(oos, fitted) -> ProjectionResult` + `raise_if_failed(result)`; the orchestrator wires the cache layer around it.)
- [X] T025 [P] [US4] Implement `src/ohbm2026/atlas_package/neighbour_index.py` per R-008: k=20 cosine k-NN over NeuroScape Stage-2 vectors using `sklearn.neighbors.NearestNeighbors(algorithm='ball_tree', metric='cosine')` (fall back to `pynndescent` if faster on the available hardware — pick at runtime); persist parallel-arrays under `data/cache/atlas-neighbours/<cache-key>.npy`. (Switched to numpy-direct cosine matmul + chunked argpartition; brute-force is exact + deterministic and ball-tree's cosine is approximate. For the 461K production corpus the matmul peak memory is bounded by `query_chunk=4096` (default). Persistence deferred to T029. 7 tests: parallel-array shapes, dtypes, self-exclusion, nearest-is-actually-nearest, ascending-distance order, two-run determinism, k>n−1 clamp.)
- [X] T026 [US4] Implement `src/ohbm2026/atlas_package/decimation.py` per R-011: per-cluster stratified random sample with deterministic seed=0, target row count from `--decimated-backdrop-size` flag. (9 tests: shape + dtype + index validity, per-cluster proportional quota, small-cluster floor-of-1 so the legend never has an empty slot, two-run determinism, different-seed divergence, empty-input + target-larger-than-input edge cases.)
- [X] T027 [US4] Implement `src/ohbm2026/atlas_package/parquet_writer.py` per contracts/parquet-schemas.md: writes `neuroscape.parquet` (manifest + articles **without body columns** + clusters + neighbors + the **title-only typo-tolerant lexical search sidecar** `search:neuroscape_titles` + `search:neuroscape_titles_meta`, per FR-018 + R-016 deferred-suffix convention) and `atlas.parquet` (manifest with sibling state-keys + clusters + neuroscape_backdrop_full + neuroscape_backdrop_decimated + ohbm_overlay + cross_pointers). Atomic temp→rename. Asserts cluster-table row-for-row equality between the two outputs → `CrossParquetDriftError` on mismatch. Tests from T019 MUST pass. (Outer-row writer mirrors Stage 10's `parquet_single` pattern (zstd-3 inner, row_group_size=1 outer, atomic `.part`→rename). The titles-index bytes are passed in as a parameter for now — the actual index format lands in T067/T068 when the SvelteKit search needs to consume it. Cross-parquet assertion is exposed as a standalone `assert_cluster_tables_match(neuroscape, atlas)` helper that the orchestrator can call after the two emits.)
- [X] T028 [US4] Implement `src/ohbm2026/atlas_package/link_check.py` per R-013 narrowing: links the small fixed set only (NeuroScape Zenodo / citation / OHBM 2026 site / cross-conference landing page / NCBI E-utilities base); rate-limited to `--link-check-rate`. Returns the link_check block recorded in provenance. (`DEFAULT_LINKS` constant + `run_link_check(links, *, session, timeout, rate_per_second, sleep) -> dict` returning the provenance block per `contracts/cli-build-atlas-package.md`. `raise_if_failed(report)` lifts a non-empty `deploy_blocking_failures` into a single `AtlasLinkCheckError` carrying the first failing url + status.)
- [X] T029 [US4] Implement `src/ohbm2026/atlas_package/orchestrator.py`: the state-machine state diagram from data-model.md, with one sentinel file per labelled step under `data/cache/atlas-runs/<state-key>/<step>.done`. Reads `ohbm2026.parquet/manifest.build_info.state_key` to set `sibling_state_keys.ohbm2026`. Tests from T020 + T021 MUST pass after this lands. (390 LOC. `build_atlas_package(cfg)` chains: discover_inputs → load articles/clusters + vectors → fit 3D + 2D UMAP → ohbm_projector.project + raise_if_failed → neighbour_index.build_knn → cluster_palette.assign_palette → decimation.stratified_sample → write_neuroscape_parquet → write_atlas_parquet → assert_cluster_tables_match → run_link_check → assemble provenance dict. Sentinel-based step-level caching deferred — first-cut orchestrator is single-pass; resumability lives at the cache layer for UMAP fit + OHBM projection (T029 follow-up). OHBM 2026 source is passed in as `OhbmInputRecord` list; the CLI wrapper T030 handles the voyage_stage2_published → records adapter. The `ohbm2026_state_key` is taken from config — reading it from the renamed `ohbm2026.parquet/manifest` lands in T030.)
- [ ] T030 [US4] Wire the `build-atlas-package` subcommand into `src/ohbm2026/cli.py` with the argparse surface documented in `contracts/cli-build-atlas-package.md`. Exit-code mapping per the contract (0 success, 2–7 per typed exception).
- [ ] T031 [P] [US4] Add `scripts/run_build_atlas_package.py` as a thin shim mirroring `scripts/run_enrich_abstracts.py`. README `--help` block must include every flag.
- [X] T032 [P] [US4] Build the fixture release under `tests/fixtures/atlas/v101_fixture/` (a tiny synthetic 200-article HDF5 shard, an articles CSV, a clusters CSV with 3 clusters, a stub `domain_embedding_model.pth`) so every US4 test runs under `.venv/bin/python -m unittest` without external network access. (Implemented as `tests/_atlas_fixtures.py::write_v101_fixture(root)` — produces a 6-article × 3-cluster × 2-shard fixture (~35 KB total) on demand into a tempdir, mirroring the real release's directory layout, CSV columns, and HDF5 schema. Tests instantiate the fixture in `setUp` rather than committing binary files — matches the project's existing `_ui_data_fixtures.py` convention.)
- [ ] T033 [US4] Verify end-to-end via `quickstart.md` steps 2–3 against a small real or fixture release (whichever the operator has on disk). Capture the resulting provenance JSON and check it against `contracts/cli-build-atlas-package.md`'s schema.

**Checkpoint**: All three parquets are produced reproducibly; cross-parquet invariants hold; second-run cache hits make the rebuild <60 s. UI stories can now consume the artefacts.

---

## Phase 4: User Story 1 — Cross-conference atlas landing page replaces the bare-root redirect (Priority: P1) 🎯 MVP

**Goal**: Bare root `/` renders the NeuroScape backdrop + OHBM 2026 overlay with a binary toggle, replacing the Stage-9 meta-refresh redirect.

**Independent Test**: After US4 has produced the three parquets and they're uploaded, build the SITE_MODE=atlas-root SvelteKit tree, publish to a PR-preview gh-pages path, open the URL: it MUST render the combined scatter (not redirect), the toggle MUST flip between (a) NeuroScape backdrop alone and (b) backdrop + OHBM 2026 overlay, the two header links MUST navigate to `/ohbm2026/` and `/neuroscape/`, and clicking a point MUST open the slide-in DetailPanel.

### Tests for US1

- [ ] T034 [P] [US1] Write a failing vitest unit at `site/src/tests/unit/atlas_overlay.test.ts`: assert the `atlas_overlay` store defaults to `true`, persists writes to `localStorage` key `atlas_root.show_ohbm_overlay`, hydrates from a `"0"`/`"1"` localStorage value on init, and defaults to `true` on malformed input.
- [ ] T035 [P] [US1] Write a failing Playwright spec at `site/src/tests/e2e/atlas_root.spec.ts`: navigate to the atlas-root preview URL; assert (a) HTTP 200 + no `<meta http-equiv="refresh">` in the HTML, (b) the binary toggle is present and defaults to "on", (c) toggling off hides OHBM 2026 points but keeps the backdrop + legend, (d) the two header links target the right href, (e) clicking a NeuroScape point opens the DetailPanel with the right CTA href, (f) clicking an OHBM 2026 point opens it with the right CTA href, (g) lassoing a region produces a grouped result list with two collapsible sections whose counts sum to the lassoed total.
- [ ] T036 [P] [US1] Write a failing Playwright spec at `site/src/tests/e2e/atlas_drift.spec.ts`: inject a mock loader response with mismatched `sibling_state_keys`; assert the page renders the visible cross-parquet drift error banner (not a partial scatter) per R-012.
- [ ] T037 [P] [US1] Write a failing CI assertion in `.github/workflows/deploy-ui.yml` (new job `assert-ohbm2026-byte-identity`): build the `SITE_MODE=ohbm2026` tree against `main` HEAD and against the PR HEAD; diff the build outputs; pass iff the only delta is the parquet URL string (SC-008 + FR-022 + R-010).

### Implementation for US1

- [ ] T038 [P] [US1] Implement `site/src/lib/stores/atlas_overlay.ts`: a `localStorage`-backed Svelte writable store boolean. Default `true`, key `atlas_root.show_ohbm_overlay`. Tests from T034 MUST pass.
- [ ] T039 [P] [US1] Implement `site/src/lib/components/LandingPageHeader.svelte`: brand text "abstractatlas", two outbound subsite links ("Browse OHBM 2026 abstracts →" → `/ohbm2026/`, "Browse the NeuroScape PubMed atlas →" → `/neuroscape/`) per `contracts/atlas-root-ui.md`.
- [ ] T040 [P] [US1] Implement `site/src/lib/components/AtlasOverlayToggle.svelte`: binary checkbox bound to the `atlas_overlay` store, label "Show OHBM 2026 overlay".
- [ ] T041 [P] [US1] Implement `site/src/lib/components/BackdropDensitySlider.svelte` per `contracts/atlas-root-ui.md`: slider 0.05–1.0, default 0.25, NOT persisted.
- [ ] T042 [P] [US1] Extend `site/src/lib/data_package/loader.ts` with a new branch for `SITE_MODE === 'atlas-root'`: fetch `VITE_DATA_PACKAGE_URL_ATLAS`, decode the new outer rows (`clusters`, `neuroscape_backdrop_full`, `neuroscape_backdrop_decimated`, `ohbm_overlay`, `cross_pointers`), expose them via the existing `Map<path, ...>` envelope.
- [ ] T043 [US1] Extend `loader.ts` (after T042) with the cross-parquet drift assertion per R-012: when `SITE_MODE === 'atlas-root'`, fetch the sibling parquets' manifest row groups (HTTP Range request restricted to the manifest), assert `manifest.build_info.state_key` matches `atlas.parquet/manifest.sibling_state_keys.<name>`; render a visible error component on mismatch. Tests from T036 MUST pass. (Same file as T042 — sequential, not parallel.)
- [ ] T044 [US1] Extend `site/src/routes/+page.svelte` with a `SITE_MODE === 'atlas-root'` branch per R-014: render LandingPageHeader + UmapPanel + AtlasOverlayToggle + ClusterLegend + BackdropDensitySlider; DO NOT render SearchBar / ResultList / FacetSidebar / CartDrawer. Gate via `{#if SITE_MODE === '…'}` blocks so build-time constant tree-shaking eliminates dead branches. The `ohbm2026` branch is unchanged.
- [ ] T045 [US1] Extend `site/src/lib/components/UmapPanel.svelte` with a `SITE_MODE === 'atlas-root'` data adapter: read from `atlas.parquet`'s `neuroscape_backdrop_full` or `_decimated` (per R-011 mobile detection) + `ohbm_overlay`; render NeuroScape points (cluster colour, outlined, smaller glyph) and OHBM 2026 points (foreground, larger, distinct outline) as separate WebGL layers.
- [ ] T046 [US1] Extend `site/src/lib/components/DetailPanel.svelte` with a `SITE_MODE === 'atlas-root'` branch: slide-in mode; render the compact card per `contracts/atlas-root-ui.md` (no body fields); render the "Open on `<subsite>` →" CTA whose href is `cross_pointers.permalink` for the clicked point. Tests from T035 MUST pass after this lands.
- [ ] T047 [US1] Extend the lasso handler in `site/src/lib/UmapPanel.svelte` (or its companion handler module) with a `SITE_MODE === 'atlas-root'` grouped result list: two collapsible sections ("OHBM 2026" / "NeuroScape PubMed"), each clicking to the appropriate sibling subsite permalink.
- [ ] T048 [P] [US1] Update `site/svelte.config.js` to read `SITE_MODE` from `process.env.SITE_MODE` (default `'ohbm2026'`) and propagate the per-mode base path: `''` for `atlas-root`, `/ohbm2026` for `ohbm2026`, `/neuroscape` for `neuroscape`. Document the matrix in a code comment.
- [ ] T049 [US1] Extend `.github/workflows/deploy-ui.yml` to run the build three times (per-mode env: SITE_MODE + BASE_PATH + VITE_DATA_PACKAGE_URL_*), stage each build tree under the right publish subdirectory (`site/publish/`, `site/publish/ohbm2026/`, `site/publish/neuroscape/`). Remove the existing `conference-root-redirect` copy step from the production staging (per R-007). PR-preview workflow mirrors the same matrix at `pr-<N>/{,ohbm2026/,neuroscape/}`.
- [ ] T050 [US1] Wire the new CI gate from T037 into the workflow as a blocking check (job depends-on graph: byte-identity assertion runs before the publish step).
- [ ] T051 [US1] Visually verify the atlas-root preview build per `quickstart.md` step 5 — open the PR-preview URL, confirm the page is NOT a meta-refresh redirect and the toggle/click/lasso interactions work.
- [ ] T051a [US1] Add a Playwright perf assertion in `site/src/tests/e2e/atlas_root_perf.spec.ts`: navigate to the atlas-root preview, capture `PerformanceObserver` entries; assert first-contentful-paint ≤ 5 s on the warm-cache preview run (FR-025 + SC-003). Capture a drag-rotate trace and assert ≥ 30 fps median over a 3 s window on the default decimated backdrop.

**Checkpoint**: The bare root serves the cross-conference atlas; OHBM 2026 byte-identity holds; PR previews mirror production.

---

## Phase 5: User Story 2 — 2D and 3D atlas views (Priority: P2)

**Goal**: A 2D/3D dimensionality control on the cross-conference atlas landing page (and on the NeuroScape subsite home page in US3) flips between the existing 3D rotatable scatter and a flat 2D scatter computed from the same NeuroScape Stage-2 vectors.

**Independent Test**: On the atlas-root preview, switch from 3D to 2D; the scatter re-projects within 2 s; lasso + hover + cluster-legend filter all still work; switching back preserves the overlay toggle, cluster filter, and selection state.

### Tests for US2

- [ ] T052 [P] [US2] Write a failing vitest at `site/src/tests/unit/dimensionality.test.ts`: assert the `dimensionality` store defaults to `'3d'`, accepts `'2d'`, and persists across simulated reload.
- [ ] T053 [P] [US2] Extend `site/src/tests/e2e/atlas_root.spec.ts` with the US2 acceptance scenarios from spec.md: switch 3D → 2D within 2 s, lasso/hover/legend still work, switching back preserves the in-flight state.

### Implementation for US2

- [ ] T054 [P] [US2] Implement `site/src/lib/stores/dimensionality.ts`: writable `'2d' | '3d'` store, default `'3d'`, `localStorage`-backed under key `atlas.dimensionality`. Tests from T052 MUST pass.
- [ ] T055 [P] [US2] Implement `site/src/lib/components/DimensionalityToggle.svelte` (or extend the existing OHBM 2026 component if present) and mount it in LandingPageHeader (US1) for `SITE_MODE === 'atlas-root'`.
- [ ] T056 [US2] Extend `UmapPanel.svelte` with a `dimensionality`-aware render path: read `umap_2d` or `umap_3d` from the appropriate table; 2D path uses a flat ortho-camera with disabled rotation; 3D path is unchanged. Switching MUST NOT reset the cluster filter or any lasso-in-progress. Tests from T053 MUST pass.
- [ ] T057 [US2] Add a Playwright assertion that the 2D screenshot is legible at 1080p without axis lines (US2 acceptance scenario 2).
- [ ] T057a [US2] Add a Playwright perf assertion in `site/src/tests/e2e/atlas_root_perf.spec.ts`: switch 3D → 2D, assert the re-projected scatter paints within 2 s (US2 acceptance scenario 1; complements the budget already named in SC-003 for the 3D drag-rotate path).

**Checkpoint**: Visitors can switch between 2D and 3D on the atlas-root landing page; the same control will plug into `/neuroscape/` in US3.

---

## Phase 6: User Story 3 — NeuroScape PubMed subsite (Priority: P2)

**Goal**: A new sibling subsite at `/neuroscape/` exposes the full ~600K-article corpus with title-only typo-tolerant lexical search, lasso, faceted filters, and per-article detail pages that fetch PubMed bodies at view time from NCBI E-utilities (FR-018, FR-019, FR-019a, FR-019b).

**Independent Test**: After US4 + US1, deploy the PR preview, visit `/pr-<N>/neuroscape/`. Searching for "hippocampus place cells" returns title-matching results; opening any result lands at `/neuroscape/abstract/<pubmed_id>/` with the local fields rendered in <200 ms and the PubMed body fetched + rendered within 3 s; disabling the network shows the body offline state without affecting the local fields; clicking a neighbour navigates via permalink and reuses the in-memory body cache for already-visited articles.

### Tests for US3

- [ ] T058 [P] [US3] Write a failing vitest at `site/src/tests/unit/pubmed_fetch.test.ts`: assert the runtime PubMed fetcher (a) returns a Map-cached response for a repeat-id call, (b) retries 5xx up to 3 times with exponential backoff, (c) honours the rate-limit token bucket (3 req/s anon, 10 req/s when `VITE_NCBI_API_KEY` is set), (d) parses an EFetch XML fixture into the documented `FetchedRecord` shape (title, authors, journal, abstract_text, doi).
- [ ] T059 [P] [US3] Write a failing Playwright spec at `site/src/tests/e2e/neuroscape_subsite.spec.ts`: home-page lexical search "hippocampus place cells" returns ≥1 result whose title contains the substring; opening it lands at `/neuroscape/abstract/<id>/`; local fields paint within 200 ms (assert via DOM presence); body is fetched + painted within 3 s on a warm network; the "Show on atlas" action navigates back to `/neuroscape/` with the article focused.
- [ ] T061 [P] [US3] Add an offline-mode Playwright case in `neuroscape_subsite.spec.ts`: simulate `context.setOffline(true)` after the local fields paint; assert the body region shows the body-offline state with a Retry button and "Open on pubmed.gov →" CTA, while local fields remain.
- [ ] T061a [P] [US3] Add a Playwright device-emulation perf case in `site/src/tests/e2e/neuroscape_subsite_mobile.spec.ts`: use `devices['Pixel 5']` (or comparable mid-range emulator), navigate to the atlas-root landing page first then `/neuroscape/`, assert combined-view first paint ≤ 10 s and that the device does not run out of memory at the default decimated backdrop (SC-007).

### Implementation for US3

- [ ] T062 [P] [US3] Implement `site/src/lib/pubmed_fetch.ts`: an exported `fetchPubmedRecord(pubmed_id: number): Promise<FetchedRecord>` per R-015 — EFetch URL builder, in-memory `Map<number, Promise<FetchedRecord>>` cache, 3-retry exponential backoff (250 ms / 500 ms / 1 s), token-bucket rate limiter wired off `import.meta.env.VITE_NCBI_API_KEY`. Tests from T058 MUST pass.
- [ ] T063 [P] [US3] Implement the EFetch XML parser in `site/src/lib/pubmed_xml.ts`: pure function from XML string → `FetchedRecord` shape; covers MEDLINE citation structure (authors as LastName + Initials; abstract may be multi-text with labels; DOI lives in `ELocationID[@EIdType='doi']`). Unit-tested as part of T058.
- [ ] T064 [P] [US3] Implement `site/src/lib/components/PubmedBodyRegion.svelte`: a slot of the DetailPanel that triggers `fetchPubmedRecord` on mount, renders a skeleton until it resolves, renders the body offline state on persistent failure (Retry button + "Open on pubmed.gov →" CTA). Used only on `SITE_MODE === 'neuroscape'`.
- [ ] T065 [US3] Extend the existing `site/src/routes/abstract/[id]/+page.svelte` with a `SITE_MODE === 'neuroscape'` branch that interprets the `id` param as a `pubmed_id` and renders local fields (title, year, cluster info, neighbour list) above the PubmedBodyRegion. The `ohbm2026` branch remains byte-identical, satisfying FR-022 + SC-008. SvelteKit's filename-driven routing keeps the directory name `[id]/` for both modes; only the in-file branch differs. Tests from T059 + T061 MUST pass.
- [ ] T066 [US3] Add the "Show on atlas" action to the `/neuroscape/abstract/<id>/` page: navigates to `/neuroscape/` with `?focus=<pubmed_id>&cluster=<cluster_id>` query string; the `/neuroscape/` home reads these on mount, scrolls the camera to the point, and highlights the cluster legend entry.
- [ ] T067 [US3] Extend `+page.svelte` with a `SITE_MODE === 'neuroscape'` branch per R-014: reuse SearchBar + ResultList + FacetSidebar + UmapPanel + DetailPanel but bound to `neuroscape.parquet`'s tables. SearchBar runs title-only typo-tolerant search per FR-018 (use the existing typo-tolerant search engine, parametrised by field-set).
- [ ] T068 [US3] Add the browser-side decoder branch in `loader.ts` for the title-only search sidecar (`search:neuroscape_titles` + `search:neuroscape_titles_meta`) — the Python emit half ships in T027 / US4. Expose the index to the SearchBar via the existing path-keyed envelope. Smoke-test under T020a.
- [ ] T069 [US3] Update `site/src/lib/data_package/loader.ts` so `SITE_MODE === 'neuroscape'` reads `VITE_DATA_PACKAGE_URL_NEUROSCAPE` and exposes the new tables (`articles`, `clusters`, `neighbors_neuroscape`, `search:neuroscape_titles`) via the existing path-keyed envelope (mirror the OHBM 2026 path conventions: `data/neuroscape_articles.json`, `data/neuroscape_clusters.json`, …).
- [ ] T070 [US3] Extend the deploy workflow (T049) to publish `site/publish/neuroscape/` under `<host>/neuroscape/` for production AND `pr-<N>/neuroscape/` for previews. Verify by visiting the PR-preview URL.
- [ ] T071 [US3] Add a "Browse the cross-conference atlas →" link in the NeuroScape subsite's header pointing at `/` and a "Browse OHBM 2026 abstracts →" link pointing at `/ohbm2026/` per FR-021.

**Checkpoint**: All four user stories are functional and independently testable. Visitors can land at `/`, follow either subsite link, search, and open detail pages.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, constitution sweep, final CI assertions, push.

- [ ] T072 [P] Update `README.md` with the Stage-15 runbook (operator commands, env vars, parquet URL matrix) — cross-reference `quickstart.md`.
- [ ] T073 [P] Update `docs/reproducibility-vision.md`: add the three-parquet artefact roots, the runtime-PubMed-fetch boundary, and the deferred semantic-search note.
- [ ] T074 [P] CLAUDE.md SPECKIT block already points at the Stage-15 plan (done during planning) — re-read and confirm it still matches the final spec text. Update any drift.
- [ ] T075 [P] Add a project-memory entry capturing the post-Stage-15 architecture: bare root is now an atlas page (not a redirect); `/ohbm2026/` and `/neuroscape/` are sibling subsites; three parquets each carry their own state-key. Index it from `MEMORY.md`.
- [ ] T076 Run `.specify/scripts/bash/constitution-check.sh --full` and address any reported violations (bare-except, committed data, secrets, `--no-verify`).
- [ ] T077 Audit error handling end-to-end: confirm every `FR-026` error path raises a typed `Stage15Error` subclass with structured kwargs (`grep -rn "except.*:" src/ohbm2026/atlas_package/`).
- [ ] T078 Verify no new artefact root is being committed (`git status --short` against the gitignore additions from T002) and that `data/`, `export/`, `tmp/`, `archive/`, `memory/archive/` remain gitignored.
- [ ] T079 Provenance audit: run the orchestrator against the real corpus, open the provenance JSON, assert (a) every required field is present, (b) no absolute/`$HOME` paths anywhere, (c) the three output state-keys match the manifests inside the parquets.
- [ ] T080 Secret-exposure review: grep the commit diff for tokens (`OHBM2026_API_TOKEN`, `OPENAI_API_KEY`, `VOYAGE_API_KEY`, `NCBI_API_KEY` values) and assert none appear in fixtures, docs, or logs. Confirm `VITE_NCBI_API_KEY` is referenced by name only.
- [ ] T081 Run quickstart.md steps 0–7 against a clean clone as a final dry-run; record any deviations in `quickstart.md` directly.
- [ ] T082 Open the PR (`gh pr create -t "feat(stage15): cross-conf atlas + neuroscape subsite" -B main`), include the PR description summary from `quickstart.md` step 5, and request review.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS** all user stories. Includes the byte-identity gate for `data.parquet → ohbm2026.parquet` (FR-022 + SC-008).
- **US4 (Phase 3)**: Depends on Foundational. **BLOCKS** US1, US2, US3 because they all consume `atlas.parquet` / `neuroscape.parquet`.
- **US1 (Phase 4)**: Depends on US4. **Required for US2 (toggle wiring shared)**.
- **US2 (Phase 5)**: Depends on US1 (shares the LandingPageHeader chrome and the SITE_MODE plumbing).
- **US3 (Phase 6)**: Depends on US4. Can run **in parallel with US1+US2** once US4 is done — the `/neuroscape/` subsite is independent of the atlas-root landing page.
- **Polish (Phase 7)**: Depends on all desired stories being complete.

### Within Each User Story

- Tests are written first and assert FAIL before the implementation task that satisfies them lands.
- Models / pure functions / stores before components / endpoints.
- Local-only behaviour before integration with external systems.
- Verified-slice commits (per Principle V): each task or short cluster of tasks gets its own descriptive commit; do not batch.

### Parallel Opportunities

- Phase 1: T002, T003, T004, T005 — independent files. All [P].
- Phase 2: T006/T008/T010/T012 (test scaffolds) run in parallel; T007/T009/T011 (implementations) each wait on their corresponding tests; T013/T014/T015 are independent files after T012 lands.
- Phase 3 (US4): T016–T021 (six failing tests) run in parallel; T022, T023, T024, T025 (loader / fit / projector / neighbours) are independent files [P]; T026, T027, T028 (decimation, parquet writer, link check) depend on their predecessors; T029 (orchestrator) wires the rest; T031–T032 [P].
- Phase 4 (US1): T034, T035, T036, T037 (four failing tests) run in parallel; T038, T039, T040, T041, T042 (five independent files) are all [P]; T043 extends the same file as T042 so it's sequential; T044–T047 wire them together; T048 [P]; T049 / T050 / T051 are deploy-workflow + verify; T051a is a perf assertion that can run in parallel with T051.
- Phase 5 (US2): T052 + T053 in parallel; T054 + T055 in parallel; T056 + T057 sequential.
- Phase 6 (US3): T058 + T059 + T061 + T061a in parallel; T062 + T063 + T064 in parallel; T065–T071 mostly sequential. (T060 moved to Phase 3 as T020a per the 2026-05-23 analyze pass.)
- Phase 7: T072–T075 in parallel; T076–T081 mostly sequential; T082 last.

---

## Parallel Example: User Story 4 (the longest phase)

```bash
# All failing tests for US4 land first, in parallel:
Task: "T016 [P] [US4] Write failing tests in tests/test_neuroscape_loader.py"
Task: "T017 [P] [US4] Write failing tests in tests/test_atlas_umap_fit.py"
Task: "T018 [P] [US4] Write failing tests in tests/test_ohbm_projector.py"
Task: "T019 [P] [US4] Write failing tests in tests/test_atlas_parquet_writer.py"
Task: "T020 [P] [US4] Write failing test in tests/test_atlas_orchestrator.py::test_idempotent_rebuild"
Task: "T021 [P] [US4] Write failing test in tests/test_atlas_exceptions.py::test_link_check_failure_blocks_run"

# Then the independent implementation files, in parallel:
Task: "T022 [P] [US4] Implement src/ohbm2026/atlas_package/neuroscape_loader.py"
Task: "T023 [P] [US4] Implement src/ohbm2026/atlas_package/umap_fit.py"
Task: "T024 [P] [US4] Implement src/ohbm2026/atlas_package/ohbm_projector.py"
Task: "T025 [P] [US4] Implement src/ohbm2026/atlas_package/neighbour_index.py"
```

---

## Implementation Strategy

### MVP scope (single demoable slice)

1. Phase 1 (Setup) — T001–T005.
2. Phase 2 (Foundational) — T006–T015.
3. Phase 3 (US4) — T016–T033. End state: three parquets reproducibly built.
4. Phase 4 (US1) — T034–T051. End state: bare root is the cross-conference atlas landing page; `/ohbm2026/` is byte-identical.
5. **STOP and VALIDATE**: a visitor at the production root sees the atlas with the binary toggle; old `/ohbm2026/` bookmarks are untouched. **This is the publishable MVP.**

### Incremental delivery

6. Phase 5 (US2) — T052–T057. Adds 2D/3D switch.
7. Phase 6 (US3) — T058–T071. Adds the NeuroScape subsite.
8. Phase 7 (Polish) — T072–T082. Docs, audits, PR.

### Parallel team strategy

- One operator runs the Python pipeline (Phase 3 / US4) in foreground.
- Once `atlas.parquet` exists, a second contributor begins US1 (Phase 4) on the SvelteKit side.
- Once `neuroscape.parquet` exists, a third contributor begins US3 (Phase 6).
- US2 (Phase 5) is small and best done by whoever finishes US1 first.

---

## Notes

- Every behaviour-changing task in Phases 3–6 is paired with a failing test that lands first per Principle IV (CA-002).
- Byte-identical `/ohbm2026/` is enforced both at the parquet level (T012/T013) and at the build-tree level (T037/T050).
- The `data.parquet → ohbm2026.parquet` rename is a single-byte change in two source files; the rest of the bundle's hash should match exactly.
- No new credentials are committed; `VITE_NCBI_API_KEY` is referenced by name and consumed by the deploy workflow only.
- The deferred MiniLM → NeuroScape semantic-search project is a separate spec, opened only after Stage 15 ships.
- Per Constitution V: each verified slice (test pair + implementation) gets its own commit with a descriptive message; do not batch.
