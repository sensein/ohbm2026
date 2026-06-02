---

description: "Task list — Cart-only filter, search selection & lasso parity on atlas-root + neuroscape"
---

# Tasks: Cart-only filter, search selection & lasso parity on atlas-root + neuroscape

**Input**: Design documents from `specs/021-atlas-cart-lasso/`
**Prerequisites**: plan.md, spec.md (incl. Clarifications 2026-06-01), research.md, data-model.md, contracts/

**Tests**: INCLUDED — every story is a behavior/UI change, so each ships failing tests first (Vitest unit in jsdom, run with `vitest run`; Playwright e2e). No Python in scope, so CA-001 venv tasks are N/A (noted in Setup).

**Organization**: Grouped by user story. All paths are under `site/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 (maps to spec.md user stories); Setup/Foundational/Polish carry no story label
- Same file (`+page.svelte`, `UmapPanel.svelte`) ⇒ NOT parallel across tasks

## Path Conventions

Web frontend, single SvelteKit project at `site/`. Source in `site/src/`, tests in `site/src/tests/{unit,e2e}/`. Run from `site/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the toolchain and create stable import paths for the new pure helpers.

- [x] T001 Ensure the site toolchain is ready and the baseline is green: `cd site && pnpm install`, then confirm `pnpm exec vitest run` and `pnpm test:e2e` execute (record baseline). NOTE: no Python in this feature — CA-001 venv tasks are N/A.
- [x] T002 [P] Create `site/src/lib/selection/` with stub modules `compose.ts` and `cart_scope.ts` (exported typed signatures only, no logic) so later parallel tasks have stable import paths.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The pure intersection composer shared by all three stories.

**⚠️ CRITICAL**: US1/US2/US3 all consume `compose()`; complete this phase first.

- [x] T003 [P] Write FAILING unit test `site/src/tests/unit/selection_compose.test.ts` for `compose(parts)` per `contracts/selection-composition.md` C1–C6 (all-null→null; single active→identity; intersection; inactive=identity; active-empty forces empty; result ⊆ corpus).
- [x] T004 Implement `compose(parts: Array<Set<number> | null>): Set<number> | null` in `site/src/lib/selection/compose.ts` to pass T003.

**Checkpoint**: Shared composer ready — user stories can begin.

---

## Phase 3: User Story 1 — "Cart only" filter on every site (Priority: P1) 🎯 MVP

**Goal**: Rename "Saved only" → "Cart only" everywhere, add it to atlas-root + neuroscape, switch composition to intersection (cart is a participating filter, not a dominant override), and show the facet-style cross-site warning + empty states.

**Independent Test**: With a mixed cart, toggle "Cart only" on `/neuroscape/` → only neuroscape saved items show, warning reports the hidden count; OHBM control reads "Cart only" and composes with search/facets instead of overriding them.

### Tests for User Story 1 (write first, ensure they FAIL) ⚠️

- [x] T005 [P] [US1] FAILING unit test `site/src/tests/unit/cart_scope.test.ts` for `savedInCorpus(cartItems, indexHas, mode)` per `contracts/cart-only-filter.md` (F2 membership; per-mode hidden counts; W4 atlas-root hides neither; W5 unknown kind counted + named).
- [x] T006 [P] [US1] Extend `site/src/tests/unit/selection_compose.test.ts` to assert cart-as-intersecting-term: cart off ⇒ identity; cart on ⇒ narrows with search/facets/lasso (encodes the OHBM cart-dominant→intersection behavior change).
- [x] T007 [P] [US1] FAILING e2e `site/src/tests/e2e/cart_only_parity.spec.ts`: neuroscape "Cart only" filters to neuroscape saved items + shows hidden-count warning; empty states E1 (cart empty) and E2 (saved but none here); OHBM toggle label reads "Cart only" / "✓ Cart". Also assert **FR-005 live update** (add/remove a cart item while the filter is active → view updates without reload) and **SC-003 latency** (the toggle/cart-mutation re-filter completes < 1 s on the neuroscape corpus — measured in the e2e).

### Implementation for User Story 1

- [x] T008 [US1] Implement `savedInCorpus(...)` in `site/src/lib/selection/cart_scope.ts` (returns `{ shown: Set<number>; hiddenCount: number; hiddenKinds: string[] }`) to pass T005.
- [x] T009 [P] [US1] Update the `cartOnly` doc comment in `site/src/lib/stores/selection.ts`: "Show only saved" → "Cart only"; note it is now an intersecting filter, not a dominant override.
- [x] T010 [US1] OHBM composition in `site/src/routes/+page.svelte`: replace the `$cartOnly ? cartIds : intersect(...)` dominant ternary (~:434) with `compose([effectiveSearchIds, $lassoSelection, facetIds, authorChipIds, cartIds])`; add `cartIds` to `preFilterForFacetCounts` (~:437); rewrite the ~:427–433 comment to describe intersection semantics.
- [x] T011 [US1] Atlas/neuroscape composition in `site/src/routes/+page.svelte`: add per-mode `cartOnly` state; when on, narrow `filteredBackdrop`/`filteredOverlay` (and the scatter feed) by `savedInCorpus().shown` via `compose`; derive `hiddenCount`/`hiddenKinds` from the loaded corpus indexes (`abstractsByPosterId`/`listCorpusById`/`atlasOverlayById`).
- [x] T012 [US1] Rename the OHBM toggle in `site/src/routes/+page.svelte` (~:2338–2353): label "Saved only"→"Cart only", active "✓ Saved"→"✓ Cart", update `title`; keep `data-testid="toggle-cart-only"`; update the OHBM-home-only gating comment.
- [x] T013 [US1] Add a "Cart only" toggle to atlas-root + neuroscape (in `site/src/lib/components/AtlasRootFacets.svelte` and `site/src/lib/components/NeuroscapeFacets.svelte`, or the atlas home header in `+page.svelte`), wired to the per-mode state, `data-testid="toggle-cart-only"`, disabled when the cart is empty and the filter is off.
- [x] T014 [P] [US1] Render the cross-site warning (W1–W5) and empty states (E1–E3) in `site/src/lib/components/NeuroscapeBrowsePanel.svelte` and `site/src/lib/components/AtlasRootBrowsePanel.svelte`, driven by `hiddenCount`/`hiddenKinds` props passed from `+page.svelte`.

**Checkpoint**: "Cart only" works on all three sites with intersection semantics + warning; MVP is shippable.

---

## Phase 4: User Story 2 — Search-driven selection on atlas-root + neuroscape (Priority: P2)

**Goal**: Search results highlight on the scatter (not just filter the list) and can be bulk-added to the cart. Bulk-add already exists; the gap is exposing the panel's matched set so the scatter highlights it.

**Independent Test**: Query on `/neuroscape/` → matching scatter points highlighted, list reflects matches; bulk "Add N to cart" adds exactly the matched set.

**Dependency note**: builds on the T010–T011 highlight-set plumbing but is testable on its own (search highlights even with no lasso/cart active).

### Tests for User Story 2 (write first, ensure they FAIL) ⚠️

- [ ] T015 [P] [US2] FAILING unit test `site/src/tests/unit/panel_matched_ids.test.ts`: `NeuroscapeBrowsePanel`/`AtlasRootBrowsePanel` expose their final matched-id set (binding/event) for a fixture corpus + query (R-003 single source of truth).
- [x] T016 [P] [US2] FAILING e2e (search section of `site/src/tests/e2e/selection_highlight.spec.ts`): query on neuroscape highlights matching scatter points; bulk "Add N to cart" adds the matched set.

### Implementation for User Story 2

- [x] T017 [P] [US2] Expose the matched-id set from `site/src/lib/components/NeuroscapeBrowsePanel.svelte` (e.g. `bind:matchedIds` or `dispatch('results', ids)`) sourced from its existing `filtered`.
- [x] T018 [P] [US2] Expose the matched-id set from `site/src/lib/components/AtlasRootBrowsePanel.svelte` the same way.
- [x] T019 [US2] In `site/src/routes/+page.svelte`, fold the panel's matched-id set into the composed highlight set (search ∩ lasso ∩ cart ∩ facets) and feed it to `UmapPanel` (extend the existing lasso-set props or add a `highlightSet` prop).
- [x] T020 [US2] In `site/src/lib/components/UmapPanel.svelte`, ensure the fed highlight set drives the 2D highlight (search matches reuse the same `selectedpoints` path as lasso).

**Checkpoint**: Search highlights on the scatter and feeds the cart on atlas-root + neuroscape.

---

## Phase 5: User Story 3 — Selection highlight visibility (2D contrast + 3D) (Priority: P3)

**Goal**: Per the 2026-06-01 clarification — keep the 2D `selectedpoints` mechanism but cap unselected opacity below selected when a selection is active (fix the zoom wash-out); add the selection highlight to 3D via an in-place restyle (no `Plotly.react`).

**Independent Test**: Draw a 2D lasso and zoom in → enclosed points stay distinct (unselected stays below a ceiling, selected stays 1.0); switch to 3D → selection reflected; a render/trace-count probe confirms no `Plotly.react` on selection change; mobile lasso disabled with a note.

### Tests for User Story 3 (write first, ensure they FAIL) ⚠️

- [x] T021 [P] [US3] FAILING unit test `site/src/tests/unit/selection_opacity.test.ts`: the selected/unselected opacity-gap helper keeps `unselected < selected (=1.0)` across the full `densityZoomOpacity` / zoom-factor range when a selection is active, and equals base when no selection (H2/H3/H4).
- [ ] T022 [P] [US3] FAILING e2e (highlight section of `site/src/tests/e2e/selection_highlight.spec.ts`): 2D lasso + zoom keeps the contrast gap; 3D reflects the selection; render/trace-count probe asserts no `Plotly.react` on selection change (H6); mobile lasso disabled with a visible note (B3); and (FR-013) the "Cart only" cross-site warning stays reachable + legible at the mobile width.

### Implementation for User Story 3

- [x] T023 [P] [US3] Add the pure selected/unselected opacity-gap helper to `site/src/lib/atlas/opacity.ts` (e.g. `unselectedOpacity(base, selectionActive)` → `selectionActive ? min(base, cap) : base`) to pass T021.
- [x] T024 [US3] In `site/src/lib/components/UmapPanel.svelte` `applyAtlasZoomOpacity` (~:1155–1159): when a selection is active, set `unselected.marker.opacity` to the capped (gap) value while `selected.marker.opacity` stays 1.0; retain `unselected == base` when no selection. (2D fix — keep `selectedpoints`.)
- [x] T025 [US3] In `site/src/lib/components/UmapPanel.svelte` `renderAtlasChart3D` (~:1945/1953): apply the selection highlight via an in-place `Plotly.restyle` of a precomputed per-point `marker.opacity` array (selected→1.0, unselected→density-dim); NO `Plotly.react`, no trace-count change. Run the H7 spike — if `marker.opacity` recreates the WebGL context, fall back to a precomputed `marker.color` rgba array.
- [ ] T026 [US3] Add the mobile "lasso available on larger screens" note where 2D dragmode falls back to `pan` (in `UmapPanel.svelte` and/or `+page.svelte`), ensuring no partial selection (FR-012/FR-013).

**Checkpoint**: Selection stays visible at all zooms in 2D and is reflected in 3D, within the resource budget.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T027 [P] Docs: update the README UI section and `memory/{search_unification,stage15_atlas_subsites,stage19_semantic_search}.md` for the rename, the cart-dominant→intersection change, the cross-site warning, and the 2D-contrast + 3D-highlight behavior (CA-003).
- [ ] T028 Update any existing test that asserted the OHBM cart-dominant override to the new intersection behavior (e.g. `site/src/tests/e2e/cart.spec.ts`, `site/src/tests/unit/filter.test.ts`) — do not weaken assertions; re-express them.
- [ ] T029 Run `cd site && pnpm check && pnpm lint`; fix type/lint issues.
- [ ] T030 Run the full suites: `cd site && pnpm exec vitest run && pnpm test:e2e`; confirm green including the no-`Plotly.react` probe.
- [ ] T031 Run `.specify/scripts/bash/constitution-check.sh --full`; verify no committed data/secrets and no new gitignored-root writes (this is a UI-only change; localStorage only).
- [ ] T032 Run `specs/021-atlas-cart-lasso/quickstart.md` verification across all three modes (`VITE_SITE_MODE=atlas-root|neuroscape|ohbm2026`).
- [ ] T033 [P] Add a combined-intersection e2e (in `site/src/tests/e2e/selection_highlight.spec.ts` or `cart_only_parity.spec.ts`) covering **SC-008**: search + lasso + facets + "Cart only" all active at once → the result list, facet counts, AND scatter highlight each show exactly the four-way intersection, with no filter clobbering another. (Cross-cutting — runs after US1+US2+US3.)
- [ ] T034 Verify **FR-014** drift detection still fires: add/keep a test asserting the cross-parquet drift banner surfaces (never a silent partial result) when "Cart only" or lasso resolves a selection against sibling-parquet geometry, after the filter/highlight changes land.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)** → no deps.
- **Foundational (P2)** → after Setup; `compose()` BLOCKS all stories.
- **US1 (P3)** → after Foundational. Independent, shippable MVP.
- **US2 (P4)** → after Foundational; soft-depends on the US1 highlight-set plumbing in `+page.svelte` (T010–T011/T019 same file) but is independently testable.
- **US3 (P5)** → after Foundational; independent of US1/US2 (operates on whatever highlight set is fed — lasso alone suffices to test).
- **Polish (P6)** → after the desired stories.

### Within each story

- Tests (T0xx) written first and FAIL before implementation.
- Pure helpers (`compose.ts`, `cart_scope.ts`, `atlas/opacity.ts`) before the components/route that consume them.
- `+page.svelte` and `UmapPanel.svelte` tasks are sequential within their file (no [P] across them).

### Parallel opportunities

- T002 (setup stub) ∥ nothing blocking.
- US1 tests T005/T006/T007 in parallel; T009 (selection.ts doc) ∥ T008 (cart_scope.ts); T014 (panels) ∥ the +page tasks only if different files (T014 is panels, T010–T013 are +page → T014 ∥ T010–T013).
- US2 tests T015/T016 in parallel; T017 ∥ T018 (different panel files).
- US3 tests T021/T022 in parallel; T023 (opacity.ts) ∥ tests.
- Across stories: once Foundational is done, US3 (UmapPanel + opacity.ts) can proceed in parallel with US1 (mostly +page + panels + selection helpers), since US3's core files differ — coordinate the shared `+page.svelte`/`UmapPanel.svelte` edits.

## Parallel Example: User Story 1

```bash
# Tests first (parallel):
Task: "FAILING unit test cart_scope.test.ts (T005)"
Task: "Extend selection_compose.test.ts for cart term (T006)"
Task: "FAILING e2e cart_only_parity.spec.ts (T007)"

# Then non-conflicting impl in parallel:
Task: "Implement cart_scope.ts savedInCorpus (T008)"
Task: "Update cartOnly doc in selection.ts (T009)"
```

## Implementation Strategy

### MVP first (US1 only)
1. Phase 1 Setup → 2. Phase 2 Foundational (`compose`) → 3. Phase 3 US1 → **STOP & validate** (Cart only + warning on all three sites) → deploy/demo.

### Incremental delivery
1. Setup + Foundational → ready.
2. US1 → test → deploy (MVP: rename + cross-site Cart-only + intersection).
3. US2 → test → deploy (search highlights + feeds cart).
4. US3 → test → deploy (highlight visible at zoom + in 3D).

## Notes

- Run unit tests with `vitest run` (never watch — see `memory/feedback_vitest_run_mode.md`); watch long-running e2e via a background Monitor, not a blocking foreground watch.
- No data/caches/exports/secrets in commits; this is UI-only (localStorage only).
- Never silence failures or call `Plotly.react` on selection change to "make it work" — the no-`react` invariant is a tested guarantee (WebGL leak plotly.js#6365).
- Commit each validated slice with a descriptive message; push when complete (production deploy still requires the `deploy-production` label — see `memory/deploy_production_label_gate.md`).
