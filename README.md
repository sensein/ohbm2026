# OHBM 2026 Pipeline

This repository builds a local OHBM 2026 abstract corpus from the Oxford
Abstracts GraphQL API and carries it through figure enrichment, reference
matching, embeddings, clustering, and a static search UI.

This README is the runbook for a person or an agent that needs to go from the
original abstract download to the current latest step.

Project conventions that should not be violated live in
[CONSTITUTION.md](/Users/satra/software/temp/ohbm2026/CONSTITUTION.md),
including the rules that Python work stays inside the repository-local `.venv`,
recorded experiment runs write to fresh directories instead of overwriting prior
outputs, behavior-changing work stays plan-first and test-driven, and secrets
never get copied into the repo or logs.

For the repo-level intent, reproducibility model, key decisions, and experiment
history, start with
[docs/reproducibility-vision.md](/Users/satra/software/temp/ohbm2026/docs/reproducibility-vision.md).

Catalogs for the rest of the repository:

- [docs/README.md](/Users/satra/software/temp/ohbm2026/docs/README.md)
- [experiments/README.md](/Users/satra/software/temp/ohbm2026/experiments/README.md)

Recommended reading order for a new person or agent:

1. [docs/reproducibility-vision.md](/Users/satra/software/temp/ohbm2026/docs/reproducibility-vision.md)
2. [docs/README.md](/Users/satra/software/temp/ohbm2026/docs/README.md)
3. [README.md](/Users/satra/software/temp/ohbm2026/README.md)
4. [CONSTITUTION.md](/Users/satra/software/temp/ohbm2026/CONSTITUTION.md)
5. [memory/summary.md](/Users/satra/software/temp/ohbm2026/memory/summary.md)
6. the specific plan or experiment README closest to the work you are changing

## What The Pipeline Produces

Core artifacts:

- `data/inputs/abstracts_graphql__<state-key>.json`
  - GraphQL-fetched source snapshot for the latest ingest run
- `data/abstracts.json`
  - canonical normalized accepted abstracts derived from the fetched snapshot
- `data/assets/`
  - downloaded local figure files, restricted to methods/results figures
- `data/cache/figure_analysis/image_analyses_<backend>__<state-key>.json`
  - resumable figure-analysis cache with direct state-key lookup
- `data/cache/claim_analysis/claim_analyses_cllm__<state-key>.json`
  - resumable `cllm` claim-extraction cache with direct state-key lookup
- `data/title_modifications.json`
  - audit log of cleaned abstract titles versus original raw titles
- `data/abstracts_enriched.json`
  - enriched abstract corpus with markdown sections, figure analyses, and claim extraction when available
- `data/reference_metadata.json`
  - OpenAlex-matched reference metadata
- `data/embeddings/*`
  - canonical embedding bundles, stage-2 projections, and neighbors
- `data/outputs/experiments/*__<state-key>/`
  - clustering, projection, and other experiment-style derived outputs
- `data/outputs/exported-sites/ui-site__<state-key>/`
  - local exported-site bundle before optional publish mirroring
- `data/outputs/proposals/*__<state-key>/`
  - proposal bundles and proposal-adjacent analysis outputs
- `export/ui-site/`
  - optional publish mirror of the latest exported-site bundle

Local artifact layout rules:

- `data/inputs/` is for fetched source snapshots
- `data/cache/` is for resumable caches and checkpoints
- `data/outputs/experiments/`, `data/outputs/exported-sites/`, and
  `data/outputs/proposals/` are for local derived outputs
- `archive/` is for local pre-migration backups that preserve legacy paths
- legacy artifact paths may temporarily remain as symlinks into the new layout
- `data/`, `export/`, and `tmp/` remain ignored by git

## Current Latest Step

The latest end state of the project is:

1. accepted abstracts downloaded locally
2. methods/results figures downloaded and linked
3. OpenAI figure text promoted into the main enriched abstract dataset
4. reference metadata matched with OpenAlex where possible
5. multiple embedding bundles generated
6. published NeuroScape stage-2 applied to Voyage embeddings
7. clustering benchmarks run on embedding bundles
8. static UI built with:
   - lexical search
   - browser-side semantic search
   - facets
   - UMAP selection
   - two semantic cluster lenses:
     - `25-cluster benchmark`
     - `claims 28-cluster benchmark`

## External Requirements

Required:

- `python` 3.11+
- `uv`

Optional, depending on which branch of the pipeline you run:

- `ollama`
- local Ollama model `qwen3.5:35b`
- Hugging Face access for downloading sentence-transformer models
- OpenAI API access for hosted figure analysis, OpenAI embeddings, and `cllm` claim extraction
- Voyage API access for Voyage embeddings
- OpenAlex API key for authenticated reference matching

## Environment Variables

Create `.env` from [.env.sample](/Users/satra/software/temp/ohbm2026/.env.sample).

Common keys:

- `OHBM2026_API`
  - required for Oxford Abstracts ingest and author lookup
- `OPENAI_API_KEY`
  - required for OpenAI figure analysis, OpenAI embeddings, or `extract-claims`
- `VOYAGE_API`
  - required for Voyage embeddings
- `OPENALEX_API`
  - optional but recommended for reference enrichment
- `HF_TOKEN`
  - optional for Hugging Face model downloads

No API key is needed for local Ollama figure analysis.

Treat `.env` and shell environment variables as the only valid homes for these
secrets. Do not commit tokens, paste them into docs, or leave them in command
logs.

## Setup

Do not use system Python in this repo. Create or refresh `.venv` with `uv`, and
run Python commands through `.venv/bin/python` or `uv` targeting that
interpreter.

Create the virtual environment and run tests:

```bash
UV_CACHE_DIR=.uv-cache uv venv --python 3.11 .venv
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Optional Python packages by workflow:

MiniLM or HF embeddings:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python sentence-transformers
```

Interactive projections:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python plotly umap-learn
```

Claim extraction:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python git+https://github.com/OpenEvalProject/cllm.git
```

Headless layout review:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[review]"
PYTHONPATH=src .venv/bin/python -m playwright install chromium
PYTHONPATH=src .venv/bin/python scripts/check_layout_review.py
```

For local figure analysis, confirm Ollama can see the required model:

```bash
ollama list
```

## End-To-End Workflow

Use `ohbmcli` for the whole pipeline.

### 1. Download The Raw Abstracts And Figures

This is the canonical starting point.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli ingest
```

What it does:

- fetches accepted abstracts from Oxford Abstracts
- stores the normalized corpus in `data/abstracts.json`
- downloads only methods/results figure images
- writes local figure links into each abstract

Important behavior:

- retries use an exponential timeout schedule starting at `100ms` and capped at `10s`
- figure downloads are reuse-aware

### 2. Refresh Assets Without Rerunning Abstract Extraction

Use this if the raw JSON already exists and you only need to rebuild or prune
local figure links.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli refresh-assets --reuse-existing-assets-only
```

### 3. Export Authors

Optional, but useful if you want a separate author database.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli authors
```

Output:

- `data/authors.json`

### 4. Run Figure Analysis

There are two supported routes.

#### Route A: OpenAI figure analysis

This is the current preferred route for the main enriched corpus.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-figures \
  --vision-backend openai \
  --openai-model gpt-4.1-mini \
  --enriched-output data/abstracts_enriched_openai.json
```

Notes:

- the cache is incremental and resumable
- current code batches OpenAI image requests for better throughput
- finished analyses are written as they complete

#### Route B: Local Ollama figure analysis

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-figures \
  --vision-backend ollama \
  --vision-model qwen3.5:35b
```

### 5. Build The Main Enriched Abstract Dataset

This step converts abstract content to ordered markdown and merges figure
analysis plus any cached claim extraction back into the canonical enriched
corpus.

Current default:

- `enrich` now defaults to the OpenAI figure-analysis cache under
  `data/cache/figure_analysis/`
- `enrich` now also defaults to the `cllm` claim cache under
  `data/cache/claim_analysis/`

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich
```

Explicit form:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich \
  --input data/abstracts.json \
  --image-analyses-input data/cache/figure_analysis/image_analyses_openai__<state-key>.json \
  --claim-analyses-input data/cache/claim_analysis/claim_analyses_cllm__<state-key>.json \
  --enriched-output data/abstracts_enriched.json
```

Output:

- `data/abstracts_enriched.json`

This is the main corpus used by downstream steps.

### 6. Audit And Clean Display Titles

The raw Oxford Abstracts export is kept unchanged, but downstream consumers now
normalize obvious title issues such as leading bullets, wrapping quotes, and
stray outer whitespace.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli title-audit \
  --input data/abstracts.json \
  --output data/title_modifications.json
```

Output:

- `data/title_modifications.json`

This file records each changed title with the original string, cleaned title,
and normalization reasons.

### 7. Match References With OpenAlex

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli reference-metadata \
  --input data/abstracts.json \
  --output data/reference_metadata.json \
  --use-title-search
```

Output:

- `data/reference_metadata.json`

This file is resumable and checkpoint-friendly.

Reference resolution now follows this order:

- markdown normalization of the raw references field
- LLM-assisted splitting of the full reference markdown block, validated against the source text
- exact DOI -> OpenAlex
- exact PMID -> OpenAlex
- direct OpenAlex title search for references with a title
- Semantic Scholar full-reference search only for references that still have neither DOI nor title

Current operational notes:

- the OpenAI splitter runs one request per abstract attempt and can be driven concurrently
- failed or invalid splits can be requeued and retried before falling back to a single-block record
- OpenAlex title search can also run concurrently with an explicit requests-per-second cap
- OpenAlex `/rate-limit` is the best way to inspect current search budget before a long rerun

Useful options:

- `--no-doi-discovery`
  - skip the Semantic Scholar full-reference DOI-discovery fallback
- `--no-llm-reference-splitting`
  - skip the OpenAI/Ollama splitting pass and fall back to local markdown heuristics
- `--reference-splitting-backend openai`
  - use OpenAI for the splitting helper
- `--reference-splitting-model gpt-5-nano`
  - model used for reference structuring; defaults to `gpt-5-nano`
  - the OpenAI backend uses the Responses API with a strict JSON schema for `{"references": [{"reference", "title", "doi"}]}` output
  - extracted `title` and `doi` values are only used downstream if they are lexically present in the returned reference text
- `--split-concurrency 500`
  - number of in-flight OpenAI reference-splitting requests during collect
- `--split-max-requeues 5`
  - maximum retries for failed or invalid split attempts before falling back to a single merged block
- `--title-concurrency 50`
  - number of concurrent OpenAlex title-search workers
- `--title-max-rps 90`
  - soft request-rate cap for OpenAlex title search; useful for staying below OpenAlex short-window throttle limits
- `--doi-discovery-similarity-threshold 0.8`
  - minimum title similarity required before accepting a discovered DOI
- `--delay-seconds 1.05`
  - pacing for sequential fallback phases such as Semantic Scholar DOI discovery

If a completed reference map still contains fallback split cases, rerun only those
abstracts and merge the repaired results back into the existing output:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli reference-metadata \
  --input data/abstracts.json \
  --output data/reference_metadata.json \
  --repair-failed-splits-from data/reference_metadata.json \
  --use-title-search \
  --reference-splitting-backend openai \
  --reference-splitting-model gpt-5-nano
```

### 8. Optional Claim Extraction

If you want claim lists over the abstracts, run this after figure analysis so
cached figure notes can be included in the `cllm` manuscript.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli extract-claims
```

What it does:

- reads `data/abstracts.json`
- reads the OpenAI figure-analysis cache under `data/cache/figure_analysis/` by
  default so figure-analysis text can be appended when present
- builds a manuscript from the title, introduction, methods, results, discussion, conclusion, and filtered additional-content fields
- excludes references and acknowledgements from the claim prompt
- writes a resumable cache under `data/cache/claim_analysis/`

Current default OpenAI path:

- provider: `openai`
- model: `gpt-4o-2024-08-06`

Useful explicit form:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli extract-claims \
  --input data/abstracts.json \
  --image-analyses-input data/cache/figure_analysis/image_analyses_openai__<state-key>.json \
  --claim-analyses-output data/cache/claim_analysis/claim_analyses_cllm__<state-key>.json \
  --openai-model gpt-4o-2024-08-06
```

If you want the claims to appear in the UI, rerun:

- `enrich`
- `build-ui`

### 9. Generate Embeddings

Pick one or more embedding routes.

MiniLM:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-minilm
```

OpenAI:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-openai
```

Voyage:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-voyage
```

Hugging Face model:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-hf \
  --model neuml/pubmedbert-base-embeddings
```

Embedding text is built on demand from:

- `title`
- `claims`
- `introduction`
- `methods`
- `results`
- `conclusion`

You can override the fields at runtime, for example:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-minilm \
  --fields title methods results
```

To build a claims-only embedding bundle:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-minilm \
  --fields claims \
  --output-name minilm_claims
```

This uses `claim_extraction.claims` from `data/abstracts_enriched.json` and formats each extracted claim as a short bullet containing the claim statement itself.

### 9. Apply Or Train Stage 2

#### Apply the published NeuroScape stage-2 model

Use this when you have a compatible Voyage stage-1 bundle.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli apply-published-stage2
```

#### Train a local stage-2 model

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-stage2
```

### 10. Build Semantic Analysis And Cluster Outputs

Community detection over an embedding bundle:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli semantic-analysis \
  --embeddings-dir data/embeddings/voyage_stage2_published
```

Clustering benchmark over an embedding bundle:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli cluster-benchmark \
  --embeddings-dir data/embeddings/voyage_stage2_published \
  --output-dir data/outputs/experiments/clustering_benchmark__<state-key>
```

To benchmark a claims-only bundle around `25-30` clusters:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli cluster-benchmark \
  --embeddings-dir data/embeddings/minilm_claims \
  --output-dir data/outputs/experiments/clustering_benchmark_claims_25_30__<state-key> \
  --k-min 25 \
  --k-max 30
```

This is the current claims-cluster artifact consumed by the UI. The latest run selected a `28`-cluster k-means solution inside that benchmark output.

Projection outputs:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli umap-plot
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli compare-projections
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli optimize-projections
```

### 11. Build The Static UI

This is the current latest delivery step.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui
```

The current default UI build uses:

- `data/abstracts.json`
- `data/abstracts_enriched.json`
- `data/reference_metadata.json`
- the OpenAI figure-analysis cache under `data/cache/figure_analysis/`
- `data/embeddings/voyage_stage2_published/clustering_benchmark`
- `data/embeddings/minilm_claims/clustering_benchmark_25_30`
- `data/embeddings/minilm_stage1/umap_title-introduction-methods-results-conclusion.json`

By default `build-ui` now writes the local bundle under
`data/outputs/exported-sites/ui-site__<state-key>/` and mirrors that bundle to
`export/ui-site/`. Pass `--site-output-dir` or `--publish-dir` to override one
or both locations.

Useful explicit form if you want to point the UI at a different claims-cluster run:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui \
  --site-output-dir data/outputs/exported-sites/ui-site__<state-key> \
  --publish-dir export/ui-site \
  --cluster-25-dir data/embeddings/voyage_stage2_published/clustering_benchmark \
  --claims-cluster-dir data/embeddings/minilm_claims/clustering_benchmark_25_30
```

The exported detail payload now includes:

- merged `claim_extraction` from `data/abstracts_enriched.json`
- `reference_summary` from `data/reference_metadata.json`
- `semantic_25` and `claims_28` cluster lenses in the facet and detail metadata

Then serve it locally:

```bash
.venv/bin/python -m http.server 8000
```

Open:

- `http://localhost:8000/export/ui-site/`

## Suggested Minimal Rebuilds

If you already have raw abstracts:

- rerun figure analysis
- rerun `extract-claims` if claim prompts should reflect updated figure analyses
- rerun `enrich`
- rerun `build-ui`

If you already have figures and only changed UI code:

- rerun `build-ui`

If you already have fresh figure analyses and only changed claim extraction:

- rerun `extract-claims`
- rerun `enrich`
- rerun `build-ui`

If you already have embeddings but want new cluster evaluations:

- rerun `cluster-benchmark`
- optionally rerun `build-ui`

If you specifically want to refresh the claims-based semantic lens:

- rerun `embed-minilm --fields claims --output-name minilm_claims`
- rerun `cluster-benchmark --embeddings-dir data/embeddings/minilm_claims --output-dir data/embeddings/minilm_claims/clustering_benchmark_25_30 --k-min 25 --k-max 30`
- rerun `build-ui`

## Module Layout

- `src/ohbm2026/graphql_api.py`
  - GraphQL access, env loading, batching, retries
- `src/ohbm2026/assets.py`
  - abstract ingest and figure asset download/refresh
- `src/ohbm2026/enrichment.py`
  - markdown conversion, figure analysis, claim extraction, enrichment assembly
- `src/ohbm2026/openalex.py`
  - reference parsing and OpenAlex matching
- `src/ohbm2026/neuroscape.py`
  - embeddings, stage-2 paths, semantic analysis, clustering, projections
- `src/ohbm2026/ui.py`
  - static UI export/build pipeline
- `src/ohbm2026/cli.py`
  - unified CLI entrypoint

## Main Outputs By Stage

- raw ingest
  - `data/abstracts.json`
  - `data/assets/`
- authors
  - `data/authors.json`
- figure analysis
  - `data/cache/figure_analysis/image_analyses_ollama__<state-key>.json`
  - `data/cache/figure_analysis/image_analyses_openai__<state-key>.json`
- claim extraction
  - `data/cache/claim_analysis/claim_analyses_cllm__<state-key>.json`
- enriched corpus
  - `data/abstracts_enriched.json`
- references
  - `data/reference_metadata.json`
- embeddings and clustering
  - `data/embeddings/*`
- static site
  - `data/outputs/exported-sites/ui-site__<state-key>/`
  - optional publish mirror at `export/ui-site/`

## Validation

Default validation command:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

If an agent is taking over this repo, this should be the first command after
setting up the environment.
