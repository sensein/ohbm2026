# OHBM 2026 Combined Plan

## Goal

Build a complete local OHBM 2026 abstract processing pipeline that:

1. fetches accepted abstracts from the Oxford Abstracts GraphQL API,
2. stores them as a local JSON database,
3. downloads and links only methods/results figure assets,
4. enriches abstracts with author metadata and markdown sections,
5. analyzes figures locally with Ollama + Qwen,
6. produces local embedding spaces and relationship indexes,
7. keeps a path open for NeuroScape-compatible retraining and evaluation.

This is the operational planning document for the repository.

## Data Products

- `data/abstracts.json`
  - canonical raw abstract database
  - includes fetch metadata, normalized responses, figure URLs, and local asset links
- `data/assets/`
  - local methods/results figure assets only
- `data/authors.json`
  - normalized author metadata keyed by author ID
- `data/abstracts_enriched.json`
  - enriched abstracts with markdown sections, author resolution, figure analyses, and embedding text
- `data/image_analyses.json`
  - cached multimodal figure analysis output
- `data/embeddings/minilm_stage1/`
  - local MiniLM embeddings and neighbors
- `data/embeddings/neuroscape_stage2_manifest.json`
  - retraining/compatibility handoff for NeuroScape work

## Architecture

- `src/ohbm2026/graphql_api.py`
  - GraphQL requests, batching, retries, env loading, author/submission fetches
- `src/ohbm2026/assets.py`
  - local asset indexing, figure URL extraction, reuse-aware downloads, JSON-only asset refresh, and ingest CLI
- `src/ohbm2026/enrichment.py`
  - author export, HTML-to-markdown conversion, section mapping, local Qwen figure analysis, enriched abstract assembly, and phase-2 CLI
- `src/ohbm2026/neuroscape.py`
  - stage-one embeddings, similarity graph generation, NeuroScape handoff manifest
- `src/ohbm2026/cli.py`
  - unified `ohbmcli` command

## Unified CLI

- `ohbmcli ingest`
  - fetch abstracts and figure assets from the API
- `ohbmcli refresh-assets`
  - rebuild `local_assets` from the local JSON database without rerunning abstract extraction
- `ohbmcli phase2`
  - run author export, enrichment, figure analysis, and embedding stages

## Execution Order

1. Ingest accepted abstracts and figure assets.
2. Refresh/prune local assets from the JSON database when needed.
3. Export deduplicated author metadata.
4. Convert abstract responses to ordered markdown sections.
5. Build enriched abstracts with resolved authors and canonical embedding text.
6. Run local Qwen multimodal analysis on linked figures.
7. Merge figure-derived keywords back into enriched abstracts.
8. Generate local stage-one embeddings with `all-MiniLM-L6-v2`.
9. Compute nearest-neighbor relationships for local exploration.
10. Prepare a retraining handoff for NeuroScape stage-two work.

## Workstreams

### Workstream A: Raw Ingest

Goal:
Create the canonical raw abstract database from the Oxford Abstracts API.

Required fields per abstract:

- `id`
- `title`
- `accepted_for`
- `authors`
- `responses`
- `external_urls`
- `figure_urls`
- `local_assets`

Required fields per local asset:

- `source_url`
- `source_question_name`
- `local_path`
- `content_type`
- `downloaded`
- `error`

Checks:

- [x] Load `OHBM2026_API` from `.env`.
- [x] Query event IDs and accepted submission IDs.
- [x] Fetch abstract content in batches.
- [x] Normalize raw GraphQL payloads into stable JSON.
- [x] Persist `data/abstracts.json`.

### Workstream B: Figure Assets

Goal:
Keep local figure handling restricted, resumable, and reuse-first.

Rules:

- only methods/results figure questions should generate `local_assets`
- only image URLs should be downloaded
- reuse local files whenever the abstract ID plus URL hash already exists
- do not rerun abstract extraction for maintenance-style refreshes

Checks:

- [x] Restrict figure handling to methods/results figure questions.
- [x] Skip non-image URLs and non-image content types.
- [x] Reuse existing files before any network download.
- [x] Add a JSON-only refresh path.
- [x] Keep missing downloads explicit in the database.

### Workstream C: Author Metadata

Goal:
Create a de-duplicated author database and resolve author IDs in enriched abstracts.

Checks:

- [x] Extract the unique author ID set from the raw corpus.
- [x] Fetch author details in batches.
- [x] Normalize and persist `data/authors.json`.
- [x] Add `authors_resolved` to enriched abstracts.

### Workstream D: Ordered Markdown Abstracts

Goal:
Turn question/response pairs into a stable, readable abstract representation.

Canonical section order:

1. Title
2. Introduction
3. Methods
4. Results
5. Discussion
6. Conclusion
7. References/Citations
8. Acknowledgement
9. Other unmapped responses

Checks:

- [x] Create a question-name to section mapping.
- [x] Convert HTML into markdown while preserving lists, emphasis, links, and superscripts where possible.
- [x] Store `sections_markdown`.
- [x] Store `abstract_markdown`.
- [x] Store `unmapped_responses_markdown`.
- [x] Preserve raw responses for traceability.

### Workstream E: Figure Understanding

Goal:
Analyze each linked local figure and generate reusable semantic metadata.

Expected outputs per analyzed image:

- caption guess
- OCR text
- rich markdown description
- figure keywords
- notes/confidence

Checks:

- [x] Use cache-first image analysis storage in `data/image_analyses.json`.
- [x] Default to local Ollama model `qwen3.5:35b`.
- [x] Check model availability before pulling.
- [ ] Complete a full cached figure-analysis sweep across all linked figures.
- [ ] Merge the full figure-analysis output back into the enriched abstract corpus.

### Workstream F: Embeddings and Relationships

Goal:
Create a local semantic search space and retain a path toward NeuroScape stage-two retraining.

Checks:

- [x] Build canonical `embedding_text` from title, ordered sections, and keywords.
- [x] Generate local stage-one embeddings with `all-MiniLM-L6-v2`.
- [x] Persist vectors and metadata to `data/embeddings/minilm_stage1/`.
- [x] Build nearest-neighbor relationships.
- [x] Write a NeuroScape stage-two handoff manifest.
- [ ] Validate the PR-based NeuroScape retraining path and required artifacts.

## Detailed Checklist

- [x] Create a `uv`-managed Python project scaffold.
- [x] Add GraphQL client helpers for abstract and author retrieval.
- [x] Normalize accepted abstracts into a local JSON database.
- [x] Restrict figure handling to methods/results figure questions.
- [x] Reuse local assets whenever possible and only download when necessary.
- [x] Add a JSON-only asset refresh path.
- [x] Export author metadata to `data/authors.json`.
- [x] Convert HTML response bodies into markdown.
- [x] Build ordered section markdown and `abstract_markdown`.
- [x] Create a local MiniLM embedding pipeline and neighbor database.
- [x] Split the codebase into API, asset, enrichment, and embedding modules.
- [x] Add a unified `ohbmcli` entrypoint.
- [ ] Complete a full cached figure-analysis sweep with local `qwen3.5:35b`.
- [ ] Validate the NeuroScape retraining path against the PR-based workflow and artifact requirements.

## Verification Targets

- Confirm the script can read `OHBM2026_API`.
- Confirm the GraphQL API returns event IDs and abstract IDs.
- Confirm normalized abstract payloads preserve author order and response content.
- Confirm only methods/results figure URLs populate `local_assets`.
- Confirm refresh operations can rebuild `local_assets` from the existing JSON database.
- Confirm markdown conversion preserves section order and list formatting.
- Confirm the local embedding bundle and neighbor graph have one entry per abstract.
- Confirm figure analysis remains resumable and cache-first.

## NeuroScape Direction

- Treat the local `all-MiniLM-L6-v2` embedding space as the executed stage-one local baseline.
- Treat NeuroScape stage-two as a separate retraining/validation track rather than a direct reuse of the published Voyage-based projection.
- Keep the PR-based retraining path as the next implementation target once the repository workflow is validated locally.

## Operational Notes

- Figure analysis should remain cache-first and resumable.
- Scripts should check for a required local Ollama model before pulling anything.
- Asset logic should continue to prefer local reuse over redownloads.
- The local JSON databases remain the source of truth for refresh-style maintenance tasks.
