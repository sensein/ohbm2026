/**
 * Cache-API wrapper for the per-deployment parquet fetch.
 *
 * First load: fetches as today (full GET) and stores the Response in
 * a named Cache. Subsequent loads: HEAD the same URL with
 * `If-None-Match: <stored ETag>`. 304 → return cached bytes. 200 →
 * refetch (ETag changed) and overwrite cache. Any network error with
 * a cache hit available → serve cache (offline mode).
 *
 * The hyparquet streaming-Range path in `loader.ts:loadDataPackage`
 * isn't actually used for the primary load — that's a full
 * `fetch(url) → response.body.getReader()`, so wrapping at this layer
 * is byte-equivalent. Range fetches are only used downstream for
 * sibling-manifest peeks in `verifyAtlasSiblingDrift`, which run
 * against the live URLs (not cached) so they always see fresh state.
 *
 * Why Cache API and not IndexedDB:
 *   - Persists across sessions out-of-the-box, just like IDB.
 *   - Native HTTP-Response semantics (status, headers like ETag /
 *     Last-Modified come along for the ride; we don't have to
 *     reinvent the conditional-revalidate dance).
 *   - Single-step `cache.put(url, response.clone())` after the fetch.
 *   - 26 MB / 96 MB parquets are well within typical browser
 *     per-origin storage quotas (Chrome: 60% of disk; Safari: 1 GB
 *     soft cap on the StorageBucket).
 *
 * Why not a Service Worker:
 *   - SW adds significant deployment complexity (scope, registration,
 *     unregister flow, scope-mismatch for the three sibling builds
 *     under one gh-pages host). Cache API alone gives us the win
 *     without that surface area. SW can be added later if we need
 *     transparent interception of fetches we don't own.
 */

const CACHE_NAME = 'ohbm-parquet-v1';

/** Result of a cache-aware parquet fetch. */
export interface CachedParquetResult {
	/** Streaming response (whether from network or cache). The caller
	 *  consumes `.body` like a normal fetch result, so the existing
	 *  progress-reader code in `loadDataPackage` works unchanged. */
	response: Response;
	/** Where this byte-stream actually came from. Useful for telemetry
	 *  and the load-phase placeholder ("Loading from cache…"). */
	source: 'cache-hit-validated' | 'cache-hit-offline' | 'network-fresh' | 'network-cold';
}

/** Returns true if the runtime exposes the Cache API. Some embedded
 *  contexts (older Safari Web View, etc.) lack it; callers fall back
 *  to a plain network fetch in that case. */
function cacheApiAvailable(): boolean {
	return typeof caches !== 'undefined' && typeof caches.open === 'function';
}

/** Open the named cache, or `null` if the runtime can't. */
async function openCache(): Promise<Cache | null> {
	if (!cacheApiAvailable()) return null;
	try {
		return await caches.open(CACHE_NAME);
	} catch {
		return null;
	}
}

/**
 * Fetch a parquet URL, prefer cache when valid.
 *
 * Strategy:
 *   1. No cache or no cache entry → plain GET, store, return.
 *   2. Cache entry → HEAD with `If-None-Match: <etag>`. 304 → return
 *      cache. 200 → refetch + overwrite.
 *   3. HEAD failed (network down, CORS, etc.) → serve cache anyway
 *      (offline mode). Tag the source as 'cache-hit-offline'.
 */
export async function fetchParquetCached(
	url: string,
	fetcher: typeof fetch = fetch
): Promise<CachedParquetResult> {
	const cache = await openCache();
	if (!cache) {
		// No Cache API. Plain network fetch — same behaviour as before.
		const response = await fetcher(url);
		return { response, source: 'network-cold' };
	}

	const cached = await cache.match(url).catch(() => undefined);

	if (cached) {
		const etag = cached.headers.get('etag');
		const lastMod = cached.headers.get('last-modified');
		const condHeaders: HeadersInit = {};
		if (etag) condHeaders['If-None-Match'] = etag;
		else if (lastMod) condHeaders['If-Modified-Since'] = lastMod;

		try {
			const head = await fetcher(url, { method: 'HEAD', headers: condHeaders });
			if (head.status === 304) {
				// Cache is still valid — clone so the caller can consume the body
				// without invalidating our cache entry.
				return { response: cached.clone(), source: 'cache-hit-validated' };
			}
			if (head.ok) {
				// New ETag (or no validators at all). Refetch the full body
				// and overwrite the cache.
				const fresh = await fetcher(url);
				if (fresh.ok && fresh.body) {
					// `response.clone()` — one copy goes into the cache, one
					// goes to the caller. We can't `put` a body that's already
					// been consumed.
					await cache.put(url, fresh.clone()).catch(() => undefined);
					return { response: fresh, source: 'network-fresh' };
				}
				// Refetch failed despite HEAD saying we should — fall back to
				// the (potentially stale) cache rather than failing the load.
				return { response: cached.clone(), source: 'cache-hit-offline' };
			}
			// HEAD returned 4xx/5xx (other than 304). Serve cache.
			return { response: cached.clone(), source: 'cache-hit-offline' };
		} catch {
			// Network error during HEAD — offline. Serve cache.
			return { response: cached.clone(), source: 'cache-hit-offline' };
		}
	}

	// Cold fetch.
	const response = await fetcher(url);
	if (response.ok && response.body) {
		// Store a clone for next time. Don't await the put — if it
		// errors (quota), we still want the caller to consume the body.
		void cache.put(url, response.clone()).catch(() => undefined);
		return { response, source: 'network-cold' };
	}
	return { response, source: 'network-cold' };
}

/**
 * Background prefetch — fire-and-forget. Called by atlas-root after
 * its own parquet finishes loading; warms the sibling parquets'
 * caches so a click into /ohbm2026/ or /neuroscape/ hits the cache.
 *
 * Skips slow connections to avoid eating mobile data: `effectiveType`
 * is 'slow-2g'/'2g'/'3g'/'4g' on Chrome + Android Chrome (NetworkInformation
 * API). Other browsers always prefetch.
 */
export function prefetchInBackground(urls: string[]): void {
	if (!cacheApiAvailable() || typeof window === 'undefined') return;
	const conn = (
		navigator as Navigator & {
			connection?: { effectiveType?: string; saveData?: boolean };
		}
	).connection;
	if (conn?.saveData) return;
	if (conn?.effectiveType === '2g' || conn?.effectiveType === 'slow-2g') return;
	for (const url of urls) {
		void (async () => {
			try {
				// `fetchParquetCached` already does the right thing: if
				// nothing in cache, it'll do a cold network fetch and
				// store; if cached, it'll revalidate via HEAD.
				const result = await fetchParquetCached(url);
				// Drain the body so the network fetch actually completes
				// and the Cache API entry settles. Without this the
				// Response sits with an unconsumed body and the cache.put
				// may be racing.
				if (result.source === 'network-cold' || result.source === 'network-fresh') {
					try {
						await result.response.arrayBuffer();
					} catch {
						/* ignore */
					}
				}
			} catch {
				/* ignore — background prefetch is best-effort */
			}
		})();
	}
}

/** Programmatic cache reset for tests + dev-only "force refresh" UI. */
export async function clearParquetCache(): Promise<boolean> {
	if (!cacheApiAvailable()) return false;
	try {
		return await caches.delete(CACHE_NAME);
	} catch {
		return false;
	}
}
