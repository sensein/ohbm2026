import { base } from '$app/paths';

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

let manifestCache: Promise<Manifest | null> | null = null;
let abstractsCache: Promise<AbstractsShard | null> | null = null;
let authorsCache: Promise<AuthorsShard | null> | null = null;
const cellCache: Map<string, Promise<CellShard | null>> = new Map();
const topicsCache: Map<string, Promise<TopicShard | null>> = new Map();

async function fetchJson<T>(url: string, fetcher: typeof fetch): Promise<T | null> {
	try {
		const response = await fetcher(url);
		if (!response.ok) return null;
		return (await response.json()) as T;
	} catch {
		return null;
	}
}

export function loadManifest(fetcher: typeof fetch = fetch): Promise<Manifest | null> {
	if (manifestCache === null) {
		manifestCache = fetchJson<Manifest>(`${base}/data/manifest.json`, fetcher);
	}
	return manifestCache;
}

export function loadAbstracts(fetcher: typeof fetch = fetch): Promise<AbstractsShard | null> {
	if (abstractsCache === null) {
		abstractsCache = fetchJson<AbstractsShard>(`${base}/data/abstracts.json`, fetcher);
	}
	return abstractsCache;
}

export function loadAuthors(fetcher: typeof fetch = fetch): Promise<AuthorsShard | null> {
	if (authorsCache === null) {
		authorsCache = fetchJson<AuthorsShard>(`${base}/data/authors.json`, fetcher);
	}
	return authorsCache;
}

/**
 * Load a per-(model, input) cell shard. Cached per cell_key so switching
 * back to a previously-viewed cell is instant.
 */
export function loadCell(
	cellKey: string,
	fetcher: typeof fetch = fetch
): Promise<CellShard | null> {
	if (!cellCache.has(cellKey)) {
		cellCache.set(cellKey, fetchJson<CellShard>(`${base}/data/cells/${cellKey}.json`, fetcher));
	}
	return cellCache.get(cellKey)!;
}

/**
 * Load a per-(model, input, kind) topics shard. `kind` is one of
 * `communities` | `topic_clusters` | `neuroscape_clusters`. Cached by
 * the full (cell_key, kind) tuple.
 */
export function loadTopics(
	cellKey: string,
	kind: string,
	fetcher: typeof fetch = fetch
): Promise<TopicShard | null> {
	const key = `${cellKey}__${kind}`;
	if (!topicsCache.has(key)) {
		topicsCache.set(
			key,
			fetchJson<TopicShard>(`${base}/data/topics/${cellKey}_${kind}.json`, fetcher)
		);
	}
	return topicsCache.get(key)!;
}

export function resetCachesForTests(): void {
	manifestCache = null;
	abstractsCache = null;
	authorsCache = null;
	cellCache.clear();
	topicsCache.clear();
}
