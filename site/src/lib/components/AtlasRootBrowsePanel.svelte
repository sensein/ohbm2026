<!--
  Stage 15 (spec 015-neuroscape-context, UX-unification slice):
  Cross-conference atlas-root browse panel.

  Mirrors the NeuroScape browse panel's shape (search input + facet
  row + paginated result list) but with two distinct sources:
    - NeuroScape backdrop articles (pubmed_id, title, year, cluster)
    - OHBM 2026 overlay abstracts (poster_id, title, nearest_cluster)
  And two facets per user spec:
    - Clusters (multi-select, shared between both sources)
    - Sites (filter to OHBM 2026, NeuroScape PubMed, or both)

  Click row → atlas-root detail panel (slide-in card with the right
  permalink CTA into the appropriate subsite).
  "On atlas" button → focus the scatter on the clicked point.

  Search target: title + (poster_id|pubmed_id) substring,
  case-insensitive via $lib/filter:normalize.
-->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { normalize } from '$lib/filter';

	type BackdropPoint = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
	};
	type OverlayPoint = {
		submission_id: number;
		poster_id: number;
		title: string;
		nearest_cluster_id: number;
	};
	type Cluster = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};

	export let backdropPoints: BackdropPoint[] = [];
	export let overlayPoints: OverlayPoint[] = [];
	export let clustersById: Map<number, Cluster> = new Map();
	export let permalinkFor: (kind: 'ohbm2026' | 'neuroscape', id: number) => string;

	const dispatch = createEventDispatcher<{
		select: { kind: 'ohbm2026' | 'neuroscape'; id: number };
		focus: { kind: 'ohbm2026' | 'neuroscape'; id: number; cluster_id: number };
		filter: { cluster_ids: Set<number>; show_ohbm: boolean; show_neuro: boolean };
	}>();

	let query = '';
	let limit = 100;

	// Site filter — both visible by default.
	let showOhbm = true;
	let showNeuro = true;

	// Cluster facet — multi-select. Shared by OHBM (via nearest_cluster_id)
	// and NeuroScape (cluster_id).
	let selectedClusterIds: Set<number> = new Set();
	let clusterSearch = '';

	$: clusterCounts = (() => {
		const counts = new Map<number, number>();
		for (const a of backdropPoints) counts.set(a.cluster_id, (counts.get(a.cluster_id) ?? 0) + 1);
		for (const o of overlayPoints)
			counts.set(o.nearest_cluster_id, (counts.get(o.nearest_cluster_id) ?? 0) + 1);
		return counts;
	})();
	$: clusterPickList = (() => {
		const list = [...clustersById.values()];
		list.sort((a, b) => {
			const ca = clusterCounts.get(a.cluster_id) ?? 0;
			const cb = clusterCounts.get(b.cluster_id) ?? 0;
			if (ca !== cb) return cb - ca;
			return a.title.localeCompare(b.title);
		});
		if (!clusterSearch.trim()) return list;
		const needle = normalize(clusterSearch);
		return list.filter((c) => normalize(c.title).includes(needle));
	})();

	function toggleCluster(id: number) {
		const next = new Set(selectedClusterIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedClusterIds = next;
		notifyFilter();
	}
	function clearClusters() {
		selectedClusterIds = new Set();
		notifyFilter();
	}
	function notifyFilter() {
		dispatch('filter', {
			cluster_ids: selectedClusterIds,
			show_ohbm: showOhbm,
			show_neuro: showNeuro
		});
	}
	$: void [showOhbm, showNeuro], notifyFilter();

	// Unified result rows. Score: title-substring position. Empty
	// query → ordering biased toward smaller corpora (OHBM first,
	// then NeuroScape by year desc).
	type Row =
		| { kind: 'ohbm2026'; id: number; title: string; cluster_id: number; subline: string }
		| {
				kind: 'neuroscape';
				id: number;
				title: string;
				cluster_id: number;
				subline: string;
		  };

	$: filtered = (() => {
		const needle = query.trim() ? normalize(query) : '';
		const out: Array<{ row: Row; score: number; tie: number }> = [];

		if (showOhbm) {
			for (const o of overlayPoints) {
				if (selectedClusterIds.size > 0 && !selectedClusterIds.has(o.nearest_cluster_id))
					continue;
				if (needle) {
					const hay = normalize(o.title);
					const idx = hay.indexOf(needle);
					const pidStr = String(o.poster_id);
					const pidIdx = pidStr.indexOf(query.trim());
					if (idx === -1 && pidIdx === -1) continue;
					const score = idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
					out.push({
						row: {
							kind: 'ohbm2026',
							id: o.poster_id,
							title: o.title,
							cluster_id: o.nearest_cluster_id,
							subline: `OHBM 2026 · #${o.poster_id}`
						},
						score,
						tie: -o.poster_id // OHBM ties biased numeric-asc by id
					});
				} else {
					out.push({
						row: {
							kind: 'ohbm2026',
							id: o.poster_id,
							title: o.title,
							cluster_id: o.nearest_cluster_id,
							subline: `OHBM 2026 · #${o.poster_id}`
						},
						score: -1, // OHBM gets ordered first when no query
						tie: o.poster_id
					});
				}
			}
		}

		if (showNeuro) {
			for (const a of backdropPoints) {
				if (selectedClusterIds.size > 0 && !selectedClusterIds.has(a.cluster_id)) continue;
				if (needle) {
					const hay = normalize(a.title);
					const idx = hay.indexOf(needle);
					const pmidStr = String(a.pubmed_id);
					const pmidIdx = pmidStr.indexOf(query.trim());
					if (idx === -1 && pmidIdx === -1) continue;
					const score = idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
					out.push({
						row: {
							kind: 'neuroscape',
							id: a.pubmed_id,
							title: a.title,
							cluster_id: a.cluster_id,
							subline: `NeuroScape · PMID ${a.pubmed_id} · ${a.year}`
						},
						score,
						tie: -a.year
					});
				} else {
					out.push({
						row: {
							kind: 'neuroscape',
							id: a.pubmed_id,
							title: a.title,
							cluster_id: a.cluster_id,
							subline: `NeuroScape · PMID ${a.pubmed_id} · ${a.year}`
						},
						score: -a.year, // newer NeuroScape first under no-query
						tie: a.pubmed_id
					});
				}
			}
		}

		out.sort((x, y) => x.score - y.score || x.tie - y.tie);
		return out.map((s) => s.row);
	})();

	$: visible = filtered.slice(0, limit);
	$: totalCount = filtered.length;
	$: ohbmShown = filtered.filter((r) => r.kind === 'ohbm2026').length;
	$: neuroShown = filtered.filter((r) => r.kind === 'neuroscape').length;
</script>

<section class="ar-browse" data-testid="atlas-root-browse-panel">
	<div class="ar-search-row">
		<label class="ar-search">
			<span class="visually-hidden">Search across both corpora</span>
			<input
				type="search"
				placeholder="Search OHBM 2026 + NeuroScape titles or ids…"
				bind:value={query}
				data-testid="atlas-root-search-input"
			/>
			{#if query}
				<button
					type="button"
					class="ar-clear"
					on:click={() => (query = '')}
					aria-label="Clear search"
					data-testid="atlas-root-search-clear"
				>
					×
				</button>
			{/if}
		</label>

		<div class="ar-facets">
			<!-- Site facet — show OHBM 2026 / NeuroScape / both. -->
			<div class="ar-site-facet" data-testid="atlas-root-site-facet">
				<label class="ar-site-row">
					<input
						type="checkbox"
						bind:checked={showOhbm}
						data-testid="atlas-root-site-ohbm"
					/>
					<span>OHBM 2026 <span class="ar-n">({ohbmShown.toLocaleString()})</span></span>
				</label>
				<label class="ar-site-row">
					<input
						type="checkbox"
						bind:checked={showNeuro}
						data-testid="atlas-root-site-neuro"
					/>
					<span>NeuroScape <span class="ar-n">({neuroShown.toLocaleString()})</span></span>
				</label>
			</div>

			<!-- Cluster facet — same shape as the neuroscape one. -->
			<details class="ar-cluster-facet" data-testid="atlas-root-cluster-facet">
				<summary>
					Clusters
					{#if selectedClusterIds.size > 0}
						<span class="ar-cluster-count">({selectedClusterIds.size})</span>
					{/if}
				</summary>
				<div class="ar-cluster-panel">
					<div class="ar-cluster-controls">
						<input
							type="search"
							placeholder="Filter clusters…"
							bind:value={clusterSearch}
							data-testid="atlas-root-cluster-search"
						/>
						{#if selectedClusterIds.size > 0}
							<button
								type="button"
								class="ar-cluster-clear"
								on:click={clearClusters}
								data-testid="atlas-root-cluster-clear"
							>
								Clear ({selectedClusterIds.size})
							</button>
						{/if}
					</div>
					<ul class="ar-cluster-list">
						{#each clusterPickList as c (c.cluster_id)}
							{@const count = clusterCounts.get(c.cluster_id) ?? 0}
							<li>
								<label class="ar-cluster-row">
									<input
										type="checkbox"
										checked={selectedClusterIds.has(c.cluster_id)}
										on:change={() => toggleCluster(c.cluster_id)}
										data-testid={`atlas-root-cluster-cb-${c.cluster_id}`}
									/>
									<span
										class="ar-cluster-swatch"
										style="background:{c.colour_hex}"
									></span>
									<span class="ar-cluster-title">{c.title}</span>
									<span class="ar-cluster-n">{count.toLocaleString()}</span>
								</label>
							</li>
						{/each}
					</ul>
				</div>
			</details>
		</div>
	</div>

	<p class="ar-count" data-testid="atlas-root-result-count">
		{totalCount.toLocaleString()} {totalCount === 1 ? 'match' : 'matches'}
		{#if totalCount > limit}
			· showing first {limit}
		{/if}
	</p>

	<ul class="ar-results" data-testid="atlas-root-result-list">
		{#each visible as r (r.kind + ':' + r.id)}
			{@const cluster = clustersById.get(r.cluster_id)}
			<li class="ar-row">
				<a
					class="ar-row-link"
					href={permalinkFor(r.kind, r.id)}
					rel="external"
					data-testid={`atlas-root-result-row-${r.kind}`}
					on:click={(e) => {
						// Default link still works (full-page nav to the sibling
						// subsite). If the visitor wants the in-page detail
						// panel instead, that's the implicit point-click on the
						// scatter — we leave anchor click to its normal nav.
					}}
				>
					<div class="ar-row-head">
						<span class="ar-kind-tag" data-kind={r.kind}>
							{r.kind === 'ohbm2026' ? 'OHBM' : 'NeuroScape'}
						</span>
						<span class="ar-subline">{r.subline}</span>
						{#if cluster}
							<span class="ar-cluster">
								<span
									class="ar-cluster-swatch"
									style="background:{cluster.colour_hex}"
								></span>
								{cluster.title}
							</span>
						{/if}
					</div>
					<div class="ar-title">{r.title}</div>
				</a>
				<button
					type="button"
					class="ar-show-atlas"
					title="Show on atlas + open detail panel"
					on:click={() => dispatch('select', { kind: r.kind, id: r.id })}
					data-testid="atlas-root-row-select"
				>
					Details
				</button>
			</li>
		{/each}
	</ul>

	{#if totalCount > limit}
		<button
			type="button"
			class="ar-more"
			on:click={() => (limit = Math.min(limit * 2, totalCount))}
			data-testid="atlas-root-show-more"
		>
			Show more
		</button>
	{/if}
</section>

<style>
	.ar-browse {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}
	.ar-search-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		align-items: center;
	}
	.ar-search {
		flex: 1 1 22rem;
		position: relative;
		display: flex;
		align-items: center;
	}
	.ar-search input[type='search'] {
		width: 100%;
		padding: 0.5rem 2rem 0.5rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-elevated);
		color: var(--text);
		font-size: 0.95rem;
	}
	.ar-clear {
		all: unset;
		cursor: pointer;
		position: absolute;
		right: 0.5rem;
		font-size: 1.1rem;
		color: var(--text-muted);
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
	}
	.ar-clear:hover {
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
	.ar-facets {
		display: flex;
		gap: 0.6rem;
		align-items: center;
		flex-wrap: wrap;
	}
	.ar-site-facet {
		display: flex;
		gap: 0.75rem;
		font-size: 0.85rem;
		padding: 0.35rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-elevated);
	}
	.ar-site-row {
		display: inline-flex;
		gap: 0.35rem;
		align-items: center;
		cursor: pointer;
	}
	.ar-n {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		font-size: 0.78rem;
	}
	.ar-cluster-facet {
		position: relative;
		font-size: 0.85rem;
	}
	.ar-cluster-facet > summary {
		cursor: pointer;
		padding: 0.35rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-elevated);
		color: var(--text);
		list-style: none;
		user-select: none;
	}
	.ar-cluster-facet > summary::-webkit-details-marker {
		display: none;
	}
	.ar-cluster-facet > summary::before {
		content: '▸';
		display: inline-block;
		margin-right: 0.3em;
		font-size: 0.7em;
		color: var(--text-muted);
	}
	.ar-cluster-facet[open] > summary::before {
		content: '▾';
	}
	.ar-cluster-count {
		color: var(--text-muted);
		font-weight: 500;
		margin-left: 0.3em;
	}
	.ar-cluster-panel {
		position: absolute;
		z-index: 50;
		top: calc(100% + 0.25rem);
		left: 0;
		min-width: 22rem;
		max-width: 30rem;
		max-height: 22rem;
		display: flex;
		flex-direction: column;
		background: var(--bg-elevated);
		border: 1px solid var(--border);
		border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
	}
	.ar-cluster-controls {
		display: flex;
		gap: 0.5rem;
		padding: 0.5rem;
		border-bottom: 1px solid var(--border);
	}
	.ar-cluster-controls input[type='search'] {
		flex: 1;
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg);
		color: var(--text);
		font-size: 0.85rem;
	}
	.ar-cluster-clear {
		all: unset;
		cursor: pointer;
		padding: 0.35rem 0.6rem;
		border-radius: 3px;
		font-size: 0.8rem;
		color: var(--text-muted);
		border: 1px solid var(--border);
	}
	.ar-cluster-clear:hover {
		color: var(--text);
		background: var(--bg-subtle);
	}
	.ar-cluster-list {
		list-style: none;
		margin: 0;
		padding: 0.25rem 0;
		overflow-y: auto;
		flex: 1;
	}
	.ar-cluster-row {
		display: grid;
		grid-template-columns: 1rem 0.7rem 1fr auto;
		gap: 0.5rem;
		align-items: center;
		padding: 0.3rem 0.6rem;
		cursor: pointer;
		font-size: 0.85rem;
	}
	.ar-cluster-row:hover {
		background: var(--bg-subtle);
	}
	.ar-cluster-swatch {
		display: inline-block;
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 2px;
		border: 1px solid var(--border);
	}
	.ar-cluster-title {
		overflow-wrap: anywhere;
		line-height: 1.3;
	}
	.ar-cluster-n {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		font-size: 0.78rem;
	}
	.ar-count {
		margin: 0;
		font-size: 0.85rem;
		color: var(--text-muted);
	}
	.ar-results {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		max-height: 70vh;
		overflow-y: auto;
	}
	.ar-row {
		display: flex;
		gap: 0.5rem;
		align-items: stretch;
		padding: 0.5rem 0.65rem;
		border-radius: 4px;
		border: 1px solid var(--border);
	}
	.ar-row:hover {
		background: var(--bg-subtle);
	}
	.ar-row-link {
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		text-decoration: none;
		color: var(--text);
		min-width: 0;
	}
	.ar-row-head {
		display: flex;
		gap: 0.6rem;
		flex-wrap: wrap;
		font-size: 0.78rem;
		color: var(--text-muted);
		align-items: baseline;
	}
	.ar-kind-tag {
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-size: 0.7rem;
		padding: 0.05rem 0.35rem;
		border-radius: 3px;
		color: var(--accent-soft-text);
		background: var(--accent-soft-bg);
	}
	.ar-subline {
		font-variant-numeric: tabular-nums;
	}
	.ar-cluster {
		display: inline-flex;
		gap: 0.3rem;
		align-items: center;
	}
	.ar-title {
		font-size: 0.92rem;
		line-height: 1.35;
		color: var(--text);
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.ar-show-atlas {
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
	.ar-show-atlas:hover {
		background: var(--accent-soft-bg);
	}
	.ar-more {
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
	.ar-more:hover {
		filter: brightness(1.05);
	}
</style>
