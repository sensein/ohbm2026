---
description: "Task list — Stage 12 book layout polish + permalink UX"
---

# Tasks: Stage 12 — book layout polish + acknowledgments + permalink UX

**Input**: Design documents from `/specs/013-book-layout-polish/`
**Prerequisites**: `plan.md` ✔, `spec.md` ✔ (clarified), `research.md` ✔, `data-model.md` ✔, `contracts/cli.md` ✔, `contracts/permalink-page.md` ✔, `quickstart.md` ✔.

**Tests**: Required. Constitution principle IV (plan-first, test-first) plus `CA-002` mandates failing tests for every behaviour-changing slice land before the corresponding implementation. Five load-bearing tests are named in plan.md.

**Organization**: Tasks are grouped by user story. US1 and US1b both touch `site/src/lib/components/DetailPanel.svelte` + `site/src/routes/abstract/[poster_id]/+page.svelte`; the task ordering within Phase 3 serialises US1 (data plumbing) before US1b (toggles) so the new section flows through before the UX overlay lands. US2, US3, US4, US5 are wholly independent of US1/US1b.

## Format: `[ID] [P?] [Story?] Description`

- **[P]** — different files, no dependencies on incomplete tasks; safe to run in parallel.
- **[Story]** — `US1`, `US1b`, `US2`–`US5` per spec. Setup / Foundational / Polish tasks carry no story label.
- Exact file paths included in every description.

## Path Conventions

Single-project layout per `plan.md § Project Structure`. Production code under `src/ohbm2026/`, site under `site/src/`, tests under `tests/` (Python) and `site/src/tests/` (TypeScript). LaTeX templates under `src/ohbm2026/book/templates/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: No new deps; this phase is the empty-but-honest opt-in step. No behaviour change.

- [X] T001 `[abstracts_book]` extra confirmed unchanged: markdownify/beautifulsoup4/pikepdf/Pillow/joblib (no python-docx since Stage 11.1; no new deps for Stage 12).
- [X] T002 `site/package.json` confirmed unchanged. No new TypeScript deps.
- [X] T003 [P] Cache invalidation confirmed via `hash_header_includes` from Stage 11.1 — modifying the header-includes file bytes auto-changes the per-chunk cache key.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No shared types or helpers required across stories — each story uses self-contained data structures. This phase only documents that fact.

- [X] T004 (Vacuous per analysis C2.) Confirmed each US owns its own dataclasses; no foundational shared code needed.

---

## Phase 3: User Story 1 — Acknowledgments on the permalink page (Priority: P1) 🎯 MVP

**Goal**: Add the `sections.acknowledgments` field to the data-package envelope; wire it through the SvelteKit detail-panel component in `mode='permalink'` only; the in-grid drawer is unchanged.

**Independent Test**: rebuild the parquet against the real corpus; open `/abstract/<poster_id>/` for an abstract whose corpus record has a non-empty `Acknowledgement` response; verify an "Acknowledgments" heading + the text. Open the in-grid drawer in the browse view for the same abstract; verify no new section appears.

### Tests for User Story 1 ⚠️ Write FIRST and watch fail

- [X] T005 [P] [US1] `tests/test_ui_data_acknowledgments.py` — 4 cases (present / empty / absent / independent). All green post-impl.

### Implementation for User Story 1

- [X] T006 [US1] `src/ohbm2026/ui_data/abstracts.py` — added `"acknowledgments": "Acknowledgement"` to `_SECTION_QUESTION` map + `"acknowledgments": _section(...)` to the per-record `sections` block.
- [X] T007 [P] [US1] `site/src/lib/shards.ts` — added optional `acknowledgments?: string` to the sections type with JSDoc explaining v1↔v2 shard compatibility.

**Checkpoint**: `sections.acknowledgments` flows through the data-package shard; the UI side has a typed slot for it but doesn't render anywhere yet.

---

## Phase 4: User Story 1b — Brief-preview UX on the permalink page (Priority: P1)

**Goal**: Add a `mode: 'panel' | 'permalink'` prop to `DetailPanel.svelte`. In `mode='permalink'`, render the Acknowledgments section (from US1), apply CSS `line-clamp: 3` preview to the 5 left-column verbatim sections, emit per-section "Show more/Show less" buttons (when text length ≥ 280 chars), and emit a column-scoped "Show all/Collapse all" master toggle. The in-grid drawer's behaviour (default `mode='panel'`) is unchanged.

**Independent Test**: open `/abstract/<poster_id>/` for an abstract with long sections. Verify (a) each clampable section starts in 3-line clamp with a "Show more" button, (b) clicking it expands ONLY that section + relabels to "Show less", (c) the master "Show all" button expands every section + relabels to "Collapse all", (d) clicking "Collapse all" returns every section to the clamp, (e) a short section (< 280 chars) renders without any toggle button, (f) the in-grid drawer in the browse view is unchanged.

### Tests for User Story 1b ⚠️ Write FIRST and watch fail

- [X] T008 [P] [US1b] Scope adjusted: full component-mount test would require adding `@testing-library/svelte` (a new dep this stage explicitly avoided). Instead extracted the pure helpers to `site/src/lib/permalink_section_state.ts` (PERMALINK_SECTION_KEYS, isClampable, masterToggleLabel, nextStateAfterMasterToggle) and wrote `site/src/tests/unit/permalink_section_state.test.ts` with 15 cases. All green.
- [X] T009 [P] [US1b] `site/src/tests/e2e/permalink_show_more.spec.ts` — 4 Playwright tests: clampable section starts in preview + per-section toggle; master toggle expands all + relabel; acknowledgments section when corpus has it; in-grid drawer unchanged. Skip-aware via `UI_DATA_AVAILABLE`.

### Implementation for User Story 1b

- [X] T010 [US1b] `DetailPanel.svelte` — added `mode: 'panel' | 'permalink'` prop (default `'panel'`), `permalinkExpanded` state, `togglePermalinkSection` + `togglePermalinkAll` handlers, reactive `clampableExpandedMap` / `masterLabel` / `anyClampable` derived state, and `permalinkExpanded = {}` reset on abstract navigation.
- [X] T011 [US1b] Section iteration array branches on `mode`: panel-mode keeps the 4-section list; permalink-mode adds `['acknowledgments','Acknowledgments']`. The existing `{#if sbody}` guard naturally suppresses empty acknowledgments.
- [X] T012 [US1b] Permalink-mode section render uses `.verbatim-section` + `.section-clamped` / `.section-expanded` / `.section-short` classes + `.section-body-clamped` modifier. `isClampable()` from `$lib/permalink_section_state` drives toggle visibility.
- [X] T013 [US1b] Master toggle rendered as `<button class="master-toggle">` above the section list when `mode === 'permalink' && anyClampable`. Click handler `togglePermalinkAll()` uses the helper module's pure `nextStateAfterMasterToggle`.
- [X] T014 [US1b] CSS added: `.verbatim-section`, `.section-label-permalink`, `.section-body-clamped` (`-webkit-line-clamp: 3` + standard `line-clamp: 3` fallback), `.section-toggle`, `.master-toggle`. ARIA: `aria-expanded` on per-section toggles, `aria-pressed` + `aria-controls` on master.
- [X] T015 [US1b] `site/src/routes/abstract/[poster_id]/+page.svelte` — passes `mode="permalink"` to `DetailPanel`.

**Checkpoint**: permalink page shows brief-preview + toggles + Acknowledgments. In-grid drawer untouched (no Acknowledgments, no clamp, no toggles).

---

## Phase 5: User Story 2 — Normalised figure assets (Priority: P2)

**Goal**: Replace `_copy_figure`'s preserve-format-or-resize behaviour with always-re-encode-to-JPEG-q90-at-150-DPI-cap. Pillow-unopenable sources fall back to byte-copy + audit entry. Build proceeds without abort on a single bad source.

**Independent Test**: run the book pipeline against the real corpus + clean `fig_assets/`. Verify (a) every file under `fig_assets/` has `.jpg` extension after the run, (b) every file's pixel width ≤ 975, (c) JPEG quality is 90 (probe with `identify -verbose` or PIL), (d) total bytes ≥ 30% smaller than the prior Stage 11.1 run against the same corpus, (e) `provenance.figures_normalised_count` is populated and `provenance.figures_normalised_with_fallback[]` is a list (probably empty).

### Tests for User Story 2 ⚠️ Write FIRST and watch fail

- [X] T016 [P] [US2] `tests/test_book_figure_normalise.py` — 5 cases (large PNG → 975 px JPEG q=90; small JPEG re-encoded; transparent PNG flattens to RGB on white; unreadable source → byte-copy fallback; reset clears registry). All green.

### Implementation for User Story 2

- [X] T017 [US2] `render_markdown.py:_copy_figure` rewritten: always re-encodes to JPEG q=90 with `effective_cap = min(FIGURE_WIDTH_CAP=975, max_width)`. Forces `.jpg` extension on dest. PNG-with-transparency flattens to RGB on white. Returns None (registry side-effect).
- [X] T018 [US2] Module-level `_figure_normalise_fallbacks: list[dict]` + byte-copy fallback on `(UnidentifiedImageError, OSError)`. Audit entries carry `{poster_id, filename, error_reason}`.
- [X] T019 [US2] `get_normalise_fallbacks()` + `reset_normalise_fallbacks()` helpers exposed for the CLI/provenance writer.
- [X] T020 [US2] Caller in `emit_book_md` unchanged; `_ext_for(fig)` now returns `"jpg"` unconditionally so the markdown body's `![Figure](fig_assets/...)` references align with the on-disk `.jpg` files.
- [X] T021 [US2] `provenance.py` — when `assembled is not None`: writes `figures_normalised_count`, `figures_normalised_with_fallback[]`, AND `toc_page_count` (front-matter chunk's page count). Bumps `pdf_pipeline_version` to `stage-12`. Resets the registry.

**Checkpoint**: fig_assets/ is uniform JPEG q=90 ≤ 975 px wide. Audit list captures the few problem files.

---

## Phase 6: User Story 3 — 3-column TOC (Priority: P2)

**Goal**: Replace pandoc's default flat-section TOC with a `longtable` carrying `Poster | Title | Page`. Sourced from `chunk_offsets`. Omits failure-isolated abstracts.

**Independent Test**: build the book PDF after the change. Verify (a) the TOC pages render as a 3-column ruled table with `Poster | Title | Page` headers, (b) every accepted abstract appears as exactly one row, (c) poster_id is right-aligned numeric (no leading-zero confusion), (d) the `Page` column matches the assembled-PDF's actual first body page of each abstract, (e) the TOC page count ≤ 50% of the prior pandoc-default TOC, (f) failure-isolated abstracts are absent from the TOC.

### Tests for User Story 3 ⚠️ Write FIRST and watch fail

- [X] T022 [P] [US3] `tests/test_book_toc.py` — 12 cases: 8 `_latex_escape` + 4 `_build_toc_markdown` (longtable headers, failure-isolated omission, page column alignment, escape in title cell). All green.

### Implementation for User Story 3

- [X] T023 [US3] `assemble_pdf.py:_build_toc_markdown(book_entries, chunk_offsets)` — emits a markdown block with `# Table of Contents {.unnumbered}` + raw-LaTeX `longtable{r p{10cm} r}` carrying Poster/Title/Page rows. Failure-isolated abstracts (absent from `chunk_offsets`) are omitted.
- [X] T024 [US3] `render_via_pandoc.py:_build_front_matter_md` — accepts optional `toc_block: str` kwarg; when provided, embeds it after the title page (replacing the legacy `\tableofcontents` macro).
- [X] T025 [US3] `to_pdf` orchestrator uses a two-pass front-matter render: v1 with placeholder page values → measure v1 page count → compute real offsets → v2 with real values. Stderr warning emitted on drift (rare; only when title widths push row count across page boundaries).
- [X] T026 [US3] `provenance.toc_page_count` = `assembled.front_matter_pages` (effectively all-TOC after Stage 12). Emitted via the same provenance block that landed `figures_normalised_count` in US2.
- [X] T027 [US3] `_latex_escape(text)` helper in `assemble_pdf.py` mapping `\\ { } $ & % # _ ^ ~` to their LaTeX escapes.
- [X] BONUS: `header-includes.tex` now includes `\usepackage{longtable}` (required for the new TOC env; otherwise pandoc/Tectonic errors with "Environment longtable undefined").

**Checkpoint**: TOC is a compact 3-column table; ≥ 50% page-count reduction vs pandoc default.

---

## Phase 7: User Story 4 — Author-index bucket headers (Priority: P2)

**Goal**: Group `_build_index_markdown`'s output by Unicode-folded last-name initial; emit `## A`, `## B`, …, `## Z`, `## Other` headers before each non-empty bucket.

**Independent Test**: open the back of the book PDF after the change. Verify (a) a `## A` section header precedes the first entry whose last name starts with A, (b) every initial-letter transition has its own `## X` header, (c) names like "Östen" appear under the `O` section (Unicode-folded), (d) names whose first letter is non-alpha appear under a final `## Other` section, (e) author-index sort within each bucket is unchanged from Stage 11.1 (last_name, first_name).

### Tests for User Story 4 ⚠️ Write FIRST and watch fail

- [X] T028 [P] [US4] `tests/test_book_author_index_buckets.py` — 7 tests covering `_bucket_letter` (ASCII / Unicode-fold / numeric / symbol / empty) + `_build_index_markdown` bucket order + within-bucket sort preserve + empty-bucket suppression. All green.

### Implementation for User Story 4

- [X] T029 [US4] `_bucket_letter(last_name)` — NFKD-fold the FIRST non-whitespace char; ASCII-A-Z passes through; non-alpha first char → `"Other"`.
- [X] T030 [US4] `_build_index_markdown` refactored: groups by bucket; iterates `_BUCKET_ORDER = (A,B,…,Z,Other)`; emits `## <letter>` header before each non-empty bucket; preserves within-bucket sort order.
- [X] T031 [US4] Author-index tests + assembly tests both green.

**Checkpoint**: author index is letter-bucketed; navigable in ≤ 2 page-turns from index start.

---

## Phase 8: User Story 5 — Tighter book margins (Priority: P3)

**Goal**: `\usepackage[margin=0.65in]{geometry}` in the tight preset (new default). Optional `--margins=loose` flag recovers the LaTeX `book` class default ~1 in margins for backward-compatibility.

**Independent Test**: build the book twice — once with `--margins=tight` (default) and once with `--margins=loose`. Verify (a) the tight build's `book.pdf` has ≥ 15% fewer total pages, (b) `provenance.figures_below_resolution_threshold` count is unchanged (no figures pushed below DPI floor by tighter content width), (c) the figure-resolution audit shows no new entries.

### Tests for User Story 5 ⚠️ Write FIRST and watch fail

- [X] T032 [P] [US5] `tests/test_book_margins.py` — 9 tests: tight/loose/per-abstract templates carry expected geometry directives; `_header_includes_path(style, margins)` returns the right file; cli `--margins` parses + defaults to `tight`; invalid values rejected. All green.

### Implementation for User Story 5

- [X] T033 [US5] `header-includes.tex` adds `\usepackage[margin=0.65in]{geometry}` + `\usepackage{longtable}` (Stage 12 US3) as the first preamble lines.
- [X] T034 [P] [US5] `header-includes-loose.tex` (new) — same preamble minus the geometry import; book-class default ~1in margins.
- [X] T035 [US5] `per-abstract.tex.template` — adds `\usepackage[margin=0.65in]{geometry}` so per-chunk dimensions match the assembled book.
- [X] T036 [US5] `_header_includes_path(style, *, margins="tight")` returns `header-includes.tex` (tight) or `header-includes-loose.tex` (loose); Tufte style unchanged.
- [X] T037 [US5] `cli.py` — `--margins {tight,loose}` flag (default `tight`) threaded into `to_pdf(..., margins=args.margins)`.
- [X] T038 [US5] `to_pdf(..., margins="tight")` signature added; `_header_includes_path(style, margins=margins)` call wired.

**Checkpoint**: tight default is the new normal; loose flag recovers the prior layout for one-off comparisons.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T039 [P] Run `.specify/scripts/bash/constitution-check.sh --full` — expect exit 0.
- [ ] T040 [P] Run the full `unittest` suite — `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`. Expect all tests pass (with the new test modules added) + the existing `test_book_*` suite green.
- [ ] T041 [P] Run `cd site && pnpm exec vitest run`. Expect all tests pass including the new `detail_panel_modes.test.ts`.
- [ ] T042 Run `pnpm build` in `site/`. Expect zero errors.
- [ ] T043 Real-corpus smoke: `time PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format pdf --sort poster_id`. Record cold-cache wall time (chunk cache + fig_assets caches all warm from Stage 11.1 — the only re-render is per-chunk because the header-includes hash changed). Verify the new TOC + bucketed index + tight margins in the assembled PDF. Record SC numbers (page count, figure-bundle size, TOC page count) in the PR description.
- [ ] T044 Real-corpus parquet rebuild: `scripts/build_ui_data.py`; verify `sections.acknowledgments` field present on the abstracts table; drag-replace `data.parquet` on Dropbox; bump `OHBM2026_UI_DATA_PACKAGE_SHA256` repo variable; trigger prod deploy.
- [ ] T045 PR-preview manual smoke: open the deployed `/pr-<N>/ohbm2026/abstract/<poster_id>/` for an abstract with long sections; verify the 3-line clamp + per-section toggles + master toggle; verify Acknowledgments visible.
- [ ] T046 Open the PR titled `feat(stage12): book layout polish + permalink show-more`. Apply `deploy-production` label. Body references each US's acceptance criteria + the SC numbers from T043.
- [ ] T047 Mark every T001–T046 as `[X]` in this file as their verification passes. Any outstanding `[ ]` rides into a follow-up commit with rationale.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 Setup** — no behaviour change; can start immediately.
- **Phase 2 Foundational** — documentation only (no foundational code).
- **Phase 3 US1 (MVP)** — depends on Phase 1. Data-package field addition + UI type slot. Doesn't block US1b directly but provides its data dependency.
- **Phase 4 US1b** — depends on Phase 3 (the data field must exist before the UI renders it). Touches `DetailPanel.svelte`.
- **Phase 5 US2** — wholly independent of US1/US1b. Touches `render_markdown.py` + `provenance.py`.
- **Phase 6 US3** — wholly independent. Touches `assemble_pdf.py` + `render_via_pandoc.py`.
- **Phase 7 US4** — wholly independent. Touches `assemble_pdf.py` (same file as US3 — serialise within Phases 6+7 if same dev; otherwise rebase-friendly because the two changes touch different functions).
- **Phase 8 US5** — wholly independent. Touches `cli.py` + `render_via_pandoc.py` + templates/.
- **Phase 9 Polish** — needs all stories complete (or the MVP scope subset).

### Within-story dependencies

**US1**:
- T005 (test) is `[P]` with the impl tasks (different file).
- T006 (abstracts.py) is the Python-side impl; T007 (shards.ts) is the TS-side type. Independent files → `[P]`.

**US1b**:
- T008 + T009 (tests) are `[P]` — different test surfaces (vitest unit + Playwright e2e).
- T010 (prop) is the gate.
- T011 (Acknowledgments in iteration) depends on T010.
- T012 (clamp class + toggle) depends on T010.
- T013 (master toggle) depends on T010.
- T014 (CSS) is `[P]` with T011/T012/T013 (same file but different sections; commit logically together).
- T015 (route passes `mode`) depends on T010 (prop must exist).

**US2**:
- T016 (test) is the gate.
- T017–T021 are sequential within `render_markdown.py` + `provenance.py`. T020 (caller update) depends on T017.

**US3**:
- T022 (test) is the gate.
- T023 (helper) depends on T022.
- T024 (front-matter MD injection) depends on T023.
- T025 (orchestration sequence) depends on T024.
- T026 (provenance) depends on T024.
- T027 (latex escape) is `[P]` with T023 (different helper in same file; commit together).

**US4**:
- T028 (test) is the gate.
- T029 (`_bucket_letter`) is `[P]` with T030.
- T030 (`_build_index_markdown` refactor) depends on T029.
- T031 (regression check) depends on T030.

**US5**:
- T032 (test) is the gate.
- T033 + T034 + T035 (template edits) are all `[P]` — different files.
- T036 (`_header_includes_path` signature) depends on T034.
- T037 (cli flag) depends on T036.
- T038 (to_pdf signature) depends on T036 + T037.

### Parallel opportunities

- **Phase 1**: T001 || T002 || T003.
- **US1 tests + impl**: T005 (test) parallel with T006/T007 once test fails (test-first; impl unblocked).
- **US1b tests**: T008 || T009 (different test surfaces).
- **US1b impl**: T010 must land first; T011–T014 then run mostly in parallel (different sections of same file but logically distinct).
- **US2**: T016 (test) before T017; T017–T021 sequential.
- **Across stories**: US2 + US3 + US4 + US5 can proceed in parallel after Phase 2 (no file overlap between US2 / US3 / US4 / US5 except US3 and US4 both touch `assemble_pdf.py` — serialise those two within one developer or in two follow-on commits).
- **Polish**: T039 || T040 || T041 (different harnesses).

---

## Implementation Strategy

### MVP first (US1 + US1b)

The P1 stories ship together as one PR slice:
1. Phase 1 + 2 (~ 10 min).
2. US1 (T005 → T006 → T007) — data field flows through. ~ 30 min.
3. US1b (T008/T009 → T010 → T011/T012/T013/T014 → T015) — UX overlay. ~ 1-2 hours.
4. **STOP and VALIDATE**: open the permalink page for a long-section abstract; click toggles; verify the in-grid drawer is unchanged.

That increment is shippable on its own — adds Acknowledgments to the permalink page + the brief-preview UX, doesn't touch the book pipeline.

### Incremental delivery

After the MVP lands:
1. US2 (figure normalisation) — ship.
2. US3 (3-col TOC) + US4 (author-index buckets) — ship together since they both touch `assemble_pdf.py`.
3. US5 (margins) — ship.
4. Polish phase + open the PR.

OR (recommended for atomic shipping): bundle all six stories into one Stage 12 PR (mirrors Stage 11.1's bundling approach). The change is medium-sized and the failure isolation per-story is clean.

### Parallel team strategy

Three contributors after Phase 2:
- **A** drives US1 + US1b (the load-bearing UI work).
- **B** drives US2 + US5 (book figure + layout; touches `render_markdown.py` + templates/).
- **C** drives US3 + US4 (TOC + author-index; both in `assemble_pdf.py` — serialise within C).

---

## Notes

- `[P]` tasks = different files, no in-flight dependencies.
- Every test task lands BEFORE its corresponding implementation task per CA-002.
- Commit each verified slice as it lands (Principle V); do not batch hours of unrecorded work.
- The figure normalisation always-on behaviour is intentional: the user explicitly asked for "the same format" so the operator does NOT get a `--figure-format=preserve` flag in v1. Documented in `contracts/cli.md`.
- The author-index `Other` bucket is the ONLY non-letter bucket. If a future operator needs further partitioning (e.g. numeric vs symbol), that's a follow-up.
- The `--margins=loose` flag is the back-door for an operator who needs to reproduce a pre-Stage-12 layout. Not removed even when nobody uses it; the cost is one extra template file.
