# Stage 3 — Embeddings Matrix Quickstart

This is the operator runbook for generating the Stage 3 per-component embeddings matrix against the freshly enriched corpus.

## Prerequisites

```bash
# Virtualenv (already pinned to Python 3.14)
UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv

# Optional extras (one-time)
uv pip install --python .venv/bin/python sentence-transformers   # MiniLM + PubMedBERT
uv pip install --python .venv/bin/python voyageai                # Voyage SDK

# Confirm the enriched corpus is present
ls -lh data/primary/abstracts_enriched.sqlite

# .env carries the API keys (never committed)
grep -E '^(OPENAI_API_KEY|VOYAGE_API_KEY|HF_TOKEN)=' .env
```

## One-time: archive the legacy 3333-record bundles

The previous bundles were computed against the prior corpus and against multi-component recipes that Stage 3 no longer materializes. Archive them so they survive but don't shadow the new outputs.

```bash
mkdir -p archive/stage3-pre-2026-05-14-legacy-bundles
mv data/outputs/experiments/embeddings/* archive/stage3-pre-2026-05-14-legacy-bundles/
```

The archive directory is gitignored (`archive/` is in the project root `.gitignore`).

## Smoke run: one (model, component) pair

Validates the pipeline end-to-end without committing to the full matrix.

```bash
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py \
  --models minilm \
  --components title \
  --dry-run
```

`--dry-run` lists the planned bundle path, cache state (hit count expected to be 0 on a clean run), and exits without making any model calls. Remove the flag to execute.

## Full default matrix

```bash
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py
```

This produces 30 bundles: 5 models × 6 components. The expected wall-clock is < 120 minutes on a single workstation with paid APIs reachable (SC-001).

Subset filters:

```bash
# Only the local-model passes (no paid API, fast iteration)
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py --models minilm,pubmedbert

# Only the claims component across all models
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py --components claims

# Single bundle (debugging)
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py --models voyage --components methods
```

## Interrupting + resuming

Embedding passes write per-abstract cache entries as each batch returns. Killing the process (SIGTERM / Ctrl-C) preserves every completed entry.

```bash
# … run starts, gets to ~half corpus, you Ctrl-C
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py
# Second run completes only the remaining abstracts; cache_hit_count reflects the progress made.
```

## Invalidating a cache slice

If a model version bumps mid-run and you want to force re-embed for one bundle (rather than waiting for a version-string change):

```bash
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py \
  --invalidate voyage_methods
```

This deletes the matching `<model_key>_<component>` cache directory contents and re-embeds. The bundle directory itself is moved aside (timestamped suffix) rather than overwritten.

## Partial-coverage components

The `inference_claims` component covers only 12.3% of the corpus. The runner refuses to write a full bundle for it. To opt in:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py \
  --components inference_claims \
  --allow-partial inference_claims
```

Produces `<model_key>_inference_claims_partial/` bundles for each model, with metadata recording the 399-row coverage.

## Downstream composition

After Stage 3 completes, downstream tools (clustering, UMAP, UI export) compose multi-component recipes from the per-component bundles:

```python
from ohbm2026.neuroscape import compose_recipe

# Reconstruct the equivalent of the legacy `*_stage1` (full-manuscript) bundle
manuscript_recipe = compose_recipe(
    components=["title", "introduction", "methods", "results", "conclusion"],
    model_key="voyage",
)
# manuscript_recipe["matrix"] is float32 [n × 1024]
# manuscript_recipe["ids"] is int64 [n]
# manuscript_recipe["present_count_per_id"] is int8 [n] — 5 if all components present
```

Composition is deterministic and runs in seconds. It does not produce a new persisted bundle in v1 — call it inline at the start of any clustering / UMAP / projection job.

## Validating one bundle

```bash
.venv/bin/python -c "
import json, numpy as np, pathlib
b = pathlib.Path('data/outputs/experiments/embeddings/minilm_methods')
meta = json.loads((b / 'metadata.json').read_text())
vec = np.load(b / 'vectors.npy', mmap_mode='r')
ids = np.load(b / 'ids.npy', mmap_mode='r')
assert vec.shape[0] == ids.shape[0] == meta['present_count'], 'shape mismatch'
assert vec.shape[1] == meta['dim'], 'dim mismatch'
assert meta['ids'] == ids.tolist(), 'ids drift between npy and json'
print(f'OK: {meta[\"bundle_name\"]} = {vec.shape[0]} × {vec.shape[1]} {vec.dtype}')
"
```

## Reading the run-level provenance

```bash
.venv/bin/python -c "
import json, sys
p = json.load(open(sys.argv[1]))
print(f\"state_key:           {p['state_key']}\")
print(f\"corpus_state_key:    {p['corpus_state_key']}\")
print(f\"wall_clock_seconds:  {p['wall_clock_seconds']:.1f}\")
print(f\"bundles:             {len(p['bundles'])}\")
for b in p['bundles']:
    flag = '' if b.get('status','ok') == 'ok' else f\" [{b['status']}]\"
    print(f\"  {b['model_key']:11s} {b['component']:14s} n={b['present_count']:4d} fail={b['failure_count']:2d} hit={b['cache_hit_count']:4d}{flag}\")
" data/inputs/embeddings_matrix_provenance__<state-key>.json
```

## Cost ballpark (3244 abstracts × 6 components)

| Provider | Inputs per pass | Avg tokens / input | Total tokens | Unit price | Cost / matrix run |
|---|---|---|---|---|---|
| Voyage | 6 × 3244 = 19 464 | ~300 | ~5.8M | $0.12/M | ~$0.70 |
| OpenAI `-3-small` | 19 464 | ~300 | ~5.8M | $0.02/M | ~$0.12 |
| MiniLM (local) | 19 464 | n/a | n/a | $0 | $0 |
| PubMedBERT (local) | 19 464 | n/a | n/a | $0 | $0 |
| NeuroScape (derived) | n/a — operates on Voyage vectors | n/a | n/a | $0 | $0 |

Total for the default matrix: < $1 USD per fresh run; ~$0 on cache hit.

## When to re-run

- Stage 2.1 corpus state changes (new abstracts ingested, claims schema bumped, etc.) — `corpus_state_key` will differ; Stage 3 will refuse to overwrite existing bundles and the operator must invoke fresh with the new state.
- Embedding model version changes upstream (provider rotates the model id) — the cache misses naturally and Stage 3 re-embeds only what's needed.
- Long-input strategy is tuned via `--long-input-strategy` — record in `metadata.json` and re-run the affected bundles.
