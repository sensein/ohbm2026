# Implementation Plan: NeuroScape Semantic Search

**Branch**: `019-neuroscape-semantic-search` | **Date**: 2026-05-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/019-neuroscape-semantic-search/spec.md`

## Summary

Stage 015 (NeuroScape Atlas) shipped a 461k-article PubMed corpus on
`/neuroscape/` with **title-only typo-tolerant lexical search**. This spec
finishes the discoverability story by adding the deferred semantic-search
lane on `/neuroscape/`, then extends the same lane to **atlas-root** as a
cross-conference (OHBM 2026 + NeuroScape) merged ranker.

The technical approach is to **reuse the existing /ohbm2026/ MiniLM
semantic worker pattern unchanged** (Xenova `all-MiniLM-L6-v2`, 384-dim,
INT8-quantised, runs in a Web Worker), and to **leverage the cluster_id
column + k=20 KNN graph that NeuroScape already ships** to bound per-query
cost. The key Stage-15-aware moves:

1. **Add a tiny cluster-centroid table to `neuroscape.parquet`** (~80 KB
   total, eagerly loaded with the existing parquet) — drives the
   query→cluster routing.
2. **Ship per-article vectors in a NEW sibling file
   `neuroscape_vectors.parquet`** (~50 MB INT8, sorted by `cluster_id`)
   — loaded lazily via hyparquet's `asyncBufferFromUrl` + HTTP range
   requests. Predicate pushdown on `cluster_id == X` fetches only the
   row-groups for the cluster the query routes to (~4 MB cold-cache).
   The precedent for this exact loading pattern already exists in this
   repo at `site/src/lib/data_package/loader.ts:687` (the sibling-drift
   manifest peek) — we extend it from "1-KB manifest peek" to "1-cluster
   row-group fetch".
3. **Add an OHBM 2026 vectors index alongside `atlas.parquet`** (~1 MB
   INT8, brute-force) for the cross-conference atlas-root surface.
   Already structurally identical to the /ohbm2026/ minilm sidecar
   established in Stage 6.
4. **Browser-side ranking pipeline**: query → cluster centroid →
   range-fetch one cluster's vectors → brute-force cosine for top-3
   seeds → walk the k=20 KNN graph (already in `neuroscape.parquet`)
   outward → re-rank candidate set by cosine to query. The full
   ohbm2026 ranker (lexical + semantic merge via set-difference, ✨
   badge on semantic-only hits) is reused unchanged.

Nothing about `/ohbm2026/`'s search, build, or bytes changes; the
`ohbm2026.parquet` byte-identity gate stays the CI primary invariant.

## Technical Context

**Language/Version**: Python 3.14 (existing project venv); TypeScript / Svelte 5 for the UI side
**Primary Dependencies**:
- Python build: existing `ohbm2026.atlas_package` orchestrator + `pyarrow` (already used for both atlas + ohbm2026 parquets); `sentence-transformers` (already an optional extra) for the corpus-side MiniLM run.
- Browser: existing `@xenova/transformers` (`all-MiniLM-L6-v2` model already loaded by `site/src/lib/workers/semantic.worker.ts`); existing `hyparquet` + `hyparquet-compressors` (asyncBufferFromUrl already imported); existing Cache API integration via `site/src/lib/data_package/cache.ts`.

**Storage**: Three parquets on gh-pages: `ohbm2026.parquet` (unchanged), `neuroscape.parquet` (+~80 KB centroid table inside), `atlas.parquet` (+~1 MB OHBM vector table inside). One NEW sibling file `neuroscape_vectors.parquet` (~50 MB) on the deploy host alongside `neuroscape.parquet`.

**Testing**: `unittest` (Python pipeline) + `vitest` (browser unit tests, e.g. ranking-merge + cluster-routing logic) + `@playwright/test` (e2e covering the ✨ toggle flow on `/neuroscape/` + atlas-root). Mirrors the existing test split.

**Target Platform**: gh-pages static site served at `https://abstractatlas.brainkb.org/{,/ohbm2026/,/neuroscape/}`; modern browsers (the existing /ohbm2026/ semantic-search baseline of Chromium / Firefox / Safari with WebGL2 + WebAssembly).

**Project Type**: Coupled SvelteKit static site (`site/`) + Python data pipeline (`src/ohbm2026/`). Single-project conventions for both halves; no monorepo packaging.

**Performance Goals** (per spec Success Criteria):
- Toggle activation < 100 ms (centroid table already loaded with main parquet) — SC-002.
- First semantic query against the 461k-article corpus < 10 s on ≥10 Mbps broadband (range-fetches typically 1–3 cluster row-groups, ~4–20 MB cold-cache) — SC-002.
- Subsequent same-cluster query < 2 s (Cache-API hit; in-memory vectors) — SC-003.
- Build-step wall-clock added to `ohbmcli build-atlas-package` < 15 min on the operator's reference machine; cacheable via a key analogous to the UMAP-fit cache shipped in PR #43 — SC-005.
- ≥80% recall on the curated 20-query evaluation set (semantically-relevant article in top-10 hits, queries with no exact-string title overlap) — SC-006.

**Constraints**:
- `ohbm2026.parquet` MUST be byte-identical across this change (the gh-pages CI byte-identity gate's primary target) — SC-007, FR-016.
- Per-query cluster-bounded range-fetch budget capped per session (default 4 distinct clusters) — FR-024.
- No new external service credentials. Embedding compute runs locally during the Python build step — CA-004.
- All new artifacts (the per-session vectors cache, the build's per-shard intermediate caches, the build's full Python output) MUST land in gitignored paths — CA-005.

**Scale/Scope**:
- ~461 000 NeuroScape articles; ~50 clusters; each cluster ≈ 9–11 k articles in the typical shape. ~3 240 OHBM 2026 abstracts.
- Vector dimensionality 384 (Xenova MiniLM L6 v2, INT8-quantised) → 461 000 × 384 × 1 B ≈ 177 MB raw → ~50 MB INT8 with metadata after parquet's per-row-group encoding overhead.
- ~50 cluster centroids × 384 × 4 B ≈ 80 KB (centroids kept FP32 for routing-precision; the small size makes the precision-trade unnecessary).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Item-by-item, from `.specify/memory/constitution.md`:

1. **I. Reproducible Venv Execution** — All new Python (corpus embedding compute, parquet writer extensions, build-step cache, tests) runs through `.venv/bin/python`. The new optional dep (`sentence-transformers`) is the same one already cited by `pyproject.toml`'s embeddings extra. ✓
2. **II. Immutable Evidence And Canonical Data** — `neuroscape.parquet` gains an additive cluster-centroid table without mutating its existing columns; the new sibling `neuroscape_vectors.parquet` is a fresh file (no canonical rewrite). All new build artifacts land under `data/outputs/atlas-package/` (already gitignored) and `data/cache/atlas-vectors/` (NEW gitignored). ✓
3. **III. Resumable, Auditable Pipelines** — The corpus-embedding step is the new long-running phase; its per-cluster intermediate output is cached at `data/cache/atlas-vectors/<state-key>/cluster_<id>.npy`, keyed on `sha256(article_set_state_key || model_id || quantization_scheme)`. Mirrors the UMAP-fit cache (PR #43) pattern. ✓
4. **IV. Plan-First, Test-First** — `research.md` + `data-model.md` + `contracts/*` land before any source file changes; the parquet-byte-identity + cluster-routing-pipeline tests (CA-002 in the spec) are listed in `tasks.md` BEFORE the matching implementation tasks. ✓
5. **V. Secret-Safe, Commit Early And Often** — No new credentials. Embedding compute is local. Each verified slice (parquet writer extension, browser-side ranker, atlas-root search bar, e2e) commits independently. ✓
6. **VI. Fail Loudly, No Shortcuts** — All failure modes named in the spec FR-006 / FR-014 / FR-024 surface visible errors. Typed exception hierarchy follows the Stage-15 pattern: new `Stage19SemanticError` subtree (extends `Stage15Error` since the orchestrator is `build-atlas-package`) with `EmbeddingComputeError`, `VectorsParquetWriteError`, `VectorsManifestDriftError`. No bare except; no `--no-verify`; no skipped tests. ✓
7. **VII. Discover External State, Don't Hardcode It** — The article set, cluster_id assignment, KNN graph, and v1.0.1 shard layout are all already discovered at runtime by `neuroscape_loader.discover_inputs()` (Stage 15). This spec reuses that loader without adding new hardcoded enumerations. The MiniLM model id (`Xenova/all-MiniLM-L6-v2`) IS hard-pinned in browser + build code — this is a deliberate "matched pair" invariant (corpus and query embedders MUST use identical model bytes) and is treated as code-revision pinned via the model file hash carried in the vectors-parquet manifest (`model_sha256`). ✓ (with the matched-pair invariant explicitly recorded in `data-model.md`)
8. **VIII. Provenance For Organizer-Facing Outputs** — The new sibling `neuroscape_vectors.parquet` and the OHBM vectors table in `atlas.parquet` both ship with provenance in their parquet manifest: model_id, model_sha256, vector_dim, quantization_scheme, scale, article_set_state_key, code_revision, command_line, seed, build_started_utc, build_finished_utc. No absolute or user-home paths. ✓
9. **Secrets** — No new credentials boundary. ✓
10. **README/docs updates** — `README.md`'s operational runbook gains a `build-atlas-package --semantic-index` entry; `CLAUDE.md`'s "Reading order" updates to reference this plan; the spec-015 plan reference in `CLAUDE.md` is supplemented (not replaced) by a 019 pointer. ✓
11. **Commit cadence** — Each user story is one to two commits; cumulative ~6–10 commits across the branch; final push happens at PR open. ✓

**Result**: ALL ITEMS PASS. No complexity-tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/019-neuroscape-semantic-search/
├── plan.md              # THIS FILE
├── spec.md              # Feature spec (already shipped)
├── research.md          # Phase 0 — Decisions + Rationale + Alternatives
├── data-model.md        # Phase 1 — Schemas for centroid table, vectors parquet, manifest
├── contracts/
│   ├── parquet-schemas.md             # Wire-level schemas (centroid table, vectors parquet, OHBM vectors)
│   ├── cli-build-atlas-package.md     # Extension of the spec-015 CLI contract (--semantic-index flag)
│   ├── search-ranking-pipeline.md     # Browser worker API + 5-step pipeline
│   └── atlas-root-search-ui.md        # Atlas-root search bar contract
├── quickstart.md        # Operator runbook
├── checklists/
│   └── requirements.md  # (already shipped from /speckit-specify)
└── tasks.md             # Phase 2 — created by /speckit-tasks (not this command)
```

### Source Code (repository root)

Single-project layout; touches both halves of the existing tree.

```text
src/ohbm2026/
├── atlas_package/
│   ├── orchestrator.py             # MODIFIED — add semantic-index step + cache key
│   ├── parquet_writer.py           # MODIFIED — write cluster-centroid table into neuroscape.parquet; write atlas-vectors table into atlas.parquet
│   ├── cli.py                      # MODIFIED — new flag `--semantic-index` / `--skip-semantic-index`
│   ├── semantic_index.py           # NEW — pyarrow writer for neuroscape_vectors.parquet (sorted by cluster_id; row-group sized for predicate pushdown)
│   ├── vectors_compute.py          # NEW — runs corpus-side MiniLM inference (sentence-transformers); per-cluster cached intermediate
│   └── provenance.py               # MODIFIED — extends Stage-15 provenance schema with vectors-build entries
└── exceptions.py                   # MODIFIED — add Stage19SemanticError subtree

site/src/
├── lib/
│   ├── workers/
│   │   └── semantic.worker.ts      # MODIFIED — extend the existing OHBM worker to accept a "cluster-routed" mode + KNN expansion
│   ├── search/
│   │   ├── semantic.ts             # MODIFIED — extend facade for /neuroscape/ + atlas-root callers
│   │   └── neuroscape_ranker.ts    # NEW — 5-step pipeline orchestrator; calls the worker + the parquet range-fetch
│   ├── data_package/
│   │   └── loader.ts               # MODIFIED — extend the existing asyncBufferFromUrl pattern (currently used by verifyAtlasSiblingDrift at line 687) to range-fetch cluster row-groups from neuroscape_vectors.parquet
│   ├── shards.ts                   # MODIFIED — new loader helpers loadClusterCentroids() + loadClusterVectors(clusterId)
│   └── components/
│       ├── SearchBar.svelte                # MODIFIED — corpus-parameterised id: autocomplete data source so the same component drives all three surfaces (FR-025)
│       ├── NeuroscapeBrowsePanel.svelte    # MODIFIED — mount the SHARED SearchBar (replaces the slim cluster-and-year-scoped input)
│       └── AtlasRootSearchBar.svelte       # NEW — thin wrapper around the shared SearchBar with cross-conference id: autocomplete + placeholder copy
├── routes/
│   └── +page.svelte                # MODIFIED on atlas-root mode only — mount the new search bar
└── tests/
    ├── unit/
    │   └── neuroscape_ranker.test.ts   # NEW — vitest, mocks the worker + buffer; tests the 5-step pipeline
    └── e2e/
        └── semantic.spec.ts            # MODIFIED — extend existing /ohbm2026/ semantic suite with /neuroscape/ + atlas-root cases

tests/
├── test_atlas_semantic_index.py        # NEW — unittest for semantic_index.py (sorted by cluster_id, row-group predicate pushdown, byte-identity rebuild test)
├── test_atlas_vectors_compute.py       # NEW — unittest for vectors_compute.py (deterministic embedding, per-cluster cache hit/miss, INT8 round-trip)
└── test_atlas_orchestrator.py          # MODIFIED — extend existing e2e to assert semantic-index artifacts produced under skip=False
```

**Structure Decision**: Single-project layout — there is no monorepo; `src/ohbm2026/` is one Python package, `site/` is one SvelteKit project. The feature spans both because the Python side produces the vectors-parquet artifact and the browser side consumes it. No new top-level directories are added; new modules slot into the existing `atlas_package`, `lib/search`, `lib/workers`, and `tests/` trees that Stage 15 already established.

The decision is forced by the existing project shape — adding the semantic index to Stage-15-canonical files (`neuroscape.parquet` and `atlas.parquet`) requires extending the Python orchestrator that built them, and the browser worker pattern is already there for `/ohbm2026/`. Forking either side into a separate module would multiply the boundaries the user has to learn without buying anything.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified.

Constitution Check passed all items (see above). No complexity tracking entries.
