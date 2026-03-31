# 2026-03-30 Topic Clustering Optimization

## Purpose

Run a staged topic-clustering optimization ladder that:

- refreshes hard clustering on the current migrated artifact layout
- compares graph-community structure on the focused embedding trio
- evaluates overlapping topic memberships with a soft-membership overlap model
- records rationale, tasks, results, and debugging notes for each step

## Experiment Order

1. `01-hard-clustering-refresh`
2. `02-graph-community-baseline`
3. `03-overlapping-nocd`

## Local Artifact Policy

- raw run outputs live under local-only `runs/`
- canonical embedding bundles stay under `data/outputs/experiments/embeddings/`
- new derived experiment outputs for this ladder live under local-only
  `data/outputs/experiments/topic_clustering_optimization/2026-03-30/`
- tracked markdown in this directory records what was tried and what was learned
- the active comparison set is:
  - `voyage_stage2_published`
  - `openai_stage1`
  - `minilm_stage1`
