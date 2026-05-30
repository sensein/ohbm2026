# Feature Specification: NeuroScape Semantic Search

**Feature Branch**: `019-neuroscape-semantic-search`
**Created**: 2026-05-26
**Status**: Draft
**Input**: User description: "let's do semantic search"

## Clarifications

### Session 2026-05-27

- Q: Should this spec add a cross-conference search surface on atlas-root (`/`) spanning OHBM 2026 + NeuroScape? → A: Yes, as a P2 user story. Result rows reuse the existing OHBM-vs-NeuroScape source identification already shipped in atlas-root's cross-pointers + scatter colouring — no new badge UI is needed. Existing facet filters on atlas-root do NOT change. Semantic search contributes ONLY a distance-based re-ordering of results.

- Q: What ranking strategy should the semantic ranker use, given the cluster + k=20 KNN graph already in `neuroscape.parquet`? → A: **Cluster-routed seeding + KNN-graph expansion** for the NeuroScape corpus, to handle the "query falls between clusters" case that pure cluster routing misses. The pipeline is: (1) embed query, (2) score query against the ~50 cluster centroids and pick the **single closest centroid**, (3) brute-force cosine within that cluster only → **top-3 matches**, (4) walk the existing k=20 KNN graph outward from those top-3 to collect candidates spanning adjacent clusters, (5) re-rank the full candidate set by cosine to query. For the small OHBM 2026 corpus (~3.2k abstracts), brute-force cosine is trivially fast and cluster routing is skipped. Atlas-root cross-conference search runs both pipelines in parallel and merges by cosine score.

- Q: Where do the per-article NeuroScape vectors live, and how does the browser fetch only the rows for a given cluster? → A: **Sibling `neuroscape_vectors.parquet`** loaded lazily via hyparquet's `asyncBufferFromUrl` + HTTP range requests. The file is sorted by `cluster_id` (already a column on the main parquet's articles table), so parquet row-group min/max statistics let the browser predicate-pushdown to `cluster_id == X` and fetch only the byte ranges containing that cluster's rows. NO per-cluster sidecar shard files; NO refactor of the existing eager-load of `neuroscape.parquet`. The vectors parquet carries two columns: `pubmed_id INT64`, `minilm_vector FIXED_LEN_BYTE_ARRAY(384)` (INT8 quantised).

- Q: Should the spec drop per-article vectors entirely and use centroids + KNN only? → A: **No, keep per-article vectors.** The size win (~50 MB → ~80 KB) was tempting, but the no-lexical-overlap case is exactly the use case US1 motivates ("find articles by meaning, not keyword"). Centroids + KNN alone degrade ranking quality precisely on the queries semantic search is meant to help. Per-article vectors stay (delivered via the sibling parquet decided above).

- Q: Should the search syntax + UX be unified across all three surfaces, reversing the prior "slim-by-design" stance for `/neuroscape/` + atlas-root? → A: **Yes.** All three surfaces (`/ohbm2026/`, `/neuroscape/`, atlas-root) reuse the OHBM `SearchBar` operator set verbatim: implicit-AND multi-word, `"exact phrase"`, `-foo` / `-"exact phrase"` negation, `word OR word` alternation, and the `id:N` operator. The `id:N` operator on atlas-root matches **both** corpora's id columns in parallel — bare `id:` queries either `poster_id` (OHBM) or `pubmed_id` (NeuroScape); the result list disambiguates via the existing source pill (no new badge UX, no new operator names like `pmid:` / `poster:`). Each surface's `SearchBar` help dropdown lists the same operator set.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find neuroscience articles by meaning, not keyword (Priority: P1)

A researcher visiting `/neuroscape/` wants to discover articles related to a
concept (e.g. "default mode network rumination") even when the article titles
don't use those exact words. Today the subsite ships **only typo-tolerant
lexical search over the ~461k article titles**, so a query like *"resting
state introspection"* returns nothing if no title contains both substrings —
even though dozens of titles about default-mode-network rumination, mind-
wandering, and self-referential thought are semantically relevant.

The OHBM 2026 subsite (`/ohbm2026/`) already has this behaviour: a `✨ Semantic`
toggle expands the result list with cards surfaced by meaning-similarity, each
flagged with a `✨` badge so the user can distinguish "matched my words" from
"matched my intent". The same affordance is the most-requested gap on
`/neuroscape/`.

**Why this priority**: This is the single largest discoverability gap on the
new NeuroScape subsite. Spec 015 / FR-018 explicitly committed to title-only
lexical search as the v1 release-blocker, with the matching semantic phase
deferred to a sibling stage. With Stage 15 shipped, this is that sibling
stage.

**Independent Test**: Open `/neuroscape/`, type a 3-5 word concept phrase that
does NOT appear verbatim in any article title (e.g. *"sleep memory
consolidation hippocampus"*), enable the `✨ Semantic` toggle, and observe at
least one semantically related article surface in the result list with a `✨`
badge. Toggle off → the result list reverts to the lexical-only set.

**Acceptance Scenarios**:

1. **Given** the user is on `/neuroscape/` and types a multi-word concept
   phrase that has zero substring matches in any title, **When** they enable
   `✨ Semantic`, **Then** the result list shows semantically related articles
   each marked with a `✨` badge, ranked by semantic similarity.

2. **Given** a query string that has BOTH lexical matches AND semantically
   related non-lexical matches, **When** semantic search is enabled, **Then**
   the result list shows lexical hits first (unbadged) followed by semantic-
   only hits (badged), in a single ranked list.

3. **Given** the user toggles `✨ Semantic` off, **When** the result list
   re-renders, **Then** all `✨`-badged rows disappear and only the lexical
   set remains, preserving scroll position.

4. **Given** the user clicks a `✨`-badged article row, **When** the detail
   panel opens, **Then** it loads the full abstract from PubMed (via the
   existing E-utilities path established in Stage 15) — there is no new
   metadata required to make a semantic-only hit clickable.

---

### User Story 2 - Visual feedback while the semantic index loads (Priority: P2)

With the cluster-routed pipeline + sibling-parquet predicate pushdown
(FR-021), the first FULL semantic query against the 461k-article corpus
issues 1-3 HTTP range requests for cluster-bounded vector row groups
(typically ~5–20 MB cold-cache total). That's a non-trivial wait on
slower connections, and the user MUST get a clear "loading semantic
search…" affordance so the toggle / submitted query does not appear
broken or frozen. The OHBM 2026 corpus's semantic index is small
(~1 MB, ~3.2k abstracts brute-force) and incurs no comparable wait.

**Why this priority**: Without it, the feature feels broken on first use —
the user enables the toggle, nothing visibly changes for several seconds, and
they conclude semantic search "doesn't work" or "didn't load". Strong loading
feedback is the difference between a usable feature and one users disable.

**Independent Test**: Clear browser storage, navigate to `/neuroscape/`,
enable `✨ Semantic` for the first time, observe a visible loading state on
the toggle (or near it) while the semantic vectors download and the worker
initialises, and confirm the toggle reaches a stable "ready" state before
the user is allowed to expect semantic hits in the result list.

**Acceptance Scenarios**:

1. **Given** the user enables `✨ Semantic` for the first time in this
   session, **When** the semantic vectors are still downloading, **Then** the
   toggle shows a loading indicator and the result list does not silently
   appear stale.

2. **Given** the semantic vectors fail to download (network error,
   429-rate-limit on the host, etc.), **When** the failure is detected,
   **Then** the toggle returns to its off state and a visible message
   explains the failure with a `Retry` affordance — the user is never left
   with a toggle stuck in a "loading forever" state.

3. **Given** the user has previously loaded the semantic vectors in this
   browser, **When** they re-enable `✨ Semantic` in a later session, **Then**
   the toggle reaches the ready state in under 2 seconds without re-
   downloading (a cache hit on the asset).

---

### User Story 3 - Search-bar parity across all three surfaces (Priority: P3)

The existing OHBM 2026 `<SearchBar>` supports a compact syntax:
implicit-AND multi-word, `"exact phrase"`, `-foo` / `-"exact phrase"`
negation, `word OR word` alternation, and the `id:N` operator (Stage 14).
All three surfaces — `/ohbm2026/`, `/neuroscape/`, atlas-root — MUST
reuse this syntax verbatim. The semantic `✨` toggle joins the same
SearchBar component. Per spec Clarifications session 2026-05-27 Q5, this
reverses the earlier "slim-by-design" stance for `/neuroscape/`; users
learn one syntax + one operator set + one toggle position regardless of
which subsite they're on.

**Why this priority**: Once US1 + US4 ship the same ranking machinery on
two new surfaces, syntax divergence between subsites becomes the dominant
remaining source of "this feels different" friction. Promoting parity to
its own story makes the SearchBar component re-use explicit (one
component, mounted three times with corpus-specific data) instead of
silently forking.

**Independent Test**: Cross-navigate `/ohbm2026/` → `/neuroscape/` →
atlas-root. On each surface, type the same query containing each of
`"exact phrase"`, `-foo`, `word OR word`, and `id:N` (substituting a
valid id for the surface — poster_id on OHBM, pubmed_id on NeuroScape,
either on atlas-root). Observe that each operator behaves identically
(same parser, same negation semantics, same id-autocomplete affordance).
Cross-navigate back to `/ohbm2026/` and confirm nothing in that
experience changed (same SearchBar bytes — FR-016 / SC-007).

**Acceptance Scenarios**:

1. **Given** a user familiar with the OHBM 2026 SearchBar, **When** they
   land on `/neuroscape/` OR atlas-root, **Then** the SearchBar is the
   SAME component (same syntax, same operator set, same help dropdown,
   same `✨ Semantic` toggle position) — only the placeholder text +
   the `id:` autocomplete corpus differ.

2. **Given** the user types `-fmri` on `/neuroscape/`, **When** the
   query runs, **Then** articles whose titles contain "fmri" are
   excluded — identical to `/ohbm2026/`'s existing negation semantics.

3. **Given** the user types `id:1234` on atlas-root, **When** the query
   runs, **Then** ANY article whose id matches `1234` is surfaced — be
   it OHBM `poster_id=1234` or NeuroScape `pubmed_id=1234` (or both).
   The result list's existing source pill identifies which corpus each
   matched row came from. No new operator names (no `pmid:` / `poster:`)
   are introduced.

4. **Given** the user has all three surfaces open in tabs, **When**
   they enable semantic search on one, **Then** enabling it on the
   others does not require re-learning the toggle — the affordance is
   recognisably the same control because it IS the same control.

---

### User Story 4 - Cross-conference search on atlas-root (Priority: P2)

The atlas-root subsite (`abstractatlas.brainkb.org/`) today ships a scatter
visualisation plus toggle-able OHBM 2026 overlay but has NO search surface.
A visitor who lands there and wants to find "all articles about
hippocampal sharp-wave ripples" cannot do so without first navigating into
one of the two child subsites.

Add a search bar on atlas-root that ranks across BOTH corpora (~3.2k OHBM
2026 abstracts + ~461k NeuroScape articles) and merges them into a single
ranked result list. The corpus-source identifier (OHBM vs NeuroScape) is
already carried by atlas-root's existing `cross_pointers` rows + scatter
colouring — no new per-row badge UX is added by this story. Existing
atlas-root facets (the OHBM overlay toggle) MUST NOT change; they remain
the only filter affordance on this surface. Semantic search contributes
ONLY a distance-based re-ordering of the merged result list — no new
result-set scoping logic.

**Why this priority**: Equal-priority with US2 (loading UX) — atlas-root
search depends on the same underlying ranking machinery as US1's
NeuroScape search, so shipping it in the same cycle adds proportionally
little incremental work. Bumping it to P1 would risk crowding US1's
NeuroScape-specific testing; demoting to P3 would invite a third spec
cycle just to enable cross-conference discovery.

**Independent Test**: Open atlas-root, type a query that has lexical
matches in BOTH the OHBM 2026 corpus AND the NeuroScape corpus, observe
a single merged ranked result list with rows from both corpora identified
by the existing source pill/colouring. Enable `✨ Semantic` → semantically
related rows from EITHER corpus appear in the merged list. Click any row
→ navigates to the correct per-subsite permalink via the existing
cross-pointer path.

**Acceptance Scenarios**:

1. **Given** the user is on atlas-root and types a query, **When** the
   query has lexical title matches in both corpora, **Then** the result
   list shows hits from both, ranked together, each row identified by the
   already-shipped OHBM-or-NeuroScape source indicator.

2. **Given** semantic search is enabled and the query has zero lexical
   matches in EITHER corpus, **When** semantic ranking runs, **Then** the
   result list shows the closest semantically related rows from across
   BOTH corpora, ranked by distance — without invoking any new facet UI.

3. **Given** the user clicks a result row, **When** the click is on an
   OHBM 2026 row vs. a NeuroScape row, **Then** the navigation lands on
   the correct per-subsite permalink (`/ohbm2026/abstract/<poster_id>/`
   or `/neuroscape/abstract/<pubmed_id>/`) using the existing cross-
   pointers table on atlas-root.

4. **Given** the existing atlas-root overlay toggle (Show OHBM 2026
   overlay) is in some state, **When** the user types in the search bar,
   **Then** that toggle's state does NOT change and the toggle remains
   the only filter affordance — the result list is not scoped by it.

---

### Edge Cases

- **Empty query + semantic enabled**: a user who toggles `✨ Semantic` on
  with an empty input sees no semantic-only hits (since there is no query to
  rank against). The toggle should remain visibly "on" and ready; semantic
  hits appear as soon as the user types.
- **Single-character or very short query**: queries shorter than a small
  threshold (e.g. <3 chars) MUST NOT spend a worker round-trip on semantic
  ranking. The toggle stays on but semantic ranking pauses until the query
  has enough signal.
- **Filtered scope**: when a cluster or year facet is active, the semantic
  result list MUST respect the facet — semantic-only hits OUTSIDE the active
  facet scope are filtered out, not displayed greyed-out.
- **Already-in-cart row surfaced semantically**: an article the user already
  added to their cart via lexical search and that ALSO scores high
  semantically MUST NOT appear twice. Its row shows the existing in-cart
  state and no `✨` badge (the lexical match takes precedence over the
  semantic-only badge).
- **Browser without WebAssembly / SIMD**: the semantic worker MUST detect the
  absence of the runtime features it needs (e.g. SIMD for the cosine
  similarity inner loop) and surface a clear "semantic search isn't
  available on this browser" state rather than silently falling back to a
  slow path that locks the UI thread.
- **Stale on-disk cache after a re-build**: when a `build-atlas-package`
  rebuild changes the semantic index state-key, an old browser cache MUST
  detect the mismatch (via the index's manifest sidecar) and re-fetch
  rather than serve a stale index whose row order no longer matches the
  current articles table.
- **First-load on a metered connection**: the semantic index download MUST
  be entirely user-initiated (only triggered when the user enables `✨
  Semantic`) so visitors who never use the feature never pay the bytes.
- **KNN expansion spans many clusters**: a top-3 article's k=20 KNN
  neighbours may belong to several different clusters whose vectors
  haven't been range-fetched yet. Per FR-024 the loader caps the
  per-session cluster-bounded range-fetch count (default 4) and
  surfaces a one-time "expand search depth?" affordance so the user
  opts in to additional cluster fetches rather than silently paying
  the bytes. Capped queries still return results — they're scored
  using the cluster vectors already in memory, with neighbours from
  un-loaded clusters ranked by their precomputed KNN distance to the
  seed article instead of by direct cosine to the query.
- **OHBM corpus alone yields no candidates**: a query that hits no
  lexical matches in either corpus AND whose closest cluster centroid
  is exclusively NeuroScape MUST NOT silently drop OHBM rows from the
  cross-conference result list — atlas-root MUST still include
  brute-force OHBM scoring (FR-022) as a parallel lane, so any
  semantically relevant OHBM abstract surfaces alongside the
  NeuroScape candidates.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The `/neuroscape/` subsite MUST add a `✨ Semantic` toggle to
  its search affordance, visually consistent with the OHBM 2026 toggle.
  (FR-001 is the user-facing functional claim; FR-025 is the
  implementation-mechanism claim that the toggle is rendered by the SAME
  `SearchBar.svelte` component bytes — the two requirements overlap by
  design.)

- **FR-002**: When semantic search is enabled and the query is non-empty,
  the result list MUST be a MERGE of (a) the existing lexical typo-tolerant
  matches over titles AND (b) semantic top-K matches from the NeuroScape
  article corpus, with each semantic-only row visibly badged.

- **FR-003**: Semantic-only result rows MUST carry the same `✨` badge
  styling and tooltip text as the OHBM 2026 site — the visual contract is
  shared between the two subsites so users learn it once.

- **FR-004**: The semantic index MUST be loaded lazily — bytes are
  downloaded only after the user enables `✨ Semantic`. Visitors who do not
  enable semantic search MUST NOT incur any of the index's network cost.

- **FR-005**: A successful first-time semantic toggle MUST surface a
  loading state (visual indicator on or near the toggle) for the duration
  of the index fetch + worker boot. The toggle MUST reach a stable "ready"
  state before the user is expected to see semantic hits in the result
  list.

- **FR-006**: A failed semantic index load (network failure, server error,
  byte-count mismatch with the manifest, etc.) MUST return the toggle to
  its off state with a visible explanatory message + a `Retry` affordance.
  The toggle MUST NOT silently stay in a "loading forever" state.

- **FR-007**: The semantic index MUST be byte-identical for the same
  underlying NeuroScape article set + semantic-model parameters across
  rebuilds (the same byte-identity contract that the rest of Stage 15 already
  honours via pinned timestamps).

- **FR-008**: The detail panel for a semantically-surfaced article MUST be
  identical to the detail panel for a lexically-surfaced article (same
  PubMed E-utilities fetch path, same per-article permalink, same cart-add
  affordance). Semantic-only rows are full first-class citizens once
  surfaced.

- **FR-009**: When a cluster or year facet is active on `/neuroscape/`, the
  semantic result list MUST respect that facet — semantic-only hits outside
  the active scope are filtered from the result list, NOT shown greyed-out.

- **FR-010**: Queries with fewer than a minimum-character threshold MUST
  NOT spend a worker round-trip. The threshold MUST match the OHBM 2026
  site's existing minimum so users do not see different "semantic kicks in
  after N chars" behaviour between the two subsites.

- **FR-011**: The semantic index sidecar MUST ship with machine-readable
  provenance (article-set state-key, model identifier, vector dimension,
  quantisation strategy, build code-revision, build wall-clock timestamps)
  so the browser can detect a stale-cache vs. current-index mismatch and a
  human can audit which articles + model produced the embeddings.

- **FR-012**: The `ohbmcli build-atlas-package` command MUST be the single
  entry point that produces the semantic index. The index MUST be produced
  in the same run that produces `neuroscape.parquet` (so the two are
  always co-versioned) and MUST live next to it on the deploy host.

- **FR-013**: A configuration flag on `ohbmcli build-atlas-package` MUST
  allow operators to skip the semantic-index step for fast iterations on
  the rest of the build (the index pre-compute is the longest single step
  on a fresh run). When skipped, the produced bundle MUST be missing only
  the semantic sidecar — `neuroscape.parquet` itself MUST be unchanged.

- **FR-014**: The browser MUST detect a `neuroscape.parquet` ↔ semantic-
  sidecar state-key drift (the parquet says state-key X, the cached
  sidecar says state-key Y) and surface a precise reload affordance — the
  same visible-error pattern Stage 15 established for the cross-parquet
  drift detector.

- **FR-015**: The semantic similarity computation MUST run off the main
  thread (in a Web Worker). The result list MUST remain scroll-responsive
  while a semantic ranking is in flight.

- **FR-016**: The existing `/ohbm2026/` semantic search behaviour and
  the OHBM 2026 parquet bytes MUST be byte-identical before and after
  this change. The atlas-root build gains a search bar (FR-017–FR-020)
  + may grow new sidecar bytes, but the OHBM 2026 site is strictly
  unaltered.

- **FR-017**: The atlas-root subsite (`abstractatlas.brainkb.org/`)
  MUST add a search bar that ranks across BOTH corpora (OHBM 2026
  abstracts + NeuroScape articles) and merges hits into a single
  ranked result list.

- **FR-018**: Atlas-root result rows MUST identify the source corpus
  using the existing OHBM-vs-NeuroScape indicators already shipped on
  atlas-root (cross-pointers rows + scatter colour palette). NO new
  per-row badge UX is introduced for source identification by this
  spec.

- **FR-019**: Atlas-root search MUST NOT change or extend the existing
  atlas-root facet affordances (the Show OHBM 2026 overlay toggle).
  Semantic search contributes ONLY a distance-based re-ordering of
  the merged result list — no new result-set scoping logic, no new
  filter UI.

- **FR-020**: Clicking an atlas-root search result row MUST navigate
  to the corresponding per-subsite permalink
  (`/ohbm2026/abstract/<poster_id>/` for OHBM rows,
  `/neuroscape/abstract/<pubmed_id>/` for NeuroScape rows) via the
  existing cross_pointers table on atlas-root.

- **FR-021**: NeuroScape semantic ranking MUST use the cluster-routed
  + KNN-expansion pipeline (no brute-force over all 461k vectors per
  query):

  1. Embed the query client-side.
  2. Score the query vector against the ~50 cluster-centroid vectors
     (already loaded with `neuroscape.parquet` on page load) and
     pick the **single closest centroid**.
  3. Range-fetch the rows where `cluster_id == <closest>` from
     `neuroscape_vectors.parquet` via hyparquet's
     `asyncBufferFromUrl` (parquet row-group min/max predicate
     pushdown drives the HTTP range request); brute-force cosine
     within those rows; take **top-3 matches**.
  4. Walk the existing k=20 KNN graph (already in
     `neuroscape.parquet`) outward from those top-3 to expand the
     candidate set across adjacent clusters.
  5. Re-rank the full candidate set by cosine to query. KNN
     neighbours whose `cluster_id` is NOT yet in memory trigger
     additional cluster-bounded range requests against
     `neuroscape_vectors.parquet` on demand.

- **FR-022**: OHBM 2026 semantic ranking (used on atlas-root for the
  OHBM half of the cross-conference search) MUST use brute-force
  cosine over the full OHBM index. Cluster routing is NOT applied —
  the corpus is small enough (~3.2k vectors) that brute force is
  faster than the routing overhead.

- **FR-023**: Atlas-root cross-conference ranking MUST run BOTH
  pipelines in parallel (NeuroScape cluster-routed + OHBM
  brute-force) and merge the two ranked lists by cosine score. No
  source-bias weighting is applied — the closest match across
  EITHER corpus wins position 1.

- **FR-024**: When the cumulative number of distinct clusters whose
  vectors have been range-fetched in a single browser session exceeds
  a configurable threshold (default 4), the loader MUST cap further
  cluster-bounded range fetches and surface a one-time "expand search
  depth?" affordance — protecting metered-connection visitors from
  accidental large downloads via repeated multi-cluster queries.

- **FR-025**: All three surfaces (`/ohbm2026/`, `/neuroscape/`,
  atlas-root) MUST reuse the existing OHBM `<SearchBar>` component
  verbatim — same parser, same operator set, same help-dropdown
  copy, same `✨ Semantic` toggle position. The supported operators
  are: implicit-AND multi-word, `"exact phrase"` quoted-phrase,
  `-foo` and `-"exact phrase"` negation, `word OR word` alternation,
  and `id:N` lookup. Per-surface differences are limited to: (a)
  placeholder text describing the corpus, (b) the `id:`
  autocomplete data source (`poster_id` index on OHBM, `pubmed_id`
  index on NeuroScape, the union on atlas-root). No surface-
  specific operators are introduced.

- **FR-026**: The `id:N` operator on atlas-root MUST match BOTH
  corpora's id columns in parallel — a query `id:1234` surfaces
  rows where `poster_id == 1234` (OHBM lane) OR `pubmed_id == 1234`
  (NeuroScape lane). When both match (rare given the typical OHBM
  4-digit / PubMed 7-8-digit ranges), BOTH rows MUST appear. The
  existing source pill on each result row identifies which corpus
  the match came from; no new `pmid:` / `poster:` operator names
  are introduced.

### Key Entities

- **NeuroScape cluster-centroid table**: ~50 cluster-centroid vectors
  (one per `cluster_id` already on the articles table), shipped INSIDE
  `neuroscape.parquet` as a new small table (~50 × 384 floats ≈ 80 KB).
  Loaded with the main parquet on page load. The browser scores the
  embedded query against these centroids to pick the routing cluster
  (Step 2 of the ranking pipeline) before fetching any per-article
  vectors.

- **NeuroScape vectors parquet (sibling file `neuroscape_vectors.parquet`)**:
  a single dedicated parquet file carrying the per-article semantic
  vectors. Two columns: `pubmed_id INT64`, `minilm_vector
  FIXED_LEN_BYTE_ARRAY(384)` (INT8 quantised). Rows are **sorted by
  cluster_id** so parquet row-group min/max statistics let the browser
  predicate-pushdown to `cluster_id == X` and the underlying HTTP range
  request fetches only the byte ranges containing that cluster's
  vectors. NO per-cluster sidecar files. NO refactor of the existing
  eager full-file load of `neuroscape.parquet`. Co-versioned with the
  articles table via a shared state-key.

- **OHBM 2026 semantic index**: a single brute-force vector file keyed by
  `poster_id`. The OHBM corpus is ~3.2k abstracts, so cluster routing
  would add overhead without benefit; brute-force cosine over the whole
  set runs in ~1 ms and the artefact is tiny (~1 MB INT8). Used by
  atlas-root cross-conference search (US4) AND, when the project later
  decides to enable `/ohbm2026/`-only semantic search, by that surface
  too — but that's NOT in this spec's scope.

- **Semantic-index manifest**: a small companion JSON document
  declaring the state-key, model identifier, vector dimension,
  quantisation strategy, vectors-parquet path + byte size, cluster
  centroid row count, and build provenance. The browser checks this
  first to decide whether its cached vectors parquet is still fresh
  before issuing any range request.

- **Query embedder**: the in-browser pathway from the user's typed string
  to a vector in the same space as the corpus index. Runs entirely client-
  side so no per-query network call is made. The embedder model MUST match
  the corpus embedder model (else cosine similarity is meaningless).

- **Candidate set (transient)**: the per-query in-memory union of
  (a) the closest cluster's top-3 brute-force matches and (b) those
  top-3's k=20 KNN neighbours from the existing
  `neuroscape.parquet` neighbour table. Re-ranked by cosine to query
  before being merged with the lexical-hit list. Never persisted.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python execution for the semantic-index build step
  (orchestrator, embedding compute, sidecar emit, tests) MUST use
  `.venv/bin/python` or `uv` targeting that interpreter.

- **CA-002**: Each behaviour-changing user story MUST land with its tests
  added or updated BEFORE implementation:
  - US1 tests: semantic-only hit appears in the merged result list with a
    `✨` badge for a query with no lexical matches; toggle-off reverts.
  - US2 tests: loading indicator visible during first toggle; failure
    path returns toggle to off + shows Retry.
  - US3 tests: the toggle's visual position + badge styling match the
    OHBM 2026 reference.
  - Index byte-identity test: two consecutive `build-atlas-package` runs
    with pinned timestamps produce sha256-identical semantic sidecars
    (mirrors the existing parquet byte-identity test).

- **CA-003**: When this feature lands, the spec 015 plan + the `CLAUDE.md`
  reading-order block MUST be updated to record the semantic-search add,
  and the deferred-item inventory's "NeuroScape semantic search" entry
  MUST be flipped from Still-Relevant to Addressed.

- **CA-004**: No new external service credentials are required by this
  feature — embedding compute runs locally during the
  `ohbm2026.build-atlas-package` Python step. If a future iteration ever
  swaps to a hosted embedding API, that swap MUST name the env-var
  boundary in its spec, not this one.

- **CA-005**: The semantic index sidecar produced by the Python build
  MUST land under a gitignored path (`data/outputs/atlas-package/` is
  already gitignored). No part of the index — bytes, manifest, or per-
  build provenance — may be tracked in the repository.

- **CA-006**: Every failure mode in the spec (sidecar fetch failure,
  byte-count mismatch, state-key drift, missing browser feature) MUST
  surface a visible, actionable error to the user — never a silent
  fallback to lexical-only ranking with no explanation. The browser MUST
  log enough context to the dev console for support diagnosis.

- **CA-007**: The build step MUST NOT hardcode the NeuroScape article
  count, the v1.0.1 shard layout, or the per-shard pubmed-id range. The
  article set, vector dimension, and per-article ordering MUST be
  discovered at runtime from the same NeuroScape v1.0.1 loader that
  Stage 15 already uses.

- **CA-008**: The deployed semantic sidecar MUST ship with its provenance
  file (FR-011) alongside the bytes — same path root, no absolute paths,
  no user-home paths. The provenance MUST name the build code-revision,
  the model identifier, the wall-clock build timestamps, the article-set
  state-key, and the resulting vector-bytes sha256 so the browser can
  cross-check a cached copy against a fresh manifest.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user typing a 3-5 word conceptual query that has ZERO
  lexical title matches MUST receive at least one `✨`-badged semantic
  hit in the result list within 3 seconds of the last keystroke (after
  the semantic index is loaded).

- **SC-002**: Enabling the `✨ Semantic` toggle MUST be instant
  (toggle reaches its "on" state within 100 ms) — the centroid
  table is already in `neuroscape.parquet` so no new bytes are
  required to ARM the lane. The first ACTUAL query then triggers
  the cluster-bounded range-fetch from `neuroscape_vectors.parquet`;
  semantic hits MUST appear in the result list within 10 seconds on
  a typical home broadband connection (≥10 Mbps). Slower connections
  see a proportional wait but never a frozen UI.

- **SC-003**: A subsequent semantic query that touches the SAME
  cluster as a prior query in this session MUST return semantic
  hits in under 2 seconds. The browser MUST NOT re-fetch the
  cluster vectors already in memory or in the Cache API when the
  vectors parquet's state-key matches.

- **SC-004**: A second `build-atlas-package` run with unchanged
  NeuroScape inputs + pinned timestamps MUST produce a byte-identical
  semantic sidecar (sha256 match) to the first run. This mirrors the
  existing Stage 15 byte-identity contract.

- **SC-005**: Adding the semantic-index build step to a fresh
  `build-atlas-package` run MUST add less than 15 minutes to the
  end-to-end wall-clock time on the operator's reference machine. The
  index pre-compute step MUST be cacheable on its own (same key
  approach as the UMAP-fit cache) so an iteration that does not change
  the article set is essentially free on re-run.

- **SC-006**: On a representative sample of 20 evaluation queries
  curated by the project (concept queries that have known semantically-
  relevant articles but no exact-string title overlap), at least 80% of
  the queries MUST surface at least one of the curated relevant
  articles in the top-10 semantic hits. Below this rate the spec is not
  shipping a usable semantic experience and the underlying embedding
  recipe needs revisiting.

- **SC-007**: The OHBM 2026 site (`/ohbm2026/`) build output MUST be
  byte-identical before and after this change ships (gh-pages bundle
  sha-tracked in CI). This feature is a strictly additive sibling on
  the NeuroScape side.

- **SC-008**: The `✨ Semantic` toggle MUST be visually identical
  (position, label, loading-spinner pattern, badge styling) across
  all three surfaces that ship it (`/ohbm2026/`, `/neuroscape/`,
  atlas-root) — verified by a multi-surface screenshot diff in the
  e2e suite that already gates each deploy.

## Assumptions

- **Corpus scope**: The semantic index covers the FULL NeuroScape v1.0.1
  article set that `/neuroscape/` already serves (~461k articles,
  1999–2023). No year-range or cluster-subset filtering is applied at
  index-build time — the runtime facets handle scope filtering on the
  user's side.

- **Semantic field**: Embeddings cover article TITLES ONLY. This matches
  the explicit user stipulation that for NeuroScape "we only need to
  store the pubmed_id and fetch abstract details on the fly" (recorded
  in the spec 015 clarification round). Indexing body text would require
  shipping body text, which contradicts that directive.

- **Embedding model**: The corpus embedder + browser query embedder pair
  is the same MiniLM family the OHBM 2026 site already uses. This keeps
  the two subsites' semantic affordance behaviourally consistent (same
  similarity metric, same query-to-vector transform) and reuses the
  existing Web Worker + INT8-quantisation pattern without inventing a
  second one. The exact model identifier is a planning-phase choice and
  may differ in a minor variant (e.g. a slightly larger MiniLM trained
  on a biomedical corpus) — but the FAMILY is fixed.

- **Quantisation**: INT8 quantisation is the planning-phase default,
  consistent with the OHBM 2026 site. With the sibling-parquet layout
  the per-query payload on a cold cache is the sum of (~50 × 384 ×
  1 B ≈ 80 KB centroids, ALREADY loaded with `neuroscape.parquet`) +
  (the cluster's row-group from `neuroscape_vectors.parquet`,
  typically ~10k articles × 384 × 1 B ≈ 4 MB, range-fetched on
  demand) + (occasional 1–3 additional cluster-bounded range
  fetches when KNN neighbours cross cluster boundaries). The
  cold-cache first-query budget is therefore ~5–20 MB, not the
  ~50–177 MB a monolithic full-file fetch would impose. Aggressive
  schemes (PCA, product quantisation, smaller-dim model) remain
  available to `/speckit-plan` if a real measurement at full corpus
  scale exceeds the per-cluster budget.

- **Distribution**: The semantic sidecar ships alongside
  `neuroscape.parquet` on the same gh-pages-served path that the
  parquet uses today. No new hosting infrastructure is needed.

- **Cache strategy**: The browser uses the same Cache API + state-key
  validation pattern that Stage 15 already uses for the parquet
  bundle. The state-key check is the source of truth for "is my cache
  still fresh?", not a wall-clock TTL.

- **Browser support**: WebAssembly + SIMD is assumed available on
  contemporary desktop and mobile browsers (the same baseline the
  OHBM 2026 semantic worker already requires). Older browsers see the
  "feature unavailable" path from FR-006.

- **Cross-conference search surface = atlas-root only**: A user typing
  on `/ohbm2026/` does NOT see NeuroScape articles in their results, and
  vice-versa. Each per-subsite search remains scoped to its own corpus.
  Cross-conference ranking lives EXCLUSIVELY on atlas-root (US4 / FR-017
  – FR-020). The per-subsite stories (US1, US2, US3) are unchanged.

- **Permalink behaviour unchanged**: Clicking a semantic-only result
  row opens the same `/neuroscape/abstract/<pubmed_id>/` permalink that
  a lexical-only row opens. The semantic ranking is a discovery aid
  layered on the existing detail-panel path; nothing about
  per-article detail loads or permalinks changes.

- **Stage-15 byte-identity invariants survive (narrowed)**: Adding
  this feature MUST NOT change `ohbm2026.parquet` bytes — that
  parquet remains the existing CI byte-identity gate's primary
  target. `neuroscape.parquet` MAY grow by ~80 KB (the new
  cluster-centroid table). A NEW sibling file
  `neuroscape_vectors.parquet` appears on disk (~50 MB INT8,
  sorted by cluster_id). `atlas.parquet` MAY grow because this
  spec adds the small OHBM 2026 vector index alongside it for
  the cross-conference search. The CI gate is updated to assert
  byte-identity only on `ohbm2026.parquet`; the other parquet
  diffs are reviewed in PR.
