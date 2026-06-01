/**
 * Spec 019 / T013-T015 — NeuroScape ranker unit tests.
 *
 * Mocks the worker + range-fetch helpers so the 5-step pipeline can be
 * exercised without spinning up Web Workers or fetching real parquet
 * data. Each test injects canned worker responses + asserts ranker
 * orchestration behaviour.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	NeuroscapeRanker,
	defaultSemanticWorker,
	type RankerConfig,
	type RankerHooks,
	type WorkerLike,
	type ClusterCentroidEntry,
	type KnnEntry
} from '$lib/search/neuroscape_ranker';
import type { ParsedQuery } from '$lib/filter';

/** Tiny synthetic centroids: 3 clusters, 4-dim vectors. */
function makeCentroids(): ClusterCentroidEntry[] {
	return [
		{ cluster_id: 0, centroid_vector: new Float32Array([1, 0, 0, 0]) },
		{ cluster_id: 1, centroid_vector: new Float32Array([0, 1, 0, 0]) },
		{ cluster_id: 2, centroid_vector: new Float32Array([0, 0, 1, 0]) }
	];
}

function makeBaseCfg(overrides: Partial<RankerConfig> = {}): RankerConfig {
	const centroids = makeCentroids();
	const pubmedToCluster = new Map<bigint, number>([
		[100n, 0],
		[101n, 0],
		[200n, 1],
		[201n, 1],
		[300n, 2]
	]);
	const knnIndex = new Map<bigint, KnnEntry>([
		[
			100n,
			{
				pubmed_id: 100n,
				nearest_pubmed_ids: [101n, 200n],
				nearest_distances: [0.1, 0.4]
			}
		],
		[101n, { pubmed_id: 101n, nearest_pubmed_ids: [100n], nearest_distances: [0.1] }]
	]);
	return {
		worker: {
			encodeQuery: vi.fn(async () => new Float32Array([1, 0, 0, 0])),
			loadCluster: vi.fn(async () => {}),
			evictCluster: vi.fn(async () => {}),
			bruteForceCluster: vi.fn(async () => [
				{ id: 100n, cosine: 0.9 },
				{ id: 101n, cosine: 0.85 }
			]),
			rerank: vi.fn(
				async (candidates: Array<{ id: bigint; cluster_id: number }>) =>
					candidates.map((c, i) => ({ id: c.id, cosine: 0.9 - i * 0.1 }))
			)
		},
		fetchClusterVectors: vi.fn(async () => ({
			pubmed_ids: new BigInt64Array([100n, 101n]),
			vectors: new Int8Array(2 * 4)
		})),
		centroids,
		pubmedToCluster,
		knnIndex,
		clusterCap: 4,
		...overrides
	};
}

function parsedFromText(s: string): ParsedQuery {
	// Minimal stand-in — the ranker's parsedToEncodableString reads
	// `groups[].clauses[]` with `kind: 'word'` clauses.
	return {
		groups: [
			{
				clauses: s
					.split(/\s+/)
					.filter((w) => w.length > 0)
					.map((word) => ({ kind: 'word' as const, word, negate: false }))
			}
		],
		hasOperators: false
	};
}

describe('NeuroscapeRanker — 5-step pipeline (T013)', () => {
	it('happy path: returns 5 ranked hits in cosine-descending order', async () => {
		const cfg = makeBaseCfg();
		const r = new NeuroscapeRanker(cfg);
		const hits = await r.searchNeuroscape(parsedFromText('memory consolidation'), 5);
		expect(hits.length).toBeGreaterThan(0);
		// Each hit's cosine should be non-increasing (sorted desc).
		for (let i = 1; i < hits.length; i++) {
			expect(hits[i].cosine).toBeLessThanOrEqual(hits[i - 1].cosine);
		}
		// First hit's corpus is always neuroscape.
		expect(hits[0].corpus).toBe('neuroscape');
	});

	it('routes to the cluster whose centroid best matches the query vector', async () => {
		// Make the worker.encodeQuery return a vector aligned with cluster 1.
		const cfg = makeBaseCfg({
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => new Float32Array([0, 1, 0, 0]))
			} as WorkerLike
		});
		const r = new NeuroscapeRanker(cfg);
		await r.searchNeuroscape(parsedFromText('attention'), 5);
		expect(cfg.worker.bruteForceCluster).toHaveBeenCalledWith(
			1,
			expect.any(Float32Array),
			3
		);
	});

	it('brute-forces topK seeds when no KNN graph is resident (atlas-root backdrop)', async () => {
		// atlas-root ships no neighbour table → knnIndex is empty, so the
		// KNN-expansion step yields only the seeds themselves. With the
		// default 3 seeds that would cap results at 3 rows; the ranker must
		// instead brute-force topK seeds so the routed cluster fills the list.
		const cfg = makeBaseCfg({ knnIndex: new Map<bigint, KnnEntry>() });
		const r = new NeuroscapeRanker(cfg);
		await r.searchNeuroscape(parsedFromText('memory consolidation'), 5);
		expect(cfg.worker.bruteForceCluster).toHaveBeenCalledWith(
			expect.any(Number),
			expect.any(Float32Array),
			5
		);
	});

	it('returns up to topK hits from a large routed cluster — count is topK-driven, not hard-capped (atlas-root semantic-match fix)', async () => {
		// Regression for complaint #2 ("under a semantic match it should match a
		// lot more"): on atlas-root the KNN graph is empty, so the routed
		// cluster's brute-force IS the candidate set. With seedCount =
		// max(topK, 3) the cluster can fill the whole topK list. Earlier the UI
		// hard-capped the panel at 60 rows; the ranker itself must honour topK.
		const N = 120;
		const ids = Array.from({ length: N }, (_, i) => BigInt(1000 + i));
		const pubmedToCluster = new Map<bigint, number>(ids.map((id) => [id, 0]));
		const cfg = makeBaseCfg({
			knnIndex: new Map<bigint, KnnEntry>(), // atlas-root: no neighbour graph
			pubmedToCluster,
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => new Float32Array([1, 0, 0, 0])),
				// Brute-force returns the requested seedCount hits.
				bruteForceCluster: vi.fn(async (_cid: number, _qv: Float32Array, topK: number) =>
					ids.slice(0, topK).map((id, i) => ({ id, cosine: 0.99 - i * 0.001 }))
				),
				rerank: vi.fn(async (candidates: Array<{ id: bigint; cluster_id: number }>) =>
					candidates.map((c, i) => ({ id: c.id, cosine: 0.99 - i * 0.001 }))
				)
			} as WorkerLike
		});
		const r = new NeuroscapeRanker(cfg);
		const hits = await r.searchNeuroscape(parsedFromText('memory consolidation'), 100);
		// Far more than the old hard cap of 60; bounded by topK=100.
		expect(hits.length).toBe(100);
		expect(hits.length).toBeGreaterThan(60);
		// All sourced from cosine re-rank (no KNN-distance fallback when the
		// single routed cluster covers every candidate).
		expect(hits.every((h) => h.score_source === 'cosine')).toBe(true);
	});

	it('atlas-root: surfaces routed-cluster seeds even when pubmedToCluster omits them (sparse-LOD regression)', async () => {
		// PROD REGRESSION: atlas-root builds pubmedToCluster from the LOD scatter
		// sample (a few hundred points), NOT the full corpus — so the full-corpus
		// ids the brute-force returns from the routed cluster are absent from it.
		// The seeds were brute-forced FROM the routed cluster, so their cluster is
		// known regardless; the ranker must still surface them. Before the fix
		// every seed was dropped (cid === undefined) → 0 results on atlas-root
		// while neuroscape (full map) worked.
		const ids = Array.from({ length: 50 }, (_, i) => BigInt(5000 + i));
		const cfg = makeBaseCfg({
			knnIndex: new Map<bigint, KnnEntry>(), // atlas-root: no neighbour graph
			pubmedToCluster: new Map<bigint, number>(), // atlas-root: LOD sample omits these ids
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => new Float32Array([1, 0, 0, 0])),
				bruteForceCluster: vi.fn(async (_cid: number, _qv: Float32Array, topK: number) =>
					ids.slice(0, topK).map((id, i) => ({ id, cosine: 0.99 - i * 0.001 }))
				),
				rerank: vi.fn(async (candidates: Array<{ id: bigint; cluster_id: number }>) =>
					candidates.map((c, i) => ({ id: c.id, cosine: 0.99 - i * 0.001 }))
				)
			} as WorkerLike
		});
		const r = new NeuroscapeRanker(cfg);
		const hits = await r.searchNeuroscape(parsedFromText('long covid complications'), 50);
		// Before the fix: 0 (every seed dropped on the empty map). After: all 50.
		expect(hits.length).toBe(50);
		expect(hits.every((h) => h.score_source === 'cosine')).toBe(true);
	});

	it('updateMaps upgrades the corpus maps in place (neighbours land after init)', async () => {
		// Ranker is initialised early (semantic works ASAP) with NO neighbour
		// graph — the k=20 graph streams in later (neuroscape neighbours wave).
		// updateMaps installs it without recreating the worker; KNN-expansion
		// must then reach neighbour-only ids the seeds didn't include.
		const cfg = makeBaseCfg({ knnIndex: new Map<bigint, KnnEntry>() });
		const r = new NeuroscapeRanker(cfg);
		// Seeds (from bruteForceCluster) are 100n,101n; 200n is reachable ONLY
		// via the neighbour graph we're about to install.
		r.updateMaps({
			knnIndex: new Map<bigint, KnnEntry>([
				[100n, { pubmed_id: 100n, nearest_pubmed_ids: [200n], nearest_distances: [0.2] }]
			])
		});
		const hits = await r.searchNeuroscape(parsedFromText('memory'), 10);
		const ids = hits.map((h) => h.id);
		expect(ids).toContain(100n);
		expect(ids).toContain(200n); // neighbour-only → proves updateMaps took effect
	});

	it('progressive sweep reaches a relevant article in a neighbouring cluster (exhaustiveness)', async () => {
		// Single-cluster routing could only ever return cluster 0's hits. The
		// sweep visits the next-nearest cluster too, so a relevant article there
		// (20n, within threshold) is surfaced.
		const centroids = [
			{ cluster_id: 0, centroid_vector: new Float32Array([1, 0, 0, 0]) },
			{ cluster_id: 1, centroid_vector: new Float32Array([0, 1, 0, 0]) }
		];
		const perCluster: Record<number, Array<{ id: bigint; cosine: number }>> = {
			0: [{ id: 10n, cosine: 0.9 }],
			1: [{ id: 20n, cosine: 0.7 }]
		};
		const cfg = makeBaseCfg({
			centroids,
			knnIndex: new Map<bigint, KnnEntry>(),
			pubmedToCluster: new Map<bigint, number>([
				[10n, 0],
				[20n, 1]
			]),
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => new Float32Array([0.9, 0.3, 0, 0])),
				bruteForceCluster: vi.fn(async (cid: number) => perCluster[cid] ?? []),
				rerank: vi.fn(async (cands: Array<{ id: bigint; cluster_id: number }>) =>
					cands.map((c, i) => ({ id: c.id, cosine: 0.9 - i * 0.01 }))
				)
			} as WorkerLike
		});
		const r = new NeuroscapeRanker(cfg);
		const ids = (await r.searchNeuroscape(parsedFromText('memory'), 10)).map((h) => h.id);
		expect(ids).toContain(10n); // nearest cluster
		expect(ids).toContain(20n); // neighbouring cluster — missed by single-cluster routing
	});

	it('sweep stops at the distance threshold — far clusters are not fetched', async () => {
		const centroids = [
			{ cluster_id: 0, centroid_vector: new Float32Array([1, 0, 0, 0]) },
			{ cluster_id: 1, centroid_vector: new Float32Array([0, 1, 0, 0]) },
			{ cluster_id: 2, centroid_vector: new Float32Array([0, 0, 1, 0]) }
		];
		// cluster 1's best hit is beyond the 0.8 distance horizon (cosine 0.1 →
		// dist 0.9), so the sweep stops there; cluster 2 must never be fetched
		// even though it holds a 0.99 hit (the "no very far clusters" directive).
		const perCluster: Record<number, Array<{ id: bigint; cosine: number }>> = {
			0: [{ id: 10n, cosine: 0.95 }],
			1: [{ id: 20n, cosine: 0.1 }],
			2: [{ id: 30n, cosine: 0.99 }]
		};
		const bf = vi.fn(async (cid: number) => perCluster[cid] ?? []);
		const cfg = makeBaseCfg({
			centroids,
			knnIndex: new Map<bigint, KnnEntry>(),
			pubmedToCluster: new Map<bigint, number>([
				[10n, 0],
				[20n, 1],
				[30n, 2]
			]),
			maxDistance: 0.8,
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => new Float32Array([0.9, 0.5, 0.2, 0])),
				bruteForceCluster: bf,
				rerank: vi.fn(async (cands: Array<{ id: bigint; cluster_id: number }>) =>
					cands.map((c, i) => ({ id: c.id, cosine: 0.9 - i * 0.01 }))
				)
			} as WorkerLike
		});
		const r = new NeuroscapeRanker(cfg);
		await r.searchNeuroscape(parsedFromText('memory'), 10);
		const fetched = bf.mock.calls.map((c) => c[0]);
		expect(fetched).toContain(0);
		expect(fetched).toContain(1); // boundary cluster fetched, then stop
		expect(fetched).not.toContain(2); // beyond the horizon → never fetched
	});

	it('keeps the default 3 seeds when a KNN graph IS resident', async () => {
		const cfg = makeBaseCfg();
		const r = new NeuroscapeRanker(cfg);
		await r.searchNeuroscape(parsedFromText('memory consolidation'), 5);
		expect(cfg.worker.bruteForceCluster).toHaveBeenCalledWith(
			expect.any(Number),
			expect.any(Float32Array),
			3
		);
	});

	it('emits expected state transitions via onState hook', async () => {
		const states: string[] = [];
		const hooks: RankerHooks = {
			onState: (s) => states.push(s)
		};
		const cfg = makeBaseCfg();
		const r = new NeuroscapeRanker(cfg);
		await r.searchNeuroscape(parsedFromText('memory'), 5, hooks);
		// Pipeline goes through embedding → routing → fetching-vectors →
		// brute-force → knn-expand → re-rank → ready.
		expect(states).toContain('embedding');
		expect(states).toContain('routing');
		expect(states).toContain('fetching-vectors');
		expect(states).toContain('brute-force');
		expect(states).toContain('knn-expand');
		expect(states).toContain('re-rank');
		expect(states[states.length - 1]).toBe('ready');
	});

	it('queries below the min-char threshold short-circuit (FR-010)', async () => {
		const cfg = makeBaseCfg();
		const r = new NeuroscapeRanker(cfg);
		const hits = await r.searchNeuroscape(parsedFromText('ab'), 5);
		expect(hits).toEqual([]);
		expect(cfg.worker.encodeQuery).not.toHaveBeenCalled();
	});
});

describe('NeuroscapeRanker — per-query cluster budget (T014, FR-024)', () => {
	it('caps the clusters fetched WITHIN one query; over-budget neighbours fall back to knn-distance (routing cluster always loads)', async () => {
		// One seed in cluster 0 whose KNN neighbours span clusters 1, 2, 3.
		const centroids = [
			{ cluster_id: 0, centroid_vector: new Float32Array([1, 0, 0, 0]) },
			{ cluster_id: 1, centroid_vector: new Float32Array([0, 1, 0, 0]) },
			{ cluster_id: 2, centroid_vector: new Float32Array([0, 0, 1, 0]) },
			{ cluster_id: 3, centroid_vector: new Float32Array([0, 0, 0, 1]) }
		];
		const pubmedToCluster = new Map<bigint, number>([
			[100n, 0],
			[200n, 1],
			[300n, 2],
			[400n, 3]
		]);
		const knnIndex = new Map<bigint, KnnEntry>([
			[
				100n,
				{
					pubmed_id: 100n,
					nearest_pubmed_ids: [200n, 300n, 400n],
					nearest_distances: [0.1, 0.2, 0.3]
				}
			]
		]);
		const fetched: number[] = [];
		const cfg = makeBaseCfg({
			clusterCap: 2, // routing cluster + exactly one expansion cluster
			centroids,
			pubmedToCluster,
			knnIndex,
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => new Float32Array([1, 0, 0, 0])),
				bruteForceCluster: vi.fn(async () => [{ id: 100n, cosine: 0.9 }])
			} as WorkerLike,
			fetchClusterVectors: vi.fn(async (clusterId: number) => {
				fetched.push(clusterId);
				return { pubmed_ids: new BigInt64Array([]), vectors: new Int8Array(0) };
			})
		});
		const r = new NeuroscapeRanker(cfg);

		const capCalls: number[] = [];
		const hits = await r.searchNeuroscape(parsedFromText('memory consolidation'), 10, {
			onCapExceeded: (n) => capCalls.push(n)
		});

		// Routing cluster (0) + exactly one expansion cluster (1) range-fetched;
		// clusters 2 and 3 are over the per-query budget.
		expect(fetched).toEqual([0, 1]);
		expect(capCalls.length).toBeGreaterThan(0);
		// Search still returns results — the capped neighbours appear via the
		// precomputed knn-distance fallback, never an empty result.
		expect(hits.length).toBeGreaterThan(0);
		expect(hits.some((h) => h.score_source === 'knn-distance')).toBe(true);
	});

	it('a fresh query routing cluster always loads — earlier queries never starve it (regression for the empty-results bug)', async () => {
		const centroids = [
			{ cluster_id: 0, centroid_vector: new Float32Array([1, 0, 0, 0]) },
			{ cluster_id: 1, centroid_vector: new Float32Array([0, 1, 0, 0]) }
		];
		const pubmedToCluster = new Map<bigint, number>([
			[100n, 0],
			[200n, 1]
		]);
		const knnIndex = new Map<bigint, KnnEntry>([
			[100n, { pubmed_id: 100n, nearest_pubmed_ids: [], nearest_distances: [] }],
			[200n, { pubmed_id: 200n, nearest_pubmed_ids: [], nearest_distances: [] }]
		]);
		const fetched: number[] = [];
		const cfg = makeBaseCfg({
			clusterCap: 1, // a session-scoped cap would block the 2nd query here
			centroids,
			pubmedToCluster,
			knnIndex,
			fetchClusterVectors: vi.fn(async (clusterId: number) => {
				fetched.push(clusterId);
				return { pubmed_ids: new BigInt64Array([]), vectors: new Int8Array(0) };
			})
		});
		const r = new NeuroscapeRanker(cfg);

		cfg.worker.encodeQuery = vi.fn(async () => new Float32Array([1, 0, 0, 0]));
		cfg.worker.bruteForceCluster = vi.fn(async () => [{ id: 100n, cosine: 0.9 }]);
		const h1 = await r.searchNeuroscape(parsedFromText('first topic'), 5);
		expect(h1.length).toBeGreaterThan(0);

		// Second query routes to a DIFFERENT cluster. The old per-session cap
		// (LRU already at size 1) would return [] here; the per-query budget
		// resets, so cluster 1 loads and the query returns hits.
		cfg.worker.encodeQuery = vi.fn(async () => new Float32Array([0, 1, 0, 0]));
		cfg.worker.bruteForceCluster = vi.fn(async () => [{ id: 200n, cosine: 0.9 }]);
		const h2 = await r.searchNeuroscape(parsedFromText('second topic'), 5);
		expect(fetched).toEqual([0, 1]);
		expect(h2.length).toBeGreaterThan(0);
	});

	it('expandSearchDepth() lifts the per-query budget so a previously-capped neighbour cluster gets fetched', async () => {
		const centroids = [
			{ cluster_id: 0, centroid_vector: new Float32Array([1, 0, 0, 0]) },
			{ cluster_id: 1, centroid_vector: new Float32Array([0, 1, 0, 0]) }
		];
		const pubmedToCluster = new Map<bigint, number>([
			[100n, 0],
			[200n, 1]
		]);
		const knnIndex = new Map<bigint, KnnEntry>([
			[100n, { pubmed_id: 100n, nearest_pubmed_ids: [200n], nearest_distances: [0.2] }]
		]);
		const fetched: number[] = [];
		const cfg = makeBaseCfg({
			clusterCap: 1,
			centroids,
			pubmedToCluster,
			knnIndex,
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => new Float32Array([1, 0, 0, 0])),
				bruteForceCluster: vi.fn(async () => [{ id: 100n, cosine: 0.9 }])
			} as WorkerLike,
			fetchClusterVectors: vi.fn(async (clusterId: number) => {
				fetched.push(clusterId);
				return { pubmed_ids: new BigInt64Array([]), vectors: new Int8Array(0) };
			})
		});
		const r = new NeuroscapeRanker(cfg);

		const capCalls: number[] = [];
		await r.searchNeuroscape(parsedFromText('first'), 5, {
			onCapExceeded: (n) => capCalls.push(n)
		});
		// Budget 1: routing cluster only; the cross-cluster neighbour is capped.
		expect(fetched).toEqual([0]);
		expect(capCalls.length).toBeGreaterThan(0);

		// Release the budget; the next query may fetch the neighbour cluster.
		r.expandSearchDepth();
		await r.searchNeuroscape(parsedFromText('second'), 5);
		expect(fetched).toContain(1);
	});
});

// ── defaultSemanticWorker adapter (T028 / FR-002) ──────────────────────
//
// The adapter bridges the abstract `WorkerLike` (bigint ids,
// Float32Array) to the concrete semantic.worker.ts postMessage protocol
// (string ids on the wire, ArrayBuffer payloads). We stub `globalThis.
// Worker` with a fake that scripts the worker side of each message so we
// can assert the boundary conversions without a real Web Worker.

const DIM = 4;

type Listener = (e: { data: unknown }) => void;

/** Fake Worker that echoes the documented semantic.worker.ts replies. */
class FakeSemanticWorker {
	static last: FakeSemanticWorker | null = null;
	private msgListeners = new Set<Listener>();
	private errListeners = new Set<(e: unknown) => void>();
	/** Toggle: make the next 'encode-query' reply with an id-targeted error
	 *  instead of a vector. */
	failNextEncodeWith: string | null = null;
	/** Toggle: emit a global (no-id) error on the next postMessage. */
	emitGlobalError: string | null = null;

	constructor(
		public url: unknown,
		public opts: unknown
	) {
		FakeSemanticWorker.last = this;
	}

	addEventListener(type: string, fn: Listener | ((e: unknown) => void)) {
		if (type === 'message') this.msgListeners.add(fn as Listener);
		else if (type === 'error') this.errListeners.add(fn as (e: unknown) => void);
	}
	removeEventListener(type: string, fn: Listener | ((e: unknown) => void)) {
		if (type === 'message') this.msgListeners.delete(fn as Listener);
		else if (type === 'error') this.errListeners.delete(fn as (e: unknown) => void);
	}
	private emit(data: unknown) {
		for (const fn of [...this.msgListeners]) fn({ data });
	}

	postMessage(msg: Record<string, unknown>, _transfer?: unknown[]) {
		const type = msg.type as string;
		queueMicrotask(() => {
			if (this.emitGlobalError) {
				const reason = this.emitGlobalError;
				this.emitGlobalError = null;
				this.emit({ type: 'error', message: reason });
				return;
			}
			switch (type) {
				case 'init':
					this.emit({ type: 'ready' });
					return;
				case 'encode-query': {
					if (this.failNextEncodeWith) {
						const reason = this.failNextEncodeWith;
						this.failNextEncodeWith = null;
						this.emit({ type: 'error', id: msg.id, reason });
						return;
					}
					const v = new Float32Array(DIM).fill(0.5);
					this.emit({ type: 'query-encoded', id: msg.id, query_vector: v.buffer });
					return;
				}
				case 'load-cluster':
					this.emit({ type: 'cluster-loaded', cluster_id: msg.cluster_id });
					return;
				case 'evict-cluster':
					this.emit({ type: 'cluster-evicted', cluster_id: msg.cluster_id });
					return;
				case 'brute-force':
					this.emit({
						type: 'brute-force-hits',
						id: msg.id,
						cluster_id: msg.cluster_id,
						hits: [
							{ id: '100', cosine: 0.9 },
							{ id: '101', cosine: 0.8 }
						]
					});
					return;
				case 'rerank':
					this.emit({
						type: 'reranked',
						id: msg.id,
						hits: [{ id: '100', cosine: 0.95 }]
					});
					return;
			}
		});
	}
}

describe('defaultSemanticWorker adapter (T028 / FR-002)', () => {
	beforeEach(() => {
		vi.stubGlobal('Worker', FakeSemanticWorker as unknown as typeof Worker);
	});
	afterEach(() => {
		vi.unstubAllGlobals();
		FakeSemanticWorker.last = null;
	});

	it('resolves only after the worker posts ready, then bridges the protocol', async () => {
		const worker = await defaultSemanticWorker({ dim: DIM, scale: 439.258 });
		// init handshake delivered the ready event; the fake recorded the
		// init message's dim + scale.
		expect(FakeSemanticWorker.last).not.toBeNull();

		// encodeQuery → Float32Array of the right dimensionality.
		const qv = await worker.encodeQuery('memory consolidation');
		expect(qv).toBeInstanceOf(Float32Array);
		expect(qv.length).toBe(DIM);

		// bruteForceCluster → string ids on the wire become bigint.
		const hits = await worker.bruteForceCluster(2, qv, 3);
		expect(hits.map((h) => h.id)).toEqual([100n, 101n]);
		expect(typeof hits[0].id).toBe('bigint');

		// rerank likewise bigint-converts.
		const reranked = await worker.rerank([{ id: 100n, cluster_id: 2 }], qv);
		expect(reranked[0].id).toBe(100n);

		// load/evict resolve void.
		await expect(
			worker.loadCluster(2, new Int8Array(DIM * 2), new BigInt64Array([100n, 101n]))
		).resolves.toBeUndefined();
		await expect(worker.evictCluster(2)).resolves.toBeUndefined();
	});

	it('correlates concurrent encode-query replies by id', async () => {
		const worker = await defaultSemanticWorker({ dim: DIM, scale: 1 });
		const [a, b] = await Promise.all([
			worker.encodeQuery('one'),
			worker.encodeQuery('two')
		]);
		expect(a.length).toBe(DIM);
		expect(b.length).toBe(DIM);
	});

	it('an id-targeted worker error rejects only that pending call', async () => {
		const worker = await defaultSemanticWorker({ dim: DIM, scale: 1 });
		FakeSemanticWorker.last!.failNextEncodeWith = 'cluster_not_loaded';
		await expect(worker.encodeQuery('boom')).rejects.toThrow(/cluster_not_loaded/);
		// A subsequent call still works (the adapter didn't tear down).
		const qv = await worker.encodeQuery('recover');
		expect(qv.length).toBe(DIM);
	});

	it('a global (no-id) worker error rejects all in-flight calls', async () => {
		const worker = await defaultSemanticWorker({ dim: DIM, scale: 1 });
		FakeSemanticWorker.last!.emitGlobalError = 'worker crashed';
		await expect(worker.encodeQuery('hang?')).rejects.toThrow(/worker crashed/);
	});
});

describe('NeuroscapeRanker — drift detection (T015, R-010 / INV-006)', () => {
	it('worker.encodeQuery throwing surfaces via onError + ranker state goes error', async () => {
		const cfg = makeBaseCfg({
			worker: {
				...makeBaseCfg().worker,
				encodeQuery: vi.fn(async () => {
					// Simulates the drift handshake failure: the worker
					// detected its loaded model_sha256 doesn't match the
					// manifest's pinned value and refuses to encode.
					throw new Error('VectorsManifestDriftError: model_sha256 mismatch');
				})
			} as WorkerLike
		});
		const r = new NeuroscapeRanker(cfg);
		const errors: Error[] = [];
		const states: string[] = [];
		await expect(
			r.searchNeuroscape(parsedFromText('memory'), 5, {
				onError: (e) => errors.push(e),
				onState: (s) => states.push(s)
			})
		).rejects.toThrow(/model_sha256 mismatch/);
		expect(errors.length).toBe(1);
		expect(states[states.length - 1]).toBe('error');
	});
});
