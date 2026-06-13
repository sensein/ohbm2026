# Phase 1 Data Model: Runtime State for the iOS-Safari Load Fix

This is a client-side bug fix, so the "entities" are **runtime state objects and
their transitions**, not persisted data. No parquet schema, no database, no new
on-disk artifact. The model below defines the small set of typed values the fix
introduces or formalizes, so the contracts and tests have a precise target.

## Entity 1 — DeviceCapability (NEW, pure/derived)

Runtime-detected capability snapshot, computed once at bootstrap. **Discovered at
runtime (CA-007), never inferred from a hardcoded UA/iOS-version list.** Lives in
`site/src/lib/device/capability.ts` as a pure function over browser globals so it
is unit-testable with injected fakes.

| Field | Type | Meaning | Source of truth (runtime) |
|-------|------|---------|---------------------------|
| `webglAvailable` | boolean | Can a WebGL context be created at all | probe canvas `getContext('webgl'/'webgl2')` |
| `webglContextBudget` | `'low' \| 'normal'` | Whether multiple simultaneous GL contexts are safe | heuristic: mobile viewport + WebKit + `deviceMemory` |
| `isSmallViewport` | boolean | Phone-class screen | `matchMedia`/`innerWidth` vs. `mobileBreakpoint` (1024) |
| `deviceMemoryGb` | number \| null | Approx RAM if exposed | `navigator.deviceMemory` (null when unavailable — common on iOS) |
| `prefersReducedMotion` | boolean | User wants no auto-animation | `matchMedia('(prefers-reduced-motion: reduce)')` |
| `rangeRequestsLikely` | boolean | Host/browser support byte-range fetch | feature-probe (only if R4 work is reached) |

**Derived gates** (consumed by contracts):
- `allow3dByDefault = webglAvailable && webglContextBudget === 'normal' && !isSmallViewport`
- `allowAutoRotate = allow3dByDefault && !prefersReducedMotion`
- `eagerSemanticWarm = !isSmallViewport && (deviceMemoryGb === null || deviceMemoryGb >= 4)`

**Validation rule:** when `navigator.deviceMemory` is absent (iOS never exposes
it), the gates MUST fall back to the *conservative* branch (treat as low budget),
never the permissive one — failing safe toward "load succeeds" over "feature-rich
but crashes."

## Entity 2 — AppLoadState (FORMALIZED state machine)

Today the bootstrap has an implicit two-value gate (`loaded: boolean`) with no
failure branch. The fix makes the failure state explicit so the UI always escapes
the spinner (R1 / spec User Story 2 / CA-006).

States and transitions:

```
            onMount start
   idle ───────────────────────▶ loading
                                   │
              awaits resolve       │ await throws / aborts / tab-pressure abort
        ┌──────────────────────────┴───────────────────────┐
        ▼                                                    ▼
      ready                                               failed(reason)
   (loaded = true,                                  (visible error message,
    map mountable)                                   NOT a blank/endless spinner)
```

| State | UI shown | Exit |
|-------|----------|------|
| `idle` | nothing yet | → `loading` on `onMount` |
| `loading` | "Loading…" status | → `ready` on success; → `failed` on throw/abort |
| `ready` | atlas interactive (list/scatter, search, detail) | terminal (until reload) |
| `failed(reason)` | human-readable error + retry affordance | → `loading` on user retry |

**Validation rules:**
- The transition into `failed` MUST carry a non-empty, human-readable `reason`
  (e.g. "Could not load the abstract data" / "This device ran out of memory
  loading the map"). No silent swallow (CA-006).
- `failed` MUST be reachable from any await in the bootstrap (data fetch, decode,
  manifest, theme import) — the try/catch wraps the whole `onMount` body.
- A worker (semantic) failure MUST NOT force `failed` (search degrades; the page
  stays usable) — only critical-path failures transition to `failed`.

## Entity 3 — RenderTarget policy for the scatter panel (FORMALIZED)

Captures which Plotly surfaces mount, derived from `DeviceCapability`. Replaces
the current unconditional `show3dPane = mode === 'ohbm' || hasWebGL` + always-on
auto-rotate in OHBM mode.

| Field | Type | Default (desktop) | Default (mobile / low budget) |
|-------|------|-------------------|-------------------------------|
| `mount2d` | boolean | true | true |
| `mount3dByDefault` | boolean | true (OHBM) | **false** — behind explicit toggle |
| `autoRotate` | boolean | true (OHBM) | **false** |
| `userOverrode3d` | boolean | false | false → true when user opts in |

**Validation rule:** at most the number of simultaneous WebGL contexts permitted
by `webglContextBudget` may be mounted at once; hiding the 3D pane MUST call the
existing `destroyChart` path to release its context (no leak — relates to the
known plotly WebGL-context-leak avoidance pattern already in the codebase).

## Non-entities (explicitly unchanged)

- `ohbm2026.parquet` schema, manifest, and all data-package contents — unchanged.
- Embedding recipes, cluster data, enrichment — unchanged.
- Provenance format — unchanged (only re-emitted if a rebuild is forced; not
  expected).
