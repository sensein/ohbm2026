"""Tests for `src/ohbm2026/embed_storage.py`.

Covers atomic-write round-trips for both bundle and cache entries,
the contract-error path for shape mismatches, and a smoke test for
atomic-write resilience under simulated mid-write failures.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohbm2026.embed import storage as embed_storage
from ohbm2026.exceptions import EmbeddingContractError


class _Tmp:
    def __init__(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)

    def cleanup(self) -> None:
        self.dir.cleanup()


class BundleRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)

    def test_write_and_load_roundtrip(self) -> None:
        bundle_dir = self.fx.path / "voyage_methods"
        ids = [10, 20, 30]
        vectors = np.array(
            [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]], dtype=np.float32
        )
        metadata = {
            "bundle_name": "voyage_methods",
            "model_key": "voyage",
            "model_id": "voyage-large-2-instruct",
            "model_version": "voyage-large-2-instruct@sdk-1",
            "component": "methods",
            "corpus_state_key": "abcdef012345",
            "corpus_source_path": "data/primary/abstracts_enriched.sqlite",
            "count": 3,
            "missing_count": 0,
            "missing_ids": [],
            "long_input_strategy": "truncate_end",
            "long_input_params": None,
            "truncated_count": 0,
            "failure_count": 0,
            "batch_size": 64,
            "embedded_at": "2026-05-14T00:00:00Z",
        }
        embed_storage.write_bundle(
            bundle_dir, ids=ids, vectors=vectors, metadata=metadata
        )

        # Bundle dir + files exist.
        for name in ("vectors.npy", "ids.npy", "metadata.json"):
            self.assertTrue((bundle_dir / name).exists(), name)

        loaded = embed_storage.load_bundle(bundle_dir)
        self.assertEqual(loaded["ids"].tolist(), ids)
        np.testing.assert_array_equal(loaded["vectors"], vectors)
        self.assertEqual(loaded["metadata"]["component"], "methods")
        self.assertEqual(loaded["metadata"]["present_count"], 3)
        self.assertEqual(loaded["metadata"]["dim"], 3)
        self.assertEqual(loaded["metadata"]["dtype"], "float32")
        self.assertEqual(loaded["metadata"]["ids"], ids)

    def test_row_count_mismatch_raises(self) -> None:
        bundle_dir = self.fx.path / "v"
        with self.assertRaises(EmbeddingContractError):
            embed_storage.write_bundle(
                bundle_dir,
                ids=[1, 2, 3],
                vectors=np.zeros((2, 4), dtype=np.float32),
                metadata={"corpus_state_key": "x"},
            )

    def test_metadata_ids_drift_raises(self) -> None:
        bundle_dir = self.fx.path / "v"
        with self.assertRaises(EmbeddingContractError):
            embed_storage.write_bundle(
                bundle_dir,
                ids=[1, 2, 3],
                vectors=np.zeros((3, 4), dtype=np.float32),
                metadata={"corpus_state_key": "x", "ids": [99, 88, 77]},
            )

    def test_rewrite_moves_prior_aside(self) -> None:
        bundle_dir = self.fx.path / "v"
        vectors = np.zeros((1, 2), dtype=np.float32)
        embed_storage.write_bundle(
            bundle_dir, ids=[1], vectors=vectors,
            metadata={"corpus_state_key": "old"},
        )
        embed_storage.write_bundle(
            bundle_dir, ids=[2], vectors=vectors,
            metadata={"corpus_state_key": "new"},
        )
        self.assertEqual(
            embed_storage.bundle_corpus_state_key(bundle_dir), "new",
        )
        self.assertEqual(
            embed_storage.bundle_corpus_state_key(self.fx.path / "v.prev"),
            "old",
        )

    def test_provenance_written_when_provided(self) -> None:
        bundle_dir = self.fx.path / "v"
        embed_storage.write_bundle(
            bundle_dir,
            ids=[1],
            vectors=np.zeros((1, 2), dtype=np.float32),
            metadata={"corpus_state_key": "k"},
            provenance={"command_line": "embed-matrix --models voyage"},
        )
        self.assertEqual(
            json.loads((bundle_dir / "provenance.json").read_text())["command_line"],
            "embed-matrix --models voyage",
        )


class CacheRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)

    def test_cache_miss_returns_none(self) -> None:
        self.assertIsNone(
            embed_storage.load_cache_entry(self.fx.path, "voyage", "nonexistent")
        )

    def test_cache_write_and_load(self) -> None:
        payload = {
            "cache_version": embed_storage.CACHE_VERSION,
            "abstract_id": 42,
            "component": "title",
            "model_id": "voyage-large-2-instruct",
            "model_version": "v1",
            "input_hash": "0" * 64,
            "vector": [0.1, 0.2, 0.3],
            "dim": 3,
            "embedded_at": "2026-05-14T00:00:00Z",
        }
        path = embed_storage.write_cache_entry(
            self.fx.path, model_key="voyage", cache_key="abc123", payload=payload,
        )
        self.assertTrue(path.exists())
        self.assertEqual(path.name, "abc123.json")
        loaded = embed_storage.load_cache_entry(self.fx.path, "voyage", "abc123")
        self.assertEqual(loaded["abstract_id"], 42)
        self.assertEqual(loaded["vector"], [0.1, 0.2, 0.3])

    def test_corrupted_cache_entry_raises(self) -> None:
        # Write garbage to a cache file.
        path = embed_storage.cache_path_for(self.fx.path, "voyage", "broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(EmbeddingContractError):
            embed_storage.load_cache_entry(self.fx.path, "voyage", "broken")


class AtomicWriteResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)

    def test_signal_during_write_no_partial(self) -> None:
        """If `atomic_write_bytes` is interrupted by an exception
        before os.replace, no destination file MUST be visible."""
        target = self.fx.path / "sub" / "out.json"

        def boom(*args, **kwargs):
            raise KeyboardInterrupt("simulated SIGTERM")

        # Patch os.replace to raise after the temp write completes.
        real_replace = os.replace
        try:
            os.replace = boom  # type: ignore[assignment]
            with self.assertRaises(KeyboardInterrupt):
                embed_storage.atomic_write_bytes(target, b"hello")
        finally:
            os.replace = real_replace
        # The destination must not exist.
        self.assertFalse(target.exists())
        # The temp file must have been cleaned up.
        leftovers = [p for p in target.parent.iterdir() if p.name.startswith("out.json.")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
