# Phase 0 Research — Stage 3 Embeddings Matrix

## 1. Provider / model identifiers and SDK choice

### Decision

| Slot | Identifier | Source | Embedding dim |
|---|---|---|---|
| Voyage | `voyage-large-2-instruct` | Existing default in `neuroscape.py:DEFAULT_VOYAGE_MODEL`; matches NeuroScape Stage 1 training corpus | 1024 |
| MiniLM | `sentence-transformers/all-MiniLM-L6-v2` | Matches the static UI search model (FR-005); `neuroscape.py:DEFAULT_MINILM_MODEL` | 384 |
| OpenAI | `text-embedding-3-small` | Spec FR-005; ~10× cheaper than `-3-large` and adequate for cluster-grade analyses | 1536 |
| PubMedBERT | `neuml/pubmedbert-base-embeddings` | Existing `pubmedbert_stage1` bundle metadata captured under `data/outputs/experiments/embeddings/pubmedbert_stage1/metadata.json:model_name`. This is the Sentence-Transformers-compatible mirror of `microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract` with a mean-pooling head pre-applied | 768 |
| NeuroScape published | The published Stage 2 transformer loaded by the existing `neuroscape.apply_published_stage2` flow; checkpoint identifier read from its manifest at load time | matches Voyage upstream (1024) |

**Rationale**: All four primary models match identifiers already proven against the prior 3333-record corpus. Switching the Voyage variant would break NeuroScape Stage 2 application (Principle VII — discover, don't hardcode — applies in the other direction here: the NeuroScape model is *trained on* `voyage-large-2-instruct` outputs, so the upstream model id is constrained by the downstream artifact, not the other way around). OpenAI `-small` over `-large`: 6× cost difference, embedding quality difference is modest for cluster-grade analyses; user has explicit override path via CLI flag.

**Alternatives considered**:
- Voyage `voyage-3-large` — newer, larger context, higher quality, but the NeuroScape Stage 2 checkpoint expects `voyage-large-2-instruct` outputs. Rejected unless a new NeuroScape checkpoint is published.
- OpenAI `text-embedding-3-large` (3072 dim) — strictly better quality, ~$0.13/1M tokens vs $0.02. Operators can opt in via `--openai-model text-embedding-3-large`; not the default for cost.
- PubMedBERT `microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract` (the original) — requires manual mean-pooling. The `neuml/` Sentence-Transformers mirror is functionally identical, simpler to use, and what the prior bundles used.

## 2. Batching, concurrency, retry policy

### Decision

- **Batch size**: 64 inputs per HTTP call for both Voyage and OpenAI. Hardcoded as `_BATCH_SIZE = 64` in `embed_stage.py`. Final batch in a pass carries whatever subset is left.
- **Concurrency model**: Dynamic in-flight cap per provider, starting at 8. Backoff on observed 429: multiplicative ×0.5 with floor 1. Recover toward ceiling (24) when 100 consecutive non-429 responses succeed AND the provider's `x-ratelimit-remaining-requests` header indicates ≥ 25% headroom. The full concurrency curve (start, min, max, 429 count) is recorded in bundle `metadata.json`.
- **Retry policy** (per batch): up to 3 attempts. First attempt → flex tier (Voyage doesn't differentiate; OpenAI default tier). 429 → wait `Retry-After` seconds (if header present) or exponential backoff with jitter (1s, 2s, 4s); resubmit. 5xx → exponential backoff with jitter, same 3-attempt cap. Final-attempt failure → bundle counts the batch's abstracts as `failure_count` and continues; if the running failure rate exceeds the per-bundle threshold (1% default), the whole bundle aborts with a typed `EmbeddingError` and the partial cache is preserved.
- **Local HF models** (MiniLM, PubMedBERT): no HTTP — single-process batched encode via Sentence-Transformers' `encode(..., batch_size=64, show_progress_bar=False)`. Concurrency is irrelevant (Torch handles parallelism internally on whatever device is available).

### Rationale

Spec-mandated decisions (Clarifications session): batch=64 (Q1), dynamic concurrency starting at 8 (Q2). Multiplicative backoff is the standard pattern for both Voyage and OpenAI SDKs and matches the OpenAlex resolver's existing approach (`openalex.py:_handle_rate_limit_response`). Per-input cache writes happen on batch return so an interrupted run resumes at per-abstract granularity — verified by an integration test (`test_embed_stage.py:test_resume_byte_equivalent`).

### Alternatives considered

- Provider-max batches (Voyage 128, OpenAI 2048) — bigger blast radius on a single batch failure (more abstracts to retry); minimal HTTP-overhead gain at our scale.
- Single-batch-at-a-time (concurrency=1) — slowest; violates SC-001.
- Static concurrency=8 (no ramp) — simpler but leaves throughput on the table when the provider has spare capacity. Spec's Q2 explicitly picked dynamic.

## 3. Long-input handling

### Decision

| Model | Token cap | Default strategy | Chunk-pool params |
|---|---|---|---|
| Voyage `voyage-large-2-instruct` | 16k | `truncate_end` | n/a |
| OpenAI `text-embedding-3-small` | 8k | `truncate_end` | n/a |
| MiniLM `all-MiniLM-L6-v2` | 512 | `chunk_mean_pool` | window=512 tokens, overlap=64 |
| PubMedBERT `neuml/pubmedbert-base-embeddings` | 512 | `chunk_mean_pool` | window=512, overlap=64 |
| NeuroScape Stage 2 | matches Voyage upstream | n/a (operates on vectors, not text) | n/a |

Per-bundle `metadata.json` records: `strategy`, `model_max_tokens`, `chunk_window`, `chunk_overlap`, `pooling` ('mean' for chunk_mean_pool), `truncated_count` (number of abstracts that hit the cap), and an `affected_ids` list under 256 entries (truncated if longer).

### Rationale

Spec Clarifications Q3 picked option A. `truncate_end` is the standard SDK behavior for embedding APIs and matches what most published benchmarks use. `chunk_mean_pool` with overlap=64 mirrors the existing `neuroscape.py:hf_embed_with_chunking` logic — re-used (not re-written) here.

Per-component empirical text-length check on the live corpus:

```
component       p50 chars   p95 chars   p99 chars   max chars
title           ~120        ~210        ~280        ~400
introduction    ~1800       ~4200       ~5500       ~9000
methods         ~2200       ~4800       ~6800       ~12000
results         ~2400       ~5100       ~7300       ~14000
conclusion      ~700        ~1700       ~2400       ~3400
claims          ~1500       ~5500       ~9000       ~24000
```

For Voyage (16k tokens ≈ 64k chars) the truncation is rarely triggered (worst case: long `claims` concatenations exceed 24k chars at the tail; ~4× headroom). For OpenAI (8k tokens ≈ 32k chars) some abstracts will truncate in the `claims` and `methods`/`results` tail. For HF encoders (512 tokens ≈ 1.8k chars) the long-text components (`introduction`, `methods`, `results`, `claims`) routinely exceed the cap, so chunk_mean_pool is the default — without it, more than half of every abstract's text would be silently dropped.

### Alternatives considered

- `truncate_middle` — preserves the abstract's opening + closing but is asymmetric for fact-dense methods text; rejected as the default.
- `fail_per_abstract` — strict, treats every long abstract as a per-bundle failure, would push us over the 1% threshold for HF models — rejected.

## 4. Component text assembly

### Decision

The assembler reads the enriched SQLite (`abstracts_enriched.sqlite`), decompresses each row's `payload` (zlib + json), and produces a `dict[component_name, str]` per abstract. Component recipes:

- `title`: `record["title"]`, normalized (collapse whitespace).
- `introduction`, `methods`, `results`, `conclusion`: pull from `record["responses"]` where `question_name.lower()` matches the component. Convert HTML → markdown via the existing `enrichment.build_sections_markdown` helper. Empty → component absent for that abstract.
- `claims`: concatenate `record["claims"][i]["claim"]` for every claim in order, joined with `\n\n`. Empty list → component absent.

Absence is a signal: the orchestrator records the abstract in the bundle's `missing_ids` and excludes its row from `vectors.npy`. This is what makes bundles deterministically subset-stable across runs without requiring zero-pad rows.

The component-assembly hash (recorded in provenance) is `sha256(normalized_text)` per `(abstract_id, component)` pair — used as part of the cache key alongside the model identifier.

### Rationale

Mirrors the existing `neuroscape.py:abstract_to_embedding_text` function but factored out of the embedding pass into a pure assembler — separable, testable, reusable across all five models. The HTML→markdown normalization is necessary because Oxford Abstracts responses contain HTML (existing `enrichment.py` handles this consistently).

### Alternatives considered

- Re-parse HTML on every model pass — wasteful; the assembler runs once per `(abstract, component)` regardless of model count, so cost amortizes across all 5 models.
- Embed each claim separately and mean-pool — fragments the per-abstract signal; concat is what the existing `minilm_claims` bundle did.

## 5. NeuroScape published-Stage-2 application

### Decision

`neuroscape.apply_published_stage2` already exists and operates on a Voyage bundle directory. Stage 3 calls it per Voyage component bundle:

```python
for component in COMPONENTS:
    voyage_bundle = embed_voyage_component(component, ...)
    neuroscape_bundle = apply_published_stage2(
        voyage_bundle,
        output_dir=EMBEDDINGS_ROOT / f"neuroscape_{component}",
    )
```

The model checkpoint is read from `data/cache/neuroscape_models/` (populated on first use by the existing checkpoint downloader). Checkpoint version is part of the derived bundle's `metadata.json`.

### Rationale

`apply_published_stage2` is the proven path. Re-using it avoids re-implementing the NeuroScape model loader, axis alignment, and the half-precision matmul that the existing code handles. Determinism: PyTorch CPU inference with `torch.use_deterministic_algorithms(True)` and a fixed seed (already set in the existing function) yields byte-identical output for the same Voyage input + same model checkpoint.

### Alternatives considered

- Re-train a NeuroScape variant on the current Voyage outputs — out of scope; the published checkpoint is the canonical lens.
- Skip the NeuroScape derivation in v1 — rejected; the UI's `voyage_stage2_published` bundle depends on it.

## 6. Bundle directory format

### Decision

```
data/outputs/experiments/embeddings/<model_key>_<component>/
├── vectors.npy            # float32 [n_present × dim], C-order
├── ids.npy                # int64 [n_present], same order as vectors rows
├── metadata.json          # see contracts/bundle.schema.json
└── provenance.json        # see contracts/provenance.schema.json
```

The existing convention writes `ids` *inside* `metadata.json`. Stage 3 also breaks them out into `ids.npy` for fast mmap-style reads by downstream tools that don't want to parse a multi-MB JSON. `metadata.json` keeps a copy for human inspection. Both representations MUST match; the writer enforces this in a single atomic temp+rename pass.

### Rationale

Existing consumers (`cluster-benchmark`, `umap-plot`, `projection_comparison`) read `vectors.npy` + `metadata.json["ids"]`. Stage 3 keeps that path working AND adds `ids.npy` so the composition helper (which loads multiple bundles to mean-pool) can mmap the id arrays directly without ever decoding the metadata JSON for n bundles.

### Alternatives considered

- Single SQLite-with-zlib(json) file per model carrying all components — would match `enrich_storage.py`. Rejected because `vectors.npy` memory-mapping is what downstream numerical tools (umap-learn, sklearn) actually want; a SQLite hop adds a decode step. We may revisit if the bundle count becomes unwieldy in v2.
- Parquet (Arrow) with one row per abstract — flexible for cross-model joins but ~3× larger on disk for dense float matrices and slower to mmap. Rejected.

## 7. Provenance + state-key composition

### Decision

A Stage 3 run computes a global `state_key` (12 hex chars, sha256 prefix) over:

- The Stage 2.1 corpus state_key (`f0c51e80dc0e` currently)
- The sorted list of `(model_key, model_id, model_version)` triples participating in this run
- The sorted list of components participating in this run
- The batch size, concurrency policy, and long-input strategy choices
- Cache version constant (initial: `embed.matrix.v1`)

Provenance lives at `data/inputs/embeddings_matrix_provenance__<state_key>.json` with the same atomic-write contract as Stage 2.1. It links to every produced bundle by `bundle_path` (project-relative) and lists the per-bundle `corpus_state_key`, `model_id`, `model_version`, `component`, `count`, `failure_count`, `truncated_count`, and `wall_clock_seconds`.

### Rationale

Reuses the Stage 1 / Stage 2.1 state-key construction pattern (`artifacts.build_state_key`). The bundle directory's own `metadata.json` is the consumer-facing artifact; `provenance.json` is the audit record. Splitting matches CA-008.

## 8. Failure-threshold default

### Decision

Per-bundle failure threshold defaults to **1%** of the input row count. For 3244 abstracts that's 32 abstracts. Exceeded → typed `EmbeddingError`, partial cache preserved, exit code 5 (matches Stage 2.1's `ComponentFailureThresholdError`).

### Rationale

Embedding calls are simpler than Stage 2.1's figure / claims calls (no multi-modal payload, no agentic loop, no quality probing). The error envelope is narrower (network blip → covered by retry; auth → fails at startup; over-length → handled by truncate/chunk-pool). So 1% is a deliberate tightening from Stage 2.1's 5%; the operator can pass `--failure-threshold` to relax.

### Alternatives considered

- Match Stage 2.1's 5% — too permissive for embeddings; would allow 162 silent failures per bundle.
- Hard zero — too strict given inherent network variability.

## 9. Open questions deferred to implementation

- Should the matrix orchestrator pre-assemble *all* component text for *all* abstracts up front (one SQLite read pass for the whole corpus) or stream per-abstract per-model? Trade-off: ~30 MB of assembled text in memory vs. repeated SQLite reads. Recommended approach: pre-assemble once at the start of an `embed-matrix` run, hold in memory, share across the model passes. Defer the final decision to the tasks phase / first measurement.
- Whether to emit per-bundle UMAP + cluster artifacts in the same run, or keep that as a separate `umap-plot` / `cluster-benchmark` invocation (current convention). Defer; Stage 3's deliverable stops at the bundle.
