import { base } from '$app/paths';
import { loadDataPackage } from './data_package/loader';

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
	/**
	 * Stage 10: the user-facing poster id is the sole identifier across
	 * the export. Stored as INT16 in the parquet (range 1–3333),
	 * surfaces as `number` here. The Oxford submission id no longer
	 * appears in the data package; the canonical reverse map lives in
	 * `data/primary/abstracts.json` for traceability.
	 *
	 * For display, zero-pad to 4 digits with `String(poster_id).padStart(4, '0')`.
	 */
	poster_id: number;
	title: string;
	accepted_for: string;
	sections: {
		introduction: string;
		methods: string;
		results: string;
		conclusion: string;
		references: string;
		/**
		 * Stage 12 US1 — trimmed `Acknowledgement` response. Optional
		 * because older parquet shards (pre-Stage-12) don't carry the
		 * field; the SvelteKit `loader.ts` doesn't backfill. Empty
		 * string means "present but blank"; `undefined` means "shard
		 * was emitted before Stage 12". UI MUST treat both as absent.
		 * See `specs/013-book-layout-polish/`.
		 */
		acknowledgments?: string;
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
	/**
	 * Poster stand-by times sourced from the FINAL OHBM 2026 poster-
	 * listing CSV (keyed by poster_id). Both windows are exactly one
	 * hour; values are UTC. `null` means the schedule row did not
	 * carry that slot (rare — every accepted poster has both windows
	 * in the FINAL listing). Local-time display lives in the UI; the
	 * data layer keeps UTC for sortability + portability.
	 *
	 * Stage 11.1 v2 transport: the parquet emits two INT8
	 * `standby_first_index` / `standby_second_index` columns referencing
	 * the new `standby_slots` table. The loader (loader.ts) hydrates
	 * this `poster_standby` field from the v2 indices so existing UI
	 * code keeps working unchanged.
	 */
	poster_standby?: {
		first: Date | number | null;
		second: Date | number | null;
	};
	/** Stage 11.1 v2 wire field — index into `standby_slots`. */
	standby_first_index?: number | null;
	/** Stage 11.1 v2 wire field — index into `standby_slots`. */
	standby_second_index?: number | null;
}

/**
 * One row of the Stage 11.1 v2 `standby_slots` table — a global
 * lookup carrying pre-rendered Paris-local display labels for each
 * of OHBM 2026's 8 program windows. Loaded once per session; the
 * UI's `standby.ts` reads `display_label` directly (no
 * Intl.DateTimeFormat work at facet-recompute time).
 */
export interface StandbySlot {
	slot_index: number;
	start_utc: Date | number;
	end_utc: Date | number;
	display_label: string;
}

export interface StandbySlotsShard {
	schema_version: string;
	build_info: BuildInfo;
	slots: StandbySlot[];
}

export interface AuthorRecord {
	author_id: number;
	name: string;
	affiliations: string[];
	poster_ids: number[];
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
	poster_id: number;
	umap2d: [number, number];
	umap3d: [number, number, number];
	community_id: number;
	topic_cluster_id: number;
	neuroscape_cluster_id?: number;
	neuroscape_cluster_distance?: number;
	/**
	 * True when the abstract has no UMAP projection (emitted by
	 * `ui_data/cells.py` when an abstract is in the corpus but
	 * neither 2D nor 3D UMAP coordinates resolved). Stage-10 carry-
	 * over flag — UI filters these out so they don't render at the
	 * origin or skew lasso selections.
	 */
	umap_missing?: boolean;
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

export interface ClaimRecord {
	claim: string;
	claim_type?: string;
	evidence?: string;
	evidence_eco_codes?: string[];
	source?: string;
	source_quote_verified?: boolean;
}

export interface FigureRecord {
	interpretation: string;
	keywords?: string[];
	ocr_text?: string;
	question_name?: string;
	model_quality_estimate?: string;
}

export interface EnrichmentRecord {
	claims: ClaimRecord[];
	figures: FigureRecord[];
}

export interface EnrichmentShard {
	schema_version: string;
	build_info: BuildInfo;
	ai_provenance: { claims_model_id: string | null; figures_model_id: string | null };
	// key = String(poster_id)
	records: Record<string, EnrichmentRecord>;
}

export interface NeighborsShard {
	schema_version: string;
	build_info: BuildInfo;
	cell_key: string;
	k: number;
	poster_ids: number[];
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

/**
 * Load every per-cell `data/neighbors/*.json` shard currently in the data
 * package, keyed by cell_key. Cheap — the data package is already a Map
 * resident in memory after first paint. Used by the detail panel to
 * surface a corpus-wide view of related abstracts rather than one biased
 * by the active (model, input) cell.
 */
export async function loadAllNeighbors(): Promise<Map<string, NeighborsShard>> {
	const pkg = await loadDataPackage();
	const out = new Map<string, NeighborsShard>();
	if (!pkg) return out;
	const prefix = 'data/neighbors/';
	for (const [path, v] of pkg) {
		if (!path.startsWith(prefix) || !path.endsWith('.json')) continue;
		const shard = v as NeighborsShard;
		out.set(shard.cell_key, shard);
	}
	return out;
}

/**
 * Load every per-cell shard + its matching `communities` topics shard so the
 * detail panel can render this abstract's cluster membership across all 15
 * (model, input) approaches. Returns a map of cell_key → { cell, topics }.
 */
export async function loadAllCellsWithTopics(): Promise<
	Map<string, { cell: CellShard; topics: TopicShard | null }>
> {
	const pkg = await loadDataPackage();
	const out = new Map<string, { cell: CellShard; topics: TopicShard | null }>();
	if (!pkg) return out;
	const cellPrefix = 'data/cells/';
	for (const [path, v] of pkg) {
		if (!path.startsWith(cellPrefix) || !path.endsWith('.json')) continue;
		const cell = v as CellShard;
		const topicsPath = `data/topics/${cell.cell_key}_communities.json`;
		const topics = (pkg.get(topicsPath) as TopicShard | undefined) ?? null;
		out.set(cell.cell_key, { cell, topics });
	}
	return out;
}

export function loadEnrichment(): Promise<EnrichmentShard | null> {
	return getFromPackage<EnrichmentShard>('data/enrichment.json');
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
	missing_poster_ids: number[];
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
