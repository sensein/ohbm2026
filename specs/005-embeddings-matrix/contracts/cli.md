# Stage 3 CLI Contract

## Canonical entrypoint

```bash
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py [OPTIONS]
# or equivalently:
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli embed-matrix [OPTIONS]
```

## Options

| Option | Type | Default | Meaning |
|---|---|---|---|
| `--source-corpus PATH` | path | `data/primary/abstracts_enriched.sqlite` | Stage 2.1 enriched SQLite |
| `--embeddings-root PATH` | path | `data/outputs/experiments/embeddings` | Where bundle directories go |
| `--cache-root PATH` | path | `data/cache/embeddings` | Where per-abstract cache lives |
| `--models LIST` | csv | `voyage,minilm,openai,pubmedbert,neuroscape` | Model keys to run |
| `--components LIST` | csv | `title,introduction,methods,results,conclusion,claims` | Components to embed |
| `--voyage-model-id ID` | string | `voyage-large-2-instruct` | Voyage model override |
| `--openai-model-id ID` | string | `text-embedding-3-small` | OpenAI model override |
| `--minilm-model-id ID` | string | `sentence-transformers/all-MiniLM-L6-v2` | MiniLM override |
| `--pubmedbert-model-id ID` | string | `neuml/pubmedbert-base-embeddings` | PubMedBERT override |
| `--batch-size N` | int | `64` | Inputs per HTTP call for paid APIs |
| `--concurrency-start N` | int | `8` | Initial in-flight cap per paid provider |
| `--concurrency-max N` | int | `24` | Ceiling for dynamic ramp |
| `--long-input-strategy MODEL=STRATEGY` (repeatable) | enum | see Research §3 | Override per-model strategy (`truncate_end`, `truncate_middle`, `chunk_mean_pool`, `fail_per_abstract`) |
| `--failure-threshold FLOAT` | float | `0.01` | Per-bundle failure rate that aborts the bundle |
| `--allow-partial COMPONENT` (repeatable) | string | — | Permit a partial-coverage component (e.g., `inference_claims`) |
| `--invalidate KEY` (repeatable) | enum | — | Force-invalidate one bundle's cache (`<model_key>_<component>`) |
| `--dry-run` | flag | `False` | List planned bundles + cache state without making provider calls |
| `--env-file PATH` | path | `.env` | Read API keys from this file (in-memory only) |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All requested bundles produced (or fully cache-hit) |
| 1 | Generic error (corpus missing, invalid argument) |
| 2 | Missing API key for a requested provider |
| 3 | Provider budget exhausted (resume-friendly; partial cache preserved) |
| 4 | Partial-coverage refusal (FR-007: component absent on some abstracts and `--allow-partial` was not passed) |
| 5 | Per-bundle failure threshold exceeded |
| 6 | Cache version mismatch (a cache entry on disk uses an unrecognized `cache_version`) |
| 7 | Bundle would overwrite a different `corpus_state_key` (FR-013 refusal) |

## Stdout contract

For each completed bundle, the runner emits one JSON object on stdout:

```json
{"bundle_path":"data/outputs/experiments/embeddings/voyage_methods","model_key":"voyage","model_id":"voyage-large-2-instruct","component":"methods","corpus_state_key":"f0c51e80dc0e","count":3244,"present_count":3244,"cache_hit_count":3244,"cache_miss_count":0,"failure_count":0,"truncated_count":0,"wall_clock_seconds":0.3}
```

At the end of the full run, a single matrix summary:

```json
{"state_key":"abcdef012345","abstract_count":3244,"bundles":[{"bundle":"voyage_methods","status":"ok","present_count":3244,"failure_count":0},...],"failure_threshold_exceeded":false,"provenance_record":"data/inputs/embeddings_matrix_provenance__abcdef012345.json"}
```

## Per-model subcommands (existing, kept for backward compat)

These pre-existed and continue to work for one-off / debugging use; they share the same component-cache layer:

```bash
ohbmcli embed-voyage --component methods
ohbmcli embed-minilm --component claims
ohbmcli embed-openai --component results
ohbmcli embed-hf --hf-model neuml/pubmedbert-base-embeddings --component title
ohbmcli apply-published-stage2 --voyage-bundle voyage_methods
```

Each subcommand accepts the same `--source-corpus`, `--cache-root`, `--failure-threshold`, `--long-input-strategy` flags as `embed-matrix`. Running one is equivalent to invoking `embed-matrix --models <X> --components <Y>`.

## Stage 3 contract guarantees

- The matrix command MUST be re-runnable: a clean re-run with the same arguments is byte-equivalent in bundle outputs (modulo `embedded_at` and `wall_clock_seconds`).
- The matrix command MUST be resumable: interrupting with SIGTERM and rerunning continues from the per-abstract cache without re-calling the provider for already-cached abstracts.
- The matrix command MUST fail loudly: missing API key → exit 2 before any provider call; provider budget exhausted → exit 3 with the cache preserved; over-threshold failures → exit 5 with no bundle overwrite.
- The matrix command MUST refuse to overwrite a bundle whose `corpus_state_key` differs from the source corpus's state_key (FR-013).
