# Quickstart — Stage 12 (book layout polish + permalink UX)

Operator runbook for the Stage 12 changes. Continuation of Stage 11.1's quickstart at `specs/012-stage11-followups/quickstart.md`.

## Prerequisites

- Stage 11.1 already shipped (`ohbmcli book --format pdf` works against the real corpus).
- The repository `.venv` exists; `uv pip install --python .venv/bin/python ".[abstracts_book]"` has been re-run after this PR lands (no actual dep changes, but a re-run confirms environment freshness).
- For the site work: `pnpm install` in `site/` already up-to-date.

## 1 — Book PDF with the new defaults (figure normalisation + 3-col TOC + bucketed index + tight margins)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format pdf --sort poster_id
```

Expected diffs vs the Stage 11.1 build (same corpus + chunk cache):

| Metric | Stage 11.1 | Stage 12 (this) | Notes |
|---|---|---|---|
| `book.pdf` total pages | 15,660 | ≥ 15% fewer | SC-005 (tight margins) |
| TOC pages | ~200+ (pandoc default) | ≤ 50% of prior | SC-003 (3-col `longtable`) |
| `fig_assets/` total bytes | mixed PNG/JPEG | ≥ 30% smaller | SC-002 (q=90 JPEG + cap) |
| Author-index navigability | flat 60+ pages | letter-bucketed | SC-004 |
| `provenance.figures_normalised_count` | absent | populated | new field |
| `provenance.figures_normalised_with_fallback[]` | absent | populated (probably empty list) | new field |
| `provenance.toc_page_count` | absent | populated | new field |

Cache impact: the per-abstract chunk cache from Stage 11.1 still works — `tight` is the new default and changes the header-includes file's hash, so every chunk re-renders once on the first Stage-12 build. Subsequent runs with the same flag hit the cache.

## 2 — Recovering the pre-Stage-12 layout

If you need to reproduce an archived Stage 11.1-style book for comparison:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
    --format pdf --sort poster_id --margins=loose
```

`--margins=loose` loads `header-includes-loose.tex` which omits the `geometry` import and recovers the LaTeX `book` class ~1 in margins. The figure normalisation, 3-col TOC, and author-index buckets are NOT recoverable through a flag — they're always-on after Stage 12 lands (the operator-facing behaviour the user explicitly asked for).

## 3 — Site permalink-page UX

The brief-preview affordances are live on every per-abstract permalink page (`/abstract/<poster_id>/`) after the next site deploy. To verify locally:

```bash
cd site
pnpm dev
# Open http://localhost:5173/abstract/0042/ (or any accepted poster_id)
```

Expected behaviour:
- Five verbatim sections (Introduction, Methods, Results, Conclusion, Acknowledgments) open in a 3-line CSS `line-clamp` preview.
- Each section's "Show more" button (bottom right of the section, when text length ≥ 280 chars) expands that section + relabels to "Show less".
- A column-scoped "Show all" button at the top of the left column expands every section at once + relabels to "Collapse all". Clicking it again returns every section to the clamp.
- The Acknowledgments section is absent when the corpus record's `Acknowledgement` response is empty.
- Navigating to a different permalink page resets every section to the clamp (state is per-page).

The in-grid drawer (`+page.svelte` browse grid → click an abstract → side drawer opens) is UNCHANGED. No new sections; no clamp; no toggles.

## 4 — Debugging an individual abstract's normalised figures

```bash
ls -la data/outputs/book/book__*/fig_assets/ | head
```

Every file should have a `.jpg` extension and dimensions ≤ 975 px wide. Files in `provenance.figures_normalised_with_fallback[]` keep their original extensions (`.png`, `.gif`, etc.) — those are the byte-copy fallbacks.

To force a re-normalise (cache the new defaults):

```bash
# Clear the staging dir; the per-abstract PDF cache stays warm.
rm -rf data/outputs/book/.staging__*
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format pdf
```

## 5 — Common errors

| You see | What it means | What to do |
|---|---|---|
| `figures_normalised_with_fallback` is non-empty after a fresh run | Pillow couldn't open one or more source figures. | Inspect the listed filenames; usually a truncated download from Stage 1. Re-running `ohbmcli refresh-assets` for the affected submission ids fixes the source. |
| TOC longtable spans far more pages than `front_matter_pages` | The corpus has more abstracts than the cache-warm assertion expected. | Expected after a corpus refresh; the TOC is content-driven. |
| Author index shows `## Other` with unexpected entries | Names whose last-name initial wasn't an A–Z letter after Unicode-fold. | Spot-check via `grep '"display_name"' data/primary/authors.json | head`; usually legitimate edge cases (numeric prefixes, glyph-only names). |
| `--margins=tight` produces fewer than 15% page reduction | The corpus changed (more figures pushing past auto-scale boundaries) OR Pillow couldn't resize some figures. | Check `provenance.figures_normalised_with_fallback`; if empty and pages didn't drop, this is a real regression and worth a follow-up. |

## 6 — Re-deploy

The data-package parquet needs a rebuild to pick up the new `sections.acknowledgments` field:

```bash
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
    --corpus data/primary/abstracts.json \
    --withdrawn data/primary/abstracts_withdrawn.json \
    --authors data/primary/authors.json \
    --enriched data/primary/abstracts_enriched.sqlite \
    --analysis-root data/outputs/analysis \
    --discover-rollup \
    --minilm-root data/outputs/embeddings/minilm \
    --output site/static/data \
    --output-format parquet-single
```

Then drag-replace `data.parquet` on Dropbox (existing share URL) + bump `OHBM2026_UI_DATA_PACKAGE_SHA256` repo variable to the new digest. Merge the Stage-12 PR with the `deploy-production` label and the new site bundle picks up:
- The new `sections.acknowledgments` field via `loader.ts` (no decoder change needed — pyarrow STRUCT auto-extension).
- The permalink page's brief-preview + show-more UX via the SvelteKit bundle.
- The in-grid drawer behaviour is unchanged (explicit non-regression target).
