# Phase 1 Data Model: client-side selection & filter state

No persisted schema or parquet changes. This documents the **in-browser** state and the derived rules. All state already exists except where marked **NEW**.

## Stores (Svelte, `site/src/lib/stores/`)

| Store | Type | Source | Role in this feature |
|-------|------|--------|----------------------|
| `searchQuery` / `debouncedSearchQuery` | `string` | `selection.ts:10,28` | search term; debounced for 461k corpus |
| `activeFilters` | `Map<string, Set<string>>` | `selection.ts:37` | OHBM facet selections |
| `lassoSelection` | `Set<number> \| null` | `selection.ts:39` | OHBM lasso id set (null = inactive) |
| `cartOnly` | `boolean` | `selection.ts:49` | the toggle; **doc renamed** "Show only saved" → "Cart only" |
| `authorChips` | `Set<string>` | `selection.ts:57` | OHBM author-chip filter (unchanged, still intersects) |
| `cartItems` | `CartItem[]` | `cart.ts:210` | typed cross-site cart |
| `cartOhbmPosterIds` | `Set<number>` | `cart.ts:222` | ohbm-kind saved ids |
| `cartNeuroPubmedIds` | `Set<number>` | `cart.ts:235` | neuroscape-kind saved ids |

`CartItem = { kind: 'ohbm2026' \| 'neuroscape'; id: number }` (`cart.ts:30`). Cart membership is the basis for the Cart-only filter and the hidden-count warning.

## Per-mode corpus indexes (derived in `+page.svelte`)

| Index | Key | Built at | Used for |
|-------|-----|----------|----------|
| `abstractsByPosterId` | poster_id | OHBM load | OHBM corpus membership / cart resolution |
| `listCorpusById` | pubmed_id | `:646` | neuroscape full-corpus membership (461k) |
| `atlasOverlayById` | poster_id | `:636` | atlas-root OHBM overlay membership |
| `atlasBackdropById` | pubmed_id | `:639` | scatter (decimated atlas-root / full neuroscape) |

"Available in this site" = present in that mode's membership index(es) — see R-004.

## Derived selection sets

### Atlas/neuroscape lasso (component-local in `+page.svelte`)
- `atlasLassoOhbmSet: Set<number>`, `atlasLassoNeuroSet: Set<number>` — set by `onAtlasLasso` (`:1080`) from `selectIdsInGeometry` over **full** coords; `anyLassoActive` (`:737`).

### NEW — pure composer (`site/src/lib/selection/compose.ts`)
```
compose(parts: Array<Set<ID> | null>): Set<ID> | null
  // null part = no constraint (identity). Returns the intersection of all
  // non-null parts, or null if every part is null (= "no filter, show all").
```
Used by both data paths so the intersection semantics are identical and unit-tested. ID = `number` (poster_id or pubmed_id within a mode).

### NEW — cart scope (`site/src/lib/selection/cart_scope.ts`)
```
savedInCorpus(cartItems, indexHas: (kind, id) => boolean): { shown: Set<number>; hiddenCount: number; hiddenKinds: string[] }
```
- `shown` = saved ids whose `(kind,id)` is in the loaded index for this mode (the Cart-only constraint set).
- `hiddenCount` = saved items not displayable here (drives the warning).
- `hiddenKinds` = distinct kinds among hidden items (for the message text; unknown kinds named generically).

## Composition rules (the contract, see contracts/selection-composition.md)

Visible/highlighted set = `compose([searchSet, lassoSet, facetSet, authorChipSet, cartSet])`:

| Filter | OHBM source | Atlas/neuroscape source | When inactive |
|--------|-------------|-------------------------|---------------|
| search | `effectiveSearchIds` (`:405`) | panel `matchedIds` (**NEW** exposed, R-003) | `null` |
| lasso | `$lassoSelection` | `atlasLassoNeuroSet`/`atlasLassoOhbmSet` | `null` |
| facets | `facetIds` (`:422`) | cluster/year filter on `listCorpus` → `listFacetFiltered` (`:696`) | `null` |
| author chips | `authorChipIds` (`:426`) | — (n/a) | `null` |
| cart-only | `cartIds` (cart ∩ corpus) | `savedInCorpus().shown` | `null` |

- **Identity**: an inactive (null) filter never narrows the set.
- **Empty intersection**: a non-null result of size 0 ⇒ explicit empty state (UI distinguishes "cart empty" from "saved items exist but none here").
- **Facet counts**: computed over the intersection of all active filters *except* the facet being counted (OHBM `preFilterForFacetCounts` `:437`, extended to include `cartIds`).
- **Scatter highlight**: the same intersection set drives the scatter highlight (R-001). **2D** keeps the native `selectedpoints` mechanism but caps unselected opacity below selected when a selection is active (fixes the zoom wash-out). **3D** adds the highlight via an in-place `Plotly.restyle` of a per-point opacity/colour array (selected→1.0, unselected→density-aware). Neither path calls `Plotly.react`.

## State transitions

- Toggle Cart-only on → `cartSet` becomes non-null → intersection narrows; warning shown if `hiddenCount > 0`. Off → `cartSet` null → widens.
- Cart mutation while Cart-only on → `cartItems` change → `savedInCorpus` recomputes → list/scatter/warning update live (SC-003, < 1 s).
- Draw lasso → lasso set non-null → narrows + highlights. Clear (`plotly_deselect` → `lassoclear`) → lasso null.
- Each transition recomputes the composed set once and restyles once (no `Plotly.react`).
