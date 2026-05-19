/**
 * Runtime data-package loader.
 *
 * The deployed site doesn't bundle any data. At runtime, the client
 * fetches the single `data.parquet` file from `VITE_DATA_PACKAGE_URL`
 * (a Dropbox / CDN URL), parses it via `hyparquet`, and returns a
 * `Map<path, JsonValue | Uint8Array>` whose keys are the legacy
 * shard paths (`data/manifest.json`, `data/cells/<key>.json`, ...).
 * UI consumers in `$lib/shards` keep their existing import surface
 * unchanged; the map shape is identical to the old tarball loader's
 * output so no Stage-6 component needed a refactor.
 *
 * The outer Parquet file has one row per logical table, with the
 * table's own Parquet bytes in a `table_bytes` BLOB column. We decode
 * the outer once, then decode each inner blob into rows and repack
 * them into the Stage-6 envelope shape the UI expects.
 */

import { parquetReadObjects } from 'hyparquet';
import { compressors } from 'hyparquet-compressors';

let packageCache: Promise<Map<string, unknown> | null> | null = null;

export function getDataPackageUrl(): string | null {
	const url = import.meta.env.VITE_DATA_PACKAGE_URL;
	if (!url) return null;
	// Dropbox shared links served via `www.dropbox.com` redirect (HTTP 302)
	// to `*.dl.dropboxusercontent.com`, but the redirect step itself lacks
	// CORS headers — browsers refuse the cross-origin fetch. Rewriting the
	// host to `dl.dropboxusercontent.com` skips the redirect and lands
	// directly on the content endpoint, which DOES send
	// `Access-Control-Allow-Origin: *` and serves raw bytes.
	return url
		.replace(/^https:\/\/www\.dropbox\.com\//, 'https://dl.dropboxusercontent.com/')
		.replace(/[?&]dl=0(\b|$)/, (m) => m.replace('dl=0', ''));
}

export function loadDataPackage(
	fetcher: typeof fetch = fetch
): Promise<Map<string, unknown> | null> {
	if (packageCache !== null) return packageCache;
	const url = getDataPackageUrl();
	if (!url) {
		packageCache = Promise.resolve(null);
		return packageCache;
	}
	packageCache = (async (): Promise<Map<string, unknown> | null> => {
		try {
			const response = await fetcher(url);
			if (!response.ok || !response.body) return null;
			const buffer = await response.arrayBuffer();
			return await parseParquetSingle(new Uint8Array(buffer));
		} catch (err) {
			console.error('[ohbm2026] failed to load data package:', err);
			return null;
		}
	})();
	return packageCache;
}

export function resetDataPackageCacheForTests(): void {
	packageCache = null;
}

interface OuterRow {
	// `table_name` is a pyarrow `string` column → hyparquet returns it as
	// a JS string regardless of the top-level `utf8` flag (the STRING
	// logical type forces decode).
	table_name: string;
	// `table_bytes` is a pyarrow `large_binary` column → with `utf8: false`
	// hyparquet returns it as Uint8Array; default utf8 decode would mangle
	// arbitrary binary, so we opt out.
	table_bytes: Uint8Array;
}

function bytesAsAsyncBuffer(bytes: Uint8Array) {
	const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
	return {
		byteLength: ab.byteLength,
		slice: async (start: number, end?: number) => ab.slice(start, end ?? ab.byteLength)
	};
}

async function decodeBlob(blob: Uint8Array): Promise<unknown[]> {
	// `utf8: true` (default) is what we want for the inner tables — string
	// columns come back as JS strings.
	return parquetReadObjects({ file: bytesAsAsyncBuffer(blob), compressors });
}

async function parseParquetSingle(bytes: Uint8Array): Promise<Map<string, unknown>> {
	const out = new Map<string, unknown>();
	// `utf8: false` on the outer read so `table_bytes` (large_binary)
	// stays as Uint8Array. `table_name` is a STRING logical type so it
	// comes back as a JS string regardless of this flag.
	const outerRows = (await parquetReadObjects({
		file: bytesAsAsyncBuffer(bytes),
		compressors,
		utf8: false
	})) as OuterRow[];

	// Manifest first — its build_info is glued onto every shard envelope.
	const manifestRow = outerRows.find((r) => r.table_name === 'manifest');
	let manifest: unknown = null;
	if (manifestRow) {
		const rows = (await decodeBlob(manifestRow.table_bytes)) as Array<{ manifest_json?: string }>;
		if (rows[0]?.manifest_json) {
			try {
				manifest = JSON.parse(rows[0].manifest_json);
			} catch {
				/* skip malformed manifest */
			}
		}
	}
	if (manifest) out.set('data/manifest.json', manifest);
	const buildInfo = (manifest as { build_info?: unknown } | null)?.build_info ?? {};

	for (const row of outerRows) {
		const { table_name: name, table_bytes: blob } = row;
		if (name === 'manifest') continue;
		// Enrichment tables are joined into one envelope below.
		if (name === 'enrichment_claims' || name === 'enrichment_figures') continue;
		// Binary blobs are stored without Parquet wrapping.
		if (name === 'search:minilm_vectors') {
			out.set('data/search/minilm_vectors.bin', blob);
			continue;
		}
		if (name === 'search:minilm_vectors_meta') {
			try {
				out.set('data/search/minilm_vectors.build_info.json', JSON.parse(new TextDecoder().decode(blob)));
			} catch {
				/* skip malformed sidecar */
			}
			continue;
		}

		const rows = await decodeBlob(blob);

		if (name === 'abstracts') {
			out.set('data/abstracts.json', {
				schema_version: 'abstracts.v2',
				build_info: buildInfo,
				abstracts: rows
			});
		} else if (name === 'authors') {
			out.set('data/authors.json', { schema_version: 'authors.v2', build_info: buildInfo, authors: rows });
		} else if (name.startsWith('cells:')) {
			const cellKey = name.slice('cells:'.length);
			out.set(`data/cells/${cellKey}.json`, {
				schema_version: 'cells.v2',
				build_info: buildInfo,
				cell_key: cellKey,
				rows
			});
		} else if (name.startsWith('topics:')) {
			const key = name.slice('topics:'.length);
			const sep = key.lastIndexOf('_');
			const cellKey = key.slice(0, sep);
			const kind = key.slice(sep + 1);
			out.set(`data/topics/${cellKey}_${kind}.json`, {
				schema_version: 'topics.v2',
				build_info: buildInfo,
				cell_key: cellKey,
				kind,
				topics: rows
			});
		} else if (name.startsWith('neighbors:')) {
			const cellKey = name.slice('neighbors:'.length);
			const parallel = rows as Array<{
				abstract_id: number;
				nearest_ids: number[];
				nearest_distances: number[];
				farthest_ids: number[];
				farthest_distances: number[];
			}>;
			out.set(`data/neighbors/${cellKey}.json`, {
				schema_version: 'neighbors.v2',
				build_info: buildInfo,
				cell_key: cellKey,
				k: parallel[0]?.nearest_ids.length ?? 0,
				abstract_ids: parallel.map((r) => r.abstract_id),
				nearest_ids: parallel.map((r) => r.nearest_ids),
				nearest_distances: parallel.map((r) => r.nearest_distances),
				farthest_ids: parallel.map((r) => r.farthest_ids),
				farthest_distances: parallel.map((r) => r.farthest_distances)
			});
		}
	}

	// Combine the two flattened enrichment tables back into the Stage-6
	// `{records: {str(id): {claims, figures}}}` envelope.
	const claimsRow = outerRows.find((r) => r.table_name === 'enrichment_claims');
	const figuresRow = outerRows.find((r) => r.table_name === 'enrichment_figures');
	const claims = claimsRow ? await decodeBlob(claimsRow.table_bytes) : [];
	const figures = figuresRow ? await decodeBlob(figuresRow.table_bytes) : [];
	const records: Record<string, { claims: unknown[]; figures: unknown[] }> = {};
	for (const c of claims as Array<{ abstract_id: number }>) {
		const k = String(c.abstract_id);
		(records[k] ??= { claims: [], figures: [] }).claims.push(c);
	}
	for (const f of figures as Array<{ abstract_id: number }>) {
		const k = String(f.abstract_id);
		(records[k] ??= { claims: [], figures: [] }).figures.push(f);
	}
	out.set('data/enrichment.json', {
		schema_version: 'enrichment.v2',
		build_info: buildInfo,
		ai_provenance: {},
		records
	});

	return out;
}
