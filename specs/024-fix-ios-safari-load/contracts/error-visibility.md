# Contract: Error Visibility & Load-State (R1)

**Serves:** spec User Story 2, FR-004, CA-006. Highest-leverage change — landed
first so every other failure becomes observable.

## Behavioral contract

1. **An error boundary exists.** `site/src/routes/+error.svelte` MUST exist and
   render a human-readable message for any uncaught error during route load /
   hydration, instead of a blank page. It MUST NOT render a blank or
   spinner-only view.

2. **The bootstrap cannot get stuck in `loading`.** In `site/src/routes/+page.svelte`
   (and the analogous `+layout.svelte` bootstrap), the `onMount` async body MUST
   be wrapped so that:
   - On success → the load-state becomes `ready` (existing `loaded = true`).
   - On any thrown/aborted critical await (manifest, abstracts, authors, data
     decode, theme import) → the load-state becomes `failed(reason)` with a
     non-empty human-readable `reason`.
   - The render MUST never remain on `{#if !loaded}Loading…` after the bootstrap
     settles — `failed` has its own visible branch.

3. **Critical vs. non-critical failures are distinguished.** A semantic-search
   worker warm failure (R3) MUST NOT transition the page to `failed`; it logs
   with context and the page stays usable (search degrades). Only critical-path
   data failures transition to `failed`.

4. **No silent swallow.** Every catch MUST surface the failure — either to the
   visible `failed` UI (critical) or to the console with record/stage context
   (non-critical). No empty catch blocks; no catch that hides a critical failure
   behind the spinner.

## Acceptance checks (map to spec)

- **AC-1 (US2 scenario 1):** With the data fetch forced to reject, the page shows
  the `failed` message — not a blank screen or endless spinner. *(vitest:
  load-state machine reaches `failed` with a reason; Playwright: visible error
  text present.)*
- **AC-2 (US2 scenario 2):** An unrecoverable init error renders via
  `+error.svelte` with readable text. *(Playwright/WebKit: error route renders.)*
- **AC-3:** A simulated worker-warm rejection leaves the page `ready` and
  interactive (search still works on demand). *(vitest + Playwright.)*

## Out of scope

- The exact copy/wording of the error message (UX detail, decided in
  implementation; must be human-readable, not a stack trace).
