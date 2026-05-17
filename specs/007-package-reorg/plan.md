# Implementation Plan: Stage 5 — Package Reorganization & Enrichment Cleanup

**Branch**: `007-package-reorg` (to be cut from `main` after PR #7 lands, OR from `006-analysis-annotation` if Stage 5 starts in parallel) | **Date**: 2026-05-16 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-package-reorg/spec.md`

## Summary

Three independent, sequence-able structural cleanups, each shippable as its own commit series:

1. **US1 (P1)** — Delete `src/ohbm2026/enrichment.py` (1,300 LOC, 62 def/class top-level symbols, 7 importers across `enrich/claims.py`, `enrich/stage.py`, `enrich/openalex.py`, `embed/components.py`, `ui.py`, and two scripts). Redistribute its **still-used** helpers into focused `enrich/` submodules: `enrich/text.py` (HTML↔Markdown + content-question normalization), `enrich/cache_paths.py` (default cache path helpers + JSON load/write), `enrich/markdown_render.py` (manuscript/claim/figure-analysis markdown builders), `enrich/openai_compat.py` (the leftover OpenAI/Ollama low-level helpers that the agentic Stage 2.1 runners still call). Delete the **22 unused symbols** outright. Leave `EnrichmentError` at `ohbm2026.exceptions.EnrichmentError` (its current authoritative location) — `enrichment.py`'s local re-declaration is removed.

2. **US2 (P2)** — Move `poster_layout.py` + `poster_sequencing.py` + `nocd_experiments.py` to `src/ohbm2026/layout/`; relocate 15 scripts in `scripts/{benchmark_poster_sequencing.py, build_layout_review_hub.py, …}` to `scripts/layout/`. Mark `layout/` parked in CLAUDE.md, README.md, and `docs/reproducibility-vision.md`.

3. **US3 (P3)** — Split `src/ohbm2026/ui.py` (1,361 LOC) into a `ui/` package. Submodule layout: `ui/text.py` (markdown/HTML helpers), `ui/figures.py` (image-analysis ordering + figure-note builders), `ui/references.py` (reference + neighbor loaders), `ui/payload_legacy.py` (the embedding-bundle-driven build path), `ui/payload_stage4.py` (the new rollup-driven path, `build_ui_payload_from_stage4`), `ui/cli.py` (`export_ui_main` + `build_ui_main` argument parsers + dispatch), `ui/manifest.py` (manifest assembly + atomic writes). `ui/__init__.py` carries only a docstring — no re-export shell.

The approach is mechanical: identify each symbol's new home from the consumer fan-out (already enumerated in research.md), do the move in one commit per package, then rewrite the import sites. The Stage 4 reorganization (Q2 / T108b in spec 006) established the no-shim pattern; this stage applies it three more times.

## Technical Context

**Language/Version**: Python 3.14 (`.venv/bin/python`, installed via `uv venv --python 3.14`).
**Primary Dependencies**: No new dependencies added or removed. Existing surface (`openai`, `numpy`, `spacy`, `umap-learn`, `faiss-cpu`, `leidenalg`, `hdbscan`, etc.) is unchanged.
**Storage**: No new data, caches, or exports introduced. Existing artifact contracts (Stage 1 corpus, Stage 2 enrich SQLite + per-component caches, Stage 3 bundles, Stage 4 rollup) are byte-identical before and after.
**Testing**: `unittest`. Per the Session-2026-05-16 clarification (spec FR-008 + CA-002), the test-skip waiver is **scoped to US2 (parked layout) only**. US1 (enrichment cleanup) and US3 (UI split) ship with test coverage for every new submodule — either newly authored focused tests, or inherited coverage from existing tests (`tests/test_openalex.py`, `tests/test_ui.py`, `tests/test_ui_export.py`, `tests/test_embed_components.py`) after import-line rewires.
**Target Platform**: macOS / Linux workstation.
**Project Type**: Single-project CLI + library.
**Performance Goals**: No runtime perf goal. The non-perf goal is **readability**: `wc -l` per file should drop substantially (the largest file in `src/ohbm2026/` goes from 1,361 → 200–400 per UI submodule; `enrichment.py` disappears).
**Constraints**:
- Determinism preserved: `ohbmcli enrich-abstracts --limit 1 --invalidate figures` must hit the same `cache_key` after the move; `ohbmcli build-ui --analysis-rollup …` must produce a shape-equivalent bundle.
- No backward-compat shim at any `__init__.py`; every consumer imports from the explicit submodule that owns the symbol (the Stage 4 / Q2 / T108b precedent).
- No new gitignored roots; existing `data/`, `export/`, `tmp/`, `archive/`, `memory/archive/`, `.claude/` cover everything.
- Pre-existing `test_plot_poster_layout_floorplan` failure stays at the same baseline.
**Scale/Scope**:
- 5 legacy top-level modules removed (`enrichment.py`, `poster_layout.py`, `poster_sequencing.py`, `nocd_experiments.py`, `ui.py`).
- 3 new packages: `enrich/` (4 new submodules added), `layout/` (3 modules moved + `__init__.py`), `ui/` (7 submodules + `__init__.py`).
- 15 scripts relocated under `scripts/layout/`.
- 22 unused legacy symbols deleted outright.
- ~30–40 import sites rewritten across `src/`, `tests/`, `scripts/`.
- Touched tests (import-only changes): `tests/test_enrichment.py`, `tests/test_openalex.py`, `tests/test_ui.py`, `tests/test_ui_export.py`, `tests/test_nocd_experiments.py`, `tests/test_poster_sequencing.py`, `tests/test_plot_poster_layout_floorplan.py`, `tests/test_embed_components.py` (or wherever the embed-side enrichment import lives).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (venv-only Python)**: All `python` invocations in the plan, the implementation, and the verification scripts go through `.venv/bin/python` or `uv pip --python .venv/bin/python`. ✓
- **Principle II (immutable evidence, no committed data)**: No new artifact roots introduced. The cleanup touches only source code under `src/`, tests under `tests/`, scripts under `scripts/`, and docs (`CLAUDE.md`, `README.md`, `docs/reproducibility-vision.md`). ✓
- **Principle III (resumable, auditable)**: No change to caches or checkpoints; cache-key determinism is verified by FR-010 / SC-005. ✓
- **Principle IV (plan-first, test-first)**: This plan exists. Test-first is **scoped-waived for US2 only** (parked layout) per the Session-2026-05-16 clarification (spec FR-008 + CA-002). US1 and US3 author new focused tests for every new submodule (4 enrich + 4 ui new test files) or inherit coverage from existing tests where the existing coverage is already behavioral-equivalent. The verification surface: (a) the unit suite stays at no worse than `(583 − 22) + N_new` passing / 1 pre-existing failure, where 22 = test count of the to-be-deleted `tests/test_enrichment.py` and N_new = count of new tests authored; (b) two live-corpus smoke tests (SC-005 + SC-006). ✓ with documented scoped waiver.
- **Principle V (secret-safe, commit early and often)**: No secret-handling code changes. Plan commits each US as its own commit series; `git diff` carries no token-shaped strings (verified by the existing `constitution-check --staged` pre-commit hook). ✓
- **Principle VI (fail loudly, no shortcuts)**: No bare `except`, no `--no-verify`, no skipped tests, no `if NOT_READY: pass` shortcuts. The 22 unused symbols are **deleted**, not commented out, to avoid future false-positive importers. ✓
- **Principle VII (discover external state)**: No external-state surfaces are introduced or removed. ✓
- **Principle VIII (provenance for organizer-facing artifacts)**: No organizer-facing artifact is produced by this stage. The existing UI bundles and Stage 4 rollups carry the same provenance contract before and after. ✓

**Gate verdict**: PASS, with the documented scoped test-first waiver (US2 only) per spec FR-008 + CA-002. The existing test suite + new US1/US3 tests + 2 live-corpus smoke tests are the verification surface.

## Project Structure

### Documentation (this feature)

```text
specs/007-package-reorg/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 — enrichment.py symbol categorization + new homes
├── data-model.md        # Phase 1 — package-after-the-move layout per FR-001..FR-006
├── quickstart.md        # Phase 1 — smoke-run recipes (enrich + build-ui) for SC-005/SC-006
├── contracts/           # Phase 1 — public-import contract per new package
│   ├── enrich-api.md
│   ├── layout-api.md
│   └── ui-api.md
├── checklists/
│   └── requirements.md  # Spec-quality checklist (already exists)
└── tasks.md             # Phase 2 output (/speckit-tasks command — NOT created here)
```

### Source Code (repository root)

**Before (current state):**

```text
src/ohbm2026/
├── enrich/                      # Stage 2 package (Stages 2 + 2.1)
│   ├── __init__.py              # currently re-exports — to keep minimal
│   ├── claims.py
│   ├── figures.py
│   ├── flex_tier.py
│   ├── image_quality.py
│   ├── openalex.py
│   ├── references.py
│   ├── stage.py
│   └── storage.py
├── enrichment.py                # 1,361 LOC — LEGACY, to be deleted
├── poster_layout.py             # 103 KB — to be moved to layout/
├── poster_sequencing.py         # 103 KB — to be moved to layout/
├── nocd_experiments.py          # 21 KB — to be moved to layout/
├── ui.py                        # 1,361 LOC — to be split into ui/ package
├── analyze/                     # Stage 4 (unchanged by this stage)
├── embed/                       # Stage 3 (unchanged)
├── fetch/                       # Stage 1 (unchanged)
├── cli.py                       # subcommand dispatch — import sites rewired
├── exceptions.py                # typed exception hierarchy (unchanged)
└── …other unchanged modules
```

**After (Stage 5 end state):**

```text
src/ohbm2026/
├── enrich/
│   ├── __init__.py              # docstring + ≤1 warmup import; no re-export shell
│   ├── cache_paths.py           # NEW — `default_image_analysis_cache_path`, `default_claim_analysis_cache_path`, `load_json`, `write_json` (the only JSON I/O helpers actually used)
│   ├── claims.py
│   ├── figures.py
│   ├── flex_tier.py
│   ├── image_quality.py
│   ├── markdown_render.py       # NEW — `build_sections_markdown`, `build_claim_manuscript_markdown`, `render_abstract_markdown`, `filter_content_questions_markdown`, `is_content_question`, `question_to_section`
│   ├── openai_compat.py         # NEW — `openai_chat_multimodal`, `openai_chat_multimodal_batch`, `resolve_openai_api_key`, `parse_jsonish_content`, `image_to_data_url`, `normalize_question_name` (leftover low-level helpers still called by the agentic runners)
│   ├── openalex.py
│   ├── references.py
│   ├── stage.py
│   ├── storage.py
│   └── text.py                  # NEW — `html_to_markdown`, `HTMLToMarkdownParser`
├── layout/                      # NEW package — parked
│   ├── __init__.py              # docstring only: "Parked surface. Revive when a new organizer cycle needs poster-layout work."
│   ├── nocd_experiments.py
│   ├── poster_layout.py
│   └── poster_sequencing.py
├── ui/                          # NEW package — replaces ui.py
│   ├── __init__.py              # docstring only; no re-export shell
│   ├── cli.py                   # NEW — `export_ui_main`, `build_ui_main`, argparse builders
│   ├── figures.py               # NEW — `simplify_image_analysis`, `figure_note_sort_key`, `order_figure_notes`, `build_figure_text_blob`, `load_image_analysis_lookup`
│   ├── manifest.py              # NEW — `default_site_output_dir`, `default_export_output_dir`, atomic manifest write
│   ├── payload_legacy.py        # NEW — legacy embedding-bundle-driven `build_ui_payload`
│   ├── payload_stage4.py        # NEW — `build_ui_payload_from_stage4`, `UIBuildError`, `ClusterLayerSpec`
│   ├── references.py            # NEW — `load_reference_lookup`, `load_neighbors`, `load_distant`
│   └── text.py                  # NEW — `markdown_to_plain_text`, `markdown_to_html`, `render_additional_content_markdown`, topic helpers, `question_lookup`
├── analyze/                     # unchanged
├── embed/                       # unchanged; embed/components.py import rewired
├── fetch/                       # unchanged
├── cli.py                       # imports rewired for ui + (transitively) enrich
├── exceptions.py                # unchanged
└── …

scripts/
├── layout/                      # NEW — parked
│   ├── analyze_poster_layout.py
│   ├── benchmark_poster_sequencing.py
│   ├── build_layout_review_hub.py
│   ├── check_layout_review.py
│   ├── compare_poster_layout_proposals.py
│   ├── extract_layout_geometry.py
│   ├── generate_semantic_layout_proposals.py
│   ├── generate_target_poster_layout_proposals.py
│   ├── optimize_poster_layout.py
│   ├── plot_poster_layout_day_comparison.py
│   ├── plot_poster_layout_floorplan.py
│   ├── run_nocd_checkpoint_sweep_experiment.py
│   ├── run_nocd_classic_predict_experiment.py
│   ├── write_layout_category_summaries.py
│   └── write_layout_reassignment_summaries.py
└── …all other unmoved scripts (Stage 1–4 scripts stay where they are)
```

**Structure Decision**: The cleanup applies the per-stage package pattern already used by Stages 1–4 (`fetch/`, `enrich/`, `embed/`, `analyze/`). The new `layout/` package mirrors that shape but is **marked parked** in docs; no runtime warning. The `ui/` package extends the same pattern to the UI export surface. Each `__init__.py` is minimal (the Stage 4 / Q2 / T108b precedent).

## Complexity Tracking

> Filled only if the Constitution Check produced unjustified violations. No unjustified violations were found — the test-first waiver is **scoped to US2 only** (parked layout) per the Session-2026-05-16 clarification, explicitly documented in spec FR-008 + CA-002. US1 and US3 follow standard test-first discipline. No row needed.

## Phasing & sequencing

The three user stories are independent commit series, in priority order:

1. **Commit series A (US1 — enrichment cleanup)** lands first; rewires `enrich/`, deletes `enrichment.py`, updates the 7 importer sites. After this, the full test suite (with import rewrites in `tests/test_enrichment.py`, `tests/test_openalex.py`) returns to 583/1 baseline. Smoke: `ohbmcli enrich-abstracts --limit 1 --invalidate figures` produces the same `cache_key` (SC-005).
2. **Commit series B (US2 — layout park)** lands second; pure `git mv` operations + minimal `__init__.py` + script path-resolution updates + the docs note. Smoke: pick one moved script (e.g., `scripts/layout/optimize_poster_layout.py --help`) and confirm it imports without error.
3. **Commit series C (US3 — UI split)** lands third; splits `ui.py`, rewires `cli.py` + tests, updates docs. Smoke: `ohbmcli build-ui --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite …` writes a shape-equivalent bundle (SC-006).

Each series ends with a green test suite (583/1 baseline) and a commit. There is no required intermediate "all three commits stacked" state — the series are reorder-able if review feedback dictates.

## Verification surface

Per the scoped test-first waiver (US2 only), this stage's verification is:

- **Existing unit test suite**: `KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` at `≥ 561 + N_new passing / 1 pre-existing failure` before and after each commit series (561 = pre-stage 583 minus the 22 tests in the to-be-deleted `tests/test_enrichment.py`; N_new = tests authored for US1 + US3 new submodules).
- **US1 new tests**: `tests/test_enrich_text.py`, `tests/test_enrich_cache_paths.py`, `tests/test_enrich_markdown_render.py`, `tests/test_enrich_openai_compat.py` — focused coverage of the four new `enrich/` submodules. The four new files MUST exist and pass before US1 is considered done.
- **US3 new tests**: `tests/test_ui_text.py`, `tests/test_ui_figures.py`, `tests/test_ui_references.py`, `tests/test_ui_manifest.py` — focused coverage of the four leaf `ui/` submodules. The trunk modules (`ui/cli.py`, `ui/payload_legacy.py`, `ui/payload_stage4.py`) inherit coverage from the existing `tests/test_ui.py` + `tests/test_ui_export.py` via the import-line rewires (FR-008 inheritance route).
- **US2 (waived)**: only import-line rewires in `tests/test_nocd_experiments.py`, `tests/test_poster_sequencing.py`, `tests/test_plot_poster_layout_floorplan.py`. No new layout tests authored.
- **Smoke A (post-US1)**: `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich-abstracts --limit 1 --invalidate figures` — read the produced cache file and confirm the `cache_key` matches the pre-stage value for the same abstract id.
- **Smoke C (post-US3)**: `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui --raw-input data/primary/abstracts.json --enriched-input data/primary/abstracts_enriched.sqlite --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite --analysis-root data/outputs/analysis --output-dir /tmp/ui-smoke` — diff the produced file list against a pre-split bundle to confirm shape equivalence.
