# Phase 1 — Data Model (Stage 4 Analysis & Annotation)

Stage 4 produces two output classes: **per-(model, input_source, analysis_kind) bundles** (the unit of cache-aware regeneration) and a **per-corpus rollup** (the canonical UI input).

## 1. AnalysisRun

The top-level orchestration record. One per `ohbmcli analyze-matrix` invocation.

```python
@dataclass
class AnalysisRun:
    corpus_state_key: str            # 12-char hex; e.g., "f0c51e80dc0e"
    requested_models: list[str]      # ["voyage", "minilm", "openai", "pubmedbert", "neuroscape"]
    requested_inputs: list[str]      # ["abstract", "claims", "methods"] (the canonical defaults)
    requested_kinds: list[str]       # ["projections", "communities", "neuroscape_clusters", "topic_clusters"]
    seed: int                        # default 42; recorded in every bundle's metadata.json
    skip_llm_topics: bool            # default False
    strict_matrix: bool              # default False — when True, dim-incompatible (model, neuroscape_clusters) pairs raise instead of skipping
    run_state_key: str               # 12-char hex from sha256 of the canonical config; identifies this run
    started_at: str                  # ISO 8601 UTC; informational only (not part of cache key)
```

Validation:
- Every `(model, input)` referenced MUST resolve to a valid Stage 3 bundle on disk before any analysis fires.
- `run_state_key` is derived from `(corpus_state_key, requested_models, requested_inputs, requested_kinds, seed, skip_llm_topics, strict_matrix, code_revision)`.
- The orchestrator auto-skips `(model, "neuroscape_clusters")` for `model ∈ {voyage, minilm, openai, pubmedbert}` because the published NeuroScape centroids live in the domain-embedding space and the runner consumes the Stage 3 `neuroscape` bundle directly. Set `strict_matrix=True` to convert the auto-skip into a typed `AnalysisError`.
- Default matrix size: **48 bundles** (15 projections + 15 communities + 15 topic_clusters + 3 neuroscape_clusters).

## 2. InputSource

A resolved 2-D embedding matrix for analysis.

```python
@dataclass
class InputSource:
    model_key: str                   # "voyage" | "minilm" | …
    recipe_or_component: str         # "abstract" (composed) | "claims" | "title" | …
    abstract_ids: np.ndarray         # int64, shape (n,)
    vectors: np.ndarray              # float32, shape (n, d)
    assembly_hash: str               # sha256 of sorted(component_state_keys) || recipe_name; truncated to 16 hex
```

Validation:
- For the canonical `abstract` recipe: vectors come from `embed.compose.compose_recipe([title, introduction, methods, results, conclusion], …)`.
- For the canonical `claims` component: vectors are loaded directly from `data/outputs/embeddings/<model>/claims__<state-key>/`.
- For the canonical `methods` component: vectors are loaded directly from `data/outputs/embeddings/<model>/methods__<state-key>/`.
- Rows must align across all components; missing rows in any component → row excluded with the count recorded in `metadata.json` (edge case in spec).

## 3. AnalysisBundle

Common envelope shared by every analysis kind.

```python
@dataclass
class AnalysisBundle:
    bundle_dir: Path                 # data/outputs/analysis/<input_key>/<kind>__<state_key>/
    kind: str                        # "projections" | "communities" | "neuroscape_clusters" | "topic_clusters"
    input_source: InputSource        # the input matrix this bundle was computed against
    ids: np.ndarray                  # row-aligned abstract ids (FR-010)
    payload: dict[str, np.ndarray | dict]  # kind-specific (see subclasses)
    topics: dict[int, dict] | None   # only present for clustering kinds; cluster_id → {Keywords, Title, Description, Focus}
    algorithm_config: dict           # canonical JSON-able config; part of the cache key
    metadata: dict                   # stats: dimension counts, distance distribution moments, modularity, …
    provenance: dict                 # corpus_state_key, input_source_assembly_hash, algorithm_config, cache_key, …
```

### 3a. ProjectionsBundle (kind="projections")

```python
payload = {
    "umap2d_coords": np.ndarray,         # float32, shape (n, 2)
    "umap3d_coords": np.ndarray,         # float32, shape (n, 3)
    "reference_matrix": np.ndarray,      # float32, shape (n, d) — copy of input vectors for knn_weighted
    "umap2d_model_pickle": bytes | None, # the fitted umap.UMAP for `native`; None if not serializable on this host
    "umap3d_model_pickle": bytes | None,
    "parametric_mlp_pickle_2d": bytes | None,  # the small MLP for `parametric`
    "parametric_mlp_pickle_3d": bytes | None,
}
metadata = {
    "supported_algorithms": ["native", "knn_weighted", "parametric"],
    "umap_n_neighbors": int, "umap_min_dist": float, "umap_metric": str,
    "umap_random_state": int,
}
```

Validation:
- If `umap2d_model_pickle` is missing, `supported_algorithms` MUST NOT include `"native"` for the 2D side.
- Hyperparameters live in `metadata` so `project_into_umap` can refuse mismatched callers.

### 3b. CommunitiesBundle (kind="communities")

```python
payload = {
    "community_ids": np.ndarray,         # int32, shape (n,) — ordered by descending size, so largest community is 0
    "knn_indices": np.ndarray,           # int32, shape (n, k)
    "knn_distances": np.ndarray,         # float32, shape (n, k)
    "resolution_sweep": list[dict],      # [{resolution, n_communities, modularity}, …]
    "selected_resolution": float,
    "selected_modularity": float,
}
metadata = {
    "knn_k": int, "knn_metric": "ip_normalized",
    "leiden_partition": "CPMVertexPartition",
    "resolution_min": float, "resolution_max": float, "resolution_points": int,
    "n_communities": int, "largest_community_share": float,
}
topics = {community_id: {Keywords: [...], Title, Description, Focus}}  # per FR-009
```

### 3c. NeuroScapeClustersBundle (kind="neuroscape_clusters")

```python
payload = {
    "neuroscape_cluster_ids": np.ndarray,     # int32, shape (n,) — id from cluster_table.csv
    "neuroscape_cluster_distances": np.ndarray,  # float32, shape (n,) — angular distance on unit hypersphere
}
metadata = {
    "centroid_table_version": str,            # discovered from cluster_table.csv (CA-007)
    "centroid_table_path": str,               # project-relative
    "n_centroids": int,
    "distance_mean": float, "distance_std": float,
    "distance_percentile_10": float, "distance_percentile_90": float,
}
topics = None  # NeuroScape clusters carry their own Title/Description/Keywords/Focus
               # supplied verbatim from cluster_table.csv via the rollup join (FR-018).
               # NeuroScape bundles do NOT ship a topics.json file — the rollup writer
               # joins cluster_table.csv directly when populating cluster_topics rows.
```

Validation:
- The kind is **only** computed for `model_key == "neuroscape"` — the published NeuroScape centroids live in the domain-embedding space, so the runner consumes the Stage 3 `neuroscape` bundle directly. For every other model (`voyage`, `minilm`, `openai`, `pubmedbert`), the orchestrator auto-skips with a structured `skipped` event; `strict_matrix=True` makes it raise `AnalysisError`.
- Centroid bundle metadata MUST carry: `centroid_table_version`, source CSV sha256s (articles + clusters), HDF5 shard manifest hash, discovered `cluster_count`, discovered `cluster_ids` list, and the `domain_model_checkpoint_sha256`. Before assignment, the runner compares the recorded checkpoint SHA against the Stage 3 `neuroscape` bundle's provenance; mismatch raises `CentroidTableVersionMismatch` (CA-007 + edge case 3).

### 3d. TopicClustersBundle (kind="topic_clusters")

```python
payload = {
    "topic_cluster_ids": np.ndarray,          # int32, shape (n,) — topic-model-driven cluster id
    "topic_cluster_probabilities": np.ndarray, # float32, shape (n, k) — soft assignment per topic
}
metadata = {
    "n_topics": int,                          # may be auto-selected via elbow / coherence rule
    "topic_selection_rule": "elbow" | "fixed",
    "topic_model_seed": int,
}
topics = {topic_cluster_id: {Keywords, Title, Description, Focus}}
```

## 4. CentroidTable (NeuroScape sidecar)

```python
@dataclass
class CentroidTable:
    matrix_path: Path                # data/inputs/neuroscape/centroids__<version>.npy
    sidecar_path: Path               # data/inputs/neuroscape/cluster_table.csv
    table_version: str               # 12-char hex from sha256 of the grouped vectors; recorded inside cluster_table.csv
    cluster_ids: np.ndarray          # int32, shape (n_centroids,)
    centroids: np.ndarray            # float32, shape (n_centroids, 64) — unit-norm spherical means
    labels: dict[int, dict]          # cluster_id → {Title, Description, Keywords, Focus}
```

Validation:
- `centroids` rows MUST be unit-norm (`||v|| - 1 < 1e-5`).
- Mismatch between `table_version` recorded in the sidecar and the value referenced by Stage 2 model bundle raises `CentroidTableVersionMismatch`.

## 5. RollupTable (the per-corpus UI input)

Schema for `data/outputs/analysis/annotations__<state-key>.parquet` and the equivalent SQLite table.

### Main table `annotations`

| Column | Type | Notes |
|---|---|---|
| `abstract_id` | int64 | primary key |
| `umap2d_<model>_x` | float32 | per model present (e.g., `umap2d_voyage_x`) |
| `umap2d_<model>_y` | float32 | per model |
| `umap3d_<model>_x` | float32 | per model |
| `umap3d_<model>_y` | float32 | per model |
| `umap3d_<model>_z` | float32 | per model |
| `community_<model>_<input>` | int32 | per (model, input) — `0` is largest |
| `neuroscape_cluster_<model>_<input>` | int32 | per (model, input) |
| `neuroscape_cluster_distance_<model>_<input>` | float32 | per (model, input) |
| `topic_cluster_<model>_<input>` | int32 | per (model, input) |

A row exists for every abstract present in the corpus; missing analyses for an abstract are `null`.

### Join table `cluster_topics`

| Column | Type | Notes |
|---|---|---|
| `clustering_method` | str | `"communities"` \| `"neuroscape_clusters"` \| `"topic_clusters"` |
| `model_key` | str | |
| `input_source` | str | `"abstract"` \| `"claims"` \| `"methods"` |
| `cluster_id` | int32 | |
| `topic_keywords` | str | JSON-encoded list[str] |
| `topic_title` | str | |
| `topic_description` | str | |
| `topic_focus` | str | `"themes"` \| `"methodologies"` \| `""` (when LLM stage skipped) |

Primary key: `(clustering_method, model_key, input_source, cluster_id)`.

The parquet and SQLite forms are byte-equivalent in content (column shapes + row counts) so a UI consumer can pick either.

## 6. State transitions

Stage 4 itself has no long-lived state, but each bundle goes through a clear cache lifecycle:

```
MISSING ──(stage.run)──▶ COMPUTED ──(stage.rerun, cache hit)──▶ REUSED
                              │
                              └──(stage.rerun, cache miss / invalidate flag)──▶ COMPUTED (replaces prior bundle path)
```

The `<state-key>` suffix encodes the cache identity, so two runs with different configs land at different paths and never collide on disk (FR-013 + edge case 6).

## 7. Error hierarchy

```python
class AnalysisError(OhbmStageError):
    """Stage 4 root; subclass of the project-wide OhbmStageError defined in ohbm2026.exceptions."""

class InputBundleMissing(AnalysisError): ...        # CA-006 / FR-012
class CentroidTableMissing(AnalysisError): ...      # FR-008 / edge case 3
class CentroidTableVersionMismatch(AnalysisError): ...
class UnsupportedProjectionAlgorithm(AnalysisError): ...  # FR-006 / FR-012
class ProjectionDimensionMismatch(AnalysisError): ... # edge case 2
class TopicGroupingHallucination(AnalysisError): ... # FR-009 guard: Keywords ⊄ candidate_phrases
class CommunityResolutionDegenerate(Warning): ...    # edge case 5: largest community >90%; warning not error
```
