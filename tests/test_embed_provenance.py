"""Tests for `src/ohbm2026/embed_provenance.py`.

Two contracts to enforce:
1. Valid payloads write and round-trip.
2. Unsafe paths (absolute, `~`-prefixed) raise ProvenanceError.
3. Missing required fields raise ProvenanceError.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ohbm2026 import embed_provenance
from ohbm2026.exceptions import ProvenanceError


def _good_payload(**overrides) -> dict:
    base = {
        "schema_version": embed_provenance.PROVENANCE_SCHEMA_VERSION,
        "state_key": "abcdef012345",
        "corpus_state_key": "f0c51e80dc0e",
        "corpus_source_path": "data/primary/abstracts_enriched.sqlite",
        "corpus_source_hash": "0" * 64,
        "command_line": "ohbmcli embed-matrix --models minilm --components title",
        "code_revision": "1234567",
        "seed": None,
        "started_at": "2026-05-14T00:00:00Z",
        "completed_at": "2026-05-14T00:01:00Z",
        "wall_clock_seconds": 60.0,
        "cache_version": "embed.matrix.v1",
        "cache_root": "data/cache/embeddings",
        "failure_threshold": 0.01,
        "batch_size": 64,
        "concurrency_policy": "dynamic_start_8_min_1_max_24",
        "env_vars_consulted": ["OPENAI_API_KEY", "VOYAGE_API_KEY"],
        "bundles": [
            {
                "bundle_path": "data/outputs/experiments/embeddings/minilm_title",
                "model_key": "minilm",
                "model_id": "sentence-transformers/all-MiniLM-L6-v2",
                "model_version": "2.7.0",
                "component": "title",
                "present_count": 3244,
                "failure_count": 0,
                "truncated_count": 0,
                "cache_hit_count": 3244,
                "cache_miss_count": 0,
                "wall_clock_seconds": 0.5,
            }
        ],
    }
    base.update(overrides)
    return base


class _Tmp:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)

    def cleanup(self):
        self.dir.cleanup()


class WriteRunProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Tmp()
        self.addCleanup(self.fx.cleanup)

    def test_valid_payload_writes_and_roundtrips(self) -> None:
        out_path = self.fx.path / "prov.json"
        embed_provenance.write_run_provenance(out_path, _good_payload())
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["schema_version"], "stage3.provenance.v1")
        self.assertEqual(len(loaded["bundles"]), 1)

    def test_absolute_corpus_path_raises(self) -> None:
        with self.assertRaises(ProvenanceError):
            embed_provenance.write_run_provenance(
                self.fx.path / "prov.json",
                _good_payload(corpus_source_path="/abs/path/abstracts.sqlite"),
            )

    def test_tilde_cache_root_raises(self) -> None:
        with self.assertRaises(ProvenanceError):
            embed_provenance.write_run_provenance(
                self.fx.path / "prov.json",
                _good_payload(cache_root="~/data/cache/embeddings"),
            )

    def test_absolute_bundle_path_raises(self) -> None:
        payload = _good_payload()
        payload["bundles"][0]["bundle_path"] = "/abs/embeddings/minilm_title"
        with self.assertRaises(ProvenanceError):
            embed_provenance.write_run_provenance(self.fx.path / "prov.json", payload)

    def test_missing_required_field_raises(self) -> None:
        payload = _good_payload()
        del payload["state_key"]
        with self.assertRaises(ProvenanceError):
            embed_provenance.write_run_provenance(self.fx.path / "prov.json", payload)


if __name__ == "__main__":
    unittest.main()
