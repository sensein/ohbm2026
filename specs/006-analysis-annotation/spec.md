# Feature Specification: Stage 4 — Analysis & Annotation

**Feature Branch**: `006-analysis-annotation`
**Created**: 2026-05-14
**Status**: Draft
**Input**: User description: "Next stage (analysis/annotation). UMAPs, community detection, cluster assignments based on the NeuroScape centroids, topic modeling. Focus on entire-abstract (title+intro+methods+results+conclusion) and claims embeddings as the two canonical input sources, with an option to generate annotations for other recipes/components. For UMAP, generate both 2D and 3D and provide a function to embed a new embedding into an existing UMAP space (with different algorithms). Clean up the code into appropriate stage-specific organization and utilities."

## Clarifications

### Session 2026-05-14

- Q: Which embedding models does the default Stage 4 matrix cover? → A: **All five models** — voyage, minilm, openai, pubmedbert, neuroscape (the published Stage-2 lens applied to Voyage). Operators may still filter via CLI; the default is "all".
- Q: Should `ohbm2026.analyze` keep a backward-compatibility shim after the `analyze/` package reorganization? → A: **No legacy shim.** The flat `analyze.py` module is deleted; every caller (cli.py, scripts/, tests/) is updated to the new `analyze/` package paths in this same change.
- Q: Are topics a separate analysis kind, or a per-cluster attribute of every clustering? → A: **Per-cluster attribute.** Every clustering method (communities, NeuroScape clusters, topic-model clusters) produces a row-aligned "topic list per cluster" alongside its cluster assignments. Topic modeling stays as one clustering METHOD but is no longer a standalone analysis kind.
- Q: Should Stage 4 emit a single rollup file the UI can consume in one read? → A: **Yes.** A canonical aggregate (`annotations.sqlite` or `annotations.parquet`) per corpus_state_key composes per-abstract rows with: id, UMAP 2D/3D coordinates for every embedding model, cluster labels for every clustering method, and joinable cluster→topic-list tables.
- Q: How should community detection, centroid computation, and topic / cluster labeling be done? → A: **Match the published NeuroScape recipe.** kNN graph via FAISS `IndexFlatIP` (cosine on normalized embeddings) + symmetrize; Leiden with `CPMVertexPartition` and a resolution-parameter sweep; **spherical** (mean-on-hypersphere) centroids — convert to polar, take `mean_angle` per cluster, back to cartesian; **LLM-driven cluster definition** — feed cluster member abstracts to an LLM with a structured prompt returning `{Keywords[], Title, Description, Focus}` JSON. This replaces the earlier BERTopic / HDBSCAN / c-TF-IDF default.
- Q: Where does the NeuroScape centroid table come from for `neuroscape_clusters` assignment? → A: **Pre-compute once from the published NeuroScape corpus.** NeuroScape ships `neuroscience_articles_1999-2023.csv` (461k articles × Cluster ID) + `DomainEmbeddings/*.h5` shards (the Stage-2 projected 64-dim vectors). Stage 4 adds a one-off setup step (`scripts/derive_neuroscape_centroids.py`) that groups the published vectors by `Cluster ID` and applies the spherical-mean to write a 2632-row centroid file at `data/inputs/neuroscape/centroids__<table_version>.{npy,csv}`. Stage 4's `neuroscape_clusters` analysis kind reads this precomputed file and assigns each abstract to the nearest centroid in spherical (angular) distance.
- Q: How should topic/keyword extraction work — pure LLM, pure local, or hybrid? → A: **spaCy phrase extraction + LLM as a grouping pass over the phrase list.** Per cluster: spaCy (`en_core_web_md` baseline; optional scispacy add-on) extracts noun-chunks + named entities → canonicalize (lowercase + lemmatize + dedupe) → class-based TF-IDF across clusters → keep the top-N (default 60) candidate phrases. Then ONE LLM call per cluster receives just the candidate-phrase list (NOT the raw abstracts) and is asked to (a) pick the best keyword_out_n (default 15) phrases from the list, (b) write a Title, (c) write a Description, (d) classify Focus. Post-response guard: emitted `Keywords ⊆ candidate_phrases` — the LLM is allowed to re-rank/group but cannot invent terms. With `--skip-llm-topics`, Stage 4 emits the top-N c-TF-IDF phrases directly as `Keywords` and leaves Title/Description/Focus empty — no API key required.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Generate the canonical analysis suite for the two default inputs (Priority: P1) 🎯 MVP

A researcher running the analysis pipeline against the current 3244-abstract Stage 3 bundles needs the full set of post-embedding artifacts: UMAP projections (2D + 3D), community labels, NeuroScape-cluster assignments, and topic labels. The two canonical inputs are the **manuscript recipe** (`title+introduction+methods+results+conclusion`, composed at consumption time from the per-component embedding bundles) and the **claims component** (the single per-abstract `claims` bundle directly). The researcher invokes one canonical Stage 4 entrypoint that produces, for each `(input_source, analysis_kind)` pair, a self-contained annotation bundle directory consumable by the UI export, the poster-layout proposals, and the cluster-quality dashboards.

**Why this priority**: Every downstream consumer (UI search lens, poster-layout sequencer, cluster-summary dashboards, organizer-facing topic narratives) depends on Stage 4's annotations. Until they exist for the current corpus, none of those workflows can run. The two canonical inputs cover ~95% of the visible use cases, so an MVP that locks them in is the minimum-viable pipeline.

**Independent Test**: Run the canonical command against the current Stage 3 bundles for one input. Verify the bundle directory contains the four required artifact types (`umap2d/`, `umap3d/`, `communities/`, `neuroscape_clusters/`, `topics/`) and that each carries `metadata.json` + `provenance.json` plus the analysis-specific payload (assignments, coordinates, labels). Verify an existing consumer (the UI export step) reads at least one of them without modification.

**Acceptance Scenarios**:

1. **Given** the Stage 3 bundles at corpus_state_key `f0c51e80dc0e`, **When** the operator runs Stage 4 with no filters, **Then** the runner produces all default-matrix annotations under `data/outputs/analysis/<input_key>/<analysis_kind>__<state_key>/` for the two canonical inputs across the default model lineup, and emits one JSON summary per artifact on stdout plus a run-level rollup.

2. **Given** the same input bundles and command, **When** Stage 4 is rerun, **Then** every annotation artifact is byte-equivalent to the prior run (modulo timestamps) — analyses are deterministic with respect to (corpus_state_key, input source, algorithm config, seed).

3. **Given** a requested input source whose per-component bundles aren't on disk, **When** Stage 4 runs, **Then** the runner exits with a typed `AnalysisError` naming the missing bundle and the expected path, before performing any other work.

---

### User Story 2 — Embed a new abstract into an existing UMAP space (Priority: P1)

A researcher receives an embedding for a newly submitted abstract (or any out-of-corpus vector) and wants to place it in the same 2D/3D UMAP plot as the 3244-abstract baseline — without re-fitting UMAP across the whole corpus (which would re-shuffle every other abstract's coordinates and break visual continuity). The pipeline exposes a `project_into_umap(new_vectors, fitted_umap_bundle, algorithm=…)` function that returns the new 2D/3D coordinates in the existing UMAP space. Multiple algorithms are supported: native UMAP `transform()` (when the fitted UMAP model is available), kNN-weighted reprojection (model-free; works on saved coords + a reference matrix), and an explicit parametric variant.

**Why this priority**: Same-priority as P1 — the UI, the poster-layout proposals, and the cluster-quality dashboards all assume "new points land in the same plot." Without an out-of-corpus projection API, every late-arrival abstract forces a full UMAP re-fit, which invalidates downstream interpretation (a cluster's coordinates drift on every reseed).

**Independent Test**: Fit a UMAP on a 100-abstract synthetic sample. Hold out 10 abstracts. Project each holdout into the fitted UMAP space three ways — native `transform`, kNN-weighted, parametric — and verify (a) each algorithm returns the right shape, (b) holdout points land in the convex hull of their nearest in-sample neighbors, and (c) repeated calls with the same `(holdout_vectors, fitted_umap_bundle, algorithm)` triple return byte-identical coordinates.

**Acceptance Scenarios**:

1. **Given** a fitted UMAP bundle (saved model + reference matrix + reference coords), **When** the operator calls `project_into_umap(new_vectors, bundle, algorithm="native")` for a 10-vector batch, **Then** the returned matrix is shape `(10, dim)` (2 or 3) and each new coordinate is within the convex hull of its 10 nearest-neighbor reference coordinates.

2. **Given** the same bundle and `algorithm="knn_weighted"`, **When** the operator calls the function, **Then** it returns a matrix without requiring the saved UMAP model object (which may be absent because the operator only stashed the reference coordinates).

3. **Given** an algorithm name the function does not recognize, **When** the operator calls it, **Then** the function raises a typed `AnalysisError` naming the supported algorithms.

---

### User Story 3 — Cluster assignment via NeuroScape centroids (Priority: P2)

A researcher wants to label each Stage 3 abstract with its corresponding NeuroScape published-domain cluster (the same labels that NeuroScape Stage 1 used for its training corpus). The pipeline reads the canonical NeuroScape cluster-centroid table that ships with the published Stage-2 model, computes the nearest centroid in the published embedding space for each abstract, and persists the resulting cluster id + cluster label + cosine distance per abstract.

**Why this priority**: NeuroScape is the project's primary cross-corpus reference lens. Aligning to NeuroScape's cluster ids lets the UI / organizer narratives reuse NeuroScape's domain vocabulary instead of inventing a local one. Important but downstream of the UMAP / community work (P1).

**Independent Test**: Apply NeuroScape-centroid assignment over a 50-abstract sample. Verify (a) every abstract receives a NeuroScape cluster id from the published vocabulary, (b) the distance distribution has a sensible tail (no all-uniform 1.0s indicating a bug in the cosine call), (c) reapplying the assignment is byte-identical.

**Acceptance Scenarios**:

1. **Given** the NeuroScape Stage-2 model checkpoint and its co-distributed centroid table, **When** the operator runs cluster assignment over the Voyage→NeuroScape projected bundles, **Then** each abstract receives one cluster id, one cluster label, and one cosine distance; the distribution of distances is recorded in the bundle's `metadata.json`.

2. **Given** the published centroid table is missing or doesn't match the model's checkpoint version, **When** the operator runs the assignment, **Then** the runner fails loudly with a typed error naming the missing artifact.

---

### User Story 4 — Community detection on the embedding kNN graph (Priority: P2)

A researcher wants emergent (data-driven, not predefined) groups of abstracts to complement the NeuroScape-assigned clusters. The pipeline builds a kNN graph over the chosen embedding, runs a community-detection algorithm (Louvain or Leiden) at a configurable resolution, and persists `community_id` + `community_size_rank` per abstract.

**Why this priority**: Community detection is the canonical "what topics exist in this conference" lens. Equally useful to the UI but not as cross-corpus-comparable as the NeuroScape-centroid alignment.

**Independent Test**: Run community detection on a 200-abstract synthetic corpus where three of the abstracts are deliberate duplicates with permuted-but-near-identical vectors. Verify the three near-duplicates end up in the same community.

**Acceptance Scenarios**:

1. **Given** a fitted embedding matrix and a target community count via resolution, **When** the operator runs the community detector, **Then** every abstract receives a `community_id`, communities are ordered by size, and the modularity score is recorded in `metadata.json`.

2. **Given** a fixed seed, **When** the operator reruns the detector twice with identical inputs, **Then** community assignments are byte-identical (label-stable).

---

### User Story 5 — Topic modeling on the canonical inputs (Priority: P3)

A researcher wants human-readable topic labels per abstract — distinct from cluster ids — to drive narrative/summary surfaces in the UI. The pipeline runs a topic model over the same canonical inputs (manuscript-recipe and claims) and persists topic-id + topic-label + topic-weight per abstract, plus a per-topic keyword summary.

**Why this priority**: Narrative surfaces are nice-to-have for organizer-facing dashboards. Lower priority than clusters/communities (which the UI already needs).

**Independent Test**: Run topic modeling on a synthetic 100-abstract corpus with three deliberate topic clusters. Verify the model recovers approximately three topics and that abstracts seeded with the same topic land in the same topic-id bucket >= 80% of the time.

**Acceptance Scenarios**:

1. **Given** a chosen number of topics, **When** the operator runs topic modeling, **Then** each abstract receives one primary topic id and a top-k secondary topic distribution; per-topic keyword summaries are written to the bundle's `topics.json`.

2. **Given** a corpus with an open-ended topic count, **When** the operator runs the model with `n_topics=None`, **Then** the runner picks a reasonable default via the documented elbow / coherence rule and records the choice in `metadata.json`.

---

### User Story 6 — Package the post-embedding analysis code (Priority: P2)

The `src/ohbm2026/analyze.py` module is currently ~2790 lines of mixed concerns (UMAP, t-SNE, clustering benchmark, community detection, projection comparison, Stage-2 NeuroScape model code, manifest writer). It needs the same per-package treatment Stage 1, 2, and 3 already received: an `analyze/` package with `umap.py`, `clusters.py`, `communities.py`, `topics.py`, `neuroscape.py`, `projections.py`, etc. Move the Stage-2 NeuroScape model code into `embed/neuroscape.py` (replacing the current re-export façade with the real implementation). Keep the per-stage public surface re-exported via each package's `__init__.py`.

**Why this priority**: This is structural cleanup that accompanies Stage 4 rather than blocking it. Doing it as part of Stage 4 means every new file the pipeline introduces (UMAP transform, topic model, community detector) lands in its proper home from the start instead of being moved later.

**Independent Test**: After the reorganization, `from ohbm2026.analyze.umap import compute_umap_projection` and `from ohbm2026.embed.neuroscape import apply_stage2_model` both work without going through `ohbm2026.analyze`. The legacy `ohbm2026.analyze` import path keeps working as a backward-compat shim for downstream scripts.

**Acceptance Scenarios**:

1. **Given** the existing test suite for analysis tools (`tests/test_neuroscape.py` plus any Stage 4 tests added), **When** the suite runs after the reorganization, **Then** every test passes without modification beyond import-path rewrites.

2. **Given** the existing CLI subcommands (`cluster-benchmark`, `umap-plot`, `compare-projections`, etc.), **When** the operator invokes each one, **Then** they continue to work and reach the new module paths.

---

### Edge Cases

- An operator requests Stage 4 against an input source whose per-component bundles partially overlap with the corpus (e.g., one component has 3242 rows because two abstracts have empty claims). The runner MUST emit annotations only for abstracts that appear in the composed input matrix; abstracts absent from the input are explicitly excluded from the output (not given a null cluster id), and the count is recorded in `metadata.json`.
- A new abstract's vector is fed to `project_into_umap` whose dimension does not match the fitted UMAP's reference matrix. The function MUST raise a typed `AnalysisError` naming the mismatch (e.g., "expected 384-dim input, got 1024").
- The NeuroScape centroid table version disagrees with the Stage-2 model checkpoint version. The runner MUST refuse to proceed and explicitly request the operator re-download / re-pin the centroid file.
- An operator requests `topic_clusters --inputs claims` for abstracts with empty claims. Those abstracts MUST be excluded from `topic_cluster_ids` (recorded as missing in `metadata.json`).
- An operator requests `neuroscape_clusters` for a source model whose embedding dimension is incompatible with the published Stage-2 lens (i.e., `model ∈ {minilm, openai, pubmedbert}`). The runner MUST skip the `(model, neuroscape_clusters)` pair by default and emit a structured `skipped` event recording the reason; with `--strict-matrix`, it MUST raise a typed `AnalysisError` naming the incompatible model + expected dim.
- A community-detection run produces a single dominant community holding >90% of abstracts. The runner MUST emit a warning and still write the bundle — the operator may want to adjust resolution; the runner should not silently substitute a different resolution.
- Two simultaneous Stage 4 runs (different operators, same corpus) write to the same output paths. State-key suffixing on the bundle directory (matching the Stage 3 pattern) MUST prevent collision; the second run lands at a fresh path if the analysis-run state_key differs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a single canonical Stage 4 CLI entrypoint that takes one or more `(input_source, analysis_kind)` pairs as input and produces, for each pair, an annotation bundle directory under `data/outputs/analysis/<input_key>/<analysis_kind>__<state-key>/`.
- **FR-002**: The two canonical input sources for the default matrix MUST be: `<model_key>_abstract` (the manuscript recipe `title+introduction+methods+results+conclusion` composed via `embed.compose.compose_recipe` from the per-component bundles) and `<model_key>_claims` (the single-component `claims` bundle for that model). **The default model set MUST be all five embedding models — `voyage`, `minilm`, `openai`, `pubmedbert`, `neuroscape`.** Operators may filter via CLI (`--models …`); the default is "all". **Model-compatibility constraint for `neuroscape_clusters`**: the `neuroscape_clusters` analysis kind requires Voyage-dimension input because the published Stage-2 lens (`embed.neuroscape.apply_stage2_model`) was trained on Voyage embeddings. The matrix MUST automatically skip `(model, neuroscape_clusters)` pairs for `model ∈ {minilm, openai, pubmedbert}` and emit a structured `skipped` event for each, recording the reason. `(voyage, neuroscape_clusters)` projects through Stage-2 before assignment; `(neuroscape, neuroscape_clusters)` consumes the Stage 3 bundle directly (it is already in the published 64-dim space). The runner MUST raise a typed error if an operator force-requests `neuroscape_clusters` on an incompatible model via `--strict-matrix`.
- **FR-003**: The system MUST produce four analysis-kind artifacts per `(model, input_source)` pair for v1: `projections` (carries both 2D and 3D UMAP coordinates), `communities` (kNN-graph community detection), `neuroscape_clusters` (nearest-centroid assignment in the published NeuroScape space), and `topic_clusters` (a topic-model-driven clustering, e.g., BERTopic-style). **Every clustering analysis kind (`communities`, `neuroscape_clusters`, `topic_clusters`) MUST also emit a per-cluster `topics` artifact** — a row-aligned list of representative keywords / phrases per cluster, derived via c-TF-IDF or equivalent over the cluster's member texts.
- **FR-004**: The system MUST be invocable for ad-hoc inputs beyond the default matrix: any `(model_key, recipe-or-component)` combination that resolves to a valid embedding (per `embed.compose.compose_recipe`) MUST be a legal input source.
- **FR-005**: Every UMAP bundle MUST persist enough state for out-of-corpus projection: the fitted UMAPModel (when the algorithm supports it), the reference embedding matrix, the reference coordinates, and the hyperparameter set used.
- **FR-006**: The system MUST expose a `project_into_umap(new_vectors, fitted_umap_bundle, algorithm=…)` function (also reachable via CLI `analyze-umap-project`) that returns the projected coordinates in the existing UMAP space. Supported algorithms for v1: `native` (uses the fitted UMAPModel's `transform`), `knn_weighted` (model-free; weighted-mean of the k=15 nearest reference coordinates), and `parametric` (a small neural mapping fitted at project-time and persisted with the bundle).
- **FR-007**: The system MUST run community detection following the published NeuroScape recipe: a FAISS-backed `IndexFlatIP` kNN graph over **L2-normalized** embedding vectors (inner product equals cosine similarity), symmetrized; Leiden via `leidenalg.find_partition` with `CPMVertexPartition` and weighted edges; a configurable **resolution-parameter sweep** (default: 20 resolutions linearly spaced over `(min_res, max_res]`); the runner records per-resolution modularity + community count and selects the resolution whose modularity is plateauing as the cluster count grows. The resulting `community_id`s MUST be ordered by descending community size so the most populous community is always `0`.
- **FR-008**: The system MUST assign NeuroScape cluster ids by (a) projecting each abstract's embedding into the published NeuroScape Stage-2 space via `embed.neuroscape.apply_stage2_model` when the source model is `voyage` (and skipping the projection step when the source model is `neuroscape` — those vectors are already in the published 64-dim space), (b) loading a **precomputed centroid file** at `data/inputs/neuroscape/centroids__<table_version>.npy` (companion `cluster_table.csv` carries Cluster ID → Title / Description / Keywords / Focus from `neuroscience_clusters_1999-2023.csv`), and (c) computing the nearest centroid by **spherical** angular distance on the unit hypersphere. The centroid file is produced once via `scripts/derive_neuroscape_centroids.py`, which reads the published NeuroScape `DomainEmbeddings/*.h5` shards + `neuroscience_articles_1999-2023.csv`, groups by Cluster ID, applies the `get_centroids` spherical-mean recipe, and writes the resulting 2632-row centroid matrix. The bundle records the centroid-table version (which is itself the source-data sha256 hash, truncated to 12 hex chars) and the per-abstract angular-distance distribution in `metadata.json`.
- **FR-009**: Every clustering analysis kind MUST emit a per-cluster `topics` artifact via a **two-stage hybrid pipeline**:
  1. **Local phrase extraction (spaCy + c-TF-IDF)** — per cluster, run spaCy (`en_core_web_md` baseline; `scispacy/en_core_sci_lg` opt-in via flag) over the cluster's member abstract texts, harvest noun-chunks + named entities, canonicalize (lowercase + lemmatize + dedupe), score each candidate by class-based TF-IDF across clusters, keep the top-N (default 60) phrases. This stage is fully local; no API needed.
  2. **LLM grouping pass (optional, opt-out via `--skip-llm-topics`)** — for each cluster, send the candidate-phrase list (NOT the raw abstracts) to an OpenAI chat model with a strict-schema prompt returning `{Keywords: list[str], Title: str, Description: str, Focus: "themes" | "methodologies"}`. Post-response guard: `Keywords ⊆ candidate_phrases` — the LLM can re-rank/group but cannot invent terms. Cache keyed by `sha256(model_id || prompt_version || sorted(candidate_phrases))` so reruns hit cache.

  When the LLM stage is skipped, the topics artifact contains the top-N c-TF-IDF phrases directly as `Keywords` and leaves `Title`/`Description`/`Focus` empty. The topics artifact is row-aligned with `cluster_id` so consumers can join cluster → topic-list in one read.
- **FR-010**: Every annotation bundle MUST include row-aligned id arrays (`ids.npy` or equivalent) plus the analysis payload, so consumers can match the abstract id of every row without going through `metadata.json`.
- **FR-011**: The system MUST emit a per-bundle run summary on stdout in a single JSON object (consistent with Stage 3's contract) and a run-level matrix summary at the end.
- **FR-012**: The system MUST fail loudly when an input source is missing on disk, when a NeuroScape centroid table is missing or version-mismatched, or when `project_into_umap` is asked for an algorithm not supported by the fitted bundle (e.g., `native` against a bundle that only persisted reference coordinates, no UMAPModel).
- **FR-013**: The system MUST refuse to overwrite an existing annotation bundle whose `corpus_state_key` or `embedding_state_key` differs from the current run's, mirroring the Stage 3 FR-013 contract.
- **FR-014**: The Stage 4 entrypoint MUST be invocable via `ohbmcli analyze-matrix` (single canonical command) and `scripts/run_analyze_matrix.py` (the venv-only wrapper).
- **FR-015**: Provenance for every annotation bundle MUST list project-relative paths only, matching Stage 1/2/3's `_assert_paths_safe` contract.
- **FR-016**: The `analyze.py` module MUST be reorganized into a `analyze/` package containing: `analyze/stage.py` (orchestrator), `analyze/umap.py` (UMAP fitting + transform + bundle I/O), `analyze/clusters.py` (clustering + cluster benchmarks), `analyze/communities.py` (Leiden + CPM community detection over the FAISS kNN graph), `analyze/centroids.py` (spherical centroids + nearest-centroid assignment), `analyze/topics.py` (LLM-driven cluster-definition / topics artifact), `analyze/projections.py` (UMAP/t-SNE visualization HTML), `analyze/rollup.py` (single-file UI aggregate writer), and `analyze/storage.py` (bundle + cache atomic I/O). Stage-2 NeuroScape model code (currently in `analyze.py`) MUST physically move to `embed/neuroscape.py`, replacing the current re-export façade. **No backward-compat shim** — `ohbm2026.analyze` as a flat module is deleted; every caller (cli.py, scripts/, tests/) is updated to the new package paths in this same change.
- **FR-017**: Every analysis runner MUST cache per-input intermediate state under `data/cache/analysis/<analysis_kind>/<cache_key>.json` so reruns reuse computed UMAPs, communities, topics, etc. Cache key is `sha256(input_matrix_hash || algorithm_config || seed || prompt_version_when_applicable)`.
- **FR-018**: After all per-`(model, input_source, analysis_kind)` bundles complete, the system MUST emit a **canonical UI rollup** at `data/outputs/analysis/annotations__<state-key>.parquet` (parquet) and `annotations__<state-key>.sqlite` (sqlite) — both shape-equivalent for ease of consumption. The rollup MUST contain at least these columns: `abstract_id`, `umap2d_<model>_x`, `umap2d_<model>_y`, `umap3d_<model>_x`, `umap3d_<model>_y`, `umap3d_<model>_z` for each model present, `community_<model>_<input>` per model+input cluster method, `neuroscape_cluster_<model>_<input>` per assignment, `topic_cluster_<model>_<input>` per topic-model cluster. A second joinable table (`cluster_topics`) MUST map `(clustering_method, model, input, cluster_id) → topic_keywords, topic_title, topic_description, topic_focus`.

### Key Entities

- **Input source**: A pair `(model_key, recipe_or_component)` that resolves to a single 2-D matrix of embeddings via `embed.compose.compose_recipe`. The canonical pair set for v1 is `{(model, "abstract"), (model, "claims")}` for each requested model.
- **Analysis kind**: One of `projections | communities | neuroscape_clusters | topic_clusters`. The `projections` kind carries BOTH 2D and 3D UMAP coordinates in one bundle (it is not split into separate `umap2d` / `umap3d` kinds). Every clustering kind (`communities`, `neuroscape_clusters`, `topic_clusters`) carries an associated topic-keyword list as a per-cluster attribute — topics are NOT a standalone analysis kind. Each kind shares the metadata + provenance pattern.
- **Annotation bundle**: A directory under `data/outputs/analysis/<input_key>/<analysis_kind>__<state-key>/` carrying the per-abstract result of one analysis on one input source. The unit of cache-aware regeneration.
- **Fitted UMAP bundle**: A `projections` bundle that additionally persists the fitted UMAPModel (when serializable) + the parametric MLP (when fitted) + the reference matrix + the reference coordinates, so out-of-corpus projection (US2) can land new points without re-fitting.
- **Analysis-matrix run**: An operator invocation that requests one or more `(input_source, analysis_kind)` annotations. Reports per-bundle outcomes + a matrix-level summary.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python execution for this feature MUST use the repository-local `.venv/bin/python` interpreter or `uv` targeting that interpreter. The Stage 4 entrypoint follows the existing `scripts/run_*.py` pattern.
- **CA-002**: Tests MUST be added or identified before implementation for each behavior-changing user story: golden per-input matrix assembly, deterministic UMAP fit + transform, deterministic community detection with a fixed seed, NeuroScape-centroid assignment determinism + missing-centroid-table refusal, topic-model deterministic recovery on a synthetic three-cluster corpus, and the `project_into_umap` per-algorithm round-trips.
- **CA-003**: This change reorganizes the existing `analyze.py` module. Every consumer (cli.py, scripts/, downstream PRs that may have referenced the old paths) MUST be updated in the same change. README, CLAUDE.md, and `docs/reproducibility-vision.md` MUST be updated to point at the new package paths.
- **CA-004**: The optional LLM grouping pass (FR-009 stage 2) consumes `OPENAI_API_KEY` — loaded from `.env` in-memory only (never `os.environ.set`-style), passed to the SDK constructor exactly as Stage 2.1 and Stage 3 do. The LLM stage is **opt-out**: passing `--skip-llm-topics` produces a fully local run with no API dependency. Other analysis kinds (UMAP, communities, centroids, rollup) operate on already-persisted vectors and need no credentials.
- **CA-005**: Every new directory under `data/outputs/analysis/`, `data/cache/analysis/`, and `data/provenance/` lands under existing gitignored roots. The spec MUST NOT propose tracking any generated annotation artifact in the repository.
- **CA-006**: External-call failures MUST be explicit: missing centroid tables, missing input bundles, missing UMAPModel for a `native` projection — each surfaces as a typed `AnalysisError` (or the relevant subclass).
- **CA-007**: NeuroScape centroid table version + checksum MUST be discovered at runtime from the artifact's own metadata, NOT matched against a hardcoded constant. Mismatches between the table version and the Stage-2 model checkpoint MUST raise.
- **CA-008**: Every annotation bundle MUST ship with a `provenance.json` co-located with `metadata.json`, carrying project-relative paths only and the full input-hash chain (`corpus_state_key → input_source_assembly_hash → algorithm_config → cache_key`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fresh Stage 4 run against the current Stage 3 bundles (corpus_state_key `f0c51e80dc0e`) produces all default-matrix annotation bundles in under **30 minutes** wall-clock on a single workstation. The default matrix is **34 bundles**: 10 `projections` (5 models × 2 inputs) + 10 `communities` (5 × 2) + 10 `topic_clusters` (5 × 2) + 4 `neuroscape_clusters` (Voyage + NeuroScape × 2 inputs; the other three models are auto-skipped per FR-002's model-compatibility constraint).
- **SC-002**: A cached re-run with no input changes completes in under **60 seconds** (every analysis hits cache; no recomputation).
- **SC-003**: `project_into_umap(new_vectors, bundle, algorithm=X)` is deterministic: two calls with the same `(new_vectors, bundle, algorithm)` return byte-identical coordinates for every supported algorithm.
- **SC-004**: The UI export step (`ohbmcli export-ui` / `build-ui`) is updated to consume the canonical Stage 4 rollup (`data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}`) plus at least one per-cluster `topics.json` bundle, and produces a UI bundle that surfaces the new UMAP coordinates, community labels, NeuroScape cluster labels, and topic keywords. UI code changes are EXPECTED for this stage — the SC verifies the new Stage 4 outputs are the canonical input format the UI consumes going forward, not that the UI remained untouched. The legacy UI export path is replaced, not preserved.
- **SC-005**: Community detection on the 3244-abstract Voyage manuscript-recipe embedding (default Leiden, resolution=1.0, seed=42) produces at least 12 communities with the largest community holding ≤ 30% of abstracts.
- **SC-006**: NeuroScape cluster assignment over the 3244-abstract Voyage→NeuroScape projected embedding produces a non-degenerate distance distribution (mean cosine distance ≥ 0.15, std ≥ 0.05) — verifies the centroid lookup isn't a no-op.
- **SC-007**: The `analyze.py` → `analyze/` reorganization keeps every passing test green; the only allowed diff is import-path rewrites.

## Assumptions

- The canonical Stage 3 bundles already exist on disk at `data/outputs/embeddings/<model>/<component>__<state-key>/`. Stage 4 does NOT re-embed; it consumes vectors only.
- Compose-recipe semantics (mean-pool over present components per abstract) for the manuscript recipe match the Stage 3 spec's FR-006a contract. Stage 4 treats the composed matrix as opaque embedding input.
- The NeuroScape centroid table is **derived once** from the published `DomainEmbeddings/*.h5` + `neuroscience_articles_1999-2023.csv` by a one-off setup script (`scripts/derive_neuroscape_centroids.py`); the resulting `centroids__<table_version>.npy` + `cluster_table.csv` are operator-supplied to Stage 4 via `--neuroscape-centroids data/inputs/neuroscape/`. The derivation needs `h5py` (added to the `[analysis]` extra in `pyproject.toml`).
- "Topic modeling" is a **two-stage hybrid**: spaCy phrase extraction + class-based TF-IDF scoring (local, deterministic, no API) feeds a 60-phrase candidate list per cluster, then an optional one-call-per-cluster LLM pass groups/re-ranks the phrases and emits `{Title, Description, Focus}`. Passing `--skip-llm-topics` produces a fully-local run; the canonical pipeline runs the LLM pass because the UI consumes the richer labels. The LLM operates on phrase lists not raw abstracts, so the per-call token budget is ~3k (vs ~30k for a raw-abstract approach) — full-corpus cost at `gpt-5.4-mini` flex is ~$0.15 for ~100 clusters.
- "Community detection" follows the published NeuroScape `community_detection.py` recipe: FAISS `IndexFlatIP` kNN graph over L2-normalized vectors, symmetrize, then Leiden with `CPMVertexPartition` swept over a configurable resolution range. The default sweep picks the resolution at the modularity plateau as the cluster count grows.
- "Centroids" use NeuroScape's spherical-mean recipe (polar → mean_angle → cartesian) on the unit hypersphere, NOT Euclidean-mean centroids on raw vectors.
- "UMAP" defaults to the `umap-learn` library's standard algorithm with `n_neighbors=15`, `min_dist=0.1`. v1 produces a single `projections` bundle per `(model, input_source)` carrying BOTH 2D and 3D coordinates side-by-side.
- The annotation matrix produces **34 per-bundle artifacts by default**: 10 `projections` (5 models × 2 inputs) + 10 `communities` (5 × 2) + 10 `topic_clusters` (5 × 2) + 4 `neuroscape_clusters` (only `voyage` and `neuroscape` are dim-compatible with the published Stage-2 lens; minilm / openai / pubmedbert are auto-skipped). Operators can request additional `(model, input)` combinations or skip kinds via CLI flags; `--strict-matrix` turns the auto-skip into a typed error.
- `project_into_umap` algorithm support: `native` (UMAPModel.transform) requires the fitted UMAPModel to be persisted. `knn_weighted` works on the saved reference matrix + coords. `parametric` fits a small neural mapper at project-time and persists it alongside the bundle. v1 ships all three; v2 may add a Procrustes-aligned variant.
- The `analyze.py` reorganization (FR-016 / SC-007) is structural and lands in the same change as Stage 4. The `embed/neuroscape.py` façade gets the real Stage-2 model implementation moved into it, replacing the re-export.
- Stage 4 adds the following dependencies as an opt-in `[analysis]` extra in `pyproject.toml`: `umap-learn` (UMAP fit + transform), `faiss-cpu` (kNN graph for community detection), `python-igraph` + `leidenalg` (Leiden CPM partitioning), `spacy` (noun-chunk + NER phrase extraction; baseline model `en_core_web_md`), `h5py` (one-off NeuroScape centroid derivation), `pyarrow` (parquet rollup; promoted from the existing `[parquet]` extra), `scikit-learn` (c-TF-IDF + cosine helpers; typically already present transitively), and `hdbscan` (used by `topic_clusters`). An opt-in `[analysis-sci]` extra adds `scispacy` + `en_core_sci_lg` for scientific-NER phrase extraction.
- Stage 4 outputs the bundles in a layout consistent with Stages 1–3: `data/outputs/analysis/<input_key>/<analysis_kind>__<state-key>/`, with run-level provenance under `data/provenance/`.
