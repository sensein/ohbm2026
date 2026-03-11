# OHBM 2026 Abstract Pipeline

This project builds a local OHBM 2026 abstract corpus from the Oxford
Abstracts GraphQL API, keeps only methods/results figure assets, enriches the
abstracts into ordered markdown, runs local multimodal figure analysis, and
produces local embedding bundles plus a semantic graph and cluster analysis.

## External Requirements

Required programs:

- `python` 3.11+
- `uv`

Required for figure analysis:

- `ollama`
- local Ollama model `qwen3.5:35b`

Optional for embedding generation:

- Python package `sentence-transformers` for local MiniLM embeddings
- Python packages `plotly` and `umap-learn` for local 2D embedding visualization
- Hugging Face access if you want to download additional sentence-transformer models
- OpenAI API access if you want to run the OpenAI embedding path
- Voyage API access if you want to run the Voyage embedding path

Optional for alternate hosted figure analysis:

- OpenAI API access if you want to run the hosted multimodal figure-analysis path instead of local Ollama

## Token Requirements

Environment variables are read from `.env`. A safe template is provided in
[.env.sample](/Users/satra/software/temp/ohbm2026/.env.sample).

- `OHBM2026_API`
  - required for abstract ingest and author metadata fetches from Oxford Abstracts
- `VOYAGE_API`
  - optional, only required if running `embed-voyage`
- `OPENALEX_API`
  - optional, used for authenticated OpenAlex reference enrichment
- `HF_TOKEN`
  - optional, used for authenticated Hugging Face model downloads
- `OPENAI_API_KEY`
  - optional, required if running `embed-openai` or `analyze-figures --vision-backend openai`

No API token is required for local Ollama usage.

## Setup

```bash
UV_CACHE_DIR=.uv-cache uv venv --python /opt/homebrew/bin/python3 .venv
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The GraphQL ingest reads `OHBM2026_API` from `.env`. The request timeout uses
an exponential schedule that starts at `100ms` and caps at `10s`.

For local MiniLM embeddings, install:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python sentence-transformers
```

For the interactive 2D UMAP visualization, install:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python plotly umap-learn
```

For local figure analysis, confirm Ollama can see the required model:

```bash
ollama list
```

## Unified CLI

The main entrypoint is `ohbmcli`.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli ingest
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli refresh-assets --reuse-existing-assets-only
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli authors
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-figures --vision-max-images 10
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-figures --vision-backend openai --image-analyses-output data/image_analyses_openai.json --enriched-output data/abstracts_enriched_openai.json
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-minilm
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-hf --model neuml/pubmedbert-base-embeddings
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-openai
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli semantic-analysis
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli umap-plot
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli export-ui
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli write-manifest
```

Subcommands:

- `ingest`
  - fetch abstracts and methods/results figures from Oxford Abstracts
- `refresh-assets`
  - rebuild `local_assets` from `data/abstracts.json` without rerunning abstract extraction
- `authors`
  - export author metadata from the local abstract database
- `enrich`
  - build `data/abstracts_enriched.json` from abstracts and any cached image analyses
- `analyze-figures`
  - analyze local figure files with either local Ollama or hosted OpenAI vision and update an image-analysis cache incrementally
- `embed-minilm`
  - generate local MiniLM embeddings and nearest neighbors
- `embed-hf`
  - generate embeddings from an arbitrary Hugging Face sentence-transformer model
- `embed-voyage`
  - generate Voyage embeddings and nearest neighbors
- `embed-openai`
  - generate OpenAI embeddings and nearest neighbors
- `semantic-analysis`
  - build a semantic similarity graph, community assignments, and cluster summaries from a local embedding bundle
- `umap-plot`
  - project a local embedding bundle to 2D UMAP and write an interactive Plotly HTML with hover metadata
- `export-ui`
  - build the static JSON data bundle for the standalone abstract search UI
- `build-ui`
  - copy the standalone UI assets and write a deployable static-site bundle
- `write-manifest`
  - write the NeuroScape handoff manifest

Embedding text is generated on demand from the enriched abstract content and is
not stored in `data/abstracts_enriched.json`. By default, the embedding
commands use:

- `title`
- `introduction`
- `methods`
- `results`
- `conclusion`

You can override that at runtime, for example:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-minilm --fields title methods results
```

## Module Layout

- `src/ohbm2026/graphql_api.py`
  - GraphQL access, retries, batching, and API-key loading
- `src/ohbm2026/assets.py`
  - figure URL extraction, reuse-aware downloads, and JSON-driven asset refresh
- `src/ohbm2026/enrichment.py`
  - author resolution, HTML-to-markdown conversion, figure analysis, and enrichment assembly
- `src/ohbm2026/neuroscape.py`
  - local embedding generation, semantic graph analysis, and NeuroScape handoff metadata
- `src/ohbm2026/ui.py`
  - static UI export/build pipeline for client-side search, facets, and relations
- `src/ohbm2026/cli.py`
  - unified CLI entrypoint

## Key Outputs

- `data/abstracts.json`
- `data/assets/`
- `data/authors.json`
- `data/abstracts_enriched.json`
- `data/image_analyses.json`
- `data/image_analyses_openai.json`
- `data/embeddings/minilm_stage1/`
- `data/embeddings/minilm_stage1/semantic_analysis/`
- `export/ui-site/`
- `data/embeddings/neuroscape_stage2_manifest.json`
