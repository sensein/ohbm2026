"""Stage 15 — byte-identity gate for the ``data.parquet → ohbm2026.parquet`` rename.

Spec: ``specs/015-neuroscape-context/`` — FR-022 + SC-008 + research
R-010. The rename is a pure cosmetic / namespacing change in the
Stage-10 single-file Parquet emitter: the literal output filename
flips from ``data.parquet`` to ``ohbm2026.parquet`` while the bytes
inside the file are unchanged for the same input envelope.

This module enforces the byte-identity property at the Python level:

- The module-level :data:`ohbm2026.ui_data.formats.parquet_single.DEFAULT_OUTPUT_FILENAME`
  constant equals the new name.
- A real ``build_ui_data_package`` run with the parquet-single emitter
  produces a file at the new path (``<out>/ohbm2026.parquet``) and NOT
  at the legacy path.
- Two back-to-back builds with pinned ``build_info`` produce a
  byte-identical parquet (sha256 match). This matches the existing
  ``TestDeterministicBuild`` invariant for the JSON-shards format but
  for the parquet-single emitter — confirming the rename did not
  accidentally introduce nondeterminism.

The browser-tree-level byte-identity gate (CI diff on the
``SITE_MODE=ohbm2026`` build) is owned by T037 / T050 and lives in
the deploy workflow; this Python module covers the data-package half.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.ui_data.builder import build_ui_data_package
from ohbm2026.ui_data.formats import parquet_single

from tests._ui_data_fixtures import BUILD_INFO, write_fixtures


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DefaultOutputFilenameConstantTests(unittest.TestCase):
    def test_default_output_filename_is_ohbm2026_parquet(self) -> None:
        self.assertEqual(
            parquet_single.DEFAULT_OUTPUT_FILENAME,
            "ohbm2026.parquet",
            msg=(
                "Stage 15 renamed the single-file parquet output from "
                "data.parquet to ohbm2026.parquet (spec 015 FR-022). "
                "Update the module constant if this changes."
            ),
        )

    def test_legacy_name_is_not_re_used(self) -> None:
        self.assertNotEqual(parquet_single.DEFAULT_OUTPUT_FILENAME, "data.parquet")


class ParquetSingleEmitterPathTests(unittest.TestCase):
    def test_emit_lands_at_new_filename(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp) / "inputs")
            output = Path(tmp) / "build" / "data"
            rc = build_ui_data_package(
                corpus_path=paths["corpus"],
                withdrawn_path=paths["withdrawn"],
                authors_path=paths["authors"],
                enriched_path=None,
                references_path=None,
                analysis_root=None,
                rollup=paths["rollup"],
                discover_rollup=False,
                output_dir=output,
                build_info=BUILD_INFO,
                output_format="parquet-single",
            )
            self.assertEqual(rc, 0)
            self.assertTrue(
                (output / "ohbm2026.parquet").exists(),
                msg="The Stage-15 rename did not produce ohbm2026.parquet.",
            )
            self.assertFalse(
                (output / "data.parquet").exists(),
                msg="The legacy data.parquet should not be emitted after the rename.",
            )


class ParquetSingleEmitterByteIdentityTests(unittest.TestCase):
    """SC-008 enforcement — two builds with pinned build_info produce
    byte-identical parquet bytes for the same input envelope."""

    def test_two_runs_produce_byte_identical_parquet(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp) / "inputs")
            out1 = Path(tmp) / "build1" / "data"
            out2 = Path(tmp) / "build2" / "data"
            for output in (out1, out2):
                rc = build_ui_data_package(
                    corpus_path=paths["corpus"],
                    withdrawn_path=paths["withdrawn"],
                    authors_path=paths["authors"],
                    enriched_path=None,
                    references_path=None,
                    analysis_root=None,
                    rollup=paths["rollup"],
                    discover_rollup=False,
                    output_dir=output,
                    build_info=BUILD_INFO,
                    output_format="parquet-single",
                )
                self.assertEqual(rc, 0)
            sha1 = _sha256(out1 / "ohbm2026.parquet")
            sha2 = _sha256(out2 / "ohbm2026.parquet")
            self.assertEqual(
                sha1,
                sha2,
                msg=(
                    "parquet-single emitter is not deterministic — Stage 15's "
                    "byte-identity guarantee (FR-022 + SC-008) is broken."
                ),
            )


if __name__ == "__main__":
    unittest.main()
