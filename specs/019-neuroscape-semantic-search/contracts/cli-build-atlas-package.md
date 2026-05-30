# Contract: `ohbmcli build-atlas-package` Extensions

**Status**: Phase 1 contract for spec 019 · **Date**: 2026-05-27 ·
**Extends**: [specs/015-neuroscape-context/contracts/cli-build-atlas-package.md](../../015-neuroscape-context/contracts/cli-build-atlas-package.md)

Spec 015 established the `ohbmcli build-atlas-package` CLI. Spec 019
adds the semantic-index build step to that same command. This contract
records ONLY the deltas from spec 015's contract.

---

## 1. New CLI flags

```text
--semantic-index / --no-semantic-index  (default: --semantic-index)
   Whether to compute corpus vectors + write the sibling
   neuroscape_vectors.parquet + the atlas-root ohbm_vectors table.

--semantic-cache-root <PATH>            (default: data/cache/atlas-vectors)
   Root for the per-cluster intermediate cache (analogous to
   --umap-cache-root in spec 015). Gitignored under the existing
   data/ rule.

--semantic-model-id <STR>               (default: Xenova/all-MiniLM-L6-v2)
   Override for testing / future model swaps. Production MUST use the
   default to preserve the matched-pair invariant (R-010) with the
   existing /ohbm2026/ semantic worker.
```

`--no-semantic-index` skips the embedding-compute step + does NOT
write `neuroscape_vectors.parquet`. `neuroscape.parquet` STILL gains
the `cluster_centroids` table when this flag is on (centroid compute
is fast — no skip needed) ONLY IF prior vectors exist somewhere on
disk to compute from; otherwise the centroid table is omitted and the
browser falls back to lexical-only on `/neuroscape/` (per FR-013 the
parquet itself is unchanged structurally — extra tables remain
optional).

---

## 2. New exit codes

Stage 19 errors join the Stage 1/2/3/4/6/11/15 hierarchy already in
`src/ohbm2026/exceptions.py`. Adding to the existing CLI exit-code
map in `src/ohbm2026/atlas_package/cli.py`:

```text
EmbeddingComputeError      → 8
VectorsParquetWriteError   → 9
VectorsManifestDriftError  → 10
```

All three are new subclasses of `Stage19SemanticError` (NEW), which
subclasses the existing `Stage15Error` (shipped in spec 015) so any
caller of the Stage-15 base class catches Stage-19 errors too.

---

## 3. New provenance fields

The existing `data/provenance/build_atlas_package__<state-key>.json`
provenance schema gains a `semantic_index` block:

```text
provenance.semantic_index:
  enabled:               bool          # True when the step ran (not skipped)
  state_key:             str (12 hex)  # sha256-prefix of (article_set_state_key || model_id || quantization)
  model_id:              str           # Xenova/all-MiniLM-L6-v2
  model_sha256:          str (64 hex)  # local file sha256 at compute time
  vector_dim:            int           # 384
  quantization:          str           # "int8-global-scale"
  scale:                 float         # 127.0 / max_abs_original
  max_abs_original:      float         # for audit
  n_neuroscape_vectors:  int
  n_ohbm_vectors:        int
  cluster_count:         int           # mirrors cluster_centroids table
  cosine_recovery_mae:   float         # build-side quality check
  cache_hits:            int           # per-cluster cache hits during this run
  cache_misses:          int           # per-cluster cache misses (i.e., embedded fresh)
  build_seconds:         float         # wall-clock of just the semantic-index step
```

All paths in the provenance JSON remain repo-relative (CA-008).

---

## 4. New outputs the CLI MUST emit (when `--semantic-index` is on)

| Path | Notes |
|---|---|
| `<output_root>/neuroscape.parquet` | EXISTING, now includes `cluster_centroids` table |
| `<output_root>/neuroscape_vectors.parquet` | NEW |
| `<output_root>/atlas.parquet` | EXISTING, now includes `ohbm_vectors` table |
| `<semantic_cache_root>/<state-key>/cluster_<id>.npy` | Per-cluster intermediate cache (gitignored) |
| `<semantic_cache_root>/<state-key>/manifest.json` | Cache-validity sidecar (one file per cache state) |
| Updated provenance JSON (path unchanged) | New `semantic_index` block as above |

---

## 5. Compatibility with the existing UMAP-fit cache

The semantic-index cache is independent of the UMAP-fit cache shipped
in PR #43. Both caches keyed on different state keys (UMAP keyed on
vectors+UMAP params; semantic keyed on articles+model). A rebuild
that changes ONLY the model_id invalidates only the semantic cache.

---

## 6. Idempotency + byte-identity guarantees (analogous to spec 015 R-005 / SC-004)

Two consecutive `ohbmcli build-atlas-package --semantic-index` runs
with pinned timestamps and unchanged inputs MUST produce byte-identical
artefacts for:

- `neuroscape.parquet` (the existing byte-identity contract carries
  forward, now including the new `cluster_centroids` table)
- `neuroscape_vectors.parquet`
- `atlas.parquet` (incl. the new `ohbm_vectors` table)
- `data/provenance/build_atlas_package__<state-key>.json`

`ohbm2026.parquet` MUST remain byte-identical to its pre-spec-019
form across this change (FR-016 / SC-007).
