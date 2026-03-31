# Plan

## Rationale

We need a current hard-clustering baseline on the migrated artifact tree before
we optimize overlapping communities. This step picks the strongest candidate
embedding spaces for the follow-on graph and overlap experiments.

## Commands

```bash
.venv/bin/python -m ohbm2026.cli cluster-benchmark \
  --embeddings-dir data/outputs/experiments/embeddings/voyage_stage2_published \
  --output-dir data/outputs/experiments/topic_clustering_optimization/2026-03-30/01-hard-clustering/voyage_stage2_published \
  --k-min 18 --k-max 34

.venv/bin/python -m ohbm2026.cli cluster-benchmark \
  --embeddings-dir data/outputs/experiments/embeddings/openai_stage1 \
  --output-dir data/outputs/experiments/topic_clustering_optimization/2026-03-30/01-hard-clustering/openai_stage1 \
  --k-min 18 --k-max 34

.venv/bin/python -m ohbm2026.cli cluster-benchmark \
  --embeddings-dir data/outputs/experiments/embeddings/minilm_stage1 \
  --output-dir data/outputs/experiments/topic_clustering_optimization/2026-03-30/01-hard-clustering/minilm_stage1 \
  --k-min 18 --k-max 34
```

## Expected Outputs

- one benchmark directory per embedding bundle
- benchmark JSON plus best-run assignments and cluster summaries
- rationale markdown generated from the best run for the selected follow-on
  embedding bundles
