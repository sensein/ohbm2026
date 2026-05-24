"""Tests for ``ohbm2026.atlas_package.ohbm_projector``.

Spec: ``specs/015-neuroscape-context/`` — research R-002 (OHBM 2026
projection into the UMAP space via ``umap.transform``) + R-009
(``OhbmProjectionError`` aggregate-and-re-raise contract).

The projector lands OHBM 2026 Stage-2 vectors into the same 2D/3D
UMAP solution previously fitted on the NeuroScape corpus by
:func:`ohbm2026.atlas_package.umap_fit.fit`. Per R-002 it does NOT
re-fit the UMAP — it uses the fitted model's ``transform`` method.

Per R-009 the projector aggregates failures across the entire OHBM
2026 corpus and the orchestrator re-raises a single
:class:`OhbmProjectionError` at the END of the pass with the full
list of failed submission ids. A single broken record never aborts
a 3K-record projection mid-stream (Principle III — resumability).
"""

from __future__ import annotations

import unittest

import numpy as np

from ohbm2026 import exceptions
from ohbm2026.atlas_package import ohbm_projector, umap_fit


def _synthetic_vectors(n: int, dim: int = 64, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed=seed)
    v = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (v / norms).astype(np.float32)


def _fitted_umap(n_components: int = 3) -> umap_fit.UmapFitResult:
    """Stand-in for a NeuroScape-fitted UMAP — synthetic, small."""

    return umap_fit.fit(
        _synthetic_vectors(n=50, seed=0),
        umap_fit.UmapFitParams(n_components=n_components, n_neighbors=10),
    )


class ProjectHappyPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fitted = _fitted_umap(n_components=3)

    def test_projects_to_n_components_dim(self) -> None:
        oos = [(101, _synthetic_vectors(n=1, seed=101)[0]), (102, _synthetic_vectors(n=1, seed=102)[0])]
        result = ohbm_projector.project(oos, self.fitted)
        self.assertEqual(result.coordinates.shape, (2, 3))
        self.assertEqual(result.coordinates.dtype, np.float32)
        self.assertEqual(result.submission_ids, (101, 102))

    def test_no_failures_means_no_omissions(self) -> None:
        oos = [(101, _synthetic_vectors(n=1, seed=101)[0])]
        result = ohbm_projector.project(oos, self.fitted)
        self.assertEqual(result.failed_submission_ids, ())

    def test_two_runs_with_same_input_produce_identical_coordinates(self) -> None:
        oos = [
            (101, _synthetic_vectors(n=1, seed=101)[0]),
            (102, _synthetic_vectors(n=1, seed=102)[0]),
            (103, _synthetic_vectors(n=1, seed=103)[0]),
        ]
        a = ohbm_projector.project(oos, self.fitted)
        b = ohbm_projector.project(oos, self.fitted)
        self.assertTrue(np.array_equal(a.coordinates, b.coordinates))


class ProjectFailureAggregationTests(unittest.TestCase):
    """R-009: a single broken record must NOT abort the pass; the
    orchestrator re-raises ONCE at the end with the full failed list."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fitted = _fitted_umap(n_components=3)

    def test_nan_vectors_are_aggregated_not_raised_mid_stream(self) -> None:
        good = _synthetic_vectors(n=1, seed=201)[0]
        bad = good.copy()
        bad[5] = np.nan
        worse = good.copy()
        worse[10] = np.inf
        oos = [
            (201, good),
            (202, bad),
            (203, good),
            (204, worse),
            (205, good),
        ]
        result = ohbm_projector.project(oos, self.fitted)
        # The two bad records are recorded in failed_submission_ids;
        # the three good ones are projected.
        self.assertEqual(set(result.failed_submission_ids), {202, 204})
        self.assertEqual(result.submission_ids, (201, 203, 205))
        self.assertEqual(result.coordinates.shape, (3, 3))

    def test_raise_aggregated_lifts_failures_into_a_single_error(self) -> None:
        good = _synthetic_vectors(n=1, seed=301)[0]
        bad = good.copy()
        bad[0] = np.nan
        oos = [(301, good), (302, bad), (303, bad)]
        result = ohbm_projector.project(oos, self.fitted)
        # The orchestrator uses this helper at the END of the
        # projection pass per R-009.
        with self.assertRaises(exceptions.OhbmProjectionError) as ctx:
            ohbm_projector.raise_if_failed(result)
        self.assertEqual(sorted(ctx.exception.failed_submission_ids), [302, 303])

    def test_raise_aggregated_is_noop_when_no_failures(self) -> None:
        good = _synthetic_vectors(n=1, seed=401)[0]
        result = ohbm_projector.project([(401, good)], self.fitted)
        # Must not raise.
        ohbm_projector.raise_if_failed(result)


class ProjectInputShapeRejectionTests(unittest.TestCase):
    """Input shape errors are caller-side bugs, not corpus drift — they
    raise immediately rather than being aggregated."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fitted = _fitted_umap(n_components=3)

    def test_wrong_dim_vector_is_aggregated(self) -> None:
        # A vector with the wrong dim is per-record drift (e.g. one
        # OHBM abstract has a mis-shaped stage-2 vector) — aggregate
        # like NaN, do not raise mid-stream.
        good = _synthetic_vectors(n=1, seed=501)[0]
        wrong = np.zeros((32,), dtype=np.float32)  # wrong dim
        result = ohbm_projector.project([(501, good), (502, wrong)], self.fitted)
        self.assertEqual(result.failed_submission_ids, (502,))

    def test_empty_input_returns_empty_result(self) -> None:
        result = ohbm_projector.project([], self.fitted)
        self.assertEqual(result.coordinates.shape, (0, 3))
        self.assertEqual(result.submission_ids, ())
        self.assertEqual(result.failed_submission_ids, ())


if __name__ == "__main__":
    unittest.main()
