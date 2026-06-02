# Contract: Cloudflare host cache rule (reproducible config)

**Surface**: Cloudflare zone configuration for the `aadata.cirrusscience.org` custom domain (the R2 public base). This is **infrastructure config**, documented here so it is reproducible and auditable (FR-008). Applied manually via the dashboard by default; an optional automated path uses the Cloudflare API with a token from `.env` (`CLOUDFLARE_API_TOKEN`) — not the default.

## Why it's needed

An R2 custom domain proxies to the R2 origin but is **not edge-cached by default** → the observed 0% cache rate. A Cache Rule makes responses cache-eligible so the edge serves repeat requests (incl. ranges) from cache, honoring the immutable `Cache-Control` already on every object.

## Required rule settings

| Setting | Value | Rationale |
|---------|-------|-----------|
| Scope (matcher) | hostname = `aadata.cirrusscience.org` | only the data host; doesn't affect other zone traffic |
| Cache eligibility | **Eligible for cache** (cache everything) | R2 custom domains aren't cached otherwise |
| Edge TTL | **Respect origin** `Cache-Control` | objects already send `public, max-age=31536000, immutable`; reuse it (keys are content-addressed → safe) |
| Browser TTL | Respect origin | same immutable policy reaches browsers |
| Partial-content (Range/206) | **must remain cacheable** | the loader's per-table predicate-pushdown depends on cached ranges (FR-004) |
| CORS headers | unchanged / preserved | the cross-origin Range loader must keep working on cache-served responses (FR-005) |

## Acceptance (proven by `compare-data-hosting`, not by inspection)

| # | Rule |
|---|------|
| R1 | After the rule is applied, a warm repeat of a full GET on the host returns `cf-cache-status: HIT`. |
| R2 | A warm repeat of an inner-table **Range** request returns `cf-cache-status: HIT` with byte-parity to origin. |
| R3 | CORS (incl. the `If-None-Match` preflight) still passes on cache-served responses. |
| R4 | No change to the production data channel (Dropbox remains default — FR-009). |

## Credentials (if automated)

- `CLOUDFLARE_API_TOKEN` (zone-scoped, cache-rules edit) referenced by name from `.env` only; never logged or committed (Constitution V / CA-004). Manual application needs no repo credential.

## Provenance / docs

- The exact applied settings are recorded here and referenced from the README / Stage 20 notes; the publish manifest records the object `cache_control` (see data-model). Together they make "what policy is the bundle served under" auditable without dashboard access.
