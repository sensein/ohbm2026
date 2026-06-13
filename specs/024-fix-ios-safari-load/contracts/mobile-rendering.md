# Contract: Mobile WebGL / 3D Rendering Gate (R2)

**Serves:** FR-001, FR-002, FR-005, CA-007. The iOS-specific trigger.

## Behavioral contract

1. **Capability is detected at runtime, not from a device/UA allow-list (CA-007).**
   A pure `site/src/lib/device/capability.ts` computes `DeviceCapability`
   (see data-model.md) from probes: a WebGL context probe, `matchMedia`/viewport,
   `navigator.deviceMemory` (treated as low when absent), and
   `prefers-reduced-motion`.

2. **Default render target on small viewport / low WebGL budget:**
   - `mount2d = true` (the 2D scatter remains the landing map).
   - `mount3dByDefault = false` — the 3D `scatter3d` pane is NOT mounted on first
     paint; it is available behind an explicit user toggle.
   - `autoRotate = false` — no auto-rotation on mobile (also respects
     `prefers-reduced-motion`).
   - At most `webglContextBudget`-permitted contexts mounted simultaneously.

3. **Desktop behavior is preserved (FR-005).** On normal-budget, large-viewport
   devices the existing OHBM behavior is unchanged: 2D + 3D mount, auto-rotate on.
   This contract changes behavior ONLY on the mobile/low-budget branch.

4. **Hiding the 3D pane releases its WebGL context.** Toggling 3D off MUST call
   the existing `destroyChart` teardown so the context is freed (no leak; reuses
   the codebase's plotly WebGL-context-leak-avoidance pattern). No `Plotly.react`
   that changes trace count on toggle.

5. **The map is never the reason the page fails to load.** If WebGL is
   unavailable entirely (`webglAvailable === false`), the atlas still loads with
   the list/search experience and a clear note that the map is unavailable — not
   a blank page (ties to error-visibility contract).

## Acceptance checks (map to spec)

- **AC-1 (US1 scenario 1):** On an iPhone-class WebKit emulation, `/ohbm2026/`
  reaches interactive with only the 2D pane mounted and auto-rotate off; no
  `webglcontextlost` cascade, no tab crash. *(Playwright/WebKit.)*
- **AC-2 (US1 scenario 2):** Search runs and an abstract detail opens with the
  mobile render target active. *(Playwright/WebKit.)*
- **AC-3 (FR-005 regression):** On a desktop-class context, 2D+3D mount and
  auto-rotate on — unchanged from today. *(vitest gate logic + Playwright
  desktop.)*
- **AC-4 (capability unit):** `capability.ts` returns the conservative gate when
  `deviceMemory` is undefined and viewport is small. *(vitest with injected
  fakes.)*

## Out of scope

- Rewriting the 3D rendering engine or replacing Plotly. The fix gates *when* 3D
  mounts, not *how* it renders.
