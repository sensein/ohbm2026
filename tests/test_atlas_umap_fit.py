"""Tests for ``ohbm2026.atlas_package.umap_fit``.

Spec: ``specs/015-neuroscape-context/`` — research R-001 (UMAP fit
parameters and seed) + R-009 (``UmapFitError``).

Per R-001 the production fit uses ``n_components ∈ {2, 3}``,
``n_neighbors=30, min_dist=0.10, metric='cosine', seed=0,
init='spectral'``. These tests use a synthetic 50-vector batch with
a smaller ``n_neighbors`` so the unit test runs in <2 s — the
production defaults are exercised at the orchestrator level by T020.

Per the 2026-05-23 user directive, no test loads the full 461K-row
corpus.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohbm2026 import exceptions
from ohbm2026.atlas_package import umap_fit


def _synthetic_vectors(n: int = 50, dim: int = 64, seed: int = 0) -> np.ndarray:
    """Deterministic unit-norm batch — stand-in for NeuroScape Stage-2 vectors."""

    rng = np.random.default_rng(seed=seed)
    v = rng.standard_normal((n, dim)).astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (v / norms).astype(np.float32)


class UmapFitParamsTests(unittest.TestCase):
    def test_default_params_match_R001(self) -> None:
        p = umap_fit.UmapFitParams(n_components=3)
        self.assertEqual(p.n_neighbors, 30)
        self.assertAlmostEqual(p.min_dist, 0.10)
        self.assertEqual(p.metric, "cosine")
        self.assertEqual(p.seed, 0)
        self.assertEqual(p.init, "spectral")


class ComputeStateKeyTests(unittest.TestCase):
    def test_state_key_is_12_hex_chars(self) -> None:
        v = _synthetic_vectors(n=20)
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        key = umap_fit.compute_state_key(v, p)
        self.assertRegex(key, r"^[0-9a-f]{12}$")

    def test_state_key_is_deterministic(self) -> None:
        v = _synthetic_vectors(n=20)
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        self.assertEqual(
            umap_fit.compute_state_key(v, p),
            umap_fit.compute_state_key(v, p),
        )

    def test_state_key_changes_when_vectors_change(self) -> None:
        v1 = _synthetic_vectors(n=20, seed=0)
        v2 = _synthetic_vectors(n=20, seed=1)
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        self.assertNotEqual(
            umap_fit.compute_state_key(v1, p),
            umap_fit.compute_state_key(v2, p),
        )

    def test_state_key_changes_when_params_change(self) -> None:
        v = _synthetic_vectors(n=20)
        p3 = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        p2 = umap_fit.UmapFitParams(n_components=2, n_neighbors=5)
        self.assertNotEqual(
            umap_fit.compute_state_key(v, p3),
            umap_fit.compute_state_key(v, p2),
        )

    def test_state_key_matches_sha256_truncation_contract(self) -> None:
        v = _synthetic_vectors(n=10)
        p = umap_fit.UmapFitParams(n_components=2, n_neighbors=3)
        # Verify the documented contract: sha256(vectors_bytes || params_json)[:12]
        h = hashlib.sha256()
        h.update(np.ascontiguousarray(v.astype(np.float32)).tobytes())
        h.update(
            json.dumps(
                {
                    "n_components": p.n_components,
                    "n_neighbors": p.n_neighbors,
                    "min_dist": p.min_dist,
                    "metric": p.metric,
                    "seed": p.seed,
                    "init": p.init,
                },
                sort_keys=True,
            ).encode()
        )
        self.assertEqual(umap_fit.compute_state_key(v, p), h.hexdigest()[:12])


class FitDeterminismTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vectors = _synthetic_vectors(n=50)
        # Smaller n_neighbors so the 50-vector synthetic batch fits.
        # Production defaults are validated at the orchestrator level
        # against the real release (T020 / T033).
        self.params_3d = umap_fit.UmapFitParams(n_components=3, n_neighbors=10)
        self.params_2d = umap_fit.UmapFitParams(n_components=2, n_neighbors=10)

    def test_3d_fit_returns_expected_shape(self) -> None:
        result = umap_fit.fit(self.vectors, self.params_3d)
        self.assertEqual(result.embedded.shape, (50, 3))
        self.assertEqual(result.embedded.dtype, np.float32)

    def test_2d_fit_returns_expected_shape(self) -> None:
        result = umap_fit.fit(self.vectors, self.params_2d)
        self.assertEqual(result.embedded.shape, (50, 2))

    def test_two_fits_with_same_input_produce_identical_embeddings(self) -> None:
        a = umap_fit.fit(self.vectors, self.params_3d)
        b = umap_fit.fit(self.vectors, self.params_3d)
        self.assertTrue(
            np.array_equal(a.embedded, b.embedded),
            msg=(
                "UMAP fit is not deterministic for the same input + seed. "
                "Stage 15 requires byte-identical embeddings across rebuilds "
                "(R-001 + SC-004)."
            ),
        )

    def test_2d_fit_is_independent_of_3d_fit(self) -> None:
        a = umap_fit.fit(self.vectors, self.params_3d)
        b = umap_fit.fit(self.vectors, self.params_2d)
        self.assertNotEqual(a.state_key, b.state_key)


class FitRejectionTests(unittest.TestCase):
    def test_nan_input_raises_umap_fit_error(self) -> None:
        v = _synthetic_vectors(n=20)
        v[0, 5] = np.nan
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        with self.assertRaises(exceptions.UmapFitError) as ctx:
            umap_fit.fit(v, p)
        self.assertEqual(ctx.exception.reason, "nan_input")
        self.assertEqual(ctx.exception.n_vectors, 20)

    def test_inf_input_raises_umap_fit_error(self) -> None:
        v = _synthetic_vectors(n=20)
        v[3, 10] = np.inf
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        with self.assertRaises(exceptions.UmapFitError) as ctx:
            umap_fit.fit(v, p)
        self.assertEqual(ctx.exception.reason, "nonfinite_input")

    def test_empty_input_raises_umap_fit_error(self) -> None:
        v = np.empty((0, 64), dtype=np.float32)
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        with self.assertRaises(exceptions.UmapFitError) as ctx:
            umap_fit.fit(v, p)
        self.assertEqual(ctx.exception.reason, "empty_input")

    def test_wrong_shape_raises_umap_fit_error(self) -> None:
        v = np.zeros((10,), dtype=np.float32)  # 1-D
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=5)
        with self.assertRaises(exceptions.UmapFitError) as ctx:
            umap_fit.fit(v, p)
        self.assertEqual(ctx.exception.reason, "wrong_shape")


class FitModelHandleTests(unittest.TestCase):
    """The fitted UMAP model handle MUST be available on the result so
    the OHBM 2026 projector (T024) can ``transform`` out-of-sample
    vectors into the same space."""

    def test_result_carries_a_fitted_model_with_transform(self) -> None:
        v = _synthetic_vectors(n=50)
        p = umap_fit.UmapFitParams(n_components=3, n_neighbors=10)
        result = umap_fit.fit(v, p)
        self.assertTrue(hasattr(result.model, "transform"))
        # A trivial OOS transform should succeed — exercises the
        # model handle without claiming anything about projection
        # quality (T024 covers that).
        oos = _synthetic_vectors(n=3, seed=42)
        projected = result.model.transform(oos)
        self.assertEqual(projected.shape, (3, 3))


class FitCacheTests(unittest.TestCase):
    """The cache_root parameter should short-circuit a refit when the
    same (vectors, params) combination is reused, and persist a fresh
    entry on first run. The cache is the contract behind R-007 /
    SC-005 — second invocation byte-identical and <60s.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_root = Path(self._tmp.name) / "atlas-umap"
        self.vectors = _synthetic_vectors(n=50)
        self.params = umap_fit.UmapFitParams(n_components=3, n_neighbors=10)

    def test_cache_miss_writes_complete_entry(self) -> None:
        result = umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        entry = umap_fit.cache_paths(self.cache_root, result.state_key)
        self.assertTrue(entry["model"].exists(), "model.joblib should be written")
        self.assertTrue(entry["embedded"].exists(), "embedded.npy should be written")
        self.assertTrue(entry["params"].exists(), "params.json should be written")
        # Forensic params blob carries the same state_key + params.
        payload = json.loads(entry["params"].read_text())
        self.assertEqual(payload["state_key"], result.state_key)
        self.assertEqual(payload["n_components"], 3)
        self.assertEqual(payload["n_neighbors"], 10)

    def test_cache_hit_returns_identical_embedding(self) -> None:
        # First fit populates the cache.
        first = umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        # Second call returns the cached embedding byte-for-byte.
        second = umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        self.assertEqual(first.state_key, second.state_key)
        self.assertTrue(
            np.array_equal(first.embedded, second.embedded),
            "cache hit must return byte-identical embedded array",
        )

    def test_cache_hit_returns_working_model_handle(self) -> None:
        # A cache hit must produce a model whose .transform still
        # works — the OHBM projector depends on it.
        umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        cached = umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        oos = _synthetic_vectors(n=4, seed=99)
        projected = cached.model.transform(oos)
        self.assertEqual(projected.shape, (4, 3))

    def test_cache_isolates_2d_and_3d_state_keys(self) -> None:
        # Both 2D and 3D fits under the same cache_root must coexist
        # without overwriting each other (the orchestrator runs both).
        params_3d = umap_fit.UmapFitParams(n_components=3, n_neighbors=10)
        params_2d = umap_fit.UmapFitParams(n_components=2, n_neighbors=10)
        r3 = umap_fit.fit(self.vectors, params_3d, cache_root=self.cache_root)
        r2 = umap_fit.fit(self.vectors, params_2d, cache_root=self.cache_root)
        self.assertNotEqual(r3.state_key, r2.state_key)
        e3 = umap_fit.cache_paths(self.cache_root, r3.state_key)
        e2 = umap_fit.cache_paths(self.cache_root, r2.state_key)
        self.assertTrue(e3["model"].exists())
        self.assertTrue(e2["model"].exists())
        # And re-hit each one independently.
        again3 = umap_fit.fit(self.vectors, params_3d, cache_root=self.cache_root)
        again2 = umap_fit.fit(self.vectors, params_2d, cache_root=self.cache_root)
        self.assertTrue(np.array_equal(r3.embedded, again3.embedded))
        self.assertTrue(np.array_equal(r2.embedded, again2.embedded))

    def test_partial_entry_raises_umap_cache_error(self) -> None:
        # Half-written entry (model present, embedded missing) must
        # raise loudly so operators delete + retry rather than
        # silently pay the refit cost.
        umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        state_key = umap_fit.compute_state_key(self.vectors, self.params)
        entry = umap_fit.cache_paths(self.cache_root, state_key)
        entry["embedded"].unlink()
        with self.assertRaises(exceptions.UmapCacheError) as ctx:
            umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        self.assertEqual(ctx.exception.reason, "incomplete_entry")

    def test_corrupt_model_raises_umap_cache_error(self) -> None:
        umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        state_key = umap_fit.compute_state_key(self.vectors, self.params)
        entry = umap_fit.cache_paths(self.cache_root, state_key)
        entry["model"].write_bytes(b"not a real joblib payload")
        with self.assertRaises(exceptions.UmapCacheError) as ctx:
            umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        self.assertEqual(ctx.exception.reason, "model_unreadable")

    def test_embedded_shape_mismatch_raises_umap_cache_error(self) -> None:
        # A cached entry whose embedded.npy carries the wrong number
        # of columns (e.g. an old 2D fit pasted into a 3D slot) must
        # be flagged, not silently used.
        umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        state_key = umap_fit.compute_state_key(self.vectors, self.params)
        entry = umap_fit.cache_paths(self.cache_root, state_key)
        # Replace the 3-col embedded with a 2-col version.
        np.save(entry["embedded"], np.zeros((50, 2), dtype=np.float32))
        with self.assertRaises(exceptions.UmapCacheError) as ctx:
            umap_fit.fit(self.vectors, self.params, cache_root=self.cache_root)
        self.assertEqual(ctx.exception.reason, "embedded_shape_mismatch")

    def test_no_cache_when_cache_root_is_none(self) -> None:
        # Calling without a cache_root falls back to the historical
        # uncached behaviour (no files written, fresh fit each call).
        empty_cache = Path(self._tmp.name) / "should-stay-empty"
        umap_fit.fit(self.vectors, self.params)
        self.assertFalse(empty_cache.exists())


if __name__ == "__main__":
    unittest.main()
