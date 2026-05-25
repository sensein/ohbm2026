<!--
  Stage 15 (spec 015-neuroscape-context, T067):
  NeuroScape PubMed subsite browse panel.

  Title-bar search + result list of articles, scoped to
  neuroscape.parquet's `articles` rows. Click a row → navigate to
  /neuroscape/abstract/<pubmed_id>/.

  Search shape (FR-018): title-only, case-insensitive, currently
  substring + token-prefix scoring (NOT yet the full typo-tolerant
  engine the OHBM 2026 SearchBar uses). The spec's "parametrise the
  existing typo-tolerant engine" intent is deferred — pulling the
  engine apart cleanly is its own slice. This implementation covers
  the common case (visitor types "hippocampus" or "place cells" →
  ranked title matches) and the empty-query case (first 100 by
  PubMed id).

  Pagination: shows first 100 matches, with a "Show more" affordance
  that doubles the cap. The full 461k corpus is too dense to render
  in one list.
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { base } from '$app/paths';
	import { normalize } from '$lib/filter';

	type Article = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
	};
	type Cluster = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};

	export let articles: Article[] = [];
	export let clustersById: Map<number, Cluster> = new Map();

	const dispatch = createEventDispatcher<{
		focus: { pubmed_id: number; cluster_id: number };
		filter: { cluster_ids: Set<number> };
	}>();

	let query = '';
	let limit = 100;

	// Year facet — typical visitor wants to narrow to "recent" articles.
	let minYear: number | null = null;
	let maxYear: number | null = null;

	// Cluster facet — multi-select; empty = no cluster filter.
	let selectedClusterIds: Set<number> = new Set();
	let clusterSearch = '';
	let clusterFacetOpen = false;

	// Sorted cluster list for the picker. Sort by total article count
	// descending so the most-populous clusters surface first; ties
	// broken alphabetically by title.
	$: clusterCounts = (() => {
		const counts = new Map<number, number>();
		for (const a of articles) counts.set(a.cluster_id, (counts.get(a.cluster_id) ?? 0) + 1);
		return counts;
	})();
	$: clusterPickList = (() => {
		const list = [...clustersById.values()];
		list.sort((a, b) => {
			const ca = clusterCounts.get(a.cluster_id) ?? 0;
			const cb = clusterCounts.get(b.cluster_id) ?? 0;
			if (ca !== cb) return cb - ca;
			return a.title.localeCompare(b.title);
		});
		if (!clusterSearch.trim()) return list;
		const needle = normalize(clusterSearch);
		return list.filter((c) => normalize(c.title).includes(needle));
	})();

	function toggleCluster(id: number) {
		const next = new Set(selectedClusterIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedClusterIds = next;
		dispatch('filter', { cluster_ids: next });
	}
	function clearClusters() {
		selectedClusterIds = new Set();
		dispatch('filter', { cluster_ids: selectedClusterIds });
	}
	$: yearBounds = (() => {
		if (articles.length === 0) return { lo: 0, hi: 0 };
		let lo = Infinity;
		let hi = -Infinity;
		for (const a of articles) {
			if (a.year < lo) lo = a.year;
			if (a.year > hi) hi = a.year;
		}
		return { lo: Number.isFinite(lo) ? lo : 0, hi: Number.isFinite(hi) ? hi : 0 };
	})();

	$: filtered = (() => {
		// Year + cluster facets first — cheap, narrow the search space.
		const yLo = minYear ?? yearBounds.lo;
		const yHi = maxYear ?? yearBounds.hi;
		const facetFilt = articles.filter((a) => {
			if (a.year < yLo || a.year > yHi) return false;
			if (selectedClusterIds.size > 0 && !selectedClusterIds.has(a.cluster_id))
				return false;
			return true;
		});
		if (!query.trim()) {
			// No query → "Recent first" ordering (descending by year,
			// then by pubmed_id for stability).
			return [...facetFilt].sort((a, b) => b.year - a.year || a.pubmed_id - b.pubmed_id);
		}
		const needle = normalize(query);
		// Score by first-match position; ties broken by year desc.
		const scored: Array<{ a: Article; score: number }> = [];
		for (const a of facetFilt) {
			const hay = normalize(a.title);
			const idx = hay.indexOf(needle);
			if (idx === -1) continue;
			// Earlier match = lower score = better; -idx makes higher
			// scores worse so we sort ascending by `score`.
			scored.push({ a, score: idx });
		}
		scored.sort((x, y) => x.score - y.score || y.a.year - x.a.year);
		return scored.map((s) => s.a);
	})();

	$: visible = filtered.slice(0, limit);

	function gotoDetail(pubmed_id: number) {
		return `${base}/abstract/${pubmed_id}/`;
	}

	function onShowOnAtlas(a: Article) {
		dispatch('focus', { pubmed_id: a.pubmed_id, cluster_id: a.cluster_id });
	}

	function clearQuery() {
		query = '';
	}
</script>

<section class="ns-browse" data-testid="neuroscape-browse-panel">
	<div class="ns-search-row">
		<label class="ns-search">
			<span class="visually-hidden">Search NeuroScape titles</span>
			<input
				type="search"
				placeholder="Search 461,316 NeuroScape titles…"
				bind:value={query}
				data-testid="neuroscape-search-input"
			/>
			{#if query}
				<button
					type="button"
					class="ns-clear"
					on:click={clearQuery}
					aria-label="Clear search"
					data-testid="neuroscape-search-clear"
				>
					×
				</button>
			{/if}
		</label>

		<div class="ns-facets">
			<label class="ns-year">
				<span>Year ≥</span>
				<input
					type="number"
					min={yearBounds.lo}
					max={yearBounds.hi}
					bind:value={minYear}
					placeholder={String(yearBounds.lo)}
					data-testid="neuroscape-year-min"
				/>
			</label>
			<label class="ns-year">
				<span>Year ≤</span>
				<input
					type="number"
					min={yearBounds.lo}
					max={yearBounds.hi}
					bind:value={maxYear}
					placeholder={String(yearBounds.hi)}
					data-testid="neuroscape-year-max"
				/>
			</label>

			<!-- Cluster facet — collapsible because there are 175 of
			     them; opens to a searchable scrollable checkbox list. -->
			<details
				class="ns-cluster-facet"
				bind:open={clusterFacetOpen}
				data-testid="neuroscape-cluster-facet"
			>
				<summary>
					Clusters
					{#if selectedClusterIds.size > 0}
						<span
							class="ns-cluster-count"
							data-testid="neuroscape-cluster-selected-count"
							>({selectedClusterIds.size})</span
						>
					{/if}
				</summary>
				<div class="ns-cluster-panel">
					<div class="ns-cluster-controls">
						<input
							type="search"
							placeholder="Filter clusters…"
							bind:value={clusterSearch}
							data-testid="neuroscape-cluster-search"
						/>
						{#if selectedClusterIds.size > 0}
							<button
								type="button"
								class="ns-cluster-clear"
								on:click={clearClusters}
								data-testid="neuroscape-cluster-clear"
							>
								Clear ({selectedClusterIds.size})
							</button>
						{/if}
					</div>
					<ul class="ns-cluster-list" data-testid="neuroscape-cluster-list">
						{#each clusterPickList as c (c.cluster_id)}
							{@const count = clusterCounts.get(c.cluster_id) ?? 0}
							<li>
								<label class="ns-cluster-row">
									<input
										type="checkbox"
										checked={selectedClusterIds.has(c.cluster_id)}
										on:change={() => toggleCluster(c.cluster_id)}
										data-testid={`neuroscape-cluster-cb-${c.cluster_id}`}
									/>
									<span
										class="ns-cluster-swatch"
										style="background:{c.colour_hex}"
									></span>
									<span class="ns-cluster-title">{c.title}</span>
									<span class="ns-cluster-n">{count.toLocaleString()}</span>
								</label>
							</li>
						{/each}
					</ul>
				</div>
			</details>
		</div>
	</div>

	<p class="ns-count" data-testid="neuroscape-result-count">
		{filtered.length.toLocaleString()} {filtered.length === 1 ? 'match' : 'matches'}
		{#if filtered.length > limit}
			· showing first {limit}
		{/if}
	</p>

	<ul class="ns-results" data-testid="neuroscape-result-list">
		{#each visible as a (a.pubmed_id)}
			{@const cluster = clustersById.get(a.cluster_id)}
			<li class="ns-row">
				<a
					class="ns-row-link"
					href={gotoDetail(a.pubmed_id)}
					data-testid="neuroscape-result-row"
				>
					<div class="ns-row-head">
						<span class="ns-pmid">PMID {a.pubmed_id}</span>
						<span class="ns-year">{a.year}</span>
						{#if cluster}
							<span class="ns-cluster">
								<span
									class="ns-cluster-swatch"
									style="background:{cluster.colour_hex}"
								></span>
								{cluster.title}
							</span>
						{/if}
					</div>
					<div class="ns-title">{a.title}</div>
				</a>
				<button
					type="button"
					class="ns-show-atlas"
					title="Focus this article on the atlas"
					on:click={() => onShowOnAtlas(a)}
					data-testid="neuroscape-row-show-atlas"
				>
					On atlas
				</button>
			</li>
		{/each}
	</ul>

	{#if filtered.length > limit}
		<button
			type="button"
			class="ns-more"
			on:click={() => (limit = Math.min(limit * 2, filtered.length))}
			data-testid="neuroscape-show-more"
		>
			Show more
		</button>
	{/if}
</section>

<style>
	.ns-browse {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}
	.ns-search-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		align-items: center;
	}
	.ns-search {
		flex: 1 1 18rem;
		position: relative;
		display: flex;
		align-items: center;
	}
	.ns-search input[type='search'] {
		width: 100%;
		padding: 0.5rem 2rem 0.5rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-elevated);
		color: var(--text);
		font-size: 0.95rem;
	}
	.ns-clear {
		all: unset;
		cursor: pointer;
		position: absolute;
		right: 0.5rem;
		font-size: 1.1rem;
		color: var(--text-muted);
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
	}
	.ns-clear:hover {
		background: var(--bg-subtle);
		color: var(--text);
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		border: 0;
	}
	.ns-facets {
		display: flex;
		gap: 0.6rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.ns-year {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
		font-size: 0.85rem;
		color: var(--text-muted);
	}
	.ns-year input {
		width: 5rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg-elevated);
		color: var(--text);
		font-size: 0.85rem;
	}
	.ns-cluster-facet {
		position: relative;
		font-size: 0.85rem;
	}
	.ns-cluster-facet > summary {
		cursor: pointer;
		padding: 0.3rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg-elevated);
		color: var(--text);
		list-style: none;
		user-select: none;
	}
	.ns-cluster-facet > summary::-webkit-details-marker {
		display: none;
	}
	.ns-cluster-facet > summary::before {
		content: '▸';
		display: inline-block;
		margin-right: 0.3em;
		font-size: 0.7em;
		color: var(--text-muted);
	}
	.ns-cluster-facet[open] > summary::before {
		content: '▾';
	}
	.ns-cluster-count {
		color: var(--text-muted);
		font-weight: 500;
		margin-left: 0.3em;
	}
	.ns-cluster-panel {
		position: absolute;
		z-index: 50;
		top: calc(100% + 0.25rem);
		left: 0;
		min-width: 22rem;
		max-width: 30rem;
		max-height: 22rem;
		display: flex;
		flex-direction: column;
		background: var(--bg-elevated);
		border: 1px solid var(--border);
		border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
	}
	.ns-cluster-controls {
		display: flex;
		gap: 0.5rem;
		padding: 0.5rem;
		border-bottom: 1px solid var(--border);
	}
	.ns-cluster-controls input[type='search'] {
		flex: 1;
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg);
		color: var(--text);
		font-size: 0.85rem;
	}
	.ns-cluster-clear {
		all: unset;
		cursor: pointer;
		padding: 0.35rem 0.6rem;
		border-radius: 3px;
		font-size: 0.8rem;
		color: var(--text-muted);
		border: 1px solid var(--border);
	}
	.ns-cluster-clear:hover {
		color: var(--text);
		background: var(--bg-subtle);
	}
	.ns-cluster-list {
		list-style: none;
		margin: 0;
		padding: 0.25rem 0;
		overflow-y: auto;
		flex: 1;
	}
	.ns-cluster-row {
		display: grid;
		grid-template-columns: 1rem 0.7rem 1fr auto;
		gap: 0.5rem;
		align-items: center;
		padding: 0.3rem 0.6rem;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.ns-cluster-row:hover {
		background: var(--bg-subtle);
	}
	.ns-cluster-swatch {
		display: inline-block;
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 2px;
		border: 1px solid var(--border);
	}
	.ns-cluster-title {
		overflow-wrap: anywhere;
		line-height: 1.3;
	}
	.ns-cluster-n {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		font-size: 0.78rem;
	}
	.ns-count {
		margin: 0;
		font-size: 0.85rem;
		color: var(--text-muted);
	}
	.ns-results {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		max-height: 70vh;
		overflow-y: auto;
	}
	.ns-row {
		display: flex;
		gap: 0.5rem;
		align-items: stretch;
		padding: 0.5rem 0.65rem;
		border-radius: 4px;
		border: 1px solid var(--border);
	}
	.ns-row:hover {
		background: var(--bg-subtle);
	}
	.ns-row-link {
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		text-decoration: none;
		color: var(--text);
		min-width: 0;
	}
	.ns-row-head {
		display: flex;
		gap: 0.7rem;
		flex-wrap: wrap;
		font-size: 0.78rem;
		color: var(--text-muted);
	}
	.ns-pmid {
		font-variant-numeric: tabular-nums;
	}
	.ns-cluster {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
	}
	.ns-cluster-swatch {
		display: inline-block;
		width: 0.6rem;
		height: 0.6rem;
		border-radius: 2px;
		border: 1px solid var(--border);
	}
	.ns-title {
		font-size: 0.92rem;
		line-height: 1.35;
		color: var(--text);
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.ns-show-atlas {
		all: unset;
		cursor: pointer;
		padding: 0.35rem 0.6rem;
		border-radius: 3px;
		font-size: 0.78rem;
		color: var(--accent);
		border: 1px solid var(--accent);
		background: transparent;
		align-self: flex-start;
		white-space: nowrap;
	}
	.ns-show-atlas:hover {
		background: var(--accent-soft-bg);
	}
	.ns-more {
		all: unset;
		cursor: pointer;
		align-self: center;
		padding: 0.4rem 0.85rem;
		border-radius: 4px;
		background: var(--accent);
		color: var(--accent-text);
		font-size: 0.88rem;
		font-weight: 500;
	}
	.ns-more:hover {
		filter: brightness(1.05);
	}
</style>
