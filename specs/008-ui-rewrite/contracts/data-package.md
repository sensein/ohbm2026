# Contract: UI Data Package (post-build)

The data package is the **public file-system contract** between the Python builders and the Svelte site. Anything else (storage engines, query layers, ML runtimes) is implementation detail; this contract is what the site fetches.

## Files

| Path | Format | Lazy? | Max gz size | Schema reference |
|---|---|---|---|---|
| `data/manifest.json` | JSON object | no | 5 KB | data-model.md §1 |
| `data/abstracts.json` | JSON array | no | 6 MB | data-model.md §2 |
| `data/authors.json` | JSON array | no | 1.5 MB | data-model.md §3 |
| `data/cells/<model>_<input>.json` | JSON array | yes (non-default cells) | 100 KB each | data-model.md §4 |
| `data/topics/<model>_<input>_<kind>.json` | JSON array | yes (non-default cells/kinds) | 30 KB each | data-model.md §5 |
| `data/search/lexical_index.json` | JSON object | no | 500 KB | data-model.md §6 |
| `data/search/minilm_vectors.bin` | binary `Int8Array` | yes (first semantic query) | 1.5 MB | data-model.md §7 |

## Stable URL conventions

- All paths are **relative to the site root**. With GitHub Pages serving from `https://<org>.github.io/<repo>/`, the manifest lives at `https://<org>.github.io/<repo>/data/manifest.json`.
- PR previews mount the **same** relative layout under `https://<org>.github.io/<repo>/pr-<N>/data/manifest.json`. The site never hardcodes the base; it uses SvelteKit's `base` config.
- File names use only `[a-z0-9_]+` plus `.json` / `.bin` extensions — no spaces, no special characters.

## Loading order (browser)

1. **Manifest** — fetched first; everything else's URL is in here.
2. **Parallel fan-out** after manifest resolves:
   - `abstracts.json`
   - `authors.json`
   - `cells/<default_cell>.json` (the default `neuroscape_abstract` cell)
   - `topics/<default_cell>_communities.json`, `..._neuroscape_clusters.json`, `..._topic_clusters.json`
   - `search/lexical_index.json`
3. **On-demand**:
   - `cells/<other_cell>.json` when the user switches the (model, input) selector.
   - `topics/<other_cell>_<kind>.json` lazy-loaded with its cell.
   - `search/minilm_vectors.bin` on the first semantic query.

## Invariants

- **Accepted-only.** `accepted_for != "Withdrawn"` for every record in every shard.
- **Positional join.** `cells/<cell>.json[i].abstract_id == abstracts.json[i].abstract_id` for all `i ∈ [0, 3244)`.
- **Referential integrity.** Every `author_id` in `abstracts.json` exists in `authors.json`; every `*_cluster_id` exists in the matching topics file.
- **Provenance block.** Every shard's `build_info` block is byte-identical (same corpus + same rollup + same code revision).
- **Determinism.** The build is reproducible: same inputs → same shard SHA-256 hashes (modulo the `built_at` timestamp).

## Versioning

The manifest's `schema_version` field is the contract version. Bumping it triggers a deliberate site-side migration; the site refuses to load an unknown schema_version (with a user-facing error).

## Build command

```bash
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
  --corpus data/primary/abstracts.json \
  --withdrawn data/primary/abstracts_withdrawn.json \
  --authors data/primary/authors.json \
  --enriched data/primary/abstracts_enriched.sqlite \
  --references data/primary/reference_metadata.json \
  --rollup data/outputs/analysis/annotations__<state-key>.sqlite \
  --analysis-root data/outputs/analysis \
  --minilm-bundle data/outputs/embeddings/minilm/title__<state-key> \
  --references-yaml specs/008-ui-rewrite/contracts/references.yaml \
  --output site/static/data/
```

Exit codes:
- `0` — all shards written; all invariants satisfied; link checker passed.
- `2` — corpus mismatch or referential-integrity failure (Principle VI: fail loudly).
- `3` — link checker found a non-2xx URL in `references.yaml`.
- `5` — output directory not writable or partial-write detected; nothing committed.
