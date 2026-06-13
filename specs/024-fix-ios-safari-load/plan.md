# Implementation Plan: Fix OHBM Atlas Load Failure on iPhone Safari

**Branch**: `024-fix-ios-safari-load` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/024-fix-ios-safari-load/spec.md`

## Summary

The `/ohbm2026/` atlas (a prerendered SvelteKit SPA in `site/`, deployed to
`abstractatlas.brainkb.org/ohbm2026/`) does not load on iPhone Safari: users
get a blank screen or an endless "Loading…" spinner. Root-cause investigation
of the actual code (see `research.md`) found the failure is **not** a JS-syntax
/ build-target problem (the build ships the SvelteKit default `modules` target,
which modern iOS Safari parses fine) but a combination of WebKit-specific
runtime limits and a non-resilient bootstrap that turns any failure into an
invisible blank page:

- **R1 (visibility — the amplifier):** there is no `+error.svelte` boundary, and
  `+page.svelte` only sets `loaded = true` *after* its `await`s
  (`+page.svelte:278,308`). Any thrown await or tab-pressure event leaves the
  render gate stuck on `{#if !loaded}Loading…` (`+page.svelte:2589`) forever,
  with no diagnostic. This is what makes every other failure present as the
  reported "blank/spinner."
- **R2 (the iOS-specific trigger):** in OHBM mode the panel mounts ~3 WebGL
  contexts simultaneously and auto-rotates by default — 2D `scattergl` + 3D
  `scatter3d` + HUD, gated by `show3dPane = mode === 'ohbm' || hasWebGL`
  (`UmapPanel.svelte:232`) and `autoRotate = mode === 'ohbm'`
  (`UmapPanel.svelte:247`). Mobile WebKit caps simultaneous WebGL contexts very
  low and reclaims them aggressively under GPU/memory pressure → context loss or
  tab crash on first paint.
- **R3 (memory pressure contributor):** an ONNX/WASM semantic-search worker is
  warmed eagerly on **every** load (`+page.svelte:317 warmSemantic()`), stacking
  WASM compile + model weights on top of the parquet decode and WebGL contexts,
  pushing the tab toward iOS Safari's per-tab memory ceiling.
- **R4 (memory pressure contributor):** the 25 MB `ohbm2026.parquet` is fully
  buffered (~2× peak during `chunks → Uint8Array` assembly) and decoded on the
  **main thread** (`loader.ts:237-267,347-735`).

**Approach (priority-ordered, matching the spec's P1/P2):** Fix the *visibility*
first (R1) so the real failure is observable and the spec's User Story 2 is
satisfied; then remove the iOS *trigger* (R2) by gating the 3D pane + auto-rotate
behind device capability / viewport on mobile; then relieve *memory pressure*
(R3 lazy-warm, R4 streamed/worker decode) as needed to clear the load.
Every change is client-side in `site/`; no corpus or pipeline rerun is required.
A re-publish of the data package is **not** expected (R4's fix is decode-path
only, not a parquet schema change), so the byte-identical-output guarantee
(FR-007) is preserved by default.

## Technical Context

**Language/Version**: TypeScript / Svelte 5 + SvelteKit (site); Python 3.14 only
if a data-package rebuild proves necessary (not expected).
**Primary Dependencies**: SvelteKit + `@sveltejs/adapter-static`, Vite 6,
Plotly.js (`scattergl` / `scatter3d`), `hyparquet` (in-browser parquet decode),
`@xenova/transformers` + onnxruntime-web (semantic-search worker).
**Storage**: Static JSON/parquet data package fetched at runtime from the
production data host (Dropbox default; R2 sibling). No server.
**Testing**: `vitest run` for `site/` unit tests (never watch mode — see memory
`feedback_vitest_run_mode`); Playwright-driven device/emulation check for the
iOS-Safari load (the failing-first verification, FR-006); existing Python
`unittest` only if a data rebuild is touched.
**Target Platform**: iPhone Safari (current iOS major + one prior), without
regressing desktop browsers or Android/Chrome. WebKit (iOS) is the platform
under test.
**Project Type**: Web application (static SvelteKit SPA under `site/`, three
sibling build modes: atlas-root, `ohbm2026`, `neuroscape`).
**Performance Goals**: Atlas reaches an interactive state on iPhone Safari with
no blank screen / endless spinner / crash; load-time within a small margin of
the desktop experience (SC-002); core journey (open → search → open abstract)
succeeds in ≥95% of mobile attempts (SC-003).
**Constraints**: iOS Safari per-tab memory ceiling; low simultaneous-WebGL-
context cap; stricter WASM-MIME / range-request behavior than desktop;
client-side-only change; byte-identical `/ohbm2026/` data package preserved
unless a rebuild is justified.
**Scale/Scope**: `/ohbm2026/` = 25 MB parquet full-GET (~the corpus of OHBM 2026
abstracts). Sibling sites (atlas-root 33 MB, neuroscape ~92–97 MB range-fetched)
are in scope only if they share the same defect (Assumptions).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Venv-only Python** — PASS. The fix is overwhelmingly TypeScript in
  `site/`. Any Python (only if a data rebuild is needed) runs via
  `.venv/bin/python` / `uv`. No system Python.
- **II. Immutable evidence / no committed data** — PASS. No corpus mutation.
  Diagnostic captures (screenshots, traces, any rebuilt package) land in
  gitignored roots (`data/`, `site/static/data/`, `tmp/`). Nothing generated is
  tracked.
- **III. Resumable, auditable pipelines** — N/A for the client fix; if a data
  rebuild is triggered it uses the existing resumable `build-atlas-package`
  path with its caches, unchanged.
- **IV. Plan-first, test-first** — PASS. This plan precedes code; FR-002/FR-006
  name the failing-first verification (a device/emulated load check that
  reproduces the blank/spinner and passes only once the atlas loads) plus
  `vitest run` unit coverage for the new guards. See `quickstart.md`.
- **V. Secret-safe, commit early/often** — PASS. No new secrets. Existing data
  host accessed via `.env`-named vars only. Work commits in small verified
  slices (visibility fix → trigger fix → pressure relief).
- **VI. Fail loudly, no shortcuts** — PASS and *central to the design*: R1's fix
  replaces the silent blank page with an explicit, visible error state (a
  `+error.svelte` boundary + try/catch that surfaces the failure), directly
  serving CA-006 and the spec's User Story 2. No bare excepts, no
  swallowed worker failures, no skipped tests/`--no-verify`.
- **VII. Discover external state, don't hardcode it** — PASS. Device capability
  (WebGL availability/context budget, `deviceMemory`, viewport, range-request
  support) is **detected at runtime**, not matched against a hardcoded
  device/iOS-version allow-list (CA-007). The mobile gate keys on measured
  capability + viewport, not a UA string blocklist.
- **VIII. Provenance for organizer-facing outputs** — PASS. No new
  organizer-facing data artifact. If the data package is re-published, it
  carries the existing co-located provenance with no absolute/home paths.
- **Docs sync** — PASS. README's deploy/browser notes and this spec's plan are
  updated in-change; a browser-support note is added if the supported matrix is
  made explicit.
- **Granular commits + push** — PASS. Each verified slice commits separately;
  pushed when complete (PR to `main`, with the `deploy-production` label gate
  respected per memory `deploy_production_label_gate`).

**Result: PASS — no violations. Complexity Tracking not required.**

## Project Structure

### Documentation (this feature)

```text
specs/024-fix-ios-safari-load/
├── plan.md              # This file
├── spec.md              # Feature spec (/speckit-specify)
├── research.md          # Phase 0 — root-cause analysis + decisions
├── data-model.md        # Phase 1 — runtime state/entities (capability, load-state)
├── quickstart.md        # Phase 1 — how to reproduce + verify the fix
├── contracts/           # Phase 1 — UI/behavior contracts
│   ├── error-visibility.md       # R1: error boundary + load-state contract
│   ├── mobile-rendering.md       # R2: WebGL/3D/auto-rotate gating on mobile
│   ├── lazy-semantic-warm.md     # R3: defer the ONNX/WASM worker on mobile
│   └── load-verification.md      # FR-006: failing-first device/emulation check
├── checklists/
│   └── requirements.md  # spec quality checklist (/speckit-specify)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
site/                                  # SvelteKit SPA (the only code touched)
├── src/
│   ├── routes/
│   │   ├── +page.svelte               # R1: loaded/failed state + try/catch in onMount; R3: gate warmSemantic
│   │   ├── +layout.svelte             # R1: resilient bootstrap (manifest/theme awaits)
│   │   └── +error.svelte              # R1: NEW — visible error boundary (currently absent)
│   ├── lib/
│   │   ├── components/
│   │   │   └── UmapPanel.svelte       # R2: gate show3dPane + autoRotate on mobile/low-capability
│   │   ├── device/                    # NEW — runtime capability detection (pure, testable)
│   │   │   └── capability.ts          # WebGL budget, deviceMemory, viewport, reduced-motion
│   │   ├── search/semantic.ts         # R3: lazy-warm policy hook
│   │   └── data/loader.ts             # R4 (if needed): avoid 2× buffer / move decode off main thread
│   └── workers/semantic.worker.ts     # R3: unchanged logic; only invocation timing changes
└── tests/ (vitest)                    # unit coverage for capability gate + load-state machine
```

**Structure Decision**: Web application, single existing SvelteKit project under
`site/`. All changes are client-side. New code is isolated into a small,
pure, unit-testable `site/src/lib/device/capability.ts` (so the runtime gate is
verifiable without a browser) plus narrow edits to the three bootstrap/render
files. No Python `src/ohbm2026/` change is planned; a data-package rebuild is a
contingency, not a default.

## Complexity Tracking

> No constitution violations — this section intentionally left empty.
