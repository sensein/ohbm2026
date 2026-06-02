# Phase 0 Research: Cart-only + selection intersection + lasso highlight

All findings are grounded in the current `site/` code (cited as `file:line`). Decisions resolve the spec's deferred thresholds and the technical unknowns the plan named.

## R-001 — Selection highlight: fix 2D zoom-contrast (keep `selectedpoints`) + add 3D via in-place restyle

> **Updated by the 2026-06-01 clarification.** The earlier draft proposed dropping `selectedpoints` and rewiring 2D to a per-point opacity array. The user clarified that the 2D highlight **already works** — it only washes out at zoom — and chose a minimal opacity-gap fix for 2D plus a separate 3D addition. This section reflects that scope.

**Context** (verified in code):
- 2D atlas/neuroscape highlight uses Plotly's native selection styling: `selected.marker.opacity: 1`, `unselected.marker.opacity: …`, plus `selectedpoints: [indices]` on the trace (`UmapPanel.svelte` ~1457–1461, 1532–1536). It renders correctly. The wash-out comes from `applyAtlasZoomOpacity` (`UmapPanel.svelte:1132–1167`), which on every zoom **deliberately sets `unselected.marker.opacity` EQUAL to the base `marker.opacity`** (lines 1155–1159, with the comment "keeping it equal … means lassoing never dims the surrounding cloud into invisibility"). `densityZoomOpacity` raises that base toward ~1.0 as you zoom in (fewer points on screen ⇒ brighter cloud), so the unselected cloud climbs to match the selected points' 1.0 and the selection stops standing out.
- 3D **intentionally ignores the selection**: both 3D trace builders are called with an empty set (`UmapPanel.svelte` ~1945, 1953) because `scatter3d` ignores `selectedpoints` and a selected/unselected dual-trace split would need `Plotly.react` per change, leaking WebGL contexts (~620 MB/cycle, plotly.js#6365). The 3D-focus fix (commit `dba3d7cf`) introduced a **cheap in-place restyle** for the single-point focus halo (`applyFocus3dHalo`, ~1869–1914) — `Plotly.restyle` of persistent traces, no `react`, no trace-count change.

**Decision**:
- **2D — keep the existing `selectedpoints` mechanism**; change only the unselected-opacity coupling. When a selection is active (`lassoOhbmSet`/`lassoNeuroSet`/search set non-empty), cap the **unselected** opacity below the **selected** opacity so a minimum contrast gap survives at all zoom levels: `unselectedOpacity = selectionActive ? min(base, base * (1 - GAP)) : base` (or an absolute ceiling such as `min(base, CAP)`), while `selected.marker.opacity` stays 1.0. When no selection is active, retain today's behavior (`unselected == base`) so an un-lassoed cloud still reads at zoom. The gap factor lives in `atlas/opacity.ts` as a pure, unit-tested helper.
- **3D — add the highlight via an in-place restyle** of a precomputed per-point `marker.opacity` (or `marker.color` rgba) array on the existing 3D backdrop/overlay traces — the same cheap-restyle pattern as the focus halo. Selected → 1.0; unselected → current density-dim. **No `Plotly.react`, no trace-count change.**

**Rationale**:
- 2D is the smallest correct change: the highlight already works, so we don't risk a rewire; we only decouple unselected opacity from the base when a selection is active, which is exactly the reported defect.
- 3D reuses a proven leak-free pattern (the focus-halo restyle), so it can finally reflect the selection without the `react` leak that motivated disabling it.
- Both are pure data updates: O(points) array build (≤461k 2D / ≤50k 3D) + restyle; no network.

**Alternatives rejected**:
- *Full per-point-opacity-array rewire of 2D* (the earlier R-001 draft): unnecessary given the working `selectedpoints` path; more change/risk than the contrast bug warrants. Rejected per the clarification.
- *Add a size/outline/colour emphasis channel for selected points*: the user chose opacity-gap-only for now; emphasis channel deferred.
- *`Plotly.react` dual traces in 3D*: the leaking path (plotly.js#6365).

**Verification spike (3D only) — RESOLVED by code inspection (T025 follow-up):**
`scatter3d` **silently ignores a per-point `marker.opacity` array** — it only
honors a SCALAR opacity (confirmed at `UmapPanel.svelte:2123`, where the OHBM
3D path works around this by splitting into selected/unselected dual traces,
each with a scalar opacity). That dual-trace split is exactly what triggers a
`Plotly.react` per selection change → the WebGL-context leak the atlas/
neuroscape 3D path was built to avoid (hence it passes empty sets today).

⇒ The leak-free 3D highlight for atlas/neuroscape MUST use the H7 fallback: a
per-point **`marker.color` rgba array** (alpha baked in) applied via in-place
`Plotly.restyle` — `marker.color` is already a per-point array there (points
are coloured by cluster), so dimming the unselected entries' alpha and
restyling that one array reflects the selection with no trace rebuild and no
`react`. This is the concrete path for T025 (still pending implementation).

## R-002 — Where the intersection composition lives (two data paths)

**Context**: OHBM and atlas/neuroscape compose filters in different places.
- OHBM: `+page.svelte:434` — `filteredIds = $cartOnly ? cartIds : intersect(intersect(intersect(effectiveSearchIds, $lassoSelection), facetIds), authorChipIds)`. `cartOnly` is a **dominant override**; facet counts use `preFilterForFacetCounts` (`:437`).
- Atlas/neuroscape: `+page.svelte:738–747` — `filteredBackdrop = anyLassoActive ? listFacetFiltered.filter(in lasso) : listFacetFiltered`. Search is applied **inside** the browse panels (`NeuroscapeBrowsePanel`/`AtlasRootBrowsePanel` receive `articles={filteredBackdrop}` + `query` + `semanticHits`, `+page.svelte:2177–2214`).

**Decision**:
- **OHBM**: make `cartOnly` an intersecting term. Replace the `:434` ternary with `intersect(…, cartIds)` where `cartIds = $cartOnly ? <cart poster_ids ∩ corpus> : null` (null = identity in `intersect`). Add `cartIds` to `preFilterForFacetCounts` (`:437`) so facet counts also respect Cart-only. Rewrite the `:427–433` comment block (it documents the old dominant behavior).
- **Atlas/neuroscape**: when Cart-only is on, narrow `filteredBackdrop` (and `filteredOverlay`) by cart membership *before* it reaches the panel. The panel then runs search within that set ⇒ list = `facet ∩ lasso ∩ cart ∩ search`. Extract the id-set intersection into a pure `site/src/lib/selection/compose.ts` so both paths share one tested implementation.

**Rationale**: Narrowing the array fed to the panel reuses the panel's existing search/rank/semantic-merge untouched, and keeps the intersection in one pure function. Matches the user's "similar to selecting a faceted filter" framing.

**Alternatives rejected**: threading a `cartOnly` flag into each panel and filtering internally (duplicates the membership logic in two components, harder to unit-test).

## R-003 — Single source of truth for the search-matched set (scatter highlight)

**Context**: FR-007 needs search matches **highlighted on the scatter** for atlas/neuroscape, but the matched set is computed inside the panel (`filtered`, `NeuroscapeBrowsePanel.svelte:70`). The scatter (`UmapPanel`) currently only receives lasso sets (`+page.svelte:2070–2071`).

**Decision**: Have the browse panel **expose its final matched-id set** to the route (Svelte `bind:matchedIds` or a `dispatch('results', ids)`). The route intersects it with the lasso/cart/facet sets to form the **highlight set** fed to `UmapPanel` (via the per-point opacity array of R-001). One computation drives both the list and the scatter — no divergence.

**Rationale**: Recomputing search in the route would duplicate the panel's lexical+semantic merge and risk list/scatter mismatch. The panel already has the authoritative `filtered`.

**Alternatives rejected**: route recomputes search from `titleSearchIndex` + `semanticHits` (divergence risk, double work on 461k).

## R-004 — Cross-site "hidden saved items" definition (CA-007)

**Context**: The cart is cross-site (`cart.ts`: `kind: 'ohbm2026' | 'neuroscape'`, with `cartOhbmPosterIds` / `cartNeuroPubmedIds` derived views). The warning must say how many saved items are not shown here.

**Decision**: Define **hidden = saved items not present in the current site's loaded corpus index** — discovered at runtime, not from a hardcoded kind→site table:
- ohbm2026 → index = `abstractsByPosterId` (poster_id).
- neuroscape → index = `listCorpusById` (pubmed_id, the full 461k).
- atlas-root → present if in `atlasOverlayById` (ohbm) **or** `listCorpusById`/backdrop (neuroscape); both kinds displayable ⇒ usually 0 hidden ⇒ no warning.
A saved item whose `kind` is unrecognized (future third corpus) is counted and named generically ("from other collections"), never silently dropped.

**Rationale**: Robust to a future third site and to stale/withdrawn ids (an ohbm item removed from the corpus is correctly "not available here"). Satisfies VII.

## R-005 — Lasso resource budget / responsiveness (pins FR-011 / FR-012 / SC-005)

**Decision / concrete thresholds**:
- **Network**: no new fetch beyond the existing one-time `coords` per-table range fetch on atlas-root (`ensureAtlasFullCoords`, `+page.svelte:1052`, ~11 MB) used for *id resolution*. Highlighting adds **zero** network. No whole-envelope parquet download (constitution).
- **Compute**: id resolution is the existing `selectIdsInGeometry` bbox-reject + ray-cast (`lasso_select.ts:82`), "a few ms even at 461k". The new opacity-array build is O(rendered points) ≤ 461k (2D) / ≤ 50k (3D, `MAX_3D_BACKDROP_POINTS`).
- **Render**: exactly one `Plotly.restyle` per selection change; **no `Plotly.react`** (invariant, asserted in e2e via a trace-count/render probe). "Responsive" = no multi-second freeze; target highlight applied < ~150 ms after the lasso resolves on a representative desktop session (SC-005).
- **3D cap**: unchanged 50k budget; selection over the full corpus still resolves the *list* via full coords, while the 3D *highlight* applies to the rendered ≤50k sample (documented; the list remains complete).

## R-006 — Mobile / disabled affordance (FR-012 / FR-013)

**Context**: 2D dragmode is already `'pan'` on mobile for OHBM (`UmapPanel.svelte:767`); atlas/neuroscape 2D forces `'lasso'` (`:1683`).

**Decision**: On mobile (the existing `isMobile` / 1024px breakpoint the panel already uses), lasso is disabled (pan), and the UI shows a short "lasso available on larger screens" note rather than a dead control — no partial selection. The Cart-only toggle and its warning remain available and legible at small widths (they're list-level, not Plotly-level).

## Cross-cutting: docs & tests to touch (IV)

- Docs: README UI section (Cart-only rename + cross-site warning + intersection semantics), `memory/search_unification.md`, `memory/stage15_atlas_subsites.md`, `memory/stage19_semantic_search.md`.
- Tests updated for the behavior change: any existing assertion of OHBM "cart dominant" override is updated to intersection (named in /tasks); `cart.spec.ts`, `umap.spec.ts`, `atlas_root.spec.ts`, `search.spec.ts` must stay green.
