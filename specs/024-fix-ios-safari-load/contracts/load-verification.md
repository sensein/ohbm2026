# Contract: iOS-Safari Load Verification (FR-006, CA-002)

**Serves:** FR-006, the spec's Independent Tests, and the plan-first/test-first
constitution gate (IV / CA-002). This is the *failing-first* verification that
must reproduce the blank/spinner before the fix and pass only after.

## What must exist

1. **An automated WebKit-emulation load check** (Playwright with the WebKit
   engine / iPhone device descriptor) that:
   - Builds/serves the `/ohbm2026/` site locally (preview build, mobile mode
     via the existing `SITE_MODE`/`BASE_PATH` mechanism + a local data package —
     see memory `local_dev_env`).
   - Navigates to the atlas URL on an iPhone viewport + WebKit engine.
   - **Asserts the app reaches `ready`**: the corpus is loaded (abstract count >
     0 rendered), the search input is usable, and at least one abstract
     detail/permalink opens — within a bounded timeout.
   - **Fails first**: before the fix, this check times out on the "Loading…"
     spinner (or errors), reproducing the report.

2. **Unit coverage (`vitest run`, never watch mode):**
   - `capability.ts` returns the conservative gate when `deviceMemory` is
     undefined + viewport small, and the permissive gate on desktop-class fakes.
   - The `AppLoadState` machine reaches `failed(reason)` on a rejected critical
     await and `ready` on success, and a worker-warm rejection does NOT force
     `failed`.

3. **Manual confirmation (recorded in quickstart.md):** a physical-iPhone pass
   via Safari Web Inspector (Mac → Develop → [iPhone]) confirming no
   `webglcontextlost` cascade in Console and no tab-kill in the Memory timeline.
   This is the final sign-off for SC-001/SC-003; the automated WebKit check is
   the CI-enforceable proxy.

## Pass / fail criteria (map to Success Criteria)

| Check | Maps to | Pass condition |
|-------|---------|----------------|
| WebKit-emulation load | SC-001 | App reaches interactive (no blank/spinner/crash) 100% of runs |
| Load-time budget | SC-002 | iPhone load-to-interactive ≤ desktop baseline + 3s, both measured by the same harness on a comparable connection |
| Core journey | SC-003 | open → search → open abstract succeeds (≥95% across runs) |
| Forced-failure visibility | SC-004 | Visible readable message shown, never blank/spinner |
| Desktop/Android regression | SC-005 | Existing desktop + Android/Chrome checks still pass |

## Constraints

- Tests run via `vitest run` (NOT `pnpm test:unit -- --run`, which hangs in watch
  mode — memory `feedback_vitest_run_mode`).
- Any data package the test needs is fetched/placed under a gitignored path
  (`site/static/data/`, `data/`, `tmp/`) — no committed data (CA-005).
- Long-running watches (CI, preview server) run under a background monitor, never
  a blocking foreground watch (memory `feedback_watch_use_monitor`).
