# Implementation Plan: Data export redesign — LinkML-tight schema + compact storage + cross-conference foundation

**Branch**: `010-export-redesign` | **Date**: 2026-05-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/010-export-redesign/spec.md`

## Summary

The Atlas's exported data package (currently 26 MB gzipped JSON tarball / 96 MB uncompressed / 633-line LinkML schema with 3 `range: Any` slots) is being re-architected with three coupled goals:

1. **LinkML-tight schema** — every `range: Any` either replaced by a concrete inner class or retained with an inline `# LIMITATION:` rationale (FR-201 / SC-203).
2. **Compact storage** — at least 30 % smaller gzipped tarball, 20 % smaller uncompressed (FR-203 / SC-201 / SC-202), with the home page interactive before the heaviest shard finishes loading (FR-205 / SC-205).
3. **Cross-conference foundation** — a `conference_id` affordance + a cross-conference linking surface, such that a future second conference (ISMRM 2027, a NeuroScape PubMed projection) can be added without regenerating OHBM 2026's shards (FR-206 / FR-207 / FR-208 / SC-207 / SC-208).

**The format choice is empirically determined, not pre-committed.** Phase 0 of this plan runs a documented bench matrix across six candidate storage containers (status-quo-tightened JSON, multi-file Parquet, Parquet + DuckDB-WASM, single-file SQLite, single-file DuckDB, Arrow IPC) measuring six metrics per candidate (FR-212 / SC-211). The architect-agent review (FR-209) sits in front of the populated table. The format choice happens AFTER the bench, NOT before. Phase 1 design artifacts (data-model.md, contracts/) are therefore format-conditional: their final shape is locked once the bench commits to a winner.

## Technical Context

**Language/Version**: Python 3.14 (data-builder under `src/ohbm2026/ui_data/`); TypeScript 5 / Svelte 5 / Vite 6 (runtime decoder under `site/src/lib/`). Bench scripts and the LinkML edits live in Python.
**Primary Dependencies**: `linkml-runtime` (validator unchanged); candidate-format dependencies added per the bench results — possibilities include `pyarrow` (Parquet), `duckdb` (DuckDB Python build), `apache-arrow` (Arrow IPC). Browser-side decoders depend on the chosen format: `@sqlite.org/sqlite-wasm`, `@duckdb/duckdb-wasm`, `hyparquet`, `apache-arrow` are all candidates pending Phase 0.
**Storage**: The output is a static container served from the existing Dropbox URL (`OHBM2026_UI_DATA_PACKAGE_URL`). No database. The on-disk format is one of the six bench candidates; the choice is recorded in `research.md`.
**Testing**: `scripts/validate_ui_data.sh` (LinkML validation), Vitest (unit tests in the data_package decoder), Playwright (the eight existing e2e specs MUST still pass — FR-204 / SC-206). A NEW set of `bench` scripts under `scripts/format_bench/` runs each candidate's build + measurement.
**Target Platform**: Same as Stage 6/9 — GitHub Pages serving a SvelteKit static build, browsers ≥ 2 years old. New constraint: the chosen format MUST work on mobile Safari (which excludes WASM features only available in Chromium).
**Project Type**: Static data export pipeline; web-only consumer.
**Performance Goals**: SC-205 (home interactive in ≤ 3 s on 1 Mbps even with the heaviest shard incomplete); SC-209 (Lighthouse FCP + LCP each improve by ≥ 10 % vs. the Stage-6 baseline). Cold-start TTI on 1 Mbps is the single most-load-bearing metric in the bench.
**Constraints**: Deterministic build (FR-210) — same inputs MUST produce byte-identical outputs across runs, for Dropbox share-link inode preservation. Zero UI feature regression (FR-204) — every existing testid and route stays functional.
**Scale/Scope**: 3,244 OHBM 2026 abstracts (today's corpus); ~100 MB uncompressed JSON today. Future scale: O(10 K) abstracts per added conference, up to ~1 M for the PubMed-NeuroScape projection if it lands. The chosen format's scaling characteristics figure into the bench's qualitative rating.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Reproducible Venv Execution** — PASS. Bench scripts run through `.venv/bin/python`. New dependencies (pyarrow, duckdb, etc.) install through `uv pip install --python .venv/bin/python ...` only.
- **II. Immutable Evidence And Canonical Data** — PASS. No corpus rewrite; the data builder reads `data/primary/abstracts.json` etc. (unchanged) and emits the new container. The `data/`, `site/static/data/`, `site/publish/` gitignored roots stay gitignored. Bench result CSVs land in `research.md` (committed) but the per-candidate generated containers stay in a gitignored bench directory.
- **III. Resumable, Auditable Pipelines** — PASS. Same Stage 5 contract: deterministic build, run-level provenance under `data/provenance/`. The bench is a one-shot research activity, not a pipeline.
- **IV. Plan-First, Test-Driven Delivery** — PASS. This plan precedes the rework; the bench scripts have their own verification (sha256 of output vs. expected, byte-identical re-runs). The existing 26 Playwright e2e cases are the regression gate (FR-204 / SC-206).
- **V. Secret-Safe, Reviewable Delivery** — PASS. No new secrets. Commits land in small slices: bench scripts → bench results → format choice → schema edits → data-builder edits → runtime decoder edits → CI workflows. Each slice's verification is named.
- **VI. Fail Loudly, No Shortcuts** — PASS. If no bench candidate meets the SC-201/SC-202 thresholds, the plan explicitly degrades to "keep status quo, re-scope" (named in the spec's assumptions) rather than ship a marginal win and claim victory. No `--no-verify`, no silent fallbacks.
- **VII. Discover External State, Don't Hardcode It** — PASS. The chosen format's specific tuning (Parquet row-group size, SQLite page size, etc.) is captured per-candidate in research.md and discovered/tuned at build time, not hardcoded.
- **VIII. Provenance For Organizer-Facing Outputs** — PASS. The chosen container WILL preserve the existing `build_info` envelope (state-keys, code revision, timestamps). Whether `build_info` lives as a Parquet metadata block, a SQLite `meta` table, or a JSON sidecar is one of the bench's qualitative metrics. The deploy SHA stays visible in the page title + footer (FR-110 / SC-106 from spec 009, unchanged).

**Verdict: GATE PASSES. No Complexity Tracking entries needed.**

## Project Structure

### Documentation (this feature)

```text
specs/010-export-redesign/
├── plan.md              # This file — captures the bench methodology, constitution check, phase plan
├── research.md          # Phase 0 — bench matrix design + populated results + architect review
├── data-model.md        # Phase 1 — format-agnostic entity inventory + format-conditional table shapes (finalised after bench)
├── quickstart.md        # Phase 1 — how to run the bench locally + how to rebuild the redesigned export
├── contracts/
│   ├── shards.linkml.yaml  # The redesigned LinkML schema (replaces specs/008-ui-rewrite/contracts/ui_data.linkml.yaml)
│   └── decoder.md          # The runtime decoder interface: what `loadAbstracts()` / `loadEnrichment()` look like under the chosen format
├── checklists/
│   └── requirements.md  # Spec quality gate (from /speckit-specify)
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/ohbm2026/ui_data/
├── builder.py                     # extended: --output-format flag, calls into one of the format-specific emitters
├── formats/                       # NEW package, one emitter module per bench candidate
│   ├── __init__.py
│   ├── json_shards.py             # status-quo-tightened JSON (today's emitters refactored here)
│   ├── parquet_files.py           # multi-file Parquet
│   ├── parquet_duckdb.py          # Parquet files annotated for DuckDB-WASM consumption
│   ├── sqlite_single.py           # single-file SQLite (FTS5 + range-fetch VFS metadata)
│   ├── duckdb_single.py           # single-file .duckdb
│   └── arrow_ipc.py               # Arrow IPC record-batch files
└── (existing per-shard modules: abstracts.py, authors.py, etc. — refactored to emit table rows rather than JSON shards)

scripts/format_bench/              # NEW — bench harness
├── README.md                      # how to run; reads from `data/primary/` + `data/outputs/analysis/`
├── build_all_candidates.py        # builds each candidate from the same corpus
├── measure_size.py                # disk + on-the-wire size per candidate
├── measure_tti.py                 # Playwright-driven cold-start TTI on a throttled link
├── measure_session_bytes.py       # typical-session wire-bytes (home → search → open one abstract → about)
├── measure_decoder_bundle.py      # browser-side JS+WASM bundle delta vs Stage-6 baseline
└── render_decision_table.py       # builds the populated decision matrix → research.md

site/src/lib/data_package/         # NEW namespace; replaces today's `data_package.ts` + `shards.ts`
├── decoder.ts                     # format-agnostic interface: loadManifest, loadAbstracts, loadAbstractByPosterId, loadCell, …
├── json_shards.ts                 # today's loader, kept as the baseline candidate
├── parquet_files.ts               # via `hyparquet` (or chosen JS Parquet reader)
├── parquet_duckdb.ts              # via `@duckdb/duckdb-wasm`
├── sqlite_single.ts               # via `@sqlite.org/sqlite-wasm`
├── duckdb_single.ts               # via `@duckdb/duckdb-wasm` against a single .duckdb file
├── arrow_ipc.ts                   # via `apache-arrow`
└── index.ts                       # picks the loader from `manifest.json`'s `format` field

scripts/
└── validate_ui_data.sh             # extended: validates against the chosen format's emitted output

.github/workflows/
└── (no changes expected — deploy-ui.yml / pr-preview.yml already pull from a single env-var URL; the URL just points at a different container)
```

**Structure Decision**: The data builder's existing per-shard modules (`abstracts.py`, `authors.py`, etc.) are refactored to emit ROWS rather than JSON shards. Each candidate format gets a thin emitter module under `src/ohbm2026/ui_data/formats/` that consumes those rows and writes the format's specific output. The runtime decoder gets the same split: a format-agnostic interface (`decoder.ts`) plus one decoder implementation per candidate, with `manifest.json` carrying a `format` field that picks the right loader at runtime. This lets the bench produce 6 working containers from the same builder code and switch the production deploy by changing one env-var or one manifest line — no rewrites of `+page.svelte` or any UI component.

## Phase 0: Outline & Research — The Bench Matrix

Phase 0 IS the bench. The plan defers every format-dependent decision to the empirical results captured in `research.md`. The flow:

1. **Build six candidates** from the same source corpus (`data/primary/abstracts.json`, `data/primary/abstracts_enriched.sqlite`, `data/outputs/analysis/annotations__<state-key>.sqlite`, `data/outputs/embeddings/...`). Each candidate is a self-contained `bench/<candidate-name>/` directory under a gitignored bench workspace.
2. **Measure** six metrics per candidate:
    - (a) **Total on-disk size** (`du -b`).
    - (b) **Cold-start TTI** on a 1 Mbps / 100 ms RTT throttled link to "search-input visible AND result grid populated". Playwright-driven (`scripts/format_bench/measure_tti.py`).
    - (c) **Session wire bytes** for the typical user session: home → search "memory" → open one abstract → open About → return home. Measured by intercepting all `fetch()` calls in the worker.
    - (d) **In-browser decoder bundle cost**: the JS + WASM bytes delivered for the chosen format's runtime, minus the Stage-6 baseline. (Hyparquet ~300 KB; SQLite-WASM ~1.5 MB; DuckDB-WASM ~6 MB; Arrow ~500 KB; status quo 0.)
    - (e) **Cross-conference linking feasibility**: qualitative (with a one-paragraph rationale per candidate). Possible values: "native SQL JOIN", "single-key lookup", "requires pre-computed table", "no path".
    - (f) **LinkML-schema fidelity**: qualitative. "Native (per-column types)", "Adapter (JSON-blob columns)", "Loose (opaque container)".
3. **Render the decision table** in `research.md` with one row per candidate, six columns + a "notes" column.
4. **Architect-agent review** runs in front of the populated table (FR-209 / SC-210). The agent's report — strengths, weaknesses, the recommendation — lands in `research.md` alongside the table. The human responds in writing in the same file.
5. **Commit to a format**. The chosen format's row in the decision table is highlighted; the rationale is the agent review + the human responses.

If no candidate clears SC-201 (≥ 30 % shrink) AND SC-205 (TTI ≤ 3 s on 1 Mbps), the spec's "no-result fallback" applies: we keep status quo, re-scope, and the rework reduces to "schema tightening only" (FR-201 + SC-203) with no storage change.

**Output**: `research.md` — bench methodology, scripts inventory, populated decision table, architect review, committed format choice with citation.

## Phase 1: Design & Contracts

**Prerequisites**: `research.md` Phase 0 complete; format choice committed.

1. **`data-model.md`** — populated AFTER the format is chosen. Two sections:
    - **Format-agnostic entity inventory**: the 8 entity types the UI consumes (Manifest, Abstract, Author, Cell, Topic, Neighbour, EnrichmentRecord, MinilmVectorsSidecar). These don't change with the format — they're the existing Stage-6 shape.
    - **Format-conditional table layout**: the chosen format's specific shape — column types for Parquet/Arrow, table-with-FTS5 for SQLite, etc. Includes the `conference_id` placement (FR-206) and the cross-conference linking surface (FR-208) in the form the bench committed to.

2. **`contracts/shards.linkml.yaml`** — the redesigned LinkML schema. Replaces `specs/008-ui-rewrite/contracts/ui_data.linkml.yaml`. Tightening pass covers:
    - The 3 known `range: Any` slots (Manifest.topic_shards, Abstract.facets, Enrichment.records).
    - The secondary looseness identified in the Explore survey (UMAP coord arrays, missing ECO-code enum, parallel-array fields without cross-validation, missing `minimum_cardinality` on multi-valued slots).
    - Any new affordances the chosen format introduces (e.g., Parquet column types, SQLite tables, DuckDB views).

3. **`contracts/decoder.md`** — the runtime decoder interface. A short markdown spec defining the seven `load*()` functions the UI calls, their signatures, error semantics, and the lazy-load contract (FR-205): which functions MAY block, which MUST return synchronously after the first paint.

4. **`quickstart.md`** — local-dev recipe:
    - How to run the bench locally (`PYTHONPATH=src .venv/bin/python scripts/format_bench/build_all_candidates.py …`).
    - How to rebuild the production export after the format is chosen (`scripts/build_ui_data.py` + the new `--output-format` flag).
    - How to validate the LinkML schema against the rebuilt export.
    - How to verify the existing 26 Playwright e2e cases pass against the new format locally.

5. **CLAUDE.md SPECKIT block** updated to point at this plan.

**Output**: `data-model.md`, `contracts/shards.linkml.yaml`, `contracts/decoder.md`, `quickstart.md`, refreshed `CLAUDE.md` SPECKIT block.

## Complexity Tracking

No constitution violations. The plan adds:
- One new package (`src/ohbm2026/ui_data/formats/`) with up to 6 emitter modules — but at most ONE will be retained after the bench commits. The losing candidates are pruned in the post-bench cleanup.
- One new bench harness directory (`scripts/format_bench/`) — research artifact; pruned or moved into a permanent regression suite after the bench commits.
- One new runtime decoder namespace (`site/src/lib/data_package/`) — replaces today's flat `data_package.ts` + `shards.ts`. Retained.

The plan is intentionally over-built for Phase 0 (six emitters, six decoders) because the bench cannot be run without them. Phase 1 prunes back to the chosen format. The peak complexity occurs during the bench, not at the post-merge end state.
