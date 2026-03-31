# Summary

The soft-overlap experiment used the best hard-cluster count for each bundle and
then assigned top-2 memberships when the secondary posterior was at least
`0.20`.

| Embedding | Communities | Multi-membership Fraction | Mean Primary Prob. | Mean Secondary Prob. | Mean Entropy |
| --- | ---: | ---: | ---: | ---: | ---: |
| `openai_stage1` | 30 | 0.0753 | 0.9478 | 0.3270 | 0.0436 |
| `minilm_stage1` | 34 | 0.0654 | 0.9560 | 0.3211 | 0.0356 |
| `voyage_stage2_published` | 32 | 0.0594 | 0.9636 | 0.3338 | 0.0284 |

Interpretation:

- `openai_stage1` produced the highest overlap rate, but also the lowest mean
  primary-cluster confidence and the highest assignment entropy
- `voyage_stage2_published` produced the cleanest overlap assignments, with the
  highest primary confidence and the lowest entropy, but fewer bridge cases
- `minilm_stage1` landed in the middle and remained the best balanced choice
  when combined with its Experiment 01 hard-clustering win

Decision:

- `minilm_stage1` is the best all-around optimization target for topic
  clustering in this pass
- `voyage_stage2_published` remains the best choice when we want the cleanest
  partitions and graph communities
- `openai_stage1` is most useful when we explicitly want more bridge abstracts
  surfaced, but it is not the strongest default taxonomy space

Explainable reports:

- [voyage_stage2_published_overlap_report.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-30-topic-clustering-optimization/03-overlapping-nocd/voyage_stage2_published_overlap_report.md)
- [openai_stage1_overlap_report.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-30-topic-clustering-optimization/03-overlapping-nocd/openai_stage1_overlap_report.md)
- [minilm_stage1_overlap_report.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-30-topic-clustering-optimization/03-overlapping-nocd/minilm_stage1_overlap_report.md)
