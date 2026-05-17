import { loadMinilmVectors } from '$lib/shards';
import { writable, type Readable } from 'svelte/store';

/**
 * Main-thread facade for the semantic-search worker. Lazy-initializes the
 * worker + transferring the int8 vector buffer + waiting for the
 * `Xenova/all-MiniLM-L6-v2` model to finish loading (one-time per browser
 * session; the model + its tokenizer are cached by the browser thereafter).
 */

type SemanticStatus =
	| { state: 'idle' }
	| { state: 'loading-vectors' }
	| { state: 'loading-model' }
	| { state: 'ready' }
	| { state: 'error'; message: string };

const _status = writable<SemanticStatus>({ state: 'idle' });
export const semanticStatus: Readable<SemanticStatus> = { subscribe: _status.subscribe };

let worker: Worker | null = null;
let initPromise: Promise<Worker> | null = null;
let queryCounter = 0;

export interface SemanticHit {
	index: number;
	score: number;
}

async function initWorker(): Promise<Worker> {
	if (worker) return worker;
	if (initPromise) return initPromise;
	initPromise = (async () => {
		_status.set({ state: 'loading-vectors' });
		const vectors = await loadMinilmVectors();
		if (!vectors) {
			_status.set({ state: 'error', message: 'minilm vectors not available' });
			throw new Error('minilm vectors not available');
		}
		const w = new Worker(new URL('../workers/semantic.worker.ts', import.meta.url), {
			type: 'module'
		});
		const ready = new Promise<void>((resolve, reject) => {
			const handler = (e: MessageEvent) => {
				const m = e.data;
				if (m?.type === 'progress' && m.stage === 'model') {
					_status.set({ state: 'loading-model' });
				} else if (m?.type === 'ready') {
					w.removeEventListener('message', handler);
					resolve();
				} else if (m?.type === 'error') {
					w.removeEventListener('message', handler);
					reject(new Error(m.message));
				}
			};
			w.addEventListener('message', handler);
		});
		const buffer = vectors.bytes.buffer.slice(
			vectors.bytes.byteOffset,
			vectors.bytes.byteOffset + vectors.bytes.byteLength
		);
		w.postMessage(
			{
				type: 'init',
				vectors: buffer,
				dim: vectors.sidecar.shape[1],
				scale: vectors.sidecar.scale
			},
			[buffer]
		);
		await ready;
		worker = w;
		_status.set({ state: 'ready' });
		return w;
	})().catch((err) => {
		_status.set({ state: 'error', message: (err as Error).message });
		initPromise = null;
		throw err;
	});
	return initPromise;
}

/** Ensure the worker is initialized; resolves once ready. */
export async function warmSemantic(): Promise<void> {
	await initWorker();
}

export async function semanticSearch(query: string, topK = 50): Promise<SemanticHit[]> {
	const w = await initWorker();
	const id = `q-${++queryCounter}`;
	return new Promise((resolve, reject) => {
		const handler = (e: MessageEvent) => {
			const m = e.data;
			if (m?.type === 'results' && m.id === id) {
				w.removeEventListener('message', handler);
				const hits: SemanticHit[] = m.indices.map((idx: number, k: number) => ({
					index: idx,
					score: m.scores[k]
				}));
				resolve(hits);
			} else if (m?.type === 'error') {
				w.removeEventListener('message', handler);
				reject(new Error(m.message));
			}
		};
		w.addEventListener('message', handler);
		w.postMessage({ type: 'query', query, topK, id });
	});
}
