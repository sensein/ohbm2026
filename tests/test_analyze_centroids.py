"""Tests for `ohbm2026.analyze.centroids` (US3).

Coverage per spec FR-008 / CA-002 / CA-007:
- `spherical_mean` produces unit-norm direction means matching the
  von-Mises-Fisher recipe.
- `load_centroid_table` discovers version at runtime; missing /
  version-mismatched tables raise typed errors.
- `assign_nearest_centroid` returns angular distances in [0, π],
  pulls cluster ids from the table, and matches the obvious nearest
  centroid for synthetic seeded inputs.
- Metadata of a `write_neuroscape_clusters_bundle` records
  centroid_table_version, n_centroids, distance moments + percentiles.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np

from ohbm2026.analyze.centroids import (
    STAGE2_DIM,
    CentroidTable,
    assign_nearest_centroid,
    load_centroid_table,
    spherical_mean,
    write_neuroscape_clusters_bundle,
)
from ohbm2026.exceptions import (
    AnalysisError,
    CentroidTableMissing,
    CentroidTableVersionMismatch,
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


def _make_centroid_table(
    tmp: Path,
    *,
    n_centroids: int = 4,
    version: str = "test-v1",
    rng_seed: int = 5,
) -> tuple[Path, np.ndarray, np.ndarray]:
    """Write a synthetic centroid file + cluster_table.csv under `tmp/neuroscape/`."""
    nsc_dir = tmp / "data" / "inputs" / "neuroscape"
    nsc_dir.mkdir(parents=True)
    rng = np.random.default_rng(rng_seed)
    raw = rng.normal(size=(n_centroids, STAGE2_DIM)).astype(np.float32)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    centroids = (raw / norms).astype(np.float32)
    cluster_ids = np.arange(1, n_centroids + 1, dtype=np.int32)
    matrix_path = nsc_dir / f"centroids__{version}.npy"
    np.save(matrix_path, centroids)
    sidecar = nsc_dir / "cluster_table.csv"
    with sidecar.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["Cluster ID", "Title", "Description", "Keywords", "Focus", "centroid_table_version"]
        )
        for cid in cluster_ids.tolist():
            writer.writerow(
                [cid, f"Title {cid}", f"Description {cid}", json.dumps([f"kw{cid}"]), "themes", version]
            )
    return nsc_dir, centroids, cluster_ids


class SphericalMeanTests(unittest.TestCase):
    def test_unit_norm_output(self) -> None:
        rng = np.random.default_rng(7)
        vectors = rng.normal(size=(10, 32))
        mean = spherical_mean(vectors)
        self.assertAlmostEqual(float(np.linalg.norm(mean)), 1.0, places=5)

    def test_concentrated_cluster_mean_in_direction(self) -> None:
        """All vectors near a known direction → mean direction ≈ that direction.

        Uses a non-axis-aligned truth direction so the polar `mean_angle`
        recipe (which has reduced precision near coordinate axes) lands
        clearly in the right hemisphere.
        """
        rng = np.random.default_rng(7)
        truth = rng.normal(size=STAGE2_DIM).astype(np.float32)
        truth = truth / np.linalg.norm(truth)
        noisy = truth + rng.normal(scale=0.05, size=(40, STAGE2_DIM)).astype(np.float32)
        # The polar recipe operates on absolute angles, so we need the
        # inputs to all share the same orthant; project all noisy
        # samples onto the positive side relative to truth.
        signs = np.sign(noisy @ truth)
        noisy = noisy * signs[:, None]
        mean = spherical_mean(noisy)
        cos_with_truth = float(np.abs(np.dot(mean, truth)))
        self.assertGreater(cos_with_truth, 0.9)

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            spherical_mean(np.zeros((0, STAGE2_DIM), dtype=np.float32))


class LoadCentroidTableTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir, centroids, cluster_ids = _make_centroid_table(tmp)
            table = load_centroid_table(nsc_dir)
            self.assertEqual(table.table_version, "test-v1")
            np.testing.assert_array_equal(table.cluster_ids, cluster_ids)
            np.testing.assert_allclose(table.centroids, centroids, atol=1e-6)
            self.assertEqual(set(table.labels.keys()), set(cluster_ids.tolist()))
            self.assertEqual(table.labels[1]["Title"], "Title 1")
            self.assertEqual(table.labels[1]["Keywords"], ["kw1"])

    def test_missing_dir_raises(self) -> None:
        with _isolated_cwd():
            with self.assertRaises(CentroidTableMissing):
                load_centroid_table(Path("data/inputs/neuroscape"))

    def test_no_centroid_npy_raises(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir = tmp / "data" / "inputs" / "neuroscape"
            nsc_dir.mkdir(parents=True)
            (nsc_dir / "cluster_table.csv").write_text("Cluster ID,Title\n", encoding="utf-8")
            with self.assertRaises(CentroidTableMissing):
                load_centroid_table(nsc_dir)

    def test_missing_sidecar_raises(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir = tmp / "data" / "inputs" / "neuroscape"
            nsc_dir.mkdir(parents=True)
            mat = np.zeros((2, STAGE2_DIM), dtype=np.float32)
            mat[:, 0] = 1.0
            np.save(nsc_dir / "centroids__nope.npy", mat)
            with self.assertRaises(CentroidTableMissing):
                load_centroid_table(nsc_dir)

    def test_version_mismatch_raises(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir, _, _ = _make_centroid_table(tmp, version="test-v1")
            # Rewrite the sidecar with a different recorded version
            sidecar = nsc_dir / "cluster_table.csv"
            text = sidecar.read_text(encoding="utf-8")
            sidecar.write_text(text.replace("test-v1", "wrong-version"), encoding="utf-8")
            with self.assertRaises(CentroidTableVersionMismatch):
                load_centroid_table(nsc_dir)

    def test_non_unit_centroids_raise(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir = tmp / "data" / "inputs" / "neuroscape"
            nsc_dir.mkdir(parents=True)
            # Centroids that are NOT unit-norm
            mat = np.ones((2, STAGE2_DIM), dtype=np.float32) * 5.0
            np.save(nsc_dir / "centroids__bad.npy", mat)
            sidecar = nsc_dir / "cluster_table.csv"
            sidecar.write_text(
                "Cluster ID,Title,Description,Keywords,Focus,centroid_table_version\n"
                "1,T1,D1,\"[\"\"kw\"\"]\",themes,bad\n"
                "2,T2,D2,\"[\"\"kw\"\"]\",themes,bad\n",
                encoding="utf-8",
            )
            with self.assertRaises(AnalysisError):
                load_centroid_table(nsc_dir)


class AssignNearestCentroidTests(unittest.TestCase):
    def test_assigns_to_obvious_nearest(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir, centroids, cluster_ids = _make_centroid_table(tmp, n_centroids=3)
            table = load_centroid_table(nsc_dir)
            # Use the centroid rows themselves as inputs — each should
            # assign to its own cluster id, with distance ~ 0.
            assigned_ids, distances = assign_nearest_centroid(centroids, table)
            np.testing.assert_array_equal(assigned_ids, cluster_ids)
            for d in distances:
                self.assertLess(float(d), 1e-3)

    def test_distance_range(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir, _, _ = _make_centroid_table(tmp, n_centroids=5)
            table = load_centroid_table(nsc_dir)
            rng = np.random.default_rng(7)
            inputs = rng.normal(size=(50, STAGE2_DIM)).astype(np.float32)
            _ids, distances = assign_nearest_centroid(inputs, table)
            self.assertEqual(distances.shape, (50,))
            self.assertTrue((distances >= 0).all())
            self.assertTrue((distances <= np.pi + 1e-5).all())

    def test_dim_mismatch_raises(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir, _, _ = _make_centroid_table(tmp)
            table = load_centroid_table(nsc_dir)
            bad = np.zeros((2, STAGE2_DIM - 1), dtype=np.float32)
            with self.assertRaises(AnalysisError):
                assign_nearest_centroid(bad, table)


class WriteBundleTests(unittest.TestCase):
    def test_metadata_carries_required_fields(self) -> None:
        with _isolated_cwd() as tmp:
            nsc_dir, centroids, cluster_ids = _make_centroid_table(tmp, n_centroids=4)
            table = load_centroid_table(nsc_dir)
            inputs = centroids.copy()
            assigned_ids, distances = assign_nearest_centroid(inputs, table)
            ids = np.arange(1, 5, dtype=np.int64)
            bundle_dir = tmp / "data" / "outputs" / "analysis" / "neuroscape_abstract" / "neuroscape_clusters__xyz"
            write_neuroscape_clusters_bundle(
                bundle_dir,
                ids=ids,
                cluster_ids=assigned_ids,
                distances=distances,
                centroid_table=table,
                source_model="neuroscape",
                seed=42,
            )
            meta = json.loads((bundle_dir / "metadata.json").read_text())
            self.assertEqual(meta["kind"], "neuroscape_clusters")
            self.assertEqual(meta["source_model"], "neuroscape")
            self.assertNotIn("stage2_applied", meta)  # field removed
            self.assertIn("domain_model_checkpoint_sha256", meta)
            self.assertEqual(meta["centroid_table_version"], "test-v1")
            self.assertEqual(meta["n_centroids"], 4)
            self.assertIn("distance_mean", meta)
            self.assertIn("distance_percentile_10", meta)


if __name__ == "__main__":
    unittest.main()
