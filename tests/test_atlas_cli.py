"""Tests for ``ohbm2026.atlas_package.cli``.

Spec: ``specs/015-neuroscape-context/`` —
``contracts/cli-build-atlas-package.md``.

These tests exercise the argparse surface + the exit-code mapping
without invoking the full orchestrator (which would need a voyage
bundle + ohbm2026.parquet fixture). The integration with the real
release lands at T033 (operator runbook).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ohbm2026 import exceptions
from ohbm2026.atlas_package import cli as atlas_cli


class BuildParserTests(unittest.TestCase):
    def test_parser_has_documented_flags(self) -> None:
        parser = atlas_cli.build_parser()
        # Resolve actions by their `dest` so we don't rely on flag
        # ordering inside argparse.
        dests = {action.dest for action in parser._actions}
        for flag_dest in (
            "neuroscape_source",
            "voyage_bundle",
            "ohbm2026_parquet",
            "output_root",
            "umap_cache_root",
            "knn_cache_root",
            "projection_cache_root",
            "lod_resolutions",
            "neighbors_k",
            "link_check_rate",
            "ncbi_api_key_env",
            "force_rebuild",
            "no_link_check",
        ):
            self.assertIn(flag_dest, dests, msg=f"missing flag: {flag_dest}")

    def test_default_values_match_contract(self) -> None:
        parser = atlas_cli.build_parser()
        args = parser.parse_args(
            [
                "--neuroscape-source",
                "x",
                "--ohbm2026-parquet",
                "y",
                "--output-root",
                "z",
            ]
        )
        self.assertEqual(args.voyage_bundle, "voyage_stage2_published")
        self.assertEqual(args.lod_resolutions, "24,48,96,192,384")
        self.assertEqual(args.neighbors_k, 20)
        self.assertAlmostEqual(args.link_check_rate, 3.0)
        self.assertEqual(args.ncbi_api_key_env, "NCBI_API_KEY")
        self.assertFalse(args.no_link_check)
        self.assertIsNone(args.force_rebuild)
        self.assertEqual(args.umap_cache_root, Path("data/cache/atlas-umap"))
        self.assertEqual(args.knn_cache_root, Path("data/cache/atlas-knn"))
        self.assertEqual(
            args.projection_cache_root, Path("data/cache/atlas-projection")
        )


class MainExitCodeMappingTests(unittest.TestCase):
    """The CLI MUST map typed exceptions to the documented exit codes
    per ``contracts/cli-build-atlas-package.md``."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.argv = [
            "--neuroscape-source",
            str(Path(self._tmp.name) / "ns"),
            "--ohbm2026-parquet",
            str(Path(self._tmp.name) / "ohbm.parquet"),
            "--output-root",
            str(Path(self._tmp.name) / "out"),
        ]

    def _patch_load(self, exc: Exception):
        return patch.object(atlas_cli, "load_ohbm_corpus", side_effect=exc)

    def test_neuroscape_input_error_maps_to_2(self) -> None:
        with self._patch_load(exceptions.NeuroScapeInputError("missing")):
            self.assertEqual(atlas_cli.main(self.argv), 2)

    def test_umap_fit_error_maps_to_3(self) -> None:
        with self._patch_load(exceptions.UmapFitError("nan")):
            self.assertEqual(atlas_cli.main(self.argv), 3)

    def test_ohbm_projection_error_maps_to_4(self) -> None:
        with self._patch_load(exceptions.OhbmProjectionError("failed")):
            self.assertEqual(atlas_cli.main(self.argv), 4)

    def test_cross_parquet_drift_error_maps_to_5(self) -> None:
        with self._patch_load(exceptions.CrossParquetDriftError("drift")):
            self.assertEqual(atlas_cli.main(self.argv), 5)

    def test_atlas_provenance_error_maps_to_6(self) -> None:
        with self._patch_load(exceptions.AtlasProvenanceError("path")):
            self.assertEqual(atlas_cli.main(self.argv), 6)

    def test_atlas_link_check_error_maps_to_7(self) -> None:
        with self._patch_load(exceptions.AtlasLinkCheckError("404")):
            self.assertEqual(atlas_cli.main(self.argv), 7)


class MainHappyPathTests(unittest.TestCase):
    """When the orchestrator returns, the CLI writes provenance and
    returns 0."""

    def test_writes_provenance_to_documented_path(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "data" / "provenance").mkdir(parents=True, exist_ok=True)
            argv = [
                "--neuroscape-source",
                str(tmp_path / "ns"),
                "--ohbm2026-parquet",
                str(tmp_path / "ohbm.parquet"),
                "--output-root",
                str(tmp_path / "out"),
            ]
            with patch.object(
                atlas_cli,
                "load_ohbm_corpus",
                return_value=([], "ohbm12345678"),
            ), patch.object(
                atlas_cli,
                "build_atlas_package",
                return_value={"state_key": "atlas1234abcd", "schema_version": "neuroscape_context_provenance.v1"},
            ), patch("pathlib.Path.cwd", return_value=tmp_path):
                rc = atlas_cli.main(argv)
            self.assertEqual(rc, 0)
            prov_path = tmp_path / "data" / "provenance" / "neuroscape_context_provenance__atlas1234abcd.json"
            self.assertTrue(prov_path.exists(), msg=f"provenance not at {prov_path}")
            decoded = json.loads(prov_path.read_text())
            self.assertEqual(decoded["state_key"], "atlas1234abcd")


class NoLinkCheckCIGuardTests(unittest.TestCase):
    def test_no_link_check_refused_under_ci(self) -> None:
        argv = [
            "--neuroscape-source",
            "x",
            "--ohbm2026-parquet",
            "y",
            "--output-root",
            "z",
            "--no-link-check",
        ]
        with patch.dict("os.environ", {"CI": "true"}, clear=False):
            self.assertEqual(atlas_cli.main(argv), 7)

    def test_no_link_check_allowed_outside_ci(self) -> None:
        # Outside CI the flag is honoured (but we still don't actually
        # run the orchestrator — patch it out).
        argv = [
            "--neuroscape-source",
            "x",
            "--ohbm2026-parquet",
            "y",
            "--output-root",
            "z",
            "--no-link-check",
        ]
        with patch.dict("os.environ", {}, clear=True), patch.object(
            atlas_cli,
            "load_ohbm_corpus",
            return_value=([], "ohbm12345678"),
        ), patch.object(
            atlas_cli,
            "build_atlas_package",
            return_value={"state_key": "atlas1234abcd", "schema_version": "neuroscape_context_provenance.v1"},
        ):
            # Use a tempdir for the provenance write.
            with TemporaryDirectory() as tmp:
                with patch("pathlib.Path.cwd", return_value=Path(tmp)):
                    rc = atlas_cli.main(argv)
                self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
