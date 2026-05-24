# Contract — Parquet Schemas (Stage 15)

This contract pins the column types, nullability, and primary keys of
the three publishable parquets. Browser-side decoder behaviour
(`loader.ts`) and Python build behaviour (`parquet_writer.py`) MUST
match what is in this file. Changes here are breaking changes; bump
the relevant inner-table `schema_version` string + add a fallback in
`loader.ts` for one deploy cycle.

## File layout convention (inherited from Stage 10)

Each parquet is a "single-file outer parquet" — one outer row per
inner table, with `(table_name: STRING, table_bytes: LARGE_BINARY)`.
`row_group_size=1` on the outer write so each inner table sits in its
own row group and the browser-side decoder can range-fetch a single
table if needed. Inner tables are themselves Parquet (zstd level 3,
dictionary on strings).

This is the same shape Stage 10 already uses for `data.parquet`. The
new parquets reuse `parquet_single.write()` with new table names.

## `ohbm2026.parquet`

Identical to today's `data.parquet`. Outer rows / inner tables /
schema versions / row counts MUST be byte-identical to the pre-rename
build for the same OHBM 2026 corpus state-key. See spec FR-022 +
SC-008 + R-010.

The **only** observable change is the file *name* — content (SHA-256)
unchanged. The byte-identity property is asserted by
`tests/test_ohbm2026_parquet_rename.py`.

## `neuroscape.parquet`

Outer table = `(table_name: STRING, table_bytes: LARGE_BINARY)`, one
row per inner table. Inner tables:

### `manifest` (1 row)

```text
manifest_json: STRING (UTF-8 JSON)
```

Decoded JSON shape:

```json
{
  "schema_version": "neuroscape.v1",
  "build_info": {
    "state_key": "<12-hex>",
    "code_revision": "<git sha>",
    "command_line": "<argv joined>",
    "seed": 0,
    "umap_state_key": "<12-hex>",
    "centroid_table_version": "<12-hex>",
    "voyage_bundle_id": null,
    "build_started_utc": "<ISO8601>",
    "build_finished_utc": "<ISO8601>"
  },
  "n_articles": <int>,
  "n_clusters": <int>,
  "k_neighbors": 20
}
```

`voyage_bundle_id` is `null` in `neuroscape.parquet` (it doesn't read
voyage embeddings; only `atlas.parquet`'s manifest carries it). The
field is present for shape-consistency across all three parquets.

### `articles` (~600K rows)

Stage 15 stores **only the fields the local UI renders**. Authors,
journal, full abstract text, and DOI are fetched from NCBI E-utilities
at view time (FR-019a) and are NOT columns in this table.

```text
pubmed_id          INT64         NOT NULL  -- primary key
title              STRING        NOT NULL  -- drives hover tooltip + lexical search
year               INT16         NOT NULL  -- in [1999, 2023]; facet filter
cluster_id         INT16         NOT NULL  -- FK → clusters.cluster_id
umap_2d            LIST<FLOAT32> NOT NULL  -- fixed length 2
umap_3d            LIST<FLOAT32> NOT NULL  -- fixed length 3
```

### `clusters` (175 rows; must equal `atlas.parquet/clusters`)

```text
cluster_id    INT16        NOT NULL  -- primary key
title         STRING       NOT NULL
description   STRING       NOT NULL
keywords      LIST<STRING> NOT NULL  -- decoded from upstream JSON-encoded column
focus         STRING       NOT NULL
point_count   INT32        NOT NULL  -- count of articles in this cluster
colour_hex    STRING       NOT NULL  -- "#RRGGBB", deterministic per R-003
palette_tier  STRING       NOT NULL  -- "primary" | "secondary"
```

### `neighbors_neuroscape` (~600K rows)

```text
pubmed_id              INT64                       NOT NULL  -- primary key
nearest_pubmed_ids     LIST<INT64>   fixed=20      NOT NULL
nearest_distances      LIST<FLOAT32> fixed=20      NOT NULL  -- cosine distance
```

### `search:neuroscape_titles` — sidecar binary blob (not a Parquet inner table)

Two outer rows:

```text
search:neuroscape_titles          → bytes (typo-tolerant lexical index binary over TITLES ONLY; format mirrors Stage 6 minilm_vectors)
search:neuroscape_titles_meta     → bytes (UTF-8 JSON sidecar with build_info + index params + n_documents + "field_set": ["title"])
```

Same outer-row pattern as `search:minilm_vectors` /
`search:minilm_vectors_meta` in `ohbm2026.parquet`. Stage 15 ships
title-only search per FR-018; the `field_set` discriminator allows the
deferred semantic-search phase to add a parallel sidecar
(`search:neuroscape_titles_abstracts`) without breaking the
loader's table-name dispatch.

## `atlas.parquet`

Outer table = `(table_name: STRING, table_bytes: LARGE_BINARY)`, one
row per inner table. Inner tables:

### `manifest` (1 row)

```text
manifest_json: STRING (UTF-8 JSON)
```

Decoded JSON shape:

```json
{
  "schema_version": "atlas.v1",
  "build_info": {
    "state_key": "<12-hex>",
    "code_revision": "<git sha>",
    "command_line": "<argv joined>",
    "seed": 0,
    "umap_state_key": "<12-hex>",
    "centroid_table_version": "<12-hex>",
    "voyage_bundle_id": "<bundle-id>",
    "sibling_state_keys": {
      "ohbm2026":   "<12-hex>",
      "neuroscape": "<12-hex>"
    },
    "build_started_utc": "<ISO8601>",
    "build_finished_utc": "<ISO8601>"
  },
  "n_overlay_points":            <int>,
  "n_backdrop_full":             <int>,
  "n_backdrop_decimated":        <int>,
  "n_clusters":                  <int>,
  "ohbm_omitted_submission_ids": [<int>, ...]
}
```

### `clusters` (175 rows)

Schema identical to `neuroscape.parquet/clusters`. Content asserted
row-for-row equal at build time (`parquet_writer.py`); a mismatch
raises `CrossParquetDriftError`.

### `neuroscape_backdrop_full` (~600K rows)

```text
pubmed_id   INT64                       NOT NULL  -- FK → neuroscape.parquet/articles.pubmed_id
cluster_id  INT16                       NOT NULL  -- FK → clusters.cluster_id
umap_2d     LIST<FLOAT32> fixed=2       NOT NULL
umap_3d     LIST<FLOAT32> fixed=3       NOT NULL
title       STRING                      NOT NULL  -- for hover tooltip
year        INT16                       NOT NULL  -- for hover tooltip
```

### `neuroscape_backdrop_decimated` (≤50K rows)

Same schema as `neuroscape_backdrop_full`. Per R-011: per-cluster
stratified random sample with deterministic seed=0, preserving
cluster proportions.

### `ohbm_overlay` (~3K rows)

```text
submission_id        INT64                    NOT NULL  -- primary key
poster_id            INT16                    NOT NULL  -- FK → ohbm2026.parquet/abstracts.poster_id
umap_2d              LIST<FLOAT32> fixed=2    NOT NULL
umap_3d              LIST<FLOAT32> fixed=3    NOT NULL
nearest_cluster_id   INT16                    NOT NULL  -- FK → clusters.cluster_id
title                STRING                   NOT NULL  -- for hover tooltip
```

### `cross_pointers` (~603K rows = backdrop + overlay)

```text
point_kind   STRING    NOT NULL  -- "ohbm2026" | "neuroscape"
id           INT64     NOT NULL  -- poster_id for "ohbm2026", pubmed_id for "neuroscape"
permalink    STRING    NOT NULL  -- "/ohbm2026/abstract/345/" or "/neuroscape/abstract/14702342/"
```

The permalink string is exact (including trailing slash). The
SvelteKit landing-page slide-in detail panel uses this column to
build the "Open on `<subsite>` →" CTA href.

## `build_info` envelope shape

Every parquet's `manifest.build_info` carries at minimum:

```text
state_key, code_revision, command_line, seed,
build_started_utc, build_finished_utc
```

`atlas.parquet`'s `build_info` ADDS:

```text
sibling_state_keys: {ohbm2026, neuroscape}
umap_state_key, centroid_table_version, voyage_bundle_id
```

This shape mirrors the Stage 6 build_info contract; the only addition
is the `sibling_state_keys` object specific to the cross-connector
parquet. The browser-side `loader.ts` performs the equality assertion
described in R-012.

## Migration rules

- A new column on an existing inner table is allowed without a
  `schema_version` bump if and only if the column is fully nullable
  AND the existing browser decoder ignores unknown columns. (Today
  the decoder ignores unknown columns when reading via
  `parquetReadObjects`; verified by Stage 10 + Stage 11.1 tests.)
- A type change, a column rename, or a non-null new column is a
  breaking change → bump the inner table's `schema_version` and add a
  fallback branch in `loader.ts` that handles both shapes for at least
  one deploy cycle.
- An outer-row removal is a breaking change → bump
  `manifest.schema_version` and document in the loader's fallback
  block.
