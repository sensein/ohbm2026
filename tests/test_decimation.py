"""Tests for ``ohbm2026.atlas_package.decimation``.

Spec: ``specs/015-neuroscape-context/`` — research R-011 (decimation
+ mobile fallback strategy).

The landing-page UI ships two backdrop samples in ``atlas.parquet``:

- ``neuroscape_backdrop_full`` — every NeuroScape article
- ``neuroscape_backdrop_decimated`` — at most ``target_size`` rows,
  stratified per-cluster so cluster proportions are preserved

The decimation is deterministic (seed=0) so consecutive rebuilds
produce byte-identical decimated backdrops.
"""

from __future__ import annotations

import unittest
from collections import Counter

import numpy as np

from ohbm2026.atlas_package import decimation


class StratifiedSampleShapeTests(unittest.TestCase):
    def test_target_size_caps_total_rows(self) -> None:
        cluster_ids = np.array([c for c in range(5) for _ in range(100)], dtype=np.int16)
        out = decimation.stratified_sample(cluster_ids, target_size=50, seed=0)
        self.assertLessEqual(len(out), 50)

    def test_returns_indices_into_original_array(self) -> None:
        cluster_ids = np.array([0] * 30 + [1] * 30 + [2] * 30, dtype=np.int16)
        out = decimation.stratified_sample(cluster_ids, target_size=20, seed=0)
        self.assertTrue((out >= 0).all())
        self.assertTrue((out < len(cluster_ids)).all())
        self.assertEqual(len(set(out.tolist())), len(out), msg="indices must be unique")

    def test_returns_int64_indices(self) -> None:
        cluster_ids = np.array([0, 1, 2, 3, 4] * 10, dtype=np.int16)
        out = decimation.stratified_sample(cluster_ids, target_size=10, seed=0)
        self.assertEqual(out.dtype, np.int64)


class StratifiedSampleProportionTests(unittest.TestCase):
    def test_per_cluster_quota_is_proportional(self) -> None:
        # Imbalanced clusters: 500 in 0, 250 in 1, 50 in 2 — total 800.
        # Target 80 — should yield ~50 / ~25 / ~5.
        cluster_ids = np.concatenate(
            [
                np.zeros(500, dtype=np.int16),
                np.ones(250, dtype=np.int16),
                np.full(50, 2, dtype=np.int16),
            ]
        )
        out = decimation.stratified_sample(cluster_ids, target_size=80, seed=0)
        picked = cluster_ids[out]
        counts = Counter(picked.tolist())
        self.assertAlmostEqual(counts[0] / counts[1], 2.0, delta=0.5)
        # Cluster 2 (smallest) MUST still appear so the legend stays
        # meaningful.
        self.assertGreater(counts.get(2, 0), 0)

    def test_small_cluster_is_not_excluded(self) -> None:
        # A 1-article cluster MUST still appear in the decimated
        # sample so the cluster legend has at least one point.
        cluster_ids = np.concatenate(
            [
                np.zeros(1000, dtype=np.int16),
                np.array([1], dtype=np.int16),
            ]
        )
        out = decimation.stratified_sample(cluster_ids, target_size=50, seed=0)
        picked = cluster_ids[out]
        self.assertIn(1, picked.tolist())


class StratifiedSampleDeterminismTests(unittest.TestCase):
    def test_two_runs_with_same_seed_produce_identical_indices(self) -> None:
        cluster_ids = np.array([c for c in range(3) for _ in range(100)], dtype=np.int16)
        a = decimation.stratified_sample(cluster_ids, target_size=50, seed=0)
        b = decimation.stratified_sample(cluster_ids, target_size=50, seed=0)
        self.assertTrue(np.array_equal(a, b))

    def test_different_seeds_produce_different_indices(self) -> None:
        cluster_ids = np.array([c for c in range(3) for _ in range(100)], dtype=np.int16)
        a = decimation.stratified_sample(cluster_ids, target_size=50, seed=0)
        b = decimation.stratified_sample(cluster_ids, target_size=50, seed=42)
        # With 300 rows and 50 picks the indices should differ for
        # different seeds — overlapping is fine, identical is not.
        self.assertFalse(np.array_equal(a, b))


class StratifiedSampleEdgeCaseTests(unittest.TestCase):
    def test_empty_input_returns_empty_array(self) -> None:
        out = decimation.stratified_sample(np.empty(0, dtype=np.int16), target_size=50, seed=0)
        self.assertEqual(len(out), 0)

    def test_target_size_greater_than_input_returns_all_indices(self) -> None:
        cluster_ids = np.array([0, 0, 1, 1, 2], dtype=np.int16)
        out = decimation.stratified_sample(cluster_ids, target_size=100, seed=0)
        self.assertEqual(set(out.tolist()), set(range(5)))


if __name__ == "__main__":
    unittest.main()
