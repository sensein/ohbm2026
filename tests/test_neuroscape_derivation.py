"""Tests for the Stage 3 NeuroScape derivation path (T038–T039).

Verifies that `embed_compose.apply_published_stage2_to_matrix` and
the matrix-orchestrator hook `embed_stage._run_neuroscape_derivation`
both fail loudly when the model checkpoint is missing or wrong shape,
and that the transform is deterministic given a fake apply function.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohbm2026 import exceptions
from ohbm2026.embed import compose as embed_compose
from ohbm2026.embed import stage as embed_stage
from ohbm2026.embed import storage as embed_storage


class _Tmp:
    def __init__(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)

    def cleanup(self) -> None:
        self.dir.cleanup()


class ApplyPublishedStage2Tests(unittest.TestCase):
    def test_missing_model_path_raises_typed_error(self) -> None:
        fake_matrix = np.zeros((3, 1024), dtype=np.float32)
        with self.assertRaises(exceptions.EmbeddingError) as ctx:
            embed_compose.apply_published_stage2_to_matrix(
                fake_matrix,
                model_path=Path("/nonexistent/neuroscape_stage2.pth"),
            )
        self.assertIn("not found", str(ctx.exception))

    def test_wrong_input_dim_raises_typed_error(self) -> None:
        with self.assertRaises(exceptions.EmbeddingError) as ctx:
            embed_compose.apply_published_stage2_to_matrix(
                np.zeros((3, 512), dtype=np.float32),  # not 1024
                model_path=Path("/anywhere.pth"),
            )
        self.assertIn("1024-dim", str(ctx.exception))


class RunNeuroscapeDerivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)
        self.state_key = "deadbeef0001"

        # Pre-write a small Voyage bundle so the derivation can read it.
        self.voyage_dir = self.fx.path / "embeddings" / "voyage" / f"title__{self.state_key}"
        voyage_matrix = np.arange(2 * 1024, dtype=np.float32).reshape(2, 1024)
        embed_storage.write_bundle(
            self.voyage_dir,
            ids=[10, 20],
            vectors=voyage_matrix,
            metadata={
                "bundle_name": f"title__{self.state_key}",
                "model_key": "voyage",
                "component": "title",
                "corpus_state_key": self.state_key,
            },
        )

    def test_missing_upstream_voyage_bundle_raises(self) -> None:
        with self.assertRaises(exceptions.EmbeddingError) as ctx:
            embed_stage._run_neuroscape_derivation(
                component="title",
                voyage_bundle_dir=self.fx.path / "embeddings" / "voyage" / "does-not-exist",
                embeddings_root=self.fx.path / "embeddings",
                corpus_state_key=self.state_key,
            )
        self.assertIn("required upstream", str(ctx.exception))

    def test_neuroscape_application_is_deterministic(self) -> None:
        """With a deterministic fake apply_fn, two calls produce the
        same bundle bytes (modulo embedded_at)."""
        fake_projected = np.arange(2 * 64, dtype=np.float32).reshape(2, 64)
        fake_model_version = "neuroscape-stage2-published@deterministic"

        def fake_apply(_matrix: np.ndarray, **_kwargs) -> tuple[np.ndarray, str]:
            # `_kwargs` may include `model_path` when the orchestrator
            # plumbs `args.neuroscape_model_path` through. The test
            # leaves it None so the orchestrator passes no kwargs.
            return fake_projected.copy(), fake_model_version

        out_dir = self.fx.path / "embeddings" / "neuroscape" / f"title__{self.state_key}"
        with mock.patch.object(embed_compose, "apply_published_stage2_to_matrix", side_effect=fake_apply):
            r1 = embed_stage._run_neuroscape_derivation(
                component="title",
                voyage_bundle_dir=self.voyage_dir,
                embeddings_root=self.fx.path / "embeddings",
                corpus_state_key=self.state_key,
            )
        # Read the bundle to verify shape + metadata captured the model_version.
        bundle = embed_storage.load_bundle(out_dir)
        np.testing.assert_array_equal(bundle["vectors"], fake_projected)
        np.testing.assert_array_equal(bundle["ids"], [10, 20])
        self.assertEqual(bundle["metadata"]["model_version"], fake_model_version)
        self.assertEqual(bundle["metadata"]["component"], "title")
        self.assertEqual(bundle["metadata"]["upstream_voyage_bundle"].split("/")[-1], f"title__{self.state_key}")

        # Re-run; output must match byte-for-byte except embedded_at.
        first_vectors = bundle["vectors"].copy()
        # Move first bundle out of the way so write_bundle creates a fresh dir.
        import shutil
        shutil.rmtree(out_dir)
        with mock.patch.object(embed_compose, "apply_published_stage2_to_matrix", side_effect=fake_apply):
            r2 = embed_stage._run_neuroscape_derivation(
                component="title",
                voyage_bundle_dir=self.voyage_dir,
                embeddings_root=self.fx.path / "embeddings",
                corpus_state_key=self.state_key,
            )
        bundle2 = embed_storage.load_bundle(out_dir)
        np.testing.assert_array_equal(bundle2["vectors"], first_vectors)
        np.testing.assert_array_equal(bundle2["ids"], [10, 20])
        self.assertEqual(bundle2["metadata"]["model_version"], fake_model_version)


if __name__ == "__main__":
    unittest.main()
