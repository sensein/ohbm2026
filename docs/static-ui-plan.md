# OHBM 2026 Static Search UI Plan

## Goal

Build a standalone static web UI that lets neuroimagers and neuroscientists:

1. search the OHBM 2026 abstract corpus by relevance,
2. filter quickly through facets such as topic, modality, methods, keywords, and presentation type,
3. inspect semantic relations between abstracts,
4. browse cluster/topic structure derived from the existing embedding and semantic-analysis outputs,
5. deploy the whole UI as a static site with no required backend.

This branch starts that work from the existing corpus and analysis artifacts already generated in this repository.

## Constraints

- deployment target is a static host
- the UI must not depend on a live API
- search and relations should be backed by precomputed local data products
- the interface should be usable by domain scientists, not just technical users
- the data contract should be reproducible from the current pipeline outputs

## Existing Inputs To Reuse

- `data/abstracts.json`
  - raw title, accepted-for status, question/response content, figure metadata, primary topic, keywords
- `data/abstracts_enriched.json`
  - markdown sections, figure analysis fields, figure keywords
- `data/reference_metadata.json`
  - external citation matches and reference metadata
- `data/embeddings/*`
  - stage-one bundles across MiniLM, PubMedBERT, OpenAI, Voyage
- `data/embeddings/voyage_stage2_published/`
  - published-stage2 vectors for the default Voyage field set
- `data/embeddings/voyage_stage2_published/semantic_analysis/`
  - coarse 2-cluster solution
- `data/embeddings/voyage_stage2_published/semantic_analysis_15-communities/`
  - mid-granularity semantic partition
- `data/embeddings/voyage_stage2_published/semantic_analysis_21-communities/`
  - finer semantic partition

## Proposed Product Shape

### User-facing views

1. Search view
   - query box
   - relevance-ranked results
   - facet panel
   - quick filters for common neuroscientific concerns

2. Abstract detail view
   - title and accepted-for
   - markdown sections
   - content-related metadata
   - figure analysis summary
   - external references summary
   - related abstracts panel

3. Relations view
   - nearest-neighbor list
   - cluster membership for one or more semantic partitions
   - local “more like this” exploration
   - optional projection view hookup later

4. Topic browse view
   - browse by primary topic
   - browse by semantic cluster labels
   - browse by extracted keywords

### Static architecture

- build a compact public data bundle from local JSON outputs
- serve a fully static client bundle
- do client-side filtering and ranking
- optionally use web workers for search/index loading if the bundle size requires it

## Recommended Technical Direction

### Frontend

- Vite + React + TypeScript
- static build output to `dist/`
- no SSR requirement

### Search

- client-side full-text index
- recommended first choice: `MiniSearch`
- fallback: `FlexSearch` if bundle size or ranking control becomes a problem

### State and URL model

- route state encoded in the URL
- shareable search URLs
- persistent facets in query params

### Styling

- preserve an intentional scientific/research-tool aesthetic
- fast scanning over marketing style
- light visual chrome, strong typography, dense information layout

## Data Model For The UI

Create a build step that emits a UI-focused normalized dataset, for example:

- `public/data/abstracts.search.json`
  - minimal search documents
- `public/data/abstracts.detail.json`
  - full detail payloads keyed by abstract ID
- `public/data/facets.json`
  - all facet buckets and counts
- `public/data/relations.json`
  - nearest neighbors and semantic-cluster memberships
- `public/data/clusters.json`
  - labels, keywords, sizes, representative abstracts for chosen semantic partitions
- `public/data/manifest.json`
  - metadata about corpus version, embedding source, build date, and selected partitions

### Search document fields

- `id`
- `title`
- `accepted_for`
- `primary_topic`
- `keywords`
- `figure_keywords`
- `introduction_markdown`
- `methods_markdown`
- `results_markdown`
- `conclusion_markdown`
- `additional_content_questions_markdown`

### Relation fields

- nearest-neighbor IDs from the selected embedding bundle
- cluster IDs for:
  - 15-community solution
  - 21-community solution
- cluster labels and keywords
- optional similarity scores if already available or cheaply computable in the build step

## Relevance Strategy

Start simple and deterministic:

1. lexical search over title + section text + keywords
2. field boosts:
   - title highest
   - keywords high
   - results and conclusion medium-high
   - methods medium
3. optional relation-aware reranking:
   - for “similar abstract” interactions, use precomputed nearest neighbors instead of live vector search

Current implementation also adds an optional browser-side semantic mode:

- query embedding generated in-browser with `Xenova/all-MiniLM-L6-v2`
- ranking against pre-exported normalized MiniLM abstract vectors
- no backend required, but the browser must be able to download the model from the public CDN/Hugging Face path

## Facets To Expose First

- accepted-for
- primary topic
- raw keywords
- figure keywords
- imaging methods
- task vs resting-state
- healthy subjects vs patients
- field strength
- processing packages
- species
- recording technology
- brain regions
- brain networks
- semantic cluster 15
- semantic cluster 21

The first ten are now implemented in the static exporter and UI. The domain-specific categories are heuristically extracted from title, methods, results, and additional content fields.

## Semantic Partition Recommendation

Use both current published-stage2 semantic partitions:

- 15-community solution
  - useful for broader navigation
- 21-community solution
  - useful for finer topic discovery

The UI should allow switching the cluster layer instead of forcing one partition.

## Implementation Tasks

### Task 1: Define the public UI data contract

Status:

- completed

Work:

- choose the exact normalized output schemas for search, detail, facets, relations, and cluster summaries
- decide which fields are duplicated for speed and which remain keyed by ID
- choose the primary embedding/cluster source for v1

Validation:

- document the schema in code and in this plan
- confirm every `abstract_id` in the UI bundle maps back to one source abstract
- confirm chosen cluster partitions cover all abstracts
- confirm the bundle excludes unnecessary raw admin metadata

### Task 2: Build a reproducible UI export pipeline

Status:

- completed

Work:

- add a CLI/build step that transforms the current corpus outputs into UI-ready static JSON
- include manifest metadata with source bundle names and partition names
- produce deterministic sorted outputs

Validation:

- rerunning the export with unchanged inputs should produce stable file contents
- counts in the UI export should match source counts
- all relation IDs should resolve to exported abstracts
- export generation should complete without network access

### Task 3: Scaffold the standalone frontend app

Status:

- completed

Work:

- add a new `ui/` app or equivalent standalone frontend package
- configure static build
- set up routing, shell layout, and shared data-loading layer

Validation:

- local build succeeds
- static preview opens without runtime API calls
- route refresh works on static hosting assumptions

### Task 4: Implement result ranking and search UX

Status:

- partially completed

Work:

- build the full-text index from UI export data
- add ranked search results
- add result snippets and highlighting
- add keyboard-friendly search interactions

Validation:

- empty query yields a sensible browse mode
- exact title queries return the expected abstract near the top
- common domain terms like `fMRI`, `TMS`, `connectivity`, `pain`, `aging` return relevant results
- search state is reflected in the URL

Implemented now:

- lexical search with AND semantics by default
- quoted phrase search
- explicit `OR`
- `-term` exclusion
- URL-synced search mode and query state
- browser-side semantic query ranking

### Task 5: Implement faceted filtering

Status:

- completed for the initial facet set and the new neuroimaging-derived facet groups

Work:

- add multi-select facets
- support intersecting filters with search queries
- expose cluster facets for both 15 and 21 partitions
- show active filters and clear/reset behavior

Validation:

- facet counts update correctly after filters
- multi-facet intersections reduce result sets deterministically
- switching cluster layers changes the facet space without breaking selected abstract views
- browser back/forward preserves filter state

### Task 6: Build the abstract detail page

Status:

- completed for the current static UI

Work:

- render markdown sections cleanly
- show key metadata chips
- show figure analysis and figure keywords when available
- summarize external references and matches

Validation:

- detail page works for abstracts with and without figures
- markdown renders lists and links correctly
- figure analysis sections fail gracefully when absent
- all detail links are stable and shareable

### Task 7: Add relations and topic exploration

Status:

- completed for nearest neighbors and 15/21 cluster switching; browse-first cluster landing pages are still a follow-up

Work:

- show nearest neighbors for each abstract
- show cluster membership and representative cluster summaries
- add browse-by-cluster and browse-by-topic entry points

Validation:

- every abstract has a relations panel or explicit “no relations available” state
- nearest-neighbor links resolve correctly
- cluster browse pages show representative abstracts and cluster labels
- the same abstract can be inspected under both 15- and 21-cluster lenses

### Task 8: Performance and bundle control

Status:

- partially completed

Work:

- measure payload sizes
- split data files if needed
- lazy-load detail payloads and cluster metadata
- consider web-worker indexing if search startup is too slow

Validation:

- initial load remains acceptable on a laptop browser
- search becomes interactive quickly after app load
- no single static JSON file becomes unreasonably large for the chosen host

### Task 9: Accessibility and scientific usability pass

Status:

- pending

Work:

- keyboard navigation
- color-contrast checks
- screen-reader labels for filters and results
- domain-language review for labels and facet names

Validation:

- tab order is coherent
- form controls are labeled
- color is not the only carrier of meaning
- dense views remain readable on laptop-width screens

### Task 10: Static deployment packaging

Status:

- partially completed

Work:

- produce static build artifacts
- document how to publish on GitHub Pages, Netlify, or similar
- document how to regenerate the UI data bundle from local corpus outputs

Validation:

- clean build from repo checkout to static output
- no hidden local-path dependencies
- a static preview command works end to end

## Validation Milestones

### Milestone A: Data export ready

Pass when:

- UI export files build locally
- schema is stable
- counts align with source corpus

### Milestone B: Search and detail ready

Pass when:

- title and keyword search work
- results are linkable
- detail pages render markdown and metadata correctly

### Milestone C: Facets and relations ready

Pass when:

- multi-facet filtering works
- nearest neighbors and semantic cluster browsing work
- 15/21 cluster layers can be switched cleanly

### Milestone D: Static release candidate

Pass when:

- production build is static
- no runtime API calls are required
- documentation is sufficient for deployment and data refresh

## Recommended v1 Scope

Ship first:

- one static frontend
- one search index
- detail pages
- core facets
- nearest-neighbor relations
- 15- and 21-cluster browsing

Defer:

- live graph visualization
- in-browser embedding search
- user accounts or saved workspaces
- annotation/collaboration tooling
- figure gallery as a primary navigation surface

## Suggested Initial Task Order

1. define the UI export schema
2. build the export CLI
3. scaffold the static frontend
4. implement search + result list
5. add abstract detail pages
6. add facets
7. add relations and cluster browse views
8. optimize bundle size and polish accessibility

## Branch

Current implementation branch for this UI work:

- `codex/static-abstract-ui`
