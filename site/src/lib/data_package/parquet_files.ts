/**
 * Stage-10 candidate #2 decoder: multi-file Parquet via `hyparquet`.
 *
 * Strategy for this pass: full-read each Parquet file via
 * `asyncBufferFromUrl` + `parquetReadObjects`. The hyparquet library
 * does support row-range fetches via HTTP `Range:` headers (which is
 * the architectural win that justifies this candidate), but lazy
 * loading would require refactoring the UI's `loadAbstracts() →
 * AbstractRecord[]` consumers to handle partial arrays. That's a
 * Phase-4-after-format-commitment scope; this decoder lands the
 * functional substrate so the bench can measure end-to-end.
 *
 * The "session bytes" win for Parquet vs gzip-json-shards in this
 * pass = the byte-size difference between the two formats (24 MB vs
 * 26 MB gzipped). The future range-fetch lazy-load reduces session
 * bytes by another order of magnitude when it lands.
 */

import { asyncBufferFromUrl, parquetReadObjects } from 'hyparquet';
import type {
	AbstractRecord,
	AbstractsShard,
	AuthorsShard,
	CellShard,
	EnrichmentShard,
	Manifest,
	NeighborsShard,
	TopicShard
} from '$lib/shards';
import type { CrossConferenceLink, DataDecoder } from './decoder';
import { getDataPackageUrl } from './tarball';

function dataRoot(): string | null {
	const url = getDataPackageUrl();
	if (!url) return null;
	// Parquet emits a directory of files; the env var either points at the
	// directory root OR at a single file inside it (manifest.parquet). We
	// strip the filename to get the root the other shard URLs are relative to.
	if (url.endsWith('.parquet') || url.endsWith('.tar.gz')) {
		return url.replace(/\/[^/]+$/, '/');
	}
	return url.endsWith('/') ? url : url + '/';
}

async function readParquet<T>(relativePath: string): Promise<T[] | null> {
	const root = dataRoot();
	if (!root) return null;
	try {
		const file = await asyncBufferFromUrl({ url: root + relativePath });
		// `parquetReadObjects` returns an array of row objects; rejects on a
		// non-Parquet response.
		return (await parquetReadObjects({ file })) as T[];
	} catch (err) {
		console.error('[ohbm2026] parquet_files: failed to read', relativePath, err);
		return null;
	}
}

interface ManifestParquetRow {
	schema_version?: string;
	format?: string;
	manifest_json?: string;
}

export class ParquetFilesDecoder implements DataDecoder {
	private manifestCache: Promise<Manifest | null> | null = null;
	private abstractsCache: Promise<AbstractsShard | null> | null = null;
	private authorsCache: Promise<AuthorsShard | null> | null = null;
	private enrichmentCache: Promise<EnrichmentShard | null> | null = null;
	private cellCache = new Map<string, Promise<CellShard | null>>();
	private topicCache = new Map<string, Promise<TopicShard | null>>();
	private neighbourCache = new Map<string, Promise<NeighborsShard | null>>();

	loadManifest(): Promise<Manifest | null> {
		if (this.manifestCache !== null) return this.manifestCache;
		this.manifestCache = (async () => {
			const rows = await readParquet<ManifestParquetRow>('manifest.parquet');
			if (!rows || rows.length === 0) return null;
			const row = rows[0];
			// The emitter packed the manifest as a JSON-string column to
			// keep the Parquet schema flat. We unpack it client-side and
			// surface the same Manifest shape the json-shards decoder
			// returns, so the UI sees no difference.
			if (!row.manifest_json) return null;
			try {
				return JSON.parse(row.manifest_json) as Manifest;
			} catch {
				return null;
			}
		})();
		return this.manifestCache;
	}

	loadAbstracts(): Promise<AbstractsShard | null> {
		if (this.abstractsCache !== null) return this.abstractsCache;
		this.abstractsCache = (async () => {
			const [manifest, rows] = await Promise.all([
				this.loadManifest(),
				readParquet<AbstractRecord>('abstracts.parquet')
			]);
			if (!rows) return null;
			return {
				schema_version: 'abstracts.v2',
				build_info: (manifest?.build_info ?? {}) as AbstractsShard['build_info'],
				abstracts: rows
			};
		})();
		return this.abstractsCache;
	}

	loadAuthors(): Promise<AuthorsShard | null> {
		if (this.authorsCache !== null) return this.authorsCache;
		this.authorsCache = (async () => {
			const [manifest, rows] = await Promise.all([
				this.loadManifest(),
				readParquet<AuthorsShard['authors'][number]>('authors.parquet')
			]);
			if (!rows) return null;
			return {
				schema_version: 'authors.v2',
				build_info: (manifest?.build_info ?? {}) as AuthorsShard['build_info'],
				authors: rows
			};
		})();
		return this.authorsCache;
	}

	loadCell(cellKey: string): Promise<CellShard | null> {
		const cached = this.cellCache.get(cellKey);
		if (cached) return cached;
		const p = (async (): Promise<CellShard | null> => {
			const [manifest, rows] = await Promise.all([
				this.loadManifest(),
				readParquet<CellShard['rows'][number]>(`cells/${cellKey}.parquet`)
			]);
			if (!rows) return null;
			return {
				schema_version: 'cells.v2',
				build_info: (manifest?.build_info ?? {}) as CellShard['build_info'],
				cell_key: cellKey,
				rows
			};
		})();
		this.cellCache.set(cellKey, p);
		return p;
	}

	loadTopics(cellKey: string, kind: string): Promise<TopicShard | null> {
		const key = `${cellKey}::${kind}`;
		const cached = this.topicCache.get(key);
		if (cached) return cached;
		const p = (async (): Promise<TopicShard | null> => {
			const [manifest, rows] = await Promise.all([
				this.loadManifest(),
				readParquet<TopicShard['topics'][number]>(`topics/${cellKey}_${kind}.parquet`)
			]);
			if (!rows) return null;
			return {
				schema_version: 'topics.v2',
				build_info: (manifest?.build_info ?? {}) as TopicShard['build_info'],
				cell_key: cellKey,
				kind,
				topics: rows
			};
		})();
		this.topicCache.set(key, p);
		return p;
	}

	loadNeighbors(cellKey: string): Promise<NeighborsShard | null> {
		const cached = this.neighbourCache.get(cellKey);
		if (cached) return cached;
		const p = (async (): Promise<NeighborsShard | null> => {
			const [manifest, rows] = await Promise.all([
				this.loadManifest(),
				readParquet<{
					abstract_id: number;
					nearest_ids: number[];
					nearest_distances: number[];
					farthest_ids: number[];
					farthest_distances: number[];
				}>(`neighbors/${cellKey}.parquet`)
			]);
			if (!rows) return null;
			// Repack per-row tuples into the Stage-6 parallel-array shape
			// the UI expects.
			return {
				schema_version: 'neighbors.v2',
				build_info: (manifest?.build_info ?? {}) as NeighborsShard['build_info'],
				cell_key: cellKey,
				k: rows[0]?.nearest_ids.length ?? 0,
				abstract_ids: rows.map((r) => r.abstract_id),
				nearest_ids: rows.map((r) => r.nearest_ids),
				nearest_distances: rows.map((r) => r.nearest_distances),
				farthest_ids: rows.map((r) => r.farthest_ids),
				farthest_distances: rows.map((r) => r.farthest_distances)
			};
		})();
		this.neighbourCache.set(cellKey, p);
		return p;
	}

	async loadAllNeighbors(): Promise<Map<string, NeighborsShard>> {
		const manifest = await this.loadManifest();
		if (!manifest) return new Map();
		const keys = manifest.cells?.map((c) => c.cell_key ?? '') ?? [];
		const out = new Map<string, NeighborsShard>();
		await Promise.all(
			keys.map(async (cellKey) => {
				if (!cellKey) return;
				const shard = await this.loadNeighbors(cellKey);
				if (shard) out.set(cellKey, shard);
			})
		);
		return out;
	}

	loadEnrichment(): Promise<EnrichmentShard | null> {
		if (this.enrichmentCache !== null) return this.enrichmentCache;
		this.enrichmentCache = (async (): Promise<EnrichmentShard | null> => {
			const [manifest, claims, figures] = await Promise.all([
				this.loadManifest(),
				readParquet<{
					abstract_id: number;
					claim_index: number;
					text?: string;
					source?: string;
					evidence?: string;
					evidence_eco_codes?: string[];
					confidence?: number;
				}>('enrichment_claims.parquet'),
				readParquet<{
					abstract_id: number;
					figure_index: number;
					[k: string]: unknown;
				}>('enrichment_figures.parquet')
			]);
			// Reconstruct the Stage-6 `{str(id): {claims, figures}}` shape.
			const records: Record<string, { claims: unknown[]; figures: unknown[] }> = {};
			for (const c of claims ?? []) {
				const key = String(c.abstract_id);
				(records[key] ??= { claims: [], figures: [] }).claims.push(c);
			}
			for (const f of figures ?? []) {
				const key = String(f.abstract_id);
				(records[key] ??= { claims: [], figures: [] }).figures.push(f);
			}
			return {
				schema_version: 'enrichment.v2',
				build_info: (manifest?.build_info ?? {}) as EnrichmentShard['build_info'],
				ai_provenance: {} as EnrichmentShard['ai_provenance'],
				records: records as unknown as EnrichmentShard['records']
			};
		})();
		return this.enrichmentCache;
	}

	async loadMinilmVectors(): Promise<{
		vectors: Uint8Array;
		shape: [number, number];
		abstractIds: number[];
	} | null> {
		const root = dataRoot();
		if (!root) return null;
		try {
			const [binResp, sidecarResp] = await Promise.all([
				fetch(root + 'search/minilm_vectors.bin'),
				fetch(root + 'search/minilm_vectors.build_info.json')
			]);
			if (!binResp.ok || !sidecarResp.ok) return null;
			const bin = new Uint8Array(await binResp.arrayBuffer());
			const sidecar = await sidecarResp.json();
			return {
				vectors: bin,
				shape: sidecar.shape as [number, number],
				abstractIds: sidecar.abstract_ids ?? []
			};
		} catch {
			return null;
		}
	}

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
		const rec = (
			shard.records as Record<string, { claims?: unknown[]; figures?: unknown[] } | undefined>
		)[String(abstractId)];
		if (!rec) return null;
		return { claims: rec.claims ?? [], figures: rec.figures ?? [] };
	}

	async loadCrossConferenceLinks(_abstractId: number): Promise<CrossConferenceLink[]> {
		// Empty for the OHBM-only deploy. Future work: range-fetch
		// `cross_conference_links.parquet` filtered by `id_a = _abstractId`.
		return [];
	}
}
