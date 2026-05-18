/**
 * Stage-10 decoder dispatch.
 *
 * Picks the runtime decoder based on the deployed `manifest.format`
 * field. Until the Stage-10 bench (`specs/010-export-redesign/research.md`)
 * commits to a winning candidate, only `'gzip-json-shards'` resolves —
 * every other value throws. Phase-3 work (T025–T029) lands the candidate
 * decoders alongside this dispatch.
 *
 * The caller pattern:
 *
 *   const decoder = await getDecoder();
 *   const abstracts = await decoder.loadAbstracts();
 *
 * Stage-6 call-sites that import `loadAbstracts` from `$lib/shards`
 * directly still work — that module is the json-shards decoder under
 * its legacy name. The Stage-10 refactor (T018) moves it under this
 * namespace as `json_shards.ts`; `$lib/shards` becomes a thin
 * re-export shim so existing imports don't break mid-rework.
 */

import type { DataDecoder } from './decoder';
import { JsonShardsDecoder } from './json_shards';

let cachedDecoder: Promise<DataDecoder> | null = null;

/**
 * Returns the singleton decoder for this page session. The first call
 * triggers a manifest fetch (to read `manifest.format`); subsequent
 * calls re-use the same instance.
 */
export function getDecoder(): Promise<DataDecoder> {
	if (cachedDecoder !== null) return cachedDecoder;
	cachedDecoder = (async () => {
		// We construct the json-shards decoder first to read the manifest;
		// if the manifest names a different format we hand off. This works
		// because every candidate emitter writes a `manifest.json` (or
		// equivalent) at the same URL — the manifest is always JSON-
		// readable so the dispatch is bootstrappable without prior
		// knowledge of the format.
		const probe = new JsonShardsDecoder();
		const manifest = await probe.loadManifest();
		const format = (manifest as { format?: string } | null)?.format ?? 'gzip-json-shards';

		switch (format) {
			case 'gzip-json-shards':
				return probe;
			case 'parquet-files':
			case 'parquet-duckdb':
			case 'sqlite-single':
			case 'duckdb-single':
			case 'arrow-ipc':
				throw new Error(
					`Stage-10 candidate decoder for format=${format} is not yet implemented. ` +
						`It lands in Phase 3 (specs/010-export-redesign/tasks.md T025–T029).`
				);
			default:
				throw new Error(`Unknown manifest.format: ${format}`);
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
