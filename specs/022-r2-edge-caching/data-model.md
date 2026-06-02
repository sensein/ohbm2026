# Phase 1 Data Model: cache evidence + manifest cache policy

No new persisted datasets. This documents the two small structured additions.

## 1. Cache-evidence record (verification — `compare.py` → comparison report)

Per probed URL (and per probe kind: full GET vs inner-table Range), captured from the **live response metadata**:

| Field | Source | Meaning |
|-------|--------|---------|
| `url` | input | the probed object/range on the R2 host |
| `kind` | input | `full` or `range` (with the byte range) |
| `cf_cache_status` | `cf-cache-status` header | HIT / MISS / EXPIRED / DYNAMIC / BYPASS / (absent) |
| `age` | `age` header | seconds the edge has held the entry (>0 corroborates a cache hit) |
| `cache_control` | `cache-control` header | the policy the edge advertises (expected: `public, max-age=31536000, immutable`) |
| `cached` | derived | true iff `cf_cache_status` ∈ {HIT, EXPIRED-then-HIT}; false for DYNAMIC/BYPASS/absent |
| `warmed` | derived | first probe MISS → second probe HIT (legitimate cold→warm) |
| `cold_ms` | measured | wall-clock duration of the first (cold/origin) probe |
| `warm_ms` | measured | wall-clock duration of the second (warm/edge) probe; `warm_ms < cold_ms` corroborates edge-serving (SC-003) |
| `range_byte_parity` | derived (range only) | cached 206 bytes == origin 206 bytes for the same range |
| `flag` | derived | set when a response is bypassing cache, or range parity fails |

**Rules**
- Each probe is issued twice (cold → warm) so a first-request MISS is distinguished from a never-caching BYPASS.
- A `BYPASS`/`DYNAMIC`/absent-status warm response → `flag` (FR-006) → the report marks the host not-cache-effective and the command flags/non-zero-exits.
- Range parity (FR-007): fetch the same byte range from the edge and (cache-bypassing control) the origin/cold path; bytes must match.
- Evidence is appended to the existing `data/outputs/data-hosting-comparison__<ts>.json` (immutable, timestamped — Constitution II).

## 2. Manifest cache-policy field (provenance — `manifest.py`)

Record the cache policy actually applied at publish so a bundle is auditable (FR-010 / CA-008):

- Add a cache-policy field to the upload manifest (channel-level, since the policy is uniform per publish): e.g. `cache_control: "public, max-age=31536000, immutable"`.
- Sourced from the value `r2_client` used for `CacheControl` (expose `_DEFAULT_CACHE_CONTROL` or thread the per-upload value through `uploader.upload_atlas_package`).
- Written into `data/provenance/atlas_upload_provenance__<key>.json` alongside the existing object list — no absolute/home paths.

## State / flow

- **Publish**: `uploader` → `r2_client.upload_*` (already sets `CacheControl`) → `manifest` now records the policy → provenance file.
- **Enable** (one-time, Cloudflare side): host Cache Rule per `contracts/cloudflare-cache-rule.md`.
- **Verify**: `compare-data-hosting` → cold+warm full & range probes → cache-evidence records → report + pass/flag. Run before (expect BYPASS flagged) and after (expect HIT) the rule.

No changes to the published parquet bytes, the content-addressed keys, the site loader, or the production channel selection.
