# Quickstart: enable + verify R2 edge caching

Track A (`ohbmcli atlas_hosting`). Python via `.venv`. Requires R2 vars in `.env` (Stage 20): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`.

## 0. Baseline — confirm the host is NOT caching (before)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli compare-data-hosting
# Read data/outputs/data-hosting-comparison__<ts>.json → cache section:
# expect cf-cache-status DYNAMIC/BYPASS on the R2 host → flagged "not cache-effective".
```

## 1. Publish carries the immutable policy (already true — verify)

```bash
# The uploader already sets Cache-Control: public, max-age=31536000, immutable on
# every object (single + multipart). Unit guard:
PYTHONPATH=src .venv/bin/python -m unittest tests.test_atlas_hosting_r2_client -v
# A (re)publish now also records the policy in the manifest provenance:
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli upload-atlas-package --help
# → data/provenance/atlas_upload_provenance__<key>.json includes cache_control.
```

## 2. Enable the Cloudflare host cache rule (one-time, infra)

Apply the rule in `contracts/cloudflare-cache-rule.md` to the `aadata.cirrusscience.org` host (dashboard by default): eligible-for-cache, respect origin `Cache-Control`, keep 206/Range cacheable, preserve CORS.

## 3. Verify — confirm caching now works (after)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli compare-data-hosting
# Read the new comparison report's cache section:
#  - warm full GET  → cf-cache-status: HIT
#  - warm Range 206 → cf-cache-status: HIT, range byte-parity OK
#  - CORS + If-None-Match still pass
#  - aggregate: host is edge-cache-effective (no flags)
```

## 4. Unit tests

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
  tests.test_atlas_hosting_compare tests.test_atlas_hosting_r2_client tests.test_atlas_hosting_manifest -v
```

## Done-when
- `compare-data-hosting` reports HIT on warm full + range requests with range byte-parity, CORS intact (SC-003/004/005/006).
- Cloudflare dashboard cached-request rate climbs off 0% toward steady-state ≥90% (SC-001).
- Manifest records the cache policy (FR-010); production channel unchanged (still Dropbox — FR-009/SC-007).
- Unit suites green; `cloudflare_cache_unused` memory item closed out.
