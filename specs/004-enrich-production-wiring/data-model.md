# Data Model — Stage 2.1 Extensions

Phase 1 of `/speckit-plan`. Stage 2.1 is a wire-up of production
component runners; the canonical artifact shapes (`abstracts_enriched.sqlite`,
the per-component caches, the provenance record) are inherited
from Stage 2. This doc documents only the EXTENSIONS that
Stage 2.1 introduces. Refer to `specs/003-enrich-abstracts/data-model.md`
for the unchanged base shapes.

## Path Layout (unchanged from Stage 2)

| Artifact | Path |
|---|---|
| Enriched corpus (SQLite + zlib) | `data/primary/abstracts_enriched.sqlite` |
| Enrich provenance record | `data/inputs/abstracts_enrich_provenance__<state-key>.json` |
| Figure-interpretation cache | `data/cache/figure_analysis/<cache-key>.json` |
| Claims cache | `data/cache/claim_analysis/<cache-key>.json` |
| Reference-resolution cache | `data/cache/reference_metadata/<cache-key>.json` |
| **ECO v1 vocabulary (committed source)** | `src/ohbm2026/data/eco_top_codes.json` |

## 1. ECO Vocabulary File (NEW)

Shipped at `src/ohbm2026/data/eco_top_codes.json`. Format:

```json
{
  "vocabulary_version": "eco.v1",
  "source": "https://www.ebi.ac.uk/ols4/ontologies/eco",
  "parent_term": "ECO:0000000",
  "fetched_at": "<ISO-8601 UTC>",
  "codes": [
    {"eco_id": "ECO:0000006", "label": "experimental evidence", "definition": "..."},
    {"eco_id": "ECO:0000041", "label": "similarity evidence", "definition": "..."},
    {"eco_id": "ECO:0000212", "label": "combinatorial evidence", "definition": "..."},
    {"eco_id": "ECO:0000352", "label": "evidence used in manual assertion", "definition": "..."},
    {"eco_id": "ECO:0000361", "label": "inferential evidence", "definition": "..."},
    {"eco_id": "ECO:0000501", "label": "evidence used in automatic assertion", "definition": "..."},
    {"eco_id": "ECO:0006055", "label": "high throughput evidence", "definition": "..."},
    {"eco_id": "ECO:0006151", "label": "documented statement evidence", "definition": "..."},
    {"eco_id": "ECO:0007672", "label": "computational evidence", "definition": "..."}
  ]
}
```

**Validation rules**:

- File MUST validate against `contracts/eco_top_codes.schema.json`.
- `codes` MUST be a list of exactly 9 entries for `vocabulary_version: "eco.v1"`.
- Every `eco_id` MUST match `^ECO:\d{7}$`.

## 2. Extensions to `FigureInterpretation` Record

Stage 2's `FigureInterpretation` schema already defines:
`figure_url`, `local_path`, `question_name`, `interpretation`,
`model_id`, `cache_key`.

Stage 2.1 ADDS the following fields:

| Field | Type | Description |
|---|---|---|
| `local_quality_estimate` | object | Local probe results computed before the model call. See sub-schema below. |
| `model_quality_estimate` | enum string | Model's own quality assessment. One of: `"high"`, `"medium"`, `"low_resolution"`, `"low_contrast"`, `"diagram_only"`, `"uninterpretable"`. |
| `keywords` | array<string> | Model-extracted keyword list (3-10 terms describing figure content). |
| `ocr_text` | string \| null | Model-extracted OCR text from figure annotations. `null` if no text is visible. |

### `local_quality_estimate` sub-schema

| Field | Type | Description |
|---|---|---|
| `laplacian_variance` | number | Variance of a 3×3 Laplacian filter on the grayscale image. Lower = blurrier. Advisory threshold around 100. |
| `mean_brightness` | number | Mean grayscale intensity, 0–255. |
| `native_max_dim` | integer | Max(width, height) of the original PNG before resize. |
| `compression_ratio` | number | `len(jpeg_bytes) / len(original_png_bytes)`. Range 0.0–1.0. |

## 3. Extensions to `Claim` Record

Stage 2's `Claim` schema already defines: `claim_text`,
`confidence`, `model_id`, `cache_key`.

Stage 2.1 EXTENDS the schema:

| Field | Type | Description |
|---|---|---|
| `source_quote` | string | Verbatim substring from the manuscript that supports the claim. Required. |
| `source_quote_verified` | boolean | `true` iff `source_quote` is an exact substring of the manuscript when checked by the `verify_source_quote` tool. Claims with `false` AND no candidate correction are dropped before the SQLite write — never persisted with `false`. |
| `claim_type` | enum string | `"explicit"` or `"implicit"`. |
| `evidence_eco_codes` | array<string> | ≥1 ECO ID from the v1 vocabulary. Each MUST be in the embedded `codes` list. |

`confidence` becomes required (was optional in Stage 2). Range
0.0–1.0.

## 4. Extensions to Enrich Provenance Record

Stage 2's provenance record's `components` array carries one
`ComponentSummary` per component. Stage 2.1 EXTENDS the
`ComponentSummary` schema:

| New Field | Type | Description |
|---|---|---|
| `flex_tier_enabled` | boolean | `true` iff the component ran on the flex tier by default for this run. |
| `flex_timeout_count` | integer | Number of logical requests that returned a flex-tier timeout. |
| `tier_fallback_count` | integer | Number of logical requests where a flex timeout was followed by a successful standard-tier retry. |
| `retry_exhaustion_count` | integer | Number of logical requests that exhausted both attempts (flex + standard). |
| `prompt_tokens_cached` | integer | Sum of cached prompt tokens across all calls for this component (per OpenAI `response.usage`). |
| `prompt_tokens_uncached` | integer | Sum of uncached prompt tokens. |
| `completion_tokens` | integer | Sum of completion tokens. |
| `wall_clock_seconds` | number | Total wall-clock time spent in this component (sum of per-call elapsed time, accounting for concurrency means this is NOT the elapsed wall-clock of the orchestrator). |
| `latency_p50_ms` | number | Median per-call latency in milliseconds. |
| `latency_p95_ms` | number | 95th-percentile per-call latency. |

The top-level provenance record ALSO gains:

| New Field | Type | Description |
|---|---|---|
| `eco_vocabulary_version` | string | The `vocabulary_version` field of the embedded ECO file at run time. Stage 2.1 v1 is `"eco.v1"`. |

## 5. Component Cache Entry Schema

Stage 2's cache-entry schema envelope (`cache_version`,
`component`, `cache_key`, `model_id`, `input_hash`, `computed_at`,
`payload`) is unchanged. The `payload` shape for figures + claims
is the NEW per-component output (with the added fields from §2
and §3 above); for references it's unchanged.

**Cache-key derivation (Stage 2.1)**:

- Figures: `cache_key = sha256(image_bytes || figure_model_id)`
  (inherited from Stage 2).
- Claims: `cache_key = sha256(manuscript_md || claims_model_id ||
  eco_vocabulary_version)` — **Stage 2.1 EXTENDS this from
  Stage 2's `sha256(input || model_id)` scheme by appending the
  ECO vocabulary version**. A vocabulary bump (e.g., `eco.v1` →
  `eco.v2` adding subterms) thus invalidates all claims caches
  loudly, with no silent migration. This matches FR-013's
  cache-invalidation guarantee.
- References: `cache_key = sha256(raw_reference || strategy_id)`
  (inherited from Stage 2).

The `cache_version` constant in `enrich_storage.py` stays at
`"enrich.cache.v1"`. The new payload shapes are additive — older
cache entries (if any) would parse cleanly modulo missing-field
behavior; in practice no Stage 2 cache entries exist on disk
because Stage 2's production runners were stubs that never wrote
real entries.

## State Transitions (unchanged)

Inherited from Stage 2. Per-component caches remain the
checkpoint. The agentic claims call is an atomic logical request
from the cache layer's perspective — either the whole response
parses and one cache entry gets written, or the call raises and
no entry exists.

## Validation Rules Summary

- **ECO file**: 9 entries, every `eco_id` matches the documented pattern.
- **FigureInterpretation**: `local_quality_estimate` always present
  on records produced by Stage 2.1; `model_quality_estimate`
  always one of the documented enum values; off-enum values raise
  `EnrichmentError`.
- **Claim**: `evidence_eco_codes` is a non-empty list; every code
  is a member of the embedded vocabulary; off-vocabulary codes
  trigger drop-with-typed-warning. `source_quote_verified=false`
  records are dropped before the SQLite write.
- **Provenance**: `eco_vocabulary_version` matches the embedded
  file at run time; every `ComponentSummary` has the new tier and
  cost-telemetry fields populated (even with zeros when flex was
  disabled or no requests were made).
- **Claims cache key**: MUST include the ECO vocabulary version
  alongside the manuscript content hash and model id; a
  vocabulary version mismatch on read raises a typed
  `CacheVersionError` (the existing Stage 2 surface), causing the
  claim to be re-extracted under the new vocabulary.
