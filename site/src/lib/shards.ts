import { base } from '$app/paths';
import { loadDataPackage } from './data_package';

export interface BuildInfo {
	corpus_state_key: string;
	code_revision: string;
	code_revision_short: string;
	stage4_rollup_state_key: string;
	built_at: string;
}

/**
 * Build-time fallback when the data-package builder hasn't run (e.g. the
 * placeholder deploy where Stage 1–4 inputs aren't materialized in CI). The
 * Vite env vars `VITE_BUILD_SHA` / `VITE_BUILD_SHA_SHORT` / `VITE_BUILD_AT`
 * are populated by the deploy workflow before `pnpm build`. Local dev (no
 * env vars set) returns null so the UI doesn't display stale data.
 */
export function buildInfoFromEnv(): BuildInfo | null {
	const sha = import.meta.env.VITE_BUILD_SHA;
	const short = import.meta.env.VITE_BUILD_SHA_SHORT;
	const at = import.meta.env.VITE_BUILD_AT;
	if (!sha || !short) return null;
	return {
		corpus_state_key: 'placeholder',
		code_revision: sha,
		code_revision_short: short,
		stage4_rollup_state_key: 'placeholder',
		built_at: at || ''
	};
}

export interface Manifest {
	schema_version: string;
	build_info: BuildInfo;
	corpus_count: number;
	default_cell: { model: string; input: string };
	models: string[];
	inputs: string[];
	cells: Array<{
		cell_key: string;
		model: string;
		input: string;
		shard_url: string;
		topic_shards: Record<string, string>;
	}>;
	facets: Array<{ key: string; label: string; options: string[] }>;
	search: {
		lexical_index: string;
		minilm_vectors: string;
		minilm_vectors_build_info_url: string;
		minilm_dim: number;
		minilm_dtype: string;
	};
}

export interface AbstractRecord {
	abstract_id: number;
	poster_id: string;
	title: string;
	accepted_for: string;
	sections: {
		introduction: string;
		methods: string;
		results: string;
		conclusion: string;
		references: string;
	};
	topics: {
		primary: string;
		primary_subcategory: string;
		secondary: string;
		secondary_subcategory: string;
	};
	methods_checklist: string[];
	facets: Record<string, string | string[]>;
	author_ids: number[];
	reference_dois: string[];
	reference_urls: string[];
	reference_titles?: string[];
}

export interface AuthorRecord {
	author_id: number;
	name: string;
	affiliations: string[];
	abstract_ids: number[];
}

export interface AbstractsShard {
	schema_version: string;
	build_info: BuildInfo;
	abstracts: AbstractRecord[];
}

export interface AuthorsShard {
	schema_version: string;
	build_info: BuildInfo;
	authors: AuthorRecord[];
}

export interface CellRow {
	abstract_id: number;
	umap2d: [number, number];
	umap3d: [number, number, number];
	community_id: number;
	topic_cluster_id: number;
	neuroscape_cluster_id?: number;
	neuroscape_cluster_distance?: number;
}

export interface CellShard {
	schema_version: string;
	build_info: BuildInfo;
	cell_key: string;
	rows: CellRow[];
}

export interface TopicRecord {
	cluster_id: number;
	keywords: string[];
	title: string;
	description: string;
	focus: string;
}

export interface TopicShard {
	schema_version: string;
	build_info: BuildInfo;
	cell_key: string;
	kind: string;
	topics: TopicRecord[];
}

export interface NeighborsShard {
	schema_version: string;
	build_info: BuildInfo;
	cell_key: string;
	k: number;
	abstract_ids: number[];
	nearest_ids: number[][];
	nearest_distances: number[][];
	farthest_ids: number[][];
	farthest_distances: number[][];
}

/**
 * Per-(shard kind) lookups now read from a single in-memory `Map<path, json>`
 * built by `loadDataPackage()` on first paint. The path keys are tar-relative,
 * e.g. `data/manifest.json`, `data/cells/voyage_abstract.json`. When the
 * data package isn't reachable (no `VITE_DATA_PACKAGE_URL`, CORS failure,
 * network drop) every loader returns null — callers fall back to the
 * "data unavailable" placeholder.
 *
 * The `base` import + per-shard fetch URL machinery from prior versions is
 * gone: nothing is hosted on the same origin as the app anymore.
 */

void base; // base no longer used directly; keep import warm for any future relative asset

async function getFromPackage<T>(path: string): Promise<T | null> {
	const pkg = await loadDataPackage();
	if (!pkg) return null;
	const v = pkg.get(path);
	return (v as T | undefined) ?? null;
}

export function loadManifest(): Promise<Manifest | null> {
	return getFromPackage<Manifest>('data/manifest.json');
}

export function loadAbstracts(): Promise<AbstractsShard | null> {
	return getFromPackage<AbstractsShard>('data/abstracts.json');
}

export function loadAuthors(): Promise<AuthorsShard | null> {
	return getFromPackage<AuthorsShard>('data/authors.json');
}

export function loadCell(cellKey: string): Promise<CellShard | null> {
	return getFromPackage<CellShard>(`data/cells/${cellKey}.json`);
}

export function loadTopics(cellKey: string, kind: string): Promise<TopicShard | null> {
	return getFromPackage<TopicShard>(`data/topics/${cellKey}_${kind}.json`);
}

export function loadNeighbors(cellKey: string): Promise<NeighborsShard | null> {
	return getFromPackage<NeighborsShard>(`data/neighbors/${cellKey}.json`);
}

export interface MinilmVectorsSidecar {
	schema_version: string;
	build_info: BuildInfo;
	shape: [number, number];
	dtype: string;
	scale: number;
	max_abs_original: number;
	components: string[];
	component_state_keys: string[];
	missing_abstract_ids: number[];
	cosine_recovery_mae: number;
	byte_offset_url: string;
	note?: string;
}

export async function loadMinilmVectors(): Promise<{
	sidecar: MinilmVectorsSidecar;
	bytes: Uint8Array;
} | null> {
	const sidecar = await getFromPackage<MinilmVectorsSidecar>(
		'data/search/minilm_vectors.build_info.json'
	);
	if (!sidecar) return null;
	const pkg = await loadDataPackage();
	const bytes = pkg?.get('data/search/minilm_vectors.bin') as Uint8Array | undefined;
	if (!bytes) return null;
	return { sidecar, bytes };
}

export function resetCachesForTests(): void {
	// Caches now live on the data_package module; reset there.
}
