# OHBM 2026 Pipeline

This repository builds a local OHBM 2026 abstract corpus from the Oxford
Abstracts GraphQL API and carries it through figure enrichment, reference
matching, embeddings, clustering, and a static search UI.

This README is the runbook for a person or an agent that needs to go from the
original abstract download to the current latest step.

Repository home:

- Git remote `origin`: `git@github.com:sensein/ohbm2026.git`
- GitHub URL: [github.com/sensein/ohbm2026](https://github.com/sensein/ohbm2026)

Project conventions that should not be violated live in
[CONSTITUTION.md](CONSTITUTION.md),
including the rules that Python work stays inside the repository-local `.venv`,
recorded experiment runs write to fresh directories instead of overwriting prior
outputs, behavior-changing work stays plan-first and test-driven, and secrets
never get copied into the repo or logs.

This README is the operational runbook, not the full project charter.
For the repo-level intent, reproducibility model, authoritative defaults, key
decisions, and experiment history, start with
[docs/reproducibility-vision.md](docs/reproducibility-vision.md).

If you only read one document before changing behavior, read
[docs/reproducibility-vision.md](docs/reproducibility-vision.md)
first.

Catalogs for the rest of the repository:

- [docs/README.md](docs/README.md)

Recommended reading order for a new person or agent:

1. [docs/reproducibility-vision.md](docs/reproducibility-vision.md)
2. [README.md](README.md)
3. [docs/README.md](docs/README.md)
4. [CONSTITUTION.md](CONSTITUTION.md)
5. [memory/summary.md](memory/summary.md)
6. the specific plan under `specs/` closest to the work you are changing

## What The Pipeline Produces

Core artifacts:

- `data/inputs/abstracts_graphql__<state-key>.json`
  - GraphQL-fetched source snapshot for the latest ingest run
- `data/primary/abstracts.json`
  - canonical normalized accepted abstracts derived from the fetched snapshot
- `data/inputs/assets/`
  - downloaded local figure files, restricted to methods/results figures
- `data/cache/figure_analysis/image_analyses_<backend>__<state-key>.json`
  - resumable figure-analysis cache with direct state-key lookup
- `data/cache/claim_analysis/<cache-key>.json`
  - resumable claim-extraction cache (Stage 2.1: keyed by
    `sha256(manuscript || claims_model_id || eco_vocabulary_version)`)
- `data/outputs/experiments/title_audit/title_modifications.json`
  - audit log of cleaned abstract titles versus original raw titles
- `data/primary/abstracts_enriched.json`
  - enriched abstract corpus with markdown sections, figure analyses, and claim extraction when available
- `data/primary/reference_metadata.json`
  - OpenAlex-matched reference metadata
- `data/outputs/experiments/embeddings/*`
  - canonical embedding bundles, stage-2 projections, and neighbors
- `data/outputs/experiments/*__<state-key>/`
  - clustering, projection, and other experiment-style derived outputs
- `data/outputs/exported-sites/ui-site__<state-key>/`
  - local exported-site bundle before optional publish mirroring
- `data/outputs/proposals/*__<state-key>/`
  - proposal bundles and proposal-adjacent analysis outputs
- `export/ui-site/`
  - optional publish mirror of the latest exported-site bundle

Local artifact layout rules:

- `data/inputs/` is for fetched snapshots, API-derived inputs, and manual operator-supplied inputs
- `data/primary/` is for canonical normalized datasets consumed by downstream stages
- `data/cache/` is for resumable caches and checkpoints
- `data/outputs/experiments/`, `data/outputs/exported-sites/`, and
  `data/outputs/proposals/` are for local derived outputs
- `archive/` is for local pre-migration backups that preserve legacy paths
- `data/`, `export/`, and `tmp/` remain ignored by git

## Current Latest Step

The latest end state of the project is:

1. accepted abstracts downloaded locally
2. methods/results figures downloaded and linked
3. OpenAI figure text promoted into the main enriched abstract dataset
4. reference metadata matched with OpenAlex where possible
5. multiple embedding bundles generated
6. published NeuroScape stage-2 applied to Voyage embeddings
7. clustering benchmarks run on embedding bundles
8. static UI built with:
   - lexical search
   - browser-side semantic search
   - facets
   - UMAP selection
   - two semantic cluster lenses:
     - `25-cluster benchmark`
     - `claims 28-cluster benchmark`
9. **Atlas UI** — static SvelteKit site served from GitHub Pages, with per-PR preview deploys surfaced in the PR's Deployments box (NOT bot comments). Shipped across `008-ui-rewrite` (US1–US8), `009-conference-subpath` (URL rework), and `010-export-redesign` (parquet data package + identifier consolidation). Production at `abstractatlas.brainkb.org/ohbm2026/`; PR previews at `/pr-<N>/ohbm2026/`. The bare root `abstractatlas.brainkb.org/` bounces to `/ohbm2026/` via a static `<meta http-equiv="refresh">` + JS redirect island (gh-pages cannot serve a true HTTP 301; spec 009 names this honestly).

10. **Data export redesign** (`010-export-redesign`) — the data package switched from a gzipped tarball of JSON shards to a single Parquet file. Reasons: native STRUCT/LIST types eliminate every `range: Any` slot from the schema, dict-encoded int columns shrink id storage ~4× before zstd, and the single-file shape supports HTTP Range requests for future row-group lazy load. Schema change: `poster_id` (int16, range 1–3333) is the sole user-facing identifier across every shard — Oxford submission_id no longer appears in the export. The reverse map lives in `data/primary/abstracts.json` for traceability. Phase 5 (cross-conference linking) is deferred to a UI-side artifact so conference parquets stay immutable post-build.

## Atlas UI

The site lives under `site/` (a self-contained SvelteKit project; SvelteKit 2 + Vite 6 + Svelte 5). The data-package builder lives under `src/ohbm2026/ui_data/`. Capabilities: typo-tolerant lexical search, transformers.js-backed semantic search (MiniLM-L6 ONNX in a Web Worker against an int8-quantised corpus matrix), 2D + 3D UMAP with lasso + cluster colour-coding, interactive facets, cart + email-my-list, a guided tour (shepherd.js), and an About page whose external citations are HEAD-checked at build time (`link_check.py`). Every OHBM 2026 surface (home, About, abstract permalink) lives under the `/ohbm2026/` URL subpath so the same domain can later host other conferences without URL-space collision.

Build the data package + the site locally:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
  --corpus data/primary/abstracts.json \
  --withdrawn data/primary/abstracts_withdrawn.json \
  --authors data/primary/authors.json \
  --enriched data/primary/abstracts_enriched.sqlite \
  --analysis-root data/outputs/analysis \
  --discover-rollup \
  --output site/static/data

cd site && pnpm install && pnpm dev    # http://localhost:5173
```

Run the JS test suite:

```bash
cd site && pnpm test:unit --run        # Vitest unit tests
cd site && UI_DATA_AVAILABLE=1 pnpm exec playwright test --project=chromium   # e2e (needs the data package built first)
```

### Refreshing the deployed data package

CI doesn't materialize the Stage 1–4 inputs. Instead, the maintainer builds the data package locally and hosts the single `data.parquet` at a URL the deploy workflow reads from the `OHBM2026_UI_DATA_PACKAGE_URL` repo variable (sha256-pinned via `OHBM2026_UI_DATA_PACKAGE_SHA256`).

**Stage 10 swap** (see `specs/010-export-redesign/research.md` § B3): the data package is now a single `data.parquet` file (~25 MB) with one row group per logical table — abstracts, authors, cells, topics, neighbours, enrichment, manifest, MiniLM vector blob. Range-fetchable at row-group granularity for the lazy-load story; replaces the Stage-6 gzipped JSON-shards tarball.

**Dropbox in-place write is still required to preserve the share link** — overwrite the same path on Dropbox so the inode / share URL stays stable; do NOT delete-and-create.

```bash
# 1. Build the parquet directly to the canonical Dropbox path.
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
  --corpus data/primary/abstracts.json \
  --withdrawn data/primary/abstracts_withdrawn.json \
  --authors data/primary/authors.json \
  --enriched data/primary/abstracts_enriched.sqlite \
  --analysis-root data/outputs/analysis \
  --discover-rollup \
  --minilm-root data/outputs/embeddings/minilm \
  --proposal-listing archive/proposals/proposals/block_spread_soft/proposal_listing.csv \
  --output ~/dbm/shares/ohbm2026/ \
  --output-format parquet-single \
  --conference ohbm2026

# 2. Update the sha256 repo variable so CI sidecar docs reflect the
#    new bytes. The URL repo variable never changes after the first
#    share-link is generated; only the sha256 var bumps per refresh.
NEW_SHA=$(shasum -a 256 ~/dbm/shares/ohbm2026/data.parquet | awk '{print $1}')
gh variable set OHBM2026_UI_DATA_PACKAGE_SHA256 --body "$NEW_SHA"
```

The `--proposal-listing` flag is optional — without it the `poster_standby` field is empty; with it each abstract carries the program-committee stand-by times. The CLI also accepts `--output-format gzip-json-shards` for the legacy tarball shape (kept reachable for one-off dev comparisons; not the canonical export).

Per-PR previews surface in the **PR's Deployments box** (top-of-PR, via the `environment:` declaration in `.github/workflows/pr-preview.yml`) — NOT as a bot comment. The short committish (first 7 chars of git SHA) bakes into the page `<title>` + the persistent footer affordance via the `VITE_BUILD_SHA` env var injected by the deploy workflows, so reviewers can verify each PR-preview reflects the latest pushed commit at-a-glance (FR-022 + SC-011).

## External Requirements

Required:

- `python` 3.14 (canonical local target; `pyproject.toml` still declares `requires-python = ">=3.11"` for downstream compat)
- `uv`

Optional, depending on which branch of the pipeline you run:

- `ollama`
- local Ollama model `qwen3.5:35b`
- Hugging Face access for downloading sentence-transformer models
- OpenAI API access for Stage 2.1 enrichment (`gpt-5.4-mini` default; figures + agentic claims via the Responses API) and OpenAI embeddings
- Voyage API access for Voyage embeddings
- OpenAlex API key for authenticated reference matching

### Stage 15 prerequisites (`ohbmcli build-atlas-package`)

Stage 15 (spec `015-neuroscape-context`) builds the cross-conference
atlas landing page and the new `/neuroscape/` subsite. Operators
running `ohbmcli build-atlas-package` need the NeuroScape v1.0.1
release on disk under `data/inputs/neuroscape-source/v101/` with this
layout (gitignored):

```text
data/inputs/neuroscape-source/v101/
└── Data/
    ├── CSV/
    │   ├── neuroscience_articles_1999-2023.csv   # one row per article: pmid, title, abstract, year, cluster_id, journal, doi, …
    │   ├── neuroscience_clusters_1999-2023.csv   # cluster_id → title, description, keywords, focus, …
    │   └── neuroscience_dimensions_1999-2023.csv # dimension axis labels (optional)
    ├── HDF5/
    │   ├── DomainEmbeddings/                     # 2307 `shard_*.h5` files — Stage-2 vectors (64-dim, ~200 articles/shard)
    │   └── VoyageAIEmbeddings/                   # Stage-1 vectors (Voyage 1024-dim; not used by Stage-15 pipeline)
    └── Models/
        ├── domain_embedding_model.pth            # NeuroScape Stage-2 model checkpoint (sha 8a8e6931…)
        └── discipline_classification_model.pth   # not used by Stage-15 pipeline
```

Scale: 461,316 articles across 175 clusters (the upstream clusters
CSV holds 2,632 entries but only 175 are used at the top level — the
Stage-15 orchestrator filters to clusters that appear in the articles
CSV's `Cluster ID` column, mirroring the convention already used by
`scripts/derive_neuroscape_centroids.py`).

See [specs/015-neuroscape-context/quickstart.md](specs/015-neuroscape-context/quickstart.md)
for the full operator runbook (download + rebuild + upload + deploy).
The release is published on Zenodo; the orchestrator does not
redistribute it.

## Environment Variables

Create `.env` from [.env.sample](.env.sample).

Common keys:

- `OHBM2026_API`
  - required for Oxford Abstracts ingest and author lookup
- `OPENAI_API_KEY`
  - required for Stage 2's `enrich-abstracts` (figure interpretation, claims extraction, OpenAI-backed reference splitting) and for OpenAI embeddings
- `ANTHROPIC_API_KEY`
  - currently unused by Stage 2.1 — the default claims path is OpenAI Responses API. Reserved for a future Anthropic alternative.
- `VOYAGE_API`
  - required for Voyage embeddings
- `OPENALEX_API`
  - optional but recommended for reference enrichment
- `HF_TOKEN`
  - optional for Hugging Face model downloads

No API key is needed for local Ollama figure analysis.

Treat `.env` and shell environment variables as the only valid homes for these
secrets. Do not commit tokens, paste them into docs, or leave them in command
logs.

## Token And Tool Matrix

Use this as the quick answer to "what do I need before I run this step?"

| Workflow | Required secret(s) | Extra local tool(s) | Notes |
| --- | --- | --- | --- |
| `ohbmcli fetch-abstracts` / `fetch-withdrawn` | `OHBM2026_API` | none | Stage 1 — accepted + withdrawn corpora; authors fetched inline |
| `ohbmcli refresh-assets` | none | none | Uses the existing local normalized corpus |
| `ohbmcli enrich-abstracts` | `OPENAI_API_KEY`; optional `OPENALEX_API` (recommended) | `.[enrich]` optional extra (openai>=2.0 + Pillow>=10 + pydantic>=2) | Stage 2.1 — figures + agentic claims + references with per-component caches. Default model `gpt-5.4-mini`, flex tier ON by default. Flags: `--invalidate <component>`, `--no-flex-figures` / `--no-flex-claims`, `--concurrency-figures N` / `--concurrency-claims N` (default 30 each), `--figure-model-id` / `--claims-model-id` / `--reference-strategy-id`, `--export-parquet PATH` (needs the `parquet` extra). |
| `ohbmcli title-audit` | none | none | Reads local normalized corpus only |
| `ohbmcli embed-minilm` / `embed-hf` | optional `HF_TOKEN` | `sentence-transformers` | `HF_TOKEN` is only needed for gated/private Hub access |
| `ohbmcli embed-openai` | `OPENAI_API_KEY` | none | Hosted embedding route |
| `ohbmcli embed-voyage` | `VOYAGE_API` | none | Voyage embedding route |
| `ohbmcli apply-published-stage2` / `embed-stage2` | none | local model dependencies already in `.venv` | Uses local artifacts |
| `ohbmcli semantic-analysis` / `cluster-benchmark` / `umap-plot` / `compare-projections` / `optimize-projections` | none | optional `plotly`, `umap-learn` | Purely local once embeddings exist |
| `ohbmcli book` | none | `.[abstracts_book]` (markdownify, beautifulsoup4, pikepdf, Pillow, joblib) + system `pandoc` + LaTeX engine (Tectonic recommended) | Stage 11 + Stage 11.1 — composes Book of Abstracts; markdown bundle always; `--format pdf` runs the per-abstract pipeline with content-hash caching; outputs to `data/outputs/book/`. (DOCX retired in Stage 11.1 US3.) |
| `scripts/optimize_poster_layout.py` / `scripts/analyze_poster_layout.py` | none | none | Uses local proposal inputs, authors, and layout assets |
| poster sequencing scripts under `scripts/` | none | none | Use local proposals and embeddings |
| `scripts/build_ui_data.py` | none | none | Stage 6: builds the static-JSON data package consumed by the SvelteKit site under `site/` |

## Setup

Do not use system Python in this repo. Create or refresh `.venv` with `uv`, and
run Python commands through `.venv/bin/python` or `uv` targeting that
interpreter.

Create the virtual environment and run tests:

```bash
UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Optional Python packages by workflow:

MiniLM or HF embeddings:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python sentence-transformers
```

Interactive projections:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python plotly umap-learn
```

Stage 2.1 enrichment (figures + agentic claims via OpenAI Responses API + references):

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[enrich]"
```

Installs `openai>=2.0` + `Pillow>=10` + `pydantic>=2`. The legacy
`cllm` zero-shot claim-extraction path is removed in Stage 2.1.

Headless layout review:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[review]"
PYTHONPATH=src .venv/bin/python -m playwright install chromium
PYTHONPATH=src .venv/bin/python scripts/check_layout_review.py
```

For local figure analysis, confirm Ollama can see the required model:

```bash
ollama list
```

## Recommended Sequences

Pick the sequence that matches what you are trying to regenerate.

### Full Rebuild To The Static UI

Run these in order when rebuilding the main deliverable from upstream data:

1. `ohbmcli fetch-abstracts` (authors are fetched inline; replaces the former `ingest` + `authors` pair)
2. `ohbmcli enrich-abstracts` (replaces the former `analyze-figures` + `extract-claims` + `enrich` + `reference-metadata` quartet; one entry, per-component caches under `data/cache/{figure_analysis,claim_analysis,reference_metadata}`)
3. `ohbmcli title-audit`
4. one or more embedding commands such as `embed-minilm`, `embed-voyage`, or `embed-openai`
5. `ohbmcli apply-published-stage2` if you want the published Voyage stage-2 space
6. `ohbmcli semantic-analysis`, `cluster-benchmark`, `umap-plot`, or `compare-projections` for the cluster and projection products you want the UI to consume
7. `ohbmcli analyze-matrix` (Stage 4 — produces the canonical `data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}` rollup the Stage 6 site consumes)
8. `scripts/build_ui_data.py` (Stage 6 — see the "Stage 6: UI" section above)

### Add Or Refresh A Cluster Family

Use this when you already have the corpora and want a new cluster output:

1. confirm the required embedding bundle exists under `data/outputs/experiments/embeddings/`
2. run `ohbmcli semantic-analysis` for community-detection style outputs
3. run `ohbmcli cluster-benchmark` for k-sweep style outputs
4. optionally run `scripts/evaluate_label_systems.py` to compare a new cluster family against the submitter taxonomy
5. point Stage 4 (`ohbmcli analyze-matrix`) or layout scripts at the new cluster directory

### Generate Or Refresh A Layout Proposal

> **The `layout/` package is parked as of Stage 5** (specs/007-package-reorg/) — poster-layout / sequencing / NOCD code is preserved verbatim under `src/ohbm2026/layout/` and `scripts/layout/`, but is not actively maintained. The instructions below remain accurate; only the script paths have moved (`scripts/optimize_poster_layout.py` → `scripts/layout/optimize_poster_layout.py`, etc.). Revive when a new organizer cycle needs poster work.

Use this when you want a new organizer-facing proposal:

1. confirm `data/primary/abstracts.json`, `data/inputs/authors.json`, and `data/inputs/poster_layout/layout_assets/layout_geometry.json` exist
2. choose the embedding bundle and any claims/layout cluster inputs you want to drive the proposal
3. run `scripts/layout/optimize_poster_layout.py` into a fresh proposal directory under `data/outputs/proposals/`
4. run `scripts/layout/analyze_poster_layout.py` on that proposal
5. optionally run comparison or review scripts against multiple proposal directories

### Run A Poster Sequencing Experiment

Use this when you already have a base proposal and want comparative sequencing evidence:

1. pick a base proposal under `data/outputs/proposals/`
2. run one of the sequencing scripts under `scripts/` into a fresh local output root under `data/outputs/proposals/`
3. keep the experiment outputs immutable and compare them rather than overwriting the active proposal set

### Minimal UI Refresh

Use this when the data products already exist locally:

1. rerun only the upstream steps that changed
2. rerun `scripts/build_ui_data.py` to refresh the static-JSON shards under `site/static/data/`
3. do not rerun hosted/API steps unless their inputs or parameters changed

## End-To-End Workflow

Use `ohbmcli` for the corpus, enrichment, embedding, clustering, and UI
pipeline. Use the script wrappers under `scripts/` for proposal generation,
layout analysis, and sequencing experiments.

### 1. Download The Raw Abstracts And Figures

This is the canonical starting point. Two distinct corpora are
fetched separately; they never share an output file or a state-key
namespace.

**Accepted corpus** (the main pipeline driver):

```bash
PYTHONPATH=src .venv/bin/python scripts/run_fetch_abstracts.py
```

Equivalent through `ohbmcli`:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli fetch-abstracts
```

What it does:

- fetches accepted abstracts from Oxford Abstracts (`decision_status=Accepted`)
- stores the normalized corpus in `data/primary/abstracts.json`
- persists the upstream GraphQL schema introspection alongside at
  `data/inputs/abstracts_graphql_schema__<state-key>.json`
- writes a machine-readable provenance record at
  `data/provenance/abstracts_fetch_provenance__<state-key>.json`
- writes a resumable checkpoint under
  `data/cache/fetch_abstracts/checkpoint__<state-key>.json` (deleted
  on full completion)
- downloads only methods/results figure images, reuse-aware
- writes local figure links into each abstract

Each normalized record now includes:

- `poster_id` (the OHBM-assigned poster number, sourced from upstream `program_code`)
- `program_sessions` (list of standby/symposium session memberships
  with date, location, time, type, track — empty list until
  organizer scheduling lands upstream)

Important behavior:

- retries use an exponential timeout schedule starting at `100ms` and capped at `10s`
- figure downloads are reuse-aware (same abstract_id + same source URL → zero HTTP)
- schema drift on a fetch-query field exits non-zero (code 2) without overwriting the corpus
- resumable: an interrupted run picks up from the per-record marker on the next invocation

**Withdrawn corpus** (separate file, never mixed with accepted):

```bash
PYTHONPATH=src .venv/bin/python scripts/run_fetch_withdrawn.py
```

Or `ohbmcli fetch-withdrawn`. Output:
`data/primary/abstracts_withdrawn.json`. Filter:
`decision_status="Withdrawn" AND complete=true AND archived=false`.
Same per-record shape as the accepted corpus. State-key namespace
is independent.

See [docs/per-stage-pattern.md](docs/per-stage-pattern.md) for the
contract every stage script (this one and the upcoming Stage 2..N)
satisfies.

### 2. Refresh Assets Without Rerunning Abstract Extraction

Use this if the raw JSON already exists and you only need to rebuild or prune
local figure links.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli refresh-assets --reuse-existing-assets-only
```

### 3. Enrich The Corpus

Stage 2 — single canonical entry that runs all three enrichment components
(figure interpretation, claims extraction, reference resolution) against the
accepted corpus, with per-component caches keyed by
`sha256(input || model_id)`. The four legacy subcommands
(`analyze-figures`, `extract-claims`, `enrich`, `reference-metadata`)
are REPLACED by this single entry (FR-014).

```bash
PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py
```

Equivalent through `ohbmcli`:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich-abstracts
```

What it does:

- reads `data/primary/abstracts.json` (accepted-only filter; the
  withdrawn corpus is read-only)
- for each accepted abstract: runs figures + claims + references
  through per-component caches under
  `data/cache/{figure_analysis,claim_analysis,reference_metadata}/<cache-key>.json`
- writes the enriched corpus to `data/primary/abstracts_enriched.sqlite`
  (SQLite + zlib(json) per row; primary-key indexed for O(1) random
  lookup; ~21 MB for the 3244-abstract corpus per the benchmark in
  `specs/003-enrich-abstracts/research.md`)
- writes provenance to
  `data/provenance/abstracts_enrich_provenance__<state-key>.json`
  with names-only env vars, per-component model identifiers, and
  cache hit/miss counts

Component-targeted refresh (when only one model changes):

```bash
PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py \
  --invalidate figures \
  --figure-model-id gpt-4o
```

Other two components reuse cache hits intact. Use the same pattern
with `--invalidate claims` or `--invalidate references`.

Optional Parquet export (alongside the canonical SQLite output):

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[parquet]"
PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py \
  --export-parquet data/primary/abstracts_enriched.parquet
```

The `parquet` optional extra installs `pyarrow`; the orchestrator
lazy-imports it only when the flag is set.

Smoke-check a random lookup:

```bash
.venv/bin/python -c "
import sqlite3, zlib, json
con = sqlite3.connect('data/primary/abstracts_enriched.sqlite')
row = con.execute('SELECT payload FROM abstracts WHERE id = ?', (1246274,)).fetchone()
rec = json.loads(zlib.decompress(row[0]))
print(rec['id'], rec.get('poster_id'), 'claims:', len(rec.get('claims', [])), 'figures:', len(rec.get('figure_interpretation', [])))
"
```

### 4. Audit And Clean Display Titles

The raw Oxford Abstracts export is kept unchanged, but downstream consumers now
normalize obvious title issues such as leading bullets, wrapping quotes, and
stray outer whitespace.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli title-audit \
  --input data/primary/abstracts.json \
  --output data/outputs/experiments/title_audit/title_modifications.json
```

Output:

- `data/outputs/experiments/title_audit/title_modifications.json`

This file records each changed title with the original string, cleaned title,
and normalization reasons.

### 5. Generate Embeddings

Stage 3 generates per-component embeddings (one bundle per
`(model, component)` pair) and lets downstream tools compose
multi-component recipes by averaging the relevant component vectors.

Canonical entry — the matrix command:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py \
  --models voyage,minilm,openai,pubmedbert \
  --components title,introduction,methods,results,conclusion,claims
```

Models supported (FR-005):

| Model key  | Model id                                          | Tier   |
|------------|---------------------------------------------------|--------|
| voyage     | `voyage-large-2-instruct` (NeuroScape Stage-1 compatible) | paid  |
| minilm     | `sentence-transformers/all-MiniLM-L6-v2` (UI search model) | local |
| openai     | `text-embedding-3-small`                          | paid   |
| pubmedbert | `neuml/pubmedbert-base-embeddings`                | local  |
| neuroscape | derived from a Voyage bundle (apply the published Stage-2 model) | local |

Canonical components (FR-006):
`title`, `introduction`, `methods`, `results`, `conclusion`, `claims`.
The opt-in `inference_claims` component covers ~12% of abstracts and
requires `--allow-partial inference_claims`.

Bundles land at `data/outputs/embeddings/<model_key>/<component>__<state-key>/`
with `vectors.npy`, `ids.npy`, `metadata.json`, and `provenance.json`.
The state-key suffix lets re-runs against a fresh enriched corpus
coexist alongside prior versions; old corpora can be cleaned via
`rm -rf data/outputs/embeddings/*/*__<old_state_key>`.

Behavior:
- Per-abstract cache writes (`data/cache/embeddings/<model_key>/`)
  enable byte-equivalent resume after interruption (FR-009 / SC-003).
- Paid providers batch at 64 inputs per HTTP call with dynamic
  concurrency starting at 8 (FR-009a / FR-009b).
- Long-input defaults: `chunk_mean_pool` for MiniLM / PubMedBERT,
  `truncate_end` for Voyage / OpenAI (FR-010).
- Per-bundle JSON-on-stdout + a run-level rollup at the end.
- Provenance at `data/provenance/embeddings_matrix_provenance__<state-key>.json`.

Single-model subcommands (`embed-voyage`, `embed-minilm`, `embed-openai`,
`embed-hf`) remain available for debugging individual bundles.

Composing multi-component recipes downstream:

```python
from ohbm2026.neuroscape import compose_recipe
manuscript = compose_recipe(
    ["title", "introduction", "methods", "results", "conclusion"],
    model_key="voyage",
)
# manuscript["matrix"] is float32 [n_union × dim]
# manuscript["ids"]    is int64 [n_union]
```

Cost ballpark for the full 30-bundle matrix at fresh-cache: ~$1 USD
(Voyage + OpenAI combined); free for the local-only subset
(`--models minilm,pubmedbert`). Cached re-runs complete in seconds.

### 6. Apply Or Train The NeuroScape Stage-2 Embedding Model

#### Apply the published NeuroScape stage-2 model

Use this when you have a compatible Voyage stage-1 bundle.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli apply-published-stage2
```

#### Train a local stage-2 model

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-stage2
```

### 7. Build Semantic Analysis And Cluster Outputs

Community detection over an embedding bundle:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli semantic-analysis \
  --embeddings-dir data/outputs/experiments/embeddings/voyage_stage2_published
```

Clustering benchmark over an embedding bundle:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli cluster-benchmark \
  --embeddings-dir data/outputs/experiments/embeddings/voyage_stage2_published \
  --output-dir data/outputs/experiments/clustering_benchmark__<state-key>
```

To benchmark a claims-only bundle around `25-30` clusters:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli cluster-benchmark \
  --embeddings-dir data/outputs/experiments/embeddings/minilm_claims \
  --output-dir data/outputs/experiments/clustering_benchmark_claims_25_30__<state-key> \
  --k-min 25 \
  --k-max 30
```

This is the current claims-cluster artifact consumed by the UI. The latest run selected a `28`-cluster k-means solution inside that benchmark output.

If you want to score a new cluster family against the submitter taxonomy:

```bash
PYTHONPATH=src .venv/bin/python scripts/evaluate_label_systems.py \
  --embeddings-dir data/outputs/experiments/embeddings/voyage_stage2_published \
  --raw-input data/primary/abstracts.json \
  --label-system submitter_parent \
  --label-system submitter_exact \
  --label-system candidate=data/outputs/experiments/embeddings/voyage_stage2_published/clustering_benchmark/cluster_assignments.json \
  --output-dir data/outputs/experiments/embeddings/voyage_stage2_published/category_evaluation
```

Projection outputs:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli umap-plot
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli compare-projections
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli optimize-projections
```

### 7.5 Stage 4 Analysis Matrix (`analyze-matrix`)

Stage 4 is the canonical post-embedding annotation pipeline. It runs the
**(model, input_source, analysis_kind)** matrix end-to-end and emits the
canonical UI rollup. See `specs/006-analysis-annotation/quickstart.md`
for the operator runbook; high-level recipe below.

One-off setup (NeuroScape centroid derivation from the published Zenodo
deposit at <https://zenodo.org/records/14865161>):

```bash
# After unzipping NeuroScape_v101.zip somewhere on disk:
PYTHONPATH=src .venv/bin/python scripts/derive_neuroscape_centroids.py \
  --input-root <path-to-unzipped-NeuroScape_v101> \
  --output-root data/inputs/neuroscape
# Produces:
#   data/inputs/neuroscape/centroids__<version>.npy
#   data/inputs/neuroscape/cluster_table.csv
#   data/inputs/neuroscape/centroid_metadata.json
```

Default-matrix run (48 bundles: 15 projections + 15 communities +
15 topic_clusters + 3 neuroscape_clusters across 5 models × 3 inputs —
`abstract` recipe + `claims` component + `methods` component; the
published NeuroScape centroids only assign rows for the `neuroscape`
domain embedding, so voyage/minilm/openai/pubmedbert are auto-skipped
for the `neuroscape_clusters` kind):

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix
```

Run without an OpenAI key (topic keywords come from a local
spaCy + c-TF-IDF pipeline; `Title`/`Description`/`Focus` are left
empty):

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix \
  --skip-llm-topics
```

Restrict to one model (faster iteration; produces 6 bundles + 1
auto-skip event):

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix \
  --models voyage
```

Project a new abstract into an existing fitted UMAP bundle (US2):

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-umap-project \
  --fitted-bundle data/outputs/analysis/voyage_abstract/projections__<state-key>/ \
  --input-vectors path/to/new_vectors.npy \
  --algorithm native \
  --output path/to/new_coords.npy
```

The orchestrator writes one bundle per `(model, input, kind)` cell
under `data/outputs/analysis/<model>_<input>/<kind>__<state-key>/`
plus a canonical rollup at
`data/outputs/analysis/annotations__<corpus-state-key>.{parquet,sqlite}`
that the UI export step consumes. See `contracts/bundle.md` +
`contracts/rollup.md` under `specs/006-analysis-annotation/` for the
exact schemas.

### 8. Generate And Analyze Layout Proposals

The stable route for proposal generation currently lives in the script wrappers
under `scripts/`, not in `ohbmcli`.

Generate a fresh proposal bundle:

```bash
PYTHONPATH=src .venv/bin/python scripts/optimize_poster_layout.py \
  --raw-input data/primary/abstracts.json \
  --authors-input data/inputs/authors.json \
  --embeddings-dir data/outputs/experiments/embeddings/minilm_claims \
  --claims-cluster-assignments data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json \
  --claims-cluster-summaries data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json \
  --output-dir data/outputs/proposals/layout_claims__<fresh-run-name>
```

Analyze that proposal:

```bash
PYTHONPATH=src .venv/bin/python scripts/analyze_poster_layout.py \
  --assignment data/outputs/proposals/layout_claims__<fresh-run-name>/proposal.json \
  --raw-input data/primary/abstracts.json \
  --embeddings-dir data/outputs/experiments/embeddings/minilm_claims \
  --claims-cluster-assignments data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json \
  --claims-cluster-summaries data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json \
  --output data/outputs/proposals/layout_claims__<fresh-run-name>/analysis.json
```

To drive the layout with a learned label system instead of the submitter
taxonomy, add:

- `--layout-cluster-assignments <cluster_assignments.json>`
- `--layout-cluster-summaries <cluster_summaries.json>`
- `--layout-label-system <name>`

Use a fresh `--output-dir` whenever the layout label system, embeddings, or
weights change. The default output-root hash does not encode every proposal
option.

### 9. Run Poster Sequencing And Proposal Experiments

Once a base proposal exists, the sequencing and comparison workflows are also
script-driven. Write these outputs to fresh experiment directories or fresh
proposal output roots.

Graph benchmark against an existing proposal:

```bash
PYTHONPATH=src .venv/bin/python scripts/benchmark_poster_sequencing.py \
  --proposal data/outputs/proposals/layout_claims__<fresh-run-name>/proposal.json \
  --raw-input data/primary/abstracts.json \
  --authors-input data/inputs/authors.json \
  --embeddings-dir data/outputs/experiments/embeddings/voyage_stage2_published \
  --claims-cluster-assignments data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json \
  --claims-cluster-summaries data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json \
  --output-root data/outputs/proposals/poster-sequencing-benchmark__<fresh-run-name>
```

Advanced non-diffusion global-path experiment:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_advanced_global_path_experiment.py \
  --proposal data/outputs/proposals/layout_claims__<fresh-run-name>/proposal.json \
  --raw-input data/primary/abstracts.json \
  --authors-input data/inputs/authors.json \
  --embeddings-dir data/outputs/experiments/embeddings/voyage_stage2_published \
  --claims-cluster-assignments data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json \
  --claims-cluster-summaries data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json \
  --output-root data/outputs/proposals/advanced-global-path__<fresh-run-name>
```

The same pattern applies to `scripts/sweep_diffusion_variants.py`,
`scripts/sweep_global_path_variants.py`, and
`scripts/sweep_global_path_mapalign_variants.py`: pass explicit current paths
for the proposal, corpora, authors, embeddings, and output root rather than
relying on older baked-in defaults.

### 10. Build The Static UI

The current latest delivery step is the **Atlas UI — SvelteKit site under `site/`**, fed by the Python data-package builder under `src/ohbm2026/ui_data/`. See the "Atlas UI" section near the top of this README for the canonical build recipe (`scripts/build_ui_data.py` then `pnpm dev` / `pnpm build`). The legacy `ohbmcli export-ui` / `build-ui` commands that wrote a hand-rolled HTML+JSON bundle into `data/outputs/exported-sites/ui-site__<state-key>/` have been removed.

### 11. Book Of Abstracts (Stage 11 + Stage 11.1)

Compose a publication-quality book of every accepted abstract — title,
authors with affiliations, full body text, embedded figures, and the
author-supplied references — sorted by `poster_id` (default), `title`,
or `first_author` surname, with a paginated author index at the back.

Markdown is the canonical intermediate; PDF derives from the per-
abstract pipeline introduced in Stage 11.1: each abstract renders to
its own small PDF (cached by content+toolchain hash) in parallel via
joblib, chunks concatenate via pikepdf with measured page offsets,
and a hand-rolled author-index appendix is pandoc-compiled in a
second pass and appended. Per-abstract failures isolate cleanly — the
offending entry drops out, the rest renders, and the diagnostic
capture lands under `provenance.failed_abstracts[]`. Re-runs with no
input change skip every per-abstract render (cache hit), so the
warm-cache path is dominated by `pikepdf` concat + the index pass.
Cache lives under `data/cache/book/abstracts/` (gitignored).

DOCX export was retired in Stage 11.1 US3 — `--format docx` exits
with a pointer at the surviving formats. The real-corpus DOCX
hit 2.8 GB (too large for Word to open) and the markdown bundle
plus PDF cover every use case it served.

Content sourced exclusively from Stage-1 artefacts (`data/primary/abstracts.json`
+ `authors.json` + `data/inputs/assets/`); **zero Stage-2 / LLM
content reaches the book** (SC-006 audit logged in `provenance.json`).

System deps: install `pandoc` + a LaTeX engine (Tectonic recommended)
once per machine — see `specs/011-abstracts-book/quickstart.md` step 2
for the brew / apt commands. Optional Python extra:

```bash
uv pip install --python .venv/bin/python ".[abstracts_book]"
```

Then invoke:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format pdf --sort poster_id
```

Useful Stage 11.1 flags:

- `--workers N` — joblib `n_jobs` for per-abstract rendering. Default `-1` (all cores); `1` for serial debug.
- `--no-cache` — bypass the per-abstract PDF cache (every chunk re-renders; existing cache entries are NOT overwritten).
- `--cache-dir PATH` — override the cache root. Default `data/cache/book/abstracts`.

Output lands at `data/outputs/book/book__<state-key>/` with
`book.md` + `book.pdf` (when `--format pdf|all`) +
`fig_assets/` + `provenance.json`. The figure-asset filename
contract: `<submission_id>-<poster_id>-<type>[-<index>].<ext>` —
flat directory; `<type>` is `methods` / `results`; `<index>` is
1-based and only present when an abstract supplies more than one
figure of the same type. Full design at
`specs/011-abstracts-book/`; Stage 11.1 per-abstract pipeline +
standby schema rework at `specs/012-stage11-followups/`.

The deployed site lives at `abstractatlas.brainkb.org/ohbm2026/` (per spec 009-conference-subpath). PR previews surface at `/pr-<N>/ohbm2026/` in each PR's Deployments box. The bare root `abstractatlas.brainkb.org/` (and `/pr-<N>/`) is a static redirect island that bounces visitors to the conference subpath — gh-pages cannot serve a true HTTP 301, so this is a `<meta http-equiv="refresh">` + JS `location.replace`. Deploy workflows (`.github/workflows/deploy-ui.yml`, `pr-preview.yml`) stage the build into `site/publish/ohbm2026/` and copy `site/conference-root-redirect/{index,404}.html` to the publish root.

## Suggested Minimal Rebuilds

If you already have raw abstracts:

- rerun `ohbmcli enrich-abstracts` (per-component caches make it cheap; pass `--invalidate <component>` if a single model identifier changed)
- rerun `scripts/build_ui_data.py` to refresh the Stage 6 data package

If you already have an enriched corpus and only changed UI code:

- rerun `scripts/build_ui_data.py`

If only one component model changed (e.g., new figure model):

- rerun `ohbmcli enrich-abstracts --invalidate figures --figure-model-id <new>`
- rerun `scripts/build_ui_data.py`

If you already have embeddings but want new cluster evaluations:

- rerun `cluster-benchmark`
- optionally rerun `scripts/evaluate_label_systems.py`
- optionally rerun `ohbmcli analyze-matrix` + `scripts/build_ui_data.py`

If you specifically want to refresh the claims-based semantic lens:

- rerun `embed-minilm --fields claims --output-name minilm_claims`
- rerun `cluster-benchmark --embeddings-dir data/outputs/experiments/embeddings/minilm_claims --output-dir data/outputs/experiments/embeddings/minilm_claims/clustering_benchmark_25_30 --k-min 25 --k-max 30`
- rerun `ohbmcli analyze-matrix` + `scripts/build_ui_data.py`

If you want to regenerate a proposal without touching the corpora:

- rerun `scripts/optimize_poster_layout.py` into a fresh `data/outputs/proposals/...` directory
- rerun `scripts/analyze_poster_layout.py`

If you want to rerun sequencing experiments on an existing proposal:

- pick the proposal JSON under `data/outputs/proposals/`
- rerun the relevant script under `scripts/` into a fresh experiment run directory

## Module Layout

- `src/ohbm2026/graphql_api.py`
  - GraphQL access, env loading, batching, retries; canonical
    `INTROSPECTION_QUERY`; `fetch_abstract_ids`,
    `fetch_withdrawn_ids`, `fetch_schema_introspection`
- `src/ohbm2026/assets.py`
  - figure asset download/refresh (reuse-aware), normalization
    (`normalize_abstract` maps `program_code` → `poster_id` and
    flattens `program_sessions_submissions[]` →
    `program_sessions[]`), `fetch_content_batches` generator with
    per-batch + per-record callback hooks, `advance_record_state`
    state-machine validator
- `src/ohbm2026/fetch_stage.py`
  - **Stage 1 orchestrator**. Entry point for
    `ohbmcli fetch-abstracts` and `ohbmcli fetch-withdrawn`.
    Drives: introspection → schema diff (HARD / SOFT /
    INFORMATIONAL) → checkpoint lifecycle → batched fetch →
    atomic-write corpus + schema + provenance → delete checkpoint
    on success. The canonical reference for the per-stage
    contract (see [docs/per-stage-pattern.md](docs/per-stage-pattern.md))
- `src/ohbm2026/schema_diff.py`
  - tiered field-level schema-drift classifier
    (HARD / SOFT / INFORMATIONAL); pure functions, no I/O
- `src/ohbm2026/exceptions.py`
  - typed cross-stage exception hierarchy rooted at
    `OhbmStageError(RuntimeError)`. Stage 1: `Stage1Error` →
    `SchemaContractError`, `CheckpointError`, `FigureFailureError`.
    Stage 2: `Stage2Error` → `EnrichmentError`, `CacheVersionError`,
    `ComponentFailureThresholdError`. `ProvenanceError` shared.
    Re-exports `GraphQLAPIError`.
- `src/ohbm2026/artifacts.py`
  - shared path helpers (`build_schema_artifact_path`,
    `build_provenance_path`, `build_fetch_checkpoint_path`,
    `build_enrich_provenance_path`, `build_enrich_cache_path`,
    `PRIMARY_ABSTRACTS_PATH`, `PRIMARY_WITHDRAWN_ABSTRACTS_PATH`,
    `PRIMARY_ENRICHED_CORPUS_PATH`), state-key derivation
- `src/ohbm2026/enrich_stage.py`
  - **Stage 2 orchestrator**. Entry point for
    `ohbmcli enrich-abstracts`. Drives: backend discovery →
    per-abstract figures + claims + references with per-component
    caching → atomic SQLite + zlib write → provenance write → optional
    Parquet export. The multi-component reference for the per-stage
    contract (see [docs/per-stage-pattern.md](docs/per-stage-pattern.md)).
- `src/ohbm2026/enrich_storage.py`
  - SQLite + zlib I/O helper for Stage 2: `EnrichedCorpusWriter`
    (atomic temp→rename), `read_one_by_id`, `iter_enriched`,
    `corpus_metadata`. Stdlib only.
- `src/ohbm2026/enrichment.py`
  - markdown conversion, figure analysis, claim extraction building
    blocks (wrapped by `enrich_stage.py`)
- `src/ohbm2026/openalex.py`
  - reference parsing and OpenAlex matching (wrapped by
    `enrich_stage.py`'s references component)
- `src/ohbm2026/neuroscape.py`
  - embeddings, stage-2 paths, semantic analysis, clustering, projections
- `src/ohbm2026/ui_data/`
  - Stage 6 static-JSON data-package builders (per-shard envelopes + cross-shard invariants + state-key discovery + reference link-check); CLI entry at `scripts/build_ui_data.py`. Consumed by the SvelteKit site under `site/`.
- `src/ohbm2026/cli.py`
  - unified CLI entrypoint

## Main Outputs By Stage

- Stage 1 — raw ingest
  - `data/primary/abstracts.json` (accepted corpus)
  - `data/primary/abstracts_withdrawn.json` (withdrawn corpus, separate file)
  - `data/primary/authors.json` (authors for the accepted corpus, fetched inline)
  - `data/primary/authors_withdrawn.json` (authors for the withdrawn corpus)
  - `data/primary/assets/` (downloaded methods/results figure images)
  - `data/inputs/abstracts_graphql_schema__<state-key>.json` (persisted upstream schema)
  - `data/provenance/abstracts_fetch_provenance__<state-key>.json` (provenance record)
  - `data/cache/fetch_abstracts/checkpoint__<state-key>.json` (resume checkpoint; deleted on success)
- Stage 2 — enriched corpus
  - `data/primary/abstracts_enriched.sqlite` (SQLite + zlib(json) per row; canonical)
  - `data/provenance/abstracts_enrich_provenance__<state-key>.json` (per-component model identifiers + cache hit/miss counts)
  - `data/cache/figure_analysis/<cache-key>.json` (per-figure interpretations)
  - `data/cache/claim_analysis/<cache-key>.json` (per-abstract claim lists)
  - `data/cache/reference_metadata/<cache-key>.json` (per-reference resolutions)
  - optional `data/primary/abstracts_enriched.parquet` (via `--export-parquet`)
- manual and operator inputs
  - `data/inputs/abstracts_with_phenomena_with_theories_refined.csv`
  - `data/inputs/poster_layout/layout_assets/`
- audit outputs
  - `data/outputs/experiments/title_audit/title_modifications.json`
- embeddings and clustering
  - `data/outputs/experiments/embeddings/*`
- static site
  - `data/outputs/exported-sites/ui-site__<state-key>/`
  - optional publish mirror at `export/ui-site/`

## Validation

Default validation command:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

If an agent is taking over this repo, this should be the first command after
setting up the environment.
