"""End-to-end test for :func:`ohbm2026.atlas_package.orchestrator.build_atlas_package`.

Spec: ``specs/015-neuroscape-context/`` — T020 + R-005 + SC-004.

Drives the entire Stage-15 build against the synthetic 6-article
fixture (:mod:`tests._atlas_fixtures`) and a hand-built 4-record
OHBM 2026 corpus. The test verifies that a single
``build_atlas_package`` call produces:

- ``neuroscape.parquet`` + ``atlas.parquet`` at the documented paths
- a provenance dict matching the contract schema
- byte-identical parquet bytes when invoked a second time with the
  same config (the rebuild-idempotency property — SC-004 +
  R-005).

The link check is skipped via ``cfg.skip_link_check=True`` so the
test runs hermetically (no real network).
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ohbm2026.atlas_package import orchestrator, umap_fit

from tests._atlas_fixtures import write_v101_fixture


def _ohbm_record(submission_id: int, poster_id: int, seed: int) -> orchestrator.OhbmInputRecord:
    rng = np.random.default_rng(seed=seed)
    v = rng.standard_normal(64).astype(np.float32)
    v /= max(float(np.linalg.norm(v)), 1.0)
    return orchestrator.OhbmInputRecord(
        submission_id=submission_id,
        poster_id=poster_id,
        title=f"OHBM 2026 abstract {submission_id}",
        stage2_vector=v,
    )


def _build_config(neuroscape_root: Path, output: Path, cache: Path) -> orchestrator.AtlasBuildConfig:
    return orchestrator.AtlasBuildConfig(
        neuroscape_source_root=neuroscape_root,
        ohbm_corpus=[
            _ohbm_record(1001, 201, seed=1001),
            _ohbm_record(1002, 202, seed=1002),
            _ohbm_record(1003, 203, seed=1003),
            _ohbm_record(1004, 204, seed=1004),
        ],
        ohbm2026_state_key="ohbm00000001",
        output_root=output,
        umap_cache_root=cache,
        decimated_backdrop_size=3,
        neighbors_k=3,
        # Synthetic fixture has 6 articles — production R-001 defaults
        # (n_neighbors=30) can't fit. Use small overrides; the
        # production defaults are exercised against the real release
        # at T033.
        umap_params_3d=umap_fit.UmapFitParams(n_components=3, n_neighbors=3),
        umap_params_2d=umap_fit.UmapFitParams(n_components=2, n_neighbors=3),
        primary_palette_size=32,
        skip_link_check=True,
        code_revision="testsha",
        # Pin the manifest timestamps so byte-identity holds across
        # consecutive rebuilds (SC-004). Production runs leave this
        # None so the manifest carries the real wall clock.
        pinned_built_at="2026-05-24T00:00:00Z",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OrchestratorEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_root = Path(self._tmp.name)
        self.ns_root = write_v101_fixture(self.tmp_root)

    def test_build_produces_two_parquets_plus_provenance(self) -> None:
        out = self.tmp_root / "out1"
        cache = self.tmp_root / "cache1"
        cfg = _build_config(self.ns_root, out, cache)
        prov = orchestrator.build_atlas_package(cfg)

        self.assertTrue((out / "neuroscape.parquet").exists())
        self.assertTrue((out / "atlas.parquet").exists())

        # Provenance schema check — every required top-level field
        # documented in contracts/cli-build-atlas-package.md.
        for key in (
            "schema_version",
            "state_key",
            "code_revision",
            "command_line",
            "seed",
            "started_utc",
            "finished_utc",
            "inputs",
            "umap_params",
            "ohbm_inclusion",
            "outputs",
            "link_check",
        ):
            self.assertIn(key, prov, msg=f"missing {key!r}")
        self.assertEqual(prov["schema_version"], "neuroscape_context_provenance.v1")
        # Repo-relative paths only (CA-008).
        for path_str in (
            prov["inputs"]["neuroscape_source_root"],
            prov["outputs"]["neuroscape_parquet"],
            prov["outputs"]["atlas_parquet"],
        ):
            self.assertFalse(path_str.startswith("/"), msg=path_str)
            self.assertFalse(path_str.startswith("~"), msg=path_str)

    def test_provenance_records_ohbm_inclusion_counts(self) -> None:
        out = self.tmp_root / "out2"
        cache = self.tmp_root / "cache2"
        cfg = _build_config(self.ns_root, out, cache)
        prov = orchestrator.build_atlas_package(cfg)
        self.assertEqual(prov["ohbm_inclusion"]["n_overlay_points"], 4)
        self.assertEqual(prov["ohbm_inclusion"]["n_omitted"], 0)
        self.assertEqual(prov["ohbm_inclusion"]["omitted_submission_ids"], [])

    def test_provenance_state_keys_chain_correctly(self) -> None:
        out = self.tmp_root / "out3"
        cache = self.tmp_root / "cache3"
        cfg = _build_config(self.ns_root, out, cache)
        prov = orchestrator.build_atlas_package(cfg)
        # The atlas state_key is derived from the OHBM + NeuroScape +
        # UMAP state keys; it MUST differ from any of its component
        # keys.
        atlas_sk = prov["outputs"]["atlas_state_key"]
        self.assertNotEqual(atlas_sk, prov["outputs"]["neuroscape_state_key"])
        self.assertNotEqual(atlas_sk, prov["outputs"]["ohbm2026_state_key"])

    def test_rebuild_is_idempotent_for_unchanged_inputs(self) -> None:
        """SC-004 — a second invocation with unchanged config produces
        byte-identical parquets. The provenance JSON has timestamps
        and thus diverges; the parquet contents are the contract."""

        out1 = self.tmp_root / "outA"
        out2 = self.tmp_root / "outB"
        cache = self.tmp_root / "cacheS"
        cfg1 = _build_config(self.ns_root, out1, cache)
        cfg2 = _build_config(self.ns_root, out2, cache)
        orchestrator.build_atlas_package(cfg1)
        orchestrator.build_atlas_package(cfg2)
        self.assertEqual(
            _sha256_file(out1 / "neuroscape.parquet"),
            _sha256_file(out2 / "neuroscape.parquet"),
        )
        self.assertEqual(
            _sha256_file(out1 / "atlas.parquet"),
            _sha256_file(out2 / "atlas.parquet"),
        )


if __name__ == "__main__":
    unittest.main()
