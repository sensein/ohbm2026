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
	import { activeFilters, authorChips, cartOnly, focusedAbstract, lassoSelection, searchQuery, selectedCell, showMap } from '$lib/stores/selection';
	import { lexicalSearch, parseQuery, queryForSemantic } from '$lib/filter';
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
	import CartDrawer from '$lib/components/CartDrawer.svelte';
	// Stage 15 (spec 015-neuroscape-context, FR-008/FR-009/FR-013/FR-014):
	// the bare-root cross-conference atlas landing page mounts a small
	// chrome (header + binary toggle + density slider) in place of the
	// existing OHBM-2026-only home page. SITE_MODE is a build-time
	// constant (Vite substitutes `import.meta.env.VITE_SITE_MODE` at
	// compile time), so the {#if SITE_MODE === 'atlas-root'} branch
	// below is dead-code eliminated in the 'ohbm2026' / 'neuroscape'
	// builds — FR-022 byte-identity is preserved.
	import { SITE_MODE } from '$lib/site_mode';
	import LandingPageHeader from '$lib/components/LandingPageHeader.svelte';
	import AtlasOverlayToggle from '$lib/components/AtlasOverlayToggle.svelte';
	import BackdropDensitySlider from '$lib/components/BackdropDensitySlider.svelte';
	import AtlasUmapPanel from '$lib/components/AtlasUmapPanel.svelte';
	import AtlasRootDetailPanel from '$lib/components/AtlasRootDetailPanel.svelte';
	import AtlasRootLassoResults from '$lib/components/AtlasRootLassoResults.svelte';
	import DimensionalityToggle from '$lib/components/DimensionalityToggle.svelte';
	import { base } from '$app/paths';
	import { atlasOverlay } from '$lib/stores/atlas_overlay';
	import { dimensionality } from '$lib/stores/dimensionality';
	import {
		loadDataPackage,
		verifyAtlasSiblingDrift,
		type AtlasDriftEntry
	} from '$lib/data_package/loader';

	// Shapes the AtlasUmapPanel expects. Defined here (not imported
	// from the .svelte component) because Svelte's type re-export
	// path is unreliable across the build.
	type AtlasBackdropPoint = {
		pubmed_id: number;
		cluster_id: number;
		umap_3d: [number, number, number];
		title: string;
		year: number;
	};
	type AtlasOverlayPoint = {
		submission_id: number;
		poster_id: number;
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
	let cartOpen = false;
	let semanticScores: Map<number, number> | null = null;
	let semanticQuerySerial = 0;
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
	let atlasOverlayPoints: AtlasOverlayPoint[] = [];
	let atlasClusters: AtlasClusterRow[] = [];
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
	let atlasLassoOhbmIds: number[] = [];
	let atlasLassoNeuroIds: number[] = [];

	// O(1) lookup maps built whenever the atlas data lands.
	$: atlasOverlayById = new Map(atlasOverlayPoints.map((p) => [p.poster_id, p]));
	$: atlasBackdropById = new Map(atlasBackdrop.map((p) => [p.pubmed_id, p]));
	$: atlasClustersById = new Map(
		atlasClusters.map((c) => [c.cluster_id, { cluster_id: c.cluster_id, title: c.title, colour_hex: c.colour_hex }])
	);

	// Permalink construction. cross_pointers in atlas.parquet documents
	// these URLs at build time; constructing them here is equivalent
	// (the convention is part of the spec) and avoids round-tripping
	// the table for every click. `base` is the deploy root in
	// atlas-root mode (no per-mode suffix), so `${base}/ohbm2026/...`
	// resolves to the OHBM 2026 sibling at any deploy depth
	// (production `/`, PR preview `/pr-N/`).
	function atlasPermalink(kind: 'ohbm2026' | 'neuroscape', id: number): string {
		const root = base;
		return kind === 'ohbm2026'
			? `${root}/ohbm2026/abstract/${id}/`
			: `${root}/neuroscape/abstract/${id}/`;
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

	function onAtlasLasso(
		ev: CustomEvent<{ ohbm2026_ids: number[]; neuroscape_ids: number[] }>
	) {
		atlasLassoOhbmIds = ev.detail.ohbm2026_ids;
		atlasLassoNeuroIds = ev.detail.neuroscape_ids;
	}

	function clearAtlasLasso() {
		atlasLassoOhbmIds = [];
		atlasLassoNeuroIds = [];
	}
	// T043 — drift banner state. Populated by the sibling-state-key
	// check that fires in the background after atlas.parquet loads.
	let atlasDrift: AtlasDriftEntry[] = [];
	let atlasLoading = false;
	let atlasError: string | null = null;
	let atlasProgressLoaded = 0;
	let atlasProgressTotal: number | null = null;
	// Phase string drives the placeholder label so the parsing window
	// (CPU-bound, no byte progress) doesn't look frozen on fast links.
	let atlasPhase: 'connecting' | 'downloading' | 'parsing' | 'ready' = 'connecting';

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
				atlasError =
					SITE_MODE === 'atlas-root'
						? 'Atlas data package URL not configured.'
						: 'NeuroScape data package URL not configured.';
				return;
			}
			if (SITE_MODE === 'atlas-root') {
				const backdropShard = pkg.get('data/atlas/backdrop_full.json') as
					| { points: AtlasBackdropPoint[] }
					| undefined;
				const overlayShard = pkg.get('data/atlas/ohbm_overlay.json') as
					| { points: AtlasOverlayPoint[] }
					| undefined;
				const clustersShard = pkg.get('data/atlas/clusters.json') as
					| { clusters: AtlasClusterRow[] }
					| undefined;
				if (!backdropShard || !overlayShard || !clustersShard) {
					atlasError = 'Atlas data package is missing one of the expected row groups.';
					return;
				}
				atlasBackdrop = backdropShard.points;
				atlasOverlayPoints = overlayShard.points;
				atlasClusters = clustersShard.clusters;
				// T043 — Fire the sibling-state-key drift check in the
				// background. The scatter renders immediately with the
				// atlas data; if the check completes with a mismatch,
				// a banner appears on top. The check itself is HTTP-Range-
				// limited (~10 KB per sibling), so the network cost is
				// trivial compared to the 34 MB atlas parquet we just
				// finished streaming.
				const manifest = pkg.get('data/manifest.json');
				void verifyAtlasSiblingDrift(manifest).then((result) => {
					if (!result.ok) atlasDrift = result.drift;
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
				atlasBackdrop = articlesShard.articles;
				atlasOverlayPoints = [];
				atlasClusters = clustersShard.clusters;
			}
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
	});
</script>

{#if SITE_MODE === 'atlas-root' || SITE_MODE === 'neuroscape'}
	<!-- Stage 15 atlas-root + neuroscape modes — both use the
	     LandingPageHeader + AtlasUmapPanel. The atlas-root mode
	     additionally shows the overlay toggle (OHBM 2026 layer). -->
	<div class="atlas-root-home" data-testid="atlas-root-home" data-mode={SITE_MODE}>
		<LandingPageHeader />
		{#if SITE_MODE === 'atlas-root' && atlasDrift.length > 0}
			<!-- T043 / R-012: cross-parquet drift banner. One of the
			     sibling deployments doesn't match what atlas.parquet
			     was built against. The scatter may show stale ids;
			     surface this loudly rather than rendering a partial /
			     silently-wrong cross-link experience. -->
			<aside
				class="atlas-drift-banner"
				role="alert"
				data-testid="atlas-drift-banner"
			>
				<strong>Atlas data is out of sync with a sibling subsite.</strong>
				<ul class="atlas-drift-list" data-testid="atlas-drift-list">
					{#each atlasDrift as d (d.sibling)}
						<li>
							<code>{d.sibling}</code> expected
							<code>{d.expected.slice(0, 8)}…</code> but found
							<code>{d.actual ? d.actual.slice(0, 8) + '…' : `(${d.reason})`}</code>
						</li>
					{/each}
				</ul>
				<p class="atlas-drift-explain">
					Cross-conference links may point at stale ids. Rebuild
					<code>atlas.parquet</code> against the current sibling parquets.
				</p>
			</aside>
		{/if}
		<main class="atlas-root-main">
			<div class="atlas-controls" data-testid="atlas-root-controls">
				{#if SITE_MODE === 'atlas-root'}
					<AtlasOverlayToggle />
				{/if}
				<DimensionalityToggle />
				<BackdropDensitySlider bind:value={backdropDensity} />
				{#if SITE_MODE === 'neuroscape'}
					<span class="neuroscape-tag" data-testid="neuroscape-mode-tag"
						>NeuroScape PubMed atlas <em>· browse/search coming soon</em></span
					>
				{/if}
			</div>
			{#if atlasError}
				<div class="atlas-scatter-placeholder" data-testid="atlas-scatter-error" role="alert">
					<p class="placeholder-text">{atlasError}</p>
				</div>
			{:else if atlasBackdrop.length === 0}
				<!-- Render the loading placeholder whenever data hasn't
				     populated yet — covers SSR (atlasLoading=false), the
				     client-hydration window (atlasLoading=true,
				     atlasBackdrop=[]), AND any future case where the
				     load is retried. The user always sees a visible
				     "Loading…" state instead of a blank/empty panel. -->
				<div class="atlas-scatter-placeholder" data-testid="atlas-scatter-loading">
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
						<!-- Always show an indeterminate bar when no determinate
						     value is available — covers SSR (no progress yet),
						     connecting (no bytes), parsing (no byte counter),
						     and the no-Content-Length fallback. Without this,
						     fast connections that finish the byte stream before
						     the user can perceive the bar see only a blank
						     "Loading…" text. -->
						<progress class="atlas-progress" data-testid="atlas-loading-indeterminate"
						></progress>
					{/if}
				</div>
			{:else}
				<AtlasUmapPanel
					backdropPoints={atlasBackdrop}
					overlayPoints={atlasOverlayPoints}
					clusters={atlasClusters}
					showOverlay={SITE_MODE === 'atlas-root' ? $atlasOverlay : false}
					backdropOpacity={backdropDensity}
					dimensionality={$dimensionality}
					on:pointclick={onAtlasPointClick}
					on:lassoselect={onAtlasLasso}
					on:lassoclear={clearAtlasLasso}
				/>
			{/if}
		</main>
		{#if SITE_MODE === 'atlas-root'}
			<AtlasRootDetailPanel
				selection={atlasSelection}
				clustersById={atlasClustersById}
				on:close={() => (atlasSelection = null)}
			/>
			<AtlasRootLassoResults
				ohbm2026_ids={atlasLassoOhbmIds}
				neuroscape_ids={atlasLassoNeuroIds}
				overlayById={atlasOverlayById}
				backdropById={atlasBackdropById}
				permalinkFor={atlasPermalink}
				on:close={clearAtlasLasso}
			/>
		{/if}
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
				<button
					type="button"
					class="control-toggle cart-toggle"
					class:active={$cartStore.size > 0}
					on:click={() => (cartOpen = true)}
					aria-label={`Open your list (${$cartStore.size} saved)`}
					title={$cartStore.size > 0
						? `${$cartStore.size} abstract${$cartStore.size === 1 ? '' : 's'} saved — click to open`
						: 'Your list is empty — save abstracts via the cart icon on each result'}
					data-testid="toggle-cart"
				>
					🛒 {$cartStore.size}
				</button>
			</div>
		{/if}
	</div>

	<CartDrawer bind:open={cartOpen} {abstracts} {authorsById} />

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
		background: var(--warning-bg);
		color: var(--warning-text);
		border: 1px solid var(--warning-border);
		border-radius: 4px;
		padding: 0.75rem 1rem;
		margin: 0.75rem clamp(1rem, 2vw, 2rem);
		font-size: 0.92rem;
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

	.atlas-root-home {
		display: flex;
		flex-direction: column;
		min-height: 100vh;
	}
	.atlas-root-main {
		flex: 1;
		display: flex;
		flex-direction: column;
		padding: 1rem 1.25rem;
		gap: 1rem;
	}
	.atlas-controls {
		display: flex;
		gap: 1rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.atlas-scatter-placeholder {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.75rem;
		border: 1px dashed var(--border);
		border-radius: 6px;
		min-height: 50vh;
	}
	.placeholder-text {
		color: var(--text-muted);
		margin: 0;
	}
	.atlas-progress {
		width: 16rem;
		height: 0.6rem;
	}
	.neuroscape-tag {
		color: var(--text-muted);
		font-size: 0.85rem;
		margin-left: auto;
	}
	.neuroscape-tag em {
		font-style: italic;
		opacity: 0.7;
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
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.kbd-hint {
		font-size: 0.75rem;
		color: var(--text-muted);
		padding-left: 0.2rem;
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
