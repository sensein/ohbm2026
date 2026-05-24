# Phase 0 Research — Stage 15 NeuroScape Context

This file consolidates the decisions taken in front of Phase 1 design.
Every decision below was reachable from the spec + the existing repo
state; no NEEDS CLARIFICATION markers remain.

## R-001 UMAP fit parameters and seed

**Decision**.

- 3D fit: `n_components=3, n_neighbors=30, min_dist=0.10, metric='cosine',
  random_state=0, init='spectral', densmap=False`.
- 2D fit: same parameters except `n_components=2`. The two fits are
  independent (the 2D scatter is not a projection of the 3D scatter —
  it is its own UMAP solution on the same Stage-2 vectors).
- Input vectors: NeuroScape Stage-2 (64-dim, unit-norm) collected from
  the HDF5 shards by `atlas_package.neuroscape_loader` (extends the
  vector iteration already implemented in
  `scripts/derive_neuroscape_centroids.py`).
- Cache key for the fit: `sha256(stage2_vectors_concat || param_json)`.

**Rationale**.

- `metric='cosine'` matches how the NeuroScape Stage-2 embedding is
  used elsewhere in the project (spherical-mean centroids in
  `derive_neuroscape_centroids.py`, similarity in
  `neuroscape.compose_recipe`).
- `n_neighbors=30, min_dist=0.10` are inside UMAP's "preserve global
  structure, modest local density" regime — appropriate for a 600K-row
  atlas where the visitor will read both within-cluster local density
  AND between-cluster macro structure. These are the defaults
  recommended by McInnes et al. for ≥100K-row scientific corpora.
- `random_state=0` makes the fit deterministic so the SC-004
  byte-identical second-run requirement holds.
- 2D and 3D are independent fits because using `umap.transform` to
  project a 3D solution down to 2D loses the locality structure UMAP
  is supposed to preserve. The cost is one extra UMAP fit at build
  time (~10 minutes single-shot on a recent laptop for 600K rows on
  CPU); the cost is paid once per centroid table version.

**Alternatives considered**.

- `metric='euclidean'`: rejected. The Stage-2 embedding is angular by
  construction (the published model trains with cosine similarity
  loss); euclidean produces clusters that don't match the upstream
  cluster table.
- `densmap=True`: rejected. Improves density-preservation in the
  projection at the cost of ~3× runtime and a deeper random-state
  surface — not worth it for the size-of-laptop budget here.
- Re-projecting the 3D solution to 2D (single fit): rejected as above.

## R-002 OHBM 2026 projection into the UMAP space

**Decision**. Use `umap_model.transform(ohbm_stage2_vectors)` to project
the OHBM 2026 corpus into the same 2D and 3D UMAP solutions fitted on
NeuroScape Stage-2 vectors. Cache one entry per OHBM 2026 abstract,
keyed by `sha256(stage2_vector || umap_state_key)`. Per-abstract cache
under `data/cache/atlas-projection/<cache-key>.json`.

**Rationale**. `umap-learn`'s `UMAP.transform` is the documented way to
project out-of-sample points into a previously-fitted UMAP space.
Empirically the function preserves the in-vs-out-of-cluster geometry as
long as the OOS points come from the same embedding distribution — the
Voyage→Stage-2 transform is exactly the one NeuroScape itself uses, so
OHBM 2026 abstracts are in-distribution by construction.

**Alternatives considered**.

- Fit UMAP on the union of NeuroScape + OHBM 2026: rejected. (a)
  Refitting any time the OHBM 2026 corpus changes is wasteful, (b) the
  union-fit moves NeuroScape points around, breaking comparability
  across rebuilds.
- Nearest-neighbour assignment in Stage-2 space then copy-position:
  rejected. Doesn't actually place the OHBM 2026 abstract — it stacks
  it on top of the nearest NeuroScape point.

## R-003 Cluster colour palette and legend strategy

**Decision**.

- Top-32 most-populated clusters get distinct colours from a perceptually
  uniform qualitative palette (e.g. `tab20` extended with secondary
  hues to 32). Remaining ~143 clusters use a documented secondary
  palette (lightness-cycled greys / muted hues). Colour assignment
  is deterministic: clusters are ranked by point count in
  `neuroscape.parquet`, the top-32 get palette slots in rank order, the
  rest get the secondary palette in id order.
- The legend renders the top-32 with cluster titles up-front and the
  rest behind a "Show all 175 clusters" disclosure. Visitors can
  toggle visibility per cluster (FR-010).
- Colour table is computed once in `cluster_palette.py` at build time
  and persisted into both `neuroscape.parquet` (cluster table row
  group) and `atlas.parquet` (cluster table row group) — they MUST
  agree, which is asserted by `parquet_writer.py`.

**Rationale**. 175 clusters cannot be uniquely coloured without
sacrificing distinguishability. The top-32 cover the bulk of the
backdrop visually; the long tail is greyed out but legend-searchable.
Persisting the colour table in the parquet (rather than computing it
client-side) keeps the legend consistent across all three deployments
(landing page + `/neuroscape/`) and makes the colours stable across
rebuilds for a fixed centroid table version.

**Alternatives considered**.

- 175-colour palette: rejected on distinguishability grounds.
- Client-side palette generation: rejected on consistency grounds.

## R-004 Three-parquet layout (vs single multi-conference parquet)

**Decision**. Three separate files: `ohbm2026.parquet`,
`neuroscape.parquet`, `atlas.parquet`. `atlas.parquet` is a
cross-connector that holds only what the landing page reads (overlay
scatter rows + backdrop scatter rows + cluster table + sibling state
keys), with **stable-id pointers** into the sibling parquets — no
duplicated bodies.

**Rationale**.

- Matches the user's directive: "one parquet per conference, plus a
  cross-connector for the front page".
- Each deployment fetches exactly one parquet so per-page transfer
  size is bounded. Visitors who land on `/` and don't follow either
  outbound link never download the bulky `neuroscape.parquet`.
- Body de-duplication keeps `atlas.parquet` small (estimated <30 MB
  for current scale vs >500 MB if bodies were duplicated).
- Stable-id pointers (`source: 'ohbm2026' | 'neuroscape'`,
  `id: int64`) let the landing-page slide-in detail panel hydrate
  from the appropriate sibling parquet on click — but per FR-015 the
  default behaviour is a deep-link into the sibling subsite, which
  needs no body fetch at all.

**Alternatives considered**.

- One mega-parquet with a `conference_id` column (the Stage 10
  "Phase 5 cross-conference" deferred path): rejected for spec 015.
  Forces every visitor to download all corpora; ergonomics of a single
  600K-row + 3K-row mixed table are worse; conference outputs are
  designed to be frozen post-build, so a separate parquet per
  conference is the natural unit.
- Two parquets only (no cross-connector — landing page fetches both):
  rejected. Doubles the landing-page bytes; visitors who don't follow
  a sibling link pay for it anyway.

## R-005 Browser-side decoder strategy for three parquets

**Decision**. Reuse the existing `hyparquet`-based decoder in
`site/src/lib/data_package/loader.ts`. Parametrise the URL fetch by
`SITE_MODE`:

- `ohbm2026` mode → `VITE_DATA_PACKAGE_URL_OHBM2026` →
  `ohbm2026.parquet`.
- `neuroscape` mode → `VITE_DATA_PACKAGE_URL_NEUROSCAPE` →
  `neuroscape.parquet`.
- `atlas-root` mode → `VITE_DATA_PACKAGE_URL_ATLAS` →
  `atlas.parquet`.

Each mode reads exactly one URL. The decoder branches once on
`SITE_MODE` to dispatch the table-name-to-shard-key mapping for the
new `atlas` and `neuroscape` table layouts. Existing `ohbm2026` table
names (`abstracts`, `cells:*`, `topics:*`, `neighbors:*`, etc.) and
their decoder behaviours are untouched.

**Rationale**. No new browser dependency. The existing
`parquet_single` outer/inner BLOB layout already works for arbitrary
inner-table schemas; we just add new outer rows for the new tables.
The `coerceBigInts` + `parquetReadObjects` plumbing carries over
unchanged.

**Alternatives considered**.

- Per-mode separate loaders: rejected. Duplicates ~200 lines of
  decoder logic for no compression benefit.
- Switch to DuckDB-WASM for cross-parquet `JOIN`: rejected. Stage 10
  bench already explicitly deferred this; the spec confirms cross-conf
  linking is out of scope for 015.

## R-006 SvelteKit multi-mode build strategy

**Decision**. Single SvelteKit project, three build invocations, each
keyed on `SITE_MODE` + `BASE_PATH`:

| SITE_MODE     | BASE_PATH       | Parquet URL env                    | Publish dir            |
|---------------|-----------------|-------------------------------------|------------------------|
| `ohbm2026`    | `/ohbm2026`     | `VITE_DATA_PACKAGE_URL_OHBM2026`    | `site/publish/ohbm2026/` |
| `neuroscape`  | `/neuroscape`   | `VITE_DATA_PACKAGE_URL_NEUROSCAPE`  | `site/publish/neuroscape/` |
| `atlas-root`  | `` (empty)      | `VITE_DATA_PACKAGE_URL_ATLAS`       | `site/publish/`         |

`svelte.config.js` already reads `BASE_PATH`. The new
`site/src/lib/site_mode.ts` reads `SITE_MODE` from
`$env/static/public` (Vite injects it at build time as
`VITE_SITE_MODE`). `+layout.svelte` and `+page.svelte` branch on the
exported `SITE_MODE` constant — when `ohbm2026` (default), the
branches all take the existing path, so the OHBM 2026 build output is
byte-identical to the pre-change baseline modulo the parquet URL
string (verified by `test_ohbm2026_parquet_rename.py` + the CI diff
step demanded by SC-008).

**Rationale**. Three SvelteKit builds are cheap (each is ~10-20s in CI
today). One project keeps component reuse trivial. `SITE_MODE`
conditional rendering touches exactly two routes (home + abstract
detail) and one layout-header file — small, reviewable diff.

**Alternatives considered**.

- One SvelteKit project + a runtime "what site am I" switch based on
  `window.location.pathname`: rejected. Sends both NeuroScape and OHBM
  2026 code paths in every bundle; defeats per-mode tree-shaking;
  fails FR-022 byte-identical check.
- Three separate SvelteKit projects (one per mode): rejected.
  Forks the component library, doubles maintenance burden, defeats the
  "reuse the OHBM 2026 site's component library" requirement (FR-016).
- Multi-app monorepo workspace (`apps/ohbm2026`, `apps/neuroscape`,
  `apps/root`): rejected. Same fork cost as separate projects, with
  added workspace-tool complexity.

## R-007 Retiring the Stage 9 root redirect island

**Decision**. The new bare-root SvelteKit build (mode `atlas-root`)
replaces the publish-root contents of `site/conference-root-redirect/`
in the deploy workflow. The `site/conference-root-redirect/` source
directory itself is preserved in-tree (operator history + the
`/sandbox/` redirect still uses it) but no longer copied to the
publish staging tree for production builds. PR previews behave the
same — the per-PR publish root gets the atlas-root build, not the
redirect island.

**Rationale**. The redirect island and the new landing page cannot
coexist at the bare root (HTML conflict). The Stage 9 redirect served
its purpose; with a real landing page at `/`, the redirect is
strictly less useful (visitors get more, not less). Keeping the
source files in-tree preserves git blame + the operator-facing comment
documenting the original mechanism.

**Alternatives considered**.

- Delete `site/conference-root-redirect/` entirely: rejected.
  `/sandbox/` and the PR-preview-cleanup workflow still reference the
  redirect mechanism; this feature does not touch those paths.

## R-008 NeuroScape neighbour shard scope

**Decision**. Precompute k-NN (k=20) for **all ~600K NeuroScape
articles** in NeuroScape Stage-2 space at build time, persist into
`neuroscape.parquet` as a `neighbors_neuroscape` row group with the
same parallel-arrays shape Stage 6 uses for OHBM 2026 neighbours.
Compute uses `sklearn.neighbors.NearestNeighbors(algorithm='ball_tree',
metric='cosine')` or `pynndescent` (already an indirect dep through
`umap-learn`) — picked at orchestrator time based on which is
faster on the available hardware.

**Rationale**. Per the spec (FR-019 + US3) every NeuroScape detail page
shows a "Nearest neighbours" list; computing this lazily in-browser
against 600K vectors is not feasible (Stage-2 vectors are 64 × 600K ×
4 = ~150 MB, well above the per-page transfer budget). Precompute at
build time, ship the resulting `(int32, int32)` parallel arrays
(~24 MB total at k=20, fits comfortably in `neuroscape.parquet`).

**Alternatives considered**.

- Lazy in-browser k-NN with a Web Worker: rejected on payload
  grounds.
- k=10: rejected — too few for a "show me more like this" affordance.
- k=50: rejected — diminishing UX returns for double the payload.
- Server-side k-NN endpoint: rejected — no server in this deploy
  model.

## R-009 Typed exception subtree for Stage 15

**Decision**. Extend `src/ohbm2026/exceptions.py` with a new subtree:

```text
OhbmStageError
└── Stage15Error
    ├── NeuroScapeInputError        # missing/changed HDF5 shard, CSV checksum drift
    ├── UmapFitError                # UMAP fit failure (numerical, OOM, etc.)
    ├── OhbmProjectionError         # transform of OHBM 2026 vectors failed
    ├── CrossParquetDriftError      # atlas.parquet's sibling state-keys don't match the live sibling parquets
    ├── AtlasProvenanceError        # absolute / $HOME path in provenance (re-uses existing ProvenanceError contract)
    └── AtlasLinkCheckError         # external link-check failure
```

`OhbmProjectionError` carries the offending submission id; the
orchestrator collects all such failures and re-raises a single
`OhbmProjectionError` listing every failed id only at the END of the
projection pass, so a single broken record does not stop the run mid-
way (resumability — Principle III).

**Rationale**. Mirrors the Stage 1 / Stage 2 exception-subtree pattern
already in `exceptions.py`. Typed exceptions let the test suite assert
specific error paths (per CA-002) instead of regex-matching generic
`RuntimeError` messages.

**Alternatives considered**.

- One flat exception class with an enum discriminator: rejected;
  doesn't match the existing convention.
- Reusing existing Stage 1/2 exception classes: rejected; the failure
  modes are different (UMAP / cross-parquet drift / link-check have
  nothing in common with checkpoint or enrichment failures).

## R-010 OHBM 2026 byte-identical guarantee (SC-008) — how it's enforced

**Decision**. Add a CI step `test_ohbm2026_parquet_rename.py` that:

1. Builds `ohbm2026.parquet` from the current corpus state-key via
   `ohbmcli build-ui-data` (with the rename applied).
2. Builds the legacy `data.parquet` by running the same command with
   an env override forcing the old filename.
3. Asserts the two files have byte-identical content (`sha256` match).
   Filenames differ; content does not.

Additionally, an automated diff step in `deploy-ui.yml` builds the
`SITE_MODE=ohbm2026` tree both with and without the FR-022 plumbing
applied and asserts the build trees are byte-identical modulo the
parquet URL string. (The "without" baseline is computed against `main`
just before the merge.)

**Rationale**. Spec FR-022 + SC-008 demand that the existing
`/ohbm2026/` deployment is unchanged in everything but the parquet
pointer string. Both the upstream (Python) and downstream (build tree)
guarantees need automated enforcement; doing it once in a CI step
keeps reviewers honest forever.

**Alternatives considered**.

- Manual sign-off only: rejected (regresses too easily).
- Snapshot-test the rendered `/ohbm2026/` home page DOM: rejected;
  brittle and downstream of the actual byte-identity goal.

## R-011 Decimation and mobile fallback strategy

**Decision**. Build emits **two** backdrop sample arrays in
`atlas.parquet`: `neuroscape_full` (all ~600K rows) and
`neuroscape_decimated` (≤50K rows). The decimation is a per-cluster
stratified random sample with deterministic seed=0, sampling
`min(cluster_count, ceil(50000 * cluster_count / total))` rows per
cluster so cluster proportions are preserved. The landing page chooses
which array to render based on a feature-detection signal (default:
mobile UAs / pixel-ratio + memory hint → decimated; "Show full atlas"
button flips to full).

**Rationale**. Loading and rendering 600K WebGL points on a mid-range
phone exhausts memory; the spec calls out SC-007 (≤10 s on mid-range
mobile) explicitly. Per-cluster stratification keeps every cluster
visually present in the decimated view so the legend remains
meaningful. 50K is empirically the largest single-point-cloud size
that stays interactive on a 4-year-old phone using regl/three.js
(Stage 6 perf baseline data).

**Alternatives considered**.

- Decimate client-side: rejected — still requires the full transfer.
- Single decimated default for everyone: rejected — desktop visitors
  rightly want to see the full landscape; the "Show full atlas"
  affordance lets them.

## R-012 Cross-parquet state-key drift detection at the loader

**Decision**. `atlas.parquet`'s manifest row (in the build_info block)
embeds `sibling_state_keys: {ohbm2026: <state-key>, neuroscape:
<state-key>}`. On load, the SvelteKit `loader.ts` fetches the
sibling parquet's manifest only (via an HTTP Range request restricted
to the manifest row group, ~few KB) and asserts the state-keys match.
On mismatch the landing page renders a visible error component naming
the stale/missing sibling and instructing the visitor to retry —
**not** a silent partial scatter.

**Rationale**. Operators who upload only two of the three parquets, or
who update one without the others, would otherwise leave the
production landing page silently inconsistent. The loader-side check
makes this an opt-in red banner rather than a debugging trip.

**Alternatives considered**.

- Build-time only check: rejected — doesn't catch operator upload
  errors after the build.
- Always-fetch sibling parquets on landing page: rejected — defeats
  the point of `atlas.parquet`'s small footprint.

## R-013 Build-time link checking (narrowed to non-PubMed-record URLs)

**Decision**. Build-time link check covers ONLY the small fixed set
of non-PubMed-record URLs:
- NeuroScape Zenodo release URL (one URL)
- NeuroScape citation URL (one URL)
- OHBM 2026 site root (one URL)
- Cross-conference landing page (the new bare-root URL — one URL)
- NCBI E-utilities base URL (one URL — `efetch.fcgi`,
  `esummary.fcgi` reachable)

Per-PubMed-record URLs (`pubmed.ncbi.nlm.nih.gov/<id>/`, per-record
DOIs) are **not** pre-checked at build time — see clarification
in spec FR-024. Their health is enforced at view time by the
SvelteKit detail page's runtime fetch (R-015), which surfaces dead
records as the body offline state.

**Rationale**. Pre-checking 600K records against NCBI at build time
violates NCBI's documented rate limits (3 req/s anon would take ~55
hours per build), and DOI HEAD checks against `doi.org` would
exhaust common rate-limit budgets too. View-time fetch shifts the
"is this record alive" check to when a visitor actually needs it,
amortising it across many sessions; transient PubMed outages
degrade gracefully instead of blocking deploys.

**Alternatives considered**.

- Pre-check every PubMed record: rejected on rate-limit grounds
  (above).
- Sample-check (e.g. 1%): rejected — partial coverage with
  build-time gating is worse than no coverage at all.
- Skip link checking entirely: rejected — the small fixed set
  covers high-value, low-volume URLs that a 4xx would surface as a
  user-visible UI break.

## R-014 SvelteKit `+page.svelte` branching for `atlas-root` mode

**Decision**. The existing `site/src/routes/+page.svelte` retains its
current shape for `SITE_MODE === 'ohbm2026'` and gains a new branch
for `SITE_MODE === 'atlas-root'` that:

- Renders the `UmapPanel` (already exists) configured with the
  `atlas.parquet` overlay + backdrop sample arrays.
- Renders a `LandingPageHeader` (new) with the two outbound subsite
  links and a binary `AtlasOverlayToggle` (new).
- Does NOT render `SearchBar`, `ResultList`, `FacetSidebar`, or
  `CartDrawer` — these are gated by `SITE_MODE !== 'atlas-root'`.
- Renders `DetailPanel` in slide-in mode on point click; the panel
  hydrates from the embedded row in `atlas.parquet` (which contains
  only summary fields, not the full body — for the body the panel
  shows a "Open on /ohbm2026/ →" or "Open on /neuroscape/ →" CTA per
  FR-015).

`SITE_MODE === 'neuroscape'` reuses the OHBM 2026 home-page shape
fully (SearchBar + ResultList + FacetSidebar + UmapPanel +
DetailPanel), but reading `neuroscape.parquet`'s tables.
`SearchBar` runs typo-tolerant lexical search over **titles only**
per spec FR-018. The DetailPanel branches by `SITE_MODE` to render
the local NeuroScape fields immediately and to trigger the runtime
PubMed fetch (R-015) for the body.

**Rationale**. Three modes, three home-page shapes. The branching is
done at the JSX/Svelte template level via `{#if SITE_MODE === '…'}`
blocks; build-time `SITE_MODE` is constant so tree-shaking eliminates
the dead branches per-build (verified by the bundle-size diff in CI).

**Alternatives considered**.

- Conditional dynamic imports (`import().then`): rejected — adds
  runtime cost on every visit for no benefit (the mode is fixed per
  build).
- A separate `+page.atlas-root.svelte` file conditionally selected:
  rejected — SvelteKit routes are filename-driven; a SITE_MODE alias
  layer adds tooling complexity for no diff-readability benefit.

## R-015 Runtime PubMed body fetch on the NeuroScape detail page

**Decision**. The SvelteKit `neuroscape` mode's
`abstract/[pubmed_id]/+page.svelte` performs a single client-side
fetch against NCBI E-utilities at page-render time, using:

- **Endpoint**: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi`
  with `?db=pubmed&id=<pubmed_id>&retmode=xml`. EFetch returns the
  full record (title, authors, journal, MeSH, abstract text, DOI) in
  a single round-trip per pubmed_id.
- **Rate limit**: respect NCBI's documented 3 req/s anon. If
  `VITE_NCBI_API_KEY` is set at build time (env var), the value is
  baked into the bundle and the per-session limit rises to 10 req/s.
  The key is a low-sensitivity API token (NCBI's E-utilities key is
  user-attribution, not auth); committing it via
  GitHub Actions repo variable is acceptable per the project's
  Constitution Principle V (the key does not grant write access to
  any external resource).
- **CORS**: `efetch.fcgi` serves `Access-Control-Allow-Origin: *` for
  GETs, verified manually. No proxy required.
- **Cache**: in-memory `Map<pubmed_id, FetchedRecord>` for the
  session. The Map is NOT persisted to localStorage/IndexedDB in
  Stage 15 (avoids stale-cache invalidation work); a future stage can
  add IndexedDB persistence behind a feature flag if traffic patterns
  justify it.
- **Retry**: on 5xx / network error, retry up to 3 times with
  exponential backoff (250 ms, 500 ms, 1 s); on persistent failure
  the page renders the body offline state from spec Edge Cases.
- **First paint**: local fields render immediately from
  `neuroscape.parquet`; the body region renders a skeleton until
  EFetch resolves. Per FR-019b: local fields ≤200 ms, body ≤3 s on
  a warm network.

**Rationale**. EFetch is the cheapest way to materialise the full
PubMed record (one request vs. ESummary + EFetch for abstract text).
NCBI's CORS support means no Cloudflare Worker / proxy is required.
The in-memory cache covers the common case (neighbour click-through
→ back → forward navigation) without the persistence-invalidation
overhead.

**Alternatives considered**.

- ESummary instead of EFetch: rejected — ESummary returns the
  authors + journal but not the abstract text; we'd need to follow
  with EFetch anyway.
- Server-side proxy via the gh-pages host: rejected — gh-pages is
  static-only; no proxy capability.
- Cloudflare Worker proxy: rejected — adds infra + ops cost the
  spec does not justify; CORS already works direct-to-NCBI.
- Persist fetched bodies to IndexedDB: deferred — adds invalidation
  complexity (when does a cached body become stale?); in-memory is
  fine for the typical session.

## R-016 Deferred semantic search (MiniLM → NeuroScape projector)

**Decision**. Semantic search on `/neuroscape/` is **explicitly
deferred** to a sibling stage. Stage 15's
`search:neuroscape_titles` sidecar table-name uses the `_titles`
suffix specifically so the deferred stage can add a parallel
`search:neuroscape_titles_abstracts` (or
`search:neuroscape_minilm_neuroscape_vectors`) sidecar without
breaking the Stage-15 loader's table-name dispatch.

The deferred work consists of: (a) collecting the NeuroScape Stage-2
vectors as float32 arrays (already needed by R-008 for the k-NN
table, so the Python pipeline can persist them as a byproduct under
a feature flag), (b) training a small MLP / linear head bridging
MiniLM 384-dim → NeuroScape 64-dim against the published Stage-2
vectors as targets, (c) exporting the projector for the browser
(ONNX), and (d) extending the SvelteKit search code path to encode
the query in MiniLM → project → cosine over the shipped vectors.

**Rationale**. The user explicitly accepted Option C ("Deferred:
ship lexical-only first, add semantic later") in the clarification
session. Stage 15 stays focused on the cross-conference scatter +
title-only lexical search; the semantic-search project gets its own
constitution check, plan, and tests in a fresh spec.

**Alternatives considered**.

- Ship the projector inside Stage 15: rejected per the clarification.
- Pre-emptively ship Stage-2 vectors in `neuroscape.parquet` even
  without the projector (so semantic can be enabled later by shipping
  only the projector): rejected for Stage 15 — adds ~150 MB to the
  parquet for no Stage-15 user benefit. The deferred stage will add
  the vectors itself when it lands.
