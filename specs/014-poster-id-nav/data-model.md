# Phase 1 Data Model: Navigate posters by ID

Pure-function types and rules for the `id:` operator added to the
existing `SearchBar`. No persistent entities introduced. Reuses the
existing `AbstractRecord` from `site/src/lib/shards.ts`.

## Pure-function module — `site/src/lib/goto_poster.ts`

```ts
import type { AbstractRecord } from '$lib/shards';

/** A single suggestion shown in the dropdown. */
export interface Suggestion {
  posterId: number;
  display: string;  // 4-digit zero-padded, e.g. "0345"
  title: string;
}

/** The result of filtering the corpus by the user's typed query. */
export interface SuggestionResult {
  visible: Suggestion[];     // capped at `limit`, ascending by posterId
  total: number;             // overflow = total - visible.length
  exactMatch: Suggestion | null;
}

/**
 * Return the digit payload when `raw` starts with the `id:` operator
 * (case-insensitive, optional whitespace around the colon and digits),
 * or `null` otherwise. When `raw === "id:"` returns `""` (empty payload
 * — drives the "type a poster number" hint).
 */
export function parseIdOperator(raw: string): string | null;

/**
 * Normalize the digit payload to the matching query string: drop
 * non-digits, strip leading zeros. Returns `""` for empty / pure-zero
 * payloads.
 */
export function normaliseQuery(payload: string): string;

/** Run the prefix-on-integer filter against the loaded corpus. */
export function filterSuggestions(
  payload: string,
  abstractsByPosterId: Map<number, AbstractRecord>,
  limit?: number,  // default 10
): SuggestionResult;
```

## Activation rule

`parseIdOperator("id:1234")  → "1234"`
`parseIdOperator("ID:1234")  → "1234"` (case-insensitive)
`parseIdOperator("id:  12 ") → "  12 "` (whitespace passes through;
`normaliseQuery` strips later)
`parseIdOperator("id:")      → ""` (empty payload → hint, no list)
`parseIdOperator("id")       → null` (no colon → not navigator mode)
`parseIdOperator("ab id:34") → null` (only START of query activates)
`parseIdOperator("")         → null`
`parseIdOperator("topic:x")  → null`

## Matching rule

1. `normaliseQuery(payload)`:
   - Drop every non-digit character.
   - Strip leading zeros.
   - If nothing remains (`""`, `"0"`, `"00"`, …) return `""`.

2. `filterSuggestions(payload, map, limit = 10)`:
   - `q = normaliseQuery(payload)`.
   - If `q === ""` → `{ visible: [], total: 0, exactMatch: null }`.
   - For each `[id, record]` in `map`:
     - Include iff `id.toString().startsWith(q)`.
   - Sort ascending by `id`.
   - `total = matched.length`.
   - `visible = matched.slice(0, limit).map(record => ({
       posterId: record.poster_id,
       display: String(record.poster_id).padStart(4, "0"),
       title: record.title,
     }))`.
   - `exactMatch = visible.length === 1 && total === 1 ? visible[0] : null`.

### Worked examples

| Search-bar value | `parseIdOperator` | `normaliseQuery` | Matched ids (sample) | `total` | `exactMatch` |
|---|---|---|---|---|---|
| `id:12` | `"12"` | `"12"` | `12, 120..129, 1200..1299` | up to 111 | null |
| `id:0012` | `"0012"` | `"12"` | same | 111 | null |
| `id:2094` | `"2094"` | `"2094"` | `[2094]` if present | 1 | `{2094, …}` |
| `id:9999` | `"9999"` | `"9999"` | `[]` | 0 | null |
| `id:` | `""` | `""` | `[]` | 0 | null |
| `id:0` / `id:00` | `"0"` / `"00"` | `""` | `[]` | 0 | null |
| `topic:foo` | `null` | (n/a) | (navigator mode not active) | — | — |
| `id:12 3` | `"12 3"` | `"123"` | `123, 1230..1239` | up to 11 | null |

## SearchBar integration (UI state)

```ts
// State derived inside SearchBar.svelte
let raw = $state(''); // the existing search bar's writable
let activeIndex = $state<number>(-1);

$: idPayload = parseIdOperator(raw);
$: inNavigatorMode = idPayload !== null;
$: result = inNavigatorMode
  ? filterSuggestions(idPayload!, abstractsByPosterId)
  : { visible: [], total: 0, exactMatch: null };
$: canNavigate = inNavigatorMode && (
  result.exactMatch !== null ||
  (activeIndex >= 0 && activeIndex < result.visible.length)
);
```

State transitions:

- `raw` changes → if `inNavigatorMode` flips, the parent route
  HIDES the result list (via a `mode` boolean prop passed up via
  event or store) and the SearchBar dropdown opens.
- ArrowDown / ArrowUp → cycle `activeIndex` over `result.visible`.
- Enter while `canNavigate`:
  - Use `result.visible[activeIndex]` if highlighted, else
    `result.exactMatch`.
  - `await goto(`${base}/abstract/${posterId}/`)`.
- Escape → close dropdown; if a pre-mode query was saved in the
  undo buffer (US2), restore it.
- Backspacing the `id:` prefix → `inNavigatorMode` flips to
  false → result list re-shows.

## Reused entities

- `AbstractRecord` (from `$lib/shards.ts`) — only `poster_id` and
  `title` are read.
- `Map<number, AbstractRecord>` — the existing `abstractsByPosterId`
  map already maintained by `+page.svelte`. The SearchBar receives
  it via a new prop.

## State-key sensitivity (Constitution VII)

- The set of valid ids is derived ENTIRELY from
  `abstractsByPosterId.keys()` at runtime; no hard-coded range table.
- When the corpus state-key flips (Dropbox parquet replaced), the
  prop re-references the new map and the dropdown follows. No code
  change required.
