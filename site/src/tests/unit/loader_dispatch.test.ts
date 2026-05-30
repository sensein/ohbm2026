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

	it('emits ONLY manifest + ohbm_overlay for schema_version atlas.v1 (spec 019 slim atlas)', async () => {
		// Spec 019 — atlas.parquet now carries only the OHBM→NeuroScape
		// overlay (sibling-impossible). clusters / backdrop / centroids are
		// range-fetched from neuroscape.parquet, cross_pointers is dropped.
		await runAssertions({
			innerByName: {
				manifest: [
					{
						manifest_json: JSON.stringify({
							schema_version: 'atlas.v1',
							build_info: {
								state_key: 'atlas1234abcd',
								sibling_state_keys: { ohbm2026: 'ohbm12345678', neuroscape: 'ns0000000001' }
							},
							n_overlay_points: 2
						})
					}
				],
				ohbm_overlay: [{ submission_id: 1001, poster_id: 201 }]
			},
			expectedKeys: ['data/manifest.json', 'data/atlas/ohbm_overlay.json'],
			notExpectedKeys: [
				'data/atlas/clusters.json',
				'data/atlas/backdrop_full.json',
				'data/atlas/backdrop_decimated.json',
				'data/atlas/cross_pointers.json',
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
				coords: [
					{ pubmed_id: 100, cluster_id: 0, umap_2d: [1, 2], umap_3d: [1, 2, 3], lod_level: 0 }
				],
				// Spec 019 follow-up — progressive backdrop tiers are
				// range-fetched on demand by atlas-root, never emitted as a
				// full-GET shard. The full-GET dispatch must SKIP them.
				backdrop_lod0: [
					{ pubmed_id: 100, cluster_id: 0, umap_2d: [1, 2], umap_3d: [1, 2, 3], title: 'T', year: 2020 }
				],
				clusters: [{ cluster_id: 0, title: 'C0' }],
				neighbors_neuroscape: [{ pubmed_id: 100, nearest_pubmed_ids: [101, 102] }]
			},
			expectedKeys: [
				'data/manifest.json',
				'data/neuroscape/articles.json',
				'data/neuroscape/coords.json',
				'data/neuroscape/clusters.json',
				'data/neuroscape/neighbors.json'
			],
			notExpectedKeys: [
				'data/abstracts.json',
				'data/enrichment.json',
				'data/neuroscape/backdrop_decimated.json',
				'data/neuroscape/backdrop_lod0.json'
			]
		});
	});

	it('folds the coords table onto neuroscape articles (umap_2d / umap_3d join)', async () => {
		__innerByName = {
			manifest: [
				{
					manifest_json: JSON.stringify({
						schema_version: 'neuroscape.v1',
						build_info: { state_key: 'ns0000000001' },
						n_articles: 1
					})
				}
			],
			articles: [{ pubmed_id: 100, title: 'T', year: 2020, cluster_id: 0 }],
			coords: [
				{ pubmed_id: 100, cluster_id: 0, umap_2d: [1.5, 2.5], umap_3d: [1, 2, 3], lod_level: 2 }
			]
		};
		__outerNames = Object.keys(__innerByName);

		const fakeFetch = vi.fn(async () => {
			return new Response(new Uint8Array(8).buffer, {
				status: 200,
				headers: { 'content-type': 'application/octet-stream' }
			});
		}) as unknown as typeof fetch;

		vi.stubEnv('VITE_DATA_PACKAGE_URL_NEUROSCAPE', 'https://example.test/neuroscape.parquet');
		vi.stubEnv('VITE_SITE_MODE', 'neuroscape');

		const { loadDataPackage, resetDataPackageCacheForTests } = await import(
			'$lib/data_package/loader'
		);
		resetDataPackageCacheForTests();
		const map = await loadDataPackage(fakeFetch);
		expect(map).not.toBeNull();
		const articlesShard = map!.get('data/neuroscape/articles.json') as {
			articles: Array<{
				pubmed_id: number;
				umap_2d?: number[];
				umap_3d?: number[];
				lod_level?: number;
			}>;
		};
		expect(articlesShard.articles[0].umap_2d).toEqual([1.5, 2.5]);
		expect(articlesShard.articles[0].umap_3d).toEqual([1, 2, 3]);
		// Spec 019 follow-up — lod_level folds onto the article so the
		// /neuroscape/ scatter can cap to the blue-noise sample.
		expect(articlesShard.articles[0].lod_level).toEqual(2);
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

	it('range-fetches the FULL articles identity table from the sibling neuroscape.parquet (spec 019 atlas-root count fix)', async () => {
		// atlas.parquet ships no corpus list; atlas-root must range-fetch the
		// single source-of-truth `articles` table from the neuroscape sibling
		// so the result-list count + lexical search cover the whole ~461k
		// corpus (regression: the coords-split dropped neuroscape_backdrop_full,
		// collapsing the count from ~461k to ~53k).
		__innerByName = {
			articles: [
				{ pubmed_id: 100, title: 'Memory consolidation', year: 2020, cluster_id: 0 },
				{ pubmed_id: 101, title: 'Attention networks', year: 2021, cluster_id: 1 },
				{ pubmed_id: 102, title: 'Cortical thickness', year: 2022, cluster_id: 0 }
			]
		};
		__outerNames = ['clusters', 'articles', 'coords', 'backdrop_decimated'];

		vi.stubEnv('VITE_DATA_PACKAGE_URL_NEUROSCAPE', 'https://example.test/neuroscape.parquet');

		const { loadArticlesFromNeuroscape } = await import('$lib/data_package/loader');
		const articles = await loadArticlesFromNeuroscape();
		expect(articles).not.toBeNull();
		expect(articles!.length).toBe(3);
		expect(articles!.map((a) => a.pubmed_id)).toEqual([100, 101, 102]);
		expect(articles![0].title).toBe('Memory consolidation');
	});

	it('returns null from loadArticlesFromNeuroscape when the sibling URL is unset', async () => {
		vi.stubEnv('VITE_DATA_PACKAGE_URL_NEUROSCAPE', '');
		const { loadArticlesFromNeuroscape } = await import('$lib/data_package/loader');
		expect(await loadArticlesFromNeuroscape()).toBeNull();
	});

	it('range-fetches the FULL coords table from the sibling (atlas-root lasso find-all)', async () => {
		// atlas-root lazily pulls the full `coords` geometry on the first
		// lasso so the polygon test covers all 461k abstracts, not just the
		// rendered LOD sample.
		__innerByName = {
			coords: [
				{ pubmed_id: 100, cluster_id: 0, umap_2d: [1.0, 2.0], umap_3d: [1, 2, 3], lod_level: 0 },
				{ pubmed_id: 101, cluster_id: 1, umap_2d: [3.0, 4.0], umap_3d: [3, 4, 5], lod_level: 5 }
			]
		};
		__outerNames = ['clusters', 'articles', 'coords', 'backdrop_lod0'];
		vi.stubEnv('VITE_DATA_PACKAGE_URL_NEUROSCAPE', 'https://example.test/neuroscape.parquet');
		const { loadCoordsFromNeuroscape } = await import('$lib/data_package/loader');
		const coords = await loadCoordsFromNeuroscape();
		expect(coords).not.toBeNull();
		expect(coords!.length).toBe(2);
		expect(coords!.map((c) => c.pubmed_id)).toEqual([100, 101]);
		expect(coords![0].umap_2d).toEqual([1.0, 2.0]);
	});

	it('returns null from loadCoordsFromNeuroscape when the sibling URL is unset', async () => {
		vi.stubEnv('VITE_DATA_PACKAGE_URL_NEUROSCAPE', '');
		const { loadCoordsFromNeuroscape } = await import('$lib/data_package/loader');
		expect(await loadCoordsFromNeuroscape()).toBeNull();
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
