# Contract — `ohbmcli book` (Stage 11.1 updates)

This contract amends `specs/011-abstracts-book/contracts/cli.md`. Only the deltas are listed here.

## Format choices (FR-007 — DOCX retirement)

```diff
- [--format {md,pdf,docx,all}]
+ [--format {md,pdf,all}]
```

`--format docx` is **rejected** with a specific exit code + stderr:

| Condition | Behaviour |
|---|---|
| `--format docx` | Exit code 2 (`BookBuildError`). Stderr: `error: docx export was retired in Stage 11.1 — use --format md (markdown bundle) or --format pdf (per-abstract PDF pipeline) instead. See docs/abstracts-book-plan.md for the migration note.` No `book.docx` written. |

`--format all` now expands to `{md, pdf}` (no docx).

## New flag — `--workers` (US1)

```text
[--workers N]
```

| Default | Description |
|---|---|
| `-1` (all cores) | Number of parallel pandoc subprocess invocations during per-abstract PDF rendering. Passed as `joblib.Parallel(n_jobs=...)`. `1` for serial (debug) builds; `2`-`N` for partial parallelism on shared CI runners; `-1` for max throughput on a developer laptop. |

## New flag — `--no-cache` (US1)

```text
[--no-cache]
```

When set, the per-abstract PDF cache is **bypassed**: every chunk re-renders from scratch (cache files NOT overwritten — they remain valid for the next normal run). Useful for measuring cold-cache wall time + debugging cache-key collisions.

## Updated provenance fields (US1)

`provenance.json` for any run that produces a PDF now carries:

```json
{
  "cache_hit_count": 0,
  "cache_miss_count": 0,
  "failed_abstracts": [],
  "assembly_time_seconds": 0.0,
  "pdf_pipeline_version": "stage-11.1",
  "pdf_engine_version": "..."  // renamed from xelatex_version
}
```

`xelatex_version` is removed; `pdf_engine_version` carries the engine name (xelatex|tectonic) + version line.

## Exit codes (updated)

| Code | When |
|---|---|
| 0 | All requested formats produced successfully (PDF run may still log per-abstract failures in provenance — those are isolated, not exit-worthy). |
| 1 | Generic CLI error. |
| 2 | `BookBuildError`: corpus missing, output unwritable, system dep missing, **`--format docx` requested**, ALL abstracts failed to render (zero-survivors guard). |
| 3 | Figure-resolution check failed catastrophically (unchanged). |

## Cache directory layout

```text
data/cache/book/
└── abstracts/
    ├── <16-hex-cache-key>.pdf
    ├── <16-hex-cache-key>.json   # sidecar: page_count, index_entries
    └── ...
```

Operator can rm -rf this directory to force a full rebuild. The directory is gitignored under the existing root `data/` rule.

## Per-abstract debug recipe

A single abstract can be re-rendered in isolation by running:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.book.render_per_abstract \
  --corpus data/primary/abstracts.json \
  --poster-id 0042 \
  --style plain
```

Output: a single-PDF chunk written to the cache + stderr trace from pandoc. Useful for debugging the LaTeX of a specific abstract without running the full pipeline.
