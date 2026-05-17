/// <reference lib="webworker" />

/**
 * Semantic-search worker.
 *
 * Boots transformers.js inside a Web Worker (off the main thread), pulls the
 * `Xenova/all-MiniLM-L6-v2` ONNX model from the Hugging Face CDN (~23 MB,
 * one-time download cached by the browser), and answers query messages by:
 *   1. Mean-pooled + L2-normalized embedding of the query text → 384-d float32
 *   2. Cosine similarity against every row of the int8-quantized corpus
 *      matrix (`[N, 384]`) transferred from the main thread on init.
 *   3. Top-K indices (positional → maps to `abstracts.json:abstracts[i]`).
 *
 * Wire protocol:
 *   main → worker: { type: 'init', vectors: Uint8Array, dim, scale }
 *                  { type: 'query', query: string, topK: number, id: string }
 *   worker → main: { type: 'ready' } | { type: 'error', message }
 *                  { type: 'results', id, indices: number[], scores: number[] }
 *                  { type: 'progress', stage: 'model', detail: string }
 */

import { pipeline, env, type FeatureExtractionPipeline } from '@xenova/transformers';

// Disable local-model lookups; we always pull from the Hugging Face CDN.
env.allowLocalModels = false;
env.useBrowserCache = true;

let extractor: FeatureExtractionPipeline | null = null;
let corpus: Int8Array | null = null;
let dim = 384;

type InitMsg = { type: 'init'; vectors: ArrayBuffer; dim: number; scale: number };
type QueryMsg = { type: 'query'; query: string; topK: number; id: string };
type InMsg = InitMsg | QueryMsg;

const post = (msg: unknown) => (self as unknown as Worker).postMessage(msg);

self.addEventListener('message', async (e: MessageEvent<InMsg>) => {
	const msg = e.data;
	try {
		if (msg.type === 'init') {
			corpus = new Int8Array(msg.vectors);
			dim = msg.dim;
			post({ type: 'progress', stage: 'model', detail: 'loading' });
			extractor = (await pipeline(
				'feature-extraction',
				'Xenova/all-MiniLM-L6-v2'
			)) as FeatureExtractionPipeline;
			post({ type: 'ready' });
			return;
		}
		if (msg.type === 'query') {
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
				scores[i] = s;
			}
			const topK = Math.min(msg.topK || 50, n);
			// Heap-pick via partial sort: collect indices, sort by descending score, slice.
			const indices = Array.from({ length: n }, (_, i) => i);
			indices.sort((a, b) => scores[b] - scores[a]);
			const top = indices.slice(0, topK);
			const topScores = top.map((i) => scores[i]);
			post({ type: 'results', id: msg.id, indices: top, scores: topScores });
		}
	} catch (err) {
		post({ type: 'error', message: (err as Error).message });
	}
});
