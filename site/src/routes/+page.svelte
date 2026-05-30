<script lang="ts">
	import { onMount } from 'svelte';
	import {
		buildInfoFromEnv,
		loadAbstracts,
		loadAuthors,
		loadCell,
		loadManifest,
		loadTopics,
		type AbstractRecord,
		type AuthorRecord,
		type BuildInfo,
		type CellShard,
		type Manifest,
		type TopicShard
	} from '$lib/shards';
	import { activeFilters, authorChips, cartOnly, debouncedSearchQuery, focusedAbstract, lassoSelection, searchQuery, selectedCell, showMap } from '$lib/stores/selection';
	import {
		buildTitleIndex,
		lexicalSearch,
		parseQuery,
		queryForSemantic,
		seedScores,
		type InvertedIndex
	} from '$lib/filter';
	import { filterByFacets, recomputeFacets, type FacetCellContext } from '$lib/facets';
	import { normaliseQuery, parseIdOperator } from '$lib/goto_poster';
	import SearchBar from '$lib/components/SearchBar.svelte';
	import ResultList from '$lib/components/ResultList.svelte';
	import DetailPanel from '$lib/components/DetailPanel.svelte';
	import ModelSelector from '$lib/components/ModelSelector.svelte';
	import UmapPanel from '$lib/components/UmapPanel.svelte';
	import FacetSidebar from '$lib/components/FacetSidebar.svelte';
	import { semanticEnabled } from '$lib/stores/searchMode';
	import { semanticStatus } from '$lib/search/semantic';
	import { cartStore } from '$lib/stores/cart';
	import {
		cartDrawerOpen,
		ohbmTitleLookup,
		neuroscapeTitleLookup
	} from '$lib/stores/cart_ui';
	// CartDrawer is mounted by `+layout.svelte` for all modes — no
	// import needed here.
	// Stage 15 (spec 015-neuroscape-context, FR-008/FR-009/FR-013/FR-014):
	// the bare-root cross-conference atlas landing page mounts a small
	// chrome (header + binary toggle + density slider) in place of the
	// existing OHBM-2026-only home page. SITE_MODE is a build-time
	// constant (Vite substitutes `import.meta.env.VITE_SITE_MODE` at
	// compile time), so the {#if SITE_MODE === 'atlas-root'} branch
	// below is dead-code eliminated in the 'ohbm2026' / 'neuroscape'
	// builds — FR-022 byte-identity is preserved.
	import { SITE_MODE } from '$lib/site_mode';
	// SiteHeader is rendered by `+layout.svelte` for ALL modes —
	// atlas-root + neuroscape no longer mount their own header here.
	// AtlasSubsiteNav is the hub-and-spoke nav strip; only mounted on
	// the atlas-root build (subsites surface a home icon instead).
	import AtlasSubsiteNav from '$lib/components/AtlasSubsiteNav.svelte';
	// AtlasOverlayToggle + BackdropDensitySlider + DimensionalityToggle
	// were removed from the atlas-root/neuroscape top-row to match the
	// OHBM 2026 UI shape. Overlay visibility is now driven by the
	// Sites facet (filterShowOhbm); opacity defaults to 0.05; both
	// 2D and 3D scatters are rendered side-by-side so no
	// dimensionality toggle is needed.
	// AtlasUmapPanel is now an alias for the unified UmapPanel — the
	// underlying file was deleted (Stage 15 UX-unification, slice D);
	// all three subsites use `UmapPanel` with mode='ohbm' | 'atlas' |
	// 'neuroscape'.
	import AtlasRootDetailPanel from '$lib/components/AtlasRootDetailPanel.svelte';
	// AtlasRootLassoResults retired (slice E) — lasso filters the
	// result list inline now, no modal needed.
	import AtlasRootBrowsePanel from '$lib/components/AtlasRootBrowsePanel.svelte';
	import AtlasRootFacets from '$lib/components/AtlasRootFacets.svelte';
	import NeuroscapeBrowsePanel from '$lib/components/NeuroscapeBrowsePanel.svelte';
	import NeuroscapeFacets from '$lib/components/NeuroscapeFacets.svelte';
	import { base } from '$app/paths';
	// atlasOverlay + dimensionality stores no longer driven from this
	// page (removed top-row toggles). Stores still exist for any
	// external consumer; tree-shaken from this bundle if unused.
	import {
		loadDataPackage,
		getDataPackageUrl,
		getNeuroscapeVectorsUrl,
		loadVectorsManifest,
		loadClusterVectors,
		loadClusterCentroidsFromNeuroscape,
		loadClustersFromNeuroscape,
		loadArticlesFromNeuroscape,
		loadCoordsFromNeuroscape,
		loadBackdropLevelFromNeuroscape,
		readNeuroscapeBackdropLevelCount,
		verifyAtlasSiblingDrift,
		type AtlasDriftEntry
	} from '$lib/data_package/loader';
	import { selectIdsInGeometry, type LassoGeometry } from '$lib/geo/lasso_select';
	import { loadClusterCentroids } from '$lib/shards';
	// Spec 019 / FR-002 — full cluster-routed semantic ranker. Wired in
	// when the `neuroscape_vectors.parquet` sidecar URL is configured;
	// otherwise the page keeps the KNN-only fallback below.
	import {
		initRanker,
		searchNeuroscape,
		expandSearchDepth as rankerExpandSearchDepth,
		defaultSemanticWorker,
		type RankerState,
		type KnnEntry
	} from '$lib/search/neuroscape_ranker';

	// Shapes the AtlasUmapPanel expects. Defined here (not imported
	// from the .svelte component) because Svelte's type re-export
	// path is unreliable across the build.
	type AtlasBackdropPoint = {
		pubmed_id: number;
		cluster_id: number;
		umap_2d?: [number, number];
		umap_3d: [number, number, number];
		title: string;
		year: number;
		// Populated by the loader's `neighbors_neuroscape` → articles
		// join (loader.ts). Present only on the /neuroscape/ build;
		// atlas-root's `backdrop` rows from atlas.parquet don't carry
		// neighbours.
		nearest_pubmed_ids?: number[];
		nearest_distances?: number[];
		// Quadtree LOD tier (spec 019 follow-up). Present on the
		// /neuroscape/ build (folded from `coords`); used to cap the
		// scatter to the blue-noise sample. atlas-root's per-tier rows
		// don't carry it (they're already the sample for that tier).
		lod_level?: number;
	};
	type AtlasOverlayPoint = {
		submission_id: number;
		poster_id: number;
		umap_2d?: [number, number];
		umap_3d: [number, number, number];
		title: string;
		nearest_cluster_id: number;
	};
	type AtlasClusterRow = {
		cluster_id: number;
		title: string;
		colour_hex: string;
		palette_tier: 'primary' | 'secondary';
	};
	// Minimal shape the lasso point-in-polygon test needs — satisfied by
	// AtlasBackdropPoint, AtlasOverlayPoint, and the lazily-fetched coords.
	type CoordPoint = { pubmed_id: number; umap_2d?: [number, number] };

	let manifest: Manifest | null = null;
	let abstracts: AbstractRecord[] = [];
	let authorsById: Map<number, AuthorRecord> = new Map();
	let abstractsByPosterId: Map<number, AbstractRecord> = new Map();
	let abstractsById: Map<number, AbstractRecord> = new Map();
	let loaded = false;
	let dataMissing = false;
	// `showMap` is now backed by a localStorage-persistent store
	// (`$lib/stores/selection.showMap`) so a browser reload keeps the
	// user's chosen view. Read/write via the `$showMap` Svelte sugar.
	// `cartOpen` was the OHBM-only local; the unifying cart drawer is
	// now controlled by the shared `cartDrawerOpen` store so the 🛒
	// in the SiteHeader can open it from any subsite.
	let semanticScores: Map<number, number> | null = null;
	let semanticQuerySerial = 0;
	// Spec 019 — full cluster-routed ranker wiring (FR-002 / T028
	// follow-up). `rankerReady` flips true once initRanker has run with
	// the production centroids + worker; until then the page uses the
	// KNN-only `neuroscapeKnnHits` fallback. `neuroscapeRankerHits` holds
	// the most recent async ranker result (pubmed_id → cosine).
	let rankerReady = false;
	let rankerState: RankerState | null = null;
	let rankerCapExceeded = false;
	let neuroscapeRankerHits: Map<number, number> = new Map();
	let neuroscapeRankerSerial = 0;
	// True when the most recent ranker query threw. While set, the
	// semantic-hit selection degrades to the KNN-only fallback instead of
	// showing empty results — otherwise a ranker that's "ready" but fails
	// on every query (e.g. a range-fetch/parquet error) would silently
	// zero out semantic search. The error is still logged loudly.
	let rankerErrored = false;
	// Bumped by the "Expand search depth" affordance to force the ranker
	// async block to re-run after `expandSearchDepth()` lifts the cap.
	let rankerDepthBump = 0;
	let showFacets = false; // mobile drawer state; desktop always-shown
	let cellShard: CellShard | null = null;
	let cellTopics: TopicShard | null = null;
	/**
	 * Per-page-load random rank over abstract ids. The home grid sorts by
	 * this when no search ranking applies so each visit shows a different
	 * sample first. The underlying `abstracts` array is left in canonical
	 * order — the semantic worker indexes vectors positionally and would
	 * misalign if we shuffled in place.
	 */
	let defaultRank: Map<number, number> | null = null;
	const envBuildInfo: BuildInfo | null = buildInfoFromEnv();

	function buildRandomRank(records: AbstractRecord[]): Map<number, number> {
		const ids = records.map((r) => r.poster_id);
		// Fisher-Yates shuffle.
		for (let i = ids.length - 1; i > 0; i--) {
			const j = Math.floor(Math.random() * (i + 1));
			[ids[i], ids[j]] = [ids[j], ids[i]];
		}
		const out = new Map<number, number>();
		ids.forEach((id, idx) => out.set(id, idx));
		return out;
	}

	onMount(async () => {
		// Cart-restore deep-link: `<siteUrl>/?cart=0001,0042,...` merges
		// the listed poster_ids into the cart store on load. Used by the
		// "Email my list" link so a recipient (or sender on a different
		// machine) can rebuild the full saved-list state with one click.
		// Merge semantics — never clobber an existing cart silently.
		try {
			const sp = new URLSearchParams(window.location.search);
			const cartParam = sp.get('cart');
			if (cartParam) {
				const ids = cartParam
					.split(',')
					.map((s) => Number.parseInt(s.trim(), 10))
					.filter((n) => Number.isFinite(n) && n > 0);
				if (ids.length) {
					cartStore.addMany(ids);
				}
				// Strip the param from the visible URL so the user sees a
				// clean home URL after the restore (the cart is now in
				// localStorage; no need to keep the param around).
				sp.delete('cart');
				const cleanQuery = sp.toString();
				const cleanUrl =
					window.location.pathname +
					(cleanQuery ? `?${cleanQuery}` : '') +
					window.location.hash;
				window.history.replaceState({}, '', cleanUrl);
			}
		} catch {
			/* malformed query param — ignore */
		}

		const [m, a, au] = await Promise.all([loadManifest(), loadAbstracts(), loadAuthors()]);
		manifest = m;
		if (a && au) {
			abstracts = a.abstracts;
			defaultRank = buildRandomRank(abstracts);
			authorsById = new Map(au.authors.map((x) => [x.author_id, x]));
			abstractsByPosterId = new Map(
				a.abstracts.filter((x) => x.poster_id).map((x) => [x.poster_id, x])
			);
			abstractsById = new Map(a.abstracts.map((x) => [x.poster_id, x]));
			// Publish the OHBM title lookup so the unifying cart drawer
			// can render rich rows for OHBM items saved from any subsite.
			ohbmTitleLookup.set(
				new Map(
					a.abstracts
						.filter((x) => x.poster_id)
						.map((x) => {
							const leadId = x.author_ids[0];
							const lead = leadId !== undefined ? au.authors.find((y) => y.author_id === leadId)?.name : undefined;
							return [x.poster_id, { title: x.title, lead_author: lead }];
						})
				)
			);
			// Test-only debug global used by Playwright accepted-only invariant guard.
			if (typeof window !== 'undefined') {
				(window as unknown as { __abstracts: AbstractRecord[] }).__abstracts = abstracts;
			}
		} else {
			dataMissing = true;
		}
		loaded = true;
		if (!dataMissing) {
			// Warm the semantic worker in the background so the model is ready
			// the moment the user types. The worker does NOT influence ordering
			// while the search box is empty — the reactive block below nulls
			// `semanticScores` whenever `$searchQuery` is blank.
			void (async () => {
				try {
					const mod = await import('$lib/search/semantic');
					await mod.warmSemantic();
				} catch (err) {
					console.warn('semantic search unavailable:', err);
				}
			})();
			// Pre-build the lexical inverted index off the critical render
			// path. `lexicalSearch` lazy-builds + caches in a WeakMap; running
			// it once with a no-match token populates the cache. Schedule via
			// requestIdleCallback (or a 200 ms setTimeout fallback) so we
			// don't compete with the first interactive paint.
			const warmLexical = (): void => {
				void lexicalSearch(abstracts, authorsById, '__warm__');
			};
			if (typeof window !== 'undefined') {
				const w = window as unknown as {
					requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => void;
				};
				if (typeof w.requestIdleCallback === 'function') {
					w.requestIdleCallback(warmLexical, { timeout: 1500 });
				} else {
					setTimeout(warmLexical, 200);
				}
			}
		}
	});

	// Re-run semantic search on query change, with serial-number guard so
	// out-of-order completions don't overwrite a newer result. Skipped when
	// the user has disabled semantic via the toggle.
	//
	// When the query carries operators (quotes / `-` / `OR`), the semantic
	// embedder receives the operators-stripped form (positive content words
	// only) so the vector reflects the conceptual intent. Negation is still
	// honoured by subtracting `negationBlocked` from the semantic set in
	// `mergeSearch` — semantic has no native NOT.
	$: void (async (q: string, on: boolean) => {
		const trimmed = q.trim();
		if (!on || !trimmed) {
			semanticScores = null;
			return;
		}
		const parsed = parseQuery(trimmed);
		const forSemantic = parsed.hasOperators ? queryForSemantic(parsed) : trimmed;
		if (!forSemantic.trim()) {
			semanticScores = null;
			return;
		}
		const my = ++semanticQuerySerial;
		try {
			const mod = await import('$lib/search/semantic');
			const hits = await mod.semanticSearch(forSemantic, 50);
			if (my !== semanticQuerySerial) return;
			// Translate worker indices (positional in abstracts.json) → poster_id
			// AND preserve the per-hit cosine similarity so the card can show it.
			const scores = new Map<number, number>();
			for (const h of hits) {
				const rec = abstracts[h.index];
				if (rec) scores.set(rec.poster_id, h.score);
			}
			semanticScores = scores;
		} catch {
			if (my === semanticQuerySerial) semanticScores = null;
		}
	})($searchQuery, $semanticEnabled);

	$: lexicalResult = lexicalSearch(abstracts, authorsById, $searchQuery);
	$: lexicalIds = lexicalResult?.ids ?? null;
	$: lexicalExactness = lexicalResult?.exactness ?? null;
	$: lexicalNegationBlocked = lexicalResult?.negationBlocked ?? null;
	$: semanticIdsForMerge = semanticScores
		? new Set<number>(semanticScores.keys())
		: null;
	$: searchIds = mergeSearch(lexicalIds, semanticIdsForMerge, $searchQuery, lexicalNegationBlocked);

	// Stage 14 — `id:` operator narrows the result list to abstracts
	// whose poster_id's decimal form starts with the typed digits. When
	// the operator is active it REPLACES `searchIds` entirely (the
	// lexical/semantic pipeline doesn't apply to the literal `id:NNNN`
	// string). When the payload is empty (`id:` with no digits) or
	// matches nothing, the filter set is empty — the result list will
	// show 0 cards, which matches the dropdown's "no matches" hint.
	$: idPayload = parseIdOperator($searchQuery);
	$: idFilterIds = (() => {
		if (idPayload === null) return null;
		const q = normaliseQuery(idPayload);
		if (q === '') return new Set<number>();
		const out = new Set<number>();
		for (const id of abstractsByPosterId.keys()) {
			if (id.toString().startsWith(q)) out.add(id);
		}
		return out;
	})();
	$: effectiveSearchIds = idPayload !== null ? idFilterIds : searchIds;

	// Load the current (model, input) cell + its community topics so the
	// Cluster facet can offer per-cell options. The same data feeds the
	// UMAP panel; loadCell/loadTopics are cheap (Map-get from the in-memory
	// data package) so duplicating the load here is fine.
	$: cellKey = `${$selectedCell.model}_${$selectedCell.input}`;
	$: void (async () => {
		const key = cellKey;
		const [c, t] = await Promise.all([loadCell(key), loadTopics(key, 'communities')]);
		// Guard against late-arriving results after the user switched cells.
		if (key === cellKey) {
			cellShard = c;
			cellTopics = t;
		}
	})();
	$: facetCtx = buildFacetCtx(cellShard, cellTopics);
	$: facetIds = filterByFacets(abstracts, $activeFilters, facetCtx);
	$: cartIds = $cartOnly ? cartIdsFromStore(abstractsByPosterId, $cartStore) : null;
	// Build a Map<author_name, poster_ids> on the fly when the chip set
	// changes, then intersect. Empty chip set → null (no filter).
	$: authorChipIds = computeAuthorChipIds($authorChips, abstracts, authorsById);
	// Saved-only is a DOMINANT filter — when ON, it overrides the search /
	// facet / lasso state so the user sees their full saved list. Toggling
	// it off restores the prior filter state (search box text, active
	// facets, lasso are kept in their stores so they reappear). Facet
	// counts in Saved-only mode are computed over the saved set, so any
	// facets the user clicks while in this mode are advisory only — they
	// don't further narrow the result list until Saved-only is turned off.
	$: filteredIds = $cartOnly
		? cartIds
		: intersect(intersect(intersect(effectiveSearchIds, $lassoSelection), facetIds), authorChipIds);
	$: preFilterForFacetCounts = $cartOnly
		? cartIds
		: intersect(intersect(effectiveSearchIds, $lassoSelection), authorChipIds);
	$: facetCounts = recomputeFacets(abstracts, $activeFilters, preFilterForFacetCounts, facetCtx);

	function cartIdsFromStore(
		byPid: Map<number, AbstractRecord>,
		cart: Set<number>
	): Set<number> {
		const out = new Set<number>();
		for (const pid of cart) {
			const rec = byPid.get(pid);
			if (rec) out.add(rec.poster_id);
		}
		return out;
	}

	/**
	 * Given the active author chips, return the union of poster_ids
	 * whose author list contains any chip name. Empty chip set returns
	 * null (= no filter). Names match via case-insensitive + NFD-folded
	 * comparison so "García" and "Garcia" are equivalent.
	 */
	function computeAuthorChipIds(
		chips: Set<string>,
		all: AbstractRecord[],
		byId: Map<number, AuthorRecord>
	): Set<number> | null {
		if (!chips.size) return null;
		const norm = (s: string) =>
			s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase().trim();
		const wanted = new Set([...chips].map(norm));
		const out = new Set<number>();
		for (const rec of all) {
			for (const aid of rec.author_ids) {
				const name = byId.get(aid)?.name;
				if (name && wanted.has(norm(name))) {
					out.add(rec.poster_id);
					break;
				}
			}
		}
		return out;
	}

	function removeChip(name: string) {
		authorChips.update((s) => {
			if (!s.has(name)) return s;
			const next = new Set(s);
			next.delete(name);
			return next;
		});
	}
	function clearAllChips() {
		authorChips.set(new Set());
	}

	function buildFacetCtx(
		shard: CellShard | null,
		topics: TopicShard | null
	): FacetCellContext {
		const labelByCluster = new Map<number, string>();
		if (topics) {
			for (const t of topics.topics) {
				const label = t.title
					? t.title
					: t.keywords.length
						? t.keywords.slice(0, 3).join(', ')
						: `cluster ${t.cluster_id}`;
				labelByCluster.set(t.cluster_id, label);
			}
		}
		const clusterLabelByPosterId = new Map<number, string>();
		if (shard) {
			for (const row of shard.rows) {
				const label = labelByCluster.get(row.community_id);
				if (label) clusterLabelByPosterId.set(row.poster_id, label);
			}
		}
		return { clusterLabelByPosterId };
	}

	function mergeSearch(
		lex: Set<number> | null,
		sem: Set<number> | null,
		query: string,
		negationBlocked: Set<number> | null
	): Set<number> | null {
		if (!query.trim()) return null;
		if (lex === null && sem === null) return null;
		if (lex === null) return sem;
		if (sem === null) return lex;
		const union = new Set<number>(lex);
		// Honour `-clause` negations across semantic candidates too. Semantic
		// has no native NOT, so the merger subtracts any abstract that hit a
		// negated clause before unioning it in.
		for (const id of sem) {
			if (negationBlocked && negationBlocked.has(id)) continue;
			union.add(id);
		}
		return union;
	}
	$: focused = $focusedAbstract ? (abstractsByPosterId.get($focusedAbstract) ?? null) : null;

	function intersect(a: Set<number> | null, b: Set<number> | null): Set<number> | null {
		if (a === null && b === null) return null;
		if (a === null) return b;
		if (b === null) return a;
		const out: Set<number> = new Set();
		const [small, large] = a.size <= b.size ? [a, b] : [b, a];
		for (const id of small) if (large.has(id)) out.add(id);
		return out;
	}

	// Stage 15 — backdrop opacity for the bare-root atlas landing page
	// (FR-013). Not persisted (defaults to 0.25 on every visit per
	// contracts/atlas-root-ui.md). When SITE_MODE !== 'atlas-root' this
	// variable is unused and tree-shaken.
	let backdropDensity = 0.05;

	// Stage 15 — atlas.parquet / neuroscape.parquet hydration state.
	// Loaded lazily on mount when SITE_MODE !== 'ohbm2026'. The same
	// AtlasUmapPanel powers both modes; in neuroscape mode the
	// overlayPoints list stays empty (the OHBM 2026 overlay only
	// renders on the bare-root cross-conference page).
	let atlasBackdrop: AtlasBackdropPoint[] = [];
	// Spec 019 follow-up — the LIST + search corpus, decoupled from the
	// SCATTER source (`atlasBackdrop`). On /neuroscape/ both are the same
	// full 461k articles array (atlasBackdrop carries coords there). On
	// atlas-root they diverge: `atlasBackdrop` is the decimated 50k landing
	// scatter (carries umap coords, range-fetched from `backdrop_decimated`),
	// while `listCorpus` is the FULL ~461k identity table (no coords),
	// range-fetched from the sibling `articles` table so the result-list count
	// + lexical search cover the whole corpus rather than just the 50k sample.
	// Without this split atlas-root's no-query count regressed to ~53k
	// (50k decimated + 3.2k OHBM overlay) instead of the full corpus.
	let listCorpus: AtlasBackdropPoint[] = [];
	let atlasOverlayPoints: AtlasOverlayPoint[] = [];
	let atlasClusters: AtlasClusterRow[] = [];
	// Spec 019 follow-up — /neuroscape/ loads the full 461k corpus for
	// search + result-list, but renders the SCATTER from the quadtree
	// blue-noise sample only (lod_level <= cap), which preserves the
	// overall shape while keeping the WebGL scene light. `null` ⇒ older
	// build with no lod_level → render every point (no cap). The cap is
	// the highest representative tier (rest tier hidden by default).
	let neuroscapeLodCap: number | null = null;
	// T046 + T047 — selection state for the slide-in detail panel
	// and the lasso grouped result list. Both are atlas-root-only.
	let atlasSelection:
		| {
				kind: 'ohbm2026';
				title: string;
				poster_id: number;
				nearest_cluster_id: number;
				permalink: string;
		  }
		| {
				kind: 'neuroscape';
				title: string;
				pubmed_id: number;
				year: number;
				cluster_id: number;
				permalink: string;
		  }
		| null = null;
	// Lasso state now lives in `atlasLassoOhbmSet` / `atlasLassoNeuroSet`
	// declared further down — Sets are the right shape since the
	// browse panel needs O(1) lookup, and the scatter highlight needs
	// a "selected indices" mask too.

	// O(1) lookup maps built whenever the atlas data lands.
	$: atlasOverlayById = new Map(atlasOverlayPoints.map((p) => [p.poster_id, p]));
	// `atlasBackdropById` keys the SCATTER points (decimated on atlas-root,
	// full on /neuroscape/) — used for point-click → detail panel + focus.
	$: atlasBackdropById = new Map(atlasBackdrop.map((p) => [p.pubmed_id, p]));
	// `listCorpusById` keys the LIST/search corpus (full ~461k on both
	// surfaces). The KNN-fallback seed scorer reads year + neighbour graph
	// from here; on /neuroscape/ this is the same array as atlasBackdrop (so
	// the neighbour graph is present), on atlas-root it's the identity-only
	// articles table (no graph → KNN fallback yields nothing, ranker drives
	// semantic search).
	$: listCorpusById = new Map(listCorpus.map((p) => [p.pubmed_id, p]));
	$: atlasClustersById = new Map(
		atlasClusters.map((c) => [c.cluster_id, { cluster_id: c.cluster_id, title: c.title, colour_hex: c.colour_hex }])
	);

	// Spec 019 perf — inverted title index over the FULL backdrop, built
	// ONCE when the corpus lands. `atlasBackdrop` is stable after load (facet
	// edits narrow `filteredBackdrop` but never mutate the full array), so the
	// ~461k-title tokenization runs a single time and is cached by array
	// identity inside `buildTitleIndex`. Both browse panels and the KNN seed
	// scorer query this via `searchTitleIndex`, which walks the unique-token
	// vocabulary (length-prefiltered) instead of running Damerau-Levenshtein
	// across every title's tokens per keystroke — the brute-force scan was a
	// ~2s main-thread freeze per query (measured at 461,316 articles) and the
	// root cause of the laggy-typing report. Shares the exact OHBM operator +
	// typo-tolerance semantics (consistent across all three sites).
	$: titleSearchIndex = buildTitleIndex(
		listCorpus,
		(a) => a.pubmed_id,
		(a) => a.title
	);

	// Filtered point lists threaded into AtlasUmapPanel so the
	// scatter visibly reflects browse-panel facet state. Empty cluster
	// set means "all clusters". For neuroscape mode, filterShowOhbm
	// is irrelevant (overlay is always empty) and filterShowNeuro is
	// always true (we never want to hide ALL backdrop points there).
	// Facet-only filters — these are what the SCATTER sees. The lasso
	// HIGHLIGHTS within these (via the dim-unselected mechanism in
	// UmapPanel) but does NOT remove points from the map.
	$: scatterBackdrop = (() => {
		if (SITE_MODE === 'atlas-root' && !filterShowNeuro) return [];
		const yLo = filterMinYear ?? yearBounds.lo;
		const yHi = filterMaxYear ?? yearBounds.hi;
		const needsYear = SITE_MODE === 'neuroscape';
		const needsCluster = filterClusterIds.size > 0;
		if (!needsYear && !needsCluster) return atlasBackdrop;
		return atlasBackdrop.filter((p) => {
			if (needsYear && (p.year < yLo || p.year > yHi)) return false;
			if (needsCluster && !filterClusterIds.has(p.cluster_id)) return false;
			return true;
		});
	})();
	// Spec 019 follow-up — facet-filtered FULL corpus for the RESULT LIST.
	// Mirrors scatterBackdrop's facet logic but over `listCorpus` (461k) so
	// the list count reflects the whole corpus, not the 50k scatter sample.
	// Filter deps are inlined (not factored into a helper) because Svelte's
	// reactive dependency tracking only sees variables referenced directly in
	// the `$:` block — a helper call would hide `filterShowNeuro`/year/cluster
	// from the dependency graph and the list would stop reacting to facets.
	$: listFacetFiltered = (() => {
		if (SITE_MODE === 'atlas-root' && !filterShowNeuro) return [];
		const yLo = filterMinYear ?? yearBounds.lo;
		const yHi = filterMaxYear ?? yearBounds.hi;
		const needsYear = SITE_MODE === 'neuroscape';
		const needsCluster = filterClusterIds.size > 0;
		if (!needsYear && !needsCluster) return listCorpus;
		return listCorpus.filter((p) => {
			if (needsYear && (p.year < yLo || p.year > yHi)) return false;
			if (needsCluster && !filterClusterIds.has(p.cluster_id)) return false;
			return true;
		});
	})();
	$: scatterOverlay = (() => {
		if (SITE_MODE !== 'atlas-root' || !filterShowOhbm) return [] as AtlasOverlayPoint[];
		if (filterClusterIds.size === 0) return atlasOverlayPoints;
		return atlasOverlayPoints.filter((p) => filterClusterIds.has(p.nearest_cluster_id));
	})();
	// Spec 019 follow-up — the SCATTER-only render set. atlas-root already
	// renders the LOD sample it range-fetched (no per-point lod_level, no
	// cap). /neuroscape/ holds the full corpus, so cap the scatter to the
	// blue-noise representative tiers (lod_level <= cap) while the result
	// list keeps the full `filteredBackdrop`. Derived from `scatterBackdrop`
	// so facet filters still apply to the map.
	$: scatterBackdropForMap = (() => {
		if (SITE_MODE !== 'neuroscape' || neuroscapeLodCap === null) return scatterBackdrop;
		const cap = neuroscapeLodCap;
		return scatterBackdrop.filter((p) => {
			const lv = (p as { lod_level?: number }).lod_level;
			return lv === undefined || lv <= cap;
		});
	})();
	// Result-list filters — the same facets plus the lasso. Browse
	// panel narrows to lassoed ids when the lasso is active.
	//
	// The "active lasso" decision is GLOBAL across both kinds — if
	// the user lassoes a region containing ONLY NeuroScape points
	// (zero OHBM overlay points fell inside), the OHBM result-list
	// must collapse to empty rather than fall through to "show all
	// OHBM" (the prior bug). The reverse holds for an OHBM-only
	// lasso region: NeuroScape rows collapse to empty.
	$: anyLassoActive = atlasLassoOhbmSet.size + atlasLassoNeuroSet.size > 0;
	$: filteredBackdrop = (() => {
		// No lasso → the RESULT LIST shows the full facet-filtered corpus.
		// With a lasso active, narrow the FULL corpus to the lassoed ids.
		// Spec 019 follow-up — `atlasLassoNeuroSet` now holds EVERY abstract
		// whose coordinate fell inside the polygon (point-in-polygon over the
		// full coords), not just the rendered LOD sample, so the result list
		// reflects the whole region — not the downsampled subset on screen.
		if (!anyLassoActive) return listFacetFiltered;
		return listFacetFiltered.filter((p) => atlasLassoNeuroSet.has(p.pubmed_id));
	})();
	// Spec 019 / FR-002 — KNN-expansion semantic search on /neuroscape/
	// + atlas-root. When `$semanticEnabled` is on AND the debounced
	// query is non-empty, take the top-N articles whose titles loosely
	// match the query as semantic SEEDS, walk the k=20 nearest-neighbour
	// graph already attached to each article, aggregate the
	// (pubmed_id, min-distance) pairs that don't already appear in the
	// lexical hit set, and pass them to the NeuroscapeBrowsePanel as
	// the `semanticHits` prop.
	//
	// Note: this is the KNN-only branch of the broader cluster-routed
	// pipeline (research.md §R-007). Without the production
	// neuroscape_vectors.parquet (a separate spec-019 build artefact
	// still pending deploy), we can't run the full embed→route→
	// cosine-rerank steps. The KNN graph alone gives a useful
	// "semantically related to your lexical hits" signal; the full
	// ranker drops in via the existing $lib/search/neuroscape_ranker
	// scaffolding when the production parquet ships.
	const SEMANTIC_SEED_LIMIT = 25;
	// Display cap on semantic-only rows. Raised from 60 → 250: a single
	// routed cluster (or the KNN-expansion fan-out) routinely holds far more
	// than 60 genuinely-related articles, and capping at 60 made semantic
	// search "show very few matches" (the reported regression). The cosine-
	// distance threshold below is the real relevance gate; this cap is just a
	// sanity bound on list length / render cost.
	const SEMANTIC_TOP_N = 250;
	// Relevance gate (cosine DISTANCE = 1 − cosine; lower = more similar).
	// Semantic-only rows with a distance above this are dropped, so the user
	// gets "a lot more matches subject to a distance threshold" (their exact
	// ask) rather than the whole routed cluster padded with unrelated titles.
	// 0.80 (cosine ≥ 0.20) is deliberately lenient for MiniLM title
	// embeddings — tightened later if visual review shows weak matches
	// leaking in. Applied to BOTH the cluster-routed ranker result and the
	// KNN-graph fallback so the bound is consistent across both paths.
	const SEMANTIC_MAX_DISTANCE = 0.8;
	// KNN-only fallback. Used whenever the full cluster-routed ranker
	// isn't initialised (`rankerReady === false`) — e.g. the vectors
	// sidecar URL isn't configured for this deploy. Selection between
	// this and the ranker result happens in `neuroscapeSemanticHits`.
	$: neuroscapeKnnHits = (() => {
		if (!$semanticEnabled) return new Map<number, number>();
		const raw = ($debouncedSearchQuery ?? '').trim();
		if (raw.length < 3) return new Map<number, number>();
		if (SITE_MODE !== 'neuroscape' && SITE_MODE !== 'atlas-root') {
			return new Map<number, number>();
		}
		// Lightweight seed selection — token-aware so multi-word natural-
		// language queries (e.g. "corpus callosum disorders") still seed.
		// A whole-phrase substring match would require some title to
		// literally contain the full phrase, which almost never happens for
		// 3+ word queries → 0 seeds → empty result. Instead: tokenise the
		// query, score each title by how many distinct query tokens it
		// contains, keep titles matching ≥1 token, and rank by match-count
		// (desc) then year (desc). This loose seed is plenty to drive KNN
		// expansion; the BrowsePanel's full operator + typo path handles
		// exact ranking downstream.
		//
		// seedScores() does a UNION over the query's positive words (≥1 token
		// qualifies), NOT searchTitleIndex()'s AND-intersection: a bare
		// multi-word query otherwise requires one title to contain ALL words,
		// which a titles-only corpus almost never does → 0 seeds → empty
		// fallback (the bug this fixes). It reuses the shared per-word typo
		// ladder (lookupWord) so quote/typo handling stays consistent across
		// sites, and excludes negated clauses so a `-term` can't leak a
		// positive seed. The returned count of distinct matched words drives
		// the match-count ranking below. Intersecting with filteredBackdrop
		// keeps it facet-aware; the BrowsePanel applies full AND/phrase ranking.
		const seedCounts = seedScores(titleSearchIndex, parseQuery(raw));
		if (seedCounts.size === 0) return new Map<number, number>();
		const facetSet = new Set(filteredBackdrop.map((a) => a.pubmed_id));
		const scored: { id: number; exact: number; year: number }[] = [];
		for (const [id, cnt] of seedCounts) {
			if (!facetSet.has(id)) continue;
			const a = listCorpusById.get(id);
			if (!a) continue;
			scored.push({ id, exact: cnt, year: a.year });
		}
		if (scored.length === 0) return new Map<number, number>();
		scored.sort((x, y) => y.exact - x.exact || y.year - x.year);
		const seedIds = scored.slice(0, SEMANTIC_SEED_LIMIT).map((s) => s.id);
		// Walk the KNN graph from each seed. The graph is attached to
		// each article as `nearest_pubmed_ids` + `nearest_distances`
		// (loader.ts:545 join). For each neighbour, record the minimum
		// distance across all seeds.
		const seedSet = new Set(seedIds);
		const semanticOnly = new Map<number, number>();
		const articleById = listCorpusById;
		for (const seed of seedIds) {
			const a = articleById.get(seed);
			if (!a?.nearest_pubmed_ids || !a?.nearest_distances) continue;
			for (let i = 0; i < a.nearest_pubmed_ids.length; i++) {
				const nb = a.nearest_pubmed_ids[i];
				if (seedSet.has(nb)) continue;
				const d = a.nearest_distances[i];
				const prev = semanticOnly.get(nb);
				if (prev === undefined || d < prev) semanticOnly.set(nb, d);
			}
		}
		// Apply the relevance gate, then trim to top-N by ascending distance.
		const sorted = Array.from(semanticOnly.entries())
			.filter(([, d]) => d <= SEMANTIC_MAX_DISTANCE)
			.sort((x, y) => x[1] - y[1]);
		return new Map(sorted.slice(0, SEMANTIC_TOP_N));
	})();
	// Spec 019 / FR-002 — full cluster-routed ranker invocation. When the
	// ranker is initialised, run the embed→route→range-fetch→top-3→KNN-
	// expand→re-rank pipeline (async, off the main thread via the
	// semantic worker) and stash the result in `neuroscapeRankerHits`.
	// Serial-number guard discards stale responses when the user types
	// faster than the worker resolves. Falls through to the KNN-only
	// fallback by leaving `neuroscapeRankerHits` empty on any short query
	// or non-ranker mode.
	$: (async (_q: string, _on: boolean, _ready: boolean, _depth: number) => {
		if (!_ready || !_on) {
			neuroscapeRankerHits = new Map();
			rankerCapExceeded = false;
			return;
		}
		if (SITE_MODE !== 'neuroscape' && SITE_MODE !== 'atlas-root') return;
		const trimmed = (_q ?? '').trim();
		if (trimmed.length < 3) {
			neuroscapeRankerHits = new Map();
			return;
		}
		const my = ++neuroscapeRankerSerial;
		try {
			const parsed = parseQuery(trimmed);
			const hits = await searchNeuroscape(parsed, SEMANTIC_TOP_N, {
				onState: (s) => {
					if (my === neuroscapeRankerSerial) rankerState = s;
				},
				onCapExceeded: () => {
					if (my === neuroscapeRankerSerial) rankerCapExceeded = true;
				},
				onError: (e) => console.warn('neuroscape ranker error:', e)
			});
			if (my !== neuroscapeRankerSerial) return;
			const m = new Map<number, number>();
			// Store DISTANCE (1 − cosine), not cosine similarity, so this map
			// is the SAME metric as the KNN-fallback map (`nearest_distances`):
			// both are "lower = better". The browse panels sort ascending on
			// the value and surface it as `d=` on the ✨ badge. Storing cosine
			// here would invert the sort order and mislabel the badge whenever
			// the ranker path is active.
			// Apply the same cosine-distance relevance gate as the KNN
			// fallback so a routed cluster padded with weakly-related members
			// doesn't flood the list — the user wanted "a lot more matches
			// subject to a distance threshold", not the whole cluster.
			for (const h of hits) {
				const d = 1 - h.cosine;
				if (d <= SEMANTIC_MAX_DISTANCE) m.set(Number(h.id), d);
			}
			neuroscapeRankerHits = m;
			rankerErrored = false;
		} catch (err) {
			if (my === neuroscapeRankerSerial) {
				console.warn('neuroscape ranker query failed:', err);
				neuroscapeRankerHits = new Map();
				rankerErrored = true;
			}
		}
	})($debouncedSearchQuery, $semanticEnabled, rankerReady, rankerDepthBump);
	// Selection: prefer the full ranker when it's initialised AND its last
	// query succeeded; otherwise the KNN-only fallback. A ranker that's
	// "ready" but errors on every query (range-fetch/parquet failure) must
	// not silently zero out semantic search — it degrades to KNN instead.
	// Both are pubmed_id → DISTANCE maps (lower = better) consumed
	// identically by NeuroscapeBrowsePanel / AtlasRootBrowsePanel: the
	// ranker path stores 1 − cosine (above) so it matches the KNN
	// fallback's `nearest_distances` metric. The panels sort ascending
	// and render the value as `d=` on the ✨ badge.
	// A ranker that is "ready" but returns an EMPTY set for a query the
	// KNN graph can answer (per-query cluster-budget cap, empty routed
	// cluster) must also degrade to KNN rather than show 0 semantic rows.
	$: neuroscapeSemanticHits =
		rankerReady && !rankerErrored && neuroscapeRankerHits.size > 0
			? neuroscapeRankerHits
			: neuroscapeKnnHits;
	// True while the ranker pipeline is mid-flight (any non-terminal
	// state) — drives the "searching…" toggle hint.
	$: rankerBusy =
		rankerState !== null && rankerState !== 'ready' && rankerState !== 'idle' && rankerState !== 'error';
	$: filteredOverlay = (() => {
		if (!anyLassoActive) return scatterOverlay;
		return scatterOverlay.filter((p) => atlasLassoOhbmSet.has(p.poster_id));
	})();

	// Cross-subsite permalink construction.
	//
	// gh-pages serves a single ROOT /404.html for every unresolved
	// path host-wide. Until the cross-conference root 404.html shim
	// is on production, a direct navigation to
	// `/pr-37/neuroscape/abstract/<n>/` 404s into the legacy redirect
	// and bounces to /ohbm2026/ — the lasso-click bug.
	//
	// Workaround: route through the existing `?spa=<deep-link>`
	// mechanism. The SvelteKit shell at `/pr-37/neuroscape/index.html`
	// (which DOES exist, served HTTP 200) handles `?spa=` in its
	// `+layout.svelte` onMount — it `goto`s the deep link with
	// `replaceState: true` so the final URL bar shows the clean
	// `/pr-37/neuroscape/abstract/<n>/` form. No root-404 update
	// needed; no production risk.
	//
	// Two URL forms:
	//   - `cleanPermalink(kind, id)` — the canonical deep link
	//     `/pr-37/<mode>/abstract/<n>/`. Use for status display,
	//     copy-link buttons, anything the visitor would expect to
	//     paste into a browser. (These DO 404 until the root shim
	//     update lands.)
	//   - `atlasPermalink(kind, id)` — the SPA-shell+`?spa=` form
	//     above. Used for href attributes on in-page anchors so the
	//     navigation actually works.
	// Strip the per-mode suffix off `base` so the permalink helpers
	// can compose URLs against the deploy ROOT regardless of which
	// build is currently running. Without this, on `/neuroscape/`
	// `base` already ends in `/neuroscape`, and the naive
	// `${base}/neuroscape/abstract/<id>/` form produced
	// `/neuroscape/neuroscape/abstract/<id>/` — the `?spa=` shim then
	// looped trying to resolve the non-existent path.
	function permalinkRoot(): string {
		if (SITE_MODE === 'ohbm2026' && base.endsWith('/ohbm2026')) {
			return base.slice(0, -'/ohbm2026'.length);
		}
		if (SITE_MODE === 'neuroscape' && base.endsWith('/neuroscape')) {
			return base.slice(0, -'/neuroscape'.length);
		}
		return base;
	}
	function cleanPermalink(kind: 'ohbm2026' | 'neuroscape', id: number): string {
		const root = permalinkRoot();
		return kind === 'ohbm2026'
			? `${root}/ohbm2026/abstract/${id}/`
			: `${root}/neuroscape/abstract/${id}/`;
	}
	function atlasPermalink(kind: 'ohbm2026' | 'neuroscape', id: number): string {
		// Same-mode permalink (e.g. /neuroscape/ → NeuroScape detail
		// page): use the clean in-app URL directly. SvelteKit handles
		// the navigation within the same bundle; no `?spa=` shim
		// dance needed.
		if (SITE_MODE === kind) {
			return cleanPermalink(kind, id);
		}
		// Cross-mode (atlas-root → either subsite, or sibling → sibling
		// in some future routing): wrap in the `?spa=` payload so the
		// gh-pages root 404 shim bounces into the right sibling shell.
		const root = permalinkRoot();
		const target = cleanPermalink(kind, id);
		const shellPath = kind === 'ohbm2026' ? `${root}/ohbm2026/` : `${root}/neuroscape/`;
		return `${shellPath}?spa=${encodeURIComponent(target)}`;
	}

	function onAtlasPointClick(
		ev: CustomEvent<{ kind: 'ohbm2026' | 'neuroscape'; id: number }>
	) {
		const { kind, id } = ev.detail;
		if (kind === 'ohbm2026') {
			const p = atlasOverlayById.get(id);
			if (!p) return;
			atlasSelection = {
				kind: 'ohbm2026',
				title: p.title,
				poster_id: p.poster_id,
				nearest_cluster_id: p.nearest_cluster_id,
				permalink: atlasPermalink('ohbm2026', p.poster_id)
			};
		} else {
			const p = atlasBackdropById.get(id);
			if (!p) return;
			atlasSelection = {
				kind: 'neuroscape',
				title: p.title,
				pubmed_id: p.pubmed_id,
				year: p.year,
				cluster_id: p.cluster_id,
				permalink: atlasPermalink('neuroscape', p.pubmed_id)
			};
		}
	}

	// Most-similar list for the inline detail panel. On /neuroscape/
	// the backdrop articles carry `nearest_pubmed_ids` (10 ids per
	// article), baked into neuroscape.parquet by the orchestrator and
	// joined onto each article record in loader.ts. atlas-root's
	// backdrop comes from atlas.parquet which has no neighbours table,
	// so we surface an empty list there — the CTA "Open on /<sibling>/"
	// is the user's path to the full detail page in that case.
	$: detailNeighbours = (() => {
		if (!atlasSelection || atlasSelection.kind !== 'neuroscape') return [];
		const src = atlasBackdropById.get(atlasSelection.pubmed_id);
		if (!src?.nearest_pubmed_ids) return [];
		const out: Array<{ id: number; title: string; href: string }> = [];
		for (const nid of src.nearest_pubmed_ids.slice(0, 10)) {
			const hit = atlasBackdropById.get(nid);
			if (!hit) continue;
			out.push({
				id: nid,
				title: hit.title,
				href: atlasPermalink('neuroscape', nid)
			});
		}
		return out;
	})();

	// Lazily-fetched FULL NeuroScape coords for atlas-root lasso. The
	// landing scatter renders only the LOD sample, so a lasso must test
	// its polygon against the whole 461k coordinate set to find every
	// abstract in the region. /neuroscape/ already holds the full coords
	// in `atlasBackdrop`; atlas-root fetches the `coords` table (~11 MB)
	// on the FIRST lasso only. `null` until fetched; a fetch in flight is
	// tracked so concurrent lassos don't double-fetch.
	let atlasFullCoords: CoordPoint[] | null = null;
	let atlasFullCoordsPromise: Promise<CoordPoint[] | null> | null = null;

	async function ensureAtlasFullCoords(): Promise<CoordPoint[] | null> {
		if (atlasFullCoords) return atlasFullCoords;
		if (!atlasFullCoordsPromise) {
			atlasFullCoordsPromise = loadCoordsFromNeuroscape()
				.then((rows) => {
					if (!rows || rows.length === 0) {
						console.warn(
							'atlas-root: full `coords` unavailable from the NeuroScape sibling — lasso limited to the displayed LOD sample.'
						);
						return null;
					}
					atlasFullCoords = rows as unknown as CoordPoint[];
					return atlasFullCoords;
				})
				.catch((err) => {
					console.warn('atlas-root: full `coords` range-fetch failed; lasso limited to the LOD sample:', err);
					atlasFullCoordsPromise = null; // allow a retry on the next lasso
					return null;
				});
		}
		return atlasFullCoordsPromise;
	}

	// Resolve a lasso polygon/box to the selected ids by point-in-polygon
	// over the FULL corpus (not the rendered LOD sample) — spec 019 follow-up.
	// OHBM overlay is fully rendered so its own coords suffice; the NeuroScape
	// backdrop is downsampled, so we test against the full coords: in memory
	// on /neuroscape/ (`atlasBackdrop`), lazily range-fetched on atlas-root.
	async function onAtlasLasso(ev: CustomEvent<{ geometry: LassoGeometry }>) {
		const g = ev.detail.geometry;
		const getXY = (p: { umap_2d?: [number, number] }) => p.umap_2d;
		atlasLassoOhbmSet = new Set(
			selectIdsInGeometry(atlasOverlayPoints, g, (p) => p.poster_id, getXY)
		);
		let neuroSource: CoordPoint[];
		if (SITE_MODE === 'neuroscape') {
			neuroSource = atlasBackdrop;
		} else {
			// atlas-root: prefer the full coords; fall back to the rendered
			// LOD sample while they load (or if unavailable), then re-resolve
			// once they land so the selection upgrades to the full region.
			const full = await ensureAtlasFullCoords();
			neuroSource = full ?? atlasBackdrop;
		}
		atlasLassoNeuroSet = new Set(
			selectIdsInGeometry(neuroSource, g, (p) => p.pubmed_id, getXY)
		);
	}

	function clearAtlasLasso() {
		atlasLassoOhbmSet = new Set();
		atlasLassoNeuroSet = new Set();
	}
	// T043 — drift banner state. Populated by the sibling-state-key
	// check that fires in the background after atlas.parquet loads.
	let atlasDrift: AtlasDriftEntry[] = [];
	// UX unification — facet state lives at the page level so the
	// AtlasRootFacets / NeuroscapeFacets sidebars can be the single
	// source of truth. Browse panels + scatter both read the
	// filtered arrays computed from this state.
	let filterClusterIds: Set<number> = new Set();
	let filterShowOhbm = true;
	let filterShowNeuro = true;
	let filterMinYear: number | null = null;
	let filterMaxYear: number | null = null;

	// Year bounds for the NeuroScape year facet — derived from the
	// loaded backdrop. Default 0/0 until articles arrive.
	$: yearBounds = (() => {
		if (SITE_MODE !== 'neuroscape' || atlasBackdrop.length === 0) {
			return { lo: 0, hi: 0 };
		}
		let lo = Infinity;
		let hi = -Infinity;
		for (const p of atlasBackdrop) {
			if (p.year < lo) lo = p.year;
			if (p.year > hi) hi = p.year;
		}
		return { lo: Number.isFinite(lo) ? lo : 0, hi: Number.isFinite(hi) ? hi : 0 };
	})();

	// Cluster counts — shared by both facet sidebars. For atlas-root,
	// counts include BOTH backdrop and overlay; for neuroscape, only
	// backdrop. SITE_MODE-conditional so we don't pay the iteration
	// cost on the wrong mode.
	// Facet counts mirror OHBM 2026's pattern: each facet shows the
	// counts that WOULD result if you added one of its options,
	// computed from the intersection of (lasso ∩ every OTHER active
	// facet). The facet's own selection is excluded from its own
	// counts so unchecking an option doesn't make its count vanish.
	// Base sources after lasso (the lasso is global — affects every
	// facet).
	$: lassoBackdropPoints = (() => {
		// Facet counts over the FULL corpus (`listCorpus`), not the LOD
		// scatter sample — so cluster/year counts match the full-region
		// result list. `listCorpus` carries cluster_id + year and is the
		// whole corpus on both surfaces (identity table on atlas-root,
		// the same full array as atlasBackdrop on /neuroscape/).
		if (!anyLassoActive) return listCorpus;
		return listCorpus.filter((p) => atlasLassoNeuroSet.has(p.pubmed_id));
	})();
	$: lassoOverlayPoints = (() => {
		if (!anyLassoActive) return atlasOverlayPoints;
		return atlasOverlayPoints.filter((p) => atlasLassoOhbmSet.has(p.poster_id));
	})();
	// Sites counts (atlas-root) — apply cluster filter, exclude self.
	$: siteCounts = (() => {
		if (SITE_MODE !== 'atlas-root') return { ohbm: 0, neuro: 0 };
		const useC = filterClusterIds.size > 0;
		const ohbm = useC
			? lassoOverlayPoints.filter((p) => filterClusterIds.has(p.nearest_cluster_id)).length
			: lassoOverlayPoints.length;
		const neuro = useC
			? lassoBackdropPoints.filter((p) => filterClusterIds.has(p.cluster_id)).length
			: lassoBackdropPoints.length;
		return { ohbm, neuro };
	})();
	// Cluster counts — apply every OTHER active facet (Sites on atlas-
	// root; Years on neuroscape), exclude self.
	$: clusterCounts = (() => {
		const counts = new Map<number, number>();
		if (SITE_MODE === 'atlas-root') {
			if (filterShowNeuro) {
				for (const a of lassoBackdropPoints)
					counts.set(a.cluster_id, (counts.get(a.cluster_id) ?? 0) + 1);
			}
			if (filterShowOhbm) {
				for (const o of lassoOverlayPoints)
					counts.set(o.nearest_cluster_id, (counts.get(o.nearest_cluster_id) ?? 0) + 1);
			}
		} else if (SITE_MODE === 'neuroscape') {
			const yLo = filterMinYear ?? yearBounds.lo;
			const yHi = filterMaxYear ?? yearBounds.hi;
			for (const a of lassoBackdropPoints) {
				if (a.year < yLo || a.year > yHi) continue;
				counts.set(a.cluster_id, (counts.get(a.cluster_id) ?? 0) + 1);
			}
		}
		return counts;
	})();
	// UX-unification: search query + show-map state at the page level,
	// matching the OHBM 2026 home's pattern (search lives in the
	// top-row, map toggles in/out via a control-toggle button). Both
	// atlas-root and neuroscape modes share these.
	//
	// `atlasShowMap` defaults to false on mobile-width viewports.
	// On phones this may drain battery and could incur cellular
	// download charges (the parquet is ~25–96 MB and the 461k-point
	// scatter3d hammers SwiftShader CPU rendering). Visitors flip
	// it on with the same toggle after reading the admonition near
	// the top of the page.
	// Spec 019 / T028 — the atlas-root + /neuroscape/ search surface
	// now reuses the shared `$searchQuery` store via <SearchBar>
	// (FR-025). The previously-local `atlasSearchQuery` declaration is
	// removed; downstream readers use `$searchQuery` directly. The
	// store is auto-cleared by SearchBar's own clear-button affordance.
	let atlasShowMap =
		typeof window === 'undefined' ? true : window.innerWidth >= 1024;
	// Mobile-only "🔍 Filters" toggle, mirroring OHBM's pattern: the
	// facets sidebar is hidden by default on narrow viewports and
	// opens above the result list when the user taps the button.
	// On desktop (≥1024 px) OHBM's `.facet-pane { display: block
	// !important }` rule keeps it always visible.
	let showAtlasFacets = false;

	// Mobile-viewport reactive — tracked via a resize listener so the
	// admonition + map default re-flow if the user rotates / resizes.
	// `mobileViewport` mirrors UmapPanel's 1024px breakpoint so the
	// page-level chrome and the chart-level layout switch in lockstep.
	let mobileViewport =
		typeof window === 'undefined' ? false : window.innerWidth < 1024;
	function onWindowResize() {
		mobileViewport = window.innerWidth < 1024;
	}
	// Lasso selection. When non-null, the result list filters to these
	// ids and the 2D scatter dims unselected points + zooms the 3D
	// camera to the lassoed bounding box.
	let atlasLassoOhbmSet: Set<number> = new Set();
	let atlasLassoNeuroSet: Set<number> = new Set();
	// Lasso "active" reactive — currently unused after the clear-
	// selection button moved into UmapPanel's header, but kept as a
	// stable selector if any future top-row chrome needs it.
	$: atlasLassoActive = atlasLassoOhbmSet.size + atlasLassoNeuroSet.size > 0;
	void atlasLassoActive;
	let atlasLoading = false;
	let atlasError: string | null = null;
	let atlasProgressLoaded = 0;
	let atlasProgressTotal: number | null = null;
	// Phase string drives the placeholder label so the parsing window
	// (CPU-bound, no byte progress) doesn't look frozen on fast links.
	let atlasPhase: 'connecting' | 'downloading' | 'parsing' | 'ready' = 'connecting';

	/**
	 * Spec 019 / FR-002 — initialise the full cluster-routed semantic
	 * ranker once the NeuroScape articles + clusters are in memory.
	 *
	 * Runs in the background (never blocks first paint) and is a no-op
	 * unless ALL of these are present:
	 *   - `VITE_DATA_PACKAGE_URL_NEUROSCAPE_VECTORS` (the INT8 sidecar),
	 *   - a `cluster_centroids` table in the loaded parquet,
	 *   - articles carrying `cluster_id` + the k=20 neighbour graph.
	 * Any missing piece leaves `rankerReady=false` and the page falls
	 * back to the KNN-only `neuroscapeKnnHits` path — no thrown error,
	 * no broken search.
	 *
	 * The maps (pubmed→cluster, pubmed→KNN) are built from the already-
	 * loaded `atlasBackdrop` rows rather than re-reading the parquet.
	 */
	async function initNeuroscapeRanker() {
		if (SITE_MODE !== 'neuroscape' && SITE_MODE !== 'atlas-root') return;
		if (rankerReady) return;
		const vectorsUrl = getNeuroscapeVectorsUrl();
		if (!vectorsUrl) return; // KNN-only fallback
		try {
			const [manifest, localCentroids] = await Promise.all([
				loadVectorsManifest(vectorsUrl),
				loadClusterCentroids()
			]);
			// atlas-root's own atlas.parquet carries no centroid table; pull
			// the cluster_centroids row group that already exists in the
			// sibling neuroscape.parquet (one Range request, ~268 KB — the
			// envelope is row_group_size=1). One source of truth, no
			// duplication, no data rebuild.
			let centroids = localCentroids;
			if (!centroids || centroids.length === 0) {
				centroids = await loadClusterCentroidsFromNeuroscape();
			}
			if (!manifest || !centroids || centroids.length === 0) {
				// CA-006 — never degrade to lexical-only silently. The vectors
				// sidecar is configured (vectorsUrl present) but no centroids
				// were found locally or in the neuroscape sibling, so the
				// cluster-routed ranker can't run.
				console.warn(
					`neuroscape ranker: vectors sidecar present but cluster centroids ` +
						`unavailable (manifest=${!!manifest}, centroids=${centroids?.length ?? 0}) — ` +
						`semantic search will fall back to KNN-only. Check that ` +
						`VITE_DATA_PACKAGE_URL_NEUROSCAPE points at a neuroscape.parquet ` +
						`carrying the cluster_centroids table.`
				);
				return;
			}
			// Build the pubmed→cluster + pubmed→KNN maps from the in-memory
			// articles. atlas-root's backdrop rows don't carry neighbours,
			// so its knnIndex stays empty — the ranker still routes +
			// brute-forces + re-ranks; only the KNN-expansion step yields
			// nothing extra there (acceptable: atlas-root search is a
			// cross-conference convenience, not the primary surface).
			const pubmedToCluster = new Map<bigint, number>();
			const knnIndex = new Map<bigint, KnnEntry>();
			for (const a of atlasBackdrop) {
				const pid = BigInt(a.pubmed_id);
				pubmedToCluster.set(pid, a.cluster_id);
				if (a.nearest_pubmed_ids && a.nearest_distances) {
					knnIndex.set(pid, {
						pubmed_id: pid,
						nearest_pubmed_ids: a.nearest_pubmed_ids.map((n) => BigInt(n)),
						nearest_distances: a.nearest_distances
					});
				}
			}
			const worker = await defaultSemanticWorker({
				dim: manifest.dim,
				scale: manifest.scale
			});
			initRanker({
				worker,
				fetchClusterVectors: (clusterId: number) => loadClusterVectors(vectorsUrl, clusterId),
				centroids: centroids.map((c) => ({
					cluster_id: c.cluster_id,
					centroid_vector: c.centroid_vector
				})),
				pubmedToCluster,
				knnIndex
			});
			rankerReady = true;
		} catch (err) {
			// Loud-but-non-fatal: the page keeps the KNN fallback. Log so
			// the failure is visible in the console rather than silently
			// degrading semantic quality.
			console.warn('neuroscape ranker init failed; using KNN fallback:', err);
			rankerReady = false;
		}
	}

	// Rebuild the cross-site NeuroScape title lookup from the current
	// `listCorpus` + `atlasClusters`. Sourced from `listCorpus` (the
	// LIST/search corpus) rather than the SCATTER (`atlasBackdrop`) so it
	// covers the full corpus once the background `articles` fetch lands —
	// on atlas-root the scatter is only the LOD sample, so sourcing it
	// there would shrink the cart's title coverage. Called after first
	// paint and again when the full corpus swaps in.
	function refreshNeuroscapeTitleLookup() {
		const clusterTitleById = new Map<number, string>();
		for (const c of atlasClusters) clusterTitleById.set(c.cluster_id, c.title);
		const neuroMap = new Map<
			number,
			{ title: string; year?: number; cluster_title?: string }
		>();
		for (const p of listCorpus) {
			neuroMap.set(p.pubmed_id, {
				title: p.title,
				year: p.year,
				cluster_title: clusterTitleById.get(p.cluster_id)
			});
		}
		neuroscapeTitleLookup.set(neuroMap);
	}

	async function loadAtlasData() {
		if (SITE_MODE === 'ohbm2026') return;
		if (atlasLoading || atlasBackdrop.length > 0) return;
		atlasLoading = true;
		atlasProgressLoaded = 0;
		atlasProgressTotal = null;
		atlasPhase = 'connecting';
		try {
			const pkg = await loadDataPackage(
				fetch,
				(loaded, total) => {
					atlasProgressLoaded = loaded;
					atlasProgressTotal = total;
				},
				(phase) => {
					atlasPhase = phase;
				}
			);
			if (!pkg) {
				// `pkg === null` has two distinct causes: the data-package
				// URL genuinely isn't configured (build-time env missing),
				// or the fetch failed (network / a 429 from the data host
				// rate-limiting rapid requests). Distinguish them so the
				// visitor sees an actionable message instead of a wrong
				// "not configured" one.
				const label = SITE_MODE === 'atlas-root' ? 'Atlas' : 'NeuroScape';
				atlasError = getDataPackageUrl()
					? `Couldn't load the ${label} data package — the data host may be temporarily rate-limiting requests. Refresh to retry.`
					: `${label} data package URL not configured.`;
				return;
			}
			if (SITE_MODE === 'atlas-root') {
				const overlayShard = pkg.get('data/atlas/ohbm_overlay.json') as
					| { points: AtlasOverlayPoint[] }
					| undefined;
				if (!overlayShard) {
					atlasError = 'Atlas data package is missing the ohbm_overlay row group.';
					return;
				}
				// Spec 019 — atlas.parquet now carries ONLY the OHBM→NeuroScape
				// overlay. The cluster legend + the landing backdrop are
				// range-fetched from the sibling neuroscape.parquet (single
				// source of truth, no 27 MB duplication in atlas.parquet).
				//
				// Spec 019 follow-up — the backdrop is range-fetched
				// progressively as quadtree LOD tiers: `backdrop_lod0` (a
				// coarse blue-noise cover) paints almost instantly, then the
				// finer tiers stream in and refine. The full corpus is never
				// fetched for the backdrop. Clusters + the coarse tier load
				// together so the first paint already has its legend colours.
				const [clustersRows, lod0Rows, levelCount] = await Promise.all([
					loadClustersFromNeuroscape(),
					loadBackdropLevelFromNeuroscape(0),
					readNeuroscapeBackdropLevelCount()
				]);
				if (!clustersRows || !lod0Rows) {
					atlasError =
						'Atlas backdrop/clusters could not be range-fetched from the NeuroScape sibling parquet.';
					return;
				}
				atlasBackdrop = lod0Rows as unknown as AtlasBackdropPoint[];
				// Seed the LIST/search corpus with the coarse tier so the result
				// list renders immediately on first paint; the FULL ~461k identity
				// table is range-fetched in the background below and swapped in
				// when ready (progressive enhancement — the no-query count ticks
				// up to the full corpus once the articles land). The SCATTER and
				// the LIST diverge on atlas-root: the scatter refines through the
				// LOD tiers (below), the list jumps to the full identity table.
				listCorpus = lod0Rows as unknown as AtlasBackdropPoint[];
				atlasOverlayPoints = overlayShard.points;
				atlasClusters = clustersRows as unknown as AtlasClusterRow[];
				// Refine: stream the remaining tiers (lod1..N-1) and append.
				// A missing/absent level resolves to null and is skipped — the
				// scatter still shows every tier that did load (no silent
				// zero-result; a fully-failed refine just keeps the coarse
				// cover already painted).
				const nLevels = levelCount ?? 1;
				if (nLevels > 1) {
					void (async () => {
						const finer = await Promise.all(
							Array.from({ length: nLevels - 1 }, (_, i) =>
								loadBackdropLevelFromNeuroscape(i + 1).catch(() => null)
							)
						);
						const extra = finer
							.filter((r): r is Array<Record<string, unknown>> => !!r && r.length > 0)
							.flat() as unknown as AtlasBackdropPoint[];
						if (extra.length > 0) {
							// Reassign (not push) so Svelte's reactivity repaints
							// the scatter + rebuilds the derived id maps. The title
							// lookup is driven by `listCorpus` (the full identity
							// table), not the scatter, so it isn't rebuilt here.
							atlasBackdrop = [...atlasBackdrop, ...extra];
						}
					})();
				}
				// Publish title lookups so the unifying cart drawer can
				// render rich rows for items from EITHER subsite when
				// the user is on atlas-root (the only build that loads
				// both kinds locally).
				const ohbmMap = new Map<number, { title: string; lead_author?: string }>();
				for (const p of atlasOverlayPoints) {
					ohbmMap.set(p.poster_id, { title: p.title });
				}
				ohbmTitleLookup.set(ohbmMap);
				refreshNeuroscapeTitleLookup();
				// T043 — Sibling-state-key drift check. Fires after the
				// atlas scatter renders, so a slow / unreachable sibling
				// doesn't block first paint. The check itself retries
				// each sibling fetch up to 4 times with 400/1200/3000 ms
				// backoff (loader.ts) before giving up.
				//
				// Two distinct loud signals — never silent:
				//   - `mismatch` → confirmed drift; cross-conference
				//     links will point at stale ids. Per R-012.
				//   - `fetch-failed` / `no-state-key` → couldn't verify
				//     after retries. The atlas MAY be fine, but we
				//     can't confirm. Surfaced with different copy so
				//     the visitor can act on the actual signal.
				const manifest = pkg.get('data/manifest.json');
				void verifyAtlasSiblingDrift(manifest).then((result) => {
					if (!result.ok) atlasDrift = result.drift;
				});
				// Background upgrade: range-fetch the FULL ~461k `articles`
				// identity table from the sibling so the result-list count +
				// lexical search cover the whole corpus (not just the 50k
				// scatter sample). Fire-and-forget so the scatter's first paint
				// isn't blocked on this ~20 MB fetch. On failure we keep the
				// decimated 50k list and log loudly (CA-006) — never silently
				// pretend the corpus is only 50k.
				void loadArticlesFromNeuroscape()
					.then((rows) => {
						if (!rows || rows.length === 0) {
							console.warn(
								'atlas-root: full `articles` table unavailable from the NeuroScape sibling — result list limited to the decimated 50k backdrop.'
							);
							return;
						}
						listCorpus = rows as unknown as AtlasBackdropPoint[];
						// Widen the cart's NeuroScape title lookup to the full
						// corpus now that we have every title (was seeded with the
						// coarse LOD tier above). Sources `listCorpus`, just set.
						refreshNeuroscapeTitleLookup();
					})
					.catch((err) => {
						console.warn(
							'atlas-root: full `articles` range-fetch failed; result list limited to the decimated 50k backdrop:',
							err
						);
					});
			} else if (SITE_MODE === 'neuroscape') {
				const articlesShard = pkg.get('data/neuroscape/articles.json') as
					| { articles: AtlasBackdropPoint[] }
					| undefined;
				const clustersShard = pkg.get('data/neuroscape/clusters.json') as
					| { clusters: AtlasClusterRow[] }
					| undefined;
				if (!articlesShard || !clustersShard) {
					atlasError =
						'NeuroScape data package is missing the articles or clusters row group.';
					return;
				}
				// neuroscape.parquet doesn't ship a pre-decimated row group;
				// keep the full 461k articles for search + result-list,
				// decimate at scatter-render time below. On /neuroscape/ the
				// scatter source (atlasBackdrop, carries coords from the
				// coords→articles join) and the list/search corpus (listCorpus)
				// are the SAME array — only atlas-root splits them.
				atlasBackdrop = articlesShard.articles;
				listCorpus = articlesShard.articles;
				atlasOverlayPoints = [];
				atlasClusters = clustersShard.clusters;
				// Cap the scatter to the representative tiers (hide the
				// rest tier) so the WebGL scene stays light; the full
				// corpus above still feeds search + the result list. An
				// older build with no n_backdrop_levels leaves the cap
				// null → every point renders (prior behaviour).
				const nsManifest = pkg.get('data/manifest.json') as
					| { n_backdrop_levels?: number }
					| undefined;
				neuroscapeLodCap =
					typeof nsManifest?.n_backdrop_levels === 'number' &&
					nsManifest.n_backdrop_levels > 0
						? nsManifest.n_backdrop_levels - 1
						: null;
				// /neuroscape/ publishes only the neuroscape title
				// lookup; cross-site OHBM rows in the cart render with
				// a placeholder until the user visits an OHBM page or
				// atlas-root warms the OHBM lookup.
				refreshNeuroscapeTitleLookup();
			}
			// Kick off the full cluster-routed ranker in the background
			// once the articles + clusters are in memory. Non-blocking;
			// no-op when the vectors sidecar URL is unset.
			void initNeuroscapeRanker();
		} catch (err) {
			atlasError = `failed to load atlas data: ${(err as Error)?.message ?? String(err)}`;
		} finally {
			atlasLoading = false;
		}
	}

	$: atlasProgressPercent =
		atlasProgressTotal && atlasProgressTotal > 0
			? Math.min(100, Math.round((atlasProgressLoaded / atlasProgressTotal) * 100))
			: null;

	function formatMb(bytes: number): string {
		return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
	}

	onMount(() => {
		void loadAtlasData();
		window.addEventListener('resize', onWindowResize);
		return () => window.removeEventListener('resize', onWindowResize);
	});

	// Auto-open the inline detail panel ONCE when the URL carries
	// `?focus=<id>&cluster=<id>`. The "Show on atlas" buttons on the
	// /neuroscape/abstract/<pmid>/ permalink page navigate to
	// `/neuroscape/?focus=<pmid>&cluster=<cid>`; without this hook the
	// visitor arrives at the home with no visible signal that they
	// asked to focus a specific point. Reactively watching
	// `atlasBackdrop` so the focus applies after the parquet finishes
	// loading (race: the URL is set before data is ready on cold
	// load).
	//
	// The `?focus=` params are CLEARED from the URL after applying,
	// otherwise closing the panel (atlasSelection → null) would
	// re-trigger this reactive and re-open the panel on the next
	// tick — a "can't close it" loop the user hit when round-
	// tripping detail page → "Show on atlas" → close.
	let focusParamConsumed = false;
	$: if (
		typeof window !== 'undefined' &&
		(SITE_MODE === 'atlas-root' || SITE_MODE === 'neuroscape') &&
		atlasBackdrop.length > 0 &&
		atlasSelection === null &&
		!focusParamConsumed
	) {
		const params = new URLSearchParams(window.location.search);
		const focusStr = params.get('focus');
		if (focusStr) {
			const focusId = Number(focusStr);
			if (Number.isFinite(focusId)) {
				const overlayHit = atlasOverlayById.get(focusId);
				if (overlayHit) {
					onAtlasPointClick(
						new CustomEvent('pointclick', {
							detail: { kind: 'ohbm2026', id: focusId }
						})
					);
				} else if (atlasBackdropById.get(focusId)) {
					onAtlasPointClick(
						new CustomEvent('pointclick', {
							detail: { kind: 'neuroscape', id: focusId }
						})
					);
				}
				// Strip `?focus=` + `?cluster=` from the URL so
				// closing the panel doesn't trigger another auto-open.
				// `replaceState` keeps the history entry intact (no
				// back-button confusion).
				params.delete('focus');
				params.delete('cluster');
				const search = params.toString();
				const cleaned =
					window.location.pathname +
					(search ? '?' + search : '') +
					window.location.hash;
				window.history.replaceState({}, '', cleaned);
			}
		}
		// Mark consumed regardless — even if there was no `?focus=`
		// or it didn't match, we only want this reactive to fire
		// once per page load. Future opens come from explicit clicks.
		focusParamConsumed = true;
	}
</script>

{#if SITE_MODE === 'atlas-root' || SITE_MODE === 'neuroscape'}
	<!-- UX unification: reuse OHBM 2026's `.home` / `.top-row` /
	     `.layout` structure so the atlas-root and neuroscape pages
	     have the same shape as `/ohbm2026/` — search at the top,
	     toggleable map below, then a results pane with an inline
	     detail panel on the right. SITE_MODE branches inside the
	     structure pick the appropriate browse-panel + control set;
	     the OHBM 2026 build still hits the `{:else}` branch lower
	     down (unchanged). -->
	<div
		class="home atlas-home"
		class:has-focus={atlasSelection !== null}
		data-testid="atlas-root-home"
		data-mode={SITE_MODE}
	>
		{#if SITE_MODE === 'atlas-root'}
			<AtlasSubsiteNav />
		{/if}
		<!-- Mobile admonition — the 461k-point scatter3d via Plotly +
		     SwiftShader is unkind to phones. Visible only when the
		     viewport is narrow; the underlying parquet (25-96 MB) is
		     also fetched lazily only when the user opts into the map.
		     The map toggle (top-row, below) starts OFF on mobile;
		     this banner explains why. -->
		{#if mobileViewport}
			<aside
				class="atlas-mobile-warning"
				data-testid="atlas-mobile-warning"
				role="note"
			>
				<strong>Mobile viewing tip</strong>
				<p>
					The 3D atlas renders {SITE_MODE === 'atlas-root'
						? '~461k PubMed points + the OHBM overlay'
						: '~461k PubMed points'}
					and downloads a {SITE_MODE === 'atlas-root'
						? '~35 MB'
						: '~96 MB'} data file. On phones this may drain
					battery and could incur cellular download charges. The
					map is hidden by default — tap "Show map" to load it if
					you're on Wi-Fi.
				</p>
			</aside>
		{/if}
		{#if SITE_MODE === 'atlas-root' && atlasDrift.length > 0}
			<!-- T043 / R-012 — surface BOTH drift signals loudly.

			     Confirmed drift (reason === 'mismatch'): visitor's
			     cross-conference clicks may land on stale ids. Action:
			     rebuild atlas.parquet against the current siblings.

			     Cannot-verify (reason === 'fetch-failed' or
			     'no-state-key'): we couldn't read the sibling's
			     manifest after 4 retries with backoff. The atlas may
			     be fine, but we can't confirm. Action: check the
			     sibling deployment is reachable + the parquet has a
			     state_key. -->
			{#each [{ kind: 'mismatch', items: atlasDrift.filter((d) => d.reason === 'mismatch') }, { kind: 'cannot-verify', items: atlasDrift.filter((d) => d.reason !== 'mismatch') }] as section (section.kind)}
				{#if section.items.length > 0}
					<aside
						class="atlas-drift-banner"
						class:atlas-drift-banner--mismatch={section.kind === 'mismatch'}
						class:atlas-drift-banner--cannot-verify={section.kind === 'cannot-verify'}
						role="alert"
						data-testid={`atlas-drift-banner-${section.kind}`}
					>
						{#if section.kind === 'mismatch'}
							<strong>Atlas data is out of sync with a sibling subsite.</strong>
							<ul class="atlas-drift-list" data-testid="atlas-drift-list">
								{#each section.items as d (d.sibling)}
									<li>
										<code>{d.sibling}</code> expected
										<code>{d.expected.slice(0, 8)}…</code> but found
										<code>{d.actual ? d.actual.slice(0, 8) + '…' : '(unknown)'}</code>
									</li>
								{/each}
							</ul>
							<p class="atlas-drift-explain">
								Cross-conference links may point at stale ids. Rebuild
								<code>atlas.parquet</code> against the current sibling parquets.
							</p>
						{:else}
							<strong
								>Couldn't verify atlas data against {section.items.length === 1
									? 'a sibling subsite'
									: 'sibling subsites'}.</strong
							>
							<ul class="atlas-drift-list" data-testid="atlas-drift-list-cannot-verify">
								{#each section.items as d (d.sibling)}
									<li>
										<code>{d.sibling}</code> ·
										{#if d.reason === 'fetch-failed'}
											fetch failed after retries{#if d.error_message}: <code>{d.error_message}</code>{/if}
										{:else}
											sibling parquet manifest has no state_key
										{/if}
									</li>
								{/each}
							</ul>
							<p class="atlas-drift-explain">
								Atlas may be fine, but we couldn't confirm. Check the
								Network tab for the actual error; refresh to retry.
							</p>
						{/if}
					</aside>
				{/if}
			{/each}
		{/if}
		<!-- Top row — minimal control set matching OHBM 2026's pattern:
		     search input + Show/Hide Map toggle. The overlay-visibility
		     toggle (atlas-root) is now driven by the Sites facet; the
		     dimensionality toggle + backdrop-opacity slider are gone
		     (sensible defaults instead, exposed later via a Settings
		     panel if needed). -->
		<div class="top-row">
			<div class="search-row">
				<!-- Spec 019 / T028 / FR-025 — replace the slim local-state
				     <input> with the shared <SearchBar> so atlas-root and
				     /neuroscape/ inherit OHBM 2026's operator syntax
				     verbatim (phrase, negation, OR, id:N). The corpus prop
				     drives the `id:` autocomplete data source + the
				     placeholder copy; the value binds via the same
				     `$searchQuery` store /ohbm2026/ uses. -->
				<SearchBar
					corpus={SITE_MODE === 'atlas-root' ? 'atlas-root' : 'neuroscape'}
					placeholderOverride={SITE_MODE === 'atlas-root'
						? 'Search OHBM 2026 + NeuroScape titles or ids…'
						: 'Search 461,316 NeuroScape titles…'}
					abstractsByPosterId={new Map()}
				/>
			</div>
			<div class="controls" data-testid="atlas-root-controls">
				<!-- Clear-selection button lives inside the UmapPanel header
				     for atlas/neuroscape modes, mirroring how OHBM 2026
				     does it. The top-row holds the map + filters toggles
				     (filters is mobile-only — desktop facet sidebar is
				     always visible via the .layout grid). -->
				<!-- Spec 019 / FR-001 — ✨ Semantic toggle on atlas-root +
				     /neuroscape/, parity with the same control on
				     /ohbm2026/ (OHBM branch below). Click flips the shared
				     `semanticEnabled` store; when the vectors sidecar is
				     configured this drives the full cluster-routed ranker
				     (searchNeuroscape), otherwise the KNN-only fallback. -->
				<button
					type="button"
					class="control-toggle"
					class:active={$semanticEnabled}
					on:click={() => semanticEnabled.toggle()}
					aria-pressed={$semanticEnabled}
					title={$semanticEnabled
						? rankerReady
							? rankerBusy
								? 'Semantic search is ON — searching…'
								: 'Semantic search is ON — cluster-routed ranker active'
							: 'Semantic search is ON — related-article (KNN) mode'
						: 'Semantic search is OFF — click to enable'}
					data-testid="toggle-semantic"
				>
					✨ Semantic
				</button>
				{#if $semanticEnabled && rankerCapExceeded}
					<button
						type="button"
						class="control-toggle"
						on:click={() => {
							rankerExpandSearchDepth();
							rankerCapExceeded = false;
							rankerDepthBump++;
						}}
						title="More clusters are relevant than the per-query cap allows. Expand to search them too."
						data-testid="expand-search-depth"
					>
						↧ Expand search depth
					</button>
				{/if}
				<button
					type="button"
					class="control-toggle mobile-only"
					class:active={showAtlasFacets}
					on:click={() => (showAtlasFacets = !showAtlasFacets)}
					aria-pressed={showAtlasFacets}
					data-testid="toggle-facets"
				>
					🔍 Filters
				</button>
				<button
					type="button"
					class="control-toggle"
					class:active={atlasShowMap}
					on:click={() => (atlasShowMap = !atlasShowMap)}
					aria-pressed={atlasShowMap}
					data-testid="toggle-map"
				>
					{atlasShowMap ? '✕ Hide map' : '🗺  Show map'}
				</button>
			</div>
		</div>

		<!-- Drift banners — surface before the scatter so the visitor
		     sees them above the fold. Only fires in atlas-root mode. -->
		{#if SITE_MODE === 'atlas-root' && atlasDrift.length > 0}
			{#each [{ kind: 'mismatch', items: atlasDrift.filter((d) => d.reason === 'mismatch') }, { kind: 'cannot-verify', items: atlasDrift.filter((d) => d.reason !== 'mismatch') }] as section (section.kind)}
				{#if section.items.length > 0}
					<aside
						class="atlas-drift-banner"
						class:atlas-drift-banner--mismatch={section.kind === 'mismatch'}
						class:atlas-drift-banner--cannot-verify={section.kind === 'cannot-verify'}
						role="alert"
						data-testid={`atlas-drift-banner-${section.kind}`}
					>
						{#if section.kind === 'mismatch'}
							<strong>Atlas data is out of sync with a sibling subsite.</strong>
							<ul class="atlas-drift-list" data-testid="atlas-drift-list">
								{#each section.items as d (d.sibling)}
									<li>
										<code>{d.sibling}</code> expected
										<code>{d.expected.slice(0, 8)}…</code> but found
										<code>{d.actual ? d.actual.slice(0, 8) + '…' : '(unknown)'}</code>
									</li>
								{/each}
							</ul>
							<p class="atlas-drift-explain">
								Cross-conference links may point at stale ids. Rebuild
								<code>atlas.parquet</code> against the current sibling parquets.
							</p>
						{:else}
							<strong
								>Couldn't verify atlas data against {section.items.length === 1
									? 'a sibling subsite'
									: 'sibling subsites'}.</strong
							>
							<ul class="atlas-drift-list" data-testid="atlas-drift-list-cannot-verify">
								{#each section.items as d (d.sibling)}
									<li>
										<code>{d.sibling}</code> ·
										{#if d.reason === 'fetch-failed'}
											fetch failed after retries{#if d.error_message}: <code
													>{d.error_message}</code
												>{/if}
										{:else}
											sibling parquet manifest has no state_key
										{/if}
									</li>
								{/each}
							</ul>
							<p class="atlas-drift-explain">
								Atlas may be fine, but we couldn't confirm. Check the
								Network tab for the actual error; refresh to retry.
							</p>
						{/if}
					</aside>
				{/if}
			{/each}
		{/if}

		<!-- Map panel — toggleable above the layout grid, OHBM-style.
		     The loading state OVERLAYS the UmapPanel containers (the
		     2D + 3D chart frames render immediately, the loading
		     status floats on top of the frame area) instead of
		     replacing them with a bottom-of-page placeholder. Same
		     pattern as native map widgets: visitor sees where the
		     map WILL be while it loads. -->
		{#if atlasShowMap}
			<div class="atlas-map-wrap">
				<UmapPanel
					mode={SITE_MODE === 'atlas-root' ? 'atlas' : 'neuroscape'}
					backdropPoints={scatterBackdropForMap}
					overlayPoints={scatterOverlay}
					atlasClusters={atlasClusters}
					showOverlay={SITE_MODE === 'atlas-root' ? filterShowOhbm : false}
					backdropOpacity={0.05}
					lassoOhbmSet={atlasLassoOhbmSet}
					lassoNeuroSet={atlasLassoNeuroSet}
					atlasFocusKind={atlasSelection?.kind ?? null}
					atlasFocusId={atlasSelection
						? atlasSelection.kind === 'ohbm2026'
							? atlasSelection.poster_id
							: atlasSelection.pubmed_id
						: null}
					on:pointclick={onAtlasPointClick}
					on:lassoselect={onAtlasLasso}
					on:lassoclear={clearAtlasLasso}
				/>
				{#if atlasError}
					<div class="atlas-map-overlay" data-testid="atlas-scatter-error" role="alert">
						<p class="placeholder-text">{atlasError}</p>
					</div>
				{:else if atlasBackdrop.length === 0}
					<div class="atlas-map-overlay" data-testid="atlas-scatter-loading">
						<p class="placeholder-text">
							{#if atlasPhase === 'connecting'}
								Connecting to {SITE_MODE === 'atlas-root'
									? 'cross-conference atlas'
									: 'NeuroScape atlas'}…
							{:else if atlasPhase === 'downloading'}
								Downloading {SITE_MODE === 'atlas-root'
									? 'cross-conference atlas'
									: 'NeuroScape atlas'}…
								{#if atlasProgressPercent !== null}
									<strong data-testid="atlas-loading-percent">{atlasProgressPercent}%</strong>
								{:else if atlasProgressLoaded > 0}
									<strong data-testid="atlas-loading-bytes"
										>{formatMb(atlasProgressLoaded)}</strong
									>
								{/if}
							{:else if atlasPhase === 'parsing'}
								Parsing
								{#if atlasProgressLoaded > 0}
									<strong data-testid="atlas-loading-parsing-bytes"
										>{formatMb(atlasProgressLoaded)}</strong
									>
								{/if}
								{SITE_MODE === 'atlas-root' ? 'cross-conference atlas' : 'NeuroScape atlas'}…
							{:else}
								Loading {SITE_MODE === 'atlas-root'
									? 'cross-conference atlas'
									: 'NeuroScape atlas'}…
							{/if}
						</p>
						{#if atlasPhase === 'downloading' && atlasProgressPercent !== null}
							<progress
								class="atlas-progress"
								value={atlasProgressPercent}
								max="100"
								data-testid="atlas-loading-progressbar"
							></progress>
						{:else}
							<progress class="atlas-progress" data-testid="atlas-loading-indeterminate"></progress>
						{/if}
					</div>
				{/if}
			</div>
		{/if}

		<!-- 3-column layout grid — facets | list | detail. Uses OHBM's
		     `.layout` rules directly (no `atlas-layout` overrides):
		     single column on mobile, 3 columns ≥1024 px, facet-pane
		     opens via `.open` when the user taps "🔍 Filters". -->
		{#if atlasBackdrop.length > 0}
			<div class="layout">
				<div class="facet-pane" class:open={showAtlasFacets}>
					{#if SITE_MODE === 'atlas-root'}
						<AtlasRootFacets
							clustersById={atlasClustersById}
							{clusterCounts}
							ohbmCount={siteCounts.ohbm}
							neuroCount={siteCounts.neuro}
							selectedClusterIds={filterClusterIds}
							showOhbm={filterShowOhbm}
							showNeuro={filterShowNeuro}
							on:update={(ev) => {
								filterClusterIds = ev.detail.cluster_ids;
								filterShowOhbm = ev.detail.show_ohbm;
								filterShowNeuro = ev.detail.show_neuro;
							}}
						/>
					{:else}
						<NeuroscapeFacets
							clustersById={atlasClustersById}
							{clusterCounts}
							selectedClusterIds={filterClusterIds}
							minYear={filterMinYear}
							maxYear={filterMaxYear}
							{yearBounds}
							on:update={(ev) => {
								filterClusterIds = ev.detail.cluster_ids;
								filterMinYear = ev.detail.min_year;
								filterMaxYear = ev.detail.max_year;
							}}
						/>
					{/if}
				</div>
				<div class="list-pane">
					{#if SITE_MODE === 'neuroscape'}
						<NeuroscapeBrowsePanel
							articles={filteredBackdrop}
							clustersById={atlasClustersById}
							query={$debouncedSearchQuery}
							semanticHits={neuroscapeSemanticHits}
							searchIndex={titleSearchIndex}
							on:focus={(ev) => {
								// Update the URL so deep-link restore + back-button work,
								// THEN open the detail panel so the inline third pane
								// renders the article + its nearest-neighbours list.
								const url = new URL(window.location.href);
								url.searchParams.set('focus', String(ev.detail.pubmed_id));
								url.searchParams.set('cluster', String(ev.detail.cluster_id));
								window.history.pushState({}, '', url);
								onAtlasPointClick(
									new CustomEvent('pointclick', {
										detail: { kind: 'neuroscape', id: ev.detail.pubmed_id }
									})
								);
							}}
						/>
					{:else}
						<AtlasRootBrowsePanel
							backdropPoints={filteredBackdrop}
							overlayPoints={filteredOverlay}
							clustersById={atlasClustersById}
							permalinkFor={atlasPermalink}
							query={$debouncedSearchQuery}
							semanticHits={neuroscapeSemanticHits}
							searchIndex={titleSearchIndex}
							on:select={(ev) => {
								onAtlasPointClick(
									new CustomEvent('pointclick', { detail: ev.detail })
								);
							}}
						/>
					{/if}
				</div>
				<div class="detail-pane" class:active={atlasSelection !== null}>
					{#if atlasSelection}
						<AtlasRootDetailPanel
							selection={atlasSelection}
							clustersById={atlasClustersById}
							mode="inline"
							neighbours={detailNeighbours}
							on:close={() => (atlasSelection = null)}
						/>
					{:else}
						<aside class="detail-empty">
							<p>
								{SITE_MODE === 'atlas-root'
									? 'Click a result or a point on the map to see details here.'
									: 'Click a result or a point on the map to see article details here.'}
							</p>
						</aside>
					{/if}
				</div>
			</div>
		{/if}

		<!-- AtlasRootLassoResults modal removed in slice E: lassoed
		     ids now filter the result-list inline (see
		     `filteredBackdrop` / `filteredOverlay` reactives). The
		     "Clear lasso (n)" button in the top-row resets state. -->
	</div>
{:else}
<div class="home" class:has-focus={focused !== null}>
	<div class="top-row">
		<div class="search-row">
			<SearchBar {abstractsByPosterId} />
			<span class="kbd-hint" data-testid="goto-kbd-hint" aria-hidden="true">
				<kbd>g</kbd> jump to poster id
			</span>
			{#if $authorChips.size > 0}
				<div class="author-chips" data-testid="author-chips">
					<span class="chips-label">authors:</span>
					{#each [...$authorChips] as name (name)}
						<span class="chip" data-testid="author-chip">
							<span class="chip-name">{name}</span>
							<button
								type="button"
								class="chip-x"
								on:click={() => removeChip(name)}
								aria-label={`Remove ${name} from author filter`}
								title={`Remove ${name}`}
								data-testid="author-chip-remove"
							>×</button>
						</span>
					{/each}
					{#if $authorChips.size > 1}
						<button
							type="button"
							class="chip-clear-all"
							on:click={clearAllChips}
							data-testid="author-chips-clear"
						>
							clear all
						</button>
					{/if}
				</div>
			{/if}
		</div>
		{#if loaded && !dataMissing}
			<div class="controls">
				<ModelSelector {manifest} />
				<button
					type="button"
					class="control-toggle"
					class:active={$semanticEnabled}
					class:loading={$semanticEnabled &&
						($semanticStatus.state === 'loading-vectors' || $semanticStatus.state === 'loading-model')}
					class:errored={$semanticEnabled && $semanticStatus.state === 'error'}
					on:click={() => semanticEnabled.toggle()}
					aria-pressed={$semanticEnabled}
					title={$semanticStatus.state === 'ready'
						? $semanticEnabled
							? 'Semantic search is ON — click to disable'
							: 'Semantic search is OFF — click to enable'
						: $semanticStatus.state === 'loading-model'
							? 'Loading MiniLM model… search will be live shortly'
							: $semanticStatus.state === 'loading-vectors'
								? 'Loading semantic vectors…'
								: $semanticStatus.state === 'error'
									? `Semantic search unavailable: ${$semanticStatus.message}`
									: $semanticEnabled
										? 'Semantic search ON — engaging on first query'
										: 'Semantic search OFF — click to enable'}
					data-testid="toggle-semantic"
				>
					{#if $semanticEnabled && ($semanticStatus.state === 'loading-vectors' || $semanticStatus.state === 'loading-model')}
						⏳
					{:else}
						✨
					{/if}
					Semantic
				</button>
				<button
					type="button"
					class="control-toggle mobile-only"
					class:active={showFacets}
					on:click={() => (showFacets = !showFacets)}
					aria-pressed={showFacets}
					data-testid="toggle-facets"
				>
					🔍 Filters
				</button>
				<button
					type="button"
					class="control-toggle"
					class:active={$showMap}
					on:click={() => showMap.update((v) => !v)}
					aria-pressed={$showMap}
					data-testid="toggle-map"
				>
					{$showMap ? '✕ Hide map' : '🗺  Show map'}
				</button>
				<button
					type="button"
					class="control-toggle"
					class:active={$cartOnly}
					disabled={$cartStore.size === 0 && !$cartOnly}
					on:click={() => cartOnly.update((v) => !v)}
					aria-pressed={$cartOnly}
					title={$cartOnly
						? 'Showing saved abstracts only — click to show everything'
						: $cartStore.size === 0
							? 'Saved-only filter — your list is empty'
							: `Filter to the ${$cartStore.size} saved abstract${$cartStore.size === 1 ? '' : 's'}`}
					data-testid="toggle-cart-only"
				>
					{$cartOnly ? '✓ Saved' : 'Saved only'}
				</button>
				<!-- The 🛒 N "open cart drawer" button is now in the
				     unifying SiteHeader so it's the single source on
				     every subsite. The "Saved only" filter stays here
				     because it's OHBM-home-specific (no equivalent on
				     atlas-root / neuroscape). -->
			</div>
		{/if}
	</div>

	<!-- Cart drawer is mounted by `+layout.svelte` for ALL subsites so
	     the 🛒 toggle in the unified SiteHeader works from anywhere.
	     The OHBM home publishes its abstracts + authors into the shared
	     `ohbmTitleLookup` store, so cart rows render with rich titles. -->

	{#if $showMap && loaded && !dataMissing}
		<UmapPanel {abstracts} selection={filteredIds} />
	{/if}

	{#if !loaded}
		<p class="status">Loading…</p>
	{:else if dataMissing}
		<section class="placeholder" data-testid="data-missing">
			<h2>Data package not deployed yet</h2>
			{#if envBuildInfo}
				<p class="committish-callout">
					This preview is built from
					<code data-testid="placeholder-short-sha">{envBuildInfo.code_revision_short}</code>
					but no <code>data/abstracts.json</code> was found.
				</p>
			{/if}
			<p>
				The deploy workflow runs against the source code; the Stage 1–4 inputs aren't yet
				wired into CI via <code>scripts/fetch_ui_inputs.sh</code>. Build locally per
				<code>specs/008-ui-rewrite/quickstart.md</code> to exercise the full UI.
			</p>
		</section>
	{:else}
		<div class="layout">
			<div class="facet-pane" class:open={showFacets} data-testid="facet-pane">
				<FacetSidebar counts={facetCounts} />
			</div>
			<div class="list-pane">
				<ResultList
					{abstracts}
					{authorsById}
					{filteredIds}
					{semanticScores}
					lexicalIds={lexicalIds}
					lexicalExactness={lexicalExactness}
					{defaultRank}
				/>
			</div>
			<div class="detail-pane" class:active={focused !== null}>
				{#if focused}
					<DetailPanel abstract={focused} {authorsById} {abstractsById} compact={true} />
				{:else}
					<aside class="detail-empty">
						<p>Tap an abstract to see its details here.</p>
						{#if manifest}
							<dl class="manifest-stats">
								<dt>Accepted abstracts</dt>
								<dd data-testid="abstract-count">{manifest.corpus_count}</dd>
							</dl>
						{/if}
					</aside>
				{/if}
			</div>
		</div>
	{/if}
</div>
{/if}

<style>
	/* Stage 15 atlas-root chrome. Dead-CSS-eliminated in
	   non-atlas-root builds (the markup branch is gone, so Svelte
	   marks these selectors as unused and they don't ship). */
	.atlas-drift-banner {
		border-radius: 4px;
		padding: 0.75rem 1rem;
		margin: 0.75rem clamp(1rem, 2vw, 2rem);
		font-size: 0.92rem;
	}
	.atlas-drift-banner--mismatch {
		/* Yellow — confirmed drift; user-actionable. */
		background: var(--warning-bg);
		color: var(--warning-text);
		border: 1px solid var(--warning-border);
	}
	.atlas-drift-banner--cannot-verify {
		/* Subtle — "couldn't check" is informational, not alarming. */
		background: var(--bg-subtle);
		color: var(--text-muted);
		border: 1px solid var(--border);
	}
	.atlas-drift-list {
		margin: 0.4rem 0 0.4rem 1.25rem;
		padding: 0;
	}
	.atlas-drift-explain {
		margin: 0;
		color: var(--warning-text);
		opacity: 0.85;
	}
	.atlas-drift-banner code {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		background: rgba(0, 0, 0, 0.06);
		padding: 0 0.25em;
		border-radius: 2px;
	}

	/* UX-unification — atlas-home reuses OHBM's `.home` + `.layout` +
	   `.facet-pane` / `.list-pane` / `.detail-pane` shape directly.
	   The only atlas-specific overrides here are:
	     - page-wide padding (atlas-root + neuroscape use a minimal
	       shell, not OHBM's `.shell` wrapper that adds the OHBM
	       header padding)
	     - the mobile admonition banner styling
	     - the side-by-side 2D + 3D scatter row at desktop
	   Everything else (grid columns, .open facet pattern, detail-pane
	   overlay on mobile, has-focus widening) is inherited from
	   OHBM's CSS at the bottom of this stylesheet. */
	.atlas-home {
		min-height: 100vh;
		padding: 0 clamp(1rem, 2vw, 2rem) 1rem;
		box-sizing: border-box;
	}
	.atlas-mobile-warning {
		margin-top: 0.75rem;
		padding: 0.7rem 0.9rem;
		border-radius: 6px;
		border: 1px solid var(--warning-border, #b8860b);
		background: var(--warning-bg, #fff7e0);
		color: var(--warning-text, #5c4400);
		font-size: 0.85rem;
		line-height: 1.4;
	}
	.atlas-mobile-warning strong {
		display: block;
		margin-bottom: 0.2rem;
		font-size: 0.9rem;
	}
	.atlas-mobile-warning p {
		margin: 0;
	}
	@media (prefers-color-scheme: dark) {
		.atlas-mobile-warning {
			background: rgba(184, 134, 11, 0.18);
			color: #f0d68d;
			border-color: rgba(184, 134, 11, 0.45);
		}
	}
	/* `.atlas-map-wrap` hosts the UmapPanel + an absolutely-positioned
	   loading overlay so the chart frames are visible as soon as the
	   map toggle flips on, with the loading status floating over them
	   until the parquet finishes parsing. */
	.atlas-map-wrap {
		position: relative;
	}
	.atlas-map-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.6rem;
		padding: 1rem;
		background: rgba(255, 255, 255, 0.78);
		backdrop-filter: blur(2px);
		-webkit-backdrop-filter: blur(2px);
		z-index: 10;
		border-radius: 6px;
		pointer-events: none;
	}
	@media (prefers-color-scheme: dark) {
		.atlas-map-overlay {
			background: rgba(20, 22, 28, 0.78);
		}
	}
	.atlas-map-overlay .placeholder-text {
		margin: 0;
		color: var(--text);
		font-size: 0.95rem;
		text-align: center;
		max-width: 32rem;
	}
	.atlas-map-overlay .placeholder-text strong {
		color: var(--accent);
		font-variant-numeric: tabular-nums;
		margin-left: 0.3rem;
	}
	.atlas-map-overlay .atlas-progress {
		width: min(20rem, 80%);
		height: 0.45rem;
	}
	.placeholder-text {
		color: var(--text-muted);
		margin: 0;
	}
	.atlas-progress {
		width: 16rem;
		height: 0.6rem;
	}

	.home {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.top-row {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		align-items: center;
		justify-content: space-between;
	}
	.search-row {
		flex: 1 1 22rem;
		min-width: 0;
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0;
	}
	/* `g jump to poster id` is a discoverability hint that used to
	   add ~1rem of vertical space below the SearchBar inside the
	   search-row column. The extra height pushed the search input's
	   centre off the baseline of the MODEL/INPUT/Semantic/Hide/Saved
	   controls that the parent .top-row centre-aligns against — the
	   SearchBar sat slightly above the controls instead of in line
	   with them. Float the hint absolutely below the search-row so
	   it carries zero layout height and the baseline lines up. */
	.kbd-hint {
		position: absolute;
		top: 100%;
		left: 0;
		margin-top: 0.2rem;
		font-size: 0.75rem;
		color: var(--text-muted);
		pointer-events: none;
		white-space: nowrap;
	}
	.kbd-hint kbd {
		display: inline-block;
		padding: 0.05rem 0.35rem;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.7rem;
		background: var(--bg-subtle);
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text);
		margin-right: 0.25rem;
	}
	.search-row:focus-within .kbd-hint {
		visibility: hidden;
	}
	.author-chips {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.35rem;
	}
	.chips-label {
		font-size: 0.75rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text, var(--text));
		padding: 0.15rem 0.5rem 0.15rem 0.6rem;
		border-radius: 999px;
		font-size: 0.78rem;
		border: 1px solid var(--accent);
	}
	.chip-x {
		all: unset;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 0.9rem;
		height: 0.9rem;
		line-height: 1;
		font-size: 0.85rem;
		color: var(--accent);
		border-radius: 999px;
	}
	.chip-x:hover {
		background: var(--accent);
		color: var(--accent-text, white);
	}
	.chip-clear-all {
		all: unset;
		cursor: pointer;
		font-size: 0.7rem;
		color: var(--text-muted);
		text-decoration: underline;
		padding: 0.15rem 0.3rem;
	}
	.chip-clear-all:hover {
		color: var(--text);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.45rem 0.5rem;
		width: 100%;
	}
	.control-toggle {
		all: unset;
		cursor: pointer;
		padding: 0.4rem 0.7rem;
		border-radius: 4px;
		font-size: 0.85rem;
		border: 1px solid var(--border-strong);
		background: var(--bg);
		color: var(--text);
		white-space: nowrap;
	}
	@media (max-width: 480px) {
		.control-toggle {
			font-size: 0.78rem;
			padding: 0.35rem 0.55rem;
		}
	}
	@media (min-width: 720px) {
		.controls {
			width: auto;
			align-items: flex-end;
			gap: 0.75rem;
		}
	}
	.control-toggle:hover {
		background: var(--bg-sunken);
	}
	.control-toggle.active {
		background: var(--accent);
		color: var(--accent-text);
		border-color: var(--accent);
	}
	.control-toggle.loading {
		/* still highlighted (active + loading); add a subtle pulsing tint */
		opacity: 0.85;
		cursor: progress;
	}
	.control-toggle.errored {
		background: var(--warning-bg);
		color: var(--text);
		border-color: var(--warning-border);
	}
	.control-toggle:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 1rem;
		width: 100%;
	}
	.facet-pane {
		min-width: 0;
		display: none; /* shown via class on smaller viewports; @media for desktop */
	}
	.facet-pane.open {
		display: block;
	}
	.list-pane {
		min-width: 0;
	}
	.detail-pane {
		min-width: 0;
	}
	.detail-empty {
		background: var(--bg-subtle);
		border: 1px dashed var(--border-strong);
		border-radius: 6px;
		padding: 1rem;
		color: var(--text-muted);
	}
	.manifest-stats {
		margin: 0.75rem 0 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.25rem 1rem;
		font-size: 0.9rem;
	}
	.manifest-stats dt {
		color: var(--text-faint);
	}
	.placeholder {
		background: var(--warning-bg);
		border: 1px solid var(--warning-border);
		color: var(--text);
		border-radius: 6px;
		padding: 1rem;
	}
	.committish-callout {
		font-size: 0.95rem;
	}
	.status {
		color: var(--text-muted);
		font-style: italic;
	}
	code {
		background: var(--bg-sunken);
		color: var(--text);
		padding: 0 0.25rem;
		border-radius: 3px;
		font-size: 0.95em;
	}

	@media (min-width: 1024px) {
		.layout {
			grid-template-columns: clamp(14rem, 18vw, 20rem) minmax(0, 1fr) clamp(22rem, 26vw, 38rem);
			align-items: start;
		}
		.facet-pane {
			display: block !important; /* always visible on desktop */
			position: sticky;
			top: 1rem;
			max-height: calc(100vh - 2rem);
			overflow-y: auto;
			padding-right: 0.5rem;
		}
		.detail-pane {
			position: sticky;
			top: 1rem;
			max-height: calc(100vh - 2rem);
			overflow-y: auto;
		}
		.mobile-only {
			display: none;
		}
	}

	/* Mobile: detail panel becomes a full-screen overlay when focused. */
	@media (max-width: 1023px) {
		.home.has-focus .list-pane {
			display: none;
		}
		.detail-pane:not(.active) {
			display: none;
		}
		.home.has-focus .detail-pane {
			display: block;
		}
	}
</style>
