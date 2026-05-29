"""Tests for ``ohbm2026.atlas_package.neighbour_index``.

Spec: ``specs/015-neuroscape-context/`` — research R-008 (k-NN over
NeuroScape Stage-2 vectors, k=20, cosine).

The neighbour index produces, for each NeuroScape article, the
``k`` nearest PubMed ids in Stage-2 space + their cosine distances.
The result feeds ``neuroscape.parquet/neighbors_neuroscape`` (parallel
arrays per :data:`contracts/parquet-schemas.md`) and powers the
"nearest articles" list on `/neuroscape/abstract/<id>/` detail
pages.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohbm2026 import exceptions
from ohbm2026.atlas_package import neighbour_index


def _synthetic_vectors(n: int, dim: int = 64, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed=seed)
    v = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (v / norms).astype(np.float32)


class BuildKnnShapeTests(unittest.TestCase):
    def test_returns_two_parallel_arrays(self) -> None:
        pmids = np.arange(50, dtype=np.int64) + 10000
        vectors = _synthetic_vectors(n=50)
        result = neighbour_index.build_knn(pmids, vectors, k=5)
        self.assertEqual(result.pmids.shape, (50,))
        self.assertEqual(result.nearest_pmids.shape, (50, 5))
        self.assertEqual(result.nearest_distances.shape, (50, 5))

    def test_dtypes_match_parquet_contract(self) -> None:
        pmids = np.arange(20, dtype=np.int64) + 10000
        vectors = _synthetic_vectors(n=20)
        result = neighbour_index.build_knn(pmids, vectors, k=3)
        self.assertEqual(result.pmids.dtype, np.int64)
        self.assertEqual(result.nearest_pmids.dtype, np.int64)
        self.assertEqual(result.nearest_distances.dtype, np.float32)


class BuildKnnSemanticsTests(unittest.TestCase):
    def test_self_is_not_included_in_own_neighbours(self) -> None:
        pmids = np.arange(20, dtype=np.int64) + 10000
        vectors = _synthetic_vectors(n=20)
        result = neighbour_index.build_knn(pmids, vectors, k=5)
        for i, neighbours in enumerate(result.nearest_pmids):
            self.assertNotIn(
                pmids[i],
                neighbours.tolist(),
                msg=f"self-id should be excluded for row {i}",
            )

    def test_nearest_neighbour_is_actually_nearest(self) -> None:
        # Construct a deliberate near-duplicate pair (pmids 10000 + 10001
        # share most of their vector). Each should appear as the other's
        # nearest neighbour.
        vectors = _synthetic_vectors(n=20)
        vectors[1] = vectors[0] + 0.001 * vectors[2]
        # Re-normalise so the cosine geometry stays canonical.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = (vectors / norms).astype(np.float32)
        pmids = np.arange(20, dtype=np.int64) + 10000
        result = neighbour_index.build_knn(pmids, vectors, k=3)
        # Row 0's first neighbour should be 10001; row 1's first
        # neighbour should be 10000.
        self.assertEqual(int(result.nearest_pmids[0, 0]), 10001)
        self.assertEqual(int(result.nearest_pmids[1, 0]), 10000)

    def test_distances_are_in_ascending_order(self) -> None:
        pmids = np.arange(50, dtype=np.int64) + 10000
        vectors = _synthetic_vectors(n=50)
        result = neighbour_index.build_knn(pmids, vectors, k=10)
        for i, dists in enumerate(result.nearest_distances):
            diffs = np.diff(dists)
            self.assertTrue(
                np.all(diffs >= -1e-6),
                msg=f"row {i}: distances not in ascending order: {dists.tolist()}",
            )


class BuildKnnDeterminismTests(unittest.TestCase):
    def test_two_runs_produce_identical_output(self) -> None:
        pmids = np.arange(30, dtype=np.int64) + 10000
        vectors = _synthetic_vectors(n=30)
        a = neighbour_index.build_knn(pmids, vectors, k=4)
        b = neighbour_index.build_knn(pmids, vectors, k=4)
        self.assertTrue(np.array_equal(a.nearest_pmids, b.nearest_pmids))
        self.assertTrue(np.array_equal(a.nearest_distances, b.nearest_distances))


class BuildKnnEdgeCaseTests(unittest.TestCase):
    def test_k_greater_than_n_minus_1_is_clamped(self) -> None:
        # 5 rows, asking for k=20 — the function MUST clamp at n-1=4
        # rather than padding with garbage. Document via assertion.
        pmids = np.arange(5, dtype=np.int64) + 10000
        vectors = _synthetic_vectors(n=5)
        result = neighbour_index.build_knn(pmids, vectors, k=20)
        self.assertEqual(result.nearest_pmids.shape, (5, 4))
        self.assertEqual(result.nearest_distances.shape, (5, 4))


class BuildKnnCacheTests(unittest.TestCase):
    """The brute-force k-NN is the dominant build cost on the 461k
    corpus. Like the UMAP fit, it must cache on disk keyed by its
    inputs so a rebuild with unchanged (pmids, vectors, k) skips the
    O(n²) search entirely (constitution III)."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_root = Path(self._tmp.name)
        self.pmids = np.arange(40, dtype=np.int64) + 10000
        self.vectors = _synthetic_vectors(n=40)

    def test_state_key_is_stable_for_identical_inputs(self) -> None:
        a = neighbour_index.compute_knn_state_key(self.pmids, self.vectors, k=5)
        b = neighbour_index.compute_knn_state_key(self.pmids, self.vectors, k=5)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 12)

    def test_state_key_changes_with_k_and_vectors(self) -> None:
        base = neighbour_index.compute_knn_state_key(self.pmids, self.vectors, k=5)
        self.assertNotEqual(
            base, neighbour_index.compute_knn_state_key(self.pmids, self.vectors, k=6)
        )
        other = _synthetic_vectors(n=40, seed=99)
        self.assertNotEqual(
            base, neighbour_index.compute_knn_state_key(self.pmids, other, k=5)
        )

    def test_miss_then_hit_returns_identical_result(self) -> None:
        miss = neighbour_index.build_knn(
            self.pmids, self.vectors, k=5, cache_root=self.cache_root
        )
        hit = neighbour_index.build_knn(
            self.pmids, self.vectors, k=5, cache_root=self.cache_root
        )
        self.assertTrue(np.array_equal(miss.nearest_pmids, hit.nearest_pmids))
        self.assertTrue(np.array_equal(miss.nearest_distances, hit.nearest_distances))
        self.assertTrue(np.array_equal(miss.pmids, hit.pmids))

    def test_hit_reads_cache_rather_than_recomputing(self) -> None:
        # Populate, then tamper the cached distances with a sentinel. A
        # genuine cache HIT returns the sentinel; a recompute would
        # return the real distances. Proves the second call is a read.
        neighbour_index.build_knn(
            self.pmids, self.vectors, k=5, cache_root=self.cache_root
        )
        sk = neighbour_index.compute_knn_state_key(self.pmids, self.vectors, k=5)
        paths = neighbour_index.cache_paths(self.cache_root, sk)
        sentinel = np.full((40, 5), 0.4242, dtype=np.float32)
        np.save(paths["nearest_distances"], sentinel, allow_pickle=False)
        hit = neighbour_index.build_knn(
            self.pmids, self.vectors, k=5, cache_root=self.cache_root
        )
        self.assertTrue(np.array_equal(hit.nearest_distances, sentinel))

    def test_no_cache_root_still_computes(self) -> None:
        res = neighbour_index.build_knn(self.pmids, self.vectors, k=5)
        self.assertEqual(res.nearest_pmids.shape, (40, 5))

    def test_incomplete_cache_entry_raises(self) -> None:
        neighbour_index.build_knn(
            self.pmids, self.vectors, k=5, cache_root=self.cache_root
        )
        sk = neighbour_index.compute_knn_state_key(self.pmids, self.vectors, k=5)
        paths = neighbour_index.cache_paths(self.cache_root, sk)
        # Delete one companion file → the entry is corrupt; the loader
        # must raise loudly (operator cleans up) rather than silently
        # recompute or return a partial result.
        paths["nearest_pmids"].unlink()
        with self.assertRaises(exceptions.KnnCacheError):
            neighbour_index.build_knn(
                self.pmids, self.vectors, k=5, cache_root=self.cache_root
            )


if __name__ == "__main__":
    unittest.main()
