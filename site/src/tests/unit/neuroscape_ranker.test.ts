/**
 * Spec 019 / T013-T015 — NeuroScape ranker unit tests.
 *
 * Mocks the worker + range-fetch helpers so the 5-step pipeline can be
 * exercised without spinning up Web Workers or fetching real parquet
 * data. Each test injects canned worker responses + asserts ranker
 * orchestration behaviour.
 */
import { describe, expect, it, vi } from 'vitest';
import {
	NeuroscapeRanker,
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
			rerank: vi.fn(async (candidates) =>
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

describe('NeuroscapeRanker — cluster cap (T014, FR-024)', () => {
	it('5th distinct cluster route triggers onCapExceeded and skips fetch', async () => {
		const centroids = [
			{ cluster_id: 0, centroid_vector: new Float32Array([1, 0, 0, 0]) },
			{ cluster_id: 1, centroid_vector: new Float32Array([0, 1, 0, 0]) },
			{ cluster_id: 2, centroid_vector: new Float32Array([0, 0, 1, 0]) },
			{ cluster_id: 3, centroid_vector: new Float32Array([0, 0, 0, 1]) },
			{
				cluster_id: 4,
				centroid_vector: new Float32Array([0.5, 0.5, 0.5, 0.5])
			}
		];
		const fetched: number[] = [];
		const cfg = makeBaseCfg({
			clusterCap: 4,
			centroids,
			fetchClusterVectors: vi.fn(async (clusterId: number) => {
				fetched.push(clusterId);
				return {
					pubmed_ids: new BigInt64Array([]),
					vectors: new Int8Array(0)
				};
			})
		});
		const r = new NeuroscapeRanker(cfg);

		// Drive 4 distinct cluster routes (fills LRU to cap).
		for (let i = 0; i < 4; i++) {
			cfg.worker.encodeQuery = vi.fn(async () => {
				const v = new Float32Array([0, 0, 0, 0]);
				v[i] = 1;
				return v;
			});
			await r.searchNeuroscape(parsedFromText(`topic ${i}`), 5);
		}
		expect(fetched).toEqual([0, 1, 2, 3]);

		// 5th route → cluster 4 — should hit the cap.
		const capCalls: number[] = [];
		const hooks: RankerHooks = { onCapExceeded: (n) => capCalls.push(n) };
		cfg.worker.encodeQuery = vi.fn(async () => new Float32Array([0.5, 0.5, 0.5, 0.5]));
		const hits = await r.searchNeuroscape(parsedFromText('topic four'), 5, hooks);
		expect(capCalls.length).toBeGreaterThan(0);
		expect(capCalls[0]).toBe(4);
		expect(hits).toEqual([]); // capped path returns empty per the contract
	});

	it('expandSearchDepth() releases the cap; next query fetches', async () => {
		const fetched: number[] = [];
		const cfg = makeBaseCfg({
			clusterCap: 1,
			fetchClusterVectors: vi.fn(async (clusterId: number) => {
				fetched.push(clusterId);
				return {
					pubmed_ids: new BigInt64Array([]),
					vectors: new Int8Array(0)
				};
			})
		});
		const r = new NeuroscapeRanker(cfg);
		cfg.worker.encodeQuery = vi.fn(async () => new Float32Array([1, 0, 0, 0]));
		await r.searchNeuroscape(parsedFromText('first'), 5);
		expect(fetched).toEqual([0]);

		// Route to cluster 1 next — would hit cap.
		cfg.worker.encodeQuery = vi.fn(async () => new Float32Array([0, 1, 0, 0]));
		const capCalls: number[] = [];
		await r.searchNeuroscape(parsedFromText('second'), 5, {
			onCapExceeded: (n) => capCalls.push(n)
		});
		expect(capCalls.length).toBe(1);

		// Release + retry.
		r.expandSearchDepth();
		await r.searchNeuroscape(parsedFromText('second'), 5);
		expect(fetched).toContain(1);
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
