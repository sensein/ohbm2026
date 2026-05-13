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
UV_CACHE_DIR=.uv-cache uv venv --python 3.11 .venv
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
- Claim extraction: `uv pip install --python .venv/bin/python git+https://github.com/OpenEvalProject/cllm.git`
- Headless layout review: `uv pip install --python .venv/bin/python ".[review]"` then `playwright install chromium`

## CLI entrypoint

The canonical interface is `ohbmcli` (mapped in `pyproject.toml`):

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli <subcommand>
```

Subcommands group into stages (see README for full options):

- ingest/refresh: `ingest`, `refresh-assets`, `authors`
- enrichment: `analyze-figures`, `extract-claims`, `enrich`, `title-audit`, `reference-metadata`
- embeddings: `embed-minilm`, `embed-hf`, `embed-openai`, `embed-voyage`, `embed-stage2`, `apply-published-stage2`
- analysis: `semantic-analysis`, `cluster-benchmark`, `umap-plot`, `compare-projections`, `optimize-projections`
- UI: `export-ui`, `build-ui`

Poster layout/sequencing is **not** in `ohbmcli` — use `scripts/optimize_poster_layout.py`, `scripts/analyze_poster_layout.py`, `scripts/benchmark_poster_sequencing.py`, `scripts/run_advanced_global_path_experiment.py`, and the `sweep_*` scripts. Always pass explicit input paths and a fresh `--output-root`/`--output-dir`; do not rely on stale baked-in defaults.

## Code architecture

All library code lives in `src/ohbm2026/`:

- `graphql_api.py` — Oxford Abstracts GraphQL client (env loading, batching, exponential-backoff retries).
- `assets.py` — abstract ingest and methods/results figure download/refresh (reuse-aware).
- `enrichment.py` — markdown conversion, figure analysis (OpenAI or Ollama backends), claim extraction (`cllm`), and final enriched-corpus assembly.
- `openalex.py` — reference parsing pipeline: markdown normalization → LLM-assisted splitting (validated lexically against source) → DOI/PMID lookup → OpenAlex title search → Semantic Scholar fallback. Resumable with checkpoints.
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
- `data/primary/` — canonical normalized datasets consumed downstream (`abstracts.json`, `abstracts_enriched.json`, `reference_metadata.json`).
- `data/cache/` — resumable caches, keyed by `<state-key>` (e.g. `data/cache/figure_analysis/image_analyses_openai__<state-key>.json`).
- `data/outputs/experiments/` — clustering, embeddings, projections, audit outputs.
- `data/outputs/proposals/` — poster-layout proposal bundles and analyses.
- `data/outputs/exported-sites/ui-site__<state-key>/` — primary local UI bundle.
- `export/ui-site/` — optional publish mirror of the latest UI bundle.
- `archive/` — local pre-migration backups; preserves legacy paths.
- `experiments/<date>-<topic>/runs/<fresh-run-name>/` — recorded exploratory experiments; immutable.

`data/`, `export/`, `tmp/`, `archive/`, and `memory/archive/` are gitignored.

## Default pipeline state

Current canonical defaults (the UI consumes these):

- figure analysis backend: OpenAI (`gpt-4.1-mini`), cached under `data/cache/figure_analysis/`.
- claim extraction: `cllm` with OpenAI (`gpt-4o-2024-08-06`), cached under `data/cache/claim_analysis/`.
- reference splitting: OpenAI Responses API with `gpt-5-nano`, with concurrency caps and requeue-on-failure.
- embedding bundles in use by the UI: `voyage_stage2_published` (semantic 25-cluster lens) and `minilm_claims` (claims 28-cluster lens via `clustering_benchmark_25_30`).
- UI projection: `minilm_stage1/umap_title-introduction-methods-results-conclusion.json`.

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
<!-- SPECKIT END -->
