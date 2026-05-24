# Contract — `ohbmcli build-atlas-package` (Stage 15)

This contract pins the CLI surface, the input/output contract, and the
typed-exception surface for the new orchestrator. Python `unittest`
modules MUST cover every error path enumerated below.

## Invocation

```text
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-atlas-package \
    --neuroscape-source data/inputs/neuroscape-source/v101 \
    --voyage-bundle voyage_stage2_published \
    --ohbm2026-parquet data/outputs/parquets/<state>/ohbm2026.parquet \
    --output-root data/outputs/parquets/<state>/ \
    --umap-cache-root data/cache/atlas-umap \
    --projection-cache-root data/cache/atlas-projection \
    [--decimated-backdrop-size 50000] \
    [--neighbors-k 20] \
    [--link-check-rate 3.0] \
    [--ncbi-api-key-env NCBI_API_KEY] \
    [--force-rebuild umap|projection|neighbors|all] \
    [--no-link-check]
```

The thin shim script
`scripts/run_build_atlas_package.py` mirrors the existing
`scripts/run_enrich_abstracts.py` pattern (positional + env-driven
sensible defaults; the bare `--help` output documents every flag).

### Required arguments

| Flag | Purpose |
|------|---------|
| `--neuroscape-source` | Path to the unzipped NeuroScape v1.0.1 release root (contains `DomainEmbeddings/*.h5`, `neuroscience_articles_*.csv`, `neuroscience_clusters_*.csv`, `Data/Models/domain_embedding_model.pth`). The orchestrator discovers the centroid table version from this path at runtime (CA-007 / R-001). |
| `--voyage-bundle` | Voyage bundle id whose Stage-2 vectors are projected for the OHBM 2026 overlay. The default is `voyage_stage2_published`; only override during development. |
| `--ohbm2026-parquet` | Path to the canonical (renamed) `ohbm2026.parquet`. Its manifest's `build_info.state_key` is read and embedded into `atlas.parquet`'s `sibling_state_keys` per R-012. |
| `--output-root` | Directory to write the three parquets + provenance into. Created atomically (temp dir → `os.rename`) so a failed run never leaves a partial directory at the canonical path. |

### Optional arguments

| Flag | Default | Notes |
|------|---------|-------|
| `--umap-cache-root` | `data/cache/atlas-umap` | UMAP fit cache root. |
| `--projection-cache-root` | `data/cache/atlas-projection` | Per-OHBM-2026 abstract projection cache root. |
| `--decimated-backdrop-size` | 50000 | Target row count for `neuroscape_backdrop_decimated`. Per-cluster stratified sample, deterministic seed=0. |
| `--neighbors-k` | 20 | k for the NeuroScape k-NN table per R-008. |
| `--link-check-rate` | 3.0 | requests/second for the small fixed set of non-PubMed-record URLs (R-013). Per-PubMed-record URLs are NOT pre-checked at build time. |
| `--ncbi-api-key-env` | `NCBI_API_KEY` | Env var name to read the NCBI API key from. Used only for the (small) fixed link-check pass. Key is never echoed (CA-004 + Principle V). |
| `--force-rebuild` | (none) | Invalidates the named cache region and triggers a full re-execution of that step + every downstream step. |
| `--no-link-check` | false | DEV ONLY. Skips the build-time link check. Must NOT be used in CI. The orchestrator refuses `--no-link-check` if `CI=true`. |

## Outputs

```text
data/outputs/parquets/<state-key>/
├── ohbm2026.parquet                  # copied/moved in by ohbmcli build-ui-data; this orchestrator does NOT re-write it
├── neuroscape.parquet
├── atlas.parquet
└── (none other)

data/provenance/neuroscape_context_provenance__<state-key>.json
```

The orchestrator MUST NOT write to any directory outside of:
- `--output-root`
- `--umap-cache-root`
- `--projection-cache-root`
- `data/cache/atlas-runs/<state-key>/` (sentinel files for
  resumability)
- `data/provenance/`

Any attempt to write elsewhere is a bug.

## Provenance file contract

`data/provenance/neuroscape_context_provenance__<state-key>.json`:

```json
{
  "schema_version": "neuroscape_context_provenance.v1",
  "state_key": "<12-hex>",
  "code_revision": "<git rev-parse HEAD>",
  "command_line": ["python", "-m", "ohbm2026.cli", "build-atlas-package", "..."],
  "seed": 0,
  "started_utc": "<ISO8601>",
  "finished_utc": "<ISO8601>",
  "inputs": {
    "neuroscape_source_root": "<repo-relative path>",
    "voyage_bundle_id": "voyage_stage2_published",
    "ohbm2026_parquet": "<repo-relative path>",
    "ohbm2026_parquet_sha256": "<hex>",
    "centroid_table_version": "<12-hex>",
    "domain_model_checkpoint_sha256": "<hex>",
    "neuroscience_articles_csv_sha256": "<hex>",
    "neuroscience_clusters_csv_sha256": "<hex>",
    "hdf5_shard_manifest_sha256": "<hex>",
    "hdf5_shard_count": <int>
  },
  "umap_params": {
    "seed": 0,
    "n_neighbors": 30,
    "min_dist": 0.10,
    "metric": "cosine",
    "init": "spectral",
    "n_components_3d": 3,
    "n_components_2d": 2
  },
  "ohbm_inclusion": {
    "n_overlay_points":     <int>,
    "n_omitted":            <int>,
    "omitted_submission_ids": [<int>, ...]
  },
  "outputs": {
    "ohbm2026_parquet":   "<repo-relative path>",
    "neuroscape_parquet": "<repo-relative path>",
    "atlas_parquet":      "<repo-relative path>",
    "ohbm2026_parquet_sha256":    "<hex>",
    "neuroscape_parquet_sha256":  "<hex>",
    "atlas_parquet_sha256":       "<hex>",
    "ohbm2026_state_key":   "<12-hex>",
    "neuroscape_state_key": "<12-hex>",
    "atlas_state_key":      "<12-hex>"
  },
  "link_check": {
    "scope": "non-pubmed-record only (per FR-024 / R-013)",
    "checked_urls": [<{"name": "neuroscape_zenodo", "url": "..."}, ...>],
    "n_total": <int>,
    "n_2xx":   <int>,
    "n_3xx":   <int>,
    "n_4xx":   <int>,
    "n_5xx":   <int>,
    "deploy_blocking_failures": [<{"name":..., "url":..., "status":...}>, ...]
  }
}
```

All paths inside provenance MUST be repo-relative. The orchestrator
calls `provenance.normalise_path(p)` on every path; an absolute or
`$HOME`-prefixed path raises `AtlasProvenanceError` (CA-008).

## Typed exception subtree (R-009)

```text
OhbmStageError(RuntimeError)
└── Stage15Error
    ├── NeuroScapeInputError
    ├── UmapFitError
    ├── OhbmProjectionError
    ├── CrossParquetDriftError
    ├── AtlasProvenanceError
    └── AtlasLinkCheckError
```

Each subclass carries structured context (file path, expected value,
actual value, offending id) as kwargs to `super().__init__`. Tests:

| Exception | Test module | Trigger |
|-----------|-------------|---------|
| `NeuroScapeInputError` | `tests/test_atlas_exceptions.py::test_input_sha_mismatch` | Mutate a fixture CSV byte after caching the original SHA in metadata. |
| `UmapFitError` | `tests/test_atlas_umap_fit.py::test_umap_fit_handles_singular` | Inject a degenerate vector matrix (rank-deficient). |
| `OhbmProjectionError` | `tests/test_atlas_exceptions.py::test_projection_aggregates_all_failures` | Inject a NaN into one stage-2 vector; assert the orchestrator collects all failures and re-raises ONCE at the end (resumability). |
| `CrossParquetDriftError` | `tests/test_atlas_parquet_writer.py::test_writer_rejects_cluster_table_mismatch` | Build with a hand-edited cluster table that diverges between the two outputs. |
| `AtlasProvenanceError` | `tests/test_atlas_provenance.py::test_absolute_path_rejected` | Inject `/tmp/...` into a path field; assert raise. |
| `AtlasLinkCheckError` | `tests/test_atlas_exceptions.py::test_link_check_failure_blocks_run` | Mock the link-checker to return a 404 for one URL; assert the orchestrator raises `AtlasLinkCheckError` listing every 4xx/5xx hit. |

## Resumability sentinels

Each labelled orchestrator step (data-model.md "state machine")
writes a sentinel file
`data/cache/atlas-runs/<state-key>/<step>.done` on success. A second
invocation reads the sentinels and skips finished steps. Sentinel
content is a one-line ISO8601 timestamp + git SHA for auditability.

## Determinism guarantee

For an unchanged input set (same NeuroScape source SHAs, same
`ohbm2026.parquet` sha, same Voyage bundle, same code revision, same
CLI flags), the orchestrator produces byte-identical
`neuroscape.parquet` and `atlas.parquet`. This is asserted by
`tests/test_atlas_orchestrator.py::test_idempotent_rebuild`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0    | Run completed; all three parquets + provenance present. |
| 1    | Catch-all for unhandled exceptions (should be impossible under contract). |
| 2    | `NeuroScapeInputError` (input drift). |
| 3    | `UmapFitError`. |
| 4    | `OhbmProjectionError` (aggregated). |
| 5    | `CrossParquetDriftError`. |
| 6    | `AtlasProvenanceError`. |
| 7    | `AtlasLinkCheckError`. |

CI parses exit codes to surface specific failure modes in the build
status check name.
