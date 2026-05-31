# Quickstart: Publish the Atlas Data Bundle to Cloudflare R2

Operator runbook for Stage 20. Prerequisites: a built atlas package (from
`ohbmcli build-atlas-package`) under `data/outputs/atlas-package__<state-key>/`,
an R2 bucket, and the `r2` extra installed.

## 0. One-time setup

```bash
# Install the optional R2 client into the repo venv
uv pip install --python .venv/bin/python ".[r2]"
```

Add R2 credentials to `.env` (gitignored — never commit):

```dotenv
R2_ACCOUNT_ID=<cloudflare-account-id>
R2_ACCESS_KEY_ID=<r2-access-key-id>
R2_SECRET_ACCESS_KEY=<r2-secret>
R2_BUCKET=<bucket-name>
R2_PUBLIC_BASE_URL=https://aadata.cirrusscience.org   # configured custom domain (CORS already set)
# R2_KEY_PREFIX=                                       # optional namespace
```

Configure the bucket once for public read + CORS + Range (see
`contracts/r2-storage-layout.md` §"Required bucket configuration").

## 1. Dry-run the upload (no writes)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli upload-atlas-package \
  --package-dir data/outputs/atlas-package__<state-key> \
  --ohbm2026-parquet data/outputs/parquets/<corpus-key>/ohbm2026.parquet \
  --dry-run
```

Prints each artifact's content hash, content-addressed key, would-be public
URL, and `head_object` action (`uploaded`/`skipped`). No PUTs, no manifest.

## 2. Upload

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli upload-atlas-package \
  --package-dir data/outputs/atlas-package__<state-key> \
  --ohbm2026-parquet data/outputs/parquets/<corpus-key>/ohbm2026.parquet
```

The bundle spans two locations: `--package-dir` holds `neuroscape.parquet` +
`atlas.parquet` + `neuroscape_vectors.parquet` (all required); `ohbm2026.parquet`
is the Stage-10 build supplied via `--ohbm2026-parquet`. Emits the **channel
entry** JSON to stdout and writes
`data/provenance/atlas_upload_provenance__<key>.json`. Idempotent: re-running
on the same package uploads zero bytes.

## 3. Register a new R2 channel

Take the emitted `channel_entry` and add it under a NEW key in the
`OHBM2026_UI_DATA_PACKAGE_URLS` GitHub Actions variable (the registry is
operator-managed; the CLI never touches GitHub):

```bash
# Pull current registry, merge the new channel under e.g. "r2-validate", push back:
gh variable get OHBM2026_UI_DATA_PACKAGE_URLS > /tmp/registry.json   # local only; never commit
#   …merge channel_entry under "r2-validate"…
gh variable set OHBM2026_UI_DATA_PACKAGE_URLS < /tmp/registry.json
```

Point the validation branch at it:

```jsonc
// site/data-channel.json
{ "key": "r2-validate" }
```

Push the branch — its PR preview, sandbox, and prod builds now resolve the R2
URLs through the unchanged `resolve-data-channel.sh`.

## 4. Validate the live site

Open the PR preview and confirm `/ohbm2026/`, `/neuroscape/`, and atlas-root all
render with no console fetch/CORS/Range errors (SC-001) — atlas-root exercises a
sibling Range fetch from `neuroscape.parquet`.

## 5. Compare Dropbox vs R2 (evidence for the cutover decision)

```bash
gh variable get OHBM2026_UI_DATA_PACKAGE_URLS > /tmp/registry.json
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli compare-data-hosting \
  --registry /tmp/registry.json \
  --dropbox-channel <current-prod-key> \
  --r2-channel r2-validate \
  --origin https://abstractatlas.brainkb.org
```

Writes `data/outputs/data-hosting-comparison__<ts>.json` and prints a per-artifact
✓/✗ table for byte-parity / Range / CORS. Exit 0 = all pass (SC-005). This report
is the input to the (separate) production-cutover decision.

## 6. Future atlas update

Rebuild the package, then repeat steps 2–4. Changed artifacts get new
content-addressed keys; unchanged ones are skipped; every previously published
URL keeps resolving (FR-008/FR-013, SC-004). Register the new channel entry under
a fresh key and move the relevant branch's `data-channel.json` to it.

---

## Tests (test-first — write red, then implement)

Python (`PYTHONPATH=src .venv/bin/python -m unittest tests.<module> -v`):

| Module | Covers |
|---|---|
| `tests/test_atlas_hosting_content_hash.py` | object-key derivation stable/distinct; streamed sha256 == whole-file hash |
| `tests/test_atlas_hosting_uploader.py` | dedup skip (200) vs upload (404) via `botocore.stub.Stubber`; size-mismatch → `ContentHashMismatchError`; missing/unexpected artifact → `ArtifactDiscoveryError`; optional vectors omitted; missing env → `R2CredentialsError`; manifest has no absolute/`~` paths; no secret in manifest |
| `tests/test_atlas_hosting_compare.py` | parity/Range/CORS verdicts; `200`-not-`206` → range fail; failed probe recorded with `error` (not omitted); `overall_pass` is AND; un-attemptable probe → `HostingComparisonError` (requests mocked) |
| `tests/test_atlas_hosting_cli.py` | argparse surface + top-level dispatch + exit codes (`--dry-run` issues no PUT) |
| `tests/test_stage20_exceptions.py` | `Stage20Error` subtree subclasses + `__all__` exports (mirror `test_atlas_exceptions.py`) |

Site (`cd site && pnpm exec vitest run src/tests/unit/loader_r2_passthrough.test.ts`
— use `vitest run`, never `pnpm test:unit -- --run`):

| Spec | Covers |
|---|---|
| `site/src/tests/unit/loader_r2_passthrough.test.ts` | `normaliseDropboxUrl('https://pub-x.r2.dev/<sha>/atlas.parquet')` returns the URL unchanged (FR-005) |

Schema validation: the manifest and report validate against
`contracts/upload-manifest.schema.json` and `contracts/comparison-report.schema.json`.
