# Memory Summary

This summary consolidates the local `memory/` notes into a single project view.
The memory filenames are not treated as authoritative chronology. The sequence
below is reconstructed mainly from the repo commit history plus the content of
the notes.

## Reconstructed Order Of Operations

### 1. Core abstract pipeline and enrichment

The project began with the end-to-end OHBM 2026 corpus pipeline:

- accepted abstracts were ingested into `data/abstracts.json`
- the enrichment flow was broken into task-oriented commands
- the enriched abstract schema was simplified into the compact form now used by
  `data/abstracts_enriched.json`
- methods/results figure assets were retained and refresh logic was made
  reuse-aware

Relevant history anchors:

- `42ce05c` `Initial OHBM 2026 pipeline`
- `2b217d3` `Break enrichment into task commands`
- `d056676` `Simplify enriched abstract schema`

### 2. Figure analysis, references, and semantic groundwork

The next major phase added semantic infrastructure around the abstracts:

- OpenAI figure analysis was added and then batched for throughput
- figure text was promoted into enrichment and search/facet behavior
- OpenAlex matching and reference-splitting/resolution were added, with retries,
  async processing, and checkpointing
- local NeuroScape stage-2 tooling and semantic projection tooling were added

Relevant history anchors:

- `83274ca` `Batch OpenAI figure analysis requests`
- `8b167c3` `Promote OpenAI figure text into enrichment`
- `bd8d143` `Improve abstract cleanup and reference resolution`
- `93d9ed4` `Refine reference splitting and resolution flow`
- `2e4c8a8` `Parallelize reference enrichment and refresh docs`
- `f377b43` `Add local NeuroScape stage 2 pipeline`
- `eacc23a` `Add semantic visualization and OpenAlex tooling`

### 3. Static UI and semantic cluster lenses

The abstract atlas UI was then built and refined:

- a standalone static UI was implemented under `ui/` and built to
  `export/ui-site/`
- the UI gained lexical and semantic search, faceted filtering, UMAP selection,
  related abstracts, figure notes, and reference display
- cluster-lens support was added and later made manifest-driven
- the sticky detail panel, collapsible detail sections, compact search toolbar,
  semantic context display, and facet summary behavior were all refined

Stable UI decisions from the memories:

- the right detail panel should stay sticky while the middle results column
  scrolls on desktop
- all detail sections should be collapsible and collapsed by default
- semantic context should show all available cluster assignments for an abstract
- the cluster toggle belongs in the UMAP section and controls coloring rather
  than filtering
- UMAP categorical colors should be perceptually distinct and compactly exposed
  in the UI

Relevant history anchors:

- `b5d29ff` `Build static abstract atlas UI`
- `f5f1ed7` `Add clustering benchmark and UI lens`
- `4feee17` `Add claims-based semantic clustering`
- `2ebc90d` `Add semantic category evaluation and rollup tooling`
- `d91fceb` `Make UI cluster layers manifest-driven`
- `9b54472` `Drop fragmented graph communities from UI shortlist`
- `66e75de` `Move semantic cluster facets near top of sidebar`
- `7961f9e` `Add phenomena and theories annotations to UI`

### 4. Embeddings, clustering, and semantic dataset decisions

The notes record several durable semantic-data decisions:

- `semantic_25` is based on `data/embeddings/voyage_stage2_published`, not
  `minilm_stage1`
- `voyage_stage2_published` comes from the published NeuroScape stage-2 model
  applied to Voyage stage-1 embeddings, not from a locally trained stage-2
  model
- `claims_28` is based on `data/embeddings/minilm_claims`
- claims embeddings currently use only extracted claim text values formatted as
  a `Claims:` section with bullet lines

The first-pass clustering benchmark findings captured in memory were:

- `voyage_stage2_published`: strongest benchmark run `kmeans`, `k=25`
- `minilm_stage1`: strongest benchmark run `kmeans`, `k=30`

### 5. Poster layout system and review workflow

After the abstract atlas work, the repo moved into poster-layout planning and
review:

- poster layout optimization and proposal tooling were added
- the review experience was consolidated into one page at
  `data/poster_layout/proposals/layout_review.html`
- the active organizer review set was narrowed to four proposals:
  - `block_spread_soft`
  - `semantic_layout_voyage25`
  - `semantic_layout_voyage31`
  - `semantic_layout_claims28`
- OLO-derived sequence proposals were explored later, but they were explicitly
  removed from the active organizer-facing workflow

Stable review/layout decisions from the memories:

- the layout review should use regular HTML containers for controls/details with
  Plotly limited to the visualizations
- the page structure should emphasize block 1, block 2, and UMAP at the top,
  with compact controls below
- poster numbering should follow a human-friendly snaking physical traversal of
  the hall
- shared group ordering across the two blocks matters so similar thematic
  regions appear in similar hall locations
- proposal listings should be written with `utf-8-sig` for spreadsheet
  compatibility
- organizer memo balance should be summarized by two-day block, not by
  individual standby session

Relevant history anchors:

- `e0810ed` `Add poster layout optimizer and proposal tooling`
- `d3e149e` `Refine poster layout review interactions`
- `7bf80ca` `Restore poster detail hover interactions`
- `51592ea` `Tighten UMAP toolbar controls`

### 6. Experiment discipline and local working rules

The project now has a strong experiment-management rule set:

- recorded experiment outputs are immutable
- every new experiment run goes in a fresh run directory
- recorded results should never overwrite prior runs
- generic method diagnostics should use names like `diagnostics.json`

This is codified in `CONSTITUTION.md` and is especially relevant for the
sequencing and NOCD experiment trees.

Other durable process notes:

- long-running data jobs should checkpoint incrementally
- headless Chromium checks are worthwhile for visual/interaction-heavy pages
- local `memory/` notes are working memory and should remain untracked unless
  someone explicitly asks otherwise

### 7. NOCD checkpoint workflow

The latest NOCD-related thread established a reusable predict-only workflow:

- OHBM-side NOCD experiments now discover available checkpoints dynamically from
  checkpoint metadata rather than assuming a fixed set
- the classic NOCD runner auto-selects the preferred portable baseline in this
  order:
  - `gcn + structural`
  - `gcn + spectral`
  - `improved + structural`
  - `improved + spectral`
- `feature_type = X` checkpoints are incompatible for zero-shot prediction on
  the OHBM embedding bundles and should be treated as compatibility-only rows
  when present

After pulling the current `sensein/nocd` repo, the shipped checkpoint set
changed:

- the old `X` and `improved` shipped checkpoints were removed
- the current transferable shipped checkpoints are:
  - `nocd-gcn-structural-mag_med.pt`
  - `nocd-gcn-spectral-k32-mag_med.pt`

The first sweep against that reduced shipped set was recorded in:

- `experiments/2026-03-25-nocd-checkpoint-sweep/runs/20260326T082242-nocd-magmed-v1`

Top observed result from that run:

- `nocd_gcn_structural_mag_med_pretrained` on `voyage_stage2_published`

### 8. Stage 4 analysis & annotation

Stage 4 (specs/006-analysis-annotation/) added the canonical post-
embedding annotation pipeline driven by a single CLI entrypoint:
`ohbmcli analyze-matrix`. Key design moves:

- Per-(model, input_source, analysis_kind) bundle layout under
  `data/outputs/analysis/<model>_<input>/<kind>__<state-key>/` —
  mirrors Stage 3's per-component directory shape. Canonical UI
  rollup pair at
  `data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}`.
- Four analysis kinds: `projections` (UMAP 2D+3D + parametric MLP for
  out-of-corpus projection), `communities` (FAISS `IndexFlatIP` kNN +
  Leiden CPM with 20-point resolution sweep + plateau-elbow
  selection, per the published NeuroScape recipe), `neuroscape_clusters`
  (spherical-mean nearest-centroid; **only runs for
  `model == "neuroscape"`** — the published centroids live in the
  domain-embedding space), `topic_clusters` (BERTopic-style UMAP +
  HDBSCAN with noise-elbow `min_cluster_size` selection).
- Hybrid topic pipeline: spaCy `en_core_web_md` (or opt-in scispacy)
  noun-chunk + named-entity extraction → class-based TF-IDF locally;
  optional one-LLM-call-per-cluster pass over the candidate-phrase
  shortlist with strict `Keywords ⊆ candidate_phrases` guard. Cache
  key is sha256-of-sorted-candidates so reruns and order-permutations
  hit cache. `--skip-llm-topics` makes the whole pipeline fully local
  (no OpenAI key needed).
- `project_into_umap(new_vectors, fitted_bundle, algorithm=…)` for
  US2 — supports `native` (umap-learn `transform`), `knn_weighted`
  (model-free softmax of k-nearest reference coords), and `parametric`
  (small numpy-only MLP persisted with the bundle).
- One-off NeuroScape centroid derivation at
  `scripts/derive_neuroscape_centroids.py` reads the published Zenodo
  deposit (DomainEmbeddings/*.h5 + clusters CSVs + the
  `Models/domain_embedding_model.pth` checkpoint) and writes
  `centroids__<sha12>.npy` + `cluster_table.csv` +
  `centroid_metadata.json` carrying source-data sha256s + the
  checkpoint SHA. The runner gate refuses to assign centroids when
  the centroid metadata's `domain_model_checkpoint_sha256` disagrees
  with the Stage 3 `neuroscape` bundle provenance.
- Default matrix is **48 bundles** (5 models × 3 inputs × 4 kinds =
  60 cells, with 12 auto-skipped for non-`neuroscape` source models on
  the `neuroscape_clusters` kind). Inputs: the manuscript `abstract`
  recipe + the per-component `claims` and `methods` bundles.
- Same reorganization treatment Stages 1–3 received: the flat
  `analyze.py` (≈ 2800 LOC) was split into the `analyze/` package
  (`stage.py`, `storage.py`, `clusters.py`, `projections.py`,
  `communities.py`, `centroids.py`, `topics.py`, `topic_clusters.py`,
  `umap.py`, `rollup.py`, `provenance.py`, `errors.py`, `runners.py`).
  The Stage-2 NeuroScape model code moved physically into
  `embed/neuroscape.py` (replacing the re-export façade).
- Per the spec's clarification Q2 (Session 2026-05-15),
  `analyze/__init__.py` carries NO package-level re-export shell.
  Every consumer imports from the explicit submodule that owns the
  symbol.

## Current Practical Defaults

If someone needs the shortest durable summary of how to operate in this repo:

- treat `voyage_stage2_published` as the primary semantic embedding reference
- the canonical post-embedding annotations come from
  `ohbmcli analyze-matrix`, and the UI consumes
  `data/outputs/analysis/annotations__<state-key>.sqlite` plus the
  per-cluster `topics.json` bundles
- treat the four standard poster proposals as the active organizer comparison
  set
- keep experiment runs immutable
- keep local memory notes out of git
- prefer discovery-driven checkpoint handling for NOCD because the upstream
  shipped checkpoint set can change
