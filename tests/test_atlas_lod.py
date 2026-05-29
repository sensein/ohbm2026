"""Tests for ``ohbm2026.atlas_package.lod`` — quadtree blue-noise LOD.

Spec: ``specs/019-neuroscape-semantic-search/plan-lod-backdrop.md``.

``assign_lod_levels`` assigns every point a level-of-detail rank from a
deterministic coarse→fine quadtree: at each resolution it keeps ONE
representative per occupied grid cell, so any cumulative prefix
``levels <= k`` is a near-uniform (blue-noise) spatial cover that
preserves the scatter silhouette. The remaining points fall to a final
"rest" level so ``union(levels) == all points`` and the full corpus is
recoverable by loading every level.
"""

from __future__ import annotations

import unittest

import numpy as np

from ohbm2026.atlas_package import lod


def _grid_cell(coords: np.ndarray, resolution: int) -> np.ndarray:
    """Replicate the module's square-cell binning for assertions."""
    mins = coords.min(axis=0)
    span = float((coords.max(axis=0) - mins).max())
    span = span if span > 0 else 1.0
    norm = (coords - mins) / span
    cell = np.floor(norm * resolution).astype(np.int64)
    cell = np.clip(cell, 0, resolution - 1)
    return cell[:, 0] * resolution + cell[:, 1]


class AssignLodLevelsShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        rng = np.random.default_rng(0)
        self.coords = rng.random((2000, 2)).astype(np.float32)
        self.resolutions = (4, 8, 16)

    def test_returns_int16_level_per_point(self) -> None:
        levels = lod.assign_lod_levels(self.coords, resolutions=self.resolutions)
        self.assertEqual(levels.shape, (2000,))
        self.assertEqual(levels.dtype, np.int16)

    def test_every_point_assigned_a_level(self) -> None:
        levels = lod.assign_lod_levels(self.coords, resolutions=self.resolutions)
        # Levels span 0..len(resolutions) inclusive (last == rest level).
        self.assertGreaterEqual(int(levels.min()), 0)
        self.assertLessEqual(int(levels.max()), len(self.resolutions))

    def test_union_of_levels_is_full_corpus(self) -> None:
        levels = lod.assign_lod_levels(self.coords, resolutions=self.resolutions)
        self.assertEqual(len(levels), len(self.coords))
        # No sentinel / unassigned values.
        self.assertFalse((levels < 0).any())


class BlueNoiseCoverTests(unittest.TestCase):
    """Each level's representatives occupy distinct cells at that level's
    resolution → a blue-noise cover (the silhouette-preserving property)."""

    def test_level_zero_points_have_distinct_coarse_cells(self) -> None:
        rng = np.random.default_rng(1)
        coords = rng.random((3000, 2)).astype(np.float32)
        resolutions = (8, 16, 32)
        levels = lod.assign_lod_levels(coords, resolutions=resolutions)
        l0 = np.flatnonzero(levels == 0)
        cells = _grid_cell(coords, resolutions[0])[l0]
        self.assertEqual(len(set(cells.tolist())), len(l0))

    def test_each_representative_level_has_distinct_cells(self) -> None:
        rng = np.random.default_rng(2)
        coords = rng.random((4000, 2)).astype(np.float32)
        resolutions = (8, 16, 32)
        levels = lod.assign_lod_levels(coords, resolutions=resolutions)
        for level, res in enumerate(resolutions):
            members = np.flatnonzero(levels == level)
            if members.size == 0:
                continue
            cells = _grid_cell(coords, res)[members]
            self.assertEqual(
                len(set(cells.tolist())),
                len(members),
                msg=f"level {level} has duplicate cells at resolution {res}",
            )

    def test_coarse_level_is_bounded_by_cell_count(self) -> None:
        rng = np.random.default_rng(3)
        coords = rng.random((5000, 2)).astype(np.float32)
        resolutions = (10, 20, 40)
        levels = lod.assign_lod_levels(coords, resolutions=resolutions)
        n_level0 = int((levels == 0).sum())
        # At most one representative per cell at resolution 10 → ≤ 100.
        self.assertLessEqual(n_level0, 10 * 10)


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_output(self) -> None:
        rng = np.random.default_rng(4)
        coords = rng.random((1500, 2)).astype(np.float32)
        a = lod.assign_lod_levels(coords, resolutions=(8, 16))
        b = lod.assign_lod_levels(coords, resolutions=(8, 16))
        self.assertTrue(np.array_equal(a, b))

    def test_order_independent_with_tiebreak_keys(self) -> None:
        rng = np.random.default_rng(5)
        coords = rng.random((1200, 2)).astype(np.float32)
        keys = np.arange(1200, dtype=np.int64) * 7 + 13  # stand-in pubmed_ids
        resolutions = (8, 16, 32)

        levels = lod.assign_lod_levels(
            coords, resolutions=resolutions, tiebreak_keys=keys
        )
        ref = dict(zip(keys.tolist(), levels.tolist()))

        perm = rng.permutation(1200)
        levels_perm = lod.assign_lod_levels(
            coords[perm], resolutions=resolutions, tiebreak_keys=keys[perm]
        )
        got = dict(zip(keys[perm].tolist(), levels_perm.tolist()))

        self.assertEqual(ref, got)


class EdgeCaseTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        levels = lod.assign_lod_levels(
            np.empty((0, 2), dtype=np.float32), resolutions=(8, 16)
        )
        self.assertEqual(levels.shape, (0,))
        self.assertEqual(levels.dtype, np.int16)

    def test_single_point_is_level_zero(self) -> None:
        levels = lod.assign_lod_levels(
            np.array([[0.5, 0.5]], dtype=np.float32), resolutions=(8, 16)
        )
        self.assertEqual(levels.tolist(), [0])

    def test_all_identical_points_one_representative_rest_to_final_level(self) -> None:
        coords = np.zeros((50, 2), dtype=np.float32)
        resolutions = (8, 16, 32)
        levels = lod.assign_lod_levels(coords, resolutions=resolutions)
        # Every point shares the single occupied cell at every resolution,
        # so exactly one is a representative (level 0) and the other 49
        # fall to the rest level.
        self.assertEqual(int((levels == 0).sum()), 1)
        self.assertEqual(int((levels == len(resolutions)).sum()), 49)


class CoverageMetricTests(unittest.TestCase):
    def test_cumulative_coverage_is_monotone_and_reaches_one(self) -> None:
        rng = np.random.default_rng(6)
        coords = rng.random((3000, 2)).astype(np.float32)
        resolutions = (8, 16, 32)
        levels = lod.assign_lod_levels(coords, resolutions=resolutions)
        cov = lod.lod_coverage(coords, levels, reference_resolution=16)
        self.assertEqual(len(cov), int(levels.max()) + 1)
        # Monotone non-decreasing cumulative coverage.
        for earlier, later in zip(cov, cov[1:]):
            self.assertLessEqual(earlier, later + 1e-9)
        # The full set covers all occupied reference cells.
        self.assertAlmostEqual(cov[-1], 1.0, places=6)
        # The coarse level already covers a meaningful fraction of the
        # silhouette (blue-noise property), not a tiny sliver.
        self.assertGreater(cov[0], 0.1)


if __name__ == "__main__":
    unittest.main()
