# Documentation Guide

## Start Here

If you are new to the repository, read these first:

1. [reproducibility-vision.md](reproducibility-vision.md)
2. [README.md](../README.md)
3. [CONSTITUTION.md](../CONSTITUTION.md)
4. [memory/summary.md](../memory/summary.md)

The vision document explains what the repo is for. The README explains how to
run the current canonical pipeline. The constitution explains what should not be
broken while changing it, including `.venv`-only Python execution,
plan-first/test-driven delivery, auditability, and secret hygiene.

Treat [reproducibility-vision.md](reproducibility-vision.md)
as the project charter and source of truth for the repo's scope, defaults, and
reproducibility model. Treat [README.md](../README.md)
as the operational runbook.

Current artifact contract to keep in mind while reading older docs:

- `data/inputs/` holds fetched GraphQL source snapshots
- `data/cache/` holds resumable caches and checkpoints
- `data/outputs/experiments/`, `data/outputs/exported-sites/`, and
  `data/outputs/proposals/` hold local derived outputs
- `export/` is only for publish mirrors, not the primary local output root

## Planning Documents By Topic

### Core pipeline and reproducibility

- [ohbm26-plan.md](ohbm26-plan.md)
  - original combined pipeline plan
- [title-reference-cleanup-plan.md](title-reference-cleanup-plan.md)
  - title normalization and reference-resolution changes
- [cllm-claims-plan.md](cllm-claims-plan.md)
  - claim extraction workflow and UI exposure
- [clustering-analysis-plan.md](clustering-analysis-plan.md)
  - unsupervised clustering benchmark
- [static-ui-plan.md](static-ui-plan.md)
  - static search UI goals and data contract

### Semantic category and analysis work

- [claims-semantic-clustering-plan.md](claims-semantic-clustering-plan.md)
  - claim-only embedding and clustering track
- [semantic-category-evaluation-plan.md](semantic-category-evaluation-plan.md)
  - compare learned semantic taxonomies with submitter categories
- [topic-clustering-landscape-2026-03-30.md](topic-clustering-landscape-2026-03-30.md)
  - recent literature scan on explainable, overlapping, and scientific-document topic clustering
- [poster-semantic-category-experiments-plan.md](poster-semantic-category-experiments-plan.md)
  - poster-facing semantic-category experiments

### Poster layout and sequencing work

- [poster-layout-optimizer-plan.md](poster-layout-optimizer-plan.md)
  - optimizer goals, outputs, and metrics
- [poster-sequencing-benchmark-plan.md](poster-sequencing-benchmark-plan.md)
  - stronger 1D ordering methods for poster numbering

## Review And Debt Tracking

- [repo-review-2026-03-28.md](repo-review-2026-03-28.md)
  - software-engineering and technical-management inspection of the current repo

## How To Use These Docs

- treat `README.md` as the current operational runbook
- treat plan docs as design history plus intent
- treat experiment READMEs under `experiments/` as the source of truth for a
  recorded experiment’s scope and rerun instructions
- when a doc conflicts with current code behavior, fix the doc or the code in
  the same change rather than letting the mismatch persist
