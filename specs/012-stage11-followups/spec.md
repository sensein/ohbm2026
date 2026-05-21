# Feature Specification: Stage 11.1 — book PDF pipeline + standby schema + housekeeping

**Feature Branch**: `012-stage11-followups`
**Created**: 2026-05-20
**Status**: Draft
**Input**: User description: "let's do 11.1 in addition to the plans stated earlier look into the history and memory of this repo to surface prior punted elements"

## Clarifications

### Session 2026-05-20

- Q: DOCX strategy commitment for US3 → A: Retire `--format docx` entirely (option B). `ohbmcli book --format docx` errors with a clear pointer at `--format md` and `--format pdf`. Drops the implementation + maintenance burden of a 2.8 GB artefact Word can't open.
- Q: PDF author-index strategy for US1 → A: Two-pass assembly with real page numbers (option A). Pass 1 renders per-abstract chunks (cached) and concatenates them into a draft PDF; chunk page offsets are measured via `pikepdf`. Pass 2 emits a small index appendix with `\setcounter{page}{<measured>}` + `\printindex` and concatenates. Page numbers in the back-of-book index match the printed pagination, preserving the print use case the spec's "publication-quality" promise depends on.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Per-abstract parallel + cached PDF rendering (Priority: P1)

The Stage 11 book exporter ships a working markdown bundle and an acceptable DOCX, but the PDF path never produced a real-corpus output: every iteration of the LaTeX compile was an 8-15 minute single-pass that aborted on the first problematic abstract, leaving no usable artefact and no way to diagnose which one of 3,242 entries triggered the failure. Organizers can't ship a print PDF. This story redesigns the PDF pipeline so each abstract is rendered independently, cached by content hash, and reassembled into a single book; a single corrupt abstract gets isolated and skipped instead of killing the whole build, and unchanged abstracts skip re-rendering on subsequent runs.

**Why this priority**: a publication-quality PDF is the canonical deliverable Stage 11 promised and didn't ship. Every other 11.1 item is housekeeping; this is the load-bearing one.

**Independent Test**: run the new pipeline against the real corpus on a machine with pandoc + Tectonic installed. Verify (a) the produced PDF contains every accepted abstract, (b) the build completes in under 10 minutes on the first run and under 60 seconds on a repeat run with no input change, (c) introducing a deliberately-malformed abstract in the corpus produces a successful build that EXCLUDES that abstract and logs the failure in `provenance.json`, (d) the produced PDF has a real page-numbered author index at the back.

**Acceptance Scenarios**:

1. **Given** the accepted-abstract corpus, **When** the operator runs the per-abstract PDF pipeline for the first time, **Then** the system renders each abstract independently in parallel, caches each by content hash under `data/cache/book/abstracts/`, assembles the per-abstract PDFs into a single `book.pdf` with a unified front matter (title page + TOC) and back matter (author index with global page numbers), and writes `provenance.json` recording the pandoc + LaTeX-engine versions, the cache hit/miss counts, and any per-abstract failures.
2. **Given** a successful first run, **When** the operator re-runs the same command with no input change, **Then** every per-abstract render is a cache hit and the assembly + author-index computation completes in under 60 seconds.
3. **Given** a corpus containing one abstract whose body causes Tectonic to raise an unrecoverable error, **When** the operator runs the pipeline, **Then** the build completes, the failing abstract is OMITTED from the assembled PDF, the failure is recorded in `provenance.json` under `failed_abstracts` with the abstract's poster_id + the LaTeX stderr captured for diagnosis, and the remaining 3,241 abstracts render normally.

---

### User Story 2 - Standby-block schema redesign (Priority: P2)

The Stage 11 implementation stored each abstract's stand-by windows as two UTC timestamps in the parquet — `poster_standby: {first, second}` typed as `TIMESTAMP[ms, UTC]`. This forced the UI's facet-recomputer to call `Intl.DateTimeFormat` 6,500+ times per filter click; with three formatter constructions per call, the click froze the browser long enough that tabs were killed. A memoisation patch (`fix/standby-perf-and-collapse`) kept the existing schema and added a per-input-ms cache that effectively reduces real-world work to 8 distinct slot keys. This story redesigns the on-disk shape so the cache becomes unnecessary and the UI can never regress: each abstract carries TWO 1-byte indices into an 8-row global lookup table of program windows.

**Why this priority**: the symptom is fixed in prod via the memo cache, but the underlying data shape still invites the same hot-path regression every time someone touches this code. The fix is a small, principled schema change.

**Independent Test**: rebuild the data package against the redesigned schema; verify the parquet's `abstracts` table carries `standby_first_index` + `standby_second_index` as INT8 columns referencing a new `standby_slots` table with one row per program window (UTC start + end + Paris-local display label). The UI's `standby_block` facet returns the same set of options as before, the per-abstract values match the prior data byte-for-byte after lookup, and the `Intl.DateTimeFormat` memo cache can be removed without regression.

**Acceptance Scenarios**:

1. **Given** the redesigned data shape, **When** the UI computes the `standby_block` facet over 3,240 abstracts, **Then** the per-facet recompute runs in under 5 milliseconds, no `Intl.DateTimeFormat` instances are constructed at facet-time (the formatters are needed only at first-render of the global lookup table), and the option-list is byte-identical to the prior memo-cached output.
2. **Given** a Stage-6 builder run against a corpus with no standby data, **When** the builder emits the parquet, **Then** the `standby_slots` table is empty and abstracts carry null indices; the UI hides the standby block and facet (existing fallback behaviour).

---

### User Story 3 - Retire DOCX export (Priority: P2)

The Stage 11 DOCX export embeds all ~4,700 figures into a single Word document; even at `--max-image-width=1800`, the real-corpus result is 2.8 GB — large enough that Word refuses to open it on most machines. Once US1's per-abstract PDF pipeline lands, the canonical artefacts are (1) the markdown bundle for editorial work, (2) the assembled PDF for print, and (3) per-abstract PDF caches for spot-checks. The DOCX path covered no use case those three don't and carried a maintenance burden disproportionate to its value. This story retires `--format docx` end-to-end: the CLI errors with a clear pointer at the surviving formats, the docx implementation is removed, and every doc / quickstart / README mention is updated.

**Why this priority**: removes a footgun (an artefact users may attempt to produce, finding Word refuses to open it), simplifies the codebase, and prevents the operator confusion of "which artefact do I share with editors?".

**Independent Test**: run `ohbmcli book --format docx` against the real corpus. Verify (a) the command exits non-zero, (b) stderr names the alternative formats (`md`, `pdf`) and the rationale (DOCX retired in 11.1, see specs/012-stage11-followups/), (c) no `book.docx` file is produced, (d) `--format all` no longer attempts DOCX (only `md` + `pdf`).

**Acceptance Scenarios**:

1. **Given** the corpus, **When** the operator runs `ohbmcli book --format docx`, **Then** the command exits with a non-zero status, prints `docx export was retired in Stage 11.1 — use --format md (markdown bundle) or --format pdf (per-abstract PDF pipeline) instead`, and writes no output file.
2. **Given** the retired path, **When** the operator opens the README / quickstart / `docs/abstracts-book-plan.md`, **Then** every prior mention of DOCX-as-canonical is removed or replaced with a "retired in 11.1" pointer; the CLI `--format` choices show only `{md, pdf, all}`; the optional `[abstracts_book]` extra in pyproject.toml drops `python-docx` (no longer needed).

---

### User Story 4 - CI label-aware deploy verification + state-key naming (Priority: P3)

Two consecutive merges (PR #26, PR #27) carrying the `deploy-production` label demoted to sandbox because GitHub's `listPullRequestsAssociatedWithCommit` API lagged the merge. A retry-loop fix (PR #28) added 6 × 5 s linear backoff but the operator has never seen the loop actually save a deploy — the next labelled merge could still race, and the operator only finds out by checking prod manually. This story does two small things: (a) instrument the retry loop with explicit telemetry that surfaces in the run log even when the lookup hits on the first try, so we can VERIFY the fix works on the next labelled merge; (b) rename Stage 1's `state_key` so it no longer collides verbally with Stage 6's `corpus_state_key`, since the two are independent fingerprints and operators routinely confuse them.

**Why this priority**: P3 because both are paper cuts, not blockers. But they're cheap enough that bundling them into the 11.1 PR avoids a separate housekeeping PR.

**Independent Test**: (a) trigger a labelled merge and confirm the workflow log shows the retry-loop telemetry (attempt count, time to first hit). (b) Grep the codebase for `state_key`; verify Stage 1's value is now `fetch_state_key` (or similar) and Stage 6 keeps `corpus_state_key`; all docs + tests + provenance files are updated coherently.

**Acceptance Scenarios**:

1. **Given** a PR labelled `deploy-production` is merged, **When** the deploy-ui workflow runs, **Then** the resolve-target step's log contains `PR-association lookup: attempt 1/6 succeeded on first call (XXX ms)` (or the equivalent multi-attempt message), the deploy target resolves to `production`, and the prod site updates without manual `workflow_dispatch` intervention.
2. **Given** the renamed state-key, **When** an operator reads the README / quickstart / any provenance.json, **Then** the field name unambiguously identifies which stage's fingerprint it represents; no two distinct values share the name `state_key`.

---

### Edge Cases

- **Per-abstract PDF cache invalidation**: when pandoc or the LaTeX engine is upgraded, the cached PDFs may no longer match what a fresh compile would produce. Cache key MUST include `pandoc_version` + `pdf_engine_version` + the header-includes file's content hash + the style choice — so an engine upgrade invalidates the cache automatically.
- **Per-abstract PDF assembly fails on one abstract**: the assembly step is robust to per-abstract failures (skipping the failed entry); the global front matter (TOC) + back matter (author index) are recomputed against the surviving set.
- **Standby schema migration**: the existing parquet on Dropbox uses the old shape; the new builder MUST write the new shape but the in-browser decoder MUST detect either shape from the parquet's manifest schema version and accept both for one deploy cycle (no surprise breakage).
- **CI retry-loop telemetry**: if GitHub's API never recovers within the 30 s budget, the workflow still falls through to `sandbox` per the existing behaviour — telemetry is observational, not a hard gate.
- **State-key rename roll-out**: the new name appears in all NEW provenance files; existing provenance files on disk continue to use the old name. Tooling that reads provenance MUST accept both for the rest of the lifetime of those artefacts.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The PDF pipeline MUST render each abstract independently into a per-abstract PDF page-set, cache each result under a key derived from the abstract's markdown content + pandoc version + LaTeX-engine version + header-includes hash + style choice, and reuse the cache on subsequent runs when the key is unchanged.

- **FR-002**: The PDF pipeline MUST tolerate per-abstract failures: a Tectonic / pandoc non-zero exit for one abstract MUST NOT abort the build. The failing abstract is OMITTED from the assembled PDF, the stderr capture + poster_id are recorded under `provenance.failed_abstracts`, and the remaining abstracts render normally.

- **FR-003**: The assembled `book.pdf` MUST carry a real page-numbered author index at the back. The index is built via a **two-pass assembly**: pass 1 concatenates the per-abstract PDF chunks (each cached, FR-001) into a draft PDF and measures each chunk's global page offset via `pikepdf`; pass 2 emits a small index appendix (a separate pandoc invocation against a stub markdown that carries the `\index{...}` entries with `\setcounter{page}{<measured>}` markers + `\printindex`) and concatenates it onto the draft. Page numbers in the back-of-book index match the printed pagination — not the per-chunk local pagination.

- **FR-004**: Re-running the PDF build with no input change MUST complete in under 60 seconds (cache-hit-only path: assembly + provenance, no pandoc invocations).

- **FR-005**: The data-package schema MUST add a `standby_slots` table (one row per distinct program window: UTC start, UTC end, Paris-local display label) and the `abstracts` table MUST carry `standby_first_index` + `standby_second_index` as nullable INT8 columns referencing rows in the new table. The existing `poster_standby: {first, second}` STRUCT column is removed.

- **FR-006**: The browser-side decoder MUST consume the new shape and present the same `standby_block` facet options + per-abstract display values that the prior shape produced. The `Intl.DateTimeFormat` memo cache added in PR #27 can be removed once the decoder no longer needs to format per-abstract timestamps at facet-recompute time.

- **FR-007**: The `ohbmcli book --format docx` path MUST be retired: the command exits non-zero with a stderr message naming the surviving formats (`--format md`, `--format pdf`) and the rationale (DOCX retired in 11.1). The docx implementation in `render_via_pandoc.to_docx` + the docx-only test module MUST be removed. The `[abstracts_book]` optional extra in `pyproject.toml` MUST drop `python-docx`. The README, quickstart, and `docs/abstracts-book-plan.md` MUST be updated to remove DOCX-as-canonical wording and add a "retired in 11.1" pointer.

- **FR-008**: The `deploy-ui` workflow's resolve-target step MUST log every attempt of the PR-association retry loop (attempt count, success vs. retry, elapsed time) so the operator can VERIFY the retry-loop saved a deploy on the next labelled merge.

- **FR-009**: Stage 1's emitted `state_key` field MUST be renamed to a name that distinguishes it from Stage 6's `corpus_state_key` (suggested: `fetch_state_key`). All places in the codebase that produce or consume this field — provenance writers, checkpoint loaders, the build_ui_data CLI, docs — MUST be updated coherently. Existing provenance artefacts on disk keep the legacy field name; consumers MUST accept both for the lifetime of those artefacts.

- **FR-010**: The Stage 11.1 PR's spec, plan, tasks, and quickstart documents MUST explicitly list which historically-deferred items are IN scope (the four above) and which remain OUT of scope (cross-conference Phase 5/6, Range-fetch lazy load for parquet, Native STRUCT migration, Tufte sidenote conversion, PAGEREF DOCX field-code injection, 3D UMAP lasso enhancements, neurovlm text embeddings, README walkthroughs from #3) — so the next person knows where the line was drawn.

### Key Entities *(include if feature involves data)*

- **AbstractPdfChunk**: one abstract's per-abstract PDF. Carries its poster_id, page count, cache key, and the bytes (cached on disk under `data/cache/book/abstracts/<cache-key>.pdf`).
- **StandbySlot**: one program window — UTC start, UTC end, Paris-local display label (e.g. `Day 1 (Mon Jun 15) · 13:45-14:45`). 8 rows for OHBM 2026.
- **AssembledBook**: the final unified PDF — sequence of `AbstractPdfChunk` bytes + global TOC + global author index. The author index references global page numbers (computed during assembly), not per-chunk local ones.
- **PerAbstractFailure**: a record per abstract whose pandoc/LaTeX compile aborted — poster_id, stderr capture, attempt timestamp. Aggregated in `provenance.failed_abstracts[]`.

### Constitution Alignment *(mandatory)*

- **CA-001**: All Python execution for this feature MUST use the repository-local `.venv/bin/python` interpreter or `uv` targeting that interpreter.
- **CA-002**: The plan and tasks MUST identify the failing tests (or named existing tests that are tightened) that land before each behaviour-changing slice — notably (a) per-abstract cache hit/miss correctness, (b) per-abstract failure isolation, (c) standby-schema-roundtrip equivalence, (d) DOCX-retirement contract (the CLI rejects `--format docx` with the right exit code + stderr).
- **CA-003**: Renaming Stage 1's `state_key` changes a documented field name; README, quickstart, and `docs/reproducibility-vision.md` MUST be updated in the same change.
- **CA-004**: No new credentials introduced; pandoc + Tectonic are local-binary system deps already documented in Stage 11.
- **CA-005**: All produced books, intermediate per-abstract PDFs, and the cache directory MUST land under gitignored roots (`data/cache/book/`, `data/outputs/book/`).
- **CA-006**: Per-abstract failures MUST surface explicitly (stderr captured, poster_id logged in provenance); they MUST NOT be silently dropped without trace. The build summary printed to stderr MUST name the failure count + path to provenance.
- **CA-007**: Cache invalidation MUST be driven by content-hashed inputs (markdown + pandoc version + engine version + header-includes hash + style); the cache MUST NOT rely on a hardcoded version allow-list.
- **CA-008**: The assembled book carries `provenance.json` with the same shape as Stage 11 plus the new `cache_hit_count`, `cache_miss_count`, `failed_abstracts[]`, and `assembly_time_seconds` fields. No absolute / `~/` paths.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can produce a complete real-corpus `book.pdf` (3,200+ accepted abstracts) in under 10 minutes on a typical laptop on the first run.
- **SC-002**: A repeated run with the same inputs produces the same `book.pdf` in under 60 seconds (cache-hit-only).
- **SC-003**: An operator can introduce a deliberately-broken abstract into the corpus and the build still completes, omitting only that abstract and recording the failure in `provenance.json`.
- **SC-004**: Clicking the `standby_block` facet on a 3,200-abstract production deploy completes the per-facet recompute in under 5 ms; the page does not stutter or freeze, and no `Intl.DateTimeFormat` instances are constructed during the recompute.
- **SC-005**: `ohbmcli book --format docx` exits non-zero with a stderr message that names the surviving formats (`--format md`, `--format pdf`) and the rationale. No `book.docx` is produced; the README, quickstart, and `docs/abstracts-book-plan.md` carry no DOCX-as-canonical wording.
- **SC-006**: The next merge of a `deploy-production`-labelled PR resolves to `production` on the first try (no manual `workflow_dispatch` follow-up), AND the workflow log contains explicit attempt-count telemetry so the operator can verify the retry loop saved the deploy.
- **SC-007**: Grepping the codebase for ambiguous `state_key` usage returns zero matches outside the renamed Stage 1 callsite; every provenance.json field is unambiguously named.

## Assumptions

- Operators running the new PDF pipeline have `pandoc >= 3.x` + a LaTeX engine (Tectonic or xelatex) on PATH per the Stage 11 quickstart.
- The Stage 4 analysis rollup (topics, clusters, UMAP) is keyed by `poster_id`; a small number of removed-after-rollup abstracts in subsequent fetches is silently dropped from the UI's cluster/topic context without warning. Large-scale corpus refresh (>50 abstract changes) still requires a Stage-4 re-run, tracked separately.
- The Stage 10 single-file parquet shape stays the canonical wire format; the new `standby_slots` table is a sibling of the existing `abstracts` table inside the same parquet file (no separate file, no extra HTTP fetch).
- The Stage 11.1 PR ships ONE markdown bundle + the new PDF pipeline as the canonical exports. DOCX is retired (US3): the implementation, the optional `python-docx` dependency, and the docx-only test module are removed; the CLI rejects the format with a clear stderr pointer.
- The CI retry-loop telemetry surfaces in the workflow log; no new dashboard / observability product is introduced.

## Out of Scope (explicitly deferred)

Listed for FR-010 clarity. Each item was named in prior specs / memory / issues and is **not** part of Stage 11.1:

- **Cross-conference Phase 5/6** — UI-side cross-conference linking artefact (`specs/010-export-redesign/research.md` §B3). Deferred until a second conference is ingested.
- **Range-fetch lazy load for Parquet** — per-shard row-group HTTP Range requests (`specs/010-export-redesign/research.md` Phase 4). Deferred pending wire-bytes measurement.
- **Native STRUCT migration** — DuckDB/SQLite intermediate layer (`specs/010-export-redesign/research.md` Phase 4). Deferred pending bench rework.
- **Tufte sidenote conversion per citation** — full `\sidenote{}` per superscript numeral (`specs/011-abstracts-book/research.md` R7). Deferred; current Tufte styling is typography-only.
- **PAGEREF field-code injection in DOCX** — Word page-numbered author index (`specs/011-abstracts-book/research.md` R3). Moot as of 11.1: DOCX export is retired (US3).
- **3D UMAP lasso enhancements** (`specs/008-ui-rewrite/spec.md` FR-006). Out-of-scope from Stage 6.
- **neurovlm as text embedding model** (open issue #29). Future embedding-model exploration.
- **Stage 1 README walkthroughs** (open issue #3, T029/T030). Documentation backlog.
- **prod-e2e regressions tracked under issues #22 + #23** — independent investigation, not bundled here.
