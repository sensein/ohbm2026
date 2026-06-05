"""Stage 23 — research-classification dimensions: distiller + slim loader.

Spec specs/023-atlas-research-dimensions/: a distiller reduces the bulky
``abstracts.detail.json`` to a slim ``dimensions.slim.json`` (id + 4 dimension
lists only), which the data-package build consumes via a left-join.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


# A tiny full-detail file matching the operator-supplied shape: keyed by
# submission-id string, each record carries the four dimensions plus noise.
FULL_PAYLOAD = {
    "abstracts": {
        "1001": {
            "id": 1001,
            "title": "noise that must be dropped",
            "figure_analyses": [{"big": "blob"}],
            "claim_extraction": ["lots", "of", "text"],
            "focus": ["Translational", "Clinical"],
            "research_modality": ["Observational", "Computational"],
            "theory_scope": ["Domain Framework"],
            "epistemic_basis": ["Data-driven"],
        },
        "1003": {
            "id": 1003,
            "title": "more noise",
            "focus": ["Fundamental"],
            "research_modality": ["Experimental"],
            "theory_scope": [],  # no value for this dimension
            "epistemic_basis": ["Hypothesis-driven"],
        },
        "1009": {
            "id": 1009,
            # all four empty → omitted from the slim file (no value anywhere)
            "focus": [],
            "research_modality": [],
            "theory_scope": [],
            "epistemic_basis": [],
        },
    }
}


class TestDistiller(unittest.TestCase):
    def test_slim_has_wrapper_and_only_four_lists(self) -> None:
        from ohbm2026.ui_data.dimensions import distill_dimensions

        with TemporaryDirectory() as tmp:
            full = Path(tmp) / "abstracts.detail.json"
            full.write_text(json.dumps(FULL_PAYLOAD))
            slim = Path(tmp) / "dimensions.slim.json"
            distill_dimensions(full, slim)

            payload = json.loads(slim.read_text())
            self.assertEqual(payload["schema_version"], "dimensions.slim.v1")
            dims = payload["dimensions"]
            # 1009 (all-empty) is omitted; 1001 + 1003 kept.
            self.assertEqual(set(dims), {"1001", "1003"})
            # No field other than the four dimension keys survives.
            self.assertEqual(
                set(dims["1001"]),
                {"focus", "research_modality", "theory_scope", "epistemic_basis"},
            )
            self.assertNotIn("title", dims["1001"])
            self.assertNotIn("figure_analyses", dims["1001"])
            self.assertEqual(dims["1001"]["focus"], ["Translational", "Clinical"])
            # An empty per-record dimension is preserved as [].
            self.assertEqual(dims["1003"]["theory_scope"], [])

    def test_distiller_is_deterministic(self) -> None:
        from ohbm2026.ui_data.dimensions import distill_dimensions

        with TemporaryDirectory() as tmp:
            full = Path(tmp) / "abstracts.detail.json"
            full.write_text(json.dumps(FULL_PAYLOAD))
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            distill_dimensions(full, a)
            distill_dimensions(full, b)
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_distiller_rejects_layout_mismatch(self) -> None:
        from ohbm2026.ui_data.dimensions import DimensionInputError, distill_dimensions

        with TemporaryDirectory() as tmp:
            slim = Path(tmp) / "out.json"
            # not an object with `abstracts`
            bad1 = Path(tmp) / "bad1.json"
            bad1.write_text(json.dumps([1, 2, 3]))
            with self.assertRaises(DimensionInputError):
                distill_dimensions(bad1, slim)

            # `abstracts` present but no record carries any dimension field
            bad2 = Path(tmp) / "bad2.json"
            bad2.write_text(json.dumps({"abstracts": {"1": {"id": 1, "title": "x"}}}))
            with self.assertRaises(DimensionInputError):
                distill_dimensions(bad2, slim)

    def test_distiller_raises_on_missing_file(self) -> None:
        from ohbm2026.ui_data.dimensions import DimensionInputError, distill_dimensions

        with TemporaryDirectory() as tmp:
            with self.assertRaises(DimensionInputError):
                distill_dimensions(Path(tmp) / "nope.json", Path(tmp) / "out.json")


class TestLoadSlim(unittest.TestCase):
    def test_load_returns_int_keyed_map(self) -> None:
        from ohbm2026.ui_data.dimensions import distill_dimensions, load_research_dimensions

        with TemporaryDirectory() as tmp:
            full = Path(tmp) / "abstracts.detail.json"
            full.write_text(json.dumps(FULL_PAYLOAD))
            slim = Path(tmp) / "dimensions.slim.json"
            distill_dimensions(full, slim)

            dims = load_research_dimensions(slim)
            self.assertEqual(set(dims), {1001, 1003})  # int keys, 1009 omitted
            self.assertEqual(dims[1001]["focus"], ["Translational", "Clinical"])
            self.assertEqual(dims[1003]["theory_scope"], [])
            self.assertEqual(set(dims[1001]), set(("focus", "research_modality", "theory_scope", "epistemic_basis")))

    def test_load_rejects_wrong_shape(self) -> None:
        from ohbm2026.ui_data.dimensions import DimensionInputError, load_research_dimensions

        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"not_dimensions": {}}))
            with self.assertRaises(DimensionInputError):
                load_research_dimensions(bad)


class TestCoverage(unittest.TestCase):
    """Stage 23 — compute_dimension_coverage (data-model §3 / D1 / D3)."""

    def test_matched_plus_no_value_equals_corpus_count(self) -> None:
        from ohbm2026.ui_data.dimensions import compute_dimension_coverage

        dims = {
            1001: {"focus": ["Clinical"], "research_modality": [], "theory_scope": ["X"], "epistemic_basis": ["Data-driven"]},
            1003: {"focus": [], "research_modality": ["Computational"], "theory_scope": [], "epistemic_basis": []},
            9999: {"focus": ["Clinical"], "research_modality": [], "theory_scope": [], "epistemic_basis": []},  # not exported
        }
        exported = [1001, 1003]
        cov = compute_dimension_coverage(dims, exported, source_file="dimensions.slim.json", source_sha256="ab" * 32)
        for key in ("focus", "research_modality", "theory_scope", "epistemic_basis"):
            d = cov["dimensions"][key]
            self.assertEqual(d["matched"] + d["no_value"], len(exported), key)  # D1
        self.assertEqual(cov["dimensions"]["focus"], {"matched": 1, "no_value": 1})
        self.assertEqual(cov["unmatched_in_file"], 1)  # 9999 (D3)
        self.assertEqual(cov["source_file"], "dimensions.slim.json")

    def test_non_list_value_rejected_on_load(self) -> None:
        from ohbm2026.ui_data.dimensions import DimensionInputError, load_research_dimensions

        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"schema_version": "dimensions.slim.v1",
                                       "dimensions": {"1": {"focus": "not-a-list"}}}))
            with self.assertRaises(DimensionInputError):
                load_research_dimensions(bad)


class TestParquetFacetsRoundTrip(unittest.TestCase):
    """Stage 23 — the four dimension lists round-trip through the abstracts
    STRUCT in the single-file parquet emitter."""

    def _facets(self, **overrides):
        base = {
            "keywords": [], "methods": [], "study_type": [], "population": [],
            "field_strength": [], "processing_packages": [], "species": [],
            "recording_technology": [], "brain_regions": [], "brain_networks": [],
            "accepted_for": [],
            "focus": [], "research_modality": [], "theory_scope": [], "epistemic_basis": [],
        }
        base.update(overrides)
        return base

    def test_facets_to_arrow_includes_four_dimensions(self) -> None:
        from ohbm2026.ui_data.formats.parquet_single import _facets_to_arrow

        out = _facets_to_arrow(self._facets(focus=["Clinical"], theory_scope=["Micro Theory"]))
        for key in ("focus", "research_modality", "theory_scope", "epistemic_basis"):
            self.assertIn(key, out)
        self.assertEqual(out["focus"], ["Clinical"])
        self.assertEqual(out["theory_scope"], ["Micro Theory"])
        self.assertEqual(out["research_modality"], [])

    def test_abstracts_table_round_trips_dimensions(self) -> None:
        from ohbm2026.ui_data.formats.parquet_single import _abstracts_to_table

        envelope = {
            "abstracts": [
                {
                    "poster_id": 101, "title": "t", "accepted_for": "Poster",
                    "sections": {}, "topics": {}, "methods_checklist": [],
                    "facets": self._facets(focus=["Translational", "Clinical"],
                                           epistemic_basis=["Data-driven"]),
                    "author_ids": [], "reference_dois": [], "reference_urls": [],
                    "reference_titles": [], "poster_standby": {},
                },
            ]
        }
        table = _abstracts_to_table(envelope, {})
        facets = table.column("facets").to_pylist()[0]
        self.assertEqual(facets["focus"], ["Translational", "Clinical"])
        self.assertEqual(facets["epistemic_basis"], ["Data-driven"])
        self.assertEqual(facets["theory_scope"], [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
