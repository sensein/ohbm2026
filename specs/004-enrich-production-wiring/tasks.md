---

description: "Task list for Stage 2.1 — Production Wiring for Enrichment Components"
---

# Tasks: Stage 2.1 — Production Wiring for Enrichment Components

**Input**: Design documents from `/specs/004-enrich-production-wiring/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED for every behavior task (Principle IV + CA-002 in spec). Tests are authored first and must fail, then implementation makes them pass (red → green). No xfail / skip / weakened assertions to make CI green (Principle VI).

**Organization**: Tasks are grouped by Setup → Foundational → User Stories (P1 first, then P2) → Polish. US1 is the MVP bedrock; US2 (flex handling), US3 (model override), and US4 (agentic claims) are independent P1 slices that share the same orchestrator; US5 (image probe) and US6 (references throughput) are P2 operational efficiency wins.

**User stories** (from spec.md):
- **US1 (P1, MVP)** — Operator runs Stage 2.1 against the live accepted corpus and gets a fully-enriched SQLite.
- **US2 (P1)** — Flex-tier processing absorbs the cost win without silent data loss.
- **US3 (P1)** — Operator overrides the default model per component.
- **US4 (P1)** — Agentic claim extraction yields verified, ECO-annotated claims.
- **US5 (P2)** — Local image compression + quality probe reduce egress + flag bad scans.
- **US6 (P2)** — References finally go fast (wire-up to existing async pool).

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task primarily belongs to (US1–US6); omitted in Setup, Foundational, and Polish phases
- Every task includes an exact file path

## Path Conventions

- Library code: `src/ohbm2026/`
- Tests: `tests/` (existing `unittest`-based suite)
- Operator-facing wrappers: `scripts/`
- Docs: `docs/`, plus `README.md` and `CLAUDE.md` at repo root
- Spec artifacts: `specs/004-enrich-production-wiring/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm a clean pre-change baseline and install the new optional dependencies that the production runners need.

- [ ] T001 Refresh `.venv` and run baseline tests: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` — confirm only the pre-existing `test_plot_poster_layout_floorplan` failure (366 tests, 1 error).
- [ ] T002 [P] Run baseline lint: `.specify/scripts/bash/constitution-check.sh --full` — confirm exit 0 before any changes land.
- [ ] T003 Add the `[enrich]` optional extra to `pyproject.toml` with `openai>=2.0.0` and `Pillow>=10.0`. Keep `[parquet]` and `[review]` unchanged.
- [ ] T004 Install the new extra into the venv: `UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[enrich]"`. Verify `import openai; openai.__version__` is `>=2.0.0` and `import PIL; PIL.__version__` is `>=10.0`.

**Checkpoint**: Baseline is clean. Production-runner dependencies are installable.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared symbols every user-story phase depends on. No production-runner behavior yet.

**⚠️ CRITICAL**: No user-story implementation may start until this phase is complete.

- [ ] T005 [P] Create `src/ohbm2026/data/__init__.py` (empty file; makes the directory importable as `ohbm2026.data` for package-data loading).
- [ ] T006 [P] Create `src/ohbm2026/data/eco_top_codes.json` with the 9 ECO top-level codes (ECO:0000006, 0000041, 0000212, 0000352, 0000361, 0000501, 0006055, 0006151, 0007672). Each entry has `eco_id`, `label`, `definition`. File MUST validate against `specs/004-enrich-production-wiring/contracts/eco_top_codes.schema.json`. Use the labels listed in research.md §8 / spec FR-013.
- [ ] T007 [P] Create `tests/test_eco_vocabulary.py` with three tests: `test_vocabulary_file_validates_against_schema` (loads the contract schema, validates the JSON via stdlib `re` checks on every field that has a pattern — no `jsonschema` dep), `test_vocabulary_has_nine_codes`, `test_every_eco_id_matches_expected_pattern`. Tests fail before T006 lands.
- [ ] T008 [P] Create `src/ohbm2026/image_quality.py` stub with module docstring and four function signatures only (`laplacian_variance(image)`, `mean_brightness(image)`, `native_max_dim(image)`, `compression_ratio(original_bytes, compressed_bytes)`); each raises `NotImplementedError`. Test stub is T015.
- [ ] T009 [P] Create `src/ohbm2026/flex_tier.py` stub: module docstring, `class FlexTierResult` dataclass (`response`, `tier_used: Literal["flex","standard"]`, `flex_timed_out: bool`, `latency_ms: float`), `def call_with_flex_fallback(...) -> FlexTierResult` raising `NotImplementedError`. Test stub is T020.
- [ ] T010 [P] Create `src/ohbm2026/stage2_figures.py` stub: module docstring + `def run_figure_component(abstract, model_id, flex_enabled, ...) -> list[dict]` raising `NotImplementedError`. Test stub is T026.
- [ ] T011 [P] Create `src/ohbm2026/stage2_claims.py` stub: module docstring + `def run_claims_component(abstract, figure_interpretations, model_id, flex_enabled, ...) -> list[dict]` raising `NotImplementedError`. Test stub is T035.
- [ ] T012 [P] Create `src/ohbm2026/stage2_references.py` stub: module docstring + `def run_references_component(abstract, strategy_id, ...) -> list[dict]` raising `NotImplementedError`. Test stub is T044.

**Checkpoint**: All NEW module stubs exist; ECO vocabulary file lands; vocabulary tests fail intentionally (they reference functions in T006 that exist) — verify only T007 passes after T006, while T015/T020/T026/T035/T044 stubs raise on import-by-call.

---

## Phase 3: User Story 1 — MVP Production Run (Priority: P1) 🎯 MVP

**Goal**: End-to-end production run against a synthetic corpus produces a fully-enriched SQLite with all three components actually invoking their backends.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.IntegrationProductionWiringTests -v` — runs all three production runners (mocked at the OpenAI / openalex seams) against an N=3 synthetic corpus and verifies the SQLite contains the expected records with figure interpretations, claims, and references.

### Tests for User Story 1 (red phase first)

- [ ] T013 [P] [US1] Augment `tests/test_enrich_stage.py` with `IntegrationProductionWiringTests` class (3 tests): `test_clean_run_invokes_all_three_production_runners` (asserts each `run_*_component` is called the expected number of times), `test_provenance_carries_new_extension_fields` (validates `eco_vocabulary_version`, per-component tier counters, cost telemetry), `test_default_model_is_gpt_5_4_mini_for_both_llm_components` (asserts the per-component `model_id` in provenance). Patch `ohbm2026.stage2_figures.run_figure_component`, `ohbm2026.stage2_claims.run_claims_component`, `ohbm2026.stage2_references.run_references_component`. Use the existing `_RepoFixture` mixin pattern.
- [ ] T013a [P] [US1] Add a `ConcurrencyContractTests` class to `tests/test_enrich_stage.py` (drives FR-018, 3 tests): `test_concurrency_flag_caps_in_flight_requests` (assert no more than N requests in flight when `--concurrency-figures N` is set; use a counter inside a patched runner), `test_rate_limit_header_triggers_back_off` (synthesize a fake response with `x-ratelimit-remaining-tokens` below 10% of the limit; assert a typed back-off event was logged to stderr naming the component + limit family), `test_default_concurrency_is_30`.
- [ ] T014 [P] [US1] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.IntegrationProductionWiringTests tests.test_enrich_stage.ConcurrencyContractTests -v` and confirm the new tests fail with messages naming the missing wiring (e.g., `_call_figure_model` still raises NotImplementedError, provenance fields missing, no concurrency cap).

### Implementation for User Story 1

- [ ] T015 [US1] Implement `src/ohbm2026/image_quality.py`: Laplacian variance via Pillow's `ImageFilter.Kernel`, mean brightness via `ImageStat.Stat(im.convert('L')).mean[0]`, native max dim, compression ratio (raw bytes input). Match T008's signatures. Add `tests/test_image_quality.py` with synthetic-image tests: known-blurry image yields low variance, known-bright image yields high mean brightness, known-dim metadata, compression-ratio bounds 0..1.
- [ ] T016 [US1] Implement `src/ohbm2026/flex_tier.py`: `call_with_flex_fallback(client_call, *, flex_enabled, timeout_seconds, max_retries=2)` that (a) if `flex_enabled` sets the `service_tier="flex"` request kwarg, (b) catches OpenAI timeout / `service_unavailable` errors and retries on standard tier, (c) raises `EnrichmentError` after retry budget exhausted, (d) returns a `FlexTierResult` with `tier_used`, `flex_timed_out`, `latency_ms`. No async logic yet (per-call wrapper). Add `tests/test_flex_tier.py` with `_FakeClient` patches.
- [ ] T017 [US1] Implement `src/ohbm2026/stage2_figures.py` production path:
  - load + compress figures via `image_quality.py` (JPEG q85 @ 1024 px in-memory; canonical PNG read-only);
  - build per-abstract Responses API request: system message instructions + user message with manuscript markdown + user message with the N images;
  - call `flex_tier.call_with_flex_fallback` wrapping `client.responses.parse(text_format=FigureInterpretationResponse, ...)`;
  - assemble per-figure dicts matching the Stage 2.1 `FigureInterpretation` shape (figure_url, local_path, question_name, interpretation, keywords, ocr_text, model_quality_estimate, local_quality_estimate, model_id, cache_key);
  - return the list to the orchestrator.
- [ ] T018 [US1] Implement `src/ohbm2026/stage2_claims.py` production path:
  - build per-abstract Responses API request with three function tools registered (`verify_source_quote`, `lookup_eco_code`, `dedupe_check`);
  - tools are orchestrator-side Python callables (see T021 for handlers);
  - call `flex_tier.call_with_flex_fallback` wrapping `client.responses.parse(text_format=ClaimsResponse, tools=[...], ...)`;
  - validate every returned claim's `evidence_eco_codes` against the embedded vocabulary; drop off-vocab claims with typed warning;
  - drop claims with `source_quote_verified=false` AND no successful candidate correction.
- [ ] T019 [US1] Implement `src/ohbm2026/stage2_references.py` production path: thin adapter that calls `openalex.collect_reference_metadata` with the abstract's reference block + strategy_id; converts the result to a list of `ReferenceResolution` dicts matching the Stage 2 schema.
- [ ] T020 [US1] Wire `enrich_stage._call_figure_model` → `stage2_figures.run_figure_component`, `enrich_stage._call_claims_model` → `stage2_claims.run_claims_component`, `enrich_stage._call_reference_strategy` → `stage2_references.run_references_component`. Remove the `NotImplementedError` raises. Extend `_run_figure_component` / `_run_claims_component` / `_run_references_component` to pass the flex configuration (default True), the per-component model ids (existing args), the embedded ECO vocabulary path (for claims), and the manuscript context (for figures).
- [ ] T020a [US1] Implement the async concurrency wrapper + rate-limit back-off in `src/ohbm2026/enrich_stage.py` (drives FR-018). Add a `_run_component_concurrent(abstracts, runner, concurrency, on_rate_limit_event)` helper that fans out `runner(abstract)` calls via `concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)` and inspects each call's OpenAI response headers (returned alongside the runner's payload via a small `_LastResponseHeaders` thread-local). When `x-ratelimit-remaining-tokens` OR `x-ratelimit-remaining-requests` drops below 10% of `x-ratelimit-limit-*`, pause new submissions for the response's `x-ratelimit-reset-*` window AND emit a typed stderr line: `RATE_LIMIT_BACKOFF component=<name> limit_family=<tokens|requests> reset_seconds=<float>`. Per-component runners (stage2_figures, stage2_claims) expose the response-header dict on each call so the orchestrator-level wrapper can read it.
- [ ] T021 [US1] In `src/ohbm2026/stage2_claims.py`, declare the three function-tool handler **signatures** (no bodies) and register them with the Responses API via `openai.pydantic_function_tool(handler_callable, name=..., description=...)`. The SDK derives each tool's JSON schema from the handler's Pydantic input/output models. Bodies land in T035 (US4 phase).
- [ ] T022 [US1] Extend the Stage 2 provenance assembly in `enrich_stage.py`:
  - add `eco_vocabulary_version` at the top level (read from the embedded JSON's `vocabulary_version` field);
  - extend every `components` entry with `flex_tier_enabled`, `flex_timeout_count`, `tier_fallback_count`, `retry_exhaustion_count`, `prompt_tokens_cached`, `prompt_tokens_uncached`, `completion_tokens`, `wall_clock_seconds`, `latency_p50_ms`, `latency_p95_ms`;
  - per-component runners return a `RunSummary` dataclass (new in `enrich_stage.py`) the orchestrator accumulates into the provenance counters.
- [ ] T023 [US1] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.IntegrationProductionWiringTests -v` and confirm all three tests PASS (green phase). If failures, fix the implementation — do NOT weaken the test.

**Checkpoint**: Stage 2.1 is functional end-to-end against synthetic fixtures. SQLite output carries the new fields; provenance carries the new counters.

---

## Phase 4: User Story 2 — Flex-Tier Resilience (Priority: P1)

**Goal**: Flex-tier timeout is absorbed by the standard-tier retry; retry exhaustion escalates through the existing component-failure-threshold logic.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_flex_tier tests.test_enrich_stage.FlexTierContractTests -v` — simulates flex timeouts and verifies fallback paths.

### Tests for User Story 2 (red phase first)

- [ ] T024 [P] [US2] Add `FlexTierContractTests` class to `tests/test_enrich_stage.py` (4 tests):
  - `test_flex_timeout_falls_back_to_standard_tier` — patch the figure runner to raise a timeout on first attempt, succeed on second; assert success + provenance `tier_fallback_count==1`.
  - `test_no_flex_figures_flag_disables_flex` — pass `--no-flex-figures`; assert provenance `components[figures].flex_tier_enabled==false`.
  - `test_retry_exhaustion_raises_component_failure` — patch runner to always raise timeout; assert orchestrator exits with `ComponentFailureThresholdError` once threshold exceeded; assert SQLite NOT written.
  - `test_provenance_carries_tier_counters` — basic clean run; assert `flex_timeout_count`, `tier_fallback_count`, `retry_exhaustion_count` all present and integer.

### Implementation for User Story 2

- [ ] T025 [US2] Augment `tests/test_flex_tier.py` (started in T016) with: timeout-on-first-call retries-on-standard tests, retry-budget-exhausted test, tier-counter-increment test, latency-measurement test. Verify `FlexTierResult` carries correct `tier_used` / `flex_timed_out` / `latency_ms`.
- [ ] T026 [US2] Extend `enrich_stage._build_parser` to add `--no-flex-figures` and `--no-flex-claims` boolean flags (defaults to flex ON, flag negates) AND `--concurrency-figures INT` / `--concurrency-claims INT` (default 30 each, per FR-018). Thread the flex setting AND the concurrency cap through to the per-component runners (concurrency consumed by `_run_component_concurrent` from T020a). Verify CLI tests in `tests/test_cli.py` still pass.
- [ ] T027 [US2] Extend `stage2_figures.run_figure_component` and `stage2_claims.run_claims_component` to accept the `flex_enabled` parameter and forward it to `flex_tier.call_with_flex_fallback`. Per-call tier-counter increments accumulate into the per-component `RunSummary`.
- [ ] T028 [US2] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_flex_tier tests.test_enrich_stage.FlexTierContractTests -v` and confirm green.
- [ ] T028a [US2] Resume-from-interruption check (Principle III): run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.ResumabilityContractTests -v` (inherited from Stage 2) AND add one new test `test_production_wiring_preserves_caches_across_interruption` that (a) starts a run, (b) raises mid-loop after some cache entries have been written, (c) re-invokes `main()` and asserts the second run reuses the populated cache entries (zero LLM calls for already-cached abstracts). Confirms production wiring did not break Stage 2's resume guarantee.

**Checkpoint**: Flex-tier behavior + resumability both verified. SC-009, SC-010, and Stage 2 SC-009 (resume) all green.

---

## Phase 5: User Story 3 — Per-Component Model Override (Priority: P1)

**Goal**: Changing one component's model id invalidates only that component's cache; the other two stay 100% hits.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.ModelOverrideTests -v` — runs the orchestrator with default models, then re-runs with one component's model changed; verifies cache hit/miss counts.

### Tests for User Story 3 (red phase first)

- [ ] T029 [P] [US3] Add `ModelOverrideTests` class to `tests/test_enrich_stage.py` (3 tests):
  - `test_default_model_is_gpt_5_4_mini` — clean run; assert provenance's figures + claims components both list `model_id == "gpt-5.4-mini"`.
  - `test_claims_model_override_invalidates_only_claims_cache` — baseline run, then re-run with `--claims-model-id gpt-5.4`; assert figures+references caches 100% hit, claims cache 100% miss.
  - `test_figures_model_override_invalidates_only_figures_cache` — baseline run, then re-run with `--figure-model-id gpt-4.1-mini`; assert claims+references caches 100% hit, figures cache 100% miss.

### Implementation for User Story 3

- [ ] T030 [US3] Verify that `enrich_stage._build_parser` already exposes `--figure-model-id` / `--claims-model-id` / `--reference-strategy-id` (inherited from Stage 2). Update the defaults to `gpt-5.4-mini` for figures + claims; reference-strategy default stays `refs.v1+openai-gpt-5-nano` for v1 (operator-overridable). Verify the model id is part of every cache key computation in the per-component runners.
- [ ] T031 [US3] Update `enrich_stage._compute_state_key` (or its existing equivalent) to include the per-component model ids in the input fingerprint, so a model change shifts the state-key (which gates whether a previous enriched corpus is interpreted as "delta-vs-previous" vs "fresh").
- [ ] T032 [US3] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrich_stage.ModelOverrideTests -v` and confirm green.

**Checkpoint**: Per-component model override works; cache invalidation matrix verified.

---

## Phase 6: User Story 4 — Agentic Claims with ECO Annotation (Priority: P1)

**Goal**: Claims have verified source quotes (substring of manuscript) + ≥1 ECO code from v1 vocabulary; the model uses the three function tools internally.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_stage2_claims -v` — exercises the agentic loop end-to-end with mocked OpenAI responses that include synthetic tool-call traces.

### Tests for User Story 4 (red phase first)

- [ ] T033 [P] [US4] Create `tests/test_stage2_claims.py` with the following test classes:
  - `FunctionToolHandlerTests` (pure-function tests, no SDK): `test_verify_source_quote_finds_exact_match`, `test_verify_source_quote_returns_candidates_on_miss`, `test_lookup_eco_code_matches_label`, `test_lookup_eco_code_matches_definition`, `test_dedupe_check_jaccard_threshold`.
  - `AgenticClaimsExtractionTests`: `test_known_exact_substring_yields_verified_claim` (manuscript contains "we observed a 23% decrease in BOLD signal" verbatim; assert one claim with `source_quote_verified=true` and at least one ECO code), `test_off_vocabulary_eco_code_drops_claim` (synthetic response includes ECO:9999999; assert dropped + typed warning in stderr), `test_unverifiable_quote_with_no_candidate_drops_claim` (synthetic claim with quote not in manuscript; assert dropped), `test_empty_claims_list_is_legitimate` (abstract with no factual content; assert empty list, no failure), `test_idempotent_extraction` (run twice with same fixture; assert cache hit, zero second-call invocations).
  - `ClaimsResponseSchemaTests`: `test_response_validates_against_schema` (round-trip a synthetic response through Pydantic + the contract JSON schema), `test_missing_required_field_raises` (synthetic response missing `evidence_eco_codes`; assert `EnrichmentError`).
- [ ] T034 [P] [US4] Patch `client.responses.parse` at the `stage2_claims` import seam. Test fixtures use a `_fake_parsed_response(claims, tool_call_log, usage)` helper that constructs an SDK-shape object with `.output_parsed`, `.usage`, etc.

### Implementation for User Story 4

- [ ] T035 [US4] Implement the function-tool handlers in `stage2_claims.py` (signatures from T021, full bodies here). `_verify_source_quote_handler` splits manuscript on `[.!?]` for sentence-list candidates. `_lookup_eco_code_handler` reads the embedded vocabulary once at module load. `_dedupe_check_handler` uses `set(word.lower() for word in re.findall(r'\w+', text))` for tokens.
- [ ] T036 [US4] Implement the Responses API call wiring in `stage2_claims.run_claims_component`: system prompt instructs the model on the four-step extract → verify → annotate → dedupe loop; user message provides manuscript + figure interpretations + ECO vocabulary primer (the 9 codes' labels + definitions, ~600 tokens; eligible for prefix caching after abstract #1); `tools=[verify_source_quote, lookup_eco_code, dedupe_check]`; `text_format=ClaimsResponse` Pydantic model.
- [ ] T037 [US4] Post-response validation in `stage2_claims.run_claims_component`: for each returned claim, (a) re-verify `source_quote in manuscript` (don't trust the model's `source_quote_verified` field alone — verify independently), (b) confirm every `evidence_eco_codes` entry is in the embedded vocabulary's `codes[].eco_id` set, (c) drop claims that fail either check; log typed warnings naming the offending claim's first 80 chars.
- [ ] T038 [US4] Cache-key derivation for claims includes the ECO vocabulary version: `cache_key = sha256(manuscript_md || model_id || vocabulary_version)`. Changing the vocabulary version (v1 → v2 later) naturally invalidates claims caches.
- [ ] T039 [US4] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_stage2_claims -v` and confirm green.

**Checkpoint**: Agentic claims component is functional. SC-007 (95% verified) and SC-008 (100% ECO-annotated) verified against synthetic fixtures.

---

## Phase 7: User Story 5 — Local Image Compression + Quality Probe (Priority: P2)

**Goal**: Every figure is compressed locally to JPEG q85 @ 1024 px (in-memory) AND probed for quality before the model call. The canonical PNG on disk is never overwritten.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_stage2_figures -v` — exercises the figures path with synthetic PNGs and verifies compression + probe outputs.

### Tests for User Story 5 (red phase first)

- [ ] T040 [P] [US5] Create `tests/test_stage2_figures.py` with the following test classes:
  - `LocalCompressionTests`: `test_compresses_3mb_png_to_under_300kb` (use Pillow to synthesize a 3 MB random-pattern PNG; assert post-compression bytes < 300 KB), `test_canonical_png_unchanged_after_run` (snapshot PNG bytes pre- and post-run; assert byte-identical), `test_long_side_capped_at_1024_px` (synthesize a 4000×3000 PNG; assert compressed image dimensions ≤ 1024 long side).
  - `LocalQualityProbeTests`: `test_local_quality_estimate_present_on_every_figure`, `test_laplacian_variance_low_on_blurred_input`, `test_brightness_in_documented_range`, `test_compression_ratio_in_0_to_1`.
  - `PerAbstractGroupingTests`: `test_single_call_per_abstract` (synthetic abstract with 2 figures; assert exactly 1 call to `client.responses.parse`), `test_manuscript_context_attached` (assert the request payload includes the manuscript text), `test_figure_index_round_trips` (synthetic 3-figure abstract; assert response items in 1-based index order match request order).
  - `ModelQualityEstimateTests`: `test_off_enum_value_raises_enrichment_error` (synthetic response with `model_quality_estimate="terrible"`; assert raised), `test_enum_values_pass_through_to_record`.

### Implementation for User Story 5

- [ ] T041 [US5] Implement `stage2_figures.run_figure_component`'s compression path: read canonical PNG bytes (no write-back), open via Pillow, resize via `Image.LANCZOS` with long side capped (default 1024), encode JPEG q85 to `io.BytesIO`, base64-encode for OpenAI vision input. The original PIL Image and the original PNG bytes flow into the local quality probe BEFORE encoding so the probe sees pre-compression brightness/sharpness.
- [ ] T042 [US5] Implement local-quality assembly in `stage2_figures.run_figure_component`: populate the four-field `local_quality_estimate` dict per FR-007 / data-model.md §2. Add the dict to every `FigureInterpretation` record before persisting to cache.
- [ ] T043 [US5] Validate model's `model_quality_estimate` enum: the Pydantic `FigureInterpretationItem.model_quality_estimate` is `Literal[...]`, so off-enum values raise a Pydantic validation error which the runner re-raises as `EnrichmentError`. Add an integration assertion: a synthetic response with an off-enum value causes the run to count a per-figure failure (consistent with threshold logic).
- [ ] T044 [US5] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_stage2_figures -v` and confirm green.

**Checkpoint**: Image compression + quality probe verified. SC-006 (95% records carry both estimates), SC-011 (PNGs byte-identical before/after) verified.

---

## Phase 8: User Story 6 — References Throughput (Priority: P2)

**Goal**: `_call_reference_strategy` wires to the existing `openalex.py` async pool; the references stage runs at production throughput.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_stage2_references -v` — synthetic abstract with N=30 references; assert one call to `openalex.collect_reference_metadata` with the correct argument shape.

### Tests for User Story 6 (red phase first)

- [ ] T045 [P] [US6] Create `tests/test_stage2_references.py` with:
  - `ReferencesWireUpTests`: `test_run_references_component_calls_openalex_collect` (patch `openalex.collect_reference_metadata`; assert called once per abstract with the abstract's reference block + strategy_id), `test_returns_resolution_records_matching_stage2_schema`, `test_strategy_id_in_cache_key` (assert cache key derivation includes the strategy_id), `test_per_reference_failures_recorded` (synthetic resolution result with some `resolution_status="unresolved"`; assert recorded but does not abort the abstract).

### Implementation for User Story 6

- [ ] T046 [US6] Verify `openalex.collect_reference_metadata` (or its async equivalent) exists and exposes a stable signature taking `(reference_text, strategy_id, **opts)`. If the existing entry is async-only, wrap it with `asyncio.run(...)` in `stage2_references.run_references_component` so the orchestrator's synchronous loop can call it; the orchestrator-level concurrency-30 wraps multiple of these calls in parallel — the inner async pool handles per-reference parallelism for the SAME abstract.
- [ ] T047 [US6] Map the openalex resolution-result records to the Stage 2 `ReferenceResolution` schema (raw_reference, doi, pmid, openalex_id, title, authors, year, resolution_status, resolution_source, strategy_id, cache_key). Fields the openalex result already provides flow straight through; the `cache_key` is computed by the runner from `sha256(raw_reference || strategy_id)`.
- [ ] T048 [US6] Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_stage2_references -v` and confirm green.

**Checkpoint**: References component is wired. P2 stories complete.

---

## Phase 9: Doc Sync (Cross-Story)

**Goal**: Document Stage 2.1 across the project's doc surfaces and remove `cllm` references.

- [ ] T049 [P] Update `docs/per-stage-pattern.md`: append a "Stage 2.1 production wiring" paragraph at the bottom of the multi-component reference instance section. Cite `stage2_figures.py`, `stage2_claims.py`, `stage2_references.py`, `flex_tier.py`, `image_quality.py`, and `src/ohbm2026/data/eco_top_codes.json` by name.
- [ ] T050 Update `README.md` Stage 2 section: replace cllm install instruction with the `[enrich]` extra install command; document `gpt-5.4-mini` as the new default for both figures and claims; document `--no-flex-figures` / `--no-flex-claims`; document the ECO annotation surface; document the new provenance fields (eco_vocabulary_version, tier counters, cost telemetry); add the cost-estimation Python snippet from quickstart.md.
- [ ] T051 [P] Update `CLAUDE.md`: refresh the "Default pipeline state" section to mention `gpt-5.4-mini` as the figures + claims default and flex-tier on as the default; refresh the Module Layout to list `stage2_figures.py`, `stage2_claims.py`, `stage2_references.py`, `flex_tier.py`, `image_quality.py`. The `<!-- SPECKIT START -->` block was updated in `/speckit-plan`; no further edit needed unless this spec amends the design.
- [ ] T052 [P] Update `docs/reproducibility-vision.md` Reproduction Ladder Level 2: keep `ohbmcli enrich-abstracts` as the single step (no surface change at that level); add a parenthetical noting the new default model + flex tier.
- [ ] T053 [P] Remove `cllm` from any docs that still reference it (search: `git grep -nE "cllm|--llm-provider"` across `README.md`, `CLAUDE.md`, `docs/`, `quickstart.md`s). Note in the doc updates that Stage 2.1's agentic-call architecture is the new canonical path; pinning an older model id changes WHICH model runs the agentic loop but does NOT recover cllm's single-call zero-shot behavior (that design choice is not preserved).

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Verify the cross-cutting invariants from the constitution and from the spec's Success Criteria.

- [ ] T054 Run the full test suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`. Confirm green except the pre-existing unrelated `test_plot_poster_layout_floorplan` failure. No new failures, no skipped tests, no xfail markers (Principle VI, SC-012).
- [ ] T055 Run `.specify/scripts/bash/constitution-check.sh --full` and confirm exit 0 (SC-012).
- [ ] T056 Run `git status --porcelain` after staging — verify NO file under `data/`, `export/`, `tmp/`, `archive/`, `memory/archive/`, or `.claude/` was tracked or staged (Principle II, CA-005).
- [ ] T057 Provenance fixture audit: `git grep -nE "(\"|')(/Users/|/home/|~/)" -- tests/` returns nothing or only fixtures that ASSERT such paths are REJECTED (CA-008).
- [ ] T058 Live production run against the current accepted corpus: `PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py`. This is the canonical Stage 2.1 first-run that produces the new enriched SQLite. Verify the run completes within 75 minutes (SC-002), costs under $10 per the provenance cost telemetry (SC-003), and produces a SQLite where 95%+ of figure records have both quality estimates (SC-006), 95%+ of claims have `source_quote_verified=true` (SC-007), 100% of claims carry ≥1 ECO code (SC-008). Record observed values in the run's provenance.
- [ ] T059 FR-015 live mtime verification: capture `os.stat()` for `data/primary/abstracts.json`, `abstracts_withdrawn.json`, `authors.json`, `authors_withdrawn.json`, `data/inputs/abstracts_graphql_schema__*.json`, and a sample of `data/primary/assets/*.png` BEFORE T058. After T058 completes, re-stat them all and assert mtimes unchanged. Confirms Stage 2.1 maintains Stage 2's read-only access to Stage 1 outputs (SC-011).
- [ ] T060 SC-001 manual walkthrough: hand the updated README's Stage 2 section to an unfamiliar contributor and have them run Stage 2.1 end-to-end. Record any other documentation lookups required. Acceptance: zero docs lookups beyond the README's Stage 2 section. (Tracked in a manual-walkthrough issue.)
- [ ] T061 Idempotency live check: re-run T058's command immediately after T058 completes. Verify the second run finishes in seconds (only cache hits), produces a byte-identical SQLite (modulo provenance run-id + timestamp), and reports zero LLM calls in provenance (SC-004).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** — no dependencies; starts immediately.
- **Foundational (Phase 2)** — depends on Setup completion. BLOCKS all user-story phases. T005–T012 can run in parallel (different files).
- **US1 (Phase 3, MVP)** — depends on Foundational. T013/T014 (tests) are red-phase. T015–T022 (implementation) feed T023 (green verification). T015 + T016 are independent and can run in parallel; T017/T018/T019 build on them; T020/T021/T022 wire them into the orchestrator.
- **US2 (Phase 4)** — depends on US1 (the flex-tier helper lands in US1's T016). T024 is the red-phase test; T025–T027 add flag plumbing + tier-counter accumulation; T028 is green verification.
- **US3 (Phase 5)** — depends on US1. T029 red-phase; T030/T031 small wiring; T032 green.
- **US4 (Phase 6)** — depends on US1 (specifically T018 + T021). T033/T034 red-phase; T035–T038 implementation; T039 green.
- **US5 (Phase 7)** — depends on US1 (specifically T017). T040 red-phase; T041/T042/T043 implementation; T044 green.
- **US6 (Phase 8)** — depends on US1 (specifically T019). T045 red-phase; T046/T047 implementation; T048 green.
- **Doc Sync (Phase 9)** — depends on US1–US6 implementation being substantially complete. T049/T051/T052/T053 parallel; T050 is the bigger edit and is sequential within its lane.
- **Polish (Phase 10)** — depends on Phases 1-9 complete.

### Parallel Opportunities

- Phase 1: T002 + T003/T004 (T002 reads existing state; T003/T004 modify pyproject; mild conflict).
- Phase 2: T005–T012 all touch different files; all parallelizable.
- Phase 3: T013/T014 [P]; T015 + T016 [P]; T017/T018/T019 [P] (different files); T020/T021/T022 sequential (touch the same orchestrator module + provenance assembly).
- Phase 4: T024 [P]; T025/T026/T027 sequential; T028 sequential.
- Phase 5: T029 [P]; T030/T031 sequential; T032 sequential.
- Phase 6: T033/T034 [P]; T035–T038 [P] on the same file but logically sequential (handlers → call wiring → validation → cache key); T039 sequential.
- Phase 7: T040 [P]; T041/T042/T043 sequential on the same file; T044 sequential.
- Phase 8: T045 [P]; T046/T047 sequential; T048 sequential.
- Phase 9: T049 + T051 + T052 + T053 all [P] on different files; T050 sequential.
- Phase 10: T054 + T055 + T056 + T057 all [P]; T058–T061 sequential.

### User Story Dependencies

- **US1 (P1, MVP) BEFORE everything**: US2–US6 all build on the production-runner scaffolding US1 establishes.
- **US2 / US3 / US4 / US5 / US6 INDEPENDENT** after US1 lands. Each tests a distinct property of the orchestrator (flex resilience, model-override cache matrix, agentic claims, image-quality probe, references throughput) and adds its own tests + small implementation touch.
- **Per Principle IV**, tests precede behavior change in every user-story phase.

---

## Implementation Strategy

### MVP First

The MVP is **US1** — Stage 2.1 produces a fully-enriched SQLite against the live corpus, replacing the `NotImplementedError` stubs. US2–US6 are properties of the same wiring, layered on top.

1. Complete Phase 1 (Setup) and Phase 2 (Foundational). Commit.
2. Complete Phase 3 (US1 — tests + implementation). Commit after each major file (eco_top_codes.json, image_quality.py, flex_tier.py, stage2_*.py, enrich_stage.py wiring).
3. Run Phase 10's T058 (live smoke run) — at this point the orchestrator works end-to-end with mocked-tier defaults. Capture the cost + wall-clock for the baseline.
4. Add Phase 4 (US2 flex resilience), Phase 5 (US3 model override), Phase 6 (US4 agentic claims), Phase 7 (US5 image probe), Phase 8 (US6 references throughput) — each as its own commit with its own test set landing first.
5. Complete Phase 9 (doc sync). Commit.
6. Complete Phase 10 (polish + live verification). Commit if any small fixes needed.

### Commit cadence (Principle V)

- Every verified slice gets its own commit with a descriptive message.
- Do NOT batch unrelated phases into one commit.
- Each commit MUST contain only source / docs / tests / specs — never data, caches, exports, or downloaded assets.
- The `.githooks/pre-commit` constitution lint runs automatically on every commit.

### Parallel team strategy

With multiple contributors:
- Contributor A: Phase 2 (foundational stubs + ECO file) + Phase 3 T015 (image_quality.py) + Phase 3 T016 (flex_tier.py).
- Contributor B: After Phase 2, T017 (stage2_figures.py) + T041–T043 (US5).
- Contributor C: After Phase 2, T018 + T021 (stage2_claims.py + handlers) + T035–T038 (US4).
- Contributor D: After Phase 3 T020 lands, Phase 9 docs.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks.
- `[Story]` label maps task to user story for traceability.
- Tests are written first and MUST fail before implementation begins (Principle IV).
- Commit early and often: each validated slice gets its own descriptive commit; do not batch hours of work into one commit (Principle V).
- Commits MUST NOT include data, caches, exports, downloaded assets, or secrets (Principle II). The `.githooks/pre-commit` constitution lint catches the automatable subset.
- Never silence failures or bypass verification gates to make a task look done; surface the error and address the root cause (Principle VI). No `--no-verify`, no skipped tests, no xfail-as-shortcut.
- All Python invocations run through `.venv/bin/python` or `uv` targeting that interpreter (Principle I, FR-017).
- External-state discovery is part of the contract: LLM response schemas validated at parse time; flex-tier availability discovered at runtime via response headers; ECO codes validated against the embedded vocabulary (Principle VII, CA-007).
- Provenance record paths are project-relative; no absolute or `~`-prefixed paths reach disk (Principle VIII, CA-008).
- T058 (live smoke run) costs real OpenAI money (~$5 per the spec's estimate). Do it once, capture the provenance, and use cached re-runs (T061) for subsequent verifications.
