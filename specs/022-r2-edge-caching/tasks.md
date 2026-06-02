---

description: "Task list — Edge caching for the R2 data host"
---

# Tasks: Edge caching for the R2 data host

**Input**: Design documents from `specs/022-r2-edge-caching/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: INCLUDED — the plan is verification-first. Python `unittest`, run via `PYTHONPATH=src .venv/bin/python -m unittest`. The atlas_hosting test modules already exist (`tests/test_atlas_hosting_{compare,r2_client,manifest,cli}.py`) — EXTEND them.

**Organization**: by user story. Track A — all code under `src/ohbm2026/atlas_hosting/`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- Same file ⇒ NOT parallel across tasks

## Path Conventions

Python package `src/ohbm2026/atlas_hosting/`; tests `tests/`. CLI `ohbmcli` (`src/ohbm2026/cli.py`). Run Python through `.venv/bin/python` (Constitution I).

---

## Phase 1: Setup

- [x] T001 Confirm the toolchain: the `r2` extra is installed (`uv pip install --python .venv/bin/python ".[r2]"` if needed) and the baseline atlas_hosting suite runs: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_atlas_hosting_compare tests.test_atlas_hosting_r2_client tests.test_atlas_hosting_manifest tests.test_atlas_hosting_cli -v`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: shared loud-failure type for the cache verification.

- [x] T002 Add a typed cache-verification failure to the `Stage20Error` subtree in `src/ohbm2026/exceptions.py` (e.g. `DataHostingCacheError`) so a bypassing host / range-parity mismatch raises explicitly (CA-006); export it where the other Stage20 errors are exported.

**Checkpoint**: error type available to US3.

---

## Phase 3: User Story 2 — Immutable cache policy on every object (Priority: P1) 🎯 MVP

**Goal**: lock in the already-correct immutable `Cache-Control` on every uploaded object and record the applied policy in the publish provenance.

**Independent Test**: inspect a publish's manifest/provenance → the cache policy is recorded; the uploader's ExtraArgs carry `public, max-age=31536000, immutable`; a re-publish leaves it intact.

**Note**: the upload itself already sets the policy (`r2_client.py:185`, applied to single + multipart by `upload_file`) — this story is regression-guard + provenance, not new upload logic.

### Tests for User Story 2 (write/extend first) ⚠️

- [x] T003 [P] [US2] Extend `tests/test_atlas_hosting_r2_client.py`: assert the upload path passes `CacheControl="public, max-age=31536000, immutable"` (and the parquet `ContentType`) in `ExtraArgs` for both small and multipart-sized files (regression guard — should pass immediately).
- [x] T004 [P] [US2] Extend `tests/test_atlas_hosting_manifest.py`: a manifest built for a publish records the applied cache policy (`cache_control`) and round-trips through `to_dict`/`from_dict` (FAILS until T005/T006).

### Implementation for User Story 2

- [x] T005 [US2] In `src/ohbm2026/atlas_hosting/r2_client.py`, expose the applied cache policy (e.g. make `_DEFAULT_CACHE_CONTROL` accessible / return it from the upload helper) so callers can record it — without changing upload behavior.
- [x] T006 [US2] In `src/ohbm2026/atlas_hosting/manifest.py`, add a `cache_control` field to the upload manifest (channel-level, uniform per publish) incl. `to_dict`/`from_dict`; in `src/ohbm2026/atlas_hosting/uploader.py`, thread the applied policy from the R2 client into the manifest so `data/provenance/atlas_upload_provenance__<key>.json` records it (FR-010 / CA-008).

**Checkpoint**: every published object's cache policy is auditable from provenance; behavior unchanged.

---

## Phase 4: User Story 3 — Verifiable cache behavior + safe Range (Priority: P2)

**Goal**: extend `compare-data-hosting` to capture cache evidence (cf-cache-status/age/cache-control) for full + range requests, distinguish cold→warm from BYPASS, flag bypass, and assert range byte-parity.

**Independent Test**: run `compare-data-hosting` against the R2 host → the report's cache section shows per-request status/age/policy for full + range; a bypassing host is flagged (non-zero/explicit), and range byte-parity is verified.

**Dependency**: T002 (error type). This tooling is what proves US1.

### Tests for User Story 3 (write/extend first) ⚠️

- [x] T007 [P] [US3] Extend `tests/test_atlas_hosting_compare.py` with mocked `http_request`: (a) parse `cf-cache-status`/`age`/`cache-control`; (b) classify HIT vs MISS-then-HIT (warmed) vs DYNAMIC/BYPASS (flagged); (c) range byte-parity match vs mismatch (mismatch → flag/raise); (d) cold/warm timings are recorded (`cold_ms`/`warm_ms` present) (FAILS until T008).

### Implementation for User Story 3

- [x] T008 [US3] In `src/ohbm2026/atlas_hosting/compare.py`, add cache-evidence capture: issue each probe twice (cold→warm) for a representative full GET and ≥1 inner-table Range, record the [data-model](./data-model.md) fields (`cf_cache_status`, `age`, `cache_control`, `cached`, `warmed`, `cold_ms`, `warm_ms`, `range_byte_parity`, `flag`) — including the wall-clock cold/warm timings for the SC-003 latency-drop measurement — flag BYPASS/DYNAMIC and range-parity mismatches; preserve the existing reachability/Range/CORS/If-None-Match probes.
- [x] T009 [US3] In `src/ohbm2026/cli.py` (`compare-data-hosting`), surface the cache section in the comparison report (`data/outputs/data-hosting-comparison__<ts>.json`) + a human-readable "edge-cache-effective?" summary, and make a bypassing/parity-failing host flag explicitly (non-zero or clearly-failing aggregate) via `DataHostingCacheError` where appropriate; guard/skip clearly when creds/host are absent (CA-006/CA-007).

**Checkpoint**: a single `compare-data-hosting` run audits cache effectiveness for full + range, before and after the host rule.

---

## Phase 5: User Story 1 — Cached data loads (Priority: P1)

**Goal**: actually enable host caching (the Cloudflare rule) and prove repeat full + range requests are edge-served, byte-identical, faster — without changing the production channel.

**Independent Test**: with the rule applied, `compare-data-hosting` reports warm HIT on full + range with byte-parity and intact CORS; the Cloudflare dashboard cached-rate moves off 0%.

**Dependency**: US3 tooling (T008/T009) proves it; US2 provenance records the policy the rule respects.

### Implementation for User Story 1

- [x] T010 [US1] Finalize `specs/022-r2-edge-caching/contracts/cloudflare-cache-rule.md` as the reproducible host-rule spec (scope = `aadata.cirrusscience.org`, eligible-for-cache, respect-origin `Cache-Control`, 206/Range cacheable, CORS preserved) and apply the rule to the zone (dashboard by default; API automation only if `CLOUDFLARE_API_TOKEN` is in `.env`).
- [x] T011 [US1] Run `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli compare-data-hosting` BEFORE (expect BYPASS flagged) and AFTER applying the rule (expect warm HIT on full + range, byte-parity, CORS intact); record the after-report as the acceptance evidence (SC-001/003/004/005/006).

**Checkpoint**: the R2 host is edge-cache-effective; production channel still Dropbox (FR-009).

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T012 [P] Docs (CA-003): update README + `specs/020-cloudflare-r2-migration` notes with the cache rule + `compare-data-hosting` cache verification; close out `memory/cloudflare_cache_unused.md` once verified.
- [x] T013 Run the full atlas_hosting suite: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_atlas_hosting_compare tests.test_atlas_hosting_r2_client tests.test_atlas_hosting_manifest tests.test_atlas_hosting_cli tests.test_atlas_hosting_uploader -v`.
- [x] T014 Run `.specify/scripts/bash/constitution-check.sh --full`; verify no committed data/secrets (R2 + any Cloudflare token stay in `.env`), provenance records the policy, and error paths are explicit.
- [x] T015 Run `specs/022-r2-edge-caching/quickstart.md` end-to-end against the live host (before/after evidence) and attach the comparison report.

---

## Dependencies & Execution Order

- **Setup (P1)** → no deps.
- **Foundational (P2: T002)** → after setup; the error type is used by US3.
- **US2 (Phase 3, P1)** → after setup; independent of US1/US3 (pure code + provenance). Shippable MVP.
- **US3 (Phase 4, P2)** → after T002; the verification tooling.
- **US1 (Phase 5, P1)** → after US3 (its tooling proves the rule); benefits from US2 provenance. US1's "implementation" is config + an operator verification run.
- **Polish (Phase 6)** → after the desired stories.

### Within each story
- Tests/extensions written first and FAIL (except the T003 regression guard, which documents already-correct behavior) before implementation.
- `manifest.py` + `uploader.py` (T006) after the policy is exposed (T005).
- `compare.py` (T008) before the CLI surface (T009).

### Parallel opportunities
- T003 ∥ T004 (different test files).
- T012 ∥ most things (docs).
- US2 (Phase 3) and US3 (Phase 4) touch disjoint files (manifest/uploader/r2_client vs compare/cli) → can proceed in parallel once T002 lands.

## Parallel Example: User Story 2

```bash
# Tests first (parallel — different files):
Task: "Extend test_atlas_hosting_r2_client.py: assert immutable CacheControl ExtraArg (T003)"
Task: "Extend test_atlas_hosting_manifest.py: manifest records cache_control (T004)"
```

## Implementation Strategy

### MVP first
1. Setup → 2. Foundational (T002) → 3. **US2** (provenance + regression guard) → ship: every publish now records its immutable cache policy.

### Incremental delivery
1. US2 → provenance + guard.
2. US3 → the cache-evidence verification tooling.
3. US1 → apply the Cloudflare rule + verify HIT (the actual 0%→cached fix), proven by US3's tooling.

## Notes

- The upload already sets the immutable `Cache-Control` (single + multipart) — do NOT re-implement; T003 just guards it.
- The Cloudflare host rule is config, not committed code; T010 documents + applies it, T011 proves it.
- No committed data/secrets; R2 + any Cloudflare token stay in `.env`. Production channel stays Dropbox.
- Never let the cache check silently pass a bypassing host — flag/raise (CA-006/CA-007).
