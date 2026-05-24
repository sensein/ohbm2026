/**
 * Stage 15 (spec 015-neuroscape-context, T062 / R-015):
 * Runtime PubMed abstract fetcher for the NeuroScape subsite.
 *
 * The /neuroscape/ detail page renders local fields (title, year,
 * cluster, neighbours) immediately from neuroscape.parquet, then
 * calls fetchPubmedRecord(pubmed_id) to populate authors / journal /
 * abstract body / DOI from NCBI E-utilities EFetch at view time.
 *
 * Per R-015:
 *  - Endpoint: efetch.fcgi?db=pubmed&id=<n>&retmode=xml
 *  - CORS: enabled by NCBI (verified manually); no proxy required
 *  - Cache: in-memory Map<pubmed_id, Promise<FetchedRecord>> — the
 *    Promise lives in the cache so that two concurrent calls for the
 *    same id resolve to a single in-flight fetch, not two
 *  - Rate limit: 3 req/s anon, 10 req/s when VITE_NCBI_API_KEY is
 *    set at build time. Token-bucket implementation; calls wait for
 *    a token before issuing the network request
 *  - Retry: 3 attempts on 5xx / network error, exponential backoff
 *    250 ms, 500 ms, 1 s. 4xx is a non-retryable failure (the id
 *    doesn't exist or the request was malformed)
 */

import { parsePubmedXml, type FetchedRecord } from './pubmed_xml';

export type { FetchedRecord };

const EFETCH_BASE = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi';

export class PubmedFetchError extends Error {
	readonly pubmedId: number;
	readonly cause?: unknown;
	constructor(pubmedId: number, message: string, cause?: unknown) {
		super(message);
		this.name = 'PubmedFetchError';
		this.pubmedId = pubmedId;
		this.cause = cause;
	}
}

// ===========================================================================
// Token bucket — paces calls to NCBI to within their documented limits.
// ===========================================================================

type Bucket = {
	tokens: number;
	max: number;
	refillPerSec: number;
	lastRefill: number;
};

let bucket: Bucket | null = null;

function getBucket(): Bucket {
	if (bucket !== null) return bucket;
	// VITE_NCBI_API_KEY is baked into the bundle at build time. When
	// present, NCBI permits 10 req/s; otherwise the anon limit is 3.
	const hasKey = Boolean(
		(import.meta.env as Record<string, unknown>).VITE_NCBI_API_KEY
	);
	const rate = hasKey ? 10 : 3;
	bucket = {
		tokens: rate,
		max: rate,
		refillPerSec: rate,
		lastRefill: Date.now()
	};
	return bucket;
}

async function waitForToken(): Promise<void> {
	const b = getBucket();
	// Refill based on elapsed time.
	const now = Date.now();
	const elapsedSec = (now - b.lastRefill) / 1000;
	if (elapsedSec > 0) {
		b.tokens = Math.min(b.max, b.tokens + elapsedSec * b.refillPerSec);
		b.lastRefill = now;
	}
	if (b.tokens >= 1) {
		b.tokens -= 1;
		return;
	}
	// Not enough — wait the minimum time for one token.
	const needed = 1 - b.tokens;
	const waitMs = Math.ceil((needed / b.refillPerSec) * 1000);
	await new Promise<void>((r) => setTimeout(r, waitMs));
	// Recurse to re-evaluate; bounded by the token math above.
	return waitForToken();
}

// ===========================================================================
// In-memory result cache — Map<pubmed_id, Promise<FetchedRecord>>.
// Two concurrent calls for the same id share one in-flight fetch.
// ===========================================================================

const sessionCache = new Map<number, Promise<FetchedRecord>>();

export function resetPubmedCacheForTests(): void {
	sessionCache.clear();
	bucket = null;
}

// ===========================================================================
// fetchPubmedRecord — public entry point.
// ===========================================================================

const RETRY_DELAYS_MS = [250, 500, 1000] as const;

function buildUrl(pubmedId: number): string {
	const u = new URL(EFETCH_BASE);
	u.searchParams.set('db', 'pubmed');
	u.searchParams.set('id', String(pubmedId));
	u.searchParams.set('retmode', 'xml');
	const key = (import.meta.env as Record<string, unknown>).VITE_NCBI_API_KEY as
		| string
		| undefined;
	if (key) u.searchParams.set('api_key', key);
	return u.toString();
}

/** Internal: perform the actual fetch with retry. Token-bucket-paced. */
async function fetchOnce(
	pubmedId: number,
	fetcher: typeof fetch
): Promise<FetchedRecord> {
	const url = buildUrl(pubmedId);
	let lastErr: unknown = null;
	for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
		await waitForToken();
		try {
			const res = await fetcher(url);
			if (res.status >= 400 && res.status < 500) {
				throw new PubmedFetchError(
					pubmedId,
					`PubMed EFetch returned ${res.status} — non-retryable`
				);
			}
			if (!res.ok) {
				// 5xx → retry
				lastErr = new PubmedFetchError(pubmedId, `PubMed EFetch returned ${res.status}`);
			} else {
				const xml = await res.text();
				return parsePubmedXml(xml);
			}
		} catch (err) {
			// Non-retryable PubmedFetchError already thrown above.
			if (err instanceof PubmedFetchError) throw err;
			lastErr = err;
		}
		// If we still have retries left, back off; else fall through to
		// throw.
		if (attempt < RETRY_DELAYS_MS.length) {
			await new Promise<void>((r) => setTimeout(r, RETRY_DELAYS_MS[attempt]));
		}
	}
	throw new PubmedFetchError(
		pubmedId,
		`PubMed EFetch failed after ${RETRY_DELAYS_MS.length + 1} attempts`,
		lastErr
	);
}

/**
 * Fetch (or return cached) a single PubMed record's runtime fields.
 *
 * @param pubmedId the integer PubMed id (matches the `pubmed_id`
 *   column in neuroscape.parquet's `articles` row group)
 * @param fetcher injectable fetch for tests; defaults to global
 *   `fetch`
 */
export function fetchPubmedRecord(
	pubmedId: number,
	fetcher: typeof fetch = fetch
): Promise<FetchedRecord> {
	const hit = sessionCache.get(pubmedId);
	if (hit !== undefined) return hit;
	const promise = fetchOnce(pubmedId, fetcher).catch((err) => {
		// On failure, evict the cached promise so a subsequent call
		// (e.g. the Retry button) can try again instead of receiving
		// the same rejection forever.
		sessionCache.delete(pubmedId);
		throw err;
	});
	sessionCache.set(pubmedId, promise);
	return promise;
}
