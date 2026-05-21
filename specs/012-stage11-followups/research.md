# Phase 0 — Research: Stage 11.1

Six decisions with Decision / Rationale / Alternatives entries.

## R1 — Cache-key derivation

**Decision**: `sha256(md_body || pandoc_version || engine_version || header_includes_hash || style).hexdigest()[:16]` per abstract. The components are concatenated with NUL separators to avoid boundary ambiguity.

- `md_body` — the abstract's emit-time markdown (output of `html_to_md` + per-abstract template wrapping), bytes UTF-8.
- `pandoc_version` — the first line of `pandoc --version`, captured once at build start.
- `engine_version` — the first line of `xelatex --version` (or `tectonic --version`), captured once at build start.
- `header_includes_hash` — sha256 of the active `header-includes*.tex` (varies by style).
- `style` — string literal (`plain` / `tufte`).

Cached file lands at `data/cache/book/abstracts/<key>.pdf`. Misses trigger a fresh pandoc invocation; hits load from disk + skip pandoc.

**Rationale**: per CA-007, cache invalidation MUST be content-driven, not allow-listed. Discovering the toolchain versions at runtime means any pandoc/Tectonic upgrade automatically invalidates the cache. The 16-char prefix gives a 2^64 keyspace — collisions are astronomically unlikely at the 3,242-abstract scale.

**Alternatives considered**:
- *Hash only md_body*: rejected — engine upgrades would silently serve stale rendered output (subtle font / layout drift).
- *Use mtime + content size*: rejected — mtime fingerprints can match across legit content changes.
- *Per-abstract cache directory keyed by poster_id*: rejected — would prevent reuse across a state-key change that touches non-content metadata.

## R2 — Parallelism

**Decision**: `joblib.Parallel(n_jobs=args.workers, backend="loky", verbose=10)`. Default `args.workers = -1` (all available cores).

**Rationale**: matches Stage 4's existing pattern (`analyze_stage.py` uses joblib + loky for the embedding-bundle parallel sweep). `loky` is a `multiprocessing.Pool` variant that handles subprocess lifecycle robustly across macOS (default `spawn`) and Linux (`fork`). Each per-abstract task is a self-contained pandoc subprocess invocation; no shared state, no GIL contention.

**Alternatives considered**:
- *`asyncio.gather` + `asyncio.subprocess`*: would give event-loop overhead for what is fundamentally a CPU-bound subprocess pool. joblib is the right shape.
- *`concurrent.futures.ThreadPoolExecutor`*: subprocesses don't benefit from threads; joblib avoids the GIL pitfall.
- *Manual `multiprocessing.Pool`*: doable but loses joblib's progress bar + retry-on-pickle-failure guards.

## R3 — Two-pass assembly mechanism

**Decision**: the assembler runs in TWO sequential passes:

**Pass 1 — chunk concatenation + page-offset measurement**:
1. Render the front matter (title page + TOC) as its own pandoc invocation → `front_matter.pdf`.
2. Concatenate `front_matter.pdf` + every per-abstract `<key>.pdf` (in sort order) into `draft.pdf` via `pikepdf.Pdf.new()` + `pdf.pages.extend(...)`.
3. As each chunk is appended, record `chunk_offset = running_page_count` and append `(poster_id, chunk_offset)` to a list. The first per-abstract chunk's `chunk_offset` = number of pages in front matter.

**Pass 2 — index appendix**:
1. Generate a stub markdown that contains `\setcounter{page}{<total_draft_pages + 1>}` + every author's `\index{Lastname, F.}` entry hoisted from the per-abstract chunks + `\printindex`.
2. To make `\index{...}` markers reference the right page, the stub uses LaTeX `\immediate\write` to a `.idx` file that already encodes the per-chunk page offsets — bypassing makeindex's normal sequential-pagination assumption.
3. Run pandoc against the stub → `index_appendix.pdf` (with `\printindex` rendering page numbers from the pre-computed `.idx`).
4. Concatenate `index_appendix.pdf` onto `draft.pdf` → final `book.pdf`.

**Rationale**: this is the standard "split LaTeX makeindex into a two-pass external job" pattern. The first pass gets us the per-chunk offsets we couldn't know upfront; the second pass uses LaTeX's normal `\index`/`\printindex` machinery with hand-rolled page numbers. No new LaTeX packages introduced.

**Alternatives considered**:
- *Three-pass with `latexmk -pdflatex`*: requires a different engine and rebuild of the whole document twice; defeats the cache.
- *Hyperlink-only "name index" with no page numbers*: rejected at clarification (Option B in Q2) — printed book needs page numbers.
- *Per-chunk-local indices*: would produce N small indices instead of one global, useless for navigation.

## R4 — Standby_slots table shape

**Decision**: new top-level parquet table named `standby_slots` with one row per distinct program window:

```
slot_index     INT8       primary key (0..N-1)
start_utc      TIMESTAMP[ms, UTC]    inclusive start
end_utc        TIMESTAMP[ms, UTC]    exclusive end
display_label  VARCHAR    e.g. "Day 1 (Mon Jun 15) · 13:45-14:45"
```

Each abstract carries two nullable INT8 columns referencing this table: `standby_first_index`, `standby_second_index`. Null when the abstract has no standby info.

Row ordering in `standby_slots` is **chronological by `start_utc` ascending**, so `slot_index` IS the chronological position (no separate sort key needed). For OHBM 2026 this means `slot_index=0` is `Mon Jun 15 13:45`, `slot_index=7` is `Thu Jun 18 14:45`.

**Rationale**: INT8 fits ≤127 distinct slots — way more than any conference will have. INT8 columns dict-encode trivially to constant bytes; with 3,240 rows × 2 indices, the parquet column is ~6 KB. The display label is pre-rendered in Paris time so the UI doesn't need any `Intl.DateTimeFormat` at facet-recompute time.

**Alternatives considered**:
- *Embed slot label inline per abstract* (no separate table): rejected — duplicates 3,240 × ~40-byte labels = 130 KB of redundant data, defeats the schema-cleanup goal.
- *INT16 indices*: same dict-encoded final size as INT8; INT8 is honest about the range.
- *String key (`"day-1-1345"`) instead of integer*: harder to sort, larger, no win.

## R5 — Standby schema migration

**Decision**: bump the parquet manifest's `schema_version` from `parquet-single.v1` → `parquet-single.v2`. The in-browser decoder (`site/src/lib/data_package/loader.ts`) branches on the version:

- `v1` (legacy): read `poster_standby` STRUCT, lookup-table absent.
- `v2` (current): read `standby_first_index` + `standby_second_index` + `standby_slots` shard.

Both branches present the same `standby` shape to UI consumers (a function `getStandbyForPoster(record) → {first: SlotMeta|null, second: SlotMeta|null}`). Components downstream don't see the schema difference.

After the next prod deploy with v2 settles for one cycle (≥ 24 hours of green prod-e2e), the v1 acceptance branch can be removed in a future housekeeping commit — tracked as a comment in `loader.ts`.

**Rationale**: zero-downtime migration. The cached parquet on Dropbox stays at v1 until the operator drag-replaces with the new v2 build; the deployed site code reads both shapes so neither order (deploy code first / data first) breaks the live site.

**Alternatives considered**:
- *Schema change without version bump*: breaks every browser that has the v1 parquet cached. Not acceptable.
- *Separate parquet file per version*: doubles the storage + breaks the magic-byte-sniff dispatch.
- *Hard cutover with downtime announcement*: avoidable.

## R6 — State-key rename strategy

**Decision**: Stage 1 (`fetch_stage.py` + `artifacts.py`) renames its output field from `state_key` to `fetch_state_key` in all new provenance + checkpoint files. Stage 6's `corpus_state_key` is unchanged.

Reader compatibility: every loader of legacy Stage 1 artefacts (`assets.py`, the cache key derivation in Stage 2, etc.) accepts BOTH names via a small helper `read_state_key(doc) → str` that falls through to the legacy name. The helper logs a one-line deprecation hint when it falls back, so a future cleanup can grep for the hint to find all legacy-touch points.

The CLAUDE.md + README + `docs/reproducibility-vision.md` + every plan doc that mentions Stage 1's `state_key` gets updated in the same PR.

**Rationale**: avoids a flag-day rename that would invalidate every cached checkpoint on disk. The dual-acceptance helper is ~15 lines and gives us a clean migration window.

**Alternatives considered**:
- *Flag-day rename*: would invalidate every operator's local checkpoint files; forces a re-fetch for users who have stale state-key-named artefacts.
- *Rename Stage 6's field instead*: rejected — Stage 6's `corpus_state_key` is the more recently introduced + more descriptive name; Stage 1's `state_key` is the legacy that should align.
- *Add an alias without renaming*: leaves both names live forever; the confusion stays.
