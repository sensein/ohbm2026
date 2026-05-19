---
description: "Task list — Book of Abstracts"
---

# Tasks: Book of Abstracts

**Input**: Design documents from `/specs/011-abstracts-book/`
**Prerequisites**: `plan.md` ✔, `spec.md` ✔, `research.md` ✔, `data-model.md` ✔, `contracts/cli.md` ✔, `quickstart.md` ✔.

**Tests**: Required. Constitution principle IV (plan-first, test-first) plus the spec's `CA-002` mandates failing tests for every behaviour-changing slice land before the corresponding implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]** — can run in parallel (different files, no dependencies)
- **[Story]** — which user story this task belongs to (`US1`, `US2`, `US3`)
- Exact file paths included in every description.

## Path Conventions

Single-project layout (per `plan.md § Project Structure`): production code under `src/ohbm2026/book/`, tests under `tests/`, fixtures under `tests/fixtures/book/`, operator docs under `docs/`, optional dev shim under `scripts/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton + dependency declarations. No code-behaviour changes; tests not applicable for this phase per the template's stated exception ("pure setup / dependency wiring").

- [X] T001 Create empty package skeleton at `src/ohbm2026/book/__init__.py` and the templates subdirectory `src/ohbm2026/book/templates/.keep`; commit as a single skeleton commit so subsequent module commits diff cleanly.
- [X] T002 [P] Add the `abstracts_book` optional extra to `pyproject.toml` (`[project.optional-dependencies] abstracts_book = ["markdownify>=0.13", "beautifulsoup4>=4.12", "python-docx>=1.1", "pikepdf>=8"]`) and `uv pip install --python .venv/bin/python ".[abstracts_book]"` to populate the venv.
- [X] T003 [P] Add `data/outputs/book/` to the gitignore landscape — verify the existing root-level `data/` rule covers it; add an explicit `book__*/` rule to `.gitignore` only if `git check-ignore data/outputs/book/book__test/` reports unignored.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Modules and fixtures every user story consumes. NO test/impl alternation here — foundation is impl-only; the tests that verify these foundations live inside each user story's test block and run after the foundation lands.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 Add `BookBuildError(OhbmStageError)` to `src/ohbm2026/exceptions.py` as a sibling to `Stage1Error` / `Stage2Error`, mirroring the existing typed-exception pattern (constructor accepts a `details: str | None = None` kwarg for pandoc stderr capture).
- [X] T005 [P] Create `src/ohbm2026/book/sections.py` with the `BODY_SECTION_NAMES` tuple constant (per `research.md § R4`: `Introduction`, `Methods`, `Results`, `Conclusion`, `Acknowledgement`, `References/Citations`) plus a documented rationale comment citing CA-007.
- [X] T006 [P] Create `src/ohbm2026/book/model.py` with frozen-slots dataclasses (`AuthorAffiliation`, `Author`, `FigureBlock`, `BodySection`, `ReferencesBlock`, `BookEntry`, `AuthorIndexEntry`, `Book`) exactly as `data-model.md § Layer 2` specifies. `BodySection.markdown` and `ReferencesBlock.markdown` carry markdown (not HTML).
- [X] T007 [P] Create `src/ohbm2026/book/html_to_md.py` exposing `html_to_pandoc_md(html: str) -> str`, applying the conversion-rule table from `research.md § R2` (BeautifulSoup pre-pass to convert `<sup>x</sup>` → `^x^` and `<sub>x</sub>` → `~x~`, strip `id="isPasted"` + inline `style="..."`, then `markdownify` does the rest with `heading_style="ATX"`, `bullets="-"`). Pure function, no I/O.
- [X] T008 [P] Create `src/ohbm2026/book/figure_check.py` exposing `probe_figure(local_path: pathlib.Path) -> (pixel_width: int | None, pixel_height: int | None, error: str | None)` — opens with `PIL.Image.open`, returns dims on success, returns `(None, None, "asset missing" | "unreadable: <Pillow error>")` otherwise. Adds `effective_dpi(pixel_width: int, display_width_inches: float) -> float` helper.
- [X] T009 Create `src/ohbm2026/book/corpus.py` exposing `load_book(corpus_path, authors_path, withdrawn_path, assets_root, sort_order, include_sections) -> Book`. Drives the filter (withdrawn / null-poster-id / accepted_for ∉ {Poster, Oral}), builds the authors-by-submission-id map, calls `html_to_md` for body sections + references at the corpus boundary (R2), assembles the in-memory `Book`. Depends on T004 (exception), T005 (sections), T006 (model), T007 (html_to_md), T008 (figure_check).
- [X] T010 [P] Create the test fixture corpus under `tests/fixtures/book/` — `abstracts.json` with 5 synthetic accepted abstracts: poster_ids `0001`-`0005` covering (a) both Methods + Results figures, (b) single figure, (c) zero figures, (d) two Results figures of the **same type** to exercise the `-1`/`-2` index suffix in the figure-naming contract, (e) a deliberately-missing figure asset to exercise FR-008. `authors.json` with 6 distinct authors, one shared between two abstracts to exercise index aggregation. `abstracts_withdrawn.json` with one withdrawn entry whose `id` matches a row in `abstracts.json`. `assets/*.png` valid PNGs sized **2400×2400 px** (synthetic flat-colour content; PNG compression keeps these under ~10 KB each) so the figure-resolution probe in T017 has data that can pass the `≥ 300 DPI at 6.5"-display-width` assertion (resolves the prior fixture / test-target mismatch — see analysis finding U1). Total directory size budget: < 100 KB.

**Checkpoint**: Foundation ready — every user story can now exercise the loader, model, and HTML→md converter against the fixture corpus.

---

## Phase 3: User Story 1 — Canonical printable book in poster-id order (Priority: P1) 🎯 MVP

**Goal**: Produce a publication-quality PDF + markdown bundle of every accepted abstract, sorted by `poster_id`, with figures, references, and a LaTeX-page-numbered author index — sourced entirely from Stage-1 artefacts, zero Stage-2 / LLM content.

**Independent Test**: `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format pdf --sort poster_id --corpus tests/fixtures/book/abstracts.json --authors tests/fixtures/book/authors.json --withdrawn tests/fixtures/book/abstracts_withdrawn.json --assets-root tests/fixtures/book/assets --output-root /tmp/bookmvp` produces both `book.md` and `book.pdf` whose abstract-count matches the fixture's accepted+non-withdrawn count, sample figures embed at the right path, and the author index contains every fixture author with at least one page reference (PDF) or anchor (md).

### Tests for User Story 1 ⚠️ Write FIRST and watch fail

- [X] T011 [P] [US1] `tests/test_book_corpus.py` — assert (a) withdrawn-id entry is dropped, (b) null-poster-id entry is dropped, (c) non-`Poster`/`Oral` entry is dropped, (d) returned `Book.entries` count matches the expected survivor count from `tests/fixtures/book/`, (e) authors are joined by `submission_id` correctly.
- [X] T012 [P] [US1] `tests/test_book_html_to_md.py` — exercise every row of the R2 conversion table: `<sup>1,2</sup>` → `^1,2^`, `<sub>x</sub>` → `~x~`, `<ol><li>A</li><li>B</li></ol>` → `1. A\n2. B`, `<p style="…" id="isPasted">x</p>` → `x` (style + id dropped), `<strong>` → `**…**`, `&plusmn;` → `±`. Pure function, no fixture loading.
- [X] T013 [P] [US1] `tests/test_book_no_ai_audit.py` — (a) walk the import graph of `ohbm2026.book.*` and assert no module under `ohbm2026.stage2_*` or `ohbm2026.enrich_*` is imported (SC-006 by construction); (b) after building a `book.md` from the fixture corpus, grep its bytes for every ECO code in `src/ohbm2026/data/eco_top_codes.json` and the tool names from `stage2_claims.py` (`verify_source_quote`, `lookup_eco_code`, `dedupe_check`); assert zero matches.
- [X] T014 [P] [US1] `tests/test_book_figure_check.py` — (a) probe each fixture PNG; verify `pixel_width`/`pixel_height` match the 2400×2400 fixture dimensions; (b) probe a deliberately-missing path; verify `error == "asset missing"`; (c) probe a corrupt-bytes file; verify `error.startswith("unreadable:")`; (d) `effective_dpi(3000, 6.5) == pytest.approx(461.5, rel=1e-3)` (numeric check); (e) the 2400 px fixture at a 6.5" display width hits ~369 DPI which clears the 300 DPI threshold (verifies the assertion path used by T017).
- [X] T015 [P] [US1] `tests/test_book_author_index.py` — build the index from the fixture `Book`; assert every distinct author from `authors.json` appears in `Book.author_index`, the shared-across-two-abstracts author has both `poster_ids`, and entries are sorted by `(last.casefold(), first.casefold())`.
- [X] T016 [P] [US1] `tests/test_book_markdown.py` — render `book.md` + `fig_assets/` from the fixture corpus; assert (a) `^## Abstract 0001 ` line exists for each surviving fixture entry, (b) every `![…](fig_assets/<submission_id>-<poster_id>-<type>[-<index>].<ext>)` reference resolves to a file under the flat `fig_assets/` directory, (c) every file under `fig_assets/` is referenced from `book.md`, (d) for an abstract with two figures of the same type the `-1` / `-2` index suffix appears and for single-figure-of-type the suffix is absent (verifies the contract from `data-model.md § Layer 3`), (e) running the render twice produces byte-identical `book.md` (SC-007a), (f) `\index{Lastname, F.}` markers appear inline beside every author name, (g) `\printindex` appears exactly once near the end, (h) a `<details><summary>Author Index (anchor links)</summary>` block follows `\printindex` with one bullet per distinct fixture author whose link targets `#abstract-NNNN` (matches `data-model.md § Layer 3 / Markdown bundle`).
- [X] T017 [P] [US1] `tests/test_book_render_pdf.py` — `unittest.skipUnless(shutil.which("pandoc") and shutil.which("xelatex"), …)`; invoke `render_via_pandoc.to_pdf` against the fixture-built `book.md`; assert (a) pandoc exit code 0, (b) emitted `book.pdf` has `page_count >= len(book.entries) + 2` via `pikepdf.Pdf.open().pages` — one page minimum per abstract plus the title page and the author-index page (the fixture has 5 surviving entries → ≥ 7 pages), (c) sample 3 figures' embedded image streams measure ≥ 300 DPI at display width derived from the page geometry, (d) re-running with the same input produces a `book.pdf` whose `pdftotext` output is byte-identical (SC-007b).

### Implementation for User Story 1

- [X] T018 [P] [US1] Implement `src/ohbm2026/book/sort.py` — start with `by_poster_id(entries)` returning `tuple(sorted(entries, key=lambda e: e.poster_id))`. Add a `SortStrategy = Callable[[tuple[BookEntry, ...]], tuple[BookEntry, ...]]` Protocol so US2 can extend without churning the call site.
- [X] T019 [US1] Implement `src/ohbm2026/book/author_index.py` — `build_author_index(entries) -> tuple[AuthorIndexEntry, ...]` aggregates by `(display_name, sort_key_last_first)`; sorts by `sort_key_last_first`; per-entry `poster_ids` is the sorted ascending tuple of all `BookEntry.poster_id` the author appears on. Depends on T006 (model).
- [X] T020 [P] [US1] Create `src/ohbm2026/book/templates/book.md.template` — top-of-book skeleton with the YAML metadata block (title / date / sort), the `\makeindex` directive, the abstract iteration placeholder, and the `\printindex` + `<details>`-anchor-index back matter (per `data-model.md § Layer 3 / Markdown bundle`).
- [X] T021 [P] [US1] Create `src/ohbm2026/book/templates/header-includes.tex` — LaTeX preamble loaded via pandoc `-H`: `\usepackage{makeidx}`, `\makeindex`, `\usepackage{graphicx}`, `\graphicspath{{./fig_assets/}}`, `\usepackage{microtype}`.
- [X] T022 [US1] Implement `src/ohbm2026/book/render_markdown.py` — `emit_book_md(book: Book, output_dir: pathlib.Path) -> None`. Loads the template via `importlib.resources`; emits the YAML header, one section per abstract (heading with `{#abstract-NNNN}` identifier, author list with inline `\index{…}` markers, body sections in `BODY_SECTION_NAMES` order, figure references with `{#fig-NNNN-<type>[-<index>]}` identifiers, references block), `\printindex`, and the `<details>` anchor-link back matter. Copies each figure to the flat `fig_assets/<submission_id>-<poster_id>-<type>[-<index>].<ext>` path per the contract in `data-model.md § Layer 3` — `<type>` derived from the figure's question_name (lower-cased, ` Figure` suffix stripped, non-word chars dash-replaced); `<index>` appended only when an abstract has > 1 figure of the same type. Depends on T006, T019, T020.
- [X] T023 [US1] Implement `src/ohbm2026/book/render_via_pandoc.py` — `to_pdf(md_path, output_path, style)` builds the pandoc argv per `research.md § R3` (xelatex engine, `-H header-includes.tex`, `--standalone --toc`, `--resource-path=<book_dir>`). Captures stderr; non-zero exit raises `BookBuildError`. After pandoc, calls `_strip_pdf_metadata(output_path)` (R6): opens with `pikepdf`, overwrites `/CreationDate` + `/ModDate` to `D:19700101000000Z`, saves. Depends on T004, T021.
- [X] T024 [US1] Implement `src/ohbm2026/book/provenance.py` — `write_provenance(book, output_dir, *, pandoc_version=None, xelatex_version=None, figures_below_threshold)` writes `provenance.json` per the schema in `data-model.md § Layer 3`. Captures `code_revision_short` + `code_revision_full` via `git rev-parse HEAD`. Refuses to write absolute paths (asserts each path field has no leading `/` or `~`). Depends on T006.
- [X] T025 [US1] Implement `src/ohbm2026/book/cli.py` — argparse for the MVP-needed flags (`--format {md,pdf}`, `--sort poster_id`, `--corpus`, `--authors`, `--withdrawn`, `--assets-root`, `--output-root`, `--state-key`). Includes the system-dep preflight (`shutil.which("pandoc")` / `shutil.which("xelatex")` when `--format` touches PDF) per `contracts/cli.md § System-dependency preflight`. Computes state-key per `contracts/cli.md § State-key derivation`. Orchestrates: `load_book` → `by_poster_id` → `build_author_index` → `emit_book_md` → `_audit_no_ai_content` → (if PDF) `to_pdf` → `write_provenance`. Depends on T009, T018, T019, T022, T023, T024.
- [X] T026 [US1] Wire the `book` subcommand into `src/ohbm2026/cli.py` — add the dispatch case mirroring the existing Stage 2 / Stage 3 patterns; entry function delegates to `ohbm2026.book.cli.main`.
- [X] T027 [P] [US1] Update `README.md` — add a "Stage 11 — Book of abstracts" entry under "Current Latest Step" with one invocation example (`ohbmcli book --format pdf --sort poster_id`); add `book` to the CLI-subcommand list. (CA-003.)
- [X] T027a [P] [US1] Update `docs/reproducibility-vision.md` — extend the project-charter pipeline narrative to include the book-export step as the final reader-facing deliverable. Note that the book sources only Stage-1 artefacts (zero LLM content) per FR-002. (FR-011 / CA-003.)
- [X] T028 [P] [US1] Create `docs/abstracts-book-plan.md` — operator-facing summary that points at `specs/011-abstracts-book/quickstart.md` for the system-dep install steps and the four canonical invocations (md / pdf / pdf-tufte / all). (FR-011 / CA-003.)

**Checkpoint**: User Story 1 fully functional and testable independently. The MVP — a `--format pdf --sort poster_id` invocation against the real corpus — produces a publication-quality PDF book. Stop here if you want to ship the MVP increment.

---

## Phase 4: User Story 2 — Alternate sort orders (Priority: P2)

**Goal**: Add `--sort title` and `--sort first_author` so the same book content can be reordered for editorial or attendee-facing use.

**Independent Test**: Run the MVP invocation three times — once each with `--sort poster_id`, `--sort title`, `--sort first_author`. Each output directory holds an independent build whose abstract order matches the asserted sort key; all three produce the same author index.

### Tests for User Story 2 ⚠️ Write FIRST and watch fail

- [X] T029 [P] [US2] `tests/test_book_sort.py` — build a `Book` from the fixture corpus three times (once per sort strategy); assert (a) `poster_id` order is numeric ascending, (b) `title` order is case-insensitive lexicographic with poster_id tie-break, (c) `first_author` order is by `(last.casefold(), first.casefold(), title.casefold())`; (d) each sort produces the SAME set of entries (no entries dropped/added across sort strategies).

### Implementation for User Story 2

- [X] T030 [US2] Extend `src/ohbm2026/book/sort.py` with `by_title(entries)` and `by_first_author(entries)` following the sort-key rules in `data-model.md § Layer 2 § Construction rules § 7`.
- [X] T031 [US2] Extend `src/ohbm2026/book/cli.py` — broaden `--sort` choices to `{poster_id, title, first_author}`; dispatch to the appropriate strategy by name; ensure `--state-key` derivation incorporates the sort choice (it already does per T025, just verify).

**Checkpoint**: All three sort orders work independently. User Stories 1 + 2 both functional.

---

## Phase 5: User Story 3 — Multi-format export: DOCX + `--format all` (Priority: P3)

**Goal**: Add the DOCX export and the `--format all` convenience for editorial / archival workflows.

**Independent Test**: Run `ohbmcli book --format all --sort poster_id` against the fixture corpus; verify the output directory contains `book.md` + `book.pdf` + `book.docx` + `fig_assets/` + `provenance.json`; open `book.docx` with `python-docx` and confirm it has heading-1 paragraphs for each abstract and clickable anchor-link entries in the author index.

### Tests for User Story 3 ⚠️ Write FIRST and watch fail

- [X] T032 [P] [US3] `tests/test_book_render_docx.py` — `unittest.skipUnless(shutil.which("pandoc"), …)`; render fixture corpus to DOCX; assert (a) pandoc exit code 0, (b) `python-docx.Document(path).paragraphs` includes a Heading-1 per abstract, (c) the embedded inline-shape count matches the fixture's figure count, (d) re-running produces a `book.docx` whose `pandoc -t plain` output is byte-identical (SC-007b).

### Implementation for User Story 3

- [X] T033 [US3] Extend `src/ohbm2026/book/render_via_pandoc.py` — add `to_docx(md_path, output_path)` with the pandoc argv from `research.md § R3` (`--to=docx`, no LaTeX flags). After pandoc, call `_strip_docx_metadata(output_path)`: open the `.docx` as a `zipfile.ZipFile`; rewrite `docProps/core.xml` to set `dcterms:created` + `dcterms:modified` to `1970-01-01T00:00:00Z`; re-zip with sorted entries + zeroed mtimes + `ZIP_DEFLATED` level 9 (R6).
- [X] T034 [US3] Extend `src/ohbm2026/book/cli.py` — broaden `--format` choices to `{md, pdf, docx, all}`; when `all`, orchestrate `emit_book_md` → `to_pdf` → `to_docx` in sequence (md first since pdf/docx both depend on it); preflight checks both pandoc (always) and xelatex (only when `pdf` or `all`).

**Checkpoint**: All three user stories independently functional. Feature is feature-complete for the spec's three priorities.

---

## Phase N: Polish & Cross-Cutting Concerns

**Purpose**: Optional Tufte styling (FR-006b), determinism / debug escape hatches, the forward-compat `--include-section` flag, dev shim, the constitution check, and the SC sweep against the real corpus.

- [ ] T035 [P] Create `src/ohbm2026/book/templates/header-includes-tufte.tex` — Tufte variant: `\documentclass{tufte-book}[nobib,nofonts]`, ET-Book font with TeX-Gyre fallback, ragged-right setting, plus the same `makeidx`/`graphicx`/`microtype` from the plain header (R7).
- [ ] T036 [P] Extend `src/ohbm2026/book/cli.py` and `render_via_pandoc.py` — add `--style {plain,tufte}` flag (default `plain`); when `tufte`, `to_pdf` swaps the `-H` argument to point at `header-includes-tufte.tex`; provenance.style records the choice; DOCX path ignores the flag.
- [ ] T037 [P] Add the Tufte case to `tests/test_book_render_pdf.py` — extra test method `test_pdf_tufte_style` that runs with `--style tufte`, skips if ET-Book font isn't available on the LaTeX install (detect via xelatex log), and asserts the PDF has the Tufte page-geometry (~4.21" body width) when font is present.
- [ ] T038 [P] Add the `--no-determinism-strip` escape hatch to `src/ohbm2026/book/cli.py` + `render_via_pandoc.py`; when set, the `_strip_pdf_metadata` / `_strip_docx_metadata` post-processes are skipped. Tests in `tests/test_book_determinism.py` verify the metadata WAS stripped by default and is preserved when the flag is set.
- [ ] T039 [P] Add the `--include-section <name>` (repeatable) forward-compat flag to `src/ohbm2026/book/cli.py`; thread through to `corpus.load_book` so the effective body-section set is `BODY_SECTION_NAMES + tuple(extras)`. Logs a `WARN` once if any extra name appears in zero responses across the corpus.
- [ ] T040 [P] Create `scripts/run_build_book.py` — thin shim that imports `ohbm2026.book.cli:main` and re-exports the same CLI. Useful for ad-hoc dev runs (matches the pattern of `scripts/run_enrich_abstracts.py`).
- [ ] T041 Run the full real-corpus pipeline end-to-end: `time PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format all --sort poster_id` against `data/primary/abstracts.json`. Verify wall time < 15 min total (SC-001 ceiling) and record the actual seconds in the PR description (target 10 min). Verify `provenance.abstract_count` matches the corpus's accepted-non-withdrawn count (SC-002); `provenance.no_ai_audit.matches_found == 0` (SC-006); `provenance.figures_below_resolution_threshold` is reviewed and either short or annotated. **Output not committed** (per CA-005).
- [ ] T042 Run `.specify/scripts/bash/constitution-check.sh --full` from repo root. Expect exit 0. Address any reported violations (most likely candidates: a typo in `BookBuildError` parent class lineage that the secret-pattern grep mis-fires on; an accidentally-staged `data/outputs/book/…` artefact).
- [ ] T043 Run `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v -p "test_book_*"` and verify every test module passes (including the skip-aware PDF/DOCX cases on a machine with pandoc + xelatex installed).
- [ ] T044 Manual smoke per `specs/011-abstracts-book/quickstart.md` steps 3–8 — confirm each invocation succeeds and the produced output matches its quickstart description. Capture any quickstart-doc drift; fix in the same commit.
- [ ] T045 Update `specs/011-abstracts-book/tasks.md` — mark every T001-T044 as `[X]` once their verification passes. Outstanding `[ ]` items ride into a follow-up commit with explicit rationale in the body. Open the PR `feat(stage11): book of abstracts — markdown-canonical via pandoc` linking to `specs/011-abstracts-book/{spec,plan}.md` and summarising the SC sweep (SC-001 wall-time actual, SC-002 abstract count, SC-006 audit result, SC-007 determinism check).

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 Setup** — no dependencies; start immediately.
- **Phase 2 Foundational** — needs Phase 1; **blocks every user story**.
- **Phase 3 US1 (P1)** — needs Phase 2 complete; this is the MVP.
- **Phase 4 US2 (P2)** — needs Phase 2 complete; can start in parallel with US1 implementation tasks once US1 tests are written and `sort.py` (T018) lands, but its test (T029) needs the fixture from T010 only.
- **Phase 5 US3 (P3)** — needs Phase 2 complete; can start in parallel with US1 implementation tasks once `render_via_pandoc.py` (T023) lands. The DOCX path (T033) extends the same module.
- **Phase N Polish** — needs all user stories complete (or scoped to MVP).

### Within-story dependencies (US1)

- All US1 test tasks T011-T017 are `[P]` — different files, no inter-dependencies. They can be written in parallel.
- US1 impl: T018 (sort) and T019 (author_index) and T020/T021 (templates) are `[P]` — different files.
- T022 (render_markdown) depends on T006 (model) + T019 (author_index) + T020 (template).
- T023 (render_via_pandoc) depends on T004 (exception) + T021 (header-includes.tex).
- T024 (provenance) depends on T006 (model).
- T025 (cli) depends on T009 (corpus loader) + T018 (sort) + T019 (author_index) + T022 (render_md) + T023 (render_pdf) + T024 (provenance) — it's the final orchestration step.
- T026 (wire into ohbmcli) depends on T025.
- T027 + T027a + T028 (docs) are `[P]` once US1 is shape-stable (after T025).

### Within-story dependencies (US2)

- T029 (test) depends on T010 (fixtures).
- T030 (sort extension) depends on T018 (sort scaffold).
- T031 (cli flag) depends on T025 (cli scaffold) + T030.

### Within-story dependencies (US3)

- T032 (test) depends on T010 (fixtures).
- T033 (DOCX render) depends on T023 (render_via_pandoc PDF path establishes the subprocess wrapper).
- T034 (cli `--format all`) depends on T025 (cli scaffold) + T033.

### Parallel opportunities

- **Setup**: T002 || T003 (different concerns).
- **Foundational**: T005 || T006 || T007 || T008 || T010 (independent modules + fixture build); T009 then serialises after the four `[P]` modules it imports.
- **US1 tests**: T011 || T012 || T013 || T014 || T015 || T016 || T017 (all `[P]`).
- **US1 impl**: T018 || T020 || T021 (different files), then T019/T022/T023/T024 partially parallel, then T025/T026 serial.
- **Across stories**: once T025 lands, US2 impl (T030/T031) and US3 impl (T033/T034) can be developed in parallel by two contributors with no merge conflicts (different files / different `--format`/`--sort` branches in cli.py).
- **Polish**: T035 || T036 || T038 || T039 || T040 all `[P]` (different files / different flags).

---

## Parallel example: User Story 1 tests in parallel

```bash
# All seven US1 test files can be authored simultaneously:
Task: "tests/test_book_corpus.py — filter logic"
Task: "tests/test_book_html_to_md.py — conversion rule table"
Task: "tests/test_book_no_ai_audit.py — import-graph walk + book.md grep"
Task: "tests/test_book_figure_check.py — Pillow probe + effective_dpi"
Task: "tests/test_book_author_index.py — every author present, aggregation"
Task: "tests/test_book_markdown.py — md bundle determinism + figure copy-out"
Task: "tests/test_book_render_pdf.py — pandoc PDF (skip if absent)"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup (T001-T003) — ~30 min.
2. Phase 2 Foundational (T004-T010) — ~3-4 h. **Critical**: blocks every story.
3. Phase 3 US1 (T011-T028) — ~1.5 days. Tests land first (T011-T017); impl proceeds T018 → T025 → T026 → docs.
4. **STOP and VALIDATE**: run `ohbmcli book --format pdf --sort poster_id` against the real corpus; check provenance against the SC list.
5. Ship the MVP increment.

### Incremental delivery

1. Setup + Foundational → fixture corpus runnable.
2. US1 → MVP PDF + markdown bundle. Ship.
3. US2 → alternate sort orders. Ship.
4. US3 → DOCX + `--format all`. Ship.
5. Polish → Tufte styling, debug flags, real-corpus SC sweep. Ship.

### Parallel team strategy

- Two contributors after T025 lands:
  - **A** writes T029-T031 (US2 sort).
  - **B** writes T032-T034 (US3 DOCX).
  - No merge conflicts — different sort strategies + a new method on render_via_pandoc.

---

## Notes

- `[P]` tasks = different files, no in-flight dependencies.
- Every test task is written BEFORE its corresponding implementation task within the same user-story phase; tests are expected to fail until impl lands.
- Foundational impl (T004-T010) is verified by US1's tests — that's by design; the foundation needs to exist before the tests can target it, but the tests run before US1's impl tasks (T018+).
- Commit each verified slice as it lands (Principle V); do not batch hours of work into one commit.
- Output artefacts (PDFs, DOCXes, fig_assets, provenance.json) under `data/outputs/book/` are gitignored by the existing root `data/` rule; verify with `git check-ignore` in T003 if uncertain.
- The `tests/fixtures/book/` directory (T010) is the ONLY committed binary content; total size budgeted at < 50 KB so it doesn't trip the no-committed-data rule.
- Never silence failures or bypass verification gates to make a task look done; surface errors and address root cause (CA-006).
- Stop at any checkpoint to validate the story independently.
