# Phase 1 — Quickstart (Stage 5 Package Reorganization)

This stage is a refactor with no new user-facing CLI commands. The "quickstart" is the **verification recipe** for each user story.

## Prereqs

```bash
# venv-only Python (Principle I)
UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv

# Stage 4 outputs must exist on disk for the post-US3 smoke (corpus_state_key=f0c51e80dc0e)
ls data/outputs/analysis/annotations__f0c51e80dc0e.{parquet,sqlite}
```

## US1 verification — enrichment cleanup

### 1. Pre-stage baseline capture

Run **before** the cleanup so post-stage comparisons are honest:

```bash
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
# Expect: Ran 583 tests / 1 pre-existing failure (test_plot_poster_layout_floorplan)

# Capture the pre-stage figure-analysis cache_key for abstract id 1 (or any pinned id)
ls data/cache/figure_analysis/ | head -3
# Pick one .json; save its filename for post-stage comparison
```

### 2. Apply US1

Implementation guidance is in `tasks.md` (Phase 2). The mechanical steps:

```bash
# 1. Create the four new submodules with their owned symbols
$EDITOR src/ohbm2026/enrich/text.py
$EDITOR src/ohbm2026/enrich/cache_paths.py
$EDITOR src/ohbm2026/enrich/markdown_render.py
$EDITOR src/ohbm2026/enrich/openai_compat.py

# 2. Rewire each importer (the 7 known sites)
$EDITOR src/ohbm2026/enrich/claims.py
$EDITOR src/ohbm2026/enrich/stage.py
$EDITOR src/ohbm2026/enrich/openalex.py
$EDITOR src/ohbm2026/embed/components.py
$EDITOR src/ohbm2026/ui.py                              # will be touched again in US3
$EDITOR scripts/reference_split_regression_probe.py

# 3. Delete the legacy artifacts
git rm src/ohbm2026/enrichment.py
git rm tests/test_enrichment.py
git rm scripts/time_figure_enrichment.py

# 4. Verify the contract
grep -rE "from ohbm2026 import enrichment|from ohbm2026\.enrichment" src/ tests/ scripts/
# Expect: zero matches

# 5. Run the unit suite
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
# Expect: Ran (583 − N) tests / 1 pre-existing failure
# (N = test count of the deleted test_enrichment.py)
```

### 3. Smoke (SC-005)

```bash
# The cache_key for abstract id 1 must be unchanged post-cleanup
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich-abstracts --limit 1 --invalidate figures 2>&1 | grep cache_key
# Expect: the same cache_key that was on disk pre-stage
```

### 4. Commit

```bash
git add src/ohbm2026/enrich/ src/ohbm2026/enrichment.py src/ohbm2026/embed/components.py src/ohbm2026/ui.py scripts/reference_split_regression_probe.py tests/test_enrichment.py scripts/time_figure_enrichment.py
git commit -m "refactor(stage5): collapse enrichment.py into enrich/ submodules (US1)"
```

## US2 verification — layout park

### 1. Apply US2

```bash
# Move the three modules
mkdir -p src/ohbm2026/layout
git mv src/ohbm2026/poster_layout.py     src/ohbm2026/layout/
git mv src/ohbm2026/poster_sequencing.py src/ohbm2026/layout/
git mv src/ohbm2026/nocd_experiments.py  src/ohbm2026/layout/

# Add the parking docstring
cat > src/ohbm2026/layout/__init__.py <<'EOF'
"""Parked package — poster-layout / sequencing / NOCD code preserved from
the pre-Stage-5 surface. Not actively maintained. Revive when a new
organizer cycle needs poster work; see specs/007-package-reorg/spec.md FR-003.
"""
EOF

# Update poster_sequencing.py's internal import
sed -i '' 's|from ohbm2026.poster_layout|from ohbm2026.layout.poster_layout|g' src/ohbm2026/layout/poster_sequencing.py

# Move the 15 scripts
mkdir -p scripts/layout
git mv scripts/analyze_poster_layout.py                 scripts/layout/
git mv scripts/benchmark_poster_sequencing.py           scripts/layout/
git mv scripts/build_layout_review_hub.py               scripts/layout/
git mv scripts/check_layout_review.py                   scripts/layout/
git mv scripts/compare_poster_layout_proposals.py       scripts/layout/
git mv scripts/extract_layout_geometry.py               scripts/layout/
git mv scripts/generate_semantic_layout_proposals.py    scripts/layout/
git mv scripts/generate_target_poster_layout_proposals.py scripts/layout/
git mv scripts/optimize_poster_layout.py                scripts/layout/
git mv scripts/plot_poster_layout_day_comparison.py     scripts/layout/
git mv scripts/plot_poster_layout_floorplan.py          scripts/layout/
git mv scripts/run_nocd_checkpoint_sweep_experiment.py  scripts/layout/
git mv scripts/run_nocd_classic_predict_experiment.py   scripts/layout/
git mv scripts/write_layout_category_summaries.py       scripts/layout/
git mv scripts/write_layout_reassignment_summaries.py   scripts/layout/

# Fix each script's path-resolution (parents[1] → parents[2])
# (do this one script at a time; pattern depends on each script's specific layout)

# Rewire test imports
$EDITOR tests/test_nocd_experiments.py
$EDITOR tests/test_poster_sequencing.py
$EDITOR tests/test_plot_poster_layout_floorplan.py
```

### 2. Verify

```bash
# No leftover legacy references
grep -rE "from ohbm2026 import (poster_layout|poster_sequencing|nocd_experiments)|from ohbm2026\.(poster_layout|poster_sequencing|nocd_experiments)" src/ tests/ scripts/
# Expect: zero matches

# Scripts still import cleanly
PYTHONPATH=src .venv/bin/python scripts/layout/optimize_poster_layout.py --help >/dev/null
PYTHONPATH=src .venv/bin/python scripts/layout/benchmark_poster_sequencing.py --help >/dev/null
PYTHONPATH=src .venv/bin/python scripts/layout/run_nocd_classic_predict_experiment.py --help >/dev/null

# Unit suite still at baseline (minus the test_enrichment.py removed in US1)
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
```

### 3. Docs note (SC-007)

```bash
# Update CLAUDE.md, README.md, docs/reproducibility-vision.md with the parking note
$EDITOR CLAUDE.md README.md docs/reproducibility-vision.md

# Verify
grep -l "layout.*parked\|parked.*layout" CLAUDE.md README.md docs/reproducibility-vision.md
# Expect: three filenames
```

### 4. Commit

```bash
git add -A
git commit -m "refactor(stage5): park poster-layout / sequencing / NOCD under layout/ (US2)"
```

## US3 verification — UI split

### 1. Capture a pre-stage UI bundle for shape comparison

```bash
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui \
  --raw-input data/primary/abstracts.json \
  --enriched-input data/primary/abstracts_enriched.sqlite \
  --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite \
  --analysis-root data/outputs/analysis \
  --output-dir /tmp/ui-pre-stage5

# Save the file list for post-stage diff
ls /tmp/ui-pre-stage5 | sort > /tmp/ui-pre-stage5.filelist
```

### 2. Apply US3

```bash
# Create the package + 7 submodules; move symbols per data-model.md §3
mkdir -p src/ohbm2026/ui
$EDITOR src/ohbm2026/ui/__init__.py            # docstring only
$EDITOR src/ohbm2026/ui/text.py
$EDITOR src/ohbm2026/ui/figures.py
$EDITOR src/ohbm2026/ui/references.py
$EDITOR src/ohbm2026/ui/manifest.py
$EDITOR src/ohbm2026/ui/payload_legacy.py
$EDITOR src/ohbm2026/ui/payload_stage4.py
$EDITOR src/ohbm2026/ui/cli.py

# Move UIBuildError to ohbm2026.exceptions
$EDITOR src/ohbm2026/exceptions.py

# Rewire CLI dispatch
$EDITOR src/ohbm2026/cli.py

# Rewire test imports
$EDITOR tests/test_ui.py
$EDITOR tests/test_ui_export.py

# Delete the legacy file
git rm src/ohbm2026/ui.py
```

### 3. Verify

```bash
# CLI works
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli export-ui --help >/dev/null
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui --help >/dev/null

# No leftover top-level imports
grep -rE "^import ohbm2026.ui\b|^from ohbm2026 import ui\b" src/ tests/ scripts/
# Expect: zero matches

# Unit suite still at baseline
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
```

### 4. Smoke (SC-006)

```bash
# Build a post-stage bundle; diff the file list
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui \
  --raw-input data/primary/abstracts.json \
  --enriched-input data/primary/abstracts_enriched.sqlite \
  --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite \
  --analysis-root data/outputs/analysis \
  --output-dir /tmp/ui-post-stage5

ls /tmp/ui-post-stage5 | sort > /tmp/ui-post-stage5.filelist
diff /tmp/ui-pre-stage5.filelist /tmp/ui-post-stage5.filelist
# Expect: empty diff (same file list)

# manifest equivalence
diff <(jq -S 'del(.timestamp,.code_revision)' /tmp/ui-pre-stage5/manifest.json) \
     <(jq -S 'del(.timestamp,.code_revision)' /tmp/ui-post-stage5/manifest.json)
# Expect: empty diff (manifest content is identical modulo timestamp + git rev)
```

### 5. Commit

```bash
git add -A
git commit -m "refactor(stage5): split ui.py into ui/ package (US3)"
```

## Full-stage final verification (SC-001..SC-007)

```bash
# SC-001 — no legacy top-level modules
git ls-files src/ohbm2026/enrichment.py src/ohbm2026/ui.py src/ohbm2026/poster_layout.py src/ohbm2026/poster_sequencing.py src/ohbm2026/nocd_experiments.py
# Expect: empty output

# SC-002 — each new package has a minimal __init__.py
wc -l src/ohbm2026/enrich/__init__.py src/ohbm2026/ui/__init__.py src/ohbm2026/layout/__init__.py
# Expect: each ≤ 5 lines

# SC-003 — no banned imports
grep -rE "from ohbm2026 import (enrichment|poster_layout|poster_sequencing|nocd_experiments)|from ohbm2026\.(enrichment|poster_layout|poster_sequencing|nocd_experiments)" src/ tests/ scripts/
# Expect: empty output

# SC-004 — unit suite green (modulo the pre-existing failure)
KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
# Expect: (583 − N) passing, 1 pre-existing failure

# SC-005 — figure cache_key idempotent (verified inline in US1 step 3)

# SC-006 — UI bundle shape-equivalent (verified in US3 step 4)

# SC-007 — parking note present in all three docs
grep -l "layout.*parked\|parked.*layout" CLAUDE.md README.md docs/reproducibility-vision.md | wc -l
# Expect: 3
```
