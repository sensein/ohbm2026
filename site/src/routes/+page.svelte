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
	import { activeFilters, cartOnly, focusedAbstract, lassoSelection, searchQuery, selectedCell } from '$lib/stores/selection';
	import { lexicalSearch } from '$lib/filter';
	import { filterByFacets, recomputeFacets, type FacetCellContext } from '$lib/facets';
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

	let manifest: Manifest | null = null;
	let abstracts: AbstractRecord[] = [];
	let authorsById: Map<number, AuthorRecord> = new Map();
	let abstractsByPosterId: Map<string, AbstractRecord> = new Map();
	let abstractsById: Map<number, AbstractRecord> = new Map();
	let loaded = false;
	let dataMissing = false;
	let showMap = false;
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
		const ids = records.map((r) => r.abstract_id);
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
		const [m, a, au] = await Promise.all([loadManifest(), loadAbstracts(), loadAuthors()]);
		manifest = m;
		if (a && au) {
			abstracts = a.abstracts;
			defaultRank = buildRandomRank(abstracts);
			authorsById = new Map(au.authors.map((x) => [x.author_id, x]));
			abstractsByPosterId = new Map(
				a.abstracts.filter((x) => x.poster_id).map((x) => [x.poster_id, x])
			);
			abstractsById = new Map(a.abstracts.map((x) => [x.abstract_id, x]));
			// Test-only debug global used by Playwright accepted-only invariant guard.
			if (typeof window !== 'undefined') {
				(window as unknown as { __abstracts: AbstractRecord[] }).__abstracts = abstracts;
			}
		} else {
			dataMissing = true;
		}
		loaded = true;
		// Warm the semantic worker in the background so the model is ready
		// the moment the user types. The worker does NOT influence ordering
		// while the search box is empty — the reactive block below nulls
		// `semanticScores` whenever `$searchQuery` is blank.
		if (!dataMissing) {
			void (async () => {
				try {
					const mod = await import('$lib/search/semantic');
					await mod.warmSemantic();
				} catch (err) {
					console.warn('semantic search unavailable:', err);
				}
			})();
		}
	});

	// Re-run semantic search on query change, with serial-number guard so
	// out-of-order completions don't overwrite a newer result. Skipped when
	// the user has disabled semantic via the toggle.
	$: void (async (q: string, on: boolean) => {
		const trimmed = q.trim();
		if (!on || !trimmed) {
			semanticScores = null;
			return;
		}
		const my = ++semanticQuerySerial;
		try {
			const mod = await import('$lib/search/semantic');
			const hits = await mod.semanticSearch(trimmed, 50);
			if (my !== semanticQuerySerial) return;
			// Translate worker indices (positional in abstracts.json) → abstract_id
			// AND preserve the per-hit cosine similarity so the card can show it.
			const scores = new Map<number, number>();
			for (const h of hits) {
				const rec = abstracts[h.index];
				if (rec) scores.set(rec.abstract_id, h.score);
			}
			semanticScores = scores;
		} catch {
			if (my === semanticQuerySerial) semanticScores = null;
		}
	})($searchQuery, $semanticEnabled);

	$: lexicalResult = lexicalSearch(abstracts, authorsById, $searchQuery);
	$: lexicalIds = lexicalResult?.ids ?? null;
	$: lexicalExactness = lexicalResult?.exactness ?? null;
	$: semanticIdsForMerge = semanticScores
		? new Set<number>(semanticScores.keys())
		: null;
	$: searchIds = mergeSearch(lexicalIds, semanticIdsForMerge, $searchQuery);

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
	$: preFilterForFacetCounts = intersect(intersect(searchIds, $lassoSelection), cartIds);
	$: facetCounts = recomputeFacets(abstracts, $activeFilters, preFilterForFacetCounts, facetCtx);
	$: filteredIds = intersect(intersect(intersect(searchIds, $lassoSelection), facetIds), cartIds);

	function cartIdsFromStore(
		byPid: Map<string, AbstractRecord>,
		cart: Set<string>
	): Set<number> {
		const out = new Set<number>();
		for (const pid of cart) {
			const rec = byPid.get(pid);
			if (rec) out.add(rec.abstract_id);
		}
		return out;
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
		const clusterLabelByAbstractId = new Map<number, string>();
		if (shard) {
			for (const row of shard.rows) {
				const label = labelByCluster.get(row.community_id);
				if (label) clusterLabelByAbstractId.set(row.abstract_id, label);
			}
		}
		return { clusterLabelByAbstractId };
	}

	function mergeSearch(
		lex: Set<number> | null,
		sem: Set<number> | null,
		query: string
	): Set<number> | null {
		if (!query.trim()) return null;
		if (lex === null && sem === null) return null;
		if (lex === null) return sem;
		if (sem === null) return lex;
		const union = new Set<number>(lex);
		for (const id of sem) union.add(id);
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
</script>

<div class="home" class:has-focus={focused !== null}>
	<div class="top-row">
		<div class="search-row">
			<SearchBar />
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
					class:active={showMap}
					on:click={() => (showMap = !showMap)}
					aria-pressed={showMap}
					data-testid="toggle-map"
				>
					{showMap ? '✕ Hide map' : '🗺  Show map'}
				</button>
				<button
					type="button"
					class="control-toggle"
					class:active={$cartOnly}
					disabled={$cartStore.size === 0}
					on:click={() => cartOnly.update((v) => !v)}
					aria-pressed={$cartOnly}
					title={$cartStore.size === 0
						? 'Saved-only filter — your list is empty'
						: $cartOnly
							? 'Showing saved abstracts only — click to show everything'
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

	{#if showMap && loaded && !dataMissing}
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
								<dt>Models × inputs</dt>
								<dd>{manifest.models.length} × {manifest.inputs.length}</dd>
								<dt>Cells</dt>
								<dd>{manifest.cells.length}</dd>
							</dl>
						{/if}
					</aside>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
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
	}
	.controls {
		display: flex;
		align-items: flex-end;
		gap: 0.75rem;
	}
	.control-toggle {
		all: unset;
		cursor: pointer;
		padding: 0.45rem 0.8rem;
		border-radius: 4px;
		font-size: 0.85rem;
		border: 1px solid var(--border-strong);
		background: var(--bg);
		color: var(--text);
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
		cursor: progress;
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
