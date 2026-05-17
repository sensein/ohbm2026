<script lang="ts">
	import { focusedAbstract, authorChips } from '$lib/stores/selection';
	import { cartStore } from '$lib/stores/cart';
	import type { AbstractRecord, AuthorRecord } from '$lib/shards';

	export let abstracts: AbstractRecord[];
	export let authorsById: Map<number, AuthorRecord>;
	/**
	 * If set, only abstracts whose `abstract_id` is in this set are rendered.
	 * `null` means "show all" (no filter).
	 */
	export let filteredIds: Set<number> | null = null;
	/** When semantic search is active, a map `abstract_id → cosine similarity` so
	 * we can show a per-card score badge and sort by score. */
	export let semanticScores: Map<number, number> | null = null;
	/** When lexical search is active, a map `abstract_id → number of EXACT
	 * query-token matches`. Used as the primary sort key so an abstract that
	 * literally contains the user's query (e.g. "pydra") surfaces above
	 * fuzzy/proximal matches (hydra, pydry, etc.). */
	export let lexicalExactness: Map<number, number> | null = null;
	/** Per-abstract default rank — applied only when no search/semantic
	 * ranking is active. The parent shuffles abstract_ids on every page load
	 * so the home grid surfaces a different sample each visit. The semantic
	 * worker still indexes by the original positional order in
	 * `abstracts.json`, so we MUST NOT shuffle the underlying array. */
	export let defaultRank: Map<number, number> | null = null;
	/** Truncate to this many cards to keep DOM size bounded; "Show more" appends. */
	export let initialWindow = 60;

	let revealed = initialWindow;

	$: visible = (() => {
		const matched = abstracts.filter((a) => filteredIds === null || filteredIds.has(a.abstract_id));
		const hasExactness = lexicalExactness !== null && lexicalExactness.size > 0;
		const hasSemantic = semanticScores !== null && semanticScores.size > 0;
		if (!hasExactness && !hasSemantic) {
			// No search ranking — apply the random default order if provided.
			if (!defaultRank) return matched;
			return matched
				.slice()
				.sort((a, b) => (defaultRank!.get(a.abstract_id) ?? 0) - (defaultRank!.get(b.abstract_id) ?? 0));
		}
		// Sort key: primary = lexical exactness (higher first), secondary =
		// semantic score (higher first). Exactness wins because the user's
		// expectation when typing a rare technical term ("pydra") is that the
		// actual abstract containing the word lands at the top, not buried
		// among fuzzy proximal matches.
		return matched.slice().sort((a, b) => {
			const ea = (hasExactness ? lexicalExactness!.get(a.abstract_id) : undefined) ?? 0;
			const eb = (hasExactness ? lexicalExactness!.get(b.abstract_id) : undefined) ?? 0;
			if (ea !== eb) return eb - ea;
			const sa = hasSemantic ? semanticScores!.get(a.abstract_id) : undefined;
			const sb = hasSemantic ? semanticScores!.get(b.abstract_id) : undefined;
			if (sa === undefined && sb === undefined) return 0;
			if (sa === undefined) return 1;
			if (sb === undefined) return -1;
			return sb - sa;
		});
	})();
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

	function addAuthorChip(name: string) {
		if (!name) return;
		authorChips.update((s) => {
			if (s.has(name)) return s;
			const next = new Set(s);
			next.add(name);
			return next;
		});
	}

	// Visible poster_ids in the current filter/result state, used by the
	// bulk add control. The control is ADD-ONLY now — "Remove N from list"
	// was a foot-gun in Saved-only mode (one click wipes the cart) and
	// adding/removing in bulk should only ever grow the cart. Use the
	// drawer's per-item × or the "Clear" footer button to remove.
	$: visiblePosterIds = visible.map((r) => r.poster_id).filter(Boolean);
	$: missingFromCart = visiblePosterIds.filter((id) => !$cartStore.has(id));

	function addAllVisible() {
		if (missingFromCart.length > 0) cartStore.addMany(missingFromCart);
	}
</script>

<section class="results" data-testid="result-list">
	<header class="results-header">
		<span data-testid="result-count">{visible.length}</span> abstract{visible.length === 1 ? '' : 's'}
		{#if filteredIds !== null}
			<span class="muted">(filtered)</span>
		{/if}
		{#if missingFromCart.length > 0}
			<button
				type="button"
				class="bulk-action"
				on:click={addAllVisible}
				title={`Add the ${missingFromCart.length} visible abstract${missingFromCart.length === 1 ? '' : 's'} not yet in your list`}
				data-testid="bulk-cart-add"
			>
				+ Add {missingFromCart.length} to list
			</button>
		{/if}
	</header>

	{#if visible.length === 0}
		<p class="empty">No abstracts match the current search.</p>
	{:else}
		<ul class="cards">
			{#each pageItems as record (record.abstract_id)}
				{@const lead = leadAuthor(record)}
				<li class="card" class:focused={$focusedAbstract === record.poster_id}>
					<!-- The card-body used to be a single <button>, which prevented
						 nesting a real <button> for the author click. Switched to a
						 role="button" div + keyboard handler so the meta row can host
						 a separate author button. -->
					<div
						class="card-body"
						role="button"
						tabindex="0"
						on:click={() => focus(record.poster_id)}
						on:keydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') {
								e.preventDefault();
								focus(record.poster_id);
							}
						}}
						data-testid="result-card"
						data-poster-id={record.poster_id}
					>
						<div class="card-top">
							<span class="poster-id">{record.poster_id || `id ${record.abstract_id}`}</span>
							{#if semanticScores && semanticScores.has(record.abstract_id)}
								<span
									class="semantic-badge"
									title={`cosine similarity ${semanticScores.get(record.abstract_id)?.toFixed(3)} (distance ${(1 - (semanticScores.get(record.abstract_id) ?? 0)).toFixed(3)})`}
									data-testid="semantic-score"
								>
									✨ d={(1 - (semanticScores.get(record.abstract_id) ?? 0)).toFixed(3)}
								</span>
							{/if}
						</div>
						<div class="title">{record.title}</div>
						<div class="lead-author">
							{#if lead}
								<button
									type="button"
									class="lead-author-link"
									on:click|stopPropagation={() => addAuthorChip(lead)}
									title={`Filter by ${lead}`}
									data-testid="card-author-search"
								>{lead}</button>
							{/if}
							{#if record.topics.primary}
								<span class="sep">·</span><span class="topic">{record.topics.primary}</span>
							{/if}
						</div>
					</div>
					<div class="card-actions">
						{#if $cartStore.has(record.poster_id)}
							<button
								type="button"
								class="cart-icon in-cart"
								on:click={() => cartStore.remove(record.poster_id)}
								aria-label="Remove from your list"
								aria-pressed="true"
								title="In your list — click to remove"
								data-testid="card-cart-remove"
							>
								<!-- filled cart with checkmark indicates "in your list" -->
								<svg
									width="20"
									height="20"
									viewBox="0 0 24 24"
									fill="currentColor"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									aria-hidden="true"
								>
									<circle cx="9" cy="21" r="1.2" />
									<circle cx="18" cy="21" r="1.2" />
									<path
										fill="currentColor"
										stroke="currentColor"
										d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7 4.5 3H2zM7 9l1 5h11l1-5z"
									/>
								</svg>
								<span class="check-pip" aria-hidden="true">✓</span>
							</button>
						{:else}
							<button
								type="button"
								class="cart-icon"
								on:click={() => cartStore.add(record.poster_id)}
								disabled={!record.poster_id}
								aria-label="Add to your list"
								aria-pressed="false"
								title="Add to your list"
								data-testid="card-cart-add"
							>
								<!-- outlined cart indicates "not in list" -->
								<svg
									width="20"
									height="20"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									stroke-linecap="round"
									stroke-linejoin="round"
									aria-hidden="true"
								>
									<circle cx="9" cy="21" r="1.2" />
									<circle cx="18" cy="21" r="1.2" />
									<path d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7" />
								</svg>
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
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-wrap: wrap;
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
	.card-body:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
	.lead-author-link {
		all: unset;
		cursor: pointer;
		color: var(--text-muted);
		border-bottom: 1px dotted transparent;
	}
	.lead-author-link:hover {
		color: var(--accent);
		border-bottom-color: var(--accent);
	}
	.card-top {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: 0.5rem;
	}
	.poster-id {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.8rem;
		color: var(--accent);
		font-weight: 600;
	}
	.semantic-badge {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.72rem;
		color: var(--text-muted);
		background: var(--accent-soft-bg);
		padding: 0.1rem 0.4rem;
		border-radius: 999px;
		flex-shrink: 0;
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
	.cart-icon {
		all: unset;
		cursor: pointer;
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2.1rem;
		height: 2.1rem;
		border-radius: 4px;
		color: var(--text-faint);
	}
	.cart-icon:hover {
		background: var(--accent-soft-bg);
		color: var(--accent);
	}
	.cart-icon.in-cart {
		color: var(--accent);
	}
	.cart-icon.in-cart:hover {
		color: var(--warning-text, var(--accent));
	}
	.cart-icon .check-pip {
		position: absolute;
		bottom: -2px;
		right: -2px;
		background: var(--success);
		color: var(--bg-elevated);
		border-radius: 999px;
		width: 0.9rem;
		height: 0.9rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-size: 0.65rem;
		font-weight: 700;
		line-height: 1;
		border: 1.5px solid var(--bg-elevated);
	}
	.cart-icon:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.bulk-action {
		all: unset;
		cursor: pointer;
		margin-left: auto;
		padding: 0.25rem 0.6rem;
		font-size: 0.72rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--accent);
		background: var(--bg-elevated);
	}
	.bulk-action:hover {
		background: var(--accent-soft-bg);
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
