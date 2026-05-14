# Feature Specification: Stage 2.1 — Production Wiring for Enrichment Components

**Feature Branch**: `004-enrich-production-wiring`
**Created**: 2026-05-13
**Status**: Draft
**Input**: User description: "Stage 2.1 — wire production component runners for figures, claims, and references in `enrich_stage.py`. Default model `gpt-5.4-mini` for both figures and claims (per-component overridable). Flex processing on by default (per-component disable flag), with graceful timeout handling. Figures grouped by abstract with abstract context and local JPEG-q85 compression + local quality estimate. Claims drop cllm in favor of an agentic Responses API call with function tools (verify_source_quote, lookup_eco_code, dedupe_check) returning structured output annotated with ECO top-9 codes. References wire to the existing async pool. No cache backfill (new component versions naturally invalidate)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Operator runs Stage 2.1 against the live accepted corpus and gets a fully-enriched SQLite (Priority: P1) — MVP

After Stage 1 has produced `data/primary/abstracts.json`, an OHBM 2026
maintainer invokes the single Stage 2 entry point. The orchestrator
loads the accepted corpus, runs each accepted abstract through the
three production component runners (figures, claims, references),
writes the enriched SQLite + provenance, and returns within an hour
at a documented cost.

**Why this priority**: this is the moment Stage 2 stops being a
test-only scaffold and starts producing the corpus the UI, search,
and clustering stages consume. Without it, Stage 3+ work cannot
move forward against fresh data.

**Independent Test**: against a small synthetic accepted corpus
(N=10 abstracts; 6 with figures; mixed reference styles), run the
production orchestrator with the default model. Verify the
enriched SQLite contains every accepted abstract once, each with
non-empty enrichment lists where the corresponding input exists,
and that the run completes in seconds (not the full 45-minute
wall-clock — the synthetic fixture is small).

**Acceptance Scenarios**:

1. **Given** the live accepted corpus and a valid `OPENAI_API_KEY`,
   **When** the operator runs the orchestrator with defaults,
   **Then** the run completes successfully, the enriched SQLite is
   written at the canonical path, and the provenance record names
   the production model identifiers AND the flex-tier setting per
   component.
2. **Given** the same state, **When** the operator inspects a
   sampled enriched record, **Then** each `figure_interpretation`
   entry carries both a `local_quality_estimate` (set BEFORE the
   model call) and a `model_quality_estimate` (set by the model)
   and the figure was interpreted in the context of its parent
   abstract's manuscript text, not in isolation.
3. **Given** the same state, **When** the operator inspects a
   sampled enriched record, **Then** each `claims` entry carries
   ≥1 ECO evidence code from the v1 controlled vocabulary, a
   verified source quote (with the verification flag populated by
   the in-call function tool), and a model self-confidence rating.

---

### User Story 2 — Flex-tier processing absorbs the cost win without silent data loss (Priority: P1)

The orchestrator runs both LLM-backed components on OpenAI's flex
tier by default. Flex requests have non-deterministic latency and
can time out; the orchestrator handles those cases without losing
records or silently degrading quality.

**Why this priority**: flex tier is ~50% cheaper than standard
tier — a meaningful cost lever at corpus scale. But its
non-deterministic latency makes "fire-and-forget" implementations
fragile; the spec needs to pin the fail-loud semantics so a
half-finished run never gets confused with a complete one.

**Independent Test**: against a synthetic corpus, simulate a flex
timeout for one figure request and one claims request. Verify the
orchestrator retries on the standard tier after a configurable
number of flex attempts, logs the tier-fallback decision in
provenance, and completes the run with both records correctly
enriched. Separately, simulate persistent flex failure beyond
the retry budget on one component; verify the typed component
failure escalates through the existing component-failure-
threshold logic and the run exits non-zero without writing a
partial enriched corpus.

**Acceptance Scenarios**:

1. **Given** flex defaults are on, **When** a flex request for
   one abstract's figures returns a timeout, **Then** the
   orchestrator falls back to standard-tier processing for that
   abstract's retry attempt and the provenance record contains
   tier-fallback counters per component.
2. **Given** flex defaults are on, **When** the operator passes
   `--no-flex-figures`, **Then** the figures component runs only
   on the standard tier and the provenance records that choice.
3. **Given** flex defaults are on, **When** persistent flex
   failures + standard-tier retries exhaust the retry budget for
   one component across enough abstracts, **Then** the component
   failure rate crosses its threshold, the orchestrator exits
   non-zero with the typed component-failure error, and the
   previous enriched corpus on disk (if any) is left intact.

---

### User Story 3 — Operator overrides the default model per component (Priority: P1)

An operator wants to use a different model for one component
(e.g., the latest `gpt-5.4` for claims while keeping
`gpt-5.4-mini` for figures, OR an older `gpt-4.1-mini` for both
to reproduce an archived corpus). The orchestrator respects the
override AND the per-component cache invalidates only for the
component whose model id changed.

**Why this priority**: model choice is the dominant cost / quality
lever. Operators need to be able to A/B different models or pin
an older model for reproducibility. P1 because reproducibility
is a constitutional requirement (Principle III) and ad-hoc
overrides must not corrupt other components' caches.

**Independent Test**: complete a baseline run with defaults.
Re-run with `--claims-model-id gpt-5.4` only. Verify provenance
shows the figures cache had 100% hits and the claims cache had
100% misses; the new enriched corpus matches the baseline on
every record's figure fields and differs on claim fields only.

**Acceptance Scenarios**:

1. **Given** a baseline run with default models, **When** the
   operator changes the claims model identifier only,
   **Then** the claims cache is fully invalidated, figures and
   references are reused intact, and the provenance reflects the
   per-component model identifiers actually used.
2. **Given** the same baseline, **When** the operator pins both
   components to an older model identifier explicitly, **Then**
   the run reproduces the older corpus shape (modulo model
   non-determinism) and the provenance is sufficient to replay it
   on a different machine.

---

### User Story 4 — Agentic claim extraction yields verified, ECO-annotated claims (Priority: P1)

The claims component MUST produce claims whose source quotes are
literal substrings of the parent manuscript and whose evidence
type is annotated with at least one Evidence and Conclusion
Ontology (ECO) code from the v1 controlled vocabulary. The model
performs the verify-review-annotate loop internally; the
orchestrator only sees the final structured output.

**Why this priority**: the legacy cllm path was zero-shot, used
a coarse evidence vocabulary (5 free-form types), and never
verified that claim sources actually appeared in the source text
— producing hallucinated quotes that downstream consumers (search,
clustering, the UI's "claims about this abstract" surface) had
to filter. P1 because claim quality is the dominant quality
signal of the enriched corpus.

**Independent Test**: feed a synthetic abstract whose text
contains an exact known sentence. Verify the produced claim's
source quote exactly substring-matches the manuscript, the
verification flag is `true`, and the claim carries ≥1 ECO code
drawn from the v1 vocabulary. Separately, feed a synthetic
abstract whose extraction would (under a non-verifying baseline)
hallucinate a citation; verify the production run either drops
that claim OR corrects the source quote to a real substring of
the manuscript.

**Acceptance Scenarios**:

1. **Given** a manuscript that mentions "we observed a 23%
   decrease in BOLD signal", **When** the claims component runs,
   **Then** a claim about that observation exists in the output
   with a source quote that exactly substring-matches the
   manuscript and an ECO code drawn from the v1 vocabulary (most
   likely the experimental code).
2. **Given** the same manuscript run twice with the same model
   id, **When** the operator compares the two output claim lists,
   **Then** the two lists deduplicate to the same set of claims
   (the model uses the dedupe tool internally; later runs hit
   cache and return byte-identical output).
3. **Given** an abstract with no extractable factual claims,
   **When** the claims component runs, **Then** the output is an
   empty list with provenance recording that the abstract was
   processed (zero claims is a legitimate outcome, NOT a failure).

---

### User Story 5 — Local image compression + quality probe reduce egress + flag bad scans (Priority: P2)

Before each figure leaves the operator's machine, it is
compressed locally to a transmission-efficient form AND probed
for blur / contrast / native resolution so the operator can
audit which figures the model is being asked to interpret.

**Why this priority**: P2 because the system works without it,
but the win is large in practice: median figure drops from
~720 KB PNG to ~140 KB JPEG (~5× transmission reduction) and
local quality estimates expose figures the model would otherwise
hallucinate on. The local probe also gives the model a numerical
signal it can corroborate with its own visual assessment.

**Independent Test**: feed a known-blurry figure (synthetic) to
the orchestrator. Verify the `local_quality_estimate` records a
Laplacian-variance value below a documented blur threshold and
that the operator can grep the provenance for figures the local
probe flagged. Separately, verify the compressed image bytes
transmitted match the canonical PNG within a perceptual quality
budget AND that the canonical PNG on disk is NEVER overwritten
by the compression step.

**Acceptance Scenarios**:

1. **Given** a corpus of mixed-quality figures, **When** the
   orchestrator processes them, **Then** every
   `figure_interpretation` carries a `local_quality_estimate`
   dict with Laplacian variance, mean brightness, native max
   dimension, and compression ratio fields populated.
2. **Given** a single 3 MB PNG figure, **When** the orchestrator
   processes it, **Then** the compressed payload sent to the
   model is under 300 KB AND the canonical PNG file on disk is
   byte-identical before and after the run (read-only access).
3. **Given** any figure, **When** the model returns its response,
   **Then** the response includes a `model_quality_estimate`
   string from a fixed enum and the orchestrator records both
   the local and the model estimate in the enriched record.

---

### User Story 6 — References finally go fast (Priority: P2)

The references component runs the existing multi-stage resolution
strategy at production throughput by wiring it to the existing
async worker pool. No new reference-resolution logic; just
wire-up.

**Why this priority**: P2 because correctness is already
established; this story is about latency. Today the per-reference
runner would serialize through one HTTPS request at a time. The
existing async pool supports hundreds of concurrent splits and
dozens of concurrent OpenAlex title-searches with rate-limit-
aware back-off.

**Independent Test**: process a synthetic abstract carrying 30
references. Verify wall-clock for the references component on
that abstract is bounded by the async-pool's concurrency and
rate-limit budgets, not by the count-of-references × per-request
latency.

**Acceptance Scenarios**:

1. **Given** a corpus where 80% of abstracts have references,
   **When** the orchestrator runs the references component on
   the full corpus, **Then** wall-clock for the references stage
   is dominated by rate-limit budgets rather than by serial
   request latency.
2. **Given** the same run, **When** any individual reference
   fails to resolve, **Then** the failure is recorded with the
   typed reference-failure metric and the run continues —
   per-reference failures are tolerated up to the existing
   reference-failure threshold (default 1.0, configurable).

---

### Edge Cases

- An abstract has zero figures → the figures component is a
  no-op for that abstract and `figure_interpretation` is an
  empty list. Manuscript is still sent to the claims component;
  no figure context is added to the claims prompt.
- An abstract has figures but their local files were never
  downloaded (Stage 1 figure-download failure leaked into Stage
  2) → the figures component records a per-figure failure with a
  typed cause ("local asset missing"); the abstract is still
  enriched with whatever else resolves; if missing-asset rate
  exceeds the figures threshold, the run exits non-zero.
- Flex tier returns a malformed response (schema drift on the
  model side) → the response captures the offending payload in
  the cache file's failure-record AND raises the typed component
  error so the threshold logic counts it as a failure.
- The orchestrator's machine loses network mid-run → already-
  cached entries on disk survive; the per-component caches ARE
  the checkpoint; on next invocation the orchestrator picks up
  where it left off (inherited from Stage 2 SC-009).
- The operator deletes only one component's cache directory →
  that component re-runs end-to-end; the others reuse intact
  entries (inherited from Stage 2).
- The model returns a claim with an ECO code that isn't in the
  v1 vocabulary → the claim is dropped with a typed warning in
  provenance (Principle VI: do not silently accept off-vocabulary
  annotations). Operator can extend the vocabulary in a follow-on
  spec.
- The `verify_source_quote` tool reports the model's quoted
  source is not a substring of the manuscript AND no candidate
  correction substring-matches either → the claim is dropped
  with a typed warning; threshold counters track this case
  separately from "no claims extracted" so the operator can tell
  the two apart.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Stage 2.1 MUST replace the existing
  `NotImplementedError` stubs in the orchestrator's three
  production component runners with implementations that
  actually invoke the configured backend.
- **FR-002**: Each component runner MUST default to
  `gpt-5.4-mini` and MUST accept an operator-supplied per-
  component model override via the existing CLI flags
  (`--figure-model-id`, `--claims-model-id`,
  `--reference-strategy-id`). When the operator changes ONLY one
  component's model identifier, ONLY that component's per-
  component cache is invalidated (inherited from Stage 2 FR-005).
- **FR-003**: Both LLM-backed components (figures, claims) MUST
  default to OpenAI's flex processing tier. The operator MUST be
  able to disable flex per component via
  `--no-flex-figures` / `--no-flex-claims`. The provenance record
  MUST capture the tier setting per component.
- **FR-004**: Flex-tier timeouts MUST be handled gracefully:
  - explicit per-request timeout (configurable; defaults to a
    documented value);
  - on flex timeout, fall back to a standard-tier retry for the
    SAME logical request, up to a configurable retry budget;
  - on retry-budget exhaustion, raise the typed component error
    so the existing component-failure-threshold logic kicks in;
  - the provenance record MUST surface per-component counters for
    `flex_timeout_count`, `tier_fallback_count`, and
    `retry_exhaustion_count`.
- **FR-005**: The figures component MUST group figures BY
  ABSTRACT — one model call carries all of that abstract's
  figures plus the manuscript markdown (title + introduction +
  methods + results + conclusion) as context. The model MUST
  return one interpretation entry per figure in the request.
- **FR-006**: The figures component MUST compress each figure
  locally before transmission. Compression MUST:
  - read from the canonical asset path WITHOUT modifying it;
  - resize so the long side is at most a configurable maximum
    (default 1024 px) using a high-quality resampler;
  - encode as a transmission-efficient format (default JPEG with
    quality parameter 85) in memory only;
  - never write the compressed bytes back to disk.
- **FR-007**: The figures component MUST compute a local image-
  quality estimate before the model call. The estimate MUST
  include: a blur indicator (Laplacian variance over the
  grayscale image), mean brightness, native max dimension before
  resize, and the post-compression byte ratio. The estimate MUST
  be stored on every `figure_interpretation` record alongside the
  model's own `model_quality_estimate` enum.
- **FR-008**: The model's per-figure `model_quality_estimate`
  MUST be a string drawn from a fixed enum (e.g., "high",
  "medium", "low_resolution", "low_contrast", "diagram_only",
  "uninterpretable"). The orchestrator MUST reject any
  off-enum value as a schema-drift error (Principle VII /
  CA-007) and surface it via the typed component error.
- **FR-009**: The claims component MUST NOT depend on the
  `cllm` library. Stage 2.1 removes `cllm` from the project's
  optional dependency declarations and from any installation
  instructions in operator-facing docs.
- **FR-010**: The claims component MUST issue a single agentic
  API call per abstract (one network request from the
  orchestrator's perspective; the model may issue multiple
  internal tool calls). Inputs to the call: manuscript markdown +
  figure interpretations from this run + an embedded ECO
  vocabulary primer.
- **FR-011**: The claims component MUST expose three function
  tools to the model:
  - `verify_source_quote(claim_text, source_quote) ->
    {is_substring: bool, candidate_corrections: list[str]}` — the
    orchestrator-side handler performs an exact substring check
    against the manuscript text AND returns ranked candidate
    substring corrections when not found.
  - `lookup_eco_code(label_or_description) ->
    list[{eco_id, label, definition}]` — the orchestrator-side
    handler returns matches against the embedded ECO vocabulary;
    in v1 the vocabulary is the 9 top-level codes.
  - `dedupe_check(claim_a, claim_b) -> {is_duplicate: bool,
    reasoning: str}` — the orchestrator-side handler implements
    a lightweight similarity check the model can invoke during
    its own intermediate review pass.
- **FR-012**: The claims component's structured output MUST
  conform to a documented schema with the following per-claim
  fields: `claim_text` (string), `source_quote` (string),
  `source_quote_verified` (bool, populated via the verification
  tool), `claim_type` (enum: explicit | implicit),
  `evidence_eco_codes` (list of ECO identifiers, ≥1 required,
  each MUST be a member of the v1 vocabulary), and `confidence`
  (numeric self-rating). Claims whose `source_quote_verified` is
  false AND for which no candidate correction substring-matches
  MUST be dropped before reaching the SQLite write.
- **FR-013**: The ECO v1 controlled vocabulary MUST be the 9
  direct children of ECO:0000000 (experimental, similarity,
  combinatorial, manual assertion, inferential, automatic
  assertion, high throughput, documented statement,
  computational). The vocabulary file MUST ship inside the source
  tree (no network access required at run time) and MUST carry a
  versioned schema so future broader vocabularies (full ECO
  graph) can land without ambiguity. The claims component's cache
  key MUST embed the vocabulary version in addition to the model
  identifier (so a vocabulary bump invalidates claims caches
  loudly): `cache_key = sha256(manuscript_md || claims_model_id ||
  vocabulary_version)`.
- **FR-014**: The references component runner MUST wire to the
  existing async resolution pipeline (markdown normalization →
  LLM-assisted splitting → DOI/PMID/OpenAlex/Semantic Scholar
  resolution) at production throughput. The component MUST
  respect the existing per-pool concurrency caps (split,
  title-search) and rate-limit back-off. No new resolution logic
  in Stage 2.1.
- **FR-015**: Stage 2.1 MUST NOT modify Stage 1 outputs or the
  Stage 2 SQLite-storage contract. The enriched corpus shape
  (canonical SQLite + zlib(json) per row) and the provenance
  schema remain compatible with Stage 2; Stage 2.1 EXTENDS the
  provenance schema with the new tier counters (FR-004) and the
  ECO vocabulary version field (FR-013).
- **FR-016**: Operator-facing docs (README's Stage 2 section,
  CLAUDE.md, quickstart) MUST be updated in the same change to
  document `gpt-5.4-mini` as the new default, the flex flags, the
  agentic-claims design, and the ECO annotation surface. The
  legacy `cllm` install instruction MUST be removed.
- **FR-017**: Operator-supplied secrets (`OPENAI_API_KEY` and
  any future per-component override env var) MUST be named by
  variable rather than embedded; values MUST NEVER appear in
  provenance, logs, or stdout.
- **FR-018**: Concurrency across abstracts MUST be configurable
  per component (defaults to 30 in flight). The orchestrator
  MUST back off when OpenAI's response headers indicate the
  account is near its TPM or RPM budget; the back-off MUST be
  surfaced as a typed event in stderr with the component name
  and the limit family that triggered it.
- **FR-019**: Cost-related telemetry MUST be recorded in the
  provenance record per component: tokens consumed (prompt
  cached, prompt uncached, completion), wall-clock total, and
  per-call median + p95 latency. Operators MUST be able to
  reproduce the run's spend after the fact from the provenance
  alone (no per-call OpenAI dashboard scraping required).

### Key Entities

- **Production Figure-Component Runner**: replaces the
  `NotImplementedError` stub. Owns: in-memory local compression
  (FR-006), local quality probe (FR-007), per-abstract grouping
  + manuscript-context attachment (FR-005), flex-tier logic
  (FR-003 / FR-004), and the schema-validated
  `model_quality_estimate` (FR-008).
- **Production Claims-Component Runner**: replaces the
  `NotImplementedError` stub. Owns: agentic single-call request
  (FR-010), three orchestrator-side function tools (FR-011),
  structured output schema enforcement (FR-012), flex-tier
  handling (FR-003 / FR-004).
- **Production References-Component Runner**: replaces the
  `NotImplementedError` stub. Owns: wire-up to the existing
  async resolution pipeline (FR-014); no new resolution logic.
- **ECO Vocabulary v1**: an embedded, versioned data file
  carrying the 9 top-level Evidence and Conclusion Ontology
  codes (FR-013). Defines the controlled vocabulary the claims
  component's `lookup_eco_code` tool draws from.
- **Per-Component Flex Configuration**: the flex tier setting
  (on/off) AND timeout / retry budgets per component, captured
  in CLI flags and surfaced in the provenance record's component
  summaries (FR-003 / FR-004).
- **Tier-Fallback Counters**: provenance fields per component
  recording how often flex timed out, how often the standard-tier
  retry took over, and how often the retry budget was exhausted
  (FR-004 / FR-019).
- **Cost Telemetry**: per-component prompt/completion token
  counts and latency summaries in the provenance record
  (FR-019).

### Constitution Alignment *(mandatory)*

- **CA-001**: Every Python invocation introduced by this feature
  runs through `.venv/bin/python` or `uv` targeting it; no
  system Python.
- **CA-002**: Tests for each user story land before
  implementation. US1 → end-to-end run against a synthetic
  corpus with all three production runners; US2 → simulated
  flex-timeout + tier-fallback path; US3 → per-component model
  override + cache-invalidation matrix; US4 → source-quote
  verification + ECO annotation + dedupe loop; US5 → local
  compression byte-budget + canonical-PNG read-only check + blur
  threshold probe; US6 → references-component async-pool wire-up
  smoke test.
- **CA-003**: README's Stage 2 section, CLAUDE.md, and the
  Stage 2 quickstart MUST update in the same change to document
  the new defaults, the flex flags, the agentic-claims design,
  and the ECO annotation surface. The `cllm` install instruction
  MUST disappear.
- **CA-004**: API keys named only as env vars (`OPENAI_API_KEY`,
  optional `OPENALEX_API`). Values NEVER recorded in provenance;
  only names appear in `env_vars_consulted`.
- **CA-005**: All artifacts (enriched corpus, provenance,
  per-component caches, embedded ECO file) live under existing
  gitignored or source-tree paths. The ECO vocabulary file lives
  under `src/ohbm2026/data/` as source (gitignored data roots
  remain for derived artifacts).
- **CA-006**: All failure modes surface loudly with typed causes
  (existing Stage 2 hierarchy applies). New failure surfaces
  added by Stage 2.1: flex-timeout retry-exhaustion (escalates
  through existing component-failure-threshold logic),
  off-vocabulary ECO code (typed warning + drop), unverified
  source quote with no candidate correction (typed warning +
  drop), missing local figure asset (per-figure failure with
  typed cause). NO silent fallbacks.
- **CA-007**: Discovery surfaces in Stage 2.1: (a) LLM response
  shape validated at parse time against the structured-output
  schema (figures + claims); (b) `model_quality_estimate` enum
  validated against the documented value set;
  (c) `evidence_eco_codes` validated against the embedded
  vocabulary; (d) flex-tier availability discovered at runtime
  by inspecting the OpenAI API's response headers (the model
  family's tier support matrix is NOT hardcoded). Mismatches
  surface as typed errors.
- **CA-008**: The enriched corpus remains organizer-facing
  secondary data. Its provenance record (extended per
  FR-004 / FR-019) MUST remain free of absolute paths and
  user-home paths; the ECO vocabulary version + the tier
  configuration + the cost telemetry MUST all be machine-
  readable and reproducible.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fresh contributor can run Stage 2.1 end-to-end
  against the live accepted corpus by following only the
  updated README's Stage 2 section — no other documentation
  lookups required.
- **SC-002**: A full fresh run against the 3244-accepted-
  abstract corpus completes in under 75 minutes wall-clock on a
  typical developer laptop with `OPENAI_API_KEY` configured and
  flex tier on.
- **SC-003**: A full fresh run against the same corpus costs
  under USD 10 in OpenAI spend with the default
  `gpt-5.4-mini` + flex configuration — verifiable from the
  provenance record's cost telemetry without consulting the
  OpenAI dashboard.
- **SC-004**: A second Stage 2.1 run with no input or model
  changes produces a byte-identical enriched SQLite (modulo
  provenance run-id and timestamp) AND issues zero LLM calls
  for any of the three components (inherited from Stage 2
  SC-002, must remain true post-wiring).
- **SC-005**: Changing only one component's model id
  invalidates only that component's cache; the other two show
  100% cache hits on the next run (inherited from Stage 2
  SC-003, must remain true post-wiring).
- **SC-006**: 95% of `figure_interpretation` records have both
  a `local_quality_estimate` dict (Laplacian variance, mean
  brightness, native max dimension, compression ratio) AND a
  `model_quality_estimate` enum value populated on the first
  fresh run.
- **SC-007**: 95% of produced `claims` records have
  `source_quote_verified = true`. The remaining ≤5% are
  measured against the documented failure surface (no
  substring + no candidate correction → claim dropped, NOT
  retained with verified=false).
- **SC-008**: No claim is persisted to the enriched SQLite
  without at least one ECO evidence code drawn from the v1
  vocabulary; claims the model failed to annotate (or
  annotated with off-vocabulary codes) are dropped at parse
  time, the drop is recorded with a typed warning, and the
  per-component failure-threshold counter increments. The
  surface metric to verify: zero records in the enriched
  SQLite with `claims[].evidence_eco_codes == []` or any
  member outside the embedded vocabulary.
- **SC-009**: A simulated flex-tier timeout for one abstract's
  figure request triggers the documented tier-fallback path:
  one standard-tier retry, success, tier-fallback counter
  incremented in provenance, the abstract is still enriched.
- **SC-010**: A simulated persistent flex failure beyond the
  retry budget for a component triggers the component-failure-
  threshold logic: run exits non-zero with the typed component
  error, the previous enriched corpus on disk is unchanged,
  per-component cache entries written so far survive for the
  next run.
- **SC-011**: The orchestrator's `data/primary/assets/*.png`
  files have byte-identical contents before and after a fresh
  Stage 2.1 run (read-only access to canonical figure assets).
- **SC-012**: The full project test suite remains green after
  this feature lands (excluding the pre-existing unrelated
  `test_plot_poster_layout_floorplan` failure), and the
  `constitution-check.sh --full` lint stays at exit 0.

## Assumptions

These are informed defaults applied when the brief did not
specify. Any of them can be overridden in `/speckit-clarify` or
`/speckit-plan`.

- **Default model `gpt-5.4-mini`** for both figures and claims;
  available in the project's OpenAI account at flex tier; pricing
  in the ~$0.25/$2 per-1M-tokens range. If `gpt-5.4-mini` is not
  accessible at run time the operator overrides via the per-
  component model-id flag (the spec does NOT require a
  hardcoded fallback chain).
- **Flex tier default = on**. Operators concerned about latency
  predictability (e.g., a live demo run) toggle it off via
  `--no-flex-*`. The spec assumes flex tier is available at the
  account level when the operator has not toggled it off; if the
  API rejects flex (e.g., account tier doesn't support flex),
  the orchestrator falls back to standard tier with a typed
  warning rather than failing.
- **Per-request flex timeout default**: a documented value
  expressed in seconds (default chosen during planning, not
  baked into the spec). Configurable per component.
- **Retry budget default**: a small documented integer (e.g.,
  2 attempts). Configurable per component.
- **Concurrency default 30 in flight per component**. Operators
  with elevated OpenAI tiers can raise it; the back-off on
  rate-limit headers (FR-018) protects against
  over-concurrency.
- **Local image compression default JPEG q85 at 1024 px**
  long-side. WebP at q85 is ~35% smaller but encodes ~20× slower
  (in-session benchmark); JPEG is the better default for the
  encode-loop. Operators can override the cap and quality
  parameter in a follow-on round (out of scope for v1).
- **Laplacian-variance "blur threshold"** is recorded but is
  advisory — the orchestrator surfaces the number in provenance
  without using it to drop figures automatically. (Dropping
  blurry figures would prevent the model from contributing
  rich-text descriptions of legitimately-stylized diagrams.) A
  future spec can add an opt-in drop threshold.
- **ECO v1 vocabulary = the 9 top-level codes**. Subterms are
  rich but the top-9 cover the OHBM-style brain-imaging claim
  landscape adequately. v2 may drill in.
- **Cost telemetry comes from the OpenAI response headers**
  (token counts) and from local wall-clock measurement
  (latency). The orchestrator does NOT call any OpenAI billing
  API.
- **Withdrawn-corpus enrichment is OUT of scope** (inherited
  from Stage 2). Stage 2.1 enriches the accepted corpus only.
- **Historical-corpus migration (`abstracts_enriched.json`
  3333-record Mar-2026 corpus into the new SQLite)** is OUT
  of scope. A separate one-shot migration spec can land if
  the fresh-run cost / time ever pushes us toward it; the
  current cost estimate (~$5, <75 min wall-clock) suggests it
  won't be needed.
- **Legacy cache backfill is OUT of scope**. New component
  versions imply new cache keys; the first Stage 2.1 run is a
  fresh fill. The Stage 2 cache layout already supported this
  natively (`sha256(input || model_id)` keys).

## Future Work (explicitly OUT of scope for this spec)

- **OpenAI Batch API** as a third cost-saving lever (~50% off
  flex, 24h async). Could land as `--use-openai-batch` toggle in
  a later spec; requires submit-then-reconcile lifecycle that
  doesn't fit the synchronous-loop mental model the current
  orchestrator carries.
- **Full ECO vocabulary subterms** beyond the top-9.
- **Withdrawn-corpus enrichment.**
- **Historical-corpus migration** (`abstracts_enriched.json` →
  `abstracts_enriched.sqlite`).
- **Multi-provider failover** (Anthropic, Google Gemini) for
  components — the spec assumes OpenAI as the production
  backend in v1.
- **Per-record cost telemetry** (only per-component aggregates
  are mandated in v1; per-record telemetry inflates every
  enriched record).
- **Refactoring `enrichment.py` and `openalex.py`** into smaller
  modules — still a candidate follow-up, still not mandated by
  this spec.
