# Poster Layout Optimizer Plan

## Goal

Build a script-first poster session optimizer for OHBM 2026 that assigns poster abstracts to standby sessions and numbering/layout groups while balancing:

- topical similarity between nearby posters
- even distribution across standby sessions
- presenter ability to see posters in their own field during sessions when they are not standing by their own poster
- reduced author conflicts, especially when the same person appears as first or second author on multiple posters

The first pass should produce library code plus CLI scripts only. UI integration is explicitly out of scope for now.

## Working Assumptions

These are the assumptions used in the current implementation:

- poster assignment is built from the accepted-poster subset of `data/abstracts.json`
- oral presentations are not assigned poster standby sessions, but they are included in analysis outputs as topical and semantic context
- claim-based semantic distance should come from the existing `data/embeddings/minilm_claims` bundle unless a different bundle is preferred
- first-author conflict checks should use `authors[*].author_order` from the Oxford Abstracts export and should be treated as hard constraints
- the optimization output should be auditable and rerunnable from local files without API access
- each poster is assigned to one paired standby pattern out of four; each pattern contains two one-hour standby windows, one on each day of a single 2-day block

## Product Questions To Confirm

Confirmed decisions for the first pass:

1. Posters live in a fixed two-day block, and the presenter is assigned to one of the two odd/even hourly standby patterns within that block.
2. Only first-author conflicts are constrained, and they are hard constraints.
3. The first implementation should optimize over the accepted corpus while explicitly reporting the oral presentations in the analysis outputs.
4. A numeric poster order is sufficient for now.
5. Category reporting should support both parent-only and parent-plus-subcategory views.

## Proposed Deliverables

- `src/ohbm2026/poster_layout.py`
  - reusable loading, feature extraction, optimization, numbering, and scoring helpers
- `scripts/optimize_poster_layout.py`
  - CLI entrypoint to assign posters to sessions and output a proposed numbering/layout
- `scripts/analyze_poster_layout.py`
  - CLI entrypoint to score an assignment for author conflicts, semantic locality, and category locality
- tests for optimizer constraints, scoring behavior, and CLI output shape
- JSON and CSV outputs that can be reviewed outside the app

## Input Data Model

Per poster, the optimizer will need:

- `abstract_id`
- cleaned `title`
- primary category
- first author id
- second author id if present
- claim-based embedding vector or neighbor profile

Likely source files:

- `data/abstracts.json`
- `data/abstracts_enriched.json`
- `data/embeddings/minilm_claims/metadata.json`
- `data/embeddings/minilm_claims/vectors.npy`

## Proposed Output Artifacts

- `data/poster_layout/proposal.json`
  - full assignment payload with metadata and objective components
- `data/poster_layout/proposal.csv`
  - one row per accepted abstract for spreadsheet review and downstream plotting
- `data/poster_layout/proposal_listing.csv`
  - organizer-facing export shaped like the 2025 poster listing sheet, with poster number plus first/second standby times
- `data/poster_layout/analysis.json`
  - quality metrics for the proposed or supplied layout
- `data/poster_layout/session_summaries.json`
  - per-session category mix, semantic cohesion, and conflict totals

Suggested fields in `proposal.csv`:

- `abstract_id`
- `poster_number`
- explicit first and second standby times
- `layout_zone`
- `layout_row`
- `layout_position`
- `primary_category`
- `first_author_id`
- `second_author_id`
- `semantic_cluster` if useful as a review aid

## Optimization Strategy

Use a staged optimizer instead of trying to solve all layout details at once.

### Phase 1: Build Poster Features

- load poster-only abstracts
- extract primary category from raw responses
- extract first and second author ids from ordered author lists
- align abstract ids with the claims embedding bundle
- optionally attach semantic cluster ids from an existing claims clustering run for diagnostics

### Phase 2: Assign Posters To Session Buckets

Treat session assignment as the highest-priority combinatorial problem.

Hard constraints:

- every poster is assigned to exactly one paired standby pattern, which implies two total one-hour standby windows within a single 2-day block
- session sizes stay within capacity tolerance
- accepted poster count is fully assigned exactly once

Soft constraints to optimize:

- split posters from the same primary category across available session buckets
- avoid placing the same first or second author in the same standby session
- preserve overall category balance across sessions

Candidate implementation approach:

- start with a greedy seeded assignment by category size and author-conflict risk
- improve with local search:
  - swap posters between sessions
  - move a poster when it reduces total penalty
- compute an objective score after each move

This keeps the first version transparent and testable without requiring a heavy solver dependency.

### Phase 3: Number Posters Within Each Session Or Layout Block

After session assignment is stable:

- compute pairwise semantic distance within a session or session block
- order posters so nearby numbers have lower semantic distance
- add a category-aware term so related fields remain discoverable

Candidate implementation approach:

- cluster or sort each session using claims embeddings
- build a nearest-neighbor walk or seriation-like ordering
- optionally reserve contiguous ranges per coarse topic band while still mixing categories across sessions

### Phase 4: Score The Result

The analysis script should report:

- author conflicts by session
- semantic distance between nearby numbered posters
- primary-category adjacency distances
- category distribution across sessions
- same-category availability across alternate sessions for presenter discoverability

## Metrics

### Author Conflict Metrics

- number of first-author conflicts per session
- number of second-author conflicts per session
- number of first-or-second-author conflicts per session
- list of conflicting author ids and affected posters

### Semantic Locality Metrics

Using claims-based embeddings:

- mean cosine distance between adjacent posters in numbering order
- median cosine distance between adjacent posters
- nearest-neighbor retention within a local numbering window
- per-session semantic cohesion summary

### Category Locality Metrics

- fraction of adjacent poster pairs with identical primary category
- fraction sharing the same parent category if applicable
- run lengths for category streaks
- category entropy per session

### Discoverability Metrics

- for each primary category, share of posters in each session or session block
- for each presenter, count of same-category posters available outside their own standby assignment

## CLI Shape

Proposed first-pass commands:

```bash
PYTHONPATH=src .venv/bin/python scripts/optimize_poster_layout.py \
  --raw-input data/abstracts.json \
  --enriched-input data/abstracts_enriched.json \
  --embeddings-dir data/embeddings/minilm_claims \
  --output-dir data/poster_layout
```

```bash
PYTHONPATH=src .venv/bin/python scripts/analyze_poster_layout.py \
  --assignment data/poster_layout/proposal.json \
  --raw-input data/abstracts.json \
  --embeddings-dir data/embeddings/minilm_claims \
  --output data/poster_layout/analysis.json
```

If this matures well, we can later fold the same functionality into `ohbmcli`.

## Test Plan

### Unit Tests

- feature extraction returns primary category and ordered author ids correctly
- embedding alignment fails clearly when ids are missing or duplicated
- conflict scorer catches same-author collisions in the same session
- semantic adjacency scorer prefers semantically coherent orderings
- category scorer reflects same-category and cross-category adjacency as expected

### Optimizer Tests

- assignment respects exact session capacities on a synthetic corpus
- optimizer reduces conflicts versus a naive baseline
- optimizer splits oversized categories across session buckets
- local-search improvement never drops posters or duplicates assignments

### CLI Tests

- optimize script writes proposal JSON and CSV
- analysis script writes expected summary metrics
- invalid inputs fail with actionable errors

## Implementation Phases

- [x] Confirm session-assignment model and physical numbering assumptions
- [x] Add a poster-layout design module in `src/ohbm2026/poster_layout.py`
- [x] Add synthetic tests for constraints and scoring before implementing search
- [x] Implement poster feature loading and validation
- [x] Implement conflict and locality scoring
- [x] Implement greedy grouped assignment with hard first-author session constraints
- [x] Implement numbering/layout ordering within each assigned block
- [x] Add analysis script and output reports
- [x] Shift standby assignments to paired one-hour patterns within each 2-day block
- [x] Add an organizer-facing listing export modeled on the 2025 poster listing spreadsheet
- [x] Run on the local accepted corpus and review diagnostics
- [ ] Tune weights with stakeholder feedback

## Recommendation

For the first implementation, optimize in two levels:

- session assignment for fairness, conflict reduction, and cross-session discoverability
- within-session numbering for semantic and category locality

That decomposition matches the operational problem well and should give us an auditable result faster than a single monolithic optimizer.

## Next Phase

The next sequencing-focused benchmark phase is tracked in:

- [docs/poster-sequencing-benchmark-plan.md](/Users/satra/software/temp/ohbm2026/docs/poster-sequencing-benchmark-plan.md)

That plan keeps block assignments fixed and compares stronger ordering algorithms against the current greedy nearest-neighbor baseline, with special attention to low-similarity local stretches in the current Voyage-based proposal.
