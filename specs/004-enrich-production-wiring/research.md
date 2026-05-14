# Research: Stage 2.1 Design Decisions

Phase 0 of `/speckit-plan`. Spec measurements + design decisions
that fix the open choices for production wiring. Every decision
includes Rationale + Alternatives considered. Concrete defaults
(timeouts, retry budgets, concurrency caps) land here so the spec
stays technology-agnostic.

## 1. Image compression — JPEG q85 @ 1024 px

**Decision**: in-memory JPEG at quality 85 with the long side
capped at 1024 px. Pillow `Image.save(buf, format='JPEG',
quality=85, optimize=True)` on a Lanczos-resampled `Image`.

**Rationale** (anchored in the in-session benchmark, n=30 random
figures from the live `data/primary/assets/`):

| format | median bytes | mean encode time | bytes ratio vs PNG |
|---|---|---|---|
| original PNG | 720 KB | — | 100% |
| **JPEG q85 @ 1024 px ⭐** | **140 KB** | **4.2 ms** | **19.4%** |
| WebP q85 @ 1024 px | 90 KB | 84.5 ms | 14.0% |

The JPEG encoder is 20× faster than WebP at q85. WebP gives ~35%
smaller files but at scale the encoder time matters: 4694 figures
× 80 ms = 6 min of encoder-bound CPU vs ~20 s for JPEG. OpenAI
accepts both formats; the byte savings of WebP do not justify the
encode-loop cost when network egress is not the bottleneck.

OpenAI's vision-input pricing is based on tile count, NOT input
bytes. A 1024-px long-side image renders to a fixed-tile budget
(typically ~85 base tokens + ~170 per 512×512 tile = ~1000 input
tokens). Compressing below 1024 px wouldn't reduce token cost;
compressing above 1024 px wouldn't materially improve model
visual acuity on figure-style content.

**Alternatives considered**:

- **WebP q85**: rejected on encoder-time at corpus scale.
- **JPEG q70 @ 768 px**: smaller (~80 KB) but quality drops visibly
  on annotated brain-imaging figures. Reject.
- **PNG passthrough**: rejected on transmission size (~5 GB egress
  per run; ~30× more than JPEG).
- **Format auto-pick**: rejected as unnecessary complexity.

## 2. Local image-quality probe

**Decision**: every figure gets a four-field probe dict on its
`figure_interpretation` record, computed locally BEFORE the model
call:

- `laplacian_variance`: variance of a 3×3 Laplacian filter on the
  grayscale image. Lower = blurrier. Empirical cutoff for "likely
  blurry" is around 100 (advisory; orchestrator does NOT
  auto-drop).
- `mean_brightness`: mean grayscale intensity 0-255. Near-0 or
  near-255 values flag scans that are too dark or too washed out
  to interpret reliably.
- `native_max_dim`: max(width, height) of the original PNG before
  resize. Useful for auditing why a particular figure was
  compressed differently from others.
- `compression_ratio`: `len(jpeg_bytes) / len(original_png_bytes)`.
  Suspiciously high (>0.5) flags figures that didn't compress well
  (often line-art / diagram content where JPEG performs poorly).

**Rationale**: cheap to compute (~5 ms total per figure with
Pillow); gives the operator a numerical signal independent of the
model's `model_quality_estimate`; the two estimates can be
cross-referenced after the fact to flag systematic model
optimism on blurry inputs.

**Alternatives considered**:

- **BRISQUE / blind image-quality assessment**: rejected — adds a
  PyTorch model dependency for a few-percent quality signal lift.
  The Laplacian variance is the standard quick blur proxy and
  matches the operator's intuition.
- **No local probe; trust the model**: rejected. Principle VII
  applies: external state (figure quality) should be discovered
  locally where possible rather than relying on an opaque model
  judgment.
- **More than four fields**: deferred. Color histogram, edge density,
  text-region detection could land in a v2 probe.

## 3. Flex-tier retry budget and timeout

**Decision**:

- Per-request timeout: **120 seconds** for figures, **180 seconds**
  for claims (claims runs an agentic loop with tool calls; needs
  more headroom). Exposed as module-level constants
  `flex_tier.DEFAULT_FIGURES_TIMEOUT_SECONDS = 120` and
  `flex_tier.DEFAULT_CLAIMS_TIMEOUT_SECONDS = 180` so operators
  can inspect them programmatically and CLI flags can reference
  them.
- Retry budget per logical request: **2 attempts** — one flex
  attempt + one standard-tier retry. After exhaustion, raise the
  typed component error and let the existing
  `ComponentFailureThresholdError` logic decide whether the run
  aborts.
- Tier-counter bookkeeping: `flex_timeout_count` (per-component),
  `tier_fallback_count` (per-component; successful standard-tier
  retries), `retry_exhaustion_count` (per-component; logical
  requests that exhausted both attempts).

**Rationale**: flex's 50% cost discount comes with non-deterministic
latency — the failure mode is timeout, not error. A single
standard-tier retry recovers the call at the standard price (still
better than always paying standard); failures past the retry are
genuine — either the model is misbehaving or the abstract content
is malformed — and should escalate. Two attempts is the smallest
number that gives flex a fair shot.

The 120-second / 180-second timeouts are chosen above the
observed median latency of standard-tier `gpt-5.4-mini` calls
(~10–30 s for figures, ~20–60 s for the agentic claims call) with
~3× headroom for the flex-tier P99. Configurable; defaults are
documented.

**Alternatives considered**:

- **3+ retries**: rejected on cost. If 2 attempts fail, the issue
  is upstream — more retries hide root cause and inflate latency.
- **Exponential backoff between flex and standard**: rejected.
  Flex failure isn't rate-limited; it's a different request type.
  Immediate fallback is correct.
- **One global timeout**: rejected. Figures vs claims have
  legitimately different latency profiles; one timeout penalizes
  the longer-running component.

## 4. Concurrency cap and TPM-aware back-off

**Decision**:

- Concurrency: **30 in-flight requests per component** by default;
  configurable via `--concurrency-figures` / `--concurrency-claims`.
- Back-off: read OpenAI's `x-ratelimit-remaining-tokens` and
  `x-ratelimit-remaining-requests` headers; when either drops
  below 10% of the limit, pause new submissions for the
  `x-ratelimit-reset-*` window. Log a typed back-off event to
  stderr (component name + limit family + reset window).

**Rationale**: typical Tier-4 OpenAI accounts get ~5M TPM for
`gpt-5.4-mini`. At ~5.5k tokens per figures call, 30 concurrent
in-flight requests with median 15s latency = ~22k tokens/s = 1.3M
TPM — comfortably under the cap. Same math for claims (~7k tokens
× 30 concurrency / 25 s median = ~500k TPM). The 10%-remaining
threshold gives the orchestrator room to pause before the API
starts 429-ing.

**Alternatives considered**:

- **Higher concurrency (50, 100)**: rejected for default; operators
  on elevated tiers can raise it. Default should not push the
  median operator's rate-limit budget.
- **Token-bucket on the client side**: rejected as duplicate of the
  API's own rate-limiting. Read-the-headers + pause is simpler and
  authoritative.
- **No back-off, rely on retries on 429**: rejected. 429 retries
  amplify the load problem; preemptive pausing is cheaper.

## 5. Manuscript-context attachment to figure prompts

**Decision**: figures component sends an instruction message + a
"context" user message containing the abstract's manuscript text
(title + introduction + methods + results + conclusion, in that
order) + an "images" user message attaching the compressed figures
in order. The model is told that all N images are figures from
the SAME abstract and to interpret each in the context of that
abstract.

**Rationale**: the prior session's question — "what does 'see
siblings' mean?" — surfaced the cross-contamination risk of
in-request batching. The mitigation: attach the parent manuscript
text as explicit context so any cross-figure inference is
grounded in the abstract's actual content rather than the model
free-associating across unrelated figures. Empirical assumption:
OHBM abstracts that have two figures usually have one methods
figure and one results figure that genuinely refer to the same
study, so cross-context is signal, not noise.

The instruction message asks for one interpretation per figure in
the response, with the model emitting a JSON array of length N.

**Alternatives considered**:

- **One request per figure with abstract context**: rejected on
  call-count economics. 4694 separate calls vs 2808 grouped calls
  is ~67% more network round-trips for the same model time.
- **No manuscript context; figures interpreted blind**: rejected.
  Without context, figures from a methods section often look like
  generic plots; the model hallucinates more.
- **Manuscript context but ALSO one-call-per-figure**: rejected as
  worst-of-both — high call count AND no sibling-context benefit.

## 6. Structured output schemas

**Decision**: both LLM-backed components use the Responses API's
`responses.parse(text_format=PydanticModel)` surface. Pydantic
models defined in the per-component modules:

```python
# stage2_figures.py
class FigureInterpretationItem(BaseModel):
    figure_index: int  # 1-based, matches request order
    interpretation: str
    keywords: list[str]
    ocr_text: str | None
    model_quality_estimate: Literal[
        "high", "medium", "low_resolution",
        "low_contrast", "diagram_only", "uninterpretable",
    ]

class FigureInterpretationResponse(BaseModel):
    figures: list[FigureInterpretationItem]

# stage2_claims.py
class Claim(BaseModel):
    claim_text: str
    source_quote: str
    source_quote_verified: bool  # set true by the model after the verify tool returns is_substring=true
    claim_type: Literal["explicit", "implicit"]
    evidence_eco_codes: list[str]  # each MUST be one of the 9 v1 ECO IDs
    confidence: float  # 0..1

class ClaimsResponse(BaseModel):
    claims: list[Claim]
```

**Rationale**: the Responses API's strict structured-output mode
enforces the schema server-side; malformed output never reaches
the orchestrator. Pydantic gives field-level validation on the
client side too (the orchestrator double-checks the ECO codes are
in the v1 vocabulary, since the server-side enforcement is by
JSON shape, not by domain constraints). Both layers fail loudly
on schema drift — the model can't silently downgrade.

**Alternatives considered**:

- **Free-form JSON + post-hoc validation**: rejected. Server-side
  schema enforcement is strictly stronger.
- **Function-call signature as the output**: rejected. The
  Responses API's `text_format=...` is the right primitive for
  "final response"; function tools are for intermediate
  steps.

## 7. Function tool semantics

**Decision**: the three orchestrator-side function tools for the
claims component are pure, fast, side-effect-free. The model
invokes them inside its agentic loop; the SDK executes them
locally; the result is fed back into the model's context. No
network calls inside any tool handler.

**Registration mechanism**: tools are registered via
`openai.pydantic_function_tool(handler_callable, name=..., description=...)`
which derives each tool's JSON schema from the handler's
Pydantic input/output models. This means each handler's argument
schema lives in one place (the Pydantic model on the handler
itself) — no hand-written JSON schemas elsewhere.

- `verify_source_quote(claim_text, source_quote)`:
  exact substring check (`source_quote in manuscript_text`); if
  not, ranked candidate corrections via `difflib.get_close_matches`
  against the manuscript's sentence list. Returns
  `{is_substring: bool, candidate_corrections: list[str]}`.
- `lookup_eco_code(label_or_description)`:
  case-insensitive label match against the 9-entry vocabulary
  + substring match on the term definitions. Returns
  `list[{eco_id, label, definition}]`.
- `dedupe_check(claim_a, claim_b)`:
  cheap similarity check: normalized token-set overlap (Jaccard)
  + first-N-words exact match. Returns
  `{is_duplicate: bool, reasoning: str}`. The model uses this as
  a coordination signal; the orchestrator does NOT enforce dedupe
  unilaterally.

**Rationale**: the function tools' job is to give the model
ground-truth signals (does this substring exist? what's the ECO
label?) and let it self-correct. They're NOT enforcement points
that drop claims; the enforcement happens later in the
structured-output validation. Keeping the tools side-effect-free
makes the agentic loop reproducible: re-invoking the same
verify_source_quote call with the same arguments returns the
same result.

**Alternatives considered**:

- **Tools that drop claims themselves**: rejected as confusing —
  enforcement should be a single explicit step (post-response
  Pydantic validation).
- **Semantic-similarity dedupe with an embedding model**: rejected
  on cost. Jaccard is good enough for the dedupe-of-similar-
  wording case the model encounters mid-loop.
- **`lookup_eco_code` with full ECO graph traversal**: rejected;
  v1 vocabulary is 9 entries. Subterms are future work.

## 8. ECO v1 vocabulary file shape

**Decision**: the file at `src/ohbm2026/data/eco_top_codes.json` is
a versioned JSON object:

```json
{
  "vocabulary_version": "eco.v1",
  "source": "https://www.ebi.ac.uk/ols4/ontologies/eco",
  "parent_term": "ECO:0000000",
  "codes": [
    {
      "eco_id": "ECO:0000006",
      "label": "experimental evidence",
      "definition": "Evidence type from experimental data..."
    },
    ... 8 more entries
  ]
}
```

The vocabulary_version field is recorded in every Stage 2.1
provenance record's `eco_vocabulary_version` field so a future
run can detect that the vocabulary changed (and the cache should
be invalidated).

**Rationale**: machine-readable, versioned, committed to source;
no network access at run time; future expansion path obvious
(`eco.v2` adds subterms; v1 stays cached for reproducibility).

**Alternatives considered**:

- **Embed the vocabulary as a Python module-level dict**: rejected
  for diff-ability — JSON shows clean diffs on vocabulary updates.
- **Fetch from EBI at run time**: rejected on offline-ability and
  reproducibility (the EBI service can go down, the vocabulary can
  silently shift between runs).
- **YAML format**: rejected as inconsistent with the project's
  existing JSON-for-data convention.

## 9. Cost telemetry capture

**Decision**: per-component provenance fields:

```json
{
  "component": "figures",
  ...
  "prompt_tokens_cached": <int>,
  "prompt_tokens_uncached": <int>,
  "completion_tokens": <int>,
  "wall_clock_seconds": <float>,
  "latency_p50_ms": <float>,
  "latency_p95_ms": <float>,
  "flex_timeout_count": <int>,
  "tier_fallback_count": <int>,
  "retry_exhaustion_count": <int>
}
```

Token counts come from the OpenAI API response (`response.usage`);
latency is local wall-clock measured around each `responses.create`
call.

**Rationale**: operators can reproduce the dollar cost of a run
from provenance alone:

```text
spend ≈ (prompt_tokens_cached × $0.025 / 1M)
      + (prompt_tokens_uncached × $0.25 / 1M)
      + (completion_tokens × $2 / 1M)
      × (flex_discount_factor if flex was on)
```

The orchestrator does NOT call the OpenAI billing API. No
dashboard scraping required after the fact.

**Alternatives considered**:

- **Per-call telemetry persisted alongside each cache entry**:
  rejected on size — per-component aggregates are sufficient;
  per-record inflation hurts the SQLite blob and the cache files.
- **Skip cached / uncached split**: rejected; the cached prefix is
  the dominant cost-saving lever for the claims component, and
  the split matters for spend forecasting.

## 10. cllm removal scope

**Decision**: drop `cllm` entirely.

- Remove the cllm install instruction from README and CLAUDE.md.
- Remove any cllm-referencing imports in `enrichment.py`
  (the cllm-specific paths `extract_claims_with_cllm`,
  `extract_claims_from_cllm_module`, the claim-cache loader that
  uses cllm's payload shape). These are wrapped functions that
  the orchestrator never calls in Stage 2.1; their tests can
  stay if they don't import cllm at module-load time.
- Remove any `--llm-provider` flag references in operator-facing
  docs (cllm's CLI surface).

**Rationale**: keeping cllm as a "fallback" path would be a
silent-fallback pattern (Principle VI prohibits). Two routes to
do the same thing is a foot-gun. Operators who want zero-shot
extraction can pin an older model on the Responses API path.

**Alternatives considered**:

- **Keep cllm as opt-in via flag**: rejected. The agentic Responses
  API path is strictly better (verified quotes, ECO codes, dedupe).
  Operators have no reason to opt into the worse path.
- **Soft-deprecate with warnings**: rejected as inconsistent with
  Stage 1's `ingest` and Stage 2's four-subcommand-removal
  precedents.

## 11. Reference component wire-up

**Decision**: `_call_reference_strategy` becomes a thin adapter
that calls a function in `stage2_references.py` which:

1. Reads the raw reference markdown block from the abstract.
2. Invokes the existing `openalex.collect_reference_metadata`
   async entry point with the abstract's reference text and the
   configured `strategy_id` (which encodes the splitting model +
   strategy version).
3. Returns one `ReferenceResolution` record per resolved
   reference, matching the existing Stage 2 `ReferenceResolution`
   schema (raw_reference, doi, pmid, openalex_id, title, authors,
   year, resolution_status, resolution_source, strategy_id,
   cache_key).

The async pool's existing concurrency caps (`split_concurrency`
500, `title_concurrency` 50) and rate-limit back-off remain in
place. Stage 2.1 does NOT introduce new resolution logic, new
backends, or new concurrency tuning.

**Rationale**: this is wire-up, not redesign. The references
component is already production-grade; the only thing Stage 2.1
adds is exposing it through the orchestrator's
`_call_reference_strategy` seam.

**Alternatives considered**:

- **Pull reference resolution into the per-component agentic
  loop**: rejected as scope creep; the existing pipeline works
  and is well-tested.
- **Switch to a different OpenAlex client library**: rejected;
  the current async-pool implementation is bespoke and
  appropriately tuned for OpenAlex's rate limits.

## 12. Test fixture for agentic claims call

**Decision**: tests patch `client.responses.parse` at the
`stage2_claims` module's name-import seam:

```python
with mock.patch.object(stage2_claims, "_responses_client") as fake_client:
    fake_client.responses.parse.side_effect = lambda *a, **kw: _fake_parsed_response(
        claims_for_abstract=fixture_claims,
        tool_calls=fixture_tool_call_history,
    )
```

The `_fake_parsed_response` helper builds an SDK-shape object that
exposes:

- `.output_parsed` — the parsed Pydantic `ClaimsResponse`
- `.usage` — `prompt_tokens_cached`, `prompt_tokens_uncached`,
  `completion_tokens` fields
- `.tool_call_log` — synthetic history of which tools the
  "model" pretended to invoke (for test assertions about the
  agentic loop)

The orchestrator's three function tools (`verify_source_quote`
etc.) are exercised in their own focused tests (pure-function
inputs, expected outputs); the integration tests in
`test_stage2_claims.py` simulate the model invoking them by
having the fake response include tool-call-result entries.

**Rationale**: the function-tool handlers are pure functions on
the orchestrator side; testing them directly is simpler and faster
than round-tripping through a mocked agentic loop. The integration
tests verify that the orchestrator correctly assembles the prompt,
forwards the response through Pydantic validation, drops claims
that fail the post-response checks, and records the tier
counters.

**Alternatives considered**:

- **Use the OpenAI Python SDK's record-and-replay mode**: rejected
  for the v1 tests because it ties the test suite to a real
  network roundtrip captured at one point in time; brittle.
- **End-to-end test against a real OpenAI sandbox**: rejected for
  the v1 tests; live API tests can be added as a separate
  opt-in test family later (similar to the existing
  `test_openai_api_smoke.py`).
