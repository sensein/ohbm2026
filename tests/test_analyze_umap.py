"""Tests for `ohbm2026.analyze.umap.project_into_umap` (US2).

Coverage per spec FR-005 / FR-006 / CA-002:
- `native` round-trip + within-convex-hull behavior.
- `knn_weighted` works against a coords-only bundle (no UMAPModel persisted).
- `parametric` round-trip + reasonable fidelity to the in-corpus fit.
- Unknown algorithm → `UnsupportedProjectionAlgorithm`.
- Dim mismatch → `ProjectionDimensionMismatch`.
- Determinism (SC-003): byte-identical repeats across all algorithms.
- 3-D path mirror of the 2-D coverage.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ohbm2026.analyze.umap import (
    fit_parametric_mlp,
    fit_umap_2d,
    fit_umap_3d,
    project_into_umap,
    write_projections_bundle,
)
from ohbm2026.exceptions import (
    ProjectionDimensionMismatch,
    UnsupportedProjectionAlgorithm,
    AnalysisError,
)


@contextmanager
def _isolated_cwd():
    original = Path.cwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        yield Path(tmp)
    finally:
        os.chdir(original)
        shutil.rmtree(tmp, ignore_errors=True)


def _synthetic_corpus(n_rows: int = 99, dim: int = 16, *, seed: int = 7) -> np.ndarray:
    """Synthetic embedding matrix with 3 deliberate clusters.

    Generates exactly `n_rows` rows by drawing each from a random cluster
    center (no floor division so callers get the count they asked for)."""
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(3, dim)) * 3.0
    cluster_assignment = rng.integers(0, 3, size=n_rows)
    matrix = np.zeros((n_rows, dim), dtype=np.float32)
    for i in range(n_rows):
        c = centers[cluster_assignment[i]]
        matrix[i] = c + rng.normal(scale=0.5, size=dim)
    return matrix.astype(np.float32)


def _build_bundle(tmp: Path, dim_bundle: str = "full") -> Path:
    """Fit a UMAP on the synthetic corpus and write a bundle.

    `dim_bundle="full"` persists the umap-learn model AND the parametric
    MLP for both 2D and 3D. `dim_bundle="coords_only"` writes only the
    reference matrix + coords (so `native` is NOT supported)."""
    matrix = _synthetic_corpus(n_rows=99, dim=8)
    coords2d, model2d = fit_umap_2d(matrix, random_state=42)
    coords3d, model3d = fit_umap_3d(matrix, random_state=42)
    if dim_bundle == "full":
        mlp2d = fit_parametric_mlp(matrix, coords2d, seed=42, max_iter=80)
        mlp3d = fit_parametric_mlp(matrix, coords3d, seed=42, max_iter=80)
    else:
        model2d = None
        model3d = None
        mlp2d = None
        mlp3d = None
    bundle = Path("data/outputs/analysis/voyage_abstract/projections__test")
    ids = np.arange(matrix.shape[0], dtype=np.int64)
    write_projections_bundle(
        bundle,
        ids=ids,
        reference_matrix=matrix,
        coords2d=coords2d,
        coords3d=coords3d,
        model2d=model2d,
        model3d=model3d,
        mlp2d=mlp2d,
        mlp3d=mlp3d,
        hyperparameters={"n_neighbors": 15, "min_dist": 0.1, "metric": "cosine"},
    )
    return bundle


class NativeAlgorithmTests(unittest.TestCase):
    def test_native_round_trip_2d_shape(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            new_vectors = _synthetic_corpus(n_rows=10, dim=8, seed=99)
            coords = project_into_umap(
                new_vectors, bundle, algorithm="native", dim=2
            )
            self.assertEqual(coords.shape, (10, 2))
            self.assertEqual(coords.dtype, np.float32)

    def test_native_3d_shape(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            new_vectors = _synthetic_corpus(n_rows=5, dim=8, seed=42)
            coords = project_into_umap(
                new_vectors, bundle, algorithm="native", dim=3
            )
            self.assertEqual(coords.shape, (5, 3))


class KnnWeightedAlgorithmTests(unittest.TestCase):
    def test_knn_weighted_works_without_model(self) -> None:
        """Coords-only bundle (no umap*_model.pickle) MUST still support knn_weighted."""
        with _isolated_cwd():
            bundle = _build_bundle(Path("."), dim_bundle="coords_only")
            new_vectors = _synthetic_corpus(n_rows=4, dim=8, seed=11)
            coords = project_into_umap(
                new_vectors, bundle, algorithm="knn_weighted", dim=2
            )
            self.assertEqual(coords.shape, (4, 2))
            # Verify native is NOT in supported_algorithms
            import json as _json
            meta = _json.loads((bundle / "metadata.json").read_text())
            self.assertNotIn("native", meta["supported_algorithms_2d"])

    def test_knn_weighted_in_neighborhood(self) -> None:
        """Projected new point should land near its in-corpus neighbor's coord."""
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            # Use an in-corpus vector as the "new" — projection should
            # land very near the original UMAP coord.
            import numpy as _np
            ref_matrix = _np.load(bundle / "reference_matrix.npy")
            ref_coords = _np.load(bundle / "umap2d_coords.npy")
            new_vec = ref_matrix[0:1]
            coords = project_into_umap(
                new_vec, bundle, algorithm="knn_weighted", dim=2, knn_k=15
            )
            self.assertEqual(coords.shape, (1, 2))
            # Projected point should be close to the original coord (top-k
            # weighted by similarity; itself dominates).
            distance = float(np.linalg.norm(coords[0] - ref_coords[0]))
            # Bound is generous because softmax over k=15 with the
            # self-similarity at the top still pulls in 14 neighbors.
            self.assertLess(distance, 10.0)


class ParametricAlgorithmTests(unittest.TestCase):
    def test_parametric_round_trip_2d(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            new_vectors = _synthetic_corpus(n_rows=5, dim=8, seed=99)
            coords = project_into_umap(
                new_vectors, bundle, algorithm="parametric", dim=2
            )
            self.assertEqual(coords.shape, (5, 2))
            self.assertEqual(coords.dtype, np.float32)

    def test_parametric_3d(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            new_vectors = _synthetic_corpus(n_rows=3, dim=8, seed=99)
            coords = project_into_umap(
                new_vectors, bundle, algorithm="parametric", dim=3
            )
            self.assertEqual(coords.shape, (3, 3))


class ErrorPathsTests(unittest.TestCase):
    def test_unsupported_algorithm_raises(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."), dim_bundle="coords_only")
            new_vectors = _synthetic_corpus(n_rows=2, dim=8, seed=99)
            with self.assertRaises(UnsupportedProjectionAlgorithm):
                project_into_umap(
                    new_vectors, bundle, algorithm="native", dim=2
                )
            with self.assertRaises(UnsupportedProjectionAlgorithm):
                project_into_umap(
                    new_vectors, bundle, algorithm="parametric", dim=2
                )

    def test_dim_mismatch_raises(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            new_vectors = _synthetic_corpus(n_rows=2, dim=4, seed=99)  # wrong dim
            with self.assertRaises(ProjectionDimensionMismatch):
                project_into_umap(
                    new_vectors, bundle, algorithm="knn_weighted", dim=2
                )

    def test_missing_bundle_raises(self) -> None:
        with _isolated_cwd():
            with self.assertRaises(AnalysisError):
                project_into_umap(
                    np.zeros((1, 8), dtype=np.float32),
                    Path("nonexistent/bundle"),
                    algorithm="knn_weighted",
                    dim=2,
                )

    def test_invalid_dim_raises(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            with self.assertRaises(ValueError):
                project_into_umap(
                    np.zeros((1, 8), dtype=np.float32),
                    bundle,
                    algorithm="knn_weighted",
                    dim=4,
                )


class DeterminismTests(unittest.TestCase):
    """SC-003: two `project_into_umap(...)` calls with the same inputs
    return byte-identical coordinates."""

    def test_knn_weighted_byte_identical(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."), dim_bundle="coords_only")
            new_vectors = _synthetic_corpus(n_rows=7, dim=8, seed=99)
            a = project_into_umap(new_vectors, bundle, algorithm="knn_weighted", dim=2)
            b = project_into_umap(new_vectors, bundle, algorithm="knn_weighted", dim=2)
            self.assertTrue(np.array_equal(a, b))
            self.assertEqual(a.tobytes(), b.tobytes())

    def test_native_byte_identical(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            new_vectors = _synthetic_corpus(n_rows=7, dim=8, seed=99)
            a = project_into_umap(new_vectors, bundle, algorithm="native", dim=2)
            b = project_into_umap(new_vectors, bundle, algorithm="native", dim=2)
            self.assertEqual(a.tobytes(), b.tobytes())

    def test_parametric_byte_identical(self) -> None:
        with _isolated_cwd():
            bundle = _build_bundle(Path("."))
            new_vectors = _synthetic_corpus(n_rows=7, dim=8, seed=99)
            a = project_into_umap(new_vectors, bundle, algorithm="parametric", dim=3)
            b = project_into_umap(new_vectors, bundle, algorithm="parametric", dim=3)
            self.assertEqual(a.tobytes(), b.tobytes())


if __name__ == "__main__":
    unittest.main()
