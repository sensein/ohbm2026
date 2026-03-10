# OHBM 2026 Abstract Pipeline

This project builds a local OHBM 2026 abstract corpus from the Oxford
Abstracts GraphQL API, keeps only methods/results figure assets, enriches the
abstracts into ordered markdown, runs local multimodal figure analysis, and
produces local embedding bundles.

## External Requirements

Required programs:

- `python` 3.11+
- `uv`

Required for figure analysis:

- `ollama`
- local Ollama model `qwen3.5:35b`

Optional for embedding generation:

- Python package `sentence-transformers` for local MiniLM embeddings
- Voyage API access if you want to run the Voyage embedding path

## Token Requirements

Environment variables are read from `.env`. A safe template is provided in
[.env.sample](/Users/satra/software/temp/ohbm2026/.env.sample).

- `OHBM2026_API`
  - required for abstract ingest and author metadata fetches from Oxford Abstracts
- `VOYAGE_API`
  - optional, only required if running phase 2 without `--skip-voyage`

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

For local figure analysis, confirm Ollama can see the required model:

```bash
ollama list
```

## Unified CLI

The main entrypoint is `ohbmcli`.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli ingest
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli refresh-assets --reuse-existing-assets-only
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli phase2 --skip-voyage
```

Subcommands:

- `ingest`
  - fetch abstracts and methods/results figures from Oxford Abstracts
- `refresh-assets`
  - rebuild `local_assets` from `data/abstracts.json` without rerunning abstract extraction
- `phase2`
  - export authors, build markdown sections, run local figure analysis, and generate embeddings

## Module Layout

- `src/ohbm2026/graphql_api.py`
  - GraphQL access, retries, batching, and API-key loading
- `src/ohbm2026/assets.py`
  - figure URL extraction, reuse-aware downloads, and JSON-driven asset refresh
- `src/ohbm2026/enrichment.py`
  - author resolution, HTML-to-markdown conversion, figure analysis, and enrichment assembly
- `src/ohbm2026/neuroscape.py`
  - local embedding generation, neighbor computation, and NeuroScape handoff metadata
- `src/ohbm2026/cli.py`
  - unified CLI entrypoint

## Key Outputs

- `data/abstracts.json`
- `data/assets/`
- `data/authors.json`
- `data/abstracts_enriched.json`
- `data/image_analyses.json`
- `data/embeddings/minilm_stage1/`
- `data/embeddings/neuroscape_stage2_manifest.json`
