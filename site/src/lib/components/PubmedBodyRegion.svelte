<!--
  Stage 15 (spec 015-neuroscape-context, T064):
  Body region of the NeuroScape detail page.

  - On mount, fires fetchPubmedRecord(pubmed_id).
  - While in flight, renders a skeleton (title-ish bars).
  - On success, renders authors + journal + abstract paragraphs +
    optional DOI link.
  - On persistent failure (3 retries exhausted), renders the body
    offline state per spec.md "Edge Cases":
      * "Retry" button → re-fires fetchPubmedRecord (the cache
        evicts on rejection so this is a real refetch).
      * "Open on pubmed.gov →" CTA → falls back to the PubMed
        canonical URL so the visitor still gets the article.

  Used only on SITE_MODE === 'neuroscape'. The atlas-root detail
  panel never shows bodies (per R-015 + contracts/atlas-root-ui.md).
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchPubmedRecord, type FetchedRecord } from '$lib/pubmed_fetch';

	export let pubmed_id: number;

	type State =
		| { kind: 'loading' }
		| { kind: 'loaded'; record: FetchedRecord }
		| { kind: 'error'; message: string };

	let state: State = { kind: 'loading' };

	async function load() {
		state = { kind: 'loading' };
		try {
			const record = await fetchPubmedRecord(pubmed_id);
			state = { kind: 'loaded', record };
		} catch (err) {
			const message = err instanceof Error ? err.message : String(err);
			state = { kind: 'error', message };
		}
	}

	onMount(() => {
		void load();
	});

	function pubmedCanonical(id: number): string {
		return `https://pubmed.ncbi.nlm.nih.gov/${id}/`;
	}

	function doiLink(doi: string): string {
		return `https://doi.org/${encodeURIComponent(doi)}`;
	}
</script>

<section class="pubmed-body" data-testid="pubmed-body-region" data-state={state.kind}>
	{#if state.kind === 'loading'}
		<div class="skeleton" data-testid="pubmed-body-skeleton" aria-busy="true">
			<div class="bar bar-short"></div>
			<div class="bar bar-medium"></div>
			<div class="bar bar-long"></div>
			<div class="bar bar-long"></div>
			<div class="bar bar-medium"></div>
		</div>
	{:else if state.kind === 'loaded'}
		<div class="loaded" data-testid="pubmed-body-loaded">
			{#if state.record.authors.length > 0}
				<p class="authors" data-testid="pubmed-body-authors">
					{state.record.authors.join(', ')}
				</p>
			{/if}
			{#if state.record.journal}
				<p class="journal" data-testid="pubmed-body-journal">{state.record.journal}</p>
			{/if}
			{#if state.record.abstract_text}
				<div class="abstract" data-testid="pubmed-body-abstract">
					{#each state.record.abstract_text.split('\n\n') as para, i (i)}
						<p>{para}</p>
					{/each}
				</div>
			{:else}
				<p class="empty" data-testid="pubmed-body-empty">
					This PubMed record has no abstract text.
				</p>
			{/if}
			<p class="external-links">
				{#if state.record.doi}
					<a
						href={doiLink(state.record.doi)}
						target="_blank"
						rel="noopener noreferrer"
						data-testid="pubmed-body-doi"
					>
						DOI: {state.record.doi}
					</a>
				{/if}
				<a
					href={pubmedCanonical(pubmed_id)}
					target="_blank"
					rel="noopener noreferrer"
					data-testid="pubmed-body-pubmed-link"
				>
					Open on pubmed.gov →
				</a>
			</p>
		</div>
	{:else}
		<div class="offline" data-testid="pubmed-body-offline" role="alert">
			<p>
				Couldn't fetch the abstract body from PubMed right now.
				<span class="error-detail">({state.message})</span>
			</p>
			<div class="offline-actions">
				<button
					type="button"
					class="retry-btn"
					on:click={load}
					data-testid="pubmed-body-retry"
				>
					Retry
				</button>
				<a
					href={pubmedCanonical(pubmed_id)}
					target="_blank"
					rel="noopener noreferrer"
					class="pubmed-link"
					data-testid="pubmed-body-offline-link"
				>
					Open on pubmed.gov →
				</a>
			</div>
		</div>
	{/if}
</section>

<style>
	.pubmed-body {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}
	.skeleton {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}
	.bar {
		height: 0.85rem;
		background: var(--bg-subtle);
		border-radius: 4px;
		animation: shimmer 1.6s linear infinite;
	}
	.bar-short { width: 35%; }
	.bar-medium { width: 65%; }
	.bar-long { width: 92%; }
	@keyframes shimmer {
		0% { opacity: 0.6; }
		50% { opacity: 0.9; }
		100% { opacity: 0.6; }
	}
	.authors {
		margin: 0;
		font-size: 0.9rem;
		color: var(--text-muted);
	}
	.journal {
		margin: 0;
		font-style: italic;
		font-size: 0.9rem;
		color: var(--text-muted);
	}
	.abstract {
		display: flex;
		flex-direction: column;
		gap: 0.55rem;
		margin-top: 0.4rem;
	}
	.abstract p {
		margin: 0;
		line-height: 1.55;
		font-size: 0.95rem;
	}
	.empty {
		margin: 0.3rem 0;
		color: var(--text-muted);
		font-style: italic;
	}
	.external-links {
		display: flex;
		gap: 1rem;
		flex-wrap: wrap;
		margin-top: 0.5rem;
		font-size: 0.88rem;
	}
	.external-links a {
		color: var(--accent);
		text-decoration: none;
	}
	.external-links a:hover {
		text-decoration: underline;
	}
	.offline {
		background: var(--warning-bg);
		color: var(--warning-text);
		border: 1px solid var(--warning-border);
		border-radius: 4px;
		padding: 0.75rem 1rem;
		font-size: 0.92rem;
	}
	.offline p {
		margin: 0 0 0.5rem;
	}
	.error-detail {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.82rem;
		opacity: 0.75;
	}
	.offline-actions {
		display: flex;
		gap: 0.75rem;
		align-items: center;
	}
	.retry-btn {
		all: unset;
		cursor: pointer;
		padding: 0.35rem 0.75rem;
		border-radius: 3px;
		background: var(--accent);
		color: var(--accent-text);
		font-size: 0.88rem;
		font-weight: 500;
	}
	.retry-btn:hover {
		filter: brightness(1.05);
	}
	.pubmed-link {
		color: var(--accent);
		text-decoration: none;
		font-size: 0.88rem;
	}
</style>
