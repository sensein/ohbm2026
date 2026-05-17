# Phase 1 — Data Model (Stage 5 Package Reorganization)

This stage produces no new persistent artifacts. The "data model" here is the **package layout**: which symbols live in which submodule after the cleanup, and the explicit import contracts each new submodule exposes.

## 1. `ohbm2026.enrich` package (after US1)

```
src/ohbm2026/enrich/
├── __init__.py            # docstring only; no re-export shell
├── claims.py              # unchanged
├── figures.py             # unchanged
├── flex_tier.py           # unchanged
├── image_quality.py       # unchanged
├── markdown_render.py     # NEW
├── openalex.py            # rewired import of html_to_markdown → enrich.text
├── references.py          # unchanged
├── stage.py               # rewired import of markdown helpers → enrich.markdown_render
├── storage.py             # unchanged
└── text.py                # NEW
```

**Note (Stage 5 implementation — final state after the rework)**: two originally planned submodules (`enrich/cache_paths.py` and `enrich/openai_compat.py`) were not retained. Per the clean-rework directive ("we don't need to maintain backwards compatibility"):

- **`enrich/openai_compat.py`** — the legacy OpenAI/Ollama multimodal helpers (`openai_chat_multimodal`, `openai_chat_multimodal_batch`, `resolve_openai_api_key`, `parse_jsonish_content`, `image_to_data_url`) had zero real importers. Stage 2.1's agentic path uses `enrich/flex_tier.py` + `enrich/figures.py` directly. These symbols were deleted, not relocated.
- **`enrich/cache_paths.py`** — initially created with `default_image_analysis_cache_path` / `default_claim_analysis_cache_path` + the 5 legacy model-ID constants + `load_json` / `write_json`. The full-tree consumer audit (post-bot-review of PR #8) found: the legacy cache-path helpers had ONE consumer (`ui/payload.py`'s legacy default), and `load_json` / `write_json` had zero real importers (all 10+ "consumers" defined their own local copies). The whole module was deleted; the canonical `load_json` / `write_json` moved to `ohbm2026/util/json_io.py` (see §1.5 below).

### `enrich/text.py`

**Owned symbols** (moved from `enrichment.py`):

| Symbol | Kind | Pre-stage consumers |
|---|---|---|
| `html_to_markdown(value: str \| None) -> str` | function | `enrich/openalex.py`, `enrich/claims.py`, `enrich/markdown_render.py`, plus 7 more |
| `HTMLToMarkdownParser` | class | `enrich/text.html_to_markdown` backing parser |

**Imports allowed** (leaf module): stdlib only (`html.parser.HTMLParser`).

### `enrich/cache_paths.py` (NOT CREATED — see Note above)

The Stage 2.1 production cache key is `sha256(input || model_id)` computed inside `enrich/figures.py`, `enrich/claims.py`, and `enrich/references.py` directly. No helper module is needed. The legacy `default_*_cache_path` helpers + their 5 legacy model-ID constants were deleted; `ui/payload.py`'s legacy default reverted to a static string (`"data/image_analyses_openai.json"`).

### §1.5. `ohbm2026/util/` package (added in the rework)

```
src/ohbm2026/util/
├── __init__.py     # docstring only
└── json_io.py      # `load_json`, `write_json` — canonical
```

`load_json` / `write_json` were duplicated in **11 places** across the tree before the rework (`titles.py`, `category_evaluation.py`, `category_rollup.py`, `ui/payload.py`, `enrich/cache_paths.py`, `enrich/openalex.py`, `analyze/storage.py`, plus 4 in `scripts/`). The 6 src/ duplicates were consolidated into `ohbm2026.util.json_io`; each consumer's import line was rewired and local def deleted. (Scripts/-side duplicates remain — defer to a future operational cleanup; the `layout/` package is parked verbatim.)

`util/json_io.write_json` is **not** atomic — callers that need atomic temp+rename keep their own helper (`embed/storage.atomic_write_json`, `fetch/stage._atomic_write_json`, `enrich/stage._atomic_write_json`, `analyze/provenance._atomic_write_json`). Those 4 variants write different JSON formats (compact vs `indent=2`, different sort_keys) — each is tied to an on-disk artifact contract and intentionally not consolidated.

### `enrich/markdown_render.py`

**Owned symbols** (moved from `enrichment.py`):

| Symbol | Kind |
|---|---|
| `build_sections_markdown(abstract: dict) -> tuple[dict, list]` | function |
| `build_claim_manuscript_markdown(...)` | function |
| `render_abstract_markdown(title: str, sections_markdown: dict) -> str` | function |
| `filter_content_questions_markdown(items: list[dict]) -> list[dict]` | function |
| `is_content_question(question_name: str \| None) -> bool` | function |
| `question_to_section(question_name: str \| None) -> str \| None` | function |
| `normalize_question_name(question_name: str \| None) -> str` | function |
| `parse_list_value(raw_value: str \| None) -> list[str]` | function |

**Imports allowed**: `enrich/text.py` only (for `html_to_markdown`).

### `enrich/openai_compat.py` (NOT CREATED — see Note above)

The legacy `openai_chat_multimodal`, `openai_chat_multimodal_batch`, `resolve_openai_api_key`, `parse_jsonish_content`, `image_to_data_url` symbols were deleted with `enrichment.py`. None had a real consumer in the production code paths. Stage 2.1's actual multimodal call lives in `enrich/figures.py` via the OpenAI Responses API + `enrich/flex_tier.py` retry wrapper — not via these legacy helpers.

### Deleted symbols (no new home)

See `research.md` R1 for the full list of ~40 deleted symbols, including:
- All `cllm`-prefixed paths (Stage 2.1 replaced cllm with the agentic OpenAI Responses API per CLAUDE.md FR-014).
- All `enrich_main` / `analyze_figures_main` / `extract_claims_main` + their parser builders (commands removed in Stage 2 rewire).
- All Ollama helpers (`ollama_chat_multimodal`, `ensure_ollama_model`, `ollama_model_status`).
- All 22 zero-consumer symbols.

### Deleted files

- `src/ohbm2026/enrichment.py` (the whole legacy module is gone).
- `tests/test_enrichment.py` (tests-only consumer of the deleted Stage 2 path; see research.md R3).
- `scripts/time_figure_enrichment.py` (legacy benchmark of the deleted `analyze_figures` entry point).

### `EnrichmentError`

This exception class is **already canonical** at `ohbm2026.exceptions.EnrichmentError`. `enrichment.py:72`'s local re-declaration is a duplicate; it's removed in this stage. All 28 importers currently use either path; they normalize to `from ohbm2026.exceptions import EnrichmentError` in this stage.

## 2. `ohbm2026.layout` package (after US2)

```
src/ohbm2026/layout/
├── __init__.py            # docstring only — names the package as parked
├── nocd_experiments.py    # moved verbatim
├── poster_layout.py       # moved verbatim
└── poster_sequencing.py   # moved verbatim
```

### `layout/__init__.py`

Single docstring, ≤ 5 lines:

```python
"""Parked package — poster-layout / sequencing / NOCD code preserved from
the pre-Stage-5 surface. Not actively maintained. Revive when a new
organizer cycle needs poster work; see specs/007-package-reorg/spec.md FR-003.
"""
```

No re-exports. No `__all__`. No `warnings.warn(...)`.

### Content preservation

Each of the three `.py` files moves **verbatim** — same byte content, same line numbers — with one exception: the `from ohbm2026.poster_layout import …` line inside `poster_sequencing.py` becomes `from ohbm2026.layout.poster_layout import …`. No other inline refactors during the move.

### `scripts/layout/` directory (after US2)

```
scripts/layout/
├── analyze_poster_layout.py
├── benchmark_poster_sequencing.py
├── build_layout_review_hub.py
├── check_layout_review.py
├── compare_poster_layout_proposals.py
├── extract_layout_geometry.py
├── generate_semantic_layout_proposals.py
├── generate_target_poster_layout_proposals.py
├── optimize_poster_layout.py
├── plot_poster_layout_day_comparison.py
├── plot_poster_layout_floorplan.py
├── run_nocd_checkpoint_sweep_experiment.py
├── run_nocd_classic_predict_experiment.py
├── write_layout_category_summaries.py
└── write_layout_reassignment_summaries.py
```

### Script path-resolution adjustments

Each script that does `Path(__file__).parents[N]` to find the repo root or import `src/` must shift its `parents[N]` by one (since the script is now one directory deeper). The two patterns to fix are:

- `REPO_ROOT = Path(__file__).resolve().parents[1]` → `parents[2]`
- `sys.path.insert(0, str(REPO_ROOT / "src"))` — same value but recompute `REPO_ROOT` first

Each script is touched in the same commit that moves it.

## 3. `ohbm2026.ui` package (after US3)

```
src/ohbm2026/ui/
├── __init__.py            # docstring only; no re-export shell
├── cli.py                 # NEW — export_ui_main + build_ui_main + argparse
└── payload.py             # NEW — all builders + helpers (markdown / figures /
                           #       references / manifest / cluster-layer /
                           #       semantic-search / facets / pattern-matching /
                           #       export_ui_bundle / copy_ui_assets /
                           #       publish_ui_bundle / build_ui_payload /
                           #       build_ui_payload_from_stage4)
```

**Note (Stage 5 implementation)**: the spec originally illustrated a more granular 7-submodule layout (`text.py`, `figures.py`, `references.py`, `manifest.py`, `payload_legacy.py`, `payload_stage4.py`, `cli.py`). The implementation went with the pragmatic 2-submodule split above — FR-005's literal contract is satisfied (the `ui/` package boundary exists; consumers import from explicit submodules; `__init__.py` is 1 line). The fine-grained breakdown can land as a follow-up refactor without churn because the package boundary is now established. The owned-symbol enumeration below is preserved as documentation of where each function would live if/when the finer split happens.

### Submodule boundaries (as implemented)

- **Trunk**: `ui/cli.py` — argparse builders + entry points + the private `_cli_option_present` helper. Imports from `ui/payload.py` only.
- **Leaf**: `ui/payload.py` — everything else. Self-contained; imports from `ohbm2026.enrich.cache_paths.default_image_analysis_cache_path` + `ohbm2026.analyze.storage.parse_string_list_value` + `ohbm2026.exceptions.UIBuildError` (no other intra-`ui/` imports because there's only one submodule body).

### Owned-symbol map (for a future finer-grained split)

The 2-submodule landing keeps the following groupings inside `ui/payload.py`. If a contributor later wants to split, these are the natural boundaries:

**`ui/text.py` candidates** (lines 257–322 in the pre-stage `ui.py`):
`markdown_to_plain_text`, `markdown_to_html`, `render_additional_content_markdown`, `question_lookup`, `topic_pair_from_questions`, `topic_parent`, `topic_subcategory`, `primary_topic_from_questions`, `secondary_topic_from_questions`, `topic_subcategories_from_questions`.

**`ui/figures.py` candidates** (lines 335–395):
`simplify_image_analysis`, `figure_note_sort_key`, `order_figure_notes`, `build_figure_text_blob`, `load_image_analysis_lookup`.

**`ui/references.py` candidates** (lines 398–455):
`load_reference_lookup`, `load_neighbors`, `load_distant`.

**`ui/manifest.py` candidates** (lines 157–211):
`default_site_output_dir`, `default_export_output_dir`, `ClusterLayerSpec`, plus UI-local `load_json` / `write_json` copies.

**`ui/payload_legacy.py` candidates**: `build_ui_payload`, `build_clusters_payload`, related helpers around the legacy embedding-bundle-driven path.

**`ui/payload_stage4.py` candidates**: `build_ui_payload_from_stage4` (the Stage 4 rollup-driven path).

`UIBuildError` has been moved to `ohbm2026.exceptions` (foundational task T004); `ui/payload.py` imports it from there.

### `ui/cli.py` — owned symbols

| Symbol | Pre-stage location |
|---|---|
| `export_ui_main(argv)` | line 1227 |
| `build_ui_main(argv)` | line 1308 |
| `_cli_option_present(...)` | line 154 (private helper; tags along with `export_ui_main`) |

### Deleted files

- `src/ohbm2026/ui.py` (the monolithic file is gone after US3).

### Consumer rewiring (US3)

- `src/ohbm2026/cli.py`: replace `from ohbm2026 import ui` + dispatch with explicit `from ohbm2026.ui.cli import export_ui_main, build_ui_main`.
- `tests/test_ui.py`: 1 import block to rewrite.
- `tests/test_ui_export.py`: 3 import blocks to rewrite (lines 138, 198, 215).

## 4. Test surface after Stage 5

| Path | Before | After | Notes |
|---|---|---|---|
| `tests/test_enrichment.py` | 658 LOC, class-based, ~?-test count (TBD) | **deleted** | Tested only the legacy Stage 2 path; see research.md R3. |
| `tests/test_openalex.py` | passes | passes | Import path for `html_to_markdown` updates from `enrichment` to `enrich.text`. |
| `tests/test_ui.py` | passes | passes | Imports rewire to `ui/*`. |
| `tests/test_ui_export.py` | 3 tests pass | 3 tests pass | Imports rewire to `ui/payload_stage4`, `ui/cli`. |
| `tests/test_nocd_experiments.py` | passes | passes | Import path updates from `ohbm2026.nocd_experiments` to `ohbm2026.layout.nocd_experiments`. |
| `tests/test_poster_sequencing.py` | passes | passes | Import path updates analogously. |
| `tests/test_plot_poster_layout_floorplan.py` | 1 pre-existing failure | 1 pre-existing failure | Import path updates; failure unchanged. |
| `tests/test_embed_components.py` | passes | passes | If it imports from `enrichment`, rewires to `enrich.markdown_render` / `enrich.text`. |
| **Net** | 583 tests / 1 pre-existing | (583 − N) tests / 1 pre-existing | where N is the test count of the deleted `tests/test_enrichment.py`. |

Post-stage baseline is recorded in the final commit message.
