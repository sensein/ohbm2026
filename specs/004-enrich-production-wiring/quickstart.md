# Quickstart — Stage 2.1: Production Enrichment

How to run Stage 2.1 against the live accepted corpus, what to
expect, and how to verify the run. This page extends the Stage 2
quickstart with the new defaults; the Stage 2 quickstart remains
the canonical reference for the orchestrator's contract surfaces.

## Prerequisites

- Stage 1 has produced `data/primary/abstracts.json`.
- Python 3.14 + `uv` + `.venv` already set up (canonical local target).
- API keys in `.env`:
  - `OPENAI_API_KEY` — required for figures + claims.
  - `OPENALEX_API` — optional but recommended for references.
- Stage 2.1 dependencies installed via the new `[enrich]` extra:

```bash
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[enrich]"
```

This installs `openai>=2.0.0` (for the Responses API) and
`Pillow>=10.0` (for in-memory JPEG compression and the local
image-quality probe).

## Run Stage 2.1 (default: gpt-5.4-mini + flex tier)

The canonical invocation, copy-pasteable:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py
```

Equivalent through `ohbmcli`:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich-abstracts
```

What's new vs Stage 2:

- **Production runners are wired** — no more `NotImplementedError`
  stubs. The three components actually invoke their backends.
- **Default model**: `gpt-5.4-mini` for both figures and claims.
- **Flex tier ON by default** for both LLM-backed components.
- **Per-figure local quality probe** is recorded on every figure
  record before the model call.
- **Claims annotated with ECO evidence codes** (v1 vocabulary, 9
  top-level codes).
- **Per-component cost telemetry + tier counters** in provenance.

Expected fresh-run cost / wall-clock on the live 3244-abstract
corpus:

| component | wall-clock | cost |
|---|---|---|
| figures | ~15–25 min | ~$2 |
| claims | ~20–35 min | ~$3 |
| references | ~10–15 min | $0 |
| **combined** | **~45–75 min** | **~$5** |

(SC-002: under 75 min. SC-003: under $10.)

## Override the model per component

Stick `gpt-4.1-mini` on figures while testing a newer model on
claims:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py \
  --figure-model-id gpt-4.1-mini \
  --claims-model-id gpt-5.4
```

Only the claims cache is invalidated (the figure-model change
also invalidates figures since the cache key embeds `model_id`).

## Disable flex tier

Latency-sensitive runs (live demo, debugging a stuck call) can
disable flex per component:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_enrich_abstracts.py \
  --no-flex-figures \
  --no-flex-claims
```

Both components run on the standard tier. Provenance records the
choice.

## Verify a successful run

```bash
ls -la data/primary/abstracts_enriched.sqlite \
       data/inputs/abstracts_enrich_provenance__*.json
```

Inspect the provenance record's new fields:

```bash
.venv/bin/python -m json.tool \
  data/inputs/abstracts_enrich_provenance__*.json | less
```

Confirm:

- `eco_vocabulary_version` is `"eco.v1"`.
- Each entry under `components` has the new tier counters
  (`flex_timeout_count`, `tier_fallback_count`,
  `retry_exhaustion_count`) and the cost-telemetry fields
  (`prompt_tokens_cached`, `prompt_tokens_uncached`,
  `completion_tokens`, `wall_clock_seconds`, `latency_p50_ms`,
  `latency_p95_ms`).
- `flex_tier_enabled` reflects the per-component setting you
  passed.

Spot-check a figure record:

```bash
.venv/bin/python -c "
import sqlite3, zlib, json
con = sqlite3.connect('data/primary/abstracts_enriched.sqlite')
row = con.execute('SELECT payload FROM abstracts LIMIT 1').fetchone()
rec = json.loads(zlib.decompress(row[0]))
for fig in rec.get('figure_interpretation', []):
    print(fig['figure_url'])
    print('  local:', fig.get('local_quality_estimate'))
    print('  model:', fig.get('model_quality_estimate'))
    print('  keywords:', fig.get('keywords'))
"
```

Spot-check a claim record:

```bash
.venv/bin/python -c "
import sqlite3, zlib, json
con = sqlite3.connect('data/primary/abstracts_enriched.sqlite')
row = con.execute('SELECT payload FROM abstracts LIMIT 1').fetchone()
rec = json.loads(zlib.decompress(row[0]))
for claim in rec.get('claims', []):
    print('-', claim['claim_text'][:80])
    print('  type:', claim.get('claim_type'))
    print('  verified:', claim.get('source_quote_verified'))
    print('  ECO codes:', claim.get('evidence_eco_codes'))
    print('  confidence:', claim.get('confidence'))
"
```

Estimate the run's OpenAI spend from provenance alone:

```bash
.venv/bin/python -c "
import glob, json
prov = json.loads(open(sorted(glob.glob('data/inputs/abstracts_enrich_provenance__*.json'))[-1]).read())
# gpt-5.4-mini approx pricing; verify against the OpenAI console.
RATES = {'cached': 0.025e-6, 'uncached': 0.25e-6, 'out': 2.0e-6}
total = 0
for c in prov['components']:
    if c['component'] == 'references':
        continue
    flex_factor = 0.5 if c['flex_tier_enabled'] else 1.0
    spend = (
        c['prompt_tokens_cached']   * RATES['cached']
      + c['prompt_tokens_uncached'] * RATES['uncached']
      + c['completion_tokens']      * RATES['out']
    ) * flex_factor
    print(f\"{c['component']:<11s} {c['model_id']:<24s} \${spend:>6.2f}\")
    total += spend
print(f'TOTAL                              \${total:>6.2f}')
"
```

## Re-run hygiene

Stage 2.1 inherits Stage 2's idempotency: a second run with the
same source corpus, same model identifiers, and same flex
setting reuses every cache, makes zero LLM calls, and produces a
byte-identical SQLite (modulo provenance run-id + timestamp).

If you change ONE component's model:

- Only that component's cache invalidates.
- Re-run; the other two stay 100% cache hits.

If you toggle the flex setting:

- The model id is unchanged, so the cache key is unchanged → caches
  STILL hit. The only differences are the tier counters and
  cost-telemetry numbers in provenance. (Flex setting is not part
  of the cache key — same model + same input = same answer
  regardless of which tier it ran on.)

## Test it locally

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_enrich_stage \
  tests.test_stage2_figures \
  tests.test_stage2_claims \
  tests.test_stage2_references \
  tests.test_flex_tier \
  tests.test_image_quality \
  tests.test_eco_vocabulary \
  -v
```

The full project test suite should remain green:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

And the constitution lint:

```bash
.specify/scripts/bash/constitution-check.sh --full
```

## What's NOT in Stage 2.1

For future `/speckit-specify` rounds:

- OpenAI Batch API (~50% off flex, 24h async).
- Full ECO subterms beyond the top-9.
- Withdrawn-corpus enrichment.
- Historical-corpus migration (`abstracts_enriched.json` →
  `.sqlite`).
- Multi-provider failover (Anthropic, Gemini).
- Per-record cost telemetry (only per-component aggregates in
  v1).
- Splitting `enrichment.py` / `openalex.py` into smaller modules.

See `specs/004-enrich-production-wiring/spec.md` "Future Work"
for the full deferred list.
