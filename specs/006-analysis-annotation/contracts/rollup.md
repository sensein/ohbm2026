# Rollup Contract: `data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}`

The canonical UI input. One file per corpus state-key. Parquet and SQLite forms are content-equivalent.

## `annotations` table

One row per abstract present in the corpus. Per-(model, input) columns are emitted only for `(model, input)` pairs that the run produced. Missing values are encoded as nulls (parquet: native; sqlite: `NULL`).

### Column order

```text
abstract_id INT64 NOT NULL PRIMARY KEY

-- For each model M present (e.g., voyage, minilm, openai, pubmedbert, neuroscape):
umap2d_<M>_x FLOAT32,    umap2d_<M>_y FLOAT32
umap3d_<M>_x FLOAT32,    umap3d_<M>_y FLOAT32,    umap3d_<M>_z FLOAT32

-- For each (model M, input I) pair present:
community_<M>_<I> INT32                          -- 0 is largest community
neuroscape_cluster_<M>_<I> INT32                 -- from cluster_table.csv
neuroscape_cluster_distance_<M>_<I> FLOAT32     -- angular distance on hypersphere
topic_cluster_<M>_<I> INT32                      -- topic-model-driven cluster id
```

For the canonical default matrix (5 models × 3 inputs), the column count is:
- 1 id
- 5 models × 5 UMAP-coord columns (`umap2d_x/y` + `umap3d_x/y/z`) = 25 — the rollup carries one canonical UMAP per model (`abstract` input); the per-bundle artifacts retain UMAP coords for the other inputs.
- 5 models × 3 inputs × 2 cluster-id columns (community + topic_cluster) = 30
- 1 model (`neuroscape`) × 3 inputs × 2 columns (neuroscape_cluster_id + neuroscape_cluster_distance) = 6

Total: **62 columns** for the default full run. Sparser runs (e.g., one model) emit a subset; `neuroscape_cluster_*` columns are absent for non-compatible source models because their bundles are auto-skipped.

## `cluster_topics` table

A row per `(clustering_method, model_key, input_source, cluster_id)`. Composite primary key.

```text
clustering_method TEXT NOT NULL        -- "communities" | "neuroscape_clusters" | "topic_clusters"
model_key         TEXT NOT NULL        -- "voyage", "minilm", "openai", "pubmedbert", "neuroscape"
input_source      TEXT NOT NULL        -- "abstract" | "claims" | "methods" | <component>
cluster_id        INT32 NOT NULL
topic_keywords    TEXT                 -- JSON-encoded list[str]; non-empty
topic_title       TEXT                 -- may be "" when --skip-llm-topics
topic_description TEXT                 -- may be ""
topic_focus       TEXT                 -- "themes" | "methodologies" | ""
```

### `neuroscape_clusters` rows

Sourced from `cluster_table.csv` — the centroid sidecar — joined into this table verbatim. Title/Description/Keywords/Focus come from NeuroScape's published cluster vocabulary and don't pass through the spaCy/LLM pipeline.

### `communities` and `topic_clusters` rows

Sourced from each bundle's `topics.json` (FR-009 hybrid pipeline output).

## Atomicity

Both writes (parquet and sqlite) are atomic via temp-file + rename. If the run produces an empty `annotations` table (zero abstracts after filtering), the writer emits the empty tables anyway and records the row count in the matrix-complete summary; no implicit fallback.

## Determinism

Column order is canonical (sorted by `(kind, model, input)`); row order is `abstract_id ASC`. Re-running with identical inputs produces a byte-identical parquet file (modulo the file's embedded timestamp).
