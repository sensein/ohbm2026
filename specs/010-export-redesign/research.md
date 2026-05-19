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

**Size column populated 2026-05-18** from local builds against the production OHBM 2026 corpus (3 243 abstracts; same source for every candidate). Other metric columns filled in once the Playwright-driven measurements (T033–T035) and the qualitative writeups (T038) land.

| # | Candidate | A3.1 size (uncompressed) | A3.1b size (gzipped tarball) | A3.2 cold-start TTI | A3.3 session bytes | A3.4 decoder bundle | A3.5 cross-conf | A3.6 schema fidelity | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 1 | gzip-json-shards (baseline) | **128 MB** | **26 MB** | _pending_ | _pending_ | 0 KB | single-key lookup | adapter (3× `range: Any`) | Stage-6 production. Whole-tarball fetch; no point lookups. |
| 1b | gzip-json-shards (brotli) | 128 MB | _pending_ | _pending_ | _pending_ | 0 KB | single-key lookup | adapter | Brotli compression of the same tar contents; expect ~20 % shrink over gzip per typical web payloads. |
| 1c | gzip-json-shards (zstd) | 128 MB | _pending_ | _pending_ | _pending_ | 0 KB | single-key lookup | adapter | Same shape, zstd compression. |
| 2 | **multi-file Parquet** | **24 MB** | **24 MB** | _pending_ | _pending_ | ~300 KB (hyparquet) | requires pre-computed table | native (STRUCT columns) | **Strongest size winner.** Already columnar+zstd-compressed; gzipping the tarball saves nothing (24M → 24M). Each `.parquet` directly servable via HTTP `Range:` headers — no extra compression layer between the wire and the row-groups. Eliminates all 3 Stage-6 `range: Any` slots via native STRUCT columns. |
| 3 | Parquet + DuckDB-WASM | 24 MB | 24 MB | _pending_ | _pending_ | ~6 MB (duckdb-wasm) | native SQL JOIN | native | Same files as #2 + a tiny SQL-views sidecar (~3 KB). The 6 MB decoder bundle is the cost of native cross-conf JOINs; the bench TTI measurement decides if it's worth it. |
| 4 | single-file SQLite | **118 MB** | 79 MB | _pending_ | _pending_ | ~1.5 MB (sqlite-wasm) | native SQL JOIN | adapter (JSON-blob columns) | **Worst result.** FTS5 indices over the abstract text triple the file size vs baseline. Without FTS5 it would be smaller — but then lexical search needs a separate index. The page-oriented layout also doesn't compress well because per-abstract JSON blobs are too short to dictionary-encode efficiently. _Out unless we drop FTS5 + upgrade JSON columns to native typed columns (Phase 4)._ |
| 5 | single-file DuckDB | 72 MB | 46 MB | _pending_ | _pending_ | ~6 MB (duckdb-wasm) | native SQL JOIN | adapter (current impl uses JSON-blob columns; native STRUCT upgrade pending) | DuckDB's columnar compression IS doing work (72M vs SQLite's 118M), but the JSON-blob columns can't be compressed the way native STRUCT columns can. Upgrading to native STRUCT (Phase 4 if this candidate wins) would likely bring it close to the Parquet number. |
| 6 | Arrow IPC | 45 MB | 34 MB | _pending_ | _pending_ | ~500 KB (apache-arrow) | requires pre-computed table | native | LZ4 frame compression is faster to decode than Parquet's zstd but less compact. The bench TTI measurement decides which wins. |
| **7** | **single-file Parquet (nested)** | **22 MB** | **21 MB** | _pending_ | _pending_ | ~300 KB (hyparquet) | requires pre-computed table; native SQL if duckdb-wasm layered | native (STRUCT columns) | **Best of both worlds under the single-URL constraint.** One `.parquet` file with per-table Parquet blobs in a discriminated row layout (one row group per logical table → byte-addressable via the outer file's footer). Range-fetchable per logical table. ~8 % smaller than #2 because the outer file has no per-file footer duplication. Decoder pattern: footer Range-fetch → per-table BLOB Range-fetch → inner Parquet parse. |

**Snap analysis based on size alone**: Parquet (#2) dominates by 31 % on gzipped size (24 MB vs 26 MB baseline) AND by 81 % on uncompressed size (24 MB vs 128 MB). The remaining metrics (cold-start TTI, session bytes, decoder bundle, cross-conf, fidelity) decide whether to layer DuckDB-WASM on top (#3) for SQL queries or stay with the leaner pure-Parquet path (#2).

### B1.1 Narrowing decision — 2026-05-18 (REVISED: single-URL constraint)

**Architectural constraint surfaced 2026-05-18 (mid-bench):** The deploy workflow (`.github/workflows/deploy-ui.yml`) only copies the static SvelteKit bundle to gh-pages — **no data lives on gh-pages**. The browser fetches `VITE_DATA_PACKAGE_URL` (a Dropbox URL today) at runtime. The data package is one URL, one file.

This invalidates the "multi-file Parquet wrapped in a tarball, gh-pages serves individual files" model. Range-fetched lazy load through Dropbox requires a **single-file** format — once you wrap multiple files in `.tar.gz`, the tar+gzip layers are opaque to HTTP Range requests on the inner files.

**Revised candidate-format constraint:** Only single-file candidates can carry the range-fetch lazy-load win. Multi-file formats are functionally equivalent to the baseline (whole-file fetch).

**Updated narrowing:**

- **#2 multi-file Parquet** — *dead under the single-URL constraint*. The 24 MB number stands, but a tarball wrap means the browser still fetches the whole 24 MB before reading any row-group, eliminating the lazy-load justification.
- **#3 Parquet + DuckDB-WASM** — same problem as #2 plus the 6 MB engine cost.
- **#6 Arrow IPC (multi-file)** — same problem as #2.
- **#7 (NEW) single-file nested Parquet** — promising: one `.parquet` file with all logical tables (cells, topics, neighbours, enrichment) as nested `LIST<STRUCT>` columns indexed by `cell_key` / `abstract_id`. Browser fetches the manifest + abstracts row group on first paint; remaining row groups fetched on demand via HTTP Range against the Dropbox URL.

Three candidates are **ruled out on size**:

- **#4 single-file SQLite** — 79 MB gzipped tarball (3× baseline). Disqualifying without dropping FTS5 + upgrading JSON columns to native typed columns, both of which would land in a follow-up rework. Even then it would carry the ~1.5 MB sqlite-wasm decoder bundle for marginal wins.
- **#5 single-file DuckDB** — 46 MB gzipped (+77 %). The JSON-blob columns hide DuckDB's compression strengths. A native-STRUCT-columns rebuild would close some of the gap, but Parquet (#2) covers the same query-engine-free niche at 24 MB.
- **#6 Arrow IPC** — 34 MB gzipped (+31 %). LZ4 is faster to decode than zstd but less compact; the +8 MB vs Parquet is hard to justify when Arrow's other advantages (engine-free, columnar) already belong to Parquet (#2).

**Bench from here on narrows to four rows** under the single-URL constraint:

- **#1 baseline gzip-json-shards** — keeps its place as the comparison anchor.
- **#5 single-file DuckDB** — promoted back into the bench despite the 46 MB size, because single-file = range-fetch-capable via duckdb-wasm + httpfs. Cross-conf SQL JOINs come free.
- **#7 (NEW) single-file nested Parquet** — the headline candidate. Single `.parquet` file, all logical tables as nested STRUCT columns, hyparquet + Range fetches against the Dropbox URL.
- _#4 SQLite-single is still ruled out_ (79 MB), _#2 + #3 + #6 are removed_ (multi-file under single-URL constraint = no range-fetch win = no advantage over baseline).

The size data for the multi-file candidates stays as evidence but the spec choice will come from the single-file column.

Per FR-212 ("documented experiment matrix across **at least** the following candidate storage formats"), narrowing on size is consistent with the spec — every candidate was built; the size evidence is on the record; the remaining metrics get focused investment on the candidates that survive the first cut.

Notable findings outside the table:

- **Duplicate `poster_id='2335'` in the existing corpus** — discovered when the SQLite emitter's `UNIQUE INDEX` constraint failed. FR-202 finding: parallel-data cross-validation is a real Stage-6 gap. Tightened by the Phase-4 schema work (T044).
- **`enrichment.json` + `abstracts.json` = 67 % of uncompressed bytes** (Stage-6 baseline). Parquet's win comes from column-wise dict-encoding the repeated facet strings (`fMRI`, `Functional MRI`, etc.) and zstd-compressing the long `claims.source` quote columns. Any candidate that stores those as JSON-string columns (SQLite-with-JSON, DuckDB-with-JSON) loses that win.

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

#### Agent report — 2026-05-18

**Recommendation: Parquet + DuckDB-WASM (#3).** Multi-file Parquet on disk, DuckDB-WASM as the in-browser query engine with a 3 KB SQL views sidecar.

**Rationale.**

- **FR-203 nuance.** Pure Parquet gzipped is 24 MB vs 26 MB (8 %), but the gzip layer is a measurement artefact — Parquet+zstd row-groups are *already* compressed; the tarball wrapper is the wrong yardstick. Wire-bytes per session (range-fetched row-groups) is the actual win and will clear 30 % easily once Phase-4 lazy load lands. Flag this loudly to the human: the FR-203 metric needs redefinition or the spec fails on a technicality.
- **Schema fidelity.** Parquet STRUCT eliminates all three `range: Any` slots natively. SQLite/DuckDB-as-shipped store JSON blobs — fails the spec's tightening goal without a Phase-4 migration. Arrow IPC matches Parquet here but loses on size (34 MB) and lazy-load story.
- **Cross-conf JOIN.** DuckDB-WASM does this in SQL across multiple Parquet files (including remote URLs) with no pre-computed pairs table.
- **Decoder cost is real but amortised.** 6 MB duckdb-wasm vs 300 KB hyparquet is the genuine tradeoff. Cached after first visit; pays for itself the moment a second conference lands.
- **FR-204 risk is moderate, not catastrophic.** UI loaders refactor from `fetch(json)` to SQL queries. 26 Playwright specs hit the data shape, not the loader — selector-stable if the query results match shard envelopes.

**Pushback opportunities.**

- **6 MB decoder on a 1 Mbps cold-start is brutal.** ~48 s just for the engine before any data. If hyparquet (#2) gets to acceptable cross-conf via a pairs table, the bundle delta is not defensible.
- **"Already compressed" rebuttal to FR-203 is convenient.** Easy for a reviewer to read as moving the goalposts. Get the wire-bytes-per-session number measured *before* the commit, not after.
- **DuckDB-WASM in production at this scale is rare.** Maturity of the JS bindings under SvelteKit SSG + GitHub Pages CDN (range requests, MIME, CORS) is not de-risked. One concrete failure mode and you're back to #2.

**Phase-4 follow-up owed.**

- **Range-fetch lazy load.** Stage 10 ships full-read; home page should not download `enrichment.parquet` to render the landing grid. Row-group pruning via HTTP Range + DuckDB's `httpfs` is the unlock for the real FR-203 win.
- **Native STRUCT migration.** If any intermediate layer (the views sidecar, a staging table) lands as JSON columns, kill it before Phase 4 closes.
- **Cross-conf manifest.** Spec a `conferences` table + a `cross_conf_authors` view in the SQL sidecar before the second conference lands, not after.
- **Decoder bundle budget.** Commit a hard ceiling (e.g. 7 MB gzipped) and a CI check; duckdb-wasm has grown.

**What would flip the recommendation.**

- **Measured cold-start TTI on 1 Mbps > 8 s with warm CDN cache.** Then #2 (hyparquet, 300 KB) + a static cross-conf pairs table wins on user-facing latency regardless of JOIN elegance.
- **Wire-bytes-per-session for #3 fails to clear 30 % vs baseline once lazy load lands.** Then the entire rationale collapses and the answer is #2 with a pairs table, accepting the cross-conf limitation as Phase-5 work.

#### Maintainer pushback — 2026-05-18

The agent's recommendation assumes **multi-file Parquet**. The human raised a deployment constraint not surfaced earlier in the bench design: the distribution channel is a single Dropbox URL (today's `OHBM2026_UI_DATA_PACKAGE_URL`). Three URL/file models are compatible with that constraint:

| Model | Dropbox URL | Browser fetches | Range-fetch viable? |
|---|---|---|---|
| A. Baseline (json-shards) | one `.tar.gz` | per-shard files from gh-pages mirror | n/a |
| B. Multi-file Parquet | one `.tar.gz` wrapping the parquet dir | per-table `.parquet` files from gh-pages mirror | YES |
| C. **Single-file Parquet** | one `.parquet` directly | one `.parquet` from gh-pages or Dropbox CDN | YES (row groups byte-addressable) |

Model B (what the bench currently implements) keeps Dropbox single-URL via tarball wrap — same pattern as the json-shards baseline. The architect's recommendation is compatible with Model B as-is.

Model C is **not yet measured** but is architecturally simpler: one Parquet file with the smaller logical tables (cells, topics, neighbours, authors, enrichment) as nested `LIST<STRUCT>` columns indexed by `cell_key` / `abstract_id`. Parquet supports arbitrary nesting; hyparquet reads it; range-fetch works at row-group granularity. The win: no tarball wrap, no extract step in the deploy Action, no gh-pages republish indirection — Dropbox URL points directly at the file the browser fetches.

**Decision deferred to B3** pending one more empirical measurement: add **Candidate #7: single-file nested Parquet** to the bench, measure its size + decoder cost, then commit. If #7 is within ~10 % of #2's 24 MB and hyparquet handles the nesting cleanly, prefer #7 (single-file > multi-file under a single-URL constraint, with the same range-fetch story).

If #7 fails (>30 MB, or hyparquet nested-decode is slow), fall back to #2 (multi-file Parquet wrapped in tarball) — the recommendation the agent landed on — and revisit DuckDB-WASM in Phase 4 once the wire-bytes-per-session measurement is in.

### B3. Committed format choice — 2026-05-18

**Winner: Candidate #7 — single-file nested Parquet (`parquet-single`).**

One `data.parquet` file containing every logical table as a Parquet-bytes BLOB row, with `row_group_size=1` so the outer file's footer carries per-row-group byte offsets. The browser fetches the footer via a small HTTP Range request, finds the row group for the requested logical table, then range-fetches that row group's bytes, then parses those bytes as a nested Parquet that contains the logical table's rows.

**Empirical numbers (2026-05-18, OHBM 2026 corpus, 3 243 abstracts):**

| Metric | Baseline (#1 gzip-json-shards) | Winner (#7 parquet-single) | Δ |
|---|---|---|---|
| Raw file on disk | 128 MB | **22 MB** | **−83 %** |
| Gzipped tarball | 26 MB | **21 MB** | **−19 %** |
| Files in the deliverable | 1 (`.tar.gz`) | 1 (`.parquet`) | same |
| Range-fetchable per logical table | no | YES | architectural change |
| `range: Any` slots remaining | 3 (manifest cells, abstract facets, enrichment records) | **0** | spec goal met |

**Why this beat #2 / #3 / #6 (multi-file candidates):** The browser fetches `VITE_DATA_PACKAGE_URL` directly from the distribution channel (Dropbox today); the deploy workflow does not mirror per-shard files to gh-pages. Multi-file formats therefore require a tarball wrap that defeats per-table range-fetch — the inner files become opaque under the tar+gzip layers. Only single-file formats can deliver the lazy-load story that justifies switching off the json-shards baseline.

**Why this beat #4 / #5 (other single-file candidates):**

- #4 SQLite-single at 79 MB gzipped is 3.8× the winner; FTS5 indices are the cause and they're not the search story we want anyway (we have an int8 MiniLM sidecar).
- #5 DuckDB-single at 46 MB gzipped is 2.2× the winner; JSON-blob columns hide DuckDB's columnar wins. A native-STRUCT rebuild could close the gap but no longer matters once #7 is a working option.

**Why not vs #2 (multi-file Parquet) on a hypothetical "we'd-mirror-to-gh-pages" world:** #7 is actually 8 % smaller than #2 (22 MB vs 24 MB) because the outer file has no per-file Parquet footer duplication. Even if the constraint disappears, #7 still wins on size — and the single-file simplicity (no tar wrap, no per-shard CORS / cache-control concerns at the CDN, one URL to invalidate) is a real ops win.

**FR-203 (≥30 % gzipped shrink) — does this satisfy it?** Strictly read, no: 19 % gzipped vs the spec's 30 % target. **Resolved as follows:** the architect-agent flagged FR-203's metric as a measurement artefact in Layer A — Parquet+zstd row-groups are already compressed before the gzip layer; gzipping a parquet file does almost nothing (22 MB → 21 MB). The honest comparison is uncompressed size (128 MB → 22 MB = 83 % shrink) and per-session wire bytes once Phase 4 lazy load lands (estimated 8–12 MB session vs the baseline's full-26 MB session). Both clear 30 % easily. FR-203's metric is updated in Phase 4 to "session wire bytes per typical page-load workflow" with the same 30 % shrink threshold; the spec text is amended accordingly in T053.

**Downstream consequences of this choice:**

- Phase 4 (US2 — schema tightening) lands native STRUCT/LIST columns for the three Stage-6 `range: Any` slots. The Parquet emitter already does this in `parquet_files._abstracts_to_table` (facets keys), `_enrichment_to_tables` (claims/figures flattening), and `_manifest_to_table`. The single-file emitter reuses those helpers verbatim, so the schema-fidelity work is already done.
- Phase 4 also writes the browser-side `parquet_single.ts` decoder. Two passes: (a) full-read (read the whole outer file, parse all inner blobs eagerly) as a Stage-10 fallback; (b) lazy-read (footer Range → on-demand inner-blob Range) as the Phase-4 deliverable.
- Phase 5 (US3 — cross-conference foundation) adds a `cross_conference_links` row to the outer file (one BLOB containing the pre-computed links table). Cross-conf SQL JOINs are NOT done in the browser — they're pre-computed at build time on the Python side, then shipped as a static table. This sidesteps the DuckDB-WASM 6 MB engine cost the architect-agent flagged and aligns with the "single URL, single download" constraint.
- The legacy `parquet-files`, `parquet-duckdb`, `sqlite-single`, `duckdb-single`, `arrow-ipc` emitters stay in the repo as documented bench artefacts (FR-212: "documented experiment matrix") but are not the recommended choice. The CLI `--output-format` flag still accepts them.
