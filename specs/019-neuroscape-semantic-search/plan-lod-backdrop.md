# Phase 2 — Progressive LOD backdrop (blue-noise hierarchical scatter)

Branch: `019-progressive-lod-backdrop` (off PR-47 head
`019-neuroscape-semantic-search`; merges back into it).

## Problem

The atlas-root + `/neuroscape/` UMAP scatter ships the full NeuroScape
backdrop with no level-of-detail structure:

- **atlas-root** range-fetches one `backdrop_decimated` table (≤50k,
  per-cluster *stratified random*) from `neuroscape.parquet` in a single
  shot. Stratified-random within a cluster oversamples dense blobs and
  drops the sparse filaments / boundaries that define the silhouette.
- **`/neuroscape/`** loads the full 461k `coords` + `articles` and renders
  every point — the root cause of the disabled 3D auto-rotate, the
  un-mirrored 3D lasso, and the ~300 MB lasso-cycle heap churn.

Neither surface can paint a coarse shape first and refine, and atlas-root
must fetch the whole 50k blob before the first point appears.

## Design

### Downsampling that preserves shape — quadtree blue-noise LOD

`src/ohbm2026/atlas_package/lod.py`:

```
assign_lod_levels(coords_2d, *, resolutions, tiebreak_keys) -> int16[N]
```

Coarse→fine greedy, fully deterministic (no RNG):

1. Normalise coords to a unit square with a *single* span
   (`max(span_x, span_y)`) so grid cells are square in UMAP space → a
   spatial (not per-axis) uniform sample.
2. For each resolution `R_L` (L = 0..len(resolutions)-1), bin every
   still-unclaimed point into an `R_L × R_L` grid. For each occupied
   cell pick ONE representative (smallest `tiebreak_key`, default
   `pubmed_id` → order-independent + reproducible), assign it level `L`,
   mark it claimed.
3. All points still unclaimed after the last resolution → final "rest"
   level `len(resolutions)` so `union(levels) == all points`.

Properties: each cumulative prefix `levels ≤ k` is ≤1 point per cell at
`R_k` (a blue-noise cover → silhouette preserved); denser regions occupy
more cells → contribute more points (density gradient preserved); levels
grow geometrically; full corpus recoverable by loading every level.

Default `resolutions = (24, 48, 96, 192, 384, 768)` → 6 representative
levels + 1 rest (`lod0..lod6`). Tune against the real 461k build.

### Encoding into the parquet (so not everything is fetched)

The envelope parquet range-fetches at *one-outer-row* granularity (an
inner table's bytes are an atomic BLOB). So the hierarchy must be
*separate outer rows*, not row-groups inside one inner table.

`neuroscape.parquet` changes:

- `coords` table: **+ `lod_level INT16`** (full corpus). Lets
  `/neuroscape/` cap the scatter with `lod_level <= cap` and zero extra
  fetch — the corpus is already resident for search.
- Replace the single `backdrop_decimated` outer row with
  **`backdrop_lod0 … backdrop_lodN`** outer rows. Each is the existing
  self-contained backdrop schema (`pubmed_id, cluster_id, umap_2d,
  umap_3d, title, year`) over that level's rows → each independently
  range-fetchable.
- Manifest: `n_backdrop_levels`, `backdrop_lod_sizes` (list),
  `lod_resolutions`, `backdrop_default_level_cap`.

Provenance gains `lod_coverage`: per cumulative level, occupied-cell
coverage at the finest reference resolution (a quantitative "shape
maintained" check, not an assertion — constitution VIII).

### Progressive rendering (browser)

`loader.ts`:
- `loadBackdropLevelFromNeuroscape(level)` — range-fetch one
  `backdrop_lod{level}` outer row (mirrors
  `loadBackdropDecimatedFromNeuroscape`).
- `readBackdropLevelCount()` — read `n_backdrop_levels` from the sibling
  manifest footer (cheap).

`+page.svelte`:
- atlas-root: fetch `lod0` → set `atlasBackdrop` → first paint; then
  `Promise.all(lod1..lodCap)` → concat → second paint + single
  index/derived-map build. Remainder levels fetched on demand (zoom) —
  stretch.
- neuroscape: derive `scatterBackdrop` capped by `lod_level <= cap` from
  the already-loaded `coords`; full `articles` still feed search.

## Files

- `src/ohbm2026/atlas_package/lod.py` (new) + `tests/test_atlas_lod.py` (new)
- `src/ohbm2026/atlas_package/parquet_writer.py` (coords.lod_level,
  backdrop_lod tables) + `tests/test_atlas_parquet_writer.py`
- `src/ohbm2026/atlas_package/orchestrator.py` (call lod, pass levels,
  manifest, provenance.lod_coverage) + `tests/test_atlas_orchestrator.py`
- `site/src/lib/data_package/loader.ts` (+ progressive fns) +
  `site/src/tests/unit/loader_dispatch.test.ts`
- `site/src/routes/+page.svelte` (progressive wiring)
- `specs/019-neuroscape-semantic-search/contracts/parquet-schemas.md`
  (document coords.lod_level + backdrop_lod tables)

## Verification

1. `tests/test_atlas_lod.py` — determinism, full coverage, ≤1-per-cell at
   each prefix, degenerate inputs.
2. `PYTHONPATH=src .venv/bin/python -m unittest` atlas_package suite.
3. `pnpm test` + `pnpm check` + `pnpm build` (site).
4. Synthetic-fixture build via the orchestrator test (no 461k needed).
5. Optional real `ohbmcli build-atlas-package` to tune `resolutions` +
   confirm level sizes / coverage.

## Constitution

I venv-only · II all new artefacts gitignored (no data committed) ·
III deterministic/cacheable build unchanged · IV this doc + tests-first ·
VI typed errors, no silent fallback (missing level → loud) ·
VIII `lod_coverage` provenance + seed recorded.
