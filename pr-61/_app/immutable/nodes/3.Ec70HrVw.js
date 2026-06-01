import{a as r,c as He,f as i,s as M,e as F}from"../chunks/BKT_6NDN.js";import{e as Z,S as E,s as o}from"../chunks/C8vGhCzW.js";import{bm as _,ah as z,ae as re,$ as ne,Y as t,a_ as s,bc as a,ak as c,aO as n,aM as me,b3 as be}from"../chunks/Db9XsndZ.js";import{i as O}from"../chunks/B_uEPX93.js";import{h as Ue}from"../chunks/DdeDTspS.js";import{d as je}from"../chunks/CT4KpFBZ.js";var Fe=i('<a class="svelte-cwls5q"> </a>'),ze=i('<h1 class="svelte-cwls5q">About Abstract Atlas</h1>'),We=i('<h1 class="svelte-cwls5q">About the NeuroScape PubMed Atlas</h1>'),Ge=i('<h1 class="svelte-cwls5q">About the OHBM 2026 Atlas</h1>'),Ve=i(`<p class="lead svelte-cwls5q">A search-and-browse interface that places every accepted OHBM 2026 abstract in
				the context of a neuroscience-wide PubMed literature map. The OHBM abstracts are
				the submitters' own text; the clusters, related-abstract suggestions, figure
				interpretations, and claim extractions are computed by an automated pipeline. It
				is open-source and reproducible.</p>`),Ke=i(`<p class="lead svelte-cwls5q">A search-and-browse interface for the NeuroScape PubMed neuroscience corpus —
				~461,000 article titles from 1999–2023, clustered into 175 topical groups.
				Article metadata is fetched live from PubMed; the embedding + clusters come from
				the NeuroScape model. The atlas pipeline is open-source and reproducible.</p>`),Qe=i(`<p class="lead svelte-cwls5q">A search-and-browse interface for every accepted OHBM 2026 abstract. Each abstract
				is the submitter's own text; everything else on the site — clusters, related-abstract
				suggestions, figure interpretations, claim extractions — is computed from those
				abstracts by an automated pipeline. The pipeline is open-source and reproducible.</p>`),Je=i(`<p class="svelte-cwls5q">The cross-conference landing page — currently Abstract Atlas — puts the
				3,240 OHBM 2026 abstracts in the context of a much larger neuroscience
				literature snapshot: NeuroScape PubMed, ~461,000 articles from 1999–2023
				embedded with the NeuroScape Stage-2 model and clustered into 175 topical
				groups. Both layers share the same UMAP, so OHBM 2026 work appears as an
				overlay on the broader landscape; a binary toggle hides the overlay if
				you only want to browse the PubMed backdrop. From here you can drop into
				either site directly (OHBM 2026 · <a href="../neuroscape/" rel="external">NeuroScape PubMed</a>);
				the subsites are independently rebuildable and link back to this hub.</p>`),Ye=i(`<p class="svelte-cwls5q">A reduced-functionality browse of the NeuroScape PubMed 1999–2023
				corpus — ~461,000 article titles + 175 topical clusters from <a target="_blank" rel="noopener noreferrer">Senden (2026)</a>'s
				NeuroScape Stage-2 model. Each detail page fetches PubMed metadata
				live (authors, journal, abstract body, DOI) from NCBI E-utilities; no
				article bodies are stored locally. Use the <a href="../" rel="external">Abstract Atlas</a> landing page to see
				OHBM 2026 abstracts overlaid on this same UMAP.</p>`),Xe=i(`<p class="svelte-cwls5q">Reading 3,000+ abstracts to find the ones you care about isn't realistic for most
				people. This atlas tries to make that browsable: a free-text + faceted search, a
				2D + 3D map of the corpus coloured by topic cluster, AI-extracted highlights of each
				abstract's claims and figures, and a lightweight saved-list export.</p>`),Ze=i(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Source.</strong> <code class="svelte-cwls5q">src/ohbm2026/fetch/graphql_api.py</code> exports three queries: <code class="svelte-cwls5q">ABSTRACT_IDS_QUERY</code> (accepted
										ids), <code class="svelte-cwls5q">WITHDRAWN_IDS_QUERY</code> (deny-list), and <code class="svelte-cwls5q">ABSTRACT_CONTENTS_QUERY</code> (full record incl. <code class="svelte-cwls5q">program_code</code> + <code class="svelte-cwls5q">program_sessions_submissions</code>).
										An exponential-backoff retry wrapper handles upstream 5xx /
										429 without crashing the run.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Contract-checking.</strong> Before each fetch the
										orchestrator (<code class="svelte-cwls5q">fetch/stage.py</code>) runs <code class="svelte-cwls5q">INTROSPECTION_QUERY</code> and feeds the result to <code class="svelte-cwls5q">fetch/schema_diff.py</code>. Field-level diff is tiered
										HARD / SOFT / INFORMATIONAL; a HARD-tier change (e.g. a
										previously non-null field flips to null) aborts the run with
										a typed <code class="svelte-cwls5q">SchemaContractError</code> so we never silently
										consume drift.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Normalisation.</strong> <code class="svelte-cwls5q">fetch/assets.py::normalize_abstract</code> maps <code class="svelte-cwls5q">program_code</code> → <code class="svelte-cwls5q">poster_id</code> (FR-002),
										flattens <code class="svelte-cwls5q">program_sessions_submissions</code> → <code class="svelte-cwls5q">program_sessions</code>, and runs <code class="svelte-cwls5q">advance_record_state</code> as a per-record state-machine
										validator. Records without a poster_id are skipped with a
										logged count.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Figure assets.</strong> Inline figures stream into <code class="svelte-cwls5q">data/primary/assets/&lt;poster_id&gt;_&lt;sha12&gt;.&lt;ext&gt;</code> via the <code class="svelte-cwls5q">asset_stem</code> hash; re-runs detect identical
										content and skip the download.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Resumability.</strong> Checkpoint JSON at <code class="svelte-cwls5q">data/cache/fetch_abstracts/checkpoint__&lt;state-key&gt;.json</code>;
										on resume we union the already-fetched id-set with the live id
										list and only fetch the diff. State-key is a deterministic hash
										of the query set + GraphQL endpoint version.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Outputs.</strong> <code class="svelte-cwls5q">data/primary/abstracts.json</code> (accepted; consumed by every downstream stage), <code class="svelte-cwls5q">abstracts_withdrawn.json</code> (deny-list for invariant
										3), and the live schema snapshot at <code class="svelte-cwls5q">data/primary/schema__&lt;state-key&gt;.json</code> for the
										next run's diff base.</li></ul></aside>`),$e=i(`<p>We pull the accepted-abstract corpus from the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Oxford Abstracts GraphQL API</a>, paginating through every accepted submission. Each record carries
							its program-assigned <em>poster id</em>, authors + affiliations,
							submitter-typed abstract sections (introduction / methods / results /
							conclusion), and the answers to the submission-form "extra questions"
							that drive our facets (methods, study type, population, etc.). Withdrawn
							submissions never reach this site — they're filtered out at this stage.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),es=i(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Orchestrator.</strong> <code class="svelte-cwls5q">src/ohbm2026/enrich/stage.py</code> walks the accepted corpus, dispatches each record to three
										component runners (figures, claims, references), and atomically
										writes <code class="svelte-cwls5q">data/primary/abstracts_enriched.sqlite</code> via <code class="svelte-cwls5q">enrich/storage.py::EnrichedCorpusWriter</code> (temp →
										rename). Per-row payload is zlib(JSON) so the 3,243-record DB
										stays around 80 MB.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Claims (agentic).</strong> <code class="svelte-cwls5q">enrich/stage2_claims.py</code> calls the OpenAI Responses
										API on <code class="svelte-cwls5q">gpt-5.4-mini</code> with three function tools the
										model may invoke iteratively: <code class="svelte-cwls5q">verify_source_quote</code> (lexically verifies the
										evidence quote against the abstract), <code class="svelte-cwls5q">lookup_eco_code</code> (resolves the evidence to one of
										the 9 top-level ECO v1 codes in <code class="svelte-cwls5q">data/eco_top_codes.json</code>), and <code class="svelte-cwls5q">dedupe_check</code> (rejects near-duplicate claims). Output
										is Pydantic-validated; invalid rows are dropped with a logged
										reason. Cache key = <code class="svelte-cwls5q">sha256(manuscript || model_id || vocabulary_version)</code> under <code class="svelte-cwls5q">data/cache/claim_analysis/</code>.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Figures.</strong> <code class="svelte-cwls5q">enrich/stage2_figures.py</code> groups all of an abstract's figures into a single vision call.
										Locally each PNG/JPEG is re-encoded to JPEG-q85 at max 1024 px
										via <code class="svelte-cwls5q">enrich/image_quality.py</code>, which also returns a
										four-field probe (<code class="svelte-cwls5q">laplacian_variance</code>, <code class="svelte-cwls5q">mean_brightness</code>, <code class="svelte-cwls5q">compression_ratio</code>, <code class="svelte-cwls5q">native_max_dim</code>) — these are stored alongside the
										interpretation so reviewers can see the model's input quality.
										Cache key = <code class="svelte-cwls5q">sha256(image_blob || prompt || model_id)</code> under <code class="svelte-cwls5q">data/cache/figure_analysis/</code>.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Flex-tier retry pattern.</strong> <code class="svelte-cwls5q">enrich/flex_tier.py</code> wraps both LLM calls in
										"1 flex attempt + 1 standard retry" (default timeouts 120 s
										for figures, 180 s for claims). Flex-tier reduces $$$ on the
										happy path; the standard retry catches the <code class="svelte-cwls5q">ContextLengthExceededError</code> /
										timeout / transient-5xx tail without crashing the run.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">References.</strong> Per-record references-block text
										→ LLM-assisted split into individual citation candidates →
										lexical-match each candidate back to the source text (drops
										hallucinated citations) → DOI lookup, then PMID, then <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">OpenAlex</a> title search, with a Semantic Scholar fallback. The LLM
										only HELPS split — the canonical metadata comes from the
										lookup, which is why references do NOT carry the <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> pill in the UI.
										Cached under <code class="svelte-cwls5q">data/cache/reference_metadata/&lt;cache-key&gt;.json</code>.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Provenance.</strong> A run emits <code class="svelte-cwls5q">data/provenance/abstracts_enrich_provenance__&lt;state-key&gt;.json</code> with the per-component model ids, cache hit/miss counts, run
										wall time, and the cmdline that produced it.</li></ul></aside>`),ss=i(`<p>Each abstract is passed to an LLM (currently <code class="svelte-cwls5q">gpt-5.4-mini</code>) twice:
							once to extract structured <em>claims</em> with the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Evidence and Conclusion Ontology</a> annotating each piece of evidence, and once per figure to produce a
							written <em>interpretation</em>. Both outputs are cached by content hash so
							re-runs only pay for changed records. References are split out of the
							submitter's text via the same LLM, then resolved to canonical DOIs via <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">OpenAlex</a>.</p> <p>These two surfaces — figure interpretations and claims — are the only
							pieces of the site that are LLM-written. They're always tagged <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> with the model identifier in the
							tooltip so readers can decide how much to trust them. Verbatim
							submitter content (abstract sections, topic dropdowns, methods
							checklists, authors) carries no such pill — that text is theirs.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),ts=i(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Per-component bundles.</strong> Every abstract is
										embedded separately for <code class="svelte-cwls5q">title</code>, <code class="svelte-cwls5q">introduction</code>, <code class="svelte-cwls5q">methods</code>, <code class="svelte-cwls5q">results</code>, <code class="svelte-cwls5q">conclusion</code>, and <code class="svelte-cwls5q">claims</code>. Each (model, component) pair produces a
										bundle directory <code class="svelte-cwls5q">data/outputs/embeddings/&lt;model_key&gt;/&lt;component&gt;__&lt;state-key&gt;/</code> containing <code class="svelte-cwls5q">vectors.npy</code> (float32, L2-normalised), <code class="svelte-cwls5q">ids.npy</code>, <code class="svelte-cwls5q">metadata.json</code>, and <code class="svelte-cwls5q">provenance.json</code>. The state-key suffix lets historical
										versions coexist on disk; the manifest pins the active one.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Per-abstract cache.</strong> <code class="svelte-cwls5q">data/cache/embeddings/&lt;model_key&gt;/&lt;cache-key&gt;.json</code>;
										key = <code class="svelte-cwls5q">sha256(text || model_id || model_version)</code>. A
										re-run only pays the API/GPU cost for the records whose source
										text actually changed.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Composition at read time.</strong> <code class="svelte-cwls5q">ohbm2026.embed.compose_recipe([components], model_key=...)</code> produces a corpus matrix on demand — for instance the SPA's
										"abstract" lens is <code class="svelte-cwls5q">compose_recipe(['title','introduction','methods','results','conclusion'])</code> meaned per record. No fixed-shape "abstract" embedding is
										persisted; the recipe is the contract.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Token-aware chunking.</strong> Long sections are split
										along sentence boundaries (BlingFire) into model-token budgets
										and the chunk embeddings are mean-pooled per section. NeuroScape
										wraps a public base in a learned Stage-2 transform — see the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Aperture Neuro paper</a> and the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">code</a>.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Models.</strong> <code class="svelte-cwls5q">voyage-3-lite</code> / <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q"><code class="svelte-cwls5q">sentence-transformers/all-MiniLM-L6-v2</code></a> / <code class="svelte-cwls5q">text-embedding-3-small</code> / <code class="svelte-cwls5q">microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract</code> / <code class="svelte-cwls5q">neuroscape</code> (Stage-2 transform).</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">SPA wire format.</strong> <code class="svelte-cwls5q">127 / max_abs</code>.
										The buffer ships as <code class="svelte-cwls5q">data/search/minilm_vectors.bin</code> with a sidecar JSON declaring <code class="svelte-cwls5q">shape</code>, <code class="svelte-cwls5q">scale</code>, and <code class="svelte-cwls5q">cosine_recovery_mae</code> (≤ 0.005
										invariant — current build is 0.00057). The buffer is transferred
										zero-copy into a Web Worker on first paint.</li></ul></aside>`),as=i(`<p>We compute sentence-level embeddings for every abstract using five
							different encoder families: a public general-purpose model
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">MiniLM-L6</a>), a domain-specific biomedical model (PubMedBERT), two commercial APIs
							(OpenAI, Voyage), and our project-specific NeuroScape model
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Aperture Neuro paper</a>, <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">code</a>). Embeddings are computed per section (title / introduction /
							methods / results / conclusion / claims) and composed into bundles at
							read time, so the UI can show the same corpus through different "lenses".</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),ls=i(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Orchestrator.</strong> <code class="svelte-cwls5q">ohbmcli analyze-matrix</code> (wraps <code class="svelte-cwls5q">analyze/runners.py</code>) fans out across 48 (model,
										input, recipe) bundles on a joblib pool. Each bundle's
										per-record output rolls up into a single <code class="svelte-cwls5q"></code>;
										the SQLite is what Stage 6's data-package builder reads.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">kNN graph.</strong> <code class="svelte-cwls5q">analyze/communities.py::build_faiss_knn</code> L2-normalises
										the corpus matrix, builds a FAISS <code class="svelte-cwls5q">IndexFlatIP</code> (exact inner-product on the unit sphere → cosine), runs a
										batched search, masks each node's own hit. Default <code class="svelte-cwls5q">k = 15</code>. Falls back to a sklearn cosine-kNN if <code class="svelte-cwls5q">faiss-cpu</code> isn't installed.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Leiden community detection.</strong> CPM partition
										(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Traag 2019</a>) via <code class="svelte-cwls5q">leidenalg</code>; resolution chosen by a 20-point
										sweep over <code class="svelte-cwls5q">[0.001, 0.1]</code> (geometric spacing), picking
										the modularity plateau where the partition is stable. The
										resulting <code class="svelte-cwls5q">community_id</code> per abstract is what the
										UMAP colour-codes; <code class="svelte-cwls5q">-1</code> = unclustered.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">UMAP layout.</strong> <code class="svelte-cwls5q">analyze/umap.py</code> runs both 2D and 3D layouts with <code class="svelte-cwls5q">n_neighbors = 15</code>, <code class="svelte-cwls5q">min_dist = 0.1</code>, <code class="svelte-cwls5q">metric = cosine</code>, <code class="svelte-cwls5q">random_state = 42</code>.
										Outputs <code class="svelte-cwls5q">umap2d_coords.npy</code> + <code class="svelte-cwls5q">umap3d_coords.npy</code> per bundle.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">HDBSCAN topic clusters.</strong> <code class="svelte-cwls5q">analyze/topic_clusters.py</code> reuses the UMAP layout's
										2D coordinates (with its own tighter parameters <code class="svelte-cwls5q">n_neighbors = 15</code>, <code class="svelte-cwls5q">min_dist = 0.0</code>) and feeds them to HDBSCAN with <code class="svelte-cwls5q">min_cluster_size = 10</code>. Falls through to a
										constant-label partition when fewer than that survive. <code class="svelte-cwls5q">topic_cluster_id = -1</code> means HDBSCAN-noise.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Cluster naming.</strong> Hybrid: spaCy noun-chunk
										keyword extraction → class-TF-IDF over the cluster's titles +
										abstracts → an LLM grouping pass that produces <code class="svelte-cwls5q"></code> per cluster. These
										are the only Stage-4 surface that carries the <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> pill in the UI.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Neighbour pre-compute.</strong> <code class="svelte-cwls5q">scripts/compute_neighbors.py</code> reads each bundle's <code class="svelte-cwls5q">reference_matrix.npy</code> (the canonical embedding the
										community detection ran on), computes pairwise cosine
										distance, and bakes in <code class="svelte-cwls5q">k = 10</code> nearest + 10
										farthest per abstract into <code class="svelte-cwls5q">data/outputs/analysis/&lt;cell&gt;/projections__&lt;state-key&gt;/neighbors__&lt;state-key&gt;/*.npy</code>.
										The detail panel aggregates this across all 15 cells for the
										"Most similar / Most different" rails.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Output shape.</strong> Every per-abstract row carries <code class="svelte-cwls5q">community_id</code>, <code class="svelte-cwls5q">topic_cluster_id</code>, <code class="svelte-cwls5q">umap2d</code>, <code class="svelte-cwls5q">umap3d</code>, and (NeuroScape
										only) <code class="svelte-cwls5q">neuroscape_cluster_id</code> + <code class="svelte-cwls5q">neuroscape_cluster_distance</code>. The Stage 6 builder
										projects this wide table into per-cell shards keyed by <code class="svelte-cwls5q">&lt;model&gt;_&lt;input&gt;</code>.</li></ul></aside>`),cs=i(`<p>For each (model, input) combination we build a UMAP layout
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">McInnes 2018</a>) in 2D and 3D, run Leiden community detection
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Traag 2019</a>) on the nearest-neighbour graph to find topic clusters, and HDBSCAN
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">McInnes 2017</a>) for a density-based view. An LLM names each community by reading a
							representative sample of titles from inside it; those names are what
							you see in the "Cluster (current map)" facet and in the UMAP hover
							tooltips.</p> <p>The same per-(model, input) bundle drives the "Most similar" and "Most
							different" lists in the detail panel — we precompute the 10 nearest +
							10 farthest abstracts per record per cell. The detail panel then
							aggregates across all 15 cells so the similar-list reflects every
							"lens" rather than just the currently-selected one.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),os=i(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Stack.</strong> SvelteKit 2 + Vite 6 + Svelte 5, <code class="svelte-cwls5q">@sveltejs/adapter-static</code> with <code class="svelte-cwls5q">fallback: '404.html'</code> and <code class="svelte-cwls5q">paths.base = $env.BASE_PATH</code>. Plotly via <code class="svelte-cwls5q">plotly.js-gl3d-dist-min</code> (lazy-loaded; only the
										gl3d bundle has scatter3d). Theme handling via a
										localStorage-backed Svelte store with a system-pref watcher.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Data delivery.</strong> Each site loads a single-file <strong class="svelte-cwls5q">Parquet</strong> from a per-mode URL
										(<code class="svelte-cwls5q">VITE_DATA_PACKAGE_URL_OHBM2026 / _NEUROSCAPE / _ATLAS</code>;
										Dropbox links are rewritten to <code class="svelte-cwls5q">dl.dropboxusercontent.com</code> at runtime to skip the <code class="svelte-cwls5q">www.dropbox.com</code> 302 that drops CORS). The parquets use
										a nested-envelope layout (an outer row per inner table, written <code class="svelte-cwls5q">row_group_size=1</code>) so the browser can HTTP-range-fetch
										ONE inner table via hyparquet predicate pushdown — the cluster
										legend, one quadtree backdrop tier, the OHBM→NeuroScape overlay —
										instead of pulling the whole ~100&nbsp;MB file. The
										cross-conference hub range-fetches the NeuroScape backdrop +
										clusters + overlay from the sibling parquets; nothing is
										duplicated across files.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Neuroscience-wide map.</strong> A Python orchestrator
										(<code class="svelte-cwls5q">ohbmcli build-atlas-package</code>) fits a deterministic 2D
										+ 3D UMAP on the NeuroScape Stage-2 vectors and projects the OHBM
										2026 abstracts into it via <code class="svelte-cwls5q">umap.transform</code>, so the
										conference overlay and the ~461k PubMed backdrop share one
										coordinate space. The backdrop is decimated into quadtree
										blue-noise LOD tiers (a coarse cover paints first, finer tiers
										stream in on zoom, capped by a viewport budget) and the 3D scene
										renders a thinned sample to stay interactive. Semantic search on
										this corpus is cluster-routed: the query embeds, picks the
										nearest cluster centroid, range-fetches that cluster's int8
										vectors, brute-forces seeds, then expands through the k=20
										neighbour graph — bounded per-query cost instead of a full-corpus
										scan.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Lexical search.</strong> <code class="svelte-cwls5q">site/src/lib/filter.ts</code> builds an in-memory inverted
										index (lazy-built per <code class="svelte-cwls5q">WeakMap&lt;abstracts, index&gt;</code>)
										over title + topics + methods + author names + facet values +
										section bodies (NFD-folded + lower-cased + length-≥-2 tokens).
										Query token → all corpus tokens within Damerau-Levenshtein ≤ <code class="svelte-cwls5q">thresholdFor(token)</code> (<code class="svelte-cwls5q">&lt;4</code> chars: 0; <code class="svelte-cwls5q">4-6</code>: 1; <code class="svelte-cwls5q">≥7</code>: 2). Multi-token queries
										AND-intersect their per-token postings. Returns <code class="svelte-cwls5q"></code> so the result list can
										rank exact-match abstracts above fuzzy/proximal hits.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Semantic search.</strong> <code class="svelte-cwls5q">site/src/lib/workers/semantic.worker.ts</code> is a
										Web Worker that loads <code class="svelte-cwls5q">Xenova/all-MiniLM-L6-v2</code> via <code class="svelte-cwls5q">@xenova/transformers</code> (HF CDN, browser-cached),
										receives the int8 vector buffer via zero-copy <code class="svelte-cwls5q">postMessage(..., [buffer])</code>, then per query:
										mean-pooled + L2-normalised embedding of the query
										(384-d), dot-product against every row, dequantised by <code class="svelte-cwls5q">1 / scale</code>, clamped to <code class="svelte-cwls5q">[-1, 1]</code>,
										sorted to top-K. The main-thread facade
										(<code class="svelte-cwls5q">site/src/lib/search/semantic.ts</code>) exposes a <code class="svelte-cwls5q">semanticStatus</code> store the toggle button reads.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Filter pipeline.</strong> <code class="svelte-cwls5q">filteredIds = compose([searchIds, lasso, facetIds,
										authorChipIds, cartIds])</code> — the intersection of every
										ACTIVE filter (an inactive one contributes no constraint).
										"Cart only" is one more intersecting filter, not a dominant
										override, so it composes with search / facets / lasso like a
										facet selection, consistently across all three sibling sites.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">UMAP.</strong> 2D scatter + 3D scatter3d in Plotly,
										coloured + shaped by <code class="svelte-cwls5q">community_id</code> using Paul
										Tol's "bright" palette × 5 marker symbols (≈ 35 unique combos
										before any pair repeats — colour-vision-safe). The 3D camera
										is tracked via a <code class="svelte-cwls5q">plotly_relayout</code> listener into a
										module-level <code class="svelte-cwls5q">currentEye3D</code> so pause/zoom/orbit
										then unpause continues from the user's chosen camera. The
										focused abstract carries an over-sized open-circle halo trace
										drawn last so it pops above the cluster carpet on both 2D
										and 3D.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Permalink direct-load.</strong> gh-pages serves the
										root <code class="svelte-cwls5q">/404.html</code> for any URL it can't resolve. Ours
										is a hand-written SPA-redirect committed directly to the <code class="svelte-cwls5q">gh-pages</code> branch: it detects the requested base
										path (<code class="svelte-cwls5q">/pr-N</code> or root), stashes the full original
										path in <code class="svelte-cwls5q">?spa=…</code> + <code class="svelte-cwls5q">sessionStorage</code> (belt + suspenders), and replaces location with the SPA shell
										root. The layout's <code class="svelte-cwls5q">onMount</code> pops the stash,
										strips the <code class="svelte-cwls5q">?spa=…</code> with <code class="svelte-cwls5q">history.replaceState</code>, and <code class="svelte-cwls5q"></code>s to the deep
										link — passing the FULL stash (not the base-stripped form)
										because SvelteKit's <code class="svelte-cwls5q">goto</code> treats <code class="svelte-cwls5q">/path</code> as origin-absolute and would otherwise
										escape the SPA's scope.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Deploy.</strong> <code class="svelte-cwls5q">.github/workflows/deploy-ui.yml</code> publishes to
										gh-pages root via <code class="svelte-cwls5q">peaceiris/actions-gh-pages@v3</code> on every push to <code class="svelte-cwls5q">main</code>; <code class="svelte-cwls5q">pr-preview.yml</code> declares <code class="svelte-cwls5q">environment: pr-preview-&lt;N&gt;</code> so the URL
										surfaces in the PR's Deployments box (not a bot comment), and
										deploys to <code class="svelte-cwls5q">gh-pages:pr-&lt;N&gt;/</code> with <code class="svelte-cwls5q">BASE_PATH=/pr-&lt;N&gt;</code>. The tarball lives at a
										stable URL outside the repo (Dropbox shared link); the build
										step injects it as <code class="svelte-cwls5q">VITE_DATA_PACKAGE_URL</code> + a sha256 var
										(<code class="svelte-cwls5q">OHBM2026_UI_DATA_PACKAGE_SHA256</code>) for integrity.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Validation.</strong> Every emitted shard validates
										against the LinkML schema at <code class="svelte-cwls5q">specs/008-ui-rewrite/contracts/ui_data.linkml.yaml</code>. <code class="svelte-cwls5q">scripts/validate_ui_data.sh</code> runs <code class="svelte-cwls5q">linkml-validate</code> over each shard
										(<code class="svelte-cwls5q">Manifest</code>, <code class="svelte-cwls5q">AbstractsShard</code>, <code class="svelte-cwls5q">AuthorsShard</code>, <code class="svelte-cwls5q">EnrichmentShard</code>, <code class="svelte-cwls5q">MinilmVectorsSidecar</code>, every CellShard / TopicShard
										/ NeighborsShard) — currently 68/68 pass. A re-generated data
										package whose shards validate against the same schema can be
										loaded by the site with zero code changes.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Accessibility.</strong> Targeting WCAG 2.1 AA. <code class="svelte-cwls5q">@axe-core/playwright</code> audits the home / about /
										abstract-permalink routes against the live production URL
										(<code class="svelte-cwls5q">site/src/tests/e2e/a11y.spec.ts</code>) — critical +
										serious violations fail the test. Every <code class="svelte-cwls5q">overflow-y: auto</code> scroll container carries <code class="svelte-cwls5q">tabindex="0"</code> + a labelled <code class="svelte-cwls5q">role="region"</code> so keyboard users can reach and
										scroll the cluster-membership grid, the related-abstracts
										rails, the facet option lists, and the cart drawer items.
										Theme + colour-vision-safe palette choices are documented in
										the Stage 4 deep-dive.</li></ul></aside>`),rs=i(`<p>Stage 6 turns the pipeline outputs into the browsable atlas — and it
							now builds <strong>three sibling sites from one SvelteKit codebase</strong> (selected by a build-time site mode): the per-conference OHBM 2026
							site, the cross-conference <strong>Abstract Atlas</strong> hub, and the
							neuroscience-wide <strong>NeuroScape PubMed atlas</strong> (~461,000
							articles, 1999–2023, 175 topic clusters). The hub projects the 3,240
							OHBM 2026 abstracts into the same UMAP as the NeuroScape corpus, so
							conference work can be read against the broader neuroscience literature;
							a toggle shows or hides the OHBM overlay on the PubMed backdrop.</p> <p>Every site is static on GitHub Pages — no server, no database, no
							per-query backend round-trip. Each one's data is a single-file <strong>Parquet</strong> on a stable CDN URL, and the browser <em>range-fetches one inner table at a time</em> (predicate pushdown
							over a nested-envelope layout) instead of downloading the whole file.
							The neuroscience-wide map is far too large to draw at once, so its
							backdrop paints from a coarse quadtree tier first and refines as finer
							tiers stream into view on zoom, with per-point opacity that scales to
							the on-screen density so the cloud stays readable at any zoom.</p> <p>Lexical typo-tolerant search runs in the main thread; semantic search <span class="ai-pill-demo svelte-cwls5q">✨</span> runs in a Web Worker using <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">MiniLM-L6</a> ONNX through transformers.js, against int8-quantised vectors. On the
							small per-conference corpus it scores every abstract directly; on the
							461k-article neuroscience map it routes each query to the nearest topic
							cluster and expands through a precomputed neighbour graph, so it stays
							fast without holding every vector in memory.</p> <p class="muted svelte-cwls5q">Source: <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">github.com/sensein/ohbm2026</a>. Build provenance is in the footer of every page.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),ns=i('<div class="stage-body svelte-cwls5q"><!></div>'),is=i('<section class="stage svelte-cwls5q"><button type="button" class="stage-header svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> <span class="stage-label svelte-cwls5q"> </span></button> <!></section>'),ds=i('<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q"> </a>'),hs=i('<li class="changelog-entry svelte-cwls5q"><div class="changelog-meta svelte-cwls5q"><time class="svelte-cwls5q"> </time> <span class="changelog-refs svelte-cwls5q"></span></div> <h3 class="changelog-title svelte-cwls5q"> </h3> <p class="changelog-summary svelte-cwls5q"> </p></li>'),ps=i(`<div class="about-page svelte-cwls5q"><nav class="back svelte-cwls5q"><a class="svelte-cwls5q">← back to atlas</a></nav> <div class="about-layout svelte-cwls5q"><aside class="about-toc svelte-cwls5q" aria-label="On this page"><p class="toc-label svelte-cwls5q">On this page</p> <nav class="svelte-cwls5q"></nav></aside> <div class="about-content svelte-cwls5q"><header class="svelte-cwls5q"><!> <!></header> <section id="pipeline" class="pipeline-section svelte-cwls5q"><section class="overview svelte-cwls5q"><!> <p class="svelte-cwls5q">The pipeline runs in five stages, listed below. Click each one to see how it works.
			Surfaces that were authored or interpreted by an LLM (figure interpretations,
			extracted claims, LLM-grouped topic-cluster titles) carry an <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> pill in the detail panel so the
			provenance is always visible.</p> <p class="svelte-cwls5q">Beyond the per-conference pipeline, the <strong>Abstract Atlas</strong> cross-conference landing page projects this corpus into
			a much larger neuroscience embedding (NeuroScape PubMed, ~461k articles
			1999–2023, 175 clusters) so OHBM 2026 work can be browsed in the context of
			the broader literature. The NeuroScape PubMed atlas itself is the second
			sibling subsite, with the same UMAP and clusters but no OHBM overlay. All
			three subsites — Abstract Atlas (root), OHBM 2026 (this site), and
			NeuroScape PubMed — are independently rebuildable; the Abstract Atlas
			landing is the only hub that knows about all of them.</p></section> <!></section> <section id="changes" class="changes-section svelte-cwls5q"><h2 class="changes-heading svelte-cwls5q">Changes</h2> <p class="changes-intro svelte-cwls5q">Major user-visible updates, newest first. Each entry links to the pull
			request (or commit) that shipped it.</p> <ol class="changelog svelte-cwls5q"></ol></section></div></div></div>`);function fs(ge){let H=me({}),u=me({});function fe(l){be(H,{...c(H),[l]:!c(H)[l]})}function W(l){be(u,{...c(u),[l]:!c(u)[l]})}const v={oxford:{url:"https://app.oxfordabstracts.com/"},umap:{url:"https://arxiv.org/abs/1802.03426"},leiden:{url:"https://www.nature.com/articles/s41598-019-41695-z"},hdbscan:{url:"https://joss.theoj.org/papers/10.21105/joss.00205"},minilm:{url:"https://arxiv.org/abs/2002.10957"},eco:{url:"https://evidenceontology.org/"},openalex:{url:"https://openalex.org/"},neuroscape_repo:{url:"https://github.com/ccnmaastricht/NeuroScape"},neuroscape_paper:{url:"https://apertureneuro.org/article/156380-the-evolving-landscape-of-neuroscience"},repo:{url:"https://github.com/sensein/ohbm2026"}},ie="https://github.com/sensein/ohbm2026",h=l=>`${ie}/pull/${l}`,qe=[{date:"2026-05",title:"Readable large-corpus map + live loading",summary:"The PubMed backdrop now paints a coarse quadtree tier instantly and refines as finer detail streams in on zoom, with per-point opacity that scales to how many points are on screen so the cloud stays readable at every zoom level. The map opens fitted to the whole corpus, facet toggles (including hiding NeuroScape) clear every layer, and the result count shows a live loading indicator while the full ~461k-article corpus streams in. Cross-site navigation warms sibling data more cheaply.",refs:[{label:"PR #47",url:h(47)},{label:"PR #49",url:h(49)}]},{date:"2026-05",title:"Cross-conference semantic search",summary:"Semantic search ✨ now runs on the NeuroScape PubMed atlas and the cross-conference root, not just OHBM 2026 — reusing the same in-browser MiniLM model. Search gained Damerau-Levenshtein typo tolerance and a debounced input so typing stays smooth on the 461k-article corpus.",refs:[{label:"PR #47",url:h(47)}]},{date:"2026-05",title:"Privacy-respecting analytics",summary:"Added Google Analytics gated behind a consent banner that honours Do-Not-Track and Global-Privacy-Control signals; theme variables were fixed so the banner reads correctly in dark mode.",refs:[{label:"PR #45",url:h(45)},{label:"PR #46",url:h(46)}]},{date:"2026-04",title:"Atlas rebuild + provenance speed-ups",summary:"The UMAP fit is now cached so atlas rebuilds complete in under a minute, and per-abstract AI provenance is plumbed through the parquet manifest.",refs:[{label:"PR #43",url:h(43)},{label:"PR #44",url:h(44)}]},{date:"2026-04",title:"Large-corpus performance + mobile WebGL",summary:'Performance wins for the 461k-point scatter, a graceful 2D-only fallback when a browser exposes no WebGL, and a bulk "Add N to cart" action on the root + NeuroScape sites.',refs:[{label:"PR #40",url:h(40)},{label:"PR #41",url:h(41)},{label:"PR #42",url:h(42)}]},{date:"2026-03",title:"Cross-conference atlas + NeuroScape subsite",summary:"Introduced the three-site hub-and-spoke layout: a cross-conference Abstract Atlas landing page, a standalone NeuroScape PubMed atlas (~461k articles, 175 clusters), and the existing OHBM 2026 site — built from one codebase via three site modes, with deep links routed correctly across subsites.",refs:[{label:"PR #36",url:h(36)},{label:"PR #37",url:h(37)},{label:"PR #38",url:h(38)},{label:"PR #39",url:h(39)}]},{date:"2026-02",title:"Poster-id search navigator",summary:"The search bar gained an id: operator with an autocomplete dropdown to jump straight to a poster by its program id.",refs:[{label:"PR #35",url:h(35)}]},{date:"2026-02",title:"Book of abstracts (PDF)",summary:"A deterministic book-of-abstracts PDF generator, layout polish, an acknowledgments section, and authoritative standby times wired into the UI with deep links.",refs:[{label:"PR #26",url:h(26)},{label:"PR #31",url:h(31)},{label:"PR #34",url:h(34)}]},{date:"2026-01",title:"Conference subpaths + single-file data export",summary:"Moved every OHBM 2026 surface under /ohbm2026/ to make room for sibling conferences, and redesigned the data package as a single-file Parquet with a tight schema and a poster-id as the sole user-facing identifier.",refs:[{label:"PR #19",url:h(19)},{label:"PR #20",url:h(20)}]},{date:"2025-12",title:"Static atlas launch",summary:"First public release: a static SvelteKit site with typo-tolerant lexical + semantic search, a 2D + 3D UMAP with lasso selection, a saved-list cart with email export, a guided tour, and this About page with link-checked references.",refs:[{label:"PRs #9–#18",url:`${ie}/pulls?q=is%3Apr+is%3Amerged`}]}],ye=[{id:"pipeline",label:"How it works"},{id:"changes",label:"Changes"}];var $=ps();Ue("cwls5q",l=>{var e=He(),w=z(e);{var k=x=>{re(()=>{ne.title="About · Abstract Atlas"})},D=x=>{re(()=>{ne.title="About · NeuroScape PubMed Atlas"})},G=x=>{re(()=>{ne.title="About · OHBM 2026 Atlas"})};O(w,x=>{E==="atlas-root"?x(k):E==="neuroscape"?x(D,1):x(G,-1)})}r(l,e)});var ee=t($),_e=t(ee);s(ee);var de=a(ee,2),se=t(de),he=a(t(se),2);Z(he,5,()=>ye,l=>l.id,(l,e)=>{var w=Fe(),k=t(w,!0);s(w),_(()=>{o(w,"href",`#${c(e).id}`),M(k,c(e).label)}),r(l,w)}),s(he),s(se);var pe=a(se,2),te=t(pe),ue=t(te);{var ke=l=>{var e=ze();r(l,e)},Ae=l=>{var e=We();r(l,e)},xe=l=>{var e=Ge();r(l,e)};O(ue,l=>{E==="atlas-root"?l(ke):E==="neuroscape"?l(Ae,1):l(xe,-1)})}var Se=a(ue,2);{var Pe=l=>{var e=Ve();r(l,e)},Me=l=>{var e=Ke();r(l,e)},Te=l=>{var e=Qe();r(l,e)};O(Se,l=>{E==="atlas-root"?l(Pe):E==="neuroscape"?l(Me,1):l(Te,-1)})}s(te);var ae=a(te,2),le=t(ae),Ne=t(le);{var Le=l=>{var e=Je();r(l,e)},Oe=l=>{var e=Ye(),w=a(t(e));n(3),s(e),_(()=>o(w,"href",v.neuroscape_paper.url)),r(l,e)},De=l=>{var e=Xe();r(l,e)};O(Ne,l=>{E==="atlas-root"?l(Le):E==="neuroscape"?l(Oe,1):l(De,-1)})}n(4),s(le);var Re=a(le,2);Z(Re,0,()=>[{key:"fetch",label:"Stage 1 — Fetch & normalise (Oxford Abstracts → JSON)"},{key:"enrich",label:"Stage 2 — AI enrichment (figures + claims + references)"},{key:"embed",label:"Stage 3 — Embeddings (5 models × per-section)"},{key:"analyse",label:"Stage 4 — Communities + clusters + UMAP"},{key:"ui",label:"Stage 6 — This site"}],l=>l.key,(l,e)=>{var w=is(),k=t(w),D=t(k),G=t(D,!0);s(D);var x=a(D,2),V=t(x,!0);s(x),s(k);var ce=a(k,2);{var Q=K=>{var I=ns(),J=t(I);{var U=b=>{var f=$e(),p=z(f),S=a(t(p));n(3),s(p);var m=a(p,2),q=t(m),d=t(q,!0);s(q),n(),s(m);var P=a(m,2);{var R=T=>{var N=Ze();r(T,N)};O(P,T=>{c(u)[e.key]&&T(R)})}_(()=>{o(S,"href",v.oxford.url),o(m,"aria-expanded",!!c(u)[e.key]),M(d,c(u)[e.key]?"▾":"▸")}),F("click",m,()=>W(e.key)),r(b,f)},oe=b=>{var f=ss(),p=z(f),S=a(t(p),5),m=a(S,4);n(),s(p);var q=a(p,4),d=t(q),P=t(d,!0);s(d),n(),s(q);var R=a(q,2);{var T=N=>{var g=es(),y=t(g),L=a(t(y),8),A=a(t(L),2);n(5),s(L),n(2),s(y),s(g),_(()=>o(A,"href",v.openalex.url)),r(N,g)};O(R,N=>{c(u)[e.key]&&N(T)})}_(()=>{o(S,"href",v.eco.url),o(m,"href",v.openalex.url),o(q,"aria-expanded",!!c(u)[e.key]),M(P,c(u)[e.key]?"▾":"▸")}),F("click",q,()=>W(e.key)),r(b,f)},Ce=b=>{var f=as(),p=z(f),S=a(t(p)),m=a(S,2),q=a(m,2);n(),s(p);var d=a(p,2),P=t(d),R=t(P,!0);s(P),n(),s(d);var T=a(d,2);{var N=g=>{var y=ts(),L=t(y),A=a(t(L),6),j=a(t(A),2),C=a(j,2);n(),s(A);var B=a(A,2),Y=a(t(B),4);n(7),s(B);var X=a(B,2),Be=a(t(X));Be.nodeValue=` The MiniLM corpus matrix used
										for in-browser semantic search is composed of
										{intro, methods, results, conclusion}, L2-renormalised, then
										int8-quantised with a global scale = `,n(10),s(X),s(L),s(y),_(()=>{o(j,"href",v.neuroscape_paper.url),o(C,"href",v.neuroscape_repo.url),o(Y,"href",v.minilm.url)}),r(g,y)};O(T,g=>{c(u)[e.key]&&g(N)})}_(()=>{o(S,"href",v.minilm.url),o(m,"href",v.neuroscape_paper.url),o(q,"href",v.neuroscape_repo.url),o(d,"aria-expanded",!!c(u)[e.key]),M(R,c(u)[e.key]?"▾":"▸")}),F("click",d,()=>W(e.key)),r(b,f)},Ee=b=>{var f=cs(),p=z(f),S=a(t(p)),m=a(S,2),q=a(m,2);n(),s(p);var d=a(p,4),P=t(d),R=t(P,!0);s(P),n(),s(d);var T=a(d,2);{var N=g=>{var y=ls(),L=t(y),A=t(L),j=a(t(A),6);j.textContent="data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}",n(),s(A);var C=a(A,4),B=a(t(C),2);n(9),s(C);var Y=a(C,6),X=a(t(Y),2);X.textContent="{title, description, focus}",n(3),s(Y),n(4),s(L),s(y),_(()=>o(B,"href",v.leiden.url)),r(g,y)};O(T,g=>{c(u)[e.key]&&g(N)})}_(()=>{o(S,"href",v.umap.url),o(m,"href",v.leiden.url),o(q,"href",v.hdbscan.url),o(d,"aria-expanded",!!c(u)[e.key]),M(R,c(u)[e.key]?"▾":"▸")}),F("click",d,()=>W(e.key)),r(b,f)},Ie=b=>{var f=rs(),p=a(z(f),4),S=a(t(p),3);n(),s(p);var m=a(p,2),q=a(t(m));n(),s(m);var d=a(m,2),P=t(d),R=t(P,!0);s(P),n(),s(d);var T=a(d,2);{var N=g=>{var y=os(),L=t(y),A=a(t(L),6),j=a(t(A),14);j.textContent="{ ids, exactness }",n(),s(A);var C=a(A,8),B=a(t(C),18);B.textContent="goto(stash, { replaceState: true })",n(5),s(C),n(6),s(L),s(y),r(g,y)};O(T,g=>{c(u)[e.key]&&g(N)})}_(()=>{o(S,"href",v.minilm.url),o(q,"href",v.repo.url),o(d,"aria-expanded",!!c(u)[e.key]),M(R,c(u)[e.key]?"▾":"▸")}),F("click",d,()=>W(e.key)),r(b,f)};O(J,b=>{e.key==="fetch"?b(U):e.key==="enrich"?b(oe,1):e.key==="embed"?b(Ce,2):e.key==="analyse"?b(Ee,3):e.key==="ui"&&b(Ie,4)})}s(I),r(K,I)};O(ce,K=>{c(H)[e.key]&&K(Q)})}s(w),_(()=>{o(w,"data-testid",`about-stage-${e.key}`),o(k,"aria-expanded",!!c(H)[e.key]),M(G,c(H)[e.key]?"▾":"▸"),M(V,e.label)}),F("click",k,()=>fe(e.key)),r(l,w)}),s(ae);var ve=a(ae,2),we=a(t(ve),4);Z(we,5,()=>qe,l=>l.title+l.date,(l,e)=>{var w=hs(),k=t(w),D=t(k),G=t(D,!0);s(D);var x=a(D,2);Z(x,5,()=>c(e).refs,I=>I.url,(I,J)=>{var U=ds(),oe=t(U,!0);s(U),_(()=>{o(U,"href",c(J).url),M(oe,c(J).label)}),r(I,U)}),s(x),s(k);var V=a(k,2),ce=t(V,!0);s(V);var Q=a(V,2),K=t(Q,!0);s(Q),s(w),_(()=>{M(G,c(e).date),M(ce,c(e).title),M(K,c(e).summary)}),r(l,w)}),s(we),s(ve),s(pe),s(de),s($),_(()=>o(_e,"href",`${je}/`)),r(ge,$)}export{fs as component};
