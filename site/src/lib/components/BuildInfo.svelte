<script lang="ts">
	import type { BuildInfo } from '$lib/shards';

	/** Build info from the live deploy workflow (VITE_BUILD_SHA env var). */
	export let deployBuildInfo: BuildInfo | null = null;
	/** Build info from the data package's manifest.json (when the data SHA differs from the deploy SHA). */
	export let dataBuildInfo: BuildInfo | null = null;

	let expanded = false;

	function toggle() {
		expanded = !expanded;
	}

	$: deploySha = deployBuildInfo?.code_revision_short ?? '';
	$: dataSha = dataBuildInfo?.code_revision_short ?? '';
	$: shasDiffer = deploySha && dataSha && deploySha !== dataSha;
	$: primary = deployBuildInfo ?? dataBuildInfo;
</script>

<footer class="build-info" data-testid="build-info-footer">
	{#if primary}
		<button
			type="button"
			on:click={toggle}
			aria-expanded={expanded}
			aria-controls="build-info-detail"
			class="summary"
		>
			<span class="label">build</span>
			<code data-testid="build-info-short-sha">{deploySha || dataSha}</code>
			{#if shasDiffer}
				<span class="sep">·</span>
				<span class="label">data</span>
				<code data-testid="build-info-data-sha">{dataSha}</code>
			{/if}
			{#if dataBuildInfo}
				<span class="sep">·</span>
				<span class="corpus" data-testid="build-info-corpus-state">
					corpus {dataBuildInfo.corpus_state_key}
				</span>
				<span class="sep">·</span>
				<time datetime={dataBuildInfo.built_at}>{dataBuildInfo.built_at}</time>
			{:else if deployBuildInfo}
				<span class="sep">·</span>
				<time datetime={deployBuildInfo.built_at}>{deployBuildInfo.built_at}</time>
			{/if}
		</button>
		{#if expanded}
			<dl id="build-info-detail" class="detail">
				{#if deployBuildInfo}
					<dt>deploy code_revision</dt>
					<dd><code>{deployBuildInfo.code_revision}</code></dd>
					<dt>deploy built_at</dt>
					<dd><code>{deployBuildInfo.built_at}</code></dd>
				{/if}
				{#if dataBuildInfo}
					<dt>data code_revision</dt>
					<dd><code>{dataBuildInfo.code_revision}</code></dd>
					<dt>data corpus_state_key</dt>
					<dd><code>{dataBuildInfo.corpus_state_key}</code></dd>
					<dt>data stage4_rollup_state_key</dt>
					<dd><code>{dataBuildInfo.stage4_rollup_state_key}</code></dd>
					<dt>data built_at</dt>
					<dd><code>{dataBuildInfo.built_at}</code></dd>
				{/if}
			</dl>
		{/if}
	{:else}
		<span class="label" data-testid="build-info-missing">build info unavailable</span>
	{/if}
</footer>

<style>
	.build-info {
		font-family:
			ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace;
		font-size: 0.75rem;
		color: var(--text-muted);
		padding: 0.5rem 1rem;
		border-top: 1px solid var(--border);
		background: var(--bg-subtle);
	}
	.summary {
		all: unset;
		cursor: pointer;
		display: inline-flex;
		gap: 0.4rem;
		align-items: baseline;
		flex-wrap: wrap;
	}
	.summary:hover code {
		text-decoration: underline;
	}
	.label {
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-faint);
	}
	.sep {
		color: var(--text-faint);
	}
	.detail {
		margin: 0.5rem 0 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.15rem 0.75rem;
	}
	.detail dt {
		font-weight: 600;
		color: var(--text-muted);
	}
	.detail dd {
		margin: 0;
	}
</style>
