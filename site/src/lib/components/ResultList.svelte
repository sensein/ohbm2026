<script lang="ts">
	import { focusedAbstract } from '$lib/stores/selection';
	import { cartStore } from '$lib/stores/cart';
	import type { AbstractRecord, AuthorRecord } from '$lib/shards';

	export let abstracts: AbstractRecord[];
	export let authorsById: Map<number, AuthorRecord>;
	/**
	 * If set, only abstracts whose `abstract_id` is in this set are rendered.
	 * `null` means "show all" (no filter).
	 */
	export let filteredIds: Set<number> | null = null;
	/** Truncate to this many cards to keep DOM size bounded; "Show more" appends. */
	export let initialWindow = 60;

	let revealed = initialWindow;

	$: visible = abstracts.filter((a) => filteredIds === null || filteredIds.has(a.abstract_id));
	$: pageItems = visible.slice(0, revealed);

	function loadMore() {
		revealed = Math.min(revealed + initialWindow, visible.length);
	}

	function focus(posterId: string) {
		$focusedAbstract = posterId;
	}

	function leadAuthor(record: AbstractRecord): string {
		const id = record.author_ids[0];
		if (id === undefined) return '';
		return authorsById.get(id)?.name ?? '';
	}
</script>

<section class="results" data-testid="result-list">
	<header class="results-header">
		<span data-testid="result-count">{visible.length}</span> abstract{visible.length === 1 ? '' : 's'}
		{#if filteredIds !== null}
			<span class="muted">(filtered)</span>
		{/if}
	</header>

	{#if visible.length === 0}
		<p class="empty">No abstracts match the current search.</p>
	{:else}
		<ul class="cards">
			{#each pageItems as record (record.abstract_id)}
				<li class="card" class:focused={$focusedAbstract === record.poster_id}>
					<button
						type="button"
						class="card-body"
						on:click={() => focus(record.poster_id)}
						data-testid="result-card"
						data-poster-id={record.poster_id}
					>
						<div class="poster-id">{record.poster_id || `id ${record.abstract_id}`}</div>
						<div class="title">{record.title}</div>
						<div class="lead-author">
							{leadAuthor(record)}
							{#if record.topics.primary}
								<span class="sep">·</span><span class="topic">{record.topics.primary}</span>
							{/if}
						</div>
					</button>
					<div class="card-actions">
						{#if $cartStore.has(record.poster_id)}
							<button
								type="button"
								class="cart-action remove"
								on:click={() => cartStore.remove(record.poster_id)}
								data-testid="card-cart-remove"
							>
								Saved ✓
							</button>
						{:else}
							<button
								type="button"
								class="cart-action add"
								on:click={() => cartStore.add(record.poster_id)}
								disabled={!record.poster_id}
								data-testid="card-cart-add"
							>
								+ list
							</button>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
		{#if pageItems.length < visible.length}
			<button type="button" class="load-more" on:click={loadMore} data-testid="load-more">
				Show {Math.min(initialWindow, visible.length - pageItems.length)} more
			</button>
		{/if}
	{/if}
</section>

<style>
	.results {
		min-width: 0;
	}
	.results-header {
		font-size: 0.85rem;
		color: var(--text-muted);
		margin: 0 0 0.5rem;
	}
	.results-header .muted {
		color: var(--text-faint);
	}
	.cards {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.card {
		display: flex;
		align-items: stretch;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--bg-elevated);
		overflow: hidden;
	}
	.card.focused {
		border-color: var(--accent);
		box-shadow: 0 0 0 1px var(--accent);
	}
	.card-body {
		all: unset;
		flex: 1;
		cursor: pointer;
		padding: 0.6rem 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		min-width: 0;
	}
	.card-body:hover {
		background: var(--bg-sunken);
	}
	.poster-id {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.8rem;
		color: var(--accent);
		font-weight: 600;
	}
	.title {
		font-size: 0.95rem;
		font-weight: 500;
		line-height: 1.3;
		color: var(--text);
		overflow: hidden;
		text-overflow: ellipsis;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
	}
	.lead-author {
		font-size: 0.8rem;
		color: var(--text-muted);
	}
	.sep {
		color: var(--text-faint);
		margin: 0 0.25rem;
	}
	.topic {
		color: var(--text-muted);
	}
	.card-actions {
		display: flex;
		align-items: center;
		padding: 0 0.5rem;
		border-left: 1px solid var(--border);
	}
	.cart-action {
		all: unset;
		cursor: pointer;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
		font-size: 0.8rem;
		color: var(--accent);
	}
	.cart-action:hover {
		background: var(--accent-soft-bg);
	}
	.cart-action.remove {
		color: var(--success);
	}
	.cart-action:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.load-more {
		margin-top: 0.5rem;
		align-self: center;
		padding: 0.5rem 1rem;
		border: 1px solid var(--border-strong);
		background: var(--bg);
		color: var(--text);
		border-radius: 4px;
		cursor: pointer;
	}
	.empty {
		color: var(--text-muted);
		font-style: italic;
	}
</style>
