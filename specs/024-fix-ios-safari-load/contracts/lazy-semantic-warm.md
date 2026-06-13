# Contract: Lazy Semantic-Search Warm (R3)

**Serves:** FR-001, FR-002, CA-006. Removes the ONNX/WASM worker from the
critical load path to relieve iOS memory pressure, without losing search.

## Behavioral contract

1. **No eager warm on the critical load path for mobile/low-memory.** The current
   unconditional `await mod.warmSemantic()` in `+page.svelte` (fires on every
   load, right after the data load) MUST NOT run eagerly when
   `eagerSemanticWarm === false` (small viewport, or `deviceMemory` low/absent).

2. **Warm on demand instead.** The semantic worker is warmed:
   - on first focus/interaction with the search input, OR
   - during true idle (guarded `requestIdleCallback`/`setTimeout` fallback)
   whichever comes first — so search still feels responsive but the WASM compile +
   model weights are not stacked onto first paint.

3. **Worker failures stay non-critical.** A warm/instantiation failure logs with
   context and degrades search (e.g. lexical-only) — it MUST NOT blank the page or
   transition the app to `failed` (defers to error-visibility contract rule 3).

4. **WASM delivery is WebKit-safe.** Verify the worker's WASM is loaded in a way
   iOS Safari accepts (correct `application/wasm` MIME / no
   `instantiateStreaming` reliance on a mis-typed response). If the current path
   relies on streaming compile against a CDN response, add the documented
   fallback. (Investigate during implementation; only change if the probe shows
   a problem — CA-006 "label the workaround with root cause.")

5. **Desktop behavior preserved (FR-005).** On normal-memory desktop, eager warm
   MAY remain (or move to idle) but search latency on first query MUST NOT
   regress noticeably.

## Acceptance checks (map to spec)

- **AC-1:** On iPhone-class emulation, the page reaches interactive without the
  semantic worker having compiled (verified by no worker network/compile on the
  critical path), and the corpus is usable. *(Playwright/WebKit.)*
- **AC-2 (US1 scenario 2):** Focusing search then querying warms the worker and
  returns semantic results. *(Playwright.)*
- **AC-3:** A forced worker-warm rejection leaves the page interactive with
  degraded (lexical) search. *(vitest + Playwright.)*

## Out of scope

- Changing the embedding model or the worker's ranking logic — only *when* it is
  instantiated changes.
