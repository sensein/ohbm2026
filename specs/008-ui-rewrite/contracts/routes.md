# Contract: Site Routes

The site is a single-page-ish application with three top-level routes. SvelteKit serves them as static HTML + per-route lazy-loaded JS chunks.

## Routes

| Path | Component | Description | Hard-link-ability |
|---|---|---|---|
| `/` | `+page.svelte` | Home: search + UMAP + result list + detail panel. State (search query, filters, lasso, selected abstract) is reflected in URL query params so the page is shareable. | Yes — `?q=...&model=neuroscape&input=abstract&filters=...&abstract=M-AM-101` |
| `/about` | `about/+page.svelte` | About page with overview + collapsible deep-dives. | Yes — `/about#embedding-models` etc. for deep-dive anchors |
| `/abstract/<poster_id>` | `abstract/[poster_id]/+page.svelte` | Permalink to a single abstract's detail panel; opens the same detail UI as `/` but without the surrounding search context. Used by cart-email permalinks. | Yes — direct link |

## Query-param contract on `/`

The home route serializes its state into URL query params (debounced ~500 ms during typing) so users can share their view:

| Param | Type | Default | Notes |
|---|---|---|---|
| `q` | string | empty | Search query (semantic + lexical) |
| `mode` | enum | `both` | Search mode: `semantic` \| `lexical` \| `both` |
| `model` | enum | `neuroscape` | Selected model |
| `input` | enum | `abstract` | Selected input source |
| `filters` | comma-sep | empty | Active facet filters, encoded as `facet_key:option_value` pairs (e.g. `methods:fMRI,species:Human`) |
| `lasso` | base64 | empty | Lasso-selected abstract ids, packed as a base64 varint list to keep URLs short |
| `abstract` | string | empty | Currently-focused poster_id (for the detail panel) |
| `tour` | bool | false | `?tour=1` re-launches the walkthrough on page load |

Empty params are dropped from the URL.

## Permalinks for cart-email

When the user clicks "email my list" with a non-empty cart, each cart item's permalink is `/abstract/<poster_id>` — NOT `/?abstract=<poster_id>`. Rationale:
- Shareable: even if the recipient doesn't have the search context, the direct link works.
- Crawler-friendly: search engines can index per-abstract pages.
- Resilient: a future search/UMAP UX change doesn't break archived cart-email permalinks.

## 404 + edge cases

- `/abstract/<unknown>` — renders a "Abstract not found" page; offers a search link back to `/`.
- `/` with `?abstract=<unknown>` — opens the home view; toast says "Abstract <poster_id> not found"; the detail panel stays empty.
- `/<anything-else>` — SvelteKit's catch-all renders a 404 page; SPA fallback to `/` is configured so deep links work on GitHub Pages.
