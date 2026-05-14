# Implementation Plan: Stage 4 — Analysis & Annotation

**Branch**: `006-analysis-annotation` | **Date**: 2026-05-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-analysis-annotation/spec.md`

## Summary

Stage 4 turns Stage 3 embedding bundles into analysis artifacts the UI and organizer tooling consume. For every `(model, input_source)` pair in the default matrix (5 models × 2 inputs), produce four bundles — `projections` (UMAP 2D+3D), `communities` (FAISS+Leiden+CPM with resolution sweep), `neuroscape_clusters` (spherical-mean nearest-centroid in the published Stage-2 space), and `topic_clusters` (a topic-model clustering whose cluster labels are exposed alongside communities and NeuroScape clusters). Every clustering kind ships a row-aligned `topics` artifact produced by a **hybrid spaCy phrase extraction + optional LLM grouping** pipeline (fully local with `--skip-llm-topics`). Provide a `project_into_umap(new_vectors, fitted_bundle, algorithm=…)` function supporting `native` / `knn_weighted` / `parametric`. Finalize the structural cleanup by exploding `src/ohbm2026/analyze.py` (~2,800 LOC) into an `analyze/` package and moving Stage-2 NeuroScape model code into `embed/neuroscape.py` (replacing the façade). Emit a canonical per-corpus rollup (`annotations__<state-key>.parquet` + `.sqlite`) so the UI consumes Stage 4 in one read.

## Technical Context

**Language/Version**: Python 3.14 (`.venv/bin/python` via `uv`).
**Primary Dependencies**:
- New analysis libs added under a `[analysis]` optional-extra in `pyproject.toml`:
  - `umap-learn>=0.5` (UMAP fit + `transform`)
  - `faiss-cpu>=1.8` (`IndexFlatIP` kNN over normalized embeddings)
  - `python-igraph>=0.11` + `leidenalg>=0.10` (community detection)
  - `spacy>=3.8` + `en_core_web_md` model (noun-chunk + NER phrase extraction)
  - `h5py>=3.10` (one-off NeuroScape centroid derivation)
  - `pyarrow>=17.0` (parquet rollup; already exists as `[parquet]` extra — folded in)
  - `scikit-learn>=1.4` (already transitively present; used for c-TF-IDF + cosine helpers)
  - `hdbscan>=0.8` (used by the `topic_clusters` analysis kind)
  - Optional: `scispacy>=0.5` + `en_core_sci_lg` (scientific NER, opt-in via `[analysis-sci]`)
- Existing libs reused: `numpy`, `torch` (Stage-2 model), `openai` (opt-in topic-grouping LLM call — reuses `enrich.flex_tier`).
**Storage**:
- Per-bundle outputs: `data/outputs/analysis/<input_key>/<analysis_kind>__<state-key>/` (npy + json).
- Canonical rollup: `data/outputs/analysis/annotations__<state-key>.parquet` + `.sqlite` (shape-equivalent).
- Caches: `data/cache/analysis/<analysis_kind>/<cache_key>.json[+.npy]`.
- Provenance: `data/provenance/analysis/<analysis_kind>__<state-key>.json` (run-level) + per-bundle `provenance.json`.
- NeuroScape centroids (one-off): `data/inputs/neuroscape/centroids__<table_version>.npy` + `cluster_table.csv`.
**Testing**: `unittest` (mirroring Stages 1–3); fixtures use synthetic small matrices so test runtime stays well under existing suite envelope.
**Target Platform**: macOS / Linux workstation (single-machine pipeline; no GPU required — FAISS-CPU is the chosen backend; Stage-2 model already runs on CPU via existing `apply_stage2_model`).
**Project Type**: Single-project CLI + library, mirroring Stages 1–3 layout.
**Performance Goals**:
- SC-001: Default matrix (**34 bundles**: 10 projections + 10 communities + 10 topic_clusters + 4 neuroscape_clusters; minilm/openai/pubmedbert auto-skipped for `neuroscape_clusters` per FR-002's dim-compat constraint) in < 30 min wall-clock against corpus `f0c51e80dc0e` (3,244 rows).
- SC-002: Cached re-run < 60 s.
- SC-005: Voyage manuscript-recipe communities ≥ 12 with largest ≤ 30%.
- SC-006: NeuroScape angular-distance distribution sane (mean ≥ 0.15, std ≥ 0.05).
**Constraints**:
- Determinism: every analysis kind seeded; reruns byte-identical modulo timestamps.
- No data committed; every new directory under `data/outputs/analysis/`, `data/cache/analysis/`, `data/provenance/`, `data/inputs/neuroscape/` lives under existing gitignored roots.
- No backward-compat shim for `ohbm2026.analyze`. Every caller (`cli.py`, scripts/, tests/, `ui.py`, `category_evaluation.py`, `poster_layout.py`, `embed/neuroscape.py`) migrates in the same change.
- LLM topic-grouping is **opt-out** via `--skip-llm-topics`; default run uses it.
**Scale/Scope**:
- 3,244 abstracts × 34 default bundles + 1 rollup pair (parquet + sqlite). Default matrix: 5×2 projections + 5×2 communities + 5×2 topic_clusters + 2×2 neuroscape_clusters (voyage + neuroscape only).
- LLM topic grouping: ≈ 75 cluster-summary calls per full run (2 LLM-eligible clustering methods — communities + topic_clusters — across 10 (model, input) cells × ~25 mean clusters each, minus cache hits; `neuroscape_clusters` uses the verbatim `cluster_table.csv` labels and does NOT invoke the LLM), ~3k tokens per call, ~$0.15 total cost at `gpt-5.4-mini` flex.
- UI export step (`ohbmcli export-ui` / `build-ui`) is **updated in this change** to consume the new rollup; legacy UI consumption path is replaced, not preserved.
- Reorganization touches ~12 importing modules and ~3 tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|---|---|---|
| **I. Venv-only Python** | PASS | `scripts/run_analyze_matrix.py` and `ohbmcli analyze-matrix` run through `.venv/bin/python`; spec CA-001 makes this explicit. |
| **II. Immutable evidence / no committed data** | PASS | All new directories (`data/outputs/analysis/`, `data/cache/analysis/`, `data/provenance/analysis/`, `data/inputs/neuroscape/`) live under existing gitignored roots (`data/`). Spec CA-005 captures this; lint will catch regressions. |
| **III. Resumable, auditable pipelines** | PASS | Per-analysis caches keyed by `sha256(input_matrix_hash || algorithm_config || seed || prompt_version)` (FR-017); reruns hit cache; SC-002 enforces. |
| **IV. Plan-first, test-first** | PASS | This plan + spec exist before code. Tests (FR-016/SC-007 = reorg green; CA-002 = per-kind determinism + missing-centroid refusal + project_into_umap algorithm coverage) are required first. |
| **V. Secret-safe, commit early** | PASS | `OPENAI_API_KEY` is the only secret involved (opt-in via the LLM topic stage). Loaded from `.env` in-memory only, same pattern as Stage 2/3 (`enrich.flex_tier`). No secret appears in any artifact. Implementation slices commit per phase. |
| **VI. Fail loudly, no shortcuts** | PASS | Typed `AnalysisError` hierarchy (CA-006); missing centroid table / version mismatch / unknown UMAP algorithm / dimension mismatch each raise with diagnostic context. No fallbacks. |
| **VII. Discover external state** | PASS | NeuroScape centroid table version + checksum are discovered from the artifact's own sidecar `metadata.json` (CA-007); UMAP bundle metadata records persisted-algorithm capability so `project_into_umap` can refuse `native` against a coords-only bundle. |
| **VIII. Provenance for organizer-facing outputs** | PASS | Every annotation bundle ships `provenance.json` alongside `metadata.json` (CA-008): corpus_state_key → input_source_assembly_hash → algorithm_config → cache_key, plus code revision + command + seed. Project-relative paths only (`_assert_paths_safe`). |

No violations. No Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/006-analysis-annotation/
├── plan.md              # This file
├── research.md          # Phase 0 — algorithmic + library choices consolidated
├── data-model.md        # Phase 1 — entity shapes (bundle, rollup, centroid table)
├── quickstart.md        # Phase 1 — operator runbook
├── contracts/
│   ├── cli.md           # `ohbmcli analyze-matrix` flags + exit codes
│   ├── bundle.md        # Per-bundle metadata.json + provenance.json schema
│   ├── rollup.md        # annotations__<state-key>.{parquet,sqlite} schema
│   └── project_into_umap.md  # function signature + per-algorithm contract
├── checklists/
│   └── requirements.md  # Already created by /speckit-specify
└── tasks.md             # Phase 2 — generated by /speckit-tasks
```

### Source Code (repository root)

```text
src/ohbm2026/
├── analyze/                       # NEW (replaces flat analyze.py)
│   ├── __init__.py                # Public re-exports for legacy import paths used by ui/poster_layout/category_evaluation
│   ├── stage.py                   # Orchestrator: matrix iteration + cache + provenance + rollup
│   ├── umap.py                    # UMAP fit + bundle I/O + project_into_umap (native | knn_weighted | parametric)
│   ├── communities.py             # FAISS kNN + Leiden CPM + resolution sweep
│   ├── centroids.py               # Spherical-mean centroid loader + nearest-centroid assignment
│   ├── topics.py                  # spaCy phrase extraction + c-TF-IDF + optional LLM grouping
│   ├── topic_clusters.py          # Topic-model-driven clustering (the "topic_clusters" analysis kind)
│   ├── clusters.py                # Cluster benchmark + agglomerative helpers (migrated from analyze.py)
│   ├── projections.py             # t-SNE + UMAP visualization HTML (migrated)
│   ├── rollup.py                  # annotations.parquet + .sqlite writer
│   ├── storage.py                 # Atomic bundle + cache I/O helpers
│   ├── provenance.py              # Run-level provenance writer (mirrors embed.provenance)
│   └── errors.py                  # AnalysisError hierarchy (CA-006)
├── embed/
│   └── neuroscape.py              # Receives the real Stage-2 implementation moved out of analyze.py
│                                  # (replaces the current re-export façade)
├── cli.py                         # Wire `analyze-matrix` subcommand; migrate every analyze.* import
├── ui.py                          # Update import: ohbm2026.analyze.storage (or analyze package __init__)
├── poster_layout.py               # Update imports
├── category_evaluation.py         # Update imports
└── analyze.py                     # DELETED in same change

scripts/
├── run_analyze_matrix.py          # NEW — venv wrapper, mirrors run_embed_matrix.py
└── derive_neuroscape_centroids.py # NEW — one-off setup, reads NeuroScape H5 shards + clusters CSV

tests/
├── test_analyze_stage.py          # NEW — matrix iteration, cache hit/miss, rollup join
├── test_analyze_umap.py           # NEW — fit + project_into_umap × 3 algorithms + dim-mismatch refusal
├── test_analyze_communities.py    # NEW — FAISS+Leiden recipe + size-ordered ids + resolution sweep
├── test_analyze_centroids.py      # NEW — spherical-mean + nearest-centroid + missing-table refusal
├── test_analyze_topics.py         # NEW — spaCy extraction + c-TF-IDF + Keywords⊆candidate_phrases guard
├── test_analyze_rollup.py         # NEW — parquet + sqlite shape equivalence + join semantics
├── test_analyze_cli.py            # NEW — argparse + delegation
├── test_neuroscape.py             # UPDATE imports to ohbm2026.embed.neuroscape / ohbm2026.analyze.umap etc.
└── test_neuroscape_derivation.py  # UPDATE imports likewise
```

**Structure Decision**: Stage 4 follows the same per-stage package shape Stages 1–3 settled on:
`src/ohbm2026/<stage>/{stage.py, storage.py, provenance.py, errors.py, <per-concern>.py}`.
The flat `analyze.py` (≈ 2,800 LOC of mixed concerns) is **deleted in this change**; the `analyze/__init__.py` keeps the small public surface that downstream modules still import (`parse_string_list_value`, `load_embedding_bundle`, `build_knn_graph`, `compute_clustering_metrics`, `build_distinct_color_map`, `prepare_clustering_matrix`) by re-exporting from the new submodules. The Stage-2 model code (training entrypoint, applier, checkpoint loader, bundle writers) physically moves to `embed/neuroscape.py`; the existing `embed/neuroscape.py` façade is replaced, and `analyze.umap` etc. no longer re-export Stage-2 internals.

## Complexity Tracking

No Constitution-Check violations → table intentionally omitted.
