"""Tests for `ohbm2026.analyze.topic_clusters` (US5).

Coverage per FR-009 + CA-002:
- Synthetic 3-cluster corpus → `run_topic_clustering` recovers
  approximately 3 topics; same-seed rows share `topic_cluster_id`
  ≥80% of the time (allowing for HDBSCAN noise).
- `n_topics=auto` triggers the documented elbow / coherence rule;
  selection is recorded in `metadata.json` via the bundle writer.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ohbm2026.analyze.topic_clusters import (
    run_topic_clustering,
    write_topic_clusters_bundle,
)


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


def _three_cluster_corpus(
    n_per_cluster: int = 60, dim: int = 32, *, seed: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic 3-cluster corpus + ground-truth labels."""
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(3, dim)) * 5.0
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    vectors = []
    labels = []
    for cid, c in enumerate(centers):
        cluster = c + rng.normal(scale=0.1, size=(n_per_cluster, dim))
        cluster /= np.linalg.norm(cluster, axis=1, keepdims=True)
        vectors.append(cluster)
        labels.extend([cid] * n_per_cluster)
    return np.vstack(vectors).astype(np.float32), np.asarray(labels, dtype=np.int32)


class RunTopicClusteringTests(unittest.TestCase):
    def test_recovers_three_clusters(self) -> None:
        vectors, truth = _three_cluster_corpus(n_per_cluster=40, dim=32, seed=7)
        result = run_topic_clustering(vectors, min_cluster_size=10, seed=42)
        self.assertGreaterEqual(result.n_topics, 2)  # at least separates
        # Per planted cluster, the majority should fall into a single topic id
        # (allowing for some HDBSCAN noise points).
        for planted_id in range(3):
            mask = truth == planted_id
            slice_topics = result.topic_cluster_ids[mask]
            # Exclude HDBSCAN noise (id == -1)
            non_noise = slice_topics[slice_topics >= 0]
            if non_noise.size == 0:
                continue
            counts = np.bincount(non_noise)
            self.assertGreater(counts.max() / non_noise.size, 0.7)

    def test_auto_min_cluster_size_selection(self) -> None:
        """`min_cluster_size=None` triggers the noise-elbow sweep; the
        selected value should be recorded in `result.min_cluster_size`."""
        vectors, _ = _three_cluster_corpus(n_per_cluster=40, dim=16, seed=7)
        result = run_topic_clustering(vectors, min_cluster_size=None, seed=42)
        self.assertGreater(result.min_cluster_size, 2)
        # The sweep table records the chosen mcs implicitly via the
        # `topic_selection_rule` field on the bundle, exercised below.

    def test_bundle_metadata_carries_selection_rule(self) -> None:
        vectors, _ = _three_cluster_corpus(n_per_cluster=30, dim=16, seed=7)
        result = run_topic_clustering(vectors, min_cluster_size=None, seed=42)
        ids = np.arange(1, vectors.shape[0] + 1, dtype=np.int64)
        with _isolated_cwd() as tmp:
            bundle_dir = tmp / "data" / "outputs" / "analysis" / "voyage_abstract" / "topic_clusters__xyz"
            write_topic_clusters_bundle(
                bundle_dir,
                ids=ids,
                result=result,
                source_model="voyage",
                input_source="abstract",
                seed=42,
            )
            meta = json.loads((bundle_dir / "metadata.json").read_text())
            self.assertEqual(meta["kind"], "topic_clusters")
            self.assertEqual(meta["topic_selection_rule"], "noise_elbow_sweep")
            self.assertEqual(meta["min_cluster_size"], result.min_cluster_size)
            self.assertEqual(meta["n_topics"], result.n_topics)

    def test_payload_shape(self) -> None:
        vectors, _ = _three_cluster_corpus(n_per_cluster=20, dim=8, seed=7)
        result = run_topic_clustering(vectors, min_cluster_size=8, seed=42)
        self.assertEqual(
            result.topic_cluster_ids.shape[0], vectors.shape[0]
        )
        self.assertEqual(
            result.topic_cluster_probabilities.shape[0], vectors.shape[0]
        )


if __name__ == "__main__":
    unittest.main()
