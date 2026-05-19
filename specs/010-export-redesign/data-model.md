# Phase 1 Data Model — Format-agnostic entities + format-conditional layout

This data model has two layers. The **format-agnostic** layer is locked here and survives every candidate. The **format-conditional** layer is filled in AFTER `research.md` Phase 0 commits to a winner — until then it carries `<FILL POST-BENCH>` markers.

## Layer 1 — Format-agnostic entity inventory

These are the eight entities the SvelteKit UI consumes. They survive any format choice; the only thing that changes is how they're stored on disk and decoded in the browser.

### Manifest

- One per deployed conference.
- Carries `build_info` (corpus_state_key, stage4_rollup_state_key, code_revision, code_revision_short, built_at, builder_version).
- Carries `conference_id` (NEW per FR-206 — placement decided post-bench).
- Carries `format` (NEW — a string identifying which candidate was committed, so the runtime decoder picks the right loader at runtime).
- Carries an inventory of every shard / table the deployed export contains, with each entry's relative path / table name and (where applicable) a sha256 for integrity.
- Inherits the Stage-6 `ManifestCell` substructure (per-(model, input) cell pointers + per-cell topic shard pointers) — these stay; the cell-to-shard pointer shape adapts to the chosen format.

### Abstract

- One per accepted abstract in the corpus.
- Keys: `abstract_id` (int, the Stage-1 GraphQL submission id), `poster_id` (string, the program-assigned tag, e.g. `M-AM-101`).
- Body: `title`, `accepted_for`, `sections` (introduction / methods / results / conclusion / references — five long-text fields), `topics` (primary / primary_subcategory / secondary / secondary_subcategory), `methods_checklist` (multi-valued string), `facets` (the 11 keyword/method/etc. lists — Stage-6 `range: Any` slot, MUST tighten), `author_ids` (multi-valued int), `reference_dois` / `reference_urls` / `reference_titles` (parallel arrays — MUST gain cross-validation per FR-202).

### Author

- One per author across the corpus.
- Keys: `author_id` (synthetic int), `name` (string after Stage-1 normalisation).
- Body: `affiliations` (multi-valued string), `abstract_ids` (multi-valued int — reverse index).

### Cell

- One per `(model, input)` combination (today: 5 models × 3 inputs = 15 cells per conference).
- Keys: `cell_key` (e.g. `voyage_abstract`), `model`, `input`.
- Body: per-abstract rows carrying `abstract_id`, `umap2d` (float[2]), `umap3d` (float[3]), `community_id`, `topic_cluster_id`, optionally `neuroscape_cluster_id` (only for `model == "neuroscape"`).
- Tightening targets (FR-202): the UMAP arrays MUST gain explicit cardinality constraints; missing-UMAP records MUST use a sparse representation, not a `umap_missing` flag.

### Topic

- One per cluster across each `(model, input, kind)` tuple.
- Keys: `cell_key`, `kind` (communities / neuroscape_clusters / topic_clusters), `cluster_id`.
- Body: `Keywords` (multi-valued string), `Title`, `Description`, `Focus`. The architect-agent review (FR-209) checks whether `Description` and `Focus` carry length bounds — Stage-6 has none.

### Neighbour

- Per-(model, input) k-nearest + k-farthest pairs.
- Keys: `cell_key`, `abstract_id`.
- Body: `nearest_ids` (int[k]), `nearest_distances` (float[k]), `farthest_ids` (int[k]), `farthest_distances` (float[k]). Stage-6 stores at full float64 precision; the bench measures whether float16 / int8-quantized distances preserve UI ranking.

### EnrichmentRecord

- One per abstract that has enrichment output.
- Keys: `abstract_id`.
- Body: `claims` (multi-valued ClaimRecord — each with `text`, `source` (long quote), `evidence` (model-generated explanation), `evidence_eco_codes` (multi-valued string, MUST gain enum per FR-202), `confidence`); `figures` (multi-valued FigureRecord — each with `caption_guess`, `interpretation` (long text), `ocr_text`, `keywords`); `ai_provenance` (model identifiers + flex-tier flags).
- Stage-6 stores this as `{str(abstract_id): EnrichmentRecord}` — the third `range: Any` slot. MUST tighten by promoting `abstract_id` to a column.

### MinilmVectorsSidecar

- One per conference.
- Body: int8-quantised MiniLM-L6 embeddings, shape `(N_abstracts, 384)`. Stored as a binary blob today (`minilm_vectors.bin`); the bench evaluates whether moving it into the chosen format's container (Parquet binary column? SQLite blob? DuckDB blob?) costs more than the sidecar.

### CrossConferenceLink (NEW per FR-208)

- One per cross-conference linking entry.
- Keys: `conf_a`, `id_a`, `conf_b`, `id_b`.
- Body: `link_kind` (enum: `embedding_neighbour`, `claim_overlap`, `citation`), `similarity` (float, semantics depend on `link_kind`), `metadata` (optional, format-specific extras).
- Storage shape decided post-bench; sits in a separate table / file / shard from the per-conference entities (FR-207 — no-regenerate guarantee).

## Layer 2 — Format-conditional table layout

> Filled in AFTER `research.md` Phase 0 commits a winner.

### Storage container

`<FILL POST-BENCH>` — one of: gzipped JSON tarball (status quo, tightened), multi-file Parquet directory, Parquet + DuckDB-WASM, single-file SQLite, single-file DuckDB, Arrow IPC bundle.

### Per-entity table / file layout

For each entity above, the chosen format's column types, primary keys, and index plan. Example shapes (illustrative — actual values land post-bench):

- If the winner is **single-file SQLite**: an `abstracts` table with FTS5 over `title + sections.*`, `(poster_id, abstract_id)` as composite key; an `enrichment_claims` table joined on `abstract_id`; an `embedding_vectors` table with the int8 blobs as `BLOB` columns; etc.
- If the winner is **multi-file Parquet**: per-table `.parquet` files (`abstracts.parquet`, `authors.parquet`, etc.) with row-group sizes tuned per the bench's range-fetch economics; cross-conf as a separate `cross_conference_links.parquet`.
- If the winner is **status-quo-tightened gzip**: today's directory layout minus unused fields + with binary sidecars for dense numerics + the tightened LinkML schema.

### `conference_id` placement

`<FILL POST-BENCH>` — envelope-only, per-record column, or per-file header. The bench's per-candidate notes inform the choice.

### Cross-conference linking surface

`<FILL POST-BENCH>` — pre-computed pair shard / table OR runtime JOIN / nearest-neighbour query. Names the specific table or query shape.

## Layer 3 — Validation rules (format-agnostic)

These hold regardless of format:

| Rule | Where enforced | Failure mode |
|---|---|---|
| Manifest's `format` field matches the runtime decoder's chosen loader | `site/src/lib/data_package/index.ts` | Decoder picks wrong loader → silent corrupt reads. Tested by a unit test against every candidate's manifest. |
| Every shard's `build_info.conference_id` matches the URL subpath | `scripts/validate_ui_data.sh` extended | Mismatch blocks deploy. Adds 1 line of validation. |
| `Abstract.author_ids` reference rows present in `Author` table | Validator script | Validator emits warning per orphan, non-zero exit at >10 orphans. |
| Parallel arrays (`reference_dois`, `reference_urls`, `reference_titles`) have matching `len()` per record | Validator script | Validator non-zero exit on first mismatch. FR-202. |
| Cross-conference links reference rows present in BOTH conferences' tables | Validator script | Non-zero exit on first orphan. FR-208. |
| LinkML schema validates 68 / 68 shards (or the chosen format's table count) | `scripts/validate_ui_data.sh` | Non-zero exit blocks deploy. FR-201 / SC-204. |
| `range: Any` count is zero OR every occurrence has `# LIMITATION:` annotation | A new grep-based lint in `scripts/validate_ui_data.sh` | Non-zero exit. FR-201 / SC-203. |

## State transitions

None. The data model is read-only at runtime.
