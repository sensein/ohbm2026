# Phase 0 — Research (Stage 4 Analysis & Annotation)

All Stage 4 algorithmic choices are pinned in the spec's seven clarifications and Assumptions block. This document records why each choice was made and the alternatives evaluated so future operators can audit (or revisit) the decisions without re-reading the spec.

## 1. Community detection — FAISS `IndexFlatIP` + Leiden + CPM

**Decision**: Build the kNN graph with FAISS `IndexFlatIP` over **L2-normalized** vectors (inner product on the unit hypersphere equals cosine similarity), **symmetrize** the resulting adjacency, then run `leidenalg.find_partition(..., partition_type=leidenalg.CPMVertexPartition, resolution_parameter=r, weights=...)` over a **20-point linear resolution sweep** `(min_res, max_res]` and pick the resolution at the "modularity plateau as cluster count grows" elbow.

**Rationale**: This is exactly the published NeuroScape recipe (`community_detection.py`) the project already aligns to elsewhere. FAISS gives us a single-machine, no-extra-services kNN graph builder that scales to 3k–500k rows trivially. Leiden + CPM is the published default; the modularity-plateau heuristic is what NeuroScape uses to pick the operating resolution rather than a baked-in constant.

**Implementation notes**:
- L2-normalize via `numpy` (already used in `analyze.py:_normalize_rows`); FAISS expects float32 contiguous.
- Symmetrize with `(A + A.T) / 2` then keep edges above zero.
- Convert to `igraph.Graph` via `Graph.Weighted_Adjacency` (or `from_numpy_array` if we prefer).
- Order returned `community_id`s by descending size so the largest community is always `0` (FR-007).

**Alternatives considered**:
- HNSW kNN (`hnswlib`) — faster on huge corpora but unnecessary at 3k–10k rows; introduces extra dep with no win.
- Louvain (`python-louvain`) — Leiden strictly dominates on modularity + connected-community guarantee.
- Pre-computed kNN matrix from `analyze.build_knn_graph` (sklearn-based) — superseded; FAISS+IP is the published recipe and ~10× faster on dense matrices.

## 2. Centroid recipe — Spherical mean on the unit hypersphere

**Decision**: Compute centroids per cluster id by (a) converting member vectors to spherical coordinates, (b) taking the per-coordinate `mean_angle` (the von-Mises-mean-direction approach: `atan2(mean(sin θ), mean(cos θ))`), (c) converting back to cartesian on the unit hypersphere. Distance to centroid is the angular distance `arccos(x · μ)` on the unit hypersphere (equivalently `1 - cosine_similarity` rescaled).

**Rationale**: The NeuroScape Stage-2 model outputs 64-dim vectors that are conceptually directional (the model produces a constant-norm embedding). Euclidean-mean centroids on directional data underestimate the true center (Steinhaus's "longitude problem"); the spherical mean is the standard correction.

**Implementation notes**:
- The recipe lives in NeuroScape's `get_centroids` helper (which the one-off `scripts/derive_neuroscape_centroids.py` re-implements / ports).
- On-disk format: `centroids__<table_version>.npy` (shape `(n_clusters, 64)`, float32) + companion `cluster_table.csv` carrying `Cluster ID → Title / Description / Keywords / Focus` (lifted directly from NeuroScape's `neuroscience_clusters_1999-2023.csv`).
- The Stage-2 model bundle records `centroid_table_version`; mismatches raise `CentroidTableVersionMismatch` (subclass of `AnalysisError`).

**Alternatives considered**:
- Euclidean-mean centroid — undercounts the true direction for non-trivial angles; rejected per NeuroScape.
- Medoid (member-vector closest to others) — robust but discontinuous; rejected because it can't reproduce NeuroScape's published cluster centers.

## 3. UMAP fit + out-of-corpus projection — three algorithms

**Decision**: v1 supports three algorithms for `project_into_umap(new_vectors, fitted_umap_bundle, algorithm=…)`:
- `native` — requires the fitted `umap.UMAP` model object to be persisted in the bundle (we pickle it). Calls `model.transform(new_vectors)`.
- `knn_weighted` — model-free fallback. Computes cosine kNN against the bundle's reference matrix and emits `Σ w_i · ref_coords[i]` with `w_i = softmax(-d_i / τ)` over the top-k=15.
- `parametric` — at bundle-build time, fit a small MLP `R^d → R^{2 or 3}` on `(reference_vectors, reference_coords)`; persist the MLP; at project time use it.

The bundle's `metadata.json` records `supported_algorithms = ["native", "knn_weighted", "parametric"]` (or a subset if the bundle was built without one of them); `project_into_umap` raises `UnsupportedProjectionAlgorithm` when asked for a missing one.

**Rationale**:
- `native` is the gold standard but requires `umap-learn` and the persisted model object.
- `knn_weighted` is the model-free fallback that works on any saved (matrix + coords) pair — useful when the operator only stashed reference coordinates (e.g., after re-importing a published UMAP).
- `parametric` makes future zero-shot projection cheap (a single matmul) without depending on the operator's local `umap-learn` version.

**Alternatives considered**:
- Procrustes-aligned re-fit — defers to v2; needs careful handling to keep the alignment stable across multiple project calls.
- Pure `nearestneighbors` snap-to-coord (k=1) — produces visible jaggedness in UMAP plots; rejected.

## 4. Topic modeling — Hybrid spaCy + optional LLM grouping

**Decision**: Two-stage hybrid pipeline (clarification Q7):

1. **Local phrase extraction** — Per cluster, run spaCy (`en_core_web_md` baseline; `scispacy/en_core_sci_lg` opt-in via `--scispacy`) over the cluster's member abstract texts, harvest `doc.noun_chunks` + `doc.ents`, canonicalize (lowercase + lemma + dedupe), then score each candidate via class-based TF-IDF (c-TF-IDF) across the cluster set. Keep the top-N (default 60) phrases.
2. **LLM grouping pass (opt-out)** — For each cluster, send ONLY the candidate-phrase list (NOT raw abstracts) to OpenAI with a strict JSON-schema prompt returning `{Keywords: list[str], Title: str, Description: str, Focus: "themes" | "methodologies"}`. Post-response guard: `Keywords ⊆ candidate_phrases` — the LLM may re-rank and group but cannot invent terms. Cache key: `sha256(model_id || prompt_version || sorted(candidate_phrases))`.

`--skip-llm-topics` produces a fully-local run: emit the top-N c-TF-IDF phrases directly as `Keywords` with empty `Title`/`Description`/`Focus`.

**Rationale**:
- spaCy noun-chunk + NER over scientific text is a well-established phrase-extraction baseline with deterministic output; c-TF-IDF (the BERTopic-style class-based TF-IDF) gives us a discriminative score per cluster without any API call.
- The LLM call grouping a 60-phrase shortlist consumes ~3k tokens vs. the ~30k that a raw-abstract approach would burn per cluster — ~10× cheaper and removes the hallucination surface (LLM cannot invent words because we assert the subset relationship).
- Cost: ~$0.15 for 100 clusters at `gpt-5.4-mini` flex tier (consistent with the project's existing flex tier usage in Stage 2.1).
- Making the LLM stage opt-out matches the user's directive ("topic modeling doesn't necessarily need an openai key") while still letting the canonical UI pipeline have the richer labels.

**Implementation notes**:
- `analyze.topics.extract_candidate_phrases(cluster_texts, *, spacy_model, top_n=60)` returns `list[str]`.
- `analyze.topics.group_phrases_via_llm(candidate_phrases, *, model_id, prompt_version, keyword_out_n=15, cache_dir)` returns the structured dict; reuses `enrich.flex_tier` for retry/fallback.
- Pillow / sentence-transformers etc. are NOT pulled in.

**Alternatives considered**:
- Pure BERTopic — heavy (`hdbscan` + `umap-learn` + `sentence-transformers` again); we already produced embeddings in Stage 3 and have purpose-built clustering in Stage 4. Rejected.
- LLM over raw abstracts — ~10× more tokens, opens hallucination surface; rejected.
- LDA / NMF — historically the default for topic modeling but consistently underperforms phrase-based methods on short scientific text. Rejected.

## 5. Rollup file format — Parquet + SQLite (shape-equivalent)

**Decision**: Emit `data/outputs/analysis/annotations__<state-key>.parquet` AND `annotations__<state-key>.sqlite` (a 1:1 mirror via a single `annotations` table + a joinable `cluster_topics` table). Parquet for analytical consumers (the UI build step's data-prep, ad-hoc notebook work, the poster-layout sequencer); SQLite for indexed lookup by `abstract_id` and for downstream consumers that already use sqlite (`enrich/storage.py`).

**Rationale**:
- Parquet is the natural fit for the per-abstract wide table (one row per abstract; UMAP coords + cluster ids columns are all small numeric/text). pyarrow is already an existing `[parquet]` extra.
- SQLite keeps the lookup surface trivial for the UI's static export — the export step can `SELECT * FROM annotations WHERE abstract_id IN (...)` without spinning up a parquet reader.
- Both writes are atomic (temp → rename) per the project's existing pattern.

**Alternatives considered**:
- Parquet-only — forces every downstream consumer to either link to pyarrow or to load via parquet-to-pandas. UI's existing pattern is sqlite-friendly; we keep both.
- JSON rollup — would be ~50 MB for 3.2k rows × ~30 columns; rejected for size.

## 6. NeuroScape centroid derivation — one-off setup script

**Decision**: `scripts/derive_neuroscape_centroids.py` reads:
- `data/inputs/neuroscape/DomainEmbeddings/*.h5` — Stage-2 projected vectors (multi-shard, ~461k articles × 64 dim).
- `data/inputs/neuroscape/neuroscience_articles_1999-2023.csv` — article id → `Cluster ID`.
- `data/inputs/neuroscape/neuroscience_clusters_1999-2023.csv` — `Cluster ID → Title / Description / Keywords / Focus`.

Groups by `Cluster ID`, applies `get_centroids` (spherical-mean), writes `centroids__<table_version>.npy` (shape `(~2632, 64)`) + `cluster_table.csv` (Cluster ID + label columns). The `<table_version>` is derived from `sha256(grouped-vectors-bytes)[:12]` and recorded inside `cluster_table.csv` for runtime discovery (Principle VII).

**Rationale**: NeuroScape ships these as separate downloads; computing centroids from them once and persisting both the matrix and the lookup table means Stage 4's `neuroscape_clusters` analysis kind can run without h5py or 460k articles in memory.

**Implementation notes**:
- Script only runs when the operator explicitly requests it; the centroid file is checked in to the gitignored `data/inputs/neuroscape/` and re-derived only if NeuroScape ships a new published table.
- The script is venv-scoped (`PYTHONPATH=src .venv/bin/python scripts/derive_neuroscape_centroids.py`).

**Alternatives considered**:
- Hardcoding the centroids — would violate Principle VII (Discover External State). Rejected.
- Computing centroids on every Stage 4 run from H5 shards — wastes ~5 minutes per run for a static input; rejected.

## 7. Module reorganization — `analyze/` package, no compat shim

**Decision**: Delete `src/ohbm2026/analyze.py` in this change. Create `src/ohbm2026/analyze/__init__.py` plus the submodules listed in plan.md. Migrate every importer (`cli.py`, `ui.py`, `poster_layout.py`, `category_evaluation.py`, `embed/neuroscape.py`, scripts: `plot_voyage_stage2_umap_3d.py`, `write_topic_group_report.py`, `run_gmm_overlap_experiment.py`, `plot_poster_layout_floorplan.py`, `cluster_projection_silhouette.py`, tests: `test_neuroscape.py`, `test_neuroscape_derivation.py`) to the new paths in the same commit.

The Stage-2 NeuroScape model code (the training entrypoint, applier, checkpoint loader, bundle helpers) physically moves into `src/ohbm2026/embed/neuroscape.py`. The existing façade is replaced; `embed/neuroscape.py` ships the real implementation.

**Rationale**:
- Stages 1–3 already settled on per-stage packages; a flat 2,800-LOC module is the last remaining outlier.
- A "legacy shim" path would never get cleaned up; the user explicitly directed "no legacy compat" in Q2 of the spec clarifications.
- The reorganization is mechanical and lands in the same PR as Stage 4 logic so import-path rewrites and new files settle together.

**Alternatives considered**:
- Keep flat `analyze.py` — rejected; spec FR-016 mandates the split.
- Backward-compat shim — rejected per clarification Q2.

## 8. Per-bundle directory contract

**Decision**: Each Stage 4 bundle lives at:
```
data/outputs/analysis/<input_key>/<analysis_kind>__<state-key>/
  ids.npy                # row-aligned abstract ids (FR-010)
  payload/...            # analysis-kind-specific (umap_coords_2d.npy, umap_coords_3d.npy, community_ids.npy, neuroscape_cluster_ids.npy, …)
  topics.json            # cluster_id → keywords/title/description/focus (only when the kind is a clustering)
  metadata.json          # kind, model, input_source, algorithm_config, seed, distance/modularity stats, dimension stats
  provenance.json        # corpus_state_key, input_source_assembly_hash, algorithm_config, cache_key, code revision, command, seed
```

Where `<input_key> = <model>_<recipe-or-component>` (e.g., `voyage_abstract`, `voyage_claims`), and `<state-key>` is the 12-char prefix of `sha256(corpus_state_key || input_source_assembly_hash || algorithm_config_canonical_json || seed)`.

**Rationale**: Mirrors Stage 3 (`embed.storage`) directory shape, so existing tooling (Stage 3's `compose_recipe`, the rollup writer) can iterate `data/outputs/analysis/*/` with one glob.

## Open items deferred to Phase 1

None. All clarifications resolved in the spec; Phase 1 designs the on-disk schemas and the CLI flag surface from these decisions.
