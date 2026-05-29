/**
 * Stage 15 (spec 015-neuroscape-context, T042) — loader.ts atlas
 * + neuroscape dispatch.
 *
 * `parseParquetSingle` switches its outer-row dispatch table based
 * on the manifest's `schema_version`:
 *
 *   - 'abstracts.v2' (default) → Stage-10 OHBM 2026 envelope.
 *   - 'atlas.v1'              → bare-root cross-conference scatter.
 *   - 'neuroscape.v1'         → /neuroscape/ subsite envelope.
 *
 * The tests construct canned outer + inner rows via a module-level
 * `vi.mock('hyparquet', …)` factory, then call `loadDataPackage`
 * against a fake fetch and assert the returned envelope's key set.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Shared mutable "what should the next parquetReadObjects call
// return". The mock factory below reads this on every call.
let __innerByName: Record<string, object[]> = {};
let __outerNames: string[] = [];

vi.mock('hyparquet', () => {
	return {
		parquetReadObjects: vi.fn(async (opts: { file: { byteLength: number; slice: (a: number, b?: number) => Promise<ArrayBuffer> } }) => {
			// Read the bytes the loader handed us. Outer rows have an
			// empty/short outer-shape payload; inner blobs carry the
			// table_name as ASCII so we can route them.
			const ab = await opts.file.slice(0, opts.file.byteLength);
			const bytes = new Uint8Array(ab);
			const decoded = new TextDecoder().decode(bytes);
			if (__innerByName[decoded]) return __innerByName[decoded];
			// Otherwise the loader is asking for outer rows.
			return __outerNames.map((name) => ({
				table_name: name,
				// Embed the table_name as the blob bytes so the inner
				// read above can route back to the canned rows.
				table_bytes: new TextEncoder().encode(name)
			}));
		}),
		// Used by loadClusterCentroidsFromNeuroscape's range-fetch. Returns
		// a zero-length buffer; the parquetReadObjects mock decodes '' (not a
		// known inner table) and falls through to the outer-rows branch.
		asyncBufferFromUrl: vi.fn(async () => ({
			byteLength: 0,
			slice: async () => new ArrayBuffer(0)
		})),
		parquetMetadataAsync: vi.fn(async () => ({ key_value_metadata: [] }))
	};
});

// Hyparquet-compressors is only imported for the compressors map;
// it's a no-op in this test.
vi.mock('hyparquet-compressors', () => ({ compressors: {} }));

describe('loader atlas-root dispatch (T042)', () => {
	beforeEach(() => {
		__innerByName = {};
		__outerNames = [];
	});

	afterEach(() => {
		vi.resetModules();
		vi.unstubAllEnvs();
	});

	async function runAssertions(args: {
		innerByName: Record<string, object[]>;
		expectedKeys: string[];
		notExpectedKeys: string[];
	}) {
		__innerByName = args.innerByName;
		__outerNames = Object.keys(args.innerByName);

		const fakeFetch = vi.fn(async () => {
			return new Response(new Uint8Array(8).buffer, {
				status: 200,
				headers: { 'content-type': 'application/octet-stream' }
			});
		}) as unknown as typeof fetch;

		// Provide a URL so the loader doesn't short-circuit to null.
		// `import.meta.env` is compile-time substituted by Vite, so a
		// runtime assignment doesn't take; use vitest's stubEnv API.
		vi.stubEnv('VITE_DATA_PACKAGE_URL', 'https://example.test/data.parquet');

		const { loadDataPackage, resetDataPackageCacheForTests } = await import(
			'$lib/data_package/loader'
		);
		resetDataPackageCacheForTests();
		const map = await loadDataPackage(fakeFetch);
		expect(map).not.toBeNull();
		const keys = Array.from(map!.keys());

		for (const k of args.expectedKeys) {
			expect(keys, `missing expected key: ${k}\nactual: ${JSON.stringify(keys)}`).toContain(k);
		}
		for (const k of args.notExpectedKeys) {
			expect(keys, `unexpected key present: ${k}\nactual: ${JSON.stringify(keys)}`).not.toContain(
				k
			);
		}
	}

	it('emits the documented atlas-root envelope keys for schema_version atlas.v1', async () => {
		await runAssertions({
			innerByName: {
				manifest: [
					{
						manifest_json: JSON.stringify({
							schema_version: 'atlas.v1',
							build_info: { state_key: 'atlas1234abcd' },
							n_overlay_points: 2,
							n_clusters: 3
						})
					}
				],
				clusters: [{ cluster_id: 0, title: 'C0' }],
				neuroscape_backdrop_full: [{ pubmed_id: 100, cluster_id: 0 }],
				neuroscape_backdrop_decimated: [{ pubmed_id: 100, cluster_id: 0 }],
				ohbm_overlay: [{ submission_id: 1001, poster_id: 201 }],
				cross_pointers: [
					{ point_kind: 'ohbm2026', id: 201, permalink: '/ohbm2026/abstract/201/' }
				]
			},
			expectedKeys: [
				'data/manifest.json',
				'data/atlas/clusters.json',
				'data/atlas/backdrop_full.json',
				'data/atlas/backdrop_decimated.json',
				'data/atlas/ohbm_overlay.json',
				'data/atlas/cross_pointers.json'
			],
			notExpectedKeys: [
				'data/abstracts.json',
				'data/enrichment.json',
				'data/standby_slots.json'
			]
		});
	});

	it('emits the documented neuroscape envelope keys for schema_version neuroscape.v1', async () => {
		await runAssertions({
			innerByName: {
				manifest: [
					{
						manifest_json: JSON.stringify({
							schema_version: 'neuroscape.v1',
							build_info: { state_key: 'ns0000000001' },
							n_articles: 1,
							n_clusters: 1
						})
					}
				],
				articles: [{ pubmed_id: 100, title: 'T', year: 2020, cluster_id: 0 }],
				clusters: [{ cluster_id: 0, title: 'C0' }],
				neighbors_neuroscape: [{ pubmed_id: 100, nearest_pubmed_ids: [101, 102] }]
			},
			expectedKeys: [
				'data/manifest.json',
				'data/neuroscape/articles.json',
				'data/neuroscape/clusters.json',
				'data/neuroscape/neighbors.json'
			],
			notExpectedKeys: ['data/abstracts.json', 'data/enrichment.json']
		});
	});

	it('still emits the OHBM 2026 envelope when manifest has no schema_version (legacy abstracts.v2 path)', async () => {
		await runAssertions({
			innerByName: {
				manifest: [
					{
						manifest_json: JSON.stringify({
							build_info: { state_key: 'ohbm12345678' }
						})
					}
				],
				abstracts: [{ submission_id: 1001, poster_id: 201, title: 'OHBM' }],
				authors: [{ author_id: 1, name: 'A' }]
			},
			expectedKeys: ['data/manifest.json', 'data/abstracts.json', 'data/authors.json'],
			notExpectedKeys: ['data/atlas/clusters.json', 'data/neuroscape/articles.json']
		});
	});

	it('recovers ai_provenance from the manifest so the ✨ AI pill can display (stage 15.4 follow-up)', async () => {
		__innerByName = {
			manifest: [
				{
					manifest_json: JSON.stringify({
						build_info: { state_key: 'ohbm12345678' },
						enrichment_ai_provenance: {
							claims_model_id: 'gpt-5.4-mini',
							figures_model_id: 'gpt-5.4-mini'
						}
					})
				}
			],
			abstracts: [{ poster_id: 201, title: 'OHBM' }],
			authors: [{ author_id: 1, name: 'A' }],
			enrichment_claims: [{ poster_id: 201, claim_index: 0, claim: 'c' }]
		};
		__outerNames = Object.keys(__innerByName);

		const fakeFetch = vi.fn(async () => {
			return new Response(new Uint8Array(8).buffer, {
				status: 200,
				headers: { 'content-type': 'application/octet-stream' }
			});
		}) as unknown as typeof fetch;

		vi.stubEnv('VITE_DATA_PACKAGE_URL', 'https://example.test/data.parquet');

		const { loadDataPackage, resetDataPackageCacheForTests } = await import(
			'$lib/data_package/loader'
		);
		resetDataPackageCacheForTests();
		const map = await loadDataPackage(fakeFetch);
		expect(map).not.toBeNull();

		const enrichment = map!.get('data/enrichment.json') as {
			ai_provenance: { claims_model_id: string | null; figures_model_id: string | null };
		};
		expect(enrichment).toBeDefined();
		expect(enrichment.ai_provenance.claims_model_id).toBe('gpt-5.4-mini');
		expect(enrichment.ai_provenance.figures_model_id).toBe('gpt-5.4-mini');
	});

	it('range-fetches cluster_centroids from the sibling neuroscape.parquet (atlas-root fallback)', async () => {
		// The outer read returns one row per name in __outerNames; the inner
		// decode of the 'cluster_centroids' blob routes back to these rows.
		__innerByName = {
			cluster_centroids: [
				{ cluster_id: 0, centroid_vector: [0.1, 0.2, 0.3], member_count: 12 },
				{ cluster_id: 1, centroid_vector: [0.4, 0.5, 0.6], member_count: 7 }
			]
		};
		__outerNames = ['clusters', 'cluster_centroids', 'articles'];

		vi.stubEnv('VITE_DATA_PACKAGE_URL_NEUROSCAPE', 'https://example.test/neuroscape.parquet');

		const { loadClusterCentroidsFromNeuroscape } = await import('$lib/data_package/loader');
		const centroids = await loadClusterCentroidsFromNeuroscape();
		expect(centroids).not.toBeNull();
		expect(centroids!.length).toBe(2);
		expect(centroids![0].cluster_id).toBe(0);
		expect(centroids![0].member_count).toBe(12);
		expect(centroids![0].centroid_vector).toBeInstanceOf(Float32Array);
		expect(Array.from(centroids![0].centroid_vector)).toEqual([
			expect.closeTo(0.1, 5),
			expect.closeTo(0.2, 5),
			expect.closeTo(0.3, 5)
		]);
	});

	it('returns null from loadClusterCentroidsFromNeuroscape when the sibling URL is unset', async () => {
		vi.stubEnv('VITE_DATA_PACKAGE_URL_NEUROSCAPE', '');
		const { loadClusterCentroidsFromNeuroscape } = await import('$lib/data_package/loader');
		expect(await loadClusterCentroidsFromNeuroscape()).toBeNull();
	});

	it('leaves ai_provenance keys null when the manifest carries no enrichment attribution', async () => {
		__innerByName = {
			manifest: [
				{
					manifest_json: JSON.stringify({
						build_info: { state_key: 'ohbm12345678' }
					})
				}
			],
			abstracts: [{ poster_id: 201, title: 'OHBM' }],
			authors: [{ author_id: 1, name: 'A' }],
			enrichment_claims: [{ poster_id: 201, claim_index: 0, claim: 'c' }]
		};
		__outerNames = Object.keys(__innerByName);

		const fakeFetch = vi.fn(async () => {
			return new Response(new Uint8Array(8).buffer, {
				status: 200,
				headers: { 'content-type': 'application/octet-stream' }
			});
		}) as unknown as typeof fetch;

		vi.stubEnv('VITE_DATA_PACKAGE_URL', 'https://example.test/data.parquet');

		const { loadDataPackage, resetDataPackageCacheForTests } = await import(
			'$lib/data_package/loader'
		);
		resetDataPackageCacheForTests();
		const map = await loadDataPackage(fakeFetch);
		const enrichment = map!.get('data/enrichment.json') as {
			ai_provenance: { claims_model_id: string | null; figures_model_id: string | null };
		};
		expect(enrichment.ai_provenance.claims_model_id).toBeNull();
		expect(enrichment.ai_provenance.figures_model_id).toBeNull();
	});
});
