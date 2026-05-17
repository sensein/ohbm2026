# Implementation Plan: Stage 6 — UI Rewrite (Static Search Site)

**Branch**: `008-ui-rewrite` | **Date**: 2026-05-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/008-ui-rewrite/spec.md`

## Summary

Rebuild the OHBM 2026 abstract search UI as a **static SvelteKit + Vite site** served from GitHub Pages, built and deployed by a GitHub Action with **per-PR preview management**. The site consumes a **static-JSON-shard data package** (the Session-2026-05-17 clarification ruled out DuckDB-WASM at this scale — 3,244 abstracts × 15 (model, input) cells fit in ~9 MB gzipped, where in-memory JS aggregation runs in < 10 ms). Adds previously-missing capabilities to the prior UI: program-assigned **poster ids** (not submission ids), restored **author + affiliation details**, **3D UMAP**, **typo-tolerant lexical + semantic search** (MiniLM-L6 ONNX via transformers.js, int8-quantized vectors), **interactive facet recomputation**, a **saved-list shopping cart** with `mailto:`-based export, an **optional walkthrough**, an **About page** with build-time verified references, and **mobile-first responsive layout**. Accepted abstracts only; withdrawn submissions never surface anywhere.

The implementation is **stage-parallel-friendly**: each user story (US1 through US8) is independently shippable as a per-route slice. Per the Session-2026-05-17 sequencing clarification, **US8 (deploy workflows + minimal placeholder) ships first as a small standalone PR** so US1–US7 can be reviewed via live PR previews (surfaced in the PR's Deployments box via `environment:` declaration, not as bot comments). MVP = US1 (search + browse on every device) lands second; US2–US7 then ship in any order, each on top of a working preview pipeline.

## Technical Context

**Languages/Versions**:
- **Build-side (data package)**: Python 3.14 in `.venv` (matches the existing pipeline; see CA-001).
- **Site (client)**: TypeScript on Node 20 LTS. The site is fully static — no server runtime.

**Primary Dependencies**:
- **Site framework**: SvelteKit 2 + Vite 5 in static-adapter mode (`@sveltejs/adapter-static`). Picked over Next.js / Astro for the smallest framework runtime (~5 KB Svelte vs ~50 KB React) and TypeScript-first DX. Decision rationale lives in `research.md` R1.
- **In-browser ML**: `@xenova/transformers` (transformers.js) loading the quantized `Xenova/all-MiniLM-L6-v2` ONNX model from the Hugging Face CDN. Cached by the browser after first visit (~23 MB one-time).
- **Search**:
  - Lexical: a **pre-built inverted index** with **n-gram bag tokens** + **Damerau-Levenshtein** distance check on candidate matches. Built at deploy time in Python (`scripts/build_lexical_index.py`); serialized as compact JSON. The browser library is small (~5 KB; a custom edit-distance lookup over the inverted-index postings).
  - Semantic: int8-quantized MiniLM vectors (`[3244, 384]` little-endian buffer) loaded on first semantic query. Cosine similarity via typed-array math in a Web Worker.
- **Plotting**: **Plotly.js Basic** (the lite bundle: scatter, gl3d, lasso events; ~700 KB gz) for both 2D and 3D UMAP. Lazy-loaded only when the user opens the projections tab.
- **State**: Svelte stores; no Redux/Pinia/etc. Cart persists via `localStorage`.
- **Walkthrough**: `shepherd.js` (~18 KB gz) or `intro.js` (~14 KB gz). Decision deferred to `research.md` R3.
- **Build-side data scripts**: stdlib + `numpy` + the existing `ohbm2026.*` pipeline (corpus + Stage 4 rollup readers). NO new Python deps.

**Storage**:
- **Site build output**: a `dist/` directory committed nowhere (gitignored under `export/`) and pushed to the `gh-pages` branch by the GitHub Action.
- **Data package**: static JSON shards + 1 binary file. Detail in `data-model.md`:
  - `data/manifest.json`, `data/abstracts.json`, `data/authors.json`
  - `data/cells/<model>_<input>.json` × 15
  - `data/topics/<model>_<input>_<kind>.json` × ≤ 45
  - `data/search/lexical_index.json`
  - `data/search/minilm_vectors.bin` (int8)
- **Provenance**: every shard embeds the build-info block (`corpus_state_key`, `code_revision`, `stage4_rollup_state_key`, `built_at`). The site footer's "build info" affordance surfaces this (CA-008).

**Testing**:
- **Python build-side**: `unittest` for the data-package builders (`scripts/build_ui_data.py`, `scripts/build_lexical_index.py`, link checker). Test-first per CA-002.
- **JS site**: **Vitest** for unit tests (store mutations, facet aggregation, edit-distance lexical match). **Playwright** for end-to-end smoke per US1 (page loads, search returns results, abstract panel opens, accepted-only invariant verified by data scan). Headless Chromium runs in CI.
- **Build-gate tests**: the GitHub Action runs (a) Python data-package builders + tests, (b) link checker against the About page, (c) JS unit suite + Playwright smoke. Any failure blocks deploy (CA-006).

**Target Platform**:
- **Production**: GitHub Pages (Jekyll-bypassed via `.nojekyll`).
- **Browsers**: evergreen Chromium / Firefox / Safari, last 2 versions; mobile Safari ≥ iOS 15, Chrome on Android ≥ 90. No IE11.

**Project Type**: client-only static SPA + Python data-package builders. Spec doesn't require a backend.

**Performance Goals** (from SCs):
- First interactive paint ≤ 3 s on typical broadband (SC-001).
- Query → ranked results ≤ 500 ms median (SC-002).
- Cell-switch UMAP re-render ≤ 1 s on a recent laptop (SC-003).
- Mobile US1 flow without horizontal scroll (SC-004).
- Data package: ≤ 8 MB gz first-paint + ≤ 3 MB gz lazy-expansion + ≤ 1.5 MB MiniLM vectors on first semantic query (SC-006).
- 90 % single-typo recall in top-10 (SC-010).
- PR-preview latency p90 ≤ 10 min (SC-008).

**Constraints**:
- **Static-only**: no server runtime; no per-request compute. Everything client-side.
- **No new secrets**: deploy uses only `GITHUB_TOKEN` (CA-004).
- **Build-gate determinism**: same corpus + same Stage 4 rollup → byte-identical data shards (build info aside). Test asserts this.
- **Withdrawn-excluded invariant**: build-time filter; every shard is asserted accepted-only before deploy.
- **No DuckDB-WASM**: ruled out by Session-2026-05-17 clarification.

**Scale/Scope**:
- 3,244 accepted abstracts (live count); ~12,000 author records; 15 active (model, input) cells; ≤ 45 topic files; ≤ 11 MB gz total data package; 8 user stories spanning 105 implementation tasks (T001–T100 + 5 `Tnnna` post-analysis inserts).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (venv-only Python)**: All build-side scripts execute via `.venv/bin/python` or `uv` targeting the venv. CI runs the same `.venv` install. ✓
- **Principle II (no committed data)**: The site `dist/`, the data-package JSON shards, the lexical index, and the int8 vectors all land under `export/ui-site/` (existing gitignored root) or `data/outputs/exported-sites/ui-site__<state-key>/` (also gitignored). The `gh-pages` branch is auto-generated by the Action and not part of source review. Nothing tracked. ✓
- **Principle III (resumable, auditable)**: The data package is rebuildable in one command (`ohbmcli build-ui-data` via `scripts/build_ui_data.py`). The build is deterministic given fixed inputs (corpus + rollup). No external network calls at build time except the About-page link checker. ✓
- **Principle IV (plan-first, test-first)**: This plan exists. Test-first is honored: Python unit tests for builders + link checker land before their impl; JS Vitest + Playwright smoke land before the corresponding UI features. CA-002 captures this in the spec. ✓
- **Principle V (secret-safe, commit-early)**: No new secrets. Deploy uses default `GITHUB_TOKEN` only. Per-slice commits per CA-002 (one commit per shipped user-story slice). ✓
- **Principle VI (fail loudly)**: Build-time link checker is a hard gate; build-time accepted-only invariant check is a hard gate; build-time data-shape contract test is a hard gate. No silent fallbacks. ✓
- **Principle VII (discover external state)**: The data-package builder discovers the (model, input) cell catalog by reading the Stage 4 rollup's `cluster_topics` table at build time. Adding a 6th model is a zero-UI-code change — just rebuild. ✓
- **Principle VIII (provenance for organizer-facing artifacts)**: Every shard carries the build-info block. The site footer surfaces it. The `gh-pages` branch's site is the published artifact; provenance is co-located. No absolute or user-home paths. ✓

**Gate verdict**: PASS, no waivers.

## Project Structure

### Documentation (this feature)

```text
specs/008-ui-rewrite/
├── plan.md                # This file (/speckit-plan output)
├── research.md            # Phase 0 — framework + ML-runtime + walkthrough lib decisions
├── data-model.md          # Phase 1 — per-shard JSON field schemas + invariants
├── quickstart.md          # Phase 1 — local-dev + build-and-deploy recipes
├── contracts/
│   ├── data-package.md    # Per-shard contract (URLs, schema, size budgets)
│   ├── github-action.md   # Workflow contract (triggers, outputs, deploy targets)
│   └── routes.md          # Site URL contract (/, /about, /abstract/<poster_id>)
├── checklists/
│   └── requirements.md    # Spec quality checklist (already exists)
└── tasks.md               # Phase 2 output (created by /speckit-tasks, not here)
```

### Source Code (repository root)

**New additions in this stage:**

```text
src/ohbm2026/ui_data/              # NEW Python package — build the data shards
├── __init__.py
├── builder.py                     # `build_ui_data_package(rollup_path, corpus_path, …)`
├── abstracts.py                   # Build `abstracts.json`
├── authors.py                     # Build `authors.json` (dedupe + normalize)
├── cells.py                       # Build `cells/<model>_<input>.json` × 15
├── topics.py                      # Build `topics/<model>_<input>_<kind>.json`
├── lexical_index.py               # Build `search/lexical_index.json`
├── vectors.py                     # Build `search/minilm_vectors.bin` (int8 from minilm Stage 3 bundle)
├── link_check.py                  # Verify About-page external URLs at build time
└── manifest.py                    # Build `manifest.json` + per-shard build-info block

scripts/
├── build_ui_data.py               # CLI thin wrapper around `ui_data.builder`
└── build_ui_site.sh               # End-to-end: `build_ui_data` + `pnpm build` → `dist/`

site/                              # NEW SvelteKit site
├── package.json
├── svelte.config.js               # static-adapter + base path for gh-pages
├── vite.config.ts
├── tsconfig.json
├── playwright.config.ts
├── vitest.config.ts
├── src/
│   ├── app.html
│   ├── lib/
│   │   ├── shards.ts              # Fetch + cache the data shards
│   │   ├── facets.ts              # Facet recomputation (in-memory)
│   │   ├── search/
│   │   │   ├── lexical.ts         # Inverted-index lookup + Damerau-Levenshtein
│   │   │   └── semantic.ts        # MiniLM ONNX inference + cosine similarity (Web Worker)
│   │   ├── stores/
│   │   │   ├── selection.ts       # Active (model, input) cell + lasso state + filters
│   │   │   ├── cart.ts            # Saved-list with localStorage persistence
│   │   │   └── tour.ts            # Walkthrough state machine
│   │   ├── components/
│   │   │   ├── SearchBar.svelte
│   │   │   ├── ResultList.svelte
│   │   │   ├── DetailPanel.svelte
│   │   │   ├── FacetSidebar.svelte
│   │   │   ├── ModelSelector.svelte
│   │   │   ├── UmapPanel.svelte   # 2D + 3D tabs; lazy-loads Plotly
│   │   │   ├── Cart.svelte
│   │   │   ├── Tour.svelte
│   │   │   └── BuildInfo.svelte
│   │   └── workers/
│   │       └── semantic.worker.ts # MiniLM inference off-main-thread
│   ├── routes/
│   │   ├── +layout.svelte
│   │   ├── +page.svelte            # Home: search + UMAP + results + detail
│   │   ├── about/+page.svelte      # About + collapsible deep-dives
│   │   └── abstract/[poster_id]/+page.svelte   # Direct-link to one abstract
│   └── tests/
│       ├── unit/                   # Vitest
│       │   ├── facets.test.ts
│       │   ├── lexical.test.ts
│       │   └── cart.test.ts
│       └── e2e/                    # Playwright
│           ├── browse.spec.ts
│           └── accepted-only.spec.ts
└── static/
    └── data/                       # Populated by build_ui_data.py at deploy time

.github/
└── workflows/
    ├── deploy-ui.yml               # Build + deploy on push to main → gh-pages root
    ├── pr-preview.yml              # PR open/update → preview under /pr-<N>; surfaces in PR Deployments box via environment:
    └── pr-preview-cleanup.yml      # PR close → remove /pr-<N>/ + mark deployment inactive via Deployments API
```

**Structure Decision**: The site lives under `site/` as a self-contained SvelteKit project (its own `package.json`, `node_modules`, build output). The Python data builders live under `src/ohbm2026/ui_data/` following the same per-stage package pattern as `enrich/`, `embed/`, `analyze/`. The GitHub Action wires them together: data builders run first, write into `site/static/data/`, then the SvelteKit build emits `dist/` which is published.

## Complexity Tracking

> Filled only if the Constitution Check produced unjustified violations. None did — the spec is decision-complete and every principle is satisfied.

## Phasing & sequencing

Per the Session-2026-05-17 clarification, **US8 ships first** as a small standalone PR so the rest of the work can be reviewed via live PR-previews. Phase numbers below match tasks.md exactly:

- **Phase 1 (Setup)** — repo layout, deps, gitignore, scaffolding (T001–T007). No UI features yet.
- **Phase 2 (Foundational)** — data-package builder skeleton (manifest + abstracts + authors + cells + topics + state_key discovery + invariant tests) (T008–T020a). Lands the build pipeline that US8 needs to exercise.
- **Phase 3 (US8, P5 promoted to first-shipped) 🥇 first PR** — `deploy-ui.yml`, `pr-preview.yml`, `pr-preview-cleanup.yml` workflows using `environment:` declarations so previews surface in the PR's Deployments box (not as bot comments). A minimal "Stage 6 — under construction" placeholder Svelte page that **renders the build_info footer + short committish in the page title** (FR-022) so reviewers can verify which committish deployed. After this PR merges, every subsequent PR for US1–US7 gets an automatic live preview tagged with its committish.
- **Phase 4 (US1, P1 MVP)** — SvelteKit shell + search bar + result list + detail panel + responsive layout + accepted-only invariant + poster-id + authors + footer build-info on every route. The site goes live for the first time with real content.
- **Phase 5 (US2)** — UmapPanel with 2D (lasso) + 3D tabs; Plotly lazy-load; model selector. Selection-by-id persists across cell switches.
- **Phase 6 (US3)** — semantic + lexical search engines; merged ranking; semantic/lexical/both toggle; author search with typo tolerance; typo-recall eval script.
- **Phase 7 (US4)** — facet sidebar + interactive facet recount over intersection (search ∩ facets ∩ lasso).
- **Phase 8 (US5)** — saved-list cart + email-my-list (`mailto:` + clipboard fallback).
- **Phase 9 (US6)** — walkthrough (shepherd.js per research.md R3).
- **Phase 10 (US7)** — About page + build-time link checker.
- **Phase 11 (Polish)** — accessibility audit, perf budget validation against SC-001..SC-011, docs reconciliation (CLAUDE.md + README + vision doc — most docs micro-updates ride in per-US PRs per Constitution IV), final PR.

Each phase ends at a green-suite checkpoint (Vitest + Playwright + Python builders + constitution lint).

## Verification surface

Per spec FR-001..FR-021 and SC-001..SC-010:

- **Functional**: `unit/` Vitest suite for stores + search + facet math; `e2e/` Playwright suite per user story.
- **Build-gate**: Python `unittest` against the data-package builders; link checker over the About page; deterministic-build assertion (same inputs → same shard SHAs modulo build info).
- **Performance**: a CI job runs Lighthouse against the production-deploy preview and asserts SC-001 (first interactive paint) + SC-006 (data-package size). Fails the deploy if either regresses by > 20 %.
- **Accepted-only invariant**: `e2e/accepted-only.spec.ts` scans the loaded shards for any `accepted_for == "Withdrawn"` and fails if found. The Python builder also asserts this at build time so the violation can't reach `dist/`.
- **Mobile**: Playwright runs the US1 smoke against a mobile-emulated viewport (360 × 640 — SC-004's stated minimum) and asserts no horizontal scroll on the home + detail screens.

## Out of scope for this stage (v1)

- Server-side anything (auth, accounts, persistent carts across devices).
- 3D-UMAP lasso (out per FR-006).
- Runtime dead-link handling on the About page (build-gated only).
- An SMTP/email service — email export is `mailto:` only.
- A user-supplied custom embedding model — only the built-in MiniLM-L6 ONNX.
- Multi-language UI — English only for v1.
- Analytics — no tracker beacons; the site is privacy-respecting.
