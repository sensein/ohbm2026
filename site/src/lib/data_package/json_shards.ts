/**
 * Stage-6 baseline decoder, wrapped to implement the Stage-10
 * `DataDecoder` interface.
 *
 * Strategy: delegate every bulk loader to the existing module-level
 * functions in `$lib/shards` (the Stage-6 implementation). That keeps
 * the on-the-wire fetch behaviour, the tarball-parse logic, and the
 * 26-spec regression coverage entirely unchanged. The class is just
 * an interface adapter — no logic moves here.
 *
 * The per-record affordances (`loadAbstractByPosterId`,
 * `loadEnrichmentRecord`, `loadCrossConferenceLinks`) are implemented
 * here via fallback scans because the json-shards format doesn't
 * support point lookups. The winning Stage-10 decoder will override
 * with native efficient implementations.
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
import {
	loadAbstracts as legacyLoadAbstracts,
	loadAllNeighbors as legacyLoadAllNeighbors,
	loadAuthors as legacyLoadAuthors,
	loadCell as legacyLoadCell,
	loadEnrichment as legacyLoadEnrichment,
	loadManifest as legacyLoadManifest,
	loadMinilmVectors as legacyLoadMinilmVectors,
	loadNeighbors as legacyLoadNeighbors,
	loadTopics as legacyLoadTopics
} from '$lib/shards';
import type { CrossConferenceLink, DataDecoder } from './decoder';

export class JsonShardsDecoder implements DataDecoder {
	loadManifest(): Promise<Manifest | null> {
		return legacyLoadManifest();
	}

	loadAbstracts(): Promise<AbstractsShard | null> {
		return legacyLoadAbstracts();
	}

	loadAuthors(): Promise<AuthorsShard | null> {
		return legacyLoadAuthors();
	}

	loadCell(cellKey: string): Promise<CellShard | null> {
		return legacyLoadCell(cellKey);
	}

	loadTopics(cellKey: string, kind: string): Promise<TopicShard | null> {
		return legacyLoadTopics(cellKey, kind);
	}

	loadNeighbors(cellKey: string): Promise<NeighborsShard | null> {
		return legacyLoadNeighbors(cellKey);
	}

	loadAllNeighbors(): Promise<Map<string, NeighborsShard>> {
		return legacyLoadAllNeighbors();
	}

	loadEnrichment(): Promise<EnrichmentShard | null> {
		return legacyLoadEnrichment();
	}

	loadMinilmVectors(): Promise<{
		vectors: Uint8Array;
		shape: [number, number];
		abstractIds: number[];
	} | null> {
		return legacyLoadMinilmVectors();
	}

	// ----- per-record point lookups: fallback scans -------------------------

	async loadAbstractByPosterId(posterId: string): Promise<AbstractRecord | null> {
		const shard = await this.loadAbstracts();
		if (!shard) return null;
		return shard.abstracts.find((a) => a.poster_id === posterId) ?? null;
	}

	async loadEnrichmentRecord(
		abstractId: number
	): Promise<{ claims: unknown[]; figures: unknown[] } | null> {
		const shard = await this.loadEnrichment();
		if (!shard) return null;
		const rec = (shard.records as Record<string, { claims?: unknown[]; figures?: unknown[] } | undefined>)[
			String(abstractId)
		];
		if (!rec) return null;
		return { claims: rec.claims ?? [], figures: rec.figures ?? [] };
	}

	// ----- cross-conference (Stage-10 FR-208) -------------------------------
	// The json_shards baseline ships ZERO cross-conference linking — Stage-10
	// adds the affordance only once the bench commits to a format that can
	// produce it efficiently. For the OHBM-only deploy, returning [] is
	// the documented contract.

	async loadCrossConferenceLinks(_abstractId: number): Promise<CrossConferenceLink[]> {
		return [];
	}
}
