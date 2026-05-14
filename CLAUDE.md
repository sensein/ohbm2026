# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

Local pipeline that ingests OHBM 2026 accepted abstracts from Oxford Abstracts (GraphQL), enriches them (figures, claims, references), embeds and clusters them, and exports a static search UI plus organizer-facing poster-layout/sequencing experiments. The README is the operational runbook; `docs/reproducibility-vision.md` is the project charter.

There are two coupled but distinct tracks:

- **Track A — canonical corpus pipeline**: driven by `ohbmcli` (`src/ohbm2026/cli.py`). Produces the authoritative artifacts under `data/primary/`, `data/cache/`, `data/outputs/experiments/`, and `data/outputs/exported-sites/`.
- **Track B — exploratory layout/sequencing**: driven by standalone scripts in `scripts/` and recorded runs under `experiments/` and `data/outputs/proposals/`. These produce comparative evidence, not silent replacements for canonical outputs.

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
- UI: `export-ui`, `build-ui`

Poster layout/sequencing is **not** in `ohbmcli` — use `scripts/optimize_poster_layout.py`, `scripts/analyze_poster_layout.py`, `scripts/benchmark_poster_sequencing.py`, `scripts/run_advanced_global_path_experiment.py`, and the `sweep_*` scripts. Always pass explicit input paths and a fresh `--output-root`/`--output-dir`; do not rely on stale baked-in defaults.

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
- `poster_layout.py`, `poster_sequencing.py`, `nocd_experiments.py` — exploratory organizer-facing analyses, called by `scripts/`.
- `ui.py` — static UI export (`export-ui` writes a fresh bundle; `build-ui` also mirrors to `export/ui-site/`).
- `cli.py` — single dispatch entrypoint that wires the above into subcommands.

Tests in `tests/` mirror the module names and use `unittest`.

## Artifact layout contract

The directory hierarchy is part of the contract — don't write to other roots:

- `data/inputs/` — fetched GraphQL snapshots, API-derived inputs, operator-supplied inputs (e.g. authors, poster layout geometry, manual CSVs).
- `data/primary/` — canonical normalized datasets consumed downstream (`abstracts.json`, `abstracts_withdrawn.json`, `authors.json`, `abstracts_enriched.sqlite` — Stage 2 canonical SQLite+zlib; the legacy `abstracts_enriched.json` is retained until downstream consumers migrate).
- `data/cache/` — resumable caches. Stage 1's `fetch_abstracts/checkpoint__<state-key>.json` uses the legacy state-key naming. Stage 2's per-component caches under `figure_analysis/`, `claim_analysis/`, `reference_metadata/` are keyed by `sha256(input || model_id)` and named `<cache-key>.json`.
- `data/outputs/experiments/` — clustering, embeddings, projections, audit outputs.
- `data/outputs/proposals/` — poster-layout proposal bundles and analyses.
- `data/outputs/exported-sites/ui-site__<state-key>/` — primary local UI bundle.
- `export/ui-site/` — optional publish mirror of the latest UI bundle.
- `archive/` — local pre-migration backups; preserves legacy paths.
- `experiments/<date>-<topic>/runs/<fresh-run-name>/` — recorded exploratory experiments; immutable.

`data/`, `export/`, `tmp/`, `archive/`, and `memory/archive/` are gitignored.

## Default pipeline state

Current canonical defaults (the UI consumes these):

- Stage 2 single entry: `ohbmcli enrich-abstracts` (`scripts/run_enrich_abstracts.py`). Reads `data/primary/abstracts.json`, writes `data/primary/abstracts_enriched.sqlite` + per-component caches + `data/inputs/abstracts_enrich_provenance__<state-key>.json`. Optional `--export-parquet PATH`.
- figure-interpretation model: OpenAI `gpt-5.4-mini` (flex tier on by default), per-abstract grouped Responses API call with manuscript-text context + in-memory JPEG-q85@1024px compression + a four-field local quality probe. Cached under `data/cache/figure_analysis/<cache-key>.json`.
- claims-extraction: agentic OpenAI Responses API call with `gpt-5.4-mini` (flex tier on by default) — three function tools (verify_source_quote, lookup_eco_code, dedupe_check); Pydantic-validated structured output annotated with ECO v1 codes. Cached under `data/cache/claim_analysis/<cache-key>.json` (key = `sha256(manuscript || model_id || vocabulary_version)`). The legacy `cllm` zero-shot path was removed in Stage 2.1.
- reference-resolution strategy: `refs.v1+openai-gpt-5-nano` (multi-stage: LLM-assisted splitting → DOI/PMID → OpenAlex title search → Semantic Scholar fallback), cached under `data/cache/reference_metadata/<cache-key>.json`.
- Stage 3 single entry: `ohbmcli embed-matrix` (`scripts/run_embed_matrix.py`). Per-component bundles for voyage / minilm / openai / pubmedbert × {title, introduction, methods, results, conclusion, claims}. Output: `data/outputs/experiments/embeddings/<model_key>_<component>/{vectors.npy,ids.npy,metadata.json,provenance.json}`. Run-level provenance at `data/inputs/embeddings_matrix_provenance__<state-key>.json`. Per-abstract cache under `data/cache/embeddings/<model_key>/<cache-key>.json` (key = `sha256(text || model_id || model_version)`).
- embedding bundles in use by the UI (recipes composed at read time via `neuroscape.compose_recipe`): `voyage_stage2_published` (mean of voyage `title+introduction+methods+results+conclusion`, then optional NeuroScape Stage-2 transform) and `minilm_claims` (the per-component `minilm_claims` bundle directly).
- UI projection: composed at consumption time from the per-component minilm bundles using `compose_recipe(["title", "introduction", "methods", "results", "conclusion"], model_key="minilm")`.

## Reading order for unfamiliar context

1. `docs/reproducibility-vision.md` — project charter, what is canonical vs exploratory.
2. `README.md` — operational runbook with every subcommand example.
3. `.specify/memory/constitution.md` — hard rules (root `CONSTITUTION.md` is a pointer).
4. `memory/summary.md` — reconstructed history of major design moves.
5. The plan doc under `docs/` closest to the area you're touching (e.g. `static-ui-plan.md`, `poster-layout-optimizer-plan.md`).
6. The experiment README under `experiments/` if rerunning a recorded experiment.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/005-embeddings-matrix/plan.md`. The companion design artifacts
under the same directory — `research.md`, `data-model.md`, `contracts/`,
and `quickstart.md` — pin Stage 3 embedding-matrix design: per-component
embeddings (title, introduction, methods, results, conclusion, claims)
across five models (Voyage, MiniLM, OpenAI, PubMedBERT, NeuroScape-from-
Voyage); multi-component recipes are composed downstream by averaging.
Batch size 64 per paid-API call with dynamic concurrency starting at 8;
long-input strategy defaults to chunk_mean_pool for MiniLM/PubMedBERT
and truncate_end for Voyage/OpenAI; per-abstract caching under
`data/cache/embeddings/<model_key>/` keyed by sha256(text || model_id ||
model_version) for resume-friendly runs.

Previous-stage plans:
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
