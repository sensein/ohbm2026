"""Tests for the embedded ECO v1 controlled vocabulary.

Validates the file at `src/ohbm2026/data/eco_top_codes.json` against
the contract schema at
`specs/004-enrich-production-wiring/contracts/eco_top_codes.schema.json`.

We do the validation with stdlib `re` checks rather than pulling in
a `jsonschema` dependency — the schema is small enough that
hand-walking it is cheaper than a new dep.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


_VOCAB_PATH = Path(__file__).resolve().parents[1] / "src" / "ohbm2026" / "data" / "eco_top_codes.json"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "specs"
    / "004-enrich-production-wiring"
    / "contracts"
    / "eco_top_codes.schema.json"
)


class ECOVocabularyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vocab = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
        self.schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_vocabulary_file_validates_against_schema(self) -> None:
        # Walk the schema's top-level constraints.
        for required in self.schema["required"]:
            self.assertIn(required, self.vocab, f"missing required field {required!r}")
        self.assertEqual(
            self.vocab["vocabulary_version"],
            self.schema["properties"]["vocabulary_version"]["const"],
        )
        self.assertEqual(
            self.vocab["parent_term"],
            self.schema["properties"]["parent_term"]["const"],
        )
        # source MUST be https://
        self.assertRegex(self.vocab["source"], self.schema["properties"]["source"]["pattern"])
        # fetched_at MUST be ISO-8601 — coarse check: parses as date-like.
        self.assertRegex(
            self.vocab["fetched_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
        )

    def test_vocabulary_has_nine_codes(self) -> None:
        codes = self.vocab["codes"]
        items = self.schema["properties"]["codes"]
        self.assertEqual(len(codes), items["minItems"])
        self.assertEqual(len(codes), items["maxItems"])
        self.assertEqual(len(codes), 9)

    def test_every_eco_id_matches_expected_pattern(self) -> None:
        eco_id_pattern = self.schema["properties"]["codes"]["items"]["properties"]["eco_id"]["pattern"]
        seen_ids = set()
        for entry in self.vocab["codes"]:
            self.assertRegex(entry["eco_id"], eco_id_pattern)
            self.assertGreater(len(entry["label"]), 0)
            self.assertGreater(len(entry["definition"]), 0)
            self.assertNotIn(entry["eco_id"], seen_ids, "duplicate eco_id")
            seen_ids.add(entry["eco_id"])
        # All 9 documented codes are present.
        expected_ids = {
            "ECO:0000006", "ECO:0000041", "ECO:0000212",
            "ECO:0000352", "ECO:0000361", "ECO:0000501",
            "ECO:0006055", "ECO:0006151", "ECO:0007672",
        }
        self.assertEqual(seen_ids, expected_ids)


if __name__ == "__main__":
    unittest.main()
