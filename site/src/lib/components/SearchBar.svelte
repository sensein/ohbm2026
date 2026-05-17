<script lang="ts">
	import { searchQuery } from '$lib/stores/selection';

	let value = '';
	$: $searchQuery = value;

	let helpOpen = false;
	function toggleHelp() {
		helpOpen = !helpOpen;
	}
	function closeHelp() {
		helpOpen = false;
	}

	function onClear() {
		value = '';
	}
</script>

<div class="searchbar" role="search">
	<label for="search-input" class="visually-hidden">Search abstracts</label>
	<input
		id="search-input"
		type="search"
		bind:value
		placeholder='Search… try "phrase", -exclude, word OR word  (typos OK)'
		autocomplete="off"
		spellcheck="false"
		data-testid="search-input"
	/>
	<div class="actions">
		{#if value}
			<button
				type="button"
				class="icon-btn"
				on:click={onClear}
				aria-label="Clear search"
				data-testid="search-clear"
			>×</button>
		{/if}
		<button
			type="button"
			class="icon-btn help-btn"
			class:active={helpOpen}
			on:click={toggleHelp}
			aria-label="Search syntax help"
			aria-expanded={helpOpen}
			title="Search syntax help"
			data-testid="search-help-toggle"
		>?</button>
	</div>
	{#if helpOpen}
		<!--
			Click-outside dismiss: a transparent backdrop catches clicks
			behind the popover so the user can dismiss without taking an
			explicit action on the toggle button.
		-->
		<div
			class="help-backdrop"
			role="presentation"
			on:click={closeHelp}
			on:keydown={(e) => { if (e.key === 'Escape') closeHelp(); }}
		></div>
		<div class="help-popover" role="dialog" aria-label="Search syntax help" data-testid="search-help-popover">
			<div class="help-title">Search operators</div>
			<dl>
				<dt><code>word word</code></dt>
				<dd>AND of typo-tolerant words (default)</dd>
				<dt><code>"phrase here"</code></dt>
				<dd>words must appear adjacent</dd>
				<dt><code>-word</code> · <code>-"phrase"</code></dt>
				<dd>exclude</dd>
				<dt><code>word OR word</code></dt>
				<dd>either; <code>OR</code> must be uppercase</dd>
			</dl>
			<div class="help-foot">
				Semantic suggestions still apply to the operators-stripped query (✨ badge on cards
				marks semantic-only hits).
			</div>
		</div>
	{/if}
</div>

<style>
	.searchbar {
		position: relative;
		display: flex;
		align-items: center;
		width: 100%;
	}
	input[type='search'] {
		width: 100%;
		padding: 0.6rem 4rem 0.6rem 0.8rem;
		font-size: 1rem;
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		box-sizing: border-box;
		background: var(--bg);
		color: var(--text);
	}
	input[type='search']:focus {
		outline: 2px solid var(--accent);
		outline-offset: 0;
		border-color: var(--accent);
	}
	.actions {
		position: absolute;
		right: 0.3rem;
		top: 50%;
		transform: translateY(-50%);
		display: flex;
		align-items: center;
		gap: 0.1rem;
	}
	.icon-btn {
		background: transparent;
		border: 0;
		font-size: 1.2rem;
		line-height: 1;
		cursor: pointer;
		color: var(--text-muted);
		padding: 0.2rem 0.4rem;
		border-radius: 4px;
	}
	.icon-btn:hover {
		color: var(--text);
		background: var(--bg-subtle);
	}
	.help-btn {
		font-size: 0.95rem;
		font-weight: 600;
		border: 1px solid var(--border);
		width: 1.6rem;
		height: 1.6rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0;
	}
	.help-btn.active {
		color: var(--accent);
		border-color: var(--accent);
	}
	.help-backdrop {
		position: fixed;
		inset: 0;
		z-index: 50;
		background: transparent;
	}
	.help-popover {
		position: absolute;
		top: calc(100% + 0.4rem);
		right: 0;
		z-index: 51;
		background: var(--bg);
		color: var(--text);
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
		padding: 0.7rem 0.85rem;
		min-width: 18rem;
		max-width: 22rem;
		font-size: 0.85rem;
	}
	.help-title {
		font-weight: 600;
		margin-bottom: 0.45rem;
		color: var(--text);
	}
	dl {
		margin: 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.25rem 0.6rem;
	}
	dt {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.78rem;
		color: var(--text);
	}
	dt code {
		background: var(--bg-subtle);
		padding: 0.05rem 0.25rem;
		border-radius: 3px;
	}
	dd {
		margin: 0;
		color: var(--text-muted);
	}
	.help-foot {
		margin-top: 0.6rem;
		padding-top: 0.5rem;
		border-top: 1px solid var(--border);
		color: var(--text-muted);
		font-size: 0.78rem;
		line-height: 1.4;
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
</style>
