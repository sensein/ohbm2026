"""Tests for `ohbm2026.analyze.provenance`.

Per CA-008 + Principle VIII, provenance MUST reject absolute / `~` /
parent-escape paths so bundle records stay portable.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ohbm2026.analyze.provenance import (
    assert_path_safe,
    assert_paths_safe,
    write_bundle_provenance,
    write_run_provenance,
)
from ohbm2026.exceptions import ProvenanceError


class AssertPathSafeTests(unittest.TestCase):
    def test_relative_paths_pass(self) -> None:
        assert_path_safe("data/outputs/analysis/voyage_abstract/communities__x/")
        assert_path_safe("data/cache/analysis/communities/abcdef.json")
        assert_path_safe(Path("data/inputs/neuroscape/cluster_table.csv"))

    def test_absolute_path_rejected(self) -> None:
        with self.assertRaises(ProvenanceError):
            assert_path_safe("/tmp/data/outputs/analysis/foo/")

    def test_home_relative_rejected(self) -> None:
        with self.assertRaises(ProvenanceError):
            assert_path_safe("~/data/outputs/analysis/foo/")

    def test_parent_escape_rejected(self) -> None:
        with self.assertRaises(ProvenanceError):
            assert_path_safe("../outside/foo")
        with self.assertRaises(ProvenanceError):
            assert_path_safe("..")

    def test_empty_rejected(self) -> None:
        with self.assertRaises(ProvenanceError):
            assert_path_safe("")

    def test_assert_paths_safe_iterates(self) -> None:
        assert_paths_safe(["data/x", "data/y"])
        with self.assertRaises(ProvenanceError):
            assert_paths_safe(["data/x", "/tmp/y"])


class WriteBundleProvenanceTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "kind": "communities",
            "bundle_path": "data/outputs/analysis/voyage_abstract/communities__abc/",
            "corpus_state_key": "f0c51e80dc0e",
            "input_source_assembly_hash": "abc123",
            "algorithm_config_canonical_json": "{}",
            "cache_key": "sha256:deadbeef",
            "code_revision": "0" * 40,
            "command": "ohbmcli analyze-matrix",
            "seed": 42,
            "started_at": "2026-05-14T00:00:00Z",
            "completed_at": "2026-05-14T00:00:01Z",
        }

    def test_atomic_write_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "communities__abc" / "provenance.json"
            payload = self._payload()
            write_bundle_provenance(out, payload)
            self.assertTrue(out.exists())
            read = json.loads(out.read_text())
            self.assertEqual(read["bundle_path"], payload["bundle_path"])

    def test_missing_required_field_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "p.json"
            bad = self._payload()
            del bad["cache_key"]
            with self.assertRaises(ProvenanceError):
                write_bundle_provenance(out, bad)

    def test_absolute_bundle_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "p.json"
            bad = self._payload()
            bad["bundle_path"] = "/tmp/data/outputs/analysis/foo/"
            with self.assertRaises(ProvenanceError):
                write_bundle_provenance(out, bad)


class WriteRunProvenanceTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "schema_version": "stage4.provenance.v1",
            "stage": "analysis",
            "run_state_key": "deadbeef0001",
            "corpus_state_key": "f0c51e80dc0e",
            "requested_models": ["voyage"],
            "requested_inputs": ["abstract"],
            "requested_kinds": ["projections"],
            "seed": 42,
            "skip_llm_topics": False,
            "strict_matrix": False,
            "command_line": "ohbmcli analyze-matrix --models voyage --inputs abstract --kinds projections",
            "code_revision": "0" * 40,
            "started_at": "2026-05-14T00:00:00Z",
            "completed_at": "2026-05-14T00:30:00Z",
            "wall_clock_seconds": 1800,
            "cache_root": "data/cache/analysis",
            "rollup_path": "data/outputs/analysis/annotations__f0c51e80dc0e.parquet",
            "bundles": [
                {
                    "bundle_path": "data/outputs/analysis/voyage_abstract/projections__abc/",
                    "kind": "projections",
                    "cache": "miss",
                }
            ],
        }

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run.json"
            write_run_provenance(out, self._payload())
            read = json.loads(out.read_text())
            self.assertEqual(read["run_state_key"], "deadbeef0001")
            self.assertEqual(len(read["bundles"]), 1)

    def test_rollup_absolute_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = self._payload()
            bad["rollup_path"] = "/abs/path/annotations.parquet"
            with self.assertRaises(ProvenanceError):
                write_run_provenance(Path(tmp) / "run.json", bad)

    def test_bundle_entry_absolute_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = self._payload()
            bad["bundles"][0]["bundle_path"] = "/abs/data/outputs/analysis/x/"
            with self.assertRaises(ProvenanceError):
                write_run_provenance(Path(tmp) / "run.json", bad)


if __name__ == "__main__":
    unittest.main()
