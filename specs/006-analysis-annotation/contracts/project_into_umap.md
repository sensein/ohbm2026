# Function Contract: `analyze.umap.project_into_umap`

User Story 2's public surface. Project an out-of-corpus vector batch into an existing fitted UMAP bundle without re-fitting the whole UMAP.

## Signature

```python
def project_into_umap(
    new_vectors: np.ndarray,            # float32, shape (m, d) — must match bundle.vector_dim
    fitted_umap_bundle: Path | dict,    # bundle directory path OR pre-loaded dict from load_projections_bundle
    *,
    algorithm: str,                     # "native" | "knn_weighted" | "parametric"
    dim: int = 2,                       # 2 or 3 — pick which UMAP space to project into
    knn_k: int = 15,                    # only used by "knn_weighted"
    knn_temperature: float = 1.0,       # softmax sharpness for "knn_weighted"
) -> np.ndarray:                        # float32, shape (m, dim)
```

## Pre-conditions

1. `fitted_umap_bundle` resolves to a `kind="projections"` bundle (raise `AnalysisError` otherwise).
2. `new_vectors.shape[1]` equals `bundle.metadata["vector_dim"]` (raise `ProjectionDimensionMismatch` otherwise — edge case 2).
3. `algorithm` is in `bundle.metadata["supported_algorithms"]` (raise `UnsupportedProjectionAlgorithm` otherwise).
4. `dim in (2, 3)` and the corresponding `umap{dim}_coords.npy` exists in the bundle (raise `AnalysisError` otherwise).

## Algorithm-specific behavior

### `algorithm="native"`
- Loads `umap{dim}_model.pickle` and calls `model.transform(new_vectors)`.
- Requires `umap-learn` to be importable; raises `AnalysisError` with a recoverable message if not.
- Strictly deterministic for the same `(bundle, new_vectors)` pair (umap-learn's `transform` is deterministic given the same model state).

### `algorithm="knn_weighted"`
- L2-normalizes `new_vectors` and `bundle.payload["reference_matrix"]` (if not already unit-norm).
- For each row of `new_vectors`, finds the top-`knn_k` nearest reference rows by cosine similarity.
- Weights: `w_i = softmax(sim_i / knn_temperature)` over the top-k.
- Output: `sum(w_i * ref_coords[i])` per row.
- Strictly deterministic.

### `algorithm="parametric"`
- Loads `parametric_mlp_{dim}.pickle` (a small `numpy`-only MLP — stored as a list of `(W, b, activation)` tuples; no torch dependency at projection time).
- Forwards `new_vectors` through the MLP and returns the output.
- Strictly deterministic.

## Post-conditions

1. The returned array has shape `(m, dim)` and dtype `float32`.
2. `project_into_umap` does NOT mutate the bundle on disk; it does NOT mutate `new_vectors`.
3. Two calls with the same `(new_vectors, fitted_umap_bundle, algorithm, dim, knn_k, knn_temperature)` return byte-identical output (SC-003).

## Error surface

| Condition | Exception |
|---|---|
| Bundle path does not exist | `AnalysisError` |
| Bundle is not a `projections` kind | `AnalysisError` |
| `algorithm` not in `supported_algorithms` | `UnsupportedProjectionAlgorithm` |
| `new_vectors.shape[1] != bundle.vector_dim` | `ProjectionDimensionMismatch` |
| `dim not in (2, 3)` | `ValueError` (programmer error, not configurational) |
| `algorithm="native"` but `umap-learn` not installed in the venv | `AnalysisError` |
| `algorithm="native"` but `umap{dim}_model.pickle` missing | `AnalysisError` |
