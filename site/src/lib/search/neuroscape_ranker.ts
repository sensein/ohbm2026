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
	/** Cosine-distance relevance horizon for the cluster sweep (default 0.8).
	 *  Once a swept cluster's best hit exceeds this, the nearest-first sweep
	 *  stops — far/irrelevant clusters are never fetched. Mirrors the caller's
	 *  SEMANTIC_MAX_DISTANCE. */
	maxDistance?: number;
}

const DEFAULT_CLUSTER_CAP = 4;
const TOP_K_SEEDS = 3;
const MIN_QUERY_CHARS = 3;
// Cosine-distance relevance horizon for the progressive sweep — mirrors the
// caller's SEMANTIC_MAX_DISTANCE. Once a cluster's best hit exceeds this, the
// (nearest-first) sweep stops.
const DEFAULT_MAX_DISTANCE = 0.8;
// How many clusters we keep resident beyond the per-query fetch budget so
// that consecutive queries about adjacent topics reuse warm clusters (LRU
// cache hit → no re-fetch) instead of re-ranging the sidecar each time.
const RESIDENT_SLACK = 8;

// Module-level state — each browser session has one ranker, so we
// keep the LRU + cap-released flag + state-machine here. (In a multi-
// tab environment each tab has its own worker, so this is per-tab.)
class NeuroscapeRanker {
	private cfg: RankerConfig;
	private clusterLru: Set<number> = new Set();
	private capReleased = false;
	private state: RankerState = 'idle';
	// FR-024 cost bound is PER QUERY, not per session: each query may
	// range-fetch at most `clusterCap` *new* clusters from the sidecar
	// (~one cluster's INT8 vectors each). Resident clusters from earlier
	// queries are reused for free and don't count. Reset at the start of
	// every searchNeuroscape so a fresh query's routing cluster always
	// loads — a session-scoped cap would let one query's KNN-expansion
	// exhaust the budget and starve every subsequent query's routing
	// cluster (→ empty results).
	private clustersFetchedThisQuery = 0;

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

	/**
	 * Replace the corpus lookup maps WITHOUT recreating the worker or losing
	 * the warm cluster LRU. Used as the full corpus + its k=20 neighbour graph
	 * stream in after first paint: the ranker is initialised early (so semantic
	 * search works ASAP) with whatever corpus slice is resident, then its maps
	 * are upgraded in place once the full `listCorpus` + `neighbors_neuroscape`
	 * land. The maps MUST be derived from the full corpus, never the displayed
	 * LOD scatter (search must not depend on what the UMAP renders).
	 */
	updateMaps(maps: {
		pubmedToCluster?: Map<bigint, number>;
		knnIndex?: Map<bigint, KnnEntry>;
	}): void {
		if (maps.pubmedToCluster) this.cfg.pubmedToCluster = maps.pubmedToCluster;
		if (maps.knnIndex) this.cfg.knnIndex = maps.knnIndex;
	}

	private rankClusters(queryVector: Float32Array): Array<{ cluster_id: number; sim: number }> {
		// Dense cosine-similarity score for every centroid (~175 dot products,
		// trivially cheap), sorted descending → the nearest-first order the
		// progressive sweep visits. Replaces single-cluster argmax routing.
		const scored = this.cfg.centroids.map((c) => {
			let s = 0;
			for (let i = 0; i < queryVector.length; i++) {
				s += queryVector[i] * c.centroid_vector[i];
			}
			return { cluster_id: c.cluster_id, sim: s };
		});
		scored.sort((a, b) => b.sim - a.sim);
		return scored;
	}

	private async ensureClusterLoaded(
		clusterId: number,
		hooks?: RankerHooks
	): Promise<'loaded' | 'cap-exceeded'> {
		if (this.clusterLru.has(clusterId)) {
			// Move-to-front on access — LRU cache hit, no fetch, free.
			this.clusterLru.delete(clusterId);
			this.clusterLru.add(clusterId);
			return 'loaded';
		}
		// FR-024 PER-QUERY fetch budget. A non-resident cluster costs one
		// range-fetch; cap how many of those a single query incurs. The
		// counter resets each searchNeuroscape, so the routing cluster of a
		// fresh query is always within budget (counter starts at 0) and
		// never gets starved by a previous query's expansion.
		if (!this.capReleased && this.clustersFetchedThisQuery >= this.clusterCap) {
			hooks?.onCapExceeded?.(this.clustersFetchedThisQuery);
			return 'cap-exceeded';
		}
		// Range-fetch + load into worker.
		const { pubmed_ids, vectors } = await this.cfg.fetchClusterVectors(clusterId);
		await this.cfg.worker.loadCluster(clusterId, vectors, pubmed_ids);
		this.clusterLru.add(clusterId);
		this.clustersFetchedThisQuery++;
		// Bound resident memory across queries: evict LRU-oldest clusters
		// beyond the budget + slack. Never evict the cluster we just loaded
		// (it's needed for this query's brute-force / re-rank).
		while (this.clusterLru.size > this.clusterCap + RESIDENT_SLACK) {
			const oldest = this.clusterLru.values().next().value as number | undefined;
			if (oldest === undefined || oldest === clusterId) break;
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
			// Reset the per-query fetch budget so this query's routing
			// cluster always loads regardless of how many clusters earlier
			// queries pulled in (FR-024 is a per-query egress bound).
			this.clustersFetchedThisQuery = 0;
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

			// Step 2: rank ALL centroids by similarity → nearest-first sweep order.
			this.setState('routing', hooks);
			const rankedClusters = this.rankClusters(qv);

			// Steps 3-4: relevance-bounded progressive sweep. Visit clusters
			// nearest-first, brute-forcing seeds in each, and STOP at the
			// relevance horizon — once a cluster's best hit falls beyond the
			// distance threshold, less-similar clusters (visited later) cannot
			// beat it, so there's no need to fetch them. This replaces routing to
			// a SINGLE cluster, which could never reach a relevant article in a
			// neighbouring cluster (the non-exhaustiveness gap). The per-query
			// FR-024 fetch cap (ensureClusterLoaded) bounds bandwidth; "Expand
			// search depth" lifts it. Step 5's KNN-expansion then reaches near
			// cross-cluster neighbours cheaply via the graph, without fetching
			// their vectors.
			this.setState('fetching-vectors', hooks);
			const maxDistance = this.cfg.maxDistance ?? DEFAULT_MAX_DISTANCE;
			// Per-cluster seed budget: with no KNN graph resident (atlas-root) the
			// brute-force IS the candidate set, so pull topK from each swept
			// cluster; with a graph, a smaller per-cluster slice seeds the
			// cross-cluster KNN expansion.
			const perCluster =
				this.cfg.knnIndex.size === 0
					? Math.max(topK, TOP_K_SEEDS)
					: Math.max(TOP_K_SEEDS, Math.ceil(topK / 4));
			const seeds: Array<{ id: bigint; cosine: number }> = [];
			// Seeds carry their OWN cluster (we just brute-forced them from it), so
			// they resolve below even when pubmedToCluster omits them (atlas-root's
			// sparse map — the regression #59 first patched; now structural).
			const seedClusterById = new Map<bigint, number>();
			for (const { cluster_id } of rankedClusters) {
				const status = await this.ensureClusterLoaded(cluster_id, hooks);
				if (status === 'cap-exceeded') {
					// Bandwidth cap reached. If nothing gathered yet (first cluster
					// already over budget) surface cap-exceeded; else keep what we
					// have and stop sweeping.
					if (seeds.length === 0) {
						this.setState('cap-exceeded', hooks);
						return [];
					}
					break;
				}
				this.setState('brute-force', hooks);
				const hits = await this.cfg.worker.bruteForceCluster(cluster_id, qv, perCluster);
				for (const h of hits) {
					if (!seedClusterById.has(h.id)) {
						seeds.push(h);
						seedClusterById.set(h.id, cluster_id);
					}
				}
				// Relevance horizon (user directive): stop once semantic distance
				// crosses the threshold — don't visit very far clusters.
				const bestCosine = hits.reduce((m, h) => Math.max(m, h.cosine), -1);
				if (1 - bestCosine > maxDistance) break;
			}
			if (seeds.length === 0) {
				this.setState('ready', hooks);
				return [];
			}

			// Step 5: KNN-expand.
			this.setState('knn-expand', hooks);
			const candidates = this.knnExpandFromSeeds(seeds);
			const candidateList: Array<{ id: bigint; cluster_id: number }> = [];
			const knnDistanceFallback: Map<bigint, number> = new Map();
			for (const id of candidates) {
				const cid = this.cfg.pubmedToCluster.get(id) ?? seedClusterById.get(id);
				if (cid === undefined) continue;
				// Ensure this neighbour's cluster is loaded for re-ranking,
				// subject to FR-024 cap. The cap-exceeded signal itself
				// is surfaced via onCapExceeded inside ensureClusterLoaded;
				// here we just route un-loaded candidates to the KNN-
				// distance fallback path so they still appear in the result
				// list (FR-024 fallback contract).
				const status = await this.ensureClusterLoaded(cid, hooks);
				if (status === 'cap-exceeded') {
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
			const cosineHits: RankedHit[] = cosineScored.map((s) => ({
				corpus: 'neuroscape' as Corpus,
				id: s.id,
				cluster_id: this.cfg.pubmedToCluster.get(s.id) ?? null,
				cosine: s.cosine,
				score_source: 'cosine'
			}));
			const knnHits: RankedHit[] = Array.from(knnDistanceFallback.entries()).map(
				([id, score]) => ({
					corpus: 'neuroscape' as Corpus,
					id,
					cluster_id: this.cfg.pubmedToCluster.get(id) ?? null,
					cosine: score,
					score_source: 'knn-distance'
				})
			);
			const result: RankedHit[] = [...cosineHits, ...knnHits]
				.sort((a, b) => b.cosine - a.cosine)
				.slice(0, topK);

			this.setState('ready', hooks);
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

/** Upgrade the ranker's corpus maps in place (no worker/LRU reset). No-op
 *  before initRanker. See {@link NeuroscapeRanker.updateMaps}. */
export function updateRankerMaps(maps: {
	pubmedToCluster?: Map<bigint, number>;
	knnIndex?: Map<bigint, KnnEntry>;
}): void {
	_ranker?.updateMaps(maps);
}

/** Exported for tests. */
export { NeuroscapeRanker };

// ── Default production worker adapter ────────────────────────────────
//
// Bridges the abstract `WorkerLike` (bigint ids, Float32Array vectors)
// to the concrete semantic.worker.ts postMessage protocol (string ids
// on the wire, ArrayBuffer payloads). The worker is constructed INSIDE
// the factory (not at module top level) so vitest's node import of this
// module doesn't try to spin up a Worker.

type PendingResolver = { resolve: (v: unknown) => void; reject: (e: Error) => void };

/** Return a transferable ArrayBuffer that exactly spans the typed
 *  array. Avoids shipping a larger backing buffer (or a wrong-offset
 *  view) to the worker, which reconstructs the typed array over the
 *  whole buffer. */
function wholeBuffer(arr: ArrayBufferView): ArrayBuffer {
	if (arr.byteOffset === 0 && arr.byteLength === arr.buffer.byteLength) {
		return arr.buffer as ArrayBuffer;
	}
	return arr.buffer.slice(arr.byteOffset, arr.byteOffset + arr.byteLength) as ArrayBuffer;
}

/** Lazily construct + init the real semantic worker in NeuroScape mode
 *  and expose it through the `WorkerLike` contract. Resolves once the
 *  worker has loaded the model and posted `ready`. */
export async function defaultSemanticWorker(opts: {
	dim: number;
	scale: number;
}): Promise<WorkerLike> {
	const worker = new Worker(new URL('../workers/semantic.worker.ts', import.meta.url), {
		type: 'module'
	});

	// init handshake — independent listeners so an init crash rejects
	// instead of hanging.
	await new Promise<void>((resolve, reject) => {
		const onMsg = (e: MessageEvent) => {
			if ((e.data as { type?: string })?.type === 'ready') {
				cleanup();
				resolve();
			}
		};
		const onErr = (e: Event) => {
			cleanup();
			reject(new Error(`semantic worker init failed: ${(e as ErrorEvent).message ?? 'unknown'}`));
		};
		const cleanup = () => {
			worker.removeEventListener('message', onMsg);
			worker.removeEventListener('error', onErr);
		};
		worker.addEventListener('message', onMsg);
		worker.addEventListener('error', onErr);
		worker.postMessage({ type: 'init', corpus: 'neuroscape', dim: opts.dim, scale: opts.scale });
	});

	const pending = new Map<string, PendingResolver>();
	let counter = 0;
	const nextId = () => `q${counter++}`;

	const rejectAll = (err: Error) => {
		for (const [, p] of pending) p.reject(err);
		pending.clear();
	};

	worker.addEventListener('message', (e: MessageEvent) => {
		const msg = e.data as {
			type: string;
			id?: string;
			cluster_id?: number;
			query_vector?: ArrayBuffer;
			hits?: Array<{ id: string; cosine: number }>;
			reason?: string;
			message?: string;
		};
		switch (msg.type) {
			case 'query-encoded': {
				const p = pending.get(`enc:${msg.id}`);
				if (p) {
					pending.delete(`enc:${msg.id}`);
					p.resolve(new Float32Array(msg.query_vector as ArrayBuffer));
				}
				return;
			}
			case 'brute-force-hits': {
				const p = pending.get(`bf:${msg.id}`);
				if (p) {
					pending.delete(`bf:${msg.id}`);
					p.resolve(msg.hits ?? []);
				}
				return;
			}
			case 'reranked': {
				const p = pending.get(`rr:${msg.id}`);
				if (p) {
					pending.delete(`rr:${msg.id}`);
					p.resolve(msg.hits ?? []);
				}
				return;
			}
			case 'cluster-loaded': {
				const p = pending.get(`load:${msg.cluster_id}`);
				if (p) {
					pending.delete(`load:${msg.cluster_id}`);
					p.resolve(undefined);
				}
				return;
			}
			case 'cluster-evicted': {
				const p = pending.get(`evict:${msg.cluster_id}`);
				if (p) {
					pending.delete(`evict:${msg.cluster_id}`);
					p.resolve(undefined);
				}
				return;
			}
			case 'error': {
				const detail = msg.reason ?? msg.message ?? 'unknown';
				// Targeted error: a brute-force against an unloaded cluster
				// carries the request id. Reject just that promise.
				if (typeof msg.id === 'string') {
					for (const prefix of ['bf', 'enc', 'rr']) {
						const key = `${prefix}:${msg.id}`;
						const p = pending.get(key);
						if (p) {
							pending.delete(key);
							p.reject(new Error(`semantic worker error: ${detail}`));
							return;
						}
					}
				}
				// Global (no-id) error — reject everything so callers don't
				// hang awaiting a reply that will never come.
				rejectAll(new Error(`semantic worker error: ${detail}`));
				return;
			}
		}
	});
	worker.addEventListener('error', (e: Event) => {
		rejectAll(new Error(`semantic worker crashed: ${(e as ErrorEvent).message ?? 'unknown'}`));
	});

	return {
		encodeQuery(query: string): Promise<Float32Array> {
			const id = nextId();
			return new Promise<Float32Array>((resolve, reject) => {
				pending.set(`enc:${id}`, { resolve: resolve as (v: unknown) => void, reject });
				worker.postMessage({ type: 'encode-query', query, id });
			});
		},
		bruteForceCluster(clusterId, queryVector, topK) {
			const id = nextId();
			// COPY the query vector — it's reused across brute-force +
			// rerank in one search, so we must not transfer (neuter) it.
			const buf = queryVector.slice().buffer;
			return new Promise<Array<{ id: bigint; cosine: number }>>((resolve, reject) => {
				pending.set(`bf:${id}`, {
					resolve: (v) =>
						resolve(
							(v as Array<{ id: string; cosine: number }>).map((h) => ({
								id: BigInt(h.id),
								cosine: h.cosine
							}))
						),
					reject
				});
				worker.postMessage(
					{ type: 'brute-force', cluster_id: clusterId, query_vector: buf, topK, id },
					[buf]
				);
			});
		},
		rerank(candidates, queryVector) {
			const id = nextId();
			const buf = queryVector.slice().buffer;
			const wire = candidates.map((c) => ({ id: c.id.toString(), cluster_id: c.cluster_id }));
			return new Promise<Array<{ id: bigint; cosine: number }>>((resolve, reject) => {
				pending.set(`rr:${id}`, {
					resolve: (v) =>
						resolve(
							(v as Array<{ id: string; cosine: number }>).map((h) => ({
								id: BigInt(h.id),
								cosine: h.cosine
							}))
						),
					reject
				});
				worker.postMessage({ type: 'rerank', candidates: wire, query_vector: buf, id }, [buf]);
			});
		},
		loadCluster(clusterId, vectors, pubmedIds) {
			// TRANSFER the cluster buffers — single-use, freshly decoded
			// from the parquet by the loader.
			const vBuf = wholeBuffer(vectors);
			const pBuf = wholeBuffer(pubmedIds);
			return new Promise<void>((resolve, reject) => {
				pending.set(`load:${clusterId}`, { resolve: () => resolve(), reject });
				worker.postMessage(
					{ type: 'load-cluster', cluster_id: clusterId, vectors: vBuf, pubmedIds: pBuf },
					[vBuf, pBuf]
				);
			});
		},
		evictCluster(clusterId) {
			return new Promise<void>((resolve, reject) => {
				pending.set(`evict:${clusterId}`, { resolve: () => resolve(), reject });
				worker.postMessage({ type: 'evict-cluster', cluster_id: clusterId });
			});
		}
	};
}

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
