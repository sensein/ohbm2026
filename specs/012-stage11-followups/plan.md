# Implementation Plan: Stage 11.1 — book PDF pipeline + standby schema + housekeeping

**Branch**: `012-stage11-followups` | **Date**: 2026-05-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/012-stage11-followups/spec.md`

## Summary

Four bundled stories on top of Stage 11:

1. **Per-abstract parallel + cached PDF** (P1, US1) — the load-bearing piece. Each abstract renders to its own small PDF (cached by content+toolchain hash); the assembler concatenates the per-abstract PDFs into a single `book.pdf` and uses a **two-pass** trick to get a real page-numbered author index. Per-abstract failures isolate cleanly: the offending entry drops out of the assembled PDF, the rest renders, and `provenance.json` carries the failure record.
2. **Standby-block INT8 schema** (P2, US2) — replaces the parquet's `poster_standby: {first, second}` STRUCT with a separate 8-row `standby_slots` table + two INT8 indices per abstract. UI's hot-path `Intl.DateTimeFormat` memo cache becomes unnecessary; per-facet recompute drops to constant time.
3. **DOCX retirement** (P2, US3) — `ohbmcli book --format docx` exits non-zero with a stderr pointer at md / pdf; the docx implementation, python-docx dependency, and docx-only test module are removed; README + quickstart updated.
4. **CI telemetry + state-key rename** (P3, US4) — telemetry on the PR-association retry loop so the operator can verify it saved the deploy; Stage 1's `state_key` renamed to `fetch_state_key` so it no longer collides verbally with Stage 6's `corpus_state_key`.

## Technical Context

**Language/Version**: Python 3.14 (repository `.venv`); SvelteKit 2 + Vite 6 + Svelte 5 (existing site).

**Primary Dependencies**:
- *Existing in `[abstracts_book]` optional extra*: `markdownify`, `beautifulsoup4`, `pikepdf`, `Pillow`. **Removed**: `python-docx` (US3 retirement).
- *New / new use*:
  - `joblib` (already in `[analysis]` extra) for parallel per-abstract pandoc invocations.
  - `pikepdf` (already in `[abstracts_book]`) for per-chunk page-offset measurement + PDF concatenation.
- *System binaries* (unchanged from Stage 11): `pandoc >= 3.1` and a LaTeX engine (Tectonic preferred; xelatex fallback).

**Storage**:
- New cache root: `data/cache/book/abstracts/<cache-key>.pdf` (gitignored under existing `data/` rule).
- Output stays at `data/outputs/book/book__<state-key>/` (Stage 11 staging-then-promote contract preserved).
- Parquet output unchanged location (`site/static/data/data.parquet`).

**Testing**:
- `unittest` (project convention). New tests under `tests/`:
  - `test_book_cache.py` — cache key derivation + hit/miss correctness + invalidation on toolchain change.
  - `test_book_assembly.py` — two-pass page-offset measurement + index injection.
  - `test_book_failure_isolation.py` — broken-fixture abstract drops out, rest renders, provenance records the failure.
  - `test_standby_schema.py` — round-trip equivalence (old shape ↔ new shape lookups produce identical per-abstract values + facet keys).
  - `test_docx_retirement.py` — CLI exits non-zero with the right stderr.
  - `test_state_key_rename.py` — Stage 1's provenance fields use the new name; old name still accepted by readers.

**Target Platform**: macOS / Linux developer + CI. Tectonic must auto-fetch the same package set as Stage 11 (no new LaTeX-package requirements introduced by the two-pass index trick).

**Project Type**: Track-A canonical pipeline addition + Stage-6 schema rework + CI workflow patch. Three sub-areas touched: `src/ohbm2026/book/`, `src/ohbm2026/ui_data/`, `.github/workflows/deploy-ui.yml`.

**Performance Goals**:
- SC-001: first-run real-corpus `book.pdf` ≤ 10 min. Per-abstract pandoc/Tectonic ~150 ms each in parallel × 3,242 abstracts / 8 cores ≈ 60 s + assembly ~30 s + index pass ~30 s ⇒ budget comfortable.
- SC-002: cache-hit-only re-run ≤ 60 s — measured time is dominated by `pikepdf` concatenation of 3,242 small PDFs + index pass. Validation: a sustained-write benchmark on the cache directory.
- SC-004: standby_block facet recompute ≤ 5 ms across 3,240 records. INT8-index lookup into a Map<int,SlotMeta> is O(1) per record; total work is one Map.get per record per recompute.

**Constraints**:
- No new system deps beyond Stage 11 (pandoc + Tectonic).
- Cache invalidation MUST be content-driven, never an allow-list.
- Parquet schema version bumps so the in-browser decoder can detect old vs new shape and accept both for the deploy cycle.

**Scale/Scope**: 3,242 accepted abstracts in current corpus; the per-abstract pipeline parallelises across cores. Cache directory at steady state: ~500 KB × 3,242 ≈ 1.5 GB on disk (gitignored).

## Constitution Check

- **I. Venv-only Python**: all entrypoints through `ohbmcli`. The per-abstract pandoc invocations are subprocesses; no system-Python exposure.
- **II. Immutable evidence**: cache + output under gitignored `data/`. The cache is reproducible (content-hashed) so accidental loss is recoverable without committed evidence.
- **III. Resumable, auditable**: the per-abstract cache IS the resumability primitive. A failed mid-build run resumes from the cache on retry; only changed inputs re-render. Provenance records cache hit/miss counts + per-abstract failures.
- **IV. Plan-first, test-first**: failing tests land first per US (see Tasks). The four load-bearing tests:
  (a) cache hit produces byte-identical per-abstract PDF (SC-002);
  (b) broken fixture abstract drops out + failure logged (SC-003);
  (c) standby roundtrip equivalence (SC-004 + FR-006);
  (d) `--format docx` rejection (SC-005).
- **V. Secret-safe**: no credentials. The deploy-ui telemetry uses only public GitHub API calls.
- **VI. Fail loudly**: per-abstract failures captured + recorded; the build summary names the failure count; assembly aborts (not silently) when zero abstracts survive.
- **VII. Discover external state**: standby_slots table content is discovered from the FINAL CSV at build time; INT8 indices are assigned by sort order (deterministic but not hardcoded). The cache key includes discovered `pandoc --version` and engine `--version` output (not a hardcoded allow-list).
- **VIII. Provenance**: every produced `book.pdf` ships with `provenance.json` carrying `cache_hit_count`, `cache_miss_count`, `failed_abstracts[]`, `assembly_time_seconds`, `pandoc_version`, `pdf_engine_version` (renamed from Stage 11's `xelatex_version` per `contracts/cli.md`). No absolute/`~/` paths.

**Re-evaluation (post-design)**: Pass. No constitutional carve-outs needed.

## Project Structure

### Documentation (this feature)

```text
specs/012-stage11-followups/
├── plan.md              # this file
├── research.md          # six decisions (R1-R6)
├── data-model.md        # per-abstract chunk + assembled book + standby_slots
├── quickstart.md        # operator runbook
├── contracts/
│   ├── cli.md           # `ohbmcli book` updates + DOCX rejection contract
│   └── standby.linkml.yaml   # data-package addendum for standby_slots
├── checklists/
│   └── requirements.md  # spec quality (already filled)
└── tasks.md             # produced by /speckit-tasks
```

### Source Code (repository root)

```text
src/ohbm2026/book/
├── cache.py                    # NEW. compute_cache_key() + load_cached_pdf() +
│                               # store_cached_pdf(). Key = sha256 of (markdown
│                               # body + pandoc_version + engine_version +
│                               # header-includes hash + style). Disk layout
│                               # under data/cache/book/abstracts/.
├── render_per_abstract.py      # NEW. Per-abstract pandoc invocation. Takes a
│                               # BookEntry + style + style-header path, emits
│                               # one cached PDF chunk. Used in joblib parallel.
├── assemble_pdf.py             # NEW. Two-pass assembly:
│                               #   Pass 1: concat per-abstract chunks via
│                               #     pikepdf.Pdf.new() → measure each chunk's
│                               #     starting page via running pages-length
│                               #     counter. Front matter (title + TOC)
│                               #     emitted as its own chunk via pandoc.
│                               #   Pass 2: emit index appendix from a stub md
│                               #     containing every \index{...} entry from
│                               #     the assembled chunks + \setcounter{page}
│                               #     + \printindex; concat onto draft.
├── render_via_pandoc.py        # MODIFIED. to_pdf() now delegates to the new
│                               # per-abstract + assemble pipeline. The old
│                               # whole-book pandoc invocation is removed.
│                               # to_docx() is removed entirely. preflight()
│                               # narrows to pandoc + engine (docx-only path
│                               # gone). resolve_pdf_engine() unchanged.
├── cli.py                      # MODIFIED. --format choices become
│                               # {md, pdf, all}. --format docx prints the
│                               # retirement message and exits non-zero
│                               # (typed BookBuildError exit code 2).
├── templates/
│   ├── header-includes.tex     # unchanged
│   ├── header-includes-tufte.tex # unchanged
│   ├── per-abstract.tex.template  # NEW. Minimal preamble used by the
│   │                              # per-abstract pandoc invocation — pulls
│   │                              # in math + microtype + makeidx but NOT
│   │                              # the title page / TOC machinery (those
│   │                              # are emitted only in the front-matter
│   │                              # chunk).
│   └── index-appendix.tex.template  # NEW. \setcounter{page}{N} + a sequence
│                                    # of \index{Lastname, F.} entries (one
│                                    # per surviving abstract's authors) +
│                                    # \printindex. N is the page offset
│                                    # measured during pass 1.
├── render_markdown.py          # unchanged (md bundle path is untouched)
├── corpus.py                   # unchanged (book reads the FINAL CSV
│                               # directly; the standby schema rework
│                               # affects ui_data only).
├── ...                         # rest unchanged

src/ohbm2026/ui_data/
├── formats/
│   └── parquet_single.py       # MODIFIED. Drops poster_standby STRUCT;
│                               # adds new `standby_slots` table emission
│                               # + INT8 standby_first_index +
│                               # standby_second_index on abstracts table.
│                               # Schema version in build_info bumps from
│                               # parquet-single.v1 → parquet-single.v2.
├── abstracts.py                # MODIFIED. Pre-computes (slot_index, slot_meta)
│                               # before emitting per-abstract rows. The
│                               # poster_to_slot map is derived once from the
│                               # FINAL CSV (deterministic ordering: ISO start
│                               # time ascending), shared across all rows.
├── builder.py                  # MODIFIED. Wires the new standby-emission
│                               # path; passes the slot table to the parquet
│                               # emitter.

src/ohbm2026/fetch/
├── artifacts.py                # MODIFIED. Stage 1's emitted "state_key" field
│                               # in provenance JSON renamed to
│                               # "fetch_state_key" (FR-009). Old name still
│                               # accepted by readers via union-type loader.
├── stage.py                    # MODIFIED. Same rename applied throughout
│                               # checkpoint emission.

.github/workflows/
└── deploy-ui.yml               # MODIFIED. Adds explicit attempt-count
                                # telemetry inside the retry loop so the
                                # operator can verify it saved the deploy.

site/src/lib/
├── shards.ts                   # MODIFIED. AbstractRecord.poster_standby
│                               # field becomes
│                               # `{standbyFirstIndex: number|null,
│                               #   standbySecondIndex: number|null}` plus
│                               # a new shard `StandbySlot[]` type.
├── standby.ts                  # MODIFIED. Becomes a thin lookup-table
│                               # consumer. Map<index, SlotMeta>; the memo
│                               # caches added in PR #27 are removed.
└── data_package/loader.ts      # MODIFIED. Adds the `standby_slots` shard to
                                # the in-memory map.

tests/
├── test_book_cache.py          # NEW
├── test_book_assembly.py       # NEW
├── test_book_failure_isolation.py # NEW (introduces a deliberately-broken
│                                  # fixture abstract: contains a single
│                                  # `\bogus{}` LaTeX command that Tectonic
│                                  # can't resolve).
├── test_standby_schema.py      # NEW (round-trip test against fixtures)
├── test_docx_retirement.py     # NEW
├── test_state_key_rename.py    # NEW
└── fixtures/book/
    └── broken_abstract.json    # NEW. One-entry fixture appended to the
                                # synthetic book fixture for the failure-
                                # isolation test.
```

**Structure Decision**: stays within the existing Track-A layout. Each story touches a single sub-area (US1 → `book/`, US2 → `ui_data/` + `site/src/lib/`, US3 → `book/` removal, US4 → `fetch/` + `.github/workflows/`); no new top-level directories. The cache directory follows the existing `data/cache/<stage>/` convention.

## Phase 0 — research

See `research.md`. Six decisions:

- **R1**: cache-key derivation — `sha256(md_body || pandoc_version || engine_version || header_includes_hash || style)`. Discovered at runtime, no hardcoded version allow-list (CA-007).
- **R2**: parallelism via `joblib.Parallel(n_jobs=-1, backend="loky")` — process-based pool, matches Stage 4's existing pattern, avoids GIL contention on Pillow+pandoc subprocess management.
- **R3**: two-pass assembly mechanism — pass 1 concatenates chunks with `pikepdf.Pdf.new()` + running page counter; pass 2 emits an index appendix from a stub markdown. The `\setcounter{page}` markers in pass 2 are anchored to chunk-start offsets recorded during pass 1.
- **R4**: standby_slots table shape — `slot_index: INT8`, `start_utc: TIMESTAMP[ms, UTC]`, `end_utc: TIMESTAMP[ms, UTC]`, `display_label: VARCHAR`. 8 rows for OHBM 2026. Sort order = ISO start time ascending (so `slot_index` IS the chronological position).
- **R5**: standby schema migration — bump parquet manifest `schema_version` from `parquet-single.v1` → `parquet-single.v2`. The in-browser decoder branches on the version and accepts both shapes for one deploy cycle. After the next deploy clears, v1 acceptance can be deleted in a future cleanup.
- **R6**: state-key rename strategy — Stage 1 writes `fetch_state_key` in new provenance. Loaders accept both `state_key` and `fetch_state_key` for the lifetime of any on-disk artefact. Stage 6's `corpus_state_key` is unchanged.

## Phase 1 — design artefacts

- **data-model.md** — entity shapes for `AbstractPdfChunk`, `AssembledBook`, `StandbySlot`, `PerAbstractFailure`; cache-on-disk layout; parquet schema v2 deltas.
- **contracts/cli.md** — `ohbmcli book` updates: `--format` choices reduced to `{md, pdf, all}`; explicit DOCX-rejection contract; new `--workers N` flag default `-1` (all cores); the existing flags pass through.
- **contracts/standby.linkml.yaml** — LinkML addendum for the standby_slots table; integrates with the Stage-10 schema at `specs/010-export-redesign/contracts/shards.linkml.yaml`.
- **quickstart.md** — operator runbook: first build (~7 min), cache warm-up, single-abstract debug recipe, cache invalidation triggers, DOCX-retirement migration notes.

## Complexity Tracking

> No constitutional violations — table omitted.
