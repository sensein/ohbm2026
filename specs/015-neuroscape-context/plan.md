# Implementation Plan: NeuroScape Context — Cross-Conference Atlas Landing Page + NeuroScape PubMed Subsite

**Branch**: `015-neuroscape-context` | **Date**: 2026-05-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/015-neuroscape-context/spec.md`

## Summary

Replace the bare-root meta-refresh redirect at
`abstractatlas.brainkb.org/` with a real cross-conference atlas landing
page (NeuroScape PubMed 1999–2023 backdrop colour-coded by cluster +
OHBM 2026 overlay with a binary toggle + 2D/3D control + lasso → grouped
result list), and add a new sibling subsite at `/neuroscape/` for full
PubMed abstract navigation against the ~600K-article corpus. The
existing `/ohbm2026/` SvelteKit site is **untouched** beyond a single
data-loader path string change (`data.parquet → ohbm2026.parquet`) so
the three deployments — `/`, `/ohbm2026/`, `/neuroscape/` — each read a
uniquely-named parquet (FR-022, SC-008).

Technical approach (locked after Phase 0 research):

- **Three-parquet layout.** `ohbm2026.parquet` (renamed from
  `data.parquet`, content-identical), `neuroscape.parquet` (new —
  pubmed_id + title + year + cluster_id + 2D/3D UMAP coords +
  precomputed k-NN ids + clusters row group + title-only typo-tolerant
  lexical search index; **no PubMed body fields**), `atlas.parquet`
  (new — landing-page scatter rows pointing into the two siblings by
  stable id; **no duplicated bodies**). `atlas.parquet`'s `build_info`
  embeds the two sibling state-keys for drift detection (FR-007,
  FR-026).
- **Runtime PubMed body fetch.** Per the 2026-05-23 clarification,
  authors / journal / abstract text / DOI are NOT persisted in any
  parquet. The `/neuroscape/abstract/<pubmed_id>/` detail page
  fetches them at view time from NCBI E-utilities (`efetch.fcgi`,
  CORS-enabled). In-memory session cache; 3-retry exponential
  backoff; explicit body-offline error state on persistent failure
  (FR-019a, R-015).
- **Semantic search deferred.** Stage 15 ships title-only lexical
  search on `/neuroscape/`. The MiniLM → NeuroScape Stage-2 projector
  + semantic search is explicitly out of scope and lands in a sibling
  stage (R-016).
- **Single SvelteKit project, three build modes** controlled by a new
  `SITE_MODE` env (`ohbm2026` / `neuroscape` / `atlas-root`) + the
  existing `BASE_PATH`. The deploy workflow runs the build three times
  and stages each tree under the appropriate publish path. The
  `ohbm2026` mode preserves every existing route and code path
  byte-identically (modulo the parquet pointer); the `neuroscape` and
  `atlas-root` modes branch only on the home-page route and on the
  shard-loader URL.
- **New Python orchestrator**: `ohbmcli build-atlas-package` produces
  `neuroscape.parquet` + `atlas.parquet` from (a) the NeuroScape v1.0.1
  release (HDF5 shards + CSVs + checkpoint), (b) the existing OHBM 2026
  `voyage_stage2_published` recipe vectors, (c) the latest
  `ohbm2026.parquet` (so `atlas.parquet` can name its state-key). UMAP
  is fitted once on NeuroScape Stage-2 vectors with a documented seed
  + params, then OHBM 2026 abstracts are projected by `umap.transform`.
- **Existing `ohbmcli build-ui-data`** (Stage 6 / Stage 10) gains a
  single output-filename change: `data.parquet → ohbm2026.parquet`. No
  schema, content, or feature change to that pipeline.

## Technical Context

**Language/Version**: Python 3.14 (existing pipeline) + TypeScript 5.7 /
Svelte 5.16 (existing SvelteKit site).
**Primary Dependencies**:
- Python: existing `pyarrow` (parquet writer; reused from
  `src/ohbm2026/ui_data/formats/parquet_single.py`), existing
  `umap-learn` (UMAP fit + `umap.transform` for OOS projection),
  existing `h5py` (HDF5 shard read; used by
  `scripts/derive_neuroscape_centroids.py`), existing `numpy`.
  No new dependencies — every required library is already in
  `pyproject.toml`'s optional groups (`embeddings`, `enrich`) or in
  the `derive-neuroscape-centroids` script's import set.
- Browser: existing `hyparquet` + `hyparquet-compressors` (already in
  `site/package.json`; reused via `loader.ts`). No additions.
**Storage**:
- Inputs: `data/inputs/neuroscape-source/<v101>/…` (operator-supplied,
  gitignored); existing OHBM 2026 voyage stage-2 bundles under
  `data/outputs/embeddings/voyage/...` (already produced).
- Intermediate: `data/outputs/atlas-package/<state-key>/` containing
  UMAP fit (`umap_3d.npy`, `umap_2d.npy`, model pickle), NeuroScape
  per-article projection table, per-cluster colour assignment.
- Published: a single staging directory
  `data/outputs/parquets/<state-key>/` carrying the three publishable
  parquets (`ohbm2026.parquet`, `neuroscape.parquet`,
  `atlas.parquet`). Each is then uploaded to its own Dropbox-style URL
  and pointed at by the corresponding deploy mode's
  `VITE_DATA_PACKAGE_URL`.
- Provenance: single
  `data/provenance/neuroscape_context_provenance__<state-key>.json`.
**Testing**: existing `unittest` (Python) + existing `vitest` (Svelte
unit, jsdom) + existing `playwright` (e2e against the prerendered
preview). No new test frameworks.
**Target Platform**: Modern browsers (Chromium / WebKit / Firefox);
gh-pages static deploy via the existing
`.github/workflows/deploy-ui.yml` pipeline, extended to build three
modes and stage three publish trees.
**Project Type**: Web application (SvelteKit static site) + Python
data pipeline (`ohbmcli`).
**Performance Goals**:
- Landing-page first paint ≤ 5 s on a recent laptop on a warm cache
  (SC-003); ≥ 30 fps drag/rotate on the default decimated backdrop
  (SC-003).
- Landing-page first paint ≤ 10 s on a mid-range mobile (SC-007).
- Rebuild idempotent second-run completes in ≤ 60 s via cache hits
  (SC-004).
- Three-clicks-max search → detail on the NeuroScape subsite
  (SC-005).
**Constraints**:
- `/ohbm2026/` build output byte-identical to pre-change modulo the
  parquet pointer string (FR-022, SC-008). Verified by an automated
  diff in CI.
- `atlas.parquet` does NOT duplicate abstract bodies — it references
  rows in the sibling parquets by stable id (FR-006).
- Cross-parquet state-key drift surfaces as a precise loader-side
  error (FR-007, FR-026).
- No new credentials; no new hosting target.
**Scale/Scope**:
- ~600K NeuroScape PubMed articles (1999–2023), 175 clusters.
- ~3K OHBM 2026 accepted abstracts (current state-key
  `f0c51e80dc0e`).
- Default decimated backdrop ≤ 50K points for mobile; full backdrop
  available behind a "Show full atlas" affordance on desktop.
- Published parquet sizes (post-clarification, post-body-drop):
  ~25 MB `ohbm2026.parquet`, ~70 MB `neuroscape.parquet`, ~40 MB
  `atlas.parquet`. See `data-model.md` size table.

## Constitution Check

- **I. Reproducible Venv Execution** — PASS. The new
  `ohbmcli build-atlas-package` subcommand runs through `.venv/bin/python`
  exactly as every existing `ohbmcli` subcommand does (`cli.py` wiring
  unchanged). Phase-2 task ordering will surface a single `.venv`-based
  command line in `quickstart.md` for the maintainer. No system Python.
- **II. Immutable Evidence And Canonical Data** — PASS. No canonical
  raw dataset is rewritten. The new parquet stage writes to
  `data/outputs/parquets/<state-key>/` (gitignored under `data/`); the
  UMAP fit lands in
  `data/outputs/atlas-package/<state-key>/umap_*.{npy,pkl}` (gitignored).
  The rename `data.parquet → ohbm2026.parquet` happens at the
  `ohbmcli build-ui-data` emit step inside the same gitignored root,
  not in any tracked file. No new tracked artifacts.
- **III. Resumable, Auditable Pipelines** — PASS.
  `ohbmcli build-atlas-package` checkpoints in two places: (a) the UMAP
  fit cache keyed by `sha256(neuroscape_stage2_vectors || umap_params)`
  under `data/cache/atlas-umap/<cache-key>/`, and (b) the per-OHBM-2026
  abstract projection cache keyed by `sha256(stage2_vector ||
  umap_params)` under `data/cache/atlas-projection/<cache-key>.json`.
  A second invocation with unchanged inputs reads both caches and
  produces byte-identical parquets (FR-005, SC-004).
- **IV. Plan-First, Test-Driven Delivery** — PASS. Phase-2 task
  ordering will require: a failing Python `unittest` for each new
  exception class in `ohbm2026.exceptions` (Stage15Error subtree)
  BEFORE the corresponding orchestrator code lands; a failing vitest
  for the binary toggle store BEFORE the SvelteKit toggle component
  lands; a failing Playwright e2e for the bare-root scatter + click +
  deep-link BEFORE the route is wired. The byte-identical `/ohbm2026/`
  diff (SC-008) is added as a CI step BEFORE the
  `data.parquet → ohbm2026.parquet` rename ships.
- **V. Secret-Safe, Reviewable** — PASS. No new credentials; existing
  Voyage/OpenAI keys are not touched by this feature (it reads
  already-cached vectors). Commits land in small slices per US
  ordering (Phase 0 bench → Python pipeline → SvelteKit modes →
  deploy workflow → README/docs).
- **VI. Fail Loudly** — PASS. Every error path enumerated in FR-026
  surfaces a typed exception (see Phase 0 research; new
  `Stage15Error` subtree under `OhbmStageError`). The browser-side
  loader surfaces cross-parquet state-key drift as a visible page
  error (not a NaN-coordinate silent partial render). The deploy job
  fails on any link-check error (FR-024).
- **VII. Discover External State, Don't Hardcode It** — PASS. The
  NeuroScape cluster count (175 today), shard manifest, and centroid
  table version are read from the on-disk release files at runtime
  via the same conventions
  `scripts/derive_neuroscape_centroids.py` already uses (centroid
  table version stamp, SHA-checked shard manifest). The OHBM 2026
  state-key is read from the existing
  `ohbm2026.parquet`'s `build_info` block at orchestrator runtime.
  No hardcoded counts.
- **VIII. Provenance For Organizer-Facing Outputs** — PASS. Each of
  the three parquets carries a `build_info` block; `atlas.parquet`'s
  `build_info` additionally embeds the two sibling state-keys
  (FR-007). A single
  `data/provenance/neuroscape_context_provenance__<state-key>.json`
  records every input SHA, the UMAP seed/params, the Voyage bundle
  id, the centroid table version, the code revision, the command
  line, and the OHBM 2026 inclusion / omission counts (CA-008).
  Repo-relative paths only.
- **Secrets, docs, commits** — README + reproducibility-vision +
  CLAUDE.md are updated in the same change set (CA-003).
- **Verified-slice commits** — Phase-2 will order tasks so the
  Python pipeline lands first (with `unittest` passing), then the
  SvelteKit `SITE_MODE` plumbing (with vitest + Playwright passing
  on the OHBM-2026 mode regression), then the new routes, then the
  deploy workflow expansion, then docs. Each slice is its own
  commit.

No Constitution Check violations.

## Project Structure

### Documentation (this feature)

```text
specs/015-neuroscape-context/
├── plan.md                                # This file
├── research.md                            # Phase 0
├── data-model.md                          # Phase 1
├── quickstart.md                          # Phase 1
├── contracts/
│   ├── parquet-schemas.md                 # the three parquets' inner tables + build_info
│   ├── atlas-root-ui.md                   # bare-root landing-page UI contract
│   └── cli-build-atlas-package.md         # ohbmcli build-atlas-package CLI surface
├── checklists/
│   └── requirements.md                    # already exists
└── tasks.md                               # /speckit-tasks output (NOT written by /speckit-plan)
```

### Source Code (repository root)

```text
src/ohbm2026/
├── atlas_package/                         # NEW package (Stage 15)
│   ├── __init__.py
│   ├── orchestrator.py                    # main entry — wired to `ohbmcli build-atlas-package`
│   ├── neuroscape_loader.py               # reads HDF5 shards + CSVs (extends derive_neuroscape_centroids.py conventions)
│   ├── umap_fit.py                        # deterministic 2D + 3D UMAP fit; cache key = sha256(stage2_vectors || params)
│   ├── ohbm_projector.py                  # umap.transform for OHBM 2026 stage-2 vectors; per-abstract cache
│   ├── cluster_palette.py                 # deterministic colour assignment (top-N by point count + fallback palette)
│   ├── neighbour_index.py                 # k-NN over NeuroScape Stage-2 vectors (k=20) for neuroscape.parquet
│   ├── parquet_writer.py                  # emits neuroscape.parquet + atlas.parquet
│   ├── provenance.py                      # single provenance JSON writer
│   └── link_check.py                      # extends ui_data/link_check.py for the new corpora (PubMed, DOI, NeuroScape)
├── exceptions.py                          # EXTEND with Stage15Error subtree (see contracts/cli-build-atlas-package.md)
├── ui_data/
│   └── formats/parquet_single.py          # MINIMAL change: rename output filename `data.parquet → ohbm2026.parquet`
└── cli.py                                 # add `build-atlas-package` subcommand

scripts/
└── run_build_atlas_package.py             # thin shim mirroring run_enrich_abstracts.py pattern

site/
├── svelte.config.js                       # extend basePath logic; read SITE_MODE
├── src/
│   ├── lib/
│   │   ├── data_package/loader.ts         # parametrise parquet URL by SITE_MODE; add atlas.parquet decoder branch
│   │   ├── site_mode.ts                   # NEW small module — reads $env/static/public for SITE_MODE
│   │   └── stores/atlas_overlay.ts        # NEW — binary toggle store (localStorage-backed)
│   ├── routes/
│   │   ├── +layout.svelte                 # add SITE_MODE-conditional header (titles, outbound links)
│   │   ├── +page.svelte                   # add SITE_MODE-conditional rendering for atlas-root mode
│   │   ├── abstract/[id]/                 # used by ohbm2026 + neuroscape modes; record-shape branch by SITE_MODE
│   │   └── (existing routes unchanged)
│   └── tests/
│       ├── unit/atlas_overlay.test.ts     # NEW vitest
│       └── e2e/atlas_root.spec.ts         # NEW Playwright spec
└── conference-root-redirect/              # RETIRED — removed from publish staging

.github/workflows/
├── deploy-ui.yml                          # extend: build three modes, stage three publish trees
└── pr-preview.yml                         # mirror: PR previews include /pr-<N>/{,ohbm2026/,neuroscape/}

tests/
├── test_atlas_orchestrator.py             # NEW — orchestrator end-to-end with fixture inputs
├── test_atlas_umap_fit.py                 # NEW — deterministic seed → byte-identical
├── test_atlas_parquet_writer.py           # NEW — schema, build_info, sibling state-key embedding
├── test_atlas_provenance.py               # NEW — schema validation
├── test_atlas_exceptions.py               # NEW — every FR-026 error path
└── test_ohbm2026_parquet_rename.py        # NEW — byte-identity (data.parquet → ohbm2026.parquet) for FR-022

data/                                      # ALREADY gitignored
├── inputs/neuroscape-source/<v101>/…      # operator-supplied NeuroScape release
├── cache/
│   ├── atlas-umap/<cache-key>/            # NEW UMAP fit cache
│   └── atlas-projection/<cache-key>.json  # NEW per-OHBM-2026 abstract projection cache
├── outputs/
│   ├── atlas-package/<state-key>/         # NEW staging for UMAP artefacts
│   └── parquets/<state-key>/              # NEW staging for the three publishable parquets
└── provenance/neuroscape_context_provenance__<state-key>.json
```

**Structure Decision**: extend the existing `src/ohbm2026/` Python
package with a new `atlas_package/` module, extend the existing
SvelteKit site under `site/` with `SITE_MODE`-conditional rendering on
two of its routes (home + abstract detail) without touching any other
route, and extend the existing `deploy-ui.yml` workflow to build three
modes. No new top-level project, no new framework.

## Complexity Tracking

> Constitution Check passes — no violations to justify.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|

(None.)
