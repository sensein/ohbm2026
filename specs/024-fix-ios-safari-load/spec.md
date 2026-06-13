# Feature Specification: Fix OHBM Atlas Load Failure on iPhone Safari

**Feature Branch**: `024-fix-ios-safari-load`  
**Created**: 2026-06-13  
**Status**: Draft  
**Input**: User description: "on iphones+safari the ohbm site does not load."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - OHBM attendee opens the atlas on an iPhone (Priority: P1)

An OHBM 2026 attendee (or organizer) taps the published atlas link
(`abstractatlas.brainkb.org/ohbm2026/`) on their iPhone using the default
Safari browser. Today the page never finishes loading — they see a blank
screen, an indefinite spinner, or an error — and they cannot browse, search,
or open any abstract. After the fix, the atlas loads and becomes interactive
on iPhone Safari just as it does on a desktop browser.

**Why this priority**: The atlas is a conference-facing product. A large share
of attendees will reach it from a phone during the meeting, and iOS Safari is
the dominant mobile browser at a scientific conference. A site that does not
load at all on that platform is effectively unavailable to a major segment of
its audience — this is the most severe possible defect for a public site.

**Independent Test**: Open `…/ohbm2026/` on a physical iPhone (or an iOS
Safari simulator) on a current iOS version and confirm the landing view
renders, the abstract corpus loads, and the page becomes interactive without a
crash, blank screen, or stalled spinner.

**Acceptance Scenarios**:

1. **Given** an iPhone running a currently-supported iOS version with the
   stock Safari browser, **When** the user navigates to the `/ohbm2026/`
   atlas URL, **Then** the landing view renders and the abstract data finishes
   loading within the same time budget expected on desktop.
2. **Given** the atlas has loaded on iPhone Safari, **When** the user runs a
   search and opens an abstract detail view, **Then** results appear and the
   detail panel opens without a crash or unresponsive page.
3. **Given** an iPhone Safari session that previously failed to load,
   **When** the user reloads after the fix is deployed, **Then** the previous
   failure mode (blank screen / endless spinner / error) no longer occurs.

---

### User Story 2 - Diagnosable, visible failure instead of a silent blank screen (Priority: P2)

If the atlas cannot fully load on a given device — whether because of a
genuinely unsupported browser, a network failure mid-load, or device memory
limits — the user should see a clear, human-readable message explaining what
happened and what to try next, rather than a blank page or a spinner that
never resolves.

**Why this priority**: A silent blank screen gives the user no recourse and
gives organizers no signal. Even after the primary load path is fixed, a
visible, explained failure mode prevents the same "it just doesn't work"
report from recurring on edge devices and makes future regressions
self-evident. This aligns with the project's "fail loudly, no silent
fallbacks" principle.

**Independent Test**: Simulate a load failure (e.g. interrupt the data fetch,
or load on a deliberately unsupported configuration) on iPhone Safari and
confirm a readable error/empty-state message appears instead of a blank page.

**Acceptance Scenarios**:

1. **Given** the data package cannot be fetched on iPhone Safari, **When** the
   load fails, **Then** the user sees a readable message describing the
   problem instead of a blank screen or an indefinite spinner.
2. **Given** an unrecoverable error during initialization, **When** it occurs
   on iPhone Safari, **Then** the failure is surfaced visibly in the UI (not
   swallowed) so it can be reported and reproduced.

---

### Edge Cases

- **Memory pressure**: The OHBM corpus and any in-browser decoding must load
  within the tighter memory ceiling iOS Safari imposes on a tab before it is
  killed. What happens when the device is older / lower-memory?
- **Interactive 3D / WebGL surface**: The scatter view uses hardware-
  accelerated rendering. iOS Safari limits the number of simultaneous
  hardware-rendering contexts more aggressively than desktop. Does the page
  still load (even if a heavy view degrades gracefully) when that limit is
  reached?
- **Range / partial-fetch behavior**: The atlas relies on partial
  (byte-range) fetches of its data package. Does iOS Safari's handling of
  range requests and caching from the production data host succeed?
- **Private Browsing / storage restrictions**: iOS Safari restricts or
  disables client-side storage in Private Browsing. Does the site load when
  persistent client storage is unavailable?
- **First visit vs. reload**: Does behavior differ between a cold first load
  and a subsequent reload (cache warm vs. cold)?
- **Scope of sibling sites**: The atlas-root (`/`) and `/neuroscape/` sibling
  surfaces share the same codebase and data-loading approach; if the same
  defect affects them, do they need the same fix? (See Assumptions.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `/ohbm2026/` atlas MUST fully load and become interactive on
  iPhones running a currently-supported version of iOS using the stock Safari
  browser, with no blank screen, indefinite spinner, or unrecoverable error on
  initial load.
- **FR-002**: After loading on iPhone Safari, the atlas MUST support the core
  user journeys — viewing the landing scatter/list, searching, and opening an
  abstract detail/permalink — without crashing or becoming unresponsive.
- **FR-003**: The root cause of the current iPhone Safari load failure MUST be
  identified and documented (the specific incompatibility, resource limit, or
  failing load step), not merely worked around blindly.
- **FR-004**: When the atlas genuinely cannot load on a device or session
  (unsupported configuration, network failure, or resource exhaustion), it
  MUST present a readable, human-facing message explaining the situation
  rather than rendering a blank page or a spinner that never resolves.
- **FR-005**: The fix MUST NOT degrade the existing, working experience on
  desktop browsers or on Android/Chrome mobile; previously-passing behavior on
  those platforms MUST continue to pass.
- **FR-006**: A repeatable verification MUST exist that confirms the atlas
  loads on iPhone Safari (a physical-device or iOS-Safari-emulated check) so
  the fix can be validated and a future regression detected.
- **FR-007**: If the fix requires regenerating or re-publishing the data
  package, the change MUST preserve the byte-identical-output and provenance
  guarantees the project already enforces for atlas artifacts.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python execution for this feature MUST use the repository-local
  `.venv/bin/python` interpreter or `uv` targeting that interpreter.
- **CA-002**: A failing-first verification MUST be identified before the fix: a
  check (manual device/emulator script or automated test) that reproduces the
  iPhone Safari load failure and passes only once the site loads. Site unit
  tests run via `vitest run` (never watch mode).
- **CA-003**: If canonical defaults, the data package, build modes, or the
  documented browser-support matrix change, the docs in the same change
  (README and/or the relevant `specs/<stage>/` plan, and any browser-support
  note) MUST be updated alongside.
- **CA-004**: No new credentials are expected. If diagnosis touches the data
  host, any access MUST use existing `.env`-named secrets; no checked-in
  tokens.
- **CA-005**: Any diagnostic capture, regenerated data package, or downloaded
  asset MUST land in a gitignored path (`data/`, `site/static/data/`,
  `tmp/`); no generated data is tracked in the repository.
- **CA-006**: Error paths MUST be explicit and visible: load failures,
  unsupported-browser conditions, and data-fetch failures MUST be surfaced in
  the UI or logs with context rather than silently swallowed. No verification
  gate may be bypassed to ship the fix.
- **CA-007**: Any dependency on browser capabilities or data-host behavior
  (range-request support, storage availability, WebGL context limits) MUST be
  detected at runtime and surfaced as a precise condition, not assumed from a
  hardcoded device/version list.
- **CA-008**: This feature produces no new organizer-facing data artifact. If a
  data package is re-published as part of the fix, it MUST carry the existing
  machine-readable provenance (inputs, build config, code revision, command,
  seed) co-located with it and free of absolute or user-home paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of attempts to open the `/ohbm2026/` atlas on a currently-
  supported iPhone Safari configuration reach an interactive state (no blank
  screen, no endless spinner, no crash) — up from the current 0% (does not
  load).
- **SC-002**: On iPhone Safari, the atlas reaches an interactive state no more
  than **3 seconds** slower than the desktop load-to-interactive time measured
  on a comparable connection (i.e. `iphone_time ≤ desktop_baseline + 3s`). The
  desktop baseline is captured by the same automated harness so the margin is
  verifiable, not aspirational.
- **SC-003**: The core mobile journey — open the atlas, run a search, open one
  abstract — completes successfully on iPhone Safari in at least 95% of
  attempts across the supported iOS-version range.
- **SC-004**: In any case where the site cannot load, the user sees a readable
  explanatory message 100% of the time, instead of a blank page or stalled
  spinner.
- **SC-005**: No regression on currently-working platforms: existing
  desktop-browser and Android/Chrome load and interaction behavior continues
  to pass after the fix.

## Assumptions

- **"The ohbm site" = the `/ohbm2026/` atlas** at
  `abstractatlas.brainkb.org/ohbm2026/`. This is the primary, P1 target.
  Because the atlas-root (`/`) and `/neuroscape/` siblings share one codebase
  and the same data-loading mechanism, a fix that addresses a shared root
  cause is expected to benefit them too; bringing those siblings to the same
  bar is in scope only if they exhibit the same failure, and is otherwise a
  follow-up.
- **Supported targets**: "currently-supported iOS" means the current major iOS
  release and the one prior, using stock Safari, on iPhone hardware Apple
  still supports. Jailbroken devices, third-party iOS browser engines, and
  end-of-life iOS versions are out of scope.
- **The failure is reproducible** on iPhone Safari (or an equivalent iOS
  Safari emulation/simulator) and is not an intermittent network artifact;
  diagnosis can begin from a reproducible load failure.
- **No corpus/content change**: the abstract data and enrichment content are
  correct; this is a client-side load/compatibility defect, not a data defect.
  The fix should not require re-running the upstream ingest/enrichment
  pipeline, though it may require re-publishing the existing data package.
- **Existing data host stays**: the production data channel and host remain as
  currently configured; diagnosis may inspect host behavior but a host change
  is not assumed to be required.
