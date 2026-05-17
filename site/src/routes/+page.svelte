<script lang="ts">
	import { onMount } from 'svelte';
	import {
		buildInfoFromEnv,
		loadAbstracts,
		loadAuthors,
		loadManifest,
		type AbstractRecord,
		type AuthorRecord,
		type BuildInfo,
		type Manifest
	} from '$lib/shards';
	import { focusedAbstract, lassoSelection, searchQuery } from '$lib/stores/selection';
	import { lexicalSearch } from '$lib/filter';
	import SearchBar from '$lib/components/SearchBar.svelte';
	import ResultList from '$lib/components/ResultList.svelte';
	import DetailPanel from '$lib/components/DetailPanel.svelte';
	import ModelSelector from '$lib/components/ModelSelector.svelte';
	import UmapPanel from '$lib/components/UmapPanel.svelte';

	let manifest: Manifest | null = null;
	let abstracts: AbstractRecord[] = [];
	let authorsById: Map<number, AuthorRecord> = new Map();
	let abstractsByPosterId: Map<string, AbstractRecord> = new Map();
	let abstractsById: Map<number, AbstractRecord> = new Map();
	let loaded = false;
	let dataMissing = false;
	let showMap = false;
	const envBuildInfo: BuildInfo | null = buildInfoFromEnv();

	onMount(async () => {
		const [m, a, au] = await Promise.all([loadManifest(), loadAbstracts(), loadAuthors()]);
		manifest = m;
		if (a && au) {
			abstracts = a.abstracts;
			authorsById = new Map(au.authors.map((x) => [x.author_id, x]));
			abstractsByPosterId = new Map(
				a.abstracts.filter((x) => x.poster_id).map((x) => [x.poster_id, x])
			);
			abstractsById = new Map(a.abstracts.map((x) => [x.abstract_id, x]));
			// Test-only debug global used by Playwright accepted-only invariant guard.
			if (typeof window !== 'undefined') {
				(window as unknown as { __abstracts: AbstractRecord[] }).__abstracts = abstracts;
			}
		} else {
			dataMissing = true;
		}
		loaded = true;
	});

	$: searchIds = lexicalSearch(abstracts, authorsById, $searchQuery);
	$: filteredIds = intersect(searchIds, $lassoSelection);
	$: focused = $focusedAbstract ? (abstractsByPosterId.get($focusedAbstract) ?? null) : null;

	function intersect(a: Set<number> | null, b: Set<number> | null): Set<number> | null {
		if (a === null && b === null) return null;
		if (a === null) return b;
		if (b === null) return a;
		const out: Set<number> = new Set();
		const [small, large] = a.size <= b.size ? [a, b] : [b, a];
		for (const id of small) if (large.has(id)) out.add(id);
		return out;
	}
</script>

<div class="home" class:has-focus={focused !== null}>
	<div class="top-row">
		<div class="search-row">
			<SearchBar />
		</div>
		{#if loaded && !dataMissing}
			<div class="controls">
				<ModelSelector {manifest} />
				<button
					type="button"
					class="map-toggle"
					class:active={showMap}
					on:click={() => (showMap = !showMap)}
					aria-pressed={showMap}
					data-testid="toggle-map"
				>
					{showMap ? '✕ Hide map' : '🗺  Show map'}
				</button>
			</div>
		{/if}
	</div>

	{#if showMap && loaded && !dataMissing}
		<UmapPanel {abstracts} />
	{/if}

	{#if !loaded}
		<p class="status">Loading…</p>
	{:else if dataMissing}
		<section class="placeholder" data-testid="data-missing">
			<h2>Data package not deployed yet</h2>
			{#if envBuildInfo}
				<p class="committish-callout">
					This preview is built from
					<code data-testid="placeholder-short-sha">{envBuildInfo.code_revision_short}</code>
					but no <code>data/abstracts.json</code> was found.
				</p>
			{/if}
			<p>
				The deploy workflow runs against the source code; the Stage 1–4 inputs aren't yet
				wired into CI via <code>scripts/fetch_ui_inputs.sh</code>. Build locally per
				<code>specs/008-ui-rewrite/quickstart.md</code> to exercise the full UI.
			</p>
		</section>
	{:else}
		<div class="layout">
			<div class="list-pane">
				<ResultList {abstracts} {authorsById} {filteredIds} />
			</div>
			<div class="detail-pane" class:active={focused !== null}>
				{#if focused}
					<DetailPanel abstract={focused} {authorsById} {abstractsById} />
				{:else}
					<aside class="detail-empty">
						<p>Tap an abstract to see its details here.</p>
						{#if manifest}
							<dl class="manifest-stats">
								<dt>Accepted abstracts</dt>
								<dd data-testid="abstract-count">{manifest.corpus_count}</dd>
								<dt>Models × inputs</dt>
								<dd>{manifest.models.length} × {manifest.inputs.length}</dd>
								<dt>Cells</dt>
								<dd>{manifest.cells.length}</dd>
							</dl>
						{/if}
					</aside>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.home {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.top-row {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		align-items: center;
		justify-content: space-between;
	}
	.search-row {
		flex: 1 1 22rem;
		min-width: 0;
	}
	.controls {
		display: flex;
		align-items: flex-end;
		gap: 0.75rem;
	}
	.map-toggle {
		all: unset;
		cursor: pointer;
		padding: 0.45rem 0.8rem;
		border-radius: 4px;
		font-size: 0.85rem;
		border: 1px solid var(--border-strong);
		background: var(--bg);
		color: var(--text);
	}
	.map-toggle:hover {
		background: var(--bg-sunken);
	}
	.map-toggle.active {
		background: var(--accent);
		color: var(--accent-text);
		border-color: var(--accent);
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 1rem;
		width: 100%;
	}
	.list-pane {
		min-width: 0;
	}
	.detail-pane {
		min-width: 0;
	}
	.detail-empty {
		background: var(--bg-subtle);
		border: 1px dashed var(--border-strong);
		border-radius: 6px;
		padding: 1rem;
		color: var(--text-muted);
	}
	.manifest-stats {
		margin: 0.75rem 0 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.25rem 1rem;
		font-size: 0.9rem;
	}
	.manifest-stats dt {
		color: var(--text-faint);
	}
	.placeholder {
		background: var(--warning-bg);
		border: 1px solid var(--warning-border);
		color: var(--text);
		border-radius: 6px;
		padding: 1rem;
	}
	.committish-callout {
		font-size: 0.95rem;
	}
	.status {
		color: var(--text-muted);
		font-style: italic;
	}
	code {
		background: var(--bg-sunken);
		color: var(--text);
		padding: 0 0.25rem;
		border-radius: 3px;
		font-size: 0.95em;
	}

	@media (min-width: 1024px) {
		.layout {
			grid-template-columns: minmax(0, 1fr) clamp(24rem, 28vw, 42rem);
			align-items: start;
		}
		.detail-pane {
			position: sticky;
			top: 1rem;
			max-height: calc(100vh - 2rem);
			overflow-y: auto;
		}
	}

	/* Mobile: detail panel becomes a full-screen overlay when focused. */
	@media (max-width: 1023px) {
		.home.has-focus .list-pane {
			display: none;
		}
		.detail-pane:not(.active) {
			display: none;
		}
		.home.has-focus .detail-pane {
			display: block;
		}
	}
</style>
