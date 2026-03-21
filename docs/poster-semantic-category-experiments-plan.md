# Poster Semantic Category Experiments Plan

## Goal

Determine whether data-driven semantic categories provide a better modular grouping of the OHBM 2026 abstract space than the submitter-selected category system.

This should answer three concrete questions:

1. Which embedding spaces produce the cleanest semantic partitions?
2. Which clustering strategy yields useful category systems at organizer-relevant granularity?
3. Do those learned categories outperform submitter-selected parent/subcategory labels as a layout primitive?

## Current Baseline

Submitter-selected labels currently give us:

- `16` parent categories
- `121` exact `parent :: subcategory` labels

Existing local semantic outputs already suggest that the information space supports mid-granularity partitions in roughly the `15-30` cluster range, depending on embedding space and method.

## Candidate Embedding Families

Primary comparison set:

- `data/embeddings/voyage_stage2_published`
- `data/embeddings/minilm_stage1`
- `data/embeddings/minilm_claims`
- `data/embeddings/openai_stage1`
- `data/embeddings/pubmedbert_stage1`
- `data/embeddings/voyage_stage1`
- `data/embeddings/neuroscape_stage2_local`

Interpretation:

- `claims` is likely strongest for claim-level thematic grouping
- `voyage_stage2_published` is likely strongest for general semantic organization
- the stage-1 bundles are the main baselines for model-family comparison

## Evaluation Families

### 1. Internal Cluster Quality

Run `cluster-benchmark` on each embedding bundle and compare:

- silhouette score
- Davies-Bouldin score
- Calinski-Harabasz score
- intercluster / intracluster distance ratio
- cluster size entropy
- largest-cluster fraction

Purpose:

- identify embeddings that naturally support well-separated, balanced semantic categories

### 2. Graph Community Quality

Run `semantic-analysis` on each embedding bundle with a controlled target range for community counts.

Evaluate:

- modularity
- realized community count
- cluster size distribution
- qualitative coherence from representative abstracts and keywords

Purpose:

- test whether graph communities give more modular organizer-facing categories than centroid-based clustering

### 3. Submitter-Label Geometry Fit

Evaluate existing submitter labels directly as labelings over each embedding space.

Label systems to score:

- parent category
- exact `parent :: subcategory`

Metrics to compute:

- silhouette score
- Davies-Bouldin score
- intercluster / intracluster distance ratio
- k-nearest-neighbor label purity
- graph modularity when labels are projected onto the embedding kNN graph

Purpose:

- quantify how well the submitter categories match the actual semantic geometry

### 4. Alignment Between Learned and Submitter Labels

Compare learned clusters to submitter categories using:

- adjusted mutual information
- normalized mutual information
- V-measure / homogeneity / completeness
- cluster-to-category entropy

Purpose:

- determine whether learned clusters merely reproduce submitter categories, or reorganize the space in a more coherent way

### 5. Layout-Relevance Metrics

For the best candidate label systems, run poster-layout simulations and compare:

- nearby-poster semantic coherence
- nearby-poster category purity
- discoverability of related work across standby sessions
- cluster spread across blocks and sessions
- small-cluster handling

Purpose:

- ensure a cluster system is not only mathematically clean, but useful for physical layout

## Proposed Experiment Matrix

Phase 1: existing artifact audit

- summarize already-generated clustering benchmarks and semantic analyses
- identify missing benchmark outputs

Phase 2: benchmark all embedding bundles

- run `cluster-benchmark` on all primary comparison embeddings
- collect best method and best cluster count per bundle

Phase 3: compare learned clusters vs submitter labels

- score submitter parent/exact labels on each embedding
- score best learned clusters on the same embedding
- rank embeddings by improvement over submitter labels

Phase 4: derive organizer-facing candidate category systems

- shortlist `3-5` candidate label systems, likely including:
  - `voyage_stage2_published` best benchmark clustering
  - `minilm_claims` best benchmark clustering
  - one graph-community solution in the `15-30` range
  - submitter parent labels as baseline
  - submitter exact labels as baseline

Phase 5: layout simulation

- run poster-layout assignment/ordering using each shortlisted label system
- compare organizer-relevant outcomes

## Expected Deliverables

- `data/embeddings/category_evaluation_summary.json`
- `data/embeddings/category_evaluation_summary.csv`
- `data/embeddings/category_evaluation_summary.md`
- per-embedding evaluation outputs under each embedding directory
- cross-embedding rollup outputs in `data/embeddings/category_evaluation_summary.*`
- one organizer-facing comparison brief explaining:
  - whether learned categories beat submitter categories
  - which embedding space to trust
  - which cluster granularity is most usable

## Immediate Implementation Tasks

- [x] Audit existing embedding and clustering artifacts
- [x] Finish missing `cluster-benchmark` runs for the main embedding bundles
- [x] Add a script to evaluate arbitrary label systems on a given embedding space
- [x] Add a script to compare learned clusters against submitter categories
- [x] Build a cross-embedding rollup summary
- [ ] Shortlist candidate semantic category systems for layout testing
- [ ] Run layout comparisons for shortlisted systems

## First-Pass Findings

Current best unsupervised clustering outputs:

- `voyage_stage2_published`: `kmeans`, `k=25`, silhouette `0.1028`, inter/intra ratio `1.2782`
- `voyage_stage1`: `kmeans`, `k=30`, silhouette `0.0815`, inter/intra ratio `1.2285`
- `pubmedbert_stage1`: `kmeans`, `k=29`, silhouette `0.0674`, inter/intra ratio `1.0638`
- `minilm_stage1`: `kmeans`, `k=30`, silhouette `0.0664`, inter/intra ratio `1.0939`
- `openai_stage1`: `kmeans`, `k=25`, silhouette `0.0654`, inter/intra ratio `1.0302`
- `minilm_claims`: `kmeans`, `k=28`, silhouette `0.0635`, inter/intra ratio `1.0331`
- `neuroscape_stage2_local`: `kmeans`, `k=30`, silhouette `0.0254`, inter/intra ratio `0.6150`

Interpretation:

- `voyage_stage2_published` is currently the strongest general-purpose embedding for category discovery
- `voyage_stage1` is the strongest stage-1 baseline
- `minilm_claims` remains useful because it yields an organizer-plausible `28`-cluster claim-space partition
- `neuroscape_stage2_local` is currently not competitive for organizer-facing category discovery

Submitter-label fit on embedding geometry:

- parent-category silhouettes are slightly negative on every tested embedding
- exact submitter-category silhouettes are more negative on every tested embedding
- this strongly suggests the submitter taxonomy does not align with the semantic geometry of the corpus

Practical consequence:

- the burden of proof has shifted
- we no longer need to prove that learned categories are merely different from submitter categories
- we need to determine which learned category system is most coherent and organizer-usable

## Recommended First Decision Gate

Before doing new layout work, pick the best `2-3` semantic category candidates based on:

- strongest internal clustering quality
- acceptable cluster size balance
- clear qualitative themes
- clear improvement over submitter labels on geometry-fit metrics

If no learned system clearly beats submitter labels, then the right conclusion is not to replace submitter categories wholesale. In that case, the fallback should be a hybrid system: submitter categories for high-level navigation, learned clusters for within-category ordering and cross-category discovery.
