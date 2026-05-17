# OHBM 2026 Vision And Reproducibility Guide

## Why This Document Exists

This repository is no longer a single-purpose script bundle. It is now a
working system with two coupled but distinct missions:

1. build a reproducible local semantic corpus for OHBM 2026 accepted abstracts
2. use that corpus to support downstream review products such as the static UI,
   semantic analyses, and poster-layout experiments

Future readers should not have to reverse-engineer that intent from commit
history or scattered plan files. This document names the durable goals,
non-negotiable rules, current defaults, and the main decision points that shape
how work should be reproduced.

## Project Vision

The project aims to make the accepted OHBM 2026 abstract corpus locally
rebuildable, inspectable, and useful for both scientific browsing and organizer
decision support.

The repo is successful when a new person or agent can:

- reproduce the current canonical corpus artifacts from documented inputs
- understand which outputs are authoritative versus exploratory
- rerun experiments without overwriting prior evidence
- explain why the current semantic and layout defaults were chosen
- extend the pipeline without breaking auditability or resumability

## System Boundaries

There are two primary tracks in this repo.

### Track A: Canonical corpus pipeline

This is the durable backbone of the project. Its responsibility is to turn the
Oxford Abstracts source corpus into local, reproducible artifacts:

- `data/inputs/abstracts_graphql__<state-key>.json`
- `data/primary/abstracts.json`
- `data/inputs/assets/`
- `data/cache/figure_analysis/image_analyses_<backend>__<state-key>.json`
- `data/cache/claim_analysis/<cache-key>.json` (Stage 2.1; key = `sha256(manuscript || claims_model_id || eco_vocabulary_version)`)
- `data/outputs/experiments/title_audit/title_modifications.json`
- `data/primary/abstracts_enriched.json`
- `data/primary/reference_metadata.json`
- `data/outputs/experiments/embeddings/*`
- `data/outputs/experiments/*__<state-key>/`
- `data/outputs/exported-sites/ui-site__<state-key>/`
- `export/ui-site/`

The canonical operational interface for this track is `ohbmcli`.

### Track B: Exploratory layout and experiment workflows

This track uses the canonical corpus and embedding products to explore poster
sequencing, layout proposals, NOCD community detection, and related organizer
tooling.

**As of Stage 5 (specs/007-package-reorg/) this track is parked.** The
poster-layout / sequencing / NOCD source code moved to the parked
`src/ohbm2026/layout/` package; the 15 companion scripts moved to
`scripts/layout/`. Code is preserved verbatim for future revival —
expect to revive when a new organizer cycle needs poster work.

These workflows are intentionally more experimental. They are expected to
produce comparative evidence, not silent replacements for canonical outputs.
That is why they are concentrated under:

- `experiments/`
- `data/outputs/proposals/`
- `scripts/layout/` (parked as of Stage 5)

The strongest outputs from this track can later be promoted into organizer
defaults, but only after they are documented and auditable.

## Constitutional Commitments

The project constitution lives in
[CONSTITUTION.md](../CONSTITUTION.md). The
practical commitments future operators should internalize are:

- all Python execution must use the repository-local `.venv` via
  `.venv/bin/python` or `uv` targeting that interpreter, never system Python
- recorded experiment outputs are immutable and must go into fresh run
  directories
- `data/primary/abstracts.json` is the canonical normalized raw corpus and should not
  be silently rewritten to apply downstream cleanup decisions
- audit-style corrections belong in explicit derivative artifacts such as
  `data/outputs/experiments/title_audit/title_modifications.json`
- long-running API and LLM jobs should checkpoint incrementally and remain
  resumable
- `ohbmcli` is the canonical interface for the main pipeline
- organizer-facing review outputs must preserve machine-readable provenance
  alongside summaries and HTML views
- behavior-changing work should update the nearest plan or spec and define
  verification before implementation begins
- secrets must remain in `.env` or local environment variables and never be
  copied into committed files or logs
- when canonical defaults change, the docs must change with them

These commitments matter because the repo is simultaneously a data pipeline, an
analysis environment, and a decision-support system. Reproducibility here is
not just about code execution; it is also about preserving evidence and
explanations.

## Current Canonical Defaults

The defaults that future users should treat as current project reality are:

- raw accepted abstracts live in `data/primary/abstracts.json`
- the preferred figure-analysis path for the main corpus is OpenAI-backed, not
  the local Ollama route
- the main enriched corpus is the SQLite + zlib(json) store at
  `data/primary/abstracts_enriched.sqlite` (the Stage 2.1 canonical
  artifact; the legacy `abstracts_enriched.json` is archived)
- Stage 3 embeddings are per-component bundles under
  `data/outputs/embeddings/<model_key>/<component>__<state_key>/`
  for `voyage`, `minilm`, `openai`, `pubmedbert`, and the derived
  `neuroscape`. The state-key suffix lets historical corpora coexist;
  removing stale bundles is `rm -rf <model_key>/<component>__<old_state_key>`.
  Multi-component recipes (`stage1`, `methods-results`,
  `title-results-conclusion`, etc.) are composed at consumption time
  via `neuroscape.compose_recipe([...], model_key=<m>)` — no
  multi-component bundles are persisted in v1.
- the primary semantic embedding lens is the composed
  `title+introduction+methods+results+conclusion` recipe over the
  `voyage` per-component bundles, transformed by the published
  NeuroScape Stage-2 model
- the claims-focused UI lens is the `minilm/claims` per-component
  bundle directly (no composition needed; one component)
- run-level provenance for Stage 3 lives under `data/provenance/`
  alongside the per-bundle `provenance.json` files
- Stage 4 analysis & annotation produces per-(model, input, kind)
  bundles under `data/outputs/analysis/<model>_<input>/<kind>__<state-key>/`
  for four analysis kinds: `projections` (UMAP 2D+3D), `communities`
  (FAISS+Leiden+CPM), `neuroscape_clusters` (spherical-mean nearest-
  centroid in the published NeuroScape domain-embedding space; only
  runs for `model == "neuroscape"`), and `topic_clusters` (BERTopic-
  style UMAP + HDBSCAN). Every clustering bundle ships a per-cluster
  `topics.json` produced by a hybrid pipeline: spaCy phrase
  extraction + class-based TF-IDF locally, then an optional LLM
  grouping pass (opt-out via `--skip-llm-topics`) that re-ranks the
  shortlist into `{Keywords, Title, Description, Focus}` while
  enforcing `Keywords ⊆ candidate_phrases` to prevent hallucination.
- the canonical Stage 4 rollup the UI consumes is
  `data/outputs/analysis/annotations__<corpus-state-key>.{parquet,sqlite}`,
  carrying per-abstract UMAP coordinates + community / NeuroScape-
  cluster / topic-cluster ids for every model present, plus a joined
  `cluster_topics` table with the per-cluster keyword/title/description
  metadata.
- the final delivery artifact is the static site under `export/ui-site/`

The local pre-publish exported-site root now lives under
`data/outputs/exported-sites/ui-site__<state-key>/`.

Those defaults reflect current project choices, not abstract theory. If a later
change supersedes them, it should update this document, the README, and the
relevant experiment or workflow docs together.

## Reproduction Ladder

Reproduction in this repo should be thought of in layers.

### Level 1: Verify the current workspace

Useful when the data products already exist locally and you need confidence that
the code still matches the documented pipeline.

1. Create or refresh `.venv` with `uv`.
2. Run the test suite through `.venv/bin/python`.
3. Review `README.md` for the latest canonical step ordering.
4. Inspect `memory/summary.md` and the relevant experiment README before
   changing defaults.

### Level 2: Rebuild the canonical derived products from local raw data

Useful when `data/primary/abstracts.json` already exists and the goal is to rebuild
enrichment, references, embeddings, clusters, or the UI.

The usual order is:

1. `ohbmcli refresh-assets`
2. `ohbmcli enrich-abstracts` — single Stage 2 entry (replaces the
   former `analyze-figures` / `extract-claims` / `enrich` /
   `reference-metadata` quartet). Writes the SQLite + zlib enriched
   corpus at `data/primary/abstracts_enriched.sqlite` plus
   per-component caches under `data/cache/figure_analysis/`,
   `data/cache/claim_analysis/`, `data/cache/reference_metadata/`,
   plus `data/provenance/abstracts_enrich_provenance__<state-key>.json`.
   Use `--invalidate <component>` to force a single component to
   re-run; pass `--export-parquet PATH` (with the `parquet` optional
   extra installed) to emit a Parquet copy.
3. `ohbmcli title-audit`
4. embedding commands such as `embed-minilm`, `embed-voyage`, or
   `apply-published-stage2`
5. `ohbmcli cluster-benchmark` and related semantic-analysis steps
6. `ohbmcli build-ui`

### Level 3: Rebuild from the upstream abstract source

Useful when a new operator needs to replay the pipeline from the Oxford
Abstracts API.

1. configure `.env`
2. run `ohbmcli fetch-abstracts` (accepted corpus; replaces the
   former `ohbmcli ingest`) — writes `data/primary/abstracts.json`
   plus the persisted GraphQL schema introspection at
   `data/inputs/abstracts_graphql_schema__<state-key>.json` and a
   machine-readable provenance record at
   `data/provenance/abstracts_fetch_provenance__<state-key>.json`. The
   stage is resumable from per-record checkpoint and detects
   upstream schema drift (HARD / SOFT / INFORMATIONAL tiers).
3. optionally run `ohbmcli fetch-withdrawn` to fetch the SEPARATE
   withdrawn-decision corpus into
   `data/primary/abstracts_withdrawn.json` (never co-mingled with
   the accepted corpus).
4. continue with the Level 2 steps

This repo is designed so that upstream access is only required for a subset of
the work. Once `data/primary/abstracts.json` exists, much of the pipeline can be
repeated locally.

The per-stage script pattern that Stage 1 now establishes — six
contracts (input, output, provenance, error, resumability, discovery)
documented in [per-stage-pattern.md](per-stage-pattern.md) — is the
template subsequent stages (figure analysis, enrichment, references,
embeddings, clustering, UI build) will follow as they get cleaned up
in their own per-stage `/speckit-specify` rounds.

## Key Decision Points

### 1. Preserve the raw corpus and express cleanup as derivative artifacts

The project keeps raw normalization and downstream cleanup separate. Title
cleanup now writes `data/outputs/experiments/title_audit/title_modifications.json` instead of altering the raw
record silently. This is the right choice for traceability and future audit.

### 2. Break the pipeline into resumable task-oriented commands

The move from monolithic enrichment toward task commands was a foundational
decision. It made the project easier to resume, test, and explain, and it
turned `ohbmcli` into the shared operating surface.

### 3. Prefer OpenAI figure analysis for the canonical enriched corpus

Local Ollama support remains useful, but the repo’s current default path for the
main enriched dataset is the OpenAI-backed figure-analysis cache. That choice
was reinforced by batching, incremental writes, and downstream integration into
the enriched corpus and UI.

### 4. Keep reference resolution staged and evidence-preserving

Reference matching is intentionally not a single opaque LLM step. The project
uses structured splitting, lexical validation, DOI and PMID matching, OpenAlex
title lookup, and more limited fallback discovery. This is a deliberate balance
between automation and auditability.

### 5. Treat `voyage_stage2_published` as the primary semantic backbone

The project has multiple embedding families, but current decisions point to the
published NeuroScape stage-2 model applied to Voyage embeddings as the strongest
general semantic reference space. It anchors the main benchmarked cluster lens
and a large portion of the downstream semantic work.

### 6. Keep claims as a separate semantic lens rather than merging them into the main one

Claim extraction and claim-only embeddings are treated as an additional
interpretive layer, not as a replacement for the section-based semantic corpus.
That is why `claims_28` is a separate UI lens and not the only cluster system.

### 7. Make the UI static and rebuildable

The static UI is a strategic choice. It keeps deployment simple, preserves local
reproducibility, and allows search, facets, cluster views, and semantic search
to be built from exported artifacts rather than a live backend.

### 8. Keep poster-layout work auditable and experimental

Poster-layout proposals are valuable, but they are not raw truth. The repo
rightly treats them as auditable outputs with proposal bundles, review pages,
metrics, and experiment directories rather than as invisible code-side state.

## Experiment Summary

The experiments so far point to a few durable conclusions.

### Corpus and semantic infrastructure

- the project matured from raw ingest into a checkpointed semantic pipeline with
  figure analysis, claim extraction, reference enrichment, embeddings, and a
  static UI
- the benchmarked semantic backbone is currently stronger in the published
  Voyage stage-2 space than in the default MiniLM stage-1 space
- claims-only embeddings support a useful secondary cluster lens at organizer-
  and reader-relevant granularity

### Poster sequencing and layout

- the original greedy semantic-path ordering was useful but left many weak local
  neighborhoods
- global-path experiments showed that plain diffusion variants did not beat the
  strongest hierarchical or refinement-based baselines
- the current best recorded global ordering result is `global_olo_two_opt_knn20`
  from the advanced global-path experiments
- mapalign-style diffusion variants underperformed badly relative to the OLO
  baseline and should not be treated as the leading path today

### Visualization

- the 3D Voyage stage-2 UMAP experiment established a reusable visualization
  pattern for rotating cluster-aware inspection
- the static UI accumulated several durable interaction choices around sticky
  detail panels, collapsible sections, and manifest-driven semantic layers

### NOCD experiments

- the NOCD work established a predict-only, checkpoint-discovery-driven workflow
- portable structural checkpoints transfer more cleanly than fixed-feature `X`
  checkpoints
- the strongest observed transferable result in the memory summary was
  `nocd_gcn_structural_mag_med_pretrained` on `voyage_stage2_published`

## What A Future Reader Should Check Before Making Changes

Before changing defaults or starting a new experiment, inspect:

1. `README.md` for the current operational runbook
2. `CONSTITUTION.md` for the project’s non-negotiables
3. `memory/summary.md` for the condensed project history
4. the closest plan document under `docs/`
5. the closest experiment `README.md` under `experiments/`

If your change affects canonical outputs, also ask:

- does this alter a default model, input path, or output path?
- does this create a new authoritative artifact or only an experiment?
- does it preserve resume behavior and auditability?
- did you update the docs that a future operator would rely on?

## Practical Guidance For Future Operators

- prefer `ohbmcli` when working on the canonical pipeline
- use `.venv/bin/python` or `uv` targeting `.venv` for every Python command
- treat `scripts/` as focused workflow entrypoints, especially for experiments
  and organizer tooling
- keep experiment runs fresh and non-destructive
- keep secrets out of committed files, docs, and logs
- assume `memory/` is context, not canon
- when in doubt, optimize for traceability over convenience

That tradeoff is what has made the repo understandable despite its growing
scope.
