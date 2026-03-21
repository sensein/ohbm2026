# Semantic Category Evaluation Plan

## Goal

Evaluate whether embedding-derived semantic categories provide a more modular and layout-useful organization of the accepted OHBM 2026 abstracts than the submitter-selected primary parent/subcategory labels.

The immediate objective is not to replace the current category system blindly. It is to produce evidence about:

- which embedding spaces best support modular semantic grouping
- which clustering approaches produce usable category systems
- whether those learned categories outperform submitter categories on neighborhood, coherence, and poster-layout utility metrics

## Core Question

Can we derive a conference-facing category system that is:

- semantically coherent in embedding space
- modular rather than overly fragmented or dominated by one giant cluster
- interpretable enough for organizers and attendees
- useful for poster numbering and session/block distribution
- meaningfully better than submitter-selected primary categories on those dimensions

## Target Granularity Bands

We should not assume there is one globally correct number of semantic categories. Instead, we should compare candidate systems across practical granularity bands:

- coarse: `10-15` categories
  - plausible for signage or high-level organizer overviews
- mid-grain: `20-30` categories
  - likely the main sweet spot for semantic layout and poster discovery
- fine: `31-40` categories
  - useful if the corpus supports more detailed semantic neighborhoods without becoming too fragmented

Current evidence suggests the strongest embedding-native candidates are likely to land in the `20-35` range rather than in a very small number of broad groups.

## Candidate Embedding Families

Full-corpus candidates already available locally (`3333` abstracts each):

- `data/embeddings/voyage_stage2_published`
- `data/embeddings/neuroscape_stage2_local`
- `data/embeddings/minilm_claims`
- `data/embeddings/minilm_stage1`
- `data/embeddings/pubmedbert_stage1`
- `data/embeddings/openai_stage1`
- `data/embeddings/voyage_stage1`

Recommended first-pass focus:

- `voyage_stage2_published`
  - strongest current unsupervised benchmarked abstract-section space
- `minilm_claims`
  - strongest claim-driven space and most directly content-centered
- `minilm_stage1`
  - useful baseline because it is already wired into the UI and prior analyses
- `pubmedbert_stage1`
  - important domain-specific comparison against general embedding models

Second-pass candidates:

- `openai_stage1`
- `voyage_stage1`
- `neuroscape_stage2_local`

## Experiment Families

### 1. Partition-Based Clustering Sweep

For each embedding family:

- run the existing clustering benchmark over a common `k` range
- compare methods:
  - `kmeans`
  - `agglomerative-ward`
  - `agglomerative-average`
  - `gaussian-mixture`
  - `birch`
- retain best-run assignments and cluster summaries

Purpose:

- identify which embedding families naturally support clean partitions
- establish candidate semantic taxonomies without using submitter labels

### 2. Graph Community Detection Sweep

For each embedding family:

- run the existing semantic graph/community analysis
- compare the resulting community counts and modularity
- treat graph communities as an alternative category system to centroid-based clusters

Purpose:

- test whether the information space is better represented as communities than as fixed-`k` partitions

Recommended graph methods:

- Leiden or Louvain modularity optimization on a kNN graph
- resolution sweeps targeting practical category counts such as `15-30`
- optional label propagation or Infomap later if they are straightforward to support locally

### 3. Embedding-Native Factorization and Soft Grouping

These methods are useful because they can produce parts-based or overlapping structure rather than only hard centroid-style partitions.

Recommended first pass:

- semi-NMF or kernel-NMF style factorization derived from the embedding space
- nonnegative matrix factorization on an embedding-derived affinity or similarity matrix
- optional soft cluster membership models if they can still be evaluated against layout constraints

Important note:

- plain NMF is not a natural fit for the current signed dense embedding vectors because they contain negative values
- for this project, we should prioritize embedding-native formulations rather than pivoting to a separate TF-IDF-first workflow

Purpose:

- test whether a parts-based semantic taxonomy can be recovered directly from the embedding geometry

### 4. Density- and Manifold-Aware Grouping

Recommended candidates:

- HDBSCAN on reduced embedding spaces
- spectral clustering on nearest-neighbor graphs or affinity matrices

Purpose:

- test whether the corpus contains variable-density semantic regions that are poorly captured by fixed-`k` methods
- identify whether some abstracts should remain bridge cases rather than being forced into hard categories

### 5. Submitter-Category Comparison

For each candidate semantic category system, compare against:

- primary parent category
- exact primary category (`parent :: subcategory`)

Metrics to add:

- adjusted mutual information
- normalized mutual information
- adjusted Rand index
- per-cluster purity with respect to submitter categories
- per-cluster category entropy
- per-submitter-category fragmentation across learned clusters

Purpose:

- quantify whether learned clusters recover, refine, or cut across the current submitter taxonomy

### 6. Neighborhood Coherence Evaluation

For each embedding family and each candidate category system:

- compute nearest-neighbor agreement at `k = 5, 10, 20`
- compare:
  - fraction of nearest neighbors sharing submitter category
  - fraction of nearest neighbors sharing learned semantic cluster
- compute gain or loss relative to the submitter taxonomy

Purpose:

- test whether learned clusters match the actual local geometry of the embedding space better than the current categories

### 7. Layout Utility Evaluation

Treat each candidate cluster system as a first-class poster-grouping taxonomy and evaluate it using poster-layout objectives.

Metrics:

- adjacent same-cluster rate after numbering
- windowed semantic distance after numbering
- paired-session same-cluster availability
- fraction of multi-poster clusters confined to one block
- cluster fragmentation across sessions
- first-author conflict pressure under session assignment
- oral-to-poster semantic proximity

Purpose:

- measure not just abstract cluster quality, but whether the category system is useful for real conference layout decisions

### 8. Category Usability Evaluation

Assess whether a candidate taxonomy would be organizer-facing usable.

Metrics:

- cluster count
- smallest cluster size
- largest cluster fraction
- small-cluster rate
- singleton/orphan rate
- labelability review from keywords and representative abstracts
- number of clusters that look like catch-all or mixed-topic groups

Purpose:

- avoid adopting a mathematically clean but practically unusable taxonomy

## Evaluation Matrix

Each candidate category system should get a scorecard with these sections:

- embedding family
- category derivation method
  - partition-based clustering benchmark best run
  - graph community detection
  - factorization-based grouping
  - density/manifold-aware grouping
- cluster count and size distribution
- unsupervised quality metrics
- agreement/divergence relative to submitter categories
- nearest-neighbor coherence
- layout utility metrics
- qualitative interpretability notes

## Recommended First Experiment Set

### Phase 1: Baseline Comparison

Run on:

- `voyage_stage2_published`
- `minilm_claims`
- `minilm_stage1`
- `pubmedbert_stage1`

For each:

- partition-based clustering benchmark
- graph semantic analysis
- one non-partition alternative where feasible
  - first preference: embedding-native factorization or soft grouping
  - second preference: spectral or density-based grouping
- nearest-neighbor coherence comparison against submitter categories

Output:

- a cross-embedding benchmark table
- one scorecard per best candidate category system
- a cross-embedding category-evaluation rollup summary in `data/embeddings/category_evaluation_summary.*`

### Phase 2: Layout-Relevance Comparison

Take the top 3 to 5 candidate category systems from Phase 1 and:

- drive poster-layout evaluation with them
- compare directly against the existing submitter-category-based proposal family

Output:

- “Would this taxonomy improve poster layout?” comparison

### Phase 3: Organizer-Facing Recommendation

From the strongest candidates:

- recommend one or two semantic category systems for human review
- summarize where they outperform submitter categories
- identify any failure modes or reasons to keep submitter labels in the loop

## Deliverables

- new design doc for semantic category evaluation
- reusable experiment runner for category-system comparison
- output directory per embedding family under `data/embeddings/*/category_evaluation/`
- summary table comparing candidate semantic taxonomies
- recommendation memo for organizer review

## Implementation Plan

- [ ] Add a category-evaluation script that can score a candidate cluster assignment against submitter categories and layout objectives
- [ ] Add neighborhood-agreement metrics for submitter vs learned categories
- [ ] Add clustering-agreement metrics (`AMI`, `NMI`, `ARI`, purity, entropy)
- [ ] Add support for evaluating graph-community assignments on the same scorecard as partition-based clusters
- [ ] Add a factorization experiment path
  - embedding-native semi-NMF or kernel-based variant first
  - text-feature factorization only if it adds clear value beyond the embedding-native path
- [ ] Add one density/manifold-aware experiment path such as spectral clustering or HDBSCAN
- [ ] Add a summary writer for cross-embedding comparisons
- [ ] Run Phase 1 on the first four embedding families
- [ ] Select top candidate category systems for layout-focused Phase 2
- [ ] Write organizer-facing conclusion

## Notes

- We should keep the current submitter categories as a comparison baseline, not treat them as ground truth.
- A good learned taxonomy may intentionally cut across submitter categories if it better reflects the semantic structure of the abstracts.
- Claims-derived categories may be especially useful for poster-layout grouping because they are content-centered rather than form-centered.
- We should avoid assuming one family of methods is sufficient. A good final taxonomy may come from comparing partition, graph, factorization, and density-aware methods side by side.
