/**
 * Runtime data-package loader.
 *
 * The deployed site doesn't bundle any data. At runtime, the client
 * fetches a single `*.parquet` file from a per-deployment env var,
 * parses it via `hyparquet`, and returns a
 * `Map<path, JsonValue | Uint8Array>` whose keys are the legacy
 * shard paths (`data/manifest.json`, `data/cells/<key>.json`, ...).
 * UI consumers in `$lib/shards` keep their existing import surface
 * unchanged; the map shape is identical to the old tarball loader's
 * output so no Stage-6 component needed a refactor.
 *
 * Stage 15 (spec 015-neuroscape-context, FR-022) renamed the
 * canonical OHBM 2026 file from `data.parquet` to
 * `ohbm2026.parquet` and split the URL by deployment mode:
 *
 *   - `VITE_DATA_PACKAGE_URL_OHBM2026` → `ohbm2026.parquet` (the
 *     `/ohbm2026/` SvelteKit build reads this).
 *   - `VITE_DATA_PACKAGE_URL_NEUROSCAPE` → `neuroscape.parquet`
 *     (the `/neuroscape/` build reads this; landed via T069).
 *   - `VITE_DATA_PACKAGE_URL_ATLAS` → `atlas.parquet` (the bare-root
 *     cross-conference build reads this; landed via T042).
 *
 * The legacy `VITE_DATA_PACKAGE_URL` is honoured as a fallback for
 * one deploy cycle so a stale GitHub Actions repo variable does not
 * silently break production.
 *
 * The outer Parquet file has one row per logical table, with the
 * table's own Parquet bytes in a `table_bytes` BLOB column. We decode
 * the outer once, then decode each inner blob into rows and repack
 * them into the Stage-6 envelope shape the UI expects.
 */

import { parquetReadObjects, asyncBufferFromUrl, parquetMetadataAsync } from 'hyparquet';
import { fetchParquetCached, prefetchInBackground } from './cache';
import { compressors } from 'hyparquet-compressors';
import { SITE_MODE } from '$lib/site_mode';

let packageCache: Promise<Map<string, unknown> | null> | null = null;

function pickRawUrl(): string | undefined {
	const env = import.meta.env;
	// Stage-15 per-mode URL variables. The legacy single
	// `VITE_DATA_PACKAGE_URL` is honoured as a final fallback so a
	// not-yet-updated deploy-workflow repo variable doesn't break
	// production silently.
	if (SITE_MODE === 'neuroscape') {
		return (env.VITE_DATA_PACKAGE_URL_NEUROSCAPE ?? env.VITE_DATA_PACKAGE_URL) as
			| string
			| undefined;
	}
	if (SITE_MODE === 'atlas-root') {
		return (env.VITE_DATA_PACKAGE_URL_ATLAS ?? env.VITE_DATA_PACKAGE_URL) as
			| string
			| undefined;
	}
	// SITE_MODE === 'ohbm2026' (default): prefer the new per-mode
	// variable; fall back to the legacy single variable.
	return (env.VITE_DATA_PACKAGE_URL_OHBM2026 ?? env.VITE_DATA_PACKAGE_URL) as
		| string
		| undefined;
}

function normaliseDropboxUrl(url: string): string {
	// Dropbox shared links served via `www.dropbox.com` redirect (HTTP 302)
	// to `*.dl.dropboxusercontent.com`, but the redirect step itself lacks
	// CORS headers — browsers refuse the cross-origin fetch. Rewriting the
	// host to `dl.dropboxusercontent.com` skips the redirect and lands
	// directly on the content endpoint, which DOES send
	// `Access-Control-Allow-Origin: *` and serves raw bytes.
	return url
		.replace(/^https:\/\/www\.dropbox\.com\//, 'https://dl.dropboxusercontent.com/')
		.replace(/[?&]dl=0(\b|$)/, (m) => m.replace('dl=0', ''));
}

export function getDataPackageUrl(): string | null {
	const url = pickRawUrl();
	if (!url) return null;
	return normaliseDropboxUrl(url);
}

/**
 * Spec 019 — URL of `neuroscape_vectors.parquet`, the per-cluster INT8
 * sidecar that drives the full cluster-routed semantic ranker (steps
 * 3-6 of contracts/search-ranking-pipeline.md). Resolved from
 * `VITE_DATA_PACKAGE_URL_NEUROSCAPE_VECTORS` and run through the same
 * Dropbox CORS/range normalisation as the primary parquet.
 *
 * Returns `null` when unset — the caller then leaves the full ranker
 * uninitialised and the UI falls back to the KNN-only semantic path
 * (which needs only the k=20 graph already in `neuroscape.parquet`).
 */
export function getNeuroscapeVectorsUrl(): string | null {
	const raw = (import.meta.env.VITE_DATA_PACKAGE_URL_NEUROSCAPE_VECTORS ?? null) as
		| string
		| null;
	if (!raw) return null;
	return normaliseDropboxUrl(raw);
}

/**
 * URLs of the two SIBLING parquets for the current build mode — the
 * ones that aren't this build's own parquet. Used to warm the Cache
 * API after the primary load so any cross-subsite click (e.g. from a
 * permalink on /ohbm2026/ to the atlas-root home) reads from cache
 * instead of doing a cold network fetch.
 *
 * Visitors can land on any subsite first — permalinks bookmark
 * specific /<mode>/abstract/<id>/ URLs and we never know which mode
 * starts the session. So the prefetch runs from every mode's
 * loadDataPackage success branch; each warms the other two parquets.
 */
export function getCrossSiblingUrls(): string[] {
	const env = import.meta.env;
	const ohbm = env.VITE_DATA_PACKAGE_URL_OHBM2026 ?? env.VITE_DATA_PACKAGE_URL;
	const neuro = env.VITE_DATA_PACKAGE_URL_NEUROSCAPE;
	const atlas = env.VITE_DATA_PACKAGE_URL_ATLAS;
	const all: Array<string | undefined> = [];
	if (SITE_MODE === 'atlas-root') {
		all.push(ohbm as string | undefined, neuro as string | undefined);
	} else if (SITE_MODE === 'ohbm2026') {
		all.push(atlas as string | undefined, neuro as string | undefined);
	} else if (SITE_MODE === 'neuroscape') {
		all.push(atlas as string | undefined, ohbm as string | undefined);
	}
	return all.filter((u): u is string => !!u).map(normaliseDropboxUrl);
}

/** Progress callback fired during the parquet HTTP fetch. The
 *  caller can render "Loading… X%" while bytes stream in. `total`
 *  is null when the server doesn't send a Content-Length header
 *  (the caller can show "Loading X MB…" instead). */
export type LoadProgress = (loaded: number, total: number | null) => void;

/** Phase callback. Lets the UI distinguish the three observable
 *  steps that together feel like "loading":
 *
 *    'connecting' → request issued, no bytes yet
 *    'downloading' → first chunk arrived; onProgress is now firing
 *    'parsing'    → bytes complete, hyparquet decode is in flight
 *                   (CPU-bound; the main thread will be busy)
 *    'ready'      → result map is fully populated
 *
 *  Without this, fast connections show a blank placeholder for the
 *  ~3-5s parsing window after the byte progress hits 100%, which
 *  reads as "frozen". */
export type LoadPhase = 'connecting' | 'downloading' | 'parsing' | 'ready';
export type PhaseHook = (phase: LoadPhase) => void;

export function loadDataPackage(
	fetcher: typeof fetch = fetch,
	onProgress: LoadProgress | null = null,
	onPhase: PhaseHook | null = null
): Promise<Map<string, unknown> | null> {
	if (packageCache !== null) return packageCache;
	const url = getDataPackageUrl();
	if (!url) {
		packageCache = Promise.resolve(null);
		return packageCache;
	}
	packageCache = (async (): Promise<Map<string, unknown> | null> => {
		try {
			onPhase?.('connecting');
			// Wrap the GET in a Cache-API layer: persistent across
			// sessions, conditionally revalidated via If-None-Match /
			// If-Modified-Since on subsequent loads. A cache-hit-
			// validated response is byte-equivalent to a fresh GET so
			// the rest of the loader doesn't need to know.
			const { response, source } = await fetchParquetCached(url, fetcher);
			if (!response.ok || !response.body) return null;
			if (source === 'cache-hit-validated' || source === 'cache-hit-offline') {
				console.info(`[ohbm2026] data package served from ${source}`);
			}
			// When a progress callback is provided, stream the body via
			// `getReader()` so we can report bytes-arrived as we go.
			// Without a callback we still take the simpler `arrayBuffer()`
			// path — no measurable overhead in the no-progress case.
			let bytes: Uint8Array;
			if (onProgress && response.body && typeof response.body.getReader === 'function') {
				const contentLengthHeader = response.headers.get('content-length');
				const total = contentLengthHeader ? Number(contentLengthHeader) : null;
				const reader = response.body.getReader();
				const chunks: Uint8Array[] = [];
				let loaded = 0;
				onProgress(0, total);
				onPhase?.('downloading');
				// eslint-disable-next-line no-constant-condition
				while (true) {
					const { value, done } = await reader.read();
					if (done) break;
					if (value) {
						chunks.push(value);
						loaded += value.byteLength;
						onProgress(loaded, total);
					}
				}
				bytes = new Uint8Array(loaded);
				let offset = 0;
				for (const c of chunks) {
					bytes.set(c, offset);
					offset += c.byteLength;
				}
			} else {
				onPhase?.('downloading');
				const buffer = await response.arrayBuffer();
				bytes = new Uint8Array(buffer);
			}
			// Yield once so any pending DOM update (final 100% / final
			// MB readout) flushes before parseParquetSingle blocks the
			// main thread.
			onPhase?.('parsing');
			await new Promise<void>((r) => setTimeout(r, 0));
			const result = await parseParquetSingle(bytes);
			onPhase?.('ready');
			// Warm the Cache API with the two sibling parquets so any
			// cross-subsite navigation lands on cache instead of a
			// cold fetch. Fire-and-forget; skipped on save-data /
			// slow-2g connections (see cache.ts).
			const siblings = getCrossSiblingUrls();
			if (siblings.length) prefetchInBackground(siblings);
			return result;
		} catch (err) {
			console.error('[ohbm2026] failed to load data package:', err);
			return null;
		}
	})();
	return packageCache;
}

export function resetDataPackageCacheForTests(): void {
	packageCache = null;
}

interface OuterRow {
	// `table_name` is a pyarrow `string` column → hyparquet returns it as
	// a JS string regardless of the top-level `utf8` flag (the STRING
	// logical type forces decode).
	table_name: string;
	// `table_bytes` is a pyarrow `large_binary` column → with `utf8: false`
	// hyparquet returns it as Uint8Array; default utf8 decode would mangle
	// arbitrary binary, so we opt out.
	table_bytes: Uint8Array;
}

function bytesAsAsyncBuffer(bytes: Uint8Array) {
	const ab = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
	return {
		byteLength: ab.byteLength,
		slice: async (start: number, end?: number) => ab.slice(start, end ?? ab.byteLength)
	};
}

/**
 * Walk decoded Parquet rows and coerce any BigInt values to Number.
 * pyarrow stores integer columns as INT64 by default; hyparquet returns
 * INT64 columns as BigInt for safety. Stage-6 UI consumers expect plain
 * Numbers (poster_ids, cluster_ids, neighbour_ids) — BigInts break
 * `===` joins against Number-typed IDs from other shards and can't be
 * JSON-serialised.
 *
 * Our IDs all fit in float64 (max poster_id ~3333); the coercion is
 * loss-free for this dataset. If a future corpus grows past 2^53, the
 * fix is to cast columns to INT32 in the Python emitter explicitly.
 */
function coerceBigInts(value: unknown): unknown {
	if (typeof value === 'bigint') return Number(value);
	if (Array.isArray(value)) {
		for (let i = 0; i < value.length; i++) value[i] = coerceBigInts(value[i]);
		return value;
	}
	if (value !== null && typeof value === 'object') {
		for (const k of Object.keys(value)) {
			(value as Record<string, unknown>)[k] = coerceBigInts(
				(value as Record<string, unknown>)[k]
			);
		}
		return value;
	}
	return value;
}

async function decodeBlob(blob: Uint8Array): Promise<unknown[]> {
	// `utf8: true` (default) is what we want for the inner tables — string
	// columns come back as JS strings.
	const rows = (await parquetReadObjects({
		file: bytesAsAsyncBuffer(blob),
		compressors
	})) as unknown[];
	return coerceBigInts(rows) as unknown[];
}

async function parseParquetSingle(bytes: Uint8Array): Promise<Map<string, unknown>> {
	const out = new Map<string, unknown>();
	// `utf8: false` on the outer read so `table_bytes` (large_binary)
	// stays as Uint8Array. `table_name` is a STRING logical type so it
	// comes back as a JS string regardless of this flag.
	const outerRows = (await parquetReadObjects({
		file: bytesAsAsyncBuffer(bytes),
		compressors,
		utf8: false
	})) as OuterRow[];

	// Manifest first — its build_info is glued onto every shard envelope.
	const manifestRow = outerRows.find((r) => r.table_name === 'manifest');
	let manifest: unknown = null;
	if (manifestRow) {
		const rows = (await decodeBlob(manifestRow.table_bytes)) as Array<{ manifest_json?: string }>;
		if (rows[0]?.manifest_json) {
			try {
				manifest = JSON.parse(rows[0].manifest_json);
			} catch {
				/* skip malformed manifest */
			}
		}
	}
	if (manifest) out.set('data/manifest.json', manifest);
	const buildInfo = (manifest as { build_info?: unknown } | null)?.build_info ?? {};
	// Stage 15 (T042): the same single-file parquet shape carries
	// three distinct schemas now — Stage-10 'abstracts.v2' (the
	// OHBM 2026 corpus), 'atlas.v1' (the bare-root cross-conference
	// scatter), and 'neuroscape.v1' (the new /neuroscape/ subsite).
	// The manifest's schema_version selects the dispatch table.
	const schemaVersion =
		(manifest as { schema_version?: string } | null)?.schema_version ?? 'abstracts.v2';
	const isAtlas = schemaVersion === 'atlas.v1';
	const isNeuroscape = schemaVersion === 'neuroscape.v1';

	for (const row of outerRows) {
		// Yield to the event loop before each blob decode. hyparquet's
		// per-blob decode is largely synchronous once it starts; for
		// large tables (e.g. the 461k-row neuroscape backdrop) that
		// can block the main thread for hundreds of ms. Yielding here
		// lets the browser repaint the "Parsing…" placeholder + animate
		// the indeterminate progress bar between blobs, so the parse
		// phase is visibly active instead of looking frozen.
		await new Promise<void>((r) => setTimeout(r, 0));
		const { table_name: name, table_bytes: blob } = row;
		if (name === 'manifest') continue;
		// Enrichment tables are joined into one envelope below.
		if (name === 'enrichment_claims' || name === 'enrichment_figures') continue;
		// Binary blobs are stored without Parquet wrapping.
		if (name === 'search:minilm_vectors') {
			out.set('data/search/minilm_vectors.bin', blob);
			continue;
		}
		if (name === 'search:minilm_vectors_meta') {
			try {
				out.set('data/search/minilm_vectors.build_info.json', JSON.parse(new TextDecoder().decode(blob)));
			} catch {
				/* skip malformed sidecar */
			}
			continue;
		}
		// Stage 15 — neuroscape.parquet's title-only search sidecar.
		if (name === 'search:neuroscape_titles') {
			out.set('data/neuroscape/titles_index.bin', blob);
			continue;
		}
		if (name === 'search:neuroscape_titles_meta') {
			try {
				out.set(
					'data/neuroscape/titles_index.meta.json',
					JSON.parse(new TextDecoder().decode(blob))
				);
			} catch {
				/* skip malformed sidecar */
			}
			continue;
		}

		const rows = await decodeBlob(blob);

		// Stage 15 — atlas.parquet dispatch (schema_version === 'atlas.v1').
		// Bare-root cross-conference landing page reads these row groups.
		if (isAtlas) {
			if (name === 'ohbm_overlay') {
				out.set('data/atlas/ohbm_overlay.json', {
					schema_version: 'atlas.overlay.v1',
					build_info: buildInfo,
					points: rows
				});
				continue;
			}
			// Spec 019 — atlas.parquet now carries ONLY manifest + ohbm_overlay
			// (the OHBM→NeuroScape projection, which is impossible to derive
			// from either sibling alone). clusters, backdrop_decimated, and
			// cluster_centroids are all range-fetched from the sibling
			// neuroscape.parquet (loadClustersFromNeuroscape /
			// loadBackdropDecimatedFromNeuroscape / loadClusterCentroidsFromNeuroscape)
			// — single source of truth, no duplication. cross_pointers dropped:
			// permalinks are derived from (kind, id) in the browser.
			// Unknown atlas.v1 outer row — ignore silently (forwards
			// compatible: future atlas.parquet versions can add tables
			// without breaking this decoder).
			continue;
		}

		// Stage 15 — neuroscape.parquet dispatch (schema_version === 'neuroscape.v1').
		// The new /neuroscape/ subsite reads these row groups.
		if (isNeuroscape) {
			if (name === 'articles') {
				out.set('data/neuroscape/articles.json', {
					schema_version: 'neuroscape.articles.v1',
					build_info: buildInfo,
					articles: rows
				});
				continue;
			}
			if (name === 'coords') {
				// Spec 019 — geometry split out of `articles` so a view that
				// only needs identity/search never pays for umap_2d/umap_3d.
				// Folded onto articles in the post-loop join below.
				out.set('data/neuroscape/coords.json', {
					schema_version: 'neuroscape.coords.v1',
					build_info: buildInfo,
					coords: rows
				});
				continue;
			}
			if (name === 'backdrop_decimated') {
				// Spec 019 — self-contained landing scatter sample (moved here
				// from atlas.parquet). Carries its own title/year/umap so the
				// atlas-root backdrop renders from one range fetch.
				out.set('data/neuroscape/backdrop_decimated.json', {
					schema_version: 'neuroscape.backdrop.v1',
					build_info: buildInfo,
					points: rows
				});
				continue;
			}
			if (name === 'clusters') {
				out.set('data/neuroscape/clusters.json', {
					schema_version: 'neuroscape.clusters.v1',
					build_info: buildInfo,
					clusters: rows
				});
				continue;
			}
			if (name === 'neighbors_neuroscape') {
				out.set('data/neuroscape/neighbors.json', {
					schema_version: 'neuroscape.neighbors.v1',
					build_info: buildInfo,
					rows
				});
				continue;
			}
			if (name === 'cluster_centroids') {
				// Spec 019 / T025 — drive Step 2 of the cluster-routed
				// pipeline (route query to closest centroid). Rows shape:
				// `{cluster_id: int16, centroid_vector: FLOAT32[384],
				// member_count: int32}`.
				out.set('data/neuroscape/cluster_centroids.json', {
					schema_version: 'neuroscape.cluster_centroids.v1',
					build_info: buildInfo,
					rows
				});
				continue;
			}
			// Unknown neuroscape.v1 outer row — ignore (forwards
			// compatible, same rationale as the atlas branch).
			continue;
		}

		// Default dispatch path — Stage-10 'abstracts.v2' (OHBM 2026).
		if (name === 'abstracts') {
			out.set('data/abstracts.json', {
				schema_version: 'abstracts.v2',
				build_info: buildInfo,
				abstracts: rows
			});
		} else if (name === 'standby_slots') {
			// Stage 11.1 US2 — global lookup table. Decoder emits it as
			// its own shard; the abstract-hydration step below joins the
			// per-row INT8 indices against this table.
			out.set('data/standby_slots.json', {
				schema_version: 'standby_slots.v1',
				build_info: buildInfo,
				slots: rows
			});
		} else if (name === 'authors') {
			out.set('data/authors.json', { schema_version: 'authors.v2', build_info: buildInfo, authors: rows });
		} else if (name.startsWith('cells:')) {
			const cellKey = name.slice('cells:'.length);
			out.set(`data/cells/${cellKey}.json`, {
				schema_version: 'cells.v2',
				build_info: buildInfo,
				cell_key: cellKey,
				rows
			});
		} else if (name.startsWith('topics:')) {
			const key = name.slice('topics:'.length);
			const sep = key.lastIndexOf('_');
			const cellKey = key.slice(0, sep);
			const kind = key.slice(sep + 1);
			out.set(`data/topics/${cellKey}_${kind}.json`, {
				schema_version: 'topics.v2',
				build_info: buildInfo,
				cell_key: cellKey,
				kind,
				topics: rows
			});
		} else if (name.startsWith('neighbors:')) {
			const cellKey = name.slice('neighbors:'.length);
			const parallel = rows as Array<{
				poster_id: number;
				nearest_ids: number[];
				nearest_distances: number[];
				farthest_ids: number[];
				farthest_distances: number[];
			}>;
			out.set(`data/neighbors/${cellKey}.json`, {
				schema_version: 'neighbors.v2',
				build_info: buildInfo,
				cell_key: cellKey,
				k: parallel[0]?.nearest_ids.length ?? 0,
				poster_ids: parallel.map((r) => r.poster_id),
				nearest_ids: parallel.map((r) => r.nearest_ids),
				nearest_distances: parallel.map((r) => r.nearest_distances),
				farthest_ids: parallel.map((r) => r.farthest_ids),
				farthest_distances: parallel.map((r) => r.farthest_distances)
			});
		}
	}

	// Stage 15 — atlas.parquet and neuroscape.parquet don't carry the
	// OHBM-2026-specific enrichment / standby tables; the post-loop
	// hydration steps below are OHBM-2026-only.
	//
	// Before returning, however, fold the neuroscape `neighbors_neuroscape`
	// table back onto every article so the abstract detail page +
	// inline detail panel can render the "Most similar" list without
	// loading a second shard. The parquet stores them in parallel
	// rows (one per pubmed_id) instead of inlined to keep the row
	// group compressible; the in-browser join is O(N) and cheap.
	if (isNeuroscape) {
		const articlesShard = out.get('data/neuroscape/articles.json') as
			| {
					articles?: Array<{
						pubmed_id: number;
						nearest_pubmed_ids?: number[];
						nearest_distances?: number[];
						umap_2d?: number[];
						umap_3d?: number[];
					}>;
			  }
			| undefined;
		// Spec 019 — geometry now lives in its own `coords` table; fold it
		// back onto every article so the existing /neuroscape/ render code
		// (which reads a.umap_2d / a.umap_3d) is unchanged.
		const coordsShard = out.get('data/neuroscape/coords.json') as
			| {
					coords?: Array<{
						pubmed_id: number;
						umap_2d: number[];
						umap_3d: number[];
					}>;
			  }
			| undefined;
		if (articlesShard?.articles && coordsShard?.coords) {
			const geoById = new Map<number, { umap_2d: number[]; umap_3d: number[] }>();
			for (const c of coordsShard.coords) {
				geoById.set(c.pubmed_id, { umap_2d: c.umap_2d, umap_3d: c.umap_3d });
			}
			for (const a of articlesShard.articles) {
				const hit = geoById.get(a.pubmed_id);
				if (hit) {
					a.umap_2d = hit.umap_2d;
					a.umap_3d = hit.umap_3d;
				}
			}
		}
		const neighboursShard = out.get('data/neuroscape/neighbors.json') as
			| {
					rows?: Array<{
						pubmed_id: number;
						nearest_pubmed_ids: number[];
						nearest_distances: number[];
					}>;
			  }
			| undefined;
		if (articlesShard?.articles && neighboursShard?.rows) {
			const byId = new Map<number, { ids: number[]; dists: number[] }>();
			for (const n of neighboursShard.rows) {
				byId.set(n.pubmed_id, {
					ids: n.nearest_pubmed_ids,
					dists: n.nearest_distances
				});
			}
			for (const a of articlesShard.articles) {
				const hit = byId.get(a.pubmed_id);
				if (hit) {
					a.nearest_pubmed_ids = hit.ids;
					a.nearest_distances = hit.dists;
				}
			}
		}
	}
	if (isAtlas || isNeuroscape) {
		return out;
	}

	// Combine the two flattened enrichment tables back into the
	// `{records: {String(poster_id): {claims, figures}}}` envelope.
	const claimsRow = outerRows.find((r) => r.table_name === 'enrichment_claims');
	const figuresRow = outerRows.find((r) => r.table_name === 'enrichment_figures');
	const claims = claimsRow ? await decodeBlob(claimsRow.table_bytes) : [];
	const figures = figuresRow ? await decodeBlob(figuresRow.table_bytes) : [];
	const records: Record<string, { claims: unknown[]; figures: unknown[] }> = {};
	for (const c of claims as Array<{ poster_id: number }>) {
		const k = String(c.poster_id);
		(records[k] ??= { claims: [], figures: [] }).claims.push(c);
	}
	for (const f of figures as Array<{ poster_id: number }>) {
		const k = String(f.poster_id);
		(records[k] ??= { claims: [], figures: [] }).figures.push(f);
	}
	// ai_provenance is lifted from the manifest. The envelope-level
	// model-id annotation can't ride along with the two flattened
	// per-row enrichment tables, so the python writer embeds it in
	// the manifest JSON. Missing keys collapse to null so the
	// `✨ AI` pill stays hidden when the corpus has no enrichment
	// model attribution.
	const aiProv = ((manifest as { enrichment_ai_provenance?: unknown } | null)
		?.enrichment_ai_provenance ?? {}) as {
		claims_model_id?: string | null;
		figures_model_id?: string | null;
	};
	out.set('data/enrichment.json', {
		schema_version: 'enrichment.v2',
		build_info: buildInfo,
		ai_provenance: {
			claims_model_id: aiProv.claims_model_id ?? null,
			figures_model_id: aiProv.figures_model_id ?? null
		},
		records
	});

	// Stage 11.1 US2 — hydrate the legacy `poster_standby: {first, second}`
	// STRUCT on every abstract record from the new v2 (standby_first_index,
	// standby_second_index) → standby_slots lookup. This keeps the existing
	// UI code (facets.ts, standby.ts) working unchanged during the
	// migration window. Once the next deploy clears, the v1 fallback +
	// the Intl-formatter memo cache can be retired.
	const slotsShard = out.get('data/standby_slots.json') as
		| { slots?: Array<{ slot_index: number; start_utc: Date | number }> }
		| undefined;
	if (slotsShard?.slots && Array.isArray(slotsShard.slots)) {
		const slotByIndex = new Map<number, Date | number>();
		for (const s of slotsShard.slots) {
			slotByIndex.set(Number(s.slot_index), s.start_utc);
		}
		const abstractsShard = out.get('data/abstracts.json') as
			| { abstracts?: Array<Record<string, unknown>> }
			| undefined;
		if (abstractsShard?.abstracts) {
			for (const a of abstractsShard.abstracts) {
				const fi = a['standby_first_index'];
				const si = a['standby_second_index'];
				const first =
					fi == null ? null : slotByIndex.get(Number(fi)) ?? null;
				const second =
					si == null ? null : slotByIndex.get(Number(si)) ?? null;
				if (first !== null || second !== null) {
					a['poster_standby'] = { first, second };
				}
			}
		}
	}

	return out;
}

// ===========================================================================
// T043 — Cross-parquet drift assertion (R-012)
// ===========================================================================
//
// Atlas.parquet's manifest declares the sibling state-keys it was built
// against, e.g.
//
//   build_info.sibling_state_keys = { ohbm2026: '1ba5a9ea1efe',
//                                     neuroscape: '27f8f139b296' }
//
// The actual `ohbm2026.parquet` and `neuroscape.parquet` deployed beside
// it carry their own state-keys in their own manifests. If a deploy ever
// publishes a refreshed sibling without re-running the atlas builder, the
// `ohbm_overlay` rows in `atlas.parquet` will point at
// stale ids on the sibling subsite. R-012 mandates the atlas-root page
// detect this and render a visible banner rather than rendering a
// partial / silently-wrong scatter.
//
// Implementation: an HTTP-Range-only read of each sibling parquet's
// `manifest` row group via hyparquet's `asyncBufferFromUrl`. Hyparquet
// fetches just the footer (~few KB) and the manifest row group bytes (~1
// KB) — total network cost is sub-10 KB per sibling, not the full 26+96
// MB. The check is fired in parallel for both siblings; both must come
// back matching for `ok: true`.

export type AtlasDriftEntry = {
	sibling: 'ohbm2026' | 'neuroscape';
	expected: string; // state-key declared by atlas.parquet
	actual: string | null; // state-key read from the sibling's manifest
	reason: 'mismatch' | 'fetch-failed' | 'no-state-key';
	error_message?: string; // for fetch-failed: the underlying error
};

export type AtlasDriftResult =
	| { ok: true }
	| { ok: false; drift: AtlasDriftEntry[] };

function ohbm2026SiblingUrl(): string | null {
	const raw = (import.meta.env.VITE_DATA_PACKAGE_URL_OHBM2026 ?? null) as string | null;
	if (!raw) return null;
	return raw
		.replace(/^https:\/\/www\.dropbox\.com\//, 'https://dl.dropboxusercontent.com/')
		.replace(/[?&]dl=0(\b|$)/, (m) => m.replace('dl=0', ''));
}
function neuroscapeSiblingUrl(): string | null {
	const raw = (import.meta.env.VITE_DATA_PACKAGE_URL_NEUROSCAPE ?? null) as string | null;
	if (!raw) return null;
	return raw
		.replace(/^https:\/\/www\.dropbox\.com\//, 'https://dl.dropboxusercontent.com/')
		.replace(/[?&]dl=0(\b|$)/, (m) => m.replace('dl=0', ''));
}

/**
 * Read just the state_key from a sibling parquet's manifest row group.
 *
 * Network strategy: hyparquet's `asyncBufferFromUrl` uses HTTP Range
 * requests so we don't pay the full 26-96 MB to read a few KB of
 * manifest. But a single failure (transient network, Dropbox
 * throttling on rapid-fire Range requests, etc.) shouldn't lose us
 * the entire check — retry with exponential backoff before giving up.
 *
 * Throws on persistent failure. The caller (verifyAtlasSiblingDrift)
 * catches and classifies as `reason: 'fetch-failed'`.
 */
const SIBLING_FETCH_RETRY_DELAYS_MS = [400, 1200, 3000] as const;

async function readSiblingStateKey(url: string): Promise<string | null> {
	let lastErr: unknown = null;
	for (let attempt = 0; attempt <= SIBLING_FETCH_RETRY_DELAYS_MS.length; attempt++) {
		try {
			const file = await asyncBufferFromUrl({ url });
			const rows = (await parquetReadObjects({
				file,
				compressors,
				utf8: false
			})) as Array<{ table_name?: string; table_bytes?: Uint8Array }>;
			const manifestRow = rows.find((r) => r.table_name === 'manifest');
			if (!manifestRow?.table_bytes) return null;
			const innerFile = bytesAsAsyncBuffer(manifestRow.table_bytes);
			const inner = (await parquetReadObjects({ file: innerFile, compressors })) as Array<{
				manifest_json?: string;
			}>;
			const json = inner[0]?.manifest_json;
			if (!json) return null;
			const meta = JSON.parse(json) as {
				build_info?: { state_key?: string; corpus_state_key?: string };
			};
			return meta.build_info?.state_key ?? meta.build_info?.corpus_state_key ?? null;
		} catch (err) {
			lastErr = err;
			if (attempt < SIBLING_FETCH_RETRY_DELAYS_MS.length) {
				await new Promise<void>((r) =>
					setTimeout(r, SIBLING_FETCH_RETRY_DELAYS_MS[attempt])
				);
			}
		}
	}
	// All retries exhausted — propagate so the caller can record the
	// fetch-failed entry with an informative reason.
	throw lastErr instanceof Error
		? lastErr
		: new Error(`sibling parquet fetch failed for ${url}: ${String(lastErr)}`);
}

/**
 * Spec 019 / T024 — range-fetch one cluster's vectors from
 * `neuroscape_vectors.parquet`. Uses hyparquet's `asyncBufferFromUrl`
 * + predicate-pushdown on `cluster_id` so only the matching row groups
 * cross the network.
 *
 * Returned arrays are BigInt64Array (pubmed_ids) + Int8Array (vectors
 * as a flat `[N * 384]` byte buffer). The ranker
 * (`$lib/search/neuroscape_ranker`) transfers them to the worker via
 * `loadCluster`.
 */
export async function loadClusterVectors(
	url: string,
	clusterId: number
): Promise<{ pubmed_ids: BigInt64Array; vectors: Int8Array }> {
	const file = await asyncBufferFromUrl({ url });
	// hyparquet supports `filter` for predicate pushdown via row-group
	// stats. The parquet writer (semantic_index.py) sorts rows by
	// cluster_id so row groups have non-overlapping cluster_id ranges, and
	// the MongoDB-style `{ cluster_id: { $eq: clusterId } }` predicate skips
	// every row group whose min/max range doesn't include clusterId. (Object
	// keys are column names; the prior `{ column, value }` shape was wrong —
	// hyparquet read "column"/"value" as the column names and threw
	// `parquet filter columns not found`, breaking the ranker on every
	// query.)
	const rows = (await parquetReadObjects({
		file,
		compressors,
		utf8: false,
		filter: { cluster_id: { $eq: clusterId } }
	})) as Array<{
		cluster_id?: number;
		pubmed_id?: bigint | number;
		minilm_vector?: Uint8Array;
	}>;
	const matched = rows.filter((r) => Number(r.cluster_id) === clusterId);
	const n = matched.length;
	const pubmed_ids = new BigInt64Array(n);
	const vectors = new Int8Array(n * 384);
	for (let i = 0; i < n; i++) {
		const r = matched[i];
		pubmed_ids[i] =
			typeof r.pubmed_id === 'bigint' ? r.pubmed_id : BigInt(r.pubmed_id ?? 0);
		const v = r.minilm_vector;
		if (!v || v.length !== 384) continue;
		vectors.set(new Int8Array(v.buffer, v.byteOffset, v.byteLength), i * 384);
	}
	return { pubmed_ids, vectors };
}

/** Spec 019 — quantisation + drift metadata read from the
 *  `neuroscape_vectors.parquet` footer (file-level `manifest_json`
 *  key/value metadata written by semantic_index.py). */
export interface VectorsManifest {
	/** Single global INT8 scale: int8 = round(float * scale). The worker
	 *  dequantises with invScale = 1/scale during cosine scoring. */
	scale: number;
	/** Embedding dimensionality (384 for MiniLM-L6-v2). */
	dim: number;
	/** sha256 of the corpus-side model file — pinned for the R-010
	 *  matched-pair drift gate. */
	model_sha256: string | null;
}

/**
 * Spec 019 — read the vectors sidecar's quantisation manifest from its
 * Parquet footer. hyparquet's `parquetMetadataAsync` issues only the
 * tail Range request(s) needed for the footer, so this costs a few KB,
 * not the full ~170 MB file. Returns `null` when the URL is unset or
 * the footer carries no `manifest_json` (older build) — the caller
 * treats that as "full ranker unavailable" and keeps the KNN fallback.
 */
export async function loadVectorsManifest(url: string): Promise<VectorsManifest | null> {
	const file = await asyncBufferFromUrl({ url });
	const meta = await parquetMetadataAsync(file);
	const kv = meta.key_value_metadata ?? [];
	const entry = kv.find((e) => e.key === 'manifest_json');
	if (!entry?.value) return null;
	const m = JSON.parse(entry.value) as {
		scale?: number;
		vector_dim?: number;
		model_sha256?: string;
	};
	if (typeof m.scale !== 'number' || typeof m.vector_dim !== 'number') return null;
	return { scale: m.scale, dim: m.vector_dim, model_sha256: m.model_sha256 ?? null };
}

/**
 * Spec 019 — range-fetch the `cluster_centroids` table from the sibling
 * `neuroscape.parquet` without downloading the whole ~97 MB corpus file.
 *
 * The main parquets are a nested envelope: an outer parquet with one row
 * per inner table (`table_name`, `table_bytes` BLOB), written
 * `row_group_size=1` precisely so a browser can pull one inner table in
 * isolation. A `{ table_name: { $eq: 'cluster_centroids' } }` predicate
 * skips every other row group via row-group stats (same strategy
 * `loadClusterVectors` uses on the flat vectors sidecar), so only the
 * ~268 KB centroid blob (175 clusters × 384-dim) crosses the network.
 *
 * Used by atlas-root, whose own `atlas.parquet` carries no centroid table.
 * Returns `null` when the neuroscape sibling URL is unset or the table is
 * absent (older build) — the caller then keeps the KNN-only fallback and
 * logs loudly (CA-006). Shape matches `shards.loadClusterCentroids`.
 */
export async function loadClusterCentroidsFromNeuroscape(): Promise<Array<{
	cluster_id: number;
	centroid_vector: Float32Array;
	member_count: number;
}> | null> {
	const url = neuroscapeSiblingUrl();
	if (!url) return null;
	const file = await asyncBufferFromUrl({ url });
	const outer = (await parquetReadObjects({
		file,
		compressors,
		utf8: false,
		filter: { table_name: { $eq: 'cluster_centroids' } }
	})) as Array<{ table_name?: string; table_bytes?: Uint8Array }>;
	const match = outer.find((r) => r.table_name === 'cluster_centroids');
	if (!match?.table_bytes) return null;
	const rows = (await decodeBlob(match.table_bytes)) as Array<{
		cluster_id: number | bigint;
		centroid_vector: number[] | Float32Array;
		member_count: number | bigint;
	}>;
	if (rows.length === 0) return null;
	return rows.map((r) => ({
		cluster_id: Number(r.cluster_id),
		centroid_vector:
			r.centroid_vector instanceof Float32Array
				? r.centroid_vector
				: new Float32Array(r.centroid_vector),
		member_count: Number(r.member_count)
	}));
}

/**
 * Spec 019 — range-fetch the `clusters` legend table from the sibling
 * `neuroscape.parquet`. atlas.parquet no longer duplicates it; the
 * atlas-root cluster legend (id, label, colour, member_count) is pulled
 * from the single source of truth via the same row_group_size=1
 * predicate-pushdown trick as loadClusterCentroidsFromNeuroscape().
 * Returns `null` when the sibling URL is unset or the table is absent.
 */
export async function loadClustersFromNeuroscape(): Promise<Array<
	Record<string, unknown>
> | null> {
	const url = neuroscapeSiblingUrl();
	if (!url) return null;
	const file = await asyncBufferFromUrl({ url });
	const outer = (await parquetReadObjects({
		file,
		compressors,
		utf8: false,
		filter: { table_name: { $eq: 'clusters' } }
	})) as Array<{ table_name?: string; table_bytes?: Uint8Array }>;
	const match = outer.find((r) => r.table_name === 'clusters');
	if (!match?.table_bytes) return null;
	const rows = (await decodeBlob(match.table_bytes)) as Array<Record<string, unknown>>;
	if (rows.length === 0) return null;
	return rows;
}

/**
 * Spec 019 — range-fetch the self-contained `backdrop_decimated` scatter
 * sample from the sibling `neuroscape.parquet`. This table moved out of
 * atlas.parquet: each row carries its own pubmed_id, cluster_id, umap_2d,
 * umap_3d, title, year, so the atlas-root landing backdrop renders from a
 * single range fetch without joining the full corpus. Returns `null` when
 * the sibling URL is unset or the table is absent.
 */
export async function loadBackdropDecimatedFromNeuroscape(): Promise<Array<
	Record<string, unknown>
> | null> {
	const url = neuroscapeSiblingUrl();
	if (!url) return null;
	const file = await asyncBufferFromUrl({ url });
	const outer = (await parquetReadObjects({
		file,
		compressors,
		utf8: false,
		filter: { table_name: { $eq: 'backdrop_decimated' } }
	})) as Array<{ table_name?: string; table_bytes?: Uint8Array }>;
	const match = outer.find((r) => r.table_name === 'backdrop_decimated');
	if (!match?.table_bytes) return null;
	const rows = (await decodeBlob(match.table_bytes)) as Array<Record<string, unknown>>;
	if (rows.length === 0) return null;
	return rows;
}

/**
 * Verify that the sibling parquets currently published match what
 * `atlas.parquet` was built against. Returns `{ok: true}` on match,
 * `{ok: false, drift: [...]}` on any mismatch / fetch error so the
 * UI can render a banner.
 *
 * Safe to call when SITE_MODE !== 'atlas-root' (returns ok: true) and
 * when sibling URLs aren't configured (returns ok: true — there's
 * nothing to check against; treats absence as "trust the local
 * build").
 */
export async function verifyAtlasSiblingDrift(
	atlasManifest: unknown
): Promise<AtlasDriftResult> {
	if (SITE_MODE !== 'atlas-root') return { ok: true };
	const m = atlasManifest as
		| { build_info?: { sibling_state_keys?: Record<string, string> } }
		| null;
	const siblingKeys = m?.build_info?.sibling_state_keys ?? null;
	if (!siblingKeys) return { ok: true };

	const drift: AtlasDriftEntry[] = [];
	const checks: Array<Promise<void>> = [];

	const expectedOhbm = siblingKeys.ohbm2026;
	const ohbmUrl = ohbm2026SiblingUrl();
	if (expectedOhbm && ohbmUrl) {
		checks.push(
			readSiblingStateKey(ohbmUrl)
				.then((actual) => {
					if (actual === null) {
						drift.push({
							sibling: 'ohbm2026',
							expected: expectedOhbm,
							actual: null,
							reason: 'no-state-key'
						});
					} else if (actual !== expectedOhbm) {
						drift.push({
							sibling: 'ohbm2026',
							expected: expectedOhbm,
							actual,
							reason: 'mismatch'
						});
					}
				})
				.catch((err) => {
					drift.push({
						sibling: 'ohbm2026',
						expected: expectedOhbm,
						actual: null,
						reason: 'fetch-failed',
						error_message: err instanceof Error ? err.message : String(err)
					});
				})
		);
	}

	const expectedNeuro = siblingKeys.neuroscape;
	const neuroUrl = neuroscapeSiblingUrl();
	if (expectedNeuro && neuroUrl) {
		checks.push(
			readSiblingStateKey(neuroUrl)
				.then((actual) => {
					if (actual === null) {
						drift.push({
							sibling: 'neuroscape',
							expected: expectedNeuro,
							actual: null,
							reason: 'no-state-key'
						});
					} else if (actual !== expectedNeuro) {
						drift.push({
							sibling: 'neuroscape',
							expected: expectedNeuro,
							actual,
							reason: 'mismatch'
						});
					}
				})
				.catch((err) => {
					drift.push({
						sibling: 'neuroscape',
						expected: expectedNeuro,
						actual: null,
						reason: 'fetch-failed',
						error_message: err instanceof Error ? err.message : String(err)
					});
				})
		);
	}

	await Promise.all(checks);
	if (drift.length === 0) return { ok: true };
	return { ok: false, drift };
}
