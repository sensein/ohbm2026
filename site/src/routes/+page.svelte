<script lang="ts">
	import { onMount } from 'svelte';
	import { loadManifest, type Manifest } from '$lib/shards';

	let manifest: Manifest | null = null;
	let error: string | null = null;

	onMount(async () => {
		try {
			manifest = await loadManifest();
		} catch (err) {
			error = (err as Error).message;
		}
	});
</script>

<section class="placeholder">
	<h2 data-testid="page-title">Stage 6 — under construction</h2>

	{#if manifest}
		<p class="committish-callout">
			Built from
			<code data-testid="placeholder-short-sha">{manifest.build_info.code_revision_short}</code>
			against corpus
			<code>{manifest.build_info.corpus_state_key}</code>
			and Stage 4 rollup
			<code>{manifest.build_info.stage4_rollup_state_key}</code>.
		</p>
		<p>
			This page renders the data-package <code>manifest.json</code> only — the real US1 home
			page lands in a subsequent PR. The build pipeline + per-PR preview deploys are wired so
			reviewers can verify each PR by clicking <em>"View deployment"</em> in the PR's Deployments
			box (top-of-PR) and confirming the short SHA above matches the latest pushed commit.
		</p>
		<dl class="stats">
			<dt>Accepted abstracts</dt>
			<dd>{manifest.corpus_count}</dd>
			<dt>Models</dt>
			<dd>{manifest.models.join(', ')}</dd>
			<dt>Inputs</dt>
			<dd>{manifest.inputs.join(', ')}</dd>
			<dt>Cells</dt>
			<dd>{manifest.cells.length} <span class="muted">({manifest.models.length} × {manifest.inputs.length})</span></dd>
			<dt>Facet catalog</dt>
			<dd>{manifest.facets.length} facets</dd>
		</dl>
	{:else if error}
		<p class="error">
			Failed to load <code>manifest.json</code>: {error}
		</p>
	{:else}
		<p>Loading <code>manifest.json</code>…</p>
		<noscript>
			<p class="error">JavaScript is required to render the build provenance.</p>
		</noscript>
	{/if}
</section>

<style>
	.placeholder {
		padding: 1rem 0 2rem;
	}
	.placeholder h2 {
		margin: 0 0 0.75rem;
	}
	.committish-callout {
		background: #fffbe6;
		border: 1px solid #f0e2a4;
		padding: 0.75rem 1rem;
		border-radius: 4px;
		font-size: 0.95rem;
	}
	.stats {
		margin: 1.5rem 0 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.25rem 1rem;
		font-size: 0.9rem;
	}
	.stats dt {
		color: #666;
		font-weight: 500;
	}
	.stats dd {
		margin: 0;
	}
	.muted {
		color: #999;
	}
	.error {
		color: #b00;
	}
	code {
		background: #f4f4f4;
		padding: 0 0.25rem;
		border-radius: 3px;
		font-size: 0.95em;
	}
</style>
