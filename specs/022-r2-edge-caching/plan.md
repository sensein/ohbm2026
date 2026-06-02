# Implementation Plan: Edge caching for the R2 data host

**Branch**: `022-r2-edge-caching` | **Date**: 2026-06-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/022-r2-edge-caching/spec.md`

## Summary

Make the R2-hosted UI data bundle (`https://aadata.cirrusscience.org`, Stage 20) actually served from the Cloudflare edge cache, verifiably, without breaking the per-table Range-fetch loader or byte-parity, and without changing the production data channel (Dropbox stays default).

**Key code-reality finding (drives the whole plan):** the publish side already does the right thing. `atlas_hosting/r2_client.py` uploads every object via boto3 `upload_file` with `ExtraArgs={"ContentType": …, "CacheControl": "public, max-age=31536000, immutable"}` (`r2_client.py:185`), and `upload_file` applies ExtraArgs to **both** single-part and multipart transfers — so **every** published object (incl. the large vectors sidecar) already carries the immutable cache policy. **US2 is therefore "verify + record in provenance", not "implement".**

The actual cause of the 0% cache rate is **Cloudflare-side**: an R2 custom domain is **not** edge-cached by default, and Range (HTTP 206) responses are commonly bypassed. So the real work is:

1. **Enable host caching** (FR-008) — a documented Cloudflare Cache Rule for the `aadata.cirrusscience.org` host (eligible-for-cache, respect origin `Cache-Control`, cache 206/partial). This is infrastructure config, not repo code; the repo deliverable is precise, reproducible documentation (manual dashboard by default; the Cloudflare API path is an optional stretch gated on a token in `.env`).
2. **Verify it** (US3 / FR-006/007) — extend the existing `compare-data-hosting` evidence command (`atlas_hosting/compare.py`) to capture `cf-cache-status` / `age` / `cache-control` for full **and** range requests, flag bypass, and assert range byte-parity. This is the auditable before/after and the main repo-code deliverable.
3. **Provenance** (FR-010) — record the applied cache policy in the upload manifest so a published bundle's cache policy is auditable.
4. **Regression guard** (US2) — a unit test asserting the uploader sets the immutable `CacheControl` on its `ExtraArgs` (locks in the already-correct behavior).

This is a **Track A / `ohbmcli atlas_hosting`** change (Python). No frontend changes — the site loader treats R2 URLs as opaque (Stage 20), so caching is transparent to it.

## Technical Context

**Language/Version**: Python 3.14 via `.venv/bin/python` (Constitution I).
**Primary Dependencies**: `boto3` (the optional `r2` extra — R2 S3 client, already used by Stage 20), `requests` (used by `compare.py` probes). Optional, only if the host rule is automated: a Cloudflare API client/`requests` call with a token.
**Storage**: Cloudflare R2 bucket + the `aadata.cirrusscience.org` custom domain (public base). Local evidence/provenance under gitignored `data/` roots.
**Testing**: stdlib `unittest` (`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`). Live cache verification is the `compare-data-hosting` run against the real host (network-gated, like Stage 20's compare).
**Target Platform**: CLI (`ohbmcli`), operator-run; the artifact is served to browsers via the CDN.
**Project Type**: Python pipeline (Track A, `src/ohbm2026/atlas_hosting/`).
**Performance Goals**: turn the 0% edge-cache rate into a high steady-state hit rate (≥90% of repeat requests, SC-001); warm/cache-served request materially faster than cold/origin (SC-003).
**Constraints**: must preserve the per-table Range/206 fetch pattern + CORS (FR-004/005); must NOT change the production channel (FR-009); long TTL is safe only because keys are content-addressed + immutable (Stage 20 guarantee).
**Scale/Scope**: the 4 content-addressed parquets per bundle; verification probes a representative full request + ≥1 inner-table range.

## Constitution Check

*GATE: must pass before Phase 0; re-checked after Phase 1.*

- **I. Venv-only Python** — uploader/compare/tests run through `.venv/bin/python` (`ohbmcli`). ✅
- **IV. Plan-first, test-first** — verification named before code: a unit test for the uploader's `CacheControl` ExtraArgs (US2 regression guard) and for the new cache-evidence parsing in `compare.py`; the live `compare-data-hosting` run is the acceptance check for the edge-cache outcome (run before/after the host rule). ✅
- **II. Immutable evidence / no committed data** — the comparison report + upload manifest land under gitignored `data/outputs/` & `data/provenance/`; no new committed data. ✅
- **VI. Fail loudly** — a publish that can't set the policy, and a cache check that finds bypass or a range byte mismatch, MUST raise/flag (extend the typed `Stage20Error` subtree; no bare except, no silent pass). ✅
- **VII. Discover external state** — cache effectiveness is read from real response metadata (`cf-cache-status`/`age`/`cache-control` on live full+range requests), not inferred from config; mismatch → explicit flag. ✅
- **VIII. Provenance** — the applied cache policy is recorded in the upload manifest (FR-010), co-located, no absolute/home paths. ✅
- **V. Secrets** — R2 creds (and an optional Cloudflare API token) referenced by env-var name from `.env` only; never logged/committed. ✅
- **Docs (IV/CA-003)** — Stage 20 plan/README `atlas_hosting` notes, the R2 storage-layout + compare contracts, and the `cloudflare_cache_unused` memory item updated in the same change. ✅

**Result**: PASS — no violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/022-r2-edge-caching/
├── plan.md            # This file
├── research.md        # Phase 0 — host cache rule, Range/206 caching, cache-status detection, upload-already-sets-policy, provenance
├── data-model.md      # Phase 1 — cache-evidence record + manifest cache-policy field
├── quickstart.md      # Phase 1 — enable rule + run compare-data-hosting before/after
├── contracts/
│   ├── cache-evidence-report.md     # extension to the comparison report (cache-status/age/policy + range parity)
│   └── cloudflare-cache-rule.md     # the exact host cache-rule settings (reproducible config)
├── checklists/requirements.md
└── tasks.md           # Phase 2 — /speckit-tasks (NOT created here)
```

### Source Code (repository root)

```text
src/ohbm2026/atlas_hosting/
├── r2_client.py     # UNCHANGED behavior — already sets immutable CacheControl on upload_file
│                    #   (single + multipart). Possibly expose the policy string for provenance.
├── uploader.py      # pass the applied cache policy through to the manifest (FR-010)
├── manifest.py      # record the cache policy on the upload manifest / channel entry (FR-010)
├── compare.py       # CORE: capture cf-cache-status / age / cache-control for full + range;
│                    #   flag bypass; assert range byte-parity (FR-006/007)
└── cli.py           # surface the cache evidence in `compare-data-hosting` output / exit semantics

src/ohbm2026/exceptions.py   # extend Stage20Error subtree if a new explicit cache-failure type is warranted

tests/
├── test_atlas_hosting_r2_client.py   # NEW/extend — assert upload ExtraArgs carry the immutable CacheControl (US2 guard)
├── test_atlas_hosting_compare.py     # NEW/extend — cache-status parsing, bypass flag, range byte-parity logic (mocked http)
└── test_atlas_hosting_manifest.py    # NEW/extend — manifest records the cache policy
```

```text
docs / config (no committed data):
- README + specs/020-cloudflare-r2-migration notes — cache rule + verification
- specs/022-r2-edge-caching/contracts/cloudflare-cache-rule.md — the reproducible host-rule settings
- memory/cloudflare_cache_unused.md — already points here; close it out when verified
```

**Structure Decision**: Single Python package change under `src/ohbm2026/atlas_hosting/` (Track A). The bulk is in `compare.py` (cache-evidence verification — pure header/byte logic, unit-testable with a mocked `http_request`), a small `manifest.py`/`uploader.py` provenance addition, and a `r2_client.py` regression test. The Cloudflare host cache rule is **configuration documented in a contract**, not code (optionally automated later via the Cloudflare API behind an `.env` token — out of default scope).

## Verification strategy (test-first)

- **US2 (policy on upload — already true)**: unit test asserts `R2Client.upload_*` passes `CacheControl="public, max-age=31536000, immutable"` in `ExtraArgs` (single + multipart config), so the behavior can't silently regress. `manifest` test asserts the policy is recorded.
- **US3 (verification)**: unit tests for the new `compare.py` logic with a mocked `http_request` — (a) parse `cf-cache-status`/`age`/`cache-control`; (b) classify hit vs miss vs **bypass** and flag bypass; (c) range byte-parity comparison (cached 206 bytes vs origin 206 bytes). Then the live `compare-data-hosting` run is the end-to-end acceptance (before rule = bypass flagged; after rule = hits on warm repeat).
- **US1 (cached data loads)**: validated by the live `compare-data-hosting` evidence (warm repeat = hit, faster, byte-identical) + the Cloudflare dashboard rate moving off 0% (SC-001).

The live cache checks are network-gated (skip/guard when creds/host absent, like Stage 20's compare), surfaced explicitly — never a silent pass (CA-006/CA-007).

## Phase 0 — Research

See [research.md](./research.md): (R-001) the exact Cloudflare host cache rule for an R2 custom domain incl. caching 206/partial responses + respecting origin `Cache-Control`; manual-vs-API decision; (R-002) how Range/206 caching behaves on Cloudflare and what the verification must assert; (R-003) detecting cache status from response metadata (`cf-cache-status`, `age`) robustly; (R-004) confirmation that `upload_file` already applies `CacheControl` to multipart (US2 already satisfied) + where to record it for provenance; (R-005) extending `compare.py`/`compare-data-hosting` vs. a new command.

## Phase 1 — Design & Contracts

- [data-model.md](./data-model.md) — the cache-evidence record (per-request cache-status/age/policy + range-parity) and the manifest cache-policy field.
- [contracts/cache-evidence-report.md](./contracts/cache-evidence-report.md) — the comparison-report extension (fields, pass/flag semantics, exit behavior).
- [contracts/cloudflare-cache-rule.md](./contracts/cloudflare-cache-rule.md) — the exact, reproducible host cache-rule settings + rationale (the FR-008 reproducible config).
- [quickstart.md](./quickstart.md) — enable the rule, run `compare-data-hosting` before/after, read the evidence.

Post-design Constitution re-check: unchanged — PASS (venv Python, loud errors, runtime-discovered cache state, provenance recorded, no committed data, no channel change).
