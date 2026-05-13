# CLI Contract — Stage 1: Fetch Abstracts

Stage 1 exposes one canonical surface in two equivalent forms; both
route through `ohbm2026.fetch_stage.main(argv: list[str]) -> int`.

## Primary form: `ohbmcli fetch-abstracts`

```text
.venv/bin/python -m ohbm2026.cli fetch-abstracts [OPTIONS]
```

`ohbmcli ingest` is REMOVED in this change (no alias, per spec
Clarifications session 2026-05-12).

## Wrapper form: `scripts/run_fetch_abstracts.py`

```text
.venv/bin/python scripts/run_fetch_abstracts.py [OPTIONS]
```

The wrapper exists so the README's Stage 1 section has a single
copy-pasteable invocation that does not depend on the `ohbmcli` entry
point's installation state.

## Options

| Option | Type | Default | Purpose |
|---|---|---|---|
| `--env-file PATH` | path | `.env` | dotenv file scanned for `OHBM2026_API`. |
| `--env-var NAME` | string | `OHBM2026_API` | Env var name holding the GraphQL token. |
| `--batch-size N` | int | `50` | Submission IDs per content-fetch GraphQL query. |
| `--timeout-start-ms MS` | int | `100` | Initial timeout for the exponential-backoff retry. |
| `--timeout-limit-seconds S` | float | `10.0` | Maximum timeout in the retry sequence. |
| `--figure-failure-threshold FLOAT` | float | `0.05` | Fraction of figure URLs that may fail to download before the run exits non-zero. Set to `1.0` to never fail on figure errors. |
| `--allow-empty` | flag | off | Permits a fetch that produces zero accepted abstracts to complete successfully. Default: refuse with non-zero exit. |
| `--allow-schema-change` | flag | off | Permits resume from a checkpoint whose `bound_schema_hash` does not match the current schema artifact. Default: refuse with non-zero exit (FR-019). |
| `--no-introspect` | flag | off | Skip the schema introspection step. **Reserved for testing only**; not for production runs. Default: introspect on every run. |
| `--corpus-output PATH` | path | `data/primary/abstracts.json` | Override the corpus snapshot path. MUST stay under a gitignored root or the run aborts (FR-008). |
| `--schema-artifact-dir DIR` | path | `data/inputs/` | Directory for the schema artifact + provenance sidecar. MUST be gitignored. |
| `--checkpoint-dir DIR` | path | `data/cache/fetch_abstracts/` | Directory for the resume checkpoint. MUST be gitignored. |
| `--assets-dir DIR` | path | `data/inputs/assets/` | Local figure-asset directory. |
| `--reuse-existing-assets-only` | flag | off | When set, never make new figure HTTP requests — reuse on-disk assets or skip. |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success — corpus, schema artifact, provenance record all written; checkpoint deleted. |
| `1` | Generic GraphQL or auth failure — `GraphQLAPIError`. Provenance and checkpoint preserved for diagnosis. |
| `2` | Hard-contract schema drift detected — `SchemaContractError`. Corpus snapshot is NOT overwritten. |
| `3` | Checkpoint validation failed — `CheckpointError` (e.g. `bound_schema_hash` mismatch without `--allow-schema-change`). |
| `4` | Output-boundary violation — `ProvenanceError` or a write target outside the gitignored root. |
| `5` | Figure-asset failure-rate exceeded `--figure-failure-threshold`. |
| `6` | Semantically empty corpus and `--allow-empty` not set. |

## Stdout contract

On success, prints a single JSON object to stdout:

```json
{
  "corpus_output": "data/primary/abstracts.json",
  "schema_artifact": "data/inputs/abstracts_graphql_schema__<state-key>.json",
  "provenance_record": "data/inputs/abstracts_fetch_provenance__<state-key>.json",
  "state_key": "<state-key>",
  "abstract_count": 1700,
  "figure_asset_count": 1280,
  "figure_failure_count": 7,
  "resumed_from_previous_run": false,
  "schema_diff_vs_previous": {
    "hard_count": 0,
    "soft_count": 0,
    "informational_count": 12
  }
}
```

On failure, error details go to stderr; stdout receives no JSON.

## Stderr contract

- Retries log to stderr with `[retry]` prefix and the reason.
- Schema-drift errors print the field path, old shape, new shape on
  separate lines.
- All other errors prefix `[fetch-abstracts]`.
- No secrets ever appear in stderr (`env_vars_consulted` is a list
  of NAMES; values never logged).

## Side effects

Stage 1 writes ONLY under the gitignored roots:
- `data/primary/abstracts.json` (overwrite on full completion).
- `data/inputs/abstracts_graphql__<state-key>.json` (existing pattern).
- `data/inputs/abstracts_graphql_schema__<state-key>.json` (NEW).
- `data/inputs/abstracts_fetch_provenance__<state-key>.json` (NEW).
- `data/cache/fetch_abstracts/checkpoint__<state-key>.json` (NEW; deleted on full completion).
- `data/inputs/assets/<abstract-id>_<url-hash>.<ext>` (existing).

If any write would land outside a gitignored root, Stage 1 aborts
(exit 4) without writing anywhere.
