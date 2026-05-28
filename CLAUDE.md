# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

Local pipeline that ingests OHBM 2026 accepted abstracts from Oxford Abstracts (GraphQL), enriches them (figures, claims, references), embeds and clusters them, and exports a static search UI plus organizer-facing poster-layout/sequencing experiments. The README is the operational runbook; `docs/reproducibility-vision.md` is the project charter.

There are two coupled but distinct tracks:

- **Track A — canonical corpus pipeline**: driven by `ohbmcli` (`src/ohbm2026/cli.py`). Produces the authoritative artifacts under `data/primary/`, `data/cache/`, `data/outputs/experiments/`, and `data/outputs/exported-sites/`.
- **Track B — exploratory layout/sequencing**: driven by standalone scripts in `scripts/` and recorded runs under `data/outputs/proposals/`. These produce comparative evidence, not silent replacements for canonical outputs.

## Non-negotiables (from `.specify/memory/constitution.md`)

The canonical constitution lives at `.specify/memory/constitution.md` (the root
`CONSTITUTION.md` is a pointer). It applies on **every turn**, not just when
Spec Kit slash commands run — see "Constitution applies to every turn" below.
Short-name summary:

- **I. Venv-only Python.** Always run through `.venv/bin/python` or `uv` explicitly targeting `.venv/bin/python`. Same rule for tests, scripts, one-offs, and dependency installs.
- **II. Immutable evidence, no committed data.** Recorded experiment outputs are append-only (new runs → fresh directories). `data/primary/abstracts.json` is canonical raw corpus; cleanup belongs in explicit derivative artifacts. **Data, caches, exports, downloaded assets MUST NOT be committed** — `data/`, `export/`, `tmp/`, `archive/`, `memory/archive/`, `.claude/` are gitignored; new artifact roots must be gitignored before any write.
- **III. Resumable, auditable pipelines.** Long-running API/LLM jobs checkpoint incrementally; caches under `data/cache/` are keyed by `<state-key>` so reruns skip completed records.
- **IV. Plan-first, test-first.** Update the nearest plan/spec doc and add or identify failing tests before implementing. When canonical defaults change, docs in the same change.
- **V. Secret-safe, commit early and often.** Secrets stay in `.env`; never commit, echo into logs, or paste into docs/transcripts. Commit each verified slice as it lands; do not accumulate hours of unrecorded work.
- **VI. Fail loudly, no shortcuts.** No bare `except`, no silent fallbacks, no `--no-verify` or skipped tests/hooks to make CI green. Temporary workarounds must be labeled with root cause and follow-up.
- **VII. Discover external state, don't hardcode it.** Upstream checkpoints, vendor enumerations, API schemas, and external file layouts MUST be discovered at runtime from metadata; mismatches surface as precise errors, never silent skips.
- **VIII. Provenance for organizer-facing outputs.** Every artifact that reaches organizers, reviewers, or downstream consumers ships with machine-readable provenance (inputs, bundle, config, code revision, command, seed) alongside it — no absolute or user-home paths.

## Constitution applies to every turn

Spec Kit slash commands run a Constitution Check automatically, but the
constitution applies to every action in this repo — direct edits, ad-hoc
prompts, bash-only work, debugging sessions, and unattended jobs all
included. Before reporting work complete, self-check against the I–VIII
short names above. If any check fails, the change is not complete.

The pattern-detectable subset of these checks is automated by the local
lint:

```bash
.specify/scripts/bash/constitution-check.sh --staged   # what the pre-commit hook runs
.specify/scripts/bash/constitution-check.sh --full     # CI / manual sweep
```

The lint catches Principle II (tracked files under gitignored roots),
Principle V (token-shaped strings in the staged diff), and Principle VI
(bare `except:` in `src/`, `--no-verify` usage in committed code). It is
**necessary but not sufficient** — Principles I, III, IV, VII, VIII still
require judgment.

Install the lint as a pre-commit hook once per clone:

```bash
git config core.hooksPath .githooks
```

The hook lives at `.githooks/pre-commit` and delegates to the lint script.

## Setup and validation

```bash
UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Run a single test module:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_neuroscape -v
```

Run a single test:

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_neuroscape.TestClass.test_method
```

Optional dependency groups (only install what a workflow needs):

- Embeddings via HF/MiniLM: `uv pip install --python .venv/bin/python sentence-transformers`
- Projections/UMAP: `uv pip install --python .venv/bin/python plotly umap-learn`
- Stage 2 enrichment (figures + claims + references via OpenAI Responses API): `uv pip install --python .venv/bin/python ".[enrich]"`
- Headless layout review: `uv pip install --python .venv/bin/python ".[review]"` then `playwright install chromium`

## CLI entrypoint

The canonical interface is `ohbmcli` (mapped in `pyproject.toml`):

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli <subcommand>
```

Subcommands group into stages (see README for full options):

- ingest/refresh: `fetch-abstracts`, `fetch-withdrawn`, `refresh-assets` (note: `ingest` and `authors` removed; authors are fetched inline by `fetch-abstracts`)
- enrichment: `enrich-abstracts`, `title-audit` (note: `enrich`, `analyze-figures`, `extract-claims`, `reference-metadata` REMOVED in Stage 2 rewire — FR-014. Operators run `enrich-abstracts` and use `--invalidate <component>` for targeted refresh.)
- embeddings: `embed-matrix` (Stage 3 canonical — per-component bundles for one or more `(model, component)` pairs; supports voyage / minilm / openai / pubmedbert; NeuroScape is a derivation step). Per-model debugging subcommands kept for backward compat: `embed-minilm`, `embed-hf`, `embed-openai`, `embed-voyage`, `embed-stage2`, `apply-published-stage2`. Multi-component recipes (full-manuscript, methods+results, title+results+conclusion) are composed downstream via `neuroscape.compose_recipe([...], model_key=...)`.
- analysis: `semantic-analysis`, `cluster-benchmark`, `umap-plot`, `compare-projections`, `optimize-projections`
- UI data package: `scripts/build_ui_data.py` (Stage 6 canonical; emits `site/static/data/` consumed by the SvelteKit site under `site/`).

Poster layout/sequencing is **not** in `ohbmcli` AND is **parked** as of Stage 5 (see `ohbm2026.layout` parked package and `scripts/layout/` for the 15 companion scripts: `scripts/layout/optimize_poster_layout.py`, `scripts/layout/analyze_poster_layout.py`, `scripts/layout/benchmark_poster_sequencing.py`, etc.). Always pass explicit input paths and a fresh `--output-root`/`--output-dir`; do not rely on stale baked-in defaults.

## Code architecture

All library code lives in `src/ohbm2026/`:

- `graphql_api.py` — Oxford Abstracts GraphQL client (env loading, batching, exponential-backoff retries). Defines `ABSTRACT_IDS_QUERY` (accepted), `WITHDRAWN_IDS_QUERY` (withdrawn), `ABSTRACT_CONTENTS_QUERY` (incl. `program_code` + `program_sessions_submissions` chain), `INTROSPECTION_QUERY` (canonical), and `fetch_schema_introspection`.
- `assets.py` — figure asset download/refresh (reuse-aware via `asset_stem` matching), `normalize_abstract` (maps `program_code` → `poster_id`, flattens `program_sessions_submissions` → `program_sessions`), `fetch_content_batches` generator with per-batch + per-record callback hooks, `advance_record_state` state-machine validator.
- `fetch_stage.py` — **Stage 1 orchestrator** for `ohbmcli fetch-abstracts` / `fetch-withdrawn`; drives introspection → tiered schema diff → checkpoint lifecycle → batched fetch with figure download → atomic-write corpus + schema + provenance.
- `schema_diff.py` — tiered HARD/SOFT/INFORMATIONAL field-level diff classifier; pure functions, no I/O.
- `exceptions.py` — typed cross-stage exception hierarchy rooted at `OhbmStageError(RuntimeError)`. Stage 1 subtree: `Stage1Error` → `SchemaContractError`, `CheckpointError`, `FigureFailureError`. Stage 2 subtree: `Stage2Error` → `EnrichmentError`, `CacheVersionError`, `ComponentFailureThresholdError`. `ProvenanceError` is shared (both stages enforce the no-absolute-/-no-`~` path-boundary rule). Re-exports `GraphQLAPIError`.
- `enrich_stage.py` — **Stage 2 orchestrator** for `ohbmcli enrich-abstracts`; reads the accepted corpus, runs figures + claims + references components with per-component caching keyed by `sha256(input || model_id)`, writes the enriched corpus as SQLite + zlib(json) per row, writes provenance with model identifiers and cache hit/miss counts. Optional Parquet export via `--export-parquet PATH` (lazy-imports `pyarrow`).
- `enrich_storage.py` — `EnrichedCorpusWriter` SQLite I/O helper for Stage 2 (atomic temp→rename) plus `read_one_by_id` / `iter_enriched` / `corpus_metadata`. Stdlib only.
- `enrichment.py` — Stage 2 building blocks (markdown conversion, legacy figure-analysis helpers). Wrapped (not refactored) by `enrich_stage.py`. Stage 2.1 replaces the `cllm`-based claim-extraction path with the agentic OpenAI Responses API call in `stage2_claims.py`.
- `stage2_figures.py`, `stage2_claims.py`, `stage2_references.py` — Stage 2.1 per-component production runners. Figures: per-abstract grouped vision call with local JPEG-q85 compression + a four-field quality probe (`image_quality.py`). Claims: agentic Responses API call with three function tools (`verify_source_quote`, `lookup_eco_code`, `dedupe_check`) returning Pydantic-validated, ECO-annotated claims. References: thin adapter to the existing `openalex.collect_reference_metadata` pipeline.
- `flex_tier.py` — OpenAI flex-tier retry/fallback helper used by figures + claims (1 flex attempt + 1 standard retry; default timeouts 120s figures / 180s claims).
- `image_quality.py` — pure Pillow helpers for the local quality probe.
- `data/eco_top_codes.json` — committed-source ECO v1 controlled vocabulary (9 top-level codes from ECO:0000000).
- `openalex.py` — reference parsing pipeline: markdown normalization → LLM-assisted splitting (validated lexically against source) → DOI/PMID lookup → OpenAlex title search → Semantic Scholar fallback. Wrapped by Stage 2's references component.
- `neuroscape.py` — embeddings (MiniLM/HF/OpenAI/Voyage), stage-2 projection (apply published NeuroScape model or train local), semantic community detection, k-sweep clustering benchmarks, UMAP, projection comparison/optimization.
- `titles.py` — title normalization rules (used by `title-audit`).
- `artifacts.py` — shared artifact-naming/state-key helpers used across stages.
- `category_evaluation.py`, `category_rollup.py` — compare learned cluster families against submitter taxonomies.
- `layout/` (**parked** as of Stage 5 — specs/007-package-reorg/) — poster_layout, poster_sequencing, nocd_experiments. Preserved verbatim for future revival; not actively maintained. Tests under `tests/test_poster_*.py` + `tests/test_nocd_experiments.py` still run with import-paths updated to `ohbm2026.layout.*`. The 15 companion scripts live under `scripts/layout/`. Revive when a new organizer cycle needs poster-layout work.
- `ui_data/` — **Stage 6** UI data-package builders. `manifest.py`, `abstracts.py`, `authors.py`, `cells.py`, `topics.py`, `neighbors.py`, `enrichment.py`, `vectors.py` produce per-shard envelopes (every shard carries a top-level `build_info` block — FR-019 + CA-008). `state_key.py` discovers the corpus + Stage 4 rollup state-keys at build time (CA-007). `builder.py` orchestrates + enforces the 8 cross-shard invariants from `specs/008-ui-rewrite/data-model.md` §8. `link_check.py` HEAD-validates `specs/008-ui-rewrite/contracts/references.yaml` (every external citation from the About page; non-zero exit blocks the deploy — FR-017). CLI entry: `scripts/build_ui_data.py`. Schema: every emitted JSON shard validates against `specs/008-ui-rewrite/contracts/ui_data.linkml.yaml` via `scripts/validate_ui_data.sh`. The SvelteKit site lives at `site/` (self-contained pnpm project; gh-pages deploy via `.github/workflows/{deploy-ui,pr-preview,pr-preview-cleanup}.yml`; runtime data fetched from the Dropbox tarball at `vars.OHBM2026_UI_DATA_PACKAGE_URL`).
- `cli.py` — single dispatch entrypoint that wires the above into subcommands.

Tests in `tests/` mirror the module names and use `unittest`.

## Artifact layout contract

The directory hierarchy is part of the contract — don't write to other roots:

- `data/inputs/` — fetched GraphQL snapshots, API-derived inputs, operator-supplied inputs (e.g. authors, poster layout geometry, manual CSVs).
- `data/primary/` — canonical normalized datasets consumed downstream (`abstracts.json`, `abstracts_withdrawn.json`, `authors.json`, `abstracts_enriched.sqlite` — Stage 2 canonical SQLite+zlib; the legacy `abstracts_enriched.json` is retained until downstream consumers migrate).
- `data/cache/` — resumable caches. Stage 1's `fetch_abstracts/checkpoint__<state-key>.json` uses the legacy state-key naming. Stage 2's per-component caches under `figure_analysis/`, `claim_analysis/`, `reference_metadata/` are keyed by `sha256(input || model_id)` and named `<cache-key>.json`.
- `data/outputs/experiments/` — clustering, embeddings, projections, audit outputs.
- `data/outputs/proposals/` — poster-layout proposal bundles and analyses.
- `data/outputs/exported-sites/ui-site__<state-key>/` — legacy local UI bundle root (the `export-ui` / `build-ui` CLI commands were retired with the Stage 6 rewrite; left in the contract for any remaining legacy bundles).
- `export/ui-site/` — legacy publish mirror of the retired UI bundle.
- `site/static/data/` — **Stage 6** static-JSON shards produced by `scripts/build_ui_data.py`.
- `archive/` — local pre-migration backups; preserves legacy paths.

`data/`, `export/`, `tmp/`, `archive/`, and `memory/archive/` are gitignored.

## Default pipeline state

Current canonical defaults (the UI consumes these):

- Stage 2 single entry: `ohbmcli enrich-abstracts` (`scripts/run_enrich_abstracts.py`). Reads `data/primary/abstracts.json`, writes `data/primary/abstracts_enriched.sqlite` + per-component caches + `data/provenance/abstracts_enrich_provenance__<state-key>.json`. Optional `--export-parquet PATH`.
- figure-interpretation model: OpenAI `gpt-5.4-mini` (flex tier on by default), per-abstract grouped Responses API call with manuscript-text context + in-memory JPEG-q85@1024px compression + a four-field local quality probe. Cached under `data/cache/figure_analysis/<cache-key>.json`.
- claims-extraction: agentic OpenAI Responses API call with `gpt-5.4-mini` (flex tier on by default) — three function tools (verify_source_quote, lookup_eco_code, dedupe_check); Pydantic-validated structured output annotated with ECO v1 codes. Cached under `data/cache/claim_analysis/<cache-key>.json` (key = `sha256(manuscript || model_id || vocabulary_version)`). The legacy `cllm` zero-shot path was removed in Stage 2.1.
- reference-resolution strategy: `refs.v1+openai-gpt-5-nano` (multi-stage: LLM-assisted splitting → DOI/PMID → OpenAlex title search → Semantic Scholar fallback), cached under `data/cache/reference_metadata/<cache-key>.json`.
- Stage 3 single entry: `ohbmcli embed-matrix` (`scripts/run_embed_matrix.py`). Per-component bundles for voyage / minilm / openai / pubmedbert × {title, introduction, methods, results, conclusion, claims}. Output: `data/outputs/embeddings/<model_key>/<component>__<state-key>/{vectors.npy,ids.npy,metadata.json,provenance.json}`. State-key suffix on the bundle dir lets multiple historical versions coexist; clean stale corpora with `rm -rf data/outputs/embeddings/*/*__<old_state_key>`. Run-level provenance at `data/provenance/embeddings_matrix_provenance__<state-key>.json`. Per-abstract cache under `data/cache/embeddings/<model_key>/<cache-key>.json` (key = `sha256(text || model_id || model_version)`).
- embedding bundles in use by the UI (recipes composed at read time via `neuroscape.compose_recipe`): `voyage_stage2_published` (mean of voyage `title+introduction+methods+results+conclusion`, then optional NeuroScape Stage-2 transform) and `minilm_claims` (the per-component `minilm_claims` bundle directly).
- UI projection: composed at consumption time from the per-component minilm bundles using `compose_recipe(["title", "introduction", "methods", "results", "conclusion"], model_key="minilm")`.

## Reading order for unfamiliar context

1. `docs/reproducibility-vision.md` — project charter, what is canonical vs exploratory.
2. `README.md` — operational runbook with every subcommand example.
3. `.specify/memory/constitution.md` — hard rules (root `CONSTITUTION.md` is a pointer).
4. `memory/summary.md` — reconstructed history of major design moves.
5. The plan doc under `docs/` closest to the area you're touching (e.g. `static-ui-plan.md`, `poster-layout-optimizer-plan.md`).
6. The Spec Kit plan under `specs/<NNN>-<topic>/plan.md` for the most recent or most relevant stage if you're touching its area.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/019-neuroscape-semantic-search/plan.md`. The companion design
artefacts under the same directory — `research.md`, `data-model.md`,
`contracts/parquet-schemas.md`, `contracts/cli-build-atlas-package.md`,
`contracts/search-ranking-pipeline.md`,
`contracts/atlas-root-search-ui.md`, and `quickstart.md` — pin Stage 19:
the deferred semantic-search lane for `/neuroscape/` plus a new
cross-conference search bar on atlas-root that ranks OHBM 2026 +
NeuroScape together. Reuses the existing `/ohbm2026/` Xenova/MiniLM-L6-v2
worker; adds a cluster-routed + KNN-expansion pipeline that bounds
per-query cost (~4 MB cold-cache range fetch instead of full 50 MB
sidecar).

The earlier Stage-15 baseline (the three-sibling-deployment architecture
+ three-parquet data layout this spec extends) is documented in
`specs/015-neuroscape-context/plan.md` — that plan remains the canonical
reference for atlas-root, `/ohbm2026/`, and `/neuroscape/` structurally;
spec 019 only adds the semantic search lane to the existing surfaces.

**Architecture — three sibling deployments on one gh-pages host**:
`abstractatlas.brainkb.org/` (atlas-root mode; binary "Show OHBM
2026 overlay" toggle on a NeuroScape PubMed backdrop colour-coded
by cluster); `/ohbm2026/` (unchanged); `/neuroscape/` (new; full
~600K-article PubMed corpus with search + detail). One SvelteKit
project, three build modes via `SITE_MODE` env + `BASE_PATH`.

**Three-parquet data layout**: `ohbm2026.parquet` (renamed from
`data.parquet`, content-identical), `neuroscape.parquet` (new — full
NeuroScape 1999–2023 corpus + cluster table + k=20 neighbours +
lexical search index), `atlas.parquet` (new — landing-page scatter
rows pointing into the two siblings by stable id; bodies NOT
duplicated). `atlas.parquet`'s `build_info` embeds the two sibling
state-keys for drift detection — the browser-side loader surfaces a
visible error banner on mismatch, never a silent partial scatter.

**New Python orchestrator `ohbmcli build-atlas-package`** reads the
NeuroScape v1.0.1 release (HDF5 shards + CSVs + checkpoint, same
inputs as `scripts/derive_neuroscape_centroids.py`), fits a
deterministic 2D + 3D UMAP on Stage-2 vectors (seed=0,
n_neighbors=30, min_dist=0.10, metric=cosine), projects OHBM 2026
abstracts via `umap.transform` using the existing
`voyage_stage2_published` recipe, and emits `neuroscape.parquet` +
`atlas.parquet`. Two caches (UMAP fit, per-abstract projection)
make a second invocation byte-identical and <60s.

**Constitution-critical guarantees**: byte-identical `/ohbm2026/`
build output before vs after this change (FR-022 / SC-008, CI-
enforced); precise typed exceptions across the new
`Stage15Error` subtree for every error path (FR-026); link-checked
PubMed/DOI/citation URLs at build time block the deploy
(FR-024 / SC-006); no new credentials needed; all new artefact
roots are gitignored.

Previous-stage plans:
- Stage 14 poster-id navigator: `specs/014-poster-id-nav/plan.md`
  (extended the existing `<SearchBar>` with an `id:` operator and
  autocomplete dropdown over the in-memory `abstractsByPosterId`
  map; pure client-side, no parquet rebuild). Shipped in PR #35.
- Stage 12 book layout polish + acknowledgments + permalink UX:
  `specs/013-book-layout-polish/plan.md`. Six bundled stories:
  acknowledgments on the permalink page, brief-preview UX with
  show-more, JPEG-q90 @ 150 DPI figure normalisation, 3-column
  TOC longtable, author-index letter buckets, tight book margins.
  Shipped in PR #34 (Stage 12.2 also closed 12 real-corpus
  LaTeX failures + wired KaTeX math + Unicode super/subscript in
  section bodies).
- Stage 11.1 book PDF + standby + DOCX retire + CI telemetry:
  `specs/012-stage11-followups/plan.md` (per-abstract parallel +
  cached PDF; standby INT8 schema; DOCX retirement; CI telemetry
  on the deploy-ui PR-association retry loop; Stage 1's
  `state_key` renamed to `fetch_state_key`). Shipped in PR #31.
- Stage 11 book of abstracts: `specs/011-abstracts-book/plan.md`
  (deterministic `ohbmcli book` CLI; markdown-canonical intermediate
  via pandoc → xelatex/Tectonic for PDF + pandoc-native DOCX writer;
  optional `--style tufte`; figure pre-resize at `--max-image-width`;
  authoritative standby times from FINAL OHBM 2026 listing CSV with
  UI display + facet + cart-restore deep links). Shipped via PRs
  #26-#30. Real-corpus PDF on monolithic compile didn't ship; Stage
  11.1 supersedes that path with per-abstract parallel + caching.
- Stage 10 data export redesign: `specs/010-export-redesign/plan.md`
  (single-file Parquet with row-group-per-table layout; LinkML-tight
  schema eliminating every `range: Any`; magic-byte sniff dispatch
  via the in-browser hyparquet decoder; `poster_id` int16 as the
  sole user-facing identifier replacing Oxford submission_id;
  cross-conference Phase 5 deferred — conference outputs frozen
  post-build, cross-conf linking ships as a UI-side artefact when a
  second conference is ingested). Shipped in PR #20.
- Stage 9 conference subpath rework: `specs/009-conference-subpath/plan.md`
  (every OHBM-2026 surface under `/ohbm2026/`; static meta-refresh
  root-redirect island via `<meta http-equiv="refresh">` + JS
  `location.replace` because gh-pages can't serve real 301s; legacy
  URLs not preserved per Q2; PR previews mirror production at
  `/pr-<N>/ohbm2026/`; primary mechanism is SvelteKit `kit.paths.base`
  with a `BASE_PATH` env override). Shipped in PR #19.
- Stage 6 UI rewrite (US1–US8): `specs/008-ui-rewrite/plan.md` (static
  SvelteKit site on gh-pages; `site/` + `src/ohbm2026/ui_data/`;
  typo-tolerant lexical + semantic search; 3D UMAP + lasso; cart +
  email; guided tour; About + link-checked references; 10+ PRs
  #9–#18 across spec ship-out + post-spec UX (search operators +
  badge clarification) + wrap-up).
- Stage 5 package reorganization: `specs/007-package-reorg/plan.md`
  (collapsed `enrichment.py` into `enrich/{text, markdown_render}.py`;
  parked `layout/`; split `ui.py` into `ui/{payload, cli}.py`;
  consolidated `load_json`/`write_json` into `ohbm2026/util/json_io.py`).
- Stage 4 analysis & annotation: `specs/006-analysis-annotation/plan.md`
  (canonical `ohbmcli analyze-matrix` producing 48 bundles + canonical
  rollup `annotations__<state-key>.{parquet,sqlite}`; joblib-parallel
  orchestrator; hybrid spaCy + c-TF-IDF + LLM-grouping topics).
- Stage 3 embeddings matrix: `specs/005-embeddings-matrix/plan.md`
  (per-component embeddings × 5 models with token-level chunking;
  state-key keyed bundle directories; canonical
  `compose_recipe(...)` composer).
- Stage 2.1 production wiring: `specs/004-enrich-production-wiring/plan.md`
  (gpt-5.4-mini figures+claims, agentic Responses API, ECO v1
  annotation, OpenAlex async references; T058 corpus state_key
  `f0c51e80dc0e`).
- Stage 2 enrichment scaffolding: `specs/003-enrich-abstracts/plan.md`
  (SQLite+zlib storage; the orchestrator surface Stage 2.1 wires
  production runners into).
- Stage 1 fetch-abstracts rewire: `specs/002-rewire-pipeline/plan.md`
  (canonical reference for the per-stage contract pattern).
<!-- SPECKIT END -->
