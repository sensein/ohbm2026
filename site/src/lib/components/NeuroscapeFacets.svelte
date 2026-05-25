<!--
  Stage 15 UX-unification — neuroscape facet sidebar.

  Same OHBM-FacetSidebar visual pattern as AtlasRootFacets:
    - `<aside class="facets">` with "Filters" header + Clear button
    - Collapsible `<section class="facet">` per group

  Facets:
    - Clusters: 175-option multi-select, same as atlas-root.
    - Years: a range filter (min / max bounded by the corpus' min/max
      year). Two number inputs in the OHBM `.opt` rail visual.
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
	export let selectedClusterIds: Set<number>;
	export let minYear: number | null;
	export let maxYear: number | null;
	export let yearBounds: { lo: number; hi: number };

	const dispatch = createEventDispatcher<{
		update: {
			cluster_ids: Set<number>;
			min_year: number | null;
			max_year: number | null;
		};
	}>();

	let clustersOpen = true;
	let yearsOpen = true;
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
		selectedClusterIds.size +
		(minYear !== null && minYear > yearBounds.lo ? 1 : 0) +
		(maxYear !== null && maxYear < yearBounds.hi ? 1 : 0);

	function notify(next: {
		cluster_ids: Set<number>;
		min_year: number | null;
		max_year: number | null;
	}) {
		dispatch('update', next);
	}

	function toggleCluster(id: number) {
		const next = new Set(selectedClusterIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		notify({ cluster_ids: next, min_year: minYear, max_year: maxYear });
	}

	function clearAll() {
		notify({ cluster_ids: new Set(), min_year: null, max_year: null });
	}

	function onMinYear(e: Event) {
		const v = (e.target as HTMLInputElement).value;
		const n = v === '' ? null : Number(v);
		notify({
			cluster_ids: selectedClusterIds,
			min_year: Number.isFinite(n as number) ? (n as number) : null,
			max_year: maxYear
		});
	}
	function onMaxYear(e: Event) {
		const v = (e.target as HTMLInputElement).value;
		const n = v === '' ? null : Number(v);
		notify({
			cluster_ids: selectedClusterIds,
			min_year: minYear,
			max_year: Number.isFinite(n as number) ? (n as number) : null
		});
	}
</script>

<aside class="facets" data-testid="neuroscape-facet-sidebar">
	<header>
		<h2>Filters</h2>
		{#if activeCount > 0}
			<button
				type="button"
				class="clear"
				on:click={clearAll}
				data-testid="neuroscape-facets-clear"
			>
				Clear ({activeCount})
			</button>
		{/if}
	</header>

	<section class="facet" data-testid="neuroscape-facet-years">
		<button
			type="button"
			class="facet-header"
			on:click={() => (yearsOpen = !yearsOpen)}
			aria-expanded={yearsOpen}
		>
			<span class="caret">{yearsOpen ? '▾' : '▸'}</span>
			<span class="facet-label">Years</span>
			<span class="facet-count">{yearBounds.lo}–{yearBounds.hi}</span>
		</button>
		{#if yearsOpen}
			<div class="year-row">
				<label class="year-input">
					<span>From</span>
					<input
						type="number"
						min={yearBounds.lo}
						max={yearBounds.hi}
						value={minYear ?? ''}
						placeholder={String(yearBounds.lo)}
						on:input={onMinYear}
						data-testid="neuroscape-year-min"
					/>
				</label>
				<label class="year-input">
					<span>To</span>
					<input
						type="number"
						min={yearBounds.lo}
						max={yearBounds.hi}
						value={maxYear ?? ''}
						placeholder={String(yearBounds.hi)}
						on:input={onMaxYear}
						data-testid="neuroscape-year-max"
					/>
				</label>
			</div>
		{/if}
	</section>

	<section class="facet" data-testid="neuroscape-facet-clusters">
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
				<span class="facet-active" data-testid="neuroscape-cluster-selected-count"
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
				data-testid="neuroscape-cluster-search"
			/>
			<ul class="options scroll" data-testid="neuroscape-cluster-list">
				{#each clusterPickList as c (c.cluster_id)}
					{@const count = clusterCounts.get(c.cluster_id) ?? 0}
					<li>
						<label class="opt" class:active={selectedClusterIds.has(c.cluster_id)}>
							<input
								type="checkbox"
								checked={selectedClusterIds.has(c.cluster_id)}
								on:change={() => toggleCluster(c.cluster_id)}
								data-testid={`neuroscape-cluster-cb-${c.cluster_id}`}
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
	.year-row {
		display: flex;
		gap: 0.5rem;
		padding: 0.2rem 0.3rem;
	}
	.year-input {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		font-size: 0.78rem;
		color: var(--text-muted);
	}
	.year-input input {
		padding: 0.25rem 0.4rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg-elevated);
		color: var(--text);
		font-size: 0.85rem;
		font-variant-numeric: tabular-nums;
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
</style>
