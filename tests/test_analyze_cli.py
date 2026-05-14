"""Tests for the `analyze-matrix` subcommand wiring in `ohbm2026.cli`."""

from __future__ import annotations

import unittest
from unittest import mock

from ohbm2026 import cli


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


if __name__ == "__main__":
    unittest.main()
