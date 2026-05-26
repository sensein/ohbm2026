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
	import { cartStore, cartNeuroPubmedIds } from '$lib/stores/cart';
	import CartIconButton from '$lib/components/CartIconButton.svelte';

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

	// Bulk-add over the FULL filtered set (every article matching
	// the current facets + search + lasso), not just the paginated
	// `visible` slice — OHBM 2026 ResultList does the same. "Add
	// N to cart" reflects the size of the user's actual selection.
	//
	// Sanity-cap at 5,000 items — localStorage caps at ~5 MB
	// per origin, each typed cart item serialises to ~25 bytes JSON,
	// so > ~200k items breaks `JSON.stringify(...)` → setItem(). The
	// cart drawer also stops being useful well before then (you
	// can't email or read a 1,000-item list). Above the warn
	// threshold (200) the user gets a confirm() so accidental
	// "add the whole 461k corpus" clicks don't silently nuke their
	// cart.
	const CART_BULK_WARN_AT = 200;
	const CART_BULK_HARD_CAP = 5000;
	$: filteredNotInCart = filtered
		.map((a) => a.pubmed_id)
		.filter((id) => !$cartNeuroPubmedIds.has(id));
	function addAllVisible() {
		const n = filteredNotInCart.length;
		if (n === 0) return;
		let toAdd = filteredNotInCart;
		if (n > CART_BULK_HARD_CAP) {
			const ok =
				typeof window !== 'undefined' &&
				window.confirm(
					`This selection has ${n.toLocaleString()} articles.\n\n` +
						`The cart can hold up to ${CART_BULK_HARD_CAP.toLocaleString()} items before browser storage fills up.\n\n` +
						`Add the first ${CART_BULK_HARD_CAP.toLocaleString()} (sorted by year, newest first)?`
				);
			if (!ok) return;
			toAdd = filteredNotInCart.slice(0, CART_BULK_HARD_CAP);
		} else if (n > CART_BULK_WARN_AT) {
			const ok =
				typeof window !== 'undefined' &&
				window.confirm(
					`Add ${n.toLocaleString()} articles to your cart? ` +
						`Large carts can be slow to email or display.`
				);
			if (!ok) return;
		}
		cartStore.addManyItems(
			toAdd.map((id) => ({ kind: 'neuroscape' as const, id }))
		);
	}
</script>

<section class="ns-browse" data-testid="neuroscape-browse-panel">
	<header class="ns-list-head">
		<p class="ns-count" data-testid="neuroscape-result-count">
			{filtered.length.toLocaleString()} {filtered.length === 1 ? 'match' : 'matches'}
			{#if filtered.length > limit}
				· showing first {limit}
			{/if}
		</p>
		{#if filteredNotInCart.length > 0}
			<button
				type="button"
				class="ns-bulk-cart-add"
				on:click={addAllVisible}
				title={`Add the ${filteredNotInCart.length} article${filteredNotInCart.length === 1 ? '' : 's'} not yet in your cart`}
				data-testid="neuroscape-bulk-cart-add"
			>
				+ Add {filteredNotInCart.length} to cart
			</button>
		{/if}
	</header>

	<ul class="ns-results" data-testid="neuroscape-result-list">
		{#each visible as a (a.pubmed_id)}
			{@const cluster = clustersById.get(a.cluster_id)}
			{@const inCart = $cartNeuroPubmedIds.has(a.pubmed_id)}
			<li class="ns-row">
				<!-- Click opens the inline detail panel (third column) to
				     match the OHBM home: the row is a <button>, not a
				     <a href>. The "Full details" link inside the detail
				     panel is the path to the dedicated permalink page. -->
				<button
					type="button"
					class="ns-row-link"
					on:click={() => onShowOnAtlas(a)}
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
				</button>
				<div class="ns-row-actions">
					<!-- Same cart-icon UX as OHBM 2026 ResultList: outlined
					     cart → filled-with-✓ when in the unifying list.
					     "Full details" link removed from the row; the
					     inline detail panel's CTA is the canonical path
					     to the dedicated permalink page. -->
					<CartIconButton
						kind="neuroscape"
						id={a.pubmed_id}
						{inCart}
						testidPrefix="neuroscape-row-cart"
					/>
				</div>
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
		min-width: 0;
		box-sizing: border-box;
	}
	.ns-browse,
	.ns-results {
		min-width: 0;
		box-sizing: border-box;
	}
	.ns-list-head {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.ns-list-head .ns-count {
		flex: 1;
	}
	.ns-bulk-cart-add {
		all: unset;
		cursor: pointer;
		padding: 0.3rem 0.6rem;
		font-size: 0.78rem;
		color: var(--accent);
		border: 1px solid var(--accent);
		background: transparent;
		border-radius: 4px;
		white-space: nowrap;
	}
	.ns-bulk-cart-add:hover {
		background: var(--accent-soft-bg);
	}
	.ns-row:hover {
		background: var(--bg-subtle);
	}
	.ns-row-link {
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
	.ns-row-actions {
		display: flex;
		align-items: center;
		flex-shrink: 0;
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
