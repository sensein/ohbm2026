# Quickstart — NeuroScape Semantic Search

**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Date**: 2026-05-27

The operator-facing runbook for the spec-019 deliverables. Assumes
Stage 15 + Stage 15.4 (UMAP cache) are already merged on `main`.

---

## 0. Pre-flight

```bash
# Same venv that Stage 15 uses.
UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv

# The sentence-transformers optional extra now includes the MiniLM
# encoder used by spec 019. Already declared in pyproject.toml's
# [project.optional-dependencies].embeddings entry.
uv pip install --python .venv/bin/python ".[embeddings]"

# Browser side — same site/ layout Stage 15 established.
pnpm --dir site install
```

---

## 1. One-time inputs

Spec 019 reuses Stage 15's NeuroScape v1.0.1 release inputs unchanged
(`data/inputs/neuroscape_v1.0.1/`). No new external data is fetched.

---

## 2. Run the build

The same `ohbmcli build-atlas-package` command Stage 15 established now
runs the semantic-index step by default:

```bash
.venv/bin/python -m ohbm2026.cli build-atlas-package \
    --neuroscape-source data/inputs/neuroscape_v1.0.1 \
    --ohbm2026-parquet  data/outputs/exported-sites/ui-site__<state-key>/ohbm2026.parquet \
    --voyage-bundle     voyage_stage2_published \
    --output-root       data/outputs/atlas-package__<state-key> \
    --umap-cache-root   data/cache/atlas-umap \
    --semantic-cache-root data/cache/atlas-vectors \
    --semantic-index
```

What this writes (new in spec 019, on top of Stage 15's outputs):

```text
data/outputs/atlas-package__<state-key>/
├── neuroscape.parquet            # NOW carries `cluster_centroids` table (~80 KB)
├── neuroscape_vectors.parquet    # NEW (~50 MB INT8, sorted by cluster_id)
└── atlas.parquet                 # NOW carries `ohbm_vectors` table (~1.25 MB)

data/cache/atlas-vectors/<state-key>/
├── cluster_<id>.npy              # Per-cluster intermediate cache (~50 files)
└── manifest.json                 # Cache-validity sidecar

data/provenance/build_atlas_package__<state-key>.json
                                  # NOW carries a `semantic_index` provenance block
```

`ohbm2026.parquet` is NOT touched by this command — its bytes remain
identical to the Stage 15 / 15.4 output (FR-016 / SC-007).

### 2.1 Iteration with cache hits

A second run with unchanged inputs hits the semantic-index cache:

```bash
# Identical command — should be sub-minute (just rewriting parquets
# from cached intermediates; no embedding compute).
.venv/bin/python -m ohbm2026.cli build-atlas-package ...same args...
```

Expected log lines (final summary):

```text
[semantic-index] cache_hits=50  cache_misses=0  build_seconds=12.4
[semantic-index] wrote neuroscape_vectors.parquet (461,000 rows, 8192/group)
[semantic-index] cluster_centroids table embedded in neuroscape.parquet (50 rows)
[semantic-index] ohbm_vectors table embedded in atlas.parquet (3,240 rows)
```

### 2.2 Skip the semantic step

For iterating on the rest of the build (UMAP, decimation, link check):

```bash
.venv/bin/python -m ohbm2026.cli build-atlas-package \
    --no-semantic-index \
    ...other args...
```

`neuroscape_vectors.parquet` is NOT produced; `cluster_centroids` and
`ohbm_vectors` tables are OMITTED from the main parquets. The browser
falls back to lexical-only ranking on `/neuroscape/` and atlas-root.

---

## 3. Verify the build outputs

```bash
PYTHONPATH=src .venv/bin/python -m unittest \
    tests.test_atlas_semantic_index \
    tests.test_atlas_vectors_compute \
    tests.test_atlas_orchestrator \
    -v
```

Expected: all pass. The byte-identity tests inside
`test_atlas_orchestrator.py` confirm two consecutive runs with pinned
timestamps produce sha256-identical parquets for `neuroscape.parquet`,
`neuroscape_vectors.parquet`, and `atlas.parquet`.

---

## 4. Try the browser side locally

```bash
# Build the three SvelteKit deployments against the local atlas-package
# outputs.
VITE_DATA_PACKAGE_URL_OHBM2026=file://$PWD/data/outputs/exported-sites/.../ohbm2026.parquet \
VITE_DATA_PACKAGE_URL_NEUROSCAPE=file://$PWD/data/outputs/atlas-package__<state-key>/neuroscape.parquet \
VITE_DATA_PACKAGE_URL_ATLAS=file://$PWD/data/outputs/atlas-package__<state-key>/atlas.parquet \
SITE_MODE=neuroscape \
pnpm --dir site dev
```

Open `http://localhost:5173/neuroscape/`, enable the `✨ Semantic`
toggle, type a 3–5 word concept query that doesn't appear verbatim in
any title (e.g. *"sleep memory consolidation hippocampus"*), and confirm
at least one `✨`-badged row appears within a few seconds.

Repeat with `SITE_MODE=atlas-root` and confirm cross-conference results
appear with the existing OHBM-vs-NeuroScape source identification.

---

## 5. Verify against the deployed CI smoke

The post-merge production smoke at `site/scripts/verify-production-deploy.mjs`
gets a new check:

```bash
pnpm --dir site exec node scripts/verify-production-deploy.mjs
```

Expected new line in the output:

```text
✓ /neuroscape/ semantic ready: state=ready  cluster-budget=4
✓ atlas-root cross-conference search responsive
```

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `VectorsManifestDriftError` on toggle activation | Model file on HuggingFace CDN re-released with different sha256 | Re-run `ohbmcli build-atlas-package --semantic-index` so the rebuilt manifest pins the new sha256; redeploy |
| Build step takes ~10 min on every run | Cache root not writable, OR state key changed (article set / model / quantization differ) | Confirm `data/cache/atlas-vectors/<state-key>/` is writable; if state key changed intentionally, this is expected on the first run; subsequent runs hit the cache |
| "Expand search depth?" banner on every query | User is searching across many topics → multiple cluster routes per session, hitting the FR-024 cap | Click "Expand" once; the cap is released for the rest of the session |
| Browser console shows `RangeFetchError` | gh-pages range requests rejected (rare) or `neuroscape_vectors.parquet` missing | Confirm the file exists at the documented URL; check Cache API hasn't cached a 404 |
| Lexical results match but no semantic results ever appear | Toggle state stuck in `loading-model` or `error` | Open DevTools → Application → Local Storage → clear `ohbm2026.semantic.*`; refresh |
