<!--
  Stage 15 UX-unification — atlas-root facet sidebar.

  Visually + behaviourally mirrors OHBM 2026's `FacetSidebar`:
    - `<aside class="facets">` wrapper with "Filters" header + Clear
    - One collapsible `<section class="facet">` per facet group, each
      with a count + chevron + checkbox list

  Facets:
    - Sites (Sites): OHBM 2026 | NeuroScape PubMed (binary checkboxes
      driving filterShowOhbm / filterShowNeuro). Live counts of
      filtered rows in each.
    - Clusters: 175-option searchable multi-select.

  State is owned by `+page.svelte`; this component reads via props
  + dispatches changes. Same separation OHBM 2026 uses for its
  FacetSidebar.
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { normalize } from '$lib/filter';

	type Cluster = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};

	export let clustersById: Map<number, Cluster> = new Map();
	export let clusterCounts: Map<number, number> = new Map();
	export let ohbmCount: number = 0;
	export let neuroCount: number = 0;
	export let selectedClusterIds: Set<number>;
	export let showOhbm: boolean;
	export let showNeuro: boolean;

	const dispatch = createEventDispatcher<{
		update: {
			cluster_ids: Set<number>;
			show_ohbm: boolean;
			show_neuro: boolean;
		};
	}>();

	let sitesOpen = true;
	let clustersOpen = true;
	let clusterSearch = '';

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

	$: activeCount =
		selectedClusterIds.size + (showOhbm ? 0 : 1) + (showNeuro ? 0 : 1);

	function notify(next: {
		cluster_ids: Set<number>;
		show_ohbm: boolean;
		show_neuro: boolean;
	}) {
		dispatch('update', next);
	}

	function toggleCluster(id: number) {
		const next = new Set(selectedClusterIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		notify({ cluster_ids: next, show_ohbm: showOhbm, show_neuro: showNeuro });
	}

	function clearAll() {
		notify({ cluster_ids: new Set(), show_ohbm: true, show_neuro: true });
	}

	function toggleOhbm() {
		notify({ cluster_ids: selectedClusterIds, show_ohbm: !showOhbm, show_neuro: showNeuro });
	}
	function toggleNeuro() {
		notify({ cluster_ids: selectedClusterIds, show_ohbm: showOhbm, show_neuro: !showNeuro });
	}
</script>

<aside class="facets" data-testid="atlas-root-facet-sidebar">
	<header>
		<h2>Filters</h2>
		{#if activeCount > 0}
			<button
				type="button"
				class="clear"
				on:click={clearAll}
				data-testid="atlas-root-facets-clear"
			>
				Clear ({activeCount})
			</button>
		{/if}
	</header>

	<section class="facet" data-testid="atlas-root-facet-sites">
		<button
			type="button"
			class="facet-header"
			on:click={() => (sitesOpen = !sitesOpen)}
			aria-expanded={sitesOpen}
		>
			<span class="caret">{sitesOpen ? '▾' : '▸'}</span>
			<span class="facet-label">Sites</span>
			<span class="facet-count">2</span>
		</button>
		{#if sitesOpen}
			<ul class="options">
				<li>
					<label class="opt" class:active={showOhbm}>
						<input
							type="checkbox"
							checked={showOhbm}
							on:change={toggleOhbm}
							data-testid="atlas-root-site-ohbm"
						/>
						<span class="opt-label">OHBM 2026</span>
						<span class="opt-count">{ohbmCount.toLocaleString()}</span>
					</label>
				</li>
				<li>
					<label class="opt" class:active={showNeuro}>
						<input
							type="checkbox"
							checked={showNeuro}
							on:change={toggleNeuro}
							data-testid="atlas-root-site-neuro"
						/>
						<span class="opt-label">NeuroScape PubMed</span>
						<span class="opt-count">{neuroCount.toLocaleString()}</span>
					</label>
				</li>
			</ul>
		{/if}
	</section>

	<section class="facet" data-testid="atlas-root-facet-clusters">
		<button
			type="button"
			class="facet-header"
			on:click={() => (clustersOpen = !clustersOpen)}
			aria-expanded={clustersOpen}
		>
			<span class="caret">{clustersOpen ? '▾' : '▸'}</span>
			<span class="facet-label">Clusters</span>
			<span class="facet-count">{clustersById.size}</span>
			{#if selectedClusterIds.size > 0}
				<span class="facet-active" data-testid="atlas-root-cluster-selected-count"
					>· {selectedClusterIds.size} selected</span
				>
			{/if}
		</button>
		{#if clustersOpen}
			<input
				type="search"
				class="cluster-search"
				placeholder="Filter clusters…"
				bind:value={clusterSearch}
				data-testid="atlas-root-cluster-search"
			/>
			<ul class="options scroll" data-testid="atlas-root-cluster-list">
				{#each clusterPickList as c (c.cluster_id)}
					{@const count = clusterCounts.get(c.cluster_id) ?? 0}
					<li>
						<label class="opt" class:active={selectedClusterIds.has(c.cluster_id)}>
							<input
								type="checkbox"
								checked={selectedClusterIds.has(c.cluster_id)}
								on:change={() => toggleCluster(c.cluster_id)}
								data-testid={`atlas-root-cluster-cb-${c.cluster_id}`}
							/>
							<span
								class="cluster-swatch"
								style="background:{c.colour_hex}"
								aria-hidden="true"
							></span>
							<span class="opt-label" title={c.title}>{c.title}</span>
							<span class="opt-count">{count.toLocaleString()}</span>
						</label>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</aside>

<style>
	.facets {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-bottom: 0.25rem;
		border-bottom: 1px solid var(--border);
	}
	h2 {
		font-size: 0.95rem;
		font-weight: 600;
		margin: 0;
	}
	.clear {
		all: unset;
		cursor: pointer;
		font-size: 0.78rem;
		color: var(--text-muted);
		padding: 0.2rem 0.45rem;
		border-radius: 3px;
		border: 1px solid var(--border);
	}
	.clear:hover {
		background: var(--bg-subtle);
		color: var(--text);
	}
	.facet {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.facet-header {
		all: unset;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.3rem;
		font-size: 0.9rem;
		color: var(--text);
		border-radius: 3px;
	}
	.facet-header:hover {
		background: var(--bg-subtle);
	}
	.caret {
		font-size: 0.75em;
		color: var(--text-muted);
		width: 1em;
	}
	.facet-label {
		font-weight: 600;
	}
	.facet-count {
		color: var(--text-muted);
		font-size: 0.78rem;
		font-variant-numeric: tabular-nums;
	}
	.facet-active {
		color: var(--accent-soft-text, var(--accent));
		font-size: 0.78rem;
	}
	.cluster-search {
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg);
		color: var(--text);
		font-size: 0.82rem;
	}
	.options {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.options.scroll {
		max-height: 16rem;
		overflow-y: auto;
		border: 1px solid var(--border);
		border-radius: 3px;
		padding: 0.1rem 0;
	}
	.opt {
		display: grid;
		grid-template-columns: 1rem auto 1fr auto;
		gap: 0.4rem;
		align-items: center;
		padding: 0.25rem 0.45rem;
		cursor: pointer;
		font-size: 0.83rem;
		border-radius: 2px;
	}
	.opt:hover {
		background: var(--bg-subtle);
	}
	.opt.active {
		background: var(--accent-soft-bg);
	}
	.cluster-swatch {
		display: inline-block;
		width: 0.65rem;
		height: 0.65rem;
		border-radius: 2px;
		border: 1px solid var(--border);
	}
	.opt-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.opt-count {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		font-size: 0.76rem;
	}
	.facet:nth-of-type(1) .opt {
		/* Sites facet has no swatch — collapse the swatch column. */
		grid-template-columns: 1rem 1fr auto;
	}
</style>
