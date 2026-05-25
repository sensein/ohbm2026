# Quickstart — Stage 15 NeuroScape Context

Maintainer-facing runbook for the cross-conference atlas landing page
+ NeuroScape PubMed subsite. All shells assume `cwd` is the repo root.

## 0. Prerequisites

```bash
# Existing project setup (no changes for Stage 15):
UV_CACHE_DIR=.uv-cache uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e ".[enrich,embeddings,review]"

# NeuroScape v1.0.1 release (one-off setup; gitignored input root):
# 1) Download from Zenodo (URL in NeuroScape README — out of repo scope).
# 2) Unzip under data/inputs/neuroscape-source/v101 so the following layout exists:
#      data/inputs/neuroscape-source/v101/DomainEmbeddings/*.h5
#      data/inputs/neuroscape-source/v101/neuroscience_articles_1999-2023.csv
#      data/inputs/neuroscape-source/v101/neuroscience_clusters_1999-2023.csv
#      data/inputs/neuroscape-source/v101/Data/Models/domain_embedding_model.pth
ls data/inputs/neuroscape-source/v101/
```

If the NeuroScape release is not yet downloaded, the orchestrator
refuses to run with a precise `NeuroScapeInputError` naming the
missing path — fix the layout and retry.

## 1. Refresh the OHBM 2026 corpus (only if upstream changed)

```bash
# Existing Stage 1 + Stage 2 + Stage 6/10 commands; no Stage-15-specific changes:
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli fetch-abstracts
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli enrich-abstracts
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-ui-data \
    --output-root data/outputs/parquets/$(cat data/outputs/parquets/CURRENT_STATE_KEY)/
# This writes the renamed ohbm2026.parquet in place of the legacy data.parquet (FR-022).
```

Skip this step if `ohbm2026.parquet` is already current for the
corpus state-key you want to publish.

## 2. Build the Stage-15 atlas package

```bash
STATE_KEY=$(cat data/outputs/parquets/CURRENT_STATE_KEY)

PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-atlas-package \
    --neuroscape-source data/inputs/neuroscape-source/v101 \
    --voyage-bundle voyage_stage2_published \
    --ohbm2026-parquet data/outputs/parquets/${STATE_KEY}/ohbm2026.parquet \
    --output-root      data/outputs/parquets/${STATE_KEY}/
```

First-run wall-clock budget (recent laptop, CPU): ~15–25 minutes
dominated by the two UMAP fits (~10 min total for ~600K rows in 64-dim
on cosine), the k-NN compute (~3–5 min), and the link-check pass.

Resume budget (cache hits): < 60 s end-to-end (SC-004).

The orchestrator writes:

- `data/outputs/parquets/<state-key>/neuroscape.parquet`
- `data/outputs/parquets/<state-key>/atlas.parquet`
- `data/outputs/parquets/<state-key>/ohbm2026.parquet`   (unchanged from step 1)
- `data/provenance/neuroscape_context_provenance__<state-key>.json`

Inspect provenance:

```bash
.venv/bin/python -m json.tool \
    "data/provenance/neuroscape_context_provenance__${STATE_KEY}.json" | head -60
```

## 3. Smoke-test the parquets

Each parquet embeds its own schema (row-group-per-table layout from
Stage 10 + the Stage-15 additions documented in
`specs/015-neuroscape-context/contracts/parquet-schemas.md`). A
round-trip read with `pyarrow` is enough to catch a truncated or
corrupt file:

```bash
for P in ohbm2026 neuroscape atlas; do
  .venv/bin/python -c "
import pyarrow.parquet as pq, sys
t = pq.read_table('data/outputs/parquets/${STATE_KEY}/${P}.parquet')
print(f'${P}: rows={t.num_rows} cols={len(t.column_names)}')
"
done
```

Then verify the cross-parquet state-key chain that the in-browser
loader checks at runtime (R-012) — read each parquet's `manifest`
row-group and confirm `atlas.parquet`'s
`build_info.sibling_state_keys` match the `state_key` fields embedded
in `ohbm2026.parquet` and `neuroscape.parquet`:

```bash
.venv/bin/python - <<'PY'
import io, json, pyarrow.parquet as pq
ROOT = "data/outputs/parquets"
STATE = "${STATE_KEY}"   # shell-substituted by the heredoc parent
keys = {}
for name in ("ohbm2026", "neuroscape", "atlas"):
    t = pq.read_table(f"{ROOT}/{STATE}/{name}.parquet")
    for r in t.to_pylist():
        if r["table_name"] != "manifest":
            continue
        inner = pq.read_table(io.BytesIO(r["table_bytes"])).to_pylist()[0]
        bi = json.loads(inner["manifest_json"])["build_info"]
        keys[name] = bi.get("state_key") or bi.get("corpus_state_key")
        if name == "atlas":
            sib = bi.get("sibling_state_keys", {})
print("state_keys:", keys)
print("atlas sibling_state_keys:", sib)
ok = sib.get("ohbm2026") == keys["ohbm2026"] and sib.get("neuroscape") == keys["neuroscape"]
print("chain CONSISTENT" if ok else "chain DRIFT — would trigger R-012 banner")
PY
```

A mismatch here trips the visible drift banner on the deployed
atlas-root page.

## 4. Upload the three parquets and configure runtime envs

Each parquet has its own Dropbox-style shareable URL. The deploy
workflow reads these from GitHub Actions repository variables:

| Variable                                  | Points at                       |
|-------------------------------------------|----------------------------------|
| `OHBM2026_UI_DATA_PACKAGE_URL_OHBM2026`   | `ohbm2026.parquet`              |
| `OHBM2026_UI_DATA_PACKAGE_URL_NEUROSCAPE` | `neuroscape.parquet`            |
| `OHBM2026_UI_DATA_PACKAGE_URL_ATLAS`      | `atlas.parquet`                 |
| `VITE_NCBI_API_KEY` (optional)            | NCBI E-utilities API key — raises the `/neuroscape/abstract/<id>/` runtime fetch rate limit from 3 req/s to 10 req/s (R-015). |

Update all three parquet URLs when publishing a new state-key.
Failing to update even one will trip the cross-parquet drift check
in `loader.ts` (R-012) and surface a visible error banner on the
landing page rather than silently mis-rendering. `VITE_NCBI_API_KEY`
is optional; without it the runtime fetch still works at the anonymous
rate limit.

## 5. Trigger the deploy

```bash
git push origin 015-neuroscape-context
gh pr create -t "feat(stage15): cross-conf atlas + neuroscape subsite" -B main
```

The PR triggers `pr-preview.yml`, which builds all three modes and
publishes them under `gh-pages/pr-<N>/{,ohbm2026/,neuroscape/}`. Open
the preview URL to verify:

- `https://abstractatlas.brainkb.org/pr-<N>/` — atlas-root mode
- `https://abstractatlas.brainkb.org/pr-<N>/ohbm2026/` — unchanged OHBM 2026 site
- `https://abstractatlas.brainkb.org/pr-<N>/neuroscape/` — new NeuroScape subsite

Once merged to `main`, `deploy-ui.yml` publishes to the production
branch:

- `https://abstractatlas.brainkb.org/` — atlas-root (replaces the redirect island)
- `https://abstractatlas.brainkb.org/ohbm2026/` — unchanged
- `https://abstractatlas.brainkb.org/neuroscape/` — new

## 6. Verify post-deploy

```bash
# Atlas root no longer redirects:
curl -sI https://abstractatlas.brainkb.org/ | head -5
# Expected: HTTP/2 200, content-type: text/html, NO Location header,
# NO <meta http-equiv="refresh"> in the HTML.

# OHBM 2026 still reachable and renders the search/UMAP UI:
curl -sI https://abstractatlas.brainkb.org/ohbm2026/ | head -5
# Expected: HTTP/2 200. Then manually verify functional parity
# (FR-022): search, facets, lasso, cart, detail pages, 2D+3D UMAP
# all behave as before. The build output is NOT byte-identical to
# pre-Stage-15 — the Plotly bundle and UmapPanel were touched to
# unify atlas-mode rendering — but the OHBM-mode code path is
# unchanged behaviourally.

# NeuroScape subsite reachable:
curl -sI https://abstractatlas.brainkb.org/neuroscape/ | head -5
# Expected: HTTP/2 200.
```

## 7. Force a rebuild from scratch

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli build-atlas-package \
    --neuroscape-source data/inputs/neuroscape-source/v101 \
    --voyage-bundle voyage_stage2_published \
    --ohbm2026-parquet data/outputs/parquets/${STATE_KEY}/ohbm2026.parquet \
    --output-root      data/outputs/parquets/${STATE_KEY}/ \
    --force-rebuild all
```

Invalidates every cache region and recomputes from scratch. Useful
after a NeuroScape input-release upgrade (the build SHOULD refuse
without `--force-rebuild` if the centroid table version drifts;
exceptions surface as `NeuroScapeInputError`).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `NeuroScapeInputError: missing HDF5 shard X` | Source unzip incomplete. | Re-unzip; check `data/inputs/neuroscape-source/v101/DomainEmbeddings/`. |
| `UmapFitError: nan in input vectors` | A shard has bad data. | Inspect with the diagnostic helper in `atlas_package/neuroscape_loader.py`; re-download the offending shard. |
| `OhbmProjectionError: <list of submission_ids>` | OHBM 2026 abstracts without a Stage-2 vector. | Run `ohbmcli embed-matrix` for the listed ids; rerun the orchestrator. |
| `CrossParquetDriftError` | The three parquets weren't all rebuilt together. | Rerun `build-atlas-package` against the latest `ohbm2026.parquet`. |
| `AtlasLinkCheckError` | One of the small fixed set of non-PubMed-record URLs (NeuroScape Zenodo / citation / OHBM 2026 site / NCBI base) returned 4xx/5xx. | Re-run; if persistent, file an issue. Per-PubMed-record URLs are NOT pre-checked, so they cannot raise this error. Do NOT skip with `--no-link-check` in CI. |
| Visitor reports a `/neuroscape/abstract/<id>/` page has a missing body | Runtime PubMed fetch failed for that record (PubMed retraction, NCBI 5xx, network). | Per FR-019b the local fields still render; the body region shows the offline state. Visitor can hit Retry; persistent failures should be reported via the NCBI E-utilities status page (out of repo scope). |
| Landing page shows the cross-parquet-drift banner | Dropbox URLs out of sync. | Re-upload all three parquets; verify all three repo variables match the latest state-key. |
| `/ohbm2026/` functional regression detected (FR-022) | Atlas-mode code leaked into the OHBM-mode path. | Inspect the unified `UmapPanel.svelte` mode dispatch + any other component touched in this stage for `mode === 'ohbm'` branches that no longer cleanly partition. |
