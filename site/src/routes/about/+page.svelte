<script lang="ts">
	import { base } from '$app/paths';
	import { SITE_MODE } from '$lib/site_mode';

	let openStages: Record<string, boolean> = {};
	let openTldrs: Record<string, boolean> = {};
	function toggle(k: string) {
		openStages = { ...openStages, [k]: !openStages[k] };
	}
	function toggleTldr(k: string) {
		openTldrs = { ...openTldrs, [k]: !openTldrs[k] };
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
			title: 'Senden (2026) — NeuroScape code repository (CCN Maastricht)',
			url: 'https://github.com/ccnmaastricht/NeuroScape'
		},
		neuroscape_paper: {
			title:
				'Senden (2026) — The evolving landscape of neuroscience (Aperture Neuro)',
			url: 'https://apertureneuro.org/article/156380-the-evolving-landscape-of-neuroscience'
		},
		repo: {
			title: 'OHBM 2026 Atlas — source repository',
			url: 'https://github.com/sensein/ohbm2026'
		}
	};
</script>

<svelte:head>
	{#if SITE_MODE === 'atlas-root'}
		<title>About · Abstract Atlas</title>
	{:else if SITE_MODE === 'neuroscape'}
		<title>About · NeuroScape PubMed Atlas</title>
	{:else}
		<title>About · OHBM 2026 Atlas</title>
	{/if}
</svelte:head>

<div class="about-page">
	<nav class="back"><a href={`${base}/`}>← back to atlas</a></nav>

	<header>
		{#if SITE_MODE === 'atlas-root'}
			<h1>About Abstract Atlas</h1>
		{:else if SITE_MODE === 'neuroscape'}
			<h1>About the NeuroScape PubMed Atlas</h1>
		{:else}
			<h1>About the OHBM 2026 Atlas</h1>
		{/if}
		<p class="lead">
			A search-and-browse interface for every accepted OHBM 2026 abstract. Each abstract
			is the submitter's own text; everything else on the site — clusters, related-abstract
			suggestions, figure interpretations, claim extractions — is computed from those
			abstracts by an automated pipeline. The pipeline is open-source and reproducible.
		</p>
	</header>

	<section class="overview">
		{#if SITE_MODE === 'atlas-root'}
			<p>
				The cross-conference landing page — currently Abstract Atlas — puts the
				3,240 OHBM 2026 abstracts in the context of a much larger neuroscience
				literature snapshot: NeuroScape PubMed, ~461,000 articles from 1999–2023
				embedded with the NeuroScape Stage-2 model and clustered into 175 topical
				groups. Both layers share the same UMAP, so OHBM 2026 work appears as an
				overlay on the broader landscape; a binary toggle hides the overlay if
				you only want to browse the PubMed backdrop. From here you can drop into
				either site directly (OHBM 2026 ·
				<a href="../neuroscape/" rel="external">NeuroScape PubMed</a>);
				the subsites are independently rebuildable and link back to this hub.
			</p>
		{:else if SITE_MODE === 'neuroscape'}
			<p>
				A reduced-functionality browse of the NeuroScape PubMed 1999–2023
				corpus — ~461,000 article titles + 175 topical clusters from
				<a href={references.neuroscape_paper.url} target="_blank" rel="noopener noreferrer">Senden (2026)</a>'s
				NeuroScape Stage-2 model. Each detail page fetches PubMed metadata
				live (authors, journal, abstract body, DOI) from NCBI E-utilities; no
				article bodies are stored locally. Use the
				<a href="../" rel="external">Abstract Atlas</a> landing page to see
				OHBM 2026 abstracts overlaid on this same UMAP.
			</p>
		{:else}
			<p>
				Reading 3,000+ abstracts to find the ones you care about isn't realistic for most
				people. This atlas tries to make that browsable: a free-text + faceted search, a
				2D + 3D map of the corpus coloured by topic cluster, AI-extracted highlights of each
				abstract's claims and figures, and a lightweight saved-list export.
			</p>
		{/if}
		<p>
			The pipeline runs in five stages, listed below. Click each one to see how it works.
			Surfaces that were authored or interpreted by an LLM (figure interpretations,
			extracted claims, LLM-grouped topic-cluster titles) carry an
			<span class="ai-pill-demo">✨ AI</span> pill in the detail panel so the
			provenance is always visible.
		</p>
		<p>
			Beyond the per-conference pipeline, the
			<strong>Abstract Atlas</strong> cross-conference landing page projects this corpus into
			a much larger neuroscience embedding (NeuroScape PubMed, ~461k articles
			1999–2023, 175 clusters) so OHBM 2026 work can be browsed in the context of
			the broader literature. The NeuroScape PubMed atlas itself is the second
			sibling subsite, with the same UMAP and clusters but no OHBM overlay. All
			three subsites — Abstract Atlas (root), OHBM 2026 (this site), and
			NeuroScape PubMed — are independently rebuildable; the Abstract Atlas
			landing is the only hub that knows about all of them.
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
						<button
							type="button"
							class="tldr-toggle"
							on:click={() => toggleTldr(stage.key)}
							aria-expanded={!!openTldrs[stage.key]}
						>
							<span class="caret">{openTldrs[stage.key] ? '▾' : '▸'}</span>
							Technical details
						</button>
						{#if openTldrs[stage.key]}
							<aside class="tldr">
								<ul>
									<li>
										<strong>Source.</strong> <code>src/ohbm2026/fetch/graphql_api.py</code>
										exports three queries: <code>ABSTRACT_IDS_QUERY</code> (accepted
										ids), <code>WITHDRAWN_IDS_QUERY</code> (deny-list), and
										<code>ABSTRACT_CONTENTS_QUERY</code> (full record incl.
										<code>program_code</code> + <code>program_sessions_submissions</code>).
										An exponential-backoff retry wrapper handles upstream 5xx /
										429 without crashing the run.
									</li>
									<li>
										<strong>Contract-checking.</strong> Before each fetch the
										orchestrator (<code>fetch/stage.py</code>) runs
										<code>INTROSPECTION_QUERY</code> and feeds the result to
										<code>fetch/schema_diff.py</code>. Field-level diff is tiered
										HARD / SOFT / INFORMATIONAL; a HARD-tier change (e.g. a
										previously non-null field flips to null) aborts the run with
										a typed <code>SchemaContractError</code> so we never silently
										consume drift.
									</li>
									<li>
										<strong>Normalisation.</strong> <code>fetch/assets.py::normalize_abstract</code>
										maps <code>program_code</code> → <code>poster_id</code> (FR-002),
										flattens <code>program_sessions_submissions</code> →
										<code>program_sessions</code>, and runs
										<code>advance_record_state</code> as a per-record state-machine
										validator. Records without a poster_id are skipped with a
										logged count.
									</li>
									<li>
										<strong>Figure assets.</strong> Inline figures stream into
										<code>data/primary/assets/&lt;poster_id&gt;_&lt;sha12&gt;.&lt;ext&gt;</code>
										via the <code>asset_stem</code> hash; re-runs detect identical
										content and skip the download.
									</li>
									<li>
										<strong>Resumability.</strong> Checkpoint JSON at
										<code>data/cache/fetch_abstracts/checkpoint__&lt;state-key&gt;.json</code>;
										on resume we union the already-fetched id-set with the live id
										list and only fetch the diff. State-key is a deterministic hash
										of the query set + GraphQL endpoint version.
									</li>
									<li>
										<strong>Outputs.</strong> <code>data/primary/abstracts.json</code>
										(accepted; consumed by every downstream stage),
										<code>abstracts_withdrawn.json</code> (deny-list for invariant
										3), and the live schema snapshot at
										<code>data/primary/schema__&lt;state-key&gt;.json</code> for the
										next run's diff base.
									</li>
								</ul>
							</aside>
						{/if}
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
						<button
							type="button"
							class="tldr-toggle"
							on:click={() => toggleTldr(stage.key)}
							aria-expanded={!!openTldrs[stage.key]}
						>
							<span class="caret">{openTldrs[stage.key] ? '▾' : '▸'}</span>
							Technical details
						</button>
						{#if openTldrs[stage.key]}
							<aside class="tldr">
								<ul>
									<li>
										<strong>Orchestrator.</strong> <code>src/ohbm2026/enrich/stage.py</code>
										walks the accepted corpus, dispatches each record to three
										component runners (figures, claims, references), and atomically
										writes <code>data/primary/abstracts_enriched.sqlite</code> via
										<code>enrich/storage.py::EnrichedCorpusWriter</code> (temp →
										rename). Per-row payload is zlib(JSON) so the 3,243-record DB
										stays around 80 MB.
									</li>
									<li>
										<strong>Claims (agentic).</strong>
										<code>enrich/stage2_claims.py</code> calls the OpenAI Responses
										API on <code>gpt-5.4-mini</code> with three function tools the
										model may invoke iteratively:
										<code>verify_source_quote</code> (lexically verifies the
										evidence quote against the abstract),
										<code>lookup_eco_code</code> (resolves the evidence to one of
										the 9 top-level ECO v1 codes in
										<code>data/eco_top_codes.json</code>), and
										<code>dedupe_check</code> (rejects near-duplicate claims). Output
										is Pydantic-validated; invalid rows are dropped with a logged
										reason. Cache key = <code>sha256(manuscript || model_id || vocabulary_version)</code>
										under <code>data/cache/claim_analysis/</code>.
									</li>
									<li>
										<strong>Figures.</strong> <code>enrich/stage2_figures.py</code>
										groups all of an abstract's figures into a single vision call.
										Locally each PNG/JPEG is re-encoded to JPEG-q85 at max 1024 px
										via <code>enrich/image_quality.py</code>, which also returns a
										four-field probe (<code>laplacian_variance</code>,
										<code>mean_brightness</code>,
										<code>compression_ratio</code>,
										<code>native_max_dim</code>) — these are stored alongside the
										interpretation so reviewers can see the model's input quality.
										Cache key = <code>sha256(image_blob || prompt || model_id)</code>
										under <code>data/cache/figure_analysis/</code>.
									</li>
									<li>
										<strong>Flex-tier retry pattern.</strong>
										<code>enrich/flex_tier.py</code> wraps both LLM calls in
										"1 flex attempt + 1 standard retry" (default timeouts 120 s
										for figures, 180 s for claims). Flex-tier reduces $$$ on the
										happy path; the standard retry catches the
										<code>ContextLengthExceededError</code> /
										timeout / transient-5xx tail without crashing the run.
									</li>
									<li>
										<strong>References.</strong> Per-record references-block text
										→ LLM-assisted split into individual citation candidates →
										lexical-match each candidate back to the source text (drops
										hallucinated citations) → DOI lookup, then PMID, then
										<a href={references.openalex.url} target="_blank" rel="noopener noreferrer">
											OpenAlex
										</a> title search, with a Semantic Scholar fallback. The LLM
										only HELPS split — the canonical metadata comes from the
										lookup, which is why references do NOT carry the
										<span class="ai-pill-demo">✨ AI</span> pill in the UI.
										Cached under
										<code>data/cache/reference_metadata/&lt;cache-key&gt;.json</code>.
									</li>
									<li>
										<strong>Provenance.</strong> A run emits
										<code>data/provenance/abstracts_enrich_provenance__&lt;state-key&gt;.json</code>
										with the per-component model ids, cache hit/miss counts, run
										wall time, and the cmdline that produced it.
									</li>
								</ul>
							</aside>
						{/if}
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
						<button
							type="button"
							class="tldr-toggle"
							on:click={() => toggleTldr(stage.key)}
							aria-expanded={!!openTldrs[stage.key]}
						>
							<span class="caret">{openTldrs[stage.key] ? '▾' : '▸'}</span>
							Technical details
						</button>
						{#if openTldrs[stage.key]}
							<aside class="tldr">
								<ul>
									<li>
										<strong>Per-component bundles.</strong> Every abstract is
										embedded separately for <code>title</code>,
										<code>introduction</code>, <code>methods</code>,
										<code>results</code>, <code>conclusion</code>, and
										<code>claims</code>. Each (model, component) pair produces a
										bundle directory
										<code>data/outputs/embeddings/&lt;model_key&gt;/&lt;component&gt;__&lt;state-key&gt;/</code>
										containing <code>vectors.npy</code> (float32, L2-normalised),
										<code>ids.npy</code>, <code>metadata.json</code>, and
										<code>provenance.json</code>. The state-key suffix lets historical
										versions coexist on disk; the manifest pins the active one.
									</li>
									<li>
										<strong>Per-abstract cache.</strong>
										<code>data/cache/embeddings/&lt;model_key&gt;/&lt;cache-key&gt;.json</code>;
										key = <code>sha256(text || model_id || model_version)</code>. A
										re-run only pays the API/GPU cost for the records whose source
										text actually changed.
									</li>
									<li>
										<strong>Composition at read time.</strong>
										<code>ohbm2026.embed.compose_recipe([components], model_key=...)</code>
										produces a corpus matrix on demand — for instance the SPA's
										"abstract" lens is
										<code>compose_recipe(['title','introduction','methods','results','conclusion'])</code>
										meaned per record. No fixed-shape "abstract" embedding is
										persisted; the recipe is the contract.
									</li>
									<li>
										<strong>Token-aware chunking.</strong> Long sections are split
										along sentence boundaries (BlingFire) into model-token budgets
										and the chunk embeddings are mean-pooled per section. NeuroScape
										wraps a public base in a learned Stage-2 transform — see the
										<a href={references.neuroscape_paper.url} target="_blank" rel="noopener noreferrer">
											Aperture Neuro paper
										</a> and the
										<a href={references.neuroscape_repo.url} target="_blank" rel="noopener noreferrer">
											code
										</a>.
									</li>
									<li>
										<strong>Models.</strong>
										<code>voyage-3-lite</code> /
										<a href={references.minilm.url} target="_blank" rel="noopener noreferrer">
											<code>sentence-transformers/all-MiniLM-L6-v2</code>
										</a> /
										<code>text-embedding-3-small</code> /
										<code>microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract</code> /
										<code>neuroscape</code> (Stage-2 transform).
									</li>
									<li>
										<strong>SPA wire format.</strong> The MiniLM corpus matrix used
										for in-browser semantic search is composed of
										{`{intro, methods, results, conclusion}`}, L2-renormalised, then
										int8-quantised with a global scale = <code>127 / max_abs</code>.
										The buffer ships as <code>data/search/minilm_vectors.bin</code>
										with a sidecar JSON declaring <code>shape</code>,
										<code>scale</code>, and <code>cosine_recovery_mae</code> (≤ 0.005
										invariant — current build is 0.00057). The buffer is transferred
										zero-copy into a Web Worker on first paint.
									</li>
								</ul>
							</aside>
						{/if}
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
						<button
							type="button"
							class="tldr-toggle"
							on:click={() => toggleTldr(stage.key)}
							aria-expanded={!!openTldrs[stage.key]}
						>
							<span class="caret">{openTldrs[stage.key] ? '▾' : '▸'}</span>
							Technical details
						</button>
						{#if openTldrs[stage.key]}
							<aside class="tldr">
								<ul>
									<li>
										<strong>Orchestrator.</strong>
										<code>ohbmcli analyze-matrix</code> (wraps
										<code>analyze/runners.py</code>) fans out across 48 (model,
										input, recipe) bundles on a joblib pool. Each bundle's
										per-record output rolls up into a single
										<code>data/outputs/analysis/annotations__&lt;state-key&gt;.{`{parquet,sqlite}`}</code>;
										the SQLite is what Stage 6's data-package builder reads.
									</li>
									<li>
										<strong>kNN graph.</strong>
										<code>analyze/communities.py::build_faiss_knn</code> L2-normalises
										the corpus matrix, builds a FAISS <code>IndexFlatIP</code>
										(exact inner-product on the unit sphere → cosine), runs a
										batched search, masks each node's own hit. Default
										<code>k = 15</code>. Falls back to a sklearn cosine-kNN if
										<code>faiss-cpu</code> isn't installed.
									</li>
									<li>
										<strong>Leiden community detection.</strong> CPM partition
										(<a href={references.leiden.url} target="_blank" rel="noopener noreferrer">
											Traag 2019
										</a>) via <code>leidenalg</code>; resolution chosen by a 20-point
										sweep over <code>[0.001, 0.1]</code> (geometric spacing), picking
										the modularity plateau where the partition is stable. The
										resulting <code>community_id</code> per abstract is what the
										UMAP colour-codes; <code>-1</code> = unclustered.
									</li>
									<li>
										<strong>UMAP layout.</strong>
										<code>analyze/umap.py</code> runs both 2D and 3D layouts with
										<code>n_neighbors = 15</code>, <code>min_dist = 0.1</code>,
										<code>metric = cosine</code>, <code>random_state = 42</code>.
										Outputs <code>umap2d_coords.npy</code> + <code>umap3d_coords.npy</code>
										per bundle.
									</li>
									<li>
										<strong>HDBSCAN topic clusters.</strong>
										<code>analyze/topic_clusters.py</code> reuses the UMAP layout's
										2D coordinates (with its own tighter parameters
										<code>n_neighbors = 15</code>,
										<code>min_dist = 0.0</code>) and feeds them to HDBSCAN with
										<code>min_cluster_size = 10</code>. Falls through to a
										constant-label partition when fewer than that survive.
										<code>topic_cluster_id = -1</code> means HDBSCAN-noise.
									</li>
									<li>
										<strong>Cluster naming.</strong> Hybrid: spaCy noun-chunk
										keyword extraction → class-TF-IDF over the cluster's titles +
										abstracts → an LLM grouping pass that produces
										<code>{`{title, description, focus}`}</code> per cluster. These
										are the only Stage-4 surface that carries the
										<span class="ai-pill-demo">✨ AI</span> pill in the UI.
									</li>
									<li>
										<strong>Neighbour pre-compute.</strong>
										<code>scripts/compute_neighbors.py</code> reads each bundle's
										<code>reference_matrix.npy</code> (the canonical embedding the
										community detection ran on), computes pairwise cosine
										distance, and bakes in <code>k = 10</code> nearest + 10
										farthest per abstract into
										<code>data/outputs/analysis/&lt;cell&gt;/projections__&lt;state-key&gt;/neighbors__&lt;state-key&gt;/*.npy</code>.
										The detail panel aggregates this across all 15 cells for the
										"Most similar / Most different" rails.
									</li>
									<li>
										<strong>Output shape.</strong> Every per-abstract row carries
										<code>community_id</code>, <code>topic_cluster_id</code>,
										<code>umap2d</code>, <code>umap3d</code>, and (NeuroScape
										only) <code>neuroscape_cluster_id</code> +
										<code>neuroscape_cluster_distance</code>. The Stage 6 builder
										projects this wide table into per-cell shards keyed by
										<code>&lt;model&gt;_&lt;input&gt;</code>.
									</li>
								</ul>
							</aside>
						{/if}
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
						<button
							type="button"
							class="tldr-toggle"
							on:click={() => toggleTldr(stage.key)}
							aria-expanded={!!openTldrs[stage.key]}
						>
							<span class="caret">{openTldrs[stage.key] ? '▾' : '▸'}</span>
							Technical details
						</button>
						{#if openTldrs[stage.key]}
							<aside class="tldr">
								<ul>
									<li>
										<strong>Stack.</strong> SvelteKit 2 + Vite 6 + Svelte 5,
										<code>@sveltejs/adapter-static</code> with
										<code>fallback: '404.html'</code> and
										<code>paths.base = $env.BASE_PATH</code>. Plotly via
										<code>plotly.js-gl3d-dist-min</code> (lazy-loaded; only the
										gl3d bundle has scatter3d). Theme handling via a
										localStorage-backed Svelte store with a system-pref watcher.
									</li>
									<li>
										<strong>Data delivery.</strong> A single gzipped tarball at
										<code>VITE_DATA_PACKAGE_URL</code> (Dropbox shared link rewritten
										to <code>dl.dropboxusercontent.com</code> at runtime to avoid the
										<code>www.dropbox.com</code> 302 that drops CORS). Body is
										decoded via native <code>DecompressionStream('gzip')</code> + a
										hand-rolled ~50-line tar parser
										(<code>site/src/lib/data_package.ts</code>) into a
										<code>Map&lt;path, JsonValue | Uint8Array&gt;</code> resident in
										memory.
									</li>
									<li>
										<strong>Lexical search.</strong>
										<code>site/src/lib/filter.ts</code> builds an in-memory inverted
										index (lazy-built per <code>WeakMap&lt;abstracts, index&gt;</code>)
										over title + topics + methods + author names + facet values +
										section bodies (NFD-folded + lower-cased + length-≥-2 tokens).
										Query token → all corpus tokens within Damerau-Levenshtein ≤
										<code>thresholdFor(token)</code> (<code>&lt;4</code> chars: 0;
										<code>4-6</code>: 1; <code>≥7</code>: 2). Multi-token queries
										AND-intersect their per-token postings. Returns
										<code>{`{ ids, exactness }`}</code> so the result list can
										rank exact-match abstracts above fuzzy/proximal hits.
									</li>
									<li>
										<strong>Semantic search.</strong>
										<code>site/src/lib/workers/semantic.worker.ts</code> is a
										Web Worker that loads
										<code>Xenova/all-MiniLM-L6-v2</code> via
										<code>@xenova/transformers</code> (HF CDN, browser-cached),
										receives the int8 vector buffer via zero-copy
										<code>postMessage(..., [buffer])</code>, then per query:
										mean-pooled + L2-normalised embedding of the query
										(384-d), dot-product against every row, dequantised by
										<code>1 / scale</code>, clamped to <code>[-1, 1]</code>,
										sorted to top-K. The main-thread facade
										(<code>site/src/lib/search/semantic.ts</code>) exposes a
										<code>semanticStatus</code> store the toggle button reads.
									</li>
									<li>
										<strong>Filter pipeline.</strong>
										<code>filteredIds = $cartOnly ? cartIds : (searchIds ∩ lasso ∩
										facetIds ∩ authorChipIds)</code>. Saved-only is a dominant
										filter (overrides the other three) so the user always sees
										their full saved set; the other stores remain in their state
										so toggling Saved-only off restores them.
									</li>
									<li>
										<strong>UMAP.</strong> 2D scatter + 3D scatter3d in Plotly,
										coloured + shaped by <code>community_id</code> using Paul
										Tol's "bright" palette × 5 marker symbols (≈ 35 unique combos
										before any pair repeats — colour-vision-safe). The 3D camera
										is tracked via a <code>plotly_relayout</code> listener into a
										module-level <code>currentEye3D</code> so pause/zoom/orbit
										then unpause continues from the user's chosen camera. The
										focused abstract carries an over-sized open-circle halo trace
										drawn last so it pops above the cluster carpet on both 2D
										and 3D.
									</li>
									<li>
										<strong>Permalink direct-load.</strong> gh-pages serves the
										root <code>/404.html</code> for any URL it can't resolve. Ours
										is a hand-written SPA-redirect committed directly to the
										<code>gh-pages</code> branch: it detects the requested base
										path (<code>/pr-N</code> or root), stashes the full original
										path in <code>?spa=…</code> + <code>sessionStorage</code>
										(belt + suspenders), and replaces location with the SPA shell
										root. The layout's <code>onMount</code> pops the stash,
										strips the <code>?spa=…</code> with
										<code>history.replaceState</code>, and
										<code>{`goto(stash, { replaceState: true })`}</code>s to the deep
										link — passing the FULL stash (not the base-stripped form)
										because SvelteKit's <code>goto</code> treats
										<code>/path</code> as origin-absolute and would otherwise
										escape the SPA's scope.
									</li>
									<li>
										<strong>Deploy.</strong>
										<code>.github/workflows/deploy-ui.yml</code> publishes to
										gh-pages root via
										<code>peaceiris/actions-gh-pages@v3</code> on every push to
										<code>main</code>; <code>pr-preview.yml</code> declares
										<code>environment: pr-preview-&lt;N&gt;</code> so the URL
										surfaces in the PR's Deployments box (not a bot comment), and
										deploys to <code>gh-pages:pr-&lt;N&gt;/</code> with
										<code>BASE_PATH=/pr-&lt;N&gt;</code>. The tarball lives at a
										stable URL outside the repo (Dropbox shared link); the build
										step injects it as
										<code>VITE_DATA_PACKAGE_URL</code> + a sha256 var
										(<code>OHBM2026_UI_DATA_PACKAGE_SHA256</code>) for integrity.
									</li>
									<li>
										<strong>Validation.</strong> Every emitted shard validates
										against the LinkML schema at
										<code>specs/008-ui-rewrite/contracts/ui_data.linkml.yaml</code>.
										<code>scripts/validate_ui_data.sh</code> runs
										<code>linkml-validate</code> over each shard
										(<code>Manifest</code>, <code>AbstractsShard</code>,
										<code>AuthorsShard</code>, <code>EnrichmentShard</code>,
										<code>MinilmVectorsSidecar</code>, every CellShard / TopicShard
										/ NeighborsShard) — currently 68/68 pass. A re-generated data
										package whose shards validate against the same schema can be
										loaded by the site with zero code changes.
									</li>
									<li>
										<strong>Accessibility.</strong> Targeting WCAG 2.1 AA.
										<code>@axe-core/playwright</code> audits the home / about /
										abstract-permalink routes against the live production URL
										(<code>site/src/tests/e2e/a11y.spec.ts</code>) — critical +
										serious violations fail the test. Every
										<code>overflow-y: auto</code> scroll container carries
										<code>tabindex="0"</code> + a labelled
										<code>role="region"</code> so keyboard users can reach and
										scroll the cluster-membership grid, the related-abstracts
										rails, the facet option lists, and the cart drawer items.
										Theme + colour-vision-safe palette choices are documented in
										the Stage 4 deep-dive.
									</li>
								</ul>
							</aside>
						{/if}
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
	.tldr-toggle {
		all: unset;
		cursor: pointer;
		align-self: flex-start;
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--accent);
		padding: 0.3rem 0.45rem;
		border-radius: 4px;
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}
	.tldr-toggle:hover {
		background: var(--accent-soft-bg);
	}
	.tldr-toggle .caret {
		font-size: 0.7rem;
		color: var(--text-muted);
	}
	.tldr {
		background: var(--bg-sunken);
		border-left: 3px solid var(--accent);
		padding: 0.6rem 0.85rem;
		border-radius: 4px;
	}
	.tldr ul {
		margin: 0;
		padding-left: 1.1rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		font-size: 0.85rem;
		line-height: 1.55;
	}
	.tldr li {
		color: var(--text);
	}
	.tldr li strong {
		color: var(--accent);
		font-weight: 600;
	}
	.tldr code {
		background: var(--bg-elevated);
		padding: 0 0.25rem;
		border-radius: 3px;
		font-size: 0.85em;
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
