# Quickstart — Stage 4 Analysis & Annotation

This is the operator runbook for Stage 4. All commands assume the repository root and a hydrated `.venv` (Python 3.14).

## 0. One-off setup

```bash
# Add the analysis extras to your venv.
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[analysis]"

# spaCy model (required for topic phrase extraction).
.venv/bin/python -m spacy download en_core_web_md

# Optional: scientific NER variant.
UV_CACHE_DIR=.uv-cache uv pip install --python .venv/bin/python ".[analysis-sci]"
.venv/bin/python -m spacy download en_core_sci_lg  # via scispacy

# One-off NeuroScape centroid derivation (downloads + groups the published table).
# Place the NeuroScape data under data/inputs/neuroscape/ first (DomainEmbeddings/*.h5
# + neuroscience_articles_1999-2023.csv + neuroscience_clusters_1999-2023.csv).
PYTHONPATH=src .venv/bin/python scripts/derive_neuroscape_centroids.py \
    --input-root data/inputs/neuroscape \
    --output-root data/inputs/neuroscape
# Produces:
#   data/inputs/neuroscape/centroids__<version>.npy
#   data/inputs/neuroscape/cluster_table.csv
```

## 1. Run the default analysis matrix

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix
# Equivalent venv-only wrapper:
PYTHONPATH=src .venv/bin/python scripts/run_analyze_matrix.py
```

By default this produces **40 bundles** (5 models × 2 inputs × 4 kinds) + 1 canonical rollup file pair (parquet + sqlite). Wall-clock budget: < 30 min (SC-001).

Each bundle directory looks like:
```
data/outputs/analysis/voyage_abstract/communities__abc123def456/
├── ids.npy
├── community_ids.npy
├── knn_indices.npy
├── knn_distances.npy
├── resolution_sweep.json
├── topics.json
├── metadata.json
└── provenance.json
```

The rollup pair:
```
data/outputs/analysis/annotations__f0c51e80dc0e.parquet
data/outputs/analysis/annotations__f0c51e80dc0e.sqlite
```

## 2. Run without an OpenAI key

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix --skip-llm-topics
```

The topic-keyword pipeline runs locally only (spaCy + c-TF-IDF). `Keywords` in every `topics.json` contains the top-N c-TF-IDF phrases; `Title`/`Description`/`Focus` are empty strings.

## 3. Restrict to one model (faster iteration)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix --models voyage
```

Produces 8 bundles (1 model × 2 inputs × 4 kinds) + the rollup limited to voyage columns.

## 4. Force-recompute one kind without invalidating the rest

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-matrix \
    --invalidate communities
```

The other three kinds hit cache; communities is re-computed (e.g., after tweaking the resolution sweep).

## 5. Project a new abstract into an existing UMAP

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli analyze-umap-project \
    --fitted-bundle data/outputs/analysis/voyage_abstract/projections__<state-key>/ \
    --input-vectors path/to/new_vectors.npy \
    --algorithm native \
    --output path/to/new_coords.npy
```

Or programmatically:
```python
from pathlib import Path
import numpy as np
from ohbm2026.analyze.umap import project_into_umap

new_vectors = np.load("path/to/new_vectors.npy")
new_coords = project_into_umap(
    new_vectors,
    fitted_umap_bundle=Path("data/outputs/analysis/voyage_abstract/projections__<state-key>/"),
    algorithm="native",
    dim=2,
)
```

## 6. Common failure modes

| Error | Meaning | Fix |
|---|---|---|
| `InputBundleMissing: data/outputs/embeddings/voyage/claims__... not found` | Stage 3 hasn't run for this `(model, component)`. | Run `ohbmcli embed-matrix` first. |
| `CentroidTableMissing` | `data/inputs/neuroscape/centroids__*.npy` doesn't exist. | Run `scripts/derive_neuroscape_centroids.py` (step 0). |
| `CentroidTableVersionMismatch` | Centroid file version disagrees with the Stage-2 checkpoint. | Re-derive centroids; or pin to a matching checkpoint. |
| `UnsupportedProjectionAlgorithm: native not in supported_algorithms` | The bundle persisted no UMAPModel for the requested dim. | Use `knn_weighted` or `parametric`; or re-run `analyze-matrix --invalidate projections` to rebuild. |
| `ProjectionDimensionMismatch: expected 1024-dim input, got 384` | UMAP was fit on a different-dim bundle than your `new_vectors`. | Check the bundle's `metadata.json:vector_dim`. |
| `TopicGroupingHallucination: 'X' not in candidate_phrases` | LLM emitted a keyword that wasn't in the spaCy/c-TF-IDF shortlist. | The run aborts; re-run is safe (cache is keyed on candidate_phrases so the same call is retried until the LLM stays in-vocabulary). |

## 7. What the UI consumes

The UI's static-export step reads the `annotations.sqlite` and the per-bundle `topics.json` files. No code change is needed on the UI side beyond the import-path rewrites for the `analyze/` package (SC-004 + SC-007).
