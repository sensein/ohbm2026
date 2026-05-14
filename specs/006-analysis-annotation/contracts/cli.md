# CLI Contract: `ohbmcli analyze-matrix`

Canonical Stage 4 entrypoint. Mirrors the Stage 3 contract shape (model × input × kind matrix iteration with per-bundle JSON-per-line output plus a run-level summary).

## Synopsis

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix [OPTIONS]
# Equivalent venv wrapper:
PYTHONPATH=src .venv/bin/python scripts/run_analyze_matrix.py [OPTIONS]
```

## Options

### Input selection
| Flag | Default | Notes |
|---|---|---|
| `--env-file` | `.env` | Loaded in-memory only (Principle V). |
| `--embeddings-root` | `data/outputs/embeddings` | Stage 3 output root the matrix consumes. |
| `--corpus-state-key` | auto-detect | If omitted, derives from the single state-key present under `embeddings-root`; fails if ambiguous. |
| `--models MODEL [MODEL …]` | `voyage minilm openai pubmedbert neuroscape` | The five-model default. |
| `--inputs INPUT [INPUT …]` | `abstract claims` | Canonical pair. `abstract` triggers `compose_recipe`; `claims` reads the claims bundle directly. Additional `(model, recipe-or-component)` combos are accepted as long as they resolve via `embed.compose.compose_recipe`. |

### Analysis kinds
| Flag | Default | Notes |
|---|---|---|
| `--kinds KIND [KIND …]` | `projections communities neuroscape_clusters topic_clusters` | One bundle per kind per `(model, input)`. |
| `--skip-llm-topics` | unset | Run the topic-keyword pipeline as fully-local (spaCy + c-TF-IDF only). No OpenAI calls. |
| `--scispacy` | unset | Use `scispacy/en_core_sci_lg` for phrase extraction instead of `en_core_web_md`. Requires the optional `[analysis-sci]` extra. |

### UMAP / community / centroid / topic hyperparameters
| Flag | Default | Notes |
|---|---|---|
| `--umap-n-neighbors` | `15` | Forwarded to umap-learn. |
| `--umap-min-dist` | `0.1` | |
| `--umap-metric` | `cosine` | |
| `--community-knn-k` | `30` | k for the FAISS `IndexFlatIP` kNN graph. |
| `--community-resolution-min` | `0.001` | NeuroScape default. |
| `--community-resolution-max` | `0.1` | NeuroScape default. |
| `--community-resolution-points` | `20` | Linear sweep count. |
| `--neuroscape-centroids` | `data/inputs/neuroscape` | Directory holding `centroids__<version>.npy` + `cluster_table.csv`. |
| `--n-topics` | `auto` | For `topic_clusters`. `auto` triggers an elbow / coherence rule. |
| `--topic-llm-model-id` | `gpt-5.4-mini` | Forwarded to the optional LLM grouping pass; flex tier by default (matches Stage 2.1). |
| `--topic-prompt-version` | `v1` | Cache key component (FR-017). |

### Determinism + cache
| Flag | Default | Notes |
|---|---|---|
| `--seed` | `42` | Forwarded to umap, leidenalg, topic_clusters. |
| `--cache-root` | `data/cache/analysis` | |
| `--invalidate KIND` | unset (repeatable) | Force-recompute one analysis kind (e.g., `--invalidate projections`). |
| `--strict-matrix` | unset | When set, dim-incompatible `(model, neuroscape_clusters)` pairs raise `AnalysisError`. Default behavior is to auto-skip with a structured `skipped` event on stdout. |

### Output + provenance
| Flag | Default | Notes |
|---|---|---|
| `--output-root` | `data/outputs/analysis` | Bundle root; one subdirectory per `(input_key, kind)`. |
| `--rollup-path` | `data/outputs/analysis/annotations__<state-key>.parquet` | Auto-derives the sidecar `.sqlite` path. |
| `--provenance-root` | `data/provenance/analysis` | One JSON per run. |
| `--code-revision` | auto via `git rev-parse HEAD` | Recorded in provenance. |

### Diagnostics
| Flag | Default | Notes |
|---|---|---|
| `--dry-run` | unset | Resolve the matrix, log the plan, exit 0 without computing anything. |
| `--log-level` | `INFO` | |

## Stdout protocol

One JSON object per bundle on completion, then a final summary line. Identical to Stage 3.

```json
{"event":"bundle_complete","input_key":"voyage_abstract","kind":"communities","bundle_path":"data/outputs/analysis/voyage_abstract/communities__abc123def456/","n_rows":3244,"n_communities":18,"largest_community_share":0.214,"cache":"miss","duration_seconds":12.4}
{"event":"bundle_skipped","input_key":"minilm_abstract","kind":"neuroscape_clusters","reason":"dim_incompatible","model_vector_dim":384,"stage2_expected_dim":1024}
...
{"event":"matrix_complete","run_state_key":"...","bundles_written":34,"bundles_skipped":6,"bundles_cached":0,"rollup_path":"data/outputs/analysis/annotations__f0c51e80dc0e.parquet","duration_seconds":1683.2}
```

## Exit codes

| Code | Condition |
|---|---|
| `0` | All bundles produced (or cached); rollup written. |
| `1` | One or more bundles failed before completion. Run is aborted at first failure; previously-written bundles remain on disk. |
| `2` | Pre-flight validation failed (missing input bundle, missing centroid table, unknown model name). No bundles attempted. |

## Subcommand: `ohbmcli analyze-umap-project`

A small CLI surface for User Story 2 — project an out-of-corpus vector batch into an existing fitted UMAP bundle.

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-umap-project \
    --fitted-bundle data/outputs/analysis/voyage_abstract/projections__<state-key>/ \
    --input-vectors path/to/new_vectors.npy \
    --algorithm native | knn_weighted | parametric \
    --output path/to/new_coords.npy
```

Exit codes: `0` on success, `2` if the bundle does not list the requested algorithm under `supported_algorithms`, or if the input matrix dimension does not match the bundle's reference matrix.

## Subcommand: `ohbmcli derive-neuroscape-centroids`

Thin alias for `scripts/derive_neuroscape_centroids.py`. Operator runs this once; it produces `centroids__<version>.npy` + `cluster_table.csv` under `data/inputs/neuroscape/`.

## Removed / replaced subcommands

This change does not remove any existing subcommand surface — Stage 4's `analyze-matrix` is additive. The existing `umap-plot`, `compare-projections`, `optimize-projections`, `cluster-benchmark`, `semantic-analysis`, `analyze-stage2`, and `write-manifest` subcommands remain (they're still useful for ad-hoc work) but now route through the new `analyze/` package modules instead of `analyze.py`.
