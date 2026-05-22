# Quickstart: Navigate posters by ID

Dev + verification commands a maintainer needs.

## Prerequisites

- `site/` has its pnpm deps already installed (`pnpm install` once
  per fresh clone).
- The data package is reachable. For local development against the
  prod parquet you can either:
  - Set `VITE_DATA_PACKAGE_URL` in your shell to the Dropbox URL,
    OR
  - Point at the local Dropbox-synced parquet via the
    `site/scripts/stage-and-serve.mjs` flow (see
    `site/scripts/stage-and-serve.mjs:67`).

## Dev loop

```bash
cd site
pnpm dev
# open the printed http://localhost:5173/ohbm2026/ URL
```

Smoke checks while iterating:

1. Home page loads → spot a result card → note its 4-digit poster id
   (e.g. `0345`).
2. Type `id:345` in the search bar → dropdown shows exactly one
   match → press Enter → URL becomes `/abstract/345/` and the
   abstract renders.
3. Type `id:12` → dropdown shows `0012`, `0120`–`0129`, `1200`–`1299`
   sampled; `1012` and `0212` are NOT in the list.
4. Browser-back → home page → search bar still contains `id:12`,
   dropdown re-renders, result list stays hidden.
5. Backspace until the `id:` prefix is gone → result list
   re-renders; dropdown unmounts.
6. Press `g` from anywhere on the page (no input focused) → search
   bar focused, value becomes `id:`, cursor at end.
7. While focus is in the search bar, press `g` → literal `g` lands
   in the input; no shortcut behavior.

## Test commands

```bash
# Unit tests for the pure-function parser/validator
cd site
pnpm exec vitest --run src/tests/unit/goto_poster.test.ts

# Full UI unit suite
pnpm exec vitest --run src/tests/unit

# Playwright e2e for this feature
pnpm exec playwright test src/tests/e2e/goto_poster.spec.ts

# Type-check
pnpm check
```

Expected results:

- Unit tests: parser + filter cases all green (parseIdOperator
  positive/negative, normaliseQuery leading-zero/non-digit,
  filterSuggestions prefix-match including exclusion of `1012`/`212`
  for query `12`, limit, sort).
- e2e: 6 US1 specs + 1 US2 spec, all green against the preview
  deploy or `pnpm preview`.

## Build verification

```bash
cd site
pnpm build
```

Must succeed without new TypeScript errors. The build emits the same
prerendered HTML; the input itself is hydrated client-side after
SvelteKit mounts.

## Manual a11y spot-check

- Tab from the top of the page until focus lands on the SearchBar.
  Confirm a visible focus ring.
- VoiceOver (macOS): with focus on the SearchBar, type `id:12`;
  hear the combobox expanding + the suggestion count via the
  aria-live overflow announcement.
- With focus elsewhere on the page, press `g`; hear the SearchBar
  re-focused and the value change to `id:`.

## Deploy verification

After the PR merges, the existing `deploy-ui.yml` rebuilds and pushes
to gh-pages. To verify on production:

1. Open `https://abstractatlas.brainkb.org/ohbm2026/`.
2. Type a known poster id; confirm navigation.
3. Footer should show the matching deploy SHA.

No parquet upload step is needed for this feature — the data package
is unchanged.
