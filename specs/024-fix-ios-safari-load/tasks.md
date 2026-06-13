---

description: "Task list for fixing the OHBM atlas load failure on iPhone Safari"
---

# Tasks: Fix OHBM Atlas Load Failure on iPhone Safari

**Input**: Design documents from `/specs/024-fix-ios-safari-load/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Verification tasks ARE included — this is a behavior/UI change, and
the spec (FR-006 / CA-002) requires a failing-first check. Site unit tests run
via `vitest run` (NEVER watch mode — memory `feedback_vitest_run_mode`).
Long-running preview/CI watches run under a background monitor, never a blocking
foreground watch (memory `feedback_watch_use_monitor`).

**Organization**: Tasks are grouped by user story. The two stories are
independently testable. NOTE on ordering: US1 is the P1 MVP, but the plan
recommends landing US2's error-visibility mechanism (R1) early because it makes
US1 failures *observable* during development — see Implementation Strategy. Both
remain independently deliverable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 (Setup/Foundational/Polish carry no story label)
- All paths are under `site/` (the only code touched — client-side only)

## Path Conventions

- Web app, single existing SvelteKit project at `site/`. No `src/ohbm2026/`
  (Python) change is planned; a data-package rebuild is a contingency only.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make the `/ohbm2026/` site buildable, testable, and WebKit-emulatable locally.

- [X] T001 [P] Confirm the site toolchain and a local `ohbm2026` data channel: `cd site && pnpm install`, then copy `site/.env.example` → `site/.env.local` and set `VITE_DATA_PACKAGE_URL_*` for the `ohbm2026.parquet` channel (per `quickstart.md` + memory `local_dev_env`). Do NOT commit `.env.local` or any data (CA-005).
- [X] T002 [P] Add a Playwright WebKit + iPhone device descriptor test project under `site/` (e.g. `site/playwright.config.ts` project using `devices['iPhone 13']` / WebKit engine), wired to a preview build. No data committed; any fetched package lands under a gitignored path.
- [X] T003 [P] Confirm the `vitest run` baseline is green in `site/` (run `vitest run`, NOT `pnpm test:unit -- --run`).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: A reusable local preview + WebKit load harness that BOTH user stories' integration checks depend on.

**⚠️ CRITICAL**: The WebKit/iPhone integration tests in US1 and US2 cannot run until this harness exists.

- [X] T004 Build a reusable harness that serves the `/ohbm2026/` mobile build locally and loads it under the Playwright WebKit/iPhone project: `VITE_SITE_MODE=ohbm2026 pnpm build && pnpm preview` driven from the test runner, with the preview server started under a background monitor (memory `feedback_watch_use_monitor`). Expose a helper that navigates to the atlas URL and waits for an interactivity signal. File: `site/tests/e2e/_harness.ts` (or framework-idiomatic equivalent).

**Checkpoint**: Either story can now be implemented and verified independently.

---

## Phase 3: User Story 1 - OHBM attendee opens the atlas on an iPhone (Priority: P1) 🎯 MVP

**Goal**: `/ohbm2026/` fully loads and becomes interactive on iPhone Safari (no blank/spinner/crash); search runs and an abstract opens.

**Independent Test**: On the WebKit/iPhone harness (and a physical iPhone), load `/ohbm2026/` → corpus renders, search returns results, an abstract detail opens — within the load-time budget. Maps to spec US1 acceptance scenarios 1–3.

### Tests for User Story 1 (write FIRST, ensure they FAIL/are missing) ⚠️

- [X] T005 [P] [US1] Failing-first WebKit/iPhone load check in `site/tests/e2e/ios-ohbm-load.spec.ts`: assert the atlas reaches interactive (abstract count > 0 rendered, search input usable, one abstract detail opens). MUST FAIL initially (times out on "Loading…"). Also capture load-to-interactive time on the iPhone descriptor AND a desktop-descriptor baseline from the same harness, and assert `iphone_time ≤ desktop_baseline + 3s` (SC-002). Maps to contract `load-verification.md` + SC-001/SC-002/SC-003.
- [X] T006 [P] [US1] Unit test for the capability gate in `site/tests/unit/capability.test.ts`: with injected fakes, returns the conservative gate when `navigator.deviceMemory` is undefined + small viewport, and the permissive gate on desktop-class fakes. MUST FAIL/be missing initially. Maps to contract `mobile-rendering.md` AC-4 + data-model `DeviceCapability`.

### Implementation for User Story 1

- [X] T007 [US1] Create `site/src/lib/device/capability.ts`: pure `detectCapability()` over browser globals returning `DeviceCapability` (`webglAvailable`, `webglContextBudget`, `isSmallViewport`, `deviceMemoryGb`, `prefersReducedMotion`) + derived `allow3dByDefault` / `allowAutoRotate` / `eagerSemanticWarm`. Detected at RUNTIME — no UA/iOS-version allow-list (CA-007). Fail safe to the conservative branch when `deviceMemory` is absent (data-model validation rule). Makes T006 pass.
- [X] T008 [US1] Gate the scatter panel on capability in `site/src/lib/components/UmapPanel.svelte`: replace `show3dPane = mode === 'ohbm' || hasWebGL` (`:232`) and `autoRotate = mode === 'ohbm'` (`:247`) so that on mobile/low-budget only the 2D pane mounts by default, auto-rotate is off, and 3D is behind an explicit user toggle. Toggling 3D off MUST call the existing `destroyChart` teardown to free the WebGL context (no leak; no trace-count-changing `Plotly.react` on toggle). Preserve desktop behavior unchanged (FR-005). Maps to contract `mobile-rendering.md` rules 2–4.
- [X] T009 [US1] Make the semantic-search warm lazy in `site/src/routes/+page.svelte` (remove the unconditional `await mod.warmSemantic()` at `:314-321` from the critical path when `eagerSemanticWarm === false`) and in `site/src/lib/search/semantic.ts` warm on first search-input focus or guarded idle (`requestIdleCallback` with `setTimeout` fallback). A warm failure stays non-critical (logs with context, search degrades) — does NOT blank the page. Maps to contract `lazy-semantic-warm.md` rules 1–3.
- [X] T010 [US1] Verify the worker's WASM is delivered WebKit-safely (correct `application/wasm` MIME / no reliance on a mis-typed `instantiateStreaming` response) in `site/src/workers/semantic.worker.ts` / its load path; if a workaround is needed, label it in code with the root cause + follow-up (CA-006). Maps to contract `lazy-semantic-warm.md` rule 4.
- [X] T011 [US1] WebGL-unavailable fallback in `site/src/routes/+page.svelte` / `UmapPanel.svelte`: when `webglAvailable === false`, load the list/search experience with a clear "map unavailable on this device" note instead of a blank panel. Maps to contract `mobile-rendering.md` rule 5.
- [ ] T012 [US1] CONTINGENT (apply only if T005 still fails on target devices/emulation after T007–T011): reduce parquet decode memory in `site/src/lib/data/loader.ts` — avoid the ~2× `chunks → Uint8Array` buffer (`:237-267`) and/or move the hyparquet decode off the main thread. Gate this task on a measurement note in the PR; skip if the load already passes (keeps the change minimal — research.md R4).

**Checkpoint**: `/ohbm2026/` loads and is interactive on iPhone Safari; T005 passes; desktop unchanged.

---

## Phase 4: User Story 2 - Visible failure instead of a silent blank screen (Priority: P2)

**Goal**: When the atlas genuinely cannot load, the user sees a readable message — never a blank page or endless spinner. (Also the diagnosability foundation that makes US1 failures observable.)

**Independent Test**: Force a data-fetch rejection / an uncaught init error on the WebKit harness → a readable error message is shown (no blank/spinner). Maps to spec US2 acceptance scenarios 1–2 + SC-004.

### Tests for User Story 2 (write FIRST, ensure they FAIL/are missing) ⚠️

- [X] T013 [P] [US2] Unit test for the `AppLoadState` machine in `site/tests/unit/load-state.test.ts`: reaches `failed(reason)` (non-empty reason) on a rejected critical await, reaches `ready` on success, and a worker-warm rejection does NOT force `failed`. MUST FAIL/be missing initially. Maps to data-model `AppLoadState` + contract `error-visibility.md` rules 2–4.
- [X] T014 [P] [US2] WebKit integration test in `site/tests/e2e/ios-load-failure.spec.ts`: with the data fetch stubbed to reject, the page shows a visible readable error (not blank/spinner); and an uncaught init error renders via `+error.svelte`. MUST FAIL initially (no `+error.svelte` exists today). Maps to contract `error-visibility.md` AC-1/AC-2.

### Implementation for User Story 2

- [X] T015 [US2] Add `site/src/routes/+error.svelte`: a human-readable error boundary (not a blank or spinner-only view) for uncaught route-load/hydration errors. Makes the `+error.svelte` half of T014 pass. Maps to contract `error-visibility.md` rule 1.
- [X] T016 [US2] In `site/src/routes/+page.svelte`, formalize the `AppLoadState` machine: wrap the `onMount` body (around the `Promise.all` at `:278`) in try/catch so any thrown/aborted critical await sets an explicit `failed(reason)` state with a visible branch, and the render never stays on `{#if !loaded}Loading…` (`:2589`) after the bootstrap settles. Distinguish critical (data) vs non-critical (worker) failures. Makes T013 + the data-rejection half of T014 pass. Maps to contract `error-visibility.md` rules 2–4 + Principle VI.
- [X] T017 [US2] Apply the same resilient bootstrap to `site/src/routes/+layout.svelte` (`onMount` manifest/theme awaits): surface failures visibly or log with context; ensure no critical failure is swallowed behind the spinner and no empty catch blocks remain. Maps to contract `error-visibility.md` rule 4.

**Checkpoint**: Both stories pass independently — the atlas loads on iPhone (US1), and any genuine failure is visible (US2).

---

## Phase 5: Polish & Cross-Cutting Concerns

**Purpose**: Docs sync, sibling-site scope decision, regression, and constitution gates.

- [X] T018 [P] Docs sync (CA-003): add a browser-support note (supported iOS/Safari range + mobile render behavior) to `README.md` and reference it from this spec; note the `/ohbm2026/`-primary scope.
- [X] T019 Sibling-site scope check (spec Assumptions): run the WebKit/iPhone harness against atlas-root (`/`) and `/neuroscape/`; if they exhibit the same blank/spinner (they share the bootstrap + `UmapPanel`), apply the same R1/R2 guards there. If not affected, record that they are out of scope in the PR.
- [X] T020 Regression check (SC-005): run the existing desktop + (if present) Android/Chrome checks and the desktop Playwright path to confirm 2D+3D mount + auto-rotate are unchanged on desktop-class devices.
- [X] T021 [P] Run the full `site/` `vitest run` suite + the Playwright WebKit suite green; confirm T005/T006/T013/T014 now pass and none were skipped/`xfail`'d to go green (CA-006).
- [X] T022 [P] Verify no data, caches, exports, or downloaded assets were committed and that any test-data path used is gitignored (`site/static/data/`, `data/`, `tmp/`); run `.specify/scripts/bash/constitution-check.sh --full`.
- [X] T023 Audit error handling: no bare catches, no silent fallbacks, no bypassed verification gates; confirm the capability gate is runtime-discovered (no hardcoded UA/iOS allow-list — CA-007).
- [ ] T024 Run `quickstart.md` validation end-to-end, including the final physical-iPhone Safari Web Inspector sign-off (no `webglcontextlost` cascade in Console, no tab kill in the Memory timeline) — SC-001/SC-003. Include a Private-Browsing load and a cold-vs-warm (first-visit vs reload) load, covering the spec's storage-restriction and first-visit-vs-reload edge cases.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately. T001/T002/T003 are [P].
- **Foundational (Phase 2)**: Depends on Setup. T004 blocks the WebKit integration tests (T005, T014).
- **User Stories (Phase 3–4)**: Both depend on Foundational. They are independent of each other and may be done in parallel by different developers.
- **Polish (Phase 5)**: Depends on the desired stories being complete.

### User Story Dependencies

- **US1 (P1)**: Independent. Needs T004 (harness) for its integration test (T005).
- **US2 (P2)**: Independent. Needs T004 for its integration test (T014). Recommended to land *before/with* US1 for diagnosability (see Implementation Strategy), but not a hard code dependency.

### Within Each User Story

- Verification tasks first and failing (T005/T006 for US1; T013/T014 for US2) before implementation.
- US1: `capability.ts` (T007) before the gate that consumes it (T008, T009).
- US2: `+error.svelte` (T015) and the load-state machine (T016) before `+layout` hardening (T017).
- T012 (US1) is contingent — only if the load still fails after T007–T011.

### Parallel Opportunities

- T001, T002, T003 (Setup) in parallel.
- T005 + T006 (US1 tests) in parallel; T013 + T014 (US2 tests) in parallel.
- With two developers: US1 and US2 proceed in parallel after T004.
- T018, T021, T022 (Polish) largely parallel.

---

## Parallel Example: User Story 1

```bash
# Write US1 verification first (parallel):
Task: "Failing-first WebKit/iPhone load check in site/tests/e2e/ios-ohbm-load.spec.ts"
Task: "Unit test for capability gate in site/tests/unit/capability.test.ts"
```

---

## Implementation Strategy

### Recommended order (diagnosability-first, still MVP-focused)

The plan's confirmed fix order is **visibility → trigger → pressure**:

1. Phase 1 Setup + Phase 2 Foundational (harness).
2. **Land US2's R1 mechanism early** (T015–T016): add `+error.svelte` + the
   try/catch load-state machine. This converts the silent blank/spinner into a
   visible failure, so the *real* US1 failure mode becomes observable on-device.
   This is also Principle VI (fail loudly) in action.
3. **US1 (T007–T011)**: capability gate → 2D-only/no-auto-rotate on mobile →
   lazy semantic warm. Re-run the US1 load check (T005) on the WebKit harness and
   a physical iPhone.
4. **Decide on T012 (contingent)** from on-device measurement: apply the decode
   memory fix only if the load still fails.
5. Polish (Phase 5): docs, sibling scope, regression, constitution gates,
   physical-iPhone sign-off.

### MVP scope

US1 (the site loading on iPhone) is the MVP and the user's actual request. US2 is
delivered alongside it because it is both an independent value (no silent blank
screens) and the diagnostic lever for US1.

### Delivery

- Commit each verified slice separately (T004 harness; US2 R1; each US1 task);
  do not batch. No data/secrets in any commit.
- PR to `main`; production deploy needs the `deploy-production` label BEFORE merge
  or a `workflow_dispatch target=production` (memory `deploy_production_label_gate`).
- No data-package re-publish expected; if T012 forces a rebuild, preserve the
  byte-identical-output + co-located provenance guarantees (FR-007 / CA-008).

---

## Notes

- [P] = different files, no dependencies.
- Verify each test FAILS before implementing the code that makes it pass.
- `vitest run` only (watch mode hangs — memory `feedback_vitest_run_mode`).
- Preview/CI watches run under a background monitor, never a blocking foreground
  watch (memory `feedback_watch_use_monitor`).
- Never silence a failure or skip a test to go green (CA-006).
- FR-003 (root cause identified + documented) is discharged by `research.md`
  (Phase 0), not by a task — it was completed during planning and verified
  against the working tree.
