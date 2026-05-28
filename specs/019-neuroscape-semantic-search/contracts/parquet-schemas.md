# Contract: Parquet Schemas (Semantic Search)

**Status**: Phase 1 contract for spec 019 · **Date**: 2026-05-27

Wire-level schemas the build step writes and the browser loader reads.
Cross-table invariants live in [../data-model.md §Cross-file
consistency invariants](../data-model.md#cross-file-consistency-invariants).

---

## 1. `cluster_centroids` (table inside `neuroscape.parquet`)

```text
table_name = "cluster_centroids"

schema:
  cluster_id        INT16            NOT NULL  (primary key)
  centroid_vector   LIST<FLOAT32, 384> NOT NULL
  member_count      INT32            NOT NULL

row_count:          ~50 (one per distinct cluster_id on articles)
sort_order:         cluster_id ASC
row_group_size:     default (one row group fits all rows)
compression:        snappy (matches existing parquet_writer.py default)
```

Outer-row entry inside `neuroscape.parquet`: emitted by
`src/ohbm2026/atlas_package/parquet_writer.py::write_neuroscape_parquet`
in the same loop that already writes `clusters`, `articles`, etc.

---

## 2. `neuroscape_vectors.parquet` (NEW sibling file)

Path on disk: `<output_root>/neuroscape_vectors.parquet`. Co-located
with `neuroscape.parquet` so the existing co-versioning conventions
apply (same `<state-key>`-suffixed directory).

```text
parquet metadata:
  key_value_metadata:
    "manifest_json" -> <JSON serialisation of the manifest entity
                       described in data-model.md §4>

schema:
  cluster_id        INT16                          NOT NULL
  pubmed_id         INT64                          NOT NULL
  minilm_vector     FIXED_LEN_BYTE_ARRAY(length=384) NOT NULL

row_count:          ~461 000 (one per article in neuroscape.parquet)
sort_order:         (cluster_id ASC, pubmed_id ASC)
row_group_size:     8192 rows  (~3 MB per row group at 384 bytes/row)
compression:        SNAPPY (default); the FIXED_LEN_BYTE_ARRAY column
                    uses parquet's per-row binary encoding — the INT8
                    bytes are already maximally dense
```

**Row-group statistics MUST be populated** for `cluster_id` (min, max)
and `pubmed_id` (min, max). Hyparquet uses the `cluster_id`
min/max to drive the per-cluster predicate pushdown that bounds the
HTTP range fetch.

---

## 3. `ohbm_vectors` (table inside `atlas.parquet`)

```text
table_name = "ohbm_vectors"

schema:
  poster_id         INT16                          NOT NULL
  minilm_vector     FIXED_LEN_BYTE_ARRAY(length=384) NOT NULL

row_count:          ~3 240 (one per OHBM 2026 accepted abstract)
sort_order:         poster_id ASC
row_group_size:     default (the whole table fits in 1-2 row groups)
compression:        snappy
```

The manifest fields for `ohbm_vectors` live in `atlas.parquet`'s
top-level `manifest_json` as a new key `ohbm_vectors_provenance`
(parallel to the existing `ohbm_overlay_provenance` / `cross_pointers_*`
blocks).

---

## 4. Browser-side decode contract

For every binary column emission above, the browser layer MUST:

1. **Decode INT8 vectors** as little-endian; reinterpret the 384 bytes
   as a `Int8Array` of length 384.
2. **Dequantise** by multiplying each `Int8Array` element by the
   manifest's `scale` (= `127.0 / max_abs_original`) to recover a
   FP32 approximation of the original unit-norm vector. Recovery MAE
   < 0.005 expected (verified at build time by `cosine_recovery_mae`).
3. **Cosine score** against the FP32 query vector by inner product
   (dequantisation can be folded into the inner loop with a scalar
   pre-multiply — see existing
   `site/src/lib/workers/semantic.worker.ts:63-74`).
4. **Cross-conference** cosine comparison: both corpora's vectors
   use the SAME `scale` (INV-007). The same `Float32` query vector
   scored against both produces comparable cosine values; no
   per-corpus normalisation needed (R-008 / FR-023).

---

## 5. Build-side enforcement

`src/ohbm2026/atlas_package/semantic_index.py::write_neuroscape_vectors_parquet`:

- Asserts INV-003 (`{pubmed_id from articles}` == `{pubmed_id in
  vectors}`) before writing; raises `VectorsParquetWriteError` on
  mismatch.
- Sorts rows by `(cluster_id, pubmed_id)` before passing to
  `pyarrow.parquet.write_table` so the per-row-group min/max stats
  are tight (each row group's `cluster_id` range is single-valued
  except across the cluster boundary).
- Verifies `row_group_size == 8192` matches the contract.
- Computes `model_sha256` from the local sentence-transformers
  download (NOT a remote re-fetch); records it in the manifest.

`src/ohbm2026/atlas_package/parquet_writer.py` extensions:

- `cluster_centroids` table written inside the same atomic write of
  `neuroscape.parquet` that today writes `articles` / `clusters` /
  etc. — no separate write step.
- `ohbm_vectors` table written inside the same atomic write of
  `atlas.parquet` that today writes `ohbm_overlay` / `cross_pointers`
  / etc.

---

## 6. Drift-detection on the browser side

On every `loadDataPackage` for `/neuroscape/` or atlas-root, the
loader (extending the existing
`site/src/lib/data_package/loader.ts::verifyAtlasSiblingDrift` at
line 683) MUST cross-check:

- `neuroscape.parquet.manifest.state_key` ==
  `neuroscape_vectors.parquet.manifest.parent_state_key` →
  `VectorsManifestDriftError` if not.
- `atlas.parquet.manifest.expected_model_sha256` ==
  `neuroscape_vectors.parquet.manifest.model_sha256` ==
  `atlas.parquet.ohbm_vectors_provenance.model_sha256` →
  `VectorsManifestDriftError` if not.

Both errors surface as the user-visible "semantic search is
unavailable — try refreshing" banner with a refresh button. They
do NOT silently fall back to lexical-only ranking (Constitution VI).
