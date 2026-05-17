# Phase 1 — Quickstart (Stage 6 UI Rewrite)

End-to-end recipes for local development, build verification, and deployment.

## Prerequisites

```bash
# Python side (build the data package)
UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e ".[ui,enrich]"

# Node side (build + serve the site)
corepack enable
corepack prepare pnpm@9 --activate
cd site && pnpm install
```

Stage 1–4 outputs must exist on disk:

- `data/primary/abstracts.json` (3,244 accepted records)
- `data/primary/authors.json`
- `data/primary/abstracts_enriched.sqlite`
- `data/primary/reference_metadata.json`
- `data/outputs/analysis/annotations__f0c51e80dc0e.sqlite` (Stage 4 rollup)
- `data/outputs/analysis/` (per-bundle topics.json files)
- `data/outputs/embeddings/minilm/title__f0c51e80dc0e/` (Stage 3 MiniLM bundle for corpus-vector quantization)

## Local development loop

```bash
# 1. Build the data package once (data/ inputs → site/static/data/ shards).
# The state-key is discovered at build time via `ohbm2026.ui_data.state_key`; the
# hardcoded value below is only convenient for local one-offs.
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
  --corpus data/primary/abstracts.json \
  --withdrawn data/primary/abstracts_withdrawn.json \
  --authors data/primary/authors.json \
  --enriched data/primary/abstracts_enriched.sqlite \
  --references data/primary/reference_metadata.json \
  --rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite \
  --analysis-root data/outputs/analysis \
  --minilm-bundle data/outputs/embeddings/minilm/title__f0c51e80dc0e \
  --references-yaml specs/008-ui-rewrite/contracts/references.yaml \
  --output site/static/data/

# Alternative: let the builder discover the latest rollup state-key automatically
# (this is what CI runs):
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
  --corpus data/primary/abstracts.json \
  --withdrawn data/primary/abstracts_withdrawn.json \
  --authors data/primary/authors.json \
  --enriched data/primary/abstracts_enriched.sqlite \
  --references data/primary/reference_metadata.json \
  --analysis-root data/outputs/analysis \
  --discover-rollup \
  --minilm-bundle "$(PYTHONPATH=src .venv/bin/python -m ohbm2026.ui_data.state_key minilm data/outputs/embeddings/minilm title)" \
  --references-yaml specs/008-ui-rewrite/contracts/references.yaml \
  --output site/static/data/

# 2. Serve the site with hot-reload (Vite dev server)
cd site && pnpm dev   # opens http://localhost:5173
```

Hot-reload picks up edits to `site/src/**`. Editing the data package requires re-running step 1.

## Build verification

```bash
# Python unit tests (data-package builders + link checker)
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p "test_ui_data*" 2>&1 | tail -3

# Site unit tests
cd site && pnpm test:unit -- --run

# Site end-to-end tests (Playwright headless)
cd site && pnpm test:e2e --reporter=line

# Production build (static-adapter output)
cd site && pnpm build  # → site/build/

# Local preview of the production build
cd site && pnpm preview   # serves site/build/ at http://localhost:4173
```

## US1 smoke (first-paint verification)

After running the site locally:

```bash
# Open http://localhost:5173 in a fresh tab.
# Expected:
# - Search bar visible within 3s (SC-001).
# - Type "connectivity" → results appear within 500ms (SC-002).
# - Click a result → detail panel opens with poster_id as header (NOT submission_id).
# - Author list visible with affiliations (FR-003).
# - Check Network tab: no shard contains a `accepted_for == "Withdrawn"` record.
# - Resize browser to 360x640 — confirm no horizontal scroll on home + detail (SC-004 minimum).
# - Confirm the footer "build info" affordance renders the short SHA (FR-022 / SC-011).
```

## US2 smoke (2D UMAP + lasso + model switch)

```bash
# Click "Map" tab → 2D UMAP loads (Plotly bundle lazy-loaded; check Network).
# Drag a lasso around a cluster of ~100 points.
# Expected:
# - Result list filters to lasso selection within 500ms (US2 acceptance #1).
# - Facet counts update to reflect the intersection.
# - Clear lasso → full corpus restored.
# Switch model dropdown from "neuroscape × abstract" to "voyage × claims".
# - UMAP coordinates change.
# - Lasso selection (by abstract id) persists across the switch (US2 acceptance #2).
```

## US3 smoke (search + typo tolerance)

```bash
# Type "defautl mode netwrk" (2 typos).
# Expected: "default mode network" abstracts surface in the lexical results (US3 acceptance #1).
# Type "Smtih" in the author-search subfield.
# Expected: abstracts by "Smith" appear (US3 acceptance #3).
# Type "how the brain remembers faces" (no verbatim match).
# Expected: face-memory abstracts surface via semantic search (US3 acceptance — semantic-only path).
```

## US4 smoke (interactive facets)

```bash
# Click "Methods = fMRI" in the facet sidebar.
# Expected:
# - Result list shrinks to fMRI abstracts (~1,840 of 3,244).
# - "Species" facet now shows only species that appear in fMRI abstracts.
# - "Brain Regions" + "Brain Networks" + other facets all recount accordingly.
# Lasso a region while the facet is active.
# - Result list = (lasso) ∩ (facet); facet counts reflect the intersection.
```

## US5 smoke (cart + email)

```bash
# Click "add to list" on 3 abstracts from different facet-filtered views.
# Expected:
# - Cart badge shows "3".
# - Reload page → badge still shows "3" (localStorage persistence).
# Click "email my list".
# Expected: OS mail composer opens with:
#   Subject: "OHBM 2026 — my abstracts (3)"
#   Body: 3 lines, each with poster_id + title + permalink to /abstract/<poster_id>.
# Click "clear cart" → badge resets; localStorage cleared.
```

## US6 smoke (walkthrough)

```bash
# Open the site in an incognito window.
# Expected: "Take the tour" CTA visible in the header; no modal auto-opens.
# Click "Take the tour".
# - Tour runs through 5+ stops: search bar, model selector, UMAP, facets, cart.
# - Each step has next/previous/skip controls.
# - Tour can be re-launched anytime from the "?" affordance.
# Reload the page after dismissing the tour.
# - Tour does NOT auto-launch again.
```

## US7 smoke (About page + link health)

```bash
# Navigate to /about.
# Expected:
# - Top-of-page overview is ≤ 250 words (US7 acceptance #1).
# - Each collapsible deep-dive (Stages 1–4 + topics + UMAP) has clickable references.
# - Click any reference link → opens in a new tab (target=_blank, rel=noopener).
# Run the link checker locally before the build:
PYTHONPATH=src .venv/bin/python -m ohbm2026.ui_data.link_check \
  specs/008-ui-rewrite/contracts/references.yaml
# Expected: exit 0; "All references reachable: N URLs"
# If any URL is dead, the build fails (SC-007).
```

## US8 smoke (deploy + PR previews)

US8 is the **first** Stage 6 PR (per Session-2026-05-17 sequencing). After it lands on `main`, every subsequent PR gets a live preview surfaced in the PR's **Deployments box** at the top of the PR (NOT as a bot comment in the conversation).

```bash
# === First-PR verification (US8 itself) ===
# Open a small PR containing only the workflows + the placeholder route
# (the "Stage 6 — under construction" page).
# Expected within 10 minutes:
# - The PR's "Deployments" box appears AT THE TOP of the PR (above the file
#   diff, below the description). NOT in the conversation as a comment.
# - The box shows: "pr-preview-<N> — Active" with a "View deployment" button.
# - Clicking "View deployment" loads https://<org>.github.io/<repo>/pr-<N>/
#   and the placeholder page renders the manifest build_info.
# Push another commit to the same PR.
# - The SAME Deployments environment ("pr-preview-<N>") updates in place
#   (GitHub does NOT create a new environment per push).
# - No bot comment churn anywhere in the conversation.
# Close the PR (merge or reject).
# - Within 30 min: the preview directory is removed from gh-pages AND the
#   Deployments box marks "pr-preview-<N>" as "Inactive".
# - Visiting the preview URL returns 404.
# Merge US8 to main.
# - Production deploy runs; canonical GitHub Pages URL updates within 10 min.

# === Subsequent-PR verification (US1–US7) ===
# Open any PR touching site/ or src/ohbm2026/ui_data/.
# Expected within 10 minutes:
# - Same Deployments-box flow: top-of-PR "View deployment" link to the
#   per-PR subdirectory; updates in place on subsequent commits; marks
#   "Inactive" 30 min after PR close.
# - Preview directories from other open PRs are untouched.
# - Production deploys on merge to main only.
```

**Sanity check**: if you ever see a `peter-evans/find-comment` step in `.github/workflows/pr-preview.yml`, that's wrong — the contract uses the Deployments API surface (auto-populated from the workflow's `environment:` declaration), not a bot comment. Restore from `contracts/github-action.md`.

## Common operations

### Clean rebuild (force fresh data package)

```bash
rm -rf site/static/data/
# ...then re-run the build command above.
```

### Verify the accepted-only invariant

```bash
PYTHONPATH=src .venv/bin/python -c "
import json
with open('site/static/data/abstracts.json') as f:
    abstracts = json.load(f)
withdrawn = [a for a in abstracts if a.get('accepted_for') == 'Withdrawn']
print(f'Withdrawn rows in abstracts.json: {len(withdrawn)}')
assert len(withdrawn) == 0, 'INVARIANT VIOLATION: withdrawn record found'
"
# Expected: 0 (any non-zero aborts the deploy)
```

### Update reference YAML before deploy

```bash
# Edit the references list:
$EDITOR specs/008-ui-rewrite/contracts/references.yaml

# Validate before push:
PYTHONPATH=src .venv/bin/python -m ohbm2026.ui_data.link_check \
  specs/008-ui-rewrite/contracts/references.yaml
```

### Inspect bundle sizes

```bash
cd site && pnpm build
du -sh site/build/* | sort -h
du -sh site/static/data/* | sort -h
gzip -k site/static/data/abstracts.json && du -h site/static/data/abstracts.json.gz
```

Expected: total of `site/static/data/` ≤ 11 MB raw (≤ 8 MB gz first-paint per SC-006).
