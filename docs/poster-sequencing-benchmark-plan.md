# Poster Sequencing Benchmark Plan

## Goal

Improve local neighborhood coherence in the poster-numbering sequence without changing the current standby-block assignment model.

This phase focuses on the ordering problem only:

- keep the current poster-to-block assignments fixed
- replace the current greedy nearest-neighbor sequencing logic with stronger 1D ordering methods
- compare methods using the existing proposal-analysis workflow plus a stronger focus on low-similarity tails

We can think of this explicitly as a weighted graph reordering problem:

- nodes are posters
- edge weights are semantic similarities
- the objective is to find a permutation whose reordered similarity matrix concentrates edge mass near the diagonal while still preserving interpretable topical blocks

## Why This Phase Now

The current semantic-path ordering logic is still based on greedy nearest-neighbor walks in [src/ohbm2026/poster_layout.py](/Users/satra/software/temp/ohbm2026/src/ohbm2026/poster_layout.py).

Relevant functions:

- `_nearest_neighbor_order`
- `build_block_numeric_order`
- `build_semantic_path_order`
- `build_shared_layout_group_order`

That family of methods is fast and understandable, but it is vulnerable to local traps. This appears in the current Voyage-based recommended layout:

- proposal: `data/poster_layout/proposals/semantic_layout_voyage31/proposal.csv`
- metric: `voyage_stage2_neighbor5_mean_cosine_similarity`
- poster count: `3333`
- mean: `0.617145`
- median: `0.642867`
- 10th percentile: `0.385044`
- posters below `0.6`: `1351`
- posters below `0.5`: `768`

This confirms that the current order has long low-coherence stretches that are noticeable to human reviewers.

## Research Update

The classic method families still dominate this problem:

- spectral seriation
- diffusion-map path extraction
- path-length or TSP-style ordering
- optimal leaf ordering on a hierarchy
- minimum linear arrangement / p-SUM style objectives

There are newer advances that matter, but they mostly extend or hybridize those families rather than replacing them:

- continuation methods for large-scale p-SUM optimization
- tree-penalized path length, which blends TSP-style local coherence with tree consistency
- active seriation methods, which are less relevant here because we already have embeddings for all posters

## Recommended Shortlist

### 1. Tree-Penalized Path Length

`tpPL` is the strongest modern hybrid for this project. It explicitly trades off:

- shorter path length, which helps local semantic coherence
- staying close to a tree structure, which helps interpretability and chunk stability

Why it fits this repo:

- we already care about preserving some meaningful local grouping
- we do not want pure TSP behavior that can split obvious topical clusters
- we can derive the tree from hierarchical clustering or from current layout groups

Main risk:

- the exact best implementation path in Python may require either an external TSP heuristic or a custom approximation layer

### 2. Continuation Methods for Approximate Large-Scale Object Sequencing

This is the strongest recent scalable p-SUM direction. It directly optimizes sequence quality rather than relying only on a spectral relaxation.

Why it fits this repo:

- it targets the exact class of problem we care about: similar items should stay nearby in a 1D order
- it should be better aligned with our failure mode than pure nearest-neighbor or plain spectral sorting
- it offers a strong modern comparator to both spectral and TSP-style methods

Main risk:

- implementation complexity is higher than spectral or OLO
- this may be best as a second-phase benchmark after easier baselines are running

### 3. LKH / Sparse Path-Length Optimization

This is still the strongest practical quality target for a pure 1D sequence.

Why it fits this repo:

- `3333` posters is well within the practical range for candidate-set TSP heuristics
- it should aggressively reduce bad local jumps
- it provides a high-quality upper benchmark for sequence coherence

Main risk:

- without extra structure, pure path-length optimization can split coherent topic chunks
- external solver integration will add some engineering overhead

### 4. Diffusion-Map Path Extraction

This is a strong manifold-first variant of spectral ordering. Instead of using only a Laplacian eigenvector, it builds a diffusion operator on the similarity graph and extracts a path-like order from the leading nontrivial diffusion coordinate.

Why it fits this repo:

- well matched to the idea that semantic poster space may have curved topic manifolds rather than only hard clusters
- uses the same `k`-NN similarity graph we need for spectral methods anyway
- gives us a principled graph-based baseline that is slightly less brittle than a plain greedy path

Main risk:

- if the poster graph is highly branched rather than path-like, a single diffusion coordinate can still flatten important side branches poorly

### 5. Spectral Seriation

This is the fastest meaningful upgrade over the current greedy walk.

Why it fits this repo:

- simple to prototype on a sparse `k`-NN graph
- global rather than greedy
- likely to give a cleaner first benchmark than the current path builder

Main risk:

- it optimizes a relaxation rather than the final discrete adjacency objective
- it may still produce unstable local order inside repeated or weakly separated topic regions

### 6. Hierarchical Clustering with Optimal Leaf Ordering

This remains the best hierarchy-first baseline.

Why it fits this repo:

- easy to explain to organizers
- compatible with category-aware review
- likely useful as the tree input for `tpPL`

Main risk:

- the tree constrains the sequence heavily
- bad early merges can lock in weak local neighborhoods

## Benchmark Strategy

### Fixed Inputs

Use the current recommended semantic proposal as the starting point:

- `data/poster_layout/proposals/semantic_layout_voyage31`

Hold these fixed during the first benchmark pass:

- standby block assignment
- poster inclusion set
- organizer-facing numbering/export format

Only change:

- the sequence order of posters inside each block

This isolates the ordering problem from the assignment problem.

### Similarity Inputs

Primary optimization space:

- `voyage_stage2_published`

Secondary evaluation space:

- `minilm_claims`

Reasoning:

- Voyage is the strongest current semantic layout space
- Claims similarity is still useful as a cross-check that the sequence is not overfitting one embedding family

### Initial Benchmark Pipelines

Start with four concrete sequencing pipelines:

1. current greedy nearest-neighbor baseline
2. spectral seriation on a sparse `k`-NN graph
3. diffusion-map path extraction
4. hierarchical clustering plus optimal leaf ordering
5. sparse path-length optimization

Then extend with the two newer higher-value methods:

6. tree-penalized path length
7. continuation-based p-SUM optimization

In practice, the first pass should implement them in this order:

1. spectral seriation
2. diffusion-map path extraction
3. optimal leaf ordering
4. sparse path-length optimization
5. tree-penalized path length
6. continuation p-SUM

## Evaluation Metrics

### Core Local-Coherence Metrics

- mean adjacent cosine similarity
- median adjacent cosine similarity
- mean `neighbor5` cosine similarity
- median `neighbor5` cosine similarity
- 10th percentile `neighbor5` similarity
- number of posters below `0.6` on `neighbor5`
- number of posters below `0.5` on `neighbor5`
- maximum local semantic jump

### Structural Metrics

- same-category adjacency rate
- same-parent-category adjacency rate
- category fragmentation count
- number of category returns after leaving a local group

### Operational Guardrails

- first-author standby conflicts must remain unchanged at zero
- block sizes and block assignments must remain unchanged
- listing and proposal exports must remain valid

## Proposed Implementation Phases

### Phase 1: Benchmark Harness

- add a reusable sequencing benchmark module
- load a fixed proposal and re-sequence posters inside each block
- score all candidate methods with the same metrics
- write per-method CSV, JSON, and Markdown summaries

Suggested outputs:

- `data/poster_layout/sequencing_benchmarks/<method>/proposal.json`
- `data/poster_layout/sequencing_benchmarks/<method>/proposal.csv`
- `data/poster_layout/sequencing_benchmarks/<method>/analysis.json`
- `data/poster_layout/sequencing_benchmarks/summary.json`
- `data/poster_layout/sequencing_benchmarks/summary.md`

### Phase 2: Fast In-Repo Baselines

- implement spectral seriation
- implement optimal leaf ordering
- add a sparse `2-opt` or `3-opt` local-search path optimizer as an in-repo stand-in for full LKH

This phase should tell us quickly whether the current low-similarity tails are easy to fix.

### Phase 3: Higher-Quality Path Optimizers

- integrate LKH or a similarly strong path solver
- compare pure path-length optimization against the in-repo sparse local-search baseline

### Phase 4: Modern Hybrid / Objective-Driven Methods

- implement or approximate tree-penalized path length
- prototype continuation-based p-SUM optimization

This is the phase most likely to produce the best final sequence quality without giving up thematic structure.

## Initial Recommendation

The first implementation sprint should benchmark these three in order:

1. spectral seriation
2. optimal leaf ordering
3. sparse path-length local search

That gives:

- one global graph-based method
- one hierarchy-preserving method
- one direct path-improvement method

If those results are promising, the next best upgrade is:

- tree-penalized path length

If we want the strongest modern objective-driven comparator after that, add:

- continuation-based p-SUM optimization

## Deliverables

- [ ] Add a sequencing benchmark design module and CLI entrypoint
- [ ] Add tests for benchmark scoring and sequence validity
- [ ] Implement spectral-seriation benchmark
- [ ] Implement diffusion-map path benchmark
- [ ] Implement optimal-leaf-ordering benchmark
- [ ] Implement sparse local-search path benchmark
- [ ] Generate benchmark outputs for the current recommended Voyage layout
- [ ] Review the tail-behavior metrics and choose the best next method
- [ ] Implement `tpPL` benchmark
- [ ] Evaluate continuation-based p-SUM feasibility

## Primary Sources

- Atkins, Boman, Hendrickson. “A Spectral Algorithm for Seriation and the Consecutive Ones Problem.” 1998. DOI: `10.1137/S0097539795285771`
- Bar-Joseph, Gifford, Jaakkola. “Fast optimal leaf ordering for hierarchical clustering.” 2001. DOI: `10.1093/bioinformatics/17.suppl_1.S22`
- Evangelopoulos et al. “Continuation methods for approximate large scale object sequencing.” 2019. DOI: `10.1007/s10994-018-5764-7`
- Aliyev, Zirbel. “Seriation using tree-penalized path length.” 2023. DOI: `10.1016/j.ejor.2022.06.026`
- Lin, Kernighan. “An Effective Heuristic Algorithm for the Traveling-Salesman Problem.” 1973. DOI: `10.1287/opre.21.2.498`
- Helsgaun. “An Effective Implementation of the Lin-Kernighan Traveling Salesman Heuristic.” 2000. DOI: `10.1016/S0377-2217(99)00284-2`
- Helsgaun. “General k-opt submoves for the Lin-Kernighan TSP heuristic.” 2009. DOI: `10.1007/s12532-009-0004-6`
