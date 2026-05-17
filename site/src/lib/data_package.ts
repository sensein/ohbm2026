/**
 * Runtime data-package fetcher.
 *
 * The deployed site no longer bundles any data. Instead the client fetches
 * a single tarball from `VITE_DATA_PACKAGE_URL` (a Dropbox / CDN URL), uses
 * the browser's native `DecompressionStream('gzip')` to ungzip, parses the
 * tar entries in memory, and returns a `Map<path, JsonValue>` keyed by the
 * tarball-relative path (e.g. `data/manifest.json`,
 * `data/cells/voyage_abstract.json`).
 *
 * No tar/gzip npm dependency — `DecompressionStream` is available in all
 * modern browsers, and the tar format's a 512-byte-aligned stream that
 * fits in ~50 lines of straightforward TypeScript.
 */

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
			const decompressed = response.body.pipeThrough(new DecompressionStream('gzip'));
			const buffer = await new Response(decompressed).arrayBuffer();
			return parseTar(new Uint8Array(buffer));
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

function parseTar(bytes: Uint8Array): Map<string, unknown> {
	const out = new Map<string, unknown>();
	const decoder = new TextDecoder();
	let offset = 0;
	while (offset + 512 <= bytes.length) {
		// Two consecutive 512-byte zero blocks = end of archive.
		if (isZeroBlock(bytes, offset)) {
			offset += 512;
			if (offset + 512 <= bytes.length && isZeroBlock(bytes, offset)) break;
			continue;
		}
		const name = decoder.decode(bytes.subarray(offset, offset + 100)).split('\0')[0];
		const prefix = decoder.decode(bytes.subarray(offset + 345, offset + 345 + 155)).split('\0')[0];
		const fullName = prefix ? `${prefix}/${name}` : name;
		const sizeStr = decoder
			.decode(bytes.subarray(offset + 124, offset + 124 + 12))
			.split('\0')[0]
			.trim();
		const size = sizeStr ? parseInt(sizeStr, 8) : 0;
		const typeFlag = decoder.decode(bytes.subarray(offset + 156, offset + 157));
		offset += 512;
		if (size > 0 && (typeFlag === '' || typeFlag === '0' || typeFlag === '\0')) {
			if (fullName && fullName.endsWith('.json')) {
				const content = decoder.decode(bytes.subarray(offset, offset + size));
				try {
					out.set(fullName, JSON.parse(content));
				} catch {
					// skip malformed json
				}
			} else if (fullName && fullName.endsWith('.bin')) {
				// Copy out the raw bytes so the underlying ArrayBuffer can be
				// GC'd once the parser returns; sharing the original buffer
				// would pin the whole 50 MB decompressed package in memory.
				const slice = bytes.subarray(offset, offset + size);
				const copy = new Uint8Array(size);
				copy.set(slice);
				out.set(fullName, copy);
			}
			// Skip past content padded to 512-byte boundary.
			offset += Math.ceil(size / 512) * 512;
		}
	}
	return out;
}

function isZeroBlock(bytes: Uint8Array, offset: number): boolean {
	for (let i = offset; i < offset + 512; i++) {
		if (bytes[i] !== 0) return false;
	}
	return true;
}
