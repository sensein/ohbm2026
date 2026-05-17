# Feature Specification: Stage 5 — Package Reorganization & Enrichment Cleanup

**Feature Branch**: `007-package-reorg`
**Created**: 2026-05-16
**Status**: Draft
**Input**: User description: "Let's move on to the next stage. Do the enrichment cleanup first. Move poster-layout-related functionality into a `layout/` folder — poster layouts are no longer a priority so they are just parked for the moment. OK to skip tests. Move UI-related components to a `ui/` folder."

## Clarifications

### Session 2026-05-16

- Q: Does the "OK to skip tests" guidance apply to all three user stories, or only to the parked layout work? → A: **Skip tests only for US2 (layout park).** The enrichment cleanup (US1) and UI split (US3) MUST have test coverage for their new submodules — either by authoring focused new tests for the new `enrich/{text, cache_paths, markdown_render, openai_compat}.py` + `ui/{text, figures, references, manifest, payload_legacy, payload_stage4, cli}.py` files, or by inheriting equivalent coverage from existing tests (`tests/test_openalex.py`, `tests/test_ui.py`, `tests/test_ui_export.py`, `tests/test_embed_components.py`) after import-line rewires. US2 is exempt because the layout package is parked — only the import-line rewires in `tests/test_nocd_experiments.py`, `tests/test_poster_sequencing.py`, and `tests/test_plot_poster_layout_floorplan.py` are required; no new tests authored.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Enrichment cleanup: collapse the legacy `enrichment.py` into the `enrich/` package (Priority: P1) 🎯 MVP

A maintainer reading `src/ohbm2026/` should find every Stage 2 enrichment helper inside the canonical `enrich/` package. Today the production runners live in `enrich/` (figures, claims, references, storage, stage orchestrator), but a 1300-line `enrichment.py` at the repo root still hosts: markdown rendering helpers, HTML→markdown conversion, content-question normalization, cache path helpers, figure-analysis legacy entry points, and a handful of dead Stage-1-era functions. Seven importers across `enrich/claims.py`, `enrich/stage.py`, `enrich/openalex.py`, `embed/components.py`, `ui.py`, and two scripts still reach into the legacy module, blurring the package boundary. After this story, `enrichment.py` MUST be gone; its still-used helpers move into four focused `enrich/` submodules (`enrich/text.py`, `enrich/cache_paths.py`, `enrich/markdown_render.py`, `enrich/openai_compat.py`), and every consumer imports from the explicit submodule that owns the symbol.

**Why this priority**: Every other consumer of enrichment artifacts (UI, embeddings, downstream analyses) currently has to follow a stale "where does X live" trail through the codebase. Removing the legacy module is the largest single readability win and unblocks the rest of this stage cleanly. The enrichment surface is also the most touched area in production: any future fix to figure analysis, claim extraction, or reference resolution starts here.

**Independent Test**: After the cleanup, `grep -rE "from ohbm2026 import enrichment|from ohbm2026.enrichment" src/ tests/ scripts/` returns zero matches; `git ls-files src/ohbm2026/enrichment.py` returns nothing; the full unit suite (`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`) stays at its current pass count (583 / 1 pre-existing failure baseline); and an end-to-end smoke of `ohbmcli enrich-abstracts --invalidate figures --limit 1` against the live corpus reproduces the prior cached `figure_analysis` output for that abstract byte-for-byte.

**Acceptance Scenarios**:

1. **Given** the current repository state, **When** `enrichment.py` is deleted and replaced by focused `enrich/` submodules, **Then** every prior consumer (`enrich/claims.py`, `enrich/stage.py`, `enrich/openalex.py`, `embed/components.py`, `ui.py` / `ui/*.py`, `scripts/time_figure_enrichment.py`, `scripts/reference_split_regression_probe.py`, `tests/test_enrichment.py`) imports from the submodule that owns the symbol, with no `__init__.py` re-export shim mirroring the legacy surface.
2. **Given** the cleanup landed, **When** an operator runs `PYTHONPATH=src .venv/bin/python -c "import ohbm2026.enrich"`, **Then** the import succeeds without warnings and the package exposes only the explicit submodule list (figures, claims, references, storage, stage, plus the new helpers — `markdown`, `cache_paths`, `text` or whatever names land).
3. **Given** the cleanup landed, **When** the maintainer runs `unittest discover` and the cached `ohbmcli enrich-abstracts --limit 1` smoke, **Then** both succeed and the smoke's cache-key for the per-component bundle is unchanged from the pre-cleanup run (no input-side regression).

---

### User Story 2 — Park poster-layout / sequencing / NOCD code in a `layout/` package (Priority: P2)

A maintainer scanning the active package surface should see at a glance that poster-layout work is parked, not gone. Today `src/ohbm2026/poster_layout.py` (~103 KB), `poster_sequencing.py` (~103 KB), and `nocd_experiments.py` (~21 KB) sit at the top of the `ohbm2026` namespace alongside the active pipeline modules, even though the README explicitly tracks them under the exploratory "Track B" surface and no organizer-facing work is happening on them right now. Move all three into a `layout/` package; relocate the 15 layout/poster/NOCD scripts under `scripts/layout/`; update CLAUDE.md, README, and the docs/reproducibility-vision.md to mark `layout/` as **parked**: no scheduled enhancements, no new tests, but the code is preserved verbatim so it can be revived for future organizer cycles. Existing tests (`test_poster_sequencing.py`, `test_nocd_experiments.py`, `test_plot_poster_layout_floorplan.py`) keep running with updated import paths.

**Why this priority**: The reorganization itself is low-risk and high-readability-payoff, but it sequences after enrichment cleanup because (a) enrichment touches more production code, (b) layout files are large and the move is mechanical, and (c) parking them with clear "parked" docs helps the next contributor avoid investing in dead-ends.

**Independent Test**: `git ls-files src/ohbm2026/poster_*.py src/ohbm2026/nocd*.py` returns nothing; `ls src/ohbm2026/layout/` lists `poster_layout.py`, `poster_sequencing.py`, `nocd_experiments.py`, plus a minimal `__init__.py` (one docstring line that names it as parked); `ls scripts/layout/` lists the 15 relocated scripts; `unittest discover` still passes the pre-existing 583-/-1 baseline.

**Acceptance Scenarios**:

1. **Given** the layout files moved, **When** `grep -rE "from ohbm2026 import poster_layout|from ohbm2026.poster_layout|from ohbm2026.poster_sequencing|from ohbm2026.nocd_experiments" src/ tests/ scripts/` runs, **Then** zero matches remain — every reference now points at `ohbm2026.layout.poster_layout`, `ohbm2026.layout.poster_sequencing`, or `ohbm2026.layout.nocd_experiments`.
2. **Given** the script move happened, **When** the maintainer runs one of the layout scripts via its new path (e.g. `PYTHONPATH=src .venv/bin/python scripts/layout/optimize_poster_layout.py --help`), **Then** it executes the help output cleanly without any "ModuleNotFoundError".
3. **Given** the parking docs landed, **When** a new contributor reads `CLAUDE.md` and `docs/reproducibility-vision.md`, **Then** they encounter an explicit note that `layout/` is parked, with the criteria under which the code would be revived (new organizer cycle that needs a poster-layout iteration).

---

### User Story 3 — Break the monolithic `ui.py` into a `ui/` package (Priority: P3)

A maintainer adding or fixing a UI export path should not have to scroll through a 1361-line file. Today `src/ohbm2026/ui.py` carries the entire static-UI export surface: payload composition for both the legacy embedding-bundle-driven path and the new Stage-4-rollup-driven path, the CLI front-ends (`export_ui_main`, `build_ui_main`), HTML/Markdown rendering helpers, figure-note ordering, reference + neighbor loading, manifest building, and the JSON writers. Split it into a `ui/` package with focused submodules — for example, `ui/markdown.py`, `ui/figures.py`, `ui/references.py`, `ui/neighbors.py`, `ui/payload.py` (legacy path), `ui/stage4_payload.py` (new path), `ui/cli.py` (`export_ui_main` + `build_ui_main`), `ui/manifest.py`. The two test files (`tests/test_ui.py` and `tests/test_ui_export.py`) plus the CLI dispatch in `src/ohbm2026/cli.py` update their imports to point at the new submodules. As with the analyze and enrich packages, `ui/__init__.py` carries no package-level re-export shell; every consumer imports from the explicit submodule that owns the symbol.

**Why this priority**: The UI was just updated for Stage 4 consumption (FR-018, T097a); its surface is fresh in everyone's mind. Splitting it now — before the next round of UI iteration — pays off when someone needs to touch one of the renderers without having to load the whole file mentally. Lower priority than US1 / US2 because the file is internally well-organized; the move is a pure readability improvement.

**Independent Test**: `git ls-files src/ohbm2026/ui.py` returns nothing; `ls src/ohbm2026/ui/` lists the new submodules; `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli export-ui --help` and `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui --help` both run; the existing UI tests pass without modification beyond their import lines; a `build-ui` smoke against the live Stage 4 rollup writes a bundle that is shape-equivalent to the bundle produced before the split (same file list, same `manifest.json["source"] == "stage4"`, same row count).

**Acceptance Scenarios**:

1. **Given** `ui.py` is split into the `ui/` package, **When** `grep -rE "from ohbm2026 import ui|from ohbm2026.ui import" src/ tests/ scripts/` runs, **Then** every match resolves to an explicit submodule path (`from ohbm2026.ui.cli import export_ui_main`, etc.) — there is no `from ohbm2026.ui import X` that resolves via a re-export shim.
2. **Given** the split landed, **When** `ohbmcli build-ui --raw-input data/primary/abstracts.json --enriched-input data/primary/abstracts_enriched.sqlite --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite --analysis-root data/outputs/analysis --output-dir /tmp/ui-smoke` runs, **Then** the bundle's file list and manifest match what the pre-split build produced.

---

### Edge Cases

- **Circular import risk during enrichment cleanup**: `enrichment.py` is imported by both `enrich/` submodules and by `embed/components.py` and `ui.py`. Moving symbols across modules MUST NOT introduce a circular cycle (e.g., `enrich/markdown.py` re-importing `enrich/__init__.py`); see the Stage 4 reorganization (`analyze/__init__.py` issue) for the precedent — keep `__init__.py` minimal.
- **Layout scripts that hardcode their own location**: some scripts in `scripts/` resolve paths via `Path(__file__).parents[N]`. Moving them down one directory shifts `parents[N]` by one. Each script's path-resolution call MUST be re-validated after the move.
- **Pre-existing `test_plot_poster_layout_floorplan` failure**: this test was already failing before this stage (1 pre-existing baseline failure). The move MUST NOT mask or worsen it; if it's still failing after the move it's still acceptable; if it newly passes, that's a free win to record.
- **UI split breaking the cluster-table-loader dual path**: `ui.py` has both the legacy embedding-bundle-driven path (still referenced by tests) and the new Stage-4-rollup path (T097a). Both MUST keep working after the split — neither path is silently removed.
- **`tests/test_enrichment.py`** is 658 lines but the grep earlier reported zero `^def test_` matches — its tests are class-based. Confirm before deciding whether to delete or just rewire it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The legacy `src/ohbm2026/enrichment.py` MUST be removed in the same commit (or commit series) that moves its still-used helpers into focused `src/ohbm2026/enrich/` submodules. No deprecation period; no backward-compat shim at the package level.
- **FR-002**: Every helper that is currently imported from `ohbm2026.enrichment` MUST find a new home that is named for its purpose (per the canonical mapping in `data-model.md` §1 and `research.md` R1: `html_to_markdown` + `HTMLToMarkdownParser` → `enrich/text.py`; manuscript / section / claim markdown builders → `enrich/markdown_render.py`; cache-path helpers + `load_json` / `write_json` → `enrich/cache_paths.py`; OpenAI / multimodal / image-encoding helpers → `enrich/openai_compat.py`). Helpers that have no current importer MUST be deleted, not preserved.
- **FR-003**: Poster-layout, poster-sequencing, and NOCD module files MUST move under `src/ohbm2026/layout/` with their content preserved verbatim (no inline refactors during the move); `__init__.py` MUST be minimal, carrying only a docstring noting the package is parked.
- **FR-004**: Poster-layout, poster-sequencing, and NOCD scripts in `scripts/` MUST move under `scripts/layout/`; each script's path-resolution (`Path(__file__).parents[N]`, `sys.path.insert`) MUST be updated to remain valid from the new location.
- **FR-005**: The monolithic `src/ohbm2026/ui.py` MUST be split into a `src/ohbm2026/ui/` package; `__init__.py` MUST be minimal (no package-level re-export shell); every consumer imports from the explicit submodule that owns the symbol.
- **FR-006**: CLI dispatch in `src/ohbm2026/cli.py` MUST update its `ui` imports to point at the new submodules; running `ohbmcli export-ui --help` and `ohbmcli build-ui --help` MUST succeed after the split.
- **FR-007**: CLAUDE.md, README.md, and `docs/reproducibility-vision.md` MUST be updated in the same change to (a) reflect the new `enrich/`, `layout/`, and `ui/` package layouts and (b) explicitly mark `layout/` as parked (no scheduled enhancements; no new tests; revive when a new organizer cycle needs poster work).
- **FR-008**: The full unit test suite (`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`) MUST end the stage at no worse than the pre-stage baseline — currently 583 tests, 1 pre-existing failure (`test_plot_poster_layout_floorplan`). Per the Session-2026-05-16 clarification, the test-skip waiver is **scoped to US2 (layout) only**: US1 (enrichment cleanup) and US3 (UI split) MUST ship with test coverage for their new submodules. Coverage can be (a) authored as new focused tests under `tests/test_enrich_text.py`, `tests/test_enrich_cache_paths.py`, `tests/test_enrich_markdown_render.py`, `tests/test_enrich_openai_compat.py`, `tests/test_ui_text.py`, `tests/test_ui_figures.py`, `tests/test_ui_references.py`, `tests/test_ui_manifest.py`, `tests/test_ui_payload_legacy.py`, `tests/test_ui_payload_stage4.py`, `tests/test_ui_cli.py`, or (b) inherited from existing tests (`tests/test_openalex.py`, `tests/test_ui.py`, `tests/test_ui_export.py`, `tests/test_embed_components.py`) after import-line rewires — whichever route preserves the original behavioral coverage of the moved symbol. US2 is exempt: only import-line rewires are required in `tests/test_nocd_experiments.py`, `tests/test_poster_sequencing.py`, `tests/test_plot_poster_layout_floorplan.py`; no new layout tests authored.
- **FR-009**: Each of the three user stories MUST be implementable as an independent commit (or commit series) and reviewable in isolation — i.e., the enrichment cleanup must not require the layout move to land first, and vice versa.
- **FR-010**: A smoke run of `ohbmcli enrich-abstracts --limit 1` against the live corpus MUST hit cache after the enrichment cleanup (no input-key regression); a smoke run of `ohbmcli export-ui --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite …` MUST produce a Stage-4-sourced UI bundle of the same shape as before the UI split.

### Key Entities

- **`ohbm2026.enrich` package**: Canonical home of every Stage 2 (enrichment) helper after this stage. Submodules cover figures, claims, references, storage, the orchestrator (`stage.py`), the flex-tier helper, ECO vocabulary lookups, plus the new homes for what currently lives in `enrichment.py`: markdown conversion, cache path helpers, HTML/Markdown text utilities. No package-level re-exports.
- **`ohbm2026.layout` package**: Parked surface area carrying `poster_layout.py`, `poster_sequencing.py`, `nocd_experiments.py`. Preserved for future revival; not actively maintained.
- **`ohbm2026.ui` package**: Static-UI export surface split into focused submodules — payload composition (legacy + Stage 4), CLI front-ends (`export_ui_main`, `build_ui_main`), markdown / HTML helpers, figure-note ordering, reference + neighbor loaders, manifest builder. No package-level re-exports.
- **`scripts/layout/` directory**: Parked organizer-facing one-off scripts for poster layout, sequencing, NOCD experiments.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python execution for this feature MUST use `.venv/bin/python` or `uv` targeting that interpreter.
- **CA-002**: The test-first requirement is **waived for US2 only** (parked layout package). US1 and US3 follow Principle IV's standard test-first discipline: each new submodule MUST have test coverage authored before or alongside the implementation, OR inherit equivalent coverage from existing tests after import-line rewires (see FR-008). The verification step is the existing test suite plus the new tests authored for US1/US3 plus the live-corpus smoke runs called out in FR-010 and each story's Independent Test.
- **CA-003**: CLAUDE.md, README.md, and `docs/reproducibility-vision.md` MUST be updated to reflect the new package layouts and the `layout/` parking note. This is captured in FR-007.
- **CA-004**: No new credentials, env vars, or secret boundaries are introduced by this stage. Existing `OPENAI_API_KEY` handling (loaded by `analyze/stage.py:_load_env_file` and consumed by `enrich/flex_tier`) is unchanged.
- **CA-005**: No new datasets, caches, exports, or downloaded assets are produced by this stage. The cleanup is purely structural; the on-disk artifact contract is unchanged.
- **CA-006**: Error paths MUST stay explicit: the symbol moves preserve the existing typed-exception hierarchy (`Stage1Error`, `Stage2Error`, etc.). The legacy `EnrichmentError` defined at `enrichment.py:72` MUST end up at the same import path it has today (`ohbm2026.exceptions.EnrichmentError`) — the move MUST NOT silently change the exception's qualified name.
- **CA-007**: This stage adds no new external dependency; all symbol relocations are within the existing `src/ohbm2026/` tree.
- **CA-008**: This stage produces no new organizer-facing artifact; the existing UI bundles and Stage 4 rollup carry the same provenance contract they did before.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the stage, `git ls-files src/ohbm2026/enrichment.py src/ohbm2026/ui.py src/ohbm2026/poster_layout.py src/ohbm2026/poster_sequencing.py src/ohbm2026/nocd_experiments.py` returns **zero** matches — all five legacy top-level modules are gone.
- **SC-002**: After the stage, `ls src/ohbm2026/enrich/ src/ohbm2026/ui/ src/ohbm2026/layout/` lists focused submodule files; each `__init__.py` is ≤ 5 lines (docstring + at most one warmup import).
- **SC-003**: After the stage, `grep -rE "from ohbm2026 import (enrichment|poster_layout|poster_sequencing|nocd_experiments)|from ohbm2026\.(enrichment|poster_layout|poster_sequencing|nocd_experiments)" src/ tests/ scripts/` returns **zero** matches.
- **SC-004**: After the stage, `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` produces no worse than 583 passing / 1 pre-existing failure (`test_plot_poster_layout_floorplan`), and no failure newly originates from this stage's import rewrites.
- **SC-005**: After the stage, a smoke `ohbmcli enrich-abstracts --limit 1 --invalidate figures` writes the same `cache_key` to its per-component cache as the pre-stage run for the same abstract (idempotent — no false-invalidation).
- **SC-006**: After the stage, a smoke `ohbmcli build-ui --raw-input data/primary/abstracts.json --enriched-input data/primary/abstracts_enriched.sqlite --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite --analysis-root data/outputs/analysis --output-dir /tmp/ui-smoke` writes a bundle whose file list matches the pre-stage build's file list (`manifest.json`, `abstracts.search.json`, `abstracts.detail.json`, `clusters.json`, `projection.umap.json`, `facets.json`, `relations.json`), with `manifest.json["source"] == "stage4"` and `abstract_count == 3244`.
- **SC-007**: After the stage, CLAUDE.md, README.md, and `docs/reproducibility-vision.md` each contain an explicit "layout package is parked" note (`grep -l "layout.*parked\|parked.*layout" CLAUDE.md README.md docs/reproducibility-vision.md` returns all three filenames).

## Assumptions

- The user's "OK to skip tests" guidance, narrowed by the Session-2026-05-16 clarification, applies **only to US2 (layout park)**: do not author new tests for the parked layout package. US1 (enrichment cleanup) and US3 (UI split) follow standard test-first discipline per Principle IV — new submodules require either focused new tests or inherited coverage from existing tests after import-line rewires (FR-008). Across all three stories, the unit test suite MUST end at `≥ 561 + N_new passing / 1 pre-existing failure` (561 = pre-stage 583 minus the 22 tests in the deleted `tests/test_enrichment.py`; N_new = total tests authored across the 4 new US1 + 4 new US3 test files).
- Each story is implementable in a single commit (or small commit series) by one contributor in a single working session — none of these moves require multi-day coordination or upstream dependency changes.
- The `enrichment.py` helpers split cleanly along functional lines (markdown, cache paths, HTML utilities, figure-analysis legacy entry points). If a helper is truly cross-cutting it may stay under the more general name (e.g., `enrich/text.py`).
- The `layout/` parking note is informational, not enforceable: the package can still be imported and the scripts can still run. We do NOT add a runtime warning when `ohbm2026.layout` is imported.
- The user is fine with breaking changes in import paths across this stage — no deprecation period, no compat re-export shim. The Stage 4 reorganization established the precedent (CLAUDE.md already documents "no backward-compat shim for `ohbm2026.analyze`"); this stage applies the same rule to `enrich`, `layout`, and `ui`.
- Live-corpus smoke tests in SC-005 and SC-006 require the pre-stage cached state to be on disk for an apples-to-apples comparison. They run against `corpus_state_key=f0c51e80dc0e` (the current live corpus on this branch).
- This stage stays on its own feature branch (`007-package-reorg`), independent of any in-flight Stage 4 review on PR #7. If PR #7 lands first, this stage rebases onto the updated `main`; if PR #7 lands after, this stage carries the Stage 4 commits in its history and is reviewable as a pure-refactor delta on top.
