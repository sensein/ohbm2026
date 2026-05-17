# Phase 1 — Data Model (Stage 5 Package Reorganization)

This stage produces no new persistent artifacts. The "data model" here is the **package layout**: which symbols live in which submodule after the cleanup, and the explicit import contracts each new submodule exposes.

## 1. `ohbm2026.enrich` package (after US1)

```
src/ohbm2026/enrich/
├── __init__.py            # docstring only; no re-export shell
├── cache_paths.py         # NEW
├── claims.py              # unchanged
├── figures.py             # unchanged
├── flex_tier.py           # unchanged
├── image_quality.py       # unchanged
├── markdown_render.py     # NEW
├── openai_compat.py       # NEW
├── openalex.py            # rewired import of html_to_markdown → enrich.text
├── references.py          # unchanged
├── stage.py               # rewired import of markdown helpers → enrich.markdown_render
├── storage.py             # unchanged
└── text.py                # NEW
```

### `enrich/text.py`

**Owned symbols** (moved from `enrichment.py`):

| Symbol | Kind | Pre-stage consumers |
|---|---|---|
| `html_to_markdown(value: str \| None) -> str` | function | `enrich/openalex.py`, `enrich/claims.py`, `enrich/markdown_render.py`, plus 7 more |
| `HTMLToMarkdownParser` | class | `enrich/text.html_to_markdown` backing parser |

**Imports allowed** (leaf module): stdlib only (`html.parser.HTMLParser`).

### `enrich/cache_paths.py`

**Owned symbols** (moved from `enrichment.py`):

| Symbol | Kind | Notes |
|---|---|---|
| `default_image_analysis_cache_path(...)` | function | per CLAUDE.md, cache keying is `sha256(input || model_id)` — the default-path helpers compute the on-disk location |
| `default_claim_analysis_cache_path(...)` | function | |
| `load_json(path: Path) -> dict[str, Any]` | function | generic JSON I/O — kept here because the cache helpers below need it; widely reused |
| `write_json(path: Path, payload: dict[str, Any]) -> None` | function | |
| `load_image_analysis_cache(path: Path) -> dict[str, Any]` | function | |
| `load_claim_analysis_cache(path: Path) -> dict[str, Any]` | function | |
| `refresh_analysis_cache_stats(...)` | function | |

**Imports allowed** (leaf module): stdlib only.

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

### `enrich/openai_compat.py`

**Owned symbols** (moved from `enrichment.py`):

| Symbol | Kind | Notes |
|---|---|---|
| `openai_chat_multimodal(...)` | function | Legacy multimodal-LLM call used by Stage 2.1's figure-fallback path |
| `openai_chat_multimodal_batch(...)` | function | Batched variant |
| `resolve_openai_api_key(...)` | function | Read key from env, fall back to keyring |
| `parse_jsonish_content(...)` | function | Tolerant parser for legacy LLM responses |
| `image_to_data_url(...)` | function | base64-encode JPEG/PNG for multimodal API |

**Imports allowed**: stdlib + `openai` + `keyring` (no intra-package imports).

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
├── figures.py             # NEW
├── manifest.py            # NEW
├── payload_legacy.py      # NEW — embedding-bundle-driven path
├── payload_stage4.py      # NEW — rollup-driven path (build_ui_payload_from_stage4)
├── references.py          # NEW
└── text.py                # NEW
```

### Submodule boundaries

Per research.md R5, dependencies flow **leaf → mid → trunk**:

- **Leaves** (no intra-`ui/` imports): `ui/text.py`, `ui/figures.py`, `ui/references.py`, `ui/manifest.py`.
- **Mid** (import from leaves only): `ui/payload_legacy.py`, `ui/payload_stage4.py`.
- **Trunk**: `ui/cli.py` imports from `ui/payload_legacy` + `ui/payload_stage4` + `ui/manifest`.

### `ui/text.py` — owned symbols

| Symbol | Pre-stage location in `ui.py` |
|---|---|
| `markdown_to_plain_text(text)` | line 258 |
| `markdown_to_html(text)` | line 270 |
| `render_additional_content_markdown(value)` | line 316 |
| `question_lookup(abstract)` | line 213 |
| `topic_pair_from_questions(...)` | line 220 |
| `topic_parent(...)` | line 224 |
| `topic_subcategory(...)` | line 228 |
| `primary_topic_from_questions(...)` | line 236 |
| `secondary_topic_from_questions(...)` | line 240 |
| `topic_subcategories_from_questions(...)` | line 247 |

### `ui/figures.py` — owned symbols

| Symbol | Pre-stage location |
|---|---|
| `simplify_image_analysis(record)` | line 336 |
| `figure_note_sort_key(record)` | line 349 |
| `order_figure_notes(records)` | line 361 |
| `build_figure_text_blob(enriched_abstract)` | line 365 |
| `load_image_analysis_lookup(path)` | line 386 |

### `ui/references.py` — owned symbols

| Symbol | Pre-stage location |
|---|---|
| `load_reference_lookup(path)` | line 399 |
| `load_neighbors(path, top_k)` | line 439 |
| `load_distant(path, bottom_k)` | line 447 |

### `ui/manifest.py` — owned symbols

| Symbol | Pre-stage location |
|---|---|
| `default_site_output_dir(...)` | line 158 |
| `default_export_output_dir(...)` | line 184 |
| `load_json(path)` | line 204 (a separate copy from `enrich/cache_paths.py:load_json` — the UI one stays here to avoid cross-package imports) |
| `write_json(path, payload)` | line 208 (same — UI-local copy) |
| `ClusterLayerSpec` | line 195 (dataclass) |
| `UIBuildError` | line 150 (exception class) |

Note: `UIBuildError` could equally live in `ohbm2026.exceptions`. For symmetry with the existing pattern where most stages have their typed errors under `exceptions.py`, **move it there** in this stage, and `ui/manifest.py` imports it from `ohbm2026.exceptions`.

### `ui/payload_legacy.py` — owned symbols

The full embedding-bundle-driven build path that consumed `data/outputs/embeddings/<bundle>/*.npy` directly (pre-Stage 4). The functions live verbatim; only the imports are rewired to point at the leaf submodules.

### `ui/payload_stage4.py` — owned symbols

| Symbol | Pre-stage location |
|---|---|
| `build_ui_payload_from_stage4(...)` | line ~700 |

The Stage 4 rollup-driven path: reads `annotations__<state-key>.sqlite` + per-bundle `topics.json` + raw + enriched corpus; assembles the `manifest.json` / `clusters.json` / `projection.umap.json` / `abstracts.{search,detail}.json` / `relations.json` / `facets.json` payloads.

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
