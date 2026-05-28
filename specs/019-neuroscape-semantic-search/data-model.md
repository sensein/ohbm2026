# Phase 1 Data Model — NeuroScape Semantic Search

**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Research**: [research.md](research.md) · **Date**: 2026-05-27

This document defines the schemas + invariants for every new piece of
data produced or consumed by this spec. Wire-level parquet schemas are
in [contracts/parquet-schemas.md](contracts/parquet-schemas.md);
this file captures the entities, their relationships, and the cross-
file consistency rules the builder + the browser ranker MUST honour.

---

## Entities

### 1. `cluster_centroids` table (inside `neuroscape.parquet`)

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `cluster_id` | INT16 | NOT NULL · PRIMARY KEY · matches every `articles.cluster_id` value at least once | Same dtype as `articles.cluster_id` (`parquet_writer.py:101`) |
| `centroid_vector` | LIST<FLOAT32, 384> | NOT NULL · length == 384 | FP32, not INT8 — only ~50 rows; precision matters at routing argmax |
| `member_count` | INT32 | NOT NULL · > 0 · sum(member_count) == n_articles | Forensic — lets the browser sanity-check distribution without re-joining articles |

**Rows**: one per distinct `cluster_id` in the NeuroScape v1.0.1 release.
~50 today.

**Total bytes**: ~50 × (2 + 1536 + 4) ≈ 78 KB. Eagerly loaded with
`neuroscape.parquet` on every page navigation to `/neuroscape/` and
atlas-root.

**Build-side invariants**:
- The centroid value MUST be the L2-renormalised mean of the
  per-cluster member vectors at INT8 quantisation time (NOT the
  un-quantised float32 mean — dequantisation-then-mean must round-trip
  the cluster's articles' vectors as they appear in
  `neuroscape_vectors.parquet`).
- The `cluster_id` set MUST equal the cluster_id set in the existing
  `clusters` table (cross-table consistency invariant).

---

### 2. `neuroscape_vectors.parquet` (NEW sibling file)

Co-located with `neuroscape.parquet` on the deploy host; same state
key suffix in the build provenance.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `cluster_id` | INT16 | NOT NULL · sort key | First column so row-group min/max stats are tightest |
| `pubmed_id` | INT64 | NOT NULL · UNIQUE · bijection with `articles.pubmed_id` | Order within a cluster is `articles.pubmed_id` ASC |
| `minilm_vector` | FIXED_LEN_BYTE_ARRAY(384) | NOT NULL · INT8 little-endian | Single global scale; dequantise via the manifest's `scale` field |

**Sort order**: rows sorted by (`cluster_id` ASC, `pubmed_id` ASC).
This is what makes the per-cluster predicate pushdown work — row
groups have non-overlapping `cluster_id` ranges, so hyparquet
short-circuits to only the matching row groups.

**Row groups**: target 8192 rows per row group (parquet binary-column
default), giving ~3 MB per row group at 384 bytes/row. A typical
9-11k-article cluster fits in ~1-2 row groups.

**Total bytes**: ~461 000 × ~386 B ≈ 178 MB raw; ~50 MB post-parquet-
compression with the FIXED_LEN_BYTE_ARRAY page encoding. Lazy-loaded
only on first semantic query.

**Build-side invariants**:
- Every `pubmed_id` in `articles` MUST appear exactly once in this
  file. Missing or duplicate rows MUST raise
  `VectorsParquetWriteError` at build time.
- The single global `scale` recorded in the manifest MUST equal
  `127.0 / max_abs_original` where `max_abs_original` is the maximum
  absolute value across the un-quantised FP32 vectors — same rule as
  `src/ohbm2026/ui_data/vectors.py:107-110`.
- The MiniLM model file sha256 used by the corpus encoder MUST match
  the value recorded in the manifest (cross-checked at browser worker
  init — R-010).

---

### 3. `ohbm_vectors` table (inside `atlas.parquet`)

Lives alongside the existing `ohbm_overlay`, `cross_pointers`, etc.
tables in `atlas.parquet`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `poster_id` | INT16 | NOT NULL · UNIQUE · matches every row in `ohbm_overlay.poster_id` | Same dtype as the existing overlay |
| `minilm_vector` | FIXED_LEN_BYTE_ARRAY(384) | NOT NULL · INT8 little-endian | Same scale + model as NeuroScape (matched-pair invariant) |

**Rows**: one per OHBM 2026 accepted abstract (~3 240).

**Total bytes**: ~3 240 × 386 B ≈ 1.25 MB. Eager-loaded with
`atlas.parquet`.

**Build-side invariants**:
- The `scale` value in the manifest MUST be the SAME `scale` used by
  the NeuroScape vectors parquet — same model, same quantisation
  contract, single global scale across BOTH corpora so cross-conference
  cosine merging (R-008 / FR-023) is meaningful.

---

### 4. Vectors-build manifest (inside the parquet that carries the vectors)

For `neuroscape_vectors.parquet`, the manifest is embedded as a JSON
blob in the parquet's `manifest_json` table (mirroring the
single-file-parquet manifest convention from
`src/ohbm2026/ui_data/formats/parquet_single.py`).

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | string | ✓ | `"semantic_vectors.v1"` |
| `corpus` | enum | ✓ | `"neuroscape"` or `"ohbm2026"` |
| `state_key` | string (12 hex) | ✓ | sha256-prefix of inputs (per R-009) |
| `code_revision` | string | ✓ | git sha at build |
| `command_line` | string | ✓ | for audit |
| `seed` | int | ✓ | reserved for future variants; 0 today |
| `model_id` | string | ✓ | `"Xenova/all-MiniLM-L6-v2"` (R-001) |
| `model_sha256` | string (64 hex) | ✓ | matched-pair invariant (R-010) |
| `vector_dim` | int | ✓ | 384 |
| `quantization` | string | ✓ | `"int8-global-scale"` |
| `scale` | float32 | ✓ | dequantisation multiplier (R-002) |
| `max_abs_original` | float32 | ✓ | forensic — original FP32 max-abs that produced `scale` |
| `n_vectors` | int | ✓ | row count |
| `cluster_count` | int | ✓ for `neuroscape`; absent for `ohbm2026` | mirrors the centroid table row count |
| `row_group_size` | int | ✓ | so the browser can sanity-check predicate-pushdown granularity |
| `build_started_utc` | string (ISO 8601 Z) | ✓ | mirrors existing parquet manifest |
| `build_finished_utc` | string (ISO 8601 Z) | ✓ | mirrors existing parquet manifest |

No absolute or user-home paths anywhere in the manifest (CA-008).

---

### 5. In-memory candidate set (transient, browser-side)

Constructed per query by `site/src/lib/search/neuroscape_ranker.ts`;
never persisted.

| Field | Type | Notes |
|---|---|---|
| `query_vector` | Float32Array(384) | output of the worker's query encode |
| `routing_cluster_id` | int16 | argmax over `cluster_centroids.centroid_vector · query_vector` |
| `top3_seeds` | `Array<{pubmed_id: bigint; cosine: number}>` (length 3) | brute-force top-3 within `routing_cluster_id` |
| `candidate_pmids` | `Set<bigint>` | top3_seeds ∪ KNN-expand(top3, k=20) |
| `ranked` | `Array<{pubmed_id, cosine, cluster_id, source: 'cosine' \| 'knn-distance'}>` | sorted by cosine if vectors loaded, else by precomputed KNN distance to seed |

**LRU**: parallel `Map<int16, Int8Array>` of cluster_id → INT8 cluster
vectors, capped per FR-024 at 4 distinct clusters per session.
Eviction: least-recently-used cluster array dropped first; never
evicts the routing cluster of the active query.

---

### 6. Search-query state machine (browser-side, per surface)

States: `idle` → `embedding` → `routing` → `range-fetching` →
`brute-force` → `knn-expand` → `re-rank` → `ready` (loops back to
`idle` on next keystroke).

Side-states (orthogonal):
- `model-loading` (one-shot, on first toggle activation in a session)
- `model-error` (terminal until user retries; surfaces FR-006 message)
- `vectors-cap-exceeded` (set when FR-024 cap is reached; one-shot
  banner; user opt-in to release the cap for this query)

Cancellation: any new keystroke aborts an in-flight transition; the
worker MUST drop pending range-fetch promises (via AbortController on
the underlying fetch) so a fast typist doesn't pile up worker work.

---

## Cross-file consistency invariants

These are the rules the builder + the browser drift-checker enforce.
Mirrors the existing Stage-15 cross-parquet drift detector in
`site/src/lib/data_package/loader.ts:683-719`.

**INV-001**: `cluster_centroids.cluster_id` set ==
`clusters.cluster_id` set (inside `neuroscape.parquet`). Build raises
`AssertionError` on mismatch.

**INV-002**: `cluster_centroids.member_count.sum()` ==
`articles.rowcount`. Build raises `AssertionError` on mismatch.

**INV-003**: `neuroscape_vectors.parquet`'s set of `pubmed_id` ==
`articles.pubmed_id` set (in the same `neuroscape.parquet`). Build
raises `VectorsParquetWriteError` on mismatch.

**INV-004**: `neuroscape_vectors.parquet`'s manifest `state_key`
parent-references `neuroscape.parquet`'s manifest `state_key` (i.e.,
the vectors parquet's state key derives from the articles' state key).
Browser raises `VectorsManifestDriftError` on mismatch.

**INV-005**: `ohbm_vectors.poster_id` set ==
`ohbm_overlay.submission_id_to_poster_id.values()` (same set of
OHBM 2026 abstracts). Build raises `AssertionError` on mismatch.

**INV-006**: `neuroscape_vectors.parquet.manifest.model_sha256` ==
`ohbm_vectors.manifest.model_sha256` AND ==
`atlas.parquet.manifest.expected_model_sha256` AND, at runtime, ==
the sha256 of the model file loaded by the browser worker. Worker
init raises `VectorsManifestDriftError` on mismatch (R-010).

**INV-007**: `neuroscape_vectors.parquet.manifest.scale` ==
`atlas.parquet.ohbm_vectors.manifest.scale`. Cross-corpus cosine
ranking on atlas-root depends on identical quantisation (R-008 /
FR-023). Build raises `AssertionError` on mismatch.
