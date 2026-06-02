# Contract: Selection highlight on the scatter (2D contrast + 3D)

**Surface**: `site/src/lib/components/UmapPanel.svelte` (+ a pure helper in `site/src/lib/atlas/opacity.ts`). Scope set by the 2026-06-01 clarification: **fix 2D zoom-contrast** (keep the existing mechanism) and **add 3D highlight** (new). The geometry → id path (`lasso_select.ts`) is unchanged.

## Inputs

- A **highlight id-set** per trace (backdrop + overlay) = the composed intersection (search ∩ lasso ∩ cart ∩ facets), supplied by the route. Empty/`null` ⇒ no selection active.
- The current density/zoom opacity (existing `densityZoomOpacity` / `currentZoomFactor2d`).

## 2D — keep `selectedpoints`, fix the zoom wash-out

| # | Rule |
|---|------|
| H1 | The 2D highlight MUST continue to use Plotly's native `selectedpoints` + `selected.marker.opacity: 1` + `unselected.marker.opacity`. **No rewire** of this mechanism. |
| H2 | **When a selection is active**, the unselected-point opacity MUST be capped below the selected opacity so a minimum contrast gap is preserved at every zoom level: e.g. `unselectedOpacity = min(base, base·(1−GAP))` (or an absolute ceiling), while selected stays 1.0. This replaces the current `unselected == base` coupling in `applyAtlasZoomOpacity` (`UmapPanel.svelte:1155-1159`) for the selection-active case only. |
| H3 | **When no selection is active**, retain today's behavior (`unselected == base`) so an un-lassoed cloud still reads at zoom (the original reason the two were tied). |
| H4 | The gap/cap is a pure function in `atlas/opacity.ts`, unit-tested across the full `densityZoomOpacity` range so the gap holds at all zoom factors. |

## 3D — add highlight via in-place restyle

| # | Rule |
|---|------|
| H5 | The 3D scatter MUST visibly reflect the selection (today it passes empty sets to its trace builders, `UmapPanel.svelte:1945,1953`). |
| H6 | Apply it via an **in-place `Plotly.restyle`** of a precomputed per-point `marker.opacity` (selected→1.0, unselected→density-dim) — the cheap-restyle pattern of `applyFocus3dHalo` (`~1869-1914`). **No `Plotly.react`, no trace-count change** (invariant — prevents the WebGL-context leak plotly.js#6365; asserted in e2e via a render/trace-count probe). |
| H7 | If a `marker.opacity` array restyle is found to recreate the WebGL context on `scatter3d`, fall back to a precomputed `marker.color` rgba array (alpha baked in) — still a pure restyle, still no `react`. |
| H8 | 3D highlight applies to the rendered ≤ `MAX_3D_BACKDROP_POINTS` (50k) sample; the **result list** still reflects the full-corpus intersection (documented divergence — list complete, 3D sample bounded). |

## Shared

| # | Rule |
|---|------|
| H9 | Highlight reflects the active FR-009 intersection: changing any filter recomputes the highlight set and triggers one restyle (2D) / one restyle (3D). Clearing all filters returns every point to base opacity (and 2D back to `unselected == base`). |

## Lasso event flow (unchanged)

Panel emits `lassoselect { geometry }` / `lassoclear`; route resolves ids over full coords (`selectIdsInGeometry`) and feeds the highlight set back (`+page.svelte:1080`, `lasso_select.ts:82`).

## Resource budget (pins spec FR-011 / FR-012 / SC-005)

| # | Rule |
|---|------|
| B1 | No new network: highlight adds zero fetches. The only lasso fetch is the existing one-time `coords` per-table range fetch on atlas-root (~11 MB, `ensureAtlasFullCoords`). No whole-envelope parquet download. |
| B2 | Highlight applied < ~150 ms after the lasso resolves on a representative desktop session; no multi-second freeze; no `Plotly.react` on selection change. |
| B3 | Mobile: lasso disabled (dragmode `pan`) with a visible "available on larger screens" note — no partial selection (FR-012/FR-013). |
