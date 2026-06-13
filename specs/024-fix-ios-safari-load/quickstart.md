# Quickstart: Reproduce & Verify the iOS-Safari Load Fix

Audience: an engineer implementing or reviewing branch `024-fix-ios-safari-load`.
All commands run from the repo root unless noted. Site work happens in `site/`.

## 0. Prerequisites

- Local site data package available (the site fetches a data package at runtime).
  Follow memory `local_dev_env`: copy `site/.env.example` → `site/.env.local` and
  set the `VITE_DATA_PACKAGE_URL_*` vars (CI `vars.*` mirror these). For
  `/ohbm2026/` you need the `ohbm2026.parquet` channel.
- Node + pnpm in `site/`. Python only if a data rebuild is forced (not expected);
  use `.venv/bin/python` / `uv` if so.

## 1. Reproduce the failure (failing-first — do this BEFORE the fix)

### a. On a physical iPhone (ground truth)
1. Open Safari on an iPhone (current iOS) → navigate to
   `https://abstractatlas.brainkb.org/ohbm2026/`.
2. Observe: blank screen or an indefinite "Loading…" spinner; the atlas never
   becomes interactive.
3. Attach Safari Web Inspector from a Mac (Develop → [your iPhone] → the page):
   - **Console**: look for `webglcontextlost` (→ R2) and any uncaught throw.
   - **Timelines → Memory**: look for a tab kill / sharp memory spike (→ R3/R4).

### b. WebKit emulation (reproducible, CI-able)
```bash
cd site
pnpm install
# build/serve the ohbm2026 mobile build with a local data channel (see local_dev_env)
VITE_SITE_MODE=ohbm2026 pnpm build && pnpm preview   # run under a background monitor
```
Then drive it with the Playwright WebKit/iPhone descriptor (the new check from
contracts/load-verification.md). Before the fix it times out on the spinner.

## 2. Implement in priority order (each a separately-committed, verified slice)

1. **R1 — visibility (land first):** add `site/src/routes/+error.svelte`; wrap the
   `+page.svelte` (and `+layout.svelte`) `onMount` body in try/catch driving an
   explicit `failed(reason)` state with a visible message. *(contract:
   error-visibility.md)*
2. **R2 — mobile render gate:** add `site/src/lib/device/capability.ts`; gate
   `show3dPane` / `autoRotate` in `UmapPanel.svelte` on the runtime capability
   (2D-only + no auto-rotate on mobile/low budget; 3D behind explicit toggle).
   *(contract: mobile-rendering.md)*
3. **R3 — lazy semantic warm:** make `warmSemantic()` on-demand (search focus /
   guarded idle), skip eager warm on mobile/low-memory; verify WASM MIME path.
   *(contract: lazy-semantic-warm.md)*
4. **R4 — decode pressure (only if still needed):** avoid the 2× parquet buffer /
   move hyparquet decode off the main thread. Apply only if measurement on the
   target devices shows the load still fails after R1–R3. *(research.md R4)*

## 3. Verify (must pass before merge)

```bash
cd site
vitest run                      # unit: capability gate + AppLoadState machine
                                #  (NEVER `pnpm test:unit -- --run` — hangs in watch mode)
```
- Run the Playwright WebKit/iPhone load check → now reaches interactive
  (corpus loaded, search usable, an abstract opens). It failed in step 1b.
- Forced-failure check: stub the data fetch to reject → a visible readable error
  appears (no blank/spinner). *(SC-004)*
- Desktop + Android/Chrome checks still pass (no regression — SC-005).
- Final manual sign-off: re-run step 1a on a physical iPhone → atlas loads, no
  `webglcontextlost` cascade, no tab kill. *(SC-001/SC-003)*

## 4. Ship

- Commit each slice with a descriptive message; open a PR to `main`.
- Production deploy needs the `deploy-production` PR label BEFORE merge (memory
  `deploy_production_label_gate`) or a `workflow_dispatch target=production`.
- No data package re-publish is expected. If R4 forces a rebuild, it must keep
  the byte-identical-output + co-located provenance guarantees (FR-007 / CA-008).

## Scope note

"The ohbm site" = `/ohbm2026/` (P1). The atlas-root (`/`) and `/neuroscape/`
siblings share the bootstrap + `UmapPanel`; if step 1 reproduces the same
blank/spinner there, the R1/R2 guards apply to them too (spec Assumptions —
in scope only if they share the defect).
