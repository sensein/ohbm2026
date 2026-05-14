"""Tests for `ohbm2026.analyze.storage.write_analysis_bundle`.

Per spec FR-010 + contracts/bundle.md, every Stage 4 bundle ships an
atomic-rename write of `ids.npy` + payload `*.npy` + `metadata.json` +
`provenance.json` (+ optional `topics.json`). Concurrent readers must
never observe a partially-written bundle.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohbm2026.analyze.storage import write_analysis_bundle, iter_analysis_bundles


class WriteAnalysisBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_atomic_write_creates_canonical_files(self) -> None:
        bundle_dir = self.tmp / "voyage_abstract" / "communities__abc123def456"
        ids = np.asarray([10, 20, 30], dtype=np.int64)
        payload = {"community_ids": np.asarray([0, 0, 1], dtype=np.int32)}
        metadata = {"kind": "communities", "n_rows": 3}
        provenance = {
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "kind": "communities",
            "bundle_path": "data/outputs/analysis/voyage_abstract/communities__abc123def456/",
            "corpus_state_key": "f0c51e80dc0e",
            "input_source_assembly_hash": "abc",
            "algorithm_config_canonical_json": "{}",
            "cache_key": "sha256:deadbeef",
            "code_revision": "0" * 40,
            "command": "ohbmcli analyze-matrix",
            "seed": 42,
            "started_at": "2026-05-14T00:00:00Z",
            "completed_at": "2026-05-14T00:00:01Z",
        }

        result = write_analysis_bundle(
            bundle_dir,
            ids=ids,
            payload=payload,
            metadata=metadata,
            provenance=provenance,
        )

        self.assertEqual(result, bundle_dir)
        self.assertTrue((bundle_dir / "ids.npy").exists())
        self.assertTrue((bundle_dir / "community_ids.npy").exists())
        self.assertTrue((bundle_dir / "metadata.json").exists())
        self.assertTrue((bundle_dir / "provenance.json").exists())
        self.assertFalse((bundle_dir / "topics.json").exists())  # not requested

        np.testing.assert_array_equal(np.load(bundle_dir / "ids.npy"), ids)
        np.testing.assert_array_equal(
            np.load(bundle_dir / "community_ids.npy"), payload["community_ids"]
        )
        self.assertEqual(
            json.loads((bundle_dir / "metadata.json").read_text()),
            metadata,
        )

    def test_topics_written_only_when_supplied(self) -> None:
        bundle_dir = self.tmp / "voyage_abstract" / "topic_clusters__xyz"
        write_analysis_bundle(
            bundle_dir,
            ids=np.asarray([1, 2], dtype=np.int64),
            payload={"topic_cluster_ids": np.asarray([0, 1], dtype=np.int32)},
            metadata={},
            provenance={
                "schema_version": "stage4.provenance.v1",
                "stage": "analysis",
                "kind": "topic_clusters",
                "bundle_path": "data/outputs/analysis/voyage_abstract/topic_clusters__xyz/",
                "corpus_state_key": "x",
                "input_source_assembly_hash": "x",
                "algorithm_config_canonical_json": "{}",
                "cache_key": "sha256:x",
                "code_revision": "x",
                "command": "x",
                "seed": 0,
                "started_at": "x",
                "completed_at": "x",
            },
            topics={0: {"Keywords": ["a"], "Title": "T", "Description": "D", "Focus": "themes"}},
        )
        self.assertTrue((bundle_dir / "topics.json").exists())
        data = json.loads((bundle_dir / "topics.json").read_text())
        self.assertEqual(set(data.keys()), {"0"})
        self.assertEqual(data["0"]["Keywords"], ["a"])

    def test_payload_row_count_mismatch_raises(self) -> None:
        bundle_dir = self.tmp / "x" / "y__z"
        with self.assertRaises(ValueError):
            write_analysis_bundle(
                bundle_dir,
                ids=np.asarray([1, 2, 3], dtype=np.int64),
                payload={"bad": np.asarray([0, 1], dtype=np.int32)},  # 2 rows vs 3 ids
                metadata={},
                provenance={
                    "schema_version": "stage4.provenance.v1",
                    "stage": "analysis",
                    "kind": "communities",
                    "bundle_path": "data/outputs/analysis/x/y__z/",
                    "corpus_state_key": "x",
                    "input_source_assembly_hash": "x",
                    "algorithm_config_canonical_json": "{}",
                    "cache_key": "x",
                    "code_revision": "x",
                    "command": "x",
                    "seed": 0,
                    "started_at": "x",
                    "completed_at": "x",
                },
            )

    def test_overwrite_existing_bundle(self) -> None:
        bundle_dir = self.tmp / "x" / "y__z"
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "stale.txt").write_text("old")

        write_analysis_bundle(
            bundle_dir,
            ids=np.asarray([1], dtype=np.int64),
            payload={"v": np.asarray([0.5], dtype=np.float32)},
            metadata={},
            provenance={
                "schema_version": "stage4.provenance.v1",
                "stage": "analysis",
                "kind": "communities",
                "bundle_path": "data/outputs/analysis/x/y__z/",
                "corpus_state_key": "x",
                "input_source_assembly_hash": "x",
                "algorithm_config_canonical_json": "{}",
                "cache_key": "x",
                "code_revision": "x",
                "command": "x",
                "seed": 0,
                "started_at": "x",
                "completed_at": "x",
            },
        )

        # Stale file MUST be gone after replacement.
        self.assertFalse((bundle_dir / "stale.txt").exists())
        self.assertTrue((bundle_dir / "ids.npy").exists())


class IterAnalysisBundlesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_walks_two_level_layout(self) -> None:
        (self.tmp / "voyage_abstract" / "communities__abc").mkdir(parents=True)
        (self.tmp / "voyage_abstract" / "projections__abc").mkdir(parents=True)
        (self.tmp / "voyage_claims" / "communities__def").mkdir(parents=True)
        results = sorted(p.name for p in iter_analysis_bundles(self.tmp))
        self.assertEqual(results, ["communities__abc", "communities__def", "projections__abc"])

    def test_filters_by_kind(self) -> None:
        (self.tmp / "voyage_abstract" / "communities__abc").mkdir(parents=True)
        (self.tmp / "voyage_abstract" / "projections__abc").mkdir(parents=True)
        results = sorted(
            p.name for p in iter_analysis_bundles(self.tmp, kinds=["communities"])
        )
        self.assertEqual(results, ["communities__abc"])

    def test_skips_prev_and_dotfiles(self) -> None:
        (self.tmp / "voyage_abstract" / "communities__abc").mkdir(parents=True)
        (self.tmp / "voyage_abstract" / "communities__abc.prev").mkdir(parents=True)
        (self.tmp / "voyage_abstract" / ".tmp_xyz").mkdir(parents=True)
        results = sorted(p.name for p in iter_analysis_bundles(self.tmp))
        self.assertEqual(results, ["communities__abc"])


if __name__ == "__main__":
    unittest.main()
