# Implementation Plan: Navigate posters by ID

**Branch**: `014-poster-id-nav` | **Date**: 2026-05-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/014-poster-id-nav/spec.md`

## Summary

Extend the existing `<SearchBar>` in the SvelteKit Atlas with an
`id:` operator. When the search query starts with `id:`
(case-insensitive), the SearchBar enters "navigator mode": the
normal result list is hidden and an autocomplete dropdown overlays
the bar, showing only ids that exist in the loaded
`abstractsByPosterId: Map<number, AbstractRecord>` and prefix-match
the typed digits (so `id:12` surfaces `12, 120-129, 1200-1299` but
NOT `1012` or `0212`). Pressing Enter on the exact match — or
clicking a suggestion — calls SvelteKit's `goto` to navigate to
`/abstract/<id>/`. The SearchBar is mounted on both the home page
and the permalink page so power users can chain jumps. A global
keyboard shortcut focuses the SearchBar and inserts the `id:`
prefix.

Per the 2026-05-22 clarifications:
- Only available ids appear in the dropdown — the "not-found" path
  doesn't exist.
- The navigator surface is the existing SearchBar, NOT a separate
  separate `<PosterIdInput>` component (a previous draft of this plan had
  the separate component; that approach is rejected).

Pure client-side; no new data shipped, no new parquet build, no
Python changes.

## Technical Context

**Language/Version**: TypeScript 5.7 + Svelte 5.16 (existing site stack).
**Primary Dependencies**: `@sveltejs/kit` 2.21, `svelte` 5.16. Already in
`site/package.json`; no additions.
**Storage**: N/A — pure UI state. The lookup hits the existing
`abstractsByPosterId: Map<number, AbstractRecord>` map already maintained
by `+page.svelte` after the data-package fetch.
**Testing**: vitest (unit, jsdom) + Playwright (e2e against the
prerendered preview deploy). Both already in `site/package.json`; reuse
the same setup files and config (`vite.config.ts` + `playwright.config.ts`).
**Target Platform**: Modern browsers (Chromium / WebKit / Firefox); the
prerendered SvelteKit site deployed to gh-pages via the existing
`deploy-ui.yml` and `pr-preview.yml` workflows.
**Project Type**: Web application (SvelteKit static site).
**Performance Goals**: Navigate from input-submit to permalink first
paint ≤ 2 s on a warm cache; validation in ≤ 200 ms (in-memory Map
lookup is microseconds; the 200 ms budget is for any re-render).
**Constraints**: Must work offline once the data package is loaded. Must
not require a parquet rebuild. Must not introduce new runtime fetches.
**Scale/Scope**: 3,240 abstracts in the current corpus (state-key
`1ba5a9ea1efe`). The `Map<number, AbstractRecord>` lookup is O(1) — no
scaling concern.

## Constitution Check

- **I. Reproducible Venv Execution** — No Python work; existing
  `.venv/bin/python` paths unaffected.
- **II. Immutable Evidence** — No data writes; no canonical artifacts
  touched.
- **III. Resumable Pipelines** — N/A (UI-only).
- **IV. Plan-First, Test-Driven** — Each story names the tests added
  BEFORE the implementation (see Phase 2 task ordering once
  `/speckit-tasks` runs). vitest covers the pure-function parse/
  validate (US1) and a Playwright e2e covers the full navigation flow
  (US1 + US2).
- **V. Secret-Safe, Reviewable** — No credentials. Commits land in
  small slices (component scaffold → wire to home → wire to permalink
  → keyboard shortcut), each with vitest passing.
- **VI. Fail Loudly** — Invalid ids surface an inline error via
  `aria-live`; the not-found path NEVER silently navigates or no-ops
  beyond the documented empty-submission case.
- **VII. Discover External State** — The set of valid poster ids is
  read from the in-memory `abstractsByPosterId` map (itself derived
  from the parquet's `abstracts` table at runtime). No hard-coded
  range table. When the corpus state-key changes, the set of valid
  ids changes automatically.
- **VIII. Provenance** — No new organizer-facing artifact produced.
- **Secrets, docs, commits** — No secrets touched. About page is
  unaffected (the input is on the home/permalink pages, not About).
  Each PR slice ships with vitest + e2e green before merging.

**Gate status**: PASS for Phase 0. Re-check at the bottom of this file
after Phase 1.

## Project Structure

### Documentation (this feature)

```text
specs/014-poster-id-nav/
├── plan.md              # this file
├── research.md          # Phase 0 — decisions
├── data-model.md        # Phase 1 — entities + validation
├── quickstart.md        # Phase 1 — dev/test commands
├── contracts/
│   └── id-search-mode.md    # Phase 1 — SearchBar contract
└── tasks.md             # Phase 2 — written by /speckit-tasks
```

### Source Code (repository root)

```text
site/
├── src/
│   ├── lib/
│   │   ├── components/
│   │   │   └── SearchBar.svelte       # MODIFIED — add id: operator + dropdown overlay
│   │   └── goto_poster.ts             # NEW — parseIdOperator + filterSuggestions
│   ├── routes/
│   │   ├── +page.svelte               # MODIFIED — listen for mode-change, hide result list in nav mode
│   │   └── abstract/[poster_id]/
│   │       └── +page.svelte           # MODIFIED — mount SearchBar in header
│   └── tests/
│       ├── unit/
│       │   └── goto_poster.test.ts    # NEW — vitest for parser + filter
│       └── e2e/
│           └── goto_poster.spec.ts    # NEW — Playwright e2e (US1 + US2)
└── (other existing files unchanged)
```

**Structure Decision**: SvelteKit web-application layout. Pure
client-side feature — no backend, no new data-package fields, no
Python changes. The existing `<SearchBar>` is extended (not
duplicated); the parse / filter logic lives in a separate
TypeScript module so vitest can unit-test it without a DOM mount.

## Complexity Tracking

*No constitution violations; table omitted.*

## Phase 0 — Research

See [research.md](research.md). Resolved questions:

- Keyboard shortcut letter — `g` (mnemonic "go to"). Single key,
  ignored when any input/textarea/contenteditable is focused.
- Input placement — the existing `<SearchBar>` is extended (no new
  component). Navigator mode activates when the query starts with
  `id:`. The bar appears on both home and permalink pages.
- Validation timing — synchronous on every keystroke; the dropdown
  refreshes within 100 ms (SC-003). Submit fires only when the
  current value resolves to exactly one available id.
- Re-mount on permalink — the SearchBar value is URL-bound
  (`?q=id:<last>`) so browser back/forward and chained jumps
  preserve state naturally.

## Phase 1 — Design & Contracts

See:
- [data-model.md](data-model.md) — the parser + filter rules and
  the read-time guarantees we rely on.
- [contracts/id-search-mode.md](contracts/id-search-mode.md) — the
  SearchBar's new `id:`-operator prop / event / DOM / a11y contract.
- [quickstart.md](quickstart.md) — dev + test command list a
  maintainer needs to verify the feature locally.

**Agent context update**: `CLAUDE.md`'s `<!-- SPECKIT START -->` /
`<!-- SPECKIT END -->` block must point at
`specs/014-poster-id-nav/plan.md` once this file lands.

## Constitution Re-Check (Post-Phase-1)

- All gates remain PASS. No new files outside `site/src/...` and
  `specs/...`.
- The contract names the verification tests added FIRST (vitest before
  the Svelte component lands; Playwright before route mounts).
- No new gitignored artifacts; no data-package change.
- No new external dependencies (KaTeX from Stage 12 stays the only
  recent add and is not used here).
