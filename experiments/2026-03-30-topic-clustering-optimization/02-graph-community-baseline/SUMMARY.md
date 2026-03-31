# Summary

Existing graph-community baselines for the focused trio gave this modularity
ordering:

| Embedding | Baseline | Best Modularity | Resolution Context |
| --- | --- | ---: | ---: |
| `voyage_stage2_published` | `semantic_analysis_15-communities` | 0.3958 | 2.50 |
| `openai_stage1` | `semantic_analysis_min15` | 0.3289 | 1.75 |
| `minilm_stage1` | `semantic_analysis_min15` | 0.3248 | 1.55 |

Interpretation:

- `voyage_stage2_published` remains the strongest graph-community space by a
  clear margin
- `minilm_stage1` is still a strong overall candidate because it won the hard
  clustering composite score
- `openai_stage1` remains the useful contrast, but not the leading graph
  baseline

Follow-on decision:

- use `voyage_stage2_published` as the primary overlap candidate
- use `minilm_stage1` as the strongest hard-cluster counterpoint
- keep `openai_stage1` in the overlap run so we can see whether higher overlap
  rates compensate for weaker hard-cluster separation
