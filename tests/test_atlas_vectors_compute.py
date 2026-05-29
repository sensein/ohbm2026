"""Tests for ``ohbm2026.atlas_package.vectors_compute`` (spec 019, T010 + T011).

Covers:
- Per-cluster cache hit/miss (R-009): first run populates cache; second
  run with identical inputs short-circuits to cache.
- INT8 round-trip recovery MAE < 0.005 (parquet-schemas.md §5).
- Deterministic state_key derivation.
- Input-length-mismatch guard (EmbeddingComputeError).
- Encoder-failure surfacing (no silent swallow).

Tests use a synthetic encoder so the production model download is not
required; the model_sha256 path is exercised via the
"synthetic-encoder-sha256-stub" fallback in vectors_compute.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

import numpy as np

from ohbm2026 import exceptions
from ohbm2026.atlas_package import vectors_compute


def _make_encoder(seed: int = 7) -> Callable[[list[str]], np.ndarray]:
    """Deterministic synthetic encoder returning unit-norm float32 vectors
    of the right shape. Hashes each title to seed the per-row vector so
    two runs with the same input produce byte-identical bytes."""

    def _encode(texts: list[str]) -> np.ndarray:
        vectors = np.empty((len(texts), vectors_compute.VECTOR_DIM), dtype=np.float32)
        for i, t in enumerate(texts):
            rng = np.random.default_rng(seed=hash((seed, t)) % (2**32))
            v = rng.standard_normal(vectors_compute.VECTOR_DIM).astype(np.float32)
            n = float(np.linalg.norm(v))
            vectors[i] = v / (n if n != 0.0 else 1.0)
        return vectors

    return _encode


class StateKeyTests(unittest.TestCase):
    def test_state_key_is_12_hex_chars(self) -> None:
        key = vectors_compute.compute_state_key(
            article_set_hash="abc12345def6",
            model_id=vectors_compute.DEFAULT_MODEL_ID,
        )
        self.assertEqual(len(key), 12)
        self.assertRegex(key, r"^[0-9a-f]{12}$")

    def test_state_key_changes_when_model_changes(self) -> None:
        h = "abc12345def6"
        a = vectors_compute.compute_state_key(article_set_hash=h, model_id="model-a")
        b = vectors_compute.compute_state_key(article_set_hash=h, model_id="model-b")
        self.assertNotEqual(a, b)

    def test_state_key_changes_when_articles_change(self) -> None:
        a = vectors_compute.compute_state_key(article_set_hash="aaa", model_id="m")
        b = vectors_compute.compute_state_key(article_set_hash="bbb", model_id="m")
        self.assertNotEqual(a, b)

    def test_state_key_changes_when_text_recipe_changes(self) -> None:
        # Switching the field composition (title → title+abstract) must
        # invalidate any cache built under the previous recipe.
        a = vectors_compute.compute_state_key(
            article_set_hash="aaa", model_id="m", text_recipe="title"
        )
        b = vectors_compute.compute_state_key(
            article_set_hash="aaa", model_id="m", text_recipe="title+abstract"
        )
        self.assertNotEqual(a, b)


class ComputeCachingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.titles = [f"article title {i}" for i in range(30)]
        self.pubmed_ids = list(range(1000, 1030))
        # Three clusters of 10 each.
        self.cluster_ids = [i // 10 for i in range(30)]
        self.state_key = "syntheticsk00"
        self.encoder = _make_encoder()

    def test_first_run_writes_per_cluster_cache_files(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            res = vectors_compute.compute_cluster_vectors(
                article_texts=self.titles,
                pubmed_ids=self.pubmed_ids,
                cluster_ids=self.cluster_ids,
                state_key=self.state_key,
                cache_root=cache_root,
                encoder=self.encoder,
            )
            state_dir = cache_root / self.state_key
            self.assertTrue((state_dir / "scale.json").exists())
            for cid in (0, 1, 2):
                self.assertTrue((state_dir / f"cluster_{cid}.npz").exists())
            self.assertEqual(res.cache_hits, 0)
            self.assertEqual(res.cache_misses, 3)
            self.assertEqual(len(res.clusters), 3)
            self.assertGreater(res.max_abs_original, 0.0)

    def test_second_run_with_identical_inputs_is_full_cache_hit(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            _ = vectors_compute.compute_cluster_vectors(
                article_texts=self.titles,
                pubmed_ids=self.pubmed_ids,
                cluster_ids=self.cluster_ids,
                state_key=self.state_key,
                cache_root=cache_root,
                encoder=self.encoder,
            )
            res2 = vectors_compute.compute_cluster_vectors(
                article_texts=self.titles,
                pubmed_ids=self.pubmed_ids,
                cluster_ids=self.cluster_ids,
                state_key=self.state_key,
                cache_root=cache_root,
                # Pass a None-returning encoder so the test verifies the
                # cache short-circuits BEFORE the encoder is called.
                encoder=lambda _texts: (_ for _ in ()).throw(
                    AssertionError("encoder must not be called on full cache hit")
                ),
            )
            self.assertEqual(res2.cache_hits, 3)
            self.assertEqual(res2.cache_misses, 0)

    def test_corrupt_cache_entry_triggers_recompute(self) -> None:
        with TemporaryDirectory() as tmp:
            cache_root = Path(tmp)
            _ = vectors_compute.compute_cluster_vectors(
                article_texts=self.titles,
                pubmed_ids=self.pubmed_ids,
                cluster_ids=self.cluster_ids,
                state_key=self.state_key,
                cache_root=cache_root,
                encoder=self.encoder,
            )
            # Corrupt one cluster file.
            (cache_root / self.state_key / "cluster_1.npz").write_bytes(b"not an npz")
            res = vectors_compute.compute_cluster_vectors(
                article_texts=self.titles,
                pubmed_ids=self.pubmed_ids,
                cluster_ids=self.cluster_ids,
                state_key=self.state_key,
                cache_root=cache_root,
                encoder=self.encoder,
            )
            # The corrupt cluster MUST recompute (the implementation
            # currently triggers a full-corpus recompute when ANY
            # cluster is missing/corrupt — see vectors_compute docstring).
            self.assertGreaterEqual(res.cache_misses, 1)


class Int8RoundtripTests(unittest.TestCase):
    def test_int8_recovery_mae_below_threshold(self) -> None:
        """SC-006-adjacent quality gate: dequantised INT8 vectors recover
        the original FP32 unit-norm vectors with MAE < 0.005 — the same
        bound the OHBM 2026 site asserts (`vectors.py:cosine_recovery_mae`)."""
        titles = [f"title {i}" for i in range(50)]
        encoder = _make_encoder()
        with TemporaryDirectory() as tmp:
            res = vectors_compute.compute_cluster_vectors(
                article_texts=titles,
                pubmed_ids=list(range(50)),
                cluster_ids=[0] * 50,
                state_key="rtroundtrip",
                cache_root=Path(tmp),
                encoder=encoder,
            )
            # Reconstruct the dequantised vectors and compare to the
            # original unit-norm encoder output.
            original = encoder(titles)
            # L2-renormalise to match the production path
            norms = np.linalg.norm(original, axis=1, keepdims=True)
            norms = np.where(norms == 0.0, 1.0, norms)
            original = (original / norms).astype(np.float32)
            recovered = res.clusters[0].vectors_int8.astype(np.float32) / res.scale
            mae = float(np.mean(np.abs(recovered - original)))
            self.assertLess(mae, 0.005)


class InputGuardTests(unittest.TestCase):
    def test_length_mismatch_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(exceptions.EmbeddingComputeError) as ctx:
                vectors_compute.compute_cluster_vectors(
                    article_texts=["a", "b", "c"],
                    pubmed_ids=[1, 2],  # one short
                    cluster_ids=[0, 0, 0],
                    state_key="badlen",
                    cache_root=Path(tmp),
                    encoder=_make_encoder(),
                )
            self.assertEqual(ctx.exception.reason, "input_length_mismatch")

    def test_encoder_output_wrong_shape_raises(self) -> None:
        def bad_encoder(_titles: list[str]) -> np.ndarray:
            return np.zeros((1, 100), dtype=np.float32)  # wrong dim, wrong count

        with TemporaryDirectory() as tmp:
            with self.assertRaises(exceptions.EmbeddingComputeError) as ctx:
                vectors_compute.compute_cluster_vectors(
                    article_texts=["a", "b"],
                    pubmed_ids=[1, 2],
                    cluster_ids=[0, 0],
                    state_key="badenc",
                    cache_root=Path(tmp),
                    encoder=bad_encoder,
                )
            self.assertEqual(ctx.exception.reason, "encoder_output_shape")

    def test_encoder_output_nonfinite_raises(self) -> None:
        def nan_encoder(titles: list[str]) -> np.ndarray:
            v = np.zeros((len(titles), vectors_compute.VECTOR_DIM), dtype=np.float32)
            v[0, 0] = np.nan
            return v

        with TemporaryDirectory() as tmp:
            with self.assertRaises(exceptions.EmbeddingComputeError) as ctx:
                vectors_compute.compute_cluster_vectors(
                    article_texts=["a", "b"],
                    pubmed_ids=[1, 2],
                    cluster_ids=[0, 0],
                    state_key="nanenc",
                    cache_root=Path(tmp),
                    encoder=nan_encoder,
                )
            self.assertEqual(ctx.exception.reason, "encoder_output_nonfinite")


if __name__ == "__main__":
    unittest.main()
