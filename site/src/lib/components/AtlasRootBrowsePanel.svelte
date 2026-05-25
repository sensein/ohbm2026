<!--
  Stage 15 UX-unification — atlas-root result list pane.

  Slimmed down from the earlier monolithic browse panel: facet state
  lives in `AtlasRootFacets` + `+page.svelte`, and the parent passes
  ALREADY-FILTERED backdrop + overlay points. This component is
  responsible for:
    - Combining the two pre-filtered sources into one result list
    - Title + id substring search via the `query` prop (lives in
      the top-row, bound from `+page.svelte`)
    - Pagination (100 per page, doubles via Show more)
    - Click row → sibling permalink (via the `?spa=` handoff) OR
      in-page detail panel via the "Details" button
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { normalize } from '$lib/filter';
	import { cartOhbmPosterIds, cartNeuroPubmedIds } from '$lib/stores/cart';
	import CartIconButton from '$lib/components/CartIconButton.svelte';

	type BackdropPoint = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
	};
	type OverlayPoint = {
		submission_id: number;
		poster_id: number;
		title: string;
		nearest_cluster_id: number;
	};
	type Cluster = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};

	/** Pre-filtered by the parent (cluster + sites facets applied). */
	export let backdropPoints: BackdropPoint[] = [];
	export let overlayPoints: OverlayPoint[] = [];
	export let clustersById: Map<number, Cluster> = new Map();
	export let permalinkFor: (kind: 'ohbm2026' | 'neuroscape', id: number) => string;
	export let query: string = '';

	const dispatch = createEventDispatcher<{
		select: { kind: 'ohbm2026' | 'neuroscape'; id: number };
	}>();

	let limit = 100;

	type Row =
		| { kind: 'ohbm2026'; id: number; title: string; cluster_id: number; subline: string }
		| {
				kind: 'neuroscape';
				id: number;
				title: string;
				cluster_id: number;
				subline: string;
		  };

	$: filtered = (() => {
		const needle = query.trim() ? normalize(query) : '';
		const out: Array<{ row: Row; score: number; tie: number }> = [];

		for (const o of overlayPoints) {
			if (needle) {
				const hay = normalize(o.title);
				const idx = hay.indexOf(needle);
				const pidStr = String(o.poster_id);
				const pidIdx = pidStr.indexOf(query.trim());
				if (idx === -1 && pidIdx === -1) continue;
				const score = idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
				out.push({
					row: {
						kind: 'ohbm2026',
						id: o.poster_id,
						title: o.title,
						cluster_id: o.nearest_cluster_id,
						subline: `OHBM 2026 · #${o.poster_id}`
					},
					score,
					tie: -o.poster_id
				});
			} else {
				out.push({
					row: {
						kind: 'ohbm2026',
						id: o.poster_id,
						title: o.title,
						cluster_id: o.nearest_cluster_id,
						subline: `OHBM 2026 · #${o.poster_id}`
					},
					score: -1,
					tie: o.poster_id
				});
			}
		}

		for (const a of backdropPoints) {
			if (needle) {
				const hay = normalize(a.title);
				const idx = hay.indexOf(needle);
				const pmidStr = String(a.pubmed_id);
				const pmidIdx = pmidStr.indexOf(query.trim());
				if (idx === -1 && pmidIdx === -1) continue;
				const score = idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
				out.push({
					row: {
						kind: 'neuroscape',
						id: a.pubmed_id,
						title: a.title,
						cluster_id: a.cluster_id,
						subline: `NeuroScape · PMID ${a.pubmed_id} · ${a.year}`
					},
					score,
					tie: -a.year
				});
			} else {
				out.push({
					row: {
						kind: 'neuroscape',
						id: a.pubmed_id,
						title: a.title,
						cluster_id: a.cluster_id,
						subline: `NeuroScape · PMID ${a.pubmed_id} · ${a.year}`
					},
					score: -a.year,
					tie: a.pubmed_id
				});
			}
		}

		out.sort((x, y) => x.score - y.score || x.tie - y.tie);
		return out.map((s) => s.row);
	})();

	$: visible = filtered.slice(0, limit);
	$: totalCount = filtered.length;
</script>

<section class="ar-browse" data-testid="atlas-root-browse-panel">
	<p class="ar-count" data-testid="atlas-root-result-count">
		{totalCount.toLocaleString()} {totalCount === 1 ? 'match' : 'matches'}
		{#if totalCount > limit}
			· showing first {limit}
		{/if}
	</p>

	<ul class="ar-results" data-testid="atlas-root-result-list">
		{#each visible as r (r.kind + ':' + r.id)}
			{@const cluster = clustersById.get(r.cluster_id)}
			{@const inCart =
				r.kind === 'ohbm2026'
					? $cartOhbmPosterIds.has(r.id)
					: $cartNeuroPubmedIds.has(r.id)}
			<li class="ar-row">
				<!-- Row click opens the inline detail panel (local third
				     pane). The "Full details" link beside the cart icon
				     is the explicit path to the sibling permalink page
				     when the user wants the full view. Same pattern as
				     OHBM 2026's ResultList + NeuroscapeBrowsePanel. -->
				<button
					type="button"
					class="ar-row-link"
					on:click={() => dispatch('select', { kind: r.kind, id: r.id })}
					data-testid={`atlas-root-result-row-${r.kind}`}
				>
					<div class="ar-row-head">
						<span class="ar-kind-tag" data-kind={r.kind}>
							{r.kind === 'ohbm2026' ? 'OHBM' : 'NeuroScape'}
						</span>
						<span class="ar-subline">{r.subline}</span>
						{#if cluster}
							<span class="ar-cluster">
								<span
									class="ar-cluster-swatch"
									style="background:{cluster.colour_hex}"
								></span>
								{cluster.title}
							</span>
						{/if}
					</div>
					<div class="ar-title">{r.title}</div>
				</button>
				<div class="ar-row-actions">
					<CartIconButton
						kind={r.kind}
						id={r.id}
						{inCart}
						testidPrefix="atlas-root-row-cart"
					/>
					<a
						class="ar-detail-link"
						href={permalinkFor(r.kind, r.id)}
						rel="external"
						title={`Open full detail page on /${r.kind === 'ohbm2026' ? 'ohbm2026' : 'neuroscape'}/`}
						data-testid={`atlas-root-row-detail-link-${r.kind}`}
					>
						Full details ↗
					</a>
				</div>
			</li>
		{/each}
	</ul>

	{#if totalCount > limit}
		<button
			type="button"
			class="ar-more"
			on:click={() => (limit = Math.min(limit * 2, totalCount))}
			data-testid="atlas-root-show-more"
		>
			Show more
		</button>
	{/if}
</section>

<style>
	.ar-browse {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		min-width: 0;
	}
	.ar-count {
		margin: 0;
		font-size: 0.85rem;
		color: var(--text-muted);
	}
	.ar-results {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		max-height: 70vh;
		overflow-y: auto;
	}
	.ar-row {
		display: flex;
		gap: 0.5rem;
		align-items: stretch;
		padding: 0.5rem 0.65rem;
		border-radius: 4px;
		border: 1px solid var(--border);
	}
	.ar-row:hover {
		background: var(--bg-subtle);
	}
	.ar-row-link {
		all: unset;
		cursor: pointer;
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		text-align: left;
		color: var(--text);
		min-width: 0;
	}
	.ar-row-head {
		display: flex;
		gap: 0.6rem;
		flex-wrap: wrap;
		font-size: 0.78rem;
		color: var(--text-muted);
		align-items: baseline;
	}
	.ar-kind-tag {
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-size: 0.7rem;
		padding: 0.05rem 0.35rem;
		border-radius: 3px;
		color: var(--accent-soft-text);
		background: var(--accent-soft-bg);
	}
	.ar-subline {
		font-variant-numeric: tabular-nums;
	}
	.ar-cluster {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
	}
	.ar-cluster-swatch {
		display: inline-block;
		width: 0.65rem;
		height: 0.65rem;
		border-radius: 2px;
		border: 1px solid var(--border);
	}
	.ar-title {
		font-size: 0.92rem;
		line-height: 1.35;
		color: var(--text);
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.ar-row-actions {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		align-items: flex-end;
		flex-shrink: 0;
	}
	.ar-detail-link {
		font-size: 0.72rem;
		color: var(--text-muted);
		text-decoration: none;
		white-space: nowrap;
		padding: 0.2rem 0.4rem;
		border-radius: 3px;
	}
	.ar-detail-link:hover {
		color: var(--accent);
		background: var(--accent-soft-bg);
	}
	.ar-more {
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
	.ar-more:hover {
		filter: brightness(1.05);
	}
</style>
