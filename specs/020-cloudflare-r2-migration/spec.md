# Feature Specification: Cloudflare R2 Migration & Content-Hashed Data Store

**Feature Branch**: `020-cloudflare-r2-migration`  
**Created**: 2026-05-31  
**Status**: Draft  
**Input**: User description: "we are going to copy the data bundle to cloudflare r2. create a new key and compare to dropbox. we are also going to plan for a system on the s3 bucket that stores content-hashed data, so that we can upload different data for future updates to the atlas."

## Context (current state)

The static Atlas site fetches its data at runtime as a small set of standalone
parquet files served over HTTPS — today from Dropbox direct-download links.
The pieces in play (verified against the repo, not assumed):

- The parquet artifacts that make up "the data bundle" are produced locally by
  `ohbmcli build-atlas-package`: `ohbm2026.parquet`, `neuroscape.parquet`,
  `atlas.parquet`, and the optional `neuroscape_vectors.parquet` sidecar.
- URLs are not hardcoded in the site. One GitHub Actions variable,
  `OHBM2026_UI_DATA_PACKAGE_URLS`, holds a **keyed JSON registry of channels**;
  each channel maps `ohbm2026` / `neuroscape` / `atlas` / `neuroscape_vectors`
  to `{url, sha256}`. A per-branch committed file `site/data-channel.json`
  (`{"key": "<channel>"}`) selects which channel that branch's preview,
  sandbox, and prod builds resolve.
- `.github/scripts/resolve-data-channel.sh` reads the channel key, looks it up
  in the registry, and emits `VITE_DATA_PACKAGE_URL_OHBM2026` / `_NEUROSCAPE` /
  `_ATLAS` / `_NEUROSCAPE_VECTORS` into the build environment.
- The browser loader fetches each parquet by URL and — critically — issues
  **HTTP Range requests** to read a single inner table out of an envelope
  parquet (predicate pushdown / `asyncBufferFromUrl`) without downloading the
  whole file (e.g. range-fetching the cluster legend and backdrop from a
  sibling rather than a full GET). The only host-specific URL handling is a
  Dropbox rewrite (`www.dropbox.com` → `dl.dropboxusercontent.com`, strip
  `dl=0`); non-Dropbox HTTPS URLs pass through unchanged.
- Each parquet embeds a `build_info` manifest carrying a 12-hex `state_key`
  (sha256 prefix of inputs), `code_revision`, `command_line`, build timestamps,
  and — for `atlas.parquet` — `sibling_state_keys` for cross-parquet drift
  detection.

This feature changes **where** those bytes are served from (adding Cloudflare
R2, an S3-compatible object store, as a new channel) and **how future versions
are published** (a content-hashed, immutable object layout), without changing
the registry mechanism or the site's fetch logic.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The live site serves the current bundle from R2 (Priority: P1)

An operator publishes the exact bundle currently on Dropbox to Cloudflare R2,
registers a new R2-backed channel in the registry, points a branch's
`site/data-channel.json` at it, and the site loads and renders identically —
from the full-file initial GET through the per-table Range fetches on every
surface (`/ohbm2026/`, `/neuroscape/`, atlas-root).

**Why this priority**: This is the migration's reason to exist and the minimum
viable proof. If the site cannot load correctly from R2 — public read, CORS to
the gh-pages origin, and Range support all working — nothing else matters. It
is also the smallest end-to-end slice: one channel, the existing files.

**Independent Test**: Publish the current artifacts to R2, add an R2 channel,
build a preview against it, and confirm all three surfaces render with no
console fetch errors and no missing tables — including a surface (atlas-root)
that depends on a sibling Range fetch.

**Acceptance Scenarios**:

1. **Given** the current parquet artifacts exist in R2 under a new channel,
   **When** a build resolves that channel and the browser loads each surface,
   **Then** every surface renders with the same data as the Dropbox channel and
   no fetch/CORS/Range errors appear.
2. **Given** a surface that range-fetches one inner table from a sibling
   parquet, **When** the browser requests that table from the R2 URL, **Then**
   the server returns a `206 Partial Content` for the byte range and only that
   table's bytes cross the network (not the whole file).
3. **Given** an R2 (non-Dropbox) HTTPS URL in the registry, **When** the loader
   resolves it, **Then** it is used verbatim (no Dropbox rewrite is applied and
   the URL is not mangled).

---

### User Story 2 - Publish a new atlas version without overwriting the old (Priority: P2)

When the atlas is rebuilt (new corpus, new embeddings, new layout), an operator
runs a single local command that uploads the freshly built package to R2 under
**content-addressed, immutable object keys**. Identical files are not
re-uploaded; changed files land at new keys; no prior version's objects are
modified or deleted. The command emits a ready-to-register channel entry so the
new version can be wired into a branch without touching site code.

**Why this priority**: This is the forward-looking "system" the user asked to
plan for and build. It makes future atlas updates a repeatable upload rather
than a manual, overwrite-prone copy, and guarantees that any URL ever published
keeps resolving (permalinks, cached previews, in-flight branches).

**Independent Test**: Build a package, upload it, re-run the upload unchanged
(expect zero bytes re-uploaded), then change one artifact and upload again
(expect only that artifact at a new key; all prior objects untouched and still
fetchable).

**Acceptance Scenarios**:

1. **Given** a locally built atlas package and configured R2 credentials,
   **When** the operator runs the upload command, **Then** each artifact is
   stored at a key derived from its content hash, a machine-readable upload
   manifest is recorded, and a registry channel entry (logical name → public
   URL per artifact) is emitted.
2. **Given** an upload that already happened, **When** the operator re-runs it
   against the same build, **Then** every artifact is detected as already
   present and skipped (idempotent; zero re-upload), and the run reports the
   skips explicitly rather than silently.
3. **Given** a rebuilt package where one artifact's bytes changed, **When** the
   operator uploads it, **Then** the changed artifact is stored at a new
   content-addressed key, the unchanged artifacts are skipped, and every object
   from the previous version remains present and fetchable at its original URL.
4. **Given** R2 credentials are missing or invalid, **When** the operator runs
   the upload, **Then** the command fails with a precise error before any
   partial upload and writes no manifest.

---

### User Story 3 - Compare R2 against Dropbox (Priority: P3)

Before any production cutover, an operator generates a comparison that proves
R2 is a faithful, capable substitute for Dropbox: byte-identical content,
working CORS to the gh-pages origin, working Range requests, and reachable
public URLs — recorded as a machine-readable report that becomes the evidence
for the (separate, deferred) cutover decision.

**Why this priority**: The user explicitly asked to "compare to Dropbox." The
comparison is evidence, not a blocker for US1/US2, so it is lower priority — but
it is what makes a later production cutover a confident, auditable decision
rather than a leap.

**Independent Test**: Run the comparison against both the Dropbox channel and
the R2 channel for every artifact and confirm the report records a byte-parity
verdict, a CORS verdict, and a Range-support verdict for each, with any failure
surfaced as a failure (non-zero / explicit), not a silent omission.

**Acceptance Scenarios**:

1. **Given** the same logical artifact on Dropbox and on R2, **When** the
   comparison runs, **Then** the report records whether their content hashes
   match (byte-parity) per artifact.
2. **Given** the R2 public URLs, **When** the comparison probes them, **Then**
   the report records, per artifact, whether a cross-origin Range request from
   the production site origin succeeds (status, returned range, CORS headers).
3. **Given** any probe that fails (mismatch, CORS rejection, no Range support,
   unreachable URL), **When** the comparison completes, **Then** the failure is
   reported explicitly and the overall result is non-passing — never a quietly
   incomplete report read as success.

---

### Edge Cases

- **Same content, re-uploaded**: a content-addressed key already holds an object
  whose hash equals the local file → skip (dedup), log the skip; never a silent
  no-op that looks like a fresh upload.
- **Hash-addressed key holds unexpected bytes**: an object exists at a
  content-addressed key but its size/recorded hash does not match what that key
  asserts (corruption / key scheme violation) → fail loudly; do not overwrite.
- **Interrupted upload**: a partial run is re-runnable; already-stored objects
  are detected and skipped so the upload resumes rather than restarts.
- **Large sidecar**: `neuroscape_vectors.parquet` is large (hundreds of MB); the
  upload path must handle large objects (e.g. multipart) without truncation.
- **CORS not configured on the bucket**: the site's cross-origin fetch fails;
  the US3 comparison MUST detect and report this rather than the failure first
  surfacing as a broken site in production.
- **Range not honored**: if the endpoint ignores `Range` and returns the full
  body / `200`, per-table reads degrade to full-file downloads; the comparison
  MUST detect and flag this.
- **Registry channel partially populated**: a channel missing a required
  artifact URL aborts the build today (`resolve-data-channel.sh` fails loudly);
  the emitted R2 channel entry MUST include every required artifact so it does
  not regress that guarantee.
- **Superseded versions**: old content-addressed objects accumulate; pruning is
  a deliberate, manual ops action — automatic deletion is explicitly out of
  scope to preserve the immutability guarantee.

## Requirements *(mandatory)*

### Functional Requirements

**Hosting on R2 (US1)**

- **FR-001**: The system MUST publish the four data-bundle artifacts
  (`ohbm2026.parquet`, `neuroscape.parquet`, `atlas.parquet`, and the optional
  `neuroscape_vectors.parquet`) to a Cloudflare R2 bucket such that each is
  fetchable over public, unauthenticated HTTPS.
- **FR-002**: R2-served artifacts MUST support HTTP Range requests (returning
  `206 Partial Content` for a requested byte range) so the browser can read a
  single inner table without downloading the whole file, preserving the current
  Dropbox behavior.
- **FR-003**: R2-served artifacts MUST be readable cross-origin (CORS) from the
  production site origin(s) and from PR-preview origins, for both `GET` and
  ranged `GET`.
- **FR-004**: The system MUST register a new R2-backed **channel** in the
  existing `OHBM2026_UI_DATA_PACKAGE_URLS` registry whose subkeys
  (`ohbm2026` / `neuroscape` / `atlas` / `neuroscape_vectors`) point at the R2
  public URLs, so a branch can select it via `site/data-channel.json` with no
  change to the registry mechanism or the resolver script.
- **FR-005**: The site's runtime fetch and URL-resolution logic MUST require no
  structural change to consume R2 URLs; R2 (non-Dropbox) URLs MUST pass through
  the loader's URL handling verbatim (the existing Dropbox-only rewrite MUST NOT
  alter them).

**Content-hashed upload system (US2)**

- **FR-006**: The system MUST provide a local `ohbmcli` subcommand that uploads
  a locally built atlas package's artifacts to R2.
- **FR-007**: Each artifact MUST be stored at an R2 object key **derived from
  the content hash (sha256) of the exact file bytes the site will fetch**, such
  that identical content always maps to the same key and differing content never
  maps to the same key.
- **FR-008**: The upload MUST be **immutable and non-destructive**: it MUST NOT
  overwrite, mutate, or delete any existing object. Publishing a new version
  MUST only add new objects, leaving every previously published URL resolvable.
- **FR-009**: The upload MUST be **idempotent / resumable**: before uploading an
  artifact it MUST check whether the content-addressed object already exists and
  skip it if so, reporting the skip explicitly; a re-run of an unchanged package
  MUST transfer zero artifact bytes.
- **FR-010**: The upload MUST discover, at runtime, which artifacts the built
  package actually contains rather than assuming a fixed set, and MUST surface a
  precise error if a required artifact is missing.
- **FR-011**: The upload MUST emit a ready-to-register channel entry (logical
  artifact name → public R2 URL) suitable for merging into the
  `OHBM2026_UI_DATA_PACKAGE_URLS` registry variable, so wiring a new version
  into a branch requires no code change.
- **FR-012**: The upload MUST write a machine-readable **upload manifest**
  recording, per artifact: content hash, byte size, public URL/object key, and
  the source build's `state_key`; plus run-level provenance (code revision,
  command line, upload timestamp). The manifest MUST contain no absolute or
  user-home paths.
- **FR-013**: Multiple published versions MUST coexist; the layout MUST let an
  operator publish update N+1 while every artifact of versions 1..N remains
  intact and individually fetchable.

**Comparison & validation (US3)**

- **FR-014**: The system MUST produce a machine-readable comparison report
  covering, per artifact, the Dropbox-served and R2-served copies: a byte-parity
  verdict (content-hash match), a CORS verdict (cross-origin ranged GET from the
  production origin), and a Range-support verdict (`206` with the correct byte
  range).
- **FR-015**: Any comparison probe that fails (hash mismatch, CORS rejection,
  missing Range support, unreachable URL) MUST be reported explicitly and MUST
  make the overall comparison non-passing; the report MUST NOT silently omit a
  probe it could not complete.

**Error handling (cross-cutting)**

- **FR-016**: Missing or invalid R2 credentials, network/upload failures, and
  content-hash mismatches MUST surface as precise, typed errors that name what
  failed; the system MUST NOT partially publish, silently skip, or fall back to
  stale data on failure.

### Key Entities *(include if feature involves data)*

- **Data bundle / atlas package**: the coherent set of parquet artifacts the
  site consumes (`ohbm2026`, `neuroscape`, `atlas`, optional
  `neuroscape_vectors`), produced by one `build-atlas-package` run; identified
  by build `state_key`s already embedded in each parquet's `build_info`.
- **Content-addressed object**: a single artifact stored in R2 at a key derived
  from its content hash; immutable once written; the unit of dedup and
  versioning.
- **Channel registry entry**: a named key inside `OHBM2026_UI_DATA_PACKAGE_URLS`
  mapping each logical artifact name to a public URL; what a branch selects via
  `site/data-channel.json`.
- **Upload manifest**: machine-readable provenance for one upload run — per
  artifact content hash, size, key/URL, source `state_key`; plus code revision,
  command line, and timestamp. Co-located with the build output.
- **Comparison report**: machine-readable evidence of Dropbox↔R2 parity and R2
  capability (byte-parity, CORS, Range) per artifact; the basis for a later
  cutover decision.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python for the upload/comparison CLI and its tests MUST run
  through `.venv/bin/python` (or `uv` targeting it). Site-side checks run via
  the existing `vitest run` setup.
- **CA-002**: Tests precede implementation for each behavior: content-hash key
  derivation; existence-check / skip-if-present dedup; non-destructive,
  resumable upload; required-artifact discovery and missing-artifact error;
  upload-manifest schema/no-absolute-paths; channel-entry emission; comparison
  verdicts (parity / CORS / Range) and the fail-loud aggregation. Site: a test
  asserting a non-Dropbox HTTPS URL passes through URL resolution unchanged.
- **CA-003**: Docs updated in the same change: `README.md` (new upload/compare
  subcommands + the R2 publish workflow and required env vars); `CLAUDE.md`
  (data-hosting note: R2 channel alongside Dropbox, new artifact/manifest paths,
  the R2 env-var names); and the explanatory comments in
  `.github/scripts/resolve-data-channel.sh` and `site/data-channel.json` to note
  the registry may now hold R2 URLs (no resolver code change).
- **CA-004**: R2 access uses S3-compatible credentials kept in `.env`
  (account/endpoint, access key id, secret access key, bucket, public base URL).
  The spec MUST NOT require checked-in tokens; credentials MUST NOT be echoed
  into logs, manifests, reports, or the emitted channel entry. Registering the
  channel into the GitHub variable is an operator action using the emitted
  snippet (e.g. `gh variable set`); the upload CLI does not need GitHub
  credentials.
- **CA-005**: Local build copies, upload manifests, and comparison reports land
  only in gitignored paths (under `data/outputs/…` and `data/provenance/…`); no
  parquet, manifest, or report is tracked in the repository. The committed
  surface is limited to source, the (URL-free) registry mechanism, and docs.
- **CA-006**: Every external-call failure (auth, network, upload, HEAD/probe),
  hash mismatch, and missing-artifact case is re-raised as a precise typed error
  with context (artifact, key, what was attempted); dedup skips are logged, not
  silent; no bare `except`, no silent fallback, no bypassed verification.
- **CA-007**: The bucket's contents and the package's artifact set are
  discovered at runtime (object-existence HEAD before upload; enumerate the
  built package's actual artifacts; probe the live endpoint for Range/CORS)
  rather than matched against a hardcoded list; mismatches surface as errors.
- **CA-008**: The published data bundle is a downstream-consumer-facing artifact;
  the **upload manifest** is its machine-readable provenance (inputs via source
  `state_key`s, content hashes, sizes, keys/URLs, code revision, command line,
  upload timestamp), co-located with the build output and free of absolute/
  user-home paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three site surfaces (`/ohbm2026/`, `/neuroscape/`,
  atlas-root) render with complete data and zero fetch/CORS/Range errors when
  built against the R2 channel — including at least one surface that depends on
  a sibling Range fetch.
- **SC-002**: For a representative inner-table read, the bytes transferred from
  the R2 URL are a small fraction of the full file (same order of magnitude as
  the Dropbox baseline — i.e. a single-table Range fetch, not a full download).
- **SC-003**: Re-running the upload on an unchanged build transfers zero
  artifact bytes (100% of artifacts detected as already present and skipped).
- **SC-004**: After publishing a changed build, 100% of the previous version's
  artifact URLs still resolve to byte-identical content, and only the changed
  artifact(s) occupy new keys.
- **SC-005**: The comparison report shows a byte-parity match (equal content
  hash) for 100% of artifacts present on both Dropbox and R2.
- **SC-006**: An operator can publish a new data version and wire it into a
  branch using only the documented CLI command plus a registry edit — with no
  changes to site code or the resolver script.
- **SC-007**: Every defined failure path (missing creds, hash mismatch, missing
  artifact, CORS/Range probe failure) produces an explicit, descriptive error or
  non-passing verdict; none is silently swallowed.

## Assumptions

- The R2 bucket is exposed for public, unauthenticated HTTPS reads (via R2's
  managed public URL or a Cloudflare custom domain) with CORS configured to
  allow the production and PR-preview origins and with Range honored. The exact
  domain is an operator configuration detail and does not affect the
  requirements above (the site treats the URL as opaque).
- The existing channel-registry + `site/data-channel.json` + resolver mechanism
  is reused unchanged; R2 simply supplies different URLs in a new channel.
- "Content-hashed" means keys derived from the sha256 of the exact bytes the
  browser fetches; this provides both immutability and dedup.
- The atlas package is built locally end-to-end (per the CLAUDE.md workflow);
  the upload CLI runs against that local build output. R2 credentials live in
  `.env`.
- Registering the emitted channel entry into the GitHub Actions variable is an
  operator step (the CLI emits the snippet; it does not mutate GitHub state).
- The site loader requires no structural change because it already treats data
  URLs as opaque and applies host-specific handling only to Dropbox URLs.

## Out of Scope

- **Production cutover / Dropbox retirement**: switching the production-default
  channel to R2 and decommissioning Dropbox is a separate, deferred decision
  informed by the US3 comparison.
- **CI-driven uploads**: uploads run from a local `ohbmcli` command; automating
  them in a GitHub Actions workflow is not part of this feature.
- **Garbage collection** of superseded content-addressed objects (pruning old
  versions is a deliberate manual ops action; automatic deletion would violate
  the immutability guarantee).
- **Changing the atlas package build** (`build-atlas-package`): this feature
  consumes its output unchanged; it does not alter what is built.
