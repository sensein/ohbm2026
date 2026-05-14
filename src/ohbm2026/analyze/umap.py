"""Stage 4 UMAP fit + out-of-corpus projection.

Owns the canonical `projections` bundle shape and the
`project_into_umap(new_vectors, fitted_bundle, algorithm=…)` surface
(US2). Supported projection algorithms (one per row of
`metadata.json:supported_algorithms`):

- `native`         — uses the fitted umap-learn model's `transform()`.
                     Requires `umap{dim}_model.pickle` in the bundle.
- `knn_weighted`   — model-free fallback. Softmax-weighted mean of
                     the k nearest reference coordinates (cosine
                     similarity). Works on `(reference_matrix.npy,
                     umap{dim}_coords.npy)` alone.
- `parametric`     — small numpy-only MLP fitted at write-time on
                     `(reference_matrix, reference_coords)`; persisted
                     alongside the bundle. Strictly deterministic at
                     projection time (no torch dependency).

Determinism (SC-003): two `project_into_umap(...)` calls with the same
`(new_vectors, fitted_bundle, algorithm, dim, knn_k, knn_temperature)`
return byte-identical coordinates.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.exceptions import (
    AnalysisError,
    ProjectionDimensionMismatch,
    UnsupportedProjectionAlgorithm,
)

__all__ = [
    "DEFAULT_UMAP_N_NEIGHBORS",
    "DEFAULT_UMAP_MIN_DIST",
    "DEFAULT_UMAP_METRIC",
    "DEFAULT_UMAP_RANDOM_STATE",
    "DEFAULT_KNN_K",
    "DEFAULT_KNN_TEMPERATURE",
    "ParametricMLP",
    "fit_umap_2d",
    "fit_umap_3d",
    "fit_parametric_mlp",
    "write_projections_bundle",
    "load_projections_bundle",
    "project_into_umap",
]


DEFAULT_UMAP_N_NEIGHBORS = 15
DEFAULT_UMAP_MIN_DIST = 0.1
DEFAULT_UMAP_METRIC = "cosine"
DEFAULT_UMAP_RANDOM_STATE = 42
DEFAULT_KNN_K = 15
DEFAULT_KNN_TEMPERATURE = 1.0


# ---------------------------------------------------------------------------
# UMAP fit
# ---------------------------------------------------------------------------


def _fit_umap(
    matrix: np.ndarray,
    *,
    n_components: int,
    n_neighbors: int,
    min_dist: float,
    metric: str,
    random_state: int,
) -> tuple[np.ndarray, Any]:
    """Fit a UMAP projection. Returns `(coords, fitted_model)`.

    `fitted_model` is the `umap.UMAP` instance — picklable for the
    `native` projection path.
    """
    try:
        import umap  # lazy: heavy import
    except ImportError as exc:  # pragma: no cover - opt-extra missing
        raise AnalysisError(
            "umap-learn is required for projections. Install with: "
            "uv pip install --python .venv/bin/python '.[analysis]'"
        ) from exc

    n_rows = matrix.shape[0]
    if n_rows <= n_neighbors:
        n_neighbors = max(2, n_rows - 1)
    model = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )
    coords = model.fit_transform(np.asarray(matrix, dtype=np.float32))
    return np.asarray(coords, dtype=np.float32), model


def fit_umap_2d(
    matrix: np.ndarray,
    *,
    n_neighbors: int = DEFAULT_UMAP_N_NEIGHBORS,
    min_dist: float = DEFAULT_UMAP_MIN_DIST,
    metric: str = DEFAULT_UMAP_METRIC,
    random_state: int = DEFAULT_UMAP_RANDOM_STATE,
) -> tuple[np.ndarray, Any]:
    """Fit a 2D UMAP projection. Returns `(coords, fitted_model)`."""
    return _fit_umap(
        matrix,
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )


def fit_umap_3d(
    matrix: np.ndarray,
    *,
    n_neighbors: int = DEFAULT_UMAP_N_NEIGHBORS,
    min_dist: float = DEFAULT_UMAP_MIN_DIST,
    metric: str = DEFAULT_UMAP_METRIC,
    random_state: int = DEFAULT_UMAP_RANDOM_STATE,
) -> tuple[np.ndarray, Any]:
    """Fit a 3D UMAP projection. Returns `(coords, fitted_model)`."""
    return _fit_umap(
        matrix,
        n_components=3,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )


# ---------------------------------------------------------------------------
# Parametric MLP — small, numpy-only, picklable, deterministic
# ---------------------------------------------------------------------------


class ParametricMLP:
    """Tiny numpy-only MLP for the `parametric` projection algorithm.

    Persisted as pickle bytes. Stateless at projection time — a
    single `forward()` call is a deterministic matmul chain, no
    randomness, no torch dependency.

    The MLP is fitted via scikit-learn's `MLPRegressor` (which has a
    fixed-seed solver and well-defined determinism) at bundle-write
    time; on the projection side we use ONLY the trained weights to
    do the forward pass in pure numpy.
    """

    def __init__(
        self,
        weights: list[np.ndarray],
        biases: list[np.ndarray],
        activation: str = "relu",
        output_activation: str = "identity",
    ) -> None:
        self.weights = [np.asarray(w, dtype=np.float32) for w in weights]
        self.biases = [np.asarray(b, dtype=np.float32) for b in biases]
        self.activation = activation
        self.output_activation = output_activation
        if len(self.weights) != len(self.biases):
            raise ValueError(
                f"weights ({len(self.weights)}) and biases ({len(self.biases)}) must align"
            )

    @property
    def input_dim(self) -> int:
        return int(self.weights[0].shape[0])

    @property
    def output_dim(self) -> int:
        return int(self.weights[-1].shape[1])

    def _activate(self, x: np.ndarray) -> np.ndarray:
        if self.activation == "relu":
            return np.maximum(x, 0.0)
        if self.activation == "tanh":
            return np.tanh(x)
        if self.activation == "identity":
            return x
        raise AnalysisError(f"unsupported MLP activation: {self.activation}")

    def forward(self, x: np.ndarray) -> np.ndarray:
        h = np.asarray(x, dtype=np.float32)
        for i, (W, b) in enumerate(zip(self.weights, self.biases)):
            h = h @ W + b
            if i < len(self.weights) - 1:
                h = self._activate(h)
            else:
                # Output activation
                if self.output_activation == "tanh":
                    h = np.tanh(h)
                elif self.output_activation == "relu":
                    h = np.maximum(h, 0.0)
                # else: identity
        return np.asarray(h, dtype=np.float32)


def fit_parametric_mlp(
    reference_vectors: np.ndarray,
    reference_coords: np.ndarray,
    *,
    hidden_sizes: tuple[int, ...] = (64, 32),
    seed: int = 42,
    max_iter: int = 300,
) -> ParametricMLP:
    """Fit a small MLP from input-vectors → UMAP-coords.

    Uses scikit-learn's `MLPRegressor` with a fixed `random_state` for
    deterministic fits. The result is unwrapped into a numpy-only
    `ParametricMLP` for the projection-time forward pass — no sklearn
    dependency at project time.
    """
    try:
        from sklearn.neural_network import MLPRegressor
    except ImportError as exc:  # pragma: no cover
        raise AnalysisError(
            "scikit-learn is required for the parametric projection algorithm."
        ) from exc

    X = np.asarray(reference_vectors, dtype=np.float32)
    y = np.asarray(reference_coords, dtype=np.float32)
    n_rows = X.shape[0]
    # MLPRegressor needs batch_size <= n_rows; for small datasets keep it small.
    batch_size = min(32, max(2, n_rows))
    reg = MLPRegressor(
        hidden_layer_sizes=hidden_sizes,
        activation="relu",
        solver="adam",
        random_state=seed,
        max_iter=max_iter,
        batch_size=batch_size,
    )
    reg.fit(X, y)
    return ParametricMLP(
        weights=list(reg.coefs_),
        biases=list(reg.intercepts_),
        activation="relu",
        output_activation="identity",
    )


# ---------------------------------------------------------------------------
# Bundle I/O
# ---------------------------------------------------------------------------


def _write_pickle_bytes(path: Path, obj: Any) -> None:
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    path.write_bytes(data)


def _load_pickle_bytes(path: Path) -> Any:
    return pickle.loads(path.read_bytes())


def write_projections_bundle(
    bundle_dir: Path,
    *,
    ids: np.ndarray,
    reference_matrix: np.ndarray,
    coords2d: np.ndarray,
    coords3d: np.ndarray,
    model2d: Any | None = None,
    model3d: Any | None = None,
    mlp2d: ParametricMLP | None = None,
    mlp3d: ParametricMLP | None = None,
    hyperparameters: dict[str, Any] | None = None,
    metadata_extra: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> Path:
    """Write a `projections` bundle atomically.

    The bundle's `metadata.json:supported_algorithms` is **derived
    from which artifacts were actually persisted** (Principle VII:
    discovered, not hardcoded). A bundle with no UMAP-model pickle
    cannot support `native` projection; the runtime check in
    `project_into_umap` reads `supported_algorithms` and refuses
    accordingly.
    """
    bundle_dir = Path(bundle_dir)
    parent = bundle_dir.parent
    parent.mkdir(parents=True, exist_ok=True)

    if ids.shape[0] != reference_matrix.shape[0]:
        raise ValueError(
            f"ids ({ids.shape[0]}) and reference_matrix ({reference_matrix.shape[0]}) row counts must match"
        )
    if ids.shape[0] != coords2d.shape[0] or ids.shape[0] != coords3d.shape[0]:
        raise ValueError("coords2d / coords3d must align with ids on the leading axis")
    if coords2d.shape[1] != 2 or coords3d.shape[1] != 3:
        raise ValueError("coords2d must be (n, 2); coords3d must be (n, 3)")

    supported_2d: list[str] = ["knn_weighted"]
    supported_3d: list[str] = ["knn_weighted"]
    if model2d is not None:
        supported_2d.append("native")
    if model3d is not None:
        supported_3d.append("native")
    if mlp2d is not None:
        supported_2d.append("parametric")
    if mlp3d is not None:
        supported_3d.append("parametric")

    metadata = {
        "kind": "projections",
        "n_rows": int(ids.shape[0]),
        "vector_dim": int(reference_matrix.shape[1]),
        "supported_algorithms_2d": sorted(supported_2d),
        "supported_algorithms_3d": sorted(supported_3d),
    }
    if hyperparameters:
        metadata["hyperparameters"] = dict(hyperparameters)
    if metadata_extra:
        metadata.update(metadata_extra)

    # Materialize inside a sibling temp dir, rename into place.
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(
        prefix=f".{bundle_dir.name}__tmp_", dir=parent
    ) as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        np.save(tmp_root / "ids.npy", ids)
        np.save(tmp_root / "reference_matrix.npy", reference_matrix)
        np.save(tmp_root / "umap2d_coords.npy", coords2d)
        np.save(tmp_root / "umap3d_coords.npy", coords3d)
        if model2d is not None:
            _write_pickle_bytes(tmp_root / "umap2d_model.pickle", model2d)
        if model3d is not None:
            _write_pickle_bytes(tmp_root / "umap3d_model.pickle", model3d)
        if mlp2d is not None:
            _write_pickle_bytes(tmp_root / "parametric_mlp_2d.pickle", mlp2d)
        if mlp3d is not None:
            _write_pickle_bytes(tmp_root / "parametric_mlp_3d.pickle", mlp3d)
        (tmp_root / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )
        if provenance is not None:
            (tmp_root / "provenance.json").write_text(
                json.dumps(provenance, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        tmp_root.replace(bundle_dir)
    return bundle_dir


def load_projections_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Read a `projections` bundle into a dict for `project_into_umap`."""
    bundle_dir = Path(bundle_dir)
    if not bundle_dir.exists():
        raise AnalysisError(f"projections bundle not found: {bundle_dir}")
    metadata_path = bundle_dir / "metadata.json"
    if not metadata_path.exists():
        raise AnalysisError(f"projections bundle missing metadata.json: {bundle_dir}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("kind") != "projections":
        raise AnalysisError(
            f"expected projections bundle, got kind={metadata.get('kind')!r}: {bundle_dir}"
        )
    bundle: dict[str, Any] = {
        "bundle_dir": bundle_dir,
        "metadata": metadata,
        "ids": np.load(bundle_dir / "ids.npy"),
        "reference_matrix": np.load(bundle_dir / "reference_matrix.npy"),
        "umap2d_coords": np.load(bundle_dir / "umap2d_coords.npy"),
        "umap3d_coords": np.load(bundle_dir / "umap3d_coords.npy"),
    }
    return bundle


# ---------------------------------------------------------------------------
# project_into_umap
# ---------------------------------------------------------------------------


def _l2_normalize(matrix: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms < eps, 1.0, norms)
    return (matrix / norms).astype(np.float32, copy=False)


def _project_knn_weighted(
    new_vectors: np.ndarray,
    reference_matrix: np.ndarray,
    reference_coords: np.ndarray,
    *,
    knn_k: int,
    knn_temperature: float,
) -> np.ndarray:
    """Softmax-weighted mean of the k nearest reference coords by cosine similarity."""
    ref_unit = _l2_normalize(reference_matrix)
    new_unit = _l2_normalize(np.asarray(new_vectors, dtype=np.float32))
    sims = new_unit @ ref_unit.T  # (m, n)
    k = min(knn_k, sims.shape[1])
    # Top-k indices per row (no specific order requirement; argsort is deterministic).
    top_indices = np.argsort(-sims, axis=1)[:, :k]
    out = np.zeros((new_vectors.shape[0], reference_coords.shape[1]), dtype=np.float32)
    for row in range(new_vectors.shape[0]):
        idx = top_indices[row]
        weights = sims[row, idx] / float(knn_temperature)
        # Softmax over the top-k similarities
        weights = weights - weights.max()  # numerical stability
        exp_w = np.exp(weights).astype(np.float32)
        exp_w = exp_w / exp_w.sum()
        out[row] = (exp_w.reshape(-1, 1) * reference_coords[idx].astype(np.float32)).sum(axis=0)
    return out


def project_into_umap(
    new_vectors: np.ndarray,
    fitted_umap_bundle: Path | dict[str, Any],
    *,
    algorithm: str,
    dim: int = 2,
    knn_k: int = DEFAULT_KNN_K,
    knn_temperature: float = DEFAULT_KNN_TEMPERATURE,
) -> np.ndarray:
    """Project `new_vectors` into the bundle's existing UMAP space.

    Three algorithms (per FR-006 / contracts/project_into_umap.md):
    - `native`        — requires `umap{dim}_model.pickle`; calls model.transform.
    - `knn_weighted`  — softmax of cosine-similar reference coords (k=15 default).
    - `parametric`    — requires `parametric_mlp_{dim}.pickle`; numpy-only forward.

    Determinism (SC-003): identical inputs return byte-identical output.
    """
    if dim not in (2, 3):
        raise ValueError(f"dim must be 2 or 3, got {dim}")

    if isinstance(fitted_umap_bundle, (str, Path)):
        bundle = load_projections_bundle(Path(fitted_umap_bundle))
    else:
        bundle = fitted_umap_bundle

    new_vectors = np.asarray(new_vectors, dtype=np.float32)
    if new_vectors.ndim != 2:
        raise ValueError(
            f"new_vectors must be 2-D, got shape {new_vectors.shape}"
        )
    expected_dim = int(bundle["metadata"]["vector_dim"])
    if new_vectors.shape[1] != expected_dim:
        raise ProjectionDimensionMismatch(
            f"expected {expected_dim}-dim input, got {new_vectors.shape[1]}"
        )

    supported_key = "supported_algorithms_2d" if dim == 2 else "supported_algorithms_3d"
    supported = bundle["metadata"].get(supported_key, [])
    if algorithm not in supported:
        raise UnsupportedProjectionAlgorithm(
            f"algorithm={algorithm!r} not in supported_algorithms for dim={dim}: {supported}"
        )

    bundle_dir = bundle.get("bundle_dir")
    coords_key = "umap2d_coords" if dim == 2 else "umap3d_coords"
    reference_coords = bundle[coords_key].astype(np.float32, copy=False)

    if algorithm == "knn_weighted":
        return _project_knn_weighted(
            new_vectors,
            bundle["reference_matrix"],
            reference_coords,
            knn_k=knn_k,
            knn_temperature=knn_temperature,
        )

    if algorithm == "native":
        model_filename = f"umap{dim}d_model.pickle"
        model_path = Path(bundle_dir) / model_filename if bundle_dir is not None else None
        if model_path is None or not model_path.exists():
            raise AnalysisError(
                f"native algorithm requires {model_filename} in the bundle"
            )
        try:
            import umap  # noqa: F401 — ensure umap-learn loads its unpicklers
        except ImportError as exc:  # pragma: no cover
            raise AnalysisError(
                "umap-learn must be installed for the native projection algorithm."
            ) from exc
        model = _load_pickle_bytes(model_path)
        return np.asarray(model.transform(new_vectors), dtype=np.float32)

    if algorithm == "parametric":
        mlp_filename = f"parametric_mlp_{dim}d.pickle"
        # Note: bundle writer names files `parametric_mlp_2d.pickle` / `parametric_mlp_3d.pickle`
        mlp_filename = f"parametric_mlp_{dim}d.pickle"
        mlp_path = Path(bundle_dir) / mlp_filename if bundle_dir is not None else None
        if mlp_path is None or not mlp_path.exists():
            raise AnalysisError(
                f"parametric algorithm requires {mlp_filename} in the bundle"
            )
        mlp: ParametricMLP = _load_pickle_bytes(mlp_path)
        return mlp.forward(new_vectors)

    raise UnsupportedProjectionAlgorithm(
        f"unknown algorithm: {algorithm!r}; expected one of {supported}"
    )
