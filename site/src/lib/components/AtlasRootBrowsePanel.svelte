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
	import { buildTitleIndex, searchTitleIndex, type InvertedIndex } from '$lib/filter';
	import { cartStore, cartOhbmPosterIds, cartNeuroPubmedIds } from '$lib/stores/cart';
	import CartIconButton from '$lib/components/CartIconButton.svelte';
	import InlineLoader from '$lib/components/InlineLoader.svelte';

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
	/** True while the full corpus is still streaming in — shows an inline
	 *  "loading" indicator next to the count so the count growing (seed → full
	 *  ~461k) reads as progress, not a glitch. */
	export let loading: boolean = false;
	/** Spec 019 / FR-002 — KNN-expanded semantic hits for the
	 *  NeuroScape lane (computed in +page.svelte by walking the per-
	 *  article nearest_pubmed_ids graph from the lexical seed set).
	 *  Map<pubmed_id, knn_distance>. OHBM side has no semantic hits
	 *  yet — that lane requires the production atlas.parquet to gain
	 *  the ohbm_vectors table, which is a separate spec-019 build
	 *  step still pending deploy. */
	export let semanticHits: Map<number, number> = new Map();
	/** Spec 019 perf — inverted title index over the FULL NeuroScape backdrop
	 *  corpus, built once by the parent (+page.svelte) and cached by array
	 *  identity. The per-query backdrop filter runs the shared OHBM
	 *  operator/typo-tolerant search against it (vocabulary lookup) instead of
	 *  scanning ~461k titles on every keystroke. The (small) OHBM overlay gets
	 *  its own locally-built index. When null, search is disabled (the panel
	 *  shows the unfiltered combined list). */
	export let searchIndex: InvertedIndex | null = null;

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
				// Set only on semantic-only (KNN-expanded) rows: the distance
				// from the nearest lexical match (lower = better). Drives the
				// ✨ d= badge, matching /ohbm2026/ ResultList + NeuroscapeBrowsePanel.
				d?: number;
		  };

	// Spec 019 / FR-025 / FR-026 — operator-aware cross-conference filter.
	// Both corpora run through the shared `searchTitleIndex` (same operators,
	// same Damerau-Levenshtein typo ladder as /ohbm2026/'s `lexicalSearch`),
	// so matching is identical across overlay + backdrop + the sibling sites.
	//   - implicit-AND multi-word over titles in BOTH corpora
	//   - "exact phrase" + -negation + word OR word work across both
	//   - id:N matches `poster_id` (OHBM) OR `pubmed_id` (NeuroScape)
	// The backdrop uses the parent's full-corpus index (post-filtered to the
	// facet-narrowed set); the small overlay gets a locally-built index.
	$: overlaySearchIndex = buildTitleIndex(
		overlayPoints,
		(o) => o.poster_id,
		(o) => o.title
	);
	$: backdropById = new Map(backdropPoints.map((b) => [b.pubmed_id, b]));
	$: overlayById = new Map(overlayPoints.map((o) => [o.poster_id, o]));
	$: filtered = (() => {
		const trimmed = (query ?? '').trim();
		const out: Array<{ row: Row; score: number; tie: number }> = [];

		// id:N short-circuit (FR-026) — match across BOTH corpora in parallel.
		// The id: prefix is parsed from the raw query; if present, return
		// every overlay/backdrop row whose id matches.
		const idMatch = trimmed.match(/^id:(\d+)$/i);
		if (idMatch) {
			const wanted = Number(idMatch[1]);
			for (const o of overlayPoints) {
				if (o.poster_id === wanted) {
					out.push({
						row: {
							kind: 'ohbm2026',
							id: o.poster_id,
							title: o.title,
							cluster_id: o.nearest_cluster_id,
							subline: `OHBM 2026 · #${o.poster_id}`
						},
						score: 0,
						tie: 0
					});
				}
			}
			for (const a of backdropPoints) {
				if (a.pubmed_id === wanted) {
					out.push({
						row: {
							kind: 'neuroscape',
							id: a.pubmed_id,
							title: a.title,
							cluster_id: a.cluster_id,
							subline: `NeuroScape · PMID ${a.pubmed_id} · ${a.year}`
						},
						score: 0,
						tie: 1
					});
				}
			}
			out.sort((x, y) => x.tie - y.tie);
			return out.map((s) => s.row);
		}

		if (!trimmed) {
			// Empty query — build every row (everything "matches").
			for (const o of overlayPoints) {
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
			for (const a of backdropPoints) {
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
		} else {
			// Operator/typo-tolerant search via the shared index. Negative
			// exactness sorts the higher-exact-count rows first; the kind tie
			// preserves OHBM-before-NeuroScape ordering at equal exactness.
			const overlayRes = searchTitleIndex(overlaySearchIndex, trimmed);
			if (overlayRes) {
				for (const id of overlayRes.ids) {
					const o = overlayById.get(id);
					if (!o) continue;
					out.push({
						row: {
							kind: 'ohbm2026',
							id: o.poster_id,
							title: o.title,
							cluster_id: o.nearest_cluster_id,
							subline: `OHBM 2026 · #${o.poster_id}`
						},
						score: -(overlayRes.exactness.get(id) ?? 0),
						tie: -o.poster_id
					});
				}
			}
			const backdropRes = searchIndex ? searchTitleIndex(searchIndex, trimmed) : null;
			if (backdropRes) {
				for (const id of backdropRes.ids) {
					const a = backdropById.get(id);
					if (!a) continue;
					out.push({
						row: {
							kind: 'neuroscape',
							id: a.pubmed_id,
							title: a.title,
							cluster_id: a.cluster_id,
							subline: `NeuroScape · PMID ${a.pubmed_id} · ${a.year}`
						},
						score: -(backdropRes.exactness.get(id) ?? 0),
						tie: -a.year
					});
				}
			}
		}

		out.sort((x, y) => x.score - y.score || x.tie - y.tie);
		const lexicalRows = out.map((s) => s.row);
		// Spec 019 / FR-002 — augment with NeuroScape-side semantic-only
		// rows (KNN-expansion). OHBM-side semantic awaits the production
		// ohbm_vectors table; for now atlas-root semantic hits are the
		// NeuroScape lane only — same mechanism as NeuroscapeBrowsePanel.
		if (semanticHits.size === 0) return lexicalRows;
		const lexicalIds = new Set(lexicalRows.map((r) => `${r.kind}:${r.id}`));
		const semanticRows: Array<{ row: Row; d: number }> = [];
		for (const [pmid, d] of semanticHits) {
			const key = `neuroscape:${pmid}`;
			if (lexicalIds.has(key)) continue;
			const a = backdropById.get(pmid);
			if (!a) continue;
			semanticRows.push({
				row: {
					kind: 'neuroscape',
					id: a.pubmed_id,
					title: a.title,
					cluster_id: a.cluster_id,
					subline: `NeuroScape · PMID ${a.pubmed_id} · ${a.year}`,
					d
				},
				d
			});
		}
		semanticRows.sort((x, y) => x.d - y.d);
		return [...lexicalRows, ...semanticRows.map((s) => s.row)];
	})();
	$: semanticHitMap = semanticHits;

	$: visible = filtered.slice(0, limit);
	$: totalCount = filtered.length;

	// Bulk-add over the FULL filtered set (mixed kinds), not just
	// the paginated `visible` slice — matches OHBM 2026 ResultList
	// + NeuroscapeBrowsePanel.
	//
	// Sanity-cap + confirmation: localStorage tops out at ~5 MB
	// (~200k typed cart items), and even well below that the cart
	// drawer + email exports become unwieldy. CART_BULK_WARN_AT
	// triggers a confirm() so accidental "add the entire 464k
	// corpus" clicks don't silently overflow the cart.
	const CART_BULK_WARN_AT = 200;
	const CART_BULK_HARD_CAP = 5000;
	$: filteredNotInCart = filtered.filter((r) =>
		r.kind === 'ohbm2026'
			? !$cartOhbmPosterIds.has(r.id)
			: !$cartNeuroPubmedIds.has(r.id)
	);
	function addAllVisible() {
		const n = filteredNotInCart.length;
		if (n === 0) return;
		let toAdd = filteredNotInCart;
		if (n > CART_BULK_HARD_CAP) {
			const ok =
				typeof window !== 'undefined' &&
				window.confirm(
					`This selection has ${n.toLocaleString()} rows.\n\n` +
						`The cart can hold up to ${CART_BULK_HARD_CAP.toLocaleString()} items before browser storage fills up.\n\n` +
						`Add the first ${CART_BULK_HARD_CAP.toLocaleString()}?`
				);
			if (!ok) return;
			toAdd = filteredNotInCart.slice(0, CART_BULK_HARD_CAP);
		} else if (n > CART_BULK_WARN_AT) {
			const ok =
				typeof window !== 'undefined' &&
				window.confirm(
					`Add ${n.toLocaleString()} rows to your cart? ` +
						`Large carts can be slow to email or display.`
				);
			if (!ok) return;
		}
		cartStore.addManyItems(toAdd.map((r) => ({ kind: r.kind, id: r.id })));
	}
</script>

<section class="ar-browse" data-testid="atlas-root-browse-panel">
	<header class="ar-list-head">
		<p class="ar-count" data-testid="atlas-root-result-count">
			{totalCount.toLocaleString()} {totalCount === 1 ? 'match' : 'matches'}
			{#if totalCount > limit}
				· showing first {limit}
			{/if}
			{#if loading}<InlineLoader />{/if}
		</p>
		{#if filteredNotInCart.length > 0}
			<button
				type="button"
				class="ar-bulk-cart-add"
				on:click={addAllVisible}
				title={`Add the ${filteredNotInCart.length} row${filteredNotInCart.length === 1 ? '' : 's'} not yet in your cart`}
				data-testid="atlas-root-bulk-cart-add"
			>
				+ Add {filteredNotInCart.length} to cart
			</button>
		{/if}
	</header>

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
						{#if r.kind === 'neuroscape' && r.d !== undefined}
							<span
								class="ar-semantic-badge"
								title={`Semantic-only hit — distance ${r.d.toFixed(3)} from nearest lexical match`}
								data-testid="semantic-only-badge"
							>✨ d={r.d.toFixed(3)}</span>
						{/if}
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
		min-width: 0;
		box-sizing: border-box;
	}
	.ar-browse,
	.ar-results {
		min-width: 0;
		box-sizing: border-box;
	}
	.ar-list-head {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.ar-list-head .ar-count {
		flex: 1;
	}
	.ar-bulk-cart-add {
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
	.ar-bulk-cart-add:hover {
		background: var(--accent-soft-bg);
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
	.ar-semantic-badge {
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
