"""Tests for `src/ohbm2026/stage2_references.py`.

Smoke tests for the thin adapter to openalex.collect_reference_metadata.
"""

from __future__ import annotations

import unittest

from ohbm2026 import stage2_references
from ohbm2026.exceptions import EnrichmentError


def _abstract_with_refs(refs: list[str]) -> dict:
    return {
        "id": 1,
        "responses": [
            {"question_name": "References", "value": "\n".join(refs)},
        ],
    }


class ReferencesWireUpTests(unittest.TestCase):
    def test_run_references_component_invokes_resolver(self) -> None:
        called_with = {}

        def resolver(reference_text: str, strategy_id: str):
            called_with["reference_text"] = reference_text
            called_with["strategy_id"] = strategy_id
            return [
                {"raw_reference": "ref1", "doi": "10.1/x", "title": "T1",
                 "resolution_status": "resolved", "resolution_source": "doi"},
                {"raw_reference": "ref2", "doi": None, "title": None,
                 "resolution_status": "unresolved", "resolution_source": None},
            ]

        abstract = _abstract_with_refs(["ref1", "ref2"])
        records, summary = stage2_references.run_references_component(
            abstract, strategy_id="refs.v1+test", resolver=resolver,
        )
        self.assertEqual(called_with["strategy_id"], "refs.v1+test")
        self.assertEqual(summary.reference_count, 2)
        self.assertEqual(summary.resolved_count, 1)
        self.assertEqual(summary.unresolved_count, 1)
        # cache_key is set on every record.
        for record in records:
            self.assertTrue(record["cache_key"])

    def test_cache_key_includes_strategy_id(self) -> None:
        resolver = lambda reference_text, strategy_id: []
        abstract = _abstract_with_refs(["ref-alpha"])
        records1, _ = stage2_references.run_references_component(
            abstract, strategy_id="v1", resolver=resolver,
        )
        records2, _ = stage2_references.run_references_component(
            abstract, strategy_id="v2", resolver=resolver,
        )
        # Resolver returned empty; no records produced. Verify the
        # internal cache-key helper:
        from ohbm2026.stage2_references import _cache_key
        self.assertNotEqual(_cache_key("ref-alpha", "v1"), _cache_key("ref-alpha", "v2"))

    def test_empty_references_block_returns_empty(self) -> None:
        abstract = {"id": 1, "responses": []}
        records, summary = stage2_references.run_references_component(
            abstract, strategy_id="v1", resolver=lambda *a, **kw: [],
        )
        self.assertEqual(records, [])
        self.assertEqual(summary.reference_count, 0)

    def test_resolver_exception_raises_typed_error(self) -> None:
        def failing_resolver(reference_text, strategy_id):
            raise RuntimeError("openalex down")
        abstract = _abstract_with_refs(["r"])
        with self.assertRaises(EnrichmentError):
            stage2_references.run_references_component(
                abstract, strategy_id="v1", resolver=failing_resolver,
            )

    def test_unknown_resolution_status_coerced_to_enum(self) -> None:
        resolver = lambda reference_text, strategy_id: [
            {"raw_reference": "r1", "resolution_status": "weird-status"},
        ]
        abstract = _abstract_with_refs(["r1"])
        records, _ = stage2_references.run_references_component(
            abstract, strategy_id="v1", resolver=resolver,
        )
        self.assertEqual(records[0]["resolution_status"], "partial")


if __name__ == "__main__":
    unittest.main()
