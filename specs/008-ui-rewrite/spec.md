# Feature Specification: UI Rewrite — Static Search Site for the OHBM 2026 Corpus

**Feature Branch**: `008-ui-rewrite`
**Created**: 2026-05-17
**Status**: Draft
**Input**: User description: "Build the UI as a site served by GitHub Pages, built by a GitHub Action with PR-preview management. Replace the UI with a modern framework. Content: model selection (default = neuroscape, abstract); 2D + 3D UMAP with lasso selection on the 2D view; semantic + lexical search (with typo tolerance for lexical/author search); abstract details with extra questions limited to topics and methods; facets that update interactively from selection/search; an optional walkthrough for new users; an About page describing how the data were processed (for a general neuroscientist, with collapsible deep-dive details and verified references); a minimal data package that contains abstract details + model-configuration outputs; responsive on phone/tablet; abstracts keyed by poster id (not submission id), with author details restored; accepted abstracts only — no withdrawn; references open in a new tab; users can add search results to a shopping cart and open an email editor pre-populated with the cart contents."

## Clarifications

### Session 2026-05-17

- Q: Storage engine for the UI data package — DuckDB-WASM, static JSON shards, or a hybrid? → A: **Static JSON shards (no DuckDB-WASM).** At 3,244 abstracts × 15 (model, input) cells the entire dataset is ~9 MB gzipped, fits in client memory, and in-memory `Array.filter`/intersection runs in <10 ms. DuckDB-WASM's ~3.5 MB runtime overhead buys no measurable win at this scale and adds a WASM dependency the rest of the site doesn't need. The site is fully client-side static + per-shard CDN-cacheable JSON; facet aggregations are computed in JS over the in-memory abstract array; the schema is documented under FR-019.
- Q: Delivery sequencing + how preview URLs surface on a PR? → A: **Ship the deploy + PR-preview GitHub Actions in a small first PR (US8 first); use the GitHub Deployments / environment surface (top-of-PR Deployments box) rather than a bot comment in the conversation.** Rationale: once the workflows are merged, every subsequent PR for US1–US7 automatically gets a live preview at the top of the PR — reviewers can click "View deployment" without scrolling through commit history. The first PR ships a minimal placeholder site ("Stage 6 — under construction" + the empty data-package builder skeleton) so the preview is non-empty and the workflows are exercised end-to-end. See FR-021 + contracts/github-action.md for the environment-based deploy mechanism.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Find and read accepted-poster details from any device (Priority: P1) 🎯 MVP

A neuroscientist heading to OHBM 2026 lands on the site from a phone, tablet, or laptop. They search by keyword, author, or topic and read the full details of relevant accepted posters — including author names + affiliations and the canonical poster id assigned by the program. Withdrawn submissions are not surfaced anywhere.

**Why this priority**: This is the irreducible value the site offers. Without working search + abstract detail on every device, every other feature (UMAP, cart, walkthrough) is dressing on something nobody can actually consume.

**Independent Test**: From a fresh device, navigate to the site URL, search for a known abstract author or keyword, click into a result, and confirm the panel shows: title; poster id (formatted as the program assigned it, not as a submission id); ordered author list with affiliations; abstract sections (Introduction, Methods, Results, Conclusion); and "Topics" + "Methods" structured-question values. Verify no withdrawn abstracts appear in any list, search, or projection at any time.

**Acceptance Scenarios**:

1. **Given** a phone in portrait orientation, **When** the user opens the site and types `"connectivity"`, **Then** the search returns matching accepted abstracts within 1 second; each result card shows poster id, title, lead author + affiliation, primary topic; tapping a card opens the detail panel as a full-screen overlay readable without horizontal scrolling.
2. **Given** the corpus contains 3,244 accepted abstracts + ~166 withdrawn submissions, **When** the user performs any search, filter, or projection, **Then** zero withdrawn abstracts appear in any UI surface; the visible total never exceeds the accepted-only count.
3. **Given** an abstract whose poster id is `M-AM-101` and submission id is `49213`, **When** the user opens that abstract's detail panel, **Then** the panel header displays `M-AM-101` as the primary identifier; the submission id is not shown anywhere.
4. **Given** an abstract with 12 listed authors, **When** the user opens the detail panel, **Then** all 12 authors appear in submission order with their affiliations; mobile view collapses the list under a "show all 12 authors" toggle when it exceeds the viewport.

---

### User Story 2 — Explore the 2D semantic map with lasso selection (Priority: P2)

A reviewer wants to see the global structure of the accepted corpus. They open the 2D UMAP, pan/zoom, and lasso a region of dots to drill into a thematic cluster. The result list, facets, and details panel update to reflect the lasso selection. They can switch the underlying model (e.g., voyage abstract → neuroscape claims) to see how the layout changes.

**Why this priority**: The UMAP is the visual hook that distinguishes this site from a vanilla search interface. Lasso is the existing user gesture from the prior UI — preserving it keeps the muscle memory intact.

**Independent Test**: Open the projections panel, draw a lasso around 50–200 points on the 2D UMAP, confirm the result list shrinks to those points, the facet counts update accordingly, and clearing the lasso restores the full corpus. Then switch model from default `neuroscape / abstract` to `voyage / claims` and verify the point positions change while the lasso selection-by-id is preserved (the same abstracts stay selected; only their geometric positions move).

**Acceptance Scenarios**:

1. **Given** the user is on the 2D UMAP, **When** they drag a lasso around a cluster, **Then** the result count, facet counts, and detail-panel "selected" state all update within 500 ms; clearing the lasso returns the previous global state.
2. **Given** the user has selected `voyage / abstract` from the model dropdown, **When** they switch to `neuroscape / claims`, **Then** the 2D and 3D UMAPs re-render with the new model's coordinates; the lasso selection (by abstract id) persists.
3. **Given** the 3D UMAP is displayed, **When** the user interacts with it, **Then** the user can rotate, pan, and zoom; the 3D view does NOT support lasso (3D lasso is out of scope; only the 2D view supports it).

---

### User Story 3 — Semantic + lexical search with typo tolerance (Priority: P2)

A user types a search query. The system runs **both** a semantic match (a sentence embedding compared against the corpus) AND a lexical match (with typo tolerance) and merges results. Author search treats common name misspellings (e.g., one transposed letter, one missing letter) as matches.

**Why this priority**: Search quality is what distinguishes a useful site from a slow filter. Semantic + lexical together gives both "I know roughly what I'm looking for" and "I know the exact phrase / surname" coverage.

**Independent Test**: Type the query `"defautl mode netwrk"` (two typos) — confirm the lexical matcher still surfaces "default mode network" abstracts. Type the surname `"Smtih"` (1 transposition) and verify abstracts by `"Smith"` appear in author search. Type a phrase that doesn't appear verbatim in any abstract (e.g., `"how the brain remembers faces"`) and confirm the semantic search surfaces face-memory-related abstracts.

**Acceptance Scenarios**:

1. **Given** the user types a 3+ character query, **When** the lexical search runs, **Then** matches within Damerau-Levenshtein distance 2 are surfaced for words ≥4 characters (1-edit for shorter words); typo-tolerance is on by default.
2. **Given** the user types text in the search box, **When** results appear, **Then** semantic-only matches are visually distinguished from lexical/exact matches (e.g., badge or section header), and the user can filter to "semantic only" / "lexical only" / "both".
3. **Given** the user types text into the author-search field, **When** results appear, **Then** the field tolerates 1 typo for short surnames (≤4 chars) and 2 typos for longer names; matching authors and their abstracts are returned.

---

### User Story 4 — Interactive facets that follow selection (Priority: P3)

A user filters by faceted dimensions (accepted-for, primary topic, secondary topic, keywords, methods, study type, population, field strength, processing packages, species, recording technology, brain regions, brain networks). When they apply a facet filter OR lasso a UMAP region OR run a search, the facet counts re-compute so that each remaining option reflects only what's reachable from the current selection.

**Why this priority**: Faceted exploration is how organizers + reviewers narrow down 3,244 abstracts to a manageable shortlist. The "facets update with selection" behavior is what separates a usable filter from a frustrating one.

**Independent Test**: Apply `Methods = fMRI` and confirm the `Species` facet now shows only species that appear in fMRI abstracts (e.g., Human × 1,840; Macaque × 24). Lasso a region of the UMAP and confirm the facet counts contract further. Clear filters and counts return to the corpus totals.

**Acceptance Scenarios**:

1. **Given** the user applies a facet filter, **When** the result list updates, **Then** every other facet's per-option count updates to reflect only the remaining reachable abstracts (combined-filter counts, not absolute).
2. **Given** the user has lassoed a UMAP region, **When** they then click a facet option, **Then** the result is the intersection (lasso ∩ facet); both visual surfaces (UMAP highlight + result list) reflect the intersection.

---

### User Story 5 — Save abstracts to a cart and email the list (Priority: P3)

A user finds 8 abstracts of interest while browsing. They click "add to my list" on each. The cart icon shows `8`. They click "email my list" — a system-native email composer opens (mail client launches with a pre-filled message) containing the list of poster ids + titles + per-abstract permalinks back to this site.

**Why this priority**: Reviewers + meeting planners frequently triage abstracts and want to share their picks with collaborators. Today they paste links into Slack/email by hand; the cart shortens that loop to one click.

**Independent Test**: Add 3 abstracts to the cart from different facet-filtered views, click "email my list", verify the OS mail composer opens with the body listing the 3 poster ids + titles + permalinks; the cart can be cleared or items removed individually before emailing.

**Acceptance Scenarios**:

1. **Given** the cart is empty, **When** the user clicks "add to list" on an abstract card, **Then** the cart badge increments to 1 and the abstract id is persisted across page reloads (within the same browser).
2. **Given** the cart has items, **When** the user clicks "email my list", **Then** the OS mail composer opens with a subject like `"OHBM 2026 — my abstracts (N)"` and a body containing one line per item: poster id, title, link back to the site's abstract anchor.
3. **Given** the user is on a mobile device, **When** they trigger "email my list", **Then** the mobile mail client launches (iOS Mail / Gmail / Outlook depending on default handler).

---

### User Story 6 — Optional guided walkthrough for first-time visitors (Priority: P4)

A first-time visitor lands and sees an unobtrusive "Take the tour" button. If they click it, an overlay walks them through the search box, the UMAP, the model selector, the facet sidebar, and the cart — each step highlighting the relevant UI element. If they ignore the button, nothing else nags them.

**Why this priority**: New visitors to a search UI with this much surface area get lost; existing UI feedback shows people miss the lasso + model selector. A skippable tour solves that without forcing onboarding on returning users.

**Independent Test**: Open the site in an incognito window, confirm the "Take the tour" call-to-action is visible but unobtrusive (small button or banner, dismissible). Click it; verify each step highlights the right region and a "next / previous / skip" UI is present. Reload the page after dismissing the tour; verify it doesn't auto-launch again unless the user explicitly clicks "restart tour".

**Acceptance Scenarios**:

1. **Given** the user has never visited the site, **When** they land on the home page, **Then** a "Take the tour" CTA is visible (e.g., header button or one-time banner) but no modal auto-opens.
2. **Given** the user clicks "Take the tour", **When** the tour runs, **Then** it visits ≥ 5 stops (search, model selector, UMAP, facets, cart) with clear "next / previous / skip" controls; the tour can be re-launched anytime from a "?" or "help" affordance.

---

### User Story 7 — About page with verified references for the data-processing methods (Priority: P4)

A general neuroscientist clicks "About" to understand how this corpus was built. They get a one-paragraph overview, then collapsible sections that drill into each stage (corpus ingestion → enrichment → embeddings → analysis & annotation). Each section's claims about methods cite verifiable references (textbook chapters, published methods papers, software docs). External reference links open in a new tab.

**Why this priority**: Without this, the site is opaque about its provenance — and reviewers + organizers need to trust the pipeline before they trust the rankings/clusters. Putting the explanation behind progressive disclosure keeps the front page focused on browsing while giving the deeper details to those who want them.

**Independent Test**: Open the About page, confirm the top section is readable in under 2 minutes by a non-specialist. Expand each collapsible deep-dive section and confirm every methods claim links to a real, accessible reference (e.g., UMAP paper, Leiden paper, HDBSCAN paper, NeuroScape paper, Voyage AI docs). Clicking any external link opens it in a new tab.

**Acceptance Scenarios**:

1. **Given** the user opens the About page, **When** they read the top section, **Then** the overview is ≤ 250 words and uses no jargon beyond "embedding", "cluster", and "UMAP" (each defined inline at first mention).
2. **Given** the user expands the "Embedding models" deep dive, **When** they click any reference link, **Then** the link points at a real reachable URL (no 404s; verified at build time) and opens in a new browser tab (`target="_blank"` + `rel="noopener noreferrer"`).
3. **Given** the deep dives cover Stages 1–4, **When** the user reads each, **Then** each stage references the canonical published method paper (corpus fetch: Oxford Abstracts GraphQL — vendor docs; figure interpretation: GPT-4-vision-class reference; claim extraction: the ECO ontology paper; references: OpenAlex; embeddings: model-card / paper for each of voyage / minilm / openai / pubmedbert / neuroscape; analysis: UMAP, Leiden CPM, HDBSCAN, FAISS; topics: BERTopic + spaCy).

---

### User Story 8 — Deploy continuously via GitHub Actions with per-PR previews (Priority: P5)

A maintainer pushes a PR that touches the UI or the data package. A GitHub Action builds the site and publishes a preview URL (e.g., `https://<org>.github.io/<repo>/pr-<N>/`) that's commented on the PR. When the PR merges, the action redeploys the main GitHub Pages site. When the PR closes (merged or not), the preview is cleaned up.

**Why this priority**: Without preview deploys, reviewers test changes locally — slow, error-prone, and inconsistent. Per-PR previews close the design-review loop in minutes.

**Independent Test**: Open a draft PR that changes a UI file; confirm within 10 minutes the **PR's Deployments box** (top-of-PR, NOT the conversation) shows a "View deployment" link for the `pr-preview-<N>` environment; click it and verify the change is live; close the PR; verify within an hour the Deployments box marks the deployment "Inactive" and the URL returns 404 (cleaned up). Merge a different PR to main; confirm the production site updates within 10 minutes of the merge.

**Acceptance Scenarios**:

1. **Given** a PR is opened, **When** the GitHub Action runs, **Then** the preview URL surfaces in the PR's **Deployments box** within 10 minutes (the workflow declares `environment: { name: pr-preview-<N>, url: ... }` so GitHub auto-creates the deployment entry); subsequent commits update the same environment URL in place (no environment churn, no conversation spam).
2. **Given** a PR is closed (merged or rejected), **When** the close event fires, **Then** the preview directory is removed from the gh-pages branch AND the `pr-preview-<N>` deployment is marked **inactive** via the Deployments API within 30 minutes; the preview URL returns 404; the Deployments box shows the deployment in the inactive state.
3. **Given** a merge to `main` occurs, **When** the deploy workflow completes, **Then** the production site at the canonical GitHub Pages URL reflects the merged changes; preview directories from other open PRs are not disturbed.
4. **Given** the first delivery of Stage 6, **When** US8 is shipped as a small first PR with a placeholder site (e.g., "Stage 6 — under construction" landing page + the empty data-package builder skeleton), **Then** the workflows are exercised end-to-end and reviewers can use the live PR-preview deployment on subsequent PRs (US1–US7) to evaluate UI changes before merge.

---

### Edge Cases

- **Empty search** — when the search box is empty, the site shows the full corpus state (no implicit filter). Clearing all filters returns to the same global state.
- **Single result** — when search + facets narrow to a single abstract, the detail panel auto-expands. If the user then clears the filter, the panel collapses but the cart contents persist.
- **Mobile lasso** — the 2D lasso gesture requires a click-drag that conflicts with mobile pan. On mobile, the lasso is replaced by a "select cluster" tap mode (tap a point → select its containing community by community-id); the lasso re-enables when the viewport is ≥ 1024 px wide.
- **Empty cart email** — clicking "email my list" with an empty cart shows a toast `"Add abstracts first"` instead of opening an empty composer.
- **Mail client unavailable** — if the user's environment has no default mail handler (some Linux desktop / kiosk setups), clicking "email my list" falls back to displaying the email body in a modal with a "copy to clipboard" button.
- **Typo tolerance + short queries** — for queries < 3 characters, typo tolerance is disabled (otherwise every 3-letter abbreviation matches half the corpus). The threshold is documented in the help tooltip.
- **3D UMAP on low-end devices** — the 3D view may stutter on older phones; users on such devices can switch to the 2D tab manually. Automatic FPS-based degradation is out of scope for v1.
- **About-page external link breakage** — if a reference URL becomes a 404, the build action fails noisily so the link is fixed before deploy. (Out-of-scope: handling dead links at runtime.)
- **PR preview collisions** — two PRs touching the same files publish to distinct preview URLs (`pr-<N>`); they never overwrite each other.
- **Walkthrough on small screens** — the tour layout adapts: on phones the highlight + tooltip stack vertically rather than side-by-side.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001 (Audience scope)**: The site MUST show only **accepted** abstracts (`accepted_for ≠ "Withdrawn"`). Withdrawn submissions MUST NOT appear in any search, projection, facet, cart, or detail surface.
- **FR-002 (Poster id)**: Every abstract reference (URL fragment, cart item, detail header, list card) MUST use the program-assigned **poster id** as the user-facing identifier. The submission id is internal only and MUST NOT be displayed in the UI.
- **FR-003 (Authors)**: Every abstract detail panel MUST include the ordered author list with each author's affiliation. The data package MUST include author records joined to abstracts. (The current UI omits this; restoring it is part of this stage.)
- **FR-004 (Model selection)**: The user MUST be able to choose from the 5 models (`voyage`, `minilm`, `openai`, `pubmedbert`, `neuroscape`) crossed with the 3 inputs (`abstract`, `claims`, `methods`). Default selection is `neuroscape` × `abstract`. The 2D/3D UMAPs, lasso semantics, and (where applicable) facet/clustering counts reflect the selected (model, input) cell.
- **FR-005 (2D UMAP + lasso)**: The user MUST be able to view a 2D UMAP scatterplot, pan/zoom, and lasso-select a region. The lasso selection becomes the active filter (intersected with search + facets).
- **FR-006 (3D UMAP)**: The user MUST be able to view a 3D UMAP. The 3D view supports rotate / pan / zoom but NOT lasso (out of scope for v1).
- **FR-007 (Semantic search)**: The user MUST be able to type a free-text query and receive abstracts ranked by semantic similarity. The semantic similarity MUST be computed client-side (no server roundtrip) using a published sentence-embedding model that runs in the browser.
- **FR-008 (Lexical search)**: The user MUST be able to perform a lexical search with typo tolerance (Damerau-Levenshtein distance ≤ 2 for words ≥ 4 characters; ≤ 1 for shorter). Lexical matches surface across abstract title, sections, keywords, methods, and author names.
- **FR-009 (Search-result merging)**: Semantic + lexical results MUST be merged into a single ranked list; the user MUST be able to filter to "semantic only", "lexical only", or "both" via a visible control.
- **FR-010 (Author search with typo tolerance)**: The author-search input MUST tolerate 1 typo for surnames ≤ 4 characters and ≤ 2 typos for longer surnames. Diacritics MUST be matched case- and accent-insensitively (e.g., `"García" ≈ "Garcia"`).
- **FR-011 (Detail panel — extra questions scope)**: The abstract detail panel MUST display only two "extra question" fields from the submission form: **Topics** (Primary + Secondary Parent Category & Sub-Category) and **Methods** (the methods-checklist question). All other submission-form questions MUST NOT be shown in the detail panel.
- **FR-012 (References open externally)**: When an abstract carries reference links (DOI / external URL via OpenAlex), each link MUST open in a **new browser tab/window** with `rel="noopener noreferrer"` semantics.
- **FR-013 (Interactive facets)**: The facet sidebar MUST recompute every facet's per-option counts whenever the active selection changes (any combination of: search query, facet filter, UMAP lasso). Counts MUST reflect the intersection of all active filters.
- **FR-014 (Shopping cart)**: The user MUST be able to add any abstract to a cart from any result surface (list card, detail panel, search result). The cart MUST persist across page reloads in the same browser. The user MUST be able to remove individual items or clear the cart.
- **FR-015 (Email-my-list)**: The user MUST be able to launch an "email my list" action that opens the OS mail composer (mailto: link) with a pre-filled body listing each cart item's poster id, title, and a permalink back to the site's abstract anchor. If no mail handler is registered, the site MUST fall back to a copy-to-clipboard modal.
- **FR-016 (Walkthrough)**: The site MUST offer a discoverable "Take the tour" affordance. The tour MUST NOT auto-launch for returning users; it MUST be re-launchable from a persistent help affordance.
- **FR-017 (About page)**: The site MUST include an About page with a ≤ 250-word non-specialist overview followed by per-stage collapsible deep-dives (Stages 1–4 plus topics + UMAP). Every methods claim MUST link to a real, accessible external reference; build-time link validation MUST fail the deploy if any link is broken.
- **FR-018 (Responsive layout)**: The site MUST render usably on phones (≥ 360 px wide), tablets (≥ 768 px wide), and desktops (≥ 1024 px wide). Result lists, detail panels, facets, and the UMAP layout MUST adapt; the lasso gesture is desktop-only (see Edge Cases).
- **FR-019 (Data package — static JSON shards)**: The deployed data package MUST be a set of **static JSON shards** organized abstract-centric — no DuckDB-WASM, no Parquet, no client-side query engine. The canonical layout is:
  - `data/manifest.json` (≤ 5 KB) — corpus state-key, code revision, build timestamp, shard URL pointers, facet keys + ordered options, and the (model, input) cell catalog discovered from the Stage 4 rollup at build time. Loaded first; everything else lazy-loaded off of it.
  - `data/abstracts.json` (≤ 6 MB gz) — array of 3,244 accepted-only records, each `{abstract_id, poster_id, title, accepted_for, sections: {introduction, methods, results, conclusion}, references: [{text, doi?, url?}], topics: {primary, secondary, subcategories}, methods_checklist, author_ids: [int]}`. Stripped of `submission_id` everywhere; withdrawn rows excluded at build time.
  - `data/authors.json` (≤ 1.5 MB gz) — array of unique author records `{author_id, name, affiliations: [str], abstract_ids: [int]}`. Loaded once at startup; joined to abstracts in-memory via `author_ids`.
  - `data/cells/<model>_<input>.json` (15 files, each ≤ 100 KB gz) — per-cell coordinate + cluster table indexed by `abstract_id`: `[{abstract_id, umap2d: [x,y], umap3d: [x,y,z], community_id, topic_cluster_id, neuroscape_cluster_id?, neuroscape_cluster_distance?}, …]`. Lazy-loaded on demand; the default `neuroscape_abstract` cell is fetched at startup, the other 14 only when the user selects them.
  - `data/topics/<model>_<input>_<kind>.json` (≤ 45 files, each ≤ 30 KB gz) — per-cluster topic metadata: `{cluster_id, keywords: [str], title, description, focus}`. Lazy-loaded alongside the matching cell. `<kind>` ∈ {communities, neuroscape_clusters, topic_clusters}.
  - `data/search/lexical_index.json` (≤ 500 KB gz) — pre-built inverted index for typo-tolerant lexical search (n-gram bag per token, mapped to `abstract_id` postings lists). Built once at deploy time so the browser doesn't pay the indexing cost.
  - `data/search/minilm_vectors.bin` (≤ 1.5 MB) — int8-quantized MiniLM-L6 embeddings for the 3,244 accepted abstracts, fixed shape `[3244, 384]` little-endian. Lazy-loaded on first semantic query.
  - The MiniLM ONNX model itself is served from a public CDN (e.g., Hugging Face) and cached by the browser; it is NOT bundled into this data package.
  - All shards MUST embed a `build_info` block: `{corpus_state_key, code_revision, code_revision_short, stage4_rollup_state_key, built_at}` — the same block the footer's "build info" affordance exposes (CA-008) and which carries the short committish surfaced per FR-022. Raw-array JSON shards are forbidden (data-model.md §8 invariant 6); each shard is an object envelope. The `minilm_vectors.bin` carries its build_info via a co-located `minilm_vectors.build_info.json` sidecar.
  - Shard fetches are parallel where independent (manifest + abstracts.json + authors.json + default cell + default topics start in parallel right after manifest resolves).
- **FR-020 (GitHub Pages deploy)**: A GitHub Action MUST build and deploy the site to GitHub Pages on every merge to `main`. The production URL is the canonical GitHub Pages root for the repository.
- **FR-021 (PR previews via GitHub Deployments)**: Every open PR MUST receive a preview deploy at a distinct URL (e.g., `<pages-root>/pr-<N>/`). The preview URL MUST surface in the **PR's Deployments box** (top-of-PR, via the GitHub Deployments API populated from the workflow's `environment:` declaration), **NOT** as a bot comment in the conversation. Subsequent pushes to the PR MUST update the same `pr-preview-<N>` environment's URL in place (no environment churn). On PR close (merge OR reject), the workflow MUST deactivate the deployment via the Deployments API AND remove the `/pr-<N>/` directory from the gh-pages branch within 30 minutes — the Deployments box then shows the deployment as "Inactive" with no live URL.
- **FR-022 (Build provenance visible in the UI)**: Every rendered route MUST display the build provenance in a persistent **page-footer "build info" affordance**: the short code-revision tag (first 7 chars of the git SHA, e.g. `a1b2c3d`), the corpus state-key suffix, and the build timestamp. Clicking the affordance MUST reveal the full `build_info` block (full SHA, full corpus + Stage 4 rollup state-keys, ISO timestamp). The short code-revision MUST also appear in the page `<title>` suffix for the placeholder route (e.g. `OHBM 2026 — under construction · a1b2c3d`) so reviewers can verify which committish a PR-preview deploy is built from without opening the page. Source: `manifest.json:build_info.code_revision_short` (data-model.md §0).

### Key Entities

- **Accepted abstract** — the unit of display. Identified by **poster id**. Carries: title, authors (ordered, with affiliations), accepted_for, abstract sections (intro/methods/results/conclusion), references list, the two visible "extra questions" (Topics + Methods), and per-(model, input) UMAP coordinates + community / topic_cluster / neuroscape_cluster ids.
- **Author record** — name, ordered affiliation list, abstract membership (which abstracts they appear on, in which authorship order).
- **Model selection cell** — `(model, input)` pair drawn from `{voyage, minilm, openai, pubmedbert, neuroscape} × {abstract, claims, methods}`. 15 cells total. Default `neuroscape / abstract`.
- **Cart entry** — `{poster_id, title, abstract_anchor_url, added_at}`. Persisted in browser local storage.
- **Facet** — `(facet_key, option_value) → count`. Facet keys: `accepted_for`, `primary_topic`, `secondary_topic`, `keywords`, `methods`, `study_type`, `population`, `field_strength`, `processing_packages`, `species`, `recording_technology`, `brain_regions`, `brain_networks`.
- **Tour step** — `{anchor_selector, title, body, order, optional_predicate}`. The tour reads a small ordered list of steps; first-time visitors see the CTA but never auto-launch.

### Constitution Alignment *(mandatory)*

- **CA-001 (Venv-only Python)**: Build-side scripts that produce the UI data package MUST use `.venv/bin/python` or `uv` targeting that interpreter. (Node tooling for the site itself is separate and lives under `ui/` or `site/`.)
- **CA-002 (Plan-first, test-first)**: This stage adds a behavior-changing UI. Test scope includes: build-time link validation, the per-(model, input) data-shape contract test, and at least one end-to-end smoke per US1 (page loads, search works, abstract opens) using a headless browser. Test-first applies — those tests are written/identified before implementation begins.
- **CA-003 (Docs sync)**: The README operations runbook, CLAUDE.md module list, and the project charter (`docs/reproducibility-vision.md`) MUST be updated alongside the implementation to reflect the new build command, the deploy workflow, and the new UI package boundary.
- **CA-004 (Secrets)**: The deploy workflow MUST NOT require any custom secret beyond the default `GITHUB_TOKEN`. No OpenAI/Anthropic keys at runtime — the site is fully static + client-side.
- **CA-005 (No committed data)**: The UI data package landing zone MUST be under an existing gitignored root (`data/outputs/exported-sites/...` or `export/ui-site/`). The GitHub Action publishes to the `gh-pages` branch — that branch's contents are auto-generated and not part of source review.
- **CA-006 (Fail loudly)**: Reference link validation MUST be a hard build gate. Search/cart/walkthrough error paths surface user-facing messages (no silent failures).
- **CA-007 (Discover external state)**: The data package's per-(model, input) cells MUST be discovered from the Stage 4 rollup at build time, not hardcoded — adding a 6th model later requires zero UI code changes beyond a rebuild.
- **CA-008 (Provenance)**: The data package MUST embed a build-stamp metadata block (corpus_state_key, code revision (full git SHA + 7-char short SHA), Stage 4 rollup state-key, build timestamp) on **every shard** (per data-model.md §8 invariant 6; raw-array shards are forbidden). The short SHA MUST be visible in the site footer on every route AND in the page `<title>` suffix on the placeholder route per FR-022, so PR-preview deploys can be visually verified as the right committish without DevTools.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (Performance — first paint)**: On a typical broadband connection, the site reaches first interactive paint (visible search box + result list) within **3 seconds**.
- **SC-002 (Performance — search)**: A typed query returns ranked results within **500 ms** for the median query (3,244-row corpus).
- **SC-003 (Performance — UMAP)**: Switching between two `(model, input)` cells re-renders the 2D UMAP within **1 second** on a recent laptop.
- **SC-004 (Mobile usability)**: All US1 acceptance scenarios pass on a mobile viewport (360 × 640 px); the user can complete the search → detail flow without horizontal scrolling.
- **SC-005 (Accepted-only invariant)**: Every list, projection, facet, cart, and detail surface contains **zero** withdrawn abstracts — verified by an automated test that scans the deployed data package for any `accepted_for == "Withdrawn"` records.
- **SC-006 (Data-package size)**: The static JSON shard set downloaded for first paint (manifest + abstracts + authors + the default `neuroscape_abstract` cell + its topics + the lexical index) MUST be ≤ **8 MB gzipped**. The full per-cell expansion (all 15 cells + all topic files) MUST be ≤ **3 MB gzipped** on top of the first-paint set (~11 MB gz max for the complete data package). The int8 MiniLM vectors (≤ 1.5 MB) MUST be lazy-loaded only on the first semantic query.
- **SC-007 (Reference-link health)**: The build action's link checker fails the deploy if **any** external reference URL on the About page returns a non-200 status. Verified at every build.
- **SC-008 (PR-preview latency)**: From PR push to live preview URL, the action completes within **10 minutes** at the 90th percentile.
- **SC-009 (Cart persistence)**: A cart with 5 items survives a full page reload + browser restart in the same browser (within local-storage retention norms — typically 7+ days).
- **SC-010 (Typo tolerance)**: 90% of single-typo queries (insert / delete / substitute / transpose) against known abstract titles or author surnames surface the correct abstract in the top 10 results.
- **SC-011 (Provenance visible per FR-022)**: On any live PR-preview deploy, a reviewer can confirm the committish without opening DevTools — the short SHA appears in the page title suffix AND in the footer build-info affordance on every route (home, about, abstract permalink). Verified by a Playwright assertion that fails if the rendered footer does NOT include `manifest.build_info.code_revision_short`.

## Assumptions

- **Modern framework**: the site is implemented in a modern JavaScript framework. The spec doesn't mandate a specific one — implementation can choose (React + Vite, Svelte + Vite, Astro, etc.) based on bundle-size / DX trade-offs.
- **In-browser sentence-embedding model**: the user-named "minilm and its JS model" is interpreted as a small Sentence-Transformers MiniLM checkpoint shipped as a quantized ONNX model loaded via a browser ML runtime (e.g., transformers.js, ONNX Runtime Web). Implementation will pick the smallest checkpoint that hits SC-002 + SC-010.
- **Author affiliations**: per-author affiliation strings come from the existing `data/primary/authors.json` (Stage 1's inline author fetch from the GraphQL API).
- **Poster id semantics**: the program-assigned poster id (e.g., `M-AM-101`) is already in the Stage 1 corpus under `poster_id`. The current UI displays submission ids because the legacy export forgot to surface `poster_id`; the fix is to use it everywhere.
- **References data**: each abstract's reference list comes from Stage 2.1's OpenAlex-resolved `data/primary/reference_metadata.json`. References without a DOI/URL are still listed but without a clickable link.
- **Cart persistence**: browser local storage; no server-side cart. Email integration is `mailto:` (no SMTP relay).
- **Walkthrough state**: a single localStorage key tracks "user has dismissed the tour CTA at least once" so the CTA isn't a banner forever.
- **About-page references**: every external link is validated at build time via the same GitHub Action; the link checker uses a simple HEAD request with a 10-second timeout per URL.
- **PR preview cleanup**: cleanup is triggered by the `pull_request.closed` event; the action commits a directory removal to the `gh-pages` branch.
- **Mobile lasso replacement**: the 2D lasso is desktop-only; mobile users tap a point to select its community (the community-id from the active `(model, input)` cell's `communities` bundle).
- **Data-package layout**: locked in by the Session-2026-05-17 clarification as a static-JSON-shard architecture — no DuckDB-WASM, no Parquet, no client-side query engine. See FR-019 for the full shard list and SC-006 for the size budget.
- **Lexical-search index**: pre-built at deploy time (n-gram inverted index over tokens), serialized into `data/search/lexical_index.json`. The browser doesn't compute the index at runtime — it just loads it and runs typo-tolerant lookups against it.
- **Facet aggregation**: computed in JavaScript at query time over the in-memory abstract array. At 3,244 rows, a full 13-facet recount is <10 ms on a typical laptop — no SQL or query engine needed.

## Wireframe prompt for Claude Design

If you choose to ask Claude Design to draft a wireframe before implementation, here is a prompt you can paste verbatim:

> Design a wireframe for a public static search site over a corpus of 3,244 accepted scientific conference abstracts (OHBM 2026). The site is read-only, served from GitHub Pages, and must be **responsive (phone / tablet / desktop)**. Brand voice: scientific, clean, no ads.
>
> **Primary layout (desktop, ≥ 1024 px)**: three-column shell.
> - **Left column (240 px)** — collapsible facet sidebar. ~12 facet sections (accepted_for, primary_topic, secondary_topic, keywords, methods, study_type, population, field_strength, processing_packages, species, recording_technology, brain_regions, brain_networks). Each section has a per-option count that updates with selection.
> - **Center column (flexible)** — top: search bar with a "semantic / lexical / both" toggle + author-search subfield + clear button. Below: a tabbed area with two tabs: **2D UMAP** (Plotly-style scatterplot with lasso) and **3D UMAP** (rotatable scene without lasso). Below the projection: a virtualized result list of abstract cards. Each card shows poster id, title, lead author + affiliation, primary topic, an "add to list" button. A persistent "build info" footer affordance shows the short git SHA (e.g. `a1b2c3d`), corpus state-key suffix, and build timestamp — visible on every route so PR-preview deploys can be verified at a glance (FR-022).
> - **Right column (320 px)** — sticky detail panel. Shows the currently focused abstract: poster id, title, full author + affiliation list (collapsible if > 6), abstract sections (intro / methods / results / conclusion with collapsible "show more"), Topics + Methods, references (each link opens in a new tab), an "add to list" button.
>
> **Top header bar**: project name on the left; model-selection dropdowns in the center (model × input, default `neuroscape × abstract`); cart icon with item count on the right; "Take the tour" CTA next to the cart; "About" link in the header.
>
> **Mobile layout (< 768 px)**: single column. Search bar pinned to the top; "filters" button opens the facet sidebar as a full-screen drawer; "map" button opens UMAP as a full-screen overlay; result list is the default home view; tapping a result opens the detail panel as a full-screen overlay with a close button. Lasso is replaced by "tap a UMAP point to filter by its community". Cart icon stays in the top bar.
>
> **Walkthrough overlay**: when the user clicks "Take the tour", an overlay highlights each component in turn — search → model selector → UMAP → lasso (desktop only) → facets → cart — with a small tooltip and Next/Prev/Skip controls. Skippable, never auto-launches.
>
> **About page**: a separate route with a 250-word non-specialist overview at the top, followed by 5–7 collapsible deep-dive sections (corpus, enrichment, embeddings, analysis & annotation, topics, projections). Each deep dive cites real references that open externally.
>
> **Email-my-list flow**: when the user clicks "Email my list" with cart items, the OS mail composer opens with a pre-filled subject + body listing items.
>
> Use a clean, neutral color palette (mostly grayscale + one accent for the lasso / selected state); typography should be readable on small screens. Avoid skeuomorphic shopping-cart imagery — prefer a "saved list" or "bookmark" metaphor.
