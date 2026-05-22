# Feature Specification: Book layout polish + acknowledgments

**Feature Branch**: `013-book-layout-polish`
**Created**: 2026-05-21
**Status**: Draft
**Input**: User description: "let's improve the book layout and some additional info for both the book and the website. we need to add the acknowledgment section. also can the figure assets be reformatted into the same format (150 dpi, jpeg quality 90%). the book should have a table of content organized by poster number, title and page. let's organize the author index by last name, and can we improve the layout (minimize margins)."

## Clarifications

### Session 2026-05-21

- Q: Brief-preview size for collapsible sections → A: first 3 lines via CSS `line-clamp`.
- Q: Where does the brief-preview UX apply (in-grid drawer vs single-abstract permalink page)? → A: **only the permalink page** (`/abstract/<poster_id>/`). The in-grid `DetailPanel.svelte` side drawer is left as-is — same content, same fully-expanded behaviour as today.
- Q: Which sections on the permalink page get the brief-preview treatment? → A: left-column verbatim prose sections only — Introduction, Methods, Results, Conclusion, Acknowledgments. References / Topics / Methods checklist and the right-column AI cards stay as-is.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Surface the acknowledgments section on the permalink page (Priority: P1)

The book of abstracts already includes each submission's *Acknowledgement* field as a body section. The website's permalink page (`/abstract/<poster_id>/` — reached via the "full details ↗" link, email shares, and deep-link bookmarks) silently drops it. Authors and grant agencies expect their funding attribution to be visible wherever the work is — and a reader reviewing an abstract on its deep-link page can't see who funded it. This story closes that gap on the permalink page; the in-grid detail-panel side drawer is intentionally left as-is per the 2026-05-21 clarifications.

**Why this priority**: it's an attribution + funder-recognition gap that affects every abstract that carries acknowledgement text. Cheap to fix, and the data already exists in the corpus.

**Independent Test**: pick an abstract whose corpus record has a non-empty `Acknowledgement` response. Verify (a) the book PDF shows the acknowledgment under that abstract (Stage 11 already does this), (b) the website's permalink page shows the same text in a clearly labelled "Acknowledgments" subsection, (c) the in-grid drawer in the browse view is UNCHANGED (no new section, no missing section), (d) abstracts with empty / absent acknowledgments do NOT render an empty section heading on the permalink page.

**Acceptance Scenarios**:

1. **Given** an abstract with acknowledgments text in the corpus, **When** an operator visits the deep-link permalink page (`/abstract/<poster_id>/`), **Then** the permalink page shows an "Acknowledgments" subsection in the verbatim-left-column area containing the original prose, formatted consistently with the existing body sections (Introduction, Methods, Results, Conclusion).
2. **Given** the same abstract, **When** an operator opens the in-grid detail-panel side drawer in the browse view, **Then** the drawer's body sections are unchanged — no Acknowledgments section appears there (per the clarification: leave the in-grid drawer's content as-is).
3. **Given** an abstract with no acknowledgments response, **When** the permalink page renders, **Then** no empty "Acknowledgments" heading appears (graceful absence).

---

### User Story 1b - Brief-preview default + show-more controls on the permalink page (Priority: P1)

The permalink page's verbatim prose blocks (Introduction / Methods / Results / Conclusion / Acknowledgments) currently render at full length. For a long abstract that's a wall of text the reader has to scroll through before they reach the right-column AI insights. This story changes the default to a brief 3-line preview per section, with per-section "Show more" controls and a global "Show all / Collapse all" toggle. The in-grid detail-panel side drawer is unchanged.

**Why this priority**: P1 because it ships with US1 (the Acknowledgments section gets the same treatment, naturally) and dramatically improves first-impression scannability on the permalink page.

**Independent Test**: open the permalink page for an abstract whose verbatim sections each exceed 3 lines of text. Verify (a) each of the 5 left-column verbatim sections (Intro / Methods / Results / Conclusion / Acknowledgments) opens at 3 lines via CSS `line-clamp` with an ellipsis, (b) a "Show more" button is visible at the bottom of each clamped section, (c) clicking a section's "Show more" expands ONLY that section + relabels its button to "Show less", (d) a global "Show all" button at the top of the verbatim column expands every section at once + relabels to "Collapse all"; clicking again collapses every section back to the 3-line preview, (e) sections that fit in 3 lines or fewer (i.e. clamp wouldn't truncate) do NOT show a "Show more" button.

**Acceptance Scenarios**:

1. **Given** the permalink page for an abstract whose Methods section is 12 lines of prose, **When** the page first renders, **Then** the Methods section shows the first 3 lines plus a "Show more" button.
2. **Given** the same page, **When** the operator clicks the Methods "Show more" button, **Then** the Methods section expands to full text, the button relabels to "Show less", and the other sections stay in their 3-line preview state.
3. **Given** the same page, **When** the operator clicks the column-level "Show all" button, **Then** every left-column verbatim section expands to full text and the global button relabels to "Collapse all".
4. **Given** all sections are expanded, **When** the operator clicks "Collapse all", **Then** every section returns to the 3-line preview state.
5. **Given** an abstract whose Acknowledgments section is a single line ("Funded by NIH grant XYZ."), **When** the permalink page renders, **Then** the Acknowledgments section shows the full text without a "Show more" button (no clamp-truncation occurred).

---

### User Story 2 - Normalise figure assets to a single image format (Priority: P2)

The book's `fig_assets/` directory currently carries a mixed bag of formats: original PNGs preserved, JPEGs preserved (q=85), the occasional GIF / WebP / TIF. The print pipeline downstream (Tectonic + pandoc) can handle the variety, but the operator's promotional bundle (which gets shared with reviewers + organisers) is bulkier than it needs to be and renders with inconsistent print fidelity. This story standardises every figure to one shape: 150 DPI raster JPEG at quality 90% (slightly higher than the current q=85 default to preserve the few PNG-style line-art figures that lose detail under aggressive JPEG compression).

**Why this priority**: smaller + more uniform `fig_assets/` makes the book bundle easier to share, gives organisers a single mental model for "the figures look like X", and shrinks the published PDF without changing the editorial content.

**Independent Test**: run the book pipeline against a corpus containing every supported source format (PNG, JPEG, GIF, WebP, TIF). Verify (a) every file under `fig_assets/` has a `.jpg` extension after the run, (b) every file's pixel dimensions correspond to 150 DPI at the book's column width (≈ 6.5 inches wide → ~975 px wide cap), (c) JPEG quality is 90%, (d) the assembled PDF still renders each figure with no visible degradation vs the prior PNG-original behaviour for a panel of test images.

**Acceptance Scenarios**:

1. **Given** a source figure that's a 4000×3000 PNG, **When** the figure-assets normaliser runs, **Then** the output is `<submission_id>-<poster_id>-<type>.jpg` at the 150 DPI dimension cap with JPEG quality 90, and the original PNG is NOT in the bundle.
2. **Given** a small 600×400 JPEG, **When** the normaliser runs, **Then** the output preserves the source dimensions (no upscaling) but is re-encoded at q=90 (so it's deterministic regardless of the source's prior compression).
3. **Given** a source figure Pillow can't open (corrupted bytes, exotic format), **When** the normaliser runs, **Then** the build still succeeds, the source is byte-copied to the bundle with its original extension as a fallback, AND the failure is logged in `provenance.figures_normalised_with_fallback[]` so an operator can audit.

---

### User Story 3 - Table-of-contents organised by poster number / title / page (Priority: P2)

Pandoc's default LaTeX TOC for the book is a flat list of "Abstract NNNN — Title …………… 47". For a 3,200-abstract book that's 200+ pages of TOC, hard to scan, and the title overflow truncates in awkward places. This story replaces it with a compact 3-column ruled table — `poster_id | title | page` — sorted by poster_id (matching the book's body order under `--sort poster_id`), with the title column word-wrapped to a fixed width so the page column stays vertically aligned.

**Why this priority**: the TOC is the operator's primary navigation aid; a clean tabular TOC is dramatically more scannable for paper-print use.

**Independent Test**: produce the book PDF with the new TOC. Verify (a) the TOC pages are formatted as a 3-column table with visible column headers ("Poster", "Title", "Page"), (b) every accepted abstract has exactly one row, (c) the poster_id column is right-aligned (no leading-zero confusion), (d) the page column shows the SAME page number as the abstract's first body page (matches what `\setcounter{page}` resolved to during the two-pass assembly), (e) overall TOC page count is reduced vs the prior default.

**Acceptance Scenarios**:

1. **Given** the assembled book PDF, **When** an operator turns to the TOC, **Then** they see a 3-column table starting with the column headers `Poster | Title | Page`, sorted ascending by poster_id, with no leading-zero padding inconsistencies on the poster_id column.
2. **Given** an abstract whose title is unusually long, **When** the TOC renders, **Then** the title wraps to two or more lines within the title column WITHOUT pushing the page column out of alignment with adjacent rows.
3. **Given** an abstract that failed to render (Stage-11.1 failure isolation), **When** the TOC renders, **Then** that abstract is OMITTED from the TOC (consistent with its absence from the body).

---

### User Story 4 - Author index grouped by last-name initial (Priority: P2)

Stage 11.1 emits a hand-rolled author index (`assemble_pdf._build_index_markdown`) — one paragraph per author, sorted by `(last_name, first_name)`. For ~10,000 distinct authors that's a wall of 60+ pages with no visual breaks. Print-book convention is to group the index by initial letter, with a section header (`A`, `B`, `C`, …) at the top of each letter group. This story adds those headers; sorting is unchanged.

**Why this priority**: trivial improvement that makes the back-of-book navigable. The data is already last-name-sorted; this only adds visual section breaks.

**Independent Test**: open the back of the book PDF. Verify (a) before the first author entry, a section header `A` appears (assuming the first author's last name starts with A; the first letter that exists in the corpus, otherwise), (b) every letter break is preceded by the same-style section header, (c) authors with non-Latin last names that don't fold to A–Z group under a final `Other` section (or comparable bucket — the exact label is an operator detail but the bucketing rule is testable), (d) the index entries within each letter group are in the SAME order they appeared in Stage 11.1's flat output.

**Acceptance Scenarios**:

1. **Given** the assembled book PDF, **When** an operator turns to the author index, **Then** the index opens with a section header for the first letter present (typically `A`), and each new initial letter starts on a new line / page break preceded by its own section header.
2. **Given** an author whose last name is "Östen", **When** the index renders, **Then** that name appears under the `O` section (Unicode-fold-aware grouping) — NOT a separate `Ö` section.
3. **Given** an author whose last name starts with a digit or non-letter, **When** the index renders, **Then** that name appears under a final `Other` (or equivalent) bucket at the end of the index.

---

### User Story 5 - Tighter book margins for higher information density (Priority: P3)

The default `book` document class in LaTeX uses ~1-inch margins on all sides, which on US-letter / A4 wastes ~25% of every page. For a 15,000-page book that's an enormous print/storage cost. This story tightens all four margins to a still-readable but materially smaller value, reducing the total assembled page count and the bundle's file size.

**Why this priority**: P3 because it's pure typography polish — no semantic content changes, no test-breaking risk. But cheap to ship alongside the other improvements.

**Independent Test**: build the book PDF before and after the margin change against the same corpus + cache. Verify (a) total page count drops by ≥ 15%, (b) text within an abstract still reads naturally (no orphaned single-character lines, no figure-overflow into the new margin), (c) the title page + TOC + index continue to render correctly with the tighter margins, (d) the figure-resolution audit (`provenance.figures_below_resolution_threshold`) does NOT show a regression — i.e. tighter margins don't squeeze figures past the print-DPI floor.

**Acceptance Scenarios**:

1. **Given** the same corpus + cache, **When** the operator builds the book with the new margins, **Then** the resulting `book.pdf` has ≥ 15% fewer total pages than the prior build.
2. **Given** an abstract with a wide figure, **When** the figure renders under the new margins, **Then** the figure does NOT cross the page boundary (LaTeX's `\includegraphics` already auto-scales, but the margin change MUST NOT trip the auto-scale on previously-fine figures).
3. **Given** the figure-resolution audit, **When** an operator inspects `provenance.figures_below_resolution_threshold` for the new build, **Then** the count is ≤ the prior build's count (no new low-DPI flags introduced by the margin change).

---

### Edge Cases

- **Acknowledgment present but empty/whitespace**: treated as absent — no section heading on the permalink page, no book section. Trim + length-check before render.
- **Permalink-page short section**: a section whose full text fits within the 3-line clamp (no truncation needed) MUST render the full text and MUST NOT show the per-section "Show more" toggle. The master "Show all" toggle still counts that section as already-expanded.
- **Mixed-state master toggle**: when SOME sections are expanded and others clamped, the master toggle reads "Show all" (consistent with the "expand-the-rest" affordance). Only when EVERY section is fully expanded does it flip to "Collapse all".
- **Figure normalisation source unreadable**: byte-copy fallback (per US2 AS-3); audit log entry. Build proceeds.
- **TOC page-number drift**: the two-pass assembly already measures global page offsets per chunk. The new TOC table reads those offsets verbatim — if the offsets change (more chunks fail, e.g.), the TOC's page column updates to match.
- **Author index non-Latin initial**: Unicode-fold to nearest ASCII letter; truly unfoldable names go to `Other`.
- **Margin regressions**: figures whose source dimensions push past the new content width get auto-scaled by LaTeX. If `\includegraphics` warnings show in pandoc stderr for previously-fine figures, that's a regression; document the failing poster_id list under provenance.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The website's per-abstract permalink page (`/abstract/<poster_id>/`) MUST render an "Acknowledgments" subsection in the verbatim-left-column area when the corpus record's `Acknowledgement` response is non-empty (after trim). The in-grid detail-panel side drawer (`DetailPanel.svelte`) is INTENTIONALLY NOT modified — it keeps its current 4-section body (Intro / Methods / Results / Conclusion).
- **FR-002**: The permalink page's 5 left-column verbatim sections (Introduction, Methods, Results, Conclusion, Acknowledgments) MUST default to a CSS `line-clamp: 3` preview with a per-section "Show more" / "Show less" toggle button. Sections whose full text fits in 3 lines (clamp would not truncate) MUST NOT render the toggle button.
- **FR-003**: The permalink page's left column MUST also offer a column-scoped "Show all" / "Collapse all" master toggle that expands or collapses every verbatim section at once. The master toggle's label reflects the current aggregate state (showing "Show all" when at least one section is clamped; "Collapse all" when every section is expanded).
- **FR-004**: The data-package abstracts envelope MUST add `sections.acknowledgments: string` (trimmed; empty string when absent) so the UI consumers can read it as a normal section.
- **FR-005**: The book's figure-asset normaliser MUST re-encode every figure to `.jpg` at JPEG quality 90% with a 150 DPI pixel-dimension cap (≈ 975 px wide at the book's 6.5" content width). The original source filename's `<type>` and `<index>` parts of the contract are preserved; only the extension changes to `.jpg`.
- **FR-006**: When the figure-asset normaliser encounters a source file Pillow cannot open, it MUST byte-copy the original file with its original extension as a fallback AND append the poster_id + filename + error reason to `provenance.figures_normalised_with_fallback[]`. The build MUST NOT abort on a single unreadable figure.
- **FR-007**: The book's table of contents MUST be a 3-column table with the columns `Poster | Title | Page`, sorted ascending by poster_id, replacing pandoc's default TOC. The TOC MUST omit any abstract that failed to render (per Stage 11.1's failure-isolation semantics).
- **FR-008**: The book's author index appendix MUST add a section header (single uppercase letter `A`–`Z`) before each new initial-letter group. Authors whose last-name initial does not fold to A–Z MUST appear under a final `Other` bucket at the end of the index.
- **FR-009**: The book's content area MUST use tighter margins than the LaTeX `book` class default, sized to produce a ≥ 15% reduction in total page count relative to the prior Stage-11.1 build against the same corpus + cache.
- **FR-010**: The book's `provenance.json` MUST gain three fields: `figures_normalised_count`, `figures_normalised_with_fallback: [{poster_id, filename, error_reason}]`, and `toc_page_count` (the number of pages the new TOC consumes).

### Key Entities *(include if feature involves data)*

- **AcknowledgmentSection**: the trimmed prose of an abstract's `Acknowledgement` corpus response. Renders in the book + the website permalink page (NOT in the in-grid detail-panel drawer).
- **PermalinkSectionState**: client-side reactive state on the permalink page tracking each verbatim section's expand/collapse status (boolean per section_key). Derived: `allExpanded` (true when every section is expanded) drives the master toggle's label.
- **NormalisedFigureAsset**: one figure in `fig_assets/<submission_id>-<poster_id>-<type>[-<index>].jpg`, encoded at JPEG q=90 with the 150-DPI dimension cap. Sidecar audit entry exists when the source couldn't be re-encoded and got byte-copied instead.
- **TocRow**: one row of the new book TOC — `(poster_id: int, title: str, page: int)`. Sorted by poster_id; one row per accepted abstract that successfully rendered.
- **AuthorIndexBucket**: a group of `AuthorIndexEntry` records sharing the same Unicode-folded initial letter. Bucket order is `A`, `B`, …, `Z`, `Other`.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python work runs through `.venv/bin/python` or `uv` targeting it.
- **CA-002**: Tests land first for the five load-bearing behaviour changes: (a) acknowledgments-section roundtrip on the data-package shard, (b) per-section "Show more" toggle + master "Show all" toggle on the permalink page (vitest unit + Playwright e2e), (c) figure normaliser quality + dimension floor, (d) TOC table emission + page-number alignment with `chunk_offsets`, (e) author-index bucket headers.
- **CA-003**: README + `docs/abstracts-book-plan.md` updated in the same change for any new operator-visible flag (e.g. `--figure-format`, `--margin-preset`).
- **CA-004**: No new credentials introduced; figure normalisation runs locally via Pillow (already an `[abstracts_book]` extra).
- **CA-005**: All produced books + intermediate normalised figures land under gitignored roots (`data/outputs/book/`, `data/cache/book/`).
- **CA-006**: Figure-normalisation fallbacks MUST surface via `provenance.figures_normalised_with_fallback[]` (no silent drops).
- **CA-007**: Margin / TOC / index changes are content-driven (read from the corpus state + computed chunk offsets) — no hardcoded page-count allow-list.
- **CA-008**: New provenance fields ship alongside the assembled book with no absolute / `~/` paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For an abstract carrying a non-empty Acknowledgement response in the corpus, an operator on the website's permalink page can read the acknowledgment text within 1 second of the page settling (rendered with the rest of the verbatim sections, no extra fetch). The in-grid detail-panel side drawer's content is unchanged.
- **SC-001b**: On the permalink page, the first paint shows each left-column verbatim section clamped to 3 lines; the operator can expand any single section in ≤ 100 ms via its "Show more" button, and the global "Show all" toggle expands every section in ≤ 200 ms.
- **SC-002**: The figure-asset bundle for the real corpus shrinks by ≥ 30% in total bytes after the normalisation pass (relative to the prior mixed-format bundle), without any figure dropping below the print-DPI threshold (`provenance.figures_below_resolution_threshold` count does NOT increase).
- **SC-003**: The book TOC consumes ≤ 50% of the pages the prior pandoc default consumed (3-column table is denser than the indented section list).
- **SC-004**: The author index appendix shows letter-group headers (`A`, `B`, …, `Z`, `Other`); an operator can locate the start of any letter's authors in ≤ 2 page-turns from the index start.
- **SC-005**: The assembled book.pdf has ≥ 15% fewer total pages with the new margins vs the prior Stage-11.1 build against the same corpus + cache.
- **SC-006**: No regression in figure-resolution audit: `provenance.figures_below_resolution_threshold` count after the margin + normalisation changes is ≤ the prior build's count.

## Assumptions

- Operators continue running the book pipeline via `ohbmcli book` with the same `--sort poster_id` default; the TOC + author index changes apply regardless of `--sort` value but `--sort poster_id` is the primary print use case.
- The permalink page (`/abstract/<poster_id>/`) is the target placement for the new Acknowledgments subsection AND the brief-preview UX; the in-grid `DetailPanel.svelte` side drawer is explicitly out of scope.
- Per-section expand/collapse state is **per-page** (no `localStorage` persistence). Each navigation to a permalink page starts with every section in the 3-line clamp state.
- The 150 DPI / 6.5" content width assumption maps to a ~975 px wide image cap — operators changing the book's content width via a future `--page-width` flag would need to recompute this cap.
- "Minimize margins" is interpreted as a fixed tighter preset (the spec does NOT introduce an operator-facing `--margin-pt` flag for v1; that's a future cleanup). The default is the new tight preset; a `--margins=loose` flag MAY be added to recover the LaTeX-`book`-class default as a single named alternative.
- The figure normalisation step lives alongside the existing `_copy_figure` pipeline (joblib-parallel, fig_assets is per-build) — no cross-build figure cache is introduced here; that's a follow-up.

## Out of Scope (explicitly deferred)

- **Cross-build fig_assets cache** — survives staging-dir wipe between runs. Identified as a follow-up during the Stage-11.1 smoke test (warm-cache time bottleneck), still in flight.
- **DOCX format** — retired in Stage 11.1 US3.
- **Per-letter author-index page break** (forcing each letter to start on a new page) — spec only mandates a section header; explicit page-break is a future typography tweak.
- **TOC for the Tufte style variant** — the new 3-column TOC applies to `--style plain`. Tufte styling is the operator's existing experimental path; this spec leaves its TOC mechanism untouched.
- **Brief-preview UX on the in-grid detail-panel side drawer** — explicitly out of scope per 2026-05-21 clarification. Drawer content + behaviour stay as-is.
- **Persisting expand/collapse state across permalink-page visits** — every fresh page load resets to the 3-line preview. `localStorage` persistence deferred.
- **Per-section detail page on the website** — the Acknowledgments section lands inside the existing permalink layout; no separate `/acknowledgments/` routes.
- **Margin presets beyond default + (optional) `loose`** — fine-grained `--margin-top=X`, `--margin-bottom=Y` deferred to a future operator-friendly polish PR.
