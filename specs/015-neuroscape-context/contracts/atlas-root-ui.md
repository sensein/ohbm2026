# Contract — Atlas Root UI (Stage 15)

This contract pins the user-visible behaviour of the bare-root
cross-conference atlas landing page (`SITE_MODE === 'atlas-root'`).
Vitest unit specs + Playwright e2e specs MUST cover every behaviour
listed here.

## Routes

The atlas-root SvelteKit build exposes exactly two routes:

- `/` — the cross-conference atlas landing page (home).
- `/404.html` — adapter-static fallback (gh-pages convention).

The atlas-root build does NOT expose:
- `/abstract/<id>/` (visitors who click a point use the deep-link
  CTA in the slide-in detail panel to navigate to the sibling
  subsite's permalink — see R-014 + FR-015).
- `/about/`, `/cart/`, or any other route. These live only in the
  `/ohbm2026/` and `/neuroscape/` builds.

## Page layout

The home page consists of:

```text
+----------------------------------------------------------------+
|                       <LandingPageHeader>                      |
|   Browse OHBM 2026 →   Browse the NeuroScape PubMed atlas →    |
|       [Show OHBM 2026 overlay: ON ]   [View: 3D ↔ 2D]         |
+----------------------------------------------------------------+
|                                                                |
|                          <UmapPanel>                           |
|             (NeuroScape backdrop + OHBM 2026 overlay)          |
|                                                                |
+----------------------------------------------------------------+
|                  <ClusterLegend>  (collapsible)                |
+----------------------------------------------------------------+
|                <BackdropDensitySlider>                         |
+----------------------------------------------------------------+
```

When a visitor clicks a point or completes a lasso selection a
slide-in `<DetailPanel>` overlays the right side of the viewport;
clicking the page background closes it.

## Components

### `<LandingPageHeader>` (new)

- Brand text on the left: "abstractatlas".
- Two outbound subsite links in the header center: "Browse OHBM 2026
  abstracts →" → `/ohbm2026/`, "Browse the NeuroScape PubMed atlas →"
  → `/neuroscape/`. Both rendered as `<a>` with `target="_self"` (full
  navigation, not in-page route).
- An "About" link on the right pointing to a static `#about` modal
  with the citation block (NeuroScape Zenodo link, project README
  link, OHBM 2026 attribution). The modal's external links are
  link-checked at build time (FR-024).

### `<AtlasOverlayToggle>` (new)

- Single binary checkbox labelled "Show OHBM 2026 overlay".
- Default: **on**.
- State persisted in `localStorage` under key
  `atlas_root.show_ohbm_overlay` (boolean serialised as `"0"|"1"`).
- Backed by the Svelte store
  `site/src/lib/stores/atlas_overlay.ts`.
- Tests: `site/src/tests/unit/atlas_overlay.test.ts` covers
  default-on, toggle-off, persistence across reload, and the
  guard for malformed localStorage values (defaults to on).

### `<DimensionalityToggle>` (reused; SITE_MODE='atlas-root' enabled)

- Binary 2D/3D control. Already exists in the OHBM 2026 site for the
  internal UMAP view; reused here without modification.
- Default: **3D**.
- Switching dimensionality MUST preserve the overlay toggle state,
  the cluster legend filter, and any in-flight lasso selection.

### `<UmapPanel>` (reused with new data-source branch)

- Renders the scatter from `atlas.parquet`'s
  `neuroscape_backdrop_full` OR `neuroscape_backdrop_decimated` row
  group (see R-011 mobile detection) plus the
  `ohbm_overlay` row group when the overlay toggle is on.
- NeuroScape points: cluster colour (from `colour_hex`), opacity
  controlled by the density slider, glyph size `1`.
- OHBM 2026 points: distinct foreground appearance — outlined glyph,
  larger size `4`, z-order above the backdrop.
- Hover: cross-targets both layers; tooltip shows
  - NeuroScape: `{title} · {year} · {cluster.title}`
  - OHBM 2026: `{title} · poster #{poster_id} · near {cluster.title}`
- Click: opens `<DetailPanel>` with the row's permalink + cross-pointer.
- Lasso: opens a grouped result list overlay (see below).

### `<ClusterLegend>` (reused)

- Renders the top-32 (primary palette) clusters with their titles
  + a colour swatch, sorted by point count desc.
- Below that, a `Show all 175 clusters` disclosure exposes the
  secondary-palette clusters in cluster_id order.
- Each row has an eye-icon toggle: clicking it filters points of that
  cluster out of the scatter (in both backdrop layers AND in the
  overlay's `nearest_cluster_id` filter).

### `<BackdropDensitySlider>` (new)

- Slider 0.05–1.0 controlling NeuroScape point opacity.
- Default: 0.25 (chosen so the OHBM 2026 overlay remains readable at
  default zoom — FR-013).
- Not persisted (re-defaults on reload).

### `<DetailPanel>` (reused with new data-source branch)

- Slide-in from the right on point click.
- For NeuroScape points: renders a compact card with title, year,
  cluster info, and a "Open on /neuroscape/ →" CTA pointing at
  `cross_pointers.permalink`. Authors / journal / abstract body /
  DOI are NOT shown on the landing-page slide-in panel (and are NOT
  stored in `atlas.parquet`) — the visitor follows the CTA to the
  subsite which fetches the body at view time per R-015.
- For OHBM 2026 points: renders a compact card with title, poster id,
  authors, brief preview, nearest cluster, and a "Open on /ohbm2026/
  →" CTA.
- Close: click background or press Escape.

### Lasso result list (reused with grouping)

When a lasso completes:

- A modal opens showing two collapsible sections:
  - "OHBM 2026 ({n} matched)" — list of overlay points in the lasso,
    each row a click-through to `/ohbm2026/abstract/<id>/`.
  - "NeuroScape PubMed ({n} matched)" — list of backdrop points in
    the lasso, each row a click-through to
    `/neuroscape/abstract/<pubmed_id>/`.
- Sections are independently collapsible; counts sum to the lassoed
  total (verified by Playwright spec).

## Mobile / slow-device adaptation

On first load the page detects `navigator.deviceMemory <= 4 ||
navigator.userAgentData?.mobile === true`. If either is true, the
default backdrop is `neuroscape_backdrop_decimated`. A "Show full
atlas" button appears next to the density slider and switches to
`neuroscape_backdrop_full` when clicked.

The detection runs ONCE on first paint; the visitor's choice is NOT
persisted (next visit re-runs the detection so a phone with cleared
memory hints stays mobile-default).

## Error states

| Trigger | UI |
|---------|----|
| `atlas.parquet` fetch fails | Inline error card: "Atlas data unavailable. Refresh to retry." with a Retry button. |
| `atlas.parquet`'s sibling state-keys don't match the deployed siblings (per R-012) | Inline error banner naming the stale sibling: "The atlas data has drifted from /ohbm2026/ data (ohbm2026 state-key mismatch). Refresh in a few minutes." |
| WebGL context lost | Per existing OHBM 2026 UmapPanel handling. |

## Performance budgets

- First paint: ≤ 5 s on a recent laptop on a warm cache (SC-003).
- First paint mobile: ≤ 10 s on a mid-range phone (SC-007).
- Drag-rotate: ≥ 30 fps on the default decimated backdrop (SC-003).
- 2D ↔ 3D switch: ≤ 2 s perceived (US2 acceptance scenario 1).
- Lasso to result list paint: ≤ 1 s for selections of up to 5K
  points.

## Test coverage requirement

| Behaviour | Test |
|-----------|------|
| Binary toggle store default-on + persistence | `atlas_overlay.test.ts` (vitest) |
| Bare root no longer redirects | `atlas_root.spec.ts` (Playwright) |
| Header outbound links target correct subsites | `atlas_root.spec.ts` |
| 2D ↔ 3D switch preserves overlay + legend filter state | `atlas_root.spec.ts` |
| NeuroScape hover tooltip shape | `atlas_root.spec.ts` |
| OHBM 2026 hover tooltip shape | `atlas_root.spec.ts` |
| Click → slide-in detail panel + correct CTA href | `atlas_root.spec.ts` |
| Lasso → grouped result list (counts + group keys) | `atlas_root.spec.ts` |
| Cross-parquet drift surfaces a visible error component | `atlas_root.spec.ts` (mock loader injection) |
| Mobile detection → decimated default | `atlas_root.spec.ts` (device-emulation) |
