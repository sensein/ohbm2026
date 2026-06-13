# Phase 0 Research: Why the OHBM Atlas Fails to Load on iPhone Safari

This document records the root-cause investigation that grounds the plan
(FR-003 requires the cause be identified and documented, not blindly worked
around). Findings were obtained by reading the shipped `site/` code and
verifying the load-bearing claims directly (file:line citations below were
confirmed against the working tree on branch `024-fix-ios-safari-load`).

## What was ruled OUT (so we don't chase the wrong fix)

- **Decision: JS syntax / build target is NOT the cause.**
  - **Rationale:** No custom `build.target` / esbuild target / `.browserslistrc`
    exists in `site/`; Vite 6 + SvelteKit default to the `modules` target
    (esbuild baseline ≈ Safari 14+), which modern iOS Safari parses. `tsconfig`
    affects only type-checking, not emit. A grep for the usual WebKit-unsupported
    APIs (`OffscreenCanvas`, `structuredClone`, `.at`, `crypto.randomUUID`,
    `SharedArrayBuffer`/`Atomics`, top-level await, `toSorted`/`findLast`) found
    none in shipped `src` code. `requestIdleCallback` IS used but every call site
    is `typeof === 'function'`-guarded with a `setTimeout` fallback.
  - **Alternative considered:** Down-leveling the build target. Rejected — it
    would not change behavior because the bundle is already parseable.

- **Decision: Cache API / storage in Private Browsing is NOT the prime cause.**
  - **Rationale:** `cache.ts:cacheApiAvailable()` guards `caches`; all
    `cache.open/match/put` and `localStorage`/`sessionStorage` access are wrapped
    in try/catch (`app.html`, `+layout.svelte`). Worth a Private-Browsing spot
    check but not a likely trigger.

## Confirmed root causes (ranked, most-likely first)

### R1 — No error boundary + bootstrap sets `loaded` only after awaits → permanent invisible spinner  *(HIGH — the amplifier)*

- **Evidence:** No `+error.svelte` exists anywhere under `site/src` (verified:
  `find src -name "+error*"` → empty). `+page.svelte:221` `onMount(async …)`
  does `await Promise.all([loadManifest(), loadAbstracts(), loadAuthors()])`
  (`:278`) and only sets `loaded = true` at `:308`. The render gate is
  `{#if !loaded}<p class="status">Loading…</p>` (`:2589`).
- **Why iOS-specific (as a symptom):** Any upstream iOS-only failure (R2/R3/R4 or
  a tab kill) throws or aborts before `:308`, so `loaded` stays `false` forever →
  the exact "blank screen / endless spinner" the user reports, with no message.
  On desktop the upstream failure doesn't occur, so `loaded` flips normally.
- **Decision:** Add `src/routes/+error.svelte`; wrap the `onMount` body in
  try/catch that drives an explicit `failed`/error state; ensure the UI always
  escapes the spinner (a `finally` or distinct failed branch). This is the
  highest-leverage *first* change because it makes every other cause observable
  and directly satisfies spec User Story 2 + CA-006.
- **Alternative considered:** Only fixing the trigger (R2) without visibility.
  Rejected — leaves the site fragile and undiagnosable on the next edge device.

### R2 — OHBM mode mounts ~3 simultaneous, auto-rotating WebGL contexts  *(HIGH — the iOS trigger)*

- **Evidence:** `UmapPanel.svelte:232` `$: show3dPane = mode === 'ohbm' || hasWebGL`
  (always true in OHBM), `:247` `let autoRotate = mode === 'ohbm'` (auto-rotate on
  by default), markup mounts the 2D `scattergl` chart **and** the 3D `scatter3d`
  chart (which adds an HUD canvas) together (`:2599-2626`). `detectWebGL()`
  transiently opens a probe context too. The existing `mobileBreakpoint = 1024`
  (`:62`) only restyles interaction; it does **not** reduce WebGL contexts or gate
  the 3D pane.
- **Why iOS-specific:** Mobile WebKit caps simultaneous WebGL contexts very low
  and reclaims them aggressively under GPU/memory/thermal pressure; sustained GPU
  load from the default auto-rotation drives `webglcontextlost`. Desktop
  Chrome/Firefox allow far more contexts and don't reclaim as eagerly. Creating
  2–3 contexts during first paint on an iPhone can fail to initialize or crash the
  tab → blank (then R1 hides it).
- **Decision:** On mobile / low WebGL budget (detected at runtime, not by UA
  string), mount only the 2D pane by default and put the 3D scatter behind an
  explicit user toggle; disable auto-rotate on mobile; ensure `destroyChart`
  releases the context when the pane is hidden.
- **Alternative considered:** Keep 3D but cap to one context. Rejected as
  insufficient — auto-rotation + the parquet/WASM stack still pressures the tab;
  deferring 3D to explicit opt-in is the safe default and degrades gracefully.

### R3 — Eager ONNX/WASM semantic-search worker warmed on every load  *(MEDIUM-HIGH — memory pressure)*

- **Evidence:** `+page.svelte:314-321` immediately `await import('$lib/search/semantic')`
  then `await mod.warmSemantic()` on every load. `semantic.worker.ts` imports
  `@xenova/transformers`, sets `env.useBrowserCache = true`, and instantiates the
  `Xenova/all-MiniLM-L6-v2` ONNX model (multi-MB WASM runtime + weights, fetched
  from a CDN).
- **Why iOS-specific:** transformers.js/onnxruntime-web historically used
  `WebAssembly.instantiateStreaming`, which iOS Safari rejects without an exact
  `application/wasm` MIME (stricter than Chrome); and the WASM compile + weights
  stack on top of the 25 MB parquet and WebGL contexts pushes the tab toward the
  per-tab memory ceiling, where WebKit silently kills it. The `warmSemantic()`
  call has its own `.catch`, so a worker failure alone won't block `loaded`, but
  the memory it adds can crash the whole tab.
- **Decision:** Make the warm truly lazy — trigger on first focus of the search
  box (or idle, behind a real `requestIdleCallback`/`setTimeout` guard), and skip
  the eager warm on mobile / low `deviceMemory`. Verify the WASM MIME path.
- **Alternative considered:** Removing semantic search on mobile entirely.
  Rejected — search must work (FR-002); lazy on-demand warm preserves the feature
  while removing it from the critical load path.

### R4 — 25 MB parquet fully buffered (~2× peak) and decoded on the main thread  *(MEDIUM — contributor)*

- **Evidence:** `loader.ts:196-281` reads the whole body via
  `response.body.getReader()` into a `chunks[]` array, then copies into one
  `new Uint8Array(loaded)` (≈2× peak). `parseParquetSingle` (`:347-735`) decodes
  the outer + inner blobs synchronously on the main thread (only `setTimeout(0)`
  yields). INT64 columns come back as BigInt and are walked by `coerceBigInts`
  (`:320-335`).
- **Why iOS-specific:** iPhones have far less per-tab RAM headroom; the transient
  2× buffer + decoded object graph can spike memory and stall the main thread,
  contributing to a tab kill when stacked with R2+R3. By itself 25 MB is usually
  survivable on a modern iPhone.
- **Decision (contingent):** If R1+R2+R3 do not clear the load on the target
  devices, avoid the 2× copy (decode from a single `arrayBuffer()`), free
  `chunks` eagerly, and/or move the hyparquet decode into a worker. Apply only if
  measurement shows it's still needed — keeps the change minimal.
- **Alternative considered:** Switching `/ohbm2026/` to range-fetch like
  neuroscape. Rejected as out of scope for a load-fix; it would alter the data
  layout and risk the byte-identical guarantee.

## Verification strategy (resolves FR-006)

- **Decision:** A Playwright-driven check using a WebKit/iOS-Safari device
  emulation (iPhone viewport + WebKit engine) loads `/ohbm2026/` against a local
  preview build and asserts the app reaches an interactive state (corpus loaded,
  search usable, an abstract openable) — failing first (reproduces the blank/
  spinner), passing after the fix. Plus `vitest run` unit tests for the pure
  capability gate and the load-state machine.
- **Rationale:** WebKit emulation is reproducible in CI; a physical-iPhone pass
  via Safari Web Inspector is the final manual confirmation (watch Console for
  `webglcontextlost` and the Memory timeline for tab kills) per the spec's
  Independent Tests.
- **Alternative considered:** UA-string sniffing tests only. Rejected — does not
  exercise the real WebKit limits and violates CA-007 (runtime discovery).

## Open questions deferred to `/speckit-tasks` / implementation

- Exact ordering: confirm on a physical iPhone whether R2 alone clears the load
  once R1 makes failures visible, before committing to R3/R4 work.
- Whether the atlas-root (`/`) and `/neuroscape/` siblings exhibit the same
  blank/spinner (they share the bootstrap + UmapPanel); if so, the same R1/R2
  guards apply there (spec Assumptions — in scope only if they share the defect).
