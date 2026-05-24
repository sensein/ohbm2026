"""Tests for Stage 15's typed exception hierarchy.

Spec: ``specs/015-neuroscape-context/`` — research R-009 + contract
``contracts/cli-build-atlas-package.md``. Mirrors the Stage 3 pattern
(``tests/test_stage3_exceptions.py``) so the Stage 15 import surface
stays auditable.

The Stage 15 subtree extends ``OhbmStageError`` with one base
(``Stage15Error``) and six concrete error classes. Each concrete
class carries structured kwargs so the orchestrator and tests can
inspect failure context without regex-matching message strings.
"""

from __future__ import annotations

import unittest

from ohbm2026 import exceptions


class Stage15ExceptionTreeTests(unittest.TestCase):
    def test_stage15_base_is_a_runtimeerror(self) -> None:
        self.assertTrue(issubclass(exceptions.Stage15Error, exceptions.OhbmStageError))
        self.assertTrue(issubclass(exceptions.Stage15Error, RuntimeError))

    def test_concrete_classes_subclass_stage15(self) -> None:
        for cls in (
            exceptions.NeuroScapeInputError,
            exceptions.UmapFitError,
            exceptions.OhbmProjectionError,
            exceptions.CrossParquetDriftError,
            exceptions.AtlasLinkCheckError,
        ):
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, exceptions.Stage15Error))

    def test_atlas_provenance_error_subclasses_existing_provenance(self) -> None:
        # AtlasProvenanceError reuses the shared ProvenanceError
        # contract (Stage 1 + Stage 2 + Stage 15 all enforce the
        # no-absolute / no-$HOME path rule per CA-008).
        self.assertTrue(
            issubclass(exceptions.AtlasProvenanceError, exceptions.ProvenanceError)
        )
        # …and is still recognisable as a Stage-15 failure for blast-
        # radius scoping.
        self.assertTrue(
            issubclass(exceptions.AtlasProvenanceError, exceptions.Stage15Error)
        )

    def test_all_public_names_exported(self) -> None:
        expected = {
            "Stage15Error",
            "NeuroScapeInputError",
            "UmapFitError",
            "OhbmProjectionError",
            "CrossParquetDriftError",
            "AtlasProvenanceError",
            "AtlasLinkCheckError",
        }
        self.assertTrue(expected.issubset(set(exceptions.__all__)))


class NeuroScapeInputErrorContextTests(unittest.TestCase):
    def test_carries_file_and_sha_kwargs(self) -> None:
        err = exceptions.NeuroScapeInputError(
            "input drift",
            file="neuroscience_articles_1999-2023.csv",
            expected="abc123",
            actual="def456",
        )
        self.assertEqual(err.file, "neuroscience_articles_1999-2023.csv")
        self.assertEqual(err.expected, "abc123")
        self.assertEqual(err.actual, "def456")


class UmapFitErrorContextTests(unittest.TestCase):
    def test_carries_reason_and_n_vectors_kwargs(self) -> None:
        err = exceptions.UmapFitError("nan in input", reason="nan_input", n_vectors=600_000)
        self.assertEqual(err.reason, "nan_input")
        self.assertEqual(err.n_vectors, 600_000)


class OhbmProjectionErrorAggregationTests(unittest.TestCase):
    def test_carries_failed_submission_ids(self) -> None:
        ids = [101, 202, 303]
        err = exceptions.OhbmProjectionError(
            "3 abstracts failed to project",
            failed_submission_ids=ids,
        )
        self.assertEqual(err.failed_submission_ids, ids)


class CrossParquetDriftErrorContextTests(unittest.TestCase):
    def test_carries_parquet_field_expected_actual(self) -> None:
        err = exceptions.CrossParquetDriftError(
            "ohbm2026 state-key drift",
            parquet="atlas.parquet",
            field="sibling_state_keys.ohbm2026",
            expected="aaa111",
            actual="bbb222",
        )
        self.assertEqual(err.parquet, "atlas.parquet")
        self.assertEqual(err.field, "sibling_state_keys.ohbm2026")
        self.assertEqual(err.expected, "aaa111")
        self.assertEqual(err.actual, "bbb222")


class AtlasLinkCheckErrorContextTests(unittest.TestCase):
    def test_carries_failing_url_status(self) -> None:
        err = exceptions.AtlasLinkCheckError(
            "404 on NeuroScape Zenodo URL",
            url="https://zenodo.org/records/0",
            status=404,
        )
        self.assertEqual(err.url, "https://zenodo.org/records/0")
        self.assertEqual(err.status, 404)


class AtlasProvenanceErrorContextTests(unittest.TestCase):
    def test_carries_offending_path_kwargs(self) -> None:
        err = exceptions.AtlasProvenanceError(
            "absolute path in provenance",
            field="inputs.ohbm2026_parquet",
            expected="<repo-relative>",
            actual="/Users/op/abs.parquet",
        )
        self.assertEqual(err.field, "inputs.ohbm2026_parquet")
        self.assertEqual(err.expected, "<repo-relative>")
        self.assertEqual(err.actual, "/Users/op/abs.parquet")


if __name__ == "__main__":
    unittest.main()
