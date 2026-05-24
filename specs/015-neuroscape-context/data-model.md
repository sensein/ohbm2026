# Phase 1 Data Model — Stage 15 NeuroScape Context

This document captures the logical entities and the per-parquet table
layouts for the three publishable artefacts of Stage 15. Field-level
contracts (column types, nullability, primary keys) are in
`contracts/parquet-schemas.md`; this file is the higher-level entity
inventory plus the cross-parquet invariants.

## Entities

### NeuroScapeArticle

A PubMed abstract from the 1999–2023 NeuroScape release. One row per
article in `neuroscape.parquet`'s `articles` inner table; one
*pointer* row per article that is visible in the landing-page scatter
in `atlas.parquet`'s `neuroscape_backdrop` inner table.

**Stage 15 stores only the fields the local UI needs.** Authors,
journal, full abstract text, and DOI are fetched at view time from
NCBI E-utilities (FR-019a) — they are NOT persisted in any parquet.

| Attribute            | Type          | Storage   | Source                                   |
|----------------------|---------------|-----------|------------------------------------------|
| `pubmed_id`          | int64 (PK)    | local     | NeuroScape articles CSV                  |
| `title`              | string        | local     | NeuroScape articles CSV (drives hover + lexical search) |
| `year`               | int16         | local     | NeuroScape articles CSV (facet filter)   |
| `cluster_id`         | int16 (FK→ NeuroScapeCluster.cluster_id) | local | NeuroScape articles CSV |
| `umap_2d`            | list<float32, fixed=2> | local | UMAP fit (R-001)                |
| `umap_3d`            | list<float32, fixed=3> | local | UMAP fit (R-001)                |
| `nearest_pubmed_ids` | list<int64, fixed=20>  | local | k-NN compute (R-008)            |
| `nearest_distances`  | list<float32, fixed=20> | local | k-NN compute (R-008)          |
| `authors`            | list<string>  | runtime   | NCBI EFetch at view time                 |
| `journal`            | string        | runtime   | NCBI EFetch at view time                 |
| `abstract_text`      | string        | runtime   | NCBI EFetch at view time                 |
| `doi`                | string        | runtime   | NCBI EFetch at view time (nullable)      |

**Validation rules**:
- `cluster_id` MUST reference a row in `clusters`; orphans are dropped
  with a counted, named omission in provenance (Edge Cases).
- `year` MUST be in [1999, 2023]; out-of-range rows are dropped.
- `umap_2d` and `umap_3d` MUST contain finite floats; NaN rows are
  rejected (UmapFitError per R-009).
- The runtime-fetched fields are not subject to build-time validation;
  the SvelteKit detail page handles missing/error responses via the
  body offline state (Edge Cases).

### NeuroScapeCluster

One of 175 upstream clusters. One row per cluster in
`neuroscape.parquet`'s `clusters` table and in `atlas.parquet`'s
`clusters` table; the two tables MUST agree row-for-row (asserted at
build time by `parquet_writer.py`).

| Attribute        | Type         | Source                          |
|------------------|--------------|---------------------------------|
| `cluster_id`     | int16 (PK)   | NeuroScape clusters CSV         |
| `title`          | string       | NeuroScape clusters CSV         |
| `description`    | string       | NeuroScape clusters CSV         |
| `keywords`       | list<string> | NeuroScape clusters CSV (JSON-decoded) |
| `focus`          | string       | NeuroScape clusters CSV         |
| `point_count`    | int32        | derived from `articles`         |
| `colour_hex`     | string       | `cluster_palette.py` (R-003)    |
| `palette_tier`   | enum {primary, secondary} | `cluster_palette.py` |

**Validation rules**:
- Cluster count is read from the discovered CSV — not hardcoded. If
  the count changes, the orchestrator surfaces a precise
  `NeuroScapeInputError` (R-009, CA-007).

### OhbmOverlayPoint

One row per OHBM 2026 abstract that has a valid
`voyage_stage2_published` recipe vector. Stored only in
`atlas.parquet`'s `ohbm_overlay` inner table; the full OHBM 2026
record stays in `ohbm2026.parquet`.

| Attribute            | Type        | Source                          |
|----------------------|-------------|---------------------------------|
| `submission_id`      | int64 (PK)  | OHBM 2026 corpus                |
| `poster_id`          | int16       | OHBM 2026 corpus (stable id)    |
| `umap_2d`            | list<float32, fixed=2> | umap.transform (R-002) |
| `umap_3d`            | list<float32, fixed=3> | umap.transform (R-002) |
| `nearest_cluster_id` | int16 (FK→ NeuroScapeCluster.cluster_id) | derived in UMAP space |
| `title`              | string      | OHBM 2026 corpus (tooltip)      |

**Validation rules**:
- Abstracts without a valid Stage-2 vector are omitted with their
  submission_id recorded in provenance (FR-003).
- `nearest_cluster_id` is computed in UMAP space via
  `sklearn.neighbors.KNeighborsClassifier` (k=5 majority) over the
  NeuroScape backdrop — NOT in Stage-2 space, so the visible "near"
  matches what the visitor actually sees in the scatter.

### AtlasUmapModel

The fitted UMAP solution (one 2D + one 3D). Not a Parquet row; instead
its parameters are serialised into `build_info` in `atlas.parquet`'s
manifest table and into the provenance JSON. The fitted UMAP Python
object lives only at build time (used by `umap_projector.py`); it is
not persisted into the publishable parquet because (a) loading
`umap-learn`'s pickled model in a browser is not feasible, and (b)
OHBM 2026 projections are precomputed (R-002).

| Attribute             | Type         | Notes                                |
|-----------------------|--------------|--------------------------------------|
| `seed`                | int          | constant 0 (R-001)                   |
| `n_neighbors`         | int          | 30 (R-001)                           |
| `min_dist`            | float        | 0.10 (R-001)                         |
| `metric`              | string       | "cosine" (R-001)                     |
| `init`                | string       | "spectral" (R-001)                   |
| `n_components`        | int          | one row per fit (2 and 3)            |
| `centroid_table_version` | string    | from NeuroScape source (R-001)       |
| `umap_state_key`      | string       | `sha256(stage2_vectors || params)[:12]` |

### AtlasDataPackage

Logical entity describing the published artefact set. Persisted as
the staging directory `data/outputs/parquets/<state-key>/` containing
three files plus the single provenance JSON.

| Attribute                          | Type   | Notes                              |
|------------------------------------|--------|------------------------------------|
| `state_key`                        | string | `sha256(ohbm_state_key || neuroscape_state_key || umap_state_key)[:12]` |
| `ohbm2026_parquet_state_key`       | string | from `ohbmcli build-ui-data` provenance |
| `neuroscape_parquet_state_key`     | string | from R-001 + the article/cluster CSV SHAs |
| `atlas_parquet_state_key`          | string | derived from the previous two + UMAP state key |
| `code_revision`                    | string | `git rev-parse HEAD`               |
| `seed`                             | int    | 0                                  |
| `command_line`                     | string | the exact argv used                |
| `voyage_bundle_id`                 | string | which voyage bundle the OHBM 2026 stage-2 vectors come from |

## Per-parquet inner table inventory

### `ohbm2026.parquet`

Unchanged from Stage 10 / 11.1 / 13 except for the **filename rename**
(`data.parquet → ohbm2026.parquet`). Inner tables:

- `manifest` (1 row, JSON-blob column)
- `abstracts`, `authors`, `cells:<key>`, `topics:<key>_<kind>`,
  `neighbors:<key>`, `standby_slots`, `enrichment_claims`,
  `enrichment_figures`, `search:minilm_vectors`,
  `search:minilm_vectors_meta`.

Schema version: unchanged (`abstracts.v2`, `standby_slots.v1`, etc.).

### `neuroscape.parquet`

Inner tables:

- `manifest` (1 row, JSON-blob column; carries `build_info`,
  `schema_version='neuroscape.v1'`, `centroid_table_version`,
  `umap_state_key`).
- `articles` (~600K rows, NeuroScapeArticle entity — local fields
  only).
- `clusters` (175 rows, NeuroScapeCluster entity).
- `neighbors_neuroscape` (~600K rows, parallel arrays;
  `pubmed_id, nearest_pubmed_ids, nearest_distances`). Mirrors Stage 6's
  `neighbors:<key>` layout.
- `search:neuroscape_titles` (sidecar BLOB carrying a typo-tolerant
  lexical index over **titles only**, per FR-018 narrowing). Format:
  same `bin + .build_info.json` envelope as Stage 6's
  `minilm_vectors`. Implementation reuses the Stage 6 typo-tolerant
  lexical search index already used by `/ohbm2026/`. Abstract-text
  / full-body index is **out of scope** for Stage 15 (deferred with
  the semantic-search phase per spec Assumptions).

### `atlas.parquet`

Inner tables (all small — bodies are NOT here):

- `manifest` (1 row, JSON-blob column; carries `build_info` including
  `sibling_state_keys: {ohbm2026, neuroscape}` per R-012 +
  `umap_state_key`).
- `clusters` (175 rows, NeuroScapeCluster — same content as
  `neuroscape.parquet/clusters`, asserted equal at build time).
- `neuroscape_backdrop_full` (~600K rows, `pubmed_id, cluster_id,
  umap_2d, umap_3d, title`). Title included for hover tooltips so the
  landing page never needs to fetch `neuroscape.parquet` for hover.
- `neuroscape_backdrop_decimated` (≤50K rows, same shape; per R-011).
- `ohbm_overlay` (~3K rows, OhbmOverlayPoint entity).
- `cross_pointers` (per FR-006): a row group recording the
  source-id ↔ deep-link mapping for the slide-in detail panel:
  `point_kind: enum {ohbm2026, neuroscape}`, `id: int64`,
  `permalink: string`. Permalink is the absolute path under the
  appropriate sibling subsite (e.g. `/ohbm2026/abstract/345/`).

## Cross-parquet invariants

| Invariant | Where enforced | Failure mode |
|-----------|---------------|--------------|
| `neuroscape.parquet/clusters` is row-for-row equal to `atlas.parquet/clusters` | `parquet_writer.py` at build time | `CrossParquetDriftError` |
| `atlas.parquet/neuroscape_backdrop_full.pubmed_id` ⊆ `neuroscape.parquet/articles.pubmed_id` | `parquet_writer.py` | `CrossParquetDriftError` |
| `atlas.parquet/ohbm_overlay.poster_id` ⊆ `ohbm2026.parquet/abstracts.poster_id` | `parquet_writer.py` | `CrossParquetDriftError` |
| `atlas.parquet/manifest.sibling_state_keys.ohbm2026` == loaded `ohbm2026.parquet/manifest.build_info.state_key` | browser-side `loader.ts` on landing page load | visible UI error component |
| `atlas.parquet/manifest.sibling_state_keys.neuroscape` == loaded `neuroscape.parquet/manifest.build_info.state_key` | browser-side `loader.ts` (only if NeuroScape detail is fetched) | visible UI error component |

## State machine — orchestrator run

```text
[start] → discover_inputs → validate_input_shas → load_ohbm2026_parquet_state_key
   → fit_umap_3d → fit_umap_2d                                  (cached on stage2_vectors||params)
   → project_ohbm_to_umap                                       (cached per abstract)
   → assign_cluster_colours                                     (deterministic)
   → compute_neuroscape_neighbours                              (cached on stage2_vectors)
   → decimate_neuroscape_backdrop                               (deterministic seed)
   → write_neuroscape_parquet                                   (atomic temp→rename)
   → write_atlas_parquet                                        (atomic temp→rename)
   → write_provenance                                           (after both parquets exist)
   → link_check                                                 (concurrent, rate-limited)
   → DONE
```

Resumability: each labelled step writes a sentinel file in
`data/cache/atlas-runs/<state-key>/<step>.done` on completion. A
second invocation skips steps whose sentinel exists; deletion of a
sentinel forces re-execution of that step and every downstream step
(downstream invalidation via topological order).

## Sample size estimates

| Artefact                              | Approx bytes (zstd-compressed) |
|---------------------------------------|-------------------------------|
| `ohbm2026.parquet`                    | ~25 MB (unchanged from today) |
| `neuroscape.parquet/articles`         | ~23 MB (461K rows × titles dominate; bodies fetched at runtime) |
| `neuroscape.parquet/neighbors`        | ~19 MB (k=20, 4-byte ids+dists, 461K rows) |
| `neuroscape.parquet/search index`     | ~12 MB (lexical typo-tolerant, titles only) |
| `neuroscape.parquet/clusters`         | ~30 KB |
| `neuroscape.parquet` total            | ~54 MB |
| `atlas.parquet/backdrop_full`         | ~25 MB (point bodies only) |
| `atlas.parquet/backdrop_decimated`    | ~2 MB |
| `atlas.parquet/ohbm_overlay`          | ~0.5 MB |
| `atlas.parquet/clusters`              | ~30 KB |
| `atlas.parquet/cross_pointers`        | ~10 MB |
| `atlas.parquet` total                 | ~40 MB |

These are pre-bench order-of-magnitude estimates; final figures
land in the run's provenance file.
