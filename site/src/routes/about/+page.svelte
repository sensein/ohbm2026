<script lang="ts">
	import { base } from '$app/paths';

	let openStages: Record<string, boolean> = {};
	function toggle(k: string) {
		openStages = { ...openStages, [k]: !openStages[k] };
	}

	// Curated references the about page links out to. Each entry MUST point
	// at a real, accessible page; the planned `link_check.py` will HEAD-check
	// these at build time once it lands (T085–T088). Until then, treat this
	// list as the single source of truth for "things to verify before deploy".
	const references = {
		oxford: {
			title: 'Oxford Abstracts — GraphQL API documentation',
			url: 'https://app.oxfordabstracts.com/'
		},
		umap: {
			title: 'McInnes, Healy & Melville (2018) — UMAP: Uniform Manifold Approximation and Projection',
			url: 'https://arxiv.org/abs/1802.03426'
		},
		leiden: {
			title: 'Traag, Waltman & van Eck (2019) — Leiden algorithm for community detection',
			url: 'https://www.nature.com/articles/s41598-019-41695-z'
		},
		hdbscan: {
			title: 'McInnes & Healy (2017) — HDBSCAN: hierarchical density-based clustering',
			url: 'https://joss.theoj.org/papers/10.21105/joss.00205'
		},
		minilm: {
			title: 'Wang et al. (2020) — MiniLM: deep self-attention distillation',
			url: 'https://arxiv.org/abs/2002.10957'
		},
		eco: {
			title: 'Evidence and Conclusion Ontology (ECO)',
			url: 'https://evidenceontology.org/'
		},
		openalex: {
			title: 'OpenAlex — open catalog of scholarly works',
			url: 'https://openalex.org/'
		},
		neuroscape_repo: {
			title: 'NeuroScape — code repository',
			url: 'https://github.com/sensein/neuroscape'
		},
		neuroscape_paper: {
			title:
				'Vali Tehrani et al. (2024) — NeuroScape: a domain-specific embedding for neuroscience abstracts (Aperture Neuro)',
			url: 'https://apertureneuro.org/article/124574-neuroscape-a-domain-specific-embedding-for-neuroscience-abstracts'
		},
		repo: {
			title: 'OHBM 2026 Atlas — source repository',
			url: 'https://github.com/sensein/ohbm2026'
		}
	};
</script>

<svelte:head>
	<title>About · OHBM 2026 Atlas</title>
</svelte:head>

<div class="about-page">
	<nav class="back"><a href={`${base}/`}>← back to atlas</a></nav>

	<header>
		<h1>About the OHBM 2026 Atlas</h1>
		<p class="lead">
			A search-and-browse interface for every accepted OHBM 2026 abstract. Each abstract
			is the submitter's own text; everything else on the site — clusters, related-abstract
			suggestions, figure interpretations, claim extractions — is computed from those
			abstracts by an automated pipeline. The pipeline is open-source and reproducible.
		</p>
	</header>

	<section class="overview">
		<p>
			Reading 3,000+ abstracts to find the ones you care about isn't realistic for most
			people. This atlas tries to make that browsable: a free-text + faceted search, a
			2D + 3D map of the corpus coloured by topic cluster, AI-extracted highlights of each
			abstract's claims and figures, and a lightweight saved-list export.
		</p>
		<p>
			The pipeline runs in five stages, listed below. Click each one to see how it works.
			Surfaces that were authored or interpreted by an LLM (figure interpretations,
			extracted claims, LLM-grouped topic-cluster titles) carry an
			<span class="ai-pill-demo">✨ AI</span> pill in the detail panel so the
			provenance is always visible.
		</p>
	</section>

	{#each [
		{ key: 'fetch', label: 'Stage 1 — Fetch & normalise (Oxford Abstracts → JSON)' },
		{ key: 'enrich', label: 'Stage 2 — AI enrichment (figures + claims + references)' },
		{ key: 'embed', label: 'Stage 3 — Embeddings (5 models × per-section)' },
		{ key: 'analyse', label: 'Stage 4 — Communities + clusters + UMAP' },
		{ key: 'ui', label: 'Stage 6 — This site' }
	] as stage (stage.key)}
		<section class="stage" data-testid={`about-stage-${stage.key}`}>
			<button
				type="button"
				class="stage-header"
				on:click={() => toggle(stage.key)}
				aria-expanded={!!openStages[stage.key]}
			>
				<span class="caret">{openStages[stage.key] ? '▾' : '▸'}</span>
				<span class="stage-label">{stage.label}</span>
			</button>
			{#if openStages[stage.key]}
				<div class="stage-body">
					{#if stage.key === 'fetch'}
						<p>
							We pull the accepted-abstract corpus from the
							<a href={references.oxford.url} target="_blank" rel="noopener noreferrer">
								Oxford Abstracts GraphQL API</a
							>, paginating through every accepted submission. Each record carries
							its program-assigned <em>poster id</em>, authors + affiliations,
							submitter-typed abstract sections (introduction / methods / results /
							conclusion), and the answers to the submission-form "extra questions"
							that drive our facets (methods, study type, population, etc.). Withdrawn
							submissions never reach this site — they're filtered out at this stage.
						</p>
					{:else if stage.key === 'enrich'}
						<p>
							Each abstract is passed to an LLM (currently <code>gpt-5.4-mini</code>) twice:
							once to extract structured <em>claims</em> with the
							<a href={references.eco.url} target="_blank" rel="noopener noreferrer">
								Evidence and Conclusion Ontology</a
							> annotating each piece of evidence, and once per figure to produce a
							written <em>interpretation</em>. Both outputs are cached by content hash so
							re-runs only pay for changed records. References are split out of the
							submitter's text via the same LLM, then resolved to canonical DOIs via
							<a href={references.openalex.url} target="_blank" rel="noopener noreferrer">
								OpenAlex</a
							>.
						</p>
						<p>
							These two surfaces — figure interpretations and claims — are the only
							pieces of the site that are LLM-written. They're always tagged
							<span class="ai-pill-demo">✨ AI</span> with the model identifier in the
							tooltip so readers can decide how much to trust them. Verbatim
							submitter content (abstract sections, topic dropdowns, methods
							checklists, authors) carries no such pill — that text is theirs.
						</p>
					{:else if stage.key === 'embed'}
						<p>
							We compute sentence-level embeddings for every abstract using five
							different encoder families: a public general-purpose model
							(<a href={references.minilm.url} target="_blank" rel="noopener noreferrer">
								MiniLM-L6</a
							>), a domain-specific biomedical model (PubMedBERT), two commercial APIs
							(OpenAI, Voyage), and our project-specific NeuroScape model
							(<a
								href={references.neuroscape_paper.url}
								target="_blank"
								rel="noopener noreferrer">Aperture Neuro paper</a
							>,
							<a href={references.neuroscape_repo.url} target="_blank" rel="noopener noreferrer">
								code</a
							>). Embeddings are computed per section (title / introduction /
							methods / results / conclusion / claims) and composed into bundles at
							read time, so the UI can show the same corpus through different "lenses".
						</p>
					{:else if stage.key === 'analyse'}
						<p>
							For each (model, input) combination we build a UMAP layout
							(<a href={references.umap.url} target="_blank" rel="noopener noreferrer">
								McInnes 2018</a
							>) in 2D and 3D, run Leiden community detection
							(<a href={references.leiden.url} target="_blank" rel="noopener noreferrer">
								Traag 2019</a
							>) on the nearest-neighbour graph to find topic clusters, and HDBSCAN
							(<a href={references.hdbscan.url} target="_blank" rel="noopener noreferrer">
								McInnes 2017</a
							>) for a density-based view. An LLM names each community by reading a
							representative sample of titles from inside it; those names are what
							you see in the "Cluster (current map)" facet and in the UMAP hover
							tooltips.
						</p>
						<p>
							The same per-(model, input) bundle drives the "Most similar" and "Most
							different" lists in the detail panel — we precompute the 10 nearest +
							10 farthest abstracts per record per cell. The detail panel then
							aggregates across all 15 cells so the similar-list reflects every
							"lens" rather than just the currently-selected one.
						</p>
					{:else if stage.key === 'ui'}
						<p>
							This site is a static SvelteKit app deployed to GitHub Pages. The data
							package is a single gzipped tarball fetched from a stable CDN URL at
							page load — no server, no database, no per-query backend round-trip.
							Lexical typo-tolerant search runs in the main thread; semantic search
							runs in a Web Worker using
							<a href={references.minilm.url} target="_blank" rel="noopener noreferrer">
								MiniLM-L6</a
							> ONNX through transformers.js, against an int8-quantised vector matrix
							also shipped in the tarball.
						</p>
						<p class="muted">
							Source: <a href={references.repo.url} target="_blank" rel="noopener noreferrer"
								>github.com/sensein/ohbm2026</a
							>. Build provenance is in the footer of every page.
						</p>
					{/if}
				</div>
			{/if}
		</section>
	{/each}
</div>

<style>
	.about-page {
		max-width: 56rem;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1rem 0;
	}
	.back a {
		color: var(--accent);
		text-decoration: none;
		font-size: 0.9rem;
	}
	.back a:hover {
		text-decoration: underline;
	}
	header h1 {
		margin: 0 0 0.5rem;
		font-size: 1.4rem;
		color: var(--text);
	}
	.lead {
		font-size: 1rem;
		line-height: 1.55;
		color: var(--text);
	}
	.overview p {
		font-size: 0.95rem;
		line-height: 1.6;
		color: var(--text);
	}
	.stage {
		border-top: 1px solid var(--border);
		padding-top: 0.5rem;
	}
	.stage-header {
		all: unset;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 0.4rem;
		width: 100%;
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--text);
	}
	.stage-header:hover {
		color: var(--accent);
	}
	.caret {
		font-size: 0.75rem;
		color: var(--text-muted);
		width: 0.7rem;
	}
	.stage-label {
		flex: 1;
	}
	.stage-body {
		padding: 0.6rem 0 0.2rem 1.5rem;
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		font-size: 0.9rem;
		line-height: 1.6;
		color: var(--text);
	}
	.stage-body a {
		color: var(--accent);
	}
	.ai-pill-demo {
		font-size: 0.7rem;
		font-weight: 600;
		color: var(--accent-soft-text);
		background: var(--accent-soft-bg);
		padding: 0.05rem 0.4rem;
		border-radius: 999px;
		letter-spacing: 0.04em;
	}
	.muted {
		color: var(--text-muted);
		font-size: 0.85rem;
	}
	code {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.85em;
		background: var(--bg-sunken);
		padding: 0 0.3rem;
		border-radius: 3px;
	}
</style>
