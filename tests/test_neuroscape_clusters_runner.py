"""End-to-end tests for the `neuroscape_clusters` runner.

Verifies that the orchestrator + runner produce a bundle, that the
auto-skip path emits a `bundle_skipped` event for dim-incompatible
models, and that direct-runner invocation against an incompatible
model raises `AnalysisError`.
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from dataclasses import replace
from pathlib import Path

import numpy as np

# Ensure runners register on import.
import ohbm2026.analyze  # noqa: F401
from ohbm2026.analyze.centroids import STAGE2_DIM
from ohbm2026.analyze.runners import neuroscape_clusters_runner
from ohbm2026.analyze.stage import (
    AnalysisConfig,
    KIND_RUNNERS,
    PlanEntry,
    run_matrix,
)
from ohbm2026.exceptions import AnalysisError


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


def _seed_neuroscape_stage3_bundle(state_key: str, n_rows: int) -> None:
    """Write a Stage 3 'neuroscape' embedding bundle (64-dim, unit-norm)."""
    bundle = Path(f"data/outputs/embeddings/neuroscape/claims__{state_key}")
    bundle.mkdir(parents=True)
    rng = np.random.default_rng(7)
    vectors = rng.normal(size=(n_rows, STAGE2_DIM)).astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / norms
    np.save(bundle / "ids.npy", np.arange(1, n_rows + 1, dtype=np.int64))
    np.save(bundle / "vectors.npy", vectors)
    (bundle / "metadata.json").write_text(
        json.dumps({"model": "neuroscape", "component": "claims", "n_rows": n_rows})
    )


def _seed_minilm_stage3_bundle(state_key: str, n_rows: int) -> None:
    bundle = Path(f"data/outputs/embeddings/minilm/title__{state_key}")
    bundle.mkdir(parents=True)
    rng = np.random.default_rng(11)
    np.save(bundle / "ids.npy", np.arange(1, n_rows + 1, dtype=np.int64))
    np.save(bundle / "vectors.npy", rng.normal(size=(n_rows, 384)).astype(np.float32))
    (bundle / "metadata.json").write_text(
        json.dumps({"model": "minilm", "component": "title", "n_rows": n_rows})
    )


def _write_centroid_table(n_centroids: int = 4) -> Path:
    """Write a synthetic centroid file under data/inputs/neuroscape/."""
    nsc_dir = Path("data/inputs/neuroscape")
    nsc_dir.mkdir(parents=True)
    rng = np.random.default_rng(5)
    raw = rng.normal(size=(n_centroids, STAGE2_DIM)).astype(np.float32)
    raw = raw / np.linalg.norm(raw, axis=1, keepdims=True)
    np.save(nsc_dir / "centroids__test-v1.npy", raw)
    with (nsc_dir / "cluster_table.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Cluster ID", "Title", "Description", "Keywords", "Focus", "centroid_table_version"])
        for cid in range(1, n_centroids + 1):
            writer.writerow([cid, f"T{cid}", f"D{cid}", json.dumps([f"kw{cid}"]), "themes", "test-v1"])
    return nsc_dir


def _baseline_config() -> AnalysisConfig:
    return AnalysisConfig(
        embeddings_root=Path("data/outputs/embeddings"),
        output_root=Path("data/outputs/analysis"),
        cache_root=Path("data/cache/analysis"),
        provenance_root=Path("data/provenance/analysis"),
        corpus_state_key="abc123def456",
        models=("neuroscape",),
        inputs=("claims",),
        kinds=("neuroscape_clusters",),
        rollup_path=Path("data/outputs/analysis/annotations__abc123def456.parquet"),
        sqlite_path=Path("data/outputs/analysis/annotations__abc123def456.sqlite"),
        neuroscape_centroids_dir=Path("data/inputs/neuroscape"),
    )


class NeuroscapeClustersRunnerTests(unittest.TestCase):
    def test_runner_registered(self) -> None:
        self.assertIn("neuroscape_clusters", KIND_RUNNERS)

    def test_end_to_end_neuroscape_source(self) -> None:
        """Source model 'neuroscape' skips Stage-2 projection (identity)."""
        with _isolated_cwd():
            _seed_neuroscape_stage3_bundle("abc123def456", n_rows=5)
            _write_centroid_table(n_centroids=4)
            config = _baseline_config()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = run_matrix(config)

            self.assertEqual(rc, 0)
            bundle_dir = Path(
                "data/outputs/analysis/neuroscape_claims"
            )
            children = list(bundle_dir.iterdir())
            self.assertEqual(len(children), 1)
            written = children[0]
            self.assertTrue(written.name.startswith("neuroscape_clusters__"))
            meta = json.loads((written / "metadata.json").read_text())
            self.assertEqual(meta["source_model"], "neuroscape")
            self.assertNotIn("stage2_applied", meta)  # field removed in Phase 5 tightening
            self.assertEqual(meta["centroid_table_version"], "test-v1")
            self.assertEqual(meta["n_rows"], 5)
            # Cluster ids must be in the table's vocabulary
            cluster_ids = np.load(written / "neuroscape_cluster_ids.npy")
            self.assertEqual(cluster_ids.shape, (5,))
            self.assertTrue((cluster_ids >= 1).all() and (cluster_ids <= 4).all())

    def test_non_neuroscape_source_auto_skipped(self) -> None:
        """Any model != 'neuroscape' → orchestrator emits bundle_skipped."""
        with _isolated_cwd():
            _seed_minilm_stage3_bundle("abc123def456", n_rows=5)
            _write_centroid_table()
            config = replace(
                _baseline_config(),
                models=("minilm",),
                inputs=("title",),  # use minilm's title bundle as the sentinel
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = run_matrix(config)
            self.assertEqual(rc, 0)
            events = [
                json.loads(line)
                for line in stdout.getvalue().strip().splitlines()
                if line.startswith("{")
            ]
            skips = [e for e in events if e.get("event") == "bundle_skipped"]
            self.assertTrue(
                any(e.get("reason") == "non_neuroscape_source" for e in skips),
                f"expected non_neuroscape_source skip; got {skips}",
            )

    def test_direct_runner_call_with_incompatible_model_raises(self) -> None:
        """Bypassing build_plan and calling the runner directly against an
        incompatible model raises AnalysisError (defense in depth)."""
        with _isolated_cwd():
            _write_centroid_table()
            entry = PlanEntry(
                model_key="minilm",
                input_source="title",
                kind="neuroscape_clusters",
                bundle_path=Path("does/not/matter"),
            )
            config = _baseline_config()
            with self.assertRaises(AnalysisError):
                neuroscape_clusters_runner(config, entry)

    def test_checkpoint_sha_mismatch_raises(self) -> None:
        """Centroid metadata and Stage 3 neuroscape provenance must agree
        on the domain-model checkpoint SHA (FR-008 step (c))."""
        from ohbm2026.exceptions import CentroidTableVersionMismatch

        with _isolated_cwd():
            _seed_neuroscape_stage3_bundle("abc123def456", n_rows=3)
            nsc_dir = _write_centroid_table()
            # Write a centroid_metadata.json with a known SHA.
            (nsc_dir / "centroid_metadata.json").write_text(
                json.dumps({
                    "centroid_table_version": "test-v1",
                    "domain_model_checkpoint_sha256": "centroid-sha-AAA",
                    "n_centroids": 4,
                }),
                encoding="utf-8",
            )
            # Write a Stage 3 neuroscape bundle provenance with a DIFFERENT SHA.
            stage3_bundle = Path("data/outputs/embeddings/neuroscape/claims__abc123def456")
            (stage3_bundle / "provenance.json").write_text(
                json.dumps({"domain_model_checkpoint_sha256": "stage3-sha-BBB"}),
                encoding="utf-8",
            )

            config = _baseline_config()
            entry = PlanEntry(
                model_key="neuroscape",
                input_source="claims",
                kind="neuroscape_clusters",
                bundle_path=stage3_bundle,
            )
            with self.assertRaises(CentroidTableVersionMismatch):
                neuroscape_clusters_runner(config, entry)


if __name__ == "__main__":
    unittest.main()
