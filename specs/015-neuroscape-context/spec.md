# Feature Specification: NeuroScape Context — Cross-Conference Atlas Landing Page + NeuroScape PubMed Subsite

**Feature Branch**: `015-neuroscape-context`
**Created**: 2026-05-23
**Status**: Draft
**Input**: User description: "we are going to pull in the original neuroscape abstract embeddings, do a umap to 2d/3d, and then project the current abstracts into that space using the neuroscape abstract embedding. we will then add this to front page of the main site and represent ohbm 2026 in the context of the neuroscience landscape. the neuroscape atlas should be colorcoded by cluster categories, and allow a simple toggle to view ohbm2026 abstracts in this space. we will also add a subsite similar to ohbm2026, for neuroscape pubmed abstract navigation and detail viewing."

## Scope clarifier — three sibling deployments on one gh-pages host

`abstractatlas.brainkb.org` is multi-tenant by subpath. This feature
touches **only** the bare root and adds **one** new subsite; the
existing `/ohbm2026/` SvelteKit site is **not** in scope.

- **`/` (bare root)** — currently a static meta-refresh redirect to
  `/ohbm2026/` (Stage 9, file `site/conference-root-redirect/`). This
  feature **replaces the redirect** with a real cross-conference atlas
  landing page: NeuroScape PubMed backdrop + OHBM 2026 overlay,
  toggleable, with a 2D/3D control. This page is the home of the
  combined view.
- **`/ohbm2026/`** — the existing OHBM 2026 site, **untouched** by this
  feature. Its parquet dataset is renamed from `data.parquet` to
  `ohbm2026.parquet` to keep conference-scoped datasets uniquely named;
  the renaming is an upstream-rename + downstream-pointer change, not a
  schema or UX change to the OHBM 2026 site.
- **`/neuroscape/`** — **new** sibling subsite for PubMed abstract
  navigation against the full NeuroScape 1999–2023 corpus, built from
  the existing SvelteKit codebase and component library.

## Clarifications

### Session 2026-05-23

- Q: Data-package layout for the three deployments? → A: One parquet
  per deployment. The existing OHBM 2026 dataset is renamed
  `data.parquet → ohbm2026.parquet`. The new NeuroScape subsite reads
  `neuroscape.parquet`. The bare-root cross-conference atlas reads a
  third parquet (`atlas.parquet`) that contains only what the root page
  needs (combined UMAP scatter + cluster table + cross-conference
  pointers back into `ohbm2026.parquet` and `neuroscape.parquet`). The
  root parquet does NOT duplicate full abstract bodies — it links them.
- Q: How much of the NeuroScape PubMed corpus does the new subsite
  publish and make searchable? → A: The **full** 1999–2023 corpus
  (~600K abstracts). Every NeuroScape PubMed article gets a permalink
  under `/neuroscape/abstract/<pubmed_id>/`, full-text search, faceted
  filtering, and a published record in `neuroscape.parquet`.
- Q: What does this feature touch on the existing `/ohbm2026/`
  SvelteKit site? → A: Nothing visible; only the upstream rename
  `data.parquet → ohbm2026.parquet` and the corresponding pointer
  in the OHBM 2026 site's data loader. The home page, components,
  routes, and behaviour of `/ohbm2026/` are unchanged.
- Q: What kind of mode control should the bare-root atlas landing
  page have? → A: A single binary toggle "Show OHBM 2026 overlay"
  (on by default; off shows NeuroScape backdrop only). Viewing OHBM
  2026 in isolation is intentionally NOT a landing-page mode —
  visitors who want OHBM-only browsing follow the "Browse OHBM 2026
  abstracts →" link into `/ohbm2026/`.
- Q: What search affordance should the landing page expose? → A:
  None text-based. The landing page is purely visual/spatial — only
  hover tooltips, the cluster-legend filter, the binary overlay
  toggle, the 2D/3D control, and lasso. Lassoing a region yields a
  grouped result list split into "OHBM 2026" and "NeuroScape PubMed"
  with click-through to the corresponding sibling subsite detail.
  Text search lives in the two sibling subsites only, keeping
  `atlas.parquet` lean (no cross-corpus search index).
- Q: How much PubMed metadata is stored locally for the NeuroScape
  subsite? → A: Only the **fields the local UI needs to render**.
  `neuroscape.parquet` carries `pubmed_id`, `title`, `year`,
  `cluster_id`, `umap_2d`, `umap_3d`, and the precomputed nearest-
  neighbour `pubmed_id` lists. The PubMed **body** (authors, journal,
  full abstract text, DOI) is NOT stored locally — the detail page
  fetches it at view time from NCBI E-utilities (CORS-enabled). The
  cluster table, neighbours, hover tooltips, and lexical search work
  fully offline; the detail page requires connectivity.
- Q: How does search on `/neuroscape/` work given pubmed-id-only
  storage of bodies? → A: A **hybrid** is planned — typo-tolerant
  lexical search over local **titles**, and (in a later phase)
  semantic search via a MiniLM → NeuroScape Stage-2 projector. Stage
  15 ships the **lexical-on-titles** half only; the semantic half is
  explicitly deferred to a sibling stage and is NOT a release-blocker
  for Stage 15. FR-018 (this spec) commits to title-only lexical
  search; the future semantic phase will land its own FR set.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Cross-conference atlas landing page replaces the bare-root redirect (Priority: P1)

A visitor types `abstractatlas.brainkb.org` (or follows a deep link to
the bare root) and lands on a new combined atlas page. Today the bare
root is a meta-refresh redirect to `/ohbm2026/`. With this feature the
visitor lands on a real page that shows the NeuroScape PubMed
neuroscience landscape (1999–2023, ~600K abstracts) as a colour-coded
backdrop and the ~3K OHBM 2026 accepted abstracts overplotted as a
highlighted foreground layer. A single binary toggle ("Show OHBM 2026
overlay" on/off, on by default) lets the visitor flip between (a)
NeuroScape backdrop alone and (b) NeuroScape + OHBM 2026 overlay.
Visitors who want OHBM-2026-only browsing follow the prominent
"Browse OHBM 2026 abstracts →" link into `/ohbm2026/`. Hovering any
point shows a tooltip; the legend is colour-coded by NeuroScape cluster
category and supports hide/show per cluster. Two header links — "Browse
OHBM 2026 abstracts →" and "Browse the NeuroScape PubMed atlas →" —
send the visitor into the corresponding subsite for full search +
detail.

**Why this priority**: This is the headline organizer-facing payoff
("show OHBM 2026 in the neuroscience landscape") and replaces today's
trivial redirect with a meaningful landing page. None of the other
stories ship without the UMAP solution and colour table this story
needs.

**Independent Test**: Build the atlas data package once (US4), serve
the gh-pages bundle locally, and visit `/`. The page MUST render the
combined view (not a redirect), the cluster legend MUST be present and
interactive, and the binary "Show OHBM 2026 overlay" toggle MUST flip
between (a) the NeuroScape-only backdrop and (b) the combined view
without a full reload.

**Acceptance Scenarios**:

1. **Given** the deploy is live, **When** the visitor opens `/`,
   **Then** they see the NeuroScape backdrop + OHBM 2026 overlay
   (default mode), NOT the meta-refresh redirect to `/ohbm2026/`.
2. **Given** the visitor is on the cross-conference atlas page,
   **When** they click "Show OHBM 2026 overlay" off, **Then** the
   foreground OHBM 2026 layer disappears and only the NeuroScape
   backdrop remains; the legend remains intact and the toggle returns
   the overlay on a second click.
3. **Given** the combined view is active, **When** the visitor hovers
   a NeuroScape point, **Then** a tooltip shows its title, year, and
   the cluster's title; **When** they hover an OHBM 2026 point,
   **Then** the tooltip shows its title, poster id, and nearest
   cluster.
4. **Given** the visitor is on the atlas landing page, **When** they
   click "Browse OHBM 2026 abstracts →", **Then** they navigate to
   `/ohbm2026/`; **When** they click "Browse the NeuroScape PubMed
   atlas →", **Then** they navigate to `/neuroscape/`.
5. **Given** an old bookmark for the bare root, **When** the visitor
   opens it, **Then** they land on the new page (the previous
   meta-refresh redirect is removed) and the experience is at least as
   discoverable as the prior redirect target.

---

### User Story 2 — 2D and 3D atlas views (Priority: P2)

The cross-conference atlas landing page exposes a "View: 2D ↔ 3D"
control. In 3D the visitor sees the rotatable scatter; in 2D the same
UMAP solution is shown as a flat scatter that is faster to scan and
easier to screenshot for slides or social posts. The 2D and 3D
projections come from the same NeuroScape Stage-2 vectors so coordinates
remain cross-comparable. The same control is also available on the
NeuroScape subsite home page.

**Why this priority**: Static 2D versions are the format organizers and
session chairs are most likely to reuse in talks; without this story
visitors who can't comfortably steer a 3D scene are excluded.

**Independent Test**: With US1 shipped, switch the dimensionality
control on the cross-conference atlas landing page. The 2D view MUST
render and remain interactive (hover, lasso, click-through) using the
same legend behaviour as 3D.

**Acceptance Scenarios**:

1. **Given** the atlas landing page in 3D, **When** the user switches
   to 2D, **Then** the scatter re-projects to two axes within 2 seconds
   and hover/lasso/cluster-legend filter keep working.
2. **Given** the user is in 2D, **When** they screenshot the canvas,
   **Then** the resulting image is legible at 1080p without further
   editing.

---

### User Story 3 — Browse and search the NeuroScape PubMed corpus on the new subsite (Priority: P2)

From the cross-conference atlas landing page (US1) the visitor follows
"Browse the NeuroScape PubMed atlas →" into a new sibling subsite at
`/neuroscape/`. The subsite is built from the OHBM 2026 SvelteKit
codebase and reuses its component library, but reads only
`neuroscape.parquet`. It exposes the **full** ~600K-abstract NeuroScape
corpus with: a home page carrying the same 2D/3D scatter coloured by
cluster, **typo-tolerant lexical search over titles**, lasso
selection, faceted filters keyed off cluster category / publication
year, and a detail page per PubMed abstract. Each detail page shows
the locally stored fields (title, year, cluster info, neighbour list,
PubMed permalink) and **fetches the body** (authors, journal, full
abstract text, DOI) on demand from NCBI E-utilities at view time. The
fetched body is cached in the browser for the session so back/forward
navigation does not re-hit the network. Stable permalinks are at
`/neuroscape/abstract/<pubmed_id>/`. The detail page also offers a
"Show on atlas" action that returns the user to the NeuroScape home
page with the article focused and its cluster highlighted.

Semantic search is **out of scope for this story** and ships in a
follow-up stage with the MiniLM → NeuroScape projector.

**Why this priority**: Once the cross-conference backdrop exists,
visitors will want to "open the dot" — clicking through to read a
1999–2023 paper they spotted near an OHBM 2026 abstract is the obvious
follow-up. Without this story the backdrop is a picture but not an
entry point.

**Independent Test**: Deploy the build and visit `/neuroscape/`.
Search for a known PubMed neuroscience term whose title contains
"hippocampus" ("Place cell representations in the hippocampus"),
open the first result, confirm the detail page renders the locally
stored fields immediately AND fetches + renders the PubMed body
(authors, journal, abstract text, DOI) within the FR-019b budget.
Disable the network and reopen — local fields still render; the body
area shows the offline error state described in Edge Cases. Lasso a
cluster on the home scatter and confirm the result list is filtered
to articles inside that cluster.

**Acceptance Scenarios**:

1. **Given** a visitor is on the cross-conference atlas landing page,
   **When** they click "Browse the NeuroScape PubMed atlas →", **Then**
   they land on `/neuroscape/` with a layout that is visually and
   interactionally consistent with `/ohbm2026/` but reading the
   NeuroScape parquet.
2. **Given** the NeuroScape home page, **When** the visitor enters
   `cluster:<id_or_title> hippocampus` in the search bar, **Then** the
   results are restricted to articles whose **title** matches and
   whose tagged cluster matches the operator argument. (Search runs
   over titles only — body text is not in the local search index.)
3. **Given** any NeuroScape search result, **When** the visitor opens
   an article, **Then** the detail URL is a stable, shareable
   permalink under `/neuroscape/abstract/<pubmed_id>/`; the page
   first paints with the local fields (title, year, cluster info,
   neighbour list) and a body-skeleton, then fetches the PubMed body
   from NCBI E-utilities and re-paints the body region. A
   "Show on atlas" action is present.
4. **Given** the NeuroScape detail page, **When** the visitor clicks a
   neighbour, **Then** the new detail page loads via the same
   permalink scheme without losing the back-button trail. The new
   page reuses the in-memory body cache when the neighbour has been
   visited earlier in the same session.

---

### User Story 4 — Reproducible build of the three-parquet data package (Priority: P1)

A maintainer can rebuild the entire NeuroScape-context data package
from documented inputs with a single `ohbmcli` invocation. The build:

1. Reads the locally cached NeuroScape v1.0.1 release (DomainEmbeddings
   HDF5 shards + article/cluster CSVs + `domain_embedding_model.pth`) —
   same inputs `scripts/derive_neuroscape_centroids.py` uses today.
2. Fits a UMAP solution (one 2D and one 3D) on the NeuroScape Stage-2
   vectors, with a deterministic seed and documented neighbour /
   min-dist / metric configuration.
3. Projects every OHBM 2026 abstract — using the existing
   `voyage_stage2_published` recipe (Voyage embedding → published
   NeuroScape Stage-2 transform) — into the same UMAP solution.
4. Renames the existing `data.parquet` to `ohbm2026.parquet`
   (upstream-rename + downstream-pointer change for `/ohbm2026/`,
   identical schema and content).
5. Writes `neuroscape.parquet`: full 1999–2023 NeuroScape corpus,
   one row per PubMed article, with **only** `pubmed_id`, `title`,
   `year`, `cluster_id`, `umap_2d`, `umap_3d`, and precomputed
   nearest-neighbour `pubmed_id` lists; plus the cluster-table row
   group; plus a title-only typo-tolerant lexical search index.
   Authors, journal, abstract text, and DOI are **not** persisted —
   the subsite fetches them on demand from NCBI E-utilities at view
   time.
6. Writes `atlas.parquet`: the cross-conference root page's
   scatter + cluster colour table + per-point pointers (PubMed id /
   OHBM 2026 poster id) into `neuroscape.parquet` and `ohbm2026.parquet`
   respectively. This file does NOT duplicate abstract bodies; clicking
   a point fetches detail from the appropriate sibling parquet.
7. Emits a single provenance file
   `data/provenance/neuroscape_context_provenance__<state-key>.json`
   naming every input, the model checkpoint SHA, the UMAP seed/params,
   the Voyage bundle id, the centroid table version, the code revision,
   the command line, and per-input SHAs.

**Why this priority**: Without this story the cross-conference atlas
landing page is a one-off screenshot. With it the maintainer can refresh
the package when 2026 abstracts change (e.g. late withdrawals) or apply
the same pipeline to a future conference year. Stories 1–3 cannot ship
without the artefacts this story produces.

**Independent Test**: From a clean clone with `.venv` and the NeuroScape
v1.0.1 release pre-downloaded under `data/inputs/neuroscape-source/`,
run the documented one-shot command and confirm that all three parquet
files validate against the LinkML schema, the provenance file contains
every required field, and a downstream rebuild of the SvelteKit site
picks them up.

**Acceptance Scenarios**:

1. **Given** the documented inputs are in place, **When** the maintainer
   runs the rebuild command, **Then** the run is fully resumable: a
   second invocation skips already-computed cache entries (UMAP fit and
   per-abstract projections) and produces byte-identical output
   parquets for unchanged inputs.
2. **Given** the rebuild has finished, **When** the maintainer inspects
   the three parquets, **Then** each one carries a `build_info` block
   whose `state_key` is derived from its specific input set, **and**
   `atlas.parquet`'s `build_info` records the state-keys of the two
   sibling parquets it points into so cross-parquet drift is detectable.
3. **Given** a NeuroScape input checksum has changed since the last
   build, **When** the maintainer reruns the command, **Then** the
   pipeline surfaces a precise error naming the file and old/new SHA
   and refuses to silently mix old and new vectors.
4. **Given** the rebuild has finished, **When** the maintainer compares
   the new `ohbm2026.parquet` against the previous `data.parquet`,
   **Then** the row count, column set, and per-row body content are
   byte-identical (the rename is purely cosmetic / namespacing).

---

### Edge Cases

- **OHBM 2026 abstract has no Voyage embedding yet** (e.g. enrichment
  not finished for a given record): exclude it from the overlay with a
  counted, named omission in the provenance file; the landing-page UI
  MUST not render a missing point at NaN coordinates.
- **NeuroScape article has no cluster assignment** in the upstream CSV:
  exclude it from the scatter and the subsite; never silently coerce to
  an "Unknown" cluster.
- **Cluster count is large (175 today)**: the legend MUST be searchable
  / collapsible and the colour palette MUST be visually distinguishable
  for the top-N most-populated clusters; remaining clusters fall back to
  a documented secondary palette.
- **Backdrop is too dense** at default zoom: provide a backdrop
  opacity / density control so the OHBM 2026 overlay stays readable;
  defaults must remain readable without user intervention.
- **Subsite search returns zero hits**: surface a clear empty state and
  preserve the active facet selection so the user can broaden the
  query.
- **Visitor lands directly on a NeuroScape permalink** that no longer
  exists (PubMed ID retired): return a styled 404 consistent with the
  `/ohbm2026/` 404 behaviour.
- **`atlas.parquet` references a state-key that is no longer in
  `ohbm2026.parquet` or `neuroscape.parquet`** (e.g. operator forgot to
  upload all three together): the landing-page loader MUST surface a
  precise error naming the missing/stale sibling and refuse to render a
  silently-partial scatter.
- **NeuroScape input release upgraded** (e.g. v1.0.2 ships with more
  clusters): the build MUST refuse to mix old centroid table version
  with new vectors; the package's `state_key` changes deterministically
  and the deploy picks up the new manifest atomically.
- **Old bookmark to `/`** (today's redirect): the new page replaces the
  redirect; visitors land on the atlas landing page rather than being
  bounced. No URL is preserved beyond the bare root itself.
- **Slow / mobile devices** open the landing page: the combined view
  MUST default to a pre-decimated backdrop (e.g. ≤50K points) and offer
  a "Show full atlas" affordance for desktop visitors who want full
  density.
- **NCBI E-utilities is unreachable or returns 5xx** when a visitor
  opens a `/neuroscape/abstract/<pubmed_id>/` page: the local-field
  region MUST still render (title, year, cluster info, neighbour
  list); the body region MUST show a clear offline / error state with
  an "Open on pubmed.gov →" CTA and a Retry button; the page MUST
  NOT show a blank or NaN region.
- **NCBI E-utilities rate-limits a burst of fetches** (e.g. visitor
  rapidly clicks through 10 neighbour cards): the subsite MUST queue
  + retry with exponential backoff, surfacing a transient banner
  ("Fetching from PubMed — slow connection"), and MUST NOT block the
  local-field rendering of any page.

## Requirements *(mandatory)*

### Functional Requirements

#### Data ingest, projection, and packaging

- **FR-001**: The pipeline MUST consume the NeuroScape v1.0.1 release
  (DomainEmbeddings HDF5 shards + `neuroscience_articles_*.csv` +
  `neuroscience_clusters_*.csv` + `domain_embedding_model.pth`) from a
  gitignored input path under `data/inputs/`, reusing the existing
  centroid-derivation conventions.
- **FR-002**: The pipeline MUST produce a deterministic 3D UMAP and a
  deterministic 2D UMAP of the NeuroScape Stage-2 vectors with a
  documented seed and neighbour / min-dist / metric configuration; the
  parameters live in the spec/plan and the provenance file, not in
  ad-hoc script defaults.
- **FR-003**: The pipeline MUST project every OHBM 2026 abstract that
  has a valid `voyage_stage2_published` recipe vector into the same
  UMAP solution; abstracts without that vector are omitted and the
  omission is recorded by id in the provenance file.
- **FR-004**: The pipeline MUST carry every NeuroScape article's
  cluster id, cluster title, cluster description, cluster keywords, and
  cluster focus into `neuroscape.parquet` and `atlas.parquet` so the UI
  can render legends and tooltips without further lookups.
- **FR-005**: The pipeline MUST be idempotent and resumable: a second
  run with unchanged inputs MUST produce byte-identical output parquets
  and a cache-hit count equal to the cache-entry count.
- **FR-006**: The pipeline MUST emit exactly three parquet files —
  `ohbm2026.parquet` (renamed from `data.parquet`), `neuroscape.parquet`
  (full 1999–2023 corpus), and `atlas.parquet` (cross-connector for the
  bare-root landing page) — and MUST NOT duplicate abstract bodies in
  `atlas.parquet`; the cross-connector references rows in the two
  sibling parquets by stable id.
- **FR-007**: `atlas.parquet` MUST embed the state-keys of the
  `ohbm2026.parquet` and `neuroscape.parquet` it was built against, so
  drift between the three artefacts is detectable at load time.

#### UI — bare-root cross-conference atlas landing page

- **FR-008**: The bare root `/` MUST serve a cross-conference atlas
  landing page; the existing meta-refresh redirect island
  (`site/conference-root-redirect/`) MUST be retired in this change.
- **FR-009**: The landing page MUST expose a single binary toggle
  "Show OHBM 2026 overlay" (default: on) that flips between (a) the
  NeuroScape backdrop alone and (b) the NeuroScape backdrop + OHBM
  2026 overlay; the toggle state MUST persist across reloads via a
  `localStorage`-backed store. The landing page MUST NOT expose an
  "OHBM 2026 only" mode — visitors who want OHBM-only browsing follow
  the "Browse OHBM 2026 abstracts →" header link into `/ohbm2026/`.
- **FR-010**: The landing page MUST render NeuroScape points colour-
  coded by cluster category with a legend that shows the cluster title
  and supports hide/show per cluster.
- **FR-011**: The landing page MUST render OHBM 2026 points as a
  visually distinct foreground layer (larger glyph, outlined, higher
  z-order).
- **FR-012**: The landing page MUST expose a 2D/3D dimensionality
  control; switching dimensionality MUST preserve the active mode,
  cluster filter, and any active lasso selection.
- **FR-013**: The landing page MUST expose a backdrop density /
  opacity control with a default chosen so OHBM 2026 points remain
  readable without user intervention.
- **FR-014**: The landing page MUST expose two prominent header links
  — "Browse OHBM 2026 abstracts →" → `/ohbm2026/` and "Browse the
  NeuroScape PubMed atlas →" → `/neuroscape/`.
- **FR-015**: Clicking a point on the landing page MUST open a slide-
  in detail panel that shows the same fields as the corresponding
  sibling subsite's detail page (title, year, journal, abstract,
  PubMed/DOI links, cluster info for NeuroScape; title, poster id,
  authors, brief preview, nearest cluster for OHBM 2026), plus an
  "Open on `<subsite>` →" deep link to the canonical permalink on
  `/ohbm2026/abstract/<id>/` or `/neuroscape/abstract/<pubmed_id>/`.
  Lasso selection MUST produce a grouped result list split into
  "OHBM 2026" and "NeuroScape PubMed" with per-group counts; each
  entry MUST link through to the corresponding sibling subsite's
  detail page.
- **FR-015a**: The landing page MUST NOT expose a text search bar.
  Cross-corpus text search is out of scope for `atlas.parquet`;
  visitors who want text search follow the appropriate header link
  into `/ohbm2026/` or `/neuroscape/`.

#### UI — `/neuroscape/` subsite

- **FR-016**: A sibling subsite MUST be served at `/neuroscape/` under
  the same gh-pages deploy. It MUST reuse the OHBM 2026 site's
  SvelteKit codebase and component library; the build MUST NOT fork
  the SvelteKit project.
- **FR-017**: The NeuroScape home page MUST show the 2D/3D NeuroScape
  scatter coloured by cluster, with the same hover / lasso / facet
  interactions as the cross-conference landing page but reading only
  `neuroscape.parquet`.
- **FR-018**: NeuroScape search MUST support typo-tolerant lexical
  search over **titles** (locally stored) and faceted filtering by
  cluster id / cluster title / publication year. Abstract-text /
  full-body search is out of scope for Stage 15; it lands with the
  deferred semantic-search phase (assumptions).
- **FR-019**: Each PubMed abstract MUST be reachable at a stable
  permalink `/neuroscape/abstract/<pubmed_id>/`. The detail page MUST
  list locally stored fields (title, year, cluster title +
  description + keywords + focus, the nearest-neighbour articles, a
  PubMed permalink). Authors, journal, full abstract text, and DOI
  MUST be fetched at view time from NCBI E-utilities (efetch /
  esummary) and rendered into the body region of the page.
- **FR-019a**: The runtime PubMed fetch MUST:
  - use NCBI E-utilities `efetch.fcgi` (returns abstract + authors +
    journal + DOI in a single round-trip per pubmed_id);
  - respect NCBI's documented rate limit (3 req/s anon, 10 req/s
    with `VITE_NCBI_API_KEY` when set);
  - cache successful responses in-memory for the session (Map<pubmed_id,
    fetched_record>) so re-visiting an article does not re-fetch;
  - on transient failure (5xx, network), retry up to 3 times with
    exponential backoff before surfacing the error UI.
- **FR-019b**: The detail page MUST first-paint the local fields in
  under 200 ms (local parquet read is in-memory) and complete the
  body fetch + render in under 3 s on a recent laptop over a warm
  network. The local-field region is independent of the body region —
  any body fetch failure MUST NOT delay or block local-field paint.
- **FR-020**: The NeuroScape detail page MUST offer a "Show on atlas"
  action that returns the user to the NeuroScape home page with the
  article focused and its cluster legend entry highlighted.
- **FR-021**: The NeuroScape subsite MUST link back to the
  cross-conference atlas landing page (`/`) and to `/ohbm2026/` in the
  same nav region.

#### Cross-cutting

- **FR-022**: The existing `/ohbm2026/` SvelteKit site MUST NOT be
  modified by this feature beyond updating the data-loader path from
  `data.parquet` to `ohbm2026.parquet`. No routes, components,
  fixtures, behaviours, or visible content on `/ohbm2026/` change.
- **FR-023**: Every parquet emitted by this feature MUST carry a
  `build_info` block identical in shape to the existing OHBM 2026
  package's build_info (state-key, code revision, command line,
  bundle, seed); `atlas.parquet`'s build_info additionally embeds the
  sibling-parquet state-keys per FR-007.
- **FR-024**: Every **non-PubMed-record** external link in the new UI
  surfaces (NeuroScape citation, NeuroScape Zenodo release, OHBM 2026
  site, cross-conference landing page, NCBI E-utilities base URL)
  MUST be link-checked at build time; any failure MUST block the
  deploy. **Per-PubMed-record** URLs (`pubmed.ncbi.nlm.nih.gov/<id>/`,
  per-article DOIs) are NOT pre-checked at build time — 600K HEAD
  requests is infeasible against NCBI's rate limits, and the runtime
  fetch (FR-019a) surfaces dead records at view time with the offline
  error state from Edge Cases.
- **FR-025**: The cross-conference landing page's first paint MUST
  stay within today's Stage-6 performance budget for the OHBM 2026
  home page (initial map render ≤5s on a recent laptop over a warm
  cache), using pre-decimation if necessary on mobile / slow devices.
- **FR-026**: All errors in the new ingest / projection / packaging
  pipeline (input schema mismatch, missing checkpoint, UMAP failure,
  missing OHBM 2026 vector, cross-parquet state-key drift, link-check
  failure) MUST surface as typed exceptions with precise context
  (file, id, expected vs actual) — never silent skips or NaN
  coordinates.

### Key Entities

- **NeuroScape article**: a PubMed abstract from the 1999–2023
  NeuroScape release. **Locally persisted** attributes (in
  `neuroscape.parquet`): pubmed id, title, year, cluster id, 2D UMAP
  coordinates, 3D UMAP coordinates, precomputed nearest-neighbour
  pubmed ids. **Fetched at view time** from NCBI E-utilities:
  authors, journal, abstract text, DOI.
- **NeuroScape cluster**: one of 175 upstream clusters. Attributes:
  cluster id, title, description, keywords, focus, colour (assigned at
  build time), backdrop point count. Persisted in both
  `neuroscape.parquet` and `atlas.parquet`.
- **OHBM 2026 abstract projection**: a single OHBM 2026 abstract's
  position in the NeuroScape UMAP space. Attributes: submission id,
  poster id (stable identifier), source bundle id
  (`voyage_stage2_published`), 2D UMAP coordinates, 3D UMAP
  coordinates, nearest NeuroScape cluster id. Persisted in
  `atlas.parquet`; the full OHBM 2026 abstract body remains in
  `ohbm2026.parquet`.
- **Atlas UMAP model**: a fitted UMAP solution. Attributes: seed,
  neighbours, min-dist, metric, dimension (2 or 3), input vector source
  (NeuroScape Stage-2), centroid table version.
- **Atlas data package**: the three-parquet artefact set —
  `ohbm2026.parquet` (renamed), `neuroscape.parquet`, `atlas.parquet`
  — plus a single provenance JSON file. `atlas.parquet` is the only
  one read by the bare-root landing page; the two sibling parquets are
  read by their respective subsites.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python execution for this feature MUST use the
  repository-local `.venv/bin/python` interpreter or `uv` targeting it.
  The rebuild command, any one-off `derive_*` scripts, and the tests
  added by US4 follow this rule exactly.
- **CA-002**: Tests/verification steps added before implementation:
  - US1: Vitest unit tests for the landing-page mode store, Playwright
    e2e that asserts the bare root no longer redirects and renders the
    combined scatter; Playwright assertion on the two outbound subsite
    links.
  - US2: Vitest + Playwright for the 2D/3D switch on the landing page
    and the NeuroScape subsite home.
  - US3: Playwright e2e covering NeuroScape home → search → detail →
    "Show on atlas" round-trip; unit test on the
    `/neuroscape/abstract/<pubmed_id>/` permalink parser.
  - US4: Python `unittest` modules covering (a) deterministic UMAP fit
    → byte-identical vectors, (b) per-abstract projection cache key,
    (c) provenance schema, (d) all four typed exception classes for
    FR-026, and (e) byte-identical rename `data.parquet → ohbm2026.parquet`
    for FR-022.
- **CA-003**: Docs updated in the same change: `README.md` (new
  rebuild command, new subsite URL, parquet-naming rename),
  `docs/reproducibility-vision.md` (new artefact roots),
  `CLAUDE.md` (artifact layout contract section for the three-parquet
  package and the bare-root atlas page).
- **CA-004**: No new credentials are required. Voyage / OpenAI keys
  already documented in `.env` continue to gate Stage-3 embedding
  rebuilds; this feature itself reads only already-cached Voyage
  vectors and the local NeuroScape release files.
- **CA-005**: All new datasets land under gitignored roots:
  `data/inputs/neuroscape-source/` (operator-supplied release files),
  `data/outputs/embeddings/neuroscape/<state-key>/` for the UMAP fit
  artefacts, and a single canonical staging directory for the three
  publishable parquets (e.g. `data/outputs/parquets/<state-key>/`)
  containing `ohbm2026.parquet`, `neuroscape.parquet`, and
  `atlas.parquet`. These join the existing gitignore entries; the
  spec does NOT propose tracking generated data.
- **CA-006**: Error paths are explicit per FR-026. The build's exit
  code is non-zero on any error; the GitHub Actions deploy job fails
  rather than publishing partial data. Bare `except:` regressions are
  caught by the existing constitution lint.
- **CA-007**: The build MUST discover the NeuroScape centroid table
  version, the HDF5 shard manifest, and the cluster CSV columns at
  runtime via the same conventions
  `scripts/derive_neuroscape_centroids.py` already uses (SHA-checked
  shard manifest + centroid-table-version stamp). Cluster counts and
  shard counts MUST be read from discovered files and surfaced as
  precise errors if they change.
- **CA-008**: Every parquet reaching the UI MUST carry a `build_info`
  block (FR-023), and a single
  `data/provenance/neuroscape_context_provenance__<state-key>.json`
  MUST sit alongside the staging directory naming the corpus
  state-key, centroid table version, UMAP params, code revision,
  command, Voyage embedding bundle id, OHBM 2026 inclusion / omission
  counts, per-input SHAs, and the state-keys of the three published
  parquets. Paths inside provenance use repo-relative form — never
  absolute or `$HOME`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time visitor at the bare root `/` can toggle
  the OHBM 2026 overlay off and on and identify the cluster that the
  densest OHBM 2026 region belongs to in under 30 seconds, with no
  prior instruction.
- **SC-002**: ≥95% of OHBM 2026 abstracts with a
  `voyage_stage2_published` vector are visible in the overlay; the
  remaining ≤5% are listed by id in the provenance file with the
  reason for omission.
- **SC-003**: The cross-conference landing page paints its first
  frame in ≤5 seconds on a recent laptop on a warm cache and remains
  interactive (drag rotate / lasso) at ≥30 frames per second on the
  default decimated backdrop.
- **SC-004**: From a clean clone with the NeuroScape release on
  disk, the documented one-shot rebuild command completes successfully
  on a recent laptop without manual intervention, and a second
  invocation exits in under 60 seconds via cache hits with
  byte-identical output parquets.
- **SC-005**: A NeuroScape subsite visitor can go from an arbitrary
  search query to a PubMed abstract detail page in ≤3 clicks, and the
  resulting URL is a stable, shareable permalink at
  `/neuroscape/abstract/<pubmed_id>/`.
- **SC-006**: Every **non-PubMed-record** external link rendered by
  the new surfaces (NeuroScape citation, NeuroScape Zenodo release,
  OHBM 2026 site, cross-conference landing page, NCBI E-utilities
  base URL) returns a 2xx at build time; the deploy is blocked
  otherwise. Per-PubMed-record URL health is enforced at view time,
  not build time, per FR-024.
- **SC-007**: The cross-conference landing page on a mid-range mobile
  device loads within 10 seconds and the device does not exhaust
  memory at the default decimated backdrop.
- **SC-008**: The existing `/ohbm2026/` site is byte-identical (modulo
  the data-loader path string `data.parquet → ohbm2026.parquet`)
  before and after this change; an automated diff between the
  pre-change and post-change build outputs of `/ohbm2026/` returns no
  unintended deltas.

## Assumptions

- The NeuroScape v1.0.1 release (DomainEmbeddings shards + cluster /
  article CSVs + `domain_embedding_model.pth`) is already downloaded
  to an operator-supplied path under `data/inputs/` for the maintainer
  running the rebuild; this feature does not re-host or redistribute
  it.
- The published NeuroScape Stage-2 model (`stage2_model.pth`,
  SHA `8a8e6931…`) is the canonical embedding for projecting OHBM
  2026 abstracts; the existing `voyage_stage2_published` recipe
  already applies it on top of Voyage Stage-1 vectors.
- 175 NeuroScape clusters today, on the order of 600K backdrop points,
  ≤5K OHBM 2026 overlay points. Defaults (decimation, palette size)
  are chosen for this order of magnitude; the build refuses to
  silently proceed if the cluster count changes (CA-007).
- The NeuroScape subsite is a build-time mirror of the canonical
  NeuroScape data, not a live database; it does not need to refresh
  more often than the upstream release.
- The new bare-root landing page is built from the existing OHBM 2026
  SvelteKit codebase (no new framework, no new hosting target). The
  Stage 9 root-redirect island is retired by this feature.
- Mobile-class devices receive a pre-decimated backdrop by default to
  keep the landing page interactive; the "Show full atlas" affordance
  is desktop-only behaviour.
- Cross-conference linking beyond OHBM 2026 ↔ NeuroScape (e.g. SfN,
  CCN) is explicitly out of scope; the three-parquet layout
  generalises to additional conferences in the future but no second
  conference is included in this feature.
- Visitors viewing `/neuroscape/abstract/<pubmed_id>/` pages MUST
  have a network connection; the runtime PubMed fetch is the
  authoritative source of body text. Offline visitors see the local
  fields (title, year, cluster, neighbours) and an explicit offline
  error state for the body region — they are NOT promised a fully
  offline reading experience for NeuroScape articles.
- Semantic search on `/neuroscape/` (MiniLM → NeuroScape Stage-2
  projector) is **explicitly deferred** to a sibling stage. Stage 15
  ships lexical-on-titles only; the spec for the deferred work is
  not opened in this feature. Visitors during the Stage-15 window
  experience the search bar as title-lexical-only.
- Search semantics on the NeuroScape subsite reuse the
  `cluster:<id_or_title>` and `id:<pubmed_id>` operator conventions
  introduced in Stage 14; no new operator grammar is proposed here.
- The serving-side rename `data.parquet → ohbm2026.parquet` is a
  pure pointer change in the `/ohbm2026/` data loader and a publish
  step in the deploy workflow; it does not require regenerating the
  underlying OHBM 2026 data.
