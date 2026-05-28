# Contract: Atlas-Root Search UI

**Status**: Phase 1 contract for spec 019 · **Date**: 2026-05-27

The user-facing search affordance on the atlas-root subsite
(`abstractatlas.brainkb.org/`). Mirrors the existing /ohbm2026/
search bar visually + behaviourally, but ranks across BOTH corpora
via [search-ranking-pipeline.md](search-ranking-pipeline.md).

---

## 1. Components

### `AtlasRootSearchBar.svelte` (NEW)

Position: directly below the atlas-root header, above the scatter.

**Reuses the existing `SearchBar.svelte` component verbatim** (FR-025).
The atlas-root version is a thin wrapper that mounts `SearchBar` with
the cross-conference data sources for `id:` autocomplete + the
`/atlas-root/` placeholder text. No fork. Mounting the same component
on the three surfaces is what guarantees syntax + UX parity per US3.

Supported operators (inherited from OHBM, ALL apply on atlas-root):

| Operator | Example | Behaviour on atlas-root |
|---|---|---|
| Implicit AND | `fmri aging` | Title-substring match for both terms across either corpus |
| Quoted phrase | `"default mode network"` | Exact phrase match in either corpus's titles |
| Negation | `-fmri`, `-"resting state"` | Exclude any row whose title contains the term, in either corpus |
| Alternation | `aging OR development` | Either side matches in either corpus |
| Id lookup | `id:1234` | Match `poster_id=1234` (OHBM) **AND** `pubmed_id=1234` (NeuroScape) in parallel — both rows surface if both exist (FR-026) |

Help-dropdown copy is the same on all three surfaces (one source of
truth in `SearchBar.svelte`'s template).

DOM contract (data-testid attributes for e2e):

```html
<form data-testid="atlas-root-search-form">
  <input
    type="search"
    data-testid="search-input"            <!-- SAME testid as /ohbm2026/ -->
    placeholder="Search across OHBM 2026 + NeuroScape…"
    aria-label="Cross-conference search"
  />
  <button
    type="button"
    data-testid="search-semantic-toggle"  <!-- SAME testid as /ohbm2026/ -->
    aria-pressed={semanticEnabled}
  >
    ✨ Semantic
  </button>
</form>
```

`data-testid` values match the existing OHBM SearchBar so existing e2e
selectors work on the new surface unchanged (a side-benefit of
reusing the component).

State: `semanticEnabled: boolean` lives in the existing
`$lib/stores/searchMode.ts` store (extended; same store the
`/ohbm2026/` search bar uses, so cross-tab consistency is automatic).
Query string lives in component-local state; debounced ~150 ms before
firing the ranker.

---

### `AtlasRootResultList.svelte` (NEW)

Mounted below the search bar when the query is non-empty. Renders
ranked hits with the EXISTING OHBM-vs-NeuroScape source identification
already shipped on atlas-root: each row reuses the same pill +
swatch colour that `cross_pointers` produces today.

NO new badge UX (per spec US4 + Clarifications session 2026-05-27
Q1).

Row interaction: clicking a row navigates via the existing
`cross_pointers` table on `atlas.parquet`:

| Row corpus | Permalink |
|---|---|
| `ohbm2026` | `/ohbm2026/abstract/<poster_id>/` (with leading `/` honouring `kit.paths.base`) |
| `neuroscape` | `/neuroscape/abstract/<pubmed_id>/` |

---

## 2. State machine

```text
EMPTY  (no query text)
  │
  ├── typing → DEBOUNCING (150 ms)
  │             │
  │             └── debounce elapsed → RANKING
  │                                      │
  │                                      └── results arrive → SHOWING
  │
  └── clear input → EMPTY
```

While `RANKING`, the result list shows a small inline spinner. The
scatter behind it does not change (the toggle from FR-019 stays
unchanged).

---

## 3. Cross-spec cross-component invariants

- The `✨ Semantic` toggle uses the SAME label, badge styling,
  loading-spinner pattern as `/ohbm2026/`'s SearchBar +
  `/neuroscape/`'s NeuroscapeBrowsePanel — verified by SC-008's
  screenshot diff.
- The existing atlas-root overlay toggle (Show OHBM 2026 overlay)
  is OUTSIDE the search bar's DOM; the search bar MUST NOT modify
  that toggle's state (FR-019).
- The search bar's `data-testid` selectors are stable for e2e (`atlas-
  root-search-form`, `atlas-root-search-input`, `atlas-root-semantic-
  toggle`).

---

## 4. Acceptance scenarios → test mappings

| Spec acceptance scenario | Test file (e2e) | Test name |
|---|---|---|
| US4 / Sc.1 — lexical hits from both corpora rank together | `site/src/tests/e2e/semantic.spec.ts` | `atlas-root: lexical hits from both corpora appear in single ranked list` |
| US4 / Sc.2 — zero-lexical semantic ranking spans corpora | `site/src/tests/e2e/semantic.spec.ts` | `atlas-root: zero-lexical query surfaces semantic hits from BOTH corpora` |
| US4 / Sc.3 — click navigates to correct subsite permalink | `site/src/tests/e2e/semantic.spec.ts` | `atlas-root: OHBM row click → /ohbm2026/...; NeuroScape row click → /neuroscape/...` |
| US4 / Sc.4 — overlay toggle state unchanged by search | `site/src/tests/e2e/semantic.spec.ts` | `atlas-root: typing in search bar does not toggle the OHBM overlay` |

---

## 5. Accessibility

- Search input has `aria-label="Cross-conference search"`; placeholder
  is decorative only.
- `✨ Semantic` toggle button has `aria-pressed` reflecting current
  state.
- Result list is a `<ul role="list">`; each row is a `<li>` with a
  nested `<a>` element for the permalink (so keyboard / screen-reader
  navigation works without JS).
- Empty result state: an explicit `<p>No matches.</p>` message
  (`data-testid="atlas-root-empty"`), not just an empty list.
- Loading state ("Ranking…") is announced via `aria-live="polite"`
  on the result list container.
