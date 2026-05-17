# Phase 0 — Research (Stage 5 Package Reorganization)

This document resolves the open questions identified by `/speckit-plan` and produces the concrete categorization the tasks.md phase will execute.

## R1 — How do we categorize the 62 symbols in `enrichment.py`?

### Decision

Three buckets, applied symbol-by-symbol per the grep-driven fan-out:

1. **Keep & move** (still imported by Stage 2.1, embed, UI, or analyze): redistribute into focused `enrich/` submodules with names that reflect purpose.
2. **Keep & move (legacy-test-only)**: a small subset is only imported by `tests/test_enrichment.py` plus a single legacy script. We **delete the test file and the script** rather than preserve the dead helpers (see R3).
3. **Delete outright** (no consumers): 22+ symbols have zero importers across `src/`, `tests/`, `scripts/`. They go.

### Rationale

The user's "OK to skip tests" guidance, combined with FR-002 ("Helpers that have no current importer MUST be deleted, not preserved"), forces a delete-if-unused policy. Preserving dead code under new names would re-export the same readability problem the cleanup is meant to solve.

### Alternatives considered

- **Keep all helpers verbatim and just relocate them**: rejected. The whole point is to shrink the surface area, not relocate dead code.
- **Two-step cleanup (move first, prune later)**: rejected. The unused symbols are knowable today; pruning later costs another full review cycle.

### Concrete categorization (raw counts from `grep -rE '\bSYMBOL\b' src/ tests/ scripts/`, minus `enrichment.py` self-references)

| Symbol | Consumers (raw count) | New home | Notes |
|---|---|---|---|
| `EnrichmentError` | 28 | (delete redundant local copy) | Already lives at `ohbm2026.exceptions.EnrichmentError`; `enrichment.py:72`'s re-declaration is removed. |
| `load_json` / `write_json` | 18 / 24 | `enrich/cache_paths.py` | Generic JSON I/O used across the enrichment cache surface. |
| `html_to_markdown` | 10 | `enrich/text.py` | Used by `openalex.py`, `markdown_render`, etc. |
| `HTMLToMarkdownParser` | 1 | `enrich/text.py` | Backing class for `html_to_markdown`; moves with it. |
| `build_claim_manuscript_markdown` | 8 | `enrich/markdown_render.py` | Stage 2.1 claims pipeline depends on this. |
| `build_sections_markdown` | 6 | `enrich/markdown_render.py` | |
| `analyze_figures` | 6 | (delete) | Legacy Stage 2 entry point. Only consumers are `tests/test_enrichment.py` (legacy) + `scripts/time_figure_enrichment.py` (legacy benchmark) — both deleted in this stage. Stage 2.1's figure runner is `enrich/figures.py`. |
| `enrich_database` | 5 | (delete) | Legacy Stage 2 entry; only `tests/test_enrichment.py` consumes it. |
| `default_image_analysis_cache_path` | 4 | `enrich/cache_paths.py` | |
| `question_to_section` | 4 | `enrich/markdown_render.py` | Used by markdown builders. |
| `parse_jsonish_content` | 4 | `enrich/openai_compat.py` | Tolerant JSON parser for legacy multimodal-LLM responses; still touched by `enrich/claims.py`'s fallback path. |
| `extract_claims_with_cllm` | 3 | (delete) | cllm-based claim path was replaced by Stage 2.1's agentic Responses API call. Per CLAUDE.md: "Stage 2.1 replaces the `cllm`-based claim-extraction path with the agentic OpenAI Responses API call in `stage2_claims.py`." Truly dead. |
| `default_claim_analysis_cache_path` | 2 | `enrich/cache_paths.py` | |
| `is_content_question` | 2 | `enrich/markdown_render.py` | |
| `filter_content_questions_markdown` | 2 | `enrich/markdown_render.py` | |
| `render_abstract_markdown` | 2 | `enrich/markdown_render.py` | |
| `load_claim_analysis_cache` | 2 | `enrich/cache_paths.py` | |
| `image_to_data_url` | 2 | `enrich/openai_compat.py` | |
| `openai_chat_multimodal_batch` | 2 | `enrich/openai_compat.py` | |
| `resolve_openai_api_key` | 2 | `enrich/openai_compat.py` | |
| `build_cllm_environment` | 2 | (delete) | cllm-path: dead per CLAUDE.md. |
| `load_cllm_verification_module` | 1 | (delete) | cllm-path: dead. |
| `extract_claims_from_cllm_module` | 2 | (delete) | cllm-path: dead. |
| `build_enrich_parser` | 2 | (delete) | Legacy CLI parser; the `enrich` subcommand was REMOVED in Stage 2 rewire (CLAUDE.md FR-014). |
| `enrich_main` | 2 | (delete) | Same — REMOVED in Stage 2 rewire. |
| `build_figure_analysis_parser` | 2 | (delete) | Same — `analyze-figures` REMOVED in Stage 2 rewire. |
| `analyze_figures_main` | 2 | (delete) | Same. |
| `build_claim_extraction_parser` | 2 | (delete) | Same — `extract-claims` REMOVED. |
| `extract_claims_main` | 1 | (delete) | Same. |
| `OllamaModelStatus` | 1 | (delete) | Used only by the dead cllm path. |
| `_cli_option_present` | 1 | (delete) | Used only by `enrich_main`. |
| `HTMLToMarkdownParser` | 1 | `enrich/text.py` | Backing parser. |
| `normalize_question_name` | 1 | `enrich/markdown_render.py` | |
| `parse_list_value` | 1 | `enrich/markdown_render.py` | |
| `load_image_analysis_cache` | 1 | `enrich/cache_paths.py` | |
| `refresh_analysis_cache_stats` | 1 | `enrich/cache_paths.py` | |
| `openai_chat_multimodal` | 1 | `enrich/openai_compat.py` | Used by Stage 2.1's figure fallback path. |
| **22 zero-consumer symbols** | 0 | (delete) | `_database_input_digest`, `unique_preserve_order`, `build_section_markdown_fields`, `content_question_sort_key`, `figure_analysis_sort_key`, `sort_figure_analysis_entries`, `render_claim_section_markdown`, `render_additional_content_questions_markdown`, `render_figure_analyses_markdown`, `save_image_analysis_cache`, `save_claim_analysis_cache`, `_update_cache_metadata`, `analysis_entry_succeeded`, `claim_analysis_entry_completed`, `refresh_claim_analysis_cache_stats`, `estimate_openai_payload_bytes`, `ollama_model_status`, `ensure_ollama_model`, `ollama_chat_multimodal`, `normalize_openai_batch_response`, `iter_openai_batch_assets`, `extract_original_keywords`, `parse_enrich_args`, `parse_claim_extraction_args`, `parse_figure_analysis_args` |

**Net result for the `enrich/` package**: 4 new submodules (`text.py`, `cache_paths.py`, `markdown_render.py`, `openai_compat.py`) carrying ~16 still-used symbols; ~40 symbols deleted (the explicit "unused" set plus the legacy cllm + legacy-CLI surface).

## R2 — How do we mark the `layout/` package as parked?

### Decision

Three-pronged: package-level docstring + docs notes + minimal `__init__.py`.

1. `src/ohbm2026/layout/__init__.py` carries a short docstring: *"Parked package. Poster-layout / sequencing / NOCD code preserved verbatim from the pre-Stage-5 surface. Not actively maintained. Revive when a new organizer cycle needs poster work; see specs/007-package-reorg/spec.md FR-003."* No runtime warning.
2. CLAUDE.md adds a one-paragraph note under the existing module-list section: *"`layout/` (parked) — poster_layout, poster_sequencing, nocd_experiments. Preserved for future revival; not actively maintained. Tests under `tests/test_poster_sequencing.py` + `tests/test_nocd_experiments.py` + `tests/test_plot_poster_layout_floorplan.py` still run via import-path updates."*
3. README.md's "Track B" section (which already calls out poster layout as exploratory) gets the explicit "parked" wording.
4. `docs/reproducibility-vision.md` mirrors the parking note in the Track B subsection.

### Rationale

A package-level runtime warning (e.g., `DeprecationWarning`) would noisily pollute test output even though nothing in `layout/` is broken. A pure-docs signal preserves the code without making it harder to revive. SC-007 verifies the docs note's presence via a single `grep` invocation.

### Alternatives considered

- **Delete the layout code entirely**: rejected. The user said "parked for the moment" — they want preservation, not deletion.
- **`warnings.warn(DeprecationWarning, …)` on package import**: rejected. Noise, no signal. The user is aware; the docs note is enough.

## R3 — What happens to `tests/test_enrichment.py`?

### Decision

**Delete it** as part of US1 (enrichment cleanup), along with `scripts/time_figure_enrichment.py`.

### Rationale

`tests/test_enrichment.py` exclusively tests the legacy Stage 2 path: `enrich_database`, `analyze_figures`, `extract_claims_*`, `build_*_parser` — all of which were REMOVED in the Stage 2 rewire (CLAUDE.md, FR-014). The test file is testing dead code that has been replaced by the Stage 2.1 `enrich-abstracts` orchestrator (`enrich/stage.py`) and its production runners (`enrich/figures.py`, `enrich/claims.py`, `enrich/references.py`).

Stage 2.1 has its own test coverage:
- `tests/test_stage2_figures.py`
- `tests/test_stage2_claims.py`
- `tests/test_stage2_references.py`
- `tests/test_enrich_storage.py` (if present) / `tests/test_enrich_stage.py`

Keeping `tests/test_enrichment.py` after deleting the symbols it imports would require either (a) preserving the dead Stage 2 code (defeats the cleanup) or (b) rewriting every test to use the Stage 2.1 surface (which would duplicate existing coverage). Deletion is the only clean option.

`scripts/time_figure_enrichment.py` is a legacy benchmark of the deleted `analyze_figures` entry point; it has no replacement value because Stage 2.1's `enrich/figures.py` is benchmarked by the orchestrator's per-bundle `duration_seconds` metric.

### Test-count accounting

The pre-stage baseline is **583 tests, 1 pre-existing failure** (`test_plot_poster_layout_floorplan`).

Removing `tests/test_enrichment.py` drops some passing tests from the suite. Counting them ahead of time (so the baseline doesn't surprise reviewers):

```bash
PYTHONPATH=src .venv/bin/python -m unittest tests.test_enrichment 2>&1 | tail -1
```

The post-stage baseline will be 583 − N (where N = test count of `test_enrichment.py`), still with the same 1 pre-existing failure. Document this in the commit message.

### Alternatives considered

- **Rewrite `test_enrichment.py` against the Stage 2.1 surface**: rejected. Duplicates existing Stage 2.1 coverage; out of scope for a refactor stage that the user explicitly said could skip tests.
- **Keep the dead helpers + dead test together**: rejected. The whole point of the cleanup is to remove dead code.

## R4 — How do we sequence the three commit series given PR #7 is in review?

### Decision

Stage 5 work starts on a **new feature branch `007-package-reorg` cut from `main`** if PR #7 has landed by the time Stage 5 starts; otherwise it stacks on top of `006-analysis-annotation` and rebases when PR #7 lands.

### Rationale

Stage 5 touches files that PR #7 modifies (e.g., `cli.py`'s import block, the `enrich/` package, the `analyze/` package's docstrings). Branching from `main` post-#7 produces a clean refactor PR with no Stage 4 diff noise; stacking on #7 forces a rebase but unblocks Stage 5 work today.

If PR #7 takes more than ~24 hours to review, stacking is the right call. If review is fast, branch from `main`.

### Alternatives considered

- **Wait for PR #7 to land before starting Stage 5**: rejected. The work is large; review may take time; we can do the planning + research now and the implementation can stack/rebase.
- **Merge Stage 5 into the #7 branch**: rejected. That dilutes the Stage 4 review with refactor noise.

## R5 — How is the `ui/` split structured to avoid circular imports?

### Decision

The dependency direction in the new package is strictly **leaf → trunk**:

- Leaf modules (no intra-package imports): `ui/text.py`, `ui/figures.py`, `ui/references.py`, `ui/manifest.py`.
- Mid modules (import from leaves only): `ui/payload_legacy.py`, `ui/payload_stage4.py` — both import from `ui/text.py` + `ui/figures.py` + `ui/references.py` + `ui/manifest.py`.
- Trunk module: `ui/cli.py` — imports `ui/payload_legacy` + `ui/payload_stage4` + `ui/manifest`.

`ui/__init__.py` is a docstring only; no re-export shell.

### Rationale

The Stage 4 reorganization caught a circular-import bug between `analyze/__init__.py` and `exceptions.py` (see `analyze/__init__.py` warmup comment). Applying the leaf-mid-trunk discipline up front avoids re-discovering the same class of bug. The same rule was applied to `enrich/` (figures/claims/references are leaves; `stage.py` is trunk).

### Alternatives considered

- **Flat module set with cross-imports**: rejected. Cross-imports are the source of circular bugs; the leaf-mid-trunk pattern is explicit and easy to enforce.
- **`from . import *` in `__init__.py` for compat**: rejected per the spec's no-shim rule (FR-005).

## R6 — Smoke-test concrete recipes for SC-005 + SC-006

### Decision (consolidated into quickstart.md)

- **SC-005 smoke (post-US1)**: Pick one abstract id from the corpus (`abstract_id = 1`). Capture the pre-stage `cache_key` for its figure-analysis cache (`data/cache/figure_analysis/<key>.json`). Run `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich-abstracts --limit 1 --invalidate figures` post-stage. Confirm the same `cache_key` lands.
- **SC-006 smoke (post-US3)**: Run `ohbmcli build-ui --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite …` post-stage; diff the produced file list against a pre-stage capture stored under `/tmp/ui-pre-stage5/`.

Both smokes are documented in `quickstart.md` with the exact commands.

## Open questions

None. All Technical-Context placeholders are resolved.
