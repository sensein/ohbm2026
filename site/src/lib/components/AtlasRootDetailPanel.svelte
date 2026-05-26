<!--
  Stage 15 (spec 015-neuroscape-context, T046):
  Slide-in detail panel used only when SITE_MODE === 'atlas-root'.

  Renders a compact card per `contracts/atlas-root-ui.md`:
    - For ohbm2026 points: title, poster id, nearest cluster, CTA
      "Open on /ohbm2026/ →"
    - For neuroscape points: title, year, cluster info, CTA
      "Open on /neuroscape/ →"

  The atlas.parquet does NOT carry authors, abstract bodies, DOIs, or
  any other field the visitor would expect on a detail page — those
  live on the sibling subsites and the CTA carries the visitor there.

  Deliberately a NEW component, not an extension of the existing
  1740-line DetailPanel.svelte. Reasons:
    - FR-022 / SC-008 byte-identity: the ohbm2026 build must not have
      its DetailPanel's compiled output drift, even if the new branch
      is dead-code eliminated by VITE_SITE_MODE.
    - The data shape (compact card with no body) is unrelated to the
      existing DetailPanel's much larger surface.
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { onMount, onDestroy } from 'svelte';
	import { cartOhbmPosterIds, cartNeuroPubmedIds } from '$lib/stores/cart';
	import CartIconButton from '$lib/components/CartIconButton.svelte';

	type ClusterRow = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};

	type OhbmSelection = {
		kind: 'ohbm2026';
		title: string;
		poster_id: number;
		nearest_cluster_id: number;
		permalink: string; // already-prefixed deploy URL
	};

	type NeuroscapeSelection = {
		kind: 'neuroscape';
		title: string;
		pubmed_id: number;
		year: number;
		cluster_id: number;
		permalink: string; // already-prefixed deploy URL
	};

	export let selection: OhbmSelection | NeuroscapeSelection | null = null;
	export let clustersById: Map<number, ClusterRow> = new Map();
	/** Rendering mode.
	 *  - `'modal'` (default) — fixed-position slide-in with backdrop;
	 *    Escape + backdrop click close.
	 *  - `'inline'` — render the card content only, no backdrop, no
	 *    fixed positioning. Hosted by the OHBM-style `.detail-pane`
	 *    grid column. Caller controls close via clicking elsewhere or
	 *    a deselect action.
	 */
	export let mode: 'modal' | 'inline' = 'modal';
	/** Optional "Most similar" list. Each entry is one pre-computed
	 *  nearest neighbour (cosine-distance kNN in the Stage-2 embedding
	 *  space, baked into neuroscape.parquet's `neighbors_neuroscape`
	 *  row group at build time). The parent decides whether to load +
	 *  pass them — atlas-root currently leaves it empty because
	 *  atlas.parquet doesn't carry neighbours (cross-conference points
	 *  reach the full detail page via the CTA); the /neuroscape/
	 *  subsite passes the top ~10 entries.
	 */
	export let neighbours: Array<{
		id: number;
		title: string;
		href: string;
	}> = [];

	const dispatch = createEventDispatcher<{ close: void }>();

	function close() {
		dispatch('close');
	}

	function onBackdropClick(e: MouseEvent) {
		// Click on the dimmed overlay (not the panel itself) closes.
		if (e.target === e.currentTarget) close();
	}

	function onKeyDown(e: KeyboardEvent) {
		if (e.key === 'Escape') close();
	}

	// Pointer-capture the Escape key while a selection is open so it
	// closes the panel rather than dropping the lasso / triggering a
	// browser-default elsewhere.
	let bound = false;
	onMount(() => {
		if (typeof window !== 'undefined') {
			window.addEventListener('keydown', onKeyDown);
			bound = true;
		}
	});
	onDestroy(() => {
		if (bound && typeof window !== 'undefined') {
			window.removeEventListener('keydown', onKeyDown);
		}
	});

	$: cluster = selection ? clustersById.get(
		selection.kind === 'ohbm2026' ? selection.nearest_cluster_id : selection.cluster_id
	) : undefined;
	$: ctaLabel = selection?.kind === 'ohbm2026'
		? 'Open on /ohbm2026/'
		: selection?.kind === 'neuroscape'
		? 'Open on /neuroscape/'
		: '';
	$: inCart =
		selection?.kind === 'ohbm2026'
			? $cartOhbmPosterIds.has(selection.poster_id)
			: selection?.kind === 'neuroscape'
				? $cartNeuroPubmedIds.has(selection.pubmed_id)
				: false;
	$: cartItemId = selection
		? selection.kind === 'ohbm2026'
			? selection.poster_id
			: selection.pubmed_id
		: 0;
</script>

{#if selection}
	{#if mode === 'modal'}
		<!-- Modal: dim backdrop + fixed-position slide-in card. -->
		<div
			class="atlas-detail-backdrop"
			data-testid="atlas-root-detail-panel"
			role="dialog"
			aria-modal="true"
			aria-label="Point detail"
			on:click={onBackdropClick}
			on:keydown={onKeyDown}
			tabindex="-1"
		>
			<aside
				class="atlas-detail-card atlas-detail-card--modal"
				data-testid="atlas-root-detail-card"
				data-kind={selection.kind}
			>
				<header class="card-head">
					<span class="kind-tag" data-testid="atlas-root-kind-tag">
						{selection.kind === 'ohbm2026' ? 'OHBM 2026' : 'NeuroScape PubMed'}
					</span>
					<div class="head-actions">
						{#if selection && cartItemId}
							<CartIconButton
								kind={selection.kind}
								id={cartItemId}
								{inCart}
								testidPrefix="atlas-root-detail-cart"
							/>
						{/if}
						<button
							type="button"
							class="close"
							on:click={close}
							aria-label="Close detail panel"
							data-testid="atlas-root-detail-close"
						>
							×
						</button>
					</div>
				</header>
				<h2 class="title" data-testid="atlas-root-detail-title">{selection.title}</h2>
				<dl class="meta">
					{#if selection.kind === 'ohbm2026'}
						<div class="meta-row">
							<dt>Poster id</dt>
							<dd data-testid="atlas-root-detail-poster-id">{selection.poster_id}</dd>
						</div>
					{:else}
						<div class="meta-row">
							<dt>PubMed id</dt>
							<dd data-testid="atlas-root-detail-pubmed-id">{selection.pubmed_id}</dd>
						</div>
						<div class="meta-row">
							<dt>Year</dt>
							<dd data-testid="atlas-root-detail-year">{selection.year}</dd>
						</div>
					{/if}
					{#if cluster}
						<div class="meta-row">
							<dt>{selection.kind === 'ohbm2026' ? 'Nearest cluster' : 'Cluster'}</dt>
							<dd data-testid="atlas-root-detail-cluster">
								<span class="cluster-swatch" style="background:{cluster.colour_hex}"></span>
								{cluster.title}
							</dd>
						</div>
					{/if}
				</dl>
				{#if neighbours.length > 0}
					<section class="neighbours" data-testid="atlas-root-detail-neighbours">
						<h3>Most similar</h3>
						<ol>
							{#each neighbours as n (n.id)}
								<li>
									<a
										href={n.href}
										data-testid="atlas-root-detail-neighbour-link"
									>
										<span class="nid">{n.id}</span>
										<span class="ntitle">{n.title}</span>
									</a>
								</li>
							{/each}
						</ol>
					</section>
				{/if}
				<a
					class="cta"
					href={selection.permalink}
					rel="external"
					data-testid="atlas-root-detail-cta"
				>
					{ctaLabel} <span aria-hidden="true">→</span>
				</a>
			</aside>
		</div>
	{:else}
		<!-- Inline: hosted by the parent's `.detail-pane` grid column.
		     Header mirrors OHBM 2026 DetailPanel's inline pattern —
		     cart + "Full details ↗" + close — instead of a big CTA
		     button below. -->
		<aside
			class="atlas-detail-card atlas-detail-card--inline"
			data-testid="atlas-root-detail-card"
			data-kind={selection.kind}
		>
			<header class="card-head">
				<span class="kind-tag" data-testid="atlas-root-kind-tag">
					{selection.kind === 'ohbm2026' ? 'OHBM 2026' : 'NeuroScape PubMed'}
				</span>
				<div class="head-actions">
					{#if selection && cartItemId}
						<CartIconButton
							kind={selection.kind}
							id={cartItemId}
							{inCart}
							testidPrefix="atlas-root-detail-cart"
						/>
					{/if}
					<a
						class="permalink-link"
						href={selection.permalink}
						rel="external"
						title="Open the full-detail page"
						data-testid="atlas-root-detail-permalink"
					>
						Full details ↗
					</a>
					<button
						type="button"
						class="close"
						on:click={close}
						aria-label="Close detail panel"
						data-testid="atlas-root-detail-close"
					>
						×
					</button>
				</div>
			</header>
			<h2 class="title" data-testid="atlas-root-detail-title">{selection.title}</h2>
			<dl class="meta">
				{#if selection.kind === 'ohbm2026'}
					<div class="meta-row">
						<dt>Poster id</dt>
						<dd data-testid="atlas-root-detail-poster-id">{selection.poster_id}</dd>
					</div>
				{:else}
					<div class="meta-row">
						<dt>PubMed id</dt>
						<dd data-testid="atlas-root-detail-pubmed-id">{selection.pubmed_id}</dd>
					</div>
					<div class="meta-row">
						<dt>Year</dt>
						<dd data-testid="atlas-root-detail-year">{selection.year}</dd>
					</div>
				{/if}
				{#if cluster}
					<div class="meta-row">
						<dt>{selection.kind === 'ohbm2026' ? 'Nearest cluster' : 'Cluster'}</dt>
						<dd data-testid="atlas-root-detail-cluster">
							<span class="cluster-swatch" style="background:{cluster.colour_hex}"></span>
							{cluster.title}
						</dd>
					</div>
				{/if}
			</dl>
			{#if neighbours.length > 0}
				<section class="neighbours" data-testid="atlas-root-detail-neighbours">
					<h3>Most similar</h3>
					<ol>
						{#each neighbours as n (n.id)}
							<li>
								<a
									href={n.href}
									data-testid="atlas-root-detail-neighbour-link"
								>
									<span class="nid">{n.id}</span>
									<span class="ntitle">{n.title}</span>
								</a>
							</li>
						{/each}
					</ol>
				</section>
			{/if}
		</aside>
	{/if}
{/if}

<style>
	.atlas-detail-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.25);
		display: flex;
		justify-content: flex-end;
		z-index: 100;
	}
	.atlas-detail-card {
		background: var(--bg-elevated);
		color: var(--text);
		padding: 1rem 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		overflow-y: auto;
	}
	.atlas-detail-card--modal {
		/* Slide-in panel hugging the right edge inside the backdrop. */
		width: min(420px, 100%);
		border-left: 1px solid var(--border);
		box-shadow: -2px 0 8px rgba(0, 0, 0, 0.08);
	}
	.atlas-detail-card--inline {
		/* Hosted by the parent's `.detail-pane` grid column. */
		width: 100%;
		min-width: 0;
		box-sizing: border-box;
		border: 1px solid var(--border);
		border-radius: 6px;
		max-height: 80vh;
	}
	/* On narrow viewports the 7rem label column eats most of the
	   row — collapse meta rows to a stacked label-above-value
	   layout so values get full width. */
	@media (max-width: 480px) {
		.meta-row {
			grid-template-columns: minmax(0, 1fr);
			gap: 0.1rem;
		}
		.atlas-detail-card {
			padding: 0.85rem 0.9rem;
		}
	}
	.card-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.kind-tag {
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		padding: 0.15rem 0.5rem;
		border-radius: 3px;
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text);
	}
	.head-actions {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	.close {
		all: unset;
		cursor: pointer;
		font-size: 1.4rem;
		line-height: 1;
		color: var(--text-muted);
		padding: 0.2rem 0.4rem;
		border-radius: 4px;
	}
	.close:hover {
		background: var(--bg-subtle);
		color: var(--text);
	}
	.title {
		margin: 0;
		font-size: 1.05rem;
		font-weight: 600;
		line-height: 1.35;
		/* Long titles must break instead of pushing the panel wider
		   than its parent grid cell. */
		min-width: 0;
		word-break: break-word;
		overflow-wrap: anywhere;
	}
	.meta {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		min-width: 0;
	}
	.meta-row {
		display: grid;
		grid-template-columns: 7rem minmax(0, 1fr);
		gap: 0.5rem;
		align-items: baseline;
	}
	.meta dt {
		color: var(--text-muted);
		font-size: 0.85rem;
		margin: 0;
	}
	.meta dd {
		color: var(--text);
		font-size: 0.92rem;
		margin: 0;
		min-width: 0;
		word-break: break-word;
		overflow-wrap: anywhere;
	}
	.cluster-swatch {
		display: inline-block;
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 2px;
		margin-right: 0.4rem;
		vertical-align: middle;
		border: 1px solid var(--border);
	}
	/* Compact "Full details ↗" link in the head-actions row, sitting
	   between the cart icon and the close button. Same visual weight
	   as OHBM's inline DetailPanel's `.permalink permalink-top` link. */
	.permalink-link {
		font-size: 0.78rem;
		color: var(--text-muted);
		text-decoration: none;
		padding: 0.25rem 0.45rem;
		border-radius: 3px;
		white-space: nowrap;
	}
	.permalink-link:hover {
		color: var(--accent);
		background: var(--accent-soft-bg);
	}
	/* `.cta` was the big primary "Open on /<sibling>/" button at the
	   bottom of the inline card — replaced by the compact
	   permalink-link in the head-actions row (matches OHBM 2026's
	   inline detail card pattern). The modal layout still uses it. */
	.cta {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		justify-content: center;
		padding: 0.55rem 0.85rem;
		border-radius: 4px;
		background: var(--accent);
		color: var(--accent-text);
		text-decoration: none;
		font-weight: 500;
		font-size: 0.95rem;
		margin-top: 0.25rem;
	}
	.cta:hover {
		filter: brightness(1.05);
	}
	.neighbours h3 {
		margin: 0 0 0.4rem;
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.neighbours ol {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.neighbours li a {
		display: flex;
		gap: 0.5rem;
		align-items: baseline;
		padding: 0.3rem 0.4rem;
		border-radius: 4px;
		text-decoration: none;
		color: var(--text);
		font-size: 0.85rem;
		line-height: 1.3;
	}
	.neighbours li a:hover {
		background: var(--bg-sunken);
		color: var(--accent);
	}
	.neighbours .nid {
		flex-shrink: 0;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.72rem;
		color: var(--text-faint);
	}
	.neighbours .ntitle {
		flex: 1;
		word-break: break-word;
	}
</style>
