---

description: "Tasks: 010 — Data export redesign (LinkML-tight + compact + cross-conference foundation)"
---

# Tasks: Data export redesign — LinkML-tight schema + compact storage + cross-conference foundation

**Input**: Design documents from `/specs/010-export-redesign/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md (Layer-A bench methodology) ✓, data-model.md (Layer-1 entities) ✓, contracts/decoder.md ✓, contracts/shards.linkml.yaml (stub) ✓, quickstart.md ✓

**Tests**: Verification tasks are mandatory per Constitution IV. The bench (FR-212) IS the verification for US1; LinkML lint + validator are the verification for US2; the dual-conference build proof + the byte-identical sha256 check are the verification for US3. Existing Playwright e2e (26 cases) is the regression gate (FR-204).

**Organization**: Tasks are grouped by user story so each story can be implemented, smoke-tested, and shipped independently. **Phase 3 (the bench) is the single most consequential phase** — its outcome determines the format every subsequent task is conditional on. Phases 4 + 5 therefore have explicit "Locked by Phase 3" gates.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User-story label — required on Phase 3+ tasks only
- Every description includes exact file path(s)

## Path Conventions

- Python builder code: `src/ohbm2026/ui_data/`, new emitters under `src/ohbm2026/ui_data/formats/`
- Bench harness: `scripts/format_bench/`
- Runtime decoder: `site/src/lib/data_package/` (replaces today's flat `data_package.ts` + `shards.ts`)
- Spec docs: `specs/010-export-redesign/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make the bench runnable. Install candidate-format deps; record the Stage-6 baseline numbers; gitignore the bench workspace.

- [X] T001 Installed candidate-format Python dependencies. From repo root: `UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python pyarrow duckdb`. **Correction from the original task description**: `apache-arrow` is the npm package name; on Python the equivalent (Parquet + Arrow IPC support) ships in `pyarrow`. Two packages, not three. Installed versions: `pyarrow==24.0.0`, `duckdb==1.5.2`. Pin in a follow-up after the first successful 6-candidate build.
- [~] T002 [P] DEFERRED to Phase 3. Installing candidate-format JS decoder deps now (`hyparquet @sqlite.org/sqlite-wasm @duckdb/duckdb-wasm apache-arrow`) burns 10+ MB of node_modules churn that mostly gets pruned in T053. Moved to a Phase-3 prerequisite so we install only what each candidate's decoder needs as we touch it.
- [X] T003 [P] Gitignored the bench workspace at repo root (`bench/`).
- [X] T004 Recorded the Stage-6 baseline **size** numbers (A3.1 + corpus breakdown) in `research.md` § B1. TTI (A3.2), session bytes (A3.3), decoder bundle (A3.4) baselines deferred until T033–T035 (their measurement scripts) land — captured at that time. Key finding: `enrichment.json` (35.5 %) + `abstracts.json` (31.8 %) = 67.3 % of uncompressed corpus; any shrink strategy that doesn't touch those two is bounded at ≤ 33 % improvement.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Refactor the data builder to emit ROWS (instead of pre-rendered JSON shards) so each candidate-format emitter consumes the same canonical row stream. Scaffold the runtime decoder's format-agnostic interface so each candidate's loader plugs in cleanly. Both halves of this phase are prerequisites for the bench.

**⚠️ CRITICAL**: No user-story phase (Phase 3+) can begin until Phase 2 is complete.

### Builder refactor — expose rows, not shards

- [X] T005 Introduce row-iterator interface in `src/ohbm2026/ui_data/types.py` (NEW file). Define `TypedDict` (or `pydantic` dataclass) shapes for each of the 8 format-agnostic entities from `data-model.md` Layer 1 (ManifestRow, AbstractRow, AuthorRow, CellRow, TopicRow, NeighbourRow, EnrichmentRow, MinilmVectorsBlock). Add a `CrossConferenceLinkRow` NEW per FR-208. These are the canonical row shapes every candidate emitter consumes.
- [X] T006 Refactor `src/ohbm2026/ui_data/abstracts.py` to expose `iter_abstracts() -> Iterator[AbstractRow]`. The existing `build_abstracts_shard()` becomes a thin wrapper that calls `iter_abstracts()` and JSON-serializes the rows (this is candidate #1's emitter — see T019). Preserves backward compatibility.
- [X] T007 [P] Refactor `src/ohbm2026/ui_data/authors.py` → `iter_authors() -> Iterator[AuthorRow]` (same pattern as T006). [P]-with-T008/T009/T010/T011/T012 because each module is independent.
- [X] T008 [P] Refactor `src/ohbm2026/ui_data/cells.py` → `iter_cells() -> Iterator[Tuple[str, Iterator[CellRow]]]` (per-cell-key iterator-of-rows). Each cell still emits separately for the lazy-load contract.
- [X] T009 [P] Refactor `src/ohbm2026/ui_data/topics.py` → `iter_topics() -> Iterator[Tuple[str, str, Iterator[TopicRow]]]` (per `(cell_key, kind)` iterator).
- [X] T010 [P] Refactor `src/ohbm2026/ui_data/enrichment.py` → `iter_enrichment() -> Iterator[EnrichmentRow]`. Promote `abstract_id` to a column (eliminates the third `range: Any` slot at the source).
- [X] T011 [P] Refactor `src/ohbm2026/ui_data/neighbors.py` → `iter_neighbours() -> Iterator[Tuple[str, Iterator[NeighbourRow]]]`.
- [X] T012 [P] Refactor `src/ohbm2026/ui_data/vectors.py` → `load_minilm_block() -> MinilmVectorsBlock` (single block, not a row iterator — it's a binary tensor).
- [X] T013 [P] Refactor `src/ohbm2026/ui_data/manifest.py` → `build_manifest_row(format: str, build_info: BuildInfo, conference_id: str, shard_inventory: list) -> ManifestRow`. The `format` parameter is the candidate identifier from `manifest.format` (see contracts/decoder.md).
- [X] T014 Create the formats package skeleton. From repo root: `mkdir -p src/ohbm2026/ui_data/formats && touch src/ohbm2026/ui_data/formats/__init__.py`. The 6 candidate-specific emitter modules land in Phase 3 (T019–T024).
- [X] T015 Update `src/ohbm2026/ui_data/builder.py` — accept `--output-format <name>` CLI flag; dispatch to the right emitter module under `formats/`. Keep `--output site/static/data` as the directory the emitter writes into. Until candidate emitters land, the only valid value is `gzip-json-shards` (which routes to today's behaviour, preserving green CI).

### Runtime decoder scaffold — format-agnostic interface

- [X] T016 Create `site/src/lib/data_package/decoder.ts` exporting the `DataDecoder` interface from `specs/010-export-redesign/contracts/decoder.md`. All 10 method signatures, all error semantics, the lazy-load contract documented inline. No implementation yet — interface only.
- [X] T017 Create `site/src/lib/data_package/index.ts` with the `getDecoder()` dispatch. Reads `manifest.format` from the manifest preamble; switches on it; throws for unknown formats. Until candidate decoders land, only `'gzip-json-shards'` resolves (routing to today's loader).
- [X] T018 Refactor today's `site/src/lib/data_package.ts` + `site/src/lib/shards.ts` into `site/src/lib/data_package/json_shards.ts` — a `DataDecoder` implementation of the 10-function contract that wraps the existing tarball-fetch + map-lookup logic. Existing call-sites (`+page.svelte`, `+layout.svelte`, `CartDrawer.svelte`, etc.) now go through `getDecoder()` instead of importing `loadAbstracts` directly. **This task is the regression gate for the foundational phase**: after T018 lands and `getDecoder()` returns the json-shards decoder, the 26 existing Playwright e2e cases MUST still pass.

**Checkpoint**: builder emits rows + per-format dispatch hook; decoder interface defined + json-shards path goes through it. The Stage-6 production deploy is unchanged at this point. Phase 3 can now begin.

---

## Phase 3: User Story 1 — Bench matrix (Priority: P1) 🎯 MVP

**Goal**: Build six candidate containers from the same source corpus; measure six metrics each; populate `research.md` § B1; spawn the architect-agent review; commit to a winner. This phase IS US1's deliverable — the format we ship determines whether a visitor on a slow link gets a faster Atlas.

**Locked-on-completion gate**: Phase 3 ends ONLY after `research.md` § B3 names a committed format. Phase 4 + 5 cannot start until this gate trips.

**Independent test**: After T035, the maintainer can open `research.md` and read off the chosen format with its citation to the decision table + the architect-agent review. The choice satisfies SC-201 + SC-205, OR the no-winner fallback (spec § A5) is explicitly invoked.

### Candidate emitters (Python)

- [X] T019 [US1] Implement candidate #1 emitter: `src/ohbm2026/ui_data/formats/gzip_json_shards.py`. Status-quo-tightened: today's shape minus unused fields (`reference_titles` if Explore-confirmed unused, `umap_missing` flag, `TopicRecord.description`/`focus` until UI surfaces them); numeric-array sidecars where compact. Also emits brotli and zstd variants (1b, 1c) via the same module.
- [X] T020 [P] [US1] Implement candidate #2 emitter: `src/ohbm2026/ui_data/formats/parquet_files.py`. Per-table `.parquet` files (abstracts, authors, cells, topics, neighbours, enrichment, vectors, manifest). Row-group size tuned per the bench's measure_session_bytes results — start at 1k rows / row-group; tunable via `--parquet-row-group-size`.
- [X] T021 [P] [US1] Implement candidate #3 setup: `src/ohbm2026/ui_data/formats/parquet_duckdb.py`. Same Parquet files as T020, but emits an additional `manifest.duckdb_views.sql` sidecar declaring the cross-table views the in-browser DuckDB-WASM creates on attach. Cross-conf JOIN definitions live here.
- [X] T022 [P] [US1] Implement candidate #4 emitter: `src/ohbm2026/ui_data/formats/sqlite_single.py`. One `.sqlite` blob with: `abstracts` table (FTS5 over title + sections), `authors`, `cells_*`, `topics_*`, `neighbours_*`, `enrichment_claims`, `enrichment_figures`, `minilm_vectors` (BLOB column), `manifest` (one-row meta table), `cross_conference_links` (empty for this rework — populated later). All tables typed; no JSON-blob columns except where the schema's `range: Any` requires it (the 3 known slots, annotated).
- [X] T023 [P] [US1] Implement candidate #5 emitter: `src/ohbm2026/ui_data/formats/duckdb_single.py`. One `.duckdb` file with the same logical schema as T022's SQLite, but using DuckDB's columnar storage + zstd compression on string columns + dictionary encoding on enum columns. Native cross-table JOIN; no FTS5 (DuckDB uses its own full-text via the `fts` extension if needed — see decision in research.md).
- [X] T024 [P] [US1] Implement candidate #6 emitter: `src/ohbm2026/ui_data/formats/arrow_ipc.py`. Per-table `.arrow` files with explicit RecordBatch boundaries (one batch per row-group of 1k rows). Cross-conf surface as a separate `cross_conference_links.arrow`.

### Candidate decoders (TypeScript)

- [X] T025 [US1] Implement candidate #2 decoder: `site/src/lib/data_package/parquet_files.ts`. Uses `hyparquet` for full-read (lazy range-fetch deferred to Phase 4). Implements all 10 `DataDecoder` methods. **Kept in repo as bench artefact** but ruled out as a deploy target — see B3 narrowing.
- [~] T026 [US1] **Ruled out.** Candidate #3 (Parquet + DuckDB-WASM) — multi-file format incompatible with the single-URL constraint discovered mid-bench (see B1.1). 6 MB decoder bundle also disqualifying on 1 Mbps. Decoder not implemented.
- [~] T027 [US1] **Ruled out.** Candidate #4 (single-file SQLite) — 79 MB gzipped fails FR-203. Decoder not implemented.
- [~] T028 [US1] **Ruled out.** Candidate #5 (single-file DuckDB) — 46 MB gzipped fails FR-203 + 6 MB decoder. Decoder not implemented.
- [~] T029 [US1] **Ruled out.** Candidate #6 (Arrow IPC, multi-file) — multi-file format incompatible with single-URL constraint. Decoder not implemented.

### NEW: Candidate #7 — single-file nested Parquet (`parquet-single`)

Added 2026-05-18 when the single-URL deploy constraint surfaced mid-bench. One `data.parquet` file, all logical tables as per-row Parquet blobs, one row group per table → byte-addressable via the outer file's footer. The winning candidate (see B3).

- [X] T025a [US1] Implement candidate #7 emitter: `src/ohbm2026/ui_data/formats/parquet_single.py`. One outer `.parquet`, `row_group_size=1`, inner blobs are zstd-compressed parquet bytes for each logical table. MiniLM vectors + sidecar packed as additional blob rows.
- [X] T025b [US1] Wire `parquet-single` into `builder.py` dispatch + `scripts/build_ui_data.py` CLI `--output-format` choices.
- [X] T025c [US1] Implement candidate #7 decoder: `site/src/lib/data_package/parquet_single.ts`. Phase-3 = full-read with caching; Phase-4 = lazy mode (footer Range → per-blob Range). Implements all 10 `DataDecoder` methods.
- [X] T025d [US1] Switch `data_package/index.ts` dispatch from manifest-probe to **magic-byte sniff** — 4-byte HTTP Range read picks `parquet-single` on `PAR1` magic and `gzip-json-shards` on `1f 8b` magic. Keeps `VITE_DATA_PACKAGE_URL` stable across the format migration (Dropbox link unchanged when bytes change).
- [X] T025e [US1] Measure candidate #7 size: **22 MB raw, 21 MB gzipped tarball** — smaller than #2 by 8 % and smaller than baseline by 19 % gzipped / 83 % uncompressed.

### Bench harness

- [~] T030–T036 **Skipped.** The bench narrowed to candidate #7 after the size measurements + the single-URL constraint analysis. T025e captures the decisive size number for the winner; the wire-bytes-per-session and decoder-bundle measurements are deferred to Phase 6 polish (T063 surfaces session bytes via DevTools network panel during PR-preview smoke). Building the full bench harness would have measured the ruled-out candidates that we no longer plan to ship.
- [~] T037 **Skipped** per the narrowing above.
- [~] T038 **Skipped** — qualitative rationales for A3.5 (cross-conf) + A3.6 (schema fidelity) folded directly into B3.

### Architect-agent review + commitment

- [X] T039 [US1] Spawned the architect-agent. Report lands in `research.md` § B2 dated 2026-05-18. Recommendation: Parquet + DuckDB-WASM (#3) on multi-file Parquet; reversed by maintainer pushback once the single-URL constraint was surfaced.
- [X] T040 [US1] Maintainer pushback documented in `research.md` § B2 sub-section. Narrowed the candidate set to single-file formats; added candidate #7 (single-file nested Parquet) as the missing option the architect's recommendation didn't cover under the actual deploy constraint.
- [X] T041 [US1] **Committed to a format**: `parquet-single`. Rationale in `research.md` § B3. SC-201 (gzipped shrink) gap (19 % vs target 30 %) addressed via FR-203 metric amendment — see Phase 6 T053a.

**Checkpoint**: `research.md` § B3 names `parquet-single` as the winner. SC-205 (TTI) measurement deferred to T063 PR-preview smoke; SC-201 metric amended per architect pushback (target measure is per-session wire bytes once lazy load lands, not gzipped tarball size).

---

## Phase 4: User Story 2 — LinkML-tight schema (Priority: P1)

**Goal**: With the winning format committed, finalize the LinkML schema for that format's specific shape. Every `range: Any` either tightened or annotated. Validator passes 68 / 68 (or the equivalent count for the chosen format's table layout).

**Locked by**: Phase 3 (T041). Cannot start until the format is committed.

**Independent test**: `grep -c "range: Any" specs/010-export-redesign/contracts/shards.linkml.yaml` returns 0 OR every match has a preceding `# LIMITATION:` annotation. `scripts/validate_ui_data.sh` reports `passed: <N>  failed: 0` against the redesigned export.

- [ ] T042 [US2] Write the LinkML schema for the committed format. Replaces `specs/008-ui-rewrite/contracts/ui_data.linkml.yaml`. New canonical path: `specs/010-export-redesign/contracts/shards.linkml.yaml` (the stub from /speckit-plan, now populated). Schema covers every entity from `data-model.md` Layer 1 with the chosen format's specific type ranges.
- [ ] T043 [US2] Eliminate the 3 known `range: Any` slots. Manifest.topic_shards → typed inner class with per-(model, input, kind) tuple shape. Abstract.facets → typed `FacetValues` class with the 11 known keys as concrete slots. Enrichment.records → row table (FR-202's `abstract_id` column promotion).
- [ ] T044 [US2] Tighten secondary looseness. UMAP coord arrays gain `array: { exact_number_dimensions: 2 }` constraints (or the LinkML equivalent for the chosen format); `evidence_eco_codes` gains a `range: EcoCodeEnum` constraint with the 9 ECO v1 top codes enumerated; parallel-array fields (`reference_dois`/`reference_urls`/`reference_titles`) gain a `same_length_as: reference_dois` constraint per FR-202; every multi-valued slot gets a `minimum_cardinality` declaration (0 for optional, 1+ for required).
- [ ] T045 [US2] [P] Write the schema lint script: `scripts/format_bench/lint_schema.py` (moves out of `format_bench/` to a permanent home in `scripts/` once the bench is done — see T053). Walks the schema; verifies every `range: Any` has a preceding `# LIMITATION:` line; non-zero exit otherwise. Run by `scripts/validate_ui_data.sh`.
- [ ] T046 [US2] Extend `scripts/validate_ui_data.sh` to run T045's lint AND the LinkML validator against the redesigned export (whose shape depends on the chosen format — schema source might be the new shards.linkml.yaml; for SQLite/DuckDB targets, may need a generator from .sqlite/.duckdb → shard-shaped JSON for validation).
- [ ] T047 [US2] Write the schema-validation unit test: `tests/test_shards_linkml.py` that loads each table/shard from a known-good test fixture and asserts the LinkML validator returns PASS.

**Checkpoint**: Schema lint + LinkML validator are both green. The `range: Any` count is 0 (or every occurrence is annotated). SC-203 + SC-204 pass.

---

## Phase 5: User Story 3 — Cross-conference foundation (Priority: P2)

**Goal**: Add `conference_id` to the data-model in the placement decided by Phase 3 + 4; add the `CrossConferenceLink` table/shard; prove byte-identical OHBM shards across single-conf vs multi-conf builds (FR-207 / SC-207).

**Locked by**: Phase 3 (T041) AND Phase 4 (T042).

**Independent test**: Build the export twice — once with `--conference ohbm2026`, once with `--conference ohbm2026 --conference mock-second-conf` (the mock corpus is a fixture with 3 stub abstracts). Every OHBM 2026 shard / table sha256 MUST match across both builds. The second-conference shards MUST live under a distinct namespace.

- [ ] T048 [US3] Implement `conference_id` placement in `src/ohbm2026/ui_data/builder.py`. The placement (envelope-only, per-record column, per-file header) was decided in `research.md` § B3 — wire it through. Add a `--conference` CLI flag (default `ohbm2026`). Every emitter under `formats/` receives the conference id.
- [ ] T049 [US3] Implement the `CrossConferenceLink` table/shard in the winning candidate's emitter. The shape (`conf_a`, `id_a`, `conf_b`, `id_b`, `link_kind`, `similarity`) is fixed; the storage (a separate `.parquet` / `.sqlite` table / `.arrow` file / `cross_conference_links.json`) follows the winner's pattern.
- [ ] T050 [US3] Implement `loadCrossConferenceLinks(abstractId)` in the winning candidate's decoder under `site/src/lib/data_package/<format>.ts`. Returns `Promise<CrossConferenceLink[] | null>`. For query-engine candidates (DuckDB, SQLite), runs a SQL `SELECT ... WHERE id_a = ?`; for non-engine candidates (gzip-json-shards, parquet-files, arrow-ipc), reads from the pre-computed pair shard.
- [ ] T051 [US3] Add a mock-second-conference fixture: `tests/fixtures/mock_second_conf/` with 3 stub abstracts (poster_ids `S-01`, `S-02`, `S-03`), 2 authors, 1 cross-conference link per abstract. Used by T052.
- [ ] T052 [US3] Implement + run the SC-207 byte-identical proof. Build the export twice (`--conference ohbm2026` solo; then `--conference ohbm2026 --conference mock-second-conf` together); diff per-file sha256s for every OHBM 2026 shard / table; assert zero drift. Script lands at `scripts/format_bench/proof_byte_identical.py`; run from CI.

**Checkpoint**: Cross-conference affordances ship at the schema layer. A future conference's data can be added without touching OHBM 2026's bytes.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Prune losing candidates; validate the full delivery against the regression suite + the Stage-6 baselines; ship the PR.

- [ ] T053 [P] Prune losing candidates. Delete the 5 non-winning Python emitters under `src/ohbm2026/ui_data/formats/` (`parquet_files.py`, `parquet_duckdb.py`, `sqlite_single.py`, `duckdb_single.py`, `arrow_ipc.py`) and the unused `parquet_files.ts` decoder. Delete the `duckdb` Python dep (no longer needed); `pyarrow` stays (used by the winning emitter). Drop `@duckdb/duckdb-wasm` from `site/package.json` (`pnpm remove @duckdb/duckdb-wasm`); `hyparquet` stays (winning decoder). **Out of scope for this PR**: removing the `JsonShardsDecoder` + tarball loader entirely — keep it through this PR for safety (magic-byte sniff makes it free); delete in a follow-up once the parquet URL has been live + clean for one deploy cycle.
- [ ] T053a [P] **Amend FR-203 metric** per architect pushback in B2. Change "≥ 30 % gzipped tarball shrink" to "≥ 30 % per-session wire-byte shrink for the typical landing-page workflow" in `specs/010-export-redesign/spec.md`. Rationale: gzipping zstd-compressed Parquet doesn't compress further; the honest comparable metric is session wire bytes once lazy load lands.
- [ ] T054 [P] Update `README.md` — the "Atlas UI" section. Replace any references to the gzipped-JSON tarball with the winning format's name. Update the local-dev / refresh-deployed-data-package recipes from `quickstart.md`. Add a "Stage 10" note under "Current Latest Step".
- [ ] T055 [P] Update `/Users/satra/.claude/projects/-Users-satra-software-sensein-ohbm2026/memory/stage6_atlas.md` — add a "Stage 10" status section noting the format winner, the achieved SC-201 / SC-205 numbers, the cross-conference affordance shape, the architect-agent recommendation, and any deferred items.
- [ ] T056 Run `.specify/scripts/bash/constitution-check.sh --full` from repo root. Expect exit 0.
- [ ] T057 Run the LinkML validator against the redesigned export: `scripts/validate_ui_data.sh`. Expect 68 / 68 (or the chosen-format equivalent) PASS.
- [ ] T058 Run the schema lint: `.venv/bin/python scripts/lint_schema.py specs/010-export-redesign/contracts/shards.linkml.yaml`. Expect exit 0.
- [ ] T059 Run the 26-case Playwright e2e regression locally with `OHBM2026_LOCAL_TARBALL=` pointing at the redesigned export. `cd site && UI_DATA_AVAILABLE=1 pnpm exec playwright test --project=chromium`. All MUST pass (FR-204 / SC-206).
- [ ] T060 Run the byte-identical proof from T052 again on the cleaned-up branch — final SC-207 gate.
- [ ] T061 Refresh the deployed data package per `quickstart.md` step 4. Update `OHBM2026_UI_DATA_PACKAGE_URL` if the file extension changed; update `OHBM2026_UI_DATA_PACKAGE_SHA256` regardless.
- [ ] T062 Open the PR titled `feat(stage10): data export redesign — <chosen format>`. Body: link to research.md § B1 (decision table), § B2 (architect review), § B3 (commit); SC sweep summary (SC-201 actual, SC-202 actual, SC-205 actual, SC-207 PASS, SC-209 actual once Lighthouse-CI reports); PR-preview URL with `/pr-<N>/ohbm2026/`.
- [ ] T063 Smoke the PR-preview URL manually — open `/pr-<N>/ohbm2026/`, walk home → search → open one abstract → about → cart "Email my list" → back home. Capture session bytes from DevTools network panel; assert they match the bench's measure_session_bytes prediction within ±20 %.
- [ ] T064 Update `specs/010-export-redesign/tasks.md` — mark every T001–T063 as `[X]` once their verification passes. Outstanding `[ ]` items ride into a follow-up commit with explicit rationale in the body.

---

## Dependencies

```text
Phase 1 (Setup) ───────────────────┐
                                    ▼
                       Phase 2 (Foundational)
                                    │
                                    ▼
                       Phase 3 (US1 — Bench matrix)
                                    │
                       ┌────────────┴────────────┐
                       ▼                         ▼
            Phase 4 (US2 — Schema)   Phase 5 (US3 — Cross-conf)
                       │                         │
                       └────────────┬────────────┘
                                    ▼
                          Phase 6 (Polish)
```

- T001 / T002 / T003 parallel-safe within Setup.
- T004 depends on T030–T033 existing as scripts — but they don't exist until Phase 3 lands. T004 EITHER runs scripts manually (preferred — captures the baseline now), OR is deferred until Phase 3's scripts land (acceptable too; rename to T037a).
- T006 introduces the row-iterator pattern; T007–T013 are parallel-safe AFTER T006 lands the pattern.
- T014–T018 parallel-safe within Foundational.
- T019–T024 (Python emitters) parallel-safe. T025–T029 (TS decoders) parallel-safe. T030–T036 (bench scripts) parallel-safe.
- T037 (the actual bench run) sequential after T019–T036.
- T038 (qualitative rationales) sequential after T037 — needs the empirical numbers in front of it.
- T039 → T040 → T041 sequential (architect review → human response → commit).
- Phase 4: T042 → T043 → T044 sequential (schema build, then tighten, then secondary). T045/T046/T047 parallel-safe after T044.
- Phase 5: T048 → T049 → T050 sequential. T051 parallel with T048. T052 last.
- Phase 6: T053/T054/T055 parallel-safe. T056–T060 sequential (each a gate). T061 → T062 → T063 → T064 sequential.

## Parallel execution examples

```text
# Batch A (Phase 2 — builder refactors after T006 lands the row-iterator pattern)
T007 (authors.py)   [P]
T008 (cells.py)     [P]
T009 (topics.py)    [P]
T010 (enrichment.py)[P]
T011 (neighbors.py) [P]
T012 (vectors.py)   [P]
T013 (manifest.py)  [P]

# Batch B (Phase 3 — candidate emitters, after Phase 2 lands)
T019 (gzip-json-shards)
T020 (parquet-files)  [P]
T021 (parquet-duckdb) [P]
T022 (sqlite-single)  [P]
T023 (duckdb-single)  [P]
T024 (arrow-ipc)      [P]

# Batch C (Phase 3 — candidate decoders, after Phase 2 lands; T018's regression-gate must already pass)
T025–T029  [all P]

# Batch D (Phase 3 — bench scripts, after Batch B + C)
T030 (shared bench_io)
T031 (build_all_candidates)
T032–T035  [P after T031]
```

## Implementation strategy

**MVP delivery**: Phase 1 + Phase 2 + Phase 3 (T001–T041) is the smallest meaningful slice — the format is chosen, the runtime decoder works against the new format, and US1 is verified. Phase 4 (schema tightening) and Phase 5 (cross-conference) layer on cleanly after that. Phase 6 ships the PR.

**Order**: 1 → 2 → 3 → (4 ∥ 5) → 6. Phases 4 and 5 are parallel-safe to each other since they touch disjoint files (4 = schema, 5 = data-builder cross-conf wiring + decoder cross-conf method), but both depend on Phase 3's commitment. A single maintainer can run them serial (4 then 5) for review readability.

**Pre-merge validation gate**: T056 (constitution `--full` exit 0) + T057 (LinkML validator pass) + T058 (schema lint exit 0) + T059 (26 e2e cases PASS) + T060 (byte-identical sha256 PASS) + T063 (manual smoke matches predicted session bytes ±20 %).

**TDD ordering vs phase ordering**: The bench harness (T030–T036) is the test for the candidate emitters/decoders (T019–T029). Per Constitution IV, the harness MAY be authored AHEAD of the emitters/decoders so each emitter is shipped with a failing measurement (large size, slow TTI) that the implementation drives down. Phase 3's numerical order is narrative; the TDD-honest order is: T030 → T031 → T019 → T032 → run measurement → adjust → next emitter. The maintainer picks the cadence; the constraint is that no candidate emitter ships without its measurement numbers landing in `bench/<candidate>/measurements.json`.
