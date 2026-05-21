# Phase 1 — Data Model: Stage 11.1

Three areas: (1) per-abstract PDF chunks + assembled book, (2) standby-slots table + per-abstract indices in the parquet, (3) state-key rename in Stage-1 provenance.

## Area 1 — Per-abstract PDF chunks + assembled book

### `AbstractPdfChunk` (in-memory + on-disk cache)

```python
@dataclass(frozen=True, slots=True)
class AbstractPdfChunk:
    poster_id: int               # the abstract identifier
    cache_key: str               # 16-hex-char digest (R1)
    cached_path: pathlib.Path    # data/cache/book/abstracts/<key>.pdf
    page_count: int              # populated by pikepdf after render
    cache_hit: bool              # True if we loaded from disk this run
    pandoc_stderr: str | None    # None on success; populated on failure
    index_entries: tuple[str, ...]  # `\index{Lastname, F.}` markers
                                    # hoisted from the chunk for pass 2
```

Cached PDF lives at `data/cache/book/abstracts/<key>.pdf`. Side-loaded sidecar at `<key>.json` carries the `page_count` + `index_entries` so a cache hit doesn't need to re-open the PDF.

### `PerAbstractFailure`

```python
@dataclass(frozen=True, slots=True)
class PerAbstractFailure:
    poster_id: int
    cache_key: str               # the key we tried to populate
    pandoc_exit_code: int
    stderr_tail: str             # last 2 KB of stderr (capped)
    failed_at: str               # ISO-8601 UTC
```

Aggregated in `provenance.failed_abstracts[]`. The build summary prints `N abstract(s) failed — details in <output>/provenance.json` and exits 0 (failed-abstract isolation is intentional, not a build failure).

### `AssembledBook` (orchestrator state)

```python
@dataclass(frozen=True, slots=True)
class AssembledBook:
    chunks: tuple[AbstractPdfChunk, ...]   # sort-order; failures already
                                           # filtered out
    chunk_offsets: tuple[tuple[int, int], ...]  # (poster_id, start_page)
                                                # measured during pass 1
    front_matter_pages: int                # how many pages the title +
                                           # TOC chunk consumed
    draft_path: pathlib.Path               # tmp/draft.pdf after pass 1
    final_path: pathlib.Path               # data/outputs/book/.../book.pdf
                                           # after pass 2
    cache_hit_count: int
    cache_miss_count: int
    failures: tuple[PerAbstractFailure, ...]
    assembly_time_seconds: float
```

### Provenance schema delta (v1 → v2)

`provenance.json` for `--format pdf` (or `--format all`) gains:

```json
{
  ...existing fields...,
  "cache_hit_count": 3120,
  "cache_miss_count": 122,
  "failed_abstracts": [
    {"poster_id": 1234, "cache_key": "abc...", "pandoc_exit_code": 43, "stderr_tail": "...", "failed_at": "2026-05-20T15:42:11Z"}
  ],
  "assembly_time_seconds": 47.2,
  "pdf_pipeline_version": "stage-11.1"
}
```

The legacy `xelatex_version` field is renamed `pdf_engine_version` and carries the engine name + version line.

### Cache invalidation rules

The cache is invalidated automatically (key changes) when ANY of:

- abstract's markdown body changes
- pandoc binary version changes
- LaTeX engine (xelatex or tectonic) version changes
- `header-includes.tex` / `header-includes-tufte.tex` content changes
- style flag changes (`plain` ↔ `tufte`)

Manual invalidation: operator deletes `data/cache/book/abstracts/` (or specific `<key>.pdf` files).

## Area 2 — Standby_slots table

### Parquet schema v2 deltas (vs v1)

**Removed**: `abstracts.poster_standby` STRUCT column (was `{first: TIMESTAMP, second: TIMESTAMP}`).

**Added**:
- `abstracts.standby_first_index: INT8` (nullable; references `standby_slots.slot_index`)
- `abstracts.standby_second_index: INT8` (nullable)
- New top-level table `standby_slots`:

```text
standby_slots
├── slot_index: INT8       primary key, 0..N-1, chronological by start_utc
├── start_utc: TIMESTAMP[ms, UTC]    inclusive
├── end_utc: TIMESTAMP[ms, UTC]      exclusive
└── display_label: VARCHAR          pre-rendered Paris-time label
                                    e.g. "Day 1 (Mon Jun 15) · 13:45-14:45"
```

Manifest's `schema_version` bumps from `parquet-single.v1` → `parquet-single.v2`. `build_info.format` adds a `schema_version` field (was implicit).

### In-browser decoder dispatch

`site/src/lib/data_package/loader.ts` reads `manifest.schema_version`:

- `parquet-single.v1` → existing path: parse `poster_standby` STRUCT, no `standby_slots` shard. UI calls into `standby.ts` with the timestamp pair (legacy code path).
- `parquet-single.v2` → new path: read `standby_first_index` + `standby_second_index` on abstracts; load `standby_slots` shard; UI calls into `standby.ts` with `(record, slotTable) → SlotMeta`.

Both paths converge at a shared `getStandbyForPoster(record) → {first: SlotMeta|null, second: SlotMeta|null}` so downstream components don't see the schema difference. The `Intl.DateTimeFormat` memoisation in `standby.ts` becomes dead code under v2 (slot metadata is already pre-rendered) — it stays during the migration window for v1 fallback.

### Slot derivation policy

The poster_id → slot_index map is derived once per build from the FINAL CSV:

1. Parse every distinct `First Stand-by Time` + `Second Stand-by Time` string.
2. Sort by ISO start datetime ascending.
3. Assign `slot_index` = position in sorted list (0-based).
4. For each accepted poster, look up its first + second labels in the map → emit INT8 indices.

Posters in the corpus but absent from the CSV (the 91 orphans from earlier audits) get nulls.

## Area 3 — State-key rename

### Stage 1 provenance schema delta

**Before** (legacy):
```json
{
  "state_key": "f0c51e80dc0e",
  ...
}
```

**After** (current):
```json
{
  "fetch_state_key": "f0c51e80dc0e",
  ...
}
```

### Reader compatibility helper

New shared helper in `src/ohbm2026/fetch/artifacts.py`:

```python
def read_fetch_state_key(provenance_doc: Mapping[str, Any]) -> str:
    """Read Stage-1's state-key from a provenance doc, accepting both
    the legacy 'state_key' and the new 'fetch_state_key' field names.
    Logs a one-line deprecation hint when the legacy name is used so
    future cleanups can grep for the hint to find all touch points.
    """
    if "fetch_state_key" in provenance_doc:
        return str(provenance_doc["fetch_state_key"])
    if "state_key" in provenance_doc:
        import warnings
        warnings.warn(
            "deprecated: Stage 1 provenance uses 'state_key'; "
            "expect 'fetch_state_key' in future fetches. See "
            "specs/012-stage11-followups/research.md R6.",
            DeprecationWarning,
            stacklevel=2,
        )
        return str(provenance_doc["state_key"])
    raise KeyError("no fetch state-key found in provenance doc")
```

### Touch-point inventory

The rename touches:
- `src/ohbm2026/fetch/artifacts.py` (provenance emitter)
- `src/ohbm2026/fetch/stage.py` (checkpoint emitter)
- `src/ohbm2026/assets.py` (refresh-assets reader)
- `src/ohbm2026/enrich_stage.py` (cache-key derivation reader)
- `src/ohbm2026/embed/stage.py` (resume-from-checkpoint reader)
- `scripts/build_ui_data.py` (state-key discovery)
- `CLAUDE.md`, `README.md`, `docs/reproducibility-vision.md`, every `specs/*/plan.md` that mentions Stage 1's `state_key` (~15 files)
- Tests under `tests/test_fetch_*.py` (assertions on emitted provenance fields)

## Validation rules

- `AbstractPdfChunk.cached_path` MUST exist on disk when the chunk is constructed from a cache hit; the constructor raises if it doesn't.
- `AssembledBook.chunks` MUST be in the sort order requested by `--sort`; chunk_offsets list is parallel.
- `standby_slots.slot_index` values MUST be unique + dense (0..N-1, no gaps).
- `abstracts.standby_first_index` and `standby_second_index` MUST reference rows that exist in `standby_slots` (FK-equivalent invariant checked at builder time, surfaced as `Stage6BuildError` if violated).
- `provenance.failed_abstracts[].poster_id` MUST NOT collide with any `provenance.included_poster_ids` (the assembled book includes one set, the failures the complement).
