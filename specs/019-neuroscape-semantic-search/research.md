# Phase 0 Research — NeuroScape Semantic Search

**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Date**: 2026-05-27

This document records the technical decisions the plan rests on and the
alternatives evaluated. Each subsection is a single decision; the final
choice is the one carried into `data-model.md` and `contracts/`.

---

## R-001 Browser query embedder

**Decision**: Reuse the existing OHBM 2026 in-browser semantic worker
unchanged. Model: **`Xenova/all-MiniLM-L6-v2`** loaded by
`@xenova/transformers` from the HuggingFace CDN, executed in a Web Worker.
Dimension 384; INT8 quantisation at the corpus side; the query is
embedded as Float32 and dequantised inline during the cosine-similarity
inner loop. Established in `site/src/lib/workers/semantic.worker.ts:49`
and `src/ohbm2026/ui_data/vectors.py:107-110`.

**Rationale**: The matched-pair invariant (corpus + query embedders MUST
use byte-identical model weights for cosine similarity to mean anything)
is already established in the codebase; any new variant requires a fresh
sweep of OHBM 2026 e2e tests + a new model download URL. Adopting the
same Xenova/MiniLM-L6-v2 weights for NeuroScape costs zero new bytes for
visitors who've already used `/ohbm2026/` semantic search (the model
file is browser-cached).

**Alternatives considered**:
- *BioSentenceTransformers / SciBERT variants*: better in-domain accuracy
  on biomedical titles but require shipping a SECOND model file (~80–
  200 MB) and would diverge OHBM 2026 and NeuroScape semantic spaces.
  Out of scope.
- *Server-side encoding via OpenAI embedding API at query time*: kills
  offline + cache semantics, adds a credentials boundary CA-004 rules
  out, and adds per-query cost.
- *Smaller MiniLM variant (TinyBERT, MiniLM-L3-v2)*: faster encode
  per query but breaks the matched-pair invariant with the existing
  `/ohbm2026/` site.

---

## R-002 Corpus-side embedding compute path

**Decision**: Add a new `src/ohbm2026/atlas_package/vectors_compute.py`
that loads `sentence-transformers/all-MiniLM-L6-v2` via
`sentence-transformers` (already an optional extra in `pyproject.toml`)
— the PyTorch origin of the browser's `Xenova/all-MiniLM-L6-v2` ONNX
export. The Xenova repo ships ONNX-only weights that
`sentence-transformers` cannot load; both share one checkpoint, so the
embedding spaces match. This mirrors the proven `/ohbm2026/` matched
pair (corpus vectors from PyTorch `all-MiniLM-L6-v2` via `embed-matrix`,
in-browser query from the Xenova ONNX export). It runs inference over
the NeuroScape article titles in batches, and emits
INT8-quantised float32 vectors using the **same single-global-scale
scheme** as the OHBM 2026 vectors writer
(`src/ohbm2026/ui_data/vectors.py:107-110` — `scale = 127.0 /
max_abs_original`).

**Rationale**: Mirrors the proven OHBM 2026 quantisation contract,
keeping the browser dequantisation path unchanged. Single global scale
is the cosine-similarity-friendly choice (per-vector scales would
require shipping a scale per row, breaking the FIXED_LEN_BYTE_ARRAY(384)
row format).

**Alternatives considered**:
- *Per-vector scale*: 461k extra float32 values to ship; row format
  becomes (scale + 384 bytes) = 388 bytes/row, ~178 MB total. Marginal
  precision win for our cosine-rank-order use case.
- *Product quantisation (e.g. 8-bit codebook over 96-dim subspaces)*:
  ~14 MB total (4× smaller) but the in-browser dequantisation path
  changes substantially and the existing worker would need a fresh
  implementation. Reserved as an optimisation lever if SC-002 misses
  on a future corpus scale.

---

## R-003 Sibling vectors parquet schema + sort order

**Decision**: `neuroscape_vectors.parquet` carries exactly two columns:
- `pubmed_id INT64`
- `minilm_vector FIXED_LEN_BYTE_ARRAY(length=384)` (INT8 row bytes)

Rows are **sorted by `cluster_id`** (the same `cluster_id` already on
the articles table in `neuroscape.parquet`), with `cluster_id`
**included as a third column** so each row group's min/max statistics
naturally enable predicate pushdown. Row-group size targets 8192 rows
(parquet default for binary columns) — at 384 bytes/row that's ~3 MB
per row group, giving ~4 row groups per typical 9-11k-article cluster.

**Rationale**: `cluster_id` predicate pushdown via row-group stats is
the mechanism that turns "fetch one cluster's vectors" into a bounded
HTTP range request. Hyparquet honours these stats. The 8192-row group
sizing is small enough to fetch granularly but large enough that
per-cluster bytes ship in a handful of contiguous range requests.

**Alternatives considered**:
- *Sort by `pubmed_id`*: simpler for key lookups but defeats the
  per-cluster range-fetch (rows from the same cluster spread across
  the whole file).
- *Row groups of 1024 rows*: more granular but more per-group metadata
  overhead and more individual HTTP range fragments.
- *Vectors inside `neuroscape.parquet` as a new column*: bloats the
  eager-loaded main parquet by ~50 MB (the loader at
  `site/src/lib/data_package/loader.ts:150` fetches it in full); the
  cost would hit every visitor whether or not they enable semantic
  search. Already rejected in spec Clarifications Q3.
- *Per-cluster sidecar files (~50 separate .bin files)*: doesn't use
  parquet predicate pushdown; needs a separate manifest enumerating
  shards; rejected in spec Clarifications Q4.

---

## R-004 Cluster-centroid table location + dtype

**Decision**: Centroid table rides INSIDE `neuroscape.parquet` as a new
table entry `cluster_centroids` (parallel to the existing
`clusters` / `neuroscape_backdrop_*` / `ohbm_overlay` entries) — joining
the existing loop in
`src/ohbm2026/atlas_package/parquet_writer.py:write_neuroscape_parquet`.
Three columns:
- `cluster_id INT16` (matches the existing articles table dtype at
  `parquet_writer.py:101`)
- `centroid_vector LIST<FLOAT32, 384>` (FP32; precision matters at the
  routing step and the table is small)
- `member_count INT32` (forensic; lets the browser sanity-check the
  routing distribution against the articles table without rebuilding
  the cluster→article membership)

~50 × (2 + 1536 + 4) ≈ 78 KB total. Eagerly loaded with the existing
parquet on page navigation.

**Rationale**: The centroids are needed BEFORE any range fetch (Step 2
of the pipeline). Putting them inside the main parquet costs ~80 KB of
the eager load but eliminates one cold-start round-trip + manifest
manifest parse. FP32 (not INT8) for the centroids because there are
only ~50 of them — the size win is ~40 KB and the precision loss at
the routing step (a single argmax over ~50 centroids) is not worth it.

**Alternatives considered**:
- *Centroids in a separate sidecar JSON file*: extra cold-start
  round-trip; precedent points away from this (the existing OHBM 2026
  manifest is JSON inside the parquet, not a separate file).
- *Centroids INT8-quantised*: ~40 KB saving on an 80 KB table; not
  worth the precision loss at the routing argmax.

---

## R-005 OHBM 2026 vectors layout on atlas-root

**Decision**: Add an `ohbm_vectors` table inside `atlas.parquet`
(consistent with the rest of the atlas parquet's already-multi-table
shape). Two columns:
- `poster_id INT16` (matches the atlas overlay's existing dtype)
- `minilm_vector FIXED_LEN_BYTE_ARRAY(length=384)` (INT8 row bytes;
  same quantisation scheme as NeuroScape — Step R-002)

~3 240 rows × 386 B ≈ 1.25 MB. Loaded eagerly with `atlas.parquet`
since atlas-root visitors who use semantic search at all will trigger
the OHBM brute-force lane via FR-022.

**Rationale**: For 3.2k abstracts the brute-force cosine over the
whole table is ~1 ms; cluster routing would add overhead with no
benefit. Eager-loading the 1 MB is acceptable because atlas-root's
existing parquet is already ~few-MB and the search bar is a
first-class feature on this surface (US4).

**Alternatives considered**:
- *Sibling `ohbm_vectors.parquet` (lazy)*: extra round-trip + manifest
  for a 1 MB payload; over-engineered.
- *Per-mode build flag to skip OHBM vectors on atlas-root*: complicates
  the build matrix; the cost is small.

---

## R-006 Browser range-fetch wiring

**Decision**: Extend `site/src/lib/data_package/loader.ts` to add a
new helper `loadClusterVectors(clusterId: number, manifestUrl: string)`
that uses `asyncBufferFromUrl` from hyparquet **with a predicate
pushdown filter on `cluster_id`** to read only the matching row
groups. The function returns `{pubmedIds: BigInt64Array; vectors:
Int8Array}` — same layout shape as the existing
`loadMinilmVectors()` for OHBM 2026 so the worker code can be
parameterised over corpus rather than forked.

The precedent for `asyncBufferFromUrl` already exists in the same
file at line 687 (the sibling-drift manifest peek). The new helper
generalises that pattern from "1 KB manifest peek" to "1 cluster row
group fetch".

**Rationale**: Hyparquet honours parquet row-group min/max stats for
predicate pushdown; the underlying `asyncBufferFromUrl` issues HTTP
range requests for only the relevant byte ranges. Cache-API caches
the resulting byte ranges via the existing `cache.ts` wrapper, so a
repeat-cluster query is served from the local cache without a new
network round-trip.

**Alternatives considered**:
- *Full-file fetch of `neuroscape_vectors.parquet`*: ~50 MB cold-cache
  penalty even when only one cluster is needed.
- *Per-cluster URL fetches against pre-split sidecar files*: doesn't
  leverage parquet's predicate pushdown, requires the build to write
  ~50 files + a manifest enumerating them, complicates deploy + cache
  validation.

---

## R-007 In-browser candidate set & re-ranking

**Decision**: The browser-side ranker
(`site/src/lib/search/neuroscape_ranker.ts`) keeps an LRU of recently
loaded cluster vector arrays keyed by `cluster_id`. Per FR-024 the
LRU is capped at 4 clusters per session by default; a 5th cluster
load triggers the "expand search depth?" affordance.

The candidate set is built from:
1. The closest cluster's top-3 brute-force matches (cosine over the
   ~9-11k INT8 vectors of one cluster in memory).
2. Each top-3 article's k=20 KNN neighbours from the existing KNN
   table on `neuroscape.parquet` (already loaded with the main
   parquet on page navigation).
3. Union → de-duped → cosine re-ranked. Neighbours whose
   `cluster_id` is NOT in the LRU and would push us past the cap are
   ranked by their precomputed KNN distance to the seed instead of by
   direct cosine to the query.

**Rationale**: Caps per-query worst-case vectors-in-memory at 4
clusters × ~10k articles × 384 B ≈ 16 MB — well within reasonable
browser memory budgets. The KNN-distance fallback for un-loaded
clusters preserves a useful ranking signal even at the cap, since
the KNN graph was itself computed from these same vectors at build
time.

**Alternatives considered**:
- *Always re-rank everything via direct cosine* (load every cluster
  the KNN walk crosses): unbounded cluster-load growth per session.
- *Brute-force across ALL 461k vectors* (skip cluster routing
  altogether): defeats the bounded-payload contract; rejected in
  spec.

---

## R-008 Cross-conference merging on atlas-root

**Decision**: Atlas-root cross-conference search runs the two ranker
pipelines IN PARALLEL (kicked off concurrently from a single
`searchAtlasRoot(query)` orchestrator):
- NeuroScape lane: full cluster-routed pipeline (R-007).
- OHBM lane: brute-force cosine over the in-memory OHBM vectors table.

Each lane returns a ranked list with cosine scores. The merge concatenates
the two lists and stable-sorts by cosine descending. **No source-bias
weighting** — the closest match across either corpus wins position 1.
Ties (rare given continuous float scores) break in favour of the
NeuroScape row (more articles → more probable that the lexically tied
match is the more general semantic neighbour).

**Rationale**: Spec FR-023 calls for no source-bias weighting. Cosine
scores are comparable across corpora because the embedding model is
the same — the OHBM corpus is a subset of "biomedical research titles"
and shares the same MiniLM semantic space as the NeuroScape corpus.

**Alternatives considered**:
- *Min-max score normalisation per corpus*: would introduce a bias
  toward the smaller corpus (OHBM 2026's per-corpus best score gets
  scaled up to 1.0); not consistent with FR-023's "closest cosine
  match wins" rule.
- *Interleaved (zipper) merge*: visually predictable but breaks the
  closest-cosine-wins invariant.

---

## R-009 Build-step caching

**Decision**: Add a new cache root `data/cache/atlas-vectors/<state-key>/`
(gitignored under the existing `data/` rule). State key derives from
`sha256(articles_csv_sha256 || hdf5_shard_manifest_sha256 || model_id
|| quantization_scheme)`. The build step skips embedding compute when
all cluster intermediate files (`cluster_<id>.npy`) exist for the
state key; otherwise compute fills the missing clusters and merges
them into the final sorted parquet.

Mirrors the UMAP-fit cache pattern shipped in PR #43
(`src/ohbm2026/atlas_package/umap_fit.py`).

**Rationale**: Embedding 461k titles at ~750 sentences/sec on a
laptop CPU is ~10 min single-pass — acceptable for one cold-cache
run. Cache hit on a subsequent rebuild is ~seconds. Mirrors the
existing UMAP-fit cache pattern (`umap_fit.fit()` + `cache_paths()`),
so operators learn one cache contract.

**Alternatives considered**:
- *No cache (rebuild every time)*: ~10 min penalty on every
  `ohbmcli build-atlas-package` invocation, including no-op rebuilds.
  Annoying for iteration.
- *Cache at per-article granularity (Stage 2 enrichment pattern)*:
  461k cache files = filesystem hostility. Per-cluster intermediate
  is the natural unit.

---

## R-010 Constitution-VII matched-pair invariant

**Decision**: Hard-pin the MiniLM checkpoint across both halves of the
matched pair. The browser worker (`semantic.worker.ts`) loads
`Xenova/all-MiniLM-L6-v2` (the Transformers.js ONNX export) from the
HuggingFace CDN; the build step (`vectors_compute.py`) loads its PyTorch
origin `sentence-transformers/all-MiniLM-L6-v2` via sentence-transformers
(the Xenova repo is ONNX-only and not loadable by sentence-transformers).
Both ids name one checkpoint, so the corpus + query embedding spaces
match — identical to the existing `/ohbm2026/` pipeline. The corpus-side
model id + model-file sha256 are recorded in the vectors-parquet manifest
for provenance.

**Implementation status**: the corpus-side provenance (model id +
sha256 in the manifest) ships in this stage. The browser-side init
handshake that recomputes the loaded model's sha256 and raises
`VectorsManifestDriftError` on mismatch is **deferred** — a runtime
ONNX-byte handshake is non-trivial (Transformers.js loads a quantised
ONNX variant, not the PyTorch weights), so it is currently only a unit-
test mock (`neuroscape_ranker.test.ts`). Until it lands, the matched
pair rests on the shared-checkpoint guarantee above, exactly as the
existing `/ohbm2026/` search already does.

**Rationale**: Cosine similarity across corpus + query embeddings is
only meaningful when both halves used the same model weights. Pinning
the model name alone is necessary but not sufficient — Hugging Face
can re-release the same model name with re-quantised weights at any
time, breaking the matched pair silently. Pinning the file sha256 is
the only way to make the invariant audit-able.

**Alternatives considered**:
- *Pin name only* (let HuggingFace serve whatever weights it has at
  that name): violates Constitution Principle VII (mismatches surface
  as silent skips, not precise errors).
- *Ship the model file ourselves from the gh-pages host*: would work
  but adds ~24 MB of new bytes to our deploy that the existing
  `/ohbm2026/` flow already gets for free from the HuggingFace CDN
  via the user's browser cache. Net-negative for users who already
  visited `/ohbm2026/`.
