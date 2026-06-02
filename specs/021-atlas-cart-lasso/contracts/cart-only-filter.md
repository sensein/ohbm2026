# Contract: "Cart only" filter + cross-site warning

**Surfaces**: the toggle in OHBM home (`+page.svelte:2338`, relabeled) and NEW toggles in the atlas-root / neuroscape control areas (`AtlasRootFacets` / `NeuroscapeFacets` or the home header); the warning notice in/above each browse panel.

## Label & control

| # | Rule |
|---|------|
| L1 | The control reads **"Cart only"** (active state "✓ Cart") on all three sites. Zero "Saved only" strings remain. |
| L2 | `data-testid="toggle-cart-only"` is preserved (OHBM) and used for the new atlas/neuroscape toggles. |
| L3 | Control is disabled when the cart is empty and the filter is off (mirrors OHBM `:2339`). |
| L4 | Toggling reacts live; no reload. |

## Filtering behavior

| # | Rule |
|---|------|
| F1 | When on, Cart-only contributes the constraint set `savedInCorpus().shown` to the intersection (see selection-composition). It does NOT override search/lasso/facets. |
| F2 | The constraint set = saved items whose `(kind,id)` is present in the **loaded corpus index** for the current mode (runtime membership, R-004). |
| F3 | Live update on cart add/remove/clear while active (SC-003, < 1 s on 461k). |

## Cross-site warning (facet-style, non-blocking)

| # | Rule |
|---|------|
| W1 | Shown only when Cart-only is active **and** `hiddenCount > 0`. |
| W2 | States that only saved items available in this site are shown, with the count of hidden (other-collection) items. Example: "Cart only — showing 12 saved items available here. 8 saved items from other collections are hidden." |
| W3 | Inline/dismissible affordance modeled on an active faceted-filter chip — never a modal. |
| W4 | On atlas-root (both kinds displayable) `hiddenCount` is normally 0 ⇒ no warning. |
| W5 | A saved item with an unrecognized `kind` is counted in `hiddenCount` and named generically ("from other collections") — never silently dropped (Constitution VII / VI). |

## Empty states

| # | Rule |
|---|------|
| E1 | Cart empty + Cart-only on → "Your cart is empty — save items to use Cart only." |
| E2 | Cart non-empty but `shown` is empty (all saved items belong to other sites) → "None of your N saved items are available in this site." (distinct from E1). |
| E3 | Cart-only ∩ search/facets/lasso empty → standard "no matches" empty state (the intersection simply yielded nothing). |
