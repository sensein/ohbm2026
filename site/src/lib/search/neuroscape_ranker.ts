/**
 * Spec 019 — NeuroScape semantic ranking pipeline.
 *
 * 5-step pipeline (contracts/search-ranking-pipeline.md §3):
 *
 *   1. Embed query (via the semantic.worker.ts)
 *   2. Route to closest cluster centroid (in-memory; centroids load
 *      eagerly with neuroscape.parquet)
 *   3. Range-fetch the closest cluster's vectors from
 *      neuroscape_vectors.parquet via hyparquet asyncBufferFromUrl +
 *      predicate pushdown (cluster_id == X)
 *   4. Brute-force cosine within that one cluster → top-3 seeds
 *   5. KNN-expand from those seeds via the k=20 graph already in
 *      neuroscape.parquet → candidate set, re-ranked by cosine
 *
 * LRU cap on the in-memory cluster cache per FR-024 (default 4
 * distinct clusters per session); a 5th cluster triggers
 * onCapExceeded.
 *
 * Drift gate (R-010 / INV-006): the worker init handshake compares the
 * loaded model file's sha256 against the manifest's pinned value;
 * mismatch raises VectorsManifestDriftError.
 *
 * The worker is injected via the `WorkerLike` interface so unit tests
 * can mock it (see site/src/tests/unit/neuroscape_ranker.test.ts).
 * Production callers use the default lazy-loaded
 * `defaultSemanticWorker()` factory.
 */
import type { ParsedQuery } from '$lib/filter';

export type Corpus = 'neuroscape' | 'ohbm2026';

export type RankedHit = {
	corpus: Corpus;
	id: bigint;
	cluster_id: number | null;
	cosine: number;
	score_source: 'cosine' | 'knn-distance';
};

export type RankerState =
	| 'idle'
	| 'loading-model'
	| 'embedding'
	| 'routing'
	| 'fetching-vectors'
	| 'brute-force'
	| 'knn-expand'
	| 're-rank'
	| 'ready'
	| 'cap-exceeded'
	| 'error';

export interface RankerHooks {
	onState?: (state: RankerState) => void;
	onCapExceeded?: (clustersLoaded: number) => void;
	onError?: (err: Error) => void;
}

/** Abstract worker contract — both the real semantic.worker.ts and the
 *  vitest mock implement this. */
export interface WorkerLike {
	encodeQuery(query: string): Promise<Float32Array>;
	bruteForceCluster(
		clusterId: number,
		queryVector: Float32Array,
		topK: number
	): Promise<Array<{ id: bigint; cosine: number }>>;
	rerank(
		candidates: Array<{ id: bigint; cluster_id: number }>,
		queryVector: Float32Array
	): Promise<Array<{ id: bigint; cosine: number }>>;
	loadCluster(clusterId: number, vectors: Int8Array, pubmedIds: BigInt64Array): Promise<void>;
	evictCluster(clusterId: number): Promise<void>;
}

/** Browser-side range-fetch helper signature (implemented by
 *  $lib/data_package/loader.loadClusterVectors). Allows the ranker
 *  to be tested in isolation from the parquet IO. */
export type ClusterVectorsFetcher = (clusterId: number) => Promise<{
	pubmed_ids: BigInt64Array;
	vectors: Int8Array;
}>;

/** Centroid table shape (from data/neuroscape/clusters.json's
 *  cluster_centroids entry — produced by the loader). */
export interface ClusterCentroidEntry {
	cluster_id: number;
	centroid_vector: Float32Array;
}

/** k-NN graph entry per article (from data/neuroscape/neighbors.json). */
export interface KnnEntry {
	pubmed_id: bigint;
	nearest_pubmed_ids: bigint[];
	nearest_distances: number[];
}

export interface RankerConfig {
	worker: WorkerLike;
	fetchClusterVectors: ClusterVectorsFetcher;
	centroids: ClusterCentroidEntry[];
	/** Map from pubmed_id → cluster_id for every article in the corpus.
	 *  Built once by the loader from neuroscape.parquet's articles
	 *  table. */
	pubmedToCluster: Map<bigint, number>;
	/** Map from pubmed_id → KnnEntry for every article. Built once from
	 *  neuroscape.parquet's neighbors table. */
	knnIndex: Map<bigint, KnnEntry>;
	/** Default 4 per FR-024. */
	clusterCap?: number;
}

const DEFAULT_CLUSTER_CAP = 4;
const TOP_K_SEEDS = 3;
const MIN_QUERY_CHARS = 3;

// Module-level state — each browser session has one ranker, so we
// keep the LRU + cap-released flag + state-machine here. (In a multi-
// tab environment each tab has its own worker, so this is per-tab.)
class NeuroscapeRanker {
	private cfg: RankerConfig;
	private clusterLru: Set<number> = new Set();
	private capReleased = false;
	private state: RankerState = 'idle';

	constructor(cfg: RankerConfig) {
		this.cfg = cfg;
	}

	get clusterCap(): number {
		return this.cfg.clusterCap ?? DEFAULT_CLUSTER_CAP;
	}

	private setState(s: RankerState, hooks?: RankerHooks) {
		this.state = s;
		hooks?.onState?.(s);
	}

	/** Public for tests + the FR-024 "Expand search depth?" affordance. */
	expandSearchDepth(): void {
		this.capReleased = true;
	}

	private routeToCluster(queryVector: Float32Array): number {
		// Dense argmax over the ~50 centroids; trivially cheap.
		let bestId = this.cfg.centroids[0]?.cluster_id ?? 0;
		let bestScore = -Infinity;
		for (const c of this.cfg.centroids) {
			let s = 0;
			for (let i = 0; i < queryVector.length; i++) {
				s += queryVector[i] * c.centroid_vector[i];
			}
			if (s > bestScore) {
				bestScore = s;
				bestId = c.cluster_id;
			}
		}
		return bestId;
	}

	private async ensureClusterLoaded(
		clusterId: number,
		hooks?: RankerHooks
	): Promise<'loaded' | 'cap-exceeded'> {
		if (this.clusterLru.has(clusterId)) {
			// Move-to-front on access.
			this.clusterLru.delete(clusterId);
			this.clusterLru.add(clusterId);
			return 'loaded';
		}
		// FR-024 cap check.
		if (!this.capReleased && this.clusterLru.size >= this.clusterCap) {
			hooks?.onCapExceeded?.(this.clusterLru.size);
			return 'cap-exceeded';
		}
		// Range-fetch + load into worker.
		const { pubmed_ids, vectors } = await this.cfg.fetchClusterVectors(clusterId);
		await this.cfg.worker.loadCluster(clusterId, vectors, pubmed_ids);
		this.clusterLru.add(clusterId);
		// LRU eviction if we're now over cap (after a cap release).
		while (this.clusterLru.size > this.clusterCap + 8) {
			const oldest = this.clusterLru.values().next().value as number | undefined;
			if (oldest === undefined) break;
			this.clusterLru.delete(oldest);
			await this.cfg.worker.evictCluster(oldest);
		}
		return 'loaded';
	}

	private knnExpandFromSeeds(seeds: Array<{ id: bigint; cosine: number }>): Set<bigint> {
		const out = new Set<bigint>();
		for (const seed of seeds) {
			out.add(seed.id);
			const knn = this.cfg.knnIndex.get(seed.id);
			if (!knn) continue;
			for (const nb of knn.nearest_pubmed_ids) {
				out.add(nb);
			}
		}
		return out;
	}

	async searchNeuroscape(
		parsed: ParsedQuery,
		topK: number,
		hooks?: RankerHooks
	): Promise<RankedHit[]> {
		try {
			// Step 0: extract operator-stripped string for semantic
			// encoding. The parsed query carries the structural
			// clauses; the encoder gets the plain word/phrase content.
			const queryText = parsedToEncodableString(parsed);
			if (queryText.length < MIN_QUERY_CHARS) {
				// FR-010 min-char threshold — skip worker round-trip.
				this.setState('ready', hooks);
				return [];
			}

			// Step 1: embed.
			this.setState('embedding', hooks);
			const qv = await this.cfg.worker.encodeQuery(queryText);

			// Step 2: route.
			this.setState('routing', hooks);
			const routedCluster = this.routeToCluster(qv);

			// Step 3: ensure cluster vectors loaded.
			this.setState('fetching-vectors', hooks);
			const loadStatus = await this.ensureClusterLoaded(routedCluster, hooks);
			if (loadStatus === 'cap-exceeded') {
				this.setState('cap-exceeded', hooks);
				return [];
			}

			// Step 4: brute-force top-3 within cluster.
			this.setState('brute-force', hooks);
			const seeds = await this.cfg.worker.bruteForceCluster(routedCluster, qv, TOP_K_SEEDS);

			// Step 5: KNN-expand.
			this.setState('knn-expand', hooks);
			const candidates = this.knnExpandFromSeeds(seeds);
			const candidateList: Array<{ id: bigint; cluster_id: number }> = [];
			const knnDistanceFallback: Map<bigint, number> = new Map();
			let capHit = false;
			for (const id of candidates) {
				const cid = this.cfg.pubmedToCluster.get(id);
				if (cid === undefined) continue;
				// Ensure this neighbour's cluster is loaded for re-ranking,
				// subject to FR-024 cap.
				const status = await this.ensureClusterLoaded(cid, hooks);
				if (status === 'cap-exceeded') {
					capHit = true;
					// Record a KNN-distance fallback score for this row;
					// we'll still surface it but with score_source='knn-distance'.
					for (const seed of seeds) {
						const knn = this.cfg.knnIndex.get(seed.id);
						if (!knn) continue;
						const idx = knn.nearest_pubmed_ids.indexOf(id);
						if (idx >= 0) {
							knnDistanceFallback.set(id, 1 - knn.nearest_distances[idx]);
							break;
						}
					}
				}
				candidateList.push({ id, cluster_id: cid });
			}

			// Step 6: re-rank.
			this.setState('re-rank', hooks);
			const cosineScored = await this.cfg.worker.rerank(
				candidateList.filter((c) => !knnDistanceFallback.has(c.id)),
				qv
			);
			const result: RankedHit[] = cosineScored
				.map((s) => ({
					corpus: 'neuroscape' as Corpus,
					id: s.id,
					cluster_id: this.cfg.pubmedToCluster.get(s.id) ?? null,
					cosine: s.cosine,
					score_source: 'cosine' as const
				}))
				.concat(
					Array.from(knnDistanceFallback.entries()).map(([id, score]) => ({
						corpus: 'neuroscape' as Corpus,
						id,
						cluster_id: this.cfg.pubmedToCluster.get(id) ?? null,
						cosine: score,
						score_source: 'knn-distance' as const
					}))
				)
				.sort((a, b) => b.cosine - a.cosine)
				.slice(0, topK);

			this.setState('ready', hooks);
			void capHit; // surfaced via onCapExceeded already
			return result;
		} catch (err) {
			this.setState('error', hooks);
			hooks?.onError?.(err as Error);
			throw err;
		}
	}
}

let _ranker: NeuroscapeRanker | null = null;

/** Module-singleton initialisation. Production callers invoke this
 *  once during the loader's data-package wiring; tests construct a
 *  fresh NeuroscapeRanker directly via the exported class. */
export function initRanker(cfg: RankerConfig): void {
	_ranker = new NeuroscapeRanker(cfg);
}

export function searchNeuroscape(
	parsed: ParsedQuery,
	topK: number,
	hooks?: RankerHooks
): Promise<RankedHit[]> {
	if (!_ranker) throw new Error('neuroscape ranker not initialised — call initRanker() first');
	return _ranker.searchNeuroscape(parsed, topK, hooks);
}

export function expandSearchDepth(): void {
	_ranker?.expandSearchDepth();
}

/** Exported for tests. */
export { NeuroscapeRanker };

/** Turn a ParsedQuery back into an operator-stripped string the
 *  worker's encoder can embed. Mirrors the existing
 *  $lib/filter::queryForSemantic path so semantic vs. lexical
 *  treatment of the same query is consistent. */
function parsedToEncodableString(parsed: ParsedQuery): string {
	const tokens: string[] = [];
	for (const group of parsed.groups) {
		for (const clause of group.clauses) {
			if (clause.negate) continue; // negations exclude — not encoded
			if (clause.kind === 'word') {
				tokens.push(clause.word);
			} else {
				tokens.push(clause.words.join(' '));
			}
		}
	}
	return tokens.join(' ').trim();
}
