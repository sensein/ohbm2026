/**
 * Stage-10 winner: single-file nested Parquet (`parquet-single`).
 *
 * One `data.parquet` at the data-package URL. The file is structured
 * as a discriminated container: one row group per logical table, with
 * a `table_name` discriminator column and a `table_bytes` BLOB column
 * holding that table's own serialized Parquet bytes. `row_group_size=1`
 * means the outer file's footer carries explicit byte offsets for
 * each blob — the browser can fetch the footer, look up the row group
 * for a requested logical table, and issue a single HTTP Range request
 * for that blob, then decode it as a nested Parquet.
 *
 * Phase 3 (this pass): full-read the outer file once; cache the inner
 * tables in memory; serve subsequent loads from cache. This is the
 * "single-file equivalent of the Stage-6 tarball decoder" — same
 * one-network-round-trip cost as the baseline, just smaller (21 MB
 * gzipped vs 26 MB).
 *
 * Phase 4 (US2 — schema tightening pass): switch to lazy mode. Fetch
 * the Parquet footer via `Range: bytes=-16384`, parse it (hyparquet
 * does this via `parquetMetadataAsync`), look up each requested table's
 * row-group byte offset, then issue a per-table Range fetch. First
 * paint should drop to ~5 MB of wire bytes (manifest + abstracts +
 * the active cell), with the remainder fetched as the user navigates.
 *
 * The browser sees no schema difference vs the json-shards path: this
 * decoder repackages the inner Parquet rows into the same Stage-6
 * envelope shapes (`AbstractsShard`, `CellShard`, `NeighborsShard`,
 * etc.) that `loadAbstracts()` / `loadCell()` / `loadNeighbors()` have
 * been returning since Stage 6.
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

interface OuterRow {
	table_name: string;
	table_bytes: Uint8Array;
}

interface ManifestParquetRow {
	schema_version?: string;
	format?: string;
	manifest_json?: string;
}

async function fetchOuterRows(url: string): Promise<Map<string, Uint8Array>> {
	const file = await asyncBufferFromUrl({ url });
	const rows = (await parquetReadObjects({ file })) as OuterRow[];
	const out = new Map<string, Uint8Array>();
	for (const r of rows) {
		out.set(r.table_name, r.table_bytes);
	}
	return out;
}

async function decodeInnerParquet<T>(bytes: Uint8Array): Promise<T[]> {
	// hyparquet's asyncBuffer interface is byte-range-friendly. Wrap
	// the in-memory bytes as a synchronous slice; the cost of building
	// the buffer is paid once at decode time.
	const buffer = bytes.buffer.slice(
		bytes.byteOffset,
		bytes.byteOffset + bytes.byteLength
	) as ArrayBuffer;
	const file = {
		byteLength: buffer.byteLength,
		slice: async (start: number, end?: number) =>
			buffer.slice(start, end ?? buffer.byteLength)
	};
	return (await parquetReadObjects({ file })) as T[];
}

export class ParquetSingleDecoder implements DataDecoder {
	private outerCache: Promise<Map<string, Uint8Array> | null> | null = null;
	private innerCache = new Map<string, Promise<unknown[] | null>>();
	private manifestCache: Promise<Manifest | null> | null = null;

	private async getOuter(): Promise<Map<string, Uint8Array> | null> {
		if (this.outerCache !== null) return this.outerCache;
		const url = getDataPackageUrl();
		if (!url) return null;
		this.outerCache = (async () => {
			try {
				return await fetchOuterRows(url);
			} catch (err) {
				console.error('[ohbm2026] parquet_single: failed to read outer file', err);
				return null;
			}
		})();
		return this.outerCache;
	}

	private async getInnerRows<T>(tableName: string): Promise<T[] | null> {
		const cached = this.innerCache.get(tableName);
		if (cached) return (await cached) as T[] | null;
		const p = (async (): Promise<T[] | null> => {
			const outer = await this.getOuter();
			if (!outer) return null;
			const bytes = outer.get(tableName);
			if (!bytes) return null;
			try {
				return await decodeInnerParquet<T>(bytes);
			} catch (err) {
				console.error('[ohbm2026] parquet_single: failed to decode inner', tableName, err);
				return null;
			}
		})();
		this.innerCache.set(tableName, p as Promise<unknown[] | null>);
		return p;
	}

	loadManifest(): Promise<Manifest | null> {
		if (this.manifestCache !== null) return this.manifestCache;
		this.manifestCache = (async () => {
			const rows = await this.getInnerRows<ManifestParquetRow>('manifest');
			if (!rows || rows.length === 0) return null;
			const row = rows[0];
			if (!row.manifest_json) return null;
			try {
				return JSON.parse(row.manifest_json) as Manifest;
			} catch {
				return null;
			}
		})();
		return this.manifestCache;
	}

	async loadAbstracts(): Promise<AbstractsShard | null> {
		const [manifest, rows] = await Promise.all([
			this.loadManifest(),
			this.getInnerRows<AbstractRecord>('abstracts')
		]);
		if (!rows) return null;
		return {
			schema_version: 'abstracts.v2',
			build_info: (manifest?.build_info ?? {}) as AbstractsShard['build_info'],
			abstracts: rows
		};
	}

	async loadAuthors(): Promise<AuthorsShard | null> {
		const [manifest, rows] = await Promise.all([
			this.loadManifest(),
			this.getInnerRows<AuthorsShard['authors'][number]>('authors')
		]);
		if (!rows) return null;
		return {
			schema_version: 'authors.v2',
			build_info: (manifest?.build_info ?? {}) as AuthorsShard['build_info'],
			authors: rows
		};
	}

	async loadCell(cellKey: string): Promise<CellShard | null> {
		const [manifest, rows] = await Promise.all([
			this.loadManifest(),
			this.getInnerRows<CellShard['rows'][number]>(`cells:${cellKey}`)
		]);
		if (!rows) return null;
		return {
			schema_version: 'cells.v2',
			build_info: (manifest?.build_info ?? {}) as CellShard['build_info'],
			cell_key: cellKey,
			rows
		};
	}

	async loadTopics(cellKey: string, kind: string): Promise<TopicShard | null> {
		const [manifest, rows] = await Promise.all([
			this.loadManifest(),
			this.getInnerRows<TopicShard['topics'][number]>(`topics:${cellKey}_${kind}`)
		]);
		if (!rows) return null;
		return {
			schema_version: 'topics.v2',
			build_info: (manifest?.build_info ?? {}) as TopicShard['build_info'],
			cell_key: cellKey,
			kind,
			topics: rows
		};
	}

	async loadNeighbors(cellKey: string): Promise<NeighborsShard | null> {
		const [manifest, rows] = await Promise.all([
			this.loadManifest(),
			this.getInnerRows<{
				abstract_id: number;
				nearest_ids: number[];
				nearest_distances: number[];
				farthest_ids: number[];
				farthest_distances: number[];
			}>(`neighbors:${cellKey}`)
		]);
		if (!rows) return null;
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

	async loadEnrichment(): Promise<EnrichmentShard | null> {
		const [manifest, claims, figures] = await Promise.all([
			this.loadManifest(),
			this.getInnerRows<{
				abstract_id: number;
				claim_index: number;
				text?: string;
				source?: string;
				evidence?: string;
				evidence_eco_codes?: string[];
				confidence?: number;
			}>('enrichment_claims'),
			this.getInnerRows<{
				abstract_id: number;
				figure_index: number;
				[k: string]: unknown;
			}>('enrichment_figures')
		]);
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
	}

	async loadMinilmVectors(): Promise<{
		vectors: Uint8Array;
		shape: [number, number];
		abstractIds: number[];
	} | null> {
		const outer = await this.getOuter();
		if (!outer) return null;
		const bin = outer.get('search:minilm_vectors');
		const metaBytes = outer.get('search:minilm_vectors_meta');
		if (!bin || !metaBytes) return null;
		try {
			const sidecar = JSON.parse(new TextDecoder().decode(metaBytes)) as {
				shape?: [number, number];
				abstract_ids?: number[];
			};
			return {
				vectors: bin,
				shape: sidecar.shape ?? [0, 384],
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
		// Phase 5 will populate this via a `cross_conference_links` BLOB
		// in the outer file. OHBM-only deploy returns empty.
		return [];
	}
}
