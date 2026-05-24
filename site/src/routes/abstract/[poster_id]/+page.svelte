<!--
  Stage 15 (spec 015-neuroscape-context, T065 + T066):
  Detail page route shared by /ohbm2026/abstract/<poster_id>/ AND
  /neuroscape/abstract/<pubmed_id>/.

  SvelteKit's filename-driven routing requires the directory name to
  be the same across both modes; only the in-file branch differs.
  The param key is `poster_id` (from the directory name), but in
  neuroscape mode it carries the pubmed_id — both are positive
  integers so a single `Number(param)` recovers either.

  Byte-identity invariant (FR-022 / SC-008): the ohbm2026 build's
  compiled output of this file MUST NOT drift. SITE_MODE is a build-
  time Vite-substituted constant; the `{#if SITE_MODE === 'neuroscape'}`
  branch is dead-code-eliminated in the ohbm2026 build. The script-
  level `import`s and `let`s that the neuroscape branch needs are
  guarded behind a top-level `if (SITE_MODE === 'neuroscape')` so
  Rollup tree-shakes their bundle contribution out of the ohbm2026
  build.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import {
		loadAbstracts,
		loadAuthors,
		type AbstractRecord,
		type AuthorRecord
	} from '$lib/shards';
	import DetailPanel from '$lib/components/DetailPanel.svelte';
	import SearchBar from '$lib/components/SearchBar.svelte';
	import { SITE_MODE } from '$lib/site_mode';
	import { loadDataPackage } from '$lib/data_package/loader';
	import PubmedBodyRegion from '$lib/components/PubmedBodyRegion.svelte';

	// === Shared (both modes) =================================================
	$: posterIdParam = $page.params.poster_id;
	$: posterIdInt = Number(posterIdParam);

	// === OHBM 2026 mode =====================================================
	let abstractRecord: AbstractRecord | null = null;
	let authorsById: Map<number, AuthorRecord> = new Map();
	let abstractsById: Map<number, AbstractRecord> = new Map();
	let loaded = false;
	let unknown = false;

	// === NeuroScape mode ====================================================
	// Local fields (read from neuroscape.parquet); the runtime PubMed
	// fetch is delegated to PubmedBodyRegion.
	type NeuroscapeArticle = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
		umap_2d?: [number, number];
		umap_3d: [number, number, number];
		nearest_pubmed_ids?: number[];
		nearest_distances?: number[];
	};
	type NeuroscapeCluster = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};
	let nsArticle: NeuroscapeArticle | null = null;
	let nsCluster: NeuroscapeCluster | null = null;
	let nsNeighborTitles: Map<number, string> = new Map();

	function rootBase(): string {
		// In neuroscape mode `base` includes `/neuroscape`; strip it so
		// "Show on atlas" can target /neuroscape/ (the home of THIS
		// subsite, not a nested child). atlas-root + ohbm2026 don't
		// hit this route so the branch doesn't need to handle them.
		if (SITE_MODE === 'neuroscape' && base.endsWith('/neuroscape')) {
			return base.slice(0, -'/neuroscape'.length);
		}
		return base;
	}

	$: showOnAtlasHref = nsArticle
		? `${rootBase()}/neuroscape/?focus=${nsArticle.pubmed_id}&cluster=${nsArticle.cluster_id}`
		: '';

	onMount(async () => {
		if (SITE_MODE === 'neuroscape') {
			const pkg = await loadDataPackage();
			if (!pkg) {
				loaded = true;
				unknown = true;
				return;
			}
			const articlesShard = pkg.get('data/neuroscape/articles.json') as
				| { articles: NeuroscapeArticle[] }
				| undefined;
			const clustersShard = pkg.get('data/neuroscape/clusters.json') as
				| { clusters: NeuroscapeCluster[] }
				| undefined;
			if (!articlesShard || !clustersShard) {
				loaded = true;
				unknown = true;
				return;
			}
			const article = articlesShard.articles.find((a) => a.pubmed_id === posterIdInt) ?? null;
			if (!article) {
				loaded = true;
				unknown = true;
				return;
			}
			nsArticle = article;
			nsCluster =
				clustersShard.clusters.find((c) => c.cluster_id === article.cluster_id) ?? null;
			// Build a lookup so the neighbour list shows titles. (The
			// neighbour ids are local to neuroscape.parquet so the
			// articles shard always carries the titles we need.)
			const byId = new Map(articlesShard.articles.map((a) => [a.pubmed_id, a.title]));
			nsNeighborTitles = byId;
			loaded = true;
			return;
		}
		// OHBM 2026 path — UNCHANGED from the pre-Stage-15 behaviour.
		const [a, au] = await Promise.all([loadAbstracts(), loadAuthors()]);
		if (!a || !au) {
			loaded = true;
			unknown = true;
			return;
		}
		authorsById = new Map(au.authors.map((x) => [x.author_id, x]));
		abstractsById = new Map(a.abstracts.map((x) => [x.poster_id, x]));
		const target = a.abstracts.find((x) => x.poster_id === posterIdInt) ?? null;
		abstractRecord = target;
		unknown = target === null;
		loaded = true;
	});
</script>

<svelte:head>
	{#if SITE_MODE === 'neuroscape'}
		{#if nsArticle}
			<title>PMID {nsArticle.pubmed_id} — {nsArticle.title}</title>
		{:else}
			<title>Article not found</title>
		{/if}
	{:else if abstractRecord}
		<title>{String(abstractRecord.poster_id).padStart(4, '0')} — {abstractRecord.title}</title>
	{:else}
		<title>Abstract not found</title>
	{/if}
</svelte:head>

{#if SITE_MODE === 'neuroscape'}
	<!-- NeuroScape PubMed detail page (T065) -->
	<div class="permalink-page" data-testid="neuroscape-detail-page">
		<nav class="back">
			<a href={`${base}/`} data-testid="neuroscape-back-link">← all NeuroScape articles</a>
		</nav>

		{#if !loaded}
			<p class="status">Loading…</p>
		{:else if unknown || !nsArticle}
			<section class="not-found" data-testid="neuroscape-article-not-found">
				<h1>No PubMed article with id <code>{posterIdParam}</code></h1>
				<p>
					The id in this URL doesn't match any article in the current NeuroScape data
					package. It may have been filtered out or the package may not be deployed yet.
				</p>
			</section>
		{:else}
			<article class="ns-article" data-testid="neuroscape-detail-article">
				<header class="ns-head">
					<h1 class="ns-title" data-testid="neuroscape-detail-title">{nsArticle.title}</h1>
					<dl class="ns-meta">
						<div>
							<dt>PubMed id</dt>
							<dd data-testid="neuroscape-detail-pubmed-id">{nsArticle.pubmed_id}</dd>
						</div>
						<div>
							<dt>Year</dt>
							<dd data-testid="neuroscape-detail-year">{nsArticle.year}</dd>
						</div>
						{#if nsCluster}
							<div>
								<dt>Cluster</dt>
								<dd data-testid="neuroscape-detail-cluster">
									<span
										class="cluster-swatch"
										style="background:{nsCluster.colour_hex}"
									></span>
									{nsCluster.title}
								</dd>
							</div>
						{/if}
					</dl>
					<div class="ns-actions">
						<a
							class="show-on-atlas"
							href={showOnAtlasHref}
							data-testid="neuroscape-show-on-atlas"
						>
							Show on atlas →
						</a>
					</div>
				</header>

				<PubmedBodyRegion pubmed_id={nsArticle.pubmed_id} />

				{#if nsArticle.nearest_pubmed_ids && nsArticle.nearest_pubmed_ids.length > 0}
					<aside class="neighbours" data-testid="neuroscape-detail-neighbours">
						<h2>Most similar articles</h2>
						<ol>
							{#each nsArticle.nearest_pubmed_ids.slice(0, 10) as nid (nid)}
								{@const title = nsNeighborTitles.get(nid)}
								<li>
									<a
										href={`${base}/abstract/${nid}/`}
										data-testid="neuroscape-detail-neighbour-link"
									>
										<span class="nid">PMID {nid}</span>
										{#if title}
											<span class="ntitle">{title}</span>
										{/if}
									</a>
								</li>
							{/each}
						</ol>
					</aside>
				{/if}
			</article>
		{/if}
	</div>
{:else}
	<!-- OHBM 2026 permalink page — byte-identical to the pre-Stage-15
	     shape; the {#if SITE_MODE === 'neuroscape'} branch above is
	     dead-code-eliminated by Vite in the ohbm2026 build. -->
	<div class="permalink-page">
		<nav class="back">
			<a href={`${base}/`}>← all abstracts</a>
			<div class="permalink-search">
				<SearchBar abstractsByPosterId={abstractsById} />
			</div>
		</nav>

		{#if !loaded}
			<p class="status">Loading…</p>
		{:else if unknown}
			<section class="not-found" data-testid="abstract-not-found">
				<h1>No abstract with poster id <code>{posterIdParam}</code></h1>
				<p>
					The poster id in this URL doesn't match any accepted abstract in the current data
					package. It may have been re-assigned by the program, or the data package may not be
					deployed yet.
				</p>
			</section>
		{:else if abstractRecord}
			<DetailPanel
				abstract={abstractRecord}
				{authorsById}
				{abstractsById}
				dismissable={false}
				mode="permalink"
			/>
		{/if}
	</div>
{/if}

<style>
	.permalink-page {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		width: 100%;
	}
	.back {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.back a {
		color: #2c5fa3;
		text-decoration: none;
		font-size: 0.9rem;
	}
	.back a:hover {
		text-decoration: underline;
	}
	.permalink-search {
		flex: 1 1 14rem;
		min-width: 12rem;
		max-width: 28rem;
	}
	.not-found {
		background: #fff8f8;
		border: 1px solid #f0c0c0;
		border-radius: 6px;
		padding: 1rem;
	}
	.not-found h1 {
		margin: 0 0 0.5rem;
		font-size: 1.1rem;
	}
	.status {
		color: #888;
		font-style: italic;
	}
	code {
		background: #f4f4f4;
		padding: 0 0.25rem;
		border-radius: 3px;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}

	/* === NeuroScape detail page styles === */
	.ns-article {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		max-width: 50rem;
		width: 100%;
	}
	.ns-title {
		margin: 0;
		font-size: 1.4rem;
		line-height: 1.35;
		font-weight: 600;
	}
	.ns-meta {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
		gap: 0.75rem 1.5rem;
		margin: 0.6rem 0 0;
	}
	.ns-meta > div {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.ns-meta dt {
		color: var(--text-muted);
		font-size: 0.78rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		margin: 0;
	}
	.ns-meta dd {
		margin: 0;
		font-size: 0.95rem;
	}
	.cluster-swatch {
		display: inline-block;
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 2px;
		margin-right: 0.4rem;
		vertical-align: middle;
		border: 1px solid var(--border);
	}
	.ns-actions {
		margin-top: 0.6rem;
	}
	.show-on-atlas {
		display: inline-block;
		padding: 0.4rem 0.85rem;
		border-radius: 4px;
		background: var(--accent);
		color: var(--accent-text);
		text-decoration: none;
		font-size: 0.92rem;
		font-weight: 500;
	}
	.show-on-atlas:hover {
		filter: brightness(1.05);
	}
	.neighbours {
		margin-top: 0.5rem;
		border-top: 1px solid var(--border);
		padding-top: 0.8rem;
	}
	.neighbours h2 {
		margin: 0 0 0.5rem;
		font-size: 0.95rem;
		font-weight: 600;
	}
	.neighbours ol {
		margin: 0;
		padding-left: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.neighbours a {
		display: inline-flex;
		gap: 0.5rem;
		align-items: baseline;
		text-decoration: none;
		color: var(--text);
		font-size: 0.9rem;
	}
	.neighbours .nid {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		font-size: 0.82rem;
		min-width: 5.5rem;
	}
	.neighbours a:hover .ntitle {
		text-decoration: underline;
	}
</style>
