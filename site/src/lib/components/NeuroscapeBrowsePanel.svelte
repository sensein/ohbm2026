<!--
  Stage 15 UX-unification — neuroscape result list pane.

  Slim companion to AtlasRootBrowsePanel. Facet state lives in
  NeuroscapeFacets + +page.svelte; this component receives
  pre-filtered articles + the title-search query and renders a
  paginated result list with click-through to the detail page.
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

	/** Pre-filtered by the parent (cluster + year facets applied). */
	export let articles: Article[] = [];
	export let clustersById: Map<number, Cluster> = new Map();
	export let query: string = '';

	const dispatch = createEventDispatcher<{
		focus: { pubmed_id: number; cluster_id: number };
	}>();

	let limit = 100;

	$: filtered = (() => {
		if (!query.trim()) {
			return [...articles].sort((a, b) => b.year - a.year || a.pubmed_id - b.pubmed_id);
		}
		const needle = normalize(query);
		const scored: Array<{ a: Article; score: number }> = [];
		for (const a of articles) {
			const hay = normalize(a.title);
			const idx = hay.indexOf(needle);
			if (idx === -1) continue;
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
</script>

<section class="ns-browse" data-testid="neuroscape-browse-panel">
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
		gap: 0.5rem;
		min-width: 0;
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
