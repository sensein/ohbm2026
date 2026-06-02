# Contract: Selection composition (intersection)

**Surface**: `site/src/lib/selection/compose.ts` (pure) + its use in `+page.svelte` for all three modes.

## `compose(parts)`

```ts
type IdSet = Set<number>;
function compose(parts: Array<IdSet | null>): IdSet | null;
```

- Each `part` is an active filter's id-set, or `null` when that filter is inactive.
- Returns the **intersection** of all non-null parts.
- If **every** part is null → returns `null` (meaning "no constraint — show the full corpus").
- A non-null part of size 0 is honored (result becomes empty) — it is NOT treated as "inactive".

### Guarantees

| # | Rule |
|---|------|
| C1 | `compose([null, null, …]) === null` (no filter active). |
| C2 | `compose([A])` ≡ `A` for a single active filter. |
| C3 | `compose([A, B])` = `A ∩ B`; order-independent. |
| C4 | An inactive filter (`null`) never changes the result (identity). |
| C5 | An active empty filter (`∅`) forces an empty result (explicit empty state downstream). |
| C6 | Result membership ⊆ the loaded corpus for the mode (ids outside the corpus index never appear). |

## Per-mode wiring

- **OHBM** (`+page.svelte:434`): `filteredIds = compose([effectiveSearchIds, $lassoSelection, facetIds, authorChipIds, cartIds])` where `cartIds = $cartOnly ? (cart poster_ids ∩ abstractsByPosterId) : null`. **Behavior change**: `cartOnly` was a dominant override; it is now a participating filter.
- **Atlas/neuroscape**: the route narrows `filteredBackdrop`/`filteredOverlay` by `compose([lassoSet, facetSet, cartSet])`, feeds that to the browse panel, and the panel applies `search` on top → the full intersection appears in the list. The route also feeds the composed **highlight set** (incl. the panel's exposed search matches, R-003) to `UmapPanel`.

## Facet counts

`preFilterForFacetCounts` = intersection of all active filters **except** the facet dimension being counted, and now **includes** `cartIds` (OHBM `+page.svelte:437`; analogous derivation for atlas/neuroscape facet sidebars). Counts narrow as Cart-only / search / lasso narrow.
