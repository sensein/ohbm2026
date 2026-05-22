# Feature Specification: Navigate posters by ID

**Feature Branch**: `014-poster-id-nav`
**Created**: 2026-05-22
**Status**: Draft
**Input**: User description: "add an option to the ui to navigate/select posters by poster id."

## Clarifications

### Session 2026-05-22

- Q: How should the input restrict selection to available ids? → A: Autocomplete dropdown showing only ids that exist in the live corpus. Free-typing an unmatched id is structurally impossible: the submit affordance stays disabled until the value resolves to exactly one available id.
- Q: With autocomplete, what does typing `12` match? → A: PREFIX match on the integer string (after stripping leading zeros from the query). `12` matches ids whose decimal string starts with `12`: `12`, `120–129`, `1200–1299`. It does NOT match `1012`, `0212`, or any id whose integer string contains `12` only mid-position. Trimmed query `12` therefore surfaces displayed forms `0012`, `0120`–`0129`, and `1200`–`1299`.
- Q: Should the navigator live in a separate input or in the existing search bar? → A: Reuse the existing search bar via an `id:` operator. Typing `id:` at the start of the search query puts the bar into "poster navigator" mode: the normal result list hides and an autocomplete dropdown of available ids appears under the bar. Selecting one (Enter / click) navigates to its permalink. Other operators in the same query are ignored while in this mode. No separate `<PosterIdInput>` component is created.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — `id:` operator in the search bar (Priority: P1)

A conference attendee standing in front of physical poster `1234` opens the
Atlas, types `id:1234` into the existing search bar, and lands on that
abstract's permalink page. Same for an organizer scanning a printed program
by number.

**Why this priority**: Today the only way to reach a specific poster is to
search by title fragment + scroll, OR remember the URL pattern
`/abstract/1234/`. Neither works for the dominant in-person use case where
the user already knows the number and wants the metadata in two seconds.
Reusing the existing search bar avoids adding a second input element and
keeps the on-page chrome minimal.

**Independent Test**: Open the home page, type `id:` into the search bar
followed by a few digits, observe an autocomplete dropdown of every existing
poster id that prefix-matches the typed digits (the normal result list is
suspended while in this mode). Pick one with Enter / click; the browser
lands on the corresponding `/abstract/<id>/` permalink. The dropdown
never offers a value that does not match an available id.

**Acceptance Scenarios**:

1. **Given** the home page is loaded and the user knows poster id `2094`,
   **When** the user types `id:2094` (or `id:02094` with leading zero) into
   the search bar and presses Enter,
   **Then** the dropdown collapses to the single exact match `2094` and
   the browser navigates to `/abstract/2094/`.
2. **Given** the user has typed `id:12` into the search bar,
   **When** the dropdown renders,
   **Then** it lists every existing id whose integer string starts with
   `12` (e.g. `0012`, `0120`–`0129`, `1200`–`1299`), sorted ascending by id
   and capped at 10 visible rows with a "+ N more" footer if more matches
   exist. It does NOT list `1012`, `0212`, or any id whose decimal form
   merely contains `12` mid-position.
3. **Given** the user has typed `id:9999` (or any digits with no matching
   available id),
   **When** the dropdown renders,
   **Then** it shows a "No matching posters" hint and pressing Enter is a
   no-op.
4. **Given** the user has typed only `id:` (no digits),
   **When** the dropdown renders,
   **Then** it shows a brief "type a poster number" hint; pressing Enter
   does nothing.
5. **Given** the user types `id:` followed by any digits,
   **When** the navigator mode is active,
   **Then** the normal result list is hidden and the home page's other
   filters / facets are ignored. Backspacing the `id:` prefix out of the
   query immediately restores the normal result list.
6. **Given** the user is on the permalink page reached via this operator,
   **When** they press the browser back button,
   **Then** they return to the home page with the search bar still
   containing `id:<last-query>` so the next jump is one keystroke away.

---

### User Story 2 — Keyboard-driven quick jump to navigator mode (Priority: P2)

A power user (organizer, reviewer) wants to navigate the corpus by poster
number quickly without taking hand off the keyboard.

**Why this priority**: P2 because the P1 input already covers the primary
use case; this is a power-user accelerator. Organizers reviewing 50+ posters
in sequence benefit a lot, casual attendees not at all.

**Independent Test**: From the home page, press a designated keyboard
shortcut (`g`), confirm the search bar gains focus AND its value is
replaced with the prefix `id:` (cursor positioned after the colon),
type a number, press Enter, confirm navigation. Repeat from the
permalink page.

**Acceptance Scenarios**:

1. **Given** the home or permalink page is loaded and no input is focused,
   **When** the user presses `g`,
   **Then** the search bar receives focus, its current value is replaced
   with `id:` (cursor at end), and any pre-existing query is preserved
   in an undo buffer so the user can press Escape to restore it.
2. **Given** focus is in the search bar already in navigator mode,
   **When** the user types `1234` and presses Enter,
   **Then** the browser navigates to `/abstract/1234/`.
3. **Given** focus is in ANY input/textarea/contenteditable (including the
   search bar itself),
   **When** the user presses `g`,
   **Then** the shortcut does NOT trigger — the literal `g` character lands
   in whatever input has focus.

---

### Edge Cases

- **Leading zeros in payload**: `id:0001`, `id:01`, `id:1`, `id:001`
  MUST all be treated as query integer `1`; the suggestion list shows
  ids that prefix-match `1` (i.e. `1`, `10–19`, `100–199`,
  `1000–1999`).
- **Out-of-range / non-existent ids**: ids outside the 1–3333
  conference range, or in-range but not in the corpus (e.g.
  withdrawn), are simply absent from the suggestion list. Pressing
  Enter is a no-op. Withdrawn posters NEVER appear — the underlying
  `abstractsByPosterId` map already excludes them.
- **Non-digit characters in payload**: non-digit characters pass
  through to the search bar visually (so the user sees what they
  typed) but are filtered out of the digit string used for matching.
  E.g. `id:12 3` matches the same set as `id:123`.
- **Mode boundary**: only `id:` AT THE START of the query
  (case-insensitive) activates navigator mode. `... id: ...`
  embedded inside a normal query is treated as plain text.
- **Operator interaction**: while navigator mode is active, other
  search operators (`topic:`, `methods:`, etc.) in the same query
  are ignored. Backspacing out of `id:` immediately restores the
  full pre-mode behaviour.
- **Direct URL access**: pasting `/abstract/9999/` into the address
  bar routes through the existing permalink-page lookup; the search
  bar is unrelated to that path.
- **Accessibility**: the search bar MUST keep its existing keyboard
  reachability AND adopt combobox semantics (`role="combobox"`,
  `aria-expanded`, `aria-controls`, `aria-activedescendant`) while
  in navigator mode. The `aria-live` region announces the current
  suggestion count.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The existing `<SearchBar>` MUST recognize an `id:`
  operator at the start of the query and switch into "poster
  navigator" mode while present.
- **FR-002**: On submission of a navigator-mode query that resolves to
  exactly one available id (via exact integer match or via picking the
  only remaining suggestion), the application MUST navigate to the
  abstract permalink for that poster id.
- **FR-003**: The operator's digit payload MUST accept leading zeros
  (`id:0345`, `id:345`, `id:00345` all equivalent) and surrounding
  whitespace stripped before matching.
- **FR-004**: The suggestion dropdown MUST contain ONLY ids that exist
  in the loaded `abstractsByPosterId` map; ids that do not exist
  (out-of-range, withdrawn, or otherwise absent) MUST NOT appear. When
  the current digit payload does not resolve to exactly one available
  id, Enter MUST be a no-op (no navigation, no error toast).
- **FR-005**: Non-digit characters in the payload portion MUST be
  silently ignored — they pass through to the search bar as plain
  characters but are filtered out of the digit string used for
  matching.
- **FR-006**: Backspacing the `id:` prefix out of the query MUST
  exit navigator mode in the same render cycle and restore the
  normal search/result behavior.
- **FR-007**: Navigator mode MUST be keyboard accessible: combobox
  semantics on the search bar (`role="combobox"`, `aria-expanded`,
  `aria-controls`, `aria-activedescendant`), `aria-live` region
  announcing the suggestion count, visible focus ring, and
  navigation via Arrow keys + Enter + Escape.
- **FR-008**: A keyboard shortcut (`g`) MUST give the search bar
  focus from anywhere on the home or permalink pages AND insert the
  `id:` prefix; the user's prior query (if any) is held in an undo
  buffer and restored on Escape before any other key is pressed.
  The shortcut MUST be ignored when any input / textarea /
  contenteditable element already has focus.
- **FR-009**: Matching MUST be purely client-side against the
  in-memory `abstractsByPosterId` map; no additional network calls
  are triggered on keystroke or submit.
- **FR-010**: Suggestion match rule: digit payload, after stripping
  leading zeros, is treated as a string `q`; an id is included iff
  `id.toString().startsWith(q)`. The list is sorted ascending by id
  and capped at 10 visible rows with a "+ N more" footer when more
  matches exist.

### Key Entities

- **Poster id**: a positive integer in the range 1–3333 stored as `int16`
  in the corpus. Display layer renders it zero-padded to 4 digits
  (`0345`); the URL accepts the un-padded integer (`/abstract/345/`).
- **Available ids**: the set of poster ids actually present as keys in
  the loaded `abstractsByPosterId` map (already excludes withdrawn
  abstracts). This is the ONLY source of truth for the autocomplete
  dropdown; the spec NEVER hard-codes the set or its size.
- **Navigator-mode query**: the search bar value when it starts with
  `id:` (case-insensitive). The text after the colon, with leading
  zeros and non-digits stripped, is the digit string used for
  matching.
- **Suggestion list**: the subset of available ids whose decimal-string
  form starts with the digit string, sorted ascending, capped at 10
  visible entries (a footer indicates the count of additional matches
  when the list overflows). Each suggestion carries its 4-digit
  padded display string and the poster title for orientation.

### Constitution Alignment *(mandatory)*

- **CA-001**: No Python execution is added by this feature. All existing
  python development MUST continue to run through `.venv/bin/python` or
  `uv` targeting it.
- **CA-002**: Each story MUST land at least one failing test BEFORE the
  implementation that satisfies it. US1 needs a vitest unit (input
  parsing + error states) and a Playwright e2e (full navigation flow).
  US2 needs a Playwright e2e covering the keyboard shortcut on both the
  home and permalink pages.
- **CA-003**: This feature changes only the SvelteKit UI surface
  (specifically `SearchBar.svelte`, `+page.svelte`, and the permalink
  route); no canonical pipeline defaults shift. The About page
  documents the existing operator list (`topic:`, `methods:`, etc.);
  the new `id:` operator MUST be added there in the same change.
- **CA-004**: No new credentials.
- **CA-005**: No new datasets, caches, exports, or downloaded assets.
- **CA-006**: The "no matches" path MUST be explicit: the dropdown
  surfaces a visible "No matching posters" hint AND the submit
  affordance is visibly disabled. The handler MUST NOT silently
  no-op without communicating the state.
- **CA-007**: The corpus of valid ids MUST be discovered at runtime from
  the loaded abstracts envelope (not hard-coded). When the corpus
  state-key changes, the set of valid ids changes with it without code
  changes.
- **CA-008**: No new organizer-facing artifacts; provenance unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A conference attendee can navigate from "home page loaded"
  to "abstract permalink visible" in ≤ 5 seconds (median) when they
  already know the poster number.
- **SC-002**: 100% of valid accepted-abstract ids in the live corpus
  (3,240 ids in the 1ba5a9ea1efe state-key build) resolve to the right
  permalink via the input.
- **SC-003**: Suggestion list updates within 100 ms of any keystroke
  (synchronous filter over the in-memory `abstractsByPosterId` map —
  no network round-trip). When no available id matches the query the
  list displays "No matching posters" within the same budget.
- **SC-004**: The input is reachable via keyboard tab order and works
  with a screen reader on at least one major OS/screen-reader pair
  (e.g. macOS + VoiceOver, Windows + NVDA).
- **SC-005**: The Playwright e2e suite for the feature passes on Chromium
  for all acceptance scenarios in both US1 and US2.

## Assumptions

- Users either know the poster number from physical signage at the
  conference, the printed program, or a colleague's recommendation. The
  feature does NOT include barcode/QR scanning or any kind of fuzzy
  poster lookup.
- The 1–3333 conference range is stable for OHBM 2026 (no last-minute
  poster renumberings post-deploy).
- The existing `/abstract/<poster_id>/` permalink route is unchanged and
  handles the underlying navigation. This feature only adds the entry
  surface, not the destination page.
- The Atlas data package (parquet) is fully loaded before the user
  interacts with the input; the input MAY be disabled with a "Loading…"
  hint until the abstracts envelope is in memory.
- The home page and permalink page are the only routes where this input
  is mounted in v1. The About / cart / tour surfaces are out of scope.
