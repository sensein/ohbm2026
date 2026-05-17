"""Tests for the `analyze-matrix` + `analyze-umap-project` subcommand
wiring in `ohbm2026.cli`."""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

import numpy as np

from ohbm2026 import cli


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


class AnalyzeMatrixCLITests(unittest.TestCase):
    def test_analyze_matrix_delegates_to_stage_main(self) -> None:
        from ohbm2026.analyze import stage as analyze_stage_mod

        with mock.patch.object(analyze_stage_mod, "main", return_value=0) as analyze_main:
            result = cli.main(["analyze-matrix", "--dry-run"])

        self.assertEqual(result, 0)
        analyze_main.assert_called_once_with(["--dry-run"])

    def test_analyze_matrix_passes_every_flag(self) -> None:
        """contracts/cli.md enumerates every flag; the subparser must
        accept all of them."""
        from ohbm2026.analyze import stage as analyze_stage_mod

        argv = [
            "analyze-matrix",
            "--env-file", ".env",
            "--embeddings-root", "data/outputs/embeddings",
            "--corpus-state-key", "abc123def456",
            "--models", "voyage", "minilm",
            "--inputs", "abstract", "claims",
            "--kinds", "projections", "communities",
            "--skip-llm-topics",
            "--scispacy",
            "--strict-matrix",
            "--seed", "7",
            "--cache-root", "data/cache/analysis",
            "--invalidate", "projections",
            "--output-root", "data/outputs/analysis",
            "--rollup-path", "data/outputs/analysis/annotations__abc.parquet",
            "--provenance-root", "data/provenance/analysis",
            "--neuroscape-centroids", "data/inputs/neuroscape",
            "--code-revision", "deadbeef",
            "--dry-run",
            "--log-level", "DEBUG",
            "--umap-n-neighbors", "30",
            "--umap-min-dist", "0.05",
            "--umap-metric", "euclidean",
            "--community-knn-k", "50",
            "--community-resolution-min", "0.0005",
            "--community-resolution-max", "0.2",
            "--community-resolution-points", "30",
            "--n-topics", "20",
            "--topic-llm-model-id", "gpt-5.4-mini",
            "--topic-prompt-version", "v2",
        ]
        with mock.patch.object(analyze_stage_mod, "main", return_value=0) as analyze_main:
            result = cli.main(argv)
        self.assertEqual(result, 0)
        analyze_main.assert_called_once_with(argv[1:])


class AnalyzeUmapProjectCLITests(unittest.TestCase):
    def test_round_trip_knn_weighted(self) -> None:
        """End-to-end CLI run: build a bundle, then project new vectors."""
        from ohbm2026.analyze.umap import (
            fit_umap_2d,
            fit_umap_3d,
            write_projections_bundle,
        )

        with _isolated_cwd():
            rng = np.random.default_rng(7)
            matrix = rng.normal(size=(60, 8)).astype(np.float32)
            coords2d, _ = fit_umap_2d(matrix, random_state=42)
            coords3d, _ = fit_umap_3d(matrix, random_state=42)
            bundle = Path("data/outputs/analysis/voyage_abstract/projections__test")
            write_projections_bundle(
                bundle,
                ids=np.arange(60, dtype=np.int64),
                reference_matrix=matrix,
                coords2d=coords2d,
                coords3d=coords3d,
            )
            new_vectors_path = Path("new_vectors.npy")
            np.save(new_vectors_path, rng.normal(size=(4, 8)).astype(np.float32))

            out_path = Path("out_coords.npy")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = cli.main([
                    "analyze-umap-project",
                    "--fitted-bundle", str(bundle),
                    "--input-vectors", str(new_vectors_path),
                    "--algorithm", "knn_weighted",
                    "--dim", "2",
                    "--output", str(out_path),
                ])
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            coords = np.load(out_path)
            self.assertEqual(coords.shape, (4, 2))
            event = json.loads(stdout.getvalue().strip().splitlines()[-1])
            self.assertEqual(event["event"], "project_into_umap_complete")

    def test_dim_mismatch_returns_2(self) -> None:
        from ohbm2026.analyze.umap import fit_umap_2d, fit_umap_3d, write_projections_bundle

        with _isolated_cwd():
            rng = np.random.default_rng(7)
            matrix = rng.normal(size=(40, 8)).astype(np.float32)
            coords2d, _ = fit_umap_2d(matrix, random_state=42)
            coords3d, _ = fit_umap_3d(matrix, random_state=42)
            bundle = Path("data/outputs/analysis/voyage_abstract/projections__test")
            write_projections_bundle(
                bundle,
                ids=np.arange(40, dtype=np.int64),
                reference_matrix=matrix,
                coords2d=coords2d,
                coords3d=coords3d,
            )
            np.save("nv.npy", rng.normal(size=(2, 4)).astype(np.float32))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = cli.main([
                    "analyze-umap-project",
                    "--fitted-bundle", str(bundle),
                    "--input-vectors", "nv.npy",
                    "--algorithm", "knn_weighted",
                    "--dim", "2",
                    "--output", "out.npy",
                ])
            self.assertEqual(rc, 2)
            event = json.loads(stdout.getvalue().strip().splitlines()[-1])
            self.assertEqual(event["type"], "ProjectionDimensionMismatch")


if __name__ == "__main__":
    unittest.main()
