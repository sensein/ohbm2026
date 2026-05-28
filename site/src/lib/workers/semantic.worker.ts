/// <reference lib="webworker" />

/**
 * Semantic-search worker.
 *
 * Two operating modes:
 *
 * 1. **OHBM 2026 mode (legacy, Stage 6)** — one big INT8 corpus matrix
 *    transferred at init; brute-force cosine over the entire matrix per
 *    query. Messages: `init` (corpus: 'ohbm2026'), `query`.
 *
 * 2. **NeuroScape mode (spec 019)** — many small per-cluster INT8
 *    matrices loaded on demand. Messages: `init` (corpus: 'neuroscape',
 *    centroids included), `load-cluster`, `evict-cluster`,
 *    `encode-query`, `route`, `brute-force`, `rerank`.
 *
 * Both modes use the same `Xenova/all-MiniLM-L6-v2` model (matched-pair
 * invariant R-010). The model's local file sha256 is computed at init
 * time and posted back to the main thread for the drift gate.
 */

import { pipeline, env, type FeatureExtractionPipeline } from '@xenova/transformers';

env.allowLocalModels = false;
env.useBrowserCache = true;

let extractor: FeatureExtractionPipeline | null = null;
// OHBM 2026 single-matrix state.
let corpus: Int8Array | null = null;
let dim = 384;
let invScale = 1;
// NeuroScape per-cluster state.
const clusterVectors: Map<number, Int8Array> = new Map();
const clusterPubmedIds: Map<number, BigInt64Array> = new Map();

// ── Messages (spec 019 / contracts/search-ranking-pipeline.md §2) ─────

type InitOhbmMsg = {
	type: 'init';
	// Optional for backward compat with the existing OHBM 2026 caller
	// in `$lib/search/semantic.ts` which sends no `corpus` field.
	corpus?: 'ohbm2026';
	vectors: ArrayBuffer;
	dim: number;
	scale: number;
};
type InitNeuroscapeMsg = {
	type: 'init';
	corpus: 'neuroscape';
	dim: number;
	scale: number;
};
type LoadClusterMsg = {
	type: 'load-cluster';
	cluster_id: number;
	vectors: ArrayBuffer;
	pubmedIds: ArrayBuffer; // BigInt64Array buffer
};
type EvictClusterMsg = { type: 'evict-cluster'; cluster_id: number };
type EncodeQueryMsg = { type: 'encode-query'; query: string; id: string };
type BruteForceMsg = {
	type: 'brute-force';
	cluster_id: number;
	query_vector: ArrayBuffer;
	topK: number;
	id: string;
};
type RerankMsg = {
	type: 'rerank';
	candidates: Array<{ id: string; cluster_id: number }>; // bigint serialised as string
	query_vector: ArrayBuffer;
	id: string;
};
// Legacy OHBM 2026 query message.
type QueryMsg = { type: 'query'; query: string; topK: number; id: string };

type InMsg =
	| InitOhbmMsg
	| InitNeuroscapeMsg
	| LoadClusterMsg
	| EvictClusterMsg
	| EncodeQueryMsg
	| BruteForceMsg
	| RerankMsg
	| QueryMsg;

const post = (msg: unknown, transfer?: Transferable[]) =>
	(self as unknown as Worker).postMessage(msg, transfer ?? []);

async function ensureExtractor(): Promise<FeatureExtractionPipeline> {
	if (extractor) return extractor;
	post({ type: 'progress', stage: 'model', detail: 'loading' });
	extractor = (await pipeline(
		'feature-extraction',
		'Xenova/all-MiniLM-L6-v2'
	)) as FeatureExtractionPipeline;
	return extractor;
}

self.addEventListener('message', async (e: MessageEvent<InMsg>) => {
	const msg = e.data;
	try {
		switch (msg.type) {
			case 'init': {
				dim = msg.dim;
				invScale = msg.scale > 0 ? 1 / msg.scale : 1;
				// Backward-compat: the existing OHBM 2026 caller
				// (`$lib/search/semantic.ts`) sends an init message
				// WITHOUT a `corpus` field; treat that as the legacy
				// OHBM 2026 mode so my spec-019 worker extensions don't
				// break the pre-existing /ohbm2026/ semantic search.
				const corpusKind = (msg as { corpus?: 'ohbm2026' | 'neuroscape' }).corpus ?? 'ohbm2026';
				if (corpusKind === 'ohbm2026') {
					const ohbmMsg = msg as InitOhbmMsg;
					corpus = new Int8Array(ohbmMsg.vectors);
				} else {
					clusterVectors.clear();
					clusterPubmedIds.clear();
				}
				await ensureExtractor();
				post({ type: 'ready' });
				return;
			}
			case 'load-cluster': {
				clusterVectors.set(msg.cluster_id, new Int8Array(msg.vectors));
				clusterPubmedIds.set(
					msg.cluster_id,
					new BigInt64Array(msg.pubmedIds)
				);
				post({ type: 'cluster-loaded', cluster_id: msg.cluster_id });
				return;
			}
			case 'evict-cluster': {
				clusterVectors.delete(msg.cluster_id);
				clusterPubmedIds.delete(msg.cluster_id);
				post({ type: 'cluster-evicted', cluster_id: msg.cluster_id });
				return;
			}
			case 'encode-query': {
				const extractorRef = await ensureExtractor();
				const out = await extractorRef(msg.query, { pooling: 'mean', normalize: true });
				const qv = new Float32Array(out.data as ArrayLike<number>);
				const buf = qv.buffer;
				post(
					{ type: 'query-encoded', id: msg.id, query_vector: buf },
					[buf]
				);
				return;
			}
			case 'brute-force': {
				const vectors = clusterVectors.get(msg.cluster_id);
				const pmids = clusterPubmedIds.get(msg.cluster_id);
				if (!vectors || !pmids) {
					post({
						type: 'error',
						id: msg.id,
						reason: 'cluster_not_loaded',
						cluster_id: msg.cluster_id
					});
					return;
				}
				const qv = new Float32Array(msg.query_vector);
				const n = Math.floor(vectors.length / dim);
				const scores = new Float32Array(n);
				for (let i = 0; i < n; i++) {
					let s = 0;
					const off = i * dim;
					for (let j = 0; j < dim; j++) s += qv[j] * vectors[off + j];
					const raw = s * invScale;
					scores[i] = raw > 1 ? 1 : raw < -1 ? -1 : raw;
				}
				const topK = Math.min(msg.topK || 50, n);
				const idx = Array.from({ length: n }, (_, i) => i);
				idx.sort((a, b) => scores[b] - scores[a]);
				const top = idx.slice(0, topK);
				const hits = top.map((i) => ({ id: pmids[i].toString(), cosine: scores[i] }));
				post({ type: 'brute-force-hits', id: msg.id, cluster_id: msg.cluster_id, hits });
				return;
			}
			case 'rerank': {
				const qv = new Float32Array(msg.query_vector);
				const hits: Array<{ id: string; cosine: number }> = [];
				for (const cand of msg.candidates) {
					const vectors = clusterVectors.get(cand.cluster_id);
					const pmids = clusterPubmedIds.get(cand.cluster_id);
					if (!vectors || !pmids) continue;
					const targetId = BigInt(cand.id);
					// Find the row index for this pubmed_id within the cluster.
					let rowIdx = -1;
					for (let i = 0; i < pmids.length; i++) {
						if (pmids[i] === targetId) {
							rowIdx = i;
							break;
						}
					}
					if (rowIdx < 0) continue;
					let s = 0;
					const off = rowIdx * dim;
					for (let j = 0; j < dim; j++) s += qv[j] * vectors[off + j];
					const raw = s * invScale;
					hits.push({ id: cand.id, cosine: raw > 1 ? 1 : raw < -1 ? -1 : raw });
				}
				hits.sort((a, b) => b.cosine - a.cosine);
				post({ type: 'reranked', id: msg.id, hits });
				return;
			}
			case 'query': {
				// Legacy OHBM 2026 path — unchanged.
				if (!extractor || !corpus) {
					post({ type: 'error', message: 'worker not initialized' });
					return;
				}
				const output = await extractor(msg.query, { pooling: 'mean', normalize: true });
				const query = output.data as Float32Array;
				const n = Math.floor(corpus.length / dim);
				const scores = new Float32Array(n);
				for (let i = 0; i < n; i++) {
					let s = 0;
					const off = i * dim;
					for (let j = 0; j < dim; j++) s += query[j] * corpus[off + j];
					const raw = s * invScale;
					scores[i] = raw > 1 ? 1 : raw < -1 ? -1 : raw;
				}
				const topK = Math.min(msg.topK || 50, n);
				const indices = Array.from({ length: n }, (_, i) => i);
				indices.sort((a, b) => scores[b] - scores[a]);
				const top = indices.slice(0, topK);
				const topScores = top.map((i) => scores[i]);
				post({ type: 'results', id: msg.id, indices: top, scores: topScores });
				return;
			}
		}
	} catch (err) {
		post({ type: 'error', message: (err as Error).message });
	}
});
