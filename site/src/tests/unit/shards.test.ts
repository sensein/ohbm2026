import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
	loadAbstracts,
	loadAuthors,
	loadCell,
	loadManifest,
	loadTopics,
	type AbstractsShard,
	type AuthorsShard,
	type CellShard,
	type Manifest,
	type TopicShard
} from '$lib/shards';
// Stage-10: the parquet loader lives under `$lib/data_package/loader`.
// The spy targets the binding that `shards.ts` actually imports from —
// the canonical home — not any re-export.
import * as dataPackage from '$lib/data_package/loader';

const BUILD_INFO = {
	corpus_state_key: 'test12345678',
	code_revision: 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2',
	code_revision_short: 'a1b2c3d',
	stage4_rollup_state_key: 'test12345678',
	built_at: '2026-05-17T00:00:00+00:00'
};

const MANIFEST: Manifest = {
	schema_version: 'ui.v1',
	build_info: BUILD_INFO,
	corpus_count: 1,
	default_cell: { model: 'neuroscape', input: 'abstract' },
	models: ['neuroscape'],
	inputs: ['abstract'],
	cells: [],
	facets: [],
	search: {
		lexical_index: 'data/search/lexical_index.json',
		minilm_vectors: 'data/search/minilm_vectors.bin',
		minilm_vectors_build_info_url: 'data/search/minilm_vectors.build_info.json',
		minilm_dim: 384,
		minilm_dtype: 'int8'
	}
};

const ABSTRACTS: AbstractsShard = {
	schema_version: 'abstracts.v1',
	build_info: BUILD_INFO,
	abstracts: [
		{
			abstract_id: 1001,
			poster_id: 'M-AM-101',
			title: 'Memory fMRI in aging',
			accepted_for: 'Poster',
			sections: { introduction: '', methods: '', results: '', conclusion: '', references: '' },
			topics: {
				primary: 'Lifespan Development',
				primary_subcategory: 'Aging',
				secondary: '',
				secondary_subcategory: ''
			},
			methods_checklist: ['Functional MRI'],
			facets: {},
			author_ids: [0],
			reference_dois: [],
			reference_urls: []
		}
	]
};

const AUTHORS: AuthorsShard = {
	schema_version: 'authors.v1',
	build_info: BUILD_INFO,
	authors: [{ author_id: 0, name: 'Jane Smith', affiliations: ['Stanford'], abstract_ids: [1001] }]
};

const CELL: CellShard = {
	schema_version: 'cell.v1',
	build_info: BUILD_INFO,
	cell_key: 'neuroscape_abstract',
	rows: [
		{
			abstract_id: 1001,
			umap2d: [0.1, 0.2],
			umap3d: [0.1, 0.2, 0.3],
			community_id: 7,
			topic_cluster_id: 100,
			neuroscape_cluster_id: 42,
			neuroscape_cluster_distance: 0.5
		}
	]
};

const TOPICS: TopicShard = {
	schema_version: 'topics.v1',
	build_info: BUILD_INFO,
	cell_key: 'neuroscape_abstract',
	kind: 'communities',
	topics: [
		{ cluster_id: 7, keywords: ['memory'], title: 'Memory cluster', description: '', focus: '' }
	]
};

function mockPackage(entries: Record<string, unknown>) {
	const map = new Map(Object.entries(entries));
	vi.spyOn(dataPackage, 'loadDataPackage').mockResolvedValue(map);
}

describe('shard loaders (in-memory data-package map)', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it('loadManifest reads `data/manifest.json` from the map', async () => {
		mockPackage({ 'data/manifest.json': MANIFEST });
		const m = await loadManifest();
		expect(m).not.toBeNull();
		expect(m?.schema_version).toBe('ui.v1');
		expect(m?.build_info.code_revision_short).toBe('a1b2c3d');
		expect(m?.corpus_count).toBe(1);
	});

	it('loadAbstracts reads `data/abstracts.json` from the map', async () => {
		mockPackage({ 'data/abstracts.json': ABSTRACTS });
		const a = await loadAbstracts();
		expect(a?.abstracts).toHaveLength(1);
		expect(a?.abstracts[0].poster_id).toBe('M-AM-101');
	});

	it('loadAuthors reads `data/authors.json` from the map', async () => {
		mockPackage({ 'data/authors.json': AUTHORS });
		const au = await loadAuthors();
		expect(au?.authors[0].name).toBe('Jane Smith');
	});

	it('loadCell reads `data/cells/<cell_key>.json` from the map', async () => {
		mockPackage({ 'data/cells/neuroscape_abstract.json': CELL });
		const c = await loadCell('neuroscape_abstract');
		expect(c?.cell_key).toBe('neuroscape_abstract');
		expect(c?.rows[0].neuroscape_cluster_id).toBe(42);
	});

	it('loadTopics reads `data/topics/<cell_key>_<kind>.json` from the map', async () => {
		mockPackage({ 'data/topics/neuroscape_abstract_communities.json': TOPICS });
		const t = await loadTopics('neuroscape_abstract', 'communities');
		expect(t?.topics[0].title).toBe('Memory cluster');
	});

	it('returns null when the package map is unavailable (no URL set / CORS failure)', async () => {
		vi.spyOn(dataPackage, 'loadDataPackage').mockResolvedValue(null);
		expect(await loadManifest()).toBeNull();
		expect(await loadAbstracts()).toBeNull();
		expect(await loadCell('whatever')).toBeNull();
	});

	it('returns null when the path is missing from the map', async () => {
		mockPackage({ 'data/manifest.json': MANIFEST });
		expect(await loadCell('not_a_cell')).toBeNull();
	});
});
