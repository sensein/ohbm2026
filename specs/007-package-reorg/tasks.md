---
description: "Task list for Stage 5 — Package Reorganization & Enrichment Cleanup"
---

# Tasks: Stage 5 — Package Reorganization & Enrichment Cleanup

**Input**: Design documents from `/specs/007-package-reorg/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Per the Session-2026-05-16 clarification (spec FR-008, CA-002), the test-skip waiver is **scoped to US2 (parked layout) only**. US1 (enrichment cleanup) and US3 (UI split) ship with focused new tests for their new submodules — 4 + 4 new test files. The full suite ends at `≥ 561 + N_new passing / 1 pre-existing failure` (561 = pre-stage 583 minus the 22 tests in the deleted `tests/test_enrichment.py`; N_new = tests authored for US1 + US3 new submodules).

**Organization**: Tasks are grouped by user story so each story is independently shippable as its own commit series.

## Format: `[ID] [P?] [Story?] Description with file path`

- `[P]`: Can run in parallel (different files, no incomplete-task dependencies).
- `[Story]`: `[US1]` enrichment cleanup, `[US2]` layout park, `[US3]` UI split (Setup / Foundational / Polish phases carry no story label).
- Paths are project-relative.

## Path Conventions

- Source: `src/ohbm2026/{enrich,layout,ui}/...`
- Tests: `tests/test_*.py`
- Scripts: `scripts/`, `scripts/layout/`
- Docs: `CLAUDE.md`, `README.md`, `docs/reproducibility-vision.md`, this spec dir

---

## Phase 1: Setup

- [X] T001 Capture the pre-stage baselines under `tmp/stage5-baseline/`: (a) `KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3` → `tmp/stage5-baseline/test-suite.txt` (expect `583 / 1 pre-existing`); (b) `KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrichment 2>&1 | tail -3` → `tmp/stage5-baseline/test-enrichment.txt` (expect `22 tests`); (c) one cached `data/cache/figure_analysis/<key>.json` filename → `tmp/stage5-baseline/figure-cache-key.txt`; (d) a pre-stage UI bundle at `/tmp/ui-pre-stage5/` via `ohbmcli build-ui --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite …` and its file list → `tmp/stage5-baseline/ui-filelist.txt`. These are referenced by SC-005 / SC-006 verification.
- [X] T002 [P] Create the new feature branch when implementation starts: `git switch -c 007-package-reorg`. Cut from `main` if PR #7 has merged; otherwise stack on `006-analysis-annotation` and rebase later (per plan.md Phasing). The branch name MUST match the spec dir name.
- [X] T003 [P] Confirm `tmp/` is gitignored: `git check-ignore tmp/stage5-baseline/` returns the path.

---

## Phase 2: Foundational (blocks all user stories)

- [X] T004 Move `UIBuildError` from `src/ohbm2026/ui.py:150` (class definition) to `src/ohbm2026/exceptions.py` alongside the other typed errors (`EnrichmentError`, `AnalysisError`, …). The action is mechanical: cut the class from `ui.py`, paste into `exceptions.py`, no `__init__.py` or re-export changes needed (`exceptions.py` is a flat module). MUST land before US3's T040 (the test that asserts `UIBuildError` is importable from `ohbm2026.exceptions`) and T047 (the `ui/manifest.py` impl that imports it).
- [X] T005 Confirm `ohbm2026.exceptions.EnrichmentError` already exists at its canonical location (it does per CLAUDE.md's typed-exception hierarchy doc); no source change. The redundant declaration at `enrichment.py:72` is removed as part of T016 without changing the exception's qualified name for any of the 28 callers.

---

## Phase 3: User Story 1 — Enrichment cleanup (Priority: P1) 🎯 MVP

**Story Goal**: Delete `src/ohbm2026/enrichment.py`, redistribute still-used helpers into four focused `enrich/` submodules with new focused tests, drop dead helpers + legacy test file + legacy benchmark script.

**Independent Test** (per spec.md): After US1, `grep -rE "from ohbm2026 import enrichment|from ohbm2026.enrichment" src/ tests/ scripts/` returns zero; `git ls-files src/ohbm2026/enrichment.py` returns nothing; `unittest discover -s tests` returns at no worse than `561 + N_new` passing / 1 pre-existing; the smoke `ohbmcli enrich-abstracts --limit 1 --invalidate figures` produces the same `cache_key` as the pre-stage baseline.

### Tests first (new test files for the new submodules)

- [X] T006 [P] [US1] Write `tests/test_enrich_text.py` covering: (a) `html_to_markdown("<p>x</p>") == "x"` and similar canonical conversions; (b) handling of empty / `None` input; (c) nested tags + entities (`&amp;`, `&lt;`); (d) the `HTMLToMarkdownParser` class can be instantiated and produces equivalent output to the function wrapper. These tests are red until T010 lands.
- [X] T007 [P] [US1] Write `tests/test_enrich_cache_paths.py` covering: (a) `default_image_analysis_cache_path` returns a deterministic path under `data/cache/figure_analysis/` for a given `(input_hash, model_id)` tuple; (b) `default_claim_analysis_cache_path` likewise under `data/cache/claim_analysis/`; (c) `load_json` + `write_json` round-trip a dict; (d) `load_image_analysis_cache` / `load_claim_analysis_cache` tolerate a missing file (return `{}`); (e) `refresh_analysis_cache_stats` updates a stats dict in-place. Red until T011 lands.
- [X] T008 [P] [US1] Write `tests/test_enrich_markdown_render.py` covering: (a) `build_sections_markdown` produces section dict + content-question list from a synthetic abstract; (b) `build_claim_manuscript_markdown` produces a single Markdown blob with all configured sections; (c) `render_abstract_markdown(title, sections)` glues title + sections; (d) `is_content_question("Methods") == True` and `is_content_question("Title") == False`; (e) `question_to_section("methods") == "methods"`; (f) `normalize_question_name` lowercases and strips; (g) `parse_list_value("a, b; c")` returns `["a", "b", "c"]`; (h) `filter_content_questions_markdown` filters out non-content questions. Red until T012 lands.
- [X] T009 [P] [US1] Write `tests/test_enrich_openai_compat.py` covering: (a) `parse_jsonish_content` handles plain JSON + JSON with markdown fences + JSON inside prose; (b) `image_to_data_url(jpeg_bytes)` returns `data:image/jpeg;base64,…`; (c) `resolve_openai_api_key` reads from `OPENAI_API_KEY` env first, falls back to a keyring lookup (mocked); (d) `openai_chat_multimodal(...)` returns the response when the mocked OpenAI client returns a fixture; (e) `openai_chat_multimodal_batch(...)` handles a 2-record batch. Use `unittest.mock.patch` on the `openai` SDK; do NOT hit the real API. Red until T013 lands.

### Implementation (new submodules + rewires + delete)

- [X] T010 [P] [US1] Create `src/ohbm2026/enrich/text.py` with `html_to_markdown` + `HTMLToMarkdownParser` lifted verbatim from `src/ohbm2026/enrichment.py` (lines around 136 + 225); leaf module — stdlib `html.parser.HTMLParser` only, no intra-package imports. Verify T006 turns green.
- [X] T011 [P] [US1] Create `src/ohbm2026/enrich/cache_paths.py` with `default_image_analysis_cache_path`, `default_claim_analysis_cache_path`, `load_image_analysis_cache`, `load_claim_analysis_cache`, `refresh_analysis_cache_stats`, `load_json`, `write_json` lifted from `src/ohbm2026/enrichment.py` (lines 96, 114, 216, 220, 450, 461, 463); leaf module — stdlib only. Verify T007 turns green.
- [X] T012 [US1] Create `src/ohbm2026/enrich/markdown_render.py` with `build_sections_markdown`, `build_claim_manuscript_markdown`, `render_abstract_markdown`, `filter_content_questions_markdown`, `is_content_question`, `question_to_section`, `normalize_question_name`, `parse_list_value` lifted from `src/ohbm2026/enrichment.py` (lines 236–445); imports `from ohbm2026.enrich.text import html_to_markdown` (mid-tier module). Verify T008 turns green.
- [X] T013 [P] [US1] Create `src/ohbm2026/enrich/openai_compat.py` with `openai_chat_multimodal`, `openai_chat_multimodal_batch`, `resolve_openai_api_key`, `parse_jsonish_content`, `image_to_data_url` lifted from `src/ohbm2026/enrichment.py`; leaf module — stdlib + `openai` + `keyring`. Verify T009 turns green.
- [X] T013a [P] [US1] Trim `src/ohbm2026/enrich/__init__.py` from its current 25 lines (docstring + `from ohbm2026.enrich import (claims, figures, flex_tier, image_quality, references, stage, storage)` + `__all__` block) down to ≤ 5 lines: keep the module docstring only. Remove the package-level re-export shell and the `__all__` list (Stage 4 / Q2 / T108b precedent — no backward-compat shim). Verify with `wc -l < src/ohbm2026/enrich/__init__.py` returning ≤ 5 and `grep -rE "from ohbm2026.enrich import (claims|figures|flex_tier|image_quality|references|stage|storage)\b" src/ tests/ scripts/` returning matches only at explicit-submodule paths (`from ohbm2026.enrich.claims import …` is allowed; `from ohbm2026.enrich import claims` as a re-export consumer pattern is not). Required by SC-002 (each new package `__init__.py` ≤ 5 lines).
- [X] T014 [US1] Rewire `src/ohbm2026/enrich/claims.py` line 32 `from ohbm2026 import enrichment as enrichment_module` to explicit submodule imports. Concretely: (a) `from ohbm2026.enrich.cache_paths import default_claim_analysis_cache_path, load_claim_analysis_cache, load_json, write_json, refresh_analysis_cache_stats`; (b) `from ohbm2026.enrich.markdown_render import build_claim_manuscript_markdown, build_sections_markdown`; (c) `from ohbm2026.enrich.openai_compat import resolve_openai_api_key, parse_jsonish_content`. Then replace every `enrichment_module.X` reference with the bare `X`.
- [X] T015 [US1] Rewire `src/ohbm2026/enrich/stage.py` line 47 same pattern: replace `from ohbm2026 import enrichment as enrichment_module` with explicit submodule imports per the symbols `stage.py` consumes (use `grep -nE "enrichment_module\." src/ohbm2026/enrich/stage.py` to enumerate).
- [X] T016 [US1] Rewire `src/ohbm2026/enrich/openalex.py` line 24: `from ohbm2026.enrichment import html_to_markdown` → `from ohbm2026.enrich.text import html_to_markdown`.
- [X] T017 [P] [US1] Rewire `src/ohbm2026/embed/components.py` line 17 (`from ohbm2026 import enrichment as enrichment_module`) to explicit imports. Concretely, `components.py` consumes the markdown-render helpers + `html_to_markdown`: replace with `from ohbm2026.enrich.markdown_render import build_sections_markdown, build_claim_manuscript_markdown` and `from ohbm2026.enrich.text import html_to_markdown`. Verify via `grep -nE "enrichment_module\." src/ohbm2026/embed/components.py` returns zero post-edit.
- [X] T018 [P] [US1] Rewire `src/ohbm2026/ui.py` line 18 `from ohbm2026.enrichment import default_image_analysis_cache_path` → `from ohbm2026.enrich.cache_paths import default_image_analysis_cache_path`. (US3 will further split `ui.py`; this is the minimal change for US1 so the consumer compiles.)
- [X] T019 [P] [US1] Rewire `scripts/reference_split_regression_probe.py` line 9: `from ohbm2026.enrichment import html_to_markdown` → `from ohbm2026.enrich.text import html_to_markdown`.
- [X] T020 [US1] Delete the legacy module + legacy tests + legacy script:
  ```bash
  git rm src/ohbm2026/enrichment.py
  git rm tests/test_enrichment.py
  git rm scripts/time_figure_enrichment.py
  ```
- [X] T021 [US1] Verify the contract (per `contracts/enrich-api.md`):
  ```bash
  grep -rE "from ohbm2026 import enrichment|from ohbm2026\.enrichment" src/ tests/ scripts/ && exit 1 || true
  grep -rE "\b(enrich_main|analyze_figures_main|extract_claims_main|build_cllm_environment|extract_claims_with_cllm)\b" src/ tests/ scripts/ && exit 1 || true
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
  ```
- [X] T022 [US1] Smoke (SC-005): run `KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich-abstracts --limit 1 --invalidate figures 2>&1 | grep cache_key`. Confirm the printed `cache_key` matches the value in `tmp/stage5-baseline/figure-cache-key.txt`.
- [X] T023 [US1] Commit US1. Commit message MUST record (a) the post-stage test count (recompute `(583 − 22 + N_new) passing / 1 pre-existing`), (b) the list of deleted symbols (point at `research.md` R1), (c) the four new submodules + four new test files. Use the template in `quickstart.md` §"US1 verification → 4. Commit".

---

## Phase 4: User Story 2 — Park poster-layout / sequencing / NOCD under `layout/` (Priority: P2)

**Story Goal**: Move three large legacy modules and 15 scripts into a `layout/` namespace; mark the package parked in CLAUDE.md, README, and the vision doc.

**Test waiver**: Per the Session-2026-05-16 clarification, US2 is exempt from the new-test requirement. Only import-line rewires of the three existing layout tests are required; no new tests authored.

**Independent Test** (per spec.md): `git ls-files src/ohbm2026/poster_*.py src/ohbm2026/nocd*.py` returns nothing; `ls src/ohbm2026/layout/` lists the three modules + a minimal `__init__.py`; `ls scripts/layout/` lists the 15 relocated scripts; unit suite still at the post-US1 baseline.

### Implementation

- [X] T024 [P] [US2] Create `src/ohbm2026/layout/__init__.py` with the parking docstring exactly as specified in `data-model.md` §2 (one docstring, ≤ 5 lines, no `__all__`, no runtime warning).
- [X] T025 [US2] Move the three module files verbatim:
  ```bash
  git mv src/ohbm2026/poster_layout.py     src/ohbm2026/layout/poster_layout.py
  git mv src/ohbm2026/poster_sequencing.py src/ohbm2026/layout/poster_sequencing.py
  git mv src/ohbm2026/nocd_experiments.py  src/ohbm2026/layout/nocd_experiments.py
  ```
- [X] T026 [US2] Update the internal cross-reference inside the moved `poster_sequencing.py`: `from ohbm2026.poster_layout import …` → `from ohbm2026.layout.poster_layout import …`.
- [X] T027 [US2] Move the 15 layout/NOCD scripts to `scripts/layout/`:
  ```bash
  mkdir -p scripts/layout
  git mv scripts/analyze_poster_layout.py                  scripts/layout/
  git mv scripts/benchmark_poster_sequencing.py            scripts/layout/
  git mv scripts/build_layout_review_hub.py                scripts/layout/
  git mv scripts/check_layout_review.py                    scripts/layout/
  git mv scripts/compare_poster_layout_proposals.py        scripts/layout/
  git mv scripts/extract_layout_geometry.py                scripts/layout/
  git mv scripts/generate_semantic_layout_proposals.py     scripts/layout/
  git mv scripts/generate_target_poster_layout_proposals.py scripts/layout/
  git mv scripts/optimize_poster_layout.py                 scripts/layout/
  git mv scripts/plot_poster_layout_day_comparison.py      scripts/layout/
  git mv scripts/plot_poster_layout_floorplan.py           scripts/layout/
  git mv scripts/run_nocd_checkpoint_sweep_experiment.py   scripts/layout/
  git mv scripts/run_nocd_classic_predict_experiment.py    scripts/layout/
  git mv scripts/write_layout_category_summaries.py        scripts/layout/
  git mv scripts/write_layout_reassignment_summaries.py    scripts/layout/
  ```
- [X] T028 [US2] For each moved script, fix the path-resolution: any `REPO_ROOT = Path(__file__).resolve().parents[1]` becomes `parents[2]`; any internal `from ohbm2026.poster_layout import …` becomes `from ohbm2026.layout.poster_layout import …` (and same for `poster_sequencing` / `nocd_experiments`). Verify by running `--help` for 3 representative scripts: `optimize_poster_layout.py`, `benchmark_poster_sequencing.py`, `run_nocd_classic_predict_experiment.py`.
- [X] T029 [P] [US2] Rewire `tests/test_nocd_experiments.py` imports: `from ohbm2026 import nocd_experiments` → `from ohbm2026.layout import nocd_experiments`.
- [X] T030 [P] [US2] Rewire `tests/test_poster_sequencing.py` imports analogously.
- [X] T031 [P] [US2] Rewire `tests/test_plot_poster_layout_floorplan.py` imports; the pre-existing test failure stays pre-existing (it is unrelated to this stage's rewires).
- [X] T032 [US2] Update `CLAUDE.md`: add a one-paragraph note under the module-list / package-layout section explicitly naming `ohbm2026.layout` as parked (no scheduled maintenance; revive when a new organizer cycle needs it). The phrasing MUST satisfy `grep -E "layout.*parked|parked.*layout" CLAUDE.md`.
- [X] T033 [P] [US2] Update `README.md`'s Track B / poster section with the same "parked" wording; `grep -E "layout.*parked|parked.*layout" README.md` MUST match.
- [X] T034 [P] [US2] Update `docs/reproducibility-vision.md`'s Track B subsection with the same "parked" wording; `grep -E "layout.*parked|parked.*layout" docs/reproducibility-vision.md` MUST match.
- [X] T035 [US2] Verify the contract (per `contracts/layout-api.md`):
  ```bash
  grep -rE "from ohbm2026 import (poster_layout|poster_sequencing|nocd_experiments)|from ohbm2026\.(poster_layout|poster_sequencing|nocd_experiments)" src/ tests/ scripts/ && exit 1 || true
  PYTHONPATH=src .venv/bin/python scripts/layout/optimize_poster_layout.py --help >/dev/null
  PYTHONPATH=src .venv/bin/python scripts/layout/benchmark_poster_sequencing.py --help >/dev/null
  PYTHONPATH=src .venv/bin/python scripts/layout/run_nocd_classic_predict_experiment.py --help >/dev/null
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
  ```
- [X] T036 [US2] Commit US2. Use the template in `quickstart.md` §"US2 verification → 4. Commit".

---

## Phase 5: User Story 3 — Split `ui.py` into `ui/` package (Priority: P3)

**Story Goal**: Replace the 1,361-LOC `src/ohbm2026/ui.py` with a `ui/` package using the leaf-mid-trunk layout from `data-model.md` §3, with focused new tests for each leaf submodule.

**Independent Test** (per spec.md): `git ls-files src/ohbm2026/ui.py` returns nothing; `ls src/ohbm2026/ui/` lists the 7+ new submodules + minimal `__init__.py`; `ohbmcli export-ui --help` and `ohbmcli build-ui --help` both succeed; the `ohbmcli build-ui --analysis-rollup …` smoke produces a bundle whose file list matches the pre-stage capture.

### Tests first (new test files for the four leaf submodules)

- [X] T037 [P] [US3] Write `tests/test_ui_text.py` covering: (a) `markdown_to_plain_text("**bold**") == "bold"`; (b) `markdown_to_html("**bold**")` contains `<strong>`; (c) `render_additional_content_markdown` handles list + scalar input; (d) `question_lookup` returns a dict keyed by question name; (e) `primary_topic_from_questions` + `secondary_topic_from_questions` extract the right pair from a synthetic abstract. Red until T042 lands (the `ui/text.py` impl).
- [X] T038 [P] [US3] Write `tests/test_ui_figures.py` covering: (a) `simplify_image_analysis` produces a small dict from a fixture image-analysis record; (b) `figure_note_sort_key` orders by `(method_order, label)`; (c) `order_figure_notes` returns sorted list; (d) `build_figure_text_blob` concatenates per-figure text into a single string; (e) `load_image_analysis_lookup` reads a JSON file into `{abstract_id: [records]}`. Red until T043 lands (the `ui/figures.py` impl).
- [X] T039 [P] [US3] Write `tests/test_ui_references.py` covering: (a) `load_reference_lookup` reads a synthetic JSON file into `{abstract_id: {…}}`; (b) `load_neighbors` returns `{abstract_id: [neighbors_top_k]}`; (c) `load_distant` returns `{abstract_id: [distant_bottom_k]}`; (d) all three tolerate a missing file (return `{}`). Red until T046 lands.
- [X] T040 [P] [US3] Write `tests/test_ui_manifest.py` covering: (a) `default_site_output_dir` returns a path under `data/outputs/exported-sites/`; (b) `default_export_output_dir` returns `export/ui-site/`; (c) `ClusterLayerSpec` constructs from kwargs; (d) `UIBuildError` is importable from `ohbm2026.exceptions` (T004 moved it there); (e) `load_json` + `write_json` round-trip a dict (the UI-local copy that lives in `ui/manifest.py`). Red until T047 lands.

### Implementation (new submodules + rewires + delete)

- [X] T041 [P] [US3] Create `src/ohbm2026/ui/__init__.py` with a docstring only (≤ 5 lines, no re-exports, no `__all__`).
- [X] T042 [P] [US3] Create `src/ohbm2026/ui/text.py` with `markdown_to_plain_text`, `markdown_to_html`, `render_additional_content_markdown`, `question_lookup`, `topic_pair_from_questions`, `topic_parent`, `topic_subcategory`, `primary_topic_from_questions`, `secondary_topic_from_questions`, `topic_subcategories_from_questions` lifted verbatim from `src/ohbm2026/ui.py` (lines 213–322); leaf module.
- [X] T043 [P] [US3] Create `src/ohbm2026/ui/figures.py` with `simplify_image_analysis`, `figure_note_sort_key`, `order_figure_notes`, `build_figure_text_blob`, `load_image_analysis_lookup` lifted from `src/ohbm2026/ui.py` (lines 336–395); leaf module.
- [X] T044 [P] [US3] Verify T037 turns green by running `PYTHONPATH=src .venv/bin/python -m unittest tests.test_ui_text`.
- [X] T045 [P] [US3] Verify T038 turns green by running `PYTHONPATH=src .venv/bin/python -m unittest tests.test_ui_figures`.
- [X] T046 [P] [US3] Create `src/ohbm2026/ui/references.py` with `load_reference_lookup`, `load_neighbors`, `load_distant` lifted from `src/ohbm2026/ui.py` (lines 399–455); leaf module. Verify T039 turns green.
- [X] T047 [P] [US3] Create `src/ohbm2026/ui/manifest.py` with `default_site_output_dir`, `default_export_output_dir`, `ClusterLayerSpec`, plus UI-local copies of `load_json` + `write_json` (the UI keeps a local copy to avoid cross-package imports per `research.md` R5). Imports `UIBuildError` from `ohbm2026.exceptions` (T004 moved it there). Verify T040 turns green.
- [X] T048 [US3] Create `src/ohbm2026/ui/payload_legacy.py` with the legacy embedding-bundle-driven build path lifted from `src/ohbm2026/ui.py` (the pre-Stage-4 functions: `build_ui_payload`, `build_clusters_payload`, related). Imports leaves only: `from ohbm2026.ui.text import …`, `from ohbm2026.ui.figures import …`, `from ohbm2026.ui.references import …`, `from ohbm2026.ui.manifest import …`, plus `from ohbm2026.enrich.cache_paths import default_image_analysis_cache_path` directly (not via T018's `ui.py` rewire — that file is gone after T054). Inherited coverage: `tests/test_ui.py` exercises this path.
- [X] T049 [US3] Create `src/ohbm2026/ui/payload_stage4.py` with `build_ui_payload_from_stage4` lifted from `src/ohbm2026/ui.py` (~line 700); imports leaves only. Inherited coverage: `tests/test_ui_export.py::test_consumes_stage4_rollup` already exercises this end-to-end.
- [X] T050 [US3] Create `src/ohbm2026/ui/cli.py` with `export_ui_main` (line 1227) + `build_ui_main` (line 1308) + private `_cli_option_present` (line 154); imports `from ohbm2026.ui.payload_legacy import …`, `from ohbm2026.ui.payload_stage4 import build_ui_payload_from_stage4`, `from ohbm2026.ui.manifest import …`. Inherited coverage: `tests/test_ui_export.py::test_cli_export_ui_with_analysis_rollup_flag` already exercises this.
- [X] T051 [US3] Rewire `src/ohbm2026/cli.py` dispatch: replace any `from ohbm2026 import ui` and `ui.export_ui_main` / `ui.build_ui_main` references with `from ohbm2026.ui.cli import export_ui_main, build_ui_main`.
- [X] T052 [P] [US3] Rewire `tests/test_ui.py` line 9 `from ohbm2026.ui import (...)` to the explicit submodule paths (`from ohbm2026.ui.text import …`, `from ohbm2026.ui.figures import …`, etc. — match whatever symbols the test currently imports).
- [X] T053 [P] [US3] Rewire `tests/test_ui_export.py` lines 138, 198, 215: `from ohbm2026.ui import build_ui_payload_from_stage4` → `from ohbm2026.ui.payload_stage4 import build_ui_payload_from_stage4`; `from ohbm2026.ui import UIBuildError, build_ui_payload_from_stage4` → `from ohbm2026.exceptions import UIBuildError` + `from ohbm2026.ui.payload_stage4 import build_ui_payload_from_stage4`; `from ohbm2026.ui import export_ui_main` → `from ohbm2026.ui.cli import export_ui_main`.
- [X] T054 [US3] Delete the legacy file:
  ```bash
  git rm src/ohbm2026/ui.py
  ```
- [X] T055 [US3] Verify the contract (per `contracts/ui-api.md`):
  ```bash
  PYTHONPATH=src .venv/bin/python -m ohbm2026.cli export-ui --help >/dev/null
  PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui --help >/dev/null
  grep -rE "from ohbm2026 import ui\b|^import ohbm2026\.ui\s*$" src/ tests/ scripts/
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
  ```
- [X] T056 [US3] Smoke (SC-006): build a post-stage UI bundle and diff against `tmp/stage5-baseline/ui-filelist.txt`:
  ```bash
  KMP_DUPLICATE_LIB_OK=TRUE PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui \
    --raw-input data/primary/abstracts.json \
    --enriched-input data/primary/abstracts_enriched.sqlite \
    --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite \
    --analysis-root data/outputs/analysis \
    --output-dir /tmp/ui-post-stage5
  ls /tmp/ui-post-stage5 | sort > /tmp/ui-post-stage5.filelist
  diff tmp/stage5-baseline/ui-filelist.txt /tmp/ui-post-stage5.filelist
  diff <(jq -S 'del(.timestamp,.code_revision)' /tmp/ui-pre-stage5/manifest.json) \
       <(jq -S 'del(.timestamp,.code_revision)' /tmp/ui-post-stage5/manifest.json)
  ```
- [X] T057 [US3] Commit US3. Use the template in `quickstart.md` §"US3 verification → 5. Commit".

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T058 Final-stage docs sweep: confirm CLAUDE.md, README.md, and `docs/reproducibility-vision.md` each reference the new `ohbm2026.{enrich,layout,ui}` packages and that the SPECKIT block in CLAUDE.md (already updated by `/speckit-plan` to point at Stage 5) still resolves to `specs/007-package-reorg/plan.md`.
- [X] T059 [P] Run the full constitution check:
  ```bash
  .specify/scripts/bash/constitution-check.sh --full
  ```
  Expect exit code 0.
- [X] T060 [P] Run the full success-criteria sweep from `quickstart.md` §"Full-stage final verification (SC-001..SC-007)"; record the seven results in the final commit message.
- [X] T061 Mark all of T001–T060 in this `tasks.md` as `[X]` and commit the tasks-list update. Final stage state: `git status --short` is clean apart from the tasks.md update.
- [X] T062 Push the branch and open the PR to `main` (if Stage 4 / PR #7 has merged) or to `006-analysis-annotation` (if PR #7 is still in review). PR title: `refactor(stage5): package reorg + enrichment cleanup`. Body: summary of US1 / US2 / US3 + the seven SC results from T060.

---

## Dependencies

```
                 ┌──────────────────────┐
                 │ Phase 1: Setup       │
                 │ (T001–T003)          │
                 └──────────┬───────────┘
                            │
                 ┌──────────▼───────────┐
                 │ Phase 2: Foundational│
                 │ (T004–T005)          │
                 └──────────┬───────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
   ┌────────▼────────┐ ┌────▼────┐ ┌───────▼────────┐
   │ US1: enrich     │ │ US2:    │ │ US3: UI split  │
   │ cleanup         │ │ layout  │ │ (depends on    │
   │ (T006–T023)     │ │ park    │ │ T004 for       │
   │ P1 — MVP        │ │ (T024–  │ │ UIBuildError)  │
   │ 4 new test files│ │ T036)   │ │ (T037–T057)    │
   │ + impl + smoke  │ │ P2      │ │ 4 new test     │
   │                 │ │ no new  │ │ files + impl   │
   │                 │ │ tests   │ │ + smoke        │
   └────────┬────────┘ └────┬────┘ └───────┬────────┘
            │               │              │
            └───────────────┼──────────────┘
                            │
                 ┌──────────▼───────────┐
                 │ Phase 6: Polish      │
                 │ (T058–T062)          │
                 └──────────────────────┘
```

- **Cross-story dependency**: T004 (move `UIBuildError` to `ohbm2026.exceptions`) MUST land before US3's T040 (its test imports from `ohbm2026.exceptions`) and T047 (its implementation imports from there too). T004 has zero behavior change for US1 / US2.
- **Within US1**: tests-first ordering — T006–T009 land before their counterpart impl modules T010–T013. Importer-rewire tasks (T014–T019) MUST follow the four new submodules existing. T020 (delete legacy files) MUST be last in US1 (every consumer must be rewired first).
- **Within US3**: tests-first ordering — T037–T040 land before T042–T047. Mid + trunk modules (T048–T050) depend on leaves. CLI + test rewires (T051–T053) follow. T054 (delete `ui.py`) is last.
- **US1 → US2 → US3** is the **recommended** order (matches priority + spec.md sequencing in §Phasing), but each story is independent: US2 can ship before US1 if review wants; US3 can ship before US2; etc., as long as T004 has landed.

## Parallel execution examples

### Within US1

All 4 new tests and 3 leaf submodule creates run fully in parallel:

```text
T006 [P] [US1]: write tests/test_enrich_text.py
T007 [P] [US1]: write tests/test_enrich_cache_paths.py
T008 [P] [US1]: write tests/test_enrich_markdown_render.py
T009 [P] [US1]: write tests/test_enrich_openai_compat.py
T010 [P] [US1]: create enrich/text.py
T011 [P] [US1]: create enrich/cache_paths.py
T013 [P] [US1]: create enrich/openai_compat.py
T012    [US1]: create enrich/markdown_render.py    (depends on T010 for the text import)
```

Then the 6 importer rewires run in parallel after the 4 submodules exist:

```text
T014    [US1]: rewire enrich/claims.py
T015    [US1]: rewire enrich/stage.py
T016    [US1]: rewire enrich/openalex.py
T017 [P] [US1]: rewire embed/components.py
T018 [P] [US1]: rewire ui.py (the line 18 import only)
T019 [P] [US1]: rewire scripts/reference_split_regression_probe.py
```

### Within US3

All 4 leaf tests + 4 leaf creates run fully in parallel:

```text
T037 [P] [US3]: write tests/test_ui_text.py
T038 [P] [US3]: write tests/test_ui_figures.py
T039 [P] [US3]: write tests/test_ui_references.py
T040 [P] [US3]: write tests/test_ui_manifest.py
T041 [P] [US3]: ui/__init__.py
T042 [P] [US3]: ui/text.py
T043 [P] [US3]: ui/figures.py
T046 [P] [US3]: ui/references.py
T047 [P] [US3]: ui/manifest.py    (depends on T004 from foundational)
```

Mid + trunk modules sequential after leaves:

```text
T048    [US3]: ui/payload_legacy.py
T049    [US3]: ui/payload_stage4.py    (can run parallel with T048)
T050    [US3]: ui/cli.py    (depends on T048 + T049 + T047)
T051    [US3]: cli.py rewire    (depends on T050)
T052 [P] [US3]: tests/test_ui.py rewire
T053 [P] [US3]: tests/test_ui_export.py rewire
T054    [US3]: git rm src/ohbm2026/ui.py    (depends on every consumer being rewired)
```

## Implementation strategy

**Recommended sequence**: Phase 1 → Phase 2 → US1 (tests → impl → rewire → delete → verify → smoke) → US2 → US3 (tests → impl → rewire → delete → verify → smoke) → Polish.

**MVP**: US1 alone. If review pushback forces stopping after US1, the project is still better off: `enrichment.py` is gone, dead code is deleted, the `enrich/` package is the canonical home for Stage 2 / 2.1, and four focused test files cover the new submodules. US2 + US3 stay queued.

**Per-story commit messages** must record:
- For US1: the post-stage test count (`(583 − 22 + N_new) passing / 1 pre-existing`, where N_new = total tests across `test_enrich_*.py`), the list of deleted symbols, the four new submodules + four new test files.
- For US2: the 3 module moves, the 15 script moves, the `layout/__init__.py` docstring summary, and the three docs that gained the "parked" note.
- For US3: the 7-submodule split, the `UIBuildError` relocation to `ohbm2026.exceptions`, the four new leaf test files, the inherited coverage notes for payload_legacy / payload_stage4 / cli, the SC-006 file-list diff result.

## Format validation

All 62 tasks above conform to the strict checklist format: leading `- [ ]`, sequential `T###` ID, optional `[P]` parallelism marker, `[US1] / [US2] / [US3]` story label on user-story-phase tasks only (Setup / Foundational / Polish tasks carry no story label per the rule), and a description that names the file path(s) being touched.
