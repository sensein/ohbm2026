# Summary

The focused trio all preferred `kmeans`, but they separated differently:

| Embedding | Best `k` | Silhouette | Davies-Bouldin | Inter/Intra Ratio | Composite |
| --- | ---: | ---: | ---: | ---: | ---: |
| `minilm_stage1` | 34 | 0.0673 | 2.5406 | 1.1208 | 0.9053 |
| `voyage_stage2_published` | 32 | 0.0982 | 2.2632 | 1.3236 | 0.8869 |
| `openai_stage1` | 30 | 0.0639 | 2.7410 | 1.0631 | 0.8587 |

Interpretation:

- `minilm_stage1` won the composite score because its cluster-size balance and
  entropy stayed strong at a higher `k`
- `voyage_stage2_published` had the cleanest raw separation, with the best
  silhouette, the best Davies-Bouldin score, and the strongest
  intercluster/intracluster ratio
- `openai_stage1` remained viable, but it lagged the other two on both compact
  separation and composite score

Follow-on decision:

- carry all three into comparison tables
- treat `minilm_stage1` and `voyage_stage2_published` as the primary candidates
- keep `openai_stage1` as the contrast space

Explainable reports:

- [voyage_stage2_published_report.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-30-topic-clustering-optimization/01-hard-clustering-refresh/voyage_stage2_published_report.md)
- [openai_stage1_report.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-30-topic-clustering-optimization/01-hard-clustering-refresh/openai_stage1_report.md)
- [minilm_stage1_report.md](/Users/satra/software/temp/ohbm2026/experiments/2026-03-30-topic-clustering-optimization/01-hard-clustering-refresh/minilm_stage1_report.md)
