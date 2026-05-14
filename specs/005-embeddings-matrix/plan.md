# Implementation Plan: Stage 3 — Multi-Model Embeddings Matrix

**Branch**: `005-embeddings-matrix` | **Date**: 2026-05-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/005-embeddings-matrix/spec.md`

## Summary

Stage 3 generates per-component embeddings (`title`, `introduction`, `methods`, `results`, `conclusion`, `claims`) for the freshly enriched corpus (state_key `f0c51e80dc0e`, 3244 abstracts) across five models: Voyage (`voyage-large-2-instruct` — NeuroScape Stage 1 compatible), MiniLM (`sentence-transformers/all-MiniLM-L6-v2` — UI search model), OpenAI (`text-embedding-3-small`), PubMedBERT (`neuml/pubmedbert-base-embeddings`), and NeuroScape (published Stage 2 model applied to Voyage component bundles). Downstream recipes (full-manuscript, methods+results, title+results+conclusion) are composed by mean-averaging the relevant component vectors at consumption time — they are not materialized as their own bundles.

Operational shape mirrors Stage 2.1: per-abstract cache under `data/cache/embeddings/<model_key>/` keyed by `sha256(input_text || model_id || model_version)`; canonical CLI `ohbmcli embed-matrix` plus per-model entrypoints (preserving existing `embed-voyage`, `embed-minilm`, etc., which are extended to take a single `--component`); paid-API batching at 64 inputs per HTTP call with dynamic concurrency starting at 8; per-input cache writes when each batch returns so resume is per-abstract not per-batch. Long-input handling defaults to `chunk_mean_pool` for transformer encoders (MiniLM, PubMedBERT) and `truncate_end` for API embeddings (Voyage, OpenAI). Provenance per bundle lives at `data/inputs/embeddings_matrix_provenance__<state-key>.json` with project-relative paths only.

## Technical Context

**Language/Version**: Python 3.14 via `.venv/bin/python` (per Constitution Principle I and the existing project pin).
**Primary Dependencies**: `numpy` (existing), `sentence-transformers` + `torch` (MiniLM / PubMedBERT — already an optional extra in `pyproject.toml`), `voyageai` (Voyage SDK — optional install for the embed pass), `openai` (already required; reused for `text-embedding-3-small`), the existing `neuroscape.py` library for HF tokenization, chunk-pooling, and the published-NeuroScape model loader.
**Storage**: Embedding outputs in `data/outputs/experiments/embeddings/<model_key>_<component>/` (existing convention) with `vectors.npy` + `metadata.json`; per-abstract cache entries in `data/cache/embeddings/<model_key>/<cache_key>.json`; provenance records under `data/inputs/`. All paths are gitignored.
**Testing**: `unittest` (project standard), invoked as `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`. New tests live under `tests/test_stage3_embeddings.py` (component-runner unit tests) and `tests/test_embed_matrix.py` (orchestrator integration).
**Target Platform**: Single workstation (developer macOS + Linux CI); paid-API access for Voyage and OpenAI; local GPU optional for HF models (CPU is the supported baseline).
**Project Type**: Library + CLI (in `src/ohbm2026/`); single project structure.
**Performance Goals**: All 30 default-matrix component bundles in under **120 min** wall-clock on a single workstation (SC-001); cached re-run < 2 min (SC-002); zero re-calls on resume for already-cached abstracts (SC-003).
**Constraints**: Per-component failure threshold 1% per bundle (stricter than Stage 2.1's 5% because embeddings are simpler calls); no absolute / `~` paths in any provenance record (Principle VIII); secrets stay in `.env` and are passed in-memory only (Principle V); paid-API batches MUST coalesce per FR-009a, dynamic concurrency per FR-009b.
**Scale/Scope**: 3244 accepted abstracts × 6 components × 5 models = 30 bundles. Aggregated text volume ~30 MB; total embedding vectors ≤ 30 × 3244 × 1536 floats ≈ 600 MB on disk (uncompressed float32) — well within local disk budget.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (venv-only Python)**: All Stage 3 entrypoints invoke `.venv/bin/python` via `scripts/run_embed_matrix.py` and the existing `ohbmcli` wiring. No system Python steps. ✅
- **Plan-first / test-first**: Phase 1 of this plan delivers `data-model.md`, `contracts/`, `quickstart.md`, and a tasks-template-driven `tasks.md`. Each behavior-changing capability is mapped to a unit or integration test that will fail before the implementation lands. ✅
- **Principle II (immutable evidence)**: Each `(model, component)` bundle is a fresh directory under `data/outputs/experiments/embeddings/`. The legacy 3333-record bundles are *not* overwritten — they are archived under `archive/stage3-pre-2026-05-14-legacy-bundles/` before the new run writes. FR-013 enforces refusing to overwrite a bundle with a different `corpus_state_key`. ✅
- **Gitignored generated artifacts**: All new directories (`data/cache/embeddings/`, refreshed `data/outputs/experiments/embeddings/`, `data/inputs/`) are under existing gitignored roots. No new tracked path. ✅
- **Principle VI (fail loudly)**: Missing `VOYAGE_API_KEY` / `OPENAI_API_KEY` → typed `EmbeddingError` at startup. Batch responses with mismatched cardinality (e.g., provider returned 63 vectors for a 64-input batch) → typed error. Per-abstract failure threshold defaults to 1% with hard abort when exceeded. No bare `except`. ✅
- **Principle VII (discover external state)**: Voyage / OpenAI model IDs and embedding dimensions are *captured at runtime* from the SDK's first successful response and persisted in `metadata.json` — never hardcoded; mismatches between request-side and response-side `model` strings raise. The published NeuroScape model checkpoint is read from its co-distributed manifest (existing `apply_published_stage2` pattern). PubMedBERT and MiniLM identifiers are passed by the operator (with defaults) and validated against the SDK's reported config. ✅
- **Principle VIII (provenance)**: Every bundle ships with a `provenance.json` carrying `corpus_state_key`, `component_assembly_hash`, `model_id`, `model_version`, `model_card_url` (when retrievable), `cache_root`, `command_line`, `code_revision`, `seed`. Paths are project-relative; the existing `_assert_paths_safe` guard from Stage 2.1 is reused. ✅
- **Principle V (secrets)**: `VOYAGE_API_KEY`, `OPENAI_API_KEY`, optional `HF_TOKEN` are loaded from `.env` into a local dict and passed as constructor kwargs to the respective SDKs. They are never written to `os.environ`. The `embed_matrix` CLI fails loudly if any required key is missing at the start of that model's pass (not mid-run). ✅
- **README/docs sync**: README "Stage 3" runbook section, `docs/reproducibility-vision.md`, and `CLAUDE.md` Default-Pipeline-State table all update in the same change to point at the new bundle layout (per-component) and the new state_key. ✅
- **Commit cadence**: The plan structures work into reviewable slices: spec+plan (already committed), foundational helpers (cache + storage + provenance writer), per-model runners (one commit each per FR-005 model), the orchestrator/CLI, polish + docs. Each commits as it lands; no end-of-feature monolith. ✅

No violations require justification — Complexity Tracking is omitted.

## Project Structure

### Documentation (this feature)

```text
specs/005-embeddings-matrix/
├── plan.md              # This file (/speckit-plan output)
├── spec.md              # Feature spec
├── research.md          # Phase 0 output (model SDK + chunk-window + NeuroScape model discovery)
├── data-model.md        # Phase 1 output (bundle layout, cache-entry schema, provenance shape)
├── contracts/
│   ├── cli.md           # `ohbmcli embed-matrix` + per-model subcommands
│   ├── bundle.schema.json     # Stage 3 bundle metadata JSON Schema
│   ├── cache-entry.schema.json # Per-abstract cache entry JSON Schema
│   └── provenance.schema.json # Stage 3 provenance record JSON Schema
├── quickstart.md        # Phase 1 output (operator runbook for the new matrix CLI)
├── checklists/
│   └── requirements.md  # Spec quality checklist (already complete)
└── tasks.md             # /speckit-tasks output (NOT generated here)
```

### Source Code (repository root)

```text
src/ohbm2026/
├── cli.py                          # extend: register `embed-matrix` subcommand (existing per-model subcommands stay)
├── neuroscape.py                   # extend: per-component embedding helpers (chunk-pool, truncate, mean-pool); existing voyage/openai/minilm/hf/apply-published-stage2 functions stay
├── embed_stage.py                  # NEW: matrix orchestrator (cache lookup → batched provider call → bundle writer)
├── embed_storage.py                # NEW: bundle + per-abstract cache I/O (atomic write, schema validation)
├── embed_components.py             # NEW: component-text assembler (reads enriched SQLite, returns per-abstract text per component)
├── embed_provenance.py             # NEW: provenance JSON writer (reuses Stage 2.1's `_assert_paths_safe` and project-relative guards)
└── exceptions.py                   # extend: add Stage3Error → EmbeddingError tree

scripts/
└── run_embed_matrix.py             # NEW: PYTHONPATH wrapper → ohbm2026.embed_stage.main

tests/
├── test_embed_components.py        # NEW: golden component-assembly tests for each of the 6 components
├── test_embed_storage.py           # NEW: bundle / cache atomic-write + round-trip tests
├── test_embed_stage.py             # NEW: orchestrator integration tests (fake clients, byte-equivalence on resume)
├── test_embed_voyage.py            # NEW: Voyage runner (batched fake SDK; concurrency policy)
├── test_embed_openai.py            # NEW: OpenAI runner (batched fake SDK; concurrency policy)
├── test_embed_pubmedbert.py        # NEW: HF runner with chunk_mean_pool
└── test_neuroscape_application.py  # NEW: derived-bundle determinism

archive/
└── stage3-pre-2026-05-14-legacy-bundles/   # one-time relocation of the 3333-record bundles
```

**Structure Decision**: Single-project structure under `src/ohbm2026/`. Stage 3 introduces four new modules (`embed_stage.py`, `embed_storage.py`, `embed_components.py`, `embed_provenance.py`) following the Stage 2.1 module boundaries: `embed_stage.py` is the orchestrator; `embed_components.py` is the pure component-text assembler; `embed_storage.py` is the I/O helper for bundle + cache entries (parallel to `enrich_storage.py`); `embed_provenance.py` is the provenance JSON writer. The existing `neuroscape.py` library keeps its current per-model functions (voyage_embed / openai_embed / hf_embed / apply_published_stage2) — `embed_stage.py` wraps them with the per-component cache + batching + concurrency layer rather than reimplementing.

The legacy 3333-record bundles under `data/outputs/experiments/embeddings/` are moved to `archive/stage3-pre-2026-05-14-legacy-bundles/` once before the Stage 3 run begins. This is a one-shot operator step recorded in `quickstart.md`, not a code path.

## Complexity Tracking

> Constitution Check passed with no violations; this section is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| —         | —          | —                                    |
