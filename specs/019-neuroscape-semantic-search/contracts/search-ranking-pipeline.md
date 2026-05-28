# Contract: Browser Search Ranking Pipeline

**Status**: Phase 1 contract for spec 019 · **Date**: 2026-05-27

The TypeScript API the SvelteKit UI components call to run a semantic
search. This is the public surface of
`site/src/lib/search/neuroscape_ranker.ts` (NEW) plus the relevant
modifications to `site/src/lib/search/semantic.ts` and
`site/src/lib/workers/semantic.worker.ts`.

---

## 1. Public API

```typescript
// Module: $lib/search/neuroscape_ranker

export type Corpus = 'neuroscape' | 'ohbm2026';

export type RankedHit = {
  corpus: Corpus;
  id: bigint;                  // pubmed_id (NeuroScape) or poster_id (OHBM)
  cluster_id: number | null;   // null for OHBM rows
  cosine: number;              // dequantised cosine similarity to query [0, 1]
  score_source: 'cosine' | 'knn-distance';
                               // 'knn-distance' means we ran out of cluster
                               // budget (FR-024) and ranked by precomputed
                               // KNN distance to the seed instead
};

export type RankerState =
  | 'idle'
  | 'loading-model'
  | 'embedding'
  | 'routing'
  | 'fetching-vectors'
  | 'brute-force'
  | 'knn-expand'
  | 're-rank'
  | 'ready'
  | 'cap-exceeded'
  | 'error';

export interface RankerHooks {
  onState?: (state: RankerState) => void;
  onCapExceeded?: (clustersLoaded: number) => void;
  onError?: (err: Error) => void;
}

/** Parsed query from the shared `$lib/filter.ts::parseQuery` —
 *  contains the operator-stripped string (for semantic encoding,
 *  R-001) plus the structural operator clauses (phrase, negation,
 *  OR groups, id: terms) needed to filter the semantic candidate
 *  set after the worker returns. Same shape on every surface per
 *  FR-025. */
import type { ParsedQuery, LexicalResult } from '$lib/filter';

/** NeuroScape semantic search (called from /neuroscape/'s
 *  NeuroscapeBrowsePanel.svelte). Returns up to `topK` hits ranked
 *  by cosine to query, cluster-routed + KNN-expanded per FR-021.
 *
 *  - The parsed query's `semanticEncodableString` (operator-stripped,
 *    per existing `$lib/filter.ts:295`) feeds the worker query encoder.
 *  - `negationBlocked` ids are subtracted from the returned candidate
 *    list (mirrors OHBM merge behaviour at +page.svelte:439).
 *  - `id:N` clauses short-circuit: if the parsed query has any id:
 *    term, the function returns lexical id-match rows directly + skips
 *    the semantic pipeline (the user typed an explicit id lookup). */
export function searchNeuroscape(
  parsed: ParsedQuery,
  topK: number,
  hooks?: RankerHooks
): Promise<RankedHit[]>;

/** Cross-conference semantic search (called from atlas-root's
 *  AtlasRootSearchBar.svelte). Runs the NeuroScape lane + the OHBM
 *  brute-force lane in parallel; merges by cosine. Per FR-023 no
 *  source-bias weighting.
 *
 *  - `id:N` clauses run in BOTH lanes in parallel (FR-026): poster_id
 *    lookup on OHBM, pubmed_id lookup on NeuroScape. Both matching
 *    rows are returned; the existing source pill identifies which
 *    corpus each came from. */
export function searchAtlasRoot(
  parsed: ParsedQuery,
  topK: number,
  hooks?: RankerHooks
): Promise<RankedHit[]>;

/** Release the FR-024 cluster-budget cap for this session. The next
 *  query that crosses the cap proceeds without prompting. */
export function expandSearchDepth(): void;
```

---

## 2. Worker contract

`site/src/lib/workers/semantic.worker.ts` is extended (not rewritten)
to accept a new init payload shape that supports both the existing
OHBM 2026 flow (full-corpus INT8 buffer, brute-force cosine) AND the
new NeuroScape flow (per-cluster INT8 buffers, lazy-loaded). The
worker exposes:

```typescript
// Worker request messages

| { type: 'init'; corpus: 'ohbm2026'; vectors: ArrayBuffer; dim: 384; scale: number; pubmedIds?: never; posterIds: ArrayBuffer }
| { type: 'init'; corpus: 'neuroscape'; centroids: Float32Array; clusterIds: Int16Array; dim: 384; scale: number }
| { type: 'load-cluster'; cluster_id: number; vectors: ArrayBuffer; pubmedIds: ArrayBuffer }
| { type: 'evict-cluster'; cluster_id: number }
| { type: 'encode-query'; query: string }
| { type: 'route'; query_vector: ArrayBuffer }
| { type: 'brute-force'; cluster_id: number; query_vector: ArrayBuffer; topK: number }
| { type: 'rerank'; candidates: Array<{id: bigint; cluster_id: number}>; query_vector: ArrayBuffer }

// Worker response messages

| { type: 'ready' }
| { type: 'cluster-loaded'; cluster_id: number }
| { type: 'cluster-evicted'; cluster_id: number }
| { type: 'query-encoded'; query_vector: ArrayBuffer }       // transferable
| { type: 'routed'; cluster_id: number; argmax_cosine: number }
| { type: 'brute-force-hits'; cluster_id: number; hits: Array<{id: bigint; cosine: number}> }
| { type: 'reranked'; hits: Array<{id: bigint; cosine: number}> }
| { type: 'error'; reason: string; details?: object }
```

All worker messages use **transferable** ArrayBuffers for vectors to
avoid main-thread copy overhead (~1.5 MB per cluster transfer).

---

## 3. The 5-step pipeline (NeuroScape lane)

`searchNeuroscape(query, topK, hooks)` orchestrates:

```text
1. ENSURE MODEL LOADED
   - state := 'loading-model' if first call this session
   - waits for the worker's 'ready' response

2. EMBED QUERY
   - state := 'embedding'
   - worker.encode-query → query_vector (Float32Array, 384)

3. ROUTE TO CLUSTER
   - state := 'routing'
   - centroids already loaded eagerly with neuroscape.parquet
   - worker.route → routing_cluster_id (argmax cosine over centroids)

4. ENSURE CLUSTER VECTORS LOADED
   - state := 'fetching-vectors' if routing_cluster_id not in LRU
   - check FR-024 cap (default 4 distinct clusters per session):
     - if (LRU.size >= cap AND routing_cluster_id not in LRU):
       - state := 'cap-exceeded'
       - hooks.onCapExceeded?(LRU.size)
       - return early (caller may invoke expandSearchDepth())
   - else: range-fetch routing_cluster_id from neuroscape_vectors.parquet
     via $lib/data_package/loader.loadClusterVectors(routing_cluster_id)
   - worker.load-cluster(cluster_id, vectors, pubmedIds)
   - LRU.set(cluster_id, /* timestamp */)

5. BRUTE-FORCE TOP-3 WITHIN CLUSTER
   - state := 'brute-force'
   - worker.brute-force(routing_cluster_id, query_vector, topK=3)
     → top3_seeds: [{id, cosine}, ...]

6. KNN-EXPAND
   - state := 'knn-expand'
   - knn_table loaded eagerly with neuroscape.parquet (neighbours: LIST<INT64>)
   - candidate_pmids := top3_seeds ∪ KNN(top3_seeds[i].id) for i in [0..2]
   - for each candidate's cluster_id NOT in LRU:
     - if cap permits: load + worker.load-cluster
     - else: mark candidate as score_source='knn-distance' (FR-024 fallback)

7. RE-RANK
   - state := 're-rank'
   - worker.rerank(candidate_pmids, query_vector)
     → ranked: [{id, cosine}, ...]
     (knn-distance candidates appended at the end ranked by their
      precomputed KNN distance to their seed)

8. RETURN
   - state := 'ready'
   - take top `topK`
   - returned RankedHit[] carries corpus='neuroscape' for every row
```

---

## 4. Cross-conference orchestration (atlas-root lane)

`searchAtlasRoot(query, topK, hooks)`:

```text
1. Kick off in parallel:
   - p1 := searchNeuroscape(query, topK, hooks)
   - p2 := bruteForceOhbm(query, topK)   # in-memory cosine over the
                                         # OHBM ohbm_vectors table

2. Wait for BOTH to settle (Promise.allSettled).

3. Merge: concat both result lists, stable-sort by cosine DESCENDING.
   Tie-break (rare with continuous floats): prefer NeuroScape row
   per R-008.

4. Return top `topK`. Each RankedHit carries its original corpus tag.
```

`bruteForceOhbm` is a trivial in-memory pass over the ~3 240 OHBM
vectors loaded with `atlas.parquet`; runs in ~1 ms; no worker round-
trip needed unless the model isn't loaded yet (then it joins the
neuroscape lane in waiting for `loading-model`).

---

## 5. Error semantics

Each state transition can fail. The ranker MUST surface errors via
`hooks.onError(err)` and transition `state := 'error'` (terminal until
the next user query). No silent fallbacks (Constitution VI).

| Error class | Surfaced when | User-visible result |
|---|---|---|
| `ModelLoadError` | HuggingFace CDN fetch fails, model sha256 mismatch | Toggle returns to OFF; banner: "semantic search unavailable" + Retry |
| `RangeFetchError` | hyparquet range request fails (network, byte range out of file, parquet decode error) | Toggle stays ON but query returns lexical-only results + console error |
| `CapExceededError` | FR-024 cluster cap hit; emitted as a hook callback, not a thrown error | One-time banner: "Expand search depth?" with allow/deny buttons |
| `VectorsManifestDriftError` | INV-006 / model_sha256 mismatch | Banner: "semantic index changed — refresh" with Refresh button |

---

## 6. Test contract

Mirrors the existing OHBM 2026 e2e suite in
`site/src/tests/e2e/search.spec.ts`. New unit + e2e cases:

```text
vitest (site/src/tests/unit/neuroscape_ranker.test.ts):
- searchNeuroscape happy path: mocked worker returns canned hits;
  pipeline produces 5 ranked results in the expected order.
- LRU cap: 5th distinct cluster routes triggers onCapExceeded hook
  before fetching.
- expandSearchDepth(): subsequent call DOES fetch.
- Drift: worker init message includes mismatched model_sha256 →
  ModelLoadError surfaced.

playwright (site/src/tests/e2e/semantic.spec.ts):
- /neuroscape/: toggle ON → type concept query → ✨-badged row appears.
- atlas-root: toggle ON → type query → results from BOTH corpora,
  each identified by existing source pill/colouring (no new badge).
- DNT/GPC and PR-preview gates from spec 015.5 still effective.
```
