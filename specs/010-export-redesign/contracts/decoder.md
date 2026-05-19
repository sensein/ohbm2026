# Runtime Decoder Contract

The SvelteKit UI consumes the exported data via a small, format-agnostic interface that lives at `site/src/lib/data_package/decoder.ts`. Every candidate format from the bench (Phase 0) implements the same interface — `index.ts` reads `manifest.format` and dispatches to the right loader. This file is the contract every implementer must satisfy.

The contract is **format-agnostic**. The bench's job is to find an underlying format that satisfies every signature here AT the performance budgets in FR-205 / SC-205 / SC-209.

## Interface

All functions live in `site/src/lib/data_package/decoder.ts`. All return `Promise<T | null>` — `null` ONLY when the underlying data package is unreachable (no `VITE_DATA_PACKAGE_URL`, CORS failure, network drop). Decoder errors that aren't network-related throw.

```ts
interface DataDecoder {
    /**
     * MUST resolve on the page's critical path; the home page CANNOT render
     * without this. Implementations SHOULD fetch this in <1 s on a 1 Mbps
     * link. The manifest is small (~10 KB today; SHOULD stay <50 KB even with
     * the post-rework affordances).
     */
    loadManifest(): Promise<Manifest | null>;

    /**
     * The full Abstract table — the home page's search grid + result count
     * are blocked on this. MAY use range-fetch + progressive hydration in
     * the post-rework world; the contract is that `loadAbstracts()` settles
     * into a callable accessor in <3 s on a 1 Mbps link (SC-205).
     *
     * Implementations are free to return partial results AND set an
     * `incomplete: true` flag on the returned shard for the UI to display
     * a "still loading" indicator. But the array MUST be enumerable as
     * soon as it's first awaited.
     */
    loadAbstracts(): Promise<AbstractsShard | null>;

    /**
     * O(1) lookup for the abstract permalink route (`/ohbm2026/abstract/<poster_id>/`).
     * The decoder MAY use a separate index (`AbstractIndex.parquet`,
     * SQLite `CREATE INDEX poster_id`, etc.) so this fetches only the one
     * row's bytes, not the whole `loadAbstracts()` payload. If no such
     * index exists, the decoder falls back to scanning `loadAbstracts()`
     * — which means it cannot resolve before that has settled.
     */
    loadAbstractByPosterId(posterId: string): Promise<AbstractRecord | null>;

    /** Authors table. */
    loadAuthors(): Promise<AuthorsShard | null>;

    /** Per-(model, input) cell shard. */
    loadCell(cellKey: string): Promise<CellShard | null>;

    /** Per-(model, input, kind) topic shard. */
    loadTopics(cellKey: string, kind: TopicKind): Promise<TopicShard | null>;

    /**
     * The 11 currently-loaded neighbours shards (one per cell). Returns a
     * Map indexed by cell_key. MUST be lazy: home page never reads
     * neighbours; loading is gated on the user opening the UMAP panel or a
     * detail page.
     */
    loadAllNeighbours(): Promise<Map<string, NeighbourShard> | null>;

    /**
     * Single-record enrichment lookup. Implementations SHOULD use a
     * format-native point lookup (Parquet row-group fetch, SQLite query,
     * DuckDB `SELECT ... WHERE id = ?`) rather than loading the whole
     * EnrichmentShard. Home page never reads enrichment; it loads on
     * detail-panel open.
     */
    loadEnrichmentRecord(abstractId: number): Promise<EnrichmentRecord | null>;

    /**
     * MiniLM int8 sidecar — the int8-quantised vectors the semantic-search
     * worker uses. May be a separate binary file, may be a column in the
     * chosen container; the decoder hides that from the worker.
     */
    loadMinilmVectors(): Promise<MinilmVectorsSidecar | null>;

    /**
     * Cross-conference link surface (NEW per FR-208). Returns the list of
     * cross-conference links FROM `(thisConference, abstractId)` TO any
     * other conference. Implementations under a query-engine format
     * (DuckDB, SQLite) run a JOIN; non-engine formats load a pre-computed
     * pair shard.
     */
    loadCrossConferenceLinks(abstractId: number): Promise<CrossConferenceLink[] | null>;
}
```

## Lazy-load contract (FR-205)

The decoder MUST satisfy the following ordering / latency constraints on a 1 Mbps throttled link:

| Function | Budget | Why |
|---|---|---|
| `loadManifest` | < 1 s after `fetch()` start | Blocks every other call; smallest payload. |
| `loadAbstracts` (first usable rows) | < 3 s after `fetch()` start | SC-205 threshold. |
| `loadAbstractByPosterId` (warm) | < 100 ms | Detail page navigation. After manifest+index are loaded. |
| `loadAuthors` | < 3 s after `fetch()` start | Used by the author-chip UI; gated on home being interactive. |
| `loadCell` | < 1 s per cell once requested | UMAP panel opens; user-perceived latency. |
| `loadTopics` | < 500 ms per (cell, kind) once requested | Cluster lens swap. |
| `loadAllNeighbours` | Lazy. Not measured against the home budget. | Detail-panel + UMAP only. |
| `loadEnrichmentRecord` (one) | < 500 ms once requested | Detail panel open. |
| `loadMinilmVectors` | < 5 s after manifest | Semantic search worker warms on idle; not on home critical path. |
| `loadCrossConferenceLinks` (one) | < 500 ms once requested | Detail panel "related across conferences" affordance. |

## Format dispatch

`site/src/lib/data_package/index.ts`:

```ts
export async function getDecoder(): Promise<DataDecoder> {
    const manifest = await fetchManifestHead();   // tiny range-fetch of just the manifest preamble
    switch (manifest.format) {
        case 'gzip-json-shards':    return new JsonShardsDecoder(manifest);
        case 'parquet-files':       return new ParquetFilesDecoder(manifest);
        case 'parquet-duckdb':      return new ParquetDuckDbDecoder(manifest);
        case 'sqlite-single-file':  return new SqliteSingleFileDecoder(manifest);
        case 'duckdb-single-file':  return new DuckDbSingleFileDecoder(manifest);
        case 'arrow-ipc':           return new ArrowIpcDecoder(manifest);
    }
    throw new Error(`Unknown manifest.format: ${manifest.format}`);
}
```

The `manifest.format` enum is the only place the format identifier is named in the runtime. Every other decoder consumer is format-agnostic.

## Error semantics

| Condition | Response |
|---|---|
| `VITE_DATA_PACKAGE_URL` unset | Every `load*()` returns `null`. UI renders the "data unavailable" placeholder. |
| Manifest fetch returns non-2xx | Every subsequent `load*()` returns `null`. Same placeholder. |
| Single shard fetch fails (range request 416, CORS, etc.) | That `load*()` returns `null`. Other shards keep working. The UI degrades to "this section unavailable". |
| Schema validation fails at decode time (e.g., Parquet column type mismatch) | The decoder throws — this is a bug, not a network issue, and we want a loud failure. |

## What the contract does NOT decide

- The on-disk byte layout (Layer 2 of `data-model.md`, locked post-bench).
- The compression algorithm (gzip / brotli / zstd / per-column dictionary / etc.).
- Whether `loadAbstracts()` returns ALL rows or a Cursor that range-fetches more on demand. The contract says "the array MUST be enumerable as soon as awaited"; whether the entries are eagerly loaded is the decoder's choice.
- The shape of the cross-conference link table on disk (Layer 2).
