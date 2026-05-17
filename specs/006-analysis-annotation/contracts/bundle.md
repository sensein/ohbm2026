# Per-Bundle Contract: `data/outputs/analysis/<input_key>/<kind>__<state-key>/`

Every Stage 4 bundle conforms to a common envelope (`ids.npy`, `metadata.json`, `provenance.json`) plus per-kind payload files.

## Common envelope

### `ids.npy`
- `np.ndarray`, dtype `int64`, shape `(n,)`.
- Row-aligned with every payload array. The order is the order produced by `embed.compose.compose_recipe` (Stage 3 column ordering, abstract-id-ascending).

### `metadata.json`
Common keys (analysis-kind-specific additions below):
```json
{
  "kind": "projections | communities | neuroscape_clusters | topic_clusters",
  "model_key": "voyage",
  "input_source": "abstract | claims | <component>",
  "n_rows": 3244,
  "vector_dim": 1024,
  "algorithm_config": { /* canonical JSON; subset of CLI flags relevant to this kind */ },
  "seed": 42,
  "supported_algorithms": [...]  // projections kind only
  /* + per-kind stats: distance moments, modularity, n_communities, … */
}
```

### `provenance.json`
```json
{
  "stage": "analysis",
  "kind": "communities",
  "bundle_path": "data/outputs/analysis/voyage_abstract/communities__abc123def456/",
  "corpus_state_key": "f0c51e80dc0e",
  "input_source_assembly_hash": "a1b2c3d4e5f6...",
  "algorithm_config_canonical_json": "{\"...}",
  "cache_key": "sha256:...",
  "code_revision": "<git rev-parse HEAD>",
  "command": "ohbmcli analyze-matrix --models voyage --inputs abstract --kinds communities",
  "seed": 42,
  "started_at": "2026-05-14T15:42:00Z",
  "completed_at": "2026-05-14T15:42:12Z"
}
```

Every path inside `provenance.json` is project-relative (CA-008 + Principle VIII). The provenance writer (`analyze/provenance.py`) calls `_assert_paths_safe` on every emitted path before writing, matching `embed.provenance`.

## Per-kind payload

### projections (UMAP 2D + 3D)
Files:
- `umap2d_coords.npy` — float32, shape `(n, 2)`
- `umap3d_coords.npy` — float32, shape `(n, 3)`
- `reference_matrix.npy` — float32, shape `(n, d)` — copy of the input matrix for `knn_weighted` projection
- `umap2d_model.pickle` (optional) — the fitted `umap.UMAP` for the 2D fit
- `umap3d_model.pickle` (optional) — the fitted `umap.UMAP` for the 3D fit
- `parametric_mlp_2d.pickle` (optional) — small MLP for `parametric` 2D projection
- `parametric_mlp_3d.pickle` (optional) — small MLP for `parametric` 3D projection

`metadata.json` additions:
```json
{
  "umap_n_neighbors": 15,
  "umap_min_dist": 0.1,
  "umap_metric": "cosine",
  "umap_random_state": 42,
  "supported_algorithms": ["native", "knn_weighted", "parametric"]
}
```

### communities (FAISS+Leiden+CPM)
Files:
- `community_ids.npy` — int32, shape `(n,)`; `0` is largest community
- `knn_indices.npy` — int32, shape `(n, k)`
- `knn_distances.npy` — float32, shape `(n, k)`
- `resolution_sweep.json` — `[{"resolution":..., "n_communities":..., "modularity":...}, …]`
- `topics.json` — `{community_id: {Keywords, Title, Description, Focus}}`

`metadata.json` additions:
```json
{
  "knn_k": 30,
  "knn_metric": "ip_normalized",
  "leiden_partition": "CPMVertexPartition",
  "resolution_min": 0.001,
  "resolution_max": 0.1,
  "resolution_points": 20,
  "selected_resolution": 0.025,
  "selected_modularity": 0.612,
  "n_communities": 18,
  "largest_community_share": 0.214
}
```

### neuroscape_clusters (nearest-centroid in published space)
**Model-compat constraint**: this kind is only computed for `model_key == "neuroscape"`. The published NeuroScape centroids live in the domain-embedding space (64-dim), so the runner consumes the Stage 3 `neuroscape` bundle directly. Every other model is auto-skipped at orchestration time; `--strict-matrix` makes the skip a typed error.

Files:
- `neuroscape_cluster_ids.npy` — int32, shape `(n,)`
- `neuroscape_cluster_distances.npy` — float32, shape `(n,)` — angular distance on the unit hypersphere

`metadata.json` additions:
```json
{
  "source_model": "neuroscape",
  "centroid_table_version": "ab12cd34ef56",
  "centroid_table_path": "data/inputs/neuroscape/centroids__ab12cd34ef56.npy",
  "domain_model_checkpoint_sha256": "9f...",
  "n_centroids": 175,
  "distance_mean": 0.31,
  "distance_std": 0.09,
  "distance_percentile_10": 0.18,
  "distance_percentile_90": 0.46
}
```

(`n_centroids` is discovered at runtime from `cluster_table.csv`; the NeuroScape v1.0.1 snapshot publishes 175 flat clusters.)

Note: there is **no** `topics.json` for this bundle — the NeuroScape cluster labels live in `cluster_table.csv` and join into the `cluster_topics` rollup table directly.

### topic_clusters (topic-model-driven clustering)
Files:
- `topic_cluster_ids.npy` — int32, shape `(n,)`
- `topic_cluster_probabilities.npy` — float32, shape `(n, k_topics)`
- `topics.json` — `{topic_cluster_id: {Keywords, Title, Description, Focus}}`

`metadata.json` additions:
```json
{
  "n_topics": 24,
  "topic_selection_rule": "elbow",
  "topic_model_seed": 42
}
```

## Topics artifact shape

`topics.json` contents (clusterings only):

```json
{
  "0": {
    "Keywords": ["resting-state functional connectivity", "default mode network", "fMRI", "graph theory", "..."],
    "Title": "Resting-state functional connectivity",
    "Description": "Studies investigating intrinsic brain networks measured at rest with fMRI and graph-theoretic analyses.",
    "Focus": "themes"
  },
  "1": { ... },
  ...
}
```

When the LLM stage is skipped (`--skip-llm-topics`):
- `Keywords` is the top-N c-TF-IDF phrases (default 15).
- `Title` is the empty string.
- `Description` is the empty string.
- `Focus` is the empty string.

The post-response guard `Keywords ⊆ candidate_phrases` (the spaCy + c-TF-IDF shortlist) MUST hold; violation raises `TopicGroupingHallucination` and the run aborts (FR-009).
