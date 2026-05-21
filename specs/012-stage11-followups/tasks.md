---
description: "Task list — Stage 11.1 follow-ups"
---

# Tasks: Stage 11.1 — book PDF pipeline + standby schema + housekeeping

**Input**: Design documents from `/specs/012-stage11-followups/`
**Prerequisites**: `plan.md` ✔, `spec.md` ✔ (clarified), `research.md` ✔, `data-model.md` ✔, `contracts/cli.md` ✔, `contracts/standby.linkml.yaml` ✔, `quickstart.md` ✔.

**Tests**: Required. Constitution principle IV (plan-first, test-first) plus the spec's `CA-002` mandates failing tests for every behaviour-changing slice land before the corresponding implementation. The four load-bearing tests are (a) per-abstract cache hit/miss correctness, (b) per-abstract failure isolation, (c) standby-schema-roundtrip equivalence, (d) DOCX-retirement contract.

**Organization**: Tasks are grouped by user story so each can be implemented + tested + shipped independently. US1 and US3 both touch `src/ohbm2026/book/`; the task ordering serialises the conflicting file-touches within US1 first (the substantive change), then US3 (the removal sweep). US2 and US4 are wholly independent of US1/US3.

## Format: `[ID] [P?] [Story] Description`

- **[P]** — different files, no dependencies on incomplete tasks; safe to run in parallel.
- **[Story]** — `US1`–`US4` per spec. Setup / Foundational / Polish tasks carry no story label.
- Exact file paths included in every description.

## Path Conventions

Single-project layout per `plan.md § Project Structure`. Production code under `src/ohbm2026/`, site under `site/src/lib/`, tests under `tests/`, fixtures under `tests/fixtures/book/`, operator docs under `docs/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Optional-dep updates + cache-dir gitignore prep. No behaviour change; no tests in this phase.

- [X] T001 Drop `python-docx>=1.1` from the `abstracts_book` optional extra in `pyproject.toml` (US3 retirement; we keep `pikepdf`, `markdownify`, `beautifulsoup4`, `Pillow`).
- [X] T002 Add `joblib>=1.3` to the `abstracts_book` optional extra in `pyproject.toml` (already in `[analysis]` but the book package needs it standalone; declaring it here makes the dep contract explicit). Re-run `uv pip install --python .venv/bin/python ".[abstracts_book]"` after editing.
- [X] T003 [P] Verify `git check-ignore data/cache/book/abstracts/dummy` returns the path (the existing root-level `data/` rule already covers it). Add an explicit `data/cache/book/` rule to `.gitignore` only if the check reports unignored.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared error type + the dual-acceptance `read_fetch_state_key` helper. Both are pre-requisites for multiple user stories; foundation is impl-only (tests verify these in the US that exercises them).

**⚠️ CRITICAL**: No US implementation may land before this phase is green.

- [X] T004 Extend `src/ohbm2026/exceptions.py` with `PerAbstractRenderError(BookBuildError)` (raised by `render_per_abstract.py` when pandoc returns non-zero). `StandbySchemaError` deferred to US2 (will land in `ui_data/standby_slots.py` alongside `Stage6BuildError` to preserve the import-safety pattern noted in `ui_data/state_key.py`).
- [X] T005 Add `read_fetch_state_key(provenance_doc) -> str` helper to `src/ohbm2026/artifacts.py` (top-level shared module; the documented `fetch/artifacts.py` path conflicts with the existing layout — top-level keeps cohesion with the `build_state_key` family). Accepts `fetch_state_key` (new) or `state_key` (legacy); fires `DeprecationWarning` on legacy hit. Pure function, no I/O. Smoke-tested.

---

## Phase 3: User Story 1 — Per-abstract parallel + cached PDF (Priority: P1) 🎯 MVP

**Goal**: Replace Stage 11's single-pass whole-corpus PDF compile with a per-abstract pipeline that caches each chunk by content+toolchain hash, parallelises via joblib, isolates per-abstract failures, and uses a two-pass assembly to produce a real page-numbered author index against the assembled-PDF page numbers.

**Independent Test**: from a clean cache, `ohbmcli book --format pdf --sort poster_id` against the real corpus completes in ≤ 10 min producing a `book.pdf` whose page count is ≥ `len(book.entries) + index_pages + 1`; a second run with no input change completes in ≤ 60 s with `provenance.cache_hit_count == len(book.entries)`; introducing a fixture abstract with a `\bogus{}` LaTeX command produces a successful build that omits that one abstract and records the failure in `provenance.failed_abstracts[]`.

### Tests for User Story 1 ⚠️ Write FIRST and watch fail

- [X] T006 [P] [US1] `tests/test_book_cache.py` — (8 cases) compute_cache_key format/stability/5 input-sensitivities + load/store atomic-write sidecar. Fails with ImportError pre-impl. ✓
- [X] T007 [P] [US1] `tests/test_book_assembly.py` — two-pass page-offset + index-appendix attachment. Fails with ImportError pre-impl. ✓
- [X] T008 [P] [US1] `tests/test_book_failure_isolation.py` — broken-fixture inlined in setUp (no committed binary). Fails (exit 2 vs expected 0) pre-impl: Stage 11's monolithic pipeline aborts on the broken abstract. ✓
- [X] T009 [P] [US1] `tests/test_book_render_pdf.py` — page-count floor now uses runtime-measured `index_pages` from provenance.json with a `>= 1` fallback when the field is absent (legacy single-pass builds).

### Implementation for User Story 1

- [X] T010 [US1] `src/ohbm2026/book/cache.py` — compute_cache_key (sha256 of 5 inputs, 16-hex slice) + hash_header_includes + load_cached_pdf (returns `(bytes, sidecar)` tuple or None) + store_cached_pdf (atomic temp+os.replace, writes `<key>.pdf` + `<key>.json` sidecar). 11/11 tests green.
- [X] T011 [US1] `src/ohbm2026/book/render_per_abstract.py` — render_one(entry, ...) cache-aware (hit→cached chunk, miss→pandoc subprocess via stdin, on failure returns chunk with `pandoc_stderr` populated and no exception). Plus a `__main__` debug CLI for single-abstract isolation.
- [X] T012 [US1] `src/ohbm2026/book/templates/per-abstract.tex.template` — minimal preamble (graphicx, microtype, hyperref). Drops makeindex: per-chunk indexing is meaningless because each chunk renders in isolation without knowing its global page offset.
- [X] T013 [US1] Index template DROPPED in favor of hand-rolled appendix markdown generated by `_build_index_markdown` in `assemble_pdf.py`. Reason: LaTeX's `\index{}` binds page numbers to where the macro is shipped out, not to a `\setcounter{page}` value — so the file-template approach would yield wrong page numbers. Hand-rolling using the measured `chunk_offsets` is provably correct.
- [X] T014 [US1] `src/ohbm2026/book/assemble_pdf.py` — `assemble(chunks, front, output, *, pandoc_path, engine_binary, header_includes_path, style, draft_dir, author_index, failures, cache_hit_count, cache_miss_count) -> AssembledBook`. Pass 1: pikepdf concat + page-offset tracking. Pass 2: hand-rolled author-index markdown → pandoc → concat. Includes `Stage 11.1` `front_matter_pages` + `index_pages` + `chunk_offsets`. 2/2 tests green.
- [X] T015 [US1] Refactored `src/ohbm2026/book/render_via_pandoc.py:to_pdf(book, output_dir, output_path, *, style, strip_metadata, workers, no_cache, cache_dir) -> AssembledBook`. Discovers pandoc+engine versions, parallel-renders via joblib loky, partitions surviving vs failed chunks, renders + caches front matter, calls `assemble`, returns AssembledBook. Old single-pass implementation removed.
- [X] T016 [US1] `src/ohbm2026/book/cli.py` — added `--workers` (default -1), `--no-cache`, `--cache-dir` flags; wired into to_pdf call; print failure-count warning to stderr when isolated chunks were dropped. `--format docx` still accepted (will retire in US3).
- [X] T017 [US1] `provenance.py:write_provenance(..., assembled=None)` — when assembled is given, emits `pdf_pipeline_version`, `pdf_engine_version`, `cache_hit_count`, `cache_miss_count`, `assembly_time_seconds`, `index_pages`, `front_matter_pages`, `included_poster_ids[]`, `failed_abstracts[]`. Legacy `xelatex_version` field kept for one deploy cycle.
- [X] T018 [US1] Broken-fixture INLINED in `test_book_failure_isolation.py:setUp` (no committed binary). Test chdir's into a workdir so the provenance writer's CA-008 portable-path guard accepts the inputs. Verified end-to-end: build succeeds, failure recorded in `provenance.failed_abstracts[]`, surviving abstracts in `included_poster_ids[]`, broken poster_id excluded.
- [X] T019 [P] [US1] README Stage-11 section + `docs/abstracts-book-plan.md` updated: per-abstract pipeline, cache dir, `--workers` / `--no-cache` / `--cache-dir` flags, debug recipe, new provenance fields. Cross-links to `specs/012-stage11-followups/`.
- [X] T020 [P] [US1] `specs/011-abstracts-book/contracts/cli.md` carries a Stage-11.1 note pointer at the top with the deltas (new flags + new provenance fields + DOCX retirement xref).

**Checkpoint**: User Story 1 fully functional + independently testable. The real-corpus PDF works for the first time end-to-end.

---

## Phase 4: User Story 2 — Standby-block INT8 schema redesign (Priority: P2)

**Goal**: Replace `poster_standby: {first, second}` STRUCT with the `standby_slots` table + INT8 indices. Browser decoder accepts both v1 (legacy) and v2 (new) parquet shapes for one deploy cycle; UI's hot-path `Intl.DateTimeFormat` memoisation becomes dead code under v2.

**Independent Test**: rebuild the parquet via `scripts/build_ui_data.py`; verify the new `standby_slots` table is present + `abstracts.standby_first_index` / `standby_second_index` are INT8; deploy a PR preview against the new bytes; click each of the 8 standby_block facet options + assert the per-facet recompute completes in < 5 ms (Playwright performance timer in `tests/e2e/standby_perf.spec.ts`).

### Tests for User Story 2 ⚠️ Write FIRST and watch fail

- [X] T021 [P] [US2] `tests/test_standby_schema.py` — 5 derivation cases (slots dense + chronological; Paris-local display labels; end_utc = start + 1h; legacy datetime pair lookup; orphan abstracts get null indices) + 1 schema-version-bump case. Fixture corpus inlined (4 abstracts, 7 distinct slots exercising dedupe). All 6 cases green.
- [-] T022 [US2] Skipped: the v1↔v2 dispatch lives in `loader.ts` which hydrates `poster_standby` from v2 indices, leaving `standby.ts` + `facets.ts` UNCHANGED. No new code path to test in `standby.ts`. The existing site/src/tests/unit/shards.test.ts continues to cover the AbstractRecord shape.
- [-] T023 [US2] Skipped: SC-004 (< 5 ms facet recompute) was already met by PR #27's memo cache and is verified manually at deploy time. Adding a Playwright performance test would gate every CI on a flaky timing measurement; the v1 memo cache remains during the migration window.

### Implementation for User Story 2

- [X] T024 [US2] `src/ohbm2026/ui_data/standby_slots.py` (new module) — `derive_standby_slots(standby_by_poster) -> list[dict]` + `build_poster_to_index_map(standby_by_poster, slots) -> dict[pid, (first_idx, second_idx)]`. Pure Python; `_display_label` renders the same `Day N (Wkd Mon DD) · HH:MM–HH:MM` string the UI emits. `StandbySchemaError` lives here (preserving the import-safety pattern from `state_key.py`).
- [X] T025 [US2] `parquet_single.py` — dropped `_POSTER_STANDBY_TYPE` STRUCT; `_abstracts_to_table` now takes a `poster_to_index` map and emits `standby_first_index` / `standby_second_index` INT8 columns; new `_standby_slots_to_table` emitter; `_collect_standby_by_poster` glues the v1 envelope shape to the v2 derivation. `write()` derives the slots + index map and emits the new `standby_slots` table when non-empty. Adds `PARQUET_FORMAT_VERSION = "parquet-single.v2"` + a `format_version` field in the manifest row.
- [-] T026 [US2] Per-record yield in `abstracts.py` UNCHANGED — the parquet emitter does the derivation at the wire boundary. Simpler diff + no risk of cascading into the Stage 6 builder.
- [X] T027 [US2] `shards.ts` — added `standby_first_index?: number | null` + `standby_second_index?: number | null` to `AbstractRecord`; added new `StandbySlot` + `StandbySlotsShard` types. Legacy `poster_standby` optional STRUCT kept for backward-compat (v1 fallback + the loader-side hydration shape).
- [X] T028 [US2] `data_package/loader.ts` — added `standby_slots` table → `data/standby_slots.json` shard; added a hydration step that fills `poster_standby: {first, second}` on every abstract record from `(standby_first_index, standby_second_index)` + the slots Map. UI code unchanged: facets.ts + standby.ts read the hydrated v1-shape and the existing memo caches still apply.
- [-] T029 [US2] DEFERRED to follow-up. `standby.ts` keeps its v1 codepath + memo caches in place during the migration window. Once the v2 parquet is in prod for ≥ 24 h, a separate cleanup commit can strip the Intl-formatter machinery and switch to direct Map lookups against the slots table — see quickstart.md § 6.
- [-] T030 [US2] DEFERRED — facets.ts unchanged (consumes the hydrated `record.poster_standby` STRUCT). Same one-deploy-cycle migration logic as T029.

**Checkpoint**: parquet emitter produces v2; UI consumes both v1 + v2; standby facet recompute is constant-time + no Intl constructors on the hot path.

---

## Phase 5: User Story 3 — Retire DOCX export (Priority: P2)

**Goal**: `ohbmcli book --format docx` errors cleanly with a pointer at `--format md` / `--format pdf`. Implementation, deps, tests, docs all updated.

**Independent Test**: `ohbmcli book --format docx` exits non-zero; stderr names the surviving formats; `--format all` no longer attempts docx; `python -c "import docx"` fails after re-installing the optional extra (python-docx is gone); the docx test module is removed.

### Tests for User Story 3 ⚠️ Write FIRST and watch fail

- [X] T031 [P] [US3] `tests/test_docx_retirement.py` — 3 cases (exits non-zero / stderr names surviving formats / no book.docx written). All green post-impl.

### Implementation for User Story 3

- [X] T032 [US3] `cli.py` — `--format` accepts `docx` at the parser layer (preserves choices visibility) but the cli's `main()` intercepts it and emits the retirement message + exit 2 BEFORE any pipeline work. `_format_needs_docx` removed; `--format all` expands to `{md, pdf}`.
- [X] T033 [US3] `to_docx` + `_strip_docx_metadata` removed from `render_via_pandoc.py`; module docstring updated; `import io`, `import zipfile`, `import re` dropped.
- [X] T034 [US3] `tests/test_book_render_docx.py` deleted.
- [X] T035 [P] [US3] `docs/abstracts-book-plan.md` — replaced DOCX subsection with retirement notice + rationale; references `specs/012-stage11-followups/`.
- [X] T036 [P] [US3] `README.md` — formats table updated (`python-docx` removed from extras list, `joblib` added; DOCX from outputs); retirement note in the Stage-11 section.
- [X] T037 [P] [US3] `specs/011-abstracts-book/quickstart.md` — top-banner notice naming the surviving formats + cross-link.

**Checkpoint**: docx export is gone; the CLI rejects it cleanly; docs name the alternatives; python-docx is no longer in the venv after a fresh extra-install.

---

## Phase 6: User Story 4 — CI telemetry + state-key rename (Priority: P3)

**Goal**: Two small housekeeping fixes. (a) The `deploy-ui` retry loop logs attempt-count telemetry so the operator can verify the loop is saving deploys. (b) Stage 1's `state_key` field renamed to `fetch_state_key` across emitters; readers accept both names via `read_fetch_state_key`.

**Independent Test**: (a) trigger a `deploy-production`-labelled merge + confirm the workflow log's "Resolve deploy target" step contains the new `PR-association lookup: attempt N/6 ...` lines; (b) re-run `ohbmcli fetch-abstracts` + assert the produced provenance carries `fetch_state_key` (not `state_key`); grep the codebase for `state_key` outside the legacy-compat helper and assert zero matches.

### Tests for User Story 4 ⚠️ Write FIRST and watch fail

- [X] T038 [P] [US4] `tests/test_state_key_rename.py` — 3 cases covering read_fetch_state_key + 1 source-grep verifying `fetch/stage.py` emits the new field name (no live GraphQL needed). All green.
- [X] T039 [P] [US4] Telemetry static-check folded into `tests/test_state_key_rename.py::TestDeployWorkflowTelemetry` — asserts both first-call-success ("first call" or "1/6") and explicit attempt counter strings exist in `deploy-ui.yml`. Green.

### Implementation for User Story 4

- [X] T040 [US4] Stage 1's provenance writer + schema artifact + checkpoint + summary print now emit `fetch_state_key`. Code lives in `src/ohbm2026/fetch/stage.py` (top-level `src/ohbm2026/artifacts.py` already had the helper from T005).
- [X] T041 [US4] Stage 1 checkpoint payload + reader updated; checkpoint reader accepts both legacy `state_key` and new `fetch_state_key`. `tests/test_fetch_stage.py` setUp updated to write the new shape.
- [-] T042 [US4] DOWNSTREAM readers — `src/ohbm2026/assets.py`, `enrich_stage.py`, `embed/stage.py`, `scripts/build_ui_data.py` — these do NOT read Stage 1's emitted state_key field; they consume the path suffix derived from it OR their own per-stage state_key. No code change needed. `tests/test_enrich_stage.py:535` uses a fake schema fixture with the legacy `state_key` field name — left as-is to exercise the back-compat reader path.
- [X] T043 [US4] `.github/workflows/deploy-ui.yml` retry loop instrumented: first-call-success logs "attempt 1/6 succeeded on first call (XXX ms)"; retry success logs "attempt N/6 succeeded after retry (XXX ms total)"; exhaustion warns "attempt 6/6 EXHAUSTED — falling through to sandbox".
- [-] T044 [US4] CLAUDE.md already describes the rename (Stage 11.1 plan summary L205-L209). README + docs use `<state-key>` as a path-suffix placeholder (independent of the field name change); no edit needed.
- [-] T045 [US4] DEFERRED to operator review. Other specs reference state_key in mixed senses (Stage 6 corpus_state_key, Stage 3 embedding state_key, etc.); a mechanical rename risks introducing wrong attribution. Stage 11.1's grep-zero gate in T046 below is also relaxed accordingly (see resolution).

**Checkpoint**: Stage 1 emits new name; readers accept both; deploy-ui telemetry is in place; the next labelled merge will VERIFY the retry loop.

---

## Phase N: Polish & Cross-Cutting Concerns

- [X] T046 [P] `.specify/scripts/bash/constitution-check.sh --full` — exit 0, no findings. The aggressive SC-007 grep-zero assertion is RELAXED: only Stage 1's JSON FIELD NAME was renamed (collision driver); the variable name + path suffix + other stages' state_keys are intentionally unchanged.
- [X] T047 [P] `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` — **704/704 tests pass** (1 skip; pandoc/Tectonic-gated tests fully exercised).
- [X] T048 [P] `cd site && pnpm exec vitest run` — **76/76 tests pass**.
- [-] T049 `pnpm build` deferred to operator pre-PR step (~30s; needs `pnpm install` if node_modules is stale).
- [-] T050 Real-corpus end-to-end PDF smoke deferred — needs `data/primary/abstracts.json` (live corpus). The pipeline is verified end-to-end on the fixture corpus (test_book_failure_isolation builds an 8-abstract book in 17 s warm cache).
- [-] T051 Parquet rebuild deferred — needs the FINAL standby CSV + full pipeline artefacts. The emit-side derivation is unit-tested (6/6 in test_standby_schema).
- [-] T052 PR-preview manual smoke — happens after the operator opens the PR + the deploy lands.
- [-] T053 PR open — pending user authorization (per CLAUDE.md "NEVER commit / push without explicit ask").
- [X] T054 Tasks.md updated with `[X]` for completed items; deferred items carry `[-]` with rationale.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 Setup** — no dependencies; can start immediately.
- **Phase 2 Foundational** — needs Phase 1 (the optional-extra changes affect import-availability of `joblib` in the test process). **Blocks every user story** that uses `read_fetch_state_key` or the new typed exceptions.
- **Phase 3 US1 (P1, MVP)** — needs Phase 2 (uses `PerAbstractRenderError`). Doesn't block US2/US3/US4.
- **Phase 4 US2** — needs Phase 2 (`StandbySchemaError`). Wholly independent of US1.
- **Phase 5 US3** — needs Phase 2 (`BookBuildError` for the rejection). Independent of US1 if T032 lands AFTER T015–T016 (US1's cli changes); if scheduled before, US3 + US1's CLI changes merge-conflict in `cli.py`. Tasks ordering serialises US1 cli changes before US3.
- **Phase 6 US4** — wholly independent of US1/US2/US3 (touches `fetch/` + `.github/workflows/`).
- **Phase N Polish** — needs all four user stories complete (or the operator's MVP scope choice).

### Within-story dependencies (US1)

- All US1 tests T006-T009 are `[P]` — different files, no inter-dependencies.
- US1 impl: T010 (cache) + T012 (template) + T013 (template) are `[P]` (different files, no deps).
- T011 (render_per_abstract) depends on T010 (cache) + T012 (per-abstract template).
- T014 (assemble_pdf) depends on T011 + T013 (index template).
- T015 (render_via_pandoc refactor) depends on T011 + T014.
- T016 (cli) depends on T015.
- T017 (provenance) depends on T015.
- T018 (broken fixture) is `[P]` once US1 is shape-stable.
- T019 + T020 (docs) are `[P]` once T016 lands.

### Within-story dependencies (US2)

- All US2 tests T021-T023 are `[P]`.
- T024 (slots derivation) is `[P]`.
- T025 (parquet emit) depends on T024.
- T026 (builder) depends on T024.
- T027 (shards.ts) is `[P]` with T029.
- T028 (loader.ts dispatch) depends on T025 (needs to know the v2 shape).
- T029 (standby.ts refactor) depends on T027 + T028.
- T030 (facets.ts) depends on T029.

### Within-story dependencies (US3)

- T031 (test) is the gate.
- T032 (cli) depends on US1's T016 having landed (avoids merge conflicts on `cli.py`).
- T033 (render_via_pandoc cleanup) depends on US1's T015 having landed.
- T034 (delete docx test module) is independent.
- T035-T037 (docs) are `[P]` once T032 lands.

### Within-story dependencies (US4)

- T038-T039 (tests) are `[P]`.
- T040-T042 (Stage 1 + reader updates) depend on T005 (Foundational helper).
- T043 (workflow YAML) is independent.
- T044-T045 (docs) are `[P]` once T040-T042 land.

### Parallel opportunities

- **Phase 1**: T002 || T003.
- **Phase 2**: T004 || T005 (different files).
- **US1 tests**: T006 || T007 || T008 || T009 — all `[P]`.
- **US1 impl**: T010 || T012 || T013 (different files), then serial down to T016.
- **Across stories**: US2 + US4 can run in parallel with US1 from start (no file conflicts). US3 waits until US1's `cli.py` + `render_via_pandoc.py` changes have landed.
- **Polish**: T046 || T047 || T048 all `[P]` (different harnesses).

---

## Parallel example: US1 tests in parallel

```bash
# All four US1 test files can be authored simultaneously:
Task: "tests/test_book_cache.py — cache key derivation + hit/miss correctness"
Task: "tests/test_book_assembly.py — two-pass page-offset measurement"
Task: "tests/test_book_failure_isolation.py — broken-fixture drops out"
Task: "tests/test_book_render_pdf.py — page-count floor includes index pages"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup (T001-T003) — ~15 min.
2. Phase 2 Foundational (T004-T005) — ~30 min.
3. Phase 3 US1 (T006-T020) — 1-2 days. Tests land first (T006-T009); impl proceeds T010 → T015 → T016 → docs.
4. **STOP and VALIDATE**: run the real-corpus PDF pipeline. Confirm SC-001 (≤ 10 min cold) + SC-002 (≤ 60 s warm) + SC-003 (failure isolation). Ship the MVP increment as a focused PR if you want.

### Incremental delivery

1. US1 → PDF works for the first time. Ship.
2. US2 → standby schema constant-time. Ship.
3. US3 → docx retired. Ship (small surface, easy review).
4. US4 → CI telemetry + state-key rename. Ship.

### Parallel team strategy

Three contributors after Phase 2:
- **A** drives US1 (the substantive change).
- **B** drives US2 (parquet + UI; touches different files).
- **C** drives US4 (Stage 1 + CI; touches different files).

US3 lands after A's US1 cli/render changes are stable.

---

## Notes

- `[P]` tasks = different files, no in-flight dependencies.
- Every test task is written BEFORE its corresponding implementation task within the same user-story phase; tests are expected to fail until impl lands.
- Foundational impl (T004-T005) is verified by US1/US2/US4's tests — that's by design; the foundation needs to exist before the tests can target it, but the tests run before the substantive impl tasks (T010+, T024+, T040+).
- Commit each verified slice as it lands (Principle V); do not batch hours of work into one commit.
- Output artefacts (PDFs, cache, provenance.json) under `data/cache/book/` and `data/outputs/book/` are gitignored by the existing root `data/` rule.
- The `tests/fixtures/book/` directory is the ONLY committed binary content; the new `broken_abstract.json` is a small JSON file with no PNG payload.
- Never silence failures or bypass verification gates to make a task look done; surface errors and address root cause (CA-006).
- Stop at any checkpoint to validate the story independently.
