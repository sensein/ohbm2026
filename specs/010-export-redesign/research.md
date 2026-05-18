# Phase 0 Research — The Bench Matrix

This research doc has two layers:

- **Layer A — bench methodology** (this commit): the experimental protocol, the candidate inventory, the measurement procedures. Locked in by `/speckit-plan` so the bench is reproducible and the architect-agent review (FR-209 / SC-210) is calibrated to a known protocol.
- **Layer B — bench results + format choice** (filled in during `/speckit-implement`): one row per candidate, six measured metrics each, the architect-agent's findings, the human responses, the committed format.

Layer B sections are stubbed with `<RESULTS LANDS HERE>` markers. They MUST be filled in before any format-conditional Phase 1 / Phase 2 work begins.

---

## A1. Source corpus for the bench

Every candidate is built from the SAME inputs to keep the comparison apples-to-apples:

| Input | Path | Why it matters |
|---|---|---|
| Accepted OHBM 2026 abstracts | `data/primary/abstracts.json` | The corpus — titles, sections, facets, authors. |
| Enriched corpus (claims, figures, references) | `data/primary/abstracts_enriched.sqlite` | The 34 MB enrichment-side bytes that dominate today's tarball. |
| Stage-4 rollup (per-cell UMAP + clusters) | `data/outputs/analysis/annotations__<state-key>.{sqlite,parquet}` | The Cells + Topics + Neighbours tables. |
| Per-component embedding bundles | `data/outputs/embeddings/<model>/...` | Source for the `minilm_vectors.bin` int8 sidecar. |
| Authors corpus | `data/primary/authors.json` | The Authors table. |

The state-key is pinned to whatever `main` is currently building (`f0c51e80dc0e` per Stage-2.1). Every candidate's output reflects the same input fingerprint, so size deltas can be attributed to the format alone.

## A2. Candidate inventory

Six candidates, all built from the same row-level input. Pinned versions go in `scripts/format_bench/build_all_candidates.py` to make the bench reproducible.

| # | Candidate | Container shape | Browser decoder | Notes |
|---|---|---|---|---|
| 1 | **status-quo-tightened** | gzipped tarball of JSON shards | none (built-in `DecompressionStream`) | Today's shape minus unused fields, with numeric arrays moved to binary sidecars; alternate compression (brotli/zstd) tested. Lower bound on improvement. |
| 2 | **multi-file Parquet** | per-table `.parquet` files, no tarball | `hyparquet` (~300 KB) | Range-request fetch on row-group boundaries; no SQL engine; cross-conf via pre-computed pair shards. |
| 3 | **Parquet + DuckDB-WASM** | same `.parquet` files as #2 | `@duckdb/duckdb-wasm` (~6 MB) | SQL JOINs over `httpfs`-ranged Parquet; cross-conf JOIN is native. |
| 4 | **single-file SQLite** | one `.sqlite` blob with FTS5 | `@sqlite.org/sqlite-wasm` (~1.5 MB) | One container, range-fetched via SQLite-WASM's range-read VFS; FTS5 for lexical search. |
| 5 | **single-file DuckDB** | one `.duckdb` file | `@duckdb/duckdb-wasm` (~6 MB) | One container, native DuckDB query engine; cross-conf via attached secondary DBs. |
| 6 | **Arrow IPC** | one `.arrow` (or per-table `.arrow`) | `apache-arrow` (~500 KB) | Record-batch-level range-fetch; no SQL; columnar like Parquet but different metadata. |

If a candidate is unbuildable for a clear reason (e.g., a candidate library has no published mobile-Safari WASM build), it's recorded in the table as `unbuildable: <reason>` rather than dropped silently.

## A3. Metrics

Six metrics per candidate. Each metric has a measurement script under `scripts/format_bench/`.

### A3.1 — Total on-disk size

- **Script**: `measure_size.py`.
- **What**: `du -b` of the candidate's complete output. For multi-file containers (#2, #3), the sum across all files. For single-file containers (#4, #5, #6 if single-file), the one file's size.
- **Also recorded**: per-file breakdown for multi-file containers (so we can attribute bytes per table).
- **Pass threshold**: SC-201 calls for ≤ 18 MB total (≥ 30 % reduction vs the 26 MB status-quo gzipped baseline).

### A3.2 — Cold-start TTI on a throttled link

- **Script**: `measure_tti.py` — Playwright-driven, runs against the local `stage-and-serve` harness with browser-context throttling at 1 Mbps / 100 ms RTT.
- **What**: wall-clock from `page.goto('/ohbm2026/')` to the moment `[data-testid="search-input"]` is visible AND `[data-testid="result-count"]` shows a numeric value.
- **Three runs**, median reported; outlier (max - min > 30 %) re-runs the candidate.
- **Pass threshold**: SC-205 calls for ≤ 3 000 ms on the throttled profile.

### A3.3 — Session wire bytes

- **Script**: `measure_session_bytes.py` — Playwright in headed mode, with a request-recorder hook that captures EVERY `fetch()` request the page makes for 60 s. The session: `goto('/ohbm2026/')` → type "memory" → wait for results → open the first card → wait for the detail panel → click "About" → wait for the About page → click back to home.
- **What**: total `Content-Length` of all responses during that session, including the format's runtime decoder + the data-container bytes.
- **Two runs**, median reported.
- **Comparison**: Stage-6 baseline ≈ 26 MB (the whole tarball). Lazy-load candidates should land much lower.

### A3.4 — In-browser decoder bundle cost

- **Script**: `measure_decoder_bundle.py` — runs `pnpm build` with each candidate's decoder bundled in, then `du -b` on the chunked JS + WASM files specific to that decoder. Subtracts the Stage-6 baseline bundle size.
- **What**: net new bytes the browser fetches for the decoder, gzip-after-Vite figures used.
- **One-shot per candidate** (deterministic).

### A3.5 — Cross-conference linking feasibility (qualitative)

- **Method**: per-candidate write-up in `research.md`. The architect-agent (FR-209) reviews each candidate's answer.
- **Rubric**:
    - **Native SQL JOIN** — query engine present (DuckDB, SQLite), cross-conf is `JOIN abstracts a ON p.a_id = a.id`. (Candidates #3, #4, #5 likely.)
    - **Single-key lookup** — cross-conf table is itself an index keyed by `(conf_a, id_a) → (conf_b, id_b, score)`; loadable in JS as a Map. (Candidates #1, #2, #6.)
    - **Requires pre-computed table** — the cross-conf surface lives in a separate shard built post-hoc; works under any candidate but is mandatory under non-query-engine ones.
    - **No path** — would require regenerating the base tables; FAIL.
- One rubric tag per candidate + a one-paragraph rationale.

### A3.6 — LinkML schema fidelity (qualitative)

- **Method**: per-candidate write-up. The architect-agent reviews the candidate's claim.
- **Rubric**:
    - **Native** — the format admits per-column / per-attribute types that round-trip the LinkML schema with no `range: Any` and no JSON-blob columns. (Parquet typed columns, DuckDB / SQLite typed columns, Arrow typed columns — all candidates 2–6 likely.)
    - **Adapter (one JSON-blob column)** — the LinkML schema is mostly native EXCEPT for the string-keyed dicts (today's 3 `range: Any` slots), which become one JSON-string column with a `# LIMITATION:` annotation.
    - **Loose** — the schema degrades to "opaque container of bytes" (a candidate that can't carry the schema at all — none expected here).
- One rubric tag per candidate + a one-paragraph rationale.

## A4. Bench execution protocol

1. Bootstrap the bench workspace (gitignored): `mkdir -p bench/`. Each candidate gets a subdirectory.
2. Run `build_all_candidates.py` — builds all 6 candidates in parallel where possible. Total expected wall-clock: 5–15 min on the maintainer's local machine.
3. Run the four scripted measurement scripts (`measure_size`, `measure_tti`, `measure_session_bytes`, `measure_decoder_bundle`) per candidate, in series (TTI + session-bytes use Playwright, which needs serial port 4173).
4. For #5 (linking feasibility) and #6 (schema fidelity), the maintainer fills the per-candidate rationale in `research.md` directly.
5. Run `render_decision_table.py` — assembles all measurements into the Layer-B table.
6. Spawn an Agent (the architect agent) with the populated table in its prompt. The agent reviews the matrix and recommends a format with a written rationale.
7. The maintainer responds in writing (agree / disagree / push back), commits the format choice.

The whole sequence is one focused session. If it stretches to multiple sessions, the bench workspace is preserved in `bench/` (gitignored) so the work resumes mid-flight.

## A5. The no-result fallback

If, after the bench, no candidate clears BOTH SC-201 (≥ 30 % gzipped shrink) AND SC-205 (≤ 3 s TTI on 1 Mbps), the rework downgrades to **schema tightening only**: FR-201 + FR-202 + SC-203 + SC-204 (the LinkML edits) ship; the format stays gzipped JSON; FR-203 / SC-201 / SC-202 / SC-205 / SC-209 are explicitly waived with a one-line rationale citing the bench result. The cross-conference affordances (FR-206 / FR-207 / FR-208 / SC-207 / SC-208) still ship at the schema layer.

This fallback is named here so the architect-agent review knows the floor exists. It is NOT the expected outcome.

---

## Layer B — Bench results

> Filled in during `/speckit-implement`. Until then, every cell below reads `<RESULTS LANDS HERE>`.

### B1. Decision table

| # | Candidate | A3.1 size (MB) | A3.2 cold-start TTI (ms, median of 3) | A3.3 session bytes (MB) | A3.4 decoder bundle (KB) | A3.5 cross-conf | A3.6 schema fidelity | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | status-quo-tightened (gzip)  | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |
| 1b | status-quo-tightened (brotli) | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |
| 1c | status-quo-tightened (zstd)   | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |
| 2 | multi-file Parquet | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |
| 3 | Parquet + DuckDB-WASM | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |
| 4 | single-file SQLite | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |
| 5 | single-file DuckDB | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |
| 6 | Arrow IPC | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` | `<RESULTS LANDS HERE>` |

Baseline references (Stage 6) — captured 2026-05-18 against `main`:
- **A3.1 baseline (gzipped tarball size)**: **26 914 297 bytes** (= 25.67 MiB / 26.91 MB) — `site/publish/data-package.tar.gz` after a fresh `pnpm preview:gh-pages` rebuild.
- **A3.2 baseline (cold-start TTI on 1 Mbps)**: `<RESULTS LANDS HERE>` — captured when the bench harness lands (T033).
- **A3.3 baseline (session wire bytes)**: ≈ 27 MB (the whole tarball + decoder bundle ~0); full measurement when T034 lands.
- **A3.4 baseline (decoder bundle delta)**: 0 — Stage 6 uses only browser-native `DecompressionStream('gzip')` + a ~50-line tar parser inline in the worker.

Per-shard byte breakdown (uncompressed JSON, 100 908 678 bytes / 96.23 MiB total):

| Shard | Size (bytes) | % of corpus |
|---|---|---|
| `enrichment.json` | 35 824 451 | 35.5 % |
| `abstracts.json` | 32 047 513 | 31.8 % |
| `authors.json` | 4 312 311 | 4.3 % |
| `search/minilm_vectors.bin` (binary sidecar) | 1 245 312 | 1.2 % |
| neighbors/*.json (15 files combined) | 14 992 174 | 14.9 % |
| cells/*.json (15 files combined) | 9 942 718 | 9.9 % |
| topics/*.json + manifest.json | ~2 500 000 | 2.5 % |

Hotspot confirmation: `enrichment.json` + `abstracts.json` = **67.3 %** of the uncompressed bytes. Any shrink strategy that doesn't touch those two is bounded at ≤ 33 % improvement.

### B2. Architect-agent review

> Findings + recommendation land here, dated. Capture both the agent's report AND the maintainer's responses.

### B3. Committed format choice

> Single paragraph: which candidate wins, citing the table row + the architect review. Becomes the input to Phase 1's `data-model.md` and `contracts/shards.linkml.yaml`.
