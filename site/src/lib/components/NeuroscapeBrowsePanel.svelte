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
	import { searchTitleIndex, type InvertedIndex } from '$lib/filter';
	import { parseIdOperator } from '$lib/goto_poster';
	import { cartStore, cartNeuroPubmedIds } from '$lib/stores/cart';
	import CartIconButton from '$lib/components/CartIconButton.svelte';
	import InlineLoader from '$lib/components/InlineLoader.svelte';

	type Article = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
		// Spec 015: KNN graph attached per article by loader.ts.
		nearest_pubmed_ids?: number[];
		nearest_distances?: number[];
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
	/** True while the full corpus is still streaming in — shows an inline
	 *  "loading" indicator next to the count (uniform with atlas-root). */
	export let loading: boolean = false;
	/** Spec 019 / FR-002 — when set + non-empty, the panel renders
	 *  these as additional `✨ Semantic` rows below the lexical hits.
	 *  Each entry maps a pubmed_id to its KNN distance from the
	 *  closest lexical seed (lower = better; surfaced as `d=N.NNN` on
	 *  the badge). Computed by the parent (+page.svelte) by walking
	 *  the per-article `nearest_pubmed_ids` graph from the current
	 *  lexical hit set. */
	export let semanticHits: Map<number, number> = new Map();
	/** Spec 019 perf — inverted title index over the FULL backdrop corpus,
	 *  built once by the parent (+page.svelte) and cached by array identity.
	 *  The per-query filter runs the shared OHBM operator/typo-tolerant search
	 *  against it (vocabulary lookup) rather than scanning ~461k titles on
	 *  every keystroke. Required for search; when null the panel renders the
	 *  unfiltered list. */
	export let searchIndex: InvertedIndex | null = null;

	/** Spec 021 (US2) — the set of pubmed_ids matching the active query,
	 *  exposed (two-way bound by the parent) so the scatter can highlight the
	 *  search results. Empty when no query is active (no highlight). Single
	 *  source of truth: derived from the same `filtered` the list renders. */
	export let matchedIds: Set<number> = new Set();

	const dispatch = createEventDispatcher<{
		focus: { pubmed_id: number; cluster_id: number };
	}>();

	let limit = 100;

	// Spec 019 / FR-025 — operator-aware lexical filter that mirrors the
	// OHBM 2026 SearchBar syntax (implicit-AND multi-word, "exact phrase",
	// -foo / -"phrase" exclusion, word OR word, id:N exact lookup). Matching
	// runs through the shared `searchTitleIndex` against the full-corpus
	// inverted index built once by the parent — identical typo-tolerance to
	// /ohbm2026/'s `lexicalSearch`, and fast (vocabulary lookup instead of a
	// per-keystroke Damerau-Levenshtein scan over all ~461k titles).
	$: articleById = new Map(articles.map((a) => [a.pubmed_id, a]));
	$: filtered = (() => {
		const trimmed = (query ?? '').trim();
		if (!trimmed) {
			return [...articles].sort((a, b) => b.year - a.year || a.pubmed_id - b.pubmed_id);
		}
		// id:N short-circuit — return the single matching article (or none)
		// by pubmed_id; ignores the rest of the query per Stage 14's
		// id-operator semantics on /ohbm2026/.
		const idPayload = parseIdOperator(trimmed);
		if (idPayload !== null) {
			const numeric = Number(idPayload);
			if (!Number.isFinite(numeric)) return [];
			return articles.filter((a) => a.pubmed_id === numeric);
		}
		const res = searchIndex ? searchTitleIndex(searchIndex, trimmed) : null;
		// res.ids span the FULL corpus; narrow to the facet-filtered set
		// (`articleById`) and rank by exact-token count desc (consistent with
		// /ohbm2026/'s exactness ranking), then year desc. A zero-row lexical
		// result must NOT short-circuit here: an exact-phrase query like
		// "corpus callosum disorders" has no adjacent-token title yet still
		// has valid KNN-expanded semantic hits, so fall through to the
		// semantic augmentation below with an empty lexical set.
		const scored: Array<{ a: Article; exact: number }> = [];
		if (res) {
			for (const id of res.ids) {
				const a = articleById.get(id);
				if (!a) continue;
				scored.push({ a, exact: res.exactness.get(id) ?? 0 });
			}
			scored.sort(
				(x, y) => y.exact - x.exact || y.a.year - x.a.year || x.a.pubmed_id - y.a.pubmed_id
			);
		}
		const lexicalHits = scored.map((s) => s.a);
		if (lexicalHits.length === 0 && semanticHits.size === 0) return [];
		// Spec 019 / FR-002 — augment with KNN-expanded semantic candidates.
		// semanticHits maps pubmed_id → KNN distance from the nearest lexical
		// seed; append the ones NOT already in the lexical set (they get the
		// ✨ badge in the row template), in graph-distance order.
		if (semanticHits.size === 0) return lexicalHits;
		const lexicalSet = new Set(lexicalHits.map((a) => a.pubmed_id));
		const semanticRows: Array<{ a: Article; d: number }> = [];
		for (const [pmid, d] of semanticHits) {
			if (lexicalSet.has(pmid)) continue;
			const a = articleById.get(pmid);
			if (!a) continue;
			semanticRows.push({ a, d });
		}
		semanticRows.sort((x, y) => x.d - y.d);
		return [...lexicalHits, ...semanticRows.map((s) => s.a)];
	})();
	// Lookup for the row template to know which rows are semantic-only
	// + what distance to show on the badge.
	$: semanticHitMap = semanticHits;

	// Spec 021 (US2) — expose the matched pubmed_ids for scatter highlighting,
	// but only when a query is active (an empty query = no selection, so the
	// scatter shows no highlight rather than "everything selected").
	$: matchedIds = (query ?? '').trim()
		? new Set(filtered.map((a) => a.pubmed_id))
		: new Set<number>();

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
			{#if loading}<InlineLoader />{/if}
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
					data-pubmed-id={a.pubmed_id}
				>
					<div class="ns-row-head">
						<span class="ns-pmid">PMID {a.pubmed_id}</span>
						<span class="ns-year">{a.year}</span>
						{#if semanticHitMap.has(a.pubmed_id)}
							{@const d = semanticHitMap.get(a.pubmed_id) ?? 0}
							<span
								class="ns-semantic-badge"
								title={`Semantic-only hit — KNN distance ${d.toFixed(3)} from nearest lexical match`}
								data-testid="semantic-only-badge"
							>✨ d={d.toFixed(3)}</span>
						{/if}
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
	.ns-semantic-badge {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
		padding: 0.1rem 0.4rem;
		font-size: 0.72rem;
		font-variant-numeric: tabular-nums;
		border-radius: 9999px;
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text);
		border: 1px solid var(--accent);
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
