# Phase 0 Research: Edge caching for the R2 data host

Grounded in the Stage 20 code (`src/ohbm2026/atlas_hosting/`) and the `cloudflare_cache_unused` memory item.

## R-001 — Enabling cache on an R2 custom domain (the actual 0%-fix)

**Context**: `aadata.cirrusscience.org` is an R2 custom domain. The dashboard shows 0% cached. R2 custom domains are **not** edge-cached by default — Cloudflare proxies to the R2 origin but does not cache unless a Cache Rule (or the legacy Page Rule / "Cache Everything") makes responses eligible.

**Decision**: Add a **Cloudflare Cache Rule** scoped to the `aadata.cirrusscience.org` host: set "eligible for cache", respect the origin `Cache-Control` (which is already `public, max-age=31536000, immutable`) for edge TTL, and ensure status-206/partial responses are cacheable. Document the exact settings in `contracts/cloudflare-cache-rule.md` so it is reproducible/auditable (FR-008). Apply it **manually via the dashboard by default**; automating via the Cloudflare API is an optional stretch, gated on a `CLOUDFLARE_API_TOKEN` in `.env` (Constitution V) — out of default scope.

**Rationale**: The repo can't (and shouldn't, by default) own Cloudflare zone config; a precisely-documented rule is reproducible and the verification check (R-005) proves it took effect. Respecting origin `Cache-Control` reuses the immutable policy already on every object, so edge + browser both cache for a year — safe because keys are content-addressed.

**Alternatives rejected**: a Cloudflare Worker fronting R2 (more moving parts than a Cache Rule for a pure-GET immutable bundle); per-deploy API automation as the default (adds a credential + failure surface for a one-time zone setting).

## R-002 — Range (HTTP 206) caching behavior

**Context**: the loader's whole point is per-table predicate-pushdown via Range requests (`row_group_size=1` envelopes). If 206 responses bypass cache, the feature gains nothing. `compare.py` already proves Range is *honored* (206 + `content-range`); it does not check whether 206 is *cached*.

**Decision**: The cache rule must allow caching partial responses; verification (R-005) must assert that a **repeated** range request returns a cache hit (`cf-cache-status: HIT`) and that the cached partial bytes equal the origin's partial bytes for the same range. Cloudflare caches the requested ranges (range-aware) once the asset is cache-eligible; the verification confirms this empirically rather than assuming it.

**Rationale**: Range caching is the highest-risk correctness point (partial-content + cache interaction); making it an explicit, byte-parity-checked assertion (FR-004/FR-007) catches a misconfigured rule that caches full GETs but bypasses ranges.

## R-003 — Detecting cache status from response metadata

**Decision**: Read cache effectiveness from real response headers on live requests (Constitution VII): `cf-cache-status` (HIT / MISS / EXPIRED / DYNAMIC / BYPASS), `age`, and the echoed `cache-control`. Classify: `HIT` = cached; `MISS`/`EXPIRED` then `HIT` on repeat = warming correctly; `DYNAMIC`/`BYPASS` = **not cached → flag**. The check issues each probe twice (cold → warm) to distinguish a legitimate first-request miss from a never-caching bypass.

**Rationale**: The dashboard rate is a lagging aggregate; per-request `cf-cache-status` is the authoritative, immediate signal and is what makes the before/after auditable in a single run.

**Alternatives rejected**: relying solely on the dashboard (slow, not scriptable, not byte-level).

## R-004 — Is the immutable policy already applied on upload? (US2 status)

**Finding (confirmed in code)**: YES. `r2_client.py` uploads via boto3 `upload_file` with `ExtraArgs={"ContentType": …, "CacheControl": "public, max-age=31536000, immutable"}` and a `TransferConfig(multipart_threshold=8 MiB)`. `upload_file` applies `ExtraArgs` to **both** single-part `put_object` and multipart transfers, so every object — including the large `neuroscape_vectors` sidecar — already carries the immutable policy.

**Decision**: Do **not** re-implement; instead (a) add a regression unit test asserting the `CacheControl` ExtraArg is set, and (b) **record the applied policy in the upload manifest** (FR-010) — currently `ContentAddressedObject`/`UploadManifest` don't capture it. Expose `_DEFAULT_CACHE_CONTROL` (or the per-upload value) so `uploader.py` can thread it into the manifest.

**Rationale**: The publish side is correct; the gap is purely that it isn't recorded for audit and that the *edge* isn't caching (R-001).

## R-005 — Where the verification lives

**Context**: `compare.py` already probes reachability, Range support, CORS (incl. the If-None-Match preflight), and byte-parity, and `ohbmcli compare-data-hosting` writes `data/outputs/data-hosting-comparison__<ts>.json`.

**Decision**: **Extend** `compare.py`/`compare-data-hosting` rather than add a new command: add cache-status/age/cache-control capture to `probe_endpoint` (or a sibling cache probe), the cold→warm double-request, the bypass flag, and the range byte-parity assertion; surface them in the existing comparison report + a clear non-zero/flagged exit when the host is bypassing. Keep network calls behind the existing injected `http_request` so the logic is unit-testable with mocks.

**Rationale**: One evidence command + one report artifact for "is the R2 channel healthy" (parity + CORS + Range + **now cache**); reuses the existing provenance/output path and the typed `Stage20Error` handling.

## Cross-cutting: docs & tests (IV/CA-003)

- Docs: README + `specs/020-cloudflare-r2-migration` notes (cache rule + verification), the new `contracts/cloudflare-cache-rule.md`, and close out `memory/cloudflare_cache_unused.md` once verified.
- Tests: `r2_client` ExtraArgs guard; `compare` cache-status/bypass/range-parity logic (mocked http); `manifest` records the policy.
