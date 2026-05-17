<script lang="ts">
	import type { BuildInfo } from '$lib/shards';

	export let buildInfo: BuildInfo | null = null;

	let expanded = false;

	function toggle() {
		expanded = !expanded;
	}
</script>

<footer class="build-info" data-testid="build-info-footer">
	{#if buildInfo}
		<button
			type="button"
			on:click={toggle}
			aria-expanded={expanded}
			aria-controls="build-info-detail"
			class="summary"
		>
			<span class="label">build</span>
			<code data-testid="build-info-short-sha">{buildInfo.code_revision_short}</code>
			<span class="sep">·</span>
			<span class="corpus" data-testid="build-info-corpus-state">
				corpus {buildInfo.corpus_state_key}
			</span>
			<span class="sep">·</span>
			<time datetime={buildInfo.built_at}>{buildInfo.built_at}</time>
		</button>
		{#if expanded}
			<dl id="build-info-detail" class="detail">
				<dt>code_revision</dt>
				<dd><code>{buildInfo.code_revision}</code></dd>
				<dt>corpus_state_key</dt>
				<dd><code>{buildInfo.corpus_state_key}</code></dd>
				<dt>stage4_rollup_state_key</dt>
				<dd><code>{buildInfo.stage4_rollup_state_key}</code></dd>
				<dt>built_at</dt>
				<dd><code>{buildInfo.built_at}</code></dd>
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
		color: #555;
		padding: 0.5rem 1rem;
		border-top: 1px solid #eaeaea;
		background: #fafafa;
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
		color: #888;
	}
	.sep {
		color: #bbb;
	}
	.detail {
		margin: 0.5rem 0 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.15rem 0.75rem;
	}
	.detail dt {
		font-weight: 600;
		color: #777;
	}
	.detail dd {
		margin: 0;
	}
</style>
