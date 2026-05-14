# Feature Specification: Stage 3 — Multi-Model Embeddings Matrix

**Feature Branch**: `005-embeddings-matrix`
**Created**: 2026-05-14
**Status**: Draft
**Input**: User description: "Stage 3 (embeddings). Generate embeddings from Voyage to match NeuroScape Stage 1, MiniLM for matching the web UI search model, OpenAI, apply NeuroScape model on Voyage to create NeuroScape embeddings, PubMedBERT, across a few combinations of text — full text, methods+results, title+results+conclusion, claims, inference claims (if all abstracts have them). They should be stored in an easily accessible and efficient format for downstream compute (clustering, UMAP, etc.)."

## Clarifications

### Session 2026-05-14

- Q: How should OpenAI and Voyage embedding requests be batched? → A: Fixed batch size 64 per call, per-input cache writes when the batch returns.
- Q: What is the canonical unit of embedding — multi-component recipes or atomic components? → A: Per-component only (title, introduction, methods, results, conclusion, claims). Downstream tasks compose recipes by averaging the relevant component vectors at consumption time.
- Q: How many concurrent paid-API batches should be in flight? → A: Dynamic — start at concurrency 8 per provider, ramp up/down based on observed 429 rate and provider rate-limit headers.
- Q: What's the default long-input strategy per model? → A: `chunk_mean_pool` for the local transformer encoders (MiniLM, PubMedBERT); `truncate_end` for the API embeddings (Voyage, OpenAI). Operators can override per-bundle via CLI flag.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Generate the canonical per-component embedding matrix for the freshly enriched corpus (Priority: P1)

A researcher running the analysis pipeline needs every `(model × component)` embedding bundle to be regenerated from the Stage 2.1 enriched corpus (`data/primary/abstracts_enriched.sqlite`, state_key `f0c51e80dc0e`, 3244 accepted abstracts). Existing bundles under `data/outputs/experiments/embeddings/` were computed against the prior 3333-record corpus AND against multi-component recipes (`stage1`, `methods-results`, `title-results-conclusion`) that the new design no longer materializes — downstream consumers compose those recipes from per-component vectors instead. The researcher invokes one canonical Stage 3 entrypoint that produces, for each requested `(model, component)` pair, a self-contained bundle directory.

**Why this priority**: All downstream analyses (clustering benchmark, UMAP, NeuroScape projections, semantic-community detection, organizer-facing UI search) consume these bundles, either directly or via the composition helpers (FR-006a). Until the per-component matrix exists for the new corpus, no downstream workflow can be rerun.

**Independent Test**: Run the canonical command targeting one `(model, component)` pair against the enriched SQLite. Verify the resulting bundle directory contains `vectors.npy` (≤ 3244 × D float32), `metadata.json` with the model id, model version, corpus state_key, component label, the present-row count, and the ordered list of abstract IDs that index the rows of `vectors.npy`. Verify the composition helper produces a recipe vector (e.g., title + results + conclusion mean) byte-identically from the per-component bundles.

**Acceptance Scenarios**:

1. **Given** the enriched corpus at state_key `f0c51e80dc0e`, **When** the operator runs Stage 3 for a single `(model, component)` pair, **Then** the bundle directory is written under `data/outputs/experiments/embeddings/<bundle-name>/`, contains the expected files, and the ordered IDs in `metadata.json` are a deterministic subset (or full match) of the enriched corpus's accepted abstracts, with rows for any abstract that lacks that component excluded from the matrix and recorded under a `missing_ids` field.

2. **Given** an embedding bundle already on disk from a previous run with identical `(corpus_state_key, model_id, model_version, component)`, **When** Stage 3 is rerun for the same pair, **Then** the existing bundle is reused unchanged (no model calls) and the operator sees a cache-hit summary on stdout.

3. **Given** a request for a `(model, component)` pair where some abstracts' component text exceeds the model's maximum input length, **When** Stage 3 runs, **Then** the per-abstract long-input strategy (truncate, chunk-pool, or fail-per-abstract) is recorded in the bundle's `metadata.json` and the operator is informed how many abstracts were affected.

---

### User Story 2 — Resume safely after a partial run (Priority: P1)

The Voyage and OpenAI embedding models are paid APIs and the full corpus pass for a single (model, component) pair takes ~15-30 minutes on flex tier. A run can be interrupted by network blips, daily-budget exhaustion, or operator cancellation. On resume, the pipeline must skip every abstract it has already embedded and continue only with the remaining ones.

**Why this priority**: Same-priority as P1 — without resume, every interruption forces a full re-spend on paid APIs. Cache-keyed resume is part of the operational contract for any LLM/API step (matches Stage 2.1's per-abstract caching pattern).

**Independent Test**: Start a run, kill it mid-corpus, restart with the same arguments, verify the second run completes only the remaining abstracts (zero re-calls for already-cached IDs) and produces a bundle identical to the uninterrupted-run baseline.

**Acceptance Scenarios**:

1. **Given** a Stage 3 run interrupted at abstract N of 3244, **When** the same command is rerun, **Then** the first N abstracts hit the per-abstract cache, only the remaining 3244-N are sent to the model, and the final bundle matches the byte-equivalent output of an uninterrupted run.

2. **Given** the daily budget is exhausted on the embedding provider, **When** Stage 3 hits the error, **Then** the partial cache is preserved on disk, the runner exits with a typed error naming the provider, and the operator can resume after budget reset without any data loss.

---

### User Story 3 — Express the embedding matrix as a single batch request (Priority: P2)

A researcher wants to regenerate the entire planned matrix (~30 component bundles: 5 models × 6 components, minus the partial-coverage `inference_claims` skipped by default) in one operator invocation. The command sequences bundles for cost-efficient ordering (local models first, paid APIs last; identical component text reused across models so the SQLite read + text-assembly cost is amortized).

**Why this priority**: Cost and operator-time savings. Not strictly required to unblock downstream work (P1 covers single-bundle generation), but the matrix-level batch entrypoint is a meaningful operational convenience.

**Independent Test**: Run the matrix command with a small filter (e.g., 1 model × 2 components); verify both bundles are produced, the assembled component text is computed once and reused across models, and the run-level summary reports per-bundle outcomes.

**Acceptance Scenarios**:

1. **Given** the operator requests the full default matrix, **When** the command runs, **Then** every planned `(model, component)` pair is produced or explicitly skipped (with reason), and a single matrix-level summary records cache hits/misses per bundle.

2. **Given** the operator filters the matrix to a subset (e.g., `--models voyage,minilm --components claims,methods`), **When** the command runs, **Then** only the filtered bundles are processed.

---

### User Story 4 — Verify the NeuroScape-over-Voyage derived embedding (Priority: P2)

The NeuroScape Stage 1 paper publishes a transformer that maps Voyage embeddings into a NeuroScape-aligned space. Stage 3 must produce a derived bundle `neuroscape_<component>` from each Voyage bundle by applying the published NeuroScape model. The derived bundle MUST be deterministically reproducible from its Voyage input + the NeuroScape model checkpoint.

**Why this priority**: NeuroScape Stage 2 is the canonical lens the project uses to align with the broader NeuroScape ecosystem. Necessary for the published-lens analyses but not blocking general clustering / UMAP work (which has alternatives).

**Independent Test**: Given a Voyage bundle, apply the NeuroScape transform; rerun the same operation; verify the two output bundles are byte-identical (the NeuroScape transform is deterministic given fixed input and model version).

**Acceptance Scenarios**:

1. **Given** a Voyage bundle for a component, **When** the NeuroScape application step runs, **Then** the output bundle name encodes both the source component and the NeuroScape model version, and the bundle's `metadata.json` records the upstream Voyage `bundle_state_key` and the NeuroScape `model_version`.

2. **Given** the NeuroScape model checkpoint is missing or unverified, **When** the operator runs the derivation, **Then** the runner fails loudly with a typed error naming the missing artifact rather than silently producing an empty or unaligned output.

---

### User Story 5 — Handle components with partial corpus coverage (Priority: P3)

The user's input listed "inference claims (if all abstracts have them)" as a candidate component. Inspection of the enriched corpus shows that only 399 of 3244 abstracts (12.3%) carry ≥1 `IMPLICIT` claim. More broadly, any per-component slice (e.g., abstracts with empty `methods` text) can leave gaps. Stage 3 must either omit a non-default component (`inference_claims`) entirely or, when invoked with explicit consent, produce a clearly labeled `_partial` bundle whose row count matches the coverage subset and whose `metadata.json` records both the total accepted-corpus count and the per-component subset count.

**Why this priority**: Edge-case handling that protects downstream consumers from surprise. Default behavior must not produce silently-partial bundles, and the downstream composition helpers (FR-006a) must distinguish "row absent because abstract lacks this component" from "all rows present".

**Independent Test**: Run Stage 3 with `component=inference_claims`; verify the runner emits a coverage warning naming the affected abstract IDs, refuses to write a "complete" bundle, and offers an opt-in `--allow-partial` path that produces a `_partial` bundle with the 399-row subset.

**Acceptance Scenarios**:

1. **Given** a requested component for which not every accepted abstract has content, **When** Stage 3 runs, **Then** the runner reports the coverage gap and exits with a typed error unless the operator explicitly passes a `--allow-partial` flag.

2. **Given** the operator passes `--allow-partial`, **When** the runner completes, **Then** the bundle is written under a `_partial` suffix and `metadata.json` records both the total accepted-corpus count and the per-bundle subset count; the composition helper treats missing rows as "this component does not contribute to the mean for that abstract".

---

### Edge Cases

- An abstract's assembled text for a requested component is empty (e.g., the submitter left every prose response blank). The runner MUST treat that abstract's row as an explicit failure for this component, count it against a per-component failure threshold, and never emit a zero-vector silently.
- An abstract's assembled text exceeds the chosen model's maximum input length (typically Voyage ≤32k tokens, OpenAI text-embedding-3 ≤8k tokens, MiniLM / PubMedBERT ≤512 tokens). The runner MUST apply a documented long-input strategy (truncate at model limit, or chunk + mean-pool, recorded per-source in the spec/plan) and surface the count of abstracts that were truncated in `metadata.json`.
- The Voyage or OpenAI provider returns rate-limit or budget-exhaustion errors mid-run. The cache MUST preserve every completed abstract; the runner MUST exit non-zero with a typed error so resume picks up exactly where it left off.
- A re-run uses an unchanged corpus but a bumped model version (e.g., Voyage `voyage-3-large` → `voyage-3.1-large`). The bundle's `metadata.json` MUST capture the new model id and produce a separate bundle directory; the previous bundle MUST NOT be silently overwritten.
- An operator passes `--allow-partial` on a component that turns out to have full coverage. The runner MUST produce the same bundle that the non-partial command would have produced (no `_partial` suffix when coverage is complete).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a single canonical Stage 3 CLI entrypoint that takes one or more `(embedding_model, component)` pairs as input and produces, for each pair, an embedding bundle directory under `data/outputs/experiments/embeddings/<bundle-name>/`.
- **FR-002**: Bundle directory names MUST follow `<model_key>_<component>` (e.g., `voyage_methods`, `minilm_claims`, `pubmedbert_title`). Downstream tools that previously consumed multi-component bundles (`*_stage1`, `*_methods-results`, `*_title-results-conclusion`) MUST be migrated to call the composition helpers (FR-006a); this migration is part of the Stage 3 implementation, not a separate change.
- **FR-003**: Every bundle MUST contain at minimum: `vectors.npy` (float32, shape `[n_abstracts × dim]`), `metadata.json` (count, ordered ids, model_name, model_id, model_version, component, corpus_state_key, dim, dtype, run timestamp, command line, code revision, long-input strategy, optional partial-coverage marker), and (when applicable) `provenance.json` recording the inputs hash chain (corpus → component assembly → model output).
- **FR-004**: The `ids` array in `metadata.json` MUST be a permutation-stable list of accepted-abstract IDs from the enriched corpus's accepted partition, in a deterministic order (sorted by abstract id) so that `vectors.npy[i]` always corresponds to the i-th id in `ids`.
- **FR-005**: The system MUST support five embedding models for v1: **Voyage** (current production model id captured at runtime, matching NeuroScape Stage 1's choice), **MiniLM** (`sentence-transformers/all-MiniLM-L6-v2`, matching the static-UI search model), **OpenAI** (`text-embedding-3-small` as default, identifier overridable), **PubMedBERT** (microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract or the project's pinned variant), and **NeuroScape-published** (derived by applying the published NeuroScape model to a Voyage bundle).
- **FR-006**: The system MUST embed ONLY at the atomic-component granularity. The canonical components for v1 are: `title`, `introduction`, `methods`, `results`, `conclusion`, and `claims` (per-abstract concatenation of every Stage 2.1 claim's `claim` field joined with `\n\n`). Multi-component recipes such as full-manuscript or methods+results MUST NOT be embedded as their own bundles; they are derived downstream from the component vectors.
- **FR-006a**: The system MUST provide a documented downstream-composition convention: a recipe is a list of component names, and the recipe's vector for an abstract is the mean of that abstract's component vectors (where the mean is taken over only the components present for that abstract, with the per-abstract present-component count recorded). Composition is performed at consumption time by `neuroscape.py` helpers (or callers) and does NOT produce additional persisted bundles in v1.
- **FR-006b**: Component bundle names MUST follow `<model_key>_<component>` (e.g., `voyage_methods`, `minilm_claims`, `pubmedbert_title`). Recipes that previously had their own bundle names (`stage1`, `methods-results`, `title-results-conclusion`) are removed from the v1 bundle inventory; documentation MUST list the recipe → component mapping so downstream callers can request the right composition.
- **FR-007**: The system MUST evaluate coverage for every component before writing a bundle. Components like `inference_claims` (the `IMPLICIT`-only subset of claims) cover only a fraction of the corpus — 12.3% of 3244 in the current corpus — and MUST NOT be written as a full-coverage bundle. Instead the runner MUST refuse with a typed error naming the coverage statistics; an opt-in `--allow-partial` flag produces a `_partial` bundle whose `metadata.json` records both the total accepted-corpus count and the per-component subset count. Each per-abstract row in a partial bundle MUST still index back to a real abstract id; the bundle MUST NOT silently pad with zero vectors. Components in scope for default-coverage v1: `title`, `introduction`, `methods`, `results`, `conclusion`, `claims`. Out-of-scope (partial-only): `inference_claims`.
- **FR-008**: NeuroScape-derived bundles MUST be produced as a transformation of an existing Voyage bundle (not by re-embedding the corpus from raw text). One NeuroScape bundle is produced per Voyage component bundle (e.g., `neuroscape_methods` is the NeuroScape transform of `voyage_methods`). Each derived bundle's `metadata.json` MUST record the upstream Voyage bundle's state_key, the NeuroScape model version, and the transformation date.
- **FR-009**: The system MUST cache per-abstract embedding outputs keyed by `sha256(input_text || model_id || model_version)` so that interrupted runs resume from the cache and complete-corpus reruns with the same inputs hit cache. Cache entries live under `data/cache/embeddings/<model_key>/` with the same atomic-write contract as Stages 1 and 2.
- **FR-009a**: For paid embedding providers (Voyage and OpenAI), the system MUST send embedding requests in batches of up to 64 inputs per HTTP call rather than one input per call. Per-input cache writes MUST happen when the batch returns successfully so that an interrupted run resumes at per-abstract granularity (not per-batch). When fewer than 64 cache-misses remain at the end of a pass the final batch carries whatever subset is left; partial-batch retries MUST preserve per-input atomicity.
- **FR-009b**: For paid embedding providers, the system MUST run multiple batches concurrently with a dynamic in-flight cap. The cap starts at **8** per provider, decreases on every observed HTTP 429 (rate-limit response) by a documented multiplicative factor with a floor of 1, and increases back toward a ceiling when the provider's rate-limit headers (`x-ratelimit-remaining`, `x-ratelimit-reset`, or equivalent) indicate spare capacity. The per-batch retry-with-backoff path MUST honor the provider's `Retry-After` header when present. The final concurrency curve over the run MUST be summarized in the bundle's `metadata.json` (start cap, min cap observed, max cap observed, 429 count) so operators can tune the ceiling for the next run.
- **FR-010**: The system MUST surface long-input handling per (model, component) pair: each model carries a documented maximum input length, and per-pair strategies are one of `truncate_end`, `truncate_middle`, `chunk_mean_pool`, or `fail_per_abstract`. **Defaults**: `chunk_mean_pool` for the local transformer encoders (MiniLM, PubMedBERT) — over-length text is split into overlapping windows at the encoder's token cap and the resulting vectors are mean-pooled; `truncate_end` for the API embeddings (Voyage, OpenAI) — text past the model's cap is dropped from the end with the kept length recorded. The strategy chosen for the run MUST be recorded in `metadata.json` along with the chunk size, overlap, and pooling rule (for `chunk_mean_pool`), or the truncation point (for `truncate_*`). Operators MAY override the per-model default via a CLI flag; an override MUST be recorded in `metadata.json` so analyses comparing bundles can detect the mismatch.
- **FR-011**: The system MUST emit a per-bundle run summary on stdout in a single JSON object with at minimum: `bundle_path`, `model_id`, `component`, `corpus_state_key`, `count`, `cache_hit_count`, `cache_miss_count`, `failure_count`, `truncated_count`, `wall_clock_seconds`. The orchestrator-level matrix command MUST emit a single rollup JSON listing each bundle's outcome.
- **FR-012**: The system MUST fail loudly on any external-provider authentication error (missing API key) at startup of the relevant model's pass; no model pass MUST proceed silently without credentials when the model requires them.
- **FR-013**: The system MUST refuse to overwrite an existing bundle directory that carries a different `corpus_state_key` than the current corpus, even when filenames match. The runner MUST archive the prior bundle (or refuse the run) so prior analyses remain reproducible.
- **FR-014**: The Stage 3 entrypoint MUST be invocable via a single canonical CLI (mapped through `ohbmcli` or a top-level script in `scripts/`) and MUST be runnable through the repository-local `.venv/bin/python`.
- **FR-015**: Provenance for every bundle MUST list project-relative paths only (no absolute or `~`-prefixed paths), matching Stage 1's and Stage 2.1's `_assert_paths_safe` contract.

### Key Entities

- **Embedding bundle**: A directory under `data/outputs/experiments/embeddings/<bundle-name>/` containing the vectors, ordered abstract ids, and metadata for one `(model, component)` pair against one corpus state. The unit of cache-aware regeneration.
- **Text source**: A named recipe for assembling a single string per abstract from the enriched corpus (manuscript responses + claims). Recipes are pure functions: same enriched record → same text. Used as the input to every embedding model.
- **Embedding-matrix run**: An operator invocation that requests one or more (model, component) bundles. Reports a per-bundle outcome and a roll-up summary.
- **Per-abstract embedding cache entry**: A small file under `data/cache/embeddings/<model_key>/<cache_key>.json` carrying the vector + provenance for one abstract. Cache key is `sha256(input_text || model_id || model_version)` matching the project's Stage 2 caching pattern.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python execution for this feature MUST use the repository-local `.venv/bin/python` interpreter or `uv` targeting that interpreter. The Stage 3 entrypoint script will follow the `scripts/run_*.py` pattern that sets `sys.path` to the `.venv` and invokes the in-tree library code.
- **CA-002**: Tests MUST be added or identified before implementation for each behavior-changing user story: a per-component assembly test (golden text given a known enriched record), a per-model embedding test (fake model returns a deterministic vector; assert bundle shape and metadata), a resume test (interrupt + restart yields byte-equivalent output), a coverage-gate test (refuses partial bundles by default), and a NeuroScape-derivation test (deterministic transform).
- **CA-003**: This change updates canonical defaults consumed by downstream tools (the UI / clustering uses `voyage_stage2_published` and `minilm_claims`). The `README` (operational runbook), `docs/reproducibility-vision.md`, and `CLAUDE.md` MUST be updated in the same change to point at the new bundle names and the new state_key.
- **CA-004**: The Voyage, OpenAI, and Semantic-Scholar / HF integrations all use credentials. The spec names: `VOYAGE_API_KEY`, `OPENAI_API_KEY`, and optionally `HF_TOKEN` (for any gated PubMedBERT mirror). Keys MUST be loaded from `.env` in-memory and passed to the SDK constructors (never written to `os.environ`), matching the Stage 2.1 wiring pattern.
- **CA-005**: Every bundle, cache entry, and provenance record lands under gitignored roots (`data/outputs/experiments/embeddings/`, `data/cache/embeddings/`, `data/inputs/`). The spec MUST NOT propose tracking any generated embedding artifact in the repository.
- **CA-006**: External-call failures MUST be explicit: missing API keys → typed startup error; provider rate-limits / budget exhaustion → typed per-bundle error with the partial cache preserved; per-abstract decode failures → counted against a per-bundle failure threshold (default 1%) with an exit-code 5 abort when exceeded.
- **CA-007**: The system MUST discover model identifiers from runtime (the SDK's reported model id captured at first successful call, NOT hardcoded). For published NeuroScape model the checkpoint version is read from the downloaded artifact's metadata, not from a hardcoded string.
- **CA-008**: Every bundle directory MUST include both `metadata.json` (consumed by downstream tools) and `provenance.json` (the audit record). `provenance.json` is the bundle's organizer-facing artifact and MUST carry project-relative paths only and the full input-hash chain (corpus_state_key → component assembly hash → cache-key strategy → model id).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fresh Stage 3 run against the current enriched corpus (state_key `f0c51e80dc0e`, 3244 accepted abstracts) produces all 30 default-matrix component bundles (5 models × 6 components) in under **120 minutes** wall-clock on a single workstation when paid APIs are reachable, given batch-size 64 and a flex-tier-enabled budget.
- **SC-002**: A cached re-run with no input changes completes in under **2 minutes** (every abstract hits cache; no model calls).
- **SC-003**: An interrupted run, on resume, makes **zero** model calls for abstracts whose cache entries were written before the interruption — verified at per-abstract granularity (not per-batch).
- **SC-004**: Every existing downstream consumer (cluster-benchmark, UMAP plotter, projection comparator, UI export) reads either a per-component bundle directly or a composed recipe via the FR-006a composition helper. At least one canonical recipe — `title + introduction + methods + results + conclusion` — produces a composed vector matrix whose values match a direct concatenation-embedding baseline to within a documented tolerance (cosine similarity ≥ 0.90 on a 50-abstract sample) when both paths use the same model.
- **SC-005**: The matrix command refuses to produce a complete-corpus `inference_claims` bundle (given current coverage of 12.3%) and surfaces the coverage statistics in its error message; the opt-in `--allow-partial` flag produces a `_partial` bundle with exactly 399 rows.
- **SC-006**: A run that hits a model's input-length cap on at least one abstract reports a non-zero `truncated_count` in `metadata.json` and the operator can identify the affected abstract ids from the cache directory.

## Assumptions

- The enriched corpus (`data/primary/abstracts_enriched.sqlite`) is the canonical source of input text for every component — Stage 3 does NOT re-read Stage 1's `data/primary/abstracts.json` directly; it always goes through the SQLite store so that claims and figure-interpretation context are reflected when the chosen component includes them.
- The existing bundle layout (`vectors.npy` + `metadata.json` in a directory per bundle, with optional clustering / UMAP / projection sibling files) is the canonical efficient format for downstream compute. NumPy memory-mapped reads of `vectors.npy` are an order of magnitude faster than per-row decode from SQLite-with-zlib and are what `scikit-learn`, `umap-learn`, and the project's `neuroscape.py` already consume.
- `inference_claims` is dropped from the default matrix because only 12.3% of abstracts carry an `IMPLICIT` claim (399 of 3244). The full-corpus claims source remains because 99.94% coverage is high enough to treat the two missing abstracts as per-source failures.
- The `claims` component concatenates the `claim` field of every Stage 2.1 claim for an abstract, separated by `\n\n`, in the order the claims appear in the enriched record. This is deterministic, and chunking is unnecessary because Voyage and OpenAI's input limits accommodate the median claims length comfortably (typical abstract has 5-15 claims, each ≤200 characters).
- Composition by averaging — used to derive multi-component recipes from per-component bundles — is the project's chosen approximation for representing concatenated text. Cosine-similarity-vs-baseline checks (SC-004) document where the approximation holds; users who need true concatenation embeddings for a specific analysis can re-embed that recipe ad hoc outside the canonical matrix.
- The published NeuroScape model is available as a versioned checkpoint downloadable on first use and is cached locally under `data/cache/neuroscape_models/`. Re-applying it is deterministic.
- A "failure" for a component is per-abstract, not per-claim: a single missing field surfaces as a row that gets counted against the per-bundle failure-threshold rather than aborting the whole bundle.
- The `voyage_stage2_published` and `minilm_claims` bundle names referenced by the live UI are no longer materialized directly. The UI export step is updated in the same change to consume per-component bundles plus a recipe composition (claims for `minilm_claims`, a documented NeuroScape-aligned recipe for `voyage_stage2_published`). The UI bundle names visible to the frontend stay the same; their on-disk source changes.
- This spec covers v1 of Stage 3: the model lineup is the five listed; long-input strategy is per-(model, component) recorded in the plan; per-row UPSERT cache writes match Stage 2's pattern. v2 may add additional models (e.g., domain-specific embeddings) or alternative pooling strategies but is out of scope here.
- The legacy bundles under `data/outputs/experiments/embeddings/` from the prior 3333-record corpus will be archived (gitignored move to `archive/`) as part of the Stage 3 implementation, not in this spec.
