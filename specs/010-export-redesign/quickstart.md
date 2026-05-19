# Quickstart — Data export redesign (Stage 10)

Two flows live in this stage: **running the bench** (Phase 0, mandatory before any format-conditional design lands) and **rebuilding the redesigned export** once the format is chosen (post-bench). Both run from repo root through `.venv/bin/python`.

## Prerequisites

- The Stage 1–4 pipeline outputs are present locally: `data/primary/abstracts.json`, `data/primary/abstracts_enriched.sqlite`, `data/outputs/analysis/annotations__<state-key>.{sqlite,parquet}`, `data/outputs/embeddings/...`.
- `pnpm install` has been run in `site/`.
- A local copy of the production data tarball or `site/static/data/` populated by `scripts/build_ui_data.py` — needed as the BASELINE against which bench candidates are compared.

## 1. Run the bench (Phase 0)

```bash
# Install candidate-format deps in the venv (one-time).
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python \
    pyarrow duckdb apache-arrow

# Install JS-side decoder deps.
cd site && pnpm add --save-dev hyparquet @sqlite.org/sqlite-wasm @duckdb/duckdb-wasm apache-arrow && cd ..

# Build all six candidates from the same corpus.
PYTHONPATH=src .venv/bin/python scripts/format_bench/build_all_candidates.py \
    --output-root bench/

# Run the four scripted measurements.
PYTHONPATH=src .venv/bin/python scripts/format_bench/measure_size.py            --bench-root bench/
PYTHONPATH=src .venv/bin/python scripts/format_bench/measure_tti.py             --bench-root bench/  # uses Playwright
PYTHONPATH=src .venv/bin/python scripts/format_bench/measure_session_bytes.py   --bench-root bench/
PYTHONPATH=src .venv/bin/python scripts/format_bench/measure_decoder_bundle.py  --bench-root bench/

# Render the populated decision table into research.md.
PYTHONPATH=src .venv/bin/python scripts/format_bench/render_decision_table.py \
    --bench-root bench/ --research-md specs/010-export-redesign/research.md
```

Then run the architect-agent review (Agent tool with the populated table in its prompt — see the spec FR-209). The agent's report + the maintainer's responses go into `research.md` § B2. The committed format choice goes into § B3.

## 2. Rebuild the redesigned export (post-bench)

After the format is chosen, `--output-format` is the only flag that changes between rebuilds:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
    --corpus    data/primary/abstracts.json \
    --withdrawn data/primary/abstracts_withdrawn.json \
    --authors   data/primary/authors.json \
    --enriched  data/primary/abstracts_enriched.sqlite \
    --analysis-root data/outputs/analysis \
    --discover-rollup \
    --output-format <chosen-format> \
    --output    site/static/data
```

Where `<chosen-format>` is one of `gzip-json-shards | parquet-files | parquet-duckdb | sqlite-single-file | duckdb-single-file | arrow-ipc` (matching `manifest.format`).

## 3. Validate

```bash
# LinkML schema validation.
scripts/validate_ui_data.sh

# Lint: zero un-justified `range: Any` in the schema.
PYTHONPATH=src .venv/bin/python scripts/format_bench/lint_schema.py \
    specs/010-export-redesign/contracts/shards.linkml.yaml

# Run the existing Playwright e2e suite at the new format.
cd site && OHBM2026_LOCAL_TARBALL=/path/to/redesigned-export \
    UI_DATA_AVAILABLE=1 pnpm exec playwright test --project=chromium
```

`scripts/validate_ui_data.sh` extends Stage-6's validator with the new schema; `lint_schema.py` enforces FR-201 (zero un-justified `range: Any`).

## 4. Refresh the deployed data package

Same Dropbox-share-link inode-preservation recipe as Stage 6:

```bash
# Tar / pack the redesigned export. The exact recipe depends on the chosen format.
# For tarball candidates (e.g. gzip-json-shards):
tar -czf ~/MIT\ Dropbox/.../ohbm2026/ui-data.tar.gz -C site/static data

# For single-file containers (sqlite-single-file, duckdb-single-file):
cp site/static/data/main.<ext> ~/MIT\ Dropbox/.../ohbm2026/ui-data.<ext>

# Update the sha256 repo variable so CI verifies the new bytes.
NEW_SHA=$(shasum -a 256 ~/MIT\ Dropbox/.../ohbm2026/ui-data.<ext> | awk '{print $1}')
gh variable set OHBM2026_UI_DATA_PACKAGE_SHA256 --body "$NEW_SHA"

# If the file extension changed (e.g. .tar.gz → .sqlite), the URL repo
# variable updates too:
gh variable set OHBM2026_UI_DATA_PACKAGE_URL --body "<new dropbox shared link>"
```

Next PR-preview deploy fetches + sha256-verifies the new package.

## 5. Smoke the deployed export

After the deploy workflow runs:

```bash
# Pull the latest tarball / file size for sanity.
curl -sI "$(gh variable get OHBM2026_UI_DATA_PACKAGE_URL)" | head -5

# Visit the PR preview and walk through home → search → open one abstract → about.
open https://abstractatlas.brainkb.org/pr-<N>/ohbm2026/
```

Smoke includes the same five-step session the bench measured (FR-205 lazy-load test). If session bytes or TTI regress vs the bench's measured numbers, dig in before merging.

## What success looks like

- Bench's decision table has six populated rows + a committed format choice in `research.md` § B3.
- `scripts/validate_ui_data.sh` reports 68/68 PASS against the redesigned export.
- `lint_schema.py` confirms zero un-justified `range: Any`.
- All 26 existing Playwright e2e cases pass with no per-spec edits.
- Lighthouse-CI on the next PR shows FCP + LCP each improved by ≥ 10 % vs the Stage-6 baseline.
- Adding a second-conference's data to the deployed tree (via a follow-up tarball / file) does not touch any OHBM 2026 byte (verified by sha256).
