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
	/* Visual alignment with OHBM 2026's FacetSidebar: flex rows with
	   word-break: break-word so long cluster titles wrap across
	   multiple lines instead of being ellipsis-truncated. The swatch
	   sits as a fixed-width first child; flex-start alignment lets it
	   line up with the first wrapped line. */
	.facets {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		font-size: 0.85rem;
		color: var(--text);
	}
	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
		padding-bottom: 0.5rem;
		border-bottom: 1px solid var(--border);
	}
	h2 {
		margin: 0;
		font-size: 0.95rem;
		font-weight: 600;
	}
	.clear {
		all: unset;
		cursor: pointer;
		font-size: 0.75rem;
		color: var(--accent);
		padding: 0.2rem 0.5rem;
		border-radius: 3px;
		border: 1px solid var(--border);
	}
	.clear:hover {
		background: var(--bg-sunken);
	}
	.facet {
		display: flex;
		flex-direction: column;
	}
	.facet-header {
		all: unset;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.35rem 0;
		font-weight: 500;
		color: var(--text);
	}
	.facet-header:hover {
		color: var(--accent);
	}
	.caret {
		font-size: 0.65rem;
		color: var(--text-muted);
		width: 0.7rem;
	}
	.facet-label {
		flex: 1;
		font-size: 0.85rem;
	}
	.facet-count {
		font-size: 0.7rem;
		color: var(--text-faint);
		font-variant-numeric: tabular-nums;
	}
	.facet-active {
		color: var(--accent-soft-text, var(--accent));
		font-size: 0.7rem;
	}
	.cluster-search {
		padding: 0.3rem 0.5rem;
		margin: 0 0 0.25rem 1.1rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg);
		color: var(--text);
		font-size: 0.82rem;
	}
	.options {
		list-style: none;
		padding: 0 0 0.25rem 1.1rem;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.options.scroll {
		max-height: 14rem;
		overflow-y: auto;
		padding-right: 0.4rem;
	}
	.opt {
		display: flex;
		align-items: flex-start;
		gap: 0.4rem;
		padding: 0.15rem 0.35rem;
		border-radius: 3px;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.opt input[type='checkbox'] {
		margin: 0;
		margin-top: 0.18rem;
	}
	.opt:hover {
		background: var(--bg-sunken);
	}
	.opt.active {
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text);
	}
	.cluster-swatch {
		display: inline-block;
		width: 0.65rem;
		height: 0.65rem;
		margin-top: 0.32rem;
		flex-shrink: 0;
		border-radius: 2px;
		border: 1px solid var(--border);
	}
	.opt-label {
		flex: 1;
		min-width: 0;
		line-height: 1.25;
		word-break: break-word;
	}
	.opt-count {
		flex-shrink: 0;
		font-size: 0.72rem;
		color: var(--text-faint);
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
</style>
