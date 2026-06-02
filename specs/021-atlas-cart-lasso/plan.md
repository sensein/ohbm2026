# Implementation Plan: Cart-only filter, search selection & lasso parity on atlas-root + neuroscape

**Branch**: `021-atlas-cart-lasso` | **Date**: 2026-06-01 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/021-atlas-cart-lasso/spec.md` (incl. Clarifications 2026-06-01)

## Summary

Bring the OHBM-2026 selection workflow to the atlas-root (`/`) and neuroscape (`/neuroscape/`) sibling builds, and unify filter-composition semantics across all three:

1. **Rename** "Saved only" → **"Cart only"** everywhere and add it to atlas-root + neuroscape (it exists only on the OHBM home today).
2. **Switch composition from "cart dominant" to a true intersection**: the visible/highlighted set is `search ∩ lasso ∩ facets ∩ cart-only`. Inactive filters contribute no constraint. This changes the OHBM home behavior (cart was a dominant override) so all three sites behave identically.
3. **Cross-site warning**: when "Cart only" is active and some saved items are not present in the current site's loaded corpus, show a facet-style inline notice with the hidden-item count. "Hidden" is computed by membership in the loaded corpus index (runtime discovery), not a hardcoded kind→site table.
4. **Selection highlight (per the 2026-06-01 clarification)** — two distinct, scoped changes, NOT a full rewire:
   - **2D**: keep the existing Plotly `selectedpoints` + `selected`/`unselected` mechanism. The only 2D defect is a zoom wash-out: `applyAtlasZoomOpacity` (`UmapPanel.svelte:1155-1159`) sets `unselected.marker.opacity` **equal to** the base opacity, which `densityZoomOpacity` raises toward ~1.0 on zoom-in, so selected (1.0) and unselected converge. Fix = when a selection is active, cap unselected opacity below selected so a contrast gap survives zoom.
   - **3D**: today the 3D path passes empty selection sets to its trace builders (`UmapPanel.svelte:1945,1953`) because `scatter3d` ignores `selectedpoints` and a `Plotly.react` dual-trace rebuild leaks WebGL contexts. Add a 3D highlight via an **in-place restyle** (the cheap-restyle pattern the 3D-focus fix `dba3d7cf` proved) — no `Plotly.react`, no trace-count change.

This is a **UI-only** change in `site/` (SvelteKit + TypeScript). No data-package rebuild, no Python, no new parquet, no new credentials. Lasso id-resolution already runs against full corpus geometry via the existing per-table `coords` range fetch (~11 MB once on atlas-root); this feature adds no new network cost.

## Technical Context

**Language/Version**: TypeScript 5.7, Svelte 5.16, SvelteKit 2.21 (static adapter)
**Primary Dependencies**: Plotly (scattergl 2D / scatter3d 3D, via the `UmapPanel` wrapper), hyparquet (range-fetch decoder — unchanged), Vite 6
**Storage**: Browser `localStorage` for the cross-site cart (`ohbm2026.ui.cart.v2`, unchanged). No server/DB.
**Testing**: Vitest (jsdom) units — run with `vitest run` (never watch); Playwright e2e (`pnpm test:e2e`). No Python in scope.
**Target Platform**: Static site on gh-pages, three build modes via `VITE_SITE_MODE` (`ohbm2026`/`neuroscape`/`atlas-root`); desktop + mobile browsers.
**Project Type**: Web frontend (single SvelteKit project, built three times).
**Performance Goals**: Selection highlight applied via in-place `Plotly.restyle` only (no `react`) so it stays at interactive frame rates; "Cart only" toggle + cart mutation re-filter < 1 s on the 461k neuroscape corpus (SC-003); 3D scatter stays within `MAX_3D_BACKDROP_POINTS = 50_000` (`lod3d.ts`).
**Constraints**: No whole-envelope parquet download (per-table range fetch only — constitution); **no `Plotly.react` on selection change** (WebGL-context leak, plotly.js#6365); byte-identical `/ohbm2026` *data package* (no rebuild) — the OHBM *UI bundle* changes intentionally (rename + cart-intersection).
**Scale/Scope**: 3 build modes; ~461k neuroscape list corpus / ≤50k rendered 3D points; ~3.2k OHBM overlay points; one shared cart.

## Constitution Check

*GATE: must pass before Phase 0; re-checked after Phase 1.*

- **I. Venv-only Python** — No Python in this feature; site tooling is pnpm/Vitest/Playwright. ✅
- **IV. Plan-first, test-first** — Verification named before code (see "Verification strategy"); new Vitest units (intersection composer, hidden-cart-count, 2D opacity-gap math) and Playwright e2e (Cart-only parity + warning, zoom-contrast highlight, 3D highlight, search highlight) written failing first. ✅
- **II. Immutable evidence / no committed data** — No new datasets/caches/exports/roots; localStorage only. ✅
- **VI. Fail loudly** — Empty intersection → explicit empty state (distinct "cart empty" vs "none in this site"); unknown cart `kind` → counted + named (not dropped); cross-parquet drift banner preserved; the existing lasso coord-fetch already degrades with a visible `console.warn` + user note (kept). No bare catches added. ✅
- **VII. Discover external state** — "Hidden saved items" computed by membership in the loaded corpus index, not a hardcoded site→kind table; unknown kind named generically. ✅
- **VIII. Provenance** — No organizer-facing artifact, no rebuild. N/A. ✅
- **V. Secrets / commit hygiene** — No credentials; small verified commits; push when complete. ✅
- **Docs sync (IV)** — README UI section, `memory/search_unification.md`, `memory/stage15_atlas_subsites.md`, `memory/stage19_semantic_search.md`, and this spec's docs updated in the same change (rename + cart-dominant→intersection are user-facing defaults). ✅

**Result**: PASS — no violations; Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/021-atlas-cart-lasso/
├── plan.md              # This file
├── research.md          # Phase 0 — composition, highlight (2D contrast + 3D), warning, budget
├── data-model.md        # Phase 1 — client-side selection/filter state
├── quickstart.md        # Phase 1 — run/verify the three stories per mode
├── contracts/
│   ├── selection-composition.md
│   ├── cart-only-filter.md
│   └── selection-highlight.md
├── checklists/requirements.md
└── tasks.md             # Phase 2 — /speckit-tasks (NOT created here)
```

### Source Code (repository root) — all under `site/`

```text
site/src/
├── lib/
│   ├── stores/selection.ts        # cartOnly (doc rename "Show only saved" → "Cart only")
│   ├── stores/cart.ts             # cartItems / cartOhbmPosterIds / cartNeuroPubmedIds (read-only here)
│   ├── components/
│   │   ├── UmapPanel.svelte        # 2D: cap unselected opacity below selected when a selection is active
│   │   │                           #     (applyAtlasZoomOpacity ~1155); 3D: add in-place restyle highlight
│   │   │                           #     (renderAtlasChart3D ~1945/1953) — no Plotly.react
│   │   ├── NeuroscapeBrowsePanel.svelte    # expose matched-id set (R-003); render Cart-only warning slot
│   │   ├── AtlasRootBrowsePanel.svelte      # expose matched-id set; render Cart-only warning slot
│   │   ├── NeuroscapeFacets.svelte / AtlasRootFacets.svelte  # host the "Cart only" toggle + warning
│   │   └── ResultList.svelte        # (OHBM) unchanged — already reflects filteredIds
│   ├── atlas/opacity.ts            # densityZoomOpacity / currentZoomFactor2d — source of the wash-out; add selected/unselected gap helper
│   ├── geo/lasso_select.ts         # unchanged (geometry → ids already correct)
│   ├── lod3d.ts                    # unchanged (50k 3D cap reused)
│   └── selection/                  # NEW pure, unit-tested helpers
│       ├── compose.ts              # intersect over id-sets incl. cart membership
│       └── cart_scope.ts           # savedInCorpus(cartItems, indexHas, mode) → shown + hiddenCount
└── routes/+page.svelte             # intersection composition (3 modes); per-mode Cart-only state;
                                    # highlight-set feed to UmapPanel (incl. panel-exposed search matches)
```

```text
site/src/tests/
├── unit/
│   ├── selection_compose.test.ts   # NEW — intersection semantics incl. cart
│   ├── cart_scope.test.ts          # NEW — hidden-count by corpus membership per mode
│   ├── selection_opacity.test.ts   # NEW — selected/unselected opacity gap holds across zoom factors
│   └── (existing) cart.test.ts, lasso_select.test.ts, lod3d.test.ts, atlas_opacity.test.ts, filter.test.ts
└── e2e/
    ├── cart_only_parity.spec.ts    # NEW — Cart only + warning on neuroscape & atlas-root
    ├── selection_highlight.spec.ts # NEW — zoom-contrast (2D) + 3D highlight + search highlight
    └── (existing) cart.spec.ts, umap.spec.ts, atlas_root.spec.ts, search.spec.ts
```

**Structure Decision**: Single SvelteKit project (`site/`), three build modes. Intersection composition and the hidden-cart-count are extracted into pure functions under `site/src/lib/selection/` (jsdom-unit-testable without Plotly). The highlight changes are localized to `UmapPanel.svelte` (+ a small `atlas/opacity.ts` helper for the selected/unselected gap) plus the id-set the route feeds it. The 2D mechanism (`selectedpoints`) is **kept**; only the unselected-opacity coupling changes. `lasso_select.ts` (geometry → ids) is untouched.

## Verification strategy (test-first)

Written/failing before implementation, per story:

- **US1 (Cart only + intersection + warning)**:
  - `selection_compose.test.ts` — `compose()` returns the intersection of any subset of {search, lasso, facets, cart}; absent filter = identity; cart-only off ⇒ no cart constraint (encodes the OHBM behavior change).
  - `cart_scope.test.ts` — `savedInCorpus` counts saved items not in the loaded corpus index, per mode (ohbm hides neuroscape items; neuroscape hides ohbm items; atlas-root hides neither when both indexes present; unknown kind counted + named).
  - e2e `cart_only_parity.spec.ts` — Cart only on `/neuroscape/` with a mixed cart → only neuroscape saved items, warning with hidden count; empty-state variants; OHBM control reads "Cart only".
- **US2 (search highlight + bulk add)**:
  - Unit — the panel exposes its matched-id set (binding/event); asserted against a fixture corpus.
  - e2e — query on `/neuroscape/` highlights matching scatter points; existing bulk "Add N to cart" continues to add exactly the matched set.
- **US3 (highlight visibility)**:
  - `selection_opacity.test.ts` — the unselected-opacity cap keeps a minimum gap below the selected opacity (1.0) across the full range of `densityZoomOpacity` / zoom factors (pure function; no Plotly).
  - e2e `selection_highlight.spec.ts` — draw a lasso in 2D, zoom in → enclosed points remain visibly distinct (assert computed unselected opacity stays below a ceiling while selected stays 1.0); switch to 3D → selection reflected; a render/trace-count probe confirms **no `Plotly.react`** fired on selection change; mobile → lasso disabled with a note.

Existing suites stay green; any test asserting the OHBM cart-dominant override is updated to the intersection (named in /tasks).

## Phase 0 — Research

See [research.md](./research.md): (R-001) 2D zoom-contrast fix (cap unselected opacity) + 3D highlight via in-place restyle; (R-002) intersection placement across the OHBM vs atlas/neuroscape data paths; (R-003) single source of truth for the search-matched set feeding list + scatter; (R-004) cross-site "hidden" via corpus-index membership; (R-005) lasso resource budget / responsiveness (pins FR-011/FR-012/SC-005); (R-006) mobile/disabled affordance.

## Phase 1 — Design & Contracts

- [data-model.md](./data-model.md) — client-side selection/filter state and visibility rules.
- [contracts/selection-composition.md](./contracts/selection-composition.md) — intersection contract.
- [contracts/cart-only-filter.md](./contracts/cart-only-filter.md) — toggle, warning, empty states, hidden-count rule.
- [contracts/selection-highlight.md](./contracts/selection-highlight.md) — 2D contrast-gap rule (keep `selectedpoints`) + 3D in-place-restyle rule + no-`react` invariant + budget.
- [quickstart.md](./quickstart.md) — local dev + verification per mode.

Post-design Constitution re-check: unchanged — PASS (UI-only, no data, loud errors, runtime-discovered scope, no provenance surface).
