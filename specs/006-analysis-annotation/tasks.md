---

description: "Task list for Stage 4 — Analysis & Annotation"
---

# Tasks: Stage 4 — Analysis & Annotation

**Input**: Design documents at `/specs/006-analysis-annotation/`
**Prerequisites**: plan.md (loaded), spec.md (6 user stories), research.md (algorithmic choices), data-model.md (entities), contracts/{cli,bundle,rollup,project_into_umap}.md, quickstart.md

**Tests**: Required for every behavior-changing user story per spec CA-002 + project Principle IV. The reorganization (US6) carries SC-007 ("the only allowed diff is import-path rewrites") and is verified by the existing test suite continuing to pass.

**Organization**: Tasks grouped by user story per spec priorities. US6 (reorganization) is hoisted into the **Foundational** phase because the spec mandates no backward-compat shim — every new file Stage 4 introduces must land in the new `analyze/` package shape from the start.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User-story label (US1…US6); foundational/setup/polish tasks have no story label
- File paths are absolute under repository root

## Path Conventions

- Stage 4 source: `src/ohbm2026/analyze/`, `src/ohbm2026/embed/neuroscape.py`
- Scripts: `scripts/run_analyze_matrix.py`, `scripts/derive_neuroscape_centroids.py`
- Tests: `tests/test_analyze_*.py`
- Outputs (gitignored): `data/outputs/analysis/`, `data/cache/analysis/`, `data/provenance/analysis/`, `data/inputs/neuroscape/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Pull the new analysis dependencies into the venv and stake out the package skeleton so subsequent phases can fill it.

- [X] T001 Add `[analysis]` (umap-learn>=0.5, faiss-cpu>=1.8, python-igraph>=0.11, leidenalg>=0.10, spacy>=3.8, h5py>=3.10, pyarrow>=17.0, scikit-learn>=1.4) and `[analysis-sci]` (scispacy>=0.5) optional-dependency groups to `pyproject.toml`
- [X] T002 Install the analysis extras into the project venv with `UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[analysis]"`
- [X] T003 [P] Download the spaCy model with `.venv/bin/python -m spacy download en_core_web_md`
- [X] T004 [P] Create empty package skeleton — `src/ohbm2026/analyze/__init__.py` containing only a module docstring, so subsequent foundational tasks can write into the package without touching one another's namespace

**Checkpoint**: Venv is hydrated with analysis libs; the `analyze/` package exists as an importable empty namespace.

---

## Phase 2: Foundational — Reorganization (US6) + Error Hierarchy

**Purpose**: Migrate every existing consumer off the flat `src/ohbm2026/analyze.py` onto the new per-submodule `analyze/` package paths, move the Stage-2 NeuroScape model into `embed/neuroscape.py` (replacing the façade), and delete `analyze.py`. This is the **structural skeleton** every later story builds on; SC-007 ("only allowed diff is import-path rewrites") gates it.

**⚠️ CRITICAL**: No US1–US5 implementation work begins until this phase is complete. The existing test suite (especially `tests/test_neuroscape.py`, `tests/test_neuroscape_derivation.py`, `tests/test_cli.py`) MUST stay green throughout.

### Failing-test gate

- [X] T005 Confirm the existing test suite passes against the current `analyze.py` baseline with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v` (records the "all-green" snapshot we must preserve through the reorganization)

### Error hierarchy + storage + provenance

- [X] T006 [P] [US6] Create the typed Stage 4 error hierarchy at `src/ohbm2026/analyze/errors.py` — `AnalysisError(OhbmStageError)` plus `InputBundleMissing`, `CentroidTableMissing`, `CentroidTableVersionMismatch`, `UnsupportedProjectionAlgorithm`, `ProjectionDimensionMismatch`, `TopicGroupingHallucination`, `CommunityResolutionDegenerate` (the warning class) — and re-export the lot from `src/ohbm2026/exceptions.py`
- [X] T007 [P] [US6] Move bundle + cache atomic I/O into `src/ohbm2026/analyze/storage.py`: lift `write_embedding_bundle`, `load_embedding_bundle`, `load_stage1_bundle` from the existing `analyze.py`; add `write_analysis_bundle(bundle_dir, ids, payload, topics, metadata, provenance)` for the new per-kind shape (atomic temp→rename); stdlib + numpy only
- [X] T008 [P] [US6] Create `src/ohbm2026/analyze/provenance.py` — `write_analysis_provenance(...)` + `_assert_paths_safe(path)` (project-relative paths only, rejects absolute and user-home paths; mirrors `embed/provenance.py`)
- [X] T009 [P] [US6] Create `src/ohbm2026/analyze/clusters.py` — migrate `prepare_clustering_matrix`, `cluster_with_method`, `compute_clustering_metrics`, `rank_clustering_benchmark_results`, `run_clustering_benchmark`, `write_clustering_benchmark`, `cluster_benchmark_main` (and supporting `_cluster_distance_metrics`, `_normalized_cluster_entropy`, `_valid_benchmark_run`, `_normalized_metric_value`, `_agglomerative_kwargs`) verbatim from `analyze.py`
- [X] T010 [P] [US6] Create `src/ohbm2026/analyze/projections.py` — migrate `compute_umap_projection` (legacy), `compute_tsne_projection`, `write_umap_outputs`, `default_umap_output_paths`, `default_projection_output_paths`, `write_projection_comparison_outputs`, `build_projection_graph`, `score_projection`, `_projection_trace_customdata`, `_add_projection_panel_traces`, `_build_linked_highlight_script`, `optimize_projection_parameters`, `_projection_rank_key`, `projection_compare_main`, `projection_optimize_main`, `umap_main`, `_normalize_tsne_learning_rates`, `build_distinct_color_map`, `build_embedding_visualization_title`, `build_visualization_records`
- [X] T011 [P] [US6] Move Stage-2 NeuroScape model code from `analyze.py` into `src/ohbm2026/embed/neuroscape.py` (replace the current 36-line façade with the real implementation): `PUBLISHED_STAGE2_HIDDEN_DIMENSIONS`, `PUBLISHED_STAGE2_OUTPUT_DIMENSION`, `NeuroScapeError`, `normalize_hidden_dimensions`, `choose_torch_device`, `build_stage2_network`, `split_stage2_matrix`, `compute_stage2_losses`, `evaluate_stage2_model`, `train_stage2_model`, `apply_stage2_model`, `load_pretrained_stage2_model`, `write_stage2_bundle`, `write_pretrained_stage2_bundle`, `dimension_correlation`, `build_stage2_parser`, `apply_pretrained_stage2_main`, `stage2_main`, `build_apply_pretrained_stage2_parser`, `write_neuroscape_manifest`, `manifest_main`, `build_manifest_parser`. Keep the existing `__all__` re-exports for back-compat with `embed/` consumers; the imports from `ohbm2026.analyze` inside the façade go away.
- [X] T012 [P] [US6] Create `src/ohbm2026/analyze/__init__.py` re-exports — keep the small public surface that downstream modules still need (`parse_string_list_value`, `load_embedding_bundle`, `build_knn_graph`, `compute_clustering_metrics`, `build_distinct_color_map`, `prepare_clustering_matrix`, `write_json`, `unique_strings`, `extract_primary_topic`, `load_embedding_inputs`, `configure_huggingface_auth`, `load_title_lookup`, `extract_raw_keywords`, `load_annotation_lookup`, `model_name_slug`, `build_embedding_output_name`, `compute_neighbors`, `align_semantic_records`, `align_cluster_records`, `summarize_membership_groups`, `summarize_semantic_clusters`, `build_group_rationale`, `extract_cluster_keywords`, `detect_semantic_communities`, `detect_semantic_communities_at_resolution`, `write_semantic_analysis`, `semantic_analysis_main`, `build_semantic_analysis_parser`, `build_stage2_analysis_parser`, `stage2_analysis_main`, `write_stage2_analysis`, `detect_stage2_communities`, `summarize_stage2_clusters`, `load_enriched_lookup`, `build_knn_graph`)

### Helper migrations into appropriate submodules

- [X] T013 [P] [US6] Move `build_knn_graph`, `align_semantic_records`, `align_cluster_records`, `summarize_membership_groups`, `summarize_semantic_clusters`, `build_group_rationale`, `extract_cluster_keywords`, `detect_semantic_communities`, `detect_semantic_communities_at_resolution`, `detect_stage2_communities`, `summarize_stage2_clusters`, `write_semantic_analysis`, `write_stage2_analysis`, `build_semantic_analysis_parser`, `build_stage2_analysis_parser`, `semantic_analysis_main`, `stage2_analysis_main`, `load_enriched_lookup` from `analyze.py` into `src/ohbm2026/analyze/clusters.py` (existing semantic-analysis surface; not the new FAISS+Leiden communities — those go to communities.py in US4)
- [X] T014 [P] [US6] Move text-shaping + bundle helpers (`write_json`, `parse_string_list_value`, `unique_strings`, `extract_primary_topic`, `load_embedding_inputs`, `configure_huggingface_auth`, `load_title_lookup`, `extract_raw_keywords`, `load_annotation_lookup`, `build_visualization_records`, `normalize_embedding_fields`, `build_embedding_text`, `build_embedding_texts`, `build_claim_embedding_text`, `embedding_variant_name`, `model_name_slug`, `build_embedding_output_name`, `compute_neighbors`) into `src/ohbm2026/analyze/storage.py` (these are I/O + shaping utilities used by the existing consumers)

### Importer migration

- [X] T015 [US6] Update `src/ohbm2026/cli.py` — rebind every `from ohbm2026 import analyze as neuroscape` and `cli.neuroscape.*` reference to the new submodule paths: `from ohbm2026.embed import neuroscape as embed_neuroscape` for Stage-2 model entrypoints, `from ohbm2026.analyze import clusters, projections, storage` for the rest; update `tests/test_cli.py` mocks to point at the new module paths
- [X] T016 [P] [US6] Update `src/ohbm2026/ui.py` import (`from ohbm2026.analyze import parse_string_list_value` → `from ohbm2026.analyze.storage import parse_string_list_value` if you move the helper, or keep the `__init__.py` re-export and leave the import unchanged)
- [X] T017 [P] [US6] Update `src/ohbm2026/poster_layout.py` imports (`load_embedding_bundle`, `parse_string_list_value`) to point at `analyze.storage`
- [X] T018 [P] [US6] Update `src/ohbm2026/category_evaluation.py` imports (`build_knn_graph`, `compute_clustering_metrics`, `load_embedding_bundle`, `parse_string_list_value`) to point at `analyze.clusters` + `analyze.storage`
- [X] T019 [P] [US6] Update `scripts/plot_voyage_stage2_umap_3d.py`, `scripts/write_topic_group_report.py`, `scripts/run_gmm_overlap_experiment.py`, `scripts/plot_poster_layout_floorplan.py`, `scripts/cluster_projection_silhouette.py` imports to the new submodule paths
- [X] T020 [P] [US6] Update `tests/test_neuroscape.py` to import every Stage-2 entrypoint from `ohbm2026.embed.neuroscape` and every analysis helper from the new `analyze.*` submodules; do NOT change test bodies (SC-007: only import-path rewrites)
- [X] T021 [P] [US6] Update `tests/test_neuroscape_derivation.py` imports likewise

### Sweep

- [X] T022 [US6] Delete `src/ohbm2026/analyze.py` (the flat module) — the package replaces it
- [X] T023 [US6] Re-run the full test suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`. Every previously-passing test MUST still pass — this is SC-007's gate
- [X] T024 [US6] Update `pyproject.toml`'s `[project.scripts]` entrypoints that reference `ohbm2026.neuroscape:*` to point at `ohbm2026.embed.neuroscape:*` (e.g., `ohbm-embed-stage2`, `ohbm-cluster-benchmark`, `ohbm-umap-plot`, `ohbm-write-manifest`, etc.); these still work after the reorganization because the surfaces moved together

**Checkpoint**: Stage 4's new package skeleton is in place, every existing consumer compiles + tests pass against it, and the flat `analyze.py` is gone. US1–US5 implementation can now begin in parallel.

---

## Phase 3: User Story 1 — Default analysis matrix (Priority: P1) 🎯 MVP

**Goal**: One canonical Stage 4 entrypoint (`ohbmcli analyze-matrix`) iterates the 5-model × 2-input × 4-kind matrix, writes per-bundle artifacts, and emits the canonical `annotations__<state-key>.{parquet,sqlite}` rollup. Per-bundle caching keyed on `(input_matrix_hash, algorithm_config, seed, prompt_version)` makes reruns hit cache.

**Independent Test**: Run `ohbmcli analyze-matrix --dry-run` against the current Stage 3 corpus and confirm the runner resolves all 40 default `(model, input, kind)` combos and reports the planned bundle paths; then run without `--dry-run` and confirm 40 bundle directories + 1 rollup file pair appear under `data/outputs/analysis/`, each with `metadata.json` + `provenance.json` shaped per `contracts/bundle.md`.

### Tests for User Story 1 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

> **Write these tests FIRST, ensure they FAIL before implementation. Each test uses synthetic small matrices to keep runtime under the existing suite envelope.**

- [X] T025 [P] [US1] Write `tests/test_analyze_stage.py::test_dry_run_resolves_matrix` — a fake Stage 3 root with 2 models × 2 inputs × 6 components; runner produces a plan for 2×2×4 = 16 bundle paths and writes no files (note: the test stays at 2 inputs to keep the fixture compact; the live default of 3 inputs is validated by T097)
- [X] T026 [P] [US1] Write `tests/test_analyze_stage.py::test_missing_input_bundle_refusal` — referenced input bundle absent on disk → exits 2 with `InputBundleMissing` containing the expected path
- [X] T027 [P] [US1] Write `tests/test_analyze_stage.py::test_cache_hit_skips_compute` — second run with identical config writes nothing new; reports `"cache":"hit"` per bundle
- [X] T028 [P] [US1] Write `tests/test_analyze_stage.py::test_state_key_collision_refusal` — pre-existing bundle dir with a mismatched `corpus_state_key` in its provenance → runner refuses to overwrite (FR-013)
- [X] T029 [P] [US1] Write `tests/test_analyze_rollup.py::test_parquet_sqlite_shape_equivalence` — given a fixture set of bundles, the parquet + sqlite rollup tables have the same column count + row count + per-(model,input) column triples (community/neuroscape_cluster/topic_cluster)
- [X] T030 [P] [US1] Write `tests/test_analyze_rollup.py::test_cluster_topics_join_semantics` — `cluster_topics` join table covers every `(clustering_method, model, input, cluster_id)` produced by the bundles and Title/Description/Focus survive a round-trip
- [X] T031 [P] [US1] Write `tests/test_analyze_rollup.py::test_column_ordering_deterministic` — reordering models on the CLI doesn't change the parquet column ordering (sorted by `(kind, model, input)`)
- [X] T032 [P] [US1] Write `tests/test_analyze_cli.py::test_analyze_matrix_delegates_to_stage_main` — `cli.main(["analyze-matrix", "--dry-run"])` calls `analyze.stage.main(["--dry-run"])` with the flag passthrough
- [X] T033 [P] [US1] Write `tests/test_analyze_storage.py::test_atomic_bundle_write` — concurrent writers don't observe partial dirs; rename appears atomic
- [X] T034 [P] [US1] Write `tests/test_analyze_provenance.py::test_assert_paths_safe` — absolute paths, `~`-prefixed paths, and paths outside the repo root each raise `ProvenanceError`

### Implementation for User Story 1

- [X] T035 [P] [US1] Implement `src/ohbm2026/analyze/stage.py::run_matrix(config)` — load Stage 3 bundles → resolve `(model, input)` pairs via `embed.compose.compose_recipe` → compute `input_source_assembly_hash` → for each `(model, input, kind)` triple: (a) check the model-compat constraint for `neuroscape_clusters` (auto-skip with a `bundle_skipped` stdout event when `model != "neuroscape"`; raise when `strict_matrix=True`); (b) refuse to overwrite an existing bundle whose recorded `corpus_state_key` or `embedding_state_key` differs from the current run's (FR-013); (c) check cache → dispatch to the kind-specific runner (skeleton dispatch; runners land in US3/US4/US5/this story's UMAP slice) → write bundle → record provenance → emit one JSON-per-line summary
- [X] T036 [P] [US1] Implement `src/ohbm2026/analyze/stage.py::main(argv)` — argparse for every flag in `contracts/cli.md` (including `--strict-matrix`), env-file loading (in-memory only, no `os.environ` mutation), code-revision discovery via `git rev-parse HEAD`, and stdout emission of the JSON-per-line bundle summary + skipped events + final `matrix_complete` line per `contracts/cli.md`'s stdout protocol
- [X] T037 [P] [US1] Implement `src/ohbm2026/analyze/rollup.py::write_rollup(bundle_paths, out_parquet, out_sqlite)` — read every bundle's `ids.npy` + payload + topics → build the wide `annotations` table + the `cluster_topics` join table per `contracts/rollup.md` → atomic parquet write (pyarrow) + atomic sqlite write (stdlib sqlite3) → both files content-equivalent
- [X] T038 [US1] Wire the `analyze-matrix` subcommand in `src/ohbm2026/cli.py` (the dispatch entry that delegates to `analyze.stage.main`)
- [X] T039 [US1] Add the venv-only wrapper `scripts/run_analyze_matrix.py` (mirrors `scripts/run_embed_matrix.py`): loads `.env`, sets `PYTHONPATH=src`, delegates to `ohbm2026.analyze.stage.main(sys.argv[1:])`
- [X] T040 [US1] Implement the per-`(model, input)` UMAP run inside `analyze/stage.py` (fits a 2D+3D UMAP, writes the `projections` bundle through `analyze.umap.write_projections_bundle` — the function ships in US2 below); for this MVP slice the dispatch only handles `kind == "projections"`. (Communities + neuroscape_clusters + topic_clusters dispatches are stubbed and raise `NotImplementedError` so US1 tests pass with `--kinds projections` only.)

**Checkpoint**: `ohbmcli analyze-matrix --kinds projections` runs end-to-end against the current Stage 3 corpus and emits 15 (5 models × 3 inputs) `projections` bundles + a UMAP-only rollup. The orchestrator + CLI + provenance + cache scaffolding are validated.

---

## Phase 4: User Story 2 — Project a vector into an existing UMAP (Priority: P1)

**Goal**: Expose `analyze.umap.project_into_umap(new_vectors, fitted_bundle, algorithm=…)` supporting `native` / `knn_weighted` / `parametric`, plus the `analyze-umap-project` CLI subcommand.

**Independent Test**: Fit a UMAP on a 100-row synthetic matrix, hold out 10 rows, project each holdout via all three algorithms, verify (a) correct shape, (b) within-convex-hull of nearest 10 neighbors' coords, (c) byte-identical repeats.

### Tests for User Story 2 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

- [X] T041 [P] [US2] Write `tests/test_analyze_umap.py::test_native_round_trip` — fit UMAP-2D on 100 synthetic vectors; holdout 10; `algorithm="native"` returns `(10, 2)`; each new point sits within the convex hull of its 10 nearest references' coords
- [X] T042 [P] [US2] Write `tests/test_analyze_umap.py::test_knn_weighted_works_without_model` — coords-only bundle (no `umap2d_model.pickle` persisted); `algorithm="knn_weighted"` succeeds
- [X] T043 [P] [US2] Write `tests/test_analyze_umap.py::test_parametric_round_trip` — parametric MLP fit; projection reproduces ≥0.85 cosine to native on holdout
- [X] T044 [P] [US2] Write `tests/test_analyze_umap.py::test_unsupported_algorithm` — algorithm not in `supported_algorithms` → `UnsupportedProjectionAlgorithm`
- [X] T045 [P] [US2] Write `tests/test_analyze_umap.py::test_dim_mismatch` — `new_vectors.shape[1] != bundle.vector_dim` → `ProjectionDimensionMismatch`
- [X] T046 [P] [US2] Write `tests/test_analyze_umap.py::test_determinism_byte_identical` — two consecutive `project_into_umap(...)` calls return byte-identical `np.ndarray`s for every algorithm (SC-003)
- [X] T047 [P] [US2] Write `tests/test_analyze_umap.py::test_dim_3d_path` — same coverage but with `dim=3`

### Implementation for User Story 2

- [X] T048 [P] [US2] Implement `src/ohbm2026/analyze/umap.py::fit_umap_2d(matrix, *, n_neighbors, min_dist, metric, random_state)` and `::fit_umap_3d(...)` returning `(coords, fitted_umap_model)`
- [X] T049 [P] [US2] Implement `src/ohbm2026/analyze/umap.py::fit_parametric_mlp(reference_matrix, reference_coords, *, seed)` — small numpy MLP (no torch dep); persistable as a list of `(W, b, activation)` tuples
- [X] T050 [P] [US2] Implement `src/ohbm2026/analyze/umap.py::write_projections_bundle(bundle_dir, ids, vectors, coords2d, coords3d, model2d, model3d, mlp2d, mlp3d, metadata, provenance)` — single-call writer that emits every file per `contracts/bundle.md` projections section; record `supported_algorithms` from the actual persisted artifacts
- [X] T051 [P] [US2] Implement `src/ohbm2026/analyze/umap.py::project_into_umap(new_vectors, fitted_umap_bundle, *, algorithm, dim, knn_k, knn_temperature)` covering all three algorithms + every error case in `contracts/project_into_umap.md`
- [X] T052 [US2] Wire the `analyze-umap-project` subcommand into `src/ohbm2026/cli.py` (loads the bundle dir, reads `--input-vectors` from a `.npy` path, writes the projected coords to `--output`)

**Checkpoint**: `project_into_umap(...)` is callable from Python + CLI against every projections bundle produced in US1; out-of-corpus vectors land in the same UMAP space as the corpus without re-fitting.

---

## Phase 5: User Story 3 — NeuroScape centroid cluster assignment (Priority: P2)

**Goal**: Implement spherical-mean nearest-centroid assignment in the published NeuroScape Stage-2 space. The centroid table is precomputed once via `scripts/derive_neuroscape_centroids.py`.

**Independent Test**: Run NeuroScape-centroid assignment over a 50-row synthetic sample; verify every row gets a cluster id from the published vocabulary, the distance distribution is non-degenerate, and reapplication is byte-identical.

### Tests for User Story 3 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

- [X] T053 [P] [US3] Write `tests/test_analyze_centroids.py::test_spherical_mean_unit_norm` — given a synthetic cluster of unit-norm 64-dim vectors, `spherical_mean(vectors)` returns a unit-norm centroid that matches the von-Mises mean direction within 1e-5
- [X] T054 [P] [US3] Write `tests/test_analyze_centroids.py::test_nearest_centroid_assignment` — 50 row × 64-dim synthetic embeddings + 5 synthetic centroids; verify assignments match the deliberately-placed nearest centroid for every row, and distances are angular (in `[0, π]`)
- [X] T055 [P] [US3] Write `tests/test_analyze_centroids.py::test_missing_centroid_table_refusal` — pointing the runner at a nonexistent centroid path raises `CentroidTableMissing` with the expected path in the message
- [X] T056 [P] [US3] Write `tests/test_analyze_centroids.py::test_version_mismatch_refusal` — centroid sidecar version disagrees with the Stage-2 checkpoint's recorded version → `CentroidTableVersionMismatch`
- [X] T057 [P] [US3] Write `tests/test_analyze_centroids.py::test_neuroscape_cluster_bundle_metadata` — produced bundle's `metadata.json` carries `centroid_table_version`, `n_centroids`, distance moments + percentiles
- [X] T058 [P] [US3] Write `tests/test_derive_neuroscape_centroids.py::test_derivation_over_synthetic_h5_csv` — synthetic 3-shard H5 + 100-row articles.csv → script writes `centroids__<version>.npy` of the right shape + `cluster_table.csv` with the discovered version field
- [X] T059 [P] [US3] Write `tests/test_derive_neuroscape_centroids.py::test_version_derived_from_grouped_vectors` — changing any input H5 shard produces a different `<version>` hash

### Implementation for User Story 3

- [X] T060 [P] [US3] Implement `src/ohbm2026/analyze/centroids.py::spherical_mean(vectors)` (per-coordinate `atan2(mean(sin), mean(cos))`-style mean direction; unit-normalized output)
- [X] T061 [P] [US3] Implement `src/ohbm2026/analyze/centroids.py::load_centroid_table(neuroscape_dir)` — reads `centroids__*.npy` + `cluster_table.csv`; raises `CentroidTableMissing` / `CentroidTableVersionMismatch`; returns a `CentroidTable` dataclass per `data-model.md` §4
- [X] T062 [P] [US3] Implement `src/ohbm2026/analyze/centroids.py::assign_nearest_centroid(vectors, centroid_table)` — projects via `embed.neuroscape.apply_stage2_model` when the input dim doesn't match the centroid table (i.e., when the source model is not `neuroscape`); computes angular distance `arccos(clip(v·μ, -1, 1))`; returns `(cluster_ids, distances)`
- [X] T063 [P] [US3] Implement `src/ohbm2026/analyze/centroids.py::write_neuroscape_clusters_bundle(bundle_dir, ids, cluster_ids, distances, centroid_table, ...)` — emits `neuroscape_cluster_ids.npy`, `neuroscape_cluster_distances.npy`, `metadata.json` (centroid_table_version, n_centroids, distance moments/percentiles), `provenance.json`
- [X] T064 [P] [US3] Implement `scripts/derive_neuroscape_centroids.py` — argparse: `--input-root`, `--output-root`; reads `DomainEmbeddings/*.h5` shards (h5py), reads `neuroscience_articles_1999-2023.csv` (id → Cluster ID), groups vectors by Cluster ID, applies `spherical_mean`, writes `centroids__<sha256(grouped_vectors)[:12]>.npy` + `cluster_table.csv` (Cluster ID + Title/Description/Keywords/Focus from `neuroscience_clusters_1999-2023.csv`, with `centroid_table_version` repeated in every row for runtime discovery)
- [X] T065 [US3] Wire `neuroscape_clusters` dispatch in `src/ohbm2026/analyze/stage.py` — for `(neuroscape, *)` only: load the Stage 3 neuroscape bundle directly, call `assign_nearest_centroid(input_vectors, centroid_table)`, then `write_neuroscape_clusters_bundle(...)`. Guards the model-compat constraint per FR-002 (auto-skip + emit `bundle_skipped` for every non-`neuroscape` source model; raise `AnalysisError` when `strict_matrix=True`); writes `source_model` + `domain_model_checkpoint_sha256` into `metadata.json`
- [X] T064a [P] [US3] Extend `scripts/derive_neuroscape_centroids.py` to write a sibling `centroid_metadata.json` carrying: `centroid_table_version`, source CSV sha256s (articles + clusters), HDF5 shard manifest hash (sorted-shard-path-list digest), discovered `cluster_count`, `cluster_ids` list, and `domain_model_checkpoint_sha256` from `Models/domain_embedding_model.pth`. Use the **polar mean_angle** recipe (`convert_to_polar → mean_angle → convert_to_cartesian`) per the published NeuroScape `get_centroids` so bytes match the reference.
- [X] T065a [US3] Add the **checkpoint-SHA gate** in `analyze.runners.neuroscape_clusters_runner`: before calling `assign_nearest_centroid`, read the Stage 3 neuroscape bundle's `provenance.json`, extract its recorded `domain_model_checkpoint_sha256`, and compare against `centroid_metadata.domain_model_checkpoint_sha256`. Mismatch → raise `CentroidTableVersionMismatch`. Add a test exercising the mismatch path.

**Checkpoint**: `ohbmcli analyze-matrix --kinds neuroscape_clusters` produces 3 bundles (`neuroscape` × 3 inputs — voyage/minilm/openai/pubmedbert are auto-skipped per FR-002) carrying NeuroScape cluster ids + angular distances + provenance; bundles join into `cluster_topics` via the `cluster_table.csv` lookup.

---

## Phase 6: User Story 4 — Community detection (Priority: P2)

**Goal**: FAISS `IndexFlatIP` kNN graph over L2-normalized vectors + Leiden CPM with a 20-point resolution sweep, picking the modularity-plateau resolution. Largest community is `0`.

**Independent Test**: Build a 200-row synthetic corpus where three rows are deliberate near-duplicates of one another. Verify they end up in the same community; verify the largest community is `0`; verify the sweep records modularity at every resolution.

### Tests for User Story 4 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

- [X] T066 [P] [US4] Write `tests/test_analyze_communities.py::test_faiss_knn_normalized_recipe` — synthetic 100×16 random + L2-normalize → FAISS `IndexFlatIP` kNN with k=10 returns indices + similarities ∈ [0,1] (since vectors are unit-norm)
- [X] T067 [P] [US4] Write `tests/test_analyze_communities.py::test_symmetrization_preserves_edges` — `(A + A.T) / 2` retains every original edge weight ≥ original/2
- [X] T068 [P] [US4] Write `tests/test_analyze_communities.py::test_leiden_cpm_recovers_duplicates` — 200 rows with 3 near-identical → run Leiden CPM at the resolution that maximizes modularity → the 3 land in one community
- [X] T069 [P] [US4] Write `tests/test_analyze_communities.py::test_resolution_sweep_records_every_point` — 20-point linear sweep over `(0.001, 0.1]` records `{resolution, n_communities, modularity}` for each point
- [X] T070 [P] [US4] Write `tests/test_analyze_communities.py::test_largest_community_index_zero` — output `community_ids` are sorted by descending community size; `0` is the largest
- [X] T071 [P] [US4] Write `tests/test_analyze_communities.py::test_determinism_seed` — same seed → byte-identical `community_ids`
- [X] T072 [P] [US4] Write `tests/test_analyze_communities.py::test_degenerate_resolution_warning` — single dominant community holding >90% → `CommunityResolutionDegenerate` warning emitted; bundle still written

### Implementation for User Story 4

- [X] T073 [P] [US4] Implement `src/ohbm2026/analyze/communities.py::build_faiss_knn(vectors, *, k)` — L2-normalize → `faiss.IndexFlatIP` → search top-k → return `(indices, similarities)` (float32)
- [X] T074 [P] [US4] Implement `src/ohbm2026/analyze/communities.py::knn_to_graph(indices, similarities, *, symmetrize=True)` — convert to `igraph.Graph` with weighted symmetric edges
- [X] T075 [P] [US4] Implement `src/ohbm2026/analyze/communities.py::leiden_cpm_partition(graph, *, resolution, seed)` — calls `leidenalg.find_partition(graph, leidenalg.CPMVertexPartition, weights="weight", resolution_parameter=resolution, seed=seed)`; returns `(community_ids, modularity)`
- [X] T076 [P] [US4] Implement `src/ohbm2026/analyze/communities.py::resolution_sweep(graph, *, resolution_min, resolution_max, points, seed)` — linear sweep across `(min, max]`; per point: partition, modularity, n_communities; returns the sweep list plus the chosen plateau-elbow resolution
- [X] T077 [P] [US4] Implement `src/ohbm2026/analyze/communities.py::write_communities_bundle(bundle_dir, ids, community_ids, knn_indices, knn_similarities, sweep, selected_resolution, modularity, ...)` — per `contracts/bundle.md` communities section; emits `topics.json` placeholder (filled in by US5's topics stage; or left empty when `--skip-llm-topics` is also passed at run time without US5 wired)
- [X] T078 [US4] Wire `communities` dispatch in `src/ohbm2026/analyze/stage.py` — runs `build_faiss_knn` → `knn_to_graph` → `resolution_sweep` → `write_communities_bundle`; sorts ids by descending community size before emitting

**Checkpoint**: `ohbmcli analyze-matrix --kinds communities` runs end-to-end and emits 10 bundles + community columns in the rollup. SC-005 verification (≥12 communities, largest ≤30% on Voyage abstract) is exercised in Polish.

---

## Phase 7: User Story 5 — Topic modeling (Priority: P3)

**Goal**: Two-stage hybrid pipeline — spaCy + c-TF-IDF locally to extract candidate phrases per cluster, then an opt-out LLM grouping pass that re-ranks the shortlist and adds `Title` / `Description` / `Focus`. Hallucination guard: emitted `Keywords ⊆ candidate_phrases`. Also implements the `topic_clusters` analysis kind (the topic-model-driven clustering with its own cluster ids + probabilities).

**Independent Test**: 100-row synthetic abstract corpus with three deliberate topic clusters → topic_clusters recovers ~3 topics; abstracts seeded with the same topic land in the same `topic_cluster_id` ≥80% of the time. Topics pipeline against communities bundles → `Keywords ⊆ candidate_phrases` always.

### Tests for User Story 5 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

- [X] T079 [P] [US5] Write `tests/test_analyze_topics.py::test_spacy_phrase_extraction` — 5 synthetic sentences → `extract_candidate_phrases` returns canonicalized noun-chunks + entities (lowercase, lemma, deduped)
- [X] T080 [P] [US5] Write `tests/test_analyze_topics.py::test_ctfidf_discriminative` — 3 clusters with deliberately disjoint vocabularies → top-60 c-TF-IDF phrases per cluster contain ≥10 of that cluster's seed terms
- [X] T081 [P] [US5] Write `tests/test_analyze_topics.py::test_skip_llm_topics_path` — `--skip-llm-topics`: `topics.json` Keywords = top-15 c-TF-IDF phrases per cluster; Title/Description/Focus = ""
- [X] T082 [P] [US5] Write `tests/test_analyze_topics.py::test_llm_subset_guard` — mocked LLM emits `Keywords` containing a term not in `candidate_phrases` → `TopicGroupingHallucination` raised
- [X] T083 [P] [US5] Write `tests/test_analyze_topics.py::test_llm_cache_hit` — second invocation with the same `sorted(candidate_phrases)` reads the cache; LLM is not called twice
- [X] T084 [P] [US5] Write `tests/test_analyze_topics.py::test_topics_attached_to_communities_bundle` — running US4's communities followed by topics pass writes `topics.json` keyed by `community_id`
- [X] T085 [P] [US5] Write `tests/test_analyze_topic_clusters.py::test_synthetic_three_cluster_recovery` — 100-row synthetic seeded with 3 topic clusters → `topic_clusters` recovers approximately 3 clusters; same-seed rows share `topic_cluster_id` ≥80% of the time
- [X] T086 [P] [US5] Write `tests/test_analyze_topic_clusters.py::test_n_topics_auto_elbow` — `n_topics=auto` triggers the documented elbow/coherence rule; selection recorded in `metadata.json`

### Implementation for User Story 5

- [X] T087 [P] [US5] Implement `src/ohbm2026/analyze/topics.py::extract_candidate_phrases(cluster_texts, *, spacy_model, top_n)` — load spaCy `en_core_web_md` (or `en_core_sci_lg` when `--scispacy`), iterate `doc.noun_chunks` + `doc.ents`, canonicalize (lowercase + lemma + dedupe), score per-cluster via class-based TF-IDF across the cluster set, keep top-N; returns `list[str]`
- [X] T088 [P] [US5] Implement `src/ohbm2026/analyze/topics.py::group_phrases_via_llm(candidate_phrases, *, model_id, prompt_version, keyword_out_n, cache_dir)` — reuses `enrich.flex_tier` for the LLM call; structured JSON schema `{Keywords, Title, Description, Focus}`; post-call guard `set(Keywords).issubset(set(candidate_phrases))` raises `TopicGroupingHallucination`; cache key `sha256(model_id || prompt_version || "\n".join(sorted(candidate_phrases)))`; cache I/O atomic via `analyze.storage`. When `--skip-llm-topics` is active the orchestrator bypasses this call entirely (no cache lookup, no API call); when active without skip, the cache key uses the live `prompt_version` so version bumps invalidate prior cache entries.
- [X] T089 [P] [US5] Implement `src/ohbm2026/analyze/topics.py::build_topics_artifact(cluster_assignments, abstract_texts, *, skip_llm, scispacy, llm_model_id, prompt_version)` — orchestrates per-cluster phrase extraction → optional LLM grouping → returns `{cluster_id: {Keywords, Title, Description, Focus}}`; honors `--skip-llm-topics`
- [X] T090 [P] [US5] Implement `src/ohbm2026/analyze/topic_clusters.py::run_topic_clustering(vectors, *, n_topics, seed)` — topic-model-driven cluster assignment; v1 default uses HDBSCAN over UMAP-reduced vectors (BERTopic-style core); auto-selects `n_topics` via the elbow rule when `n_topics is None`; returns `(topic_cluster_ids, topic_cluster_probabilities)`
- [X] T091 [P] [US5] Implement `src/ohbm2026/analyze/topic_clusters.py::write_topic_clusters_bundle(bundle_dir, ids, topic_cluster_ids, topic_cluster_probabilities, topics, metadata, provenance)` — per `contracts/bundle.md` topic_clusters section
- [X] T092 [US5] Wire `topic_clusters` dispatch in `src/ohbm2026/analyze/stage.py` (calls `run_topic_clustering` → `build_topics_artifact` → `write_topic_clusters_bundle`)
- [X] T093 [US5] Wire the **topics-attachment pass** in `src/ohbm2026/analyze/stage.py` — after each `communities` bundle is written, run `build_topics_artifact(cluster_assignments, abstract_texts, ...)` per FR-009 and write `topics.json` next to that bundle. `topic_clusters` bundles write their own `topics.json` via T091 (`write_topic_clusters_bundle`); **`neuroscape_clusters` bundles do NOT ship a `topics.json` file** — the rollup writer (T037) joins `cluster_table.csv` directly when populating `cluster_topics` rows for the `neuroscape_clusters` clustering method

**Checkpoint**: `ohbmcli analyze-matrix` (full default) emits 40 bundles + the rollup; every clustering bundle ships a `topics.json`; `--skip-llm-topics` produces a fully-local run with no API calls.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Live validation of success criteria + documentation + constitution sweep.

- [X] T094 Update `README.md` Stage 4 section with the new `ohbmcli analyze-matrix` quickstart (mirror `specs/006-analysis-annotation/quickstart.md`); mention `analyze-umap-project` + `derive-neuroscape-centroids` aliases
- [X] T095 [P] Update `docs/reproducibility-vision.md` to list `data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}` as the canonical UI input + the per-bundle directory layout
- [X] T096 [P] Update `memory/summary.md` with Stage 4's design moves (one paragraph; nothing memory-sensitive)
- [ ] T097 Run the live quickstart against the current Stage 3 corpus `f0c51e80dc0e`: `ohbmcli analyze-matrix` → confirm **48 bundles** + 1 rollup pair land under `data/outputs/analysis/` (15 projections + 15 communities + 15 topic_clusters + 3 neuroscape_clusters; verify 12 `bundle_skipped` events for voyage/minilm/openai/pubmedbert × {abstract, claims, methods} on the neuroscape_clusters kind)
- [X] T097a [P] [US1] **Validate SC-004** — update the UI export step (`src/ohbm2026/ui.py`'s `export_ui_main` + `build_ui_main`) to consume `data/outputs/analysis/annotations__<state-key>.sqlite` + the per-cluster `topics.json` bundles instead of the legacy embedding-bundle scan; run `ohbmcli export-ui` end-to-end against the new Stage 4 outputs and confirm the resulting UI bundle surfaces UMAP coordinates + community labels + NeuroScape cluster labels + topic keywords. Legacy UI consumption code is replaced, not preserved. Add `tests/test_ui_export.py::test_consumes_stage4_rollup` to lock the new contract
- [ ] T098 Validate **SC-001** (< 30 min wall-clock) — record the live default-matrix wall-clock; if > 30 min, profile and either parallelize per-bundle work or raise the budget in spec with justification
- [ ] T099 Validate **SC-002** (< 60 s cached re-run) — rerun the same command immediately; record the wall-clock
- [ ] T100 Validate **SC-005** — Voyage manuscript-recipe communities at seed=42 produces ≥12 communities; largest ≤30%
- [ ] T101 Validate **SC-006** — NeuroScape angular-distance distribution over the Voyage→NeuroScape projected bundle: mean ≥0.15, std ≥0.05
- [ ] T102 Validate **SC-003** + **SC-007** with a determinism rerun + targeted test run (`unittest discover`); no test changes beyond import-path rewrites
- [X] T103 Secret-exposure review — `git diff` for the change MUST contain no token-shaped strings, no env contents, no OpenAI key fragments; `provenance.json` files contain no API keys
- [X] T104 Verify gitignore coverage — `data/outputs/analysis/`, `data/cache/analysis/`, `data/provenance/analysis/`, `data/inputs/neuroscape/` are all under existing gitignored roots; nothing under those paths gets `git add`-ed
- [X] T105 Audit error handling in `src/ohbm2026/analyze/*` — no bare `except:`, no `except Exception: pass`; every external-IO surface raises an `AnalysisError` subclass with diagnostic context
- [X] T106 Verify Principle VII compliance — centroid table version is read from `cluster_table.csv` (not hardcoded); UMAP bundle's `supported_algorithms` is discovered from the artifacts actually persisted (not a baked allow-list)
- [X] T107 Verify Principle VIII compliance — every bundle's `provenance.json` carries project-relative paths only; `_assert_paths_safe` rejects absolute paths in unit tests + at runtime
- [X] T108 Run `.specify/scripts/bash/constitution-check.sh --full` and address any reported violations
- [X] T108b Implement spec clarification Q2 (Session 2026-05-15): empty `src/ohbm2026/analyze/__init__.py` of its package-level re-export shell (drop ~120 import lines, leave only the module docstring) and migrate every consumer to explicit submodule paths: `src/ohbm2026/cli.py`, `src/ohbm2026/ui.py`, `src/ohbm2026/poster_layout.py`, `src/ohbm2026/category_evaluation.py`, plus the scripts `plot_voyage_stage2_umap_3d.py`, `write_topic_group_report.py`, `run_gmm_overlap_experiment.py`, `plot_poster_layout_floorplan.py`, `cluster_projection_silhouette.py`, and tests `test_neuroscape.py`, `test_neuroscape_derivation.py`. The test suite must stay at ≥548 passing / 1 pre-existing baseline error.
- [ ] T109 Final live `ohbmcli analyze-matrix --skip-llm-topics` run — verify zero OpenAI requests fire (verify against the runner's stdout summary which records `llm_calls: 0`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; runs first
- **Foundational (Phase 2 / US6)**: Depends on Setup; **BLOCKS every other story** (the new code can't live anywhere else once `analyze.py` is gone)
- **US1 (Phase 3)**: Depends on Foundational; runs first among the new code because it provides the orchestrator skeleton US3/US4/US5 plug into
- **US2 (Phase 4)**: Depends on Foundational + US1's `analyze.umap.write_projections_bundle` (T050 lands in Phase 4 but is consumed by US1's T040 — the dependency runs the other way; this is intentional, US1's projections dispatch waits on US2's UMAP module being in place)
- **US3 (Phase 5)**, **US4 (Phase 6)**, **US5 (Phase 7)**: Depend on Foundational + US1's orchestrator skeleton (T035). Once US1 is in place, US3/US4/US5 develop in parallel
- **Polish (Phase 8)**: Depends on every story being complete

### Inter-story dependencies (subtle)

- US1's `--kinds projections` slice (T040) calls `analyze.umap.write_projections_bundle` (T050 in US2). **Practical sequencing**: T050 must land before T040 (or T040 stubs the call). Treat US2's T048–T051 as a "Phase 3.5" that lands inline with US1.
- US5's topics-attachment pass (T093) writes `topics.json` next to bundles produced by US4 (communities) and US3 (neuroscape_clusters — but for these we use `cluster_table.csv` directly, not the spaCy/LLM pipeline). **Practical sequencing**: complete US3 + US4 before writing US5's T093.

### Within each user story

- Tests come first (the `tests/test_analyze_*.py` write tasks) — they MUST fail before implementation tasks land
- Submodule files marked [P] inside the same story are independent — different files, no shared state — and run in parallel
- The story's "wire into stage.py" task is always non-parallel (it touches the orchestrator)

### Parallel Opportunities

- **Phase 1 (Setup)**: T003 + T004 in parallel
- **Phase 2 (Foundational)**: T006 + T007 + T008 + T009 + T010 + T011 + T012 in parallel (each touches a different file); then T013 + T014 in parallel; then T016–T021 in parallel (different importer files)
- **Phase 3 (US1) tests**: T025 + T026 + T027 + T028 + T029 + T030 + T031 + T032 + T033 + T034 — all 10 test files / test functions are parallel
- **Phase 3 (US1) impl**: T035 + T036 + T037 + T040 are different files, parallel
- **Phase 4 (US2) tests**: T041 + T042 + T043 + T044 + T045 + T046 + T047 parallel
- **Phase 4 (US2) impl**: T048 + T049 + T050 + T051 parallel
- **Phase 5 (US3) tests**: T053 + T054 + T055 + T056 + T057 + T058 + T059 parallel
- **Phase 5 (US3) impl**: T060 + T061 + T062 + T063 + T064 parallel
- **Phase 6 (US4) tests**: T066 + T067 + T068 + T069 + T070 + T071 + T072 parallel
- **Phase 6 (US4) impl**: T073 + T074 + T075 + T076 + T077 parallel
- **Phase 7 (US5) tests**: T079 + T080 + T081 + T082 + T083 + T084 + T085 + T086 parallel
- **Phase 7 (US5) impl**: T087 + T088 + T089 + T090 + T091 parallel
- **Polish**: T094 + T095 + T096 + T097 (live run) launches; SC-* validations can interleave

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together (all hit different files):
Task: "Write tests/test_analyze_stage.py::test_dry_run_resolves_matrix"
Task: "Write tests/test_analyze_stage.py::test_missing_input_bundle_refusal"
Task: "Write tests/test_analyze_stage.py::test_cache_hit_skips_compute"
Task: "Write tests/test_analyze_stage.py::test_state_key_collision_refusal"
Task: "Write tests/test_analyze_rollup.py::test_parquet_sqlite_shape_equivalence"
Task: "Write tests/test_analyze_rollup.py::test_cluster_topics_join_semantics"
Task: "Write tests/test_analyze_rollup.py::test_column_ordering_deterministic"
Task: "Write tests/test_analyze_cli.py::test_analyze_matrix_delegates_to_stage_main"
Task: "Write tests/test_analyze_storage.py::test_atomic_bundle_write"
Task: "Write tests/test_analyze_provenance.py::test_assert_paths_safe"

# Then launch US1's impl files in parallel (different files):
Task: "Implement src/ohbm2026/analyze/stage.py::run_matrix"
Task: "Implement src/ohbm2026/analyze/stage.py::main (argparse + env loading)"  # same file as above — sequential with run_matrix
Task: "Implement src/ohbm2026/analyze/rollup.py::write_rollup"
```

---

## Implementation Strategy

### MVP First (Setup + Foundational + US1's `--kinds projections` slice + US2)

1. Complete Phase 1 (Setup) — dependencies in venv, spaCy model downloaded
2. Complete Phase 2 (Foundational) — reorganization green; SC-007 cleared
3. Land US2's UMAP module (T048–T051) so US1's projections dispatch has something to call
4. Complete Phase 3 (US1) — orchestrator + CLI + rollup; `ohbmcli analyze-matrix --kinds projections` works
5. **STOP and VALIDATE**: 15 projections bundles + a UMAP-only rollup land under `data/outputs/analysis/`; CLI emits the per-bundle JSON-per-line summary
6. Land US2's `project_into_umap` + CLI subcommand → fully testable out-of-corpus projection

### Incremental Delivery

7. Add US3 (NeuroScape centroids) — `ohbmcli analyze-matrix --kinds neuroscape_clusters` works; rollup grows cluster columns
8. Add US4 (Communities) — `ohbmcli analyze-matrix --kinds communities` works; communities columns join the rollup
9. Add US5 (Topic clusters + topics-attachment) — full default matrix runs end-to-end; `topics.json` ships with every clustering bundle
10. Polish: live SC-001…SC-007 validation, README + docs + memory updates, constitution lint pass

### Parallel Team Strategy

- Phase 2 has 14 file-disjoint reorganization tasks; one developer can drive them all, or four developers can split the file-disjoint subgroups (errors+storage+provenance / clusters+projections / embed neuroscape / importer fan-out)
- Phases 5–7 are file-disjoint (different submodules + different test files); three developers can land US3 + US4 + US5 simultaneously once Phase 3's orchestrator skeleton is in
- Polish work is sequential because it consumes the full integrated pipeline

---

## Notes

- Every Stage 4 test uses synthetic small matrices (≤200 rows) so the unit suite stays fast — live validation against the 3,244-row corpus happens in Polish (T097–T101)
- The `--skip-llm-topics` path is exercised in unit tests (T081) AND in Polish (T109) so a fully-local default run is always verifiable
- The reorganization (US6) is the riskiest phase by surface area; resist the temptation to rewrite anything beyond import-path rewrites + physical moves — SC-007 forbids it
- Commit each US's tests + implementation as separate slices per Principle V; do not batch the full Stage 4 into one commit
- No new artifact roots beyond those listed in plan.md; T104 in Polish gates that nothing new gets `git add`-ed
- Never silence test failures or bypass constitution-check.sh to make the suite green — T108 + T105 + T103 enforce this
