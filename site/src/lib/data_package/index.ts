/**
 * Stage-10 decoder dispatch.
 *
 * Picks the runtime decoder by **sniffing the first bytes** of the
 * data-package URL — file extension is not load-bearing. This is the
 * mechanism that keeps the Dropbox URL stable across the
 * gzip-json-shards → parquet-single migration: the same URL can serve
 * either format, swap the bytes on Dropbox and the browser dispatches
 * to the right decoder on the next page load.
 *
 * Bytes-sniffed via a 4-byte HTTP Range request:
 *
 *   - `1f 8b ...`           → gzip-json-shards (gzipped tarball)
 *   - `PAR1` (50 41 52 31)  → parquet-single (Parquet magic)
 *   - anything else         → fall back to gzip-json-shards
 *
 * If the Range request fails (network error, mock test runs without a
 * URL), the dispatcher falls back to gzip-json-shards — the legacy
 * behaviour — so test-only paths and ungated dev environments keep
 * working.
 *
 * The caller pattern:
 *
 *   const decoder = await getDecoder();
 *   const abstracts = await decoder.loadAbstracts();
 *
 * Stage-6 call-sites that import `loadAbstracts` from `$lib/shards`
 * directly still work — that module is the json-shards decoder under
 * its legacy name.
 */

import type { DataDecoder } from './decoder';
import { JsonShardsDecoder } from './json_shards';
import { getDataPackageUrl } from './tarball';

const PARQUET_MAGIC = [0x50, 0x41, 0x52, 0x31] as const;
const GZIP_MAGIC = [0x1f, 0x8b] as const;

/**
 * Fetch the first 4 bytes of the data-package URL and decide which
 * decoder to construct. The build-time `VITE_DATA_FORMAT` env var
 * is honoured first (used by bench harnesses and unit tests); the
 * sniff fires only when no override is set.
 */
async function detectFormat(fetcher: typeof fetch = fetch): Promise<string> {
	const override = (import.meta as { env?: Record<string, string | undefined> }).env
		?.VITE_DATA_FORMAT;
	if (override) return override;

	const url = getDataPackageUrl();
	if (!url) return 'gzip-json-shards';

	try {
		// Range: bytes=0-3 → 4 bytes is enough for both magics. Dropbox
		// honours range requests on shared-link content. If the server
		// ignores Range (returns 200 with the full body) we still read
		// only the first 4 bytes from the response stream.
		const resp = await fetcher(url, { headers: { Range: 'bytes=0-3' } });
		if (!resp.ok && resp.status !== 206) return 'gzip-json-shards';
		const buf = new Uint8Array(await resp.arrayBuffer());
		if (
			buf.length >= 4 &&
			buf[0] === PARQUET_MAGIC[0] &&
			buf[1] === PARQUET_MAGIC[1] &&
			buf[2] === PARQUET_MAGIC[2] &&
			buf[3] === PARQUET_MAGIC[3]
		) {
			return 'parquet-single';
		}
		if (buf.length >= 2 && buf[0] === GZIP_MAGIC[0] && buf[1] === GZIP_MAGIC[1]) {
			return 'gzip-json-shards';
		}
		// Unknown magic — fall back to the legacy path. The legacy
		// decoder will surface a clean failure if the bytes really
		// aren't a tarball, and the user-facing error message is
		// recognisable.
		return 'gzip-json-shards';
	} catch (err) {
		console.warn('[ohbm2026] format sniff failed, falling back to gzip-json-shards', err);
		return 'gzip-json-shards';
	}
}

let cachedDecoder: Promise<DataDecoder> | null = null;

/**
 * Returns the singleton decoder for this page session. The first call
 * triggers a 4-byte HTTP Range sniff to identify the format;
 * subsequent calls re-use the same instance.
 */
export function getDecoder(): Promise<DataDecoder> {
	if (cachedDecoder !== null) return cachedDecoder;
	cachedDecoder = (async () => {
		const format = await detectFormat();
		switch (format) {
			case 'gzip-json-shards':
				return new JsonShardsDecoder();
			case 'parquet-single': {
				const { ParquetSingleDecoder } = await import('./parquet_single');
				return new ParquetSingleDecoder();
			}
			case 'parquet-files': {
				const { ParquetFilesDecoder } = await import('./parquet_files');
				return new ParquetFilesDecoder();
			}
			case 'parquet-duckdb':
			case 'sqlite-single':
			case 'duckdb-single':
			case 'arrow-ipc':
				throw new Error(
					`Stage-10 candidate ${format} is ruled out under the single-URL ` +
						`deploy constraint. Decision rationale in ` +
						`specs/010-export-redesign/research.md § B1.1 + B3.`
				);
			default:
				throw new Error(`Unknown data-package format: ${format}`);
		}
	})();
	return cachedDecoder;
}

/**
 * Test-only: clears the cached decoder. Used by Vitest unit tests to
 * isolate per-test decoder instances.
 */
export function resetDecoderCacheForTests(): void {
	cachedDecoder = null;
}

export type { DataDecoder, CrossConferenceLink } from './decoder';

// Re-export the legacy tarball helpers so pre-existing
// `import { ... } from '$lib/data_package'` call-sites keep working
// after the data_package.ts file moved into data_package/tarball.ts.
// New code SHOULD import from $lib/data_package/tarball directly.
export {
	getDataPackageUrl,
	loadDataPackage,
	resetDataPackageCacheForTests
} from './tarball';
