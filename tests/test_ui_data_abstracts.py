"""T009 — abstracts builder accepted-only invariant tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.ui_data.abstracts import build_abstracts, build_abstracts_records

from tests._ui_data_fixtures import BUILD_INFO, write_fixtures


class TestAcceptedOnlyInvariant(unittest.TestCase):
    def test_no_withdrawn_records_leak(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            records = build_abstracts_records(
                corpus_path=paths["corpus"],
                enriched_path=None,
                references_path=None,
                withdrawn_path=paths["withdrawn"],
            )
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["accepted_for"] != "Withdrawn" for r in records))
        self.assertNotIn(1002, {r["abstract_id"] for r in records})

    def test_envelope_carries_build_info(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            envelope = build_abstracts(
                corpus_path=paths["corpus"],
                enriched_path=None,
                references_path=None,
                withdrawn_path=paths["withdrawn"],
                build_info=BUILD_INFO,
            )
        self.assertEqual(envelope["schema_version"], "abstracts.v1")
        self.assertEqual(envelope["build_info"], BUILD_INFO)
        self.assertIsInstance(envelope["abstracts"], list)

    def test_poster_id_emitted_not_submission_id(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            records = build_abstracts_records(
                corpus_path=paths["corpus"],
                enriched_path=None,
                references_path=None,
                withdrawn_path=paths["withdrawn"],
            )
        poster_ids = {r["poster_id"] for r in records}
        self.assertIn("M-AM-101", poster_ids)
        for r in records:
            self.assertNotIn("submission_id", r)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
