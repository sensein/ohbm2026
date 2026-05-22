# Phase 0 Research: Navigate posters by ID

## Decision 1 — Keyboard shortcut letter

**Decision**: Single-key `g` (mnemonic "go to") focuses the
SearchBar AND inserts the `id:` prefix (cursor at end). The prior
SearchBar value, if any, is saved to an undo buffer so a fast
Escape restores it. The handler attaches at the route layout level
and ignores the key when any other input/textarea/contenteditable
is already focused.

**Rationale**:
- `g` mnemonic ("**g**o to poster") matches the `<kbd>g</kbd>`
  hint rendered near the SearchBar.
- Vim / Gmail / many web apps already use `g` as a "go" prefix, so
  the letter is conventional for navigation.
- Single key (no modifier) keeps the on-site, hands-on-keyboard
  conference experience fluid. Browser default for `g` is no-op.
- The "ignore when focused elsewhere" guard preserves normal typing
  in every existing input (the SearchBar itself included).
- Inserting `id:` automatically saves the user a 3-character setup
  vs just focusing the bar.

**Alternatives considered**:
- `/` — already conventional for "focus search", which the existing
  SearchBar currently does NOT bind but might in the future; reserving
  `/` for search avoids a future collision.
- `#` — semantically perfect ("number") but requires Shift on US
  keyboards, slowing the power-user flow.
- `Ctrl/⌘+G` — collides with the browser's "find next" binding.

## Decision 2 — Input placement (UPDATED 2026-05-22)

**Decision**: Reuse the existing `<SearchBar>` via a new `id:`
operator. When `parseIdOperator(query)` returns non-null, the bar
enters "navigator mode": the route owner hides its result list and
the SearchBar overlays an autocomplete dropdown of available ids.
A `mode-change` event communicates the transition. No separate input
component is created.

**Rationale** (2026-05-22 clarification):
- Adding a second input element on the home + permalink pages was
  rejected as visual clutter; the SearchBar is already the
  attendee's primary entry point and accepts operator-prefixed
  queries today (`topic:`, `methods:`, …).
- The operator naturally documents itself (the About page already
  lists operators); a discoverable `id:` joins that list.
- The `mode-change` mechanism keeps lexical-search semantics
  untouched outside navigator mode — typo-tolerance, ranking, and
  facets continue to work for non-`id:` queries.

**Alternatives considered (post-clarification)**:
- Treat `id:` as a faceted FILTER over the existing result list
  (cards narrow to matching ids) — rejected because at corpus
  scale the visual delta is the same as the dedicated dropdown
  but the user has to scroll a 3-column grid to reach the right
  card; the dropdown collapses everything to a single clickable
  list.
- Hybrid (filtered cards AND dropdown) — rejected for the same
  reason plus duplicated affordances.

**Pre-clarification choice** (kept here for trace):
- Originally: mount a separate `<PosterIdInput>` on home + permalink.
  Rejected by user 2026-05-22 in favor of reusing the SearchBar.

## Decision 3 — Validation timing (UPDATED 2026-05-22)

**Decision**: Synchronous, real-time. Every keystroke recomputes the
suggestion list from the in-memory `abstractsByPosterId` map. The submit
button is disabled until the input value resolves to exactly one
available id. The user is structurally prevented from submitting an
unavailable id; the "not found" path no longer exists.

**Rationale**:
- Clarification 2026-05-22: "only available ids should be used" requires
  the input to be constrained. Submit-time validation with a "not found"
  error is rejected outright.
- A combobox/dropdown is the standard accessibility pattern for "choose
  one of a known set" and works with keyboard, mouse, and touch.
- Filtering 3,240 ids synchronously is microseconds (`Map.keys()` + a
  `startsWith` scan); the 100 ms budget in SC-003 is met by orders of
  magnitude.

**Alternatives considered**:
- Submit-only validation with a "not found" inline error — REJECTED
  by the clarification.
- Strict numeric stepper (clamp on out-of-range) — rejected because it
  can't communicate WHICH ids exist; users would step through gaps
  without knowing.
- Native `<select>` of all 3,240 ids — rejected; not scrollable in a
  usable way at that scale.

## Decision 4 — Re-mount behaviour after a chained jump (UPDATED 2026-05-22)

**Decision**: The SearchBar value is persisted across navigation via
the existing query-param flow (the search bar already serializes its
value into the URL). When the permalink page mounts, it reads
`?q=id:<last>` and pre-populates the SearchBar. Pressing browser-back
from a permalink reached this way returns to the home page with the
same `id:<last>` still in the bar, so the next jump is one keystroke
away (acceptance scenario 6).

**Rationale** (2026-05-22 clarification):
- The SearchBar already round-trips its value through the URL for
  history-back support. Navigator mode rides that machinery for
  free.
- Permalink pages need a SearchBar mount anyway (so the user can
  jump again without going home first); the route owner inserts
  the same `<SearchBar>` instance and binds it to the URL query.

**Alternatives considered**:
- Empty-on-mount each route — rejected; loses chained-jump ergonomics.
- Carry full state through a layout-level store — rejected; the URL
  is already the source of truth and browser back/forward work
  naturally with the URL approach.

## Decision 5 — Where validation logic lives

**Decision**: A standalone TypeScript module
`site/src/lib/goto_poster.ts` with pure functions
(`parsePosterId(raw: string): ParseResult`,
`validatePosterId(parsed: ParseResult, abstractsByPosterId: Map<number, AbstractRecord>): ValidateResult`).
The Svelte component imports both and renders the result.

**Rationale**:
- vitest covers the parse/validate paths in milliseconds (no jsdom
  DOM cost) and can pin every spec edge case (leading zero, leading
  whitespace, non-numeric, out-of-range, withdrawn).
- The Svelte component becomes a thin render layer: easier to e2e and
  easier to refactor (e.g., swap the keyboard shortcut later).

**Alternatives considered**:
- Inline the validation inside the `.svelte` file — rejected; vitest
  cannot unit-test `.svelte` script blocks without compiling and a
  jsdom mount, defeating the speed of pure-function tests.
