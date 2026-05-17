# Phase 1 — Data Model (Stage 6 UI Rewrite)

This document specifies the **per-shard JSON field schemas** that satisfy spec FR-019. It is the canonical reference both for the Python builders under `src/ohbm2026/ui_data/` and for the TypeScript shard-loader under `site/src/lib/shards.ts`.

Every shard is **accepted-only** — withdrawn abstracts are filtered out at build time and never reach any shard.

## 0. Shared types

```text
abstract_id    : int32    — Stage 1 corpus id; stable across rebuilds for unchanged corpora.
poster_id      : str      — program-assigned poster id (e.g. "M-AM-101"); user-facing identifier per FR-002.
author_id      : int32    — synthetic id assigned at build time; stable across rebuilds via the dedup key in research.md R6.
model_key      : enum     — one of {"voyage", "minilm", "openai", "pubmedbert", "neuroscape"}.
input_key      : enum     — one of {"abstract", "claims", "methods"}.
cell_key       : str      — `<model_key>_<input_key>` (e.g. "neuroscape_abstract"). 15 cells.
clustering_kind: enum     — one of {"communities", "neuroscape_clusters", "topic_clusters"}.
build_info     : object   — {corpus_state_key: str, code_revision: str, code_revision_short: str (first 7 chars of `code_revision`, e.g. "a1b2c3d"), stage4_rollup_state_key: str, built_at: str(ISO 8601 UTC)}.
```

## 1. `data/manifest.json` (≤ 5 KB gz)

```json
{
  "schema_version": "ui.v1",
  "build_info": { "...": "see Shared types" },
  "corpus_count": 3244,
  "default_cell": { "model": "neuroscape", "input": "abstract" },
  "models": ["voyage", "minilm", "openai", "pubmedbert", "neuroscape"],
  "inputs": ["abstract", "claims", "methods"],
  "cells": [
    {
      "cell_key": "neuroscape_abstract",
      "model": "neuroscape",
      "input": "abstract",
      "shard_url": "data/cells/neuroscape_abstract.json",
      "topic_shards": {
        "communities":         "data/topics/neuroscape_abstract_communities.json",
        "neuroscape_clusters": "data/topics/neuroscape_abstract_neuroscape_clusters.json",
        "topic_clusters":      "data/topics/neuroscape_abstract_topic_clusters.json"
      },
      "byte_size_gz": 47512
    }
    /* ...14 more cells */
  ],
  "facets": [
    {"key": "accepted_for", "label": "Accepted for", "options": ["Poster", "Oral", "Symposium", "..."]},
    {"key": "primary_topic", "label": "Primary topic", "options": ["..."]},
    /* ...11 more facet keys per spec entity list */
  ],
  "search": {
    "lexical_index": "data/search/lexical_index.json",
    "minilm_vectors": "data/search/minilm_vectors.bin",
    "minilm_vectors_build_info_url": "data/search/minilm_vectors.build_info.json",
    "minilm_dim": 384,
    "minilm_dtype": "int8"
  }
}
```

**Validation rules**

- `default_cell` MUST appear in `cells`.
- Every entry in `cells` MUST have a discoverable `shard_url` that 200s (build-time check).
- `corpus_count` MUST equal `len(abstracts.json)` (build-time assert).
- `facets[].options` MUST be the union of distinct values across the corpus for that facet key, sorted alphabetically except `accepted_for` which carries program-order.
- `byte_size_gz` is the actual gzipped size on disk, useful for client-side budget telemetry.

## 2. `data/abstracts.json` (≤ 6 MB gz)

Shard envelope. `build_info` is byte-identical to the same block in `manifest.json` (FR-019 + CA-008 + §8 invariant 6):

```json
{
  "schema_version": "abstracts.v1",
  "build_info": { "...": "see Shared types" },
  "abstracts": [ /* 3,244 records, schema below */ ]
}
```

Each record in `abstracts[]`:

```json
{
  "abstract_id": 49213,
  "poster_id": "M-AM-101",
  "title": "Memory fMRI in aging",
  "accepted_for": "Poster",
  "sections": {
    "introduction": "...markdown...",
    "methods": "...markdown...",
    "results": "...markdown...",
    "conclusion": "...markdown...",
    "references": "...markdown..."
  },
  "topics": {
    "primary": "Lifespan Development",
    "primary_subcategory": "Aging",
    "secondary": "Neuroinformatics and Data Sharing",
    "secondary_subcategory": "Informatics Other"
  },
  "methods_checklist": ["Functional MRI", "Diffusion MRI"],
  "facets": {
    "study_type": "task-activation",
    "population": "healthy",
    "field_strength": "3T",
    "processing_packages": ["fmriprep", "FSL"],
    "species": ["Human"],
    "recording_technology": ["fMRI", "Diffusion MRI"],
    "brain_regions": ["Hippocampus", "Default Mode Network"],
    "brain_networks": ["Default Mode Network"],
    "keywords": ["Aging", "MRI"]
  },
  "author_ids": [101, 102, 103],
  "reference_dois": ["10.1038/nn.4504", "10.1016/j.neuroimage.2019.116189"],
  "reference_urls": [
    "https://doi.org/10.1038/nn.4504",
    "https://doi.org/10.1016/j.neuroimage.2019.116189"
  ]
}
```

**Validation rules**

- `accepted_for != "Withdrawn"` for **every** record — build-time assert; failure aborts deploy.
- `poster_id` is unique across the corpus (build-time assert).
- `author_ids` references existing ids in `authors.json` (build-time referential check).
- `submission_id` is **never** emitted (FR-002).
- `topics.primary` + `topics.secondary` are extracted from the submission form's `Primary Parent Category & Sub-Category` and `Secondary Parent Category & Sub-Category` responses; missing values → empty string, not `null`.
- `methods_checklist` lists the values from the "Please indicate which methods were used in your research:" submission question, split on `;` and trimmed.
- `facets.brain_regions`, `facets.brain_networks`, `facets.species`, `facets.recording_technology` are extracted via the same regex patterns the current `ui.py:build_domain_facets` already uses (kept in Python so they're language-agnostic).
- `reference_dois` and `reference_urls` are parallel arrays (same index = same reference); empty string fills the slot if either is missing.

## 3. `data/authors.json` (≤ 1.5 MB gz)

Shard envelope; `build_info` byte-identical to the manifest's (§8 invariant 6):

```json
{
  "schema_version": "authors.v1",
  "build_info": { "..." },
  "authors": [
    {
      "author_id": 101,
      "name": "Jane Smith",
      "affiliations": ["Department of Psychology, Stanford University"],
      "abstract_ids": [49213, 49544]
    }
    /* ~12,000 total records */
  ]
}
```

**Validation rules**

- `author_id` is unique; assigned at build time via the dedup key in research.md R6.
- `abstract_ids` references existing accepted abstracts only.
- `name` is preserved verbatim (NFC-normalized but not transliterated); diacritics survive.
- `affiliations[0]` is the primary affiliation; subsequent entries are secondary affiliations in the order the submitter listed them.

## 4. `data/cells/<model>_<input>.json` (15 files, each ≤ 100 KB gz)

Shard envelope per cell; `build_info` byte-identical to the manifest's:

```json
{
  "schema_version": "cell.v1",
  "build_info": { "..." },
  "cell_key": "neuroscape_abstract",
  "rows": [
    {
      "abstract_id": 49213,
      "umap2d": [3.142, -1.591],
      "umap3d": [3.140, -1.589, 0.815],
      "community_id": 7,
      "topic_cluster_id": 142
    }
    /* ...3,244 records, indexed by position to match abstracts.json's order */
  ]
}
```

For the **3 `neuroscape_*` cells only**, each record also carries:

```json
{
  "neuroscape_cluster_id": 89,
  "neuroscape_cluster_distance": 1.012
}
```

**Validation rules**

- Length of array = `manifest.corpus_count` (3,244).
- `abstract_id` order in this file matches the order in `abstracts.json` (positional join). Build-time assert: `for i in range(N): cells[i].abstract_id == abstracts[i].abstract_id`.
- `umap2d` is a 2-element float array; `umap3d` is a 3-element float array. NaNs are not permitted (build-time assert).
- `community_id` and `topic_cluster_id` reference cluster ids that appear in the corresponding `topics/*.json` shard.
- Cells for non-neuroscape models MUST NOT carry `neuroscape_cluster_*` fields (those cells weren't computed per FR-002 in Stage 4).

## 5. `data/topics/<model>_<input>_<kind>.json` (≤ 45 files, each ≤ 30 KB gz)

Shard envelope per (cell, kind); `build_info` byte-identical to the manifest's:

```json
{
  "schema_version": "topics.v1",
  "build_info": { "..." },
  "cell_key": "neuroscape_abstract",
  "kind": "communities",
  "topics": [
    {
      "cluster_id": 7,
      "keywords": ["functional connectivity", "default mode network", "fmri"],
      "title": "Default Mode Network in fMRI",
      "description": "Community 7 spans abstracts on resting-state DMN ...",
      "focus": "methodologies"
    }
    /* ... */
  ]
}
```

**Validation rules**

- `cluster_id` matches the values used in the cells shard's `community_id` / `topic_cluster_id` / `neuroscape_cluster_id` fields.
- `keywords` is non-empty (when `--skip-llm-topics` was set in Stage 4, the keywords come from the local c-TF-IDF pass; `title` + `description` + `focus` may be empty in that case).
- For `<kind>=neuroscape_clusters`, the title / description / keywords / focus are sourced from `data/inputs/neuroscape/cluster_table.csv` verbatim (no LLM grouping).
- For `<kind>=communities` and `<kind>=topic_clusters`, the values come from each Stage 4 bundle's `topics.json` (the hybrid spaCy + c-TF-IDF + LLM grouping pipeline).

## 6. `data/search/lexical_index.json` (≤ 500 KB gz)

Schema is internal to the lexical-search engine; documented for traceability:

```json
{
  "schema_version": "lexical.v1",
  "build_info": { "..." },
  "tokens": [
    {
      "token_id": 0,
      "surface": "memory",
      "trigrams": ["mem", "emo", "mor", "ory"],
      "postings": [49213, 49544, 49901, /* ...abstract_ids that contain this token */]
    },
    /* ~50K tokens */
  ],
  "trigram_index": {
    "mem": [0, 142, 1057, /* ...token_ids whose surface contains "mem" */],
    /* ~12K trigrams */
  }
}
```

**Validation rules**

- Tokens are NFC-normalized, lowercased, accent-folded.
- `postings` lists are sorted ascending and contain only accepted-abstract ids.
- `trigram_index` is the inverse of `tokens[].trigrams` to enable fast query-trigram → candidate-token lookup.
- Stopwords (`the`, `a`, `and`, `of`, `in`, `to`, `for`, `with`, `on`, `at`, `by`, `is`, `was`, `were`, `are`) are dropped at index time.

## 7. `data/search/minilm_vectors.bin` (≤ 1.5 MB) + `data/search/minilm_vectors.build_info.json` (sidecar)

The vectors themselves are a raw little-endian buffer of int8 values, shape `[3244, 384]` row-major. Indexed by position to match `abstracts.json` order. The browser decodes via `new Int8Array(buf)`.

Because a raw binary buffer cannot embed JSON, the build_info travels in a sidecar JSON file at the same URL stem (`minilm_vectors.build_info.json`). The manifest's `search.minilm_vectors_build_info_url` points at the sidecar.

```json
{
  "schema_version": "minilm_vectors.v1",
  "build_info": { "..." },
  "shape": [3244, 384],
  "dtype": "int8",
  "byte_offset_url": "data/search/minilm_vectors.bin"
}
```

**Validation rules**

- Byte length of the `.bin` = `3244 * 384` = 1,245,696 bytes (≤ 1.5 MB).
- The sidecar `build_info` is byte-identical to the manifest's (§8 invariant 6).
- Quantization preserves cosine similarity: `cos(q, v_int8 / 127) ≈ cos(q, v_float32)` within ε = 0.005 on a held-out subset. Build-time assertion: pick 100 random pairs, verify the int8 → float32 cosine recovers the float32 reference within 0.5 %.

## 8. Build-time invariants (cross-shard)

These invariants are asserted by the Python builder (`src/ohbm2026/ui_data/builder.py`) at the end of every build:

1. `len(abstracts.json.abstracts) == manifest.corpus_count == 3244`.
2. For every cell shard, `len(cell_shard.rows) == 3244` and positional join with `abstracts.json.abstracts` holds.
3. Every `accepted_for != "Withdrawn"` in every shard (the accepted-only invariant — failure means a withdrawn record leaked through; abort deploy).
4. Every `author_id` in `abstracts.json:abstracts[].author_ids` exists in `authors.json:authors[]`.
5. Every `community_id` / `topic_cluster_id` / `neuroscape_cluster_id` in each cell shard exists in the matching `topics/*.json:topics[]`.
6. Every JSON shard MUST carry a top-level `build_info` block (and the `minilm_vectors.bin` MUST have its sidecar `minilm_vectors.build_info.json` co-located); all `build_info` blocks across the build are byte-identical (same corpus + same rollup + same code rev → same build-info). Raw-array JSON shards are forbidden — every shard is an object envelope.
7. All About-page reference URLs in `contracts/references.yaml` return HTTP 2xx (link checker; aborts deploy on any failure per CA-006 + SC-007).
8. Sum of shard `byte_size_gz` ≤ size budget per SC-006.

## 9. Browser-side derived state (not a shard)

For completeness — what the client builds in memory after fetching shards:

- `abstractsByPosterId: Map<string, Abstract>` — for direct-link routing `/abstract/<poster_id>`.
- `abstractsById: Map<int, Abstract>` — for cell-shard joins.
- `authorsById: Map<int, Author>` — for detail-panel rendering.
- `cellByKey: Map<string, Map<int, CellRow>>` — lazy-populated; cleared via LRU when memory pressure detected.
- `facetCountsByActiveSelection: Map<facet_key, Map<option, count>>` — recomputed on every selection change.

None of these structures are persisted; they live in Svelte stores or component-local state.
