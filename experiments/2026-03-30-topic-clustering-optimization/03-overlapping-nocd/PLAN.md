# Plan

## Rationale

This step evaluates overlapping topic structure on the focused trio. The goal
is to see whether bridge abstracts and multi-topic structure are more
interpretable than a forced partition.

## Commands

The local `nocd` checkout did not include the model code needed for prediction,
so the overlap step was implemented with `GaussianMixture` posteriors instead of
NOCD. The working commands are:

```bash
.venv/bin/python scripts/run_gmm_overlap_experiment.py \
  --embeddings-dir data/outputs/experiments/embeddings/voyage_stage2_published \
  --benchmark-json data/outputs/experiments/topic_clustering_optimization/2026-03-30/01-hard-clustering/voyage_stage2_published/benchmark.json \
  --output-root experiments/2026-03-30-topic-clustering-optimization/runs/03-overlapping-nocd/gmm_voyage_stage2_published

.venv/bin/python scripts/run_gmm_overlap_experiment.py \
  --embeddings-dir data/outputs/experiments/embeddings/openai_stage1 \
  --benchmark-json data/outputs/experiments/topic_clustering_optimization/2026-03-30/01-hard-clustering/openai_stage1/benchmark.json \
  --output-root experiments/2026-03-30-topic-clustering-optimization/runs/03-overlapping-nocd/gmm_openai_stage1

.venv/bin/python scripts/run_gmm_overlap_experiment.py \
  --embeddings-dir data/outputs/experiments/embeddings/minilm_stage1 \
  --benchmark-json data/outputs/experiments/topic_clustering_optimization/2026-03-30/01-hard-clustering/minilm_stage1/benchmark.json \
  --output-root experiments/2026-03-30-topic-clustering-optimization/runs/03-overlapping-nocd/gmm_minilm_stage1
```

## Expected Outputs

- GMM-overlap run directories with `communities.json`, `memberships.json`, and
  overlap metrics
- explainable community rationale reports for each bundle
