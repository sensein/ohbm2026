# Research: Stage 1 Design Decisions

Phase 0 of `/speckit-plan`. Every NEEDS CLARIFICATION marker that the
spec or plan left unresolved gets a Decision / Rationale / Alternatives
entry below. Items already pinned by the spec (entry-point form, no
backward compat, dual-granularity resume, tiered schema-drift) are
referenced but not re-litigated.

## 1. GraphQL schema introspection request

**Decision**: Use the canonical GraphQL introspection query — the
standard `IntrospectionQuery` shape from the GraphQL spec
(`__schema { queryType, types[…] }` etc.) — sent as a normal
`POST application/json` to the existing endpoint
(`https://app.oxfordabstracts.com/v1/graphql`) with the same
`x-api-key` header `graphql_request()` already uses. Persist the raw
introspection response under
`data/inputs/abstracts_graphql_schema__<state-key>.json`.

**Rationale**: Hasura (which Oxford Abstracts runs on) exposes the
standard introspection unless explicitly disabled. The introspection
query is a public industry standard, not project-specific configuration,
so hardcoding the query body in `graphql_api.py` does NOT violate
Principle VII — the query is part of the protocol contract, not an
assumption about server state. Sending it through the existing
`graphql_request()` reuses the retry policy and auth handling.

**Alternatives considered**:
- Per-type lazy introspection (`__type(name: "X")` per type as needed).
  Rejected: produces a partial view that can hide drift in
  not-yet-asked types; we want a complete snapshot for the schema-diff
  to be meaningful.
- Use a GraphQL client library (e.g. `gql`) for introspection.
  Rejected: no new dependencies. The stdlib `urllib` call is sufficient
  and matches the rest of the file.

## 2. Pagination boundary for resumable fetch

**Decision**: Keep the current "fetch all IDs once, then fetch
content in chunks of N (default 50)" pattern from `assets.build_database`.
For checkpoint purposes, the **batch of submission IDs** IS the
"page" cursor; the **per-abstract** completion within a batch is the
per-record marker. `FR-018`'s "page-level cursor" maps to the index
of the last fully completed batch (equivalently: the set of
submission IDs whose corpus row AND figure-asset downloads are done).

**Rationale**: The existing pattern is already deterministic and the
chunking boundary is operator-visible (batch_size CLI arg). Switching
to Hasura cursor pagination (limit/offset on submissions) would
introduce a second pagination axis and a new failure mode (ID order
across pages). The fixed-ID-list + batched-content approach has the
property that the cursor (the ID list) is computed once at the start
and never changes during the run — which makes resume deterministic.

**Alternatives considered**:
- True GraphQL cursor pagination (limit/offset/`order_by` on
  submissions). Rejected: changes upstream interaction shape; introduces
  ordering coupling; current pattern is already correct and tested.
- Per-ID checkpoint (no batches at all, one request per abstract).
  Rejected: ≥ 50× more upstream requests, no test win, breaks the
  current batch-friendly Oxford Abstracts response shape.

## 3. Resume checkpoint file layout and write semantics

**Decision**: A single JSON file at
`data/cache/fetch_abstracts/checkpoint__<state-key>.json`. Writes are
atomic via `tempfile.NamedTemporaryFile(dir=…, delete=False)` →
`os.replace()`. Checkpoint is updated at TWO trigger points:

1. **After each fully completed batch** — page cursor (`last_completed_batch_index`,
   `completed_submission_ids` set) is moved forward; the in-flight
   per-record map is cleared.
2. **After each completed abstract within the in-flight batch** —
   per-record marker flips to `done`; this is the higher-frequency write.

The state-key in the checkpoint filename is the same key under
which the corpus snapshot will eventually be written, so a corpus
snapshot and its checkpoint always live in matched pairs.

**Rationale**: Atomic rename is the standard idiom for crash-safe
single-file updates on POSIX (`os.replace` is atomic on the same
filesystem). One file per fetch run keeps the resume decision simple
(open the file, read it, decide). Two trigger points let `FR-018`'s
"per-record within in-flight page" guarantee hold without writing
megabytes per record.

**Alternatives considered**:
- SQLite checkpoint. Rejected: new dependency-style complexity for
  a single-writer, low-rate use case.
- Append-only journal of events. Rejected: more durable but requires
  a replay step on resume that the JSON model avoids.
- Per-batch separate files. Rejected: complicates "is this checkpoint
  trustworthy?" decision; one JSON answers it directly.

## 4. Soft-contract field discovery (which downstream-consumed fields)

**Decision**: Each downstream module that reads fields from
`data/primary/abstracts.json` declares them in a module-level
constant `CONSUMED_ABSTRACT_FIELDS: frozenset[str]` containing
slash-separated field paths
(e.g. `responses/question/question_name`, `title/value`). The
new `schema_diff.collect_soft_contract_fields()` function imports
each `src/ohbm2026/*.py` module that participates and unions
the declared sets.

**Rationale**: An explicit per-module declaration is more
maintainable than static AST inspection and lets the constitution-
check lint (or a new lint) verify the declarations match
actual reads if drift becomes a problem later. The set is still
"derived at runtime" per CA-007 because it is collected by
importing the live modules, not from a separate file.

**Alternatives considered**:
- Static AST inspection of `abstract["field"]` accesses. Rejected:
  brittle (misses `.get()`, dynamic key construction, helper
  functions); high false-negative rate.
- A central `CONSUMER_REGISTRY` dict in `schema_diff.py`. Rejected:
  centralization invites silent drift from the modules that own
  the consumption (`schema_diff.py` gets out of date when a
  downstream module starts reading a new field).
- No soft-contract tier at all (everything HARD). Rejected by
  Clarifications session 2026-05-12 (Q2 → tiered).

## 5. Schema-diff algorithm

**Decision**: Flatten each introspection result into a normalized
view: a `dict[(type_name, field_name), TypeInfo]` where
`TypeInfo` is a `dataclass` with `wrapping_kinds` (NON_NULL/LIST
stack), `named_type`, and `args_signature`. Compute the symmetric
set difference between the previous and current views; for
overlapping keys, compare `TypeInfo` equality. Classify each
delta against:
- **HARD set** — fields the live fetch query body requests; computed
  by parsing `ABSTRACT_IDS_QUERY` and `ABSTRACT_CONTENTS_QUERY`
  using the stdlib `graphql.parse` if available, otherwise a
  small recursive regex parser. (Stdlib does NOT have a GraphQL
  parser; we'll implement a minimal AST walker in
  `schema_diff.py` that handles the limited form our queries use:
  named fields, nested selection sets, no inline fragments.)
- **SOFT set** — `collect_soft_contract_fields()` result (see §4).
- **INFORMATIONAL** — everything else.

The output is a list of `SchemaDiffEntry` records, each tagged
with one of the three tier labels.

**Rationale**: Flattening to a (type, field) view keeps the diff
implementation simple and deterministic. The minimal query parser
is acceptable because our queries are small (~10 fields each)
and we control them; a future round can swap in a proper GraphQL
parser if the queries grow.

**Alternatives considered**:
- Pull in `graphql-core` library. Rejected: new dependency, not
  needed for the limited query shape we have.
- Compare introspection JSONs directly with `deepdiff`. Rejected:
  diff is too noisy at the JSON level — same logical field can be
  serialized in many JSON shapes; semantic flattening is cleaner.

## 6. State-key derivation for the fetch run

**Decision**: The state-key for a fetch run is
`build_state_key(dependency_basis=...)` where `dependency_basis`
captures: `{ "endpoint": <url>, "ids_query": <abstract_ids_query
text>, "content_query": <abstract_contents_query text>,
"introspection_query": <introspection query text>, "batch_size":
<int>, "env_var": "OHBM2026_API", "schema_version":
"fetch.v1" }`. Same input state → same state-key → checkpoint
and snapshot file names match across runs.

**Rationale**: The state-key changes whenever any input-shape
choice changes (query text, batch size, schema version). That is
exactly what we want — a behavior-affecting change forces a fresh
artifact name so old snapshots don't get silently overwritten or
silently reused.

**Alternatives considered**:
- State-key based on UTC date. Rejected: same-day reruns would
  share the key even when behavior changed; cross-day runs would
  differ even when nothing changed.
- State-key based on output digest (the current
  `assets.build_database` behavior for input snapshots).
  Rejected: cannot be computed before the run; doesn't support
  pre-run checkpoint lookup.

## 7. Entry-point CLI naming and shape

**Decision**: One canonical surface in two equivalent forms:

- **`ohbmcli fetch-abstracts`** — primary subcommand in
  `src/ohbm2026/cli.py`. Replaces `ohbmcli ingest` (which is
  REMOVED per the Clarifications session).
- **`scripts/run_fetch_abstracts.py`** — thin wrapper that imports
  `ohbm2026.fetch_stage.main` and forwards `sys.argv[1:]`.
  Exists so the README's Stage 1 section can show a single
  copy-pasteable invocation line that survives moves of the
  `ohbmcli` entry point.

Both forms route through `ohbm2026.fetch_stage.main(argv)` which
is the testable orchestration entry.

**Rationale**: The user's brief asked for "scripts that can
re-execute different stages". Keeping the heavy lift in the
library (`fetch_stage.py`) and exposing it both ways gives the
operator a stable script path for documentation AND a stable
library entry for tests/automation.

**Alternatives considered**:
- Only `ohbmcli fetch-abstracts`. Rejected: violates the user's
  "scripts" requirement.
- Only `scripts/run_fetch_abstracts.py`. Rejected: breaks the
  existing CLI pattern; `ohbmcli` is the canonical project
  interface per the constitution and existing docs.
- Different names for the two surfaces. Rejected: would split the
  docs.

## 8. Test fixture strategy for the live GraphQL endpoint

**Decision**: All Stage 1 tests run hermetically. Network access
is mocked by patching `ohbm2026.graphql_api.urlopen` (or the
`urlopen_with_retries` wrapper). Three fixture layers, all
synthetic — no live recordings:

- **Schema fixture**: a tiny synthetic introspection response
  containing just the types the fetch query touches plus a few
  extra types (to exercise INFORMATIONAL classification).
- **Abstract fixture**: a small synthetic list of submission IDs
  + corresponding content payloads, sized so the test
  configuration produces 2–3 batches at the test `batch_size`.
- **Failure fixtures**: HTTP 5xx, HTTP 401, timeout, partial
  response, schema-drift response (one field renamed),
  semantically empty corpus.

No VCR / cassette dependency.

**Rationale**: Hermetic + synthetic fixtures are deterministic,
fast, and don't require an API key in CI. Recordings (VCR-style)
would couple test results to a moment-in-time upstream and
require a refresh process the constitution would have to police.

**Alternatives considered**:
- Live integration test against the real endpoint, marked slow.
  Rejected: needs a secret in CI; flaky; constitution says no
  live external dependencies in the default test path.
- VCR cassettes. Rejected as above; adds dependency.

## 9. Failure surface for figure-asset download

**Decision**: Figure download failures are recorded per-asset
(`AssetDownload.error`) and the in-flight abstract's
checkpoint marker flips to `failed-retryable` until the next
run succeeds. The abstract is NOT counted as `done` for
checkpoint purposes until all linked figures resolve to either
`downloaded=True` or `error in {non-image, invalid URL,
permanent 4xx}` — i.e. terminal states.

If any abstract ends a run in `failed-retryable` state, the
fetch exits 0 only if ALL such failures are documented in the
provenance as transient and the operator has consented (via
default policy, which is "fetch completes with non-fatal
warnings"). If figure-related failures cross a configurable
threshold (default: ≥ 5% of attempted downloads in a single
run), the fetch exits non-zero — failed loudly per Principle VI.

**Rationale**: Figure-asset reliability is genuinely upstream-of-
us (third-party hosting). Treating every figure 404 as fatal
would block fetches indefinitely. Treating them all as silent
is the silent-fallback Principle VI prohibits. The threshold
makes the noise/signal tradeoff explicit and tunable.

**Alternatives considered**:
- Any figure failure → fetch fails. Rejected: too brittle for
  third-party-hosted assets.
- All figure failures silent. Rejected: violates Principle VI.

## 10. Provenance record path-safety

**Decision**: Every path written into the provenance record is
project-relative (relative to `pathlib.Path.cwd()` at write
time, which is the repo root when invoked through `ohbmcli` or
the `scripts/` wrapper). The orchestrator asserts each candidate
path is not absolute and does not start with the user's
home-directory prefix (`os.path.expanduser("~")`); violations
raise `ProvenanceError` per Principle VIII / CA-008.

**Rationale**: Absolute or `~`-prefixed paths make the provenance
bundle unportable. Asserting at write time is cheaper than
sanitizing on read.

**Alternatives considered**:
- Sanitize on read. Rejected: too late; bad data already on disk.
- Allow absolute paths. Rejected by CA-008.
