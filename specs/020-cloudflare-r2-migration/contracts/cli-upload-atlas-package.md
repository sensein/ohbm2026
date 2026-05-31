# CLI Contract: `ohbmcli upload-atlas-package`

Upload a locally built atlas package's parquet artifacts to Cloudflare R2 under
content-addressed, immutable keys; emit a registry channel entry + an upload
manifest. Local, idempotent, non-destructive.

## Invocation

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli upload-atlas-package \
  --package-dir data/outputs/atlas-package__<state-key> \
  --ohbm2026-parquet data/outputs/parquets/<state-key>/ohbm2026.parquet \
  [--env-file .env] \
  [--manifest-out data/provenance/] \
  [--dry-run]
```

## Arguments

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--package-dir` | path | **required** | The `build-atlas-package --output-root`: holds `neuroscape.parquet`, `atlas.parquet`, and `neuroscape_vectors.parquet` (all required). |
| `--ohbm2026-parquet` | path | **required** | Path to `ohbm2026.parquet` (the Stage-10 build — it lives apart from the atlas-package output, typically `data/outputs/parquets/<key>/ohbm2026.parquet`). |
| `--env-file` | path | `.env` | File the R2 credentials are read from. |
| `--manifest-out` | path | `data/provenance/` | Directory for the upload manifest. |
| `--dry-run` | flag | off | Compute hashes/keys/URLs, run `head_object` existence checks, print the would-be channel entry + per-artifact action — but issue **no** PUT and write **no** manifest. |

## Environment (read from `--env-file`; values never logged)

| Var | Required | Meaning |
|---|---|---|
| `R2_ACCOUNT_ID` | yes | Endpoint = `https://<id>.r2.cloudflarestorage.com`. |
| `R2_ACCESS_KEY_ID` | yes | S3 access key. |
| `R2_SECRET_ACCESS_KEY` | yes | S3 secret. |
| `R2_BUCKET` | yes | Target bucket. |
| `R2_PUBLIC_BASE_URL` | yes | Public base (`https://pub-….r2.dev` or custom domain) for forming URLs. |
| `R2_KEY_PREFIX` | no | Optional key namespace; default empty. |

A missing/blank required var → `R2CredentialsError`, exit non-zero, before any
network call.

## Behaviour

1. **Discover artifacts** at runtime (Constitution VII): `ohbm2026.parquet`
   from `--ohbm2026-parquet`; `neuroscape.parquet`, `atlas.parquet`, and
   `neuroscape_vectors.parquet` from `--package-dir` — all four required. A
   missing required file → `ArtifactDiscoveryError`. An unexpected `*.parquet`
   in `--package-dir` (including a stray `ohbm2026.parquet`, which belongs at
   `--ohbm2026-parquet`) → `ArtifactDiscoveryError` (no silent inclusion).
2. **Hash** each file (streamed sha256) → derive `object_key` = `[prefix/]<sha256>/<filename>`.
3. **Read** each artifact's `build_info.state_key` from its parquet for the
   manifest's `source_build_state_key` (best-effort; null if unreadable, logged).
4. For each artifact, **`head_object`**:
   - 404 → `upload_file` (multipart for large files); `action="uploaded"`.
   - 200 → skip; `action="skipped"`. If `ContentLength` ≠ local size →
     `ContentHashMismatchError`.
   - other `ClientError` → `R2UploadError` (with key/bucket/op).
5. **Emit** the channel entry (registry-shaped JSON) to stdout.
6. **Write** the upload manifest to `--manifest-out` (skipped under `--dry-run`).

## Exit codes

| Code | Condition |
|---|---|
| 0 | All artifacts present in R2 after the run (uploaded or already-present); manifest written. |
| non-zero | Any `Stage20Error` (creds, discovery, hash mismatch, upload). Nothing is partially "registered" — the channel entry is only emitted on success. |

## Output (stdout, success)

```json
{
  "channel_entry": {
    "ohbm2026":           {"url": "https://aadata.cirrusscience.org/<sha>/ohbm2026.parquet",           "sha256": "<sha>"},
    "neuroscape":         {"url": "https://aadata.cirrusscience.org/<sha>/neuroscape.parquet",         "sha256": "<sha>"},
    "atlas":              {"url": "https://aadata.cirrusscience.org/<sha>/atlas.parquet",              "sha256": "<sha>"},
    "neuroscape_vectors": {"url": "https://aadata.cirrusscience.org/<sha>/neuroscape_vectors.parquet", "sha256": "<sha>"}
  },
  "manifest_path": "data/provenance/atlas_upload_provenance__<key>.json",
  "summary": {"uploaded": 1, "skipped": 2}
}
```

## Guarantees

- **Idempotent** (SC-003): a re-run on an unchanged package issues zero PUTs
  (`summary.uploaded == 0`).
- **Non-destructive** (FR-008, SC-004): never deletes/overwrites; previously
  published keys remain.
- **Secret-safe**: creds never appear in stdout, the manifest, or logs.
