# Feature Specification: Edge caching for the R2 data host

**Feature Branch**: `022-r2-edge-caching`
**Created**: 2026-06-02
**Status**: Draft
**Input**: User description: "let's pull the memory item about caching into the next spec"

## Overview

The OHBM/atlas UI data bundle (the content-addressed parquets from Stage 20) is published to Cloudflare R2 and served from the custom domain `https://aadata.cirrusscience.org` under immutable `<sha256>/<filename>` keys. The browser loader issues **many per-table HTTP Range requests** against these envelope parquets on every visit.

As of 2026-06-01 the Cloudflare dashboard for that host shows the edge cache **effectively unused** — Cached requests 0, cached-request rate 0%, cached bandwidth 0 B. Every range fetch is being served straight from the R2 origin. Because R2 public buckets / custom domains are **not** edge-cached by default and Range (HTTP 206) responses are commonly bypassed unless configured, visitors pay full origin latency and the project pays R2 egress on every request — defeating much of the point of fronting R2 with a CDN.

The keys are **immutable and content-addressed**, so they are ideal candidates for aggressive, long-TTL edge caching. This feature makes the R2-hosted data bundle actually served from the CDN edge cache, in a way that is verifiable and that does not break the per-table range-fetch loader or byte-parity.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Cached data loads (Priority: P1)

A visitor opens an atlas/OHBM surface whose data is served from the R2 host. The data bundle (and its per-table range slices) is served from the nearest CDN edge on repeat/warm requests rather than from the R2 origin, so the page's data loads faster and the project incurs no R2 egress for cache hits. The content the visitor receives is byte-identical to what the origin would have returned.

**Why this priority**: This is the core value — turn the 0% cache rate into a high hit rate so the CDN actually accelerates data delivery and cuts egress. Everything else supports verifying and safely enabling this.

**Independent Test**: Issue the same (range and full) requests against the R2 host twice; confirm the second response is served from the edge cache (a cache "hit" indicator) and that warm-cache latency is materially lower than a cold/origin fetch, with identical bytes.

**Acceptance Scenarios**:

1. **Given** a previously-requested object/range on the R2 host, **When** it is requested again, **Then** the response is served from the edge cache (cache-status = hit) rather than the origin.
2. **Given** a range request for one inner table (the loader's predicate-pushdown pattern), **When** it is repeated, **Then** the 206 partial response is cache-served and byte-identical to the origin's partial response.
3. **Given** a freshly published bundle, **When** its objects are first requested, **Then** subsequent requests warm into cache hits within the configured policy (cold miss → warm hit).

---

### User Story 2 - Immutable cache policy on every published object (Priority: P1)

When the data bundle is published to R2, each object carries a cache policy that lets the CDN and browsers cache it for a long time without revalidation, which is safe because the keys are content-addressed (a changed file gets a new key). Re-publishing the bundle keeps this policy on every object.

**Why this priority**: Without an explicit long-lived, immutable cache policy on the objects, the edge cache (and browser cache) won't retain them aggressively. This is the publish-side half of US1 and is required for the cache to be effective.

**Independent Test**: After a publish, inspect any object's response metadata and confirm it advertises a long max-age + immutable policy; confirm a re-publish (idempotent) leaves the policy present on all objects.

**Acceptance Scenarios**:

1. **Given** a publish of the data bundle, **When** any published object is fetched, **Then** its response advertises a long-lived, immutable cache policy.
2. **Given** an object already present from a prior publish, **When** the bundle is re-published, **Then** the cache policy remains correct (no object left without it).
3. **Given** the publish provenance record, **When** it is read, **Then** it records the cache policy that was applied.

---

### User Story 3 - Verifiable cache behavior + safe Range interaction (Priority: P2)

An operator can run a check that reports, for the R2 host, whether responses are being edge-cached (cache-status, policy headers, age) for both full and range requests, and confirms the partial-content (Range/206) responses the loader depends on are cached and byte-correct. The check makes the before/after improvement auditable.

**Why this priority**: The reported defect was discovered only via the dashboard; the project needs a repeatable, machine-readable way to confirm the cache is working and that Range caching didn't subtly break the loader. Builds on the existing data-hosting comparison evidence.

**Independent Test**: Run the operator check against the R2 host and confirm it reports cache-status for full + range requests, flags any uncached responses, and verifies range byte-parity — exiting non-zero (or clearly flagging) if caching is not actually happening.

**Acceptance Scenarios**:

1. **Given** the R2 host, **When** the operator runs the cache check, **Then** it reports cache-status, cache policy, and age for representative full and range requests.
2. **Given** a host where caching is misconfigured (still bypassing), **When** the check runs, **Then** it clearly flags the bypass rather than silently passing.
3. **Given** a range request, **When** the check verifies it, **Then** the cached partial bytes match the origin's partial bytes for the same range.

---

### Edge Cases

- **Range/206 bypass**: partial-content responses are frequently excluded from CDN caching by default; the policy must explicitly allow (and verification must confirm) range caching, or the loader gains nothing.
- **Cold cache / first visitor**: the first request after publish (or after edge eviction) is an origin miss; the policy must let it warm into hits, and the check must distinguish a legitimate cold miss from a never-caching bypass.
- **Stale edge entry after a (hypothetical) key reuse**: keys are content-addressed and immutable, so a long TTL is safe; the spec assumes keys are never overwritten with different bytes (Stage 20 guarantees immutability).
- **Production channel still Dropbox**: Stage 20 keeps Dropbox as the production default (cutover deferred); this feature improves the R2 channel so it is cache-ready when/if it becomes the default, and must not change which channel the site uses.
- **CORS + cache interaction**: the cross-origin range fetches the loader uses must continue to work once responses are cache-served (cache must not strip required CORS headers).
- **Cache policy unset on some objects**: a partial/failed publish could leave objects without the policy; re-publish must be able to bring every object into compliance.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Objects published to the R2 data host MUST be served with an explicit long-lived, immutable cache policy (safe because keys are content-addressed and never overwritten with different bytes).
- **FR-002**: The publish step MUST apply that cache policy to every object it writes. Because keys are content-addressed and the uploader is idempotent (an existing key is skipped, never overwritten), each object's policy is fixed at first upload and a re-publish is a no-op for already-present objects — so policy "compliance" is inherent rather than achieved by re-stamping existing objects. The applied policy MUST be recorded in provenance (FR-010) so it is auditable without re-reading every object.
- **FR-003**: The R2 host MUST serve repeat requests (full and range) from the CDN edge cache rather than the origin, achieving a high cache-hit rate for the immutable bundle.
- **FR-004**: Range (HTTP 206 partial-content) responses — the loader's per-table predicate-pushdown pattern — MUST be edge-cacheable and, when cache-served, byte-identical to the origin's partial response.
- **FR-005**: Cross-origin access (the headers the browser loader requires) MUST continue to work for cache-served responses; enabling caching MUST NOT break the existing CORS/range behavior.
- **FR-006**: An operator-runnable check MUST report, for representative full and range requests against the R2 host, the cache status, cache policy, and age, and MUST flag (not silently pass) when responses are bypassing the cache.
- **FR-007**: The cache check MUST verify range byte-parity (cached partial bytes == origin partial bytes) for at least one representative inner-table range.
- **FR-008**: Any Cloudflare-side configuration required to enable host caching (e.g. a cache rule for the host) MUST be documented with the exact settings and rationale, so it is reproducible and auditable; if applied via an automated interface, credentials MUST come from the secret boundary (not checked in).
- **FR-009**: This feature MUST NOT change which data channel the production site uses (Dropbox remains the default per Stage 20); it only makes the R2 channel cache-effective.
- **FR-010**: The applied cache policy MUST be recorded in the publish provenance so a future operator can audit what policy a given published bundle carries.

### Key Entities *(include if feature involves data)*

- **Published object**: a content-addressed file at `<sha256>/<filename>` on the R2 host, carrying a cache policy in its response metadata.
- **Cache policy**: the long-lived + immutable directive advertised on each object (and honored by the edge + browser).
- **Cache-status evidence**: the per-request indicators (cache hit/miss/bypass, age, policy) the operator check collects for full and range requests.
- **Host cache configuration**: the Cloudflare-side rule(s) that make the custom domain cache R2-origin responses (incl. range responses).

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python touched (the R2 uploader, the cache/compare check) MUST run through the repository-local `.venv/bin/python` or `uv` targeting it.
- **CA-002**: Each behavior-changing story MUST add/identify verification first: tests for the upload cache-policy behavior, and the operator cache check itself is the verification surface for the edge-cache outcome (run before/after).
- **CA-003**: Enabling the cache policy + documenting the host cache configuration is a change to published-artifact behavior; the same change MUST update the affected docs (Stage 20 plan/README `atlas_hosting` notes, the R2 storage-layout/upload contracts, and the `cloudflare_cache_unused` memory item).
- **CA-004**: Any credentials used (R2 write keys; a Cloudflare API token if the host rule is automated) MUST be referenced by env-var name only from the `.env` secret boundary and MUST NOT be committed.
- **CA-005**: No new dataset/cache/export is committed; the bundle continues to live only on R2 and gitignored local roots.
- **CA-006**: Failure paths MUST be explicit: a publish that cannot set the cache policy, and a cache check that finds responses bypassing the cache or failing range byte-parity, MUST surface a clear error/flag — never silently pass.
- **CA-007**: Cache effectiveness MUST be discovered at runtime from the actual response metadata (cache-status/age/policy on real requests), not assumed from configuration; a mismatch surfaces as an explicit failure.
- **CA-008**: The applied cache policy MUST be recorded in the publish provenance (FR-010), co-located with the upload manifest and free of absolute/user-home paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After enabling, the R2 host's cached-request rate for the immutable bundle rises from 0% to a high steady-state hit rate (target ≥ 90% of repeat requests served from the edge) as observed on the cache dashboard / the operator check.
- **SC-002**: 100% of objects written in a publish advertise the long-lived immutable cache policy; a re-publish is a no-op for already-present (content-addressed) objects and never produces a non-compliant object. The applied policy is recorded in the publish provenance.
- **SC-003**: A warm (cached) repeat request — full or range — is served from the edge (cache-status = hit) and faster than the cold/origin fetch for the same request, with byte-identical content. The verification records both the cold and warm request timings so the latency drop is an observed measurement, not an assertion.
- **SC-004**: Range (206) requests for inner tables are cache-served and byte-parity-verified by the operator check (0 mismatches).
- **SC-005**: The cross-origin range-fetch loader continues to function against the cached host (no regression in the per-table fetch pattern).
- **SC-006**: The operator cache check flags a still-bypassing host 100% of the time (no false "cache is working" pass), making the before/after auditable.
- **SC-007**: The production data channel is unchanged (still Dropbox); no site-facing behavior changes from this feature beyond faster R2-channel data loads.

## Assumptions

- **Scope is the R2 host caching + publish-side cache policy + a verification check**, not a production cutover to R2 (that remains a separate, deferred Stage 20 decision).
- **The repo-side code change** is setting the immutable cache policy on objects at publish time (in the existing R2 uploader) plus extending/adding an operator check for cache evidence; the **Cloudflare host cache rule** is a dashboard/API configuration documented as part of this change (manual by default; automated via the Cloudflare API only if a token is available in the secret boundary).
- **Keys are immutable and content-addressed** (Stage 20 guarantee), so a one-year `immutable` cache policy is safe — a changed file always lands at a new key.
- **The existing `compare-data-hosting` evidence command** (Stage 20) is the natural home to extend with cache-status / range-cache verification, rather than a brand-new tool.
- **CORS is already configured** for the R2 host (Stage 20); this feature must preserve it, not establish it.
- **"Edge-cached" success is measured from response metadata** (cache-status/age) on real requests, since the dashboard rate is a lagging aggregate.
