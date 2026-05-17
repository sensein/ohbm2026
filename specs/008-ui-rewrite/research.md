# Phase 0 — Research (Stage 6 UI Rewrite)

This document captures the technology-choice rationale behind the Technical Context block of `plan.md`. Each open question from the spec or plan is resolved here in `Decision / Rationale / Alternatives considered` form.

## R1 — Site framework: SvelteKit vs React-Vite vs Astro

### Decision

**SvelteKit 2 + Vite 5 in static-adapter mode (`@sveltejs/adapter-static`).**

### Rationale

- **Smallest framework runtime.** Svelte compiles components to direct DOM operations; the runtime is ~5 KB gzipped. React shipping with Vite or Next is ~50 KB gzipped (react + react-dom) before any product code. Across SC-001 (≤ 3 s first paint) and SC-006 (≤ 8 MB gz first-paint package), every saved KB matters.
- **Fully static output.** `adapter-static` produces a `dist/` of HTML + JS + assets that GitHub Pages can serve directly. No Node runtime, no edge functions, no server rendering required.
- **Per-route code-split.** SvelteKit's file-based routing lazy-loads each route's JS chunk. Plotly + the MiniLM ONNX runtime only download when the user opens the UMAP tab or runs a semantic query — a clean lazy-load contract that satisfies SC-006's first-paint cap.
- **TypeScript-first DX.** First-class TS support with `svelte-check` instead of two-step tsc + bundler glue.
- **Svelte stores are idiomatic** for the kinds of derived state this app has (search query → filtered ids → facet recounts → result list).

### Alternatives considered

- **React + Vite (without Next)** — familiar, large ecosystem, but the runtime cost is 10× Svelte's. Wouldn't fail the SCs, but burns budget that the data package or Plotly could use better.
- **Next.js** — server-rendering features are wasted on a static-only site; the App Router's complexity buys nothing here. Static-export mode works but feels off-label.
- **Astro** — excellent for content-heavy sites with islands of interactivity, but this app is interactivity-heavy throughout (search + UMAP + cart + facets all need reactivity on every page). Forcing every component to be an "island" complicates state sharing.
- **Plain Vanilla + Vite** — minimal runtime cost, but you'd hand-roll routing, state, and templating. Time-to-MVP penalty isn't worth the ~5 KB savings.

## R2 — In-browser ML runtime + embedding model

### Decision

**`@xenova/transformers` (transformers.js) running the quantized `Xenova/all-MiniLM-L6-v2` ONNX checkpoint.** The model loads from the public Hugging Face CDN and is cached by the browser. Embedding inference for a query (single short string) runs in a **Web Worker** to keep the main thread responsive.

### Rationale

- **The user explicitly named MiniLM.** transformers.js's `Xenova/all-MiniLM-L6-v2` checkpoint is the canonical browser port; ~23 MB quantized, ~25 ms inference for a single query on a recent MacBook Air via WebGPU + WASM fallback.
- **CDN-hosted model = no repo bloat.** The 23 MB ONNX weights aren't bundled into our data package (which is gated to 11 MB gz total).
- **Pre-computed corpus vectors avoid running MiniLM 3,244× at runtime.** We compute corpus embeddings once at build time (using the Python `sentence-transformers` model already in our Stage 3 minilm bundle) and ship `[3244, 384]` int8-quantized vectors. At query time, the browser computes ONE 384-dim query embedding via transformers.js, then does cosine sim against the corpus matrix in JS — fast typed-array math.

### Alternatives considered

- **ONNX Runtime Web directly** — finer control but lots of boilerplate to load tokenizer + handle pooling. transformers.js wraps all of that.
- **TensorFlow.js with USE / similar** — larger runtime, larger model (USE-Lite is ~25 MB raw), and we'd need to rebuild corpus vectors with a different model.
- **Skip the in-browser embedding, send queries to a server** — kills the static-only architecture (SC-006 + privacy). Out.
- **Float16 / float32 corpus vectors** — int8 is 4× smaller (1.2 MB vs 4.8 MB) with negligible recall loss for our use; SC-006 demands the smaller footprint.

## R3 — Walkthrough library

### Decision

**`shepherd.js`** (~18 KB gz).

### Rationale

- **Step model fits our needs**: anchored highlight + tooltip + next/prev/skip. Out of the box.
- **No theme dependency.** intro.js bundles a CSS theme; shepherd.js is theme-agnostic and lets us match the rest of the site's CSS.
- **Active maintenance.** Both libs are maintained, but shepherd.js gets more contributors per year and supports Svelte via official examples.

### Alternatives considered

- **intro.js** — also fine, ~14 KB gz. The bundled theme conflicts with our minimal palette; we'd override most of it anyway.
- **Custom-rolled with Svelte transitions + Floating UI** — would shave another ~10 KB but adds ~1–2 days of UX work. Not worth it given the rest of the budget already fits.

## R4 — Plotly bundle for 2D + 3D UMAP

### Decision

**Plotly.js "basic" + "gl3d" custom bundle** (`scatter` + `scattergl` + `scatter3d` + `lasso` traces). ~700 KB gz. Lazy-loaded only when the user opens the projections tab.

### Rationale

- **Lasso is non-trivial elsewhere.** Plotly's lasso event is well-tested across browsers; rolling our own with D3 + a polygon-in-point predicate is doable but adds risk and dev time.
- **3D is free.** The `gl3d` bundle adds rotate/pan/zoom for `scatter3d` traces with no extra code.
- **Lazy-loaded.** Visiting the home page without opening UMAP never downloads Plotly. SvelteKit's dynamic `import()` handles this.

### Alternatives considered

- **deck.gl** — better at million-point scale, but our 3,244-point scatter is well within Plotly's sweet spot, and deck.gl's lasso requires extra plumbing (deck.gl-extensions/lasso).
- **D3 + custom 2D + Three.js for 3D** — finest control, largest dev cost, would lose lasso reliability.

## R5 — Lexical search: index format + edit-distance strategy

### Decision

- **Build time (Python)**: tokenize each abstract's title + sections + keywords + methods + author names into normalized tokens (lowercase, NFC-normalized, accent-folded). For each token, emit **trigrams** (3-character sliding windows). Build an inverted index `{trigram → [token_id], token → {abstract_ids, surface_form}}`. Serialize as a single compact JSON: `lexical_index.json` ≤ 500 KB gz.
- **Query time (browser)**: trigram the user's query into candidate token-id buckets; gather candidates whose trigram overlap with the query ≥ a threshold (≥ 60 %); then run **Damerau-Levenshtein** distance ≤ 2 on those candidates (≤ 1 for words of length < 4). Surface abstracts via posting lists.

### Rationale

- **Trigram pre-filter → DL distance** is the canonical approach (used by PostgreSQL `pg_trgm`, Lucene's `FuzzyQuery`, Elasticsearch's `fuzzy` mode). Lets us run real edit-distance on ≤ 100 candidate tokens per query instead of all ~50 K corpus tokens.
- **Pre-built index** means the browser doesn't pay tokenization cost on cold start.
- **500 KB gz budget** is comfortably feasible: 50 K tokens × ~5 trigrams each × 6 bytes per (trigram, token_id) pair ≈ 1.5 MB raw → ~400 KB gz with json + varint-style postings.

### Alternatives considered

- **MiniSearch / Fuse.js / Lunr.js** — runtime indexers; would force the browser to index 22 MB of abstract text on cold start. Too slow for SC-001.
- **FlexSearch encoded with `tolerant` mode** — ships as a library and provides fast fuzzy; but the resulting in-memory index is ~3 MB after `add()`, and we'd pay that on every cold start.
- **BK-tree on full token vocab** — beautiful data structure but adds CPU cost per query. Trigram pre-filter is simpler and faster at our scale.

## R6 — Author de-duplication + affiliation normalization

### Decision

- **De-duplication key**: `lower(NFC(full_name)) + "|" + lower(NFC(primary_affiliation))`. Same name + same primary affiliation → one author record. Different affiliation → different author record (intentional; "Jane Smith @ Stanford" and "Jane Smith @ MIT" are reasonably-distinct people).
- **Affiliation normalization**: trim, collapse whitespace, fold "&" → "and", remove trailing punctuation. NO heuristic merging of "Stanford University" vs "Stanford U." vs "Stanford" — those stay as 3 affiliations.
- **Storage**: each author record carries an `affiliations: list[str]` (ordered as on the abstract) and `abstract_ids: list[int]` (the abstracts they appear on, in chronological-id order).

### Rationale

- We're shipping organizer-facing data, not running an author-disambiguation research project. Conservative de-dup keeps the data honest about what was actually submitted; aggressive merging risks combining two real people.
- The submitter is the authoritative source for "is this the same person?" — we trust them.

### Alternatives considered

- **OpenAlex author IDs** — our `reference_metadata.json` carries some, but coverage is partial; matching by name alone risks false merges. Defer to v2 if the project decides to integrate OpenAlex author resolution.
- **String-similarity merging (Jaro-Winkler ≥ 0.95)** — too fuzzy; common surnames + abbreviated affiliations create cross-merges.

## R7 — Data-package: per-shard format details

### Decision

- **`abstracts.json`** — JSON array, not NDJSON. We accept the upfront cost of one big parse because (a) it's < 6 MB gz, (b) the browser's native `JSON.parse` is heavily optimized for arrays of similar-shape objects, and (c) NDJSON would require a custom parser and gain little here.
- **Per-cell `cells/<model>_<input>.json`** — JSON arrays, indexed positionally to `abstracts.json` by `abstract_id`. The client builds a `Map<abstract_id, cell_row>` once on load.
- **`minilm_vectors.bin`** — raw little-endian int8 buffer. No header — we know shape `[3244, 384]` from the manifest. Saves ~5 KB of header bytes and simplifies the client decoder to a `new Int8Array(buf)`.

### Rationale

- **JSON over Parquet** — re-locked-in by the Session-2026-05-17 clarification. Parquet would require a JS reader (~50 KB gz) and decoder time that JSON.parse avoids.
- **Plain `Int8Array` for vectors** — Web's typed arrays are zero-copy from `fetch().arrayBuffer()`; the client never builds a JS array of 384 × 3,244 numbers.

### Alternatives considered

- **Apache Arrow IPC files** — columnar, compressed, lazy column reads. Arrow JS is ~80 KB gz. Worth it at much larger scale (millions of rows); at 3,244 rows the JSON path beats it on cold-start latency.
- **JSON Lines (NDJSON) streamed** — wins on streaming-parse for huge files; doesn't pay off below ~50 MB.

## R8 — GitHub Action: deploy + PR-preview architecture

### Decision

- **`deploy-ui.yml`** (trigger: `push` to `main`):
  - Step 1: Set up Python 3.14 + uv; install `[ui]` extras (the new optional-extra to be added in pyproject.toml — `numpy`, `sentence-transformers` for the build-time vector generator).
  - Step 2: Set up Node 20 + pnpm; install `site/` deps.
  - Step 3: Run `scripts/build_ui_data.py --output site/static/data/`. Produces all shards.
  - Step 4: Run `cd site && pnpm test:unit && pnpm test:e2e` (Vitest + Playwright). Test gate.
  - Step 5: Run `cd site && pnpm build`. Emits `site/build/` (SvelteKit's static-adapter output).
  - Step 6: Run the link checker against the About page (Python `link_check.py` against the deployed-but-not-yet-published HTML).
  - Step 7: Use `peaceiris/actions-gh-pages@v3` to push `site/build/` to the `gh-pages` branch's root.
- **`pr-preview.yml`** (trigger: `pull_request` opened/synchronize):
  - Same Steps 1–6 as deploy.
  - Step 7: Push `site/build/` to the `gh-pages` branch under `/pr-<N>/` (NOT replacing root). Use a deploy action that supports `keep_files: true` + `destination_dir: pr-<N>`.
  - **No PR-conversation comment step.** Instead, the workflow declares `environment: { name: pr-preview-<N>, url: <preview_url> }`. GitHub auto-populates the PR's top-of-PR **Deployments box** from the environment, and re-uses the same environment on subsequent pushes (no churn). This is the Session-2026-05-17 clarification.
- **`pr-preview-cleanup.yml`** (trigger: `pull_request` closed): delete `/pr-<N>/` directory from `gh-pages` AND use `actions/github-script@v7` to mark every deployment for the `pr-preview-<N>` environment as `state: "inactive"` via the Deployments API. The Deployments box then shows the deployment as "Inactive" with no live URL.

### Rationale

- **`peaceiris/actions-gh-pages`** is the de-facto GitHub Action for the "push to gh-pages branch" pattern; it handles `.nojekyll`, supports `keep_files`, and is widely audited.
- **One workflow per event** keeps the failure modes legible. The deploy workflow only runs on `main`; the preview workflow only runs on PRs.
- **Deployments-box surface over bot comments.** Per Session-2026-05-17: a workflow `environment:` declaration drives the GitHub Deployments API automatically, so the URL appears in the top-of-PR Deployments box and updates in place on each push. No `peter-evans/find-comment` / `create-or-update-comment` step is needed — the native Deployments surface avoids comment churn entirely and gives reviewers a one-click "View deployment" affordance in a stable PR location.

### Alternatives considered

- **One mega-workflow with branching logic** — concentrates failure surface; less legible. The 3-workflow split is GitHub's recommended pattern.
- **Cloudflare Pages / Vercel previews** — they offer turnkey previews but require setting up a separate hosting account, which the spec rules out (GitHub Pages only). Stays in scope.
- **`actions/deploy-pages`** (the official action) — only supports deploying to the root, not to subdirectories. Wrong tool for PR previews.

## R9 — About page: reference list + link-check architecture

### Decision

The About page references live as a **YAML registry** at `specs/008-ui-rewrite/contracts/references.yaml` (a content-only artifact tracked in source). The Python `link_check.py` builder reads the registry at build time, issues an HTTP HEAD against each URL, and fails the build if any URL returns a non-2xx status. The site's `+page.svelte` for `/about` imports the registry at compile time and renders the deep-dive sections from it.

### Rationale

- **Single source of truth.** References live in one file; the site renders them and the link checker validates them. Adding a new reference is one PR.
- **YAML, not JSON.** Human-edited, multi-line citations, comments allowed. The build step parses YAML once and emits the rendered HTML.
- **Build-time check, not runtime.** Catches dead links before deploy. The spec rules out runtime handling (FR-017 + SC-007).

### Alternatives considered

- **Inline JSX/Svelte literals** — hardcoded references in the component. Adding a reference touches multiple files; the link checker has to parse JSX. Worse DX.
- **External CrossRef / OpenAlex API** — fetches reference metadata live. Adds API rate limits + a build-time external dependency. Out for v1.

## R10 — Open questions deferred to implementation

These are decisions that don't change the spec contract or the plan's structure; they're left for the implementer:

- **Cart UX**: drawer from the right, modal, or full-page route? Will land during US5 based on the wireframe.
- **Tour copy**: per-step text. Drafted by the implementer; reviewed by the user before deploy.
- **Mobile UMAP**: in `≤ 1024 px`, lasso is replaced with "tap to filter by community" (per FR-005 edge case). The exact tap target — a single point's community vs the union of neighbors — is a UX detail not a spec contract.
- **Diacritic handling for author search**: NFC-normalize + accent-fold ("á" → "a"). Standard practice.
