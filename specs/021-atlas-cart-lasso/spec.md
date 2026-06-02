# Feature Specification: Cart-only filter, search selection & lasso parity on atlas-root + neuroscape

**Feature Branch**: `021-atlas-cart-lasso`
**Created**: 2026-06-01
**Status**: Draft
**Input**: User description: "now that we have the 3d view fixed, can we bring in some of the features from ohbm into root+neuroscape around search selection or cart (saved only). let's also rename "saved only" to "Cart only" (with a warning for any given site that only items available in the site are shown. this is similar to selecting a faceted filter in any of the sites. if possible it would be nice to see the lasso selection as well on root+neuroscape if that can now be done without significant resource consumption"

## Overview

The three sibling sites (`/ohbm2026/`, atlas-root `/`, and `/neuroscape/`) share one cross-site cart, but the *interaction* features built up around that cart on the OHBM 2026 home page have never been carried over to atlas-root or neuroscape. Specifically:

- The **"Saved only"** result filter exists only on the OHBM 2026 home page; the other two sites offer no way to narrow the visible corpus down to just the saved (cart) items.
- **Lasso/search highlight loses contrast at zoom (2D) and is absent in 3D.** On atlas-root/neuroscape the 2D lasso highlight is present but gets washed out when zoomed in — the zoom-opacity model brightens the *unselected* cloud until it matches the selected points, so the selection stops standing out. Separately, the 3D scatter does not reflect the lasso/search selection at all. Both need addressing now that the 3D view has been fixed.
- The selection filters (search, lasso, facets, and "Cart only") need a single, consistent composition rule. The intended behavior is an **intersection**: the visible/highlighted set is the set of items that satisfy *every* active filter at once. This matches the user's framing that "Cart only" is "similar to selecting a faceted filter" — it is just one more intersecting constraint, not a dominant override.

This feature fixes the lasso/search highlight visibility, brings the selection workflow (search-driven highlight + lasso) to atlas-root and neuroscape, renames "Saved only" to **"Cart only"** across all three sites with intersection semantics, and adds a clear, facet-style warning when the active site can only show a subset of the saved items.

## Clarifications

### Session 2026-06-01

- Q: On root+neuroscape the lasso highlight IS present but gets washed out when zoomed in — what's the real defect? → A: The zoom-opacity model raises the *unselected* point opacity to match the brightening backdrop as you zoom, so selected (opacity 1.0) and unselected points converge and the selection stops standing out. The 2D highlight mechanism works; it just loses contrast at zoom.
- Q: How should selected points be kept distinct at every zoom level? → A: Opacity-gap only — when a selection is active, cap the unselected opacity below the selected opacity so a contrast gap survives zoom-in. No separate size/outline/colour emphasis channel for now.
- Q: What is the scope for the scatter highlight, including 3D? → A: Fix 2D + add 3D — keep the existing 2D `selectedpoints`-based mechanism and just fix the zoom contrast (no 2D rewire); separately add lasso/search highlight to 3D (which currently ignores it) via a cheap restyle that does not trigger a Plotly trace rebuild.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - "Cart only" filter on every site (Priority: P1)

A user browsing the neuroscape corpus (or atlas-root, or OHBM 2026) has saved several items to their cart while exploring multiple sites. They want to narrow the current view down to just their saved items, the same way they already can on the OHBM 2026 home page. They toggle a control now labeled **"Cart only"**. The result list, facet counts, and visualization all collapse to show only the saved items that exist in the current site. Because the cart is shared across sites, the site shows a short warning that only the saved items available *in this site* are displayed.

**Why this priority**: This is the explicit, highest-value ask — feature parity for the cart filter plus the rename and the cross-site warning. It is independently shippable and immediately useful to anyone curating across sites.

**Independent Test**: With items saved from more than one site, open neuroscape (or atlas-root), toggle "Cart only", and confirm the visible set is exactly the saved items belonging to that site, the warning is shown, and toggling off restores the full view. Verify the OHBM 2026 home page now reads "Cart only" instead of "Saved only" with identical behavior.

**Acceptance Scenarios**:

1. **Given** a cart containing items saved from neuroscape and from OHBM 2026, **When** the user activates "Cart only" on the neuroscape site, **Then** only the neuroscape saved items appear in the result list and visualization, and a warning states that only saved items available in this site are shown.
2. **Given** "Cart only" is active, **When** the user adds or removes an item from the cart, **Then** the filtered view updates immediately to reflect the new cart contents.
3. **Given** the cart contains no items that exist in the current site, **When** the user activates "Cart only", **Then** an empty-state message explains that none of the saved items are available in this site (with the count of saved items that belong to other sites).
4. **Given** "Cart only" is active alongside an active search query and/or facet filters, **Then** the visible set is the intersection of all active constraints (cart membership ∩ search ∩ facets) — "Cart only" behaves as one more facet-like filter, not a dominant override.
5. **Given** the OHBM 2026 home page, **When** the user looks at the former "Saved only" control, **Then** it is labeled "Cart only" and behaves exactly as before (including the new cross-site warning when applicable).

---

### User Story 2 - Search-driven selection on atlas-root + neuroscape (Priority: P2)

A user on atlas-root or neuroscape runs a search. They want the search results to behave the way they do on OHBM 2026: the matching items drive the result list, are visually distinguishable in the scatter/UMAP visualization, and can be added to the cart in bulk so the selection can be carried across sites or refined with "Cart only".

**Why this priority**: Connects search to the selection workflow so the new "Cart only" filter and the cart itself are easy to populate. Valuable but secondary to the filter parity itself; depends on the same shared selection state.

**Independent Test**: On neuroscape, run a query, confirm the result list reflects the matches, the matching points are visually highlighted in the visualization, and a bulk "add results to cart" action adds exactly the matching set to the cart.

**Acceptance Scenarios**:

1. **Given** a search query on atlas-root or neuroscape, **When** results are returned, **Then** the result list and visualization both reflect the matching set consistently (matches highlighted, non-matches de-emphasized).
2. **Given** an active search with results, **When** the user invokes the bulk add-to-cart action, **Then** every currently matching item available in the site is added to the cart.
3. **Given** an active search and an active "Cart only" filter, **Then** the two compose predictably (search narrows within the saved set) without losing either selection.

---

### User Story 3 - Lasso selection on atlas-root + neuroscape (Priority: P3)

A user exploring the scatter/UMAP visualization on atlas-root or neuroscape wants their lasso region (and search matches) to stay **clearly visible** at every zoom level and to be reflected in **3D** as well as 2D, while feeding the result list and being addable to the cart — just as on OHBM 2026. Today the 2D highlight exists but washes out when zoomed in (unselected points brighten until they match the selection), and 3D ignores the selection entirely. This must work without a heavy resource cost (no full-corpus download or page hang) on the large neuroscape backdrop.

**Why this priority**: Explicitly framed as a "nice to have, if it can be done without significant resource consumption." The 2D fix is a small contrast adjustment (the highlight already works); the 3D addition is the more performance-sensitive piece given the ~461k-point neuroscape backdrop and the 3D point-budget cap.

**Independent Test**: On neuroscape, draw a lasso around a cluster of points; confirm the result list narrows to the enclosed items, the selection can be added to the cart, and the interaction completes within the resource budget (no multi-tens-of-MB blocking download, no visible freeze beyond the agreed budget). If the budget cannot be met in a given mode, the lasso control is hidden or disabled with an explanation rather than degrading silently.

**Acceptance Scenarios**:

1. **Given** the scatter visualization on neuroscape or atlas-root, **When** the user draws a lasso and then zooms in, **Then** the enclosed points stay clearly distinct from the surrounding cloud at every zoom level (a contrast gap is preserved — the highlight no longer washes out), and — resolved against the full corpus geometry, not just the decimated/visible sample — they become the active selection that drives the result list.
2. **Given** the 3D scatter on neuroscape or atlas-root, **When** a lasso or search selection is active, **Then** the selected points are visibly highlighted in 3D as well (3D no longer ignores the selection), without a noticeable freeze.
3. **Given** a lasso selection, **When** the user adds it to the cart, **Then** exactly the enclosed items are added.
4. **Given** the resource budget cannot be met for lasso in the current mode/device (e.g., mobile), **Then** the lasso control is unavailable and the UI explains why, with no partial or silently incomplete selection.

---

### Edge Cases

- **Empty cart + "Cart only"**: show an empty state explaining nothing is saved yet, rather than a blank list.
- **Cart holds only other-site items**: "Cart only" shows an empty set for this site plus the count of saved items that live on other sites (the facet-style warning).
- **Lasso over a decimated/3D-capped backdrop**: the enclosed selection must be resolved against the full corpus geometry so the result list is complete even though only a sample is rendered.
- **Composition (intersection)**: "Cart only" + search + facet + lasso active simultaneously — the visible set is their intersection (items satisfying all active filters). An empty intersection must show a clear empty state, not a blank/broken view. Removing one filter must widen the set predictably without losing the others.
- **Mobile / constrained devices**: lasso may be disabled (pan-only); the resource-budget warning and the "Cart only" warning must remain legible at small widths.
- **Cart item that no longer exists in the corpus** (stale/withdrawn): "Cart only" must not crash; missing items are simply not shown and are not counted as "available in this site."
- **Drift between sibling parquets**: existing cross-parquet drift detection must continue to surface a visible error rather than a silently partial selection when "Cart only" or lasso resolves against sibling geometry.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The result-filter control currently labeled "Saved only" MUST be renamed to "Cart only" on the OHBM 2026 home page. Its filtering behavior changes per FR-003 (intersection, not dominant override) and FR-004 (cross-site warning); otherwise the cart-membership filtering is preserved.
- **FR-002**: A "Cart only" result-filter control MUST be available on the atlas-root site and the neuroscape site, narrowing the result list, facet counts, and visualization to cart items available in that site.
- **FR-003**: "Cart only" MUST behave as one more facet-like filter that *intersects* with the other active filters (it is NOT a dominant override). This is a deliberate change from the prior OHBM 2026 behavior where the cart filter overrode search/facets/lasso; the affected docs MUST be updated to reflect the new intersection semantics (see CA-003).
- **FR-004**: When "Cart only" is active on a site whose corpus cannot contain every saved item (because the cart spans sites), the UI MUST display a non-blocking warning stating that only saved items available in this site are shown — framed like an active faceted filter — including the count of saved items that belong to other sites.
- **FR-005**: "Cart only" MUST react live to cart mutations (add/remove/clear) while active, updating the filtered view without a manual refresh.
- **FR-006**: When "Cart only" yields no items for the current site, the UI MUST show an explanatory empty state (distinguishing "cart is empty" from "saved items exist but none are in this site").
- **FR-007**: On atlas-root and neuroscape, search results MUST drive the result list and be visually distinguishable in the scatter/UMAP visualization (matches highlighted, non-matches de-emphasized), consistent with the OHBM 2026 behavior.
- **FR-008**: On atlas-root and neuroscape, the user MUST be able to add the current search-result set (all matching items available in the site) to the cart in a single bulk action.
- **FR-009**: The visible/highlighted set MUST be the **intersection** of every active filter — search ∩ lasso ∩ facets ∩ ("Cart only" cart membership, when active). An inactive filter is treated as "no constraint" (does not narrow the set). The intersection MUST be applied consistently to the result list, the facet counts, and the scatter/UMAP highlight, and the composition rule MUST be documented.
- **FR-009a**: In the **2D** scatter, the selection highlight MUST remain visible at every zoom level: when a selection is active, the unselected-point opacity MUST be capped below the selected-point opacity so a contrast gap is preserved as the backdrop brightens on zoom-in (fixing the current wash-out). The existing 2D highlight mechanism is retained — this is a contrast adjustment, not a rewire. The highlight MUST stay correct as the FR-009 intersection changes.
- **FR-009b**: In the **3D** scatter (atlas-root + neuroscape), a lasso/search selection MUST be visibly highlighted (3D currently ignores it). The 3D highlight MUST be applied without a Plotly trace rebuild / `react` (i.e. via an in-place restyle), so it does not regress 3D responsiveness or leak GPU resources, and it operates within the existing 3D point-budget cap.
- **FR-010**: On atlas-root and neuroscape, the user MUST be able to make a lasso selection on the scatter/UMAP visualization that becomes the active selection, drives the result list, and is addable to the cart — provided the resource budget in FR-011 is met.
- **FR-011**: A lasso selection MUST resolve enclosed points against the full corpus geometry (not only the rendered/decimated sample) while staying within an agreed resource budget: no full-envelope-parquet download (per-table range fetch only), and no interaction that blocks the page beyond the agreed responsiveness threshold.
- **FR-012**: If the resource budget for lasso (FR-011) cannot be met in a given mode or on a given device class, the lasso control MUST be hidden or disabled with a visible explanation; the feature MUST NOT degrade into a partial or silently incomplete selection.
- **FR-013**: All three controls/warnings (Cart only, search highlight/bulk-add, lasso) MUST be reachable and legible at the supported small-screen widths, or be explicitly disabled with explanation where a device cannot support them.
- **FR-014**: Existing cross-parquet drift detection MUST continue to surface a visible error (never a silent partial result) whenever "Cart only" or lasso resolves a selection against sibling-parquet geometry.

### Key Entities *(include if feature involves data)*

- **Cart item**: a saved entry carrying a site/corpus kind (e.g., OHBM 2026 vs neuroscape) and a stable identifier; the basis for "Cart only" filtering and the cross-site warning.
- **Active selection state**: the in-browser set of currently selected/highlighted items, fed by search results and/or lasso, shared with the result list and visualization.
- **Site mode**: the build/runtime mode (ohbm2026 / atlas-root / neuroscape) that determines which corpus and which subset of the cart is displayable, and therefore the content of the cross-site warning.
- **Corpus geometry (coordinates)**: the per-item scatter coordinates against which a lasso resolves enclosed points; range-fetched per table, never as a whole envelope.

### Constitution Alignment *(mandatory)*

- **CA-001**: Any Python touched for this feature (data-package build, validation, link-check scripts) MUST run through the repository-local `.venv/bin/python` or `uv` targeting it. This feature is expected to be UI-only with no parquet rebuild; if a rebuild becomes necessary it MUST use the venv interpreter.
- **CA-002**: Each behavior-changing story MUST add or update tests before implementation: site unit tests (run with `vitest run`, never watch mode) for the selection/filter/store logic, and end-to-end tests for the per-mode "Cart only", search-selection, and lasso flows.
- **CA-003**: Renaming "Saved only" → "Cart only" and extending it cross-site is a user-facing/default change; the same change MUST update the affected docs (the spec 015 / 019 plans or their successors, README UI notes, and the relevant `memory/` entries describing search/cart/lasso behavior).
- **CA-004**: This feature introduces no new credentials or secret boundaries; data continues to load from the existing public data-package URLs. No checked-in tokens.
- **CA-005**: No new dataset, cache, or export is expected. If any build artifact is produced, it MUST land in an already-gitignored path (`data/`, `site/static/data/`); no generated data is tracked.
- **CA-006**: Error paths MUST be explicit: an unmet lasso resource budget (FR-012), a sibling-parquet drift (FR-014), and an empty "Cart only" set (FR-006) MUST each surface a visible message — never a silent empty scatter or swallowed failure.
- **CA-007**: Site-mode availability and which cart kinds can be displayed MUST be derived from the loaded data/manifest and runtime mode, not from a hardcoded assumption about which sites a saved item can belong to; a mismatch (e.g., an unknown cart kind) MUST surface as an explicit message.
- **CA-008**: This feature produces no new organizer-facing artifact. If a data-package rebuild is ultimately required, the rebuilt bundle MUST ship its existing machine-readable provenance (state-keys, inputs, command, seed) co-located and free of absolute/user-home paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On all three sites, a user can narrow the visible corpus to their saved items with a single toggle, and the control is labeled "Cart only" everywhere (zero remaining "Saved only" labels).
- **SC-002**: When the cart spans sites, 100% of the time that "Cart only" is active on a site that cannot show every saved item, the cross-site warning is displayed with an accurate count of hidden (other-site) saved items.
- **SC-003**: Toggling "Cart only" and adding/removing cart items updates the filtered view in under 1 second on the largest (neuroscape) corpus.
- **SC-004**: On atlas-root and neuroscape, a search visibly highlights matching points in the visualization and supports a one-action bulk add of the matching set to the cart.
- **SC-005**: A lasso selection on the neuroscape backdrop keeps the enclosed points visibly distinct at every zoom level (contrast gap preserved on zoom-in) in 2D and is reflected in 3D, and returns the complete enclosed set (validated against full geometry) without downloading a whole envelope parquet (per-table range fetch only) and without a Plotly trace rebuild on selection change, staying responsive (~150 ms to apply the highlight; no multi-second freeze) on a representative desktop session.
- **SC-006**: Where the lasso resource budget cannot be met (e.g., mobile), the control is unavailable with a visible explanation in 100% of those cases — no silent partial selections observed.
- **SC-007**: The byte-identical-build guarantee for `/ohbm2026/` non-UI artifacts is preserved (no data-package rebuild triggered solely by this UI change), and existing site tests plus the new tests pass.
- **SC-008**: With search, lasso, facets, and "Cart only" active in any combination, the result list, facet counts, and scatter highlight all show exactly their intersection (verified by test for representative combinations), with no filter clobbering another.

## Assumptions

- **Lasso primitives already exist** in the shared visualization component across modes; this feature is expected to be largely verification, wiring, and budget-guarding for atlas-root/neuroscape rather than building lasso from scratch. The "without significant resource consumption" constraint is interpreted as: per-table range fetch only (no whole-envelope download) and responsiveness within the existing 3D point-budget regime.
- **"Search selection"** is interpreted as bringing the OHBM-2026 search→list→visualization-highlight→bulk-add-to-cart workflow to atlas-root and neuroscape, not a brand-new selection paradigm. Per-result add/remove and the unified cart already work in all modes; the gap is the search-result highlighting and a search-scoped bulk add.
- **The cross-site warning** is modeled on the existing faceted-filter affordance (an inline notice), not a modal — it informs without blocking.
- **No parquet rebuild is required**: the full corpus geometry needed for lasso and the cart kinds needed for the warning are already available via existing per-table range fetches; this stays a UI-only change. If that proves false during planning, it is flagged as a scope change.
- **Composition is an intersection** of all active filters (search ∩ lasso ∩ facets ∩ cart-only). This intentionally supersedes the prior OHBM 2026 cart-dominant override; the OHBM 2026 home page adopts the same intersection semantics so all three sites behave identically.
- **The 2D lasso highlight already works** — the only 2D defect is a zoom-contrast wash-out (unselected opacity rises to match selected on zoom-in), fixed by capping unselected opacity below selected when a selection is active; the existing `selectedpoints`-style mechanism is kept (no 2D rewire). **3D** does not currently reflect the selection and is being added via an in-place restyle (no trace rebuild). The geometry → id plumbing already resolves against full coords, so US3 is a fix-and-extend rather than a from-scratch build.
- **Supported small-screen behavior** follows the existing mobile conventions (lasso pan-only on mobile; warnings remain legible).
