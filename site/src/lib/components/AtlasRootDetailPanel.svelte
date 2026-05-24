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
</script>

{#if selection}
	<!-- The outer is the dim backdrop; the inner card is the panel. -->
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
		<aside class="atlas-detail-card" data-testid="atlas-root-detail-card" data-kind={selection.kind}>
			<header class="card-head">
				<span class="kind-tag" data-testid="atlas-root-kind-tag">
					{selection.kind === 'ohbm2026' ? 'OHBM 2026' : 'NeuroScape PubMed'}
				</span>
				<button
					type="button"
					class="close"
					on:click={close}
					aria-label="Close detail panel"
					data-testid="atlas-root-detail-close"
				>
					×
				</button>
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
		width: min(420px, 100%);
		background: var(--bg-elevated);
		color: var(--text);
		border-left: 1px solid var(--border);
		padding: 1rem 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		box-shadow: -2px 0 8px rgba(0, 0, 0, 0.08);
		overflow-y: auto;
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
	}
	.meta {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.meta-row {
		display: grid;
		grid-template-columns: 7rem 1fr;
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
</style>
