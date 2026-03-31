# Plan

## Rationale

The hard-clustering winner may not be the best representation for semantic
topic structure. This step compares graph communities on the focused trio using
the repo's existing semantic-analysis baselines, because fresh reruns on the
full corpus were disproportionately expensive relative to the decision value.

## Commands

Reference baselines used:

- `data/outputs/experiments/embeddings/voyage_stage2_published/semantic_analysis_15-communities`
- `data/outputs/experiments/embeddings/openai_stage1/semantic_analysis_min15`
- `data/outputs/experiments/embeddings/minilm_stage1/semantic_analysis_min15`

## Expected Outputs

- one graph-community comparison note for the three focused bundles
- modularity/resolution comparison
- qualitative rationale comparison against the hard-cluster reports
