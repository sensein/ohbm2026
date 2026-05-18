/**
 * Stage-10 format-agnostic decoder interface.
 *
 * See `specs/010-export-redesign/contracts/decoder.md` for the full
 * latency / error-semantic / lazy-load contract. This file is the
 * single source of truth for the type signatures; every candidate
 * decoder under `site/src/lib/data_package/<format>.ts` implements it.
 *
 * Backward-compat note: the bulk loaders (`loadAbstracts`, `loadAuthors`,
 * `loadCell`, etc.) match the existing Stage-6 surface 1:1 so the
 * `getDecoder()` dispatch in `index.ts` can switch implementations
 * without any change to call-sites in `+page.svelte`, `+layout.svelte`,
 * `CartDrawer.svelte`, etc.
 *
 * Stage-10 introduces three per-record affordances that only the
 * winning post-bench decoder implements efficiently (Parquet
 * row-group point fetch, SQLite `WHERE id = ?`, DuckDB `SELECT`):
 *
 *   - `loadAbstractByPosterId(posterId)` — used by the
 *     `/ohbm2026/abstract/<poster_id>/` permalink route. The
 *     `json_shards` decoder implements it as `loadAbstracts().find(...)`
 *     fallback. The winning per-record-capable decoder uses a real
 *     point lookup.
 *
 *   - `loadEnrichmentRecord(abstractId)` — opened on detail-panel
 *     mount. `json_shards` returns `(await loadEnrichment())[abstractId]`;
 *     the winning decoder does a single-row read.
 *
 *   - `loadCrossConferenceLinks(abstractId)` — Stage-10's NEW
 *     cross-conference affordance (FR-208). Returns `[]` for the
 *     OHBM-only deploy; populated by a future second-conference build.
 */

import type {
	AbstractsShard,
	AbstractRecord,
	AuthorsShard,
	CellShard,
	EnrichmentShard,
	Manifest,
	NeighborsShard,
	TopicShard
} from '$lib/shards';

/**
 * Stage-10 NEW. One cross-conference link, e.g. OHBM-abstract ↔ PubMed-paper.
 * Empty list for the OHBM-only deploy. The placement (separate shard,
 * SQL JOIN view, embedded column) is decided by the bench's format
 * winner — `data-model.md` Layer 2 `<FILL POST-BENCH>`.
 */
export interface CrossConferenceLink {
	conf_a: string;
	id_a: number | string;
	conf_b: string;
	id_b: number | string;
	link_kind: 'embedding_neighbour' | 'claim_overlap' | 'citation';
	similarity: number;
	metadata?: Record<string, unknown>;
}

export interface DataDecoder {
	// ----- bulk loaders (Stage-6 surface, 1:1) ------------------------------

	loadManifest(): Promise<Manifest | null>;
	loadAbstracts(): Promise<AbstractsShard | null>;
	loadAuthors(): Promise<AuthorsShard | null>;
	loadCell(cellKey: string): Promise<CellShard | null>;
	loadTopics(cellKey: string, kind: string): Promise<TopicShard | null>;
	loadNeighbors(cellKey: string): Promise<NeighborsShard | null>;
	loadAllNeighbors(): Promise<Map<string, NeighborsShard>>;
	loadEnrichment(): Promise<EnrichmentShard | null>;
	loadMinilmVectors(): Promise<{
		vectors: Uint8Array;
		shape: [number, number];
		abstractIds: number[];
	} | null>;

	// ----- per-record point lookups (Stage-10 NEW) --------------------------
	// Default implementations under `json_shards.ts` scan the bulk shard.
	// The winning decoder overrides with a native point fetch.

	loadAbstractByPosterId(posterId: string): Promise<AbstractRecord | null>;
	loadEnrichmentRecord(
		abstractId: number
	): Promise<{ claims: unknown[]; figures: unknown[] } | null>;

	// ----- cross-conference linking (Stage-10 NEW — FR-208) -----------------

	loadCrossConferenceLinks(abstractId: number): Promise<CrossConferenceLink[]>;
}
