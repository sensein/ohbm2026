# Quickstart — Stage 1: Fetch Abstracts + GraphQL Schema

How to run Stage 1 from a fresh clone, what files it produces, and how
to verify success. This is the operator's primary reference; the
README's Stage 1 section is updated to mirror it.

## Prerequisites

- Python 3.11.
- `uv` installed on `PATH`.
- A valid `OHBM2026_API` token from Oxford Abstracts in either `.env`
  (project root) or your shell environment.

## One-time setup

```bash
UV_CACHE_DIR=.uv-cache uv venv --python 3.11 .venv
```

Install the lint hook once per clone (recommended; constitution-check
is wired here):

```bash
git config core.hooksPath .githooks
```

## Run Stage 1

The canonical invocation, copy-pasteable:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_fetch_abstracts.py
```

Equivalent through `ohbmcli`:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli fetch-abstracts
```

On a fresh, fully-online run with no checkpoint present, the stage:

1. Loads the GraphQL token from `OHBM2026_API`.
2. Issues a GraphQL introspection request; persists
   `data/inputs/abstracts_graphql_schema__<state-key>.json`.
3. Computes the `schema_hash`; if a previous schema artifact exists,
   classifies every field-level delta as HARD / SOFT / INFORMATIONAL.
4. If any HARD-tier drift is present, exits with code `2` and a
   precise error naming the affected field(s). Stage 1 does NOT
   overwrite the corpus snapshot in this case.
5. Otherwise: fetches the accepted-submission ID list, batches the
   content fetches (default size 50), downloads methods/results
   figure assets per abstract, and writes the resume checkpoint at
   every batch boundary AND every per-record completion.
6. On full completion: writes
   `data/primary/abstracts.json` (atomic temp-then-rename),
   `data/inputs/abstracts_fetch_provenance__<state-key>.json`, and
   deletes the resume checkpoint.
7. Prints a single JSON summary to stdout (see
   `contracts/cli.md`).

## Resume an interrupted fetch

If the previous run was interrupted (network failure, rate limit,
Ctrl-C), just re-run the same command:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_fetch_abstracts.py
```

Stage 1 detects the existing checkpoint, validates
`bound_schema_hash` against the current schema, and continues from
the first not-`done` record. The worst-case redo is the records
still in the in-flight batch when the interruption happened (FR-018).

If the schema has changed since the checkpoint was written, Stage 1
refuses to resume silently and exits with code `3`. To proceed, run:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_fetch_abstracts.py \
  --allow-schema-change
```

(This is rare and should be a conscious decision; the downstream
risk is that fields fetched before vs after the schema change have
slightly different shapes in the same corpus snapshot.)

## Verify a successful run

```bash
ls -la data/inputs/abstracts_graphql__*.json \
       data/inputs/abstracts_graphql_schema__*.json \
       data/inputs/abstracts_fetch_provenance__*.json \
       data/primary/abstracts.json
```

All four files should be present with matching `<state-key>`
substrings in the three `data/inputs/` filenames.

Inspect the provenance record:

```bash
.venv/bin/python -m json.tool \
  data/inputs/abstracts_fetch_provenance__*.json | less
```

Confirm:
- `abstract_count` matches expectation.
- `figure_failure_count` is within tolerance (default ≤ 5% of total
  figure URLs).
- `resumed_from_previous_run` is `false` for a clean run.
- `schema_diff_vs_previous` is `null` for the first ever run, or
  contains a structured diff for subsequent runs.

## Re-run hygiene

Stage 1 is idempotent on unchanged upstream state. Running it twice
in a row against the same upstream produces:

- byte-identical `data/inputs/abstracts_graphql_schema__<key>.json`,
- byte-identical `data/primary/abstracts.json`,
- different `provenance` records (different `run_id`,
  `run_timestamp`, `query_count`).

If you see drift in the primary outputs without an obvious upstream
change, that is a Stage-1 bug — file an issue and attach both
provenance records.

## Test it locally

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_fetch_stage \
  tests.test_schema_diff \
  tests.test_graphql_api \
  tests.test_assets \
  -v
```

The full project test suite (excluding the one pre-existing unrelated
failure in `test_plot_poster_layout_floorplan`) should remain green:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

And the constitution lint should stay green:

```bash
.specify/scripts/bash/constitution-check.sh --full
```

## What's NOT in Stage 1

For future `/speckit-specify` rounds:

- Figure analysis (`analyze-figures`), enrichment, claim extraction,
  reference matching, embeddings, clustering, UI build — all run
  unchanged from existing `ohbmcli` subcommands.
- The Astro UI rewrite is separate.
- The cleanup of oversized modules (`enrichment.py`,
  `neuroscape.py`, etc.) happens in the per-stage rounds that touch
  them, not here.

See `specs/002-rewire-pipeline/spec.md` "Future Work" for the
full deferred list.
