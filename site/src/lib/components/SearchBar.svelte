<script lang="ts">
	import { tick } from 'svelte';
	import { get } from 'svelte/store';
	import { navigatorMode, posterIdUndoBuffer, searchQuery } from '$lib/stores/selection';
	import {
		filterSuggestions,
		normaliseQuery,
		parseIdOperator,
		type SuggestionResult
	} from '$lib/goto_poster';
	import type { AbstractRecord } from '$lib/shards';

	// Stage 14 — `id:` operator navigator mode. The map drives the
	// autocomplete dropdown. Falls back to an empty Map when the parent
	// hasn't passed the prop (in which case navigator mode renders
	// nothing useful, but the rest of the bar still works).
	export let abstractsByPosterId: Map<number, AbstractRecord> = new Map();

	// Spec 019 — corpus parameterisation (FR-025). The default
	// `'ohbm2026'` preserves the pre-spec-019 behaviour byte-identically
	// (T007 regression gate). `'neuroscape'` and `'atlas-root'` are
	// consumed by the mounts that ship in US1 (T028) and US4 (T044);
	// the only per-corpus differences are (a) the placeholder text
	// override below and (b) which `id:` autocomplete source the
	// downstream `filterSuggestions` call uses (NeuroScape passes a
	// pubmed-id-keyed map via `abstractsByPosterId` since the map
	// signature is corpus-agnostic; the dropdown rendering doesn't care
	// whether the numeric id is a poster_id or a pubmed_id).
	export let corpus: 'ohbm2026' | 'neuroscape' | 'atlas-root' = 'ohbm2026';
	export let placeholderOverride: string | null = null;

	// The input value lives in the `searchQuery` store. Binding the
	// `<input bind:value={$searchQuery}>` directly handles both
	// directions via Svelte's auto-subscription: user keystrokes
	// update the store, and external writers (the `g` shortcut)
	// propagate to the input immediately. `value` here is a
	// convenience alias for in-script reads.
	$: value = $searchQuery;

	let inputEl: HTMLInputElement | null = null;

	// Navigator-mode derivation.
	$: idPayload = parseIdOperator(value);
	$: inNavigatorMode = idPayload !== null;
	$: $navigatorMode = inNavigatorMode;
	let result: SuggestionResult = { visible: [], total: 0, exactMatch: null };
	$: result = inNavigatorMode
		? filterSuggestions(idPayload as string, abstractsByPosterId)
		: { visible: [], total: 0, exactMatch: null };

	let activeIndex = -1;
	$: if (!inNavigatorMode) activeIndex = -1;
	// When the suggestion set changes (user typed more / fewer digits),
	// re-clamp the active index so we don't point past the new list.
	$: if (activeIndex >= result.visible.length) activeIndex = -1;

	$: activeOptionId =
		activeIndex >= 0 && activeIndex < result.visible.length
			? `search-id-option-${result.visible[activeIndex].posterId}`
			: '';

	// User has explicitly dismissed the dropdown (Escape, or selection
	// committed) — keep it hidden until the next keystroke. Cleared on
	// any input event so further typing re-opens it.
	let dismissed = false;
	$: open = inNavigatorMode && !dismissed;
	$: void $searchQuery, (dismissed = false); // re-open on any input change

	/**
	 * Commit a poster id selection by writing `id:<id>` to the search
	 * query — this narrows the result list to exactly that id via the
	 * filter pipeline in `+page.svelte`. Dismisses the dropdown so the
	 * card is visible. Does NOT navigate.
	 */
	function commit(posterId: number) {
		// Consume the undo buffer; an Escape after a commit should not
		// roll back to the pre-`g` query.
		posterIdUndoBuffer.set(null);
		searchQuery.set(`id:${posterId}`);
		dismissed = true;
	}

	function onInputKeydown(e: KeyboardEvent) {
		if (!inNavigatorMode) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			if (result.visible.length === 0) return;
			activeIndex = (activeIndex + 1) % result.visible.length;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			if (result.visible.length === 0) return;
			activeIndex =
				(activeIndex - 1 + result.visible.length) % result.visible.length;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			// If a suggestion is highlighted, commit it. Otherwise
			// just close the dropdown — the result list already shows
			// the prefix-match set so there's nothing else to do.
			if (activeIndex >= 0 && activeIndex < result.visible.length) {
				commit(result.visible[activeIndex].posterId);
			} else if (result.exactMatch !== null) {
				// Single exact match already in the bar — narrow to it
				// and dismiss the dropdown so the user can see the card.
				commit(result.exactMatch.posterId);
			} else {
				dismissed = true;
			}
		} else if (e.key === 'Escape' && !helpOpen) {
			// Stage 14 — Escape restores the undo buffer IF the user
			// hasn't typed any further keystrokes since `g` fired.
			// Guard on `!helpOpen` so the window-level Escape handler
			// owns the help-popover-close path uncontested.
			e.preventDefault();
			const undo = get(posterIdUndoBuffer);
			if (undo !== null && value === 'id:') {
				searchQuery.set(undo);
				posterIdUndoBuffer.set(null);
			} else {
				// No undo to restore — just close the dropdown.
				dismissed = true;
			}
		}
	}

	// Window-level shortcut: `g` from outside any input/textarea/
	// contenteditable focuses the SearchBar and inserts the `id:`
	// prefix, saving the prior value to the undo buffer.
	function onWindowKeydown(e: KeyboardEvent) {
		if (helpOpen && e.key === 'Escape') {
			closeHelp();
			return;
		}
		if (e.key !== 'g' || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
		const t = e.target as Element | null;
		if (!t) return;
		const tag = t.tagName;
		if (
			tag === 'INPUT' ||
			tag === 'TEXTAREA' ||
			(t as HTMLElement).isContentEditable
		)
			return;
		e.preventDefault();
		posterIdUndoBuffer.set(value);
		searchQuery.set('id:');
		tick().then(() => {
			if (inputEl) {
				inputEl.focus();
				inputEl.setSelectionRange(3, 3); // length of 'id:'
			}
		});
	}

	let helpOpen = false;
	function toggleHelp() {
		helpOpen = !helpOpen;
	}
	function closeHelp() {
		helpOpen = false;
	}

	function onClear() {
		searchQuery.set('');
		posterIdUndoBuffer.set(null);
	}

	function onOptionClick(posterId: number) {
		commit(posterId);
	}
</script>

<!--
	Svelte requires `<svelte:window>` at the component root (not inside
	an `{#if}` block). The handler is a no-op for keys other than `g`
	and `Escape` (when help is open).
-->
<svelte:window on:keydown={onWindowKeydown} />

<div class="searchbar" role="search" data-corpus={corpus}>
	<label for="search-input" class="visually-hidden">Search abstracts</label>
	<input
		id="search-input"
		bind:this={inputEl}
		type="search"
		bind:value={$searchQuery}
		placeholder={placeholderOverride ?? 'Search… try "phrase", -exclude, word OR word, id:1234 (typos OK)'}
		autocomplete="off"
		spellcheck="false"
		data-testid="search-input"
		role={inNavigatorMode ? 'combobox' : undefined}
		aria-autocomplete={inNavigatorMode ? 'list' : undefined}
		aria-expanded={inNavigatorMode ? open : undefined}
		aria-controls={inNavigatorMode ? 'search-id-listbox' : undefined}
		aria-activedescendant={open && activeOptionId
			? activeOptionId
			: undefined}
		on:keydown={onInputKeydown}
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
	{#if open}
		<ul
			id="search-id-listbox"
			class="id-listbox"
			role="listbox"
			data-testid="search-id-listbox"
		>
			{#each result.visible as s, i (s.posterId)}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<li
					id={`search-id-option-${s.posterId}`}
					class="id-option"
					class:active={i === activeIndex}
					role="option"
					aria-selected={i === activeIndex}
					data-testid="search-id-option"
					data-poster-id={s.posterId}
					on:click={() => onOptionClick(s.posterId)}
					on:mouseenter={() => (activeIndex = i)}
				>
					<span class="display">{s.display}</span>
					<span class="title">{s.title}</span>
				</li>
			{/each}
			{#if idPayload !== null && normaliseQuery(idPayload as string) === ''}
				<li class="hint" data-testid="search-id-hint" role="status">
					Type a poster number, e.g. <code>id:1234</code>
				</li>
			{:else if result.total === 0}
				<li class="empty" data-testid="search-id-empty" role="status">
					No matching posters
				</li>
			{/if}
			{#if result.total > result.visible.length}
				<li class="overflow" data-testid="search-id-overflow" aria-live="polite">
					+ {result.total - result.visible.length} more — keep typing
				</li>
			{/if}
		</ul>
	{/if}
	{#if helpOpen}
		<!--
			Click-outside dismiss: a transparent backdrop catches clicks
			behind the popover so the user can dismiss without taking an
			explicit action on the toggle button. Escape-to-dismiss is
			wired via `<svelte:window>` above — a non-focusable `<div>`
			can't receive keydown.
		-->
		<div
			class="help-backdrop"
			role="presentation"
			on:click={closeHelp}
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
				<dt><code>id:1234</code></dt>
				<dd>jump to a specific poster id — autocomplete suggests available ids only</dd>
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

	/* Stage 14 — `id:` operator autocomplete dropdown. */
	.id-listbox {
		position: absolute;
		top: calc(100% + 0.3rem);
		left: 0;
		right: 0;
		z-index: 51;
		margin: 0;
		padding: 0.25rem 0;
		list-style: none;
		background: var(--bg);
		color: var(--text);
		border: 1px solid var(--border-strong);
		border-radius: 6px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
		max-height: 22rem;
		overflow-y: auto;
	}
	.id-option {
		display: flex;
		align-items: baseline;
		gap: 0.6rem;
		padding: 0.35rem 0.7rem;
		cursor: pointer;
		font-size: 0.9rem;
	}
	.id-option.active,
	.id-option:hover {
		background: var(--bg-subtle);
	}
	.id-option .display {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-weight: 600;
		color: var(--accent);
		min-width: 3.2rem;
	}
	.id-option .title {
		color: var(--text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.id-listbox .hint,
	.id-listbox .empty {
		padding: 0.45rem 0.7rem;
		color: var(--text-muted);
		font-size: 0.85rem;
	}
	.id-listbox .overflow {
		padding: 0.3rem 0.7rem;
		border-top: 1px solid var(--border);
		color: var(--text-muted);
		font-size: 0.75rem;
		text-align: right;
	}
</style>
