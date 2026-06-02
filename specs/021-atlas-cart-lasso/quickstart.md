# Quickstart: verify Cart-only + selection intersection + lasso highlight

UI-only feature in `site/`. No Python, no data rebuild.

## Local dev (per mode)

From `site/` (copy `site/.env.example` → `.env.local` first so the data-package URLs resolve — see `memory/local_dev_env.md`):

```bash
cd site
pnpm install
# atlas-root (the / cross-conference atlas)
VITE_SITE_MODE=atlas-root pnpm dev
# neuroscape (461k PubMed corpus)
VITE_SITE_MODE=neuroscape pnpm dev
# ohbm2026 (default; also builds with no env)
VITE_SITE_MODE=ohbm2026 pnpm dev
```

## Tests

```bash
cd site
# unit (jsdom) — RUN mode, never watch (see memory/feedback_vitest_run_mode.md)
pnpm exec vitest run
pnpm exec vitest run src/tests/unit/selection_compose.test.ts src/tests/unit/cart_scope.test.ts
# e2e
pnpm test:e2e
pnpm exec playwright test src/tests/e2e/cart_only_parity.spec.ts src/tests/e2e/selection_highlight.spec.ts
# typecheck + lint
pnpm check && pnpm lint
```

## Manual verification by story

### US1 — Cart only + intersection + warning
1. On `/ohbm2026/`, save a couple of abstracts; on `/neuroscape/`, save a couple of articles (shared cart).
2. On `/neuroscape/`, toggle **Cart only** → list shows only the neuroscape saved items; a notice reports the OHBM saved items as hidden ("from other collections").
3. Add a search term while Cart-only is on → list narrows to the intersection (saved ∩ search). Apply a cluster/year facet → narrows further. Remove search → widens back to saved ∩ facet.
4. Empty the cart → Cart-only shows the "cart is empty" empty state. Cart with only OHBM items, on neuroscape → "none available in this site".
5. On `/ohbm2026/`, confirm the control reads **Cart only** (not "Saved only") and now composes with search/facets/lasso instead of overriding them.

### US2 — search highlight + bulk add (atlas-root + neuroscape)
1. Run a query → matching points are visibly highlighted on the scatter (others dimmed); the list reflects the matches.
2. Click **+ Add N to cart** → exactly the matched set is added (verify via the cart drawer count).

### US3 — lasso highlight (2D + 3D)
1. In 2D, draw a lasso → enclosed points become opaque, the rest dim; the list narrows to the enclosed region (full-corpus resolved, not just the sample).
2. Switch to 3D → the same selection is reflected (highlight visible); rotate/zoom stays responsive (no multi-second freeze).
3. Combine lasso + search + Cart-only → list and highlight show their intersection.
4. On a mobile viewport, the lasso control is disabled with a short note; Cart-only + warning remain usable.

## Done-when
- All new + existing unit/e2e suites green; `pnpm check && pnpm lint` clean.
- No `Plotly.react` fires on a selection change (the e2e render/trace-count probe stays flat).
- No data-package rebuild was triggered; only `site/` source changed.
