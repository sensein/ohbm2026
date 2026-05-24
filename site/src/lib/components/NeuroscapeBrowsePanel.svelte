<!--
  Stage 15 (spec 015-neuroscape-context, T067):
  NeuroScape PubMed subsite browse panel.

  Title-bar search + result list of articles, scoped to
  neuroscape.parquet's `articles` rows. Click a row → navigate to
  /neuroscape/abstract/<pubmed_id>/.

  Search shape (FR-018): title-only, case-insensitive, currently
  substring + token-prefix scoring (NOT yet the full typo-tolerant
  engine the OHBM 2026 SearchBar uses). The spec's "parametrise the
  existing typo-tolerant engine" intent is deferred — pulling the
  engine apart cleanly is its own slice. This implementation covers
  the common case (visitor types "hippocampus" or "place cells" →
  ranked title matches) and the empty-query case (first 100 by
  PubMed id).

  Pagination: shows first 100 matches, with a "Show more" affordance
  that doubles the cap. The full 461k corpus is too dense to render
  in one list.
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { base } from '$app/paths';
	import { normalize } from '$lib/filter';

	type Article = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
	};
	type Cluster = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};

	export let articles: Article[] = [];
	export let clustersById: Map<number, Cluster> = new Map();

	const dispatch = createEventDispatcher<{
		focus: { pubmed_id: number; cluster_id: number };
	}>();

	let query = '';
	let limit = 100;

	// Year facet — typical visitor wants to narrow to "recent" articles.
	let minYear: number | null = null;
	let maxYear: number | null = null;
	$: yearBounds = (() => {
		if (articles.length === 0) return { lo: 0, hi: 0 };
		let lo = Infinity;
		let hi = -Infinity;
		for (const a of articles) {
			if (a.year < lo) lo = a.year;
			if (a.year > hi) hi = a.year;
		}
		return { lo: Number.isFinite(lo) ? lo : 0, hi: Number.isFinite(hi) ? hi : 0 };
	})();

	$: filtered = (() => {
		// Year filter first — cheap, narrows the search space.
		const yLo = minYear ?? yearBounds.lo;
		const yHi = maxYear ?? yearBounds.hi;
		const yearFilt = articles.filter((a) => a.year >= yLo && a.year <= yHi);
		if (!query.trim()) {
			// No query → "Recent first" ordering (descending by year,
			// then by pubmed_id for stability).
			return [...yearFilt].sort((a, b) => b.year - a.year || a.pubmed_id - b.pubmed_id);
		}
		const needle = normalize(query);
		// Score by first-match position; ties broken by year desc.
		const scored: Array<{ a: Article; score: number }> = [];
		for (const a of yearFilt) {
			const hay = normalize(a.title);
			const idx = hay.indexOf(needle);
			if (idx === -1) continue;
			// Earlier match = lower score = better; -idx makes higher
			// scores worse so we sort ascending by `score`.
			scored.push({ a, score: idx });
		}
		scored.sort((x, y) => x.score - y.score || y.a.year - x.a.year);
		return scored.map((s) => s.a);
	})();

	$: visible = filtered.slice(0, limit);

	function gotoDetail(pubmed_id: number) {
		return `${base}/abstract/${pubmed_id}/`;
	}

	function onShowOnAtlas(a: Article) {
		dispatch('focus', { pubmed_id: a.pubmed_id, cluster_id: a.cluster_id });
	}

	function clearQuery() {
		query = '';
	}
</script>

<section class="ns-browse" data-testid="neuroscape-browse-panel">
	<div class="ns-search-row">
		<label class="ns-search">
			<span class="visually-hidden">Search NeuroScape titles</span>
			<input
				type="search"
				placeholder="Search 461,316 NeuroScape titles…"
				bind:value={query}
				data-testid="neuroscape-search-input"
			/>
			{#if query}
				<button
					type="button"
					class="ns-clear"
					on:click={clearQuery}
					aria-label="Clear search"
					data-testid="neuroscape-search-clear"
				>
					×
				</button>
			{/if}
		</label>

		<div class="ns-facets">
			<label class="ns-year">
				<span>Year ≥</span>
				<input
					type="number"
					min={yearBounds.lo}
					max={yearBounds.hi}
					bind:value={minYear}
					placeholder={String(yearBounds.lo)}
					data-testid="neuroscape-year-min"
				/>
			</label>
			<label class="ns-year">
				<span>Year ≤</span>
				<input
					type="number"
					min={yearBounds.lo}
					max={yearBounds.hi}
					bind:value={maxYear}
					placeholder={String(yearBounds.hi)}
					data-testid="neuroscape-year-max"
				/>
			</label>
		</div>
	</div>

	<p class="ns-count" data-testid="neuroscape-result-count">
		{filtered.length.toLocaleString()} {filtered.length === 1 ? 'match' : 'matches'}
		{#if filtered.length > limit}
			· showing first {limit}
		{/if}
	</p>

	<ul class="ns-results" data-testid="neuroscape-result-list">
		{#each visible as a (a.pubmed_id)}
			{@const cluster = clustersById.get(a.cluster_id)}
			<li class="ns-row">
				<a
					class="ns-row-link"
					href={gotoDetail(a.pubmed_id)}
					data-testid="neuroscape-result-row"
				>
					<div class="ns-row-head">
						<span class="ns-pmid">PMID {a.pubmed_id}</span>
						<span class="ns-year">{a.year}</span>
						{#if cluster}
							<span class="ns-cluster">
								<span
									class="ns-cluster-swatch"
									style="background:{cluster.colour_hex}"
								></span>
								{cluster.title}
							</span>
						{/if}
					</div>
					<div class="ns-title">{a.title}</div>
				</a>
				<button
					type="button"
					class="ns-show-atlas"
					title="Focus this article on the atlas"
					on:click={() => onShowOnAtlas(a)}
					data-testid="neuroscape-row-show-atlas"
				>
					On atlas
				</button>
			</li>
		{/each}
	</ul>

	{#if filtered.length > limit}
		<button
			type="button"
			class="ns-more"
			on:click={() => (limit = Math.min(limit * 2, filtered.length))}
			data-testid="neuroscape-show-more"
		>
			Show more
		</button>
	{/if}
</section>

<style>
	.ns-browse {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}
	.ns-search-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		align-items: center;
	}
	.ns-search {
		flex: 1 1 18rem;
		position: relative;
		display: flex;
		align-items: center;
	}
	.ns-search input[type='search'] {
		width: 100%;
		padding: 0.5rem 2rem 0.5rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-elevated);
		color: var(--text);
		font-size: 0.95rem;
	}
	.ns-clear {
		all: unset;
		cursor: pointer;
		position: absolute;
		right: 0.5rem;
		font-size: 1.1rem;
		color: var(--text-muted);
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
	}
	.ns-clear:hover {
		background: var(--bg-subtle);
		color: var(--text);
	}
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		border: 0;
	}
	.ns-facets {
		display: flex;
		gap: 0.6rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.ns-year {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
		font-size: 0.85rem;
		color: var(--text-muted);
	}
	.ns-year input {
		width: 5rem;
		padding: 0.3rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg-elevated);
		color: var(--text);
		font-size: 0.85rem;
	}
	.ns-count {
		margin: 0;
		font-size: 0.85rem;
		color: var(--text-muted);
	}
	.ns-results {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		max-height: 70vh;
		overflow-y: auto;
	}
	.ns-row {
		display: flex;
		gap: 0.5rem;
		align-items: stretch;
		padding: 0.5rem 0.65rem;
		border-radius: 4px;
		border: 1px solid var(--border);
	}
	.ns-row:hover {
		background: var(--bg-subtle);
	}
	.ns-row-link {
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		text-decoration: none;
		color: var(--text);
		min-width: 0;
	}
	.ns-row-head {
		display: flex;
		gap: 0.7rem;
		flex-wrap: wrap;
		font-size: 0.78rem;
		color: var(--text-muted);
	}
	.ns-pmid {
		font-variant-numeric: tabular-nums;
	}
	.ns-cluster {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
	}
	.ns-cluster-swatch {
		display: inline-block;
		width: 0.6rem;
		height: 0.6rem;
		border-radius: 2px;
		border: 1px solid var(--border);
	}
	.ns-title {
		font-size: 0.92rem;
		line-height: 1.35;
		color: var(--text);
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.ns-show-atlas {
		all: unset;
		cursor: pointer;
		padding: 0.35rem 0.6rem;
		border-radius: 3px;
		font-size: 0.78rem;
		color: var(--accent);
		border: 1px solid var(--accent);
		background: transparent;
		align-self: flex-start;
		white-space: nowrap;
	}
	.ns-show-atlas:hover {
		background: var(--accent-soft-bg);
	}
	.ns-more {
		all: unset;
		cursor: pointer;
		align-self: center;
		padding: 0.4rem 0.85rem;
		border-radius: 4px;
		background: var(--accent);
		color: var(--accent-text);
		font-size: 0.88rem;
		font-weight: 500;
	}
	.ns-more:hover {
		filter: brightness(1.05);
	}
</style>
