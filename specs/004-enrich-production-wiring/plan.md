# Implementation Plan: Stage 2.1 — Production Wiring for Enrichment Components

**Branch**: `004-enrich-production-wiring` | **Date**: 2026-05-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-enrich-production-wiring/spec.md`

## Summary

Stage 2.1 wires production component runners into the orchestrator
that Stage 2 left as `NotImplementedError` stubs. Three components,
one canonical API choice each:

- **Figures**: OpenAI Responses API call grouped per abstract,
  manuscript text as context, all of an abstract's figures attached
  to a single request after in-memory JPEG-q85 compression and a
  local quality probe (Laplacian variance + brightness + native
  max-dim + compression ratio).
- **Claims**: OpenAI Responses API call per abstract with three
  orchestrator-side function tools (`verify_source_quote`,
  `lookup_eco_code`, `dedupe_check`) and a strict Pydantic
  structured-output schema. The model orchestrates extract →
  tool-verify → review → tool-annotate → dedupe internally within
  the single API call.
- **References**: wire `_call_reference_strategy` to the existing
  async resolution pipeline in `openalex.py`; no new resolution
  logic.

Default model for both LLM-backed components: **`gpt-5.4-mini`**
(operator-overridable per component). OpenAI **flex processing tier
defaults to ON** for both LLM-backed components, with per-component
disable flags and graceful timeout handling (per-request timeout →
standard-tier retry → typed component error after retry-budget
exhaustion).

A small embedded data file ships the Evidence and Conclusion
Ontology v1 controlled vocabulary (9 top-level codes under
ECO:0000000); the claims component's `lookup_eco_code` tool draws
from it without network access at run time.

Per-component caches and SQLite-storage contracts are unchanged
from Stage 2; cache keys naturally invalidate when the model id
changes. No backfill of legacy bulk caches is required (and none
would match the new key namespace anyway).

The implementation follows the per-stage pattern; Stage 2 already
satisfies the six contracts. Stage 2.1 lands inside the existing
`enrich_stage.py` orchestrator surface, splits the three
component runners into their own files (`stage2_figures.py`,
`stage2_claims.py`, `stage2_references.py`) to keep each component's
~300-line implementation independently testable, and uses
`openai>=2.0.0` (the version that ships the Responses API surface)
plus `Pillow>=10.0` for image compression. Both are added under
the existing `[enrich]` optional extra (NEW — created in this
spec). Existing `[parquet]` extra remains unchanged.

## Technical Context

**Language/Version**: Python 3.11.
**Primary Dependencies**: stdlib (`asyncio`, `concurrent.futures`,
  `hashlib`, `json`, `pathlib`, `tempfile`, `time`, `os`); `openai
  >=2.0.0` for the Responses API (`client.responses.create`,
  `client.responses.parse`); `Pillow >= 10.0` for in-memory JPEG
  compression and the local quality probe; existing modules
  (`ohbm2026.artifacts`, `ohbm2026.exceptions`,
  `ohbm2026.enrich_storage`, `ohbm2026.openalex`).
**Storage**:
  - Enriched corpus unchanged: SQLite at
    `data/primary/abstracts_enriched.sqlite` (zlib(json) per row).
  - Per-component caches unchanged: `data/cache/figure_analysis/`,
    `data/cache/claim_analysis/`, `data/cache/reference_metadata/`.
  - Provenance unchanged path; schema EXTENDED with per-component
    tier counters (`flex_timeout_count`, `tier_fallback_count`,
    `retry_exhaustion_count`), cost telemetry (`prompt_tokens_*`,
    `completion_tokens`, `wall_clock_seconds`, `latency_p50_ms`,
    `latency_p95_ms`), and ECO vocabulary version
    (`eco_vocabulary_version`).
  - ECO v1 vocabulary embedded at
    `src/ohbm2026/data/eco_top_codes.json` (source, NOT a generated
    artifact — committed to the repo).
**Testing**: existing `unittest` suite under `tests/`; new tests
  follow the existing patching patterns (`tests/test_enrich_stage.py`
  augmented; new `tests/test_stage2_figures.py`,
  `tests/test_stage2_claims.py`,
  `tests/test_stage2_references.py`). All OpenAI calls patched at
  the `client.responses.create` / `client.responses.parse` seam.
**Target Platform**: macOS / Linux developer workstations and CI.
**Project Type**: single-project Python CLI + library (same as
  Stage 2).
**Performance Goals**:
  - Full corpus fresh run under 75 minutes wall-clock (SC-002).
  - Full corpus fresh run under USD 10 OpenAI spend (SC-003).
  - 95% of figure records carry both quality estimates (SC-006).
  - 95% of claims have verified source quotes (SC-007).
  - 100% of claims carry ≥1 ECO code from the v1 vocabulary
    (SC-008).
**Constraints**:
  - `gpt-5.4-mini` available at the operator's OpenAI tier; flex
    tier accessible (or operator disables via flag).
  - 2808 abstracts have ≥1 figure; ~4694 figure URLs in the
    corpus; figures are grouped by abstract so the per-call image
    count is bounded (median 1-2, max ~5).
  - No new third-party deps beyond what is already required for
    a production OpenAI integration (i.e., `openai` and `Pillow`).
**Scale/Scope**: 3244 accepted abstracts; ~4694 figure URLs;
  ~30k-50k reference lines.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Python execution uses `.venv/bin/python` or `uv` targeting it;
  no system Python.** PASS — FR-017 / CA-001.
- **Verification named first; expected to fail or be missing before
  implementation.** PASS — every user story has its red-phase test
  set named in the plan's Source Code section. The tasks.md
  (Phase 2 output) will land them as Phase 3 tasks before any
  production-runner implementation lands.
- **Output paths preserve auditability; canonical raw data not
  silently rewritten; recorded outputs go to fresh directories.**
  PASS — Stage 2.1 reuses Stage 2's canonical paths; the ECO
  vocabulary file is committed source (not a derived artifact);
  the figures component compresses in-memory only and never
  overwrites the canonical PNG (FR-006 / SC-011).
- **All generated artifacts land in gitignored roots; no new tracked
  artifact root.** PASS — `data/primary/`, `data/inputs/`,
  `data/cache/` are already gitignored. The ECO file is committed
  source under `src/ohbm2026/data/`, which is the existing
  package-data convention.
- **Error handling is explicit and loud; no bare excepts, silent
  fallbacks, or verification-gate bypasses.** PASS — FR-004 + FR-008
  + FR-012 + edge cases enumerate every failure mode. Typed
  exception hierarchy is the existing Stage 2 surface (no new error
  types; existing `EnrichmentError` and
  `ComponentFailureThresholdError` absorb the new cases).
- **External-state dependencies discovered at runtime; mismatches
  surface as precise errors, not silent skips.** PASS — CA-007 in
  the spec enumerates four discovery surfaces; flex-tier
  availability is discovered at runtime via OpenAI response
  headers; LLM response shapes are parsed against strict Pydantic
  schemas; `model_quality_estimate` enum + `evidence_eco_codes`
  vocabulary both validated at parse time.
- **Organizer-facing outputs ship machine-readable provenance with
  no absolute or user-home paths.** PASS — FR-015 extends the
  Stage 2 provenance schema with new fields; no path semantics
  change; `_assert_paths_safe` continues to gate every write.
- **Secrets in `.env` or env vars only; named, not embedded.** PASS
  — CA-004 / FR-017. `env_vars_consulted` in provenance lists
  names only.
- **README/docs/plan updates included when defaults/commands change.**
  PASS — FR-016 + CA-003.
- **Delivery commits each verified slice with descriptive message;
  pushed once requested change is complete.** PASS — same cadence
  as Stage 1 / Stage 2.

**Result: no violations. No Complexity Tracking rows required.**

## Project Structure

### Documentation (this feature)

```text
specs/004-enrich-production-wiring/
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0 — design decisions + measurements
├── data-model.md        # Phase 1 — entity field-level schemas (extensions to Stage 2)
├── quickstart.md        # Phase 1 — operator how-to-run Stage 2.1
├── contracts/           # Phase 1
│   ├── eco_top_codes.schema.json
│   ├── figure_response.schema.json
│   ├── claim_response.schema.json
│   └── provenance_extension.schema.json
├── spec.md              # /speckit-specify output (already on disk)
├── checklists/
│   └── requirements.md  # spec quality checklist (all 16 items pass)
└── tasks.md             # /speckit-tasks output — NOT created here
```

### Source Code (repository root)

```text
src/ohbm2026/
├── enrich_stage.py        # MODIFIED: _call_figure_model,
│                          #   _call_claims_model,
│                          #   _call_reference_strategy now delegate
│                          #   to the per-component modules below.
│                          #   Provenance assembly extended for the
│                          #   new tier counters + cost telemetry.
├── stage2_figures.py      # NEW — production figure-component runner:
│                          #   image compression, local quality probe,
│                          #   per-abstract grouping, manuscript-context
│                          #   prompt assembly, Responses API call
│                          #   with structured output schema, flex-tier
│                          #   logic + standard-tier fallback.
├── stage2_claims.py       # NEW — production claims-component runner:
│                          #   Responses API call w/ function tools
│                          #   (verify_source_quote, lookup_eco_code,
│                          #   dedupe_check), structured output schema,
│                          #   flex-tier logic + standard-tier fallback.
├── stage2_references.py   # NEW — production references runner that
│                          #   wires _call_reference_strategy to the
│                          #   existing openalex.py async pool. Thin
│                          #   adapter; no new resolution logic.
├── flex_tier.py           # NEW — shared retry/fallback helper that
│                          #   wraps an OpenAI Responses call with the
│                          #   per-request timeout, the standard-tier
│                          #   retry, and the tier-counter bookkeeping.
│                          #   Each component imports + parameterizes
│                          #   this helper.
├── image_quality.py       # NEW — pure-function helpers for the local
│                          #   image quality probe (Laplacian variance,
│                          #   mean brightness, native max dim,
│                          #   compression ratio). No I/O.
├── data/                  # NEW package-data subdirectory.
│   └── eco_top_codes.json # NEW — the 9-code ECO v1 vocabulary,
│                          #   committed source. Validated against
│                          #   contracts/eco_top_codes.schema.json.
├── enrichment.py          # UNCHANGED — wrapped, not refactored (per
│                          #   research.md §9 of Stage 2).
└── openalex.py            # UNCHANGED — wrapped, not refactored.

scripts/
└── run_enrich_abstracts.py # UNCHANGED — same wrapper, now wires to
                            #   the production runners by default.

tests/
├── test_enrich_stage.py    # MODIFIED — existing tests still pass;
│                           #   new fixtures expose the production
│                           #   seams (mock client.responses.create).
├── test_stage2_figures.py  # NEW — image compression + local quality
│                           #   probe + per-abstract grouping +
│                           #   manuscript-context attachment +
│                           #   structured-output schema enforcement +
│                           #   flex-tier fallback (US1 / US5 /
│                           #   partial US2).
├── test_stage2_claims.py   # NEW — agentic Responses API call +
│                           #   three function-tool handlers +
│                           #   source-quote verification +
│                           #   ECO annotation + dedupe loop +
│                           #   structured-output schema +
│                           #   flex-tier fallback (US1 / US4 /
│                           #   partial US2).
├── test_stage2_references.py # NEW — async-pool wire-up smoke test
│                           #   (US6).
├── test_flex_tier.py       # NEW — shared retry/fallback helper:
│                           #   timeout path, retry-budget path,
│                           #   tier-counter increment path,
│                           #   typed-error escalation path
│                           #   (US2 / SC-009 / SC-010).
├── test_image_quality.py   # NEW — pure-function probe tests
│                           #   (Laplacian variance correctness on
│                           #   known synthetic inputs, brightness
│                           #   range, compression-ratio bounds).
└── test_eco_vocabulary.py  # NEW — embedded vocabulary file matches
                            #   the schema, ≥9 entries, all entries
                            #   have ECO IDs of the documented form.

pyproject.toml             # MODIFIED — adds [enrich] optional extra
                           #   carrying `openai>=2.0.0` and
                           #   `Pillow>=10.0`. Existing `[parquet]`
                           #   extra unchanged. The legacy
                           #   `cllm` install instruction is
                           #   removed from README + CLAUDE.md.

docs/
└── per-stage-pattern.md   # MODIFIED — appends a Stage 2.1 paragraph
                           #   to the multi-component reference
                           #   instance section.
```

**Structure Decision**: split the three component runners into
their own files (`stage2_figures.py`, `stage2_claims.py`,
`stage2_references.py`) rather than packing the production logic
into `enrich_stage.py`. The orchestrator already exposes thin
`_call_*` seams; the per-component modules behind those seams
need their own test surfaces, their own structured-output schemas,
and their own flex-tier wrappers. Keeping the three component
modules siblings of the orchestrator (rather than nested under
e.g. `enrich/`) matches the existing flat layout. The shared
flex-tier retry helper and the local-image-quality helper are
small enough (~150 LOC each) to live as standalone modules with
their own focused test files.

## Complexity Tracking

> Constitution Check passes with no violations. No rows required.
