<script lang="ts">
	import { focusedAbstract } from '$lib/stores/selection';
	import { cartStore } from '$lib/stores/cart';
	import type { AbstractRecord, AuthorRecord } from '$lib/shards';

	export let abstract: AbstractRecord | null = null;
	export let authorsById: Map<number, AuthorRecord>;
	export let dismissable = true;

	let showAllAuthors = false;

	$: authorList = abstract
		? abstract.author_ids
				.map((id) => authorsById.get(id))
				.filter((a): a is AuthorRecord => a !== undefined)
		: [];
	$: visibleAuthors = showAllAuthors ? authorList : authorList.slice(0, 6);

	function close() {
		$focusedAbstract = null;
	}

	function inCart(posterId: string): boolean {
		return $cartStore.has(posterId);
	}
</script>

{#if abstract}
	<aside class="detail" data-testid="detail-panel" data-poster-id={abstract.poster_id}>
		<header class="detail-header">
			<div class="ids">
				<span
					class="poster-id"
					data-testid="detail-poster-id"
					title="Program-assigned poster id"
				>
					{abstract.poster_id || `(no poster id)`}
				</span>
				<span class="accepted-for">{abstract.accepted_for}</span>
			</div>
			{#if dismissable}
				<button
					type="button"
					class="close"
					on:click={close}
					aria-label="Close detail panel"
					data-testid="detail-close"
				>
					×
				</button>
			{/if}
		</header>

		<h1 class="detail-title" data-testid="detail-title">{abstract.title}</h1>

		<section class="authors" data-testid="detail-authors">
			<h2>Authors</h2>
			<ol class="author-list">
				{#each visibleAuthors as author (author.author_id)}
					<li>
						<span class="author-name">{author.name}</span>
						{#if author.affiliations[0]}
							<span class="author-aff">— {author.affiliations[0]}</span>
						{/if}
					</li>
				{/each}
			</ol>
			{#if authorList.length > 6}
				<button
					type="button"
					class="link"
					on:click={() => (showAllAuthors = !showAllAuthors)}
					data-testid="detail-toggle-authors"
				>
					{showAllAuthors ? 'Show fewer' : `Show all ${authorList.length} authors`}
				</button>
			{/if}
		</section>

		{#if abstract.sections.introduction}
			<section class="section" data-testid="section-introduction">
				<h2>Introduction</h2>
				<p>{abstract.sections.introduction}</p>
			</section>
		{/if}
		{#if abstract.sections.methods}
			<section class="section" data-testid="section-methods">
				<h2>Methods</h2>
				<p>{abstract.sections.methods}</p>
			</section>
		{/if}
		{#if abstract.sections.results}
			<section class="section" data-testid="section-results">
				<h2>Results</h2>
				<p>{abstract.sections.results}</p>
			</section>
		{/if}
		{#if abstract.sections.conclusion}
			<section class="section" data-testid="section-conclusion">
				<h2>Conclusion</h2>
				<p>{abstract.sections.conclusion}</p>
			</section>
		{/if}

		<!--
			FR-011: only Topics + Methods of the submission-form extras render.
			Other extra-question fields (study_type, population, field_strength,
			processing_packages, …) are stored in `facets` for filtering but MUST
			NOT surface in the detail panel.
		-->
		{#if abstract.topics.primary || abstract.topics.secondary}
			<section class="extra topics" data-testid="extra-topics">
				<h2>Topics</h2>
				<dl>
					{#if abstract.topics.primary}
						<dt>Primary</dt>
						<dd>
							{abstract.topics.primary}{#if abstract.topics.primary_subcategory}
								<span class="muted"> / {abstract.topics.primary_subcategory}</span>
							{/if}
						</dd>
					{/if}
					{#if abstract.topics.secondary}
						<dt>Secondary</dt>
						<dd>
							{abstract.topics.secondary}{#if abstract.topics.secondary_subcategory}
								<span class="muted"> / {abstract.topics.secondary_subcategory}</span>
							{/if}
						</dd>
					{/if}
				</dl>
			</section>
		{/if}

		{#if abstract.methods_checklist.length}
			<section class="extra methods-checklist" data-testid="extra-methods">
				<h2>Methods</h2>
				<ul class="chips">
					{#each abstract.methods_checklist as m (m)}
						<li>{m}</li>
					{/each}
				</ul>
			</section>
		{/if}

		{#if abstract.reference_urls.some(Boolean) || abstract.reference_dois.some(Boolean) || (abstract.reference_titles ?? []).some(Boolean)}
			<section class="references" data-testid="detail-references">
				<h2>References</h2>
				<ol>
					{#each abstract.reference_urls as url, i (url + i)}
						{@const doi = abstract.reference_dois[i] || ''}
						{@const title = (abstract.reference_titles ?? [])[i] || ''}
						{@const linkUrl = url || (doi ? `https://doi.org/${doi}` : '')}
						<li>
							{#if linkUrl}
								<a href={linkUrl} target="_blank" rel="noopener noreferrer">
									{title || doi || linkUrl}
								</a>
								{#if title && doi}
									<span class="ref-doi" title="DOI">{doi}</span>
								{/if}
							{:else if title}
								<span>{title}</span>
							{/if}
						</li>
					{/each}
				</ol>
			</section>
		{/if}

		<footer class="detail-footer">
			{#if inCart(abstract.poster_id)}
				<button
					type="button"
					class="cart-action remove"
					on:click={() => cartStore.remove(abstract.poster_id)}
					data-testid="detail-cart-remove"
				>
					Remove from list
				</button>
			{:else}
				<button
					type="button"
					class="cart-action add"
					on:click={() => cartStore.add(abstract.poster_id)}
					disabled={!abstract.poster_id}
					data-testid="detail-cart-add"
				>
					+ add to list
				</button>
			{/if}
			{#if abstract.poster_id}
				<a class="permalink" href={`./abstract/${abstract.poster_id}/`} data-testid="detail-permalink">
					permalink
				</a>
			{/if}
		</footer>
	</aside>
{/if}

<style>
	.detail {
		background: var(--bg-elevated);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		min-width: 0;
	}
	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
	}
	.ids {
		display: flex;
		gap: 0.5rem;
		align-items: baseline;
	}
	.poster-id {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-weight: 700;
		font-size: 1rem;
		color: var(--accent);
	}
	.accepted-for {
		font-size: 0.75rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.close {
		all: unset;
		cursor: pointer;
		font-size: 1.5rem;
		color: var(--text-muted);
		padding: 0 0.25rem;
	}
	.close:hover {
		color: var(--text);
	}
	.detail-title {
		font-size: 1.2rem;
		margin: 0;
		line-height: 1.3;
		color: var(--text);
	}
	h2 {
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		margin: 0 0 0.25rem;
	}
	.section p,
	.detail dd {
		margin: 0;
		font-size: 0.95rem;
		line-height: 1.55;
		color: var(--text);
	}
	.section p {
		white-space: pre-wrap;
	}
	.author-list {
		margin: 0;
		padding-left: 1.25rem;
		font-size: 0.9rem;
	}
	.author-aff {
		color: var(--text-muted);
	}
	.link {
		all: unset;
		color: var(--accent);
		cursor: pointer;
		font-size: 0.85rem;
		margin-top: 0.25rem;
	}
	.link:hover {
		text-decoration: underline;
	}
	dl {
		margin: 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.25rem 0.75rem;
		font-size: 0.9rem;
	}
	dt {
		color: var(--text-muted);
		font-weight: 500;
	}
	dd {
		margin: 0;
	}
	.muted {
		color: var(--text-faint);
	}
	.chips {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.chips li {
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text);
		padding: 0.2rem 0.5rem;
		border-radius: 999px;
		font-size: 0.8rem;
	}
	.references ol {
		margin: 0;
		padding-left: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		font-size: 0.85rem;
	}
	.references a {
		color: var(--accent);
		word-break: normal;
	}
	.references a:hover {
		text-decoration: underline;
	}
	.ref-doi {
		color: var(--text-muted);
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.78rem;
		margin-left: 0.5rem;
	}
	.detail-footer {
		display: flex;
		gap: 0.75rem;
		align-items: center;
		justify-content: flex-end;
		border-top: 1px solid var(--border);
		padding-top: 0.5rem;
	}
	.cart-action {
		all: unset;
		cursor: pointer;
		padding: 0.4rem 0.8rem;
		border-radius: 4px;
		font-size: 0.85rem;
		background: var(--accent);
		color: var(--accent-text);
	}
	.cart-action.remove {
		background: var(--bg);
		color: var(--success);
		border: 1px solid var(--success);
	}
	.cart-action:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.permalink {
		font-size: 0.85rem;
		color: var(--text-muted);
		text-decoration: none;
	}
	.permalink:hover {
		color: var(--accent);
		text-decoration: underline;
	}
</style>
