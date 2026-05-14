# Phase 1 Data Model — Stage 3 Embeddings Matrix

This document specifies the in-memory and on-disk shapes of every entity Stage 3 owns. JSON Schemas for the consumer-facing shapes live alongside in `contracts/`.

## 1. Component (text)

Pure recipe: enriched-record → string. Defined in `src/ohbm2026/embed_components.py`.

```python
ComponentName = Literal[
    "title", "introduction", "methods", "results", "conclusion", "claims",
    # partial-coverage components (only when --allow-partial):
    "inference_claims",
]

ComponentText = str  # may be empty; emptiness means the abstract is absent from this component's bundle
```

**Default components in scope for v1 (FR-006)**: `title`, `introduction`, `methods`, `results`, `conclusion`, `claims`. Partial-coverage only: `inference_claims`.

**Assembly rules** (FR-006, Research §4):
- `title`: `record["title"]` after whitespace normalization.
- `introduction` / `methods` / `results` / `conclusion`: pull from `record["responses"]` where `question_name.strip().lower() == <component>` (existing pattern in `enrichment.build_sections_markdown`). Convert HTML→markdown.
- `claims`: `"\n\n".join(c["claim"] for c in record["claims"])` (post-Stage-2.1 verbatim-cllm `claim` field).
- `inference_claims`: same as `claims`, but filtered to `c["claim_type"] == "IMPLICIT"`.

**Identity**: `(abstract_id, component_name)` is unique per corpus_state_key.

**Component-assembly hash**: `sha256(normalized_component_text)` — used as the first half of the cache key.

## 2. Cache entry (per abstract per model per component)

On-disk: `data/cache/embeddings/<model_key>/<cache_key>.json`. Schema: `contracts/cache-entry.schema.json`.

```jsonc
{
  "cache_version": "embed.matrix.v1",
  "abstract_id": 1234567,
  "component": "methods",
  "model_id": "voyage-large-2-instruct",
  "model_version": "voyage-large-2-instruct@<sdk-reported-version-or-date>",
  "input_hash": "sha256(component_text)",
  "vector": [0.0123, -0.0456, ...],  // float32, length = model dim
  "dim": 1024,
  "truncated": false,
  "truncation_strategy": "truncate_end",  // mirror of bundle metadata
  "tokens_used": 1421,                    // when provider reports; null otherwise
  "embedded_at": "2026-05-14T12:34:56Z"
}
```

**Cache key**: `sha256(component_text || "||" || model_id || "||" || model_version)`. This matches Stage 2.1's per-component cache-key pattern (input bytes + identifier triple).

**Cache lookup contract**: an exact hit returns the persisted vector; a miss means the cache must compute. The cache is the source of truth for any one `(abstract, model, component)` combination — the bundle writer reads from the cache, never from a recomputed in-memory vector that wasn't first persisted to the cache.

**Eviction**: none. The cache is grow-only. A model-id or model-version change naturally invalidates by missing the key.

## 3. Embedding bundle

On-disk: `data/outputs/experiments/embeddings/<model_key>_<component>/`. Schema: `contracts/bundle.schema.json`.

### Files

| File | Type | Purpose |
|---|---|---|
| `vectors.npy` | `numpy.ndarray[float32, shape=(n_present, dim)]` | Dense matrix; row order matches `ids.npy` |
| `ids.npy` | `numpy.ndarray[int64, shape=(n_present,)]` | Abstract IDs indexing the rows of `vectors.npy` |
| `metadata.json` | JSON object | Bundle's human + machine-readable summary (count, dim, model_id, …) — see schema |
| `provenance.json` | JSON object | Audit record for this bundle (state_key, command, code revision) — see schema |

### `metadata.json` shape

```jsonc
{
  "schema_version": "stage3.bundle.v1",
  "bundle_name": "voyage_methods",
  "model_key": "voyage",
  "model_id": "voyage-large-2-instruct",
  "model_version": "voyage-large-2-instruct@2024-12-01-sdk",
  "component": "methods",
  "corpus_state_key": "f0c51e80dc0e",
  "corpus_source_path": "data/primary/abstracts_enriched.sqlite",
  "count": 3244,
  "present_count": 3242,
  "missing_count": 2,
  "missing_ids": [1248851, 9999999],
  "dim": 1024,
  "dtype": "float32",
  "long_input_strategy": "truncate_end",
  "long_input_params": null,
  "truncated_count": 12,
  "truncated_ids": [1245567, 1244320, ...],
  "failure_count": 0,
  "failure_ids": [],
  "concurrency": {
    "policy": "dynamic",
    "start": 8,
    "min_observed": 4,
    "max_observed": 16,
    "rate_limit_429_count": 3
  },
  "batch_size": 64,
  "request_count": 51,
  "wall_clock_seconds": 142.7,
  "embedded_at": "2026-05-14T13:00:00Z",
  "ids": [1196698, 1196735, ...]
}
```

`ids` is mandatory (for legacy consumer compatibility) and MUST equal `ids.npy` element-wise. The writer enforces this on each write.

### Naming

`<model_key>_<component>`. The `_partial` suffix is appended only when the bundle is opt-in partial (`--allow-partial`).

Examples (the 30 default bundles):
```
voyage_title, voyage_introduction, voyage_methods, voyage_results, voyage_conclusion, voyage_claims
minilm_title, minilm_introduction, minilm_methods, minilm_results, minilm_conclusion, minilm_claims
openai_title, openai_introduction, openai_methods, openai_results, openai_conclusion, openai_claims
pubmedbert_title, pubmedbert_introduction, pubmedbert_methods, pubmedbert_results, pubmedbert_conclusion, pubmedbert_claims
neuroscape_title, neuroscape_introduction, neuroscape_methods, neuroscape_results, neuroscape_conclusion, neuroscape_claims
```

(`neuroscape_*` bundles are produced as a derivation of the corresponding `voyage_*` bundle, never re-embedded from text.)

## 4. Run-level provenance record

On-disk: `data/inputs/embeddings_matrix_provenance__<state-key>.json`. Schema: `contracts/provenance.schema.json`.

```jsonc
{
  "schema_version": "stage3.provenance.v1",
  "state_key": "abcdef012345",
  "corpus_state_key": "f0c51e80dc0e",
  "corpus_source_path": "data/primary/abstracts_enriched.sqlite",
  "corpus_source_hash": "sha256(...)",
  "command_line": "ohbmcli embed-matrix --models voyage,minilm,openai,pubmedbert --components title,introduction,methods,results,conclusion,claims",
  "code_revision": "<git rev-parse HEAD>",
  "seed": null,
  "started_at": "2026-05-14T13:00:00Z",
  "completed_at": "2026-05-14T14:35:12Z",
  "wall_clock_seconds": 5712.0,
  "cache_version": "embed.matrix.v1",
  "cache_root": "data/cache/embeddings",
  "failure_threshold": 0.01,
  "batch_size": 64,
  "concurrency_policy": "dynamic_start_8_min_1_max_24",
  "env_vars_consulted": ["OPENAI_API_KEY", "VOYAGE_API_KEY", "HF_TOKEN"],
  "bundles": [
    {
      "bundle_path": "data/outputs/experiments/embeddings/voyage_methods",
      "model_key": "voyage",
      "model_id": "voyage-large-2-instruct",
      "model_version": "...",
      "component": "methods",
      "present_count": 3244,
      "failure_count": 0,
      "truncated_count": 0,
      "cache_hit_count": 3244,
      "cache_miss_count": 0,
      "wall_clock_seconds": 0.3
    },
    ...
  ]
}
```

`_assert_paths_safe` is applied to every `bundle_path` and `corpus_source_path` before write (no absolute, no `~`).

## 5. Composition recipe (downstream contract)

Stage 3 itself does not materialize composed bundles, but it defines and tests the composition contract that downstream code uses.

```python
def compose_recipe(
    components: list[ComponentName],
    bundles_root: Path = EMBEDDINGS_ROOT,
    model_key: str,
) -> dict:
    """Load the named per-component bundles and return a dict with:

    - ids: int64 [n_union]  — every abstract present in AT LEAST ONE input bundle
    - matrix: float32 [n_union × dim]  — for each id, the mean over the COMPONENTS PRESENT for that id
    - present_count_per_id: int8 [n_union]  — how many of the requested components each id had

    Missing rows for an abstract on a given component do not contribute to that
    abstract's mean. An abstract present in zero of the requested components is
    excluded from the output.
    """
```

The function is implemented in `src/ohbm2026/neuroscape.py` (existing module — adds a `compose_recipe` helper) and consumed by the cluster / UMAP / UI export pipelines. SC-004 validates the composition against a baseline direct-concatenation embedding on a 50-abstract sample (cosine sim ≥ 0.90).

## 6. Exceptions

Defined in `src/ohbm2026/exceptions.py` (extending the existing tree):

```
OhbmStageError
├── Stage3Error
│   ├── EmbeddingError
│   │   ├── EmbeddingProviderError       # transient HTTP / SDK errors past retry budget
│   │   ├── EmbeddingBudgetError         # provider budget exhausted (specific case for resume-friendly exit)
│   │   ├── EmbeddingContractError       # provider returned wrong cardinality / mismatched dim
│   │   └── ComponentAssemblyError       # the enriched corpus didn't yield text for a requested component for every abstract that should have it
│   └── EmbeddingThresholdError          # per-bundle failure threshold exceeded (exit 5)
└── ProvenanceError                      # shared
```

## 7. State transitions per (model, component)

```
[no cache, no bundle]
        │ run start
        ▼
[component-assembly]  (always runs; pure)
        │
        ▼
[cache lookup]  → hit → record in bundle plan, skip provider
        │
        ▼ miss
[batch into next-batch]
        │
        ▼ batch full or end-of-pass
[provider call]
        │
        ▼ response received
[per-input cache write]  (atomic temp+rename per file)
        │
        ▼
[bundle assembly]  (after all abstracts processed)
        │
        ▼
[atomic bundle write]  (temp dir → rename)
        │
        ▼
[run-level provenance update]  (append this bundle's outcome)
        │
        ▼
[run summary stdout]
```

Failure transitions: any provider 4xx (non-429) past 3 retries → `EmbeddingProviderError` per-batch → counted; if running failure rate > threshold → `EmbeddingThresholdError` aborts the bundle. Cache entries written before abort are preserved.
