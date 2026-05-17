import{a as h,f as u,s as S,e as z}from"../chunks/CfsBuQlH.js";import{s as r}from"../chunks/DJqCkxES.js";import{be as v,a8 as G,$ as V,U as o,aS as n,b4 as t,ae as g,aF as X,aX as J,aH as d,ab as M}from"../chunks/grBROpRT.js";import{i as T}from"../chunks/BAdNfywN.js";import{e as K}from"../chunks/C--ridr8.js";import{h as Q}from"../chunks/DaX5jQg-.js";import{d as Y}from"../chunks/DCrapy9v.js";var Z=u(`<p>We pull the accepted-abstract corpus from the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Oxford Abstracts GraphQL API</a>, paginating through every accepted submission. Each record carries
							its program-assigned <em>poster id</em>, authors + affiliations,
							submitter-typed abstract sections (introduction / methods / results /
							conclusion), and the answers to the submission-form "extra questions"
							that drive our facets (methods, study type, population, etc.). Withdrawn
							submissions never reach this site — they're filtered out at this stage.</p>`),$=u(`<p>Each abstract is passed to an LLM (currently <code class="svelte-cwls5q">gpt-5.4-mini</code>) twice:
							once to extract structured <em>claims</em> with the <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Evidence and Conclusion Ontology</a> annotating each piece of evidence, and once per figure to produce a
							written <em>interpretation</em>. Both outputs are cached by content hash so
							re-runs only pay for changed records. References are split out of the
							submitter's text via the same LLM, then resolved to canonical DOIs via <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">OpenAlex</a>.</p> <p>These two surfaces — figure interpretations and claims — are the only
							pieces of the site that are LLM-written. They're always tagged <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> with the model identifier in the
							tooltip so readers can decide how much to trust them. Verbatim
							submitter content (abstract sections, topic dropdowns, methods
							checklists, authors) carries no such pill — that text is theirs.</p>`,1),ee=u(`<p>We compute sentence-level embeddings for every abstract using five
							different encoder families: a public general-purpose model
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">MiniLM-L6</a>), a domain-specific biomedical model (PubMedBERT), two commercial APIs
							(OpenAI, Voyage), and our project-specific NeuroScape model
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Aperture Neuro paper</a>, <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">code</a>). Embeddings are computed per section (title / introduction /
							methods / results / conclusion / claims) and composed into bundles at
							read time, so the UI can show the same corpus through different "lenses".</p>`),ae=u(`<p>For each (model, input) combination we build a UMAP layout
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">McInnes 2018</a>) in 2D and 3D, run Leiden community detection
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">Traag 2019</a>) on the nearest-neighbour graph to find topic clusters, and HDBSCAN
							(<a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">McInnes 2017</a>) for a density-based view. An LLM names each community by reading a
							representative sample of titles from inside it; those names are what
							you see in the "Cluster (current map)" facet and in the UMAP hover
							tooltips.</p> <p>The same per-(model, input) bundle drives the "Most similar" and "Most
							different" lists in the detail panel — we precompute the 10 nearest +
							10 farthest abstracts per record per cell. The detail panel then
							aggregates across all 15 cells so the similar-list reflects every
							"lens" rather than just the currently-selected one.</p>`,1),te=u(`<p>This site is a static SvelteKit app deployed to GitHub Pages. The data
							package is a single gzipped tarball fetched from a stable CDN URL at
							page load — no server, no database, no per-query backend round-trip.
							Lexical typo-tolerant search runs in the main thread; semantic search
							runs in a Web Worker using <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">MiniLM-L6</a> ONNX through transformers.js, against an int8-quantised vector matrix
							also shipped in the tarball.</p> <p class="muted svelte-cwls5q">Source: <a target="_blank" rel="noopener noreferrer" class="svelte-cwls5q">github.com/sensein/ohbm2026</a>. Build provenance is in the footer of every page.</p>`,1),se=u('<div class="stage-body svelte-cwls5q"><!></div>'),re=u('<section class="stage svelte-cwls5q"><button type="button" class="stage-header svelte-cwls5q"><span class="caret svelte-cwls5q"> </span> <span class="stage-label svelte-cwls5q"> </span></button> <!></section>'),oe=u(`<div class="about-page svelte-cwls5q"><nav class="back svelte-cwls5q"><a class="svelte-cwls5q">← back to atlas</a></nav> <header class="svelte-cwls5q"><h1 class="svelte-cwls5q">About the OHBM 2026 Atlas</h1> <p class="lead svelte-cwls5q">A search-and-browse interface for every accepted OHBM 2026 abstract. Each abstract
			is the submitter's own text; everything else on the site — clusters, related-abstract
			suggestions, figure interpretations, claim extractions — is computed from those
			abstracts by an automated pipeline. The pipeline is open-source and reproducible.</p></header> <section class="overview svelte-cwls5q"><p class="svelte-cwls5q">Reading 3,000+ abstracts to find the ones you care about isn't realistic for most
			people. This atlas tries to make that browsable: a free-text + faceted search, a
			2D + 3D map of the corpus coloured by topic cluster, AI-extracted highlights of each
			abstract's claims and figures, and a lightweight saved-list export.</p> <p class="svelte-cwls5q">The pipeline runs in five stages, listed below. Click each one to see how it works.
			Surfaces that were authored or interpreted by an LLM (figure interpretations,
			extracted claims, LLM-grouped topic-cluster titles) carry an <span class="ai-pill-demo svelte-cwls5q">✨ AI</span> pill in the detail panel so the
			provenance is always visible.</p></section> <!></div>`);function ue(I){let f=X({});function O(m){J(f,{...g(f),[m]:!g(f)[m]})}const l={oxford:{url:"https://app.oxfordabstracts.com/"},umap:{url:"https://arxiv.org/abs/1802.03426"},leiden:{url:"https://www.nature.com/articles/s41598-019-41695-z"},hdbscan:{url:"https://joss.theoj.org/papers/10.21105/joss.00205"},minilm:{url:"https://arxiv.org/abs/2002.10957"},eco:{url:"https://evidenceontology.org/"},openalex:{url:"https://openalex.org/"},neuroscape_repo:{url:"https://github.com/sensein/neuroscape"},neuroscape_paper:{url:"https://apertureneuro.org/article/124574-neuroscape-a-domain-specific-embedding-for-neuroscience-abstracts"},repo:{url:"https://github.com/sensein/ohbm2026"}};var y=oe();Q("cwls5q",m=>{G(()=>{V.title="About · OHBM 2026 Atlas"})});var _=o(y),B=o(_);n(_);var D=t(_,6);K(D,0,()=>[{key:"fetch",label:"Stage 1 — Fetch & normalise (Oxford Abstracts → JSON)"},{key:"enrich",label:"Stage 2 — AI enrichment (figures + claims + references)"},{key:"embed",label:"Stage 3 — Embeddings (5 models × per-section)"},{key:"analyse",label:"Stage 4 — Communities + clusters + UMAP"},{key:"ui",label:"Stage 6 — This site"}],m=>m.key,(m,i)=>{var w=re(),b=o(w),k=o(b),E=o(k,!0);n(k);var L=t(k,2),N=o(L,!0);n(L),n(b);var P=t(b,2);{var j=q=>{var x=se(),C=o(x);{var H=a=>{var e=Z(),s=t(o(e));d(3),n(e),v(()=>r(s,"href",l.oxford.url)),h(a,e)},U=a=>{var e=$(),s=M(e),c=t(o(s),5),p=t(c,4);d(),n(s),d(2),v(()=>{r(c,"href",l.eco.url),r(p,"href",l.openalex.url)}),h(a,e)},W=a=>{var e=ee(),s=t(o(e)),c=t(s,2),p=t(c,2);d(),n(e),v(()=>{r(s,"href",l.minilm.url),r(c,"href",l.neuroscape_paper.url),r(p,"href",l.neuroscape_repo.url)}),h(a,e)},R=a=>{var e=ae(),s=M(e),c=t(o(s)),p=t(c,2),A=t(p,2);d(),n(s),d(2),v(()=>{r(c,"href",l.umap.url),r(p,"href",l.leiden.url),r(A,"href",l.hdbscan.url)}),h(a,e)},F=a=>{var e=te(),s=M(e),c=t(o(s));d(),n(s);var p=t(s,2),A=t(o(p));d(),n(p),v(()=>{r(c,"href",l.minilm.url),r(A,"href",l.repo.url)}),h(a,e)};T(C,a=>{i.key==="fetch"?a(H):i.key==="enrich"?a(U,1):i.key==="embed"?a(W,2):i.key==="analyse"?a(R,3):i.key==="ui"&&a(F,4)})}n(x),h(q,x)};T(P,q=>{g(f)[i.key]&&q(j)})}n(w),v(()=>{r(w,"data-testid",`about-stage-${i.key}`),r(b,"aria-expanded",!!g(f)[i.key]),S(E,g(f)[i.key]?"▾":"▸"),S(N,i.label)}),z("click",b,()=>O(i.key)),h(m,w)}),n(y),v(()=>r(B,"href",`${Y}/`)),h(I,y)}export{ue as component};
