import{a as g,f as b,s as P,e as C}from"../chunks/0vpzw9Sl.js";import{s as l}from"../chunks/Br6ZdhzZ.js";import{bj as S,ac as de,$ as ve,X as s,aX as t,b9 as e,ah as r,aJ as J,b0 as Q,af as R,aL as c}from"../chunks/A7nDuqtY.js";import{i as D}from"../chunks/4FuyFW0G.js";import{e as pe}from"../chunks/CqAYLuKc.js";import{h as he}from"../chunks/BrJIARa6.js";import{d as ue}from"../chunks/BWyXKU9t.js";var we=b(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Source.</strong> <code class="svelte-cwls5q">src/ohbm2026/fetch/graphql_api.py</code> exports three queries: <code class="svelte-cwls5q">ABSTRACT_IDS_QUERY</code> (accepted
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
										next run's diff base.</li></ul></aside>`),me=b(`<p>We pull the accepted-abstract corpus from the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Oxford Abstracts GraphQL API</a>, paginating through every accepted submission. Each record carries
							its program-assigned <em>poster id</em>, authors + affiliations,
							submitter-typed abstract sections (introduction / methods / results /
							conclusion), and the answers to the submission-form "extra questions"
							that drive our facets (methods, study type, population, etc.). Withdrawn
							submissions never reach this site — they're filtered out at this stage.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),qe=b(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Orchestrator.</strong> <code class="svelte-cwls5q">src/ohbm2026/enrich/stage.py</code> walks the accepted corpus, dispatches each record to three
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
										wall time, and the cmdline that produced it.</li></ul></aside>`),ge=b(`<p>Each abstract is passed to an LLM (currently <code class="svelte-cwls5q">gpt-5.4-mini</code>) twice:
							once to extract structured <em>claims</em> with the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Evidence and Conclusion Ontology</a> annotating each piece of evidence, and once per figure to produce a
							written <em>interpretation</em>. Both outputs are cached by content hash so
							re-runs only pay for changed records. References are split out of the
							submitter's text via the same LLM, then resolved to canonical DOIs via <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">OpenAlex</a>.</p> <p>These two surfaces — figure interpretations and claims — are the only
							pieces of the site that are LLM-written. They're always tagged <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> with the model identifier in the
							tooltip so readers can decide how much to trust them. Verbatim
							submitter content (abstract sections, topic dropdowns, methods
							checklists, authors) carries no such pill — that text is theirs.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),be=b(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Per-component bundles.</strong> Every abstract is
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
										zero-copy into a Web Worker on first paint.</li></ul></aside>`),fe=b(`<p>We compute sentence-level embeddings for every abstract using five
							different encoder families: a public general-purpose model
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">MiniLM-L6</a>), a domain-specific biomedical model (PubMedBERT), two commercial APIs
							(OpenAI, Voyage), and our project-specific NeuroScape model
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Aperture Neuro paper</a>, <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">code</a>). Embeddings are computed per section (title / introduction /
							methods / results / conclusion / claims) and composed into bundles at
							read time, so the UI can show the same corpus through different "lenses".</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),ye=b(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Orchestrator.</strong> <code class="svelte-cwls5q">ohbmcli analyze-matrix</code> (wraps <code class="svelte-cwls5q">analyze/runners.py</code>) fans out across 48 (model,
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
										projects this wide table into per-cell shards keyed by <code class="svelte-cwls5q">&lt;model&gt;_&lt;input&gt;</code>.</li></ul></aside>`),_e=b(`<p>For each (model, input) combination we build a UMAP layout
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">McInnes 2018</a>) in 2D and 3D, run Leiden community detection
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Traag 2019</a>) on the nearest-neighbour graph to find topic clusters, and HDBSCAN
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">McInnes 2017</a>) for a density-based view. An LLM names each community by reading a
							representative sample of titles from inside it; those names are what
							you see in the "Cluster (current map)" facet and in the UMAP hover
							tooltips.</p> <p>The same per-(model, input) bundle drives the "Most similar" and "Most
							different" lists in the detail panel — we precompute the 10 nearest +
							10 farthest abstracts per record per cell. The detail panel then
							aggregates across all 15 cells so the similar-list reflects every
							"lens" rather than just the currently-selected one.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),ke=b(`<aside class="tldr svelte-cwls5q"><ul class="svelte-cwls5q"><li class="svelte-cwls5q"><strong class="svelte-cwls5q">Stack.</strong> SvelteKit 2 + Vite 6 + Svelte 5, <code class="svelte-cwls5q">@sveltejs/adapter-static</code> with <code class="svelte-cwls5q">fallback: '404.html'</code> and <code class="svelte-cwls5q">paths.base = $env.BASE_PATH</code>. Plotly via <code class="svelte-cwls5q">plotly.js-gl3d-dist-min</code> (lazy-loaded; only the
										gl3d bundle has scatter3d). Theme handling via a
										localStorage-backed Svelte store with a system-pref watcher.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Data delivery.</strong> A single gzipped tarball at <code class="svelte-cwls5q">VITE_DATA_PACKAGE_URL</code> (Dropbox shared link rewritten
										to <code class="svelte-cwls5q">dl.dropboxusercontent.com</code> at runtime to avoid the <code class="svelte-cwls5q">www.dropbox.com</code> 302 that drops CORS). Body is
										decoded via native <code class="svelte-cwls5q">DecompressionStream('gzip')</code> + a
										hand-rolled ~50-line tar parser
										(<code class="svelte-cwls5q">site/src/lib/data_package.ts</code>) into a <code class="svelte-cwls5q">Map&lt;path, JsonValue | Uint8Array&gt;</code> resident in
										memory.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Lexical search.</strong> <code class="svelte-cwls5q">site/src/lib/filter.ts</code> builds an in-memory inverted
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
										(<code class="svelte-cwls5q">site/src/lib/search/semantic.ts</code>) exposes a <code class="svelte-cwls5q">semanticStatus</code> store the toggle button reads.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">Filter pipeline.</strong> <code class="svelte-cwls5q">filteredIds = $cartOnly ? cartIds : (searchIds ∩ lasso ∩
										facetIds ∩ authorChipIds)</code>. Saved-only is a dominant
										filter (overrides the other three) so the user always sees
										their full saved set; the other stores remain in their state
										so toggling Saved-only off restores them.</li> <li class="svelte-cwls5q"><strong class="svelte-cwls5q">UMAP.</strong> 2D scatter + 3D scatter3d in Plotly,
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
										the Stage 4 deep-dive.</li></ul></aside>`),xe=b(`<p>This site is a static SvelteKit app deployed to GitHub Pages. The data
							package is a single gzipped tarball fetched from a stable CDN URL at
							page load — no server, no database, no per-query backend round-trip.
							Lexical typo-tolerant search runs in the main thread; semantic search
							runs in a Web Worker using <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">MiniLM-L6</a> ONNX through transformers.js, against an int8-quantised vector matrix
							also shipped in the tarball.</p> <p class="muted svelte-cwls5q">Source: <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">github.com/sensein/ohbm2026</a>. Build provenance is in the footer of every page.</p> <button type="button" class="tldr-toggle svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> Technical details</button> <!>`,1),Ae=b('<div class="stage-body svelte-cwls5q"><!></div>'),Se=b('<section class="stage svelte-cwls5q"><button type="button" class="stage-header svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> <span class="stage-label svelte-cwls5q"> </span></button> <!></section>'),Te=b(`<div class="about-page svelte-cwls5q"><nav class="back svelte-cwls5q"><a class="svelte-cwls5q">← back to atlas</a></nav> <header class="svelte-cwls5q"><h1 class="svelte-cwls5q">About the OHBM 2026 Atlas</h1> <p class="lead svelte-cwls5q">A search-and-browse interface for every accepted OHBM 2026 abstract. Each abstract
			is the submitter's own text; everything else on the site — clusters, related-abstract
			suggestions, figure interpretations, claim extractions — is computed from those
			abstracts by an automated pipeline. The pipeline is open-source and reproducible.</p></header> <section class="overview svelte-cwls5q"><p class="svelte-cwls5q">Reading 3,000+ abstracts to find the ones you care about isn't realistic for most
			people. This atlas tries to make that browsable: a free-text + faceted search, a
			2D + 3D map of the corpus coloured by topic cluster, AI-extracted highlights of each
			abstract's claims and figures, and a lightweight saved-list export.</p> <p class="svelte-cwls5q">The pipeline runs in five stages, listed below. Click each one to see how it works.
			Surfaces that were authored or interpreted by an LLM (figure interpretations,
			extracted claims, LLM-grouped topic-cluster titles) carry an <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> pill in the detail panel so the
			provenance is always visible.</p></section> <!></div>`);function Ee(K){let N=J({}),n=J({});function X(A){Q(N,{...r(N),[A]:!r(N)[A]})}function E(A){Q(n,{...r(n),[A]:!r(n)[A]})}const v={oxford:{url:"https://app.oxfordabstracts.com/"},umap:{url:"https://arxiv.org/abs/1802.03426"},leiden:{url:"https://www.nature.com/articles/s41598-019-41695-z"},hdbscan:{url:"https://joss.theoj.org/papers/10.21105/joss.00205"},minilm:{url:"https://arxiv.org/abs/2002.10957"},eco:{url:"https://evidenceontology.org/"},openalex:{url:"https://openalex.org/"},neuroscape_repo:{url:"https://github.com/ccnmaastricht/NeuroScape"},neuroscape_paper:{url:"https://apertureneuro.org/article/156380-the-evolving-landscape-of-neuroscience"},repo:{url:"https://github.com/sensein/ohbm2026"}};var F=Te();he("cwls5q",A=>{de(()=>{ve.title="About · OHBM 2026 Atlas"})});var z=s(F),Y=s(z);t(z);var $=e(z,6);pe($,0,()=>[{key:"fetch",label:"Stage 1 — Fetch & normalise (Oxford Abstracts → JSON)"},{key:"enrich",label:"Stage 2 — AI enrichment (figures + claims + references)"},{key:"embed",label:"Stage 3 — Embeddings (5 models × per-section)"},{key:"analyse",label:"Stage 4 — Communities + clusters + UMAP"},{key:"ui",label:"Stage 6 — This site"}],A=>A.key,(A,a)=>{var U=Se(),O=s(U),H=s(O),Z=s(H,!0);t(H);var V=e(H,2),ee=s(V,!0);t(V),t(O);var se=e(O,2);{var te=W=>{var G=Ae(),ae=s(G);{var le=p=>{var u=me(),i=R(u),f=e(s(i));c(3),t(i);var d=e(i,2),w=s(d),o=s(w,!0);t(w),c(),t(d);var y=e(d,2);{var T=_=>{var k=we();g(_,k)};D(y,_=>{r(n)[a.key]&&_(T)})}S(()=>{l(f,"href",v.oxford.url),l(d,"aria-expanded",!!r(n)[a.key]),P(o,r(n)[a.key]?"▾":"▸")}),C("click",d,()=>E(a.key)),g(p,u)},ce=p=>{var u=ge(),i=R(u),f=e(s(i),5),d=e(f,4);c(),t(i);var w=e(i,4),o=s(w),y=s(o,!0);t(o),c(),t(w);var T=e(w,2);{var _=k=>{var h=qe(),m=s(h),x=e(s(m),8),q=e(s(x),2);c(5),t(x),c(2),t(m),t(h),S(()=>l(q,"href",v.openalex.url)),g(k,h)};D(T,k=>{r(n)[a.key]&&k(_)})}S(()=>{l(f,"href",v.eco.url),l(d,"href",v.openalex.url),l(w,"aria-expanded",!!r(n)[a.key]),P(y,r(n)[a.key]?"▾":"▸")}),C("click",w,()=>E(a.key)),g(p,u)},oe=p=>{var u=fe(),i=R(u),f=e(s(i)),d=e(f,2),w=e(d,2);c(),t(i);var o=e(i,2),y=s(o),T=s(y,!0);t(y),c(),t(o);var _=e(o,2);{var k=h=>{var m=be(),x=s(m),q=e(s(x),6),I=e(s(q),2),L=e(I,2);c(),t(q);var M=e(q,2),j=e(s(M),4);c(7),t(M);var B=e(M,2),ne=e(s(B));ne.nodeValue=` The MiniLM corpus matrix used
										for in-browser semantic search is composed of
										{intro, methods, results, conclusion}, L2-renormalised, then
										int8-quantised with a global scale = `,c(10),t(B),t(x),t(m),S(()=>{l(I,"href",v.neuroscape_paper.url),l(L,"href",v.neuroscape_repo.url),l(j,"href",v.minilm.url)}),g(h,m)};D(_,h=>{r(n)[a.key]&&h(k)})}S(()=>{l(f,"href",v.minilm.url),l(d,"href",v.neuroscape_paper.url),l(w,"href",v.neuroscape_repo.url),l(o,"aria-expanded",!!r(n)[a.key]),P(T,r(n)[a.key]?"▾":"▸")}),C("click",o,()=>E(a.key)),g(p,u)},re=p=>{var u=_e(),i=R(u),f=e(s(i)),d=e(f,2),w=e(d,2);c(),t(i);var o=e(i,4),y=s(o),T=s(y,!0);t(y),c(),t(o);var _=e(o,2);{var k=h=>{var m=ye(),x=s(m),q=s(x),I=e(s(q),6);I.textContent="data/outputs/analysis/annotations__<state-key>.{parquet,sqlite}",c(),t(q);var L=e(q,4),M=e(s(L),2);c(9),t(L);var j=e(L,6),B=e(s(j),2);B.textContent="{title, description, focus}",c(3),t(j),c(4),t(x),t(m),S(()=>l(M,"href",v.leiden.url)),g(h,m)};D(_,h=>{r(n)[a.key]&&h(k)})}S(()=>{l(f,"href",v.umap.url),l(d,"href",v.leiden.url),l(w,"href",v.hdbscan.url),l(o,"aria-expanded",!!r(n)[a.key]),P(T,r(n)[a.key]?"▾":"▸")}),C("click",o,()=>E(a.key)),g(p,u)},ie=p=>{var u=xe(),i=R(u),f=e(s(i));c(),t(i);var d=e(i,2),w=e(s(d));c(),t(d);var o=e(d,2),y=s(o),T=s(y,!0);t(y),c(),t(o);var _=e(o,2);{var k=h=>{var m=ke(),x=s(m),q=e(s(x),4),I=e(s(q),14);I.textContent="{ ids, exactness }",c(),t(q);var L=e(q,8),M=e(s(L),18);M.textContent="goto(stash, { replaceState: true })",c(5),t(L),c(6),t(x),t(m),g(h,m)};D(_,h=>{r(n)[a.key]&&h(k)})}S(()=>{l(f,"href",v.minilm.url),l(w,"href",v.repo.url),l(o,"aria-expanded",!!r(n)[a.key]),P(T,r(n)[a.key]?"▾":"▸")}),C("click",o,()=>E(a.key)),g(p,u)};D(ae,p=>{a.key==="fetch"?p(le):a.key==="enrich"?p(ce,1):a.key==="embed"?p(oe,2):a.key==="analyse"?p(re,3):a.key==="ui"&&p(ie,4)})}t(G),g(W,G)};D(se,W=>{r(N)[a.key]&&W(te)})}t(U),S(()=>{l(U,"data-testid",`about-stage-${a.key}`),l(O,"aria-expanded",!!r(N)[a.key]),P(Z,r(N)[a.key]?"▾":"▸"),P(ee,a.label)}),C("click",O,()=>X(a.key)),g(A,U)}),t(F),S(()=>l(Y,"href",`${ue}/`)),g(K,F)}export{Ee as component};
