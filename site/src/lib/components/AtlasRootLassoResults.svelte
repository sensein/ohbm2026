<!--
  Stage 15 (spec 015-neuroscape-context, T047):
  Grouped lasso result list for the atlas-root landing page.

  When the visitor lassos points on the scatter, AtlasUmapPanel
  dispatches `lassoselect` with the selected ids grouped by kind
  (`ohbm2026_ids` + `neuroscape_ids`). This component renders the
  modal panel per `contracts/atlas-root-ui.md`:

    - Two collapsible sections — "OHBM 2026 ({n})" and
      "NeuroScape PubMed ({n})"
    - Each row links to the right subsite via the cross_pointers
      permalink for that id (poster_id → /ohbm2026/abstract/<id>/,
      pubmed_id → /neuroscape/abstract/<id>/)
    - Counts sum to the lassoed total (verified by Playwright spec).
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { onMount, onDestroy } from 'svelte';

	type OhbmOverlayPoint = {
		poster_id: number;
		title: string;
		nearest_cluster_id: number;
	};
	type NeuroscapePoint = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
	};

	export let ohbm2026_ids: number[] = [];
	export let neuroscape_ids: number[] = [];
	export let overlayById: Map<number, OhbmOverlayPoint> = new Map();
	export let backdropById: Map<number, NeuroscapePoint> = new Map();
	export let permalinkFor: (kind: 'ohbm2026' | 'neuroscape', id: number) => string;

	const dispatch = createEventDispatcher<{ close: void }>();

	let ohbmOpen = true;
	let neuroOpen = true;

	function close() {
		dispatch('close');
	}

	function onBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) close();
	}

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Escape') close();
	}

	// Cap the per-section list to keep the modal scrollable on dense
	// lassos. Anything past the cap is summarised at the bottom of
	// the section.
	const CAP = 200;

	$: visible = ohbm2026_ids.length > 0 || neuroscape_ids.length > 0;
	$: ohbmRows = ohbm2026_ids
		.slice(0, CAP)
		.map((id) => overlayById.get(id))
		.filter((r): r is OhbmOverlayPoint => r !== undefined);
	$: neuroRows = neuroscape_ids
		.slice(0, CAP)
		.map((id) => backdropById.get(id))
		.filter((r): r is NeuroscapePoint => r !== undefined);

	let bound = false;
	onMount(() => {
		if (typeof window !== 'undefined') {
			window.addEventListener('keydown', onKey);
			bound = true;
		}
	});
	onDestroy(() => {
		if (bound && typeof window !== 'undefined') {
			window.removeEventListener('keydown', onKey);
		}
	});
</script>

{#if visible}
	<div
		class="lasso-backdrop"
		data-testid="atlas-root-lasso-results"
		role="dialog"
		aria-modal="true"
		aria-label="Lasso selection results"
		on:click={onBackdropClick}
		on:keydown={onKey}
		tabindex="-1"
	>
		<aside class="lasso-panel" data-testid="atlas-root-lasso-panel">
			<header class="lasso-head">
				<h2>Lasso selection</h2>
				<button
					type="button"
					class="close"
					on:click={close}
					aria-label="Close lasso results"
					data-testid="atlas-root-lasso-close"
				>
					×
				</button>
			</header>

			<section class="group" data-testid="atlas-root-lasso-ohbm-section">
				<button
					type="button"
					class="group-toggle"
					on:click={() => (ohbmOpen = !ohbmOpen)}
					aria-expanded={ohbmOpen}
				>
					<span class="caret">{ohbmOpen ? '▾' : '▸'}</span>
					OHBM 2026
					<span class="count" data-testid="atlas-root-lasso-ohbm-count"
						>({ohbm2026_ids.length.toLocaleString()} matched)</span
					>
				</button>
				{#if ohbmOpen}
					{#if ohbmRows.length === 0}
						<p class="empty">No OHBM 2026 abstracts in the selection.</p>
					{:else}
						<ul class="rows" data-testid="atlas-root-lasso-ohbm-rows">
							{#each ohbmRows as r (r.poster_id)}
								<li class="row">
									<a
										href={permalinkFor('ohbm2026', r.poster_id)}
										rel="external"
										class="row-link"
										data-testid="atlas-root-lasso-ohbm-row"
									>
										<span class="row-id">#{r.poster_id}</span>
										<span class="row-title">{r.title}</span>
									</a>
								</li>
							{/each}
						</ul>
						{#if ohbm2026_ids.length > CAP}
							<p class="overflow">
								… and {(ohbm2026_ids.length - CAP).toLocaleString()} more
							</p>
						{/if}
					{/if}
				{/if}
			</section>

			<section class="group" data-testid="atlas-root-lasso-neuro-section">
				<button
					type="button"
					class="group-toggle"
					on:click={() => (neuroOpen = !neuroOpen)}
					aria-expanded={neuroOpen}
				>
					<span class="caret">{neuroOpen ? '▾' : '▸'}</span>
					NeuroScape PubMed
					<span class="count" data-testid="atlas-root-lasso-neuro-count"
						>({neuroscape_ids.length.toLocaleString()} matched)</span
					>
				</button>
				{#if neuroOpen}
					{#if neuroRows.length === 0}
						<p class="empty">No NeuroScape articles in the selection.</p>
					{:else}
						<ul class="rows" data-testid="atlas-root-lasso-neuro-rows">
							{#each neuroRows as r (r.pubmed_id)}
								<li class="row">
									<a
										href={permalinkFor('neuroscape', r.pubmed_id)}
										rel="external"
										class="row-link"
										data-testid="atlas-root-lasso-neuro-row"
									>
										<span class="row-id">PMID {r.pubmed_id} · {r.year}</span>
										<span class="row-title">{r.title}</span>
									</a>
								</li>
							{/each}
						</ul>
						{#if neuroscape_ids.length > CAP}
							<p class="overflow">
								… and {(neuroscape_ids.length - CAP).toLocaleString()} more
							</p>
						{/if}
					{/if}
				{/if}
			</section>
		</aside>
	</div>
{/if}

<style>
	.lasso-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.35);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 110;
	}
	.lasso-panel {
		width: min(720px, 92%);
		max-height: 80vh;
		background: var(--bg-elevated);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 1rem 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
		overflow-y: auto;
	}
	.lasso-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.lasso-head h2 {
		font-size: 1rem;
		font-weight: 600;
		margin: 0;
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
	.group {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.group-toggle {
		all: unset;
		cursor: pointer;
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.92rem;
		font-weight: 600;
		color: var(--text);
		padding: 0.3rem 0.4rem;
		border-radius: 4px;
	}
	.group-toggle:hover {
		background: var(--bg-subtle);
	}
	.caret {
		font-size: 0.85rem;
		width: 1em;
	}
	.count {
		color: var(--text-muted);
		font-weight: 400;
	}
	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
	}
	.row {
		display: contents;
	}
	.row-link {
		display: grid;
		grid-template-columns: 7rem 1fr;
		gap: 0.6rem;
		align-items: baseline;
		padding: 0.35rem 0.5rem;
		border-radius: 4px;
		text-decoration: none;
		color: var(--text);
		font-size: 0.88rem;
	}
	.row-link:hover {
		background: var(--bg-subtle);
	}
	.row-id {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		font-size: 0.82rem;
	}
	.row-title {
		line-height: 1.35;
	}
	.empty,
	.overflow {
		font-size: 0.85rem;
		color: var(--text-muted);
		padding: 0.2rem 0.5rem;
		margin: 0;
	}
</style>
