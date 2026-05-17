import { base } from '$app/paths';

export interface BuildInfo {
	corpus_state_key: string;
	code_revision: string;
	code_revision_short: string;
	stage4_rollup_state_key: string;
	built_at: string;
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

let manifestCache: Promise<Manifest | null> | null = null;

export function loadManifest(fetcher: typeof fetch = fetch): Promise<Manifest | null> {
	if (manifestCache === null) {
		manifestCache = (async () => {
			try {
				const response = await fetcher(`${base}/data/manifest.json`);
				if (!response.ok) return null;
				return (await response.json()) as Manifest;
			} catch {
				return null;
			}
		})();
	}
	return manifestCache;
}

export function resetManifestCacheForTests(): void {
	manifestCache = null;
}
