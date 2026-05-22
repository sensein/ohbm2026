# Implementation Plan: Book layout polish + acknowledgments + permalink UX

**Branch**: `013-book-layout-polish` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/013-book-layout-polish/spec.md`

## Summary

Six bundled stories landing on top of Stage 11.1:

1. **US1 — Acknowledgments on the permalink page** (P1). New `sections.acknowledgments` field on the data-package abstracts envelope; the permalink page's left column renders an "Acknowledgments" subsection when the trimmed value is non-empty. The in-grid `DetailPanel.svelte` drawer is **left untouched** per the 2026-05-21 clarification.
2. **US1b — Brief-preview UX on the permalink page** (P1). The 5 left-column verbatim sections (Introduction, Methods, Results, Conclusion, Acknowledgments) default to a CSS `line-clamp: 3` preview. Each section gets a per-section "Show more / Show less" toggle. A column-scoped "Show all / Collapse all" master toggle drives every section at once. Implemented behind a `mode: 'panel' | 'permalink'` prop on `DetailPanel.svelte` so the in-grid drawer's behaviour is unchanged.
3. **US2 — Normalised figure assets** (P2). The book's `_copy_figure` always re-encodes to JPEG q=90 at a 150 DPI dimension cap (≈ 975 px @ 6.5" content width). Sources Pillow can't open get a byte-copy fallback with an audit entry in `provenance.figures_normalised_with_fallback[]`.
4. **US3 — 3-column TOC** (P2). Replaces pandoc's default flat-section TOC with a `longtable` carrying `Poster | Title | Page` rows. Sourced from the assembler's measured `chunk_offsets`; omits failure-isolated abstracts.
5. **US4 — Author-index bucket headers** (P2). `_build_index_markdown` groups entries by Unicode-folded last-name initial and emits a `## A`, `## B`, …, `## Z`, `## Other` heading before each bucket.
6. **US5 — Tighter book margins** (P3). LaTeX `geometry` package with a `tight` preset (≈ 0.65 in each side) targeting ≥ 15% page-count reduction. Optional `--margins=loose` flag recovers the LaTeX `book` class default for an operator who needs the old layout.

No new system deps. The Python side adds nothing the `[abstracts_book]` extra doesn't already cover. The TypeScript side adds no new dependencies — line-clamp uses standard CSS and the toggle state is plain Svelte reactivity.

## Technical Context

**Language/Version**: Python 3.14 (repository `.venv`); SvelteKit 2 + Vite 6 + Svelte 5 (existing site).

**Primary Dependencies**:
- *Existing in `[abstracts_book]` optional extra*: `markdownify`, `beautifulsoup4`, `pikepdf`, `Pillow`, `joblib`. **No additions, no removals.**
- *System binaries* (unchanged): `pandoc >= 3.1` and Tectonic.
- *Existing site deps*: `hyparquet`, `hyparquet-compressors`. No additions.

**Storage**:
- New temporary buffer: none. Figure normalisation writes to the existing `data/outputs/book/.staging__<key>/fig_assets/` path; the on-the-wire `data.parquet` gains the `sections.acknowledgments` field inside the existing `sections` STRUCT (no schema-version bump because v2's STRUCT already accepts string fields).
- Cache: `data/cache/book/abstracts/` unchanged; cache keys still cover the new TOC + margin behaviour because the LaTeX preamble file's hash is part of the cache key.

**Testing**:
- `unittest` (Python convention). New tests under `tests/`:
  - `test_book_figure_normalise.py` — re-encode to JPEG q=90 + dimension cap; byte-copy fallback on Pillow-unopenable; preserves filename `<type>` part.
  - `test_book_toc.py` — assembler emits 3-column `longtable` with the right rows + page numbers from `chunk_offsets`; omits failure-isolated abstracts.
  - `test_book_author_index_buckets.py` — `## A`/`## B`/…/`## Other` headers emitted in expected order; Unicode-folded names go to the right bucket; numeric/symbol initials → `Other`.
  - `test_book_margins.py` — assembled PDF's page count under the new preset is at least 15% fewer than a control build with the loose preset (skip-aware via real-corpus fixture). The lighter unit-level test asserts the geometry preamble is wired correctly (substring check on the rendered .tex / pandoc args).
  - `test_ui_data_acknowledgments.py` — abstracts emitter populates `sections.acknowledgments` from the corpus's `Acknowledgement` response; empty / whitespace trims to empty string.
- `vitest` (site). New tests under `site/src/tests/unit/`:
  - `detail_panel_modes.test.ts` — `DetailPanel` in `mode='permalink'` renders the Acknowledgments section when present + applies line-clamp class + emits per-section toggles. In `mode='panel'` (default), no Acknowledgments + no toggles + no clamp.
- Playwright e2e (site, `site/src/tests/e2e/`):
  - `permalink_show_more.spec.ts` — open `/abstract/<poster_id>/`; verify the 3-line clamp visually + click "Show more" expands the section + master "Show all" expands every section + relabels to "Collapse all".

**Target Platform**: macOS / Linux developer + GitHub Pages prod. No platform-specific code; both surfaces (Python + Svelte) already cross-platform clean.

**Project Type**: Track-A book pipeline polish + Stage 6 data-package field addition + site permalink-page UX upgrade. Two sub-areas touched: `src/ohbm2026/book/`, `src/ohbm2026/ui_data/`, plus `site/src/lib/components/DetailPanel.svelte` and `site/src/routes/abstract/[poster_id]/+page.svelte`.

**Performance Goals**:
- SC-001b: per-section "Show more" toggle ≤ 100 ms on a modern laptop; global "Show all" toggle ≤ 200 ms even with 5 sections expanded simultaneously. Implementation: plain Svelte reactive state (`Map<sectionKey, boolean>`) — no layout reflow beyond the section heights changing.
- SC-002: figure-asset bundle ≥ 30% smaller in bytes after normalisation. Real-corpus before/after measurement during smoke test.
- SC-003: TOC consumes ≤ 50% of prior page count. The new 3-column `longtable` is materially denser than pandoc's default.
- SC-005: assembled PDF ≥ 15% fewer total pages with the `tight` margin preset.

**Constraints**:
- No new external service / no new optional extra.
- The figure normalisation runs through the existing joblib loky-parallel pipeline from Stage 11.1 + the cwd-resolve guard (paths already absolute before dispatch).
- `DetailPanel.svelte` is the existing shared component for the in-grid drawer + the permalink page — the `mode` prop is the surgical separation point.

**Scale/Scope**: 3,240 accepted abstracts × ~4,700 figures × 5 verbatim sections each on the permalink page. The permalink page is rendered client-side per-visit, so the brief-preview state is trivially per-page-load.

## Constitution Check

- **I. Venv-only Python**: every Python entrypoint goes through `.venv/bin/python` or `uv` targeting it; CI calls `PYTHONPATH=src .venv/bin/python -m unittest …`. No new system-Python steps.
- **II. Immutable evidence**: figure normalisation writes to the per-build staging dir under gitignored `data/outputs/book/`. No new artefact roots.
- **III. Resumable, auditable**: figure normalisation is idempotent (the dest-exists short-circuit from Stage 11.1's joblib refactor); per-figure re-encode failures are captured in `provenance.figures_normalised_with_fallback[]` (CA-006).
- **IV. Plan-first, test-first**: tests for each load-bearing slice (acknowledgments roundtrip, line-clamp + toggle, figure normaliser, TOC table, author-index buckets, margin geometry) are named above and land before their implementations.
- **V. Secret-safe**: no credentials introduced.
- **VI. Fail loudly**: byte-copy fallback for unopenable figures is audit-logged (not silenced); pandoc errors on the new TOC pass propagate as `BookBuildError`.
- **VII. Discover external state**: figure pixel dimensions probed via Pillow at runtime, not hardcoded; pandoc/Tectonic versions still discovered (CA-007).
- **VIII. Provenance**: new fields `figures_normalised_count`, `figures_normalised_with_fallback[]`, `toc_page_count` land on `provenance.json` alongside the book.pdf. No absolute / `~/` paths.

**Re-evaluation (post-design)**: Pass. No constitutional carve-outs required.

## Project Structure

### Documentation (this feature)

```text
specs/013-book-layout-polish/
├── plan.md              # this file
├── research.md          # 7 decisions (R1-R7)
├── data-model.md        # AcknowledgmentSection, PermalinkSectionState, NormalisedFigureAsset, TocRow, AuthorIndexBucket
├── quickstart.md        # operator runbook
├── contracts/
│   ├── cli.md           # `ohbmcli book` delta (one new flag: --margins)
│   └── permalink-page.md  # UI contract: brief-preview default + toggles
├── checklists/
│   └── requirements.md  # spec quality (already filled)
└── tasks.md             # produced by /speckit-tasks
```

### Source code (repository root)

```text
src/ohbm2026/book/
├── render_markdown.py       # MODIFIED. _copy_figure rewrites EVERY
│                            # source to JPEG q=90 at 150 DPI cap;
│                            # byte-copy fallback on Pillow
│                            # UnidentifiedImageError; filename keeps
│                            # the <type>[-<index>] part but forces
│                            # .jpg extension. Appends to a new module-
│                            # level fallback registry the cli reads
│                            # at provenance-write time.
├── assemble_pdf.py          # MODIFIED.
│                            # _build_index_markdown: insert
│                            # ## A / ## B / ... / ## Other section
│                            # headers by Unicode-folded last-name
│                            # initial (R6).
│                            # New _build_toc_markdown helper:
│                            # 3-column longtable from
│                            # (chunk_offsets, book.entries). The
│                            # front-matter pandoc pass adds the TOC
│                            # output after the title page.
├── render_via_pandoc.py     # MODIFIED. _build_front_matter_md now
│                            # emits the new longtable TOC block
│                            # (driven by chunk_offsets handed in from
│                            # to_pdf's call site).
├── cli.py                   # MODIFIED. New --margins flag
│                            # (tight | loose, default tight). Threads
│                            # to to_pdf.
├── templates/
│   ├── header-includes.tex          # MODIFIED. tight preset:
│   │                                # \\usepackage[margin=0.65in]{geometry}.
│   ├── header-includes-loose.tex    # NEW. Recovers the LaTeX book
│   │                                # class default (~1in margins).
│   ├── header-includes-tufte.tex    # unchanged.
│   └── per-abstract.tex.template    # MODIFIED. Same geometry as
│                                    # tight preset so per-chunk page
│                                    # dimensions match the assembled
│                                    # book.
├── provenance.py            # MODIFIED. Emit new fields when assembled:
│                            # figures_normalised_count,
│                            # figures_normalised_with_fallback[],
│                            # toc_page_count.

src/ohbm2026/ui_data/
├── abstracts.py             # MODIFIED. Add
│                            # `"acknowledgments": _section(q,
│                            #     "acknowledgement")`
│                            # to the per-record `sections` block.
├── formats/parquet_single.py # unchanged (the sections STRUCT already
│                            # accepts string fields; the new key flows
│                            # via pa.Table.from_pylist inference).

site/src/lib/
├── shards.ts                # MODIFIED. AbstractRecord.sections gains
│                            # `acknowledgments?: string`.
├── components/DetailPanel.svelte  # MODIFIED. Add `mode: 'panel' |
│                            # 'permalink'` prop (default 'panel').
│                            # In 'permalink' mode:
│                            #   * Add Acknowledgments to the section
│                            #     iteration (after Conclusion).
│                            #   * Apply per-section line-clamp CSS
│                            #     class with reactive expanded[skey]
│                            #     state controlling .clamped vs .open.
│                            #   * Render per-section "Show more" /
│                            #     "Show less" button (only when the
│                            #     section's prose would actually clamp;
│                            #     detected by a pre-render text-length
│                            #     heuristic, see R2).
│                            #   * Render a column-level master toggle.
│                            # In 'panel' mode (default): no change.
│                            # NO Acknowledgments. NO clamp. NO buttons.

site/src/routes/abstract/
└── [poster_id]/+page.svelte # MODIFIED. Pass `mode="permalink"` to
                             # DetailPanel.

tests/
├── test_book_figure_normalise.py       # NEW
├── test_book_toc.py                    # NEW
├── test_book_author_index_buckets.py   # NEW
├── test_book_margins.py                # NEW (skip-aware; real-corpus
│                                       # part is conditional)
└── test_ui_data_acknowledgments.py     # NEW

site/src/tests/
├── unit/detail_panel_modes.test.ts     # NEW
└── e2e/permalink_show_more.spec.ts     # NEW
```

**Structure Decision**: stays within the existing layout. The `DetailPanel` component is the surgical separation point — a single `mode` prop keeps the in-grid drawer's behaviour intact while enabling the new UX on the permalink page. Figure normalisation lives in `_copy_figure` (the existing joblib-parallel call-site). TOC + author-index changes are local to `assemble_pdf.py`. Margins are a preamble change with a new `--margins` CLI flag.

## Phase 0 — research

See `research.md`. Seven decisions:

- **R1** — Brief-preview CSS: `display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden` (works in Chrome / Edge / Safari / Firefox 68+ — all OHBM-attendee target browsers). Toggle = remove the `clamped` class to release.
- **R2** — "Show more" visibility: pre-render text-length heuristic (≥ 280 chars typically wraps past 3 lines at the permalink page's column width + body font size). Trade-off: ~5% false-negative on long-but-narrow content vs the JS cost of a `scrollHeight` measurement per section per render. Heuristic wins.
- **R3** — Mode separation on `DetailPanel.svelte`: a single `mode: 'panel' | 'permalink'` prop (default `'panel'`). The conditional logic is wrapped in `{#if mode === 'permalink'}` branches inside the existing render. No duplicate component.
- **R4** — Figure normalisation: ALWAYS re-encode (even when the source is already a small JPEG) so the output is deterministic regardless of source compression history. Byte-copy fallback ONLY on `PIL.UnidentifiedImageError`. Source PNG with transparency converts to RGB before JPEG save (white-fill background).
- **R5** — 3-column TOC: emit as a pandoc-friendly raw-LaTeX `longtable` block in the front-matter markdown. Columns: `P{0.8cm} P{12cm} P{1cm}` (right-aligned poster, justified title with wrap, right-aligned page). The page column reads from the assembler's `chunk_offsets`. Skips entries whose poster_id is in the failure list.
- **R6** — Author-index buckets: Python-side post-process on the already-sorted `author_index`. Group key = `unicodedata.normalize('NFKD', last_name)[0].upper()` if alpha A–Z else `'Other'`. Bucket order = A, B, …, Z, Other. Emit `## <letter>` header before each bucket in the appendix markdown.
- **R7** — Margins: `\\usepackage[margin=0.65in]{geometry}` for the `tight` preset. Two separate header-includes files (`header-includes.tex` tight default, `header-includes-loose.tex` recovers the LaTeX book-class ~1in default). The book CLI's `--margins` flag selects which file gets passed to `pandoc -H`. This sidesteps tex-conditional plumbing.

## Phase 1 — design artefacts

- **`data-model.md`** — entity shapes for `AcknowledgmentSection` (string), `PermalinkSectionState` (client-side `Map<string, boolean>`), `NormalisedFigureAsset` (path + format + dimensions + fallback flag), `TocRow` (poster_id, title, page), `AuthorIndexBucket` (letter, entries). Includes the parquet-emit shape for the new `sections.acknowledgments` field (no schema-version bump needed; STRUCT field addition is backward-compatible).
- **`contracts/cli.md`** — `ohbmcli book` delta:
  - New `--margins {tight,loose}` flag (default `tight`).
  - No other CLI surface changes.
- **`contracts/permalink-page.md`** — UI contract for the permalink page:
  - DOM structure with `data-testid` attributes the Playwright test can target.
  - Class names + state semantics (`.section-clamped`, `.section-expanded`, button labels).
  - Section iteration order (Introduction → Methods → Results → Conclusion → Acknowledgments; Acknowledgments suppressed when empty).
- **`quickstart.md`** — operator runbook for the v2 build (figure normalisation expectations, new TOC sample, margin preset switching).

## Complexity Tracking

> No constitutional violations — table omitted.
