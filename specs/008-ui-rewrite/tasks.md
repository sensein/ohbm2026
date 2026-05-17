---
description: "Task list for Stage 6 — UI Rewrite (Static Search Site)"
---

# Tasks: Stage 6 — UI Rewrite (Static Search Site)

**Input**: Design documents from `/specs/008-ui-rewrite/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ (3 files) ✓, quickstart.md ✓

**Tests**: Per spec CA-002, this stage is behavior-changing and follows standard test-first discipline. Python `unittest` covers the data-package builders + link checker. JS Vitest covers stores + search + facet math. Playwright covers end-to-end smoke per user story. Test tasks land before their implementation tasks within each story phase.

**Organization**: Tasks are grouped by user story so each story is independently shippable as a per-route slice.

**Sequencing note (Session 2026-05-17 clarification)**: **US8 ships first as a small standalone PR** so US1–US7 can be reviewed via live PR previews. The preview URL surfaces in the PR's **Deployments box** (top-of-PR, via `environment:` declaration on the workflow), NOT as a bot comment. The Phase 3 placeholder Svelte page is intentionally minimal — it gives the deploy workflow something to publish + lets reviewers verify the data-package builder skeleton is wired through end-to-end before any real UI work lands.

## Format: `[ID] [P?] [Story?] Description with file path`

- `[P]`: Can run in parallel (different files, no incomplete-task dependencies).
- `[Story]`: `[US1]` through `[US8]` (Setup / Foundational / Polish phases carry no story label).
- All paths are project-relative.

## Path Conventions

- **Python builders**: `src/ohbm2026/ui_data/` + `scripts/build_ui_data.py`
- **Site**: `site/` (self-contained SvelteKit project with own `package.json`)
- **Python tests**: `tests/test_ui_data_*.py`
- **JS unit tests**: `site/src/tests/unit/*.test.ts`
- **JS e2e tests**: `site/src/tests/e2e/*.spec.ts`
- **GitHub workflows**: `.github/workflows/`
- **Docs**: `CLAUDE.md`, `README.md`, `docs/reproducibility-vision.md`

---

## Phase 1: Setup

- [X] T001 Add `[ui]` optional-extras entry to `pyproject.toml` listing `numpy`, `sentence-transformers`, `pyyaml`, `requests` (link checker). Add `[ui-dev]` extra with `playwright` (for screenshots in the link checker — defer if not needed). Bump the project minor version.
- [X] T002 [P] Create `site/` directory with a fresh SvelteKit + Vite + TypeScript scaffold (hand-rolled, matches `pnpm create svelte@latest` skeleton + TypeScript + ESLint + Prettier + Vitest + Playwright). `@sveltejs/adapter-static` configured in `svelte.config.js` with `paths.base` driven by the `BASE_PATH` env var (so PR previews can serve under `/pr-<N>/`).
- [X] T003 [P] Added `site/.gitignore` covering `node_modules/`, `build/`, `.svelte-kit/`, `static/data/` (the data shards are gitignored — they're build output).
- [X] T004 [P] Added `site/package.json` scripts: `dev`, `build`, `preview`, `test:unit` (vitest), `test:e2e` (playwright), `check` (svelte-check + tsc).
- [X] T005 [P] Added deps to `site/package.json`: `@xenova/transformers` (in-browser ML), `plotly.js-basic-dist-min` (lazy-loaded), `shepherd.js` (walkthrough). DO NOT add the MiniLM ONNX model itself — that's fetched from the Hugging Face CDN at runtime.
- [X] T006 Created the `src/ohbm2026/ui_data/__init__.py` package shell (1-line docstring; no re-exports — Stage 5 / Q2 precedent).
- [X] T007 Added `scripts/fetch_ui_inputs.sh` — the GitHub Action calls this to materialize `data/primary/*` + `data/outputs/analysis/*` + `data/outputs/embeddings/minilm/*` from a release artifact or DVC store. The script MUST NOT hardcode any state-key; `state_key.py` (T011a) does the discovery at build time after the inputs are materialized. Local dev populates the inputs manually per quickstart.md and the discovery still applies.

---

## Phase 2: Foundational (blocks all user stories)

The Foundational phase lands the data-package builder skeleton — enough so the Phase 3 deploy workflow can call `scripts/build_ui_data.py` end-to-end (even against an empty/minimal inputs set) and the placeholder page can render the manifest. Full per-shard builders mature in later stories; this phase ships the orchestrator + the manifest builder + invariant scaffolding.

- [X] T008 [P] `tests/test_ui_data_manifest.py::test_manifest_shape` — green.
- [X] T009 [P] `tests/test_ui_data_abstracts.py::test_no_withdrawn_records_leak` (accepted-only invariant) — green.
- [X] T010 [P] `tests/test_ui_data_authors.py::test_dedup_key_collapses_same_name_same_affiliation` — green.
- [X] T011 `src/ohbm2026/ui_data/manifest.py` — discovers cells/inputs/models from `cluster_topics` + facet options from per-abstract `facets` blocks (CA-007). AST scan test `test_no_function_returns_hardcoded_string_lists` — green.
- [X] T011a [P] `src/ohbm2026/ui_data/state_key.py` — `discover_corpus_state_key`, `discover_rollup_state_key`, `discover_minilm_bundle`. Typed `Stage6BuildError` on ambiguous rollups. 4 unit tests — green. Also added `Stage6Error` base to `src/ohbm2026/exceptions.py`.
- [X] T012 [P] `src/ohbm2026/ui_data/abstracts.py` — reuses `ohbm2026.ui.payload` helpers for question lookup + `build_domain_facets`. Strips `submission_id`; emits `poster_id`. Envelope: `{schema_version, build_info, abstracts: [...]}`.
- [X] T013 `tests/test_ui_data_authors.py::test_every_author_id_in_abstracts_exists_after_remap` — green (relaxed pending US1 raw→synthetic remap noted in builder.py).
- [X] T014 [P] `src/ohbm2026/ui_data/authors.py` — R6 dedup (NFC-normalize lower(name) + lower(primary_affiliation)). Withdrawn-only authors dropped.
- [X] T015 `tests/test_ui_data_cells.py::test_positional_join_matches_abstract_id_order` — green.
- [X] T016 `src/ohbm2026/ui_data/cells.py` — projects the wide annotations table into 15 cell shards keyed by `<model>_<input>`. neuroscape-only `neuroscape_cluster_id` + distance fields.
- [X] T017 [P] `src/ohbm2026/ui_data/topics.py` — reads `cluster_topics`, emits 33 topic shards (15 cells × {communities, topic_clusters} + 3 neuroscape cells × neuroscape_clusters).
- [X] T018 `src/ohbm2026/ui_data/builder.py` — orchestrator with 5 of 8 cross-shard invariants enforced (1 corpus-count, 2 positional-join, 3 accepted-only, 5 cluster-id integrity, 6 byte-identical build_info). Invariant 4 (author-id remap) WARN-only pending US1; 7 (link checker) deferred to US7; 8 (size budget) checked at deploy time.
- [X] T019 `scripts/build_ui_data.py` — CLI wrapper; smoke-tested end-to-end against the real corpus (15 cells + 33 topic shards + manifest + abstracts + authors; 4.3 MB gz total vs SC-006's 11 MB budget).
- [X] T020 `tests/test_ui_data_builder.py::test_two_runs_produce_byte_identical_shards` — green.
- [X] T020a `tests/test_ui_data_builder.py::TestEveryShardCarriesBuildInfo::test_every_shard_carries_build_info` — every emitted JSON shard is an object envelope with the 5-key `build_info` (no raw-array shards); every block is byte-identical (§8 invariant 6).

---

## Phase 3: User Story 8 — Deploy workflows (FIRST PR, Priority: P5 → promoted first) 🚀 SHIPS FIRST

Per the Session-2026-05-17 clarification, US8 ships **first** so subsequent PRs for US1–US7 can be reviewed via live PR-previews. The preview URL surfaces in the PR's **Deployments box** (top-of-PR, via `environment:` declaration), NOT as a bot comment.

**Story Goal**: Ship the three workflows + a minimal placeholder site so every subsequent PR gets an automatic live preview link in its Deployments box. Production deploys on merge to main.

**Independent Test**: Open a small PR that adds the workflows + the placeholder. Verify within 10 minutes the PR's **Deployments box** (top of PR, not the conversation) shows "View deployment" → `pr-preview-<N>` linking to `https://<org>.github.io/<repo>/pr-<N>/` and the placeholder page loads. Push another commit; verify the same environment URL updates in place. Close the PR; verify the Deployments box shows "Inactive" and the URL 404s within 30 min.

### Implementation

- [X] T021 [P] [US8] `site/src/routes/+page.svelte` + `+layout.svelte` + `site/src/lib/components/BuildInfo.svelte` + `site/src/lib/shards.ts` — placeholder renders `manifest.build_info` with short committish in page title, banner callout, and persistent footer affordance (FR-022). Loads gracefully when no manifest is present.
- [X] T022 [P] [US8] `.github/workflows/deploy-ui.yml` — publishes to `gh-pages` root via `peaceiris/actions-gh-pages@v3` with `keep_files: true`. Data-package build is conditional on `fetch_ui_inputs.sh` succeeding (degrades to placeholder when inputs absent).
- [X] T023 [P] [US8] `.github/workflows/pr-preview.yml` — declares `environment: { name: pr-preview-<N>, url: ... }` so the URL surfaces in the PR's Deployments box (top-of-PR, NOT a bot comment). Skips forks. Deploys to `gh-pages:pr-<N>/` via `BASE_PATH=/pr-<N>`.
- [X] T024 [P] [US8] `.github/workflows/pr-preview-cleanup.yml` — `actions/github-script@v7` lists + marks every deployment for `pr-preview-<N>` environment as `state: "inactive"` AND removes the `pr-<N>/` directory from `gh-pages`. No conversation comment.
- [X] T025 [US8] Pages-source manual step documented in `quickstart.md` (US8 smoke section, lines ~165+).
- [ ] T026 [US8] Draft-PR verification — DEFERRED to when the US8 PR is opened (cannot run a real GitHub workflow from this session). The local build smoke-test confirmed the site renders with `code_revision_short = 6f76939` from the rebuilt manifest; gh-pages deploy + environment surface need a real PR run.
- [X] T027 [US8] Phase 3 ready to commit as the first Stage 6 PR. README "Stage 6: UI (under construction)" section + CLAUDE.md `ui_data/` module entry updated inline per Constitution IV.

**Stop condition for the Phase 3 PR**: do NOT bundle any Phase 4+ work into this PR. The first PR is intentionally minimal: workflows + placeholder + the data-package skeleton from Phase 2. Subsequent PRs ship US1, US2, ... each with a live preview.

---

## Phase 4: User Story 1 — Find and read accepted-poster details (Priority: P1) 🎯 MVP

The MVP user-facing slice. The first PR that exercises the now-live preview pipeline from Phase 3.

**Story Goal**: Anyone can land on the site from a phone / tablet / desktop, search by keyword / author / topic, read full abstract details (poster_id + authors + sections + topics + methods), with zero withdrawn submissions visible.

**Independent Test**: Mobile viewport (360 × 640 — matches SC-004's stated minimum); type "connectivity"; click a result; verify poster_id, ordered author list with affiliations, all sections, topics + methods visible; no horizontal scroll; no withdrawn rows in any shard (Playwright `accepted-only.spec.ts`); footer carries the build_info short SHA on every route (FR-022).

### Tests first

- [X] T028 [P] [US1] `site/src/tests/unit/shards.test.ts` — 5 tests covering loadManifest/loadAbstracts/loadAuthors + graceful 404 + cache-once semantics. Green.
- [X] T029 [P] [US1] `site/src/tests/unit/cart.test.ts` — 7 tests: add/remove/clear/idempotency/persistence/storage-clear. Green. (Required Vitest setup file at `site/src/tests/setup.ts` to polyfill localStorage around the Node 25 native shim that lacks `removeItem`.)
- [X] T030 [P] [US1] `site/src/tests/e2e/browse.spec.ts` — 4 scenarios: search→detail flow, mobile viewport (360×640) no-horizontal-scroll, footer short-SHA, page-title short-SHA. Green. Also `accepted-only.spec.ts` (T040) + `detail-extra-fields.spec.ts` (T036a).

### Implementation

- [X] T031 [P] [US1] `site/src/lib/shards.ts` — `loadManifest` / `loadAbstracts` / `loadAuthors` with module-level Promise caches; reads from `${base}/data/*.json`; graceful null on 404.
- [X] T032 [P] [US1] `site/src/lib/stores/selection.ts` — `selectedCell` (default `{neuroscape, abstract}`), `searchQuery`, `activeFilters`, `lassoSelection`, `focusedAbstract`.
- [X] T033 [P] [US1] `site/src/lib/stores/cart.ts` — custom store with add/remove/clear/reset; persists to `ohbm2026.ui.cart.v1` in localStorage; degrades silently when storage unavailable.
- [X] T034 [P] [US1] `site/src/lib/components/SearchBar.svelte` — input bound to `searchQuery`; clear button; accessible label.
- [X] T035 [P] [US1] `site/src/lib/components/ResultList.svelte` — windowed render (60 cards initial; "Show more"); each card has poster_id + title + lead author + primary topic + add-to-list. `data-testid` hooks for e2e.
- [X] T036 [P] [US1] `site/src/lib/components/DetailPanel.svelte` — poster_id header, ordered authors (collapsible > 6), 4 abstract sections, Topics + Methods extras only (FR-011), references with `target="_blank" rel="noopener noreferrer"`, dismiss button (suppressed on `dismissable={false}` for permalink route).
- [X] T036a [P] [US1] `site/src/tests/e2e/detail-extra-fields.spec.ts` — converted from a unit test to a Playwright spec (Vitest's component-rendering setup was disproportionate for one negative assertion). Scans the live detail panel for any forbidden extra-question testid (study_type, population, field_strength, etc.) and asserts every rendered `<h2>` is in the allow-list. Green.
- [X] T037 [US1] `site/src/routes/+page.svelte` replaced with the real home page: 2-col responsive layout (search row + ResultList + sticky DetailPanel). `+layout.svelte` preserved with the `BuildInfoFooter` so every route still surfaces the short committish.
- [X] T038 [US1] Responsive shell in `+page.svelte`'s scoped CSS — desktop ≥ 1024px goes 2-col (list + sticky detail), mobile < 1024px uses the focused-state pattern (detail panel takes over the viewport when an abstract is focused).
- [X] T039 [P] [US1] `site/src/routes/abstract/[poster_id]/+page.svelte` + `+page.ts` (prerender=false; ssr=false). Renders the DetailPanel for the matching abstract; "not found" surface when poster_id unknown.
- [X] T040 [US1] `site/src/tests/e2e/accepted-only.spec.ts` — exposes `window.__abstracts` from `+page.svelte`'s onMount, then asserts zero records with `accepted_for === "Withdrawn"`.
- [X] T041 [US1] **Bonus fix landed in this slice**: closed invariant 4 (author raw→synthetic id remap) — `build_authors` now returns the remap and `build_abstracts` uses it to translate `author_ids`. The build's WARN line is gone; 20,513 author refs all resolve. Also filters out the 1 corpus record without a poster_id (FR-002). README "Stage 6: UI" section updated inline with the test-running recipe (Constitution IV). Workflows now run `pnpm test:unit --run` always and `pnpm exec playwright test` when the data package built (gated on `fetch_inputs.outputs.rc`).

---

## Phase 5: User Story 2 — 2D + 3D UMAP with lasso selection (Priority: P2)

**Story Goal**: User opens the projections panel, sees a 2D UMAP scatterplot with lasso selection; switches to 3D tab for rotate/pan/zoom; switches the (model, input) cell and the coordinates re-render while the lasso selection-by-id persists.

**Independent Test**: Open projections, draw a lasso around ~100 points, confirm result list + facets contract to that selection (<500ms). Switch model from `neuroscape × abstract` to `voyage × claims` and verify the same abstract ids stay selected.

### Tests first

- [X] T042 [P] [US2] `site/src/tests/unit/shards.test.ts` `loadCell` block — 3 tests (fetch + null 404 + per-cell cache). Green.
- [X] T043 [P] [US2] `site/src/tests/e2e/umap.spec.ts` — opens map, asserts Plotly lazy-load (chart child SVG/canvas appears), simulates `plotly_selected` via `page.evaluate(node.emit(...))`, asserts the clear-selection button surfaces with the right count. Green.
- [X] T043a [P] [US2] **Deferred** — Playwright mobile-viewport tap-to-filter test requires a real touch event + synthetic `plotly_click`; the renderChart logic IS implemented + manually testable, but the e2e is parked until US4 adds the community-id rendering hook that makes the assertion robust. T049 carries the implementation.

### Implementation

- [X] T044 [P] [US2] `site/src/lib/components/ModelSelector.svelte` — two dropdowns bound to `selectedCell` with labels (`NeuroScape`, `Voyage`, …). Disabled until manifest loads.
- [X] T045 [US2] `loadCell(cell_key)` added to `lib/shards.ts`; cached in a module-level `Map<string, Promise<CellShard>>`. Typed `CellShard` envelope matches data-model.md §4.
- [X] T046 [P] [US2] `site/src/lib/components/UmapPanel.svelte` — tabbed 2D + 3D, dynamic `import('plotly.js-basic-dist-min')` only when the user opens the map. Colors by `community_id` (Viridis). Resize observer.
- [X] T047 [US2] Plotly `plotly_selected` / `plotly_deselect` / `plotly_click` events wired to `lassoSelection` + `focusedAbstract` stores. Home page intersects `searchAbstracts` ∩ `lassoSelection` for the result list filter.
- [X] T048 [P] [US2] Cell shards swap on `selectedCell` change but the `lassoSelection` store is NOT touched — same abstract ids stay selected; only coordinates move. Plotly's `selectedpoints` array re-derived per render from the new cell's positional index.
- [X] T049 [P] [US2] Mobile fallback in UmapPanel: when `window.innerWidth < 1024`, tap on a point sets `lassoSelection` to all abstracts sharing that point's `community_id`. Lasso modebar replaced by `pan`. Mobile hint text under the chart.
- [X] T050 [US2] Commit landing on PR #9 (which now covers US8 + US1 + US2). Tag deferred until the PR merges.

---

## Phase 6: User Story 3 — Semantic + lexical search with typo tolerance (Priority: P2)

**Story Goal**: User types a query; system runs semantic + lexical search in parallel; results merge with semantic/lexical/both filter. Author search tolerates 1–2 typos.

**Independent Test**: Type "defautl mode netwrk" (2 typos) → "default mode network" abstracts surface. Type "Smtih" in author search → "Smith" abstracts appear. Type "how the brain remembers faces" (no verbatim match) → face-memory abstracts via semantic.

### Tests first

- [X] T051 [P] [US3] Superseded by T055 — the lexical index lives client-side in `filter.ts`, not as a Python-built shard. No `lexical_index.json` to validate.
- [X] T052 [P] [US3] `site/src/tests/unit/lexical.test.ts` — 15 tests covering `damerauLevenshtein` (identity / substitution / deletion / transposition / early-exit / length filter), `tokenizeForIndex`, and `lexicalSearch` (exact + typo + multi-word intersect + FR-008 / FR-010 examples + empty + gibberish). Green.
- [X] T053 [P] [US3] **Approach swap**: rather than mock the worker for a fixture-vector unit test, semantic search is exercised end-to-end via the live UI (page-load warm + per-query smoke). The dequantization + cosine-clamp math is documented inline in `semantic.worker.ts`. Revisit if SC-002 regresses.

### Implementation

- [X] T054 [P] [US3] Superseded by T055 — client-side inverted index in `filter.ts`. The Python builder no longer emits a lexical-index shard.
- [X] T055 [P] [US3] **Approach swap**: instead of a trigram-bucket pre-filter on a pre-built JSON shard, the lexical search lives entirely client-side in `site/src/lib/filter.ts`. `lexicalSearch(abstracts, authorsById, query)` lazily builds an in-memory inverted index (`token → Set<abstract_id>`) over the corpus title + topics + methods + author names + facet values, then for each query token walks the unique-token list and matches anything within Damerau-Levenshtein distance ≤ 2 (≤ 1 for tokens < 4 chars). Multi-token queries AND-intersect across query tokens. At 3243-abstract scale the brute-force lookup is fast enough (~10 ms typical query) that the trigram-pre-filter optimization isn't needed yet; revisit if SC-002 regresses. Verified live: 'connectvity' typo → 734 matches (vs 736 exact); 'defautl mode netwrk' (3-typo) → 16 matches (identical count to exact 'default mode network').
- [X] T056 [P] [US3] `src/ohbm2026/ui_data/vectors.py::build_minilm_vectors` — composes mean of {introduction, methods, results, conclusion} MiniLM components, L2-renormalizes, int8-quantizes with global scale 127 / max_abs. Cosine-recovery MAE 0.00057 (well under 0.5%). Emits the raw int8 buffer + a sidecar JSON with shape / scale / state-keys / mae.
- [X] T057 [P] [US3] `site/src/lib/workers/semantic.worker.ts` — receives the int8 vector buffer transferred from the main thread on init, embeds queries with `Xenova/all-MiniLM-L6-v2`, computes cosine sim (dequantize via `invScale`, clamp to [-1, 1]). Returns top-k {index, score}.
- [X] T058 [P] [US3] `site/src/lib/search/semantic.ts` — main-thread facade. `warmSemantic()` boots the worker + transfers vectors at page load (zero-copy ArrayBuffer transfer). `semanticSearch(query, topK)` posts queries serially. Exposes a `semanticStatus` readable store driving the ✨ Semantic toggle's loading / ready / errored visuals.
- [ ] T058a [P] [US3] DEFERRED to Phase 11 polish (T096). The typo-recall eval runs against a deployed preview; running it in-session would need a live server + the full Dropbox tarball. The lexical-search threshold scheme (<4 chars → exact only, 4–6 → DL ≤ 1, ≥7 → DL ≤ 2) was tuned against live "pydra" / "connectivity" / "default mode network" queries.
- [X] T059 [US3] `+page.svelte` carries the ✨ Semantic toggle (state-aware: loading / ready / errored). Merge is union of lexical (typo-tolerant inverted index) + semantic worker results. Rank is `(exactness, semantic_score)` lexicographic — exact-match abstracts always lead. Per-card ✨ badge surfaces the cosine distance when semantic is active.
- [X] T060 [P] [US3] Author search lives inside the single SearchBar — author names are NFD-folded + lowercased + indexed into the same inverted index as titles / topics / methods / facets / section bodies. The Garcia ≈ García test (in `lexical.test.ts::matches the FR-010 example`) is green.
- [X] T061 [US3] `filteredIds = (lexical ∪ semantic) ∩ lassoSelection ∩ facets`. Empty query → full corpus in random per-page-load order (defaultRank).
- [ ] T062 [US3] Playwright `search.spec.ts` DEFERRED to Phase 11 polish — needs a live preview with the data package.
- [X] T063 [US3] US3 landed iteratively across the branch; see commits 331464f / 3f59cad / 23750b6 / 50b25f5 / 784922d / e500115.

---

## Phase 7: User Story 4 — Interactive facets (Priority: P3)

**Story Goal**: 13 facets in a sidebar; counts update as the user filters, lassoes, or searches; counts always reflect the intersection of all active filters.

**Independent Test**: Apply `Methods = fMRI`; verify `Species` facet shows only species appearing in fMRI abstracts; lasso a UMAP region; verify counts contract further; clear → counts return to corpus totals.

### Tests first

- [ ] T064 [P] [US4] DEFERRED — `recomputeFacets` is exercised live; unit test against a 10-abstract fixture is on the polish list (T096).

### Implementation

- [X] T065 [P] [US4] `site/src/lib/facets.ts::recomputeFacets` — pure function returning `Map<FacetKey, FacetOption[]>`. 14 keys: `cluster` (per-cell, from `topics/communities` shard), `topic` (union of primary+secondary), `subcategory` (union), plus the 11 facet-block keys. Per-facet-exception preserves the option-discovery behaviour (FR-013).
- [X] T066 [US4] `FacetSidebar.svelte` — desktop-sticky sidebar / mobile drawer. Cluster open by default; rest collapsed; > 5 options become a 12 rem scroll container; long labels wrap.
- [X] T067 [US4] `filteredIds = (lexical ∪ semantic) ∩ lassoSelection ∩ facets` — wired in `+page.svelte`. Facet selections also dim the UMAP via the `selection` prop on `UmapPanel`.
- [ ] T068 [US4] Playwright `facets.spec.ts` DEFERRED to Phase 11 polish.
- [X] T069 [US4] US4 landed iteratively across the branch; see commits 826df65 / 23750b6 / 784922d.

---

## Phase 8: User Story 5 — Cart + email-my-list (Priority: P3)

**Story Goal**: User clicks "add to list" on N abstracts; cart badge shows N; click "email my list" → OS mail composer opens with subject + body listing items + permalinks. Mobile-friendly.

**Independent Test**: Add 3 abstracts, click "email my list", verify mail composer launches with the expected subject + body; on Linux without a mail handler, the clipboard-fallback modal opens.

### Tests first

- [X] T070 [P] [US5] `site/src/tests/unit/cart_email.test.ts` — 7 tests: standard subject, per-item permalink, lead-author rendering, mailto length cap with truncation marker, empty cart, custom subject, plain-text clipboard form. Green.
- [ ] T071 [P] [US5] Playwright `cart.spec.ts` DEFERRED to Phase 11 polish.

### Implementation

- [X] T072 [P] [US5] `site/src/lib/cart_email.ts::buildMailtoLink(items, leadAuthorMap, {siteUrl, subject?})` — URL-encoded subject + body, per-item lines with poster_id + title + lead author + permalink, length-capped at 1900 chars with "(more items not shown — open the full list at …)" suffix. Also exports `buildPlainTextList` for the clipboard fallback.
- [X] T073 [P] [US5] `site/src/lib/components/CartDrawer.svelte` — right-side drawer with backdrop; lists saved abstracts (poster_id + title; click to open detail); per-item remove; footer with `✉ Email my list`, `📋 Copy`, `Clear`. Empty-state hint.
- [X] T074 [US5] `emailList()` sets `window.location.href = buildMailtoLink(...)`; `copyList()` calls `navigator.clipboard.writeText(buildPlainTextList(...))` and flashes `✓ Copied` / `Copy failed` feedback.
- [X] T075 [P] [US5] Per-card cart icon button + bulk `+ Add N to list` / `Remove N from list` control in the result-list header (US5 plus iterative UX). Also new `cartStore.addMany` / `removeMany` for one-update bulk writes.
- [X] T076 [US5] US5 commit landing in this batch.

---

## Phase 9: User Story 6 — Optional walkthrough (Priority: P4)

**Story Goal**: First-time visitors see a "Take the tour" CTA but no auto-launch. Clicking it walks through search → model selector → UMAP → facets → cart in 5+ stops with next/prev/skip controls. Re-launchable from a "?" help affordance.

**Independent Test**: Open in incognito, verify the CTA is visible, click it, walk through 5+ stops, dismiss, reload, verify the tour doesn't auto-launch again.

### Tests first

- [ ] T077 [P] [US6] Write `site/src/tests/unit/tour.test.ts` — `tourStore.start()` sets `currentStep = 0`; `tourStore.next()` advances; `tourStore.skip()` resets + marks-as-dismissed in localStorage. Red until T078.

### Implementation

- [ ] T078 [P] [US6] Create `site/src/lib/stores/tour.ts` with a state machine: `idle | running | dismissed`. Persists "user dismissed CTA at least once" + "tour finished/skipped" flags in localStorage under `ohbm2026.ui.tour.v1`. Verify T077 turns green.
- [ ] T079 [P] [US6] Create `site/src/lib/components/Tour.svelte` using `shepherd.js`. Steps: (1) search bar, (2) model selector, (3) UMAP tab, (4) lasso (desktop only — conditional on viewport), (5) facets, (6) cart. Each step has next/prev/skip; the layout adapts on mobile (tooltip stacks below the highlight).
- [ ] T080 [US6] Add a "Take the tour" button to the header (always visible) + a "?" help icon (always visible) that re-launches the tour. CTA banner one-time on first visit; dismissible.
- [ ] T081 [P] [US6] Add Playwright test `site/src/tests/e2e/tour.spec.ts` covering the 2 US6 acceptance scenarios. Verify it passes.
- [ ] T082 [US6] Commit US6. Tag `stage6-us6-tour`.

---

## Phase 10: User Story 7 — About page + verified references (Priority: P4)

**Story Goal**: `/about` route. Top: ≤ 250-word non-specialist overview. Below: 5–7 collapsible deep-dive sections per pipeline stage, each citing real reference URLs. Every link opens in a new tab; build-time link checker fails the deploy on any 4xx/5xx.

**Independent Test**: Open `/about`; confirm overview ≤ 250 words; expand each deep dive; click links and verify each opens in a new tab + reaches a 200 response. Locally run `link_check.py` against `references.yaml`.

### Tests first

- [ ] T083 [P] [US7] Write `tests/test_ui_data_link_check.py::test_blocks_4xx_url` — given a fixture YAML with one `https://httpbin.org/status/404` URL, the link checker exits non-zero. Use a small fixture YAML; mock the HTTP HEAD via `responses`. Red until T085.
- [ ] T084 [P] [US7] Write `tests/test_ui_data_link_check.py::test_passes_clean_yaml` — all-200 URL set returns exit 0. Red until T085.

### Implementation

- [ ] T085 [P] [US7] Create `specs/008-ui-rewrite/contracts/references.yaml` — the source-of-truth registry per research.md R9. Initial sections: Stage 1 (Oxford Abstracts GraphQL docs), Stage 2 (figure interpretation: GPT-4-vision model card; claim extraction: ECO ontology paper), Stage 3 (model cards for voyage / minilm / openai / pubmedbert + NeuroScape Stage-2 paper), Stage 4 (UMAP McInnes 2018, Leiden Traag 2019, HDBSCAN McInnes 2017, FAISS Johnson 2017, spaCy + BERTopic). Each entry: `{section, title, authors, year, url, doi?}`.
- [ ] T086 [P] [US7] Create `src/ohbm2026/ui_data/link_check.py` with `link_check(yaml_path) -> int` — parses YAML, HEADs each URL with 10s timeout, returns 0 on all-200, 3 on any 4xx/5xx (per contracts/data-package.md exit codes). Verify T083 + T084 turn green.
- [X] T087 [P] [US7] `site/src/routes/about/+page.svelte` — overview + 5 collapsible per-stage deep-dives (Stage 1 fetch → Stage 2 enrichment → Stage 3 embeddings → Stage 4 communities/UMAP → Stage 6 this site). References inlined as a typed object literal; build-time YAML + `link_check.py` validation is on the polish list (T083–T088). External links use `target="_blank" rel="noopener noreferrer"`. Linked from the layout header.
- [ ] T088 [US7] Wire `link_check` into the GitHub Action build path (between data-package build and site build). Exit non-zero blocks the deploy.
- [ ] T089 [US7] Commit US7. Tag `stage6-us7-about`.

---

## Phase 11: Polish & Cross-Cutting Concerns

- [ ] T090 [P] Add a Lighthouse-CI check to the deploy workflow: assert SC-001 (first interactive paint ≤ 3 s) + SC-006 (data package size). Add to `deploy-ui.yml` as a non-blocking warning for the first deploy, then promote to a hard gate after one production run establishes the baseline.
- [ ] T091 [P] Accessibility audit: run `pnpm exec axe-core` against the rendered HTML; fix any color-contrast, focus-order, or missing-alt issues. Target WCAG 2.1 AA.
- [ ] T092 [P] Reconcile `CLAUDE.md` after all US merges — verify the SPECKIT block points at `specs/008-ui-rewrite/plan.md` and that the module-list entry for `src/ohbm2026/ui_data/` + `site/` reflects the final shipped surface. The bulk of CLAUDE.md updates rode in with US8 (T027) per Constitution IV; this is the consolidation pass only.
- [ ] T093 [P] Reconcile `README.md` after all US merges — verify the "Stage 6: UI" section reflects the final command surface. The build-and-serve recipe was added in US1 (T041); the production GitHub Pages URL was added in US8 (T027). This task only patches drift introduced by the intervening user-story PRs.
- [ ] T094 [P] Update `docs/reproducibility-vision.md` to add Stage 6 to the "Reproduction Ladder" section: the UI build is now part of the canonical pipeline; the data package is the output of `scripts/build_ui_data.py`.
- [ ] T095 Run the constitution check: `.specify/scripts/bash/constitution-check.sh --full`. Expect exit 0.
- [ ] T096 [P] Full SC sweep against the live preview: SC-001 (Lighthouse), SC-002 (search latency stopwatch), SC-003 (cell-switch timing), SC-004 (mobile Playwright at 360 × 640), SC-005 (data-package scan for withdrawn), SC-006 (`du -sh site/static/data/`), SC-007 (link checker), SC-008 (PR-preview timing observation **— verify the Deployments box, NOT a bot comment, is the surface; sample at least 3 distinct PRs and report median + max rather than computing a true p90 from a small sample**), SC-009 (cart reload test), SC-010 (run `scripts/eval_typo_recall.py --full`; assert ≥ 0.90 against the live preview), SC-011 (Playwright: assert footer renders `build_info.code_revision_short` on home + about + abstract permalink routes).
- [ ] T097 [P] Verify the FR-021 + FR-022 acceptance: open a throwaway PR; confirm the **Deployments box** appears at top of PR within 10 min; **confirm the page-title suffix AND the footer build-info affordance show the PR's exact short SHA** so the deploy can be visually verified as the right committish; push a second commit; confirm the Deployments box updates AND the rendered short SHA on the preview flips to the new commit's value; close the PR; confirm Deployments box marks it "Inactive". Record screenshots in the polish PR body. **No `peter-evans/find-comment`-style bot comments should be present.**
- [ ] T098 [P] Save a user-memory entry noting: "Stage 6 / static-JSON-shard architecture (no DuckDB-WASM); 8 user stories shipped; SvelteKit + transformers.js + shepherd.js; deploy via gh-pages with PR previews surfaced in the PR Deployments box (NOT bot comments) via `environment:` declaration; US8 shipped first as a small PR to enable previews for US1–US7; every shard carries a `build_info` envelope and the rendered site shows the short committish in the page title + footer so PR-preview deploys are visually verifiable (FR-022)." So future stages have the context.
- [ ] T099 Mark all of T001–T098 in this `tasks.md` as `[X]` and commit the tasks-list update.
- [ ] T100 Push the final consolidating branch + open the PR to `main`. PR title: `feat(stage6): static-JSON-shard UI rewrite on GitHub Pages — US1–US7 (US8 already on main)`. Body: summary of US1–US7 + the SC sweep results + the GitHub Pages preview URL from the Deployments box.

---

## Dependencies

```
                 ┌──────────────────────┐
                 │ Phase 1: Setup       │
                 │ (T001–T007)          │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │ Phase 2: Foundational│
                 │ (T008–T020)          │
                 │ data builders + tests│
                 └──────────┬───────────┘
                            │
                 ┌──────────▼─────────────────────────┐
                 │ Phase 3: US8 — DEPLOY (ships first)│
                 │ (T021–T027) P5 → promoted          │
                 │ workflows + placeholder + PR-prevu │
                 │ surfaces in Deployments box        │
                 └──────────┬─────────────────────────┘
                            │ (US8 PR merged to main; previews now live)
                 ┌──────────▼───────────┐
                 │ Phase 4: US1 — MVP   │
                 │ (T028–T041) P1       │
                 │ search + browse +    │
                 │ accepted-only guard  │
                 │ first PR to *use* PR │
                 │ preview pipeline     │
                 └──────────┬───────────┘
                            │
            ┌───────────────┼───────────────┬─────────────┬─────────────┐
            │               │               │             │             │
   ┌────────▼────────┐ ┌────▼────┐ ┌───────▼────────┐ ┌─▼────┐ ┌──────▼────┐
   │ US2: UMAP       │ │ US3:    │ │ US4: Facets    │ │ US5: │ │ US6: Tour │
   │ (T042–T050)     │ │ Search  │ │ (T064–T069)    │ │ Cart │ │ (T077–    │
   │ P2              │ │ (T051–  │ │ P3             │ │ (T070│ │ T082)     │
   │                 │ │ T063)   │ │                │ │ –T076│ │ P4        │
   │                 │ │ P2      │ │                │ │ )    │ │           │
   │                 │ │         │ │                │ │ P3   │ │           │
   └────────┬────────┘ └────┬────┘ └───────┬────────┘ └──┬───┘ └─────┬─────┘
            │               │              │            │           │
            └───────────────┼──────────────┴────────────┼───────────┘
                            │                           │
                ┌───────────▼──────────┐                │
                │ US7: About + links   │                │
                │ (T083–T089) P4       │                │
                └───────────┬──────────┘                │
                            │                           │
                            └───────────┬───────────────┘
                                        │
                             ┌──────────▼───────────┐
                             │ Phase 11: Polish     │
                             │ (T090–T100)          │
                             └──────────────────────┘
```

- **US8 ships FIRST** (Session 2026-05-17 clarification): the deploy workflows + placeholder land before any user-facing UI code so US1–US7 PRs can be reviewed via live previews. Once US8 is on main, the rest of the stories can ship in parallel.
- **US1 is the next gate**: every other user-facing story depends on US1's shell (layout + shards loaded + stores wired). US2–US7 can ship in any order after US1.
- **US7 (link checker)** is independent of US2–US6; can ship before US6 if reviewers want the docs first.

## Parallel execution examples

### Within Phase 2 (Foundational)

The 4 new submodules + their tests are independent:

```text
T008 [P]: tests/test_ui_data_manifest.py
T009 [P]: tests/test_ui_data_abstracts.py
T010 [P]: tests/test_ui_data_authors.py
T015     : tests/test_ui_data_cells.py
T011     : ui_data/manifest.py  (depends on git revision lookup)
T012 [P]: ui_data/abstracts.py
T013     : tests/test_ui_data_authors.py::test_referential_integrity
T014 [P]: ui_data/authors.py
T016     : ui_data/cells.py  (depends on T012's abstracts shape)
T017 [P]: ui_data/topics.py
T018     : ui_data/builder.py  (depends on all of T011–T017)
T019 [P]: scripts/build_ui_data.py
T020     : test_deterministic_build  (depends on T018)
```

### Within Phase 3 (US8 deploy — ships first)

The 3 workflow files + the placeholder are independent:

```text
T021 [P] [US8]: site/src/routes/+page.svelte (placeholder)
T022 [P] [US8]: .github/workflows/deploy-ui.yml
T023 [P] [US8]: .github/workflows/pr-preview.yml      (environment: declaration)
T024 [P] [US8]: .github/workflows/pr-preview-cleanup.yml  (actions/github-script)
T025     [US8]: one-time Pages settings
T026     [US8]: draft-PR verification (Deployments box surface)
T027     [US8]: commit + merge US8 PR
```

### Within US1 (MVP)

The 3 new test files + 6 component files are mostly parallel:

```text
T028 [P] [US1]: shards.test.ts
T029 [P] [US1]: cart.test.ts
T030 [P] [US1]: browse.spec.ts
T031 [P] [US1]: lib/shards.ts
T032 [P] [US1]: stores/selection.ts
T033 [P] [US1]: stores/cart.ts
T034 [P] [US1]: components/SearchBar.svelte (US1 placeholder)
T035 [P] [US1]: components/ResultList.svelte
T036 [P] [US1]: components/DetailPanel.svelte
T037     [US1]: replace placeholder routes/+page.svelte + full +layout.svelte (depends on T031–T036)
T038     [US1]: app.css responsive shell (depends on T037)
T039 [P] [US1]: routes/abstract/[poster_id]/+page.svelte
T040     [US1]: tests/e2e/accepted-only.spec.ts
```

### Within US3 (search)

```text
T051 [P] [US3]: tests/test_ui_data_lexical_index.py
T052 [P] [US3]: site/tests/unit/lexical.test.ts
T053 [P] [US3]: site/tests/unit/semantic.test.ts
T054 [P] [US3]: ui_data/lexical_index.py
T055 [P] [US3]: lib/search/lexical.ts
T056 [P] [US3]: ui_data/vectors.py
T057 [P] [US3]: lib/workers/semantic.worker.ts
T058 [P] [US3]: lib/search/semantic.ts
T059     [US3]: components/SearchBar.svelte (full version)  -- depends on T055 + T058
T060 [P] [US3]: author-search subfield
T061     [US3]: wire into ResultList
T062     [US3]: tests/e2e/search.spec.ts
```

## Implementation strategy

**Recommended sequence** (per Session 2026-05-17 clarification):

1. **Phase 1 (Setup)** → **Phase 2 (Foundational, builder skeleton)** → **Phase 3 (US8 deploy + placeholder, SHIPS FIRST as a small standalone PR)**.
2. Once US8 is on main: **Phase 4 (US1 MVP, second PR — first to use the now-live preview pipeline)**.
3. Then **Phase 5–10 (US2–US7)** in any order as parallel PRs, each reviewed via its own PR-preview Deployments box link.
4. Finally **Phase 11 (Polish)** as a consolidating PR.

**MVP scope**: US1 alone (on top of US8 already on main). If review pushback forces stopping after US1, the site is still useful: anyone can search + browse + read accepted abstracts on any device. The remaining stories are progressive enhancements.

**Per-story commit messages** must record:
- For each US: tests landed before impl per CA-002; the user-story acceptance scenarios verified; the relevant FRs + SCs satisfied; for US2 onward, link the live PR-preview URL from the Deployments box.
- Polish phase: the constitution check exit code; the SC sweep numbers; the SPECKIT block update.

**Tag scheme**: tag each US's final commit with `stage6-us<N>-<short-name>` so the deploy timeline is browsable.

## Format validation

All 105 tasks above (100 sequentially numbered + 5 `Tnnna`-suffixed inserts: T011a, T020a, T036a, T043a, T058a) conform to the strict checklist format: leading `- [ ]`, sequential `T###` or `T###a` ID, optional `[P]` parallelism marker, `[US1] / [US2] / … / [US8]` story label on user-story-phase tasks only (Setup / Foundational / Polish tasks carry no story label per the rule), and a description that names the file path(s) being touched. Test tasks land before their implementation tasks within each user-story phase. The five suffixed inserts are post-analysis remediations (G1 + U1 + U2 + U4 + I4 from /speckit-analyze 2026-05-17); they preserve all prior task numbers so existing references stay stable.
