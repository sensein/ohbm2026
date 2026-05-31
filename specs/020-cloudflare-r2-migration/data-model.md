# Phase 1 Data Model: Cloudflare R2 Migration & Content-Hashed Data Store

These are in-memory dataclasses + their JSON serialisations. No database. The
two persisted artifacts (upload manifest, comparison report) have JSON Schemas
under `contracts/`. All file paths stored in any artifact are repo-relative
(validated by `atlas_package.provenance.normalise_path`).

---

## Entity: ContentAddressedObject

One atlas-package artifact as it lives in R2.

| Field | Type | Rules |
|---|---|---|
| `logical_name` | str | one of `ohbm2026`, `neuroscape`, `atlas`, `neuroscape_vectors` (the registry subkeys) |
| `filename` | str | original on-disk filename, e.g. `neuroscape.parquet` |
| `sha256` | str | 64-char lowercase hex of the exact file bytes |
| `size_bytes` | int | ≥ 0 |
| `object_key` | str | `[<R2_KEY_PREFIX>/]<sha256>/<filename>` |
| `public_url` | str | `${R2_PUBLIC_BASE_URL}/<object_key>`, must be `https://` |
| `source_build_state_key` | str \| null | the `state_key` read from the artifact's parquet `build_info` (provenance link to the build) |
| `action` | enum | `uploaded` \| `skipped` (skipped = already present, dedup) |

**Derivation**: `sha256` is computed by streaming the file (`hashlib.sha256`
over fixed chunks). `object_key` is pure function of `sha256` + `filename`
(+ prefix). `public_url` is pure function of base + key. Identical bytes always
yield identical `object_key` (dedup invariant).

---

## Entity: UploadManifest  (persisted — provenance, CA-008)

Machine-readable record of one `upload-atlas-package` run.
Path: `data/provenance/atlas_upload_provenance__<upload_state_key>.json`.
Schema: `contracts/upload-manifest.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | str | `atlas_upload_manifest.v1` |
| `upload_state_key` | str | `_stable_hash({bucket, key_prefix, [(logical_name, sha256)…] sorted})` (12 hex) |
| `bucket` | str | R2 bucket name (NOT a secret) |
| `public_base_url` | str | `R2_PUBLIC_BASE_URL` value (public) |
| `key_prefix` | str | `R2_KEY_PREFIX` or `""` |
| `code_revision` | str | `git rev-parse HEAD` (best-effort; `"unknown"` if not a repo) |
| `command_line` | str | argv of the invocation (no secrets — creds come from `.env`, never argv) |
| `uploaded_utc` | str | ISO-8601 Z timestamp |
| `source_package_dir` | str | **repo-relative** path of the built package (via `normalise_path`) |
| `artifacts` | array | list of `ContentAddressedObject` (serialised), one per discovered artifact |
| `channel_entry` | object | the emitted registry snippet (see ChannelEntry) — convenience copy |

**Validation**: every `artifacts[*].public_url` is `https://`; no field anywhere
contains an absolute or `~` path (enforced by `normalise_path` on path fields);
no R2 secret appears (only bucket + public base + hashes + URLs).

**Immutability**: one manifest per distinct published set (keyed by
`upload_state_key`); re-running an unchanged upload re-writes the same-named
manifest with all `action: "skipped"` — append-or-rebuild, never mutate a prior
*differently-keyed* manifest.

---

## Entity: ChannelEntry  (emitted — registry-shaped)

The object the operator merges under a new key in
`OHBM2026_UI_DATA_PACKAGE_URLS`. Shape is **identical to the existing registry
channel value** so it drops in unchanged (see `resolve-data-channel.sh`).

```json
{
  "ohbm2026":           { "url": "<public_url>", "sha256": "<sha256>" },
  "neuroscape":         { "url": "<public_url>", "sha256": "<sha256>" },
  "atlas":              { "url": "<public_url>", "sha256": "<sha256>" },
  "neuroscape_vectors": { "url": "<public_url>", "sha256": "<sha256>" }
}
```

| Rule | |
|---|---|
| required keys | `ohbm2026`, `neuroscape`, `atlas`, `neuroscape_vectors` (the production build keeps the semantic index on, so all four are always published) |
| each value | `{"url": https-url, "sha256": 64-hex}` |

---

## Entity: ComparisonReport  (persisted — US3 evidence)

Path: `data/outputs/data-hosting-comparison__<ts>.json`.
Schema: `contracts/comparison-report.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | str | `data_hosting_comparison.v1` |
| `generated_utc` | str | ISO-8601 Z |
| `origin` | str | the site origin used for the CORS probe (e.g. `https://abstractatlas.brainkb.org`) |
| `dropbox_channel` | str | channel key compared on the Dropbox side |
| `r2_channel` | str | channel key compared on the R2 side |
| `artifacts` | array | per-artifact `ArtifactComparison` |
| `overall_pass` | bool | AND of every artifact's `pass` |

### Sub-entity: ArtifactComparison

| Field | Type | Rules |
|---|---|---|
| `logical_name` | str | registry subkey |
| `dropbox` | EndpointProbe | |
| `r2` | EndpointProbe | |
| `byte_parity` | bool | dropbox.sha256 == r2.sha256 |
| `pass` | bool | `byte_parity AND r2.range_supported AND r2.cors_allowed AND r2.reachable` |

### Sub-entity: EndpointProbe

| Field | Type | Rules |
|---|---|---|
| `url` | str | probed URL |
| `reachable` | bool | a GET/HEAD returned a 2xx/3xx/206 |
| `sha256` | str \| null | null if not downloaded (`--trust-recorded-sha256`) — then recorded hash used |
| `status` | int \| null | HTTP status of the range probe |
| `range_supported` | bool | `206` + valid `Content-Range` |
| `cors_allowed` | bool | response carried an acceptable `Access-Control-Allow-Origin` for `origin` |
| `latency_ms` | number \| null | informational; not a gate |
| `error` | str \| null | populated when a probe verdict is a failure (never silently omitted) |

**Fail-loud rule (FR-015)**: a probe that cannot run records its verdict field as
`false` with `error` set; it is never dropped. `overall_pass=false` if any
artifact fails. A probe that cannot be *attempted at all* (e.g. URL malformed)
raises `HostingComparisonError`.

---

## State-key derivations (deterministic naming)

| Key | Basis (via `artifacts._stable_hash`) |
|---|---|
| `upload_state_key` | `{bucket, key_prefix, artifacts: [(logical_name, sha256) sorted]}` |
| `object_key` | not a state-key — direct `<sha256>/<filename>` (full hash) |

---

## Validation rules → tests (test-first, Constitution IV)

| Rule | Test (red before implementation) |
|---|---|
| `object_key` stable for identical bytes; distinct for differing bytes | `test_atlas_hosting_content_hash.py` |
| `sha256` matches stdlib hash of file bytes (streamed == whole) | `test_atlas_hosting_content_hash.py` |
| existing key (200) → `skipped`, no PUT issued | `test_atlas_hosting_uploader.py` (Stubber) |
| absent key (404) → `uploaded`, one PUT | `test_atlas_hosting_uploader.py` (Stubber) |
| existing object size ≠ local → `ContentHashMismatchError` | `test_atlas_hosting_uploader.py` |
| missing required artifact in package dir → `ArtifactDiscoveryError` | `test_atlas_hosting_uploader.py` |
| required `neuroscape_vectors` absent → `ArtifactDiscoveryError` (it is no longer optional) | `test_atlas_hosting_uploader.py` |
| `ohbm2026.parquet` supplied separately (Stage-10 build), not in the package dir | `test_atlas_hosting_uploader.py` |
| manifest contains no absolute/`~` path | `test_atlas_hosting_uploader.py` |
| missing `R2_*` env var → `R2CredentialsError` before any network call | `test_atlas_hosting_uploader.py` |
| comparison verdicts: parity/Range/CORS booleans + `overall_pass` AND | `test_atlas_hosting_compare.py` |
| failed probe → recorded verdict + `error`, never omitted; `overall_pass=false` | `test_atlas_hosting_compare.py` |
| `Stage20Error` subtree subclasses + `__all__` exports | `test_stage20_exceptions.py` |
| non-Dropbox HTTPS URL unchanged by `normaliseDropboxUrl` | `site/src/tests/unit/loader_r2_passthrough.test.ts` |
