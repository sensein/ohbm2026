# Experiment Guide

## Purpose

This directory holds recorded exploratory work that builds on the canonical
corpus and embedding artifacts. Experiments are evidence, not silent defaults.

Read the root
[CONSTITUTION.md](/Users/satra/software/temp/ohbm2026/CONSTITUTION.md) before
adding or rerunning anything here, especially the rules around fresh output
directories, `.venv`-scoped Python execution, and keeping secrets out of logs
or committed artifacts.

## Current Experiment Index

- [2026-03-30-topic-clustering-optimization/README.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-30-topic-clustering-optimization/README.md)
  - compares hard clustering, existing graph-community baselines, and soft overlapping memberships for `voyage_stage2_published`, `openai_stage1`, and `minilm_stage1`
- [2026-03-22-global-path-variant-sweep/README.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-22-global-path-variant-sweep/README.md)
  - compared global ordering variants and showed that plain diffusion methods
    did not beat the stronger hierarchical baselines
- [2026-03-22-mapalign-global-path-sweep/README.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-22-mapalign-global-path-sweep/README.md)
  - tested mapalign-style diffusion variants and found them clearly weaker than
    the OLO baseline
- [2026-03-22-advanced-global-path-methods/README.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-22-advanced-global-path-methods/README.md)
  - promoted the stronger global ordering family and currently points to
    `global_olo_two_opt_knn20` as the best recorded result
- [2026-03-23-voyage-stage2-3d-umap/README.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-23-voyage-stage2-3d-umap/README.md)
  - created the reusable rotating 3D UMAP view for the published Voyage stage-2
    space
- [2026-03-25-nocd-classic-predict/README.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-25-nocd-classic-predict/README.md)
  - established the portable structural predict-only NOCD baseline
- [2026-03-25-nocd-checkpoint-sweep/README.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-25-nocd-checkpoint-sweep/README.md)
  - expanded NOCD predict-only evaluation to the available portable checkpoint
    set and reinforced the value of checkpoint discovery over hard-coded names

## Current Practical Takeaways

- diffusion-based global ordering is not the leading approach in this repo
- `global_olo_two_opt_knn20` is the strongest recorded poster-sequencing result
  so far
- NOCD predict-only workflows should prefer portable structural checkpoints over
  fixed-feature `X` checkpoints
- experiment outputs should be compared, not overwritten

## Rules For New Experiments

- use a new dated experiment directory or a fresh run directory under an
  existing experiment
- if a workflow also writes machine-readable local outputs, put those under
  `data/outputs/experiments/` with a state-keyed directory name
- include a `README.md` that states the purpose, inputs, outputs, and repeat
  command
- keep recorded runs immutable
- run Python commands through `.venv/bin/python` or `uv` targeting `.venv`
- write the comparison artifacts needed to interpret the result later
- do not expose API keys or tokens in experiment notes, outputs, or logs
- do not silently replace active organizer-facing proposals with experiment
  outputs
