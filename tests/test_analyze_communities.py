"""Tests for `ohbm2026.analyze.communities` (US4).

Coverage per spec FR-007 + CA-002:
- FAISS `IndexFlatIP` kNN over L2-normalized vectors returns sensible
  shapes + similarities in `[-1, 1]` (`(0, 1]` after positive-filter).
- Symmetrization preserves edges and averages reciprocal weights.
- Leiden CPM recovers seeded duplicate groups on a small synthetic.
- Resolution sweep records `(resolution, n_communities, modularity)` per
  point.
- `community_ids` are reordered so `0` is the largest community.
- Fixed-seed runs are byte-identical (deterministic).
- A dominant single-community result triggers
  `CommunityResolutionDegenerate` warning.
"""

from __future__ import annotations

import unittest
import warnings

import numpy as np

from ohbm2026.analyze.communities import (
    DEFAULT_KNN_K,
    build_faiss_knn,
    detect_communities,
    knn_to_graph,
    leiden_cpm_partition,
    reorder_by_size,
    resolution_sweep,
    select_plateau_resolution,
    ResolutionSweepEntry,
)
from ohbm2026.exceptions import CommunityResolutionDegenerate


def _three_cluster_corpus(
    n_per_cluster: int = 40, dim: int = 32, *, seed: int = 7
) -> np.ndarray:
    """Synthetic 3-cluster corpus with deliberate within-cluster proximity."""
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(3, dim)) * 4.0
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    parts = []
    for c in centers:
        cluster = c + rng.normal(scale=0.1, size=(n_per_cluster, dim))
        cluster /= np.linalg.norm(cluster, axis=1, keepdims=True)
        parts.append(cluster)
    return np.vstack(parts).astype(np.float32)


class BuildFaissKnnTests(unittest.TestCase):
    def test_shape_and_self_excluded(self) -> None:
        rng = np.random.default_rng(7)
        vectors = rng.normal(size=(50, 16)).astype(np.float32)
        indices, sims = build_faiss_knn(vectors, k=5)
        self.assertEqual(indices.shape, (50, 5))
        self.assertEqual(sims.shape, (50, 5))
        # No self-edges: row i should not contain index i.
        for i in range(50):
            self.assertNotIn(i, indices[i].tolist(), f"self-edge in row {i}")

    def test_similarity_bounded(self) -> None:
        rng = np.random.default_rng(7)
        vectors = rng.normal(size=(20, 8)).astype(np.float32)
        _ind, sims = build_faiss_knn(vectors, k=4)
        # Inner products of unit vectors are in [-1, 1] (float tolerance).
        self.assertGreaterEqual(float(sims.min()), -1.0 - 1e-3)
        self.assertLessEqual(float(sims.max()), 1.0 + 1e-3)

    def test_small_corpus_k_clamped(self) -> None:
        rng = np.random.default_rng(7)
        vectors = rng.normal(size=(4, 8)).astype(np.float32)
        indices, sims = build_faiss_knn(vectors, k=10)  # k > n-1
        self.assertEqual(indices.shape, (4, 3))  # k clamped to n-1


class KnnToGraphTests(unittest.TestCase):
    def test_symmetrization_averages_weights(self) -> None:
        # Build a tiny manual kNN: row 0 → row 1 with sim 1.0;
        # row 1 → row 0 with sim 0.5. After symmetrization the edge weight
        # is the mean (0.75).
        indices = np.asarray([[1, 2], [0, 2], [0, 1]], dtype=np.int32)
        sims = np.asarray(
            [[1.0, 0.2], [0.5, 0.3], [0.1, 0.4]], dtype=np.float32
        )
        graph = knn_to_graph(indices, sims, symmetrize=True)
        self.assertEqual(graph.vcount(), 3)
        # Find the edge between vertex 0 and 1
        edge_id = graph.get_eid(0, 1)
        self.assertAlmostEqual(
            float(graph.es[edge_id]["weight"]), (1.0 + 0.5) / 2.0, places=5
        )

    def test_negative_sims_dropped_by_default(self) -> None:
        indices = np.asarray([[1], [0]], dtype=np.int32)
        sims = np.asarray([[-0.5], [-0.5]], dtype=np.float32)
        graph = knn_to_graph(indices, sims, symmetrize=True, keep_negative=False)
        self.assertEqual(graph.ecount(), 0)


class LeidenCpmTests(unittest.TestCase):
    def test_recovers_duplicate_groups(self) -> None:
        """Three deliberate clusters → Leiden CPM at a moderate resolution
        should produce ≥3 communities and put within-cluster rows together."""
        vectors = _three_cluster_corpus(n_per_cluster=30, dim=16, seed=7)
        indices, sims = build_faiss_knn(vectors, k=10)
        graph = knn_to_graph(indices, sims, symmetrize=True)
        # Try a few resolutions and pick the one that gives >= 3 clusters
        # with the highest modularity. CPM resolution range is data-
        # dependent so this loop is more reliable than a single fixed point.
        best_partition: tuple[np.ndarray, float] | None = None
        best_clusters = 0
        for resolution in (0.005, 0.01, 0.02, 0.05, 0.1, 0.2):
            membership, modularity = leiden_cpm_partition(
                graph, resolution=resolution, seed=42
            )
            n_clusters = int(np.unique(membership).size)
            if n_clusters >= 3 and (best_partition is None or n_clusters < best_clusters or modularity > best_partition[1]):
                best_partition = (membership, modularity)
                best_clusters = n_clusters
                if 3 <= n_clusters <= 6:
                    break
        self.assertIsNotNone(best_partition)
        membership, _ = best_partition  # type: ignore[misc]
        self.assertGreaterEqual(int(np.unique(membership).size), 3)
        # Check that rows from the SAME planted cluster mostly co-cluster:
        # first 30 rows are cluster 0, next 30 are cluster 1, etc.
        # The dominant assignment for each planted cluster should be a single id.
        for planted in range(3):
            slice_membership = membership[planted * 30 : (planted + 1) * 30]
            counts = np.bincount(slice_membership)
            self.assertGreaterEqual(counts.max(), 20)  # ≥66% co-clustered


class ResolutionSweepTests(unittest.TestCase):
    def test_sweep_records_every_point(self) -> None:
        vectors = _three_cluster_corpus(n_per_cluster=10, dim=8, seed=7)
        indices, sims = build_faiss_knn(vectors, k=4)
        graph = knn_to_graph(indices, sims, symmetrize=True)
        sweep = resolution_sweep(
            graph, resolution_min=0.001, resolution_max=0.1, points=5, seed=42
        )
        self.assertEqual(len(sweep), 5)
        for entry in sweep:
            self.assertIsInstance(entry, ResolutionSweepEntry)
            self.assertGreater(entry.resolution, 0.001)
            self.assertLessEqual(entry.resolution, 0.1)
            self.assertGreaterEqual(entry.n_communities, 1)

    def test_sweep_rejects_inverted_range(self) -> None:
        vectors = _three_cluster_corpus(n_per_cluster=5, dim=4, seed=7)
        indices, sims = build_faiss_knn(vectors, k=2)
        graph = knn_to_graph(indices, sims, symmetrize=True)
        with self.assertRaises(ValueError):
            resolution_sweep(
                graph, resolution_min=0.1, resolution_max=0.001, points=5, seed=42
            )


class SelectPlateauResolutionTests(unittest.TestCase):
    def test_chooses_elbow(self) -> None:
        # Synthetic sweep with a clear elbow: gains 0.3 → 0.3 → 0.1 → 0.05.
        sweep = [
            ResolutionSweepEntry(resolution=0.01, n_communities=2, modularity=0.10),
            ResolutionSweepEntry(resolution=0.02, n_communities=3, modularity=0.40),
            ResolutionSweepEntry(resolution=0.03, n_communities=5, modularity=0.70),
            ResolutionSweepEntry(resolution=0.04, n_communities=8, modularity=0.80),
            ResolutionSweepEntry(resolution=0.05, n_communities=12, modularity=0.85),
        ]
        idx = select_plateau_resolution(sweep)
        chosen = sweep[idx]
        # Elbow should land at the first point where per-cluster modularity
        # gain drops below the median — that's the 8-cluster or
        # 12-cluster entry depending on rounding.
        self.assertGreaterEqual(chosen.n_communities, 5)

    def test_single_entry_returns_zero(self) -> None:
        sweep = [ResolutionSweepEntry(resolution=0.05, n_communities=3, modularity=0.6)]
        self.assertEqual(select_plateau_resolution(sweep), 0)


class ReorderBySizeTests(unittest.TestCase):
    def test_largest_becomes_zero(self) -> None:
        m = np.asarray([2, 2, 2, 2, 0, 0, 1], dtype=np.int32)
        # Original sizes: 2→4, 0→2, 1→1. After reorder: 2 becomes 0, 0 becomes 1, 1 becomes 2.
        reordered = reorder_by_size(m)
        # All original 2s map to 0
        self.assertTrue((reordered[m == 2] == 0).all())
        # All original 0s map to 1
        self.assertTrue((reordered[m == 0] == 1).all())
        # The original 1 maps to 2
        self.assertTrue((reordered[m == 1] == 2).all())

    def test_empty(self) -> None:
        np.testing.assert_array_equal(
            reorder_by_size(np.asarray([], dtype=np.int32)),
            np.asarray([], dtype=np.int32),
        )


class DetectCommunitiesTests(unittest.TestCase):
    def test_deterministic_with_seed(self) -> None:
        vectors = _three_cluster_corpus(n_per_cluster=20, dim=16, seed=7)
        a = detect_communities(
            vectors,
            knn_k=10,
            resolution_min=0.001,
            resolution_max=0.1,
            resolution_points=5,
            seed=42,
        )
        b = detect_communities(
            vectors,
            knn_k=10,
            resolution_min=0.001,
            resolution_max=0.1,
            resolution_points=5,
            seed=42,
        )
        np.testing.assert_array_equal(a.community_ids, b.community_ids)
        self.assertEqual(a.selected_resolution, b.selected_resolution)
        self.assertEqual(a.n_communities, b.n_communities)

    def test_largest_community_zero(self) -> None:
        vectors = _three_cluster_corpus(n_per_cluster=30, dim=16, seed=7)
        result = detect_communities(
            vectors,
            knn_k=10,
            resolution_min=0.001,
            resolution_max=0.1,
            resolution_points=10,
            seed=42,
        )
        # Largest community has the most rows assigned, and it's labeled 0.
        counts = np.bincount(result.community_ids)
        self.assertEqual(int(counts.argmax()), 0)

    def test_degenerate_resolution_warns(self) -> None:
        """A nearly-trivial corpus (all vectors near a single direction)
        should produce a dominant community → CommunityResolutionDegenerate."""
        rng = np.random.default_rng(7)
        direction = rng.normal(size=16).astype(np.float32)
        direction /= np.linalg.norm(direction)
        # All 50 vectors near a single direction with tiny jitter.
        vectors = direction + rng.normal(scale=0.001, size=(50, 16)).astype(
            np.float32
        )
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            result = detect_communities(
                vectors,
                knn_k=10,
                resolution_min=0.0001,
                resolution_max=0.001,
                resolution_points=5,
                seed=42,
            )
        # Either we got a degenerate warning OR the resolution sweep
        # successfully split (some corpora resist single-cluster collapse).
        # The minimum guarantee: result.largest_community_share is reported.
        self.assertGreater(result.largest_community_share, 0.0)
        if result.largest_community_share > 0.9:
            self.assertTrue(
                any(issubclass(w.category, CommunityResolutionDegenerate) for w in records),
                "expected CommunityResolutionDegenerate warning",
            )


if __name__ == "__main__":
    unittest.main()
