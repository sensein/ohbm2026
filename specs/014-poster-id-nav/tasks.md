---
description: "Stage 14 — Navigate posters by ID. Implementation task list."
---

# Tasks: Navigate posters by ID

**Input**: Design documents in `specs/014-poster-id-nav/`
**Prerequisites**: `plan.md` ✓, `spec.md` ✓, `research.md` ✓, `data-model.md` ✓, `contracts/id-search-mode.md` ✓, `quickstart.md` ✓

**Tests**: This is a behavior-changing UI feature → tests are mandatory.
Pure-function `normaliseQuery` + `filterSuggestions` get vitest;
component + route mount + keyboard shortcut + autocomplete behaviour
get Playwright e2e. Both are added BEFORE implementation per
Constitution §IV.

**Clarification 2026-05-22 (1)**: only ids that exist in the live
corpus can be selected. The "not found" path has been removed.

**Clarification 2026-05-22 (2)**: the navigator surface is the
EXISTING `<SearchBar>` extended with an `id:` operator, NOT a
separate `<PosterIdInput>` component. Tasks below reflect that
shape.

**Organization**: Tasks are grouped by user story (US1, US2) so each can be
implemented + verified independently. US1 alone is a complete MVP.

## Path Conventions

- All work lives under `site/` (SvelteKit project).
- No Python changes; no parquet rebuild.

---

## Phase 1: Setup

- [X] T001 Create stub `site/src/lib/goto_poster.ts` exporting only the type definitions (`Suggestion`, `SuggestionResult`) and empty function signatures (`parseIdOperator`, `normaliseQuery`, `filterSuggestions`) from `specs/014-poster-id-nav/data-model.md` §"Pure-function module". No implementation bodies yet — just the type surface so vitest tests can import.
- [X] T002 In `site/src/lib/components/SearchBar.svelte`, add the new `abstractsByPosterId` prop (typed `Map<number, AbstractRecord>`) with a fallback to `new Map()` for backwards-compat, and a placeholder `mode-change` dispatcher. No behavior yet — just the prop surface and a TODO comment pointing to T007.

## Phase 2: Foundational

*No cross-story foundational work required — the home/permalink pages already
maintain `abstractsByPosterId` and route mounting is unchanged.*

---

## Phase 3: US1 — `id:` operator in SearchBar with autocomplete dropdown (Priority: P1)

**Story goal**: A user types `id:<digits>` in the existing search
bar, sees a live suggestion list of matching available ids (the
normal result list is hidden), picks one, and lands on its
permalink. The user CANNOT submit an id that doesn't exist.

**Independent test**: Open the home page, type `id:2094` → the
listbox shows exactly one entry (`2094`), the result list is
hidden, press Enter, observe navigation to `/abstract/2094/`. Then
type `id:12` → listbox shows `0012`, `0120`-`0129`, `1200`-`1299`
(sampled), but NOT `1012` or `0212`. Then type `id:9999` → "No
matching posters" hint renders. Backspace until `id:` is gone →
result list re-renders.

### Tests (write FIRST, must fail before implementation)

- [X] T003 [P] [US1] Add `site/src/tests/unit/goto_poster.test.ts` with vitest cases covering EVERY branch of `parseIdOperator`, `normaliseQuery`, `filterSuggestions` per `contracts/id-search-mode.md` §"Test contract" item 1: case-insensitive `ID:34` → `"34"`, embedded `... id:34` → `null`, `topic:x` → `null`, `id:` → `""`, `id` (no colon) → `null`; `normaliseQuery("0345")` → `"345"`; prefix `"12"` against a fixture map with ids `{12, 121, 129, 212, 1012, 1200, 1299, 2094}` returns `{12, 121, 129, 1200, 1299}` and explicitly excludes `212` and `1012`; an exact-match `"2094"` returns `total: 1, exactMatch.posterId === 2094`; `"9999"` returns `total: 0`; the 10-row `limit` is honored; `visible` is sorted ascending by `posterId`. Initially fails because implementations are stubs.
- [X] T004 [P] [US1] Add `site/src/tests/e2e/goto_poster.spec.ts` with Playwright cases 1-6 from `contracts/id-search-mode.md` §"Test contract": (1) `id:2094` exact-match navigates, (2) `id:12` dropdown includes/excludes the right ids, (3) `id:9999` shows "No matching posters" and Enter is no-op, (4) `id:` shows the "type a poster number" hint, (5) Backspacing the `id:` prefix exits navigator mode + result list re-renders, (6) click on an `<li>` navigates.

### Implementation

- [X] T005 [US1] Implement `parseIdOperator(raw)` in `site/src/lib/goto_poster.ts` per `data-model.md` §"Activation rule" (regex `^id:` case-insensitive at start, capture rest). Re-run vitest — `parseIdOperator` cases turn green.
- [X] T006 [US1] Implement `normaliseQuery(payload)` + `filterSuggestions(payload, map, limit = 10)` per `data-model.md` §"Matching rule" (drop non-digits, strip leading zeros, `id.toString().startsWith(q)`, sort, slice, exactMatch). Re-run vitest — remaining cases turn green.
- [X] T007 [US1] Extend `site/src/lib/components/SearchBar.svelte` to derive `inNavigatorMode` from `parseIdOperator(value)`, dispatch `mode-change`, render the listbox overlay matching the DOM contract in `contracts/id-search-mode.md` (combobox attrs on the input ONLY while in nav mode; `role="listbox"` + `role="option"` rows; hint / empty / overflow LIs). Wire keyboard: ArrowDown / ArrowUp / Enter / Escape per the behavior contract. Non-digit characters in the payload portion pass through visually but are filtered out of the match string.
- [X] T008 [US1] In `site/src/routes/+page.svelte`, pass the existing `abstractsByPosterId` prop into `<SearchBar>` and listen for `mode-change` events — when `navigator: true`, hide the result list (toggle a `class="hidden"` or `{#if !navigatorMode}` guard around the `<ResultList>`); when `navigator: false`, show it again.
- [X] T009 [US1] In `site/src/routes/abstract/[poster_id]/+page.svelte`, mount `<SearchBar>` in the header strip next to the back-to-home link, bound to the same URL `?q=` parameter (or a local writable mirrored to the URL). The permalink page's listener for `mode-change` simply lets the SearchBar overlay the listbox; there's no result list to hide on this route.

**Verification before merging US1**: vitest + Playwright cases 1-6 all
green; `pnpm check` reports 0 new errors; `pnpm build` succeeds.

---

## Phase 4: US2 — Keyboard shortcut focuses the input (Priority: P2)

**Story goal**: Pressing `g` from anywhere on the home or permalink
page focuses the SearchBar AND inserts the `id:` prefix. Ignored when
any input is already focused.

**Independent test**: Load home, press `g` from any non-input area,
confirm focus moves to the SearchBar, its value becomes `id:` (cursor
at end), and the prior query is held in an undo buffer recoverable via
Escape. Then with the SearchBar already focused, press `g`: the literal
`g` lands in the input.

### Tests (write FIRST)

- [X] T010 [P] [US2] Extend `site/src/tests/e2e/goto_poster.spec.ts` with Playwright case 7: (7a) `g` shortcut from the home page focuses the SearchBar AND inserts `id:` at the end; (7b) the prior search query is preserved in the undo buffer and Escape restores it before any other key is pressed; (7c) `g` while focus is in ANY input (e.g. SearchBar itself, or DetailPanel inputs) is a no-op — the literal `g` lands in the focused input. (7d) Repeat 7a on the permalink page.

### Implementation

- [X] T011 [US2] Register the `g` shortcut at the route level. Add an `onMount` block to both `site/src/routes/+page.svelte` AND `site/src/routes/abstract/[poster_id]/+page.svelte` that subscribes to `window.addEventListener('keydown', ...)`; guard `document.activeElement` against `HTMLInputElement`, `HTMLTextAreaElement`, or `[contenteditable="true"]` and return early; otherwise (a) save the current `<SearchBar>` value to an `undoBuffer` writable, (b) set the SearchBar value to `id:`, (c) focus `[data-testid="search-input"]` and put the cursor at end. Listen for Escape ONLY while in nav mode AND the undoBuffer is non-empty: restore + clear buffer. Detach on `onDestroy`.
- [X] T012 [US2] Add a small visible hint near the SearchBar on the home page: `<kbd>g</kbd> for poster id`, rendered when the SearchBar is NOT focused. Keep it CSS-only (no `aria-keyshortcuts` for now — the hint plus existing `<label>` is enough for screen readers).

**Verification before merging US2**: Playwright cases 4–5 green; the
shortcut hint renders on the home page; manual smoke confirms `g`
doesn't fire from inside the SearchBar.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T013 [P] Re-run the full vitest unit suite (`pnpm exec vitest --run src/tests/unit`) — must stay 103+ passing + the new goto_poster tests.
- [X] T014 [P] Re-run `pnpm check` from `site/` — must remain 0 errors.
- [X] T015 [P] Re-run `pnpm build` from `site/` — must succeed; verify the static build still emits the same prerendered HTML for `/` and `/abstract/[poster_id]/`.
- [ ] T016 Verify accessibility manually: tab order reaches the SearchBar, focus ring visible, combobox semantics (`aria-expanded` toggling, `aria-activedescendant` on Arrow keys) announced correctly by VoiceOver (macOS) or NVDA (Windows). Record findings in the PR description.
- [X] T017 ~~Update `site/src/routes/about/+page.svelte`'s search-operator list~~ — discovered the About page narrates the stack in prose but does NOT enumerate operators. Operators live in the SearchBar's `?` help popover, which T007 updated to include `id:1234 — jump to a specific poster id (autocomplete suggests available ids only)`. CA-003 satisfied by the popover update.
- [ ] T018 Open the PR for `014-poster-id-nav` against `main` with a description that lists US1 + US2 acceptance scenarios + the 5 success criteria from `spec.md` §"Measurable Outcomes". Confirm CI (`pr-preview`, `audit`, `pr-preview-e2e`) all green before merge.

---

## Dependencies & Story Completion Order

- **US1 is independently mergeable** (MVP). The component + route mounts work without the keyboard shortcut.
- **US2 depends on US1** (the input must exist before the shortcut can focus it). Implement US2 only after US1 is verified.
- Within US1: T003 + T004 (tests) MUST come before T005–T009 (implementation). T005 → T006 (validate depends on parse) → T007 (component uses both) → T008 + T009 (route mounts can be parallel once T007 lands).
- Polish phase (T013–T018) gates merge; do not skip.

## Parallel Execution Hints

- T001 + T002 in setup — different files, no dependencies.
- T003 + T004 — different test files, both unblocked once T001+T002 land.
- T008 + T009 — different route files; can land together.
- T013 + T014 + T015 — independent verification steps, run concurrently.

## Implementation Strategy

1. **Land setup (T001 + T002)** — establishes the file scaffolding so tests can import.
2. **Land failing tests (T003 + T004)** — vitest + e2e both red.
3. **Implement US1 (T005 → T009)** — drive tests green, ship MVP. Open the PR here if time-pressured; US1 alone fulfills the spec's P1 story.
4. **Implement US2 (T010 → T012)** — add the keyboard shortcut on top.
5. **Polish (T013 → T018)** — type-check, build, manual a11y, About update, PR.

## Notes

- No Python, no parquet, no new external deps. Constitution §VII honored: the valid-id set is read from the in-memory `abstractsByPosterId` map at runtime.
- Tests-first ordering matches Constitution §IV.
